"""KIPRIS 클라이언트 단위 테스트 — 전부 네트워크 없이 동작한다."""

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
      <ApplicationStatus>등록</ApplicationStatus>
      <GoodClassificationCode>09|35</GoodClassificationCode>
      <ViennaCode>010109|260504</ViennaCode>
      <ApplicantName>삼성물산 주식회사|삼성전자주식회사</ApplicantName>
      <Title>삼성전자</Title>
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
    assert items[1]["ViennaCode"] == []  # 빈 다중값 → 빈 리스트
    # ApplicantName 은 MULTI_VALUE_FIELDS 가 아니므로 원문 문자열 유지
    assert items[0]["ApplicantName"] == "삼성물산 주식회사|삼성전자주식회사"


def test_parse_total_count_from_trademarkinfo():
    # 전체 건수는 items 수(4)가 아니라 TotalSearchCount(59) 로 얻는다
    assert parse_total_count(XML_TRADEMARK) == 59
    # TotalSearchCount 가 없는 응답(구 <item> 형식)은 None
    assert parse_total_count(XML_OK) is None


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


def test_name_match_search_paginates_two_pages(monkeypatch):
    # 실측: 기본 30건/페이지 → 나머지는 docsStart 로 이어 받는다.
    # _get 을 몽키패치해 네트워크 없이 2페이지 시나리오를 검증한다.
    monkeypatch.setattr(kc, "ACCESS_KEY", "TESTKEY")
    monkeypatch.setattr(kc, "TM_NAME_SEARCH_URL", "http://test/op")
    page1 = _make_page(59, range(1, 31))   # 30건 (SerialNumber 1~30)
    page2 = _make_page(59, range(1, 30))   # 29건 (실측: SerialNumber 페이지마다 재시작)

    calls: list[dict] = []

    def fake_get(url, params):
        calls.append(params)
        return page2 if "docsStart" in params else page1

    monkeypatch.setattr(kc, "_get", fake_get)

    items, total = kc.name_match_search("삼성전자")
    assert total == 59
    assert len(items) == 59        # 두 페이지를 합쳐 전부 수집
    assert len(calls) == 2         # 정확히 2회 호출
    assert calls[0]["docsCount"] == kc.NAME_SEARCH_DOCS_COUNT  # 첫 호출에 docsCount 부착
    assert "docsStart" not in calls[0]
    assert calls[1]["docsStart"] == 31  # 다음 페이지 시작 위치 (받은 30건 + 1)


def test_name_match_search_respects_page_cap(monkeypatch):
    # 월 예산 보호: 페이지 상한을 넘지 않고 수집분으로만 진행하되 total 은 전체 보고
    monkeypatch.setattr(kc, "ACCESS_KEY", "TESTKEY")
    monkeypatch.setattr(kc, "TM_NAME_SEARCH_URL", "http://test/op")
    monkeypatch.setattr(kc, "NAME_SEARCH_MAX_PAGES", 1)
    page = _make_page(200, range(1, 31))   # 전체 200건인데 한 페이지 30건

    calls: list[dict] = []

    def fake_get(url, params):
        calls.append(params)
        return page

    monkeypatch.setattr(kc, "_get", fake_get)

    items, total = kc.name_match_search("X")
    assert total == 200        # 전체 건수는 TotalSearchCount 로 정확히 보고
    assert len(items) == 30    # 상한으로 수집분만
    assert len(calls) == 1     # 페이지 상한(1) 준수 — 추가 호출 없음


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
