"""심결문 이미지 추출·연결·쌍 생성 테스트 — 코드로 만든 픽스처 PDF 만 쓴다(실데이터·네트워크 없음).

픽스처 PDF: 제목 텍스트(PyMuPDF 내장 한글 폰트) + 표장 이미지 2개 + 모든 쪽에 반복되는 로고 +
소형 아이콘 + 문자만 있는 "구성:" + 벡터 그림만 있는 "구성:" + 기초사실 영역 밖의 이미지.
"""

from __future__ import annotations

import io

import pymupdf
import pytest
from PIL import Image

from scripts import trials_extract_images as tei

TRIAL = "2020101000001"
SCOPE_TRIAL = "2021100000002"


def _png(color: tuple[int, int, int], size: tuple[int, int]) -> bytes:
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _text(page, y: float, text: str, x: float = 60) -> None:
    page.insert_text((x, y), text, fontname="korea", fontsize=11)


@pytest.fixture
def refusal_pdf(tmp_path):
    """거절결정불복 꼴: 이 사건 출원상표 + 선등록상표 1·2·3(이미지·문자·벡터)."""
    doc = pymupdf.open()
    logo = _png((0, 0, 0), (100, 100))
    page0 = doc.new_page()
    logo_xref = page0.insert_image(pymupdf.Rect(500, 20, 560, 80), stream=logo)
    _text(page0, 120, "특허심판원 심결")
    _text(page0, 160, "1. 원 결정을 취소한다.")

    page1 = doc.new_page()
    page1.insert_image(pymupdf.Rect(500, 20, 560, 80), xref=logo_xref)
    _text(page1, 100, "1. 기초사실")
    _text(page1, 130, "가. 이 사건 출원상표/서비스표")
    _text(page1, 160, "(1) 출원번호/출원일: 제40-2020-0001234호/2020. 1. 1.")
    _text(page1, 190, "(2) 구성:")
    mark_a = page1.insert_image(
        pymupdf.Rect(140, 178, 260, 238), stream=_png((200, 30, 30), (120, 60))
    )
    page1.insert_image(pymupdf.Rect(270, 185, 290, 205), stream=_png((255, 0, 0), (20, 20)))
    _text(page1, 260, "(3) 지정상품: 상품류 구분 제9류의 컴퓨터")
    _text(page1, 300, "나. 원결정이유 및 선등록상표들")
    _text(page1, 330, "(1) 원결정이유")
    _text(page1, 360, "(2) 선등록상표 1")
    _text(page1, 390, "(가) 등록번호/출원일/등록일: 상표등록 제222222호/2010. 1. 1./2011. 1. 1.")
    _text(page1, 420, "(나) 구성:")
    page1.insert_image(pymupdf.Rect(140, 408, 230, 498), stream=_png((30, 30, 200), (90, 90)))
    _text(page1, 530, "(3) 선등록상표 2")
    _text(page1, 560, "(가) 등록번호: 상표등록 제333333호")
    _text(page1, 590, "(나) 구성: WORDMARK")

    page2 = doc.new_page()
    page2.insert_image(pymupdf.Rect(500, 20, 560, 80), xref=logo_xref)
    _text(page2, 100, "(4) 선등록상표 3")
    _text(page2, 130, "(가) 등록번호: 상표등록 제444444호")
    _text(page2, 160, "(나) 구성:")
    page2.draw_rect(pymupdf.Rect(140, 170, 220, 220), color=(0, 0, 1), fill=(0, 0, 1))
    page2.draw_circle((260, 195), 20, color=(1, 0, 0), fill=(1, 0, 0))
    _text(page2, 280, "2. 청구인 주장의 요지")
    page2.insert_image(pymupdf.Rect(140, 300, 220, 380), stream=_png((0, 200, 0), (80, 80)))
    # 판단 절의 인라인 재사용: 3쪽 중 2쪽(절반 초과)에 나와도 자리가 다르면 로고가 아니다
    page2.insert_image(pymupdf.Rect(300, 400, 360, 430), xref=mark_a)
    path = tmp_path / f"{TRIAL}.pdf"
    doc.save(path)
    return path, logo_xref


@pytest.fixture
def scope_pdf(tmp_path):
    """권리범위확인 꼴: 각주 표시 붙은 제목·"표 장 :" 라벨 + 확인대상표장. 다른 제목이 끼면 low."""
    doc = pymupdf.open()
    page = doc.new_page()
    _text(page, 100, "1. 기초사실")
    _text(page, 130, "가. 이 사건 등록서비스표1)")
    _text(page, 160, "(1) 등록번호/출원일/등록일: 서비스표등록 제111111호/2010. 1. 1./2011. 1. 1.")
    _text(page, 190, "(2) 표  장 :")
    page.insert_image(pymupdf.Rect(140, 178, 260, 238), stream=_png((20, 120, 20), (120, 60)))
    _text(page, 300, "나. 확인대상표장")
    _text(page, 330, "다. 심사 경과")
    _text(page, 360, "청구인은 2020. 1. 1. 확인대상표장을 사용하였다.")
    page.insert_image(pymupdf.Rect(140, 400, 240, 480), stream=_png((120, 20, 120), (100, 80)))
    _text(page, 520, "2. 청구인 주장의 요지")
    path = tmp_path / f"{SCOPE_TRIAL}.pdf"
    doc.save(path)
    return path


@pytest.fixture
def container_pdf(tmp_path):
    """'나. 확인대상표장들' 아래 '(1) 확인대상표장 1'·'(2) 확인대상표장 2' — 위는 묶음 제목."""
    doc = pymupdf.open()
    page = doc.new_page()
    _text(page, 100, "1. 기초사실")
    _text(page, 130, "가. 이 사건 등록상표")
    _text(page, 160, "(1) 등록번호: 상표등록 제111111호")
    _text(page, 190, "(2) 구")
    _text(page, 190, "성:", x=92)  # 조각난 "구성:" 라벨
    page.insert_image(pymupdf.Rect(140, 178, 260, 238), stream=_png((20, 120, 20), (120, 60)))
    _text(page, 300, "나. 확인대상표장들")
    _text(page, 330, "(1) 확인대상표장 1")
    _text(page, 360, "(가) 구성 :")
    page.insert_image(pymupdf.Rect(140, 348, 240, 408), stream=_png((120, 20, 120), (100, 60)))
    _text(page, 460, "(2) 확인대상표장 2")
    _text(page, 490, "(가) 구성 :")
    page.insert_image(pymupdf.Rect(140, 478, 240, 538), stream=_png((20, 20, 120), (100, 60)))
    _text(page, 600, "2. 청구인 주장의 요지")
    path = tmp_path / "2021100000003.pdf"
    doc.save(path)
    return path


def _by_role(rows: list[dict]) -> dict[str, dict]:
    return {row["role"]: row for row in rows}


def test_extract_links_images_to_headings(refusal_pdf, tmp_path):
    pdf_path, logo_xref = refusal_pdf
    rows = _by_role(tei.extract_document(pdf_path, tmp_path / "images"))

    assert set(rows) == {"this", "prior_1", "prior_2", "prior_3"}
    this = rows["this"]
    assert this["경로"] and (tmp_path / this["경로"]).exists()
    assert (int(this["폭"]), int(this["높이"])) == (120, 60)  # 소형 아이콘(20px)이 아니라 큰 이미지
    assert this["연결신뢰도"] == "high" and int(this["rendered"]) == 0
    assert "출원상표" in this["연결근거제목"]
    assert this["쪽"] == 2

    prior_1 = rows["prior_1"]
    assert prior_1["등록번호"] == "222222" and prior_1["연결신뢰도"] == "high"
    assert (int(prior_1["폭"]), int(prior_1["높이"])) == (90, 90)
    assert "선등록상표 1" in prior_1["연결근거제목"]  # 묶음 제목이 아니라 하위 제목에 연결

    prior_2 = rows["prior_2"]
    assert prior_2["경로"] == "" and prior_2["사유"] == "문자" and prior_2["등록번호"] == "333333"

    prior_3 = rows["prior_3"]
    assert int(prior_3["rendered"]) == 1 and prior_3["등록번호"] == "444444"
    with Image.open(tmp_path / prior_3["경로"]) as rendered:
        assert rendered.width >= 2 * 140 and rendered.height >= 2 * 50  # 2배 clip 렌더

    assert all(str(logo_xref) != row["xref"] for row in rows.values())  # 반복 로고 제외
    assert all("청구인" not in row["연결근거제목"] for row in rows.values())  # 영역 밖은 미연결


def test_repeated_and_small_images_are_excluded(refusal_pdf):
    pdf_path, logo_xref = refusal_pdf
    with pymupdf.open(pdf_path) as doc:
        assert tei.repeated_xrefs(doc) == {logo_xref}
        blocks = {block.role: block for block in tei.collect_blocks(doc)}
    assert blocks["this"].small_seen == 1 and len(blocks["this"].images) == 1


def test_container_headings_and_split_label(container_pdf, tmp_path):
    rows = _by_role(tei.extract_document(container_pdf, tmp_path / "images"))
    assert set(rows) == {"this", "target", "target_2"}  # 묶음 제목 행은 남지 않는다
    assert all(row["경로"] and row["연결신뢰도"] == "high" for row in rows.values())
    assert "확인대상표장 1" in rows["target"]["연결근거제목"]
    assert (int(rows["this"]["폭"]), int(rows["this"]["높이"])) == (120, 60)


def test_scope_layout_footnote_heading_and_low_confidence(scope_pdf, tmp_path):
    rows = _by_role(tei.extract_document(scope_pdf, tmp_path / "images"))
    assert rows["this"]["등록번호"] == "111111" and rows["this"]["연결신뢰도"] == "high"
    target = rows["target"]
    assert target["경로"] and target["연결신뢰도"] == "low"  # "다. 심사 경과"가 끼어 low


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("이 사건 출원상표", ("this", False, "")),
        ("이사건국제출원상표", ("this", False, "")),
        ("이 사건 등록서비스표1)", ("this", False, "")),
        ("선등록상표 2", ("prior", False, "2")),
        ("원결정이유및선등록상표/서비스표", ("prior", True, "")),
        ("선등록서비스표들 및 선출원서비스표", ("prior", True, "")),
        ("확인대상표장", ("target", False, "")),
        ("이 사건 등록상표와 확인대상표장의 유사 여부", None),
        ("확인대상표장이 이 사건 등록상표의 권리범위에 속하는지 여부", None),
        ("지정상품", None),
    ],
)
def test_classify_heading(body, expected):
    assert tei.classify_heading(body) == expected


def test_inline_text_ignores_remarks():
    assert tei.inline_text("(일반상표)") == ""
    assert tei.inline_text("2)") == ""
    assert tei.inline_text("ZOO BOUNCE") == "ZOO BOUNCE"


def test_target_trials_filters_agreeing_rows():
    rows = [
        {"심판번호": "1", "유사여부_확정": "유사", "llm_b_유사여부": "유사"},
        {"심판번호": "2", "유사여부_확정": "유사", "llm_b_유사여부": "제외"},
        {"심판번호": "3", "유사여부_확정": "제외", "llm_b_유사여부": "제외"},
        {"심판번호": "4", "유사여부_확정": "비유사", "llm_b_유사여부": "비유사"},
    ]
    trials, kept = tei.target_trials(rows)
    assert trials == ["1", "4"] and [r["심판번호"] for r in kept] == ["1", "4"]


def _label_row(number: str, kind: str, counterpart: str, verdict: str = "유사", **extra) -> dict:
    row = {
        "심판번호": number, "종류": kind, "상표B_번호": counterpart, "유사여부_확정": verdict,
        "llm_b_유사여부": verdict, "판단축_확정": "외관|호칭", "상표유형_확정": "도형",
        "상표유형_추정": "결합",
    }
    row.update(extra)
    return row


def test_build_pairs_matches_by_number_order_and_target(refusal_pdf, scope_pdf, tmp_path):
    index_rows = tei.extract_document(refusal_pdf[0], tmp_path / "images")
    index_rows += tei.extract_document(scope_pdf, tmp_path / "images")
    labels = [
        _label_row(TRIAL, "거절결정불복", "222222"),  # 번호 매칭 → prior_1
        _label_row(TRIAL, "거절결정불복", "333333", verdict="비유사"),  # prior_2 는 문자 → 탈락
        _label_row(TRIAL, "거절결정불복", "", 상표유형_확정=""),  # 3번째 행 → 순번 prior_3(벡터)
        _label_row(SCOPE_TRIAL, "권리범위확인(소극적)", "", verdict="비유사"),  # target
        _label_row("2099100000009", "무효", "555555"),  # 색인에 없음
    ]
    pairs, dropped = tei.build_pairs(labels, index_rows)

    assert [(p["상대role"], p["매칭"]) for p in pairs] == [
        ("prior_1", "번호"), ("prior_3", "순번"), ("target", "target"),
    ]
    assert pairs[0]["연결신뢰도"] == "high" and pairs[0]["rendered"] == 0
    assert pairs[1]["rendered"] == 1 and pairs[1]["상표유형"] == "결합"
    assert pairs[1]["상표유형_출처"] == "추정"
    assert pairs[2]["연결신뢰도"] == "low" and pairs[2]["라벨"] == "비유사"
    assert dropped == {"상대 문자": 1, "this 연결 실패": 1}
    assert set(pairs[0]) == set(tei.PAIR_COLUMNS)


def test_coverage_and_qa_sheet(refusal_pdf, tmp_path):
    base = tmp_path
    index_rows = tei.extract_document(refusal_pdf[0], base / "images")
    labels = [_label_row(TRIAL, "거절결정불복", "222222")]
    pairs, dropped = tei.build_pairs(labels, index_rows)
    report = tei.coverage(labels, index_rows, pairs, dropped)
    assert report["대상_행"] == 1 and report["이미지_확보_쌍"] == 1
    assert report["색인_이미지없음_사유"] == {"prior_2: 문자": 1}
    sheet = base / "qa.png"
    chosen = tei.render_qa_sheet(pairs, index_rows, base, sheet, n=30, seed=0)
    assert len(chosen) == 1 and sheet.exists() and sheet.stat().st_size > 0


def test_run_end_to_end_writes_index_pairs_and_report(refusal_pdf, tmp_path):
    base = tmp_path / "trials"
    (base / "pdf").mkdir(parents=True)
    (base / "pdf" / f"{TRIAL}.pdf").write_bytes(refusal_pdf[0].read_bytes())
    tei.write_csv(base / "labels.csv", list(_label_row("x", "y", "z")), [
        _label_row(TRIAL, "거절결정불복", "222222"),
        _label_row(TRIAL, "거절결정불복", "", verdict="제외"),  # 제외 행은 대상 아님
    ])
    report = tei.run(base, qa=True, qa_n=5, seed=0)
    assert report["이미지_확보_쌍"] == 1 and report["PDF_없음"] == 0
    assert (base / "image_index.csv").exists() and (base / "image_pairs.csv").exists()
    assert (base / "image_qa_sheet.png").exists() and (base / "image_coverage.json").exists()
    pairs = tei.read_csv(base / "image_pairs.csv")
    assert pairs[0]["이미지A"] == f"images/{TRIAL}/this.png"
    assert pairs[0]["이미지B"] == f"images/{TRIAL}/prior_1.png"
