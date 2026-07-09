"""정적 X-API-Key 인증 의존성 — R12 시연 하드닝.

감사보고서 작업3 1-1: 전 엔드포인트 무인증 개방 → 외부 시연 URL 이 생기는
순간 차단 요건. 유저 시스템이 없으므로 JWT/OAuth 대신 정적 키 1개로 처리한다
(감사보고서 '하지 말 것' 목록).

활성 조건: 환경변수 MARKLENS_API_KEY(=config.API_KEY)가 설정된 경우에만 검증.
미설정이면 완전 비활성 — 기존처럼 무인증 개방(로컬 개발 편의).

적용 범위(main.py 에서 라우터별 Depends 주입):
- 보호: /search, /name-check — 실제 CPU·외부 쿼터를 소모하는 엔드포인트.
- 제외: /health(로드밸런서·부하테스트가 키 없이 폴링해야 함),
        /docs·/openapi.json·/redoc(시연자가 API 스펙을 탐색해야 함),
        /images 정적(응답에 담긴 이미지 URL 을 브라우저가 키 없이 렌더해야 함).
  → 제외는 '이 의존성을 주입하지 않는 것'으로 자연히 처리된다(별도 예외 목록 불필요).
"""

import secrets

from fastapi import Header, HTTPException, status

from . import config

# 검증할 헤더 이름. FastAPI 는 파라미터명 x_api_key → 헤더 x-api-key(대소문자 무시)로 매핑.
API_KEY_HEADER = "X-API-Key"


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """MARKLENS_API_KEY 설정 시 X-API-Key 헤더 일치를 요구한다.

    - 키 미설정: 즉시 통과(인증 비활성).
    - 키 설정 + 헤더 누락/불일치: 401.
    - 키 설정 + 헤더 일치: 통과.
    """
    expected = config.API_KEY
    if not expected:
        return  # 키 미설정 → 인증 비활성 (로컬 개발 기본)
    # 상수시간 비교 — 정적 키 1개지만 타이밍 비교 회피는 공짜다.
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효한 X-API-Key 헤더가 필요합니다.",
        )
