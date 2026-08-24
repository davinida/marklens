import hashlib
import json
from types import SimpleNamespace

import faiss
import pytest

from backend.src.core import config, engine, paths


def _manifest(tmp_path, monkeypatch):
    index_path = tmp_path / "kipris.faiss"
    metadata_path = tmp_path / "kipris_metadata.json"
    index_path.write_bytes(b"index-generation")
    metadata = {"generation_id": "generation-1", "image_paths": ["a.png", "b.png"]}
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(paths, "INDEX_PATH", index_path)
    monkeypatch.setattr(paths, "INDEX_META_PATH", metadata_path)

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = {
        "generation_id": "generation-1",
        "model": {
            "name": engine.MODEL_NAME,
            "pretrained": engine.PRETRAINED,
            "embedding_dim": engine.EMBEDDING_DIM,
            "embedding_contract": engine.EMBEDDING_CONTRACT_VERSION,
        },
        "index": {
            "metric": "inner_product",
            "vectors_l2_normalized": True,
            "vector_count": 2,
        },
        "preprocess": {"version": engine.DEFAULT_PREPROCESS_VERSION},
        "artifacts": {
            "index": {"filename": index_path.name, "sha256": digest(index_path)},
            "metadata": {
                "filename": metadata_path.name,
                "sha256": digest(metadata_path),
            },
        },
    }
    fake_index = SimpleNamespace(
        ntotal=2,
        d=engine.EMBEDDING_DIM,
        metric_type=faiss.METRIC_INNER_PRODUCT,
    )
    return fake_index, metadata, manifest


def _image_set_digest(image_paths, image_hashes):
    digest = hashlib.sha256()
    for image_key in image_paths:
        digest.update(image_key.encode("utf-8"))
        digest.update(b"\0")
        digest.update(image_hashes[image_key].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _public_image_manifest(tmp_path, monkeypatch):
    index, metadata, manifest = _manifest(tmp_path, monkeypatch)
    image_root = tmp_path / "images"
    image_root.mkdir()
    for image_key, content in (("a.png", b"image-a"), ("b.png", b"image-b")):
        (image_root / image_key).write_bytes(content)

    image_hashes = {
        image_key: hashlib.sha256((image_root / image_key).read_bytes()).hexdigest()
        for image_key in metadata["image_paths"]
    }
    metadata["image_hashes"] = image_hashes
    paths.INDEX_META_PATH.write_text(json.dumps(metadata), encoding="utf-8")
    manifest["artifacts"]["metadata"]["sha256"] = hashlib.sha256(
        paths.INDEX_META_PATH.read_bytes()
    ).hexdigest()
    manifest["git"] = {"commit": "a" * 40, "dirty": False}
    manifest["source"] = {
        "image_set_sha256": _image_set_digest(metadata["image_paths"], image_hashes)
    }
    monkeypatch.setattr(paths, "IMAGES_DIR", image_root)
    monkeypatch.setattr(config, "ENVIRONMENT", "production")
    monkeypatch.setattr(config, "PUBLIC_RESULT_IMAGES", True)
    return index, metadata, manifest, image_root


def _rewrite_metadata_contract(metadata, manifest):
    paths.INDEX_META_PATH.write_text(json.dumps(metadata), encoding="utf-8")
    manifest["artifacts"]["metadata"]["sha256"] = hashlib.sha256(
        paths.INDEX_META_PATH.read_bytes()
    ).hexdigest()


def test_valid_manifest_contract_is_accepted(tmp_path, monkeypatch):
    index, metadata, manifest = _manifest(tmp_path, monkeypatch)
    assert engine._validate_artifact_manifest(index, metadata, manifest) == "generation-1"


def test_preprocess_contract_mismatch_fails_closed(tmp_path, monkeypatch):
    index, metadata, manifest = _manifest(tmp_path, monkeypatch)
    manifest["preprocess"]["version"] = "unknown-v99"
    with pytest.raises(RuntimeError, match="전처리 계약 불일치"):
        engine._validate_artifact_manifest(index, metadata, manifest)


def test_artifact_hash_mismatch_fails_closed(tmp_path, monkeypatch):
    index, metadata, manifest = _manifest(tmp_path, monkeypatch)
    manifest["artifacts"]["index"]["sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="SHA-256"):
        engine._validate_artifact_manifest(index, metadata, manifest)


def test_production_rejects_dirty_source_manifest(tmp_path, monkeypatch):
    index, metadata, manifest = _manifest(tmp_path, monkeypatch)
    manifest["git"] = {"commit": "a" * 40, "dirty": True}
    monkeypatch.setattr(config, "ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="clean Git source"):
        engine._validate_artifact_manifest(index, metadata, manifest)


def test_production_public_images_accept_verified_image_set(tmp_path, monkeypatch):
    index, metadata, manifest, _ = _public_image_manifest(tmp_path, monkeypatch)

    assert engine._validate_artifact_manifest(index, metadata, manifest) == "generation-1"


def test_production_public_images_reject_missing_image(tmp_path, monkeypatch):
    index, metadata, manifest, image_root = _public_image_manifest(tmp_path, monkeypatch)
    (image_root / "b.png").unlink()

    with pytest.raises(RuntimeError, match="result image is missing"):
        engine._validate_artifact_manifest(index, metadata, manifest)


def test_production_public_images_reject_tampered_image(tmp_path, monkeypatch):
    index, metadata, manifest, image_root = _public_image_manifest(tmp_path, monkeypatch)
    (image_root / "a.png").write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match="image SHA-256 mismatch"):
        engine._validate_artifact_manifest(index, metadata, manifest)


def test_production_public_images_reject_image_set_hash_mismatch(
    tmp_path, monkeypatch
):
    index, metadata, manifest, _ = _public_image_manifest(tmp_path, monkeypatch)
    manifest["source"]["image_set_sha256"] = "0" * 64

    with pytest.raises(RuntimeError, match="image_set_sha256 does not match"):
        engine._validate_artifact_manifest(index, metadata, manifest)


def test_production_public_images_reject_unsafe_image_key(tmp_path, monkeypatch):
    index, metadata, manifest, _ = _public_image_manifest(tmp_path, monkeypatch)
    old_key = metadata["image_paths"][0]
    unsafe_key = "../escape.png"
    metadata["image_paths"][0] = unsafe_key
    metadata["image_hashes"][unsafe_key] = metadata["image_hashes"].pop(old_key)
    manifest["source"]["image_set_sha256"] = _image_set_digest(
        metadata["image_paths"], metadata["image_hashes"]
    )
    _rewrite_metadata_contract(metadata, manifest)

    with pytest.raises(RuntimeError, match="Unsafe image key"):
        engine._validate_artifact_manifest(index, metadata, manifest)


@pytest.mark.parametrize("coverage_error", ["missing", "extra"])
def test_production_public_images_require_exact_hash_coverage(
    tmp_path, monkeypatch, coverage_error
):
    index, metadata, manifest, _ = _public_image_manifest(tmp_path, monkeypatch)
    if coverage_error == "missing":
        metadata["image_hashes"].pop("a.png")
    else:
        metadata["image_hashes"]["unreferenced.png"] = "0" * 64
    _rewrite_metadata_contract(metadata, manifest)

    with pytest.raises(RuntimeError, match="exactly cover image_paths"):
        engine._validate_artifact_manifest(index, metadata, manifest)


@pytest.mark.parametrize(
    ("environment", "public_result_images"),
    [("development", True), ("production", False)],
)
def test_image_verification_is_skipped_when_not_public_production(
    tmp_path, monkeypatch, environment, public_result_images
):
    index, metadata, manifest = _manifest(tmp_path, monkeypatch)
    if environment == "production":
        manifest["git"] = {"commit": "a" * 40, "dirty": False}
    monkeypatch.setattr(config, "ENVIRONMENT", environment)
    monkeypatch.setattr(config, "PUBLIC_RESULT_IMAGES", public_result_images)

    def fail_if_called(*_args):
        raise AssertionError("public image verification should not run")

    monkeypatch.setattr(engine, "_validate_public_image_artifacts", fail_if_called)
    assert engine._validate_artifact_manifest(index, metadata, manifest) == "generation-1"


def test_dirty_marker_fails_before_loading_index(tmp_path, monkeypatch):
    marker = tmp_path / ".kipris-index-dirty"
    marker.write_text("dirty", encoding="utf-8")
    monkeypatch.setattr(paths, "INDEX_DIRTY_PATH", marker)
    with pytest.raises(RuntimeError, match="게시가 완료되지 않았습니다"):
        engine.load_all()
