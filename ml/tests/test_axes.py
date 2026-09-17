"""X1 호칭 유사도 축 테스트 — A. 불변식, B. 판례 기반 명확 케이스.

실행: OMP_NUM_THREADS=1 MARKLENS_FAKE_ML=1 ml/venv/bin/python -m pytest ml/tests/test_axes.py -q
C(보고 전용 점수표)는 assert 하지 않고 ml/scripts/x1_report.py 가 출력한다.
"""

import importlib.util
import time
from pathlib import Path

import pytest
from src.axes.x1_phonetic import (
    has_pronunciation,
    phonetic_similarity,
    pronunciation_candidates,
)

# --------------------------------------------------------------------------- A. 불변식

SELF_NAMES = [
    "스타벅스",
    "삼성전자",
    "카페 ABC",
    "MONTEROSA",
    "7 STAR",
    "블루보틀 커피",
    "(주)한입 간장게장",
    "H motors SINCE 1994",
]

SYMMETRY_PAIRS = [
    ("스타벅스", "스타박스"),
    ("스타벅스", "커피빈"),
    ("삼성 SAMSUNG", "삼성"),
    ("몬테로사", "MONTEROSA"),
    ("나이키", "마이키"),
    ("리쥬", "리주"),
    ("태백투어패스", "화천투어패스"),
    ("카페 ABC", "에이비씨"),
    ("ATX", "에이티엑스"),
    ("랑콤", "랑콤 파리"),
    ("커피 빈", "커피빈"),
    ("7 STAR", "세븐스타"),
    ("3M", "쓰리엠"),
    ("NORTH FACE", "노스페이스"),
    ("코카콜라", "코카-콜라"),
    ("애플", "APPLE"),
    ("애플", "사과"),
    ("KR", "케이알"),
    ("서울바쿠테", "바쿠테"),
    ("잇버거 EAT PREMIUM BURGER", "잇버거"),
]

WEIRD_INPUTS = [
    "",
    "   ",
    "東洋",
    "🚀",
    "12345",
    "ABC",
    "a",
    "가나다라마" * 400,
    "®™©!!!...---",
]


@pytest.mark.parametrize("name", SELF_NAMES)
def test_self_similarity_is_one(name):
    assert phonetic_similarity(name, name) == 1.0


@pytest.mark.parametrize(("a", "b"), SYMMETRY_PAIRS)
def test_symmetry(a, b):
    assert phonetic_similarity(a, b) == phonetic_similarity(b, a)


@pytest.mark.parametrize(("a", "b"), SYMMETRY_PAIRS)
def test_determinism_and_range(a, b):
    first = phonetic_similarity(a, b)
    second = phonetic_similarity(a, b)
    assert first == second
    assert 0.0 <= first <= 1.0


@pytest.mark.parametrize("name", WEIRD_INPUTS)
def test_weird_inputs_return_float_quickly(name):
    started = time.perf_counter()
    score_self = phonetic_similarity(name, name)
    score_other = phonetic_similarity(name, "스타벅스")
    candidates = pronunciation_candidates(name)
    elapsed = time.perf_counter() - started
    assert isinstance(score_self, float) and isinstance(score_other, float)
    assert 0.0 <= score_self <= 1.0 and 0.0 <= score_other <= 1.0
    assert isinstance(candidates, list)
    assert elapsed < 1.0


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("스타벅스", True),
        ("STARBUCKS", True),  # ④ G2P
        ("東洋", False),  # v1: 한자 미지원
        ("", False),
        ("®", False),
    ],
)
def test_has_pronunciation(name, expected):
    assert has_pronunciation(name) is expected


# --------------------------------------------------------------------------- B. 판례 기반


@pytest.mark.parametrize(
    ("a", "b", "op", "threshold", "reason"),
    [
        ("스타벅스", "스타박스", ">=", 0.8, "중성 유사, 첫음절 동일"),
        ("스타벅스", "커피빈", "<=", 0.3, "전혀 다름"),
        ("삼성 SAMSUNG", "삼성", "==", 1.0, "⑤ 병기"),
        ("삼성전자 삼성전자", "삼성전자", "==", 1.0, "반복 토큰"),
        ("스타벅스 주식회사", "스타벅스", "==", 1.0, "회사형태 제거"),
        ("(주)스타벅스", "스타벅스", "==", 1.0, "회사표시 기호"),
        ("스타벅스 커피", "스타벅스", ">=", 0.9, "분리관찰(토큰 후보) — extra_generic 없이도"),
        ("커피 빈", "커피빈", "==", 1.0, "불가분 결합 보호"),
        ("카페 ABC", "에이비씨", ">=", 0.9, "혼용(영문 유지) + 낱자 읽기"),
        ("ATX", "에이티엑스", ">=", 0.9, "낱자 읽기"),
        ("랑콤", "랑콤 파리", ">=", 0.9, "분리관찰"),
        ("몬테로사", "MONTEROSA", ">=", 0.85, "④ G2P 룰 품질(예외 사전 미사용)"),
    ],
)
def test_case_law_clear_cases(a, b, op, threshold, reason):
    score = phonetic_similarity(a, b)
    if op == ">=":
        assert score >= threshold, f"{a} / {b}: {score:.3f} ({reason})"
    elif op == "<=":
        assert score <= threshold, f"{a} / {b}: {score:.3f} ({reason})"
    else:
        assert score == threshold, f"{a} / {b}: {score:.3f} ({reason})"


def test_extra_generic_removes_product_generic_token():
    """카페 봄 / 봄 — 호출자가 '카페'를 보통명칭으로 넘기면 요부만 대비한다."""
    score = phonetic_similarity("카페 봄", "봄", extra_generic=frozenset({"카페"}))
    assert score >= 0.9, score


# --------------------------------------------------------------------- v1 검토 반영 (2026-09-17)


def test_single_char_token_reading_is_not_a_separable_candidate():
    """알파벳 1글자 'K'의 낱자 읽기 '케이'가 분리관찰 후보로 들어가 무관한 상표를 1.0 으로
    만들지 않는다."""
    assert phonetic_similarity("실온K슐랭", "K8 REFOREST") <= 0.4
    assert "케이" not in pronunciation_candidates("실온K슐랭")


@pytest.mark.parametrize(
    ("a", "b", "op", "threshold", "reason"),
    [
        ("리쥬", "리주", ">=", 0.9, "y 계열 반모음 유사 (ㅠ,ㅜ)"),
        ("나이키", "마이키", ">=", 0.85, "비음 초성 유사 (ㄴ,ㅁ)"),
        ("현대", "HYUNDAI", "==", 1.0, "국내 브랜드 로마자 표"),
        ("교촌치킨", "KYOCHON CHICKEN", ">=", 0.9, "브랜드 표 + 룰 G2P 결합음"),
        ("3M", "쓰리엠", "==", 1.0, "1글자 토큰도 결합음에는 포함"),
        ("KR", "케이알", "==", 1.0, "모음 없는 토큰 낱자 읽기 유지"),
    ],
)
def test_review_adjustments(a, b, op, threshold, reason):
    score = phonetic_similarity(a, b)
    if op == ">=":
        assert score >= threshold, f"{a} / {b}: {score:.3f} ({reason})"
    else:
        assert score == threshold, f"{a} / {b}: {score:.3f} ({reason})"


def test_samsung_uses_paired_rule_path():
    """브랜드 표로 SAMSUNG→삼성 이 되어 ⑤ 병기 판정이 발동하면 후보는 '삼성' 하나뿐이다."""
    assert pronunciation_candidates("삼성 SAMSUNG") == ["삼성"]


def test_merged_vowel_pair_single_syllable():
    """합류 쌍(ㅐ,ㅔ) 비용 0.1 × 1음절 가중치 3.0 = 0.3, 최대거리 7.5 → 0.96 (2026-09-17 결정)."""
    assert phonetic_similarity("게", "개") >= 0.95


@pytest.mark.parametrize(
    ("a", "b", "op", "threshold", "reason"),
    [
        ("서울커피", "SEOUL COFFEE", ">=", 0.95, "지명표 seoul→서울 + 예외 coffee→커피"),
        ("커피빈", "COFFEE BEAN", "==", 1.0, "예외 coffee→커피 + 룰 bean→빈"),
        ("스타벅스커피", "STARBUCKS COFFEE", "==", 1.0, "룰 starbucks + 예외 coffee"),
        ("그대로", "GUDAERO", "==", 1.0, "브랜드표 로마자 캐기 승인분"),
        ("필라테스", "PILATES", "==", 1.0, "외래어 관용 표기 예외 사전"),
    ],
)
def test_v1_2_tables(a, b, op, threshold, reason):
    score = phonetic_similarity(a, b)
    if op == ">=":
        assert score >= threshold, f"{a} / {b}: {score:.3f} ({reason})"
    else:
        assert score == threshold, f"{a} / {b}: {score:.3f} ({reason})"


@pytest.mark.parametrize(
    ("a", "b", "op", "threshold", "reason"),
    [
        ("이랜드", "ELAND", "==", 1.0, "브랜드표 eland→이랜드"),
        ("파리바게뜨", "PARIS BAGUETTE", ">=", 0.95, "예외 사전 paris→파리 + baguette→바게뜨"),
        ("상미당", "SANGMIDANG", "==", 1.0, "브랜드표 sangmidang→상미당"),
    ],
)
def test_brand_list_cross_check(a, b, op, threshold, reason):
    """2026-09-17 유명 브랜드 목록(shared/famous_brands.txt) 교차 확인에서 승인한 항목."""
    score = phonetic_similarity(a, b)
    if op == ">=":
        assert score >= threshold, f"{a} / {b}: {score:.3f} ({reason})"
    else:
        assert score == threshold, f"{a} / {b}: {score:.3f} ({reason})"


def _load_report_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "x1_report.py"
    spec = importlib.util.spec_from_file_location("x1_report_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_benchmark_disables_exception_and_brand_tables(monkeypatch):
    """벤치마크(20단어)는 브랜드 표·지명표·예외 사전을 모두 끈 순수 룰로 측정한다."""
    from src.axes import x1_phonetic
    from src.axes.korean_brands import KOREAN_BRAND_ROMANIZATION, KOREAN_PLACE_ROMANIZATION

    assert "samsung" in KOREAN_BRAND_ROMANIZATION  # 표에 있어도
    report = _load_report_module()
    rows = {word: reading for word, _answer, reading, _score in report.benchmark_rows()}
    assert rows["SAMSUNG"] == x1_phonetic._g2p_rule("samsung") != "삼성"

    monkeypatch.setitem(x1_phonetic.G2P_EXCEPTIONS, "starbucks", "가짜")
    monkeypatch.setitem(KOREAN_BRAND_ROMANIZATION, "monterosa", "가짜")
    monkeypatch.setitem(KOREAN_PLACE_ROMANIZATION, "paris", "가짜")
    assert x1_phonetic.g2p_benchmark("starbucks") == "스타벅스"
    assert x1_phonetic.g2p_benchmark("monterosa") == "몬테로사"
    assert x1_phonetic.g2p_benchmark("paris") == "파리스"
    assert x1_phonetic._g2p_word("starbucks") == "가짜"
    assert x1_phonetic._g2p_word("monterosa") == "가짜"
    assert x1_phonetic._g2p_word("paris") == "가짜"
