"""요청 ID 부여 미들웨어 + 로그 주입 필터.

요청마다 8자리 헥사 ID를 만들어:
- contextvars 에 저장 → 로그 라인에 자동 주입 (RequestIdLogFilter)
- 응답 헤더 X-Request-ID 로 반환 → 프론트/사용자 문의 시 로그 대조 가능

순수 ASGI 미들웨어라 스레드풀로 오프로드된 sync 엔드포인트에서도
contextvars 가 전파되어 같은 ID 가 찍힌다.
"""

import logging
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders

# 요청 컨텍스트 밖(startup 등)에서는 "-" 로 표기
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware:
    """http 요청마다 요청 ID를 발급하고 응답 헤더에 되돌려주는 ASGI 미들웨어."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = uuid.uuid4().hex[:8]
        token = request_id_var.set(rid)

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append(REQUEST_ID_HEADER, rid)
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
