"""name_words_check.py(설명적 이름 안내의 확인 — 식별력 설계 §9)의 순수 함수: 화면이 고르는 안내,
맨 위 영역의 순서, 한 줄들이 사실인지, 고치기 전·후 응답 견주기. 실제 엔진을 쓰는 queries·dump·run
명령은 시험하지 않는다."""

from __future__ import annotations

import copy

from scripts import name_words_check as nc


def _word(text: str, category: str | None) -> dict:
    return {"word": text, "distinctive": category is None, "category": category, "reason": "시험"}


def _response(words: list[dict] | None = None, *, generic: str | None = None,
              famous: list[dict] | None = None, status: str = "checked",
              removed: list[list[tuple[str, str]]] | None = None) -> dict:
    """후보 둘(이름 있는 것 하나·없는 것 하나)의 응답 — removed 는 후보별 (낱말, side) 목록."""
    removed = removed or [[], []]
    data = {
        "overall": {"grade": "주의", "prob": 0.3},
        "candidates": [
            {"id": f"402020000000{i}", "title": "상표" if i == 0 else None,
             "salient": {"query_tokens": [], "candidate_tokens": [],
                         "removed": [{"token": t, "reason": "시험", "side": s} for t, s in items]}}
            for i, items in enumerate(removed)],
        "meta": {"model_version": "x"},
    }
    if words is not None:
        weak = sum(1 for w in words if not w["distinctive"])
        scope = "none" if not weak else ("all" if weak == len(words) else "some")
        data["name_words"] = {"generic": generic or scope, "words": words, "more": 0,
                              "more_generic": 0}
    if famous is not None:
        data["famous"] = {"status": status, "brand_count": 58, "matches": famous}
    return data


ALL = [_word("맛있는", "성질·품질"), _word("커피", "상품 이름")]
SOME = [_word("블루", None), _word("커피", "상품 이름")]
COMMON_ONLY = [_word("fox", "흔히 쓰는 말"), _word("books", "흔히 쓰는 말")]
REMOVED = [[("커피", "query")], []]  # 이름 있는 후보에서 '커피'를 뺌(둘째 후보는 이름이 없다)


def _match(level: str, brand: str = "김가네", basis: str = "이름") -> dict:
    return {"brand": brand, "level": level, "basis": basis}


LOGO = _match("강함", basis="로고")  # 로고로만 강한 일치 — 배너 아래에 안내가 그대로 온다


def test_notice_kind_follows_the_screen_rule():
    assert nc.notice_kind(_response(ALL)) == nc.NOTICE_BIG
    assert nc.notice_kind(_response(ALL, famous=[])) == nc.NOTICE_BIG
    assert nc.notice_kind(_response(ALL, famous=[LOGO])) == nc.NOTICE_ALL_SMALL_FAMOUS
    assert nc.notice_kind(_response(ALL, famous=[_match("약함")])) == nc.NOTICE_ALL_SMALL_FAMOUS
    # 설명적 사용 배너는 강함·약함이 아니다 — 큰 안내 그대로
    assert nc.notice_kind(_response(ALL, famous=[_match("설명적 사용")])) == nc.NOTICE_BIG
    # 확인하지 못함이면 배너가 없다
    unavailable = _response(ALL, famous=[_match("강함")], status="unavailable")
    assert nc.notice_kind(unavailable) == nc.NOTICE_BIG
    assert nc.notice_kind(_response([_word("스타벅스", None)])) == nc.NOTICE_NONE
    assert nc.notice_kind(_response([])) == nc.NOTICE_NONE
    assert nc.notice_kind(_response()) == nc.NOTICE_NONE  # 이름 없는 질의·옛 서버
    assert nc.notice_kind(_response(ALL, generic="most")) == nc.NOTICE_NONE


def test_big_notice_needs_a_word_that_is_not_just_common():
    """모든 낱말이 식별력 없는 말이어도 '흔히 쓰는 말'뿐이면 큰 안내가 아니라 작은 안내."""
    assert nc.notice_kind(_response(COMMON_ONLY)) == nc.NOTICE_ALL_SMALL_COMMON
    for category in sorted(nc.BIG_NOTICE_CATEGORIES):
        mixed = [*COMMON_ONLY, _word("낱말", category)]
        assert nc.notice_kind(_response(mixed)) == nc.NOTICE_BIG, category
    assert nc.notice_kind(_response([*COMMON_ONLY, _word("낱말", "그 밖")])) == (
        nc.NOTICE_ALL_SMALL_COMMON)
    assert "흔히 쓰는 말" not in nc.BIG_NOTICE_CATEGORIES and len(nc.BIG_NOTICE_CATEGORIES) == 5
    # 유명 상표 배너가 있으면 그쪽 이름으로 센다
    famous = _response(COMMON_ONLY, famous=[_match("약함")])
    assert nc.notice_kind(famous) == nc.NOTICE_ALL_SMALL_FAMOUS


def test_some_notice_only_when_the_words_were_removed_for_every_shown_candidate():
    assert nc.notice_kind(_response(SOME, removed=REMOVED)) == nc.NOTICE_SOME
    assert nc.notice_kind(_response(SOME)) == nc.NOTICE_SOME_HIDDEN
    for match in (_match("약함"), LOGO):
        assert nc.notice_kind(_response(SOME, removed=REMOVED, famous=[match])) == nc.NOTICE_SOME


def test_no_notice_when_the_famous_banner_comes_from_a_strong_name_side_match():
    """유명 상표 배너가 이름·이미지 속 글자의 강한 일치로 뜨면 큰·작은 안내도 한 줄도 없다."""
    for basis in ("이름", "이미지 속 글자"):
        strong = [_match("강함", basis=basis)]
        assert nc.famous_banner_state(_response(ALL, famous=strong)) == nc.BANNER_NAME_STRONG
        for words in (ALL, COMMON_ONLY):
            assert nc.notice_kind(_response(words, famous=strong)) == nc.NOTICE_FAMOUS_HIDDEN
        some = _response(SOME, removed=REMOVED, famous=strong)
        assert nc.notice_kind(some) == nc.NOTICE_FAMOUS_HIDDEN
        assert nc.top_area(_response(ALL, famous=strong)) == ["유명 상표 배너(강함 — 김가네)"]
        assert nc.whole_name_line(_response(ALL, famous=strong)) is False
        # 식별력 없는 낱말이 없으면 원래 안내가 없다
        plain = _response([_word("스타벅스", None)], famous=strong)
        assert nc.notice_kind(plain) == nc.NOTICE_NONE
    # 둘째 줄의 일치가 이름 강함이어도 같다
    both = [LOGO, _match("강함", "뚜레쥬르")]
    assert nc.famous_banner_state(_response(ALL, famous=both)) == nc.BANNER_NAME_STRONG
    # 지금대로: 약한 일치·로고로만 강한 일치·설명적 사용·확인하지 못함
    assert nc.famous_banner_state(_response(ALL, famous=[_match("약함")])) == nc.BANNER_SHOWN
    assert nc.famous_banner_state(_response(ALL, famous=[LOGO])) == nc.BANNER_SHOWN
    assert nc.famous_banner_state(_response(ALL, famous=[LOGO, _match("약함")])) == (
        nc.BANNER_SHOWN)
    assert nc.famous_banner_state(_response(ALL, famous=[_match("설명적 사용")])) == (
        nc.BANNER_NONE)
    assert nc.famous_banner_state(_response(ALL, famous=[])) == nc.BANNER_NONE
    assert nc.famous_banner_state(_response(ALL)) == nc.BANNER_NONE
    unavailable = _response(ALL, famous=[_match("강함")], status="unavailable")
    assert nc.famous_banner_state(unavailable) == nc.BANNER_NONE
    assert nc.whole_name_line(_response(ALL, famous=[LOGO])) is True
    assert nc.NOTICE_FAMOUS_HIDDEN in nc.HIDDEN_NOTICES


def test_top_area_order():
    for level, match in (("강함", LOGO), ("약함", _match("약함"))):
        assert nc.top_area(_response(ALL, famous=[match])) == [
            f"유명 상표 배너({level} — 김가네)",
            f"설명적 이름 안내({nc.NOTICE_ALL_SMALL_FAMOUS})"]
    descriptive = nc.top_area(_response(ALL, famous=[_match("설명적 사용", "BBQ")]))
    assert descriptive == [f"설명적 이름 안내({nc.NOTICE_BIG})",
                           "유명 상표 배너(설명적 사용 — BBQ)"]
    assert nc.top_area(_response(SOME, removed=REMOVED)) == [
        f"설명적 이름 안내({nc.NOTICE_SOME})"]
    assert nc.top_area(_response(SOME)) == []  # 사실이 아니면 작은 안내를 그리지 않는다
    famous_only = _response([_word("스타벅스", None)], famous=[_match("강함", "스타벅스")])
    assert nc.top_area(famous_only) == ["유명 상표 배너(강함 — 스타벅스)"]
    assert nc.top_area(_response()) == []
    unavailable = nc.top_area(_response(ALL, famous=[], status="unavailable"))
    assert unavailable == ["유명 상표 확인을 하지 못했어요(한 줄)",
                           f"설명적 이름 안내({nc.NOTICE_BIG})"]


def test_whole_name_line_only_when_no_query_word_was_removed():
    assert nc.whole_name_line(_response(ALL)) is True
    assert nc.whole_name_line(_response(ALL, removed=[[("cafe", "candidate")], []])) is True
    assert nc.whole_name_line(_response(ALL, removed=[[("맛있는", "both")], []])) is False
    assert nc.whole_name_line(_response(ALL, removed=[[], [("커피", "query")]])) is False
    assert nc.whole_name_line(_response(SOME)) is False
    assert nc.whole_name_line(_response()) is False


def test_removed_as_said_checks_every_named_candidate():
    assert nc.removed_as_said(_response(SOME, removed=[[("커피", "query")], []])) is True
    # 이름 없는 후보(로고만)는 보지 않는다 — 이름을 견주지 않았다
    assert nc.removed_as_said(_response(SOME, removed=[[("커피", "both")], []])) is True
    assert nc.removed_as_said(_response(SOME)) is False  # 결합 규칙 등으로 빼지 않은 쌍
    assert nc.removed_as_said(_response(SOME, removed=[[("블루", "candidate")], []])) is False
    # 후보 쪽에서만 약한 낱말로 뺀 것은 질의의 낱말을 뺀 것이 아니다
    assert nc.removed_as_said(_response(SOME, removed=[[("커피", "candidate")], []])) is False
    # 이름을 견준 후보가 하나도 없으면 견준 것이 없다
    nameless = _response(SOME, removed=[[("커피", "query")], []])
    nameless["candidates"][0]["title"] = None
    assert nc.removed_as_said(nameless) is False
    # 싣지 않은 식별력 없는 낱말 수만큼 질의 쪽에서 뺀 낱말이 더 있어야 한다
    more = _response(SOME, removed=[[("커피", "query")], []])
    more["name_words"]["more_generic"] = 1
    assert nc.removed_as_said(more) is False
    more["candidates"][0]["salient"]["removed"].append(
        {"token": "전문점", "reason": "시험", "side": "both"})
    assert nc.removed_as_said(more) is True


def _dump(responses: dict, tree: str = "t") -> dict:
    return {"트리": tree, "모델": "risk_model_v1.4.7", "sha256": "0" * 64, "응답": responses}


def test_compare_dumps_allows_only_the_new_field():
    old = {"시나리오 | S1": _response(), "대조군 확인용 | 가 · 이름만": _response(),
           "시나리오 | S4 로고만": _response()}
    new = {"시나리오 | S1": _response(SOME), "대조군 확인용 | 가 · 이름만": _response(ALL),
           "시나리오 | S4 로고만": _response()}
    result = nc.compare_dumps(_dump(old), _dump(new))
    assert result["통과"] is True and result["질의"] == result["같음"] == 3
    assert result["묶음별"]["시나리오"] == {"질의": 2, "같음": 2, "새_필드_있음": 1}
    assert result["묶음별"]["대조군 확인용"] == {"질의": 1, "같음": 1, "새_필드_있음": 1}

    def problems(changed: dict) -> list[str]:
        out = nc.compare_dumps(_dump(old), _dump(changed))
        assert out["통과"] is False
        return [problem["문제"] for problem in out["어긋남"]]

    grade = copy.deepcopy(new)
    grade["시나리오 | S1"]["overall"]["grade"] = "검토 권장"
    assert problems(grade) == ["응답이 다름"]
    candidate = copy.deepcopy(new)
    candidate["시나리오 | S1"]["candidates"].reverse()
    assert problems(candidate) == ["응답이 다름"]
    extra = copy.deepcopy(new)
    extra["시나리오 | S1"]["other_new_key"] = 1
    assert problems(extra) == ["응답이 다름"]
    missing = {key: value for key, value in new.items() if key != "시나리오 | S1"}
    assert "후 덤프에 없음" in problems(missing)
    # 전 덤프에 새 필드가 있으면(고치기 전 트리가 아님) 알린다
    out = nc.compare_dumps(_dump(new), _dump(new))
    assert out["통과"] is False and "전 덤프에 새 필드가 있음" in {p["문제"] for p in out["어긋남"]}


def test_strip_new_field_and_paths():
    data = _response(SOME)
    assert "name_words" not in nc.strip_new_field(data) and "name_words" in data
    assert list(nc.strip_new_field(data)) == [key for key in data if key != "name_words"]
    assert nc.sample_a_path("A:2019100003886:target") == (
        "ml/data/trials/images/2019100003886/target.png")
    assert [want for _, _, want in nc.EXPECTED] == [
        nc.NOTICE_BIG, nc.NOTICE_BIG, nc.NOTICE_SOME, nc.NOTICE_NONE]
    assert [key for key, _ in nc.DEMO] == ["F2", "F1", "F3", "S1"]
