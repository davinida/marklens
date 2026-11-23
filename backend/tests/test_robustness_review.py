"""견고성·보안 점검(2026-11-23, docs/MarkLens_견고성_보안_점검.md)에서 찾은 항목의 회귀 시험.

지금 고쳐지지 않은 항목은 strict xfail 로 두고 사유에 점검 문서의 항목 번호를 적는다(고치면 XPASS 로
실패해 xfail 을 지우라고 알린다). 통과하는 시험은 지금 동작을 지키는 가드다. 실제 CLIP·KIPRIS
호출 없음. R-P0-1(2026-11-23, v1.4.2)·R-P1-1·R-P1-2·R-P1-3·R-P1-5·R-P1-6(2026-11-23,
fix/robustness-p1)은 고쳐 통과 시험이 됐다.
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
        holder["kwargs"] = kwargs
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


def test_blank_image_is_400_with_user_facing_korean(search_api):
    """R-P1-1(고침): 전처리의 빈 이미지 예외(BlankImageError — ValueError)는 422 영어가 아니라
    400 한국어."""
    client, holder = search_api
    holder["raise"] = multi_search.BlankImageError(PREPROCESS_BLANK)
    response = client.post("/search/v2", files={"image": ("white.png", _png(), "image/png")})
    detail = response.json()["detail"]
    assert response.status_code == 400
    assert re.search(r"[가-힣]", detail) and not re.search(r"[A-Za-z]{4,}", detail)


def test_blank_and_transparent_images_raise_blank_image_error():
    """R-P1-1: 하얀·완전 투명·거의 한 가지 색이면 BlankImageError(ValueError 를 이어받아 기존
    호출부는 그대로), 보통 로고는 통과."""
    from src.preprocess import validate_visual_content

    with pytest.raises(multi_search.BlankImageError):
        validate_visual_content(Image.new("RGB", (64, 64), "white"))
    with pytest.raises(multi_search.BlankImageError):
        validate_visual_content(Image.new("RGBA", (64, 64), (255, 0, 0, 0)))
    assert issubclass(multi_search.BlankImageError, ValueError)
    logo = Image.new("RGB", (64, 64), "white")
    logo.paste((200, 40, 40), (16, 16, 48, 48))
    validate_visual_content(logo)


def test_model_not_ready_detail_hides_internal_paths(search_api, caplog):
    """R-P1-3(고침): 응답은 고정 문구. 원인(경로·예외 원문)은 기동 때 multi_search.load_all 이
    서버 로그에 남기고, 요청 때 로그에는 예외 본문을 다시 쓰지 않는다(검색어가 섞일 수 있는 본문
    금지)."""
    client, holder = search_api
    cause = "계수 JSON: [Errno 2] No such file or directory: '/var/folders/x/missing.json'"
    holder["raise"] = multi_search.ModelNotReadyError(cause)
    with caplog.at_level(logging.ERROR):
        response = client.post("/search/v2", files={"name": (None, "블루커피")})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "/" not in detail and "Errno" not in detail and re.search(r"[가-힣]", detail)
    assert "준비되지 않아 503" in caplog.text and cause not in caplog.text


def _health_app(monkeypatch, multi_state) -> TestClient:
    app = FastAPI()
    app.include_router(health.router)
    monkeypatch.setattr(health.engine, "state", SimpleNamespace(
        ready=True, index=SimpleNamespace(ntotal=10), trademark_count=10, storage_mode="file",
        artifact_generation_id="x"))
    monkeypatch.setattr(multi_search, "state", multi_state)
    return TestClient(app)


def test_health_reports_unusable_search(monkeypatch):
    """R-P1-2(고침): 계수 JSON 을 못 읽어 검색을 할 수 없으면 /health 도 503 + 이유 코드(내부 경로
    없이)."""
    client = _health_app(monkeypatch, SimpleNamespace(
        model=None, distinct=object(), records=[object()], ready=True,
        error="계수 JSON: [Errno 2] No such file or directory: '/var/folders/x/missing.json'"))
    response = client.get("/health")
    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "error" and body["search_ready"] is False
    assert body["reason"] == "RISK_MODEL_UNAVAILABLE" and body["engine_ready"] is True
    assert "/var/" not in response.text and "Errno" not in response.text


@pytest.mark.parametrize("multi_state,reason", [
    (SimpleNamespace(model={}, distinct=None, records=[object()], ready=True, error="식별력"),
     "DISTINCTIVENESS_UNAVAILABLE"),
    (SimpleNamespace(model={}, distinct=object(), records=[], ready=True, error="후보 캐시"),
     "CANDIDATES_UNAVAILABLE"),
    (SimpleNamespace(model=None, distinct=None, records=[], ready=False, error=""),
     "SEARCH_LOADING"),
])
def test_health_reason_codes(monkeypatch, multi_state, reason):
    response = _health_app(monkeypatch, multi_state).get("/health")
    assert response.status_code == 503 and response.json()["reason"] == reason


def test_health_is_200_when_search_is_ready(fake_engine):
    """가드 — 가짜 모델 모드(MARKLENS_FAKE_ML)로 정상 기동하면 /health 200·search_ready true."""
    response = TestClient(app).get("/health")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok" and body["search_ready"] is True and body["reason"] is None


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
    detail = response.json()["detail"]
    assert not re.search(r"\bper\b|\bminute\b", detail)  # R-P1-5(고침)
    assert "1분에 1번까지" in detail  # 숫자는 설정한 한도에서


@pytest.fixture(scope="module")
def fake_engine(fake_ml_mode):
    """FAKE_ML 픽스처(더미 9건, 가짜 CLIP — 빨간 64×64 는 1번 레코드와 이미지 유사도 1.0)."""
    if not fake_ml_mode:
        pytest.skip("FAKE_ML 픽스처 전용")
    with TestClient(app):
        yield


def test_identical_logo_with_unrelated_name_is_flagged(fake_engine, monkeypatch):
    """R-P0-1(2026-11-23 고침, v1.4.2 logo_floor): 이름이 달라도 같은 로고(이미지 1.0)는 이미지만
    판단과 견줘 검토 권장 이상으로 남는다(전엔 이름 있는 판단만 받아 실제 DB 에선 상위 20 밖)."""
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    data = engine.multi_search(image=Image.new("RGB", (64, 64), (200, 40, 40)), name="블루커피",
                               top_k=5).to_dict()
    same = [c for c in data["candidates"] if c["axes"]["x2_img"] == 1.0]
    assert same, "같은 로고 후보가 상위 5 밖"
    assert GRADES.index(same[0]["risk"]["grade"]) >= GRADES.index("검토 권장"), same[0]["risk"]


def _same_logo(data: dict) -> dict:
    return next(c for c in data["candidates"] if c["axes"]["x2_img"] == 1.0)


def test_logo_floor_compares_with_image_only_even_when_goods_are_given(fake_engine, monkeypatch):
    """업종이 들어간 이름 없는 판단은 쓰지 않는다 — 같은 로고 후보는 이미지만 판단
    (noname:x2_whole)."""
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    data = engine.multi_search(image=Image.new("RGB", (64, 64), (200, 40, 40)), name="블루커피",
                               goods_codes=["S0101"], top_k=9).to_dict()
    top = _same_logo(data)
    assert "nameless_floor" in top["risk"]["rule_triggers"]
    assert top["risk"]["pattern"] == "noname:x2_whole" and top["risk"]["grade"] == "위험"


def test_logo_floor_skips_photo_queries(fake_engine, monkeypatch):
    """질의 이미지가 사진이면 견주지 않는다(사진 규칙 그대로)."""
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(multi_search, "is_photo_query", lambda embedding: True)
    data = engine.multi_search(image=Image.new("RGB", (64, 64), (200, 40, 40)), name="블루커피",
                               top_k=9).to_dict()
    assert all("nameless_floor" not in c["risk"]["rule_triggers"] for c in data["candidates"])


def test_logo_floor_is_off_without_the_model_flag(fake_engine, monkeypatch):
    """v1.4.1 JSON(logo_floor 없음)으로 돌리면 예전 동작 — 버전과 동작이 같이 간다."""
    import json as _json

    from src.model import risk_model as rm

    old = _json.loads(rm.V141_MODEL_PATH.read_text(encoding="utf-8"))
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(multi_search.state, "model", old)
    data = engine.multi_search(image=Image.new("RGB", (64, 64), (200, 40, 40)), name="블루커피",
                               top_k=9).to_dict()
    assert data["meta"]["model_version"] == "risk_model_v1.4.1"
    assert all("nameless_floor" not in c["risk"]["rule_triggers"] for c in data["candidates"])


@pytest.mark.parametrize("source,level,detail,expected", [
    ("user", "도형", None, "도형"), ("user", "문자", None, "문자"),
    ("user", "결합-문자요부", None, "결합-도형요부"),
    ("ocr", "결합-문자요부", {"text_ratio": 0.2, "fig_ratio": 0.5}, "결합-도형요부"),
    ("ocr", "결합-문자요부", {"text_ratio": 0.0, "fig_ratio": 0.7}, "도형"),
    ("fallback", "문자", None, "도형")])
def test_nameless_level_is_the_type_without_the_name(source, level, detail, expected):
    query_type = multi_search.QueryType(level, source, detail)
    assert multi_search.nameless_level(query_type) == expected


def test_search_v2_cleans_invisible_format_characters_in_name(search_api):
    """R-P1-6: 검색 API 가 이름의 서식 문자(Cf)를 지우고 NFC 로 맞춰 엔진에 넘긴다 — 서식 문자만이면
    이름 없음(다른 입력도 없으면 400)."""
    import unicodedata

    client, holder = search_api
    client.post("/search/v2", files={"name": (None, "블\u200b루커\u00ad피")})
    assert holder["kwargs"]["name"] == "블루커피"
    client.post("/search/v2", files={"name": (None, unicodedata.normalize("NFD", "블루커피"))})
    assert holder["kwargs"]["name"] == "블루커피"
    response = client.post("/search/v2", files={"name": (None, "\u200b\ufeff")})
    assert response.status_code == 400


def test_name_check_cleans_invisible_format_characters(fake_engine, monkeypatch):
    """R-P1-6: 상표명 확인도 같은 정리 — 서식 문자만이면 400, 섞여 있으면 지운 이름으로 묻는다
    (KIPRIS 는 모의 응답, 호출 0)."""
    from backend.src.api import namecheck

    seen: list[str] = []
    _mock_kipris(monkeypatch, seen)
    with pytest.raises(namecheck.HTTPException) as empty:
        namecheck._run_name_check("\u200b\u2060")
    assert empty.value.status_code == 400 and not seen
    try:
        namecheck._run_name_check("블\u200b루커피상표")
    except namecheck.HTTPException:
        pass
    assert seen and "블루커피상표" in httpx.URL(seen[0]).params.values()


def test_phonetic_and_semantic_search_clean_invisible_format_characters(fake_engine):
    """R-P1-6: 상표명 확인 패널의 발음·관념 검색도 같은 정리 — 서식 문자만이면 '상표명이 비어
    있습니다'(400), 섞여 있으면 지운 이름과 같은 결과."""
    from backend.src.core import phonetic_search, semantic_search

    with pytest.raises(ValueError):
        phonetic_search.search("\u200b", 5, 0.0)
    plain = phonetic_search.search("블루커피", 5, 0.0)
    mixed = phonetic_search.search("블\u200b루커피", 5, 0.0)
    assert [m.entry.name for m in mixed.matches] == [m.entry.name for m in plain.matches]
    with pytest.raises(ValueError):
        semantic_search.search("\ufeff", 5, 0.0)

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
