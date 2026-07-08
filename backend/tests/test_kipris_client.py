"""KIPRIS 클라이언트 단위 테스트 — 전부 네트워크 없이 동작한다."""

import pytest

from backend.src.core.kipris_client import (
    CallBudgetExceeded,
    KiprisError,
    RateLimiter,
    check_result_code,
    filter_registered,
    parse_items,
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
