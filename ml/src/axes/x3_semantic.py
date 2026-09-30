"""X3 관념(의미) 유사도 축 — 두 상표명이 같은 뜻으로 읽히는지를 다국어 임베딩 코사인으로 잰다.

규약(docs/MarkLens_작업가이드_ML.md §공통-2): 입력은 상표명 문자열 2개, 출력은 0.0~1.0 float
(높을수록 유사). 순수 함수·대칭·결정적이며 어떤 입력 문자열에도 예외를 던지지 않는다(결과
메모이즈만). 모델은 첫 호출 때 지연 로드해 프로세스에 캐시하고, 이름별 임베딩은 lru_cache 로
재사용한다. torch·sentence_transformers 는 모델을 만드는 함수 안에서만 import 한다.

판례 → 구현
    관념 유사: 두 표장이 지니는 의미·내용이 같거나 비슷해 수요자가 같은 뜻으로 인식하는 경우.
    한글·영문처럼 표기가 달라도 뜻이 같으면 관념이 유사하다(왕/KING, 사과/APPLE). 외관·호칭·관념
    중 하나만 유사해도 거래 실정상 출처 오인·혼동 우려가 있으면 유사 상표로 본다.
        → X1 과 같은 요부관찰 정규화(normalize_name: 회사 형태·부가어·기능어·extra_generic 제거)로
          표기를 다듬고, 토큰을 공백으로 이어 다국어 임베딩 코사인을 잰다. 발음(G2P)은 쓰지 않는다.
    조어(造語)·기호·도형은 특정한 관념이 없어 관념 대비 자체가 성립하지 않는다(호칭·외관으로만
    판단).
        → 관념 게이트 has_meaning: 정규화 토큰 중 하나라도 실제 단어(wordfreq 빈도표에 있는
          한국어 단어 zipf ≥ ZIPF_MIN_KO, 영어 단어 zipf ≥ ZIPF_MIN_EN)여야 계산한다. 아니면 0.0 —
          유사도 0 이 아니라 **결측**이므로 통합 모델은 has_meaning 으로 먼저 거른다.

점수
    임베딩 코사인은 무관한 이름끼리도 0 이 아니라 모델마다 다른 바닥값 근처에 모인다. DB 상표명
    (has_meaning True) 무작위 200쌍의 코사인 평균을 기준선 c₀ 로 재 두고(BASELINES, 모델별 실측)
    score = clip((cos − c₀) / (1 − c₀), 0, 1) 로 다시 맞춘다. 정규화 텍스트가 같으면 1.0.

게이트 판정 방식(2026-09-30 실측 근거)
    wordfreq.zipf_frequency 는 한국어 입력을 MeCab 으로 형태소 분리한 뒤 합산하므로 조어도 높은
    값이 나온다(스타벅스 3.94 = 스타+벅스, 엘쏘 4.45 = 엘+쏘). 그래서 토큰을 통째로 빈도표에서
    찾는다(get_frequency_dict, zipf = log10(빈도) + 9 — 단일 단어에서는 zipf_frequency 와 같은 값).
    사전에 있는 브랜드(카카오 = cacao, 애플)는 관념이 있는 단어로 보고 비교 대상에 넣는다.
    붙여쓴 합성어 폴백(v1.1, 설계 문서 §2 결정표의 V2b + 4.0): 한국어 토큰이 표제어가 아니면 모든
    분할점에서 두 부분으로 나눠 양쪽이 각각 2음절 이상이고 표제어 zipf ≥ COMPOUND_MIN_ZIPF 이면
    단어로 본다(푸른하늘 → 푸른 하늘). 왼쪽이 관형형이면(검은·행복한) 어미를 뗀 어간(검·행복)으로
    조회하고, 그런 관형형 뒤에는 1음절 명사도 허용한다(행복한집 → 행복한 집). 임베딩 텍스트는
    띄어 쓴 형태를 쓰고 세 부분 이상은 나누지 않는다. 스타벅스(스타 5.19·벅스 3.97)는 4.0 미만이라
    조어로 남는다.

알려진 한계(v1): 상위개념(과일/사과)·연상(별/커피)·다의어(사과 = apple/apology)는 임베딩이 구분하지
못하거나 과대평가한다. 영어 빈도표에는 자주 쓰이는 브랜드명도 있어(starbucks 3.77, samsung 4.12)
영문 브랜드는 게이트를 통과할 수 있다. 빈도표에 없는 낱말·신조어·부분이 zipf 4.0 미만인 합성어
(카카오프렌즈: 프렌즈 3.88)는 결측이 된다.
모델을 내려받지 못하는 환경에서는 첫 계산에서 RuntimeError 가 난다(입력 오류가 아니라 환경 오류).
"""

from __future__ import annotations

import functools
import hashlib
import logging
import math
import os
from typing import Final, Protocol

import numpy as np
from wordfreq import get_frequency_dict

from .x1_phonetic import normalize_name

__all__ = ["semantic_similarity", "has_meaning"]

logger = logging.getLogger(__name__)

# =====================================================================================
# 설계 상수 (검토·조정 대상)
# =====================================================================================

# 관념 게이트 임계값(zipf: log10(단어 빈도 per 10^9)). 한국어 빈도표는 zipf 3.01 이상만 수록된
# small 목록이라 2.5 는 사실상 "표에 있는가"이고, 영어(large, 최소 1.01)는 백만 단어당 1회 이상.
ZIPF_MIN_KO: Final = 2.5
ZIPF_MIN_EN: Final = 3.0

# 붙여쓴 합성어 폴백(v1.1, 2026-09-30 결정 — 설계 문서 §2 결정표의 V2b + 4.0): 한국어 토큰이
# 표제어가 아니면 두 부분으로 나눠 양쪽이 각각 COMPOUND_MIN_SYLLABLES 음절 이상이고 표제어 zipf ≥
# COMPOUND_MIN_ZIPF 이면 단어로 본다. 왼쪽이 관형형이면 어간으로 조회하고 그 뒤에는 1음절 명사도
# 허용한다.
COMPOUND_MIN_ZIPF: Final = 4.0
COMPOUND_MIN_SYLLABLES: Final = 2
# 관형형 어미(마지막 음절). 검은 → 검, 행복한 → 행복 처럼 어미를 뗀 어간을 조회한다.
ADNOMINAL_ENDINGS: Final = frozenset("은는한운인된을할")
# 받침 ㄴ·ㄹ 로 끝나는 관형형(푸른 → 푸르)은 받침을 떼어 본다. 한글 음절 코드의 종성 번호.
_JONG_N: Final = 4
_JONG_L: Final = 8
_HANGUL_BASE: Final = 0xAC00
_HANGUL_COUNT: Final = 11172
_JONG_COUNT: Final = 28

ENV_MODEL: Final = "MARKLENS_X3_MODEL"  # sentence-transformers 모델 이름으로 교체
ENV_FAKE: Final = "MARKLENS_FAKE_ML"  # 값이 있으면 가짜 임베더(테스트·CI, 모델 다운로드 없음)

# 벤치마크(ml/scripts/x3_benchmark.py, 2026-09-30)로 선정한 기본 모델.
DEFAULT_MODEL: Final = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# 모델별 기준선 c₀ — DB 상표명 중 has_meaning True 577건에서 무작위 200쌍(seed 0)의 코사인 평균.
# 표에 없는 모델은 0.0(원 코사인)으로 계산하고 경고를 남긴다.
BASELINES: Final[dict[str, float]] = {
    "intfloat/multilingual-e5-base": 0.7716,
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 0.3313,
    "sentence-transformers/LaBSE": 0.2049,
}

# 모델이 요구하는 입력 접두어. e5 계열은 대칭 과제(유사도)에 양쪽 모두 "query: " 를 붙인다.
MODEL_PREFIX: Final[dict[str, str]] = {"intfloat/multilingual-e5-base": "query: "}

FAKE_DIM: Final = 256  # 가짜 임베더 차원(문자 3-gram 해시)
FAKE_BASELINE: Final = 0.0
EMBED_CACHE_SIZE: Final = 4096  # DB 1,100건이 모두 들어가는 크기
ENCODE_BATCH_SIZE: Final = 32

_HANGUL_RANGES: Final = ((0xAC00, 0xD7A3), (0x3131, 0x318E), (0x1100, 0x11FF))


# =====================================================================================
# 1. 관념 게이트 — 정규화 토큰이 실제 단어인가
# =====================================================================================


def _language(token: str) -> str | None:
    """토큰의 빈도표 언어: 한글이면 ko, 영문 소문자면 en, 숫자 등은 None(단어가 아님)."""
    if not token:
        return None
    code = ord(token[0])
    if any(low <= code <= high for low, high in _HANGUL_RANGES):
        return "ko"
    if "a" <= token[0] <= "z":
        return "en"
    return None


@functools.lru_cache(maxsize=4)
def _frequency_table(lang: str) -> dict[str, float]:
    return get_frequency_dict(lang)


def token_zipf(token: str) -> float:
    """토큰을 통째로 빈도표에서 찾은 zipf 값(없으면 0.0). 보고·디버깅용."""
    lang = _language(token)
    if lang is None:
        return 0.0
    frequency = _frequency_table(lang).get(token, 0.0)
    return math.log10(frequency) + 9.0 if frequency > 0 else 0.0


def _stem_zipf(part: str) -> float:
    """관형형 어미를 뗀 어간의 표제어 zipf(후보 중 최댓값). 관형형 꼴이 아니면 0.0.

    후보: 마지막 음절이 ADNOMINAL_ENDINGS 면 그 음절을 뗀 것(검은 → 검, 행복한 → 행복),
    마지막 음절의 받침이 ㄴ·ㄹ 이면 받침을 뗀 것(푸른 → 푸르).
    """
    if not part:
        return 0.0
    last = part[-1]
    candidates: list[str] = []
    if last in ADNOMINAL_ENDINGS and len(part) > 1:
        candidates.append(part[:-1])
    code = ord(last) - _HANGUL_BASE
    if 0 <= code < _HANGUL_COUNT and code % _JONG_COUNT in (_JONG_N, _JONG_L):
        candidates.append(part[:-1] + chr(_HANGUL_BASE + code - code % _JONG_COUNT))
    return max((token_zipf(candidate) for candidate in candidates), default=0.0)


def _left_zipf(left: str) -> float:
    """합성어 왼쪽 부분의 zipf: 표제어면 그 값, 아니면 관형형 어간의 값."""
    zipf = token_zipf(left)
    if zipf >= COMPOUND_MIN_ZIPF:
        return zipf
    stem = _stem_zipf(left)
    return stem if stem >= COMPOUND_MIN_ZIPF else zipf


@functools.lru_cache(maxsize=EMBED_CACHE_SIZE)
def _compound_split(token: str) -> tuple[str, str] | None:
    """표제어가 아닌 한국어 토큰을 두 부분으로 나눈다(합성어 폴백). 못 나누면 None.

    1) 모든 분할점에서 양쪽이 각각 COMPOUND_MIN_SYLLABLES 음절 이상이고 zipf(왼쪽은 관형형이면
       어간) ≥ COMPOUND_MIN_ZIPF 인 분할 중 두 부분 zipf 의 최솟값이 가장 큰 것(같으면 앞쪽).
    2) 없으면 관형형(표제어가 아니고 어간이 표제어) + 1음절 이상 명사 분할 중 첫 번째.
    세 부분 이상으로는 나누지 않는다.
    """
    if _language(token) != "ko" or len(token) < COMPOUND_MIN_SYLLABLES + 1:
        return None
    if token_zipf(token) >= ZIPF_MIN_KO:  # 표제어면 나누지 않는다
        return None
    best: tuple[str, str] | None = None
    best_score = 0.0
    for cut in range(COMPOUND_MIN_SYLLABLES, len(token) - COMPOUND_MIN_SYLLABLES + 1):
        left, right = token[:cut], token[cut:]
        score = min(_left_zipf(left), token_zipf(right))
        if score >= COMPOUND_MIN_ZIPF and score > best_score:
            best, best_score = (left, right), score
    if best is not None:
        return best
    for cut in range(COMPOUND_MIN_SYLLABLES, len(token)):
        left, right = token[:cut], token[cut:]
        if (
            token_zipf(left) < COMPOUND_MIN_ZIPF
            and _stem_zipf(left) >= COMPOUND_MIN_ZIPF
            and token_zipf(right) >= COMPOUND_MIN_ZIPF
        ):
            return left, right
    return None


def _is_word(token: str) -> bool:
    lang = _language(token)
    if lang is None:
        return False
    if lang == "en":
        return token_zipf(token) >= ZIPF_MIN_EN
    return token_zipf(token) >= ZIPF_MIN_KO or _compound_split(token) is not None


def _expand_token(token: str) -> str:
    """임베딩용 표기: 합성어 폴백으로 나뉜 토큰은 띄어 쓴 형태(푸른하늘 → "푸른 하늘")."""
    parts = _compound_split(token)
    return f"{parts[0]} {parts[1]}" if parts else token


def has_meaning(name: str, *, extra_generic: frozenset[str] = frozenset()) -> bool:
    """정규화 토큰 중 하나라도 실제 단어이면 True. False 인 상표(조어·기호만·한자만·도형)는 X3 를
    결측 처리하고 다른 축만으로 판단한다(X1 의 has_pronunciation 과 같은 역할).

    Args:
        name: 상표명 문자열.
        extra_generic: 상품 의존 보통명칭 집합. 제거된 토큰은 판정에서 빠진다("카페 봄" → 봄).
    """
    tokens = normalize_name(name, extra_generic=frozenset(extra_generic))
    return any(_is_word(token) for token in tokens)


# =====================================================================================
# 2. 임베더 — 실제 모델(지연 로드)과 가짜 모델
# =====================================================================================


class Embedder(Protocol):
    name: str

    def embed_many(self, texts: list[str]) -> np.ndarray:
        """텍스트 목록 → (n, dim) float32 단위 벡터."""


class SentenceTransformerEmbedder:
    """sentence-transformers 모델 래퍼(CPU, 단위 벡터).

    처음 만들 때 모델을 내려받거나 HuggingFace 캐시에서 읽는다.
    """

    def __init__(self, name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # 무거운 import 는 여기서만
        except ImportError as exc:  # pragma: no cover - 설치 누락은 환경 오류
            raise RuntimeError("X3 관념 축에는 sentence-transformers 가 필요합니다") from exc
        self.name = name
        self.prefix = MODEL_PREFIX.get(name, "")
        try:
            self.model = SentenceTransformer(name, device="cpu")
        except Exception as exc:  # 모델 다운로드·캐시 실패 — 입력 오류가 아니라 환경 오류
            raise RuntimeError(f"X3 모델 {name} 을 불러오지 못했습니다: {exc}") from exc

    @property
    def dim(self) -> int:
        getter = getattr(self.model, "get_embedding_dimension", None)  # 6.x 이름, 구버전 폴백
        if getter is None:
            getter = self.model.get_sentence_embedding_dimension
        return int(getter() or 0)

    def embed_many(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = self.model.encode(
            [self.prefix + text for text in texts],
            batch_size=ENCODE_BATCH_SIZE,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


class FakeEmbedder:
    """MARKLENS_FAKE_ML 용 결정적 가짜 임베더 — 문자 3-gram 해시 단위 벡터.

    의미는 모르지만 규약(같은 텍스트 → 같은 벡터, 단위 벡터, 예외 없음)은 지켜서 불변식 테스트와
    CI 가 모델 다운로드 없이 돈다. 점수 자체는 의미가 없다.
    """

    name = "fake"
    dim = FAKE_DIM

    def embed_many(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, FAKE_DIM), dtype=np.float32)
        return np.stack([self._vector(text) for text in texts])

    @staticmethod
    def _vector(text: str) -> np.ndarray:
        vector = np.zeros(FAKE_DIM, dtype=np.float32)
        padded = f" {text} "
        for index in range(len(padded) - 2):
            digest = hashlib.blake2b(padded[index : index + 3].encode("utf-8"), digest_size=4)
            code = int.from_bytes(digest.digest(), "big")
            vector[(code >> 1) % FAKE_DIM] += 1.0 if code & 1 else -1.0
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector


def configured_model() -> str:
    """환경변수 MARKLENS_X3_MODEL 이 있으면 그 모델, 없으면 DEFAULT_MODEL."""
    return os.environ.get(ENV_MODEL, "").strip() or DEFAULT_MODEL


def load_embedder(model_name: str | None = None) -> Embedder:
    """임베더를 새로 만든다(프로세스 캐시 없음). 벤치마크·사전 계산 스크립트용.

    MARKLENS_FAKE_ML 이 설정돼 있으면 model_name 과 무관하게 가짜 임베더를 돌려준다.
    """
    if os.environ.get(ENV_FAKE):
        return FakeEmbedder()
    return SentenceTransformerEmbedder(model_name or configured_model())


_embedder: Embedder | None = None


def _get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        embedder = load_embedder()
        if not isinstance(embedder, FakeEmbedder) and embedder.name not in BASELINES:
            logger.warning(
                "X3 모델 %s 의 기준선 c₀ 가 없어 원 코사인을 그대로 씁니다", embedder.name
            )
        _embedder = embedder
    return _embedder


def _reset_embedder() -> None:
    """테스트용: 캐시된 임베더와 임베딩을 비운다(환경변수를 바꾼 뒤 호출)."""
    global _embedder
    _embedder = None
    _embed_cached.cache_clear()


@functools.lru_cache(maxsize=EMBED_CACHE_SIZE)
def _embed_cached(text: str) -> np.ndarray:
    vector = _get_embedder().embed_many([text])[0]
    vector.setflags(write=False)
    return vector


def _baseline() -> float:
    embedder = _get_embedder()
    if isinstance(embedder, FakeEmbedder):
        return FAKE_BASELINE
    return BASELINES.get(embedder.name, 0.0)


# =====================================================================================
# 3. 점수
# =====================================================================================


def recalibrate(cosine: float, baseline: float) -> float:
    """원 코사인 → 0~1 점수: clip((cos − c₀) / (1 − c₀), 0, 1). c₀ 이하는 0, NaN 은 0."""
    if math.isnan(cosine):
        return 0.0
    if baseline >= 1.0:
        return min(max(cosine, 0.0), 1.0)
    return min(max((cosine - baseline) / (1.0 - baseline), 0.0), 1.0)


def embedding_text(name: str, *, extra_generic: frozenset[str] = frozenset()) -> str:
    """실제로 임베딩되는 텍스트(정규화 토큰을 공백으로 이은 것, 합성어는 띄어 씀). 보고·디버깅용."""
    tokens = normalize_name(name, extra_generic=frozenset(extra_generic))
    return " ".join(_expand_token(token) for token in tokens)


def semantic_similarity(
    name_a: str, name_b: str, *, extra_generic: frozenset[str] = frozenset()
) -> float:
    """관념(의미) 유사도. 0.0~1.0, 높을수록 유사. 대칭·결정적이며 어떤 문자열에도 예외 없이 반환.

    둘 다 has_meaning 이어야 계산하고 아니면 0.0(결측). 정규화 텍스트가 같으면 1.0, 다르면
    임베딩 코사인을 모델별 기준선 c₀ 로 재보정한 값. 임베딩은 이름별로 캐시된다.

    Args:
        name_a: 상표명 A.
        name_b: 상표명 B.
        extra_generic: 양쪽에 공통으로 적용할 상품 의존 보통명칭 집합.
    """
    generic = frozenset(extra_generic)
    tokens_a = normalize_name(name_a, extra_generic=generic)
    tokens_b = normalize_name(name_b, extra_generic=generic)
    if not any(_is_word(t) for t in tokens_a) or not any(_is_word(t) for t in tokens_b):
        return 0.0
    text_a = " ".join(_expand_token(t) for t in tokens_a)
    text_b = " ".join(_expand_token(t) for t in tokens_b)
    if text_a == text_b:
        return 1.0
    if text_b < text_a:  # 인자 순서와 무관하게 같은 순서로 계산 → 대칭 보장
        text_a, text_b = text_b, text_a
    cosine = float(np.dot(_embed_cached(text_a), _embed_cached(text_b)))
    return recalibrate(cosine, _baseline())
