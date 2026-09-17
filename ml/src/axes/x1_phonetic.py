"""X1 호칭(발음) 유사도 축 — 상표법 판례의 호칭 유사 판단 규칙을 계산 가능한 함수로 옮긴다.

규약(docs/MarkLens_작업가이드_ML.md §공통-2): 입력은 상표명 문자열 2개, 출력은 0.0~1.0
float(높을수록 유사). 순수 함수 — 파일·네트워크·전역 가변 상태 없음(결과 메모이즈만 허용).
torch·faiss·backend 를 import 하지 않고 표준 라이브러리만 사용한다.

판례 5규칙 → 구현 매핑
    ① 호칭이 가장 중요하다
        → 이 축이 통합 모델(로지스틱 회귀)의 중심 축이다. X1 내부 구현과는 무관하며
          통합 모델 담당자가 가중치 해석 시 참고할 사항으로 기록한다.
    ② 짧은 상표는 첫음절이 강조된다
        → 음절 위치별 비용 가중치 POSITION_WEIGHTS. "첫음절 2배"를 기준선으로 두고
          음절 수가 적을수록 앞 음절 가중을 더 올린다(2음절 이하 3배, 3~4음절 2배,
          5음절 이상 1.5배). 가중치는 두 문자열 중 긴 쪽 음절 수로 정한다.
    ③ 여러 호칭 중 하나만 유사해도 유사하다
        → 상표명 하나에서 발음 후보를 여러 개 만들고(pronunciation_candidates),
          양쪽 후보의 모든 쌍에 _syllable_sim 을 적용한 최댓값을 채택한다.
    ④ 외국어는 국내 거래자의 자연스러운 발음으로 부른다
        → 영문 토큰을 한글 발음으로 변환한다(_g2p_word: 국내 브랜드·지명 로마자 표
          (korean_brands) → 예외 사전 → 외래어 표기법 근사 룰). 3자 이하이거나 모음이 없는
          토큰은 알파벳 낱자 읽기(LETTER_READINGS)도 후보에 넣는다.
    ⑤ 한영 병기 시 한글을 우선한다
        → 영문 읽기가 한글 토큰과 사실상 같으면(PAIRED_THRESHOLD 이상) 병기로 보고 영문
          읽기를 버린다(_apply_paired_rule). 토큰 단위와 구 단위 두 번 판정한다.
    추가 법리
    - 분리관찰(일부만으로도 호칭될 수 있다)
        → 제거 후 각 토큰의 2음절 이상 읽기를 독립 후보로 넣는다. 단, 알파벳·숫자 1글자
          토큰에서 나온 읽기("K"→케이)는 제외한다(무관한 상표를 1.0 으로 만드는 오탐 방지).
    - 불가분 결합의 예외(전체로만 불러야 하는 경우)
        → 제거 전 토큰 전체를 이어붙인 결합음을 항상 후보에 유지한다.
    - 요부관찰(식별력 없는 부분은 제외하고 대비)
        → 회사 형태·부가어·영문 기능어(UNIVERSAL_GENERIC)와 호출자가 넘기는 상품 의존
          보통명칭(extra_generic)을 토큰 완전일치로 제거한다.

알려진 한계(v1): 한자 토큰 미지원(버림), G2P 는 외래어 표기법 근사, 붙여쓴 결합어는 분리하지
못함, 보통명칭 판단은 extra_generic 에 의존, 불가분 결합은 "전체 결합음 유지"로 근사.
"""

import functools
import itertools
import re
import unicodedata
from typing import Final

from .korean_brands import KOREAN_BRAND_ROMANIZATION, KOREAN_PLACE_ROMANIZATION

__all__ = ["phonetic_similarity", "has_pronunciation", "pronunciation_candidates"]


# =====================================================================================
# 설계 상수 (검토·조정 대상) — 초기 추천값. 각 항목의 근거는 주석의 판례 번호를 참고한다.
# =====================================================================================

# 요부관찰: 상품과 무관하게 식별력이 없는 토큰. 토큰 완전일치일 때만 제거한다(한·영 모두).
UNIVERSAL_GENERIC: Final[frozenset[str]] = frozenset(
    {
        # 회사 형태
        "주식회사", "유한회사", "합자회사", "co", "ltd", "inc", "corp", "corporation",
        "company", "llc", "gmbh", "plc", "limited",
        # 부가어
        "코리아", "korea", "인터내셔널", "international", "글로벌", "global", "그룹", "group",
        "컴퍼니", "홀딩스", "holdings",
        # 영문 기능어
        "the", "a", "an", "of", "and", "for", "by",
    }
)

# ④ G2P 예외 사전 — 룰로 맞추기 어려운 불규칙(기능어·수사·약어·외래어 관용 표기).
#    벤치마크는 g2p_benchmark(순수 룰)로 재므로 여기 넣어도 20단어 측정은 오르지 않는다
#    (테스트가 검증).
G2P_EXCEPTIONS: Final[dict[str, str]] = {
    "the": "더",
    "to": "투",
    "you": "유",
    "we": "위",
    "me": "미",
    "be": "비",
    "he": "히",
    "she": "시",
    "cafe": "카페",
    "one": "원",
    "two": "투",
    "three": "쓰리",
    "four": "포",
    "five": "파이브",
    "six": "식스",
    "eight": "에이트",
    "nine": "나인",
    "ten": "텐",
    "eleven": "일레븐",
    "twelve": "트웰브",
    "new": "뉴",
    "and": "앤드",
    "lg": "엘지",
    "tv": "티브이",
    # 외래어 관용 표기(룰과 다르게 굳어진 읽기). 2026-09-17 로마자 캐기 결과에서 승인.
    "pilates": "필라테스",
    "ballet": "발레",
    "etoile": "에뜨왈",
    "curry": "카레",
    "atelier": "아틀리에",
    "gourmet": "구르메",
    "poke": "포케",
    "musical": "뮤지컬",
    "salon": "살롱",
    "baseball": "베이스볼",
    "together": "투게더",
    "coffee": "커피",  # 룰의 o→ㅗ 기본값(코피)이 맞지 않는 불규칙. 2026-09-17 결정
}
# 국내 브랜드·지명 로마자(samsung→삼성, seoul→서울)는 korean_brands 의 두 표에서 관리한다.

# ④ 알파벳 낱자 읽기. r 은 "알"이 기본이고 "아르"를 추가 후보로 둔다.
LETTER_READINGS: Final[dict[str, str]] = {
    "a": "에이", "b": "비", "c": "씨", "d": "디", "e": "이", "f": "에프", "g": "지",
    "h": "에이치", "i": "아이", "j": "제이", "k": "케이", "l": "엘", "m": "엠", "n": "엔",
    "o": "오", "p": "피", "q": "큐", "r": "알", "s": "에스", "t": "티", "u": "유",
    "v": "브이", "w": "더블유", "x": "엑스", "y": "와이", "z": "제트",
}
LETTER_READINGS_ALT: Final[dict[str, str]] = {"r": "아르"}

# 낱자 읽기를 추가하는 영문 토큰 길이 상한(이하). 모음이 없는 토큰은 길이와 무관하게 추가.
# v1 의 5 는 4~5자 일반 단어(the, face)에도 낱자 읽기를 붙여 후보만 늘렸다 → 3 으로 낮춤.
LETTER_READING_MAX_LEN: Final = 3

# ⑤ 병기 판정 임계값: 영문 읽기와 한글 토큰의 음절 유사도가 이 값 이상이면 병기로 본다.
PAIRED_THRESHOLD: Final = 0.8

# ③ 결합음 후보 조합 수 상한. 넘으면 결합음은 토큰별 첫 읽기만 쓴다(토큰 후보는 전부 유지).
MAX_CANDIDATES: Final = 16

# 후보·비교에 쓰는 음절 수 상한(앞에서부터).
MAX_SYLLABLES: Final = 40

# ② 음절 위치별 가중치. 긴 쪽 음절 수 n 으로 고른다. "첫음절 2배"가 기준선이며 짧을수록 강조.
#    - n<=2 : 첫음절 3배, 둘째 1.5배 (2음절 상표는 첫음절이 사실상 전부)
#    - 3~4  : 첫음절 2배, 둘째 1.5배, 나머지 1배 (판례 기준선)
#    - n>=5 : 첫음절 1.5배, 둘째 1.2배, 나머지 1배 (긴 상표는 앞음절 강세가 상대적으로 약함)
POSITION_WEIGHTS: Final[dict[str, tuple[float, ...]]] = {
    "n<=2": (3.0, 1.5),
    "3<=n<=4": (2.0, 1.5, 1.0, 1.0),
    "n>=5_head": (1.5, 1.2),  # 이후 음절은 1.0
}

# 유사 자모(치환 비용 절반). 한 자모가 여러 쌍에 속할 수 있어 "쌍의 집합"으로 정의한다.
# 음성학적 근거: 같은 조음 위치의 평음·격음·경음(기식·긴장만 다름), (ㅅ,ㅆ) 긴장 차이,
# (ㄹ,ㄴ) 같은 치경음 유음·비음, (ㄴ,ㅁ) 비음끼리(치경·양순) — 청자가 흔히 혼동한다.
CHO_SIMILAR_GROUPS: Final[tuple[tuple[str, ...], ...]] = (
    ("ㄱ", "ㅋ", "ㄲ"), ("ㄷ", "ㅌ", "ㄸ"), ("ㅂ", "ㅍ", "ㅃ"), ("ㅈ", "ㅊ", "ㅉ"), ("ㅅ", "ㅆ"),
    ("ㄹ", "ㄴ"), ("ㄴ", "ㅁ"),
)
CHO_SIMILAR_PAIRS: Final[frozenset[frozenset[str]]] = frozenset(
    frozenset(pair) for group in CHO_SIMILAR_GROUPS for pair in itertools.combinations(group, 2)
)
# 중성 유사(0.5): 인접 모음(ㅓㅏ, ㅗㅜ, ㅡㅜ)과 반모음(y/w)만 다르고 핵모음이 같은 쌍
# (ㅑ=y+ㅏ, ㅕ=y+ㅓ, ㅛ=y+ㅗ, ㅠ=y+ㅜ / ㅘ=w+ㅏ, ㅝ=w+ㅓ, ㅙ=w+ㅐ, ㅞ=w+ㅔ, ㅚ≈w+ㅔ, ㅟ=w+ㅣ).
JUNG_SIMILAR_PAIRS: Final[frozenset[frozenset[str]]] = frozenset(
    frozenset(pair)
    for pair in (
        ("ㅓ", "ㅏ"), ("ㅗ", "ㅜ"), ("ㅡ", "ㅜ"), ("ㅕ", "ㅑ"), ("ㅝ", "ㅘ"),
        ("ㅑ", "ㅏ"), ("ㅕ", "ㅓ"), ("ㅛ", "ㅗ"), ("ㅠ", "ㅜ"),
        ("ㅘ", "ㅏ"), ("ㅝ", "ㅓ"), ("ㅙ", "ㅐ"), ("ㅞ", "ㅔ"), ("ㅚ", "ㅔ"), ("ㅟ", "ㅣ"),
    )
)
# 중성 합류(COST_JUNG_MERGED): 현대 서울말에서 발음이 완전히 합류해 청각적으로 구별되지 않는 쌍
# (ㅐ/ㅔ, ㅒ/ㅖ, ㅙ/ㅞ/ㅚ). 유사(0.5)보다 낮은 별도 단계.
JUNG_MERGED_PAIRS: Final[frozenset[frozenset[str]]] = frozenset(
    frozenset(pair)
    for pair in (("ㅐ", "ㅔ"), ("ㅒ", "ㅖ"), ("ㅙ", "ㅞ"), ("ㅙ", "ㅚ"), ("ㅞ", "ㅚ"))
)
# 종성 대표음 그룹(서로 배타적, 첫 원소가 대표음). 같은 그룹이면 발음이 같다(예: 낚/낙/낟...).
JONG_REP_GROUPS: Final[tuple[tuple[str, ...], ...]] = (
    ("ㄱ", "ㄲ", "ㅋ", "ㄳ", "ㄺ"), ("ㄴ", "ㄵ", "ㄶ"), ("ㄷ", "ㅅ", "ㅆ", "ㅈ", "ㅊ", "ㅌ", "ㅎ"),
    ("ㄹ", "ㄼ", "ㄽ", "ㄾ", "ㅀ"), ("ㅁ", "ㄻ"), ("ㅂ", "ㅍ", "ㅄ", "ㄿ"), ("ㅇ",),
)
# 종성 비음(0.25): 양쪽 받침의 대표음이 모두 비음이면 위치동화로 서로 넘나든다
# (신문→[심문], 한강→[항강]). JONG_REP_GROUPS 의 같은/다른 그룹 규칙보다 우선한다.
JONG_NASAL: Final[frozenset[str]] = frozenset({"ㄴ", "ㅁ", "ㅇ"})
#
# 검토 대기(정답 데이터로 검증 후 결정 — 지금은 넣지 않음): (ㅎ,ㅇ), (ㅡ,ㅓ), (ㅡ,ㅣ),
# 종성 불파음 ㄱ/ㄷ/ㅂ 간 유사. docs/MarkLens_X1_호칭유사도_설계.md "검토 대기" 절 참고.

# 비용 상수. 치환 비용 최대 = 1.0 + 1.0 + 0.5 = 2.5 이고 삽입·삭제 비용은 이와 같게 둔다.
COST_CHO_SIMILAR: Final = 0.5
COST_CHO_DIFF: Final = 1.0
# 합류 모음은 청감상 동일. 0.1 은 정확 일치가 순위에서 앞서도록 남기는 최소 비용(2026-09-17 결정).
COST_JUNG_MERGED: Final = 0.1
COST_JUNG_SIMILAR: Final = 0.5
COST_JUNG_DIFF: Final = 1.0
COST_JONG_NASAL: Final = 0.25
COST_JONG_SAME_GROUP: Final = 0.25
COST_JONG_ONE_SIDE: Final = 0.5
COST_JONG_DIFF_GROUP: Final = 0.5
COST_INDEL: Final = 2.5


# =====================================================================================
# 한글 자모 산술
# =====================================================================================

_CHO: Final = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG: Final = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG: Final = "\0ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"  # 0 = 받침 없음
_HANGUL_BASE: Final = 0xAC00
_HANGUL_LAST: Final = 0xD7A3

# 받침 자모 → 대표음(그룹 첫 원소)
_JONG_REP_OF: Final[dict[str, str]] = {
    jamo: group[0] for group in JONG_REP_GROUPS for jamo in group
}


def _is_syllable(ch: str) -> bool:
    return _HANGUL_BASE <= ord(ch) <= _HANGUL_LAST


def _decompose_syllable(ch: str) -> tuple[str, str, str | None]:
    code = ord(ch) - _HANGUL_BASE
    jong = code % 28
    return _CHO[code // 588], _JUNG[(code % 588) // 28], (_JONG[jong] if jong else None)


def _compose(cho: str, jung: str, jong: str | None) -> str:
    return chr(
        _HANGUL_BASE + _CHO.index(cho) * 588 + _JUNG.index(jung) * 28
        + (_JONG.index(jong) if jong else 0)
    )


def _syllables_only(text: str) -> str:
    return "".join(ch for ch in text if _is_syllable(ch))


# =====================================================================================
# 1. 정규화
# =====================================================================================

# NFKC 가 ™ 을 "TM" 글자로 바꾸므로 상표 기호는 정규화 전에 먼저 지운다.
_TRADEMARK_SYMBOLS: Final = str.maketrans("", "", "®™℠©")
# 회사표시 기호. ㈜ 는 NFKC 로 "(주)" 가 되므로 NFKC 뒤에 정규식 한 번으로 처리한다.
_COMPANY_MARK_RE: Final = re.compile(r"\(\s*(?:주|유|합|합자|유한|재|사|의)\s*\)")


def _char_class(ch: str) -> str:
    """H(한글) / L(영문 소문자) / D(숫자) / O(그 외: 한자·이모지·기타 문자)."""
    code = ord(ch)
    if _HANGUL_BASE <= code <= _HANGUL_LAST or 0x3131 <= code <= 0x318E or 0x1100 <= code <= 0x11FF:
        return "H"
    if "a" <= ch <= "z":
        return "L"
    if "0" <= ch <= "9":
        return "D"
    return "O"


def _clean_chars(text: str) -> str:
    """기호·구두점·공백류 → 공백, 결합 부호 제거, 라틴 확장 글자 → 기본 글자(é→e)."""
    out: list[str] = []
    for ch in text:
        category = unicodedata.category(ch)
        head = category[0]
        if head in ("P", "S", "Z", "C"):
            out.append(" ")
            continue
        if head == "M":
            continue
        if head == "L" and _char_class(ch) == "O" and ord(ch) < 0x2E80:
            base = unicodedata.normalize("NFD", ch)[0]
            out.append(base if "a" <= base <= "z" else ch)
            continue
        out.append(ch)
    return "".join(out)


def _tokenize(text: str) -> list[str]:
    """공백 토큰화 후 문자 종류(한글/영문/숫자) 경계로 분리한다. 그 외 문자 토큰은 버린다."""
    tokens: list[str] = []
    for raw in text.split():
        run: list[str] = []
        run_class = ""
        for ch in raw:
            cls = _char_class(ch)
            if cls != run_class:
                if run and run_class != "O":
                    tokens.append("".join(run))
                run, run_class = [], cls
            run.append(ch)
        if run and run_class != "O":
            tokens.append("".join(run))
    return tokens


def _basic_normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text.translate(_TRADEMARK_SYMBOLS)).casefold()


@functools.lru_cache(maxsize=256)
def _generic_sets(
    extra_generic: frozenset[str],
) -> tuple[frozenset[str], tuple[tuple[str, ...], ...]]:
    """extra_generic 항목을 상표명과 같은 정규화·토큰화로 바꾼다 (단일 토큰 / 다중 토큰 열)."""
    singles = set(UNIVERSAL_GENERIC)
    sequences: list[tuple[str, ...]] = []
    for item in extra_generic:
        tokens = _tokenize(_clean_chars(_basic_normalize(str(item))))
        if len(tokens) == 1:
            singles.add(tokens[0])
        elif len(tokens) > 1:
            sequences.append(tuple(tokens))
    return frozenset(singles), tuple(sequences)


def _remove_generic(
    tokens: list[str], singles: frozenset[str], sequences: tuple[tuple[str, ...], ...]
) -> list[str]:
    kept: list[str] = []
    index = 0
    while index < len(tokens):
        matched = next(
            (seq for seq in sequences if tuple(tokens[index : index + len(seq)]) == seq), None
        )
        if matched is not None:
            index += len(matched)
            continue
        if tokens[index] not in singles:
            kept.append(tokens[index])
        index += 1
    return kept


def _normalize_tokens(name: str, extra_generic: frozenset[str]) -> tuple[list[str], list[str]]:
    """상표명 → (제거 전 토큰, 제거 후 토큰).

    순서: NFKC·casefold → 회사표시 기호 제거 → 기호를 공백으로 → 토큰화(문자 종류 경계 분리,
    한자·기타 문자 토큰 제거) → 연속 중복 토큰 제거(=제거 전) → 보통명칭 제거(=제거 후).
    제거 후가 비면 제거 전을 그대로 쓴다(빈 문자열 방지).
    """
    text = _COMPANY_MARK_RE.sub(" ", _basic_normalize(name))
    tokens = _tokenize(_clean_chars(text))
    pre = [tok for index, tok in enumerate(tokens) if index == 0 or tok != tokens[index - 1]]
    singles, sequences = _generic_sets(extra_generic)
    post = _remove_generic(pre, singles, sequences)
    if not post:
        post = list(pre)
    return pre, post


# =====================================================================================
# 2. 토큰별 발음 — 영문 G2P(외래어 표기법 근사 룰), 알파벳 낱자, 숫자
# =====================================================================================

_VOWELS: Final = "aeiou"
_VOWEL_GROUP_RE: Final = re.compile(r"[aeiouy]+")

# 자음 종류 → (초성, 받침 가능 자모). 받침이 None 이면 받침으로 쓰지 않는다.
_CONSONANTS: Final[dict[str, tuple[str | None, str | None]]] = {
    "p": ("ㅍ", "ㅂ"), "t": ("ㅌ", "ㅅ"), "k": ("ㅋ", "ㄱ"),  # 무성 파열음: 짧은 모음 뒤 받침
    "b": ("ㅂ", None), "d": ("ㄷ", None), "g": ("ㄱ", None),  # 유성 파열음: 항상 '으' 붙임
    "m": ("ㅁ", "ㅁ"), "n": ("ㄴ", "ㄴ"), "ng": (None, "ㅇ"),
    "l": ("ㄹ", "ㄹ"), "r": ("ㄹ", None),
    "s": ("ㅅ", None), "z": ("ㅈ", None), "f": ("ㅍ", None), "v": ("ㅂ", None),
    "th": ("ㅅ", None), "sh": ("ㅅ", None), "ch": ("ㅊ", None), "j": ("ㅈ", None),
    "ts": ("ㅊ", None), "h": ("ㅎ", None), "q": ("ㅋ", None), "w": (None, None), "y": (None, None),
}
# 모음 없이 홀로 설 때 붙이는 모음(기본 ㅡ). sh/ch/j 는 시/치/지.
_EPS_VOWEL: Final[dict[str, str]] = {"sh": "ㅣ", "ch": "ㅣ", "j": "ㅣ"}
_W_GLIDE: Final[dict[str, str]] = {
    "ㅏ": "ㅝ", "ㅐ": "ㅙ", "ㅓ": "ㅝ", "ㅔ": "ㅞ", "ㅗ": "ㅝ", "ㅜ": "ㅜ", "ㅡ": "ㅜ", "ㅣ": "ㅟ",
}
_Y_GLIDE: Final[dict[str, str]] = {
    "ㅏ": "ㅑ", "ㅐ": "ㅒ", "ㅓ": "ㅕ", "ㅔ": "ㅖ", "ㅗ": "ㅛ", "ㅜ": "ㅠ", "ㅡ": "ㅠ",
}
_SH_GLIDE: Final[dict[str, str]] = {
    "ㅏ": "ㅑ", "ㅐ": "ㅒ", "ㅓ": "ㅕ", "ㅔ": "ㅖ", "ㅗ": "ㅛ", "ㅜ": "ㅠ", "ㅡ": "ㅣ",
}
_DOUBLE_LETTERS: Final = frozenset("bdfgklmnprstz")
_A_FRONT_PATTERNS: Final = (
    "ack", "ax", "ash", "atch", "ach", "ath", "ank", "and", "ant", "amp", "ang", "act", "apt",
    "aft",
)


class _Seg:
    """G2P 중간 표현: 모음(V) 또는 자음(C) 한 단위."""

    __slots__ = ("type", "kind", "onset", "coda", "jung", "short")

    def __init__(self, seg_type: str, kind: str = "", jung: str = "", short: bool = False):
        self.type = seg_type
        self.kind = kind
        self.jung = jung
        self.short = short
        onset, coda = _CONSONANTS.get(kind, (None, None))
        self.onset = onset
        self.coda = coda


def _v(jung: str, short: bool = False) -> _Seg:
    return _Seg("V", jung=jung, short=short)


def _c(kind: str) -> _Seg:
    return _Seg("C", kind=kind)


def _g_is_soft(word: str, index: int) -> bool:
    """g 가 ㅈ 소리인지. e/y 앞은 ㅈ(어말 -ger/-get 제외), i 앞은 gin/gia/gic/git 형만 ㅈ."""
    nxt = word[index + 1 : index + 2]
    if nxt in ("e", "y"):
        hard_tail = (index == len(word) - 3 and word.endswith(("ger", "get"))) or (
            index == len(word) - 4 and word.endswith(("gers", "gets"))
        )
        return not hard_tail
    if nxt == "i":
        return word[index + 2 : index + 3] in ("n", "a", "c", "t")
    return False


def _scan_vowel(word: str, index: int, silent_e: int, multi: bool) -> tuple[list[_Seg], int]:
    """모음 글자 위치에서 (모음 세그먼트들, 소비한 글자 수)를 돌려준다. 외래어 표기법 근사."""
    n = len(word)
    c = word[index]
    prev = word[index - 1] if index > 0 else ""

    def ch(k: int) -> str:
        return word[index + k] if index + k < n else ""

    def at_end(k: int) -> bool:
        return index + k >= n or index + k == silent_e

    def is_v(x: str) -> bool:
        return x != "" and x in _VOWELS

    def is_c(x: str) -> bool:
        return x != "" and x not in _VOWELS

    def starts(*patterns: str) -> bool:
        return word.startswith(patterns, index)

    def suffix_at(k: int, *suffixes: str) -> bool:
        """index+k 부터 접미사 중 하나로 단어가 끝나는지 (maker 의 'er', making 의 'ing')."""
        return any(
            word.startswith(sfx, index + k) and index + k + len(sfx) >= n for sfx in suffixes
        )

    groups_before = len(_VOWEL_GROUP_RE.findall(word[:index]))

    if c == "o":
        if starts("ould") and at_end(4):
            return [_v("ㅜ")], 3  # would 우드, should 슈드
        if starts("our") and at_end(3):
            return [_v("ㅜ"), _v("ㅓ")], 3
        if starts("ower") and at_end(4):
            return [_v("ㅏ"), _v("ㅝ")], 4
        if starts("ow"):
            if at_end(2) or is_v(ch(2)):
                return [_v("ㅗ")], 2
            return [_v("ㅏ"), _v("ㅜ", True)], 2
        if starts("oor") and at_end(3):
            return [_v("ㅗ"), _v("ㅓ")], 3
        if starts("oo"):
            return [_v("ㅜ", True)], 2
        if starts("oa"):
            return [_v("ㅗ")], 2
        if starts("oi", "oy"):
            return [_v("ㅗ"), _v("ㅣ")], 2
        if starts("ous") and index + 3 >= n and multi:
            return [_v("ㅓ")], 2  # famous 페이머스 (house 는 단음절이라 제외)
        if starts("ou"):
            return [_v("ㅏ"), _v("ㅜ", True)], 2
        if starts("ore") and at_end(3):
            return [_v("ㅗ"), _v("ㅓ")], 3
        if starts("or"):
            if at_end(2):
                return [_v("ㅓ" if multi else "ㅗ")], 2
            if ch(2) == "s" and at_end(3):
                return [_v("ㅓ")], 2
            if is_v(ch(2)):
                return [_v("ㅗ")], 1
            return [_v("ㅗ")], 2
        return [_v("ㅗ", True)], 1

    if c == "a":
        if starts("air") and (at_end(3) or is_c(ch(3))):
            return [_v("ㅔ"), _v("ㅓ")], 3
        if starts("ay", "ai"):
            return [_v("ㅔ"), _v("ㅣ")], 2
        if starts("au", "aw"):
            return [_v("ㅗ")], 2
        if starts("are") and at_end(3):
            return [_v("ㅔ"), _v("ㅓ")], 3
        if starts("arr") and is_v(ch(3)):
            return [_v("ㅐ")], 1
        if starts("ar"):
            return ([_v("ㅏ")], 1) if is_v(ch(2)) else ([_v("ㅏ")], 2)
        if starts("all") and (at_end(3) or is_c(ch(3))):
            return [_v("ㅗ")], 1
        if starts("al") and at_end(2) and multi:
            return [_v("ㅓ")], 1
        c1, c2 = ch(1), ch(2)
        if is_c(c1) and c1 != "y" and index + 2 == silent_e:  # a + 자음 + 어말 e
            return [_v("ㅔ"), _v("ㅣ")], 1
        if (
            is_c(c1)
            and c1 not in ("y", "w", "g")
            and prev != "w"
            and suffix_at(2, "er", "ers", "ed", "es", "ing")
        ):
            return [_v("ㅔ"), _v("ㅣ")], 1  # maker 메이커, paper 페이퍼, making 메이킹
        if index == 0 and is_c(c1):
            return [_v("ㅐ", True)], 1
        if c1 and c1 == c2 and c1 in _DOUBLE_LETTERS:
            return [_v("ㅐ", True)], 1
        if is_c(c1) and c1 != "y" and word.startswith("le", index + 2) and at_end(4):
            return [_v("ㅔ"), _v("ㅣ")], 1  # table 테이블
        if starts(*_A_FRONT_PATTERNS):
            return [_v("ㅐ", True)], 1
        if c1 in ("m", "n") and is_c(c2):
            return [_v("ㅐ", True)], 1
        if is_c(c1) and c1 != "y" and at_end(2):
            return [_v("ㅐ", True)], 1
        return [_v("ㅏ", True)], 1

    if c == "e":
        if starts("ear"):
            return ([_v("ㅣ"), _v("ㅓ")], 3) if at_end(3) else ([_v("ㅓ")], 3)
        if starts("eer"):
            return [_v("ㅣ"), _v("ㅓ")], 3
        if starts("ee"):
            return [_v("ㅣ")], 2
        if starts("ea"):
            if at_end(2) and multi:
                return [_v("ㅣ"), _v("ㅏ")], 2
            return [_v("ㅣ")], 2
        if starts("ey") and at_end(2):
            return ([_v("ㅣ")], 2) if multi else ([_v("ㅔ"), _v("ㅣ")], 2)
        if starts("ei"):
            return [_v("ㅔ"), _v("ㅣ")], 2
        if starts("ew", "eu"):
            return [_v("ㅠ")], 2
        if starts("ere") and at_end(3):
            return [_v("ㅣ"), _v("ㅓ")], 3
        if starts("er"):
            return ([_v("ㅔ")], 1) if is_v(ch(2)) else ([_v("ㅓ")], 2)
        if is_c(ch(1)) and ch(1) != "y" and index + 2 == silent_e:  # e + 자음 + 어말 e
            return [_v("ㅣ")], 1
        if starts("en") and at_end(2) and multi and is_c(prev):
            if word.endswith(("cken", "chen", "tchen")):
                return [_v("ㅣ")], 1  # chicken 치킨
            return [_v("ㅡ")], 1  # seven 세븐
        return [_v("ㅔ", True)], 1

    if c == "i":
        if starts("igh"):
            return [_v("ㅏ"), _v("ㅣ")], 3
        if starts("ie"):
            if at_end(2):
                return ([_v("ㅣ")], 2) if multi else ([_v("ㅏ"), _v("ㅣ")], 2)
            return [_v("ㅣ")], 2
        if starts("ire") and at_end(3):
            return [_v("ㅏ"), _v("ㅣ"), _v("ㅓ")], 3
        if starts("ir"):
            return ([_v("ㅣ")], 1) if is_v(ch(2)) else ([_v("ㅓ")], 2)
        if starts("ind", "ild", "ign") and at_end(3):
            return [_v("ㅏ"), _v("ㅣ")], 1
        if is_c(ch(1)) and ch(1) != "y" and index + 2 == silent_e:  # i + 자음 + 어말 e
            if word[index:] in ("ice", "ine", "ite", "ive") and groups_before >= 1:
                return [_v("ㅣ")], 1  # office 오피스, machine 머신
            return [_v("ㅏ"), _v("ㅣ")], 1
        if is_c(ch(1)) and ch(1) != "y" and word.startswith("le", index + 2) and at_end(4):
            return [_v("ㅏ"), _v("ㅣ")], 1  # title 타이틀
        if is_c(ch(1)) and ch(1) not in ("y", "w") and suffix_at(2, "er", "ers", "ed", "es", "ing"):
            return [_v("ㅏ"), _v("ㅣ")], 1  # tiger 타이거, rider 라이더, riding 라이딩
        return [_v("ㅣ", True)], 1

    if c == "u":
        if starts("uy"):
            return [_v("ㅏ"), _v("ㅣ")], 2
        if starts("ure") and at_end(3):
            return [_v("ㅠ"), _v("ㅓ")], 3
        if starts("ur") and not is_v(ch(2)):
            return [_v("ㅓ")], 2
        if starts("ue"):
            return [_v("ㅜ" if prev in ("l", "r", "j") else "ㅠ")], 2
        if starts("ui"):
            return [_v("ㅣ" if prev == "b" else "ㅜ")], 2
        if starts("ull"):
            return [_v("ㅜ")], 1
        if is_c(ch(1)) and ch(1) != "y" and index + 2 == silent_e:  # u + 자음 + 어말 e
            return [_v("ㅜ" if prev in ("r", "l", "j") else "ㅠ")], 1
        if at_end(1):
            return [_v("ㅜ" if prev in ("r", "l", "j", "f", "w") else "ㅠ")], 1
        if is_c(ch(1)) and ch(1) != "y" and is_v(ch(2)):  # 개음절: 뮤직, 스튜디오
            return [_v("ㅜ" if prev in ("r", "l", "j") else "ㅠ")], 1
        return [_v("ㅓ", True)], 1

    # y 를 모음으로 읽는 경우
    if at_end(1):
        return ([_v("ㅣ")], 1) if groups_before >= 1 else ([_v("ㅏ"), _v("ㅣ")], 1)
    if is_c(ch(1)) and index + 2 == silent_e:
        return [_v("ㅏ"), _v("ㅣ")], 1  # type, style
    if is_c(ch(1)) and is_v(ch(2)) and prev != "h":
        return [_v("ㅏ"), _v("ㅣ")], 1  # dynamic, cycle
    return [_v("ㅣ", True)], 1


def _scan(word: str) -> list[_Seg]:
    """영문 소문자 단어 → 세그먼트 열. 접미·자음군·묵음 규칙을 여기서 처리한다."""
    n = len(word)
    segs: list[_Seg] = []
    groups = len(_VOWEL_GROUP_RE.findall(word))
    multi = groups >= 2
    # 어말 묵음 e: 자음 뒤 어말 e 이고 그 앞에 다른 모음 글자군이 있을 때
    silent_e = -1
    if n >= 3 and word[-1] == "e" and word[-2] not in _VOWELS and word[-2] != "y":
        if _VOWEL_GROUP_RE.search(word[:-1]):
            silent_e = n - 1
    index = 0
    while index < n:
        if index == silent_e:
            index += 1
            continue
        c = word[index]
        nxt = word[index + 1] if index + 1 < n else ""
        prev = word[index - 1] if index > 0 else ""
        rest = word[index:]

        def at_end(k: int, index: int = index) -> bool:
            return index + k >= n or index + k == silent_e

        # ----- y: 활음(어두 또는 모음 뒤, 모음 앞) vs 모음 -----
        if c == "y":
            if nxt in _VOWELS and (index == 0 or prev in _VOWELS):
                segs.append(_c("y"))
                index += 1
                continue
            units, used = _scan_vowel(word, index, silent_e, multi)
            segs.extend(units)
            index += used
            continue
        if c in _VOWELS:
            units, used = _scan_vowel(word, index, silent_e, multi)
            segs.extend(units)
            index += used
            continue

        # ----- 접미 패턴 -----
        if rest.startswith("tion") and at_end(4):
            segs.extend([_c("ch" if prev == "s" else "sh"), _v("ㅓ"), _c("n")])
            index += 4
            continue
        if rest.startswith("ssion") and at_end(5):
            segs.extend([_c("sh"), _v("ㅓ"), _c("n")])
            index += 5
            continue
        if rest.startswith("sion") and at_end(4):
            segs.extend([_c("sh" if prev in ("n", "l") else "j"), _v("ㅓ"), _c("n")])
            index += 4
            continue
        if rest.startswith("ture") and at_end(4) and multi:
            segs.extend([_c("ch"), _v("ㅓ")])
            index += 4
            continue
        if rest.startswith("sure") and at_end(4) and multi:
            segs.extend([_c("j"), _v("ㅓ")])
            index += 4
            continue
        if rest.startswith("ci") and word[index + 2 : index + 3] in ("a", "o", "u") and groups >= 2:
            segs.append(_c("sh"))  # social 소셜, delicious 딜리셔스
            index += 1
            continue
        if rest.startswith("ts") and at_end(2):
            segs.append(_c("ts"))  # sports 스포츠, parts 파츠
            index += 2
            continue
        if rest.startswith("ds") and at_end(2):
            segs.append(_c("z"))  # kids 키즈, friends 프렌즈
            index += 2
            continue

        # ----- 여러 글자 자음 -----
        if rest.startswith("tch"):
            segs.append(_c("ch"))
            index += 3
            continue
        if rest.startswith("sch"):
            segs.extend([_c("s"), _c("k")])
            index += 3
            continue
        if rest.startswith("chr"):
            segs.append(_c("k"))
            index += 2
            continue
        if rest.startswith("ch"):
            segs.append(_c("ch"))
            index += 2
            continue
        if rest.startswith("sh"):
            segs.append(_c("sh"))
            index += 2
            continue
        if rest.startswith("th"):
            segs.append(_c("th"))
            index += 2
            continue
        if rest.startswith("ph"):
            segs.append(_c("f"))
            index += 2
            continue
        if rest.startswith("gh"):
            if segs and segs[-1].type == "V":
                index += 2  # light, high: 묵음
            else:
                segs.append(_c("g"))
                index += 2
            continue
        if rest.startswith("ck"):
            segs.append(_c("k"))
            index += 2
            continue
        if rest.startswith("que") and at_end(3):
            segs.append(_c("k"))  # boutique 부티크
            index += 3
            continue
        if rest.startswith("qu"):
            segs.append(_c("q") if word[index + 2 : index + 3] in _VOWELS else _c("k"))
            index += 2
            continue
        if rest.startswith("ng"):
            if word[index + 2 : index + 3] == "e":
                segs.append(_c("n"))  # orange: n + 연음 g
                index += 1
            else:
                segs.append(_c("ng"))
                index += 2
            continue
        if rest.startswith("nk"):
            segs.extend([_c("ng"), _c("k")])  # bank 뱅크
            index += 2
            continue
        if rest.startswith(("kn", "wr", "gn")) and index == 0:
            segs.append(_c("r" if rest.startswith("wr") else "n"))
            index += 2
            continue
        if rest.startswith("gn") and at_end(2):
            segs.append(_c("n"))  # sign, design
            index += 2
            continue
        if rest.startswith(("mb", "mn")) and at_end(2):
            segs.append(_c("m"))  # bomb, column
            index += 2
            continue
        if rest.startswith("dg"):
            segs.append(_c("j"))
            index += 2
            continue
        if rest.startswith("cc"):
            if word[index + 2 : index + 3] in ("e", "i", "y"):
                segs.extend([_c("k"), _c("s")])  # success 석세스
            else:
                segs.append(_c("k"))
            index += 2
            continue
        if rest.startswith("wh"):
            segs.append(_c("h") if rest.startswith("who") else _c("w"))
            index += 2
            continue
        if rest.startswith("gu") and word[index + 2 : index + 3] in _VOWELS:
            segs.append(_c("g"))  # guide, guest: u 묵음
            index += 2
            continue
        if nxt == c and c in _DOUBLE_LETTERS:
            index += 1  # 겹자음은 한 번만
            continue

        # ----- 한 글자 자음 -----
        if c == "c":
            segs.append(_c("s") if nxt in ("e", "i", "y") else _c("k"))
        elif c == "g":
            segs.append(_c("j") if _g_is_soft(word, index) else _c("g"))
        elif c == "x":
            if index == 0:
                segs.append(_c("j"))
            else:
                segs.extend([_c("k"), _c("s")])
        elif c == "q":
            segs.append(_c("k"))
        elif c == "h":
            if segs and segs[-1].type == "V" and nxt not in _VOWELS and nxt != "y":
                pass  # 모음 뒤 h 묵음 (oh, john)
            else:
                segs.append(_c("h"))
        elif c == "w":
            segs.append(_c("w"))
        elif c in _CONSONANTS:
            segs.append(_c(c))
        index += 1
    return segs


def _flush(seg: _Seg, coda: str | None = None) -> tuple[str, str, str | None]:
    """모음 없이 남은 자음(또는 활음)을 한 음절로 만든다."""
    kind = seg.kind
    if kind == "w":
        return "ㅇ", "ㅜ", coda
    if kind == "y":
        return "ㅇ", "ㅣ", coda
    if kind == "ng":
        return "ㅇ", "ㅡ", "ㅇ"
    return seg.onset or "ㅇ", _EPS_VOWEL.get(kind, "ㅡ"), coda


def _syllabify(segs: list[_Seg]) -> list[tuple[str, str, str | None]]:
    """세그먼트 열 → (초성, 중성, 종성) 음절 열. 받침·자음군('으' 삽입)·활음 규칙."""
    out: list[tuple[str, str, str | None]] = []
    onset: _Seg | None = None
    index = 0
    n = len(segs)
    while index < n:
        seg = segs[index]
        if seg.type == "V":
            cho, jung = "ㅇ", seg.jung
            if onset is not None:
                kind = onset.kind
                if kind == "w":
                    following = segs[index + 1] if index + 1 < n else None
                    next_is_i = (
                        following is not None and following.type == "V" and following.jung == "ㅣ"
                    )
                    if jung == "ㅏ" and next_is_i:
                        jung = "ㅘ"  # white 와이트, wine 와인 (아이 이중모음 앞의 w)
                    else:
                        jung = _W_GLIDE.get(jung, jung)
                elif kind == "y":
                    jung = _Y_GLIDE.get(jung, jung)
                elif kind == "q":
                    cho, jung = "ㅋ", _W_GLIDE.get(jung, jung)
                elif kind == "sh":
                    cho, jung = "ㅅ", _SH_GLIDE.get(jung, jung)
                elif onset.onset is not None:
                    cho = onset.onset
            onset = None
            jong: str | None = None
            j = index + 1
            if j < n and segs[j].type == "C":
                c1 = segs[j]
                after = segs[j + 1] if j + 1 < n else None
                after_v = after is not None and after.type == "V"
                kind = c1.kind
                if kind in ("m", "n"):
                    if not after_v:
                        jong = c1.coda
                        index = j
                elif kind == "ng":
                    jong = "ㅇ"
                    index = j
                    if after_v or (after is not None and after.kind in ("l", "r")):
                        onset = _c("g")  # finger 핑거, angle 앵글
                elif kind == "l":
                    jong = "ㄹ"
                    index = j
                    if after_v:
                        onset = c1  # 모음 사이 l 은 ㄹㄹ (salad 샐러드)
                elif kind == "r":
                    if not after_v:
                        index = j  # 모음 뒤 자음 앞/어말 r 묵음 (star 스타)
                elif kind in ("p", "t", "k"):
                    blocked = ("l", "r", "m", "n", "w", "y", "h")
                    before_consonant = after is not None and after.type == "C"
                    unblocked = before_consonant and after.kind not in blocked
                    if seg.short and (after is None or unblocked):
                        jong = c1.coda  # 짧은 모음 뒤 어말/자음 앞 무성 파열음은 받침
                        index = j
                elif kind == "b":
                    if seg.short and after is None:
                        jong = "ㅂ"  # 짧은 모음 뒤 어말 b 는 관행상 받침 (club 클럽, web 웹)
                        index = j
            out.append((cho, jung, jong))
            index += 1
            continue

        # ----- 자음 -----
        nxt = segs[index + 1] if index + 1 < n else None
        nxt_v = nxt is not None and nxt.type == "V"
        kind = seg.kind
        if kind == "h" and not nxt_v:
            index += 1
            continue
        if kind in ("w", "y") and not nxt_v:
            segs[index] = _v("ㅜ" if kind == "w" else "ㅣ")  # 모음 없는 활음은 스스로 모음
            continue
        if nxt_v:
            if onset is not None:
                out.append(_flush(onset, "ㄹ" if kind == "l" else None))  # 자음군: 앞 자음에 으
            onset = seg
            index += 1
            continue
        if nxt is not None and nxt.kind == "l" and kind not in ("l", "w", "y", "q", "ng"):
            after_l = segs[index + 2] if index + 2 < n else None
            if onset is not None:
                out.append(_flush(onset))
                onset = None
            out.append(_flush(seg, "ㄹ"))  # apple 애플 / global 글로
            index += 2
            if after_l is not None and after_l.type == "V":
                onset = nxt  # ㄹ 초성 겹침
            continue
        if onset is not None:
            out.append(_flush(onset))
            onset = None
        if kind in ("m", "n") and out and out[-1][2] == "ㄹ":
            out.append(("ㄹ", "ㅡ", seg.coda))  # film 필름: ㄹ 받침 뒤 어말 비음
        elif seg.onset is not None or kind == "ng":
            out.append(_flush(seg))
        index += 1
    if onset is not None:
        out.append(_flush(onset))
    return out


@functools.lru_cache(maxsize=4096)
def _g2p_rule(token: str) -> str:
    """순수 파이썬 룰 G2P(④). 영문 소문자 토큰 → 한글 발음 근사. 예외 사전을 쓰지 않는다."""
    word = "".join(ch for ch in token.lower() if "a" <= ch <= "z")
    if not word:
        return ""
    return "".join(_compose(*syllable) for syllable in _syllabify(_scan(word)))


def _g2p_word(token: str) -> str:
    """④ 영문 토큰 발음: 브랜드·지명 로마자 표 → 예외 사전 → 룰 폴백 (모두 토큰 완전일치)."""
    return (
        KOREAN_BRAND_ROMANIZATION.get(token)
        or KOREAN_PLACE_ROMANIZATION.get(token)
        or G2P_EXCEPTIONS.get(token)
        or _g2p_rule(token)
    )


def g2p_benchmark(token: str) -> str:
    """벤치마크 전용 읽기: 브랜드·지명 표와 예외 사전을 모두 끄고 순수 룰만 적용한다.

    `ml/scripts/x1_report.py` 의 20단어 표본은 반드시 이 함수로 측정한다(표에 넣은 단어가
    벤치마크를 부풀리지 않도록). 테스트가 이 계약을 검증한다.
    """
    return _g2p_rule(token)


def _letter_readings(token: str) -> list[str]:
    """알파벳 낱자 읽기. r 이 있으면 '아르' 변형도 추가한다."""
    base = "".join(LETTER_READINGS.get(ch, "") for ch in token)
    readings = [base] if base else []
    if any(ch in LETTER_READINGS_ALT for ch in token):
        alt = "".join(LETTER_READINGS_ALT.get(ch, LETTER_READINGS.get(ch, "")) for ch in token)
        readings.append(alt)
    return readings


_SINO_DIGITS: Final = "영일이삼사오육칠팔구"
_SINO_DIGITWISE: Final = "공일이삼사오육칠팔구"  # 자릿수별 읽기에서 0 은 '공'
_SINO_UNITS: Final = ("", "십", "백", "천")
_NATIVE_ONES: Final = ("", "하나", "둘", "셋", "넷", "다섯", "여섯", "일곱", "여덟", "아홉")
_NATIVE_TENS: Final = ("", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔")
_ENGLISH_DIGITS: Final = (
    "제로", "원", "투", "쓰리", "포", "파이브", "식스", "세븐", "에이트", "나인",
)


def _sino_number(value: int) -> str:
    """0~9999 를 한자어 수로 읽는다 (2080 → 이천팔십)."""
    if value == 0:
        return "영"
    parts: list[str] = []
    for power in range(3, -1, -1):
        digit = (value // 10**power) % 10
        if digit == 0:
            continue
        parts.append(("" if digit == 1 and power > 0 else _SINO_DIGITS[digit]) + _SINO_UNITS[power])
    return "".join(parts)


def _digit_readings(token: str) -> list[str]:
    """숫자 토큰의 세 읽기: 한자어(수 읽기·자릿수별), 고유어(1~99), 영어 낱자."""
    readings: list[str] = []
    leading_zero = len(token) > 1 and token[0] == "0"
    if len(token) <= 4 and not leading_zero:
        readings.append(_sino_number(int(token)))
    readings.append("".join(_SINO_DIGITWISE[int(ch)] for ch in token))
    value = int(token)
    if 1 <= value <= 99 and not leading_zero:
        readings.append(_NATIVE_TENS[value // 10] + _NATIVE_ONES[value % 10])
    readings.append("".join(_ENGLISH_DIGITS[int(ch)] for ch in token))
    return _dedupe(readings)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


@functools.lru_cache(maxsize=8192)
def _readings(token: str) -> tuple[str, ...]:
    """토큰 → 한글 발음 후보(0개 이상). 한글은 그대로, 영문은 G2P(+낱자), 숫자는 세 읽기."""
    cls = _char_class(token[0])
    if cls == "H":
        syllables = _syllables_only(token)
        return (syllables,) if syllables else ()
    if cls == "L":
        readings: list[str] = []
        if any(ch in "aeiouy" for ch in token):
            reading = _g2p_word(token)
            if reading:
                readings.append(reading)
        if len(token) <= LETTER_READING_MAX_LEN or not any(ch in _VOWELS for ch in token):
            readings.extend(_letter_readings(token))
        return tuple(_dedupe(readings))
    if cls == "D":
        return tuple(_digit_readings(token))
    return ()


# =====================================================================================
# 3·4. 병기 판정(⑤)과 후보 조립(③·분리관찰·불가분 결합)
# =====================================================================================


def _apply_paired_rule(pre: list[str], post: list[str]) -> dict[str, tuple[str, ...]]:
    """⑤ 병기 판정을 거친 토큰별 생존 읽기.

    - 토큰 단위: 영문 토큰의 읽기가 어떤 한글 토큰과도 PAIRED_THRESHOLD 이상이면 그 읽기를 버린다.
    - 구 단위: 영문 토큰 첫 읽기를 이어붙인 것이 한글 토큰을 이어붙인 것과 임계값 이상이면
      영문 읽기를 전부 버린다. 제거 전·후 토큰 열 중 하나라도 해당하면 병기로 본다.
    - 한글 토큰이 하나도 없으면 판정하지 않는다.
    """
    survivors: dict[str, tuple[str, ...]] = {}
    for token in pre:
        if token not in survivors:
            survivors[token] = _readings(token)
    hangul_readings = [survivors[t][0] for t in pre if _char_class(t[0]) == "H" and survivors[t]]
    if not hangul_readings:
        return survivors

    def latin_tokens(tokens: list[str]) -> list[str]:
        return [t for t in tokens if _char_class(t[0]) == "L" and survivors[t]]

    def phrase_paired(tokens: list[str]) -> bool:
        latin = "".join(survivors[t][0] for t in latin_tokens(tokens))
        hangul = "".join(
            survivors[t][0] for t in tokens if _char_class(t[0]) == "H" and survivors[t]
        )
        return bool(latin) and bool(hangul) and _syllable_sim(latin, hangul) >= PAIRED_THRESHOLD

    if phrase_paired(post) or phrase_paired(pre):
        for token in latin_tokens(pre):
            survivors[token] = ()
        return survivors
    for token in latin_tokens(pre):
        kept = tuple(
            reading
            for reading in survivors[token]
            if not any(_syllable_sim(reading, h) >= PAIRED_THRESHOLD for h in hangul_readings)
        )
        survivors[token] = kept
    return survivors


def _combos(tokens: list[str], survivors: dict[str, tuple[str, ...]]) -> list[str]:
    """토큰 읽기의 데카르트 곱 결합음. 조합 수가 MAX_CANDIDATES 를 넘으면 첫 읽기만 쓴다."""
    lists = [survivors[t] for t in tokens if survivors[t]]
    if not lists:
        return []
    total = 1
    for readings in lists:
        total *= len(readings)
    if total > MAX_CANDIDATES:
        lists = [readings[:1] for readings in lists]
    return ["".join(parts) for parts in itertools.product(*lists)]


@functools.lru_cache(maxsize=4096)
def _candidates_cached(name: str, extra_generic: frozenset[str]) -> tuple[str, ...]:
    pre, post = _normalize_tokens(name, extra_generic)
    if not pre:
        return ()
    survivors = _apply_paired_rule(pre, post)
    candidates = _combos(pre, survivors) + _combos(post, survivors)
    for token in post:
        if len(token) == 1 and _char_class(token) in ("L", "D"):
            continue  # 알파벳·숫자 1글자 토큰 유래 읽기는 분리관찰 후보에서 제외(결합음에는 포함)
        candidates.extend(r for r in survivors[token] if _syllable_count(r) >= 2)
    result: list[str] = []
    for candidate in _dedupe(candidates):
        syllables = _syllables_only(candidate)[:MAX_SYLLABLES]
        if syllables and syllables not in result:
            result.append(syllables)
    return tuple(result)


def _syllable_count(text: str) -> int:
    return sum(1 for ch in text if _is_syllable(ch))


# =====================================================================================
# 5. 음절 유사도 — 음절 단위 가중 레벤슈타인
# =====================================================================================


@functools.lru_cache(maxsize=64)
def _position_weights(n: int) -> tuple[float, ...]:
    """② 긴 쪽 음절 수 n 에 따른 위치 가중치."""
    if n <= 2:
        return POSITION_WEIGHTS["n<=2"][:n]
    if n <= 4:
        return POSITION_WEIGHTS["3<=n<=4"][:n]
    head = POSITION_WEIGHTS["n>=5_head"]
    return head + (1.0,) * (n - len(head))


@functools.lru_cache(maxsize=65536)
def _sub_cost(a: str, b: str) -> float:
    """음절 치환 비용 = 초성 + 중성 + 종성 비용 (최대 2.5). 대칭이다."""
    if a == b:
        return 0.0
    cho_a, jung_a, jong_a = _decompose_syllable(a)
    cho_b, jung_b, jong_b = _decompose_syllable(b)
    if cho_a == cho_b:
        cost = 0.0
    elif frozenset((cho_a, cho_b)) in CHO_SIMILAR_PAIRS:
        cost = COST_CHO_SIMILAR
    else:
        cost = COST_CHO_DIFF
    if jung_a != jung_b:
        jung_pair = frozenset((jung_a, jung_b))
        if jung_pair in JUNG_MERGED_PAIRS:
            cost += COST_JUNG_MERGED
        elif jung_pair in JUNG_SIMILAR_PAIRS:
            cost += COST_JUNG_SIMILAR
        else:
            cost += COST_JUNG_DIFF
    if jong_a is None and jong_b is None:
        pass
    elif jong_a is None or jong_b is None:
        cost += COST_JONG_ONE_SIDE
    elif jong_a != jong_b:
        rep_a, rep_b = _JONG_REP_OF.get(jong_a), _JONG_REP_OF.get(jong_b)
        if rep_a in JONG_NASAL and rep_b in JONG_NASAL:
            cost += COST_JONG_NASAL  # 비음 위치동화가 대표음 규칙보다 우선
        elif rep_a == rep_b:
            cost += COST_JONG_SAME_GROUP
        else:
            cost += COST_JONG_DIFF_GROUP
    return cost


@functools.lru_cache(maxsize=65536)
def _syllable_sim_cached(x: str, y: str) -> float:
    a = _syllables_only(x)[:MAX_SYLLABLES]
    b = _syllables_only(y)[:MAX_SYLLABLES]
    if not a or not b:
        return 0.0
    m, k = len(a), len(b)
    weights = _position_weights(max(m, k))
    indel = COST_INDEL
    prev = [0.0] * (k + 1)
    for j in range(1, k + 1):
        prev[j] = prev[j - 1] + indel * weights[0]
    for i in range(1, m + 1):
        cur = [prev[0] + indel * weights[0]] + [0.0] * k
        ai = a[i - 1]
        for j in range(1, k + 1):
            sub = prev[j - 1] + _sub_cost(ai, b[j - 1]) * weights[min(i - 1, j - 1)]
            delete = prev[j] + indel * weights[min(i - 1, j)]
            insert = cur[j - 1] + indel * weights[min(i, j - 1)]
            cur[j] = min(sub, delete, insert)
        prev = cur
    max_distance = indel * sum(weights)
    return max(0.0, min(1.0, 1.0 - prev[k] / max_distance))


def _syllable_sim(x: str, y: str) -> float:
    """두 한글 문자열의 발음 유사도 0.0~1.0. 대칭·결정적. 한글 음절이 없으면 0.0.

    음절 단위 가중 레벤슈타인: 치환 = 초성·중성·종성 비용 합, 삽입·삭제 = COST_INDEL.
    각 연산 비용에 위치 가중치 w[min(i, j)] 를 곱하고(대칭 보장, i·j 는 0-기반 대응 위치),
    최대거리 Σ w[p]·COST_INDEL 로 나눠 1 에서 뺀다.
    """
    if x > y:
        x, y = y, x
    return _syllable_sim_cached(x, y)


# =====================================================================================
# 공개 인터페이스 (규약)
# =====================================================================================


def _as_text(name: object) -> str:
    return "" if name is None else str(name)


def pronunciation_candidates(
    name: str, *, extra_generic: frozenset[str] = frozenset()
) -> list[str]:
    """상표명 하나의 한글 발음 후보 목록(중복 제거, 순서 결정적). 디버깅·테스트용.

    Args:
        name: 상표명 문자열.
        extra_generic: 호출자(식별력 필터 등)가 넘기는 상품 의존 보통명칭 집합.

    Returns:
        한글 음절 1개 이상인 후보 문자열 목록. 발음할 수 없으면 빈 목록.
    """
    return list(_candidates_cached(_as_text(name), frozenset(extra_generic)))


def has_pronunciation(name: str, *, extra_generic: frozenset[str] = frozenset()) -> bool:
    """한글 음절 1개 이상인 발음 후보가 하나라도 있으면 True (순수 도형·한자만·기호만이면 False)."""
    return bool(_candidates_cached(_as_text(name), frozenset(extra_generic)))


def phonetic_similarity(
    name_a: str, name_b: str, *, extra_generic: frozenset[str] = frozenset()
) -> float:
    """호칭(발음) 유사도. 0.0~1.0, 높을수록 유사. 대칭·결정적이며 어떤 문자열에도 예외 없이 반환.

    ③ 양쪽 발음 후보의 모든 쌍에 _syllable_sim 을 적용한 최댓값. 후보가 한쪽이라도 비면 0.0.

    Args:
        name_a: 상표명 A.
        name_b: 상표명 B.
        extra_generic: 양쪽에 공통으로 적용할 상품 의존 보통명칭 집합.
    """
    generic = frozenset(extra_generic)
    candidates_a = _candidates_cached(_as_text(name_a), generic)
    candidates_b = _candidates_cached(_as_text(name_b), generic)
    if not candidates_a or not candidates_b:
        return 0.0
    best = 0.0
    for x in candidates_a:
        for y in candidates_b:
            score = _syllable_sim(x, y)
            if score > best:
                best = score
                if best >= 1.0:
                    return 1.0
    return best
