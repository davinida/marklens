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

# 항목별검색 캡처 샘플 형식(특허 1건) + 실측 2013당419(상표 무효) 1건, totalCount 2
XML_LIST = """<?xml version="1.0" encoding="UTF-8"?>
<response>
<header><requestMsgID></requestMsgID><responseTime>2014-10-31 11:05:34.534</responseTime>
<responseMsgID></responseMsgID><successYN></successYN><resultCode>00</resultCode>
<resultMsg>NORMAL SERVICE.</resultMsg></header>
<body><items>
<item><applicationNumber>1020070001615</applicationNumber><defendant></defendant>
<plaintiff>주식회사 비즈모델라인</plaintiff><registrationNumber></registrationNumber>
<title>알에프 리더형 휴대폰</title><trialDecisionDoc></trialDecisionDoc>
<trialDesc>거절결정불복</trialDesc><trialFlag>특허심판원</trialFlag>
<trialNumber>2007101234567</trialNumber><trialStatus>심결</trialStatus></item>
<item><applicationNumber>4020080049731</applicationNumber><defendant>홍길동</defendant>
<plaintiff>루이비똥 말레띠에</plaintiff><registrationNumber>4009157630000</registrationNumber>
<title>LV</title><trialDecisionDoc>Y</trialDecisionDoc>
<trialDesc>무효</trialDesc><trialFlag>특허심판원</trialFlag>
<trialNumber>2013100000419</trialNumber><trialStatus>심결</trialStatus></item>
<numOfRows>500</numOfRows><pageNo>1</pageNo><totalCount>2</totalCount>
</items></body></response>
"""

# 심판(결)문 응답 — 2026-07 실측 형식
XML_DOC = """<response><header><requestMsgID/><responseTime>2026-07-06 13:25:24</responseTime>
<responseMsgID/><successYN>Y</successYN><resultCode>00</resultCode>
<resultMsg>NORMAL SERVICE.</resultMsg></header><body><item>
<fileName>2013100000419.PDF</fileName><kind>S11907</kind><openYN>Y</openYN>
<path>http://plus.kipris.or.kr/openapi/fileToss.jsp?arg=abc123</path></item></body></response>
"""
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
    assert [it["trialNumber"] for it in items] == ["2007101234567", "2013100000419"]
    assert items[1]["trialDesc"] == "무효" and items[1]["trialDecisionDoc"] == "Y"


def test_parse_doc_response_measured_format():
    doc = tc.parse_doc_response(XML_DOC)
    assert doc == {
        "fileName": "2013100000419.PDF", "kind": "S11907", "openYN": "Y",
        "path": "http://plus.kipris.or.kr/openapi/fileToss.jsp?arg=abc123",
    }
    with pytest.raises(kc.KiprisError):
        tc.parse_doc_response(XML_DOC.replace("<resultCode>00", "<resultCode>31"))


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ({"applicationNumber": "4020080049731"}, True),
        ({"applicationNumber": "41-2020-0000001"}, True),
        ({"applicationNumber": "4520200000001"}, True),
        ({"applicationNumber": "1020070001615"}, False),
        ({"applicationNumber": "", "registrationNumber": "4009157630000"}, True),
        ({"applicationNumber": "", "registrationNumber": ""}, False),
    ],
)
def test_is_trademark_item_prefix_filter(item, expected):
    assert tc.is_trademark_item(item) is expected


def test_kind_for_trial_desc_mapping():
    kinds = tc.load_kinds(KINDS)
    assert set(kinds) == {"refusal", "invalidation", "scope"}
    assert tc.kind_for_trial_desc("거절결정불복", kinds) == "refusal"
    assert tc.kind_for_trial_desc("등록무효", kinds) == "invalidation"
    assert tc.kind_for_trial_desc("권리범위확인(소극)", kinds) == "scope"
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
    assert [r["심판번호"] for r in rows] == ["2013100000419"]  # 특허(10…)는 제외, 2개월 중복 제거
    assert rows[0]["종류"] == "무효" and rows[0]["출원번호"] == "4020080049731"
    assert rows[0]["심결문유무"] == "Y" and json.loads(rows[0]["원본JSON"])["title"] == "LV"
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
    session = _session(tmp_path, lambda url, params: XML_LIST)
    assert tc.run_list(_list_args(tmp_path, allow_unverified=False), session) == 2
    assert session.api_calls == 0


def test_list_paginates_when_total_exceeds_rows(tmp_path):
    seen: list[str] = []

    def transport(url, params):
        seen.append(params["pageNo"])
        return XML_LIST.replace("<totalCount>2", "<totalCount>3")

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
    assert "177개월" in out and "실호출 0회" in out and "미검증" in out
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
    assert tc.classify(_analysis("34-7:긍정", 본문_주지=1)) == ("2", "결론 7호이나 본문에 주지")
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
    rows = tc.build_sheet_rows(list_rows, prefilter, kinds)
    assert [(r["심판번호"], r["상표B_번호"]) for r in rows] == [
        ("A", "123456"), ("A", "234567"), ("B", ""),
    ]
    assert rows[0]["상표A_번호"] == "915763" and rows[0]["자동등급"] == "3"
    assert "34-11" in rows[0]["조문플래그"] and "저명" in rows[0]["조문플래그"]
    assert rows[2]["등급사유"] == "텍스트 미추출" and rows[2]["상표A_번호"] == "4020200012345"
    assert set(tc.LABEL_COLUMNS) >= {"유사여부_확정", "판단축", "제외사유", "메모"}


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
