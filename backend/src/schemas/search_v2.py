"""통합 검색 OpenAPI 계약. 런타임 응답 필터로 사용하지 않는다."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from .dataset import DatasetInfo

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
    # 전체 등급을 정한 판단의 계수 집합("noname:…" = 이름 없는 판단 — 화면은 위험도 %를 숨긴다)
    pattern: str | None
    caveats: list[str]
    query_type: QueryType
    visual_status: Literal[
        "STRONG_MATCH", "POSSIBLE_MATCH", "WEAK_MATCH", "NO_CLOSE_MATCH"
    ] | None
    # 유명 상표 확인의 바닥이 전체 등급(grade)을 정했는가 — 유명 상표 확인이 켜진 서버
    # (v1.4.7)만 싣는다
    famous_floor: bool | None = None


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
    # 계수 집합: base·x2_whole·x4·x2_whole+x4(이름 있는 판단) / noname:x2_whole·noname:x2_whole+x4
    pattern: str


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
    # 유명 상표 등록부의 표장("관련 없음" 제외)이면 그 브랜드 — 해당할 때만 싣는다(v1.4.7)
    famous_brand: str | None = None


class FamousLogo(ContractModel):
    id: str = Field(pattern=r"^[0-9]{13}$")  # 대표 로고의 출원번호
    image_url: str | None  # 후보의 image_url 과 같은 꼴


class FamousMatch(ContractModel):
    brand: str
    level: Literal["강함", "약함", "설명적 사용"]
    basis: Literal["이름", "로고", "이미지 속 글자"]
    notation: str | None  # 일치한 표기(로고 일치는 null)
    matched_text: str | None  # 질의에서 맞은 글자(로고 일치는 null)
    protection: Literal["업종 불문", "같은·가까운 업종 중심"]
    goods_overlap: bool | None  # 업종 겹침(업종이 없거나 로고 일치면 null)
    floor: Literal["위험", "검토 권장"] | None  # 이 일치가 주는 전체 등급 바닥
    logos: list[FamousLogo]  # 그 브랜드의 대표 로고(현재 먼저, 최대 2)


class Famous(ContractModel):
    """유명 상표 확인(계약 v2 §2-6) — 유명 상표 확인이 켜진 서버(v1.4.7)만 싣는다."""

    status: Literal["checked", "unavailable"]  # 확인함 | 확인하지 못함
    brand_count: int = Field(ge=0)  # 등록부 브랜드 수
    matches: list[FamousMatch]  # 가장 강한 것부터 최대 2개 브랜드


class NameWord(ContractModel):
    word: str  # 엔진의 낱말 꼴(소문자·문자 종류 경계 분리 — salient 의 token 과 같은 꼴)
    distinctive: bool  # 식별력이 있다고 본 낱말(유명 브랜드 예외 포함)
    # 식별력이 없을 때만 — 화면용 사유 분류
    category: Literal["상품 이름", "성질·품질", "흔히 쓰는 말", "지역 이름", "흔한 성·이름",
                      "짧고 흔한 글자", "그 밖"] | None
    reason: str  # 엔진의 사유 원문("·" 로 이음 — salient.removed[].reason 과 같은 꼴)


class NameWords(ContractModel):
    """질의 이름의 낱말별 식별력(계약 v2 §2-7) — 이름이 있는 질의만 싣는다. 질의의 이름과 질의의
    업종만으로 본 판정이다(후보와 견줄 때의 쌍별 결과는 candidates[].salient)."""

    generic: Literal["all", "some", "none"]  # 식별력 없는 낱말이 전부 | 일부 | 없음
    words: list[NameWord] = Field(max_length=6)  # 이름 순서, 같은 낱말은 한 번, 최대 6
    more: int = Field(ge=0)  # 싣지 않은 낱말 수
    more_generic: int = Field(ge=0)  # 그 가운데 식별력 없는 낱말 수


class GradeThresholds(ContractModel):
    주의: Score
    검토_권장: Score = Field(alias="검토 권장")
    위험: Score


class NamelessGradeThresholds(ContractModel):
    """이름 없는 계수 집합의 등급 하한 — null 이면 위험도로는 그 등급에 닿지 않는다."""

    주의: Score | None
    검토_권장: Score | None = Field(alias="검토 권장")
    위험: Score | None


class Thresholds(ContractModel):
    grade: GradeThresholds
    nameless: dict[str, NamelessGradeThresholds]  # 키 = risk.pattern("noname:…")
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
    famous: Famous | None = None
    name_words: NameWords | None = None
    candidates: list[Candidate]
    meta: Meta
    dataset_info: DatasetInfo
    index_size: int = Field(ge=0)
    top_k_requested: int = Field(ge=1, le=20)
    top_k_returned: int = Field(ge=0, le=20)
