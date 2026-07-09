"""
백엔드-5 수집 파이프라인(collect_pipeline) 파싱/필터 단위 테스트.

전부 네트워크 없이 동작한다 — KIPRIS 실호출은 monkeypatch/픽스처로 대체하고,
main() 은 항상 --dry-run + config.DATABASE_URL="" 로 이중 차단한다(실 DB/다운로드 금지).

감사보고서(5-2) 공백 보강: "collect_pipeline 파싱(레코딩 XML 픽스처)".
검증 대상:
  ① 상태 필터        — ApplicationStatus == "등록" 만 수집
  ② 비엔나 빈값 제외  — ViennaCode 빈 값(순수 문자상표 가능성) 제외
  ③ 필드 매핑        — item_to_row (출원번호 정규화·류 int 변환·다중값 포함)
  ④ 페이지네이션 파싱 — TotalSearchCount 를 가진 다건 응답 페이지 파싱

실행 (project root 기준):
    ml\\venv\\Scripts\\python.exe -m pytest backend/tests/test_collect_pipeline.py -q
"""

import pytest

from backend.scripts import collect_pipeline as cp
from backend.src.core import kipris_client as kc


# --------------------------------------------------------------------
# 출원인 검색 응답 픽스처 (실제 KIPRIS 응답 형태)
#   등록/거절/소멸 혼합 · ViennaCode 빈 값 · "문구 포함" 케이스 ·
#   하이픈 포함 출원번호 · 상표 아닌 번호(특허 10..) 혼입
# --------------------------------------------------------------------
XML_APPLICANT = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode><resultMsg>NORMAL</resultMsg></header>
  <body><items>
    <item>
      <Title>삼성전자 로고</Title>
      <ApplicationStatus>등록</ApplicationStatus>
      <ApplicationNumber>40-2021-0000001</ApplicationNumber>
      <RegistrationNumber>4012340000</RegistrationNumber>
      <ApplicationDate>20210101</ApplicationDate>
      <RegistrationDate>20220301</RegistrationDate>
      <DrawingKindName>도형복합</DrawingKindName>
      <ViennaCode>260101|270501</ViennaCode>
      <GoodClassificationCode>09|35|A1</GoodClassificationCode>
      <SimilarCode>G0301|G3901</SimilarCode>
      <ApplicantName>삼성전자 주식회사</ApplicantName>
      <RegistrationRightholderName>삼성전자 주식회사</RegistrationRightholderName>
      <ImagePath>http://plus.kipris.or.kr/fileToss.jsp?a=1</ImagePath>
    </item>
    <item>
      <Title>삼성전자 SAM SUNG ELECTRONICS</Title>
      <ApplicationStatus>등록</ApplicationStatus>
      <ApplicationNumber>4020210000002</ApplicationNumber>
      <ViennaCode>270501</ViennaCode>
      <GoodClassificationCode>09</GoodClassificationCode>
    </item>
    <item>
      <Title>순수문자상표</Title>
      <ApplicationStatus>등록</ApplicationStatus>
      <ApplicationNumber>4020210000003</ApplicationNumber>
      <ViennaCode></ViennaCode>
      <GoodClassificationCode>09</GoodClassificationCode>
    </item>
    <item>
      <Title>소멸된로고</Title>
      <ApplicationStatus>소멸</ApplicationStatus>
      <ApplicationNumber>4019990000004</ApplicationNumber>
      <ViennaCode>260101</ViennaCode>
    </item>
    <item>
      <Title>거절된로고</Title>
      <ApplicationStatus>거절</ApplicationStatus>
      <ApplicationNumber>4019990000005</ApplicationNumber>
      <ViennaCode>260101</ViennaCode>
    </item>
    <item>
      <Title>특허혼입</Title>
      <ApplicationStatus>등록</ApplicationStatus>
      <ApplicationNumber>1020210000006</ApplicationNumber>
      <ViennaCode>260101</ViennaCode>
    </item>
  </items></body>
</response>
"""


def _fresh_report() -> dict:
    """main() 이 만드는 리포트 dict 와 동일한 키 세트 (should_collect 가 증가시킴)."""
    return {
        "검색결과": 0, "수집": 0, "이미지실패": 0,
        "제외_미등록": 0, "제외_비엔나없음(문자상표)": 0, "제외_상표번호아님": 0,
    }


# ====================================================================
# ① 상태 필터 · ② 비엔나 빈값 제외 · 상표번호 필터 (should_collect)
# ====================================================================

def test_should_collect_filters_by_status_and_vienna():
    items = kc.parse_items(XML_APPLICANT)
    report = _fresh_report()
    picked = [it for it in items if cp.should_collect(it, report)]

    # 등록 + 비엔나 있음 + 상표번호 = 2건 (삼성전자 로고, 삼성전자 SAM SUNG...)
    titles = [it["Title"] for it in picked]
    assert titles == ["삼성전자 로고", "삼성전자 SAM SUNG ELECTRONICS"]
    # 제외 사유별 집계 (소멸/거절=미등록 2, 비엔나없음 1, 특허번호 1)
    assert report["제외_미등록"] == 2
    assert report["제외_비엔나없음(문자상표)"] == 1
    assert report["제외_상표번호아님"] == 1


def test_should_collect_rejects_unregistered():
    # 소멸·거절은 ApplicationStatus != "등록" → 제외
    for status in ("소멸", "거절", "출원", "공고"):
        report = _fresh_report()
        item = {"ApplicationStatus": status, "ViennaCode": ["260101"],
                "ApplicationNumber": "4020210000001"}
        assert cp.should_collect(item, report) is False
        assert report["제외_미등록"] == 1


def test_should_collect_rejects_empty_vienna():
    # ViennaCode 빈 리스트(순수 문자상표 가능성) → 제외
    report = _fresh_report()
    item = {"ApplicationStatus": "등록", "ViennaCode": [],
            "ApplicationNumber": "4020210000001"}
    assert cp.should_collect(item, report) is False
    assert report["제외_비엔나없음(문자상표)"] == 1


def test_should_collect_rejects_non_trademark_number():
    # 특허(10..) 등 상표/서비스표(40/41) 아닌 번호 → 제외
    report = _fresh_report()
    item = {"ApplicationStatus": "등록", "ViennaCode": ["260101"],
            "ApplicationNumber": "1020210000006"}
    assert cp.should_collect(item, report) is False
    assert report["제외_상표번호아님"] == 1


def test_should_collect_accepts_contains_match():
    # "완전일치"여도 문구 포함 상표까지 잡히지만, 수집 파이프라인은 등록 로고면 채택한다
    report = _fresh_report()
    item = {"Title": "삼성전자 SAM SUNG ELECTRONICS", "ApplicationStatus": "등록",
            "ViennaCode": ["270501"], "ApplicationNumber": "4020210000002"}
    assert cp.should_collect(item, report) is True


# ====================================================================
# ③ 필드 매핑 + 출원번호 정규화 (item_to_row)
# ====================================================================

def test_item_to_row_field_mapping_and_normalization():
    item = kc.parse_items(XML_APPLICANT)[0]  # "삼성전자 로고"
    row = cp.item_to_row(item)
    (app_no, reg_no, app_date, reg_date, name_ko, name_en, mark_type,
     applicant, right_holder, image_key, vienna, nice, similar) = row

    # 출원번호: 하이픈 제거 정규화 (조인 키 통일)
    assert app_no == "4020210000001"
    # 이미지 키는 정규화된 출원번호 기반
    assert image_key == "4020210000001.png"
    assert reg_no == "4012340000"
    # 날짜: YYYYMMDD → ISO
    assert app_date == "2021-01-01"
    assert reg_date == "2022-03-01"
    # 한글명 슬롯에 원문 Title, 영문명은 후속 보강이라 None
    assert name_ko == "삼성전자 로고"
    assert name_en is None
    assert mark_type == "도형복합"
    assert applicant == "삼성전자 주식회사"
    assert right_holder == "삼성전자 주식회사"
    # 다중값: 비엔나는 문자열 리스트 유지
    assert vienna == ["260101", "270501"]
    # 류(GoodClassificationCode): 숫자만 int 로 (비숫자 "A1" 은 버림)
    assert nice == [9, 35]
    # 유사군 코드: 문자열 리스트
    assert similar == ["G0301", "G3901"]


def test_item_to_row_defaults_missing_optional_fields():
    # 선택 필드가 없어도 None/기본값으로 안전하게 매핑되는지 (2번째 item: 최소 필드)
    item = kc.parse_items(XML_APPLICANT)[1]  # "삼성전자 SAM SUNG ELECTRONICS"
    row = cp.item_to_row(item)
    app_no, reg_no = row[0], row[1]
    assert app_no == "4020210000002"
    assert reg_no is None          # RegistrationNumber 없음 → None
    assert row[8] is None          # RegistrationRightholderName 없음 → None
    assert row[10] == ["270501"]   # vienna_codes
    assert row[11] == [9]          # nice_classes
    assert row[12] == []           # similarity_codes (없음)


# ====================================================================
# ④ 페이지네이션 응답 파싱
#   상표명완전일치/출원인 응답은 <TotalSearchCount> + 다건 항목으로 페이지네이션된다.
#   파이프라인이 쓰는 parse_items/parse_total_count 가 페이지 항목을 온전히 읽는지 검증.
# ====================================================================
XML_PAGE = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode></header>
  <body><items>
    <TotalSearchCount>59</TotalSearchCount>
    <TradeMarkInfo>
      <ApplicationNumber>4020210000001</ApplicationNumber>
      <ApplicationStatus>등록</ApplicationStatus>
      <ViennaCode>010109|260504</ViennaCode>
      <Title>브랜드A</Title>
    </TradeMarkInfo>
    <TradeMarkInfo>
      <ApplicationNumber>4020210000002</ApplicationNumber>
      <ApplicationStatus>거절</ApplicationStatus>
      <ViennaCode>270501</ViennaCode>
      <Title>브랜드B</Title>
    </TradeMarkInfo>
    <TradeMarkInfo>
      <ApplicationNumber>4020210000003</ApplicationNumber>
      <ApplicationStatus>등록</ApplicationStatus>
      <ViennaCode></ViennaCode>
      <Title>브랜드C</Title>
    </TradeMarkInfo>
  </items></body>
</response>
"""


def test_pagination_page_parsing_and_total_count():
    items = kc.parse_items(XML_PAGE)
    # 한 페이지의 항목 3건 모두 파싱 (<TradeMarkInfo> 태그)
    assert len(items) == 3
    # 전체 건수는 len(items)=3 이 아니라 TotalSearchCount=59
    assert kc.parse_total_count(XML_PAGE) == 59
    # 페이지 항목에 수집 필터를 적용하면 등록+비엔나 있는 1건만 채택 (브랜드A)
    report = _fresh_report()
    picked = [it for it in items if cp.should_collect(it, report)]
    assert [it["Title"] for it in picked] == ["브랜드A"]
    assert report["제외_미등록"] == 1               # 브랜드B(거절)
    assert report["제외_비엔나없음(문자상표)"] == 1  # 브랜드C(비엔나 없음)


# ====================================================================
# main() 오프라인 흐름 (--dry-run + DATABASE_URL="" 이중 차단)
# ====================================================================

def _no_db(monkeypatch):
    """실 DB 쓰기/인덱스 재빌드를 원천 차단 (dry-run 과 이중 안전)."""
    monkeypatch.setattr(cp.config, "DATABASE_URL", "")


def test_main_dry_run_mock_xml(tmp_path, monkeypatch, capsys):
    _no_db(monkeypatch)
    xml_file = tmp_path / "mock.xml"
    xml_file.write_text(XML_APPLICANT, encoding="utf-8")
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--mock-xml", str(xml_file), "--dry-run"])
    rc = cp.main()
    out = capsys.readouterr().out
    assert rc == 0
    # 검색 6건 중 수집 2건 (등록+비엔나+상표번호)
    assert "'검색결과': 6" in out
    assert "'수집': 2" in out
    assert "[dry-run] 수집 대상: 4020210000001" in out  # 하이픈 번호 정규화 확인


def test_main_dry_run_applicant_batch(monkeypatch, capsys):
    # --applicant 배치 경로: applicant_search 를 monkeypatch 해 네트워크 없이 흐름 검증
    _no_db(monkeypatch)
    monkeypatch.setattr(kc, "applicant_search",
                        lambda name: kc.parse_items(XML_APPLICANT))
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자", "--dry-run"])
    rc = cp.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "'수집': 2" in out


def test_main_all_filtered_returns_2(tmp_path, monkeypatch):
    # 검색 결과는 있으나 전부 걸러지면 조용히 성공하지 않고 실패(2) 로 알린다
    _no_db(monkeypatch)
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>00</resultCode></header><body><items>
  <item><Title>거절</Title><ApplicationStatus>거절</ApplicationStatus>
    <ApplicationNumber>4020210000009</ApplicationNumber><ViennaCode>260101</ViennaCode></item>
</items></body></response>"""
    xml_file = tmp_path / "all_rejected.xml"
    xml_file.write_text(xml, encoding="utf-8")
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--mock-xml", str(xml_file), "--dry-run"])
    assert cp.main() == 2


def test_main_limit_caps_per_applicant(monkeypatch, capsys):
    # --limit 은 출원인당 수집 상한 (호출 예산 관리)
    _no_db(monkeypatch)
    monkeypatch.setattr(kc, "applicant_search",
                        lambda name: kc.parse_items(XML_APPLICANT))
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자",
                         "--limit", "1", "--dry-run"])
    rc = cp.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "'수집': 1" in out  # 2건 대상이지만 limit=1 로 1건만
