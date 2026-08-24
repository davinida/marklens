"""Local-only human review state and persistence for visual labeling packs."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Literal

from evaluation.labeling import (
    CONFIDENCE_LABELS,
    DEV_COUNT,
    SUPPORTED_EXTENSIONS,
    VISUAL_LABELS,
    validate_labeling_pack,
)

REVIEW_PROTOCOL = "marklens-local-human-review-v1"
HOLDOUT_UNLOCK_PROTOCOL = "marklens-frozen-holdout-unlock-v1"
MAX_ANNOTATOR_ID_LENGTH = 80
MAX_NOTES_LENGTH = 2_000
MAX_IMAGE_BYTES = 20 * 1024 * 1024
PACK_LOCK_TIMEOUT_SECONDS = 10.0
PACK_MODES = ("dev", "frozen_holdout")


class ReviewError(Exception):
    """Base error for the local labeling workflow."""


class ReviewValidationError(ReviewError):
    """The pack, annotation, or request violates the review contract."""


class ReviewAccessError(ReviewError):
    """The requested split or annotation is locked by policy."""


class ReviewConflictError(ReviewError):
    """The pack changed after the browser loaded its current revision."""


def _json_object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReviewValidationError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _load_json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReviewValidationError(f"Cannot read {label}: {path}") from exc
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_json_object_without_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ReviewValidationError) as exc:
        raise ReviewValidationError(f"{label} is not valid duplicate-free UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ReviewValidationError(f"{label} must be a JSON object")
    return value, data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
    """Durably replace one file without exposing a partially written JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = None
    if path.exists():
        existing_mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if existing_mode is not None:
            os.chmod(temporary, existing_mode)
        os.replace(temporary, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _pack_lock_path(pack_path: Path) -> Path:
    return pack_path.with_name(f".{pack_path.name}.review.lock.tmp")


def _acquire_file_lock(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_file_lock(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _exclusive_pack_lock(pack_path: Path) -> Iterator[None]:
    """Serialize pack and receipt mutations across local review processes."""
    lock_path = _pack_lock_path(pack_path)
    try:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise ReviewConflictError("Cannot open the local pack lock") from exc

    with os.fdopen(descriptor, "r+b", buffering=0) as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + PACK_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                _acquire_file_lock(handle)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise ReviewConflictError(
                        "Another local review process is busy; retry the save"
                    ) from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            _release_file_lock(handle)


def validate_annotator_id(value: str) -> str:
    if not isinstance(value, str):
        raise ReviewValidationError("annotator_id must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_ANNOTATOR_ID_LENGTH:
        raise ReviewValidationError(
            f"annotator_id must contain 1-{MAX_ANNOTATOR_ID_LENGTH} characters"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ReviewValidationError("annotator_id must not contain control characters")
    return normalized


def _normalized_notes(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReviewValidationError("notes must be a string or null")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > MAX_NOTES_LENGTH:
        raise ReviewValidationError(f"notes must not exceed {MAX_NOTES_LENGTH} characters")
    return normalized or None


def annotation_is_complete(annotation: dict[str, Any]) -> bool:
    return (
        annotation.get("visual_similarity") in VISUAL_LABELS
        and annotation.get("confidence") in CONFIDENCE_LABELS
        and isinstance(annotation.get("annotator_id"), str)
        and bool(annotation["annotator_id"].strip())
    )


def validate_review_annotations(pack: dict[str, Any]) -> None:
    """Apply stricter workflow rules than the permissive artifact JSON schema."""
    for pair in pack["pairs"]:
        pair_id = pair["pair_id"]
        annotation = pair["annotation"]
        label = annotation["visual_similarity"]
        confidence = annotation["confidence"]
        annotator_id = annotation["annotator_id"]
        notes = annotation["notes"]
        if label is None and confidence is None:
            if annotator_id is not None or notes is not None:
                raise ReviewValidationError(
                    f"Blank annotation must not retain author or notes: {pair_id}"
                )
            continue
        if label not in VISUAL_LABELS or confidence not in CONFIDENCE_LABELS:
            raise ReviewValidationError(
                f"Annotation must contain both a valid label and confidence: {pair_id}"
            )
        normalized_annotator = validate_annotator_id(annotator_id)
        if normalized_annotator != annotator_id:
            raise ReviewValidationError(f"annotator_id is not normalized: {pair_id}")
        if _normalized_notes(notes) != notes:
            raise ReviewValidationError(f"notes are not normalized: {pair_id}")


def load_review_pack(path: Path) -> tuple[dict[str, Any], bytes]:
    pack, data = _load_json_object(path, "labeling pack")
    try:
        validate_labeling_pack(pack, require_blank=False)
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewValidationError("Labeling pack failed the v2 artifact contract") from exc
    validate_review_annotations(pack)
    return pack, data


def resolve_image_path(
    image_dir: Path,
    image_key: str,
    *,
    require_exists: bool,
) -> Path:
    """Resolve one portable image key while rejecting traversal and symlink escape."""
    if not isinstance(image_key, str) or not image_key or image_key != image_key.strip():
        raise ReviewValidationError("Invalid image key")
    normalized = image_key.replace("\\", "/")
    portable = PurePosixPath(normalized)
    if (
        portable.is_absolute()
        or normalized.startswith("//")
        or any(part in ("", ".", "..") for part in portable.parts)
        or (portable.parts and ":" in portable.parts[0])
        or portable.suffix.lower() not in SUPPORTED_EXTENSIONS
        or any(ord(character) < 32 for character in normalized)
    ):
        raise ReviewValidationError(f"Unsafe or unsupported image key: {image_key!r}")

    try:
        root = image_dir.resolve(strict=True)
    except OSError as exc:
        raise ReviewValidationError(f"Image directory is unavailable: {image_dir}") from exc
    if not root.is_dir():
        raise ReviewValidationError(f"Image root is not a directory: {root}")
    try:
        candidate = root.joinpath(*portable.parts).resolve(strict=require_exists)
        candidate.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ReviewValidationError(f"Image key escapes or is missing: {image_key!r}") from exc
    if require_exists and not candidate.is_file():
        raise ReviewValidationError(f"Image is not a regular file: {image_key!r}")
    return candidate


def dev_annotation_sha256(pack: dict[str, Any]) -> str:
    records = [
        {"pair_id": pair["pair_id"], "annotation": pair["annotation"]}
        for pair in pack["pairs"]
        if pair["split"] == "dev"
    ]
    records.sort(key=lambda record: record["pair_id"])
    canonical = json.dumps(
        records, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return _sha256(canonical)


def expected_holdout_confirmation(pack_id: str) -> str:
    return f"UNLOCK_FROZEN_HOLDOUT:{pack_id}"


def default_receipt_path(pack_path: Path) -> Path:
    return pack_path.with_name(f"{pack_path.stem}.holdout_unlock.json")


def _load_unlock_receipt(path: Path, pack: dict[str, Any]) -> dict[str, Any]:
    receipt, _ = _load_json_object(path, "holdout unlock receipt")
    expected_keys = {
        "protocol",
        "pack_id",
        "dev_annotation_sha256",
        "dev_labeled_count",
        "unlocked_at",
        "unlocked_by",
        "acknowledgement",
    }
    if set(receipt) != expected_keys:
        raise ReviewValidationError("Holdout unlock receipt has unexpected fields")
    if receipt["protocol"] != HOLDOUT_UNLOCK_PROTOCOL:
        raise ReviewValidationError("Holdout unlock receipt protocol mismatch")
    if receipt["pack_id"] != pack["pack_id"]:
        raise ReviewValidationError("Holdout unlock receipt belongs to another pack")
    if receipt["dev_labeled_count"] != DEV_COUNT:
        raise ReviewValidationError("Holdout receipt does not record a complete dev set")
    if receipt["dev_annotation_sha256"] != dev_annotation_sha256(pack):
        raise ReviewAccessError("Development labels changed after holdout unlock")
    if receipt["acknowledgement"] != "scoring_and_thresholds_fixed_before_holdout":
        raise ReviewValidationError("Holdout acknowledgement mismatch")
    validate_annotator_id(receipt["unlocked_by"])
    try:
        datetime.fromisoformat(receipt["unlocked_at"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ReviewValidationError("Holdout unlock timestamp is invalid") from exc
    return receipt


def prepare_holdout_unlock(
    pack_path: Path,
    receipt_path: Path,
    *,
    annotator_id: str,
    confirmation: str,
) -> bool:
    """Create the one-way holdout receipt after all development labels are complete."""
    annotator_id = validate_annotator_id(annotator_id)
    try:
        resolved_pack_path = pack_path.resolve(strict=True)
        resolved_receipt_path = receipt_path.resolve(strict=False)
    except OSError as exc:
        raise ReviewValidationError("Cannot resolve pack or receipt path") from exc
    if resolved_receipt_path == resolved_pack_path:
        raise ReviewValidationError("Unlock receipt must not overwrite the labeling pack")
    canonical_receipt_path = default_receipt_path(resolved_pack_path).resolve(strict=False)
    if resolved_receipt_path != canonical_receipt_path:
        raise ReviewValidationError(
            "Unlock receipt must use the canonical path next to the labeling pack"
        )
    pack_path = resolved_pack_path
    receipt_path = canonical_receipt_path
    with _exclusive_pack_lock(pack_path):
        pack, _ = load_review_pack(pack_path)
        if confirmation != expected_holdout_confirmation(pack["pack_id"]):
            raise ReviewAccessError("Holdout confirmation text does not match this pack")
        dev_pairs = [pair for pair in pack["pairs"] if pair["split"] == "dev"]
        if len(dev_pairs) != DEV_COUNT or not all(
            annotation_is_complete(pair["annotation"]) for pair in dev_pairs
        ):
            raise ReviewAccessError("All 160 development pairs must be labeled first")
        holdout_pairs = [pair for pair in pack["pairs"] if pair["split"] == "frozen_holdout"]
        if not receipt_path.exists() and any(
            annotation_is_complete(pair["annotation"]) for pair in holdout_pairs
        ):
            raise ReviewAccessError(
                "Holdout labels exist without an unlock receipt; refusing to reconstruct provenance"
            )
        if receipt_path.exists():
            _load_unlock_receipt(receipt_path, pack)
            return False

        receipt = {
            "protocol": HOLDOUT_UNLOCK_PROTOCOL,
            "pack_id": pack["pack_id"],
            "dev_annotation_sha256": dev_annotation_sha256(pack),
            "dev_labeled_count": DEV_COUNT,
            "unlocked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "unlocked_by": annotator_id,
            "acknowledgement": "scoring_and_thresholds_fixed_before_holdout",
        }
        _atomic_write(receipt_path, _json_bytes(receipt))
        return True


class ReviewStore:
    """Validated, resumable annotation store for exactly one visible split."""

    def __init__(
        self,
        *,
        pack_path: Path,
        image_dir: Path,
        annotator_id: str,
        mode: Literal["dev", "frozen_holdout"] = "dev",
        receipt_path: Path | None = None,
    ) -> None:
        if mode not in PACK_MODES:
            raise ReviewValidationError(f"Unsupported review mode: {mode!r}")
        try:
            self.pack_path = pack_path.resolve(strict=True)
            self.image_dir = image_dir.resolve(strict=True)
        except OSError as exc:
            raise ReviewValidationError("Pack or image directory is unavailable") from exc
        if not self.pack_path.is_file():
            raise ReviewValidationError(f"Labeling pack is not a file: {self.pack_path}")
        if not self.image_dir.is_dir():
            raise ReviewValidationError(f"Image root is not a directory: {self.image_dir}")
        self.annotator_id = validate_annotator_id(annotator_id)
        self.mode = mode
        canonical_receipt_path = default_receipt_path(self.pack_path).resolve(strict=False)
        if (
            receipt_path is not None
            and receipt_path.resolve(strict=False) != canonical_receipt_path
        ):
            raise ReviewValidationError(
                "Unlock receipt must use the canonical path next to the labeling pack"
            )
        self.receipt_path = canonical_receipt_path
        self._lock = threading.RLock()
        self._pack: dict[str, Any] = {}
        self._revision = ""
        self._pairs: dict[str, dict[str, Any]] = {}
        self._reload()

    def _validate_policy(self, pack: dict[str, Any]) -> None:
        if self.mode == "dev":
            if self.receipt_path.exists():
                _load_unlock_receipt(self.receipt_path, pack)
                raise ReviewAccessError(
                    "Frozen holdout was already unlocked; development labels are now locked"
                )
            return
        if not self.receipt_path.exists():
            raise ReviewAccessError("Frozen holdout is locked; create an unlock receipt first")
        _load_unlock_receipt(self.receipt_path, pack)

    def _validate_image_keys(self, pack: dict[str, Any]) -> None:
        seen: set[str] = set()
        for pair in pack["pairs"]:
            for side in ("left", "right"):
                key = pair[side]["image_key"]
                if key in seen:
                    continue
                resolve_image_path(self.image_dir, key, require_exists=False)
                seen.add(key)

    def _reload(self) -> None:
        pack, data = load_review_pack(self.pack_path)
        self._validate_policy(pack)
        self._validate_image_keys(pack)
        self._install_pack(pack, data)

    def _install_pack(self, pack: dict[str, Any], data: bytes) -> None:
        pairs = {pair["pair_id"]: pair for pair in pack["pairs"] if pair["split"] == self.mode}
        if not pairs:
            raise ReviewValidationError(f"No pairs available for mode {self.mode}")
        self._pack = pack
        self._revision = _sha256(data)
        self._pairs = pairs

    def _refresh_if_changed(self) -> None:
        try:
            disk_data = self.pack_path.read_bytes()
        except OSError as exc:
            raise ReviewConflictError("Labeling pack is no longer readable") from exc
        if _sha256(disk_data) != self._revision:
            self._reload()

    def public_state(self) -> dict[str, Any]:
        with self._lock:
            self._refresh_if_changed()
            self._validate_policy(self._pack)
            pairs = []
            labeled = 0
            for index, pair in enumerate(self._pairs.values(), start=1):
                annotation = dict(pair["annotation"])
                complete = annotation_is_complete(annotation)
                if complete:
                    labeled += 1
                pairs.append(
                    {
                        "pair_id": pair["pair_id"],
                        "position": index,
                        "annotation": annotation,
                        "editable": (
                            not complete or annotation["annotator_id"] == self.annotator_id
                        ),
                        "left_url": f"/image/{pair['pair_id']}/left",
                        "right_url": f"/image/{pair['pair_id']}/right",
                    }
                )
            return {
                "protocol": REVIEW_PROTOCOL,
                "label_origin": "human_annotation_not_gold",
                "pack_id": self._pack["pack_id"],
                "mode": self.mode,
                "annotator_id": self.annotator_id,
                "revision": self._revision,
                "counts": {
                    "total": len(pairs),
                    "labeled": labeled,
                    "remaining": len(pairs) - labeled,
                },
                "pairs": pairs,
            }

    def save_annotation(
        self,
        *,
        pair_id: str,
        expected_revision: str,
        visual_similarity: str | None,
        confidence: str | None,
        notes: str | None,
        clear: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            if not isinstance(pair_id, str):
                raise ReviewValidationError("pair_id must be a string")
            if not isinstance(clear, bool):
                raise ReviewValidationError("clear must be a boolean")
            if not isinstance(expected_revision, str) or expected_revision != self._revision:
                raise ReviewConflictError("Browser revision is stale; reload before saving")
            with _exclusive_pack_lock(self.pack_path):
                pack, disk_data = load_review_pack(self.pack_path)
                if _sha256(disk_data) != self._revision:
                    raise ReviewConflictError("Labeling pack changed outside this review session")
                self._validate_policy(pack)
                self._validate_image_keys(pack)
                pairs = {
                    item["pair_id"]: item for item in pack["pairs"] if item["split"] == self.mode
                }
                pair = pairs.get(pair_id)
                if pair is None:
                    raise ReviewAccessError("Pair is not available in the active review split")
                existing = pair["annotation"]
                if (
                    annotation_is_complete(existing)
                    and existing["annotator_id"] != self.annotator_id
                ):
                    raise ReviewAccessError("Another annotator owns this saved annotation")

                if clear:
                    annotation = {
                        "visual_similarity": None,
                        "confidence": None,
                        "annotator_id": None,
                        "notes": None,
                    }
                else:
                    if visual_similarity not in VISUAL_LABELS:
                        raise ReviewValidationError("Unsupported visual similarity label")
                    if confidence not in CONFIDENCE_LABELS:
                        raise ReviewValidationError("Unsupported confidence label")
                    annotation = {
                        "visual_similarity": visual_similarity,
                        "confidence": confidence,
                        "annotator_id": self.annotator_id,
                        "notes": _normalized_notes(notes),
                    }

                pair["annotation"] = annotation
                validate_labeling_pack(pack, require_blank=False)
                validate_review_annotations(pack)
                if self.mode == "frozen_holdout":
                    _load_unlock_receipt(self.receipt_path, pack)

                updated = _json_bytes(pack)
                _atomic_write(self.pack_path, updated)
                self._install_pack(pack, updated)
                labeled = sum(
                    annotation_is_complete(item["annotation"]) for item in self._pairs.values()
                )
                counts = {
                    "total": len(self._pairs),
                    "labeled": labeled,
                    "remaining": len(self._pairs) - labeled,
                }
            return {
                "pair_id": pair_id,
                "annotation": dict(annotation),
                "revision": self._revision,
                "counts": counts,
            }

    def image_response(self, pair_id: str, side: str) -> tuple[Path, str, int]:
        with self._lock:
            self._refresh_if_changed()
            self._validate_policy(self._pack)
            pair = self._pairs.get(pair_id)
            if pair is None or side not in ("left", "right"):
                raise ReviewAccessError("Image is not available in the active review split")
            path = resolve_image_path(self.image_dir, pair[side]["image_key"], require_exists=True)
            size = path.stat().st_size
            if size <= 0 or size > MAX_IMAGE_BYTES:
                raise ReviewValidationError("Image size is outside the local review limit")
            content_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            return path, content_type, size
