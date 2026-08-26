"""
백엔드-5: KIPRIS 수집 파이프라인 — 한 명령으로
    출원인 검색 API → 견본 이미지 즉시 다운로드 → 이미지 저장(스토리지) →
    DB UPSERT → FAISS 인덱스 재빌드

실행 (project root 기준, .env 에 DATABASE_URL + KIPRIS_* 설정 후):
    ml\\venv\\Scripts\\python.exe -m backend.scripts.collect_pipeline --applicant "삼성전자"
    ml\\venv\\Scripts\\python.exe -m backend.scripts.collect_pipeline `
        --applicants-file shared/famous_brands.txt

옵션:
    --plan        네트워크/DB/파일 쓰기 없이 입력·환경·최대 호출 예산만 점검
    --dry-run     API 는 호출하되(쿼터 소모 + 응답 원본 XML 저장) 다운로드/DB/인덱스는
                  건드리지 않고 리포트만
    --limit N     출원인당 최대 N건만 처리 (호출 예산 관리)
    --target-total N
                  운영 데이터와 이번 스테이징/DB의 출원번호 합집합을 N건까지만
                  늘리는 전역 신규 레코드 캡. 목표 도달 뒤에는 다음 검색을 호출하지 않는다.
    --max-pages-per-source N
                  출원인별 검색 페이지 호출 하드 캡(1~10). 파일럿은 1 권장.
    --rows-per-page N
                  검색 응답 크기(기본 100, 최대 500). 소량 분산 수집은 100 권장.
    --search-retries N
                  페이지 네트워크 실패 뒤 추가 재시도(기본 1, 최대 3). 각 시도는 쿼터 소모.
    --retry-backoff-seconds S / --search-timeout-seconds S
                  재시도 대기와 검색 요청 1회 타임아웃을 제한된 범위에서 조정.
    --nice-class N 응답의 Nice 류가 N인 레코드만 적재. 반복 지정 가능(1~45).
                  getAdvancedSearch 응답을 받은 뒤 적용하는 로컬 필터라 검색 호출 수를
                  줄이지는 않는다.
    --file-staging F
                  DB가 없는 연구 환경에서만 쓰는 명시적 JSON 스테이징 경로.
                  ml/data/staging/ 아래만 허용하고 운영 메타/인덱스는 변경하지 않는다.
    --skip-index  인덱스 재빌드 생략 (여러 출원인 연속 수집 후 마지막에 한 번만)
    --force       기수집 skip 을 무시하고 재수집 (일회성 링크 재호출 주의 — 예산 소모)
    --mock-xml F  API 대신 저장된 XML 파일로 전체 흐름 테스트 (키 없이 개발용.
                  이미지 다운로드 대신 플레이스홀더 PNG 생성)
    --enrich-biblio  서지상세(getBibliographyDetailInfoSearch)로 유사군을 보강.
                  ⚠ 레코드당 +1회 호출 — 500건 보강 = +500회(월 예산 950의 절반).
                  getAdvancedSearch 응답엔 유사군이 없어 이 옵션 없이는 similarity_codes
                  가 빈 배열로 적재된다. 기본 꺼짐(옵트인).

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
    Ⓑ 기수집 출원번호 skip — DB 또는 체크포인트에 있으면(=적재 완료) 건너뛴다. 이미지가
       이미 있으면 다운로드만 건너뛰고 적재는 진행한다(만료 링크 재호출 방지). --force 로 무시.
    Ⓒ 페이지 체크포인트 — 페이지별 **DB UPSERT 성공 후에만** 출원번호와 다음
       (page, offset)을 CHECKPOINT_PATH 에 기록한다. 인덱스 dirty 마커는 DB 쓰기 전에
       별도 생성하고 publish 성공 뒤 제거해 중단 후 stale index를 자동 복구한다.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterator

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

# ① 페이지 체크포인트: 수집 완료 출원번호와 출원인별 (page, offset)을 영속 기록한다.
#    중단(Ctrl-C·예외·쿼터 소진) 후 재실행 시 정확한 위치에서 이어받는다.
CHECKPOINT_PATH: Path = paths.ML_DATA_DIR / "collect_checkpoint.json"

# DB 반영 후 인덱스 재빌드 전에 중단되었음을 별도 마커로 남긴다. 체크포인트와
# 분리해야 DB UPSERT 실패 시 "수집 완료"로 오인하지 않으면서도 stale index를 복구한다.
INDEX_DIRTY_PATH: Path = paths.ML_DATA_DIR / "index" / ".kipris-index-dirty"
AUTHORITATIVE_KEYS_PATH: Path = (
    paths.ML_DATA_DIR / "index" / "kipris_authoritative_keys.json"
)

# 500건 응답은 KIPRIS 측 처리와 전송이 15초를 넘긴 실측 사례가 있다. 출원인별
# 소량 수집에서는 큰 응답이 필요 없으므로 수집기 기본값만 100건으로 제한한다.
COLLECT_DEFAULT_ROWS: int = 100
SEARCH_DEFAULT_RETRIES: int = 1
SEARCH_DEFAULT_BACKOFF_SEC: float = 2.0
SEARCH_DEFAULT_TIMEOUT_SEC: float = 30.0
SEARCH_MAX_RETRIES: int = 3
SEARCH_MAX_BACKOFF_SEC: float = 60.0
SEARCH_MAX_TIMEOUT_SEC: float = 120.0


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


@dataclass(frozen=True)
class SearchPage:
    source: str
    page_no: int
    items: list[dict]
    total_found: int | None
    has_more: bool


@dataclass(frozen=True)
class SearchFailure:
    """제한된 재시도 뒤에도 가져오지 못한 검색 페이지."""

    source: str
    page_no: int
    attempts: int
    message: str


def _page_signature(items: list[dict]) -> tuple[str, ...]:
    """서버가 pageNo를 무시하고 같은 페이지를 반복하는지 판정한다."""
    return tuple(
        str(item.get("ApplicationNumber") or "").strip()
        or json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        for item in items
    )


def iter_search_pages(
    source: str,
    *,
    start_page: int = 1,
    max_pages: int = kipris_client.ADVANCED_MAX_PAGES,
    rows_per_page: int | None = None,
    max_retries: int = SEARCH_DEFAULT_RETRIES,
    retry_backoff_seconds: float = SEARCH_DEFAULT_BACKOFF_SEC,
    request_timeout_seconds: float = SEARCH_DEFAULT_TIMEOUT_SEC,
) -> Iterator[SearchPage | SearchFailure]:
    """항목별검색을 한 페이지씩 원본 저장→파싱해 전달한다."""
    rows = rows_per_page or min(
        COLLECT_DEFAULT_ROWS,
        kipris_client.ADVANCED_DEFAULT_ROWS,
    )
    seen_signatures: set[tuple[str, ...]] = set()
    for page_no in range(
        max(1, start_page),
        max(1, start_page) + max_pages,
    ):
        xml_text: str | None = None
        last_error = ""
        for attempt in range(max_retries + 1):
            try:
                xml_text = kipris_client.advanced_search_raw(
                    source,
                    page_no=page_no,
                    num_of_rows=rows,
                    request_timeout=request_timeout_seconds,
                )
                break
            except kipris_client.KiprisNetworkError as exc:
                last_error = str(exc)
                if attempt >= max_retries:
                    yield SearchFailure(
                        source=source,
                        page_no=page_no,
                        attempts=attempt + 1,
                        message=last_error,
                    )
                    return
                delay = min(
                    SEARCH_MAX_BACKOFF_SEC,
                    retry_backoff_seconds * (2**attempt),
                )
                print(
                    f"[경고] {source}: page {page_no} 검색 실패({last_error}). "
                    f"{delay:g}초 후 재시도 {attempt + 1}/{max_retries}",
                    file=sys.stderr,
                )
                if delay:
                    time.sleep(delay)

        assert xml_text is not None
        save_raw_xml(f"{source}_p{page_no}", xml_text)
        raw_items = kipris_client.parse_items(xml_text)
        normalized = [kipris_client.normalize_advanced_item(it) for it in raw_items]
        total = kipris_client.parse_advanced_total_count(xml_text)

        signature = _page_signature(normalized)
        if signature and signature in seen_signatures:
            print(
                f"[경고] {source}: 동일한 검색 페이지가 반복되어 page {page_no}에서 중단합니다.",
                file=sys.stderr,
            )
            return
        seen_signatures.add(signature)

        has_more = bool(raw_items) and len(raw_items) >= rows
        if total is not None and page_no * rows >= total:
            has_more = False
        yield SearchPage(source, page_no, normalized, total, has_more)
        if not has_more:
            return

    print(
        f"[경고] {source}: 이번 실행의 페이지 상한({max_pages})에 걸려 "
        "중단했습니다. 저장된 커서에서 다음 실행에 이어받습니다.",
        file=sys.stderr,
    )


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
    collected: list[dict] = []
    for page in iter_search_pages(source):
        if isinstance(page, SearchFailure):
            raise kipris_client.KiprisNetworkError(
                f"KIPRIS 검색 페이지를 {page.attempts}회 시도했지만 받지 못했습니다."
            ) from None
        collected.extend(page.items)
    return collected


# --------------------------------------------------------------------
# ① 레코드별 체크포인트
# --------------------------------------------------------------------
def _read_checkpoint_payload(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_checkpoint_payload(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_checkpoint(path: Path | None = None) -> set[str]:
    """체크포인트 파일에서 이미 수집한 출원번호 집합을 읽는다. 없으면 빈 집합."""
    path = path or CHECKPOINT_PATH
    data = _read_checkpoint_payload(path)
    return {str(a) for a in data.get("collected", [])}


def load_cursor(
    source: str,
    path: Path | None = None,
    *,
    rows_per_page: int | None = None,
) -> tuple[int, int]:
    """출원인별 페이지/offset을 읽고 페이지 크기 변경 시 안전하게 처음부터 재개한다."""
    data = _read_checkpoint_payload(path or CHECKPOINT_PATH)
    cursor = data.get("cursors", {}).get(source, {})
    try:
        page = max(1, int(cursor.get("page", 1)))
        offset = max(0, int(cursor.get("offset", 0)))
    except (AttributeError, TypeError, ValueError):
        return 1, 0

    if rows_per_page is not None and cursor:
        # schema v2까지는 수집기의 유일한 페이지 크기가 500건이었다.
        stored_rows = cursor.get(
            "rows_per_page",
            kipris_client.ADVANCED_DEFAULT_ROWS,
        )
        try:
            stored_rows = int(stored_rows)
        except (TypeError, ValueError):
            stored_rows = -1
        if stored_rows != rows_per_page:
            print(
                f"[경고] {source}: 체크포인트 페이지 크기({stored_rows})와 "
                f"현재 설정({rows_per_page})이 달라 1페이지부터 다시 확인합니다. "
                "기수집 출원번호는 중복 적재하지 않습니다.",
                file=sys.stderr,
            )
            return 1, 0
    return page, offset


def update_checkpoint(
    app_nos: list[str],
    *,
    source: str | None = None,
    cursor: tuple[int, int] | None = None,
    rows_per_page: int | None = None,
    source_complete: bool = False,
    path: Path | None = None,
) -> None:
    """UPSERT 완료 출원번호와 다음 검색 위치를 한 번에 원자적으로 기록한다."""
    path = path or CHECKPOINT_PATH
    payload = _read_checkpoint_payload(path)
    collected = {str(a) for a in payload.get("collected", [])}
    collected.update(str(a) for a in app_nos)
    payload["schema_version"] = 3
    payload["collected"] = sorted(collected)

    cursors = payload.get("cursors")
    if not isinstance(cursors, dict):
        cursors = {}
    if source:
        if source_complete:
            cursors.pop(source, None)
        elif cursor is not None:
            cursor_payload = {"page": cursor[0], "offset": cursor[1]}
            if rows_per_page is not None:
                cursor_payload["rows_per_page"] = rows_per_page
            cursors[source] = cursor_payload
    payload["cursors"] = cursors
    _write_checkpoint_payload(payload, path)


def append_checkpoint(app_no: str, path: Path | None = None) -> None:
    """기존 호출자 호환용: 수집 완료 출원번호 1건을 원자적으로 추가한다."""
    update_checkpoint([app_no], path=path)


def mark_index_dirty(path: Path | None = None) -> None:
    """DB가 바뀌기 직전에 stale-index 복구 마커를 원자적으로 생성한다."""
    path = path or INDEX_DIRTY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    os.replace(tmp, path)


def clear_index_dirty(path: Path | None = None) -> None:
    """인덱스 publish 성공 뒤 dirty 마커를 제거한다."""
    (path or INDEX_DIRTY_PATH).unlink(missing_ok=True)


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


def load_db_image_keys(database_url: str) -> set[str]:
    """인덱스에 포함할 DB image_key 권위 목록을 읽는다."""
    import psycopg

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT image_key FROM trademark WHERE image_key IS NOT NULL")
            return {str(row[0]).strip() for row in cur.fetchall() if str(row[0]).strip()}


def export_authoritative_keys(
    database_url: str,
    path: Path | None = None,
) -> Path:
    """DB image_key를 검증해 build_index용 UTF-8 JSON manifest로 원자 저장한다."""
    path = path or AUTHORITATIVE_KEYS_PATH
    keys: list[str] = []
    for raw_key in load_db_image_keys(database_url):
        normalized = raw_key.replace("\\", "/")
        candidate = PurePosixPath(normalized)
        if (
            candidate.is_absolute()
            or not normalized
            or any(part in ("", ".", "..") for part in candidate.parts)
            or candidate.as_posix() != normalized
            or ":" in normalized
            or candidate.suffix.lower() not in {".jpg", ".jpeg", ".png"}
        ):
            raise ValueError(f"DB image_key가 안전한 상대 이미지 경로가 아닙니다: {raw_key!r}")
        keys.append(normalized)

    payload = {
        "schema_version": 1,
        "source": "database.image_key",
        "image_keys": sorted(set(keys)),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _validated_image_keys(raw_keys: list[str] | set[str]) -> list[str]:
    """인덱스 authoritative manifest에 넣을 상대 이미지 키를 검증한다."""
    keys: list[str] = []
    for raw_key in raw_keys:
        normalized = str(raw_key).strip().replace("\\", "/")
        candidate = PurePosixPath(normalized)
        if (
            candidate.is_absolute()
            or not normalized
            or any(part in ("", ".", "..") for part in candidate.parts)
            or candidate.as_posix() != normalized
            or ":" in normalized
            or candidate.suffix.lower() not in {".jpg", ".jpeg", ".png"}
        ):
            raise ValueError(f"안전한 상대 이미지 경로가 아닙니다: {raw_key!r}")
        keys.append(normalized)
    return sorted(set(keys))


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_staging_arg(raw: str) -> Path:
    """연구 스테이징을 ml/data/staging 아래 JSON 파일로 제한한다."""
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    candidate = candidate.resolve()
    staging_root = (paths.ML_DATA_DIR / "staging").resolve()
    try:
        candidate.relative_to(staging_root)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--file-staging 은 {staging_root} 아래 경로여야 합니다."
        ) from exc
    if candidate.suffix.lower() != ".json":
        raise argparse.ArgumentTypeError("--file-staging 파일은 .json 이어야 합니다.")
    if candidate == paths.TRADEMARK_META_PATH.resolve():
        raise argparse.ArgumentTypeError("운영 상표 메타 파일을 스테이징으로 지정할 수 없습니다.")
    return candidate


def staging_authoritative_path(path: Path) -> Path:
    return path.with_name(path.stem + ".authoritative_keys.json")


def staging_checkpoint_path(path: Path) -> Path:
    return path.with_name(path.stem + ".checkpoint.json")


def staging_dirty_path(path: Path) -> Path:
    return path.with_name(path.stem + ".dirty")


def staging_image_dir(path: Path) -> Path:
    return path.with_name(path.stem + "_images")


def staging_image_path(path: Path, image_key: str) -> Path:
    return staging_image_dir(path) / image_key


def _read_metadata_payload(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"스테이징 메타데이터를 읽을 수 없습니다: {path.name}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("trademarks"), list):
        raise ValueError("스테이징 메타데이터에는 trademarks 배열이 필요합니다.")
    return payload


def _records_by_application_number(payload: dict) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for index, record in enumerate(payload["trademarks"], start=1):
        if not isinstance(record, dict) or not record.get("출원번호"):
            raise ValueError(f"스테이징 {index}번째 레코드에 출원번호가 없습니다.")
        app_no = normalize_application_number(record["출원번호"])
        if app_no in records:
            raise ValueError(f"스테이징에 중복 출원번호가 있습니다: {app_no}")
        records[app_no] = record
    return records


def _row_to_staging_record(row: tuple) -> dict:
    return {
        "출원번호": row[0],
        "등록번호": row[1],
        "이미지파일": row[9],
        "출원일자": row[2],
        "등록일자": row[3],
        "상표한글명": row[4],
        "상표영문명": row[5],
        "상표구분": row[6],
        "출원인": row[7],
        "최종권리자": row[8],
        "비엔나코드": row[10],
        "류": row[11],
        "유사군": row[12],
    }


def _canonical_record(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _initial_staging_payload() -> dict:
    return {
        "dataset_info": {
            "총_상표수": 0,
            "데이터_기준": "연구용 파일 스테이징(운영 데이터 미포함)",
        },
        "trademarks": [],
    }


def inspect_file_staging(path: Path) -> tuple[bool, str | None]:
    """기존 스테이징과 authoritative manifest가 일치하는지 읽기 전용 점검한다."""
    dirty = staging_dirty_path(path)
    authoritative = staging_authoritative_path(path)
    if dirty.exists():
        return False, f"이전 쓰기 미완료 dirty marker가 남아 있습니다: {dirty.name}"
    if path.exists() != authoritative.exists():
        return False, "스테이징 메타와 authoritative manifest 중 하나만 존재합니다."
    if not path.exists():
        return True, None
    try:
        payload = _read_metadata_payload(path)
        records = _records_by_application_number(payload)
        expected = _validated_image_keys(
            [record.get("이미지파일", "") for record in records.values()]
        )
        manifest = json.loads(authoritative.read_text(encoding="utf-8"))
        actual = _validated_image_keys(manifest.get("image_keys", []))
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        return False, str(exc)
    if expected != actual:
        return False, "스테이징 메타와 authoritative image key 목록이 다릅니다."
    if manifest.get("metadata_sha256") != _sha256_file(path):
        return False, "스테이징 메타 SHA-256이 authoritative manifest와 다릅니다."
    image_root = staging_image_dir(path)
    disk_keys = sorted(
        candidate.relative_to(image_root).as_posix()
        for candidate in image_root.rglob("*")
        if candidate.is_file()
        and candidate.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ) if image_root.exists() else []
    if expected != disk_keys:
        return False, "스테이징 authoritative key와 전용 이미지 디렉터리가 다릅니다."
    image_hashes = manifest.get("image_hashes")
    if not isinstance(image_hashes, dict) or set(image_hashes) != set(expected):
        return False, "스테이징 이미지 해시 목록이 authoritative key와 다릅니다."
    for key in expected:
        if image_hashes[key] != _sha256_file(staging_image_path(path, key)):
            return False, f"스테이징 이미지 SHA-256 불일치: {key}"
    return True, None


def load_file_staging_app_numbers(path: Path) -> set[str]:
    payload = _read_metadata_payload(path) if path.exists() else _initial_staging_payload()
    application_numbers = set(_records_by_application_number(payload))
    if paths.TRADEMARK_META_PATH.exists():
        runtime_payload = _read_metadata_payload(paths.TRADEMARK_META_PATH)
        application_numbers.update(_records_by_application_number(runtime_payload))
    return application_numbers


def merge_file_staging_rows(rows: list[tuple], path: Path) -> tuple[int, int]:
    """DB 행을 연구 JSON에 원자 병합한다. 기존 값 충돌은 덮어쓰지 않는다."""
    payload = _read_metadata_payload(path) if path.exists() else _initial_staging_payload()
    existing = _records_by_application_number(payload)
    inserted = 0
    unchanged = 0
    for row in rows:
        record = _row_to_staging_record(row)
        app_no = record["출원번호"]
        previous = existing.get(app_no)
        if previous is not None:
            if _canonical_record(previous) == _canonical_record(record):
                unchanged += 1
                continue
            raise ValueError(
                f"출원번호 {app_no}의 기존 스테이징 내용과 새 응답이 다릅니다. "
                "자동 덮어쓰지 않았습니다."
            )
        existing[app_no] = record
        inserted += 1

    ordered_records = [existing[key] for key in sorted(existing)]
    image_keys = _validated_image_keys(
        [record.get("이미지파일", "") for record in ordered_records]
    )
    missing_images = [
        key for key in image_keys if not staging_image_path(path, key).is_file()
    ]
    if missing_images:
        raise ValueError(
            f"스테이징 authoritative key에 이미지 실물이 없습니다: {missing_images[:5]}"
        )

    dataset_info = dict(payload.get("dataset_info") or {})
    dataset_info["총_상표수"] = len(ordered_records)
    payload = {
        **payload,
        "dataset_info": dataset_info,
        "trademarks": ordered_records,
        "staging_info": {
            "schema_version": 1,
            "mode": "research-file-staging",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "record_count": len(ordered_records),
        },
    }
    authoritative_payload = {
        "schema_version": 1,
        "source": path.name,
        "image_keys": image_keys,
        "image_hashes": {
            key: _sha256_file(staging_image_path(path, key)) for key in image_keys
        },
    }

    dirty = staging_dirty_path(path)
    dirty.parent.mkdir(parents=True, exist_ok=True)
    dirty.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    _atomic_write_json(path, payload)
    authoritative_payload["metadata_sha256"] = _sha256_file(path)
    _atomic_write_json(staging_authoritative_path(path), authoritative_payload)
    dirty.unlink()
    return inserted, unchanged


def already_collected(app_no: str, checkpoint: set[str], db_existing: set[str]) -> bool:
    """**적재 완료** 판정 — 참이면 이 레코드를 통째로 건너뛴다(초안 §0.2).

    - DB 에 있음: 이미 적재된 권리
    - 체크포인트에 있음: 이전 실행에서 적재까지 끝난 권리(체크포인트는 UPSERT 성공 후에만 쓴다)

    ⚠ **이미지 실물 존재는 여기에 넣지 않는다.** 이미지는 DB 적재보다 먼저 저장되므로
    "이미지 있음"이 "적재됨"을 뜻하지 않는다. 이미지만 있고 DB에 없는 레코드를 skip 하면
    그 레코드는 영원히 적재되지 않는다(실측 결함, 2026-07-10). 이미지 재사용 판정은
    `storage.image_exists` 로 다운로드 직전에 따로 한다 — 일회성 링크를 아끼는 용도.
    """
    return app_no in checkpoint or app_no in db_existing


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


def refresh_dataset_info(database_url: str) -> dict:
    """수집 성공 후 meta.dataset_info 를 DB 실측으로 갱신한다 (db 모드 전용).

    과거에는 수동 갱신 안내만 출력해, 수집 뒤 /health·검색 응답의 "데이터 범위"
    문구가 실제 적재 건수와 어긋난 채 방치될 수 있었다. 데이터_기준 문구는 기존
    값을 보존하고 건수·출원일자 범위·생성일자만 실측으로 다시 쓴다.
    테스트는 upsert_rows 처럼 이 함수를 monkeypatch 해 실 DB 를 건드리지 않는다.
    """
    from datetime import datetime, timezone

    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*), min(application_date), max(application_date) "
                "FROM trademark"
            )
            total, min_date, max_date = cur.fetchone()
            cur.execute("SELECT value FROM meta WHERE key = 'dataset_info'")
            row = cur.fetchone()
            existing = row[0] if row and isinstance(row[0], dict) else {}
            if min_date and max_date:
                date_range = f"{min_date.year} ~ {max_date.year}"
            else:
                date_range = existing.get("출원일자_범위", "")
            info = {
                "총_상표수": int(total),
                "출원일자_범위": date_range,
                "데이터_기준": existing.get("데이터_기준", "KIPRIS 등록상표 공보"),
                "생성일자": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            }
            cur.execute(
                "INSERT INTO meta (key, value) VALUES ('dataset_info', %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (Jsonb(info),),
            )
        conn.commit()
    return info


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
        # 상표구분 — getAdvancedSearch 미제공. --enrich-biblio 시 서지상세로 충전,
        # 미보강 수집에서는 의도된 NULL 이다.
        item.get("DrawingKindName") or None,
        item.get("ApplicantName") or None,
        item.get("RegistrationRightholderName") or None,
        f"{app_no}.png",
        [str(v) for v in item.get("ViennaCode", [])],
        [int(c) for c in item.get("GoodClassificationCode", []) if str(c).isdigit()],
        [str(s) for s in item.get("SimilarCode", [])],
    )


def enrich_item(item: dict) -> None:
    """서지상세(getBibliographyDetailInfoSearch)로 유사군을 보강한다 — 레코드당 +1회 호출.

    getAdvancedSearch 응답엔 유사군이 없어, 이 오퍼레이션만 출원번호로 유사군·지정상품을
    준다(X4 상품 견련성 축·다빈-1 라벨표 학습의 경로). item 을 제자리에서 갱신한다:
      - SimilarCode 를 서지상세의 유사군으로 덮어쓴다(빈 배열이었음).
      - GoodClassificationCode(류)가 비어 있으면 서지상세 mainCode 로 채운다.
      - DrawingKindName(표장구분)이 비어 있으면 서지상세 trademarkDivisionCode 로 채운다.

    원본 XML 은 파싱 전에 선저장한다(DoD Ⓐ) — 라벨에 출원번호를 넣어 어느 레코드 것인지
    남긴다. 예산 소진(CallBudgetExceeded)이나 파싱 오류는 호출자로 전파한다 —
    호출자(main)가 CallBudgetExceeded 는 이어받기용으로 전파, 그 외 실패는 '보강실패'로 집계.
    """
    app_no = normalize_application_number(item["ApplicationNumber"])
    raw = kipris_client.bibliography_detail_raw(app_no)
    save_raw_xml(f"biblio_{app_no}", raw)          # Ⓐ 파싱 전 원본 선저장
    detail = kipris_client.parse_bibliography_detail(raw)
    item["SimilarCode"] = detail["similarity_codes"]
    if not item.get("GoodClassificationCode") and detail["nice_classes"]:
        item["GoodClassificationCode"] = [str(c) for c in detail["nice_classes"]]
    if not item.get("DrawingKindName") and detail.get("mark_type"):
        item["DrawingKindName"] = detail["mark_type"]


def _item_nice_classes(item: dict) -> set[int]:
    """응답의 Nice 류를 유효한 정수 집합으로 정규화한다."""
    classes: set[int] = set()
    for raw in item.get("GoodClassificationCode", []):
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if 1 <= value <= 45:
            classes.add(value)
    return classes


def should_collect(
    item: dict,
    report: dict,
    target_nice_classes: set[int] | None = None,
) -> bool:
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
    if target_nice_classes and not (_item_nice_classes(item) & target_nice_classes):
        report["제외_대상류아님"] = report.get("제외_대상류아님", 0) + 1
        return False
    return True


def record_nice_distribution(item: dict, report: dict) -> None:
    """신규 수집 레코드의 류 분포를 기록한다(복수 류는 각각 1회 집계)."""
    distribution = report.setdefault("류별_수집", {})
    for nice_class in sorted(_item_nice_classes(item)):
        key = str(nice_class)
        distribution[key] = distribution.get(key, 0) + 1


def _nice_class_arg(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Nice 류는 1~45 정수여야 합니다.") from exc
    if not 1 <= value <= 45:
        raise argparse.ArgumentTypeError("Nice 류는 1~45 범위여야 합니다.")
    return value


def _max_pages_arg(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("페이지 상한은 정수여야 합니다.") from exc
    if not 1 <= value <= kipris_client.ADVANCED_MAX_PAGES:
        raise argparse.ArgumentTypeError(
            f"페이지 상한은 1~{kipris_client.ADVANCED_MAX_PAGES} 범위여야 합니다."
        )
    return value


def _rows_per_page_arg(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("페이지당 건수는 정수여야 합니다.") from exc
    if not 1 <= value <= kipris_client.ADVANCED_MAX_ROWS:
        raise argparse.ArgumentTypeError(
            f"페이지당 건수는 1~{kipris_client.ADVANCED_MAX_ROWS} 범위여야 합니다."
        )
    return value


def _search_retries_arg(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("검색 재시도 횟수는 정수여야 합니다.") from exc
    if not 0 <= value <= SEARCH_MAX_RETRIES:
        raise argparse.ArgumentTypeError(
            f"검색 재시도 횟수는 0~{SEARCH_MAX_RETRIES} 범위여야 합니다."
        )
    return value


def _bounded_float_arg(
    raw: str,
    *,
    label: str,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label}은 숫자여야 합니다.") from exc
    if not minimum <= value <= maximum:
        raise argparse.ArgumentTypeError(
            f"{label}은 {minimum:g}~{maximum:g} 범위여야 합니다."
        )
    return value


def _retry_backoff_arg(raw: str) -> float:
    return _bounded_float_arg(
        raw,
        label="재시도 백오프(초)",
        minimum=0,
        maximum=SEARCH_MAX_BACKOFF_SEC,
    )


def _search_timeout_arg(raw: str) -> float:
    return _bounded_float_arg(
        raw,
        label="검색 타임아웃(초)",
        minimum=1,
        maximum=SEARCH_MAX_TIMEOUT_SEC,
    )


def _target_total_arg(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("목표 총량은 정수여야 합니다.") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("목표 총량은 1 이상의 정수여야 합니다.")
    return value


def _deduplicate_sources(raw_sources: list[str]) -> tuple[list[str], int]:
    """빈 줄과 중복 출원인을 제거하되 최초 입력 순서를 유지한다."""
    sources: list[str] = []
    seen: set[str] = set()
    duplicate_count = 0
    for raw in raw_sources:
        source = raw.strip()
        if not source:
            continue
        key = source.casefold()
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        sources.append(source)
    return sources, duplicate_count


def build_collection_plan(
    *,
    source_count: int,
    duplicate_source_count: int,
    limit: int,
    target_nice_classes: set[int],
    enrich_biblio: bool,
    mock_xml: bool,
    file_staging: Path | None,
    max_pages_per_source: int,
    rows_per_page: int,
    search_retries: int,
    retry_backoff_seconds: float,
    search_timeout_seconds: float,
    target_total: int | None = None,
) -> dict:
    """외부 호출 없이 수집 준비 상태와 보수적 호출 예산을 계산한다."""
    if mock_xml:
        search_min = 0
        search_max = 0
        record_cap = 0
    else:
        search_min = source_count
        search_max = (
            source_count * max_pages_per_source * (search_retries + 1)
        )
        record_cap = source_count * (
            limit or rows_per_page * max_pages_per_source
        )

    current_total: int | None = None
    target_remaining: int | None = None
    target_already_met = False
    if target_total is not None:
        if file_staging is not None:
            try:
                current_total = len(load_file_staging_app_numbers(file_staging))
            except (OSError, ValueError):
                # inspect_file_staging below exposes the actionable integrity error.
                current_total = None
        if current_total is not None:
            target_remaining = max(0, target_total - current_total)
            target_already_met = target_remaining == 0
            record_cap = min(record_cap, target_remaining)
            if target_already_met:
                search_min = 0
                search_max = 0
        else:
            # DB count is intentionally not read in --plan. Zero existing rows is the
            # conservative upper bound for the number of records that may be added.
            record_cap = min(record_cap, target_total)

    enrich_max = record_cap if enrich_biblio else 0
    used: int | None = None
    used_today: int | None = None
    counter_error: str | None = None
    try:
        used = kipris_client.limiter.used_this_month()
        used_today = kipris_client.limiter.used_today()
    except kipris_client.KiprisError as exc:
        counter_error = type(exc).__name__

    budget = kipris_client.MONTHLY_CALL_BUDGET
    remaining = max(0, budget - used) if used is not None else None
    counted_max = search_max + enrich_max

    # 일일 예산은 월 예산과 별개의 가드다(0 이하면 비활성). 여기서 검사하지 않으면
    # 월 잔여만 보고 통과시킨 뒤 예산이 걸리는 호출에서 [중단](exit 3)으로 끝난다.
    daily_budget = kipris_client.DAILY_CALL_BUDGET
    daily_enabled = daily_budget > 0
    daily_remaining = (
        max(0, daily_budget - used_today)
        if daily_enabled and used_today is not None
        else None
    )
    daily_allows_preview = not daily_enabled or (
        daily_remaining is not None and daily_remaining >= search_min
    )

    warnings: list[str] = []
    if daily_enabled and daily_remaining is not None and not target_already_met:
        if daily_remaining < search_min:
            warnings.append(
                "오늘 남은 KIPRIS 호출 예산이 부족합니다 "
                f"(일일 {daily_budget}회 중 {used_today}회 사용, 최소 필요 {search_min}회). "
                "KIPRIS_DAILY_BUDGET 을 올리거나 자정(UTC) 초기화 후 다시 실행하세요."
            )
        elif counted_max > daily_remaining:
            warnings.append(
                f"예상 최대 호출 {counted_max}회가 오늘 남은 예산 {daily_remaining}회"
                f"(일일 {daily_budget}회 중 {used_today}회 사용)를 초과합니다. "
                "KIPRIS_DAILY_BUDGET 을 올리거나, 일일 예산이 소진되면 [중단] 후 "
                "다음 날 재실행 시 커서에서 이어받게 됩니다."
            )

    endpoint_safe = True
    endpoint_error: str | None = None
    try:
        kipris_client._validate_kipris_url(  # noqa: SLF001 - offline preflight
            kipris_client.ADVANCED_SEARCH_URL,
            "KIPRIS_APPLICANT_SEARCH_URL",
        )
        if enrich_biblio:
            kipris_client._validate_kipris_url(  # noqa: SLF001 - offline preflight
                kipris_client.BIBLIO_DETAIL_URL,
                "KIPRIS_BIBLIO_DETAIL_URL",
            )
    except kipris_client.KiprisConfigError as exc:
        endpoint_safe = False
        endpoint_error = str(exc)

    key_configured = bool(kipris_client.ACCESS_KEY)
    database_configured = bool(config.DATABASE_URL)
    staging_ready = False
    staging_error: str | None = None
    if file_staging is not None:
        staging_ready, staging_error = inspect_file_staging(file_staging)
    ready_for_api_preview = target_already_met or (
        not mock_xml
        and source_count > 0
        and key_configured
        and endpoint_safe
        and remaining is not None
        and remaining >= search_min
        and daily_allows_preview
    )
    ready_for_collection = ready_for_api_preview and (
        database_configured or staging_ready
    )

    planned_if_limit_reached: int | None = None
    if not mock_xml and limit:
        planned_if_limit_reached = (
            source_count * (search_retries + 1) + enrich_max
        )

    return {
        "network_calls_executed": 0,
        "source_count": source_count,
        "duplicate_sources_removed": duplicate_source_count,
        "target_nice_classes": sorted(target_nice_classes),
        "nice_filter_scope": "client-side-after-search" if target_nice_classes else "none",
        "limit_per_applicant": limit or None,
        "target_total": target_total,
        "known_existing_total": current_total,
        "target_remaining": target_remaining,
        "target_already_met": target_already_met,
        "max_pages_per_source": max_pages_per_source,
        "rows_per_page": rows_per_page,
        "search_retries_per_page": search_retries,
        "search_attempts_per_page_hard_max": search_retries + 1,
        "retry_backoff_seconds": retry_backoff_seconds,
        "search_timeout_seconds": search_timeout_seconds,
        "enrich_biblio": enrich_biblio,
        "estimated_calls": {
            "search_min": search_min,
            "search_hard_max": search_max,
            "biblio_hard_max": enrich_max,
            "counted_hard_max": counted_max,
            "if_limit_reached": planned_if_limit_reached,
            "image_downloads_counted_locally": False,
        },
        "quota": {
            "monthly_budget": budget,
            "used": used,
            "remaining": remaining,
            "daily_budget": daily_budget,
            "used_today": used_today,
            "daily_remaining": daily_remaining,
            "counter_error": counter_error,
            "hard_max_fits": remaining is not None and counted_max <= remaining,
            "daily_hard_max_fits": not daily_enabled or (
                daily_remaining is not None and counted_max <= daily_remaining
            ),
        },
        "environment": {
            "kipris_key_configured": key_configured,
            "api_endpoint_safe": endpoint_safe,
            "api_endpoint_error": endpoint_error,
            "database_configured": database_configured,
            "file_staging_configured": file_staging is not None,
            "file_staging_ready": staging_ready,
            "file_staging_error": staging_error,
            "storage_target": "file-staging" if file_staging is not None else "database",
        },
        "ready_for_api_preview": ready_for_api_preview,
        "ready_for_collection": ready_for_collection,
        "warnings": warnings,
    }


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
    if AUTHORITATIVE_KEYS_PATH.exists():
        cmd.extend(["--authoritative-keys", str(AUTHORITATIVE_KEYS_PATH)])
    print(f"[인덱스] 재빌드 실행: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=str(paths.ML_ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description="KIPRIS 상표 이미지 수집 파이프라인")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--applicant", action="append", help="출원인(회사명). 반복 지정 가능")
    group.add_argument("--applicants-file", help="출원인 목록 파일 (줄당 1개, # 주석)")
    group.add_argument("--mock-xml", help="API 대신 사용할 저장된 XML 파일 (개발 테스트)")
    ap.add_argument(
        "--plan",
        action="store_true",
        help="네트워크/DB/파일 쓰기 없이 입력·환경·호출 예산만 점검",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="검색 API는 실제 호출(쿼터 소모)하되 다운로드/DB/인덱스는 생략",
    )
    ap.add_argument("--limit", type=int, default=0, help="출원인당 최대 처리 건수 (0=무제한)")
    ap.add_argument(
        "--target-total",
        type=_target_total_arg,
        metavar="N",
        help=(
            "운영+스테이징/DB 출원번호 합집합의 목표 총량. "
            "남은 신규 건수만 수집하고 목표 도달 시 다음 검색을 호출하지 않음"
        ),
    )
    ap.add_argument(
        "--max-pages-per-source",
        type=_max_pages_arg,
        default=kipris_client.ADVANCED_MAX_PAGES,
        metavar="N",
        help=f"출원인별 검색 페이지 하드 캡(1~{kipris_client.ADVANCED_MAX_PAGES})",
    )
    ap.add_argument(
        "--rows-per-page",
        type=_rows_per_page_arg,
        default=min(COLLECT_DEFAULT_ROWS, kipris_client.ADVANCED_DEFAULT_ROWS),
        metavar="N",
        help=(
            f"검색 페이지당 응답 건수(1~{kipris_client.ADVANCED_MAX_ROWS}, "
            f"기본 {COLLECT_DEFAULT_ROWS}; 소량 분산 수집에서는 500보다 타임아웃 위험이 낮음)"
        ),
    )
    ap.add_argument(
        "--search-retries",
        type=_search_retries_arg,
        default=SEARCH_DEFAULT_RETRIES,
        metavar="N",
        help=(
            f"검색 페이지 네트워크 실패 후 추가 재시도(0~{SEARCH_MAX_RETRIES}, "
            f"기본 {SEARCH_DEFAULT_RETRIES}; 각 시도는 월 호출량에 포함)"
        ),
    )
    ap.add_argument(
        "--retry-backoff-seconds",
        type=_retry_backoff_arg,
        default=SEARCH_DEFAULT_BACKOFF_SEC,
        metavar="SECONDS",
        help="검색 재시도 지수 백오프의 첫 대기 시간(초)",
    )
    ap.add_argument(
        "--search-timeout-seconds",
        type=_search_timeout_arg,
        default=SEARCH_DEFAULT_TIMEOUT_SEC,
        metavar="SECONDS",
        help="KIPRIS 검색 요청 1회 타임아웃(초)",
    )
    ap.add_argument(
        "--nice-class",
        type=_nice_class_arg,
        action="append",
        default=[],
        metavar="N",
        help="응답 후 적용할 Nice 류(1~45). 반복 지정 가능",
    )
    ap.add_argument(
        "--file-staging",
        type=_file_staging_arg,
        metavar="PATH",
        help="DB 대신 쓸 연구 JSON. ml/data/staging 아래 경로만 허용",
    )
    ap.add_argument("--skip-index", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="기수집 skip 을 무시하고 재수집(만료 링크 및 예산 주의)")
    ap.add_argument("--enrich-biblio", action="store_true",
                    help="서지상세로 유사군 보강. 레코드당 +1회 호출 "
                         "(500건=+500회, 월 예산 950의 절반). 기본 꺼짐(옵트인)")
    args = ap.parse_args()

    if args.plan and args.dry_run:
        ap.error("--plan 과 --dry-run 은 함께 쓸 수 없습니다.")
    if args.file_staging and args.force:
        ap.error(
            "--file-staging 은 기존 레코드를 덮어쓰지 않으므로 "
            "--force 와 함께 쓸 수 없습니다."
        )
    if args.target_total is not None and args.force:
        ap.error("--target-total 은 신규 레코드 상한이므로 --force 와 함께 쓸 수 없습니다.")
    if args.target_total is not None and args.dry_run and not args.file_staging:
        ap.error(
            "DB를 읽지 않는 --dry-run 에서는 --target-total 을 안전하게 계산할 수 없습니다. "
            "--file-staging 을 지정하거나 --plan 으로 먼저 점검하세요."
        )

    # --mock-xml 은 "키 없이 오프라인 개발"용인데 --enrich-biblio 는 실 API 를 부른다.
    # 조합을 허용하면 오프라인인 줄 알고 돌리다 예산을 태운다(실측 지적, 2026-07-10).
    if args.mock_xml and args.enrich_biblio:
        ap.error(
            "--mock-xml 은 오프라인 개발용이라 "
            "--enrich-biblio(실 API 호출)와 함께 쓸 수 없습니다."
        )
    if args.limit < 0:
        ap.error("--limit 은 0 이상의 정수여야 합니다.")

    # ---- 입력 소스 구성 ----
    if args.mock_xml:
        xml_text = Path(args.mock_xml).read_text(encoding="utf-8")
        items = kipris_client.parse_items(xml_text)
        mock_items = [kipris_client.normalize_advanced_item(it) for it in items]
        sources = ["(mock)"]
        duplicate_source_count = 0
    else:
        raw_sources = args.applicant or [
            line.strip()
            for line in Path(args.applicants_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        sources, duplicate_source_count = _deduplicate_sources(raw_sources)
        if not sources:
            print("[오류] 수집할 출원인이 없습니다.", file=sys.stderr)
            return 1

    target_nice_classes = set(args.nice_class)
    if args.plan:
        plan = build_collection_plan(
            source_count=len(sources),
            duplicate_source_count=duplicate_source_count,
            limit=args.limit,
            target_nice_classes=target_nice_classes,
            enrich_biblio=args.enrich_biblio,
            mock_xml=bool(args.mock_xml),
            file_staging=args.file_staging,
            max_pages_per_source=args.max_pages_per_source,
            rows_per_page=args.rows_per_page,
            search_retries=args.search_retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
            search_timeout_seconds=args.search_timeout_seconds,
            target_total=args.target_total,
        )
        print("[계획] " + json.dumps(plan, ensure_ascii=False, sort_keys=True))
        for warning in plan["warnings"]:
            print(f"[경고] {warning}", file=sys.stderr)
        return 0

    if args.file_staging:
        staging_ready, staging_error = inspect_file_staging(args.file_staging)
        if not staging_ready:
            print(f"[오류] 파일 스테이징 점검 실패: {staging_error}", file=sys.stderr)
            return 1

    if not args.dry_run and not config.DATABASE_URL and not args.file_staging:
        print("[오류] DATABASE_URL 미설정 — 수집 결과를 적재할 DB가 필요합니다.", file=sys.stderr)
        return 1

    # ---- 페이지 단위 수집 ----
    report = {
        "검색결과": 0, "수집": 0, "건너뜀_기수집": 0, "이미지_재사용": 0,
        "이미지실패": 0, "레코드실패": 0, "보강": 0, "보강실패": 0,
        "검색실패_출원인": 0,
        "제외_미등록": 0, "제외_비엔나없음(문자상표)": 0, "제외_상표번호아님": 0,
        "제외_대상류아님": 0, "류별_수집": {},
    }
    checkpoint_path = (
        staging_checkpoint_path(args.file_staging)
        if args.file_staging
        else CHECKPOINT_PATH
    )
    checkpoint = load_checkpoint(checkpoint_path)
    if args.file_staging:
        db_existing = load_file_staging_app_numbers(args.file_staging)
    else:
        db_existing = load_db_app_numbers(config.DATABASE_URL) if not args.dry_run else set()
    initial_existing_count = len(db_existing)
    target_reached = bool(
        args.target_total is not None
        and initial_existing_count >= args.target_total
    )
    run_new_app_nos: set[str] = set()
    if args.target_total is not None:
        report.update(
            {
                "기존총계": initial_existing_count,
                "목표총계": args.target_total,
                "남은신규상한": max(0, args.target_total - initial_existing_count),
            }
        )
        if target_reached:
            print(
                f"[목표] 기존 총계 {initial_existing_count}건으로 "
                f"목표 {args.target_total}건에 이미 도달했습니다. 검색 호출을 생략합니다."
            )
    upserted_count = 0
    aborted: BaseException | None = None

    try:
        for source in sources:
            if target_reached:
                break
            considered = 0
            if args.mock_xml:
                start_page, start_offset = 1, 0
                pages: Iterator[SearchPage] = iter(
                    [SearchPage(source, 1, mock_items, len(mock_items), False)]
                )
            else:
                start_page, start_offset = (
                    (1, 0)
                    if args.force or args.dry_run
                    else load_cursor(
                        source,
                        checkpoint_path,
                        rows_per_page=args.rows_per_page,
                    )
                )
                print(
                    f"[검색] 출원인: {source}, page={start_page}, offset={start_offset} "
                    f"(월 사용량 {kipris_client.limiter.used_this_month()}회)"
                )
                pages = iter_search_pages(
                    source,
                    start_page=start_page,
                    max_pages=args.max_pages_per_source,
                    rows_per_page=args.rows_per_page,
                    max_retries=args.search_retries,
                    retry_backoff_seconds=args.retry_backoff_seconds,
                    request_timeout_seconds=args.search_timeout_seconds,
                )

            for page in pages:
                if isinstance(page, SearchFailure):
                    report["검색실패_출원인"] += 1
                    print(
                        f"[경고] {source}: page {page.page_no}를 {page.attempts}회 "
                        "시도했지만 받지 못해 이번 실행에서는 이 출원인만 건너뜁니다. "
                        "체크포인트는 전진하지 않습니다.",
                        file=sys.stderr,
                    )
                    break
                report["검색결과"] += len(page.items)
                offset = start_offset if page.page_no == start_page else 0
                offset = min(offset, len(page.items))
                next_offset = offset
                retry_offset: int | None = None
                stop_for_limit = False
                stop_for_target = False
                page_rows: list[tuple] = []
                page_app_nos: list[str] = []
                interrupted: BaseException | None = None

                try:
                    for item_index in range(offset, len(page.items)):
                        if (
                            args.target_total is not None
                            and initial_existing_count + len(run_new_app_nos)
                            >= args.target_total
                        ):
                            target_reached = True
                            stop_for_target = True
                            break
                        if args.limit and considered >= args.limit:
                            stop_for_limit = True
                            break
                        it = page.items[item_index]
                        if not should_collect(it, report, target_nice_classes):
                            next_offset = item_index + 1
                            continue

                        considered += 1
                        app_no = normalize_application_number(it["ApplicationNumber"])
                        image_key = f"{app_no}.png"

                        if not args.force and (
                            already_collected(app_no, checkpoint, db_existing)
                            or app_no in run_new_app_nos
                        ):
                            report["건너뜀_기수집"] += 1
                            next_offset = item_index + 1
                            if args.limit and considered >= args.limit:
                                stop_for_limit = True
                                break
                            continue

                        if args.dry_run:
                            print(
                                f"[dry-run] 수집 대상: {app_no} {it.get('Title', '')!r}"
                            )
                            checkpoint.add(app_no)
                            run_new_app_nos.add(app_no)
                            report["수집"] += 1
                            record_nice_distribution(it, report)
                            next_offset = item_index + 1
                            if (
                                args.target_total is not None
                                and initial_existing_count + len(run_new_app_nos)
                                >= args.target_total
                            ):
                                target_reached = True
                                stop_for_target = True
                            if args.limit and considered >= args.limit:
                                stop_for_limit = True
                            if stop_for_limit or stop_for_target:
                                break
                            continue

                        dest = (
                            staging_image_path(args.file_staging, image_key)
                            if args.file_staging
                            else storage.local_path(image_key)
                        )
                        try:
                            image_exists = (
                                dest.is_file()
                                if args.file_staging
                                else storage.image_exists(image_key)
                            )
                            if image_exists and not args.force:
                                report["이미지_재사용"] += 1
                            elif args.mock_xml:
                                make_placeholder_png(dest, it.get("Title", app_no))
                            else:
                                image_url = it.get("ImagePath") or it.get(
                                    "ThumbnailPath", ""
                                )
                                if not image_url:
                                    raise kipris_client.KiprisError("ImagePath 없음")
                                kipris_client.download_file_now(image_url, dest)
                        except Exception as e:
                            report["이미지실패"] += 1
                            retry_offset = (
                                item_index
                                if retry_offset is None
                                else min(retry_offset, item_index)
                            )
                            print(
                                f"[경고] 이미지 확보 실패({app_no}): {e}",
                                file=sys.stderr,
                            )
                            next_offset = item_index + 1
                            if args.limit and considered >= args.limit:
                                stop_for_limit = True
                                break
                            continue

                        if args.enrich_biblio:
                            try:
                                enrich_item(it)
                                report["보강"] += 1
                            except kipris_client.CallBudgetExceeded:
                                raise
                            except Exception as e:
                                report["보강실패"] += 1
                                print(
                                    f"[경고] 유사군 보강 실패({app_no}) — "
                                    f"유사군 빈 배열로 진행: {e}",
                                    file=sys.stderr,
                                )

                        try:
                            page_rows.append(item_to_row(it))
                        except Exception as e:
                            report["레코드실패"] += 1
                            retry_offset = (
                                item_index
                                if retry_offset is None
                                else min(retry_offset, item_index)
                            )
                            print(
                                f"[경고] 레코드 변환 실패({app_no}) — "
                                f"원본 이미지는 보존됨: {e}",
                                file=sys.stderr,
                            )
                            next_offset = item_index + 1
                            if args.limit and considered >= args.limit:
                                stop_for_limit = True
                                break
                            continue

                        page_app_nos.append(app_no)
                        run_new_app_nos.add(app_no)
                        report["수집"] += 1
                        record_nice_distribution(it, report)
                        next_offset = item_index + 1
                        if (
                            args.target_total is not None
                            and initial_existing_count + len(run_new_app_nos)
                            >= args.target_total
                        ):
                            target_reached = True
                            stop_for_target = True
                        if args.limit and considered >= args.limit:
                            stop_for_limit = True
                        if stop_for_limit or stop_for_target:
                            break
                except (kipris_client.CallBudgetExceeded, KeyboardInterrupt) as e:
                    interrupted = e
                    retry_offset = (
                        next_offset
                        if retry_offset is None
                        else min(retry_offset, next_offset)
                    )

                # 페이지 행만 즉시 적재한다. dirty는 DB 쓰기 전, 완료 체크포인트는 성공 후다.
                if page_rows and not args.dry_run:
                    if args.file_staging:
                        inserted, unchanged = merge_file_staging_rows(
                            page_rows,
                            args.file_staging,
                        )
                        print(
                            f"[파일 스테이징] page {page.page_no} "
                            f"신규 {inserted}건, 동일 {unchanged}건 원자 병합"
                        )
                    else:
                        mark_index_dirty()
                        upsert_rows(page_rows, config.DATABASE_URL)
                        print(f"[DB] page {page.page_no} UPSERT {len(page_rows)}건 완료")
                    upserted_count += len(page_rows)

                fully_processed = (
                    next_offset >= len(page.items) and retry_offset is None
                )
                source_complete = fully_processed and not page.has_more
                if fully_processed and page.has_more:
                    next_cursor = (page.page_no + 1, 0)
                else:
                    next_cursor = (
                        page.page_no,
                        retry_offset if retry_offset is not None else next_offset,
                    )

                if not args.dry_run and (page_app_nos or retry_offset is None):
                    update_checkpoint(
                        page_app_nos,
                        source=None if args.mock_xml else source,
                        cursor=next_cursor,
                        rows_per_page=args.rows_per_page,
                        source_complete=source_complete,
                        path=checkpoint_path,
                    )
                    checkpoint.update(page_app_nos)
                    db_existing.update(page_app_nos)

                if interrupted is not None:
                    raise interrupted
                if stop_for_limit or stop_for_target:
                    break
                start_offset = 0
    except (kipris_client.CallBudgetExceeded, KeyboardInterrupt) as e:
        aborted = e
        print(
            f"\n[중단] {type(e).__name__}: {e}\n"
            f"       지금까지 {upserted_count}건을 적재했습니다. 재실행하면 커서에서 이어받습니다.",
            file=sys.stderr,
        )

    # 이번 실행 또는 이전 중단의 DB 변경이 있으면 성공한 publish 뒤에만 dirty를 지운다.
    if not args.dry_run and not args.file_staging and INDEX_DIRTY_PATH.exists():
        if args.skip_index:
            print(
                f"[경고] 인덱스 재빌드를 생략했습니다. 다음 실행에서 복구 필요: {INDEX_DIRTY_PATH}",
                file=sys.stderr,
            )
        else:
            export_authoritative_keys(config.DATABASE_URL)
            rebuild_index()
            clear_index_dirty()

    # ⑤ 검색 결과는 있는데 수집도 skip 도 0이면 필터/포맷 문제 — 조용히 끝내지 않는다.
    #    (기수집 skip 으로 0건이면 정상 — 재실행/증분 수집에서 흔함)
    if (
        aborted is None
        and report["검색실패_출원인"] == 0
        and report["검색결과"] > 0
        and report["수집"] == 0
        and report["건너뜀_기수집"] == 0
    ):
        if target_nice_classes and report["제외_대상류아님"] > 0:
            print(
                "[안내] 지정한 Nice 류에 맞는 신규 수집 대상이 없습니다: "
                f"{sorted(target_nice_classes)}"
            )
            print(f"[리포트] {report}")
            return 0
        print(
            f"[오류] 검색 {report['검색결과']}건 중 수집 0건 — "
            f"필터/포맷 확인 필요: {report}",
            file=sys.stderr,
        )
        return 2

    if args.target_total is not None:
        report["최종총계"] = initial_existing_count + len(run_new_app_nos)
        report["목표도달"] = report["최종총계"] >= args.target_total
    print(f"[리포트] {report}")
    if not args.dry_run and upserted_count:
        if args.file_staging:
            print(
                f"[스테이징] 메타: {args.file_staging}\n"
                f"[스테이징] authoritative keys: "
                f"{staging_authoritative_path(args.file_staging)}\n"
                "[참고] 운영 메타와 운영 인덱스는 변경하지 않았습니다."
            )
        else:
            try:
                info = refresh_dataset_info(config.DATABASE_URL)
                print(
                    f"[갱신] meta.dataset_info 를 DB 실측으로 갱신했습니다: "
                    f"총 {info['총_상표수']}건, 범위 {info['출원일자_범위']}"
                )
            except Exception as exc:  # 수집 자체는 성공 — 안내 문구 갱신 실패는 경고로만
                print(
                    f"[경고] dataset_info 자동 갱신 실패({exc}) — "
                    "meta 테이블에서 수동 갱신이 필요합니다.",
                    file=sys.stderr,
                )
    if aborted is not None:
        return 3  # 정상 종료가 아님을 호출자(배치 스크립트)가 알 수 있게
    if report["검색실패_출원인"] and not target_reached:
        return 4  # 다른 출원인은 처리했지만 네트워크 실패 소스가 남은 부분 성공
    return 0


if __name__ == "__main__":
    sys.exit(main())
