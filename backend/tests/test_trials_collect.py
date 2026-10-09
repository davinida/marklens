"""다빈-1 심결례 수집 스크립트(trials_collect) 단위 테스트 — 전부 네트워크 없이 동작한다.

KIPRIS 호출은 Session.transport 에 가짜 함수를 주입하고, PDF 다운로드도 가짜로 바꾼다.
dry-run 은 kipris_client 의 HTTP 클라이언트를 막아 두고 돌려 실호출이 0 임을 보인다.
"""

import argparse
import csv
import json
from pathlib import Path

import pytest

from backend.scripts import trials_collect as tc
from backend.src.core import kipris_client as kc

KINDS = Path(tc.KINDS_CONFIG_PATH)

# 2026-09-30 실응답(2024-01 목록 203건 중 법인 당사자 2건: 거절결정불복 Y · 무효). 태그 사이에만
# 줄바꿈을 넣었다(원본은 한 줄).
XML_LIST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<response>
<header>
<requestMsgID>
</requestMsgID>
<responseTime>2026-09-30 19:22:55.2255</responseTime>
<responseMsgID>
</responseMsgID>
<successYN>Y</successYN>
<resultCode>00</resultCode>
<resultMsg>NORMAL SERVICE.</resultMsg>
</header>
<body>
<items>
<item>
<appReferenceNumber>
</appReferenceNumber>
<applicationNumber>4020210004125</applicationNumber>
<defendant>
</defendant>
<internationalRegisterNumber>
</internationalRegisterNumber>
<plaintiff>주식회사 인큐텐</plaintiff>
<regReferenceNumber>
</regReferenceNumber>
<registrationNumber>
</registrationNumber>
<title>Dr.Qmin</title>
<trialDecisionDoc>Y</trialDecisionDoc>
<trialDesc>거절결정불복</trialDesc>
<trialFlag>특허심판원</trialFlag>
<trialNumber>2022101002112</trialNumber>
<trialStatus>심결</trialStatus>
</item>
<item>
<appReferenceNumber>
</appReferenceNumber>
<applicationNumber>4020200070750</applicationNumber>
<defendant>팜어스 농업회사법인 주식회사</defendant>
<internationalRegisterNumber>
</internationalRegisterNumber>
<plaintiff>농업회사법인 주식회사 옻가네</plaintiff>
<regReferenceNumber>
</regReferenceNumber>
<registrationNumber>4017268290000</registrationNumber>
<title>홍삼 콜라겐 3300</title>
<trialDecisionDoc>Y</trialDecisionDoc>
<trialDesc>무효</trialDesc>
<trialFlag>특허심판원</trialFlag>
<trialNumber>2022100002719</trialNumber>
<trialStatus>확정</trialStatus>
</item>
<numOfRows>500</numOfRows>
<pageNo>1</pageNo>
<totalCount>2</totalCount>
</items>
</body>
</response>"""

# 심판(결)문 실응답(2022원2112, fileToss 링크는 마스킹)
XML_DOC = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<response>
<header>
<requestMsgID>
</requestMsgID>
<responseTime>2026-09-30 19:24:00.240</responseTime>
<responseMsgID>
</responseMsgID>
<successYN>Y</successYN>
<resultCode>00</resultCode>
<resultMsg>NORMAL SERVICE.</resultMsg>
</header>
<body>
<item>
<fileName>2022101002112.PDF</fileName>
<kind>S10221</kind>
<openYN>Y</openYN>
<path>http://plus.kipris.or.kr/openapi/fileToss.jsp?arg=MASKED</path>
</item>
</body>
</response>"""
XML_DOC_CLOSED = XML_DOC.replace("<openYN>Y</openYN>", "<openYN>N</openYN>")

# 2013당419 구조(실측 기록)를 따른 픽스처 — 저명상표(구법 7조1항 10호) 사례 → 3등급
TEXT_FAME = """심판번호 2013당419
사건표시 상표등록 제915763호 무효
청구인 루이비똥 말레띠에
피청구인 홍길동
심결일 2014. 6. 3.
주 문
상표등록 제915763호는 그 등록을 무효로 한다.
심판비용은 피청구인이 부담한다.
청구취지
주문과 같다.
이 유
1. 기초사실
가. 이 사건 등록상표
(1) 등록번호/출원일/등록일: 상표등록 제915763호/2010. 5. 3./2012. 4. 2.
(2) 구성: [이미지]
(3) 지정상품: 상품류 구분 제18류의 가방, 핸드백, 지갑
나. 선등록상표 1
(1) 등록번호/출원일/등록일: 상표등록 제123456호/1999. 1. 1./2000. 2. 2.
(2) 구성: [이미지]
(3) 지정상품: 상품류 구분 제18류의 가방
(4) 등록권리자: 청구인
다. 선등록상표 2
(1) 등록번호: 상표등록 제234567호
2. 당사자의 주장
가. 청구인
이 사건 등록상표는 청구인의 저명한 선등록상표들과 유사하다.
나. 피청구인
3. 판단
가. 이 사건 등록상표가 구 상표법 제7조 제1항 제10호에 해당하는지 여부
(1) 판단기준
(2) 저명성
(3) 표장의 유사 여부
(4) 지정상품의 유사 여부
(5) 소결
이 사건 등록상표는 구 상표법 제7조 제1항 제10호에 해당한다.
나. 소결론
이 사건 등록상표는 구 상표법 제7조 제1항 제10호에 해당하므로 그 등록이 무효로 되어야 한다.
4. 결론
그렇다면 이 사건 심판청구는 이유 있으므로 주문과 같이 심결한다.
"""

# 같은 구조, 결론이 34조1항 7호(선등록 유사)만인 순수 유사 사례 → 1등급
TEXT_SIMILAR = """심판번호 2020당100
사건표시 상표등록 제2000001호 무효
주 문
상표등록 제2000001호는 그 등록을 무효로 한다.
청구취지
주문과 같다.
이 유
1. 기초사실
가. 이 사건 등록상표
(1) 등록번호: 상표등록 제2000001호
(3) 지정상품: 상품류 구분 제30류의 커피, 차
나. 선등록상표
(1) 등록번호: 상표등록 제1000001호
2. 당사자의 주장
가. 청구인
나. 피청구인
3. 판단
가. 이 사건 등록상표가 상표법 제34조 제1항 제7호에 해당하는지 여부
(1) 판단기준
(2) 표장의 유사 여부
(3) 지정상품의 유사 여부
(4) 소결
이 사건 등록상표는 선등록상표와 표장 및 지정상품이 유사하므로 상표법 제34조 제1항 제7호에 해당한다.
나. 소결론
이 사건 등록상표는 상표법 제34조 제1항 제7호에 해당하므로 그 등록이 무효로 되어야 한다.
4. 결론
그렇다면 이 사건 심판청구는 이유 있으므로 주문과 같이 심결한다.
"""

# 거절결정불복 — 원결정 취소(7호 부정) → 1등급·비유사, 거절이유 조문 7호
TEXT_REFUSAL = """심판번호 2021원500
주 문
원결정을 취소한다.
청구취지
주문과 같다.
이 유
1. 기초사실
가. 이 사건 출원상표
(1) 출원번호/출원일: 제40-2020-0012345호/2020. 3. 2.
(3) 지정상품: 상품류 구분 제30류의 커피
나. 선등록상표
(1) 등록번호: 상표등록 제1000001호
2. 거절결정 이유
이 사건 출원상표는 선등록상표와 유사하여 상표법 제34조 제1항 제7호에 해당한다는
이유로 거절결정되었다.
3. 판단
가. 판단기준
나. 표장의 유사 여부
다. 소결
이 사건 출원상표는 상표법 제34조 제1항 제7호에 해당하지 아니한다.
4. 결론
그렇다면 원결정은 위법하므로 이를 취소한다.
"""


@pytest.fixture(autouse=True)
def _fast_limiter(monkeypatch):
    monkeypatch.setattr(kc, "MIN_CALL_INTERVAL_SEC", 0.0)
    # CI 에는 .env 가 없다 — Session.api_get 의 키 검사가 가짜 transport 테스트를 막지 않게 더미 키.
    # 실호출 경로는 transport 주입으로 차단돼 있고, dry-run 테스트는 kc._get_client 를 막아 둔다.
    monkeypatch.setenv("KIPRIS_TRIAL_ACCESS_KEY", "test-trial-key")


def _list_args(tmp_path: Path, **overrides) -> argparse.Namespace:
    values = {
        "kind": "refusal", "from": "202401", "to": "202402", "rows": 500, "max_pages": 10,
        "allow_unverified": True, "kinds_config": KINDS, "data_dir": tmp_path,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _session(tmp_path: Path, transport, downloader=None, **kw) -> tc.Session:
    return tc.Session(
        paths=tc.TrialPaths(tmp_path),
        transport=transport,
        downloader=downloader or (lambda url, dest: dest),
        **kw,
    )


def _fake_pdf_downloader(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-1.4\n%fake\n")
    return dest


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# ---------------- 파싱 ----------------

def test_parse_search_page_capture_sample():
    items, total = tc.parse_search_page(XML_LIST)
    assert total == 2
    assert [it["trialNumber"] for it in items] == ["2022101002112", "2022100002719"]
    assert items[0]["trialDesc"] == "거절결정불복" and items[0]["trialDecisionDoc"] == "Y"
    assert items[0]["applicationNumber"] == "4020210004125" and items[0]["trialStatus"] == "심결"
    assert items[1]["trialDesc"] == "무효" and items[1]["trialFlag"] == "특허심판원"


def test_parse_doc_response_measured_format():
    doc = tc.parse_doc_response(XML_DOC)
    assert doc["fileName"] == "2022101002112.PDF" and doc["kind"] == "S10221"
    assert doc["openYN"] == "Y" and doc["path"].startswith("http://plus.kipris.or.kr/")
    with pytest.raises(kc.KiprisError):
        tc.parse_doc_response(XML_DOC.replace("<resultCode>00", "<resultCode>31"))


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ({"applicationNumber": "4020080049731"}, True),
        ({"applicationNumber": "41-2020-0000001"}, True),
        ({"applicationNumber": "4520200000001"}, True),
        ({"applicationNumber": "1020070001615"}, False),
        ({"applicationNumber": "7020200001707"}, True),  # 국제상표(마드리드) 포함
        ({"applicationNumber": "4420190000002"}, False),  # 지리적표시 단체표장 제외
        ({"applicationNumber": "", "registrationNumber": "4009157630000"}, True),
        ({"applicationNumber": "", "registrationNumber": ""}, False),
    ],
)
def test_is_trademark_item_prefix_filter(item, expected):
    assert tc.is_trademark_item(item) is expected


def test_kind_for_trial_desc_mapping():
    kinds = tc.load_kinds(KINDS)
    assert set(kinds) == {"refusal", "invalidation", "scope"}
    assert all(spec["verified"] for spec in kinds.values())  # 2026-09-30 실측으로 확정
    assert tc.trial_desc_values(kinds["scope"]) == ["권리범위확인(적극적)", "권리범위확인(소극적)"]
    assert tc.kind_for_trial_desc("거절결정불복", kinds) == "refusal"
    assert tc.kind_for_trial_desc("등록무효", kinds) == "invalidation"
    assert tc.kind_for_trial_desc("권리범위확인(소극적)", kinds) == "scope"
    assert tc.kind_for_trial_desc("상표 무효 심판", kinds) == "invalidation"  # 휴리스틱
    assert tc.kind_for_trial_desc("기피", kinds) == ""


def test_month_range_and_search_params():
    assert tc.month_range("202311", "202402") == ["202311", "202312", "202401", "202402"]
    with pytest.raises(ValueError):
        tc.month_range("202413", "202501")
    with pytest.raises(ValueError):
        tc.month_range("202402", "202401")
    params = tc.build_search_params("거절결정불복", "202401", 2, 500)
    assert params["tradeMark"] == "true" and params["patent"] == "false"
    assert params["patentTrial"] == "true" and params["patentCourt"] == "false"
    assert params["exParte"] == "true" and params["interParties"] == "true"
    assert params["trialDate"] == "202401"
    assert params["pageNo"] == "2" and params["numOfRows"] == "500"


# ---------------- list ----------------

def test_list_writes_trademarks_only_idempotent_and_counts_quota(tmp_path, capsys):
    calls: list[dict] = []

    def transport(url, params):
        calls.append(params)
        assert url.endswith("/getAdvancedSearch") and "ServiceKey" in params
        return XML_LIST

    session = _session(tmp_path, transport, max_calls=10)
    assert tc.run_list(_list_args(tmp_path), session) == 0
    rows = _rows(session.paths.list_csv)
    assert [r["심판번호"] for r in rows] == ["2022101002112", "2022100002719"]  # 2개월 중복 제거
    assert rows[0]["종류"] == "거절결정불복" and rows[0]["출원번호"] == "4020210004125"
    assert rows[0]["심결문유무"] == "Y" and json.loads(rows[0]["원본JSON"])["title"] == "Dr.Qmin"
    assert [c["trialDate"] for c in calls] == ["202401", "202402"]
    assert session.api_calls == 2
    quota = json.loads(session.paths.quota.read_text(encoding="utf-8"))
    assert quota[kc.RateLimiter._month_key()] == 2
    assert len(session.paths.calls_log.read_text(encoding="utf-8").splitlines()) == 2
    assert sorted(session.paths.raw_xml_dir.glob("list_refusal_*_p1.xml")) != []
    progress = json.loads(session.paths.list_progress.read_text(encoding="utf-8"))
    assert progress["refusal"]["202401"]["done"] and progress["refusal"]["202402"]["total"] == 2

    again = _session(tmp_path, transport, max_calls=10)
    assert tc.run_list(_list_args(tmp_path), again) == 0
    assert again.api_calls == 0  # 완료한 월은 건너뛴다
    assert "미완료 0개월" in capsys.readouterr().out


def test_list_hard_cap_stops_and_keeps_partial_progress(tmp_path):
    session = _session(tmp_path, lambda url, params: XML_LIST, max_calls=1)
    assert tc.run_list(_list_args(tmp_path), session) == 3
    assert session.api_calls == 1
    progress = json.loads(session.paths.list_progress.read_text(encoding="utf-8"))
    assert progress["refusal"]["202401"]["done"] is True
    assert progress["refusal"]["202402"]["done"] is False


def test_list_refuses_unverified_kind_without_flag(tmp_path):
    unverified = tmp_path / "kinds.json"
    unverified.write_text(json.dumps({"refusal": {"trialDesc": "거절결정불복", "verified": False}}),
                          encoding="utf-8")
    session = _session(tmp_path, lambda url, params: XML_LIST)
    args = _list_args(tmp_path, allow_unverified=False, kinds_config=unverified)
    assert tc.run_list(args, session) == 2
    assert session.api_calls == 0


def test_list_calls_once_per_trial_desc_value_for_scope(tmp_path):
    seen: list[str] = []
    session = _session(tmp_path, lambda url, params: seen.append(params["trialDesc"]) or XML_LIST,
                       max_calls=10)
    assert tc.run_list(_list_args(tmp_path, kind="scope", to="202401"), session) == 0
    assert seen == ["권리범위확인(적극적)", "권리범위확인(소극적)"]  # 실측값 2개 → 월 2회
    assert (session.paths.raw_xml_dir / "list_scope_202401_d1_p1.xml").exists()


def test_list_paginates_when_total_exceeds_rows(tmp_path):
    seen: list[str] = []

    def transport(url, params):
        seen.append(params["pageNo"])
        return XML_LIST.replace("<totalCount>2<", "<totalCount>3<")

    session = _session(tmp_path, transport, max_calls=10)
    args = _list_args(tmp_path, to="202401", rows=2)
    assert tc.run_list(args, session) == 0
    assert seen == ["1", "2"]  # ceil(3/2) = 2 페이지


# ---------------- fetch ----------------

def _write_list(paths_: tc.TrialPaths, numbers: list[str]) -> None:
    rows = [
        {"심판번호": n, "종류": "무효", "심결월": "202401", "심판상태": "심결", "상표명칭": "X",
         "출원번호": "4020080049731", "등록번호": "", "청구인": "", "피청구인": "",
         "심결문유무": "Y", "원본JSON": "{}"}
        for n in numbers
    ]
    tc._write_csv(paths_.list_csv, tc.LIST_COLUMNS, rows)


def test_fetch_downloads_immediately_and_skips_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "COUNT_DOWNLOADS", True)
    calls: list[dict] = []

    def transport(url, params):
        calls.append(params)
        assert url.endswith("/getJudDocumentInfoSearch") and "ServiceKey" in params
        return XML_DOC

    session = _session(tmp_path, transport, downloader=_fake_pdf_downloader, max_calls=10)
    _write_list(session.paths, ["2013100000419", "2013100000420"])
    args = argparse.Namespace(limit=0, skip_no_doc=False, retry_failed=False)
    assert tc.run_fetch(args, session) == 0
    assert [c["trialNumber"] for c in calls] == ["2013100000419", "2013100000420"]
    assert (session.paths.pdf_dir / "2013100000419.pdf").exists()
    assert session.api_calls == 2 and session.downloads == 2
    quota = json.loads(session.paths.quota.read_text(encoding="utf-8"))
    assert quota[kc.RateLimiter._month_key()] == 4
    assert [r["결과"] for r in _rows(session.paths.fetch_log)] == ["ok", "ok"]

    again = _session(tmp_path, transport, downloader=_fake_pdf_downloader, max_calls=10)
    assert tc.run_fetch(args, again) == 0
    assert again.api_calls == 0  # 받은 PDF 는 건너뛴다


def test_fetch_logs_closed_document_and_bad_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "COUNT_DOWNLOADS", False)

    def bad_downloader(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"<html>expired</html>")
        return dest

    responses = iter([XML_DOC_CLOSED, XML_DOC])
    session = _session(tmp_path, lambda url, params: next(responses), downloader=bad_downloader)
    _write_list(session.paths, ["2013100000419", "2013100000420"])
    args = argparse.Namespace(limit=0, skip_no_doc=False, retry_failed=False)
    assert tc.run_fetch(args, session) == 0
    results = {r["심판번호"]: r["결과"] for r in _rows(session.paths.fetch_log)}
    assert results == {"2013100000419": "not_open", "2013100000420": "bad_pdf"}
    assert not any(session.paths.pdf_dir.glob("*.pdf"))
    assert tc.pending_fetch_rows(session.paths, skip_no_doc=False, retry_failed=False) == []
    assert len(tc.pending_fetch_rows(session.paths, skip_no_doc=False, retry_failed=True)) == 2


def test_fetch_hard_cap_counts_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "COUNT_DOWNLOADS", True)
    session = _session(
        tmp_path, lambda url, params: XML_DOC, downloader=_fake_pdf_downloader, max_calls=3
    )
    _write_list(session.paths, ["2013100000419", "2013100000420"])
    args = argparse.Namespace(limit=0, skip_no_doc=False, retry_failed=False)
    # 1건 = 호출 1 + 다운로드 1 → 두 번째 건의 다운로드에서 캡
    assert tc.run_fetch(args, session) == 3
    assert session.api_calls == 2 and session.downloads == 1
    assert (session.paths.pdf_dir / "2013100000419.pdf").exists()


def test_fetch_limit_and_skip_no_doc(tmp_path):
    paths_ = tc.TrialPaths(tmp_path)
    _write_list(paths_, ["1", "2", "3"])
    rows = _rows(paths_.list_csv)
    rows[1]["심결문유무"] = "N"
    tc._write_csv(paths_.list_csv, tc.LIST_COLUMNS, rows)
    pending = tc.pending_fetch_rows(paths_, skip_no_doc=True, retry_failed=False)
    assert [r["심판번호"] for r in pending] == ["1", "3"]
    assert len(tc.pending_fetch_rows(paths_, skip_no_doc=False, retry_failed=False)) == 3


# ---------------- dry-run: 실호출 0 ----------------

def test_dry_run_makes_no_network_calls(tmp_path, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise AssertionError("dry-run 에서 네트워크 접근")

    monkeypatch.setattr(kc, "_get_client", boom)
    rc = tc.main(["--data-dir", str(tmp_path), "list", "--kind", "refusal",
                  "--from", "201201", "--to", "202609", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "177개월" in out and "실호출 0회" in out and "verified=True" in out
    assert not (tmp_path / "quota.json").exists()

    _write_list(tc.TrialPaths(tmp_path), ["2013100000419"])
    rc = tc.main(["--data-dir", str(tmp_path), "fetch", "--dry-run", "--limit", "20"])
    out = capsys.readouterr().out
    assert rc == 0 and "실호출 0회" in out and "이번 대상 1건" in out
    assert not any((tmp_path / "raw_xml").glob("*")) if (tmp_path / "raw_xml").exists() else True


# ---------------- extract: 정규식 ----------------

def test_analyze_text_fame_case_matches_measured_structure():
    analysis = tc.analyze_text(TEXT_FAME)
    assert analysis["주문결과"] == "무효" and "무효로 한다" in analysis["주문"]
    assert analysis["이사건_구분"] == "등록상표"
    assert analysis["이사건_등록번호"] == "915763"
    assert analysis["이사건_지정상품"] == "상품류 구분 제18류의 가방, 핸드백, 지갑"
    assert analysis["선등록_등록번호"] == "123456|234567"
    assert analysis["판단절"].startswith("이 사건 등록상표가 구 상표법 제7조 제1항 제10호")
    assert analysis["본문_34_11"] == 1 and analysis["본문_34_7"] == 0  # 구법 10호 → 34조1항 11호
    assert analysis["본문_저명"] == 1 and analysis["본문_부정한목적"] == 0
    assert analysis["결론절추출"] == 1 and analysis["결론조문"] == "34-11:긍정"
    assert analysis["추출실패"] == 0
    assert tc.classify(analysis) == ("3", "결론에 인지도 조문 34-11")


def test_analyze_text_pure_similarity_case_is_grade_one():
    analysis = tc.analyze_text(TEXT_SIMILAR)
    assert analysis["이사건_등록번호"] == "2000001" and analysis["선등록_등록번호"] == "1000001"
    assert analysis["결론조문"] == "34-7:긍정" and analysis["본문_저명"] == 0
    assert tc.classify(analysis) == ("1", "결론 7호, 인지도 언급 없음")
    assert tc.estimate_similarity("invalidation", analysis) == ("유사", "결론 7호 긍정")


def test_analyze_text_refusal_case_ground_and_negative_conclusion():
    analysis = tc.analyze_text(TEXT_REFUSAL)
    assert analysis["주문결과"] == "취소"
    assert analysis["이사건_구분"] == "출원상표" and analysis["이사건_출원번호"] == "4020200012345"
    assert analysis["거절이유조문"] == "34-7"
    assert analysis["결론조문"] == "34-7:부정"
    assert tc.classify(analysis)[0] == "1"
    assert tc.estimate_similarity("refusal", analysis) == ("비유사", "결론 7호 부정")


def test_analyze_short_text_flags_failure():
    analysis = tc.analyze_text("")
    assert analysis["추출실패"] == 1 and analysis["결론조문"] == ""
    assert analysis["주문결과"] == "미판독"


# ---------------- 등급·유사여부 규칙 ----------------

def _analysis(conclusion: str, **flags) -> dict:
    base = {"결론조문": conclusion, "본문_저명": 0, "본문_주지": 0, "본문_부정한목적": 0,
            "주문결과": ""}
    base.update(flags)
    return base


def test_classify_rules():
    assert tc.classify(_analysis("34-7:긍정"))[0] == "1"
    assert tc.classify(_analysis("34-7:긍정", 본문_주지=1))[0] == "1"  # 문구 제외가 기본
    assert tc.classify(_analysis("34-7:긍정", 본문_주지=1), ignore_boilerplate=False) == (
        "2", "결론 7호이나 본문에 주지",
    )
    assert tc.classify(_analysis("34-7:긍정", 본문_저명주지_실질=1)) == (
        "2", "결론 7호이나 본문에 저명·주지(문구 제외 후)",
    )
    assert tc.classify(_analysis("34-7:긍정", 주문결과="각하")) == ("3", "각하(본안 판단 없음)")
    assert tc.classify(_analysis("34-7:부정", 선등록소멸취소=1))[0] == "3"
    assert tc.classify(_analysis(""))[0] == "2"
    assert tc.classify(_analysis("34-7:긍정|34-13:긍정"))[0] == "3"
    assert tc.classify(_analysis("34-12:부정"))[0] == "3"
    assert tc.classify(_analysis("33:긍정")) == ("3", "식별력 사례(33조만)")
    # '식별력' 단어 자체는 제외 사유가 아니다
    assert tc.classify(_analysis("34-7:긍정", 본문_식별력=1))[0] == "1"


def test_estimate_similarity_falls_back_to_order_by_kind():
    est = tc.estimate_similarity
    assert est("refusal", _analysis("34-7:모름", 주문결과="기각")) == ("유사", "주문 기각(refusal)")
    assert est("refusal", _analysis("34-7:모름", 주문결과="취소")) == (
        "비유사", "주문 취소(refusal)",
    )
    assert est("invalidation", _analysis("34-7:모름", 주문결과="무효"))[0] == "유사"
    assert est("invalidation", _analysis("34-7:모름", 주문결과="기각"))[0] == "비유사"
    assert tc.estimate_similarity("scope", _analysis("34-7:모름", 주문결과="불속"))[0] == "비유사"
    assert tc.estimate_similarity("scope", _analysis("34-7:모름", 주문결과="속함"))[0] == "유사"
    assert est("invalidation", _analysis("34-11:긍정", 주문결과="무효")) == ("", "")


def test_build_sheet_rows_splits_prior_marks_and_marks_missing_text():
    kinds = tc.load_kinds(KINDS)
    list_rows = [
        {"심판번호": "A", "종류": "무효", "심판상태": "심결", "심결월": "202401",
         "상표명칭": "루이", "출원번호": "4020080049731", "등록번호": "915763"},
        {"심판번호": "B", "종류": "거절결정불복", "심판상태": "심결", "심결월": "202402",
         "상표명칭": "커피", "출원번호": "4020200012345", "등록번호": ""},
    ]
    prefilter = [{"심판번호": "A", **tc.analyze_text(TEXT_FAME)}]
    rows = tc.build_sheet_rows(list_rows, prefilter, kinds, include_missing=True)
    assert [(r["심판번호"], r["상표B_번호"]) for r in rows] == [
        ("A", "123456"), ("A", "234567"), ("B", ""),
    ]
    assert rows[0]["상표A_번호"] == "915763" and rows[0]["자동등급"] == "3"
    assert "34-11" in rows[0]["조문플래그"] and "저명" in rows[0]["조문플래그"]
    assert rows[2]["등급사유"] == "텍스트 미추출" and rows[2]["상표A_번호"] == "4020200012345"
    assert len(tc.build_sheet_rows(list_rows, prefilter, kinds)) == 2  # 기본은 추출된 건만
    assert set(tc.LABEL_COLUMNS) >= {
        "유사여부_확정", "판단축_확정", "상표유형_확정", "제외사유", "메모", "family",
        "상대표장_유형", "신뢰도", "표장유사_소결", "결정축_추정", "상표유형_추정",
    }


def test_family_dedupe_keeps_first_grade_one_only():
    kinds = tc.load_kinds(KINDS)
    def row(number, title, app, plaintiff):
        return {"심판번호": number, "종류": "거절결정불복", "심판상태": "심결", "심결월": "202401",
                "상표명칭": title, "출원번호": app, "등록번호": "", "청구인": plaintiff}

    list_rows = [
        row("2022101002117", "닥터큐민", "4020210004128", "주식회사 인큐텐"),
        row("2022101002110", "Dr.Qmin", "4020210004087", "주식회사인큐텐"),
        row("2022101002011", "XSR", "", "다른회사"),
    ]
    similar = tc.analyze_text(TEXT_2024)
    numbers = ("2022101002117", "2022101002110", "2022101002011")
    prefilter = [{"심판번호": n, **similar} for n in numbers]
    rows = {r["심판번호"]: r for r in tc.build_sheet_rows(list_rows, prefilter, kinds)}
    assert rows["2022101002110"]["자동등급"] == "1"  # 심판번호 순 첫 건
    assert rows["2022101002117"]["자동등급"] == "2" and "중복" in rows["2022101002117"]["참고표시"]
    assert rows["2022101002110"]["family"] == rows["2022101002117"]["family"]
    assert rows["2022101002011"]["자동등급"] == "1"
    assert rows["2022101002011"]["family"] != rows["2022101002110"]["family"]


def test_extract_roundtrip_with_pymupdf(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = tmp_path / "pdf" / "2013100000419.pdf"
    pdf.parent.mkdir(parents=True)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Trial 2013100000419 order")
    doc.save(str(pdf))
    doc.close()
    session = tc.Session(paths=tc.TrialPaths(tmp_path), dry_run=True)
    assert tc.run_extract(argparse.Namespace(force=False), session) == 0
    text = (tmp_path / "text" / "2013100000419.txt").read_text(encoding="utf-8")
    assert "2013100000419" in text
    assert [r["심판번호"] for r in _rows(tmp_path / "prefilter.csv")] == ["2013100000419"]


# ---------------- 2단계 추가: 종류 필터 없는 list · fetch 대상 선정 · 서지상세 ----------------

XML_BIBLIO = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<response>
<header>
<requestMsgID>
</requestMsgID>
<responseTime>2026-09-30 19:26:43.2643</responseTime>
<responseMsgID>
</responseMsgID>
<successYN>Y</successYN>
<resultCode>00</resultCode>
<resultMsg>NORMAL SERVICE.</resultMsg>
</header>
<body>
<item>
<bibliographicSummaryInfo>
<appReferenceNumber>
</appReferenceNumber>
<appealFg> </appealFg>
<applicationNumber>4020210004125</applicationNumber>
<buCd>70702</buCd>
<cdDesc>거절결정불복</cdDesc>
<conclusiveDate> </conclusiveDate>
<conclusiveResultCode> </conclusiveResultCode>
<conclusiveStatusCode> </conclusiveStatusCode>
<conclusiveTrialDivision> </conclusiveTrialDivision>
<eventindication>2021년 상표등록출원 제0004125호 거절결정불복</eventindication>
<evtNo>4020210004125</evtNo>
<instanceDivision>특허심판원</instanceDivision>
<internationalRegisterNumber> </internationalRegisterNumber>
<inventionTitle> </inventionTitle>
<offcAppealFg> </offcAppealFg>
<oppositionDate> </oppositionDate>
<oppositionTrialNumber> </oppositionTrialNumber>
<originalTrialNumber>2022101002112</originalTrialNumber>
<path>MASKED</path>
<regReferenceNumber>
</regReferenceNumber>
<registerNumber> </registerNumber>
<rightDivisionCode>상표등록출원</rightDivisionCode>
<trialDecision> </trialDecision>
<trialDecisionCode>취소환송</trialDecisionCode>
<trialDecisionDate>2024.01.17</trialDecisionDate>
<trialFlag>거절결정불복</trialFlag>
<trialNumber>2022101002112</trialNumber>
<trialNumberNm>2022원2112</trialNumberNm>
<trialRequestCount>1</trialRequestCount>
<trialRequestDate>2022.11.18</trialRequestDate>
<trialRequestPurpose>원결정을 파기한다. 상표출원번호 40-2021-0004125호를 등록결정하기로 한다.
라는 취지의 심결을 구하는 바입니다.</trialRequestPurpose>
<trialStatusCode>심결</trialStatusCode>
</bibliographicSummaryInfo>
<relatedTrialNumberArray/>
<specifyCtegoryCodeInfoArray/>
<supplementaryDecisionInfo>
</supplementaryDecisionInfo>
</item>
</body>
</response>"""


def test_list_without_kind_omits_trial_desc_and_tracks_all(tmp_path):
    calls: list[dict] = []

    def transport(url, params):
        calls.append(params)
        return XML_LIST

    session = _session(tmp_path, transport, max_calls=10)
    args = _list_args(tmp_path, kind="", to="202401", allow_unverified=False)
    assert tc.run_list(args, session) == 0  # 필터 없음 → 검증 게이트 없음
    assert "trialDesc" not in calls[0] and calls[0]["tradeMark"] == "true"
    assert (session.paths.raw_xml_dir / "list_all_202401_p1.xml").exists()
    progress = json.loads(session.paths.list_progress.read_text(encoding="utf-8"))
    assert progress["all"]["202401"]["done"] is True
    assert tc.build_search_params("", "202401", 1, 500).get("trialDesc") is None


def test_select_fetch_targets_priority_doc_and_trial_filter():
    kinds = tc.load_kinds(KINDS)
    rows = [
        {"심판번호": "1", "종류": "무효", "심결문유무": "Y"},
        {"심판번호": "2", "종류": "거절결정불복", "심결문유무": "N"},
        {"심판번호": "3", "종류": "거절결정불복", "심결문유무": "Y"},
        {"심판번호": "4", "종류": "권리범위확인", "심결문유무": "Y"},
    ]
    picked = tc.select_fetch_targets(rows, 3, ["refusal", "scope"], True, set(), kinds)
    assert [r["심판번호"] for r in picked] == ["3", "2", "4"]  # 종류 우선 → Y 우선 → 원순서
    picked = tc.select_fetch_targets(rows, 0, [], False, {"4", "1"}, kinds)
    assert [r["심판번호"] for r in picked] == ["1", "4"]  # --trial 지정 건만, 원순서 유지
    plain = tc.select_fetch_targets(rows, 2, [], False, set(), kinds)
    assert [r["심판번호"] for r in plain] == ["1", "2"]


def test_parse_biblio_response_capture_sample():
    parsed = tc.parse_biblio_response(XML_BIBLIO)
    assert parsed["cdDesc"] == "거절결정불복" and parsed["trialDecisionCode"] == "취소환송"
    assert parsed["conclusiveResultCode"] == ""  # 미확정 건은 비어 있다(2026-09-30 실측 4/4)
    assert parsed["trialStatusCode"] == "심결" and parsed["trialDecisionDate"] == "2024.01.17"
    assert parsed["applicationNumber"] == "4020210004125"


def test_biblio_saves_raw_and_json_and_counts_calls(tmp_path, capsys):
    session = _session(tmp_path, lambda url, params: XML_BIBLIO, max_calls=5)
    args = argparse.Namespace(trial=["2022101002112", "2022101002112"])
    assert tc.run_biblio(args, session) == 0
    assert session.api_calls == 1  # 중복 심판번호는 한 번만
    assert (tmp_path / "raw_xml" / "biblio_2022101002112.xml").exists()
    saved = json.loads((tmp_path / "biblio" / "2022101002112.json").read_text(encoding="utf-8"))
    assert saved["trialDecisionCode"] == "취소환송"
    assert tc.summarize_calls(session.paths.calls_log) == {
        "list": 0, "doc": 0, "biblio": 1, "download": 0, "기타": 0,
    }
    assert "취소환송" in capsys.readouterr().out


# 2024-01 실제 심결문(2022원2112) 레이아웃을 본뜬 픽스처 — PyMuPDF 가 한글 사이 공백을 지우고,
# 선등록상표가 "나. 원결정이유및선등록상표" 아래 "(2)" 로 들어가며 소제목이 "(다) 소결" 형태다.
TEXT_2024 = """1/9
1. 기초사실
주       문
원결정을취소하고, 이사건출원을특허청심사관에게보내어다시심사에부친다.
청 구 취 지
주문과같다.
이       유
2/9
가. 이사건출원상표
(1) 출원번호/출원일: 제40-2021-4125호/2021. 1. 8.
(2) 표
장:
(3) 지정상품: 상품류구분제32류의커큐민성분을함유한청량음료, 커큐민을주
원료로하는숙취해소음료
나. 원결정이유및선등록상표
(1) 원결정이유
이사건출원상표는아래(2) 선등록상표와표장및지정상품이동일·유사하여상
표법제34조제1항제7호에해당하여등록받을수없다.
(2) 선등록상표
(가) 등록번호/출원일/등록일: 상표등록제1276201호/2017. 1. 19./2017. 8. 11.
(다) 지정상품
- 상품류구분제29류의가공된과일및채소
(라) 등록권리자: 주식회사가나다
2. 청구인의주장요지
이사건출원상표는선등록상표와호칭이현저하게차이가있다.
3. 이사건출원상표가상표법제34조제1항제7호에해당하는지여부
가. 판단기준
그리고상표의구성부분이요부인지여부는그부분
이주지ㆍ저명하거나일반수요자에게강한인상을주는부분인지등의요소를따져보되,
나. 구체적판단
(1) 표장의유사여부
(다) 소결
그렇다면이사건출원상표와선등록상표는전체적으로표장이유사하다고볼수없다.
다. 소결론
따라서이사건출원상표는선등록상표와표장이유사하지않으므로, 그지정상품
이유사한지여부에관하여는나아가살펴볼필요없이상표법제34조제1항제7호에
해당하지않는다.
4. 결론
그러므로원결정을취소하고, 이사건출원을다시심사에부치기로하여주문과
같이심결한다.
"""


def test_analyze_text_2024_layout_without_spaces():
    analysis = tc.analyze_text(TEXT_2024)
    assert analysis["주문결과"] == "취소"
    assert analysis["이사건_구분"] == "출원상표"
    assert analysis["이사건_출원번호"] == "4020210004125"  # 제40-2021-4125호 → 일련번호 0 채움
    assert analysis["이사건_등록번호"] == ""  # 선등록 번호를 이 사건 번호로 잘못 잡지 않는다
    assert analysis["이사건_지정상품"].startswith("상품류구분제32류의")
    assert analysis["선등록_등록번호"] == "1276201"
    assert analysis["판단절"] == "판단기준|구체적판단|소결론"
    assert analysis["거절이유조문"] == "34-7"
    assert analysis["결론조문"] == "34-7:부정"
    # 요부 판단기준 판례 문구 때문에 저명·주지 플래그가 켜진다 → 기본(문구 제외) 1등급, 원 규칙 2
    assert analysis["본문_저명"] == 1 and analysis["본문_주지"] == 1
    assert analysis["본문_저명주지_실질"] == 0
    assert tc.classify(analysis) == ("1", "결론 7호, 인지도 언급 없음")
    assert tc.classify(analysis, ignore_boilerplate=False) == ("2", "결론 7호이나 본문에 저명·주지")
    assert tc.estimate_similarity("refusal", analysis) == ("비유사", "결론 7호 부정")


TEXT_EXPIRED = TEXT_2024.replace(
    "다. 소결론\n따라서이사건출원상표는선등록상표와표장이유사하지않으므로, 그지정상품\n"
    "이유사한지여부에관하여는나아가살펴볼필요없이상표법제34조제1항제7호에\n해당하지않는다.\n",
    "다. 소결론\n선등록상표는 2023. 12. 1. 존속기간만료로소멸되었으므로이사건출원상표는더이상\n"
    "상표법제34조제1항제7호에해당하지않게되었다.\n",
)


def test_analyze_text_expired_prior_mark_and_regulation_phrasing():
    analysis = tc.analyze_text(TEXT_EXPIRED)
    assert analysis["결론조문"] == "34-7:부정"  # "더 이상 … 해당하지 않게 되었다"
    assert analysis["선등록소멸취소"] == 1
    phrased = TEXT_2024.replace(
        "상표법제34조제1항제7호에\n해당하지않는다", "상표법제34조제1항제7호의규정에해당한다"
    )
    assert tc.analyze_text(phrased)["결론조문"] == "34-7:긍정"


def test_registration_number_variants_and_conclusion_fallback():
    text = TEXT_2024.replace("상표등록제1276201호", "서비스표등록제0456789호")
    assert tc.analyze_text(text)["선등록_등록번호"] == "0456789"
    # 소결 제목 없이 판단 절 마지막 문단에 결론이 있는 경우 → 판단 절 끝에서 폴백 추출
    no_heading = TEXT_2024.replace("다. 소결론\n", "").replace("(다) 소결\n", "")
    assert tc.analyze_text(no_heading)["결론조문"] == "34-7:부정"


def test_analyze_text_madrid_subject_heading():
    text = TEXT_2024.replace(
        "가. 이사건출원상표\n(1) 출원번호/출원일: 제40-2021-4125호/2021. 1. 8.",
        "가. 이사건국제등록출원상표\n(1) 국제등록번호/국제등록일: 제1576380호/2021. 1. 8.",
    )
    analysis = tc.analyze_text(text)
    assert analysis["이사건_구분"] == "국제등록출원상표"
    assert analysis["이사건_국제등록번호"] == "1576380" and analysis["이사건_출원번호"] == ""
    assert analysis["이사건_지정상품"].startswith("상품류구분제32류")


def test_footnotes_and_international_mark_numbers():
    with_footnote = TEXT_2024.replace(
        "(다) 소결\n그렇다면",
        "(다) 소결\n1) 각주본문 상표법제34조제1항제12호에해당한다.\n2/9\n그렇다면",
    )
    assert tc.analyze_text(with_footnote)["본문_34_12"] == 0  # 각주 줄은 제거된다
    intl = TEXT_2024.replace("상표등록제1276201호", "국제상표1487520")
    assert tc.analyze_text(intl)["선등록_등록번호"] == "1487520"


def test_list_all_kinds_writes_list_all_and_reuses_saved_raw(tmp_path):
    calls: list[dict] = []
    session = _session(tmp_path, lambda url, params: calls.append(params) or XML_LIST, max_calls=10)
    (tmp_path / "raw_xml").mkdir()
    (tmp_path / "raw_xml" / "list_all_202401_p1.xml").write_text(XML_LIST, encoding="utf-8")
    args = _list_args(tmp_path, kind="", to="202402", all_kinds=True)
    assert tc.run_list(args, session) == 0
    assert [c["trialDate"] for c in calls] == ["202402"]  # 202401 은 저장된 원본 재사용
    rows = _rows(tmp_path / "list_all.csv")
    assert sorted(r["종류"] for r in rows) == ["거절결정불복", "무효"]  # 전 종류 보관
    progress = json.loads((tmp_path / "list_progress.json").read_text(encoding="utf-8"))
    assert set(progress["all_kinds"]) == {"202401", "202402"}
    assert not (tmp_path / "list.csv").exists()


def test_fetch_queue_follows_csv_order_and_skips_done(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "COUNT_DOWNLOADS", False)
    calls: list[dict] = []
    session = _session(tmp_path, lambda url, params: calls.append(params) or XML_DOC,
                       downloader=_fake_pdf_downloader, max_calls=10)
    queue = tmp_path / "queue.csv"
    tc._write_csv(queue, ["심판번호", "kind"], [{"심판번호": "3", "kind": "refusal"},
                                                {"심판번호": "1", "kind": "scope"},
                                                {"심판번호": "2", "kind": "scope"}])
    _fake_pdf_downloader("", tmp_path / "pdf" / "1.pdf")  # 이미 받은 건
    args = argparse.Namespace(limit=0, skip_no_doc=False, retry_failed=False, queue=str(queue))
    assert tc.run_fetch(args, session) == 0
    assert [c["trialNumber"] for c in calls] == ["3", "2"]


def test_select_sample_stratification_rules():
    kinds = tc.load_kinds(KINDS)
    rows = []
    for month in ("202301", "202302", "202303"):
        rows.append({"심판번호": f"s{month}", "종류": "권리범위확인(적극적)", "심결월": month,
                     "청구인": "A", "심결문유무": "Y"})
        for i in range(3):
            rows.append({"심판번호": f"i{month}{i}", "종류": "무효", "심결월": month,
                         "청구인": "B", "심결문유무": "Y"})
            rows.append({"심판번호": f"r{month}{i}", "종류": "거절결정불복", "심결월": month,
                         "청구인": "같은청구인" if i < 2 else "다른청구인", "심결문유무": "Y"})
    rows.append({"심판번호": "n1", "종류": "무효", "심결월": "202304", "청구인": "C",
                 "심결문유무": "N"})
    rows.append({"심판번호": "x1", "종류": "취소", "심결월": "202304", "청구인": "C",
                 "심결문유무": "Y"})
    quotas = {"scope": 2, "invalidation": 4, "refusal": 6}
    picked = tc.select_sample(rows, kinds, quotas, {"s202303"})
    scope = [r["심판번호"] for r in picked if r["kind"] == "scope"]
    assert scope == ["s202302", "s202301"]  # 최신순, 제외 건 빠짐
    invalid = [r["심결월"] for r in picked if r["kind"] == "invalidation"]
    assert invalid == ["202301", "202302", "202303", "202301"]  # 월 분산 라운드로빈
    refusal = [r["심판번호"] for r in picked if r["kind"] == "refusal"]
    assert refusal == ["r2023010", "r2023020", "r2023030", "r2023012", "r2023022", "r2023032"]
    assert all(r["kind"] != "" for r in picked) and "x1" not in {r["심판번호"] for r in picked}


def test_network_error_is_retried_and_each_attempt_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "NETWORK_BACKOFF_SEC", 0.0)
    attempts: list[int] = []

    def flaky(url, params):
        attempts.append(1)
        if len(attempts) == 1:
            raise kc.KiprisNetworkError("끊김")
        return XML_LIST

    session = _session(tmp_path, flaky, max_calls=10)
    assert tc.run_list(_list_args(tmp_path, kind="", to="202401"), session) == 0
    assert len(attempts) == 2 and session.api_calls == 2  # 실패한 시도도 호출로 센다

    def down(url, params):
        raise kc.KiprisNetworkError("x")

    always_down = _session(tmp_path, down)
    with pytest.raises(kc.KiprisNetworkError):
        tc.run_list(_list_args(tmp_path, kind="", to="202402"), always_down)
    assert always_down.api_calls == tc.NETWORK_RETRIES + 1



# ---------------- 4단계(2026-10-01): 권리범위확인 규칙 · 구 레이아웃 · 폴백·신뢰도 · 상대 표장 ·
# 큐레이션 보조(sheet 보존·show·status) · fetch 종류별 상한·연속 오류 중단 ----------------

# 2023당403 구조: 피청구인 답변의 "기각되어야" 가 주문 뒤 쪽 머리말·기초사실에 이어 나온다
TEXT_SCOPE = """심판번호 2023당403
사건표시 상표등록 제1697796호 권리범위확인(적극)
주       문
1. 확인대상표장은 상표등록 제1697796호의 권리범위에 속한다.
2. 심판비용은 피청구인이 부담한다.
(T)121.400-Y(09)
2/6
1. 기초사실
가. 이 사건 등록상표
(1) 등록번호/출원일/등록일/등록결정일 : 상표등록 제1697796호/2019. 10. 10./202
1. 2. 26./2020. 12. 29.
(2) 표  장 :
(3) 지정상품 : 상품류 구분 제9류의 소방용 펌프
나. 확인대상표장
(1) 구 성 :
(2) 사용업무 : 소방용 펌프
2. 당사자의 주장 및 답변
가. 청구인의 주장 요지
나. 피청구인의 답변 요지
피청구인은 이 사건 심판청구가 기각되어야 한다고 주장한다.
3. 이해관계 유무
4. 확인대상표장이 이 사건 등록상표의 권리범위에 속하는지 여부
가. 표장의 유사 여부
확인대상표장이 ‘Q-FIRE’ 부분만으로 분리관찰될 경우 이 사건 등록상표와 그 호칭이 동일하므로
이 사건 등록상표와 확인대상표장은 전체적으로 유사한 표장에 해당한다.
나. 상품의 유사 여부
이 사건 등록상표의 지정상품 중 ‘소방용 펌프’와 확인대상표장의 사용상품인 ‘소방용 펌프’는
동일한 상품이다.
다. 소결론
따라서 확인대상표장은 그 표장과 사용상품이 이 사건 등록상표의 표장 및 지정상품과 동일 또는
유사하므로 이 사건 등록상표의 권리범위에 속한다 할 것이다.
5. 결론
그러므로 이 사건 심판청구는 이유있으므로 이를 인용하고 심판비용은 피청구인의 부담으로 하기로
하여 주문과 같이 심결한다.
"""
SCOPE_SUB = (
    "따라서 확인대상표장은 그 표장과 사용상품이 이 사건 등록상표의 표장 및 지정상품과 동일 또는\n"
    "유사하므로 이 사건 등록상표의 권리범위에 속한다 할 것이다.\n"
)
SCOPE_ORDER = "1. 확인대상표장은 상표등록 제1697796호의 권리범위에 속한다.\n"


def _scope(sub: str = SCOPE_SUB, order: str = SCOPE_ORDER, extra: str = "") -> dict:
    text = TEXT_SCOPE.replace(SCOPE_SUB, sub).replace(SCOPE_ORDER, order)
    if extra:
        text = text.replace("나. 상품의 유사 여부\n", extra + "나. 상품의 유사 여부\n")
    return tc.analyze_text(text)


def test_scope_order_is_read_before_the_answer_and_graded_one():
    analysis = _scope()
    assert analysis["주문결과"] == "속함"  # 답변의 "기각되어야" 가 아니라 주문
    assert analysis["주문"].startswith("1. 확인대상표장은")
    assert analysis["판단절"] == "표장의 유사 여부|상품의 유사 여부|소결론"
    assert analysis["결론조문"] == "" and analysis["결론_신뢰도"] == ""  # 34조 결론 없음 = 정상
    assert analysis["표장유사_소결"] == "유사" and analysis["상품유사_소결"] == "유사"
    assert analysis["소결_신뢰도"] == "high" and analysis["권리범위_근거"] == ""
    assert analysis["상대표장_유형"] == "확인대상표장" and analysis["선등록_등록번호"] == ""
    assert analysis["이사건_등록번호"] == "1697796"  # 날짜 줄바꿈 "1. 2. 26." 은 제목이 아니다
    assert "호칭" in analysis["결정축_추정"] and "상품" in analysis["결정축_추정"]
    assert analysis["상표유형_추정"] == "문자"
    assert tc.classify(analysis, kind="scope") == (
        "1", "권리범위: 표장 유사 소결, 인지도 언급 없음",
    )
    assert tc.estimate_similarity("scope", analysis, "권리범위확인(적극적)") == (
        "유사", "주문 속함(scope)",
    )


def test_scope_exclusions_and_dismissal_reading():
    not_belong = "1. 확인대상표장은 상표등록 제1697796호의 권리범위에 속하지 아니한다.\n"
    applied = _scope(
        "이상에서 살펴본 바와 같이 확인대상표장은 상표법 제90조 제1항 제2호에 해당하므로 이 사건\n"
        "등록상표의 상표권 효력이 미치지 아니한다. 따라서 확인대상표장은 이 사건 등록상표와\n"
        "대비할 필요 없이 이 사건 등록상표의 권리범위에 속하지 아니한다.\n",
        not_belong,
    )
    assert applied["주문결과"] == "불속" and applied["권리범위_근거"] == "효력제한(90조)"
    assert tc.classify(applied, kind="scope") == ("3", "권리범위: 효력제한(90조)")
    assert tc.estimate_similarity("scope", applied, "권리범위확인(소극적)") == (
        "비유사", "주문 불속(scope)",
    )
    rejected = _scope(
        "이상과 같이, 확인대상표장은 이 사건 등록상표와 유사하고, 상표법 제90조 제1항 제3호에\n"
        "의하여 이 사건 등록상표의 효력이 제한되는 경우에도 해당되지 않으므로, 확인대상표장은 이\n"
        "사건 등록상표의 권리범위에 속한다 할 것이다.\n"
    )
    assert rejected["권리범위_근거"] == "" and tc.classify(rejected, kind="scope")[0] == "1"
    goods_only = _scope(
        "이상에서 본 바와 같이 확인대상표장은 그 사용상품이 이 사건 등록상표의 지정상품과 서로\n"
        "비유사하므로 표장의 유사여부에 대하여 나아가 살펴보지 않더라도 이 사건 등록상표의\n"
        "권리범위에 속하지 아니한다고 할 것이다.\n",
        "1. 이 사건 심판청구를 기각한다.\n",
    )
    assert goods_only["주문결과"] == "기각"
    assert goods_only["표장유사_소결"] == "" and goods_only["상품유사_소결"] == "비유사"
    assert tc.classify(goods_only, kind="scope") == ("3", "권리범위: 상품 비유사만")
    assert tc.estimate_similarity("scope", goods_only, "권리범위확인(적극적)") == (
        "비유사", "주문 기각(적극적 권리범위확인 → 불속)",
    )
    assert tc.estimate_similarity("scope", goods_only, "권리범위확인(소극적)") == (
        "유사", "주문 기각(소극적 권리범위확인 → 속함)",
    )
    not_use = _scope(
        "그렇다면 확인대상표장은 상담업의 방법을 나타내는 표시로서 상표적으로 사용되었다고 할 수\n"
        "없으므로 이 사건 등록상표의 권리범위에 속한다는 청구인의 주장은 이유없다.\n",
        "1. 이 사건 심판청구를 기각한다.\n",
    )
    assert tc.classify(not_use, kind="scope") == ("3", "권리범위: 상표적 사용 아님")
    plain = _scope("이상과 같이, 확인대상표장은 서비스표로 사용되었다고 할 수 없으므로, 이 사건\n"
                   "등록서비스표의 권리범위에 속하지 않는다고 할 것이다.\n", not_belong)
    assert tc.classify(plain, kind="scope") == ("3", "권리범위: 상표적 사용 아님")
    identical = _scope(
        "이상을 종합하면, 확인대상표장은 이 사건 등록상표와 표장이 동일하고, 그 사용\n"
        "상품도 지정상품과 같으므로 이 사건 등록상표의 권리범위에 속한다.\n"
    )
    assert identical["표장유사_소결"] == "유사"  # 동일은 유사에 포함
    assert tc.classify(identical, kind="scope")[0] == "1"
    dismissed = _scope(order="1. 이 사건 심판청구를 각하한다.\n")
    assert tc.classify(dismissed, kind="scope") == ("3", "각하(본안 판단 없음)")
    assert tc.estimate_similarity("scope", dismissed, "권리범위확인(적극적)") == ("", "")


def test_scope_fame_mentions_boilerplate_versus_substantive():
    boiler = _scope(extra="등록상표의 주지저명성 그리고 사용자의 의도와 사용경위 등을 종합한다.\n")
    assert boiler["본문_저명주지_실질"] == 0 and tc.classify(boiler, kind="scope")[0] == "1"
    verb = _scope(extra="부가적 부분은 표장의 동일성 여부에 영향을 주지 않는다.\n")
    assert verb["본문_주지"] == 0 and verb["본문_저명주지_실질"] == 0  # '주지 않는' 의 주지
    real = _scope(extra="이 사건 등록상표는 국내에서 주지저명한 상표이다.\n")
    assert real["본문_저명주지_실질"] == 1
    assert tc.classify(real, kind="scope") == ("2", "권리범위: 표장 유사 소결이나 저명·주지 언급")
    # 소결에 표장 판단이 없으면 판단 절 끝(앞 소제목의 결론)에서 찾는다 — 신뢰도 low
    fallback = _scope("따라서 이 사건 심판청구는 이유 없다.\n", "1. 이 사건 심판청구를 기각한다.\n")
    assert fallback["표장유사_소결"] == "유사" and fallback["소결_신뢰도"] == "low"
    text = TEXT_SCOPE.replace(SCOPE_SUB, "따라서 이 사건 심판청구는 이유 없다.\n").replace(
        "이 사건 등록상표와 확인대상표장은 전체적으로 유사한 표장에 해당한다.\n",
        "양 표장을 대비한다.\n",
    ).replace("동일한 상품이다", "같은 상품이다")
    none = tc.analyze_text(text)
    assert none["표장유사_소결"] == "" and none["소결_신뢰도"] == ""
    assert tc.classify(none, kind="scope") == ("2", "권리범위: 표장 유사 소결 없음")


# 2015당13(2017) 구 레이아웃: 번호 붙은 주문, "3. 판 단", 소결 제목 없이 다중 조문 나열 결론,
# "- 7 -" 쪽 표시, 선등록(사용)·국제상표·선출원 상대 표장
TEXT_OLD = """- 1 -
특   허   심   판   원
심       결
심판번호 2015당13
사건표시 서비스표등록 제307726호 무효
주       문
1. 이 사건 심판청구를 기각한다.
2. 심판비용은 청구인이 부담한다.
청 구 취 지
1. 서비스표등록 제41-307726호는 그 등록을 무효로 한다.
2. 심판비용은 피청구인의 부담으로 한다.
이       유
1. 기초사실
가. 이 사건 등록서비스표
(1) 등록번호/출원일/등록일 : 서비스표등록 제307726호/2013. 7. 10./2014. 12. 22.
(3) 지정서비스업 : 서비스업류 구분 제43류의 카페업
나. 선등록(사용)상표 1
(1) 등록번호/출원일/등록일 : 상표등록 제904805호/2010. 10. 26./2012. 2. 15.
다. 선등록(사용)상표 2
(1) 등록번호/출원일/등록일 : 국제상표 1048069/2010. 6. 28./2011. 12. 29.
라. 선출원서비스표
(가) 출원번호/출원일 : 제41-2012-0012345호/2012. 10. 22.
2. 양 당사자의 주장
가. 청구인의 주장
이 사건 등록서비스표는 구 상표법 제7조 제1항 제7호, 제11호 및 제12호에 해당한다고 주장한다.
3. 판 단
가. 판단기준
나. 이 사건 등록서비스표와 선등록(사용)상표들의 대비
- 7 -
(1) 표장의 구성 및 외관의 대비
양 표장은 외관이 서로 다르다.
(2) 호칭 및 관념의 대비
양 표장은 호칭 및 관념에 있어서도 서로 차이가 있다.
4. 이 사건 등록서비스표가 구 상표법 제7조 제1항 제7호, 제11호 및 제12호에 해당하는지 
여부
위에서 살펴본 내용을 종합하면, 이 사건 등록서비스표는 선등록(사용)상표들과 유사하지 않다고
판단된다.
이 사건 등록서비스표가 선등록(사용)상표들과 동일 또는 유사하지 않은 이상, 이 사건
등록서비스표는 구 상표법 제7조 제1항 제7호, 제11호 및 제12호에 해당한다고 할 수 없다.
5. 결론
그러므로 이 사건 심판청구를 기각하고 심판비용은 청구인의 부담으로 하기로 하여 주문과 같이
심결한다.
"""


def test_old_layout_numbered_order_spaced_heading_and_article_list():
    analysis = tc.analyze_text(TEXT_OLD)
    assert analysis["주문결과"] == "기각" and analysis["주문"].startswith("1. 이 사건 심판청구를")
    assert analysis["판단절"].startswith("판단기준|이 사건 등록서비스표와 선등록(사용)상표들의")
    # 구법 7·11·12호 → 34조 7·12·13호, "해당한다고 할 수 없다" 는 부정, "해당하는지 여부" 는 제외
    assert analysis["결론조문"] == "34-7:부정|34-12:부정|34-13:부정"
    assert analysis["결론_신뢰도"] == "low"  # 소결 제목 없이 판단 절 끝에서 읽음
    assert analysis["선등록_등록번호"] == "904805|1048069"
    assert analysis["상대표장_유형"] == "선등록|선출원|선사용|국제등록"
    assert analysis["선출원_출원번호"] == "4120120012345"
    assert analysis["표장유사_소결"] == "비유사" and analysis["소결_신뢰도"] == "low"
    assert analysis["결정축_추정"] == "외관|호칭|관념"
    assert tc.classify(analysis) == ("3", "결론에 인지도 조문 34-12,34-13")


def test_judgment_heading_variants_including_wrapped_lines():
    base = TEXT_OLD.replace("3. 판 단\n", "3. 상표법제7조제1항제7호해당여부\n")
    assert tc.analyze_text(base)["판단절"].startswith("판단기준|")
    wrapped = TEXT_OLD.replace(
        "3. 판 단\n", "3. 이 사건 등록서비스표가 구 상표법 제7조 제1항 제7호\n에 해당되는지 여부\n"
    )
    assert tc.analyze_text(wrapped)["판단절"].startswith("판단기준|")
    assert tc.analyze_text(TEXT_OLD.replace("3. 판 단\n", "3. 거절결정의 당부\n"))["판단절"]
    # "3. 이해관계 여부"·"3. 이 사건 심판청구의 적법 여부" 는 판단 절이 아니다
    guarded = TEXT_OLD.replace(
        "3. 판 단\n", "3. 이 사건 심판청구의 적법 여부\n가. 적법하다.\n3. 판 단\n"
    )
    assert tc.analyze_text(guarded)["판단절"].startswith("판단기준|")


def test_old_layout_prior_application_clause_and_missing_ground():
    text = TEXT_OLD.replace(
        "이 사건 등록서비스표가 선등록(사용)상표들과 동일 또는 유사하지 않은 이상, 이 사건\n"
        "등록서비스표는 구 상표법 제7조 제1항 제7호, 제11호 및 제12호에 해당한다고 할 수 없다.\n",
        "다. 소결론\n그렇다면 이 사건 등록서비스표는 선등록서비스표들과 그 표장이 비유사하므로,\n"
        "나아가 지정서비스업의 유사여부에 대하여 살펴보지 않더라도 구 상표법 제7조 제1항 제7호 및\n"
        "제8조\n"
        "제1항에 해당하는 무효사유가 존재하지 아니한다.\n",
    )
    analysis = tc.analyze_text(text)
    assert analysis["결론조문"] == "34-7:부정|35-1:부정" and analysis["결론_신뢰도"] == "high"
    assert tc.classify(analysis) == ("1", "결론 7호, 인지도 언급 없음")
    assert tc.estimate_similarity("invalidation", analysis) == ("비유사", "결론 7호 부정")
    # 선출원 저촉(35-1 = 구 8조1항)만 결론이면 7호와 같이: 표장 소결이 있으면 1등급, 추정은 7호 규칙
    only_35 = tc.analyze_text(text.replace("제7조 제1항 제7호 및\n제8조\n제1항", "제8조\n제1항"))
    assert only_35["결론조문"] == "35-1:부정"
    assert tc.classify(only_35) == (
        "1", "결론 35-1(선출원 저촉), 표장 비유사 소결, 인지도 언급 없음",
    )
    assert tc.estimate_similarity("invalidation", only_35) == (
        "비유사", "결론 35-1(선출원 저촉) 부정",
    )


def test_conclusion_confidence_and_mark_verdict_inference():
    with_heading = tc.analyze_text(TEXT_2024)
    assert with_heading["결론_신뢰도"] == "high" and with_heading["표장유사_소결"] == "비유사"
    no_heading = tc.analyze_text(TEXT_2024.replace("다. 소결론\n", "").replace("(다) 소결\n", ""))
    assert no_heading["결론조문"] == "34-7:부정" and no_heading["결론_신뢰도"] == "low"
    # 조문 없이 표장 소결만 있는 거절결정불복(거절이유 7호) → 7호로 추론, 신뢰도 low
    inferred = tc.analyze_text(TEXT_2024.replace(
        "다. 소결론\n따라서이사건출원상표는선등록상표와표장이유사하지않으므로, 그지정상품\n"
        "이유사한지여부에관하여는나아가살펴볼필요없이상표법제34조제1항제7호에\n해당하지않는다.\n",
        "다. 소결론\n따라서이사건출원상표는선등록상표와표장이비유사하다.\n",
    ))
    assert inferred["결론조문"] == "34-7:부정" and inferred["결론추론"] == "표장 소결 → 7호"
    assert tc.classify(inferred) == ("1", "결론 7호, 인지도 언급 없음 (표장 소결 추론, 신뢰도 low)")
    assert tc.estimate_similarity("refusal", inferred) == (
        "비유사", "결론 7호 부정 — 표장 소결 추론",
    )
    # 당사자 주장·"해당한다는 이유로 거절한 원결정은 … 타당하지 아니하다" 판독
    reversed_ground = tc.analyze_text(TEXT_2024.replace(
        "상표법제34조제1항제7호에\n해당하지않는다.", "상표법제34조제1항제7호에해당한다는이유로\n"
        "그등록을거절한원결정은더이상타당하지아니하다.",
    ))
    assert reversed_ground["결론조문"] == "34-7:부정"
    claim = tc.analyze_text(TEXT_2024.replace(
        "다. 소결론\n", "다. 소결론\n청구인은상표법제34조제1항제7호에해당한다고주장한다.\n"
    ))
    assert claim["결론조문"] == "34-7:부정"  # 주장 문장은 건너뛴다


def test_estimate_marks_goods_only_negative_and_mismatch():
    goods_negative = tc.estimate_similarity("refusal", {
        "결론조문": "34-7:부정", "주문결과": "취소", "표장유사_소결": "", "상품유사_소결": "비유사",
    })
    assert goods_negative == ("", "결론 7호 부정은 상품 비유사 때문 — 표장 판단 없음")
    corrected = tc.estimate_similarity("refusal", {
        "결론조문": "34-7:부정", "주문결과": "취소", "표장유사_소결": "유사",
        "상품유사_소결": "비유사",
    })
    assert corrected == ("유사", "소결 표장 유사(상품 비유사로 결론 7호 부정)")
    mismatch = tc.estimate_similarity("invalidation", {
        "결론조문": "34-7:긍정", "주문결과": "무효", "표장유사_소결": "비유사", "상품유사_소결": "",
    })
    assert mismatch == ("유사", "결론 7호 긍정 · 소결 표장 비유사와 불일치")
    assert tc.estimate_similarity("invalidation", _analysis("34-7:모름", 주문결과="일부무효")) == (
        "유사", "주문 일부무효(invalidation)",
    )


# 추출 순서가 뒤바뀐 심결문: 주문 제목 뒤에 쪽 머리말·기초사실, 주문 문장은 그 뒤, 청구취지는 다음
TEXT_REORDERED = """주       문
(T)111.270-V(03)
2/24
1. 기초사실
가. 이 사건 등록상표
(1) 등록번호/출원일 : 상표등록 제1674764호/2020. 8. 18.
(3) 지정상품 : 상품류 구분 제3류의 화장품
나. 선등록상표
(1) 등록번호 : 상표등록 제1000002호
1. 이 사건 심판청구를 기각한다.
2. 심판비용은 청구인이 부담한다.
청 구 취 지
1. 상표등록 제1674764호는 그 등록을 무효로 한다.
2. 심판비용은 피청구인이 부담한다.
이       유
2. 당사자의 주장
3. 판단
가. 판단기준
나. 소결론
이 사건 등록상표는 선등록상표와 표장이 비유사하므로 상표법 제34조 제1항 제7호에 해당하지
아니한다.
4. 결론
그러므로 이 사건 심판청구는 이유 없으므로 이를 기각한다.
"""


def test_reordered_order_block_partial_invalidation_and_cancelled_prior_mark():
    analysis = tc.analyze_text(TEXT_REORDERED)
    assert analysis["주문"].startswith("1. 이 사건 심판청구를 기각한다.")
    assert analysis["주문결과"] == "기각"
    assert analysis["이사건_등록번호"] == "1674764" and analysis["선등록_등록번호"] == "1000002"
    assert analysis["결론조문"] == "34-7:부정" and tc.classify(analysis)[0] == "1"
    partial = tc.analyze_text(TEXT_REORDERED.replace(
        "1. 이 사건 심판청구를 기각한다.\n",
        "1. 상표등록 제1674764호의 지정상품 중 ‘화장품’의 등록을 무효로 하고, 나머지 청구는\n"
        "기각한다.\n",
    ).replace("이유 없으므로 이를 기각한다", "일부 이유 있다"))
    assert partial["주문결과"] == "일부무효"
    gone = tc.analyze_text(TEXT_REORDERED.replace(
        "이 사건 등록상표는 선등록상표와 표장이 비유사하므로 상표법 제34조 제1항 제7호에 해당하지\n"
        "아니한다.\n",
        "선등록상표는 등록무효심결이 확정되어 선원의 지위를 소급적으로 상실하였으므로 이 사건\n"
        "등록상표는 상표법 제34조 제1항 제7호에 해당하지 아니한다.\n",
    ))
    assert gone["선등록소멸취소"] == 1  # 무효심판 기각이라도 선등록상표 소멸이면 유사 판단 없음
    assert tc.classify(gone) == ("3", "유사 판단 없음(선등록상표 소멸·무효로 취소)")


# ---- 큐레이션 보조: sheet 가 사람 열을 보존, show, status ----

def _list_row(number: str, desc: str, title: str = "X", plaintiff: str = "주식회사 갑") -> dict:
    return {"심판번호": number, "종류": desc, "심판상태": "심결", "심결월": "202401",
            "상표명칭": title, "출원번호": "", "등록번호": "", "청구인": plaintiff,
            "피청구인": "을"}


def test_sheet_keeps_human_columns_across_regeneration(tmp_path, capsys):
    kinds = tc.load_kinds(KINDS)
    list_rows = [_list_row("A", "무효", "루이"), _list_row("S", "권리범위확인(적극적)", "Q-FIRE")]
    prefilter = [{"심판번호": "A", **tc.analyze_text(TEXT_FAME)},
                 {"심판번호": "S", **tc.analyze_text(TEXT_SCOPE)}]
    rows = tc.build_sheet_rows(list_rows, prefilter, kinds)
    assert [(r["심판번호"], r["상표B_번호"]) for r in rows] == [
        ("A", "123456"), ("A", "234567"), ("S", ""),
    ]
    assert rows[2]["자동등급"] == "1" and rows[2]["신뢰도"] == "high"
    assert rows[2]["상대표장_유형"] == "확인대상표장" and rows[2]["유사여부_추정"] == "유사"
    previous = [
        {"심판번호": "A", "상표B_번호": "123456", "유사여부_확정": "유사", "판단축": "외관"},
        {"심판번호": "A", "상표B_번호": "234567", "유사여부_확정": "비유사", "판단축": "호칭",
         "제외사유": "", "메모": "둘째 선등록만 봄"},  # 4단계 전 열 이름(판단축)
        {"심판번호": "S", "상표B_번호": "9", "유사여부_확정": "유사", "상표유형_확정": "문자",
         "제외사유": "", "메모": ""},  # 이전 행이 하나뿐이면 상표B 가 달라도 심판번호로 옮긴다
        {"심판번호": "Z", "상표B_번호": "", "유사여부_확정": "유사"},  # 사라진 건은 버린다
    ]
    assert tc.merge_human_columns(rows, previous) == 3
    assert rows[0]["유사여부_확정"] == "유사" and rows[0]["판단축_확정"] == "외관"
    assert rows[1]["유사여부_확정"] == "비유사" and rows[1]["판단축_확정"] == "호칭"
    assert rows[1]["메모"] == "둘째 선등록만 봄"
    assert rows[2]["유사여부_확정"] == "유사" and rows[2]["상표유형_확정"] == "문자"
    # 이전 행이 여럿인데 상표B 가 모두 다르면 어느 판단인지 몰라 비워 둔다
    fresh = tc.build_sheet_rows(list_rows, prefilter, kinds)
    assert tc.merge_human_columns(fresh, [
        {"심판번호": "A", "상표B_번호": "1", "유사여부_확정": "유사"},
        {"심판번호": "A", "상표B_번호": "2", "유사여부_확정": "비유사"},
    ]) == 0

    # 파일 왕복: labels.csv 를 사람 열이 채워진 상태로 두고 sheet 를 다시 돌린다
    paths_ = tc.TrialPaths(tmp_path)
    tc._write_csv(paths_.list_csv, tc.LIST_COLUMNS, list_rows)
    tc._write_csv(paths_.prefilter_csv, tc.PREFILTER_COLUMNS, prefilter)
    tc._write_csv(paths_.labels_csv, tc.LABEL_COLUMNS, rows)
    session = tc.Session(paths=paths_, dry_run=True)
    assert tc.run_sheet(argparse.Namespace(kinds_config=KINDS), session) == 0
    again = _rows(paths_.labels_csv)
    assert [r["유사여부_확정"] for r in again] == ["유사", "비유사", "유사"]
    assert again[2]["상표유형_확정"] == "문자" and again[1]["판단축_확정"] == "호칭"
    assert "사람 열 보존 3행" in capsys.readouterr().out
    assert tc.curation_progress(again).startswith("큐레이션: 1등급 1건 중 유사여부_확정 1건(100%)")
    assert "전체 확정 2/2건 · 제외사유 0건" in tc.curation_progress(again)


def test_show_prints_order_judgment_and_auto_verdict(tmp_path, capsys):
    paths_ = tc.TrialPaths(tmp_path)
    paths_.text_dir.mkdir(parents=True)
    (paths_.text_dir / "2023100000403.txt").write_text(TEXT_SCOPE, encoding="utf-8")
    tc._write_csv(paths_.list_csv, tc.LIST_COLUMNS,
                  [_list_row("2023100000403", "권리범위확인(적극적)", "Q-FIRE")])
    session = tc.Session(paths=paths_, dry_run=True)
    args = argparse.Namespace(kinds_config=KINDS, trial=["2023100000403", "9999"])
    assert tc.run_show(args, session) == 1  # 9999 는 텍스트 없음
    out = capsys.readouterr()
    assert "## 2023100000403 · 권리범위확인(적극적)" in out.out
    assert "→ 주문결과 속함" in out.out and "4. 확인대상표장이 이 사건 등록상표의" in out.out
    assert "- 등급 1 — 권리범위: 표장 유사 소결, 인지도 언급 없음 (신뢰도 high)" in out.out
    assert "- 유사여부 추정 유사 — 주문 속함(scope)" in out.out
    assert "상대 표장 확인대상표장" in out.out and "(T)121" not in out.out
    assert "9999" in out.err


# ---- fetch: 종류별 상한 · 계획표 · 연속 오류 중단 ----

def test_parse_kind_caps_and_capped_selection():
    assert tc.parse_kind_caps("scope=280, invalidation=100,refusal=70") == {
        "scope": 280, "invalidation": 100, "refusal": 70,
    }
    assert tc.parse_kind_caps("") == {}
    for bad in ("scope", "scope=x", "scope=-1"):
        with pytest.raises(ValueError):
            tc.parse_kind_caps(bad)
    kinds = tc.load_kinds(KINDS)
    rows = [{"심판번호": str(i), "kind": k, "종류": "", "심결문유무": "Y"}
            for i, k in enumerate("scope scope invalidation refusal scope invalidation".split())]
    picked = tc.select_fetch_targets(rows, 0, ["invalidation", "scope"], False, set(), kinds,
                                     {"scope": 2, "invalidation": 1})
    # 우선순위 정렬 → 종류별 상한(refusal 은 상한 없음)
    assert [r["심판번호"] for r in picked] == ["2", "0", "1", "3"]
    assert len(tc.select_fetch_targets(rows, 3, [], False, set(), kinds, {"scope": 1})) == 3


def test_fetch_queue_plan_and_consecutive_error_stop(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tc, "COUNT_DOWNLOADS", True)
    monkeypatch.setattr(tc, "NETWORK_BACKOFF_SEC", 0.0)
    queue = tmp_path / "queue.csv"
    tc._write_csv(queue, ["심판번호", "kind", "종류"], [
        {"심판번호": str(i), "kind": "scope" if i < 6 else "refusal", "종류": ""} for i in range(8)
    ])
    args = argparse.Namespace(limit=0, skip_no_doc=False, retry_failed=False, queue=str(queue),
                              kind_priority="scope,refusal", kind_cap="scope=6,refusal=1")
    session = _session(tmp_path, lambda url, params: XML_DOC, downloader=_fake_pdf_downloader,
                       dry_run=True, max_calls=12)
    assert tc.run_fetch(args, session) == 0
    out = capsys.readouterr().out
    assert "이번 대상 7건" in out and "refusal 1건(호출 2) · scope 6건(호출 12)" in out
    assert "예상 호출 14회 / 하드캡 12회" in out and "하드캡에서 중단된다" in out

    def failing(url, params):
        raise kc.KiprisError("KIPRIS 오류 resultCode=22 한도 초과", result_code="22")

    session = _session(tmp_path, failing, downloader=_fake_pdf_downloader, max_calls=100)
    assert tc.run_fetch(args, session) == 5  # 연속 5회 오류 → 중단
    assert session.api_calls == 5 and session.downloads == 0
    log = _rows(session.paths.fetch_log)
    assert [r["결과"] for r in log] == ["error"] * 5 and log[0]["파일명"] == "KiprisError/22"
    assert "오류 응답 연속 5회" in capsys.readouterr().out

    attempts: list[str] = []

    def flaky(url, params):
        attempts.append(params["trialNumber"])
        if len(attempts) <= 2:
            raise kc.KiprisProtocolError("깨진 응답")
        return XML_DOC

    retry = argparse.Namespace(**{**vars(args), "retry_failed": True})
    session = _session(tmp_path, flaky, downloader=_fake_pdf_downloader, max_calls=100)
    assert tc.run_fetch(retry, session) == 0  # 2회 실패 뒤 성공 → 연속 카운터 초기화, 계속 진행
    assert session.downloads == 5
    assert len([r for r in _rows(session.paths.fetch_log) if r["결과"] == "ok"]) == 5

    def over_budget(url, params):
        raise kc.CallBudgetExceeded("예산 초과")

    session = _session(tmp_path, over_budget, downloader=_fake_pdf_downloader, max_calls=100)
    with pytest.raises(kc.CallBudgetExceeded):  # 예산 초과는 즉시 중단(main 이 exit 4)
        tc.run_fetch(argparse.Namespace(**{**vars(args), "retry_failed": True}), session)


# ---------------- 4단계 보강(2026-10-01): 35-1 을 7호처럼 · 상대 표장 번호 후보 · 큐레이션 큐 ----

def test_prior_application_conflict_is_graded_like_article_seven():
    text = TEXT_OLD.replace(
        "라. 선출원서비스표\n(가) 출원번호/출원일 : 제41-2012-0012345호/2012. 10. 22.\n", ""
    ).replace(
        "이 사건 등록서비스표가 선등록(사용)상표들과 동일 또는 유사하지 않은 이상, 이 사건\n"
        "등록서비스표는 구 상표법 제7조 제1항 제7호, 제11호 및 제12호에 해당한다고 할 수 없다.\n",
        "다. 소결론\n그렇다면 이 사건 등록서비스표는 선등록서비스표와 그 표장이 비유사하므로\n"
        "구 상표법 제8조 제1항에 해당하는 무효사유가 존재하지 아니한다.\n",
    )
    analysis = tc.analyze_text(text)
    assert analysis["결론조문"] == "35-1:부정" and analysis["표장유사_소결"] == "비유사"
    assert analysis["상대표장_유형"] == "선등록|선출원|선사용|국제등록"  # 제목이 없어도 선출원 추가
    assert tc.classify(analysis) == (
        "1", "결론 35-1(선출원 저촉), 표장 비유사 소결, 인지도 언급 없음",
    )
    assert tc.estimate_similarity("invalidation", analysis) == (
        "비유사", "결론 35-1(선출원 저촉) 부정",
    )
    # 표장 소결이 없으면 검토(2등급), 본문에 부정한 목적이 있어도 2등급
    plain = tc.analyze_text(text.replace(
        "그렇다면 이 사건 등록서비스표는 선등록서비스표와 그 표장이 비유사하므로\n",
        "그렇다면 이 사건 등록서비스표는\n",
    ).replace("양 표장은 외관이 서로 다르다.\n", "").replace(
        "양 표장은 호칭 및 관념에 있어서도 서로 차이가 있다.\n", ""
    ).replace("이 사건 등록서비스표는 선등록(사용)상표들과 유사하지 않다고\n판단된다.\n", ""))
    assert plain["표장유사_소결"] == ""
    assert tc.classify(plain) == ("2", "결론 35-1(선출원 저촉)이나 표장 소결 없음")
    fame = tc.analyze_text(
        text.replace("가. 판단기준\n", "가. 판단기준\n부정한 목적이 인정된다.\n")
    )
    assert tc.classify(fame) == ("2", "결론 35-1(선출원 저촉)이나 본문에 부정한 목적")


TEXT_PROSE = """주       문
1. 이 사건 심판청구를 기각한다.
2. 심판비용은 청구인이 부담한다.
이       유
1. 이 사건 등록상표(상표등록 제1000001호, 지정상품 제30류 커피)는 2020. 1. 1. 등록되었다.
청구인은 이 사건 등록상표가 선등록상표(상표등록 제1234567호)와 유사하다고 주장하고, 선출원상표
제40-2012-12345호와 국제등록 제987654호도 인용한다.
2. 판단
가. 판단기준
나. 대비
이 사건 등록상표와 선등록상표는 외관·호칭·관념이 서로 달라 비유사하다.
""" + "무관한 내용. " * 60 + """
위 등록 제5555555호는 건외 상표이다.
다. 소결론
따라서 이 사건 등록상표는 상표법 제34조 제1항 제7호에 해당하지 아니한다.
3. 결론
그러므로 이 사건 심판청구를 기각한다.
"""


def test_candidate_counterpart_numbers_recovered_from_prose():
    analysis = tc.analyze_text(TEXT_PROSE)
    assert analysis["선등록_등록번호"] == "" and analysis["상대표장_유형"] == ""  # 제목 없음
    # 이 사건 번호 제외, 선등록·선출원·인용 근처(±200자)만, 멀리 떨어진 건외 번호는 제외
    assert analysis["상대표장_번호_후보"] == "1234567;4020120012345;987654"
    assert tc.candidate_counterpart_numbers("선등록상표 출원 제40-2020-0000001호", set()) == [
        "4020200000001",
    ]
    assert tc.candidate_counterpart_numbers("상표등록 제1000호와 대비", {"1000"}) == []
    regular = tc.analyze_text(TEXT_FAME)
    assert regular["선등록_등록번호"] == "123456|234567" and regular["상대표장_번호_후보"] == ""
    kinds = tc.load_kinds(KINDS)
    rows = tc.build_sheet_rows([_list_row("P", "무효")], [{"심판번호": "P", **analysis}], kinds)
    assert rows[0]["상표B_번호"] == "" and rows[0]["상대표장_번호_후보"].startswith("1234567;")


def test_curation_queue_order_and_show_next(tmp_path, capsys):
    kinds = tc.load_kinds(KINDS)
    scope = tc.analyze_text(TEXT_SCOPE)
    scope_low = dict(scope, 소결_신뢰도="low")
    fame = dict(scope, 본문_저명주지_실질=1)
    refusal = tc.analyze_text(TEXT_2024)
    invalid = tc.analyze_text(TEXT_SIMILAR)
    prose = tc.analyze_text(TEXT_PROSE)
    list_rows = [
        _list_row("S1", "권리범위확인(적극적)", "A", "갑1"),
        _list_row("S2", "권리범위확인(소극적)", "B", "갑2"),
        _list_row("S3", "권리범위확인(적극적)", "C", "갑3"), _list_row("R1", "거절결정불복", "D"),
        _list_row("I1", "무효", "E"), _list_row("I2", "무효", "E2"),
        _list_row("P1", "무효", "F", "병"),
        # 같은 청구인·피청구인·등록상표를 둔 권리범위확인 쌍둥이 사건은 중복, 상대가 다르면 별건
        _list_row("S4", "권리범위확인(적극적)", "A", "갑1"),
        {**_list_row("S5", "권리범위확인(적극적)", "A", "갑1"), "피청구인": "정"},
    ]
    prefilter = [
        {"심판번호": "S1", **scope_low}, {"심판번호": "S2", **scope}, {"심판번호": "S3", **fame},
        {"심판번호": "R1", **refusal}, {"심판번호": "I1", **invalid}, {"심판번호": "I2", **invalid},
        {"심판번호": "P1", **prose}, {"심판번호": "S4", **scope}, {"심판번호": "S5", **scope},
    ]
    rows = tc.build_sheet_rows(list_rows, prefilter, kinds)
    by = {r["심판번호"]: r for r in rows}
    assert by["I2"]["등급사유"].startswith("family 중복")  # 같은 청구인·같은 선등록 → 큐에서 제외
    assert by["S4"]["등급사유"].startswith("family 중복(첫 건 S1)") and by["S5"]["자동등급"] == "1"
    queue = tc.build_curation_queue(rows, kinds)
    assert [q["심판번호"] for q in queue] == ["S2", "S5", "S1", "R1", "I1", "P1", "S3"]
    assert [q["순번"] for q in queue] == [1, 2, 3, 4, 5, 6, 7]
    assert queue[1]["신뢰도"] == "high" and queue[2]["신뢰도"] == "low"
    assert queue[4]["상대표장_번호"] == "1000001"
    assert queue[5]["상대표장_번호"].startswith("1234567;")
    assert queue[6]["등급사유"] == "권리범위: 표장 유사 소결이나 저명·주지 언급"
    assert set(queue[0]) == set(tc.CURATION_COLUMNS)

    paths_ = tc.TrialPaths(tmp_path)
    paths_.text_dir.mkdir(parents=True)
    for number, text in (("S2", TEXT_SCOPE), ("S5", TEXT_SCOPE), ("R1", TEXT_2024)):
        (paths_.text_dir / f"{number}.txt").write_text(text, encoding="utf-8")
    tc._write_csv(paths_.list_csv, tc.LIST_COLUMNS, list_rows)
    tc._write_csv(paths_.prefilter_csv, tc.PREFILTER_COLUMNS, prefilter)
    session = tc.Session(paths=paths_, dry_run=True)
    assert tc.run_sheet(argparse.Namespace(kinds_config=KINDS), session) == 0
    assert "큐레이션 큐 7건(1등급 6 · 권리범위 저명·주지 언급 1)" in capsys.readouterr().out
    assert [q["심판번호"] for q in _rows(paths_.curation_queue)][:2] == ["S2", "S5"]

    args = argparse.Namespace(kinds_config=KINDS, trial=[], next=True)
    assert tc.run_show(args, session) == 0
    out = capsys.readouterr().out
    assert out.startswith("큐 1/7 · 권리범위: 표장 유사 소결, 인지도 언급 없음")
    assert "## S2 ·" in out
    labels = _rows(paths_.labels_csv)
    for row in labels:
        if row["심판번호"] == "S2":
            row["유사여부_확정"] = "유사"
    tc._write_csv(paths_.labels_csv, tc.LABEL_COLUMNS, labels)
    assert tc.run_show(args, session) == 0
    assert "큐 2/7" in capsys.readouterr().out  # S2 확정 → 다음은 S5
    assert tc.run_show(argparse.Namespace(kinds_config=KINDS, trial=[], next=False), session) == 2


def test_show_marks_fallback_conclusion_sentence(tmp_path, capsys):
    no_heading = TEXT_2024.replace("다. 소결론\n", "").replace("(다) 소결\n", "")
    paths_ = tc.TrialPaths(tmp_path)
    paths_.text_dir.mkdir(parents=True)
    (paths_.text_dir / "X.txt").write_text(no_heading, encoding="utf-8")
    session = tc.Session(paths=paths_, dry_run=True)
    show_x = argparse.Namespace(kinds_config=KINDS, trial=["X"], next=False)
    assert tc.run_show(show_x, session) == 0
    out = capsys.readouterr().out
    assert "### 판단 절 (>> 폴백으로 읽은 결론 문장)" in out
    assert ">> 이유사한지여부에관하여는나아가살펴볼필요없이상표법제34조제1항제7호에" in out
    assert ">> 따라서이사건출원상표는선등록상표와표장이유사하지않으므로, 그지정상품" in out
    assert "(신뢰도 low)" in out
    (paths_.text_dir / "Y.txt").write_text(TEXT_2024, encoding="utf-8")
    show_y = argparse.Namespace(kinds_config=KINDS, trial=["Y"], next=False)
    assert tc.run_show(show_y, session) == 0
    assert ">> " not in capsys.readouterr().out  # 소결 제목 아래서 읽으면 표시 없음


# ---------------- 큐레이션 라벨 도구(feat/trials-label): label·confirm·show --batch·review·
# sample --n·status 일치율 ----------------

def _curation_fixture(tmp_path):
    """list·prefilter·텍스트·labels.csv·curation_queue.csv 를 갖춘 데이터 디렉터리.
    큐 순서: S2·S5·S1·R1·I1·P1·S3."""
    kinds = tc.load_kinds(KINDS)
    scope = tc.analyze_text(TEXT_SCOPE)
    list_rows = [
        _list_row("S1", "권리범위확인(적극적)", "A", "갑1"),
        _list_row("S2", "권리범위확인(소극적)", "B", "갑2"),
        _list_row("S3", "권리범위확인(적극적)", "C", "갑3"), _list_row("R1", "거절결정불복", "D"),
        _list_row("I1", "무효", "E"), _list_row("P1", "무효", "F", "병"),
        {**_list_row("S5", "권리범위확인(적극적)", "A", "갑1"), "피청구인": "정"},
    ]
    prefilter = [
        {"심판번호": "S1", **dict(scope, 소결_신뢰도="low")}, {"심판번호": "S2", **scope},
        {"심판번호": "S3", **dict(scope, 본문_저명주지_실질=1)},
        {"심판번호": "R1", **tc.analyze_text(TEXT_2024)},
        {"심판번호": "I1", **tc.analyze_text(TEXT_SIMILAR)},
        {"심판번호": "P1", **tc.analyze_text(TEXT_PROSE)}, {"심판번호": "S5", **scope},
    ]
    paths_ = tc.TrialPaths(tmp_path)
    paths_.text_dir.mkdir(parents=True)
    for number, text in (("S2", TEXT_SCOPE), ("S5", TEXT_SCOPE), ("S1", TEXT_SCOPE),
                         ("R1", TEXT_2024), ("I1", TEXT_SIMILAR)):
        (paths_.text_dir / f"{number}.txt").write_text(text, encoding="utf-8")
    tc._write_csv(paths_.list_csv, tc.LIST_COLUMNS, list_rows)
    tc._write_csv(paths_.prefilter_csv, tc.PREFILTER_COLUMNS, prefilter)
    assert tc.run_sheet(argparse.Namespace(kinds_config=KINDS), tc.Session(paths=paths_)) == 0
    return paths_, kinds


def _label_cli(tmp_path, *args: str) -> int:
    return tc.main(["--data-dir", str(tmp_path), *args])


def _labels_by_trial(paths_) -> dict[str, dict]:
    rows = _rows(paths_.labels_csv)
    return {row["심판번호"]: row for row in rows}


def test_label_records_columns_and_validates_inputs(tmp_path, capsys):
    paths_, _ = _curation_fixture(tmp_path)
    before = _labels_by_trial(paths_)["S2"]
    evidence = '확인대상표장은 "Q-FIRE" 부분만으로, 호칭이 동일하므로 유사하다'  # 따옴표·쉼표 보존
    assert _label_cli(tmp_path, "label", "S2", "유사", "--axis", "호칭,외관", "--type", "문자",
                      "--memo", "요부 Q-FIRE", "--source", "human", "--evidence", evidence,
                      "--confidence", "high") == 0
    row = _labels_by_trial(paths_)["S2"]
    assert row["유사여부_확정"] == "유사" and row["판단축_확정"] == "외관|호칭"
    assert row["상표유형_확정"] == "문자" and row["메모"] == "요부 Q-FIRE" and row["제외사유"] == ""
    assert row["라벨출처"] == "human" and row["확인여부"] == "Y" and row["확신도"] == "high"
    assert row["근거문장"] == evidence
    assert {k: v for k, v in row.items() if k not in tc.PRESERVED_COLUMNS} == {
        k: v for k, v in before.items() if k not in tc.PRESERVED_COLUMNS
    }  # 다른 열은 그대로
    assert "라벨 기록: S2 1행" in capsys.readouterr().out
    # 재실행으로 수정(메모는 생략하면 유지), 제외는 --reason 필수
    assert _label_cli(tmp_path, "label", "S2", "제외", "--reason", "인지도", "--source", "human",
                      "--evidence", "저명상표", "--confidence", "low") == 0
    row = _labels_by_trial(paths_)["S2"]
    assert row["유사여부_확정"] == "제외" and row["제외사유"] == "인지도"
    assert row["메모"] == "요부 Q-FIRE" and row["판단축_확정"] == "" and row["확신도"] == "low"
    snapshot = paths_.labels_csv.read_bytes()
    bad = [
        ["label", "S2", "애매", "--source", "human", "--evidence", "x", "--confidence", "high"],
        ["label", "S2", "제외", "--source", "human", "--evidence", "x", "--confidence", "high"],
        ["label", "S2", "유사", "--reason", "기타", "--source", "human", "--evidence", "x",
         "--confidence", "high"],
        ["label", "S2", "유사", "--axis", "색깔", "--source", "human", "--evidence", "x",
         "--confidence", "high"],
        ["label", "S2", "유사", "--type", "입체", "--source", "human", "--evidence", "x",
         "--confidence", "high"],
        ["label", "S2", "유사", "--source", "human", "--confidence", "high"],  # evidence 없음
        ["label", "S2", "유사", "--source", "human", "--evidence", "x", "--confidence", "중간"],
        ["label", "S2", "유사", "--source", "기계", "--evidence", "x", "--confidence", "high"],
        ["label", "S2", "유사", "--pass", "c", "--source", "llm", "--evidence", "x",
         "--confidence", "high"],
    ]
    for argv in bad:
        assert _label_cli(tmp_path, *argv) == 2, argv
    assert _label_cli(tmp_path, "label", "ZZ", "유사", "--source", "human", "--evidence", "x",
                      "--confidence", "high") == 1
    assert _label_cli(tmp_path, "label", "S2", "유사", "--b", "999", "--source", "human",
                      "--evidence", "x", "--confidence", "high") == 1
    assert paths_.labels_csv.read_bytes() == snapshot  # 오류 때는 파일을 건드리지 않는다
    assert "허용값" in capsys.readouterr().err


def test_llm_cannot_overwrite_confirmed_rows_and_undo_clears(tmp_path, capsys):
    paths_, _ = _curation_fixture(tmp_path)
    common = ["--evidence", "표장이 유사하다", "--confidence", "high"]
    assert _label_cli(tmp_path, "label", "S2", "유사", "--source", "human", *common) == 0
    snapshot = paths_.labels_csv.read_bytes()
    assert _label_cli(tmp_path, "label", "S2", "비유사", "--source", "llm", *common) == 3
    assert "[거부]" in capsys.readouterr().err and paths_.labels_csv.read_bytes() == snapshot
    # undo 도 거부
    assert _label_cli(tmp_path, "label", "S2", "유사", "--undo", "--source", "llm") == 3
    # 미확인 행은 llm 이 쓰고 덮어쓸 수 있다; 사람이 수정하면 원본 LLM 판정을 남긴다
    assert _label_cli(tmp_path, "label", "S1", "유사", "--source", "llm", *common) == 0
    assert _label_cli(tmp_path, "label", "S1", "비유사", "--source", "llm", *common) == 0
    row = _labels_by_trial(paths_)["S1"]
    assert row["유사여부_확정"] == "비유사" and row["확인여부"] == "" and row["llm_판정_원본"] == ""
    assert _label_cli(tmp_path, "label", "S1", "유사", "--axis", "호칭", "--source", "human",
                      *common) == 0
    row = _labels_by_trial(paths_)["S1"]
    assert row["라벨출처"] == "human" and row["확인여부"] == "Y"
    assert row["llm_판정_원본"] == "비유사"
    # pass b 는 llm_b_* 열에만, 사람 열·확인여부 그대로
    assert _label_cli(tmp_path, "label", "S1", "비유사", "--pass", "b", "--source", "llm",
                      "--evidence", "두 번째 판독", "--confidence", "low") == 0
    row = _labels_by_trial(paths_)["S1"]
    assert row["llm_b_유사여부"] == "비유사" and row["llm_b_확신도"] == "low"
    assert row["llm_b_근거"] == "두 번째 판독" and row["유사여부_확정"] == "유사"
    assert row["확인여부"] == "Y"
    assert _label_cli(tmp_path, "label", "S1", "--undo", "--pass", "b", "--source", "llm") == 0
    assert _label_cli(tmp_path, "label", "S1", "--undo", "--source", "human") == 0
    row = _labels_by_trial(paths_)["S1"]
    assert all(row[c] == "" for c in tc.PRESERVED_COLUMNS)
    # labels.csv 가 라벨 열 없이 만들어졌어도(이전 sheet) 열을 덧붙여 기록한다
    rows = _rows(paths_.labels_csv)
    old_columns = [c for c in tc.LABEL_COLUMNS if c not in tc.LABEL_META_COLUMNS + tc.LLM_B_COLUMNS]
    tc._write_csv(paths_.labels_csv, old_columns, rows)
    assert _label_cli(tmp_path, "label", "S5", "유사", "--source", "llm", *common) == 0
    assert _labels_by_trial(paths_)["S5"]["라벨출처"] == "llm"
    assert _rows(paths_.labels_csv)[0].keys() >= set(tc.LABEL_COLUMNS)


def test_confirm_approves_llm_label_as_is(tmp_path, capsys):
    paths_, _ = _curation_fixture(tmp_path)
    common = ["--evidence", "표장이 유사하다", "--confidence", "high"]
    assert _label_cli(tmp_path, "confirm", "S1") == 1  # 라벨 없음
    assert _label_cli(tmp_path, "label", "S1", "유사", "--axis", "호칭", "--source", "llm",
                      *common) == 0
    assert _label_cli(tmp_path, "confirm", "S1") == 0
    row = _labels_by_trial(paths_)["S1"]
    assert row["라벨출처"] == "human-confirmed" and row["확인여부"] == "Y"
    assert row["유사여부_확정"] == "유사" and row["판단축_확정"] == "호칭"
    assert row["llm_판정_원본"] == "유사" and row["근거문장"] == "표장이 유사하다"
    assert "승인: S1 1행" in capsys.readouterr().out
    assert _label_cli(tmp_path, "label", "S1", "비유사", "--source", "llm", *common) == 3
    assert _label_cli(tmp_path, "confirm", "S1") == 0  # 이미 승인 → 0행, 오류 아님
    assert "0행" in capsys.readouterr().out


def test_batch_markdown_omits_regex_estimates_and_skips_labeled(tmp_path, capsys):
    paths_, _ = _curation_fixture(tmp_path)
    assert _label_cli(tmp_path, "show", "--batch", "2") == 0
    batch = (tmp_path / "batch_1.md").read_text(encoding="utf-8")
    assert batch.startswith("# 큐레이션 배치 1 — 2건 · pass a")
    assert "## 1. S2 · 권리범위확인(소극적) · 상표A: B · 상대 번호: -" in batch
    assert "## 2. S5 ·" in batch
    assert "1. 확인대상표장은 상표등록 제1697796호의 권리범위에 속한다." in batch  # 주문
    assert "4. 확인대상표장이 이 사건 등록상표의 권리범위에 속하는지 여부" in batch  # 판단 절
    anchors = ("추정", "결정축", "등급사유", "자동등급", "신뢰도", "표장 소결", "주문결과",
               "등급 1")
    for anchor in anchors:
        assert anchor not in batch, anchor  # 자동 판정은 넣지 않는다
    assert "batch_1.md" in capsys.readouterr().out
    assert _label_cli(tmp_path, "label", "S2", "유사", "--source", "llm", "--evidence", "x",
                      "--confidence", "high") == 0
    assert _label_cli(tmp_path, "show", "--batch", "1") == 0
    batch2 = (tmp_path / "batch_2.md").read_text(encoding="utf-8")
    assert "## 1. S5 ·" in batch2 and "S2" not in batch2  # pass a 라벨이 있는 건은 건너뛴다
    assert _label_cli(tmp_path, "show", "--batch", "1", "--pass", "b") == 0
    batch3 = (tmp_path / "batch_3.md").read_text(encoding="utf-8")
    assert "pass b" in batch3 and "## 1. S2 ·" in batch3  # pass b 는 아직 없다
    assert "--pass b`" in batch3


def _label_row(number: str, desc: str, **fields) -> dict:
    row = {column: "" for column in tc.LABEL_COLUMNS}
    row.update({"심판번호": number, "종류": desc, "상표B_번호": fields.pop("b", "")})
    row.update(fields)
    return row


def test_verify_sample_is_stratified_by_kind_and_verdict(tmp_path):
    kinds = tc.load_kinds(KINDS)
    descs = {"scope": "권리범위확인(적극적)", "refusal": "거절결정불복", "invalidation": "무효"}
    rows = []
    for kind, desc in descs.items():
        for verdict in tc.VERDICTS:
            for i in range(4):
                rows.append(_label_row(f"{kind[0]}{verdict}{i}", desc, 유사여부_확정=verdict,
                                       라벨출처="llm", 확신도="high", 근거문장="e"))
    rows.append(_label_row("confirmed", descs["scope"], 유사여부_확정="유사",
                           라벨출처="human-confirmed", 확인여부="Y"))
    rows.append(_label_row("human", descs["scope"], 유사여부_확정="유사", 라벨출처="human",
                           확인여부="Y"))
    picked = tc.select_verify_sample(rows, kinds, 9, 0)
    assert len(picked) == 9 and sorted({p["층"] for p in picked}) == sorted(
        f"{k}/{v}" for k in descs for v in tc.VERDICTS
    )
    assert {p["심판번호"] for p in picked}.isdisjoint({"confirmed", "human"})
    again = tc.select_verify_sample(rows, kinds, 9, 0)
    assert [p["심판번호"] for p in again] == [p["심판번호"] for p in picked]  # 시드 재현
    assert [p["심판번호"] for p in tc.select_verify_sample(rows, kinds, 9, 1)] != [
        p["심판번호"] for p in picked
    ]
    twelve = tc.select_verify_sample(rows, kinds, 12, 0)
    per_stratum = {}
    for p in twelve:
        per_stratum[p["층"]] = per_stratum.get(p["층"], 0) + 1
    assert len(twelve) == 12 and all(1 <= c <= 2 for c in per_stratum.values())
    assert tc.allocate_strata({"a": 10, "b": 1, "c": 5}, 4) == {"a": 2, "b": 1, "c": 1}
    assert tc.allocate_strata({"a": 2, "b": 2}, 10) == {"a": 2, "b": 2}
    paths_ = tc.TrialPaths(tmp_path)
    tc._write_csv(paths_.labels_csv, tc.LABEL_COLUMNS, rows)
    assert tc.main(["--data-dir", str(tmp_path), "sample", "--n", "9", "--seed", "0"]) == 0
    assert [r["심판번호"] for r in _rows(paths_.verify_queue)] == [p["심판번호"] for p in picked]
    assert set(_rows(paths_.verify_queue)[0]) == set(tc.VERIFY_COLUMNS)
    assert tc.main(["--data-dir", str(tmp_path), "sample"]) == 2  # 수집 표본은 --out 필수


def test_review_queue_reasons_and_status_agreement(tmp_path, capsys):
    scope, refusal = "권리범위확인(적극적)", "거절결정불복"
    rows = [
        _label_row("R1", refusal, 유사여부_확정="비유사", 유사여부_추정="비유사", 라벨출처="human",
                   확인여부="Y", 확신도="high", llm_판정_원본="유사"),  # 사람이 LLM 유사→비유사로
        _label_row("R2", refusal, 유사여부_확정="유사", 유사여부_추정="유사", 라벨출처="llm",
                   확신도="low"),
        _label_row("R3", scope, 유사여부_확정="유사", 유사여부_추정="유사", 라벨출처="human",
                   확인여부="Y", 확신도="high", 메모="호칭은 애매함"),
        _label_row("R4", scope, 유사여부_확정="유사", 유사여부_추정="유사", 라벨출처="llm",
                   확신도="high", llm_b_유사여부="비유사", llm_b_확신도="high"),
        _label_row("R5", scope, 유사여부_확정="제외", 제외사유="인지도", 라벨출처="llm",
                   확신도="high", llm_b_유사여부="제외", llm_b_제외사유="식별력"),
        _label_row("R6", scope, 유사여부_확정="유사", 유사여부_추정="유사",
                   라벨출처="human-confirmed", 확인여부="Y", 확신도="high", llm_판정_원본="유사"),
        _label_row("R7", scope, 유사여부_확정="비유사", 유사여부_추정="유사", 라벨출처="llm",
                   확신도="high", llm_b_유사여부="비유사"),
        _label_row("R8", scope),  # 라벨 없음
    ]
    queue = tc.build_review_queue(rows)
    assert {q["심판번호"]: q["사유"] for q in queue} == {
        "R1": "LLM≠추정", "R2": "확신도 low", "R3": "메모 애매", "R4": "A≠B", "R5": "A≠B",
        "R7": "LLM≠추정",
    }
    assert [q["순번"] for q in queue] == [1, 2, 3, 4, 5, 6]
    paths_ = tc.TrialPaths(tmp_path)
    tc._write_csv(paths_.labels_csv, tc.LABEL_COLUMNS, rows)
    assert tc.main(["--data-dir", str(tmp_path), "review"]) == 0
    assert "review: 6행" in capsys.readouterr().out
    assert [r["사유"] for r in _rows(paths_.review_queue)][:2] == ["LLM≠추정", "확신도 low"]
    curation = [{"순번": i, "심판번호": n, "종류": scope, "상표A_명칭": "", "상대표장_번호": "",
                 "유사여부_추정": "", "신뢰도": "", "등급사유": ""}
                for i, n in enumerate(["R1", "R2", "R8"], start=1)]
    lines = tc.label_summary(rows, curation)
    assert lines[0].startswith("라벨: 유사 4 · 비유사 2 · 제외 1 (행 7/8)")
    assert "human 2" in lines[0] and "human-confirmed 1" in lines[0] and "llm 4" in lines[0]
    assert "확인(Y) 3" in lines[0] and "pass b 3" in lines[0]
    assert lines[1] == "LLM↔사람 일치율 1/2 (50%) — confirm 1 · 수정 1"  # R6 confirm, R1 수정
    assert lines[2] == "LLM↔추정 일치율 3/5 (60%)"  # R1 llm 유사≠비유사, R2 ✓, R4 ✓, R6 ✓, R7 ✗
    assert lines[3] == "LLM A↔B 일치율 1/3 (33%)"  # R4 ✗ · R5 사유 다름 ✗ · R7 ✓
    assert lines[4] == "남은 큐: pass a 1/3 · pass b 3/3"
    tc._write_csv(paths_.curation_queue, tc.CURATION_COLUMNS, curation)
    assert tc.main(["--data-dir", str(tmp_path), "status"]) == 0
    assert "LLM↔사람 일치율 1/2 (50%)" in capsys.readouterr().out


def test_label_name_b_records_counterpart_name_without_touching_verdict(tmp_path, capsys):
    paths_, _ = _curation_fixture(tmp_path)
    assert _label_cli(tmp_path, "label", "S2", "유사", "--source", "llm", "--evidence", "x",
                      "--confidence", "high", "--memo", "애매: 축 명시 없음") == 0
    before = _labels_by_trial(paths_)["S2"]
    assert _label_cli(tmp_path, "label", "S2", "--name-b", "  큐 파이어  Q-FIRE ", "--source",
                      "llm") == 0
    row = _labels_by_trial(paths_)["S2"]
    assert row["상대표장_명칭_llm"] == "큐 파이어 Q-FIRE"
    assert {k: v for k, v in row.items() if k != "상대표장_명칭_llm"} == {
        k: v for k, v in before.items() if k != "상대표장_명칭_llm"
    }  # 판정·근거·메모 그대로
    assert "상대 명칭 기록: S2 1행" in capsys.readouterr().out
    # 도형만: 빈 값 + memo 는 기존 메모 뒤에 덧붙인다(덮어쓰지 않음), 두 번 써도 한 번만
    for _ in range(2):
        assert _label_cli(tmp_path, "label", "S2", "--name-b", "", "--source", "llm",
                          "--memo", "도형") == 0
    row = _labels_by_trial(paths_)["S2"]
    assert row["상대표장_명칭_llm"] == "" and row["메모"] == "애매: 축 명시 없음 · 도형"
    assert row["유사여부_확정"] == "유사" and row["라벨출처"] == "llm"
    # human 출처로는 기록하지 않는다, 판정과 같이 주면 둘 다 기록
    assert _label_cli(tmp_path, "label", "S2", "--name-b", "X", "--source", "human") != 0
    assert _label_cli(tmp_path, "label", "S5", "비유사", "--name-b", "에스오", "--source", "llm",
                      "--evidence", "y", "--confidence", "low") == 0
    row = _labels_by_trial(paths_)["S5"]
    assert row["유사여부_확정"] == "비유사" and row["상대표장_명칭_llm"] == "에스오"
    assert "상대표장_명칭_llm" in tc.PRESERVED_COLUMNS


def test_show_ids_writes_name_batches_with_facts_and_judgment(tmp_path, capsys):
    paths_, _ = _curation_fixture(tmp_path)
    ids = tmp_path / "ids.txt"
    ids.write_text("# 명칭 추출 대상\nS2\nS5\nS2\nNOPE\n", encoding="utf-8")
    assert _label_cli(tmp_path, "show", "--batch", "1", "--ids", str(ids)) == 0
    out = capsys.readouterr().out
    assert "명칭 배치 2개: 2건(목록 3, labels 에 없음 1)" in out
    batch1 = (tmp_path / "batch_1.md").read_text(encoding="utf-8")
    batch2 = (tmp_path / "batch_2.md").read_text(encoding="utf-8")
    assert batch1.startswith("# 상대 표장 명칭 배치 1 — 1건")
    assert "## 1. S2 · 권리범위확인(소극적) · 상표A: B · 상대 번호: - · 기존 명칭: 본문 -" in batch1
    assert "### 기초사실" in batch1 and "### 판단 절" in batch1
    assert "4. 확인대상표장이 이 사건 등록상표의 권리범위에 속하는지 여부" in batch1  # 판단 절
    assert '--name-b "<문자열>" --source llm' in batch1
    assert "## 1. S5 ·" in batch2 and "S2" not in batch2.split("## 1.")[1]
    for anchor in ("추정", "결정축", "등급사유", "자동등급"):
        assert anchor not in batch1, anchor


# ---- review --bundle ---------------------------------------------------------------------------

FEATURE_COLUMNS = [
    "심판번호", "종류", "상대번호", "최종라벨", "표장라벨", "이름A", "이름B", "x1", "x1_d",
    "x2_text", "x2_text_d", "weak_a", "weak_b",
]


def _feature(number, mark, x1, x1_d, x2, x2_d, **extra) -> dict:
    row = {c: "" for c in FEATURE_COLUMNS}
    row.update({"심판번호": number, "종류": "무효", "표장라벨": mark, "최종라벨": mark,
                "이름A": "A", "이름B": "B", "x1": x1, "x1_d": x1_d, "x2_text": x2,
                "x2_text_d": x2_d})
    row.update(extra)
    return row


def _bundle_fixture(tmp_path):
    scope, refusal = "권리범위확인(적극적)", "거절결정불복"
    rows = [
        _label_row("B1", refusal, b="111", 유사여부_확정="유사",
                   llm_b_유사여부="비유사", 라벨출처="llm", 확신도="high", 근거문장="e1",
                   llm_b_근거="e1b", 상대표장_명칭_llm="큐파이어", 상대표장_명칭_본문="본문1",
                   메모="검토 필요"),
        _label_row("B2", refusal, b="222", 유사여부_확정="비유사", llm_b_유사여부="비유사",
                   라벨출처="llm", 확신도="high", 근거문장="e2"),
        _label_row("B3", scope, 유사여부_확정="유사", llm_b_유사여부="유사", 라벨출처="llm",
                   확신도="low", 근거문장="e3", 상대표장_명칭_llm="", 메모="애매 · 도형"),
        _label_row("B4", scope, 유사여부_확정="제외", 제외사유="인지도",
                   llm_b_유사여부="유사", 라벨출처="llm", 확신도="high", 근거문장="e4"),
        _label_row("B5", scope, 유사여부_확정="비유사", 라벨출처="human", 확인여부="Y",
                   확신도="high"),  # 사람 확정 — 표본 대상 아님, pass b 없음
    ]
    paths_ = tc.TrialPaths(tmp_path)
    tc._write_csv(paths_.labels_csv, tc.LABEL_COLUMNS, rows)
    features = [
        _feature("B1", "유사", "1.0000", "0.4000", "1.0000", "1.0000", 상대번호="111",
                 weak_a="gate", weak_b="gate"),  # x1 하락 0.6
        _feature("B2", "비유사", "1.0000", "0.2000", "1.0000", "0.2000",
                 상대번호="222"),  # 비유사 제외
        _feature("B3", "유사", "0.8000", "0.7500", "0.9000", "0.7000",
                 weak_b="카페"),  # x2 하락 0.2
        _feature("B4", "유사", "0.8000", "0.7000", "0.5000", "0.4500"),  # 둘 다 경계(−0.1) → 제외
        _feature("B5", "유사", "0.6000", "", "0.6000", "0.6000"),  # 결측 → 제외
    ]
    tc._write_csv(paths_.pairs_features_csv, FEATURE_COLUMNS, features)
    weak = tmp_path / "weak_tokens.json"
    weak.write_text(json.dumps({"tokens": [
        {"token": "gate", "score": 0.0, "A": 12, "N": 30, "zipf": 4.5,
         "reasons": ["일반어(zipf 4.5)"]},
        {"token": "coffee", "score": 0.0, "A": 112, "N": 119, "zipf": 4.9,
         "reasons": ["다수 등록"]},
        {"token": "dr", "score": 0.0, "A": 125, "N": 141, "zipf": 5.2,
         "reasons": ["6호 간단 표장"]},
    ]}, ensure_ascii=False), encoding="utf-8")
    paths_.name_review_ids.write_text(
        "# 검토 요청\nB3\t도형 판정 확인\nNOPE\t없는 번호\n", encoding="utf-8"
    )
    return paths_, weak


def test_review_bundle_writes_five_csvs_with_show_commands(tmp_path, capsys):
    paths_, weak = _bundle_fixture(tmp_path)
    assert _label_cli(tmp_path, "review", "--bundle", "--n", "2", "--weak-tokens", str(weak)) == 0
    out = capsys.readouterr().out
    assert "review --bundle" in out and "verify_queue 4행" in out  # 층(종류×판정)마다 최소 1
    assert "ab_disagree 2행" in out
    bundle = paths_.review_bundle_dir
    assert sorted(p.name for p in bundle.glob("*.csv")) == [
        f"{n}.csv" for n in sorted(tc.BUNDLE_NAMES)
    ]
    verify = _rows(bundle / "verify_queue.csv")
    assert len(verify) == 4
    assert all(r["show"].endswith(f"show {r['심판번호']}") for r in verify)
    assert verify[0]["처리"] == ""
    assert verify[0]["show"].startswith("ml/venv/bin/python -m backend")
    ab = _rows(bundle / "ab_disagree.csv")
    assert [r["심판번호"] for r in ab] == ["B1", "B4"]
    assert ab[0]["유사여부_확정"] == "유사" and ab[0]["llm_b_유사여부"] == "비유사"
    assert ab[0]["근거문장"] == "e1" and ab[0]["llm_b_근거"] == "e1b"
    names = _rows(bundle / "name_review.csv")
    # 목록 파일이 있으면 그 번호만(메모의 "검토" 는 무시)
    assert [(r["심판번호"], r["사유"]) for r in names] == [("B3", "도형 판정 확인")]
    assert names[0]["메모"] == "애매 · 도형" and names[0]["상대표장_명칭_llm"] == ""
    drop = _rows(bundle / "distinct_drop.csv")
    assert [r["심판번호"] for r in drop] == ["B1", "B3"]
    assert drop[0]["x1"] == "1.0000" and drop[0]["x1_d"] == "0.4000"
    assert drop[0]["떼어낸_토큰_A"] == "gate"
    assert drop[1]["떼어낸_토큰_B"] == "카페" and drop[1]["상대번호"] == ""
    top = _rows(bundle / "weak_tokens_top200.csv")
    assert [r["토큰"] for r in top] == ["dr", "coffee", "gate"]
    assert top[0]["show"] == ""
    assert top[2]["사유"] == "일반어(zipf 4.5)" and top[2]["N"] == "30"
    # 목록 파일이 없으면 메모의 "검토" 로 대체
    paths_.name_review_ids.unlink()
    assert _label_cli(tmp_path, "review", "--bundle", "--weak-tokens", str(weak)) == 0
    assert "메모의 '검토' 로 대체" in capsys.readouterr().out
    assert [(r["심판번호"], r["사유"]) for r in _rows(bundle / "name_review.csv")] == [
        ("B1", "메모에 검토")
    ]


def test_distinct_drop_rule_thresholds():
    rows = [
        _feature("D1", "유사", "0.9000", "0.8000", "0.5000", "0.5000"),  # 정확히 −0.1 → 제외
        _feature("D2", "유사", "0.9000", "0.7999", "0.5000", "0.5000"),  # x1 만 하락
        _feature("D3", "유사", "0.9000", "0.9000", "0.5000", "0.3000"),  # x2_text 만 하락
        _feature("D4", "비유사", "1.0000", "0.0000", "1.0000", "0.0000"),  # 비유사 → 제외
        _feature("D5", "", "1.0000", "0.0000", "1.0000", "0.0000"),  # 표장 라벨 없음
        _feature("D6", "유사", "", "", "0.9000", "0.5000"),  # x1 결측이어도 x2 하락이면
    ]
    dropped = tc.distinct_drop_rows(rows)
    assert [r["심판번호"] for r in dropped] == ["D2", "D3", "D6"]
    assert [r["순번"] for r in dropped] == [1, 2, 3]
    assert tc.distinct_drop_rows(rows, delta=0.05)[0]["심판번호"] == "D1"
    assert list(dropped[0]) == tc.DISTINCT_DROP_COLUMNS


def test_status_counts_bundle_progress_and_regeneration_preserves_done(tmp_path, capsys):
    paths_, weak = _bundle_fixture(tmp_path)
    assert _label_cli(tmp_path, "review", "--bundle", "--n", "2", "--weak-tokens", str(weak)) == 0
    bundle = paths_.review_bundle_dir
    ab_path = bundle / "ab_disagree.csv"
    ab = _rows(ab_path)
    ab[0]["처리"] = "확인 2026-10-09"
    tc._write_csv(ab_path, list(ab[0]), ab)
    assert tc.bundle_progress(paths_) == [
        ("verify_queue", 0, 4), ("ab_disagree", 1, 2), ("name_review", 0, 1),
        ("distinct_drop", 0, 2), ("weak_tokens_top200", 0, 3),
    ]
    tc._write_csv(paths_.curation_queue, tc.CURATION_COLUMNS, [])
    capsys.readouterr()
    assert _label_cli(tmp_path, "status") == 0
    out = capsys.readouterr().out
    assert "검토 묶음(처리/행): verify_queue 0/4 · ab_disagree 1/2" in out
    assert "name_review 0/1" in out
    # 재생성해도 같은 키 행의 처리 열은 남는다
    assert _label_cli(tmp_path, "review", "--bundle", "--n", "2", "--weak-tokens", str(weak)) == 0
    assert "ab_disagree 2행(처리 1 보존)" in capsys.readouterr().out
    assert _rows(ab_path)[0]["처리"] == "확인 2026-10-09"
    assert _rows(ab_path)[1]["처리"] == ""
    assert tc.bundle_progress(tc.TrialPaths(tmp_path / "none")) == []
