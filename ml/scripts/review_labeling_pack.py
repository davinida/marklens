#!/usr/bin/env python3
"""Run the loopback-only UI for human review of a MarkLens v2 labeling pack."""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Sequence

ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_ROOT))

from evaluation.review import (  # noqa: E402
    ReviewError,
    ReviewStore,
    default_receipt_path,
    expected_holdout_confirmation,
    load_review_pack,
    prepare_holdout_unlock,
)
from evaluation.review_server import (  # noqa: E402
    create_review_server,
    review_url,
    serve_review,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack",
        type=Path,
        default=Path("evaluation/labeling_pack_v2.json"),
        help="Validated v2 labeling pack (default: evaluation/labeling_pack_v2.json)",
    )
    parser.add_argument(
        "--image-dir",
        type=Path,
        default=Path("data/images"),
        help="Local image root (default: data/images)",
    )
    parser.add_argument(
        "--annotator-id",
        required=True,
        help="Stable human reviewer identifier written into each saved annotation",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Loopback port; use 0 to select a free port (default: 8765)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the local URL without opening the default browser",
    )
    holdout_group = parser.add_mutually_exclusive_group()
    holdout_group.add_argument(
        "--holdout",
        action="store_true",
        help="Resume a previously unlocked frozen holdout review",
    )
    holdout_group.add_argument(
        "--unlock-holdout",
        action="store_true",
        help=(
            "Irreversibly freeze development labels, create an unlock receipt, "
            "and open holdout after scoring and thresholds are fixed"
        ),
    )
    parser.add_argument(
        "--holdout-confirmation",
        help="Exact one-way confirmation required with --unlock-holdout",
    )
    return parser


def _open_browser_later(url: str) -> None:
    timer = threading.Timer(0.35, webbrowser.open, args=(url,), kwargs={"new": 2})
    timer.daemon = True
    timer.start()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        pack, _ = load_review_pack(args.pack)
        receipt_path = default_receipt_path(args.pack.resolve(strict=True))
        if args.holdout_confirmation is not None and not args.unlock_holdout:
            raise ReviewError("--holdout-confirmation is accepted only with --unlock-holdout")

        mode = "dev"
        if args.unlock_holdout:
            expected = expected_holdout_confirmation(pack["pack_id"])
            if args.holdout_confirmation is None:
                raise ReviewError(
                    "Holdout remains locked. Re-run only after development tuning is "
                    f'finished, with --holdout-confirmation "{expected}"'
                )
            created = prepare_holdout_unlock(
                args.pack,
                receipt_path,
                annotator_id=args.annotator_id,
                confirmation=args.holdout_confirmation,
            )
            action = "Created" if created else "Verified existing"
            print(
                f"{action} holdout receipt: {receipt_path}\n"
                "Development labels are now frozen. This does not make any label "
                "AI-generated or gold truth."
            )
            mode = "frozen_holdout"
        elif args.holdout:
            mode = "frozen_holdout"

        store = ReviewStore(
            pack_path=args.pack,
            image_dir=args.image_dir,
            annotator_id=args.annotator_id,
            mode=mode,
            receipt_path=receipt_path,
        )
        server = create_review_server(store, port=args.port)
    except (OSError, ReviewError) as exc:
        print(f"Cannot start local review: {exc}", file=sys.stderr)
        return 2

    url = review_url(server)
    split_label = "development" if mode == "dev" else "frozen holdout"
    print(
        f"Local human review ({split_label}): {url}\n"
        "Bound to 127.0.0.1 only. The UI hides model scores and source metadata.\n"
        "Labels are human annotations, not automatic labels, gold truth, or legal advice.\n"
        "Press Ctrl+C to stop."
    )
    if not args.no_browser:
        _open_browser_later(url)
    try:
        serve_review(server)
    except KeyboardInterrupt:
        print("\nLocal review stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
