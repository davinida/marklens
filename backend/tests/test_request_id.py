"""Request ID propagation and sanitization contract."""

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.src.core.request_id import RequestIdMiddleware, request_id_var


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/")
    def current_request_id():
        return {"request_id": request_id_var.get()}

    return TestClient(app)


def test_valid_ingress_request_id_reaches_logs_and_response():
    with _client() as client:
        response = client.get("/", headers={"X-Request-ID": "edge-abc_123"})

    assert response.headers["X-Request-ID"] == "edge-abc_123"
    assert response.json()["request_id"] == "edge-abc_123"


def test_unsafe_request_id_is_replaced():
    with _client() as client:
        response = client.get("/", headers={"X-Request-ID": "bad id with spaces"})

    generated = response.headers["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{8}", generated)
    assert response.json()["request_id"] == generated
