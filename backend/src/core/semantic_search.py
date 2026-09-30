"""X3 관념(의미) 유사도 검색 서비스 — 상표명 임베딩 캐시 + 순위 (phonetic_search.py 와 같은 구조).

흐름
- 기동: main.py lifespan 이 goods.load_all() 다음에 load_all() 을 부른다. 게시된 상표 메타의
  `상표한글명` 가운데 X3 `has_meaning` 이 True 인 레코드만 골라 임베딩 텍스트(embedding_text)를
  한 배치로 임베딩해(x3.embed_texts) 행렬로 둔다. 관념이 없는 레코드(조어·기호·도형)는 제외하고
  건수를 로그로 남긴다. file 모드는 engine.state.trademark_lookup, db 모드는 기동 시 1회
  SELECT(db.fetch_phonetic_rows — 같은 컬럼) 로 적재한다.
- `MARKLENS_X3_ENABLED=0` 이면 적재를 생략하고(모델 다운로드·RSS 약 1.2GB 회피) state.enabled=False,
  엔드포인트는 503 + 이유. 모델을 못 불러와도 서버는 뜨고 이 엔드포인트만 503 을 낸다(goods 와 같은
  방식). `MARKLENS_FAKE_ML` 이면 X3 의 가짜 임베더로 기동한다(테스트·CI).
- 요청: 입력을 has_meaning 으로 거르고(없으면 matches [] + note "관념 없음(조어)"), 임베딩 텍스트
  벡터와 캐시 행렬의 코사인을 한 번에 구해 X3 와 같은 기준선 c₀ 로 재보정 → min_score 이상만 →
  내림차순 → top_k(상한 5). 정규화 텍스트가 같은 레코드는 semantic_similarity 와 같이 1.0.
  X3 가 공개하는 함수만 쓴다(has_meaning·embedding_text·embed_text·embed_texts·current_baseline·
  embedder_name). 엔진이 재게시되면(load_token 변경) 다음 요청에서 캐시를 다시 만든다.
"""

import logging
import sys
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from . import config, engine, paths

# ml/src 를 import 경로에 둔다 (engine.py·phonetic_search.py 와 같은 패턴).
if str(paths.ML_ROOT) not in sys.path:
    sys.path.insert(0, str(paths.ML_ROOT))

from src.axes import x3_semantic as x3  # noqa: E402

logger = logging.getLogger(__name__)

AXIS = "X3"
NOTE = "관념(의미) 유사도만 반영한 참고 정보"
NOTE_NO_MEANING = "관념 없음(조어)"
TOP_K_MAX = 5  # 반환 상한(작업 명세)
TOP_K_DEFAULT = TOP_K_MAX
DISABLED_REASON = (
    "MARKLENS_X3_ENABLED=0 — 관념 유사도 검색이 꺼져 있습니다(기동 시 임베딩 캐시 생략)."
)


@dataclass(frozen=True)
class SemanticEntry:
    """임베딩 캐시 1건 — 응답 조립에 필요한 최소 필드와 임베딩 텍스트."""

    application_number: str
    name: str
    image_key: str | None
    applicant: str | None
    nice_classes: tuple[int, ...]
    text: str  # x3.embedding_text(name) — 행렬 행과 같은 순서


@dataclass
class SemanticState:
    entries: list[SemanticEntry] = field(default_factory=list)
    matrix: np.ndarray | None = None  # (n, dim) 단위 벡터, entries 와 같은 순서
    excluded_no_meaning: int = 0
    load_token: str = ""  # 캐시를 만든 시점의 engine.state.load_token
    ready: bool = False
    enabled: bool = True
    error: str = ""  # 준비 실패·비활성 이유 — 503 detail 과 로그에 쓴다
    model: str = ""
    load_ms: float = 0.0


@dataclass(frozen=True)
class SemanticMatch:
    rank: int
    score: float
    entry: SemanticEntry


@dataclass(frozen=True)
class SemanticSearchResult:
    query: str
    query_text: str
    has_meaning: bool
    matches: list[SemanticMatch]
    searched_count: int
    excluded_no_meaning: int
    top_k: int
    min_score: float
    model: str
    elapsed_ms: float


# 모듈 전역 캐시. main.py lifespan 이 load_all() 로 채운다.
state = SemanticState()
_load_lock = threading.Lock()


def _nice_classes(value: object) -> tuple[int, ...]:
    classes: list[int] = []
    for raw in value if isinstance(value, (list, tuple)) else []:
        text = str(raw).strip()
        if text.isdigit():
            classes.append(int(text))
    return tuple(classes)


def _source_records() -> list[dict]:
    """게시 모드별 상표 레코드(한글 키 dict) 목록 — phonetic_search 와 같은 소스."""
    if engine.state.storage_mode == "db":
        from . import db

        return db.fetch_phonetic_rows()
    return list(engine.state.trademark_lookup.values())


def reset() -> None:
    """테스트·재적재용: 캐시를 비운다(enabled 는 유지)."""
    state.entries = []
    state.matrix = None
    state.excluded_no_meaning = 0
    state.load_token = ""
    state.ready = False
    state.error = ""
    state.model = ""
    state.load_ms = 0.0


def load_all() -> SemanticState:
    """게시된 상표 메타로 임베딩 캐시를 만든다. 엔진이 준비된 뒤에만 호출한다.

    X3 비활성·모델 실패는 예외를 밖으로 내지 않는다 — 서버는 뜨고 /semantic-search 만 503.
    """
    if not config.X3_ENABLED:
        reset()
        state.enabled = False
        state.error = DISABLED_REASON
        logger.info("X3 관념 캐시 생략 — %s", DISABLED_REASON)
        return state
    if not engine.state.ready:
        raise RuntimeError("엔진이 준비되기 전에는 관념 캐시를 만들 수 없습니다.")
    started = time.perf_counter()
    entries: list[SemanticEntry] = []
    excluded = 0
    for record in _source_records():
        application_number = str(record.get("출원번호") or "").strip()
        if not application_number:
            continue
        name = str(record.get("상표한글명") or "").strip()
        if not name or not x3.has_meaning(name):
            excluded += 1
            continue
        entries.append(
            SemanticEntry(
                application_number=application_number,
                name=name,
                image_key=str(record.get("이미지파일") or "").strip() or None,
                applicant=str(record.get("출원인") or "").strip() or None,
                nice_classes=_nice_classes(record.get("류")),
                text=x3.embedding_text(name),
            )
        )
    entries.sort(key=lambda entry: entry.application_number)  # 결정적 순서(동점 정렬용)
    try:
        matrix = x3.embed_texts([entry.text for entry in entries])  # 한 배치 + 프로세스 캐시
        model = x3.embedder_name()
    except Exception:
        reset()
        state.enabled = True
        state.error = "관념 임베딩 모델을 불러오지 못했습니다(서버 로그 참조)."
        logger.exception("X3 관념 캐시 실패 — /semantic-search 는 503")
        return state
    state.entries = entries
    state.matrix = matrix
    state.excluded_no_meaning = excluded
    state.load_token = engine.state.load_token
    state.ready = True
    state.enabled = True
    state.error = ""
    state.model = model
    state.load_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "X3 관념 캐시 준비: %d건 (관념 없음 %d건 제외, 모델 %s, mode=%s, %.0fms)",
        len(entries),
        excluded,
        model,
        engine.state.storage_mode,
        state.load_ms,
    )
    return state


def _ensure_fresh() -> None:
    """엔진이 재게시됐거나 아직 캐시가 없으면 (락 안에서 1회) 다시 만든다."""
    if state.ready and state.load_token == engine.state.load_token:
        return
    with _load_lock:
        if state.ready and state.load_token == engine.state.load_token:
            return
        load_all()
        if not state.ready:
            raise RuntimeError(state.error or "관념 유사도 캐시가 준비되지 않았습니다.")


def _scores(query_vector: np.ndarray) -> np.ndarray:
    """캐시 행렬 전건의 재보정 점수 — X3 recalibrate 와 같은 식을 벡터로 계산한다."""
    assert state.matrix is not None
    cosine = np.nan_to_num(state.matrix @ query_vector, nan=0.0)
    baseline = x3.current_baseline()
    if baseline >= 1.0:
        return np.clip(cosine, 0.0, 1.0)
    return np.clip((cosine - baseline) / (1.0 - baseline), 0.0, 1.0)


def search(name: str, top_k: int, min_score: float) -> SemanticSearchResult:
    """입력 상표명과 캐시된 상표명의 X3 유사도 상위 top_k. 입력 정규화·게이트는 X3 에 맡긴다."""
    query = name.strip()
    if not query:
        raise ValueError("상표명이 비어 있습니다.")
    if not state.enabled:
        raise RuntimeError(state.error or DISABLED_REASON)
    _ensure_fresh()
    started = time.perf_counter()
    has_meaning = x3.has_meaning(query)
    query_text = x3.embedding_text(query) if has_meaning else ""
    matches: list[SemanticMatch] = []
    if has_meaning and state.entries:
        scores = _scores(x3.embed_text(query_text))
        scored: list[tuple[float, SemanticEntry]] = []
        for entry, score in zip(state.entries, scores.tolist()):
            value = 1.0 if entry.text == query_text else float(score)
            if value >= min_score:
                scored.append((value, entry))
        scored.sort(key=lambda item: (-item[0], item[1].application_number))
        matches = [
            SemanticMatch(rank=rank, score=score, entry=entry)
            for rank, (score, entry) in enumerate(scored[: min(top_k, TOP_K_MAX)], 1)
        ]
    return SemanticSearchResult(
        query=query,
        query_text=query_text,
        has_meaning=has_meaning,
        matches=matches,
        searched_count=len(state.entries),
        excluded_no_meaning=state.excluded_no_meaning,
        top_k=min(top_k, TOP_K_MAX),
        min_score=min_score,
        model=state.model,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )
