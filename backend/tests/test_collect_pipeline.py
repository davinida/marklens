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
import os
import subprocess

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


def _advanced_page(total: int, app_numbers: list[str]) -> str:
    rows = "".join(
        f"<item><applicationNumber>{app_no}</applicationNumber>"
        "<applicationStatus>등록</applicationStatus>"
        "<viennaCode>260101</viennaCode><classificationCode>09</classificationCode>"
        f"<title>logo-{app_no}</title>"
        f"<bigDrawing>https://plus.kipris.or.kr/image/{app_no}.png</bigDrawing>"
        "</item>"
        for app_no in app_numbers
    )
    return (
        "<response><header><resultCode>00</resultCode></header>"
        f"<count><totalCount>{total}</totalCount></count>"
        f"<body><items>{rows}</items></body></response>"
    )


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


def test_main_limit_stops_before_fetching_next_page(tmp_path, monkeypatch):
    _no_db(monkeypatch)
    _isolate_data(tmp_path, monkeypatch)
    monkeypatch.setattr(kc, "ADVANCED_DEFAULT_ROWS", 2)
    calls = []
    pages = {
        1: _advanced_page(4, ["4020210000001", "4020210000002"]),
        2: _advanced_page(4, ["4020210000003", "4020210000004"]),
    }

    def fake_raw(_name, *, page_no=1, **_kwargs):
        calls.append(page_no)
        return pages[page_no]

    monkeypatch.setattr(kc, "advanced_search_raw", fake_raw)
    monkeypatch.setattr(
        cp.sys,
        "argv",
        ["collect_pipeline", "--applicant", "삼성전자", "--limit", "1", "--dry-run"],
    )

    assert cp.main() == 0
    assert calls == [1]


def test_plan_is_offline_and_reports_budget(tmp_path, monkeypatch, capsys):
    data_dir = tmp_path / "data"
    stage = data_dir / "staging" / "bbq_29_43.json"
    monkeypatch.setattr(cp.paths, "ML_DATA_DIR", data_dir)
    monkeypatch.setattr(cp.config, "DATABASE_URL", "")
    monkeypatch.setattr(kc, "ACCESS_KEY", "configured-secret")
    monkeypatch.setattr(kc.limiter, "used_this_month", lambda: 4)
    monkeypatch.setattr(
        kc,
        "advanced_search_raw",
        lambda *_args, **_kwargs: pytest.fail("--plan must not call KIPRIS"),
    )
    monkeypatch.setattr(
        cp.sys,
        "argv",
        [
            "collect_pipeline",
            "--applicant",
            "주식회사 제너시스비비큐",
            "--plan",
            "--limit",
            "50",
            "--max-pages-per-source",
            "1",
            "--nice-class",
            "29",
            "--nice-class",
            "43",
            "--file-staging",
            str(stage),
        ],
    )

    assert cp.main() == 0
    output = capsys.readouterr().out
    plan = json.loads(output.removeprefix("[계획] "))
    assert plan["network_calls_executed"] == 0
    assert plan["target_nice_classes"] == [29, 43]
    assert plan["nice_filter_scope"] == "client-side-after-search"
    assert plan["estimated_calls"]["search_min"] == 1
    assert plan["estimated_calls"]["search_hard_max"] == 2
    assert plan["max_pages_per_source"] == 1
    assert plan["rows_per_page"] == 100
    assert plan["search_retries_per_page"] == 1
    assert plan["search_attempts_per_page_hard_max"] == 2
    assert plan["search_timeout_seconds"] == 30.0
    assert plan["quota"]["used"] == 4
    assert plan["quota"]["remaining"] == 946
    assert plan["environment"]["storage_target"] == "file-staging"
    assert plan["ready_for_collection"] is True
    assert not stage.exists()


def test_nice_class_filter_and_distribution_are_reported(
    tmp_path, monkeypatch, capsys
):
    _no_db(monkeypatch)
    xml_file = tmp_path / "mock.xml"
    xml_file.write_text(XML_APPLICANT, encoding="utf-8")
    monkeypatch.setattr(
        cp.sys,
        "argv",
        [
            "collect_pipeline",
            "--mock-xml",
            str(xml_file),
            "--dry-run",
            "--nice-class",
            "35",
        ],
    )

    assert cp.main() == 0
    output = capsys.readouterr().out
    assert "'수집': 1" in output
    assert "'제외_대상류아님': 1" in output
    assert "'류별_수집': {'9': 1, '35': 1}" in output


def test_max_pages_per_source_is_a_hard_call_cap(tmp_path, monkeypatch):
    _no_db(monkeypatch)
    _isolate_data(tmp_path, monkeypatch)
    monkeypatch.setattr(kc, "ADVANCED_DEFAULT_ROWS", 2)
    calls = []

    def fake_raw(_name, *, page_no=1, **_kwargs):
        calls.append(page_no)
        return _advanced_page(50, ["4020210000001", "4020210000002"])

    monkeypatch.setattr(kc, "advanced_search_raw", fake_raw)
    monkeypatch.setattr(
        cp.sys,
        "argv",
        [
            "collect_pipeline",
            "--applicant",
            "주식회사 제너시스비비큐",
            "--dry-run",
            "--max-pages-per-source",
            "1",
        ],
    )

    assert cp.main() == 0
    assert calls == [1]


def test_search_page_retries_once_then_succeeds(tmp_path, monkeypatch, capsys):
    _isolate_data(tmp_path, monkeypatch)
    calls = []
    sleeps = []

    def flaky_raw(_name, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise kc.KiprisNetworkError("timeout")
        return _advanced_page(1, ["4020210000001"])

    monkeypatch.setattr(kc, "advanced_search_raw", flaky_raw)
    monkeypatch.setattr(cp.time, "sleep", sleeps.append)

    results = list(
        cp.iter_search_pages(
            "삼성전자",
            max_pages=1,
            rows_per_page=100,
            max_retries=1,
            retry_backoff_seconds=2,
            request_timeout_seconds=30,
        )
    )

    assert len(results) == 1
    assert isinstance(results[0], cp.SearchPage)
    assert [call["num_of_rows"] for call in calls] == [100, 100]
    assert [call["request_timeout"] for call in calls] == [30, 30]
    assert sleeps == [2]
    assert "재시도 1/1" in capsys.readouterr().err


def test_search_failure_skips_only_source_and_preserves_cursor(
    sandbox, monkeypatch, capsys
):
    cp.update_checkpoint(
        [],
        source="실패 출원인",
        cursor=(2, 7),
        rows_per_page=100,
        path=cp.CHECKPOINT_PATH,
    )
    calls = []

    def source_raw(source, **_kwargs):
        calls.append(source)
        if source == "실패 출원인":
            raise kc.KiprisNetworkError("timeout")
        return _advanced_page(1, ["4020210000001"])

    monkeypatch.setattr(kc, "advanced_search_raw", source_raw)
    monkeypatch.setattr(kc, "download_file_now", _counting_download([]))
    monkeypatch.setattr(cp.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        cp.sys,
        "argv",
        [
            "collect_pipeline",
            "--applicant",
            "실패 출원인",
            "--applicant",
            "성공 출원인",
            "--rows-per-page",
            "100",
            "--search-retries",
            "1",
            "--retry-backoff-seconds",
            "0",
            "--skip-index",
        ],
    )

    assert cp.main() == 4
    assert calls == ["실패 출원인", "실패 출원인", "성공 출원인"]
    assert [row[0] for row in sandbox["captured"]["rows"]] == ["4020210000001"]
    assert cp.load_cursor(
        "실패 출원인",
        cp.CHECKPOINT_PATH,
        rows_per_page=100,
    ) == (2, 7)
    captured = capsys.readouterr()
    assert "이 출원인만 건너뜁니다" in captured.err
    assert "'검색실패_출원인': 1" in captured.out


def test_checkpoint_page_size_change_restarts_source_without_mutating_file(
    tmp_path, capsys
):
    checkpoint = tmp_path / "checkpoint.json"
    cp.update_checkpoint(
        ["4020210000001"],
        source="삼성전자",
        cursor=(3, 17),
        rows_per_page=500,
        path=checkpoint,
    )
    before = checkpoint.read_bytes()

    assert cp.load_cursor("삼성전자", checkpoint, rows_per_page=500) == (3, 17)
    assert cp.load_cursor("삼성전자", checkpoint, rows_per_page=100) == (1, 0)
    assert checkpoint.read_bytes() == before
    assert "1페이지부터 다시 확인" in capsys.readouterr().err


def test_help_is_encodable_on_windows_cp949():
    env = {**os.environ, "PYTHONIOENCODING": "cp949"}
    result = subprocess.run(
        [
            cp.sys.executable,
            "-m",
            "backend.scripts.collect_pipeline",
            "--help",
        ],
        cwd=cp.PROJECT_ROOT,
        env=env,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("cp949", errors="replace")
    assert "--file-staging" in result.stdout.decode("cp949")
    assert "--target-total" in result.stdout.decode("cp949")


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
    monkeypatch.setattr(cp, "INDEX_DIRTY_PATH", tmp_path / "index" / ".dirty")
    monkeypatch.setattr(
        cp,
        "AUTHORITATIVE_KEYS_PATH",
        tmp_path / "index" / "authoritative_keys.json",
    )
    monkeypatch.setattr(cp.paths, "IMAGES_DIR", images)  # storage 심이 같은 paths 모듈 참조
    monkeypatch.setattr(cp, "load_db_app_numbers", lambda url: set())
    monkeypatch.setattr(cp, "rebuild_index", lambda: None)

    captured = {"rows": []}

    def fake_upsert(rows, database_url):
        assert "fake" in database_url  # 실 DATABASE_URL 이 새어들지 않았는지 방어
        captured["rows"].extend(rows)

    monkeypatch.setattr(cp, "upsert_rows", fake_upsert)
    # upsert 성공 후 자동 실행되는 dataset_info 갱신도 실 DB 접촉 없이 차단
    monkeypatch.setattr(
        cp,
        "refresh_dataset_info",
        lambda url: {"총_상표수": 0, "출원일자_범위": "", "데이터_기준": "", "생성일자": ""},
    )
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


def test_target_total_db_caps_distinct_new_records_before_next_source(
    sandbox, monkeypatch, capsys
):
    """DB 기존 건수와 신규 출원번호 합계가 목표를 넘지 않아야 한다."""
    existing = {
        "4020190000001",
        "4020190000002",
        "4020190000003",
    }
    calls = []
    page_with_duplicate = _advanced_page(
        3,
        ["4020210000001", "4020210000001", "4020210000002"],
    )

    monkeypatch.setattr(cp, "load_db_app_numbers", lambda _url: existing)
    monkeypatch.setattr(kc.limiter, "used_this_month", lambda: 0)
    monkeypatch.setattr(
        kc,
        "advanced_search_raw",
        lambda source, **_kwargs: (calls.append(source), page_with_duplicate)[1],
    )
    monkeypatch.setattr(kc, "download_file_now", _counting_download([]))
    monkeypatch.setattr(
        cp.sys,
        "argv",
        [
            "collect_pipeline",
            "--applicant",
            "첫번째",
            "--applicant",
            "두번째",
            "--target-total",
            "5",
            "--skip-index",
        ],
    )

    assert cp.main() == 0
    output = capsys.readouterr().out
    assert calls == ["첫번째"], "목표 도달 뒤 다음 출원인 검색을 호출하면 안 된다"
    assert [row[0] for row in sandbox["captured"]["rows"]] == [
        "4020210000001",
        "4020210000002",
    ]
    assert "'기존총계': 3" in output
    assert "'최종총계': 5" in output
    assert "'목표도달': True" in output


def test_target_total_db_already_met_skips_all_kipris_calls(
    sandbox, monkeypatch, capsys
):
    monkeypatch.setattr(
        cp,
        "load_db_app_numbers",
        lambda _url: {f"402019{index:07d}" for index in range(5)},
    )
    monkeypatch.setattr(
        kc.limiter,
        "used_this_month",
        lambda: pytest.fail("목표 달성 시 쿼터 조회도 필요하지 않다"),
    )
    monkeypatch.setattr(
        kc,
        "advanced_search_raw",
        lambda *_args, **_kwargs: pytest.fail("목표 달성 시 KIPRIS 호출 금지"),
    )
    monkeypatch.setattr(
        cp.sys,
        "argv",
        [
            "collect_pipeline",
            "--applicant",
            "호출금지",
            "--target-total",
            "5",
            "--skip-index",
        ],
    )

    assert cp.main() == 0
    output = capsys.readouterr().out
    assert "검색 호출을 생략합니다" in output
    assert sandbox["captured"]["rows"] == []
    assert "'최종총계': 5" in output


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
    #    중단되어도 죽지 않고 그때까지의 행을 적재한 뒤 rc=3 으로 끝낸다(체크포인트=적재분).
    monkeypatch.setattr(kc, "advanced_search_raw", lambda name, **_: XML_THREE)
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자", "--skip-index"])

    # 1차: 3번째 다운로드에서 중단
    run1 = []
    monkeypatch.setattr(kc, "download_file_now", _counting_download(run1, raise_on=3))
    assert cp.main() == 3  # 중단 종료 코드 — 조용히 성공하지 않는다
    ckpt = json.loads(cp.CHECKPOINT_PATH.read_text(encoding="utf-8"))
    assert ckpt["collected"] == ["4020210000001", "4020210000002"]  # 적재된 2건만 체크포인트
    assert ckpt["cursors"]["삼성전자"] == {
        "page": 1,
        "offset": 2,
        "rows_per_page": 100,
    }
    assert sorted(p.name for p in sandbox["images"].glob("*.png")) == [
        "4020210000001.png", "4020210000002.png"]                    # 3번째 이미지 없음
    assert len(sandbox["captured"]["rows"]) == 2, "중단 전 확보한 행은 반드시 적재돼야 한다"

    # 2차: 영속 offset 커서가 앞 2건을 다시 처리하지 않고 3번째에서 재개
    run2 = []
    monkeypatch.setattr(kc, "download_file_now", _counting_download(run2))
    assert cp.main() == 0
    out = capsys.readouterr().out
    assert run2 == ["http://plus.kipris.or.kr/fileToss.jsp?a=3"]     # 3번째만 호출
    assert "'수집': 1" in out
    assert "'건너뜀_기수집': 0" in out
    ckpt = json.loads(cp.CHECKPOINT_PATH.read_text(encoding="utf-8"))
    assert ckpt["collected"] == ["4020210000001", "4020210000002", "4020210000003"]
    assert "삼성전자" not in ckpt["cursors"]


def test_checkpoint_never_written_when_upsert_fails(sandbox, monkeypatch):
    """체크포인트는 **UPSERT 성공 후에만** 쓴다.

    회귀 방지(2026-07-10 실측 결함): 적재 전에 체크포인트를 쓰면, 적재가 실패한 레코드를
    재실행이 '이미 수집됨'으로 skip 해 **영원히 DB에 들어가지 않는다.**
    """
    monkeypatch.setattr(kc, "advanced_search_raw", lambda name, **_: XML_THREE)
    monkeypatch.setattr(kc, "download_file_now", _counting_download([]))

    def boom_upsert(rows, database_url):
        raise RuntimeError("DB 다운")

    monkeypatch.setattr(cp, "upsert_rows", boom_upsert)
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자", "--skip-index"])

    with pytest.raises(RuntimeError):
        cp.main()
    assert not cp.CHECKPOINT_PATH.exists(), "적재 실패 시 체크포인트를 남기면 안 된다"


def test_existing_image_is_reused_not_skipped(sandbox, monkeypatch, capsys):
    """이미지만 있고 DB/체크포인트에 없는 레코드는 **skip 하지 않고 적재**한다.

    이미지는 적재보다 먼저 저장되므로 '이미지 있음'이 '적재됨'을 뜻하지 않는다.
    다만 만료된 일회성 링크를 다시 부르지 않도록 다운로드는 건너뛴다.
    """
    (sandbox["images"] / "4020210000001.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(kc, "advanced_search_raw", lambda name, **_: XML_THREE)
    dl = []
    monkeypatch.setattr(kc, "download_file_now", _counting_download(dl))
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--applicant", "삼성전자", "--skip-index"])

    assert cp.main() == 0
    out = capsys.readouterr().out
    assert "'수집': 3" in out                      # 3건 모두 적재 (skip 아님)
    assert "'이미지_재사용': 1" in out
    assert len(dl) == 2, "이미 있는 이미지는 다시 받지 않는다"
    rows = sandbox["captured"]["rows"]
    assert sorted(r[0] for r in rows) == [
        "4020210000001", "4020210000002", "4020210000003"]


def test_mock_xml_rejects_enrich_biblio(tmp_path, monkeypatch):
    """--mock-xml(오프라인 개발)과 --enrich-biblio(실 API)를 함께 쓰면 즉시 거부한다.

    허용하면 오프라인인 줄 알고 돌리다 월 예산을 태운다.
    """
    xml_file = tmp_path / "m.xml"
    xml_file.write_text(XML_THREE, encoding="utf-8")
    monkeypatch.setattr(cp.sys, "argv",
                        ["collect_pipeline", "--mock-xml", str(xml_file), "--enrich-biblio"])
    with pytest.raises(SystemExit):
        cp.main()


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


def test_two_search_pages_are_upserted_page_by_page(sandbox, monkeypatch):
    monkeypatch.setattr(kc, "ADVANCED_DEFAULT_ROWS", 2)
    pages = {
        1: _advanced_page(3, ["4020210000001", "4020210000002"]),
        2: _advanced_page(3, ["4020210000003"]),
    }
    calls = []

    def fake_raw(_name, *, page_no=1, **_kwargs):
        return pages[page_no]

    def fake_upsert(rows, _database_url):
        calls.append([row[0] for row in rows])

    monkeypatch.setattr(kc, "advanced_search_raw", fake_raw)
    monkeypatch.setattr(kc, "download_file_now", _counting_download([]))
    monkeypatch.setattr(cp, "upsert_rows", fake_upsert)
    monkeypatch.setattr(
        cp.sys,
        "argv",
        ["collect_pipeline", "--applicant", "삼성전자", "--skip-index"],
    )

    assert cp.main() == 0
    assert calls == [
        ["4020210000001", "4020210000002"],
        ["4020210000003"],
    ]
    assert len(list(cp.COLLECT_RAW_XML_DIR.glob("*.xml"))) == 2


def test_iter_search_pages_stops_on_repeated_page(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "COLLECT_RAW_XML_DIR", tmp_path / "raw")
    monkeypatch.setattr(kc, "ADVANCED_DEFAULT_ROWS", 2)
    repeated = _advanced_page(99, ["4020210000001", "4020210000002"])
    calls = []

    def fake_raw(_name, *, page_no=1, **_kwargs):
        calls.append(page_no)
        return repeated

    monkeypatch.setattr(kc, "advanced_search_raw", fake_raw)

    pages = list(cp.iter_search_pages("삼성전자"))
    assert [page.page_no for page in pages] == [1]
    assert calls == [1, 2]


def test_dirty_index_recovery_exports_db_keys_and_clears_marker(
    sandbox, monkeypatch, tmp_path
):
    xml_file = tmp_path / "all_rejected.xml"
    xml_file.write_text(
        "<response><header><resultCode>00</resultCode></header><body><items>"
        "<item><ApplicationStatus>거절</ApplicationStatus>"
        "<ApplicationNumber>4020210000009</ApplicationNumber>"
        "<ViennaCode>260101</ViennaCode></item>"
        "</items></body></response>",
        encoding="utf-8",
    )
    cp.mark_index_dirty()
    rebuilt = []
    monkeypatch.setattr(cp, "load_db_image_keys", lambda _url: {"a/one.png"})
    monkeypatch.setattr(cp, "rebuild_index", lambda: rebuilt.append(True))
    monkeypatch.setattr(
        cp.sys,
        "argv",
        ["collect_pipeline", "--mock-xml", str(xml_file)],
    )

    assert cp.main() == 2
    assert rebuilt == [True]
    assert not cp.INDEX_DIRTY_PATH.exists()
    manifest = json.loads(cp.AUTHORITATIVE_KEYS_PATH.read_text(encoding="utf-8"))
    assert manifest == {
        "schema_version": 1,
        "source": "database.image_key",
        "image_keys": ["a/one.png"],
    }


def test_rebuild_index_passes_authoritative_key_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / "authoritative_keys.json"
    manifest.write_text('{"image_keys":["one.png"]}', encoding="utf-8")
    monkeypatch.setattr(cp, "AUTHORITATIVE_KEYS_PATH", manifest)
    calls = []
    monkeypatch.setattr(
        cp.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    cp.rebuild_index()

    command, kwargs = calls[0]
    flag_index = command.index("--authoritative-keys")
    assert command[flag_index + 1] == str(manifest)
    assert kwargs["check"] is True


@pytest.mark.parametrize("bad_key", ["../x.png", "/abs/x.png", "x.txt"])
def test_authoritative_manifest_rejects_unsafe_image_keys(
    tmp_path, monkeypatch, bad_key
):
    monkeypatch.setattr(cp, "load_db_image_keys", lambda _url: {bad_key})
    with pytest.raises(ValueError):
        cp.export_authoritative_keys("postgresql://fake/db", tmp_path / "keys.json")


def _empty_file_staging(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    images = data_dir / "images"
    images.mkdir(parents=True)
    source = data_dir / "kipris_metadata.json"
    source.write_text(
        json.dumps({"dataset_info": {"총_상표수": 0}, "trademarks": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cp.paths, "ML_DATA_DIR", data_dir)
    monkeypatch.setattr(cp.paths, "IMAGES_DIR", images)
    monkeypatch.setattr(cp.paths, "TRADEMARK_META_PATH", source)
    stage = data_dir / "staging" / "research.json"
    stage_images = cp.staging_image_dir(stage)
    stage_images.mkdir(parents=True)
    return stage, stage_images, images


def test_file_staging_atomic_merge_and_conflict_no_overwrite(tmp_path, monkeypatch):
    stage, stage_images, _runtime_images = _empty_file_staging(tmp_path, monkeypatch)
    row = (
        "4020260000001",
        "4020260000001",
        "2026-01-01",
        "2026-02-01",
        "BBQ",
        None,
        "도형복합",
        "주식회사 제너시스비비큐",
        "주식회사 제너시스비비큐",
        "4020260000001.png",
        ["270501"],
        [29, 43],
        [],
    )
    (stage_images / row[9]).write_bytes(b"png")

    assert cp.merge_file_staging_rows([row], stage) == (1, 0)
    assert cp.merge_file_staging_rows([row], stage) == (0, 1)
    before = stage.read_bytes()
    conflicting = (*row[:4], "DIFFERENT", *row[5:])

    with pytest.raises(ValueError, match="자동 덮어쓰지 않았습니다"):
        cp.merge_file_staging_rows([conflicting], stage)

    assert stage.read_bytes() == before
    assert not cp.staging_dirty_path(stage).exists()
    payload = json.loads(stage.read_text(encoding="utf-8"))
    manifest = json.loads(
        cp.staging_authoritative_path(stage).read_text(encoding="utf-8")
    )
    assert payload["dataset_info"]["총_상표수"] == 1
    assert manifest["image_keys"] == ["4020260000001.png"]


def test_file_staging_mock_flow_without_database(tmp_path, monkeypatch, capsys):
    stage, stage_images, runtime_images = _empty_file_staging(tmp_path, monkeypatch)
    xml_file = tmp_path / "three.xml"
    xml_file.write_text(XML_THREE, encoding="utf-8")
    monkeypatch.setattr(cp.config, "DATABASE_URL", "")
    monkeypatch.setattr(
        cp.sys,
        "argv",
        [
            "collect_pipeline",
            "--mock-xml",
            str(xml_file),
            "--file-staging",
            str(stage),
            "--nice-class",
            "9",
        ],
    )

    assert cp.main() == 0
    output = capsys.readouterr().out
    payload = json.loads(stage.read_text(encoding="utf-8"))
    assert len(payload["trademarks"]) == 3
    assert len(list(stage_images.glob("*.png"))) == 3
    assert list(runtime_images.glob("*.png")) == []
    assert "[파일 스테이징] page 1 신규 3건" in output
    assert "운영 메타와 운영 인덱스는 변경하지 않았습니다" in output
    assert cp.inspect_file_staging(stage) == (True, None)


def test_file_staging_dirty_marker_blocks_before_network(tmp_path, monkeypatch):
    stage, _stage_images, _runtime_images = _empty_file_staging(tmp_path, monkeypatch)
    cp.staging_dirty_path(stage).parent.mkdir(parents=True, exist_ok=True)
    cp.staging_dirty_path(stage).write_text("incomplete", encoding="utf-8")
    monkeypatch.setattr(cp.config, "DATABASE_URL", "")
    monkeypatch.setattr(
        kc,
        "advanced_search_raw",
        lambda *_args, **_kwargs: pytest.fail("dirty staging must block KIPRIS"),
    )
    monkeypatch.setattr(
        cp.sys,
        "argv",
        [
            "collect_pipeline",
            "--applicant",
            "주식회사 제너시스비비큐",
            "--file-staging",
            str(stage),
        ],
    )

    assert cp.main() == 1


def test_target_total_file_staging_counts_runtime_and_stage_union(
    tmp_path, monkeypatch, capsys
):
    """승격 뒤 재사용한 stage는 운영 메타와 겹쳐도 한 번만 세고 커서를 보존한다."""
    stage, stage_images, _runtime_images = _empty_file_staging(tmp_path, monkeypatch)
    cp.paths.TRADEMARK_META_PATH.write_text(
        json.dumps(
            {
                "dataset_info": {"총_상표수": 2},
                "trademarks": [
                    {"출원번호": "4020190000001"},
                    # 이미 운영으로 승격됐지만 같은 stage에도 남아 있는 레코드.
                    {"출원번호": "4020200000001"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    staged_row = (
        "4020200000001",
        None,
        "2020-01-01",
        None,
        "기존 스테이징",
        None,
        "도형",
        "기존 출원인",
        None,
        "4020200000001.png",
        ["260101"],
        [9],
        [],
    )
    (stage_images / staged_row[9]).write_bytes(b"png")
    assert cp.merge_file_staging_rows([staged_row], stage) == (1, 0)

    calls = []
    response = _advanced_page(
        3,
        ["4020210000001", "4020210000002", "4020210000003"],
    )
    monkeypatch.setattr(cp.config, "DATABASE_URL", "")
    monkeypatch.setattr(kc.limiter, "used_this_month", lambda: 0)
    monkeypatch.setattr(
        kc,
        "advanced_search_raw",
        lambda source, **_kwargs: (calls.append(source), response)[1],
    )
    monkeypatch.setattr(kc, "download_file_now", _counting_download([]))
    monkeypatch.setattr(
        cp.sys,
        "argv",
        [
            "collect_pipeline",
            "--applicant",
            "첫번째",
            "--applicant",
            "두번째",
            "--file-staging",
            str(stage),
            "--target-total",
            "4",
        ],
    )

    assert cp.main() == 0
    output = capsys.readouterr().out
    assert calls == ["첫번째"]
    assert len(cp.load_file_staging_app_numbers(stage)) == 4
    stage_payload = json.loads(stage.read_text(encoding="utf-8"))
    assert len(stage_payload["trademarks"]) == 3
    assert "'기존총계': 2" in output
    assert "'최종총계': 4" in output
    checkpoint = json.loads(
        cp.staging_checkpoint_path(stage).read_text(encoding="utf-8")
    )
    assert checkpoint["cursors"]["첫번째"] == {
        "page": 1,
        "offset": 2,
        "rows_per_page": 100,
    }
    assert cp.inspect_file_staging(stage) == (True, None)


# --------------------------------------------------------------------
# dataset_info 자동 갱신 (db 모드 수집 후 안내 문구 드리프트 방지)
# --------------------------------------------------------------------

def test_refresh_dataset_info_recomputes_from_db(monkeypatch):
    """건수·출원일자 범위·생성일자는 실측으로, 데이터_기준 문구는 기존 값을 보존한다."""
    import datetime as dt

    import psycopg

    executed = []

    class FakeCursor:
        _last = ""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))
            self._last = sql

        def fetchone(self):
            if "count(*)" in self._last:
                return (250, dt.date(2021, 4, 5), dt.date(2026, 5, 21))
            return ({"데이터_기준": "KIPRIS 등록상표 공보(기존)", "출원일자_범위": "옛값"},)

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return FakeCursor()

        def commit(self):
            pass

    monkeypatch.setattr(psycopg, "connect", lambda url: FakeConn())

    info = cp.refresh_dataset_info("postgresql://fake/marklens")

    assert info["총_상표수"] == 250
    assert info["출원일자_범위"] == "2021 ~ 2026"
    assert info["데이터_기준"] == "KIPRIS 등록상표 공보(기존)"
    assert info["생성일자"]  # 오늘 날짜 문자열 — 값 존재만 확인(시계 고정 없음)
    upserts = [sql for sql, _ in executed if "INSERT INTO meta" in sql]
    assert upserts and "dataset_info" in upserts[0]
