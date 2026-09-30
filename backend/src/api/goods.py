"""GET /goods/search, GET /goods/classes — 상품↔유사군 변환표 검색 (프론트-6 지정상품 입력 UI용).

/phonetic-search 와 같은 인증(X-API-Key)·IP 한도·요청 ID·로깅 패턴을 따른다. KIPRIS·CPU 모델과
무관한 로컬 메모리 조회(수 ms)라 워커 스레드 오프로드 없이 동기 함수로 둔다(FastAPI 가 스레드풀에서
실행). 변환표가 없으면 503 + 이유(core/goods.py state.error) — /name-check 가 KIPRIS 키 없이
503 을 내는 것과 같은 방식. 검색어 원문은 로그에 남기지 않는다(건수·시간만).
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status

from ..core import config, goods
from ..core.ratelimit import limiter
from ..schemas.goods import GoodsClass, GoodsClassesResponse, GoodsMatch, GoodsSearchResponse

router = APIRouter()
logger = logging.getLogger(__name__)

# 검색어 길이 상한(고시상품명칭 최장 항목이 40자 안팎)과 반환 건수·시작 위치 범위.
QUERY_MAX_LENGTH = 50
LIMIT_DEFAULT = 20
LIMIT_MAX = 50
OFFSET_MAX = 100_000  # 변환표 전체(91,591건)보다 큰 값이면 빈 목록


def _require_ready() -> None:
    if not goods.state.ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"상품 검색 데이터가 준비되지 않았습니다. {goods.state.error}".strip(),
        )


@router.get("/goods/search", response_model=GoodsSearchResponse)
@limiter.limit(config.GOODS_RATE_LIMIT)  # IP 기준 한도(기본 60/min) — 자동완성 호출 폭주 보호
def goods_search(
    request: Request,  # slowapi 데코레이터가 IP 추출에 사용
    q: Optional[str] = Query(
        None,
        max_length=QUERY_MAX_LENGTH,
        description="상품명 검색어(1~50자). 고시상품명칭 name 과 원 명칭(aliases)에 부분 일치. "
        "nice_class 가 있으면 생략 가능(그 류의 항목을 이름순으로 나열)",
    ),
    limit: int = Query(LIMIT_DEFAULT, ge=1, le=LIMIT_MAX, description="반환 건수"),
    offset: int = Query(0, ge=0, le=OFFSET_MAX, description="시작 위치(0부터) — 더 보기용"),
    nice_class: Optional[int] = Query(None, ge=1, le=45, description="류 번호로 좁히기"),
) -> GoodsSearchResponse:
    """상품명 부분 일치 검색, 또는 검색어 없이 한 류의 항목 나열.

    검색: 정확 일치 > 접두 > 부분 순이며, 원 명칭(alias)으로 잡히면 matched_alias 에 표기한다.
    나열(q 생략·공백 + nice_class): 그 류의 항목을 이름순으로 offset 부터 limit 개.
    q 도 nice_class 도 없으면 422.
    """
    _require_ready()
    query = (q or "").strip()
    if not query and nice_class is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="상품명 검색어(q, 1~50자) 또는 류 번호(nice_class, 1~45) 중 하나는 필요합니다.",
        )
    try:
        if query:
            matches, total, elapsed_ms = goods.search(query, limit, nice_class, offset)
        else:
            matches, total, elapsed_ms = goods.list_class(nice_class, offset, limit)  # type: ignore[arg-type]
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from None
    except Exception:
        logger.exception("goods-search 처리 중 서버 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="상품 검색 중 서버 오류가 발생했습니다.",
        ) from None

    logger.info(
        "goods-search: mode=%s matched=%d/%d limit=%d offset=%d class=%s %.1fms",
        "search" if query else "list",
        len(matches),
        total,
        limit,
        offset,
        nice_class,
        elapsed_ms,
    )
    return GoodsSearchResponse(
        query=query,
        matches=[
            GoodsMatch(
                name=match.name,
                nice_class=match.nice_class,
                similarity_codes=list(match.similarity_codes),
                matched_alias=match.matched_alias,
            )
            for match in matches
        ],
        total=total,
        offset=offset,
        source=goods.SOURCE,
    )


@router.get("/goods/classes", response_model=GoodsClassesResponse)
@limiter.limit(config.GOODS_RATE_LIMIT)
def goods_classes(request: Request) -> GoodsClassesResponse:
    """NICE 45개 류의 명칭과 변환표 항목 수 (류 선택 UI용, 정적 데이터)."""
    _require_ready()
    try:
        rows = goods.classes()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from None
    return GoodsClassesResponse(
        classes=[GoodsClass(**row) for row in rows],
        total_entries=goods.state.entry_count,
        source=goods.SOURCE,
    )
