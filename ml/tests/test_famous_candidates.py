"""famous_candidates.py(유명 상표 대표 표장 후보 찾기 — 통합 모델 설계 §7-14-10)의 순수 함수:
검색어 만들기, 응답 항목 정리(국제등록), 후보 고르기·합치기·상한, 키 값이 글에 남지 않게 하는 장치.
KIPRIS 를 부르는 부분은 시험하지 않는다(호출 0)."""

from __future__ import annotations

import argparse
import json

import pytest
from src import famous_check as fc

from scripts import famous_candidates as cand


def _item(appno, title="", applicant="가 회사", reg="20200101", vienna=("010101",),
          classes=("30",), holder=""):
    return {"ApplicationNumber": appno, "Title": title, "ApplicantName": applicant,
            "RegistrationRightholderName": holder, "ApplicationStatus": "등록",
            "ApplicationDate": "20190101", "RegistrationDate": reg, "RegistrationNumber": "1",
            "ViennaCode": list(vienna), "GoodClassificationCode": list(classes),
            "ImagePath": "http://plus.kipris.or.kr/openapi/fileToss.jsp?arg=x"}


def test_search_targets_and_call_budget():
    plan = cand.brand_plan(fc.load_registry())
    assert len(plan) == len(cand.EXISTING_BRANDS) + len(cand.NEW_BRANDS) == 34
    assert [item["이름"] for item in plan[:6]] == list(cand.EXISTING_BRANDS)
    assert all(not item["새_브랜드"] for item in plan[:6])
    assert all(item["새_브랜드"] for item in plan[6:])
    by_name = {item["이름"]: item for item in plan}
    assert by_name["삼성"]["표기"] == ["삼성", "SAMSUNG"]
    assert by_name["삼성"]["출원인"] == [{"이름": "삼성전자주식회사", "출처": "2026-10-12 판 목록"}]
    assert by_name["이디야커피"]["표기"] == ["이디야커피", "이디야", "EDIYA"]  # 등록부의 표기
    # 2026-10-12 판에 없는 브랜드는 지금 표의 출원인
    assert by_name["에어비앤비"]["출원인"][0]["출처"] == "지금 [브랜드] 표"
    assert all(1 <= cand.planned_calls(item) <= cand.MAX_CALLS_PER_BRAND for item in plan)
    assert sum(cand.planned_calls(item) for item in plan) <= 34 * cand.MAX_CALLS_PER_BRAND < 300
    assert cand.planned_calls(by_name["삼성"], name_search=False) == 2  # (나)만: 출원인 1 × 2쪽


def test_applicant_terms_drop_commas_then_the_company_form():
    assert cand.applicant_terms("에어비앤비, 인크.") == ["에어비앤비 인크."]  # 쉼표는 요청 오류
    assert cand.applicant_terms("비알코리아 주식회사") == ["비알코리아 주식회사", "비알코리아"]
    assert cand.applicant_terms("(주)비바리퍼블리카") == ["(주)비바리퍼블리카", "비바리퍼블리카"]
    assert cand.applicant_terms("던킨도너츠 엘엘씨") == ["던킨도너츠 엘엘씨"]
    assert cand.applicant_core("비알코리아 주식회사") == cand.applicant_core("비알코리아주식회사")
    assert cand.applicant_parts("가 회사| 나 회사 |") == ["가 회사", "나 회사"]


def test_international_registrations_use_the_reference_number():
    raw = {"applicationNumber": "", "appReferenceNumber": "4020207007605",
           "internationalRegisterNumber": "1528853", "internationalRegisterDate": "20190619",
           "registrationDate": "20220311", "title": "", "applicantName": "인디텍스|INDITEX",
           "viennaCode": "261111|261125", "classificationCode": "03|25"}

    def normalize(item):  # kipris_client.normalize_advanced_item 의 해당 부분
        return {"ApplicationNumber": item.get("applicationNumber", ""), "Title": item["title"],
                "ApplicantName": item["applicantName"], "RegistrationDate": "",
                "ApplicationDate": "", "ViennaCode": item["viennaCode"].split("|"),
                "GoodClassificationCode": item["classificationCode"].split("|")}

    item = cand.normalize_item(raw, normalize)
    assert (item["ApplicationNumber"], item["NumberIsReference"]) == ("4020207007605", True)
    assert (item["InternationalNumber"], item["RegistrationDate"]) == ("1528853", "20220311")
    assert item["ApplicationDate"] == "20190619"
    candidate = cand.candidate_from_item(item, via="나:인디텍스", kind="도형")
    assert candidate["출원번호"] == "4020207007605" and candidate["국제등록번호"] == "1528853"
    assert candidate["번호는_참조번호"] is True and candidate["출원인"] == ["인디텍스", "INDITEX"]
    assert "ImagePath" not in candidate and not any("http" in str(v) for v in candidate.values())
    domestic = cand.normalize_item({"applicationNumber": "4020200000001"},
                                   lambda item: {"ApplicationNumber": item["applicationNumber"]})
    assert domestic["InternationalNumber"] is None and "NumberIsReference" not in domestic


def test_name_results_rank_known_applicants_first_but_keep_others():
    items = [_item(f"40{n:011d}", "SAMSUNG GALAXY", "삼성전자주식회사", f"2020{n:04d}")
             for n in range(101, 131)]
    items += [_item("4000000000001", "SAMSUNG", "삼성전자주식회사", "19990101"),
              _item("4000000000002", "SAMSUNG", "다른 회사", "20240101"),
              _item("4000000000003", "삼성부동산", "동네 가게", "20250101", vienna=())]
    ranked = cand.rank_name_results(items, "SAMSUNG", {cand.applicant_core("삼성전자주식회사")})
    # 아는 출원인 + 가장 많은 출원인 + 상표명이 표기와 같음
    assert ranked[0]["출원번호"] == "4000000000001" and ranked[0]["점수"] == 8
    assert ranked[0]["유형"] == "결합(추정)" and ranked[-1]["유형"] == "문자(추정)"
    picked = cand.pick_name_results(ranked)
    assert len(picked) == cand.NAME_QUOTA
    assert sum(1 for c in picked if c["아는_출원인"]) == 18  # 다른 출원인이 둘뿐이라 채운다
    assert {"4000000000002", "4000000000003"} <= {c["출원번호"] for c in picked}
    more = items + [_item(f"44{n:011d}", "SAMSUNG TOWN", f"회사 {n}") for n in range(10)]
    picked = cand.pick_name_results(cand.rank_name_results(
        more, "SAMSUNG", {cand.applicant_core("삼성전자주식회사")}))
    own = [c for c in picked if c["아는_출원인"]]
    # 아는 출원인 몫과 그 밖의 몫을 나눈다(지주사·해외 본사 권리자가 보이게)
    assert (len(own), len(picked) - len(own)) == (
        cand.NAME_QUOTA_OWN, cand.NAME_QUOTA - cand.NAME_QUOTA_OWN)
    few = cand.pick_name_results(cand.rank_name_results(items[:5], "SAMSUNG", set()))
    assert len(few) == 5 and not any(c["아는_출원인"] for c in few)


def test_figure_results_keep_only_the_applicant_and_mix_new_and_old():
    items = [_item(f"41{n:011d}", "", "주식회사 엘지", f"{1990 + n}0101") for n in range(40)]
    items += [_item("4100000009999", "", "엘지전자 주식회사", "20250101"),
              _item("4100000009998", "", "다른 이름", "20250101", holder="(주)엘지")]
    picked, same = cand.pick_figure_results(items, "주식회사 엘지")
    assert same == 41  # 출원인이나 등록권리자가 같은 것만(엘지전자는 다른 회사)
    assert len(picked) == cand.FIGURE_QUOTA and all(c["유형"] == "도형" for c in picked)
    years = sorted(int(c["등록일"][:4]) for c in picked)
    assert years[0] == 1990 and years[-1] == 2029  # 오래된 등록과 최근 등록을 섞는다
    assert sum(1 for year in years if year >= 2014) == cand.FIGURE_QUOTA_NEW
    small, count = cand.pick_figure_results(items[:3], "주식회사 엘지")
    assert count == 3 and len(small) == 3
    call = {"종류": "나", "검색어": "엘지", "출원인": "주식회사 엘지", "쪽": 2}
    second, extra = cand.pick_for_call(call, items, set())
    assert len(second) == cand.FIGURE_QUOTA_PAGE2 and extra == {"출원인이_같은_것": 41}


def test_merge_and_cap_candidates():
    first = cand.pick_name_results(cand.rank_name_results(
        [_item("4000000000001", "KIA", "기아 주식회사")], "KIA", set()))
    again = cand.candidate_from_item(_item("4000000000001", "KIA", "기아 주식회사"),
                                     via="가:기아")
    again.update(점수=9, 아는_출원인=True, 썸네일="4000000000001.png")
    merged = cand.merge_candidates(first, [again])
    assert len(merged) == 1 and merged[0]["찾은_길"] == ["가:KIA", "가:기아"]
    assert merged[0]["점수"] == 9 and merged[0]["썸네일"] == "4000000000001.png"
    figures = [dict(cand.candidate_from_item(_item(f"42{n:011d}"), via="나:x", kind="도형"),
                    점수=5) for n in range(70)]
    names = [dict(cand.candidate_from_item(_item(f"43{n:011d}", "이름"), via="가:x"), 점수=n)
             for n in range(70)]
    capped = cand.cap_candidates(figures + names)
    assert len(capped) == cand.MAX_CANDIDATES == 80
    assert sum(1 for c in capped if c["유형"] == "도형") == 40  # 도형과 이름을 절반씩
    assert max(c["점수"] for c in capped if c["유형"] != "도형") == 69
    assert len(cand.cap_candidates(figures[:10] + names)) == 80  # 한쪽이 모자라면 다른 쪽이 채움


def test_name_search_support_is_judged_from_the_first_responses():
    state = {"상표명칭_검색": {"가능": None, "근거": ""}}
    cand.judge_name_search(state, "이디야", [], 0)
    assert state["상표명칭_검색"]["가능"] is None  # 결과가 없으면 판단하지 않는다
    ignored = [_item(str(n), "무관한 상표") for n in range(50)]
    cand.judge_name_search(state, "이디야", ignored, 2_000_000)
    assert state["상표명칭_검색"]["가능"] is False  # 조건이 무시된 것으로 보임
    state = {"상표명칭_검색": {"가능": None, "근거": ""}}
    cand.judge_name_search(state, "이디야", [_item("1", "이디야커피"), _item("2", "EDIYA")], 2)
    assert state["상표명칭_검색"]["가능"] is True


def test_the_key_never_reaches_saved_text(tmp_path):
    secret = "AbC/dEf+123=c="
    assert cand.scrub(f"url?ServiceKey={secret}&x=1", secret) == "url?ServiceKey=***&x=1"
    assert cand.scrub("url?ServiceKey=AbC%2FdEf%2B123%3Dc%3D", secret) == "url?ServiceKey=***"
    assert cand.has_secret("...AbC%2FdEf%2B123%3Dc%3D...", secret)
    assert not cand.has_secret("아무 글", secret) and not cand.has_secret(secret, "")
    path = tmp_path / "state.json"
    state = cand.load_state(path)
    assert state["version"] == cand.VERSION and state["세션"]["호출"] == 0
    cand.save_state(path, state, secret)
    assert json.loads(path.read_text(encoding="utf-8")) == state
    state["브랜드"]["x"] = {"오류": f"… {secret} …"}
    with pytest.raises(RuntimeError):
        cand.save_state(path, state, secret)  # 키 값이 든 상태는 쓰지 않는다
    assert "x" not in json.loads(path.read_text(encoding="utf-8"))["브랜드"]
    path.write_text(json.dumps({"version": "다른 것"}), encoding="utf-8")
    with pytest.raises(ValueError):
        cand.load_state(path)


def test_run_refuses_without_a_key_variable_name():
    args = argparse.Namespace(key_env=None, counter=None)
    with pytest.raises(SystemExit):  # .env 의 공용 키로 떨어지지 않게
        cand.Searcher(args, {})
    with pytest.raises(SystemExit):
        cand.Searcher(argparse.Namespace(key_env="SOME_KEY", counter=None), {})
