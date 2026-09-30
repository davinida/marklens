"""POST /semantic-search — 입력 상표명과 로컬 DB 상표명의 X3 관념(의미) 유사도 상위 후보.

/phonetic-search 와 같은 본문 계약·인증·한도·요청 ID·로깅 패턴을 따르되, 로컬 임베딩 캐시
(core/semantic_search.py)만 사용한다. CPU 작업(질의 임베딩 1회 + 행렬 곱)이라 워커 스레드에서 돈다.
X3 가 꺼져 있거나(MARKLENS_X3_ENABLED=0) 모델을 못 불러왔으면 503 + 이유.
"""

import logging

import anyio
import anyio.to_thread
from fastapi import APIRouter, HTTPException, Request, status

from ..core import config, engine, semantic_search, storage
from ..core.ratelimit import limiter
from ..schemas.search import DatasetInfo
from ..schemas.semantic_search import (
    SemanticMatch,
    SemanticQuery,
    SemanticSearchParams,
    SemanticSearchRequest,
    SemanticSearchResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# /phonetic-search 와 같은 이유로 동시 실행 상한을 둔다(요청당 임베딩 1회 ≈ 수 ms + 행렬 곱).
_limiter: anyio.CapacityLimiter | None = None


def _get_limiter() -> anyio.CapacityLimiter:
    global _limiter
    if _limiter is None:
        _limiter = anyio.CapacityLimiter(config.SEARCH_MAX_CONCURRENCY)
    return _limiter


def _image_url(image_key: str | None) -> str | None:
    """현재 게시된 인덱스에 있는 이미지만 공개 경로로 연결한다 (/phonetic-search 와 같은 경계)."""
    if image_key and image_key in engine.state.image_path_set:
        return storage.public_url(image_key)
    return None


def _to_response(result: semantic_search.SemanticSearchResult) -> SemanticSearchResponse:
    matches = [
        SemanticMatch(
            rank=match.rank,
            score=match.score,
            출원번호=match.entry.application_number,
            상표한글명=match.entry.name,
            이미지URL=_image_url(match.entry.image_key),
            출원인=match.entry.applicant,
            류=list(match.entry.nice_classes),
        )
        for match in result.matches
    ]
    return SemanticSearchResponse(
        query=SemanticQuery(
            name=result.query, has_meaning=result.has_meaning, text=result.query_text
        ),
        matches=matches,
        searched_count=result.searched_count,
        excluded_no_meaning=result.excluded_no_meaning,
        dataset_info=DatasetInfo(**engine.state.dataset_info),
        params=SemanticSearchParams(top_k=result.top_k, min_score=result.min_score),
        threshold=result.min_score,
        axis=semantic_search.AXIS,
        note=semantic_search.NOTE if result.has_meaning else semantic_search.NOTE_NO_MEANING,
        model=result.model,
    )


def _require_enabled() -> None:
    if not semantic_search.state.enabled or (
        not semantic_search.state.ready and semantic_search.state.error
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"관념 유사도 검색을 쓸 수 없습니다. {semantic_search.state.error}".strip(),
        )


@router.post("/semantic-search", response_model=SemanticSearchResponse)
@limiter.limit(config.X3_RATE_LIMIT)  # IP 기준 한도(기본 30/min) — /phonetic-search 와 같은 정책
async def semantic_search_endpoint(
    request: Request,  # slowapi 데코레이터가 IP 추출에 사용
    payload: SemanticSearchRequest,
) -> SemanticSearchResponse:
    """입력 상표명과 관념(의미)이 비슷한 등록상표 상위 후보를 반환한다 (X3 축, 참고 정보)."""
    if not engine.state.ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="엔진이 아직 초기화되지 않았습니다. 잠시 후 다시 시도하세요.",
        )
    _require_enabled()
    top_k = payload.top_k if payload.top_k is not None else semantic_search.TOP_K_DEFAULT
    min_score = config.X3_MIN_SCORE

    try:
        async with _get_limiter():
            result = await anyio.to_thread.run_sync(
                lambda: semantic_search.search(payload.name, top_k, min_score)
            )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from None
    except RuntimeError as e:
        logger.warning("semantic-search 캐시 준비 안 됨: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"관념 유사도 검색을 쓸 수 없습니다. {e}".strip(),
        ) from None
    except Exception:
        logger.exception("semantic-search 처리 중 서버 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="관념 유사도 계산 중 서버 오류가 발생했습니다.",
        ) from None

    # 질의 원문은 로그에 남기지 않는다(/phonetic-search 와 같은 정책) — 건수·시간만.
    logger.info(
        "semantic-search: has_meaning=%s matched=%d/%d top_k=%d min=%.2f %.0fms",
        result.has_meaning,
        len(result.matches),
        result.searched_count,
        top_k,
        min_score,
        result.elapsed_ms,
    )
    try:
        return _to_response(result)
    except Exception:
        logger.exception("semantic-search 응답 조립 중 계약 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="관념 유사도 응답을 만들 수 없습니다.",
        ) from None
