"""
GET /name-check — 입력 상표명의 동일 명칭 선행 등록상표 존재 여부 (백엔드-7).

KIPRIS 상표명완전일치 API 를 실시간 호출하되, 동일 질의는 TTL 캐시로 재사용해
월 1,000회 한도를 보호한다 (TODO.pdf 백엔드-7 요구사항).
"""

import os
import threading
import time

from fastapi import APIRouter, HTTPException, Query, status

from ..core import kipris_client
from ..schemas.namecheck import NameCheckResponse

router = APIRouter()

# 동일 질의 캐시 TTL. 등록상표 목록은 하루 안에 바뀔 일이 거의 없다 → 기본 24h.
CACHE_TTL_SEC: int = int(os.getenv("KIPRIS_NAME_CACHE_TTL", str(24 * 3600)))

# {정규화된 질의: (저장 시각 monotonic, summary dict)}
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _cache_get(key: str) -> dict | None:
    with _cache_lock:
        hit = _cache.get(key)
        if hit and (time.monotonic() - hit[0]) < CACHE_TTL_SEC:
            return hit[1]
        if hit:
            del _cache[key]
    return None


def _cache_put(key: str, value: dict) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)


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
        items = kipris_client.name_match_search(key)
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

    summary = kipris_client.summarize_name_search(key, items)
    _cache_put(key, summary)
    return NameCheckResponse(**summary, cached=False, message=_to_message(summary))
