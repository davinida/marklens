#!/usr/bin/env python3
"""
빌드된 FAISS 인덱스에 대해 쿼리 이미지로 top-K 검색을 수행하는 CLI 스크립트.

이 스크립트는 build_index.py로 미리 만들어진 인덱스와 메타데이터를 로드한 후,
사용자가 지정한 쿼리 이미지를 임베딩으로 변환하여 가장 유사한 이미지 N개를 찾아냅니다.

사용법:
    python scripts/test_search.py --query <이미지> --index <인덱스> --metadata <메타> [--top-k N]

옵션:
    --query     쿼리 이미지 파일 경로 (필수)
    --index     FAISS 인덱스 파일 경로 (필수)
    --metadata  메타데이터 JSON 경로 (필수)
    --top-k     반환할 상위 결과 수 (기본: 5)
"""

import os
# macOS Apple Silicon의 PyTorch + FAISS OpenMP 라이브러리 충돌 방지
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# 이 스크립트는 ml/scripts/에 위치하므로, src 모듈을 import하려면
# 부모 디렉토리(ml/)를 sys.path에 추가해야 합니다.
ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_ROOT))

from src.embedding import encode_image, EMBEDDING_DIM, MODEL_NAME, PRETRAINED
from src.search import load_index, search


def load_metadata(metadata_path: Path) -> dict:
    """
    메타데이터 JSON 파일을 로드하고 필수 필드 존재를 검증합니다.

    Args:
        metadata_path: 메타데이터 JSON 파일 경로.

    Returns:
        dict: 파싱된 메타데이터 딕셔너리.

    Raises:
        FileNotFoundError: 파일이 존재하지 않는 경우.
        ValueError: 필수 필드가 누락된 경우.
    """
    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata file not found: {metadata_path}")

    with open(metadata_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # 필수 필드 검증
    required_fields = ["model", "pretrained", "embedding_dim", "total_images", "image_paths"]
    missing = [k for k in required_fields if k not in meta]
    if missing:
        raise ValueError(f"Metadata missing required fields: {missing}")

    return meta


def check_model_compatibility(meta: dict) -> None:
    """
    메타데이터의 모델 설정이 현재 환경과 일치하는지 검증합니다.

    인덱스가 만들어진 모델과 다른 모델로 검색하면 결과가 무의미하므로,
    안전을 위해 미리 차단합니다.

    Args:
        meta: load_metadata로 로드한 메타데이터 딕셔너리.

    Raises:
        ValueError: 모델, pretrained, 또는 embedding_dim이 일치하지 않는 경우.
    """
    if meta["model"] != MODEL_NAME:
        raise ValueError(
            f"Model mismatch: index built with '{meta['model']}', "
            f"current is '{MODEL_NAME}'"
        )
    if meta["pretrained"] != PRETRAINED:
        raise ValueError(
            f"Pretrained mismatch: index built with '{meta['pretrained']}', "
            f"current is '{PRETRAINED}'"
        )
    if meta["embedding_dim"] != EMBEDDING_DIM:
        raise ValueError(
            f"Embedding dim mismatch: index has {meta['embedding_dim']}, "
            f"current is {EMBEDDING_DIM}"
        )


def print_results(query_path: Path, image_paths: list, distances: np.ndarray,
                  indices: np.ndarray, ntotal: int) -> None:
    """
    검색 결과를 사람이 읽기 좋게 출력합니다.

    Args:
        query_path: 쿼리 이미지 경로 (표시용).
        image_paths: 메타데이터의 image_paths 리스트.
        distances: search 결과의 유사도 점수 배열.
        indices: search 결과의 인덱스 배열.
        ntotal: 인덱스에 포함된 전체 이미지 수.
    """
    print(f"\nQuery: {query_path}")
    print(f"Index contains {ntotal} images")
    print(f"\nTop-{len(distances)} results:")
    for rank, (d, i) in enumerate(zip(distances, indices), 1):
        # i가 인덱스 범위를 벗어나는 비정상 케이스 방어
        if 0 <= int(i) < len(image_paths):
            path_str = image_paths[int(i)]
        else:
            path_str = f"<invalid index {i}>"
        print(f"  {rank}. {path_str}  (similarity={float(d):.4f})")


def main():
    """CLI 진입점. 인자를 파싱하고 검색 파이프라인을 실행합니다."""
    parser = argparse.ArgumentParser(
        description="FAISS 인덱스에 대해 쿼리 이미지로 top-K 검색",
    )
    parser.add_argument(
        "--query",
        type=Path,
        required=True,
        help="쿼리 이미지 파일 경로",
    )
    parser.add_argument(
        "--index",
        type=Path,
        required=True,
        help="FAISS 인덱스 파일 경로 (.faiss)",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        required=True,
        help="메타데이터 JSON 파일 경로",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="반환할 상위 결과 수 (기본: 5)",
    )
    args = parser.parse_args()

    # 1. top-k 양수 검증
    if args.top_k < 1:
        raise ValueError(f"--top-k must be >= 1, got {args.top_k}")

    # 2. 입력 파일 존재 확인
    if not args.query.exists():
        raise FileNotFoundError(f"Query image not found: {args.query}")
    if not args.index.exists():
        raise FileNotFoundError(f"Index file not found: {args.index}")

    # 3. 메타데이터 로드 + 필수 필드 검증
    meta = load_metadata(args.metadata)

    # 4. 모델 호환성 검증 (인덱스와 현재 모델이 같아야 의미 있는 검색 가능)
    check_model_compatibility(meta)

    # 5. FAISS 인덱스 로드
    index = load_index(args.index)

    # 6. 인덱스 ↔ 메타데이터 일관성 검증
    if index.ntotal != meta["total_images"]:
        raise ValueError(
            f"Inconsistent index/metadata: "
            f"index has {index.ntotal} vectors, "
            f"metadata claims {meta['total_images']} images"
        )

    # 7. 쿼리 이미지 임베딩
    print(f"Encoding query: {args.query}")
    query_emb = encode_image(args.query)

    # 8. 검색
    distances, indices = search(index, query_emb, k=args.top_k)

    # 9. 결과 출력
    print_results(args.query, meta["image_paths"], distances, indices, index.ntotal)


if __name__ == "__main__":
    main()
