"""질의 이름의 낱말별 식별력 판정을 응답에 실을 꼴로 옮긴다 — 설명적 이름 안내(API 계약 v2 §2-7,
식별력 설계 §9).

여기서는 판정하지 않는다. 식별력 모듈(`src.axes.distinctiveness`)이 낸 낱말별 판정
(`TokenJudgement` — 낱말·점수·사유)을 그대로 받아 세 가지만 정리한다.

    ① 식별력이 있는가 — `TokenJudgement.is_weak`(점수 < θ)의 반대. 엔진이 요부 후보를 고를 때
       (`Distinctiveness.salient_tokens`·`weak_tokens`)와 같은 기준이다. 유명 브랜드 예외로 1.0 을
       받은 낱말은 엔진과 같게 식별력 있음.
    ② 화면에 보일 사유 분류 — 엔진의 사유 코드를 여섯 가지(+ "그 밖")로 묶는다(`REASON_CATEGORIES`).
    ③ 모든 낱말이 식별력 없는 말인지, 일부만 그런지(`NameWords.generic`).

엔진(backend/src/core/multi_search.py)은 후보마다 요부를 정할 때 쓰는 것과 같은 함수
(`Distinctiveness.judge_name` — 상품 접미어 분리 뒤의 낱말)를 **질의의 이름과 질의의 업종만으로**
불러 그 결과를 넘긴다. 후보와 견줄 때는 엔진이 후보의 업종까지 합쳐 판정하므로(1호·3호는 상품에
상대적) 후보에 따라 낱말이 더 빠질 수 있다 — 그 쌍별 결과는 지금처럼 `candidates[].salient` 에
있다.

사유 코드(`TokenJudgement.reasons` 한 항목의 머리)와 분류

    1호 보통명칭 · 1호 보통명칭(전역)                       → 상품 이름
    3호 기술적 표장(절대):종류 · 3호 기술적 표장:종류(류 …)  → 성질·품질
    4호 지명                                               → 지역 이름
    5호 흔한 성                                            → 흔한 성·이름
    6호 간단 표장                                          → 짧고 흔한 글자
    일반어(zipf …) · 다수 등록(A=…, N=…) — 점수가 θ 미만일 때 → 흔히 쓰는 말
    그 밖의 코드(지금은 "빈 토큰"뿐 — 이름에서 나온 낱말에는 붙지 않는다)  → 그 밖

    식별력 있는 낱말에만 붙는 코드(분류 없음): 유명 브랜드 · 조어 · 사람 검토 제외(…) ·
    3호 기술적 표장(상품 미상|류 미지정):종류(점수를 0.5 로 누르기만 한다 — 0.5 는 θ 이상)

한 낱말에 사유가 여럿이면 위 표의 순서에서 먼저 맞는 분류를 쓴다("커피"가 카페 업종에서
`3호 기술적 표장:원재료·1호 보통명칭` 이면 상품 이름). 상품 접미어로 뗀 낱말(블루커피 → 블루 /
커피)은 따로 표시하지 않는다 — 떼어 낸 뒤의 낱말로 판정되어 그 업종의 고시 명칭이면 1호(상품 이름),
아니면 다른 사유로 분류된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

__all__ = [
    "CATEGORIES", "CATEGORY_COMMON", "CATEGORY_GOODS", "CATEGORY_OTHER", "CATEGORY_PERSON",
    "CATEGORY_PLACE", "CATEGORY_QUALITY", "CATEGORY_SHORT", "CAP_REASONS", "GENERIC_ALL",
    "GENERIC_NONE", "GENERIC_SOME", "NameWords", "REASON_CATEGORIES", "REASON_CODES",
    "STRONG_REASONS", "WORD_LIMIT", "Word", "category", "describe", "reason_code",
]

# ---- 화면용 사유 분류(응답의 값 그대로) -------------------------------------------------------
CATEGORY_GOODS = "상품 이름"
CATEGORY_QUALITY = "성질·품질"
CATEGORY_COMMON = "흔히 쓰는 말"
CATEGORY_PLACE = "지역 이름"
CATEGORY_PERSON = "흔한 성·이름"
CATEGORY_SHORT = "짧고 흔한 글자"
CATEGORY_OTHER = "그 밖"
CATEGORIES: tuple[str, ...] = (
    CATEGORY_GOODS, CATEGORY_QUALITY, CATEGORY_COMMON, CATEGORY_PLACE, CATEGORY_PERSON,
    CATEGORY_SHORT, CATEGORY_OTHER,
)

# 엔진의 사유 코드(머리) → 분류. 한 낱말에 사유가 여럿이면 이 순서에서 먼저 맞는 것
REASON_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("1호 보통명칭", CATEGORY_GOODS),  # "1호 보통명칭" · "1호 보통명칭(전역)"
    ("3호 기술적 표장", CATEGORY_QUALITY),  # "(절대):종류" · ":종류(류 …)" — 아래 상한 사유는 뺀다
    ("4호 지명", CATEGORY_PLACE),
    ("5호 흔한 성", CATEGORY_PERSON),
    ("6호 간단 표장", CATEGORY_SHORT),
    ("다수 등록", CATEGORY_COMMON),
    ("일반어", CATEGORY_COMMON),
)
# 점수를 0.5 로 누르기만 하는 사유 — 낱말을 약하게 만들지 못해(0.5 는 θ 이상) 분류에 쓰지 않는다
CAP_REASONS: tuple[str, ...] = ("3호 기술적 표장(상품 미상)", "3호 기술적 표장(류 미지정)")
# 식별력이 있다는 사유 — 약한 낱말에는 붙지 않는다
STRONG_REASONS: tuple[str, ...] = ("유명 브랜드", "사람 검토 제외", "조어")
# 엔진이 내는 사유 코드 전부(긴 머리부터 — reason_code 가 앞에서부터 맞춘다)
REASON_CODES: tuple[str, ...] = (
    "3호 기술적 표장(절대)", *CAP_REASONS, "3호 기술적 표장", "1호 보통명칭(전역)",
    "1호 보통명칭", "4호 지명", "5호 흔한 성", "6호 간단 표장", "일반어", "다수 등록",
    *STRONG_REASONS, "빈 토큰",
)

WORD_LIMIT = 6  # 응답에 싣는 낱말 수의 상한 — 넘는 낱말은 수만 싣는다
GENERIC_ALL = "all"  # 모든 낱말이 낱말 단위로 식별력 없는 말
GENERIC_SOME = "some"  # 일부만
GENERIC_NONE = "none"  # 없음(낱말이 하나도 없을 때도)


def reason_code(reason: str) -> str:
    """사유 원문 한 항목의 코드("3호 기술적 표장:품질(류 30,43)" → "3호 기술적 표장"). 모르는
    사유는 원문 그대로."""
    text = str(reason)
    return next((code for code in REASON_CODES if text.startswith(code)), text)


def category(reasons: Iterable[str]) -> str:
    """식별력 없는 낱말의 화면용 분류 — REASON_CATEGORIES 의 순서에서 먼저 맞는 것, 없으면 그 밖."""
    codes = {reason_code(reason) for reason in reasons} - set(CAP_REASONS)
    for head, name in REASON_CATEGORIES:
        if any(code.startswith(head) for code in codes):
            return name
    return CATEGORY_OTHER


@dataclass(frozen=True, slots=True)
class Word:
    """낱말 하나 — 엔진의 낱말 꼴(정규화: 소문자·문자 종류 경계 분리) 그대로."""

    word: str
    distinctive: bool
    category: str | None  # 식별력이 없을 때만(화면용 분류)
    reason: str  # 엔진의 사유 원문("·" 로 이음 — candidates[].salient.removed[].reason 과 같은 꼴)

    def to_dict(self) -> dict:
        return {"word": self.word, "distinctive": self.distinctive, "category": self.category,
                "reason": self.reason}


@dataclass(frozen=True, slots=True)
class NameWords:
    """질의 이름의 낱말별 판정(이름 순서, 같은 낱말은 한 번)."""

    words: tuple[Word, ...]

    @property
    def generic(self) -> str:
        """식별력 없는 낱말이 전부(all)·일부(some)·없음(none)."""
        weak = sum(1 for word in self.words if not word.distinctive)
        if not weak:
            return GENERIC_NONE
        return GENERIC_ALL if weak == len(self.words) else GENERIC_SOME

    def to_dict(self, limit: int = WORD_LIMIT) -> dict:
        """응답의 name_words(계약 v2 §2-7) — 낱말은 앞에서 limit 개까지, 나머지는 수만."""
        rest = self.words[limit:]
        return {
            "generic": self.generic,
            "words": [word.to_dict() for word in self.words[:limit]],
            "more": len(rest),
            "more_generic": sum(1 for word in rest if not word.distinctive),
        }


def describe(judgements: Iterable) -> NameWords:
    """`Distinctiveness.judge_name` 의 결과(TokenJudgement 목록)를 응답에 실을 꼴로. 판정 값은
    바꾸지 않는다 — 식별력 여부는 is_weak 그대로, 분류는 사유 코드에서."""
    words: list[Word] = []
    seen: set[str] = set()
    for judgement in judgements:
        if judgement.token in seen:  # 같은 낱말이 떨어져 두 번 나오면 한 번만
            continue
        seen.add(judgement.token)
        weak = bool(judgement.is_weak)
        words.append(Word(
            word=judgement.token, distinctive=not weak,
            category=category(judgement.reasons) if weak else None,
            reason="·".join(judgement.reasons)))
    return NameWords(tuple(words))
