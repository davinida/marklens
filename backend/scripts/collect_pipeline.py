"""
백엔드-5: KIPRIS 수집 파이프라인 — 한 명령으로
    출원인 검색 API → 견본 이미지 즉시 다운로드 → 이미지 저장(스토리지) →
    DB UPSERT → FAISS 인덱스 재빌드

실행 (project root 기준, .env 에 DATABASE_URL + KIPRIS_* 설정 후):
    ml\\venv\\Scripts\\python.exe -m backend.scripts.collect_pipeline --applicant "삼성전자"
    ml\\venv\\Scripts\\python.exe -m backend.scripts.collect_pipeline --applicants-file shared/famous_brands.txt

옵션:
    --dry-run     API 는 호출하되 다운로드/DB/인덱스는 건드리지 않고 리포트만
    --limit N     출원인당 최대 N건만 처리 (호출 예산 관리)
    --skip-index  인덱스 재빌드 생략 (여러 출원인 연속 수집 후 마지막에 한 번만)
    --mock-xml F  API 대신 저장된 XML 파일로 전체 흐름 테스트 (키 없이 개발용.
                  이미지 다운로드 대신 플레이스홀더 PNG 생성)

TODO.pdf 필수 반영 사항이 코드에 강제되어 있다:
    ① 호출 카운터+초당 딜레이 (kipris_client.limiter)
    ② ImagePath 는 일회성 링크 → 응답 즉시 다운로드
    ③ ApplicationStatus == "등록" 만 수집
    ④ ViennaCode 빈 값(순수 문자상표 가능성) → 제외
    ⑤ (검증 세션 반영) 출원번호 정규화 + 매칭 0건이면 명시적 실패
"""

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.src.core import config, kipris_client, paths  # noqa: E402
from backend.src.core.appno import (  # noqa: E402
    is_trademark_application_number,
    normalize_application_number,
)


def item_to_row(item: dict) -> tuple:
    """API item → trademark UPSERT 파라미터. (migrate 스크립트와 같은 컬럼 순서)"""
    from backend.scripts.migrate_json_to_db import parse_date

    app_no = normalize_application_number(item["ApplicationNumber"])
    return (
        app_no,
        item.get("RegistrationNumber") or None,
        parse_date(item.get("ApplicationDate")),
        parse_date(item.get("RegistrationDate")),
        item.get("Title") or None,           # KIPRIS Title 은 한/영 혼재 — 한글명 슬롯에 원문 저장
        None,                                # 영문명은 공보 상세에서만 확보 가능 — 후속 보강
        item.get("DrawingKindName") or None, # 도형/복합 구분 (오퍼레이션에 따라 없을 수 있음)
        item.get("ApplicantName") or None,
        item.get("RegistrationRightholderName") or None,
        f"{app_no}.png",
        [str(v) for v in item.get("ViennaCode", [])],
        [int(c) for c in item.get("GoodClassificationCode", []) if str(c).isdigit()],
        [str(s) for s in item.get("SimilarCode", [])],
    )


def should_collect(item: dict, report: dict) -> bool:
    """수집 대상 필터 — 제외 사유를 리포트에 집계한다."""
    status_ = item.get("ApplicationStatus", "")
    if status_ != "등록":
        report["제외_미등록"] += 1
        return False
    if not item.get("ViennaCode"):
        report["제외_비엔나없음(문자상표)"] += 1
        return False
    app_no_raw = item.get("ApplicationNumber", "")
    if not is_trademark_application_number(app_no_raw):
        report["제외_상표번호아님"] += 1
        return False
    return True


def make_placeholder_png(dest: Path, label: str) -> None:
    """--mock-xml 테스트용 플레이스홀더 이미지 (실 수집에서는 사용 안 함)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (256, 256), "white")
    ImageDraw.Draw(img).text((20, 110), label[:12], fill="black")
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")


def rebuild_index() -> None:
    """ml/scripts/build_index.py 로 전체 재빌드 (소규모에선 append 보다 안전)."""
    cmd = [
        sys.executable,
        str(paths.ML_ROOT / "scripts" / "build_index.py"),
        "--image-dir", str(paths.IMAGES_DIR),
        "--output-dir", str(paths.ML_DATA_DIR / "index"),
        "--index-name", "kipris",
    ]
    print(f"[인덱스] 재빌드 실행: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=str(paths.ML_ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--applicant", action="append", help="출원인(회사명). 반복 지정 가능")
    group.add_argument("--applicants-file", help="출원인 목록 파일 (줄당 1개, # 주석)")
    group.add_argument("--mock-xml", help="API 대신 사용할 저장된 XML 파일 (개발 테스트)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="출원인당 최대 처리 건수 (0=무제한)")
    ap.add_argument("--skip-index", action="store_true")
    args = ap.parse_args()

    if not args.dry_run and not config.DATABASE_URL:
        print("[오류] DATABASE_URL 미설정 — 수집 결과를 적재할 DB가 필요합니다.", file=sys.stderr)
        return 1

    # ---- 입력 소스 구성 ----
    if args.mock_xml:
        xml_text = Path(args.mock_xml).read_text(encoding="utf-8")
        batches = [("(mock)", kipris_client.parse_items(xml_text))]
    else:
        applicants = args.applicant or [
            line.strip()
            for line in Path(args.applicants_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        batches = []
        for name in applicants:
            print(f"[검색] 출원인: {name} (월 사용량 {kipris_client.limiter.used_this_month()}회)")
            batches.append((name, kipris_client.applicant_search(name)))

    # ---- 수집 ----
    report = {
        "검색결과": 0, "수집": 0, "이미지실패": 0,
        "제외_미등록": 0, "제외_비엔나없음(문자상표)": 0, "제외_상표번호아님": 0,
    }
    rows = []
    for source, items in batches:
        report["검색결과"] += len(items)
        picked = [it for it in items if should_collect(it, report)]
        if args.limit:
            picked = picked[: args.limit]
        for it in picked:
            app_no = normalize_application_number(it["ApplicationNumber"])
            dest = paths.IMAGES_DIR / f"{app_no}.png"
            if args.dry_run:
                print(f"[dry-run] 수집 대상: {app_no} {it.get('Title', '')!r}")
            else:
                try:
                    if args.mock_xml:
                        make_placeholder_png(dest, it.get("Title", app_no))
                    else:
                        # ② 일회성 링크 — 응답 직후 즉시 다운로드
                        image_url = it.get("ImagePath") or it.get("ThumbnailPath", "")
                        if not image_url:
                            raise kipris_client.KiprisError("ImagePath 없음")
                        kipris_client.download_file_now(image_url, dest)
                except Exception as e:
                    report["이미지실패"] += 1
                    print(f"[경고] 이미지 확보 실패({app_no}): {e}", file=sys.stderr)
                    continue
                rows.append(item_to_row(it))
            report["수집"] += 1

    # ⑤ 전부 걸러졌다면 포맷/필터 문제일 가능성 — 조용히 성공으로 끝내지 않는다
    if report["검색결과"] > 0 and report["수집"] == 0:
        print(f"[오류] 검색 {report['검색결과']}건 중 수집 0건 — 필터/포맷 확인 필요: {report}",
              file=sys.stderr)
        return 2

    # ---- DB 적재 ----
    if rows and not args.dry_run:
        import psycopg

        from backend.scripts.migrate_json_to_db import UPSERT_SQL, ensure_database_exists, apply_migrations

        ensure_database_exists(config.DATABASE_URL)
        with psycopg.connect(config.DATABASE_URL) as conn:
            apply_migrations(conn)
            with conn.cursor() as cur:
                cur.executemany(UPSERT_SQL, rows)
            conn.commit()
        print(f"[DB] UPSERT {len(rows)}건 완료")

    # ---- 인덱스 재빌드 ----
    if rows and not args.dry_run and not args.skip_index:
        rebuild_index()

    print(f"[리포트] {report}")
    if not args.dry_run and rows:
        print("[참고] dataset_info(데이터 범위 안내 문구)는 백엔드-6 기준 확정 후 "
              "meta 테이블에서 갱신하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
