"""
FAISS 기반 벡터 검색 모듈.

이 모듈은 CLIP 임베딩 벡터들을 FAISS 인덱스에 저장하고,
쿼리 벡터와 가장 유사한 Top-K 벡터를 검색하는 저수준 함수를 제공합니다.

이 모듈은 ML 엔진 계층(Layer 1)에 속합니다.
유사도 퍼센트 변환, 메타데이터 결합, Risk Score 계산 등 상위 로직은
별도 모듈(상위 계층)에서 처리됩니다.
"""

from pathlib import Path
from typing import Tuple, Union

import faiss
import numpy as np


# 임베딩 차원 (CLIP ViT-B/32 기준, embedding.py와 동일)
EMBEDDING_DIM = 512


def build_index(embeddings: np.ndarray) -> faiss.Index:
    """
    임베딩 벡터 배열로 FAISS 인덱스를 생성합니다.

    IndexFlatIP를 사용하므로 입력 벡터는 반드시 L2 정규화되어 있어야 합니다.
    L2 정규화된 벡터에 대해 Inner Product = 코사인 유사도.

    Args:
        embeddings: shape (N, 512), dtype float32인 numpy 배열.

    Returns:
        faiss.Index: 검색 가능한 FAISS 인덱스 (벡터 N개 포함).

    Raises:
        ValueError: 입력 shape이 (N, 512)가 아닌 경우.
    """
    # dtype 정규화: FAISS는 float32만 받음
    if embeddings.dtype != np.float32:
        embeddings = embeddings.astype(np.float32)

    # shape 검증
    if embeddings.ndim != 2 or embeddings.shape[1] != EMBEDDING_DIM:
        raise ValueError(
            f"Expected shape (N, {EMBEDDING_DIM}), got {embeddings.shape}"
        )

    # 인덱스 생성 (Inner Product 기반)
    index = faiss.IndexFlatIP(EMBEDDING_DIM)

    # FAISS는 내부적으로 C 라이브러리이기 때문에,
    # 파이썬에서 슬라이싱이나 transpose로 만들어진 비연속 메모리는
    # 받아들이지 못합니다. ascontiguousarray로 복사본을 만들어 안전하게 처리.
    if not embeddings.flags['C_CONTIGUOUS']:
        embeddings = np.ascontiguousarray(embeddings)

    index.add(embeddings)
    return index


def save_index(index: faiss.Index, path: Union[str, Path]) -> None:
    """
    FAISS 인덱스를 파일로 저장합니다.

    Args:
        index: 저장할 FAISS 인덱스.
        path: 저장할 파일 경로. 확장자는 .faiss 또는 .index 권장.
              상위 디렉토리가 없으면 자동 생성됩니다.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(path))


def load_index(path: Union[str, Path]) -> faiss.Index:
    """
    파일에서 FAISS 인덱스를 로드합니다.

    Args:
        path: 인덱스 파일 경로.

    Returns:
        faiss.Index: 로드된 FAISS 인덱스.

    Raises:
        FileNotFoundError: 파일이 존재하지 않는 경우.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Index file not found: {path}")
    return faiss.read_index(str(path))


def search(
    index: faiss.Index,
    query: np.ndarray,
    k: int = 5,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    인덱스에서 쿼리 벡터와 가장 유사한 Top-K 벡터를 검색합니다.

    Args:
        index: FAISS 인덱스.
        query: shape (512,) 1차원 또는 (1, 512) 2차원 쿼리 벡터.
        k: 반환할 결과 개수 (기본 5). 인덱스 크기보다 크면 자동 조정.

    Returns:
        (distances, indices) 튜플:
            - distances: shape (k,) float32. 유사도 점수
                        (IP 기반이므로 1.0에 가까울수록 유사).
                        이 값은 raw distance이며, 사용자 표시용
                        퍼센트 변환은 상위 계층에서 수행합니다.
            - indices: shape (k,) int64. 인덱스 내 벡터 순번.
    """
    # dtype 정규화
    if query.dtype != np.float32:
        query = query.astype(np.float32)

    # 차원 정규화: 1차원이면 (1, 512) 2차원으로 변환
    if query.ndim == 1:
        query = query.reshape(1, -1)

    # FAISS는 C-연속 메모리만 받음 (build_index와 동일 패턴)
    if not query.flags['C_CONTIGUOUS']:
        query = np.ascontiguousarray(query)

    # k가 인덱스 크기보다 크면 자동 조정
    actual_k = min(k, index.ntotal)

    distances, indices = index.search(query, actual_k)

    # 단일 쿼리이므로 (1, k) → (k,)로 1차원 변환
    return distances[0], indices[0]
