"""
이미지 전처리 모듈.

다양한 형식의 이미지 입력(파일 경로, bytes, PIL Image)을 받아
EXIF 회전 보정, 알파 채널 처리, 크기 검증을 거친
표준화된 RGB PIL 이미지로 변환합니다.

이 모듈은 encode_image() 내부에서 자동 호출됩니다.
"""

import io
from pathlib import Path
from typing import Union

from PIL import Image, ImageOps


# 허용되는 최소 너비/높이 (픽셀)
MIN_SIZE = 32

# 허용되는 최대 너비/높이 (픽셀). 초과 시 비율 유지하며 자동 축소
MAX_SIZE = 4096


def preprocess_image(image: Union[str, Path, bytes, Image.Image]) -> Image.Image:
    """
    다양한 형식의 이미지 입력을 깨끗한 RGB PIL Image로 변환합니다.

    처리 단계:
    1. 입력 타입에 따라 PIL Image로 통일
    2. EXIF 회전 메타데이터 적용 (휴대폰 사진 자동 회전)
    3. 알파 채널 있으면 흰색 배경에 합성
    4. RGB 모드로 변환
    5. 크기 검증 (너무 작으면 ValueError, 너무 크면 비율 유지하며 축소)

    Args:
        image: 다음 중 하나:
            - str: 이미지 파일 경로
            - Path: 이미지 파일 경로 객체
            - bytes: 이미지 바이트 데이터 (FastAPI 업로드 등)
            - PIL.Image.Image: 이미 열린 PIL 이미지

    Returns:
        Image.Image: 전처리된 RGB PIL 이미지.

    Raises:
        FileNotFoundError: 파일 경로가 존재하지 않는 경우.
        ValueError: 이미지를 열 수 없거나 크기가 MIN_SIZE 미만인 경우.
    """
    # 1. 입력 타입을 PIL Image로 통일
    if isinstance(image, bytes):
        image = Image.open(io.BytesIO(image))
    elif isinstance(image, (str, Path)):
        image = Image.open(image)
    elif isinstance(image, Image.Image):
        pass  # already PIL
    else:
        raise ValueError(f"Unsupported image type: {type(image)}")

    # 2. EXIF 회전 보정 (휴대폰 사진은 회전 정보가 메타데이터에 있어,
    #    안 보정하면 옆으로 누워서 인식됨)
    image = ImageOps.exif_transpose(image)

    # 3. 알파 채널 처리 (RGBA, LA, P 모드는 투명도가 있을 수 있음)
    if image.mode in ("RGBA", "LA", "P"):
        # P(팔레트)와 LA(흑백+알파)는 일단 RGBA로 통일
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        # 흰 배경 위에 알파 채널을 마스크로 합성
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
    else:
        # 4. RGB 모드로 변환 (이미 RGB여도 안전)
        image = image.convert("RGB")

    # 5. 크기 검증
    w, h = image.size
    if w < MIN_SIZE or h < MIN_SIZE:
        raise ValueError(
            f"Image too small: {w}x{h} (minimum {MIN_SIZE}x{MIN_SIZE})"
        )

    # 6. 너무 크면 자동 축소 (메모리 보호 + CLIP은 어차피 224x224로
    #    리사이즈하므로 손실 없음)
    if w > MAX_SIZE or h > MAX_SIZE:
        image.thumbnail((MAX_SIZE, MAX_SIZE), Image.LANCZOS)

    return image
