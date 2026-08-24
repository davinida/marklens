"""상표명 확인 API 계약 테스트. 외부 네트워크를 사용하지 않는다."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from cachetools import TTLCache
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.src.api import namecheck
from backend.src.core import engine, kipris_client, storage


def _reset_cache(monkeypatch):
    monkeypatch.setattr(namecheck, "_cache", TTLCache(maxsize=16, ttl=60))
    monkeypatch.setattr(
        engine, "lookup_trademarks_by_application_numbers", lambda numbers: {}
    )


def test_engine_file_lookup_normalizes_application_number(monkeypatch):
    trademark = {
        "출원번호": "40-2021-0000001",
        "이미지파일": "4020210000001.png",
    }
    monkeypatch.setattr(engine.state, "ready", True)
    monkeypatch.setattr(engine.state, "storage_mode", "file")
    monkeypatch.setattr(
        engine.state, "trademark_lookup", {"4020210000001.png": trademark}
    )

    result = engine.lookup_trademarks_by_application_numbers(
        ["4020210000001", "invalid"]
    )

    assert result == {"4020210000001": trademark}


def test_openapi_exposes_post_body_and_deprecates_get():
    app = FastAPI()
    app.include_router(namecheck.router)
    openapi = app.openapi()
    operations = openapi["paths"]["/name-check"]

    assert "requestBody" in operations["post"]
    assert operations["post"].get("deprecated") is not True
    assert operations["get"]["deprecated"] is True
    candidate_properties = openapi["components"]["schemas"]["NameCheckCandidate"][
        "properties"
    ]
    assert {
        "application_number",
        "registration_number",
        "application_date",
        "registration_date",
        "title",
        "status",
        "mark_type",
        "applicant",
        "right_holder",
        "nice_classes",
        "vienna_codes",
        "similarity_codes",
        "exact_title_match",
        "is_registered",
        "local_image_url",
    } == set(candidate_properties)


def test_complete_name_check_response_and_cache(monkeypatch):
    _reset_cache(monkeypatch)
    result = kipris_client.NameSearchResult(
        items=[{"Title": "마크렌즈", "ApplicationStatus": "등록"}],
        total_found=1,
        complete=True,
    )
    calls = []
    monkeypatch.setattr(
        kipris_client,
        "name_match_search",
        lambda query: (calls.append(query), result)[1],
    )

    first = namecheck._run_name_check("  마크렌즈  ")
    second = namecheck._run_name_check("마크렌즈")

    assert calls == ["마크렌즈"]
    assert first.complete is True
    assert first.scanned_count == 1
    assert first.total_found == 1
    assert first.cached is False
    assert second.cached is True
    assert second.checked_at == first.checked_at
    assert second.source == namecheck.SOURCE_NAME
    assert "1건" in first.message
    assert first.exact_title_count == 1
    assert first.status_counts == {"등록": 1}
    assert first.candidates_returned == 1
    assert first.candidates_truncated is False


def test_distinct_name_forms_do_not_share_cache_without_provider_equivalence(monkeypatch):
    _reset_cache(monkeypatch)
    result = kipris_client.NameSearchResult(
        items=[{"Title": "BBQ", "ApplicationStatus": "등록"}],
        total_found=1,
        complete=True,
    )
    calls: list[str] = []
    monkeypatch.setattr(
        kipris_client,
        "name_match_search",
        lambda query: (calls.append(query), result)[1],
    )

    full_width = namecheck._run_name_check("ＢＢＱ")
    lower_case = namecheck._run_name_check("bbq")
    trimmed = namecheck._run_name_check("  BBQ  ")
    exact_repeat = namecheck._run_name_check("BBQ")

    assert calls == ["ＢＢＱ", "bbq", "BBQ"]
    assert full_width.query == "ＢＢＱ" and full_width.cached is False
    assert lower_case.query == "bbq" and lower_case.cached is False
    assert trimmed.query == "BBQ" and trimmed.cached is False
    assert exact_repeat.query == "BBQ" and exact_repeat.cached is True
    assert all(
        response.exact_registered_count == 1
        for response in (full_width, lower_case, trimmed, exact_repeat)
    )


def test_concurrent_same_name_uses_single_upstream_call(monkeypatch):
    _reset_cache(monkeypatch)
    result = kipris_client.NameSearchResult([], 0, True)
    entered = threading.Event()
    calls = []

    def slow_search(query):
        calls.append(query)
        entered.set()
        time.sleep(0.05)
        return result

    monkeypatch.setattr(kipris_client, "name_match_search", slow_search)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(namecheck._run_name_check, "동시요청")
        assert entered.wait(timeout=1)
        second = pool.submit(namecheck._run_name_check, "동시요청")
        responses = [first.result(timeout=2), second.result(timeout=2)]

    assert calls == ["동시요청"]
    assert sorted(response.cached for response in responses) == [False, True]


def test_post_route_accepts_json_body(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(
        kipris_client,
        "name_match_search",
        lambda query: kipris_client.NameSearchResult([], 0, True),
    )
    app = FastAPI()
    app.state.limiter = namecheck.limiter
    app.include_router(namecheck.router)

    with TestClient(app) as client:
        response = client.post("/name-check", json={"name": "마크렌즈"})

    assert response.status_code == 200
    assert response.json()["query"] == "마크렌즈"
    assert response.json()["complete"] is True


def test_candidates_expose_allowlisted_bibliography_and_local_image(monkeypatch):
    _reset_cache(monkeypatch)
    items = [
        {
            "ApplicationNumber": "40-2021-0000001",
            "RegistrationNumber": "4012340000",
            "ApplicationDate": "20210105",
            "RegistrationDate": "20230519",
            "Title": "BBQ",
            "ApplicationStatus": "등록",
            "TrademarkDivisionCode": "도형복합",
            "ApplicantName": "주식회사 제너시스비비큐",
            "RegistrationRightholderName": "주식회사 제너시스비비큐",
            "GoodClassificationCode": ["29", "43"],
            "ViennaCode": ["260101"],
            "SimilarCode": ["G0701", "S120602"],
            # 일회성 원천 URL은 절대 API 응답에 그대로 노출하지 않는다.
            "ImagePath": "http://plus.kipris.or.kr/fileToss.jsp?arg=secret",
            "ThumbnailPath": "http://plus.kipris.or.kr/fileToss.jsp?arg=thumb",
        }
    ]
    monkeypatch.setattr(
        kipris_client,
        "name_match_search",
        lambda query: kipris_client.NameSearchResult(items, 1, True),
    )
    monkeypatch.setattr(
        engine,
        "lookup_trademarks_by_application_numbers",
        lambda numbers: {
            "4020210000001": {
                "출원번호": "4020210000001",
                "이미지파일": "4020210000001.png",
            }
        },
    )
    monkeypatch.setattr(
        engine.state, "image_path_set", {"4020210000001.png"}
    )
    monkeypatch.setattr(storage, "public_url", lambda key: f"/images/{key}")

    response = namecheck._run_name_check("bbq")
    payload = response.model_dump(mode="json")

    assert payload["status_counts"] == {"등록": 1}
    assert payload["exact_title_count"] == 1
    assert payload["candidates_returned"] == 1
    candidate = payload["candidates"][0]
    assert candidate == {
        "application_number": "4020210000001",
        "registration_number": "4012340000",
        "application_date": "20210105",
        "registration_date": "20230519",
        "title": "BBQ",
        "status": "등록",
        "mark_type": "도형복합",
        "applicant": "주식회사 제너시스비비큐",
        "right_holder": "주식회사 제너시스비비큐",
        "nice_classes": ["29", "43"],
        "vienna_codes": ["260101"],
        "similarity_codes": ["G0701", "S120602"],
        "exact_title_match": True,
        "is_registered": True,
        "local_image_url": "/images/4020210000001.png",
    }
    encoded = response.model_dump_json()
    assert "fileToss.jsp" not in encoded
    assert "ImagePath" not in encoded
    assert "ThumbnailPath" not in encoded


def test_candidate_limit_prioritizes_exact_matches(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(namecheck, "CANDIDATE_LIMIT", 2)
    items = [
        {"Title": "BBQ CHICKEN", "ApplicationStatus": "등록"},
        {"Title": "BBQ", "ApplicationStatus": "거절"},
        {"Title": "bbq", "ApplicationStatus": "등록"},
    ]
    monkeypatch.setattr(
        kipris_client,
        "name_match_search",
        lambda query: kipris_client.NameSearchResult(items, 3, True),
    )

    response = namecheck._run_name_check("BBQ")

    assert [candidate.title for candidate in response.candidates] == ["bbq", "BBQ"]
    assert response.candidates_returned == 2
    assert response.candidates_truncated is True
    assert response.scanned_count == 3
    assert response.exact_title_count == 2


def test_upstream_image_is_not_used_without_local_index_match(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(
        kipris_client,
        "name_match_search",
        lambda query: kipris_client.NameSearchResult(
            [
                {
                    "ApplicationNumber": "4020210000001",
                    "Title": "BBQ",
                    "ApplicationStatus": "등록",
                    "ImagePath": "https://plus.kipris.or.kr/fileToss.jsp?arg=opaque",
                }
            ],
            1,
            True,
        ),
    )

    response = namecheck._run_name_check("BBQ")

    assert response.candidates[0].local_image_url is None


def test_local_image_lookup_failure_keeps_kipris_candidates(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(
        kipris_client,
        "name_match_search",
        lambda query: kipris_client.NameSearchResult(
            [
                {
                    "ApplicationNumber": "4020210000001",
                    "Title": "BBQ",
                    "ApplicationStatus": "등록",
                }
            ],
            1,
            True,
        ),
    )

    def fail_lookup(_numbers):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(engine, "lookup_trademarks_by_application_numbers", fail_lookup)

    response = namecheck._run_name_check("BBQ")

    assert response.total_found == 1
    assert response.candidates[0].title == "BBQ"
    assert response.candidates[0].local_image_url is None


def test_incomplete_result_uses_neutral_message(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(
        kipris_client,
        "name_match_search",
        lambda query: kipris_client.NameSearchResult([], 200, False),
    )

    response = namecheck._run_name_check("확인중")

    assert response.complete is False
    assert response.scanned_count == 0
    assert "확정할 수 없습니다" in response.message
    assert "발견되지 않았습니다" not in response.message


def test_incomplete_result_reports_confirmed_match_as_minimum(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(
        kipris_client,
        "name_match_search",
        lambda query: kipris_client.NameSearchResult(
            [{"Title": "BBQ", "ApplicationStatus": "등록"}],
            700,
            False,
        ),
    )

    response = namecheck._run_name_check("BBQ")

    assert response.exact_registered_count == 1
    assert "최소 1건" in response.message
    assert "전체 건수는 확정할 수 없습니다" in response.message


def test_message_distinguishes_exact_nonregistered_from_registered_contains(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(
        kipris_client,
        "name_match_search",
        lambda query: kipris_client.NameSearchResult(
            [
                {"Title": "BBQ", "ApplicationStatus": "거절"},
                {"Title": "BBQ CHICKEN", "ApplicationStatus": "등록"},
            ],
            2,
            True,
        ),
    )

    response = namecheck._run_name_check("BBQ")

    assert response.exact_title_count == 1
    assert response.exact_registered_count == 0
    assert response.registered_count == 1
    assert "정확히 같은 등록 명칭은 없지만" in response.message
    assert "정확히 같은 이름은 없지만" not in response.message


def test_configuration_error_maps_to_503(monkeypatch):
    _reset_cache(monkeypatch)

    def fail(_query):
        raise kipris_client.KiprisConfigError("KIPRIS 설정 오류")

    monkeypatch.setattr(kipris_client, "name_match_search", fail)

    try:
        namecheck._run_name_check("마크렌즈")
    except HTTPException as exc:
        assert exc.status_code == 503
        assert exc.detail == "KIPRIS 상표명 확인 서비스가 준비되지 않았습니다."
    else:
        raise AssertionError("KiprisConfigError가 HTTP 503으로 변환되지 않았습니다.")
