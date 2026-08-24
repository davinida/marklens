"""POST /name-check 및 deprecated GET 호환용 Pydantic 모델."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class NameCheckRequest(BaseModel):
    """로그에 질의가 노출되지 않는 본문 기반 상표명 확인 요청."""

    name: str = Field(..., min_length=1, max_length=100, description="확인할 상표명")


class NameCheckCandidate(BaseModel):
    """상표명 검색 응답에 포함된 공개 서지정보 1건.

    KIPRIS의 원문 행을 그대로 직렬화하지 않고 화면에 필요한 필드만 허용한다.
    특히 일회성 ``ImagePath``/``ThumbnailPath``는 외부로 전달하지 않는다.
    """

    application_number: Optional[str] = Field(None, description="KIPRIS 상표 출원번호")
    registration_number: Optional[str] = Field(None, description="상표 등록번호")
    application_date: Optional[str] = Field(None, description="KIPRIS 원문의 출원일자")
    registration_date: Optional[str] = Field(None, description="KIPRIS 원문의 등록일자")
    title: Optional[str] = Field(None, description="KIPRIS에 기록된 상표명")
    status: Optional[str] = Field(None, description="출원·등록 행정상태")
    mark_type: Optional[str] = Field(None, description="KIPRIS 원문의 상표 구분")
    applicant: Optional[str] = Field(None, description="공개 상표공보의 출원인명")
    right_holder: Optional[str] = Field(None, description="공개 상표공보의 등록권리자명")
    nice_classes: list[str] = Field(default_factory=list, description="니스 상품류 코드")
    vienna_codes: list[str] = Field(default_factory=list, description="비엔나 도형분류 코드")
    similarity_codes: list[str] = Field(default_factory=list, description="상품 유사군 코드")
    exact_title_match: bool = Field(
        ..., description="대소문자·유니코드 표현을 정규화한 뒤 질의와 같은 상표명인지 여부"
    )
    is_registered: bool = Field(..., description="응답 시점의 상태가 '등록'인지 여부")
    local_image_url: Optional[str] = Field(
        None,
        description=(
            "현재 MarkLens 로컬 인덱스와 출원번호가 일치할 때만 제공되는 이미지 경로. "
            "KIPRIS 일회성 이미지 URL은 노출하지 않음"
        ),
    )


class NameCheckResponse(BaseModel):
    """상표명완전일치 검색 요약. 실시간 KIPRIS 조회 (캐시 적용)."""

    query: str
    total_found: int = Field(..., ge=0, description="검색된 전체 건수 (등록 외 상태 포함)")
    scanned_count: int = Field(..., ge=0, description="이번 응답에서 실제로 검사한 건수")
    registered_count: int = Field(
        ..., ge=0, description="ApplicationStatus == '등록' 건수"
    )
    exact_registered_count: int = Field(
        ..., ge=0, description="등록 중 Title 이 질의와 정확히 일치하는 건수"
    )
    exact_title_count: int = Field(
        ..., ge=0, description="상태와 무관하게 정규화된 Title 이 질의와 일치하는 검사 건수"
    )
    status_counts: dict[str, int] = Field(
        default_factory=dict,
        description="이번 응답에서 검사한 결과의 행정상태별 건수",
    )
    candidates: list[NameCheckCandidate] = Field(
        default_factory=list,
        description="이번 응답에서 검사한 상표 후보의 공개 서지정보",
    )
    candidates_returned: int = Field(
        ..., ge=0, description="candidates 배열에 실제로 반환한 건수"
    )
    candidates_truncated: bool = Field(
        ..., description="응답 크기 상한 때문에 검사 결과 일부를 후보 배열에서 생략했는지 여부"
    )
    complete: bool = Field(..., description="전체 검색 결과를 빠짐없이 검사했는지 여부")
    checked_at: datetime = Field(..., description="KIPRIS 조회 또는 캐시 생성 시각")
    source: str = Field(..., description="확인에 사용한 원천 데이터")
    cached: bool = Field(..., description="캐시 응답 여부 (월 호출 한도 보호)")
    message: str = Field(..., description="사용자용 한 줄 요약")
