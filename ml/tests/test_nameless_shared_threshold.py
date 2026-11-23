"""nameless_shared_threshold.py(R-P0-1 마무리 1단계 — 이름 없는 기준을 대조군·질의 단위·두 집합
공통으로 다시 맞추기) — 엔진 없이 도는 순수 함수와 판정."""

from __future__ import annotations

import pytest
from src.model import risk_model as rm

from scripts import nameless_shared_threshold as ns


@pytest.fixture(scope="module")
def base() -> dict:
    return rm.load_model(rm.V141_MODEL_PATH)


def test_settings_hash_is_stable_and_covers_rules():
    assert ns.rule_sha256() == ns.rule_sha256()
    assert {"대조군", "하한", "채택_1", "채택_2", "채택_3", "채택_4", "채택_5"} <= set(ns.RULE)


def test_set_prob_matches_engine_nameless_sets(base):
    assert round(ns.set_prob(1.0, None, base), 4) == 0.6339  # 같은 로고, 이미지만
    assert round(ns.set_prob(1.0, 1.0, base), 3) == 0.885  # 같은 로고 + 업종 완전 겹침
    assert ns.set_prob(0.3, 1.0, base) > ns.set_prob(0.3, None, base)  # 업종 겹침이 위험도를 올림


def test_shared_thresholds_take_the_larger_fit_and_keep_caution(base):
    fitted = {ns.X: {"검토 권장": 0.40, "위험": 0.41}, ns.XG: {"검토 권장": 0.62, "위험": 0.67}}
    shared = ns.shared_thresholds(base, fitted)
    assert shared[ns.X] == {"주의": 0.3677, "검토 권장": 0.62, "위험": 0.67}
    assert shared[ns.XG] == {"주의": 0.2944, "검토 권장": 0.62, "위험": 0.67}
    assert all(ns.ordered(t) for t in shared.values())
    assert not ns.ordered({"주의": 0.3, "검토 권장": 0.5, "위험": 0.5})


def test_candidate_model_changes_only_the_nameless_review_and_danger(base):
    shared = ns.shared_thresholds(base, {ns.X: {"검토 권장": 0.6, "위험": 0.65},
                                         ns.XG: {"검토 권장": 0.6, "위험": 0.65}})
    new = ns.candidate_model(base, shared, {"rule_sha256": "x" * 64})
    assert new["version"] == ns.NEW_VERSION
    assert new["grade_thresholds"] == base["grade_thresholds"]
    for key in (ns.X, ns.XG):
        assert rm.grade_thresholds_for(new, key) == shared[key]
        short = key[len(rm.NAMELESS_PREFIX):]
        assert new[rm.NAMELESS_KEY][short]["coefficients"] == base[rm.NAMELESS_KEY][short][
            "coefficients"]
    meta = new["meta"]["nameless"]["grade_thresholds"]
    assert rm.search_calibrated(new) and meta["derived_from"] == base["version"]
    assert meta["previous"][ns.X]["검토 권장"] == 0.491


def test_final_grade_applies_goods_floor_and_figure_rule(base):
    assert ns.final_grade(1.0, None, base) == "위험"  # 0.634 ≥ 0.5724
    assert ns.final_grade(1.0, 0.0, base) == "검토 권장"  # 업종이 안 겹치면 0.625(업종 하한 밖)
    assert ns.final_grade(1.0, 0.03, base) == "위험"  # 겹침 ≥ 0.0252 → 이미지만 등급 유지
    assert ns.final_grade(0.95, None, base, goods_floor=False) == "위험"


def test_cluster_bootstrap_is_reproducible_and_bounded():
    groups = {f"q{i}": [i / 10] for i in range(10)}
    first = ns.cluster_bootstrap(groups, lambda v: max(v), rounds=200)
    assert first == ns.cluster_bootstrap(groups, lambda v: max(v), rounds=200)
    assert 0.0 <= first[0] <= first[1] <= 0.9
    assert ns.cluster_bootstrap({}, max) is None


def test_check_1_uses_tolerance_on_the_confirmation_refit():
    thresholds = {key: {"주의": 0.3, "검토 권장": 0.5, "위험": 0.6} for key, _, _ in ns.SETS}
    within = {key: {"기준용": [], "확인용": [0.1] * 90 + [0.51] * 10} for key, _, _ in ns.SETS}
    groups = {key: {"기준용": {}, "확인용": {"a": [0.1]}} for key, _, _ in ns.SETS}
    assert ns.check_1(within, groups, thresholds)["통과"]  # 10% — 목표 그대로
    near = {key: {"기준용": [], "확인용": [0.1] * 89 + [0.51] * 11} for key, _, _ in ns.SETS}
    assert ns.check_1(near, groups, thresholds)["통과"]  # 11% — 다시 맞춘 값 0.5101, 차이 0.0101
    far = {key: {"기준용": [], "확인용": [0.1] * 80 + [0.7] * 20} for key, _, _ in ns.SETS}
    assert not ns.check_1(far, groups, thresholds)["통과"]  # 다시 맞춘 값 0.7001 − 0.5 > 0.0224


def test_grid_has_no_drop_when_goods_are_added_on_the_shipped_model(base):
    assert ns.grid_violations(base, goods_floor=True, step=0.05) == 0


def test_distribution_and_overall():
    assert ns.overall(["주의", "검토 권장", "안전", "주의", "안전", "위험"]) == "검토 권장"
    assert list(ns.distribution(["위험", None, "안전"])) == ["안전", "위험", "후보 없음"]
