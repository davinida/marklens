"""weak_run_adjacent.py(견고성 점검 R-P0-2 — 식별력 결합 규칙의 약한 토큰열을 붙어 있는 구간만)의
순수 함수·채택 판정·설명적 이름 생성."""

from __future__ import annotations

import json

import pytest
from src.axes import distinctiveness as dx
from src.axes.goods_map import GoodsEntry, GoodsMap
from src.model import risk_model as rm

from scripts import weak_run_adjacent as wr


@pytest.fixture(scope="module")
def base() -> dict:
    return rm.load_model(wr.BASE_MODEL_PATH)


def _toy_model() -> dx.Distinctiveness:
    names, classes = dx.goods_index(GoodsMap([GoodsEntry("커피", 30, ("G0301",))]))
    stats = {"zorbix": (0, 0), "qwzy": (5, 10),
             **{token: (20, 40) for token in ("cool", "touch", "fresh")}}
    return dx.Distinctiveness(stats, famous=set(), goods_names=names, code_classes=classes,
                              descriptive={})


def test_settings_hash_is_stable_and_covers_rules():
    assert wr.rule_sha256() == wr.rule_sha256()
    assert {"변경", "학습_특징", "채택_AUC", "채택_1", "연속_구간", "대조군", "표본A_인용상표",
            "심결_쌍"} <= set(wr.RULE)


def test_candidate_only_adds_the_version_and_the_weak_run_rule(base):
    new = wr.candidate_model(base)
    assert new["version"] == "risk_model_v1.4.3" and rm.weak_run_version(new) == 2
    assert rm.weak_run_version(base) == 1
    for key in ("intercept", "coefficients", "grade_thresholds", "patterns", rm.NAMELESS_KEY,
                "standalone_thresholds", "figure_rule", "coupling", rm.LOGO_FLOOR_KEY):
        assert new.get(key) == base.get(key), key


def test_auc_counts_ties_as_half_and_uses_weights():
    assert wr.auc([0.9, 0.8, 0.1], [1, 1, 0]) == 1.0
    assert wr.auc([0.5, 0.5], [1, 0]) == 0.5
    assert wr.auc([0.9, 0.2, 0.5], [1, 1, 0], [1.0, 3.0, 1.0]) == pytest.approx(0.25)


def test_contiguous_and_pair_classification():
    assert wr.contiguous_in(("cool", "touch"), ["qwzy", "cool", "touch"])
    assert not wr.contiguous_in(("cool", "touch"), ["cool", "zorbix", "touch"])
    model = _toy_model()
    kept = wr.classify_pair(model, "Cool Touch Zorbix", "Qwzy Cool Touch", None)
    assert kept["붙어_있음"] and kept["계속_걸림"] and kept["규칙2"] == ["cool", "touch"]
    gone = wr.classify_pair(model, "Cool Zorbix Touch", "Cool Touch Qwzy", None)
    assert not gone["붙어_있음"] and gone["규칙2"] == []
    assert wr.classify_pair(model, "Zorbix", "Qwzy", None) is None


def test_preservation_passes_only_when_every_adjacent_pair_still_fires():
    adjacent = {"판정": {"붙어_있음": True, "계속_걸림": True, "규칙1": ["a", "b"],
                       "규칙2": ["a", "b"], "규칙1에_없던_토큰": []}}
    separated = {"판정": {"붙어_있음": False, "계속_걸림": False, "규칙1": ["a", "c"],
                        "규칙2": [], "규칙1에_없던_토큰": []}}
    result = wr.check_preservation([adjacent, separated, {"판정": None}])
    assert result["통과"] and result["붙어_있음"]["쌍"] == 1
    assert result["떨어짐"]["규칙2_빈_결과"] == 1
    lost = {"판정": {**adjacent["판정"], "계속_걸림": False}}
    assert not wr.check_preservation([lost])["통과"]


def _control(before: list[str], after: list[str]) -> list[dict]:
    rows = []
    for b, a in zip(before, after):
        block = {"전": {"전체": b}, "후": {"전체": a}}
        rows.append({"이름": "x", "방식": {label: block for label, _, _ in wr.CONTROL_MODES}})
    return rows


def test_control_condition_allows_no_increase():
    assert wr.check_control(_control(["검토 권장", "주의"], ["주의", "주의"]))["통과"]
    assert not wr.check_control(_control(["주의", "주의"], ["검토 권장", "주의"]))["통과"]
    assert not wr.check_control(_control(["검토 권장", "주의"], ["위험", "주의"]))["통과"]


def test_grade_change_condition_needs_five_rows_to_judge():
    rows = [{"최종라벨": "비유사"}] * 4 + [{"최종라벨": "유사"}] * 6
    before = ["주의"] * 10
    after = ["위험"] * 4 + ["주의"] * 6  # 새 위험 4행(모두 비유사) — 5행 미만이라 목록만
    result = wr.check_grade_changes(rows, before, after)
    assert result["통과"] and not result["새로_위험"]["판정에_씀"]
    after = ["위험"] * 5 + ["주의"] * 5  # 5행, 유사 1/5 = 0.2 < 0.70
    assert not wr.check_grade_changes(rows, before, after)["통과"]
    before = ["위험"] * 10
    after = ["위험"] * 4 + ["주의"] * 6  # 빠진 6행 모두 유사 → 1.0 > 0.5
    assert not wr.check_grade_changes(rows, before, after)["통과"]


def test_descriptive_names_are_deterministic_weak_and_include_an_industry_word():
    from src.axes import goods_map as gm

    dist = dx.load_distinctiveness(with_goods=True)
    presets = {preset.id: tuple(sorted({code for good in preset.goods
                                        for code in good.similarity_codes}))
               for preset in gm.load_business_presets(gm.load_goods_map()).presets}
    weak_rows = json.loads(wr.WEAK_TOKENS.read_text(encoding="utf-8"))["tokens"]
    preset_rows = json.loads(wr.PRESETS.read_text(encoding="utf-8"))
    names = wr.descriptive_names(dist, presets, weak_rows, preset_rows)
    assert names == wr.descriptive_names(dist, presets, weak_rows, preset_rows)
    assert len(names) == 200 and len({item["이름"] for item in names}) == 200
    assert sum(item["문자"] == "한글" for item in names) == 100
    for item in names:
        words = item["이름"].split(" ")
        assert 2 <= len(words) <= 4 and item["업종어"].lower() in [w.lower() for w in words]
        assert all(j.score < dist.theta for j in dist.judge_name(item["이름"]))
