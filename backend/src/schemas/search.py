"""
/search 응답 Pydantic 모델.

설계 결정 1번 (API 응답에 데이터를 충분히 담는다, 무엇을 숨길지는 화면이 결정)
에 따라, 격차 A/B, 경고, 비엔나코드/류/유사군 등 풍부한 정보를 모두 포함합니다.

한글 필드명은 KIPRIS 원본 데이터 구조와 일관되도록 그대로 유지합니다.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TrademarkInfo(BaseModel):
    """KIPRIS 메타데이터에서 가져온 개별 상표의 상세 정보."""

    model_config = ConfigDict(populate_by_name=True)

    출원번호: str
    등록번호: Optional[str] = None
    출원일자: Optional[str] = None
    등록일자: Optional[str] = None
    상표한글명: Optional[str] = None
    상표영문명: Optional[str] = None
    상표구분: Optional[str] = None
    출원인: Optional[str] = None
    최종권리자: Optional[str] = None
    비엔나코드: list[str] = Field(default_factory=list)
    류: list[int] = Field(default_factory=list)
    유사군: list[str] = Field(default_factory=list)


class SearchMatch(BaseModel):
    """검색 결과 1건."""

    rank: int
    similarity: float = Field(..., description="raw IP 유사도 (값이 클수록 유사)")
    이미지파일: Optional[str] = Field(
        None, description="인덱스 메타의 image_paths[i], 예: '4020210070072.png'"
    )
    이미지URL: Optional[str] = Field(
        None, description="정적 파일 서빙 경로, 예: '/images/4020210070072.png'"
    )
    trademark: Optional[TrademarkInfo] = Field(
        None, description="KIPRIS 메타에서 매칭된 상표 정보. 매칭 실패 시 None."
    )


class GradeInfo(BaseModel):
    """교정 전 시각 유사도 판정과 한 릴리스용 레거시 등급 필드."""

    status_code: str = Field(..., description="정식 시각 유사도 상태 코드")
    status_name: str
    uncertain: bool
    uncertainty_reasons: list[str] = Field(default_factory=list)
    scored_candidate_count: int
    threshold_version: str
    scope: str = "visual_similarity_only"
    calibrated: bool = False
    legal_conclusion: bool = False

    grade_code: str = Field(
        ...,
        deprecated="status_code를 사용하세요. 다음 계약 버전에서 제거됩니다.",
    )
    grade_name: str = Field(
        ...,
        deprecated="status_name을 사용하세요. 다음 계약 버전에서 제거됩니다.",
    )
    message: str
    top1_similarity: float
    separability_a: float = Field(..., description="top1 - top2 격차")
    separability_b: float = Field(..., description="top1 - mean 격차")
    warnings: list[str] = Field(default_factory=list)


class DatasetInfo(BaseModel):
    """KIPRIS 데이터셋 안내 정보."""

    총_상표수: int
    출원일자_범위: str
    데이터_기준: str
    생성일자: str


class SearchResponse(BaseModel):
    """POST /search 의 응답 본문."""

    grade: GradeInfo
    matches: list[SearchMatch]
    dataset_info: DatasetInfo
    index_size: int = Field(..., description="인덱스에 들어있는 총 벡터 수")
    top_k_requested: int
    top_k_returned: int
    scoring_k: int = Field(
        ...,
        description="판정에 사용한 내부 후보 수. 표시 top_k와 독립적입니다.",
    )
    api_version: str = "2026-08-14"
    research_beta: bool = True
