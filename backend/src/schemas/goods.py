"""GET /goods/search · /goods/classes 응답 Pydantic 모델.

상품↔유사군 변환표 검색(프론트-6 지정상품 입력 UI용) — 필드는 shared/types/goods.ts 와 맞춘다.
"""

from typing import Optional

from pydantic import BaseModel, Field


class GoodsMatch(BaseModel):
    """검색 결과 1건. shared/types/goods.ts 의 GoodsMapEntry 에 matched_alias 를 더한 것."""

    name: str = Field(..., description="고시상품명칭. 제35류 6종 병합 항목은 합성 명칭")
    nice_class: int = Field(..., ge=1, le=45)
    similarity_codes: list[str] = Field(..., description="유사군 코드(1:N)")
    matched_alias: Optional[str] = Field(
        None, description="name 이 아니라 원 명칭(alias)으로 잡혔을 때 그 alias. 그 외 null"
    )


class GoodsSearchResponse(BaseModel):
    """GET /goods/search 응답 본문."""

    query: str = Field(..., description="앞뒤 공백을 제거한 검색어")
    matches: list[GoodsMatch]
    total: int = Field(..., description="limit 과 무관한 전체 일치 건수")
    source: str = Field(..., description="변환표 원본 판, 예: '고시상품명칭 13판(2026)'")


class GoodsClass(BaseModel):
    nice_class: int = Field(..., ge=1, le=45)
    title: str = Field(..., description="NICE 류 요약 명칭")
    count: int = Field(..., ge=0, description="변환표에 있는 이 류의 상품 수")


class GoodsClassesResponse(BaseModel):
    """GET /goods/classes 응답 본문 — 45개 류 전부."""

    classes: list[GoodsClass]
    total_entries: int = Field(..., ge=0)
    source: str
