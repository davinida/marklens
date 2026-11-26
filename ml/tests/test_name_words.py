"""src.name_words — 질의 이름의 낱말별 식별력 판정을 응답에 실을 꼴로(설명적 이름 안내).

판정은 식별력 모듈의 것 그대로이고 여기서는 분류·정리만 본다. 식별력 모델은 시험 안에서 작은
자료로 직접 만든다(저장소의 shared 자산이나 환경 변수에 기대지 않게).
"""

from __future__ import annotations

import pytest
from src import name_words as nw
from src.axes.distinctiveness import (
    DESCRIPTIVE_KINDS,
    DescriptiveTerm,
    Distinctiveness,
    TokenJudgement,
)


def _judged(token: str, score: float, *reasons: str) -> TokenJudgement:
    return TokenJudgement(token, score, tuple(reasons))


def _model() -> Distinctiveness:
    """커피(30류 G0301)·가방(18류 G2501) 고시 명칭, 3호 '맛있는'(품질, 29·30·43류)·'best'(절대),
    다수 등록 '행복한', 유명 브랜드 '스타벅스'."""
    return Distinctiveness(
        {"행복한": (14, 30), "블루": (2, 2)},
        famous=["스타벅스"],
        goods_names={"커피": ((30, frozenset({"G0301"})),), "가방": ((18, frozenset({"G2501"})),)},
        code_classes={"G0301": frozenset({30}), "G2501": frozenset({18}),
                      "S120602": frozenset({43})},
        descriptive={
            "맛있는": DescriptiveTerm("품질", False, frozenset({29, 30, 43})),
            "best": DescriptiveTerm("품질", True),
        },
    )


# ---- 사유 코드 → 분류 ----------------------------------------------------------------------------

@pytest.mark.parametrize(("reasons", "expected"), [
    (("1호 보통명칭",), nw.CATEGORY_GOODS),
    (("1호 보통명칭(전역)",), nw.CATEGORY_GOODS),
    (("3호 기술적 표장(절대):품질",), nw.CATEGORY_QUALITY),
    (("3호 기술적 표장:용도(류 35,43)",), nw.CATEGORY_QUALITY),
    (("4호 지명",), nw.CATEGORY_PLACE),
    (("5호 흔한 성",), nw.CATEGORY_PERSON),
    (("6호 간단 표장",), nw.CATEGORY_SHORT),
    (("일반어(zipf 5.1)", "다수 등록(A=53, N=54)"), nw.CATEGORY_COMMON),
    (("다수 등록(A=11, N=11)",), nw.CATEGORY_COMMON),
    (("빈 토큰",), nw.CATEGORY_OTHER),
    (("앞으로 생길 사유",), nw.CATEGORY_OTHER),
    ((), nw.CATEGORY_OTHER),
])
def test_category_of_each_reason_code(reasons, expected):
    assert nw.category(reasons) == expected


@pytest.mark.parametrize(("reasons", "expected"), [
    # 사유가 여럿이면 1호 > 3호 > 4호 > 5호 > 6호 > 통계 — 엔진의 사유 나열 순서(3호가 앞)와 다르다
    (("3호 기술적 표장:원재료(류 30,35,43)", "1호 보통명칭"), nw.CATEGORY_GOODS),
    (("1호 보통명칭(전역)", "4호 지명"), nw.CATEGORY_GOODS),
    (("3호 기술적 표장(절대):품질", "6호 간단 표장"), nw.CATEGORY_QUALITY),
    (("5호 흔한 성", "6호 간단 표장"), nw.CATEGORY_PERSON),
    (("4호 지명", "5호 흔한 성"), nw.CATEGORY_PLACE),
])
def test_category_priority_when_several_reasons(reasons, expected):
    assert nw.category(reasons) == expected


def test_cap_reasons_do_not_decide_the_category():
    """점수를 0.5 로 누르기만 하는 3호 사유(상품 미상·류 미지정)는 낱말을 약하게 만들지 못한다 —
    분류에 쓰지 않는다(약한 낱말에 붙는 일은 없지만, 붙더라도 다른 사유로 분류)."""
    capped = ("다수 등록(A=20, N=40)", "3호 기술적 표장(상품 미상):품질")
    assert nw.category(capped) == nw.CATEGORY_COMMON
    assert nw.category(("3호 기술적 표장(류 미지정):시기",)) == nw.CATEGORY_OTHER


def test_reason_codes_cover_every_code_the_judgement_can_emit():
    """식별력 모듈이 내는 사유를 모두 코드로 읽는다 — 새 사유가 생기면 여기서 드러난다."""
    samples = {
        "빈 토큰": "빈 토큰", "유명 브랜드": "유명 브랜드", "조어": "조어",
        "1호 보통명칭": "1호 보통명칭", "1호 보통명칭(전역)": "1호 보통명칭(전역)",
        "4호 지명": "4호 지명", "5호 흔한 성": "5호 흔한 성", "6호 간단 표장": "6호 간단 표장",
        "일반어(zipf 4.6)": "일반어", "다수 등록(A=4, N=4)": "다수 등록",
        "사람 검토 제외(weak_token_overrides)": "사람 검토 제외",
    }
    for kind in DESCRIPTIVE_KINDS:
        samples[f"3호 기술적 표장(절대):{kind}"] = "3호 기술적 표장(절대)"
        samples[f"3호 기술적 표장(상품 미상):{kind}"] = "3호 기술적 표장(상품 미상)"
        samples[f"3호 기술적 표장(류 미지정):{kind}"] = "3호 기술적 표장(류 미지정)"
        samples[f"3호 기술적 표장:{kind}(류 30,43)"] = "3호 기술적 표장"
    for reason, code in samples.items():
        assert nw.reason_code(reason) == code, reason
    assert set(samples.values()) == set(nw.REASON_CODES)
    assert nw.reason_code("모르는 사유") == "모르는 사유"
    # 분류표의 머리는 모두 실제 코드의 머리이고, 식별력 있는 사유는 분류표에 없다
    for head, name in nw.REASON_CATEGORIES:
        assert any(code.startswith(head) for code in nw.REASON_CODES) and name in nw.CATEGORIES
    for code in nw.STRONG_REASONS:
        assert not any(code.startswith(head) for head, _ in nw.REASON_CATEGORIES)


# ---- 정리 ----------------------------------------------------------------------------------------

def test_describe_keeps_the_judgement_and_orders_by_name():
    words = nw.describe([
        _judged("블루", 0.62, "일반어(zipf 4.6)", "다수 등록(A=4, N=4)"),
        _judged("커피", 0.0, "3호 기술적 표장:원재료(류 30,35,43)", "1호 보통명칭"),
    ])
    assert [w.to_dict() for w in words.words] == [
        {"word": "블루", "distinctive": True, "category": None,
         "reason": "일반어(zipf 4.6)·다수 등록(A=4, N=4)"},
        {"word": "커피", "distinctive": False, "category": "상품 이름",
         "reason": "3호 기술적 표장:원재료(류 30,35,43)·1호 보통명칭"},
    ]
    assert words.generic == nw.GENERIC_SOME
    assert words.to_dict() == {"generic": "some", "words": [w.to_dict() for w in words.words],
                               "more": 0, "more_generic": 0}


def test_generic_scope():
    weak = _judged("커피", 0.0, "1호 보통명칭")
    strong = _judged("스타벅스", 1.0, "유명 브랜드")
    assert nw.describe([weak]).generic == nw.GENERIC_ALL
    both = [weak, _judged("전문점", 0.0, "3호 기술적 표장:용도(류 43)")]
    assert nw.describe(both).generic == nw.GENERIC_ALL
    assert nw.describe([strong, weak]).generic == nw.GENERIC_SOME
    assert nw.describe([strong]).generic == nw.GENERIC_NONE
    assert nw.describe([]).generic == nw.GENERIC_NONE  # 낱말이 하나도 없으면(한자뿐인 이름 등)
    assert nw.describe([]).to_dict() == {"generic": "none", "words": [], "more": 0,
                                         "more_generic": 0}


def test_threshold_is_the_engines_weak_test():
    """식별력 여부는 TokenJudgement.is_weak(점수 < θ) 그대로 — 0.5 는 식별력 있음."""
    at_threshold = _judged("수제", 0.5, "일반어(zipf 3.9)", "3호 기술적 표장(류 미지정):생산방법")
    below = _judged("한의원", 0.45, "다수 등록(A=11, N=11)")
    described = nw.describe([at_threshold, below]).words
    assert [w.distinctive for w in described] == [True, False]
    assert [w.category for w in described] == [None, nw.CATEGORY_COMMON]


def test_repeated_word_is_listed_once():
    coffee = _judged("커피", 0.0, "1호 보통명칭")
    words = nw.describe([coffee, _judged("블루", 1.0, "조어"), coffee])
    assert [w.word for w in words.words] == ["커피", "블루"]
    assert words.generic == nw.GENERIC_SOME


def test_more_than_six_words_are_counted_not_listed():
    judged = [_judged(f"낱말{i}", 0.0 if i % 2 else 1.0, "4호 지명" if i % 2 else "조어")
              for i in range(9)]
    data = nw.describe(judged).to_dict()
    assert [w["word"] for w in data["words"]] == [f"낱말{i}" for i in range(nw.WORD_LIMIT)]
    assert data["more"] == 3 and data["more_generic"] == 1  # 낱말6·7·8 가운데 낱말7
    assert data["generic"] == "some"  # 구분은 싣지 않은 낱말까지 보고 정한다
    all_weak = nw.describe([_judged(f"w{i}", 0.0, "6호 간단 표장") for i in range(8)]).to_dict()
    assert (all_weak["generic"], all_weak["more"], all_weak["more_generic"]) == ("all", 2, 2)
    assert nw.describe(judged).to_dict(limit=2)["more"] == 7


# ---- 식별력 모듈의 판정과 이어서 -----------------------------------------------------------------

def test_follows_the_distinctiveness_judgement_for_the_querys_goods():
    model = _model()
    cafe = {"G0301", "S120602"}

    def described(name, goods):
        return nw.describe(model.judge_name(name, goods))

    # 접미어로 뗀 낱말(블루커피 → 블루 / 커피)도 낱말로 실린다 — 카페에서는 상품 이름
    blue = described("블루커피", cafe)
    assert [(w.word, w.distinctive, w.category) for w in blue.words] == [
        ("블루", True, None), ("커피", False, nw.CATEGORY_GOODS)]
    assert blue.generic == nw.GENERIC_SOME
    # 모든 낱말이 설명하는 말
    tasty = described("맛있는 커피", cafe)
    assert [(w.word, w.category) for w in tasty.words] == [
        ("맛있는", nw.CATEGORY_QUALITY), ("커피", nw.CATEGORY_GOODS)]
    assert tasty.generic == nw.GENERIC_ALL
    # 유명 브랜드 예외는 엔진과 같게 식별력 있음
    famous = described("스타벅스 커피", cafe)
    assert [(w.word, w.distinctive, w.reason) for w in famous.words][0] == (
        "스타벅스", True, "유명 브랜드")
    assert famous.generic == nw.GENERIC_SOME
    # 업종이 다르면 같은 낱말도 달라진다(가방 업종에서 커피는 상품 이름이 아니다)
    bag = described("커피", {"G2501"})
    assert bag.words[0].distinctive is True and bag.generic == nw.GENERIC_NONE
    # 절대적 기술 표장·흔히 쓰는 말·짧은 글자는 업종과 무관
    plain = described("Best 행복한 24", None)
    assert [(w.word, w.category) for w in plain.words] == [
        ("best", nw.CATEGORY_QUALITY), ("행복한", nw.CATEGORY_COMMON), ("24", nw.CATEGORY_SHORT)]
    assert [w.reason for w in plain.words] == [
        "3호 기술적 표장(절대):품질", "다수 등록(A=14, N=30)", "6호 간단 표장"]
    # 상대적 기술 표장은 그 류의 업종에서만(맛있는 — 카페의 30·43류), 업종을 모르면 누르기만 한다
    assert described("맛있는", cafe).words[0].reason == "3호 기술적 표장:품질(류 30,43)"
    assert described("맛있는", None).words[0].distinctive is True
    # 실린 값은 판정 그대로다
    for name, goods in (("블루커피", cafe), ("맛있는 커피", cafe), ("Best 행복한 24", None)):
        judged = model.judge_name(name, goods)
        assert [(w.word, w.distinctive, w.reason) for w in described(name, goods).words] == [
            (j.token, not j.is_weak, "·".join(j.reasons)) for j in judged]
