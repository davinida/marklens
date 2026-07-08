"""
백엔드 운영 상수.

업로드 검증, 검색 파라미터, 정적 파일 마운트 경로 등을 한 곳에서 관리합니다.
값의 근거는 각 상수 위 주석에 명시합니다.
비밀값(DB 접속 문자열, KIPRIS 키)은 .env 에서 읽습니다 (paths.py 가 1회 로드).
"""

import os

# paths 가 .env 를 로드한다 — 아래 os.getenv 보다 먼저 import 되어야 함.
# (from .core import config, paths 처럼 config 가 먼저 로드되는 경로가 실재한다)
from . import paths  # noqa: F401

# ====================================================================
# 업로드 검증
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
# 검색 파라미터
# ====================================================================

# 기본 top-k 값. 5장 정도면 사용자가 한눈에 보기 적당하고, scoring의
# 격차 계산(top1 vs top2, top1 vs mean)에도 충분한 표본.
DEFAULT_TOP_K: int = 5

# top-k 허용 범위. 너무 크면 응답 크기 증폭.
MIN_TOP_K: int = 1
MAX_TOP_K: int = 20

# CPU 바운드 검색(CLIP 인코딩 + FAISS)의 동시 실행 상한.
# 검색은 워커 스레드로 오프로드되는데(이벤트 루프 차단 방지), CPU 추론을
# 무제한 동시 실행하면 서로 스래싱해 전부 느려진다 → 2개 초과분은 대기열로.
SEARCH_MAX_CONCURRENCY: int = int(os.getenv("MARKLENS_SEARCH_CONCURRENCY", "2"))


# ====================================================================
# 이미지 정적 파일 서빙
# ====================================================================

# 검색 결과의 이미지를 노출할 URL prefix. main.py 에서 StaticFiles로 마운트.
# 이 prefix 뒤에 "출원번호.png"가 붙어 클라이언트가 접근.
IMAGES_URL_PREFIX: str = "/images"


# ====================================================================
# CORS (개발용)
# ====================================================================

# 개발 단계에서는 허용적으로 설정. 배포 시 실제 프론트엔드 origin으로 좁힐 것.
# Phase 3 Next.js 개발 서버가 보통 http://localhost:3000 에서 뜸.
CORS_ALLOW_ORIGINS: list[str] = ["*"]


# ====================================================================
# 저장소 모드 (백엔드-1/2/4 — PostgreSQL 전환)
# ====================================================================

# DATABASE_URL 이 설정되어 있으면 상표 메타를 DB 에서 조회하고(db 모드),
# 비어 있으면 기존처럼 ml/data/kipris_metadata.json 을 통째로 적재한다(file 모드).
# 예: postgresql://postgres:password@127.0.0.1:5432/marklens
# 팀원이 DB 를 아직 안 깔았어도 file 모드로 기존과 동일하게 동작한다.
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# 현재 저장소 모드 문자열. /health 응답과 로그에 노출.
STORAGE_MODE: str = "db" if DATABASE_URL else "file"
