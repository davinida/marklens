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

import json

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


def _isolate_data(tmp_path, monkeypatch):
    """원본 선저장·이미지 경로를 tmp 로 돌린다 — 실 ml/data 오염 및 의존 방지.

    - 원본 XML: dry-run 도 검색 응답 원본을 저장하므로(쿼터를 태우는 호출이라)
      배치 경로를 타는 테스트에는 반드시 이 격리가 필요하다.
    - 이미지 디렉터리: 기수집 skip 판정이 storage.image_exists 를 보므로, 실
      ml/data/images 에 같은 출원번호 PNG 가 있으면 결과가 달라진다(과거 더미
      데이터가 실제로 그랬다). 판정을 로컬 데이터와 무관하게 고정한다.
    """
    monkeypatch.setattr(cp, "COLLECT_RAW_XML_DIR", tmp_path / "raw" / "xml")
    images = tmp_path / "images"
    images.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cp.paths, "IMAGES_DIR", images)  # storage 심이 같은 모듈 참조


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


def test_main_dry_run_applicant_batch(tmp_path, monkeypatch, capsys):
    # --applicant 배치 경로: advanced_search_raw 를 monkeypatch 해 네트워크 없이 흐름 검증
    _no_db(monkeypatch)
    _isolate_data(tmp_path, monkeypatch)
    monkeypatch.setattr(kc, "advanced_search_raw", lambda name, **_: XML_APPLICANT)
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자", "--dry-run"])
    rc = cp.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "'수집': 2" in out
    # dry-run 도 쿼터를 태우는 호출이므로 응답 원본이 남아야 한다 (DoD Ⓐ)
    assert len(list(cp.COLLECT_RAW_XML_DIR.glob("*.xml"))) == 1


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


def test_main_limit_caps_per_applicant(tmp_path, monkeypatch, capsys):
    # --limit 은 출원인당 수집 상한 (호출 예산 관리)
    _no_db(monkeypatch)
    _isolate_data(tmp_path, monkeypatch)
    monkeypatch.setattr(kc, "advanced_search_raw", lambda name, **_: XML_APPLICANT)
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자",
                         "--limit", "1", "--dry-run"])
    rc = cp.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "'수집': 1" in out  # 2건 대상이지만 limit=1 로 1건만


# ====================================================================
# 백엔드-6 감사보고서 DoD — 원본 선저장 / 기수집 skip / 레코드별 체크포인트
#
# 전부 오프라인. KIPRIS 실호출 0회(advanced_search_raw/download_file_now 를
# 전부 mock), 실 DB 쓰기 0회(upsert_rows·load_db_app_numbers 를 mock + 경로를
# tmp 로 격리)를 코드로 강제한다. 실 ml/data/images(100장)·실 체크포인트에 손대지 않는다.
# ====================================================================

# 수집 대상 3건 (등록 + ViennaCode + 40.. 상표번호 + ImagePath) — skip/체크포인트용.
XML_THREE = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>00</resultCode></header>
  <body><items>
    <item><Title>로고1</Title><ApplicationStatus>등록</ApplicationStatus>
      <ApplicationNumber>40-2021-0000001</ApplicationNumber>
      <ViennaCode>260101</ViennaCode><GoodClassificationCode>09</GoodClassificationCode>
      <ImagePath>http://plus.kipris.or.kr/fileToss.jsp?a=1</ImagePath></item>
    <item><Title>로고2</Title><ApplicationStatus>등록</ApplicationStatus>
      <ApplicationNumber>40-2021-0000002</ApplicationNumber>
      <ViennaCode>270501</ViennaCode><GoodClassificationCode>09</GoodClassificationCode>
      <ImagePath>http://plus.kipris.or.kr/fileToss.jsp?a=2</ImagePath></item>
    <item><Title>로고3</Title><ApplicationStatus>등록</ApplicationStatus>
      <ApplicationNumber>40-2021-0000003</ApplicationNumber>
      <ViennaCode>260101</ViennaCode><GoodClassificationCode>09</GoodClassificationCode>
      <ImagePath>http://plus.kipris.or.kr/fileToss.jsp?a=3</ImagePath></item>
  </items></body>
</response>
"""


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """실 DB/이미지/네트워크/체크포인트를 원천 차단하는 격리 샌드박스.

    - 체크포인트·원본 XML·이미지 경로를 tmp 로 리디렉트(실 ml/data 미오염)
    - upsert_rows / load_db_app_numbers 를 mock → 실 DB 접촉 0
    - rebuild_index no-op → 무거운 subprocess 미기동
    - config.DATABASE_URL 은 가짜(비어있지 않아야 실 수집 경로 진입) — 단, 실 접속 없음
    """
    images = tmp_path / "images"
    images.mkdir()
    monkeypatch.setattr(cp, "CHECKPOINT_PATH", tmp_path / "collect_checkpoint.json")
    monkeypatch.setattr(cp, "COLLECT_RAW_XML_DIR", tmp_path / "raw" / "xml")
    monkeypatch.setattr(cp.paths, "IMAGES_DIR", images)  # storage 심이 같은 paths 모듈 참조
    monkeypatch.setattr(cp, "load_db_app_numbers", lambda url: set())
    monkeypatch.setattr(cp, "rebuild_index", lambda: None)

    captured = {"rows": []}

    def fake_upsert(rows, database_url):
        assert "fake" in database_url  # 실 DATABASE_URL 이 새어들지 않았는지 방어
        captured["rows"].extend(rows)

    monkeypatch.setattr(cp, "upsert_rows", fake_upsert)
    monkeypatch.setattr(cp.config, "DATABASE_URL", "postgresql://fake/marklens")
    return {"images": images, "captured": captured}


def _counting_download(calls, *, raise_on=None):
    """실 다운로드 대체 mock — 호출을 세고 tmp 에 더미 PNG 를 쓴다.
    raise_on(1-기반)번째 호출에서 KeyboardInterrupt 를 던져 사용자 중단을 시뮬레이션."""
    def _dl(url, dest):
        calls.append(url)
        if raise_on is not None and len(calls) == raise_on:
            raise KeyboardInterrupt("사용자 중단 시뮬레이션")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\x89PNG\r\n\x1a\n(fake)")
        return dest
    return _dl


def test_rerun_skips_collected_zero_download_calls(sandbox, monkeypatch, capsys):
    # ② 재실행 시 기수집 출원번호를 건너뛰고 재다운로드 HTTP 호출이 0 인지.
    search_calls, dl_calls = [], []
    monkeypatch.setattr(kc, "advanced_search_raw",
                        lambda name, **_: (search_calls.append(name), XML_THREE)[1])
    monkeypatch.setattr(kc, "download_file_now", _counting_download(dl_calls))
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자", "--skip-index"])

    # 1차: 3건 다운로드·적재
    assert cp.main() == 0
    assert len(dl_calls) == 3
    assert len(sandbox["captured"]["rows"]) == 3
    # 체크포인트 파일에 3건 영속 기록 (레코드별 체크포인트)
    ckpt = json.loads(cp.CHECKPOINT_PATH.read_text(encoding="utf-8"))
    assert ckpt["collected"] == ["4020210000001", "4020210000002", "4020210000003"]

    # 2차: 전부 기수집 → 다운로드 HTTP 0회
    dl_calls.clear()
    sandbox["captured"]["rows"].clear()
    n_search_before = len(search_calls)
    assert cp.main() == 0
    out = capsys.readouterr().out
    assert len(dl_calls) == 0                       # ← 핵심: 재다운로드 0
    assert sandbox["captured"]["rows"] == []        # DB UPSERT 도 0건
    assert "'건너뜀_기수집': 3" in out
    assert "'수집': 0" in out
    # 검색은 출원인당 1회 상각 호출(신규 등록 발견용)이라 재실행에도 정상 수행
    assert len(search_calls) == n_search_before + 1


def test_checkpoint_resume_after_interrupt(sandbox, monkeypatch, capsys):
    # ① 중단→재개: 3건 중 2건 처리 후 중단(KeyboardInterrupt), 재실행 시 3번째만 처리.
    monkeypatch.setattr(kc, "advanced_search_raw", lambda name, **_: XML_THREE)
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자", "--skip-index"])

    # 1차: 3번째 다운로드에서 중단 → 예외 전파(이어받기용 체크포인트만 남는다)
    run1 = []
    monkeypatch.setattr(kc, "download_file_now", _counting_download(run1, raise_on=3))
    with pytest.raises(KeyboardInterrupt):
        cp.main()
    ckpt = json.loads(cp.CHECKPOINT_PATH.read_text(encoding="utf-8"))
    assert ckpt["collected"] == ["4020210000001", "4020210000002"]  # 2건만 체크포인트
    assert sorted(p.name for p in sandbox["images"].glob("*.png")) == [
        "4020210000001.png", "4020210000002.png"]                    # 3번째 이미지 없음

    # 2차: 앞 2건은 skip, 3번째만 다운로드
    run2 = []
    monkeypatch.setattr(kc, "download_file_now", _counting_download(run2))
    assert cp.main() == 0
    out = capsys.readouterr().out
    assert run2 == ["http://plus.kipris.or.kr/fileToss.jsp?a=3"]     # 3번째만 호출
    assert "'수집': 1" in out
    assert "'건너뜀_기수집': 2" in out
    ckpt = json.loads(cp.CHECKPOINT_PATH.read_text(encoding="utf-8"))
    assert ckpt["collected"] == ["4020210000001", "4020210000002", "4020210000003"]


def test_raw_xml_saved_before_parse_survives_parse_error(sandbox, monkeypatch):
    # Ⓐ 원본 선저장: 파싱이 터져도 응답 XML 원본은 디스크에 남아야 한다(파싱 전 저장).
    monkeypatch.setattr(kc, "advanced_search_raw", lambda name, **_: XML_THREE)

    def boom_parse(xml_text):
        raise ValueError("parse boom")

    monkeypatch.setattr(kc, "parse_items", boom_parse)

    with pytest.raises(ValueError):
        cp.search_batch("삼성전자")

    saved = list(cp.COLLECT_RAW_XML_DIR.glob("*.xml"))
    assert len(saved) == 1                                  # 파싱 전에 이미 저장됨
    assert saved[0].read_text(encoding="utf-8") == XML_THREE


def test_image_saved_before_rowparse_survives_error(sandbox, monkeypatch, capsys):
    # ③ 원본 선저장(이미지): 행 변환(파싱)이 터져도 다운로드된 원본 이미지는 보존된다.
    monkeypatch.setattr(kc, "advanced_search_raw", lambda name, **_: XML_THREE)
    monkeypatch.setattr(kc, "download_file_now", _counting_download([]))

    def boom_row(item):
        raise ValueError("row boom")

    monkeypatch.setattr(cp, "item_to_row", boom_row)
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자", "--skip-index"])

    rc = cp.main()
    # 3건 모두 이미지 원본은 디스크에 남았지만(선저장), 행 변환 실패로 수집 0
    assert sorted(p.name for p in sandbox["images"].glob("*.png")) == [
        "4020210000001.png", "4020210000002.png", "4020210000003.png"]
    assert sandbox["captured"]["rows"] == []                 # DB 적재 0
    assert rc == 2                                           # 수집 0 → 필터/포맷 실패 신호
    err = capsys.readouterr().err
    assert "레코드 변환 실패" in err
    # 실패해도 체크포인트에는 기록하지 않는다(수정 후 --force 재처리 여지)
    assert not cp.CHECKPOINT_PATH.exists()


def test_force_reprocesses_already_collected(sandbox, monkeypatch):
    # --force: 기수집 skip 을 무시하고 재수집(재보정·재수집 시나리오).
    monkeypatch.setattr(kc, "advanced_search_raw", lambda name, **_: XML_THREE)
    dl = []
    monkeypatch.setattr(kc, "download_file_now", _counting_download(dl))

    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자", "--skip-index"])
    assert cp.main() == 0
    assert len(dl) == 3

    dl.clear()
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자", "--skip-index", "--force"])
    assert cp.main() == 0
    assert len(dl) == 3          # --force 로 기수집분도 다시 다운로드
