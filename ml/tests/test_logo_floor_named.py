"""logo_floor_named.py(견고성 점검 R-P0-1 — nameless_floor 를 이름 있는 이미지 질의로 넓히기의 확인
표본·채택 조건) — 엔진 없이 도는 순수 함수와 채택 판정."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from src.model import risk_model as rm

from scripts import logo_floor_named as lf


@pytest.fixture(scope="module")
def model() -> dict:
    return rm.load_model(rm.V141_MODEL_PATH)


def _summary(overall, *, success=None, ms=10.0, model_ms=1.0):
    out = {"전체": overall, "상위": [], "ms": ms, "모델_ms": model_ms}
    if success is not None:
        out["인정"] = [{"id": "1", "순위": 1 if success else 30, "등급": "위험"}]
        out["인정_성공"] = success
    return out


def test_settings_hash_is_stable_and_covers_rules():
    assert lf.rule_sha256() == lf.rule_sha256()
    assert {"변경", "바꾸기_전", "채택_1", "채택_2", "채택_3", "채택_4"} <= set(lf.RULE)


def test_old_scope_is_only_user_figure_with_name_and_image():
    image = object()
    assert lf.old_scope(SimpleNamespace(source="user", type="도형"), "블루", image)
    assert lf.old_scope(SimpleNamespace(source="user", type="결합-도형요부"), "블루", image)
    assert not lf.old_scope(SimpleNamespace(source="user", type="결합-문자요부"), "블루", image)
    assert not lf.old_scope(SimpleNamespace(source="ocr", type="결합-문자요부"), "블루", image)
    assert not lf.old_scope(SimpleNamespace(source="user", type="도형"), None, image)
    assert not lf.old_scope(SimpleNamespace(source="user", type="도형"), "블루", None)


def test_overall_grade_is_the_highest_of_the_first_five():
    assert lf.overall_grade(["주의", "안전", "검토 권장", "안전", "주의", "위험"]) == "검토 권장"
    assert lf.overall_grade([]) is None
    assert lf.grade_index(None) < lf.grade_index("안전")


def test_capped_goods_keeps_the_first_sixty_sorted():
    codes = {f"G{1000 + i}" for i in range(80)}
    capped = lf.capped_goods(codes)
    assert len(capped) == 60 and max(capped) == "G1059"
    assert lf.capped_goods({"S0101"}) == frozenset({"S0101"})


def test_nameless_offline_matches_the_logo_only_engine_judgment(model):
    assert lf.nameless_offline(1.0, None, model) == "위험"  # 같은 로고 0.634
    assert lf.nameless_offline(1.0, 0.0, model) == "검토 권장"  # 업종이 안 겹치면 0.625
    assert lf.nameless_offline(1.0, 1.0, model) == "위험"
    assert lf.nameless_offline(0.2, None, model) == "안전"


def _positives(after: list[bool], alone: list[bool]) -> list[dict]:
    rows = []
    for a, b in zip(after, alone):
        block = {"이름+이미지": {"전": _summary("주의", success=False),
                              "후": _summary("위험", success=a)},
                 "이미지만": {"전": _summary("위험", success=b), "후": _summary("위험", success=b)}}
        rows.append({"출원번호": "1", "방식": {"업종 없음": block, "같은 업종": block}})
    return rows


def test_positive_condition_allows_two_points_below_image_only():
    alone = [True] * 100
    assert lf.check_positive(_positives([True] * 98 + [False] * 2, alone))["통과"]
    assert not lf.check_positive(_positives([True] * 97 + [False] * 3, alone))["통과"]


def _negatives(before: list[str], after: list[str]) -> list[dict]:
    rows = []
    for b, a in zip(before, after):
        named = {"전": _summary(b), "후": _summary(a)}
        alone = {"전": _summary("안전"), "후": _summary("안전")}
        rows.append({"이름": "x", "방식": {"이름+이미지": named, "이미지": alone,
                                          "이름+이미지+업종": named, "이미지+업종": alone}})
    return rows


def test_negative_condition_limits_review_and_danger_increases():
    base = ["주의"] * 100
    five_more_review = ["검토 권장"] * 5 + ["주의"] * 95
    six_more_review = ["검토 권장"] * 6 + ["주의"] * 94
    three_more_danger = ["위험"] * 3 + ["주의"] * 97
    assert lf.check_negative(_negatives(base, five_more_review))["통과"]
    assert not lf.check_negative(_negatives(base, six_more_review))["통과"]
    assert not lf.check_negative(_negatives(base, three_more_danger))["통과"]


def test_never_lower_counts_name_added_queries_below_image_only(model):
    searches = {"양성": _positives([True], [True]), "음성": _negatives(["주의"], ["주의"]),
                "표본A": [{"질의": "A:1:this",
                          "이름+이미지": {"전": _summary("주의"), "후": _summary("주의")},
                          "이미지만": {"전": _summary("검토 권장"), "후": _summary("검토 권장")}}]}
    result = lf.check_never_lower(searches, model)
    assert result["낮아진_경우(후)"] == 1 and not result["통과"]
    assert result["단조_위반"] and not any(result["단조_위반"].values())
    searches["표본A"][0]["이름+이미지"]["후"] = _summary("위험")
    assert lf.check_never_lower(searches, model)["통과"]


def test_distribution_keeps_grade_order():
    assert list(lf.distribution(["위험", "안전", None, "주의"])) == ["안전", "주의", "위험",
                                                                   "후보 없음"]
