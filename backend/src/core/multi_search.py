"""3입력 통합 검색 엔진 — API 계약 v2(docs/MarkLens_API계약_v2.md) §2 의 overall·candidates·meta 를
만든다. 엔진 몫 E-1~E-6 의 구현이며 `engine.multi_search()` 가 여기로 위임한다.
엔드포인트·BFF·화면은 다른 사람 몫.

흐름(계약 §1-3·§2-4)
    1. 입력 정리: name 은 NFKC·공백 정리(pair_axes.clean_name), goods_codes 는 대문자·중복 제거.
       셋 다 없으면 EmptyQueryError.
    2. 유형(2026-10-24 개정): type_override(user) → 이름이 있으면 항상 문자계(OCR fig_ratio 로
       문자 또는 결합-문자요부, OCR 실패도 문자) → 이름 없는 이미지는 도형계(글자 영역 ≥ 0.05 면
       결합-도형요부) + OCR 이 읽은 글자를 suggested_name 으로 제안(이 요청에서 이름 축은 계산하지
       않음) → OCR 실패는 fallback + caveat. 모델에는 이 한 유형을 쌍 전체에 쓴다(§2-4 1항).
    3. 후보 풀(E-1): CLIP 상위 20 ∪ 발음 상위 20 ∪ 철자 상위 20 ∪ 관념 상위 5(하한 X3_MIN_SCORE) ∪
    유사군
       겹침 상위 20(자카드 순). 출원번호로 중복 제거 → meta.pool.
    4. 쌍별 축(E-2, pair_axes.compute_pair_axes — 학습 pairs_features.name_axes 와 같은 식) +
    x2_img(질의
       임베딩 vs 후보 임베딩 코사인, **풀의 모든 후보**, 음수는 0) → risk_model.risk_score(E-5) →
       기여도를
       축별로 묶고(miss_* 는 missing_adjustment) 단독·도형 규칙 트리거를 적는다.
    5. 위험도 내림차순(동점은 x2_img 내림차순 → 출원번호 오름차순) → top_k. overall 은 반환 후보의
    최대
       등급·최대 p·caveat(§2-5 문구 그대로)·query_type·visual_status(이미지 입력이면 기존 시각
       4상태).

기동 시 준비(load_all — engine.load_all 끝에서 부른다): 상표 레코드(파일·DB 모드 공통 필드), 철자
캐시
(글자 토큰이 있는 상표명), 유사군 코드 → 상표 역색인(지금 100건, 백필 뒤 자동 확대), 인덱스 임베딩
행렬
(reconstruct_n), 유형 사전 계산(ml/data/types.json — 없으면 메타데이터 규칙만), 식별력 모델, 계수
JSON
(meta.grade_precision 필수, E-6). 실패해도 기동은 되고 multi_search 가 ModelNotReadyError 를 낸다.
발음·
관념 캐시는 phonetic_search·semantic_search 가 요청 때 스스로 준비한다(재게시 감지 포함).

규약: 동기 함수(CPU 작업은 API 가 기존 스레드 풀로 돌린다, asyncio 없음), 로그에 검색어·이미지
미기록(풀
크기·소요·유형 출처만), KIPRIS 호출 0. MARKLENS_FAKE_ML 에서는 가짜 임베더(CLIP·X3)·가짜 OCR 로 돌고
모델 JSON 은 실제를 쓴다 — CI·팀원 로컬에서 연결 테스트가 가능하다.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from . import config, engine, ocr, paths, phonetic_search, semantic_search, storage

if str(paths.ML_ROOT) not in sys.path:
    sys.path.insert(0, str(paths.ML_ROOT))

from src import mark_type as mt  # noqa: E402
from src.axes import x3_semantic as x3  # noqa: E402
from src.axes.distinctiveness import Distinctiveness, load_distinctiveness  # noqa: E402
from src.axes.pair_axes import (  # noqa: E402
    PairAxes,
    clean_name,
    compute_pair_axes,
    normalize_codes,
)
from src.axes.x1_phonetic import has_pronunciation  # noqa: E402
from src.axes.x2_ortho import has_spelling, orthographic_similarity  # noqa: E402
from src.axes.x4_goods import goods_similarity  # noqa: E402
from src.model import risk_model as rm  # noqa: E402
from src.scoring import score_results  # noqa: E402

logger = logging.getLogger(__name__)

API_VERSION = "2026-10-24"
POOL_IMAGE = 20
POOL_PHONETIC = 20
POOL_SPELLING = 20
POOL_SEMANTIC = 5
POOL_GOODS = 20
TOP_K_MIN, TOP_K_MAX = 1, 20
# ml/data/types.json — precompute_types.py 산출물(비공개 데이터). 없으면 메타데이터 규칙만 쓴다
TYPES_FILENAME = "types.json"

# 축 입력 이름(계수 JSON) ↔ 계약 축 이름
AXIS_KEYS = {"x1_d": "x1", "x2_text_d": "x2_text", "x2_whole": "x2_img", "x3_d": "x3", "x4": "x4"}
CONTRIBUTION_KEYS = ("X1", "X2", "X3", "X4", "요부")

# 계약 §2-5 caveat 문구 — 프론트가 문자열 비교로 아이콘을 고르므로 글자 하나도 바꾸지 않는다.
CAVEAT_FIGURE_LOW_DATA = "도형 유사는 검증 데이터가 적어 참고용"  # = 계수 JSON figure_rule.caveat
CAVEAT_NO_IMAGE = "이미지가 없어 외관(이미지) 축은 비교하지 않았습니다"
CAVEAT_NO_NAME = "상표명이 없어 호칭·철자·관념 축은 비교하지 않았습니다"
CAVEAT_NO_PRONUNCIATION = "입력 상표명에 호칭이 없어(기호·한자만) 호칭 축은 비교하지 않았습니다"
CAVEAT_NO_MEANING = "입력 상표명에 사전적 의미가 없어(조어) 관념 축은 비교하지 않았습니다"
CAVEAT_NO_GOODS = "지정상품이 없어 상품 견련성은 비교하지 않았습니다"
CAVEAT_GOODS_COVERAGE = "비교 대상 중 지정상품 정보가 있는 상표는 {with_goods}/{total}건입니다"
CAVEAT_GOODS_ONLY = ("지정상품만으로는 유사군이 겹치는 상표를 나열할 뿐 "
                     "표장 유사는 비교하지 않았습니다")
CAVEAT_OCR_FALLBACK = ("이미지에서 글자를 읽지 못해 유형을 {type}{ro} 두었습니다. "
                       "아니면 유형을 고쳐 주세요")
CAVEAT_NO_CANDIDATES = "비교할 후보가 없습니다 — 안전하다는 뜻이 아닙니다"
CAVEAT_X3_DISABLED = "관념 축이 꺼져 있어(MARKLENS_X3_ENABLED=0) 관념 유사도는 비교하지 않았습니다"
CAVEAT_NAME_SUGGESTED = ("이미지에서 '{text}'를 읽었습니다 — 상표명으로 넣으면 호칭·철자·관념도 "
                         "비교합니다")


class EmptyQueryError(ValueError):
    """image·name·goods_codes 가 모두 없다(API → 400)."""


class ModelNotReadyError(RuntimeError):
    """계수 JSON·식별력 모델이 준비되지 않았다(API → 503)."""


# ---- 레코드·상태 -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Record:
    """게시된 상표 1건 — 후보 조립에 필요한 필드만(파일·DB 모드 공통, 한글 키 메타에서 뽑는다)."""

    appno: str
    title: str | None  # 상표한글명, 없으면 상표영문명
    image_key: str | None
    pos: int | None  # 인덱스 순번(임베딩 행렬 행) — 이미지가 인덱스에 없으면 None
    applicant: str | None
    nice_classes: tuple[int, ...]
    goods: frozenset[str]
    display_type: str | None  # 문자 | 도형 | 결합 | None (types.json 또는 메타데이터 규칙)


@dataclass
class MultiState:
    records: list[Record] = field(default_factory=list)
    by_appno: dict[str, Record] = field(default_factory=dict)
    by_pos: dict[int, Record] = field(default_factory=dict)
    spelling_entries: tuple[Record, ...] = ()  # 글자 토큰이 있는 상표명(철자 풀 대상)
    goods_index: dict[str, tuple[str, ...]] = field(default_factory=dict)  # 유사군 코드 → 출원번호
    with_goods: int = 0
    embeddings: np.ndarray | None = None  # (ntotal, dim) 단위 벡터, 인덱스 순번 순
    types_source: str = "규칙"  # "types.json" | "규칙"
    types_loaded: int = 0
    model: dict | None = None
    grade_precision: float | None = None
    distinct: Distinctiveness | None = None
    error: str = ""
    load_token: str = ""
    ready: bool = False
    load_ms: float = 0.0


state = MultiState()
_load_lock = threading.Lock()


def reset() -> None:
    """테스트·재적재용."""
    global state
    state = MultiState()


# ---- 결과 ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class QueryType:
    type: str  # 문자 | 도형 | 결합-문자요부 | 결합-도형요부
    source: str  # ocr | fallback | user
    detail: dict | None  # {"text_ratio", "fig_ratio"} — ocr 일 때만
    suggested_name: str | None = None  # 이름 없는 이미지 질의에서 OCR 이 읽은 글자(계약 §2-4 5항)

    def to_dict(self) -> dict:
        return {
            "type": self.type, "source": self.source, "detail": self.detail,
            "suggested_name": self.suggested_name,
        }


@dataclass(frozen=True)
class CandidateResult:
    id: str
    title: str | None
    image_url: str | None
    type: str | None
    applicant: str | None
    nice_classes: tuple[int, ...]
    axes: dict  # x1·x2_text·x2_img·x3·x4 (0~1 | None)
    prob: float  # 반올림 전 위험도(정렬·검증용)
    grade: str
    contributions: dict  # X1·X2·X3·X4·요부 — 로짓 기여도(점수 항만)
    missing_adjustment: float  # miss_* 기여도 합
    figure_caveat: bool
    rule_triggers: tuple[str, ...]
    query_tokens: tuple[str, ...]
    candidate_tokens: tuple[str, ...]
    removed: tuple[dict, ...]  # {"token", "reason", "side"}
    goods_codes: tuple[str, ...]
    jaccard: float | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "image_url": self.image_url,
            "type": self.type,
            "applicant": self.applicant,
            "nice_classes": list(self.nice_classes),
            "axes": dict(self.axes),
            "risk": {
                "prob": round(self.prob, 3),
                "grade": self.grade,
                "contributions": {
                    key: round(value, 3) for key, value in self.contributions.items()
                },
                "missing_adjustment": round(self.missing_adjustment, 3),
                "figure_caveat": self.figure_caveat,
                "rule_triggers": list(self.rule_triggers),
            },
            "salient": {
                "query_tokens": list(self.query_tokens),
                "candidate_tokens": list(self.candidate_tokens),
                "removed": [dict(item) for item in self.removed],
            },
            "goods": {"codes": list(self.goods_codes), "jaccard": self.jaccard},
        }


@dataclass(frozen=True)
class SearchV2Result:
    """계약 v2 §2 응답 — to_dict() 가 키 이름을 그대로 낸다(API 는 그대로 직렬화하거나 pydantic 으로
    감싼다)."""

    overall_grade: str | None
    overall_prob: float | None
    caveats: tuple[str, ...]
    query_type: QueryType
    visual_status: str | None
    candidates: tuple[CandidateResult, ...]
    model_version: str
    grade_precision: float
    thresholds: dict
    pool: dict
    elapsed_ms: int
    dataset_info: dict
    index_size: int
    top_k_requested: int
    top_k_returned: int

    def to_dict(self) -> dict:
        return {
            "api_version": API_VERSION,
            "research_beta": True,
            "legal_conclusion": False,
            "overall": {
                "grade": self.overall_grade,
                "prob": None if self.overall_prob is None else round(self.overall_prob, 3),
                "caveats": list(self.caveats),
                "query_type": self.query_type.to_dict(),
                "visual_status": self.visual_status,
            },
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "meta": {
                "model_version": self.model_version,
                "grade_precision": self.grade_precision,
                "thresholds": self.thresholds,
                "pool": dict(self.pool),
                "elapsed_ms": self.elapsed_ms,
            },
            "dataset_info": dict(self.dataset_info),
            "index_size": self.index_size,
            "top_k_requested": self.top_k_requested,
            "top_k_returned": self.top_k_returned,
        }


# ---- 적재 ---------------------------------------------------------------------------------------


def _nice_classes(value: object) -> tuple[int, ...]:
    classes: list[int] = []
    for raw in value if isinstance(value, (list, tuple)) else []:
        text = str(raw).strip()
        if text.isdigit():
            classes.append(int(text))
    return tuple(classes)


def _source_records() -> list[dict]:
    """게시 모드별 상표 레코드(한글 키 dict) — 유사군·비엔나코드·상표구분까지 있는 전체 필드."""
    if engine.state.storage_mode == "db":
        from . import db

        return list(db.fetch_trademarks_by_image_keys(sorted(engine.state.image_path_set)).values())
    return list(engine.state.trademark_lookup.values())


def _types_path():
    return paths.ML_DATA_DIR / TYPES_FILENAME


def _load_types() -> dict[str, str]:
    """ml/data/types.json(precompute_types.py) → {출원번호: 표시 유형}. 없으면 빈 사전(규칙만)."""
    path = _types_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("유형 사전 계산 파일을 읽지 못해 규칙만 쓴다: %s", path)
        return {}
    types = data.get("types", data) if isinstance(data, dict) else {}
    out: dict[str, str] = {}
    for appno, item in types.items():
        kind = item.get("type") if isinstance(item, dict) else item
        if kind in mt.DISPLAY_TYPES:
            out[str(appno)] = kind
    return out


def _build_records(types: dict[str, str]) -> list[Record]:
    pos_of = {filename: pos for pos, filename in enumerate(engine.state.image_paths)}
    records: list[Record] = []
    for raw in _source_records():
        appno = str(raw.get("출원번호") or "").strip()
        if not appno:
            continue
        name_ko = str(raw.get("상표한글명") or "").strip()
        name_en = str(raw.get("상표영문명") or "").strip()
        title = clean_name(name_ko or name_en) or None
        image_key = str(raw.get("이미지파일") or "").strip() or None
        display = types.get(appno) or mt.type_from_metadata(
            raw.get("상표구분"), raw.get("비엔나코드"), title
        )
        records.append(
            Record(
                appno=appno,
                title=title,
                image_key=image_key,
                pos=pos_of.get(image_key) if image_key else None,
                applicant=str(raw.get("출원인") or "").strip() or None,
                nice_classes=_nice_classes(raw.get("류")),
                goods=normalize_codes(raw.get("유사군")),
                display_type=display,
            )
        )
    records.sort(key=lambda record: record.appno)
    return records


def _embedding_matrix() -> np.ndarray | None:
    index = engine.state.index
    try:
        matrix = index.reconstruct_n(0, int(index.ntotal))
    except Exception:  # 재구성을 지원하지 않는 인덱스 — CLIP 상위 20 밖 후보는 x2_img 없음
        logger.warning("인덱스 벡터를 재구성할 수 없어 x2_img 는 CLIP 상위 후보에만 붙는다")
        return None
    return np.ascontiguousarray(np.asarray(matrix, dtype=np.float32))


def load_all() -> MultiState:
    """엔진이 준비된 뒤 캐시를 만든다. 예외를 밖으로 내지 않는다 — 실패 이유는 state.error."""
    if not engine.state.ready:
        raise RuntimeError("엔진이 준비되기 전에는 통합 검색 캐시를 만들 수 없습니다.")
    started = time.perf_counter()
    fresh = MultiState()
    errors: list[str] = []
    try:
        types = _load_types()
        fresh.types_loaded = len(types)
        fresh.types_source = "types.json" if types else "규칙"
        fresh.records = _build_records(types)
        fresh.by_appno = {record.appno: record for record in fresh.records}
        fresh.by_pos = {record.pos: record for record in fresh.records if record.pos is not None}
        fresh.spelling_entries = tuple(
            record for record in fresh.records if record.title and has_spelling(record.title)
        )
        goods_index: dict[str, list[str]] = {}
        for record in fresh.records:
            for code in record.goods:
                goods_index.setdefault(code, []).append(record.appno)
        fresh.goods_index = {code: tuple(appnos) for code, appnos in goods_index.items()}
        fresh.with_goods = sum(1 for record in fresh.records if record.goods)
        fresh.embeddings = _embedding_matrix()
    except Exception as exc:  # 메타 구조가 다른 경우 등 — 기동은 막지 않는다
        errors.append(f"후보 캐시: {type(exc).__name__}")
        logger.exception("통합 검색 후보 캐시 실패")
    try:
        fresh.distinct = load_distinctiveness(with_goods=True)
    except Exception as exc:
        errors.append(f"식별력 모델: {type(exc).__name__}")
        logger.exception("식별력 모델 적재 실패 — multi_search 는 ModelNotReadyError")
    try:
        model = rm.load_model()
        precision = (model.get("meta") or {}).get("grade_precision")
        if not isinstance(precision, (int, float)):
            raise ModelNotReadyError(
                "계수 JSON meta.grade_precision 이 없습니다 — "
                "ml/scripts/train_risk_model.py 로 다시 쓰세요"
            )
        fresh.model = model
        fresh.grade_precision = float(precision)
    except Exception as exc:
        errors.append(f"계수 JSON: {exc}")
        logger.exception("통합 모델 계수 JSON 적재 실패 — multi_search 는 ModelNotReadyError")
    fresh.error = " / ".join(errors)
    fresh.load_token = engine.state.load_token
    fresh.ready = True
    fresh.load_ms = (time.perf_counter() - started) * 1000
    global state
    state = fresh
    logger.info(
        "X2 철자 캐시 준비: %d건 · 유사군 역색인 %d코드/%d건 · 임베딩 행렬 %s · "
        "유형 %s(%d건) · 모델 %s (mode=%s, %.0fms)",
        len(fresh.spelling_entries),
        len(fresh.goods_index),
        fresh.with_goods,
        "있음" if fresh.embeddings is not None else "없음",
        fresh.types_source,
        fresh.types_loaded,
        (fresh.model or {}).get("version", "미적재"),
        engine.state.storage_mode,
        fresh.load_ms,
    )
    return state


def _ensure_fresh() -> None:
    if state.ready and state.load_token == engine.state.load_token:
        return
    with _load_lock:
        if state.ready and state.load_token == engine.state.load_token:
            return
        load_all()


# ---- 유형·caveat --------------------------------------------------------------------------------


def _particle_ro(word: str) -> str:
    """'(으)로' 조사 — 받침 없음·ㄹ 받침은 '로', 그 외 '으로'."""
    if not word:
        return "로"
    code = ord(word[-1])
    if 0xAC00 <= code <= 0xD7A3:
        final = (code - 0xAC00) % 28
        return "로" if final in (0, 8) else "으로"
    return "로"


def _resolve_query_type(image, name: str | None, override: str | None) -> tuple[QueryType, bool]:
    """(query_type, OCR fallback 여부) — 계약 §2-4 5항(2026-10-24 개정).

    type_override 가 있으면 그대로(user). 이름이 있으면 **항상 문자계**: 이미지가 없거나 OCR
    fig_ratio < 0.08 이면 문자, 이미지에 뚜렷한 도형 영역이 있으면 결합-문자요부 — OCR 이 글자를 못
    읽어도 도형계로 가지 않는다(이름을 입력했다 = 문자 부분이 있다, 문자 있는 결합상표는 호칭이
    중요). 도형계(도형·결합-도형요부)는 이름 없는 이미지 질의와 사용자 선택 두 경우만: OCR 글자
    영역 ≥ 0.05 면 결합-도형요부, 그 외·실패면 도형. 이름 없는 질의에서 OCR 이 읽은 글자는
    suggested_name 으로 돌려주고 이 요청에서 이름 축을 계산하지는 않는다(사용자 확인 뒤 재요청). OCR
    은 유형의 최종 결정자가 아니라 글자를 찾아 주는 도우미다.
    """
    has_name = bool(name)
    if override:
        return QueryType(mt.model_type(override, "", has_name=has_name), "user", None), False
    if image is None:
        return QueryType("문자", "fallback", None), False
    detection = ocr.detect(image)
    if detection is None:
        return QueryType("문자" if has_name else "도형", "fallback", None), True
    detail = {"text_ratio": detection.text_ratio, "fig_ratio": detection.fig_ratio}
    if has_name:
        level = "문자" if detection.fig_ratio < mt.FIG_RATIO_TEXT else "결합-문자요부"
        return QueryType(level, "ocr", detail), False
    level = "결합-도형요부" if detection.text_ratio >= mt.TEXT_RATIO_FIGURE else "도형"
    return QueryType(level, "ocr", detail, suggested_name=detection.text or None), False


def _group_contributions(term_contributions: dict[str, float]) -> tuple[dict[str, float], float]:
    """항별 기여도 → 축별(X1·X2·X3·X4·요부) 점수 항 합과 결측 지시변수 합(missing_adjustment)."""
    grouped = {key: 0.0 for key in CONTRIBUTION_KEYS}
    missing = 0.0
    for name, value in term_contributions.items():
        if name == "intercept":
            continue
        if name.startswith("miss_"):
            missing += float(value)
            continue
        axis = rm.TERM_AXIS.get(name)
        if axis in grouped:
            grouped[axis] += float(value)
    return grouped, missing


def _rule_triggers(values: dict[str, float], model: dict, level: str) -> tuple[str, ...]:
    """등급 하한 "검토 권장"을 만드는 규칙 중 조건이 성립한 것(risk_score 와 같은 판정식)."""
    triggers: list[str] = []
    for axis, tau in (model.get("standalone_thresholds") or {}).items():
        if tau is None or axis not in AXIS_KEYS:
            continue
        miss = dict(rm.AXIS_INPUTS)[axis]
        if values[miss] == 0.0 and values[axis] >= float(tau):
            triggers.append(f"standalone_{AXIS_KEYS[axis]}")
    rule = model.get("figure_rule")
    if rule and level in rm.FIGURE_FAMILY:
        threshold = rule.get("threshold")
        if threshold is not None and values["miss_x2img"] == 0.0 and (
            values["x2_whole"] >= float(threshold)
        ):
            triggers.append("figure_x2_img")
    return tuple(triggers)


def _thresholds(model: dict) -> dict:
    standalone = model.get("standalone_thresholds") or {}
    return {
        "grade": {key: float(value) for key, value in model["grade_thresholds"].items()},
        "standalone": {AXIS_KEYS[axis]: standalone.get(axis) for axis in AXIS_KEYS},
        "figure": (model.get("figure_rule") or {}).get("threshold"),
    }


def _clip01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _candidate_sort_key(candidate: "CandidateResult") -> tuple:
    """위험도 내림차순 → 동점(이미지만 입력하면 p 가 모두 같다)은 x2_img 내림차순 → 출원번호
    오름차순."""
    x2_img = candidate.axes["x2_img"]
    return (-round(candidate.prob, 6), -(x2_img if x2_img is not None else -1.0), candidate.id)


# ---- 검색 ---------------------------------------------------------------------------------------


def multi_search(
    image=None,
    name: str | None = None,
    goods_codes=None,
    type_override: str | None = None,
    top_k: int = 5,
) -> SearchV2Result:
    """3입력 통합 검색(계약 v2). image 는 검증된 PIL 이미지(또는 encode_image 가 받는 형태), name 은
    상표명,
    goods_codes 는 유사군 코드 목록, type_override 는 문자·도형·결합 중 하나."""
    started = time.perf_counter()
    if not engine.state.ready:
        raise RuntimeError("Engine 이 아직 초기화되지 않았습니다.")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not TOP_K_MIN <= top_k <= TOP_K_MAX:
        raise ValueError(f"top_k 는 {TOP_K_MIN}~{TOP_K_MAX} 정수여야 합니다 (받은 값: {top_k!r}).")
    query_name = clean_name(name) or None
    goods = normalize_codes(goods_codes) or None
    override = str(type_override).strip() if type_override is not None else ""
    if override and override not in mt.OVERRIDE_TYPES:
        raise ValueError(f"type_override 는 {'·'.join(mt.OVERRIDE_TYPES)} 중 하나여야 합니다.")
    if image is None and query_name is None and goods is None:
        raise EmptyQueryError("image, name, goods_codes 중 하나는 있어야 합니다.")

    _ensure_fresh()
    if state.model is None or state.distinct is None:
        raise ModelNotReadyError(state.error or "통합 모델이 준비되지 않았습니다.")
    model, distinct = state.model, state.distinct
    index_size = int(engine.state.index.ntotal)

    query_type, ocr_fallback = _resolve_query_type(image, query_name, override or None)
    x3_on = bool(config.X3_ENABLED) and semantic_search.state.enabled

    # ---- 후보 풀 ----
    pool: dict[str, Record] = {}
    counts = {"image": 0, "phonetic": 0, "spelling": 0, "semantic": 0, "goods": 0, "total": 0}
    query_embedding: np.ndarray | None = None
    image_similarity: dict[int, float] = {}
    visual_status: str | None = None
    if image is not None:
        query_embedding = np.asarray(engine.encode_image(image), dtype=np.float32).reshape(-1)
        distances, indices = engine.search(
            engine.state.index, query_embedding, k=min(POOL_IMAGE, index_size)
        )
        visual_status = score_results(distances)["status_code"]
        for distance, pos in zip(distances.tolist(), indices.tolist()):
            record = state.by_pos.get(int(pos))
            if record is None:
                continue
            image_similarity[int(pos)] = _clip01(distance)
            if record.appno not in pool:
                pool[record.appno] = record
            counts["image"] += 1
    split_name = distinct.split_goods_suffix(query_name) if query_name else None
    if query_name:
        for match in phonetic_search.search(query_name, POOL_PHONETIC, 0.0).matches:
            record = state.by_appno.get(match.entry.application_number)
            if record is None or match.similarity <= 0.0:
                continue
            pool.setdefault(record.appno, record)
            counts["phonetic"] += 1
        scored = [
            (orthographic_similarity(query_name, record.title), record)
            for record in state.spelling_entries
        ]
        scored = [item for item in scored if item[0] > 0.0]
        scored.sort(key=lambda item: (-item[0], item[1].appno))
        for _, record in scored[:POOL_SPELLING]:
            pool.setdefault(record.appno, record)
            counts["spelling"] += 1
        if x3_on:
            try:
                semantic = semantic_search.search(query_name, POOL_SEMANTIC, config.X3_MIN_SCORE)
            except RuntimeError as exc:  # 캐시·모델 실패 — 관념 축 없이 진행
                x3_on = False
                logger.warning("관념 캐시를 쓸 수 없어 X3 없이 진행: %s", type(exc).__name__)
            else:
                for match in semantic.matches:
                    record = state.by_appno.get(match.entry.application_number)
                    if record is None:
                        continue
                    pool.setdefault(record.appno, record)
                    counts["semantic"] += 1
    if goods:
        overlap: dict[str, Record] = {}
        for code in goods:
            for appno in state.goods_index.get(code, ()):
                record = state.by_appno.get(appno)
                if record is not None:
                    overlap[appno] = record
        ranked = sorted(
            overlap.values(),
            key=lambda record: (-goods_similarity(goods, record.goods), record.appno),
        )
        for record in ranked[:POOL_GOODS]:
            pool.setdefault(record.appno, record)
            counts["goods"] += 1
    counts["total"] = len(pool)

    # ---- 쌍별 축·위험도 ----
    candidates: list[CandidateResult] = []
    for record in pool.values():
        x2_img: float | None = None
        if query_embedding is not None and record.pos is not None:
            if state.embeddings is not None:
                x2_img = round(_clip01(float(state.embeddings[record.pos] @ query_embedding)), 4)
            elif record.pos in image_similarity:
                x2_img = round(image_similarity[record.pos], 4)
        axes: PairAxes | None = None
        if query_name and record.title:
            axes = compute_pair_axes(
                query_name, record.title, model=distinct, goods_a=goods, goods_b=record.goods,
                x3_enabled=x3_on,
            )
            features = axes.model_features(x2_img=x2_img, mark_type=query_type.type)
            x4 = axes.x4
            query_tokens, candidate_tokens = axes.query_tokens, axes.candidate_tokens
            removed = tuple(
                {"token": item.token, "reason": item.reason, "side": item.side}
                for item in axes.removed
            )
        else:
            x4 = round(goods_similarity(goods, record.goods), 4) if goods and record.goods else None
            features = {
                "x1_d": None, "x2_text_d": None, "x2_whole": x2_img, "x3_d": None, "x4": x4,
                "has_meaning_both": False, "has_distinctive_part_a": True,
                "has_distinctive_part_b": True, "mark_type": query_type.type,
            }
            query_tokens = ()
            candidate_tokens = tuple(
                token for token, _ in distinct.salient_tokens(record.title, goods)
            ) if record.title else ()
            removed = ()
        result = rm.risk_score(features, model)
        values = rm.design_values(features)
        contributions, missing = _group_contributions(result.contributions)
        candidates.append(
            CandidateResult(
                id=record.appno,
                title=record.title,
                image_url=storage.public_url(record.image_key),
                type=record.display_type,
                applicant=record.applicant,
                nice_classes=record.nice_classes,
                axes={
                    "x1": axes.x1 if axes else None,
                    "x2_text": axes.x2_text if axes else None,
                    "x2_img": x2_img,
                    "x3": axes.x3 if axes else None,
                    "x4": x4,
                },
                prob=float(result.prob),
                grade=result.grade,
                contributions=contributions,
                missing_adjustment=missing,
                figure_caveat=result.figure_caveat,
                rule_triggers=_rule_triggers(values, model, query_type.type),
                query_tokens=query_tokens,
                candidate_tokens=candidate_tokens,
                removed=removed,
                goods_codes=tuple(sorted(record.goods)),
                jaccard=x4,
            )
        )
    candidates.sort(key=_candidate_sort_key)
    top = tuple(candidates[:top_k])

    # ---- overall·caveats ----
    caveats: list[str] = []
    if query_type.type in rm.FIGURE_FAMILY:
        caveats.append((model.get("figure_rule") or {}).get("caveat") or CAVEAT_FIGURE_LOW_DATA)
    if query_type.suggested_name:
        caveats.append(CAVEAT_NAME_SUGGESTED.format(text=query_type.suggested_name))
    if ocr_fallback:
        label = mt.display_type(query_type.type)
        caveats.append(CAVEAT_OCR_FALLBACK.format(type=label, ro=_particle_ro(label)))
    if image is None:
        caveats.append(CAVEAT_NO_IMAGE)
    if query_name is None:
        caveats.append(CAVEAT_NO_NAME)
    else:
        if not has_pronunciation(split_name or query_name):
            caveats.append(CAVEAT_NO_PRONUNCIATION)
        if x3_on and not x3.has_meaning(split_name or query_name):
            caveats.append(CAVEAT_NO_MEANING)
        if not x3_on:
            caveats.append(CAVEAT_X3_DISABLED)
    if goods is None:
        caveats.append(CAVEAT_NO_GOODS)
    else:
        caveats.append(CAVEAT_GOODS_COVERAGE.format(with_goods=f"{state.with_goods:,}",
                                                    total=f"{index_size:,}"))
        if image is None and query_name is None:
            caveats.append(CAVEAT_GOODS_ONLY)
    if not top:
        caveats.append(CAVEAT_NO_CANDIDATES)
    overall_grade = max((c.grade for c in top), key=rm.GRADES.index) if top else None
    overall_prob = max(c.prob for c in top) if top else None

    elapsed_ms = int(round((time.perf_counter() - started) * 1000))
    logger.info(
        "multi_search: pool=%s type=%s/%s candidates=%d returned=%d elapsed=%dms",
        counts, query_type.type, query_type.source, len(candidates), len(top), elapsed_ms,
    )
    return SearchV2Result(
        overall_grade=overall_grade,
        overall_prob=overall_prob,
        caveats=tuple(caveats),
        query_type=query_type,
        visual_status=visual_status,
        candidates=top,
        model_version=str(model.get("version")),
        grade_precision=float(state.grade_precision or 0.0),
        thresholds=_thresholds(model),
        pool=counts,
        elapsed_ms=elapsed_ms,
        dataset_info=dict(engine.state.dataset_info),
        index_size=index_size,
        top_k_requested=int(top_k),
        top_k_returned=len(top),
    )
