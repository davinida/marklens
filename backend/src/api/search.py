"""POST /search — multipart 이미지 업로드 → top-K 검색 결과 + 등급."""

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

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

    # 1) 업로드 검증
    raw = await file.read()
    validation.validate_upload(file, raw)

    # 2) 검색 (engine 가 preprocess + encode + search + 결합 + 등급까지 수행)
    try:
        result = engine.run_search(raw, top_k=top_k)
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

    return _to_response(result)
