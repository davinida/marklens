"""X2 문자 외관(철자) 축 테스트 — 불변식, 판례 예시 쌍, X1 과의 차이, x2_split 구현과의 회귀."""

from __future__ import annotations

import pytest
from src.axes import x2_ortho as xo
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


# ---- 철자 v2(2026-11-20): 요부 토큰 덮개 점수 + 이어 붙인 문자열 ------------------------------


V2_SINGLE_TOKEN = [  # 양쪽 토큰이 하나씩 — v2 는 v1 과 같아야 한다
    ("XSR", "XSL"), ("스타벅스", "스타박스"), ("나이키", "NIKE"), ("UNDEFEATED", "UNDFTD"),
    ("커피빈", "커피빈"), ("GATE", "GATE"), ("A", "AB"), ("가", "각"), ("ZORBIX", "ZORBIK"),
]


@pytest.mark.parametrize(("a", "b"), V2_SINGLE_TOKEN)
def test_v2_equals_v1_when_both_names_have_one_token(a, b):
    assert len(xo.spelling_tokens(a)) == len(xo.spelling_tokens(b)) == 1
    assert xo.orthographic_similarity(a, b, version=2) == pytest.approx(
        xo.orthographic_similarity(a, b), abs=1e-12)


def test_v2_single_token_invariant_holds_after_generic_removal():
    """식별력 필터가 약한 토큰을 빼고 남은 요부 토큰이 하나씩이면 v1 과 같다."""
    generic = frozenset({"커피"})
    for a, b in (("블루 커피", "블루베리 커피"), ("BLUE COFFEE", "RED COFFEE"),
                 ("스타벅스 커피", "스타박스")):
        assert len(xo.spelling_tokens(a, extra_generic=generic)) == 1
        assert len(xo.spelling_tokens(b, extra_generic=generic)) == 1
        assert xo.orthographic_similarity(a, b, extra_generic=generic, version=2) == pytest.approx(
            xo.orthographic_similarity(a, b, extra_generic=generic), abs=1e-12)


def test_v2_fixes_one_shared_token_among_several():
    """v1 은 요부 토큰이 여러 개일 때 공통 토큰 하나만 같아도 1.0 — v2 는 짝이 없거나 다른 토큰만큼
    내려간다(덮개 점수)."""
    for a, b in (("GATE HELLO", "GATE WORLD"), ("BLUE BOTTLE", "BLUE HANDS"),
                 ("GATE", "GATE HELLO"), ("닥치고 떡볶이", "떡볶이 명가")):
        assert xo.orthographic_similarity(a, b) == 1.0
        assert xo.orthographic_similarity(a, b, version=2) < 0.8
    # 덮개 점수 손계산: GATE / GATE HELLO — A 쪽 4/4 = 1, B 쪽 (4·1 + 5·0)/9, 평균 0.7222;
    # 이어 붙인 문자열 gate / gatehello = 1 − 5/9 = 0.4444 → max 0.7222
    assert xo.orthographic_similarity("GATE", "GATE HELLO", version=2) == pytest.approx(
        (1 + 4 / 9) / 2)
    # 같은 토큰을 순서만 바꾸면 1.0, 띄어쓰기만 다르면 이어 붙인 문자열로 1.0
    assert xo.orthographic_similarity("BLUE BOTTLE", "BOTTLE BLUE", version=2) == 1.0
    assert xo.orthographic_similarity("커피빈", "커피 빈", version=2) == 1.0
    assert xo.orthographic_similarity("ROYALE BEE", "ROYALEBEE", version=2) == 1.0


def test_v2_matching_is_one_to_one_and_weighted_by_key_length():
    # A 의 같은 토큰 둘이 B 의 토큰 하나를 함께 쓰지 못한다(일대일; 붙어 있는 같은 토큰은
    # normalize_name 이 하나로 합치므로 떨어뜨려 둔다): A 쪽 4/6, B 쪽 1 → 0.8333
    assert xo.spelling_tokens("ab cd ab") == ["ab", "cd", "ab"]
    assert xo.orthographic_similarity("ab cd ab", "ab cd", version=2) == pytest.approx(
        max((4 / 6 + 1) / 2, xo._similarity("abcdab", "abcd")))
    # 글자 수 가중: 긴 토큰이 맞으면 짧은 토큰이 맞을 때보다 높다
    long_match = xo.orthographic_similarity("abcdef xy", "abcdef zw", version=2)
    short_match = xo.orthographic_similarity("abcdef xy", "uvwxyz xy", version=2)
    assert long_match > short_match
    # 한글 글자 수는 자모 키 길이(유사도와 같은 단위)
    assert xo.spelling_tokens("블루 보틀") == ["ㅂㅡㄹㄹㅜ", "ㅂㅗㅌㅡㄹ"]
    # 짝 유사도 합이 같으면 덮개 점수가 큰 짝(가중 1e-9 의 동점 깨기) — 결정적·대칭
    a, b = "ab cd", "ab cd ab"
    assert xo.orthographic_similarity(a, b, version=2) == xo.orthographic_similarity(
        b, a, version=2)


@pytest.mark.parametrize(("a", "b"), [
    ("GATE HELLO", "GATE WORLD"), ("블루 보틀", "블루 핸즈 커피"), ("A B C D E", "E D C B A"),
    ("THE BEST COFFEE IN TOWN", "BEST TOWN COFFEE"), ("ab cd", "cd ab ef"), ("x", "x y z w"),
    ("가나 다라", "다라 가나 마바"), ("STAR★BUCKS", "STAR BUCKS"), ("", "GATE"), ("★", "★"),
])
def test_v2_contract_symmetric_bounded_deterministic(a, b):
    first = xo.orthographic_similarity(a, b, version=2)
    assert first == xo.orthographic_similarity(b, a, version=2)  # 대칭(정준형 계산)
    assert first == xo.orthographic_similarity(a, b, version=2)  # 결정적
    assert 0.0 <= first <= 1.0
    if not xo.has_spelling(a) or not xo.has_spelling(b):
        assert first == 0.0
    elif a.strip():
        assert xo.orthographic_similarity(a, a, version=2) == 1.0


def test_v2_handles_many_tokens_without_cap():
    """v1 은 4토큰 이상이면 전체 문자열만 — v2 는 토큰 수 상한 없이 덮개 점수를 쓴다(짝 없는 토큰이
    점수를 내리므로 한 토큰이 전체를 대신하지 않는다)."""
    many = " ".join(f"tok{chr(97 + i)}{chr(97 + i)}" for i in range(12))
    assert len(xo.spelling_tokens(many)) == 12
    assert xo.orthographic_similarity(many, many, version=2) == 1.0
    half = " ".join(many.split()[:6])
    value = xo.orthographic_similarity(many, half, version=2)
    assert 0.6 < value < 0.8  # A 쪽 6/12·B 쪽 1 → 0.75
    assert value == pytest.approx(0.75)


def test_version_argument_default_and_validation():
    assert xo.DEFAULT_SPELLING_VERSION == 1 and xo.SPELLING_VERSIONS == (1, 2)
    assert xo.orthographic_similarity("GATE HELLO", "GATE WORLD") == 1.0  # 기본은 v1 그대로
    assert xo.orthographic_similarity("GATE HELLO", "GATE WORLD", version=1) == 1.0
    with pytest.raises(ValueError, match="철자 버전"):
        xo.orthographic_similarity("a", "b", version=3)
    from src.model import risk_model as rm

    assert rm.SUPPORTED_SPELLING_VERSIONS == xo.SPELLING_VERSIONS  # 런타임 검사와 같은 목록
