"""R12 시연 하드닝 단위 테스트 — X-API-Key 인증 · 레이트리밋 · CORS 파싱.

주의: 이 파일은 실엔진(CLIP/FAISS)을 절대 로드하지 않는다. 이 머신에서는
실모델 로딩이 access violation 을 일으키므로(test_api_contract 참조), 검증 대상인
'인증 의존성 / 레이트리밋 핸들러 / 설정 파싱'만 격리해서 테스트한다.
- auth: require_api_key 의존성을 붙인 최소 스텁 앱으로 검증 (엔진 무관).
- ratelimit: 낮은 한도의 스텁 앱으로 429 발생 + 한국어 메시지 확인.
- config: MARKLENS_CORS_ORIGINS 파싱을 모듈 reload 로 검증(원상 복구 포함).
"""

import importlib

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.src.core import config
from backend.src.core.auth import require_api_key
from backend.src.core.ratelimit import rate_limit_exceeded_handler

# ====================================================================
# X-API-Key 인증 의존성
# ====================================================================


def _build_auth_app() -> FastAPI:
    """require_api_key 를 붙인 보호 라우트 + 무인증 /health 스텁 앱."""
    app = FastAPI()

    @app.get("/protected", dependencies=[Depends(require_api_key)])
    def protected():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


def test_api_key_disabled_when_unset(monkeypatch):
    """MARKLENS_API_KEY 미설정이면 헤더 없이도 통과(무인증)."""
    monkeypatch.setattr(config, "API_KEY", "")
    client = TestClient(_build_auth_app())

    assert client.get("/protected").status_code == 200


def test_api_key_missing_header_rejected(monkeypatch):
    """키 설정 + 헤더 누락 → 401."""
    monkeypatch.setattr(config, "API_KEY", "secret-demo-key")
    client = TestClient(_build_auth_app())

    resp = client.get("/protected")
    assert resp.status_code == 401
    assert "X-API-Key" in resp.json()["detail"]


def test_api_key_wrong_header_rejected(monkeypatch):
    """키 설정 + 불일치 헤더 → 401."""
    monkeypatch.setattr(config, "API_KEY", "secret-demo-key")
    client = TestClient(_build_auth_app())

    resp = client.get("/protected", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


def test_api_key_correct_header_accepted(monkeypatch):
    """키 설정 + 일치 헤더 → 통과."""
    monkeypatch.setattr(config, "API_KEY", "secret-demo-key")
    client = TestClient(_build_auth_app())

    resp = client.get("/protected", headers={"X-API-Key": "secret-demo-key"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_health_never_requires_key(monkeypatch):
    """키를 설정해도 /health(의존성 미주입)는 무인증으로 통과 — 폴링 보장."""
    monkeypatch.setattr(config, "API_KEY", "secret-demo-key")
    client = TestClient(_build_auth_app())

    assert client.get("/health").status_code == 200


# ====================================================================
# 레이트리밋 (slowapi) — 낮은 한도 주입으로 429 발생만 가볍게 검증
# ====================================================================


def _build_ratelimit_app(limit: str) -> FastAPI:
    """실제 커스텀 429 핸들러를 붙인, 낮은 한도의 스텁 앱."""
    # 실제 limiter(ratelimit.py)와 동일한 기본 설정(headers 비활성).
    limiter = Limiter(key_func=get_remote_address)
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    @app.get("/ping")
    @limiter.limit(limit)
    async def ping(request: Request):
        return {"ok": True}

    return app


def test_rate_limit_allows_within_quota():
    """한도 내(2회) 요청은 모두 200."""
    client = TestClient(_build_ratelimit_app("2/minute"))
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200


def test_rate_limit_blocks_over_quota_with_korean_message():
    """한도(2/min) 초과분은 429 + 한국어 detail."""
    client = TestClient(_build_ratelimit_app("2/minute"))
    client.get("/ping")
    client.get("/ping")

    resp = client.get("/ping")
    assert resp.status_code == 429
    assert "요청이 너무 많습니다" in resp.json()["detail"]


# ====================================================================
# CORS 오리진 파싱
# ====================================================================


def test_cors_default_is_localhost_list():
    """기본값(미설정)은 로컬 프론트 오리진 리스트이며 '*' 하드코딩이 아니다."""
    assert isinstance(config.CORS_ALLOW_ORIGINS, list)
    assert config.CORS_ALLOW_ORIGINS  # 비어 있지 않음
    assert "*" not in config.CORS_ALLOW_ORIGINS


def test_cors_env_override_parsing(monkeypatch):
    """MARKLENS_CORS_ORIGINS(콤마 구분, 공백/빈 항목 정리)를 리스트로 파싱."""
    monkeypatch.setenv(
        "MARKLENS_CORS_ORIGINS", "https://a.example, https://b.example ,"
    )
    reloaded = importlib.reload(config)
    try:
        assert reloaded.CORS_ALLOW_ORIGINS == [
            "https://a.example",
            "https://b.example",
        ]
    finally:
        # 다른 테스트에 영향 주지 않도록 env 제거 후 모듈 원상 복구.
        monkeypatch.delenv("MARKLENS_CORS_ORIGINS", raising=False)
        importlib.reload(config)


def test_production_requires_private_backend_credentials():
    with pytest.raises(ValueError, match="MARKLENS_API_KEY"):
        config.Settings(
            MARKLENS_ENVIRONMENT="production",
            MARKLENS_API_KEY="",
            DATABASE_URL="",
        )


def test_production_settings_accept_explicit_private_boundary():
    settings = config.Settings(
        MARKLENS_ENVIRONMENT="production",
        MARKLENS_API_KEY="x" * 32,
        DATABASE_URL="postgresql://marklens:test@db:5432/marklens",
        MARKLENS_PUBLIC_RESULT_IMAGES=False,
    )
    assert settings.environment == "production"
    assert settings.storage_mode == "db"
    assert settings.public_result_images is False
