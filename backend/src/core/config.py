"""
백엔드 운영 상수.

업로드 검증, 검색 파라미터, 정적 파일 마운트 경로 등을 한 곳에서 관리합니다.
값의 근거는 각 상수 위 주석에 명시합니다.

env(.env) 에서 오는 값은 pydantic-settings 의 `Settings` 클래스로 모아
**기동(import) 시점에 형식·범위를 검증**합니다(감사보고서 R5). 잘못된 env 는
런타임 깊은 곳이 아니라 여기서 한국어 메시지로 즉시 실패합니다. 검증 후
기존 공개 상수 이름(DATABASE_URL, STORAGE_MODE, CORS_ALLOW_ORIGINS 등)을
그대로 재수출하므로 `config.XXX` 로 참조하는 호출부는 손대지 않습니다.

비밀값(DB 접속 문자열, KIPRIS 키)은 .env 에서 읽습니다 (paths.py 가 1회 로드).
"""

import re

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# paths 가 .env 를 load_dotenv 로 os.environ 에 1회 적재한다 — Settings() 가
# 그 값을 읽으므로 반드시 먼저 import 되어야 함.
# (from .core import config, paths 처럼 config 가 먼저 로드되는 경로가 실재한다)
from . import paths  # noqa: F401

# ====================================================================
# 업로드 검증  (env 무관 순수 상수 — 현행 유지)
# ====================================================================

# 허용되는 이미지 MIME 타입. 실제 파일 디코딩(PIL)으로 형식을 다시 검증하므로
# Content-Type 헤더 단독으로 신뢰하지 않지만, 1차 빠른 필터링 용도로 사용.
ALLOWED_IMAGE_MIME_TYPES: set[str] = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}

# 디코딩 후 PIL이 식별하는 포맷명(대문자). 최종 형식 검증의 정답지.
ALLOWED_PIL_FORMATS: set[str] = {"PNG", "JPEG", "WEBP"}

# 업로드 파일 크기 상한 (바이트). 10 MiB.
# 근거: KIPRIS 로고 PDF 안 이미지가 대체로 수백 KB ~ 수 MB 수준이며,
# 사용자가 핸드폰으로 찍은 사진도 통상 5 MB 이하. 여유 두고 10 MiB로 설정.
MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024

# 이미지 치수 최소/최대. 너무 작으면 임베딩 품질 저하, 너무 크면 메모리 위험.
# 근거: ml/src/preprocess.py 의 MIN_SIZE=32 / MAX_SIZE=4096 과 일치.
#       (preprocess가 안에서 다시 검증하지만 API 단에서도 사전 차단)
MIN_IMAGE_DIM: int = 32
MAX_IMAGE_DIM: int = 4096


# ====================================================================
# 검색 파라미터  (env 무관 순수 상수 — 현행 유지)
# ====================================================================

# 기본 top-k 값. 5장 정도면 사용자가 한눈에 보기 적당하고, scoring의
# 격차 계산(top1 vs top2, top1 vs mean)에도 충분한 표본.
DEFAULT_TOP_K: int = 5

# top-k 허용 범위. 너무 크면 응답 크기 증폭.
MIN_TOP_K: int = 1
MAX_TOP_K: int = 20


# ====================================================================
# 이미지 정적 파일 서빙  (env 무관 순수 상수 — 현행 유지)
# ====================================================================

# 검색 결과의 이미지를 노출할 URL prefix. main.py 에서 StaticFiles로 마운트.
# 이 prefix 뒤에 "출원번호.png"가 붙어 클라이언트가 접근.
IMAGES_URL_PREFIX: str = "/images"


# ====================================================================
# env 유래 설정 — 검증되는 Settings 클래스로 집약 (감사보고서 R5)
# ====================================================================

# 레이트리밋 세그먼트 형식: "<정수>[/|per]<선택 배수><단위>".
# slowapi/limits 가 실제로 소비하는 문자열이라 사람이 흔히 틀리는 오타(단위 없음,
# 순수 숫자, 잘못된 구분자)를 여기서 거른다. 예: "10/minute", "30 per hour".
_RATE_LIMIT_SEGMENT_RE = re.compile(
    r"^\s*\d+\s*(?:/|\s+per\s+)\s*\d*\s*"
    r"(?:second|sec|minute|min|hour|hr|day|month|year)s?\s*$",
    re.IGNORECASE,
)


def _validate_rate_limit(value: str) -> str:
    """레이트리밋 문자열('<정수>/<단위>', 세미콜론으로 다중 지정 가능)을 검증한다."""
    segments = [s for s in value.split(";") if s.strip()]
    if not segments:
        raise ValueError(
            "레이트리밋이 비어 있습니다. '<정수>/<단위>' 형식으로 지정하세요 (예: '10/minute')."
        )
    for seg in segments:
        if not _RATE_LIMIT_SEGMENT_RE.match(seg):
            raise ValueError(
                f"레이트리밋 형식이 올바르지 않습니다: {seg.strip()!r}. "
                "'<정수>/<단위>' 형식이어야 합니다 "
                "(단위: second/minute/hour/day/month/year, 예: '10/minute')."
            )
    return value


# env 필드명 → 사용자가 .env 에 적는 실제 환경변수명 (오류 메시지 표기용).
_FIELD_TO_ENV: dict[str, str] = {
    "search_max_concurrency": "MARKLENS_SEARCH_CONCURRENCY",
    "cors_origins_raw": "MARKLENS_CORS_ORIGINS",
    "search_rate_limit": "MARKLENS_SEARCH_RATELIMIT",
    "namecheck_rate_limit": "MARKLENS_NAMECHECK_RATELIMIT",
    "api_key": "MARKLENS_API_KEY",
    "database_url": "DATABASE_URL",
}


class Settings(BaseSettings):
    """env 에서 오는 운영값을 검증하는 설정 클래스.

    각 필드는 .env 의 실제 환경변수명(validation_alias)에 1:1 매핑된다.
    paths.py 가 이미 .env 를 os.environ 에 적재하므로 여기서 env_file 은 읽지 않는다
    (로드 지점을 한 곳으로 유지).
    """

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    # CPU 바운드 검색(CLIP 인코딩 + FAISS)의 동시 실행 상한.
    # 검색은 워커 스레드로 오프로드되는데(이벤트 루프 차단 방지), CPU 추론을
    # 무제한 동시 실행하면 서로 스래싱해 전부 느려진다 → 초과분은 대기열로.
    search_max_concurrency: int = Field(
        default=2, validation_alias="MARKLENS_SEARCH_CONCURRENCY"
    )

    # 허용 오리진(콤마 구분) 원문. 파싱된 리스트는 cors_allow_origins 프로퍼티로 노출.
    # 미설정 시 로컬 프론트 개발 서버(Next.js localhost:3000)만 허용한다.
    # 근거(감사보고서 작업3 1-2, R12): allow_origins=["*"] 하드코딩 제거.
    cors_origins_raw: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        validation_alias="MARKLENS_CORS_ORIGINS",
    )

    # IP 기준 요청 한도. slowapi 포맷("<정수>/<단위>", 예: "10/minute").
    # 근거(감사보고서 작업3 6-3): /search 는 CPU 바운드(CLIP+FAISS) 보호,
    #   /name-check 는 KIPRIS 월 쿼터(1,000회) 보호가 목적이라 서로 다른 기본값.
    search_rate_limit: str = Field(
        default="10/minute", validation_alias="MARKLENS_SEARCH_RATELIMIT"
    )
    namecheck_rate_limit: str = Field(
        default="30/minute", validation_alias="MARKLENS_NAMECHECK_RATELIMIT"
    )

    # 정적 X-API-Key. 설정 시에만 /search·/name-check 에서 헤더 일치를 검증(불일치 401).
    # 미설정("")이면 완전 비활성 — 로컬 개발은 무인증 개방. (core/auth.py 참조)
    api_key: str = Field(default="", validation_alias="MARKLENS_API_KEY")

    # DB 접속 문자열. 설정 시 db 모드(상표 메타를 PostgreSQL 에서 조회),
    # 비어 있으면 file 모드(ml/data/kipris_metadata.json 적재).
    # 예: postgresql://postgres:password@127.0.0.1:5432/marklens
    database_url: str = Field(default="", validation_alias="DATABASE_URL")

    # ---- 검증 규칙 (사람이 실제로 틀리는 것만) --------------------------------

    @field_validator("search_max_concurrency", mode="before")
    @classmethod
    def _check_concurrency(cls, v: object) -> int:
        """양의 정수여야 함(0·음수·비정수는 스래싱/무한 대기를 유발)."""
        try:
            n = int(str(v).strip())
        except (TypeError, ValueError):
            raise ValueError(f"양의 정수여야 합니다 (받은 값: {v!r}).")
        if n < 1:
            raise ValueError(f"1 이상의 정수여야 합니다 (받은 값: {n}).")
        return n

    @field_validator("cors_origins_raw")
    @classmethod
    def _check_cors(cls, v: str) -> str:
        """콤마로 구분된 오리진이 최소 1개는 있어야 함(빈 값이면 CORS가 무력화)."""
        origins = [o.strip() for o in v.split(",") if o.strip()]
        if not origins:
            raise ValueError(
                "허용 오리진이 하나도 없습니다. 콤마로 구분된 URL을 최소 1개 지정하세요 "
                "(예: 'http://localhost:3000')."
            )
        return v

    @field_validator("search_rate_limit", "namecheck_rate_limit")
    @classmethod
    def _check_rate_limit(cls, v: str) -> str:
        return _validate_rate_limit(v)

    @field_validator("database_url")
    @classmethod
    def _check_database_url(cls, v: str) -> str:
        """설정되어 있으면 postgresql 스킴이어야 함(다른 DB 는 이 코드베이스가 미지원)."""
        v = v.strip()
        if v and not v.startswith(("postgresql://", "postgres://")):
            raise ValueError(
                "postgresql 스킴이어야 합니다 "
                "(예: postgresql://user:password@127.0.0.1:5432/marklens)."
            )
        return v

    @property
    def cors_allow_origins(self) -> list[str]:
        """콤마 구분 원문을 정제된 오리진 리스트로 변환."""
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    @property
    def storage_mode(self) -> str:
        """DATABASE_URL 유무로 결정되는 저장소 모드 문자열('db' | 'file')."""
        return "db" if self.database_url else "file"


def _load_settings() -> Settings:
    """Settings 를 로드하되, 검증 실패는 스택 트레이스 대신 한국어 요약으로 재발생."""
    try:
        return Settings()
    except ValidationError as exc:
        lines: list[str] = []
        for err in exc.errors():
            loc = err.get("loc") or ()
            field = str(loc[0]) if loc else "?"
            env_name = _FIELD_TO_ENV.get(field, field)
            ctx = err.get("ctx") or {}
            # 커스텀 검증기의 ValueError 는 ctx["error"] 에 원문 한국어 메시지가 있다.
            detail = str(ctx["error"]) if "error" in ctx else err.get("msg", "")
            lines.append(f"  - {env_name}: {detail}")
        raise RuntimeError(
            "환경설정(.env) 검증에 실패했습니다. 아래 항목을 수정한 뒤 다시 실행하세요:\n"
            + "\n".join(lines)
            + "\n(형식 설명은 .env.example 의 주석을 참고하세요.)"
        ) from None


settings: Settings = _load_settings()


# ====================================================================
# 공개 상수 재수출 — 기존 이름 그대로 유지 (호출부 `config.XXX` 무변경)
# ====================================================================

# 검색 동시 실행 상한 (env: MARKLENS_SEARCH_CONCURRENCY)
SEARCH_MAX_CONCURRENCY: int = settings.search_max_concurrency

# CORS 허용 오리진 리스트 (env: MARKLENS_CORS_ORIGINS)
CORS_ALLOW_ORIGINS: list[str] = settings.cors_allow_origins

# 인바운드 레이트리밋 (env: MARKLENS_SEARCH_RATELIMIT / MARKLENS_NAMECHECK_RATELIMIT)
SEARCH_RATE_LIMIT: str = settings.search_rate_limit
NAMECHECK_RATE_LIMIT: str = settings.namecheck_rate_limit

# 정적 X-API-Key (env: MARKLENS_API_KEY, 미설정 시 인증 비활성)
API_KEY: str = settings.api_key

# DB 접속 문자열 및 저장소 모드 (env: DATABASE_URL)
DATABASE_URL: str = settings.database_url
STORAGE_MODE: str = settings.storage_mode
