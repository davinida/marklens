#!/usr/bin/env python3
"""Generate a deterministic 200-pair, visual-only human-labeling pack."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_ROOT))

from evaluation.artifacts import load_artifact_generation  # noqa: E402
from evaluation.labeling import build_labeling_pack, write_pack  # noqa: E402


def _load_embeddings(index_path: Path, expected_count: int) -> np.ndarray:
    # Keep FAISS outside module import so --help and static inspection stay light.
    from src.search import load_index

    index = load_index(index_path)
    if index.ntotal != expected_count:
        raise ValueError(
            f"Index/metadata count mismatch: {index.ntotal} != {expected_count}"
        )
    return np.asarray(index.reconstruct_n(0, index.ntotal), dtype=np.float32)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image-dir",
        type=Path,
        default=Path("data/images"),
        help="Image root used to lock the displayed image contents",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("data/index/kipris_metadata.json"),
        help="Index metadata containing image_paths/image_keys",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("data/index/kipris.faiss"),
        help="FAISS index from the same published generation",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Generation manifest (defaults to <index-stem>_manifest.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation/labeling_pack_v2.json"),
    )
    parser.add_argument(
        "--replace-blank",
        action="store_true",
        help=(
            "Replace a different existing v2 pack only after strict validation "
            "confirms that it contains no human annotations"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    generation = load_artifact_generation(
        index_path=args.index,
        metadata_path=args.metadata,
        manifest_path=args.manifest,
        image_dir=args.image_dir,
    )
    embeddings = _load_embeddings(generation.index_path, len(generation.keys))
    pack = build_labeling_pack(
        generation.keys,
        embeddings=embeddings,
        image_hashes=generation.image_hashes,
        source=generation.report_source(),
    )
    created = write_pack(args.output, pack, replace_blank=args.replace_blank)
    action = "Wrote" if created else "Already identical"
    print(
        f"{action}: {args.output} ({pack['split_counts']['dev']} dev, "
        f"{pack['split_counts']['frozen_holdout']} frozen holdout)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
