"""named_goods_product.py(이름 있는 업종 두 벌의 곱하기 항 — 변형 L·S, 통합 모델 설계 §7-13)의 순수
함수·채택 판정."""

from __future__ import annotations

import copy

import numpy as np
import pytest
from src.model import risk_model as rm

from scripts import named_goods_product as ngp


@pytest.fixture(scope="module")
def base() -> dict:
    return rm.load_model(ngp.BASE_MODEL_PATH)


def _named(x1, x2t, x4, *, x2=None, level="문자") -> dict:
    return {"x1_d": x1, "x2_text_d": x2t, "x3_d": None, "x2_whole": x2, "x4": x4,
            "has_meaning_both": False, "has_distinctive_part_a": True,
            "has_distinctive_part_b": True, "mark_type": level}


def test_settings_hash_and_rules():
    assert ngp.rule_sha256() == ngp.rule_sha256()
    assert {"구조", "제약", "업종_상한", "학습", "지금_재현", "새_음성", "기준", "채택_1", "채택_2",
            "채택_3", "채택_4", "채택_5", "채택_6", "채택_7", "판정", "진단", "전후",
            "적용"} <= set(ngp.RULE)
    assert ngp.NEW_VERSION == "risk_model_v1.4.6" and ngp.VARIANTS == ("L", "S")


def test_product_names_per_variant_and_set():
    assert ngp.product_names("L", "x4") == list(rm.NAME_PRODUCT_TERMS)
    assert ngp.product_names("L", "x2_whole+x4") == [*rm.NAME_PRODUCT_TERMS, *rm.PRODUCT_TERMS]
    assert ngp.product_names("S", "x4") == ["pair(base)×x4"]
    assert ngp.product_names("S", "x2_whole+x4") == ["pair(x2_whole)×x4"]
    with pytest.raises(ValueError):
        ngp.product_names("H", "x4")


def test_thresholds_start_at_the_common_cut_and_rise_only_past_the_target():
    common = {"주의": 0.0902, "검토 권장": 0.5059, "위험": 0.5902}
    calm = [0.1] * 95 + [0.52] * 4 + [0.6]
    assert ngp.start_thresholds(calm, common)["기준"] == common
    busy = [0.1] * 80 + [0.55] * 15 + [0.7] * 5
    out = ngp.start_thresholds(busy, common)["기준"]
    assert out == {"주의": 0.0902, "검토 권장": 0.5501, "위험": 0.7001}
    assert ngp.start_thresholds([0.01] * 100, common)["기준"] == common  # 낮추지 않음


def test_choose_prefers_the_higher_cited_rate_then_s():
    assert ngp.choose({"L": False, "S": False}, {"L": 0.5, "S": 0.6}) is None
    assert ngp.choose({"L": True, "S": False}, {"L": 0.1, "S": 0.9}) == "L"
    assert ngp.choose({"L": True, "S": True}, {"L": 0.7, "S": 0.6}) == "L"
    assert ngp.choose({"L": True, "S": True}, {"L": 0.6, "S": 0.6}) == "S"


def test_round_named_clamps_and_fixes_monotone_combos():
    names = ["x1_d", "x1_d×문자계", "x1_d×any_no_distinctive", "x4", "x1_d×x4"]
    out = ngp.round_named(names, np.asarray([1.00004, 0.5, -1.00006, -0.00004, -0.00003]), -2.0)
    coefficients = out["coefficients"]
    assert coefficients["x4"] == 0.0 and coefficients["x1_d×x4"] == 0.0
    assert coefficients["x1_d"] + coefficients["x1_d×any_no_distinctive"] >= 0
    assert rm.monotone_violations(coefficients) == []


def test_with_named_keeps_common_cuts_and_updates_the_reference_copy(base):
    entry = {"features": [*base["patterns"]["x2_whole+x4"]["features"], "x1_d×x4"],
             "coefficients": {**base["patterns"]["x2_whole+x4"]["coefficients"], "x1_d×x4": 0.1},
             "intercept": -3.6}
    model = ngp.with_named(base, {"x2_whole+x4": entry},
                           thresholds={"x2_whole+x4": base["grade_thresholds"],
                                       "x4": {"주의": 0.0902, "검토 권장": 0.55, "위험": 0.6}})
    block = model["patterns"]["x2_whole+x4"]
    assert block[rm.GOODS_RULE_KEY] == rm.GOODS_RULE_NO_RAISE and "grade_thresholds" not in block
    assert model["features"] == block["features"] and model["intercept"] == -3.6
    assert rm.goods_cap_enabled(model) and "grade_thresholds" not in model["patterns"]["x4"]
    own = ngp.with_named(base, {"x4": {k: base["patterns"]["x4"][k] for k in (
        "features", "coefficients", "intercept")}}, thresholds={"x4": {
            "주의": 0.0902, "검토 권장": 0.55, "위험": 0.6}})
    assert own["patterns"]["x4"]["grade_thresholds"]["검토 권장"] == 0.55


def test_repair_lowers_the_set_that_rises_above_its_pair_at_zero_overlap(base):
    pair = base["patterns"]["base"]  # 짝 계수 + 업종 항 — 겹침 0 에서 짝보다 0.0005 높음
    entry = {"features": [*pair["features"], "x4"],
             "coefficients": {**pair["coefficients"], "x4": 0.9583},
             "intercept": round(pair["intercept"] + 0.0005, 4)}
    model = ngp.with_named(base, {"x4": entry})
    assert any(v.startswith("x4 (x4 = 0) >") for v in rm.coupling_violations(model))
    fixed, info = ngp.repair_intercepts(model)
    assert not any(v.startswith("x4 (x4 = 0) >") for v in rm.coupling_violations(fixed))
    assert info["걸음"].get("x4 내림", 0) > 0


def test_grade_with_rules_matches_risk_score(base):
    for features in (_named(0.99, 0.2, 0.5), _named(0.3, 0.8, 0.0), _named(0.5, 0.5, None),
                     _named(0.2, 0.1, 1.0, x2=0.95, level="도형")):
        result = rm.risk_score(features, base)
        assert ngp.grade_with_rules(result.prob, features, base, result.pattern) == result.grade


def test_goods_rules_and_engine_grade(base):
    model = copy.deepcopy(base)
    model[rm.GOODS_CAP_KEY] = {"enabled": True}
    features = _named(0.16, 0.7, 0.01)  # v1.4.5: x4 집합 주의 > base 안전
    result = rm.risk_score(features, base)
    pair = rm.risk_score({**features, "x4": None}, base)
    assert (result.grade, pair.grade) == ("주의", "안전")
    assert ngp.goods_rules(result.grade, features, model, "x4", pair.grade) == ("안전",
                                                                              "goods_cap")
    assert ngp.goods_rules(result.grade, features, base, "x4", pair.grade) == ("주의", None)
    assert ngp.engine_grade(features, model) == "안전"
    assert ngp.engine_grade(features, base) == "주의"
    assert ngp.engine_grade(features, base, set_prob=result.prob) == "주의"
    logo = _named(0.0, 0.0, 0.5, x2=1.0, level="결합-문자요부")  # 이미지만 판단(도형계)이 위험
    assert ngp.engine_grade(logo, base) == "위험"


def test_direction_check_finds_the_additive_named_sets(base):
    points = [_named(x1 / 50, x2t / 20, 0.01) for x1 in range(0, 51) for x2t in range(0, 21)]
    found = ngp.direction_check(points, base)
    assert found["어김"].get("x4 다름", 0) > 0  # v1.4.5 는 업종이 달라도 짝보다 높을 수 있다
    table = ngp.probe_table(base)
    assert set(table) == set(ngp.SETS) and set(table["x4"]) == {"0.3", "0.5", "0.7", "0.9"}
    assert table["x4"]["0.9"]["겹침 1"] > table["x4"]["0.9"]["겹침 0"]


def test_grid_points_cover_both_families_and_overlaps():
    x4_points = list(ngp.grid_points("x4"))
    assert len(x4_points) == 21 * 21 * 4 * 2 * 2
    assert {p["mark_type"] for p in x4_points} == set(ngp.LEVELS)
    assert len(list(ngp.grid_points("x2_whole+x4"))) == 11 * 11 * 11 * 4 * 2 * 2
    assert 0.0 in ngp.X4_GRID and 0.0252 in ngp.X4_GRID and 0.024 in ngp.X4_GRID


def test_smoke_needs_its_own_out_dir(tmp_path):
    assert ngp.main(["run", "--smoke"]) == ngp.EXIT_REFUSED
    assert ngp.main(["run", "--out-dir", str(tmp_path)]) == ngp.EXIT_REFUSED  # freeze 없음
