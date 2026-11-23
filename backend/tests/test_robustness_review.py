"""견고성·보안 점검(2026-11-23, docs/MarkLens_견고성_보안_점검.md)에서 찾은 항목의 회귀 시험.

지금 고쳐지지 않은 항목은 strict xfail 로 두고 사유에 점검 문서의 항목 번호를 적는다(고치면 XPASS 로
실패해 xfail 을 지우라고 알린다). 통과하는 시험은 지금 동작을 지키는 가드다. 실제 CLIP·KIPRIS
호출 없음.
"""

import io
import logging
import re
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from PIL import Image
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.src.api import health, search
from backend.src.core import config, engine, kipris_client, multi_search
from backend.src.core.ratelimit import limiter, rate_limit_exceeded_handler
from backend.src.main import app

GRADES = ["안전", "주의", "검토 권장", "위험"]
PREPROCESS_BLANK = ("Image has insufficient visual contrast; upload a non-blank mark "
                    "(range=0.00, stddev=0.00)")


def _png(size=(64, 64), color="white") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def search_api(monkeypatch):
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.include_router(search.router)
    holder = {"raise": None}

    def run(**kwargs):
        if holder["raise"] is not None:
            raise holder["raise"]
        return SimpleNamespace(to_dict=lambda: {"overall": {}, "candidates": []})

    monkeypatch.setattr(search.engine, "multi_search", run)
    monkeypatch.setattr(search.engine, "state",
                        SimpleNamespace(ready=True, index=SimpleNamespace(ntotal=1)))
    monkeypatch.setattr(search, "_search_limiter", None)
    limiter.reset()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, holder
    limiter.reset()


@pytest.mark.xfail(strict=True, reason="R-P1-1: 하얀·완전 투명 이미지가 계약 §5-1 의 400 대신 "
                                       "422 + 영어 전처리 문구")
def test_blank_image_is_400_with_user_facing_korean(search_api):
    client, holder = search_api
    holder["raise"] = ValueError(PREPROCESS_BLANK)
    response = client.post("/search/v2", files={"image": ("white.png", _png(), "image/png")})
    detail = response.json()["detail"]
    assert response.status_code == 400
    assert re.search(r"[가-힣]", detail) and not re.search(r"[A-Za-z]{4,}", detail)


@pytest.mark.xfail(strict=True, reason="R-P1-3: 모델 적재 실패 503 문구에 내부 경로·파이썬 "
                                       "오류가 그대로 나감")
def test_model_not_ready_detail_hides_internal_paths(search_api):
    client, holder = search_api
    holder["raise"] = multi_search.ModelNotReadyError(
        "계수 JSON: [Errno 2] No such file or directory: '/var/folders/x/missing.json'")
    response = client.post("/search/v2", files={"name": (None, "블루커피")})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "/" not in detail and "Errno" not in detail


@pytest.mark.xfail(strict=True, reason="R-P1-2: 모델 JSON 적재에 실패해도 /health 는 status ok·"
                                       "engine_ready true")
def test_health_reports_unusable_search(monkeypatch):
    app = FastAPI()
    app.include_router(health.router)
    monkeypatch.setattr(health.engine, "state", SimpleNamespace(
        ready=True, index=SimpleNamespace(ntotal=10), trademark_count=10, storage_mode="file",
        artifact_generation_id="x"))
    monkeypatch.setattr(multi_search, "state", SimpleNamespace(model=None, ready=False,
                                                              error="계수 JSON: 깨짐"))
    body = TestClient(app).get("/health").json()
    assert body["status"] != "ok" or body["engine_ready"] is False


@pytest.mark.xfail(strict=True, reason="R-P1-5: 429 문구 끝에 slowapi 영어 한도 문자열"
                                       "(예: 10 per 1 minute)")
def test_rate_limit_message_has_no_english_fragment():
    own = Limiter(key_func=get_remote_address)
    app = FastAPI()
    app.state.limiter = own
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    @app.get("/ping")
    @own.limit("1/minute")
    async def ping(request: Request):
        return {"ok": True}

    client = TestClient(app)
    client.get("/ping")
    response = client.get("/ping")
    assert response.status_code == 429
    assert not re.search(r"\bper\b|\bminute\b", response.json()["detail"])


@pytest.fixture(scope="module")
def fake_engine(fake_ml_mode):
    """FAKE_ML 픽스처(더미 9건, 가짜 CLIP — 빨간 64×64 는 1번 레코드와 이미지 유사도 1.0)."""
    if not fake_ml_mode:
        pytest.skip("FAKE_ML 픽스처 전용")
    with TestClient(app):
        yield


@pytest.mark.xfail(strict=True, reason="R-P0-1: 이름이 있으면 같은 로고(이미지 1.0) 후보가 "
                                       "이름 있는 판단만 받아 낮은 등급 — 실제 DB 에선 상위 20 "
                                       "밖으로 밀려 안 보임")
def test_identical_logo_with_unrelated_name_is_flagged(fake_engine, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    data = engine.multi_search(image=Image.new("RGB", (64, 64), (200, 40, 40)), name="블루커피",
                               top_k=5).to_dict()
    same = [c for c in data["candidates"] if c["axes"]["x2_img"] == 1.0]
    assert same, "같은 로고 후보가 상위 5 밖"
    assert GRADES.index(same[0]["risk"]["grade"]) >= GRADES.index("검토 권장"), same[0]["risk"]


def test_identical_logo_without_name_is_danger(fake_engine, monkeypatch):
    """가드 — 이름 없이 같은 로고만 넣으면 지금도 '위험'(이름 없는 판단, 계약 §3-2)."""
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    data = engine.multi_search(image=Image.new("RGB", (64, 64), (200, 40, 40)),
                               top_k=5).to_dict()
    top = data["candidates"][0]
    assert top["axes"]["x2_img"] == 1.0 and top["risk"]["grade"] == "위험"


def test_unsafe_image_upload_errors_do_not_leak_internals(search_api):
    """깨진 파일·위장 형식 — 지금 동작(400/415, 내부 경로·스택 없음)을 지키는 가드."""
    client, _ = search_api
    broken = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, "image/png")
    disguised = (b"GIF89a" + b"\x00" * 40, "image/png")
    for raw, mime in (broken, disguised):
        response = client.post("/search/v2", files={"image": ("x.png", raw, mime)})
        assert response.status_code in (400, 415)
        assert "/" not in response.json()["detail"] and "Traceback" not in response.text


def _mock_kipris(monkeypatch, seen: list[str]) -> None:
    body = ("<?xml version='1.0' encoding='UTF-8'?><response><header><resultCode>00</resultCode>"
            "<resultMsg>OK</resultMsg></header><body><items><TotalSearchCount>0</TotalSearchCount>"
            "</items></body></response>")

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text=body, headers={"content-type": "application/xml"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(kipris_client, "_get_client", lambda: client)
    monkeypatch.setattr(kipris_client, "ACCESS_KEY", "ROBUSTNESS-FAKE-KEY-0000")


@pytest.mark.parametrize("name", ["블루 & 커피=#%+?/", "a&accessKey=STOLEN", "STAR\r\nBUCKS",
                                  "☕<script>"])
def test_name_check_encodes_user_input_in_kipris_query(monkeypatch, name):
    """상표명 확인 — 사용자 입력이 KIPRIS 질의 문자열에 안전하게 인코딩된다(모의 응답, 호출 0)."""
    seen: list[str] = []
    _mock_kipris(monkeypatch, seen)
    try:
        kipris_client.name_match_search(name)
    except kipris_client.KiprisError:
        pass
    assert seen, "요청이 만들어지지 않음"
    query = httpx.URL(seen[0]).params
    assert query.get_list("accessKey") == ["ROBUSTNESS-FAKE-KEY-0000"]  # 입력이 키를 덮지 못함
    assert any(value == name for value in query.values())  # 원문 그대로 한 값으로 전달


def test_kipris_request_url_is_not_logged_at_info(monkeypatch, caplog):
    """KIPRIS 요청 URL 에는 키·상표명이 들어 있다 — INFO 로그에 남지 않아야 한다(httpx 로거
    WARNING)."""
    from backend.src.core.logging_conf import setup_logging

    setup_logging()
    seen: list[str] = []
    _mock_kipris(monkeypatch, seen)
    with caplog.at_level(logging.INFO):
        try:
            kipris_client.name_match_search("비밀상표후보")
        except kipris_client.KiprisError:
            pass
    text = caplog.text
    assert "ROBUSTNESS-FAKE-KEY-0000" not in text and "비밀상표후보" not in text
