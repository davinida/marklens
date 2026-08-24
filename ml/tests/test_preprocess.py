import io

import pytest
from PIL import Image, ImageDraw
from src.preprocess import (
    GLOBAL_PREPROCESS_VERSION,
    LEGACY_PREPROCESS_VERSION,
    inspect_image_content,
    letterbox_image,
    prepare_model_views,
    preprocess_image,
)


def _line_logo(mode="RGB", color="black", background="white"):
    image = Image.new(mode, (320, 80), background)
    draw = ImageDraw.Draw(image)
    draw.line((20, 20, 300, 60), fill=color, width=8)
    return image


def test_blank_white_image_is_rejected():
    with pytest.raises(ValueError, match="insufficient visual contrast"):
        preprocess_image(Image.new("RGB", (128, 128), "white"))


def test_low_contrast_uniform_image_is_rejected():
    image = Image.new("RGB", (128, 128), (128, 128, 128))
    ImageDraw.Draw(image).point((64, 64), fill=(129, 129, 129))
    with pytest.raises(ValueError, match="insufficient visual contrast"):
        preprocess_image(image)


def test_empty_alpha_is_rejected():
    with pytest.raises(ValueError, match="fully transparent"):
        preprocess_image(Image.new("RGBA", (128, 128), (255, 255, 255, 0)))


def test_transparent_white_logo_survives_dual_background_views():
    image = Image.new("RGBA", (320, 80), (255, 255, 255, 0))
    ImageDraw.Draw(image).line((20, 40, 300, 40), fill=(255, 255, 255, 255), width=8)
    views = prepare_model_views(image, preprocess_version=GLOBAL_PREPROCESS_VERSION)
    assert len(views) == 2
    assert all(view.size == (224, 224) and view.mode == "RGB" for view in views)
    assert inspect_image_content(views[1]).max_channel_range > 200


def test_opaque_logo_uses_one_global_view_without_synthetic_black_border():
    views = prepare_model_views(
        _line_logo(),
        preprocess_version=GLOBAL_PREPROCESS_VERSION,
    )

    assert len(views) == 1
    assert views[0].getpixel((0, 0)) == (255, 255, 255)


def test_letterbox_preserves_full_wide_mark():
    source = _line_logo()
    boxed = letterbox_image(source, size=224)
    assert boxed.size == (224, 224)
    nonwhite = boxed.convert("L").point(lambda value: 255 if value < 250 else 0)
    bbox = nonwhite.getbbox()
    assert bbox is not None
    assert bbox[0] < 20 and bbox[2] > 204
    assert bbox[1] > 70 and bbox[3] < 154


def test_legacy_view_keeps_geometry_for_existing_index():
    source = _line_logo()
    (view,) = prepare_model_views(source, preprocess_version=LEGACY_PREPROCESS_VERSION)
    assert view.size == source.size
    assert view.mode == "RGB"


def test_bytes_input_and_alpha_compositing():
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((8, 8, 56, 56), fill=(255, 0, 0, 255))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    result = preprocess_image(buffer.getvalue())
    assert result.mode == "RGB"
    assert result.getpixel((0, 0)) == (255, 255, 255)
    assert result.getpixel((32, 32)) == (255, 0, 0)


def test_unknown_preprocess_version_fails():
    with pytest.raises(ValueError, match="Unsupported preprocess version"):
        prepare_model_views(_line_logo(), preprocess_version="future-v99")


def test_invalid_letterbox_size_fails():
    with pytest.raises(ValueError, match="positive"):
        letterbox_image(_line_logo(), size=0)
