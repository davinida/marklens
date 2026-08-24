#!/usr/bin/env python3
"""Run a bounded, reproducible image-perturbation robustness audit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_ROOT))

from evaluation.artifacts import load_artifact_generation  # noqa: E402
from evaluation.robustness import (  # noqa: E402
    evaluate_model_robustness,
    prepare_audit,
    write_json,
)
from src.preprocess import (  # noqa: E402
    GLOBAL_PREPROCESS_VERSION,
    LEGACY_PREPROCESS_VERSION,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", type=Path, default=Path("data/images"))
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("data/index/kipris_metadata.json"),
    )
    parser.add_argument("--index", type=Path, default=Path("data/index/kipris.faiss"))
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Generation manifest (defaults to <index-stem>_manifest.json)",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sample-size", type=int, default=25)
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument(
        "--preprocess-version",
        choices=(LEGACY_PREPROCESS_VERSION, GLOBAL_PREPROCESS_VERSION),
        default=None,
        help="Optional assertion; the manifest's version is always used",
    )
    parser.add_argument(
        "--with-model",
        action="store_true",
        help="Explicitly load OpenCLIP and compute retrieval metrics",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    generation = load_artifact_generation(
        index_path=args.index,
        metadata_path=args.metadata,
        manifest_path=args.manifest,
        image_dir=args.image_dir,
        requested_preprocess_version=args.preprocess_version,
        validate_runtime_packages=args.with_model,
    )
    keys = generation.keys
    report, generated = prepare_audit(
        generation.image_dir,
        keys,
        sample_size=args.sample_size,
        seed=args.seed,
    )
    report["image_dir"] = generation.metadata["image_dir"]
    report["source"] = generation.report_source()
    report["preprocess_version"] = generation.preprocess_version

    if args.with_model:
        # Heavy OpenCLIP import/model loading happens only behind this flag.
        from src.embedding import encode_image
        from src.scoring import score_results
        from src.search import load_index, search

        index = load_index(generation.index_path)
        if index.ntotal != len(keys):
            raise ValueError(
                f"Index/metadata count mismatch: {index.ntotal} != {len(keys)}"
            )
        preprocess_version = generation.preprocess_version
        report = evaluate_model_robustness(
            report,
            generated,
            keys=keys,
            image_dir=generation.image_dir,
            index=index,
            encoder=lambda image: encode_image(
                image,
                preprocess_version=preprocess_version,
            ),
            search_fn=search,
            score_fn=score_results,
        )
        report["model"] = dict(generation.manifest["model"])

    if args.output is not None:
        write_json(args.output, report)
        print(f"Wrote {report['mode']} report: {args.output}")
    else:
        import json

        print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 1 if report["decode_failure_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
