"""POST /search — multipart 이미지 업로드 → top-K 검색 결과 + 등급."""

import functools

import anyio
import anyio.to_thread
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status

from ..core import config, engine, validation
from ..core.paths import IMAGES_DIR  # noqa: F401  (참조 의도 명시)
from ..core.config import IMAGES_URL_PREFIX
from ..schemas.search import (
    DatasetInfo,
    GradeInfo,
    SearchMatch,
    SearchResponse,
    TrademarkInfo,
)


router = APIRouter()


# CPU 바운드 검색의 동시 실행 상한 리미터.
# 이벤트 루프가 아닌 워커 스레드에서 실행되지만, CLIP 인코딩을 동시에 여러 개
# 돌리면 CPU 스래싱으로 전부 느려지므로 SEARCH_MAX_CONCURRENCY 로 묶는다.
# (이벤트 루프가 있어야 생성 가능한 anyio 버전이 있어 지연 생성)
_search_limiter: anyio.CapacityLimiter | None = None


def _get_search_limiter() -> anyio.CapacityLimiter:
    global _search_limiter
    if _search_limiter is None:
        _search_limiter = anyio.CapacityLimiter(config.SEARCH_MAX_CONCURRENCY)
    return _search_limiter


def _to_image_url(filename: str | None) -> str | None:
    """파일명을 정적 서빙 URL로 변환. 파일명이 없으면 None 반환."""
    if not filename:
        return None
    return f"{IMAGES_URL_PREFIX}/{filename}"


def _to_response(engine_result: dict) -> SearchResponse:
    """engine.run_search() 의 dict 결과를 Pydantic 응답 모델로 변환."""
    matches: list[SearchMatch] = []
    for m in engine_result["matches"]:
        tm_raw = m.get("trademark")
        tm_obj = TrademarkInfo(**tm_raw) if tm_raw else None
        matches.append(
            SearchMatch(
                rank=m["rank"],
                similarity=m["similarity"],
                이미지파일=m.get("이미지파일"),
                이미지URL=_to_image_url(m.get("이미지파일")),
                trademark=tm_obj,
            )
        )

    grade = GradeInfo(**engine_result["grade"])
    dataset_info = DatasetInfo(**engine.state.dataset_info)

    return SearchResponse(
        grade=grade,
        matches=matches,
        dataset_info=dataset_info,
        index_size=engine_result["index_size"],
        top_k_requested=engine_result["top_k_requested"],
        top_k_returned=engine_result["top_k_returned"],
    )


@router.post("/search", response_model=SearchResponse)
async def search_endpoint(
    request: Request,
    file: UploadFile = File(..., description="검색할 상표 이미지 (PNG/JPEG/WEBP)"),
    top_k: int = Query(
        default=config.DEFAULT_TOP_K,
        ge=config.MIN_TOP_K,
        le=config.MAX_TOP_K,
        description="반환할 상위 결과 개수",
    ),
) -> SearchResponse:
    """
    업로드 이미지로 KIPRIS 선행상표 DB를 검색합니다.

    응답: 4단계 등급, top-K 매칭(상표 상세 정보 포함), 데이터셋 안내.
    """
    if not engine.state.ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="엔진이 아직 초기화되지 않았습니다. 잠시 후 다시 시도하세요.",
        )
    # 빈 인덱스는 클라이언트 잘못이 아니라 서버 데이터 문제 → 503
    if engine.state.index is None or int(engine.state.index.ntotal) == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="검색 인덱스가 비어 있습니다. 데이터 적재 후 다시 시도하세요.",
        )

    # 0) Content-Length 선검사 — 본문을 메모리에 다 받기 전에 큰 요청을 차단.
    #    (헤더는 위조 가능하므로 아래 실측 크기 검증도 그대로 유지한다)
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit():
        # multipart 오버헤드가 있으므로 파일 상한보다 여유(1 MiB)를 두고 비교.
        if int(content_length) > config.MAX_UPLOAD_BYTES + 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"요청 본문이 너무 큽니다 (Content-Length: {content_length} bytes). "
                    f"파일 상한: {config.MAX_UPLOAD_BYTES} bytes."
                ),
            )

    # 1) 업로드 검증
    raw = await file.read()
    validation.validate_upload(file, raw)

    # 2) 검색 (engine 가 preprocess + encode + search + 결합 + 등급까지 수행)
    #    CPU 바운드(CLIP+FAISS) + 동기 DB 조회이므로 이벤트 루프를 막지 않도록
    #    워커 스레드로 오프로드한다. run_search 는 순수 동기 함수라 무수정 위임 가능.
    try:
        result = await anyio.to_thread.run_sync(
            functools.partial(engine.run_search, raw, top_k=top_k),
            limiter=_get_search_limiter(),
        )
    except ValueError as e:
        # preprocess/scoring 내부 검증 실패는 4xx로
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        # 그 외 예외는 서버 측 문제
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"검색 처리 중 오류: {e}",
        )

    # 3) 응답 조립 — 메타 계약 불일치(예: dataset_info 필드 누락)가 미처리 500 으로
    #    새지 않도록 감싼다. load_all() 이 기동 시점에 선검증하지만 이중 방어.
    try:
        return _to_response(result)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"응답 조립 중 메타데이터 계약 오류: {e}",
        )
