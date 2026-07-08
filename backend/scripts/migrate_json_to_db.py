"""
백엔드-2: ml/data/kipris_metadata.json → PostgreSQL 마이그레이션.

실행 (project root 기준, .env 에 DATABASE_URL 설정 후):
    ml\\venv\\Scripts\\python.exe -m backend.scripts.migrate_json_to_db
    옵션: --dry-run (DB에 쓰지 않고 리포트만)

동작:
    1) DATABASE_URL 의 대상 DB가 없으면 자동 생성 (postgres 관리 DB 경유)
    2) backend/migrations/*.sql 을 순서대로 적용 (전부 IF NOT EXISTS — 멱등)
    3) trademarks[] 를 정규화(출원번호) 후 UPSERT
       - 이미지 실물이 없는 레코드는 제외 (reconcile — "DB에 있으면 이미지도 있다" 불변식)
    4) dataset_info 를 meta 테이블에 저장
    5) 무결성 검증 리포트 출력 (건수/필드 누락/배열 표본/DB 대조)
"""

import argparse
import json
import sys
from pathlib import Path

# 직접 실행(python backend/scripts/migrate_json_to_db.py)도 되도록 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from backend.src.core import config, paths  # noqa: E402
from backend.src.core.appno import normalize_application_number  # noqa: E402

MIGRATIONS_DIR = PROJECT_ROOT / "backend" / "migrations"

UPSERT_SQL = """
INSERT INTO trademark (
    application_no, registration_no, application_date, registration_date,
    name_ko, name_en, mark_type, applicant, right_holder,
    image_key, vienna_codes, nice_classes, similarity_codes, updated_at
) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
ON CONFLICT (application_no) DO UPDATE SET
    registration_no = EXCLUDED.registration_no,
    application_date = EXCLUDED.application_date,
    registration_date = EXCLUDED.registration_date,
    name_ko = EXCLUDED.name_ko,
    name_en = EXCLUDED.name_en,
    mark_type = EXCLUDED.mark_type,
    applicant = EXCLUDED.applicant,
    right_holder = EXCLUDED.right_holder,
    image_key = EXCLUDED.image_key,
    vienna_codes = EXCLUDED.vienna_codes,
    nice_classes = EXCLUDED.nice_classes,
    similarity_codes = EXCLUDED.similarity_codes,
    updated_at = now()
"""


def parse_date(value) -> str | None:
    """'20210315' / '2021-03-15' → ISO 날짜 문자열. 비어 있으면 None."""
    s = str(value or "").strip().replace(".", "-")
    if not s:
        return None
    digits = s.replace("-", "")
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return None  # 형식 불명은 저장하지 않는다 (리포트에 집계)


def ensure_database_exists(database_url: str) -> None:
    """
    대상 DB가 없으면 같은 계정으로 postgres 관리 DB에 붙어 CREATE DATABASE.

    "DB 없음" 오류 메시지는 서버 로케일(한국어 등)에 따라 달라 문자열 매칭이
    불안정하다 → 관리 DB에 접속해 pg_database 를 직접 조회해서 판별한다.
    """
    try:
        with psycopg.connect(database_url, connect_timeout=5):
            return  # 이미 존재
    except psycopg.OperationalError as original:
        conninfo = psycopg.conninfo.conninfo_to_dict(database_url)
        dbname = str(conninfo.pop("dbname", "") or "")
        conninfo["dbname"] = "postgres"
        try:
            admin_url = psycopg.conninfo.make_conninfo(**conninfo)
            with psycopg.connect(admin_url, autocommit=True, connect_timeout=5) as conn:
                exists = conn.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)
                ).fetchone()
                if exists:
                    raise original  # DB는 있는데 다른 이유(권한 등)로 실패한 것
                conn.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname))
                )
                print(f"[migrate] 데이터베이스 생성: {dbname}")
        except psycopg.OperationalError:
            # 관리 DB 접속조차 안 됨 — 서버 다운/인증 실패가 진짜 원인
            raise original


def apply_migrations(conn: psycopg.Connection) -> None:
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        conn.execute(path.read_text(encoding="utf-8"))
        print(f"[migrate] 적용: {path.name}")
    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않고 리포트만")
    args = ap.parse_args()

    if not config.DATABASE_URL:
        print("[오류] DATABASE_URL 이 설정되지 않았습니다. .env 를 확인하세요.", file=sys.stderr)
        return 1
    if not paths.TRADEMARK_META_PATH.exists():
        print(f"[오류] 상표 메타가 없습니다: {paths.TRADEMARK_META_PATH}", file=sys.stderr)
        return 1

    meta = json.loads(paths.TRADEMARK_META_PATH.read_text(encoding="utf-8"))
    trademarks = meta.get("trademarks", [])
    dataset_info = meta.get("dataset_info", {})

    # ---- 변환 + reconcile (이미지 실물 없는 레코드 제외) ----
    rows, skipped_no_image, bad_dates = [], [], 0
    for t in trademarks:
        app_no = normalize_application_number(t["출원번호"])
        image_key = t.get("이미지파일") or f"{app_no}.png"
        if not (paths.IMAGES_DIR / image_key).exists():
            skipped_no_image.append(app_no)
            continue
        app_date = parse_date(t.get("출원일자"))
        reg_date = parse_date(t.get("등록일자"))
        if t.get("출원일자") and not app_date:
            bad_dates += 1
        rows.append((
            app_no,
            t.get("등록번호") or None,
            app_date,
            reg_date,
            t.get("상표한글명") or None,
            t.get("상표영문명") or None,
            t.get("상표구분") or None,
            t.get("출원인") or None,
            t.get("최종권리자") or None,
            image_key,
            [str(v) for v in t.get("비엔나코드", [])],
            [int(c) for c in t.get("류", [])],
            [str(s) for s in t.get("유사군", [])],
        ))

    print(f"[리포트] JSON 상표 수      : {len(trademarks)}")
    print(f"[리포트] 적재 대상        : {len(rows)}")
    print(f"[리포트] 이미지 없어 제외 : {len(skipped_no_image)} {skipped_no_image[:5]}")
    print(f"[리포트] 날짜 형식 불명   : {bad_dates}")
    if dataset_info.get("총_상표수") not in (None, len(rows)):
        print(
            f"[주의] dataset_info.총_상표수({dataset_info.get('총_상표수')}) ≠ "
            f"실제 적재({len(rows)}) — 안내 문구 갱신 검토 (reconcile 이슈)"
        )

    if args.dry_run:
        print("[dry-run] DB 쓰기 생략")
        return 0

    ensure_database_exists(config.DATABASE_URL)
    with psycopg.connect(config.DATABASE_URL) as conn:
        apply_migrations(conn)
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, rows)
            cur.execute(
                "INSERT INTO meta (key, value) VALUES ('dataset_info', %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (Jsonb(dataset_info),),
            )
        conn.commit()

        # ---- 적재 후 검증 ----
        db_count = conn.execute("SELECT count(*) FROM trademark").fetchone()[0]
        null_name = conn.execute(
            "SELECT count(*) FROM trademark WHERE name_ko IS NULL AND name_en IS NULL"
        ).fetchone()[0]
        sample = conn.execute(
            "SELECT application_no, image_key, vienna_codes, nice_classes, similarity_codes "
            "FROM trademark LIMIT 3"
        ).fetchall()

    ok = db_count >= len(rows)
    print(f"[검증] DB 건수 {db_count} (적재 대상 {len(rows)}) → {'OK' if ok else '불일치!'}")
    print(f"[검증] 이름(한/영) 모두 NULL: {null_name}건")
    for s in sample:
        print(f"[표본] {s}")
    print("[완료] 마이그레이션 종료. 서버를 db 모드로 재시작하면 반영됩니다.")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
