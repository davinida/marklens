"""GET /name-check 응답 Pydantic 모델 (백엔드-7)."""

from pydantic import BaseModel, Field


class NameCheckResponse(BaseModel):
    """상표명완전일치 검색 요약. 실시간 KIPRIS 조회 (캐시 적용)."""

    query: str
    total_found: int = Field(..., description="검색된 전체 건수 (등록 외 상태 포함)")
    registered_count: int = Field(..., description="ApplicationStatus == '등록' 건수")
    exact_registered_count: int = Field(
        ..., description="등록 중 Title 이 질의와 정확히 일치하는 건수"
    )
    cached: bool = Field(..., description="캐시 응답 여부 (월 호출 한도 보호)")
    message: str = Field(..., description="사용자용 한 줄 요약")
