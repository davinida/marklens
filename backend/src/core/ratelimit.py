"""인바운드 레이트리밋 (slowapi) — R12 시연 하드닝.

감사보고서 작업3 6-3: 인바운드 보호 부재 → 시연 URL 노출 시 차단 요건.
IP 기준으로 요청 한도를 걸어 아래 두 자원을 보호한다.
- POST /search: CPU 바운드(CLIP 인코딩 + FAISS). 폭주하면 서버 전체가 느려진다.
- GET /name-check: KIPRIS 월 1,000회 쿼터를 실시간 소모한다.

저장소는 인메모리(단일 프로세스라 Redis 불요 — 감사보고서 '하지 말 것' 목록).
한도 수치는 config.SEARCH_RATE_LIMIT / NAMECHECK_RATE_LIMIT (env 오버라이드 가능).
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# 키 함수 = 원격 IP. 시연 단계는 서버를 직접 노출하므로 remote_address 로 충분하다.
# (리버스 프록시 뒤에 두게 되면 X-Forwarded-For 신뢰 설정을 별도로 추가할 것)
# headers_enabled 는 기본값(False) 유지 — 활성화하려면 모든 제한 엔드포인트에
# response: Response 파라미터가 필요한데(pydantic 응답 모델과 충돌), 시연 요건인
# '429 + 명확한 메시지'에는 불필요한 침습이라 채택하지 않는다.
limiter = Limiter(key_func=get_remote_address)


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """한도 초과 시 429 를 한국어 detail 로 반환한다.

    slowapi 기본 핸들러는 영문 'Rate limit exceeded' 를 준다 → 기존 오류 계약
    (모든 detail 이 한국어)과 통일하려고 커스텀한다. 표준 레이트리밋 헤더
    (Retry-After / X-RateLimit-*)는 기본 핸들러와 동일하게 주입해 클라이언트가
    재시도 시점을 알 수 있게 한다.
    """
    response = JSONResponse(
        status_code=429,
        content={
            "detail": (
                "요청이 너무 많습니다. 잠시 후 다시 시도하세요. "
                f"(허용 한도: {exc.detail})"
            )
        },
    )
    # decorator 가 요청 처리 중 set 한 한도 정보. 방어적으로 존재 확인 후 헤더 주입.
    view_rate_limit = getattr(request.state, "view_rate_limit", None)
    if view_rate_limit is not None:
        response = request.app.state.limiter._inject_headers(response, view_rate_limit)
    return response
