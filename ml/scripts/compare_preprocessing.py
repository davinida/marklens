#!/usr/bin/env python3
"""Compare legacy and global MarkLens preprocessing on one verified image set."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image

ML_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ML_ROOT.parent
sys.path.insert(0, str(ML_ROOT))

from evaluation.artifacts import load_artifact_generation  # noqa: E402
from evaluation.preprocess_comparison import (  # noqa: E402
    GLOBAL_PREPROCESS_VERSION,
    LEGACY_PREPROCESS_VERSION,
    TRANSFORM_NAMES,
    assess_labeling_readiness,
    compare_preprocessing,
)
from evaluation.robustness import write_json  # noqa: E402


class OpenClipBatchEncoder:
    """Batch OpenCLIP inference while preserving encode_image aggregation semantics."""

    def __init__(self, *, batch_size: int):
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.batch_size = batch_size
        self.device: str | None = None
        self.stats: dict[str, dict[str, float | int]] = {}

    def _record_device(self, device: object) -> str:
        resolved = str(device)
        if not resolved:
            raise ValueError("Inference device must not be empty")
        if self.device is not None and self.device != resolved:
            raise RuntimeError(
                f"Inference device changed during evaluation: {self.device} -> {resolved}"
            )
        self.device = resolved
        return resolved

    def __call__(self, images: Sequence[Image.Image], version: str) -> np.ndarray:
        import torch
        from src import embedding
        from src.contracts import EMBEDDING_DIM
        from src.preprocess import prepare_model_views

        started = time.perf_counter()
        device = self._record_device(embedding.DEVICE)
        model, model_preprocess = embedding._load_model()
        sums = np.zeros((len(images), EMBEDDING_DIM), dtype=np.float32)
        view_counts = np.zeros(len(images), dtype=np.int32)
        pending_tensors = []
        pending_owners: list[int] = []
        total_views = 0

        def flush() -> None:
            if not pending_tensors:
                return
            tensor = torch.stack(pending_tensors).to(device)
            with torch.inference_mode():
                vectors = model.encode_image(tensor)
                if vectors.ndim != 2 or vectors.shape[1] != EMBEDDING_DIM:
                    raise ValueError(
                        f"Model returned unexpected batch shape: {tuple(vectors.shape)}"
                    )
                if not torch.isfinite(vectors).all():
                    raise ValueError("Model produced non-finite embeddings")
                vectors = vectors.float()
                norms = vectors.norm(dim=-1, keepdim=True)
                if torch.any(norms <= 0):
                    raise ValueError("Model produced zero-norm embeddings")
                normalized = (vectors / norms).cpu().numpy().astype(np.float32)
            for row, owner in zip(normalized, pending_owners):
                sums[owner] += row
                view_counts[owner] += 1
            pending_tensors.clear()
            pending_owners.clear()

        for owner, image in enumerate(images):
            views = prepare_model_views(image, preprocess_version=version)
            try:
                for view in views:
                    pending_tensors.append(model_preprocess(view))
                    pending_owners.append(owner)
                    total_views += 1
                    if len(pending_tensors) >= self.batch_size:
                        flush()
            finally:
                for view in views:
                    view.close()
        flush()

        if np.any(view_counts <= 0):
            raise ValueError("At least one image produced no model view")
        result = sums / view_counts[:, None]
        aggregate_norms = np.linalg.norm(result, axis=1, keepdims=True)
        if not np.all(np.isfinite(aggregate_norms)) or np.any(aggregate_norms <= 0):
            raise ValueError("View aggregation produced invalid embeddings")
        result = (result / aggregate_norms).astype(np.float32)

        stats = self.stats.setdefault(
            version,
            {"calls": 0, "images": 0, "views": 0, "seconds": 0.0},
        )
        stats["calls"] = int(stats["calls"]) + 1
        stats["images"] = int(stats["images"]) + len(images)
        stats["views"] = int(stats["views"]) + total_views
        stats["seconds"] = float(stats["seconds"]) + (time.perf_counter() - started)
        print(
            f"encoded version={version} images={len(images)} views={total_views}",
            flush=True,
        )
        return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", type=Path, default=ML_ROOT / "data" / "images")
    parser.add_argument(
        "--metadata",
        type=Path,
        default=ML_ROOT / "data" / "index" / "kipris_metadata.json",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=ML_ROOT / "data" / "index" / "kipris.faiss",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ML_ROOT / "data" / "index" / "kipris_manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ML_ROOT / "evaluation" / "preprocess_comparison_full_v1.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=ML_ROOT / "evaluation" / "preprocess_comparison_full_v1.md",
    )
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--bootstrap-seed", type=int, default=20260814)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument(
        "--labeling-pack",
        type=Path,
        default=ML_ROOT / "evaluation" / "labeling_pack_v2.json",
    )
    parser.add_argument(
        "--with-model",
        action="store_true",
        help="Required acknowledgement that this command loads OpenCLIP",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace only the explicitly selected comparison output files",
    )
    return parser


def _format_pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def _format_float(value: float) -> str:
    return f"{value:.6f}"


def _decision(report: dict) -> dict[str, str | bool]:
    delta = report["paired_deltas_global_minus_legacy"]["all_perturbations"]
    bootstrap = report["paired_bootstrap_by_source_image"]["metrics"]
    family_no_loss = delta["family_recall_at_1"] >= 0 and delta["family_recall_at_5"] >= 0
    exact_no_loss = delta["exact_recall_at_1"] >= 0 and delta["exact_recall_at_5"] >= 0
    margin_ci = bootstrap["target_to_nonfamily_margin"]["ci95"]
    margin_supported = margin_ci[0] >= 0
    passed = family_no_loss and exact_no_loss and margin_supported
    label_gate_open = report["labeling_readiness"]["fine_tuning_data_gate_open"]
    return {
        "paired_internal_gate_passed": passed,
        "preprocess_recommendation": (
            "global_candidate_requires_external_labeled_validation"
            if passed
            else "retain_legacy_pending_better_evidence"
        ),
        "fine_tuning_recommendation": (
            "not_justified_by_this_benchmark"
            if label_gate_open
            else "prohibited_label_data_not_ready"
        ),
        "fine_tuning_execution_allowed": False,
        "reason": (
            "This closed-world paired audit can compare preprocessing robustness but "
            "cannot establish generalization, legal similarity, calibration, or a need "
            "for OpenCLIP weight updates."
        ),
    }


def _render_markdown(report: dict) -> str:
    legacy = report["modes"][LEGACY_PREPROCESS_VERSION]["summary"]
    global_ = report["modes"][GLOBAL_PREPROCESS_VERSION]["summary"]
    decision = report["decision"]
    readiness = report["labeling_readiness"]
    source_count = int(report["source_image_count"])
    source_mode_counts = report["source_mode_counts"]
    if source_mode_counts == {"RGB": source_count}:
        dual_background_note = (
            f"- 현재 {source_count}개 원본은 모두 RGB이므로 global 후보의 "
            "dual-background 분기는 이번 평가에서 실행되지 않았습니다."
        )
    else:
        dual_background_note = (
            f"- 현재 {source_count}개 원본 mode 분포는 `{source_mode_counts}`입니다. "
            "dual-background 실행 여부는 각 원본의 투명 alpha 포함 여부에 좌우됩니다."
        )
    lines = [
        "# MarkLens 전처리 비교 평가 v1",
        "",
        f"생성 시각: `{report['created_at']}`",
        "",
        "## 결론",
        "",
        (
            "- 내부 paired gate: **통과**"
            if decision["paired_internal_gate_passed"]
            else "- 내부 paired gate: **미통과**"
        ),
        f"- 전처리 결정: `{decision['preprocess_recommendation']}`",
        f"- OpenCLIP fine-tuning: `{decision['fine_tuning_recommendation']}`",
        "- 이 평가는 전처리 비교 근거이며 모델 가중치 학습 필요성의 근거가 아닙니다.",
        "",
        "## 평가 범위",
        "",
        f"- 검증된 현재 이미지: {report['source_image_count']}개",
        f"- 모드별 질의: {report['query_count_per_mode']}개 "
        f"(원본 {report['source_image_count']} + 변형 "
        f"{report['perturbation_query_count_per_mode']})",
        f"- 변형: {', '.join(TRANSFORM_NAMES)}",
        "- 갤러리: 각 전처리로 원본을 메모리에서 다시 임베딩; 운영 FAISS 인덱스 미사용",
        f"- 원본 모드: `{report['source_mode_counts']}`",
        f"- 종횡비: `{report['aspect_bucket_counts']}`",
        "",
        "## 변형별 결과",
        "",
        "| 변형 | 전처리 | exact R@1 | family R@1 | family R@5 | "
        "target cosine | non-family margin |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for transform_name in ("original", *TRANSFORM_NAMES):
        for label, summary in (("legacy", legacy), ("global", global_)):
            metrics = summary["by_transform"][transform_name]
            lines.append(
                "| "
                + " | ".join(
                    [
                        transform_name,
                        label,
                        _format_pct(metrics["exact_recall_at_1"]),
                        _format_pct(metrics["family_recall_at_1"]),
                        _format_pct(metrics["family_recall_at_5"]),
                        _format_float(metrics["target_similarity_mean"]),
                        _format_float(metrics["target_to_nonfamily_margin_mean"]),
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## 종횡비 Slice",
            "",
            "| Slice | N queries/mode | legacy family R@1 | global family R@1 | "
            "legacy margin | global margin |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for bucket in sorted(legacy["by_aspect_bucket"]):
        left = legacy["by_aspect_bucket"][bucket]
        right = global_["by_aspect_bucket"][bucket]
        lines.append(
            f"| {bucket} | {left['count']} | {_format_pct(left['family_recall_at_1'])} | "
            f"{_format_pct(right['family_recall_at_1'])} | "
            f"{_format_float(left['target_to_nonfamily_margin_mean'])} | "
            f"{_format_float(right['target_to_nonfamily_margin_mean'])} |"
        )

    lines.extend(
        [
            "",
            "## Paired Bootstrap",
            "",
            f"{source_count}개 원본 이미지를 재표집 단위로 사용하고, 이미지별 네 변형 평균의 "
            "`global - legacy` 차이에 대해 결정적 bootstrap을 수행했습니다.",
            "",
            "| 지표 | 평균 차이 | 95% CI | 이미지 win/tie/loss |",
            "|---|---:|---:|---:|",
        ]
    )
    for metric, values in report["paired_bootstrap_by_source_image"]["metrics"].items():
        lines.append(
            f"| {metric} | {_format_float(values['observed_mean_delta'])} | "
            f"[{_format_float(values['ci95'][0])}, {_format_float(values['ci95'][1])}] | "
            f"{values['image_win_count']}/{values['image_tie_count']}/"
            f"{values['image_loss_count']} |"
        )

    lines.extend(
        [
            "",
            "## 학습 데이터 Readiness Gate",
            "",
            f"- 상태: **{readiness['status']}**",
            f"- pack: `{readiness.get('pack_id')}`",
            f"- 라벨 완료: {readiness.get('total_labeled_pair_count', 0)}/200",
            "- fine-tuning data gate: "
            f"`{readiness['fine_tuning_data_gate_open']}`",
            "- holdout의 학습 사용: `false`",
            f"- 미통과 사유: `{readiness['reasons']}`",
            "",
            "| Split | 라벨 | missing confidence | missing annotator | "
            "cannot_assess | class floor |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for split, values in readiness.get("splits", {}).items():
        cannot_rate = values["cannot_assess_rate"]
        lines.append(
            f"| {split} | {values['labeled_pair_count']}/{values['expected_pair_count']} | "
            f"{values['missing_confidence_count']} | "
            f"{values['missing_annotator_id_count']} | "
            f"{'n/a' if cannot_rate is None else _format_pct(cannot_rate)} | "
            f"{values['trainable_class_coverage_met']} |"
        )

    lines.extend(
        [
            "",
            "## 해석 제한",
            "",
            f"- 동일 {source_count}개 원본이 갤러리와 질의의 정답인 "
            "closed-world self-retrieval입니다.",
            "- 변형은 합성 회전·crop·여백·JPEG이며 실제 촬영·화면 캡처 표본이 아닙니다.",
            "- family 정답은 원본 파일 SHA-256이 같은 출원들만 묶습니다. 사람이 판단한 "
            "near-duplicate나 법적 유사 범위가 아닙니다.",
            dual_background_note,
            f"- 데이터는 특정 출원인·등록표장 중심 {source_count}건이며 독립 holdout이나 전체 상표 "
            "모집단을 대표하지 않습니다.",
            "- 전처리를 바꾸면 갤러리와 질의를 함께 재임베딩하고 임계값을 다시 검증해야 합니다.",
            "- fine-tuning은 사람이 라벨한 development/동결 holdout과 외부 실제 입력에서 "
            "사전학습 모델의 실패가 재현된 뒤에만 검토합니다.",
            "",
            "## 재현 명령",
            "",
            "```powershell",
            ".\\ml\\venv\\Scripts\\python.exe ml\\scripts\\compare_preprocessing.py --with-model",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.with_model:
        raise SystemExit("Refusing heavy evaluation without explicit --with-model")
    for path in (args.output, args.markdown_output):
        if path.exists() and not args.replace:
            raise SystemExit(f"Refusing to overwrite existing report without --replace: {path}")

    generation = load_artifact_generation(
        index_path=args.index,
        metadata_path=args.metadata,
        manifest_path=args.manifest,
        image_dir=args.image_dir,
        validate_runtime_packages=True,
    )
    encoder = OpenClipBatchEncoder(batch_size=args.batch_size)
    try:
        labeling_pack = json.loads(args.labeling_pack.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot load labeling pack: {exc}") from exc
    if not isinstance(labeling_pack, dict):
        raise SystemExit("Labeling pack must be a JSON object")
    report = compare_preprocessing(
        keys=generation.keys,
        image_dir=generation.image_dir,
        image_hashes=generation.image_hashes,
        encoder=encoder,
        bootstrap_seed=args.bootstrap_seed,
        bootstrap_samples=args.bootstrap_samples,
    )
    report["created_at"] = datetime.now(timezone.utc).isoformat()
    report["source"] = generation.report_source()
    report["model"] = dict(generation.manifest["model"])
    report["runtime"] = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "Pillow": importlib.metadata.version("Pillow"),
        "torch": importlib.metadata.version("torch"),
        "open_clip_torch": importlib.metadata.version("open_clip_torch"),
    }
    report["inference"] = {
        "batch_size": args.batch_size,
        "device": encoder.device,
        "per_preprocess": encoder.stats,
    }
    report["labeling_readiness"] = assess_labeling_readiness(labeling_pack)
    resolved_pack = args.labeling_pack.resolve()
    try:
        source_path = resolved_pack.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        source_path = resolved_pack.name
    report["labeling_readiness"]["source_path"] = source_path
    report["labeling_readiness"]["source_sha256"] = hashlib.sha256(
        resolved_pack.read_bytes()
    ).hexdigest()
    report["decision"] = _decision(report)
    write_json(args.output, report)
    _write_text(args.markdown_output, _render_markdown(report))
    print(f"Wrote JSON report: {args.output}")
    print(f"Wrote Markdown report: {args.markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
