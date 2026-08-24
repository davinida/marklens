import hashlib
import json
import sys
from pathlib import Path

import pytest
from evaluation.artifacts import load_artifact_generation
from src.contracts import (
    EMBEDDING_CONTRACT_VERSION,
    EMBEDDING_DIM,
    MODEL_NAME,
    PRETRAINED,
)
from src.preprocess import LEGACY_PREPROCESS_VERSION


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_set_hash(keys: list[str], hashes: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for key in keys:
        digest.update(key.encode())
        digest.update(b"\0")
        digest.update(hashes[key].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def make_generation(
    tmp_path: Path,
    *,
    metadata_generation: str = "generation-1",
    manifest_model_name: str = MODEL_NAME,
) -> tuple[Path, Path, Path, Path]:
    artifact_dir = tmp_path / "index"
    image_dir = tmp_path / "images"
    artifact_dir.mkdir()
    image_dir.mkdir()
    keys = ["a.png", "nested/b.png"]
    (image_dir / "nested").mkdir()
    (image_dir / keys[0]).write_bytes(b"image-a")
    (image_dir / keys[1]).write_bytes(b"image-b")
    hashes = {key: sha256(image_dir / key) for key in keys}

    index_path = artifact_dir / "test.faiss"
    metadata_path = artifact_dir / "test_metadata.json"
    manifest_path = artifact_dir / "test_manifest.json"
    index_path.write_bytes(b"deterministic-index")
    metadata = {
        "schema_version": 2,
        "generation_id": metadata_generation,
        "model": MODEL_NAME,
        "pretrained": PRETRAINED,
        "embedding_dim": EMBEDDING_DIM,
        "embedding_contract": EMBEDDING_CONTRACT_VERSION,
        "preprocess_version": LEGACY_PREPROCESS_VERSION,
        "metric": "inner_product_on_l2_normalized_vectors",
        "total_images": len(keys),
        "image_paths": keys,
        "image_hashes": hashes,
        "image_dir": "<external>/images",
        "failed_count": 0,
    }
    write_json(metadata_path, metadata)
    manifest = {
        "schema_version": 1,
        "generation_id": "generation-1",
        "created_at": "2026-08-14T00:00:00+00:00",
        "model": {
            "name": manifest_model_name,
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
        "preprocess": {"version": LEGACY_PREPROCESS_VERSION},
        "source": {
            "type": "authoritative_keys",
            "path": "<external>/keys.json",
            "sha256": hashlib.sha256(b"authoritative-keys").hexdigest(),
            "authoritative_key_count": len(keys),
            "image_set_sha256": image_set_hash(keys, hashes),
            "unlisted_disk_image_count": 0,
            "unlisted_disk_image_sample": [],
        },
        "git": {"commit": "abc123", "dirty": False},
        "packages": {},
        "artifacts": {
            "index": {
                "filename": index_path.name,
                "sha256": sha256(index_path),
                "bytes": index_path.stat().st_size,
            },
            "metadata": {
                "filename": metadata_path.name,
                "sha256": sha256(metadata_path),
                "bytes": metadata_path.stat().st_size,
            },
        },
    }
    write_json(manifest_path, manifest)
    return index_path, metadata_path, manifest_path, image_dir


def load(paths, **kwargs):
    index_path, metadata_path, manifest_path, image_dir = paths
    return load_artifact_generation(
        index_path=index_path,
        metadata_path=metadata_path,
        manifest_path=manifest_path,
        image_dir=image_dir,
        **kwargs,
    )


def test_load_generation_verifies_contract_without_importing_openclip(tmp_path):
    paths = make_generation(tmp_path)
    before = set(sys.modules)

    generation = load(paths)

    assert generation.generation_id == "generation-1"
    assert generation.keys == ("a.png", "nested/b.png")
    assert generation.preprocess_version == LEGACY_PREPROCESS_VERSION
    assert generation.report_source()["index_sha256"] == sha256(paths[0])
    assert "open_clip" not in set(sys.modules) - before
    assert str(tmp_path) not in json.dumps(generation.report_source())


def test_load_generation_rejects_mixed_generation(tmp_path):
    paths = make_generation(tmp_path, metadata_generation="generation-old")

    with pytest.raises(ValueError, match="generation_id mismatch"):
        load(paths)


def test_load_generation_rejects_artifact_sha_mismatch(tmp_path):
    paths = make_generation(tmp_path)
    paths[0].write_bytes(b"changed-after-publication")

    with pytest.raises(ValueError, match="index SHA-256 mismatch"):
        load(paths)


def test_load_generation_rejects_model_contract_mismatch(tmp_path):
    paths = make_generation(tmp_path, manifest_model_name="different-model")

    with pytest.raises(ValueError, match="model.name mismatch"):
        load(paths)


def test_load_generation_rejects_requested_preprocess_mismatch(tmp_path):
    paths = make_generation(tmp_path)

    with pytest.raises(ValueError, match="Requested preprocess version"):
        load(paths, requested_preprocess_version="global-letterbox-dual-bg-v1")


def test_load_generation_rejects_changed_source_image(tmp_path):
    paths = make_generation(tmp_path)
    (paths[3] / "a.png").write_bytes(b"changed-image")

    with pytest.raises(ValueError, match="Image SHA-256 mismatch"):
        load(paths)


def test_model_mode_requires_manifest_runtime_versions(tmp_path):
    paths = make_generation(tmp_path)

    with pytest.raises(ValueError, match="package version is missing"):
        load(paths, validate_runtime_packages=True)


def test_authoritative_source_requires_sha256(tmp_path):
    paths = make_generation(tmp_path)
    manifest = json.loads(paths[2].read_text(encoding="utf-8"))
    manifest["source"]["sha256"] = None
    write_json(paths[2], manifest)

    with pytest.raises(ValueError, match="source sha256"):
        load(paths)
