"""
다빈-1: 상표 심결례(정답 데이터) 수집 파이프라인 1단계 — KIPRIS Plus 심판사항 API.

    list     월별 항목별검색(getAdvancedSearch)으로 상표 심판 목록 → ml/data/trials/list.csv
    fetch    심판(결)문(getJudDocumentInfoSearch) 경로 조회 → 즉시 PDF 다운로드 → pdf/{심판번호}.pdf
    extract  PyMuPDF 텍스트 추출 + 정규식 선별 → text/{심판번호}.txt, prefilter.csv
    sheet    사람 라벨링용 시트 초안 → labels.csv
    status   예산(quota.json)·건수·단계별 진행 요약

실행 (project root 기준):
    ml/venv/bin/python -m backend.scripts.trials_collect list --kind refusal \\
        --from 202401 --to 202403 --dry-run
    ml/venv/bin/python -m backend.scripts.trials_collect fetch --limit 20 --max-calls 60
    ml/venv/bin/python -m backend.scripts.trials_collect extract | sheet | status

공통 안전장치
    --dry-run      네트워크 호출 0회. 계획·예산만 출력(collect_pipeline 의 --plan 에 해당.
                   collect_pipeline 의 --dry-run 은 API 를 호출하므로 뜻이 다르다).
    --max-calls N  이번 실행 호출 하드캡(기본 50). KIPRIS_TRIAL_COUNT_DOWNLOADS=1(기본)이면
                   PDF 다운로드도 한 회로 센다(서버 카운트 포함 여부 미확인 → 보수적).
    멱등           list 는 완료한 월(list_progress.json), fetch 는 받은 PDF·실패 기록,
                   extract 는 만든 텍스트를 건너뛴다.
    키             KIPRIS_TRIAL_ACCESS_KEY, 없으면 KIPRIS_ACCESS_KEY.
    예산           출원속보 카운터(kipris_call_count.json, KIPRIS_DAILY_BUDGET 80)와 분리 —
                   KIPRIS_TRIAL_DAILY_BUDGET(300)·KIPRIS_TRIAL_MONTHLY_BUDGET(950), 카운터
                   ml/data/trials/quota.json. kipris_client.RateLimiter 를 별도 인스턴스로 쓴다
                   (초당 50회 제한은 KIPRIS_MIN_INTERVAL 0.1s 그대로). kipris_client._get 은
                   공용 리미터를 소모하므로 부르지 않는다.

설계 (2026-09-30 명세 캡처 + 2026-07 실측. 호스트 뒤 경로만 적음)
    항목별검색 getAdvancedSearch — kipo-api/kipi/judgmentInfoSearchService/getAdvancedSearch
        인증 미확인(ServiceKey 로 가정). 입력 trialDesc·trialDate(YYYYMM)·tradeMark/patent/
        practical/design·patentTrial·patentCourt·supremeCourt·summaryCourt·appealCourt·
        exParte/interParties·pageNo·numOfRows. 응답 body/items/item{trialNumber, trialFlag,
        trialDesc, trialStatus, plaintiff, title, trialDecisionDoc, applicationNumber,
        appReferenceNumber, registrationNumber, RegReferenceNumber,
        InternationalRegisterNumber, defendant} + numOfRows/pageNo/totalCount
    심판(결)문 getJudDocumentInfoSearch — …/getJudDocumentInfoSearch?trialNumber=  ServiceKey(샘플)
        응답 body/item{fileName, kind, openYN, path}. path 는 fileToss 일회성 링크 → 즉시 다운로드
    서지상세 getBibliographyDetailInfoSearch — …?trialNumber=  ServiceKey(샘플). 이번 단계 미사용
        item/bibliographicSummaryInfo{cdDesc 심판종류, conclusiveResultCode 심판확정결과(샘플
        "청구성립"), conclusiveStatusCode, trialDecision 심결주문내용, trialDecisionCode,
        trialDecisionDate, trialStatusCode 심판상태, rightDivisionCode, path, …}
    심판종류 trialDescSearchInfo — openapi/rest/judgmentInfoSearchService/trialDescSearchInfo
        accessKey(샘플), docsStart/docsCount 페이징, items/TotalSearchCount/TrialInfo.
        샘플에서 trialDecisionDoc=N, trialStatus=심결 확인

2026-09-30 실호출 검증 결과(2024-01 상표·특허심판원 203건, 총 45회)
    ① 항목별검색 인증 파라미터 = ServiceKey (첫 호출 성공). 심결문·서지상세도 ServiceKey.
    ② trialDesc 값: 취소 97 · 거절결정불복 93 · 무효 11 · 권리범위확인(적극적) 1 ·
       권리범위확인(소극적) 1
       → trials_kinds.json verified=true. 권리범위확인은 값 2개라 월 2회 호출.
    ③ numOfRows=500 그대로 적용됨(203건 1페이지, 응답 numOfRows 500).
    ④ trialStatus 는 확정 106 · 심결 97 — 결과(인용/기각) 정보 없음 → 심결문 주문 또는 서지상세로
       판독.
    ⑤ trialDecisionDoc = Y 192 · N 11 (Y/N 문서 유무 플래그).
    ⑥ 심결문 kind 는 20건 모두 S10221(심결문). 목록 응답 항목명은 lowerCamel
       (internationalRegisterNumber, regReferenceNumber).
    ⑦ 서지상세: 미확정(심결) 건은 conclusiveResultCode 가 비고 trialDecisionCode(기각/취소환송)가
       PDF 주문과 4/4 일치. 다운로드의 서버 카운트 포함 여부는 여전히 미확인(마이페이지로 확인).
    ⑧ 출원번호 앞자리 40 170 · 41 18 · 45 13 · 70 1 · 44 1 — 70/44 는 현재 필터에서 빠진다.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.src.core import kipris_client as kc  # noqa: E402
from backend.src.core import paths  # noqa: E402

# ====================================================================
# 설정
# ====================================================================

JUDGMENT_SERVICE_PATH = "kipo-api/kipi/judgmentInfoSearchService/"
SEARCH_URL: str = os.getenv("KIPRIS_TRIAL_SEARCH_URL", "") or kc._compose_url(
    kc.KIPRIS_BASE_URL, JUDGMENT_SERVICE_PATH + "getAdvancedSearch"
)
DOC_URL: str = os.getenv("KIPRIS_TRIAL_DOC_URL", "") or kc._compose_url(
    kc.KIPRIS_BASE_URL, JUDGMENT_SERVICE_PATH + "getJudDocumentInfoSearch"
)
BIBLIO_URL: str = os.getenv("KIPRIS_TRIAL_BIBLIO_URL", "") or kc._compose_url(
    kc.KIPRIS_BASE_URL, JUDGMENT_SERVICE_PATH + "getBibliographyDetailInfoSearch"
)
# 인증 파라미터명. 심결문·서지 캡처 샘플은 ServiceKey — 항목별검색은 미확인이라 env 로 바꿀 수
# 있게 둔다.
SEARCH_AUTH_PARAM: str = os.getenv("KIPRIS_TRIAL_SEARCH_AUTH_PARAM", "ServiceKey")
DOC_AUTH_PARAM: str = os.getenv("KIPRIS_TRIAL_DOC_AUTH_PARAM", "ServiceKey")
BIBLIO_AUTH_PARAM: str = os.getenv("KIPRIS_TRIAL_BIBLIO_AUTH_PARAM", "ServiceKey")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# 예산 — 출원속보(kipris_client.MONTHLY_CALL_BUDGET / DAILY_CALL_BUDGET)와 별개의 값·카운터.
TRIAL_DAILY_BUDGET: int = _env_int("KIPRIS_TRIAL_DAILY_BUDGET", 300)
TRIAL_MONTHLY_BUDGET: int = _env_int("KIPRIS_TRIAL_MONTHLY_BUDGET", 950)
# PDF 다운로드를 호출로 셀지(기본 1=센다). 서버 카운트 포함 여부 확인 뒤 0 으로 바꿀 수 있다.
COUNT_DOWNLOADS: bool = os.getenv("KIPRIS_TRIAL_COUNT_DOWNLOADS", "1").strip().lower() not in (
    "0", "false", "no", ""
)
# 페이지당 건수. 최댓값 미확인 — 상표 getAdvancedSearch 는 500 이 상한(실측)이라 같은 값을 기본으로.
DEFAULT_ROWS: int = _env_int("KIPRIS_TRIAL_ROWS", 500)
DEFAULT_MAX_CALLS: int = 50
TRADEMARK_NUMBER_PREFIXES: tuple[str, ...] = ("40", "41", "45")
KINDS_CONFIG_PATH: Path = Path(__file__).with_name("trials_kinds.json")


def access_key() -> str:
    """심판사항 키. 별도 신청 키(KIPRIS_TRIAL_ACCESS_KEY)가 없으면 공용 KIPRIS_ACCESS_KEY."""
    return os.getenv("KIPRIS_TRIAL_ACCESS_KEY", "").strip() or os.getenv(
        "KIPRIS_ACCESS_KEY", ""
    ).strip()


@dataclass(frozen=True)
class TrialPaths:
    """산출물 위치(ml/data/trials 아래 — 전부 gitignore)."""

    base: Path

    @property
    def list_csv(self) -> Path:
        return self.base / "list.csv"

    @property
    def list_progress(self) -> Path:
        return self.base / "list_progress.json"

    @property
    def raw_xml_dir(self) -> Path:
        return self.base / "raw_xml"

    @property
    def pdf_dir(self) -> Path:
        return self.base / "pdf"

    @property
    def text_dir(self) -> Path:
        return self.base / "text"

    @property
    def fetch_log(self) -> Path:
        return self.base / "fetch_log.csv"

    @property
    def prefilter_csv(self) -> Path:
        return self.base / "prefilter.csv"

    @property
    def labels_csv(self) -> Path:
        return self.base / "labels.csv"

    @property
    def quota(self) -> Path:
        return self.base / "quota.json"

    @property
    def calls_log(self) -> Path:
        return self.base / "calls.log"

    @property
    def biblio_dir(self) -> Path:
        return self.base / "biblio"


DEFAULT_PATHS = TrialPaths(paths.ML_DATA_DIR / "trials")

LIST_COLUMNS = [
    "심판번호", "종류", "심결월", "심판상태", "상표명칭", "출원번호", "등록번호",
    "청구인", "피청구인", "심결문유무", "원본JSON",
]
FETCH_LOG_COLUMNS = ["심판번호", "결과", "파일명", "kind", "일시"]
LABEL_COLUMNS = [
    "심판번호", "종류", "심판상태", "심결월", "상표A_번호", "상표A_명칭", "상표B_번호",
    "지정상품_원문", "조문플래그", "결론조문", "자동등급", "등급사유", "등급_보일러플레이트제외",
    "참고표시", "유사여부_추정", "추정근거", "유사여부_확정", "판단축", "제외사유", "메모",
]


# ====================================================================
# 심판종류 설정 (trialDesc 값은 검증 후 고정)
# ====================================================================

def load_kinds(path: Path = KINDS_CONFIG_PATH) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in payload.items() if not k.startswith("_")}


def trial_desc_values(spec: dict) -> list[str]:
    """설정의 trialDesc(문자열 또는 배열)를 값 목록으로."""
    value = spec.get("trialDesc", "")
    return [v for v in (value if isinstance(value, list) else [value]) if v]


def kind_for_trial_desc(trial_desc: str, kinds: dict[str, dict]) -> str:
    """응답의 trialDesc 원문 → kind 키(refusal/invalidation/scope). 못 찾으면 ''."""
    text = (trial_desc or "").strip()
    for key, spec in kinds.items():
        if text in trial_desc_values(spec) or text in spec.get("candidates", []):
            return key
    if "거절" in text:
        return "refusal"
    if "무효" in text:
        return "invalidation"
    if "권리범위" in text:
        return "scope"
    return ""


# ====================================================================
# 호출 세션 — 하드캡·예산·로그 (네트워크는 transport 로 주입 → 테스트는 가짜 transport)
# ====================================================================

class HardCapReached(RuntimeError):
    """--max-calls 하드캡 도달 — 정상 종료 신호."""


Transport = Callable[[str, dict], str]


def _http_transport(url: str, params: dict) -> str:
    """실제 GET (kipris_client 의 공용 httpx 클라이언트 재사용, 공용 리미터는 쓰지 않는다)."""
    import httpx

    try:
        resp = kc._get_client().get(url, params=params, timeout=30)
        resp.raise_for_status()
    except httpx.TimeoutException:
        raise kc.KiprisNetworkError("KIPRIS 심판사항 응답 시간이 초과되었습니다.") from None
    except httpx.HTTPStatusError:
        raise kc.KiprisNetworkError("KIPRIS 심판사항 서비스가 HTTP 오류를 반환했습니다.") from None
    except httpx.RequestError:
        raise kc.KiprisNetworkError("KIPRIS 심판사항 서비스와 통신하지 못했습니다.") from None
    return resp.text


@dataclass
class Session:
    """한 번의 실행에서 호출 수를 세고 예산(quota.json)·하드캡을 강제한다."""

    paths: TrialPaths = DEFAULT_PATHS
    max_calls: int = DEFAULT_MAX_CALLS
    dry_run: bool = False
    transport: Transport = _http_transport
    downloader: Callable[[str, Path], Path] = kc.download_file_now
    api_calls: int = 0
    downloads: int = 0
    _limiter: kc.RateLimiter | None = field(default=None, repr=False)

    @property
    def limiter(self) -> kc.RateLimiter:
        if self._limiter is None:
            self._limiter = kc.RateLimiter(
                counter_path=self.paths.quota,
                monthly_budget=TRIAL_MONTHLY_BUDGET,
                daily_budget=TRIAL_DAILY_BUDGET,
                min_interval=kc.MIN_CALL_INTERVAL_SEC,
            )
        return self._limiter

    @property
    def counted(self) -> int:
        return self.api_calls + (self.downloads if COUNT_DOWNLOADS else 0)

    def _charge(self, what: str, note: str) -> None:
        if self.dry_run:
            raise RuntimeError("dry-run 에서 호출을 시도했습니다 — 코드 버그")
        if self.counted >= self.max_calls:
            raise HardCapReached(f"--max-calls {self.max_calls} 도달 ({what}: {note})")
        self.limiter.acquire()  # 예산 초과면 CallBudgetExceeded
        self.paths.base.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.paths.calls_log.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp}\t{what}\t{note}\n")

    def api_get(self, url: str, params: dict, auth_param: str) -> str:
        """리미터·하드캡을 통과한 뒤 GET. 키는 로그·예외에 싣지 않는다."""
        kc._validate_kipris_url(url, "KIPRIS 심판사항 URL")
        key = access_key()
        if not key:
            raise kc.KiprisConfigError(
                "KIPRIS_TRIAL_ACCESS_KEY(또는 KIPRIS_ACCESS_KEY)가 없습니다. "
                "심판사항 상품을 신청한 뒤 .env 에 넣으세요 (커밋 금지)."
            )
        logged = ("trialDesc", "trialDate", "pageNo", "trialNumber")
        summary = ",".join(f"{k}={v}" for k, v in params.items() if k in logged)
        self._charge("api", f"{url.rsplit('/', 1)[-1]} {summary}")
        self.api_calls += 1
        return self.transport(url, {**params, auth_param: key})

    def download(self, url: str, dest: Path) -> Path:
        if COUNT_DOWNLOADS:
            self._charge("download", dest.name)
        elif self.dry_run:
            raise RuntimeError("dry-run 에서 다운로드를 시도했습니다 — 코드 버그")
        self.downloads += 1
        return self.downloader(url, dest)

    def budget_line(self) -> str:
        """dry-run·status 용 예산 요약(quota.json 을 읽기만 한다)."""
        try:
            used_month = self.limiter.used_this_month()
            used_day = self.limiter.used_today()
        except kc.KiprisConfigError as exc:
            return f"quota.json 읽기 실패: {exc}"
        return (
            f"이번 달 {used_month}/{TRIAL_MONTHLY_BUDGET}회 사용"
            f"(남은 {TRIAL_MONTHLY_BUDGET - used_month}), "
            f"오늘 {used_day}/{TRIAL_DAILY_BUDGET}회 사용 · "
            f"이번 실행 하드캡 {self.max_calls}회 · "
            f"다운로드 카운트 {'포함' if COUNT_DOWNLOADS else '제외'} · 카운터 {self.paths.quota}"
        )


# ====================================================================
# XML 파싱 (순수 함수)
# ====================================================================

def parse_search_page(xml_text: str) -> tuple[list[dict], int | None]:
    """항목별검색 응답 → (item dict 목록, totalCount). resultCode != 00 이면 KiprisError."""
    items = kc.parse_items(xml_text)
    return items, kc.parse_advanced_total_count(xml_text)


def parse_doc_response(xml_text: str) -> dict:
    """심판(결)문 응답 → {fileName, kind, openYN, path}. 항목이 없으면 빈 값들."""
    kc.check_result_code(xml_text)
    root = ET.fromstring(xml_text)
    item = kc._find_first(root, "item")
    result = {"fileName": "", "kind": "", "openYN": "", "path": ""}
    if item is not None:
        for child in item:
            tag = kc._local_name(child.tag)
            if tag in result:
                result[tag] = (child.text or "").strip()
    return result


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def is_trademark_item(item: dict) -> bool:
    """출원번호(없으면 등록번호) 앞자리 40/41/45 만 상표로 본다(특허 혼입 방지 안전 필터)."""
    number = _digits(item.get("applicationNumber", "")) or _digits(
        item.get("registrationNumber", "")
    )
    return number[:2] in TRADEMARK_NUMBER_PREFIXES


def item_to_list_row(item: dict, month: str) -> dict:
    return {
        "심판번호": item.get("trialNumber", "").strip(),
        "종류": item.get("trialDesc", "").strip(),
        "심결월": month,
        "심판상태": item.get("trialStatus", "").strip(),
        "상표명칭": item.get("title", "").strip(),
        "출원번호": _digits(item.get("applicationNumber", "")),
        "등록번호": _digits(item.get("registrationNumber", "")),
        "청구인": item.get("plaintiff", "").strip(),
        "피청구인": item.get("defendant", "").strip(),
        "심결문유무": item.get("trialDecisionDoc", "").strip(),
        "원본JSON": json.dumps(item, ensure_ascii=False, sort_keys=True),
    }


# ====================================================================
# list — 월별 항목별검색
# ====================================================================

def month_range(start: str, end: str) -> list[str]:
    """YYYYMM 포함 범위. 형식·순서가 틀리면 ValueError."""
    for value in (start, end):
        if not re.fullmatch(r"\d{6}", value) or not 1 <= int(value[4:]) <= 12:
            raise ValueError(f"YYYYMM 형식이어야 합니다: {value!r}")
    if start > end:
        raise ValueError("--from 이 --to 보다 뒤입니다.")
    months: list[str] = []
    year, month = int(start[:4]), int(start[4:])
    while f"{year:04d}{month:02d}" <= end:
        months.append(f"{year:04d}{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return months


def build_search_params(trial_desc: str, month: str, page_no: int, rows: int) -> dict:
    """상표만·특허심판원만·결정계+당사자계, 심결일자 월 단위. trial_desc 가 비면 종류 필터 없음."""
    params: dict = {"trialDesc": trial_desc} if trial_desc else {}
    params.update({
        "trialDate": month,
        "tradeMark": "true",
        "patent": "false",
        "practical": "false",
        "design": "false",
        "patentTrial": "true",
        "patentCourt": "false",
        "supremeCourt": "false",
        "summaryCourt": "false",
        "appealCourt": "false",
        "exParte": "true",
        "interParties": "true",
        "pageNo": str(page_no),
        "numOfRows": str(rows),
    })
    return params


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _append_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_progress(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_progress(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _save_raw(paths_: TrialPaths, name: str, xml_text: str) -> Path:
    paths_.raw_xml_dir.mkdir(parents=True, exist_ok=True)
    dest = paths_.raw_xml_dir / name
    dest.write_text(xml_text, encoding="utf-8")
    return dest


def run_list(args: argparse.Namespace, session: Session) -> int:
    kinds = load_kinds(args.kinds_config)
    kind = getattr(args, "kind", "") or ""
    if kind and kind not in kinds:
        print(f"[오류] --kind 는 {', '.join(kinds)} 중 하나여야 합니다(생략 = 전체).",
              file=sys.stderr)
        return 2
    spec = kinds[kind] if kind else None
    trial_descs = trial_desc_values(spec) if spec else [""]  # "" = 종류 필터 없음
    trial_desc = trial_descs[0]
    verified = bool(spec.get("verified")) if spec else True  # 필터 없음 = 검증할 값 없음
    progress_key = kind or "all"
    months = month_range(getattr(args, "from"), args.to)
    progress = load_progress(session.paths.list_progress)
    done = progress.get(progress_key, {})
    pending = [m for m in months if not done.get(m, {}).get("done")]
    rows_per_page = args.rows

    label = "종류 필터 없음"
    if kind:
        label = f"--kind {kind} (trialDesc={trial_descs!r}, verified={verified})"
    print(f"## list {label}")
    print(f"- 기간 {months[0]}~{months[-1]} {len(months)}개월, 미완료 {len(pending)}개월")
    planned = len(trial_descs) * len(pending)
    print(f"- 호출 계획: 월 {len(trial_descs)}회 × {len(pending)}개월 = {planned}회 "
          f"(numOfRows={rows_per_page}; totalCount 가 "
          f"넘으면 페이지 추가 호출 = ceil(totalCount/{rows_per_page}) - 1, "
          f"월당 최대 {args.max_pages}쪽)")
    print(f"- 요청: GET {SEARCH_URL} 인증 {SEARCH_AUTH_PARAM} · "
          f"키 {'있음' if access_key() else '없음'}")
    sample_month = pending[0] if pending else months[0]
    print(f"- 파라미터 예: {build_search_params(trial_desc, sample_month, 1, rows_per_page)}")
    print(f"- 예산: {session.budget_line()}")
    if not verified:
        print("- 주의: trialDesc 값이 미검증 상태(trials_kinds.json verified=false) — 실호출은 "
              "--allow-unverified 로만 가능. 첫 실호출 1개월치로 응답의 trialDesc 값 집합을 확인해 "
              "고정하세요.")
    if session.dry_run:
        print("[dry-run] 실호출 0회 — 위 계획만 출력하고 종료합니다.")
        return 0
    if not verified and not args.allow_unverified:
        print("[중단] trialDesc 미검증 — --allow-unverified 를 붙이거나 trials_kinds.json 을 "
              "확정하세요.", file=sys.stderr)
        return 2

    existing = {row["심판번호"] for row in _read_csv(session.paths.list_csv)}
    added = excluded = 0
    exit_code = 0
    for month in pending:
        page, total = 1, None
        pages_done = 0
        try:
            for index, desc in enumerate(trial_descs):
                suffix = f"_d{index}" if len(trial_descs) > 1 else ""
                page = 1
                while True:
                    params = build_search_params(desc, month, page, rows_per_page)
                    xml_text = session.api_get(SEARCH_URL, params, SEARCH_AUTH_PARAM)
                    _save_raw(session.paths, f"list_{progress_key}_{month}{suffix}_p{page}.xml",
                              xml_text)
                    items, total = parse_search_page(xml_text)
                    pages_done += 1
                    rows = []
                    for item in items:
                        if not is_trademark_item(item):
                            excluded += 1
                            continue
                        row = item_to_list_row(item, month)
                        if row["심판번호"] and row["심판번호"] not in existing:
                            existing.add(row["심판번호"])
                            rows.append(row)
                    _append_csv(session.paths.list_csv, LIST_COLUMNS, rows)
                    added += len(rows)
                    needed = math.ceil(total / rows_per_page) if total else 1
                    if not items or page >= needed or page >= args.max_pages:
                        break
                    page += 1
        except HardCapReached as exc:
            print(f"[중단] {exc}")
            exit_code = 3
            progress.setdefault(progress_key, {})[month] = {
                "total": total, "pages": pages_done, "done": False,
            }
            save_progress(session.paths.list_progress, progress)
            break
        progress.setdefault(progress_key, {})[month] = {
            "total": total,
            "pages": pages_done,
            "done": True,
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        save_progress(session.paths.list_progress, progress)
        print(f"  {month}: totalCount={total} 페이지 {pages_done}")
    print(f"- 결과: 신규 {added}건 추가(특허 등 제외 {excluded}건), 호출 {session.api_calls}회 → "
          f"{session.paths.list_csv}")
    return exit_code


# ====================================================================
# fetch — 심판(결)문 경로 조회 + 즉시 다운로드
# ====================================================================

def _is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def pending_fetch_rows(paths_: TrialPaths, *, skip_no_doc: bool, retry_failed: bool) -> list[dict]:
    rows = _read_csv(paths_.list_csv)
    failed = {r["심판번호"] for r in _read_csv(paths_.fetch_log) if r.get("결과") != "ok"}
    pending = []
    for row in rows:
        number = row["심판번호"]
        if not number or (paths_.pdf_dir / f"{number}.pdf").exists():
            continue
        if number in failed and not retry_failed:
            continue
        if skip_no_doc and row.get("심결문유무", "").upper() == "N":
            continue
        pending.append(row)
    return pending


def select_fetch_targets(
    pending: list[dict],
    limit: int,
    kind_priority: list[str],
    prefer_doc: bool,
    trials: set[str],
    kinds: dict[str, dict],
) -> list[dict]:
    """대상 선정: --trial 지정 건만 / 종류 우선순위 / 심결문유무 Y 우선 (안정 정렬)."""
    if trials:
        pending = [row for row in pending if row["심판번호"] in trials]

    def sort_key(row: dict) -> tuple[int, int]:
        kind = kind_for_trial_desc(row.get("종류", ""), kinds)
        rank = kind_priority.index(kind) if kind in kind_priority else len(kind_priority)
        has_doc = 0 if row.get("심결문유무", "").upper() == "Y" else 1
        return (rank if kind_priority else 0, has_doc if prefer_doc else 0)

    ordered = sorted(pending, key=sort_key) if (kind_priority or prefer_doc) else list(pending)
    return ordered[:limit] if limit else ordered


def run_fetch(args: argparse.Namespace, session: Session) -> int:
    pending = pending_fetch_rows(
        session.paths, skip_no_doc=args.skip_no_doc, retry_failed=args.retry_failed
    )
    raw_priority = getattr(args, "kind_priority", "") or ""
    priority = [k.strip() for k in raw_priority.split(",") if k.strip()]
    targets = select_fetch_targets(
        pending, args.limit, priority, bool(getattr(args, "prefer_doc", False)),
        set(getattr(args, "trial", None) or []),
        load_kinds(getattr(args, "kinds_config", KINDS_CONFIG_PATH)),
    )
    per_item = 2 if COUNT_DOWNLOADS else 1
    listed = len(_read_csv(session.paths.list_csv))
    print(f"## fetch (list.csv {listed}건, PDF 미수신 {len(pending)}건)")
    print(f"- 이번 대상 {len(targets)}건(--limit {args.limit or '없음'}) → 호출 {len(targets)}회 + "
          f"다운로드 {len(targets)}회 = 카운트 {len(targets) * per_item}회")
    print(f"- 요청: GET {DOC_URL} 인증 {DOC_AUTH_PARAM} · 키 {'있음' if access_key() else '없음'}")
    print(f"- 예산: {session.budget_line()}")
    if session.dry_run:
        print("[dry-run] 실호출 0회 — 위 계획만 출력하고 종료합니다.")
        return 0

    done = 0
    log_rows: list[dict] = []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    exit_code = 0
    try:
        for row in targets:
            number = row["심판번호"]
            xml_text = session.api_get(DOC_URL, {"trialNumber": number}, DOC_AUTH_PARAM)
            _save_raw(session.paths, f"doc_{number}.xml", xml_text)
            doc = parse_doc_response(xml_text)
            if doc["openYN"].upper() != "Y" or not doc["path"]:
                result = "not_open" if doc["path"] else "no_path"
                log_rows.append({"심판번호": number, "결과": result, "파일명": doc["fileName"],
                                 "kind": doc["kind"], "일시": stamp})
                continue
            dest = session.paths.pdf_dir / f"{number}.pdf"
            session.download(doc["path"], dest)  # 일회성 링크 → 응답 직후 바로 받는다
            if not _is_pdf(dest):
                dest.unlink(missing_ok=True)
                log_rows.append({"심판번호": number, "결과": "bad_pdf", "파일명": doc["fileName"],
                                 "kind": doc["kind"], "일시": stamp})
                continue
            log_rows.append({"심판번호": number, "결과": "ok", "파일명": doc["fileName"],
                             "kind": doc["kind"], "일시": stamp})
            done += 1
    except HardCapReached as exc:
        print(f"[중단] {exc}")
        exit_code = 3
    finally:
        _append_csv(session.paths.fetch_log, FETCH_LOG_COLUMNS, log_rows)
    print(f"- 결과: PDF {done}건 저장, 호출 {session.api_calls}회·다운로드 {session.downloads}회 → "
          f"{session.paths.pdf_dir}")
    return exit_code


# ====================================================================
# extract — 텍스트 추출 + 정규식 선별 (analyze_text 는 순수 함수)
# ====================================================================

def extract_pdf_text(pdf_path: Path) -> str:
    """PyMuPDF 로 페이지 텍스트를 이어 붙인다(페이지 경계는 폼피드). 의존성은 여기서만 import."""
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        return "\f".join(page.get_text() for page in doc)


# 조문 번호 정규화: 현행 34조1항 N호 ↔ 구법 7조1항 N호 (7→7, 9→9, 10→11, 11→12, 12→13),
# 구법 6조 ↔ 33조.
OLD_LAW_MAP = {7: 7, 9: 9, 10: 11, 11: 12, 12: 13}
_ARTICLE_RE = re.compile(r"제\s*(34|7)\s*조\s*제\s*1\s*항\s*제\s*(\d{1,2})\s*호")
_ARTICLE_33_RE = re.compile(r"(?:상표법\s*)?제\s*(33|6)\s*조(?:\s*제\s*1\s*항)?")
# "…제34조 제1항 제7호(및 제11호)에(는) (각각) 해당한다/하므로/하지 아니한다" — 긍정·부정 판독
_CONCLUSION_RE = re.compile(
    r"제\s*(34|7)\s*조\s*제\s*1\s*항\s*제\s*(\d{1,2})\s*호"
    r"(?:\s*(?:및|,|와|과|또는)\s*(?:제\s*)?(\d{1,2})\s*호)?"
    r"(?:\s*의\s*규정)?\s*(?:에(?:는|도)?\s*)?(?:각각\s*)?(?:더\s*이상\s*)?"
    r"(해당\s*(?:하지\s*(?:아니|않)|되지\s*(?:아니|않)|하[여지므]|한다|되[어므]|됨|함|되어야|한|되는))"
)
# 선등록상표 소멸·무효 등으로 7호 적용이 없어져 원결정이 취소된 사례 — 유사 판단이 없는 취소
# (제외 후보 표시용)
_PRIOR_MARK_GONE_RE = re.compile(
    r"(?:소멸|말소|무효\s*심결|무효로\s*되|존속기간\s*만료|포기)[\s\S]{0,120}?"
    r"(?:더\s*이상|않게\s*되|해당하지)"
)
# 등록번호 표기: 상표등록 제N호 / 서비스표등록 제N호 / 국제상표(등록) 제N호 / 국제등록 제N호
_REG_NUMBER_RE = re.compile(r"(?:상표|서비스표|국제상표|국제)\s*등록\s*제\s*([\d\-]+)\s*호")
_HEADING_RE = re.compile(r"^\s*([가-힣]\.)\s*(.+?)\s*$", re.MULTILINE)
_TOP_HEADING = r"(?m)^\s*\d+\.\s*\S"
_ANY_HEADING = r"(?m)^\s*(?:\(\d+\)|\([가-힣]\)|[가-힣]\.|\d+\.)\s*\S"
_PRIOR_MARK = r"(?:선등록|선사용|선출원|비교대상|인용)\s*(?:상표|서비스표|표장)"
# 요부 판단기준의 판례 문구("…주지ㆍ저명하거나 일반수요자에게 강한 인상을…") — 인지도 사례가
# 아니어도 거의 모든 7호 심결문에 등장한다. 본문_저명주지_실질 은 이 문구를 뺀 뒤의 언급 여부.
_FAME_BOILERPLATE_RE = re.compile(r"주지\s*[ㆍ·․,]?\s*저명\s*하거나")
_SECTION_TITLES = ("소결론", "소결", "결론", "판단")
KEYWORDS = {"저명": "저명", "주지": "주지", "부정한목적": "부정한 목적", "식별력": "식별력"}


def _norm_article(law: str, number: int) -> str | None:
    if law == "34":
        return f"34-{number}" if number in (7, 9, 11, 12, 13) else f"34-{number}"
    mapped = OLD_LAW_MAP.get(number)
    return f"34-{mapped}" if mapped else f"구7-{number}"


def _find_block(text: str, start_pattern: str, end_patterns: tuple[str, ...]) -> str:
    match = re.search(start_pattern, text)
    if not match:
        return ""
    rest = text[match.end():]
    end = len(rest)
    for pattern in end_patterns:
        found = re.search(pattern, rest)
        if found and found.start() < end:
            end = found.start()
    return rest[:end]


def _conclusion_blocks(text: str) -> list[str]:
    """'소결'·'소결론'·'결론' 제목의 절 본문 — 실제 적용 조문은 여기서 읽는다.

    제목 표시는 (1)·(가)·가.·1. 네 가지를 모두 받는다(2024년 심결문은 "(다) 소결", "다. 소결론").
    """
    blocks: list[str] = []
    for match in re.finditer(
        r"(?m)^\s*(?:\(\d+\)|\([가-힣]\)|[가-힣]\.|\d+\.)\s*(?:소\s*결\s*론|소\s*결|결\s*론)\b[^\n]*$",
        text,
    ):
        rest = text[match.end():]
        stop = re.search(_ANY_HEADING, rest)
        blocks.append(rest[: stop.start()] if stop else rest)
    return blocks


def _application_number(block: str) -> str:
    """'제40-2021-4125호'(일련번호 0 채움 안 됨)·'40-2020-0012345'·13자리 형태를 13자리로."""
    match = re.search(r"(4[015])\s*-\s*(\d{4})\s*-\s*(\d{1,7})\s*호", block)
    if match:
        return f"{match.group(1)}{match.group(2)}{int(match.group(3)):07d}"
    match = re.search(r"(?:출원번호|제)\s*(4[015]\d{11})", block)
    return match.group(1) if match else ""


def _refusal_ground_block(text: str) -> str:
    return _find_block(
        text,
        r"(?:거절결정\s*(?:의\s*)?이유|원결정\s*(?:의\s*)?이유|거절이유)",
        (r"(?m)^\s*(?:\d+\.|[가-힣]\.)\s*\S",),
    )


def _decision_result(order: str) -> str:
    if re.search(r"무효로\s*한다", order):
        return "무효"
    if re.search(r"각하", order):
        return "각하"
    if re.search(r"기각", order):
        return "기각"
    if re.search(r"(원결정|결정)을?\s*취소", order):
        return "취소"
    if re.search(r"속하지\s*(아니|않)", order):
        return "불속"
    if re.search(r"권리범위에\s*속한다", order):
        return "속함"
    return "미판독"


def analyze_text(text: str) -> dict:
    """심결문 텍스트 → 정규식 추출 결과(prefilter.csv 한 행). 2013당419 구조를 기준으로 삼는다."""
    result: dict = {"텍스트길이": len(text), "추출실패": 1 if len(text.strip()) < 200 else 0}
    order = _find_block(
        text,
        r"(?m)^\s*주\s*문\s*$",
        (r"(?m)^\s*청\s*구\s*(?:의\s*)?취\s*지\s*$", r"(?m)^\s*이\s*유\s*$"),
    )
    result["주문"] = " ".join(order.split())[:200]
    result["주문결과"] = _decision_result(order)

    # "가. 이 사건 등록상표"(2013) / "가. 이사건출원상표"(2024, 공백 없음) → 다음 제목 앞까지
    subject = _find_block(
        text,
        r"(?m)^\s*[가-힣]\.\s*이\s*사건\s*(?:국제등록\s*출원|등록|출원|국제등록)?\s*(?:상표|서비스표)",
        (r"(?m)^\s*[나-힣]\.\s*\S", _TOP_HEADING),
    )
    kind_match = re.search(r"이\s*사건\s*(국제등록\s*출원|등록|출원|국제등록)?\s*상표", text)
    result["이사건_구분"] = (kind_match.group(1) or "") + "상표" if kind_match else ""
    reg = _REG_NUMBER_RE.search(subject)
    result["이사건_등록번호"] = _digits(reg.group(1)) if reg else ""
    result["이사건_출원번호"] = _application_number(subject)
    intl = re.search(r"국제등록번호[^\n]*?제\s*(\d{5,8})\s*호", subject)
    result["이사건_국제등록번호"] = intl.group(1) if intl else ""
    goods = re.search(
        r"지정상품\s*[:：]?\s*(.+?)(?=\n\s*\(\d+\)|\n\s*\([가-힣]\)|\n\s*[가-힣]\.|\Z)",
        subject, re.S,
    )
    result["이사건_지정상품"] = " ".join(goods.group(1).split())[:300] if goods else ""

    # 선등록상표 영역: 제목에 '선등록상표'가 든 첫 줄("나. 선등록상표 1", "나. 원결정이유및선등록
    # 상표", "(2) 선등록상표")부터 다음 최상위 번호 제목("2. 당사자의 주장" 등)까지.
    prior_region = _find_block(
        text,
        r"(?m)^\s*(?:\(\d+\)|[가-힣]\.|\d+\.)\s*[^\n]*?" + _PRIOR_MARK,
        (_TOP_HEADING,),
    )
    prior_numbers: list[str] = []
    for number in _REG_NUMBER_RE.findall(prior_region):
        digits = _digits(number)
        if digits and digits != result["이사건_등록번호"] and digits not in prior_numbers:
            prior_numbers.append(digits)
    result["선등록_등록번호"] = "|".join(prior_numbers)

    # 판단 절: "3. 판단"(2013) 또는 "3. 이사건출원상표가…해당하는지여부"(2024) → "N. 결론" 전까지
    judgment = _find_block(
        text,
        r"(?m)^\s*\d+\.\s*[^\n]*?(?:판\s*단|해당하는지\s*여부)[^\n]*$",
        (r"(?m)^\s*\d+\.\s*결\s*론\s*$",),
    )
    result["판단절"] = "|".join(
        " ".join(m.group(2).split())[:80] for m in _HEADING_RE.finditer(judgment)
    )

    body_articles: set[str] = set()
    for law, number in _ARTICLE_RE.findall(text):
        normalized = _norm_article(law, int(number))
        if normalized:
            body_articles.add(normalized)
    if _ARTICLE_33_RE.search(text):
        body_articles.add("33")
    for key in ("34-7", "34-9", "34-11", "34-12", "34-13", "33"):
        result[f"본문_{key.replace('-', '_')}"] = 1 if key in body_articles else 0
    for key, word in KEYWORDS.items():
        result[f"본문_{key}"] = 1 if re.search(word.replace(" ", r"\s*"), text) else 0
    without_boilerplate = _FAME_BOILERPLATE_RE.sub("", text)
    result["본문_저명주지_실질"] = 1 if re.search(r"저명|주지", without_boilerplate) else 0

    conclusions: dict[str, str] = {}
    blocks = _conclusion_blocks(text)
    # 폴백: '소결' 제목 없이 판단 절 마지막 문단에 결론이 오는 심결문(2024-01 실측 20건 중 6건)
    if judgment and not any(_CONCLUSION_RE.search(block) for block in blocks):
        blocks = blocks + [judgment[-600:]]
    for block in blocks:
        for match in _CONCLUSION_RE.finditer(block):
            law, number, extra, verb = match.groups()
            polarity = "부정" if re.search(r"(아니|않)", verb) else "긍정"
            if re.search(r"않게\s*되", block[match.end():match.end() + 12]):
                polarity = "부정"
            for raw in (number, extra):
                if raw:
                    key = _norm_article(law, int(raw))
                    if key and key not in conclusions:
                        conclusions[key] = polarity
        if re.search(r"(?:상표법\s*)?제\s*(?:33|6)\s*조", block) and "33" not in conclusions:
            lacks = re.search(r"식별력\s*(?:이\s*)?(?:없|부족)", block)
            conclusions["33"] = "부정" if lacks else "긍정"
    result["결론절추출"] = 1 if blocks else 0
    result["결론조문"] = "|".join(f"{k}:{v}" for k, v in conclusions.items())
    result["선등록소멸취소"] = 1 if (
        result["주문결과"] == "취소" and _PRIOR_MARK_GONE_RE.search(text)
    ) else 0

    ground = _refusal_ground_block(text)
    ground_articles = []
    for law, number in _ARTICLE_RE.findall(ground):
        key = _norm_article(law, int(number))
        if key and key not in ground_articles:
            ground_articles.append(key)
    if _ARTICLE_33_RE.search(ground) and "33" not in ground_articles:
        ground_articles.append("33")
    result["거절이유조문"] = "|".join(ground_articles)
    return result


PREFILTER_COLUMNS = [
    "심판번호", "텍스트길이", "추출실패", "주문", "주문결과", "이사건_구분", "이사건_등록번호",
    "이사건_출원번호", "이사건_지정상품", "선등록_등록번호", "판단절",
    "본문_34_7", "본문_34_9", "본문_34_11", "본문_34_12", "본문_34_13", "본문_33",
    "이사건_국제등록번호", "본문_저명", "본문_주지", "본문_부정한목적", "본문_식별력",
    "본문_저명주지_실질", "결론절추출", "결론조문", "거절이유조문", "선등록소멸취소",
]


def run_extract(args: argparse.Namespace, session: Session) -> int:
    paths_ = session.paths
    pdfs = sorted(paths_.pdf_dir.glob("*.pdf")) if paths_.pdf_dir.exists() else []
    paths_.text_dir.mkdir(parents=True, exist_ok=True)
    extracted = skipped = failed = 0
    for pdf in pdfs:
        dest = paths_.text_dir / f"{pdf.stem}.txt"
        if dest.exists() and not args.force:
            skipped += 1
            continue
        try:
            dest.write_text(extract_pdf_text(pdf), encoding="utf-8")
            extracted += 1
        except Exception as exc:  # 손상 PDF 등 — 한 건 때문에 전체를 멈추지 않는다
            failed += 1
            print(f"  [실패] {pdf.name}: {type(exc).__name__}")
    rows = []
    for text_file in sorted(paths_.text_dir.glob("*.txt")):
        analysis = analyze_text(text_file.read_text(encoding="utf-8"))
        rows.append({"심판번호": text_file.stem, **analysis})
    _write_csv(paths_.prefilter_csv, PREFILTER_COLUMNS, rows)
    print(f"## extract: PDF {len(pdfs)}건 → 텍스트 신규 {extracted}·기존 {skipped}·실패 {failed}, "
          f"prefilter {len(rows)}행 → {paths_.prefilter_csv}")
    return 0


# ====================================================================
# sheet — 자동 3등급·유사여부 추정 + 사람이 채우는 열
# ====================================================================

FAME_ARTICLES = ("34-9", "34-11", "34-12", "34-13")


def parse_conclusions(value: str) -> dict[str, str]:
    conclusions: dict[str, str] = {}
    for part in (value or "").split("|"):
        if ":" in part:
            key, polarity = part.split(":", 1)
            conclusions[key] = polarity
    return conclusions


def classify(analysis: dict, *, ignore_boilerplate: bool = False) -> tuple[str, str]:
    """(자동등급, 사유). 1=순수 유사 사례 후보, 2=검토 필요, 3=제외 후보.

    ignore_boilerplate=True 면 저명·주지 언급을 요부 판단기준 판례 문구를 뺀 뒤(본문_저명주지_실질)
    로 판단한다 — 규칙 변경 후보의 효과를 보는 참고 열(등급_보일러플레이트제외)용. 정식 등급은
    원 규칙이다.
    """
    conclusions = parse_conclusions(analysis.get("결론조문", ""))
    fame_in_conclusion = [k for k in FAME_ARTICLES if k in conclusions]
    fame_keys = (("본문_저명", "저명"), ("본문_주지", "주지"), ("본문_부정한목적", "부정한 목적"))
    fame_in_body = [name for key, name in fame_keys if str(analysis.get(key, "0")) == "1"]
    if ignore_boilerplate:
        fame_in_body = [n for n in fame_in_body if n == "부정한 목적"]
        if str(analysis.get("본문_저명주지_실질", "0")) == "1":
            fame_in_body.append("저명·주지(문구 제외 후)")
    if fame_in_conclusion:
        return "3", "결론에 인지도 조문 " + ",".join(fame_in_conclusion)
    if conclusions and all(key == "33" for key in conclusions):
        return "3", "식별력 사례(33조만)"
    if not conclusions:
        return "2", "결론 조문 추출 실패"
    if "34-7" in conclusions and not fame_in_body:
        return "1", "결론 7호, 인지도 언급 없음"
    if "34-7" in conclusions:
        return "2", "결론 7호이나 본문에 " + "·".join(fame_in_body)
    return "2", "결론 조문이 7호 아님(" + ",".join(conclusions) + ")"


def estimate_similarity(kind: str, analysis: dict) -> tuple[str, str]:
    """결론 7호일 때 유사여부 추정과 근거. 사람이 '유사여부_확정'에서 확정한다."""
    conclusions = parse_conclusions(analysis.get("결론조문", ""))
    polarity = conclusions.get("34-7")
    if polarity == "긍정":
        return "유사", "결론 7호 긍정"
    if polarity == "부정":
        return "비유사", "결론 7호 부정"
    if "34-7" not in conclusions:
        return "", ""
    result = analysis.get("주문결과", "")
    if kind == "refusal":
        mapping = {"기각": "유사", "취소": "비유사"}
    else:  # invalidation / scope: 인용 = 유사, 기각 = 비유사 (권리범위확인은 주문 문구 우선)
        mapping = {
            "무효": "유사", "취소": "유사", "속함": "유사", "기각": "비유사", "불속": "비유사",
        }
    guess = mapping.get(result, "")
    return guess, f"주문 {result}({kind})" if guess else ""


def build_sheet_rows(
    list_rows: list[dict], prefilter_rows: list[dict], kinds: dict[str, dict]
) -> list[dict]:
    analyses = {row["심판번호"]: row for row in prefilter_rows}
    sheet: list[dict] = []
    for row in list_rows:
        number = row["심판번호"]
        analysis = analyses.get(number)
        kind = kind_for_trial_desc(row.get("종류", ""), kinds)
        base = {
            "심판번호": number,
            "종류": row.get("종류", ""),
            "심판상태": row.get("심판상태", ""),
            "심결월": row.get("심결월", ""),
            "상표A_명칭": row.get("상표명칭", ""),
            "유사여부_확정": "", "판단축": "", "제외사유": "", "메모": "",
        }
        if analysis is None:
            sheet.append({
                **base,
                "상표A_번호": row.get("등록번호") or row.get("출원번호", ""),
                "상표B_번호": "", "지정상품_원문": "", "조문플래그": "", "결론조문": "",
                "자동등급": "", "등급사유": "텍스트 미추출", "등급_보일러플레이트제외": "",
                "참고표시": "", "유사여부_추정": "", "추정근거": "",
            })
            continue
        grade, reason = classify(analysis)
        variant_grade, _ = classify(analysis, ignore_boilerplate=True)
        guess, basis = estimate_similarity(kind, analysis)
        notes = []
        if analysis.get("주문결과") == "각하":
            notes.append("각하(본안 판단 없음)")
        if str(analysis.get("선등록소멸취소", "0")) == "1":
            notes.append("선등록상표 소멸로 취소(유사 판단 없음)")
        if analysis.get("이사건_국제등록번호"):
            notes.append("국제등록출원")
        flags = [key.replace("본문_", "").replace("_", "-") for key in analysis
                 if key.startswith("본문_") and str(analysis[key]) == "1"]
        subject_number = (analysis.get("이사건_등록번호") or row.get("등록번호")
                          or analysis.get("이사건_출원번호") or row.get("출원번호", ""))
        prior = [p for p in (analysis.get("선등록_등록번호") or "").split("|") if p] or [""]
        for prior_number in prior:  # 선등록상표가 여러 건이면 행을 나눈다
            sheet.append({
                **base,
                "상표A_번호": subject_number,
                "상표B_번호": prior_number,
                "지정상품_원문": analysis.get("이사건_지정상품", ""),
                "조문플래그": ",".join(flags),
                "결론조문": analysis.get("결론조문", ""),
                "자동등급": grade,
                "등급사유": reason,
                "등급_보일러플레이트제외": variant_grade,
                "참고표시": "; ".join(notes),
                "유사여부_추정": guess,
                "추정근거": basis,
            })
    return sheet


def run_sheet(args: argparse.Namespace, session: Session) -> int:
    paths_ = session.paths
    list_rows = _read_csv(paths_.list_csv)
    prefilter_rows = _read_csv(paths_.prefilter_csv)
    rows = build_sheet_rows(list_rows, prefilter_rows, load_kinds(args.kinds_config))
    _write_csv(paths_.labels_csv, LABEL_COLUMNS, rows)
    grades = {g: sum(1 for r in rows if r["자동등급"] == g) for g in ("1", "2", "3", "")}
    print(f"## sheet: {len(rows)}행 → {paths_.labels_csv} "
          f"(1등급 {grades['1']}, 2등급 {grades['2']}, 3등급 {grades['3']}, 미추출 {grades['']})")
    return 0


# ====================================================================
# biblio — 서지상세 1회/건 (결과 판독의 대안 평가: conclusiveResultCode·trialDecision vs PDF 주문)
# ====================================================================

BIBLIO_KEY_FIELDS = (
    "trialNumber", "cdDesc", "trialStatusCode", "conclusiveResultCode", "conclusiveStatusCode",
    "conclusiveDate", "trialDecisionCode", "trialDecision", "trialDecisionDate", "eventindication",
    "applicationNumber", "registerNumber", "rightDivisionCode", "inventionTitle", "path",
)


def parse_biblio_response(xml_text: str) -> dict:
    """서지상세 응답 → bibliographicSummaryInfo 의 모든 자식 + 지정분류코드(clssCd) 목록."""
    kc.check_result_code(xml_text)
    root = ET.fromstring(xml_text)
    summary = kc._find_first(root, "bibliographicSummaryInfo")
    result: dict = {}
    if summary is not None:
        for child in summary:
            result[kc._local_name(child.tag)] = " ".join((child.text or "").split())
    result["clssCd"] = [
        (el.text or "").strip() for el in root.iter() if kc._local_name(el.tag) == "clssCd"
    ]
    return result


def run_biblio(args: argparse.Namespace, session: Session) -> int:
    trials = list(dict.fromkeys(args.trial or []))
    prefilter = {row["심판번호"]: row for row in _read_csv(session.paths.prefilter_csv)}
    print(f"## biblio {len(trials)}건 → 호출 {len(trials)}회 "
          f"(GET {BIBLIO_URL} 인증 {BIBLIO_AUTH_PARAM})")
    print(f"- 예산: {session.budget_line()}")
    if session.dry_run:
        print("[dry-run] 실호출 0회 — 위 계획만 출력하고 종료합니다.")
        return 0
    session.paths.biblio_dir.mkdir(parents=True, exist_ok=True)
    exit_code = 0
    try:
        for number in trials:
            xml_text = session.api_get(BIBLIO_URL, {"trialNumber": number}, BIBLIO_AUTH_PARAM)
            _save_raw(session.paths, f"biblio_{number}.xml", xml_text)
            parsed = parse_biblio_response(xml_text)
            (session.paths.biblio_dir / f"{number}.json").write_text(
                json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            shown = {k: parsed.get(k, "") for k in BIBLIO_KEY_FIELDS if k != "path"}
            print(f"  {number}: {json.dumps(shown, ensure_ascii=False)}")
            row = prefilter.get(number)
            if row:
                print(f"    ↔ PDF 주문결과={row.get('주문결과')} 주문={row.get('주문', '')[:60]}")
    except HardCapReached as exc:
        print(f"[중단] {exc}")
        exit_code = 3
    print(f"- 호출 {session.api_calls}회 → {session.paths.biblio_dir}")
    return exit_code


# ====================================================================
# status
# ====================================================================

def summarize_calls(log_path: Path) -> dict[str, int]:
    """calls.log 를 오퍼레이션별로 센다(list/doc/biblio/download)."""
    counts = {"list": 0, "doc": 0, "biblio": 0, "download": 0, "기타": 0}
    if not log_path.exists():
        return counts
    for line in log_path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        what, note = (parts[1], parts[2]) if len(parts) >= 3 else ("", "")
        if what == "download":
            counts["download"] += 1
        elif note.startswith("getAdvancedSearch"):
            counts["list"] += 1
        elif note.startswith("getJudDocumentInfoSearch"):
            counts["doc"] += 1
        elif note.startswith("getBibliographyDetailInfoSearch"):
            counts["biblio"] += 1
        else:
            counts["기타"] += 1
    return counts


def run_status(args: argparse.Namespace, session: Session) -> int:
    paths_ = session.paths
    calls = summarize_calls(paths_.calls_log)
    print(f"- calls.log: list {calls['list']} · 심결문 {calls['doc']} · 서지 {calls['biblio']} · "
          f"다운로드 {calls['download']} · 기타 {calls['기타']} (합계 {sum(calls.values())})")
    list_rows = _read_csv(paths_.list_csv)
    pdfs = len(list(paths_.pdf_dir.glob("*.pdf"))) if paths_.pdf_dir.exists() else 0
    texts = len(list(paths_.text_dir.glob("*.txt"))) if paths_.text_dir.exists() else 0
    print(f"## status ({paths_.base})")
    print(f"- 예산: {session.budget_line()}")
    prefilter_count = len(_read_csv(paths_.prefilter_csv))
    labels_count = len(_read_csv(paths_.labels_csv))
    print(f"- list.csv {len(list_rows)}건 · PDF {pdfs}건 · 텍스트 {texts}건 · "
          f"prefilter {prefilter_count}행 · labels {labels_count}행")
    progress = load_progress(paths_.list_progress)
    for kind, months in progress.items():
        done = sum(1 for m in months.values() if m.get("done"))
        print(f"- list 진행 {kind}: {done}/{len(months)}개월 완료")
    if paths_.calls_log.exists():
        tail = paths_.calls_log.read_text(encoding="utf-8").splitlines()[-5:]
        print("- 최근 호출: " + (" / ".join(tail) if tail else "없음"))
    return 0


# ====================================================================
# main
# ====================================================================

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="상표 심결례 수집 파이프라인 (다빈-1, KIPRIS 심판사항 API)"
    )
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_PATHS.base,
                    help=f"산출물 디렉터리(기본 {DEFAULT_PATHS.base})")
    ap.add_argument("--kinds-config", type=Path, default=KINDS_CONFIG_PATH,
                    help="심판종류(trialDesc) 설정 파일")
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--dry-run", action="store_true", help="네트워크 호출 0회, 계획·예산만 출력")
        p.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                       help=f"이번 실행 호출 하드캡(기본 {DEFAULT_MAX_CALLS})")

    p_list = sub.add_parser("list", help="월별 항목별검색 → list.csv")
    common(p_list)
    p_list.add_argument("--kind", default="",
                        help="refusal | invalidation | scope (trials_kinds.json). 생략 = 필터 없음")
    p_list.add_argument("--from", required=True, metavar="YYYYMM")
    p_list.add_argument("--to", required=True, metavar="YYYYMM")
    p_list.add_argument("--rows", type=int, default=DEFAULT_ROWS, help="numOfRows(최댓값 미확인)")
    p_list.add_argument("--max-pages", type=int, default=10, help="월당 페이지 하드캡")
    p_list.add_argument("--allow-unverified", action="store_true",
                        help="trialDesc 미검증 상태에서도 실호출 허용(검증용 1개월치 등)")

    p_fetch = sub.add_parser("fetch", help="심결문 경로 조회 + PDF 즉시 다운로드")
    common(p_fetch)
    p_fetch.add_argument("--limit", type=int, default=0, help="이번 실행 최대 건수(0=전부)")
    p_fetch.add_argument(
        "--skip-no-doc",
        action="store_true",
        help="목록의 심결문유무(trialDecisionDoc)가 N 인 건 건너뜀(의미 미확인, 기본 끔)",
    )
    p_fetch.add_argument("--retry-failed", action="store_true", help="fetch_log 의 실패 건 재시도")
    p_fetch.add_argument("--trial", action="append", metavar="심판번호",
                         help="이 심판번호만 대상(반복 지정)")
    p_fetch.add_argument("--kind-priority", default="",
                         help="종류 우선순위, 예: refusal,scope,invalidation")
    p_fetch.add_argument("--prefer-doc", action="store_true", help="심결문유무 Y 인 건을 먼저")

    p_extract = sub.add_parser("extract", help="PDF → 텍스트 + prefilter.csv")
    common(p_extract)
    p_extract.add_argument("--force", action="store_true", help="이미 있는 텍스트도 다시 추출")

    p_sheet = sub.add_parser("sheet", help="labels.csv 초안")
    common(p_sheet)
    p_biblio = sub.add_parser("biblio", help="서지상세 조회(1회/건) — 결과·주문 대조용")
    common(p_biblio)
    p_biblio.add_argument("--trial", action="append", required=True, metavar="심판번호")
    sub.add_parser("status", help="예산·진행 요약")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    session = Session(
        paths=TrialPaths(args.data_dir),
        max_calls=getattr(args, "max_calls", DEFAULT_MAX_CALLS),
        dry_run=getattr(args, "dry_run", False),
    )
    runners = {"list": run_list, "fetch": run_fetch, "extract": run_extract,
               "sheet": run_sheet, "biblio": run_biblio, "status": run_status}
    try:
        return runners[args.command](args, session)
    except kc.CallBudgetExceeded as exc:
        print(f"[중단] 예산 초과: {exc}", file=sys.stderr)
        return 4
    except kc.KiprisError as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
