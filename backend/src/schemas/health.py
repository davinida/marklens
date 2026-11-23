"""/health 응답 Pydantic 모델."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str  # "ok" / "loading" / "error"
    engine_ready: bool
    # 통합 검색을 할 수 있는지와 할 수 없는 이유 코드(계약 v2 §5-7) — false 면 HTTP 503
    search_ready: bool = True
    reason: str | None = None
    index_size: int
    trademark_count: int
    storage_mode: str = "file"  # "file" | "db" (백엔드-4 전환 상태 노출)
    artifact_generation_id: str | None = None
