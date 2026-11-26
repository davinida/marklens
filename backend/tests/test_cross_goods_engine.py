"""업종은 다르지만 표장이 닮은 후보를 응답에 싣기(계약 v2 §2-8, 설계 §7-15) — FAKE_ML 픽스처.

후보의 선택 필드 cross_goods(업종이 다른지·다르면 업종 없이 본 등급·그 등급이 검토 권장 이상인지)와
처음 보이는 범위 밖의 후보를 싣는 cross_goods_more 가 정의대로인지, 업종을 넣지 않은 질의와 업종
겹침을 모르는 후보에는 표시가 없는지, 후보 목록·전체 등급이 그대로인지를 본다. 업종 없이 본 등급은
엔진의 채점(score_record)을 업종 축만 가리고 다시 불러 따로 구해 견준다.
"""

from __future__ import annotations

import dataclasses
import json
import logging

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.src.core import engine
from backend.src.core import multi_search as ms
from backend.src.main import app
from backend.src.schemas.search_v2 import SearchV2Response

rm = ms.rm  # 엔진이 쓰는 런타임

SAME = ["S0101"]  # 픽스처 9건 전부의 유사군 — 업종이 겹친다
CAFE = ["G0502", "S2039"]  # 픽스처 상표와 겹치지 않는 유사군 — 업종이 다르다
NAME = "더미상표1"  # 픽스처 1번 상표명(정확 일치)
REVIEW = rm.GRADES.index("검토 권장")


@pytest.fixture(scope="module")
def client(fake_ml_mode):
    if not fake_ml_mode:
        pytest.skip("FAKE_ML 픽스처(더미 9건) 전용 테스트")
    with TestClient(app) as test_client:
        yield test_client


def _image():
    return Image.new("RGB", (64, 64), (200, 40, 40))


def _plain(data: dict) -> str:
    """새 선택 필드 둘과 걸린 시간을 뺀 응답."""
    data = json.loads(json.dumps(data))
    data.pop("cross_goods_more", None)
    for candidate in data["candidates"]:
        candidate.pop("cross_goods", None)
    data["meta"].pop("elapsed_ms")
    return json.dumps(data, ensure_ascii=False)


def _context(pooled: ms.PoolResult) -> ms.QueryContext:
    return ms.make_context(pooled.query_name, pooled.goods, pooled.embedding, pooled.query_type,
                           pooled.x3_on)


def _hidden_goods_grade(record: ms.Record, ctx: ms.QueryContext, monkeypatch) -> str:
    """업종 축(x4)만 가리고 엔진의 score_record 를 다시 부른 등급 — 새 필드를 만드는 함수를 거치지
    않는다. 이름 있는 판단은 축을 그대로 두고 x4 만 없애고, 이름 없는 판단은 질의의 업종을
    없앤다."""
    if ctx.name and record.title:
        original = ms.compute_pair_axes
        with monkeypatch.context() as patch:
            patch.setattr(ms, "compute_pair_axes",
                          lambda *a, **k: dataclasses.replace(original(*a, **k), x4=None))
            return ms.score_record(record, ctx).grade
    return ms.score_record(record, dataclasses.replace(ctx, goods=None)).grade


def test_absent_without_goods(client):
    """업종을 넣지 않은 질의에는 싣지 않는다 — 후보에도 최상위에도."""
    for kwargs in (dict(name=NAME), dict(image=_image()), dict(image=_image(), name=NAME)):
        data = engine.multi_search(**kwargs, top_k=9).to_dict()
        assert "cross_goods_more" not in data
        assert all("cross_goods" not in candidate for candidate in data["candidates"])
        assert all(c.cross_goods is None for c in ms.search_pool(**kwargs).candidates)


def test_overlapping_goods_are_not_different(client):
    data = engine.multi_search(name=NAME, goods_codes=SAME, top_k=9).to_dict()
    assert data["candidates"]
    for candidate in data["candidates"]:
        assert candidate["axes"]["x4"] == 1.0
        assert candidate["cross_goods"] == {
            "differs": False, "grade_without_goods": None, "flagged": False}
    assert data["cross_goods_more"] == {"count": 0, "candidates": []}
    SearchV2Response.model_validate(data)


def test_different_goods_carry_the_grade_without_goods(client, monkeypatch):
    """업종이 다른 후보는 업종 없이 본 등급을 싣고, 그 등급이 검토 권장 이상이면 표시된다 — 등급은
    업종 축만 가리고 엔진이 다시 채점한 것과 같다."""
    floor = ms.goods_floor_value(ms.state.model)
    for kwargs in (dict(name=NAME, goods_codes=CAFE), dict(image=_image(), goods_codes=CAFE),
                   dict(image=_image(), name=NAME, goods_codes=CAFE),
                   dict(image=_image(), name=NAME, goods_codes=CAFE, type_override="도형")):
        pooled = ms.search_pool(**kwargs)
        ctx = _context(pooled)
        assert pooled.candidates
        grades = set()
        for candidate in pooled.candidates:
            field = candidate.cross_goods
            assert candidate.axes["x4"] == 0.0 < floor and field["differs"] is True
            want = _hidden_goods_grade(ms.state.by_appno[candidate.id], ctx, monkeypatch)
            assert field["grade_without_goods"] == want
            assert field["flagged"] is (rm.GRADES.index(want) >= REVIEW)
            # 업종 상한 — 화면 등급은 업종 없이 본 등급보다 높지 않다
            assert rm.GRADES.index(candidate.grade) <= rm.GRADES.index(want)
            grades.add(want)
        assert grades  # 계산됨
    # 같은 이름은 업종이 달라도 표시된다
    top = engine.multi_search(name=NAME, goods_codes=CAFE).to_dict()["candidates"][0]
    assert top["title"].startswith(NAME) and top["cross_goods"]["flagged"] is True


def test_grade_without_goods_is_the_goods_cap_pair_judgment(client):
    """이름 있는 판단에서 업종 없이 본 등급 = 업종 상한(goods_cap)이 견주는 짝 판단의 등급(단독 축
    규칙까지 반영)."""
    ctx = _context(ms.search_pool(name=NAME, goods_codes=CAFE))
    model = ms.state.model
    for x1, x2t in ((1.0, 1.0), (0.0, 0.8), (0.2, 0.1), (0.9, 0.3)):
        features = {"x1_d": x1, "x2_text_d": x2t, "x3_d": None, "x2_whole": None, "x4": 0.0,
                    "has_meaning_both": False, "has_distinctive_part_a": True,
                    "has_distinctive_part_b": True, "mark_type": "문자"}
        pair = ms._judge({**features, "x4": None}, model, "문자")
        field = ms._cross_goods(features, True, ctx, None, 0.0)
        assert field == {"differs": True, "grade_without_goods": pair.result.grade,
                         "flagged": rm.GRADES.index(pair.result.grade) >= REVIEW}
        capped, _ = ms._named_judgment(features, model, "문자")
        assert rm.GRADES.index(capped.result.grade) <= rm.GRADES.index(pair.result.grade)
    # 결합 하한 바로 아래·위
    floor = ms.goods_floor_value(model)
    assert ms._cross_goods(features, True, ctx, None, floor - 0.0001)["differs"] is True
    assert ms._cross_goods(features, True, ctx, None, floor) == {
        "differs": False, "grade_without_goods": None, "flagged": False}


def test_grade_without_goods_includes_the_image_only_judgment(client):
    """엔진은 이름 + 이미지 질의에서 이미지만 판단(logo_floor)과도 견줘 높은 등급을 쓴다 — 업종 없이
    본 등급도 같은 순서로 견준다(짝 판단은 낮아도 로고가 같으면 표시된다)."""
    base = _context(ms.search_pool(name=NAME, goods_codes=CAFE))
    model = ms.state.model
    features = {"x1_d": 0.1, "x2_text_d": 0.1, "x3_d": None, "x2_whole": 0.99, "x4": 0.0,
                "has_meaning_both": False, "has_distinctive_part_a": True,
                "has_distinctive_part_b": True, "mark_type": "문자"}
    pair = ms._judge({**features, "x4": None}, model, "문자")
    image_only = ms._judge(ms._image_only_features(0.99, "도형"), model, "도형")
    assert rm.GRADES.index(pair.result.grade) < REVIEW <= rm.GRADES.index(image_only.result.grade)
    off = dataclasses.replace(base, logo_floor=False, nameless_floor=False)
    assert ms._cross_goods(features, True, off, 0.99, 0.0) == {
        "differs": True, "grade_without_goods": pair.result.grade, "flagged": False}
    on = dataclasses.replace(base, logo_floor=True, nameless_level="도형")
    assert ms._cross_goods(features, True, on, 0.99, 0.0) == {
        "differs": True, "grade_without_goods": image_only.result.grade, "flagged": True}
    # 후보의 판단도 같은 함수 — 업종이 달라도 로고가 같으면 그 등급으로 보인다
    judged, _ = ms._candidate_judgment(features, True, on, 0.99)
    assert judged.result.grade == image_only.result.grade and ms.NAMELESS_FLOOR in judged.triggers


def test_unknown_overlap_is_not_called_different(client):
    """후보의 유사군 정보가 없어 업종 겹침을 모르면 다름이 아니라 모름이다 — 표시하지 않는다."""
    pooled = ms.search_pool(name=NAME, goods_codes=CAFE)
    ctx = _context(pooled)
    record = ms.state.by_appno[pooled.candidates[0].id]
    bare = ms.score_record(dataclasses.replace(record, goods=frozenset()), ctx)
    assert bare.axes["x4"] is None
    assert bare.cross_goods == {"differs": None, "grade_without_goods": None, "flagged": False}
    assert bare.to_dict()["cross_goods"]["differs"] is None
    # 이름 없는 판단(상표명이 없는 후보)도 같다
    nameless = ms.score_record(dataclasses.replace(record, goods=frozenset(), title=None), ctx)
    assert nameless.cross_goods["differs"] is None and nameless.cross_goods["flagged"] is False


def test_judgment_without_any_mark_axis_is_never_flagged(client):
    """견줄 표장 축이 없는 판단(업종만으로 본 판단)은 엔진이 짝 판단을 건너뛴다 — 같은 함수로
    계산하면 축이 없어 낮은 등급이고, 표시되지 않는다."""
    pooled = ms.search_pool(name=NAME, goods_codes=CAFE)
    ctx = _context(pooled)
    record = ms.state.by_appno[pooled.candidates[0].id]
    scored = ms.score_record(dataclasses.replace(record, title=None), ctx)  # 이름도 이미지도 없음
    assert scored.pattern == "x4" and scored.axes["x4"] == 0.0
    assert scored.cross_goods["differs"] is True
    assert scored.cross_goods["grade_without_goods"] == "안전"
    assert scored.cross_goods["flagged"] is False


def test_more_lists_flagged_candidates_outside_the_shown_range(client):
    pooled = ms.search_pool(name=NAME, goods_codes=CAFE)
    flagged = [c for c in pooled.candidates if c.cross_goods["flagged"]]
    assert len(flagged) >= 7  # 픽스처: 이름이 거의 같은 상표 9건
    for top_k in (1, 2, 5, 9):
        data = engine.multi_search(name=NAME, goods_codes=CAFE, top_k=top_k).to_dict()
        shown = [c["id"] for c in data["candidates"]]
        assert shown == [c.id for c in pooled.candidates[:top_k]]
        outside = [c for c in pooled.candidates[top_k:] if c.cross_goods["flagged"]]
        more = data["cross_goods_more"]
        assert more["count"] == len(outside)
        assert len(more["candidates"]) == min(len(outside), ms.CROSS_GOODS_MORE) <= 5
        # 업종 없이 본 등급이 높은 것부터, 같은 등급이면 풀의 순서
        ordered = sorted(outside, key=lambda c: -rm.GRADES.index(
            c.cross_goods["grade_without_goods"]))[:ms.CROSS_GOODS_MORE]
        assert [c["id"] for c in more["candidates"]] == [c.id for c in ordered]
        assert not set(shown) & {c["id"] for c in more["candidates"]}
        for listed, source in zip(more["candidates"], ordered):
            assert listed == source.to_dict()  # 앞의 후보와 같은 꼴
            assert listed["cross_goods"]["flagged"] is True
        SearchV2Response.model_validate(data)
    assert engine.multi_search(name=NAME, goods_codes=CAFE, top_k=9).to_dict()[
        "cross_goods_more"] == {"count": 0, "candidates": []}


def test_more_candidates_carry_the_famous_brand_mark_and_come_first(client, monkeypatch):
    """범위 밖 후보에도 앞의 후보처럼 유명 상표 표시가 붙고, 같은 등급 안에서는 유명 상표 등록부의
    표장이 먼저 실린다(다섯 개에 못 들지 않게) — 등급이 더 높은 후보보다 앞서지는 않는다."""
    pooled = ms.search_pool(name=NAME, goods_codes=CAFE)
    outside = [c for c in pooled.candidates[1:] if c.cross_goods["flagged"]]
    assert len(outside) > ms.CROSS_GOODS_MORE
    plain = engine.multi_search(name=NAME, goods_codes=CAFE, top_k=1).to_dict()["cross_goods_more"]
    target = outside[-1].id  # 풀의 순서로는 맨 뒤 — 표시가 없으면 다섯 안에 못 든다
    assert target not in [c["id"] for c in plain["candidates"]]
    runtime = dataclasses.replace(ms.state.famous, brand_of_mark={target: "스타벅스"})
    monkeypatch.setattr(ms.state, "famous", runtime)
    more = engine.multi_search(name=NAME, goods_codes=CAFE, top_k=1).to_dict()["cross_goods_more"]
    assert more["count"] == plain["count"] == len(outside)
    marks = {c["id"]: c.get("famous_brand") for c in more["candidates"]}
    assert marks[target] == "스타벅스"
    assert all(brand is None for appno, brand in marks.items() if appno != target)
    ordered = sorted(outside, key=lambda c: (
        -rm.GRADES.index(c.cross_goods["grade_without_goods"]), c.id != target))
    assert [c["id"] for c in more["candidates"]] == [c.id for c in ordered[:ms.CROSS_GOODS_MORE]]
    grades = [rm.GRADES.index(c["cross_goods"]["grade_without_goods"]) for c in more["candidates"]]
    assert grades == sorted(grades, reverse=True)


def test_candidates_and_overall_grade_are_untouched(client, monkeypatch):
    """새 선택 필드 둘 말고는 응답이 그대로다 — 그 계산을 끈 엔진과 글자까지 같다."""
    inputs = [dict(name=NAME, goods_codes=CAFE, top_k=9), dict(name=NAME, goods_codes=SAME),
              dict(name=NAME, goods_codes=CAFE, top_k=2), dict(name=NAME, top_k=5),
              dict(image=_image(), goods_codes=CAFE, top_k=3),
              dict(image=_image(), name=NAME, goods_codes=CAFE, top_k=5),
              dict(goods_codes=SAME), dict(name=NAME, goods_codes=CAFE, type_override="도형")]
    with_field = [engine.multi_search(**kwargs).to_dict() for kwargs in inputs]
    monkeypatch.setattr(ms, "_cross_goods", lambda *args: None)
    without = [engine.multi_search(**kwargs).to_dict() for kwargs in inputs]
    for kwargs, new, old in zip(inputs, with_field, without):
        assert all("cross_goods" not in candidate for candidate in old["candidates"])
        if "goods_codes" in kwargs:
            assert all("cross_goods" in candidate for candidate in new["candidates"])
            assert old["cross_goods_more"] == {"count": 0, "candidates": []}
        assert _plain(new) == _plain(old)
        assert [c["id"] for c in new["candidates"]] == [c["id"] for c in old["candidates"]]
        assert new["overall"] == old["overall"]


def test_failure_does_not_fail_the_search(client, monkeypatch, caplog):
    """업종 없이 본 등급의 계산에서 예외가 나면 그 후보의 필드만 빠진다 — 후보·등급은 그대로, 로그에
    질의 이름 없음."""
    secret = "비밀이름"
    expected = engine.multi_search(name=secret, goods_codes=CAFE).to_dict()
    original = ms._candidate_judgment

    def boom(features, named, ctx, x2_img):
        if features.get("x4") is None:  # 업종 축을 뺀 두 번째 호출만
            raise RuntimeError(f"질의 {secret} 처리 실패")
        return original(features, named, ctx, x2_img)

    monkeypatch.setattr(ms, "_candidate_judgment", boom)
    with caplog.at_level(logging.INFO):
        data = engine.multi_search(name=secret, goods_codes=CAFE).to_dict()
    assert data["candidates"]
    assert all("cross_goods" not in candidate for candidate in data["candidates"])
    assert data["cross_goods_more"] == {"count": 0, "candidates": []}
    assert _plain(data) == _plain(expected)
    assert "업종 없이 본 등급 계산 실패(RuntimeError)" in caplog.text
    assert secret not in caplog.text


def test_api_passes_the_fields_through(client):
    response = client.post("/search/v2?top_k=2", files={"name": (None, NAME),
                                                        "goods_codes": (None, ",".join(CAFE))})
    assert response.status_code == 200
    body = response.json()
    assert body["candidates"][0]["cross_goods"]["flagged"] is True
    assert body["cross_goods_more"]["count"] >= 1
    assert body["cross_goods_more"]["candidates"][0]["cross_goods"]["differs"] is True
    plain = client.post("/search/v2", files={"name": (None, NAME)}).json()
    assert "cross_goods_more" not in plain
    assert all("cross_goods" not in candidate for candidate in plain["candidates"])
