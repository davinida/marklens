"""통합 모델 런타임(v1 → v1.1 → v1.2 → v1.3 → v1.4) — 4축 점수(X1 호칭·X2 외관·X3 관념·X4 상품)를
출처
혼동 위험도 p(0~1)·등급·기여도·도형 주의 표시로 합치는 순수 함수. 설계는
docs/MarkLens_통합모델_설계.md §3·§4-3·§7·§7-1·§7-2·§7-3.

계수는 JSON(`shared/model/risk_model_v1.json`, 학습 스크립트 `ml/scripts/train_risk_model.py` 가
쓴다)에서 읽는다 — 입력 정의·계수·절편·등급 임계값·단독 임계값·학습 메타. 픽클 없음, numpy 없음.
서비스 연결은 backend/src/core/multi_search.py(2026-10-24).

    risk_score({"x1_d": 0.95, "x2_text_d": 0.8, "x2_whole": 0.6, "x3_d": None, "x4": 1.0,
                "has_meaning_both": False, "has_distinctive_part_a": True,
                "has_distinctive_part_b": True, "mark_type": "문자"})
    → RiskResult(prob, grade, contributions, figure_caveat, pattern)   # 기여도 합 = 로짓

입력 규약(§4-3): 축 점수가 None 이면 결측. X3 는 `has_meaning_both` 가 False 면 게이트 꺼짐 =
결측. 상표 유형은 문자·도형·결합-문자요부·결합-도형요부, 그 밖(미상·결합)은 문자. 교호작용
x1_d×문자계(문자·결합-문자요부)·x2_whole×도형계(도형·결합-도형요부). v1.1 계수 JSON(§7-1)은 유형
주효과·miss_x1·miss_x2text 를 쓰지 않고(유형은 교호작용으로만), `monotone` 이 있으면 적재 때 단조
제약(유사도 축 본체 ≥ 0, 본체 + 교호작용 ≥ 0)을 검증한다. 단독 임계값 `standalone_thresholds`
(정밀도 ≥ 0.7 지점)는 축 하나가 τ 이상이면 등급 하한을 "검토 권장"으로. v1.2(§7-2): 요부 플래그는
`any_no_distinctive`(한쪽이라도 요부 없음) 하나와 교호작용 x1_d×any_no_distinctive(2000후2453 —
요부 없는 쌍은 호칭을 덜 믿음), 도형계(도형·결합-도형요부) 입력에는 `figure_caveat` True(검증
데이터 부족 — 참고용)와 `figure_rule`(x2_whole ≥ 0.9 면 등급 하한 검토 권장, 미검증 제품 규칙)을
적용한다.

v1.3(§7-3) — 결측 패턴별 계수 집합: ≤ v1.2.1 은 결측 축을 "값 0 + 결측 지시변수(miss_*) 1" 로
넣었는데, 지시변수 계수(+0.50·+0.31·+0.28)가 실제 축 기여보다 커서 입력을 더 주면 위험도가
내려갔다. v1.3 JSON 은 `pattern_axes`(결측 패턴을 가르는 축, 기본 x2_whole·x4)의 관측 조합마다
계수 집합 `patterns[키]`(features·coefficients·intercept)를 두고, `risk_score` 가 입력에 따라 하나를
고른다(관측된 축만 입력에 있고 지시변수는 없다; X3 게이트 결측은 값 0). 키는 pattern_axes 순서로
관측된 축 이름을 "+" 로 이은 것, 하나도 없으면 "base". 최상위 features·coefficients·intercept 는
`reference_pattern`(모든 축 관측)의 것을 그대로 두어(기준 절편) 옛 코드도 읽을 수 있고, 기여도의
`miss_pattern` = 패턴 절편 − 기준 절편(결측 때문에 생긴 로짓 보정; 엔진은 missing_adjustment 로
묶는다). `coupling`(결합 제약)이 있으면 적재 때 "축 하나를 하한값(`floors`, 현실 분포 비유사 쌍
평균)으로 더 관측해도 로짓이 내려가지 않음"을 설계 항 상자의 모든 꼭짓점에서 검증한다 — 입력을
더 주면 p 가 내려가지 않는다는 보장(`coupling_violations`).

v1.4(§7-4) — 이름 없는 입력의 계수 집합: v1.3 은 이름(호칭·철자) 축이 없는 입력도 이름 있는
패턴에 이름 항 0 을 넣어 계산했다. v1.4 JSON 은 `nameless_patterns`(키는 `patterns` 와 같은 패턴 키,
이미지가 관측된 것만 — 이미지만 `x2_whole` / 이미지+상품 `x2_whole+x4`)를 더 두고, x1_d·x2_text_d
가 둘 다 결측인 입력에 그 패턴 키가 있으면 그 집합을 쓴다(`RiskResult.pattern` 은 "noname:" + 키;
입력 항은 이미지·상품 항뿐). 이름도 이미지도 없는 입력(상품만 등)은 종전대로 `patterns` 의 집합에
이름 항 0. 결합 제약은 이름 쪽으로도 넓혀 적재 때 검증한다 — 이름 없는 패턴 안에서 축 하나를 더
관측하는 것(하한 이상이면 로짓 비감소)과 이름을 더 관측하는 것. 이름 쪽 제약은 JSON 이 가진 키로
정해진다: `coupling.same_name`(2차 시도 — 이름 없는 입력에 후보와 **같은 이름**(호칭·철자 1.0)을
더했을 때의 이름 있는 패턴 로짓 ≥ 이름 없는 패턴 로짓; 더한 뒤의 유형은 서비스 규칙대로 문자계
`type_with_name`, 요부 유무 양쪽, 이미지·상품 값의 모든 꼭짓점) 또는 `coupling.name_floors`(1차
시도 — 이름을 쉬운 음성 평균 이상으로 더 관측하면 비감소; 채택되지 않은 형식이고 그 학습 스크립트의
재현용으로만 남긴다). `nameless_patterns` 가 없는 JSON(≤ v1.3)의 계산은 달라지지 않는다.

서비스 기본 모델(2026-11-20, §7-4-4): DEFAULT_MODEL_PATH = `shared/model/risk_model_v1.4.json`
(MODEL_VERSION risk_model_v1.4). v1.3 파일(`risk_model_v1.json`)은 V13_MODEL_PATH 로 남는다 — v1.3
학습 스크립트와 v1.4 비교·학습 스크립트가 그 경로를 쓴다(기본 경로를 덮어쓰지 않게).

이름 없는 입력의 등급 하한(§7-4-3): 이름 없는 계수 집합은 `grade_thresholds` 를 따로 둘 수 있고,
그 집합이 쓰인 입력의 등급은 그 하한으로 매긴다(`grade_thresholds_for`; 없으면 최상위 하한). 하한이
null 인 등급은 위험도 p 로는 닿지 않는다 — 단독 규칙(도형 규칙 τ)으로만 닿는다. 이름 있는 입력과
v1.3 이하 JSON 의 등급 판정은 달라지지 않는다.

축 계산 버전(§7-5, 2026-11-20): JSON 의 `axis_versions`(예: {"x2_text": 2})는 그 계수가 학습된 축
정의의 버전이다 — 없으면 모두 1(v1.3·v1.4). 입력의 `x2_text_version`(pair_axes.model_features 가
싣는다; 없으면 1)이 모델의 철자 버전과 다르고 x2_text_d 가 관측된 입력이면 `risk_score` 가
ValueError 를 낸다 — 다른 정의로 계산한 철자 점수에 계수를 곱하지 않게.
"""

from __future__ import annotations

import functools
import json
import math
import os
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

__all__ = [
    "risk_score", "RiskResult", "design_values", "design_vector", "load_model", "validate_model",
    "grade_for", "axis_contributions", "mark_type_level", "monotone_violations",
    "coupling_violations", "coupling_vertices", "select_pattern", "pattern_key", "pattern_keys",
    "block_logit", "GRADES", "TYPE_LEVELS", "AXIS_INPUTS", "FIGURE_FAMILY", "PATTERN_BASE_KEY",
    "DEFAULT_MODEL_PATH", "V13_MODEL_PATH", "V14_MODEL_PATH", "ENV_MODEL_PATH", "NAMELESS_KEY",
    "NAMELESS_PREFIX", "NAME_AXES", "is_nameless_pattern", "nameless_grade_thresholds",
    "SEARCH_THRESHOLDS_METHOD", "OverwriteRefused", "search_calibrated", "check_nameless_overwrite",
    "NAME_FLOOR_AXES", "NAME_DERIVED_TERMS", "name_missing", "nameless_vertices",
    "name_coupling_vertices", "SAME_NAME_KEY", "type_with_name", "same_name_input",
    "grade_thresholds_for", "AXIS_VERSIONS_KEY", "SPELLING_AXIS", "SPELLING_VERSION_INPUT",
    "SUPPORTED_SPELLING_VERSIONS", "spelling_version",
]

REPO_ROOT = Path(__file__).resolve().parents[3]
V13_MODEL_PATH = REPO_ROOT / "shared" / "model" / "risk_model_v1.json"  # v1.3(이름 있는 계수)
V14_MODEL_PATH = REPO_ROOT / "shared" / "model" / "risk_model_v1.4.json"
DEFAULT_MODEL_PATH = V14_MODEL_PATH  # 서비스 기본 모델(2026-11-20 부터 v1.4)
ENV_MODEL_PATH = "MARKLENS_RISK_MODEL"
MODEL_VERSION = "risk_model_v1.4"  # 서비스 기본 모델의 버전
SUPPORTED_VERSIONS = ("risk_model_v1", "risk_model_v1.1", "risk_model_v1.2", "risk_model_v1.2.1",
                      "risk_model_v1.3", "risk_model_v1.4", "risk_model_v1.5")
AXIS_VERSIONS_KEY = "axis_versions"  # 계수가 학습된 축 정의의 버전(없으면 모두 1)
SPELLING_AXIS = "x2_text"
SPELLING_VERSION_INPUT = "x2_text_version"  # 입력이 x2_text_d 를 계산한 철자 버전(없으면 1)
SUPPORTED_SPELLING_VERSIONS = (1, 2)  # = ml/src/axes/x2_ortho.SPELLING_VERSIONS(테스트로 고정)
INTERACTION_OF = {"x1_d": "x1_d×문자계", "x2_whole": "x2_whole×도형계"}
MONOTONE_AXES = ("x1_d", "x2_text_d", "x2_whole", "x3_d", "x4")
X1_EXTRA_INTERACTIONS = ("x1_d×any_no_distinctive",)  # x1 효과에 더해지는 교호작용(요부 없음)

AXIS_INPUTS = (
    ("x1_d", "miss_x1"), ("x2_text_d", "miss_x2text"), ("x2_whole", "miss_x2img"),
    ("x3_d", "miss_x3"), ("x4", "miss_x4"),
)
MISS_OF = dict(AXIS_INPUTS)
PATTERN_BASE_KEY = "base"  # v1.3: 패턴 축이 하나도 관측되지 않은 입력의 계수 집합
PATTERNABLE_AXES = ("x2_whole", "x4")  # 결측 패턴을 가를 수 있는 축(x3 는 게이트 결측 → 값 0)
# v1.4: 이름 없는 입력의 계수 집합
NAMELESS_KEY = "nameless_patterns"
NAMELESS_PREFIX = "noname:"  # RiskResult.pattern 표기 — "noname:x2_whole" 등
NAME_AXES = ("x1_d", "x2_text_d")  # 둘 다 결측이면 이름 없는 입력
NAME_FLOOR_AXES = ("x1_d", "x2_text_d", "x3_d")  # coupling.name_floors 의 키
SAME_NAME_KEY = "same_name"  # coupling.same_name — "같은 이름을 더하면 내려가지 않음"의 기준점
NAME_DERIVED_TERMS = frozenset({  # 이름에서 나오는 설계 항 — 이름 없는 계수 집합에 둘 수 없다
    "x1_d", "x2_text_d", "x3_d", "miss_x1", "miss_x2text", "miss_x3", "has_meaning_both",
    "x3_d×has_meaning_both", "x1_d×문자계", "x1_d×any_no_distinctive", "x1_d×no_distinctive",
    "any_no_distinctive", "has_distinctive_part_a", "has_distinctive_part_b",
})
TYPE_LEVELS = ("문자", "도형", "결합-문자요부", "결합-도형요부")
TEXT_FAMILY = ("문자", "결합-문자요부")
FIGURE_FAMILY = ("도형", "결합-도형요부")
GRADES = ("안전", "주의", "검토 권장", "위험")
GRADE_THRESHOLD_KEYS = ("주의", "검토 권장", "위험")  # 등급 i 의 하한 p (안전은 0)
REVIEW_GRADE = "검토 권장"
# 기여도를 "근거 축"으로 묶을 때의 항 → 축
TERM_AXIS = {
    "x1_d": "X1", "miss_x1": "X1", "x1_d×문자계": "X1",
    "x2_text_d": "X2", "miss_x2text": "X2", "x2_whole": "X2", "miss_x2img": "X2",
    "x2_whole×도형계": "X2",
    "x3_d": "X3", "miss_x3": "X3", "has_meaning_both": "X3", "x3_d×has_meaning_both": "X3",
    "x4": "X4", "miss_x4": "X4",
    "has_distinctive_part_a": "요부", "has_distinctive_part_b": "요부",
    "any_no_distinctive": "요부",
    "type_도형": "유형", "type_결합-문자요부": "유형", "type_결합-도형요부": "유형",
    "x1_d×no_distinctive": "X1", "x1_d×any_no_distinctive": "X1",
    "miss_pattern": "결측",  # v1.3 패턴 절편 − 기준 절편
}


class RiskResult(NamedTuple):
    """risk_score 결과: 위험도 p, 등급, 항별 기여도(합 = 로짓), 도형 주의 표시(v1.2), 쓴 결측
    패턴 키(v1.3; 패턴 없는 JSON 이면 "")."""

    prob: float
    grade: str
    contributions: dict[str, float]
    figure_caveat: bool
    pattern: str = ""


def mark_type_level(value: object) -> str:
    """상표 유형 지시변수 수준: 네 유형 외(미상·결합·빈값)는 문자."""
    text = str(value or "").strip()
    return text if text in TYPE_LEVELS else "문자"


def _present(value: object) -> bool:
    if value is None or value == "":
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return not math.isnan(number)


def _flag(features: dict, key: str, default: bool) -> float:
    value = features.get(key)
    if value is None or value == "":
        return 1.0 if default else 0.0
    return 1.0 if value in (True, 1, "1", "True", "true") or (
        isinstance(value, (int, float)) and float(value) != 0.0
    ) else 0.0


def _meaning_both(features: dict) -> bool:
    if "has_meaning_both" in features and features["has_meaning_both"] not in (None, ""):
        return _flag(features, "has_meaning_both", True) == 1.0
    if "has_meaning_a" in features or "has_meaning_b" in features:
        return _flag(features, "has_meaning_a", False) == 1.0 and (
            _flag(features, "has_meaning_b", False) == 1.0
        )
    return True  # 게이트 정보가 없으면 x3_d 가 있을 때 그대로 쓴다


def spelling_version(model: dict) -> int:
    """그 모델의 계수가 학습된 철자(X2 문자 외관) 정의 버전 — `axis_versions.x2_text`, 없으면 1."""
    return int((model.get(AXIS_VERSIONS_KEY) or {}).get(SPELLING_AXIS, 1))


def _check_spelling_version(features: dict, values: dict[str, float], model: dict) -> None:
    """x2_text_d 가 관측된 입력의 철자 버전이 모델과 다르면 ValueError."""
    if values["miss_x2text"] != 0.0:
        return
    given = features.get(SPELLING_VERSION_INPUT)
    given = 1 if given in (None, "") else int(given)
    required = spelling_version(model)
    if given != required:
        raise ValueError(f"risk_model: 입력의 철자 버전 v{given} 이 모델({model.get('version')})이 "
                         f"요구하는 v{required} 와 다릅니다 — pair_axes.compute_pair_axes("
                         f"spelling_version={required}) 로 계산하세요")


def design_values(features: dict) -> dict[str, float]:
    """입력 사전 → 모든 설계 항의 값(계수 JSON 의 features 가 이 중 일부를 고른다)."""
    values: dict[str, float] = {}
    meaning_both = _meaning_both(features)
    for axis, miss in AXIS_INPUTS:
        raw = features.get(axis)
        present = _present(raw) and not (axis == "x3_d" and not meaning_both)
        values[axis] = float(raw) if present else 0.0
        values[miss] = 0.0 if present else 1.0
    values["has_meaning_both"] = 1.0 - values["miss_x3"]
    values["has_distinctive_part_a"] = _flag(features, "has_distinctive_part_a", True)
    values["has_distinctive_part_b"] = _flag(features, "has_distinctive_part_b", True)
    level = mark_type_level(features.get("mark_type", features.get("상표유형")))
    for name in TYPE_LEVELS[1:]:
        values[f"type_{name}"] = 1.0 if level == name else 0.0
    values["x1_d×문자계"] = values["x1_d"] if level in TEXT_FAMILY else 0.0
    values["x2_whole×도형계"] = values["x2_whole"] if level in FIGURE_FAMILY else 0.0
    values["x3_d×has_meaning_both"] = values["x3_d"] * values["has_meaning_both"]
    no_distinctive = 1.0 - values["has_distinctive_part_a"] * values["has_distinctive_part_b"]
    values["any_no_distinctive"] = no_distinctive
    values["x1_d×any_no_distinctive"] = values["x1_d"] * no_distinctive
    values["x1_d×no_distinctive"] = values["x1_d×any_no_distinctive"]  # v1.1 보조 항 이름
    return values


def design_vector(features: dict, names: list[str] | tuple[str, ...]) -> list[float]:
    """계수 JSON 의 features 순서대로 값 목록. 모르는 항 이름이면 ValueError."""
    values = design_values(features)
    unknown = [name for name in names if name not in values]
    if unknown:
        raise ValueError(f"모르는 설계 항: {unknown}")
    return [values[name] for name in names]


# ---- v1.3 결측 패턴 ---------------------------------------------------------------------------

def pattern_key(present: Iterable[str], axes: Iterable[str]) -> str:
    """패턴 키 — pattern_axes 순서로 관측된 축 이름을 "+" 로 이은 것, 하나도 없으면 "base"."""
    chosen = set(present)
    return "+".join(axis for axis in axes if axis in chosen) or PATTERN_BASE_KEY


def pattern_keys(axes: Iterable[str]) -> list[str]:
    """pattern_axes 의 모든 관측 조합 키(base 부터, 축 수가 적은 것부터)."""
    axes = list(axes)
    keys = []
    for mask in range(2 ** len(axes)):
        keys.append(pattern_key([axis for i, axis in enumerate(axes) if mask >> i & 1], axes))
    return sorted(dict.fromkeys(keys), key=lambda key: (0 if key == PATTERN_BASE_KEY else
                                                       key.count("+") + 1, key))


def pattern_present(key: str) -> list[str]:
    """패턴 키 → 관측된 패턴 축 목록."""
    return [] if key == PATTERN_BASE_KEY else key.split("+")


def name_missing(values: dict[str, float]) -> bool:
    """이름 없는 입력인가 — 이름 축(x1_d·x2_text_d)이 둘 다 결측."""
    return all(values[MISS_OF[axis]] == 1.0 for axis in NAME_AXES)


def select_pattern(model: dict, values: dict[str, float]) -> tuple[str, dict]:
    """v1.3: 관측된(miss_* = 0) 패턴 축의 조합으로 `patterns[키]` 를 고른다. 패턴이 없는(≤ v1.2.1)
    JSON 이면 ("", model) — 최상위 계수 집합 그대로. v1.4: 이름 없는 입력이고
    `nameless_patterns` 에 그 키가 있으면 ("noname:" + 키, 그 집합)."""
    patterns = model.get("patterns")
    if not patterns:
        return "", model
    axes = model.get("pattern_axes") or ()
    key = pattern_key([axis for axis in axes if values[MISS_OF[axis]] == 0.0], axes)
    nameless = model.get(NAMELESS_KEY)
    if nameless and key in nameless and name_missing(values):
        return NAMELESS_PREFIX + key, nameless[key]
    return key, patterns[key]


def block_logit(block: dict, values: dict[str, float]) -> float:
    """계수 집합(features·coefficients·intercept) 하나의 로짓."""
    coefficients = block["coefficients"]
    return float(block["intercept"]) + sum(
        float(coefficients[name]) * values[name] for name in block["features"]
    )


def coupling_vertices(sub_features: Iterable[str]) -> list[dict]:
    """패턴 결합 제약(축 하나를 더 관측해도 로짓이 내려가지 않음)을 검사할 입력 꼭짓점 목록.
    설계 항은 축 점수·플래그·유형의 다중선형 함수라 상자 꼭짓점에서 극값을 가진다 — 축 점수 0·1,
    요부 없음 유무, 문자계·도형계. 하위 패턴 입력(sub_features)에 있는 패턴 축은 0·1(그 축의
    결측 지시변수도 있으면 결측 상태도), 없는 축은 결측."""
    sub = set(sub_features)
    states = {}
    for axis in PATTERNABLE_AXES:
        if axis in sub:
            states[axis] = [0.0, 1.0] + ([None] if MISS_OF[axis] in sub else [])
        else:
            states[axis] = [None]
    meaning_states = [True, False] if "miss_x3" in sub else [True]
    out = []
    for x1 in (0.0, 1.0):
        for x2_text in (0.0, 1.0):
            for x3 in (0.0, 1.0):
                for meaning in meaning_states:
                    for distinctive in (True, False):
                        for level in ("문자", "도형"):
                            for x2_whole in states["x2_whole"]:
                                for x4 in states["x4"]:
                                    out.append({
                                        "x1_d": x1, "x2_text_d": x2_text, "x3_d": x3,
                                        "has_meaning_both": meaning,
                                        "has_distinctive_part_a": True,
                                        "has_distinctive_part_b": distinctive,
                                        "mark_type": level, "x2_whole": x2_whole, "x4": x4,
                                    })
    return out


def nameless_vertices(sub_features: Iterable[str]) -> list[dict]:
    """이름 없는 패턴끼리의 결합 제약(축 하나를 더 관측)을 검사할 꼭짓점 — 유형(문자계·도형계) ×
    하위 패턴 입력에 있는 패턴 축 0·1, 없는 축은 결측. 이름 축은 모두 결측."""
    sub = set(sub_features)
    states = {axis: ([0.0, 1.0] if axis in sub else [None]) for axis in PATTERNABLE_AXES}
    return [{"x1_d": None, "x2_text_d": None, "x3_d": None, "mark_type": level,
             "x2_whole": x2_whole, "x4": x4}
            for level in ("문자", "도형")
            for x2_whole in states["x2_whole"] for x4 in states["x4"]]


def name_coupling_vertices(sub_features: Iterable[str]) -> list[dict]:
    """이름을 더 관측하는 결합 제약(이름 없는 패턴 → 같은 키의 이름 있는 패턴)의 꼭짓점 —
    nameless_vertices 에 요부 없음 유무를 더한 것(요부 플래그는 이름을 관측해야 생긴다)."""
    return [{**vertex, "has_distinctive_part_a": True, "has_distinctive_part_b": distinctive}
            for vertex in nameless_vertices(sub_features) for distinctive in (True, False)]


def type_with_name(level: object) -> str:
    """이름 없는 입력에 이름이 생긴 뒤의 유형 — 서비스 규칙(API 계약 v2 §2-4 5항): 이름이 있으면
    항상 문자계. 도형계로 판정됐던 입력(도형 영역이 뚜렷함)은 결합-문자요부, 그 밖은 그대로(문자·
    결합-문자요부)."""
    level = mark_type_level(level)
    return "결합-문자요부" if level in FIGURE_FAMILY else level


def same_name_input(features: dict, same_name: dict | None = None, *,
                    distinctive: bool = True) -> dict:
    """이름 없는 입력에 후보와 같은 이름을 더한 입력: 호칭·철자 = `same_name` 의 값(기본 1.0),
    관념은 게이트가 꺼진 것으로(값 0 — 계수가 음이 아니므로 가장 낮은 경우), 유형은 type_with_name,
    요부 플래그는 distinctive(False = 요부 없는 이름)."""
    values = same_name or {}
    return {**features,
            **{axis: float(values.get(axis, 1.0)) for axis in NAME_AXES},
            "x3_d": None, "has_meaning_both": False,
            "mark_type": type_with_name(features.get("mark_type", features.get("상표유형"))),
            "has_distinctive_part_a": True, "has_distinctive_part_b": bool(distinctive)}


def _where(vertex: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in vertex.items()
                     if k in ("x1_d", "x2_text_d", "x3_d", "mark_type", "x2_whole", "x4")
                     and v is not None)


def _nameless_coupling_violations(model: dict, tolerance: float) -> list[str]:
    """v1.4: 이름 없는 패턴의 결합 제약 위반 — (a) 이름 없는 패턴 안에서 축 하나를 하한값으로 더
    관측 (b) `coupling.name_floors` 가 있으면 이름을 그 값으로 더 관측(같은 키의 이름 있는 패턴,
    관념 게이트는 켜진 상태로 값 = 하한 — 1차 시도 형식) (c) `coupling.same_name` 이 있으면 같은
    이름을 더한 입력(same_name_input — 유형은 문자계로, 요부 유무 양쪽)."""
    nameless = model.get(NAMELESS_KEY) or {}
    if not nameless:
        return []
    patterns = model.get("patterns") or {}
    coupling = model.get("coupling") or {}
    floors = coupling.get("floors") or {}
    name_floors = coupling.get("name_floors")
    axes = list(model.get("pattern_axes") or ())
    out = []
    for key, upper in nameless.items():
        present = pattern_present(key)
        for axis in present:
            lower_key = pattern_key([a for a in present if a != axis], axes)
            if axis not in floors or lower_key not in nameless:
                continue
            lower = nameless[lower_key]
            floor = float(floors[axis])
            for vertex in nameless_vertices(lower["features"]):
                low = block_logit(lower, design_values(vertex))
                high = block_logit(upper, design_values({**vertex, axis: floor}))
                if high < low - tolerance:
                    out.append(f"{NAMELESS_PREFIX}{lower_key} → {NAMELESS_PREFIX}{key} "
                               f"({axis} = {floor}) {round(high - low, 6)} @ {_where(vertex)}")
    if name_floors is not None:
        named = {axis: float(name_floors.get(axis, 0.0)) for axis in NAME_FLOOR_AXES}
        for key, lower in nameless.items():
            upper = patterns[key]
            for vertex in name_coupling_vertices(lower["features"]):
                low = block_logit(lower, design_values(vertex))
                high = block_logit(upper, design_values({**vertex, **named,
                                                         "has_meaning_both": True}))
                if high < low - tolerance:
                    out.append(f"{NAMELESS_PREFIX}{key} → {key} (이름 = {named}) "
                               f"{round(high - low, 6)} @ {_where(vertex)}, "
                               f"요부없음={not vertex['has_distinctive_part_b']}")
    same_name = coupling.get(SAME_NAME_KEY)
    if same_name is not None:
        for key, lower in nameless.items():
            upper = patterns[key]
            for vertex in nameless_vertices(lower["features"]):
                low = block_logit(lower, design_values(vertex))
                for distinctive in (True, False):
                    high = block_logit(upper, design_values(
                        same_name_input(vertex, same_name, distinctive=distinctive)))
                    if high < low - tolerance:
                        out.append(f"{NAMELESS_PREFIX}{key} → {key} (같은 이름) "
                                   f"{round(high - low, 6)} @ {_where(vertex)}, "
                                   f"요부없음={not distinctive}")
    return out


def coupling_violations(model: dict, tolerance: float = 1e-9) -> list[str]:
    """결합 제약을 어기는 (하위 패턴 → 상위 패턴, 축, 꼭짓점) 설명 목록. 상위 패턴은 하위 패턴에
    축 하나를 더 관측한 것, 그 축 값은 `coupling.floors[축]`(현실 분포 비유사 쌍 평균). 로짓 차가
    −tolerance 보다 작으면 위반. v1.4 JSON 이면 이름 없는 패턴의 제약(_nameless_coupling_violations)
    도 함께."""
    patterns = model.get("patterns") or {}
    floors = (model.get("coupling") or {}).get("floors") or {}
    axes = list(model.get("pattern_axes") or ())
    out = _nameless_coupling_violations(model, tolerance)
    for key, upper in patterns.items():
        present = pattern_present(key)
        for axis in present:
            if axis not in floors:
                continue
            lower_key = pattern_key([a for a in present if a != axis], axes)
            lower = patterns[lower_key]
            floor = float(floors[axis])
            for vertex in coupling_vertices(lower["features"]):
                low = block_logit(lower, design_values(vertex))
                high = block_logit(upper, design_values({**vertex, axis: floor}))
                if high < low - tolerance:
                    where = ", ".join(
                        f"{k}={v}" for k, v in vertex.items()
                        if k in ("x1_d", "x2_text_d", "x3_d", "mark_type", "x2_whole", "x4")
                        and v is not None
                    ) + f", 요부없음={not vertex['has_distinctive_part_b']}"
                    out.append(f"{lower_key} → {key} ({axis} = {floor}) {round(high - low, 6)} "
                               f"@ {where}")
    return out


# ---- 계수 JSON 검증 -----------------------------------------------------------------------------

def _validate_block(block: dict, label: str, known: dict) -> None:
    """계수 집합 하나(features·coefficients·intercept)를 검증한다."""
    if not isinstance(block, dict):
        raise ValueError(f"{label}: 계수 집합은 JSON 객체여야 합니다")
    names = block.get("features")
    if not isinstance(names, list) or not names or len(set(names)) != len(names):
        raise ValueError(f"{label}: features 는 비어 있지 않은 고유 이름 목록이어야 합니다")
    unknown = [name for name in names if name not in known]
    if unknown:
        raise ValueError(f"{label}: 모르는 설계 항 {unknown}")
    coefficients = block.get("coefficients")
    if not isinstance(coefficients, dict) or set(coefficients) != set(names):
        raise ValueError(f"{label}: coefficients 의 키가 features 와 같아야 합니다")
    for name, value in coefficients.items():
        if not isinstance(value, (int, float)) or math.isnan(float(value)):
            raise ValueError(f"{label}: 계수 {name} 가 숫자가 아닙니다")
    if not isinstance(block.get("intercept"), (int, float)):
        raise ValueError(f"{label}: intercept 는 숫자여야 합니다")


def _validate_patterns(data: dict, known: dict) -> None:
    axes = data.get("pattern_axes")
    if not isinstance(axes, list) or len(set(axes)) != len(axes) or any(
        axis not in PATTERNABLE_AXES for axis in axes
    ):
        raise ValueError(f"risk_model: pattern_axes 는 {PATTERNABLE_AXES} 의 부분 목록이어야 "
                         "합니다")
    patterns = data["patterns"]
    expected = pattern_keys(axes)
    if not isinstance(patterns, dict) or sorted(patterns) != sorted(expected):
        raise ValueError(f"risk_model: patterns 키는 {expected} 여야 합니다")
    for key, block in patterns.items():
        _validate_block(block, f"risk_model.patterns[{key}]", known)
        present = pattern_present(key)
        for axis in axes:
            if axis not in present and axis in block["features"]:
                raise ValueError(f"risk_model.patterns[{key}]: 관측되지 않은 축 {axis} 가 입력에 "
                                 "있음")
            if axis in present and MISS_OF[axis] in block["features"]:
                raise ValueError(f"risk_model.patterns[{key}]: 패턴 축 {axis} 의 결측 지시변수가 "
                                 "있음")
        if data.get("monotone"):
            for violation in monotone_violations(block["coefficients"]):
                raise ValueError(f"risk_model.patterns[{key}]: 단조 제약 위반 — {violation}")
    reference = data.get("reference_pattern")
    if reference not in patterns:
        raise ValueError("risk_model: reference_pattern 은 patterns 의 키여야 합니다")
    block = patterns[reference]
    if (data["features"] != block["features"] or data["coefficients"] != block["coefficients"]
            or data["intercept"] != block["intercept"]):
        raise ValueError("risk_model: 최상위 features·coefficients·intercept 는 "
                         "reference_pattern 의 계수 집합과 같아야 합니다")
    coupling = data.get("coupling")
    if coupling is not None:
        floors = coupling.get("floors") if isinstance(coupling, dict) else None
        if not isinstance(floors, dict) or any(
            axis not in axes or not isinstance(value, (int, float))
            or not 0.0 <= float(value) <= 1.0 for axis, value in floors.items()
        ):
            raise ValueError("risk_model: coupling.floors 는 {패턴 축: 0~1} 이어야 합니다")
        name_floors = coupling.get("name_floors") if isinstance(coupling, dict) else None
        if name_floors is not None and (not isinstance(name_floors, dict) or any(
            axis not in NAME_FLOOR_AXES or not isinstance(value, (int, float))
            or not 0.0 <= float(value) <= 1.0 for axis, value in name_floors.items()
        )):
            raise ValueError(f"risk_model: coupling.name_floors 는 {NAME_FLOOR_AXES} 의 값(0~1) "
                             "사전이어야 합니다")
        same_name = coupling.get(SAME_NAME_KEY) if isinstance(coupling, dict) else None
        if same_name is not None and (not isinstance(same_name, dict) or any(
            not isinstance(same_name.get(axis, 1.0), (int, float))
            or not 0.0 <= float(same_name.get(axis, 1.0)) <= 1.0 for axis in NAME_AXES
        )):
            raise ValueError(f"risk_model: coupling.{SAME_NAME_KEY} 는 {NAME_AXES} 의 값(0~1)을 "
                             "가진 사전이어야 합니다")
    nameless = data.get(NAMELESS_KEY)
    if nameless is not None:
        _validate_nameless(data, nameless, known)
    if coupling is not None:
        for violation in coupling_violations(data):
            raise ValueError(f"risk_model: 결합 제약 위반 — {violation}")


def _validate_nameless(data: dict, nameless: object, known: dict) -> None:
    """v1.4 `nameless_patterns` 검증: 키는 패턴 키의 부분집합, 입력 항은 이름에서 나오는 항이 없고
    키의 패턴 축과 맞아야 한다(단조 제약도 집합마다)."""
    axes = data["pattern_axes"]
    valid_keys = pattern_keys(axes)
    if not isinstance(nameless, dict) or not nameless or any(k not in valid_keys for k in nameless):
        raise ValueError(f"risk_model: {NAMELESS_KEY} 의 키는 {valid_keys} 의 부분집합이어야 "
                         "합니다")
    for key, block in nameless.items():
        label = f"risk_model.{NAMELESS_KEY}[{key}]"
        _validate_block(block, label, known)
        derived = sorted(NAME_DERIVED_TERMS & set(block["features"]))
        if derived:
            raise ValueError(f"{label}: 이름에서 나오는 항 {derived} 는 둘 수 없습니다")
        present = pattern_present(key)
        for axis in axes:
            if (axis in present) != (axis in block["features"]):
                raise ValueError(f"{label}: 입력의 패턴 축이 키와 다릅니다({axis})")
            if MISS_OF[axis] in block["features"]:
                raise ValueError(f"{label}: 결측 지시변수 {MISS_OF[axis]} 는 둘 수 없습니다")
        if data.get("monotone"):
            for violation in monotone_violations(block["coefficients"]):
                raise ValueError(f"{label}: 단조 제약 위반 — {violation}")
        thresholds = block.get("grade_thresholds")
        if thresholds is not None:
            if not isinstance(thresholds, dict) or set(thresholds) != set(GRADE_THRESHOLD_KEYS):
                raise ValueError(f"{label}: grade_thresholds 키는 {GRADE_THRESHOLD_KEYS} 여야 "
                                 "합니다")
            cuts = [thresholds[grade] for grade in GRADE_THRESHOLD_KEYS
                    if thresholds[grade] is not None]
            if any(not isinstance(cut, (int, float)) or not 0.0 < float(cut) <= 1.0
                   for cut in cuts) or any(a > b for a, b in zip(cuts, cuts[1:])):
                raise ValueError(f"{label}: grade_thresholds 는 null 또는 (0, 1] 안의 값이고 "
                                 "오름차순이어야 합니다")


def validate_model(data: dict) -> dict:
    """계수 JSON 검증 — 어긋나면 ValueError. 검증된 사전을 돌려준다."""
    if not isinstance(data, dict):
        raise ValueError("risk_model: JSON 객체가 아닙니다")
    if data.get("version") not in SUPPORTED_VERSIONS:
        raise ValueError(f"risk_model: version 은 {SUPPORTED_VERSIONS} 중 하나여야 합니다")
    known = design_values({})
    _validate_block(data, "risk_model", known)
    coefficients = data["coefficients"]
    thresholds = data.get("grade_thresholds")
    if not isinstance(thresholds, dict) or set(thresholds) != set(GRADE_THRESHOLD_KEYS):
        raise ValueError(f"risk_model: grade_thresholds 키는 {GRADE_THRESHOLD_KEYS} 여야 합니다")
    cuts = [float(thresholds[key]) for key in GRADE_THRESHOLD_KEYS]
    if not all(0.0 < cut <= 1.0 for cut in cuts) or any(a > b for a, b in zip(cuts, cuts[1:])):
        raise ValueError("risk_model: grade_thresholds 는 (0, 1] 안에서 오름차순이어야 합니다")
    versions = data.get(AXIS_VERSIONS_KEY)
    if versions is not None and (
        not isinstance(versions, dict) or set(versions) - {SPELLING_AXIS}
        or versions.get(SPELLING_AXIS, 1) not in SUPPORTED_SPELLING_VERSIONS
    ):
        raise ValueError(f"risk_model: {AXIS_VERSIONS_KEY} 는 {{'{SPELLING_AXIS}': "
                         f"{SUPPORTED_SPELLING_VERSIONS} 중 하나}} 여야 합니다")
    standalone = data.get("standalone_thresholds", {})
    if not isinstance(standalone, dict):
        raise ValueError("risk_model: standalone_thresholds 는 객체여야 합니다")
    axes = {axis for axis, _ in AXIS_INPUTS}
    for axis, tau in standalone.items():
        if axis not in axes:
            raise ValueError(f"risk_model: 단독 임계값의 축 {axis!r} 를 모릅니다")
        if tau is not None and not (isinstance(tau, (int, float)) and 0.0 <= float(tau) <= 1.0):
            raise ValueError(f"risk_model: 단독 임계값 {axis} 는 null 또는 0~1")
    if data.get("monotone"):
        for violation in monotone_violations(coefficients):
            raise ValueError(f"risk_model: 단조 제약 위반 — {violation}")
    rule = data.get("figure_rule")
    if rule is not None:
        if not isinstance(rule, dict) or not isinstance(rule.get("caveat"), str):
            raise ValueError("risk_model: figure_rule 은 caveat 문구를 가진 객체여야 합니다")
        threshold = rule.get("threshold")
        if threshold is not None and not (isinstance(threshold, (int, float))
                                          and 0.0 <= float(threshold) <= 1.0):
            raise ValueError("risk_model: figure_rule.threshold 는 null 또는 0~1")
    if data.get("patterns") is not None:
        _validate_patterns(data, known)
    return data


def monotone_violations(coefficients: dict, tolerance: float = 1e-9) -> list[str]:
    """단조 제약을 어기는 항 설명 목록 — 유사도 축 본체 ≥ 0, 본체 + 교호작용 ≥ 0. x1 은 문자계·요부
    없음 교호작용의 모든 조합(v1.2: 본체, +문자계, +요부없음, +둘 다)에서 ≥ 0. 입력에 없는 축은
    건너뛴다."""
    out = []
    for axis in MONOTONE_AXES:
        if axis not in coefficients:
            continue
        base = float(coefficients.get(axis, 0.0))
        if base < -tolerance:
            out.append(f"{axis} {base}")
        interaction = INTERACTION_OF.get(axis)
        combos = [[]]
        if interaction in coefficients:
            combos = combos + [combo + [interaction] for combo in combos]
        for name in (X1_EXTRA_INTERACTIONS if axis == "x1_d" else ()):
            if name in coefficients:
                combos = combos + [combo + [name] for combo in combos]
        for combo in combos:
            if not combo:
                continue
            total = base + sum(float(coefficients[name]) for name in combo)
            if total < -tolerance:
                out.append(f"{axis} + {' + '.join(combo)} {round(total, 4)}")
    return out


def resolve_model_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get(ENV_MODEL_PATH, "").strip()
    return Path(env) if env else DEFAULT_MODEL_PATH


@functools.lru_cache(maxsize=4)
def _load_cached(path_text: str) -> dict:
    return validate_model(json.loads(Path(path_text).read_text(encoding="utf-8")))


def load_model(path: str | os.PathLike[str] | None = None) -> dict:
    """계수 JSON 적재(경로: 인자 > MARKLENS_RISK_MODEL > DEFAULT_MODEL_PATH = shared/model/
    risk_model_v1.4.json). 프로세스 캐시 — 파일을 바꾸면 서버를 다시 띄운다."""
    return _load_cached(str(resolve_model_path(path)))


def grade_for(prob: float, thresholds: dict) -> str:
    """p 를 4단계로: 하한 이상이면 그 등급(위험 하한 이상 → 위험). 하한이 null 인 등급은 p 로는 닿지
    않는다(이름 없는 입력의 계수 집합에서만 — 그 등급은 단독 규칙으로만 닿는다)."""
    grade = GRADES[0]
    for key in GRADE_THRESHOLD_KEYS:
        cut = thresholds[key]
        if cut is not None and prob >= float(cut):
            grade = key
    return grade


# nameless_search_thresholds.py 가 쓴 이름 없는 하한의 meta method 접두
SEARCH_THRESHOLDS_METHOD = "실제 검색 기준"


class OverwriteRefused(RuntimeError):
    """이름 없는 입력의 실제 검색 기준 하한을 다른 방식으로 덮어쓰려 했다(--force 로만 허용)."""


def search_calibrated(model: dict) -> bool:
    """계수 JSON 의 이름 없는 하한이 실제 검색 기준(§7-4-4)으로 쓰였는가
    (meta.nameless.grade_thresholds.method)."""
    meta = ((model.get("meta") or {}).get("nameless") or {}).get("grade_thresholds") or {}
    return str(meta.get("method") or "").startswith(SEARCH_THRESHOLDS_METHOD)


def check_nameless_overwrite(path: str | os.PathLike[str], *, force: bool = False) -> None:
    """이름 없는 하한을 옛 방식으로 쓰는 스크립트(학습·쉬운 음성 기준 하한)가 쓰기 전에 부른다 —
    대상 JSON 의 meta 에 실제 검색 기준 하한이 있으면 force 없이는 OverwriteRefused. 검색 기준
    스크립트(nameless_search_thresholds.py)는 부르지 않는다."""
    target = Path(path)
    if force or not target.exists():
        return
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(existing, dict) and search_calibrated(existing):
        raise OverwriteRefused(
            f"{target} 의 이름 없는 하한은 실제 검색 기준(nameless_search_thresholds.py)으로 "
            "쓰였다 — 덮어쓰려면 --force(그 뒤 nameless_search_thresholds.py 를 다시 돌린다)")


def is_nameless_pattern(pattern: str | None) -> bool:
    """RiskResult.pattern 이 이름 없는 계수 집합("noname:…")인가."""
    return bool(pattern) and str(pattern).startswith(NAMELESS_PREFIX)


def nameless_grade_thresholds(model: dict) -> dict[str, dict]:
    """이름 없는 계수 집합의 등급 하한 — {"noname:x2_whole": {"주의": p, "검토 권장": p, "위험": p
    또는 None}, …}. 자기 하한이 없는 집합은 최상위 하한을 쓰므로 그 값을 싣는다."""
    out = {}
    for key, block in (model.get(NAMELESS_KEY) or {}).items():
        thresholds = block.get("grade_thresholds") or model["grade_thresholds"]
        out[NAMELESS_PREFIX + key] = {
            grade: None if thresholds[grade] is None else float(thresholds[grade])
            for grade in GRADE_THRESHOLD_KEYS}
    return out


def grade_thresholds_for(model: dict, pattern: str = "") -> dict:
    """그 계수 집합이 쓰인 입력의 등급 하한. `pattern` 은 RiskResult.pattern("x4"·"noname:x2_whole"
    등). 이름 없는 집합에 자기 `grade_thresholds` 가 있으면 그것, 아니면 최상위 하한."""
    if pattern.startswith(NAMELESS_PREFIX):
        block = (model.get(NAMELESS_KEY) or {}).get(pattern[len(NAMELESS_PREFIX):]) or {}
        if block.get("grade_thresholds"):
            return block["grade_thresholds"]
    return model["grade_thresholds"]


def risk_score(features: dict, model: dict | None = None) -> RiskResult:
    """RiskResult(위험도 p, 등급, 기여도, figure_caveat, pattern). 기여도는 항별 계수×값 +
    "intercept"(기준 절편; 합이 로짓). v1.3 패턴 JSON 이면 입력의 결측 패턴에 맞는 계수 집합을 쓰고
    "miss_pattern" = 패턴 절편 − 기준 절편을 기여도에 둔다(결측 때문에 생긴 로짓 보정 — 엔진의
    missing_adjustment).

    단독 임계값(97후3050 후단): 어느 한 축의 점수가 그 축의 τ 이상이면 등급을 최소 "검토 권장"으로
    올린다(자동 "위험"은 아니다). τ 가 null 인 축은 비활성. 도형 규칙(v1.2, `figure_rule`): 입력
    유형이 도형계면 figure_caveat True(화면 문구는 JSON `caveat`), x2_whole 이 있고 threshold
    이상이면 등급 하한 "검토 권장" — 도형계 쌍이 적어 데이터로 검증하지 못한 제품 규칙(`validated`
    false).
    """
    model = model or load_model()
    values = design_values(features)
    _check_spelling_version(features, values, model)
    key, block = select_pattern(model, values)
    coefficients = block["coefficients"]
    contributions: dict[str, float] = {"intercept": float(model["intercept"])}
    if key:
        contributions["miss_pattern"] = float(block["intercept"]) - float(model["intercept"])
    logit = sum(contributions.values())
    for name in block["features"]:
        term = float(coefficients[name]) * values[name]
        contributions[name] = term
        logit += term
    prob = 1.0 / (1.0 + math.exp(-logit)) if logit > -700 else 0.0
    grade = grade_for(prob, grade_thresholds_for(model, key))
    for axis, tau in (model.get("standalone_thresholds") or {}).items():
        if tau is None:
            continue
        miss = MISS_OF[axis]
        if values[miss] == 0.0 and values[axis] >= float(tau):
            if GRADES.index(grade) < GRADES.index(REVIEW_GRADE):
                grade = REVIEW_GRADE
    figure_caveat = False
    rule = model.get("figure_rule")
    if rule:
        level = mark_type_level(features.get("mark_type", features.get("상표유형")))
        if level in FIGURE_FAMILY:
            figure_caveat = True
            threshold = rule.get("threshold")
            if threshold is not None and values["miss_x2img"] == 0.0 and (
                values["x2_whole"] >= float(threshold)
            ) and GRADES.index(grade) < GRADES.index(REVIEW_GRADE):
                grade = REVIEW_GRADE
    return RiskResult(prob, grade, contributions, figure_caveat, key)


def axis_contributions(contributions: dict[str, float]) -> dict[str, float]:
    """항별 기여도를 축(X1·X2·X3·X4·유형·요부·결측)별로 묶는다 — 결과 화면 "근거 축" 표시용. 절편은
    뺀다."""
    out: dict[str, float] = {}
    for name, value in contributions.items():
        if name == "intercept":
            continue
        axis = TERM_AXIS.get(name, "기타")
        out[axis] = out.get(axis, 0.0) + value
    return out
