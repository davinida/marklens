"""
MarkLens FastAPI 백엔드 진입점.

실행 (project root 기준):
    cd ~/marklens && source ml/venv/bin/activate && \\
        uvicorn backend.src.main:app --reload

Swagger UI: http://127.0.0.1:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .core.logging_conf import setup_logging

# 앱/라우터 import 전에 로깅부터 구성 (import 시점 로그도 같은 포맷으로)
setup_logging()

from .api import health, namecheck, search  # noqa: E402
from .core import config, engine, kipris_client  # noqa: E402
from .core.paths import IMAGES_DIR  # noqa: E402
from .core.request_id import RequestIdMiddleware  # noqa: E402

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    startup: 모델 + 인덱스 + 메타데이터 1회 로딩.
    실패 시 명확한 메시지와 함께 서버 기동을 중단합니다.
    """
    try:
        engine.load_all()
    except Exception:
        # uvicorn 로그에 노출. 조용히 넘어가지 않음.
        logger.exception("[FATAL] startup 리소스 로딩 실패")
        raise
    yield
    # shutdown: DB 커넥션 풀 + 외부 API HTTP 클라이언트 정리
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
# 개발용 설정. 배포 시 좁힐 것 (실제 프론트엔드 origin으로 한정).
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOW_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === 라우터 등록 ===
app.include_router(health.router)
app.include_router(search.router)
app.include_router(namecheck.router)

# === 정적 파일 서빙 (검색 결과 이미지) ===
# 설계 결정: 응답에는 이미지 URL만 담고, 실제 이미지는 이 경로로 노출.
# 주의: StaticFiles 는 기본(check_dir=True)으로 생성 시점에 디렉토리 존재를
# 요구한다 — 디렉토리가 없으면 lifespan 의 친절한 [FATAL] 안내가 나오기 전에
# import 단계에서 죽는다 (2026-07-07 검증에서 확인). 먼저 보장해 준다.
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount(
    config.IMAGES_URL_PREFIX,
    StaticFiles(directory=str(IMAGES_DIR)),
    name="images",
)
