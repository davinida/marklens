"""trials_enrich 테스트 — 네트워크 없이(가짜 fetch·가짜 goods_map). 번호 정규화, 응답 파싱,
멱등·하드캡, 본문 명칭 추출, 지정상품 분리·매핑, labels.csv 보존 병합."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.scripts import trials_collect as tc
from backend.scripts import trials_enrich as te
from backend.src.core import kipris_client as kc

XML_OK = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
<body><items>
<item><applicationNumber>4020120012345</applicationNumber>
<registrationNumber>4001234560000</registrationNumber><title>COCO</title>
<applicantName>주식회사 코코</applicantName><viennaCode>010101|020202</viennaCode>
<classificationCode>09|42</classificationCode><applicationStatus>등록</applicationStatus></item>
<item><applicationNumber>4020120099999</applicationNumber>
<registrationNumber>4009999990000</registrationNumber><title>OTHER</title></item>
</items><totalCount>2</totalCount></body></response>"""
XML_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>00</resultCode></header>
<body><items/><totalCount>0</totalCount></body></response>"""
XML_ERROR = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>10</resultCode><resultMsg>INVALID_REQUEST_PARAMETER_ERROR</resultMsg>
</header><body/></response>"""

FACTS_REFUSAL = """특허심판원 심결
1. 기초사실
가. 이 사건 출원상표
(1) 출원번호/출원일: 제40-2020-0001234호/2020. 1. 1.
(2) 구성:
(3) 지정상품: 상품류 구분 제9류의 컴퓨터, 노트북컴퓨터·모니터 등
나. 원결정 이유 및 선등록상표들
(1) 원결정이유
이 사건 출원상표는 선등록상표와 지정상품이 유사하다.
(2) 선등록상표 1
(가) 등록번호/출원일/등록일: 서비스표등록 제80250호/2010. 1. 1./2011. 1. 1.
(나) 구성:
(다) 지정서비스업: 서비스업류 구분 제42류의 컴퓨터프로그래밍업, 컴퓨터 자문업
(3) 선등록상표 2
(가) 등록번호: 상표등록 제666832호
(나) 구성: WORDMARK
(다) 지정상품: 별지1과 같다.
2. 청구인 주장의 요지
청구인은 국제상표 344173 과도 다투지 않는다.
[별지1]
상품류 구분 제9류의 컴퓨터, 키보드
[별지2]
무관
"""
FACTS_SCOPE = """특허심판원 심결
1. 기초사실
가. 이 사건 등록상표
(1) 등록번호: 상표등록 제111111호
(2) 구성:
(3) 지정상품: 상품류 구분 제25류의 신발, 운동화
나. 확인대상표장
(1) 구성 : 모래알
(2) 사용상품 : 신발, 샌들
2. 청구인 주장의 요지
확인대상표장은 한글 ‘모래알’로 구성된 표장이다.
"""


class FakeGoodsMap:
    """정확 일치 사전 + 접두 검색 흉내."""

    def __init__(self) -> None:
        self.table = {
            ("컴퓨터", 9): ("G390802",), ("노트북컴퓨터", 9): ("G390802",),
            ("모니터", 9): ("G390802",),
            ("키보드", 9): ("G390802",), ("컴퓨터프로그래밍업", 42): ("S120602",),
            ("컴퓨터 자문업", 42): ("S120602",), ("신발", 25): ("G270101",),
            ("운동화", 25): ("G270101",), ("샌들", 25): ("G270101",), ("가방", 18): ("G250101",),
        }

    def codes_for(self, name, nice_class=None):
        codes = set()
        for (entry_name, entry_class), values in self.table.items():
            if entry_name == name and (nice_class is None or entry_class == nice_class):
                codes.update(values)
        return frozenset(codes)

    def search(self, query, limit=20, nice_class=None):
        hits = []
        for (entry_name, entry_class), values in self.table.items():
            if nice_class is not None and entry_class != nice_class:
                continue
            if entry_name.startswith(query):
                tier = 0 if entry_name == query else 1
            elif query in entry_name:
                tier = 2
            else:
                continue
            hits.append(SimpleNamespace(name=entry_name, nice_class=entry_class,
                                        similarity_codes=values, matched_alias=None, tier=tier))
        return sorted(hits, key=lambda m: m.tier)[:limit]


@pytest.mark.parametrize(
    ("number", "wording", "expected"),
    [
        ("666832", "상표", ("registration", "4006668320000")),
        ("80250", "서비스표", ("registration", "4100802500000")),
        ("1234567", "상표서비스표", ("registration", "4512345670000")),
        ("4020137006136", "", ("application", "4020137006136")),
        ("4000073530000", "", ("registration", "4000073530000")),
        ("344173", "국제", ("international", "344173")),
        ("", "", ("", "")),
        ("12345678901", "", ("unknown", "12345678901")),
    ],
)
def test_normalize_number(number, wording, expected):
    assert te.normalize_number(number, wording) == expected


def test_number_wordings_and_categorize():
    wordings = te.number_wordings(FACTS_REFUSAL)
    assert wordings == {"80250": "서비스표", "666832": "상표", "344173": "국제"}
    row = {"종류": "거절결정불복", "상표B_번호": "80250", "상대표장_유형": "선등록"}
    assert te.categorize(row, wordings)["번호_정규화"] == "4100802500000"
    assert te.categorize(row, wordings)["범주"] == te.CATEGORY_NUMBERED
    intl = {"종류": "거절결정불복", "상표B_번호": "344173", "상대표장_유형": "선등록|국제등록"}
    assert te.categorize(intl, wordings)["범주"] == te.CATEGORY_INTL
    scope = {"종류": "권리범위확인(소극적)", "상표B_번호": "", "상대표장_유형": "확인대상표장"}
    assert te.categorize(scope, wordings)["범주"] == te.CATEGORY_TARGET
    use = {"종류": "무효", "상표B_번호": "", "상대표장_유형": "선등록|선사용"}
    assert te.categorize(use, wordings)["범주"] == te.CATEGORY_USE
    bad = {"종류": "무효", "상표B_번호": "12345678901", "상대표장_유형": "선등록"}
    assert te.categorize(bad, {})["범주"] == te.CATEGORY_UNCONVERTIBLE


def test_mark_blocks_and_body_name():
    blocks = te.mark_blocks(FACTS_SCOPE)
    assert [(b["kind"], b["role"]) for b in blocks] == [("this", "this"), ("target", "target")]
    assert te.body_name(FACTS_SCOPE, blocks, te.CATEGORY_TARGET) == "모래알"
    without_inline = FACTS_SCOPE.replace("(1) 구성 : 모래알", "(1) 구성 :")
    blocks = te.mark_blocks(without_inline)
    assert te.body_name(without_inline, blocks, te.CATEGORY_TARGET) == "모래알"  # 판단 절 따옴표
    noisy = without_inline.replace("‘모래알’", "‘이 사건 등록상표와 같은 표장’")
    assert te.body_name(noisy, te.mark_blocks(noisy), te.CATEGORY_TARGET) == ""
    refusal_blocks = te.mark_blocks(FACTS_REFUSAL)
    assert [b["role"] for b in refusal_blocks] == ["this", "prior_1", "prior_2"]
    assert te.body_name(FACTS_REFUSAL, refusal_blocks, te.CATEGORY_NUMBERED) == ""


FACTS_MULTI_APPENDIX = """1. 기초사실
가. 이 사건 등록상표
(1) 등록번호 : 상표등록 제111111호
(3) 지정상품 : [별지 1]과 같다.
나. 선등록상표들
(1) 선등록상표 1
(가) 등록번호 : 상표등록 제222222호
(다) 지정상품 : 별지 2. 기재와 같다.
(2) 선등록상표 2
(가) 등록번호 : 상표등록 제40-333333호
(다) 지정상품 : 별지2과 같다.
2. 당사자의 주장
[별지 1]
●이 사건 등록상표의 지정상품: 상품류 구분 제9류의 컴퓨터
[별지 2.]
●선등록상표 1의 지정상품
- 상품류 구분 제9류의 키보드
●선등록상표 제40-333333호의 지정상품
- 상품류 구분 제9류의 모니터
"""


def test_appendix_reference_forms_and_section_selection():
    blocks = te.mark_blocks(FACTS_MULTI_APPENDIX)
    by_role = {b["role"]: b for b in blocks}
    assert set(by_role) == {"this", "prior_1", "prior_2"}
    # 소제목 줄("●…지정상품:")은 떼고 콜론 뒤는 남긴다 · 헤더 "[별지 1]"
    this_text = te.goods_text(by_role["this"]["text"], FACTS_MULTI_APPENDIX, by_role["this"])
    assert te.split_goods(this_text) == [("컴퓨터", 9)]
    # "별지 2. 기재와 같다" → 헤더 "[별지 2.]" → 순번(선등록상표 1)으로 절 선택
    prior_1 = te.goods_text(by_role["prior_1"]["text"], FACTS_MULTI_APPENDIX, by_role["prior_1"])
    assert te.split_goods(prior_1) == [("키보드", 9)]
    # 등록번호(40-333333 ↔ 제40-333333호)로 절 선택
    prior_2 = te.goods_text(by_role["prior_2"]["text"], FACTS_MULTI_APPENDIX, by_role["prior_2"])
    assert te.split_goods(prior_2) == [("모니터", 9)]
    # 블록 힌트가 없으면 소제목만 떼고 절 전체
    assert te.split_goods(te.goods_text(by_role["prior_2"]["text"], FACTS_MULTI_APPENDIX)) == [
        ("키보드", 9), ("모니터", 9)
    ]
    for wording in ("별지와 같다", "[별지3]과 같다", "별지1.과 같다", "별지 기재와 같다",
                    "<별지 2>와 같다", "별지기재와같다"):
        assert te._APPENDIX_REF_RE.search(wording), wording


def test_goods_text_split_and_appendix():
    blocks = {b["role"]: b for b in te.mark_blocks(FACTS_REFUSAL)}
    this_goods = te.split_goods(te.goods_text(blocks["this"]["text"], FACTS_REFUSAL))
    assert this_goods == [("컴퓨터", 9), ("노트북컴퓨터", 9), ("모니터", 9)]
    prior_1 = te.split_goods(te.goods_text(blocks["prior_1"]["text"], FACTS_REFUSAL))
    assert prior_1 == [("컴퓨터프로그래밍업", 42), ("컴퓨터 자문업", 42)]
    prior_2 = te.split_goods(te.goods_text(blocks["prior_2"]["text"], FACTS_REFUSAL))
    assert prior_2 == [("컴퓨터", 9), ("키보드", 9)]  # 별지1
    scope = {b["role"]: b for b in te.mark_blocks(FACTS_SCOPE)}
    assert te.split_goods(te.goods_text(scope["target"]["text"], FACTS_SCOPE)) == [
        ("신발", None), ("샌들", None)]
    assert te.split_goods("제9류의 가방; 제18류의 지갑") == [("가방", 9), ("지갑", 18)]


def test_map_goods_with_fake_map():
    goods_map = FakeGoodsMap()
    codes, details = te.map_goods([("컴퓨터", 9), ("노트북컴", 9), ("가방", None), ("없는것", 3)],
                                  goods_map)
    assert codes == {"G390802", "G250101"}
    methods = {d["name"]: d["method"] for d in details}
    assert methods["컴퓨터"] == "exact" and methods["노트북컴"].startswith("search:노트북컴퓨터")
    assert methods["가방"] == "exact" and methods["없는것"] == "fail"
    partial_only, detail = te.map_goods([("퓨터", 9)], goods_map)  # 부분 일치는 채택하지 않는다
    assert partial_only == set() and detail[0]["method"] == "fail"


def test_lookup_one_parses_and_picks_matching_item(tmp_path):
    row = te.lookup_one("registration", "4001234560000", fetch=lambda n, k: XML_OK,
                        raw_dir=tmp_path)
    assert row["결과"] == "ok" and row["Title"] == "COCO" and row["건수"] == "2"
    assert row["GoodClassificationCode"] == "09|42" and row["ViennaCode"] == "010101|020202"
    assert row["ApplicantName"] == "주식회사 코코"
    assert (tmp_path / "registration_4001234560000.xml").exists()
    first = te.lookup_one("registration", "4005555550000", fetch=lambda n, k: XML_OK)
    assert first["Title"] == "COCO"  # 일치 항목이 없으면 첫 항목
    empty = te.lookup_one("application", "4020120000001", fetch=lambda n, k: XML_EMPTY)
    assert empty["결과"] == "0건" and empty["건수"] == "0"
    error = te.lookup_one("registration", "4000000010000", fetch=lambda n, k: XML_ERROR)
    assert error["결과"] == "오류" and "resultCode=10" in error["오류"]

    def boom(number, kind):
        raise kc.KiprisNetworkError("timeout")

    assert te.lookup_one("registration", "1", fetch=boom)["결과"] == "오류"
    with pytest.raises(kc.CallBudgetExceeded):
        def exhausted(number, kind):
            raise kc.CallBudgetExceeded("budget")
        te.lookup_one("registration", "1", fetch=exhausted)


def _write_labels(base, rows):
    columns = ["심판번호", "종류", "상표B_번호", "상대표장_번호_후보", "상대표장_유형",
               "유사여부_확정", "llm_b_유사여부", "판단축_확정", "메모", *tc.ENRICH_COLUMNS]
    base.mkdir(parents=True, exist_ok=True)
    tc._write_csv(base / "labels.csv", columns, [{c: r.get(c, "") for c in columns} for r in rows])


def test_run_lookup_dry_run_idempotent_and_hard_cap(tmp_path):
    base = tmp_path / "trials"
    paths_ = tc.TrialPaths(base)
    _write_labels(base, [
        {"심판번호": "T1", "종류": "거절결정불복", "상표B_번호": "80250", "유사여부_확정": "유사",
         "llm_b_유사여부": "유사", "판단축_확정": "외관"},
        {"심판번호": "T2", "종류": "무효", "상표B_번호": "666832", "유사여부_확정": "비유사",
         "llm_b_유사여부": "비유사", "판단축_확정": "외관"},
    ])
    targets = [
        {"심판번호": "T1", "종류": "거절결정불복", "상표B_번호": "80250", "상대표장_유형": "선등록",
         "범주": te.CATEGORY_NUMBERED, "번호종류": "registration", "번호_정규화": "4100802500000"},
        {"심판번호": "T2", "종류": "무효", "상표B_번호": "666832", "상대표장_유형": "선등록",
         "범주": te.CATEGORY_NUMBERED, "번호종류": "registration", "번호_정규화": "4006668320000"},
        {"심판번호": "T3", "종류": "무효", "상표B_번호": "1", "상대표장_유형": "선등록",
         "범주": te.CATEGORY_NUMBERED, "번호종류": "registration", "번호_정규화": "4000000010000"},
        {"심판번호": "T4", "종류": "무효", "상표B_번호": "2", "상대표장_유형": "선등록",
         "범주": te.CATEGORY_NUMBERED, "번호종류": "registration", "번호_정규화": "4000000020000"},
        {"심판번호": "T5", "종류": "거절결정불복", "상표B_번호": "4020120012345",
         "상대표장_유형": "선출원", "범주": te.CATEGORY_NUMBERED, "번호종류": "application",
         "번호_정규화": "4020120012345"},
        {"심판번호": "T6", "종류": "거절결정불복", "상표B_번호": "344173",
         "상대표장_유형": "선등록|국제등록", "범주": te.CATEGORY_INTL, "번호종류": "international",
         "번호_정규화": "344173"},
    ]
    for item in targets:
        item.setdefault("문구", ""), item.setdefault("명칭_본문", "")
        item.setdefault("명칭_ocr", ""), item.setdefault("후보번호", "")
    tc._write_csv(base / "enrich_targets.csv", te.TARGET_COLUMNS, targets)
    existing = [{c: "" for c in te.PRIOR_MARK_COLUMNS} | {
        "번호종류": "registration", "번호_정규화": "4006668320000", "결과": "ok", "Title": "OLD"}]
    tc._write_csv(base / "prior_marks.csv", te.PRIOR_MARK_COLUMNS, existing)

    calls: list[tuple[str, str]] = []

    def fetch(number, kind):
        calls.append((kind, number))
        if kind == "international":
            return XML_EMPTY  # 검증 실패 → 그 종류 건너뜀
        if "-" in number:
            return XML_EMPTY  # 하이픈 형식은 이 가짜 서버가 모른다
        return XML_OK.replace("4001234560000", number)

    dry = te.run_lookup(paths_, max_calls=400, dry_run=True, fetch=fetch)
    assert dry["예상_호출"] == 5 and dry["계획"]["registration"]["이미_있음"] == 1 and calls == []
    with pytest.raises(SystemExit):
        te.run_lookup(paths_, max_calls=4, dry_run=False, fetch=fetch)  # 예상 5 > 캡 4
    assert calls == []

    report = te.run_lookup(paths_, max_calls=400, dry_run=False, fetch=fetch)
    tally = report["이번_실행"]
    assert tally["호출"] == 5 and tally["ok"] == 4 and tally["0건"] == 1
    assert tally["검증"]["international"].startswith("실패")
    marks = {(m["번호종류"], m["번호_정규화"]): m for m in te.load_prior_marks(paths_)}
    assert len(marks) == 6 and marks[("registration", "4006668320000")]["Title"] == "OLD"  # 멱등
    assert marks[("registration", "4100802500000")]["Title"] == "COCO"
    log = json.loads((base / "enrich_calls.json").read_text(encoding="utf-8"))
    assert log["합계_호출"] == 5 and len(log["runs"]) == 1
    labels = {r["심판번호"]: r for r in tc._read_csv(base / "labels.csv")}
    assert labels["T1"]["상대표장_명칭_kipris"] == "COCO"
    assert labels["T2"]["상대표장_명칭_kipris"] == "OLD"

    calls.clear()
    again = te.run_lookup(paths_, max_calls=400, dry_run=False, fetch=fetch)
    assert again["예상_호출"] == 0 and calls == []  # 기록된 번호는 0건이어도 건너뛴다(멱등)
    retry = te.run_lookup(paths_, max_calls=400, dry_run=False, fetch=fetch, retry_empty=True)
    assert retry["예상_호출"] == 1 and calls == [("international", "344173")]
    assert len(te.load_prior_marks(paths_)) == 6  # 다시 조회한 행은 교체된다

    # 하드캡: 예상 3건(= 캡)이지만 첫 번호가 13자리로 0건 → 하이픈 형식 검증에 1회 더 쓰여
    # 세 번째 호출 뒤 캡에 걸린다. 남은 번호는 조회하지 않는다.
    capped_base = tmp_path / "capped"
    capped = tc.TrialPaths(capped_base)
    _write_labels(capped_base, [])
    tc._write_csv(capped_base / "enrich_targets.csv", te.TARGET_COLUMNS,
                  [targets[0], targets[2], targets[3]])
    calls.clear()

    def hyphen_only(number, kind):
        calls.append((kind, number))
        return XML_OK if "-" in number else XML_EMPTY

    report = te.run_lookup(capped, max_calls=3, dry_run=False, fetch=hyphen_only)
    assert [n for _, n in calls] == ["4100802500000", "41-0080250-0000", "40-0000001-0000"]
    assert report["이번_실행"]["중단"].startswith("하드캡")
    assert report["이번_실행"]["검증"]["registration"] == "ok(하이픈 형식)"
    assert {m["결과"] for m in te.load_prior_marks(capped)} == {"ok"}


def test_merge_into_labels_preserves_other_columns(tmp_path):
    base = tmp_path / "trials"
    paths_ = tc.TrialPaths(base)
    _write_labels(base, [
        {"심판번호": "T1", "종류": "무효", "상표B_번호": "1", "유사여부_확정": "유사",
         "llm_b_유사여부": "유사", "판단축_확정": "외관|호칭", "메모": "사람 메모"},
        {"심판번호": "T1", "종류": "무효", "상표B_번호": "2", "유사여부_확정": "비유사",
         "llm_b_유사여부": "비유사"},
    ])
    updates = {("T1", "2"): {"상대표장_명칭_kipris": "NEW", "새열": "v"}}
    changed = te.merge_into_labels(paths_, updates)
    rows = tc._read_csv(base / "labels.csv")
    assert changed == 2
    assert rows[0]["메모"] == "사람 메모" and rows[0]["상대표장_명칭_kipris"] == ""
    assert rows[1]["상대표장_명칭_kipris"] == "NEW" and rows[1]["새열"] == "v"
    assert rows[0]["새열"] == ""
    assert "x4_goods" in rows[0]


def test_run_targets_and_goods_end_to_end(tmp_path):
    base = tmp_path / "trials"
    paths_ = tc.TrialPaths(base)
    _write_labels(base, [
        {"심판번호": "R1", "종류": "거절결정불복", "상표B_번호": "80250", "상대표장_유형": "선등록",
         "유사여부_확정": "유사", "llm_b_유사여부": "유사", "판단축_확정": "호칭"},
        {"심판번호": "R1", "종류": "거절결정불복", "상표B_번호": "666832",
         "상대표장_유형": "선등록", "유사여부_확정": "비유사", "llm_b_유사여부": "비유사",
         "판단축_확정": "상품"},
        {"심판번호": "S1", "종류": "권리범위확인(소극적)", "상표B_번호": "",
         "상대표장_유형": "확인대상표장", "유사여부_확정": "유사", "llm_b_유사여부": "유사",
         "판단축_확정": "호칭"},
        {"심판번호": "X1", "종류": "무효", "상표B_번호": "", "상대표장_유형": "",
         "유사여부_확정": "유사", "llm_b_유사여부": "제외"},  # 대상 아님
    ])
    (base / "text").mkdir()
    (base / "text" / "R1.txt").write_text(FACTS_REFUSAL, encoding="utf-8")
    (base / "text" / "S1.txt").write_text(FACTS_SCOPE, encoding="utf-8")
    tc._write_csv(base / "image_parts.csv", ["심판번호", "role", "ocr_text"],
                  [{"심판번호": "S1", "role": "target", "ocr_text": "모래알 OCR"}])

    summary = te.run_targets(paths_)
    assert summary["대상_행"] == 3
    assert summary["범주"] == {te.CATEGORY_NUMBERED: 2, te.CATEGORY_TARGET: 1}
    assert summary["고유_번호"] == {"registration": 2, "application": 0, "international": 0}
    assert summary["번호없음_명칭"] == {"행": 1, "본문": 1, "ocr만": 0, "없음": 0}
    target_rows = tc._read_csv(base / "enrich_targets.csv")
    targets = {(t["심판번호"], t["상표B_번호"]): t for t in target_rows}
    assert targets[("R1", "80250")]["번호_정규화"] == "4100802500000"
    assert targets[("R1", "666832")]["번호_정규화"] == "4006668320000"
    assert targets[("S1", "")]["명칭_본문"] == "모래알"
    assert targets[("S1", "")]["명칭_ocr"] == "모래알 OCR"
    labels = {(r["심판번호"], r["상표B_번호"]): r for r in tc._read_csv(base / "labels.csv")}
    assert labels[("S1", "")]["상대표장_명칭_본문"] == "모래알"
    assert labels[("R1", "80250")]["상대표장_번호_정규화"] == "4100802500000"

    report = te.run_goods(paths_, goods_map=FakeGoodsMap())
    assert report["대상_행"] == 3 and report["행_커버리지"]["both"] == 3
    assert report["명칭"]["매핑"] == report["명칭"]["고유"] and report["행_커버리지"]["별지"] == 1
    labels = {(r["심판번호"], r["상표B_번호"]): r for r in tc._read_csv(base / "labels.csv")}
    assert labels[("R1", "80250")]["goods_codes_this"] == "G390802"
    assert labels[("R1", "80250")]["goods_codes_prior"] == "S120602"
    assert labels[("R1", "80250")]["x4_goods"] == "0.0000"  # 컴퓨터 vs 프로그래밍업 — 교집합 없음
    assert labels[("R1", "666832")]["goods_codes_prior"] == "G390802"  # 별지1 → 컴퓨터, 키보드
    assert labels[("R1", "666832")]["x4_goods"] == "1.0000"
    assert labels[("S1", "")]["goods_codes_prior"] == "G270101"
    assert labels[("S1", "")]["x4_goods"] == "1.0000"
    assert labels[("X1", "")]["goods_codes_this"] == ""  # 대상 아닌 행은 손대지 않는다
    assert report["x4"]["유사"]["n"] == 2 and report["x4"]["비유사"]["n"] == 1
    status = te.run_status(paths_)
    assert status["상표명_확보"]["행"] == 1 and status["x4_있음"] == 3
