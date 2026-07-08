"""/health 응답 Pydantic 모델."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str  # "ok" / "loading" / "error"
    engine_ready: bool
    index_size: int
    trademark_count: int
    storage_mode: str = "file"  # "file" | "db" (백엔드-4 전환 상태 노출)
