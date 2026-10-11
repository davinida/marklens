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
    prob, grade, contributions, caveat = rm.risk_score(features, model)
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
    prob0, grade0, c0, _ = rm.risk_score({}, model)
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
    prob, grade, _, _ = rm.risk_score(low, model)
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
    assert rm.risk_score(low, legacy) == (*rm.risk_score(low, legacy)[:3], False)
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
    assert rm.MODEL_VERSION == "risk_model_v1.2.1"
    with pytest.raises(ValueError):
        _model(version="risk_model_v2")


def test_shipped_model_file_is_valid():
    """저장소의 shared/model/risk_model_v1.json 이 검증을 통과하고 점수를 낸다."""
    if not rm.DEFAULT_MODEL_PATH.exists():
        pytest.skip("계수 파일 없음(학습 전)")
    model = rm.load_model()
    prob, grade, contributions, caveat = rm.risk_score(
        {"x1_d": 1.0, "x2_text_d": 1.0, "x2_whole": 0.8, "x3_d": 0.9, "x4": 1.0,
         "has_meaning_both": True, "mark_type": "문자"}, model)
    assert 0.0 <= prob <= 1.0 and grade in rm.GRADES and caveat is False
    assert sum(contributions.values()) == pytest.approx(math.log(prob / (1 - prob)))
    assert model["meta"]["n_trial"] > 0
    if model.get("monotone"):
        assert rm.monotone_violations(model["coefficients"]) == []
    if model["version"] in ("risk_model_v1.1", "risk_model_v1.2"):
        assert not any(name.startswith("type_") for name in model["features"])
        assert model["standalone_precision"] == 0.7
    if model["version"].startswith("risk_model_v1.2"):
        assert "any_no_distinctive" in model["features"]
        assert model["figure_rule"]["validated"] is False
        figure = rm.risk_score({"x1_d": 0.0, "x2_whole": 0.95, "mark_type": "도형"}, model)
        assert figure.figure_caveat and figure.grade in ("검토 권장", "위험")
