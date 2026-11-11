"""2차 수집 건의 이 사건 표장 이미지 자동유형 — "도형 추정"이 실제로 도형인지 잰다. KIPRIS 호출 0.

실행 (프로젝트 루트에서. easyocr 실제 모델 — x2_split 과 같은 검출기):
    ml/venv/bin/python ml/scripts/trials_round_images.py --queue ml/data/trials/round2_queue.csv

큐(심판번호 열) 가운데 PDF 가 있는 건마다 trials_extract_images.extract_document 로 표장 이미지를
뽑고(저장: round_images/{심판번호}/{role}.png — 기존 images/·image_index.csv·image_parts.csv 는
건드리지 않는다), 이 사건 표장(role=this)을 x2_split.analyze_image 로 문자/도형/결합·요부로 나눈다.
결과 round_image_types.csv:
  - 이미지가 있으면 자동유형·요부(text_ratio < 0.05 → 도형, fig_ratio < 0.08 → 문자, 그 외 결합).
  - 이미지가 없고 "구성:" 뒤가 글자뿐이면(사유 = 문자) 자동유형 = 문자.
  - 그 밖(소형·연결 실패·이 사건 표장 제목 없음)은 자동유형을 비운다 — 도형 여부를 모르는 건.
이미 잰 심판번호는 건너뛴다(--force 로 다시 잰다). backend/scripts/trials_round2.py 가 이 파일을
image_parts.csv 와 함께 읽어 도형 추정 조건의 정밀도를 다시 계산한다.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ML_ROOT.parent
for _root in (ML_ROOT, PROJECT_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from scripts import trials_extract_images as tei  # noqa: E402
from scripts import x2_split as xs  # noqa: E402

DEFAULT_BASE = tei.DEFAULT_BASE
IMAGE_DIR = "round_images"
OUT_NAME = "round_image_types.csv"
COLUMNS = [
    "심판번호", "role", "경로", "폭", "높이", "text_ratio", "fig_ratio", "자동유형", "요부",
    "ocr_text", "ocr_conf", "사유",
]
REASON_TEXT = "문자"  # extract_document: "구성:" 뒤에 글자만 있어 이미지를 만들지 않은 표장
REASON_NO_BLOCK = "이 사건 표장 제목 없음"


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def measure_trial(base: Path, number: str, detector: xs.TextDetector) -> dict | None:
    """심판번호 한 건 → round_image_types.csv 한 행. PDF 가 없으면 None."""
    pdf_path = base / "pdf" / f"{number}.pdf"
    if not pdf_path.exists():
        return None
    row = {column: "" for column in COLUMNS}
    row.update({"심판번호": number, "role": tei.ROLE_THIS})
    index_rows = tei.extract_document(pdf_path, base / IMAGE_DIR)
    this = next((item for item in index_rows if item["role"] == tei.ROLE_THIS), None)
    if this is None:
        row["사유"] = REASON_NO_BLOCK
    elif this["경로"]:
        image_path = base / this["경로"]
        parts = xs.analyze_image(image_path, detector, image_path.with_name("this_fig.png"))
        row.update({key: parts[key] for key in COLUMNS if key in parts})
        row["경로"] = this["경로"]
    else:
        row["사유"] = this["사유"]
        if this["사유"] == REASON_TEXT:
            row.update({"자동유형": "문자", "요부": "문자"})
    return row


def run(base: Path, numbers: list[str], *, detector: xs.TextDetector | None = None,
        force: bool = False) -> dict:
    out = base / OUT_NAME
    rows = {row["심판번호"]: row for row in read_csv(out)}
    todo = [number for number in dict.fromkeys(numbers) if force or number not in rows]
    measured = missing = 0
    for number in todo:
        if detector is None:
            detector = xs.EasyOcrDetector()  # 무거운 로드는 잴 것이 있을 때만
        row = measure_trial(base, number, detector)
        if row is None:
            missing += 1
            continue
        rows[number] = row
        measured += 1
    tei.write_csv(out, COLUMNS, [rows[number] for number in sorted(rows)])
    wanted = [rows[number] for number in dict.fromkeys(numbers) if number in rows]
    return {
        "큐": len(set(numbers)), "새로_잼": measured, "PDF_없음": missing,
        "기존_재사용": len(wanted) - measured,
        "자동유형": dict(Counter(row["자동유형"] or "(모름)" for row in wanted)),
        "요부": dict(Counter(row["요부"] or "(모름)" for row in wanted)),
        "모름_사유": dict(Counter(row["사유"] for row in wanted if not row["자동유형"])),
        "출력": str(out),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE, help="ml/data/trials")
    parser.add_argument("--queue", type=Path, required=True, help="심판번호 열이 있는 큐 CSV")
    parser.add_argument("--force", action="store_true", help="이미 잰 건도 다시 잰다")
    args = parser.parse_args(argv)
    numbers = [row["심판번호"].strip() for row in read_csv(args.queue) if row.get("심판번호")]
    report = run(args.base, numbers, force=args.force)
    for key, value in report.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
