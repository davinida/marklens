"""검증된 연구 파일 스테이징을 운영 파일 데이터셋으로 승격한다.

기본적으로 아무것도 쓰지 않는다. ``--plan``으로 충돌과 복사 범위를 확인한 뒤
``--apply``를 명시해야 운영 이미지, 메타데이터와 인덱스를 변경한다. DB 모드에서는
사용할 수 없다.
"""

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.scripts import collect_pipeline as collect  # noqa: E402
from backend.src.core import config, paths  # noqa: E402

PROMOTED_DATASET_BASIS = (
    "KIPRIS 등록 상태 도형·복합상표, 출원인 검색 기반 연구용 표본"
)


@dataclass(frozen=True)
class Promotion:
    staging_path: Path
    merged_payload: dict
    image_keys: list[str]
    image_hashes: dict[str, str]
    images_to_copy: tuple[str, ...]
    new_record_count: int
    unchanged_record_count: int


def _disk_image_keys(image_root: Path) -> set[str]:
    if not image_root.exists():
        return set()
    return {
        path.relative_to(image_root).as_posix()
        for path in image_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    }


def _application_year_range(records: list[dict]) -> str:
    years: list[int] = []
    invalid: list[str] = []
    for record in records:
        application_number = str(record.get("출원번호") or "<출원번호 없음>")
        raw_date = record.get("출원일자")
        if not isinstance(raw_date, str) or not raw_date:
            invalid.append(f"{application_number}=누락")
            continue
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError:
            invalid.append(f"{application_number}={raw_date!r}")
            continue
        if parsed.isoformat() != raw_date:
            invalid.append(f"{application_number}={raw_date!r}")
            continue
        years.append(parsed.year)

    if invalid:
        preview = ", ".join(invalid[:5])
        remainder = len(invalid) - 5
        suffix = f" 외 {remainder}건" if remainder > 0 else ""
        raise ValueError(
            "승격 대상의 출원일자는 YYYY-MM-DD 형식의 유효한 날짜여야 합니다: "
            f"{preview}{suffix}"
        )
    if not years:
        raise ValueError("승격 대상에 출원일자가 있는 상표 레코드가 없습니다.")
    return f"{min(years)} ~ {max(years)}"


def prepare_promotion(staging_path: Path) -> Promotion:
    staging_ok, staging_error = collect.inspect_file_staging(staging_path)
    if not staging_ok:
        raise ValueError(f"스테이징 무결성 실패: {staging_error}")
    if not staging_path.exists():
        raise ValueError("승격할 스테이징 메타데이터가 없습니다.")
    if not paths.TRADEMARK_META_PATH.exists():
        raise ValueError("운영 상표 메타데이터가 없습니다.")

    runtime_payload = collect._read_metadata_payload(paths.TRADEMARK_META_PATH)  # noqa: SLF001
    staging_payload = collect._read_metadata_payload(staging_path)  # noqa: SLF001
    runtime_records = collect._records_by_application_number(runtime_payload)  # noqa: SLF001
    staging_records = collect._records_by_application_number(staging_payload)  # noqa: SLF001
    manifest = json.loads(
        collect.staging_authoritative_path(staging_path).read_text(encoding="utf-8")
    )
    staging_hashes = manifest["image_hashes"]

    runtime_key_owner: dict[str, str] = {}
    for app_no, record in runtime_records.items():
        keys = collect._validated_image_keys([record.get("이미지파일", "")])  # noqa: SLF001
        key = keys[0]
        if key in runtime_key_owner:
            raise ValueError(f"운영 메타에 중복 이미지 키가 있습니다: {key}")
        runtime_key_owner[key] = app_no

    runtime_disk_keys = _disk_image_keys(paths.IMAGES_DIR)
    missing_runtime = sorted(set(runtime_key_owner) - runtime_disk_keys)
    if missing_runtime:
        raise ValueError(f"운영 메타 이미지가 누락되었습니다: {missing_runtime[:5]}")

    merged = dict(runtime_records)
    images_to_copy: list[str] = []
    new_count = 0
    unchanged_count = 0
    for app_no, record in staging_records.items():
        key = collect._validated_image_keys([record.get("이미지파일", "")])[0]  # noqa: SLF001
        owner = runtime_key_owner.get(key)
        if owner is not None and owner != app_no:
            raise ValueError(f"이미지 키 {key}가 운영 출원번호 {owner}에 이미 연결되어 있습니다.")

        previous = runtime_records.get(app_no)
        if previous is not None:
            if collect._canonical_record(previous) != collect._canonical_record(record):  # noqa: SLF001
                raise ValueError(f"출원번호 {app_no}의 운영 메타와 스테이징 내용이 다릅니다.")
            unchanged_count += 1
        else:
            merged[app_no] = record
            runtime_key_owner[key] = app_no
            new_count += 1

        destination = paths.IMAGES_DIR / key
        if destination.exists():
            destination_hash = (
                collect._sha256_file(destination)  # noqa: SLF001
                if destination.is_file()
                else None
            )
            if destination_hash != staging_hashes[key]:
                raise ValueError(f"운영 이미지 키 {key}의 파일 내용이 스테이징과 다릅니다.")
        else:
            images_to_copy.append(key)

    allowed_recovery_orphans = set(staging_hashes)
    unexpected_orphans = sorted(
        runtime_disk_keys - set(runtime_key_owner) - allowed_recovery_orphans
    )
    if unexpected_orphans:
        raise ValueError(f"운영 이미지 디렉터리에 고아 파일이 있습니다: {unexpected_orphans[:5]}")

    ordered_records = [merged[key] for key in sorted(merged)]
    application_year_range = _application_year_range(ordered_records)
    dataset_info = dict(runtime_payload.get("dataset_info") or {})
    dataset_info.update(
        {
            "총_상표수": len(ordered_records),
            "출원일자_범위": application_year_range,
            "데이터_기준": PROMOTED_DATASET_BASIS,
            "생성일자": datetime.now(timezone.utc).date().isoformat(),
        }
    )
    merged_payload = {
        key: value
        for key, value in runtime_payload.items()
        if key not in {"trademarks", "staging_info"}
    }
    merged_payload["dataset_info"] = dataset_info
    merged_payload["trademarks"] = ordered_records

    image_keys = collect._validated_image_keys(  # noqa: SLF001
        [record.get("이미지파일", "") for record in ordered_records]
    )
    image_hashes: dict[str, str] = {}
    for key in image_keys:
        if key in staging_hashes:
            image_hashes[key] = staging_hashes[key]
        else:
            image_hashes[key] = collect._sha256_file(paths.IMAGES_DIR / key)  # noqa: SLF001

    return Promotion(
        staging_path=staging_path,
        merged_payload=merged_payload,
        image_keys=image_keys,
        image_hashes=image_hashes,
        images_to_copy=tuple(sorted(images_to_copy)),
        new_record_count=new_count,
        unchanged_record_count=unchanged_count,
    )


def promotion_summary(promotion: Promotion) -> dict:
    return {
        "network_calls_executed": 0,
        "new_records": promotion.new_record_count,
        "unchanged_records": promotion.unchanged_record_count,
        "images_to_copy": len(promotion.images_to_copy),
        "merged_record_count": len(promotion.merged_payload["trademarks"]),
        "dataset_info": promotion.merged_payload["dataset_info"],
        "requires_index_rebuild": True,
    }


def apply_promotion(promotion: Promotion) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir = promotion.staging_path.parent / "promotion_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"kipris_metadata_{timestamp}.json"
    shutil.copy2(paths.TRADEMARK_META_PATH, backup_path)

    collect.mark_index_dirty(paths.INDEX_DIRTY_PATH)
    for key in promotion.images_to_copy:
        source = collect.staging_image_path(promotion.staging_path, key)
        destination = paths.IMAGES_DIR / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".promote")
        shutil.copyfile(source, temporary)
        if collect._sha256_file(temporary) != promotion.image_hashes[key]:  # noqa: SLF001
            temporary.unlink(missing_ok=True)
            raise ValueError(f"복사 후 이미지 SHA-256 검증 실패: {key}")
        os.replace(temporary, destination)

    collect._atomic_write_json(  # noqa: SLF001
        paths.TRADEMARK_META_PATH,
        promotion.merged_payload,
    )
    collect._atomic_write_json(  # noqa: SLF001
        collect.AUTHORITATIVE_KEYS_PATH,
        {
            "schema_version": 1,
            "source": "file-promotion",
            "metadata_sha256": collect._sha256_file(paths.TRADEMARK_META_PATH),  # noqa: SLF001
            "image_keys": promotion.image_keys,
            "image_hashes": promotion.image_hashes,
        },
    )
    collect.rebuild_index()
    collect.clear_index_dirty(paths.INDEX_DIRTY_PATH)
    return backup_path


def main() -> int:
    parser = argparse.ArgumentParser(description="연구 파일 스테이징 운영 승격")
    parser.add_argument("--staging", type=collect._file_staging_arg, required=True)  # noqa: SLF001
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="검증과 변경 범위 출력만 수행")
    mode.add_argument("--apply", action="store_true", help="검증 후 운영 파일과 인덱스 변경")
    args = parser.parse_args()

    if config.DATABASE_URL:
        print("[오류] DB 모드에서는 파일 스테이징 승격을 사용할 수 없습니다.", file=sys.stderr)
        return 1
    try:
        promotion = prepare_promotion(args.staging)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[오류] 승격 사전 검증 실패: {exc}", file=sys.stderr)
        return 1

    print("[승격 계획] " + json.dumps(promotion_summary(promotion), ensure_ascii=False))
    if args.plan:
        return 0
    try:
        backup = apply_promotion(promotion)
    except (OSError, ValueError, RuntimeError) as exc:
        print(
            f"[오류] 승격 중단: {exc}\n"
            f"       dirty marker를 유지했습니다: {paths.INDEX_DIRTY_PATH}",
            file=sys.stderr,
        )
        return 2
    print(f"[완료] 운영 파일 데이터셋 승격. 백업: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
