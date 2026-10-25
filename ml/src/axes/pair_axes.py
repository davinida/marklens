"""쌍별 축 계산 — 서비스(backend/src/core/multi_search.py, API 계약 v2 §2-2)와 학습 특징
(ml/scripts/pairs_features.py::name_axes)이 **같은 식**으로 X1·X2 철자·X3·X4 와 요부(식별력) 정보를
내도록 한 곳에 둔다(계약 v2 §6 E-2).

식(통합 모델 설계 §4-3·식별력 설계 §2 축 연결):
    1. 이름 정리: NFKC·공백 정리 → 고시 단일 명칭 접미 분리(`Distinctiveness.split_goods_suffix`,
    E-3:
       블루커피 → 블루 커피). X1·X2 철자·X3·요부 판정이 모두 이 분리된 이름을 받는다.
    2. 제외 토큰 = `pair_generic(a, b, goods)` — 양쪽의 약한 토큰 합집합(요부 없는 이름은 넘기지
    않음,
       결합 규칙 v0.2·v0.3 이 요부로 되돌린 토큰 제외). goods 는 양쪽 유사군의 합집합(1호 보통명칭은
       상품에 상대적 — 학습도 `goods_codes_this ∪ goods_codes_prior`).
    3. x1 = phonetic_similarity(a, b, extra_generic=제외), x2_text = orthographic_similarity(…),
       x3 = semantic_similarity(…), x4 = goods_similarity(goods_a, goods_b).
    4. 게이트(결측): has_pronunciation·has_spelling·has_meaning 은 학습과 같이 제외 토큰 없이 양쪽
    다
       True 여야 값이 있고, 아니면 None. 모델 입력(`model_features`)은 학습 CSV 와 같은 수치를 쓴다
       —
       x1·x2_text 는 게이트와 무관한 원 값(게이트 꺼짐이면 함수가 0.0), x3 는 원 값 +
       has_meaning_both
       플래그(risk_model.design_values 가 결측 처리), x4 는 양쁙 코드가 있을 때만.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from . import x3_semantic as x3
from .distinctiveness import Distinctiveness
from .x1_phonetic import has_pronunciation, phonetic_similarity
from .x2_ortho import has_spelling, orthographic_similarity
from .x4_goods import goods_similarity, has_goods

__all__ = ["RemovedToken", "PairAxes", "clean_name", "compute_pair_axes", "normalize_codes"]

_SPACES = re.compile(r"\s+")


def clean_name(name: object) -> str:
    """상표명 정리 — NFKC 정규화 + 연속 공백 하나로 + 앞뒤 공백 제거(계약 §1 `name` 처리). 토큰화·
    대소문자는 축 함수의 normalize_name 에 맡긴다."""
    text = unicodedata.normalize("NFKC", "" if name is None else str(name))
    return _SPACES.sub(" ", text).strip()


def normalize_codes(codes: Iterable[str] | str | None) -> frozenset[str]:
    """유사군 코드 집합 정리(공백 제거·대문자, 빈 값 제외) — x4_goods 와 같은 규칙."""
    if codes is None:
        return frozenset()
    if isinstance(codes, str):
        codes = [codes]
    return frozenset(c.strip().upper() for c in codes if isinstance(c, str) and c.strip())


@dataclass(frozen=True)
class RemovedToken:
    token: str
    reason: str  # judge().reasons 를 "·" 로 이은 문자열
    side: str  # "query" | "candidate" | "both"


@dataclass(frozen=True)
class PairAxes:
    name_a: str  # 접미 분리까지 적용해 실제로 비교한 이름
    name_b: str
    x1: float | None  # 게이트 적용 표시값(계약 axes.*) — 결측이면 None
    x2_text: float | None
    x3: float | None
    x4: float | None
    x1_raw: float  # 게이트와 무관한 함수 값(학습 CSV x1_d 와 같은 수치)
    x2_text_raw: float
    x3_raw: float
    has_pronunciation_both: bool
    has_spelling_both: bool
    has_meaning_both: bool
    has_goods_both: bool
    has_distinctive_a: bool
    has_distinctive_b: bool
    query_tokens: tuple[str, ...]  # 요부 후보(점수 ≥ θ, 이름 순서)
    candidate_tokens: tuple[str, ...]
    removed: tuple[RemovedToken, ...]
    generic: frozenset[str]

    def model_features(self, *, x2_img: float | None, mark_type: str) -> dict:
        """risk_model.risk_score 입력 — 계수 JSON 입력 정의(x1_d·x2_text_d·x2_whole·x3_d·x4·
        has_meaning_both·has_distinctive_part_a/b·mark_type)와 키 이름을 1:1 로 맞춘다."""
        return {
            "x1_d": self.x1_raw,
            "x2_text_d": self.x2_text_raw,
            "x2_whole": x2_img,
            "x3_d": self.x3_raw,
            "x4": self.x4,
            "has_meaning_both": self.has_meaning_both,
            "has_distinctive_part_a": self.has_distinctive_a,
            "has_distinctive_part_b": self.has_distinctive_b,
            "mark_type": mark_type,
        }


def _reason(model: Distinctiveness, token: str, goods: frozenset[str] | None) -> str:
    return "·".join(model.judge(token, goods).reasons)


def compute_pair_axes(
    name_a: str,
    name_b: str,
    *,
    model: Distinctiveness,
    goods_a: Iterable[str] | str | None = None,
    goods_b: Iterable[str] | str | None = None,
    x3_enabled: bool = True,
) -> PairAxes:
    """질의 이름 A 와 후보 이름 B 의 축 점수·요부 정보. 이름이 비면 호출하지 않는다(엔진이 결측
    처리).

    x3_enabled=False(MARKLENS_X3_ENABLED=0)면 x3 는 None·has_meaning_both False 로 두어 모델이
    관념을
    결측으로 본다.
    """
    a = model.split_goods_suffix(clean_name(name_a))
    b = model.split_goods_suffix(clean_name(name_b))
    codes_a, codes_b = normalize_codes(goods_a), normalize_codes(goods_b)
    goods = (codes_a | codes_b) or None
    generic = model.pair_generic(a, b, goods)

    x1_raw = phonetic_similarity(a, b, extra_generic=generic)
    x2_raw = orthographic_similarity(a, b, extra_generic=generic)
    pron_both = has_pronunciation(a) and has_pronunciation(b)
    spell_both = has_spelling(a) and has_spelling(b)
    if x3_enabled:
        meaning_both = x3.has_meaning(a) and x3.has_meaning(b)
        x3_raw = x3.semantic_similarity(a, b, extra_generic=generic)
    else:
        meaning_both, x3_raw = False, 0.0
    goods_both = has_goods(codes_a) and has_goods(codes_b)
    x4 = goods_similarity(codes_a, codes_b) if goods_both else None

    weak_a = model.weak_tokens(a, goods)
    weak_b = model.weak_tokens(b, goods)
    removed: list[RemovedToken] = []
    seen: set[str] = set()
    for token in [j.token for j in model.judge_name(a, goods)] + [
        j.token for j in model.judge_name(b, goods)
    ]:
        if token in generic and token not in seen:
            seen.add(token)
            side = "both" if token in weak_a and token in weak_b else (
                "query" if token in weak_a else "candidate"
            )
            removed.append(RemovedToken(token, _reason(model, token, goods), side))

    return PairAxes(
        name_a=a,
        name_b=b,
        x1=round(x1_raw, 4) if pron_both else None,
        x2_text=round(x2_raw, 4) if spell_both else None,
        x3=round(x3_raw, 4) if meaning_both else None,
        x4=round(x4, 4) if x4 is not None else None,
        x1_raw=x1_raw,
        x2_text_raw=x2_raw,
        x3_raw=x3_raw,
        has_pronunciation_both=pron_both,
        has_spelling_both=spell_both,
        has_meaning_both=meaning_both,
        has_goods_both=goods_both,
        has_distinctive_a=model.has_distinctive_part(a, goods),
        has_distinctive_b=model.has_distinctive_part(b, goods),
        query_tokens=tuple(token for token, _ in model.salient_tokens(a, goods)),
        candidate_tokens=tuple(token for token, _ in model.salient_tokens(b, goods)),
        removed=tuple(removed),
        generic=generic,
    )
