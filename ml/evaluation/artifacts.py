"""Fail-closed loading of one published index artifact generation."""

from __future__ import annotations

import importlib.metadata
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from src.contracts import (
    EMBEDDING_CONTRACT_VERSION,
    EMBEDDING_DIM,
    MODEL_NAME,
    PRETRAINED,
)
from src.preprocess import GLOBAL_PREPROCESS_VERSION, LEGACY_PREPROCESS_VERSION

from evaluation.labeling import load_image_keys, sha256_file

MANIFEST_SCHEMA_VERSION = 1
METADATA_SCHEMA_VERSION = 2
SUPPORTED_PREPROCESS_VERSIONS = {
    LEGACY_PREPROCESS_VERSION,
    GLOBAL_PREPROCESS_VERSION,
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MODEL_RUNTIME_PACKAGES = (
    "open_clip_torch",
    "faiss-cpu",
    "torch",
    "Pillow",
    "numpy",
)
SUPPORTED_SOURCE_TYPES = {
    "authoritative_keys",
    "authoritative_metadata",
    "auto_authoritative_metadata",
    "directory_opt_in",
}
ML_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ML_ROOT.parent.resolve()


@dataclass(frozen=True)
class ArtifactGeneration:
    """A fully verified, internally consistent published generation."""

    index_path: Path
    metadata_path: Path
    manifest_path: Path
    image_dir: Path
    generation_id: str
    preprocess_version: str
    keys: tuple[str, ...]
    image_hashes: dict[str, str]
    metadata: dict[str, Any]
    manifest: dict[str, Any]

    def report_source(self) -> dict[str, Any]:
        artifacts = self.manifest["artifacts"]
        source = self.manifest["source"]
        return {
            "generation_id": self.generation_id,
            "manifest_filename": self.manifest_path.name,
            "manifest_sha256": sha256_file(self.manifest_path),
            "index_filename": self.index_path.name,
            "index_sha256": artifacts["index"]["sha256"],
            "metadata_filename": self.metadata_path.name,
            "metadata_sha256": artifacts["metadata"]["sha256"],
            "image_set_sha256": source["image_set_sha256"],
            "authoritative_source_sha256": source.get("sha256"),
            "model": dict(self.manifest["model"]),
            "preprocess_version": self.preprocess_version,
            "git": dict(self.manifest["git"]),
        }


def _load_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} file is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return payload


def _require_object(parent: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{label}.{key} must be an object")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _expect(actual: Any, expected: Any, label: str) -> None:
    if actual != expected or type(actual) is not type(expected):
        raise ValueError(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def _resolve_image(image_dir: Path, key: str) -> Path:
    root = image_dir.resolve(strict=True)
    relative = PurePosixPath(key)
    path = root.joinpath(*relative.parts).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Image key escapes image-dir: {key!r}") from exc
    if not path.is_file():
        raise FileNotFoundError(f"Image is missing: {key}")
    return path


def _validate_portable_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{label} must be a non-empty portable path")
    if value.startswith("<external>/"):
        return value
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value.startswith("//")
        or any(part in ("", ".", "..") for part in path.parts)
        or (path.parts and ":" in path.parts[0])
    ):
        raise ValueError(f"Unsafe or host-specific {label}: {value!r}")
    return value


def _image_set_sha256(keys: tuple[str, ...], hashes: dict[str, str]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for key in keys:
        digest.update(key.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashes[key].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _validate_artifact_file(
    path: Path,
    artifact: dict[str, Any],
    *,
    label: str,
) -> None:
    _expect(artifact.get("filename"), path.name, f"manifest {label} filename")
    expected_hash = _require_sha256(
        artifact.get("sha256"), f"manifest {label} sha256"
    )
    actual_hash = sha256_file(path)
    if actual_hash != expected_hash:
        raise ValueError(
            f"{label} SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
        )
    _expect(artifact.get("bytes"), path.stat().st_size, f"manifest {label} bytes")


def _validate_runtime_packages(packages: dict[str, Any]) -> None:
    for distribution in MODEL_RUNTIME_PACKAGES:
        expected = packages.get(distribution)
        if not isinstance(expected, str) or not expected:
            raise ValueError(
                f"manifest package version is missing for {distribution!r}"
            )
        try:
            actual = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError(
                f"Required model package is not installed: {distribution}"
            ) from exc
        if actual != expected:
            raise RuntimeError(
                f"Runtime package mismatch for {distribution}: "
                f"manifest={expected!r}, runtime={actual!r}"
            )


def _validate_local_authoritative_source(source: dict[str, Any]) -> None:
    source_path = source.get("path")
    expected_hash = source.get("sha256")
    source_type = source.get("type")
    if source_type not in SUPPORTED_SOURCE_TYPES:
        raise ValueError(f"Unsupported manifest source type: {source_type!r}")
    _validate_portable_path(source_path, "manifest source path")
    if source_type == "directory_opt_in":
        if expected_hash is not None:
            raise ValueError("directory_opt_in source SHA-256 must be null")
        return
    expected_hash = _require_sha256(expected_hash, "manifest source sha256")
    if source_path.startswith("<external>/"):
        return
    relative = PurePosixPath(source_path)
    if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
        raise ValueError(f"Unsafe manifest source path: {source_path!r}")
    path = PROJECT_ROOT.joinpath(*relative.parts).resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"Manifest source path escapes project: {source_path!r}") from exc
    if not path.is_file():
        raise FileNotFoundError(f"Manifest authoritative source is missing: {path}")
    actual_hash = sha256_file(path)
    if actual_hash != expected_hash:
        raise ValueError(
            "Authoritative source SHA-256 mismatch: "
            f"expected {expected_hash}, got {actual_hash}"
        )


def load_artifact_generation(
    *,
    index_path: Path,
    metadata_path: Path,
    image_dir: Path,
    manifest_path: Path | None = None,
    requested_preprocess_version: str | None = None,
    validate_runtime_packages: bool = False,
) -> ArtifactGeneration:
    """Load one complete generation and reject every contract mismatch."""
    index_path = index_path.resolve(strict=True)
    metadata_path = metadata_path.resolve(strict=True)
    image_dir = image_dir.resolve(strict=True)
    if not image_dir.is_dir():
        raise ValueError(f"Image root is not a directory: {image_dir}")
    if manifest_path is None:
        manifest_path = index_path.with_name(f"{index_path.stem}_manifest.json")
    manifest_path = manifest_path.resolve(strict=True)
    if len({index_path.parent, metadata_path.parent, manifest_path.parent}) != 1:
        raise ValueError("Index, metadata, and manifest must share one artifact directory")

    manifest = _load_object(manifest_path, "manifest")
    metadata = _load_object(metadata_path, "metadata")
    _expect(manifest.get("schema_version"), MANIFEST_SCHEMA_VERSION, "manifest schema")
    _expect(metadata.get("schema_version"), METADATA_SCHEMA_VERSION, "metadata schema")

    generation_id = manifest.get("generation_id")
    if not isinstance(generation_id, str) or not generation_id.strip():
        raise ValueError("manifest generation_id must be a non-empty string")
    _expect(metadata.get("generation_id"), generation_id, "metadata generation_id")

    artifacts = _require_object(manifest, "artifacts", "manifest")
    index_artifact = _require_object(artifacts, "index", "manifest.artifacts")
    metadata_artifact = _require_object(
        artifacts, "metadata", "manifest.artifacts"
    )
    _validate_artifact_file(index_path, index_artifact, label="index")
    _validate_artifact_file(metadata_path, metadata_artifact, label="metadata")

    model = _require_object(manifest, "model", "manifest")
    expected_model = {
        "name": MODEL_NAME,
        "pretrained": PRETRAINED,
        "embedding_dim": EMBEDDING_DIM,
        "embedding_contract": EMBEDDING_CONTRACT_VERSION,
    }
    for key, expected in expected_model.items():
        _expect(model.get(key), expected, f"manifest model.{key}")
    metadata_model = {
        "model": MODEL_NAME,
        "pretrained": PRETRAINED,
        "embedding_dim": EMBEDDING_DIM,
        "embedding_contract": EMBEDDING_CONTRACT_VERSION,
    }
    for key, expected in metadata_model.items():
        _expect(metadata.get(key), expected, f"metadata {key}")

    preprocess = _require_object(manifest, "preprocess", "manifest")
    preprocess_version = preprocess.get("version")
    if preprocess_version not in SUPPORTED_PREPROCESS_VERSIONS:
        raise ValueError(
            f"Unsupported manifest preprocess version: {preprocess_version!r}"
        )
    _expect(
        metadata.get("preprocess_version"),
        preprocess_version,
        "metadata preprocess_version",
    )
    if (
        requested_preprocess_version is not None
        and requested_preprocess_version != preprocess_version
    ):
        raise ValueError(
            "Requested preprocess version does not match the index generation: "
            f"requested={requested_preprocess_version!r}, "
            f"manifest={preprocess_version!r}"
        )

    index_contract = _require_object(manifest, "index", "manifest")
    _expect(index_contract.get("metric"), "inner_product", "manifest index metric")
    _expect(
        index_contract.get("vectors_l2_normalized"),
        True,
        "manifest index L2-normalized marker",
    )
    _expect(
        metadata.get("metric"),
        "inner_product_on_l2_normalized_vectors",
        "metadata metric",
    )
    _expect(metadata.get("failed_count"), 0, "metadata failed_count")
    _validate_portable_path(metadata.get("image_dir"), "metadata image_dir")

    keys = tuple(load_image_keys(metadata_path))
    _expect(metadata.get("total_images"), len(keys), "metadata total_images")
    _expect(index_contract.get("vector_count"), len(keys), "manifest vector_count")
    source = _require_object(manifest, "source", "manifest")
    _expect(
        source.get("authoritative_key_count"),
        len(keys),
        "manifest authoritative_key_count",
    )

    raw_hashes = metadata.get("image_hashes")
    if not isinstance(raw_hashes, dict) or set(raw_hashes) != set(keys):
        raise ValueError("metadata image_hashes must exactly cover image_paths")
    image_hashes: dict[str, str] = {}
    for key in keys:
        expected_hash = _require_sha256(
            raw_hashes.get(key), f"metadata image hash for {key!r}"
        )
        actual_hash = sha256_file(_resolve_image(image_dir, key))
        if actual_hash != expected_hash:
            raise ValueError(
                f"Image SHA-256 mismatch for {key!r}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
        image_hashes[key] = expected_hash
    expected_image_set_hash = _require_sha256(
        source.get("image_set_sha256"), "manifest image_set_sha256"
    )
    actual_image_set_hash = _image_set_sha256(keys, image_hashes)
    if actual_image_set_hash != expected_image_set_hash:
        raise ValueError(
            "Image-set SHA-256 mismatch: "
            f"expected {expected_image_set_hash}, got {actual_image_set_hash}"
        )

    git = _require_object(manifest, "git", "manifest")
    if not isinstance(git.get("commit"), str) or not git["commit"]:
        raise ValueError("manifest git.commit must be a non-empty string")
    dirty = git.get("dirty")
    if dirty is not None and type(dirty) is not bool:
        raise ValueError("manifest git.dirty must be true, false, or null")
    _validate_local_authoritative_source(source)

    packages = _require_object(manifest, "packages", "manifest")
    if validate_runtime_packages:
        _validate_runtime_packages(packages)

    return ArtifactGeneration(
        index_path=index_path,
        metadata_path=metadata_path,
        manifest_path=manifest_path,
        image_dir=image_dir,
        generation_id=generation_id,
        preprocess_version=preprocess_version,
        keys=keys,
        image_hashes=image_hashes,
        metadata=metadata,
        manifest=manifest,
    )
