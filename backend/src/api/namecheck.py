"""
POST /name-check — 입력 상표명의 동일 명칭 선행 등록상표 존재 여부 (백엔드-7).

KIPRIS 상표명완전일치 API 를 실시간 호출하되, 동일 질의는 TTL 캐시로 재사용해
월 1,000회 한도를 보호한다. 기존 GET 은 한 릴리스 동안 deprecated 로 유지한다.
"""

import logging
import os
import threading
from datetime import datetime, timezone

from cachetools import TTLCache
from fastapi import APIRouter, HTTPException, Query, Request, status

from ..core import appno, config, engine, kipris_client, storage
from ..core.ratelimit import limiter
from ..schemas.namecheck import NameCheckCandidate, NameCheckRequest, NameCheckResponse

router = APIRouter()
logger = logging.getLogger(__name__)

# 동일 질의 캐시 TTL. 등록상표 목록은 하루 안에 바뀔 일이 거의 없다 → 기본 24h.
CACHE_TTL_SEC: int = int(os.getenv("KIPRIS_NAME_CACHE_TTL", str(24 * 3600)))

# 캐시 항목 상한. 수제 dict 는 상한이 없어 서로 다른 질의가 쌓이면 무한 성장했다
# → TTLCache 로 교체 (상한 + TTL + LRU 방출을 라이브러리가 처리).
CACHE_MAX_ENTRIES: int = int(os.getenv("KIPRIS_NAME_CACHE_MAX", "1024"))

# {정규화된 질의: summary dict}. TTLCache 는 스레드 안전하지 않아 락으로 감싼다.
_cache: TTLCache = TTLCache(maxsize=CACHE_MAX_ENTRIES, ttl=CACHE_TTL_SEC)
_cache_lock = threading.Lock()
_upstream_lock = threading.Lock()
SOURCE_NAME = "KIPRIS Plus trademarkNameMatchSearchInfo"
# 상세 배열은 요약 집계와 별개로 응답 크기를 제한한다. 정확 일치·등록 후보를 먼저
# 배치하며, 전체 검사 여부는 기존 complete/scanned_count 계약으로 계속 표현한다.
CANDIDATE_LIMIT: int = max(
    1,
    min(
        kipris_client.NAME_SEARCH_MAX_ITEMS,
        int(os.getenv("KIPRIS_NAME_CANDIDATE_LIMIT", "100")),
    ),
)


def _cache_get(key: str) -> dict | None:
    with _cache_lock:
        return _cache.get(key)


def _cache_put(key: str, value: dict) -> None:
    with _cache_lock:
        _cache[key] = value


def _to_message(summary: dict) -> str:
    n = summary["exact_registered_count"]
    if n > 0:
        if not summary["complete"]:
            return (
                f"확인된 범위에서 동일 명칭의 선행 등록상표가 최소 {n}건 있습니다. "
                "전체 건수는 확정할 수 없습니다."
            )
        return f"동일 명칭의 선행 등록상표 {n}건이 존재합니다."
    if not summary["complete"]:
        return "일부 결과만 확인되어 동일 명칭 등록상표 존재 여부를 확정할 수 없습니다."
    if summary["registered_count"] > 0:
        return (
            f"정확히 같은 등록 명칭은 없지만, 이 문구를 포함한 등록상표가 "
            f"{summary['registered_count']}건 있습니다."
        )
    return "동일 명칭의 등록상표가 발견되지 않았습니다."


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _string_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = str(value or "").split("|")
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        text = str(raw or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _normalized_application_number(value: object) -> str | None:
    raw = _optional_text(value)
    if raw is None:
        return None
    try:
        return appno.normalize_application_number(raw)
    except ValueError:
        # 원천 계약이 깨져도 나머지 후보는 보여주되, 잘못된 번호로 로컬 조인은 하지 않는다.
        return raw


def _candidate_priority(query: str, item: dict, original_index: int) -> tuple[int, int]:
    exact = (
        kipris_client.normalize_mark_title(item.get("Title"))
        == kipris_client.normalize_mark_title(query)
    )
    registered = item.get("ApplicationStatus") == "등록"
    if exact and registered:
        bucket = 0
    elif exact:
        bucket = 1
    elif registered:
        bucket = 2
    else:
        bucket = 3
    return bucket, original_index


def _build_candidates(
    query: str,
    items: list[dict],
) -> tuple[list[NameCheckCandidate], bool]:
    """KIPRIS 행을 공개 응답용 allowlist 모델로 변환한다.

    원천의 일회성 이미지 URL은 반환하지 않는다. 현재 게시된 로컬 인덱스와
    출원번호가 일치하는 경우에만 보호된 `/images` 경로를 연결한다.
    """
    ranked_items = [
        item
        for _, item in sorted(
            enumerate(items),
            key=lambda indexed: _candidate_priority(query, indexed[1], indexed[0]),
        )
    ]
    selected_items = ranked_items[:CANDIDATE_LIMIT]
    application_numbers = [
        number
        for item in selected_items
        if (number := _normalized_application_number(item.get("ApplicationNumber")))
        and number.isdigit()
    ]
    try:
        local_lookup = engine.lookup_trademarks_by_application_numbers(application_numbers)
    except Exception:
        # 이미지 보강 실패가 이미 성공한 KIPRIS 결과를 500으로 폐기하면 같은 질의가
        # 외부 쿼터를 다시 소모한다. 서지 후보는 유지하고 이미지만 생략한다.
        logger.exception("name-check local image metadata lookup failed")
        local_lookup = {}
    normalized_query = kipris_client.normalize_mark_title(query)

    candidates: list[NameCheckCandidate] = []
    for item in selected_items:
        application_number = _normalized_application_number(item.get("ApplicationNumber"))
        local = local_lookup.get(application_number or "")
        local_image_url = None
        if local:
            image_key = _optional_text(local.get("이미지파일"))
            if image_key and image_key in engine.state.image_path_set:
                local_image_url = storage.public_url(image_key)

        title = _optional_text(item.get("Title"))
        status_name = _optional_text(item.get("ApplicationStatus"))
        candidates.append(
            NameCheckCandidate(
                application_number=application_number,
                registration_number=_optional_text(item.get("RegistrationNumber")),
                application_date=_optional_text(item.get("ApplicationDate")),
                registration_date=_optional_text(item.get("RegistrationDate")),
                title=title,
                status=status_name,
                mark_type=_optional_text(
                    item.get("TrademarkDivisionCode")
                    or item.get("TradeMarkDivisionCode")
                ),
                applicant=_optional_text(item.get("ApplicantName")),
                right_holder=_optional_text(item.get("RegistrationRightholderName")),
                nice_classes=_string_list(item.get("GoodClassificationCode")),
                vienna_codes=_string_list(item.get("ViennaCode")),
                similarity_codes=_string_list(item.get("SimilarCode")),
                exact_title_match=(
                    bool(normalized_query)
                    and kipris_client.normalize_mark_title(title) == normalized_query
                ),
                is_registered=status_name == "등록",
                local_image_url=local_image_url,
            )
        )
    return candidates, len(ranked_items) > len(selected_items)


def _run_name_check(name: str) -> NameCheckResponse:
    """POST/GET 공통 상표명 확인 로직."""
    query = name.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="상표명이 비어 있습니다."
        )
    # KIPRIS가 대소문자·전각·호환문자를 동일한 검색으로 처리한다는 공급자 계약이
    # 없다. 서로 다른 원문 질의의 결과를 섞지 않도록 trim 이외에는 정규화하지 않는다.
    cache_key = query

    cached = _cache_get(cache_key)
    if cached is not None:
        payload = {**cached, "query": query}
        return NameCheckResponse(**payload, cached=True, message=_to_message(cached))

    # TTLCache itself is protected above, but a cache miss must also be
    # single-flight or simultaneous requests consume the external quota twice.
    with _upstream_lock:
        cached = _cache_get(cache_key)
        if cached is not None:
            payload = {**cached, "query": query}
            return NameCheckResponse(
                **payload, cached=True, message=_to_message(cached)
            )

        try:
            result = kipris_client.name_match_search(query)
        except kipris_client.CallBudgetExceeded:
            raise HTTPException(
                status_code=429,
                detail="이번 달 상표명 확인 한도에 도달했습니다.",
            ) from None
        except kipris_client.KiprisConfigError as e:
            logger.warning(
                "KIPRIS name-check configuration failure: %s", type(e).__name__
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="KIPRIS 상표명 확인 서비스가 준비되지 않았습니다.",
            ) from None
        except kipris_client.KiprisError as e:
            logger.warning(
                "KIPRIS name-check upstream failure: %s result_code=%s",
                type(e).__name__,
                e.result_code,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="KIPRIS 상표명 확인 서비스 응답을 확인하지 못했습니다.",
            ) from None

        summary = kipris_client.summarize_name_search(
            query,
            result.items,
            result.total_found,
            complete=result.complete,
        )
        candidates, candidates_truncated = _build_candidates(query, result.items)
        summary.update(
            candidates=candidates,
            candidates_returned=len(candidates),
            candidates_truncated=candidates_truncated,
            checked_at=datetime.now(timezone.utc),
            source=SOURCE_NAME,
        )
        _cache_put(cache_key, summary)
        return NameCheckResponse(
            **summary, cached=False, message=_to_message(summary)
        )


@router.post("/name-check", response_model=NameCheckResponse)
@limiter.limit(config.NAMECHECK_RATE_LIMIT)  # IP 기준 한도(기본 30/min) — KIPRIS 쿼터 보호
def name_check_post(
    request: Request,  # slowapi 데코레이터가 IP 추출에 사용
    payload: NameCheckRequest,
) -> NameCheckResponse:
    """상표명완전일치 검색 결과를 본문 기반 요청으로 반환한다."""
    return _run_name_check(payload.name)


@router.get("/name-check", response_model=NameCheckResponse, deprecated=True)
@limiter.limit(config.NAMECHECK_RATE_LIMIT)
def name_check(
    request: Request,
    name: str = Query(..., min_length=1, max_length=100, description="확인할 상표명"),
) -> NameCheckResponse:
    """한 릴리스 동안 유지하는 deprecated GET 호환 경로."""
    return _run_name_check(name)
