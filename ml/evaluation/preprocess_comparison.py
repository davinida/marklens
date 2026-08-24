"""Paired, closed-world comparison of two image preprocessing contracts."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable, Mapping, Sequence

import numpy as np
from PIL import Image
from src.preprocess import GLOBAL_PREPROCESS_VERSION, LEGACY_PREPROCESS_VERSION

from evaluation.labeling import VISUAL_LABELS, validate_labeling_pack
from evaluation.robustness import TRANSFORM_NAMES, perturb_image, resolve_key

BENCHMARK_VERSION = "preprocess-comparison-v1"
METRIC_VERSION = "paired-closed-world-retrieval-v1"
PREPROCESS_VERSIONS = (LEGACY_PREPROCESS_VERSION, GLOBAL_PREPROCESS_VERSION)
SUMMARY_METRICS = (
    "exact_recall_at_1",
    "exact_recall_at_5",
    "family_recall_at_1",
    "family_recall_at_5",
    "target_similarity_mean",
    "target_to_nonfamily_margin_mean",
)
BOOTSTRAP_METRICS = (
    "exact_recall_at_1",
    "family_recall_at_1",
    "target_similarity",
    "target_to_nonfamily_margin",
)

BatchEncoder = Callable[[Sequence[Image.Image], str], np.ndarray]

READINESS_POLICY_VERSION = "visual-label-readiness-v1"
MAX_CANNOT_ASSESS_RATE = 0.10
MIN_DEV_PER_TRAINABLE_CLASS = 10
MIN_HOLDOUT_PER_TRAINABLE_CLASS = 2
TRAINABLE_LABELS = tuple(label for label in VISUAL_LABELS if label != "cannot_assess")


def aspect_bucket(width: int, height: int) -> str:
    """Return a stable geometry slice for one source image."""
    ratio = width / height
    if ratio < 2 / 3:
        return "tall"
    if ratio > 3 / 2:
        return "wide"
    return "near_square"


def assess_labeling_readiness(pack: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate the v2 human-label data gate without training or opening artifacts."""
    try:
        validate_labeling_pack(dict(pack), require_blank=False)
    except (TypeError, ValueError) as exc:
        return {
            "policy_version": READINESS_POLICY_VERSION,
            "status": "not_ready",
            "fine_tuning_data_gate_open": False,
            "structural_valid": False,
            "reasons": ["invalid_labeling_pack_structure"],
            "validation_error": f"{type(exc).__name__}: {exc}",
            "holdout_training_use_allowed": False,
        }

    pairs = list(pack["pairs"])
    expected_by_split = {"dev": 160, "frozen_holdout": 40}
    split_reports: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    for split, expected_count in expected_by_split.items():
        split_pairs = [pair for pair in pairs if pair["split"] == split]
        labels = [pair["annotation"]["visual_similarity"] for pair in split_pairs]
        confidence = [pair["annotation"]["confidence"] for pair in split_pairs]
        annotators = [pair["annotation"]["annotator_id"] for pair in split_pairs]
        label_counts = Counter(label for label in labels if label is not None)
        labeled_count = sum(label is not None for label in labels)
        cannot_count = label_counts.get("cannot_assess", 0)
        cannot_rate = cannot_count / labeled_count if labeled_count else None
        missing_confidence = sum(value is None for value in confidence)
        missing_annotator = sum(
            not isinstance(value, str) or not value.strip() for value in annotators
        )
        class_minimums = {
            label: (
                MIN_DEV_PER_TRAINABLE_CLASS
                if split == "dev"
                else MIN_HOLDOUT_PER_TRAINABLE_CLASS
            )
            for label in TRAINABLE_LABELS
        }
        class_coverage_met = all(
            label_counts.get(label, 0) >= minimum
            for label, minimum in class_minimums.items()
        )
        complete = (
            len(split_pairs) == expected_count
            and labeled_count == expected_count
            and missing_confidence == 0
            and missing_annotator == 0
        )
        cannot_rate_met = (
            cannot_rate is not None and cannot_rate <= MAX_CANNOT_ASSESS_RATE
        )
        if labeled_count == 0:
            reasons.append(f"{split}_has_zero_labels")
        elif labeled_count != expected_count:
            reasons.append(f"{split}_labels_incomplete")
        if missing_confidence:
            reasons.append(f"{split}_confidence_incomplete")
        if missing_annotator:
            reasons.append(f"{split}_annotator_provenance_incomplete")
        if cannot_rate is not None and not cannot_rate_met:
            reasons.append(f"{split}_cannot_assess_rate_exceeds_policy")
        if not class_coverage_met:
            reasons.append(f"{split}_trainable_class_minimum_not_met")
        split_reports[split] = {
            "expected_pair_count": expected_count,
            "actual_pair_count": len(split_pairs),
            "labeled_pair_count": labeled_count,
            "missing_label_count": expected_count - labeled_count,
            "missing_confidence_count": missing_confidence,
            "missing_annotator_id_count": missing_annotator,
            "label_counts": dict(sorted(label_counts.items())),
            "cannot_assess_count": cannot_count,
            "cannot_assess_rate": cannot_rate,
            "max_cannot_assess_rate": MAX_CANNOT_ASSESS_RATE,
            "trainable_class_minimums": class_minimums,
            "complete": complete,
            "cannot_assess_rate_met": cannot_rate_met,
            "trainable_class_coverage_met": class_coverage_met,
        }

    ready = not reasons
    return {
        "policy_version": READINESS_POLICY_VERSION,
        "pack_id": pack.get("pack_id"),
        "status": "ready" if ready else "not_ready",
        "fine_tuning_data_gate_open": ready,
        "structural_valid": True,
        "reasons": reasons,
        "total_expected_pair_count": 200,
        "total_labeled_pair_count": sum(
            report["labeled_pair_count"] for report in split_reports.values()
        ),
        "splits": split_reports,
        "holdout_training_use_allowed": False,
        "scope_note": (
            "Passing this minimum data-quality gate permits a modeling review only; "
            "it does not itself justify OpenCLIP fine-tuning or allow holdout training."
        ),
    }


def _validated_vectors(
    vectors: np.ndarray,
    *,
    expected_rows: int,
    label: str,
) -> np.ndarray:
    result = np.asarray(vectors, dtype=np.float32)
    if result.ndim != 2 or result.shape[0] != expected_rows or result.shape[1] < 2:
        raise ValueError(
            f"{label} embeddings have invalid shape: {result.shape}; "
            f"expected ({expected_rows}, D>=2)"
        )
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{label} embeddings contain non-finite values")
    norms = np.linalg.norm(result, axis=1)
    if not np.allclose(norms, 1.0, rtol=0.0, atol=1e-3):
        raise ValueError(f"{label} embeddings are not L2-normalized")
    return result


def _transform_set_digest(
    digest: hashlib._Hash,
    *,
    key: str,
    transform_name: str,
    image: Image.Image,
) -> None:
    digest.update(key.encode("utf-8"))
    digest.update(b"\0")
    digest.update(transform_name.encode("ascii"))
    digest.update(b"\0")
    digest.update(image.mode.encode("ascii"))
    digest.update(f"{image.width}x{image.height}".encode("ascii"))
    digest.update(b"\0")
    digest.update(image.tobytes())
    digest.update(b"\n")


def _rank_records(
    *,
    keys: Sequence[str],
    image_hashes: Mapping[str, str],
    aspect_buckets: Mapping[str, str],
    gallery: np.ndarray,
    queries: np.ndarray,
    transform_name: str,
) -> list[dict[str, Any]]:
    similarities = queries @ gallery.T
    if not np.all(np.isfinite(similarities)):
        raise ValueError("Similarity matrix contains non-finite values")

    records: list[dict[str, Any]] = []
    index_tiebreaker = np.arange(len(keys))
    for expected_index, key in enumerate(keys):
        row = similarities[expected_index]
        order = np.lexsort((index_tiebreaker, -row))
        exact_position = int(np.flatnonzero(order == expected_index)[0] + 1)
        family_hash = image_hashes[key]
        family_indices = np.array(
            [
                index
                for index, candidate in enumerate(keys)
                if image_hashes[candidate] == family_hash
            ]
        )
        family_positions = [
            int(np.flatnonzero(order == family_index)[0] + 1)
            for family_index in family_indices
        ]
        family_rank = min(family_positions)
        nonfamily_indices = np.array(
            [
                index
                for index, candidate in enumerate(keys)
                if image_hashes[candidate] != family_hash
            ]
        )
        if nonfamily_indices.size == 0:
            raise ValueError("At least two source-hash families are required")
        best_nonfamily_similarity = float(np.max(row[nonfamily_indices]))
        target_similarity = float(row[expected_index])
        records.append(
            {
                "image_key": key,
                "aspect_bucket": aspect_buckets[key],
                "transform": transform_name,
                "exact_rank": exact_position,
                "family_rank": family_rank,
                "exact_recall_at_1": exact_position == 1,
                "exact_recall_at_5": exact_position <= 5,
                "family_recall_at_1": family_rank == 1,
                "family_recall_at_5": family_rank <= 5,
                "target_similarity": target_similarity,
                "best_nonfamily_similarity": best_nonfamily_similarity,
                "target_to_nonfamily_margin": (
                    target_similarity - best_nonfamily_similarity
                ),
                "top1_key": keys[int(order[0])],
            }
        )
    return records


def summarize_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise ValueError("Cannot summarize an empty record set")
    target_similarities = [float(record["target_similarity"]) for record in records]
    margins = [float(record["target_to_nonfamily_margin"]) for record in records]
    return {
        "count": len(records),
        "exact_recall_at_1": mean(bool(record["exact_recall_at_1"]) for record in records),
        "exact_recall_at_5": mean(bool(record["exact_recall_at_5"]) for record in records),
        "family_recall_at_1": mean(bool(record["family_recall_at_1"]) for record in records),
        "family_recall_at_5": mean(bool(record["family_recall_at_5"]) for record in records),
        "target_similarity_mean": mean(target_similarities),
        "target_similarity_median": median(target_similarities),
        "target_similarity_p10": float(np.percentile(target_similarities, 10)),
        "target_similarity_min": min(target_similarities),
        "target_to_nonfamily_margin_mean": mean(margins),
        "target_to_nonfamily_margin_median": median(margins),
        "target_to_nonfamily_margin_p10": float(np.percentile(margins, 10)),
        "target_to_nonfamily_margin_min": min(margins),
        "positive_target_margin_rate": mean(margin > 0 for margin in margins),
    }


def _mode_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped_by_transform: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    grouped_by_aspect: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped_by_transform[str(record["transform"])].append(record)
        if record["transform"] != "original":
            grouped_by_aspect[str(record["aspect_bucket"])].append(record)
    perturbation_records = [
        record for record in records if record["transform"] != "original"
    ]
    return {
        "clean_self_retrieval": summarize_records(grouped_by_transform["original"]),
        "all_perturbations": summarize_records(perturbation_records),
        "by_transform": {
            name: summarize_records(grouped_by_transform[name])
            for name in ("original", *TRANSFORM_NAMES)
        },
        "by_aspect_bucket": {
            name: summarize_records(values)
            for name, values in sorted(grouped_by_aspect.items())
        },
    }


def _summary_deltas(
    legacy: Mapping[str, Any],
    global_: Mapping[str, Any],
) -> dict[str, float]:
    return {
        metric: float(global_[metric]) - float(legacy[metric])
        for metric in SUMMARY_METRICS
    }


def _paired_bootstrap(
    *,
    keys: Sequence[str],
    legacy_records: Sequence[Mapping[str, Any]],
    global_records: Sequence[Mapping[str, Any]],
    seed: int,
    samples: int,
) -> dict[str, Any]:
    if samples <= 0:
        raise ValueError("bootstrap sample count must be positive")
    legacy_by_key: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    global_by_key: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in legacy_records:
        if record["transform"] != "original":
            legacy_by_key[str(record["image_key"])].append(record)
    for record in global_records:
        if record["transform"] != "original":
            global_by_key[str(record["image_key"])].append(record)

    rng = np.random.default_rng(seed)
    sampled_indices = rng.integers(0, len(keys), size=(samples, len(keys)))
    result: dict[str, Any] = {}
    for metric in BOOTSTRAP_METRICS:
        per_image_deltas = np.array(
            [
                mean(float(row[metric]) for row in global_by_key[key])
                - mean(float(row[metric]) for row in legacy_by_key[key])
                for key in keys
            ],
            dtype=np.float64,
        )
        bootstrap_means = per_image_deltas[sampled_indices].mean(axis=1)
        tolerance = 1e-12
        result[metric] = {
            "observed_mean_delta": float(per_image_deltas.mean()),
            "ci95": [
                float(np.percentile(bootstrap_means, 2.5)),
                float(np.percentile(bootstrap_means, 97.5)),
            ],
            "image_win_count": int(np.sum(per_image_deltas > tolerance)),
            "image_tie_count": int(np.sum(np.abs(per_image_deltas) <= tolerance)),
            "image_loss_count": int(np.sum(per_image_deltas < -tolerance)),
        }
    return result


def compare_preprocessing(
    *,
    keys: Sequence[str],
    image_dir: Path,
    image_hashes: Mapping[str, str],
    encoder: BatchEncoder,
    bootstrap_seed: int,
    bootstrap_samples: int,
) -> dict[str, Any]:
    """Encode the same sources and perturbations under both contracts."""
    if len(keys) < 2 or len(set(keys)) != len(keys):
        raise ValueError("At least two unique image keys are required")
    if set(image_hashes) != set(keys):
        raise ValueError("image_hashes must exactly cover keys")

    sources: list[Image.Image] = []
    aspects: dict[str, str] = {}
    mode_counts: dict[str, int] = defaultdict(int)
    try:
        for key in keys:
            path = resolve_key(image_dir, key)
            with Image.open(path) as opened:
                source = opened.copy()
            sources.append(source)
            aspects[key] = aspect_bucket(source.width, source.height)
            mode_counts[source.mode] += 1

        galleries = {
            version: _validated_vectors(
                encoder(sources, version),
                expected_rows=len(keys),
                label=f"{version} gallery",
            )
            for version in PREPROCESS_VERSIONS
        }
        query_vectors: dict[str, dict[str, np.ndarray]] = {
            version: {"original": galleries[version]}
            for version in PREPROCESS_VERSIONS
        }
        transform_digest = hashlib.sha256()
        for transform_name in TRANSFORM_NAMES:
            transformed = [
                perturb_image(source, transform_name) for source in sources
            ]
            try:
                for key, image in zip(keys, transformed):
                    _transform_set_digest(
                        transform_digest,
                        key=key,
                        transform_name=transform_name,
                        image=image,
                    )
                for version in PREPROCESS_VERSIONS:
                    query_vectors[version][transform_name] = _validated_vectors(
                        encoder(transformed, version),
                        expected_rows=len(keys),
                        label=f"{version} {transform_name}",
                    )
            finally:
                for image in transformed:
                    image.close()

        records_by_mode: dict[str, list[dict[str, Any]]] = {}
        summaries: dict[str, dict[str, Any]] = {}
        for version in PREPROCESS_VERSIONS:
            records: list[dict[str, Any]] = []
            for transform_name in ("original", *TRANSFORM_NAMES):
                records.extend(
                    _rank_records(
                        keys=keys,
                        image_hashes=image_hashes,
                        aspect_buckets=aspects,
                        gallery=galleries[version],
                        queries=query_vectors[version][transform_name],
                        transform_name=transform_name,
                    )
                )
            records_by_mode[version] = records
            summaries[version] = _mode_summary(records)

        legacy_summary = summaries[LEGACY_PREPROCESS_VERSION]
        global_summary = summaries[GLOBAL_PREPROCESS_VERSION]
        clean_alignment = np.sum(
            galleries[LEGACY_PREPROCESS_VERSION]
            * galleries[GLOBAL_PREPROCESS_VERSION],
            axis=1,
        )
        return {
            "benchmark_version": BENCHMARK_VERSION,
            "metric_version": METRIC_VERSION,
            "source_image_count": len(keys),
            "query_count_per_mode": len(keys) * (1 + len(TRANSFORM_NAMES)),
            "perturbation_query_count_per_mode": len(keys) * len(TRANSFORM_NAMES),
            "source_mode_counts": dict(sorted(mode_counts.items())),
            "aspect_bucket_counts": {
                name: sum(value == name for value in aspects.values())
                for name in sorted(set(aspects.values()))
            },
            "transform_names": list(TRANSFORM_NAMES),
            "transform_set_sha256": transform_digest.hexdigest(),
            "preprocess_versions": list(PREPROCESS_VERSIONS),
            "production_index_used_for_retrieval": False,
            "modes": {
                version: {
                    "summary": summaries[version],
                    "records": records_by_mode[version],
                }
                for version in PREPROCESS_VERSIONS
            },
            "paired_deltas_global_minus_legacy": {
                "all_perturbations": _summary_deltas(
                    legacy_summary["all_perturbations"],
                    global_summary["all_perturbations"],
                ),
                "by_transform": {
                    name: _summary_deltas(
                        legacy_summary["by_transform"][name],
                        global_summary["by_transform"][name],
                    )
                    for name in ("original", *TRANSFORM_NAMES)
                },
                "by_aspect_bucket": {
                    name: _summary_deltas(
                        legacy_summary["by_aspect_bucket"][name],
                        global_summary["by_aspect_bucket"][name],
                    )
                    for name in sorted(
                        set(legacy_summary["by_aspect_bucket"])
                        & set(global_summary["by_aspect_bucket"])
                    )
                },
            },
            "paired_bootstrap_by_source_image": {
                "seed": bootstrap_seed,
                "samples": bootstrap_samples,
                "unit": "source_image",
                "scope": "mean_across_four_perturbations",
                "metrics": _paired_bootstrap(
                    keys=keys,
                    legacy_records=records_by_mode[LEGACY_PREPROCESS_VERSION],
                    global_records=records_by_mode[GLOBAL_PREPROCESS_VERSION],
                    seed=bootstrap_seed,
                    samples=bootstrap_samples,
                ),
            },
            "clean_cross_mode_cosine": {
                "mean": float(np.mean(clean_alignment)),
                "median": float(np.median(clean_alignment)),
                "p10": float(np.percentile(clean_alignment, 10)),
                "min": float(np.min(clean_alignment)),
            },
        }
    finally:
        for source in sources:
            source.close()
