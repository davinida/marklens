"""Build a deterministic, leakage-resistant visual-similarity labeling pack."""

from __future__ import annotations

import hashlib
import json
import os
import random
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

import numpy as np

PACK_SCHEMA_VERSION = 2
PACK_PROTOCOL = "visual-similarity-labeling-v2"
PAIR_COUNT = 200
DEV_COUNT = 160
HOLDOUT_COUNT = 40
SPLIT_SEED = 20260814
HOLDOUT_IMAGE_FRACTION = 0.25
FAMILY_SIMILARITY_THRESHOLD = 0.995
MAX_SPLIT_TRIALS = 20_000

SIMILARITY_STRATA = (
    ("below_weak", -1.000001, 0.45),
    ("weak_band", 0.45, 0.55),
    ("possible_band", 0.55, 0.75),
    ("strong_band", 0.75, 1.000001),
)
STRATUM_PAIR_COUNTS = {
    name: {"dev": 40, "frozen_holdout": 10}
    for name, _, _ in SIMILARITY_STRATA
}
VISUAL_LABELS = (
    "same_or_near_duplicate",
    "visually_similar",
    "visually_distinct",
    "cannot_assess",
)
CONFIDENCE_LABELS = ("high", "medium", "low")
ANNOTATION_FIELDS = (
    "visual_similarity",
    "confidence",
    "annotator_id",
    "notes",
)
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


@dataclass(frozen=True)
class _Candidate:
    left_index: int
    right_index: int
    pair_id: str
    similarity: float
    stratum: str
    left_family: str
    right_family: str


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item: int) -> int:
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != item:
            parent = self.parent[item]
            self.parent[item] = root
            item = parent
        return root

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_set_sha256(image_dir: Path, keys: Sequence[str]) -> str:
    """Hash ordered image keys and bytes, rejecting missing/path-escape inputs."""
    root = image_dir.resolve(strict=True)
    digest = hashlib.sha256()
    for key in keys:
        key_path = PurePosixPath(key.replace("\\", "/"))
        path = root.joinpath(*key_path.parts).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Image key escapes image-dir: {key!r}") from exc
        if not path.is_file():
            raise FileNotFoundError(f"Image is missing: {key}")
        digest.update(key.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _validated_image_keys(raw_keys: Any) -> list[str]:
    if not isinstance(raw_keys, list):
        raise ValueError("image keys must be an array")
    keys: list[str] = []
    seen: set[str] = set()
    for raw_key in raw_keys:
        if not isinstance(raw_key, str) or not raw_key or raw_key != raw_key.strip():
            raise ValueError(f"Invalid image key: {raw_key!r}")
        normalized = raw_key.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            path.is_absolute()
            or normalized.startswith("//")
            or any(part in ("", ".", "..") for part in path.parts)
            or (path.parts and ":" in path.parts[0])
            or path.suffix.lower() not in SUPPORTED_EXTENSIONS
        ):
            raise ValueError(f"Unsafe or unsupported image key: {raw_key!r}")
        key = path.as_posix()
        if key.casefold() in seen:
            raise ValueError(f"Duplicate image key: {key!r}")
        seen.add(key.casefold())
        keys.append(key)
    if len(keys) < 2:
        raise ValueError("At least two image keys are required")
    return keys


def load_image_keys(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        raw_keys = payload
    elif isinstance(payload, dict) and isinstance(payload.get("image_paths"), list):
        raw_keys = payload["image_paths"]
    elif isinstance(payload, dict) and isinstance(payload.get("image_keys"), list):
        raw_keys = payload["image_keys"]
    else:
        raise ValueError("Expected image_paths or image_keys in metadata")
    return _validated_image_keys(raw_keys)


def similarity_stratum(similarity: float) -> str:
    if not np.isfinite(similarity):
        raise ValueError("Pair similarity must be finite")
    for name, lower, upper in SIMILARITY_STRATA:
        if lower <= similarity < upper:
            return name
    raise ValueError(f"Pair similarity is outside cosine bounds: {similarity}")


def _pair_id(left: str, right: str) -> str:
    first, second = sorted((left, right), key=str.casefold)
    digest = hashlib.sha256(
        f"marklens-visual-pair-v2\0{first}\0{second}".encode("utf-8")
    ).hexdigest()
    return f"vp2_{digest[:20]}"


def _family_id(keys: Sequence[str]) -> str:
    digest = hashlib.sha256(
        ("marklens-visual-family-v2\0" + "\0".join(keys)).encode("utf-8")
    ).hexdigest()
    return f"vf2_{digest[:16]}"


def _validated_embeddings(keys: Sequence[str], embeddings: np.ndarray) -> np.ndarray:
    vectors = np.asarray(embeddings, dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != len(keys):
        raise ValueError(
            "Embedding row count must match image keys: "
            f"{vectors.shape} versus {len(keys)}"
        )
    if vectors.shape[1] < 2:
        raise ValueError("Embeddings must have at least two dimensions")
    if not np.all(np.isfinite(vectors)):
        raise ValueError("Embeddings contain NaN or infinite values")
    norms = np.linalg.norm(vectors, axis=1)
    if not np.allclose(norms, 1.0, rtol=0.0, atol=1e-3):
        raise ValueError("Embeddings must be L2-normalized")
    return vectors


def _validated_image_hashes(
    keys: Sequence[str], image_hashes: Mapping[str, str] | None
) -> dict[str, str]:
    if image_hashes is None:
        return {}
    if set(image_hashes) != set(keys):
        raise ValueError("image_hashes must exactly cover image keys")
    validated: dict[str, str] = {}
    for key in keys:
        value = image_hashes[key]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"Invalid image SHA-256 for {key!r}")
        validated[key] = value
    return validated


def _build_families(
    keys: Sequence[str],
    vectors: np.ndarray,
    image_hashes: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    union = _UnionFind(len(keys))
    hash_owner: dict[str, int] = {}
    for index, key in enumerate(keys):
        image_hash = image_hashes.get(key)
        if image_hash is None:
            continue
        owner = hash_owner.setdefault(image_hash, index)
        union.union(owner, index)

    similarities = vectors @ vectors.T
    if not np.all(np.isfinite(similarities)):
        raise ValueError("Embedding similarity matrix contains non-finite values")
    for left_index, right_index in combinations(range(len(keys)), 2):
        if similarities[left_index, right_index] >= FAMILY_SIMILARITY_THRESHOLD:
            union.union(left_index, right_index)

    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(keys)):
        groups[union.find(index)].append(index)
    ordered_groups = sorted(
        (
            sorted(indices, key=lambda index: keys[index].casefold())
            for indices in groups.values()
        ),
        key=lambda indices: keys[indices[0]].casefold(),
    )

    families: list[dict[str, Any]] = []
    family_by_index = [""] * len(keys)
    for indices in ordered_groups:
        family_keys = [keys[index] for index in indices]
        family_id = _family_id(family_keys)
        families.append(
            {
                "family_id": family_id,
                "image_keys": family_keys,
            }
        )
        for index in indices:
            family_by_index[index] = family_id
    return families, family_by_index


def _candidate_pairs(
    keys: Sequence[str],
    vectors: np.ndarray,
    family_by_index: Sequence[str],
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for left_index, right_index in combinations(range(len(keys)), 2):
        raw_similarity = float(np.dot(vectors[left_index], vectors[right_index]))
        similarity = float(np.clip(raw_similarity, -1.0, 1.0))
        candidates.append(
            _Candidate(
                left_index=left_index,
                right_index=right_index,
                pair_id=_pair_id(keys[left_index], keys[right_index]),
                similarity=similarity,
                stratum=similarity_stratum(similarity),
                left_family=family_by_index[left_index],
                right_family=family_by_index[right_index],
            )
        )
    return candidates


def _trial_seed(seed: int, trial: int) -> int:
    digest = hashlib.sha256(f"family-split-v2\0{seed}\0{trial}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _partition_capacities(
    candidates: Sequence[_Candidate],
    family_splits: Mapping[str, str],
) -> dict[str, Counter[str]]:
    capacities = {
        "dev": Counter(),
        "frozen_holdout": Counter(),
    }
    for candidate in candidates:
        left_split = family_splits[candidate.left_family]
        if left_split == family_splits[candidate.right_family]:
            capacities[left_split][candidate.stratum] += 1
    return capacities


def _choose_family_split(
    families: Sequence[dict[str, Any]],
    candidates: Sequence[_Candidate],
    *,
    seed: int,
) -> tuple[dict[str, str], int, dict[str, Counter[str]]]:
    ordered_ids = [family["family_id"] for family in families]
    family_sizes = {
        family["family_id"]: len(family["image_keys"]) for family in families
    }
    total_images = sum(family_sizes.values())
    target_holdout_images = max(2, round(total_images * HOLDOUT_IMAGE_FRACTION))
    best_capacities = {
        "dev": Counter(),
        "frozen_holdout": Counter(),
    }

    for trial in range(MAX_SPLIT_TRIALS):
        shuffled = list(ordered_ids)
        random.Random(_trial_seed(seed, trial)).shuffle(shuffled)
        holdout_families: set[str] = set()
        holdout_images = 0
        for family_id in shuffled:
            if holdout_images >= target_holdout_images:
                break
            holdout_families.add(family_id)
            holdout_images += family_sizes[family_id]
        if not holdout_families or len(holdout_families) == len(families):
            continue
        family_splits = {
            family_id: (
                "frozen_holdout" if family_id in holdout_families else "dev"
            )
            for family_id in ordered_ids
        }
        capacities = _partition_capacities(candidates, family_splits)
        for split in capacities:
            for stratum in capacities[split]:
                best_capacities[split][stratum] = max(
                    best_capacities[split][stratum], capacities[split][stratum]
                )
        if all(
            capacities[split][stratum] >= required
            for stratum, counts in STRATUM_PAIR_COUNTS.items()
            for split, required in counts.items()
        ):
            return family_splits, trial, capacities

    summary = {
        split: {name: counts[name] for name, _, _ in SIMILARITY_STRATA}
        for split, counts in best_capacities.items()
    }
    raise ValueError(
        "Could not create an image/family-disjoint split with all similarity "
        f"quotas after {MAX_SPLIT_TRIALS} trials; best capacities={summary}"
    )


def _selection_rank(
    candidate: _Candidate,
    *,
    split: str,
    stratum: str,
    seed: int,
    usage: Mapping[int, int],
) -> tuple[int, int, str]:
    left_usage = usage.get(candidate.left_index, 0)
    right_usage = usage.get(candidate.right_index, 0)
    digest = hashlib.sha256(
        f"pair-selection-v2\0{seed}\0{split}\0{stratum}\0{candidate.pair_id}".encode(
            "ascii"
        )
    ).hexdigest()
    return max(left_usage, right_usage), left_usage + right_usage, digest


def _select_pairs(
    candidates: Sequence[_Candidate],
    family_splits: Mapping[str, str],
    *,
    seed: int,
) -> list[_Candidate]:
    available: dict[tuple[str, str], list[_Candidate]] = defaultdict(list)
    for candidate in candidates:
        split = family_splits[candidate.left_family]
        if split == family_splits[candidate.right_family]:
            available[(split, candidate.stratum)].append(candidate)

    selected: list[_Candidate] = []
    usage: Counter[int] = Counter()
    for split in ("dev", "frozen_holdout"):
        for stratum, _, _ in SIMILARITY_STRATA:
            quota = STRATUM_PAIR_COUNTS[stratum][split]
            pool = list(available[(split, stratum)])
            for _ in range(quota):
                if not pool:
                    raise ValueError(f"Insufficient {split}/{stratum} candidates")
                best = min(
                    pool,
                    key=lambda candidate: _selection_rank(
                        candidate,
                        split=split,
                        stratum=stratum,
                        seed=seed,
                        usage=usage,
                    ),
                )
                pool.remove(best)
                selected.append(best)
                usage[best.left_index] += 1
                usage[best.right_index] += 1
    return selected


def _strata_manifest() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "lower_inclusive": lower,
            "upper_exclusive": upper,
            "pair_counts": dict(STRATUM_PAIR_COUNTS[name]),
        }
        for name, lower, upper in SIMILARITY_STRATA
    ]


def _pack_id(pairs: Sequence[dict[str, Any]]) -> str:
    fingerprint = hashlib.sha256(
        "\n".join(
            f"{pair['pair_id']}:{pair['split']}:{pair['similarity_stratum']}"
            for pair in sorted(pairs, key=lambda pair: pair["pair_id"])
        ).encode("ascii")
    ).hexdigest()
    return f"vlp2_{fingerprint[:20]}"


def build_labeling_pack(
    keys: Sequence[str],
    *,
    embeddings: np.ndarray,
    image_hashes: Mapping[str, str] | None = None,
    source: dict[str, Any] | None = None,
    pair_count: int = PAIR_COUNT,
    holdout_count: int = HOLDOUT_COUNT,
    split_seed: int = SPLIT_SEED,
) -> dict[str, Any]:
    """Stratify pairs after assigning complete duplicate families to one split."""
    keys = _validated_image_keys(list(keys))
    if pair_count != PAIR_COUNT or holdout_count != HOLDOUT_COUNT:
        raise ValueError("The v2 protocol requires exactly 200 pairs and 40 holdout pairs")
    vectors = _validated_embeddings(keys, embeddings)
    hashes = _validated_image_hashes(keys, image_hashes)
    families, family_by_index = _build_families(keys, vectors, hashes)
    candidates = _candidate_pairs(keys, vectors, family_by_index)
    if len(candidates) < PAIR_COUNT:
        raise ValueError(
            f"Need at least {PAIR_COUNT} unique pairs, found {len(candidates)}"
        )
    family_splits, assignment_trial, capacities = _choose_family_split(
        families,
        candidates,
        seed=split_seed,
    )
    selected = _select_pairs(candidates, family_splits, seed=split_seed)

    pairs: list[dict[str, Any]] = []
    for candidate in selected:
        split = family_splits[candidate.left_family]
        pairs.append(
            {
                "pair_id": candidate.pair_id,
                "split": split,
                "frozen": split == "frozen_holdout",
                "similarity_stratum": candidate.stratum,
                "left": {
                    "image_key": keys[candidate.left_index],
                    "family_id": candidate.left_family,
                },
                "right": {
                    "image_key": keys[candidate.right_index],
                    "family_id": candidate.right_family,
                },
                "annotation": {field: None for field in ANNOTATION_FIELDS},
            }
        )
    pairs.sort(key=lambda pair: pair["pair_id"])

    published_families = [
        {
            **family,
            "split": family_splits[family["family_id"]],
        }
        for family in families
    ]
    family_counts = Counter(family["split"] for family in published_families)
    image_counts = Counter(
        family["split"]
        for family in published_families
        for _ in family["image_keys"]
    )
    capacity_manifest = {
        split: {name: capacities[split][name] for name, _, _ in SIMILARITY_STRATA}
        for split in ("dev", "frozen_holdout")
    }
    pack = {
        "schema_version": PACK_SCHEMA_VERSION,
        "protocol": PACK_PROTOCOL,
        "pack_id": _pack_id(pairs),
        "selection_method": "stratified_similarity_family_disjoint",
        "pair_count": PAIR_COUNT,
        "split_counts": {"dev": DEV_COUNT, "frozen_holdout": HOLDOUT_COUNT},
        "similarity_strata": _strata_manifest(),
        "split_policy": {
            "type": "image_and_family_disjoint",
            "seed": split_seed,
            "holdout_image_fraction_target": HOLDOUT_IMAGE_FRACTION,
            "family_similarity_threshold": FAMILY_SIMILARITY_THRESHOLD,
            "assignment_trial": assignment_trial,
            "image_counts": dict(image_counts),
            "family_counts": dict(family_counts),
            "candidate_capacities": capacity_manifest,
        },
        "label_scope": "visual_similarity_only",
        "source": source or {},
        "families": published_families,
        "pairs": pairs,
    }
    validate_labeling_pack(pack, require_blank=True)
    return pack


def validate_labeling_pack(pack: dict[str, Any], *, require_blank: bool) -> None:
    if pack.get("schema_version") != PACK_SCHEMA_VERSION:
        raise ValueError(f"Expected labeling schema version {PACK_SCHEMA_VERSION}")
    if pack.get("protocol") != PACK_PROTOCOL:
        raise ValueError(f"Expected protocol {PACK_PROTOCOL!r}")
    if pack.get("selection_method") != "stratified_similarity_family_disjoint":
        raise ValueError("Unexpected selection method")
    if pack.get("pair_count") != PAIR_COUNT:
        raise ValueError(f"Expected pair_count={PAIR_COUNT}")
    if pack.get("split_counts") != {
        "dev": DEV_COUNT,
        "frozen_holdout": HOLDOUT_COUNT,
    }:
        raise ValueError("Recorded split_counts are inconsistent")
    if pack.get("label_scope") != "visual_similarity_only":
        raise ValueError("Label scope must be visual_similarity_only")
    if not isinstance(pack.get("source"), dict):
        raise ValueError("Labeling source must be an object")
    if pack.get("similarity_strata") != _strata_manifest():
        raise ValueError("Similarity stratum contract or quotas changed")

    pairs = pack.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != PAIR_COUNT:
        raise ValueError(f"Labeling pack must contain exactly {PAIR_COUNT} pairs")
    if not all(isinstance(pair, dict) for pair in pairs):
        raise ValueError("Every labeling pair must be an object")
    ids = [pair.get("pair_id") for pair in pairs]
    if len(set(ids)) != PAIR_COUNT:
        raise ValueError("Pair IDs must be unique")
    try:
        expected_pack_id = _pack_id(pairs)
    except (KeyError, TypeError, UnicodeEncodeError) as exc:
        raise ValueError("Cannot derive pack ID from malformed pairs") from exc
    if pack.get("pack_id") != expected_pack_id:
        raise ValueError("Pack ID does not match pair membership and split strata")
    dev = sum(pair.get("split") == "dev" for pair in pairs)
    holdout = sum(pair.get("split") == "frozen_holdout" for pair in pairs)
    if (dev, holdout) != (DEV_COUNT, HOLDOUT_COUNT):
        raise ValueError(
            f"Expected {DEV_COUNT} dev and {HOLDOUT_COUNT} holdout pairs, "
            f"got {dev} and {holdout}"
        )

    families = pack.get("families")
    if not isinstance(families, list) or not families:
        raise ValueError("Labeling pack must contain family assignments")
    family_splits: dict[str, str] = {}
    image_assignments: dict[str, tuple[str, str]] = {}
    for family in families:
        if not isinstance(family, dict):
            raise ValueError("Family assignment must be an object")
        family_id = family.get("family_id")
        split = family.get("split")
        image_keys = family.get("image_keys")
        if not isinstance(family_id, str) or family_id in family_splits:
            raise ValueError(f"Duplicate or invalid family ID: {family_id!r}")
        if split not in ("dev", "frozen_holdout"):
            raise ValueError(f"Invalid family split: {split!r}")
        if not isinstance(image_keys, list) or not image_keys:
            raise ValueError(f"Family {family_id!r} has no images")
        family_splits[family_id] = split
        for image_key in image_keys:
            if not isinstance(image_key, str) or image_key in image_assignments:
                raise ValueError(f"Image appears in multiple families: {image_key!r}")
            image_assignments[image_key] = (family_id, split)

    seen_members: set[tuple[str, str]] = set()
    stratum_counts: Counter[tuple[str, str]] = Counter()
    used_by_split: dict[str, set[str]] = {"dev": set(), "frozen_holdout": set()}
    for pair in pairs:
        split = pair.get("split")
        if pair.get("frozen") != (split == "frozen_holdout"):
            raise ValueError(f"Frozen marker mismatch for {pair.get('pair_id')}")
        stratum = pair.get("similarity_stratum")
        if stratum not in STRATUM_PAIR_COUNTS:
            raise ValueError(f"Invalid similarity stratum: {stratum!r}")
        stratum_counts[(split, stratum)] += 1

        refs: list[tuple[str, str]] = []
        for side in ("left", "right"):
            reference = pair.get(side)
            if not isinstance(reference, dict):
                raise ValueError(f"Missing {side} reference for {pair.get('pair_id')}")
            image_key = reference.get("image_key")
            family_id = reference.get("family_id")
            if image_assignments.get(image_key) != (family_id, split):
                raise ValueError(
                    f"{side} image/family split mismatch for {pair.get('pair_id')}"
                )
            refs.append((image_key, family_id))
            used_by_split[split].add(image_key)
        if refs[0][0].casefold() == refs[1][0].casefold():
            raise ValueError(f"Pair repeats one image: {pair.get('pair_id')}")
        members = tuple(sorted((refs[0][0], refs[1][0]), key=str.casefold))
        if members in seen_members:
            raise ValueError(f"Duplicate pair members: {members!r}")
        seen_members.add(members)
        if pair.get("pair_id") != _pair_id(*members):
            raise ValueError(f"Pair ID does not match members: {pair.get('pair_id')}")

        annotation = pair.get("annotation")
        if not isinstance(annotation, dict) or set(annotation) != set(ANNOTATION_FIELDS):
            raise ValueError(f"Invalid annotation object for {pair.get('pair_id')}")
        if require_blank and any(value is not None for value in annotation.values()):
            raise ValueError("Generated packs must leave every annotation field null")
        label = annotation["visual_similarity"]
        confidence = annotation["confidence"]
        if label is not None and label not in VISUAL_LABELS:
            raise ValueError(f"Unsupported visual label: {label!r}")
        if confidence is not None and confidence not in CONFIDENCE_LABELS:
            raise ValueError(f"Unsupported confidence label: {confidence!r}")
        for field in ("annotator_id", "notes"):
            if annotation[field] is not None and not isinstance(annotation[field], str):
                raise ValueError(f"Annotation {field} must be a string or null")

    if used_by_split["dev"] & used_by_split["frozen_holdout"]:
        raise ValueError("Images must be disjoint between dev and frozen holdout")
    for stratum, counts in STRATUM_PAIR_COUNTS.items():
        for split, expected in counts.items():
            actual = stratum_counts[(split, stratum)]
            if actual != expected:
                raise ValueError(
                    f"Expected {expected} {split}/{stratum} pairs, got {actual}"
                )

    policy = pack.get("split_policy")
    if not isinstance(policy, dict) or policy.get("type") != "image_and_family_disjoint":
        raise ValueError("Missing image/family-disjoint split policy")
    if isinstance(policy.get("seed"), bool) or not isinstance(policy.get("seed"), int):
        raise ValueError("Split seed must be an integer")
    if policy.get("holdout_image_fraction_target") != HOLDOUT_IMAGE_FRACTION:
        raise ValueError("Holdout image fraction target changed")
    if policy.get("family_similarity_threshold") != FAMILY_SIMILARITY_THRESHOLD:
        raise ValueError("Family similarity threshold changed")
    assignment_trial = policy.get("assignment_trial")
    if (
        isinstance(assignment_trial, bool)
        or not isinstance(assignment_trial, int)
        or assignment_trial < 0
    ):
        raise ValueError("Split assignment trial must be a non-negative integer")
    actual_family_counts = Counter(family_splits.values())
    actual_image_counts = Counter(split for _, split in image_assignments.values())
    if policy.get("family_counts") != dict(actual_family_counts):
        raise ValueError("Recorded family split counts are inconsistent")
    if policy.get("image_counts") != dict(actual_image_counts):
        raise ValueError("Recorded image split counts are inconsistent")
    capacities = policy.get("candidate_capacities")
    if not isinstance(capacities, dict):
        raise ValueError("Candidate capacities must be an object")
    for stratum, counts in STRATUM_PAIR_COUNTS.items():
        for split, required in counts.items():
            split_capacities = capacities.get(split)
            if (
                not isinstance(split_capacities, dict)
                or isinstance(split_capacities.get(stratum), bool)
                or not isinstance(split_capacities.get(stratum), int)
                or split_capacities[stratum] < required
            ):
                raise ValueError(
                    f"Candidate capacity is insufficient for {split}/{stratum}"
                )


def _json_object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _load_replaceable_blank_pack(path: Path) -> dict[str, Any]:
    """Load one valid v2 pack and reject any human-entered annotation data."""
    try:
        existing = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_json_object_without_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FileExistsError(
            f"Refusing to replace malformed labeling pack: {path}"
        ) from exc
    if not isinstance(existing, dict):
        raise FileExistsError(
            f"Refusing to replace non-object labeling pack: {path}"
        )
    try:
        validate_labeling_pack(existing, require_blank=False)
    except (KeyError, TypeError, ValueError) as exc:
        raise FileExistsError(
            f"Refusing to replace invalid labeling pack: {path}"
        ) from exc

    for pair in existing["pairs"]:
        annotation = pair["annotation"]
        if annotation["visual_similarity"] is not None:
            raise FileExistsError(
                f"Refusing to replace labeling pack with human annotations: {path}"
            )
        if annotation["confidence"] is not None:
            raise FileExistsError(
                f"Refusing to replace labeling pack with human annotations: {path}"
            )
        for field in ("annotator_id", "notes"):
            value = annotation[field]
            if value is not None and (not isinstance(value, str) or value.strip()):
                raise FileExistsError(
                    f"Refusing to replace labeling pack with human annotations: {path}"
                )
    return existing


def write_pack(
    path: Path,
    pack: dict[str, Any],
    *,
    replace_blank: bool = False,
) -> bool:
    """Write atomically, replacing a different pack only with explicit blank consent."""
    validate_labeling_pack(pack, require_blank=True)
    data = (
        json.dumps(pack, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    if path.exists():
        if path.read_bytes() == data:
            return False
        if not replace_blank:
            raise FileExistsError(
                f"Refusing to overwrite an existing labeling pack: {path}. "
                "Pass replace_blank only for a validated pack with no human annotations."
            )
        _load_replaceable_blank_pack(path)

    path.parent.mkdir(parents=True, exist_ok=True)
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
    return True
