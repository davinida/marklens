"""
CLIP 기반 이미지 임베딩 생성 모듈.

이 모듈은 이미지를 OpenCLIP ViT-B/32 모델에 통과시켜
512차원 벡터(임베딩)로 변환하는 함수를 제공합니다.

내부적으로 preprocess_image()를 호출하여 EXIF 회전, 알파 채널 처리,
크기 검증 등 안전한 전처리를 자동으로 수행합니다.
"""

from pathlib import Path
from typing import Union

import numpy as np
import torch
import open_clip
from PIL import Image

from src.preprocess import preprocess_image


# 사용할 CLIP 모델 아키텍처
MODEL_NAME = "ViT-B-32"

# 사전학습 가중치 (LAION-2B 데이터셋으로 학습됨)
PRETRAINED = "laion2b_s34b_b79k"

# 임베딩 벡터 차원
EMBEDDING_DIM = 512

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


def encode_image(image: Union[str, Path, bytes, Image.Image]) -> np.ndarray:
    """
    이미지를 CLIP 임베딩 벡터로 변환합니다.

    내부적으로 preprocess_image()를 호출하여 EXIF 회전 보정,
    알파 채널 처리, 크기 검증을 자동으로 수행합니다.

    Args:
        image: 다음 중 하나:
            - str: 이미지 파일 경로
            - Path: 이미지 파일 경로 객체
            - bytes: 이미지 바이트 데이터 (FastAPI 업로드 등)
            - PIL.Image.Image: 이미 열린 PIL 이미지

    Returns:
        np.ndarray: L2 정규화된 512차원 float32 벡터.
                    shape == (512,), norm == 1.0

    Raises:
        FileNotFoundError: 파일 경로가 존재하지 않는 경우.
        ValueError: 이미지를 열 수 없거나 크기가 너무 작은 경우.
    """
    model, preprocess = _load_model()

    # 다양한 입력을 표준 RGB PIL Image로 통일 (EXIF, 알파, 크기 자동 처리)
    image = preprocess_image(image)

    # CLIP 모델용 전처리 (리사이즈 + 정규화) + 배치 차원 추가 + 디바이스 이동
    image_tensor = preprocess(image).unsqueeze(0).to(DEVICE)

    # 추론 (gradient 계산 비활성화)
    with torch.no_grad():
        embedding = model.encode_image(image_tensor)
        # L2 정규화 (코사인 유사도 계산을 위해 norm을 1로 만듦)
        embedding = embedding / embedding.norm(dim=-1, keepdim=True)

    # numpy float32 1차원 배열로 변환
    return embedding.cpu().numpy().flatten().astype(np.float32)
