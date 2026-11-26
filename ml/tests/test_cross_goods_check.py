"""cross_goods_check.py(업종은 다르지만 표장이 닮은 후보의 확인 — 통합 모델 설계 §7-15)의 순수
함수: 정의에서 나오는 필드 값, 응답이 스스로 앞뒤가 맞는지, 전체 등급 옆 한 줄·접힌 칸, 범위 밖 칸을
풀에서 다시 고르기, 고치기 전·후 응답 견주기. 실제 엔진을 쓰는 queries·dump·run 명령은 시험하지
않는다."""

from __future__ import annotations

import copy

from scripts import cross_goods_check as cc

FLOOR = 0.0252
FLAGGED = {"differs": True, "grade_without_goods": "검토 권장", "flagged": True}
RISKY = {"differs": True, "grade_without_goods": "위험", "flagged": True}
NOT_ALIKE = {"differs": True, "grade_without_goods": "주의", "flagged": False}
SAME = {"differs": False, "grade_without_goods": None, "flagged": False}
UNKNOWN = {"differs": None, "grade_without_goods": None, "flagged": False}
X4 = {"flagged": 0.0, "risky": 0.01, "not_alike": 0.0, "same": 0.5, "unknown": None}


def _candidate(index: int, field: dict | None, x4: float | None, grade: str = "주의",
               famous: str | None = None) -> dict:
    out = {"id": f"402020000000{index}", "title": f"상표 {index}", "axes": {"x4": x4},
           "risk": {"grade": grade}, "goods": {"codes": [], "jaccard": x4}}
    if famous:
        out["famous_brand"] = famous
    if field is not None:
        out["cross_goods"] = dict(field)
    return out


def _response(shown: list[dict], more: dict | None = None, famous_floor: bool | None = None,
              goods: bool = True) -> dict:
    data = {"overall": {"grade": "검토 권장", "prob": 0.5}, "candidates": shown,
            "meta": {"model_version": "x"}}
    if famous_floor is not None:
        data["overall"]["famous_floor"] = famous_floor
    if goods:
        data["cross_goods_more"] = more or {"count": 0, "candidates": []}
    return data


def test_expected_field_follows_the_definition():
    assert cc.expected_field(None, None, FLOOR) == UNKNOWN
    assert cc.expected_field(0.5, None, FLOOR) == SAME
    assert cc.expected_field(FLOOR, None, FLOOR) == SAME  # 하한 이상이면 겹친다
    assert cc.expected_field(0.0252 - 1e-6, "검토 권장", FLOOR) == FLAGGED
    assert cc.expected_field(0.0, "위험", FLOOR) == RISKY
    for grade in ("안전", "주의"):
        assert cc.expected_field(0.0, grade, FLOOR) == {
            "differs": True, "grade_without_goods": grade, "flagged": False}


def test_field_problems_accepts_a_consistent_response():
    shown = [_candidate(1, FLAGGED, 0.0, "검토 권장"), _candidate(2, NOT_ALIKE, 0.0),
             _candidate(3, SAME, 0.5, "위험"), _candidate(4, UNKNOWN, None)]
    more = {"count": 7, "candidates": [_candidate(5, RISKY, 0.01), _candidate(6, FLAGGED, 0.0),
                                       _candidate(7, FLAGGED, 0.0), _candidate(8, FLAGGED, 0.0),
                                       _candidate(9, FLAGGED, 0.0)]}
    assert cc.field_problems(_response(shown, more), True, FLOOR) == []
    assert cc.field_problems(_response(shown), True, FLOOR) == []
    # 업종 없는 질의 — 새 필드가 하나도 없어야 한다
    bare = _response([_candidate(1, None, None)], goods=False)
    assert cc.field_problems(bare, False, FLOOR) == []
    assert cc.has_new_fields(bare) is False and cc.has_new_fields(_response(shown)) is True


def test_field_problems_catches_what_breaks_the_definition():
    def problems(shown, more=None, has_goods=True, **kwargs) -> str:
        return " / ".join(cc.field_problems(_response(shown, more, **kwargs), has_goods, FLOOR))

    assert "정의와 다름" in problems([_candidate(1, FLAGGED, 0.5)])  # 겹치는데 표시
    # 다른데 다름이 아님 — 업종 없이 본 등급이 없다
    assert "업종이 다른데 업종 없이 본 등급이 없음" in problems([_candidate(1, SAME, 0.0)])
    assert "정의와 다름" in problems([_candidate(1, {**FLAGGED, "differs": False}, 0.0)])
    assert "정의와 다름" in problems([_candidate(1, {**NOT_ALIKE, "flagged": True}, 0.0)])
    assert "정의와 다름" in problems([_candidate(1, {**FLAGGED, "flagged": False}, 0.0)])
    assert "정의와 다름" in problems([_candidate(1, FLAGGED, None)])  # 겹침을 모르는데 표시
    assert "업종 없이 본 등급이 없음" in problems([_candidate(1, UNKNOWN, 0.0)])
    assert "cross_goods 가 없음" in problems([_candidate(1, None, 0.0)])
    assert "화면 등급이 업종 없이 본 등급보다 높음" in problems(
        [_candidate(1, NOT_ALIKE, 0.0, "검토 권장")])
    assert "업종 없는 질의의 후보에 cross_goods 가 있음" in problems(
        [_candidate(1, SAME, 0.5)], has_goods=False, goods=False)
    assert "업종 없는 질의에 cross_goods_more 가 있음" in problems(
        [_candidate(1, None, None)], has_goods=False)
    missing = _response([_candidate(1, SAME, 0.5)], goods=False)
    assert cc.field_problems(missing, True, FLOOR) == ["업종 있는 질의에 cross_goods_more 가 없음"]
    shown = [_candidate(1, SAME, 0.5)]
    assert "후보 수가 count·상한과 다름" in problems(
        shown, {"count": 3, "candidates": [_candidate(5, FLAGGED, 0.0)]})
    assert "정의에 맞지 않는 후보" in problems(
        shown, {"count": 1, "candidates": [_candidate(5, NOT_ALIKE, 0.0)]})
    assert "처음 보이는 범위에도 있음" in problems(
        shown, {"count": 1, "candidates": [_candidate(1, FLAGGED, 0.0)]})
    assert "등급 순서가 아님" in problems(
        shown, {"count": 2, "candidates": [_candidate(5, FLAGGED, 0.0), _candidate(6, RISKY, 0.0)]})
    famous_later = [_candidate(5, FLAGGED, 0.0), _candidate(6, FLAGGED, 0.0, famous="스타벅스")]
    assert "유명 상표가 먼저가 아님" in problems(shown, {"count": 2, "candidates": famous_later})
    assert problems(shown, {"count": 2, "candidates": famous_later[::-1]}) == ""
    # 등급이 먼저다 — 더 높은 등급의 보통 상표가 낮은 등급의 유명 상표보다 앞
    graded = [_candidate(5, RISKY, 0.0), _candidate(6, FLAGGED, 0.0, famous="스타벅스")]
    assert problems(shown, {"count": 2, "candidates": graded}) == ""


def test_overall_line_and_folded_section_follow_the_screen_rule():
    top_flagged = [_candidate(1, FLAGGED, 0.0), _candidate(2, SAME, 0.5)]
    assert cc.overall_line(_response(top_flagged)) is True
    assert cc.overall_line(_response(top_flagged, famous_floor=False)) is True
    assert cc.overall_line(_response(top_flagged, famous_floor=True)) is False
    assert cc.overall_line(_response(list(reversed(top_flagged)))) is False
    assert cc.overall_line(_response([])) is False
    assert cc.overall_line(_response([_candidate(1, None, None)], goods=False)) is False
    assert cc.folded_section(_response(top_flagged)) == 0
    more = {"count": 6, "candidates": [_candidate(5, FLAGGED, 0.0)] * 5}
    assert cc.folded_section(_response(top_flagged, more)) == 6
    assert cc.folded_section(_response([_candidate(1, None, None)], goods=False)) == 0
    assert cc.OVERALL_LINE.startswith("가장 닮은 상표가 다른 업종에 있어요.")


def test_expected_more_picks_from_the_pool_outside_the_shown_range():
    pool = [("a", FLAGGED, False), ("b", SAME, False), ("c", FLAGGED, False),
            ("d", NOT_ALIKE, True), ("e", RISKY, False), ("f", FLAGGED, False),
            ("g", UNKNOWN, False), ("h", RISKY, False), ("i", FLAGGED, False),
            ("j", FLAGGED, False), ("k", FLAGGED, False)]
    # 앞 2 밖: c e f h i j k — 업종 없이 본 등급이 높은 것(위험)부터, 같으면 풀의 순서, 다섯까지
    assert cc.expected_more(pool, 2) == {"count": 7, "ids": ["e", "h", "c", "f", "i"]}
    assert cc.expected_more(pool, 5) == {"count": 5, "ids": ["h", "f", "i", "j", "k"]}
    assert cc.expected_more(pool, 20) == {"count": 0, "ids": []}
    assert cc.expected_more([("a", FLAGGED, False)], 0) == {"count": 1, "ids": ["a"]}
    # 같은 등급 안에서는 유명 상표 등록부의 표장이 먼저 — 등급이 더 높은 것 다음에
    famous = [(appno, field, appno in {"j", "k", "h"}) for appno, field, _ in pool]
    assert cc.expected_more(famous, 2) == {"count": 7, "ids": ["h", "e", "j", "k", "c"]}
    assert cc.MORE_LIMIT == 5 and cc.TOP_K == 5


def test_numbers_summarizes_per_query_counts():
    assert cc.numbers([]) == {"질의": 0}
    assert cc.numbers([1, 2, 9]) == {"질의": 3, "합": 12, "평균": 4.0, "중앙값": 2, "최대": 9}


def _dump(responses: dict, tree: str = "t") -> dict:
    return {"트리": tree, "모델": "risk_model_v1.4.7", "sha256": "0" * 64, "응답": responses}


def test_compare_dumps_allows_only_the_new_fields():
    old = {"시나리오 | S1": _response([_candidate(1, None, 0.0), _candidate(2, None, 0.5)],
                                     goods=False),
           "표본 A | 가 이름+이미지": _response([_candidate(1, None, None)], goods=False)}
    new = {"시나리오 | S1": _response(
        [_candidate(1, FLAGGED, 0.0), _candidate(2, SAME, 0.5)],
        {"count": 1, "candidates": [_candidate(5, FLAGGED, 0.0)]}),
           "표본 A | 가 이름+이미지": _response([_candidate(1, None, None)], goods=False)}
    result = cc.compare_dumps(_dump(old), _dump(new))
    assert result["통과"] is True and result["질의"] == result["같음"] == 2
    assert result["묶음별"]["시나리오"] == {"질의": 1, "같음": 1, "새_필드_있음": 1}
    assert result["묶음별"]["표본 A"] == {"질의": 1, "같음": 1, "새_필드_있음": 0}

    def problems(changed: dict) -> list[str]:
        out = cc.compare_dumps(_dump(old), _dump(changed))
        assert out["통과"] is False
        return [problem["문제"] for problem in out["어긋남"]]

    grade = copy.deepcopy(new)
    grade["시나리오 | S1"]["overall"]["grade"] = "위험"
    assert problems(grade) == ["응답이 다름"]
    order = copy.deepcopy(new)
    order["시나리오 | S1"]["candidates"].reverse()
    assert problems(order) == ["응답이 다름"]
    candidate = copy.deepcopy(new)
    candidate["시나리오 | S1"]["candidates"][0]["risk"]["grade"] = "위험"
    assert problems(candidate) == ["응답이 다름"]
    extra = copy.deepcopy(new)
    extra["시나리오 | S1"]["candidates"][0]["other_new_key"] = 1
    assert problems(extra) == ["응답이 다름"]
    missing = {key: value for key, value in new.items() if key != "시나리오 | S1"}
    assert "후 덤프에 없음" in problems(missing)
    # 전 덤프에 새 필드가 있으면(고치기 전 트리가 아님) 알린다
    out = cc.compare_dumps(_dump(new), _dump(new))
    assert out["통과"] is False and "전 덤프에 새 필드가 있음" in {p["문제"] for p in out["어긋남"]}


def test_strip_new_fields_and_paths():
    data = _response([_candidate(1, FLAGGED, 0.0, famous="스타벅스")],
                     {"count": 1, "candidates": [_candidate(5, FLAGGED, 0.0)]})
    stripped = cc.strip_new_fields(data)
    assert "cross_goods_more" not in stripped and "cross_goods_more" in data
    assert "cross_goods" not in stripped["candidates"][0]
    assert "cross_goods" in data["candidates"][0]  # 원본은 그대로
    assert stripped["candidates"][0]["famous_brand"] == "스타벅스"
    assert list(stripped) == [key for key in data if key != "cross_goods_more"]
    assert cc.sample_a_path("A:2019100003886:target") == (
        "ml/data/trials/images/2019100003886/target.png")
    assert [key for key, _ in cc.DEMO] == ["F2", "F1", "F3", "S1"]
    assert cc.flagged(data["candidates"][0]) is True and cc.flagged({"id": "x"}) is False
