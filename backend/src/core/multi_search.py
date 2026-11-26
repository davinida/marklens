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
캐시(글자 토큰이 있는 상표명), 유사군 코드 → 상표 역색인(형식 ^[GS]\d{4,6}$ 에 맞는 코드만 — 안 맞는
코드는 무시하고 건수를 기동 로그에), 인덱스 임베딩 행렬(reconstruct_n), 유형 사전 계산(ml/data/
types.json — 없으면 메타데이터 규칙만), 식별력 모델, 계수 JSON(meta.grade_precision 필수, E-6), 사진
판정 방향 벡터(shared/model/photo_direction_v1.json — 없으면 사진 판정을 끈다). 실패해도 기동은 되고
multi_search 가 ModelNotReadyError 를 낸다. 발음·관념 캐시는 phonetic_search·semantic_search 가 요청
때 스스로 준비한다(재게시 감지 포함).

통합 모델 v1.4(2026-11-20, 계약 v2 §2-4): 이름 없는 입력(이미지만·이미지+지정상품)은 이름 없는 계수
집합과 그 집합의 등급 하한으로 판단한다(`risk.pattern` 이 "noname:…", `meta.thresholds.nameless`).
사진 판정(src.photo_mark): 질의 이미지가 사진이면 caveat PHOTO_QUERY — 이름이 있으면 이미지 축을
관측 없음으로 계산(학습에서 사진 쌍의 이미지를 뺀 것과 같게), 이름이 없으면 계산은 그대로.
유형을 도형계로 고친 질의(type_override)에 이름과 이미지가 있으면 같은 입력에서 이름을 뺀 판단의
등급이 더 높을 때 그쪽을 쓴다(rule_triggers 에 nameless_floor). 계수 JSON 이 logo_floor 를 켜면
(v1.4.2, 2026-11-23) 그 밖의 이미지가 있는 이름 있는 질의도 후보마다 이름도 업종도 뺀 "이미지만"
판단(유형은 이름 없이 넣었을 때의 유형)과 견줘 높은 등급·위치를 쓴다(같은 nameless_floor — 업종이
들어간 이름 없는 판단은 쓰지 않는다). 질의 이미지가 사진이면 이 비교를 하지 않는다.

유명 상표 확인(v1.4.7, 2026-11-26 — 설계 §7-14-13, 계약 v2 §2-6): 계수 JSON 이 famous_check 를 켜면
기동 때 등록부·확정 파일을 읽어 해시를 대조하고(없거나 다르면 검색 준비 안 됨 — /health 503
FAMOUS_CHECK_UNAVAILABLE), 질의마다 검색과 별개로 유명 상표를 확인한다(src.famous_runtime — 판정
규칙은 확정된 src.famous_check): 이름, 이름 없는 이미지 질의의 OCR 제안 상표명, 사진이 아닌 질의
이미지와 대표 로고. 판정이 준 바닥(위험·검토 권장)이 전체 등급보다 높으면 전체 등급만 올리고
(overall.famous_floor), 후보 목록·후보 등급·위험도·정렬은 그대로 둔다. 응답에는 선택 필드
famous(확인 상태·등록부 브랜드 수·일치 최대 2개 브랜드)와 후보의 famous_brand 를 더한다. 확인에서
예외가 나면 검색은 그대로 내고 famous.status 만 "unavailable". 표시가 없는 JSON(≤ v1.4.6)은 예전과
똑같이 동작한다. MARKLENS_FAKE_ML 에서는 로고 경로를 쓰지 않는다(가짜 임베딩은 유사도가 고정).

규약: 동기 함수(CPU 작업은 API 가 기존 스레드 풀로 돌린다, asyncio 없음), 로그에 검색어·이미지
미기록(풀
크기·소요·유형 출처만), KIPRIS 호출 0. MARKLENS_FAKE_ML 에서는 가짜 임베더(CLIP·X3)·가짜 OCR 로 돌고
모델 JSON 은 실제를 쓴다 — CI·팀원 로컬에서 연결 테스트가 가능하다.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from dataclasses import dataclass, field, replace

import numpy as np

from . import config, engine, ocr, paths, phonetic_search, semantic_search, storage

if str(paths.ML_ROOT) not in sys.path:
    sys.path.insert(0, str(paths.ML_ROOT))

from src import famous_runtime as fr  # noqa: E402
from src import mark_type as mt  # noqa: E402
from src import photo_mark  # noqa: E402
from src.axes import goods_map as gm  # noqa: E402
from src.axes import x3_semantic as x3  # noqa: E402
from src.axes.distinctiveness import Distinctiveness, load_distinctiveness  # noqa: E402
from src.axes.pair_axes import (  # noqa: E402
    PairAxes,
    clean_input_name,  # noqa: F401 — API 가 같은 정리를 쓰도록 여기서 내보낸다(견고성 점검 R-P1-6)
    clean_name,
    compute_pair_axes,
    normalize_codes,
)
from src.axes.x1_phonetic import has_pronunciation  # noqa: E402
from src.axes.x2_ortho import has_spelling, orthographic_similarity  # noqa: E402
from src.axes.x4_goods import goods_similarity  # noqa: E402
from src.model import risk_model as rm  # noqa: E402
from src.preprocess import BlankImageError  # noqa: E402, F401 — 빈 이미지(API 400, 계약 §5-6)
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
# = 계수 JSON figure_rule.caveat(v1.4). v1.3 JSON 은 옛 문구 "도형 유사는 검증 데이터가 적어 참고용"
CAVEAT_FIGURE_LOW_DATA = ("로고 파일끼리 비교한 결과예요. 도형 유사는 검증 데이터가 적어 "
                          "참고용이에요")
CAVEAT_PHOTO_QUERY = "사진으로 보여요 — 로고 파일을 올리면 외관 비교가 더 정확해요"
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
GOODS_CODE_PATTERN = re.compile(r"^[GS]\d{4,6}$")  # 유사군 코드 형식(G/S + 숫자 4~6자리)
NAMELESS_FLOOR = "nameless_floor"  # 이름 있는 이미지 질의에서 로고만 판단의 등급이 쓰였다
GOODS_FLOOR = "goods_floor"  # 업종이 겹치는 이름 없는 판단에서 이미지만 판단의 등급이 쓰였다
# 업종이 겹치는 이름 있는 업종 판단(x4·x2_whole+x4)에서 업종 없는 짝 판단의 등급이 쓰였다(§7-13)
GOODS_FLOOR_NAMED = "goods_floor_named"
# 업종이 다른(겹침 < 결합 하한) 업종 판단에서 업종 없는 짝 판단의 등급까지만 썼다(업종 상한, §7-13)
GOODS_CAP = "goods_cap"
# search_pool 단계별 시간(PoolResult.timings 키) — 축 = compute_pair_axes(관념 축 MiniLM 포함),
# 모델 = 그 밖의 채점(risk_score·nameless_floor 비교·기여도)
STAGES = ("유형(OCR)", "이미지 임베딩", "이미지 풀", "발음 풀", "철자 풀", "관념 풀", "상품 풀",
          "축", "모델", "정렬")


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
    goods: frozenset[str]  # 형식에 맞는 유사군 코드만(GOODS_CODE_PATTERN)
    display_type: str | None  # 문자 | 도형 | 결합 | None (types.json 또는 메타데이터 규칙)


@dataclass
class MultiState:
    records: list[Record] = field(default_factory=list)
    by_appno: dict[str, Record] = field(default_factory=dict)
    by_pos: dict[int, Record] = field(default_factory=dict)
    spelling_entries: tuple[Record, ...] = ()  # 글자 토큰이 있는 상표명(철자 풀 대상)
    goods_index: dict[str, tuple[str, ...]] = field(default_factory=dict)  # 유사군 코드 → 출원번호
    with_goods: int = 0
    goods_ignored: int = 0  # 형식에 안 맞아 무시한 유사군 코드 수(기동 로그)
    photo_direction: np.ndarray | None = None  # 사진 판정 방향 벡터(없으면 사진 판정 끔)
    photo_threshold: float = 0.0
    embeddings: np.ndarray | None = None  # (ntotal, dim) 단위 벡터, 인덱스 순번 순
    types_source: str = "규칙"  # "types.json" | "규칙"
    types_loaded: int = 0
    model: dict | None = None
    grade_precision: float | None = None
    distinct: Distinctiveness | None = None
    # 유명 상표 확인 자료(계수 JSON 이 famous_check 를 켰을 때만 — 못 읽으면 None, 검색 준비 안 됨)
    famous: fr.Runtime | None = None
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
    pattern: str = ""  # risk_score 가 쓴 계수 집합(RiskResult.pattern; "noname:…" = 이름 없는 판단)
    rank: tuple[int, float] = (0, 0.0)  # 정렬 위치(rank_position — 응답에 넣지 않음)
    famous_brand: str | None = None  # 유명 상표 등록부의 표장이면 그 브랜드(선택 필드, v1.4.7)

    def to_dict(self) -> dict:
        out = self._base_dict()
        if self.famous_brand is not None:
            out["famous_brand"] = self.famous_brand
        return out

    def _base_dict(self) -> dict:
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
                "pattern": self.pattern,
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
    overall_pattern: str | None = None  # 전체 등급을 정한 후보의 계수 집합("noname:…" = 이름 없음)
    # 유명 상표 확인(선택 필드 — 계수 JSON 이 켰을 때만, 계약 v2 §2-6). famous = 응답 그대로,
    # famous_floor = 그 바닥이 전체 등급을 정했는가. 아래 둘은 응답에 넣지 않는다(분석·검증용)
    famous: dict | None = None
    famous_floor: bool | None = None
    famous_outcome: object | None = None  # fr.Outcome
    famous_ms: float = 0.0  # 유명 상표 확인에 든 시간

    def to_dict(self) -> dict:
        overall = {
            "grade": self.overall_grade,
            "prob": None if self.overall_prob is None else round(self.overall_prob, 3),
            "pattern": self.overall_pattern,
            "caveats": list(self.caveats),
            "query_type": self.query_type.to_dict(),
            "visual_status": self.visual_status,
        }
        head = {"api_version": API_VERSION, "research_beta": True, "legal_conclusion": False,
                "overall": overall}
        if self.famous is not None:  # 꺼져 있으면 키를 싣지 않는다(v1.4.6 응답과 같게)
            overall["famous_floor"] = bool(self.famous_floor)
            head["famous"] = self.famous
        return {
            **head,
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


def valid_goods(codes) -> tuple[frozenset[str], int]:
    """유사군 코드 정리(normalize_codes) 뒤 형식(GOODS_CODE_PATTERN)에 맞는 것만 — (코드, 무시한
    수). 수집 원본에 V 로 시작하는 등 형식이 다른 코드가 섞여 있어 역색인·X4 에 넣지 않는다."""
    normalized = normalize_codes(codes)
    kept = frozenset(code for code in normalized if GOODS_CODE_PATTERN.match(code))
    return kept, len(normalized) - len(kept)


def _build_records(types: dict[str, str]) -> tuple[list[Record], int]:
    """(상표 레코드, 형식에 안 맞아 무시한 유사군 코드 수)."""
    pos_of = {filename: pos for pos, filename in enumerate(engine.state.image_paths)}
    records: list[Record] = []
    ignored = 0
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
        goods, dropped = valid_goods(raw.get("유사군"))
        ignored += dropped
        records.append(
            Record(
                appno=appno,
                title=title,
                image_key=image_key,
                pos=pos_of.get(image_key) if image_key else None,
                applicant=str(raw.get("출원인") or "").strip() or None,
                nice_classes=_nice_classes(raw.get("류")),
                goods=goods,
                display_type=display,
            )
        )
    records.sort(key=lambda record: record.appno)
    return records, ignored


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
        fresh.records, fresh.goods_ignored = _build_records(types)
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
    # 사진 판정 방향 벡터 — 없거나 임베딩 계약이 다르면 사진 판정만 끈다(검색은 그대로). 가짜 ML
    # 모드(MARKLENS_FAKE_ML)는 임베딩이 의미 없어 끈다(테스트는 state.photo_direction 을 직접
    # 넣는다).
    if not ocr.is_fake():
        try:
            fresh.photo_direction, fresh.photo_threshold = photo_mark.load_direction()
        except Exception as exc:
            logger.warning("사진 판정 방향 벡터를 읽지 못해 사진 판정을 끈다: %s",
                           type(exc).__name__)
    # 유명 상표 확인 — 계수 JSON 이 켰을 때만. 등록부·확정 파일이 없거나 깨졌거나 해시가 다르면
    # 모델 파일 문제와 같게 검색을 준비 안 됨으로 둔다(원인은 여기 로그에만)
    if fresh.model is not None and rm.famous_check_enabled(fresh.model):
        try:
            fresh.famous = _load_famous(fresh)
        except Exception as exc:
            errors.append(f"유명 상표 확인: {type(exc).__name__}")
            logger.exception("유명 상표 확인 자료 적재 실패 — multi_search 는 ModelNotReadyError")
    fresh.error = " / ".join(errors)
    fresh.load_token = engine.state.load_token
    fresh.ready = True
    fresh.load_ms = (time.perf_counter() - started) * 1000
    global state
    state = fresh
    logger.info(
        "X2 철자 캐시 준비: %d건 · 유사군 역색인 %d코드/%d건(형식이 안 맞아 무시한 코드 %d개) · "
        "임베딩 행렬 %s · 유형 %s(%d건) · 모델 %s · 사진 판정 %s (mode=%s, %.0fms)",
        len(fresh.spelling_entries),
        len(fresh.goods_index),
        fresh.with_goods,
        fresh.goods_ignored,
        "있음" if fresh.embeddings is not None else "없음",
        fresh.types_source,
        fresh.types_loaded,
        (fresh.model or {}).get("version", "미적재"),
        "켜짐" if fresh.photo_direction is not None else "꺼짐",
        engine.state.storage_mode,
        fresh.load_ms,
    )
    return state


def image_only_grade(x2: float, level: str, model: dict | None = None) -> str:
    """이름도 업종도 뺀 "이미지만" 판단의 등급(유형 level) — logo_floor 의 비교와 유명 상표의 로고
    확인이 같은 판단을 쓴다."""
    model = state.model if model is None else model
    return _judge(_image_only_features(x2, level), model, level).result.grade


def _load_famous(fresh: MultiState) -> fr.Runtime:
    """유명 상표 확인에 쓰는 것(설계 §7-14-13) — 확정 파일·등록부(해시 대조)·업종 표, 그리고 대표
    로고 색인(지금 색인에 있는 표장만 — 없는 것은 건너뛰고 수만 로그에). 가짜 ML 모드나 색인 벡터를
    재구성할 수 없을 때는 로고 색인을 만들지 않는다(로고 경로 끔 — 이름 확인은 그대로)."""
    started = time.perf_counter()
    model = fresh.model
    goods_map = gm.load_goods_map()
    runtime = fr.load_runtime(rm.famous_check_config(model), dist=fresh.distinct,
                              goods_map=goods_map, presets=gm.load_business_presets(goods_map))
    by_appno = fresh.by_appno
    logos, stats = None, {}
    if not ocr.is_fake() and fresh.embeddings is not None:
        direction, threshold = fresh.photo_direction, fresh.photo_threshold
        photo_of = None if direction is None else (
            lambda row: photo_mark.is_photo(row, direction=direction, threshold=threshold))
        logos, stats = fr.build_logo_index(
            runtime.registry, by_appno, fresh.embeddings,
            lambda x2, level: image_only_grade(x2, level, model), runtime.logo_kinds,
            photo_of=photo_of)
        for level in mt.MODEL_TYPES:  # 위험이 되는 유사도를 미리 구해 둔다(질의 때는 읽기만)
            logos.risk_min(level)

    def shown(appno: str) -> bool:
        record = by_appno.get(appno)
        return record is not None and bool(record.image_key)

    runtime = fr.with_engine(runtime, logos=logos,
                             brand_logos=fr.brand_logo_table(runtime.registry, shown))
    # 한 번 돌려 둔다(업종 없이·업종 세트 하나로) — 등록부 표기의 읽기·업종 낱말·35류를 뺀 식별력
    # 사본 같은 캐시가 채워져 첫 질의가 느리지 않고, 판정이 돌지 않는 상태(자료가 서로 안 맞음)는
    # 기동 때 드러난다
    fr.check(runtime, name="유명 상표 확인 준비")
    fr.check(runtime, name="유명 상표 확인 준비", goods=next(iter(runtime.codes_of.values()), None))
    logger.info(
        "유명 상표 확인 준비: 브랜드 %d · 대표 로고 %s(색인에 없어 건너뜀 %s · 구분 없어 건너뜀 %s)"
        " · 로고 경로 %s (%.0fms)",
        runtime.brand_count, stats.get("쓰는_것", 0), stats.get("색인에_없음", "-"),
        stats.get("구분_없음", "-"), "켜짐" if logos is not None else "꺼짐",
        (time.perf_counter() - started) * 1000)
    return runtime


def _ensure_fresh() -> None:
    if state.ready and state.load_token == engine.state.load_token:
        return
    with _load_lock:
        if state.ready and state.load_token == engine.state.load_token:
            return
        load_all()


def unavailable_reason() -> str | None:
    """통합 검색을 할 수 없는 이유 코드 — /health 가 쓴다(계약 v2 §5-7, 견고성 점검 R-P1-2). 할 수
    있으면 None. 원인 원문(state.error — 파일 경로·예외 문구가 들어 있을 수 있음)은 내보내지 않는다
    (원인은 기동 로그에). 기동 중에는 lifespan 이 끝나기 전이라 /health 자체가 응답하지 않는다."""
    if not engine.state.ready:
        return "ENGINE_LOADING"
    if engine.state.index is None or int(engine.state.index.ntotal) == 0:
        return "INDEX_EMPTY"
    if not state.ready:
        return "SEARCH_LOADING"
    if state.model is None:
        return "RISK_MODEL_UNAVAILABLE"
    if state.distinct is None:
        return "DISTINCTIVENESS_UNAVAILABLE"
    if rm.famous_check_enabled(state.model) and state.famous is None:
        return "FAMOUS_CHECK_UNAVAILABLE"  # 등록부·확정 파일이 없거나 깨졌거나 해시가 다름
    if not state.records:
        return "CANDIDATES_UNAVAILABLE"
    return None


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
        axis = rm.term_axis(name)  # 곱하기 항(설계 §7-12)은 X4
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
    """계약 §2-3 meta.thresholds — grade 는 이름 있는 판단의 하한, nameless 는 이름 없는 계수
    집합(risk.pattern)별 하한(위험 null = 위험도로는 닿지 않음; 이름 없는 집합이 없는 JSON 은
    {})."""
    standalone = model.get("standalone_thresholds") or {}
    out = {
        "grade": {key: float(value) for key, value in model["grade_thresholds"].items()},
        "nameless": rm.nameless_grade_thresholds(model),
        "standalone": {AXIS_KEYS[axis]: standalone.get(axis) for axis in AXIS_KEYS},
        "figure": (model.get("figure_rule") or {}).get("threshold"),
    }
    named = rm.named_grade_thresholds(model)
    if named:  # 이름 있는 계수 집합 중 자기 하한이 있는 것(§7-13) — 없으면 키를 싣지 않는다
        out["named"] = named
    return out


def is_photo_query(embedding: np.ndarray | None) -> bool:
    """질의 이미지가 사진인가(src.photo_mark — 학습 특징의 사진A·사진B 와 같은 판정)."""
    if embedding is None or state.photo_direction is None:
        return False
    return photo_mark.is_photo(embedding, direction=state.photo_direction,
                               threshold=state.photo_threshold)


def _nameless_features(features: dict) -> dict:
    """같은 입력에서 이름을 뺀 것(이름 축 결측·요부 플래그 True — 엔진의 이름 없는 입력과 같은
    꼴)."""
    return {**{key: value for key, value in features.items() if key != rm.SPELLING_VERSION_INPUT},
            "x1_d": None, "x2_text_d": None, "x3_d": None, "has_meaning_both": False,
            "has_distinctive_part_a": True, "has_distinctive_part_b": True}


def _image_only_features(x2_img: float, level: str) -> dict:
    """이름도 업종도 뺀 이미지만 입력(엔진의 이름 없는 이미지 질의와 같은 꼴)."""
    return {"x1_d": None, "x2_text_d": None, "x2_whole": x2_img, "x3_d": None, "x4": None,
            "has_meaning_both": False, "has_distinctive_part_a": True,
            "has_distinctive_part_b": True, "mark_type": level}


def _clip01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def rank_position(prob: float, model: dict, pattern: str) -> tuple[int, float]:
    """정렬 위치 = (위험도 p 만으로 정한 등급, 그 등급 안 위치). 등급 안 위치 = (p − 그 등급
    하한) / (다음 등급 하한 − 그 등급 하한), 하한은 그 판단의 계수 집합 것(grade_thresholds_for) —
    다음 하한이 null 이거나 맨 위 등급이면 위 끝 1.0. p 는 소수 6자리로 반올림해서 쓴다(예전 정렬
    키와 같은 동점). 단독·도형 규칙으로 올라간 등급은 쓰지 않는다 — 같은 계수 집합끼리는 이
    위치가 p 의 증가함수라 순서가 위험도 순서와 같고, 이름 있는·없는 판단이 섞이면 눈금이 다른 p
    대신 이 위치로 견준다."""
    value = round(float(prob), 6)
    thresholds = rm.grade_thresholds_for(model, pattern)
    grade = rm.grade_for(value, thresholds)
    index = rm.GRADES.index(grade)
    low = 0.0 if index == 0 else float(thresholds[grade])
    high = next((float(thresholds[higher]) for higher in rm.GRADES[index + 1:]
                 if thresholds.get(higher) is not None), 1.0)
    return index, ((value - low) / (high - low) if high > low else 0.0)


def _candidate_sort_key(candidate: "CandidateResult") -> tuple:
    """정렬 위치(rank_position — p 로 정한 등급 → 등급 안 위치) 내림차순 → x2_img 내림차순 →
    출원번호 오름차순. 한 응답에 이름 있는 판단과 이름 없는 판단(이름 없는 후보·nameless_floor)이
    섞이면 위험도 눈금이 달라 p 로 줄 세우지 않는다. 같은 계수 집합만 있는 응답은 예전 정렬
    (위험도 내림차순 → x2_img → 출원번호)과 같다 — 단독·도형 규칙으로 표시 등급만 올라간 후보도 p
    자리에 둔다."""
    x2_img = candidate.axes["x2_img"]
    index, band = candidate.rank
    return (-index, -band, -(x2_img if x2_img is not None else -1.0), candidate.id)


# ---- 검색 ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PoolResult:
    """search_pool 결과 — 후보 풀 전부(정렬됨)와 응답 조립에 필요한 맥락."""

    candidates: tuple[CandidateResult, ...]  # 풀 전체, 위험도 내림차순(_candidate_sort_key)
    query_type: QueryType
    ocr_fallback: bool
    visual_status: str | None
    counts: dict
    query_photo: bool
    query_name: str | None
    split_name: str | None
    goods: frozenset[str] | None
    x3_on: bool
    has_image: bool
    index_size: int
    model: dict
    embedding: np.ndarray | None = None  # 질의 이미지 임베딩(분석 스크립트가 같은 질의를 다시 채점)
    timings: dict = field(default_factory=dict)  # 단계별 ms(STAGES — 응답에 넣지 않음, 분석용)


@dataclass(frozen=True)
class QueryContext:
    """한 질의의 채점 맥락 — score_record 가 후보 하나를 채점할 때 쓴다."""

    name: str | None
    goods: frozenset[str] | None
    embedding: np.ndarray | None
    query_type: QueryType
    photo: bool  # 질의 이미지가 사진(src.photo_mark)
    nameless_floor: bool  # 유형을 도형계로 고친 질의 + 이름 + 이미지(계약 §2-4 6항)
    logo_floor: bool  # 그 밖의 이름 + 이미지(사진 아님) — 계수 JSON 이 켤 때(v1.4.2)
    nameless_level: str  # 같은 입력에서 이름을 뺀 질의의 유형(이미지만 판단에 쓴다)
    x3_on: bool
    model: dict
    distinct: object


def nameless_level(query_type: QueryType) -> str:
    """같은 입력에서 이름을 뺀 질의가 받을 유형(계약 §2-4 5항) — 이미지만 판단(logo_floor)에
    쓴다. 사용자 유형은 이름 없이 고른 것과 같게(결합 → 결합-도형요부, 문자·도형 그대로), 자동
    유형은 이름 없는 이미지 질의처럼 OCR 글자 영역 ≥ 0.05 면 결합-도형요부, 그 밖·OCR 실패면 도형.
    이름 없는 계수 집합은 도형계에만 ×도형계 항이 있어, 이름 있는 질의의 유형(문자계)을 그대로
    쓰면 같은 로고가 0.634(위험) 대신 0.556(검토 권장)이 된다."""
    if query_type.source == "user":
        return "결합-도형요부" if query_type.type.startswith("결합") else query_type.type
    text_ratio = (query_type.detail or {}).get("text_ratio")
    if text_ratio is not None and float(text_ratio) >= mt.TEXT_RATIO_FIGURE:
        return "결합-도형요부"
    return "도형"


def make_context(name: str | None, goods: frozenset[str] | None, embedding: np.ndarray | None,
                 query_type: QueryType, x3_on: bool) -> QueryContext:
    """질의 맥락. 사진 판정과 이름을 뺀 판단과의 비교 두 가지 — nameless_floor(유형을 도형계로 고친
    질의 + 이름 + 이미지, 예전 그대로)·logo_floor(그 밖의 이름 + 이미지, 사진 아님, 계수 JSON 이 켤
    때 — 이미지만 판단)를 여기서 정한다."""
    if state.model is None or state.distinct is None:
        raise ModelNotReadyError(state.error or "통합 모델이 준비되지 않았습니다.")
    photo = is_photo_query(embedding)
    named_image = name is not None and embedding is not None
    user_figure = query_type.source == "user" and query_type.type in rm.FIGURE_FAMILY
    return QueryContext(
        name=name, goods=goods, embedding=embedding, query_type=query_type, photo=photo,
        nameless_floor=user_figure and named_image,
        logo_floor=(rm.logo_floor_enabled(state.model) and named_image and not user_figure
                    and not photo),
        nameless_level=nameless_level(query_type),
        x3_on=x3_on, model=state.model, distinct=state.distinct,
    )


@dataclass(frozen=True)
class Judgment:
    """한 판단 — 위험도 결과·설계 항 값·규칙·정렬 위치."""

    result: rm.RiskResult
    values: dict
    triggers: tuple[str, ...]
    rank: tuple[int, float]


def _judge(features: dict, model: dict, query_type: str) -> Judgment:
    result = rm.risk_score(features, model)
    values = rm.design_values(features)
    return Judgment(result, values, _rule_triggers(values, model, query_type),
                    rank_position(result.prob, model, result.pattern))


def goods_floor_value(model: dict) -> float | None:
    """업종 하한(goods_floor)의 상품 겹침 기준 = 결합 하한 coupling.floors.x4(v1.3 JSON 0.0252)."""
    value = ((model.get("coupling") or {}).get("floors") or {}).get("x4")
    return None if value is None else float(value)


def _nameless_judgment(features: dict, model: dict,
                       query_type: str) -> tuple[Judgment, tuple[int, float]]:
    """이름 없는 판단(업종 하한 적용 뒤)과 정렬 위치(계약 v2 §2-4 8항). 이미지+상품 판단은 후보의
    상품 겹침 x4 가 결합 하한(goods_floor_value) 이상이면 상품을 가린 이미지만 판단과 등급을 견줘
    높은 쪽을 쓴다(같으면 이미지+상품 쪽; 이미지만 쪽이면 goods_floor). 겹침이 하한 아래면 그대로
    (업종이 다르면 내려가도 된다). 정렬 위치는 두 판단 중 높은 쪽."""
    judged = _judge(features, model, query_type)
    rank = judged.rank
    x4, floor = features.get("x4"), goods_floor_value(model)
    if (rm.is_nameless_pattern(judged.result.pattern) and features.get("x2_whole") is not None
            and x4 is not None and floor is not None):
        if float(x4) >= floor:
            image_only = _judge({**features, "x4": None}, model, query_type)
            rank = max(rank, image_only.rank)
            if rm.GRADES.index(image_only.result.grade) > rm.GRADES.index(judged.result.grade):
                judged = Judgment(image_only.result, image_only.values,
                                  image_only.triggers + (GOODS_FLOOR,), image_only.rank)
        elif rm.goods_cap_enabled(model):  # 업종 상한(§7-13) — 업종이 다르면 이미지만 판단 이하
            image_only = _judge({**features, "x4": None}, model, query_type)
            if rm.GRADES.index(judged.result.grade) > rm.GRADES.index(image_only.result.grade):
                judged = Judgment(image_only.result, image_only.values,
                                  image_only.triggers + (GOODS_CAP,), image_only.rank)
                rank = image_only.rank
    return judged, rank


def _named_judgment(features: dict, model: dict,
                    query_type: str) -> tuple[Judgment, tuple[int, float]]:
    """이름 있는 판단(업종 규칙 적용 뒤)과 정렬 위치(§7-13). 업종 집합(x4·x2_whole+x4)에
    goods_rule 이 있으면 업종이 겹칠 때(x4 ≥ 결합 하한) 업종 없는 짝 판단(x4 → base, x2_whole+x4 →
    x2_whole)과 등급을 견줘 높은 쪽(같으면 업종 집합 쪽; 짝 쪽이면 goods_floor_named, 정렬 위치는 둘
    중 높은 쪽). 업종 상한이 켜져 있으면 업종이 다를 때(x4 < 하한) 짝 판단보다 높지 않게(goods_cap,
    정렬 위치도 짝 판단). 둘 다 없는 JSON(≤ v1.4.5)은 그대로."""
    judged = _judge(features, model, query_type)
    rank = judged.rank
    pattern = judged.result.pattern
    x4, floor = features.get("x4"), goods_floor_value(model)
    if (not pattern or rm.is_nameless_pattern(pattern) or x4 is None or floor is None
            or rm.goods_pair_key(pattern, model.get("pattern_axes") or ()) is None):
        return judged, rank
    floor_on = ((model.get("patterns") or {}).get(pattern) or {}).get(
        rm.GOODS_RULE_KEY) == rm.GOODS_RULE_NO_RAISE
    if float(x4) >= floor:
        if not floor_on:
            return judged, rank
        pair = _judge({**features, "x4": None}, model, query_type)
        rank = max(rank, pair.rank)
        if rm.GRADES.index(pair.result.grade) > rm.GRADES.index(judged.result.grade):
            judged = Judgment(pair.result, pair.values, pair.triggers + (GOODS_FLOOR_NAMED,),
                              pair.rank)
    elif rm.goods_cap_enabled(model):
        pair = _judge({**features, "x4": None}, model, query_type)
        if rm.GRADES.index(judged.result.grade) > rm.GRADES.index(pair.result.grade):
            judged = Judgment(pair.result, pair.values, pair.triggers + (GOODS_CAP,), pair.rank)
            rank = pair.rank
    return judged, rank


def score_record(record: Record, ctx: QueryContext,
                 image_similarity: dict[int, float] | None = None,
                 timings: dict | None = None) -> CandidateResult:
    """후보 하나의 축·위험도. 이름 있는 판단(질의·후보 모두 이름)은 이름 있는 계수 집합, 그 밖은
    이름 없는 계수 집합(risk_model.select_pattern). 사진 질의의 이름 있는 판단은 이미지 축을 관측
    없음으로(학습에서 사진 쌍의 이미지를 뺀 것과 같게), 이름 없는 판단은 그대로."""
    model, distinct = ctx.model, ctx.distinct
    x2_img: float | None = None
    if ctx.embedding is not None and record.pos is not None:
        if state.embeddings is not None:
            x2_img = round(_clip01(float(state.embeddings[record.pos] @ ctx.embedding)), 4)
        elif image_similarity and record.pos in image_similarity:
            x2_img = round(image_similarity[record.pos], 4)
    axes: PairAxes | None = None
    if ctx.name and record.title:
        started = time.perf_counter()
        axes = compute_pair_axes(
            ctx.name, record.title, model=distinct, goods_a=ctx.goods, goods_b=record.goods,
            x3_enabled=ctx.x3_on, spelling_version=rm.spelling_version(model),
            weak_run_version=rm.weak_run_version(model),
        )
        if timings is not None:
            timings["축"] = timings.get("축", 0.0) + (time.perf_counter() - started) * 1000
        features = axes.model_features(x2_img=None if ctx.photo else x2_img,
                                       mark_type=ctx.query_type.type)
        x4 = axes.x4
        query_tokens, candidate_tokens = axes.query_tokens, axes.candidate_tokens
        removed = tuple(
            {"token": item.token, "reason": item.reason, "side": item.side}
            for item in axes.removed
        )
    else:
        x4 = (round(goods_similarity(ctx.goods, record.goods), 4)
              if ctx.goods and record.goods else None)
        features = {
            "x1_d": None, "x2_text_d": None, "x2_whole": x2_img, "x3_d": None, "x4": x4,
            "has_meaning_both": False, "has_distinctive_part_a": True,
            "has_distinctive_part_b": True, "mark_type": ctx.query_type.type,
        }
        query_tokens = ()
        candidate_tokens = tuple(
            token for token, _ in distinct.salient_tokens(record.title, ctx.goods)
        ) if record.title else ()
        removed = ()
    if axes is None:  # 이름 없는 판단 — 업종 하한(goods_floor)·상한(goods_cap)까지 적용
        judged, rank = _nameless_judgment(features, model, ctx.query_type.type)
    else:  # 이름 있는 판단 — 업종 집합이면 이름 있는 업종 하한·상한까지(§7-13)
        judged, rank = _named_judgment(features, model, ctx.query_type.type)
        if ctx.nameless_floor:
            # 이름을 뺀 판단(업종 하한 적용 뒤)과 견준다. 정렬 위치는 모든 판단 중 높은 쪽 — 등급이
            # 같아 이름 있는 판단을 보여 줄 때도 로고만의 판단이 더 높은 위치면 그 자리에 둔다
            other, other_rank = _nameless_judgment(
                _nameless_features({**features, "x2_whole": x2_img}), model, ctx.query_type.type)
            rank = max(rank, other_rank)
            if rm.GRADES.index(other.result.grade) > rm.GRADES.index(judged.result.grade):
                judged = Judgment(other.result, other.values, other.triggers + (NAMELESS_FLOOR,),
                                  other.rank)  # 같으면 이름 있는 쪽
    if ctx.logo_floor and x2_img is not None:
        # 이름도 업종도 뺀 "이미지만" 판단(유형은 이름 없이 넣었을 때의 유형)과 견준다 — 상표명
        # 없는 후보도. 업종이 들어간 이름 없는 판단은 쓰지 않는다(업종 겹침에 기대 무관한 로고도
        # 올리므로, 설계 §7-7·§7-9). 정렬 위치는 둘 중 높은 쪽, 등급이 같으면 원래 판단
        level = ctx.nameless_level
        other = _judge(_image_only_features(x2_img, level), model, level)
        rank = max(rank, other.rank)
        if rm.GRADES.index(other.result.grade) > rm.GRADES.index(judged.result.grade):
            judged = Judgment(other.result, other.values, other.triggers + (NAMELESS_FLOOR,),
                              other.rank)
    result, values, triggers = judged.result, judged.values, judged.triggers
    contributions, missing = _group_contributions(result.contributions)
    return CandidateResult(
        id=record.appno,
        title=record.title,
        image_url=storage.public_url(record.image_key),
        type=record.display_type,
        applicant=record.applicant,
        nice_classes=record.nice_classes,
        axes={
            "x1": axes.x1 if axes else None,
            "x2_text": axes.x2_text if axes else None,
            "x2_img": values["x2_whole"] if values["miss_x2img"] == 0.0 else None,
            "x3": axes.x3 if axes else None,
            "x4": x4,
        },
        prob=float(result.prob),
        grade=result.grade,
        contributions=contributions,
        missing_adjustment=missing,
        figure_caveat=result.figure_caveat,
        rule_triggers=triggers,
        query_tokens=query_tokens,
        candidate_tokens=candidate_tokens,
        removed=removed,
        goods_codes=tuple(sorted(record.goods)),
        jaccard=x4,
        pattern=result.pattern,
        rank=rank,
    )


def _validate_inputs(image, name, goods_codes, type_override, top_k):
    if not engine.state.ready:
        raise RuntimeError("Engine 이 아직 초기화되지 않았습니다.")
    if top_k is not None and (isinstance(top_k, bool) or not isinstance(top_k, int)
                              or not TOP_K_MIN <= top_k <= TOP_K_MAX):
        raise ValueError(f"top_k 는 {TOP_K_MIN}~{TOP_K_MAX} 정수여야 합니다 (받은 값: {top_k!r}).")
    query_name = clean_name(name) or None
    goods = valid_goods(goods_codes)[0] or None  # 형식이 안 맞는 코드는 무시(API 는 422)
    override = str(type_override).strip() if type_override is not None else ""
    if override and override not in mt.OVERRIDE_TYPES:
        raise ValueError(f"type_override 는 {'·'.join(mt.OVERRIDE_TYPES)} 중 하나여야 합니다.")
    if image is None and query_name is None and goods is None:
        raise EmptyQueryError("image, name, goods_codes 중 하나는 있어야 합니다.")
    return query_name, goods, override


def search_pool(
    image=None,
    name: str | None = None,
    goods_codes=None,
    type_override: str | None = None,
) -> PoolResult:
    """후보 풀 전체를 채점해 위험도 내림차순으로 돌려준다(top_k 로 자르지 않는다 — 분석·검산용,
    multi_search 가 이것을 잘라 응답을 만든다)."""
    query_name, goods, override = _validate_inputs(image, name, goods_codes, type_override, None)
    _ensure_fresh()
    if state.model is None or state.distinct is None or (
            rm.famous_check_enabled(state.model) and state.famous is None):
        raise ModelNotReadyError(state.error or "통합 모델이 준비되지 않았습니다.")
    model, distinct = state.model, state.distinct
    spelling = rm.spelling_version(model)  # 철자 축 정의 버전(계수 JSON axis_versions, 없으면 1)
    index_size = int(engine.state.index.ntotal)

    timings: dict[str, float] = {}
    clock = time.perf_counter()

    def lap(stage: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        timings[stage] = timings.get(stage, 0.0) + (now - clock) * 1000
        clock = now

    query_type, ocr_fallback = _resolve_query_type(image, query_name, override or None)
    lap("유형(OCR)")
    x3_on = bool(config.X3_ENABLED) and semantic_search.state.enabled

    # ---- 후보 풀 ----
    pool: dict[str, Record] = {}
    counts = {"image": 0, "phonetic": 0, "spelling": 0, "semantic": 0, "goods": 0, "total": 0}
    query_embedding: np.ndarray | None = None
    image_similarity: dict[int, float] = {}
    visual_status: str | None = None
    if image is not None:
        query_embedding = np.asarray(engine.encode_image(image), dtype=np.float32).reshape(-1)
        lap("이미지 임베딩")
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
        lap("이미지 풀")
    split_name = distinct.split_goods_suffix(query_name) if query_name else None
    if query_name:
        for match in phonetic_search.search(query_name, POOL_PHONETIC, 0.0).matches:
            record = state.by_appno.get(match.entry.application_number)
            if record is None or match.similarity <= 0.0:
                continue
            pool.setdefault(record.appno, record)
            counts["phonetic"] += 1
        lap("발음 풀")
        scored = [  # 철자 풀도 모델이 요구하는 철자 버전으로(v1.3·v1.4 = v1)
            (orthographic_similarity(query_name, record.title, version=spelling), record)
            for record in state.spelling_entries
        ]
        scored = [item for item in scored if item[0] > 0.0]
        scored.sort(key=lambda item: (-item[0], item[1].appno))
        for _, record in scored[:POOL_SPELLING]:
            pool.setdefault(record.appno, record)
            counts["spelling"] += 1
        lap("철자 풀")
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
            lap("관념 풀")
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
        lap("상품 풀")
    counts["total"] = len(pool)

    ctx = make_context(query_name, goods, query_embedding, query_type, x3_on)
    scored_candidates = [score_record(record, ctx, image_similarity, timings)
                         for record in pool.values()]
    lap("모델")  # 채점 전체 — 아래에서 축 시간을 뺀다
    timings["모델"] -= timings.get("축", 0.0)
    candidates = sorted(scored_candidates, key=_candidate_sort_key)
    lap("정렬")
    return PoolResult(
        candidates=tuple(candidates), query_type=query_type, ocr_fallback=ocr_fallback,
        visual_status=visual_status, counts=counts, query_photo=ctx.photo,
        query_name=query_name, split_name=split_name, goods=goods, x3_on=x3_on,
        has_image=image is not None, index_size=index_size, model=model,
        embedding=query_embedding, timings={k: round(v, 1) for k, v in timings.items()},
    )


def _overall(top: tuple[CandidateResult, ...]) -> tuple[str | None, float | None, str | None]:
    """(전체 등급, 전체 위험도, 그 등급을 정한 판단의 계수 집합). 전체 등급 = 후보 최대 등급, 그
    등급을 처음 낸 후보(정렬 순서)의 pattern 을 함께 낸다. 위험도는 그 판단과 같은 종류(이름 있는·
    없는)의 후보 가운데 최댓값 — 두 종류의 위험도 눈금이 달라 섞지 않는다(계약 §2-1)."""
    if not top:
        return None, None, None
    grade = max((candidate.grade for candidate in top), key=rm.GRADES.index)
    source = next(candidate for candidate in top if candidate.grade == grade)
    nameless = rm.is_nameless_pattern(source.pattern)
    prob = max(candidate.prob for candidate in top
               if rm.is_nameless_pattern(candidate.pattern) == nameless)
    return grade, prob, source.pattern


def _famous_query_kind(query_type: QueryType) -> str | None:
    """질의 이미지의 글자 위주·결합·도형 위주 — 검색이 이미 구한 유형 판정에서(OCR 을 새로 돌리지
    않는다). 자동 유형은 OCR 면적 비율, 사용자가 고른 유형은 그 유형, OCR 이 실패했으면 None."""
    if query_type.source == "user":
        return fr.kind_from_type(query_type.type)
    detail = query_type.detail or {}
    return fr.kind_from_ratios(detail.get("text_ratio"), detail.get("fig_ratio"))


def _famous_block(runtime: fr.Runtime, outcome: fr.Outcome) -> dict:
    """응답의 famous(계약 v2 §2-6) — 가장 강한 것부터 최대 두 브랜드."""
    def logo(appno: str) -> dict:
        record = state.by_appno.get(appno)
        return {"id": appno,
                "image_url": storage.public_url(record.image_key) if record else None}

    return {
        "status": fr.STATUS_CHECKED,
        "brand_count": runtime.brand_count,
        "matches": [
            {"brand": match.brand, "level": match.level, "basis": match.basis,
             "notation": match.notation, "matched_text": match.matched_text,
             "protection": match.protection, "goods_overlap": match.overlap,
             "floor": match.floor, "logos": [logo(appno) for appno in match.logos]}
            for match in outcome.matches],
    }


def multi_search(
    image=None,
    name: str | None = None,
    goods_codes=None,
    type_override: str | None = None,
    top_k: int = 5,
) -> SearchV2Result:
    """3입력 통합 검색(계약 v2). image 는 검증된 PIL 이미지(또는 encode_image 가 받는 형태), name 은
    상표명, goods_codes 는 유사군 코드 목록, type_override 는 문자·도형·결합 중 하나."""
    started = time.perf_counter()
    _validate_inputs(image, name, goods_codes, type_override, top_k)
    pooled = search_pool(image, name, goods_codes, type_override)
    model, query_type, goods = pooled.model, pooled.query_type, pooled.goods
    query_name, split_name, x3_on = pooled.query_name, pooled.split_name, pooled.x3_on
    top = pooled.candidates[:top_k]

    # ---- overall·caveats ----
    caveats: list[str] = []
    if query_type.type in rm.FIGURE_FAMILY:
        caveats.append((model.get("figure_rule") or {}).get("caveat") or CAVEAT_FIGURE_LOW_DATA)
    if query_type.suggested_name:
        caveats.append(CAVEAT_NAME_SUGGESTED.format(text=query_type.suggested_name))
    if pooled.ocr_fallback:
        label = mt.display_type(query_type.type)
        caveats.append(CAVEAT_OCR_FALLBACK.format(type=label, ro=_particle_ro(label)))
    if pooled.query_photo:
        caveats.append(CAVEAT_PHOTO_QUERY)
    if not pooled.has_image:
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
        if state.with_goods < pooled.index_size:  # 전건 보유면 내지 않는다
            caveats.append(CAVEAT_GOODS_COVERAGE.format(with_goods=f"{state.with_goods:,}",
                                                        total=f"{pooled.index_size:,}"))
        if not pooled.has_image and query_name is None:
            caveats.append(CAVEAT_GOODS_ONLY)
    if not top:
        caveats.append(CAVEAT_NO_CANDIDATES)
    overall_grade, overall_prob, overall_pattern = _overall(top)

    # ---- 유명 상표 확인(§7-14-13) — 검색과 별개. 후보 목록·후보 등급·위험도·정렬은 그대로 두고,
    # 판정이 준 바닥이 전체 등급보다 높을 때 전체 등급만 올린다. 예외가 나도 검색은 그대로 낸다
    famous: dict | None = None
    famous_floor: bool | None = None
    outcome: fr.Outcome | None = None
    famous_ms = 0.0
    runtime = state.famous if rm.famous_check_enabled(model) else None
    if runtime is not None:
        clock = time.perf_counter()
        try:
            outcome = fr.check(
                runtime, name=name if query_name is not None else None, goods=goods,
                ocr_text=query_type.suggested_name, embedding=pooled.embedding,
                query_kind=_famous_query_kind(query_type), query_photo=pooled.query_photo,
                level=nameless_level(query_type))
            famous = _famous_block(runtime, outcome)
        except Exception as exc:  # 검색어가 섞일 수 있는 예외 본문은 남기지 않는다
            outcome = None
            famous = {"status": fr.STATUS_UNAVAILABLE, "brand_count": runtime.brand_count,
                      "matches": []}
            logger.error("유명 상표 확인 실패(%s) — 검색 결과는 그대로 낸다", type(exc).__name__)
        famous_floor = False
        if outcome is not None and outcome.floor is not None and (
                overall_grade is None
                or rm.GRADES.index(outcome.floor) > rm.GRADES.index(overall_grade)):
            overall_grade, famous_floor = outcome.floor, True
        top = tuple(replace(candidate, famous_brand=runtime.brand_of_mark[candidate.id])
                    if candidate.id in runtime.brand_of_mark else candidate for candidate in top)
        famous_ms = (time.perf_counter() - clock) * 1000

    elapsed_ms = int(round((time.perf_counter() - started) * 1000))
    logger.info(
        "multi_search: pool=%s type=%s/%s photo=%s candidates=%d returned=%d famous=%s "
        "elapsed=%dms",
        pooled.counts, query_type.type, query_type.source, pooled.query_photo,
        len(pooled.candidates), len(top),
        "꺼짐" if famous is None else famous["status"], elapsed_ms,
    )
    return SearchV2Result(
        overall_grade=overall_grade,
        overall_prob=overall_prob,
        caveats=tuple(caveats),
        query_type=query_type,
        visual_status=pooled.visual_status,
        candidates=top,
        model_version=str(model.get("version")),
        grade_precision=float(state.grade_precision or 0.0),
        thresholds=_thresholds(model),
        pool=pooled.counts,
        elapsed_ms=elapsed_ms,
        dataset_info=dict(engine.state.dataset_info),
        index_size=pooled.index_size,
        top_k_requested=int(top_k),
        top_k_returned=len(top),
        overall_pattern=overall_pattern,
        famous=famous,
        famous_floor=famous_floor,
        famous_outcome=outcome,
        famous_ms=famous_ms,
    )
