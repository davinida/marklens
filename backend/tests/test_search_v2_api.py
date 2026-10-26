"""HTTP 경계·작업 스레드·공유 한도 검증. 실제 KIPRIS/CLIP 호출 없음."""

import io
import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from slowapi.errors import RateLimitExceeded

from backend.src.api import search
from backend.src.core import config, multi_search
from backend.src.core.ratelimit import limiter, rate_limit_exceeded_handler


def png(size=(64, 64)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def api(monkeypatch):
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.include_router(search.router)
    calls = []
    result = {"future": {"keep": None}, "prob": 0.123456789, "candidates": []}

    def run(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(to_dict=lambda: result)

    monkeypatch.setattr(search.engine, "multi_search", run)
    monkeypatch.setattr(search.engine, "state", SimpleNamespace(
        ready=True, index=SimpleNamespace(ntotal=1)
    ))
    monkeypatch.setattr(search, "_search_limiter", None)
    limiter.reset()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, calls, result
    limiter.reset()


@pytest.mark.parametrize("mask", range(1, 8))
def test_all_input_combinations_and_exact_passthrough(api, mask):
    client, calls, result = api
    fields = []
    if mask & 1:
        fields.append(("image", ("q.png", png(), "image/png")))
    if mask & 2:
        fields.append(("name", (None, "  블루😀  ")))
    if mask & 4:
        fields.extend([
            ("goods_codes", (None, " g0502, ,s120602 ")),
            ("goods_codes", (None, "G0502")),
        ])
    response = client.post("/search/v2", files=fields)
    assert response.status_code == 200
    assert response.json() == result
    assert calls[0]["name"] == ("블루😀" if mask & 2 else None)
    assert calls[0]["goods_codes"] == (["G0502", "S120602"] if mask & 4 else None)
    assert (calls[0]["image"] is not None) == bool(mask & 1)
    assert calls[0]["top_k"] == 5


@pytest.mark.parametrize("fields,code", [
    ([("name", (None, "  ")), ("goods_codes", (None, ", ,"))], 400),
    ([("name", (None, "x" * 101))], 422),
    ([("goods_codes", (None, "G１２３４"))], 422),
    ([("goods_codes", (None, "G123"))], 422),
    ([("goods_codes", (None, ",".join(f"G{i:04d}" for i in range(61))))], 422),
    ([("name", (None, "x")), ("type_override", (None, "unknown"))], 422),
    ([("image", (None, "oops"))], 415),
    ([("image", ("q.png", b"", "image/png"))], 400),
    ([("image", ("q.png", b"garbage", "image/png"))], 415),
    ([("image", ("q.png", png((31, 64)), "image/png"))], 400),
    ([("image", ("q.png", png(), "text/html"))], 415),
])
def test_validation(api, fields, code):
    client, calls, _ = api
    assert client.post("/search/v2", files=fields).status_code == code
    assert calls == []


@pytest.mark.parametrize("field", ["name", "image", "type_override"])
def test_scalar_duplicates(api, field):
    client, calls, _ = api
    assert client.post("/search/v2", files=[
        (field, (None, "x")), (field, (None, "y"))
    ]).status_code == 422
    assert not calls


@pytest.mark.parametrize("field", ["name", "goods_codes", "type_override"])
def test_file_in_text_field(api, field):
    client, calls, _ = api
    assert client.post("/search/v2", files={
        field: ("secret.txt", b"secret", "text/plain")
    }).status_code == 422
    assert not calls


@pytest.mark.parametrize("query", ["top_k=0", "top_k=21", "top_k=1.0", "top_k=1&top_k=2"])
def test_invalid_top_k(api, query):
    client, calls, _ = api
    assert client.post(f"/search/v2?{query}", data={"name": "x"}).status_code == 422
    assert not calls


@pytest.mark.parametrize("top_k", [1, 20])
def test_inclusive_boundaries(api, top_k):
    client, calls, _ = api
    response = client.post(f"/search/v2?top_k={top_k}", data={
        "name": "😀" * 100,
        "goods_codes": ",".join(f"G{i:04d}" for i in range(60)),
        "type_override": "결합",
    })
    assert response.status_code == 200
    assert calls[0]["top_k"] == top_k
    assert len(calls[0]["goods_codes"]) == 60


@pytest.mark.parametrize("error,code", [
    (multi_search.EmptyQueryError("sensitive"), 400),
    (ValueError("sensitive"), 422),
    (multi_search.ModelNotReadyError("sensitive"), 503),
    (RuntimeError("Engine 이 아직 초기화되지 않았습니다."), 503),
    (RuntimeError("sensitive"), 500),
    (KeyError("sensitive"), 500),
])
def test_error_mapping_and_private_logs(api, monkeypatch, caplog, error, code):
    client, _, _ = api

    def fail(**kwargs):
        raise error

    monkeypatch.setattr(search.engine, "multi_search", fail)
    response = client.post("/search/v2", data={"name": "sensitive"})
    assert response.status_code == code
    if type(error) is ValueError or isinstance(error, multi_search.ModelNotReadyError):
        assert response.json()["detail"] == str(error)
    else:
        assert "sensitive" not in response.text
    assert "sensitive" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_decode_and_engine_share_worker_and_capacity(api, monkeypatch):
    client, _, _ = api
    events = []

    class Capacity:
        async def __aenter__(self):
            events.append(("enter", threading.get_ident()))

        async def __aexit__(self, *args):
            events.append(("exit", threading.get_ident()))

    decode = search.validation.validate_and_decode

    def tracked_decode(raw):
        events.append(("decode", threading.get_ident()))
        return decode(raw)

    def run(**kwargs):
        events.append(("engine", threading.get_ident()))
        return SimpleNamespace(to_dict=lambda: {})

    monkeypatch.setattr(search, "_get_search_limiter", lambda: Capacity())
    monkeypatch.setattr(search.validation, "validate_and_decode", tracked_decode)
    monkeypatch.setattr(search.engine, "multi_search", run)
    response = client.post("/search/v2", files={"image": ("q.png", png(), "image/png")})
    assert response.status_code == 200
    assert [name for name, _ in events] == ["enter", "decode", "engine", "exit"]
    assert events[1][1] == events[2][1] != events[0][1]


def test_delayed_ocr_worker_can_read_image_after_response(api, monkeypatch):
    """OCR timeout이 검색을 끝내도 지연된 작업자의 PIL 참조는 유효해야 한다."""
    client, _, _ = api
    resume = threading.Event()
    outcomes = []
    workers = []

    def run(*, image, **kwargs):
        def delayed_ocr():
            if not resume.wait(5):
                outcomes.append("worker did not resume")
                return
            try:
                image.load()
                outcomes.append(image.getpixel((0, 0)))
            except Exception as exc:
                outcomes.append(type(exc).__name__)

        worker = threading.Thread(target=delayed_ocr)
        worker.start()
        workers.append(worker)
        # 엔진은 OCR timeout/fallback으로 먼저 응답하는 상황을 재현한다.
        return SimpleNamespace(to_dict=lambda: {"fallback": True})

    monkeypatch.setattr(search.engine, "multi_search", run)
    try:
        response = client.post("/search/v2", files={"image": ("q.png", png(), "image/png")})
        assert response.status_code == 200
        assert response.json() == {"fallback": True}
    finally:
        resume.set()
        for worker in workers:
            worker.join(timeout=5)
    assert outcomes == [(255, 0, 0)]
    assert not any(worker.is_alive() for worker in workers)


def test_oversized_request(api):
    client, calls, _ = api
    assert client.post("/search/v2", data={"name": "x"}, headers={
        "content-length": str(config.MAX_UPLOAD_BYTES + 1024 * 1024 + 1),
    }).status_code == 413
    assert not calls


def test_actual_upload_size_is_bounded(api, monkeypatch):
    client, calls, _ = api
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 8)
    response = client.post("/search/v2", files={"image": ("q.png", png(), "image/png")})
    assert response.status_code == 413
    assert not calls


def test_empty_request(api):
    client, calls, _ = api
    assert client.post("/search/v2").status_code == 400
    assert not calls


@pytest.mark.parametrize("ready,index", [
    (False, SimpleNamespace(ntotal=1)), (True, None), (True, SimpleNamespace(ntotal=0)),
])
def test_unready_or_empty_index_is_503(api, monkeypatch, ready, index):
    client, calls, _ = api
    monkeypatch.setattr(search.engine, "state", SimpleNamespace(ready=ready, index=index))
    assert client.post("/search/v2", data={"name": "x"}).status_code == 503
    assert not calls


def test_v1_and_v2_share_remote_ip_quota(api, monkeypatch):
    client, _, _ = api
    # Mutate the existing parsed limit, preserving the real decorators and IP key function.
    groups = [group for groups in limiter._route_limits.values() for group in groups]
    shared = [limit for limit in groups if limit.scope == "search"]
    assert len(shared) == 2
    for limit in shared:
        monkeypatch.setattr(limit, "limit", type(limit.limit)(2, 1))
    assert client.post("/search/v2", data={"name": "x"}).status_code == 200
    # Failed requests also consume the real shared bucket, without running CLIP.
    monkeypatch.setattr(search.engine.state, "ready", False)
    response = client.post("/search", files={"file": ("q.png", png(), "image/png")})
    assert response.status_code == 503
    response = client.post("/search/v2", data={"name": "x"})
    assert response.status_code == 429


def test_schema_is_documentation_only(api):
    client, _, _ = api
    document = client.get("/openapi.json").json()
    schema = document["paths"]["/search/v2"]["post"]["responses"]["200"]
    assert "SearchV2Response" in str(schema)
    route = next(route for route in search.router.routes if route.path == "/search/v2")
    assert route.response_model is None


def test_document_examples_match_response_schema():
    from backend.src.schemas.search_v2 import SearchV2Response

    contract = Path(__file__).resolve().parents[2] / "docs" / "MarkLens_API계약_v2.md"
    examples = re.findall(r"```json\s*(.*?)```", contract.read_text(encoding="utf-8"), re.S)
    assert len(examples) >= 2
    for example in examples:
        SearchV2Response.model_validate(json.loads(example))
