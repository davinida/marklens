"""DB 상표 유형 사전 계산 — 게시된 상표 메타 전건의 표시용 유형(문자·도형·결합)을
`ml/data/types.json`
에 쓴다(API 계약 v2 §2-2 `candidates[].type`, 엔진 E-4). 비공개 데이터 규칙: ml/data/ 는 커밋하지
않는다.

규칙(src/mark_type.classify_metadata): 상표구분 '도형상표' → 도형, '도형복합' → 결합 → (비어 있으면)
비엔나코드 + 상표명 → 결합, 비엔나코드만 → 도형, 상표명만 → 문자 → (셋 다 없으면) 이미지 OCR 폴백
(easyocr, auto_type 0.05/0.08; --no-ocr 이면 미상). 엔진(backend/src/core/multi_search.py)은 이
파일이
있으면 적재하고 없으면 같은 규칙을 요청 때 적용한다(OCR 폴백만 빠진다).

실행(프로젝트 루트, KIPRIS 호출 0):
    ml/venv/bin/python ml/scripts/precompute_types.py            # ml/data/kipris_metadata.json →
    ml/data/types.json
    ml/venv/bin/python ml/scripts/precompute_types.py --no-ocr   # OCR 폴백 없이(규칙만)
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from src import mark_type as mt  # noqa: E402

DEFAULT_META = ML_ROOT / "data" / "kipris_metadata.json"
DEFAULT_IMAGES = ML_ROOT / "data" / "images"
DEFAULT_OUT = ML_ROOT / "data" / "types.json"


class _OcrFallback:
    """easyocr 지연 로드 — 메타데이터로 결정되지 않는 상표에만 쓴다."""

    def __init__(self) -> None:
        self._reader = None

    def classify(self, image_path: Path) -> tuple[str | None, dict]:
        import numpy as np
        from PIL import Image

        if self._reader is None:
            import easyocr  # 무거운 import — 실제로 폴백이 필요할 때만

            self._reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
        with Image.open(image_path) as image:
            rgb = image.convert("RGB")
        width, height = rgb.size
        scale = max(1.0, mt.UPSCALE_MIN_SIDE / max(1, min(width, height)))
        scaled = rgb.resize((round(width * scale), round(height * scale))) if scale > 1.0 else rgb
        boxes = []
        for points, text, conf in self._reader.readtext(np.asarray(scaled), detail=1):
            xs = [float(p[0]) / scale for p in points]
            ys = [float(p[1]) / scale for p in points]
            bbox = (max(0, int(min(xs))), max(0, int(min(ys))),
                    min(width, int(np.ceil(max(xs)))), min(height, int(np.ceil(max(ys)))))
            boxes.append(mt.TextBox(bbox, str(text), float(conf)))
        text_ratio, fig_ratio = mt.area_ratios(rgb, boxes)
        kind, _dominant = mt.auto_type(text_ratio, fig_ratio)
        return kind, {"text_ratio": text_ratio, "fig_ratio": fig_ratio}


def classify_records(trademarks: list[dict], *, images_dir: Path, use_ocr: bool,
                     ocr: _OcrFallback | None = None) -> dict[str, dict]:
    """출원번호 → {"type", "source"(상표구분·비엔나코드·상표명·ocr·미상), ...}."""
    ocr = ocr or (_OcrFallback() if use_ocr else None)
    out: dict[str, dict] = {}
    for raw in trademarks:
        appno = str(raw.get("출원번호") or "").strip()
        if not appno:
            continue
        name = (raw.get("상표한글명") or raw.get("상표영문명") or "")
        kind, source = mt.classify_metadata(raw.get("상표구분"), raw.get("비엔나코드"), name)
        item: dict = {"type": kind, "source": source}
        if kind is None and use_ocr and ocr is not None:
            image_key = str(raw.get("이미지파일") or "").strip()
            path = images_dir / image_key if image_key else None
            if path is not None and path.exists():
                try:
                    kind, detail = ocr.classify(path)
                    item = {"type": kind, "source": "ocr", **detail}
                except Exception as exc:  # 이미지 하나의 실패가 전체를 막지 않게
                    item = {"type": None, "source": f"ocr 실패({type(exc).__name__})"}
        if item["type"] is None and item["source"] == "없음":
            item["source"] = "미상"
        out[appno] = item
    return out


def summarize(types: dict[str, dict]) -> dict:
    by_type = collections.Counter(str(item["type"]) for item in types.values())
    by_source = collections.Counter(item["source"] for item in types.values())
    return {"유형": dict(sorted(by_type.items())), "근거": dict(sorted(by_source.items()))}


def run(meta_path: Path, images_dir: Path, out_path: Path, *, use_ocr: bool) -> dict:
    data = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    trademarks = data.get("trademarks", data) if isinstance(data, dict) else data
    started = time.perf_counter()
    types = classify_records(trademarks, images_dir=images_dir, use_ocr=use_ocr)
    summary = summarize(types)
    dataset_info = data.get("dataset_info") if isinstance(data, dict) else None
    generation = (dataset_info or {}).get("생성일자")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(meta_path),
        "generation": generation,
        "rule": "상표구분 → 비엔나코드 → 상표명 → 이미지 OCR 폴백(auto_type 0.05/0.08)",
        "counts": summary,
        "types": types,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    summary["소요_ms"] = round((time.perf_counter() - started) * 1000)
    summary["건수"] = len(types)
    summary["경로"] = str(out_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--images", type=Path, default=DEFAULT_IMAGES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-ocr", action="store_true", help="OCR 폴백 없이 규칙만")
    args = parser.parse_args(argv)
    summary = run(args.meta, args.images, args.out, use_ocr=not args.no_ocr)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
