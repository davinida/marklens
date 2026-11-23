"""goods_shortcut.py(이름 없는 '이미지+업종' 판단의 업종 지름길 — 같은 업종 음성으로 다시 학습)의
순수 함수·채택 판정."""

from __future__ import annotations

import pytest
from src.model import risk_model as rm

from scripts import goods_shortcut as gs
from scripts import named_search_thresholds as first


@pytest.fixture(scope="module")
def base() -> dict:
    return rm.load_model(gs.BASE_MODEL_PATH)


def test_settings_hash_is_stable_and_covers_rules():
    assert gs.rule_sha256() == gs.rule_sha256()
    assert {"같은_업종_음성", "음성_행", "다시_학습", "학습_진단", "기준", "채택_1", "채택_2",
            "채택_3", "채택_4", "채택_5", "전후", "적용"} <= set(gs.RULE)


def test_normalize_number_uses_the_registration_form_for_short_numbers():
    assert gs.normalize_number("666832") == "4006668320000"
    assert gs.normalize_number("40-2012-0060023") == "4020120060023"
    assert gs.normalize_number("") == "" and gs.normalize_number(None) == ""


def test_trial_related_pairs_joins_this_and_counter_marks():
    numbers = {"4000073530000": "A1", "4019620001630": "A1", "4006668320000": "B2",
               "4020120060023": "C3"}
    labels = [{"심판번호": "t1", "상표A_번호": "7353", "상표B_번호": "666832"},
              {"심판번호": "t2", "상표A_번호": "", "상대표장_번호_후보": "1;666832"},
              {"심판번호": "t3", "상표A_번호": "999", "상표B_번호": "888"}]
    trial_list = {"t2": {"출원번호": "4020120060023", "등록번호": ""}}
    pairs, report = gs.trial_related_pairs(labels, trial_list, numbers)
    assert pairs == {("A1", "B2"), ("B2", "C3")}
    assert report == {"이_사건_표장_DB": 2, "상대_표장_DB": 1, "관계_쌍": 2}


def test_bottom_half_and_sampling_are_deterministic():
    scored = [(0.9, "a", "b"), (0.1, "c", "d"), (0.1, "a", "c"), (0.5, "b", "d")]
    pool = gs.bottom_share(scored)
    assert pool == [(0.1, "a", "c"), (0.1, "c", "d")]
    picked = gs.sample_pairs(pool, 1)
    assert picked == gs.sample_pairs(pool, 1) and picked[0] in pool
    with pytest.raises(ValueError):
        gs.sample_pairs(pool, 3)


def test_thresholds_keep_caution_unless_review_falls_below_it():
    values = [i / 100 for i in range(100)]  # 0.00–0.99
    fitted = gs.fit_goods_thresholds(values, 0.2944)
    # fit_cut: (k+1)번째로 큰 값보다 큰 가장 작은 넷째 자리 값(k = ⌊목표·n⌋) — 0.89 → 0.8901
    assert fitted["기준"] == {"주의": 0.2944, "검토 권장": 0.8901, "위험": 0.9701}
    assert not fitted["주의_다시_맞춤"]
    low = [v * 0.3 for v in values]  # 검토 권장이 0.2944 아래로
    fitted = gs.fit_goods_thresholds(low, 0.2944)
    assert fitted["주의_다시_맞춤"] and fitted["기준"]["검토 권장"] <= 0.2944
    assert fitted["기준"]["주의"] == first.fit_cut(low, 0.5)[0] < fitted["기준"]["검토 권장"]


def test_goods_block_changes_only_the_image_goods_set(base):
    entry = {"coefficients": {"x2_whole": 3.0, "x2_whole×도형계": 0.3, "x4": 0.5},
             "intercept": -2.5}
    new = gs.goods_block(base, entry, {"주의": 0.3, "검토 권장": 0.6, "위험": 0.7}, {"n": 1})
    block = new[rm.NAMELESS_KEY][gs.XG_KEY]
    assert block["coefficients"] == entry["coefficients"] and block["intercept"] == -2.5
    assert block["grade_thresholds"] == {"주의": 0.3, "검토 권장": 0.6, "위험": 0.7}
    assert new[rm.NAMELESS_KEY][gs.X_KEY] == base[rm.NAMELESS_KEY][gs.X_KEY]
    assert {k: v for k, v in new.items() if k != rm.NAMELESS_KEY} == {
        k: v for k, v in base.items() if k != rm.NAMELESS_KEY}


def test_repair_raises_only_the_goods_intercept_for_axis_coupling(base):
    block = base[rm.NAMELESS_KEY][gs.XG_KEY]
    fixed, report = gs.repair_coupling(base)
    assert report == {"걸음": {}, "고침": True, "남은_위반": []} and fixed == base
    low = gs.goods_block(base, {"coefficients": block["coefficients"],
                                "intercept": round(block["intercept"] - 0.0002, 4)})
    assert rm.coupling_violations(low)
    fixed, report = gs.repair_coupling(low)
    assert report["고침"] and report["걸음"] == {"올림": 2}
    assert fixed[rm.NAMELESS_KEY][gs.XG_KEY]["intercept"] == block["intercept"]
    assert fixed[rm.NAMELESS_KEY][gs.X_KEY] == base[rm.NAMELESS_KEY][gs.X_KEY]
    assert rm.coupling_violations(fixed) == []


def test_precision_needs_ten_risk_rows_to_judge():
    few = gs.precision_check(["위험"] * 9 + ["주의"], [0] * 10)
    assert few["통과"] and not few["판정에_씀"] and few["정밀도"] == 0.0
    enough = gs.precision_check(["위험"] * 10, [1] * 7 + [0] * 3)
    assert enough["판정에_씀"] and enough["정밀도"] == 0.7 and enough["통과"]
    assert not gs.precision_check(["위험"] * 10, [1] * 6 + [0] * 4)["통과"]


def _named(before: list[str], after: list[str]) -> list[dict]:
    return [{"방식": {gs.NAMED_GOODS_MODE: {"지금": {"전체": b}, "새": {"전체": a}}}}
            for b, a in zip(before, after)]


def test_named_control_condition_allows_no_increase():
    assert gs.check_named(_named(["검토 권장", "주의"], ["주의", "주의"]))["통과"]
    assert not gs.check_named(_named(["주의", "주의"], ["검토 권장", "주의"]))["통과"]
    assert gs.check_named(_named(["위험", None], ["검토 권장", None]))["통과"]


def test_industry_gap_compares_same_and_different_industry(base):
    pool = [{"x2": 0.2, "x4": 1.0, "무관": True}, {"x2": 0.2, "x4": 0.0, "무관": True},
            {"x2": 0.2, "x4": 0.01, "무관": False}]
    queries = [{"검색": [{"방식": "이미지+업종", "풀": pool}]}]
    gap = gs.industry_gap(queries, {"지금": base})["지금"]["전체"]
    assert gap["같은 업종"]["n"] == 1 and gap["다른 업종"]["n"] == 1
    assert gap["평균_차(같은 − 다른)"] > 0  # 지금 계수는 업종 겹침만으로 위험도를 올린다
