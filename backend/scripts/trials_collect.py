"""
다빈-1: 상표 심결례(정답 데이터) 수집 파이프라인 1단계 — KIPRIS Plus 심판사항 API.

    list     월별 항목별검색(getAdvancedSearch)으로 상표 심판 목록 → ml/data/trials/list.csv
    fetch    심판(결)문(getJudDocumentInfoSearch) 경로 조회 → 즉시 PDF 다운로드 → pdf/{심판번호}.pdf
    extract  PyMuPDF 텍스트 추출 + 정규식 선별 → text/{심판번호}.txt, prefilter.csv
    sheet    사람 라벨링용 시트 초안 → labels.csv (재생성 때 사람 열 보존)
    show     심판번호의 주문·판단 절·자동 판정 보기 (--next: curation_queue.csv 의 다음 미확정 건,
             --batch n: 라벨 없는 다음 n건을 batch_<k>.md 로 — 정규식 추정은 넣지 않는다)
    label    큐레이션 라벨 기록 (유사|비유사|제외, --source llm|human, --evidence, --confidence,
             --pass a|b). llm 은 사람이 확인한 행(확인여부=Y)을 덮어쓰지 못한다
    confirm  LLM 라벨을 그대로 승인 (확인여부=Y, 라벨출처=human-confirmed)
    review   재검토 큐 review_queue.csv (LLM≠추정 · 확신도 low · 메모 애매 · pass A≠B)
    sample   --n 40 --seed 0: 미확인 LLM 라벨에서 종류×판정 층화 표본 → verify_queue.csv
    status   예산(quota.json)·건수·단계별 진행·큐레이션 진행률 요약
    sample   층화 표본 CSV (호출 없음) · biblio 서지상세 (1회/건)

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
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
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
# 40 상표 · 41 서비스표 · 45 상표서비스표 · 70 국제상표(마드리드). 44(지리적표시 단체표장)는 제외.
TRADEMARK_NUMBER_PREFIXES: tuple[str, ...] = ("40", "41", "45", "70")
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
    def list_all_csv(self) -> Path:
        return self.base / "list_all.csv"

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

    @property
    def curation_queue(self) -> Path:
        return self.base / "curation_queue.csv"

    @property
    def review_queue(self) -> Path:
        return self.base / "review_queue.csv"

    @property
    def verify_queue(self) -> Path:
        return self.base / "verify_queue.csv"


DEFAULT_PATHS = TrialPaths(paths.ML_DATA_DIR / "trials")

LIST_COLUMNS = [
    "심판번호", "종류", "심결월", "심판상태", "상표명칭", "출원번호", "등록번호",
    "청구인", "피청구인", "심결문유무", "원본JSON",
]
FETCH_LOG_COLUMNS = ["심판번호", "결과", "파일명", "kind", "일시"]
# 사람이 채우는 열(sheet 재생성 때 심판번호·상표B_번호 기준으로 보존). 판단축 은 4단계 전 이름.
HUMAN_COLUMNS = ("유사여부_확정", "판단축_확정", "상표유형_확정", "제외사유", "메모")
LEGACY_HUMAN_COLUMNS = {"판단축": "판단축_확정"}
# label 명령의 메타 열: 출처(llm/human/human-confirmed), 소결 문장 원문, 확신도(high/low),
# 사람 확인(Y), 사람이 수정하기 전 LLM 판정(LLM↔사람 일치율용). pass b(이중 라벨링)는 llm_b_* 열.
LABEL_META_COLUMNS = ("라벨출처", "근거문장", "확신도", "확인여부", "llm_판정_원본")
LLM_B_COLUMNS = ("llm_b_유사여부", "llm_b_판단축", "llm_b_제외사유", "llm_b_확신도", "llm_b_근거")
# 보강 열(backend/scripts/trials_enrich.py): 상대 표장 번호 정규화·명칭(본문/OCR/KIPRIS)·양쪽
# 지정상품 유사군·X4 자카드. sheet 재생성 때 사람 열과 같이 보존된다.
ENRICH_COLUMNS = (
    "상대표장_번호_정규화", "상대표장_명칭_본문", "상대표장_명칭_ocr", "상대표장_명칭_kipris",
    "goods_codes_this", "goods_codes_prior", "x4_goods",
)
PRESERVED_COLUMNS = HUMAN_COLUMNS + LABEL_META_COLUMNS + LLM_B_COLUMNS + ENRICH_COLUMNS
LABEL_COLUMNS = [
    "심판번호", "종류", "심판상태", "심결월", "상표A_번호", "상표A_명칭", "상표B_번호",
    "상대표장_번호_후보", "상대표장_유형", "지정상품_원문", "조문플래그", "결론조문", "신뢰도",
    "표장유사_소결", "자동등급", "등급사유", "등급_원규칙", "family", "참고표시", "유사여부_추정",
    "추정근거", "결정축_추정", "상표유형_추정", *PRESERVED_COLUMNS,
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


# 일시적 네트워크 오류(연결 끊김 등)는 잠시 기다렸다가 재시도한다. 각 시도는 호출로 센다.
# 2026-09-30 실측: 129개월 목록 호출 중 58번째에서 1회 통신 실패 → 재시도 없이는 배치가 멈춘다.
NETWORK_RETRIES = 2
NETWORK_BACKOFF_SEC = 3.0


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


def api_get_with_retry(session: "Session", url: str, params: dict, auth_param: str) -> str:
    for attempt in range(NETWORK_RETRIES + 1):
        try:
            return session.api_get(url, params, auth_param)
        except kc.KiprisNetworkError as exc:
            if attempt >= NETWORK_RETRIES:
                raise
            wait = NETWORK_BACKOFF_SEC * (attempt + 1)
            print(f"  [재시도 {attempt + 1}/{NETWORK_RETRIES}] {exc} — {wait:.0f}s 뒤")
            time.sleep(wait)
    raise AssertionError("unreachable")


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
    all_kinds = bool(getattr(args, "all_kinds", False))
    spec = kinds[kind] if kind else None
    trial_descs = trial_desc_values(spec) if spec else [""]  # "" = 종류 필터 없음
    trial_desc = trial_descs[0]
    verified = bool(spec.get("verified")) if spec else True  # 필터 없음 = 검증할 값 없음
    progress_key = kind or ("all_kinds" if all_kinds else "all")
    raw_prefix = kind or "all"  # 원본 파일명은 필터 없는 호출끼리 공유(재사용)
    output_csv = session.paths.list_all_csv if all_kinds else session.paths.list_csv
    months = month_range(getattr(args, "from"), args.to)
    progress = load_progress(session.paths.list_progress)
    done = progress.get(progress_key, {})
    pending = [m for m in months if not done.get(m, {}).get("done")]
    rows_per_page = args.rows

    label = "종류 필터 없음" + (" → list_all.csv(전 종류 보관)" if all_kinds else "")
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

    existing = {row["심판번호"] for row in _read_csv(output_csv)}
    added = excluded = reused = 0
    exit_code = 0
    for month in pending:
        page, total = 1, None
        pages_done = 0
        try:
            for index, desc in enumerate(trial_descs):
                suffix = f"_d{index}" if len(trial_descs) > 1 else ""
                page = 1
                while True:
                    raw_name = f"list_{raw_prefix}_{month}{suffix}_p{page}.xml"
                    raw_path = session.paths.raw_xml_dir / raw_name
                    if raw_path.exists():  # 저장된 원본 재사용 — 호출하지 않는다
                        xml_text = raw_path.read_text(encoding="utf-8")
                        reused += 1
                    else:
                        params = build_search_params(desc, month, page, rows_per_page)
                        xml_text = api_get_with_retry(
                            session, SEARCH_URL, params, SEARCH_AUTH_PARAM
                        )
                        _save_raw(session.paths, raw_name, xml_text)
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
                    _append_csv(output_csv, LIST_COLUMNS, rows)
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
    print(f"- 결과: 신규 {added}건 추가(앞자리 필터 제외 {excluded}건), "
          f"호출 {session.api_calls}회, 원본 재사용 {reused}쪽 → {output_csv}")
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


def parse_kind_caps(value: str) -> dict[str, int]:
    """--kind-cap "scope=280,invalidation=100,refusal=70" → {kind: 상한}. 형식 오류는 ValueError."""
    caps: dict[str, int] = {}
    for part in (value or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"--kind-cap 형식은 kind=건수 입니다: {part!r}")
        kind, raw = part.split("=", 1)
        try:
            caps[kind.strip()] = int(raw)
        except ValueError:
            raise ValueError(f"--kind-cap 건수가 정수가 아닙니다: {part!r}") from None
        if caps[kind.strip()] < 0:
            raise ValueError(f"--kind-cap 건수는 0 이상이어야 합니다: {part!r}")
    return caps


def row_kind(row: dict, kinds: dict[str, dict]) -> str:
    """표본·큐 CSV 의 kind 열이 있으면 그 값, 없으면 종류(trialDesc)로 역매핑."""
    return (row.get("kind") or "").strip() or kind_for_trial_desc(row.get("종류", ""), kinds)


def select_fetch_targets(
    pending: list[dict],
    limit: int,
    kind_priority: list[str],
    prefer_doc: bool,
    trials: set[str],
    kinds: dict[str, dict],
    kind_caps: dict[str, int] | None = None,
) -> list[dict]:
    """대상 선정: --trial 지정 건만 / 종류 우선순위 / 심결문유무 Y 우선 / 종류별 상한 / 건수."""
    if trials:
        pending = [row for row in pending if row["심판번호"] in trials]

    def sort_key(row: dict) -> tuple[int, int]:
        kind = row_kind(row, kinds)
        rank = kind_priority.index(kind) if kind in kind_priority else len(kind_priority)
        has_doc = 0 if row.get("심결문유무", "").upper() == "Y" else 1
        return (rank if kind_priority else 0, has_doc if prefer_doc else 0)

    ordered = sorted(pending, key=sort_key) if (kind_priority or prefer_doc) else list(pending)
    if kind_caps:
        taken: dict[str, int] = {}
        capped: list[dict] = []
        for row in ordered:
            kind = row_kind(row, kinds)
            if kind in kind_caps and taken.get(kind, 0) >= kind_caps[kind]:
                continue
            taken[kind] = taken.get(kind, 0) + 1
            capped.append(row)
        ordered = capped
    return ordered[:limit] if limit else ordered


def queued_fetch_rows(paths_: TrialPaths, queue_path: Path, *, retry_failed: bool) -> list[dict]:
    """--queue CSV(심판번호 열 필수) 순서대로, 이미 받은 PDF·실패 기록은 건너뛴다."""
    failed = {r["심판번호"] for r in _read_csv(paths_.fetch_log) if r.get("결과") != "ok"}
    pending = []
    for row in _read_csv(queue_path):
        number = row.get("심판번호", "").strip()
        if not number or (paths_.pdf_dir / f"{number}.pdf").exists():
            continue
        if number in failed and not retry_failed:
            continue
        pending.append(row)
    return pending


# 오류 응답(resultCode≠00·네트워크·프로토콜)이 연속으로 이만큼 오면 중단한다 — 한도 초과 등
# 상태성 오류에서 호출만 낭비하는 것을 막는다. 예산 초과(CallBudgetExceeded)는 즉시 중단(exit 4).
MAX_CONSECUTIVE_ERRORS = 5


def run_fetch(args: argparse.Namespace, session: Session) -> int:
    queue = getattr(args, "queue", None)
    if queue:
        pending = queued_fetch_rows(session.paths, Path(queue), retry_failed=args.retry_failed)
    else:
        pending = pending_fetch_rows(
            session.paths, skip_no_doc=args.skip_no_doc, retry_failed=args.retry_failed
        )
    raw_priority = getattr(args, "kind_priority", "") or ""
    priority = [k.strip() for k in raw_priority.split(",") if k.strip()]
    kinds = load_kinds(getattr(args, "kinds_config", KINDS_CONFIG_PATH))
    caps = parse_kind_caps(getattr(args, "kind_cap", "") or "")
    targets = select_fetch_targets(
        pending, args.limit, priority, bool(getattr(args, "prefer_doc", False)),
        set(getattr(args, "trial", None) or []), kinds, caps,
    )
    per_item = 2 if COUNT_DOWNLOADS else 1
    listed = len(_read_csv(Path(queue))) if queue else len(_read_csv(session.paths.list_csv))
    print(f"## fetch ({'queue ' + str(queue) if queue else 'list.csv'} {listed}건, "
          f"PDF 미수신 {len(pending)}건)")
    by_kind: dict[str, int] = {}
    for row in targets:
        kind = row_kind(row, kinds) or "?"
        by_kind[kind] = by_kind.get(kind, 0) + 1
    planned = len(targets) * per_item
    print(f"- 이번 대상 {len(targets)}건(--limit {args.limit or '없음'}"
          f"{', --kind-cap ' + ','.join(f'{k}={v}' for k, v in caps.items()) if caps else ''}) → "
          f"호출 {len(targets)}회 + 다운로드 {len(targets)}회 = 카운트 {planned}회")
    print("- 종류별 계획: " + (" · ".join(
        f"{kind} {count}건(호출 {count * per_item})" for kind, count in sorted(by_kind.items())
    ) or "없음") + f" → 예상 호출 {planned}회 / 하드캡 {session.max_calls}회")
    if planned > session.max_calls:
        print(f"- 주의: 예상 호출 {planned}회 > --max-calls {session.max_calls}회 — "
              "하드캡에서 중단된다. --kind-cap·--limit 으로 줄이는 것을 권장")
    print(f"- 요청: GET {DOC_URL} 인증 {DOC_AUTH_PARAM} · 키 {'있음' if access_key() else '없음'}")
    print(f"- 예산: {session.budget_line()}")
    if session.dry_run:
        print("[dry-run] 실호출 0회 — 위 계획만 출력하고 종료합니다.")
        return 0

    done = errors = consecutive = 0
    log_rows: list[dict] = []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    exit_code = 0
    try:
        for row in targets:
            number = row["심판번호"]
            try:
                xml_text = api_get_with_retry(
                    session, DOC_URL, {"trialNumber": number}, DOC_AUTH_PARAM
                )
                _save_raw(session.paths, f"doc_{number}.xml", xml_text)
                doc = parse_doc_response(xml_text)
                if doc["openYN"].upper() != "Y" or not doc["path"]:
                    result = "not_open" if doc["path"] else "no_path"
                    log_rows.append({"심판번호": number, "결과": result, "파일명": doc["fileName"],
                                     "kind": doc["kind"], "일시": stamp})
                    consecutive = 0
                    continue
                dest = session.paths.pdf_dir / f"{number}.pdf"
                session.download(doc["path"], dest)  # 일회성 링크 → 응답 직후 바로 받는다
            except kc.CallBudgetExceeded:
                raise
            except kc.KiprisError as exc:  # resultCode 오류(한도 초과 포함)·네트워크·프로토콜
                errors += 1
                consecutive += 1
                code = getattr(exc, "result_code", None)
                log_rows.append({"심판번호": number, "결과": "error",
                                 "파일명": f"{type(exc).__name__}{'/' + code if code else ''}",
                                 "kind": "", "일시": stamp})
                print(f"  [오류 {consecutive}/{MAX_CONSECUTIVE_ERRORS}] {number}: {exc}")
                if consecutive >= MAX_CONSECUTIVE_ERRORS:
                    print(f"[중단] 오류 응답 연속 {MAX_CONSECUTIVE_ERRORS}회 — "
                          "한도 초과·장애 가능성. 원인 확인 뒤 --retry-failed 로 재개")
                    exit_code = 5
                    break
                continue
            consecutive = 0
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
    print(f"- 결과: PDF {done}건 저장, 오류 {errors}건, 호출 {session.api_calls}회·"
          f"다운로드 {session.downloads}회 → {session.paths.pdf_dir}")
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
    r"(?:소멸|말소|무효\s*심결|무효로\s*(?:되|확정)|존속기간\s*만료|포기|취소한다는\s*심결|등록을\s*취소하는\s*심결"
    r"|선원의\s*지위를?\s*(?:소급적으로\s*)?상실)[\s\S]{0,160}?"
    r"(?:더\s*이상|않게\s*되|해당하지|해당되지|해소)"
)
# 등록번호 표기: 상표등록 제N호 / 서비스표등록 제N호 / 국제상표(등록) 제N호 / 국제등록 제N호
_REG_NUMBER_RE = re.compile(
    r"(?:(?:상표|서비스표|국제상표|국제)\s*등록\s*제\s*([\d\-]+)\s*호"
    r"|국제\s*상표\s*제?\s*(\d{6,8}))"
)
# 각주("1) …")와 쪽 표시("3/9") — 각주 본문이 소결 문단 안에 끼어 들어오는 것을 막는다(2024-01 실측)
_FOOTNOTE_START_RE = re.compile(r"^\s*\d{1,2}\)\s*\S")
# 쪽 표시 "3/9"·구 레이아웃 "- 3 -", 쪽 머리말 분류코드 "(T)111.000-Z(09) 270"
_PAGE_MARK_RE = re.compile(r"^\s*(?:\d{1,3}/\d{1,3}|-\s*\d{1,3}\s*-)\s*$")
_HEADER_CODE_RE = re.compile(r"^\s*\(T\)\s*\d{3}[^\n]*$")


def _registration_numbers(block: str) -> list[str]:
    numbers: list[str] = []
    for first, second in _REG_NUMBER_RE.findall(block):
        digits = _digits(first or second)
        if digits and digits not in numbers:
            numbers.append(digits)
    return numbers


def _strip_footnotes(text: str) -> str:
    """각주 표시 줄부터 다음 쪽 표시·제목 줄 앞까지 제거한다."""
    kept: list[str] = []
    skipping = False
    for line in text.splitlines():
        if _FOOTNOTE_START_RE.match(line):
            skipping = True
            continue
        if skipping and (_PAGE_MARK_RE.match(line) or re.match(_ANY_HEADING, line)):
            skipping = False
        if _PAGE_MARK_RE.match(line) or _HEADER_CODE_RE.match(line):
            continue  # "3/9"·"- 3 -"·"(T)111.000-Z(09) 270" — 문장 가운데 끼면 조문 정규식이 끊긴다
        if not skipping:
            kept.append(line)
    return "\n".join(kept)
_HEADING_RE = re.compile(r"^\s*([가-힣]\.)\s*(.+?)\s*$", re.MULTILINE)
# 번호 제목. "2. 1. 19./2022. 1. 3." 처럼 줄바꿈된 날짜는 제목이 아니다(번호 뒤에 숫자가 오면 제외)
_TOP_HEADING = r"(?m)^\s*\d+\.\s*(?!\d)\S"
_ANY_HEADING = r"(?m)^\s*(?:\(\d+\)|\([가-힣]\)|[가-힣]\.|\d+\.(?!\s*\d))\s*\S"
_PRIOR_MARK = (
    r"(?:(?:선등록|선사용|선출원|비교대상|인용)\s*(?:\(\s*사용\s*\)\s*)?(?:상표|서비스표|표장)"
    r"|확인대상\s*표장)"
)
# 요부 판단기준의 판례 문구("…주지ㆍ저명하거나 일반수요자에게 강한 인상을…") — 인지도 사례가
# 아니어도 거의 모든 7호 심결문에 등장한다. 본문_저명주지_실질 은 이 문구를 뺀 뒤의 언급 여부.
# 요부 판단기준 "주지ㆍ저명하거나", 상표적 사용 판단기준 "등록상표의 주지저명성 그리고 사용자의
# 의도", 동일성 판단기준 "표장의 주지 정도 및 당해 상품과의 관계"(권리범위확인) — 전부 판례 문구
_FAME_BOILERPLATE_RE = re.compile(
    r"주지\s*[ㆍ·․,]?\s*저\s*명\s*하\s*거나|주지\s*저\s*명\s*성\s*(?:그\s*리\s*고|및|과|,)"
    r"|표장의\s*주지\s*정도\s*및|주지\s*[ㆍ·․,]\s*저\s*명의\s*상\s*표로"
)
# "영향을 주지 않는" 의 '주지'는 周知가 아니다
_FAME_WORD_RE = re.compile(r"저명|주지(?!\s*(?:않|아니|말|못))")
_SECTION_TITLES = ("소결론", "소결", "결론", "판단")
KEYWORDS = {"저명": "저명", "주지": "주지", "부정한목적": "부정한 목적", "식별력": "식별력"}


def _norm_article(law: str, number: int) -> str | None:
    if law in ("8", "35"):  # 선출원 저촉: 구법 8조1항 = 현행 35조1항
        return "35-1"
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


def _conclusion_blocks(text: str, *, final: bool = True) -> list[str]:
    """'소결'·'소결론'·'결론' 제목의 절 본문 — 실제 적용 조문은 여기서 읽는다.

    제목 표시는 (1)·(가)·가.·1. 네 가지를 모두 받는다(2024년 심결문은 "(다) 소결", "다. 소결론").
    final=False 면 '소결'·'소결론' 제목만(유사 판단·권리범위 근거는 여기서 읽는다).
    """
    blocks: list[str] = []
    titles = r"소\s*결\s*론|소\s*결" + (r"|결\s*론" if final else "")
    for match in re.finditer(
        r"(?m)^\s*(?:\(\d+\)|\([가-힣]\)|[가-힣]\.|\d+\.(?!\s*\d))\s*(?:" + titles + r")\b[^\n]*$",
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
    """주문 문장 → 무효/일부무효/각하/불속/속함/기각/취소/미판독. 속함·불속은 기각보다 먼저 본다."""
    if re.search(r"무효로\s*(?:한다|하고)", order):
        return "일부무효" if re.search(r"나머지[^.]{0,30}?기각", order) else "무효"
    if re.search(r"각하", order):
        return "각하"
    if re.search(r"속하지\s*(?:아니|않)", order):
        return "불속"
    if re.search(r"권리범위에\s*속한다", order):
        return "속함"
    if re.search(r"기각", order):
        return "기각"
    if re.search(r"(?:원\s*결정|결정)을?\s*(?:취소|파기)", order):
        return "취소"
    return "미판독"


# 주문 블록의 끝: 청구취지·이유 제목, 기초사실 제목, 쪽 머리말 분류코드 "(T)111.000-Z(09)", 쪽 번호,
# 서명란. PyMuPDF 가 쪽 요소 순서를 바꾸면 주문 제목 뒤에 기초사실이 따라오므로 거기서 끊는다
# (2023당403: 피청구인 답변의 "기각"을 주문으로 읽던 문제).
_ORDER_END_PATTERNS = (
    r"(?m)^\s*청\s*구\s*(?:의\s*)?취\s*지\s*$",
    r"(?m)^\s*이\s*유\s*$",
    r"(?m)^\s*\d+\.\s*기\s*초\s*사\s*실",
    r"(?m)^\s*[가-힣]\.\s*이\s*사건",
    r"(?m)^\s*심\s*판\s*장\s*$",
)
_PAGE_NOISE_RE = re.compile(r"\(T\)\s*\d{3}|^\s*(?:-\s*\d{1,3}\s*-|\d{1,3}/\d{1,3})\s*$", re.M)
# 주문 문장 자체(번호 유무 무관) — 제목 뒤 블록이 비면 본문 순서에서 찾는다(청구취지보다 앞에 온다)
_ORDER_SENTENCE_RE = re.compile(
    r"(?m)^[^\n]*?(?:심판\s*청구를\s*(?:모두\s*)?(?:기각|각하)|청구(?:를|는)\s*(?:모두\s*)?(?:기각|각하)한다"
    r"|권리범위에\s*속(?:한다|하지)|등록을\s*무효로\s*(?:한다|하고)|(?:원\s*)?결정을\s*(?:취소|파기))[^\n]*$"
)


def _final_section_hint(text: str) -> str:
    """'N. 결론' 절의 "이유 있으므로"(인용) / "이유 없으므로"(기각) — 주문 폴백의 대조용."""
    match = re.search(r"(?m)^\s*\d+\.\s*결\s*론\s*$", text)
    if not match:
        return ""
    final = " ".join(text[match.end(): match.end() + 400].split())
    if re.search(r"이유\s*(?:가\s*)?없", final):
        return "기각"
    if re.search(r"이유\s*(?:가\s*)?있", final):
        return "인용"
    return ""


def _order_block(text: str) -> str:
    """주문 제목 아래 블록. 쪽 머리말·쪽 번호가 주문 문장보다 먼저 오면(추출 순서가 뒤바뀐 문서)
    본문에서 주문 문장을 찾는다. 긴 지정상품 목록이 쪽을 넘기는 일부무효 주문은 그대로 둔다."""
    block = _find_block(text, r"(?m)^\s*주\s*문\s*$", _ORDER_END_PATTERNS)
    sentence = _ORDER_SENTENCE_RE.search(block)
    noise = _PAGE_NOISE_RE.search(block)
    if sentence and (noise is None or sentence.start() < noise.start()):
        return block
    heading = re.search(r"(?m)^\s*주\s*문\s*$", text)
    region = text[heading.end():] if heading else text
    candidates = list(_ORDER_SENTENCE_RE.finditer(region))[:4]
    if not candidates:
        return block
    hint = _final_section_hint(text)  # 주문과 청구취지가 뒤섞인 문서: 결론 절과 맞는 문장을 고른다
    found = candidates[0]
    for candidate in candidates:
        verdict = _decision_result(candidate.group(0))
        if (hint == "기각" and verdict in ("기각", "각하")) or (
            hint == "인용" and verdict not in ("기각", "각하", "미판독")
        ):
            found = candidate
            break
    picked = [region[found.start():found.end()]]
    for line in region[found.end():].splitlines()[1:4]:  # 이어지는 줄·"2. 심판비용은 …" 까지만
        if re.match(r"^\s*\d+\.\s*(?!\d)\S", line) or "심판비용" in line:
            picked.append(line)
        elif not picked[-1].rstrip().endswith(".") and not re.search(r"취\s*지|^\s*이\s*유", line):
            picked.append(line)  # 문장이 줄을 넘겼다
        else:
            break
    return "\n".join(picked)


# 판단 절: "3. 판단"·"3. 판 단"(2016)·"3. …해당하는지 여부"(2024)·"3. …유사여부"(2017)·
# "4. 확인대상표장이 … 권리범위에 속하는지 여부"(권리범위확인) → "N. 결론"·서명란·별지 앞까지
_JUDGMENT_KEYWORD_RE = re.compile(
    r"판\s*단|해당\s*(?:하는지|되는지|하는\s*것인지|되는\s*것인지)?\s*여부|유사\s*(?:한지\s*)?여부"
    r"|권리범위에\s*속하|당부|존부|가능\s*여부|무효\s*여부"
)
_JUDGMENT_END_PATTERNS = (
    r"(?m)^\s*\d+\.\s*결\s*론\s*$",
    r"(?m)^\s*심\s*판\s*장\s*$",
    r"(?m)^\s*\[?\s*별\s*지\s*(?:\]|\d|$)",
)


def _judgment_heading(text: str) -> re.Match | None:
    """판단 절의 최상위 제목 줄. 줄을 넘긴 제목("…제7호" / "에 해당하는지 여부")은 다음 줄도
    본다."""
    for match in re.finditer(_TOP_HEADING + r"[^\n]*", text):
        line = match.group(0)
        if re.search(r"결\s*론\s*$|기\s*초\s*사\s*실|주장|답변|이해관계|적법", line):
            continue
        after = text[match.end(): match.end() + 60]
        following = after.split("\n", 2)[1] if "\n" in after else ""
        if _JUDGMENT_KEYWORD_RE.search(line) or (
            not re.match(r"\s*(?:\(\d+\)|\([가-힣]\)|[가-힣]\.)", following)
            and _JUDGMENT_KEYWORD_RE.search(line + " " + following)
        ):
            return match
    return None


def _judgment_block(text: str) -> str:
    heading = _judgment_heading(text)
    if not heading:
        return ""
    rest = text[heading.end():]
    end = len(rest)
    for pattern in _JUDGMENT_END_PATTERNS:
        found = re.search(pattern, rest)
        if found and found.start() < end:
            end = found.start()
    return rest[:end]


def judgment_text(text: str, marks: list[tuple[int, int]] | None = None) -> str:
    """show 용: 각주·쪽 표시를 뺀 판단 절(제목 포함). 없으면 ''. marks 는 판단 절 본문 기준 구간
    목록으로, 그 구간이 걸린 줄은 ">> " 로 표시한다(폴백으로 읽은 결론 문장)."""
    cleaned = _strip_footnotes(text)
    heading = _judgment_heading(cleaned)
    if not heading:
        return ""
    body = _judgment_block(cleaned)
    full = heading.group(0).strip() + body
    offset = len(heading.group(0).strip())
    lines: list[str] = []
    position = 0
    for line in full.splitlines():
        start, end = position - offset, position + len(line) - offset
        position += len(line) + 1
        flagged = any(s < end and e > start for s, e in (marks or []))
        lines.append((">> " + line) if flagged else line)
    return "\n".join(lines).strip()


def fallback_marks(text: str, analysis: dict) -> list[tuple[int, int]]:
    """판단 절 폴백으로 읽은 결론(조문·표장 판단)의 본문 위치. 소결 제목 아래서 읽었으면 빈 목록."""
    cleaned = _strip_footnotes(text)
    judgment = _judgment_block(cleaned)
    marks: list[tuple[int, int]] = []
    if not judgment:
        return marks
    if analysis.get("결론_신뢰도") == "low" and not analysis.get("결론추론"):
        spans: dict[str, tuple[int, int]] = {}
        _conclusions_in(judgment, {}, last_wins=True, spans=spans)
        marks += list(spans.values())
    if analysis.get("소결_신뢰도") == "low" and analysis.get("표장유사_소결"):
        tail = judgment[-1500:]
        base = len(judgment) - len(tail)
        spans = {}
        _similarity_verdicts(tail, spans)
        if "표장" in spans:
            marks.append((base + spans["표장"][0], base + spans["표장"][1]))
    return marks


def next_in_queue(queue: list[dict], label_rows: list[dict]) -> dict | None:
    """큐에서 유사여부_확정이 비어 있는 첫 건(심판번호의 어느 행이든 채워졌으면 확정으로 본다)."""
    confirmed = {row["심판번호"] for row in label_rows if (row.get("유사여부_확정") or "").strip()}
    for item in queue:
        if item["심판번호"] not in confirmed:
            return item
    return None


# 결론 조문: "제34조 제1항 제7호(, 제11호 및 제12호 | 및 제8조 제1항)에(는) (각) 해당…" — 조문
# 나열 전부와 선출원 저촉(제8조 제1항·제35조 제1항)을 받고, 긍정·부정은 뒤따르는 문구로 판독한다.
_ART_LIST_TAIL = (
    r"((?:\s*(?:및|,|와|과|또는|·|ㆍ|내지)\s*(?:같은\s*법\s*|구\s*상표법\s*|상표법\s*)?(?:제\s*)?"
    r"(?:\d{1,2}\s*조\s*(?:제\s*)?\d\s*항(?:\s*제\s*\d{1,2}\s*호)?|\d{1,2}\s*호))*)"
)
_CONCLUSION_RE = re.compile(
    r"(?:제\s*(34|7)\s*조\s*제\s*1\s*항\s*제\s*(\d{1,2})\s*호"
    r"|제\s*(8|35)\s*조\s*제\s*1\s*항|제\s*(33|6)\s*조\s*제\s*1\s*항\s*제\s*\d{1,2}\s*호)"
    + _ART_LIST_TAIL
    + r"(?:\s*의\s*규정)?\s*(?:에(?:는|도)?\s*)?(?:각각?\s*)?(?:더\s*이상\s*)?(?:의하여\s*)?"
    r"(해당|위반되|등록(?:될|받을)\s*수\s*없)"
)
# 조문 뒤가 쟁점·주장이면 결론이 아니다: "해당하는지 여부", "해당한다고 주장", "해당한다는 취지"
_NOT_CONCLUSION_AFTER_RE = re.compile(
    r"^\s*(?:하는지|되는지|하는\s*것인지|여부|하는\s*경우)"
)
_CLAIM_AFTER_RE = re.compile(r"주장|다투|취지")  # 조문 뒤 35자 안이면 당사자 주장 인용
# "…에 해당한다는 이유로 (등록을 거절한) 원결정은 타당하다 / 더 이상 타당하지 아니하다"
# — 원결정 평가가 결론
_GROUND_RE = re.compile(r"이유\s*로")
_GROUND_UPHELD_RE = re.compile(
    r"타당하다|정당하다|적법하다|타당하고|정당하고|무효로\s*되어야|등록받을\s*수\s*없|거절되어야"
)
_GROUND_REVERSED_RE = re.compile(
    r"타당하지\s*(?:아니|않)|부당하|위법하|타당하다고\s*(?:할\s*수\s*없|볼\s*수\s*없)|타당성을\s*잃"
    r"|아니\s*될|아니\s*된다|해소되"
)
# 조문 뒤 40자 안의 부정 표현: "하지 아니한다 / 않게 되었다 / 한다고 할 수 없다 /
# 하는 무효사유가 존재하지 아니한다"
_NEGATIVE_AFTER_RE = re.compile(
    r"^\s*(?:(?:하지|되지)\s*(?:아니|않)"
    r"|한다고\s*(?:할\s*수\s*없|보기\s*어렵|볼\s*수\s*없|단정|인정하기\s*어렵)"
    r"|된다고\s*(?:볼\s*수\s*없|보기\s*어렵)"
    r"|하는\s*(?:무효\s*사유|거절\s*이유|사유)가?\s*(?:존재하지|없)"
    r"|않게\s*되|되는\s*것으로\s*볼\s*수\s*없|한다\s*(?:할|볼)\s*수\s*없)"
)


def _conclusions_in(
    block: str,
    found: dict[str, str],
    *,
    last_wins: bool = False,
    spans: dict[str, tuple[int, int]] | None = None,
) -> bool:
    """block 의 결론 조문을 found 에 모은다. 소결 블록은 첫 언급, 판단 절 폴백(last_wins)은
    마지막 언급. 34조·7조·8조·35조 결론을 하나라도 읽었으면 True(33조만 있으면 False).
    spans 를 주면 조문별로 읽은 문장 위치(block 기준)를 기록한다(show 의 ">>" 표시용)."""
    seen = False
    for match in _CONCLUSION_RE.finditer(block):
        law, number, law_art, law_33, extra, _verb = match.groups()
        window = block[match.end(): match.end() + 40]
        clause = re.match(r"[^,.]{0,35}", window).group(0)
        if _NOT_CONCLUSION_AFTER_RE.match(window) or _CLAIM_AFTER_RE.search(clause):
            continue
        if _GROUND_RE.search(clause):
            sentence = block[match.end(): match.end() + 120]
            if _GROUND_REVERSED_RE.search(sentence):
                polarity = "부정"
            elif _GROUND_UPHELD_RE.search(sentence):
                polarity = "긍정"
            else:
                continue
        else:
            polarity = "부정" if _NEGATIVE_AFTER_RE.match(window) else "긍정"
        keys: list[str] = []
        if law:
            keys.append(_norm_article(law, int(number)) or "")
        elif law_33:
            keys.append("33")
        else:
            keys.append(_norm_article(law_art, 1) or "")
        rest = extra or ""
        for article, clause, ho in re.findall(
            r"(\d{1,2})\s*조\s*(?:제\s*)?(\d)\s*항(?:\s*제\s*(\d{1,2})\s*호)?", rest
        ):
            if article in ("8", "35") and clause == "1":
                keys.append("35-1")
            elif article in ("33", "6"):
                keys.append("33")
            elif article in ("34", "7") and ho:
                keys.append(_norm_article(article, int(ho)) or "")
        rest = re.sub(r"\d{1,2}\s*조\s*(?:제\s*)?\d\s*항(?:\s*제\s*\d{1,2}\s*호)?", " ", rest)
        for extra_ho in re.findall(r"(\d{1,2})\s*호", rest):
            keys.append("33" if law_33 else (_norm_article(law or "34", int(extra_ho)) or ""))
        for key in keys:
            if key and (last_wins or key not in found):
                found[key] = polarity
                seen = seen or key != "33"
                if spans is not None:
                    spans[key] = (match.start(), match.end() + len(window))
    if re.search(r"(?:상표법\s*)?제\s*(?:33|6)\s*조", block) and "33" not in found:
        lacks = re.search(r"식별력\s*(?:이\s*)?(?:없|부족)", block)
        found["33"] = "부정" if lacks else "긍정"
    return seen


# 소결 문장의 유사 판단: "표장이 비유사하므로", "표장 및 사용상품이 동일 또는 유사하여",
# "유사하다고 볼 수 없다". '유사 여부'·'유사한지'·가정문·당사자 주장은 판단이 아니다.
_MARK_WORDS_RE = re.compile(r"표장|상표|서비스표|확인대상")
_GOODS_WORDS_RE = re.compile(r"상품|서비스업|역무|업무")
_SIM_SKIP_AFTER_RE = re.compile(
    r"^\s*(?:여부|한지|한\s*것인지|할\s*것인지|점|성|판단|할\s*때|하다\s*(?:하더라도|할지라도)"
    r"|하다[고는]\s*(?:가정|주장|취지)|한\s*(?:상품|서비스)[^.]{0,20}?하더라도)"
)
_SIM_HYPOTHETICAL_RE = re.compile(r"살펴보지|살펴볼\s*필요|살피지|따질\s*필요")
_SIM_NEG_AFTER_RE = re.compile(
    r"^\s*(?:하지도?\s*(?:아니|않)|하다고\s*(?:보기\s*어렵|볼\s*수\s*없|할\s*수\s*없|단정|인정하기\s*어렵)"
    r"|한\s*것으로\s*볼\s*수\s*없|하다\s*할\s*수\s*없)"
)
# "표장 및 사용상품이 … 유사" 처럼 표장·상품이 병렬로 묶인 경우만 양쪽 판단으로 본다
_BOTH_SUBJECTS_RE = re.compile(
    r"(?:표장|상표|서비스표)\s*(?:및|과|와|,|·|ㆍ)\s*(?:그\s*)?(?:사용|지정)?\s*(?:\(지정\))?\s*(?:상품|서비스업)"
    r"|(?:상품|서비스업)\s*(?:및|과|와|,|·|ㆍ)\s*(?:그\s*)?(?:표장|상표)"
)


def _compact_hangul(text: str) -> str:
    """공백 정리 + 한글 사이 공백 제거 — PDF 줄바꿈이 낱말 가운데 남긴 공백("유 사하므로")."""
    return _compact_hangul_map(text)[0]


def _compact_hangul_map(text: str) -> tuple[str, list[int]]:
    """_compact_hangul 과 같되, 압축 문자열의 각 글자가 원문의 어느 위치에서 왔는지도 돌려준다."""
    chars: list[str] = []
    origin: list[int] = []
    previous_hangul = False
    pending_space = False
    for index, char in enumerate(text):
        if char.isspace():
            pending_space = chars != []  # 앞뒤 공백은 버리고 가운데 공백은 하나로
            continue
        if pending_space:
            is_hangul = "가" <= char <= "힣"
            if not (previous_hangul and is_hangul):
                chars.append(" ")
                origin.append(index)
            pending_space = False
        chars.append(char)
        origin.append(index)
        previous_hangul = "가" <= char <= "힣"
    return "".join(chars), origin


def _similarity_verdicts(
    block: str, spans: dict[str, tuple[int, int]] | None = None
) -> dict[str, str]:
    """표장·상품의 유사/비유사 판단(마지막 언급 우선). 없으면 ''. spans 를 주면 판단 문장의
    원문 위치(block 기준)를 기록한다."""
    verdicts = {"표장": "", "상품": ""}
    compact, origin = _compact_hangul_map(block)

    def mark(key: str, start: int, end: int) -> None:
        if spans is not None and origin:
            spans[key] = (origin[max(0, start - 20)], origin[min(len(origin), end + 20) - 1] + 1)

    for match in re.finditer(r"(비\s*)?유사|비유(?=하)", compact):
        after = compact[match.end(): match.end() + 24]
        if _SIM_SKIP_AFTER_RE.match(after) or _SIM_HYPOTHETICAL_RE.search(after[:14]):
            continue
        negative = bool(match.group(1)) or compact.startswith("비유", match.start()) or bool(
            _SIM_NEG_AFTER_RE.match(after)
        )
        verdict = "비유사" if negative else "유사"
        before = compact[max(0, match.start() - 45): match.start()]
        mark_hits = [m.end() for m in _MARK_WORDS_RE.finditer(before)]
        goods_hits = [m.end() for m in _GOODS_WORDS_RE.finditer(before)]
        near = before[-30:]
        if _BOTH_SUBJECTS_RE.search(near):
            verdicts["표장"] = verdicts["상품"] = verdict
            mark("표장", match.start(), match.end())
            mark("상품", match.start(), match.end())
        elif goods_hits and (not mark_hits or goods_hits[-1] > mark_hits[-1]):
            verdicts["상품"] = verdict
            mark("상품", match.start(), match.end())
        else:
            verdicts["표장"] = verdict
            mark("표장", match.start(), match.end())
    differs = re.search(
        r"(?:표장|상표|서비스표)[^.]{0,40}?(?:서로\s*)?(?:다르|상이|구별|달라)", compact
    )
    if not verdicts["표장"] and differs:
        verdicts["표장"] = "비유사"
        mark("표장", differs.start(), differs.end())
    identical = re.search(
        r"(?:표장|상표|서비스표)(?:이|은|가|와|과|을)?\s*(?:서로\s*|실질적으로\s*)?"
        r"동일(?:하다|하고|하므로|하여|함|한\s*것)",
        compact,
    )
    if not verdicts["표장"] and identical:
        verdicts["표장"] = "유사"  # 동일은 유사에 포함된다
        mark("표장", identical.start(), identical.end())
    return verdicts


# 권리범위확인에서 유사 판단 외의 결론 근거(3등급): 효력제한(90조)·자유실시·식별력 없음·확인대상표장
# 불특정·상표적 사용 아님·상품 비유사만
_NOT_APPLY_90_RE = re.compile(
    r"해당(?:하지|되지)(?:아니|않)|해당(?:되지|하지)도않|경우에도해당|해당(?:된다|한다)고(?:볼수없|보기어렵)"
    r"|해당하는지"
)
_APPLY_90_RE = re.compile(
    r"해당하(?:여|므로|고|는|기)(?!않)|해당한다|미치지(?:아니|않)|효력이제한(?:된다|되므로|되어)|규정에따라"
)


def _scope_basis(block: str, verdicts: dict[str, str]) -> list[str]:
    compact = _compact_hangul(block)
    basis: list[str] = []
    for match in re.finditer(r"제\s*(?:90|51)\s*조", compact):
        window = compact[match.end(): match.end() + 90]
        rejected = _NOT_APPLY_90_RE.search(window)
        applied = _APPLY_90_RE.search(window)
        if applied and (rejected is None or applied.start() < rejected.start()):
            basis.append("효력제한(90조)")
            break
    if re.search(r"자유\s*실시", compact):
        basis.append("자유실시")
    elif re.search(
        r"제\s*33\s*조|식별력이?\s*(?:없|부족|미약)|기술적\s*표장|보통명칭|관용표장", compact
    ):
        basis.append("식별력 없음(33조)")
    if re.search(r"특정되(?:지|었다고\s*볼\s*수\s*없)|불특정", compact):
        basis.append("확인대상표장 불특정")
    if re.search(
        r"(?:상표|서비스표)(?:로서|로|적|으로서)(?:의|으로)?\s*(?:사용|이용)(?:이|으로|에|을|된)?[^.]{0,25}?"
        r"(?:아니(?!라)|볼\s*수\s*없|할\s*수\s*없|해당하지|않)"
        r"|출처(?:표시|를\s*표시)[^.]{0,15}?사용[^.]{0,20}?(?:볼\s*수\s*없|할\s*수\s*없)"
        r"|순수한?\s*디자인|디자인적\s*요소|장식적",
        compact,
    ):
        basis.append("상표적 사용 아님")
    if verdicts.get("상품") == "비유사" and verdicts.get("표장") != "비유사":
        basis.append("상품 비유사만")
    return basis


# 결정축·상표유형 추정 — 판단 절 끝부분(구체적 판단 + 소결)의 판단 문장에서 축 단어를 모은다
_AXIS_PATTERNS = (("외관", r"외관"), ("호칭", r"호칭|칭호|발음"), ("관념", r"관념"),
                  ("상품", r"지정상품|사용상품|상품|서비스업"))
_VERDICT_WORD_RE = re.compile(r"유사|다르|상이|차이|동일|구별|달라")
_AXIS_SKIP_SENTENCE_RE = re.compile(r"기준|판결|참조|대법원|하더라도|주장")
# 판단하지 않은 축: "나아가 지정상품의 유사 여부에 대하여 살펴보지 않더라도", "…살펴볼 필요 없이"
_AXIS_SKIP_CLAUSE_RE = re.compile(
    r"(?:나아가\s*)?[^,.]*?(?:살펴보지\s*않|살펴볼\s*필요|살펴보지\s*아니|여부에\s*(?:대하여|관하여|관하여는)[^,.]*)"
)


def _decision_axes(tail: str) -> str:
    axes: list[str] = []
    for sentence in re.split(r"(?<=다)\.\s*|\.\s+", " ".join(tail.split())):
        if _AXIS_SKIP_SENTENCE_RE.search(sentence):
            continue
        clause = _AXIS_SKIP_CLAUSE_RE.sub("", sentence)
        if not _VERDICT_WORD_RE.search(clause):
            continue
        for name, pattern in _AXIS_PATTERNS:
            if name not in axes and re.search(pattern, clause):
                axes.append(name)
    return "|".join(name for name, _ in _AXIS_PATTERNS if name in axes)


def _mark_type(subject: str, tail: str, title: str = "") -> str:
    clauses = [c for c in re.split(r"[.]\s*", " ".join((subject + " " + tail).split()))
               if not re.search(r"판결|참조|기준|대법원", c)]
    text = " ".join(clauses)
    combined = (
        r"(?:문자|한글|영문)[^.]{0,20}도형|도형[^.]{0,20}(?:문자|한글|영문)|결합\s*(?:상표|표장)"
    )
    if re.search(combined, text):
        return "결합"
    if re.search(r"도형\s*(?:상표|표장|만으로|으로만)", text):
        return "도형"
    has_figure = bool(re.search(r"도형", text))
    has_letters = bool(re.search(r"문자|한글|영문|알파벳|국문|한자|음절|호칭", text))
    if has_figure and not has_letters:
        return "도형"
    if has_figure:
        return "결합"
    if has_letters or title:
        return "문자"
    return "미상"


# 상대 표장 유형: 기초사실의 제목 줄에서 선등록/선출원/선사용/국제등록/확인대상표장을 읽는다
_COUNTERPART_HEAD_RE = re.compile(
    r"(선등록|선사용|선출원|확인대상|인용|비교대상)\s*(?:\(\s*(사용|등록)\s*\)\s*)?(?:상표|서비스표|표장)"
)
_COUNTERPART_ORDER = ("선등록", "선출원", "선사용", "국제등록", "확인대상표장", "인용")


def _counterparts(facts: str) -> tuple[list[str], list[str]]:
    """(유형 목록, 선출원 출원번호 목록)."""
    headings = [m for m in re.finditer(_ANY_HEADING + r"[^\n]*", facts)
                if _COUNTERPART_HEAD_RE.search(m.group(0))]
    types: list[str] = []
    applications: list[str] = []

    def add(name: str) -> None:
        if name and name not in types:
            types.append(name)

    for index, match in enumerate(headings):
        line = match.group(0)
        end = headings[index + 1].start() if index + 1 < len(headings) else len(facts)
        block = facts[match.start():end]
        for head, paren in _COUNTERPART_HEAD_RE.findall(line):
            add({"확인대상": "확인대상표장", "비교대상": "인용"}.get(head, head))
            if paren == "사용":
                add("선사용")
            if head == "선출원":
                number = _application_number(block)
                if number and number not in applications:
                    applications.append(number)
        if re.search(r"국제\s*(?:등록|상표)", block):
            add("국제등록")
    ordered = [name for name in _COUNTERPART_ORDER if name in types]
    return ordered, applications


# 상대 표장 번호 복구: 기초사실 제목이 없거나 상대 표장이 산문에만 있는 문서 — 본문 전체에서 번호를
# "선등록·인용·선출원·확인대상·대비" 단어의 ±200자 안에서 찾는다. 이 사건 번호와 "이 사건 …" 바로 뒤
# 번호는 제외. 복수면 ; 로 잇는다(사람이 확정).
_COUNTERPART_WORD_RE = re.compile(r"선등록|인용|선출원|확인대상|대비")
_CANDIDATE_NUMBER_RE = re.compile(
    r"(?:상표|서비스표|국제)?\s*등록(?:번호)?\s*[:：]?\s*제\s*([\d\-]{5,})\s*호"
    r"|출원(?:번호)?\s*[:：]?\s*제\s*([\d\-]{5,})\s*호"
    r"|제\s*(4[015]\s*-\s*\d{4}\s*-\s*\d{1,7})\s*호"
    r"|국제\s*상표\s*(\d{6,8})"
)
CANDIDATE_WINDOW = 200


def _normalize_candidate(raw: str) -> str:
    parts = re.split(r"\s*-\s*", raw.strip())
    if len(parts) == 3 and re.fullmatch(r"4[015]", parts[0]) and re.fullmatch(r"\d{4}", parts[1]):
        return f"{parts[0]}{parts[1]}{int(parts[2]):07d}"  # 40-2012-12345 → 4020120012345
    return _digits(raw)


def candidate_counterpart_numbers(text: str, exclude: set[str]) -> list[str]:
    found: list[str] = []
    for match in _CANDIDATE_NUMBER_RE.finditer(text):
        window = text[max(0, match.start() - CANDIDATE_WINDOW): match.end() + CANDIDATE_WINDOW]
        if not _COUNTERPART_WORD_RE.search(window):
            continue
        before = text[max(0, match.start() - 30): match.start()]
        own = list(re.finditer(r"이\s*사건", before))
        if own and not _COUNTERPART_WORD_RE.search(before[own[-1].end():]):
            continue  # "이 사건 등록상표(상표등록 제N호)" — 이 사건 번호
        number = _normalize_candidate(next(group for group in match.groups() if group))
        if number and number not in exclude and number not in found:
            found.append(number)
    return found


def analyze_text(text: str) -> dict:
    """심결문 텍스트 → 정규식 추출 결과(prefilter.csv 한 행). 2013당419 구조를 기준으로 삼는다."""
    result: dict = {"텍스트길이": len(text), "추출실패": 1 if len(text.strip()) < 200 else 0}
    text = _strip_footnotes(text)
    order = _order_block(text)
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
    subject_numbers = _registration_numbers(subject)
    result["이사건_등록번호"] = subject_numbers[0] if subject_numbers else ""
    result["이사건_출원번호"] = _application_number(subject)
    intl = re.search(r"국제등록번호[^\n]*?제\s*(\d{5,8})\s*호", subject)
    result["이사건_국제등록번호"] = intl.group(1) if intl else ""
    goods = re.search(
        r"지정상품\s*[:：]?\s*(.+?)(?=\n\s*\(\d+\)|\n\s*\([가-힣]\)|\n\s*[가-힣]\.|\Z)",
        subject, re.S,
    )
    result["이사건_지정상품"] = " ".join(goods.group(1).split())[:300] if goods else ""

    # 선등록상표 영역: 제목에 '선등록상표'가 든 첫 줄("나. 선등록상표 1", "나. 원결정이유및선등록
    # 상표", "(2) 선등록상표", "나. 확인대상표장")부터 다음 최상위 번호 제목("2. 당사자의 주장")까지
    prior_region = _find_block(
        text,
        r"(?m)^\s*(?:\(\d+\)|[가-힣]\.|\d+\.)\s*[^\n]*?" + _PRIOR_MARK,
        (_TOP_HEADING,),
    )
    prior_numbers = [
        n for n in _registration_numbers(prior_region) if n != result["이사건_등록번호"]
    ]
    result["선등록_등록번호"] = "|".join(prior_numbers)
    facts = _find_block(text, r"(?m)^\s*\d+\.\s*기\s*초\s*사\s*실", (_TOP_HEADING,))
    types, applications = _counterparts(facts or (subject + "\n" + prior_region))
    result["상대표장_유형"] = "|".join(types)
    result["선출원_출원번호"] = "|".join(
        n for n in applications if n != result["이사건_출원번호"]
    )
    result["상대표장_번호_후보"] = ""
    if not prior_numbers and not result["선출원_출원번호"]:
        exclude = {
            result["이사건_등록번호"], result["이사건_출원번호"], result["이사건_국제등록번호"],
        } - {""}
        result["상대표장_번호_후보"] = ";".join(candidate_counterpart_numbers(text, exclude))

    judgment = _judgment_block(text)
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
        pattern = _FAME_WORD_RE if key == "주지" else re.compile(word.replace(" ", r"\s*"))
        result[f"본문_{key}"] = 1 if pattern.search(text) else 0
    without_boilerplate = _FAME_BOILERPLATE_RE.sub("", text)
    result["본문_저명주지_실질"] = 1 if _FAME_WORD_RE.search(without_boilerplate) else 0

    ground = _refusal_ground_block(text)
    ground_articles = []
    for law, number in _ARTICLE_RE.findall(ground):
        key = _norm_article(law, int(number))
        if key and key not in ground_articles:
            ground_articles.append(key)
    if _ARTICLE_33_RE.search(ground) and "33" not in ground_articles:
        ground_articles.append("33")
    result["거절이유조문"] = "|".join(ground_articles)

    # 결론 조문: 소결·소결론·결론 제목 블록(신뢰도 high) → 없으면 판단 절 전체(low)
    conclusions: dict[str, str] = {}
    blocks = _conclusion_blocks(text)
    article_found = False
    for block in blocks:
        article_found = _conclusions_in(block, conclusions) or article_found
    confidence = "high" if conclusions else ""
    if judgment and not article_found:  # 소결에 34조·35조 결론이 없으면(33조만 있어도) 판단 절 전체
        if _conclusions_in(judgment, conclusions, last_wins=True) or not conclusions:
            confidence = "low" if conclusions else ""

    # 표장·상품 유사 소결: 소결 제목 블록(마지막) → 없으면 판단 절 끝 1,500자
    sub_conclusions = _conclusion_blocks(text, final=False)
    tail = judgment[-1500:] if judgment else ""
    verdict_block = sub_conclusions[-1] if sub_conclusions else tail
    verdicts = _similarity_verdicts(verdict_block) if verdict_block else {"표장": "", "상품": ""}
    verdict_confidence = "high" if sub_conclusions else "low"
    reserved = re.search(  # 소결이 표장 판단을 유보한 경우("표장의 유사여부는 살펴보지 않더라도")
        r"표장[^.]{0,30}?(?:살펴보지|살펴볼필요|살피지|따질필요)", _compact_hangul(verdict_block)
    )
    # 소결이 표장을 말하지 않으면(유보가 아니면) 판단 절 끝에서 찾는다 — 신뢰도 low
    if sub_conclusions and not verdicts["표장"] and tail and not reserved:
        fallback = _similarity_verdicts(tail)
        if fallback["표장"]:
            verdicts = {"표장": fallback["표장"], "상품": verdicts["상품"] or fallback["상품"]}
            verdict_confidence = "low"
    result["표장유사_소결"] = verdicts["표장"]
    result["상품유사_소결"] = verdicts["상품"]
    result["소결_신뢰도"] = verdict_confidence if (verdicts["표장"] or verdicts["상품"]) else ""
    result["권리범위_근거"] = (
        "|".join(_scope_basis(verdict_block, verdicts)) if verdict_block else ""
    )

    # 조문 없이 표장 소결만 있는 거절·무효 사례: 거절이유가 7호이거나 본문이 7호만 다루면 7호로
    # 추론한다(신뢰도 low)
    result["결론추론"] = ""
    if not conclusions and verdicts["표장"] and verdicts["상품"] != "비유사":
        fame_in_body = any(result[f"본문_{k}"] for k in ("34_9", "34_11", "34_12", "34_13"))
        if result["거절이유조문"] == "34-7" or (result["본문_34_7"] == 1 and not fame_in_body):
            conclusions["34-7"] = "긍정" if verdicts["표장"] == "유사" else "부정"
            confidence = "low"
            result["결론추론"] = "표장 소결 → 7호"
    result["결론절추출"] = 1 if blocks else 0
    result["결론조문"] = "|".join(f"{k}:{v}" for k, v in conclusions.items())
    result["결론_신뢰도"] = confidence
    if "35-1" in conclusions and "선출원" not in types:  # 선출원 저촉 결론 → 상대 표장은 선출원
        types = types + ["선출원"]
        result["상대표장_유형"] = "|".join(t for t in _COUNTERPART_ORDER if t in types)
    # 선등록상표가 소멸·무효·취소돼 유사 판단 없이 끝난 사건: 거절결정 취소 또는 무효심판 기각
    result["선등록소멸취소"] = 1 if (
        result["주문결과"] in ("취소", "기각") and _PRIOR_MARK_GONE_RE.search(judgment or text)
    ) else 0
    result["결정축_추정"] = _decision_axes(judgment) if judgment else ""
    result["상표유형_추정"] = _mark_type(subject, judgment) if (subject or judgment) else "미상"
    return result


PREFILTER_COLUMNS = [
    "심판번호", "텍스트길이", "추출실패", "주문", "주문결과", "이사건_구분", "이사건_등록번호",
    "이사건_출원번호", "이사건_지정상품", "선등록_등록번호", "선출원_출원번호",
    "상대표장_번호_후보", "상대표장_유형", "판단절",
    "본문_34_7", "본문_34_9", "본문_34_11", "본문_34_12", "본문_34_13", "본문_33",
    "이사건_국제등록번호", "본문_저명", "본문_주지", "본문_부정한목적", "본문_식별력",
    "본문_저명주지_실질", "결론절추출", "결론조문", "결론_신뢰도", "결론추론", "거절이유조문",
    "선등록소멸취소", "표장유사_소결", "상품유사_소결", "소결_신뢰도", "권리범위_근거",
    "결정축_추정", "상표유형_추정",
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


def _flag(analysis: dict, key: str) -> bool:
    return str(analysis.get(key, "0")) == "1"


def classify_scope(analysis: dict) -> tuple[str, str]:
    """권리범위확인(4단계 규칙). 34조 결론이 없는 것이 정상이라 '추출 실패'로 보지 않는다.

    1 = 판단 절에 표장 유사 소결(유사/비유사) & 34조 9·11·12·13호 결론 없음 & 저명·주지 실질
    언급 없음. 3 = 각하, 효력제한(90조)·자유실시·식별력 없음·상품 비유사만·확인대상표장 불특정·
    상표적 사용 아님. 나머지 2.
    """
    if analysis.get("주문결과") == "각하":
        return "3", "각하(본안 판단 없음)"
    basis = analysis.get("권리범위_근거") or ""
    if basis:
        return "3", "권리범위: " + basis.replace("|", "·")
    verdict = analysis.get("표장유사_소결") or ""
    if not verdict:
        return "2", "권리범위: 표장 유사 소결 없음"
    conclusions = parse_conclusions(analysis.get("결론조문", ""))
    fame = [k for k in FAME_ARTICLES if k in conclusions]
    if fame:
        return "2", "권리범위: 표장 소결 있으나 인지도 조문 " + ",".join(fame)
    if _flag(analysis, "본문_저명주지_실질"):
        return "2", f"권리범위: 표장 {verdict} 소결이나 저명·주지 언급"
    return "1", f"권리범위: 표장 {verdict} 소결, 인지도 언급 없음"


def classify(analysis: dict, *, kind: str = "", ignore_boilerplate: bool = True) -> tuple[str, str]:
    """(자동등급, 사유). 1=순수 유사 사례 후보, 2=검토 필요, 3=제외 후보.

    2026-09-30 3단계 규칙: 각하와 선등록상표 소멸·무효 취소는 3등급(유사 판단 없음), 저명·주지
    언급은 요부 판단기준 판례 문구("주지ㆍ저명하거나…")를 뺀 뒤(본문_저명주지_실질)로 판단한다.
    2026-10-01 4단계: kind="scope" 는 classify_scope. 선출원 저촉(35-1 = 구 8조1항)은 7호와 같이
    다루되 표장 유사 소결이 있어야 1등급.
    ignore_boilerplate=False 는 이전 규칙(참고 열 등급_원규칙)용.
    """
    if kind == "scope":
        return classify_scope(analysis)
    if analysis.get("주문결과") == "각하":
        return "3", "각하(본안 판단 없음)"
    if _flag(analysis, "선등록소멸취소"):
        return "3", "유사 판단 없음(선등록상표 소멸·무효로 취소)"
    conclusions = parse_conclusions(analysis.get("결론조문", ""))
    fame_in_conclusion = [k for k in FAME_ARTICLES if k in conclusions]
    fame_keys = (("본문_저명", "저명"), ("본문_주지", "주지"), ("본문_부정한목적", "부정한 목적"))
    fame_in_body = [name for key, name in fame_keys if _flag(analysis, key)]
    if ignore_boilerplate:
        fame_in_body = [n for n in fame_in_body if n == "부정한 목적"]
        if _flag(analysis, "본문_저명주지_실질"):
            fame_in_body.append("저명·주지(문구 제외 후)")
    if fame_in_conclusion:
        return "3", "결론에 인지도 조문 " + ",".join(fame_in_conclusion)
    if conclusions and all(key == "33" for key in conclusions):
        return "3", "식별력 사례(33조만)"
    if not conclusions:
        return "2", "결론 조문 추출 실패"
    inferred = " (표장 소결 추론, 신뢰도 low)" if analysis.get("결론추론") else ""
    if "34-7" in conclusions and not fame_in_body:
        return "1", "결론 7호, 인지도 언급 없음" + inferred
    if "34-7" in conclusions:
        return "2", "결론 7호이나 본문에 " + "·".join(fame_in_body)
    if "35-1" in conclusions:
        verdict = analysis.get("표장유사_소결") or ""
        if fame_in_body:
            return "2", "결론 35-1(선출원 저촉)이나 본문에 " + "·".join(fame_in_body)
        if not verdict:
            return "2", "결론 35-1(선출원 저촉)이나 표장 소결 없음"
        return "1", f"결론 35-1(선출원 저촉), 표장 {verdict} 소결, 인지도 언급 없음"
    return "2", "결론 조문이 7호 아님(" + ",".join(conclusions) + ")"


def estimate_similarity(kind: str, analysis: dict, trial_desc: str = "") -> tuple[str, str]:
    """유사여부 추정과 근거. 사람이 '유사여부_확정'에서 확정한다.

    권리범위확인: 주문 속함 → 유사, 불속 → 비유사, 기각은 적극(→ 불속)·소극(→ 속함)으로 읽는다.
    그 외: 결론 7호(없으면 35-1) 긍정/부정. 소결의 표장 판단이 있으면 대조해 불일치를 근거에 적고,
    상품 비유사로 7호가 부정된 경우는 표장 판단(유사)을 따른다.
    """
    result = analysis.get("주문결과", "")
    mark_verdict = analysis.get("표장유사_소결") or ""
    if kind == "scope":
        if result == "속함":
            return "유사", "주문 속함(scope)"
        if result == "불속":
            return "비유사", "주문 불속(scope)"
        if result == "기각" and "소극" in (trial_desc or ""):
            return "유사", "주문 기각(소극적 권리범위확인 → 속함)"
        if result == "기각" and "적극" in (trial_desc or ""):
            return "비유사", "주문 기각(적극적 권리범위확인 → 불속)"
        return "", ""
    conclusions = parse_conclusions(analysis.get("결론조문", ""))
    for article, label in (("34-7", "결론 7호"), ("35-1", "결론 35-1(선출원 저촉)")):
        polarity = conclusions.get(article)
        if polarity not in ("긍정", "부정"):
            continue
        guess = "유사" if polarity == "긍정" else "비유사"
        basis = f"{label} {polarity}"
        if analysis.get("결론추론"):
            basis += " — 표장 소결 추론"
        elif guess == "비유사" and not mark_verdict and analysis.get("상품유사_소결") == "비유사":
            return "", f"{label} 부정은 상품 비유사 때문 — 표장 판단 없음"
        elif mark_verdict and mark_verdict != guess:
            if guess == "비유사" and analysis.get("상품유사_소결") == "비유사":
                return "유사", f"소결 표장 유사(상품 비유사로 {label} 부정)"
            basis += f" · 소결 표장 {mark_verdict}와 불일치"
        return guess, basis
    if mark_verdict:
        return mark_verdict, f"소결 표장 {mark_verdict}(조문 없음)"
    if "34-7" not in conclusions:
        return "", ""
    if kind == "refusal":
        mapping = {"기각": "유사", "취소": "비유사"}
    else:  # invalidation: 인용(무효·일부무효) = 유사, 기각 = 비유사
        mapping = {"무효": "유사", "일부무효": "유사", "취소": "유사", "기각": "비유사"}
    guess = mapping.get(result, "")
    return guess, f"주문 {result}({kind})" if guess else ""


def family_key(plaintiff: str, prior_numbers: list[str]) -> str:
    """청구인 + 선등록번호 집합의 해시 — 같은 청구인이 같은 선등록상표를 두고 낸 연속 사건 묶음."""
    name = "".join((plaintiff or "").split()).casefold()  # 공백 차이("주식회사 X"/"주식회사X") 무시
    payload = name + "|" + "|".join(sorted(set(prior_numbers)))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def _empty_human() -> dict[str, str]:
    return {column: "" for column in PRESERVED_COLUMNS}


def build_sheet_rows(
    list_rows: list[dict],
    prefilter_rows: list[dict],
    kinds: dict[str, dict],
    *,
    include_missing: bool = False,
) -> list[dict]:
    """labels.csv 행. 같은 family 는 첫 건(심판번호 순)만 1등급을 유지하고 나머지는 '중복'."""
    analyses = {row["심판번호"]: row for row in prefilter_rows}
    sheet: list[dict] = []
    first_of_family: dict[str, str] = {}
    for row in sorted(list_rows, key=lambda r: r["심판번호"]):
        number = row["심판번호"]
        analysis = analyses.get(number)
        kind = kind_for_trial_desc(row.get("종류", ""), kinds)
        base = {
            "심판번호": number,
            "종류": row.get("종류", ""),
            "심판상태": row.get("심판상태", ""),
            "심결월": row.get("심결월", ""),
            "상표A_명칭": row.get("상표명칭", ""),
            **_empty_human(),
        }
        if analysis is None:
            if include_missing:
                sheet.append({
                    **base,
                    "상표A_번호": row.get("등록번호") or row.get("출원번호", ""),
                    "상표B_번호": "", "상대표장_번호_후보": "", "상대표장_유형": "",
                    "지정상품_원문": "", "조문플래그": "",
                    "결론조문": "", "신뢰도": "", "표장유사_소결": "",
                    "자동등급": "", "등급사유": "텍스트 미추출", "등급_원규칙": "", "family": "",
                    "참고표시": "", "유사여부_추정": "", "추정근거": "", "결정축_추정": "",
                    "상표유형_추정": "",
                })
            continue
        grade, reason = classify(analysis, kind=kind)
        old_grade, _ = classify(analysis, kind=kind, ignore_boilerplate=False)
        guess, basis = estimate_similarity(kind, analysis, row.get("종류", ""))
        notes = []
        prior_list = [p for p in (analysis.get("선등록_등록번호") or "").split("|") if p]
        prior_list += [p for p in (analysis.get("선출원_출원번호") or "").split("|")
                       if p and p not in prior_list]
        if kind == "scope":  # 확인대상표장은 번호가 없다 → 청구인·피청구인·이 사건 등록번호
            family = family_key(
                f"{row.get('청구인', '')}|{row.get('피청구인', '')}",
                [analysis.get("이사건_등록번호") or row.get("등록번호", "")],
            )
        else:
            family = family_key(row.get("청구인", ""), prior_list)
        if family in first_of_family:
            notes.append(f"중복(family 첫 건 {first_of_family[family]})")
            if grade == "1":
                grade, reason = "2", f"family 중복(첫 건 {first_of_family[family]})"
        else:
            first_of_family[family] = number
        if analysis.get("주문결과") == "각하":
            notes.append("각하(본안 판단 없음)")
        if _flag(analysis, "선등록소멸취소"):
            notes.append("선등록상표 소멸로 취소(유사 판단 없음)")
        if analysis.get("이사건_국제등록번호"):
            notes.append("국제등록출원")
        counterpart = analysis.get("상대표장_유형", "")
        if kind != "scope" and not prior_list and counterpart not in ("", "선사용"):
            notes.append("상대 표장 번호 없음")
        flags = [key.replace("본문_", "").replace("_", "-") for key in analysis
                 if key.startswith("본문_") and str(analysis[key]) == "1"]
        subject_number = (analysis.get("이사건_등록번호") or row.get("등록번호")
                          or analysis.get("이사건_출원번호") or row.get("출원번호", ""))
        confidence = (analysis.get("소결_신뢰도") if kind == "scope"
                      else analysis.get("결론_신뢰도")) or ""
        prior = prior_list or [""]
        for prior_number in prior:  # 선등록상표가 여러 건이면 행을 나눈다
            sheet.append({
                **base,
                "상표A_번호": subject_number,
                "상표B_번호": prior_number,
                "상대표장_번호_후보": analysis.get("상대표장_번호_후보", ""),
                "상대표장_유형": analysis.get("상대표장_유형", ""),
                "지정상품_원문": analysis.get("이사건_지정상품", ""),
                "조문플래그": ",".join(flags),
                "결론조문": analysis.get("결론조문", ""),
                "신뢰도": confidence,
                "표장유사_소결": analysis.get("표장유사_소결", ""),
                "자동등급": grade,
                "등급사유": reason,
                "등급_원규칙": old_grade,
                "family": family,
                "참고표시": "; ".join(notes),
                "유사여부_추정": guess,
                "추정근거": basis,
                "결정축_추정": analysis.get("결정축_추정", ""),
                "상표유형_추정": analysis.get("상표유형_추정", ""),
            })
    return sheet


def merge_human_columns(rows: list[dict], previous: list[dict]) -> int:
    """이전 labels.csv 의 사람 열·라벨 메타·llm_b 열을 새 행에 옮긴다 — (심판번호, 상표B_번호) 일치
    우선. 그 심판번호의 이전 행이 하나뿐이면 상표B 가 달라도 옮긴다(여러 행이면 어느 것인지 몰라
    비워 둔다). 4단계 전 열 이름(판단축)도 받는다. 옮긴 행 수를 돌려준다."""
    by_pair: dict[tuple[str, str], dict[str, str]] = {}
    by_trial: dict[str, dict[str, str]] = {}
    rows_per_trial: dict[str, int] = {}
    for old in previous:
        rows_per_trial[old.get("심판번호", "")] = rows_per_trial.get(old.get("심판번호", ""), 0) + 1
        values = {}
        for column in PRESERVED_COLUMNS:
            value = (old.get(column) or "").strip()
            if not value:
                for legacy, renamed in LEGACY_HUMAN_COLUMNS.items():
                    if renamed == column:
                        value = (old.get(legacy) or "").strip()
            values[column] = value
        if not any(values.values()):
            continue
        by_pair.setdefault((old.get("심판번호", ""), old.get("상표B_번호", "")), values)
        by_trial.setdefault(old.get("심판번호", ""), values)
    moved = 0
    for row in rows:
        pair = (row["심판번호"], row.get("상표B_번호", ""))
        values = by_pair.get(pair)
        if not values and rows_per_trial.get(row["심판번호"], 0) == 1:
            values = by_trial.get(row["심판번호"])
        if not values:
            continue
        for column, value in values.items():
            if value:
                row[column] = value
        moved += 1
    return moved


def _grade_summary(rows: list[dict]) -> tuple[dict[str, int], int]:
    trials: dict[str, str] = {}
    for r in rows:
        trials.setdefault(r["심판번호"], r["자동등급"])
    return {g: sum(1 for v in trials.values() if v == g) for g in ("1", "2", "3")}, len(trials)


CURATION_COLUMNS = [
    "순번", "심판번호", "종류", "상표A_명칭", "상대표장_번호", "유사여부_추정", "신뢰도",
    "등급사유",
]
_CURATION_KIND_ORDER = {"scope": 0, "refusal": 1, "invalidation": 2}
_CURATION_CONFIDENCE_ORDER = {"high": 0, "low": 1, "": 2}
_CURATION_SECOND_RE = re.compile(r"^권리범위: 표장 (?:유사|비유사) 소결이나 저명·주지 언급")


def build_curation_queue(rows: list[dict], kinds: dict[str, dict]) -> list[dict]:
    """큐레이션 순서: 1등급(권리범위확인 → 거절결정불복 → 무효, 각 안에서 신뢰도 high → low) 다음에
    2등급 중 "권리범위 … 저명·주지 언급". family 중복은 제외. 심판번호당 한 줄(상대 표장 번호는 ; 로
    잇고, 없으면 복구 후보)."""
    first: dict[str, dict] = {}
    numbers: dict[str, list[str]] = {}
    for row in rows:
        first.setdefault(row["심판번호"], row)
        known = numbers.setdefault(row["심판번호"], [])
        if row.get("상표B_번호") and row["상표B_번호"] not in known:
            known.append(row["상표B_번호"])
    picked: list[tuple[tuple[int, int, int, str], dict]] = []
    for number, row in first.items():
        reason = row.get("등급사유", "")
        if "중복" in row.get("참고표시", "") or reason.startswith("family 중복"):
            continue
        if row.get("자동등급") == "1":
            bucket = 0
        elif row.get("자동등급") == "2" and _CURATION_SECOND_RE.match(reason):
            bucket = 1
        else:
            continue
        kind = kind_for_trial_desc(row.get("종류", ""), kinds)
        key = (bucket, _CURATION_KIND_ORDER.get(kind, 3),
               _CURATION_CONFIDENCE_ORDER.get(row.get("신뢰도", ""), 2), number)
        picked.append((key, row))
    picked.sort(key=lambda item: item[0])
    return [
        {
            "순번": index,
            "심판번호": row["심판번호"],
            "종류": row.get("종류", ""),
            "상표A_명칭": row.get("상표A_명칭", ""),
            "상대표장_번호": ";".join(numbers.get(row["심판번호"], []))
            or row.get("상대표장_번호_후보", ""),
            "유사여부_추정": row.get("유사여부_추정", ""),
            "신뢰도": row.get("신뢰도", ""),
            "등급사유": row.get("등급사유", ""),
        }
        for index, (_, row) in enumerate(picked, start=1)
    ]


def run_sheet(args: argparse.Namespace, session: Session) -> int:
    paths_ = session.paths
    source = paths_.list_all_csv if paths_.list_all_csv.exists() else paths_.list_csv
    list_rows = _read_csv(source)
    known = {row["심판번호"] for row in list_rows}
    list_rows += [row for row in _read_csv(paths_.list_csv) if row["심판번호"] not in known]
    prefilter_rows = _read_csv(paths_.prefilter_csv)
    previous = _read_csv(paths_.labels_csv)
    kinds = load_kinds(args.kinds_config)
    rows = build_sheet_rows(list_rows, prefilter_rows, kinds)
    moved = merge_human_columns(rows, previous)
    _write_csv(paths_.labels_csv, LABEL_COLUMNS, rows)
    grades, trials = _grade_summary(rows)
    print(f"## sheet: {len(rows)}행/{trials}건 → {paths_.labels_csv} "
          f"(1등급 {grades['1']}, 2등급 {grades['2']}, 3등급 {grades['3']}) · "
          f"사람 열 보존 {moved}행(이전 {len(previous)}행)")
    queue = build_curation_queue(rows, kinds)
    _write_csv(paths_.curation_queue, CURATION_COLUMNS, queue)
    second = sum(1 for item in queue if _CURATION_SECOND_RE.match(item["등급사유"]))
    recovered = sum(1 for r in {row["심판번호"]: row for row in rows}.values()
                    if not r.get("상표B_번호") and r.get("상대표장_번호_후보"))
    print(f"- 큐레이션 큐 {len(queue)}건(1등급 {len(queue) - second} · "
          f"권리범위 저명·주지 언급 {second}) → {paths_.curation_queue} · "
          f"상대 표장 번호 후보 복구 {recovered}건")
    return 0


# ====================================================================
# show — 주문 + 판단 절 + 자동 판정 (호출 없음, 큐레이션 보조)
# ====================================================================

def run_show(args: argparse.Namespace, session: Session) -> int:
    paths_ = session.paths
    kinds = load_kinds(args.kinds_config)
    listed = {row["심판번호"]: row for row in _read_csv(paths_.list_csv)}
    if paths_.list_all_csv.exists():
        for row in _read_csv(paths_.list_all_csv):
            listed.setdefault(row["심판번호"], row)
    label_rows = _read_csv(paths_.labels_csv)
    labels: dict[str, dict] = {}
    for row in label_rows:
        labels.setdefault(row["심판번호"], row)
    if getattr(args, "batch", 0):
        return run_batch(args, session)
    trials = list(getattr(args, "trial", None) or [])
    if getattr(args, "next", False):
        queue = _read_csv(paths_.curation_queue)
        if not queue:
            print(f"[없음] {paths_.curation_queue} — sheet 먼저", file=sys.stderr)
            return 1
        item = next_in_queue(queue, label_rows)
        if item is None:
            print(f"큐 {len(queue)}건 모두 유사여부_확정 완료")
            return 0
        print(f"큐 {item['순번']}/{len(queue)} · {item['등급사유']} · "
              f"추정 {item['유사여부_추정'] or '-'} · 신뢰도 {item['신뢰도'] or '-'}")
        trials.append(item["심판번호"])
    if not trials:
        print("[오류] 심판번호를 주거나 --next 를 쓰세요.", file=sys.stderr)
        return 2
    exit_code = 0
    for number in trials:
        text_path = paths_.text_dir / f"{number}.txt"
        if not text_path.exists():
            print(f"[없음] {text_path} — fetch·extract 먼저", file=sys.stderr)
            exit_code = 1
            continue
        text = text_path.read_text(encoding="utf-8")
        analysis = analyze_text(text)
        row = listed.get(number, {"심판번호": number, "종류": "", "심결월": "", "상표명칭": ""})
        sheet = build_sheet_rows([row], [{"심판번호": number, **analysis}], kinds)
        auto = sheet[0] if sheet else {}
        print(f"## {number} · {row.get('종류', '')} · {row.get('심결월', '')} · "
              f"{row.get('상표명칭', '')} · 청구인 {row.get('청구인', '')}")
        print("### 주문")
        print(analysis["주문"] or "(주문을 찾지 못함)")
        print(f"→ 주문결과 {analysis['주문결과']}")
        marks = fallback_marks(text, analysis)
        print("### 판단 절" + (" (>> 폴백으로 읽은 결론 문장)" if marks else ""))
        print(judgment_text(text, marks) or "(판단 절 제목을 찾지 못함)")
        print("### 자동 판정")
        dash = lambda value: value or "-"  # noqa: E731 — 빈 값 표시
        print(f"- 등급 {auto.get('자동등급', '')} — {auto.get('등급사유', '')} "
              f"(신뢰도 {dash(auto.get('신뢰도', ''))})")
        print(f"- 유사여부 추정 {dash(auto.get('유사여부_추정', ''))} — "
              f"{dash(auto.get('추정근거', ''))}")
        print(f"- 결론조문 {dash(analysis['결론조문'])} · "
              f"표장 소결 {dash(analysis['표장유사_소결'])} · "
              f"상품 소결 {dash(analysis['상품유사_소결'])} · "
              f"권리범위 근거 {dash(analysis['권리범위_근거'])}")
        print(f"- 결정축 추정 {dash(analysis['결정축_추정'])} · "
              f"상표유형 추정 {analysis['상표유형_추정']}")
        prior = [r.get("상표B_번호", "") for r in sheet if r.get("상표B_번호")]
        candidates = analysis.get("상대표장_번호_후보", "")
        print(f"- 상대 표장 {dash(analysis['상대표장_유형'])} 번호 {dash(', '.join(prior))}"
              f"{' (후보 ' + candidates + ')' if candidates else ''} · "
              f"이 사건 {dash(auto.get('상표A_번호', ''))} · "
              f"조문플래그 {dash(auto.get('조문플래그', ''))}")
        human = labels.get(number)
        if human:
            filled = {c: human.get(c, "") for c in PRESERVED_COLUMNS if human.get(c)}
            print(f"- 라벨(labels.csv): {filled if filled else '아직 없음'}")
    return exit_code


# ====================================================================
# label·confirm·review·sample --n·show --batch — 큐레이션 라벨 (호출 없음)
# ====================================================================

VERDICTS = ("유사", "비유사", "제외")
AXES = ("외관", "호칭", "관념", "상품")
MARK_TYPES = ("문자", "도형", "결합-문자요부", "결합-도형요부")
EXCLUDE_REASONS = ("인지도", "식별력", "소멸", "각하", "불특정", "비사용", "중복", "기타")
LABEL_SOURCES = ("llm", "human")
CONFIDENCES = ("high", "low")
LABEL_PASSES = ("a", "b")


class LabelError(ValueError):
    """label/confirm/review/sample 의 입력·상태 오류. exit 2 입력 · 3 덮어쓰기 거부 · 1 데이터."""

    def __init__(self, message: str, exit_code: int = 2):
        super().__init__(message)
        self.exit_code = exit_code


@contextmanager
def _labels_lock(paths_: TrialPaths):
    """labels.csv 갱신의 프로세스 간 배타 잠금 — 라벨링 에이전트 둘(pass a·b)이 동시에 label 을
    돌려도 읽기→쓰기 사이에 상대 갱신이 유실되지 않게 한다(kipris_client 의 카운터 잠금과 같다)."""
    lock_path = paths_.labels_csv.with_suffix(paths_.labels_csv.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_csv_atomic(path: Path, columns: list[str], rows: list[dict]) -> None:
    """임시 파일에 쓰고 바꿔치기 — 쓰다 죽어도 labels.csv 가 반쯤 쓰인 채 남지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def _load_labels(paths_: TrialPaths) -> tuple[list[str], list[dict]]:
    """labels.csv 를 열 순서째 읽는다. 라벨 열이 없는(이전 sheet) 파일은 열을 덧붙인다."""
    if not paths_.labels_csv.exists():
        raise LabelError(f"{paths_.labels_csv} 가 없습니다 — sheet 먼저", 1)
    with paths_.labels_csv.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for column in LABEL_COLUMNS:
        if column not in fieldnames:
            fieldnames.append(column)
    for row in rows:
        for column in fieldnames:
            if row.get(column) is None:
                row[column] = ""
    return fieldnames, rows


def _target_rows(rows: list[dict], number: str, b: str | None) -> list[dict]:
    targets = [row for row in rows if row.get("심판번호") == number]
    if not targets:
        raise LabelError(f"labels.csv 에 심판번호 {number} 가 없습니다", 1)
    if b is not None:
        matched = [row for row in targets if (row.get("상표B_번호") or "") == b]
        if not matched:
            have = ", ".join(row.get("상표B_번호") or "(없음)" for row in targets)
            raise LabelError(
                f"심판번호 {number} 에 상표B_번호 {b!r} 행이 없습니다(있는 값: {have})", 1
            )
        targets = matched
    return targets


def canonical_axes(value: str) -> str:
    """'호칭,외관' → '외관|호칭'(고정 순서). 허용값 밖이면 LabelError."""
    parts = [part.strip() for part in (value or "").replace("|", ",").split(",") if part.strip()]
    bad = [part for part in parts if part not in AXES]
    if bad:
        raise LabelError(f"--axis 허용값은 {','.join(AXES)} 입니다: {','.join(bad)}")
    return "|".join(axis for axis in AXES if axis in parts)


def _refuse_if_confirmed(targets: list[dict]) -> None:
    confirmed = [row for row in targets if (row.get("확인여부") or "").strip().upper() == "Y"]
    if confirmed:
        where = ", ".join(
            f"{row['심판번호']}(상표B {row.get('상표B_번호') or '-'})" for row in confirmed
        )
        raise LabelError(
            f"[거부] 사람이 확인한 라벨(확인여부=Y)은 llm 이 덮어쓸 수 없습니다: {where} — "
            "--source human 으로 수정하거나 --b 로 다른 행을 고르세요",
            3,
        )


def apply_label(
    rows: list[dict],
    number: str,
    verdict: str,
    *,
    axis: str = "",
    mark_type: str = "",
    reason: str = "",
    memo: str | None = None,
    b: str | None = None,
    source: str = "",
    evidence: str = "",
    confidence: str = "",
    pass_: str = "a",
    undo: bool = False,
) -> list[dict]:
    """labels.csv 행(들)에 라벨을 기록하고 바뀐 행을 돌려준다. 다른 열은 건드리지 않는다.

    pass a: 유사여부_확정·판단축_확정·상표유형_확정·제외사유·메모 + 라벨출처·근거문장·확신도·
    확인여부.
    human 은 확인여부=Y. llm 은 확인여부=Y 인 행을 덮어쓰지 못한다(LabelError exit 3).
    사람이 LLM 라벨을 수정하면 이전 LLM 판정을 llm_판정_원본 에 남긴다(일치율용).
    pass b: llm_b_* 열에만 기록(사람 열 그대로). --undo 는 해당 pass 의 열을 비운다.
    """
    if pass_ not in LABEL_PASSES:
        raise LabelError("--pass 는 a 또는 b 입니다")
    if source not in LABEL_SOURCES:
        raise LabelError("--source 는 llm 또는 human 이어야 합니다")
    targets = _target_rows(rows, number, b)
    if pass_ == "a" and source == "llm":
        _refuse_if_confirmed(targets)
    if undo:
        columns = LLM_B_COLUMNS if pass_ == "b" else HUMAN_COLUMNS + LABEL_META_COLUMNS
        for row in targets:
            for column in columns:
                row[column] = ""
        return targets
    if verdict not in VERDICTS:
        raise LabelError(f"판정은 {'|'.join(VERDICTS)} 중 하나여야 합니다: {verdict!r}")
    if mark_type and mark_type not in MARK_TYPES:
        raise LabelError(f"--type 허용값은 {'|'.join(MARK_TYPES)} 입니다: {mark_type!r}")
    if reason and reason not in EXCLUDE_REASONS:
        raise LabelError(f"--reason 허용값은 {'|'.join(EXCLUDE_REASONS)} 입니다: {reason!r}")
    if verdict == "제외" and not reason:
        raise LabelError("제외에는 --reason 이 필요합니다")
    if verdict != "제외" and reason:
        raise LabelError("--reason 은 판정이 제외일 때만 씁니다")
    if confidence not in CONFIDENCES:
        raise LabelError("--confidence 는 high 또는 low 여야 합니다")
    evidence = (evidence or "").strip()
    if not evidence:
        raise LabelError("--evidence(소결 문장 원문)가 필요합니다")
    axes = canonical_axes(axis)
    for row in targets:
        if pass_ == "b":
            row["llm_b_유사여부"] = verdict
            row["llm_b_판단축"] = axes
            row["llm_b_제외사유"] = reason
            row["llm_b_확신도"] = confidence
            row["llm_b_근거"] = evidence
            continue
        previous_source = (row.get("라벨출처") or "").strip()
        previous_verdict = (row.get("유사여부_확정") or "").strip()
        if source == "human" and previous_source == "llm" and previous_verdict:
            row["llm_판정_원본"] = previous_verdict  # 사람이 LLM 라벨을 수정 — 원본을 남긴다
        row["유사여부_확정"] = verdict
        row["판단축_확정"] = axes
        row["상표유형_확정"] = mark_type
        row["제외사유"] = reason
        if memo is not None:
            row["메모"] = memo
        row["라벨출처"] = source
        row["근거문장"] = evidence
        row["확신도"] = confidence
        row["확인여부"] = "Y" if source == "human" else ""
    return targets


def confirm_labels(rows: list[dict], number: str, b: str | None = None) -> int:
    """기존 LLM 라벨을 그대로 승인: 확인여부=Y, 라벨출처=human-confirmed, llm_판정_원본=판정.
    새로 승인한 행 수를 돌려준다(이미 사람 라벨·승인된 행은 그대로)."""
    targets = _target_rows(rows, number, b)
    unlabeled = [row for row in targets if not (row.get("유사여부_확정") or "").strip()]
    if unlabeled:
        raise LabelError(f"심판번호 {number} 에 승인할 라벨이 없습니다(유사여부_확정 비어 있음)", 1)
    foreign = [row for row in targets
               if (row.get("라벨출처") or "").strip() not in ("llm", "human", "human-confirmed")]
    if foreign:
        raise LabelError(
            f"심판번호 {number} 의 라벨출처가 llm 이 아닙니다(label 로 기록한 라벨만 승인)", 1
        )
    confirmed = 0
    for row in targets:
        if (row.get("라벨출처") or "").strip() != "llm":
            continue
        row["llm_판정_원본"] = row["유사여부_확정"]
        row["라벨출처"] = "human-confirmed"
        row["확인여부"] = "Y"
        confirmed += 1
    return confirmed


def _label_args_summary(args: argparse.Namespace) -> str:
    parts = [f"판정 {args.verdict or '-'}", f"출처 {args.source}", f"pass {args.pass_}"]
    if args.axis:
        parts.append(f"축 {canonical_axes(args.axis)}")
    if args.mark_type:
        parts.append(f"유형 {args.mark_type}")
    if args.reason:
        parts.append(f"사유 {args.reason}")
    return " · ".join(parts)


def run_label(args: argparse.Namespace, session: Session) -> int:
    paths_ = session.paths
    with _labels_lock(paths_):
        fieldnames, rows = _load_labels(paths_)
        changed = apply_label(
            rows, args.trial, args.verdict,
            axis=args.axis, mark_type=args.mark_type, reason=args.reason, memo=args.memo,
            b=args.b, source=args.source, evidence=args.evidence, confidence=args.confidence,
            pass_=args.pass_, undo=args.undo,
        )
        _write_csv_atomic(paths_.labels_csv, fieldnames, rows)
    action = "라벨 비움" if args.undo else "라벨 기록"
    print(f"## {action}: {args.trial} {len(changed)}행 ({_label_args_summary(args)}) "
          f"→ {paths_.labels_csv}")
    return 0


def run_confirm(args: argparse.Namespace, session: Session) -> int:
    paths_ = session.paths
    with _labels_lock(paths_):
        fieldnames, rows = _load_labels(paths_)
        confirmed = confirm_labels(rows, args.trial, args.b)
        _write_csv_atomic(paths_.labels_csv, fieldnames, rows)
    print(f"## 승인: {args.trial} {confirmed}행 확인여부=Y(human-confirmed) → {paths_.labels_csv}")
    return 0


# ---- show --batch: 라벨 없는 다음 n건을 markdown 으로(정규식 추정·결정축·등급사유는 뺀다) ----

def unlabeled_queue(queue: list[dict], label_rows: list[dict], pass_: str = "a") -> list[dict]:
    column = "llm_b_유사여부" if pass_ == "b" else "유사여부_확정"
    labeled = {row["심판번호"] for row in label_rows if (row.get(column) or "").strip()}
    return [item for item in queue if item["심판번호"] not in labeled]


def next_batch_index(base: Path) -> int:
    numbers = []
    for path in base.glob("batch_*.md"):
        match = re.fullmatch(r"batch_(\d+)\.md", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


BATCH_GUIDE = (
    "라벨 명령: `label <심판번호> <유사|비유사|제외> [--axis 외관,호칭,관념,상품] "
    "[--type 문자|도형|결합-문자요부|결합-도형요부] "
    "[--reason 인지도|식별력|소멸|각하|불특정|비사용|중복|기타] [--b 상대번호] "
    "--source llm --evidence '<소결 문장 원문>' --confidence high|low --pass {pass_}`"
)


def render_batch(
    items: list[dict], paths_: TrialPaths, label_rows: list[dict], *, index: int, pass_: str
) -> str:
    """배치 markdown: 심판번호·종류·상표A 명칭·상대 번호(후보 포함)·주문·판단 절. 자동 판정은 뺀다.
    """
    numbers: dict[str, list[str]] = {}
    candidates: dict[str, str] = {}
    for row in label_rows:
        if row.get("상표B_번호"):
            numbers.setdefault(row["심판번호"], []).append(row["상표B_번호"])
        candidates.setdefault(row["심판번호"], row.get("상대표장_번호_후보") or "")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"# 큐레이션 배치 {index} — {len(items)}건 · pass {pass_} · {stamp}",
        "",
        BATCH_GUIDE.format(pass_=pass_),
        "",
    ]
    for order, item in enumerate(items, start=1):
        number = item["심판번호"]
        text_path = paths_.text_dir / f"{number}.txt"
        text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
        order_text = analyze_text(text)["주문"] if text else ""
        counterpart = "; ".join(dict.fromkeys(numbers.get(number, []))) or "-"
        candidate = candidates.get(number, "")
        lines += [
            f"## {order}. {number} · {item.get('종류', '')} · "
            f"상표A: {item.get('상표A_명칭') or '-'} · 상대 번호: {counterpart}"
            + (f" (후보 {candidate})" if candidate else ""),
            "",
            "### 주문",
            order_text or "(주문을 찾지 못함)",
            "",
            "### 판단 절",
            "```text",
            (judgment_text(text) if text else "") or "(판단 절을 찾지 못함 — 텍스트 없음)",
            "```",
            "",
        ]
    return "\n".join(lines)


def run_batch(args: argparse.Namespace, session: Session) -> int:
    paths_ = session.paths
    pass_ = getattr(args, "pass_", "a") or "a"
    if pass_ not in LABEL_PASSES:
        raise LabelError("--pass 는 a 또는 b 입니다")
    queue = _read_csv(paths_.curation_queue)
    if not queue:
        raise LabelError(f"{paths_.curation_queue} 가 없습니다 — sheet 먼저", 1)
    label_rows = _read_csv(paths_.labels_csv)
    pending = unlabeled_queue(queue, label_rows, pass_)
    items = pending[: args.batch]
    if not items:
        print(f"큐 {len(queue)}건 모두 pass {pass_} 라벨이 있습니다")
        return 0
    index = next_batch_index(paths_.base)
    out = paths_.base / f"batch_{index}.md"
    out.write_text(
        render_batch(items, paths_, label_rows, index=index, pass_=pass_), encoding="utf-8"
    )
    print(f"## batch {index}: pass {pass_} 라벨 없는 {len(items)}건"
          f"(남은 {len(pending)}/{len(queue)}) → {out}")
    print("- " + ", ".join(item["심판번호"] for item in items))
    return 0


# ---- review: 재검토 큐 ----

REVIEW_COLUMNS = [
    "순번", "심판번호", "상표B_번호", "종류", "유사여부_확정", "유사여부_추정", "llm_b_유사여부",
    "확신도", "라벨출처", "사유",
]


def _llm_verdict(row: dict) -> str:
    """pass a 의 LLM 판정: 사람이 수정했으면 llm_판정_원본, 아니면 llm/human-confirmed 행의 판정."""
    original = (row.get("llm_판정_원본") or "").strip()
    if original:
        return original
    if (row.get("라벨출처") or "").strip() in ("llm", "human-confirmed"):
        return (row.get("유사여부_확정") or "").strip()
    return ""


def _passes_disagree(row: dict) -> bool:
    a = (row.get("유사여부_확정") or "").strip()
    b = (row.get("llm_b_유사여부") or "").strip()
    if not a or not b:
        return False
    if a != b:
        return True
    return a == "제외" and (row.get("제외사유") or "") != (row.get("llm_b_제외사유") or "")


def build_review_queue(label_rows: list[dict]) -> list[dict]:
    """(a) LLM 판정 ≠ 정규식 추정 (b) 확신도 low (c) 메모에 '애매' (d) pass a ≠ pass b."""
    queue: list[dict] = []
    for row in label_rows:
        verdict = (row.get("유사여부_확정") or "").strip()
        b_verdict = (row.get("llm_b_유사여부") or "").strip()
        if not verdict and not b_verdict:
            continue
        reasons: list[str] = []
        llm = _llm_verdict(row)
        estimate = (row.get("유사여부_추정") or "").strip()
        if llm and estimate and llm != estimate:
            reasons.append("LLM≠추정")
        if (row.get("확신도") or "").strip() == "low":
            reasons.append("확신도 low")
        if "애매" in (row.get("메모") or ""):
            reasons.append("메모 애매")
        if _passes_disagree(row):
            reasons.append("A≠B")
        if not reasons:
            continue
        queue.append({
            "순번": len(queue) + 1,
            "심판번호": row["심판번호"],
            "상표B_번호": row.get("상표B_번호", ""),
            "종류": row.get("종류", ""),
            "유사여부_확정": verdict,
            "유사여부_추정": estimate,
            "llm_b_유사여부": b_verdict,
            "확신도": row.get("확신도", ""),
            "라벨출처": row.get("라벨출처", ""),
            "사유": ";".join(reasons),
        })
    return queue


def run_review(args: argparse.Namespace, session: Session) -> int:
    paths_ = session.paths
    _fieldnames, rows = _load_labels(paths_)
    queue = build_review_queue(rows)
    _write_csv(paths_.review_queue, REVIEW_COLUMNS, queue)
    counts = {key: sum(1 for item in queue if key in item["사유"].split(";"))
              for key in ("LLM≠추정", "확신도 low", "메모 애매", "A≠B")}
    print(f"## review: {len(queue)}행 → {paths_.review_queue} · " + " · ".join(
        f"{key} {value}" for key, value in counts.items()
    ))
    return 0


# ---- sample --n: 미확인 LLM 라벨의 종류×판정 층화 무작위 표본(검증용) ----

VERIFY_COLUMNS = [
    "순번", "층", "심판번호", "상표B_번호", "종류", "유사여부_확정", "판단축_확정", "제외사유",
    "확신도", "근거문장",
]


def allocate_strata(sizes: dict[str, int], n: int) -> dict[str, int]:
    """비례 배분(비어 있지 않은 층은 최소 1), 큰 나머지 순으로 n 에 맞춘다."""
    total = sum(sizes.values())
    if total == 0 or n <= 0:
        return {key: 0 for key in sizes}
    if n >= total:
        return dict(sizes)
    keys = sorted(sizes)
    quota = {key: min(sizes[key], max(1, int(n * sizes[key] / total))) for key in keys}
    remainder = {key: n * sizes[key] / total - int(n * sizes[key] / total) for key in keys}
    while sum(quota.values()) > n:  # 최소 1 때문에 넘치면 큰 층부터 하나씩 뺀다
        key = max((k for k in keys if quota[k] > 1), key=lambda k: quota[k], default=None)
        if key is None:
            break
        quota[key] -= 1
    while sum(quota.values()) < n:
        open_keys = [k for k in keys if quota[k] < sizes[k]]
        key = max(open_keys, key=lambda k: remainder[k], default=None)
        if key is None:
            break
        quota[key] += 1
        remainder[key] = -1.0
    return quota


def select_verify_sample(
    label_rows: list[dict], kinds: dict[str, dict], n: int, seed: int
) -> list[dict]:
    pool = [
        row for row in label_rows
        if (row.get("라벨출처") or "").strip() == "llm"
        and not (row.get("확인여부") or "").strip()
        and (row.get("유사여부_확정") or "").strip()
    ]
    strata: dict[str, list[dict]] = {}
    for row in pool:
        key = f"{kind_for_trial_desc(row.get('종류', ''), kinds) or '?'}/{row['유사여부_확정']}"
        strata.setdefault(key, []).append(row)
    quota = allocate_strata({key: len(rows) for key, rows in strata.items()}, n)
    rng = random.Random(seed)
    picked: list[dict] = []
    for key in sorted(strata):
        for row in rng.sample(strata[key], min(quota[key], len(strata[key]))):
            picked.append({
                "순번": len(picked) + 1, "층": key, "심판번호": row["심판번호"],
                "상표B_번호": row.get("상표B_번호", ""), "종류": row.get("종류", ""),
                "유사여부_확정": row["유사여부_확정"], "판단축_확정": row.get("판단축_확정", ""),
                "제외사유": row.get("제외사유", ""), "확신도": row.get("확신도", ""),
                "근거문장": row.get("근거문장", ""),
            })
    return picked


def run_verify_sample(args: argparse.Namespace, session: Session) -> int:
    paths_ = session.paths
    _fieldnames, rows = _load_labels(paths_)
    picked = select_verify_sample(rows, load_kinds(args.kinds_config), args.n, args.seed)
    out = Path(args.out) if args.out else paths_.verify_queue
    _write_csv(out, VERIFY_COLUMNS, picked)
    strata: dict[str, int] = {}
    for item in picked:
        strata[item["층"]] = strata.get(item["층"], 0) + 1
    print(f"## sample: 미확인 LLM 라벨에서 {len(picked)}건(요청 {args.n}, seed {args.seed}) "
          f"→ {out}")
    by_stratum = " · ".join(f"{key} {count}" for key, count in sorted(strata.items()))
    print("- 층별: " + (by_stratum or "없음"))
    return 0


# ---- status: 판정 집계·일치율 ----

def _rate(hits: int, total: int) -> str:
    return f"{hits}/{total} ({hits * 100 // total}%)" if total else "0/0 (-)"


def label_summary(label_rows: list[dict], queue: list[dict]) -> list[str]:
    labeled = [row for row in label_rows if (row.get("유사여부_확정") or "").strip()]
    verdicts = {key: sum(1 for row in labeled if row["유사여부_확정"] == key) for key in VERDICTS}
    sources: dict[str, int] = {}
    for row in labeled:
        source = (row.get("라벨출처") or "").strip() or "(출처 없음)"
        sources[source] = sources.get(source, 0) + 1
    confirmed = sum(1 for row in labeled if (row.get("확인여부") or "").strip().upper() == "Y")
    # LLM↔사람: confirm 은 일치, 사람이 LLM 라벨을 수정(llm_판정_원본 있음·라벨출처 human)은 불일치
    agree = sum(1 for row in labeled if (row.get("라벨출처") or "") == "human-confirmed")
    modified = sum(1 for row in labeled
                   if (row.get("라벨출처") or "") == "human" and (row.get("llm_판정_원본") or ""))
    estimate_pairs = [
        (_llm_verdict(row), (row.get("유사여부_추정") or "").strip()) for row in labeled
    ]
    estimate_pairs = [(llm, est) for llm, est in estimate_pairs if llm and est]
    estimate_agree = sum(1 for llm, est in estimate_pairs if llm == est)
    both = [row for row in label_rows
            if _llm_verdict(row) and (row.get("llm_b_유사여부") or "").strip()]
    ab_agree = sum(1 for row in both if not _passes_disagree(row))
    b_only = sum(1 for row in label_rows if (row.get("llm_b_유사여부") or "").strip())
    lines = [
        f"라벨: 유사 {verdicts['유사']} · 비유사 {verdicts['비유사']} · 제외 {verdicts['제외']} "
        f"(행 {len(labeled)}/{len(label_rows)}) · 출처 "
        + (", ".join(f"{key} {value}" for key, value in sorted(sources.items())) or "-")
        + f" · 확인(Y) {confirmed} · pass b {b_only}",
        f"LLM↔사람 일치율 {_rate(agree, agree + modified)} — confirm {agree} · 수정 {modified}",
        f"LLM↔추정 일치율 {_rate(estimate_agree, len(estimate_pairs))}",
        f"LLM A↔B 일치율 {_rate(ab_agree, len(both))}",
    ]
    if queue:
        remaining_a = len(unlabeled_queue(queue, label_rows, "a"))
        remaining_b = len(unlabeled_queue(queue, label_rows, "b"))
        lines.append(
            f"남은 큐: pass a {remaining_a}/{len(queue)} · pass b {remaining_b}/{len(queue)}"
        )
    return lines


# ====================================================================
# sample — 층화 표본 (trialDecisionDoc=Y 만, 종류별 분산 규칙)
# ====================================================================

SAMPLE_COLUMNS = [
    "심판번호", "kind", "종류", "심결월", "상표명칭", "청구인", "출원번호", "등록번호",
    "심결문유무",
]


def _round_robin_by_month(rows: list[dict], n: int) -> list[dict]:
    """월별로 묶어 한 달에 한 건씩 돌아가며 뽑는다(월 분산). 각 월 안에서는 입력 순서."""
    by_month: dict[str, list[dict]] = {}
    for row in rows:
        by_month.setdefault(row["심결월"], []).append(row)
    picked: list[dict] = []
    while len(picked) < n and any(by_month.values()):
        for month in sorted(by_month):
            if by_month[month] and len(picked) < n:
                picked.append(by_month[month].pop(0))
    return picked


def select_sample(
    rows: list[dict], kinds: dict[str, dict], quotas: dict[str, int], exclude: set[str]
) -> list[dict]:
    """종류별 표본. scope=최신순, invalidation=월 분산, refusal=청구인당 월 1건 + 월 분산."""
    usable = [
        r for r in rows
        if r.get("심결문유무", "").upper() == "Y" and r["심판번호"] not in exclude
    ]
    for row in usable:
        row["kind"] = kind_for_trial_desc(row.get("종류", ""), kinds)
    picked: list[dict] = []
    scope = sorted(
        (r for r in usable if r["kind"] == "scope"),
        key=lambda r: (r["심결월"], r["심판번호"]), reverse=True,
    )
    picked += scope[: quotas.get("scope", 0)]
    invalid = sorted(
        (r for r in usable if r["kind"] == "invalidation"), key=lambda r: r["심판번호"]
    )
    picked += _round_robin_by_month(invalid, quotas.get("invalidation", 0))
    seen_month_plaintiff: set[tuple[str, str]] = set()
    refusal: list[dict] = []
    for r in sorted((r for r in usable if r["kind"] == "refusal"), key=lambda r: r["심판번호"]):
        key = (r["심결월"], " ".join(r.get("청구인", "").split()).casefold())
        if key in seen_month_plaintiff:
            continue
        seen_month_plaintiff.add(key)
        refusal.append(r)
    picked += _round_robin_by_month(refusal, quotas.get("refusal", 0))
    return picked


def run_sample(args: argparse.Namespace, session: Session) -> int:
    if getattr(args, "n", 0):
        return run_verify_sample(args, session)
    if not args.out:
        raise LabelError("수집 표본에는 --out 이 필요합니다(검증 표본은 --n)")
    paths_ = session.paths
    source = Path(args.source) if args.source else paths_.list_all_csv
    rows = _read_csv(source)
    exclude = {p.stem for p in paths_.pdf_dir.glob("*.pdf")} if paths_.pdf_dir.exists() else set()
    exclude |= {r["심판번호"] for r in _read_csv(paths_.fetch_log)}
    for extra in args.exclude or []:
        exclude |= {r["심판번호"] for r in _read_csv(Path(extra))}
    quotas = {"scope": args.scope, "invalidation": args.invalidation, "refusal": args.refusal}
    picked = select_sample(rows, load_kinds(args.kinds_config), quotas, exclude)
    _write_csv(Path(args.out), SAMPLE_COLUMNS, picked)
    counts: dict[str, int] = {}
    years: dict[tuple[str, str], int] = {}
    for r in picked:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        years[(r["kind"], r["심결월"][:4])] = years.get((r["kind"], r["심결월"][:4]), 0) + 1
    print(f"## sample: {source} {len(rows)}건 중 문서 Y·미수집 대상에서 {len(picked)}건 "
          f"→ {args.out}")
    print(f"- 종류별: {counts} (요청 {quotas})")
    for kind in ("scope", "invalidation", "refusal"):
        line = ", ".join(f"{y}:{c}" for (k, y), c in sorted(years.items()) if k == kind)
        print(f"- {kind} 연도 분포: {line or '-'}")
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
            xml_text = api_get_with_retry(
                session, BIBLIO_URL, {"trialNumber": number}, BIBLIO_AUTH_PARAM
            )
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


def curation_progress(label_rows: list[dict]) -> str:
    """큐레이션 진행률: 1등급 중 유사여부_확정이 채워진 건수, 제외사유 표시 건수(심판번호 단위)."""
    first: dict[str, dict] = {}
    for row in label_rows:
        first.setdefault(row["심판번호"], row)
    confirmed_by_trial: dict[str, bool] = {}
    excluded: set[str] = set()
    for row in label_rows:
        if (row.get("유사여부_확정") or "").strip():
            confirmed_by_trial[row["심판번호"]] = True
        if (row.get("제외사유") or "").strip():
            excluded.add(row["심판번호"])
    grade_one = [n for n, r in first.items() if r.get("자동등급") == "1"]
    confirmed_one = sum(1 for n in grade_one if confirmed_by_trial.get(n))
    confirmed_all = sum(1 for n in first if confirmed_by_trial.get(n))
    percent = (confirmed_one * 100 // len(grade_one)) if grade_one else 0
    return (f"큐레이션: 1등급 {len(grade_one)}건 중 유사여부_확정 {confirmed_one}건({percent}%) · "
            f"전체 확정 {confirmed_all}/{len(first)}건 · 제외사유 {len(excluded)}건")


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
    label_rows = _read_csv(paths_.labels_csv)
    print(f"- list.csv {len(list_rows)}건 · PDF {pdfs}건 · 텍스트 {texts}건 · "
          f"prefilter {prefilter_count}행 · labels {len(label_rows)}행")
    if label_rows:
        print("- " + curation_progress(label_rows))
        for line in label_summary(label_rows, _read_csv(paths_.curation_queue)):
            print("- " + line)
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
    p_list.add_argument("--all-kinds", action="store_true",
                        help="종류 필터 없이 월 1회 호출, 전 종류를 list_all.csv 에 보관")

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
    p_fetch.add_argument("--queue", metavar="CSV", help="sample 이 만든 표본 CSV 순서대로 받는다")
    p_fetch.add_argument("--kind-cap", default="", metavar="kind=N,...",
                         help="종류별 상한(우선순위 정렬 뒤 적용), 예: scope=280,invalidation=100")

    p_extract = sub.add_parser("extract", help="PDF → 텍스트 + prefilter.csv")
    common(p_extract)
    p_extract.add_argument("--force", action="store_true", help="이미 있는 텍스트도 다시 추출")

    p_sheet = sub.add_parser("sheet", help="labels.csv 초안(재생성 때 사람 열 보존)")
    common(p_sheet)
    p_show = sub.add_parser("show", help="심판번호의 주문·판단 절·자동 판정 보기(호출 없음)")
    p_show.add_argument("trial", nargs="*", metavar="심판번호")
    p_show.add_argument("--next", action="store_true",
                        help="curation_queue.csv 에서 유사여부_확정이 비어 있는 첫 건을 보여 준다")
    p_show.add_argument("--batch", type=int, default=0, metavar="N",
                        help="큐에서 라벨 없는 다음 N건을 batch_<k>.md 로(자동 판정은 넣지 않음)")
    p_show.add_argument("--pass", dest="pass_", default="a", help="--batch 기준 pass: a(기본)|b")
    p_label = sub.add_parser("label", help="큐레이션 라벨 기록(호출 없음)")
    p_label.add_argument("trial", metavar="심판번호")
    p_label.add_argument("verdict", nargs="?", default="", metavar="유사|비유사|제외")
    p_label.add_argument("--axis", default="", help="판단축: 외관,호칭,관념,상품 중 복수(쉼표)")
    p_label.add_argument("--type", dest="mark_type", default="",
                         help="상표유형: 문자|도형|결합-문자요부|결합-도형요부")
    p_label.add_argument("--reason", default="",
                         help="제외사유(제외일 때 필수): " + "|".join(EXCLUDE_REASONS))
    p_label.add_argument("--memo", default=None, help="메모(생략하면 기존 메모 유지)")
    p_label.add_argument("--b", default=None, metavar="상대번호",
                         help="그 상표B_번호 행만(없으면 심판번호의 전 행)")
    p_label.add_argument("--source", default="", help="llm|human (human 은 확인여부=Y)")
    p_label.add_argument("--evidence", default="", help="소결 문장 원문")
    p_label.add_argument("--confidence", default="", help="high|low")
    p_label.add_argument("--pass", dest="pass_", default="a",
                         help="a(기본, 판정 열)|b(llm_b_* 열, 이중 라벨링)")
    p_label.add_argument("--undo", action="store_true", help="해당 pass 의 라벨 열을 비운다")
    p_confirm = sub.add_parser("confirm", help="LLM 라벨을 그대로 승인(확인여부=Y)")
    p_confirm.add_argument("trial", metavar="심판번호")
    p_confirm.add_argument("--b", default=None, metavar="상대번호")
    sub.add_parser("review", help="재검토 큐 review_queue.csv(LLM≠추정·확신도 low·메모 애매·A≠B)")
    p_sample = sub.add_parser("sample", help="층화 표본 CSV 생성(호출 없음)")
    p_sample.add_argument("--source", default="", help="목록 CSV(기본 list_all.csv)")
    p_sample.add_argument("--scope", type=int, default=0)
    p_sample.add_argument("--invalidation", type=int, default=0)
    p_sample.add_argument("--refusal", type=int, default=0)
    p_sample.add_argument("--exclude", action="append", metavar="CSV", help="제외할 심판번호 CSV")
    p_sample.add_argument("--out", default="", metavar="CSV",
                          help="수집 표본 출력(필수) · 검증 표본은 기본 verify_queue.csv")
    p_sample.add_argument("--n", type=int, default=0,
                          help="검증 표본: 미확인 LLM 라벨에서 종류×판정 층화 무작위 N건")
    p_sample.add_argument("--seed", type=int, default=0, help="검증 표본 난수 시드")
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
               "sheet": run_sheet, "show": run_show, "label": run_label, "confirm": run_confirm,
               "review": run_review, "sample": run_sample, "biblio": run_biblio,
               "status": run_status}
    try:
        return runners[args.command](args, session)
    except LabelError as exc:
        print(f"[오류] {exc}" if exc.exit_code != 3 else str(exc), file=sys.stderr)
        return exc.exit_code
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
