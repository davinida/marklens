"""백엔드 로깅 설정 (stdlib logging.dictConfig).

원칙:
- print() 금지 — 모든 진단 출력은 logging 으로 (요청 ID 자동 포함).
- uvicorn 로거들도 같은 포맷으로 정렬해 로그가 한 결로 나온다.
- JSON 포맷/수집기 연동은 실배포 전까지 도입하지 않는다 (과잉 설계).

main.py 가 앱 생성 전에 setup_logging() 을 1회 호출한다.
"""

import logging.config
import os

from .request_id import RequestIdLogFilter

LOG_FORMAT = (
    "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """루트/uvicorn 로거를 공통 포맷으로 구성한다. 여러 번 호출해도 안전."""
    level = os.getenv("MARKLENS_LOG_LEVEL", "INFO").upper()
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "request_id": {"()": RequestIdLogFilter},
            },
            "formatters": {
                "default": {"format": LOG_FORMAT, "datefmt": DATE_FORMAT},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                    "stream": "ext://sys.stderr",
                },
            },
            "root": {"level": level, "handlers": ["console"]},
            "loggers": {
                # uvicorn 기본 핸들러를 대체해 포맷을 통일 (중복 출력 방지)
                "uvicorn": {"level": level, "handlers": ["console"], "propagate": False},
                "uvicorn.error": {"level": level, "handlers": ["console"], "propagate": False},
                "uvicorn.access": {"level": level, "handlers": ["console"], "propagate": False},
            },
        }
    )
