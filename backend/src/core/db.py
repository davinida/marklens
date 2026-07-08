"""
PostgreSQL 접근 계층 (백엔드-1·2·4).

- 커넥션 풀은 서버 startup(engine.load_all)에서 1회 생성하고 요청마다 재사용한다.
  (요청마다 커넥션을 새로 만드는 것 금지 — 가이드 백엔드-4)
- DB 컬럼은 영문, API 응답 계약은 한글 필드 유지 → row_to_trademark() 가 변환.
  프론트/README 가 문서화한 응답 스키마를 깨지 않기 위한 경계선이다.
- 이 모듈은 DATABASE_URL 이 설정된 "db 모드"에서만 초기화된다.
  file 모드에서는 import 만 되고 아무 연결도 만들지 않는다.
"""

from typing import Optional

from psycopg_pool import ConnectionPool

from . import config


# 모듈 전역 풀. engine.load_all() 이 init_pool() 로 채운다.
_pool: Optional[ConnectionPool] = None

# 후보 조회에 사용하는 컬럼 목록 (마이그레이션 001_init.sql 과 일치해야 함)
_SELECT_COLUMNS = """
    application_no, registration_no, application_date, registration_date,
    name_ko, name_en, mark_type, applicant, right_holder,
    image_key, vienna_codes, nice_classes, similarity_codes
"""


def init_pool() -> None:
    """풀 생성 + 연결 1회 검증. 실패 시 예외를 그대로 올려 기동을 중단시킨다."""
    global _pool
    if _pool is not None:
        return
    # min_size=1: 개발 장비 부담 최소화. 검색은 요청당 쿼리 1개라 소규모면 충분.
    _pool = ConnectionPool(
        conninfo=config.DATABASE_URL,
        min_size=1,
        max_size=4,
        open=True,
        timeout=10,
    )
    # 기동 시점에 연결 가능 여부를 확정한다 (첫 요청에서 터지지 않게).
    with _pool.connection() as conn:
        conn.execute("SELECT 1")


def close_pool() -> None:
    """서버 shutdown 시 호출."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _require_pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("DB 풀이 초기화되지 않았습니다. (db 모드 아님?)")
    return _pool


def row_to_trademark(row: tuple) -> dict:
    """
    trademark 테이블 row → API 계약(한글 키) dict.

    스키마는 schemas/search.py TrademarkInfo 와 일치.
    `이미지파일` 은 TrademarkInfo 의 필드는 아니지만 엔진의 조인 키라 포함한다.
    """
    (
        application_no, registration_no, application_date, registration_date,
        name_ko, name_en, mark_type, applicant, right_holder,
        image_key, vienna_codes, nice_classes, similarity_codes,
    ) = row
    return {
        "출원번호": application_no,
        "등록번호": registration_no,
        "출원일자": str(application_date) if application_date else None,
        "등록일자": str(registration_date) if registration_date else None,
        "상표한글명": name_ko,
        "상표영문명": name_en,
        "상표구분": mark_type,
        "출원인": applicant,
        "최종권리자": right_holder,
        "이미지파일": image_key,
        "비엔나코드": list(vienna_codes or []),
        "류": list(nice_classes or []),
        "유사군": list(similarity_codes or []),
    }


def fetch_trademarks_by_image_keys(image_keys: list[str]) -> dict[str, dict]:
    """
    FAISS 검색 결과(파일명 목록)로 후보 메타를 한 번에 조회한다 (백엔드-4).

    Returns:
        {이미지파일명: trademark dict}. DB 에 없는 파일명은 키가 빠진다
        (엔진이 None 처리 → 응답의 trademark: null).
    """
    if not image_keys:
        return {}
    pool = _require_pool()
    with pool.connection() as conn:
        rows = conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM trademark WHERE image_key = ANY(%s)",
            (image_keys,),
        ).fetchall()
    result = {}
    for row in rows:
        tm = row_to_trademark(row)
        result[tm["이미지파일"]] = tm
    return result


def fetch_dataset_info() -> dict:
    """meta 테이블에서 dataset_info(JSONB)를 읽는다. 없으면 빈 dict."""
    pool = _require_pool()
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'dataset_info'"
        ).fetchone()
    return row[0] if row else {}


def count_trademarks() -> int:
    """/health 의 trademark_count 용."""
    pool = _require_pool()
    with pool.connection() as conn:
        row = conn.execute("SELECT count(*) FROM trademark").fetchone()
    return int(row[0])
