"""
GET /name-check — 입력 상표명의 동일 명칭 선행 등록상표 존재 여부 (백엔드-7).

KIPRIS 상표명완전일치 API 를 실시간 호출하되, 동일 질의는 TTL 캐시로 재사용해
월 1,000회 한도를 보호한다 (TODO.pdf 백엔드-7 요구사항).
"""

import os
import threading

from cachetools import TTLCache
from fastapi import APIRouter, HTTPException, Query, status

from ..core import kipris_client
from ..schemas.namecheck import NameCheckResponse

router = APIRouter()

# 동일 질의 캐시 TTL. 등록상표 목록은 하루 안에 바뀔 일이 거의 없다 → 기본 24h.
CACHE_TTL_SEC: int = int(os.getenv("KIPRIS_NAME_CACHE_TTL", str(24 * 3600)))

# 캐시 항목 상한. 수제 dict 는 상한이 없어 서로 다른 질의가 쌓이면 무한 성장했다
# → TTLCache 로 교체 (상한 + TTL + LRU 방출을 라이브러리가 처리).
CACHE_MAX_ENTRIES: int = int(os.getenv("KIPRIS_NAME_CACHE_MAX", "1024"))

# {정규화된 질의: summary dict}. TTLCache 는 스레드 안전하지 않아 락으로 감싼다.
_cache: TTLCache = TTLCache(maxsize=CACHE_MAX_ENTRIES, ttl=CACHE_TTL_SEC)
_cache_lock = threading.Lock()


def _cache_get(key: str) -> dict | None:
    with _cache_lock:
        return _cache.get(key)


def _cache_put(key: str, value: dict) -> None:
    with _cache_lock:
        _cache[key] = value


def _to_message(summary: dict) -> str:
    n = summary["exact_registered_count"]
    if n > 0:
        return f"동일 명칭의 선행 등록상표 {n}건이 존재합니다."
    if summary["registered_count"] > 0:
        return (
            f"정확히 같은 이름은 없지만, 이 문구를 포함한 등록상표가 "
            f"{summary['registered_count']}건 있습니다."
        )
    return "동일 명칭의 등록상표가 발견되지 않았습니다."


@router.get("/name-check", response_model=NameCheckResponse)
def name_check(
    name: str = Query(..., min_length=1, max_length=100, description="확인할 상표명"),
) -> NameCheckResponse:
    """상표명완전일치 검색 → 등록 상태만 집계해 요약을 반환합니다."""
    key = name.strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="상표명이 비어 있습니다."
        )

    cached = _cache_get(key)
    if cached is not None:
        return NameCheckResponse(**cached, cached=True, message=_to_message(cached))

    try:
        items, total_found = kipris_client.name_match_search(key)
    except kipris_client.CallBudgetExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))
    except kipris_client.KiprisError as e:
        # 설정 누락(키/URL 미설정)은 서비스 준비 안 됨, 그 외는 게이트웨이 오류
        code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if "설정되지 않았습니다" in str(e)
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code=code, detail=str(e))

    # total_found 는 TotalSearchCount(전체 건수), registered/exact 는 수집된 items 기준
    summary = kipris_client.summarize_name_search(key, items, total_found)
    _cache_put(key, summary)
    return NameCheckResponse(**summary, cached=False, message=_to_message(summary))
