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
    raw_path: Path | None = None  # 이 페이지 원본 XML(save_raw_xml) — 검색 목록이 가리킨다


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
        raw_path = save_raw_xml(f"{source}_p{page_no}", xml_text)
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
        yield SearchPage(source, page_no, normalized, total, has_more, raw_path)
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
class CheckpointError(ValueError):
    """기존 수집 진행 상태를 신뢰할 수 없어 재수집/덮어쓰기를 차단한다."""


def _validate_checkpoint_payload(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("최상위 값은 JSON 객체여야 합니다")
    if "schema_version" in data and (
        type(data["schema_version"]) is not int or data["schema_version"] not in {1, 2, 3}
    ):
        raise ValueError("지원하지 않는 schema_version입니다")
    collected = data.get("collected")
    if not isinstance(collected, list) or any(
        not isinstance(app_no, str) or not app_no.strip() for app_no in collected
    ):
        raise ValueError("collected는 비어 있지 않은 문자열의 배열이어야 합니다")
    cursors = data.get("cursors", {})
    if not isinstance(cursors, dict):
        raise ValueError("cursors는 JSON 객체여야 합니다")
    for cursor in cursors.values():
        if not isinstance(cursor, dict):
            raise ValueError("각 커서는 JSON 객체여야 합니다")
        for key, minimum in (("page", 1), ("offset", 0)):
            value = cursor.get(key)
            if type(value) is not int or value < minimum:
                raise ValueError(f"커서 {key}는 {minimum} 이상의 정수여야 합니다")
        if "rows_per_page" in cursor:
            rows = cursor["rows_per_page"]
            if type(rows) is not int or not 1 <= rows <= kipris_client.ADVANCED_MAX_ROWS:
                raise ValueError("커서 rows_per_page가 허용 범위를 벗어났습니다")
    return data


def _read_checkpoint_payload(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _validate_checkpoint_payload(data)
    except FileNotFoundError:
        if not path.is_symlink():
            return {}  # 체크포인트가 없는 최초 실행만 빈 상태로 시작한다.
        reason = "체크포인트 링크의 대상 파일이 없습니다"
    except (ValueError, OSError) as exc:
        reason = str(exc)
    raise CheckpointError(
        f"체크포인트를 읽거나 검증하지 못했습니다: {path} ({reason}). "
        "기존 파일을 보존했습니다. 백업을 복원하거나 내용을 확인·복구한 뒤 재실행하세요."
    ) from None


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
    page = cursor.get("page", 1)
    offset = cursor.get("offset", 0)

    if rows_per_page is not None and cursor:
        # schema v2까지는 수집기의 유일한 페이지 크기가 500건이었다.
        stored_rows = cursor.get(
            "rows_per_page",
            kipris_client.ADVANCED_DEFAULT_ROWS,
        )
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


def merge_file_staging_rows(
    rows: list[tuple],
    path: Path,
    *,
    extra: dict | None = None,
    row_extras: list[dict] | None = None,
) -> tuple[int, int]:
    """DB 행을 연구 JSON에 원자 병합한다. 기존 값 충돌은 덮어쓰지 않는다.

    extra: 모든 새 레코드에 덧붙일 필드(예: 수집 출처 {"수집_출처": "유명 브랜드"}).
    row_extras: 행마다 덧붙일 필드(rows 와 같은 길이, 예: 메모)."""
    if row_extras is not None and len(row_extras) != len(rows):
        raise ValueError("row_extras 는 rows 와 길이가 같아야 합니다.")
    payload = _read_metadata_payload(path) if path.exists() else _initial_staging_payload()
    existing = _records_by_application_number(payload)
    inserted = 0
    unchanged = 0
    for index, row in enumerate(rows):
        record = {
            **_row_to_staging_record(row),
            **(extra or {}),
            **((row_extras or [{}] * len(rows))[index]),
        }
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

    _publish_file_staging(path, payload, [existing[key] for key in sorted(existing)])
    return inserted, unchanged


def _publish_file_staging(path: Path, payload: dict, ordered_records: list[dict]) -> None:
    """스테이징 메타 → authoritative keys(이미지 키·해시·메타 SHA)를 dirty 표시 안에서 쓴다."""
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


# ====================================================================
# 유명 브랜드 수집(2026-11-19) — 출원인 검색 목록 → 선택 계획(호출 0) → 계획 실행
#
#   1) --search-only: 출원인(검색어)마다 검색 페이지 원본을 저장하고 검색 목록
#      (--search-manifest)에 적는다. 같은 검색어의 완전한 원본(1쪽부터 totalCount 까지)이
#      이미 있으면 부르지 않는다 — 같은 출원인을 두 번 검색하지 않는다.
#   2) --select-plan: 검색 목록의 원본만 읽어(호출 0) 출원인당 --max-per-applicant 건을 고른다.
#      거르기 = 출원인명 일치·등록(③)·비엔나코드 있음(도형·결합, ④)·상표 번호·운영 메타와
#      겹치지 않음,
#      순서 = 등록 → 도형·결합(거르기로 이미 앞) → 업종 세트의 류 → 최근 등록 → 출원번호.
#   3) --run-plan: 고른 건마다 서지상세 1회(유사군·새 견본 링크·등록 상태)를 부르고 견본을
#      곧바로 받아(②) 파일 스테이징에 넣는다. 검색 응답의 견본 링크는 일회성이라 쓰지 않는다.
#      연속 오류 5회면 멈추고, 20건마다·중단 때 그때까지 받은 것을 저장한다.
# ====================================================================
BRAND_SECTION = "[브랜드]"
DEFAULT_MAX_PER_APPLICANT = 10
PLAN_ERROR_STREAK_STOP = 5
PLAN_SAVE_EVERY = 20
SOURCE_LABEL_FIELD = "수집_출처"
BUSINESS_PRESETS_PATH: Path = PROJECT_ROOT / "shared" / "goods_map" / "business_presets.json"
_INLINE_COMMENT = re.compile(r"\s+#.*$")
_LEGAL_FORMS = re.compile(r"주식회사|유한회사|유한책임회사|\(주\)|㈜")
_NAME_NOISE = re.compile(r"[\s.,·()\[\]&'\"-]+")


def use_key_and_counter(*, key_env: str | None = None, counter: Path | None = None) -> dict:
    """이 실행에서 쓸 KIPRIS 키와 호출 카운터를 바꾼다(--key-env·--counter).

    key_env: 키를 담은 환경변수 이름 — 값은 kipris_client.ACCESS_KEY 에만 넣고 출력·저장하지
    않는다(.env 는 그대로). counter: 그 키 전용 카운터 파일 — 공용 카운터
    (ml/data/kipris_call_count.json)는 건드리지 않고, 월·일 예산(KIPRIS_MONTHLY_BUDGET·
    KIPRIS_DAILY_BUDGET)은 그 파일에 적용한다. trials_enrich lookup 의 같은 옵션과 같은 규약.
    돌려주는 사전에는 키 값이 없다(키 출처·카운터 경로·이번 달·오늘 사용량)."""
    info: dict = {}
    if key_env:
        value = os.environ.get(key_env, "").strip()
        if not value:
            raise SystemExit(f"환경변수 {key_env} 가 비어 있습니다 — 키를 넣은 셸에서 실행하세요")
        kipris_client.ACCESS_KEY = value
        info["키"] = f"환경변수 {key_env}"
    if counter:
        kipris_client.limiter = kipris_client.RateLimiter(
            counter_path=Path(counter),
            monthly_budget=kipris_client.MONTHLY_CALL_BUDGET,
            min_interval=kipris_client.limiter.min_interval,
            daily_budget=kipris_client.DAILY_CALL_BUDGET,
        )
        info["카운터"] = str(counter)
    info["이번_달"] = kipris_client.limiter.used_this_month()
    info["오늘"] = kipris_client.limiter.used_today()
    return info


@dataclass(frozen=True)
class BrandRow:
    """famous_brands.txt [브랜드] 절의 한 줄: 브랜드 | 출원인명 | 업종(세트 id) | 선정 근거."""

    brand: str
    applicant: str
    industry: str
    basis: str


def _content_lines(text: str) -> list[tuple[str | None, str]]:
    """(절 머리, 줄) 목록. 빈 줄·전체 주석 줄을 빼고 줄 끝 ' # 주석'은 뗀다."""
    section: str | None = None
    lines: list[tuple[str | None, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = _INLINE_COMMENT.sub("", line).strip()
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue
        lines.append((section, line))
    return lines


def read_brand_rows(path: Path) -> list[BrandRow]:
    """[브랜드] 절의 표 행. 열이 4개가 아니면 몇째 줄인지 밝혀 ValueError."""
    rows: list[BrandRow] = []
    for section, line in _content_lines(Path(path).read_text(encoding="utf-8")):
        if section != BRAND_SECTION:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 4 or not all(cells[:3]):
            raise ValueError(f"[브랜드] 행은 '브랜드 | 출원인명 | 업종 | 선정 근거' 입니다: {line}")
        rows.append(BrandRow(cells[0], cells[1], cells[2], " | ".join(cells[3:])))
    return rows


def applicant_names(applicant: str) -> list[str]:
    """출원인명 열의 표기들 — KIPRIS 가 같은 회사를 두 가지로 적은 경우 ' / ' 로 잇는다
    (예: '인터 이케아 시스템 비. 브이. / 인터 이케아 시스템스 비. 브이.')."""
    return [name.strip() for name in applicant.split(" / ") if name.strip()]


def read_applicants_file(path: Path) -> list[str]:
    """--applicants-file 출원인 목록. [브랜드] 절이 있으면 그 표의 출원인명(표기마다 하나),
    없으면(옛 형식) 주석이 아닌 줄 전체(줄 끝 ' # 주석' 제외)."""
    lines = _content_lines(Path(path).read_text(encoding="utf-8"))
    if any(section == BRAND_SECTION for section, _ in lines):
        return [name for row in read_brand_rows(path) for name in applicant_names(row.applicant)]
    return [line for section, line in lines if section is None]


def applicant_core(name: str) -> str:
    """출원인명 비교 키 — 회사 형태(주식회사·(주) 등)·공백·문장부호를 빼고 소문자로."""
    return _NAME_NOISE.sub("", _LEGAL_FORMS.sub("", name or "")).lower()


def applicant_matches(applicant_field: str, target: str) -> bool:
    """검색 응답의 출원인('A|B' 공동 출원 포함) 가운데 target 과 같은 출원인이 있는가.

    항목별검색의 출원인 검색은 키워드 일치라('네이버' → 굿네이버스·네이버웹툰) 결과를 이 비교로
    다시 거른다(포함이 아니라 같음). target 은 ' / ' 로 이은 여러 표기일 수 있다."""
    keys = {applicant_core(name) for name in applicant_names(target)} - {""}
    return bool(keys) and any(
        applicant_core(part) in keys for part in (applicant_field or "").split("|")
    )


def _rel_data_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(paths.ML_DATA_DIR.resolve()).as_posix()
    except ValueError:
        return str(path)


def _abs_data_path(raw: str) -> Path:
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else paths.ML_DATA_DIR / candidate


def _page_summary(path: Path) -> tuple[int | None, list[dict]]:
    xml_text = path.read_text(encoding="utf-8")
    total = kipris_client.parse_advanced_total_count(xml_text)
    items = [
        kipris_client.normalize_advanced_item(it) for it in kipris_client.parse_items(xml_text)
    ]
    return total, items


def _applicant_distribution(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        for part in str(item.get("ApplicantName") or "").split("|"):
            part = part.strip()
            if part:
                counts[part] = counts.get(part, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _search_entry(source: str, files: list[Path], *, calls: int, reused: bool) -> dict:
    """저장된 검색 원본 묶음 → 검색 목록 항목(완전 여부·건수·출원인 분포)."""
    total: int | None = None
    items: list[dict] = []
    for path in files:
        page_total, page_items = _page_summary(path)
        total = page_total if page_total is not None else total
        items.extend(page_items)
    complete = bool(files) and (total is None or len(items) >= total)
    return {
        "검색어": source,
        "파일": [_rel_data_path(path) for path in files],
        "totalCount": total,
        "건수": len(items),
        "완전": complete,
        "출원인_분포": _applicant_distribution(items),
        "호출": calls,
        "재사용": reused,
        "기록_시각": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def saved_search_files(source: str) -> list[Path] | None:
    """같은 검색어로 이미 저장된 원본 가운데 1쪽부터 끝까지 이어지는 최신 묶음(완전할 때만).

    save_raw_xml 파일명({검색어}_p{쪽}_{시각}.xml)으로 찾는다. 쪽마다 가장 늦은 파일을 쓰고,
    totalCount 를 다 덮지 못하거나 응답이 오류면 None(다시 검색해야 함)."""
    if not COLLECT_RAW_XML_DIR.exists():
        return None
    by_page: dict[int, Path] = {}
    for page_no in range(1, kipris_client.ADVANCED_MAX_PAGES + 1):
        safe = re.sub(r"[^0-9A-Za-z가-힣]+", "_", f"{source}_p{page_no}").strip("_")[:40]
        if not safe.endswith(f"_p{page_no}"):
            return None  # 이름이 잘려 쪽 번호를 가릴 수 없다
        found = sorted(COLLECT_RAW_XML_DIR.glob(f"{safe}_[0-9]*Z.xml"))
        if not found:
            break
        by_page[page_no] = found[-1]
    if not by_page:
        return None
    files = [by_page[page] for page in sorted(by_page)]
    try:
        entry = _search_entry(source, files, calls=0, reused=True)
    except kipris_client.KiprisError:
        return None
    return files if entry["완전"] else None


def _read_search_manifest(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 1, "검색": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("검색"), dict):
        raise ValueError(f"검색 목록 형식이 아닙니다: {path.name}")
    return payload


def run_search_only(
    sources: list[str],
    manifest_path: Path,
    *,
    rows_per_page: int,
    max_pages: int,
    max_retries: int,
    retry_backoff_seconds: float,
    request_timeout_seconds: float,
    max_calls: int | None = None,
) -> dict:
    """출원인마다 검색 원본을 저장하고 검색 목록에 적는다(완전한 기존 원본은 재사용).

    한 출원인이 끝날 때마다 목록을 원자적으로 쓴다. 연속 오류 5회·예산 소진·max_calls 에
    닿으면 멈춘다(그때까지 적은 것은 남는다)."""
    manifest = _read_search_manifest(manifest_path)
    entries: dict = manifest["검색"]
    report = {"검색어": len(sources), "재사용": 0, "검색": 0, "호출": 0, "실패": 0, "멈춤": ""}
    streak = 0
    for source in sources:
        previous = entries.get(source)
        if previous and previous.get("완전"):
            report["재사용"] += 1
            continue
        saved = saved_search_files(source)
        if saved is not None:
            entries[source] = _search_entry(source, saved, calls=0, reused=True)
            report["재사용"] += 1
            _atomic_write_json(manifest_path, manifest)
            continue
        if max_calls is not None and report["호출"] + max_pages > max_calls:
            report["멈춤"] = f"호출 상한 {max_calls}"
            break
        files: list[Path] = []
        failure = ""
        try:
            for page in iter_search_pages(
                source,
                max_pages=max_pages,
                rows_per_page=rows_per_page,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
                request_timeout_seconds=request_timeout_seconds,
            ):
                if isinstance(page, SearchFailure):
                    failure = page.message
                    report["호출"] += page.attempts
                    break
                report["호출"] += 1
                if page.raw_path is not None:
                    files.append(page.raw_path)
        except kipris_client.CallBudgetExceeded as exc:
            report["멈춤"] = f"예산: {exc}"
            break
        except kipris_client.KiprisConfigError:
            raise
        except kipris_client.KiprisError as exc:
            failure = f"{type(exc).__name__}: {exc}"
            report["호출"] += 1
        if failure or not files:
            report["실패"] += 1
            streak += 1
            entries[source] = {"검색어": source, "완전": False, "오류": failure or "응답 없음"}
            _atomic_write_json(manifest_path, manifest)
            print(f"[경고] {source}: 검색 실패 — {failure or '응답 없음'}", file=sys.stderr)
            if streak >= PLAN_ERROR_STREAK_STOP:
                report["멈춤"] = f"연속 오류 {PLAN_ERROR_STREAK_STOP}회"
                break
            continue
        streak = 0
        entries[source] = _search_entry(source, files, calls=len(files), reused=False)
        report["검색"] += 1
        _atomic_write_json(manifest_path, manifest)
        entry = entries[source]
        print(
            f"[검색] {source}: totalCount {entry['totalCount']} · 받은 {entry['건수']}건 · "
            f"{'완전' if entry['완전'] else '불완전'} · 출원인 상위 "
            f"{list(entry['출원인_분포'])[:3]}"
        )
    return report


def saved_biblio_not_registered() -> set[str]:
    """저장된 서지 원본(biblio_<출원번호>_*.xml, 출원번호마다 가장 늦은 것)의 등록 상태가 '등록'이
    아닌 출원번호 — 계획에서 미리 빼 같은 건을 다시 부르지 않는다(호출 0)."""
    latest: dict[str, Path] = {}
    if COLLECT_RAW_XML_DIR.exists():
        for path in sorted(COLLECT_RAW_XML_DIR.glob("biblio_*_*.xml")):
            latest[path.name.split("_")[1]] = path
    status = re.compile(r"<registerStatus>([^<]*)</registerStatus>")
    gone: set[str] = set()
    for app_no, path in latest.items():
        found = status.search(path.read_text(encoding="utf-8", errors="replace"))
        if found and found.group(1).strip() and found.group(1).strip() != "등록":
            gone.add(app_no)
    return gone


def load_business_preset_classes(path: Path = BUSINESS_PRESETS_PATH) -> dict[str, set[int]]:
    """업종 세트 id → 그 세트 지정상품의 Nice 류 집합."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    presets = payload["presets"] if isinstance(payload, dict) else payload
    classes: dict[str, set[int]] = {}
    for preset in presets:
        classes[str(preset["id"])] = {
            int(goods["nice_class"]) for goods in preset.get("지정상품", [])
            if str(goods.get("nice_class", "")).isdigit()
        }
    return classes


OTHER_BRAND_MEMO = "같은 출원인의 다른 브랜드"
_HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
_TITLE_DROP = re.compile(r"['’`\-]")


def brand_names(brand: str) -> list[str]:
    """[브랜드] 열의 표기들(' / ' 로 이음) — 첫 표기가 표시 이름, 모두 상표명 대조에 쓴다
    (예: '교촌치킨 / 교촌 / KYOCHON')."""
    return [name.strip() for name in brand.split(" / ") if name.strip()]


def _latin_words(text: str) -> str:
    text = _TITLE_DROP.sub("", str(text or "").lower())
    return " ".join(re.sub(r"[^0-9a-z가-힣]+", " ", text).split())


def title_has_brand(title: str | None, names: list[str]) -> bool:
    """상표명에 브랜드명(국문·영문)이 들어 있는가.

    한글 표기는 공백·기호를 뗀 부분 일치('동대문 엽기 떡볶이' ⊃ '엽기떡볶이'), 영문 표기는 소문자·
    아포스트로피·하이픈 제거 뒤 단어 경계 일치('Nice to CU' ⊃ 'cu', 'cupon' ⊅ 'cu')."""
    words = _latin_words(title or "")
    compact = words.replace(" ", "")
    for name in names:
        if _HANGUL.search(name):
            key = _latin_words(name).replace(" ", "")
            if key and key in compact:
                return True
        else:
            key = _latin_words(name)
            if key and re.search(rf"(?<![0-9a-z]){re.escape(key)}(?![0-9a-z])", words):
                return True
    return False


def short_mark_kind(kind: str | None) -> str | None:
    """서지 표장구분('국내상표 도형복합 일반상표')을 운영 메타 표기('도형복합'·'도형상표')로 줄인다.

    유형 판정(src/mark_type.classify_metadata)은 상표구분이 정확히 '도형상표'·'도형복합'일 때만
    쓰고, 그 밖의 값이면 비엔나코드+상표명 규칙이라 상표명이 있는 도형상표를 결합으로 본다."""
    text = " ".join(str(kind or "").split())
    for short in ("도형복합", "도형상표"):
        if short in text:
            return short
    return text or None


def _registration_date_value(item: dict) -> int:
    digits = re.sub(r"\D", "", str(item.get("RegistrationDate") or ""))
    return int(digits[:8]) if len(digits) >= 8 else 0


def selection_key(
    item: dict, preset_classes: set[int], names: list[str] | None = None
) -> tuple:
    """선택 순서: 상표명에 브랜드명 → 등록 → 도형·결합(비엔나코드 있음) → 업종 세트의 류 →
    최근 등록 → 출원번호. names 가 없으면 첫 기준은 모두 같다."""
    return (
        not title_has_brand(item.get("Title"), names or []),
        item.get("ApplicationStatus") != "등록",
        not item.get("ViennaCode"),
        not (_item_nice_classes(item) & preset_classes),
        -_registration_date_value(item),
        normalize_application_number(str(item.get("ApplicationNumber") or "")),
    )


def select_for_applicant(
    items: list[dict],
    *,
    applicant: str,
    preset_classes: set[int],
    excluded: set[str],
    max_per_applicant: int,
    names: list[str] | None = None,
) -> tuple[list[dict], dict]:
    """한 출원인의 검색 결과에서 수집할 건을 고른다(호출 0). (고른 항목, 거른 사유별 건수).

    names(브랜드 표기)가 있으면 상표명에 브랜드명이 든 표장을 먼저 고르고 모자라면 나머지 순서로
    채운다."""
    stats = {
        "검색": len(items), "출원인_다름": 0, "미등록": 0, "비엔나없음": 0,
        "상표번호아님": 0, "운영_중복": 0, "후보": 0, "브랜드명_후보": 0,
    }
    candidates: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not applicant_matches(str(item.get("ApplicantName") or ""), applicant):
            stats["출원인_다름"] += 1
            continue
        if item.get("ApplicationStatus") != "등록":
            stats["미등록"] += 1
            continue
        if not item.get("ViennaCode"):
            stats["비엔나없음"] += 1
            continue
        raw_number = str(item.get("ApplicationNumber") or "")
        if not is_trademark_application_number(raw_number):
            stats["상표번호아님"] += 1
            continue
        app_no = normalize_application_number(raw_number)
        if app_no in seen:
            continue
        seen.add(app_no)
        if app_no in excluded:
            stats["운영_중복"] += 1
            continue
        candidates.append(item)
    stats["후보"] = len(candidates)
    stats["브랜드명_후보"] = sum(
        1 for item in candidates if title_has_brand(item.get("Title"), names or [])
    )
    candidates.sort(key=lambda item: selection_key(item, preset_classes, names))
    return candidates[:max_per_applicant], stats


def _manifest_entry_for(applicant: str, entries: dict) -> dict | None:
    """출원인명에 맞는 검색 목록 항목 — 결과 출원인 분포에 그 출원인(표기 중 하나)이 있는 것 가운데
    완전한 것 먼저, 그 출원인 건수가 많은 것 먼저. 검색어만 같고 결과가 0건인 항목은 고르지 않는다.
    쪽 상한에 걸린 불완전 항목은 완전한 것이 없을 때만(계획에 검색_완전 False 로 남긴다)."""
    keys = {applicant_core(name) for name in applicant_names(applicant)} - {""}
    ranked: list[tuple[bool, int, dict]] = []
    for entry in entries.values():
        hits = sum(
            count for name, count in entry.get("출원인_분포", {}).items()
            if applicant_core(name) in keys
        )
        if entry.get("파일") and hits:
            ranked.append((not entry.get("완전"), -hits, entry))
    ranked.sort(key=lambda item: item[:2])
    return ranked[0][2] if ranked else None


def build_selection_plan(
    brands: list[BrandRow],
    manifest: dict,
    *,
    preset_classes: dict[str, set[int]],
    excluded: set[str],
    max_per_applicant: int,
) -> dict:
    """브랜드 표 + 검색 목록 → 수집 계획(호출 0). 계획 건수 = 서지 호출 = 견본 다운로드."""
    unknown = sorted({row.industry for row in brands} - set(preset_classes))
    if unknown:
        raise ValueError(f"업종 세트에 없는 업종 id: {unknown}")
    taken = set(excluded)
    brand_rows: list[dict] = []
    records: list[dict] = []
    for row in brands:
        names = brand_names(row.brand)
        entry = _manifest_entry_for(row.applicant, manifest.get("검색", {}))
        summary = {
            "브랜드": names[0], "브랜드_표기": names, "출원인명": row.applicant,
            "업종": row.industry, "업종_류": sorted(preset_classes[row.industry]),
        }
        if entry is None:
            brand_rows.append({**summary, "상태": "검색 없음", "선택": 0})
            continue
        items: list[dict] = []
        for raw in entry["파일"]:
            items.extend(_page_summary(_abs_data_path(raw))[1])
        chosen, stats = select_for_applicant(
            items,
            applicant=row.applicant,
            preset_classes=preset_classes[row.industry],
            excluded=taken,
            max_per_applicant=max_per_applicant,
            names=names,
        )
        in_preset = sum(
            1 for item in chosen if _item_nice_classes(item) & preset_classes[row.industry]
        )
        named = 0
        for item in chosen:
            app_no = normalize_application_number(str(item["ApplicationNumber"]))
            taken.add(app_no)
            has_name = title_has_brand(item.get("Title"), names)
            named += has_name
            record = {
                "출원번호": app_no, "브랜드": names[0], "출원인명": row.applicant,
                "업종": row.industry, "브랜드명_포함": has_name, "item": item,
            }
            if not has_name:
                record["메모"] = OTHER_BRAND_MEMO
            records.append(record)
        brand_rows.append({
            **summary, "검색어": entry["검색어"], "검색_완전": bool(entry.get("완전")),
            **stats, "선택": len(chosen), "선택_브랜드명": named,
            "선택_업종류": in_preset, "상태": "ok" if chosen else "후보 없음",
        })
    count = len(records)
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "max_per_applicant": max_per_applicant,
        "brands": brand_rows,
        "records": records,
        "estimated_calls": {
            "서지(유사군·견본 링크)": count,
            "견본_다운로드": count,
            "참고": "하드캡은 KIPRIS API 호출(키 카운터)로 센다 — 계획 전체를 처음 받을 때 서지 "
                    "= 계획 건수, 견본 다운로드는 따로. 유사군은 서지 응답에서 함께 채운다"
                    "(goods_backfill 로 다시 부르지 않음).",
        },
    }


def sync_staging_with_plan(
    plan: dict, staging: Path, *, archive_dir: Path | None = None, prune: set[str] | None = None
) -> dict:
    """스테이징을 계획에 맞춘다(호출 0): 계획에 있는 레코드의 메모를 계획대로 고치고, archive_dir 가
    있으면 prune 에 든 계획 밖 레코드를 뺀다 — 견본은 archive_dir/images 로 옮기고 레코드는
    archive_dir/removed_records.json 에 덧붙인다(원본 XML 은 그대로). 체크포인트에서도 뺀다."""
    if not staging.exists():
        return {"메모_변경": 0, "계획_밖": 0, "뺌": 0}
    ready, error = inspect_file_staging(staging)
    if not ready:
        raise ValueError(f"파일 스테이징 점검 실패: {error}")
    payload = _read_metadata_payload(staging)
    records = _records_by_application_number(payload)
    planned = {record["출원번호"]: record for record in plan["records"]}
    outside = sorted(app_no for app_no in records if app_no not in planned)
    memo_changed = 0
    for app_no, record in records.items():
        if app_no not in planned:
            continue
        memo = planned[app_no].get("메모")
        if record.get("메모") != memo:
            if memo:
                record["메모"] = memo
            else:
                record.pop("메모", None)
            memo_changed += 1
    removed: list[dict] = []
    targets = sorted(set(prune or ()) & set(outside))
    if archive_dir is not None and targets:
        images = Path(archive_dir) / "images"
        images.mkdir(parents=True, exist_ok=True)
        log_path = Path(archive_dir) / "removed_records.json"
        previous = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
        for app_no in targets:
            record = records.pop(app_no)
            source = staging_image_path(staging, record["이미지파일"])
            if source.exists():
                os.replace(source, images / record["이미지파일"])
            removed.append(record)
        _atomic_write_json(log_path, previous + removed)  # type: ignore[arg-type]
    if memo_changed or removed:
        _publish_file_staging(staging, payload, [records[key] for key in sorted(records)])
    if removed:
        checkpoint = staging_checkpoint_path(staging)
        data = _read_checkpoint_payload(checkpoint)
        gone = {record["출원번호"] for record in removed}
        data["collected"] = sorted(set(map(str, data.get("collected", []))) - gone)
        _write_checkpoint_payload(data, checkpoint)
    return {"메모_변경": memo_changed, "계획_밖": len(outside), "뺌": len(removed)}


def _staged_records(staging: Path) -> dict[str, dict]:
    if not staging.exists():
        return {}
    return _records_by_application_number(_read_metadata_payload(staging))


def run_selection_plan(
    plan: dict,
    staging: Path,
    *,
    source_label: str,
    limit: int | None = None,
    max_calls: int | None = None,
    fetch=None,
    download=None,
    archive_dir: Path | None = None,
    industry_order: list[str] | None = None,
) -> dict:
    """계획을 브랜드 단위로 실행한다: 건마다 서지상세 1회 → 견본 즉시 다운로드 → 스테이징 병합.

    - 순서: industry_order 의 업종 순(같은 업종은 계획 순), 브랜드 안에서는 계획 순.
    - 이미 스테이징·운영에 있는 출원번호는 건너뛴다(재실행 이어받기). 서지의 등록 상태가 '등록'이
      아니면 넣지 않는다.
    - 빼기(archive_dir 가 있을 때): 그 브랜드의 새 건을 모두 받은 뒤에만 그 브랜드의 계획 밖
      스테이징 레코드(출원인 일치)를 뺀다. 멈추거나 한 건이라도 못 받은 브랜드는 이전 건을 그대로
      둔다 — 중간에 멈춰도 스테이징이 줄지 않는다. 모든 브랜드가 끝나면 어느 브랜드에도 속하지
      않는 계획 밖 레코드를 뺀다.
    - 멈춤: 연속 오류(서지·다운로드) 5회, 예산, max_calls(이번 실행 KIPRIS API 호출 = 서지 호출
      상한, 견본 다운로드는 따로 센다), limit(이번 실행에서 처리할 건수)."""
    fetch = fetch or kipris_client.bibliography_detail_raw
    download = download or kipris_client.download_file_now
    ready, error = inspect_file_staging(staging)
    if not ready:
        raise ValueError(f"파일 스테이징 점검 실패: {error}")
    synced = sync_staging_with_plan(plan, staging)
    existing = load_file_staging_app_numbers(staging)
    planned_app_nos = {record["출원번호"] for record in plan["records"]}
    rank = {industry: index for index, industry in enumerate(industry_order or [])}
    brand_rows = sorted(
        enumerate(plan["brands"]),
        key=lambda pair: (rank.get(pair[1]["업종"], len(rank)), pair[0]),
    )
    by_brand: dict[str, list[dict]] = {}
    for record in plan["records"]:
        by_brand.setdefault(record["브랜드"], []).append(record)
    report: dict = {
        "계획": len(plan["records"]), "메모_변경": synced["메모_변경"],
        "이미_있음": sum(1 for app_no in planned_app_nos if app_no in existing),
        "수집": 0, "유사군_있음": 0, "서지_호출": 0, "견본_다운로드": 0,
        "제외_등록상태": 0, "견본_링크없음": 0, "서지_실패": 0, "견본_실패": 0,
        "뺌": 0, "멈춤": "", "브랜드별": [],
    }
    rows: list[tuple] = []
    extras: list[dict] = []
    done: list[str] = []
    checkpoint = staging_checkpoint_path(staging)

    def flush() -> None:
        if not rows:
            return
        merge_file_staging_rows(
            rows, staging, extra={SOURCE_LABEL_FIELD: source_label}, row_extras=extras
        )
        update_checkpoint(done, path=checkpoint)
        existing.update(done)
        rows.clear()
        extras.clear()
        done.clear()

    def stop(reason: str) -> None:
        report["멈춤"] = report["멈춤"] or reason

    streak = 0
    processed = 0
    incomplete_applicants: list[str] = []
    try:
        for _, brand_row in brand_rows:
            brand, applicant = brand_row["브랜드"], brand_row["출원인명"]
            queue = [r for r in by_brand.get(brand, []) if r["출원번호"] not in existing]
            got = 0
            complete = True
            for record in queue:
                if limit and processed >= limit:
                    stop(f"건수 상한 {limit}")
                    break
                if max_calls is not None and report["서지_호출"] + 1 > max_calls:
                    stop(f"호출 상한 {max_calls}")
                    break
                processed += 1
                app_no = record["출원번호"]
                item = dict(record["item"])
                try:
                    report["서지_호출"] += 1
                    raw = fetch(app_no)
                    save_raw_xml(f"biblio_{app_no}", raw)  # Ⓐ 파싱 전 원본 선저장
                    detail = kipris_client.parse_bibliography_detail(raw)
                except kipris_client.CallBudgetExceeded as exc:
                    report["서지_호출"] -= 1
                    stop(f"예산: {exc}")
                    break
                except kipris_client.KiprisConfigError:
                    raise
                except kipris_client.KiprisError as exc:
                    report["서지_실패"] += 1
                    complete = False
                    streak += 1
                    print(f"  [실패] 서지 {app_no}: {type(exc).__name__}", file=sys.stderr)
                    if streak >= PLAN_ERROR_STREAK_STOP:
                        stop(f"연속 오류 {PLAN_ERROR_STREAK_STOP}회")
                        break
                    continue
                status = detail.get("register_status")
                if status and status != "등록":
                    report["제외_등록상태"] += 1
                    complete = False
                    streak = 0
                    continue
                image_url = detail.get("image_url")
                if not image_url:
                    report["견본_링크없음"] += 1
                    complete = False
                    streak = 0
                    continue
                dest = staging_image_path(staging, f"{app_no}.png")
                try:
                    report["견본_다운로드"] += 1
                    download(image_url, dest, validate_image=True)
                except (kipris_client.KiprisError, ValueError) as exc:
                    report["견본_실패"] += 1
                    complete = False
                    streak += 1
                    print(f"  [실패] 견본 {app_no}: {type(exc).__name__}", file=sys.stderr)
                    if streak >= PLAN_ERROR_STREAK_STOP:
                        stop(f"연속 오류 {PLAN_ERROR_STREAK_STOP}회")
                        break
                    continue
                streak = 0
                item["SimilarCode"] = detail["similarity_codes"]
                if not item.get("GoodClassificationCode") and detail.get("nice_classes"):
                    item["GoodClassificationCode"] = [str(c) for c in detail["nice_classes"]]
                if not item.get("DrawingKindName") and detail.get("mark_type"):
                    item["DrawingKindName"] = short_mark_kind(detail["mark_type"])
                rows.append(item_to_row(item))
                extras.append({"메모": record["메모"]} if record.get("메모") else {})
                done.append(app_no)
                got += 1
                report["수집"] += 1
                report["유사군_있음"] += bool(detail["similarity_codes"])
                if len(rows) >= PLAN_SAVE_EVERY:
                    flush()
            flush()
            finished = complete and not report["멈춤"]
            pruned = 0
            if finished and archive_dir is not None:
                old = {
                    app_no for app_no, staged in _staged_records(staging).items()
                    if app_no not in planned_app_nos
                    and applicant_matches(str(staged.get("출원인") or ""), applicant)
                }
                pruned = sync_staging_with_plan(
                    plan, staging, archive_dir=archive_dir, prune=old
                )["뺌"]
                report["뺌"] += pruned
            elif not finished:
                incomplete_applicants.append(applicant)
            report["브랜드별"].append({
                "브랜드": brand, "업종": brand_row["업종"], "새로_대상": len(queue),
                "받음": got, "뺌": pruned, "완료": finished,
            })
            if report["멈춤"]:
                break
        if not report["멈춤"] and archive_dir is not None:
            applicants = [row["출원인명"] for row in plan["brands"]]
            orphans = {
                app_no for app_no, staged in _staged_records(staging).items()
                if app_no not in planned_app_nos
                and not any(
                    applicant_matches(str(staged.get("출원인") or ""), name)
                    for name in applicants
                )
            }
            report["뺌"] += sync_staging_with_plan(
                plan, staging, archive_dir=archive_dir, prune=orphans
            )["뺌"]
    except KeyboardInterrupt:
        stop("사용자 중단")
    finally:
        flush()
    report["미완료_브랜드_출원인"] = incomplete_applicants
    return report


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


def _positive_int_arg(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 합니다.") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 합니다.")
    return value


def _search_only_command(sources: list[str], args) -> int:
    if not args.search_manifest:
        print("[오류] --search-only 에는 --search-manifest 가 필요합니다.", file=sys.stderr)
        return 1
    report = run_search_only(
        sources,
        args.search_manifest,
        rows_per_page=args.rows_per_page,
        max_pages=args.max_pages_per_source,
        max_retries=args.search_retries,
        retry_backoff_seconds=args.retry_backoff_seconds,
        request_timeout_seconds=args.search_timeout_seconds,
        max_calls=args.max_calls,
    )
    print(f"[검색 목록] {args.search_manifest}")
    print("[리포트] " + json.dumps(report, ensure_ascii=False))
    _print_counter()
    return 3 if report["멈춤"] else (4 if report["실패"] else 0)


def _select_plan_command(args) -> int:
    if not args.applicants_file or not args.search_manifest:
        print(
            "[오류] --select-plan 에는 --applicants-file(브랜드 표)·--search-manifest 가 "
            "필요합니다.",
            file=sys.stderr,
        )
        return 1
    brands = read_brand_rows(Path(args.applicants_file))
    if not brands:
        print("[오류] 목록 파일에 [브랜드] 표가 없습니다.", file=sys.stderr)
        return 1
    manifest = _read_search_manifest(args.search_manifest)
    runtime = _records_by_application_number(_read_metadata_payload(paths.TRADEMARK_META_PATH))
    not_registered = saved_biblio_not_registered()
    plan = build_selection_plan(
        brands,
        manifest,
        preset_classes=load_business_preset_classes(),
        excluded=set(runtime) | not_registered,
        max_per_applicant=args.max_per_applicant,
    )
    plan["제외_서지_등록아님"] = sorted(not_registered)
    plan["brands_file"] = str(args.applicants_file)
    plan["search_manifest"] = _rel_data_path(args.search_manifest)
    _atomic_write_json(args.select_plan, plan)
    print(f"[계획] {args.select_plan} — 호출 0")
    print("브랜드 | 업종 | 검색 | 출원인 일치 후보(브랜드명) | 운영 중복 | 선택(브랜드명·업종 류)")
    for row in plan["brands"]:
        if row["상태"] == "검색 없음":
            print(f"{row['브랜드']} | {row['업종']} | 검색 없음 | - | - | 0")
            continue
        print(
            f"{row['브랜드']} | {row['업종']} | {row['검색']} | {row['후보']}"
            f"({row['브랜드명_후보']}) | {row['운영_중복']} | {row['선택']}"
            f"({row['선택_브랜드명']}·{row['선택_업종류']})"
        )
    print("[예상 호출] " + json.dumps(plan["estimated_calls"], ensure_ascii=False))
    return 0


def _run_plan_command(args) -> int:
    if not args.file_staging:
        print("[오류] --run-plan 에는 --file-staging 이 필요합니다.", file=sys.stderr)
        return 1
    plan = json.loads(Path(args.run_plan).read_text(encoding="utf-8"))
    try:
        report = run_selection_plan(
            plan,
            args.file_staging,
            source_label=args.source_label,
            limit=args.limit or None,
            max_calls=args.max_calls,
            archive_dir=args.prune_archive,
            industry_order=args.industry_order,
        )
    except ValueError as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 1
    ready, error = inspect_file_staging(args.file_staging)
    brands = report.pop("브랜드별")
    print("브랜드 | 업종 | 새로 대상 | 받음 | 뺌 | 완료")
    for row in brands:
        print(f"{row['브랜드']} | {row['업종']} | {row['새로_대상']} | {row['받음']} | "
              f"{row['뺌']} | {'예' if row['완료'] else '아니오(이전 건 유지)'}")
    outside = len(set(_staged_records(args.file_staging)) - {
        r["출원번호"] for r in plan["records"]})
    if outside and not args.prune_archive:
        print(f"[안내] 계획에 없는 스테이징 레코드 {outside}건 — 빼려면 --prune-archive DIR",
              file=sys.stderr)
    print("[리포트] " + json.dumps(report, ensure_ascii=False))
    print(f"[스테이징] {args.file_staging} — 점검 {'통과' if ready else '실패: ' + str(error)}")
    _print_counter()
    if not ready:
        return 1
    return 3 if report["멈춤"] else 0


def _print_counter() -> None:
    limiter = kipris_client.limiter
    print(
        f"[카운터] {limiter.counter_path} — 이번 달 {limiter.used_this_month()}회, "
        f"오늘 {limiter.used_today()}회"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="KIPRIS 상표 이미지 수집 파이프라인")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--applicant", action="append", help="출원인(회사명). 반복 지정 가능")
    group.add_argument(
        "--applicants-file",
        help="출원인 목록 파일 (줄당 1개, # 주석. [브랜드] 표가 있으면 그 출원인명 열)",
    )
    group.add_argument("--mock-xml", help="API 대신 사용할 저장된 XML 파일 (개발 테스트)")
    group.add_argument(
        "--run-plan",
        metavar="PLAN",
        help="--select-plan 이 쓴 계획을 실행(서지 1회 + 견본 즉시 다운로드 → --file-staging)",
    )
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
    ap.add_argument("--key-env", metavar="NAME",
                    help="KIPRIS 키를 담은 환경변수 이름(값은 출력·저장하지 않음, .env 그대로)")
    ap.add_argument("--counter", type=Path, metavar="PATH",
                    help="이 키 전용 호출 카운터 파일(공용 카운터는 그대로)")
    ap.add_argument("--search-only", action="store_true",
                    help="출원인 검색 원본만 저장하고 --search-manifest 에 적는다(다운로드 없음)")
    ap.add_argument("--search-manifest", type=_file_staging_arg, metavar="PATH",
                    help="출원인 검색 목록 JSON(ml/data/staging 아래)")
    ap.add_argument("--select-plan", type=_file_staging_arg, metavar="PATH",
                    help="검색 목록에서 출원인당 상한만큼 골라 계획 JSON 을 쓴다(호출 0)")
    ap.add_argument("--max-per-applicant", type=_positive_int_arg,
                    default=DEFAULT_MAX_PER_APPLICANT, metavar="N",
                    help=f"--select-plan 출원인당 상한(기본 {DEFAULT_MAX_PER_APPLICANT})")
    ap.add_argument("--source-label", default="유명 브랜드",
                    help=f"--run-plan 레코드의 {SOURCE_LABEL_FIELD} 값(기본 '유명 브랜드')")
    ap.add_argument("--prune-archive", type=Path, metavar="DIR",
                    help="--run-plan: 브랜드의 새 건을 다 받은 뒤 그 브랜드의 계획 밖 스테이징 "
                         "레코드를 빼고 견본을 DIR 로 옮김")
    ap.add_argument("--industry-order", type=lambda raw: [x for x in raw.split(",") if x],
                    metavar="ID,ID,...", help="--run-plan 업종 처리 순서(빠진 업종은 뒤에)")
    ap.add_argument("--max-calls", type=_positive_int_arg, metavar="N",
                    help="--search-only·--run-plan 이번 실행 KIPRIS API 호출 상한"
                         "(검색·서지, 견본 다운로드는 따로 셈)")
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
    if args.search_only and (args.select_plan or args.plan or args.dry_run):
        ap.error("--search-only 는 --select-plan·--plan·--dry-run 과 함께 쓸 수 없습니다.")
    if args.select_plan and (args.plan or args.dry_run):
        ap.error("--select-plan 은 --plan·--dry-run 과 함께 쓸 수 없습니다.")

    if args.key_env or args.counter:
        info = use_key_and_counter(key_env=args.key_env, counter=args.counter)
        print("[키·카운터] " + json.dumps(info, ensure_ascii=False))
    if args.run_plan:
        return _run_plan_command(args)
    if args.select_plan:
        return _select_plan_command(args)

    # ---- 입력 소스 구성 ----
    if args.mock_xml:
        xml_text = Path(args.mock_xml).read_text(encoding="utf-8")
        items = kipris_client.parse_items(xml_text)
        mock_items = [kipris_client.normalize_advanced_item(it) for it in items]
        sources = ["(mock)"]
        duplicate_source_count = 0
    else:
        raw_sources = args.applicant or read_applicants_file(Path(args.applicants_file))
        sources, duplicate_source_count = _deduplicate_sources(raw_sources)
        if not sources:
            print("[오류] 수집할 출원인이 없습니다.", file=sys.stderr)
            return 1
        if args.search_only:
            return _search_only_command(sources, args)

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
    try:
        checkpoint = load_checkpoint(checkpoint_path)
    except CheckpointError as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 1
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
                                kipris_client.download_file_now(
                                    image_url, dest, validate_image=True
                                )
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
