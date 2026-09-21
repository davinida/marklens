"""X4 상품 견련성 축 — 자카드 계수 규약 테스트."""

import pytest
from src.axes.x4_goods import goods_similarity, has_goods

COSMETICS = {"G1201", "S120907", "S128302"}


def test_identical_sets_are_one():
    assert goods_similarity(COSMETICS, set(COSMETICS)) == 1.0


def test_disjoint_sets_are_zero():
    assert goods_similarity(COSMETICS, {"G4502", "G4503"}) == 0.0


def test_partial_overlap_is_intersection_over_union():
    # 교집합 {G1201, S120907} = 2, 합집합 4 → 0.5
    assert goods_similarity(COSMETICS, {"G1201", "S120907", "G1202"}) == 0.5


@pytest.mark.parametrize("empty", [set(), frozenset(), [], (), None, "", "  "])
def test_empty_side_is_zero(empty):
    assert goods_similarity(COSMETICS, empty) == 0.0
    assert goods_similarity(empty, COSMETICS) == 0.0
    assert goods_similarity(empty, empty) == 0.0


def test_symmetric():
    a, b = COSMETICS, {"G1201", "G4502"}
    assert goods_similarity(a, b) == goods_similarity(b, a)


def test_accepts_lists_tuples_and_single_code_string():
    assert goods_similarity(list(COSMETICS), tuple(COSMETICS)) == 1.0
    assert goods_similarity("G1201", ["G1201"]) == 1.0


def test_codes_are_normalized_and_junk_ignored():
    assert goods_similarity({" g1201 ", "", None, 42}, {"G1201"}) == 1.0  # type: ignore[arg-type]


def test_has_goods_distinguishes_empty_from_present():
    assert has_goods(COSMETICS) is True
    assert has_goods(["G1201"]) is True
    assert has_goods(set()) is False
    assert has_goods(None) is False
    assert has_goods(["", "  "]) is False


def test_result_is_within_unit_interval():
    for a, b in [(COSMETICS, {"G1201"}), ({"A1"}, {"B2", "C3", "A1"}), ({"X1"}, {"X1"})]:
        assert 0.0 <= goods_similarity(a, b) <= 1.0
