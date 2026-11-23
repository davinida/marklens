"""견고성 점검용 시험 이미지를 만든다(저장소 밖 출력 폴더에만 — DB 로고를 쓰는 파일은 비공개).

    ml/venv/bin/python scripts/robustness/make_images.py [출력 폴더]
    (출력 폴더 기본값 ~/marklens-archive/robustness-YYYYMMDD/images)

깨진 파일·형식 위장·애니메이션·색 공간·치수 경계·픽셀 수 폭탄·큰 파일·SVG 와, 같은 로고의
크기·형식·여백만 다른 사본(결과 일관성 점검용)을 만든다. 만들 때마다 같은 바이트가 나오도록 난수
seed 를 고정한다.
"""

from __future__ import annotations

import io
import json
import random
import sys
import zlib
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
LOGO = (
    ROOT / "ml" / "data" / "images" / "4020240111417.png"
)  # 도형상표(DB 로고 — 결과 일관성용, 비공개)
TEXT_LOGO = ROOT / "ml" / "data" / "images" / "4020050047425.png"  # BLU hands(글자 있는 결합상표)


def _png(image: Image.Image, **kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", **kwargs)
    return buffer.getvalue()


def _jpeg(image: Image.Image, **kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", **kwargs)
    return buffer.getvalue()


def _webp(image: Image.Image, **kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", **kwargs)
    return buffer.getvalue()


def _sample(size=(256, 256), text="MARK") -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse(
        (size[0] * 0.15, size[1] * 0.15, size[0] * 0.85, size[1] * 0.85),
        outline="navy",
        width=max(2, size[0] // 32),
    )
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", size[1] // 5)
    except OSError:
        font = ImageFont.load_default()
    draw.text((size[0] * 0.25, size[1] * 0.4), text, fill="black", font=font)
    return image


def _png_bomb(width: int, height: int) -> bytes:
    """작은 파일·큰 치수 PNG(픽셀은 전부 0 — zlib 으로 거의 0 바이트). 한 줄씩 스트리밍으로 압축."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return len(data).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")

    compressor = zlib.compressobj(9)
    row = b"\x00" + b"\x00" * width  # 필터 0 + 회색조 8비트
    parts = [compressor.compress(row) for _ in range(min(height, 64))]
    idat = b"".join(parts)
    for _ in range(height - min(height, 64)):
        idat += compressor.compress(row)
    idat += compressor.flush()
    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 0, 0, 0, 0])
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    )


def build(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(0)
    files: dict[str, dict] = {}

    def put(name: str, data: bytes, mime: str, note: str) -> None:
        (out / name).write_bytes(data)
        files[name] = {"mime": mime, "bytes": len(data), "note": note}

    base = _sample()
    put("ok.png", _png(base), "image/png", "정상 PNG 256×256")
    put("ok.jpg", _jpeg(base, quality=90), "image/jpeg", "정상 JPEG")
    put("ok.webp", _webp(base), "image/webp", "정상 WebP")
    full = _png(base)
    put("broken_truncated.png", full[: len(full) // 2], "image/png", "PNG 를 절반에서 자름")
    put(
        "broken_garbage.png",
        bytes(rng.randrange(256) for _ in range(4096)),
        "image/png",
        "무작위 바이트",
    )
    put("empty.png", b"", "image/png", "0 바이트")
    put("jpeg_named_png.png", _jpeg(base), "image/png", "JPEG 내용 + .png 이름 + image/png")
    put("png_named_jpg.jpg", _png(base), "image/jpeg", "PNG 내용 + .jpg 이름 + image/jpeg")
    put("webp_as_png.png", _webp(base), "image/png", "WebP 내용 + image/png")
    buffer = io.BytesIO()
    base.save(buffer, format="GIF")
    put("static.gif", buffer.getvalue(), "image/gif", "정적 GIF(허용 형식 밖)")
    put("gif_as_png.png", buffer.getvalue(), "image/png", "GIF 내용 + image/png(위장)")
    put(
        "fake.heic",
        b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + bytes(64),
        "image/heic",
        "HEIC 머리만(디코더 없음)",
    )
    put(
        "heic_as_jpeg.jpg",
        b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + bytes(64),
        "image/jpeg",
        "HEIC 머리 + image/jpeg(아이폰 사진을 jpg 로 착각)",
    )
    frames = [_sample(text="A"), _sample(text="B")]
    buffer = io.BytesIO()
    frames[0].save(
        buffer, format="GIF", save_all=True, append_images=frames[1:], duration=200, loop=0
    )
    put("animated.gif", buffer.getvalue(), "image/gif", "애니메이션 GIF")
    buffer = io.BytesIO()
    frames[0].save(
        buffer, format="PNG", save_all=True, append_images=frames[1:], duration=200, loop=0
    )
    put("animated.png", buffer.getvalue(), "image/png", "APNG 2프레임(첫 프레임 A)")
    buffer = io.BytesIO()
    frames[0].save(buffer, format="WEBP", save_all=True, append_images=frames[1:], duration=200)
    put("animated.webp", buffer.getvalue(), "image/webp", "애니메이션 WebP")
    put("cmyk.jpg", _jpeg(base.convert("CMYK")), "image/jpeg", "CMYK JPEG")
    put("gray16.png", _png(base.convert("L").convert("I;16")), "image/png", "16비트 회색조 PNG")
    rgba = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    ImageDraw.Draw(rgba).ellipse((40, 40, 216, 216), fill=(10, 30, 120, 255))
    put("transparent.png", _png(rgba), "image/png", "투명 배경 + 남색 원")
    put(
        "fully_transparent.png",
        _png(Image.new("RGBA", (256, 256), (0, 0, 0, 0))),
        "image/png",
        "완전 투명",
    )
    put("palette.png", _png(base.convert("P")), "image/png", "팔레트 PNG")
    exif = Image.Exif()
    exif[0x0112] = 6  # 오른쪽으로 90° 돌려 보이라는 표시
    put(
        "exif_rotated.jpg",
        _jpeg(base.rotate(90, expand=True), exif=exif),
        "image/jpeg",
        "EXIF 회전 6(눕힌 원본 + 회전 표시)",
    )
    put("1x1.png", _png(Image.new("RGB", (1, 1), "black")), "image/png", "1×1")
    put("31x31.png", _png(_sample((31, 31))), "image/png", "최소 치수 바로 아래")
    put("32x32.png", _png(_sample((32, 32))), "image/png", "최소 치수")
    put("thin_4000x32.png", _png(_sample((4000, 32))), "image/png", "가늘고 긴 4000×32")
    put("thin_32x4000.png", _png(_sample((32, 4000))), "image/png", "가늘고 긴 32×4000")
    put(
        "max_4096.png",
        _png(Image.new("RGB", (4096, 4096), "white")),
        "image/png",
        "최대 치수(흰색)",
    )
    put(
        "over_4097x64.png",
        _png(Image.new("RGB", (4097, 64), "white")),
        "image/png",
        "최대 치수 + 1",
    )
    put(
        "bomb_20000.png",
        _png_bomb(20000, 20000),
        "image/png",
        "픽셀 수 폭탄 20000×20000(작은 파일)",
    )
    put(
        "bomb_4096_gray.png", _png_bomb(4096, 4096), "image/png", "4096×4096 회색조(허용 경계 폭탄)"
    )
    noise = Image.frombytes(
        "RGB", (2400, 2400), bytes(rng.randrange(256) for _ in range(2400 * 2400 * 3))
    )
    put(
        "big_12mb.png",
        _png(noise, compress_level=0),
        "image/png",
        "약 17MB 잡음 PNG(상한 10MiB 초과)",
    )
    near = Image.frombytes(
        "RGB", (1800, 1800), bytes(rng.randrange(256) for _ in range(1800 * 1800 * 3))
    )
    put("near_10mb.png", _png(near, compress_level=0), "image/png", "약 9.7MB(상한 바로 아래)")
    put(
        "logo.svg",
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256">'
            b'<circle cx="128" cy="128" r="100" fill="navy"/>'
            b"<script>alert(1)</script></svg>"
        ),
        "image/svg+xml",
        "SVG(스크립트 포함)",
    )
    put("white.png", _png(Image.new("RGB", (256, 256), "white")), "image/png", "하얀 빈 이미지")
    text_only = Image.new("RGB", (512, 160), "white")
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 96)
    except OSError:
        font = ImageFont.load_default()
    ImageDraw.Draw(text_only).text((20, 20), "COFFEE", fill="black", font=font)
    put("text_only_coffee.png", _png(text_only), "image/png", "글자만(COFFEE)")
    if LOGO.exists():
        logo = Image.open(LOGO).convert("RGB")
        put("logo_same.png", LOGO.read_bytes(), "image/png", "DB 도형상표 원본(비공개)")
        put(
            "logo_half.png",
            _png(logo.resize((max(32, logo.width // 2), max(32, logo.height // 2)))),
            "image/png",
            "같은 로고 절반 크기",
        )
        put("logo.jpg", _jpeg(logo, quality=92), "image/jpeg", "같은 로고 JPEG")
        put("logo.webp", _webp(logo, quality=92), "image/webp", "같은 로고 WebP")
        padded = Image.new("RGB", (int(logo.width * 1.6), int(logo.height * 1.6)), "white")
        padded.paste(logo, ((padded.width - logo.width) // 2, (padded.height - logo.height) // 2))
        put("logo_padded.png", _png(padded), "image/png", "같은 로고 + 흰 여백 30%")
        both = Image.new("RGB", (logo.width * 2 + 40, logo.height + 40), "white")
        both.paste(logo, (20, 20))
        if TEXT_LOGO.exists():
            other = Image.open(TEXT_LOGO).convert("RGB").resize(logo.size)
            both.paste(other, (logo.width + 20, 20))
        put("two_marks.png", _png(both), "image/png", "상표 두 개(도형상표 + BLU hands)")
    if TEXT_LOGO.exists():
        put("blu_hands.png", TEXT_LOGO.read_bytes(), "image/png", "DB 결합상표 BLU hands(비공개)")
    (out / "manifest.json").write_text(
        json.dumps(files, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return files


if __name__ == "__main__":
    target = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (Path.home() / "marklens-archive" / f"robustness-{date.today():%Y%m%d}" / "images")
    )
    made = build(target)
    print(f"{len(made)}개 → {target}")
