"""
업로드 이미지 검증.

확장자나 Content-Type 헤더는 1차 필터링용으로만 사용하고,
최종 검증은 파일 내용을 PIL 로 실제 디코딩해서 수행합니다.
검증 실패는 HTTPException 으로 변환되어 클라이언트에 적절한 4xx 응답을 보냅니다.
"""

import io
import warnings

from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError

from . import config


def validate_upload_size(raw_bytes: bytes) -> None:
    """크기 상한 검증."""
    if len(raw_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="빈 파일입니다.",
        )
    if len(raw_bytes) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"파일 크기 상한({config.MAX_UPLOAD_BYTES} bytes)을 초과했습니다. "
                f"받은 크기: {len(raw_bytes)} bytes."
            ),
        )


def validate_content_type(upload: UploadFile) -> None:
    """Content-Type 1차 필터. 진위는 디코딩으로 확인하므로 여기는 가볍게."""
    ct = (upload.content_type or "").lower()
    if ct and ct not in config.ALLOWED_IMAGE_MIME_TYPES:
        # Content-Type 헤더가 명시되어 있지만 허용 목록에 없을 때만 차단.
        # 헤더가 비어 있는 경우는 디코딩 검증으로 넘어가 결정.
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"지원하지 않는 Content-Type: {ct}. "
                f"허용: {sorted(config.ALLOWED_IMAGE_MIME_TYPES)}"
            ),
        )


def validate_and_decode(raw_bytes: bytes) -> Image.Image:
    """
    실제 디코딩으로 이미지 형식/치수를 최종 검증합니다.

    성공 시 RGB가 아니어도 그대로 PIL.Image 반환 (preprocess가 추후 RGB로 변환).
    """
    try:
        source = Image.open(io.BytesIO(raw_bytes))
    except UnidentifiedImageError:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="이미지로 디코딩할 수 없는 파일입니다.",
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미지 헤더를 읽을 수 없습니다.",
        ) from None

    fmt = (source.format or "").upper()
    if fmt not in config.ALLOWED_PIL_FORMATS:
        source.close()
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"지원하지 않는 이미지 형식: {fmt or '<unknown>'}. "
                f"허용: {sorted(config.ALLOWED_PIL_FORMATS)}"
            ),
        )

    w, h = source.size
    if w < config.MIN_IMAGE_DIM or h < config.MIN_IMAGE_DIM:
        source.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"이미지가 너무 작습니다: {w}x{h} "
                f"(최소 {config.MIN_IMAGE_DIM}x{config.MIN_IMAGE_DIM})"
            ),
        )
    if w > config.MAX_IMAGE_DIM or h > config.MAX_IMAGE_DIM:
        source.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"이미지 치수 상한을 초과했습니다: {w}x{h} "
                f"(최대 {config.MAX_IMAGE_DIM}x{config.MAX_IMAGE_DIM})"
            ),
        )
    if w * h > config.MAX_IMAGE_PIXELS:
        source.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"이미지 픽셀 수 상한을 초과했습니다: {w * h} "
                f"(최대 {config.MAX_IMAGE_PIXELS})"
            ),
        )

    try:
        # Pillow 자체 decompression-bomb 경고도 오류로 승격한다. 치수 검사를
        # 먼저 했으므로 허용 범위 이미지만 실제 픽셀 버퍼를 할당한다.
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            source.load()
        decoded = source.copy()
        decoded.info = dict(source.info)
        return decoded
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="안전하게 처리할 수 없는 이미지 크기입니다.",
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="손상되었거나 완전히 디코딩할 수 없는 이미지입니다.",
        ) from None
    finally:
        source.close()


def validate_upload(upload: UploadFile, raw_bytes: bytes) -> Image.Image:
    """
    엔드포인트가 한 번에 호출하는 통합 검증.

    검증 순서: Content-Type → 크기 → 디코딩 + 형식 + 치수.
    """
    validate_content_type(upload)
    validate_upload_size(raw_bytes)
    return validate_and_decode(raw_bytes)
