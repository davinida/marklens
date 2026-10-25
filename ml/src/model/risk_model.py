"""통합 모델 런타임(v1 → v1.1 → v1.2 → v1.3) — 4축 점수(X1 호칭·X2 외관·X3 관념·X4 상품)를 출처
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
    "DEFAULT_MODEL_PATH", "ENV_MODEL_PATH",
]

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL_PATH = REPO_ROOT / "shared" / "model" / "risk_model_v1.json"
ENV_MODEL_PATH = "MARKLENS_RISK_MODEL"
MODEL_VERSION = "risk_model_v1.3"
SUPPORTED_VERSIONS = ("risk_model_v1", "risk_model_v1.1", "risk_model_v1.2", "risk_model_v1.2.1",
                      "risk_model_v1.3")
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


def select_pattern(model: dict, values: dict[str, float]) -> tuple[str, dict]:
    """v1.3: 관측된(miss_* = 0) 패턴 축의 조합으로 `patterns[키]` 를 고른다. 패턴이 없는(≤ v1.2.1)
    JSON 이면 ("", model) — 최상위 계수 집합 그대로."""
    patterns = model.get("patterns")
    if not patterns:
        return "", model
    axes = model.get("pattern_axes") or ()
    key = pattern_key([axis for axis in axes if values[MISS_OF[axis]] == 0.0], axes)
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


def coupling_violations(model: dict, tolerance: float = 1e-9) -> list[str]:
    """결합 제약을 어기는 (하위 패턴 → 상위 패턴, 축, 꼭짓점) 설명 목록. 상위 패턴은 하위 패턴에
    축 하나를 더 관측한 것, 그 축 값은 `coupling.floors[축]`(현실 분포 비유사 쌍 평균). 로짓 차가
    −tolerance 보다 작으면 위반."""
    patterns = model.get("patterns") or {}
    floors = (model.get("coupling") or {}).get("floors") or {}
    axes = list(model.get("pattern_axes") or ())
    out = []
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
        for violation in coupling_violations(data):
            raise ValueError(f"risk_model: 결합 제약 위반 — {violation}")


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
    """계수 JSON 적재(경로: 인자 > MARKLENS_RISK_MODEL > shared/model/risk_model_v1.json). 프로세스
    캐시."""
    return _load_cached(str(resolve_model_path(path)))


def grade_for(prob: float, thresholds: dict) -> str:
    """p 를 4단계로: 하한 이상이면 그 등급(위험 하한 이상 → 위험)."""
    grade = GRADES[0]
    for key in GRADE_THRESHOLD_KEYS:
        if prob >= float(thresholds[key]):
            grade = key
    return grade


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
    grade = grade_for(prob, model["grade_thresholds"])
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
