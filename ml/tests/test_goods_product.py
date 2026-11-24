"""goods_product.py(이름 없는 '이미지+업종' 판단의 곱하기 항 — 변형 L·H)의 순수 함수·채택 판정."""

from __future__ import annotations

import math

import numpy as np
import pytest
from src.model import risk_model as rm

from scripts import goods_product as gp


@pytest.fixture(scope="module")
def base() -> dict:
    return rm.load_model(gp.BASE_MODEL_PATH)


def _entry(variant: str, e: float, f: float, *, x4: float = 0.0,
           intercept: float = -1.9187) -> dict:
    names = ["x2_whole", "x2_whole×도형계", "x4", *gp.product_names(variant)]
    return {"features": names, "intercept": intercept,
            "coefficients": {"x2_whole": 2.1447, "x2_whole×도형계": 0.3229, "x4": x4,
                             names[3]: e, names[4]: f}}


def test_settings_hash_is_stable_and_covers_rules():
    assert gp.rule_sha256() == gp.rule_sha256()
    assert {"구조", "제약", "학습", "진단", "기준", "채택_1", "채택_2", "채택_3", "채택_4",
            "채택_5", "채택_6", "채택_7", "판정", "전후", "적용"} <= set(gp.RULE)
    assert gp.NEW_VERSION == "risk_model_v1.4.5" and gp.VARIANTS == ("L", "H")


def test_hinge_points_are_where_the_image_only_set_reaches_caution(base):
    assert gp.hinge_points(base) == gp.HINGE_C
    block = base[rm.NAMELESS_KEY][gp.X_KEY]
    caution = rm.grade_thresholds_for(base, gp.X)[gp.CAUTION]
    for level, c in (("문자", gp.HINGE_C["문자계"]), ("도형", gp.HINGE_C["도형계"])):
        prob = rm.risk_score(gp.level_features(c, None, level), base).prob
        assert prob == pytest.approx(caution, abs=1e-4)
    flat = {**base, rm.NAMELESS_KEY: {**base[rm.NAMELESS_KEY], gp.X_KEY: {
        **block, "coefficients": {"x2_whole": 0.1, "x2_whole×도형계": 0.0}}}}
    assert gp.hinge_points(flat) == {"문자계": 1.0, "도형계": 1.0}  # 0–1 안에서 주의에 못 닿음


def test_product_names_per_variant():
    assert gp.product_names("L") == ["x2_whole×x4", "x2_whole×도형계×x4"]
    assert gp.product_names("H") == ["hinge(x2_whole;0.6419;0.5579)×x4",
                                     "hinge(x2_whole;0.6419;0.5579)×도형계×x4"]
    assert all(rm.is_product_term(name) for name in gp.product_names("H"))
    with pytest.raises(ValueError):
        gp.product_names("Q")


def test_thresholds_start_at_image_only_and_rise_only_past_the_target():
    image_only = {"주의": 0.3677, "검토 권장": 0.491, "위험": 0.5724}
    calm = [0.1] * 95 + [0.5] * 4 + [0.6]  # 검토 권장 이상 5%·위험 이상 1% — 그대로
    out = gp.start_thresholds(calm, image_only)
    assert out["기준"] == image_only
    assert not out["자세히"]["검토 권장"]["올림"] and not out["자세히"]["위험"]["올림"]
    busy = [0.1] * 80 + [0.55] * 15 + [0.7] * 5  # 20%·5% — 둘 다 올림
    out = gp.start_thresholds(busy, image_only)
    assert out["기준"]["주의"] == 0.3677
    assert out["기준"]["검토 권장"] == 0.5501 and out["기준"]["위험"] == 0.7001
    assert gp.start_thresholds(busy, image_only)["기준"]["검토 권장"] > image_only["검토 권장"]


def test_choose_prefers_the_higher_cited_rate_then_l():
    assert gp.choose({"L": False, "H": False}, {"L": 0.3, "H": 0.4}) is None
    assert gp.choose({"L": False, "H": True}, {"L": 0.9, "H": 0.1}) == "H"
    assert gp.choose({"L": True, "H": True}, {"L": 0.3, "H": 0.4}) == "H"
    assert gp.choose({"L": True, "H": True}, {"L": 0.4, "H": 0.4}) == "L"


def test_round_block_clamps_monotone_terms():
    names = gp.product_names("L")
    out = gp.round_block(["x2_whole", "x2_whole×도형계", "x4", *names],
                         np.asarray([0.00004, -0.00006, -0.00004, -0.00003, 0.12345]), -1.23456)
    assert out["coefficients"] == {"x2_whole": 0.0, "x2_whole×도형계": 0.0, "x4": 0.0,
                                   names[0]: 0.0, names[1]: 0.1235}
    assert out["intercept"] == -1.2346


def test_goods_block_replaces_only_the_image_goods_set(base):
    model = gp.with_block(base, _entry("H", 0.4, 0.2), thresholds={
        "주의": 0.3677, "검토 권장": 0.5, "위험": 0.6})
    block = model[rm.NAMELESS_KEY][gp.XG_KEY]
    assert block[rm.GOODS_RULE_KEY] == rm.GOODS_RULE_NO_RAISE
    assert block["grade_thresholds"] == {"주의": 0.3677, "검토 권장": 0.5, "위험": 0.6}
    assert model[rm.NAMELESS_KEY][gp.X_KEY] == base[rm.NAMELESS_KEY][gp.X_KEY]
    assert model["patterns"] == base["patterns"]
    rm.validate_model(model)
    assert gp.rule_sha256()  # 설정은 모델과 무관


def test_repair_lowers_only_the_goods_intercept(base):
    # 겹침 0 에서 이미지만보다 높음
    model = gp.with_block(base, _entry("L", 0.2, 0.1, intercept=-1.9))
    assert rm.coupling_violations(model)
    fixed, info = gp.repair_intercept(model)
    assert info["고침"] and info["걸음"] == 187  # −1.9 → −1.9187(이미지만 절편)
    assert fixed[rm.NAMELESS_KEY][gp.XG_KEY]["intercept"] == -1.9187
    assert rm.coupling_violations(fixed) == []
    assert fixed[rm.NAMELESS_KEY][gp.X_KEY] == base[rm.NAMELESS_KEY][gp.X_KEY]


def test_direction_check_on_a_model_that_keeps_the_principle(base):
    image_only = rm.grade_thresholds_for(base, gp.X)
    model = gp.with_block(base, _entry("H", 0.0, 0.0, intercept=-1.95), thresholds=image_only)
    # 곱하기 항 0·업종 0·절편이 더 낮음 → 겹침이 있어도 이미지만 이하, 겹침 ≥ 하한이면 업종 하한
    for x2 in (0.2, 0.56, 0.76, 0.95):
        for x4 in (0.0, 0.01, 0.0252, 0.5, 1.0):
            assert not gp.direction_violation(x2, x4, model, base)
    grid = gp.grid_check(model, base, step=0.05)
    assert all(not v["어김"] for v in grid.values())


def test_direction_check_finds_the_current_additive_model(base):
    # v1.4.3: 이미지+업종 주의 0.2944 < 이미지만 0.3677 — 겹침이 하한 미만이어도 등급이 올라가는 띠
    grid = gp.grid_check(base, base, step=0.01)
    assert grid["도형"]["어김"].get("하한_아래", 0) > 0
    assert grid["도형"]["어김"].get("하한_이상", 0) == 0  # 업종 하한이 막는다


def test_probe_table_and_level_features(base):
    features = gp.level_features(0.7, 1.0, "문자")
    assert features["mark_type"] == "문자" and features["x4"] == 1.0 and features["x1_d"] is None
    table = gp.probe_table(base, base)
    assert set(table) == {"도형", "문자"} and set(table["도형"]) == {"0.3", "0.5", "0.7", "0.9"}
    row = table["도형"]["0.9"]
    assert row["겹침 1"] > row["겹침 0"] and row["이미지만"] == pytest.approx(
        rm.risk_score(gp.level_features(0.9, None, "도형"), base).prob, abs=1e-4)
    logit = lambda p: math.log(p / (1 - p))  # noqa: E731
    assert logit(row["겹침 1"]) - logit(row["겹침 0"]) == pytest.approx(1.5302, abs=2e-3)


def test_named_control_condition_allows_no_increase():
    def row(now, new):
        return {"방식": {gp.NAMED_GOODS_MODE: {"지금": {"전체": now}, "H": {"전체": new}}}}
    rows = [row("검토 권장", "주의"), row("주의", "주의")]
    assert gp.check_named(rows, "H")["통과"]
    assert not gp.check_named([row("주의", "검토 권장")], "H")["통과"]


def test_smoke_needs_its_own_out_dir(tmp_path):
    assert gp.main(["run", "--smoke"]) == gp.EXIT_REFUSED
    assert gp.main(["run", "--out-dir", str(tmp_path)]) == gp.EXIT_REFUSED  # freeze 없음
