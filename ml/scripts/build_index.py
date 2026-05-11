#!/usr/bin/env python3
"""
이미지 폴더로부터 FAISS 인덱스를 빌드하는 CLI 스크립트.

이 스크립트는 지정된 이미지 폴더를 재귀 탐색하여 모든 이미지를
CLIP 임베딩으로 변환한 후, FAISS 인덱스와 메타데이터 JSON을 생성합니다.

사용법:
    python scripts/build_index.py --image-dir <이미지폴더> [옵션]

옵션:
    --image-dir   이미지가 있는 폴더 (필수)
    --output-dir  인덱스/메타데이터 저장 폴더 (기본: data/index)
    --index-name  인덱스 파일 이름 (기본: default)

생성 파일:
    {output-dir}/{index-name}.faiss          : FAISS 인덱스
    {output-dir}/{index-name}_metadata.json  : 메타데이터 매핑
"""

import os
# macOS Apple Silicon의 PyTorch + FAISS OpenMP 라이브러리 충돌 방지
# (이 줄은 반드시 다른 import보다 먼저 실행되어야 효과 있음)
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import argparse
import json
import sys
from pathlib import Path
from typing import List

import numpy as np

# 이 스크립트는 ml/scripts/에 위치하므로, src 모듈을 import하려면
# 부모 디렉토리(ml/)를 sys.path에 추가해야 합니다.
ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_ROOT))

from src.embedding import encode_image, EMBEDDING_DIM, MODEL_NAME, PRETRAINED
from src.search import build_index, save_index


# 지원하는 이미지 확장자 (대소문자 모두 허용)
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def find_images(image_dir: Path) -> List[Path]:
    """
    이미지 폴더를 재귀 탐색하여 지원하는 확장자의 모든 이미지 파일을 찾습니다.

    Args:
        image_dir: 이미지가 있는 폴더 경로.

    Returns:
        List[Path]: 정렬된 이미지 파일 경로 목록.
    """
    images = []
    for ext in SUPPORTED_EXTENSIONS:
        # 소문자와 대문자 둘 다 탐색
        images.extend(image_dir.rglob(f"*{ext}"))
        images.extend(image_dir.rglob(f"*{ext.upper()}"))
    return sorted(set(images))  # 중복 제거 + 정렬


def main():
    """CLI 진입점. 인자를 파싱하고 인덱스 빌드 파이프라인을 실행합니다."""
    parser = argparse.ArgumentParser(
        description="이미지 폴더로부터 FAISS 인덱스 빌드",
    )
    parser.add_argument(
        "--image-dir",
        type=Path,
        required=True,
        help="이미지가 있는 폴더 경로",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/index"),
        help="인덱스/메타데이터 저장 폴더 (기본: data/index)",
    )
    parser.add_argument(
        "--index-name",
        type=str,
        default="default",
        help="인덱스 파일 이름 (기본: default)",
    )
    args = parser.parse_args()

    # 1. 이미지 폴더 검증
    if not args.image_dir.exists():
        raise FileNotFoundError(f"Image directory not found: {args.image_dir}")
    if not args.image_dir.is_dir():
        raise ValueError(f"Not a directory: {args.image_dir}")

    # 2. 이미지 파일 목록 수집
    image_paths = find_images(args.image_dir)
    if len(image_paths) == 0:
        raise ValueError(
            f"No images found in {args.image_dir} "
            f"(supported: {sorted(SUPPORTED_EXTENSIONS)})"
        )

    print(f"Found {len(image_paths)} images in {args.image_dir}")

    # 3. 각 이미지를 임베딩으로 변환
    embeddings = []
    successful_paths = []
    failed_paths = []

    for i, path in enumerate(image_paths, 1):
        try:
            emb = encode_image(path)
            embeddings.append(emb)
            successful_paths.append(path)
            print(f"[{i}/{len(image_paths)}] OK: {path.name}")
        except Exception as e:
            failed_paths.append((str(path), str(e)))
            print(f"[{i}/{len(image_paths)}] SKIP: {path.name} ({e})")

    if len(embeddings) == 0:
        raise RuntimeError("All images failed to encode")

    # 4. 벡터 스택 (N, 512) 행렬 생성
    embeddings_array = np.stack(embeddings)
    print(f"\nEmbeddings shape: {embeddings_array.shape}")

    # 5. FAISS 인덱스 빌드
    index = build_index(embeddings_array)

    # 6. 출력 폴더 생성
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # 7. 인덱스 저장
    index_path = args.output_dir / f"{args.index_name}.faiss"
    save_index(index, index_path)
    print(f"Index saved: {index_path}")

    # 8. 메타데이터 저장 (image_dir 기준 상대 경로로 portable하게)
    metadata = {
        "model": MODEL_NAME,
        "pretrained": PRETRAINED,
        "embedding_dim": EMBEDDING_DIM,
        "total_images": len(successful_paths),
        "image_paths": [
            str(p.relative_to(args.image_dir)) for p in successful_paths
        ],
        "image_dir": str(args.image_dir.resolve()),
        "failed_count": len(failed_paths),
    }

    metadata_path = args.output_dir / f"{args.index_name}_metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"Metadata saved: {metadata_path}")

    # 9. 완료 요약
    print(f"\n=== Build complete: {len(successful_paths)} images indexed ===")
    if failed_paths:
        print(f"=== {len(failed_paths)} images skipped ===")


if __name__ == "__main__":
    main()
