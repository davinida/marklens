"""통합 모델 런타임(risk_score) 테스트 — 임시 계수 JSON 으로 결측·유형·등급 경계·기여도·검증."""

from __future__ import annotations

import json
import math

import pytest
from src.model import risk_model as rm

FEATURES = [
    "x1_d", "x2_text_d", "x2_whole", "x3_d", "x4",
    "miss_x1", "miss_x2text", "miss_x2img", "miss_x3", "miss_x4",
    "has_distinctive_part_a", "has_distinctive_part_b",
    "type_도형", "type_결합-문자요부", "type_결합-도형요부",
    "x1_d×문자계", "x2_whole×도형계",
]
COEFFICIENTS = {
    "x1_d": 1.0, "x2_text_d": 0.5, "x2_whole": 0.2, "x3_d": 0.3, "x4": 0.8,
    "miss_x1": 0.4, "miss_x2text": 0.4, "miss_x2img": 0.1, "miss_x3": 0.2, "miss_x4": 0.1,
    "has_distinctive_part_a": 0.0, "has_distinctive_part_b": -0.5,
    "type_도형": 0.3, "type_결합-문자요부": 1.0, "type_결합-도형요부": -0.1,
    "x1_d×문자계": 1.5, "x2_whole×도형계": 2.0,
}


def _model(**overrides) -> dict:
    model = {
        "version": rm.MODEL_VERSION, "trained_at": "2026-10-11", "label": "최종",
        "variant": "B", "w_easy": 0.5, "C": 0.3, "features": list(FEATURES),
        "coefficients": dict(COEFFICIENTS), "intercept": -2.0,
        "grade_thresholds": {"주의": 0.1, "검토 권장": 0.2, "위험": 0.7},
        "standalone_thresholds": {"x1_d": None, "x2_text_d": 0.95, "x2_whole": None,
                                  "x3_d": None, "x4": None},
        "meta": {"n_trial": 10},
    }
    model.update(overrides)
    return rm.validate_model(model)


@pytest.fixture
def model():
    return _model()


def test_design_values_missing_type_and_interactions():
    values = rm.design_values({
        "x1_d": 0.9, "x2_text_d": None, "x2_whole": 0.5, "x3_d": 0.3, "x4": "",
        "has_meaning_both": False, "has_distinctive_part_a": True, "has_distinctive_part_b": False,
        "mark_type": "도형",
    })
    assert values["x1_d"] == 0.9 and values["miss_x1"] == 0.0
    assert values["x2_text_d"] == 0.0 and values["miss_x2text"] == 1.0  # None → 결측
    assert values["x4"] == 0.0 and values["miss_x4"] == 1.0  # 빈 문자열 → 결측
    assert values["x3_d"] == 0.0 and values["miss_x3"] == 1.0  # 게이트 꺼짐 → 결측
    assert values["has_meaning_both"] == 0.0
    assert values["type_도형"] == 1.0 and values["type_결합-문자요부"] == 0.0
    assert values["x1_d×문자계"] == 0.0 and values["x2_whole×도형계"] == 0.5  # 도형계 교호작용
    assert values["x1_d×no_distinctive"] == 0.9  # 한쪽 요부 없음
    # 미상·결합·빈값은 문자(교호작용 x1_d×문자계 활성), 결합-문자요부도 문자계
    for level in ("미상", "결합", "", None):
        text = rm.design_values({"x1_d": 0.7, "mark_type": level})
        assert text["x1_d×문자계"] == 0.7
        assert all(text[f"type_{t}"] == 0.0 for t in rm.TYPE_LEVELS[1:])
    combo = rm.design_values({"x1_d": 0.7, "x2_whole": 0.4, "mark_type": "결합-도형요부"})
    assert combo["type_결합-도형요부"] == 1.0 and combo["x1_d×문자계"] == 0.0
    assert combo["x2_whole×도형계"] == 0.4
    # has_meaning_a/b 로도 게이트를 읽고, 게이트 정보가 없으면 x3_d 를 그대로 쓴다
    gated = rm.design_values({"x3_d": 0.4, "has_meaning_a": 1, "has_meaning_b": 0})
    assert gated["miss_x3"] == 1.0
    assert rm.design_values({"x3_d": 0.4})["x3_d"] == 0.4
    with pytest.raises(ValueError):
        rm.design_vector({}, ["x1_d", "없는항"])


def test_risk_score_contributions_sum_to_logit_and_grade(model):
    features = {"x1_d": 1.0, "x2_text_d": 0.8, "x2_whole": 0.6, "x3_d": 0.5, "x4": 1.0,
                "has_meaning_both": True, "has_distinctive_part_a": True,
                "has_distinctive_part_b": True, "mark_type": "결합-문자요부"}
    prob, grade, contributions, caveat, _pattern = rm.risk_score(features, model)
    assert caveat is False  # v1 JSON(figure_rule 없음)
    logit = sum(contributions.values())
    assert contributions["intercept"] == -2.0
    assert prob == pytest.approx(1 / (1 + math.exp(-logit)))
    expected = -2.0 + 1.0 + 0.4 + 0.12 + 0.15 + 0.8 - 0.5 + 1.0 + 1.5  # 항별 계수×값
    assert logit == pytest.approx(expected)
    assert prob > 0.7 and grade == "위험"
    axes = rm.axis_contributions(contributions)
    assert axes["X1"] == pytest.approx(1.0 + 1.5) and axes["X4"] == pytest.approx(0.8)
    assert axes["유형"] == pytest.approx(1.0) and axes["요부"] == pytest.approx(-0.5)
    assert set(axes) == {"X1", "X2", "X3", "X4", "유형", "요부"}
    # 전부 결측이면 절편 + 결측 지시변수 + 요부 기본값만 남는다
    prob0, grade0, c0, _, _ = rm.risk_score({}, model)
    logit0 = -2.0 + 0.4 + 0.4 + 0.1 + 0.2 + 0.1 - 0.5
    assert sum(c0.values()) == pytest.approx(logit0)
    assert prob0 == pytest.approx(1 / (1 + math.exp(-logit0)))
    assert grade0 == rm.grade_for(prob0, model["grade_thresholds"]) == "검토 권장"  # p 0.214


def test_grade_boundaries_and_standalone_threshold(model):
    thresholds = model["grade_thresholds"]
    assert rm.grade_for(0.0, thresholds) == "안전"
    assert rm.grade_for(0.1, thresholds) == "주의"  # 하한 이상이면 그 등급
    assert rm.grade_for(0.19999, thresholds) == "주의"
    assert rm.grade_for(0.2, thresholds) == "검토 권장"
    assert rm.grade_for(0.7, thresholds) == "위험" and rm.grade_for(1.0, thresholds) == "위험"
    # 단독 임계값: x2_text_d ≥ 0.95 면 낮은 p 라도 최소 검토 권장(위험으로는 올리지 않는다)
    low = {"x1_d": 0.0, "x2_text_d": 0.96, "x2_whole": 0.0, "x3_d": 0.0, "x4": 0.0,
           "has_distinctive_part_b": True, "mark_type": "문자"}
    prob, grade, _, _, _ = rm.risk_score(low, model)
    assert prob < 0.2 and grade == "검토 권장"
    low["x2_text_d"] = 0.9
    assert rm.risk_score(low, model)[1] in ("안전", "주의")
    low["x2_text_d"] = None  # 결측이면 단독 규칙도 적용하지 않는다
    assert rm.risk_score(low, model)[1] in ("안전", "주의")
    inactive = _model(standalone_thresholds={"x2_text_d": None})
    low["x2_text_d"] = 0.99
    assert rm.risk_score(low, inactive)[1] in ("안전", "주의")


def test_validate_model_rejects_broken_json(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        _model(version="other")
    with pytest.raises(ValueError):
        _model(features=FEATURES + ["없는항"], coefficients={**COEFFICIENTS, "없는항": 1.0})
    with pytest.raises(ValueError):
        _model(coefficients={k: v for k, v in COEFFICIENTS.items() if k != "x4"})
    with pytest.raises(ValueError):
        _model(grade_thresholds={"주의": 0.5, "검토 권장": 0.4, "위험": 0.7})
    with pytest.raises(ValueError):
        _model(grade_thresholds={"주의": 0.1, "위험": 0.7})
    with pytest.raises(ValueError):
        _model(standalone_thresholds={"x9": 0.5})
    with pytest.raises(ValueError):
        _model(standalone_thresholds={"x1_d": 1.5})
    with pytest.raises(ValueError):
        _model(intercept="a")
    # 파일 적재: 경로 인자 > 환경변수 > 기본 경로, 프로세스 캐시
    path = tmp_path / "risk.json"
    path.write_text(json.dumps(_model(intercept=-1.0), ensure_ascii=False), encoding="utf-8")
    assert rm.load_model(path)["intercept"] == -1.0
    monkeypatch.setenv(rm.ENV_MODEL_PATH, str(path))
    assert rm.resolve_model_path() == path and rm.load_model()["intercept"] == -1.0
    monkeypatch.delenv(rm.ENV_MODEL_PATH)
    assert rm.resolve_model_path() == rm.DEFAULT_MODEL_PATH


V12_FEATURES = [
    "x1_d", "x2_text_d", "x2_whole", "x3_d", "x4", "miss_x2img", "miss_x3", "miss_x4",
    "any_no_distinctive", "x1_d×문자계", "x2_whole×도형계", "x1_d×any_no_distinctive",
]
V12_COEFFICIENTS = {
    "x1_d": 1.4, "x2_text_d": 1.1, "x2_whole": 0.1, "x3_d": 0.3, "x4": 1.2,
    "miss_x2img": 0.2, "miss_x3": 0.3, "miss_x4": 0.2, "any_no_distinctive": 0.6,
    "x1_d×문자계": 2.2, "x2_whole×도형계": -0.1, "x1_d×any_no_distinctive": -0.9,
}
FIGURE_RULE = {"threshold": 0.9, "caveat": "도형 유사는 검증 데이터가 적어 참고용",
               "validated": False, "basis": "97후3050 후단 — 미검증 제품 규칙"}


def _model_v12(**overrides) -> dict:
    model = _model(features=list(V12_FEATURES), coefficients=dict(V12_COEFFICIENTS),
                   intercept=-3.2, method="prior_monotone_logistic",
                   removed_terms=["type_도형", "type_결합-문자요부", "type_결합-도형요부",
                                  "miss_x1", "miss_x2text", "has_distinctive_part_a",
                                  "has_distinctive_part_b"],
                   prior={"mu": {"x1_d": 1.0, "x1_d×any_no_distinctive": -0.5}, "sigma": 1.0,
                          "intercept_prior": False},
                   monotone={"features": ["x1_d", "x2_whole"],
                             "constraint": "본체 ≥ 0, 본체 + 교호작용 조합 ≥ 0"},
                   figure_rule=dict(FIGURE_RULE))
    model.update(overrides)
    return rm.validate_model(model)


def test_v12_type_only_difference_changes_only_interactions():
    """유형 주효과가 없으므로 유형만 다른 두 입력의 로짓 차는 교호작용 항에서만 난다."""
    model = _model_v12()
    base = {"x1_d": 0.8, "x2_text_d": 0.6, "x2_whole": 0.5, "x3_d": 0.4, "x4": 0.7,
            "has_meaning_both": True, "mark_type": "문자"}
    text = rm.risk_score(base, model)
    combo = rm.risk_score({**base, "mark_type": "결합-문자요부"}, model)
    assert text.prob == pytest.approx(combo.prob)  # 둘 다 문자계
    figure = rm.risk_score({**base, "mark_type": "도형"}, model)
    diff = sum(text.contributions.values()) - sum(figure.contributions.values())
    expected = V12_COEFFICIENTS["x1_d×문자계"] * 0.8 - V12_COEFFICIENTS["x2_whole×도형계"] * 0.5
    assert diff == pytest.approx(expected)
    changed = {k for k in text.contributions if text.contributions[k] != figure.contributions[k]}
    assert changed == {"x1_d×문자계", "x2_whole×도형계"}
    assert rm.risk_score({**base, "mark_type": "미상"}, model).prob == pytest.approx(text.prob)
    assert not text.figure_caveat and not combo.figure_caveat and figure.figure_caveat


def test_v12_distinctive_flag_interaction():
    """요부 플래그: any_no_distinctive(한쪽이라도 없음) 와 x1_d×any_no_distinctive 교호작용."""
    model = _model_v12()
    base = {"x1_d": 1.0, "x2_text_d": 0.0, "x2_whole": 0.0, "x3_d": 0.0, "x4": 0.0,
            "has_meaning_both": True, "mark_type": "문자"}
    both = rm.risk_score({**base, "has_distinctive_part_a": True,
                          "has_distinctive_part_b": True}, model)
    one_missing = rm.risk_score({**base, "has_distinctive_part_a": True,
                                 "has_distinctive_part_b": False}, model)
    assert both.contributions["any_no_distinctive"] == 0.0
    assert both.contributions["x1_d×any_no_distinctive"] == 0.0
    assert one_missing.contributions["any_no_distinctive"] == pytest.approx(0.6)
    assert one_missing.contributions["x1_d×any_no_distinctive"] == pytest.approx(-0.9)
    # 요부 없는 쌍은 호칭 1.0 의 효과가 0.9 만큼 작다(2000후2453 전체 대비)
    logit_both = sum(both.contributions.values())
    logit_missing = sum(one_missing.contributions.values())
    assert logit_missing - logit_both == pytest.approx(0.6 - 0.9)
    assert rm.axis_contributions(one_missing.contributions)["요부"] == pytest.approx(0.6)
    assert rm.axis_contributions(one_missing.contributions)["X1"] == pytest.approx(1.4 + 2.2 - 0.9)
    # 플래그를 안 주면 요부 있음(기본값)으로 본다
    assert rm.risk_score(base, model).contributions["any_no_distinctive"] == 0.0


def test_v12_figure_rule_caveat_and_floor():
    model = _model_v12()
    low = {"x1_d": 0.0, "x2_text_d": 0.0, "x2_whole": 0.95, "x3_d": 0.0, "x4": 0.0,
           "has_meaning_both": True, "mark_type": "도형"}
    result = rm.risk_score(low, model)
    assert result.prob < 0.2 and result.grade == "검토 권장" and result.figure_caveat
    assert rm.risk_score({**low, "mark_type": "결합-도형요부"}, model).grade == "검토 권장"
    assert rm.risk_score({**low, "x2_whole": 0.85}, model).grade in ("안전", "주의")  # τ 미만
    assert rm.risk_score({**low, "x2_whole": None}, model).grade in ("안전", "주의")  # 결측
    text = rm.risk_score({**low, "mark_type": "문자"}, model)
    assert text.grade in ("안전", "주의") and not text.figure_caveat  # 문자계에는 적용 안 함
    # threshold 가 null 이면 caveat 만, v1.1 JSON(figure_rule 없음)은 둘 다 없음
    only_caveat = _model_v12(figure_rule={**FIGURE_RULE, "threshold": None})
    result = rm.risk_score(low, only_caveat)
    assert result.figure_caveat and result.grade in ("안전", "주의")
    legacy = _model_v12(figure_rule=None)
    assert rm.risk_score(low, legacy) == (*rm.risk_score(low, legacy)[:3], False, "")
    with pytest.raises(ValueError):
        _model_v12(figure_rule={"threshold": 1.5, "caveat": "x"})
    with pytest.raises(ValueError):
        _model_v12(figure_rule={"threshold": 0.9})


def test_v12_monotone_validation_and_non_decreasing_probability():
    assert rm.monotone_violations(V12_COEFFICIENTS) == []
    bad = {**V12_COEFFICIENTS, "x4": -0.3}
    assert rm.monotone_violations(bad) == ["x4 -0.3"]
    with pytest.raises(ValueError):
        _model_v12(coefficients=bad)
    worse = {**V12_COEFFICIENTS, "x2_whole×도형계": -0.5}  # 0.1 − 0.5 < 0
    assert rm.monotone_violations(worse) == ["x2_whole + x2_whole×도형계 -0.4"]
    # x1 은 문자계·요부없음 교호작용의 모든 조합에서 ≥ 0 — 요부 없음 조합이 음수면 위반
    combo = {**V12_COEFFICIENTS, "x1_d×any_no_distinctive": -1.6}  # 1.4 − 1.6 < 0
    assert rm.monotone_violations(combo) == ["x1_d + x1_d×any_no_distinctive -0.2"]
    with pytest.raises(ValueError):
        _model_v12(coefficients=combo)
    assert rm.validate_model({**_model_v12(), "monotone": None, "coefficients": worse})  # 검증 생략
    model = _model_v12()
    for mark_type in ("문자", "도형", "결합-도형요부"):
        for flag in (True, False):
            for axis in ("x1_d", "x2_text_d", "x2_whole", "x3_d", "x4"):
                previous = -1.0
                for value in (0.0, 0.25, 0.5, 0.75, 1.0):
                    prob = rm.risk_score({"x1_d": 0.3, "x2_text_d": 0.3, "x2_whole": 0.3,
                                          "x3_d": 0.3, "x4": 0.3, "has_meaning_both": True,
                                          "has_distinctive_part_b": flag,
                                          "mark_type": mark_type, axis: value}, model).prob
                    assert prob >= previous - 1e-12  # 축 점수를 올리면 확률 비감소
                    previous = prob


def test_versions_accepted():
    assert _model(version="risk_model_v1")["version"] == "risk_model_v1"
    assert _model(version="risk_model_v1.1")["version"] == "risk_model_v1.1"
    assert _model(version="risk_model_v1.2")["version"] == "risk_model_v1.2"
    assert _model(version="risk_model_v1.2.1")["version"] == "risk_model_v1.2.1"
    assert rm.MODEL_VERSION == "risk_model_v1.4.7"  # 서비스 기본 모델(2026-11-26 부터)
    assert rm.DEFAULT_MODEL_PATH == rm.V147_MODEL_PATH
    assert rm.V13_MODEL_PATH.name == "risk_model_v1.json"
    with pytest.raises(ValueError):
        _model(version="risk_model_v2")


def test_shipped_model_file_is_valid():
    """저장소의 shared/model/risk_model_v1.json 이 검증을 통과하고 점수를 낸다."""
    if not rm.DEFAULT_MODEL_PATH.exists():
        pytest.skip("계수 파일 없음(학습 전)")
    model = rm.load_model()
    prob, grade, contributions, caveat, pattern = rm.risk_score(
        {"x1_d": 1.0, "x2_text_d": 1.0, "x2_whole": 0.8, "x3_d": 0.9, "x4": 1.0,
         "has_meaning_both": True, "mark_type": "문자"}, model)
    assert 0.0 <= prob <= 1.0 and grade in rm.GRADES and caveat is False
    assert sum(contributions.values()) == pytest.approx(math.log(prob / (1 - prob)))
    assert model["meta"]["n_trial"] > 0
    assert 0.0 < model["meta"]["grade_precision"] <= 1.0  # 계약 v2 meta.grade_precision(E-6)
    if model.get("monotone"):
        assert rm.monotone_violations(model["coefficients"]) == []
    if model["version"] in ("risk_model_v1.1", "risk_model_v1.2"):
        assert not any(name.startswith("type_") for name in model["features"])
        assert model["standalone_precision"] == 0.7
    if model["version"] >= "risk_model_v1.2":
        assert "any_no_distinctive" in model["features"]
        assert model["figure_rule"]["validated"] is False
        figure = rm.risk_score({"x1_d": 0.0, "x2_whole": 0.95, "mark_type": "도형"}, model)
        assert figure.figure_caveat and figure.grade in ("검토 권장", "위험")
    if model["version"] == "risk_model_v1.3":
        assert pattern == "x2_whole+x4" == model["reference_pattern"]
        assert contributions["miss_pattern"] == 0.0
        assert sorted(model["patterns"]) == sorted(rm.pattern_keys(model["pattern_axes"]))
        assert {"miss_x2img", "miss_x3", "miss_x4"} <= set(model["removed_terms"])
        assert rm.coupling_violations(model) == []
        for block in model["patterns"].values():
            assert rm.monotone_violations(block["coefficients"]) == []
            assert not any(name.startswith("miss_") for name in block["features"])
        without_image = rm.risk_score({"x1_d": 1.0, "x2_text_d": 1.0, "x3_d": 0.9, "x4": 1.0,
                                       "has_meaning_both": True, "mark_type": "문자"}, model)
        assert without_image.pattern == "x4"
        assert without_image.contributions["miss_pattern"] == pytest.approx(
            model["patterns"]["x4"]["intercept"] - model["intercept"])


# ---- v1.3 결측 패턴별 계수 집합 ------------------------------------------------------------

V13_BASE = ["x1_d", "x2_text_d", "x3_d", "any_no_distinctive", "x1_d×문자계",
            "x1_d×any_no_distinctive"]
V13_SHARED = {"x1_d": 1.6, "x2_text_d": 1.0, "x3_d": 0.2, "any_no_distinctive": 0.7,
              "x1_d×문자계": 2.0, "x1_d×any_no_distinctive": -0.8}
V13_FLOORS = {"x2_whole": 0.35, "x4": 0.03}


def _block(extra: dict, intercept: float) -> dict:
    coefficients = {**V13_SHARED, **extra}
    return {"features": list(coefficients), "coefficients": coefficients, "intercept": intercept}


def _model_v13(**overrides) -> dict:
    """합성 v1.3: 패턴 4개. 결합 제약은 하한(이미지 0.35·상품 0.03)에서 꼭짓점마다 성립하도록 절편을
    두었다(base −3.9 → x2_whole −3.95(문자계 −0.05 + 0.105, 도형계 −0.05 + 0.07) · x4 −3.93(+0.012)
    → 둘 다 −3.94(x2_whole 에서 +0.01 + 0.042, x4 에서 문자계 −0.01 + 0.105·도형계 −0.01 + 0.07)).
    공통 항 계수는 네 패턴이 같다(결합 제약은 꼭짓점 전부에서 성립해야 하므로 기울기 차가 있으면
    절편 여유가 더 필요하다)."""
    patterns = {
        "base": _block({}, -3.9),
        "x2_whole": _block({"x2_whole": 0.3, "x2_whole×도형계": -0.1}, -3.95),
        "x4": _block({"x4": 1.4}, -3.93),
        "x2_whole+x4": _block({"x2_whole": 0.3, "x2_whole×도형계": -0.1, "x4": 1.4}, -3.94),
    }
    reference = patterns["x2_whole+x4"]
    model = {
        "version": "risk_model_v1.3", "trained_at": "2026-10-25", "label": "최종",
        "method": "prior_monotone_logistic", "w_easy": 0.5, "hyper": 1.0,
        "removed_terms": ["miss_x2img", "miss_x3", "miss_x4"],
        "monotone": {"features": ["x1_d", "x2_whole"], "constraint": "테스트"},
        "figure_rule": FIGURE_RULE,
        "pattern_axes": ["x2_whole", "x4"], "reference_pattern": "x2_whole+x4",
        "patterns": patterns,
        "features": list(reference["features"]), "coefficients": dict(reference["coefficients"]),
        "intercept": reference["intercept"],
        "coupling": {"floors": dict(V13_FLOORS), "basis": "테스트"},
        "grade_thresholds": {"주의": 0.06, "검토 권장": 0.12, "위험": 0.56},
        "standalone_thresholds": {"x1_d": 0.98, "x2_text_d": None, "x2_whole": None,
                                  "x3_d": None, "x4": None},
        "meta": {"n_trial": 10, "grade_precision": 0.7},
    }
    model.update(overrides)
    return rm.validate_model(model)


def test_v13_pattern_selection_and_miss_pattern_contribution():
    model = _model_v13()
    full = {"x1_d": 0.8, "x2_text_d": 0.5, "x2_whole": 0.6, "x3_d": 0.4, "x4": 0.5,
            "has_meaning_both": True, "mark_type": "문자"}
    result = rm.risk_score(full, model)
    assert result.pattern == "x2_whole+x4" and result.contributions["miss_pattern"] == 0.0
    assert result.contributions["intercept"] == -3.94
    assert sum(result.contributions.values()) == pytest.approx(
        math.log(result.prob / (1 - result.prob)))
    assert set(result.contributions) == {"intercept", "miss_pattern", *model["features"]}
    no_image = rm.risk_score({**full, "x2_whole": None}, model)
    assert no_image.pattern == "x4" and "x2_whole" not in no_image.contributions
    assert no_image.contributions["miss_pattern"] == pytest.approx(-3.93 + 3.94)
    no_goods = rm.risk_score({**full, "x4": None}, model)
    assert no_goods.pattern == "x2_whole" and "x4" not in no_goods.contributions
    assert no_goods.contributions["miss_pattern"] == pytest.approx(-3.95 + 3.94)  # 음수도 가능
    nothing = rm.risk_score({**full, "x2_whole": None, "x4": None}, model)
    assert nothing.pattern == "base"
    assert nothing.contributions["miss_pattern"] == pytest.approx(0.04)
    assert rm.axis_contributions(nothing.contributions)["결측"] == pytest.approx(0.04)
    # 기준 절편 + 결측 보정 + 점수 항 = 로짓(엔진의 missing_adjustment 검산식)
    logit = -3.94 + nothing.contributions["miss_pattern"] + sum(
        v for k, v in nothing.contributions.items() if k not in ("intercept", "miss_pattern"))
    assert 1 / (1 + math.exp(-logit)) == pytest.approx(nothing.prob)
    # 게이트 꺼진 X3 는 값 0 — 패턴을 바꾸지 않는다
    gated = rm.risk_score({**full, "has_meaning_both": False}, model)
    assert gated.pattern == "x2_whole+x4" and gated.contributions["x3_d"] == 0.0
    # 패턴 없는 JSON(≤ v1.2.1)은 그대로
    legacy = rm.risk_score(full, _model_v12())
    assert legacy.pattern == "" and "miss_pattern" not in legacy.contributions
    assert rm.select_pattern(_model_v12(), rm.design_values(full)) == ("", _model_v12())


def test_v13_more_input_never_lowers_probability():
    """결합 제약: 하한 이상의 이미지·상품을 더 관측하면 어떤 입력에서도 p 가 내려가지 않는다."""
    model = _model_v13()
    assert rm.coupling_violations(model) == []
    assert len(rm.coupling_vertices(V13_BASE)) == 32
    assert len(rm.coupling_vertices(V13_BASE + ["x2_whole", "x2_whole×도형계"])) == 64
    assert len(rm.coupling_vertices(V13_BASE + ["x4", "miss_x4"])) == 96
    grid = (0.0, 0.3, 0.7, 1.0)
    for x1 in grid:
        for x2_text in grid:
            for level in ("문자", "도형", "결합-문자요부"):
                for flag in (True, False):
                    base = {"x1_d": x1, "x2_text_d": x2_text, "x3_d": 0.5, "x2_whole": None,
                            "x4": None, "has_meaning_both": True,
                            "has_distinctive_part_b": flag, "mark_type": level}
                    p0 = rm.risk_score(base, model).prob
                    for value in (V13_FLOORS["x2_whole"], 0.5, 1.0):
                        assert rm.risk_score({**base, "x2_whole": value}, model).prob >= p0 - 1e-12
                    for value in (V13_FLOORS["x4"], 0.5, 1.0):
                        with_goods = rm.risk_score({**base, "x4": value}, model)
                        assert with_goods.prob >= p0 - 1e-12
                        both = rm.risk_score({**base, "x4": value, "x2_whole": 0.35}, model)
                        assert both.prob >= with_goods.prob - 1e-12
    # 하한 아래의 이미지는 내려갈 수 있다(비유사 평균보다 덜 비슷한 이미지는 음의 증거)
    low = {"x1_d": 0.9, "x2_text_d": 0.5, "x3_d": 0.5, "x4": None, "has_meaning_both": True,
           "mark_type": "문자"}
    assert rm.risk_score({**low, "x2_whole": 0.0}, model).prob < rm.risk_score(low, model).prob


def test_v13_validate_patterns():
    with pytest.raises(ValueError, match="patterns 키"):
        _model_v13(patterns={k: v for k, v in _model_v13()["patterns"].items() if k != "x4"})
    with pytest.raises(ValueError, match="reference_pattern"):
        _model_v13(intercept=-3.0)
    with pytest.raises(ValueError, match="reference_pattern"):
        _model_v13(reference_pattern="base")
    with pytest.raises(ValueError, match="pattern_axes"):
        _model_v13(pattern_axes=["x2_whole", "x3_d"])
    bad = _model_v13()["patterns"]
    with pytest.raises(ValueError, match="관측되지 않은 축"):
        _model_v13(patterns={**bad, "base": {**bad["x4"], "intercept": -3.9}})
    with pytest.raises(ValueError, match="결측 지시변수"):
        block = bad["x4"]
        _model_v13(patterns={**bad, "x4": {
            "features": block["features"] + ["miss_x4"],
            "coefficients": {**block["coefficients"], "miss_x4": 0.1}, "intercept": -3.93}})
    with pytest.raises(ValueError, match="결합 제약 위반"):
        _model_v13(patterns={**bad, "x2_whole": {**bad["x2_whole"], "intercept": -4.2}})
    with pytest.raises(ValueError, match="단조 제약 위반"):
        _model_v13(patterns={**bad, "x2_whole": {
            **bad["x2_whole"], "coefficients": {**bad["x2_whole"]["coefficients"],
                                                 "x2_whole×도형계": -0.5}}})
    with pytest.raises(ValueError, match="coupling.floors"):
        _model_v13(coupling={"floors": {"x2_whole": 1.5}})
    # 결합 제약 없는(coupling null) 패턴 JSON 은 검증을 건너뛴다
    loose = _model_v13(coupling=None, patterns={**bad, "x2_whole": {**bad["x2_whole"],
                                                                     "intercept": -4.2}})
    assert rm.coupling_violations(loose) == []  # floors 없음 → 검사 대상 없음
    violations = rm.coupling_violations({**loose, "coupling": {"floors": V13_FLOORS}})
    assert violations and all(v.startswith("base → x2_whole") for v in violations)


# ---- v1.4 이름 없는 입력의 계수 집합 --------------------------------------------------------

V14_NAME_FLOORS = {"x1_d": 0.25, "x2_text_d": 0.1, "x3_d": 0.0}


def _nameless_block(coefficients: dict, intercept: float) -> dict:
    return {"features": list(coefficients), "coefficients": dict(coefficients),
            "intercept": intercept}


def _model_v14(**overrides) -> dict:
    """합성 v1.4 = 합성 v1.3 + 이름 없는 패턴 2벌. 이름 하한(호칭 0.25·철자 0.1·관념 0)에서 이름
    있는 패턴의 로짓은 문자계 −2.95 + 0.3·이미지(요부 없음이면 +0.5), 도형계 −3.45 + 0.2·이미지 —
    이름 없는 패턴(−3.5 + 0.2·이미지)이 모든 꼭짓점에서 그 이하다. 상품을 하한 0.03 으로 더 관측하면
    +0.042."""
    nameless = {
        "x2_whole": _nameless_block({"x2_whole": 0.2, "x2_whole×도형계": 0.0}, -3.5),
        "x2_whole+x4": _nameless_block({"x2_whole": 0.2, "x2_whole×도형계": 0.0, "x4": 1.4}, -3.5),
    }
    values = {"version": "risk_model_v1.4", "nameless_patterns": nameless,
              "coupling": {"floors": dict(V13_FLOORS), "name_floors": dict(V14_NAME_FLOORS),
                           "basis": "테스트"}}
    values.update(overrides)
    return _model_v13(**values)


def test_v14_nameless_pattern_selection_and_score():
    model = _model_v14()
    image_only = {"x1_d": None, "x2_text_d": None, "x3_d": None, "x4": None, "x2_whole": 0.8,
                  "has_meaning_both": False, "has_distinctive_part_a": True,
                  "has_distinctive_part_b": True, "mark_type": "도형"}
    result = rm.risk_score(image_only, model)
    assert result.pattern == "noname:x2_whole" and result.figure_caveat
    assert set(result.contributions) == {"intercept", "miss_pattern", "x2_whole",
                                         "x2_whole×도형계"}  # 이름 항이 없다
    assert result.contributions["intercept"] == -3.94  # 기준 절편(이름·이미지·상품 모두 관측)
    assert result.contributions["miss_pattern"] == pytest.approx(-3.5 + 3.94)
    assert math.log(result.prob / (1 - result.prob)) == pytest.approx(-3.5 + 0.2 * 0.8)
    with_goods = rm.risk_score({**image_only, "x4": 0.5}, model)
    assert with_goods.pattern == "noname:x2_whole+x4"
    assert math.log(with_goods.prob / (1 - with_goods.prob)) == pytest.approx(
        -3.5 + 0.2 * 0.8 + 1.4 * 0.5)
    # 이름도 이미지도 없는 입력(상품만·아무것도 없음)은 종전대로 이름 있는 패턴에 이름 항 0
    goods_only = rm.risk_score({**image_only, "x2_whole": None, "x4": 0.5}, model)
    assert goods_only.pattern == "x4" and goods_only.contributions["x1_d"] == 0.0
    assert rm.risk_score({**image_only, "x2_whole": None}, model).pattern == "base"
    # 이름 축이 하나라도 있으면 이름 있는 패턴(호칭만 결측인 입력 포함)
    named = rm.risk_score({**image_only, "x1_d": 0.4, "x2_text_d": 0.3}, model)
    assert named.pattern == "x2_whole" and "x1_d" in named.contributions
    assert rm.risk_score({**image_only, "x2_text_d": 0.3}, model).pattern == "x2_whole"
    assert rm.name_missing(rm.design_values(image_only))
    assert not rm.name_missing(rm.design_values({**image_only, "x2_text_d": 0.3}))
    # v1.3 JSON(nameless_patterns 없음)은 같은 입력을 종전대로 계산한다
    old = rm.risk_score(image_only, _model_v13())
    assert old.pattern == "x2_whole" and old.contributions["x1_d"] == 0.0
    assert math.log(old.prob / (1 - old.prob)) == pytest.approx(-3.95 + (0.3 - 0.1) * 0.8)
    # 한 벌만 있는 JSON: 없는 키의 입력은 이름 있는 패턴으로 내려간다
    partial = _model_v14(nameless_patterns={
        "x2_whole": _model_v14()["nameless_patterns"]["x2_whole"]})
    assert rm.risk_score({**image_only, "x4": 0.5}, partial).pattern == "x2_whole+x4"
    assert rm.risk_score(image_only, partial).pattern == "noname:x2_whole"


def test_v14_observing_name_or_goods_never_lowers_probability():
    """결합 제약(이름 쪽): 이름 없는 입력에 이름을 하한 이상으로 더 주거나 상품을 하한 이상으로 더
    주면 어떤 유형·이미지 값에서도 p 가 내려가지 않는다."""
    model = _model_v14()
    assert rm.coupling_violations(model) == []
    assert len(rm.nameless_vertices(["x2_whole", "x2_whole×도형계"])) == 4
    assert len(rm.nameless_vertices(["x2_whole", "x2_whole×도형계", "x4"])) == 8
    assert len(rm.name_coupling_vertices(["x2_whole", "x2_whole×도형계", "x4"])) == 16
    for level in ("문자", "도형", "결합-문자요부", "결합-도형요부"):
        for image in (0.0, 0.35, 0.7, 1.0):
            for goods in (None, 0.03, 0.6, 1.0):
                base = {"x1_d": None, "x2_text_d": None, "x3_d": None, "x2_whole": image,
                        "x4": goods, "has_meaning_both": False, "mark_type": level}
                p0 = rm.risk_score(base, model).prob
                assert rm.risk_score(base, model).pattern.startswith(rm.NAMELESS_PREFIX)
                for x1 in (0.25, 0.6, 1.0):
                    for x2_text in (0.1, 0.5, 1.0):
                        for flag in (True, False):
                            more = rm.risk_score(
                                {**base, "x1_d": x1, "x2_text_d": x2_text, "x3_d": 0.0,
                                 "has_meaning_both": True, "has_distinctive_part_b": flag},
                                model)
                            assert not more.pattern.startswith(rm.NAMELESS_PREFIX)
                            assert more.prob >= p0 - 1e-12
                if goods is None:
                    for value in (0.03, 0.5, 1.0):
                        assert rm.risk_score({**base, "x4": value}, model).prob >= p0 - 1e-12
    # 하한 아래의 이름(쉬운 음성 평균보다 덜 비슷한 이름)은 내려갈 수 있다 — 음의 증거
    image_only = {"x1_d": None, "x2_text_d": None, "x3_d": None, "x4": None, "x2_whole": 1.0,
                  "mark_type": "도형"}
    low_name = {**image_only, "x1_d": 0.0, "x2_text_d": 0.0}
    assert rm.risk_score(low_name, model).prob < rm.risk_score(image_only, model).prob


def test_v14_validate_nameless_patterns():
    good = _model_v14()["nameless_patterns"]
    with pytest.raises(ValueError, match="nameless_patterns 의 키"):
        _model_v14(nameless_patterns={"x9": good["x2_whole"]})
    with pytest.raises(ValueError, match="nameless_patterns 의 키"):
        _model_v14(nameless_patterns={})
    with pytest.raises(ValueError, match="이름에서 나오는 항"):
        _model_v14(nameless_patterns={**good, "x2_whole": _nameless_block(
            {"x2_whole": 0.2, "x2_whole×도형계": 0.0, "x1_d": 0.1}, -3.5)})
    with pytest.raises(ValueError, match="패턴 축이 키와 다릅니다"):
        _model_v14(nameless_patterns={**good, "x2_whole": good["x2_whole+x4"]})
    with pytest.raises(ValueError, match="단조 제약 위반"):
        _model_v14(nameless_patterns={**good, "x2_whole": _nameless_block(
            {"x2_whole": 0.2, "x2_whole×도형계": -0.5}, -3.5)})
    with pytest.raises(ValueError, match="name_floors"):
        _model_v14(coupling={"floors": dict(V13_FLOORS), "name_floors": {"x1_d": 1.5}})
    with pytest.raises(ValueError, match="name_floors"):
        _model_v14(coupling={"floors": dict(V13_FLOORS), "name_floors": {"x4": 0.1}})
    # 이름 결합 위반: 이름 없는 패턴의 절편이 이름 하한에서의 이름 있는 패턴보다 높다
    with pytest.raises(ValueError, match="결합 제약 위반"):
        _model_v14(nameless_patterns={**good, "x2_whole": _nameless_block(
            {"x2_whole": 0.2, "x2_whole×도형계": 0.0}, -3.0)})
    # 이름 없는 패턴 사이: 상품을 하한으로 더 관측했는데 내려간다
    with pytest.raises(ValueError, match="결합 제약 위반"):
        _model_v14(nameless_patterns={**good, "x2_whole+x4": _nameless_block(
            {"x2_whole": 0.2, "x2_whole×도형계": 0.0, "x4": 1.4}, -3.6)})
    high = {**good, "x2_whole": _nameless_block({"x2_whole": 0.2, "x2_whole×도형계": 0.0}, -3.0)}
    loose = _model_v14(coupling=None, nameless_patterns=high)  # coupling null → 검증 건너뜀
    violations = rm.coupling_violations(
        {**loose, "coupling": {"floors": V13_FLOORS, "name_floors": V14_NAME_FLOORS}})
    assert any(v.startswith("noname:x2_whole → x2_whole (이름") for v in violations)
    assert any(v.startswith("noname:x2_whole → noname:x2_whole+x4") for v in violations)
    # name_floors 가 없는 v1.4 JSON 은 이름 결합을 검사하지 않는다(이름 없는 패턴 사이만)
    without_floors = rm.coupling_violations({**loose, "coupling": {"floors": V13_FLOORS}})
    assert without_floors and all("(이름" not in v for v in without_floors)
    assert rm.MODEL_VERSION == "risk_model_v1.4.7"  # 서비스 기본 모델(2026-11-26 부터 v1.4.7)
    assert "risk_model_v1.4" in rm.SUPPORTED_VERSIONS
    assert "risk_model_v1.4.1" in rm.SUPPORTED_VERSIONS
    assert "risk_model_v1.4.2" in rm.SUPPORTED_VERSIONS
    assert "risk_model_v1.4.3" in rm.SUPPORTED_VERSIONS
    assert "risk_model_v1.4.5" in rm.SUPPORTED_VERSIONS
    assert "risk_model_v1.4.6" in rm.SUPPORTED_VERSIONS
    assert "risk_model_v1.4.7" in rm.SUPPORTED_VERSIONS


def test_shipped_v13_scores_nameless_input_with_named_pattern():
    """v1.3 JSON 의 계산은 v1.4 런타임에서도 달라지지 않는다 — 이름 없는 이미지 질의는 이름 있는
    패턴에 이름 항 0(v1.3 때의 계약 v2 §3-2)."""
    if not rm.V13_MODEL_PATH.exists():
        pytest.skip("계수 파일 없음(학습 전)")
    model = rm.load_model(rm.V13_MODEL_PATH)
    assert model["version"] == "risk_model_v1.3" and rm.NAMELESS_KEY not in model
    features = {"x1_d": None, "x2_text_d": None, "x3_d": None, "x4": None, "x2_whole": 0.9,
                "has_meaning_both": False, "has_distinctive_part_a": True,
                "has_distinctive_part_b": True, "mark_type": "도형"}
    result = rm.risk_score(features, model)
    block = model["patterns"]["x2_whole"]
    expected = block["intercept"] + 0.9 * (block["coefficients"]["x2_whole"]
                                          + block["coefficients"]["x2_whole×도형계"])
    assert result.pattern == "x2_whole"
    assert math.log(result.prob / (1 - result.prob)) == pytest.approx(expected)
    assert result.prob == pytest.approx(0.0581, abs=5e-5)  # 설계 §7-4 "이미지만" 표의 v1.3 값


# ---- v1.4 2차 시도: 이름 없는 집합 + "같은 이름" 결합 ------------------------------------------

def _model_v14_same_name(**overrides) -> dict:
    """합성 v1.4(2차 시도 형식) = 합성 v1.3 그대로 + 이름 없는 2벌 + coupling.same_name. 같은 이름을
    더한 입력(문자계, 호칭·철자 1.0)의 이름 있는 패턴 로짓은 이미지 패턴 0.65 + 0.3·이미지(요부
    없음이면 −0.1), 이미지+상품 패턴 0.66 + 0.3·이미지 + 1.4·상품(요부 없음 −0.1) — 이름 없는
    집합(−1.0 + 1.2·이미지 + 0.6·이미지·도형계 [+ 1.4·상품])이 모든 꼭짓점에서 그 이하다."""
    nameless = {
        "x2_whole": _nameless_block({"x2_whole": 1.2, "x2_whole×도형계": 0.6}, -1.0),
        "x2_whole+x4": _nameless_block({"x2_whole": 1.2, "x2_whole×도형계": 0.6, "x4": 1.4}, -1.0),
    }
    values = {"version": "risk_model_v1.4", "nameless_patterns": nameless,
              "coupling": {"floors": dict(V13_FLOORS), "basis": "테스트",
                           "same_name": {"x1_d": 1.0, "x2_text_d": 1.0}}}
    values.update(overrides)
    return _model_v13(**values)


def test_type_with_name_follows_service_rule():
    """이름이 생기면 항상 문자계(계약 v2 §2-4 5항) — 도형계였던 입력은 결합-문자요부."""
    assert rm.type_with_name("도형") == "결합-문자요부"
    assert rm.type_with_name("결합-도형요부") == "결합-문자요부"
    assert rm.type_with_name("문자") == "문자"
    assert rm.type_with_name("결합-문자요부") == "결합-문자요부"
    assert rm.type_with_name("") == "문자" and rm.type_with_name(None) == "문자"
    base = {"x1_d": None, "x2_text_d": None, "x3_d": None, "x2_whole": 0.7, "x4": 0.2,
            "has_meaning_both": False, "mark_type": "도형"}
    added = rm.same_name_input(base, distinctive=False)
    assert added["x1_d"] == added["x2_text_d"] == 1.0 and added["mark_type"] == "결합-문자요부"
    assert added["x3_d"] is None and added["has_meaning_both"] is False  # 관념은 가장 낮은 경우로
    assert added["has_distinctive_part_a"] is True and added["has_distinctive_part_b"] is False
    assert added["x2_whole"] == 0.7 and added["x4"] == 0.2 and base["x1_d"] is None  # 원본 불변
    assert rm.same_name_input(base, {"x1_d": 0.9})["x1_d"] == 0.9
    # 문자·결합-문자요부는 모델에 같은 값이다(둘 다 문자계)
    model = _model_v13()
    for level in ("문자", "결합-문자요부"):
        assert rm.risk_score({**added, "mark_type": level}, model).prob == pytest.approx(
            rm.risk_score(added, model).prob)


def test_v14_same_name_never_lowers_probability_and_named_outputs_unchanged():
    model, old = _model_v14_same_name(), _model_v13()
    assert rm.coupling_violations(model) == []
    grid = (0.0, 0.2, 0.5, 0.9, 1.0)
    for level in ("도형", "결합-도형요부", "문자", "결합-문자요부"):
        for image in grid:
            for goods in (None, 0.0, 0.03, 0.5, 1.0):
                base = {"x1_d": None, "x2_text_d": None, "x3_d": None, "x2_whole": image,
                        "x4": goods, "has_meaning_both": False, "mark_type": level}
                nameless = rm.risk_score(base, model)
                assert nameless.pattern == "noname:" + ("x2_whole" if goods is None
                                                        else "x2_whole+x4")
                for distinctive in (True, False):
                    same = rm.risk_score(rm.same_name_input(base, distinctive=distinctive), model)
                    assert same.pattern in ("x2_whole", "x2_whole+x4")
                    assert same.prob >= nameless.prob - 1e-12  # 같은 이름을 더해도 내려가지 않는다
                    with_meaning = rm.risk_score(
                        {**rm.same_name_input(base, distinctive=distinctive), "x3_d": 1.0,
                         "has_meaning_both": True}, model)
                    assert with_meaning.prob >= same.prob - 1e-12  # 관념이 켜지면 더 높거나 같다
                if goods is None:  # 상품을 하한 이상으로 더해도 내려가지 않는다
                    assert rm.risk_score({**base, "x4": 0.03}, model).prob >= nameless.prob - 1e-12
    # 다른 이름(호칭·철자가 낮음)은 내려갈 수 있다 — 제약의 대상이 아니다(음의 증거)
    image_only = {"x1_d": None, "x2_text_d": None, "x3_d": None, "x4": None, "x2_whole": 1.0,
                  "mark_type": "도형"}
    different = {**image_only, "x1_d": 0.1, "x2_text_d": 0.1, "mark_type": "결합-문자요부"}
    assert rm.risk_score(different, model).prob < rm.risk_score(image_only, model).prob
    # 이름 있는 입력·이름도 이미지도 없는 입력의 출력은 v1.3 과 완전히 같다
    for x1 in (None, 0.0, 0.6, 1.0):
        for x2_text in (None, 0.4):
            for image in (None, 0.5):
                for goods in (None, 0.7):
                    for level in ("문자", "도형"):
                        features = {"x1_d": x1, "x2_text_d": x2_text, "x3_d": 0.3,
                                    "x2_whole": image, "x4": goods, "has_meaning_both": True,
                                    "has_distinctive_part_b": False, "mark_type": level}
                        new_result = rm.risk_score(features, model)
                        if x1 is None and x2_text is None and image is not None:
                            assert new_result.pattern.startswith("noname:")
                        else:
                            assert tuple(new_result) == tuple(rm.risk_score(features, old))


def test_v14_same_name_validation():
    good = _model_v14_same_name()["nameless_patterns"]
    floors = {"floors": dict(V13_FLOORS)}
    # 이름 없는 집합이 같은 이름을 더한 v1.3 로짓보다 높으면 적재 거부
    high = {**good, "x2_whole": _nameless_block({"x2_whole": 1.2, "x2_whole×도형계": 0.6}, -0.2)}
    with pytest.raises(ValueError, match="결합 제약 위반"):
        _model_v14_same_name(nameless_patterns=high)
    loose = _model_v14_same_name(nameless_patterns=high, coupling=None)  # coupling null → 건너뜀
    violations = rm.coupling_violations(
        {**loose, "coupling": {**floors, "same_name": {"x1_d": 1.0, "x2_text_d": 1.0}}})
    same = [v for v in violations if "(같은 이름)" in v]
    assert same and all(v.startswith("noname:x2_whole → x2_whole (같은 이름)") for v in same)
    assert any("요부없음=True" in v for v in same)  # 요부 없는 이름 쪽이 더 낮아 먼저 걸린다
    assert any("mark_type=도형, x2_whole=1.0" in v for v in same)
    assert not any("x2_whole=0.0" in v for v in same)  # 이미지 0 에서는 −0.2 ≤ 0.55
    # same_name 이 없는 JSON 은 이 검사를 하지 않는다(이름 없는 집합 사이의 축 결합만)
    assert all("(같은 이름)" not in v
               for v in rm.coupling_violations({**loose, "coupling": floors}))
    # 기준점이 낮으면(같은 이름이 아니라 0.5) 같은 집합도 걸린다 — 기준점은 JSON 의 값을 쓴다
    weaker = rm.coupling_violations(
        {**_model_v14_same_name(), "coupling": {**floors,
                                               "same_name": {"x1_d": 0.5, "x2_text_d": 0.5}}})
    assert any("(같은 이름)" in v for v in weaker)
    with pytest.raises(ValueError, match="coupling.same_name"):
        _model_v14_same_name(coupling={**floors, "same_name": {"x1_d": 1.5}})
    with pytest.raises(ValueError, match="coupling.same_name"):
        _model_v14_same_name(coupling={**floors, "same_name": [1.0, 1.0]})
    # 값을 생략하면 1.0(같은 이름)
    assert rm.coupling_violations(
        {**_model_v14_same_name(), "coupling": {**floors, "same_name": {}}}) == []


V14_MODEL_PATH = rm.REPO_ROOT / "shared" / "model" / "risk_model_v1.4.json"


def test_shipped_v14_adds_nameless_blocks_without_changing_named_outputs():
    """채택된 v1.4(2차 시도, 설계 §7-4): 이름 있는 4벌·등급 하한·단독 임계값·grade_precision 은 v1.3
    그대로, 이름 없는 2벌만 더했다. 2026-11-23 부터 서비스 기본 모델은 이 파일에서 이름 있는 검토
    권장 하한만 바꾼 v1.4.1 이다(아래 test_shipped_v141_…)."""
    if not V14_MODEL_PATH.exists() or not rm.V13_MODEL_PATH.exists():
        pytest.skip("v1.4 계수 파일 없음")
    old = rm.load_model(rm.V13_MODEL_PATH)
    new = rm.load_model(V14_MODEL_PATH)
    assert old["version"] == "risk_model_v1.3"
    assert rm.V14_MODEL_PATH == V14_MODEL_PATH  # v1.4.1 의 원본(2026-11-20–22 서비스 기본)
    assert new["version"] == "risk_model_v1.4" and rm.coupling_violations(new) == []
    for key in ("patterns", "features", "coefficients", "intercept", "grade_thresholds",
                "standalone_thresholds", "standalone_precision", "pattern_axes",
                "reference_pattern", "prior", "monotone", "removed_terms"):
        assert new[key] == old[key], key
    # 도형 규칙은 τ·검증 표시 그대로, 화면 문구만 서비스 문구로(2026-11-20, 계약 v2 §2-5)
    assert {k: v for k, v in new["figure_rule"].items() if k != "caveat"} == {
        k: v for k, v in old["figure_rule"].items() if k != "caveat"}
    assert new["figure_rule"]["caveat"] == ("로고 파일끼리 비교한 결과예요. 도형 유사는 검증 "
                                            "데이터가 적어 참고용이에요")
    assert new["meta"]["figure_caveat_history"][0]["이전"] == old["figure_rule"]["caveat"]
    assert new["meta"]["grade_precision"] == old["meta"]["grade_precision"]
    assert new["coupling"]["floors"] == old["coupling"]["floors"]
    assert new["coupling"]["same_name"]["x1_d"] == new["coupling"]["same_name"]["x2_text_d"] == 1.0
    assert "name_floors" not in new["coupling"]  # 1차 시도의 이름 하한 결합은 쓰지 않는다
    assert sorted(new[rm.NAMELESS_KEY]) == ["x2_whole", "x2_whole+x4"]
    assert new["meta"]["named_from"]["version"] == "risk_model_v1.3"
    assert new["meta"]["nameless"]["adoption"]["채택"] is True
    for block in new[rm.NAMELESS_KEY].values():
        assert set(block["features"]) <= {"x2_whole", "x2_whole×도형계", "x4"}
        assert rm.monotone_violations(block["coefficients"]) == []
    # 이름 있는 입력(호칭·철자 중 하나라도 있음)과 이름도 이미지도 없는 입력의 출력은 v1.3 과 같다
    import random

    rng = random.Random(7)
    levels = (*rm.TYPE_LEVELS, "미상", "")

    def maybe(probability: float):
        return None if rng.random() < probability else rng.random()

    for _ in range(3000):
        features = {"x1_d": maybe(0.2), "x2_text_d": maybe(0.2), "x3_d": maybe(0.4),
                    "x2_whole": maybe(0.3), "x4": maybe(0.4),
                    "has_meaning_both": rng.random() < 0.5,
                    "has_distinctive_part_a": rng.random() < 0.8,
                    "has_distinctive_part_b": rng.random() < 0.8,
                    "mark_type": rng.choice(levels)}
        nameless_image = (features["x1_d"] is None and features["x2_text_d"] is None
                          and features["x2_whole"] is not None)
        result = rm.risk_score(features, new)
        if nameless_image:
            assert result.pattern.startswith(rm.NAMELESS_PREFIX)
        else:
            assert tuple(result) == tuple(rm.risk_score(features, old))
    # 같은 이름을 더하면(문자계로, 요부 유무 양쪽) 어떤 이미지·상품 값에서도 내려가지 않는다
    for level in rm.TYPE_LEVELS:
        for image in (0.0, 0.2, 0.5, 0.8, 0.95, 1.0):
            for goods in (None, 0.0, 0.0252, 0.5, 1.0):
                base = {"x1_d": None, "x2_text_d": None, "x3_d": None, "x2_whole": image,
                        "x4": goods, "has_meaning_both": False, "mark_type": level}
                nameless = rm.risk_score(base, new)
                for distinctive in (True, False):
                    same = rm.risk_score(rm.same_name_input(
                        base, new["coupling"]["same_name"], distinctive=distinctive), new)
                    assert same.prob >= nameless.prob - 1e-9
                if goods is None:
                    assert rm.risk_score({**base, "x4": 0.0252}, new).prob >= nameless.prob - 1e-9
    # 설계 §7-4 "이미지만 입력" 표의 값(도형계)
    image_only = {"x1_d": None, "x2_text_d": None, "x3_d": None, "x4": None,
                  "has_meaning_both": False, "mark_type": "도형"}
    for image, expected_new, expected_old in ((0.5, 0.3352, 0.0376), (1.0, 0.6339, 0.0646)):
        features = {**image_only, "x2_whole": image}
        result = rm.risk_score(features, new)
        assert result.pattern == "noname:x2_whole" and result.figure_caveat  # 참고용 표시는 그대로
        assert result.prob == pytest.approx(expected_new, abs=5e-5)
        assert rm.risk_score(features, old).prob == pytest.approx(expected_old, abs=5e-5)
    # 이름 없는 입력의 등급 하한(§7-4-4, 2026-11-20) — 실제 검색(표본 A: 심사를 거치지 않은 표장)
    # 에서 이름 없는 판단이 그 등급 이상인 비율을 같은 쌍을 이름을 알고 채점했을 때와 맞춘 값
    assert new[rm.NAMELESS_KEY]["x2_whole"]["grade_thresholds"] == {
        "주의": 0.3677, "검토 권장": 0.491, "위험": 0.5724}
    assert new[rm.NAMELESS_KEY]["x2_whole+x4"]["grade_thresholds"] == {
        "주의": 0.2944, "검토 권장": 0.4441, "위험": 0.7892}
    assert new["grade_thresholds"] == old["grade_thresholds"]  # 이름 있는 입력의 하한은 그대로
    assert rm.grade_thresholds_for(new, "x2_whole+x4") == old["grade_thresholds"]
    meta = new["meta"]["nameless"]["grade_thresholds"]
    assert meta["method"].startswith("실제 검색 기준 — 표본 A")
    assert [entry["thresholds"] for entry in meta["history"]][0] == {  # 쉬운 음성 기준(§7-4-3)
        "x2_whole": {"주의": 0.279, "검토 권장": 0.4258, "위험": None},
        "x2_whole+x4": {"주의": 0.2221, "검토 권장": 0.3709, "위험": None}}
    assert meta["history"][1]["thresholds"] is None  # 1차 시도(순서 실패 — 쓰지 않음)
    assert set(meta["validation_B"]) == {"이미지만", "이미지+상품"}
    for label, key in (("이미지만", "x2_whole"), ("이미지+상품", "x2_whole+x4")):
        grades = meta["kinds"][label]["grades"]
        assert {g: grades[g]["하한"] for g in grades} == new[rm.NAMELESS_KEY][key][
            "grade_thresholds"]
        assert grades["위험"]["이름_알_때_이상"] > 0  # 이름 알 때도 위험이 있어 null 이 아니다
    grades = [rm.risk_score({**image_only, "x2_whole": image}, new).grade
              for image in (0.2, 0.36, 0.5, 0.7, 0.89, 1.0)]
    assert grades == ["안전", "안전", "안전", "주의", "검토 권장", "위험"]  # 위험 = 이미지 ≥ 0.896
    # 상품이 겹치면(1.0) 이미지가 낮아도 검토 권장, 이미지 0.8 이상이면 위험(하한 0.7892 ↔ 0.708)
    assert rm.risk_score({**image_only, "x2_whole": 0.2, "x4": 1.0}, new).grade == "검토 권장"
    assert rm.risk_score({**image_only, "x2_whole": 0.8, "x4": 1.0}, new).grade == "위험"
    assert [rm.risk_score({**image_only, "x2_whole": image, "x4": 0.0}, new).grade
            for image in (0.2, 0.36, 0.7)] == ["안전", "안전", "주의"]
    # 하한을 떼면(2차 시도 채택 때의 판정) 같은 입력이 v1.3 하한으로 매겨진다
    plain = json.loads(json.dumps(new))
    for block in plain[rm.NAMELESS_KEY].values():
        block.pop("grade_thresholds")
    assert rm.risk_score({**image_only, "x2_whole": 0.36}, plain).grade == "검토 권장"
    assert rm.risk_score({**image_only, "x2_whole": 1.0}, plain).grade == "위험"


# ---- 이름 없는 입력의 등급 하한(§7-4-3) ---------------------------------------------------------

def test_grade_for_skips_null_thresholds():
    """하한이 null 인 등급은 위험도로는 닿지 않는다(단독 규칙으로만)."""
    full = {"주의": 0.1, "검토 권장": 0.2, "위험": 0.6}
    assert [rm.grade_for(p, full) for p in (0.05, 0.1, 0.2, 0.59, 0.6, 1.0)] == [
        "안전", "주의", "검토 권장", "검토 권장", "위험", "위험"]
    no_risk = {"주의": 0.1, "검토 권장": 0.2, "위험": None}
    assert rm.grade_for(0.99, no_risk) == "검토 권장" and rm.grade_for(0.15, no_risk) == "주의"
    no_review = {"주의": 0.3, "검토 권장": None, "위험": None}
    assert rm.grade_for(0.99, no_review) == "주의" and rm.grade_for(0.29, no_review) == "안전"
    assert rm.grade_for(0.99, {"주의": None, "검토 권장": None, "위험": None}) == "안전"
    assert rm.grade_for(0.7, {"주의": None, "검토 권장": 0.5, "위험": None}) == "검토 권장"


def test_nameless_blocks_use_their_own_grade_thresholds():
    base = _model_v14_same_name()
    nameless = {key: dict(block) for key, block in base["nameless_patterns"].items()}
    nameless["x2_whole"]["grade_thresholds"] = {"주의": 0.3, "검토 권장": 0.45, "위험": None}
    nameless["x2_whole+x4"]["grade_thresholds"] = {"주의": 0.35, "검토 권장": 0.7, "위험": 0.8}
    model = _model_v14_same_name(nameless_patterns=nameless)
    assert rm.grade_thresholds_for(model, "noname:x2_whole") == nameless["x2_whole"][
        "grade_thresholds"]
    assert rm.grade_thresholds_for(model, "noname:x2_whole+x4")["위험"] == 0.8
    for pattern in ("", "base", "x2_whole", "x4", "x2_whole+x4", "noname:x4"):
        assert rm.grade_thresholds_for(model, pattern) == model["grade_thresholds"]
    # 자기 하한이 없는 집합은 최상위 하한
    assert rm.grade_thresholds_for(base, "noname:x2_whole") == base["grade_thresholds"]
    image_only = {"x1_d": None, "x2_text_d": None, "x3_d": None, "x4": None,
                  "has_meaning_both": False, "mark_type": "문자"}

    def score(image, **extra):
        return rm.risk_score({**image_only, "x2_whole": image, **extra}, model)

    # 문자계 이미지만: 로짓 −1.0 + 1.2·이미지 → p 0.269(0.0)·0.401(0.5)·0.550(1.0)
    assert [score(image).grade for image in (0.0, 0.5, 1.0)] == ["안전", "주의", "검토 권장"]
    assert score(0.5).prob == rm.risk_score({**image_only, "x2_whole": 0.5}, base).prob  # 확률 불변
    assert rm.risk_score({**image_only, "x2_whole": 0.5}, base).grade == "검토 권장"  # 종전 하한
    # 위험 하한이 null 이면 위험도가 아무리 높아도 위험이 아니다 — 도형 단독 규칙은 그대로 검토 권장
    figure = score(1.0, mark_type="도형")
    assert figure.prob > 0.6 and figure.grade == "검토 권장" and figure.figure_caveat
    low_figure = {**image_only, "x2_whole": 0.95, "mark_type": "도형"}
    strict = {key: dict(block) for key, block in nameless.items()}
    strict["x2_whole"]["grade_thresholds"] = {"주의": 0.9, "검토 권장": None, "위험": None}
    lifted = rm.risk_score(low_figure, _model_v14_same_name(nameless_patterns=strict))
    assert lifted.grade == "검토 권장"  # p 로는 안전이지만 x2_whole ≥ τ 0.9 → 도형 규칙
    assert rm.risk_score({**low_figure, "x2_whole": 0.5}, _model_v14_same_name(
        nameless_patterns=strict)).grade == "안전"
    # 이미지+상품은 자기 하한(위험 0.8)
    assert score(1.0, x4=1.0, mark_type="도형").grade == "위험"  # 로짓 2.2 → p 0.90
    assert score(0.5, x4=0.5).grade == "주의"  # 로짓 0.3 → p 0.574: 0.35 ≤ p < 0.7
    # 이름 있는 입력·이름도 이미지도 없는 입력은 최상위 하한 그대로(v1.3 과 같은 결과)
    old = _model_v13()
    for features in ({"x1_d": 0.9, "x2_text_d": 0.8, "x2_whole": 0.9, "mark_type": "문자"},
                     {"x1_d": 0.2, "x2_text_d": 0.1, "x4": 1.0, "mark_type": "도형"},
                     {**image_only, "x2_whole": None, "x4": 1.0}):
        assert tuple(rm.risk_score(features, model)) == tuple(rm.risk_score(features, old))


def test_validate_nameless_grade_thresholds():
    good = _model_v14_same_name()["nameless_patterns"]

    def with_thresholds(thresholds):
        blocks = {key: dict(block) for key, block in good.items()}
        blocks["x2_whole"]["grade_thresholds"] = thresholds
        return _model_v14_same_name(nameless_patterns=blocks)

    assert with_thresholds({"주의": 0.2, "검토 권장": None, "위험": None})
    assert with_thresholds({"주의": None, "검토 권장": None, "위험": None})
    assert with_thresholds({"주의": 0.2, "검토 권장": 0.2, "위험": 1.0})
    with pytest.raises(ValueError, match="grade_thresholds 키"):
        with_thresholds({"주의": 0.2, "검토 권장": 0.4})
    with pytest.raises(ValueError, match="grade_thresholds 키"):
        with_thresholds([0.2, 0.4, 0.6])
    with pytest.raises(ValueError, match="오름차순"):
        with_thresholds({"주의": 0.5, "검토 권장": 0.4, "위험": None})
    with pytest.raises(ValueError, match="오름차순"):
        with_thresholds({"주의": 0.5, "검토 권장": None, "위험": 0.4})
    with pytest.raises(ValueError, match="오름차순"):
        with_thresholds({"주의": 0.0, "검토 권장": 0.4, "위험": 0.6})
    with pytest.raises(ValueError, match="오름차순"):
        with_thresholds({"주의": "0.2", "검토 권장": 0.4, "위험": 0.6})
    # 최상위 하한은 여전히 null 을 허용하지 않는다(이름 있는 입력)
    with pytest.raises((ValueError, TypeError)):
        _model_v13(grade_thresholds={"주의": 0.06, "검토 권장": None, "위험": 0.56})


def test_shipped_v141_changes_only_the_named_review_cut():
    """서비스 기본 v1.4.1(설계 §7-6-2, 2026-11-23): v1.4 JSON 에서 이름 있는 판단의 검토 권장 하한만
    0.1805 → 0.5059(이름 있는 4벌 공통 — 최상위 grade_thresholds)로 바꿨다. 계수·이름 없는 집합과 그
    하한·단독 임계값·도형 규칙·결합 제약·위험 정밀도는 v1.4 그대로 — v1.4 를 다시 쓰면 이 시험이
    v1.4.1 도 다시 만들라고 알린다(named_shared_threshold.py)."""
    if not rm.V141_MODEL_PATH.exists() or not V14_MODEL_PATH.exists():
        pytest.skip("v1.4.1 계수 파일 없음")
    base = json.loads(V14_MODEL_PATH.read_text(encoding="utf-8"))
    new = json.loads(rm.V141_MODEL_PATH.read_text(encoding="utf-8"))
    assert rm.V141_MODEL_PATH.name == "risk_model_v1.4.1.json"  # v1.4.2 의 원본(2026-11-23)
    assert new["version"] == "risk_model_v1.4.1"
    assert new["grade_thresholds"] == {"주의": 0.0902, "검토 권장": 0.5059, "위험": 0.5902}
    assert {k: v for k, v in new["grade_thresholds"].items() if k != "검토 권장"} == {
        k: v for k, v in base["grade_thresholds"].items() if k != "검토 권장"}
    named = new["meta"]["named_grade_thresholds"]
    assert named["previous"] == base["grade_thresholds"]
    assert named["derived_from"] == base["version"]
    assert named["adopted"] is True and len(named["rule_sha256"]) == 64
    review = new["grade_thresholds"]["검토 권장"]
    assert named["per_set"] and max(named["per_set"].values()) == review
    same = {k: v for k, v in new.items() if k not in ("version", "grade_thresholds", "grade_basis",
                                                     "meta")}
    assert same == {k: v for k, v in base.items() if k not in (
        "version", "grade_thresholds", "grade_basis", "meta")}
    assert {k: v for k, v in new["meta"].items() if k != "named_grade_thresholds"} == base["meta"]
    model = rm.load_model(rm.V141_MODEL_PATH)
    assert rm.coupling_violations(model) == []
    for pattern in model["patterns"]:
        assert rm.grade_thresholds_for(model, pattern) == new["grade_thresholds"]
    assert rm.nameless_grade_thresholds(model) == rm.nameless_grade_thresholds(
        rm.load_model(V14_MODEL_PATH))



def test_weak_run_version_key_validation():
    """weak_run.version(식별력 결합 규칙의 약한 토큰열 — 서비스 규칙): 없으면 1, 1·2 만 받는다."""
    from src.axes import distinctiveness as dx

    base = json.loads(rm.V141_MODEL_PATH.read_text(encoding="utf-8"))
    assert rm.weak_run_version(base) == 1
    assert rm.weak_run_version({**base, rm.WEAK_RUN_KEY: {"version": 2}}) == 2
    rm.validate_model({**base, rm.WEAK_RUN_KEY: {"version": 2}})
    for bad in ({"version": 3}, {"version": True}, 2, {"enabled": True}):
        with pytest.raises(ValueError):
            rm.validate_model({**base, rm.WEAK_RUN_KEY: bad})
    assert rm.SUPPORTED_WEAK_RUN_VERSIONS == dx.WEAK_RUN_VERSIONS


def test_shipped_v142_only_adds_the_logo_floor_flag():
    """v1.4.2(설계 §7-9, 2026-11-23 — v1.4.3 의 원본): v1.4.1 JSON 에 logo_floor 표시(엔진이 이름
    있는 이미지 질의를 이미지만 판단과 견줌 — 견고성 점검 R-P0-1)와 그 출처 meta 만 더했다. 계수·
    하한·규칙은 v1.4.1 그대로 — v1.4.1 을 다시 쓰면 이 시험이 v1.4.2 도 다시 만들라고 알린다
    (logo_floor_image_only.py)."""
    if not rm.V142_MODEL_PATH.exists() or not rm.V141_MODEL_PATH.exists():
        pytest.skip("v1.4.2 계수 파일 없음")
    base = json.loads(rm.V141_MODEL_PATH.read_text(encoding="utf-8"))
    new = json.loads(rm.V142_MODEL_PATH.read_text(encoding="utf-8"))
    assert rm.V142_MODEL_PATH.name == "risk_model_v1.4.2.json"
    assert new["version"] == "risk_model_v1.4.2"
    assert rm.logo_floor_enabled(new) and not rm.logo_floor_enabled(base)
    assert {k for k in set(base) | set(new) if base.get(k) != new.get(k)} == {
        "version", rm.LOGO_FLOOR_KEY, "meta"}
    assert {k for k in set(base["meta"]) | set(new["meta"])
            if base["meta"].get(k) != new["meta"].get(k)} == {"logo_floor"}
    assert new["meta"]["logo_floor"]["derived_from"] == base["version"]


def test_shipped_v143_only_adds_the_weak_run_rule():
    """v1.4.3(설계 §7-10, 2026-11-23 — v1.4.5 의 원본): v1.4.2 JSON 에 weak_run 규칙 2(엔진이
    이름 축을 계산할 때 약한 토큰열을 두 이름 모두에서 붙어 있는 구간만 묶음 — 견고성 점검
    R-P0-2)와 그 출처 meta 만 더했다. 계수·하한·규칙은 v1.4.2 그대로 — v1.4.2 를 다시 쓰면 이
    시험이 v1.4.3 도 다시
    만들라고 알린다(weak_run_adjacent.py)."""
    if not rm.V143_MODEL_PATH.exists() or not rm.V142_MODEL_PATH.exists():
        pytest.skip("v1.4.3 계수 파일 없음")
    base = json.loads(rm.V142_MODEL_PATH.read_text(encoding="utf-8"))
    new = json.loads(rm.V143_MODEL_PATH.read_text(encoding="utf-8"))
    assert rm.V143_MODEL_PATH.name == "risk_model_v1.4.3.json"
    assert new["version"] == "risk_model_v1.4.3"
    assert rm.weak_run_version(new) == 2 and rm.weak_run_version(base) == 1
    assert {k for k in set(base) | set(new) if base.get(k) != new.get(k)} == {
        "version", rm.WEAK_RUN_KEY, "meta"}
    assert {k for k in set(base["meta"]) | set(new["meta"])
            if base["meta"].get(k) != new["meta"].get(k)} == {"weak_run"}
    assert new["meta"]["weak_run"]["derived_from"] == base["version"]
    assert len(new["meta"]["weak_run"]["rule_sha256"]) == 64
    model = rm.load_model(rm.V143_MODEL_PATH)
    assert rm.coupling_violations(model) == [] and rm.logo_floor_enabled(model)


def test_shipped_v145_only_changes_the_image_goods_set():
    """v1.4.5(설계 §7-12, 2026-11-24 — v1.4.6 의 원본): v1.4.3 JSON 에서 이름 없는
    이미지+업종 집합만 로고 유사도 × 업종 겹침의 곱하기 항(변형 L)·goods_rule·이미지만과 같은
    기준으로 바꾸고 출처 meta 를 더했다(채택 조건 ③ 미달 — 사람 결정). 이름 있는 4벌·이미지만
    집합·규칙은 v1.4.3 그대로 — v1.4.3 을 다시 쓰면 이 시험이 v1.4.5 도 다시 만들라고
    알린다(goods_product.py apply)."""
    if not rm.V145_MODEL_PATH.exists() or not rm.V143_MODEL_PATH.exists():
        pytest.skip("v1.4.5 계수 파일 없음")
    base = json.loads(rm.V143_MODEL_PATH.read_text(encoding="utf-8"))
    new = json.loads(rm.V145_MODEL_PATH.read_text(encoding="utf-8"))
    assert new["version"] == "risk_model_v1.4.5" and not rm.goods_cap_enabled(new)
    assert {k for k in set(base) | set(new) if base.get(k) != new.get(k)} == {
        "version", rm.NAMELESS_KEY, "meta"}
    assert {k for k in set(base["meta"]) | set(new["meta"])
            if base["meta"].get(k) != new["meta"].get(k)} == {"nameless"}
    assert {k for k in set(base["meta"]["nameless"]) | set(new["meta"]["nameless"])
            if base["meta"]["nameless"].get(k) != new["meta"]["nameless"].get(k)} == {
        "goods_product"}
    assert {k for k in base[rm.NAMELESS_KEY]
            if base[rm.NAMELESS_KEY][k] != new[rm.NAMELESS_KEY][k]} == {"x2_whole+x4"}
    block = new[rm.NAMELESS_KEY]["x2_whole+x4"]
    assert block["features"] == ["x2_whole", "x2_whole×도형계", "x4", *rm.PRODUCT_TERMS]
    assert block[rm.GOODS_RULE_KEY] == rm.GOODS_RULE_NO_RAISE
    assert block["grade_thresholds"] == base[rm.NAMELESS_KEY]["x2_whole"]["grade_thresholds"]
    provenance = new["meta"]["nameless"]["goods_product"]
    assert provenance["variant"] == "L" and provenance["derived_from"] == base["version"]
    assert provenance["adopted"]["근거"] == "사람 결정" and len(provenance["rule_sha256"]) == 64
    model = rm.load_model(rm.V145_MODEL_PATH)
    assert rm.coupling_violations(model) == [] and rm.logo_floor_enabled(model)
    assert rm.weak_run_version(model) == 2
    # 업종이 안 겹치면 이미지만 판단 이하, 겹치면 로고가 닮은 만큼 오른다(곱하기 항)
    for x2 in (0.3, 0.6, 0.9, 1.0):
        alone = rm.risk_score({"x2_whole": x2, "mark_type": "도형"}, model).prob
        none = rm.risk_score({"x2_whole": x2, "x4": 0.0, "mark_type": "도형"}, model).prob
        full = rm.risk_score({"x2_whole": x2, "x4": 1.0, "mark_type": "도형"}, model).prob
        assert none <= alone + 1e-9 and full > none
    low = [rm.risk_score({"x2_whole": x2, "x4": x4, "mark_type": "도형"}, model).prob
           for x2 in (0.3, 0.9) for x4 in (0.0, 1.0)]
    assert low[3] - low[2] > low[1] - low[0]  # 업종의 몫은 로고가 닮을수록 크다


def test_shipped_v146_only_turns_the_goods_cap_on():
    """v1.4.6(설계 §7-13, 2026-11-24 — 사람 결정; v1.4.7 의 원본): v1.4.5 JSON 에 업종 상한
    `goods_cap.enabled` 만 켜고 출처 meta 를 더했다 — 계수·기준·다른 규칙은 v1.4.5 그대로(엔진이
    업종이 다르면 업종 없는 짝 판단의 등급 이하로 내린다). v1.4.5 를 다시 쓰면 이 시험이 v1.4.6 도
    다시 만들라고 알린다(goods_cap.py apply)."""
    if not rm.V146_MODEL_PATH.exists() or not rm.V145_MODEL_PATH.exists():
        pytest.skip("v1.4.6 계수 파일 없음")
    base = json.loads(rm.V145_MODEL_PATH.read_text(encoding="utf-8"))
    new = json.loads(rm.V146_MODEL_PATH.read_text(encoding="utf-8"))
    assert new["version"] == "risk_model_v1.4.6"
    assert {k for k in set(base) | set(new) if base.get(k) != new.get(k)} == {
        "version", rm.GOODS_CAP_KEY, "meta"}
    assert {k for k in set(base["meta"]) | set(new["meta"])
            if base["meta"].get(k) != new["meta"].get(k)} == {"goods_cap"}
    assert new[rm.GOODS_CAP_KEY] == {"enabled": True}
    provenance = new["meta"]["goods_cap"]
    assert provenance["derived_from"] == base["version"] and len(provenance["rule_sha256"]) == 64
    assert provenance["checks"] == {f"확인_{i}": True for i in range(1, 5)}
    model = rm.load_model(rm.V146_MODEL_PATH)
    assert rm.goods_cap_enabled(model) and rm.coupling_violations(model) == []
    assert rm.logo_floor_enabled(model) and rm.weak_run_version(model) == 2
    assert rm.named_grade_thresholds(model) == {}  # 이름 있는 집합의 자기 하한·goods_rule 없음
    for features in ({"x1_d": 0.16, "x2_text_d": 0.7, "x4": 0.01, "mark_type": "문자"},
                     {"x2_whole": 0.9, "x4": 0.0, "mark_type": "도형"}):
        assert rm.risk_score(features, model) == rm.risk_score(features, base)  # 위험도는 그대로


def test_shipped_v147_only_marks_the_famous_check():
    """서비스 기본 v1.4.7(설계 §7-14-13, 2026-11-26): v1.4.6 JSON 에 유명 상표 확인 표시
    `famous_check`(enabled·확정 파일의 version·sha256)와 출처 meta 만 더했다 — 계수·기준·다른
    규칙은 v1.4.6 그대로다(엔진이 질의마다 유명 상표 확인을 따로 해 전체 등급의 바닥만 더한다).
    표시의 sha256 은 저장소의 확정 파일의 것이어야 한다 — 확정 파일을 다시 만들면 이 시험이 v1.4.7
    도 다시 만들라고 알린다(famous_connect.py apply)."""
    from src import famous_runtime as fr

    if not rm.V147_MODEL_PATH.exists() or not rm.V146_MODEL_PATH.exists():
        pytest.skip("v1.4.7 계수 파일 없음")
    base = json.loads(rm.V146_MODEL_PATH.read_text(encoding="utf-8"))
    new = json.loads(rm.V147_MODEL_PATH.read_text(encoding="utf-8"))
    assert rm.DEFAULT_MODEL_PATH == rm.V147_MODEL_PATH
    assert new["version"] == rm.MODEL_VERSION == "risk_model_v1.4.7"
    assert {k for k in set(base) | set(new) if base.get(k) != new.get(k)} == {
        "version", rm.FAMOUS_CHECK_KEY, "meta"}
    assert {k for k in set(base["meta"]) | set(new["meta"])
            if base["meta"].get(k) != new["meta"].get(k)} == {rm.FAMOUS_CHECK_KEY}
    mark = new[rm.FAMOUS_CHECK_KEY]
    assert mark["enabled"] is True and mark["version"] == fr.CONFIRMED_VERSION
    assert mark["confirmed_sha256"] == fr.file_sha256(fr.CONFIRMED_PATH)
    assert new["meta"][rm.FAMOUS_CHECK_KEY]["derived_from"] == base["version"]
    model = rm.load_model(rm.V147_MODEL_PATH)
    assert rm.famous_check_enabled(model) and rm.famous_check_config(model) == mark
    assert not rm.famous_check_enabled(rm.load_model(rm.V146_MODEL_PATH))
    assert rm.famous_check_config(rm.load_model(rm.V146_MODEL_PATH)) is None
    assert rm.goods_cap_enabled(model) and rm.logo_floor_enabled(model)
    assert rm.weak_run_version(model) == 2 and rm.coupling_violations(model) == []
    for features in ({"x1_d": 0.16, "x2_text_d": 0.7, "x4": 0.01, "mark_type": "문자"},
                     {"x2_whole": 0.9, "x4": 0.0, "mark_type": "도형"}, {}):
        assert rm.risk_score(features, model) == rm.risk_score(features, base)  # 위험도는 그대로


def test_famous_check_mark_format():
    """famous_check 는 enabled(true/false)를 가진 객체 — 켜려면 version 과 confirmed_sha256(64자리
    16진수)이 있어야 한다. 키가 없으면 꺼짐."""
    assert not rm.famous_check_enabled(_model())
    off = _model(**{rm.FAMOUS_CHECK_KEY: {"enabled": False}})
    assert not rm.famous_check_enabled(off) and rm.famous_check_config(off) is None
    good = {"enabled": True, "version": "famous_check_confirmed_v1", "confirmed_sha256": "a" * 64}
    assert rm.famous_check_config(_model(**{rm.FAMOUS_CHECK_KEY: good})) == good
    for bad in (True, {"enabled": "yes"}, {"enabled": True},
                {"enabled": True, "version": "v", "confirmed_sha256": "abc"},
                {"enabled": True, "version": "", "confirmed_sha256": "a" * 64},
                {"enabled": True, "version": "v", "confirmed_sha256": "A" * 64}):
        with pytest.raises(ValueError):
            _model(**{rm.FAMOUS_CHECK_KEY: bad})

