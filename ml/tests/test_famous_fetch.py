"""famous_fetch.py(유명 상표의 대표 표장 받기 — 통합 모델 설계 §7-14-11)의 순수 함수: 받을 목록과
순서, 넣지 않을 까닭, 스테이징에 넣을 항목. KIPRIS 를 부르는 부분은 시험하지 않는다(호출 0)."""

from __future__ import annotations

import argparse

import pytest
from src import famous_check as fc

from scripts import famous_fetch as fetch


def _overrides(**brands) -> dict:
    return fc.parse_overrides({"version": fc.OVERRIDES_VERSION, "brands": brands})


def test_fetch_plan_orders_by_role_and_skips_marks_already_in_the_database():
    overrides = _overrides(
        이디야커피={"fetch": [
            {"appno": "4020240158104", "role": fc.ROLE_BRAND_OTHER, "source": "후보"},
            {"appno": "4520130000641", "role": fc.ROLE_LOGO_NOW, "source": "후보"}]},
        애플={"new": True, "name": "애플(Apple)", "notations": {"add": ["애플"]}, "fetch": [
            {"appno": "4119880000402", "role": fc.ROLE_LOGO_OLD, "source": "후보"},
            {"appno": "4020257000482", "role": fc.ROLE_LOGO_NOW, "source": "후보"},
            {"appno": "4020130016625", "role": fc.ROLE_LOGO_NOW, "source": "직접"},
            {"appno": "4020000000001", "role": fc.ROLE_LOGO_NOW, "source": "후보"}]})
    items = {"4520130000641": {}, "4119880000402": {}, "4020240158104": {},
             "4020257000482": {"NumberIsReference": True}}
    plan = fetch.fetch_plan(overrides, {"4020000000001"}, items)
    # 대표 로고(현재) → 과거 로고 → 그 밖(같은 역할은 overrides 순서) — 상한에 걸리면 뒤가 남는다
    assert [(row["출원번호"], row["역할"]) for row in plan["받을_표장"]] == [
        ("4520130000641", fc.ROLE_LOGO_NOW), ("4020257000482", fc.ROLE_LOGO_NOW),
        ("4020130016625", fc.ROLE_LOGO_NOW), ("4119880000402", fc.ROLE_LOGO_OLD),
        ("4020240158104", fc.ROLE_BRAND_OTHER)]
    assert [row["출원번호"] for row in plan["이미_DB에_있음"]] == ["4020000000001"]  # 역할만 잇는다
    assert plan["국제등록"] == ["4020257000482"]
    # 검색 응답이 없는 것(직접 적은 번호)은 출원번호 검색 1회를 더 쓴다
    assert plan["필요한_호출"] == 5 + 1
    assert plan["받을_표장"][1]["브랜드"] == "애플(Apple)"  # 바꾼 이름으로 보고
    assert plan["브랜드·역할별"]["이디야커피"] == {fc.ROLE_BRAND_OTHER: 1, fc.ROLE_LOGO_NOW: 1}
    assert plan["역할별"] == {fc.ROLE_LOGO_NOW: 3, fc.ROLE_LOGO_OLD: 1, fc.ROLE_BRAND_OTHER: 1}
    shared = _overrides(가={"new": True, "notations": {"add": ["가"]}, "fetch": [
        {"appno": "4020200000001"}]}, 나={"new": True, "notations": {"add": ["나"]}, "fetch": [
            {"appno": "4020200000001"}]})
    plan = fetch.fetch_plan(shared, set(), {})
    assert len(plan["받을_표장"]) == 1 and plan["여러_브랜드가_고른_번호"] == ["4020200000001"]


def test_marks_are_not_staged_without_registration_goods_or_image():
    detail = {"register_status": "등록", "similarity_codes": ["G0301"], "image_url": "u"}
    assert fetch.judge(detail, {}) is None
    assert fetch.judge({**detail, "register_status": "소멸"}, {}) == "등록 상태가 아님(소멸)"
    assert fetch.judge({**detail, "similarity_codes": []}, {}) == "지정상품(유사군) 없음"
    assert fetch.judge({**detail, "image_url": None}, {}) == "견본 링크 없음"
    # 서지에 상태가 없으면 검색 응답의 상태를 본다
    missing = {**detail, "register_status": None}
    assert fetch.judge(missing, {"ApplicationStatus": "등록"}) is None
    assert fetch.judge(missing, {}) == "등록 상태가 아님(상태 없음)"


def test_staged_item_fills_from_the_bibliography_like_the_existing_procedure():
    item = {"ApplicationNumber": "4020187009094", "Title": "DUNKIN'", "ViennaCode": [],
            "GoodClassificationCode": [], "RegistrationNumber": "", "ApplicantName": "가|나"}
    detail = {"similarity_codes": ["G0301", "S120602"], "nice_classes": [30, 43],
              "mark_type": "국제등록상표(마드리드) 도형복합 일반", "vienna_codes": ["241701"],
              "registration_number": None}
    staged = fetch.staged_item(item, detail, lambda kind: "도형복합" if "도형복합" in kind
                               else kind)
    assert staged["SimilarCode"] == ["G0301", "S120602"]
    assert staged["GoodClassificationCode"] == ["30", "43"]
    assert staged["DrawingKindName"] == "도형복합" and staged["ViennaCode"] == ["241701"]
    assert staged["Title"] == "DUNKIN'" and staged["ApplicantName"] == "가|나"
    assert item["GoodClassificationCode"] == []  # 원래 항목은 그대로
    filled = {**item, "GoodClassificationCode": ["9"], "DrawingKindName": "도형상표"}
    kept = fetch.staged_item(filled, detail, str)
    assert kept["GoodClassificationCode"] == ["9"] and kept["DrawingKindName"] == "도형상표"


def test_state_and_source_label(tmp_path):
    assert fetch.SOURCE_LABEL == fc.DB_SOURCE_LOGOS == "유명 브랜드(대표 표장)"
    state = fetch.load_state(tmp_path / "state.json")
    assert state["세션"]["호출"] == 0 and state["표장"] == {}
    state["표장"]["1"] = {"브랜드": "가", "역할": fc.ROLE_LOGO_NOW, "결과": fetch.DONE}
    state["표장"]["2"] = {"브랜드": "가", "역할": fc.ROLE_LOGO_OLD, "국제등록": True,
                        "결과": "지정상품(유사군) 없음"}
    plan = {"받을_표장": [{"출원번호": "2", "브랜드": "가", "역할": fc.ROLE_LOGO_OLD},
                       {"출원번호": "3", "브랜드": "나", "역할": fc.ROLE_LOGO_NOW}]}
    summary = fetch.summarize(state, plan)
    assert summary["받음"] == 1 and summary["받음_역할별"] == {fc.ROLE_LOGO_NOW: 1}
    assert summary["넣지_않음"] == [{"출원번호": "2", "브랜드": "가", "역할": fc.ROLE_LOGO_OLD,
                                  "국제등록": True, "까닭": "지정상품(유사군) 없음"}]
    assert [row["출원번호"] for row in summary["아직_안_받음"]] == ["3"]
    with pytest.raises(RuntimeError):  # 키 값이 든 상태는 쓰지 않는다
        fetch.save_state(tmp_path / "state.json", {**state, "오류": "… KEY=c= …"}, "KEY=c=")


def test_run_refuses_without_a_key_variable_name():
    with pytest.raises(SystemExit):  # .env 의 공용 키로 떨어지지 않게
        fetch.Fetcher(argparse.Namespace(key_env=None, counter=None), {})
    with pytest.raises(SystemExit):
        fetch.Fetcher(argparse.Namespace(key_env="SOME_KEY", counter=None), {})
