"""유명 브랜드 수집(collect_pipeline --search-only·--select-plan·--run-plan) 단위 테스트.

전부 네트워크 없이 — 검색·서지·견본 다운로드는 가짜 함수로 바꾸고, 원본 XML·스테이징·운영 메타
경로는 tmp 로 돌린다(실 ml/data 와 카운터에 손대지 않는다).
"""

import json
from io import BytesIO

import pytest
from PIL import Image

from backend.scripts import collect_pipeline as cp
from backend.src.core import kipris_client as kc


def _item_xml(app_no: str, *, applicant: str, status: str = "등록", vienna: str = "260101",
              classes: str = "43", reg_date: str = "20200101") -> str:
    return (
        f"<item><applicationNumber>{app_no}</applicationNumber>"
        f"<applicationStatus>{status}</applicationStatus>"
        f"<applicantName>{applicant}</applicantName>"
        f"<viennaCode>{vienna}</viennaCode><classificationCode>{classes}</classificationCode>"
        f"<registrationDate>{reg_date}</registrationDate>"
        f"<title>logo-{app_no}</title>"
        f"<bigDrawing>https://plus.kipris.or.kr/image/{app_no}.png</bigDrawing>"
        "</item>"
    )


def _page(total: int, items: list[str]) -> str:
    return (
        "<response><header><resultCode>00</resultCode></header>"
        f"<count><totalCount>{total}</totalCount></count>"
        f"<body><items>{''.join(items)}</items></body></response>"
    )


def _biblio(app_no: str, *, status: str = "등록", codes: tuple[str, ...] = ("G0301",)) -> str:
    similar = "".join(f"<similarCode>{code}</similarCode>" for code in codes)
    return (
        "<response><header><resultCode>00</resultCode></header><body><item>"
        f"<biblioSummaryInfo><applicationNumber>{app_no}</applicationNumber>"
        f"<registerStatus>{status}</registerStatus>"
        "<trademarkDivisionCode>국내상표 도형복합  일반상표</trademarkDivisionCode>"
        "</biblioSummaryInfo>"
        f"<similarityCodeInfo>{similar}</similarityCodeInfo>"
        "<sampleImageInfo><path>https://plus.kipris.or.kr/openapi/fileToss.jsp?arg=x</path>"
        "</sampleImageInfo></item></body></response>"
    )


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """원본 XML·운영 메타·스테이징을 tmp 로. 운영 메타에는 출원번호 1건(중복 거르기 확인용)."""
    data_dir = tmp_path / "data"
    (data_dir / "images").mkdir(parents=True)
    runtime = data_dir / "kipris_metadata.json"
    runtime.write_text(json.dumps({
        "dataset_info": {"총_상표수": 1},
        "trademarks": [{"출원번호": "4020200000009", "이미지파일": "4020200000009.png"}],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cp.paths, "ML_DATA_DIR", data_dir)
    monkeypatch.setattr(cp.paths, "IMAGES_DIR", data_dir / "images")
    monkeypatch.setattr(cp.paths, "TRADEMARK_META_PATH", runtime)
    monkeypatch.setattr(cp, "COLLECT_RAW_XML_DIR", data_dir / "raw" / "xml")
    staging = data_dir / "staging"
    staging.mkdir()
    return staging


def test_read_applicants_file_old_format_and_brand_table(tmp_path):
    """옛 형식은 줄 끝 '# 주석'을 떼고, [브랜드] 표가 있으면 출원인명 열만(토큰 절은 안 읽음)."""
    old = tmp_path / "old.txt"
    old.write_text("# 머리\n주식회사 앤하우스            # 메가MGC커피\n샤넬\n\n", encoding="utf-8")
    assert cp.read_applicants_file(old) == ["주식회사 앤하우스", "샤넬"]

    table = tmp_path / "table.txt"
    table.write_text(
        "# 머리\n[브랜드]\n"
        "메가MGC커피 | 주식회사 앤하우스 | cafe | 가맹점 수 1위 https://example.com/a#b\n"
        "샤넬 | 샤넬 | clothing | 순위 24\n"
        "[식별력 토큰]\n삼성전자주식회사\n",
        encoding="utf-8",
    )
    assert cp.read_applicants_file(table) == ["주식회사 앤하우스", "샤넬"]
    rows = cp.read_brand_rows(table)
    assert rows[0] == cp.BrandRow(
        "메가MGC커피", "주식회사 앤하우스", "cafe", "가맹점 수 1위 https://example.com/a#b"
    )
    bad = tmp_path / "bad.txt"
    bad.write_text("[브랜드]\n브랜드만 | 출원인\n", encoding="utf-8")
    with pytest.raises(ValueError, match="브랜드 \\| 출원인명"):
        cp.read_brand_rows(bad)


def test_applicant_matches_same_company_not_keyword_hits():
    """출원인 검색은 키워드 일치라 결과를 '같은 출원인'으로 다시 거른다(회사 형태·공백 무시)."""
    assert cp.applicant_matches("(주) 비지에프리테일", "비지에프리테일 주식회사")
    assert cp.applicant_matches("교촌 에프 앤 비(주)", "교촌에프앤비 주식회사")
    assert cp.applicant_matches("주식회사 삼립|주식회사 지에스리테일", "주식회사 지에스리테일")
    assert not cp.applicant_matches("네이버웹툰컴퍼니 주식회사", "네이버 주식회사")
    assert not cp.applicant_matches("재단법인 굿네이버스 미래재단", "네이버 주식회사")
    assert not cp.applicant_matches("", "네이버 주식회사")
    two = "인터 이케아 시스템 비. 브이. / 인터 이케아 시스템스 비. 브이."  # KIPRIS 표기 둘
    assert cp.applicant_matches("인터 이케아 시스템스 비. 브이.|Inter IKEA Systems B.V.", two)
    assert cp.applicant_matches("인터 이케아 시스템 비. 브이.", two)
    assert cp.applicant_names(two) == [
        "인터 이케아 시스템 비. 브이.", "인터 이케아 시스템스 비. 브이."]


def test_select_for_applicant_filters_then_orders_and_caps():
    """거르기(출원인·등록·비엔나·운영 중복) 뒤 순서 = 업종 세트 류 → 최근 등록 → 출원번호, 상한."""
    def item(app_no, **kw):
        base = {"ApplicationNumber": app_no, "ApplicantName": "주식회사 갑",
                "ApplicationStatus": "등록", "ViennaCode": ["260101"],
                "GoodClassificationCode": ["43"],
                "RegistrationDate": "20200101"}
        return {**base, **kw}

    items = [
        item("4020200000001", GoodClassificationCode=["9"], RegistrationDate="20250101"),
        item("4020200000002", RegistrationDate="20210101"),
        item("4020200000003", RegistrationDate="20240101"),
        item("4020200000004", ApplicantName="주식회사 갑을"),
        item("4020200000005", ApplicationStatus="소멸"),
        item("4020200000006", ViennaCode=[]),
        item("4020200000007"),  # 운영 메타에 있음
        item("4020200000003", RegistrationDate="20240101"),  # 페이지 중복
    ]
    chosen, stats = cp.select_for_applicant(
        items, applicant="갑 주식회사", preset_classes={43},
        excluded={"4020200000007"}, max_per_applicant=2,
    )
    assert [it["ApplicationNumber"] for it in chosen] == ["4020200000003", "4020200000002"]
    assert stats == {"검색": 8, "출원인_다름": 1, "미등록": 1, "비엔나없음": 1,
                     "상표번호아님": 0, "운영_중복": 1, "후보": 3, "브랜드명_후보": 0}


def test_title_has_brand_korean_substring_and_latin_word_boundary():
    """국문은 공백·기호를 뗀 부분 일치, 영문은 단어 경계 일치(아포스트로피·하이픈 무시)."""
    assert cp.title_has_brand("불닭발 동대문 엽기 떡볶이 땡초", ["엽기떡볶이"])
    assert cp.title_has_brand("PAIK'S COFFEE", ["빽다방", "PAIK'S"])
    assert cp.title_has_brand("Nice to CU", ["CU", "씨유"])
    assert not cp.title_has_brand("쿠폰 cupon", ["CU", "씨유"])
    assert cp.title_has_brand("L'ORE'AL PROFESSIONNEL", ["로레알", "L'OREAL"])
    assert cp.title_has_brand("ya-nolja", ["야놀자", "YANOLJA"])
    assert cp.title_has_brand("LOUIS VUITTON PARIS", ["루이비통", "LOUIS VUITTON"])
    assert not cp.title_has_brand("HALO STUDIOS", ["마이크로소프트", "MICROSOFT"])
    assert not cp.title_has_brand(None, ["샤넬", "CHANEL"]) and not cp.title_has_brand("", [])
    assert cp.brand_names("교촌치킨 / 교촌 / KYOCHON") == ["교촌치킨", "교촌", "KYOCHON"]


def test_select_prefers_brand_name_titles_then_fills_with_previous_order():
    """상표명에 브랜드명이 든 표장을 먼저, 모자라면 기존 순서(업종 류 → 최근 등록)로 채운다."""
    def item(app_no, title, date, classes=("43",)):
        return {"ApplicationNumber": app_no, "ApplicantName": "주식회사 갑",
                "ApplicationStatus": "등록", "ViennaCode": ["260101"], "Title": title,
                "GoodClassificationCode": list(classes), "RegistrationDate": date}

    items = [item("4020200000001", "다른브랜드", "20250101"),
             item("4020200000002", "GAP COFFEE", "20100101", classes=("9",)),
             item("4020200000003", "갑커피 로고", "20120101"),
             item("4020200000004", "", "20240101")]
    chosen, stats = cp.select_for_applicant(
        items, applicant="주식회사 갑", preset_classes={43}, excluded=set(),
        max_per_applicant=3, names=["갑커피", "GAP"],
    )
    assert [it["ApplicationNumber"] for it in chosen] == [
        "4020200000003", "4020200000002", "4020200000001"]
    assert stats["브랜드명_후보"] == 2


def test_search_only_reuses_complete_saved_search_and_records_new(sandbox, monkeypatch):
    """완전한 기존 원본(1쪽~totalCount)은 다시 부르지 않고, 새 검색어는 쪽마다 원본을 저장해
    검색 목록에 파일·건수·출원인 분포를 적는다. 두 번째 실행은 호출 0."""
    cp.save_raw_xml("가사_p1", _page(1, [_item_xml("4020200000001", applicant="가사")]))
    calls: list[tuple[str, int]] = []

    def fake_search(source, *, page_no=1, num_of_rows=500, request_timeout=None):
        calls.append((source, page_no))
        numbers = ["4020200000011", "4020200000012"] if page_no == 1 else ["4020200000013"]
        return _page(3, [_item_xml(n, applicant="주식회사 나사") for n in numbers])

    monkeypatch.setattr(kc, "advanced_search_raw", fake_search)
    manifest = sandbox / "famous.search.json"
    report = cp.run_search_only(
        ["가사", "나사"], manifest, rows_per_page=2, max_pages=4, max_retries=0,
        retry_backoff_seconds=0, request_timeout_seconds=5,
    )
    assert calls == [("나사", 1), ("나사", 2)]
    assert report == {"검색어": 2, "재사용": 1, "검색": 1, "호출": 2, "실패": 0, "멈춤": ""}
    entries = json.loads(manifest.read_text(encoding="utf-8"))["검색"]
    assert entries["가사"]["재사용"] and entries["가사"]["완전"]
    assert entries["나사"]["완전"] and entries["나사"]["건수"] == 3
    assert entries["나사"]["출원인_분포"] == {"주식회사 나사": 3}
    assert len(entries["나사"]["파일"]) == 2

    calls.clear()
    again = cp.run_search_only(
        ["가사", "나사"], manifest, rows_per_page=2, max_pages=4, max_retries=0,
        retry_backoff_seconds=0, request_timeout_seconds=5,
    )
    assert calls == [] and again["재사용"] == 2


def test_search_only_stops_after_five_consecutive_errors(sandbox, monkeypatch):
    """서버 거절(resultCode 오류)이 이어지면 5번째에서 멈춘다 — 예산만 태우지 않게."""
    calls: list[str] = []

    def rejected(source, **_kwargs):
        calls.append(source)
        return ("<response><header><resultCode>22</resultCode>"
                "<resultMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</resultMsg>"
                "</header></response>")

    monkeypatch.setattr(kc, "advanced_search_raw", rejected)
    report = cp.run_search_only(
        [f"회사{i}" for i in range(8)], sandbox / "m.json", rows_per_page=500, max_pages=1,
        max_retries=0, retry_backoff_seconds=0, request_timeout_seconds=5,
    )
    assert len(calls) == 5
    assert report["실패"] == 5 and report["멈춤"] == "연속 오류 5회"


def _manifest_for(sandbox, monkeypatch, items_by_source: dict[str, list[str]]):
    def fake_search(source, *, page_no=1, num_of_rows=500, request_timeout=None):
        rows = items_by_source[source]
        return _page(len(rows), rows)

    monkeypatch.setattr(kc, "advanced_search_raw", fake_search)
    manifest = sandbox / "famous.search.json"
    cp.run_search_only(list(items_by_source), manifest, rows_per_page=500, max_pages=1,
                       max_retries=0, retry_backoff_seconds=0, request_timeout_seconds=5)
    return cp._read_search_manifest(manifest)  # noqa: SLF001


def test_select_plan_then_run_plan_into_staging(sandbox, monkeypatch):
    """계획(호출 0) → 실행: 서지 1회로 유사군·등록 상태·새 견본 링크를 받고 견본을 바로 받아
    스테이징에 '수집_출처' 와 함께 넣는다. 소멸 건은 빼고, 재실행은 이미 넣은 건을 건너뛴다."""
    manifest = _manifest_for(sandbox, monkeypatch, {
        "주식회사 갑": [
            _item_xml("4020200000001", applicant="주식회사 갑", reg_date="20240101"),
            _item_xml("4020200000002", applicant="주식회사 갑", reg_date="20230101"),
            _item_xml("4020200000009", applicant="주식회사 갑"),  # 운영 메타와 중복
            _item_xml("4020200000003", applicant="주식회사 갑", classes="9"),
        ],
        "을 인크.": [_item_xml("4020200000021", applicant="을 인크.", classes="25")],
    })
    brands = [cp.BrandRow("갑커피", "주식회사 갑", "cafe", "근거"),
              cp.BrandRow("을옷", "을 인크.", "clothing", "근거"),
              cp.BrandRow("병", "주식회사 병", "pub", "근거")]
    plan = cp.build_selection_plan(
        brands, manifest, preset_classes=cp.load_business_preset_classes(),
        excluded={"4020200000009"}, max_per_applicant=2,
    )
    assert [r["출원번호"] for r in plan["records"]] == [
        "4020200000001", "4020200000002", "4020200000021"]
    assert [b["상태"] for b in plan["brands"]] == ["ok", "ok", "검색 없음"]
    assert plan["estimated_calls"]["서지(유사군·견본 링크)"] == 3

    fetched: list[str] = []

    def fake_fetch(app_no):
        fetched.append(app_no)
        return _biblio(app_no, status="소멸(존속기간만료)" if app_no.endswith("21") else "등록")

    def fake_download(url, dest, *, validate_image=False):
        assert validate_image and "fileToss" in url
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_png_bytes())
        return dest

    staging = sandbox / "famous.json"
    report = cp.run_selection_plan(plan, staging, source_label="유명 브랜드",
                                   fetch=fake_fetch, download=fake_download)
    assert report["수집"] == 2 and report["제외_등록상태"] == 1
    assert report["서지_호출"] == 3 and report["견본_다운로드"] == 2
    assert cp.inspect_file_staging(staging) == (True, None)
    records = json.loads(staging.read_text(encoding="utf-8"))["trademarks"]
    assert {r["수집_출처"] for r in records} == {"유명 브랜드"}
    assert records[0]["유사군"] == ["G0301"] and records[0]["상표구분"] == "도형복합"
    assert any((cp.paths.ML_DATA_DIR / "raw" / "xml").glob("biblio_4020200000001_*.xml"))

    fetched.clear()
    again = cp.run_selection_plan(plan, staging, source_label="유명 브랜드",
                                  fetch=fake_fetch, download=fake_download)
    assert again["이미_있음"] == 2 and fetched == ["4020200000021"]


def test_select_plan_skips_empty_search_with_same_query_core(sandbox, monkeypatch):
    """전체 이름 검색이 0건이고 핵심어 검색에 그 출원인이 나오면, 검색어가 같은 빈 항목이 아니라
    출원인이 실제로 나온 항목을 쓴다(빽다방: '주식회사 더본코리아' 0건 · '더본코리아' 118건)."""
    manifest = _manifest_for(sandbox, monkeypatch, {
        "주식회사 병": [],
        "병": [_item_xml("4020200000031", applicant="(주)병")],
    })
    plan = cp.build_selection_plan(
        [cp.BrandRow("병커피", "(주)병", "cafe", "근거")], manifest,
        preset_classes=cp.load_business_preset_classes(), excluded=set(), max_per_applicant=10,
    )
    assert plan["brands"][0]["검색어"] == "병" and plan["brands"][0]["선택"] == 1


def test_sync_staging_prunes_outside_plan_and_sets_memo(sandbox, monkeypatch, tmp_path):
    """계획을 다시 만들면: 계획 밖 레코드는 빼고 견본은 보관 폴더로(원본 XML 은 그대로), 남는
    레코드는 메모를 계획대로, 새 건만 서지·견본을 받는다. 브랜드명 없는 표장엔 메모."""
    manifest = _manifest_for(sandbox, monkeypatch, {"주식회사 갑": [
        _item_xml("4020200000001", applicant="주식회사 갑", reg_date="20240101"),
        _item_xml("4020200000002", applicant="주식회사 갑", reg_date="20230101"),
        _item_xml("4020200000003", applicant="주식회사 갑", reg_date="20100101"),
    ]})
    brands = [cp.BrandRow("갑", "주식회사 갑", "cafe", "근거")]
    presets = cp.load_business_preset_classes()
    first = cp.build_selection_plan(brands, manifest, preset_classes=presets, excluded=set(),
                                    max_per_applicant=2)
    for record in first["records"]:  # 메모 도입 전 계획으로 받은 스테이징과 같게
        record.pop("메모", None)
    fetched: list[str] = []

    def fake_fetch(app_no):
        fetched.append(app_no)
        return _biblio(app_no)

    def fake_download(url, dest, *, validate_image=False):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_png_bytes())
        return dest

    staging = sandbox / "famous.json"
    cp.run_selection_plan(first, staging, source_label="유명 브랜드", fetch=fake_fetch,
                          download=fake_download)
    assert fetched == ["4020200000001", "4020200000002"]
    raw_before = sorted(p.name for p in (cp.paths.ML_DATA_DIR / "raw" / "xml").glob("biblio_*"))

    # 상표명 'logo-4020200000003' 만 브랜드명 'logo-4020200000003' 을 담는다 → 그 건이 맨 앞으로
    second = cp.build_selection_plan(
        [cp.BrandRow("갑 / logo-4020200000003", "주식회사 갑", "cafe", "근거")], manifest,
        preset_classes=presets, excluded=set(), max_per_applicant=2)
    assert [r["출원번호"] for r in second["records"]] == ["4020200000003", "4020200000001"]
    assert second["records"][1]["메모"] == cp.OTHER_BRAND_MEMO
    assert "메모" not in second["records"][0]

    archive = tmp_path / "archive"
    fetched.clear()
    report = cp.run_selection_plan(second, staging, source_label="유명 브랜드",
                                   fetch=fake_fetch, download=fake_download, archive_dir=archive)
    assert fetched == ["4020200000003"] and report["이미_있음"] == 1
    assert report["메모_변경"] == 1 and report["뺌"] == 1
    assert report["브랜드별"] == [{"브랜드": "갑", "업종": "cafe", "새로_대상": 1, "받음": 1,
                                  "뺌": 1, "완료": True}]
    assert (archive / "images" / "4020200000002.png").exists()
    assert [r["출원번호"] for r in json.loads((archive / "removed_records.json").read_text(
        encoding="utf-8"))] == ["4020200000002"]
    assert cp.inspect_file_staging(staging) == (True, None)
    records = {r["출원번호"]: r for r in json.loads(staging.read_text("utf-8"))["trademarks"]}
    assert set(records) == {"4020200000001", "4020200000003"}
    assert records["4020200000001"]["메모"] == cp.OTHER_BRAND_MEMO
    assert "메모" not in records["4020200000003"]
    checkpoint = json.loads(cp.staging_checkpoint_path(staging).read_text("utf-8"))
    assert "4020200000002" not in checkpoint["collected"]
    raw_after = sorted(p.name for p in (cp.paths.ML_DATA_DIR / "raw" / "xml").glob("biblio_*"))
    assert set(raw_before) <= set(raw_after)  # 원본 XML 은 남는다


def test_run_plan_stops_after_five_consecutive_errors_and_respects_cap(sandbox, monkeypatch):
    manifest = _manifest_for(sandbox, monkeypatch, {
        "주식회사 갑": [_item_xml(f"40202000001{i:02d}", applicant="주식회사 갑")
                    for i in range(8)],
    })
    plan = cp.build_selection_plan(
        [cp.BrandRow("갑", "주식회사 갑", "cafe", "근거")], manifest,
        preset_classes=cp.load_business_preset_classes(), excluded=set(), max_per_applicant=8,
    )
    calls: list[str] = []

    def failing(app_no):
        calls.append(app_no)
        raise kc.KiprisNetworkError("down")

    report = cp.run_selection_plan(plan, sandbox / "s.json", source_label="유명 브랜드",
                                   fetch=failing, download=None)
    assert len(calls) == 5 and report["멈춤"] == "연속 오류 5회"

    calls.clear()
    capped = cp.run_selection_plan(plan, sandbox / "s.json", source_label="유명 브랜드",
                                   fetch=failing, download=None, max_calls=4, limit=None)
    # 하드캡은 KIPRIS API 호출(서지)만 센다 — 견본 다운로드는 따로
    assert len(calls) == 4 and capped["멈춤"] == "호출 상한 4"


def test_run_plan_prunes_only_brands_fully_received_in_industry_order(sandbox, monkeypatch,
                                                                       tmp_path):
    """업종 순서대로 받고, 새 건을 다 받은 브랜드만 이전 건을 뺀다. 상한·거절로 멈추면 남은 브랜드의
    이전 건은 그대로 — 스테이징이 줄지 않는다."""
    manifest = _manifest_for(sandbox, monkeypatch, {
        "주식회사 갑": [_item_xml("4020200000001", applicant="주식회사 갑"),
                    _item_xml("4020200000002", applicant="주식회사 갑", reg_date="20100101")],
        "주식회사 을": [_item_xml("4020200000011", applicant="주식회사 을"),
                    _item_xml("4020200000012", applicant="주식회사 을", reg_date="20100101")],
    })
    presets = cp.load_business_preset_classes()

    def fake_fetch(app_no):
        return _biblio(app_no)

    def fake_download(url, dest, *, validate_image=False):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_png_bytes())
        return dest

    old_rows = [cp.BrandRow("갑", "주식회사 갑", "software", "근거"),
                cp.BrandRow("을", "주식회사 을", "cafe", "근거")]
    first = cp.build_selection_plan(old_rows, manifest, preset_classes=presets, excluded=set(),
                                    max_per_applicant=1)
    staging = sandbox / "famous.json"
    cp.run_selection_plan(first, staging, source_label="유명 브랜드", fetch=fake_fetch,
                          download=fake_download)
    assert set(cp._staged_records(staging)) == {"4020200000001", "4020200000011"}  # noqa: SLF001

    new_rows = [cp.BrandRow("갑 / logo-4020200000002", "주식회사 갑", "software", "근거"),
                cp.BrandRow("을 / logo-4020200000012", "주식회사 을", "cafe", "근거")]
    second = cp.build_selection_plan(new_rows, manifest, preset_classes=presets, excluded=set(),
                                     max_per_applicant=1)
    calls: list[str] = []

    def counting_fetch(app_no):
        calls.append(app_no)
        return _biblio(app_no)

    report = cp.run_selection_plan(
        second, staging, source_label="유명 브랜드", fetch=counting_fetch,
        download=fake_download, archive_dir=tmp_path / "archive", max_calls=1,
        industry_order=["cafe", "software"],
    )
    assert calls == ["4020200000012"]  # cafe(을) 먼저
    assert report["멈춤"] == "호출 상한 1"
    assert [(b["브랜드"], b["완료"], b["뺌"]) for b in report["브랜드별"]] == [
        ("을", True, 1), ("갑", False, 0)]
    staged = set(cp._staged_records(staging))  # noqa: SLF001
    assert staged == {"4020200000001", "4020200000012"}  # 갑의 이전 건은 그대로
    assert cp.inspect_file_staging(staging) == (True, None)


def test_saved_biblio_not_registered_reads_latest_status(sandbox):
    """저장된 서지 원본의 등록 상태가 '등록'이 아니면 계획에서 미리 뺀다(출원번호마다 최신 원본)."""
    cp.save_raw_xml("biblio_4020200000001", _biblio("4020200000001", status="소멸(존속기간만료)"))
    cp.save_raw_xml("biblio_4020200000002", _biblio("4020200000002"))
    assert cp.saved_biblio_not_registered() == {"4020200000001"}


def test_short_mark_kind_matches_runtime_vocabulary():
    """서지 표장구분을 운영 메타 표기로 — 유형 판정이 상표구분 근거를 그대로 쓰게."""
    assert cp.short_mark_kind("국내상표 도형복합 일반상표") == "도형복합"
    assert cp.short_mark_kind("국내상표  도형상표 일반상표") == "도형상표"
    assert cp.short_mark_kind("국내상표 문자상표 일반상표") == "국내상표 문자상표 일반상표"
    assert cp.short_mark_kind(None) is None and cp.short_mark_kind("  ") is None


def test_use_key_and_counter_switches_key_and_counter(tmp_path, monkeypatch):
    """--key-env·--counter: trials_enrich lookup 과 같은 규약(키 값은 돌려주지 않음)."""
    shared = tmp_path / "kipris_call_count.json"
    month, day = kc.RateLimiter._month_key(), kc.RateLimiter._day_key()
    shared.write_text(json.dumps({month: 688, day: 177}), encoding="utf-8")
    monkeypatch.setattr(kc, "limiter", kc.RateLimiter(counter_path=shared, min_interval=0.0))
    monkeypatch.setattr(kc, "ACCESS_KEY", "")
    monkeypatch.setenv("TEST_TEAM_KEY", "  secret-value-123  ")
    own = tmp_path / "jiwon" / "kipris_call_count.json"
    own.parent.mkdir()
    own.write_text(json.dumps({month: 148, day: 3}), encoding="utf-8")

    info = cp.use_key_and_counter(key_env="TEST_TEAM_KEY", counter=own)
    assert kc.ACCESS_KEY == "secret-value-123"
    assert "secret" not in json.dumps(info, ensure_ascii=False)
    assert info == {"키": "환경변수 TEST_TEAM_KEY", "카운터": str(own), "이번_달": 148, "오늘": 3}
    kc.limiter.min_interval = 0.0
    kc.limiter.acquire()
    assert json.loads(own.read_text(encoding="utf-8"))[month] == 149
    assert json.loads(shared.read_text(encoding="utf-8")) == {month: 688, day: 177}
    monkeypatch.setenv("TEST_TEAM_KEY", "")
    with pytest.raises(SystemExit):
        cp.use_key_and_counter(key_env="TEST_TEAM_KEY")
