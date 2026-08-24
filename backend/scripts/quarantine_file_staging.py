"""검증된 파일 스테이징에서 사용할 수 없는 레코드 한 건을 격리한다.

이 도구는 KIPRIS를 호출하지 않으며 운영 메타, 운영 이미지, 운영 인덱스를 변경하지
않는다. ``--plan``으로 변경 범위를 확인한 뒤 ``--apply``를 명시해야만 스테이징을
변경한다. 체크포인트의 ``collected`` 항목은 그대로 유지해 같은 원본을 재수집하지 않는다.
"""

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.scripts import collect_pipeline as collect  # noqa: E402
from backend.src.core.appno import (  # noqa: E402
    is_trademark_application_number,
    normalize_application_number,
)


@dataclass(frozen=True)
class QuarantinePlan:
    staging_path: Path
    checkpoint_path: Path
    application_number: str
    reason: str
    record: dict
    image_key: str
    image_sha256: str
    metadata_payload: dict
    authoritative_payload: dict
    metadata_sha256_before: str
    authoritative_sha256_before: str
    checkpoint_sha256_before: str
    quarantined_at: str
    operation_id: str
    record_count_before: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validated_application_number(raw: str) -> str:
    try:
        normalized = normalize_application_number(raw)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if not is_trademark_application_number(normalized):
        raise ValueError("--application-number 는 13자리 상표 출원번호여야 합니다.")
    return normalized


def _application_number_arg(raw: str) -> str:
    try:
        return _validated_application_number(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _validated_reason(raw: str) -> str:
    reason = raw.strip()
    if not reason:
        raise ValueError("--reason 은 비어 있을 수 없습니다.")
    if len(reason) > 500:
        raise ValueError("--reason 은 500자 이하여야 합니다.")
    return reason


def _validated_staging_path(path: Path) -> Path:
    try:
        return collect._file_staging_arg(str(path))  # noqa: SLF001
    except argparse.ArgumentTypeError as exc:
        raise ValueError(str(exc)) from exc


def quarantine_root(path: Path) -> Path:
    return path.with_name(path.stem + "_quarantine")


def _require_safe_companion(path: Path, *, label: str) -> Path:
    staging_root = (collect.paths.ML_DATA_DIR / "staging").resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label}가 없거나 심볼릭 링크입니다: {path.name}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(staging_root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise ValueError(f"{label} 경로가 스테이징 범위를 벗어납니다: {path}") from exc
    return resolved


def _load_json_object(path: Path, *, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"{label} JSON을 읽을 수 없습니다: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} JSON 최상위 값은 객체여야 합니다: {path.name}")
    return payload


def _checkpoint_contains(path: Path, application_number: str) -> None:
    if not path.is_file():
        raise ValueError(
            "스테이징 체크포인트가 없습니다. 재수집 방지를 보장할 수 없어 중단합니다."
        )
    payload = _load_json_object(path, label="스테이징 체크포인트")
    collected = payload.get("collected")
    if not isinstance(collected, list):
        raise ValueError("스테이징 체크포인트의 collected 배열이 유효하지 않습니다.")
    if application_number not in {str(value) for value in collected}:
        raise ValueError(
            f"출원번호 {application_number}가 체크포인트 collected에 없습니다. "
            "재수집 방지를 보장할 수 없어 중단합니다."
        )


def _safe_staging_image(path: Path, image_key: str) -> Path:
    image_root = collect.staging_image_dir(path)
    if image_root.is_symlink() or not image_root.is_dir():
        raise ValueError("스테이징 이미지 디렉터리가 없거나 심볼릭 링크입니다.")

    candidate = image_root.joinpath(*PurePosixPath(image_key).parts)
    cursor = candidate
    while cursor != image_root:
        if cursor.is_symlink():
            raise ValueError(f"스테이징 이미지 경로에 심볼릭 링크가 있습니다: {image_key}")
        cursor = cursor.parent
    try:
        resolved_root = image_root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise ValueError(f"스테이징 이미지 경로가 안전하지 않습니다: {image_key}") from exc
    if not resolved.is_file():
        raise ValueError(f"스테이징 이미지가 일반 파일이 아닙니다: {image_key}")
    return resolved


def _assert_quarantine_root_safe(path: Path) -> Path:
    root = quarantine_root(path)
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise ValueError(f"격리 경로가 안전한 디렉터리가 아닙니다: {root}")
    return root


def prepare_quarantine(
    staging_path: Path,
    application_number: str,
    reason: str,
) -> QuarantinePlan:
    staging_path = _validated_staging_path(staging_path)
    application_number = _validated_application_number(application_number)
    reason = _validated_reason(reason)

    if not staging_path.is_file():
        raise ValueError("격리할 스테이징 메타데이터가 없습니다.")
    authoritative_path = collect.staging_authoritative_path(staging_path)
    checkpoint_path = collect.staging_checkpoint_path(staging_path)
    _require_safe_companion(authoritative_path, label="authoritative manifest")
    _require_safe_companion(checkpoint_path, label="스테이징 체크포인트")
    image_root = collect.staging_image_dir(staging_path)
    if image_root.is_symlink() or not image_root.is_dir():
        raise ValueError("스테이징 이미지 디렉터리가 없거나 심볼릭 링크입니다.")

    staging_ok, staging_error = collect.inspect_file_staging(staging_path)
    if not staging_ok:
        raise ValueError(f"스테이징 무결성 검사 실패: {staging_error}")
    _assert_quarantine_root_safe(staging_path)

    _checkpoint_contains(checkpoint_path, application_number)

    metadata = collect._read_metadata_payload(staging_path)  # noqa: SLF001
    records = collect._records_by_application_number(metadata)  # noqa: SLF001
    record = records.get(application_number)
    if record is None:
        raise ValueError(f"스테이징에 출원번호 {application_number}가 없습니다.")

    image_keys = collect._validated_image_keys([record.get("이미지파일", "")])  # noqa: SLF001
    if len(image_keys) != 1:
        raise ValueError("격리 대상 레코드는 이미지 키를 정확히 하나 가져야 합니다.")
    image_key = image_keys[0]
    owners = [
        app_no
        for app_no, candidate in records.items()
        if image_key
        in collect._validated_image_keys([candidate.get("이미지파일", "")])  # noqa: SLF001
    ]
    if owners != [application_number]:
        raise ValueError(
            f"이미지 키 {image_key}를 여러 레코드가 공유해 자동 격리할 수 없습니다: {owners}"
        )

    image_path = _safe_staging_image(staging_path, image_key)
    image_sha256 = collect._sha256_file(image_path)  # noqa: SLF001
    authoritative = _load_json_object(authoritative_path, label="authoritative manifest")
    hashes = authoritative.get("image_hashes")
    if not isinstance(hashes, dict) or hashes.get(image_key) != image_sha256:
        raise ValueError(f"격리 대상 이미지 SHA-256이 manifest와 다릅니다: {image_key}")

    remaining_records = [
        records[key] for key in sorted(records) if key != application_number
    ]
    dataset_info = dict(metadata.get("dataset_info") or {})
    dataset_info["총_상표수"] = len(remaining_records)
    staging_info = dict(metadata.get("staging_info") or {})
    now = _utc_now()
    quarantined_at = now.isoformat()
    staging_info.update(
        {
            "schema_version": 1,
            "mode": "research-file-staging",
            "updated_at": quarantined_at,
            "record_count": len(remaining_records),
        }
    )
    metadata_after = {
        **metadata,
        "dataset_info": dataset_info,
        "trademarks": remaining_records,
        "staging_info": staging_info,
    }

    remaining_keys = [key for key in authoritative["image_keys"] if key != image_key]
    remaining_hashes = {
        key: value for key, value in hashes.items() if key != image_key
    }
    authoritative_after = {
        **authoritative,
        "image_keys": remaining_keys,
        "image_hashes": remaining_hashes,
    }
    authoritative_after.pop("metadata_sha256", None)

    return QuarantinePlan(
        staging_path=staging_path,
        checkpoint_path=checkpoint_path,
        application_number=application_number,
        reason=reason,
        record=record,
        image_key=image_key,
        image_sha256=image_sha256,
        metadata_payload=metadata_after,
        authoritative_payload=authoritative_after,
        metadata_sha256_before=collect._sha256_file(staging_path),  # noqa: SLF001
        authoritative_sha256_before=collect._sha256_file(authoritative_path),  # noqa: SLF001
        checkpoint_sha256_before=collect._sha256_file(checkpoint_path),  # noqa: SLF001
        quarantined_at=quarantined_at,
        operation_id=now.strftime("%Y%m%dT%H%M%S%fZ_") + application_number,
        record_count_before=len(records),
    )


def quarantine_summary(plan: QuarantinePlan) -> dict:
    return {
        "network_calls_executed": 0,
        "operating_files_changed": False,
        "staging": str(plan.staging_path),
        "application_number": plan.application_number,
        "image_key": plan.image_key,
        "image_sha256": plan.image_sha256,
        "reason": plan.reason,
        "record_count_before": plan.record_count_before,
        "record_count_after": plan.record_count_before - 1,
        "checkpoint_collected_preserved": True,
        "quarantine_directory": str(quarantine_root(plan.staging_path)),
    }


def _assert_plan_unchanged(plan: QuarantinePlan) -> None:
    _require_safe_companion(
        collect.staging_authoritative_path(plan.staging_path),
        label="authoritative manifest",
    )
    _require_safe_companion(
        plan.checkpoint_path,
        label="스테이징 체크포인트",
    )
    staging_ok, staging_error = collect.inspect_file_staging(plan.staging_path)
    if not staging_ok:
        raise ValueError(f"적용 직전 스테이징 무결성 검사 실패: {staging_error}")
    authoritative_path = collect.staging_authoritative_path(plan.staging_path)
    expected = (
        (plan.staging_path, plan.metadata_sha256_before, "스테이징 메타"),
        (authoritative_path, plan.authoritative_sha256_before, "authoritative manifest"),
        (plan.checkpoint_path, plan.checkpoint_sha256_before, "스테이징 체크포인트"),
    )
    for path, digest, label in expected:
        if not path.is_file() or collect._sha256_file(path) != digest:  # noqa: SLF001
            raise ValueError(f"계획 생성 후 {label}가 변경되어 격리를 중단합니다.")
    image = _safe_staging_image(plan.staging_path, plan.image_key)
    if collect._sha256_file(image) != plan.image_sha256:  # noqa: SLF001
        raise ValueError("계획 생성 후 격리 대상 이미지가 변경되어 중단합니다.")
    _checkpoint_contains(plan.checkpoint_path, plan.application_number)


def _create_dirty_marker(plan: QuarantinePlan) -> Path:
    dirty = collect.staging_dirty_path(plan.staging_path)
    dirty.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "operation": "file-staging-quarantine",
        "operation_id": plan.operation_id,
        "application_number": plan.application_number,
        "started_at": plan.quarantined_at,
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        descriptor = os.open(dirty, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"스테이징 dirty marker가 이미 존재합니다: {dirty.name}") from exc
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)
    return dirty


def _operation_manifest(plan: QuarantinePlan, *, state: str) -> dict:
    return {
        "schema_version": 1,
        "operation": "file-staging-quarantine",
        "state": state,
        "operation_id": plan.operation_id,
        "quarantined_at": plan.quarantined_at,
        "reason": plan.reason,
        "application_number": plan.application_number,
        "image_key": plan.image_key,
        "image_sha256": plan.image_sha256,
        "record": plan.record,
        "source": {
            "staging_file": plan.staging_path.name,
            "metadata_sha256_before": plan.metadata_sha256_before,
            "authoritative_sha256_before": plan.authoritative_sha256_before,
            "checkpoint_file": plan.checkpoint_path.name,
            "checkpoint_sha256_before": plan.checkpoint_sha256_before,
            "checkpoint_collected_preserved": True,
        },
        "post_state": {
            "record_count": plan.record_count_before - 1,
        },
    }


def _backup_inputs(plan: QuarantinePlan, operation_dir: Path) -> None:
    backup_dir = operation_dir / "before"
    backup_dir.mkdir(parents=True)
    sources = (
        (plan.staging_path, plan.metadata_sha256_before),
        (
            collect.staging_authoritative_path(plan.staging_path),
            plan.authoritative_sha256_before,
        ),
        (plan.checkpoint_path, plan.checkpoint_sha256_before),
    )
    for source, expected_hash in sources:
        destination = backup_dir / source.name
        shutil.copy2(source, destination)
        if collect._sha256_file(destination) != expected_hash:  # noqa: SLF001
            raise ValueError(f"격리 전 백업 SHA-256 검증 실패: {source.name}")


def _validate_post_state(plan: QuarantinePlan, quarantined_image: Path) -> None:
    authoritative_path = collect.staging_authoritative_path(plan.staging_path)
    authoritative = _load_json_object(authoritative_path, label="authoritative manifest")
    if authoritative.get("metadata_sha256") != collect._sha256_file(  # noqa: SLF001
        plan.staging_path
    ):
        raise ValueError("격리 후 메타 SHA-256과 authoritative manifest가 다릅니다.")
    if plan.image_key in authoritative.get("image_keys", []):
        raise ValueError("격리 후 authoritative key에 대상 이미지가 남아 있습니다.")
    if plan.image_key in authoritative.get("image_hashes", {}):
        raise ValueError("격리 후 authoritative hash에 대상 이미지가 남아 있습니다.")
    if collect.staging_image_path(plan.staging_path, plan.image_key).exists():
        raise ValueError("격리 후 원본 스테이징 이미지 경로에 파일이 남아 있습니다.")
    if (
        not quarantined_image.is_file()
        or collect._sha256_file(quarantined_image) != plan.image_sha256  # noqa: SLF001
    ):
        raise ValueError("격리된 이미지 SHA-256 검증에 실패했습니다.")
    if collect._sha256_file(plan.checkpoint_path) != plan.checkpoint_sha256_before:  # noqa: SLF001
        raise ValueError("격리 과정에서 스테이징 체크포인트가 변경되었습니다.")
    _checkpoint_contains(plan.checkpoint_path, plan.application_number)


def apply_quarantine(plan: QuarantinePlan) -> Path:
    """격리를 적용하고 완료된 감사 manifest 경로를 반환한다.

    dirty marker 뒤에만 파일을 변경한다. 실패하면 marker와 원본 백업을 유지해 다음
    수집·승격을 차단하며, 원본 이미지는 삭제하지 않고 격리 디렉터리에 보존한다.
    """
    _assert_plan_unchanged(plan)
    root = _assert_quarantine_root_safe(plan.staging_path)
    operation_dir = root / plan.operation_id
    if operation_dir.exists():
        raise ValueError(f"같은 격리 작업 디렉터리가 이미 존재합니다: {operation_dir}")

    dirty = _create_dirty_marker(plan)
    manifest_path = operation_dir / "quarantine.json"
    quarantined_image = operation_dir / "image" / plan.image_key
    try:
        # dirty 생성 뒤에도 입력 해시를 다시 확인해 계획/적용 사이 경합을 차단한다.
        _require_safe_companion(
            collect.staging_authoritative_path(plan.staging_path),
            label="authoritative manifest",
        )
        _require_safe_companion(
            plan.checkpoint_path,
            label="스테이징 체크포인트",
        )
        for path, digest in (
            (plan.staging_path, plan.metadata_sha256_before),
            (
                collect.staging_authoritative_path(plan.staging_path),
                plan.authoritative_sha256_before,
            ),
            (plan.checkpoint_path, plan.checkpoint_sha256_before),
        ):
            if collect._sha256_file(path) != digest:  # noqa: SLF001
                raise ValueError("dirty marker 생성 직전 입력이 변경되어 중단합니다.")

        operation_dir.mkdir(parents=True)
        collect._atomic_write_json(  # noqa: SLF001
            manifest_path,
            _operation_manifest(plan, state="in_progress"),
        )
        _backup_inputs(plan, operation_dir)

        source_image = _safe_staging_image(plan.staging_path, plan.image_key)
        quarantined_image.parent.mkdir(parents=True)
        os.replace(source_image, quarantined_image)
        if collect._sha256_file(quarantined_image) != plan.image_sha256:  # noqa: SLF001
            raise ValueError("이동된 격리 이미지 SHA-256이 원본과 다릅니다.")

        collect._atomic_write_json(plan.staging_path, plan.metadata_payload)  # noqa: SLF001
        authoritative_after = dict(plan.authoritative_payload)
        authoritative_after["metadata_sha256"] = collect._sha256_file(  # noqa: SLF001
            plan.staging_path
        )
        collect._atomic_write_json(  # noqa: SLF001
            collect.staging_authoritative_path(plan.staging_path),
            authoritative_after,
        )
        _validate_post_state(plan, quarantined_image)

        completed = _operation_manifest(plan, state="complete")
        completed["post_state"].update(
            {
                "metadata_sha256": collect._sha256_file(plan.staging_path),  # noqa: SLF001
                "authoritative_sha256": collect._sha256_file(  # noqa: SLF001
                    collect.staging_authoritative_path(plan.staging_path)
                ),
            }
        )
        collect._atomic_write_json(manifest_path, completed)  # noqa: SLF001
        dirty.unlink()

        staging_ok, staging_error = collect.inspect_file_staging(plan.staging_path)
        if not staging_ok:
            collect.mark_index_dirty(dirty)
            raise ValueError(f"격리 후 최종 무결성 검사 실패: {staging_error}")
        return manifest_path
    except Exception as exc:
        if operation_dir.exists():
            try:
                failed = _operation_manifest(plan, state="failed")
                failed["error"] = f"{type(exc).__name__}: {exc}"
                collect._atomic_write_json(manifest_path, failed)  # noqa: SLF001
            except Exception:
                pass
        # dirty marker는 의도적으로 유지한다. 백업 또는 격리 이미지 확인 뒤에만 복구한다.
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="파일 스테이징의 레코드/이미지 한 건을 감사 가능한 위치로 격리"
    )
    parser.add_argument(
        "--staging",
        type=collect._file_staging_arg,  # noqa: SLF001
        required=True,
        help="ml/data/staging 아래 스테이징 JSON",
    )
    parser.add_argument(
        "--application-number",
        type=_application_number_arg,
        required=True,
        help="격리할 13자리 상표 출원번호",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="격리 사유(감사 manifest에 기록)",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="검증과 변경 범위 출력만 수행")
    mode.add_argument("--apply", action="store_true", help="백업 후 스테이징 격리를 적용")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        plan = prepare_quarantine(
            args.staging,
            args.application_number,
            args.reason,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[오류] 격리 사전검증 실패: {exc}", file=sys.stderr)
        return 1

    print("[격리 계획] " + json.dumps(quarantine_summary(plan), ensure_ascii=False))
    if args.plan:
        return 0
    try:
        manifest_path = apply_quarantine(plan)
    except (OSError, ValueError, RuntimeError) as exc:
        print(
            f"[오류] 격리 적용 중단: {exc}\n"
            f"       dirty marker와 격리 백업을 확인하세요: "
            f"{collect.staging_dirty_path(plan.staging_path)}",
            file=sys.stderr,
        )
        return 2
    print(f"[완료] 스테이징 격리 manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
