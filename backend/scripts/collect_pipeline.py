"""
백엔드-5: KIPRIS 수집 파이프라인 — 한 명령으로
    출원인 검색 API → 견본 이미지 즉시 다운로드 → 이미지 저장(스토리지) →
    DB UPSERT → FAISS 인덱스 재빌드

실행 (project root 기준, .env 에 DATABASE_URL + KIPRIS_* 설정 후):
    ml\\venv\\Scripts\\python.exe -m backend.scripts.collect_pipeline --applicant "삼성전자"
    ml\\venv\\Scripts\\python.exe -m backend.scripts.collect_pipeline --applicants-file shared/famous_brands.txt

옵션:
    --dry-run     API 는 호출하되(쿼터 소모 + 응답 원본 XML 저장) 다운로드/DB/인덱스는
                  건드리지 않고 리포트만
    --limit N     출원인당 최대 N건만 처리 (호출 예산 관리)
    --skip-index  인덱스 재빌드 생략 (여러 출원인 연속 수집 후 마지막에 한 번만)
    --force       기수집 skip 을 무시하고 재수집 (일회성 링크 재호출 주의 — 예산 소모)
    --mock-xml F  API 대신 저장된 XML 파일로 전체 흐름 테스트 (키 없이 개발용.
                  이미지 다운로드 대신 플레이스홀더 PNG 생성)

TODO.pdf 필수 반영 사항이 코드에 강제되어 있다:
    ① 호출 카운터+초당 딜레이 (kipris_client.limiter)
    ② ImagePath 는 일회성 링크 → 응답 즉시 다운로드
    ③ ApplicationStatus == "등록" 만 수집
    ④ ViennaCode 빈 값(순수 문자상표 가능성) → 제외
    ⑤ (검증 세션 반영) 출원번호 정규화 + 매칭 0건이면 명시적 실패

백엔드-6 감사보고서 DoD (본 수집 전 선결 — 초안 §0 / 감사보고서 §6-2·횡단리스크):
    Ⓐ 파싱 전 원본 선저장 — 검색 응답 XML 원본을 파싱 이전에 COLLECT_RAW_XML_DIR 에
       저장하고, 이미지 원본은 storage.local_path 경유로 즉시 저장한다. 파싱 버그로
       재실행해도 일회성 링크(월 쿼터)를 다시 태우지 않는다.
    Ⓑ 기수집 출원번호 skip — DB/이미지 실물/체크포인트 중 하나라도 있으면 검색 결과에서
       건너뛴다(중복 다운로드 = 예산 낭비). 건너뛴 건수를 리포트에 집계. --force 로 무시.
    Ⓒ 레코드별 체크포인트 — 수집 완료한 출원번호를 CHECKPOINT_PATH 에 영속 기록.
       중단(Ctrl-C·예외·쿼터 소진) 후 재실행 시 이어받는다.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.src.core import config, kipris_client, paths, storage  # noqa: E402
from backend.src.core.appno import (  # noqa: E402
    is_trademark_application_number,
    normalize_application_number,
)

# ====================================================================
# 백엔드-6 감사보고서 DoD — 원본 선저장 / 기수집 skip / 레코드별 체크포인트
# (감사보고서 §6-2·횡단리스크, 수집기준 초안 §0)
#
# 세 산출물은 모두 ml/data/ 하위에 둔다 — .gitignore 가 ml/data/ 전체를 무시하므로
# 저작권 KIPRIS 원본/체크포인트가 커밋에 섞이지 않는다(RateLimiter 의 월 카운터
# 파일 kipris_call_count.json 과 같은 관례). 데이터 위치를 MARKLENS_DATA_DIR 로
# 옮기면 이 세 경로도 함께 따라간다.
# ====================================================================

# ③ 원본 선저장: KIPRIS 응답 XML 원본을 파싱 전에 남기는 위치.
#    (이미지 원본은 storage.local_path 경유로 최종 이미지 디렉터리에 즉시 저장)
COLLECT_RAW_XML_DIR: Path = paths.ML_DATA_DIR / "raw_kipris" / "collect" / "xml"

# ① 레코드별 체크포인트: 수집 완료한 출원번호를 파일에 영속 기록(RateLimiter 방식).
#    중단(Ctrl-C·예외·쿼터 소진) 후 재실행 시 이 집합을 읽어 이어받는다.
CHECKPOINT_PATH: Path = paths.ML_DATA_DIR / "collect_checkpoint.json"


# --------------------------------------------------------------------
# ③ 원본(XML) 선저장
# --------------------------------------------------------------------
def save_raw_xml(source: str, xml_text: str) -> Path:
    """검색 응답 XML 원본을 파싱 이전에 디스크에 남긴다.

    근거(초안 §0.3): ImagePath 는 일회성 링크라, 파싱 버그로 재수집하면 링크가
    만료돼 검색 호출을 또 태운다. 원본을 먼저 저장하고 파싱은 로컬에서 하면,
    파싱 실패 시 재검색 없이 저장된 원본에서 다시 파싱할 수 있다.
    """
    safe = re.sub(r"[^0-9A-Za-z가-힣]+", "_", source).strip("_")[:40] or "batch"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    COLLECT_RAW_XML_DIR.mkdir(parents=True, exist_ok=True)
    dest = COLLECT_RAW_XML_DIR / f"{safe}_{ts}.xml"
    dest.write_text(xml_text, encoding="utf-8")
    return dest


def search_batch(source: str) -> list[dict]:
    """출원인 검색(getAdvancedSearch) → 정규화된 item 리스트. 원본 XML 을 파싱 전에 선저장한다.

    본 수집 소스는 항목별검색(advanced_search)이다 — 인증 ServiceKey + 불리언 플래그
    30개(등록만·도형/도형복합만·표장유형 전부)를 실어 보내고, camelCase 응답을
    normalize_advanced_item 으로 파이프라인 정규 키로 바꾼다.

    **dry-run 도 예외가 아니다.** dry-run 은 다운로드·DB 를 건너뛸 뿐 검색 API 는
    실제로 호출해 월 쿼터를 태운다. 그 응답을 버리면 본 수집 때 같은 검색을 다시
    호출하게 되는데, 이는 원본 선저장(DoD Ⓐ)이 막으려는 바로 그 낭비다.
    저장된 원본은 --mock-xml 로 재파싱·검증에 그대로 재사용할 수 있다.
    """
    rows = kipris_client.ADVANCED_DEFAULT_ROWS  # 500(상한) — 같은 건수를 적은 호출로
    collected: list[dict] = []
    total: int | None = None
    for page in range(1, kipris_client.ADVANCED_MAX_PAGES + 1):
        xml_text = kipris_client.advanced_search_raw(source, page_no=page, num_of_rows=rows)
        save_raw_xml(f"{source}_p{page}", xml_text)        # Ⓐ 페이지마다 파싱 전 선저장
        page_items = kipris_client.parse_items(xml_text)   # camelCase 원 항목
        collected.extend(kipris_client.normalize_advanced_item(it) for it in page_items)
        if total is None:
            total = kipris_client.parse_advanced_total_count(xml_text)
        # 마지막 페이지 판정: 빈 페이지이거나, 전체 건수를 다 받았거나, 한 페이지가 덜 찼다.
        if not page_items or len(page_items) < rows or (total is not None and len(collected) >= total):
            break
    else:
        print(f"[경고] {source}: 페이지 상한({kipris_client.ADVANCED_MAX_PAGES})에 걸려 "
              f"{len(collected)}건에서 멈춤 (전체 {total}건) — 남은 건수는 다음 실행에서 이어받는다",
              file=sys.stderr)
    return collected


# --------------------------------------------------------------------
# ① 레코드별 체크포인트
# --------------------------------------------------------------------
def load_checkpoint(path: Path | None = None) -> set[str]:
    """체크포인트 파일에서 이미 수집한 출원번호 집합을 읽는다. 없으면 빈 집합."""
    path = path or CHECKPOINT_PATH
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()  # 파손 파일은 무시하고 처음부터(원본/이미지 skip 이 이중 방어)
    return {str(a) for a in data.get("collected", [])}


def append_checkpoint(app_no: str, path: Path | None = None) -> None:
    """수집 완료한 출원번호 1건을 체크포인트에 원자적으로 추가한다.

    포맷: {"collected": ["<출원번호>", ...], "updated_at": "<ISO8601>"}.
    매 레코드마다 전체를 다시 쓰되(수백~1,000건 규모라 충분), tmp→replace 로
    중단 도중 파일이 반쯤 쓰여 파손되는 것을 막는다.
    """
    path = path or CHECKPOINT_PATH
    collected = load_checkpoint(path)
    if app_no in collected:
        return
    collected.add(app_no)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"collected": sorted(collected),
               "updated_at": datetime.now(timezone.utc).isoformat()}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------
# ② 기수집 출원번호 skip
# --------------------------------------------------------------------
def load_db_app_numbers(database_url: str) -> set[str]:
    """DB 에 이미 있는 출원번호 집합 (기수집 skip 판정용, 읽기 전용 SELECT).

    DB 미설정("")이면 빈 집합. 테스트는 이 함수를 monkeypatch 해 실 DB 접촉을 막는다.
    """
    if not database_url:
        return set()
    import psycopg

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT application_no FROM trademark")
            return {row[0] for row in cur.fetchall()}


def already_collected(app_no: str, image_key: str,
                      checkpoint: set[str], db_existing: set[str]) -> bool:
    """기수집 판정 — 셋 중 하나라도 참이면 검색·다운로드를 건너뛴다(초안 §0.2).

    - 체크포인트에 있음: 이번/이전 실행에서 이미 수집함
    - DB 에 있음: 이미 적재된 권리
    - 이미지 실물 존재(storage.image_exists): 파일시스템 truth (심 경유)
    """
    return (
        app_no in checkpoint
        or app_no in db_existing
        or storage.image_exists(image_key)
    )


# --------------------------------------------------------------------
# DB UPSERT (테스트에서 monkeypatch 로 실 DB 쓰기 차단)
# --------------------------------------------------------------------
def upsert_rows(rows: list, database_url: str) -> None:
    """수집 행을 DB 에 UPSERT 한다. 테스트는 이 함수를 monkeypatch 해 실 DB 를 건드리지 않는다."""
    import psycopg

    from backend.scripts.migrate_json_to_db import (
        UPSERT_SQL,
        apply_migrations,
        ensure_database_exists,
    )

    ensure_database_exists(database_url)
    with psycopg.connect(database_url) as conn:
        apply_migrations(conn)
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, rows)
        conn.commit()


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
    ap.add_argument("--force", action="store_true",
                    help="기수집 skip 을 무시하고 재수집(만료된 링크 재호출 주의 — 예산 소모)")
    args = ap.parse_args()

    if not args.dry_run and not config.DATABASE_URL:
        print("[오류] DATABASE_URL 미설정 — 수집 결과를 적재할 DB가 필요합니다.", file=sys.stderr)
        return 1

    # ---- 입력 소스 구성 ----
    # Ⓐ 원본 선저장은 검색 API 를 호출하는 모든 경로(dry-run 포함)에서 한다 —
    #    dry-run 도 쿼터를 태우므로 응답을 버리면 안 된다(search_batch docstring).
    #    mock-xml 은 원본 파일 자체가 이미 디스크에 있어 요건을 자연히 만족한다.
    if args.mock_xml:
        xml_text = Path(args.mock_xml).read_text(encoding="utf-8")
        # 저장된 원본은 항목별검색(camelCase)일 수 있으므로 search_batch 와 같은
        # 정규화를 거친다. 이미 정규 키(PascalCase)면 normalize 가 그대로 통과시킨다.
        items = kipris_client.parse_items(xml_text)
        batches = [("(mock)", [kipris_client.normalize_advanced_item(it) for it in items])]
    else:
        applicants = args.applicant or [
            line.strip()
            for line in Path(args.applicants_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        batches = []
        for name in applicants:
            print(f"[검색] 출원인: {name} (월 사용량 {kipris_client.limiter.used_this_month()}회)")
            batches.append((name, search_batch(name)))

    # ---- 수집 ----
    report = {
        "검색결과": 0, "수집": 0, "건너뜀_기수집": 0, "이미지실패": 0, "레코드실패": 0,
        "제외_미등록": 0, "제외_비엔나없음(문자상표)": 0, "제외_상표번호아님": 0,
    }
    # ① 체크포인트 이어받기 + ② 기수집 skip 재료. checkpoint 는 이번 실행에서
    #    수집한 건도 계속 더해 같은 배치 내 출원인 간 중복까지 걸러낸다.
    checkpoint = load_checkpoint()
    db_existing = load_db_app_numbers(config.DATABASE_URL) if not args.dry_run else set()
    rows = []
    for source, items in batches:
        report["검색결과"] += len(items)
        picked = [it for it in items if should_collect(it, report)]
        if args.limit:
            picked = picked[: args.limit]
        for it in picked:
            app_no = normalize_application_number(it["ApplicationNumber"])
            image_key = f"{app_no}.png"

            # ② 기수집 skip — DB/이미지 실물/체크포인트 중 하나라도 있으면 건너뛴다
            if not args.force and already_collected(app_no, image_key, checkpoint, db_existing):
                report["건너뜀_기수집"] += 1
                continue

            if args.dry_run:
                print(f"[dry-run] 수집 대상: {app_no} {it.get('Title', '')!r}")
                checkpoint.add(app_no)  # 미리보기 내 중복 표시용 (파일에는 안 씀)
                report["수집"] += 1
                continue

            # ③ 원본(이미지 바이트) 즉시 저장 — 일회성 링크 보호. 파싱/DB 보다 먼저.
            dest = storage.local_path(image_key)
            try:
                if args.mock_xml:
                    make_placeholder_png(dest, it.get("Title", app_no))
                else:
                    image_url = it.get("ImagePath") or it.get("ThumbnailPath", "")
                    if not image_url:
                        raise kipris_client.KiprisError("ImagePath 없음")
                    kipris_client.download_file_now(image_url, dest)
            except Exception as e:
                # 개별 이미지 실패는 배치를 죽이지 않는다. KeyboardInterrupt·쿼터 초과
                # 등 BaseException 은 여기서 잡히지 않고 전파 → 체크포인트로 이어받기.
                report["이미지실패"] += 1
                print(f"[경고] 이미지 확보 실패({app_no}): {e}", file=sys.stderr)
                continue

            # 이 지점부터 이미지 원본은 디스크에 안전히 존재한다. 이후 파싱(행 변환).
            try:
                rows.append(item_to_row(it))
            except Exception as e:
                # 파싱(행 변환) 실패해도 원본 이미지는 남는다 → 버그 수정 후 --force 재처리.
                report["레코드실패"] += 1
                print(f"[경고] 레코드 변환 실패({app_no}) — 원본 이미지는 보존됨: {e}",
                      file=sys.stderr)
                continue

            # ① 원본 저장 + 행 변환 성공 → 출원번호를 체크포인트에 영속 기록
            checkpoint.add(app_no)
            append_checkpoint(app_no)
            report["수집"] += 1

    # ⑤ 검색 결과는 있는데 수집도 skip 도 0이면 필터/포맷 문제 — 조용히 끝내지 않는다.
    #    (기수집 skip 으로 0건이면 정상 — 재실행/증분 수집에서 흔함)
    if report["검색결과"] > 0 and report["수집"] == 0 and report["건너뜀_기수집"] == 0:
        print(f"[오류] 검색 {report['검색결과']}건 중 수집 0건 — 필터/포맷 확인 필요: {report}",
              file=sys.stderr)
        return 2

    # ---- DB 적재 ----
    if rows and not args.dry_run:
        upsert_rows(rows, config.DATABASE_URL)
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
