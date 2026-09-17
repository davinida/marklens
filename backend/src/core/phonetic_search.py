"""X1 호칭(발음) 유사도 검색 서비스 — 상표명 발음 후보 캐시 + 순위 (최소 통합).

흐름
- 기동: main.py lifespan 이 engine.load_all() 직후 load_all() 을 부른다. 게시된 상표 메타의
  `상표한글명` 가운데 X1 `has_pronunciation` 이 True 인 레코드만 골라 `pronunciation_candidates`
  를 미리 계산해 메모리에 둔다(출원번호 → 후보). 호칭이 없는 레코드(순수 도형·기호만)는 제외하고
  건수를 로그로 남긴다. file 모드는 engine.state.trademark_lookup, db 모드는 기동 시 1회
  SELECT(db.fetch_phonetic_rows) 로 적재한다.
- 요청: 입력 상표명과 캐시된 각 레코드의 `phonetic_similarity` 를 계산 → min_similarity 이상만
  → 내림차순 → top_k. X1 이 공개하는 세 함수만 쓴다(내부 함수·캐시 구조에 의존하지 않음).
  DB 쪽 발음 후보는 기동 시 계산으로 X1 내부 lru_cache 에 이미 올라가 있어 요청 시에는
  음절 유사도 단계만 반복된다(1,100건 기준 실측은 README·API 계약 참고).
- KIPRIS 키·네트워크와 무관한 로컬 CPU 계산이다. 엔진이 재게시되면(load_token 변경) 다음
  요청에서 캐시를 다시 만든다.
"""

import logging
import sys
import threading
import time
from dataclasses import dataclass, field

from . import engine, paths

# ml/src 를 import 경로에 둔다 (engine.py 와 같은 패턴). X1 은 torch·faiss 를 쓰지 않아 가볍다.
if str(paths.ML_ROOT) not in sys.path:
    sys.path.insert(0, str(paths.ML_ROOT))

from src.axes.x1_phonetic import (  # noqa: E402
    has_pronunciation,
    phonetic_similarity,
    pronunciation_candidates,
)

logger = logging.getLogger(__name__)

AXIS = "X1"
NOTE = "호칭(발음) 유사도만 반영한 참고 정보"


@dataclass(frozen=True)
class PhoneticEntry:
    """발음 캐시 1건 — 응답 조립에 필요한 최소 필드만 보관한다."""

    application_number: str
    name: str
    image_key: str | None
    applicant: str | None
    nice_classes: tuple[int, ...]
    candidates: tuple[str, ...]


@dataclass
class PhoneticState:
    entries: list[PhoneticEntry] = field(default_factory=list)
    excluded_no_pronunciation: int = 0
    load_token: str = ""  # 캐시를 만든 시점의 engine.state.load_token
    ready: bool = False


@dataclass(frozen=True)
class PhoneticMatch:
    rank: int
    similarity: float
    entry: PhoneticEntry


@dataclass(frozen=True)
class PhoneticSearchResult:
    query: str
    query_candidates: tuple[str, ...]
    matches: list[PhoneticMatch]
    searched_count: int
    excluded_no_pronunciation: int
    top_k: int
    min_similarity: float
    elapsed_ms: float


# 모듈 전역 캐시. main.py lifespan 이 load_all() 로 채운다.
state = PhoneticState()
_load_lock = threading.Lock()


def _nice_classes(value: object) -> tuple[int, ...]:
    classes: list[int] = []
    for raw in value if isinstance(value, (list, tuple)) else []:
        text = str(raw).strip()
        if text.isdigit():
            classes.append(int(text))
    return tuple(classes)


def _source_records() -> list[dict]:
    """게시 모드별 상표 레코드(한글 키 dict) 목록."""
    if engine.state.storage_mode == "db":
        from . import db

        return db.fetch_phonetic_rows()
    return list(engine.state.trademark_lookup.values())


def reset() -> None:
    """테스트·재적재용: 캐시를 비운다."""
    state.entries = []
    state.excluded_no_pronunciation = 0
    state.load_token = ""
    state.ready = False


def load_all() -> PhoneticState:
    """게시된 상표 메타로 발음 캐시를 만든다. 엔진이 준비된 뒤에만 호출한다."""
    if not engine.state.ready:
        raise RuntimeError("엔진이 준비되기 전에는 발음 캐시를 만들 수 없습니다.")
    started = time.perf_counter()
    entries: list[PhoneticEntry] = []
    excluded = 0
    for record in _source_records():
        application_number = str(record.get("출원번호") or "").strip()
        if not application_number:
            continue
        name = str(record.get("상표한글명") or "").strip()
        if not name or not has_pronunciation(name):
            excluded += 1
            continue
        entries.append(
            PhoneticEntry(
                application_number=application_number,
                name=name,
                image_key=str(record.get("이미지파일") or "").strip() or None,
                applicant=str(record.get("출원인") or "").strip() or None,
                nice_classes=_nice_classes(record.get("류")),
                candidates=tuple(pronunciation_candidates(name)),
            )
        )
    entries.sort(key=lambda entry: entry.application_number)  # 결정적 순서(동점 정렬용)
    state.entries = entries
    state.excluded_no_pronunciation = excluded
    state.load_token = engine.state.load_token
    state.ready = True
    logger.info(
        "X1 발음 캐시 준비: %d건 (호칭 없음 %d건 제외, mode=%s, %.0fms)",
        len(entries),
        excluded,
        engine.state.storage_mode,
        (time.perf_counter() - started) * 1000,
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


def search(name: str, top_k: int, min_similarity: float) -> PhoneticSearchResult:
    """입력 상표명과 캐시된 상표명의 X1 유사도 상위 top_k. 입력 정규화는 X1 에 맡긴다."""
    query = name.strip()
    if not query:
        raise ValueError("상표명이 비어 있습니다.")
    _ensure_fresh()
    started = time.perf_counter()
    query_candidates = tuple(pronunciation_candidates(query))
    matches: list[PhoneticMatch] = []
    if query_candidates:
        scored: list[tuple[float, PhoneticEntry]] = []
        for entry in state.entries:
            similarity = phonetic_similarity(query, entry.name)
            if similarity >= min_similarity:
                scored.append((similarity, entry))
        scored.sort(key=lambda item: (-item[0], item[1].application_number))
        matches = [
            PhoneticMatch(rank=rank, similarity=similarity, entry=entry)
            for rank, (similarity, entry) in enumerate(scored[:top_k], 1)
        ]
    return PhoneticSearchResult(
        query=query,
        query_candidates=query_candidates,
        matches=matches,
        searched_count=len(state.entries),
        excluded_no_pronunciation=state.excluded_no_pronunciation,
        top_k=top_k,
        min_similarity=min_similarity,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )
