"""유형 사전 계산(ml/scripts/precompute_types.py) — 메타데이터 규칙·요약·파일 출력(OCR 폴백
없이)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import precompute_types as pt

TRADEMARKS = [
    {"출원번호": "1", "상표구분": "도형상표", "비엔나코드": ["270522"], "상표한글명": "가"},
    {"출원번호": "2", "상표구분": "도형복합", "비엔나코드": [], "상표한글명": "나"},
    {"출원번호": "3", "상표구분": None, "비엔나코드": ["020901"], "상표한글명": "다"},
    {"출원번호": "4", "상표구분": "", "비엔나코드": ["020901"], "상표한글명": None,
     "상표영문명": None},
    {"출원번호": "5", "상표구분": "", "비엔나코드": [], "상표한글명": "", "상표영문명": "ENG"},
    {"출원번호": "6", "상표구분": "", "비엔나코드": [], "상표한글명": "", "이미지파일": "none.png"},
    {"출원번호": "", "상표구분": "도형상표"},  # 출원번호 없음 → 제외
]


def test_classify_records_without_ocr(tmp_path: Path):
    types = pt.classify_records(TRADEMARKS, images_dir=tmp_path, use_ocr=False)
    assert {k: (v["type"], v["source"]) for k, v in types.items()} == {
        "1": ("도형", "상표구분"), "2": ("결합", "상표구분"), "3": ("결합", "비엔나코드"),
        "4": ("도형", "비엔나코드"), "5": ("문자", "상표명"), "6": (None, "미상"),
    }
    summary = pt.summarize(types)
    assert summary["유형"] == {"None": 1, "결합": 2, "도형": 2, "문자": 1}
    assert summary["근거"] == {"미상": 1, "비엔나코드": 2, "상표구분": 2, "상표명": 1}


def test_run_writes_types_json(tmp_path: Path):
    meta = tmp_path / "kipris_metadata.json"
    meta.write_text(json.dumps({
        "dataset_info": {"생성일자": "2026-08-27"}, "trademarks": TRADEMARKS[:3],
    }, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "types.json"
    summary = pt.run(meta, tmp_path / "images", out, use_ocr=False)
    assert summary["건수"] == 3 and summary["경로"] == str(out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["generation"] == "2026-08-27"
    assert payload["types"]["3"] == {"type": "결합", "source": "비엔나코드"}
    assert payload["counts"]["유형"] == {"결합": 2, "도형": 1}
