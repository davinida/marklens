"""
CLIP 기반 이미지 임베딩 생성 모듈.

이 모듈은 이미지를 OpenCLIP ViT-B/32 모델에 통과시켜
512차원 벡터(임베딩)로 변환하는 함수를 제공합니다.

버전이 지정된 전처리 계약으로 EXIF 회전, 알파 채널, 콘텐츠 품질,
모델 view 생성을 일관되게 처리합니다.
"""

import numpy as np
import open_clip
import torch

from src.contracts import (
    EMBEDDING_CONTRACT_VERSION as EMBEDDING_CONTRACT_VERSION,
)
from src.contracts import (
    EMBEDDING_DIM,
    MODEL_NAME,
    PRETRAINED,
)
from src.preprocess import (
    DEFAULT_PREPROCESS_VERSION,
    ImageInput,
    prepare_model_views,
)

# 사용할 CLIP 모델 아키텍처

# 사전학습 가중치 (LAION-2B 데이터셋으로 학습됨)

# 임베딩 벡터 차원

# Increment when model-view aggregation or normalization semantics change.

# Phase 1에서는 안정성을 위해 CPU 사용. MPS/GPU는 추후 검토.
DEVICE = "cpu"


# 모델을 한 번만 로드해서 재사용하기 위한 캐시
_model = None
_preprocess = None


def _load_model() -> tuple:
    """
    CLIP 모델과 전처리 함수를 로드합니다 (최초 1회만).

    이미 로드되어 있으면 캐시된 객체를 반환합니다.
    최초 호출 시에는 모델 가중치(~150MB) 다운로드가 발생할 수 있습니다.

    Returns:
        tuple: (model, preprocess) 튜플
    """
    global _model, _preprocess

    if _model is None:
        print("CLIP 모델 로딩 중... (최초 1회만, 시간이 걸릴 수 있습니다)")

        # open_clip은 (model, train_preprocess, val_preprocess) 3-튜플 반환
        # 우리는 추론(inference)만 하므로 train_preprocess는 사용 안 함
        model, _, preprocess = open_clip.create_model_and_transforms(
            MODEL_NAME,
            pretrained=PRETRAINED,
        )

        model = model.to(DEVICE)
        model.eval()  # 추론 모드 (Dropout, BatchNorm 등 비활성화)

        _model = model
        _preprocess = preprocess

        print("CLIP 모델 로딩 완료")

    return _model, _preprocess


def encode_image(
    image: ImageInput,
    *,
    preprocess_version: str = DEFAULT_PREPROCESS_VERSION,
) -> np.ndarray:
    """
    이미지를 CLIP 임베딩 벡터로 변환합니다.

    선택한 전처리 계약에 따라 하나 이상의 모델 view를 준비하고,
    각 view의 정규화된 임베딩을 평균한 뒤 다시 L2 정규화합니다.

    Args:
        image: 다음 중 하나:
            - str: 이미지 파일 경로
            - Path: 이미지 파일 경로 객체
            - bytes: 이미지 바이트 데이터 (FastAPI 업로드 등)
            - PIL.Image.Image: 이미 열린 PIL 이미지

        preprocess_version: 재현 가능한 전처리 계약 버전.

    Returns:
        np.ndarray: L2 정규화된 512차원 float32 벡터.
                    shape == (512,), norm == 1.0

    Raises:
        FileNotFoundError: 파일 경로가 존재하지 않는 경우.
        ValueError: 이미지를 열 수 없거나 크기가 너무 작은 경우.
    """
    model, preprocess = _load_model()

    # The legacy contract produces one historical center-crop input. The global
    # contract produces white/black letterboxed views and aggregates them.
    views = prepare_model_views(image, preprocess_version=preprocess_version)
    image_tensor = torch.stack([preprocess(view) for view in views]).to(DEVICE)

    # 추론 (gradient 계산 비활성화)
    with torch.no_grad():
        view_embeddings = model.encode_image(image_tensor)
        if view_embeddings.ndim != 2 or view_embeddings.shape != (
            len(views),
            EMBEDDING_DIM,
        ):
            raise ValueError(
                "Model returned an unexpected image embedding shape: "
                f"{tuple(view_embeddings.shape)}"
            )
        if not torch.isfinite(view_embeddings).all():
            raise ValueError("Model produced a non-finite image embedding")
        view_norms = view_embeddings.norm(dim=-1, keepdim=True)
        if torch.any(view_norms <= 0):
            raise ValueError("Model produced a zero-norm image embedding")
        view_embeddings = view_embeddings / view_norms

        if len(views) == 1:
            # Preserve the historical single-view normalization path exactly.
            embedding = view_embeddings
        else:
            embedding = view_embeddings.mean(dim=0, keepdim=True)
            aggregate_norm = embedding.norm(dim=-1, keepdim=True)
            if not torch.isfinite(aggregate_norm).all() or torch.any(
                aggregate_norm <= 0
            ):
                raise ValueError("Model-view aggregation produced an invalid embedding")
            embedding = embedding / aggregate_norm

    # numpy float32 1차원 배열로 변환
    return embedding.cpu().numpy().flatten().astype(np.float32)
