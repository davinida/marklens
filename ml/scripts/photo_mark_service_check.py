"""사진 판정(src.photo_mark)이 서비스 경로의 CLIP 임베딩으로도 학습 때와 같게 도는지 확인하고,
DB 등록 상표가 사진으로 판정되는 비율(등록 로고를 사진으로 잘못 보는 비율의 근사)을 잰다.
2026-11-20 서비스 v1.4 반영 때. KIPRIS 호출 0, 파일을 고치지 않는다(x2 캐시도 읽기만).

서비스 경로 = 업로드 바이트 → backend `validation.validate_and_decode` → `engine.encode_image`(같은
OpenCLIP 모델·전처리 계약). 학습 경로 = 심결 추출 이미지는 x2_benchmark 캐시(`x2_cache_v0.npz`, 파일
경로로 encode_image), DB 이미지는 서비스 FAISS 색인 reconstruct(`pairs_features.
db_embedding_provider` 와 같음). 두 벡터의 코사인과 사진 판정 일치를 본다.

    ml/venv/bin/python ml/scripts/photo_mark_service_check.py
    # → ml/data/trials/photo_mark_service_check.{json,md} (약 3분 — 이미지 약 2,000장 CLIP 인코딩)
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
for root in (ML_ROOT, REPO_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from backend.src.core import engine, validation  # noqa: E402, I001  (torch 를 faiss 보다 먼저)
from src import photo_mark  # noqa: E402

from scripts.x2_benchmark import file_sha256, load_cache  # noqa: E402

DEFAULT_BASE = ML_ROOT / "data" / "trials"
DEFAULT_IMAGE_PAIRS = DEFAULT_BASE / "image_pairs_v1.csv"
DEFAULT_X2_CACHE = DEFAULT_BASE / "x2_cache_v0.npz"
DEFAULT_INDEX = ML_ROOT / "data" / "index" / "kipris.faiss"
DEFAULT_INDEX_META = ML_ROOT / "data" / "index" / "kipris_metadata.json"
DEFAULT_IMAGES = ML_ROOT / "data" / "images"
DEFAULT_METADATA = ML_ROOT / "data" / "kipris_metadata.json"
DEFAULT_OUT = DEFAULT_BASE / "photo_mark_service_check"


def service_vector(path: Path) -> np.ndarray | str:
    """서비스와 같은 경로 — 업로드 바이트를 검증·디코딩한 PIL 이미지를 engine.encode_image 로.
    서비스가 거절하는 파일(치수·형식 상한)은 거절 사유 문자열."""
    from fastapi import HTTPException

    try:
        image = validation.validate_and_decode(Path(path).read_bytes())
    except HTTPException as exc:
        return f"{exc.status_code}: {exc.detail}"
    return np.asarray(engine.encode_image(image), dtype=np.float32).reshape(-1)


def compare(pairs: list[tuple[str, np.ndarray, np.ndarray]]) -> dict:
    """[(식별자, 학습 벡터, 서비스 벡터)] → 코사인 요약·사진 판정 일치."""
    cosines, agree, train_photo, service_photo, disagreements = [], 0, 0, 0, []
    for key, trained, served in pairs:
        cosines.append(float(np.dot(trained, served)))
        flag_t, flag_s = photo_mark.is_photo(trained), photo_mark.is_photo(served)
        train_photo += flag_t
        service_photo += flag_s
        if flag_t == flag_s:
            agree += 1
        else:
            disagreements.append({"key": key, "학습": flag_t, "서비스": flag_s,
                                  "학습_점수": round(photo_mark.photo_score(trained), 4),
                                  "서비스_점수": round(photo_mark.photo_score(served), 4)})
    ordered = sorted(cosines)
    return {
        "n": len(pairs),
        "코사인_최소": round(ordered[0], 6) if ordered else None,
        "코사인_하위1%": round(ordered[int(0.01 * (len(ordered) - 1))], 6) if ordered else None,
        "코사인_중앙값": round(statistics.median(ordered), 6) if ordered else None,
        "판정_일치": agree,
        "사진_학습": train_photo,
        "사진_서비스": service_photo,
        "불일치": disagreements,
    }


def trial_paths(image_pairs: Path, base: Path) -> list[Path]:
    with open(image_pairs, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    names = sorted({row.get(column) or "" for row in rows for column in ("이미지A", "이미지B")})
    return [base / name for name in names if name and (base / name).exists()]


def run(args: argparse.Namespace) -> dict:
    started = time.perf_counter()
    cache = load_cache(args.x2_cache)
    trial_pairs, trial_missing, trial_rejected = [], 0, {}
    for path in trial_paths(args.image_pairs, args.base):
        trained = cache.get(file_sha256(path))
        if trained is None:
            trial_missing += 1
            continue
        served = service_vector(path)
        key = str(path.relative_to(args.base))
        if isinstance(served, str):
            trial_rejected[key] = served
            continue
        trial_pairs.append((key, np.asarray(trained, np.float32), served))
    trial = compare(trial_pairs) | {"캐시_없음": trial_missing, "서비스_거절": trial_rejected}

    from src.search import load_index  # torch 뒤에 faiss

    index = load_index(args.index)
    names = json.loads(args.index_meta.read_text(encoding="utf-8"))["image_paths"]
    data = json.loads(args.metadata.read_text(encoding="utf-8"))
    records = data.get("trademarks", data) if isinstance(data, dict) else data
    by_image = {str(r.get("이미지파일") or "").strip(): r for r in records}
    db_pairs, photo_rows, db_rejected = [], [], {}
    by_source: dict[str, dict] = {}  # 색인 벡터로 DB 전체(업로드 상한을 넘는 파일 포함)
    for pos, name in enumerate(names):
        trained = np.asarray(index.reconstruct(pos), dtype=np.float32)
        record = by_image.get(name) or {}
        slot = by_source.setdefault(record.get("수집_출처") or "알 수 없음", {"n": 0, "사진": 0})
        slot["n"] += 1
        slot["사진"] += int(photo_mark.is_photo(trained))
        served = service_vector(args.images / name)
        if isinstance(served, str):
            db_rejected[name] = served
        else:
            db_pairs.append((name, trained, served))
        if photo_mark.is_photo(trained) or (
                not isinstance(served, str) and photo_mark.is_photo(served)):
            photo_rows.append({
                "출원번호": record.get("출원번호"),
                "상표명": record.get("상표한글명") or record.get("상표영문명") or "",
                "수집_출처": record.get("수집_출처"),
                "상표구분": record.get("상표구분"),
                "점수_색인": round(photo_mark.photo_score(trained), 4),
                "점수_서비스": (None if isinstance(served, str)
                              else round(photo_mark.photo_score(served), 4)),
            })
    db = compare(db_pairs) | {"서비스_거절": db_rejected}
    return {
        "기준일": time.strftime("%Y-%m-%d"),
        "방향_파일": str(photo_mark.resolve_direction_path().relative_to(REPO_ROOT)),
        "심결_이미지": trial,
        "DB_이미지": db | {"출처별_사진(색인 벡터)": by_source, "사진_판정_목록": photo_rows,
                         "전체_색인": {"n": len(names), "사진": sum(
                             slot["사진"] for slot in by_source.values())}},
        "소요_초": round(time.perf_counter() - started, 1),
    }


def report(result: dict) -> str:
    def block(title: str, part: dict) -> list[str]:
        return [
            f"## {title}", "",
            f"- n {part['n']} · 코사인 최소 {part['코사인_최소']} · 하위 1% {part['코사인_하위1%']}"
            f" · 중앙값 {part['코사인_중앙값']}",
            f"- 사진 판정 일치 {part['판정_일치']}/{part['n']}"
            f" · 사진(학습 벡터) {part['사진_학습']}"
            f" · 사진(서비스 벡터) {part['사진_서비스']}",
            *(f"- 불일치 {item}" for item in part["불일치"]), "",
        ]

    db = result["DB_이미지"]
    lines = [
        "# 사진 판정 — 서비스 경로 확인 (2026-11-20)", "",
        f"방향 파일 `{result['방향_파일']}` · 소요 {result['소요_초']}초 · KIPRIS 호출 0", "",
        *block("심결 추출 이미지(학습 = x2 캐시)", result["심결_이미지"]),
        f"캐시에 없는 심결 이미지 {result['심결_이미지']['캐시_없음']}장 · 서비스가 거절하는 파일 "
        f"{len(result['심결_이미지']['서비스_거절'])}장(업로드 상한 — 비교에서 뺌): "
        + ", ".join(f"{k} ({v})" for k, v in result["심결_이미지"]["서비스_거절"].items()), "",
        *block("DB 등록 상표 이미지(학습 = FAISS 색인)", db),
        f"서비스가 거절하는 DB 파일 {len(db['서비스_거절'])}장(업로드 치수 상한 — 색인에는 "
        "있음)", "",
        f"DB 전체 {db['전체_색인']['n']}건(색인 벡터) 중 사진 판정 {db['전체_색인']['사진']}건 — "
        "출처별: " + " · ".join(
            f"{source} {slot['사진']}/{slot['n']}"
            for source, slot in sorted(db["출처별_사진(색인 벡터)"].items())), "",
        "| 출원번호 | 상표명 | 출처 | 상표구분 | 점수(색인) | 점수(서비스) |",
        "|---|---|---|---|---:|---:|",
        *(f"| {r['출원번호']} | {r['상표명']} | {r['수집_출처']} | {r['상표구분']} | "
          f"{r['점수_색인']} | {r['점수_서비스']} |" for r in db["사진_판정_목록"]),
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--image-pairs", type=Path, default=DEFAULT_IMAGE_PAIRS)
    parser.add_argument("--x2-cache", type=Path, default=DEFAULT_X2_CACHE)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--index-meta", type=Path, default=DEFAULT_INDEX_META)
    parser.add_argument("--images", type=Path, default=DEFAULT_IMAGES)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="출력 경로(확장자 없이)")
    args = parser.parse_args(argv)
    result = run(args)
    args.out.with_suffix(".json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.out.with_suffix(".md").write_text(report(result), encoding="utf-8")
    trial, db = result["심결_이미지"], result["DB_이미지"]
    print(f"심결 {trial['판정_일치']}/{trial['n']} 일치(코사인 최소 {trial['코사인_최소']}) · "
          f"DB {db['판정_일치']}/{db['n']} 일치(코사인 최소 {db['코사인_최소']}) · "
          f"DB 사진 {db['사진_학습']}/{db['n']}(색인)·{db['사진_서비스']}/{db['n']}(서비스)"
          f"·전체 {db['전체_색인']['사진']}/{db['전체_색인']['n']} · "
          f"{result['소요_초']}초")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
