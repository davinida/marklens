"""GET /health — 서버 상태 + 리소스 로딩 여부."""

from fastapi import APIRouter

from ..core import engine
from ..schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """간단한 상태 점검 응답."""
    return HealthResponse(
        status="ok" if engine.state.ready else "loading",
        engine_ready=engine.state.ready,
        index_size=int(engine.state.index.ntotal) if engine.state.index else 0,
        trademark_count=engine.state.trademark_count,
        storage_mode=engine.state.storage_mode,
        artifact_generation_id=engine.state.artifact_generation_id,
    )
