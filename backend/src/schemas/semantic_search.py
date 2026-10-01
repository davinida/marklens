"""POST /semantic-search 요청·응답 Pydantic 모델 (X3 관념 유사도, phonetic_search 와 같은 구조)."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .search import DatasetInfo

TOP_K_MAX = 5  # 반환 상한(작업 명세). 요청 top_k 도 이 값을 넘지 못한다.


class SemanticSearchRequest(BaseModel):
    """본문 기반 요청 — 질의가 URL·프록시 로그에 남지 않도록 /phonetic-search 와 같은 방식."""

    name: str = Field(..., min_length=1, max_length=100, description="비교할 상표명")
    top_k: Optional[int] = Field(
        None, ge=1, le=TOP_K_MAX, description="반환할 상위 후보 수. 미지정이면 5(상한)"
    )

    @field_validator("name")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("상표명이 비어 있습니다.")
        return value


class SemanticQuery(BaseModel):
    """입력 상표명의 관념 게이트 결과 (설명·디버그용)."""

    name: str
    has_meaning: bool = Field(..., description="X3 has_meaning — 정규화 토큰 중 실제 단어가 있는지")
    text: str = Field("", description="실제로 임베딩한 텍스트(정규화 토큰, 합성어는 띄어 씀)")


class SemanticMatch(BaseModel):
    """관념 유사 후보 1건. 한글 키는 /phonetic-search 응답 관례를 따른다."""

    model_config = ConfigDict(populate_by_name=True)

    rank: int
    score: float = Field(
        ..., description="X3 semantic_similarity 0~1 (재보정 코사인, 높을수록 유사)"
    )
    출원번호: str
    상표한글명: str
    이미지URL: Optional[str] = Field(
        None, description="현재 인덱스에 있는 이미지만 제공, 예: '/images/4020210070072.png'"
    )
    출원인: Optional[str] = None
    류: list[int] = Field(default_factory=list)


class SemanticSearchParams(BaseModel):
    top_k: int
    min_score: float


class SemanticSearchResponse(BaseModel):
    """POST /semantic-search 응답 본문."""

    query: SemanticQuery
    matches: list[SemanticMatch]
    searched_count: int = Field(..., description="관념이 있어 비교한 DB 레코드 수")
    excluded_no_meaning: int = Field(..., description="관념이 없어(조어·기호) 제외한 DB 레코드 수")
    dataset_info: DatasetInfo
    params: SemanticSearchParams
    threshold: float = Field(..., description="후보 점수 하한(params.min_score 와 같음)")
    axis: str = "X3"
    note: str = "관념(의미) 유사도만 반영한 참고 정보"
    model: str = Field("", description="임베딩 모델 이름(가짜 임베더는 'fake')")
