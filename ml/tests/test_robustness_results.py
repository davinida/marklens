"""견고성 점검(2026-11-23, docs/MarkLens_견고성_보안_점검.md) — 오류는 아니지만 결과가 이상한 입력의
회귀 시험. 실제 식별력 모델(shared/distinctiveness)과 배포 계수 JSON 으로 쌍 하나를 채점한다
(CLIP·X3 없이 — 관념 축은 결측으로 둔다). 지금 고쳐지지 않은 항목은 strict xfail, 사유에 점검 문서의
항목 번호.
"""

from __future__ import annotations

import pytest
from src.axes import pair_axes as pa
from src.axes.distinctiveness import Distinctiveness, load_distinctiveness
from src.model import risk_model as rm

CAFE = ["G0301", "G0502", "S120602"]  # 업종 세트 카페(커피전문점업·커피·커피 소매업)
# 4020170150241 "맛있는 만두 전문점 장수손만두 1976" 의 유사군(DB 메타 그대로)
DUMPLING_GOODS = ["G020102", "G0206", "G0301", "G0502", "S120602", "S120603"]
INVISIBLE = {
    "U+200B 폭 없는 공백": "​",
    "U+200C 폭 없는 비결합자": "‌",
    "U+200D 폭 없는 결합자": "‍",
    "U+2060 낱말 결합자": "⁠",
    "U+FEFF BOM": "﻿",
    "U+00AD 부드러운 붙임표": "­",
}


@pytest.fixture(scope="module")
def dist() -> Distinctiveness:
    return load_distinctiveness()


def _score(dist: Distinctiveness, query: str, candidate: str, goods_a=None, goods_b=None):
    axes = pa.compute_pair_axes(query, candidate, model=dist, goods_a=goods_a, goods_b=goods_b,
                                x3_enabled=False)
    return axes, rm.risk_score(axes.model_features(x2_img=None, mark_type="문자"), rm.load_model())


@pytest.mark.xfail(strict=True, reason="R-P0-2: 설명적 낱말만으로 된 이름이 같은 순서의 약한 "
                                       "낱말 둘(맛있는…전문점)을 요부로 보아 호칭 1.0·'위험'")
def test_descriptive_only_name_is_not_rated_danger(dist):
    axes, result = _score(dist, "맛있는 커피 전문점", "맛있는 만두 전문점 장수손만두 1976",
                          CAFE, DUMPLING_GOODS)
    assert axes.query_tokens == ()  # 전제: 질의에 요부가 없다(낱말이 모두 약함)
    assert result.grade in ("안전", "주의"), (axes.x1_raw, result.prob)


def test_descriptive_only_name_with_one_shared_weak_word_stays_low(dist):
    """가드 — 약한 낱말 하나만 겹치면(맛있는 커피) 지금도 호칭이 낮다."""
    axes, result = _score(dist, "맛있는 커피", "맛있는 만두 전문점 장수손만두 1976",
                          CAFE, DUMPLING_GOODS)
    assert axes.x1_raw < 0.5 and result.grade in ("안전", "주의")


@pytest.mark.xfail(strict=True, reason="R-P1-6: 이름 속 보이지 않는 서식 문자(U+200B 등)가 토큰을 "
                                       "갈라 축 점수·등급이 바뀜")
def test_invisible_format_characters_do_not_change_the_judgment(dist):
    plain_axes, plain = _score(dist, "블루커피", "BLU hands")
    differ = {}
    for label, char in INVISIBLE.items():
        axes, result = _score(dist, f"블{char}루커피", "BLU hands")
        seen = (round(axes.x1_raw, 4), round(axes.x2_text_raw, 4), axes.query_tokens, result.grade)
        want = (round(plain_axes.x1_raw, 4), round(plain_axes.x2_text_raw, 4),
                plain_axes.query_tokens, plain.grade)
        if seen != want:
            differ[label] = seen
    assert not differ, differ


def test_case_width_and_spacing_variants_give_the_same_judgment(dist):
    """가드 — 대소문자·전각·앞뒤 공백·NFD 는 지금도 같은 판단(점검 2 의 같아야 하는 입력)."""
    import unicodedata

    base_axes, base = _score(dist, "STARBUCKS", "STARBUCKS COFFEE")
    for variant in ("starbucks", "ＳＴＡＲＢＵＣＫＳ", "  STARBUCKS  ",
                    unicodedata.normalize("NFD", "STARBUCKS")):
        axes, result = _score(dist, variant, "STARBUCKS COFFEE")
        assert (round(axes.x1_raw, 4), axes.query_tokens, result.grade) == (
            round(base_axes.x1_raw, 4), base_axes.query_tokens, base.grade)
    hangul = _score(dist, "블루커피", "BLU hands")[1].grade
    assert _score(dist, unicodedata.normalize("NFD", "블루커피"), "BLU hands")[1].grade == hangul
