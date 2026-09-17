"""POST /phonetic-search — 입력 상표명과 로컬 DB 상표명의 X1 호칭(발음) 유사도 상위 후보.

/name-check 와 같은 본문 계약·인증·한도·로깅 패턴을 따르되, 외부 KIPRIS 호출 없이 로컬
발음 캐시(core/phonetic_search.py)만 사용한다. CPU 작업이라 /search 처럼 워커 스레드에서 돈다.
"""

import logging

import anyio
import anyio.to_thread
from fastapi import APIRouter, HTTPException, Request, status

from ..core import config, engine, phonetic_search, storage
from ..core.ratelimit import limiter
from ..schemas.phonetic_search import (
    PhoneticMatch,
    PhoneticQuery,
    PhoneticSearchParams,
    PhoneticSearchRequest,
    PhoneticSearchResponse,
)
from ..schemas.search import DatasetInfo

router = APIRouter()
logger = logging.getLogger(__name__)

# /search 와 같은 이유로 동시 실행 상한을 둔다(요청당 DB 전건 계산 ≈ 수백 ms CPU).
_limiter: anyio.CapacityLimiter | None = None


def _get_limiter() -> anyio.CapacityLimiter:
    global _limiter
    if _limiter is None:
        _limiter = anyio.CapacityLimiter(config.SEARCH_MAX_CONCURRENCY)
    return _limiter


def _image_url(image_key: str | None) -> str | None:
    """현재 게시된 인덱스에 있는 이미지만 공개 경로로 연결한다 (/name-check 와 같은 경계)."""
    if image_key and image_key in engine.state.image_path_set:
        return storage.public_url(image_key)
    return None


def _to_response(result: phonetic_search.PhoneticSearchResult) -> PhoneticSearchResponse:
    matches = [
        PhoneticMatch(
            rank=match.rank,
            similarity=match.similarity,
            출원번호=match.entry.application_number,
            상표한글명=match.entry.name,
            이미지URL=_image_url(match.entry.image_key),
            출원인=match.entry.applicant,
            류=list(match.entry.nice_classes),
        )
        for match in result.matches
    ]
    return PhoneticSearchResponse(
        query=PhoneticQuery(
            name=result.query,
            has_pronunciation=bool(result.query_candidates),
            candidates=list(result.query_candidates),
        ),
        matches=matches,
        searched_count=result.searched_count,
        excluded_no_pronunciation=result.excluded_no_pronunciation,
        dataset_info=DatasetInfo(**engine.state.dataset_info),
        params=PhoneticSearchParams(top_k=result.top_k, min_similarity=result.min_similarity),
        axis=phonetic_search.AXIS,
        note=phonetic_search.NOTE,
    )


@router.post("/phonetic-search", response_model=PhoneticSearchResponse)
@limiter.limit(config.PHONETIC_RATE_LIMIT)  # IP 기준 한도(기본 30/min) — 로컬 CPU 보호
async def phonetic_search_endpoint(
    request: Request,  # slowapi 데코레이터가 IP 추출에 사용
    payload: PhoneticSearchRequest,
) -> PhoneticSearchResponse:
    """입력 상표명과 발음(호칭)이 비슷한 등록상표 상위 후보를 반환한다 (X1 축, 참고 정보)."""
    if not engine.state.ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="엔진이 아직 초기화되지 않았습니다. 잠시 후 다시 시도하세요.",
        )
    top_k = payload.top_k if payload.top_k is not None else config.PHONETIC_TOP_K_DEFAULT
    min_similarity = config.PHONETIC_MIN_SIMILARITY

    try:
        async with _get_limiter():
            result = await anyio.to_thread.run_sync(
                lambda: phonetic_search.search(payload.name, top_k, min_similarity)
            )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from None
    except RuntimeError:
        logger.exception("phonetic-search 발음 캐시 준비 실패")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="발음 유사도 캐시가 준비되지 않았습니다. 잠시 후 다시 시도하세요.",
        ) from None
    except Exception:
        logger.exception("phonetic-search 처리 중 서버 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="발음 유사도 계산 중 서버 오류가 발생했습니다.",
        ) from None

    # 질의 원문은 로그에 남기지 않는다(/name-check 와 같은 정책) — 건수·시간만.
    logger.info(
        "phonetic-search: matched=%d/%d top_k=%d min=%.2f %.0fms",
        len(result.matches),
        result.searched_count,
        top_k,
        min_similarity,
        result.elapsed_ms,
    )
    try:
        return _to_response(result)
    except Exception:
        logger.exception("phonetic-search 응답 조립 중 계약 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="발음 유사도 응답을 만들 수 없습니다.",
        ) from None
