"""엔진 기여도 묶음 — 이름 없는 이미지+업종 집합의 곱하기 항(통합 모델 설계 §7-12)은 업종 겹침이
더한 몫이라 X4 로 묶는다(절편 + 기여도 합 + 결측 보정 = 로짓, 계약 v2 §2-2)."""

from __future__ import annotations

import pytest

from backend.src.core import multi_search as ms


def test_product_terms_group_into_the_goods_contribution():
    grouped, missing = ms._group_contributions({
        "intercept": -2.0, "x2_whole": 1.0, "x2_whole×도형계": 0.25, "x4": 0.1,
        "x2_whole×x4": 0.3, "hinge(x2_whole;0.6419;0.5579)×x4": 0.2,
        "hinge(x2_whole;0.6419;0.5579)×도형계×x4": 0.05, "miss_pattern": -0.4})
    assert grouped["X2"] == pytest.approx(1.25)
    assert grouped["X4"] == pytest.approx(0.65)
    assert missing == pytest.approx(-0.4)
