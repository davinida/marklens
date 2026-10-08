"""X2 문자 외관(철자) 축 테스트 — 불변식, 판례 예시 쌍, X1 과의 차이, x2_split 구현과의 회귀."""

from __future__ import annotations

import pytest
from src.axes.x1_phonetic import phonetic_similarity
from src.axes.x2_ortho import (
    decompose_jamo,
    has_spelling,
    orthographic_similarity,
    spelling_candidates,
)

from scripts import x2_split

NAMES = ["스타벅스", "STARBUCKS", "커피 빈", "XSR", "나이키", "(주)스타벅스 코리아", "", "★", "美"]


@pytest.mark.parametrize("name", [n for n in NAMES if has_spelling(n)])
def test_self_is_one(name):
    assert orthographic_similarity(name, name) == 1.0


@pytest.mark.parametrize("a,b", [(a, b) for a in NAMES for b in NAMES])
def test_symmetric_and_in_range(a, b):
    score = orthographic_similarity(a, b)
    assert 0.0 <= score <= 1.0
    assert score == orthographic_similarity(b, a)


def test_no_exception_on_odd_inputs():
    for value in (None, 123, "   ", "​", "🙂", "ㅋㅋ"):
        assert 0.0 <= orthographic_similarity(value, "스타벅스") <= 1.0  # type: ignore[arg-type]


def test_xsr_xsl_spelling_close_but_pronunciation_differs():
    assert orthographic_similarity("XSR", "XSL") >= 0.6
    assert orthographic_similarity("XSR", "XSL") == pytest.approx(2 / 3)
    # X1 은 음절 편집거리로 0.93 — 같은 쌍을 다른 근거로 잰다(값 자체는 X1 테스트의 몫)
    assert phonetic_similarity("XSR", "XSL") != orthographic_similarity("XSR", "XSL")


def test_starbucks_typo_pair_is_close():
    assert orthographic_similarity("스타벅스", "스타박스") >= 0.8


def test_nike_korean_vs_latin_differs_in_spelling_but_same_pronunciation():
    assert orthographic_similarity("나이키", "NIKE") <= 0.3
    assert phonetic_similarity("나이키", "NIKE") >= 0.8  # 호칭은 같은 쪽으로 읽힌다(0.91)


def test_starbucks_korean_vs_latin_differs():
    assert orthographic_similarity("스타벅스", "STARBUCKS") <= 0.3


def test_spacing_is_ignored():
    assert orthographic_similarity("커피 빈", "커피빈") == 1.0
    assert orthographic_similarity("Coffee Bean", "COFFEEBEAN") == 1.0


def test_extra_generic_removes_shared_generic_token():
    without = orthographic_similarity("BLUE COFFEE", "RED COFFEE")
    with_generic = orthographic_similarity(
        "BLUE COFFEE", "RED COFFEE", extra_generic=frozenset({"커피"})
    )
    assert without == 1.0  # 공통 토큰 COFFEE 의 분리관찰
    assert with_generic <= 0.3


def test_company_marks_and_symbols_are_removed():
    assert orthographic_similarity("(주)스타벅스 코리아", "스타벅스") == 1.0
    assert orthographic_similarity("스타벅스®", "스타벅스") == 1.0


def test_coined_word_has_spelling_but_symbols_do_not():
    assert has_spelling("XSR") and has_spelling("Zyqrt") and has_spelling("777")
    assert not has_spelling("★") and not has_spelling("") and not has_spelling("美")
    assert not has_spelling("(주)")  # 회사 표시만
    assert orthographic_similarity("★", "★") == 0.0  # 후보 없음 → 비교 불가


def test_candidates_whole_plus_tokens_up_to_three():
    assert spelling_candidates("Blue Coffee") == ["bluecoffee", "blue", "coffee"]
    # 4토큰 이상(슬로건형)은 전체 문자열만(a·of 같은 기능어는 정규화에서 빠지므로 세지 않는다)
    assert spelling_candidates("Blue Red Green Coffee") == ["blueredgreencoffee"]
    assert spelling_candidates("A Cup Of Coffee Dream") == [
        "cupcoffeedream", "cup", "coffee", "dream"
    ]
    # 1글자 토큰은 후보에서 뺀다
    assert spelling_candidates("K 카페") == [decompose_jamo("k카페"), decompose_jamo("카페")]


def test_decompose_jamo_matches_syllable_structure():
    assert decompose_jamo("강") == "ㄱㅏㅇ" and decompose_jamo("가") == "ㄱㅏ"
    assert decompose_jamo("ab1") == "ab1"


@pytest.mark.parametrize("a,b", [
    ("스타벅스", "스타박스"), ("XSR", "XSL"), ("나이키", "NIKE"), ("스타벅스", "STARBUCKS"),
    ("커피빈", "커피 빈"), ("봉구스웨어", "봉구데집"), ("UNDEFEATED", "UNDFTD"), ("Hue", "HUE"),
    ("SPINNER", "SPINOS"), ("GATE", "Gate"),
])
def test_regression_against_x2_split_ortho_similarity(a, b):
    """같은 입력에서 x2_split 의 OCR 철자 유사도(전체 문자열만, 4자리 반올림)와 같은 값.
    토큰 후보는 전체 문자열 쌍을 넘지 못하는 입력으로 고정했다."""
    expected = x2_split.ortho_similarity(a, b)
    assert expected is not None
    assert orthographic_similarity(a, b) == pytest.approx(expected, abs=5e-5)


def test_token_candidates_only_raise_the_score():
    """토큰 후보는 전체 문자열 점수의 상한을 올릴 뿐 내리지 않는다."""
    whole = x2_split.ortho_similarity("닥치고 떡볶이", "떡볶이 명가")
    assert whole is not None and whole < 1.0
    assert orthographic_similarity("닥치고 떡볶이", "떡볶이 명가") == 1.0
