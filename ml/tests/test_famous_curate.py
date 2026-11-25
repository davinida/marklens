"""famous_curate.py(유명 상표 고르기 도구 만들기 — 통합 모델 설계 §7-14-10)의 순수 함수와 틀:
도구에 싣는 자료, 새 브랜드 제안, 자료를 싣는 방식, 그리고 틀이 밖으로 아무것도 보내지 않게 돼
있는지(바깥 주소·연결 차단)."""

from __future__ import annotations

import json
import re

import pytest
from src import famous_check as fc

from scripts import famous_curate as curate


def _notation(text: str, kind: str = fc.KIND_NORMAL, reason: str = "") -> fc.Notation:
    key = fc.text_key(text)
    return fc.Notation(text=text, key=key, pieces=(key,), script=fc.script_label(key),
                       length=fc.length_class(key), kind=kind, base_weak=False,
                       kind_reason=reason)


def _mark(appno: str, title: str | None, auto: str, **more) -> fc.Mark:
    return fc.Mark(appno=appno, title=title, kind="도형복합", role=fc.DEFAULT_ROLE[auto],
                   auto_role=auto, source=fc.SOURCE_FAMOUS, image=f"{appno}.png",
                   image_exists=True, codes=frozenset({"G0301"}), classes=(30, 43),
                   app_date="2020-01-02", reg_date="2021-03-04", **more)


def _brand(name: str, notations, marks=(), **more) -> fc.Brand:
    return fc.Brand(name=name, notations=tuple(notations), applicants=("회사",),
                    applicant_keys=frozenset({"회사"}), preset="cafe", preset_label="카페",
                    preset_codes=frozenset({"G0301"}), evidence="", evidence_urls=(),
                    protection=fc.PROTECT_NEAR, goods_codes=frozenset(), goods_source="업종 세트",
                    marks=tuple(marks), table_name=more.pop("table_name", name), **more)


def test_goods_summary_names_the_classes():
    assert curate.goods_summary((30, 43)) == "30류 커피·과자·빵·조미료 · 43류 음식·숙박업"
    assert curate.goods_summary(["09", "x", None]).startswith("9류 ")
    assert curate.goods_summary(()) == "" and curate.goods_summary([99]) == "99류"


def test_new_brands_from_the_candidate_search_are_only_proposed_once():
    candidates = {"브랜드": {
        "이디야커피": {"새_브랜드": False, "표기": ["이디야"], "출원인": []},
        "삼성": {"새_브랜드": True, "표기": ["삼성", "SAMSUNG"],
                 "출원인": [{"이름": "삼성전자주식회사", "출처": "2026-10-12 판 목록"}]},
        "토스": {"새_브랜드": True, "표기": ["토스"], "출원인": []}}}
    overrides = {"brands": {"토스": {"new": True, "notations": {"add": ["토스"]}}}}
    proposed = curate.proposed_brands(candidates, overrides, {"이디야커피"})
    # 이미 넣은 브랜드(토스)와 표에 있는 브랜드는 제안하지 않는다
    assert proposed == {"삼성": {"new": True, "notations": {"add": ["삼성", "SAMSUNG"]},
                                "applicants": ["삼성전자주식회사"]}}
    assert curate.proposed_brands(None, overrides, set()) == {}
    fc.parse_overrides({"version": fc.OVERRIDES_VERSION, "brands": proposed})  # 형식이 맞다


def test_tool_data_separates_automatic_values_from_decisions():
    star = _brand("스타벅스", [_notation("스타벅스"), _notation("별다방", fc.KIND_WEAK, "흔한 말")],
                  [_mark("4020200000001", "STARBUCKS", fc.ROLE_NAME),
                   _mark("4020200000002", None, fc.ROLE_FIGURE)])
    samsung = _brand("삼성", [_notation("삼성")], is_new=True)
    registry = fc.Registry(fc.REGISTRY_VERSION, (star, samsung))
    table = [{"notations": ["스타벅스", "STARBUCKS"], "applicants": ["스타벅스 코포레이션"],
              "preset": "cafe", "evidence": "카페 예외 https://example.org/a",
              "urls": ["https://example.org/a"]}]
    proposed = {"삼성": {"new": True, "notations": {"add": ["삼성", "SAMSUNG"]},
                         "applicants": ["삼성전자주식회사"]}}
    candidates = {"브랜드": {"스타벅스": {
        "호출": [{"종류": "가", "검색어": "스타벅스", "쪽": 1, "totalCount": 9, "오류": None},
                 {"종류": "나", "검색어": "스타벅스 인크", "쪽": 1, "오류": "resultCode 10"}],
        "쓴_출원인": [{"이름": "스타벅스 코포레이션", "출처": "2026-10-12 판 목록",
                    "보낸_말": ["스타벅스 코포레이션"]}],
        "가장_많은_출원인": {"이름": "스타벅스 코포레이션", "건수": 7, "전체": 9},
        "후보": [
            {"출원번호": "4020200000002", "상표명": None, "유형": "도형", "출원인": ["가"],
             "등록권리자": [], "출원일": "20200102", "등록일": "20210304", "류": ["30"],
             "찾은_길": ["나:가"], "아는_출원인": True, "썸네일": None, "국제등록번호": None},
            {"출원번호": "4020200000009", "상표명": "SIREN", "유형": "결합(추정)",
             "출원인": ["나"], "등록권리자": ["나"], "출원일": None, "등록일": "20220101",
             "류": ["43"], "찾은_길": ["가:스타벅스"], "아는_출원인": False,
             "썸네일": "4020200000009.png", "국제등록번호": "123"},
            {"출원번호": "4020200000007", "상표명": "남의 것", "유형": "문자(추정)",
             "출원인": ["다"], "등록권리자": [], "출원일": None, "등록일": None, "류": [],
             "찾은_길": ["가:스타벅스"], "아는_출원인": False, "썸네일": None,
             "국제등록번호": None}]}}}
    records = [{"출원번호": "4020200000001", "출원인": "스타벅스 코포레이션"},
               {"출원번호": "4020200000002", "출원인": "스타벅스 코포레이션",
                "이미지파일": "4020200000002.png"},
               {"출원번호": "4020200000007", "출원인": "다", "이미지파일": "4020200000007.png"}]
    picked = {"brands": {"스타벅스": {"fetch": [
        {"appno": "4020200000002", "role": fc.ROLE_LOGO_NOW, "source": "후보"}]}}}
    via = curate.tool_data(
        registry=registry, table_rows=table, overrides=picked, proposed=proposed,
        candidates=None, records=records, presets={"cafe": "카페"},
        thumb_of=lambda appno, image: None, cand_thumb_of=lambda name: None)
    # 출원번호로 골라 이어 둔 표장(받아서 DB 에 들어온 것)은 내보낼 때 fetch 로 남는다
    assert [mark["via_fetch"] for mark in via["brands"][0]["marks"]] == [None, "후보"]
    assert via["initial_overrides"] == picked and via["db_count"] == 3
    data = curate.tool_data(
        registry=registry, table_rows=table, overrides={"brands": {}}, proposed=proposed,
        candidates=candidates, records=records, presets={"cafe": "카페"},
        thumb_of=lambda appno, image: f"t/db/{appno}.png" if image else None,
        cand_thumb_of=lambda name: f"t/cand/{name}")
    assert data["roles"] == list(fc.MARK_ROLES) and data["kinds"] == list(fc.KINDS)
    assert data["overrides_version"] == fc.OVERRIDES_VERSION
    assert data["initial_overrides"] == {"brands": {}}
    first, second = data["brands"]
    # 자동 값(base)은 [브랜드] 표 그대로 — 사람이 정한 값은 initial_overrides 로 따로
    assert first["base"] == {
        "name": "스타벅스", "is_new": False, "applicants": ["스타벅스 코포레이션"],
        "preset": "cafe", "urls": ["https://example.org/a"], "evidence_text": "카페 예외",
        "protection_default": fc.PROTECT_ANY, "notations": ["스타벅스", "STARBUCKS"]}
    assert first["kinds"]["별다방"] == {"kind": fc.KIND_WEAK, "reason": "흔한 말"}
    assert [(m["appno"], m["default_role"], m["thumb"]) for m in first["marks"]] == [
        ("4020200000001", fc.ROLE_BRAND_OTHER, "t/db/4020200000001.png"),
        ("4020200000002", fc.ROLE_UNRELATED, "t/db/4020200000002.png")]
    assert first["marks"][0]["goods"].startswith("30류 ")
    assert first["marks"][0]["codes"] == "유사군 G0301"
    cands = {c["appno"]: c for c in first["candidates"]}
    assert (cands["4020200000002"]["in_db"], cands["4020200000002"]["in_brand"]) == (True, True)
    assert cands["4020200000002"]["thumb"] == "t/db/4020200000002.png"  # DB 의 그림을 쓴다
    assert (cands["4020200000007"]["in_db"], cands["4020200000007"]["in_brand"]) == (True, False)
    assert cands["4020200000009"]["thumb"] == "t/cand/4020200000009.png"
    assert (cands["4020200000009"]["intl"], cands["4020200000009"]["own"]) == ("123", False)
    assert first["search"]["applicants"] == [{
        "name": "스타벅스 코포레이션", "source": "2026-10-12 판 목록",
        "terms": ["스타벅스 코포레이션"]}]
    assert first["search"]["calls"] == 2 and first["search"]["note"] == ""
    assert first["search"]["errors"] == ["나 스타벅스 인크: resultCode 10"]
    # 제안된 새 브랜드: 자동 값은 검색에 쓴 표기와 2026-10-12 판 출원인, 보호 범위는 가까운 업종
    assert second["proposed"] is True and second["search"] is None
    assert second["base"] == {
        "name": "삼성", "is_new": True, "applicants": ["삼성전자주식회사"], "preset": None,
        "urls": [], "evidence_text": "", "protection_default": fc.PROTECT_NEAR,
        "notations": ["삼성", "SAMSUNG"]}


def test_render_keeps_markup_in_the_data_inert():
    template = '<script type="application/json" id="data">/*__DATA__*/</script>'
    html = curate.render({"title": "</script><script>alert(1)</script>", "a": " "}, template)
    assert html.count("</script>") == 1 and " " not in html
    body = html[html.index(">") + 1:html.rindex("</script>")]
    assert json.loads(body) == {"title": "</script><script>alert(1)</script>", "a": " "}
    with pytest.raises(ValueError):
        curate.render({}, "자리 없음")


def test_template_sends_nothing_outside():
    template = curate.TEMPLATE.read_text(encoding="utf-8")
    assert template.count(curate.DATA_SLOT) == 1
    assert not re.search(r"https?://", template)  # 바깥 글꼴·스크립트·그림 주소가 없다
    assert not re.search(r"\b(fetch|XMLHttpRequest|WebSocket|sendBeacon|EventSource)\s*\(",
                         template)
    policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', template)
    assert policy and "default-src 'none'" in policy.group(1)
    assert "connect-src 'none'" in policy.group(1) and "form-action 'none'" in policy.group(1)
    assert "<script src" not in template and "<link" not in template
    for role in ("대표 로고(현재)", "과거 로고", "관련 없음"):
        assert role in template  # 역할 이름은 자료의 roles 순서와 같은 말로 보인다
    assert "innerHTML" not in template  # 자료는 글로만 넣는다


def test_industry_table_flags_missing_presets_and_off_core_received_marks():
    from scripts import famous_registry as builder

    logo = _mark("4020200000001", "STARBUCKS", fc.ROLE_NAME)
    star = _brand("스타벅스", [_notation("스타벅스")], [
        fc.Mark(**{**logo.__dict__, "role": fc.ROLE_LOGO_NOW, "picked": True}),
        fc.Mark(**{**_mark("4020200000002", None, fc.ROLE_FIGURE).__dict__,
                   "role": fc.ROLE_LOGO_OLD, "picked": True, "classes": (25, 43),
                   "source": fc.SOURCE_RECEIVED})])
    gs = fc.Brand(**{**_brand("GS25", [_notation("GS25")], [
        fc.Mark(**{**_mark("4020200000003", "GS25", fc.ROLE_NAME).__dict__,
                   "role": fc.ROLE_LOGO_NOW, "picked": True, "classes": (36, 41),
                   "source": fc.SOURCE_RECEIVED})]).__dict__, "preset": "convenience"})
    kia = fc.Brand(**{**_brand("기아", [_notation("기아")], is_new=True).__dict__,
                      "preset": None, "preset_label": None})
    goods = {"4020200000001": [(43, "카페업"), (30, "커피")],
             "4020200000002": [(25, "의류"), (43, "카페업")]}
    rows = builder.industry_table(
        fc.Registry(fc.REGISTRY_VERSION, (star, gs, kia)),
        classes_of={"cafe": [30, 43], "convenience": [35]},
        goods_of=lambda appno: goods.get(appno, []))
    first, second, third = rows
    assert (first["대표_로고_현재"], first["대표_로고_과거"]) == (1, 1)
    assert first["대표_표장의_류"] == [25, 30, 43] and first["업종_세트의_류"] == [30, 43]
    assert first["대표_지정상품"] == ["카페업", "커피", "의류"]  # 핵심 업종의 것·많이 나온 것 먼저
    # 받은 표장이 하나라도 핵심 업종의 류에 있으면 표시하지 않는다
    assert first["받은_표장"] == 1 and first["표시"] == []
    first_only = builder.industry_table(
        fc.Registry(fc.REGISTRY_VERSION, (star,)), classes_of={"cafe": [30]},
        goods_of=lambda appno: [])[0]
    assert first_only["표시"] == ["받은 표장이 핵심 업종 밖의 류뿐"]
    assert second["표시"] == ["받은 표장이 핵심 업종 밖의 류뿐"] and second["받은_표장의_류"] == [
        36, 41]
    assert third["표시"] == ["업종 세트 없음"] and third["대표_표장의_류"] == []
    text = builder.review_text({**builder.review(
        fc.Registry(fc.REGISTRY_VERSION, (star, gs, kia))), "업종_표": rows})
    assert "GS25 | convenience(35)" in text and "업종 세트 없음" in text

