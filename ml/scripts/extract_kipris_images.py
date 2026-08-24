#!/usr/bin/env python3
"""
KIPRIS PDF에서 로고 이미지를 추출하여 RGB PNG로 저장합니다.

사용법:
    python scripts/extract_kipris_images.py
    python scripts/extract_kipris_images.py --pdf-dir data/raw_kipris/pdfs \\
        --metadata data/kipris_metadata.json --output-dir data/images

알고리즘:
1. 메타데이터의 대상 출원번호에 대응하는 PDF만 처리.
2. pdfimages -all -p 로 모든 이미지 추출.
3. PDF별 등장 이미지의 (width, height)를 전체에 걸쳐 집계.
4. 두 가지 노이즈 필터 적용:
   - 같은 크기가 임계값 이상 PDF에 반복 등장 → 양식 요소 (예: 특허청 태극 로고)
   - 양 변 모두 임계값 미만 → 너무 작은 이미지
5. 남은 후보 중 면적이 가장 큰 이미지를 로고로 선택, PIL로 RGB PNG 저장.
6. 실패한 PDF는 목록에 기록하고 전체는 계속 진행.
"""

import argparse
import json
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image

# === 노이즈 식별 임계값 ===
# 같은 (w, h) 크기가 이 건수 이상의 PDF에 반복 등장하면 양식 요소로 간주
THRESH_REPEAT_COUNT = 50

# 양 변 모두 이 픽셀 미만이면 로고 후보에서 제외
# 100 선정 근거: 알려진 노이즈는 반복 등장 필터로 모두 잡힘. 이 임계값은 안전망 역할로,
# 가장 작은 알려진 노이즈(100x100 stamp)와 같은 값 이하면 잡음으로 간주.
# 실제 데이터에서 가장 작은 로고가 165x137(4020230126877)이었음.
THRESH_MIN_DIM = 100


def extract_all_images(pdf_path: Path, work_dir: Path) -> list[Path]:
    """
    pdfimages로 PDF의 모든 이미지를 work_dir에 추출하고 파일 경로 리스트 반환.

    -p 옵션으로 파일명에 페이지 번호를 인코딩합니다: img-PPP-NNN.{ext}.
    실패 시 빈 리스트 반환.
    """
    prefix = work_dir / "img"
    cmd = ["pdfimages", "-all", "-p", str(pdf_path), str(prefix)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return sorted(work_dir.iterdir())


def get_dimensions(path: Path):
    """이미지 파일을 PIL로 열어 (width, height) 반환. 못 열면 None."""
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


def parse_page_from_name(stem: str) -> int:
    """pdfimages -p가 생성한 'img-PPP-NNN' stem에서 페이지 번호를 추출."""
    parts = stem.split("-")
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return -1


def main():
    parser = argparse.ArgumentParser(description="KIPRIS PDF → 로고 PNG 추출")
    parser.add_argument(
        "--pdf-dir", type=Path, default=Path("data/raw_kipris/pdfs"),
        help="PDF 폴더 (기본: data/raw_kipris/pdfs)",
    )
    parser.add_argument(
        "--metadata", type=Path, default=Path("data/kipris_metadata.json"),
        help="메타데이터 JSON 경로 (기본: data/kipris_metadata.json)",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/images"),
        help="PNG 출력 폴더 (기본: data/images)",
    )
    args = parser.parse_args()

    # 메타데이터에서 대상 출원번호 로드
    with open(args.metadata, "r", encoding="utf-8") as f:
        meta = json.load(f)
    target_apps = {t["출원번호"] for t in meta["trademarks"]}
    print(f"대상 출원번호: {len(target_apps)}개")

    # ===== 1단계: 모든 PDF에서 이미지 추출 + 크기 집계 =====
    print()
    print("=== 1단계: 이미지 크기 집계 ===")
    pdf_files = sorted(args.pdf_dir.glob("*.pdf"))
    print(f"발견된 PDF: {len(pdf_files)}개")

    # PDF별 정보: app_no → list of (path, w, h, page)
    pdf_images: dict[str, list] = {}
    # 크기 → 그 크기를 포함하는 PDF 수 (PDF당 1회 카운트)
    size_in_pdfs: Counter = Counter()
    pdfimages_failures: list[tuple[str, str]] = []

    tmp_root = Path(tempfile.mkdtemp(prefix="kipris_extract_"))
    try:
        for pdf_path in pdf_files:
            app_no = pdf_path.stem
            if app_no not in target_apps:
                continue

            pdf_tmp = tmp_root / app_no
            pdf_tmp.mkdir()
            extracted = extract_all_images(pdf_path, pdf_tmp)

            if not extracted:
                pdfimages_failures.append((app_no, "pdfimages 추출 실패"))
                pdf_images[app_no] = []
                continue

            images_info = []
            seen_sizes = set()
            for ext_path in extracted:
                dim = get_dimensions(ext_path)
                if dim is None:
                    continue  # PIL이 못 여는 포맷 (jb2 등) — 후보 제외
                w, h = dim
                page = parse_page_from_name(ext_path.stem)
                images_info.append((ext_path, w, h, page))
                seen_sizes.add((w, h))
            pdf_images[app_no] = images_info
            for sz in seen_sizes:
                size_in_pdfs[sz] += 1

        # ===== 2단계: 노이즈 크기 식별 =====
        noise_sizes = {sz for sz, c in size_in_pdfs.items() if c >= THRESH_REPEAT_COUNT}
        print()
        print("=== 2단계: 노이즈 식별 ===")
        print(f"  임계값 1 (반복 등장): >= {THRESH_REPEAT_COUNT}개 PDF에 동일 크기 출현")
        print(f"  임계값 2 (너무 작음): width < {THRESH_MIN_DIM} AND height < {THRESH_MIN_DIM}")
        print()
        print(f"  반복 출현으로 노이즈 식별된 크기 ({len(noise_sizes)}개):")
        for sz in sorted(noise_sizes, key=lambda x: x[0] * x[1]):
            print(f"    {sz[0]}x{sz[1]} (등장 PDFs: {size_in_pdfs[sz]}/{len(pdf_images)})")

        # ===== 3단계: PDF별 로고 선택 + PNG 저장 =====
        args.output_dir.mkdir(parents=True, exist_ok=True)
        successes: list[tuple[str, int, int, int]] = []
        failures: list[tuple[str, str]] = list(pdfimages_failures)

        for app_no, images_info in pdf_images.items():
            if not images_info:
                continue  # 이미 pdfimages 실패로 기록됨

            # 노이즈 필터 적용
            candidates = []
            for path, w, h, page in images_info:
                if (w, h) in noise_sizes:
                    continue
                if w < THRESH_MIN_DIM and h < THRESH_MIN_DIM:
                    continue
                candidates.append((path, w, h, page))

            if not candidates:
                failures.append((app_no, "노이즈 필터 통과한 후보 0개"))
                continue

            # 가장 큰 이미지 (면적 기준)
            candidates.sort(key=lambda x: x[1] * x[2], reverse=True)
            chosen_path, w, h, page = candidates[0]

            try:
                with Image.open(chosen_path) as im:
                    im_rgb = im.convert("RGB")
                    out_path = args.output_dir / f"{app_no}.png"
                    im_rgb.save(out_path, "PNG")
                successes.append((app_no, w, h, page))
            except Exception as e:
                failures.append((app_no, f"PNG 저장 실패: {e}"))

        # ===== 결과 출력 =====
        print()
        print("=== 3단계: 추출 결과 ===")
        print(f"  성공: {len(successes)} / {len(pdf_images)}")
        print(f"  실패: {len(failures)}")

        if successes:
            print()
            print("  성공 샘플 3건 (출원번호: WxH, page):")
            for app_no, w, h, page in successes[:3]:
                print(f"    {app_no}: {w}x{h} (page {page})")
            print()
            # 선택된 로고들의 크기 분포 (참고용)
            areas = sorted([w * h for _, w, h, _ in successes])
            print(
                "  선택된 로고 면적 분포: "
                f"min={areas[0]:,} median={areas[len(areas) // 2]:,} "
                f"max={areas[-1]:,}"
            )
            pages_dist = Counter(p for _, _, _, p in successes)
            print(f"  로고 페이지 분포: {dict(pages_dist)}")

        if failures:
            print()
            print("  실패 목록:")
            for app_no, reason in failures:
                print(f"    {app_no}: {reason}")

        print()
        print(f"  출력 폴더: {args.output_dir}")
        print(f"  생성된 PNG 수: {len(successes)}")

    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
