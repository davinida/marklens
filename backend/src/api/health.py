"""GET /health — 서버 상태 + 리소스 로딩 여부 + 통합 검색을 할 수 있는지.

검색(POST /search/v2)을 할 수 없으면 503 과 이유 코드 reason(내부 경로·예외 원문 없음 — 원인은
서버 로그)을 낸다(계약 v2 §5-7, 견고성 점검 R-P1-2). 배포 헬스체크(deploy/*.Dockerfile)는 200 이
아니면 실패로 센다 — 모델 적재는 lifespan 안에서 끝나 기동 중에는 이 응답 자체가 없고(연결 거부),
HEALTHCHECK start-period 안의 실패는 세지 않으며, compose 의 restart: unless-stopped 는 unhealthy
로 재시작하지 않는다.
"""

from fastapi import APIRouter, Response

from ..core import engine, multi_search
from ..schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
def health(response: Response) -> HealthResponse:
    """간단한 상태 점검 응답. 검색을 할 수 없으면 503."""
    reason = multi_search.unavailable_reason()
    if reason is not None:
        response.status_code = 503
    return HealthResponse(
        status=("ok" if reason is None
                else "loading" if reason in ("ENGINE_LOADING", "SEARCH_LOADING") else "error"),
        engine_ready=engine.state.ready,
        search_ready=reason is None,
        reason=reason,
        index_size=int(engine.state.index.ntotal) if engine.state.index else 0,
        trademark_count=engine.state.trademark_count,
        storage_mode=engine.state.storage_mode,
        artifact_generation_id=engine.state.artifact_generation_id,
    )
