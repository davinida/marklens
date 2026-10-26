"""POST /search — multipart 이미지 업로드 → top-K 검색 결과 + 등급."""

import logging
import re

import anyio
import anyio.to_thread
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from starlette.datastructures import UploadFile as StarletteUploadFile

from ..core import config, engine, multi_search, storage, validation
from ..core.ratelimit import limiter
from ..schemas.search import (
    DatasetInfo,
    GradeInfo,
    SearchMatch,
    SearchResponse,
    TrademarkInfo,
)
from ..schemas.search_v2 import SearchV2Response

router = APIRouter()
logger = logging.getLogger(__name__)


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
                이미지URL=storage.public_url(m.get("이미지파일")),
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
        scoring_k=engine_result["scoring_k"],
    )


@router.post("/search", response_model=SearchResponse)
@limiter.shared_limit(config.SEARCH_RATE_LIMIT, scope="search")
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
                status_code=413,
                detail=(
                    f"요청 본문이 너무 큽니다 (Content-Length: {content_length} bytes). "
                    f"파일 상한: {config.MAX_UPLOAD_BYTES} bytes."
                ),
            )

    # 1) 업로드 헤더와 실측 크기 검증. UploadFile 전체를 한 번에 읽지 않고
    #    상한+1 바이트까지만 읽어 메모리 사용량을 제한한다.
    validation.validate_content_type(file)

    # 2) 디코딩과 검색을 같은 동시성 슬롯 안에서 수행한다. 검증된 PIL 객체를
    #    엔진에 넘기므로 정상 입력을 두 번 디코딩하지 않는다.
    try:
        async with _get_search_limiter():
            raw = await file.read(config.MAX_UPLOAD_BYTES + 1)
            validation.validate_upload_size(raw)

            def decode_and_search() -> dict:
                image = validation.validate_and_decode(raw)
                return engine.run_search(image, top_k=top_k)

            result = await anyio.to_thread.run_sync(decode_and_search)
    except HTTPException:
        raise
    except ValueError as e:
        # preprocess/scoring 내부 검증 실패는 4xx로
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception:
        logger.exception("검색 처리 중 서버 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="검색 처리 중 서버 오류가 발생했습니다.",
        ) from None

    # 3) 응답 조립 — 메타 계약 불일치(예: dataset_info 필드 누락)가 미처리 500 으로
    #    새지 않도록 감싼다. load_all() 이 기동 시점에 선검증하지만 이중 방어.
    try:
        return _to_response(result)
    except Exception:
        logger.exception("검색 응답 조립 중 계약 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="검색 응답을 만들 수 없습니다.",
        ) from None


@router.post(
    "/search/v2", response_model=None,
    responses={200: {"model": SearchV2Response}},
    openapi_extra={"requestBody": {"content": {"multipart/form-data": {"schema": {
        "type": "object", "properties": {
            "image": {"type": "string", "format": "binary"},
            "name": {"type": "string", "maxLength": 100},
            "goods_codes": {"type": "array", "items": {"type": "string"}},
            "type_override": {"type": "string", "enum": ["문자", "도형", "결합"]},
        },
    }}}}},
)
@limiter.shared_limit(config.SEARCH_RATE_LIMIT, scope="search")
async def search_v2_endpoint(
    request: Request,
    top_k: int = Query(default=5, ge=1, le=20),
) -> dict:
    """통합 검색. 응답 모델은 문서용이며 엔진의 결과를 그대로 반환한다."""
    values = request.query_params.getlist("top_k")
    if len(values) > 1 or (values and not re.fullmatch(r"[0-9]+", values[0])):
        raise HTTPException(422, "top_k는 1~20 정수 하나여야 합니다.")
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > config.MAX_UPLOAD_BYTES + 1024 * 1024:
        raise HTTPException(413, "요청 본문이 너무 큽니다.")
    try:
        form = await request.form()
    except Exception:
        raise HTTPException(400, "multipart 폼을 읽을 수 없습니다.") from None
    try:
        for field in ("image", "name", "type_override"):
            if len(form.getlist(field)) > 1:
                raise HTTPException(422, f"{field}는 하나만 보내야 합니다.")
        for field in ("name", "goods_codes", "type_override"):
            if any(not isinstance(value, str) for value in form.getlist(field)):
                raise HTTPException(422, f"{field}는 텍스트여야 합니다.")
        image_file = form.get("image")
        if image_file is not None and not isinstance(image_file, StarletteUploadFile):
            raise HTTPException(415, "image는 파일이어야 합니다.")
        name = (form.get("name") or "").strip() or None
        if name and len(name) > 100:
            raise HTTPException(422, "name은 100자 이하여야 합니다.")
        goods = list(dict.fromkeys(
            code.strip().upper()
            for value in form.getlist("goods_codes") for code in value.split(",")
            if code.strip()
        ))
        if len(goods) > 60 or any(not re.fullmatch(r"[GS][0-9]{4,6}", c) for c in goods):
            raise HTTPException(422, "goods_codes는 G/S와 숫자 4~6자리 코드 최대 60개입니다.")
        override = form.get("type_override")
        if override is not None and override not in {"문자", "도형", "결합"}:
            raise HTTPException(422, "type_override는 문자·도형·결합 중 하나여야 합니다.")
        if image_file is None and not name and not goods:
            raise HTTPException(400, "image, name, goods_codes 중 하나는 있어야 합니다.")
        if not engine.state.ready:
            raise HTTPException(503, "Engine 이 아직 초기화되지 않았습니다.")
        if engine.state.index is None or int(engine.state.index.ntotal) == 0:
            raise HTTPException(503, "검색 인덱스가 비어 있습니다.")
        if image_file is not None:
            validation.validate_content_type(image_file)
        async with _get_search_limiter():
            raw = None
            if image_file is not None:
                raw = await image_file.read(config.MAX_UPLOAD_BYTES + 1)
                validation.validate_upload_size(raw)

            def decode_and_search_v2() -> dict:
                try:
                    image = validation.validate_and_decode(raw) if raw is not None else None
                except ValueError:
                    raise HTTPException(400, "이미지를 디코딩할 수 없습니다.") from None
                # OCR timeout 후에도 엔진의 작업자가 같은 PIL 객체를 사용할 수 있다.
                # 수명은 엔진/작업자의 참조에 맡기고 응답 시점에 닫지 않는다.
                return engine.multi_search(
                    image=image, name=name, goods_codes=goods or None,
                    type_override=override, top_k=top_k,
                ).to_dict()

            return await anyio.to_thread.run_sync(decode_and_search_v2)
    except HTTPException:
        raise
    except multi_search.EmptyQueryError:
        raise HTTPException(400, "image, name, goods_codes 중 하나는 있어야 합니다.") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except multi_search.ModelNotReadyError as exc:
        raise HTTPException(503, str(exc)) from None
    except RuntimeError as exc:
        if str(exc) == "Engine 이 아직 초기화되지 않았습니다.":
            raise HTTPException(503, str(exc)) from None
        logger.error("통합 검색 처리 중 서버 오류 (RuntimeError)")
        raise HTTPException(500, "검색 처리 중 서버 오류가 발생했습니다.") from None
    except Exception:
        # 예외 본문/traceback에는 검색어·이미지가 포함될 수 있다.
        logger.error("통합 검색 처리 중 서버 오류")
        raise HTTPException(500, "검색 처리 중 서버 오류가 발생했습니다.") from None
    finally:
        await form.close()
