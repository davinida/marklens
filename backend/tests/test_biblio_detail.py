"""
백엔드-6: 서지상세정보(getBibliographyDetailInfoSearch) 유사군 보강 단위 테스트.

전부 네트워크 없이 동작한다 — HTTP 클라이언트/리미터를 mock 으로 대체하고,
collect_pipeline 의 서지상세 호출도 monkeypatch 로 대체해 KIPRIS 실호출 0회를
코드로 강제한다. 픽스처는 실 응답을 복사하지 않고, 실측 경로 구조(중첩 Array)를
본뜬 **합성 데이터**로 직접 작성했다(저작권 — 실 응답 원문 커밋 금지).

검증 대상:
  ① parse_bibliography_detail — 유사군 정렬·중복 제거 / subCode 폴백 / mainCode→int
     (비숫자 버림) / 비엔나 / mark_type 공백 정규화 / image_url path 우선
  ② 인증 파라미터 ServiceKey · URL 이 kipo-api 경로 · applicationNumber 하나만
  ③ resultCode != 00 이면 KiprisError
  ④ collect_pipeline: --enrich-biblio 없으면 서지상세 호출 0회, 있으면 레코드당
     1회 호출하고 similarity_codes 가 채워진다 / 보강 실패 시 레코드 생존 + '보강실패' 집계

실행 (project root 기준):
    ml\\venv\\Scripts\\python.exe -m pytest backend/tests/test_biblio_detail.py -q
"""

import json

import pytest

from backend.scripts import collect_pipeline as cp
from backend.src.core import kipris_client as kc


# --------------------------------------------------------------------
# 합성 서지상세 XML — 실측 경로 구조(중첩 Array)를 본뜬 임의 값.
#   유사군 similarCode 중복(G3404) + 정렬 안 됨 / mainCode 에 비숫자(A1) 혼입 /
#   trademarkDivisionCode 공백 다수 / sampleImageInfo path+smallPath 둘 다.
# --------------------------------------------------------------------
BIBLIO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode><resultMsg>success</resultMsg></header>
  <body>
    <item>
      <biblioSummaryInfoArray>
        <biblioSummaryInfo>
          <applicationNumber>4020210076341</applicationNumber>
          <registrationNumber>4098765430000</registrationNumber>
          <registerStatus>등록</registerStatus>
          <trademarkDivisionCode>국내상표   도형복합    일반상표</trademarkDivisionCode>
          <imageFlag>Y</imageFlag>
          <applicationDate>20210101</applicationDate>
          <registrationDate>20220301</registrationDate>
        </biblioSummaryInfo>
      </biblioSummaryInfoArray>
      <similarityCodeInfoArray>
        <similarityCodeInfo><similarCode>G3404</similarCode></similarityCodeInfo>
        <similarityCodeInfo><similarCode>G3402</similarCode></similarityCodeInfo>
        <similarityCodeInfo><similarCode>G3404</similarCode></similarityCodeInfo>
        <similarityCodeInfo><similarCode>G390701</similarCode></similarityCodeInfo>
      </similarityCodeInfoArray>
      <asignProductArray>
        <asignProduct><mainCode>25</mainCode><subCode>G3404</subCode><productName>신발</productName><seq>1</seq></asignProduct>
        <asignProduct><mainCode>09</mainCode><subCode>G3402</subCode><productName>안경</productName><seq>2</seq></asignProduct>
        <asignProduct><mainCode>25</mainCode><subCode>G390701</subCode><productName>모자</productName><seq>3</seq></asignProduct>
        <asignProduct><mainCode>A1</mainCode><subCode>G390702</subCode><productName>분류불가</productName><seq>4</seq></asignProduct>
      </asignProductArray>
      <viennaCodeInfoArray>
        <viennaCodeInfo><rowNumber>1</rowNumber><viennaCode>030102</viennaCode><viennaCodeDescription>고양이</viennaCodeDescription></viennaCodeInfo>
        <viennaCodeInfo><rowNumber>2</rowNumber><viennaCode>270501</viennaCode><viennaCodeDescription>문자</viennaCodeDescription></viennaCodeInfo>
      </viennaCodeInfoArray>
      <sampleImageInfoArray>
        <sampleImageInfo>
          <imageName>sample.jpg</imageName>
          <path>http://plus.kipris.or.kr/fileToss.jsp?arg=big</path>
          <smallPath>http://plus.kipris.or.kr/fileToss.jsp?arg=small</smallPath>
        </sampleImageInfo>
      </sampleImageInfoArray>
    </item>
  </body>
</response>
"""

# 유사군 배열이 아예 없는 응답 — 지정상품 subCode 폴백 검증용.
BIBLIO_NO_SIMILARITY_ARRAY = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode></header>
  <body><item>
    <asignProductArray>
      <asignProduct><mainCode>18</mainCode><subCode>G2701</subCode><productName>가방</productName></asignProduct>
      <asignProduct><mainCode>18</mainCode><subCode>G0201</subCode><productName>지갑</productName></asignProduct>
      <asignProduct><mainCode>18</mainCode><subCode>G2701</subCode><productName>핸드백</productName></asignProduct>
    </asignProductArray>
  </item></body>
</response>
"""

# path 없이 smallPath 만 있는 응답 — 이미지 폴백 검증용.
BIBLIO_SMALLPATH_ONLY = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode></header>
  <body><item>
    <sampleImageInfoArray>
      <sampleImageInfo><imageName>x.jpg</imageName><smallPath>http://only/small.jpg</smallPath></sampleImageInfo>
    </sampleImageInfoArray>
  </item></body>
</response>
"""

BIBLIO_ERROR = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>10</resultCode><resultMsg>INVALID_REQUEST_PARAMETER_ERROR</resultMsg></header>
  <body/>
</response>
"""


# ====================================================================
# ① parse_bibliography_detail
# ====================================================================

def test_parse_similarity_sorted_deduped():
    d = kc.parse_bibliography_detail(BIBLIO_XML)
    # 중복(G3404) 제거 + 정렬. 원본 순서(G3404,G3402,...)와 무관.
    assert d["similarity_codes"] == ["G3402", "G3404", "G390701"]


def test_parse_nice_classes_int_and_drops_non_numeric():
    d = kc.parse_bibliography_detail(BIBLIO_XML)
    # mainCode 25/09/25/A1 → 정렬·중복 제거·int, 비숫자 A1 버림.
    assert d["nice_classes"] == [9, 25]


def test_parse_vienna_and_goods():
    d = kc.parse_bibliography_detail(BIBLIO_XML)
    assert d["vienna_codes"] == ["030102", "270501"]
    # 지정상품 4건 전부, 류·유사군·상품명 매핑.
    assert len(d["goods"]) == 4
    assert d["goods"][0] == {"mainCode": "25", "subCode": "G3404", "productName": "신발"}


def test_parse_mark_type_whitespace_collapsed():
    d = kc.parse_bibliography_detail(BIBLIO_XML)
    # 연속 공백이 한 칸으로 정규화된다.
    assert d["mark_type"] == "국내상표 도형복합 일반상표"


def test_parse_summary_fields():
    d = kc.parse_bibliography_detail(BIBLIO_XML)
    assert d["register_status"] == "등록"
    assert d["registration_number"] == "4098765430000"
    assert d["application_number"] == "4020210076341"


def test_parse_image_url_prefers_path():
    d = kc.parse_bibliography_detail(BIBLIO_XML)
    assert d["image_url"] == "http://plus.kipris.or.kr/fileToss.jsp?arg=big"


def test_parse_image_url_falls_back_to_smallpath():
    d = kc.parse_bibliography_detail(BIBLIO_SMALLPATH_ONLY)
    assert d["image_url"] == "http://only/small.jpg"


def test_parse_similarity_falls_back_to_subcode():
    # similarityCodeInfoArray 가 없으면 지정상품 subCode 로 폴백(정렬·중복 제거).
    d = kc.parse_bibliography_detail(BIBLIO_NO_SIMILARITY_ARRAY)
    assert d["similarity_codes"] == ["G0201", "G2701"]
    assert d["nice_classes"] == [18]


def test_parse_raises_on_error_result_code():
    with pytest.raises(kc.KiprisError) as exc:
        kc.parse_bibliography_detail(BIBLIO_ERROR)
    assert exc.value.result_code == "10"


# ====================================================================
# ② 인증 파라미터 ServiceKey · kipo-api URL · applicationNumber 하나만
# ====================================================================

class _Resp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        pass


class _RecordingClient:
    def __init__(self, xml: str):
        self._xml = xml
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        return _Resp(self._xml)


class _NoLimiter:
    def acquire(self) -> None:
        pass


def _install_client(monkeypatch, xml: str) -> _RecordingClient:
    client = _RecordingClient(xml)
    monkeypatch.setattr(kc, "ACCESS_KEY", "TESTKEY")
    monkeypatch.setattr(kc, "_get_client", lambda: client)
    monkeypatch.setattr(kc, "limiter", _NoLimiter())
    return client


def test_bibliography_detail_raw_uses_servicekey_and_kipo_api_url(monkeypatch):
    client = _install_client(monkeypatch, BIBLIO_XML)
    kc.bibliography_detail_raw("4020210076341")
    call = client.calls[0]
    params = call["params"]

    # 인증 파라미터는 ServiceKey(getAdvancedSearch 계열), accessKey 아님.
    assert params["ServiceKey"] == "TESTKEY"
    assert "accessKey" not in params
    # 요청 파라미터는 applicationNumber 하나뿐(+ ServiceKey).
    assert set(params) == {"applicationNumber", "ServiceKey"}
    assert params["applicationNumber"] == "4020210076341"
    # URL 은 kipo-api/kipi 경로의 서지상세 오퍼레이션.
    assert call["url"] == kc.BIBLIO_DETAIL_URL
    assert "kipo-api/kipi" in call["url"]
    assert call["url"].endswith("getBibliographyDetailInfoSearch")


def test_bibliography_detail_end_to_end(monkeypatch):
    # raw → parse 조립 함수도 같은 결과를 준다.
    _install_client(monkeypatch, BIBLIO_XML)
    d = kc.bibliography_detail("4020210076341")
    assert d["similarity_codes"] == ["G3402", "G3404", "G390701"]


# ====================================================================
# ④ collect_pipeline 보강 — 옵트인 호출/집계/실패 생존
# ====================================================================

# 수집 대상 3건 (camelCase, 등록 + 비엔나 + 40.. 상표번호 + bigDrawing).
ADV_THREE = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode></header>
  <count><totalCount>3</totalCount></count>
  <body><items>
    <item><applicationNumber>4020210000001</applicationNumber><applicationStatus>등록</applicationStatus>
      <viennaCode>260101</viennaCode><classificationCode>09</classificationCode>
      <title>로고1</title><bigDrawing>http://plus.kipris.or.kr/fileToss.jsp?a=1</bigDrawing></item>
    <item><applicationNumber>4020210000002</applicationNumber><applicationStatus>등록</applicationStatus>
      <viennaCode>270501</viennaCode><classificationCode>09</classificationCode>
      <title>로고2</title><bigDrawing>http://plus.kipris.or.kr/fileToss.jsp?a=2</bigDrawing></item>
    <item><applicationNumber>4020210000003</applicationNumber><applicationStatus>등록</applicationStatus>
      <viennaCode>260101</viennaCode><classificationCode>09</classificationCode>
      <title>로고3</title><bigDrawing>http://plus.kipris.or.kr/fileToss.jsp?a=3</bigDrawing></item>
  </items></body>
</response>
"""


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """실 DB/이미지/네트워크/체크포인트를 원천 차단하는 격리 샌드박스
    (test_collect_pipeline.sandbox 와 동일 관례)."""
    images = tmp_path / "images"
    images.mkdir()
    monkeypatch.setattr(cp, "CHECKPOINT_PATH", tmp_path / "collect_checkpoint.json")
    monkeypatch.setattr(cp, "COLLECT_RAW_XML_DIR", tmp_path / "raw" / "xml")
    monkeypatch.setattr(cp.paths, "IMAGES_DIR", images)
    monkeypatch.setattr(cp, "load_db_app_numbers", lambda url: set())
    monkeypatch.setattr(cp, "rebuild_index", lambda: None)

    captured = {"rows": []}

    def fake_upsert(rows, database_url):
        assert "fake" in database_url
        captured["rows"].extend(rows)

    monkeypatch.setattr(cp, "upsert_rows", fake_upsert)
    monkeypatch.setattr(cp.config, "DATABASE_URL", "postgresql://fake/marklens")
    # 이미지 다운로드는 tmp 에 더미 PNG 로 대체(네트워크 0).
    def _dl(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\x89PNG\r\n\x1a\n(fake)")
        return dest
    monkeypatch.setattr(kc, "download_file_now", _dl)
    monkeypatch.setattr(kc, "advanced_search_raw", lambda name, **_: ADV_THREE)
    return {"images": images, "captured": captured}


def test_no_enrich_makes_zero_biblio_calls(sandbox, monkeypatch, capsys):
    # --enrich-biblio 없으면 서지상세를 호출하지 않고 유사군은 빈 배열로 적재된다.
    biblio_calls: list[str] = []
    monkeypatch.setattr(kc, "bibliography_detail_raw",
                        lambda app_no: (biblio_calls.append(app_no), BIBLIO_XML)[1])
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자", "--skip-index"])

    assert cp.main() == 0
    out = capsys.readouterr().out
    assert len(biblio_calls) == 0                       # ← 핵심: 보강 호출 0
    assert "'수집': 3" in out
    assert "'보강': 0" in out
    # 유사군(row[12])은 전부 빈 배열.
    rows = sandbox["captured"]["rows"]
    assert len(rows) == 3
    assert all(r[12] == [] for r in rows)


def test_enrich_calls_once_per_record_and_fills_similarity(sandbox, monkeypatch, capsys):
    # --enrich-biblio 켜면 레코드당 1회 호출하고 similarity_codes 가 채워진다.
    biblio_calls: list[str] = []
    monkeypatch.setattr(kc, "bibliography_detail_raw",
                        lambda app_no: (biblio_calls.append(app_no), BIBLIO_XML)[1])
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자",
                         "--skip-index", "--enrich-biblio"])

    assert cp.main() == 0
    out = capsys.readouterr().out
    # 레코드당 정확히 1회 (수집 3건 = 서지상세 3회).
    assert biblio_calls == ["4020210000001", "4020210000002", "4020210000003"]
    assert "'수집': 3" in out
    assert "'보강': 3" in out
    assert "'보강실패': 0" in out
    # 유사군(row[12])이 서지상세 값으로 채워진다.
    rows = sandbox["captured"]["rows"]
    assert all(r[12] == ["G3402", "G3404", "G390701"] for r in rows)
    # 원본 XML 도 파싱 전 선저장(라벨에 출원번호 포함, DoD Ⓐ).
    saved = [p.name for p in cp.COLLECT_RAW_XML_DIR.glob("biblio_*.xml")]
    assert len(saved) == 3


def test_enrich_failure_keeps_record_and_counts(sandbox, monkeypatch, capsys):
    # 보강 실패(KiprisError)해도 레코드는 살아남고 '보강실패'로 집계, 유사군은 빈 배열.
    def boom(app_no):
        raise kc.KiprisError("서지상세 오류", result_code="10")

    monkeypatch.setattr(kc, "bibliography_detail_raw", boom)
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자",
                         "--skip-index", "--enrich-biblio"])

    assert cp.main() == 0                               # 레코드가 죽지 않아 정상 종료
    captured_io = capsys.readouterr()
    out, err = captured_io.out, captured_io.err
    assert "'수집': 3" in out                           # 3건 모두 생존
    assert "'보강실패': 3" in out
    assert "'보강': 0" in out
    # 보강 실패분은 유사군 빈 배열로 진행.
    rows = sandbox["captured"]["rows"]
    assert len(rows) == 3
    assert all(r[12] == [] for r in rows)
    assert "유사군 보강 실패" in err


def test_enrich_checkpoint_records_survive(sandbox, monkeypatch):
    # 보강까지 성공한 레코드는 체크포인트에 기록된다(중복 보강 방지).
    monkeypatch.setattr(kc, "bibliography_detail_raw", lambda app_no: BIBLIO_XML)
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자",
                         "--skip-index", "--enrich-biblio"])
    assert cp.main() == 0
    ckpt = json.loads(cp.CHECKPOINT_PATH.read_text(encoding="utf-8"))
    assert ckpt["collected"] == ["4020210000001", "4020210000002", "4020210000003"]
