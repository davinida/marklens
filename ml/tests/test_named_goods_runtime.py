"""이름 있는 업종 두 벌(x4·x2_whole+x4)의 곱하기 항·업종 규칙·자기 하한, 업종 상한 표시(통합 모델
설계 §7-13) — 런타임 계산·검증. 이 키가 없는 v1.4.5 JSON 은 예전과 같은 계산이어야 한다."""

from __future__ import annotations

import copy
import math

import pytest
from src.model import risk_model as rm


@pytest.fixture(scope="module")
def base() -> dict:
    return rm.load_model(rm.V145_MODEL_PATH)


def _named(x1, x2t, x4, *, x2=None, level="문자", distinctive=True) -> dict:
    return {"x1_d": x1, "x2_text_d": x2t, "x3_d": None, "x2_whole": x2, "x4": x4,
            "has_meaning_both": False, "has_distinctive_part_a": True,
            "has_distinctive_part_b": distinctive, "mark_type": level}


def _with_named_block(base: dict, key: str, extra: dict[str, float], *, delta: float = 0.0,
                      rule: bool = True, thresholds: dict | None = None) -> dict:
    model = copy.deepcopy(base)
    block = model["patterns"][key]
    block["features"] = [*block["features"], *extra]
    block["coefficients"] = {**block["coefficients"], **extra}
    block["intercept"] = round(block["intercept"] + delta, 4)
    if rule:
        block[rm.GOODS_RULE_KEY] = rm.GOODS_RULE_NO_RAISE
    if thresholds is not None:
        block["grade_thresholds"] = thresholds
    if key == model["reference_pattern"]:  # 최상위는 기준 패턴의 사본
        model.update(features=block["features"], coefficients=block["coefficients"],
                     intercept=block["intercept"])
    return model


def _no_raise_shift(base: dict, key: str) -> float:
    """그 집합의 x4 를 0 으로 둔 로짓이 짝 이하가 되도록 내릴 절편(꼭짓점 최대 차, 넷째 자리
    올림)."""
    pair = base["patterns"][rm.goods_pair_key(key, base["pattern_axes"])]
    block = base["patterns"][key]
    worst = max(rm.block_logit(block, rm.design_values({**v, "x4": 0.0}), base)
                - rm.block_logit(pair, rm.design_values(v), base)
                for v in rm.coupling_vertices(pair["features"]))
    return -math.ceil(max(worst, 0.0) * 10000) / 10000


def test_name_products_and_pair_term_values(base):
    values = rm.design_values(_named(0.8, 0.5, 0.5, distinctive=False))
    assert values["x1_d×x4"] == pytest.approx(0.4)
    assert values["x2_text_d×x4"] == pytest.approx(0.25)
    assert values["x1_d×문자계×x4"] == pytest.approx(0.4)
    assert values["x1_d×any_no_distinctive×x4"] == pytest.approx(0.4)
    assert values["x3_d×x4"] == 0.0  # 관념 게이트가 꺼지면 0
    assert set(rm.NAME_PRODUCT_TERMS) <= set(values)
    name = rm.pair_term_name("base")
    assert name == "pair(base)×x4" and rm.is_product_term(name) and rm.term_axis(name) == "X4"
    p_base = 1 / (1 + math.exp(-rm.block_logit(base["patterns"]["base"], values, base)))
    assert rm.term_value(name, values, base) == pytest.approx(p_base * 0.5)
    assert rm.term_value(name, rm.design_values(_named(0.8, 0.5, 0.0)), base) == 0.0
    with pytest.raises(ValueError):
        rm.term_value(name, values)  # 짝 계수 집합이 있는 모델이 있어야
    assert rm.goods_pair_key("x2_whole+x4", base["pattern_axes"]) == "x2_whole"
    assert rm.goods_pair_key("x2_whole", base["pattern_axes"]) is None


def test_v145_has_no_named_goods_keys(base):
    assert not rm.goods_cap_enabled(base) and rm.named_grade_thresholds(base) == {}
    for block in base["patterns"].values():
        assert rm.GOODS_RULE_KEY not in block and "grade_thresholds" not in block
        assert not any(rm.is_product_term(name) for name in block["features"])
    assert rm.grade_thresholds_for(base, "x4") == base["grade_thresholds"]


def _goods_messages(model: dict, key: str) -> list[str]:
    """그 업종 집합의 업종 관련 결합 메시지만(다른 제약은 장난감 모델이라 신경 쓰지 않는다)."""
    pair = rm.goods_pair_key(key, model["pattern_axes"])
    return [v for v in rm.coupling_violations(model)
            if v.startswith(f"{key} (x4 = 0) >") or v.startswith(f"{pair} → {key} (x4")]


@pytest.mark.parametrize("key", ["x4", "x2_whole+x4"])
def test_named_goods_rule_checks_zero_overlap_instead_of_the_floor(base, key):
    extra = {name: 0.1 for name in rm.NAME_PRODUCT_TERMS}
    shift = _no_raise_shift(base, key)
    assert _goods_messages(_with_named_block(base, key, extra, delta=shift), key) == []
    higher = _with_named_block(base, key, extra, delta=shift + 0.5)  # 겹침 0 에서 짝보다 높음
    assert any(" (x4 = 0) >" in v for v in _goods_messages(higher, key))
    # 옛 결합(하한에서 짝 이상)은 안 봄
    lower = _with_named_block(base, key, extra, delta=shift - 3.0)
    assert _goods_messages(lower, key) == []
    plain = _with_named_block(base, key, extra, delta=shift - 3.0, rule=False)
    assert any(" → " in v for v in _goods_messages(plain, key))
    assert rm.validate_model(base) is base  # v1.4.5 는 그대로 통과


def test_pair_term_variant_scores_through_the_pair_block(base):
    key = "x2_whole+x4"
    model = _with_named_block(base, key, {rm.pair_term_name("x2_whole"): 0.8},
                              delta=_no_raise_shift(base, key))
    assert _goods_messages(model, key) == []
    features = _named(0.9, 0.9, 1.0, x2=0.8)
    result = rm.risk_score(features, model)
    assert result.pattern == key
    pair = rm.risk_score({**features, "x4": None}, model)
    assert result.contributions[rm.pair_term_name("x2_whole")] == pytest.approx(0.8 * pair.prob)
    grouped = rm.axis_contributions(result.contributions)
    assert grouped["X4"] == pytest.approx(result.contributions["x4"] + 0.8 * pair.prob)
    assert sum(result.contributions.values()) == pytest.approx(
        math.log(result.prob / (1 - result.prob)))


def test_named_goods_placement_is_checked(base):
    axes = base["pattern_axes"]

    def check(key: str, extra: dict, rule: object = None) -> None:
        block = copy.deepcopy(base["patterns"][key])
        block["features"] = [*block["features"], *extra]
        block["coefficients"] = {**block["coefficients"], **extra}
        if rule is not None:
            block[rm.GOODS_RULE_KEY] = rule
        rm._validate_named_goods(block, key, axes)  # noqa: SLF001

    check("x4", {"x1_d×x4": 0.1, rm.pair_term_name("base"): 0.2}, rm.GOODS_RULE_NO_RAISE)
    check("x2_whole+x4", {"x2_whole×x4": 0.1, "x2_whole×도형계×x4": 0.1})
    for key, extra, rule in (("x2_whole", {"x1_d×x4": 0.1}, None),  # 업종이 없는 집합의 곱
                             ("base", {}, rm.GOODS_RULE_NO_RAISE),  # 업종이 없는 집합의 규칙
                             ("x4", {rm.pair_term_name("x2_whole"): 0.1}, None),  # 짝이 아님
                             ("x4", {"x2_whole×x4": 0.1}, None),  # 이미지 곱인데 이미지가 없음
                             ("x4", {rm.hinge_term_name(0.6, 0.5): 0.1}, None),  # 꺾인 곱
                             ("x4", {}, "anything")):
        with pytest.raises(ValueError):
            check(key, extra, rule)
    negative = copy.deepcopy(base["patterns"]["x4"]["coefficients"])
    negative["x1_d×x4"] = -0.1
    assert any(v.startswith("x1_d×x4") for v in rm.monotone_violations(negative))
    nameless = copy.deepcopy(base)
    block = nameless[rm.NAMELESS_KEY]["x2_whole+x4"]
    block["features"] = [*block["features"], "x1_d×x4"]
    block["coefficients"] = {**block["coefficients"], "x1_d×x4": 0.1}
    with pytest.raises(ValueError, match="이름에서 나오는 항"):
        rm.validate_model(nameless)


def test_named_thresholds_and_goods_cap_flag(base):
    own = {"주의": 0.0902, "검토 권장": 0.55, "위험": 0.62}
    model = copy.deepcopy(base)
    model["patterns"]["x4"]["grade_thresholds"] = own
    model[rm.GOODS_CAP_KEY] = {"enabled": True}
    rm.validate_model(model)
    assert rm.grade_thresholds_for(model, "x4") == own
    assert rm.grade_thresholds_for(model, "base") == base["grade_thresholds"]
    assert rm.named_grade_thresholds(model) == {"x4": own} and rm.goods_cap_enabled(model)
    bad = copy.deepcopy(model)
    bad["patterns"]["x4"]["grade_thresholds"] = {"주의": 0.6, "검토 권장": 0.5, "위험": 0.7}
    with pytest.raises(ValueError):
        rm.validate_model(bad)
    flag = copy.deepcopy(model)
    flag[rm.GOODS_CAP_KEY] = {"enabled": "yes"}
    with pytest.raises(ValueError):
        rm.validate_model(flag)
