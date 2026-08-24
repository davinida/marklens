"""
MarkLens FastAPI 백엔드 진입점.

실행 (project root 기준):
    cd ~/marklens && source ml/venv/bin/activate && \\
        uvicorn backend.src.main:app --reload

Swagger UI: http://127.0.0.1:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from slowapi.errors import RateLimitExceeded

from .core.logging_conf import setup_logging

# 앱/라우터 import 전에 로깅부터 구성 (import 시점 로그도 같은 포맷으로)
setup_logging()

from .api import health, namecheck, search  # noqa: E402
from .core import config, engine, kipris_client, storage  # noqa: E402
from .core.auth import require_api_key  # noqa: E402
from .core.ratelimit import limiter, rate_limit_exceeded_handler  # noqa: E402
from .core.request_id import RequestIdMiddleware  # noqa: E402

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    startup: 모델 + 인덱스 + 메타데이터 1회 로딩.
    실패 시 명확한 메시지와 함께 서버 기동을 중단합니다.
    """
    try:
        try:
            engine.load_all()
        except Exception:
            logger.exception("[FATAL] startup 리소스 로딩 실패")
            raise
        yield
    finally:
        # startup 중간 실패에도 이미 열린 DB/HTTP 자원을 정리한다.
        engine.shutdown()
        kipris_client.close_client()


app = FastAPI(
    title="MarkLens API",
    description=(
        "도형 상표 시각적 유사도 검색 API. "
        "업로드 이미지로 KIPRIS 선행상표 DB에서 Top-K 매칭을 찾고 4단계 등급을 반환."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# === 레이트리밋 (slowapi) ===
# limiter 를 app.state 에 두고(slowapi 데코레이터가 요청 시 참조), 한도 초과
# 예외(RateLimitExceeded)를 한국어 429 핸들러에 연결한다. 실제 한도 데코레이터는
# search/namecheck 라우터에 붙어 있다. RateLimitExceeded 는 HTTPException 하위라
# 아래 전역 Exception 핸들러보다 먼저(더 구체적인 타입으로) 디스패치된다.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


# === 전역 예외 핸들러 ===
# 엔드포인트별 HTTPException 은 그대로 두고, 어디서도 처리되지 않은 예외만
# 여기서 받아 (1) 요청 ID와 함께 traceback 로그 (2) 스택 미노출 JSON 500 반환.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("처리되지 않은 예외: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "서버 내부 오류가 발생했습니다. 로그의 요청 ID로 문의하세요."},
    )


# === 요청 ID ===
# 모든 응답에 X-Request-ID 헤더 + 요청 처리 중 로그 라인에 같은 ID 주입.
app.add_middleware(RequestIdMiddleware)

# === CORS ===
# 허용 오리진은 config.CORS_ALLOW_ORIGINS (env MARKLENS_CORS_ORIGINS, 기본 localhost:3000).
# 과거 하드코딩 "*" 제거 (감사보고서 작업3 1-2, R12).
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOW_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === 라우터 등록 ===
# X-API-Key 인증(require_api_key)은 MARKLENS_API_KEY 설정 시에만 활성(미설정이면 무인증).
# /health 는 무인증 유지 — 로드밸런서·부하테스트가 키 없이 상태를 폴링해야 함.
# 실제 처리 비용/외부 쿼터를 쓰는 /search·/name-check 에만 의존성을 주입한다.
app.include_router(health.router)
app.include_router(search.router, dependencies=[Depends(require_api_key)])
app.include_router(namecheck.router, dependencies=[Depends(require_api_key)])

# === 검색 결과 이미지 ===
# 디렉터리 전체를 정적 마운트하지 않고 현재 인덱스에 포함된 키만 제공한다.
# production 템플릿은 재배포 권리 확인 전까지 이 라우트를 비활성화한다.
if config.PUBLIC_RESULT_IMAGES:
    _images_dir = storage.local_path().resolve()
    _images_dir.mkdir(parents=True, exist_ok=True)

    @app.get(
        f"{config.IMAGES_URL_PREFIX}/{{image_key:path}}",
        include_in_schema=False,
        dependencies=[Depends(require_api_key)],
    )
    def indexed_image(image_key: str) -> FileResponse:
        if image_key not in engine.state.image_path_set:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        candidate = storage.local_path(image_key).resolve()
        if not candidate.is_relative_to(_images_dir) or not candidate.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(
            candidate,
            headers={
                "Cache-Control": "private, max-age=300",
                "X-Content-Type-Options": "nosniff",
            },
        )
