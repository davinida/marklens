"""MarkLens 파일 데이터셋을 네트워크 없이 감사한다.

구조 불일치(중복 출원번호, 안전하지 않은 이미지 키, 이미지 누락, 고아 이미지)는
종료 코드 2로 알린다. 동일 이미지나 동일 명칭은 합법적인 복수 권리일 수 있으므로
자동 삭제하지 않고 검토 목록으로만 남긴다.
"""

import argparse
import hashlib
import json
import os
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.src.core import paths  # noqa: E402
from backend.src.core.appno import (  # noqa: E402
    is_trademark_application_number,
    normalize_application_number,
)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _safe_image_key(raw: object) -> str | None:
    key = str(raw or "").strip().replace("\\", "/")
    candidate = PurePosixPath(key)
    if (
        not key
        or candidate.is_absolute()
        or any(part in ("", ".", "..") for part in candidate.parts)
        or candidate.as_posix() != key
        or ":" in key
        or candidate.suffix.lower() not in IMAGE_SUFFIXES
    ):
        return None
    return key


def _normalized_name(raw: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(raw or "")).casefold().split())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_dataset(
    source: Path,
    image_dir: Path,
    target_classes: set[int] | None = None,
) -> dict:
    payload = json.loads(source.read_text(encoding="utf-8"))
    records = payload.get("trademarks")
    if not isinstance(records, list):
        raise ValueError("metadata에는 trademarks 배열이 필요합니다.")

    application_numbers: Counter[str] = Counter()
    nice_counts: Counter[int] = Counter()
    year_counts: Counter[str] = Counter()
    normalized_names: dict[str, list[str]] = defaultdict(list)
    expected_keys: set[str] = set()
    unsafe_image_keys: list[str] = []
    invalid_application_numbers: list[str] = []
    field_present: Counter[str] = Counter()

    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            invalid_application_numbers.append(f"row:{index}")
            continue
        raw_app_no = record.get("출원번호", "")
        try:
            app_no = normalize_application_number(raw_app_no)
        except (TypeError, ValueError):
            invalid_application_numbers.append(str(raw_app_no))
            continue
        application_numbers[app_no] += 1
        if not is_trademark_application_number(app_no):
            invalid_application_numbers.append(app_no)

        key = _safe_image_key(record.get("이미지파일"))
        if key is None:
            unsafe_image_keys.append(str(record.get("이미지파일", "")))
        else:
            expected_keys.add(key)

        for raw_class in record.get("류", []):
            try:
                nice_class = int(raw_class)
            except (TypeError, ValueError):
                continue
            if 1 <= nice_class <= 45:
                nice_counts[nice_class] += 1

        application_date = str(record.get("출원일자") or "")
        if len(application_date) >= 4 and application_date[:4].isdigit():
            year_counts[application_date[:4]] += 1

        name = _normalized_name(record.get("상표한글명") or record.get("상표영문명"))
        if name:
            normalized_names[name].append(app_no)

        for field in ("비엔나코드", "류", "유사군", "출원인", "최종권리자"):
            if record.get(field):
                field_present[field] += 1

    disk_files = {
        path.relative_to(image_dir).as_posix(): path
        for path in image_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    }
    missing_images = sorted(expected_keys - set(disk_files))
    orphan_images = sorted(set(disk_files) - expected_keys)

    hashes: dict[str, list[str]] = defaultdict(list)
    for key in sorted(expected_keys & set(disk_files)):
        hashes[_sha256(disk_files[key])].append(key)
    duplicate_hash_groups = sorted(
        (sorted(keys) for keys in hashes.values() if len(keys) > 1),
        key=lambda keys: (-len(keys), keys),
    )
    duplicate_name_groups = {
        name: sorted(app_nos)
        for name, app_nos in sorted(normalized_names.items())
        if len(app_nos) > 1
    }
    duplicate_application_numbers = {
        app_no: count
        for app_no, count in sorted(application_numbers.items())
        if count > 1
    }
    record_count = len(records)
    completeness = {
        field: {
            "present": field_present[field],
            "ratio": round(field_present[field] / record_count, 4) if record_count else 0,
        }
        for field in ("비엔나코드", "류", "유사군", "출원인", "최종권리자")
    }
    target_classes = target_classes or set()
    blockers = []
    if duplicate_application_numbers:
        blockers.append("duplicate_application_numbers")
    if invalid_application_numbers:
        blockers.append("invalid_application_numbers")
    if unsafe_image_keys:
        blockers.append("unsafe_image_keys")
    if missing_images:
        blockers.append("missing_images")
    if orphan_images:
        blockers.append("orphan_images")

    return {
        "schema_version": 1,
        "source": source.name,
        "summary": {
            "record_count": record_count,
            "distinct_application_numbers": len(application_numbers),
            "disk_image_count": len(disk_files),
            "missing_image_count": len(missing_images),
            "orphan_image_count": len(orphan_images),
            "duplicate_image_hash_group_count": len(duplicate_hash_groups),
            "duplicate_image_hash_file_count": sum(map(len, duplicate_hash_groups)),
            "duplicate_name_group_count": len(duplicate_name_groups),
            "blocking_issue_count": len(blockers),
        },
        "target_class_counts": {
            str(value): nice_counts[value] for value in sorted(target_classes)
        },
        "nice_class_counts": {
            str(key): value for key, value in sorted(nice_counts.items())
        },
        "application_year_counts": dict(sorted(year_counts.items())),
        "field_completeness": completeness,
        "blocking_issues": blockers,
        "details": {
            "duplicate_application_numbers": duplicate_application_numbers,
            "invalid_application_numbers": invalid_application_numbers,
            "unsafe_image_keys": unsafe_image_keys,
            "missing_images": missing_images,
            "orphan_images": orphan_images,
            "duplicate_image_hash_groups": duplicate_hash_groups,
            "duplicate_name_groups": duplicate_name_groups,
        },
    }


def _nice_class(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Nice 류는 1~45 정수여야 합니다.") from exc
    if not 1 <= value <= 45:
        raise argparse.ArgumentTypeError("Nice 류는 1~45 범위여야 합니다.")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="MarkLens 파일 데이터셋 오프라인 감사")
    parser.add_argument("--source", type=Path, default=paths.TRADEMARK_META_PATH)
    parser.add_argument("--image-dir", type=Path, default=paths.IMAGES_DIR)
    parser.add_argument("--target-class", type=_nice_class, action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = audit_dataset(args.source, args.image_dir, set(args.target_class))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[오류] 데이터셋 감사를 완료하지 못했습니다: {exc}", file=sys.stderr)
        return 1
    if args.output:
        _atomic_write(args.output, report)
        print(f"[감사] JSON 리포트: {args.output}")
    print("[감사] " + json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 2 if report["blocking_issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
