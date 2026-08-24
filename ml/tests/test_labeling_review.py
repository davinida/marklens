from __future__ import annotations

import http.client
import json
import multiprocessing
import re
import threading
from pathlib import Path

import pytest
from evaluation import review as review_module
from evaluation.labeling import DEV_COUNT, HOLDOUT_COUNT, validate_labeling_pack
from evaluation.review import (
    MAX_NOTES_LENGTH,
    ReviewAccessError,
    ReviewConflictError,
    ReviewStore,
    ReviewValidationError,
    default_receipt_path,
    expected_holdout_confirmation,
    load_review_pack,
    prepare_holdout_unlock,
    resolve_image_path,
)
from evaluation.review_server import CSRF_HEADER, create_review_server

ML_ROOT = Path(__file__).resolve().parents[1]
PACK_SOURCE = ML_ROOT / "evaluation" / "labeling_pack_v2.json"
UI_DIR = ML_ROOT / "evaluation" / "review_ui"
BLANK_ANNOTATION = {
    "visual_similarity": None,
    "confidence": None,
    "annotator_id": None,
    "notes": None,
}


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _nested_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_nested_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_nested_keys(item) for item in value))
    return set()


def _blank_pack_copy(tmp_path: Path) -> tuple[Path, Path, dict]:
    pack = json.loads(PACK_SOURCE.read_text(encoding="utf-8"))
    for pair in pack["pairs"]:
        pair["annotation"] = dict(BLANK_ANNOTATION)
    validate_labeling_pack(pack, require_blank=True)
    pack_path = tmp_path / "labeling_pack_v2.json"
    _write_json(pack_path, pack)
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    return pack_path, image_dir, pack


def _complete_development_labels(pack_path: Path, annotator: str = "dev-reviewer") -> dict:
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    for pair in pack["pairs"]:
        if pair["split"] == "dev":
            pair["annotation"] = {
                "visual_similarity": "visually_distinct",
                "confidence": "high",
                "annotator_id": annotator,
                "notes": None,
            }
    _write_json(pack_path, pack)
    return pack


def _request(
    port: int,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        return response.status, response_headers, response.read()
    finally:
        connection.close()


def _concurrent_save_worker(
    pack_path: str,
    image_dir: str,
    pair_id: str,
    annotator_id: str,
    ready,
    start,
    results,
) -> None:
    try:
        store = ReviewStore(
            pack_path=Path(pack_path),
            image_dir=Path(image_dir),
            annotator_id=annotator_id,
        )
        state = store.public_state()
        ready.put(("ready", state["revision"]))
        if not start.wait(15):
            results.put(("error", "start timeout"))
            return
        store.save_annotation(
            pair_id=pair_id,
            expected_revision=state["revision"],
            visual_similarity="visually_similar",
            confidence="medium",
            notes=None,
        )
        results.put(("ok", pair_id))
    except ReviewConflictError as exc:
        results.put(("conflict", str(exc)))
    except Exception as exc:  # pragma: no cover - surfaced with process result
        results.put(("error", repr(exc)))


@pytest.fixture
def dev_store(tmp_path):
    pack_path, image_dir, pack = _blank_pack_copy(tmp_path)
    store = ReviewStore(
        pack_path=pack_path,
        image_dir=image_dir,
        annotator_id="reviewer-a",
    )
    return store, pack_path, image_dir, pack


def test_store_saves_atomically_and_resumes_without_exposing_selection_metadata(
    dev_store,
):
    store, pack_path, image_dir, pack = dev_store
    state = store.public_state()

    assert state["counts"] == {"total": DEV_COUNT, "labeled": 0, "remaining": DEV_COUNT}
    assert len(state["pairs"]) == DEV_COUNT
    assert {pair["pair_id"] for pair in state["pairs"]} == {
        pair["pair_id"] for pair in pack["pairs"] if pair["split"] == "dev"
    }
    public_keys = _nested_keys(state)
    for forbidden_field in (
        "similarity_stratum",
        "family_id",
        "image_key",
        "similarity",
        "source",
    ):
        assert forbidden_field not in public_keys

    first = state["pairs"][0]
    result = store.save_annotation(
        pair_id=first["pair_id"],
        expected_revision=state["revision"],
        visual_similarity="visually_similar",
        confidence="medium",
        notes="  balanced shapes  ",
    )

    assert result["annotation"] == {
        "visual_similarity": "visually_similar",
        "confidence": "medium",
        "annotator_id": "reviewer-a",
        "notes": "balanced shapes",
    }
    assert result["counts"] == {
        "total": DEV_COUNT,
        "labeled": 1,
        "remaining": DEV_COUNT - 1,
    }
    lock_name = f".{pack_path.name}.review.lock.tmp"
    leftovers = [
        path for path in pack_path.parent.glob(f".{pack_path.name}.*.tmp") if path.name != lock_name
    ]
    assert not leftovers

    saved_pack, _ = load_review_pack(pack_path)
    validate_labeling_pack(saved_pack, require_blank=False)
    resumed = ReviewStore(
        pack_path=pack_path,
        image_dir=image_dir,
        annotator_id="reviewer-a",
    ).public_state()
    assert resumed["counts"]["labeled"] == 1
    assert resumed["pairs"][0]["annotation"] == result["annotation"]


def test_invalid_annotation_and_failed_atomic_write_leave_state_unchanged(dev_store, monkeypatch):
    store, pack_path, _, _ = dev_store
    state = store.public_state()
    first = state["pairs"][0]
    original_bytes = pack_path.read_bytes()

    with pytest.raises(ReviewValidationError, match="confidence"):
        store.save_annotation(
            pair_id=first["pair_id"],
            expected_revision=state["revision"],
            visual_similarity="visually_similar",
            confidence=None,
            notes=None,
        )
    with pytest.raises(ReviewValidationError, match="notes"):
        store.save_annotation(
            pair_id=first["pair_id"],
            expected_revision=state["revision"],
            visual_similarity="visually_similar",
            confidence="high",
            notes="x" * (MAX_NOTES_LENGTH + 1),
        )

    def fail_write(_path, _data):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(review_module, "_atomic_write", fail_write)
    with pytest.raises(OSError, match="simulated"):
        store.save_annotation(
            pair_id=first["pair_id"],
            expected_revision=state["revision"],
            visual_similarity="visually_distinct",
            confidence="low",
            notes=None,
        )

    assert pack_path.read_bytes() == original_bytes
    assert store.public_state()["pairs"][0]["annotation"] == BLANK_ANNOTATION


def test_external_revision_and_foreign_annotator_are_fail_closed(dev_store):
    store, pack_path, image_dir, _ = dev_store
    state = store.public_state()
    first, second = state["pairs"][:2]
    saved = store.save_annotation(
        pair_id=first["pair_id"],
        expected_revision=state["revision"],
        visual_similarity="visually_distinct",
        confidence="high",
        notes=None,
    )

    other = ReviewStore(
        pack_path=pack_path,
        image_dir=image_dir,
        annotator_id="reviewer-b",
    )
    other_state = other.public_state()
    foreign = next(pair for pair in other_state["pairs"] if pair["pair_id"] == first["pair_id"])
    assert foreign["editable"] is False
    with pytest.raises(ReviewAccessError, match="owns"):
        other.save_annotation(
            pair_id=first["pair_id"],
            expected_revision=other_state["revision"],
            visual_similarity="visually_similar",
            confidence="medium",
            notes=None,
        )

    external_pack = json.loads(pack_path.read_text(encoding="utf-8"))
    external_pair = next(
        pair for pair in external_pack["pairs"] if pair["pair_id"] == second["pair_id"]
    )
    external_pair["annotation"] = {
        "visual_similarity": "cannot_assess",
        "confidence": "low",
        "annotator_id": "external-reviewer",
        "notes": "missing image",
    }
    _write_json(pack_path, external_pack)

    with pytest.raises(ReviewConflictError, match="changed outside"):
        store.save_annotation(
            pair_id=second["pair_id"],
            expected_revision=saved["revision"],
            visual_similarity="visually_similar",
            confidence="medium",
            notes=None,
        )
    reloaded, _ = load_review_pack(pack_path)
    unchanged = next(pair for pair in reloaded["pairs"] if pair["pair_id"] == second["pair_id"])
    assert unchanged["annotation"]["annotator_id"] == "external-reviewer"


def test_interprocess_lock_allows_one_commit_and_rejects_one_stale_writer(tmp_path):
    pack_path, image_dir, pack = _blank_pack_copy(tmp_path)
    pair_ids = [pair["pair_id"] for pair in pack["pairs"] if pair["split"] == "dev"][:2]
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_concurrent_save_worker,
            args=(
                str(pack_path),
                str(image_dir),
                pair_id,
                f"reviewer-{index}",
                ready,
                start,
                results,
            ),
        )
        for index, pair_id in enumerate(pair_ids, start=1)
    ]
    try:
        for process in processes:
            process.start()
        revisions = [ready.get(timeout=20) for _ in processes]
        assert all(status == "ready" for status, _ in revisions)
        assert len({revision for _, revision in revisions}) == 1
        start.set()
        outcomes = [results.get(timeout=20) for _ in processes]
    finally:
        start.set()
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    assert sorted(status for status, _ in outcomes) == ["conflict", "ok"]
    assert all(process.exitcode == 0 for process in processes)
    saved_pack, _ = load_review_pack(pack_path)
    assert (
        sum(pair["annotation"]["visual_similarity"] is not None for pair in saved_pack["pairs"])
        == 1
    )


def test_image_resolution_rejects_traversal_absolute_and_symlink_escape(tmp_path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    valid = image_dir / "nested" / "valid.png"
    valid.parent.mkdir()
    valid.write_bytes(b"png")

    assert resolve_image_path(image_dir, "nested/valid.png", require_exists=True) == valid
    for unsafe in ("../escape.png", "/absolute.png", "C:/escape.png", "\\server\\x.png"):
        with pytest.raises(ReviewValidationError):
            resolve_image_path(image_dir, unsafe, require_exists=False)

    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png")
    link = image_dir / "linked.png"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is unavailable in this Windows test environment")
    with pytest.raises(ReviewValidationError, match="escapes"):
        resolve_image_path(image_dir, "linked.png", require_exists=True)


def test_development_mode_denies_holdout_pairs_and_images(dev_store):
    store, _, _, pack = dev_store
    state = store.public_state()
    holdout_pair = next(pair for pair in pack["pairs"] if pair["split"] == "frozen_holdout")

    assert len(state["pairs"]) == DEV_COUNT
    assert holdout_pair["pair_id"] not in {pair["pair_id"] for pair in state["pairs"]}
    with pytest.raises(ReviewAccessError, match="active review split"):
        store.image_response(holdout_pair["pair_id"], "left")


def test_holdout_requires_complete_dev_exact_confirmation_and_immutable_receipt(tmp_path):
    pack_path, image_dir, _ = _blank_pack_copy(tmp_path)
    receipt_path = default_receipt_path(pack_path)
    pack, _ = load_review_pack(pack_path)
    confirmation = expected_holdout_confirmation(pack["pack_id"])

    with pytest.raises(ReviewAccessError, match="160 development"):
        prepare_holdout_unlock(
            pack_path,
            receipt_path,
            annotator_id="reviewer-a",
            confirmation=confirmation,
        )
    assert not receipt_path.exists()

    completed = _complete_development_labels(pack_path)
    running_dev_store = ReviewStore(
        pack_path=pack_path,
        image_dir=image_dir,
        annotator_id="dev-reviewer",
        mode="dev",
    )
    running_dev_state = running_dev_store.public_state()
    with pytest.raises(ReviewAccessError, match="confirmation"):
        prepare_holdout_unlock(
            pack_path,
            receipt_path,
            annotator_id="reviewer-a",
            confirmation="UNLOCK_FROZEN_HOLDOUT:wrong-pack",
        )
    assert prepare_holdout_unlock(
        pack_path,
        receipt_path,
        annotator_id="reviewer-a",
        confirmation=confirmation,
    )
    assert not prepare_holdout_unlock(
        pack_path,
        receipt_path,
        annotator_id="reviewer-a",
        confirmation=confirmation,
    )

    with pytest.raises(ReviewAccessError, match="now locked"):
        running_dev_store.public_state()
    original_bytes = pack_path.read_bytes()
    running_pair = running_dev_state["pairs"][0]
    with pytest.raises(ReviewAccessError, match="now locked"):
        running_dev_store.save_annotation(
            pair_id=running_pair["pair_id"],
            expected_revision=running_dev_state["revision"],
            visual_similarity="visually_similar",
            confidence="medium",
            notes="must not change after unlock",
        )
    assert pack_path.read_bytes() == original_bytes

    with pytest.raises(ReviewAccessError, match="now locked"):
        ReviewStore(
            pack_path=pack_path,
            image_dir=image_dir,
            annotator_id="reviewer-a",
            mode="dev",
            receipt_path=receipt_path,
        )

    holdout_store = ReviewStore(
        pack_path=pack_path,
        image_dir=image_dir,
        annotator_id="reviewer-a",
        mode="frozen_holdout",
        receipt_path=receipt_path,
    )
    holdout_state = holdout_store.public_state()
    assert holdout_state["counts"] == {
        "total": HOLDOUT_COUNT,
        "labeled": 0,
        "remaining": HOLDOUT_COUNT,
    }
    assert {pair["pair_id"] for pair in holdout_state["pairs"]} == {
        pair["pair_id"] for pair in completed["pairs"] if pair["split"] == "frozen_holdout"
    }

    dev_pair = next(pair for pair in completed["pairs"] if pair["split"] == "dev")
    dev_pair["annotation"]["notes"] = "changed after unlock"
    _write_json(pack_path, completed)
    with pytest.raises(ReviewAccessError, match="changed after holdout unlock"):
        ReviewStore(
            pack_path=pack_path,
            image_dir=image_dir,
            annotator_id="reviewer-a",
            mode="frozen_holdout",
            receipt_path=receipt_path,
        )


def test_unlock_receipt_path_is_canonical_and_cannot_overwrite_pack(tmp_path):
    pack_path, image_dir, pack = _blank_pack_copy(tmp_path)
    _complete_development_labels(pack_path)
    with pytest.raises(ReviewValidationError, match="must not overwrite"):
        prepare_holdout_unlock(
            pack_path,
            pack_path,
            annotator_id="reviewer-a",
            confirmation=expected_holdout_confirmation(pack["pack_id"]),
        )
    arbitrary_receipt = tmp_path / "alternate-unlock.json"
    with pytest.raises(ReviewValidationError, match="canonical path"):
        prepare_holdout_unlock(
            pack_path,
            arbitrary_receipt,
            annotator_id="reviewer-a",
            confirmation=expected_holdout_confirmation(pack["pack_id"]),
        )
    with pytest.raises(ReviewValidationError, match="canonical path"):
        ReviewStore(
            pack_path=pack_path,
            image_dir=image_dir,
            annotator_id="reviewer-a",
            receipt_path=arbitrary_receipt,
        )


def test_loopback_server_enforces_host_origin_csrf_and_sanitized_state(dev_store):
    store, _, _, _ = dev_store
    server = create_review_server(store, port=0, static_dir=UI_DIR)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    good_host = f"127.0.0.1:{port}"
    good_origin = f"http://{good_host}"
    try:
        status, headers, body = _request(port, "GET", "/", headers={"Host": good_host})
        assert status == 200
        assert headers["content-security-policy"].startswith("default-src 'none'")
        assert headers["cache-control"].startswith("no-store")
        html = body.decode("utf-8")
        assert "__MARKLENS_CSRF_TOKEN__" not in html
        token_match = re.search(r'name="marklens-csrf" content="([^"]+)"', html)
        assert token_match is not None
        csrf_token = token_match.group(1)

        status, _, body = _request(port, "GET", "/api/state", headers={"Host": good_host})
        assert status == 200
        state = json.loads(body)
        public_keys = _nested_keys(state)
        assert len(state["pairs"]) == DEV_COUNT
        assert "similarity_stratum" not in public_keys
        assert "family_id" not in public_keys
        assert "image_key" not in public_keys
        assert "similarity" not in public_keys
        assert "source" not in public_keys

        status, _, _ = _request(port, "GET", "/api/state", headers={"Host": f"evil.test:{port}"})
        assert status == 403

        first = state["pairs"][0]
        request_body = json.dumps(
            {
                "pair_id": first["pair_id"],
                "expected_revision": state["revision"],
                "visual_similarity": "visually_similar",
                "confidence": "medium",
                "notes": None,
                "clear": False,
            }
        ).encode("utf-8")
        base_headers = {
            "Host": good_host,
            "Content-Type": "application/json",
            "Content-Length": str(len(request_body)),
            CSRF_HEADER: csrf_token,
        }
        status, _, _ = _request(
            port,
            "POST",
            "/api/annotation",
            headers=base_headers,
            body=request_body,
        )
        assert status == 403

        status, _, body = _request(
            port,
            "POST",
            "/api/annotation",
            headers={**base_headers, "Origin": good_origin},
            body=request_body,
        )
        assert status == 200
        assert json.loads(body)["counts"]["labeled"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_static_ui_is_local_only_and_contains_required_review_controls():
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    javascript = (UI_DIR / "app.js").read_text(encoding="utf-8")
    combined = html + javascript

    assert "http://" not in combined
    assert "https://" not in combined
    assert 'data-filter="remaining"' in html
    assert 'data-filter="cannot_assess"' in html
    assert 'event.key === "ArrowLeft"' in javascript
    assert 'event.key === "ArrowRight"' in javascript
    assert "event.ctrlKey || event.metaKey" in javascript
    assert "similarity_stratum" not in combined
    assert "family_id" not in combined
