"""POST /phonetic-search 요청·응답 Pydantic 모델 (X1 호칭 유사도 최소 통합)."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .search import DatasetInfo


class PhoneticSearchRequest(BaseModel):
    """본문 기반 요청 — 질의가 URL·프록시 로그에 남지 않도록 /name-check 와 같은 방식."""

    name: str = Field(..., min_length=1, max_length=100, description="비교할 상표명")
    top_k: Optional[int] = Field(
        None,
        ge=1,
        le=20,
        description="반환할 상위 후보 수. 미지정이면 서버 기본값(MARKLENS_PHONETIC_TOP_K_DEFAULT)",
    )

    @field_validator("name")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("상표명이 비어 있습니다.")
        return value


class PhoneticQuery(BaseModel):
    """입력 상표명의 발음 후보 (설명·디버그용)."""

    name: str
    has_pronunciation: bool = Field(..., description="X1 이 발음 후보를 하나라도 만들었는지")
    candidates: list[str] = Field(
        default_factory=list, description="X1 pronunciation_candidates 결과"
    )


class PhoneticMatch(BaseModel):
    """발음 유사 후보 1건. 한글 키는 /search 응답 관례를 따른다."""

    model_config = ConfigDict(populate_by_name=True)

    rank: int
    similarity: float = Field(..., description="X1 phonetic_similarity 0~1 (높을수록 유사)")
    출원번호: str
    상표한글명: str
    이미지URL: Optional[str] = Field(
        None, description="현재 인덱스에 있는 이미지만 제공, 예: '/images/4020210070072.png'"
    )
    출원인: Optional[str] = None
    류: list[int] = Field(default_factory=list)


class PhoneticSearchParams(BaseModel):
    top_k: int
    min_similarity: float


class PhoneticSearchResponse(BaseModel):
    """POST /phonetic-search 응답 본문."""

    query: PhoneticQuery
    matches: list[PhoneticMatch]
    searched_count: int = Field(..., description="발음 후보가 있어 비교한 DB 레코드 수")
    excluded_no_pronunciation: int = Field(..., description="호칭이 없어 제외한 DB 레코드 수")
    dataset_info: DatasetInfo
    params: PhoneticSearchParams
    axis: str = "X1"
    note: str = "호칭(발음) 유사도만 반영한 참고 정보"
