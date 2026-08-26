"""KIPRIS 클라이언트 단위 테스트 — 전부 네트워크 없이 동작한다."""

import json

import pytest

from backend.src.core import kipris_client as kc
from backend.src.core.kipris_client import (
    CallBudgetExceeded,
    KiprisError,
    RateLimiter,
    check_result_code,
    filter_registered,
    parse_items,
    parse_total_count,
    summarize_name_search,
)

XML_OK = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode><resultMsg>NORMAL</resultMsg></header>
  <body><items>
    <item>
      <Title>삼성전자</Title>
      <ApplicationStatus>등록</ApplicationStatus>
      <ApplicationNumber>4020210000001</ApplicationNumber>
      <ViennaCode>260101|270501</ViennaCode>
      <GoodClassificationCode>09|35</GoodClassificationCode>
      <ApplicantName>삼성전자 주식회사</ApplicantName>
    </item>
    <item>
      <Title>삼성전자 SAM SUNG ELECTRONICS</Title>
      <ApplicationStatus>등록</ApplicationStatus>
      <ApplicationNumber>4020210000002</ApplicationNumber>
      <ViennaCode>270501</ViennaCode>
      <GoodClassificationCode>09</GoodClassificationCode>
    </item>
    <item>
      <Title>삼성전자</Title>
      <ApplicationStatus>소멸</ApplicationStatus>
      <ApplicationNumber>4019990000003</ApplicationNumber>
      <ViennaCode></ViennaCode>
      <GoodClassificationCode>09</GoodClassificationCode>
    </item>
  </items></body>
</response>
"""

XML_EXPIRED = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>31</resultCode><resultMsg>DEADLINE_HAS_EXPIRED_ERROR</resultMsg></header>
  <body/>
</response>
"""


def test_parse_items_multivalue_split():
    items = parse_items(XML_OK)
    assert len(items) == 3
    assert items[0]["ViennaCode"] == ["260101", "270501"]
    assert items[0]["GoodClassificationCode"] == ["09", "35"]
    # 빈 다중값 필드는 빈 리스트
    assert items[2]["ViennaCode"] == []


def test_result_code_31_raises_with_hint():
    with pytest.raises(KiprisError) as exc:
        check_result_code(XML_EXPIRED)
    assert exc.value.result_code == "31"
    assert "상품 신청" in str(exc.value)  # 대응 방법 안내 포함


def test_result_code_31_actionable_guidance():
    # 승인 대기(키 발급 직후 미승인) 상황에서 바로 조치할 수 있는 한국어 안내인지 검증.
    # (사용자 상황: 상품 승인 대기 중 → 이 코드가 실제로 반환될 수 있다)
    with pytest.raises(KiprisError) as exc:
        check_result_code(XML_EXPIRED)
    msg = str(exc.value)
    assert "승인 대기" in msg          # 만료가 아니라 "승인 대기"일 수 있음을 명시
    assert "plus.kipris.or.kr" in msg  # 확인할 위치(마이페이지)
    assert "사용중" in msg             # 확인할 처리상태 값


def test_non_xml_raises():
    with pytest.raises(KiprisError):
        check_result_code("<html>not an api response")


def test_missing_result_code_is_protocol_error():
    with pytest.raises(kc.KiprisProtocolError, match="resultCode"):
        check_result_code("<response><header /><body><items /></body></response>")


def test_result_code_outside_header_is_rejected():
    with pytest.raises(kc.KiprisProtocolError, match="resultCode"):
        check_result_code(
            "<response><header /><body><resultCode>00</resultCode></body></response>"
        )


def test_unexpected_xml_envelope_is_protocol_error():
    with pytest.raises(kc.KiprisProtocolError, match="envelope"):
        check_result_code("<html><resultCode>00</resultCode></html>")


def test_missing_body_is_protocol_error():
    with pytest.raises(kc.KiprisProtocolError, match="body"):
        check_result_code(
            "<response><header><resultCode>00</resultCode></header></response>"
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://plus.kipris.or.kr/openapi/rest/example",
        "https://evil.example/openapi/rest/example",
        "https://plus.kipris.or.kr:444/openapi/rest/example",
        "https://user@plus.kipris.or.kr/openapi/rest/example",
    ],
)
def test_kipris_url_policy_rejects_unsafe_targets(monkeypatch, url):
    monkeypatch.setattr(kc, "ACCESS_KEY", "TESTKEY")
    with pytest.raises(kc.KiprisConfigError):
        kc._require_config(url, "TEST_URL")


def test_http_error_does_not_expose_key_or_query(monkeypatch):
    secret = "SECRET-KEY-MUST-NOT-LEAK"
    query = "CONFIDENTIAL-BRAND-NAME"
    request = kc.httpx.Request(
        "GET",
        "https://plus.kipris.or.kr/openapi/rest/example",
        params={"accessKey": secret, "trademarkNameMatch": query},
    )
    response = kc.httpx.Response(500, request=request)

    class FakeClient:
        def get(self, *args, **kwargs):
            return response

    monkeypatch.setattr(kc, "ACCESS_KEY", secret)
    monkeypatch.setattr(kc, "_get_client", lambda: FakeClient())
    monkeypatch.setattr(kc.limiter, "acquire", lambda: None)

    with pytest.raises(kc.KiprisNetworkError) as exc:
        kc._get(str(request.url.copy_with(query=None)), {"trademarkNameMatch": query})
    message = str(exc.value)
    assert secret not in message
    assert query not in message
    assert "https://" not in message


def test_get_applies_per_request_timeout(monkeypatch):
    captured = {}

    class FakeResponse:
        text = "<response />"

        def raise_for_status(self):
            return None

    class FakeClient:
        def get(self, url, **kwargs):
            captured.update({"url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setattr(kc, "ACCESS_KEY", "TESTKEY")
    monkeypatch.setattr(kc, "_get_client", lambda: FakeClient())
    monkeypatch.setattr(kc.limiter, "acquire", lambda: None)

    kc._get(
        "https://plus.kipris.or.kr/openapi/rest/example",
        {"query": "brand"},
        timeout=30,
    )

    assert captured["timeout"] == 30
    assert captured["params"] == {"query": "brand", "accessKey": "TESTKEY"}


def test_download_upgrades_official_legacy_http_url(monkeypatch, tmp_path):
    calls = []

    class FakeResponse:
        content = b"image-bytes"

        def raise_for_status(self):
            return None

    class FakeClient:
        def get(self, url, **kwargs):
            calls.append(url)
            return FakeResponse()

    monkeypatch.setattr(kc, "_get_client", lambda: FakeClient())
    dest = tmp_path / "mark.png"
    kc.download_file_now(
        "http://plus.kipris.or.kr/fileToss.jsp?token=temporary",
        dest,
    )

    assert calls == ["https://plus.kipris.or.kr/fileToss.jsp?token=temporary"]
    assert dest.read_bytes() == b"image-bytes"
    assert not (tmp_path / "mark.png.part").exists()


def test_filter_registered_only():
    items = parse_items(XML_OK)
    registered = filter_registered(items)
    assert len(registered) == 2
    assert all(it["ApplicationStatus"] == "등록" for it in registered)


def test_summarize_exact_vs_contains():
    # 실측 주의사항: 완전일치 검색이어도 포함 상표까지 잡힌다 → 나눠 센다
    items = parse_items(XML_OK)
    s = summarize_name_search("삼성전자", items)
    assert s["total_found"] == 3
    assert s["registered_count"] == 2
    assert s["exact_registered_count"] == 1  # "삼성전자 SAM SUNG ..."은 정확 일치 아님


def test_rate_limiter_corrupt_counter_fails_closed(tmp_path):
    counter = tmp_path / "counter.json"
    counter.write_text("not-json", encoding="utf-8")
    limiter = RateLimiter(counter_path=counter, min_interval=0)

    with pytest.raises(kc.KiprisConfigError, match="읽을 수 없습니다"):
        limiter.acquire()


def test_rate_limiter_write_failure_is_configuration_error(tmp_path, monkeypatch):
    counter = tmp_path / "counter.json"
    limiter = RateLimiter(counter_path=counter, min_interval=0)

    def fail_write(*args, **kwargs):
        raise PermissionError("read only")

    monkeypatch.setattr(kc.Path, "write_text", fail_write)
    with pytest.raises(kc.KiprisConfigError, match="저장할 수 없습니다"):
        limiter.acquire()


# --------------------------------------------------------------------
# 상표명완전일치(trademarkNameMatchSearchInfo) 응답 형식
# 실측(TODO.pdf): 항목 태그가 <item> 이 아니라 <TradeMarkInfo> 이고,
# 전체 건수는 <TotalSearchCount> 에 담긴다 (items 는 한 페이지분만).
# --------------------------------------------------------------------
XML_TRADEMARK = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode><resultMsg>success</resultMsg></header>
  <body><items>
    <TotalSearchCount>59</TotalSearchCount>
    <TradeMarkInfo>
      <SerialNumber>1</SerialNumber>
      <ApplicationNumber>4020210000001</ApplicationNumber>
      <RegistrationNumber>4012340000</RegistrationNumber>
      <ApplicationDate>20210105</ApplicationDate>
      <RegistrationDate>20230519</RegistrationDate>
      <ApplicationStatus>등록</ApplicationStatus>
      <TrademarkDivisionCode>도형복합</TrademarkDivisionCode>
      <GoodClassificationCode>09|35</GoodClassificationCode>
      <ViennaCode>010109|260504</ViennaCode>
      <SimilarCode>G0701|S120602</SimilarCode>
      <ApplicantName>삼성물산 주식회사|삼성전자주식회사</ApplicantName>
      <RegistrationRightholderName>삼성전자주식회사</RegistrationRightholderName>
      <Title>삼성전자</Title>
      <ImagePath>http://plus.kipris.or.kr/fileToss.jsp?arg=opaque</ImagePath>
    </TradeMarkInfo>
    <TradeMarkInfo>
      <SerialNumber>2</SerialNumber>
      <ApplicationNumber>4020210000002</ApplicationNumber>
      <ApplicationStatus>등록</ApplicationStatus>
      <GoodClassificationCode>09</GoodClassificationCode>
      <ViennaCode></ViennaCode>
      <ApplicantName>삼성전자주식회사</ApplicantName>
      <Title>삼성전자 SAM SUNG ELECTRONICS</Title>
    </TradeMarkInfo>
    <TradeMarkInfo>
      <SerialNumber>3</SerialNumber>
      <ApplicationNumber>4019890008545</ApplicationNumber>
      <ApplicationStatus>거절</ApplicationStatus>
      <GoodClassificationCode>034</GoodClassificationCode>
      <ViennaCode></ViennaCode>
      <ApplicantName>삼성전자주식회사</ApplicantName>
      <Title>삼성전자</Title>
    </TradeMarkInfo>
    <TradeMarkInfo>
      <SerialNumber>4</SerialNumber>
      <ApplicationNumber>4019890008532</ApplicationNumber>
      <ApplicationStatus>소멸</ApplicationStatus>
      <GoodClassificationCode>018</GoodClassificationCode>
      <ViennaCode>010109|260207</ViennaCode>
      <ApplicantName>삼성전자주식회사</ApplicantName>
      <Title>삼성전자</Title>
    </TradeMarkInfo>
  </items></body>
</response>
"""


def _make_page(total: int, serials, status: str = "등록", title: str = "삼성전자") -> str:
    """페이지네이션 테스트용 TradeMarkInfo 페이지 XML 을 만든다."""
    rows = "".join(
        f"<TradeMarkInfo><SerialNumber>{s}</SerialNumber>"
        f"<ApplicationStatus>{status}</ApplicationStatus>"
        f"<Title>{title}</Title></TradeMarkInfo>"
        for s in serials
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<response><header><resultCode>00</resultCode></header>"
        f"<body><items><TotalSearchCount>{total}</TotalSearchCount>"
        f"{rows}</items></body></response>"
    )


def test_parse_items_trademarkinfo_tag():
    # 실측 버그: <item> 만 찾던 코드는 이 응답을 0건으로 파싱했다
    items = parse_items(XML_TRADEMARK)
    assert len(items) == 4
    assert items[0]["Title"] == "삼성전자"
    # MULTI_VALUE_FIELDS 는 '|' 분리 유지
    assert items[0]["GoodClassificationCode"] == ["09", "35"]
    assert items[0]["ViennaCode"] == ["010109", "260504"]
    assert items[0]["SimilarCode"] == ["G0701", "S120602"]
    assert items[1]["ViennaCode"] == []  # 빈 다중값 → 빈 리스트
    # ApplicantName 은 MULTI_VALUE_FIELDS 가 아니므로 원문 문자열 유지
    assert items[0]["ApplicantName"] == "삼성물산 주식회사|삼성전자주식회사"
    assert items[0]["RegistrationRightholderName"] == "삼성전자주식회사"
    assert items[0]["RegistrationNumber"] == "4012340000"
    assert items[0]["ApplicationDate"] == "20210105"
    assert items[0]["RegistrationDate"] == "20230519"
    assert items[0]["TrademarkDivisionCode"] == "도형복합"
    assert items[0]["ImagePath"].startswith("http://plus.kipris.or.kr/fileToss.jsp")


def test_parse_total_count_from_trademarkinfo():
    # 전체 건수는 items 수(4)가 아니라 TotalSearchCount(59) 로 얻는다
    assert parse_total_count(XML_TRADEMARK) == 59
    # TotalSearchCount 가 없는 응답(구 <item> 형식)은 None
    assert parse_total_count(XML_OK) is None


@pytest.mark.parametrize("bad_total", ["-1", "not-a-number"])
def test_invalid_total_count_is_protocol_error(bad_total):
    xml = (
        "<response><header><resultCode>00</resultCode></header><body>"
        f"<TotalSearchCount>{bad_total}</TotalSearchCount>"
        "</body></response>"
    )
    with pytest.raises(kc.KiprisProtocolError, match="TotalSearchCount"):
        parse_total_count(xml)


def test_filter_registered_trademarkinfo():
    items = parse_items(XML_TRADEMARK)
    registered = filter_registered(items)
    assert len(registered) == 2  # 등록 2건 (거절/소멸 제외)
    assert all(it["ApplicationStatus"] == "등록" for it in registered)


def test_summarize_uses_total_search_count():
    # total_found 는 TotalSearchCount(59) 기준, registered/exact 는 수집 items 기준
    items = parse_items(XML_TRADEMARK)
    total = parse_total_count(XML_TRADEMARK)
    s = summarize_name_search("삼성전자", items, total)
    assert s["total_found"] == 59            # len(items)=4 가 아니라 전체 건수
    assert s["registered_count"] == 2
    assert s["exact_registered_count"] == 1  # "삼성전자 SAM SUNG ..."은 정확 일치 아님
    assert s["exact_title_count"] == 3  # 등록 1 + 거절 1 + 소멸 1
    assert s["status_counts"] == {"등록": 2, "거절": 1, "소멸": 1}


def test_title_match_normalizes_case_width_and_whitespace():
    items = [
        {"Title": "ＢＢＱ", "ApplicationStatus": "등록"},
        {"Title": "  bbq  ", "ApplicationStatus": "거절"},
        {"Title": "B B Q", "ApplicationStatus": "등록"},
    ]

    summary = summarize_name_search("BBQ", items, total_found=3, complete=True)

    assert kc.normalize_mark_title(" ＢＢＱ ") == "bbq"
    assert kc.normalize_mark_title("BBQ   CHICKEN") == "bbq chicken"
    assert summary["exact_title_count"] == 2
    assert summary["exact_registered_count"] == 1


def test_name_match_search_paginates_two_pages(monkeypatch):
    # 실측: 기본 30건/페이지 → 나머지는 docsStart 로 이어 받는다.
    # _get 을 몽키패치해 네트워크 없이 2페이지 시나리오를 검증한다.
    monkeypatch.setattr(kc, "ACCESS_KEY", "TESTKEY")
    monkeypatch.setattr(kc, "TM_NAME_SEARCH_URL", "https://plus.kipris.or.kr/test/op")
    page1 = _make_page(59, range(1, 31))   # 30건 (SerialNumber 1~30)
    page2 = _make_page(59, range(1, 30))   # 29건 (실측: SerialNumber 페이지마다 재시작)

    calls: list[dict] = []

    def fake_get(url, params):
        calls.append(params)
        return page2 if "docsStart" in params else page1

    monkeypatch.setattr(kc, "_get", fake_get)

    result = kc.name_match_search("삼성전자")
    items, total = result
    assert total == 59
    assert len(items) == 59        # 두 페이지를 합쳐 전부 수집
    assert len(calls) == 2         # 정확히 2회 호출
    assert calls[0]["docsCount"] == kc.NAME_SEARCH_DOCS_COUNT  # 첫 호출에 docsCount 부착
    assert "docsStart" not in calls[0]
    assert calls[1]["docsStart"] == 31  # 다음 페이지 시작 위치 (받은 30건 + 1)
    assert result.complete is True


def test_name_match_search_respects_page_cap(monkeypatch):
    # 월 예산 보호: 페이지 상한을 넘지 않고 수집분으로만 진행하되 total 은 전체 보고
    monkeypatch.setattr(kc, "ACCESS_KEY", "TESTKEY")
    monkeypatch.setattr(kc, "TM_NAME_SEARCH_URL", "https://plus.kipris.or.kr/test/op")
    monkeypatch.setattr(kc, "NAME_SEARCH_MAX_PAGES", 1)
    page = _make_page(200, range(1, 31))   # 전체 200건인데 한 페이지 30건

    calls: list[dict] = []

    def fake_get(url, params):
        calls.append(params)
        return page

    monkeypatch.setattr(kc, "_get", fake_get)

    result = kc.name_match_search("X")
    items, total = result
    assert total == 200        # 전체 건수는 TotalSearchCount 로 정확히 보고
    assert len(items) == 30    # 상한으로 수집분만
    assert len(calls) == 1     # 페이지 상한(1) 준수 — 추가 호출 없음
    assert result.complete is False


def test_name_match_search_marks_underreported_total_incomplete(monkeypatch):
    monkeypatch.setattr(kc, "ACCESS_KEY", "TESTKEY")
    monkeypatch.setattr(kc, "TM_NAME_SEARCH_URL", "https://plus.kipris.or.kr/test/op")
    page = _make_page(1, range(1, 3))
    monkeypatch.setattr(kc, "_get", lambda url, params: page)

    result = kc.name_match_search("X")
    assert result.total_found == 2
    assert result.scanned_count == 2
    assert result.complete is False


def test_name_match_search_stops_on_repeated_page(monkeypatch):
    monkeypatch.setattr(kc, "ACCESS_KEY", "TESTKEY")
    monkeypatch.setattr(kc, "TM_NAME_SEARCH_URL", "https://plus.kipris.or.kr/test/op")
    page = _make_page(100, range(1, 31))
    calls = []

    def fake_get(url, params):
        calls.append(params)
        return page

    monkeypatch.setattr(kc, "_get", fake_get)

    result = kc.name_match_search("X")
    assert result.scanned_count == 30
    assert result.complete is False
    assert len(calls) == 2


def test_rate_limiter_budget_and_persistence(tmp_path):
    counter = tmp_path / "count.json"
    lim = RateLimiter(counter_path=counter, monthly_budget=2, min_interval=0)
    lim.acquire()
    lim.acquire()
    with pytest.raises(CallBudgetExceeded):
        lim.acquire()
    # 새 인스턴스(프로세스 재시작 시뮬레이션)에도 월 누적이 유지된다
    lim2 = RateLimiter(counter_path=counter, monthly_budget=2, min_interval=0)
    assert lim2.used_this_month() == 2
    with pytest.raises(CallBudgetExceeded):
        lim2.acquire()


def test_rate_limiter_daily_budget_and_day_key_pruning(tmp_path):
    counter = tmp_path / "count.json"
    lim = RateLimiter(
        counter_path=counter, monthly_budget=100, min_interval=0, daily_budget=2
    )
    lim.acquire()
    lim.acquire()
    with pytest.raises(CallBudgetExceeded, match="오늘"):
        lim.acquire()
    assert lim.used_today() == 2
    assert lim.used_this_month() == 2

    # 월 키("YYYY-MM")와 일 키("YYYY-MM-DD")가 같은 파일에 공존한다
    counts = json.loads(counter.read_text(encoding="utf-8"))
    assert counts[lim._month_key()] == 2
    assert counts[lim._day_key()] == 2

    # 보존 기간이 지난 일 키는 다음 쓰기에서 정리되고, 월 키는 남는다
    counts["2000-01-01"] = 7
    counts["2000-01"] = 7
    counter.write_text(json.dumps(counts), encoding="utf-8")
    lim2 = RateLimiter(
        counter_path=counter, monthly_budget=100, min_interval=0, daily_budget=10
    )
    lim2.acquire()
    remaining = json.loads(counter.read_text(encoding="utf-8"))
    assert "2000-01-01" not in remaining
    assert remaining["2000-01"] == 7
    assert remaining[lim2._month_key()] == 3


def test_rate_limiter_daily_budget_disabled_when_nonpositive(tmp_path):
    lim = RateLimiter(
        counter_path=tmp_path / "count.json",
        monthly_budget=100,
        min_interval=0,
        daily_budget=0,
    )
    for _ in range(5):
        lim.acquire()
    assert lim.used_today() == 5
