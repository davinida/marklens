"""
백엔드-6: 본 수집 경로를 getAdvancedSearch 로 전환한 부분의 단위 테스트.

전부 네트워크 없이 동작한다 — HTTP 클라이언트/리미터를 mock 으로 대체해 KIPRIS
실호출 0회를 코드로 강제한다. 픽스처는 실제 응답을 복사하지 않고, 실측 구조를 본뜬
**합성 camelCase 데이터**로 직접 작성했다(저작권 — 실 응답 원문 커밋 금지).

검증 대상:
  ① advanced_search 가 불리언 플래그 30개를 "전부" 실어 보내는지(요청 파라미터)
  ② 인증 파라미터 분기 — advanced 는 ServiceKey, name-match 는 accessKey
  ③ normalize_advanced_item 매핑(다중값 '|' 분해·bigDrawing 우선·빈 title·유사군 빈 배열)
  ④ 정규화 → should_collect → item_to_row 전 구간(40/41 필터·비엔나 빈값 제외 유지)

실행 (project root 기준):
    ml\\venv\\Scripts\\python.exe -m pytest backend/tests/test_advanced_search.py -q
"""

from backend.scripts import collect_pipeline as cp
from backend.src.core import kipris_client as kc


# --------------------------------------------------------------------
# 네트워크 없는 HTTP mock — 요청 파라미터를 기록하고 합성 XML 을 돌려준다.
# --------------------------------------------------------------------
class _Resp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        pass


class _RecordingClient:
    """_get 이 부르는 최소 인터페이스만 흉내낸다(.get(url, params=...))."""

    def __init__(self, xml: str):
        self._xml = xml
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        return _Resp(self._xml)


class _NoLimiter:
    """월 카운터/딜레이를 건드리지 않는 리미터 대체(실 카운터 파일 오염 방지)."""

    def acquire(self) -> None:
        pass


def _install_client(monkeypatch, xml: str) -> _RecordingClient:
    client = _RecordingClient(xml)
    monkeypatch.setattr(kc, "ACCESS_KEY", "TESTKEY")
    monkeypatch.setattr(kc, "_get_client", lambda: client)
    monkeypatch.setattr(kc, "limiter", _NoLimiter())
    return client


def _fresh_report() -> dict:
    """should_collect 가 증가시키는 제외 사유 키 세트(main() 리포트의 부분집합)."""
    return {"제외_미등록": 0, "제외_비엔나없음(문자상표)": 0, "제외_상표번호아님": 0}


# 항목별검색(getAdvancedSearch) 합성 응답 — camelCase, 항목 태그 <item>,
# 전체 건수 <totalCount>, 유사군 필드 없음, drawing/bigDrawing 일회성 링크.
ADV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode><resultMsg>success</resultMsg></header>
  <count><totalCount>630</totalCount><numOfRows>20</numOfRows><pageNo>1</pageNo></count>
  <body><items>
    <item>
      <applicationNumber>4020210000001</applicationNumber>
      <applicationStatus>등록</applicationStatus>
      <title>삼성 로고</title>
      <registrationNumber>4012340000</registrationNumber>
      <applicationDate>20210101</applicationDate>
      <registrationDate>20220301</registrationDate>
      <applicantName>삼성전자 주식회사</applicantName>
      <regPrivilegeName>삼성전자 주식회사</regPrivilegeName>
      <viennaCode>260101|270501</viennaCode>
      <classificationCode>09|35</classificationCode>
      <drawing>http://plus.kipris.or.kr/fileToss.jsp?arg=small1</drawing>
      <bigDrawing>http://plus.kipris.or.kr/fileToss.jsp?arg=big1</bigDrawing>
    </item>
  </items></body>
</response>
"""

# 상표명완전일치(PascalCase) — name_match_search 가 1회 호출 후 종료하도록
# TotalSearchCount=1 + 1건.
NAME_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode></header>
  <body><items>
    <TotalSearchCount>1</TotalSearchCount>
    <TradeMarkInfo>
      <ApplicationNumber>4020210000001</ApplicationNumber>
      <ApplicationStatus>등록</ApplicationStatus>
      <Title>삼성전자</Title>
    </TradeMarkInfo>
  </items></body>
</response>
"""


# ====================================================================
# ① 플래그 30개 전부 전송 + ② 인증 파라미터 ServiceKey
# ====================================================================

def test_advanced_search_sends_all_30_flags_with_servicekey(monkeypatch):
    client = _install_client(monkeypatch, ADV_XML)

    items, total = kc.advanced_search("삼성전자")
    params = client.calls[0]["params"]

    # 플래그가 정확히 30개(행정 8 + 표장유형 9 + 표장구성 13)이고 전부 실렸다.
    assert len(kc.ADVANCED_ALL_FLAGS) == 30
    assert len(set(kc.ADVANCED_ALL_FLAGS)) == 30  # 중복 없음
    for flag in kc.ADVANCED_ALL_FLAGS:
        assert flag in params, f"플래그 누락: {flag}"
        assert params[flag] in ("true", "false")  # 값은 문자열

    # 기본 필터: 등록만 / 도형·도형복합만 / 표장유형 전부.
    assert params["registration"] == "true"
    assert params["application"] == "false"
    assert params["refused"] == "false"
    assert params["figure"] == "true"
    assert params["figureComposition"] == "true"
    assert params["character"] == "false"
    assert all(params[m] == "true" for m in kc.ADVANCED_MARK_TYPE_FLAGS)

    # 인증 파라미터 분기: advanced 는 ServiceKey (accessKey 아님).
    assert params["ServiceKey"] == "TESTKEY"
    assert "accessKey" not in params
    # 출원인 파라미터 + 정확한 오퍼레이션 URL.
    assert params["applicantName"] == "삼성전자"
    assert client.calls[0]["url"] == kc.ADVANCED_SEARCH_URL

    # 반환: 정규화된 item + 전체 건수(totalCount).
    assert total == 630
    assert items[0]["ApplicationNumber"] == "4020210000001"


def test_advanced_search_flags_are_overridable(monkeypatch):
    # 호출자가 필터 정책을 바꿀 수 있다(기본값만 강제되는 게 아님).
    client = _install_client(monkeypatch, ADV_XML)
    kc.advanced_search("삼성전자", true_flags=frozenset({"application", "character"}))
    params = client.calls[0]["params"]
    assert params["application"] == "true"
    assert params["character"] == "true"
    assert params["registration"] == "false"  # 기본 true 였던 것이 false 로
    assert params["figure"] == "false"
    # 여전히 30개 전부 실린다(일부만 넘기면 resultCode=10).
    assert all(f in params for f in kc.ADVANCED_ALL_FLAGS)


def test_name_match_search_uses_accesskey_not_servicekey(monkeypatch):
    # 인증 파라미터 분기의 반대편: name-match 는 여전히 accessKey.
    client = _install_client(monkeypatch, NAME_XML)
    monkeypatch.setattr(
        kc,
        "TM_NAME_SEARCH_URL",
        "https://plus.kipris.or.kr/test/name-match",
    )

    items, total = kc.name_match_search("삼성전자")
    params = client.calls[0]["params"]

    assert params["accessKey"] == "TESTKEY"
    assert "ServiceKey" not in params
    assert len(client.calls) == 1  # TotalSearchCount=1 → 1건 받고 종료
    assert total == 1


def test_build_advanced_flags_default_true_set(monkeypatch):
    flags = kc.build_advanced_flags()
    true_flags = {k for k, v in flags.items() if v == "true"}
    # 등록 + 도형 + 도형복합 + 표장유형 9종 = 12개가 true.
    assert true_flags == {"registration", "figure", "figureComposition",
                          *kc.ADVANCED_MARK_TYPE_FLAGS}
    assert len(flags) == 30


# ====================================================================
# ③ normalize_advanced_item 매핑
# ====================================================================

def test_normalize_advanced_item_mapping():
    item = {
        "applicationNumber": "4020210000001",
        "applicationStatus": "등록",
        "title": "삼성 로고",
        "registrationNumber": "4012340000",
        "applicationDate": "20210101",
        "registrationDate": "20220301",
        "applicantName": "삼성전자 주식회사",
        "regPrivilegeName": "삼성전자 주식회사",
        "viennaCode": "260101|270501",
        "classificationCode": "09|35",
        "drawing": "http://plus.kipris.or.kr/fileToss.jsp?arg=small",
        "bigDrawing": "http://plus.kipris.or.kr/fileToss.jsp?arg=big",
    }
    n = kc.normalize_advanced_item(item)

    assert n["ApplicationNumber"] == "4020210000001"
    assert n["ApplicationStatus"] == "등록"
    assert n["Title"] == "삼성 로고"
    assert n["RegistrationNumber"] == "4012340000"
    assert n["ApplicantName"] == "삼성전자 주식회사"
    assert n["RegistrationRightholderName"] == "삼성전자 주식회사"
    # 다중값 '|' 분해
    assert n["ViennaCode"] == ["260101", "270501"]
    assert n["GoodClassificationCode"] == ["09", "35"]
    # bigDrawing(큰 이미지) 우선
    assert n["ImagePath"] == "http://plus.kipris.or.kr/fileToss.jsp?arg=big"
    # 유사군 없음 → 빈 배열(TODO 후속 보강)
    assert n["SimilarCode"] == []


def test_normalize_advanced_item_drawing_fallback_and_empty_title():
    # bigDrawing 이 없으면 drawing 을 이미지로, 빈 title 은 그대로 둔다.
    item = {
        "applicationNumber": "4020210000002",
        "applicationStatus": "등록",
        "title": "",
        "viennaCode": "270501",
        "classificationCode": "09",
        "drawing": "http://plus.kipris.or.kr/fileToss.jsp?arg=small2",
    }
    n = kc.normalize_advanced_item(item)
    assert n["ImagePath"] == "http://plus.kipris.or.kr/fileToss.jsp?arg=small2"
    assert n["Title"] == ""
    assert n["ViennaCode"] == ["270501"]
    assert n["SimilarCode"] == []


def test_normalize_advanced_item_passes_through_canonical():
    # 이미 정규 키(PascalCase)인 항목(레거시 name-match 원본·mock)은 그대로 통과.
    canonical = {"ApplicationNumber": "4020210000003", "ApplicationStatus": "등록",
                 "ViennaCode": ["260101"], "Title": "이미정규"}
    assert kc.normalize_advanced_item(canonical) is canonical


# ====================================================================
# ④ 정규화 → should_collect → item_to_row 전 구간
# ====================================================================

def test_normalize_then_should_collect_then_item_to_row():
    item = {
        "applicationNumber": "40-2021-0000001",   # 하이픈 포함 — 정규화 확인
        "applicationStatus": "등록",
        "title": "삼성 로고",
        "registrationNumber": "4012340000",
        "applicationDate": "20210101",
        "registrationDate": "20220301",
        "applicantName": "삼성전자 주식회사",
        "regPrivilegeName": "삼성전자 주식회사",
        "viennaCode": "260101|270501",
        "classificationCode": "09|35",
        "bigDrawing": "http://plus.kipris.or.kr/fileToss.jsp?arg=big",
    }
    n = kc.normalize_advanced_item(item)

    report = _fresh_report()
    assert cp.should_collect(n, report) is True

    row = cp.item_to_row(n)
    assert row[0] == "4020210000001"          # 출원번호 정규화(하이픈 제거)
    assert row[1] == "4012340000"             # 등록번호
    assert row[9] == "4020210000001.png"      # 이미지 키
    assert row[10] == ["260101", "270501"]    # 비엔나 코드 리스트
    assert row[11] == [9, 35]                 # 류(숫자만 int)
    assert row[12] == []                      # 유사군(similarity_codes) 빈 배열


def test_chain_rejects_non_trademark_and_empty_vienna():
    # 50.. 접두 → 채택 (2026-07-10 정책 적용: 등록번호 40/41 인 정식 상표로 실측 확인,
    # 특허 10/실용신안 20/디자인권 30 만 블랙리스트로 제외).
    n_50 = kc.normalize_advanced_item({
        "applicationNumber": "5020210000001", "applicationStatus": "등록",
        "viennaCode": "260101", "title": "도형50"})
    r1 = _fresh_report()
    assert cp.should_collect(n_50, r1) is True
    assert r1["제외_상표번호아님"] == 0

    # 특허(10..)는 상표가 아닌 별개 권리 → 제외 유지(블랙리스트의 존재 이유).
    n_patent = kc.normalize_advanced_item({
        "applicationNumber": "1020210000001", "applicationStatus": "등록",
        "viennaCode": "260101", "title": "특허혼입"})
    r_p = _fresh_report()
    assert cp.should_collect(n_patent, r_p) is False
    assert r_p["제외_상표번호아님"] == 1

    # 비엔나 빈 값(순수 문자상표 가능성) → 제외 유지.
    n_empty = kc.normalize_advanced_item({
        "applicationNumber": "4020210000009", "applicationStatus": "등록",
        "viennaCode": "", "title": "문자상표"})
    r2 = _fresh_report()
    assert cp.should_collect(n_empty, r2) is False
    assert r2["제외_비엔나없음(문자상표)"] == 1


def test_advanced_search_end_to_end_offline(monkeypatch):
    # advanced_search(camelCase) → normalize → should_collect → item_to_row 가 붙는지.
    _install_client(monkeypatch, ADV_XML)
    items, total = kc.advanced_search("삼성전자")
    assert total == 630
    report = _fresh_report()
    picked = [it for it in items if cp.should_collect(it, report)]
    assert len(picked) == 1
    row = cp.item_to_row(picked[0])
    assert row[0] == "4020210000001"
    assert row[11] == [9, 35]


# ====================================================================
# 페이징 (공식 문서: pageNo / numOfRows, 기본 30 · 최대 500)
#   같은 건수를 적은 호출로 받는 것이 월 1,000회 예산의 핵심이다.
# ====================================================================

def test_advanced_search_sends_pagination_params(monkeypatch):
    """기본 요청이 numOfRows=500(상한) · pageNo=1 을 싣는지."""
    client = _install_client(monkeypatch, ADV_XML)
    kc.advanced_search("삼성전자")
    params = client.calls[0]["params"]
    assert params["numOfRows"] == "500"
    assert params["pageNo"] == "1"


def test_advanced_search_clamps_rows_to_official_max(monkeypatch):
    """공식 상한(500)을 넘겨 요청하면 500으로 깎는다 — 서버 거절 방지."""
    client = _install_client(monkeypatch, ADV_XML)
    kc.advanced_search("삼성전자", page_no=3, num_of_rows=9999)
    params = client.calls[0]["params"]
    assert params["numOfRows"] == "500"
    assert params["pageNo"] == "3"


def _paged_xml(total: int, app_numbers: list[str]) -> str:
    items = "".join(
        f"<item><applicationNumber>{n}</applicationNumber>"
        f"<applicationStatus>등록</applicationStatus>"
        f"<viennaCode>260101</viennaCode><classificationCode>09</classificationCode>"
        f"<title>t{n}</title><bigDrawing>http://x/big?arg={n}</bigDrawing></item>"
        for n in app_numbers
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><response>'
        "<header><resultCode>00</resultCode></header>"
        f"<count><totalCount>{total}</totalCount></count>"
        f"<body><items>{items}</items></body></response>"
    )


def test_search_batch_follows_pages_until_total(monkeypatch, tmp_path):
    """search_batch 가 totalCount 를 다 받을 때까지 pageNo 를 올리며 이어받고,
    페이지마다 원본을 따로 선저장하는지(DoD Ⓐ)."""
    monkeypatch.setattr(cp, "COLLECT_RAW_XML_DIR", tmp_path / "raw")
    # 한 페이지에 2건씩, 전체 3건 → 2페이지에서 멈춘다.
    monkeypatch.setattr(kc, "ADVANCED_DEFAULT_ROWS", 2)
    pages = {
        1: _paged_xml(3, ["4020210000001", "4020210000002"]),
        2: _paged_xml(3, ["4020210000003"]),
    }
    seen: list[int] = []

    def fake_raw(
        applicant,
        true_flags=None,
        page_no=1,
        num_of_rows=2,
        request_timeout=None,
    ):
        seen.append(page_no)
        return pages[page_no]

    monkeypatch.setattr(kc, "advanced_search_raw", fake_raw)

    items = cp.search_batch("삼성전자")
    assert seen == [1, 2], "totalCount 를 다 받을 때까지 페이지를 이어받아야 한다"
    assert [i["ApplicationNumber"] for i in items] == [
        "4020210000001", "4020210000002", "4020210000003"]
    saved = sorted(p.name for p in (tmp_path / "raw").glob("*.xml"))
    assert len(saved) == 2, f"페이지마다 원본을 저장해야 한다: {saved}"


def test_search_batch_stops_on_short_page(monkeypatch, tmp_path):
    """페이지가 덜 차면(마지막 페이지) 추가 호출을 하지 않는다 — 쿼터 낭비 방지."""
    monkeypatch.setattr(cp, "COLLECT_RAW_XML_DIR", tmp_path / "raw")
    monkeypatch.setattr(kc, "ADVANCED_DEFAULT_ROWS", 500)
    calls: list[int] = []

    def fake_raw(
        applicant,
        true_flags=None,
        page_no=1,
        num_of_rows=500,
        request_timeout=None,
    ):
        calls.append(page_no)
        # totalCount 가 999 라고 우겨도, 페이지가 덜 찼으면 마지막이다.
        return _paged_xml(999, ["4020210000001"])

    monkeypatch.setattr(kc, "advanced_search_raw", fake_raw)

    cp.search_batch("삼성전자")
    assert calls == [1], "덜 찬 페이지 뒤에는 호출하지 않아야 한다"
