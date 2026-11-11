"""2차 수집 이미지 자동유형(trials_round_images) — 가짜 검출기, PDF 추출은 대역.
모델·네트워크 없음."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from scripts import trials_round_images as tri
from scripts import x2_split as xs


class FakeDetector:
    """검은 픽셀 덩어리를 글자 박스 하나로 본다."""

    def __init__(self) -> None:
        self.calls = 0

    def detect(self, image: Image.Image) -> list[xs.TextBox]:
        self.calls += 1
        black = (np.asarray(image.convert("RGB")) < 30).all(axis=2)
        if not black.any():
            return []
        ys, xs_ = np.nonzero(black)
        bbox = (int(xs_.min()), int(ys.min()), int(xs_.max()) + 1, int(ys.max()) + 1)
        return [xs.TextBox(bbox, "TEXT", 0.9)]


def _text_image() -> Image.Image:
    image = Image.new("RGB", (200, 80), "white")
    ImageDraw.Draw(image).rectangle((20, 20, 179, 59), fill="black")
    return image


def _figure_image() -> Image.Image:
    image = Image.new("RGB", (200, 200), "white")
    ImageDraw.Draw(image).ellipse((50, 50, 149, 149), fill=(220, 30, 30))
    return image


def _combined_image() -> Image.Image:
    image = Image.new("RGB", (300, 150), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((20, 35, 99, 114), fill=(30, 30, 220))
    draw.rectangle((140, 55, 279, 94), fill="black")
    return image


def test_round_image_types_figure_text_unknown_and_reuse(tmp_path, monkeypatch):
    base = tmp_path
    (base / "pdf").mkdir()
    numbers = ["FIG", "TXT", "COMBO", "TYPED", "SMALL", "NOBLOCK"]
    for number in numbers:
        (base / "pdf" / f"{number}.pdf").write_bytes(b"%PDF-1.4\n")
    images = {"FIG": _figure_image(), "TXT": _text_image(), "COMBO": _combined_image()}

    def fake_extract(pdf_path, out_dir, **_kwargs):
        number = pdf_path.stem
        other = {"심판번호": number, "role": "prior_1", "경로": "", "사유": "연결 실패"}
        if number == "NOBLOCK":  # 이 사건 표장 제목을 못 찾은 문서
            return [other]
        row = {"심판번호": number, "role": "this", "경로": "", "사유": ""}
        if number in images:
            target = out_dir / number
            target.mkdir(parents=True, exist_ok=True)
            images[number].save(target / "this.png")
            row["경로"] = (target / "this.png").relative_to(out_dir.parent).as_posix()
        else:
            row["사유"] = "문자" if number == "TYPED" else "소형"
        return [other, row]

    monkeypatch.setattr(tri.tei, "extract_document", fake_extract)
    detector = FakeDetector()
    report = tri.run(base, [*numbers, "MISSING"], detector=detector)
    rows = {row["심판번호"]: row for row in tri.read_csv(base / tri.OUT_NAME)}
    assert list(next(iter(rows.values()))) == tri.COLUMNS and set(rows) == set(numbers)
    assert (rows["FIG"]["자동유형"], rows["FIG"]["요부"]) == ("도형", "도형")
    assert rows["FIG"]["경로"] == "round_images/FIG/this.png"  # 기존 images/ 와 다른 폴더
    assert (rows["TXT"]["자동유형"], rows["TXT"]["요부"]) == ("문자", "문자")
    assert rows["COMBO"]["자동유형"] == "결합" and rows["COMBO"]["요부"] in ("문자", "도형")
    # 이미지 없이 글자로만 적힌 표장은 문자, 소형·제목 없음은 도형 여부를 모른다(자동유형 빈 값)
    assert (rows["TYPED"]["자동유형"], rows["TYPED"]["사유"]) == ("문자", "문자")
    assert (rows["SMALL"]["자동유형"], rows["SMALL"]["사유"]) == ("", "소형")
    assert (rows["NOBLOCK"]["자동유형"], rows["NOBLOCK"]["사유"]) == ("", tri.REASON_NO_BLOCK)
    assert all(row["role"] == "this" for row in rows.values())
    assert report["새로_잼"] == 6 and report["PDF_없음"] == 1 and detector.calls == 3
    assert report["자동유형"] == {"도형": 1, "문자": 2, "결합": 1, "(모름)": 2}

    # 이미 잰 건은 건너뛰고(큐에 없는 기존 행도 남는다), --force 는 다시 잰다
    again = tri.run(base, ["FIG", "TXT"], detector=detector)
    assert detector.calls == 3 and again["새로_잼"] == 0 and again["기존_재사용"] == 2
    assert len(tri.read_csv(base / tri.OUT_NAME)) == 6
    tri.run(base, ["FIG"], detector=detector, force=True)
    assert detector.calls == 4

    # trials_round2 가 읽는 형식: 요부가 도형이면 도형계, 자동유형이 빈 건은 근거에서 빠진다
    from backend.scripts import trials_round2 as r2

    assert r2.image_figure_types(tri.read_csv(base / tri.OUT_NAME)) == {
        "FIG": True, "TXT": False, "TYPED": False,
        "COMBO": rows["COMBO"]["요부"] == "도형",
    }
