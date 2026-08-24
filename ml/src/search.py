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

from src.contracts import EMBEDDING_DIM

# 임베딩 차원 (CLIP ViT-B/32 기준, embedding.py와 동일)
NORM_ATOL = 1e-3


def _validated_vectors(
    vectors: np.ndarray,
    *,
    name: str,
    allow_single_vector: bool,
) -> np.ndarray:
    """Return a finite, normalized, C-contiguous float32 vector matrix."""
    try:
        values = np.asarray(vectors, dtype=np.float32)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must contain numeric values") from exc

    if allow_single_vector and values.ndim == 1:
        values = values.reshape(1, -1)
    if values.ndim != 2 or values.shape[1] != EMBEDDING_DIM:
        expected = (
            f"({EMBEDDING_DIM},) or (1, {EMBEDDING_DIM})"
            if allow_single_vector
            else f"(N, {EMBEDDING_DIM})"
        )
        raise ValueError(f"{name} must have shape {expected}, got {values.shape}")
    if values.shape[0] == 0:
        raise ValueError(f"{name} must contain at least one vector")
    if allow_single_vector and values.shape[0] != 1:
        raise ValueError(f"{name} must contain exactly one vector, got {values.shape[0]}")
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{name} contains NaN or infinite values")

    norms = np.linalg.norm(values, axis=1)
    if not np.all(np.isfinite(norms)) or not np.allclose(
        norms,
        1.0,
        rtol=0.0,
        atol=NORM_ATOL,
    ):
        raise ValueError(
            f"{name} must be L2-normalized within {NORM_ATOL}; "
            f"observed norm range {float(norms.min()):.6f}..{float(norms.max()):.6f}"
        )
    return np.ascontiguousarray(values, dtype=np.float32)


def validate_index(index: faiss.Index, *, require_vectors: bool = True) -> None:
    """Validate the FAISS contract used by MarkLens cosine search."""
    if not isinstance(index, faiss.Index):
        raise ValueError(f"Expected a FAISS index, got {type(index).__name__}")
    if index.d != EMBEDDING_DIM:
        raise ValueError(f"Index dimension must be {EMBEDDING_DIM}, got {index.d}")
    metric = getattr(index, "metric_type", None)
    if metric != faiss.METRIC_INNER_PRODUCT:
        raise ValueError(
            "Index metric must be inner product for normalized cosine search, "
            f"got {metric}"
        )
    if require_vectors and index.ntotal <= 0:
        raise ValueError("Index must contain at least one vector")


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
    embeddings = _validated_vectors(
        embeddings,
        name="embeddings",
        allow_single_vector=False,
    )

    # 인덱스 생성 (Inner Product 기반)
    index = faiss.IndexFlatIP(EMBEDDING_DIM)

    index.add(embeddings)
    validate_index(index)
    return index


def save_index(index: faiss.Index, path: Union[str, Path]) -> None:
    """
    FAISS 인덱스를 파일로 저장합니다.

    Args:
        index: 저장할 FAISS 인덱스.
        path: 저장할 파일 경로. 확장자는 .faiss 또는 .index 권장.
              상위 디렉토리가 없으면 자동 생성됩니다.
    """
    validate_index(index)
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
    index = faiss.read_index(str(path))
    validate_index(index)
    return index


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
    validate_index(index)
    if isinstance(k, bool) or not isinstance(k, (int, np.integer)) or k <= 0:
        raise ValueError(f"k must be a positive integer, got {k!r}")
    query = _validated_vectors(query, name="query", allow_single_vector=True)

    # k가 인덱스 크기보다 크면 자동 조정
    actual_k = min(k, index.ntotal)

    distances, indices = index.search(query, actual_k)
    if not np.all(np.isfinite(distances)):
        raise RuntimeError("FAISS returned non-finite distances")
    if np.any(indices < 0) or np.any(indices >= index.ntotal):
        raise RuntimeError("FAISS returned an out-of-range result index")

    # 단일 쿼리이므로 (1, k) → (k,)로 1차원 변환
    return distances[0], indices[0]
