import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from scripts import build_index as builder


def write_image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 40), color).save(path)


def fake_encoder(path, *, preprocess_version):
    index = int(Path(path).stem[-1]) % builder.EMBEDDING_DIM
    vector = np.zeros(builder.EMBEDDING_DIM, dtype=np.float32)
    vector[index] = 1.0
    return vector


def write_keys(path: Path, keys: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "database.image_key",
                "image_keys": keys,
            }
        ),
        encoding="utf-8",
    )


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_git_state_marks_untracked_runtime_source_dirty(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "--quiet")
    run_git(repo, "config", "user.name", "MarkLens Test")
    run_git(repo, "config", "user.email", "marklens-test@example.invalid")
    (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    run_git(repo, "add", "tracked.txt")
    run_git(repo, "commit", "--quiet", "-m", "baseline")
    monkeypatch.setattr(builder, "ML_ROOT", repo)

    clean = builder._git_state()
    assert clean["commit"] == run_git(repo, "rev-parse", "HEAD")
    assert clean["dirty"] is False

    runtime_source = repo / "ml" / "src" / "runtime_contract.py"
    runtime_source.parent.mkdir(parents=True)
    runtime_source.write_text("CONTRACT = 'untracked'\n", encoding="utf-8")

    assert builder._git_state()["dirty"] is True


def test_load_authoritative_keys_supports_object_and_legacy_array(tmp_path):
    object_path = tmp_path / "object.json"
    array_path = tmp_path / "array.json"
    write_keys(object_path, ["nested/a.png", "b.JPG"])
    array_path.write_text('["a.png"]', encoding="utf-8")

    assert builder.load_authoritative_keys(object_path) == ["b.JPG", "nested/a.png"]
    assert builder.load_authoritative_keys(array_path) == ["a.png"]


@pytest.mark.parametrize(
    "key",
    ["../a.png", "/a.png", "C:/a.png", "a.txt", " a.png", "a.png/../b.png"],
)
def test_load_authoritative_keys_rejects_unsafe_key(tmp_path, key):
    path = tmp_path / "keys.json"
    write_keys(path, [key])

    with pytest.raises(ValueError):
        builder.load_authoritative_keys(path)


def test_load_authoritative_keys_rejects_casefold_duplicate(tmp_path):
    path = tmp_path / "keys.json"
    write_keys(path, ["A.png", "a.PNG"])

    with pytest.raises(ValueError, match="Duplicate"):
        builder.load_authoritative_keys(path)


def test_metadata_key_extraction(tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text(
        json.dumps({"trademarks": [{"\uc774\ubbf8\uc9c0\ud30c\uc77c": "a.png"}]}),
        encoding="utf-8",
    )

    assert builder.load_authoritative_keys(path, metadata=True) == ["a.png"]


def test_resolve_images_excludes_unlisted_disk_files(tmp_path):
    images = tmp_path / "images"
    write_image(images / "listed.png", (255, 0, 0))
    write_image(images / "orphan.png", (0, 255, 0))

    paths, orphans = builder.resolve_authoritative_images(images, ["listed.png"])

    assert [path.name for path in paths] == ["listed.png"]
    assert orphans == ["orphan.png"]


def test_resolve_images_fails_on_missing_authoritative_file(tmp_path):
    images = tmp_path / "images"
    images.mkdir()

    with pytest.raises(FileNotFoundError, match="missing"):
        builder.resolve_authoritative_images(images, ["missing.png"])


def test_build_publishes_valid_generation_and_manifest(tmp_path, monkeypatch):
    images = tmp_path / "images"
    output = tmp_path / "index"
    keys_path = tmp_path / "keys.json"
    write_image(images / "mark1.png", (255, 0, 0))
    write_image(images / "mark2.png", (0, 255, 0))
    write_image(images / "orphan.png", (0, 0, 255))
    write_keys(keys_path, ["mark2.png", "mark1.png"])
    monkeypatch.setattr(builder, "encode_image", fake_encoder)
    monkeypatch.setattr(builder, "_git_state", lambda: {"commit": "abc", "dirty": False})
    monkeypatch.setattr(builder, "_package_versions", lambda: {})

    manifest = builder.build_and_publish(
        image_dir=images,
        output_dir=output,
        index_name="test",
        authoritative_keys=keys_path,
    )

    metadata = json.loads((output / "test_metadata.json").read_text(encoding="utf-8"))
    published_manifest = json.loads(
        (output / "test_manifest.json").read_text(encoding="utf-8")
    )
    index = builder.load_index(output / "test.faiss")
    assert index.ntotal == 2
    assert metadata["image_paths"] == ["mark1.png", "mark2.png"]
    assert metadata["generation_id"] == manifest["generation_id"]
    assert published_manifest["generation_id"] == manifest["generation_id"]
    assert manifest["source"]["unlisted_disk_image_count"] == 1
    serialized = json.dumps({"metadata": metadata, "manifest": manifest})
    assert str(tmp_path) not in serialized
    assert manifest["source"]["path"] == "<external>/keys.json"
    assert metadata["image_dir"] == "<external>/images"
    assert manifest["artifacts"]["index"]["sha256"] == hashlib.sha256(
        (output / "test.faiss").read_bytes()
    ).hexdigest()


def test_encoding_failure_preserves_existing_generation(tmp_path, monkeypatch):
    images = tmp_path / "images"
    output = tmp_path / "index"
    keys_path = tmp_path / "keys.json"
    write_image(images / "mark1.png", (255, 0, 0))
    write_keys(keys_path, ["mark1.png"])
    output.mkdir()
    existing = {
        "test.faiss": b"old-index",
        "test_metadata.json": b"old-metadata",
        "test_manifest.json": b"old-manifest",
    }
    for name, content in existing.items():
        (output / name).write_bytes(content)

    def fail_encoder(path, *, preprocess_version):
        raise ValueError("bad image")

    monkeypatch.setattr(builder, "encode_image", fail_encoder)

    with pytest.raises(RuntimeError, match="no artifacts were published"):
        builder.build_and_publish(
            image_dir=images,
            output_dir=output,
            index_name="test",
            authoritative_keys=keys_path,
        )

    for name, content in existing.items():
        assert (output / name).read_bytes() == content


def test_requires_authoritative_source_unless_explicit_demo_opt_in(tmp_path):
    images = tmp_path / "standalone"
    write_image(images / "mark1.png", (255, 0, 0))

    with pytest.raises(ValueError, match="authoritative source"):
        builder.build_and_publish(
            image_dir=images,
            output_dir=tmp_path / "index",
            index_name="test",
        )
