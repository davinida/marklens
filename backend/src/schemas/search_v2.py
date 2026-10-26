"""통합 검색 OpenAPI 계약. 런타임 응답 필터로 사용하지 않는다."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from .search import DatasetInfo

Grade = Literal["안전", "주의", "검토 권장", "위험"]
Score = Annotated[float, Field(ge=0, le=1)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class TypeDetail(ContractModel):
    text_ratio: Score
    fig_ratio: Score


class QueryType(ContractModel):
    type: Literal["문자", "도형", "결합-문자요부", "결합-도형요부"]
    source: Literal["ocr", "fallback", "user"]
    detail: TypeDetail | None
    suggested_name: str | None


class Overall(ContractModel):
    grade: Grade | None
    prob: Score | None
    caveats: list[str]
    query_type: QueryType
    visual_status: Literal[
        "STRONG_MATCH", "POSSIBLE_MATCH", "WEAK_MATCH", "NO_CLOSE_MATCH"
    ] | None


class Axes(ContractModel):
    x1: Score | None
    x2_text: Score | None
    x2_img: Score | None
    x3: Score | None
    x4: Score | None


class Contributions(ContractModel):
    X1: FiniteFloat
    X2: FiniteFloat
    X3: FiniteFloat
    X4: FiniteFloat
    요부: FiniteFloat


class Risk(ContractModel):
    prob: Score
    grade: Grade
    contributions: Contributions
    missing_adjustment: FiniteFloat
    figure_caveat: bool
    rule_triggers: list[str]


class RemovedToken(ContractModel):
    token: str
    reason: str
    side: Literal["query", "candidate", "both"]


class Salient(ContractModel):
    query_tokens: list[str]
    candidate_tokens: list[str]
    removed: list[RemovedToken]


class Goods(ContractModel):
    codes: list[str]
    jaccard: Score | None


class Candidate(ContractModel):
    id: str = Field(pattern=r"^[0-9]{13}$")
    title: str | None
    image_url: str | None
    type: Literal["문자", "도형", "결합"] | None
    applicant: str | None
    nice_classes: list[Annotated[int, Field(ge=1, le=45)]]
    axes: Axes
    risk: Risk
    salient: Salient
    goods: Goods


class GradeThresholds(ContractModel):
    주의: Score
    검토_권장: Score = Field(alias="검토 권장")
    위험: Score


class Thresholds(ContractModel):
    grade: GradeThresholds
    standalone: Axes
    figure: Score


class Pool(ContractModel):
    image: int = Field(ge=0)
    phonetic: int = Field(ge=0)
    spelling: int = Field(ge=0)
    semantic: int = Field(ge=0)
    goods: int = Field(ge=0)
    total: int = Field(ge=0)


class Meta(ContractModel):
    model_version: str
    grade_precision: Score
    thresholds: Thresholds
    pool: Pool
    elapsed_ms: int = Field(ge=0)


class SearchV2Response(ContractModel):
    api_version: Literal["2026-10-24"]
    research_beta: Literal[True]
    legal_conclusion: Literal[False]
    overall: Overall
    candidates: list[Candidate]
    meta: Meta
    dataset_info: DatasetInfo
    index_size: int = Field(ge=0)
    top_k_requested: int = Field(ge=1, le=20)
    top_k_returned: int = Field(ge=0, le=20)
