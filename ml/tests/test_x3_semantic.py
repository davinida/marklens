"""X3 관념 유사도 축 테스트 — A. 불변식, B. 관념 게이트, C. 벤치마크(실제 모델), D. 정규화 재사용.

실행 (프로젝트 루트):
    MARKLENS_FAKE_ML=1 ml/venv/bin/python -m pytest ml/tests/test_x3_semantic.py -q   # 가짜(CI)
    ml/venv/bin/python -m pytest ml/tests/test_x3_semantic.py -q                       # 실제 모델
C 는 MARKLENS_FAKE_ML 이 있으면 건너뛴다(가짜 임베더 점수는 의미가 없다). 실제 모델은 첫 실행 때
HuggingFace 에서 내려받는다. 점수표 보고는 ml/scripts/x3_benchmark.py 가 한다.
"""

import math
import os

import numpy as np
import pytest
from src.axes import x3_semantic as x3
from src.axes.x1_phonetic import normalize_name, phonetic_similarity
from src.axes.x3_semantic import has_meaning, semantic_similarity

FAKE_MODE = bool(os.environ.get("MARKLENS_FAKE_ML"))
real_model = pytest.mark.skipif(
    FAKE_MODE, reason="MARKLENS_FAKE_ML: 가짜 임베더 — 실제 모델 점수는 재지 않는다"
)

# 벤치마크 정답 쌍(작업 명세 2026-09-30). 단언값 0.6/0.35 는 선정 모델(MiniLM-L12-v2)의 점수 분포에
# 맞춘 값(v1.1 결정: 유사 최소 0.617, 비유사 최대 0.318)이지 서비스 임계값이 아니다(설계 문서 §4).
SIMILAR_MIN = 0.6
DISSIMILAR_MAX = 0.35
SIMILAR = [
    ("왕", "KING"), ("사과", "APPLE"), ("별", "STAR"), ("바다", "OCEAN"), ("하늘", "SKY"),
    ("봄", "SPRING"), ("달", "MOON"), ("사랑", "LOVE"), ("나무", "TREE"), ("태양", "SUN"),
    ("꽃", "FLOWER"),
]
DISSIMILAR = [
    ("왕", "사과"), ("별", "커피"), ("바다", "나무"), ("사랑", "자동차"), ("하늘", "신발"),
    ("달", "의자"), ("꽃", "컴퓨터"), ("태양", "가방"),
]

# --------------------------------------------------------------------------- A. 불변식

MEANINGFUL = [
    "왕", "KING", "사과", "카페 봄", "BLACK CAT", "(주)사과 코리아", "Dr.Groot TRIPLE CICA",
]
GARBAGE = [None, "", "   ", "🙂", "漢字", "ㅂㄹ", "1234", "%%%", 42, "x" * 2000, "​", "王"]


@pytest.mark.parametrize("name", MEANINGFUL)
def test_self_similarity_is_one(name):
    assert semantic_similarity(name, name) == 1.0


def test_same_normalized_text_is_one_without_embedding():
    # 회사 형태·부가어를 뗀 텍스트가 같으면 임베딩 없이 1.0 (X1 정규화 재사용)
    assert semantic_similarity("사과", "(주)사과 코리아") == 1.0
    assert semantic_similarity("KING", "king co., ltd.") == 1.0


@pytest.mark.parametrize(
    ("a", "b"),
    [("왕", "KING"), ("사과", "APPLE"), ("왕", "사과"), ("스타벅스", "커피빈"), ("카페 봄", "봄"),
     ("BLACK CAT", "검은 고양이"), ("사랑", "자동차")],
)
def test_symmetric(a, b):
    assert semantic_similarity(a, b) == semantic_similarity(b, a)


@pytest.mark.parametrize("a", MEANINGFUL + GARBAGE)
@pytest.mark.parametrize("b", ["왕", "APPLE", None, "", "🙂"])
def test_returns_float_in_unit_interval_without_raising(a, b):
    score = semantic_similarity(a, b)  # type: ignore[arg-type]
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0
    assert not math.isnan(score)


def test_deterministic_across_calls():
    first = semantic_similarity("왕", "KING")
    assert all(semantic_similarity("왕", "KING") == first for _ in range(3))


def test_missing_meaning_side_is_zero():
    # 유사도 0 이 아니라 결측: 조어·기호·빈 문자열이 한쪽이라도 있으면 0.0
    assert semantic_similarity("스타벅스", "커피빈") == 0.0
    assert semantic_similarity("엘쏘", "왕") == 0.0
    assert semantic_similarity("왕", "XSR") == 0.0
    assert semantic_similarity("", "왕") == 0.0
    assert semantic_similarity("엘쏘", "엘쏘") == 0.0  # 같아도 관념이 없으면 결측


def test_extra_generic_is_applied_to_both_sides():
    assert semantic_similarity("카페 봄", "봄", extra_generic=frozenset({"카페"})) == 1.0
    # 전부 제거되면 제거 전 토큰으로 폴백
    assert semantic_similarity("카페", "카페", extra_generic=frozenset({"카페"})) == 1.0


# --------------------------------------------------------------------------- B. 관념 게이트


@pytest.mark.parametrize(
    "name",
    ["스타벅스", "엘쏘", "XSR", "", "   ", "漢字", "🙂", "ㅂㄹ", "1234", "%%%", "モンテローザ",
     "asdfgh", "qzxv"],
)
def test_has_meaning_false_for_coined_symbols_and_hanja(name):
    assert has_meaning(name) is False


@pytest.mark.parametrize(
    "name",
    ["왕", "KING", "사과", "APPLE", "바다", "BLACK CAT", "하늘 SKY",
     "카카오", "애플"],  # 사전어 브랜드(카카오 = cacao)는 관념 비교 대상 (v1.1 결정)
)
def test_has_meaning_true_for_real_words(name):
    assert has_meaning(name) is True


def test_has_meaning_with_extra_generic():
    assert has_meaning("카페 봄", extra_generic=frozenset({"카페"})) is True
    assert has_meaning("카페", extra_generic=frozenset({"카페"})) is True  # 전부 제거 → 폴백


@pytest.mark.parametrize(
    "name", ["유", "재", "T", "e", "LG", "e마티콘", "숏MV", "BB", "K8", "Dr", "잔", "탑"]
)
def test_gate_rejects_syllable_fragments_and_short_english(name):
    # v1.3: 빈도표의 1음절 조각(유·재)과 2자 이하 영문(T·e·LG)은 단어로 보지 않는다
    assert has_meaning(name) is False


@pytest.mark.parametrize("name", ["왕", "별", "달", "꽃", "해", "집", "KING", "SKY", "bbq"])
def test_gate_accepts_whitelisted_single_syllables_and_three_letter_words(name):
    assert has_meaning(name) is True


def test_single_syllable_noun_whitelist_shape():
    nouns = x3.KO_SINGLE_SYLLABLE_NOUNS
    assert len(nouns) >= 60
    assert all(len(n) == 1 and "가" <= n <= "힣" for n in nouns)
    assert {"왕", "별", "달"} <= nouns and not {"유", "재", "노래"} & nouns
    assert x3.EN_MIN_LETTERS == 3


def test_one_real_word_among_coined_tokens_is_enough():
    assert has_meaning("엘쏘 사과") is True
    assert has_meaning("XSR king") is True


def test_token_zipf_lookup_is_exact_and_language_specific():
    assert x3.token_zipf("왕") >= x3.ZIPF_MIN_KO
    assert x3.token_zipf("king") >= x3.ZIPF_MIN_EN
    assert x3.token_zipf("xsr") == 0.0
    assert x3.token_zipf("1234") == 0.0
    assert x3.token_zipf("") == 0.0
    # 통째로 조회: MeCab 분리 합산(zipf_frequency)이면 3.9 이상인 조어가 0 이다
    assert x3.token_zipf("스타벅스") == 0.0
    assert x3.token_zipf("엘쏘") == 0.0


# --------------------------------------------------------------------------- B-2. 합성어 폴백(v1.1)
# 설계 문서 §2 결정표의 V2b + COMPOUND_MIN_ZIPF 4.0 (2026-09-30 확정). 카카오프렌즈(프렌즈 3.88)·
# 트로피카나(트로피+카나)는 보수적으로 제외된다.


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("푸른하늘", True), ("검은고양이", True), ("행복한집", True), ("서울우유", True),
        ("스타벅스", False), ("엘쏘", False), ("카카오프렌즈", False), ("트로피카나", False),
    ],
)
def test_compound_fallback_gate(name, expected):
    assert has_meaning(name) is expected


def test_compound_split_rules():
    assert x3._compound_split("푸른하늘") == ("푸른", "하늘")  # 푸른 은 표제어(4.37)
    assert x3._compound_split("검은고양이") == ("검은", "고양이")  # 검은 → 어간 검(4.94)
    assert x3._compound_split("행복한집") == ("행복한", "집")  # 관형형 뒤 1음절 명사 허용
    assert x3._compound_split("서울우유") == ("서울", "우유")
    assert x3._compound_split("스타벅스") is None  # 벅스 3.97 < 4.0
    assert x3._compound_split("고양이") is None  # 표제어는 나누지 않는다
    assert x3._compound_split("엘쏘") is None  # 1음절 부분(관형형 아님)은 허용하지 않는다
    assert x3._compound_split("서울우유고양이") is None  # 세 부분 이상은 나누지 않는다
    assert x3._compound_split("king") is None
    assert x3._compound_split("") is None


def test_stem_zipf_strips_adnominal_endings():
    assert x3._stem_zipf("검은") == x3.token_zipf("검") >= x3.COMPOUND_MIN_ZIPF
    assert x3._stem_zipf("행복한") == x3.token_zipf("행복")
    assert x3._stem_zipf("푸른") == x3.token_zipf("푸르")  # 받침 ㄴ 분리
    assert x3._stem_zipf("고양이") == 0.0  # 관형형 꼴이 아니다
    assert x3._stem_zipf("") == 0.0


def test_compound_embedding_text_is_spaced():
    assert x3.embedding_text("푸른하늘") == "푸른 하늘"
    assert x3.embedding_text("검은고양이") == "검은 고양이"
    assert x3.embedding_text("행복한집 HAPPY HOME") == "행복한 집 happy home"
    assert semantic_similarity("푸른하늘", "푸른 하늘") == 1.0
    assert semantic_similarity("검은고양이", "검은 고양이") == 1.0
    assert semantic_similarity("푸른하늘", "푸른하늘") == 1.0


# --------------------------------------------------------------------------- C. 벤치마크(실제 모델)


@real_model
@pytest.mark.slow
@pytest.mark.parametrize(("a", "b"), SIMILAR)
def test_benchmark_similar_pairs_score_high(a, b):
    assert semantic_similarity(a, b) >= SIMILAR_MIN


@real_model
@pytest.mark.slow
@pytest.mark.parametrize(("a", "b"), DISSIMILAR)
def test_benchmark_dissimilar_pairs_score_low(a, b):
    assert semantic_similarity(a, b) <= DISSIMILAR_MAX


@real_model
@pytest.mark.slow
def test_benchmark_compound_black_cat():
    assert semantic_similarity("검은고양이", "BLACK CAT") >= SIMILAR_MIN


@real_model
@pytest.mark.slow
def test_benchmark_compound_blue_sky():
    assert semantic_similarity("푸른하늘", "BLUE SKY") >= SIMILAR_MIN


@real_model
@pytest.mark.slow
def test_benchmark_spaced_compound_and_hypernyms():
    assert semantic_similarity("검은 고양이", "BLACK CAT") >= SIMILAR_MIN
    for a, b in [("과일", "사과"), ("동물", "고양이")]:
        assert semantic_similarity(a, b) < SIMILAR_MIN  # 상위개념은 유사 쌍보다 낮아야 한다


@real_model
@pytest.mark.slow
def test_default_model_has_measured_baseline():
    assert x3.configured_model() in x3.BASELINES
    assert 0.0 < x3.BASELINES[x3.DEFAULT_MODEL] < 1.0


# ------------------------------------------------------------------- D. 정규화·임베더·재보정


@pytest.mark.parametrize(
    ("name", "generic", "expected"),
    [
        ("(주)스타벅스 코리아", frozenset(), ["스타벅스"]),
        ("KING", frozenset(), ["king"]),
        ("카페 봄", frozenset({"카페"}), ["봄"]),
        ("BLUE COFFEE", frozenset({"커피"}), ["blue"]),  # 읽기 대조(COFFEE→커피) 포함
        ("주식회사", frozenset(), ["주식회사"]),  # 전부 제거되면 제거 전 토큰
        ("Dr.Groot TRIPLE CICA", frozenset(), ["dr", "groot", "triple", "cica"]),
        (None, frozenset(), []),
        ("", frozenset(), []),
        ("漢字", frozenset(), []),
        ("검은고양이", frozenset(), ["검은고양이"]),
    ],
)
def test_normalize_name(name, generic, expected):
    assert normalize_name(name, extra_generic=generic) == expected  # type: ignore[arg-type]


def test_normalize_name_is_the_x1_pipeline_unchanged():
    # 공개 헬퍼는 X1 내부 정규화(제거 후 토큰)를 그대로 돌려준다 — X1 점수 변화 없음(§9 v1.5)
    from src.axes.x1_phonetic import _normalize_tokens

    for name in MEANINGFUL + ["(주)한입 간장게장", "H motors SINCE 1994", "BLUE COFFEE"]:
        for generic in (frozenset(), frozenset({"커피"})):
            expected = _normalize_tokens(name, generic)[1]
            assert normalize_name(name, extra_generic=generic) == expected
    assert phonetic_similarity("(주)스타벅스 코리아", "스타벅스") == 1.0


def test_embedding_text_joins_normalized_tokens():
    assert x3.embedding_text("(주)BLACK CAT 코리아") == "black cat"
    assert x3.embedding_text("카페 봄", extra_generic=frozenset({"카페"})) == "봄"


@pytest.mark.parametrize(
    ("cosine", "baseline", "expected"),
    [(1.0, 0.5, 1.0), (0.5, 0.5, 0.0), (0.75, 0.5, 0.5), (0.2, 0.5, 0.0), (-1.0, 0.0, 0.0),
     (1.2, 0.5, 1.0), (float("nan"), 0.5, 0.0), (0.7, 1.0, 0.7)],
)
def test_recalibrate(cosine, baseline, expected):
    assert x3.recalibrate(cosine, baseline) == pytest.approx(expected)


def test_fake_embedder_is_deterministic_unit_vectors():
    fake = x3.FakeEmbedder()
    vectors = fake.embed_many(["왕", "king", "왕"])
    assert vectors.shape == (3, x3.FAKE_DIM)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert np.array_equal(vectors[0], vectors[2])
    assert not np.array_equal(vectors[0], vectors[1])
    assert fake.embed_many([]).shape == (0, x3.FAKE_DIM)


def test_embed_texts_batches_and_feeds_the_cache():
    # 서비스(backend/src/core/semantic_search.py) 기동용 배치 헬퍼 — 단위 벡터, 같은 텍스트는
    # 같은 벡터, 이후 embed_text·semantic_similarity 가 같은 캐시를 쓴다.
    vectors = x3.embed_texts(["왕", "king", "왕"])
    assert vectors.shape[0] == 3 and vectors.shape[1] == x3._get_embedder().dim
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert np.array_equal(vectors[0], vectors[2])
    assert np.array_equal(x3.embed_text("왕"), vectors[0])
    assert x3.embed_texts([]).shape[0] == 0
    assert 0.0 <= x3.current_baseline() < 1.0
    assert x3.embedder_name() == ("fake" if FAKE_MODE else x3.configured_model())
    cosine = float(np.dot(vectors[0], vectors[1]))
    assert semantic_similarity("왕", "KING") == pytest.approx(
        x3.recalibrate(cosine, x3.current_baseline()), abs=1e-6
    )


def test_load_embedder_uses_fake_when_env_set(monkeypatch):
    monkeypatch.setenv(x3.ENV_FAKE, "1")
    assert isinstance(x3.load_embedder("whatever/model"), x3.FakeEmbedder)


def test_configured_model_env_override(monkeypatch):
    monkeypatch.delenv(x3.ENV_MODEL, raising=False)
    assert x3.configured_model() == x3.DEFAULT_MODEL
    monkeypatch.setenv(x3.ENV_MODEL, " some/model ")
    assert x3.configured_model() == "some/model"


def test_module_does_not_import_heavy_libraries_at_import_time():
    import sys

    assert "src.axes.x3_semantic" in sys.modules
    # sentence_transformers 는 SentenceTransformerEmbedder 를 만들 때만 import 된다
    if FAKE_MODE:
        assert "sentence_transformers" not in sys.modules
