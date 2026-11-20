"""X2 문자 외관(철자) 축 — 두 상표명의 글자 구성이 얼마나 비슷한지(표기 기준, 발음 변환 없음).

규약(공통-2): 입력은 상표명 문자열 2개, 출력은 0.0~1.0 float(높을수록 유사). 순수 함수·대칭·결정적
이며 어떤 입력에도 예외를 던지지 않는다. 표준 라이브러리만 쓰고 X1 의 정규화·자모 유틸을 재사용한다.

판례 근거
    표장의 유사는 외관·호칭·관념을 전체적·객관적·이격적으로 관찰해 수요자가 출처를 오인·혼동할
    염려가 있는지로 판단한다(대법원 97후3050 등). 문자상표의 **외관**은 글자의 구성·배열이
    시각적으로 비슷한지의 문제이므로, 이 축은 발음(G2P)을 쓰지 않고 정규화한 **철자** 를 비교한다.
    심결 이미지 쌍 벤치마크(docs/MarkLens_X2_외관_설계.md §7)에서 OCR 글자의 철자 유사
    (`x2_text_ortho`)가 외관축 AUC 0.72 로 CLIP 전체 이미지(0.63)보다 높아 축 함수로 올렸다.

X1 호칭과의 차이 — 재는 것이 다르다
    - XSR / XSL: 철자는 3자 중 2자가 같아 외관이 유사(0.667)하고, 호칭(엑스에스알 / 엑스에스엘)은
      끝 음절이 다른 별개의 호칭이다(X1 은 음절 편집거리라 0.93 으로 높게 보지만 이 축과는 다른
      근거).
    - 나이키 / NIKE: 호칭은 같지만(X1 0.91) 철자는 한글·영문이라 전혀 다르다(0.0).
    - 스타벅스 / STARBUCKS 도 같은 이유로 0.0 — 한영 병기 표장은 X1 이 호칭으로 잇고, 이 축은
      글자 구성만 본다. 통합 모델은 두 축을 따로 받아 학습한다.

방법
    1. X1 `normalize_name` 으로 토큰 정리(NFKC·casefold → 회사 형태·부가어·영문 기능어·호출자의
       `extra_generic` 제거, 한자·기호 토큰 버림). 영문은 소문자, 한글은 음절을 초·중·종성 자모로
       푼다.
    2. 비교 후보 = 정규화 토큰을 붙인 전체 문자열 + (토큰이 3개 이하일 때) 2자 이상인 각 토큰
       — 분리관찰(일부만으로도 외관이 대비될 수 있다)을 X1 과 같은 상한으로 근사한다.
    3. 양쪽 후보의 모든 쌍에 문자 단위 정규화 편집거리 유사도 1 − d/max(len) 를 적용한 최댓값.

알려진 한계(v1): 서체·색·배열(세로쓰기 등) 같은 시각 요소는 보지 못한다. 공통 토큰이 있으면
분리관찰로 1.0 이 되므로 보통명칭은 `extra_generic` 으로 걸러야 한다(X1 과 같음). 한자 토큰은
버린다. **요부 토큰이 여러 개일 때 공통 토큰 하나만 같아도 1.0 이 된다**(GATE HELLO / GATE WORLD,
BLUE BOTTLE / BLUE HANDS — 둘 다 요부인데 하나만 같다) — v2 가 고친다.

버전(2026-11-20, `version` 인자 — 기본 1, 통합 모델 JSON 이 요구하는 버전으로 계산한다)
    v1  위의 방법(전체 문자열 + 토큰 후보의 최댓값). 통합 모델 v1.3·v1.4 의 입력.
    v2  같은 토큰(정규화 + `extra_generic` 제거 뒤 — 식별력 필터가 넘긴 약한 토큰을 뺀 요부
        토큰)으로
        ① 덮개 점수: 두 이름의 토큰을 일대일로 짝지어(짝 유사도의 합이 최대가 되게, 같으면 덮개
           점수가 큰 쪽) 짝의 유사도를 토큰 글자 수로 가중 평균하되 짝이 없는 토큰의 글자 수는
           분모에만 넣는다 — A 쪽·B 쪽 양방향으로 구해 평균.
        ② 이어 붙인 문자열: 토큰을 공백 없이 이은 문자열끼리의 유사도(띄어쓰기 차이 대비 —
           커피빈 / 커피 빈).
        ③ v2 = max(①, ②).
        "글자 수" = 비교 키 길이(한글은 자모로 푼 길이, 영문·숫자는 글자 수) — 유사도
        1 − d/max(len) 와 같은 단위. 토큰 수 상한(v1 의 3토큰)과 2자 미만 제외는 두지 않는다 — 짝이
        없는 토큰이 점수를 내리므로 한 토큰이 전체를 대신하지 않는다. 양쪽 토큰이 하나씩이면 v1 과
        같은 값이다(①·② 모두 그 두 토큰의 유사도).

    orthographic_similarity("XSR", "XSL")                 # 0.667
    orthographic_similarity("스타벅스", "스타박스")           # 0.889
    orthographic_similarity("GATE HELLO", "GATE WORLD")    # 1.0
    orthographic_similarity("GATE HELLO", "GATE WORLD", version=2)   # 0.556
    has_spelling("★")                                     # False → X2 문자 외관 결측
"""

from __future__ import annotations

from .x1_phonetic import _decompose_syllable, _is_syllable, normalize_name

__all__ = ["orthographic_similarity", "has_spelling", "spelling_candidates", "spelling_tokens",
           "SPELLING_VERSIONS", "DEFAULT_SPELLING_VERSION", "LATEST_SPELLING_VERSION"]

# 분리관찰 상한 — X1 MAX_TOKENS_FOR_SPLIT 과 같다(4토큰 이상 슬로건형은 전체관찰). v1 만 쓴다.
MAX_TOKENS_FOR_SPLIT = 3
MIN_TOKEN_CHARS = 2
SPELLING_VERSIONS = (1, 2)
DEFAULT_SPELLING_VERSION = 1  # 기본값 — v1.3·v1.4 통합 모델과 지금 서비스의 정의
LATEST_SPELLING_VERSION = 2
TIE_BREAK = 1e-9  # 짝 유사도 합이 같을 때 덮개 점수가 큰 짝을 고르는 가중(합의 차이보다 아주 작다)


def _as_text(name: object) -> str:
    return "" if name is None else str(name)


def decompose_jamo(text: str) -> str:
    """완성형 한글 음절을 초성·중성(·종성) 자모로 푼다. 그 밖 글자는 그대로."""
    out: list[str] = []
    for char in text:
        if _is_syllable(char):
            cho, jung, jong = _decompose_syllable(char)
            out.append(cho)
            out.append(jung)
            if jong:
                out.append(jong)
        else:
            out.append(char)
    return "".join(out)


def _levenshtein(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(min(
                previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b)
            ))
        previous = current
    return previous[-1]


def _similarity(key_a: str, key_b: str) -> float:
    longest = max(len(key_a), len(key_b))
    if longest == 0:
        return 0.0
    return 1.0 - _levenshtein(key_a, key_b) / longest


def spelling_candidates(
    name: str, *, extra_generic: frozenset[str] = frozenset()
) -> list[str]:
    """비교 후보(자모로 푼 비교 키) 목록 — 전체 문자열 + 토큰(3토큰 이하, 2자 이상).
    디버깅·테스트용.

    Returns:
        후보 키 목록(중복 제거, 전체 문자열이 첫 항목). 글자 토큰이 없으면 빈 목록.
    """
    tokens = normalize_name(_as_text(name), extra_generic=frozenset(extra_generic))
    if not tokens:
        return []
    candidates = ["".join(tokens)]
    if len(tokens) <= MAX_TOKENS_FOR_SPLIT:
        candidates.extend(token for token in tokens if len(token) >= MIN_TOKEN_CHARS)
    keys: list[str] = []
    for candidate in candidates:
        key = decompose_jamo(candidate)
        if key and key not in keys:
            keys.append(key)
    return keys


def spelling_tokens(name: str, *, extra_generic: frozenset[str] = frozenset()) -> list[str]:
    """v2 의 비교 토큰(자모로 푼 비교 키, 이름 순서) — 정규화 + `extra_generic` 제거 뒤의 토큰 하나
    하나. 디버깅·테스트용."""
    tokens = normalize_name(_as_text(name), extra_generic=frozenset(extra_generic))
    return [key for key in (decompose_jamo(token) for token in tokens) if key]


def _assignment(weights: list[list[float]]) -> list[int]:
    """최대 가중 일대일 짝(행 수 ≤ 열 수): 행마다 짝지은 열 번호. 헝가리안 방법(표준 라이브러리만).
    가중이 모두 0 이상이라 행은 모두 짝을 얻는다."""
    rows, cols = len(weights), len(weights[0])
    infinity = float("inf")
    u = [0.0] * (rows + 1)
    v = [0.0] * (cols + 1)
    owner = [0] * (cols + 1)  # 열 j(1부터)에 짝지은 행(1부터), 0 = 없음
    way = [0] * (cols + 1)
    for row in range(1, rows + 1):
        owner[0] = row
        col0 = 0
        minimum = [infinity] * (cols + 1)
        used = [False] * (cols + 1)
        while True:
            used[col0] = True
            row0, delta, col1 = owner[col0], infinity, 0
            for col in range(1, cols + 1):
                if used[col]:
                    continue
                current = -weights[row0 - 1][col - 1] - u[row0] - v[col]
                if current < minimum[col]:
                    minimum[col], way[col] = current, col0
                if minimum[col] < delta:
                    delta, col1 = minimum[col], col
            for col in range(cols + 1):
                if used[col]:
                    u[owner[col]] += delta
                    v[col] -= delta
                else:
                    minimum[col] -= delta
            col0 = col1
            if owner[col0] == 0:
                break
        while True:
            col1 = way[col0]
            owner[col0] = owner[col1]
            col0 = col1
            if col0 == 0:
                break
    matched = [0] * rows
    for col in range(1, cols + 1):
        if owner[col]:
            matched[owner[col] - 1] = col - 1
    return matched


def _coverage(keys_a: list[str], keys_b: list[str]) -> float:
    """① 덮개 점수 — 일대일 짝(유사도 합 최대, 같으면 덮개 점수 최대)의 유사도를 글자 수로 가중
    평균, 짝 없는 토큰은 분모에만; A·B 양방향 평균. 인자 순서와 무관하게 같은 계산을 하도록 정렬해
    정준형으로 푼다(대칭)."""
    side_a, side_b = sorted(keys_a), sorted(keys_b)
    if (len(side_a), side_a) > (len(side_b), side_b):
        side_a, side_b = side_b, side_a  # 행 = 토큰이 적은 쪽(같으면 정렬 순서가 앞선 쪽)
    total_a = sum(len(key) for key in side_a)
    total_b = sum(len(key) for key in side_b)
    similarity = [[_similarity(a, b) for b in side_b] for a in side_a]
    weights = [[similarity[i][j] + TIE_BREAK * similarity[i][j]
                * (len(side_a[i]) / total_a + len(side_b[j]) / total_b) / 2
                for j in range(len(side_b))] for i in range(len(side_a))]
    matched = _assignment(weights)
    covered_a = sum(len(side_a[i]) * similarity[i][j] for i, j in enumerate(matched))
    covered_b = sum(len(side_b[j]) * similarity[i][j] for i, j in enumerate(matched))
    return (covered_a / total_a + covered_b / total_b) / 2


def _orthographic_v2(keys_a: list[str], keys_b: list[str]) -> float:
    """v2 = max(① 덮개 점수, ② 토큰을 이어 붙인 문자열끼리의 유사도)."""
    joined = _similarity("".join(keys_a), "".join(keys_b))
    return max(_coverage(keys_a, keys_b), joined)


def has_spelling(name: str, *, extra_generic: frozenset[str] = frozenset()) -> bool:
    """정규화 뒤 글자(한글·영문·숫자) 토큰이 하나라도 있으면 True. False(순수 도형·한자만·기호만)면
    X2 문자 외관을 결측 처리하고 다른 축만으로 판단한다(X1 의 has_pronunciation 과 같은 역할)."""
    return bool(normalize_name(_as_text(name), extra_generic=frozenset(extra_generic)))


def orthographic_similarity(
    name_a: str, name_b: str, *, extra_generic: frozenset[str] = frozenset(),
    version: int = DEFAULT_SPELLING_VERSION,
) -> float:
    """문자 외관(철자) 유사도. 0.0~1.0, 높을수록 유사. 대칭·결정적이며 어떤 문자열에도 예외 없이
    반환.

    v1: 양쪽 비교 후보(spelling_candidates)의 모든 쌍에 정규화 편집거리 유사도를 적용한 최댓값.
    v2: 요부 토큰의 덮개 점수와 이어 붙인 문자열 유사도의 최댓값(모듈 설명). 토큰이 한쪽이라도
    없으면 0.0 — 유사도 0 이 아니라 비교 불가의 뜻이므로 has_spelling 으로 먼저 거른다.

    Args:
        name_a: 상표명 A.
        name_b: 상표명 B.
        extra_generic: 양쪽에 공통으로 적용할 상품 의존 보통명칭 집합(X1 과 같은 의미·매칭).
        version: 철자 정의 버전(SPELLING_VERSIONS). 기본 1 — 통합 모델 JSON 의 `axis_versions`
            가 요구하는 버전을 넘긴다. 모르는 버전이면 ValueError.
    """
    if version not in SPELLING_VERSIONS:
        raise ValueError(f"x2_ortho: 철자 버전은 {SPELLING_VERSIONS} 중 하나여야 합니다: "
                         f"{version!r}")
    generic = frozenset(extra_generic)
    if version == 2:
        keys_a = spelling_tokens(_as_text(name_a), extra_generic=generic)
        keys_b = spelling_tokens(_as_text(name_b), extra_generic=generic)
        if not keys_a or not keys_b:
            return 0.0
        return _orthographic_v2(keys_a, keys_b)
    keys_a = spelling_candidates(_as_text(name_a), extra_generic=generic)
    keys_b = spelling_candidates(_as_text(name_b), extra_generic=generic)
    if not keys_a or not keys_b:
        return 0.0
    best = 0.0
    for key_a in keys_a:
        for key_b in keys_b:
            score = _similarity(key_a, key_b)
            if score > best:
                best = score
                if best >= 1.0:
                    return 1.0
    return best
