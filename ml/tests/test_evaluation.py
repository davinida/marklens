import hashlib
import json
import sys
from collections import Counter

import numpy as np
import pytest
from evaluation.labeling import (
    DEV_COUNT,
    HOLDOUT_COUNT,
    PAIR_COUNT,
    SIMILARITY_STRATA,
    build_labeling_pack,
    similarity_stratum,
    validate_labeling_pack,
    write_pack,
)
from evaluation.robustness import (
    TRANSFORM_NAMES,
    evaluate_model_robustness,
    perturb_image,
    prepare_audit,
)
from PIL import Image, ImageDraw


def image_keys(count=100):
    return [f"mark-{index:03d}.png" for index in range(count)]


def stratified_embeddings(count=100):
    if count > 100:
        raise ValueError("test construction supports at most 100 vectors")
    coefficients = np.repeat(np.array([0.90, 0.80, 0.72, 0.60]), 25)[:count]
    values = np.zeros((count, count + 1), dtype=np.float32)
    values[:, 0] = coefficients
    values[np.arange(count), np.arange(count) + 1] = np.sqrt(
        1.0 - coefficients**2
    )
    return values


def unique_hashes(keys):
    return {key: hashlib.sha256(key.encode()).hexdigest() for key in keys}


def test_labeling_pack_is_deterministic_blank_and_exactly_split():
    keys = image_keys()
    vectors = stratified_embeddings(len(keys))

    first = build_labeling_pack(
        keys,
        embeddings=vectors,
        image_hashes=unique_hashes(keys),
    )
    second = build_labeling_pack(
        keys,
        embeddings=vectors,
        image_hashes=unique_hashes(keys),
    )

    assert first == second
    assert len(first["pairs"]) == PAIR_COUNT
    assert sum(pair["split"] == "dev" for pair in first["pairs"]) == DEV_COUNT
    assert sum(pair["split"] == "frozen_holdout" for pair in first["pairs"]) == HOLDOUT_COUNT
    assert all(
        all(value is None for value in pair["annotation"].values())
        for pair in first["pairs"]
    )
    assert first["schema_version"] == 2
    assert first["selection_method"] == "stratified_similarity_family_disjoint"

    expected = {
        (split, name): 40 if split == "dev" else 10
        for split in ("dev", "frozen_holdout")
        for name, _, _ in SIMILARITY_STRATA
    }
    actual = Counter(
        (pair["split"], pair["similarity_stratum"]) for pair in first["pairs"]
    )
    assert actual == expected

    split_images = {
        split: {
            pair[side]["image_key"]
            for pair in first["pairs"]
            if pair["split"] == split
            for side in ("left", "right")
        }
        for split in ("dev", "frozen_holdout")
    }
    assert split_images["dev"].isdisjoint(split_images["frozen_holdout"])
    split_families = {
        split: {
            family["family_id"]
            for family in first["families"]
            if family["split"] == split
        }
        for split in ("dev", "frozen_holdout")
    }
    assert split_families["dev"].isdisjoint(split_families["frozen_holdout"])


def test_labeling_pack_rejects_too_few_unique_pairs():
    with pytest.raises(ValueError, match="unique pairs"):
        build_labeling_pack(image_keys(20), embeddings=stratified_embeddings(20))


def test_generated_pack_validation_rejects_inferred_label():
    pack = build_labeling_pack(image_keys(), embeddings=stratified_embeddings())
    pack["pairs"][0]["annotation"]["visual_similarity"] = "visually_similar"

    with pytest.raises(ValueError, match="every annotation field null"):
        validate_labeling_pack(pack, require_blank=True)


def test_pack_writer_is_idempotent_but_protects_existing_annotations(tmp_path):
    path = tmp_path / "pack.json"
    pack = build_labeling_pack(image_keys(), embeddings=stratified_embeddings())

    assert write_pack(path, pack) is True
    assert write_pack(path, pack) is False
    changed = json.loads(json.dumps(pack))
    changed["pairs"][0]["annotation"]["visual_similarity"] = "visually_similar"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(FileExistsError, match="Refusing"):
        write_pack(path, pack)


def test_pack_writer_replaces_only_valid_blank_pack_when_explicit(tmp_path):
    path = tmp_path / "pack.json"
    existing = build_labeling_pack(
        image_keys(),
        embeddings=stratified_embeddings(),
        source={"generation_id": "old"},
    )
    replacement = build_labeling_pack(
        image_keys(),
        embeddings=stratified_embeddings(),
        source={"generation_id": "clean-release"},
    )
    write_pack(path, existing)

    with pytest.raises(FileExistsError, match="replace_blank"):
        write_pack(path, replacement)

    assert write_pack(path, replacement, replace_blank=True) is True
    assert json.loads(path.read_text(encoding="utf-8"))["source"] == {
        "generation_id": "clean-release"
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("visual_similarity", "visually_similar"),
        ("confidence", "high"),
        ("annotator_id", "reviewer-1"),
        ("notes", "reviewed"),
    ],
)
def test_replace_blank_refuses_any_human_annotation(tmp_path, field, value):
    path = tmp_path / "pack.json"
    existing = build_labeling_pack(
        image_keys(),
        embeddings=stratified_embeddings(),
        source={"generation_id": "old"},
    )
    replacement = build_labeling_pack(
        image_keys(),
        embeddings=stratified_embeddings(),
        source={"generation_id": "new"},
    )
    existing["pairs"][0]["annotation"][field] = value
    original = json.dumps(existing).encode()
    path.write_bytes(original)

    with pytest.raises(FileExistsError, match="human annotations"):
        write_pack(path, replacement, replace_blank=True)

    assert path.read_bytes() == original


def test_replace_blank_accepts_whitespace_only_free_text(tmp_path):
    path = tmp_path / "pack.json"
    existing = build_labeling_pack(
        image_keys(),
        embeddings=stratified_embeddings(),
        source={"generation_id": "old"},
    )
    replacement = build_labeling_pack(
        image_keys(),
        embeddings=stratified_embeddings(),
        source={"generation_id": "new"},
    )
    existing["pairs"][0]["annotation"]["annotator_id"] = "   "
    existing["pairs"][0]["annotation"]["notes"] = "\t"
    path.write_text(json.dumps(existing), encoding="utf-8")

    assert write_pack(path, replacement, replace_blank=True) is True


def test_replace_blank_refuses_malformed_or_ambiguous_json(tmp_path):
    path = tmp_path / "pack.json"
    replacement = build_labeling_pack(image_keys(), embeddings=stratified_embeddings())
    original = b'{"pairs": [], "pairs": []}'
    path.write_bytes(original)

    with pytest.raises(FileExistsError, match="malformed"):
        write_pack(path, replacement, replace_blank=True)

    assert path.read_bytes() == original


def test_exact_image_hashes_join_a_family_even_below_similarity_threshold():
    keys = image_keys()
    hashes = unique_hashes(keys)
    hashes[keys[0]] = hashes[keys[50]]

    pack = build_labeling_pack(
        keys,
        embeddings=stratified_embeddings(),
        image_hashes=hashes,
    )

    family_by_image = {
        key: family["family_id"]
        for family in pack["families"]
        for key in family["image_keys"]
    }
    assert family_by_image[keys[0]] == family_by_image[keys[50]]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-1.0, "below_weak"),
        (0.4499, "below_weak"),
        (0.45, "weak_band"),
        (0.55, "possible_band"),
        (0.75, "strong_band"),
        (1.0, "strong_band"),
    ],
)
def test_similarity_stratum_boundaries(value, expected):
    assert similarity_stratum(value) == expected


def test_similarity_stratum_rejects_nan():
    with pytest.raises(ValueError, match="finite"):
        similarity_stratum(float("nan"))


def test_perturbations_are_deterministic_and_keep_dimensions():
    source = Image.new("RGB", (80, 40), "white")
    ImageDraw.Draw(source).rectangle((10, 5, 60, 30), fill="black")

    for name in TRANSFORM_NAMES:
        first = perturb_image(source, name)
        second = perturb_image(source, name)
        assert first.size == source.size
        assert first.tobytes() == second.tobytes()
        assert first.tobytes() != source.tobytes()


def test_prepare_audit_is_seeded_and_does_not_import_openclip(tmp_path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    keys = image_keys(3)
    for index, key in enumerate(keys):
        image = Image.new("RGB", (64, 48), "white")
        ImageDraw.Draw(image).rectangle((4 + index, 5, 40, 30), fill="black")
        image.save(image_dir / key)
    before = set(sys.modules)

    first, generated_first = prepare_audit(
        image_dir,
        keys,
        sample_size=2,
        seed=7,
    )
    second, generated_second = prepare_audit(
        image_dir,
        keys,
        sample_size=2,
        seed=7,
    )

    assert first == second
    assert first["transform_success_count"] == 2 * len(TRANSFORM_NAMES)
    assert set(generated_first) == set(generated_second)
    assert "open_clip" not in set(sys.modules) - before


def test_model_metric_aggregation_with_injected_lightweight_encoder(tmp_path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    key = "mark-000.png"
    image = Image.new("RGB", (64, 48), "white")
    ImageDraw.Draw(image).rectangle((5, 5, 40, 30), fill="black")
    image.save(image_dir / key)
    report, generated = prepare_audit(
        image_dir,
        [key],
        sample_size=1,
        seed=1,
    )
    report["image_dir"] = str(image_dir)

    class FakeIndex:
        ntotal = 1

        def reconstruct(self, index):
            return np.array([1.0, 0.0], dtype=np.float32)

    def encoder(_image):
        return np.array([1.0, 0.0], dtype=np.float32)

    def search_fn(_index, _query, *, k):
        return np.array([1.0], dtype=np.float32), np.array([0], dtype=np.int64)

    result = evaluate_model_robustness(
        report,
        generated,
        keys=[key],
        image_dir=image_dir,
        index=FakeIndex(),
        encoder=encoder,
        search_fn=search_fn,
        score_fn=lambda distances: {"status_code": "STRONG_MATCH"},
    )

    assert result["mode"] == "with_model"
    assert set(result["model_metrics"]) == {"original", *TRANSFORM_NAMES}
    assert all(
        metrics["recall_at_1"] == 1.0
        and metrics["recall_at_5"] == 1.0
        and metrics["status_stability"] == 1.0
        for metrics in result["model_metrics"].values()
    )
