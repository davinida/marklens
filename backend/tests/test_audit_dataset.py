import json

from backend.scripts import audit_dataset as audit


def _record(app_no: str, image_key: str, name: str = "BBQ") -> dict:
    return {
        "출원번호": app_no,
        "이미지파일": image_key,
        "출원일자": "2026-01-01",
        "상표한글명": name,
        "비엔나코드": ["270501"],
        "류": [29, 43],
        "유사군": [],
        "출원인": "출원인",
        "최종권리자": "권리자",
    }


def test_audit_reports_blockers_and_non_destructive_review_groups(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "4020260000001.png").write_bytes(b"same")
    (images / "4020260000002.png").write_bytes(b"same")
    (images / "orphan.png").write_bytes(b"orphan")
    source = tmp_path / "metadata.json"
    source.write_text(
        json.dumps(
            {
                "trademarks": [
                    _record("4020260000001", "4020260000001.png"),
                    _record("4020260000002", "4020260000002.png", "ＢＢＱ"),
                    _record("4020260000003", "missing.png", "다른 이름"),
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = audit.audit_dataset(source, images, {29, 43})

    assert report["summary"]["record_count"] == 3
    assert report["summary"]["missing_image_count"] == 1
    assert report["summary"]["orphan_image_count"] == 1
    assert report["summary"]["duplicate_image_hash_group_count"] == 1
    assert report["summary"]["duplicate_name_group_count"] == 1
    assert report["target_class_counts"] == {"29": 3, "43": 3}
    assert report["blocking_issues"] == ["missing_images", "orphan_images"]


def test_audit_clean_dataset_has_no_blockers(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "4020260000001.png").write_bytes(b"one")
    source = tmp_path / "metadata.json"
    source.write_text(
        json.dumps(
            {"trademarks": [_record("4020260000001", "4020260000001.png")]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = audit.audit_dataset(source, images)

    assert report["blocking_issues"] == []
    assert report["summary"]["blocking_issue_count"] == 0
