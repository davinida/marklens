"""Image validation and deterministic model-view preparation."""

from __future__ import annotations

import io
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Union

from PIL import Image, ImageOps, ImageStat

ImageInput = Union[str, Path, bytes, Image.Image]

MIN_SIZE = 32
MAX_SIZE = 4096
MAX_DECODE_PIXELS = 64_000_000

LEGACY_PREPROCESS_VERSION = "clip-center-crop-v1"
GLOBAL_PREPROCESS_VERSION = "global-letterbox-dual-bg-v1"
DEFAULT_PREPROCESS_VERSION = LEGACY_PREPROCESS_VERSION

LETTERBOX_SIZE = 224
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

# Conservative rejection thresholds: near-uniform uploads are not meaningful
# marks, while the lowest-contrast real artifact in the current set remains far
# above these values.
MIN_CHANNEL_RANGE = 4.0
MIN_CHANNEL_STDDEV = 1.0


@dataclass(frozen=True)
class ContentMetrics:
    width: int
    height: int
    has_alpha: bool
    alpha_min: int
    alpha_max: int
    max_channel_range: float
    max_channel_stddev: float

    def to_dict(self) -> dict:
        return asdict(self)


def _open_image(image: ImageInput) -> Image.Image:
    if isinstance(image, bytes):
        source = Image.open(io.BytesIO(image))
    elif isinstance(image, (str, Path)):
        source = Image.open(image)
    elif isinstance(image, Image.Image):
        source = image
    else:
        raise ValueError(f"Unsupported image type: {type(image)}")

    width, height = source.size
    if width <= 0 or height <= 0:
        if not isinstance(image, Image.Image):
            source.close()
        raise ValueError(f"Image has invalid dimensions: {width}x{height}")
    if width * height > MAX_DECODE_PIXELS:
        if not isinstance(image, Image.Image):
            source.close()
        raise ValueError(
            f"Image has too many pixels: {width}x{height} "
            f"(maximum {MAX_DECODE_PIXELS:,})"
        )
    try:
        transposed = ImageOps.exif_transpose(source)
        transposed.load()
        result = transposed.copy()
        if transposed is not source:
            transposed.close()
        return result
    finally:
        if not isinstance(image, Image.Image):
            source.close()


def _rgba_has_alpha(image: Image.Image) -> bool:
    return image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    )


def _composite(image: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    rgba = image.convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, (*background, 255))
    return Image.alpha_composite(canvas, rgba).convert("RGB")


def inspect_image_content(image: Image.Image) -> ContentMetrics:
    """Measure visible color/alpha variation on a bounded probe image."""
    probe = image.copy()
    probe.thumbnail((256, 256), Image.Resampling.LANCZOS)
    has_alpha = _rgba_has_alpha(probe)

    if has_alpha:
        alpha = probe.convert("RGBA").getchannel("A")
        alpha_min, alpha_max = alpha.getextrema()
        composites = (_composite(probe, WHITE), _composite(probe, BLACK))
    else:
        alpha_min = alpha_max = 255
        composites = (probe.convert("RGB"),)

    channel_ranges: list[float] = []
    channel_stddevs: list[float] = []
    for composite in composites:
        stat = ImageStat.Stat(composite)
        channel_stddevs.extend(float(value) for value in stat.stddev)
        channel_ranges.extend(
            float(high - low) for low, high in composite.getextrema()
        )

    return ContentMetrics(
        width=image.width,
        height=image.height,
        has_alpha=has_alpha,
        alpha_min=int(alpha_min),
        alpha_max=int(alpha_max),
        max_channel_range=max(channel_ranges, default=0.0),
        max_channel_stddev=max(channel_stddevs, default=0.0),
    )


def validate_visual_content(image: Image.Image) -> ContentMetrics:
    """Reject empty-alpha, blank, and effectively uniform inputs."""
    metrics = inspect_image_content(image)
    if metrics.has_alpha and metrics.alpha_max == 0:
        raise ValueError("Image alpha channel is fully transparent")
    if (
        metrics.max_channel_range < MIN_CHANNEL_RANGE
        or metrics.max_channel_stddev < MIN_CHANNEL_STDDEV
    ):
        raise ValueError(
            "Image has insufficient visual contrast; upload a non-blank mark "
            f"(range={metrics.max_channel_range:.2f}, "
            f"stddev={metrics.max_channel_stddev:.2f})"
        )
    return metrics


def preprocess_image(
    image: ImageInput,
    *,
    background: tuple[int, int, int] = WHITE,
    validate_content: bool = True,
) -> Image.Image:
    """Return an EXIF-corrected RGB image while preserving legacy geometry."""
    opened = _open_image(image)
    width, height = opened.size
    if width < MIN_SIZE or height < MIN_SIZE:
        raise ValueError(
            f"Image too small: {width}x{height} (minimum {MIN_SIZE}x{MIN_SIZE})"
        )
    if validate_content:
        validate_visual_content(opened)

    if _rgba_has_alpha(opened):
        result = _composite(opened, background)
    else:
        result = opened.convert("RGB")

    if result.width > MAX_SIZE or result.height > MAX_SIZE:
        result.thumbnail((MAX_SIZE, MAX_SIZE), Image.Resampling.LANCZOS)
    return result


def letterbox_image(
    image: Image.Image,
    *,
    size: int = LETTERBOX_SIZE,
    background: tuple[int, int, int] = WHITE,
) -> Image.Image:
    """Fit the complete image into a square canvas without center cropping."""
    if size < 1:
        raise ValueError(f"letterbox size must be positive, got {size}")
    source = image.convert("RGB").copy()
    source.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (size, size), background)
    offset = ((size - source.width) // 2, (size - source.height) // 2)
    canvas.paste(source, offset)
    return canvas


def prepare_model_views(
    image: ImageInput,
    *,
    preprocess_version: str = DEFAULT_PREPROCESS_VERSION,
    backgrounds: Iterable[tuple[int, int, int]] = (WHITE, BLACK),
) -> tuple[Image.Image, ...]:
    """Prepare deterministic views for the selected embedding contract.

    The legacy version returns one geometry-preserving RGB image; OpenCLIP then
    applies its historical resize/center-crop transform. The global version
    composites alpha onto each requested background and letterboxes every view
    to 224x224, so the downstream OpenCLIP transform cannot crop the mark.
    """
    opened = _open_image(image)
    width, height = opened.size
    if width < MIN_SIZE or height < MIN_SIZE:
        raise ValueError(
            f"Image too small: {width}x{height} (minimum {MIN_SIZE}x{MIN_SIZE})"
        )
    validate_visual_content(opened)

    if preprocess_version == LEGACY_PREPROCESS_VERSION:
        return (preprocess_image(opened, validate_content=False),)
    if preprocess_version != GLOBAL_PREPROCESS_VERSION:
        raise ValueError(f"Unsupported preprocess version: {preprocess_version}")

    requested = tuple(backgrounds) if _rgba_has_alpha(opened) else (WHITE,)
    if not requested:
        raise ValueError("At least one model-view background is required")

    views: list[Image.Image] = []
    for background in requested:
        if len(background) != 3 or any(not 0 <= value <= 255 for value in background):
            raise ValueError(f"Invalid RGB background: {background}")
        composited = (
            _composite(opened, background)
            if _rgba_has_alpha(opened)
            else opened.convert("RGB")
        )
        views.append(
            letterbox_image(composited, size=LETTERBOX_SIZE, background=background)
        )
    return tuple(views)
