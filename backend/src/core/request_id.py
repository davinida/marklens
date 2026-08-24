"""요청 ID 부여 미들웨어 + 로그 주입 필터.

신뢰 경계에서 받은 안전한 ID를 이어 쓰고, 없거나 잘못됐으면 8자리 헥사 ID를 만들어:
- contextvars 에 저장 → 로그 라인에 자동 주입 (RequestIdLogFilter)
- 응답 헤더 X-Request-ID 로 반환 → 프론트/사용자 문의 시 로그 대조 가능

순수 ASGI 미들웨어라 스레드풀로 오프로드된 sync 엔드포인트에서도
contextvars 가 전파되어 같은 ID 가 찍힌다.
"""

import logging
import re
import uuid
from contextvars import ContextVar

from starlette.datastructures import Headers, MutableHeaders

# 요청 컨텍스트 밖(startup 등)에서는 "-" 로 표기
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

REQUEST_ID_HEADER = "X-Request-ID"
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class RequestIdMiddleware:
    """안전한 요청 ID를 전파하거나 새로 발급해 응답에 되돌린다."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = (Headers(scope=scope).get(REQUEST_ID_HEADER) or "").strip()
        rid = incoming if SAFE_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex[:8]
        token = request_id_var.set(rid)

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = rid
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            request_id_var.reset(token)


class RequestIdLogFilter(logging.Filter):
    """모든 로그 레코드에 request_id 속성을 주입한다 (포맷터에서 사용)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True
