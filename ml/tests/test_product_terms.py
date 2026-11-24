"""이름 없는 이미지+업종 집합의 곱하기 항(통합 모델 설계 §7-12) — 런타임 계산·검증. 곱하기 항이 없는
v1.4.3 JSON 은 예전과 같은 계산이어야 한다."""

from __future__ import annotations

import copy

import pytest
from src.model import risk_model as rm

C_TEXT, C_FIGURE = 0.6419, 0.5579


@pytest.fixture(scope="module")
def base() -> dict:
    return rm.load_model(rm.V143_MODEL_PATH)


def _nameless(x2, x4, mark_type="도형") -> dict:
    return {"x1_d": None, "x2_text_d": None, "x3_d": None, "x2_whole": x2, "x4": x4,
            "has_meaning_both": False, "mark_type": mark_type}


def _toy(base: dict, e: float, f: float, *, hinge: bool = False, intercept: float = -1.9187,
         rule: bool = True) -> dict:
    model = copy.deepcopy(base)
    block = model[rm.NAMELESS_KEY]["x2_whole+x4"]
    names = ([rm.hinge_term_name(C_TEXT, C_FIGURE), rm.hinge_term_name(C_TEXT, C_FIGURE,
                                                                      figure=True)]
             if hinge else list(rm.PRODUCT_TERMS))
    block["features"] = ["x2_whole", "x2_whole×도형계", "x4", *names]
    block["coefficients"] = {"x2_whole": 2.1447, "x2_whole×도형계": 0.3229, "x4": 0.0,
                             names[0]: e, names[1]: f}
    block["intercept"] = intercept
    if rule:
        block[rm.GOODS_RULE_KEY] = rm.GOODS_RULE_NO_RAISE
    return model


def test_product_and_hinge_values():
    values = rm.design_values(_nameless(0.8, 0.5))
    assert values["x2_whole×x4"] == pytest.approx(0.4)
    assert values["x2_whole×도형계×x4"] == pytest.approx(0.4)
    assert rm.design_values(_nameless(0.8, 0.5, "문자"))["x2_whole×도형계×x4"] == 0.0
    name = rm.hinge_term_name(C_TEXT, C_FIGURE)
    figure_name = rm.hinge_term_name(C_TEXT, C_FIGURE, figure=True)
    assert name == "hinge(x2_whole;0.6419;0.5579)×x4" and rm.is_product_term(figure_name)
    assert rm.term_value(name, values) == pytest.approx((0.8 - C_FIGURE) * 0.5)  # 도형계 c
    text = rm.design_values(_nameless(0.8, 0.5, "결합-문자요부"))
    assert rm.term_value(name, text) == pytest.approx((0.8 - C_TEXT) * 0.5)  # 문자계 c
    assert rm.term_value(figure_name, text) == 0.0
    assert rm.term_value(name, rm.design_values(_nameless(0.5, 1.0))) == 0.0  # c 아래
    assert rm.term_value(name, rm.design_values(_nameless(None, 1.0))) == 0.0  # 이미지 결측
    assert rm.design_vector(_nameless(0.8, 0.5), [name, "x4"]) == pytest.approx(
        [(0.8 - C_FIGURE) * 0.5, 0.5])
    with pytest.raises(ValueError):
        rm.design_vector(_nameless(0.8, 0.5), ["hinge(x2_whole;2;0.5)×x4"])


def test_v143_has_no_product_terms_and_scores_as_before(base):
    assert not any(rm.is_product_term(name) for block in base[rm.NAMELESS_KEY].values()
                   for name in block["features"])
    for x2 in (0.0, 0.3, 0.7, 1.0):
        for x4 in (None, 0.0, 0.5, 1.0):
            features = _nameless(x2, x4)
            result = rm.risk_score(features, base)
            key, block = rm.select_pattern(base, rm.design_values(features))
            assert result.pattern == key
            assert sum(result.contributions.values()) == pytest.approx(
                rm.block_logit(block, rm.design_values(features)))


@pytest.mark.parametrize("hinge", [False, True])
def test_goods_rule_replaces_the_level_coupling(base, hinge):
    model = _toy(base, 0.2, 0.1, hinge=hinge)
    assert rm.coupling_violations(model) == []
    rm.validate_model(model)
    higher = _toy(base, 0.2, 0.1, hinge=hinge, intercept=-1.9)  # 업종 0 에서 이미지만보다 높음
    assert any("(x4 = 0) >" in v for v in rm.coupling_violations(higher))
    with pytest.raises(ValueError):
        rm.validate_model(higher)
    lower = _toy(base, 0.2, 0.1, hinge=hinge, intercept=-2.5)  # 옛 결합(겹침 하한에서 이상)은 안 봄
    assert rm.coupling_violations(lower) == []
    plain = _toy(base, 0.2, 0.1, hinge=hinge, intercept=-2.5, rule=False)
    assert any(v.startswith("noname:x2_whole → noname:x2_whole+x4")
               for v in rm.coupling_violations(plain))


def test_product_terms_must_be_non_negative_and_stay_in_the_goods_set(base):
    model = _toy(base, -0.1, 0.1)
    assert any(v.startswith("x2_whole×x4") for v in rm.monotone_violations(
        model[rm.NAMELESS_KEY]["x2_whole+x4"]["coefficients"]))
    with pytest.raises(ValueError):
        rm.validate_model(model)
    named = copy.deepcopy(base)
    block = named["patterns"]["x2_whole+x4"]
    block["features"] = [*block["features"], "x2_whole×x4"]
    block["coefficients"] = {**block["coefficients"], "x2_whole×x4": 0.1}
    with pytest.raises(ValueError):
        rm.validate_model(named)
    wrong = _toy(base, 0.2, 0.1)
    wrong[rm.NAMELESS_KEY]["x2_whole+x4"][rm.GOODS_RULE_KEY] = "anything"
    with pytest.raises(ValueError):
        rm.validate_model(wrong)
    top = copy.deepcopy(base)  # 최상위(패턴 없는 옛 JSON 의 유일한 집합)에도 두지 않는다
    top["features"] = [*top["features"], "x2_whole×x4"]
    top["coefficients"] = {**top["coefficients"], "x2_whole×x4": 0.1}
    with pytest.raises(ValueError):
        rm.validate_model(top)


def test_product_terms_count_as_the_goods_contribution(base):
    model = _toy(base, 0.5, 0.3, hinge=True)
    features = _nameless(0.9, 1.0)
    result = rm.risk_score(features, model)
    grouped = rm.axis_contributions(result.contributions)
    assert rm.term_axis("x2_whole×x4") == "X4"
    assert rm.term_axis(rm.hinge_term_name(C_TEXT, C_FIGURE)) == "X4"
    assert grouped["X4"] == pytest.approx(0.5 * (0.9 - C_FIGURE) + 0.3 * (0.9 - C_FIGURE))
    assert result.contributions["intercept"] + sum(
        value for key, value in grouped.items()) == pytest.approx(
        rm.block_logit(model[rm.NAMELESS_KEY]["x2_whole+x4"], rm.design_values(features)))
