"""
KIPRIS Plus Open API 클라이언트 (백엔드-5 수집 / 백엔드-7 호칭 검색 공용).

팀 공통 규칙(TODO.pdf)을 코드로 강제한다:
- 모든 호출에 호출 카운터 + 초당 딜레이 (상품별 월 1,000회 / 초당 50회)
- 인증키는 .env 로만 주입 (커밋 금지 — 키 공유는 약관 위반, 각자 발급)
- fileToss.jsp 형태의 파일 링크는 일회성/시한부 → 응답 수신 즉시 다운로드

두 개의 서로 다른 KIPRIS API 계열이 공존한다(실측 확정):
  - 상표명완전일치(trademarkNameMatchSearchInfo, /name-check 백엔드-7):
    openapi/rest 계열, 인증 파라미터 **accessKey**, 응답 PascalCase.
  - 항목별검색(getAdvancedSearch, 본 수집 백엔드-6):
    kipo-api/kipi 계열, 인증 파라미터 **ServiceKey**, 응답 camelCase.
호스트(KIPRIS_BASE_URL)만 같고 경로·인증 파라미터·응답 표기가 다르다.

오퍼레이션 URL/파라미터명은 KIPRIS "API 통합설명서"에서 확인해 .env 에 넣는다
(사이트 상단 링크에서 다운로드. 상표 출원속보: 오퍼레이션 54개):
    KIPRIS_ACCESS_KEY               = 상품 인증키 (마이페이지). 두 계열 공용 —
                                      계열에 따라 accessKey/ServiceKey 로 이름만 바꿔 싣는다.
    KIPRIS_BASE_URL                 = 공통 호스트 (기본 https://plus.kipris.or.kr/)
    KIPRIS_TM_NAME_SEARCH_URL       = 상표명완전일치 오퍼레이션 URL 오버라이드(선택,
                                      미설정 시 BASE_URL + 경로 상수로 자동 조합)
    KIPRIS_TM_NAME_PARAM            = 상표명 파라미터명 (기본 trademarkNameMatch)
                                      실측: trademarkName 을 주면 resultCode 11
                                      (NO_MANDATORY_REQUEST_PARAMETERS_ERROR)
    KIPRIS_APPLICANT_SEARCH_URL     = 항목별검색(getAdvancedSearch) URL 오버라이드(선택)
    KIPRIS_APPLICANT_PARAM          = 출원인 파라미터명 (기본 applicantName)
"""

import json
import logging
import os
import re
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import urlsplit, urlunsplit

# 호출 카운터는 API 서버와 수집 스크립트가 같은 파일을 공유한다(프로세스 2개 이상).
# 스레드 락만으로는 프로세스 간 read-modify-write 가 겹쳐 증가분이 유실되므로
# OS 파일 잠금을 함께 쓴다. 플랫폼별 구현만 여기서 고른다.
if os.name == "nt":
    import msvcrt
else:
    import fcntl

import httpx

from . import paths

# httpx 는 INFO 에서 query string 전체를 기록한다. KIPRIS 인증키와 사용자 질의가
# query parameter 로 전달되므로 애플리케이션의 root INFO 로거로 전파되지 않게 한다.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ====================================================================
# 설정 (.env)
# ====================================================================

ACCESS_KEY: str = os.getenv("KIPRIS_ACCESS_KEY", "")

# 공통 호스트. 오퍼레이션 경로 상수와 조합해 전체 URL 을 만든다. 두 API 계열
# (openapi/rest 상표명완전일치 · kipo-api/kipi getAdvancedSearch)이 이 호스트를 공유한다.
KIPRIS_BASE_URL: str = os.getenv("KIPRIS_BASE_URL", "https://plus.kipris.or.kr/")

# 인증키가 query string 에 실리므로 HTTPS + 공식 호스트만 허용한다. 환경변수 오타나
# 악성 리다이렉트로 키가 제3자 호스트에 전달되는 것을 막는 자격증명 경계다.
ALLOWED_KIPRIS_HOSTS: frozenset[str] = frozenset({"plus.kipris.or.kr"})

# 오퍼레이션 경로(호스트 제외) — 실측으로 확정한 검증값.
TM_NAME_SEARCH_PATH: str = (
    "openapi/rest/trademarkInfoSearchService/trademarkNameMatchSearchInfo"
)
ADVANCED_SEARCH_PATH: str = "kipo-api/kipi/trademarkInfoSearchService/getAdvancedSearch"
# 서지상세정보 getBibliographyDetailInfoSearch(백엔드-6 유사군 보강). getAdvancedSearch
# 와 같은 kipo-api/kipi 계열(인증 ServiceKey). 출원번호 1개로 유사군·지정상품·비엔나·
# 서지요약을 준다 — getAdvancedSearch 응답에 없는 유사군을 얻는 유일한 경로다.
BIBLIO_DETAIL_PATH: str = (
    "kipo-api/kipi/trademarkInfoSearchService/getBibliographyDetailInfoSearch"
)


def _compose_url(base: str, path: str) -> str:
    """KIPRIS_BASE_URL 과 오퍼레이션 경로를 슬래시 중복 없이 합친다."""
    return base.rstrip("/") + "/" + path.lstrip("/")


# 상표명완전일치(백엔드-7). env 오버라이드가 있으면 우선, 없으면 검증된 기본값으로 조합한다.
# (과거엔 기본값이 "" 라 .env 없이는 동작하지 않았다 — 표의 검증값으로 채운다.)
TM_NAME_SEARCH_URL: str = os.getenv("KIPRIS_TM_NAME_SEARCH_URL", "") or _compose_url(
    KIPRIS_BASE_URL, TM_NAME_SEARCH_PATH
)
TM_NAME_PARAM: str = os.getenv("KIPRIS_TM_NAME_PARAM", "trademarkNameMatch")

# 항목별검색 getAdvancedSearch(백엔드-6 본 수집). 인증 파라미터는 ServiceKey.
# env 오버라이드명은 기존 KIPRIS_APPLICANT_SEARCH_URL 을 계속 지원한다(설정 시 우선).
ADVANCED_SEARCH_URL: str = os.getenv("KIPRIS_APPLICANT_SEARCH_URL", "") or _compose_url(
    KIPRIS_BASE_URL, ADVANCED_SEARCH_PATH
)
APPLICANT_PARAM: str = os.getenv("KIPRIS_APPLICANT_PARAM", "applicantName")

# 서지상세정보(백엔드-6 유사군 보강). env 오버라이드가 있으면 우선, 없으면 검증 경로로 조합.
BIBLIO_DETAIL_URL: str = os.getenv("KIPRIS_BIBLIO_DETAIL_URL", "") or _compose_url(
    KIPRIS_BASE_URL, BIBLIO_DETAIL_PATH
)

# 월 호출 예산. 공식 한도는 1,000회지만 수동 실험/재시도 여유로 50회를 남긴다.
MONTHLY_CALL_BUDGET: int = int(os.getenv("KIPRIS_MONTHLY_BUDGET", "950"))

# 일일 호출 예산 — 월 예산과 별개의 운영 가드. 하루짜리 폭주(데모 반복·버그 루프·
# name-check 다건 질의: 1질의 최대 5콜)가 월 쿼터를 태우는 것을 막는다.
# 0 이하로 설정하면 일일 검사를 끈다. 자정(UTC) 기준으로 초기화된다.
DAILY_CALL_BUDGET: int = int(os.getenv("KIPRIS_DAILY_BUDGET", "80"))

# 초당 50회 제한 → 요청 간 최소 간격. 여유를 두고 기본 0.1s (10 req/s).
MIN_CALL_INTERVAL_SEC: float = float(os.getenv("KIPRIS_MIN_INTERVAL", "0.1"))

# 호출 카운터 영속 파일 (스크립트 재시작에도 월 누적 유지, gitignore 영역)
CALL_COUNTER_PATH: Path = Path(
    os.getenv("KIPRIS_COUNTER_PATH", str(paths.ML_DATA_DIR / "kipris_call_count.json"))
)

# resultCode 의미 (TODO.pdf 실측)
RESULT_CODE_OK = "00"
# 31 은 "상품 미신청 또는 승인 대기" 상태에서 반환된다(실측: TODO.pdf).
# 키를 막 발급받아 아직 승인(처리상태 '사용중') 전이면 이 코드가 오므로,
# 사용자가 바로 조치할 수 있게 마이페이지 확인 경로까지 안내한다.
RESULT_CODE_MESSAGES = {
    "31": "상품 미신청 또는 승인 대기 (DEADLINE_HAS_EXPIRED_ERROR) — "
          "plus.kipris.or.kr 마이페이지 > 오픈API 신청현황에서 처리상태가 '사용중'인지 "
          "확인하세요. '승인대기/신청'이면 승인 후 다시 시도하고, '사용중'인데도 이 오류가 "
          "나면 상품 신청 상태와 .env 의 KIPRIS_ACCESS_KEY 를 재확인하세요.",
}


class KiprisError(RuntimeError):
    """API 오류 (resultCode != 00, 네트워크 오류, 설정 누락)."""

    def __init__(self, message: str, result_code: Optional[str] = None):
        super().__init__(message)
        self.result_code = result_code


class KiprisConfigError(KiprisError):
    """KIPRIS 키/URL 설정이 없거나 안전 정책을 위반함."""


class KiprisNetworkError(KiprisError):
    """KIPRIS 네트워크/HTTP 오류. 메시지에 요청 URL을 포함하지 않는다."""


class KiprisProtocolError(KiprisError):
    """KIPRIS 응답 envelope/XML 계약 위반."""


class CallBudgetExceeded(KiprisError):
    """월 호출 예산 초과 — 다음 달 1일 초기화까지 호출 금지."""


# ====================================================================
# 호출 카운터 + 딜레이
# ====================================================================

class RateLimiter:
    """
    월/일 누적 카운터(파일 영속) + 요청 간 최소 간격을 강제한다.

    사용: limiter.acquire() 를 API 호출 직전에 부른다.
    파일 포맷: {"2026-07": 123, "2026-07-10": 8, ...}
      - "YYYY-MM" 키 = 월별 누적, "YYYY-MM-DD" 키 = 일별 누적(오래된 날짜는 자동 정리).
    잠금 계층: threading.Lock(프로세스 내) + OS 파일 잠금(프로세스 간 — API 서버와
    수집 스크립트가 같은 카운터 파일을 공유하므로 둘 다 필요).
    """

    _DAY_KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    _DAY_KEY_RETENTION_DAYS = 35  # 한 달 조금 넘게 남겨 월말·월초 경계 디버깅에 쓴다

    def __init__(
        self,
        counter_path: Path = CALL_COUNTER_PATH,
        monthly_budget: int = MONTHLY_CALL_BUDGET,
        min_interval: float = MIN_CALL_INTERVAL_SEC,
        daily_budget: int = DAILY_CALL_BUDGET,
    ):
        self.counter_path = counter_path
        self.monthly_budget = monthly_budget
        self.daily_budget = daily_budget
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last_call = 0.0

    @staticmethod
    def _month_key() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    @staticmethod
    def _day_key() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @contextmanager
    def _file_lock(self):
        """카운터 파일에 대한 프로세스 간 배타 잠금 (Windows msvcrt / POSIX flock)."""
        lock_path = self.counter_path.with_suffix(self.counter_path.suffix + ".lock")
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(lock_path, "a+b")
        except OSError as exc:
            raise KiprisConfigError(
                "KIPRIS 호출 카운터 잠금 파일을 열 수 없습니다."
            ) from exc
        try:
            try:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                # msvcrt.LK_LOCK 은 약 10초 재시도 후 포기한다 — 다른 프로세스가
                # 잠금을 오래 쥐고 있다는 뜻이므로 호출을 실패시키는 편이 안전하다.
                raise KiprisConfigError(
                    "KIPRIS 호출 카운터 잠금을 얻지 못했습니다 (다른 프로세스가 사용 중)."
                ) from exc
            yield
        finally:
            try:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()

    def _load(self) -> dict:
        if not self.counter_path.exists():
            return {}
        try:
            payload = json.loads(self.counter_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise KiprisConfigError(
                "KIPRIS 호출 카운터를 안전하게 읽을 수 없습니다."
            ) from exc
        if not isinstance(payload, dict):
            raise KiprisConfigError("KIPRIS 호출 카운터 형식이 올바르지 않습니다.")
        return payload

    def used_this_month(self) -> int:
        return int(self._load().get(self._month_key(), 0))

    def used_today(self) -> int:
        return int(self._load().get(self._day_key(), 0))

    def _prune_stale_day_keys(self, counts: dict) -> None:
        """보존 기간이 지난 일별 키를 제거한다 (월별 키는 그대로 둔다)."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self._DAY_KEY_RETENTION_DAYS)
        ).strftime("%Y-%m-%d")
        for key in [k for k in counts if self._DAY_KEY_RE.match(str(k)) and k < cutoff]:
            del counts[key]

    def acquire(self) -> None:
        """예산 검사 + 카운터 증가 + 초당 딜레이. 초과 시 CallBudgetExceeded."""
        with self._lock:
            with self._file_lock():
                counts = self._load()
                month_key = self._month_key()
                day_key = self._day_key()
                used_month = int(counts.get(month_key, 0))
                used_day = int(counts.get(day_key, 0))
                if used_month >= self.monthly_budget:
                    raise CallBudgetExceeded(
                        f"이번 달 KIPRIS 호출 예산({self.monthly_budget}회)을 다 썼습니다 "
                        f"(사용: {used_month}). 매월 1일 초기화."
                    )
                if self.daily_budget > 0 and used_day >= self.daily_budget:
                    raise CallBudgetExceeded(
                        f"오늘 KIPRIS 호출 예산({self.daily_budget}회)을 다 썼습니다 "
                        f"(사용: {used_day}). 자정(UTC) 초기화 — 급하면 "
                        f"KIPRIS_DAILY_BUDGET 를 올려 재시작하세요."
                    )
                counts[month_key] = used_month + 1
                counts[day_key] = used_day + 1
                self._prune_stale_day_keys(counts)
                try:
                    self.counter_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.counter_path.with_suffix(
                        self.counter_path.suffix + ".tmp"
                    )
                    temporary.write_text(
                        json.dumps(counts, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    os.replace(temporary, self.counter_path)
                except OSError as exc:
                    raise KiprisConfigError(
                        "KIPRIS 호출 카운터를 안전하게 저장할 수 없습니다."
                    ) from exc
            # 초당 제한 — 마지막 호출로부터 최소 간격 보장.
            # (파일 잠금 밖에서 대기해 다른 프로세스의 카운터 접근을 막지 않는다)
            elapsed = time.monotonic() - self._last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_call = time.monotonic()


# 모듈 공용 리미터 (백엔드-5 스크립트와 /name-check 가 같은 예산을 공유)
limiter = RateLimiter()


# ====================================================================
# XML 파싱 (순수 함수 — 네트워크 없이 테스트 가능)
# ====================================================================

# '|' 로 다중값이 오는 필드 (TODO.pdf 실측: GoodClassificationCode, ViennaCode)
MULTI_VALUE_FIELDS = {"GoodClassificationCode", "ViennaCode", "AsignProductMainCode",
                      "AsignProductSubCode", "SimilarCode"}


def _local_name(tag: str) -> str:
    """XML namespace 가 있어도 로컬 태그명만 반환한다."""
    return tag.rsplit("}", 1)[-1]


def _find_first(root: ET.Element, tag_name: str) -> ET.Element | None:
    return next((node for node in root.iter() if _local_name(node.tag) == tag_name), None)


def _parse_response_root(xml_text: str) -> ET.Element:
    """KIPRIS 공통 `<response>` envelope 를 엄격히 검증해 반환한다."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        raise KiprisProtocolError("KIPRIS 응답을 XML로 해석할 수 없습니다.") from None
    if _local_name(root.tag) != "response":
        raise KiprisProtocolError("KIPRIS 응답 envelope가 올바르지 않습니다.")
    if not any(_local_name(child.tag) == "body" for child in root):
        raise KiprisProtocolError("KIPRIS 응답에 body가 없습니다.")
    return root


def check_result_code(xml_text: str) -> None:
    """정상 envelope와 필수 resultCode=00을 검증한다."""
    root = _parse_response_root(xml_text)
    header = next(
        (child for child in root if _local_name(child.tag) == "header"),
        None,
    )
    if header is None:
        raise KiprisProtocolError("KIPRIS 응답에 header가 없습니다.")
    node = _find_first(header, "resultCode")
    if node is None or not (node.text or "").strip():
        raise KiprisProtocolError("KIPRIS 응답에 resultCode가 없습니다.")
    code = node.text.strip()
    if code != RESULT_CODE_OK:
        hint = RESULT_CODE_MESSAGES.get(code, "")
        raise KiprisError(
            f"KIPRIS 오류 resultCode={code} {hint}".strip(),
            result_code=code,
        )


# 항목 태그명. 오퍼레이션마다 항목 태그가 다르다 — 출원인 검색 등은 <item>,
# 상표명완전일치(trademarkNameMatchSearchInfo)는 <TradeMarkInfo> 다.
# 실측(TODO.pdf): <item> 만 찾던 기존 코드는 상표명완전일치 응답에서
# resultCode 00·59건이 와도 0건으로 파싱했다(위양성 "안전" 판정 — 실사용 위험).
ITEM_TAGS = ("item", "TradeMarkInfo")


def parse_items(xml_text: str) -> list[dict]:
    """
    응답의 항목 목록(<item> 또는 <TradeMarkInfo>)을 dict 리스트로 변환한다.

    - 자식 태그명 → 키, 텍스트 → 값
    - MULTI_VALUE_FIELDS 는 '|' 로 분리해 list[str] 로
    """
    check_result_code(xml_text)
    root = _parse_response_root(xml_text)
    items = []
    # root.iter() 로 전체를 순회하며 항목 태그만 골라 문서 순서를 유지한다.
    for item in root.iter():
        if _local_name(item.tag) not in ITEM_TAGS:
            continue
        row: dict = {}
        for child in item:
            child_tag = _local_name(child.tag)
            value = (child.text or "").strip()
            if child_tag in MULTI_VALUE_FIELDS:
                row[child_tag] = [v.strip() for v in value.split("|") if v.strip()]
            else:
                row[child_tag] = value
        items.append(row)
    return items


def parse_total_count(xml_text: str) -> Optional[int]:
    """
    응답의 <TotalSearchCount>(전체 검색 건수)를 반환. 없거나 숫자가 아니면 None.

    실측(TODO.pdf): 상표명완전일치 응답은 페이지네이션되며 items 는 한 페이지분
    (기본 30건)만 온다. 전체 건수는 항상 TotalSearchCount 에 담기므로
    /name-check 총계(total_found)는 len(items) 가 아니라 이 값을 써야 한다.
    """
    check_result_code(xml_text)
    root = _parse_response_root(xml_text)
    node = _find_first(root, "TotalSearchCount")
    if node is None or not (node.text or "").strip():
        return None
    try:
        total = int(node.text.strip())
    except ValueError:
        raise KiprisProtocolError("KIPRIS TotalSearchCount가 올바른 정수가 아닙니다.") from None
    if total < 0:
        raise KiprisProtocolError("KIPRIS TotalSearchCount가 음수입니다.")
    return total


def filter_registered(items: list[dict]) -> list[dict]:
    """ApplicationStatus == '등록' 만 채택 (등록/소멸/거절 중)."""
    return [it for it in items if it.get("ApplicationStatus") == "등록"]


def normalize_mark_title(value: object) -> str:
    """표시 문자열을 훼손하지 않으면서 명칭 동일성 비교용 표현을 만든다.

    KIPRIS 원문은 ASCII 대소문자, 전각 문자, 연속 공백이 섞일 수 있다. 이 차이만
    때문에 ``BBQ``와 ``bbq``를 다른 명칭으로 집계하지 않도록 NFKC/casefold와
    공백 정규화만 적용한다. 구두점이나 단어 사이 공백은 제거하지 않는다.
    """
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"\s+", " ", text)


def summarize_name_search(
    query: str,
    items: list[dict],
    total_found: Optional[int] = None,
    *,
    complete: Optional[bool] = None,
) -> dict:
    """
    상표명완전일치 결과 요약.

    실측 주의: '완전일치'여도 해당 문구를 포함한 상표까지 잡힌다
    ("삼성전자 SAM SUNG ELECTRONICS" 포함) → 정확 일치와 포함을 나눠 센다.

    total_found: 전체 검색 건수(TotalSearchCount). 미지정 시 수집된 items 수로 대체한다.
      실측(TODO.pdf): 응답은 페이지네이션되고 수집에는 안전 상한(NAME_SEARCH_MAX_ITEMS)이
      걸려 있어 items 가 전체보다 적을 수 있다. 그래서 total_found 는 항상
      TotalSearchCount 기준으로 받고, registered/exact 카운트는 실제 수집된 items
      기준이다(상한에 잘리면 등록/정확일치 건수가 실제보다 적게 집계될 수 있음).
    """
    registered = filter_registered(items)
    normalized_query = normalize_mark_title(query)
    exact_all = [
        it
        for it in items
        if normalized_query and normalize_mark_title(it.get("Title")) == normalized_query
    ]
    exact_registered = [it for it in exact_all if it.get("ApplicationStatus") == "등록"]
    status_counts: dict[str, int] = {}
    for item in items:
        status_name = str(item.get("ApplicationStatus") or "").strip() or "미상"
        status_counts[status_name] = status_counts.get(status_name, 0) + 1
    resolved_total = total_found if total_found is not None else len(items)
    if complete is None:
        complete = total_found is None or len(items) >= resolved_total
    return {
        "query": query,
        "total_found": resolved_total,
        "scanned_count": len(items),
        "registered_count": len(registered),
        "exact_registered_count": len(exact_registered),
        "exact_title_count": len(exact_all),
        "status_counts": status_counts,
        "complete": complete,
    }


# ====================================================================
# HTTP 호출
# ====================================================================

def _validate_kipris_url(url: str, url_env_name: str) -> None:
    """인증정보를 전송해도 되는 HTTPS KIPRIS 공식 URL인지 검증한다."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise KiprisConfigError(f"{url_env_name} 형식이 올바르지 않습니다.") from None
    if parsed.scheme.lower() != "https":
        raise KiprisConfigError(f"{url_env_name} 는 HTTPS URL이어야 합니다.")
    if (parsed.hostname or "").lower() not in ALLOWED_KIPRIS_HOSTS:
        raise KiprisConfigError(f"{url_env_name} 의 호스트가 KIPRIS 공식 호스트가 아닙니다.")
    if parsed.username or parsed.password or port not in (None, 443):
        raise KiprisConfigError(f"{url_env_name} 에 사용자정보나 비표준 포트를 넣을 수 없습니다.")


def _secure_kipris_download_url(url: str) -> str:
    """공식 호스트가 반환한 legacy HTTP 파일 링크를 HTTPS로만 승격한다."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise KiprisConfigError("KIPRIS 이미지 URL 형식이 올바르지 않습니다.") from None
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() == "http"
        and host in ALLOWED_KIPRIS_HOSTS
        and not parsed.username
        and not parsed.password
        and port in (None, 80)
    ):
        url = urlunsplit(("https", host, parsed.path, parsed.query, ""))
    _validate_kipris_url(url, "KIPRIS 이미지 URL")
    return url


def _require_config(url: str, url_env_name: str) -> None:
    if not ACCESS_KEY:
        raise KiprisConfigError(
            "KIPRIS_ACCESS_KEY 가 설정되지 않았습니다. "
            "KIPRIS Plus 에서 상품 신청 후 .env 에 키를 넣으세요 (커밋 금지)."
        )
    if not url:
        raise KiprisConfigError(
            f"{url_env_name} 가 설정되지 않았습니다. "
            f"API 통합설명서에서 오퍼레이션 URL 을 확인해 .env 에 넣으세요."
        )
    _validate_kipris_url(url, url_env_name)


# 모듈 공용 HTTP 클라이언트 — 호출마다 새로 만들면 TCP/TLS 커넥션을 매번
# 다시 맺는다. 재사용으로 커넥션 풀링 (httpx.Client 는 스레드 안전).
_http_client: Optional[httpx.Client] = None
_http_client_lock = threading.Lock()


def _get_client() -> httpx.Client:
    global _http_client
    with _http_client_lock:
        if _http_client is None:
            _http_client = httpx.Client(
                timeout=15,
                follow_redirects=False,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return _http_client


def close_client() -> None:
    """공용 HTTP 클라이언트 정리 (main.py lifespan shutdown 이 호출)."""
    global _http_client
    with _http_client_lock:
        if _http_client is not None:
            _http_client.close()
            _http_client = None


def _get(
    url: str,
    params: dict,
    auth_param: str = "accessKey",
    *,
    timeout: float | None = None,
) -> str:
    """리미터를 통과한 뒤 GET. 응답 본문(XML 텍스트) 반환.

    auth_param: 인증키를 실을 파라미터 이름. 상표명완전일치/openapi-rest 계열은
      accessKey(기본), getAdvancedSearch/kipo-api 계열은 ServiceKey 다(실측).
      값은 두 계열 모두 같은 KIPRIS_ACCESS_KEY 를 쓰고 파라미터 이름만 다르다 —
      잘못 붙이면 resultCode=10 (INVALID_REQUEST_PARAMETER_ERROR).
    """
    _validate_kipris_url(url, "KIPRIS API URL")
    limiter.acquire()
    try:
        request_kwargs: dict = {"params": {**params, auth_param: ACCESS_KEY}}
        if timeout is not None:
            request_kwargs["timeout"] = timeout
        resp = _get_client().get(url, **request_kwargs)
        resp.raise_for_status()
    except httpx.TimeoutException:
        raise KiprisNetworkError("KIPRIS 서비스 응답 시간이 초과되었습니다.") from None
    except httpx.HTTPStatusError:
        raise KiprisNetworkError("KIPRIS 서비스가 HTTP 오류를 반환했습니다.") from None
    except httpx.RequestError:
        raise KiprisNetworkError("KIPRIS 서비스와 통신하지 못했습니다.") from None
    return resp.text


# 상표명완전일치 페이지네이션 설정 (백엔드-7). 실측(TODO.pdf):
#  - 기본 30건/페이지 → docsCount 로 한 번에 더 받는다(docsCount=100 이면 59건 전부).
#  - TotalSearchCount 는 항상 전체 건수, SerialNumber 는 페이지마다 1부터 재시작.
#  - 다음 페이지는 docsStart(=이미 받은 건수+1)로 이어 받는다.
# 아래 두 상한은 월 1,000회 예산 보호용 — 초과하면 수집분으로만 진행한다.
NAME_SEARCH_DOCS_COUNT: int = 500   # 페이지당 요청 건수(docsCount) — 대부분 1회로 끝난다
NAME_SEARCH_MAX_ITEMS: int = 500    # 수집 상한 (초과분 버림 → summarize 는 total 로 별도 보고)
NAME_SEARCH_MAX_PAGES: int = 5      # 추가 호출 폭주 방지 상한


@dataclass(frozen=True)
class NameSearchResult:
    """호칭 검색 결과와 전체 스캔 완전성.

    기존 `items, total = name_match_search(...)` 호출은 `__iter__` 로 한 릴리스
    호환한다. 신규 호출자는 complete/scanned_count 를 직접 사용한다.
    """

    items: list[dict]
    total_found: int
    complete: bool

    @property
    def scanned_count(self) -> int:
        return len(self.items)

    def __iter__(self) -> Iterator[object]:
        yield self.items
        yield self.total_found


def _name_item_key(item: dict) -> str:
    """페이지 반복 판정에 사용할 안정적인 항목 표현."""
    application_no = str(item.get("ApplicationNumber") or "").strip()
    if application_no:
        return f"application:{application_no}"
    return json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)


def name_match_search(name: str) -> NameSearchResult:
    """
    상표명완전일치 검색 (백엔드-7).

    반환: (수집된 item dict 리스트, 전체 검색 건수 total_found).
      total_found 는 응답의 TotalSearchCount(없으면 수집 건수)로, 안전 상한에 잘려
      len(items) 가 total_found 보다 작을 수 있다.

    실측(TODO.pdf): 응답이 기본 30건/페이지라 docsCount 로 페이지를 키우고,
    len(items) < TotalSearchCount 면 docsStart 로 나머지 페이지를 이어 받는다.
    월 예산 보호를 위해 수집 상한/페이지 상한을 두고 초과 시 수집분으로만 진행한다.
    """
    _require_config(TM_NAME_SEARCH_URL, "KIPRIS_TM_NAME_SEARCH_URL")
    items: list[dict] = []
    seen_item_keys: set[str] = set()
    seen_page_signatures: set[tuple[str, ...]] = set()
    total: Optional[int] = None
    total_consistent = True
    start = 1   # docsStart 는 1-기반. 첫 페이지(1)는 파라미터를 생략한다.
    pages = 0
    while True:
        params: dict = {TM_NAME_PARAM: name, "docsCount": NAME_SEARCH_DOCS_COUNT}
        if start > 1:
            params["docsStart"] = start
        # 페이지 호출마다 _get 내장 limiter(예산+딜레이)를 그대로 통과한다.
        xml_text = _get(TM_NAME_SEARCH_URL, params)
        page_items = parse_items(xml_text)
        page_total = parse_total_count(xml_text)
        if total is None:
            total = page_total
        elif page_total is not None and page_total != total:
            total = max(total, page_total)
            total_consistent = False

        page_keys = tuple(_name_item_key(item) for item in page_items)
        if page_keys and page_keys in seen_page_signatures:
            break
        seen_page_signatures.add(page_keys)

        added = 0
        for item, item_key in zip(page_items, page_keys):
            # 실 응답에는 출원번호가 있으므로 중복 제거가 가능하다. 축약 테스트/비정상
            # 응답처럼 번호가 없다면 페이지별 SerialNumber 재시작을 중복으로 오판하지 않는다.
            has_application_no = bool(str(item.get("ApplicationNumber") or "").strip())
            if has_application_no and item_key in seen_item_keys:
                continue
            if has_application_no:
                seen_item_keys.add(item_key)
            if len(items) >= NAME_SEARCH_MAX_ITEMS:
                break
            items.append(item)
            added += 1
        if total is not None and len(items) > total:
            total = len(items)
            total_consistent = False
        pages += 1
        # --- 종료 조건 ---
        if not page_items:
            break  # 빈 페이지 → 더 이상 없음
        if total is not None and len(items) >= total:
            break  # 전체 건수 도달
        if len(items) >= NAME_SEARCH_MAX_ITEMS or pages >= NAME_SEARCH_MAX_PAGES:
            break  # 월 예산 보호 상한 — 수집분으로만 진행
        if added == 0:
            break  # 서버가 같은/중복 페이지만 반복하면 추가 호출하지 않는다
        start += len(page_items)  # 다음 페이지 시작 위치
    resolved_total = total if total is not None else len(items)
    complete = total is not None and len(items) >= resolved_total and total_consistent
    return NameSearchResult(items=items, total_found=resolved_total, complete=complete)


# ====================================================================
# 항목별검색 getAdvancedSearch (백엔드-6 본 수집)
#
# 실측 확정(호출 소진분 재분석):
#  - 상표명완전일치와 다른 API 계열(kipo-api/kipi). 인증 파라미터는 ServiceKey.
#  - 30개 불리언 플래그(행정상태 8 + 표장유형 9 + 표장구성 13)를 "전부" 실어야 한다.
#    일부만 넘기면 resultCode=10(INVALID_REQUEST_PARAMETER_ERROR). 값은 "true"/"false".
#  - 응답은 camelCase 필드, 항목 태그는 <item>, 전체 건수는 <totalCount>.
#    페이징 요청 파라미터명은 미확인 → 보내지 않고 서버 기본값(numOfRows=20)에 맡긴다.
#  - 유사군(similarityCode) 필드가 없다 → normalize 에서 빈 배열(후속 보강 TODO).
# ====================================================================

# 행정상태 8
ADVANCED_ADMIN_STATUS_FLAGS: tuple[str, ...] = (
    "application", "registration", "refused", "expiration",
    "withdrawal", "publication", "cancel", "abandonment",
)
# 표장유형 9
ADVANCED_MARK_TYPE_FLAGS: tuple[str, ...] = (
    "trademark", "serviceMark", "businessEmblem", "collectiveMark",
    "geoOrgMark", "trademarkServiceMark", "certMark", "geoCertMark",
    "internationalMark",
)
# 표장구성 13
ADVANCED_COMPOSITION_FLAGS: tuple[str, ...] = (
    "character", "figure", "compositionCharacter", "figureComposition",
    "fragrance", "sound", "color", "colorMixed", "dimension",
    "hologram", "invisible", "motion", "visual",
)
# 전체 30개 — 요청에 반드시 전부 실어야 한다(일부만 넘기면 resultCode=10).
ADVANCED_ALL_FLAGS: tuple[str, ...] = (
    ADVANCED_ADMIN_STATUS_FLAGS + ADVANCED_MARK_TYPE_FLAGS + ADVANCED_COMPOSITION_FLAGS
)

# 본 수집 기본 필터(실측 성공 조합):
#  - 행정상태: 등록만(registration)         ← 서버측에서 미등록을 걸러준다
#  - 표장구성: 도형 + 도형복합(figure, figureComposition)만
#  - 표장유형: 전부 허용(9종 모두 true)
# 호출자가 정책을 바꾸려면 advanced_search 에 다른 true_flags 를 넘긴다.
DEFAULT_ADVANCED_TRUE_FLAGS: frozenset[str] = frozenset(
    {"registration", "figure", "figureComposition", *ADVANCED_MARK_TYPE_FLAGS}
)


def build_advanced_flags(
    true_flags: "frozenset[str] | set[str]" = DEFAULT_ADVANCED_TRUE_FLAGS,
) -> dict[str, str]:
    """30개 불리언 플래그를 전부 담은 요청 dict 를 만든다.

    true_flags 에 든 플래그만 "true", 나머지는 "false"(문자열). 일부만 넘기면
    resultCode=10 이 오므로 항상 30개를 다 싣는다.
    """
    return {f: ("true" if f in true_flags else "false") for f in ADVANCED_ALL_FLAGS}


# 항목별검색 페이징(공식 문서 실측): pageNo(페이지 번호), numOfRows(페이지당 건수,
# 기본 30 · 최대 500). 상표명완전일치 계열의 docsStart/docsCount 와 이름이 다르다.
# 한 페이지를 크게 받을수록 같은 건수를 적은 호출로 수집한다 — 월 1,000회 예산의 핵심.
ADVANCED_MAX_ROWS: int = 500      # 공식 상한
ADVANCED_DEFAULT_ROWS: int = 500  # 예산 절약을 위해 항상 상한으로 받는다
ADVANCED_MAX_PAGES: int = 10      # 호출 폭주 방지 상한(출원인당 최대 5,000건)


def advanced_search_raw(
    applicant: str,
    true_flags: "frozenset[str] | set[str]" = DEFAULT_ADVANCED_TRUE_FLAGS,
    page_no: int = 1,
    num_of_rows: int = ADVANCED_DEFAULT_ROWS,
    request_timeout: float | None = None,
) -> str:
    """항목별검색(getAdvancedSearch) — 응답 원본 XML 텍스트를 그대로 반환한다(백엔드-6).

    상표명완전일치와 달리 인증 파라미터가 ServiceKey 이고, 30개 불리언 플래그를 전부
    실어 보낸다. 원본 선저장(DoD Ⓐ)을 위해 raw 를 분리해 둔다 — advanced_search 는
    이 원본을 파싱·정규화할 뿐이다. 파싱 버그로 재실행해도 이 원본에서 다시 파싱할 수 있다.
    """
    _require_config(ADVANCED_SEARCH_URL, "KIPRIS_APPLICANT_SEARCH_URL")
    rows = max(1, min(num_of_rows, ADVANCED_MAX_ROWS))
    params = {
        APPLICANT_PARAM: applicant,
        **build_advanced_flags(true_flags),
        "pageNo": str(max(1, page_no)),
        "numOfRows": str(rows),
    }
    return _get(
        ADVANCED_SEARCH_URL,
        params,
        auth_param="ServiceKey",
        timeout=request_timeout,
    )


def parse_advanced_total_count(xml_text: str) -> Optional[int]:
    """항목별검색 응답의 <totalCount>(전체 건수)를 반환. 없거나 숫자가 아니면 None.

    상표명완전일치의 <TotalSearchCount> 와 태그명이 다르다(실측: camelCase totalCount).
    """
    check_result_code(xml_text)
    root = _parse_response_root(xml_text)
    node = _find_first(root, "totalCount")
    if node is None or not (node.text or "").strip():
        return None
    try:
        total = int(node.text.strip())
    except ValueError:
        raise KiprisProtocolError("KIPRIS totalCount가 올바른 정수가 아닙니다.") from None
    if total < 0:
        raise KiprisProtocolError("KIPRIS totalCount가 음수입니다.")
    return total


def normalize_advanced_item(item: dict) -> dict:
    """항목별검색(camelCase) 항목을 파이프라인 정규 키(기존 PascalCase 계약)로 변환한다.

    - viennaCode/classificationCode 는 '|' 다중값 → 리스트로 분해
    - 이미지 URL 은 bigDrawing(큰 이미지) 우선, 없으면 drawing → ImagePath
    - title 은 빈 문자열도 그대로 둔다(item_to_row 가 빈 값을 None 으로 처리)
    - SimilarCode(유사군)는 빈 배열
      TODO(백엔드-6): getAdvancedSearch 응답엔 유사군(similarityCode)이 없다.
      서지정보 오퍼레이션으로 후속 보강한다.

    이미 정규 키(PascalCase)로 들어온 항목(레거시 name-match 원본·mock 재파싱)은 그대로
    통과시킨다 — 정규화는 camelCase 원 응답에만 적용해, 두 입력 형식을 한 파이프라인이 쓴다.
    """
    if "ApplicationNumber" in item and "applicationNumber" not in item:
        return item  # 이미 정규 키 → 그대로

    def _multi(value: str) -> list[str]:
        return [v.strip() for v in (value or "").split("|") if v.strip()]

    return {
        "ApplicationNumber": item.get("applicationNumber", ""),
        "ApplicationStatus": item.get("applicationStatus", ""),
        "Title": item.get("title", ""),
        "RegistrationNumber": item.get("registrationNumber", ""),
        "ApplicationDate": item.get("applicationDate", ""),
        "RegistrationDate": item.get("registrationDate", ""),
        "ApplicantName": item.get("applicantName", ""),
        # 등록권리자명 슬롯 — getAdvancedSearch 는 regPrivilegeName 로 온다(실측 item 필드).
        "RegistrationRightholderName": item.get("regPrivilegeName", ""),
        "ViennaCode": _multi(item.get("viennaCode", "")),
        "GoodClassificationCode": _multi(item.get("classificationCode", "")),
        "SimilarCode": [],  # TODO(백엔드-6): 유사군 부재 → 서지정보 오퍼레이션으로 후속 보강
        "ImagePath": item.get("bigDrawing") or item.get("drawing") or "",
    }


def advanced_search(
    applicant: str,
    true_flags: "frozenset[str] | set[str]" = DEFAULT_ADVANCED_TRUE_FLAGS,
    page_no: int = 1,
    num_of_rows: int = ADVANCED_DEFAULT_ROWS,
) -> tuple[list[dict], int]:
    """항목별검색(getAdvancedSearch) — (정규화된 item 리스트, 전체 건수)를 반환한다(백엔드-6).

    한 페이지(numOfRows, 기본이자 상한 500)를 받고 전체 건수(totalCount)를 함께 준다.
    총 건수가 한 페이지를 넘으면 호출자가 page_no 를 올려 이어 받는다 — 수집
    파이프라인은 원본 선저장(DoD Ⓐ) 때문에 페이지마다 raw 를 따로 저장해야 하므로
    여기서 페이지를 합치지 않는다(collect_pipeline.search_batch 참조).
    """
    xml_text = advanced_search_raw(applicant, true_flags, page_no, num_of_rows)
    items = [normalize_advanced_item(it) for it in parse_items(xml_text)]
    total = parse_advanced_total_count(xml_text)
    return items, (total if total is not None else len(items))


# ====================================================================
# 서지상세정보 getBibliographyDetailInfoSearch (백엔드-6 유사군 보강)
#
# 실측 확정(2026-07-10):
#  - getAdvancedSearch 와 같은 kipo-api/kipi 계열, 인증 파라미터 ServiceKey.
#  - 요청 파라미터는 applicationNumber 하나뿐 → 레코드당 1회 호출(쿼터 1 소모).
#  - 본 수집 소스(getAdvancedSearch)에는 유사군이 없다. 이 오퍼레이션이 유일하게
#    출원번호로 유사군·지정상품을 준다(X4 상품 견련성 축·다빈-1 라벨표 학습의 경로).
#  - 응답은 평면 <item> 이 아니라 중첩 구조라 parse_items 로는 못 읽는다 → 전용 파서.
#
# 예산 주의: 레코드당 1회다. 500건 보강 = 500회(월 예산 950의 절반). 기본 동작이
#           아니라 옵트인이어야 한다(collect_pipeline --enrich-biblio).
# ====================================================================

def _child_text(parent: ET.Element, tag: str) -> str:
    """직계 자식 태그의 텍스트를 공백 정리해 반환한다(없으면 빈 문자열)."""
    node = parent.find(tag)
    return (node.text or "").strip() if node is not None else ""


def bibliography_detail_raw(application_number: str) -> str:
    """서지상세(getBibliographyDetailInfoSearch) — 응답 원본 XML 텍스트를 그대로 반환한다.

    인증 파라미터는 ServiceKey(getAdvancedSearch 와 같은 계열), 요청 파라미터는
    applicationNumber 하나뿐이다. 원본 선저장(DoD Ⓐ)을 위해 raw 를 분리해 둔다 —
    bibliography_detail 은 이 원본을 파싱할 뿐이다.
    """
    _require_config(BIBLIO_DETAIL_URL, "KIPRIS_BIBLIO_DETAIL_URL")
    return _get(
        BIBLIO_DETAIL_URL,
        {"applicationNumber": application_number},
        auth_param="ServiceKey",
    )


def parse_bibliography_detail(xml_text: str) -> dict:
    """서지상세 응답을 파싱한다(백엔드-6 유사군 보강).

    응답은 중첩 구조라 parse_items(평면 item)로는 못 읽어 전용 파서를 둔다.
    반환 dict(파이프라인이 쓰기 쉬운 정규 키):
      - similarity_codes: list[str]  유사군코드(similarCode, 정렬·중복 제거).
        비어 있으면 지정상품 subCode 로 폴백(실측상 동일 집합).
      - nice_classes:     list[int]  지정상품 mainCode(류)를 int 로(정렬·중복 제거, 비숫자 버림).
      - vienna_codes:     list[str]  비엔나 코드(문서 순서, 빈 값 제외).
      - goods:            list[dict] 지정상품 {mainCode(류), subCode(유사군), productName(상품명)}.
      - mark_type:        str|None   trademarkDivisionCode를 공백 정규화한 값.
                                      값이 없으면 None.
      - register_status:  str|None   registerStatus.
      - registration_number: str|None
      - image_url:        str|None   sampleImageInfo/path(큰 이미지) 우선, 없으면 smallPath.
      - application_number: str|None  biblioSummaryInfo/applicationNumber.

    resultCode != 00 이면 KiprisError(check_result_code 를 먼저 통과시킨다).
    """
    check_result_code(xml_text)
    root = ET.fromstring(xml_text)

    # 유사군: similarityCodeInfo/similarCode (정렬·중복 제거)
    similarity = sorted({
        (el.text or "").strip()
        for el in root.findall(".//similarityCodeInfo/similarCode")
        if (el.text or "").strip()
    })

    # 지정상품(asignProduct) — 류(mainCode)·유사군 폴백(subCode)·상품명 재료
    goods: list[dict] = []
    nice: set[int] = set()
    sub_codes: set[str] = set()
    for ap in root.findall(".//asignProduct"):
        main = _child_text(ap, "mainCode")
        sub = _child_text(ap, "subCode")
        goods.append({
            "mainCode": main,
            "subCode": sub,
            "productName": _child_text(ap, "productName"),
        })
        if main.isdigit():
            nice.add(int(main))
        if sub:
            sub_codes.add(sub)
    if not similarity:
        similarity = sorted(sub_codes)  # 폴백: 실측상 유사군 집합과 동일

    # 비엔나 코드 (문서 순서 유지, 빈 값 제외)
    vienna = [
        (el.text or "").strip()
        for el in root.findall(".//viennaCodeInfo/viennaCode")
        if (el.text or "").strip()
    ]

    # 서지요약 — 표장구분/등록상태/등록번호/출원번호
    biblio = root.find(".//biblioSummaryInfo")
    mark_type = register_status = registration_number = application_number = None
    if biblio is not None:
        # trademarkDivisionCode 는 공백이 여러 칸 섞여 온다 → 연속 공백을 한 칸으로.
        mark_type = " ".join(_child_text(biblio, "trademarkDivisionCode").split()) or None
        register_status = _child_text(biblio, "registerStatus") or None
        registration_number = _child_text(biblio, "registrationNumber") or None
        application_number = _child_text(biblio, "applicationNumber") or None

    # 이미지 URL — path(큰 이미지) 우선, 없으면 smallPath (둘 다 fileToss 일회성 링크)
    image_url = None
    sample = root.find(".//sampleImageInfo")
    if sample is not None:
        image_url = _child_text(sample, "path") or _child_text(sample, "smallPath") or None

    return {
        "similarity_codes": similarity,
        "nice_classes": sorted(nice),
        "vienna_codes": vienna,
        "goods": goods,
        "mark_type": mark_type,
        "register_status": register_status,
        "registration_number": registration_number,
        "image_url": image_url,
        "application_number": application_number,
    }


def bibliography_detail(application_number: str) -> dict:
    """서지상세 — 원본 XML 을 받아 parse_bibliography_detail 로 파싱해 돌려준다.

    원본 선저장이 필요한 파이프라인은 bibliography_detail_raw → save → parse 를
    직접 조합한다(collect_pipeline.enrich_item). 이 함수는 raw 저장이 필요 없는 호출용.
    """
    return parse_bibliography_detail(bibliography_detail_raw(application_number))


def download_file_now(url: str, dest: Path) -> Path:
    """
    fileToss.jsp 류의 일회성 링크를 즉시 다운로드한다.

    주의: 이 링크는 시한부다 — 응답에서 받자마자 호출할 것 (모아뒀다 열면 만료).
    """
    url = _secure_kipris_download_url(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # 파일 다운로드는 본문이 커 검색 API 보다 여유 있는 타임아웃을 준다.
    try:
        resp = _get_client().get(url, timeout=30)
        resp.raise_for_status()
    except httpx.TimeoutException:
        raise KiprisNetworkError("KIPRIS 이미지 다운로드 시간이 초과되었습니다.") from None
    except httpx.HTTPStatusError:
        raise KiprisNetworkError("KIPRIS 이미지 서버가 HTTP 오류를 반환했습니다.") from None
    except httpx.RequestError:
        raise KiprisNetworkError("KIPRIS 이미지를 다운로드하지 못했습니다.") from None
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(resp.content)
    os.replace(tmp, dest)
    return dest
