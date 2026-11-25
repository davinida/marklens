"""유명 상표 확인 — 등록부와 일치 판정(측정용: 엔진·계약·화면에서 부르지 않는다).

통합 모델 설계 §7-14. 유명 상표 보호는 일반 유사 판단과 근거가 달라, 업종에 따라 움직이는 판단
앞에 따로 둔다. 질의 이름이 등록부(shared/famous_registry.json — `ml/scripts/famous_registry.py`
가 만든다)의 브랜드 표기와 일치하는지를 **표기 기준**으로 본다. 식별력 필터(요부 추출)는
거치지 않는다 — 설명 낱말로 빠지는 "bbq" 도 견줘야 한다. 아래는 2-1단계(2026-11-25) 규칙.

용어
    붙여 쓴 꼴(key)  정리(clean_input_name → 상표 기호 제거·NFKC·소문자) 뒤 한글·영문·숫자만
                    이은 것.
    낱말            공백·기호로만 나눈 것의 붙여 쓴 꼴(상품 접미어 분리는 쓰지 않는다).
    낱말 묶음       이어진 낱말(최대 MAX_BUNDLE_WORDS)을 붙인 꼴 — 표기에 기호·공백이 있어 질의
                    에서 여러 낱말로 나뉘는 경우(PAIK'S·PARIS BAGUETTE)도 묶음으로 본다.
    설명 낱말       ① 업종 낱말(업종 세트 25개의 이름·별칭의 낱말과 가게 형태 낱말 — 이 모듈
                    안의 사전) ② 질의 업종이나 브랜드 업종에서 1호 보통명칭·3호 성질표시로
                    판정되는 말(유명 예외를 뺀 판정). 4호·5호·6호로만 식별력이 없는 말(지명·
                    흔한 성·한 글자)은 설명 낱말이 아니다. 나머지는 설명 낱말 하나 또는 둘을
                    이어 쓴 꼴까지 인정한다.
    브랜드 업종     이름 일치에는 업종 세트와 역할 "이름" 표장의 유사군만 쓴다(표장별 겹침의
                    최댓값 ≥ 결합 하한 0.0252 면 겹침). 도형·다른 이름 표장의 유사군은 안 쓴다.

표기 종류
    약한 표기       유명 예외를 뺀 식별력 판정으로 그 브랜드 자신의 업종에서 식별력이 없는 표기
                    (BBQ·CU·GS25·김가네)와, 같은 브랜드에서 그 표기와 소리가 0.98 이상인 표기
                    (비비큐·씨유·지에스25).
    머리글자 표기   약한 표기가 아닌 영문 3자 이하 표기(bhc)와, 같은 브랜드에서 그 표기와 소리가
                    0.98 이상인 표기(비에이치씨). 같음과 품음-설명만 인정한다.
    보통 표기       나머지.

경로(보통 표기)
    (가) 같음       낱말 묶음 = 표기.
    (나) 품음       낱말(묶음)이 표기 + 나머지(앞이나 뒤). 나머지가 설명 낱말이면 "품음-설명"
                    (강함), 아니면 "품음-기타"(약함 — 짧은 표기는 인정하지 않음).
    (다) 소리       표기 전체와 견주는 구간 전체를 통째로 견준다(X1 의 읽기와 음절 유사도 —
                    조각끼리의 최댓값·붙여쓴 결합어 포함 점수는 쓰지 않고, 숫자는 숫자끼리 같아야
                    한다). 대상은 낱말 묶음과, 낱말의 앞·뒤 구간으로서 나머지가 설명 낱말인 것.
    (라) 철자       같은 문자 종류끼리만, 붙여 쓴 꼴 전체의 자모 편집거리(x2_ortho v1 의 식).
                    대상은 (다)와 같다. 약한 철자 일치는 같은 대상의 소리가 S 이상일 때만.
약한 표기           질의에서 설명 낱말(붙여 쓴 것 포함)을 뺀 나머지가 그 표기 하나뿐일 때만 일치
                    — 업종이 없거나 겹치면 강함, 업종이 다르고 그 표기가 그 업종에서도 식별력
                    없는 말이면 안내만, 그 업종에서는 식별력이 있으면 보통 표기의 같음처럼 강함.
                    다른 말과 함께면 안내만. 질의 안의 약한 표기는 그 브랜드의 다른 표기와 견주지
                    않는다(가림).

수준과 바닥
    강함 = 같음·품음-설명·소리 ≥ 강한 소리·철자 ≥ 강한 철자, 약함 = 소리·철자가 약한 기준 이상·
    품음-기타. 업종 불문 브랜드: 강함 → 위험, 약함 → 검토 권장. 같은·가까운 업종 중심 브랜드:
    업종이 겹치거나 없으면 같고, 다르면 강함 → 검토 권장·약함 → 안내만. 설명적 사용 안내는
    바닥이 없다.
"""

from __future__ import annotations

import functools
import itertools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping

from src.axes import distinctiveness as _distinctiveness
from src.axes.distinctiveness import Distinctiveness, TokenJudgement, load_distinctiveness
from src.axes.pair_axes import clean_input_name, normalize_codes
from src.axes.x1_phonetic import (
    MAX_CANDIDATES,
    MAX_SYLLABLES,
    _basic_normalize,
    _char_class,
    _clean_chars,
    _readings,
    _syllable_sim,
    _syllables_only,
    _tokenize,
)
from src.axes.x2_ortho import _similarity as _key_similarity
from src.axes.x2_ortho import decompose_jamo
from src.axes.x4_goods import goods_similarity

__all__ = [
    "REGISTRY_VERSION", "OVERRIDES_VERSION", "DEFAULT_REGISTRY_PATH", "DEFAULT_OVERRIDES_PATH",
    "DEFAULT_BRANDS_PATH", "PROTECT_ANY", "PROTECT_NEAR", "ROLE_NAME", "ROLE_FIGURE",
    "ROLE_OTHER", "ROLE_LOGO", "ROLE_EXCLUDED", "LENGTHS", "KIND_WEAK", "KIND_INITIAL",
    "KIND_NORMAL", "LEVEL_STRONG", "LEVEL_WEAK", "LEVEL_NOTICE", "PATH_EXACT",
    "PATH_CONTAIN_DESC", "PATH_CONTAIN_OTHER", "PATH_SOUND", "PATH_SPELLING", "BASIS_NAME",
    "BASIS_OCR", "Notation", "Mark", "Brand", "Registry", "Thresholds", "PreparedQuery",
    "Evidence", "BrandEvidence", "BrandMatch", "FamousResult", "normalize_text", "split_pieces",
    "text_key", "script_label", "length_class", "whole_sound", "whole_spelling",
    "industry_words", "analyze_notation", "classify_notations", "read_brand_table",
    "title_has_notation", "auto_role", "build_registry", "registry_to_json", "load_registry",
    "load_overrides", "prepare_query", "collect_evidence", "decide", "check_famous",
    "default_goods_floor",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = REPO_ROOT / "shared" / "famous_registry.json"
DEFAULT_OVERRIDES_PATH = REPO_ROOT / "shared" / "famous_registry_overrides.json"
DEFAULT_BRANDS_PATH = REPO_ROOT / "shared" / "famous_brands.txt"
# 업종 낱말 사전의 원천 — 환경 변수로 바꾼 경로가 아니라 저장소의 업종 세트 파일 그대로
PRESETS_PATH = REPO_ROOT / "shared" / "goods_map" / "business_presets.json"
REGISTRY_VERSION = "famous_registry_v2"  # v2: 표기 종류(kind)·종류의 근거(inherits)
OVERRIDES_VERSION = "famous_registry_overrides_v1"
BRAND_SECTION = "[브랜드]"

PROTECT_ANY = "업종 불문"
PROTECT_NEAR = "같은·가까운 업종 중심"
PROTECTIONS = (PROTECT_ANY, PROTECT_NEAR)
ROLE_NAME, ROLE_FIGURE, ROLE_OTHER = "이름", "도형", "다른 이름"
ROLE_LOGO, ROLE_EXCLUDED = "브랜드 로고", "제외"  # overrides 로만
AUTO_ROLES = (ROLE_NAME, ROLE_FIGURE, ROLE_OTHER)
OVERRIDE_ROLES = (ROLE_LOGO, ROLE_EXCLUDED)
BRAND_MARK_ROLES = (ROLE_NAME, ROLE_FIGURE, ROLE_LOGO)  # 브랜드 자신의 표장으로 보는 역할
SOURCE_FAMOUS, SOURCE_EXISTING = "유명 브랜드 수집", "기존 수집(같은 출원인)"

LENGTH_SHORT, LENGTH_MID, LENGTH_LONG = "짧음", "중간", "김"
LENGTHS = (LENGTH_SHORT, LENGTH_MID, LENGTH_LONG)
ALNUM_WEIGHT = 0.6  # 길이 환산: 한글 음절 1 = 영문·숫자 1/0.6자(순수 표기에서는 지시의 구간과 같다)
KIND_WEAK, KIND_INITIAL, KIND_NORMAL = "약한 표기", "머리글자 표기", "보통 표기"
KINDS = (KIND_WEAK, KIND_INITIAL, KIND_NORMAL)
KIND_SOUND = 0.98  # 같은 브랜드에서 약한·머리글자 표기와 소리가 이 이상이면 같은 종류로 본다
INITIAL_MAX_LETTERS = 3  # 머리글자 표기: 약한 표기가 아닌 영문 이 글자 수 이하
LEVEL_STRONG, LEVEL_WEAK, LEVEL_NOTICE = "강함", "약함", "설명적 사용 안내"
PATH_EXACT, PATH_CONTAIN_DESC, PATH_CONTAIN_OTHER = "같음", "품음-설명", "품음-기타"
PATH_SOUND, PATH_SPELLING = "소리", "철자"
BASIS_NAME, BASIS_OCR = "이름", "이미지 속 글자 기준"
GRADES = ("안전", "주의", "검토 권장", "위험")
GRADE_REVIEW, GRADE_RISK = "검토 권장", "위험"
STRONG_SOUND = 0.98  # 단독 축 기준(standalone x1)과 같다
MAX_BUNDLE_WORDS = 5  # 낱말 묶음에 넣는 이어진 낱말 수 상한
MAX_DESCRIPTIVE_WORDS = 2  # 나머지는 설명 낱말 하나 또는 둘을 이어 쓴 꼴까지
WEAK_USE_ALONE, WEAK_USE_WITH_OTHERS = "단독", "다른 말과 함께"
# 가게 형태 낱말(업종 낱말 사전의 일부 — 업종 세트의 이름·별칭에 더한다)
SHOP_WORDS = ("가게", "전문점", "매장", "샵", "숍", "스토어", "마트", "하우스", "본점", "지점",
              "직영점")
# 설명 낱말로 보는 판정 사유의 머리(보통명칭·성질표시). 4호·5호·6호만으로는 설명 낱말이 아니다
DESCRIPTIVE_REASONS = ("1호 보통명칭", "3호 기술적 표장")
# 근거로 남길 대상의 최소 점수 — 기준 격자의 가장 낮은 값(약한 소리 0.90·약한 철자 0.75)보다 낮게
UNIT_MIN_SOUND, UNIT_MIN_SPELLING = 0.85, 0.70
_LEVEL_RANK = {LEVEL_STRONG: 3, LEVEL_WEAK: 2, LEVEL_NOTICE: 1}
_PATH_RANK = {PATH_EXACT: 5, PATH_CONTAIN_DESC: 4, PATH_SOUND: 3, PATH_SPELLING: 2,
              PATH_CONTAIN_OTHER: 1}
_SCRIPT_NAMES = {"H": "한글", "L": "영문", "D": "숫자"}
_URL = re.compile(r"https?://\S+")
_INLINE_COMMENT = re.compile(r"\s+#.*$")
_HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
_TITLE_DROP = re.compile(r"['’`\-]")


# ---- 글자 정리 ---------------------------------------------------------------------------------

def normalize_text(text: object) -> str:
    """정리 — clean_input_name(서식 문자 제거·NFC) → 상표 기호 제거·NFKC·소문자(대소문자 무시)."""
    return _basic_normalize(clean_input_name(text))


def split_pieces(text: str) -> list[str]:
    """정리한 글자열 → 문자 종류(한글/영문/숫자) 경계 조각. 기호는 공백, 한자·기타 문자는 버린다
    (X1 토큰화와 같은 기준)."""
    return _tokenize(_clean_chars(text))


def text_key(text: object) -> str:
    """붙여 쓴 꼴 — 정리 뒤 한글·영문·숫자만 이은 것("L'OREAL" → "loreal")."""
    return "".join(split_pieces(normalize_text(text)))


def split_words(text: object) -> tuple[str, ...]:
    """낱말 — 공백·기호로만 나눈 것의 붙여 쓴 꼴("PAIK'S 카페" → paik·s·카페). 상품 접미어
    분리는 하지 않는다."""
    words = ("".join(_tokenize(raw)) for raw in _clean_chars(normalize_text(text)).split())
    return tuple(word for word in words if word)


def script_label(key: str) -> str:
    """문자 종류 — "한글"·"영문"·"숫자" 또는 섞인 것("영문+숫자")."""
    kinds = {_SCRIPT_NAMES[c] for c in map(_char_class, key) if c in _SCRIPT_NAMES}
    return "+".join(name for name in ("한글", "영문", "숫자") if name in kinds)


def length_class(key: str) -> str:
    """길이 구간 — 짧음 = 한글 2음절 이하 또는 영문·숫자 3자 이하, 중간 = 한글 3음절 또는 영문·
    숫자 4–5자, 김 = 그 이상. 섞인 표기는 한글 음절 수 + 0.6 × 영문·숫자 글자 수로 환산해 2 이하·
    3 이하·그 위로 나눈다(순수 표기에서는 앞의 구간과 같다)."""
    hangul = sum(1 for ch in key if _char_class(ch) == "H")
    alnum = sum(1 for ch in key if _char_class(ch) in ("L", "D"))
    size = hangul + ALNUM_WEIGHT * alnum
    if size <= 2.0 + 1e-9:
        return LENGTH_SHORT
    if size <= 3.0 + 1e-9:
        return LENGTH_MID
    return LENGTH_LONG


# ---- 통째 비교(소리·철자) -----------------------------------------------------------------------

def _digit_runs(key: str) -> tuple[str, ...]:
    return tuple(token for token in _tokenize(key) if _char_class(token[0]) == "D")


@functools.lru_cache(maxsize=65536)
def whole_readings(key: str) -> tuple[str, ...]:
    """붙여 쓴 꼴 전체의 한글 읽기 — 문자 종류 조각마다 X1 의 읽기(_readings: 한글 그대로·영문
    G2P(+낱자)·숫자 읽기)를 순서대로 이은 것. 조각 하나만 떼어 낸 읽기는 만들지 않는다. 조합이
    MAX_CANDIDATES 를 넘으면 조각마다 첫 읽기만 쓴다(X1 의 결합음과 같은 규칙)."""
    lists = [readings for readings in map(_readings, _tokenize(key)) if readings]
    if not lists:
        return ()
    total = 1
    for readings in lists:
        total *= len(readings)
    if total > MAX_CANDIDATES:
        lists = [readings[:1] for readings in lists]
    out: list[str] = []
    for parts in itertools.product(*lists):
        reading = _syllables_only("".join(parts))[:MAX_SYLLABLES]
        if reading and reading not in out:
            out.append(reading)
    return tuple(out)


def whole_sound(key_a: str, key_b: str) -> float:
    """통째 소리 — 두 붙여 쓴 꼴 전체의 읽기끼리 X1 음절 유사도(편집거리)의 최댓값. 숫자는 숫자끼리
    같아야 하고(다르면 0), 조각끼리의 최댓값·붙여쓴 결합어 포함 점수는 쓰지 않는다. 대칭."""
    if not key_a or not key_b or _digit_runs(key_a) != _digit_runs(key_b):
        return 0.0
    best = 0.0
    for x in whole_readings(key_a):
        for y in whole_readings(key_b):
            score = _syllable_sim(x, y)
            if score > best:
                best = score
    return best


def whole_spelling(key_a: str, key_b: str) -> float:
    """통째 철자 — 두 붙여 쓴 꼴 전체를 자모로 푼 편집거리 유사도(x2_ortho v1 이 전체 문자열에 쓰는
    식). 숫자는 숫자끼리 같아야 한다(다르면 0). 문자 종류가 같은지는 부르는 쪽이 본다."""
    if not key_a or not key_b or _digit_runs(key_a) != _digit_runs(key_b):
        return 0.0
    return _key_similarity(decompose_jamo(key_a), decompose_jamo(key_b))


# ---- 설명 낱말 ---------------------------------------------------------------------------------

@functools.lru_cache(maxsize=4)
def industry_words(path: str | None = None) -> frozenset[str]:
    """업종 낱말 사전 — 업종 세트 25개의 이름·별칭을 공백·기호로 나눈 낱말 전부와 가게 형태 낱말
    (붙여 쓴 꼴). 이 모듈 안에서만 쓴다(식별력 모듈과 학습 특징은 그대로)."""
    presets = json.loads(Path(path or PRESETS_PATH).read_text(encoding="utf-8"))
    words = {text_key(word) for word in SHOP_WORDS}
    for preset in presets:
        for phrase in (preset.get("업종명") or "", *(preset.get("별칭") or ())):
            words.update(split_words(phrase))
    words.discard("")
    return frozenset(words)


_REASON_CACHE: dict[tuple[int, str, frozenset[str]], bool] = {}


def _descriptive_by_judgement(dist: Distinctiveness, token: str, goods: frozenset[str]) -> bool:
    """그 업종에서 보통명칭(1호)·성질표시(3호)로 식별력이 없다고 판정되는 말인가(유명 예외 뺌)."""
    key = (id(dist), token, goods)
    hit = _REASON_CACHE.get(key)
    if hit is None:
        if len(_REASON_CACHE) > 500_000:
            _REASON_CACHE.clear()
        judged = dist.judge(token, goods, famous_exception=False)
        hit = judged.score < dist.theta and any(
            reason.startswith(DESCRIPTIVE_REASONS) for reason in judged.reasons)
        _REASON_CACHE[key] = hit
    return hit


def _descriptive_checker(dist: Distinctiveness, query_goods: frozenset[str],
                         brand_codes: frozenset[str], words: frozenset[str]
                         ) -> Callable[[str], bool]:
    """설명 낱말(하나 또는 둘을 이어 쓴 꼴)인가 — 모듈 설명의 정의."""
    contexts = tuple(codes for codes in (query_goods, brand_codes) if codes)
    terms = dist.descriptive
    if terms is None:
        terms = _distinctiveness.DESCRIPTIVE_TERMS
    names = dist.goods_names
    single_memo: dict[str, bool] = {}
    memo: dict[str, bool] = {}

    def single(text: str) -> bool:
        hit = single_memo.get(text)
        if hit is None:
            hit = text in words
            if not hit and (text in names or text in terms):  # 1호·3호가 될 수 있는 말만 판정
                hit = any(_descriptive_by_judgement(dist, text, codes) for codes in contexts)
            single_memo[text] = hit
        return hit

    def descriptive(text: str) -> bool:
        if not text:
            return False
        hit = memo.get(text)
        if hit is None:
            hit = single(text) or (MAX_DESCRIPTIVE_WORDS >= 2 and any(
                single(text[:cut]) and single(text[cut:]) for cut in range(1, len(text))))
            memo[text] = hit
        return hit

    return descriptive


# ---- 등록부 ------------------------------------------------------------------------------------

def _judge(dist: Distinctiveness, piece: str, goods: frozenset[str]) -> TokenJudgement:
    return dist.judge(piece, goods or None, famous_exception=False)


def _weak(dist: Distinctiveness, piece: str, goods: frozenset[str]) -> bool:
    return _judge(dist, piece, goods).score < dist.theta


def _notation_pieces(text: str, dist: Distinctiveness) -> list[str]:
    """표기의 식별력을 보는 조각 — 1단계 정의대로 상품 접미어 분리 뒤의 문자 종류 조각."""
    return split_pieces(dist.split_goods_suffix(normalize_text(text)))


def _plain_in(dist: Distinctiveness, text: str, goods: frozenset[str]) -> bool:
    """그 업종에서 표기의 조각이 모두 식별력 없는 말인가(유명 예외 뺌)."""
    pieces = _notation_pieces(text, dist)
    return bool(pieces) and all(_weak(dist, piece, goods) for piece in pieces)


def analyze_notation(text: str, dist: Distinctiveness, brand_codes: frozenset[str]) -> dict:
    """표기 하나의 등록부 항목 — 붙여 쓴 꼴·조각·문자 종류·길이 구간, 그리고 자기 업종에서의
    식별력(base_weak): 유명 예외를 뺀 판정으로 그 브랜드 자신의 업종(brand_codes)에서 조각(접미어
    분리 뒤)이 모두 약하면 True. 조각별 판정(점수·사유)을 함께 남긴다. 표기 종류(kind)는
    classify_notations 가 브랜드 단위로 정한다."""
    clean = normalize_text(text)
    key = "".join(split_pieces(clean))
    judged = [_judge(dist, piece, brand_codes) for piece in _notation_pieces(text, dist)]
    weak = bool(judged) and all(j.score < dist.theta for j in judged)
    return {"text": text, "key": key, "pieces": split_pieces(clean),
            "script": script_label(key), "length": length_class(key), "base_weak": weak,
            "judgements": [{"token": j.token, "score": j.score, "reasons": list(j.reasons)}
                           for j in judged]}


def classify_notations(items: list[dict]) -> list[dict]:
    """한 브랜드의 표기들에 종류를 붙인다(kind·inherits·kind_reason).

    약한 표기 = base_weak 인 표기와, 그 표기와 통째 소리가 KIND_SOUND 이상인 표기(inherits = 그
    약한 표기들 — 다른 업종에서의 식별력은 그 표기의 것을 따른다). 머리글자 표기 = 약한 표기가
    아닌 영문 INITIAL_MAX_LETTERS 자 이하 표기와, 그 표기와 소리가 KIND_SOUND 이상인 표기. 나머지는
    보통 표기."""
    out = [dict(item) for item in items]
    base = [item for item in out if item["base_weak"]]
    for item in out:
        if item["base_weak"]:
            reasons = "; ".join(f"{j['token']}: {'·'.join(j['reasons'])}"
                                for j in item["judgements"])
            item.update(kind=KIND_WEAK, inherits=[item["text"]],
                        kind_reason=f"자기 업종에서 식별력 없음({reasons})")
            continue
        alike = [(other["text"], whole_sound(item["key"], other["key"])) for other in base]
        alike = [(text, score) for text, score in alike if score >= KIND_SOUND]
        if alike:
            item.update(kind=KIND_WEAK, inherits=[text for text, _ in alike],
                        kind_reason="약한 표기와 소리가 같음(" + ", ".join(
                            f"{text} {score:.2f}" for text, score in alike) + ")")
    initials = [item for item in out if "kind" not in item and item["script"] == "영문"
                and len(item["key"]) <= INITIAL_MAX_LETTERS]
    for item in initials:
        item.update(kind=KIND_INITIAL, inherits=[item["text"]],
                    kind_reason=f"영문 {len(item['key'])}자")
    for item in out:
        if "kind" in item:
            continue
        alike = [(other["text"], whole_sound(item["key"], other["key"])) for other in initials]
        alike = [(text, score) for text, score in alike if score >= KIND_SOUND]
        if alike:
            item.update(kind=KIND_INITIAL, inherits=[text for text, _ in alike],
                        kind_reason="머리글자 표기와 소리가 같음(" + ", ".join(
                            f"{text} {score:.2f}" for text, score in alike) + ")")
        else:
            item.update(kind=KIND_NORMAL, inherits=[], kind_reason="")
    return out


@dataclass(frozen=True)
class Notation:
    text: str  # 표에 적힌 표기 그대로
    key: str
    pieces: tuple[str, ...]
    script: str
    length: str
    kind: str  # 약한 표기 | 머리글자 표기 | 보통 표기
    base_weak: bool  # 자기 업종에서 식별력 없는 표기(1단계의 약한 표기)
    inherits: tuple[str, ...] = ()  # 종류를 따르는 같은 브랜드의 표기(자기 자신일 수 있다)
    kind_reason: str = ""
    judgements: tuple[dict, ...] = ()

    @property
    def weak(self) -> bool:
        return self.kind == KIND_WEAK


@dataclass(frozen=True)
class Mark:
    appno: str
    title: str | None
    kind: str | None  # 상표구분(도형복합·도형상표 …)
    role: str  # 이름 | 도형 | 다른 이름 | 브랜드 로고 | 제외
    auto_role: str  # overrides 적용 전 자동 역할
    source: str  # 유명 브랜드 수집 | 기존 수집(같은 출원인)
    image: str | None
    image_exists: bool
    codes: frozenset[str]
    classes: tuple[int, ...] = ()


@dataclass(frozen=True)
class Brand:
    name: str
    notations: tuple[Notation, ...]
    applicants: tuple[str, ...]
    applicant_keys: frozenset[str]  # 정규화 + 별칭 표 적용
    preset: str
    preset_label: str | None
    preset_codes: frozenset[str]
    evidence: str
    evidence_urls: tuple[str, ...]
    protection: str
    goods_codes: frozenset[str]  # 자기 업종의 식별력 맥락 — 브랜드 표장 유사군, 없으면 업종 세트
    goods_source: str
    marks: tuple[Mark, ...]

    @property
    def brand_marks(self) -> tuple[Mark, ...]:
        return tuple(mark for mark in self.marks if mark.role in BRAND_MARK_ROLES)

    @property
    def goods_sets(self) -> tuple[frozenset[str], ...]:
        """1단계의 업종 겹침 집합(브랜드 표장 하나하나와 업종 세트) — 1단계 표본을 그대로 다시
        만드는 데만 쓴다. 이름 일치의 업종 겹침은 name_goods_sets."""
        sets = [mark.codes for mark in self.brand_marks if mark.codes]
        if self.preset_codes:
            sets.append(self.preset_codes)
        return tuple(sets)

    @property
    def name_goods_sets(self) -> tuple[frozenset[str], ...]:
        """이름 일치용 브랜드 업종 — 업종 세트와 역할 "이름" 표장 하나하나의 유사군."""
        sets = [self.preset_codes] if self.preset_codes else []
        sets += [mark.codes for mark in self.marks if mark.role == ROLE_NAME and mark.codes]
        return tuple(sets)

    @property
    def name_goods_codes(self) -> frozenset[str]:
        """이름 일치용 브랜드 업종의 유사군 합집합(설명 낱말 판정의 맥락)."""
        return frozenset(code for codes in self.name_goods_sets for code in codes)


@dataclass(frozen=True)
class Registry:
    version: str
    brands: tuple[Brand, ...]
    sources: Mapping = field(default_factory=dict)

    def brand(self, name: str) -> Brand | None:
        return next((brand for brand in self.brands if brand.name == name), None)

    @property
    def applicant_keys(self) -> frozenset[str]:
        return frozenset(key for brand in self.brands for key in brand.applicant_keys)


def read_brand_table(path: Path = DEFAULT_BRANDS_PATH) -> list[dict]:
    """famous_brands.txt 의 [브랜드] 표 — 행마다 {notations, applicants, preset, evidence, urls}.
    표기·출원인은 ' / ' 로 이은 것을 나눈다(표에 있는 그대로, 새 표기를 지어내지 않는다)."""
    rows: list[dict] = []
    section: str | None = None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = _INLINE_COMMENT.sub("", line).strip()
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue
        if section != BRAND_SECTION:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 4 or not all(cells[:3]):
            raise ValueError(f"[브랜드] 행은 '브랜드 | 출원인명 | 업종 | 선정 근거' 입니다: {line}")
        evidence = " | ".join(cells[3:])
        rows.append({
            "notations": [part.strip() for part in cells[0].split(" / ") if part.strip()],
            "applicants": [part.strip() for part in cells[1].split(" / ") if part.strip()],
            "preset": cells[2], "evidence": evidence, "urls": _URL.findall(evidence)})
    return rows


def _latin_words(text: str) -> str:
    text = _TITLE_DROP.sub("", str(text or "").lower())
    return " ".join(re.sub(r"[^0-9a-z가-힣]+", " ", text).split())


def title_has_notation(title: str | None, notations: Iterable[str]) -> bool:
    """상표명에 브랜드 표기가 들어 있는가 — 수집 때의 규칙(collect_pipeline.title_has_brand)과
    같다: 한글 표기는 공백·기호를 뗀 부분 일치, 영문 표기는 소문자·아포스트로피·하이픈 제거 뒤 단어
    경계 일치('Nice to CU' ⊃ 'cu', 'cupon' ⊅ 'cu')."""
    words = _latin_words(title or "")
    compact = words.replace(" ", "")
    for name in notations:
        if _HANGUL.search(name):
            key = _latin_words(name).replace(" ", "")
            if key and key in compact:
                return True
        else:
            key = _latin_words(name)
            if key and re.search(rf"(?<![0-9a-z]){re.escape(key)}(?![0-9a-z])", words):
                return True
    return False


def auto_role(title: str | None, notations: Iterable[str]) -> str:
    """표장 역할(자동) — 상표명에 브랜드 표기가 있으면 "이름", 상표명이 없으면 "도형", 그 밖은
    "다른 이름"."""
    if not (title or "").strip():
        return ROLE_FIGURE
    return ROLE_NAME if title_has_notation(title, notations) else ROLE_OTHER


def load_overrides(path: Path = DEFAULT_OVERRIDES_PATH) -> dict:
    """사람이 정한 값 — {"brands": {브랜드: {"protection": …}}, "marks": {출원번호: {"role": …}}}.
    파일이 없으면 빈 틀. 모르는 값은 ValueError."""
    if not Path(path).exists():
        return {"version": OVERRIDES_VERSION, "brands": {}, "marks": {}}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != OVERRIDES_VERSION:
        raise ValueError(f"famous_registry_overrides: version 은 {OVERRIDES_VERSION} 여야 합니다")
    for name, item in (data.get("brands") or {}).items():
        protection = item.get("protection")
        if protection is not None and protection not in PROTECTIONS:
            raise ValueError(f"overrides: {name} 의 보호 범위는 {PROTECTIONS} 중 하나여야 합니다")
    for appno, item in (data.get("marks") or {}).items():
        if item.get("role") not in OVERRIDE_ROLES:
            raise ValueError(f"overrides: {appno} 의 역할은 {OVERRIDE_ROLES} 중 하나여야 합니다")
    return {"version": data["version"], "brands": dict(data.get("brands") or {}),
            "marks": dict(data.get("marks") or {})}


def _record_title(record: dict) -> str | None:
    parts = [str(record.get(key) or "").strip() for key in ("상표한글명", "상표영문명")]
    title = " ".join(part for part in parts if part)
    return title or None


def _notation(item: dict) -> Notation:
    return Notation(
        text=item["text"], key=item["key"], pieces=tuple(item["pieces"]),
        script=item["script"], length=item["length"], kind=item["kind"],
        base_weak=bool(item["base_weak"]), inherits=tuple(item.get("inherits") or ()),
        kind_reason=item.get("kind_reason") or "",
        judgements=tuple(item.get("judgements") or ()))


def build_registry(
    rows: list[dict], *, plan_records: list[dict], db_records: list[dict],
    preset_codes: Mapping[str, Iterable[str]], preset_labels: Mapping[str, str],
    dist: Distinctiveness, applicant_keys: Callable[[str], frozenset[str]],
    overrides: dict | None = None, image_exists: Callable[[str], bool] | None = None,
    sources: Mapping | None = None,
) -> Registry:
    """[브랜드] 표(rows)·수집 계획 기록(plan_records: 출원번호 → 브랜드)·DB 메타데이터로 등록부를
    만든다. 브랜드의 DB 표장 = 계획 기록의 그 브랜드 표장 + 같은 출원인(별칭 표 적용)의 그 밖의
    DB 표장(기존 수집). 역할은 자동(auto_role) 뒤 overrides("브랜드 로고" 확정·"제외")로 덮는다."""
    overrides = overrides or {"brands": {}, "marks": {}}
    by_appno = {str(record["출원번호"]): record for record in db_records}
    planned: dict[str, list[str]] = {}
    for record in plan_records:
        planned.setdefault(record["브랜드"], []).append(str(record["출원번호"]))
    planned_all = {appno for items in planned.values() for appno in items}
    owner_of: dict[str, str] = {}
    brand_rows = []
    for row in rows:
        name = row["notations"][0]
        keys = frozenset(key for text in row["applicants"] for key in applicant_keys(text))
        for key in keys:
            if owner_of.setdefault(key, name) != name:
                raise ValueError(f"출원인 {key} 이 두 브랜드({owner_of[key]}, {name})에 있습니다")
        brand_rows.append((name, row, keys))
    extra: dict[str, list[str]] = {}
    for record in db_records:
        appno = str(record["출원번호"])
        if appno in planned_all:
            continue
        for key in applicant_keys(str(record.get("출원인") or "")):
            if key in owner_of:
                extra.setdefault(owner_of[key], []).append(appno)
                break
    brands: list[Brand] = []
    for name, row, keys in brand_rows:
        marks: list[Mark] = []
        listed = [(appno, SOURCE_FAMOUS) for appno in planned.get(name, [])]
        listed += [(appno, SOURCE_EXISTING) for appno in sorted(extra.get(name, []))]
        for appno, source in listed:
            record = by_appno.get(appno)
            if record is None:
                raise ValueError(f"계획 기록의 출원번호가 DB 에 없습니다: {appno}")
            title = _record_title(record)
            automatic = auto_role(title, row["notations"])
            role = (overrides["marks"].get(appno) or {}).get("role") or automatic
            image = record.get("이미지파일")
            marks.append(Mark(
                appno=appno, title=title, kind=record.get("상표구분"), role=role,
                auto_role=automatic, source=source, image=image,
                image_exists=bool(image) and (image_exists(image) if image_exists else True),
                codes=normalize_codes(record.get("유사군") or ()),
                classes=tuple(sorted(int(c) for c in record.get("류") or ()))))
        own = frozenset(code for mark in marks if mark.role in BRAND_MARK_ROLES
                        for code in mark.codes)
        preset = frozenset(normalize_codes(preset_codes.get(row["preset"]) or ()))
        goods_codes, goods_source = (own, "브랜드 표장") if own else (preset, "업종 세트")
        notations = tuple(_notation(item) for item in classify_notations(
            [analyze_notation(text, dist, goods_codes) for text in row["notations"]]))
        protection = (overrides["brands"].get(name) or {}).get("protection") or PROTECT_ANY
        brands.append(Brand(
            name=name, notations=notations, applicants=tuple(row["applicants"]),
            applicant_keys=keys, preset=row["preset"],
            preset_label=preset_labels.get(row["preset"]), preset_codes=preset,
            evidence=row["evidence"], evidence_urls=tuple(row["urls"]), protection=protection,
            goods_codes=goods_codes, goods_source=goods_source, marks=tuple(marks)))
    unknown = sorted(set(overrides["brands"]) - {brand.name for brand in brands})
    if unknown:
        raise ValueError(f"overrides 의 브랜드가 등록부에 없습니다: {unknown}")
    known = {mark.appno for brand in brands for mark in brand.marks}
    unknown = sorted(set(overrides["marks"]) - known)
    if unknown:
        raise ValueError(f"overrides 의 출원번호가 등록부에 없습니다: {unknown}")
    return Registry(version=REGISTRY_VERSION, brands=tuple(brands), sources=dict(sources or {}))


def registry_to_json(registry: Registry) -> dict:
    """등록부 → JSON(dict). load_registry 가 그대로 되읽는다."""
    brands = []
    for brand in registry.brands:
        counts: dict[str, int] = {}
        for mark in brand.marks:
            counts[mark.role] = counts.get(mark.role, 0) + 1
        brands.append({
            "name": brand.name,
            "notations": [{"text": n.text, "key": n.key, "pieces": list(n.pieces),
                           "script": n.script, "length": n.length, "kind": n.kind,
                           "base_weak": n.base_weak, "inherits": list(n.inherits),
                           "kind_reason": n.kind_reason,
                           "judgements": list(n.judgements)} for n in brand.notations],
            "applicants": list(brand.applicants),
            "applicant_keys": sorted(brand.applicant_keys),
            "industry": {"preset": brand.preset, "label": brand.preset_label,
                         "codes": sorted(brand.preset_codes)},
            "evidence": {"text": brand.evidence, "urls": list(brand.evidence_urls)},
            "protection": brand.protection,
            "goods": {"source": brand.goods_source, "codes": sorted(brand.goods_codes)},
            "role_counts": counts,
            "marks": [{"appno": m.appno, "title": m.title, "kind": m.kind, "role": m.role,
                       "auto_role": m.auto_role, "source": m.source, "image": m.image,
                       "image_exists": m.image_exists, "codes": sorted(m.codes),
                       "classes": list(m.classes)} for m in brand.marks]})
    return {"version": registry.version, "sources": dict(registry.sources), "brands": brands}


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> Registry:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != REGISTRY_VERSION:
        raise ValueError(f"famous_registry: version 은 {REGISTRY_VERSION} 여야 합니다")
    brands = []
    for item in data["brands"]:
        if item["protection"] not in PROTECTIONS:
            raise ValueError(f"famous_registry: {item['name']} 의 보호 범위를 모릅니다")
        for n in item["notations"]:
            if n["kind"] not in KINDS:
                raise ValueError(f"famous_registry: {n['text']} 의 표기 종류를 모릅니다")
        brands.append(Brand(
            name=item["name"],
            notations=tuple(_notation(n) for n in item["notations"]),
            applicants=tuple(item["applicants"]),
            applicant_keys=frozenset(item["applicant_keys"]),
            preset=item["industry"]["preset"], preset_label=item["industry"].get("label"),
            preset_codes=frozenset(item["industry"]["codes"]),
            evidence=item["evidence"]["text"], evidence_urls=tuple(item["evidence"]["urls"]),
            protection=item["protection"], goods_codes=frozenset(item["goods"]["codes"]),
            goods_source=item["goods"]["source"],
            marks=tuple(Mark(
                appno=m["appno"], title=m.get("title"), kind=m.get("kind"), role=m["role"],
                auto_role=m.get("auto_role", m["role"]), source=m.get("source", SOURCE_FAMOUS),
                image=m.get("image"), image_exists=bool(m.get("image_exists")),
                codes=frozenset(m.get("codes") or ()),
                classes=tuple(m.get("classes") or ())) for m in item["marks"])))
    return Registry(version=data["version"], brands=tuple(brands),
                    sources=dict(data.get("sources") or {}))


# ---- 기준값 ------------------------------------------------------------------------------------

def _per_length(value: float | None = None) -> dict[str, float | None]:
    return {length: value for length in LENGTHS}


@dataclass(frozen=True)
class Thresholds:
    """기준값. None 은 그 경로를 쓰지 않는다는 뜻. 강한 철자·약한 소리·약한 철자는 표기의 길이
    구간별, spelling_sound(S)는 약한 철자 일치가 인정되려면 같은 대상의 소리가 넘어야 하는 값."""

    strong_sound: float | None = STRONG_SOUND
    strong_spelling: Mapping[str, float | None] = field(default_factory=_per_length)
    weak_sound: Mapping[str, float | None] = field(default_factory=_per_length)
    weak_spelling: Mapping[str, float | None] = field(default_factory=_per_length)
    spelling_sound: float | None = None
    contain_other: bool = True  # 품음-기타를 약한 일치로 둘지(결정 대기 — 따로 센다)

    def to_dict(self) -> dict:
        return {"strong_sound": self.strong_sound,
                "strong_spelling": dict(self.strong_spelling),
                "weak_sound": dict(self.weak_sound), "weak_spelling": dict(self.weak_spelling),
                "spelling_sound": self.spelling_sound, "contain_other": self.contain_other}

    @classmethod
    def from_dict(cls, data: Mapping) -> "Thresholds":
        return cls(strong_sound=data.get("strong_sound", STRONG_SOUND),
                   strong_spelling={**_per_length(), **(data.get("strong_spelling") or {})},
                   weak_sound={**_per_length(), **(data.get("weak_sound") or {})},
                   weak_spelling={**_per_length(), **(data.get("weak_spelling") or {})},
                   spelling_sound=data.get("spelling_sound"),
                   contain_other=bool(data.get("contain_other", True)))


def default_goods_floor() -> float:
    """업종 겹침 기준 — 서비스 기본 계수 JSON 의 결합 하한 coupling.floors.x4(0.0252)."""
    from src.model import risk_model as rm

    return float(rm.load_model()["coupling"]["floors"]["x4"])


# ---- 질의 정리 ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class PreparedQuery:
    text: str  # 정리한 이름
    words: tuple[str, ...]  # 낱말의 붙여 쓴 꼴(공백·기호로만 나눔)
    goods: frozenset[str]


def prepare_query(name: object, goods_codes: Iterable[str] | str | None) -> PreparedQuery:
    """이름 정리 — clean_input_name·소문자 → 공백·기호로 낱말. 상품 접미어 분리도, 식별력 필터도
    거치지 않는다."""
    return PreparedQuery(text=normalize_text(name), words=split_words(name),
                         goods=normalize_codes(goods_codes))


def _spans(words: tuple[str, ...]) -> list[tuple[int, int, str]]:
    """낱말 묶음 — (시작, 끝, 붙여 쓴 꼴): 이어진 낱말 1개부터 MAX_BUNDLE_WORDS 개까지."""
    out: list[tuple[int, int, str]] = []
    for start in range(len(words)):
        key = ""
        for stop in range(start + 1, min(len(words), start + MAX_BUNDLE_WORDS) + 1):
            key += words[stop - 1]
            out.append((start, stop, key))
    return out


# ---- 근거(기준값 적용 전) ----------------------------------------------------------------------

@dataclass(frozen=True)
class Evidence:
    """브랜드 표기 하나에 대한 근거 — 기준값을 적용하기 전의 값(기준을 바꿔 가며 다시 판정)."""

    notation: str
    key: str
    length: str
    kind: str
    exact: bool = False
    contain: str | None = None  # "설명" | "기타"
    contain_word: str | None = None
    contain_rest: str | None = None
    units: tuple[tuple[str, float, float], ...] = ()  # 보통 표기: (대상, 소리, 철자)
    weak_use: str | None = None  # 약한 표기: WEAK_USE_ALONE | WEAK_USE_WITH_OTHERS
    foreign_weak: bool | None = None  # 약한 표기: 질의 업종에서도 식별력 없는 말(업종 없으면 None)
    descriptive: bool = False  # 질의 업종에서 이 표기가 식별력 없는 말

    def best(self, index: int) -> tuple[float, str | None]:
        """대상 가운데 소리(index 1)·철자(index 2)가 가장 높은 것 — (점수, 대상)."""
        if not self.units:
            return 0.0, None
        unit = max(self.units, key=lambda item: item[index])
        return unit[index], unit[0]

    @property
    def sound(self) -> float:
        return self.best(1)[0]

    @property
    def spelling(self) -> float:
        return self.best(2)[0]


@dataclass(frozen=True)
class BrandEvidence:
    brand: str
    protection: str
    overlap: bool | None  # 질의 업종과 브랜드 업종의 겹침(질의 업종이 없으면 None)
    overlap_value: float | None
    items: tuple[Evidence, ...]


def _overlap(goods: frozenset[str], brand: Brand, goods_floor: float
             ) -> tuple[bool | None, float | None]:
    if not goods:
        return None, None
    value = max((goods_similarity(goods, codes) for codes in brand.name_goods_sets),
                default=0.0)
    return value >= goods_floor, round(value, 4)


def _attached(words: tuple[str, ...], spans: list[tuple[int, int, str]], key: str,
              descriptive: Callable[[str], bool]) -> list[tuple[int, int, str, str | None]]:
    """표기가 놓인 낱말 묶음 — (시작, 끝, 종류, 나머지): 종류 "같음"(묶음 = 표기), "설명"·"기타"
    (묶음 = 표기 + 나머지 또는 나머지 + 표기 — 나머지는 묶음의 끝 낱말의 뒷부분이거나 첫 낱말의
    앞부분이고, 설명 낱말이면 "설명")."""
    out: list[tuple[int, int, str, str | None]] = []
    for start, stop, joined in spans:
        if joined == key:
            out.append((start, stop, "같음", None))
            continue
        if len(joined) <= len(key):
            continue
        if joined.startswith(key):
            rest = joined[len(key):]
            if len(rest) < len(words[stop - 1]):
                out.append((start, stop, "설명" if descriptive(rest) else "기타", rest))
        if joined.endswith(key):
            rest = joined[:-len(key)]
            if len(rest) < len(words[start]):
                out.append((start, stop, "설명" if descriptive(rest) else "기타", rest))
    return out


def _weak_evidence(query: PreparedQuery, notation: Notation, base: dict,
                   placements: list[tuple[int, int, str, str | None]],
                   descriptive: Callable[[str], bool], dist: Distinctiveness
                   ) -> tuple[Evidence, set[int]]:
    """약한 표기의 근거와, 질의에서 그 표기가 놓인 낱말 번호(가림용). 표기 = 낱말 묶음이거나
    묶음 = 표기 + 설명 낱말인 자리를 찾아, 그 밖의 낱말이 모두 설명 낱말이면 "단독"."""
    use: str | None = None
    covered: set[int] = set()
    for start, stop, kind, _ in placements:
        if kind == "기타":
            continue
        covered.update(range(start, stop))
        others = query.words[:start] + query.words[stop:]
        if all(descriptive(word) for word in others):
            use = WEAK_USE_ALONE
        elif use is None:
            use = WEAK_USE_WITH_OTHERS
    foreign = None
    if use and query.goods:  # 다른 업종에서의 식별력은 종류를 따르는 표기의 것도 본다
        foreign = any(_plain_in(dist, text, query.goods)
                      for text in dict.fromkeys((notation.text, *notation.inherits)))
    return Evidence(**base, weak_use=use, foreign_weak=foreign), covered


def _trimmed(words: tuple[str, ...], descriptive: Callable[[str], bool]
             ) -> tuple[list[list[str]], list[list[str]]]:
    """낱말마다 설명 낱말인 뒷부분들·앞부분들(낱말 전체는 빼고)."""
    tails = [[word[cut:] for cut in range(1, len(word)) if descriptive(word[cut:])]
             for word in words]
    heads = [[word[:cut] for cut in range(1, len(word)) if descriptive(word[:cut])]
             for word in words]
    return tails, heads


def _units(spans: list[tuple[int, int, str]], tails: list[list[str]], heads: list[list[str]],
           masked: set[int], hidden: frozenset[str]) -> list[str]:
    """소리·철자를 견줄 대상 — 낱말 묶음과, 묶음의 앞·뒤 구간으로서 나머지가 설명 낱말인 것.
    가린 낱말이 든 묶음과 약한 표기 그 자체는 뺀다."""
    out: dict[str, None] = {}
    for start, stop, joined in spans:
        if masked and not masked.isdisjoint(range(start, stop)):
            continue
        out.setdefault(joined)
        for rest in tails[stop - 1]:
            out.setdefault(joined[:-len(rest)])
        for rest in heads[start]:
            out.setdefault(joined[len(rest):])
    return [unit for unit in out if unit and unit not in hidden]


def _brand_evidence(query: PreparedQuery, brand: Brand, dist: Distinctiveness,
                    goods_floor: float, words: frozenset[str], similarity: bool
                    ) -> BrandEvidence:
    descriptive = _descriptive_checker(dist, query.goods, brand.name_goods_codes, words)
    spans = _spans(query.words)
    overlap, value = _overlap(query.goods, brand, goods_floor)
    items: dict[str, Evidence] = {}
    masked: set[int] = set()
    for notation in brand.notations:  # 약한 표기 먼저 — 그 자리는 다른 표기에서 가린다
        if notation.kind != KIND_WEAK or not notation.key:
            continue
        base = dict(notation=notation.text, key=notation.key, length=notation.length,
                    kind=notation.kind)
        placements = _attached(query.words, spans, notation.key, descriptive)
        items[notation.text], covered = _weak_evidence(
            query, notation, base, placements, descriptive, dist)
        masked |= covered
    hidden = frozenset(n.key for n in brand.notations if n.kind == KIND_WEAK and n.key)
    open_spans = [span for span in spans if masked.isdisjoint(range(span[0], span[1]))]
    units: list[str] | None = None
    for notation in brand.notations:
        if notation.kind == KIND_WEAK:
            continue
        base = dict(notation=notation.text, key=notation.key, length=notation.length,
                    kind=notation.kind)
        if not notation.key:
            items[notation.text] = Evidence(**base)
            continue
        exact, contain, word_hit, rest_hit = False, None, None, None
        for start, stop, kind, rest in _attached(query.words, open_spans, notation.key,
                                                 descriptive):
            if kind == "같음":
                exact = True
            elif kind == "기타" and (notation.kind != KIND_NORMAL
                                    or notation.length == LENGTH_SHORT):
                continue  # 품음-기타는 보통 표기만, 짧은 표기는 인정하지 않는다
            elif contain is None or (kind == "설명" and contain == "기타"):
                contain, rest_hit = kind, rest
                word_hit = "".join(query.words[start:stop])
        scored: list[tuple[str, float, float]] = []
        if similarity and notation.kind == KIND_NORMAL:
            if units is None:
                tails, heads = _trimmed(query.words, descriptive)
                units = _units(spans, tails, heads, masked, hidden)
            for unit in units:
                sound = whole_sound(unit, notation.key)
                spelling = (whole_spelling(unit, notation.key)
                            if script_label(unit) == notation.script else 0.0)
                if sound >= UNIT_MIN_SOUND or spelling >= UNIT_MIN_SPELLING:
                    scored.append((unit, round(sound, 4), round(spelling, 4)))
        plain = bool(query.goods) and bool(notation.pieces) and all(
            _weak(dist, piece, query.goods) for piece in notation.pieces)
        items[notation.text] = Evidence(
            **base, exact=exact, contain=contain, contain_word=word_hit,
            contain_rest=rest_hit, units=tuple(scored), descriptive=plain)
    return BrandEvidence(brand=brand.name, protection=brand.protection, overlap=overlap,
                         overlap_value=value,
                         items=tuple(items[n.text] for n in brand.notations))


def collect_evidence(query: PreparedQuery, registry: Registry, dist: Distinctiveness,
                     goods_floor: float, *, similarity: bool = True,
                     words: frozenset[str] | None = None) -> list[BrandEvidence]:
    """질의와 등록부의 모든 브랜드 표기 사이의 근거. similarity=False 면 (가)(나)만(이미지 속 글자).
    words 는 업종 낱말 사전(기본: 저장소의 업종 세트에서 만든 것). 근거가 하나도 없는 브랜드도
    돌려준다(기준값 적용은 decide)."""
    words = industry_words() if words is None else words
    return [_brand_evidence(query, brand, dist, goods_floor, words, similarity)
            for brand in registry.brands]


# ---- 판정 --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class BrandMatch:
    brand: str
    level: str  # 강함 | 약함 | 설명적 사용 안내
    path: str  # 같음 | 품음-설명 | 품음-기타 | 소리 | 철자
    notation: str
    score: float
    floor: str | None  # 이 일치가 주는 전체 등급 바닥(없으면 None)
    protection: str
    overlap: bool | None
    pending: bool = False  # 품음-기타(결정 대기)
    note: str = ""
    basis: str = BASIS_NAME
    kind: str = KIND_NORMAL  # 일치한 표기의 종류

    @property
    def order(self) -> tuple[int, int, float]:
        return (_LEVEL_RANK[self.level], _PATH_RANK[self.path], self.score)


@dataclass(frozen=True)
class FamousResult:
    matches: tuple[BrandMatch, ...]  # 브랜드마다 가장 강한 일치 하나, 강한 것부터
    strongest: BrandMatch | None
    floor: str | None  # 전체 등급 바닥(위험 | 검토 권장 | None)
    basis: str


def _floor(level: str, protection: str, overlap: bool | None) -> str | None:
    if level == LEVEL_NOTICE:
        return None
    near_and_different = protection == PROTECT_NEAR and overlap is False
    if level == LEVEL_STRONG:
        return GRADE_REVIEW if near_and_different else GRADE_RISK
    return None if near_and_different else GRADE_REVIEW


def _candidates(item: Evidence, overlap: bool | None, thresholds: Thresholds
                ) -> list[tuple[str, str, float, bool, str]]:
    """표기 하나에서 나오는 (수준, 경로, 점수, 결정 대기, 메모) 후보."""
    if item.kind == KIND_WEAK:
        if item.weak_use == WEAK_USE_ALONE:
            if overlap is False and item.foreign_weak:
                return [(LEVEL_NOTICE, PATH_EXACT, 1.0, False,
                         "약한 표기 — 업종이 다르고 그 업종에서도 식별력 없는 말")]
            note = ("약한 표기 — 업종이 다르지만 그 업종에서는 식별력 있음"
                    if overlap is False else "약한 표기 — 그 표기 하나뿐")
            return [(LEVEL_STRONG, PATH_EXACT, 1.0, False, note)]
        if item.weak_use == WEAK_USE_WITH_OTHERS:
            return [(LEVEL_NOTICE, PATH_EXACT, 1.0, False, "약한 표기 — 다른 말과 함께")]
        return []
    out: list[tuple[str, str, float, bool, str]] = []
    if item.exact:
        out.append((LEVEL_STRONG, PATH_EXACT, 1.0, False, ""))
    if item.contain == "설명":
        out.append((LEVEL_STRONG, PATH_CONTAIN_DESC, 1.0, False,
                    f"{item.contain_word} = 표기 + {item.contain_rest}"))
    if item.kind == KIND_NORMAL:  # 머리글자 표기는 같음·품음-설명만
        sound, sound_unit = item.best(1)
        spelling, spelling_unit = item.best(2)
        if thresholds.strong_sound is not None and sound >= thresholds.strong_sound:
            out.append((LEVEL_STRONG, PATH_SOUND, sound, False, sound_unit or ""))
        strong_spelling = thresholds.strong_spelling.get(item.length)
        if strong_spelling is not None and spelling >= strong_spelling:
            out.append((LEVEL_STRONG, PATH_SPELLING, spelling, False, spelling_unit or ""))
        weak_sound = thresholds.weak_sound.get(item.length)
        if weak_sound is not None and sound >= weak_sound:
            out.append((LEVEL_WEAK, PATH_SOUND, sound, False, sound_unit or ""))
        weak_spelling = thresholds.weak_spelling.get(item.length)
        if weak_spelling is not None:
            floor = thresholds.spelling_sound  # 약한 철자는 같은 대상의 소리가 S 이상일 때만
            usable = [unit for unit in item.units
                      if unit[2] >= weak_spelling and (floor is None or unit[1] >= floor)]
            if usable:
                unit = max(usable, key=lambda entry: entry[2])
                out.append((LEVEL_WEAK, PATH_SPELLING, unit[2], False, unit[0]))
        if item.contain == "기타" and thresholds.contain_other:
            out.append((LEVEL_WEAK, PATH_CONTAIN_OTHER, 1.0, True,
                        f"{item.contain_word} = 표기 + {item.contain_rest}"))
    if item.descriptive and overlap is False:  # 그 밖의 설명적 사용
        out = [(LEVEL_NOTICE, path, score, pending, "질의 업종에서 식별력 없는 말 — 업종이 다름")
               for _, path, score, pending, _ in out]
    return out


def decide(evidence: Iterable[BrandEvidence], thresholds: Thresholds, *,
           basis: str = BASIS_NAME) -> FamousResult:
    """근거에 기준값을 적용 — 브랜드마다 가장 강한 일치, 그중 가장 강한 것, 전체 등급 바닥."""
    matches: list[BrandMatch] = []
    for brand in evidence:
        best: BrandMatch | None = None
        for item in brand.items:
            for level, path, score, pending, note in _candidates(item, brand.overlap,
                                                                 thresholds):
                match = BrandMatch(
                    brand=brand.brand, level=level, path=path, notation=item.notation,
                    score=round(float(score), 4),
                    floor=_floor(level, brand.protection, brand.overlap),
                    protection=brand.protection, overlap=brand.overlap, pending=pending,
                    note=note, basis=basis, kind=item.kind)
                if best is None or match.order > best.order:
                    best = match
        if best is not None:
            matches.append(best)
    matches.sort(key=lambda match: match.order, reverse=True)
    floors = [match.floor for match in matches if match.floor]
    floor = max(floors, key=GRADES.index) if floors else None
    return FamousResult(matches=tuple(matches), strongest=matches[0] if matches else None,
                        floor=floor, basis=basis)


def check_famous(
    name: object, goods_codes: Iterable[str] | str | None, registry: Registry,
    thresholds: Thresholds, *, dist: Distinctiveness | None = None,
    goods_floor: float | None = None, ocr_text: object = None,
    words: frozenset[str] | None = None,
) -> FamousResult:
    """유명 상표 일치 판정. 질의 이름이 없고 이미지에서 읽은 글자(ocr_text — OCR 제안 상표명)가
    있으면 그 글자로 (가)(나)만 판정해 "이미지 속 글자 기준"으로 표시한다. 이름도 글자도 없으면
    빈 결과."""
    dist = dist or load_distinctiveness()
    floor = default_goods_floor() if goods_floor is None else float(goods_floor)
    if normalize_text(name):
        query = prepare_query(name, goods_codes)
        return decide(collect_evidence(query, registry, dist, floor, words=words), thresholds)
    if normalize_text(ocr_text):
        query = prepare_query(ocr_text, goods_codes)
        evidence = collect_evidence(query, registry, dist, floor, similarity=False, words=words)
        return decide(evidence, thresholds, basis=BASIS_OCR)
    return FamousResult(matches=(), strongest=None, floor=None, basis=BASIS_NAME)
