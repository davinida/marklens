#!/usr/bin/env python3
"""Build and atomically publish a validated visual-search index generation."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence

# Avoid the macOS PyTorch/FAISS OpenMP collision before importing either module.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_ROOT))

from src.embedding import (
    EMBEDDING_CONTRACT_VERSION,
    EMBEDDING_DIM,
    MODEL_NAME,
    PRETRAINED,
    encode_image,
)
from src.preprocess import (
    DEFAULT_PREPROCESS_VERSION,
    GLOBAL_PREPROCESS_VERSION,
    LEGACY_PREPROCESS_VERSION,
)
from src.search import (
    build_index as create_faiss_index,
)
from src.search import (
    load_index,
    save_index,
)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
INDEX_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MANIFEST_SCHEMA_VERSION = 1
METADATA_SCHEMA_VERSION = 2
PROJECT_ROOT = ML_ROOT.parent.resolve()

IMAGE_KEY_FIELDS = (
    "image_key",
    "image_path",
    "image_file",
    "\uc774\ubbf8\uc9c0\ud30c\uc77c",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def portable_path(path: Path) -> str:
    """Record reproducible paths without leaking host usernames or drive layout."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return f"<external>/{resolved.name}"


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_json(path: Path, payload: Any) -> None:
    data = _json_bytes(payload)
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _normalize_image_key(raw_key: Any) -> str:
    if not isinstance(raw_key, str) or not raw_key or raw_key != raw_key.strip():
        raise ValueError(f"Image key must be a non-empty trimmed string: {raw_key!r}")
    if "\x00" in raw_key:
        raise ValueError("Image key contains a NUL byte")

    normalized = raw_key.replace("\\", "/")
    key_path = PurePosixPath(normalized)
    if (
        key_path.is_absolute()
        or normalized.startswith("//")
        or any(part in ("", ".", "..") for part in key_path.parts)
        or (key_path.parts and ":" in key_path.parts[0])
    ):
        raise ValueError(f"Image key must stay relative to image-dir: {raw_key!r}")
    if key_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported image extension in key {raw_key!r}; "
            f"expected one of {sorted(SUPPORTED_EXTENSIONS)}"
        )
    return key_path.as_posix()


def _validated_unique_keys(raw_keys: Iterable[Any]) -> list[str]:
    keys: list[str] = []
    seen: dict[str, str] = {}
    for raw_key in raw_keys:
        key = _normalize_image_key(raw_key)
        folded = key.casefold()
        if folded in seen:
            raise ValueError(
                f"Duplicate authoritative image key: {key!r} conflicts with "
                f"{seen[folded]!r}"
            )
        seen[folded] = key
        keys.append(key)
    if not keys:
        raise ValueError("Authoritative image key set is empty")
    return sorted(keys, key=str.casefold)


def _extract_metadata_keys(payload: Any) -> list[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("trademarks"), list):
        raise ValueError("Authoritative metadata must contain a trademarks array")

    raw_keys: list[Any] = []
    for row_number, record in enumerate(payload["trademarks"], start=1):
        if not isinstance(record, dict):
            raise ValueError(f"Trademark row {row_number} must be an object")
        key = next(
            (record[field] for field in IMAGE_KEY_FIELDS if record.get(field)),
            None,
        )
        if key is None:
            raise ValueError(f"Trademark row {row_number} has no image key")
        raw_keys.append(key)
    return _validated_unique_keys(raw_keys)


def load_authoritative_keys(path: Path, *, metadata: bool = False) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"Authoritative source not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in authoritative source {path}: {exc}") from exc

    if metadata:
        return _extract_metadata_keys(payload)
    if isinstance(payload, list):
        return _validated_unique_keys(payload)
    if isinstance(payload, dict) and isinstance(payload.get("image_keys"), list):
        return _validated_unique_keys(payload["image_keys"])
    raise ValueError(
        "Authoritative key source must be a string array or an object with "
        "an image_keys array"
    )


def find_images(image_dir: Path) -> list[Path]:
    """Return supported files inside image_dir, without following path escapes."""
    root = image_dir.resolve(strict=True)
    images: list[Path] = []
    for candidate in image_dir.rglob("*"):
        if not candidate.is_file() or candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Image path escapes image-dir: {candidate}") from exc
        images.append(candidate)
    return sorted(images, key=lambda item: item.as_posix().casefold())


def resolve_authoritative_images(
    image_dir: Path,
    keys: Sequence[str],
) -> tuple[list[Path], list[str]]:
    """Resolve every authoritative key and report unlisted on-disk images."""
    root = image_dir.resolve(strict=True)
    paths: list[Path] = []
    for key in keys:
        normalized = _normalize_image_key(key)
        path = root.joinpath(*PurePosixPath(normalized).parts).resolve(strict=False)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Image key escapes image-dir after resolution: {key!r}") from exc
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Authoritative image is missing: {key}")
        paths.append(path)

    authoritative = {key.casefold() for key in keys}
    discovered_keys = {
        path.resolve().relative_to(root).as_posix() for path in find_images(image_dir)
    }
    orphans = sorted(
        (key for key in discovered_keys if key.casefold() not in authoritative),
        key=str.casefold,
    )
    return paths, orphans


def _git_state() -> dict[str, Any]:
    def run(*args: str) -> str | None:
        result = subprocess.run(
            ["git", *args],
            cwd=ML_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    commit = run("rev-parse", "HEAD")
    # A release artifact must not claim clean provenance when it may have
    # imported an untracked runtime module or configuration file. Git still
    # excludes ignored data/model/build outputs from this status.
    status = run("status", "--porcelain", "--untracked-files=all")
    return {"commit": commit, "dirty": None if status is None else bool(status)}


def _package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for distribution in ("open_clip_torch", "faiss-cpu", "torch", "Pillow", "numpy"):
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = None
    return versions


def _image_set_hash(keys: Sequence[str], hashes: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for key in keys:
        digest.update(key.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashes[key].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _validate_temp_generation(
    index_path: Path,
    metadata_path: Path,
    expected_embeddings: np.ndarray,
    expected_keys: Sequence[str],
) -> None:
    index = load_index(index_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if index.ntotal != len(expected_keys):
        raise RuntimeError(
            f"Temporary index count mismatch: {index.ntotal} != {len(expected_keys)}"
        )
    if metadata.get("image_paths") != list(expected_keys):
        raise RuntimeError("Temporary metadata ordering does not match authoritative keys")
    if metadata.get("total_images") != index.ntotal:
        raise RuntimeError("Temporary metadata count does not match index")

    reconstructed = np.asarray(index.reconstruct_n(0, index.ntotal), dtype=np.float32)
    if (
        reconstructed.shape != expected_embeddings.shape
        or not np.all(np.isfinite(reconstructed))
        or not np.allclose(reconstructed, expected_embeddings, rtol=0.0, atol=1e-6)
    ):
        raise RuntimeError("Temporary FAISS vectors failed round-trip validation")


def _select_source(
    image_dir: Path,
    authoritative_keys: Path | None,
    authoritative_metadata: Path | None,
    allow_unlisted_images: bool,
) -> tuple[list[str], dict[str, Any]]:
    if authoritative_keys is not None:
        keys = load_authoritative_keys(authoritative_keys)
        source_path = authoritative_keys.resolve()
        source_type = "authoritative_keys"
    elif authoritative_metadata is not None:
        keys = load_authoritative_keys(authoritative_metadata, metadata=True)
        source_path = authoritative_metadata.resolve()
        source_type = "authoritative_metadata"
    else:
        auto_metadata = image_dir.resolve().parent / "kipris_metadata.json"
        if auto_metadata.is_file():
            keys = load_authoritative_keys(auto_metadata, metadata=True)
            source_path = auto_metadata.resolve()
            source_type = "auto_authoritative_metadata"
        elif allow_unlisted_images:
            root = image_dir.resolve()
            keys = _validated_unique_keys(
                path.resolve().relative_to(root).as_posix()
                for path in find_images(image_dir)
            )
            source_path = None
            source_type = "directory_opt_in"
        else:
            raise ValueError(
                "An authoritative source is required. Pass --authoritative-keys or "
                "--authoritative-metadata. --allow-unlisted-images is only for "
                "explicit local/demo builds."
            )

    source = {
        "type": source_type,
        "path": portable_path(source_path or image_dir),
        "sha256": sha256_file(source_path) if source_path else None,
        "authoritative_key_count": len(keys),
    }
    return keys, source


def build_and_publish(
    *,
    image_dir: Path,
    output_dir: Path,
    index_name: str,
    authoritative_keys: Path | None = None,
    authoritative_metadata: Path | None = None,
    allow_unlisted_images: bool = False,
    preprocess_version: str = DEFAULT_PREPROCESS_VERSION,
) -> dict[str, Any]:
    """Build a complete generation, validate it, then publish with manifest last."""
    if not INDEX_NAME_PATTERN.fullmatch(index_name):
        raise ValueError(f"Invalid index name: {index_name!r}")
    if authoritative_keys is not None and authoritative_metadata is not None:
        raise ValueError("Choose only one authoritative source")
    if not image_dir.exists():
        raise FileNotFoundError(f"Image directory not found: {image_dir}")
    if not image_dir.is_dir():
        raise ValueError(f"Not a directory: {image_dir}")

    keys, source = _select_source(
        image_dir,
        authoritative_keys,
        authoritative_metadata,
        allow_unlisted_images,
    )
    image_paths, orphans = resolve_authoritative_images(image_dir, keys)

    embeddings: list[np.ndarray] = []
    image_hashes: dict[str, str] = {}
    failures: list[dict[str, str]] = []
    for key, path in zip(keys, image_paths):
        try:
            embedding = encode_image(path, preprocess_version=preprocess_version)
            embeddings.append(embedding)
            image_hashes[key] = sha256_file(path)
        except Exception as exc:  # Preserve the authoritative all-or-nothing contract.
            failures.append(
                {
                    "image_key": key,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
    if failures:
        preview = json.dumps(failures[:5], ensure_ascii=False)
        raise RuntimeError(
            f"Failed to encode {len(failures)} authoritative image(s); "
            f"no artifacts were published: {preview}"
        )

    embeddings_array = np.stack(embeddings).astype(np.float32, copy=False)
    index = create_faiss_index(embeddings_array)
    generation_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:12]
    )
    created_at = datetime.now(timezone.utc).isoformat()

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{index_name}-{generation_id}-",
        dir=output_dir,
    ) as temporary:
        temp_dir = Path(temporary)
        index_filename = f"{index_name}.faiss"
        metadata_filename = f"{index_name}_metadata.json"
        manifest_filename = f"{index_name}_manifest.json"
        temp_index = temp_dir / index_filename
        temp_metadata = temp_dir / metadata_filename
        temp_manifest = temp_dir / manifest_filename

        save_index(index, temp_index)
        _fsync_file(temp_index)
        metadata = {
            "schema_version": METADATA_SCHEMA_VERSION,
            "generation_id": generation_id,
            "model": MODEL_NAME,
            "pretrained": PRETRAINED,
            "embedding_dim": EMBEDDING_DIM,
            "embedding_contract": EMBEDDING_CONTRACT_VERSION,
            "preprocess_version": preprocess_version,
            "metric": "inner_product_on_l2_normalized_vectors",
            "total_images": len(keys),
            "image_paths": list(keys),
            "image_hashes": image_hashes,
            "image_dir": portable_path(image_dir),
            "failed_count": 0,
        }
        _write_json(temp_metadata, metadata)
        _validate_temp_generation(
            temp_index,
            temp_metadata,
            embeddings_array,
            keys,
        )

        source.update(
            {
                "image_set_sha256": _image_set_hash(keys, image_hashes),
                "unlisted_disk_image_count": len(orphans),
                "unlisted_disk_image_sample": orphans[:20],
            }
        )
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "generation_id": generation_id,
            "created_at": created_at,
            "model": {
                "name": MODEL_NAME,
                "pretrained": PRETRAINED,
                "embedding_dim": EMBEDDING_DIM,
                "embedding_contract": EMBEDDING_CONTRACT_VERSION,
            },
            "index": {
                "implementation": "faiss.IndexFlatIP",
                "metric": "inner_product",
                "vectors_l2_normalized": True,
                "vector_count": len(keys),
            },
            "preprocess": {"version": preprocess_version},
            "source": source,
            "git": _git_state(),
            "packages": _package_versions(),
            "artifacts": {
                "index": {
                    "filename": index_filename,
                    "sha256": sha256_file(temp_index),
                    "bytes": temp_index.stat().st_size,
                },
                "metadata": {
                    "filename": metadata_filename,
                    "sha256": sha256_file(temp_metadata),
                    "bytes": temp_metadata.stat().st_size,
                },
            },
        }
        _write_json(temp_manifest, manifest)
        json.loads(temp_manifest.read_text(encoding="utf-8"))

        # Each replacement is atomic on the target filesystem. Publishing the
        # manifest last makes it the generation commit marker for new readers;
        # fixed index/metadata names keep legacy readers compatible.
        os.replace(temp_index, output_dir / index_filename)
        os.replace(temp_metadata, output_dir / metadata_filename)
        os.replace(temp_manifest, output_dir / manifest_filename)

    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a validated FAISS index from authoritative image keys",
    )
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/index"))
    parser.add_argument("--index-name", default="default")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--authoritative-keys", type=Path)
    source.add_argument("--authoritative-metadata", type=Path)
    parser.add_argument(
        "--allow-unlisted-images",
        action="store_true",
        help="Explicit local/demo opt-in when no authoritative source exists",
    )
    parser.add_argument(
        "--preprocess-version",
        choices=(LEGACY_PREPROCESS_VERSION, GLOBAL_PREPROCESS_VERSION),
        default=DEFAULT_PREPROCESS_VERSION,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest = build_and_publish(
        image_dir=args.image_dir,
        output_dir=args.output_dir,
        index_name=args.index_name,
        authoritative_keys=args.authoritative_keys,
        authoritative_metadata=args.authoritative_metadata,
        allow_unlisted_images=args.allow_unlisted_images,
        preprocess_version=args.preprocess_version,
    )
    source = manifest["source"]
    print(
        f"Published {manifest['index']['vector_count']} vectors as generation "
        f"{manifest['generation_id']} (unlisted disk images: "
        f"{source['unlisted_disk_image_count']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
