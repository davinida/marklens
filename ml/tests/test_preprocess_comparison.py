"""Paired preprocessing comparison tests without loading OpenCLIP."""

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path

import numpy as np
from evaluation.preprocess_comparison import (
    GLOBAL_PREPROCESS_VERSION,
    LEGACY_PREPROCESS_VERSION,
    TRANSFORM_NAMES,
    aspect_bucket,
    assess_labeling_readiness,
    compare_preprocessing,
)
from PIL import Image, ImageDraw
from scripts.compare_preprocessing import OpenClipBatchEncoder, _render_markdown

ML_ROOT = Path(__file__).resolve().parents[1]


def _fake_encoder(images, _version):
    rows = []
    for image in images:
        resized = image.convert("RGB").resize((4, 4), Image.Resampling.BILINEAR)
        vector = np.asarray(resized, dtype=np.float32).reshape(-1)
        vector = np.concatenate([vector, np.array([image.width, image.height])])
        vector /= np.linalg.norm(vector)
        rows.append(vector.astype(np.float32))
    return np.stack(rows)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_aspect_bucket_boundaries():
    assert aspect_bucket(60, 100) == "tall"
    assert aspect_bucket(100, 100) == "near_square"
    assert aspect_bucket(200, 100) == "wide"


def test_batch_encoder_records_the_actual_device_consistently():
    encoder = OpenClipBatchEncoder(batch_size=4)

    assert encoder.device is None
    assert encoder._record_device("cpu") == "cpu"
    assert encoder.device == "cpu"

    with np.testing.assert_raises_regex(RuntimeError, "device changed"):
        encoder._record_device("cuda:0")


def test_markdown_uses_the_report_source_count():
    report = json.loads(
        (ML_ROOT / "evaluation" / "preprocess_comparison_full_v1.json").read_text(
            encoding="utf-8"
        )
    )

    rendered = _render_markdown(report)
    source_count = report["source_image_count"]

    assert f"{source_count}개 원본 이미지를 재표집" in rendered
    assert f"동일 {source_count}개 원본이 갤러리" in rendered
    assert f"등록표장 중심 {source_count}건" in rendered
    if source_count != 100:
        assert "100개 원본" not in rendered


def test_paired_comparison_is_deterministic_and_family_aware(tmp_path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    first = Image.new("RGB", (80, 40), "white")
    ImageDraw.Draw(first).rectangle((5, 5, 35, 30), fill="red")
    second = Image.new("RGB", (80, 40), "white")
    ImageDraw.Draw(second).ellipse((40, 5, 72, 35), fill="blue")
    first.save(image_dir / "a.png")
    shutil.copyfile(image_dir / "a.png", image_dir / "b.png")
    second.save(image_dir / "c.png")
    keys = ["a.png", "b.png", "c.png"]
    image_hashes = {key: _sha256(image_dir / key) for key in keys}

    kwargs = {
        "keys": keys,
        "image_dir": image_dir,
        "image_hashes": image_hashes,
        "encoder": _fake_encoder,
        "bootstrap_seed": 17,
        "bootstrap_samples": 100,
    }
    first_report = compare_preprocessing(**kwargs)
    second_report = compare_preprocessing(**kwargs)

    assert first_report == second_report
    assert first_report["source_image_count"] == 3
    assert first_report["query_count_per_mode"] == 3 * (1 + len(TRANSFORM_NAMES))
    assert first_report["aspect_bucket_counts"] == {"wide": 3}
    assert first_report["production_index_used_for_retrieval"] is False
    for version in (LEGACY_PREPROCESS_VERSION, GLOBAL_PREPROCESS_VERSION):
        clean = first_report["modes"][version]["summary"]["clean_self_retrieval"]
        assert clean["exact_recall_at_1"] == 2 / 3
        assert clean["family_recall_at_1"] == 1.0
        assert clean["family_recall_at_5"] == 1.0
        assert len(first_report["modes"][version]["records"]) == 15
    paired = first_report["paired_bootstrap_by_source_image"]
    assert paired["unit"] == "source_image"
    assert paired["samples"] == 100
    assert all(
        values["observed_mean_delta"] == 0.0
        for values in paired["metrics"].values()
    )


def _labeling_pack():
    return json.loads(
        (ML_ROOT / "evaluation" / "labeling_pack_v2.json").read_text(encoding="utf-8")
    )


def test_blank_v2_pack_closes_fine_tuning_gate():
    result = assess_labeling_readiness(_labeling_pack())

    assert result["status"] == "not_ready"
    assert result["fine_tuning_data_gate_open"] is False
    assert result["total_labeled_pair_count"] == 0
    assert "dev_has_zero_labels" in result["reasons"]
    assert "frozen_holdout_has_zero_labels" in result["reasons"]
    assert result["splits"]["dev"]["cannot_assess_rate"] is None


def test_complete_balanced_v2_pack_opens_minimum_data_gate():
    pack = deepcopy(_labeling_pack())
    labels = ("same_or_near_duplicate", "visually_similar", "visually_distinct")
    counters = {"dev": 0, "frozen_holdout": 0}
    for pair in pack["pairs"]:
        split = pair["split"]
        label = labels[counters[split] % len(labels)]
        counters[split] += 1
        pair["annotation"] = {
            "visual_similarity": label,
            "confidence": "high",
            "annotator_id": "unit-test",
            "notes": None,
        }

    result = assess_labeling_readiness(pack)

    assert result["status"] == "ready"
    assert result["fine_tuning_data_gate_open"] is True
    assert result["reasons"] == []
    assert result["total_labeled_pair_count"] == 200
    assert result["holdout_training_use_allowed"] is False


def test_cannot_assess_rate_and_class_floor_close_gate():
    pack = deepcopy(_labeling_pack())
    for pair in pack["pairs"]:
        pair["annotation"] = {
            "visual_similarity": "cannot_assess",
            "confidence": "high",
            "annotator_id": "unit-test",
            "notes": None,
        }

    result = assess_labeling_readiness(pack)

    assert result["fine_tuning_data_gate_open"] is False
    assert "dev_cannot_assess_rate_exceeds_policy" in result["reasons"]
    assert "dev_trainable_class_minimum_not_met" in result["reasons"]
