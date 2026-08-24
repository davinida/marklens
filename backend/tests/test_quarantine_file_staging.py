import json
from datetime import datetime, timezone

import pytest

from backend.scripts import collect_pipeline as collect
from backend.scripts import quarantine_file_staging as quarantine


def _record(app_no: str, name: str) -> dict:
    return {
        "출원번호": app_no,
        "등록번호": app_no,
        "이미지파일": f"{app_no}.png",
        "출원일자": "2026-01-01",
        "등록일자": "2026-02-01",
        "상표한글명": name,
        "상표영문명": None,
        "상표구분": "도형복합",
        "출원인": "테스트 출원인",
        "최종권리자": "테스트 권리자",
        "비엔나코드": ["270501"],
        "류": [9],
        "유사군": [],
    }


def _row(record: dict) -> tuple:
    return (
        record["출원번호"],
        record["등록번호"],
        record["출원일자"],
        record["등록일자"],
        record["상표한글명"],
        record["상표영문명"],
        record["상표구분"],
        record["출원인"],
        record["최종권리자"],
        record["이미지파일"],
        record["비엔나코드"],
        record["류"],
        record["유사군"],
    )


@pytest.fixture
def quarantine_sandbox(tmp_path, monkeypatch):
    data = tmp_path / "data"
    runtime_images = data / "images"
    runtime_index = data / "index"
    staging = data / "staging" / "expansion.json"
    stage_images = collect.staging_image_dir(staging)
    runtime_images.mkdir(parents=True)
    runtime_index.mkdir(parents=True)
    stage_images.mkdir(parents=True)

    runtime_meta = data / "kipris_metadata.json"
    runtime_meta.write_bytes(b'{"runtime": true}')
    runtime_image = runtime_images / "runtime.png"
    runtime_image.write_bytes(b"runtime-image")
    runtime_artifact = runtime_index / "runtime.index"
    runtime_artifact.write_bytes(b"runtime-index")

    monkeypatch.setattr(collect.paths, "ML_DATA_DIR", data)
    monkeypatch.setattr(collect.paths, "IMAGES_DIR", runtime_images)
    monkeypatch.setattr(collect.paths, "TRADEMARK_META_PATH", runtime_meta)

    first = _record("4020240121569", "oversized")
    second = _record("4020240121570", "usable")
    (stage_images / first["이미지파일"]).write_bytes(b"oversized-image")
    (stage_images / second["이미지파일"]).write_bytes(b"usable-image")
    collect.merge_file_staging_rows([_row(first), _row(second)], staging)
    checkpoint = collect.staging_checkpoint_path(staging)
    collect.update_checkpoint(
        [first["출원번호"], second["출원번호"]],
        path=checkpoint,
    )
    monkeypatch.setattr(
        quarantine,
        "_utc_now",
        lambda: datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc),
    )
    return {
        "staging": staging,
        "checkpoint": checkpoint,
        "target": first,
        "remaining": second,
        "runtime": (runtime_meta, runtime_image, runtime_artifact),
    }


def test_plan_is_read_only_and_rejects_paths_outside_staging(quarantine_sandbox, tmp_path):
    sandbox = quarantine_sandbox
    staging = sandbox["staging"]
    before = {
        path: path.read_bytes()
        for path in (
            staging,
            collect.staging_authoritative_path(staging),
            sandbox["checkpoint"],
            *sandbox["runtime"],
        )
    }

    plan = quarantine.prepare_quarantine(
        staging,
        sandbox["target"]["출원번호"],
        "이미지 픽셀 안전 한도 초과",
    )
    summary = quarantine.quarantine_summary(plan)

    assert summary["network_calls_executed"] == 0
    assert summary["operating_files_changed"] is False
    assert summary["record_count_before"] == 2
    assert summary["record_count_after"] == 1
    assert all(path.read_bytes() == contents for path, contents in before.items())
    assert not quarantine.quarantine_root(staging).exists()
    assert not collect.staging_dirty_path(staging).exists()

    outside = tmp_path / "outside.json"
    with pytest.raises(ValueError, match="ml.*data.*staging|staging"):
        quarantine.prepare_quarantine(
            outside,
            sandbox["target"]["출원번호"],
            "범위 밖",
        )


def test_apply_moves_image_updates_hashes_and_preserves_checkpoint(
    quarantine_sandbox,
):
    sandbox = quarantine_sandbox
    staging = sandbox["staging"]
    checkpoint_before = sandbox["checkpoint"].read_bytes()
    runtime_before = {path: path.read_bytes() for path in sandbox["runtime"]}
    plan = quarantine.prepare_quarantine(
        staging,
        sandbox["target"]["출원번호"],
        "8001x8000 이미지가 64M 픽셀 안전 한도를 초과",
    )

    manifest_path = quarantine.apply_quarantine(plan)

    payload = json.loads(staging.read_text(encoding="utf-8"))
    authoritative = json.loads(
        collect.staging_authoritative_path(staging).read_text(encoding="utf-8")
    )
    audit = json.loads(manifest_path.read_text(encoding="utf-8"))
    quarantined_image = manifest_path.parent / "image" / plan.image_key
    assert [record["출원번호"] for record in payload["trademarks"]] == [
        sandbox["remaining"]["출원번호"]
    ]
    assert payload["dataset_info"]["총_상표수"] == 1
    assert authoritative["image_keys"] == [sandbox["remaining"]["이미지파일"]]
    assert set(authoritative["image_hashes"]) == {
        sandbox["remaining"]["이미지파일"]
    }
    assert authoritative["metadata_sha256"] == collect._sha256_file(staging)
    assert not collect.staging_image_path(staging, plan.image_key).exists()
    assert quarantined_image.read_bytes() == b"oversized-image"
    assert audit["state"] == "complete"
    assert audit["reason"] == "8001x8000 이미지가 64M 픽셀 안전 한도를 초과"
    assert audit["application_number"] == sandbox["target"]["출원번호"]
    assert audit["image_sha256"] == collect._sha256_file(quarantined_image)
    assert audit["source"]["checkpoint_collected_preserved"] is True
    assert sandbox["checkpoint"].read_bytes() == checkpoint_before
    assert sandbox["target"]["출원번호"] in collect.load_checkpoint(
        sandbox["checkpoint"]
    )
    assert all(path.read_bytes() == contents for path, contents in runtime_before.items())
    assert not collect.staging_dirty_path(staging).exists()
    assert collect.inspect_file_staging(staging) == (True, None)

    backup_dir = manifest_path.parent / "before"
    assert (backup_dir / staging.name).is_file()
    assert (backup_dir / collect.staging_authoritative_path(staging).name).is_file()
    assert (backup_dir / sandbox["checkpoint"].name).read_bytes() == checkpoint_before


def test_missing_checkpoint_collected_entry_blocks_before_any_write(
    quarantine_sandbox,
):
    sandbox = quarantine_sandbox
    staging = sandbox["staging"]
    collect.update_checkpoint([], path=sandbox["checkpoint"])
    payload = json.loads(sandbox["checkpoint"].read_text(encoding="utf-8"))
    payload["collected"] = [sandbox["remaining"]["출원번호"]]
    sandbox["checkpoint"].write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="collected"):
        quarantine.prepare_quarantine(
            staging,
            sandbox["target"]["출원번호"],
            "재수집 방지 검사",
        )

    assert collect.staging_image_path(
        staging, sandbox["target"]["이미지파일"]
    ).is_file()
    assert not quarantine.quarantine_root(staging).exists()
    assert not collect.staging_dirty_path(staging).exists()


def test_mid_apply_failure_keeps_dirty_backups_and_image_in_quarantine(
    quarantine_sandbox,
    monkeypatch,
):
    sandbox = quarantine_sandbox
    staging = sandbox["staging"]
    checkpoint_before = sandbox["checkpoint"].read_bytes()
    runtime_before = {path: path.read_bytes() for path in sandbox["runtime"]}
    plan = quarantine.prepare_quarantine(
        staging,
        sandbox["target"]["출원번호"],
        "실패 복구 검사",
    )
    authoritative_path = collect.staging_authoritative_path(staging)
    real_atomic_write = collect._atomic_write_json

    def fail_authoritative(path, payload):
        if path == authoritative_path:
            raise OSError("injected manifest failure")
        return real_atomic_write(path, payload)

    monkeypatch.setattr(collect, "_atomic_write_json", fail_authoritative)

    with pytest.raises(OSError, match="injected manifest failure"):
        quarantine.apply_quarantine(plan)

    operation_dir = quarantine.quarantine_root(staging) / plan.operation_id
    assert collect.staging_dirty_path(staging).is_file()
    assert (operation_dir / "before" / staging.name).is_file()
    assert (
        operation_dir / "before" / authoritative_path.name
    ).read_bytes() == authoritative_path.read_bytes()
    assert (operation_dir / "image" / plan.image_key).read_bytes() == b"oversized-image"
    assert not collect.staging_image_path(staging, plan.image_key).exists()
    assert sandbox["checkpoint"].read_bytes() == checkpoint_before
    assert all(path.read_bytes() == contents for path, contents in runtime_before.items())
    failure_audit = json.loads(
        (operation_dir / "quarantine.json").read_text(encoding="utf-8")
    )
    assert failure_audit["state"] == "failed"
    assert "injected manifest failure" in failure_audit["error"]


def test_cli_contract_requires_explicit_target_reason_and_mode():
    help_text = quarantine.build_parser().format_help()

    assert "--application-number" in help_text
    assert "--reason" in help_text
    assert "--plan" in help_text
    assert "--apply" in help_text
