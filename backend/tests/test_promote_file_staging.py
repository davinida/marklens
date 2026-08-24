import json

import pytest

from backend.scripts import collect_pipeline as collect
from backend.scripts import promote_file_staging as promote


def _record(
    app_no: str,
    image_key: str,
    name: str,
    *,
    application_date: str | None = "2026-01-01",
) -> dict:
    return {
        "출원번호": app_no,
        "등록번호": app_no,
        "이미지파일": image_key,
        "출원일자": application_date,
        "등록일자": "2026-02-01",
        "상표한글명": name,
        "상표영문명": None,
        "상표구분": "도형복합",
        "출원인": "출원인",
        "최종권리자": "권리자",
        "비엔나코드": ["270501"],
        "류": [29, 43],
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
def promotion_sandbox(tmp_path, monkeypatch):
    data = tmp_path / "data"
    images = data / "images"
    index = data / "index"
    staging = data / "staging" / "bbq.json"
    images.mkdir(parents=True)
    index.mkdir(parents=True)
    runtime_record = _record(
        "4020250000001",
        "4020250000001.png",
        "기존",
        application_date="2025-01-01",
    )
    runtime_meta = data / "kipris_metadata.json"
    runtime_meta.write_text(
        json.dumps(
            {"dataset_info": {"총_상표수": 1}, "trademarks": [runtime_record]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (images / runtime_record["이미지파일"]).write_bytes(b"runtime")
    monkeypatch.setattr(collect.paths, "ML_DATA_DIR", data)
    monkeypatch.setattr(collect.paths, "IMAGES_DIR", images)
    monkeypatch.setattr(collect.paths, "TRADEMARK_META_PATH", runtime_meta)
    monkeypatch.setattr(collect.paths, "INDEX_DIRTY_PATH", index / ".kipris-index-dirty")
    monkeypatch.setattr(collect, "INDEX_DIRTY_PATH", index / ".kipris-index-dirty")
    monkeypatch.setattr(collect, "AUTHORITATIVE_KEYS_PATH", index / "keys.json")
    return staging, runtime_meta, images


def test_promotion_plan_and_apply_are_hash_checked_and_atomic(
    promotion_sandbox, monkeypatch
):
    staging, runtime_meta, runtime_images = promotion_sandbox
    staged = _record("4020260000002", "4020260000002.png", "BBQ")
    stage_images = collect.staging_image_dir(staging)
    stage_images.mkdir(parents=True)
    (stage_images / staged["이미지파일"]).write_bytes(b"staged")
    collect.merge_file_staging_rows([_row(staged)], staging)

    before_meta = runtime_meta.read_bytes()
    plan = promote.prepare_promotion(staging)
    summary = promote.promotion_summary(plan)
    assert summary["new_records"] == 1
    assert summary["dataset_info"] == {
        "총_상표수": 2,
        "출원일자_범위": "2025 ~ 2026",
        "데이터_기준": promote.PROMOTED_DATASET_BASIS,
        "생성일자": promote.datetime.now(promote.timezone.utc).date().isoformat(),
    }
    assert runtime_meta.read_bytes() == before_meta
    assert not (runtime_images / staged["이미지파일"]).exists()

    rebuilt = []
    monkeypatch.setattr(collect, "rebuild_index", lambda: rebuilt.append(True))
    backup = promote.apply_promotion(plan)

    payload = json.loads(runtime_meta.read_text(encoding="utf-8"))
    assert len(payload["trademarks"]) == 2
    assert (runtime_images / staged["이미지파일"]).read_bytes() == b"staged"
    assert rebuilt == [True]
    assert backup.is_file()
    assert not collect.INDEX_DIRTY_PATH.exists()
    keys = json.loads(collect.AUTHORITATIVE_KEYS_PATH.read_text(encoding="utf-8"))
    assert keys["image_keys"] == ["4020250000001.png", "4020260000002.png"]


def test_repromotion_refreshes_dataset_info_without_new_records(
    promotion_sandbox, monkeypatch
):
    staging, runtime_meta, _runtime_images = promotion_sandbox
    runtime_record = json.loads(runtime_meta.read_text(encoding="utf-8"))["trademarks"][0]
    stage_images = collect.staging_image_dir(staging)
    stage_images.mkdir(parents=True)
    (stage_images / runtime_record["이미지파일"]).write_bytes(b"runtime")
    collect.merge_file_staging_rows([_row(runtime_record)], staging)

    plan = promote.prepare_promotion(staging)
    summary = promote.promotion_summary(plan)

    assert summary["network_calls_executed"] == 0
    assert summary["new_records"] == 0
    assert summary["unchanged_records"] == 1
    assert summary["images_to_copy"] == 0
    assert summary["requires_index_rebuild"] is True
    assert summary["dataset_info"]["총_상표수"] == 1
    assert summary["dataset_info"]["출원일자_범위"] == "2025 ~ 2025"
    assert summary["dataset_info"]["데이터_기준"] == promote.PROMOTED_DATASET_BASIS

    rebuilt = []
    monkeypatch.setattr(collect, "rebuild_index", lambda: rebuilt.append(True))
    promote.apply_promotion(plan)

    payload = json.loads(runtime_meta.read_text(encoding="utf-8"))
    assert payload["dataset_info"] == summary["dataset_info"]
    assert rebuilt == [True]


@pytest.mark.parametrize("application_date", [None, "", "2026-02-30", "2026/01/01"])
def test_promotion_rejects_missing_or_malformed_application_dates(
    promotion_sandbox, application_date
):
    staging, _runtime_meta, _runtime_images = promotion_sandbox
    staged = _record(
        "4020260000002",
        "4020260000002.png",
        "BBQ",
        application_date=application_date,
    )
    stage_images = collect.staging_image_dir(staging)
    stage_images.mkdir(parents=True)
    (stage_images / staged["이미지파일"]).write_bytes(b"staged")
    collect.merge_file_staging_rows([_row(staged)], staging)

    with pytest.raises(ValueError, match="YYYY-MM-DD 형식의 유효한 날짜"):
        promote.prepare_promotion(staging)


def test_promotion_rejects_staging_image_hash_mismatch(promotion_sandbox):
    staging, _runtime_meta, _runtime_images = promotion_sandbox
    staged = _record("4020260000002", "4020260000002.png", "BBQ")
    stage_images = collect.staging_image_dir(staging)
    stage_images.mkdir(parents=True)
    image_path = stage_images / staged["이미지파일"]
    image_path.write_bytes(b"staged")
    collect.merge_file_staging_rows([_row(staged)], staging)
    image_path.write_bytes(b"tampered")

    with pytest.raises(ValueError, match="스테이징 무결성 실패"):
        promote.prepare_promotion(staging)
