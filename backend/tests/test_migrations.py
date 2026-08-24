"""마이그레이션 버전 추적(schema_migrations) 동작 검증.

전용 테스트 DB(MARKLENS_TEST_DATABASE_URL)가 필요하다 — 개발 DB 와 분리해
파괴적 초기화(DROP)를 안전하게 수행한다. 미설정 시 skip (CI 는 postgres
서비스 컨테이너로 항상 실행).

로컬 실행 예:
    MARKLENS_TEST_DATABASE_URL=postgresql://postgres:암호@127.0.0.1:5432/marklens_test `
        pytest backend/tests/test_migrations.py
"""

import os

import pytest

TEST_DB_URL = os.getenv("MARKLENS_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL,
    reason="MARKLENS_TEST_DATABASE_URL 미설정 — PostgreSQL 테스트 DB 필요",
)


def test_apply_migrations_is_tracked_and_idempotent():
    import psycopg

    from backend.scripts.migrate_json_to_db import (
        MIGRATIONS_DIR,
        apply_migrations,
        ensure_database_exists,
    )

    ensure_database_exists(TEST_DB_URL)
    with psycopg.connect(TEST_DB_URL) as conn:
        # 전용 테스트 DB — 깨끗한 상태에서 시작
        conn.execute("DROP TABLE IF EXISTS schema_migrations, trademark, meta CASCADE")
        conn.commit()

        first = apply_migrations(conn)
        second = apply_migrations(conn)

        versions = [
            row[0]
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]

    sql_files = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    assert first == len(sql_files), "첫 실행은 모든 파일을 적용해야 한다"
    assert second == 0, "두 번째 실행은 0 applied 여야 한다 (버전 추적)"
    assert versions == sql_files, "적용된 버전 목록이 파일 목록과 일치해야 한다"
