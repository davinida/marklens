"""Deterministic perturbations and metric aggregation for robustness audits."""

from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import os
import platform
import random
import tempfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from statistics import mean, median
from typing import Any, Callable, Sequence

import numpy as np
from PIL import Image, ImageOps

BENCHMARK_VERSION = "visual-robustness-v2"
TRANSFORM_VERSION = "bounded-perturbations-v1"
TRANSFORM_NAMES = ("rotate_8deg", "center_crop_90pct", "gray_margin_20pct", "jpeg_q60")


def pixel_sha256(image: Image.Image) -> str:
    digest = hashlib.sha256()
    digest.update(image.mode.encode("ascii"))
    digest.update(f"{image.width}x{image.height}".encode("ascii"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def _rgb_on_white(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(canvas, rgba).convert("RGB")
    return image.convert("RGB")


def perturb_image(image: Image.Image, transform_name: str) -> Image.Image:
    source = _rgb_on_white(image)
    width, height = source.size
    if transform_name == "rotate_8deg":
        return source.rotate(
            8.0,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=(255, 255, 255),
        )
    if transform_name == "center_crop_90pct":
        crop_width = max(1, round(width * 0.9))
        crop_height = max(1, round(height * 0.9))
        left = (width - crop_width) // 2
        top = (height - crop_height) // 2
        cropped = source.crop((left, top, left + crop_width, top + crop_height))
        return cropped.resize((width, height), Image.Resampling.LANCZOS)
    if transform_name == "gray_margin_20pct":
        inner_width = max(1, round(width * 0.8))
        inner_height = max(1, round(height * 0.8))
        inner = source.resize((inner_width, inner_height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (width, height), (224, 224, 224))
        canvas.paste(inner, ((width - inner_width) // 2, (height - inner_height) // 2))
        return canvas
    if transform_name == "jpeg_q60":
        encoded = io.BytesIO()
        source.save(encoded, format="JPEG", quality=60, optimize=False, progressive=False)
        encoded.seek(0)
        with Image.open(encoded) as decoded:
            return decoded.convert("RGB").copy()
    raise ValueError(f"Unsupported perturbation: {transform_name}")


def select_sample(keys: Sequence[str], *, sample_size: int, seed: int) -> list[str]:
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    ordered = sorted(keys, key=str.casefold)
    if sample_size > len(ordered):
        raise ValueError(
            f"sample_size {sample_size} exceeds available image count {len(ordered)}"
        )
    selected = random.Random(seed).sample(ordered, sample_size)
    return sorted(selected, key=str.casefold)


def resolve_key(image_dir: Path, key: str) -> Path:
    normalized = key.replace("\\", "/")
    key_path = PurePosixPath(normalized)
    if key_path.is_absolute() or any(part in ("", ".", "..") for part in key_path.parts):
        raise ValueError(f"Unsafe image key: {key!r}")
    root = image_dir.resolve(strict=True)
    path = root.joinpath(*key_path.parts).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Image key escapes image-dir: {key!r}") from exc
    if not path.is_file():
        raise FileNotFoundError(f"Image is missing: {key}")
    return path


def prepare_audit(
    image_dir: Path,
    keys: Sequence[str],
    *,
    sample_size: int,
    seed: int,
) -> tuple[dict[str, Any], dict[tuple[str, str], Image.Image]]:
    """Decode a bounded sample and create deterministic perturbations."""
    selected = select_sample(keys, sample_size=sample_size, seed=seed)
    generated: dict[tuple[str, str], Image.Image] = {}
    items: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for key in selected:
        try:
            path = resolve_key(image_dir, key)
            with Image.open(path) as opened:
                source = opened.copy()
            original_hash = pixel_sha256(_rgb_on_white(source))
            transforms: dict[str, dict[str, Any]] = {}
            for transform_name in TRANSFORM_NAMES:
                transformed = perturb_image(source, transform_name)
                generated[(key, transform_name)] = transformed
                transformed_hash = pixel_sha256(transformed)
                transforms[transform_name] = {
                    "pixel_sha256": transformed_hash,
                    "changed": transformed_hash != original_hash,
                    "width": transformed.width,
                    "height": transformed.height,
                }
            items.append(
                {
                    "image_key": key,
                    "original_pixel_sha256": original_hash,
                    "transforms": transforms,
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "image_key": key,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

    transform_attempts = len(selected) * len(TRANSFORM_NAMES)
    changed = sum(
        transform["changed"]
        for item in items
        for transform in item["transforms"].values()
    )
    report = {
        "benchmark_version": BENCHMARK_VERSION,
        "transform_version": TRANSFORM_VERSION,
        "mode": "prepare_only",
        "seed": seed,
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pillow": importlib.metadata.version("Pillow"),
        },
        "requested_sample_size": sample_size,
        "selected_image_keys": selected,
        "decoded_image_count": len(items),
        "decode_failure_count": len(failures),
        "transform_attempt_count": transform_attempts,
        "transform_success_count": len(generated),
        "changed_transform_count": changed,
        "transform_config": {
            "rotate_8deg": {"degrees": 8.0, "expand": False},
            "center_crop_90pct": {"retained_fraction": 0.9},
            "gray_margin_20pct": {"content_fraction": 0.8, "background": [224, 224, 224]},
            "jpeg_q60": {"quality": 60},
        },
        "items": items,
        "failures": failures,
    }
    return report, generated


def evaluate_model_robustness(
    report: dict[str, Any],
    generated: dict[tuple[str, str], Image.Image],
    *,
    keys: Sequence[str],
    image_dir: Path,
    index: Any,
    encoder: Callable[[Image.Image], np.ndarray],
    search_fn: Callable[..., tuple[np.ndarray, np.ndarray]],
    score_fn: Callable[[np.ndarray], dict[str, Any]],
) -> dict[str, Any]:
    """Add retrieval/similarity/status metrics using injected model functions."""
    if report["decode_failure_count"]:
        raise RuntimeError("Cannot run model metrics while sampled images failed to decode")
    key_to_index = {key: index_number for index_number, key in enumerate(keys)}
    records: list[dict[str, Any]] = []
    aggregate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    baseline_status: dict[str, str] = {}

    for key in report["selected_image_keys"]:
        expected_index = key_to_index[key]
        original_path = resolve_key(image_dir, key)
        with Image.open(original_path) as original:
            variants = {"original": original.copy()}
        variants.update(
            {
                name: generated[(key, name)]
                for name in TRANSFORM_NAMES
            }
        )
        for transform_name, image in variants.items():
            query = encoder(image)
            distances, indices = search_fn(index, query, k=min(5, index.ntotal))
            expected_vector = np.asarray(index.reconstruct(expected_index), dtype=np.float32)
            target_similarity = float(np.dot(query, expected_vector))
            positions = np.flatnonzero(indices == expected_index)
            expected_rank = int(positions[0] + 1) if positions.size else None
            status = score_fn(distances)["status_code"]
            if transform_name == "original":
                baseline_status[key] = status
            record = {
                "image_key": key,
                "transform": transform_name,
                "target_similarity": target_similarity,
                "expected_rank_within_5": expected_rank,
                "recall_at_1": expected_rank == 1,
                "recall_at_5": expected_rank is not None,
                "status_code": status,
            }
            records.append(record)
            aggregate[transform_name].append(record)

    summaries: dict[str, dict[str, Any]] = {}
    for transform_name, values in sorted(aggregate.items()):
        similarities = [value["target_similarity"] for value in values]
        summaries[transform_name] = {
            "count": len(values),
            "recall_at_1": mean(value["recall_at_1"] for value in values),
            "recall_at_5": mean(value["recall_at_5"] for value in values),
            "target_similarity_mean": mean(similarities),
            "target_similarity_median": median(similarities),
            "target_similarity_min": min(similarities),
            "status_stability": mean(
                value["status_code"] == baseline_status[value["image_key"]]
                for value in values
            ),
        }
    result = dict(report)
    result["mode"] = "with_model"
    result["model_metrics"] = summaries
    result["model_records"] = records
    return result


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
