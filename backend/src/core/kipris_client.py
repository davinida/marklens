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
    KIPRIS_BASE_URL                 = 공통 호스트 (기본 http://plus.kipris.or.kr/)
    KIPRIS_TM_NAME_SEARCH_URL       = 상표명완전일치 오퍼레이션 URL 오버라이드(선택,
                                      미설정 시 BASE_URL + 경로 상수로 자동 조합)
    KIPRIS_TM_NAME_PARAM            = 상표명 파라미터명 (기본 trademarkNameMatch)
                                      실측: trademarkName 을 주면 resultCode 11
                                      (NO_MANDATORY_REQUEST_PARAMETERS_ERROR)
    KIPRIS_APPLICANT_SEARCH_URL     = 항목별검색(getAdvancedSearch) URL 오버라이드(선택)
    KIPRIS_APPLICANT_PARAM          = 출원인 파라미터명 (기본 applicantName)
"""

import json
import os
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from . import paths

# ====================================================================
# 설정 (.env)
# ====================================================================

ACCESS_KEY: str = os.getenv("KIPRIS_ACCESS_KEY", "")

# 공통 호스트. 오퍼레이션 경로 상수와 조합해 전체 URL 을 만든다. 두 API 계열
# (openapi/rest 상표명완전일치 · kipo-api/kipi getAdvancedSearch)이 이 호스트를 공유한다.
KIPRIS_BASE_URL: str = os.getenv("KIPRIS_BASE_URL", "http://plus.kipris.or.kr/")

# 오퍼레이션 경로(호스트 제외) — 실측으로 확정한 검증값.
TM_NAME_SEARCH_PATH: str = (
    "openapi/rest/trademarkInfoSearchService/trademarkNameMatchSearchInfo"
)
ADVANCED_SEARCH_PATH: str = "kipo-api/kipi/trademarkInfoSearchService/getAdvancedSearch"


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

# 월 호출 예산. 공식 한도는 1,000회지만 수동 실험/재시도 여유로 50회를 남긴다.
MONTHLY_CALL_BUDGET: int = int(os.getenv("KIPRIS_MONTHLY_BUDGET", "950"))

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


class CallBudgetExceeded(KiprisError):
    """월 호출 예산 초과 — 다음 달 1일 초기화까지 호출 금지."""


# ====================================================================
# 호출 카운터 + 딜레이
# ====================================================================

class RateLimiter:
    """
    월 누적 카운터(파일 영속) + 요청 간 최소 간격을 강제한다.

    사용: limiter.acquire() 를 API 호출 직전에 부른다.
    파일 포맷: {"2026-07": 123, ...}  (월별 누적 호출 수)
    """

    def __init__(
        self,
        counter_path: Path = CALL_COUNTER_PATH,
        monthly_budget: int = MONTHLY_CALL_BUDGET,
        min_interval: float = MIN_CALL_INTERVAL_SEC,
    ):
        self.counter_path = counter_path
        self.monthly_budget = monthly_budget
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last_call = 0.0

    @staticmethod
    def _month_key() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def _load(self) -> dict:
        if self.counter_path.exists():
            try:
                return json.loads(self.counter_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def used_this_month(self) -> int:
        return int(self._load().get(self._month_key(), 0))

    def acquire(self) -> None:
        """예산 검사 + 카운터 증가 + 초당 딜레이. 초과 시 CallBudgetExceeded."""
        with self._lock:
            counts = self._load()
            key = self._month_key()
            used = int(counts.get(key, 0))
            if used >= self.monthly_budget:
                raise CallBudgetExceeded(
                    f"이번 달 KIPRIS 호출 예산({self.monthly_budget}회)을 다 썼습니다 "
                    f"(사용: {used}). 매월 1일 초기화."
                )
            counts[key] = used + 1
            self.counter_path.parent.mkdir(parents=True, exist_ok=True)
            self.counter_path.write_text(
                json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            # 초당 제한 — 마지막 호출로부터 최소 간격 보장
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


def check_result_code(xml_text: str) -> None:
    """resultCode != 00 이면 KiprisError. 헤더가 없으면 통과(오퍼레이션별 편차 방어)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise KiprisError(f"KIPRIS 응답이 XML이 아닙니다: {e}")
    node = root.find(".//resultCode")
    if node is None or node.text is None:
        return
    code = node.text.strip()
    if code != RESULT_CODE_OK:
        msg_node = root.find(".//resultMsg")
        detail = (msg_node.text or "").strip() if msg_node is not None else ""
        hint = RESULT_CODE_MESSAGES.get(code, "")
        raise KiprisError(
            f"KIPRIS 오류 resultCode={code} {detail} {hint}".strip(),
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
    root = ET.fromstring(xml_text)
    items = []
    # root.iter() 로 전체를 순회하며 항목 태그만 골라 문서 순서를 유지한다.
    for item in root.iter():
        if item.tag not in ITEM_TAGS:
            continue
        row: dict = {}
        for child in item:
            value = (child.text or "").strip()
            if child.tag in MULTI_VALUE_FIELDS:
                row[child.tag] = [v.strip() for v in value.split("|") if v.strip()]
            else:
                row[child.tag] = value
        items.append(row)
    return items


def parse_total_count(xml_text: str) -> Optional[int]:
    """
    응답의 <TotalSearchCount>(전체 검색 건수)를 반환. 없거나 숫자가 아니면 None.

    실측(TODO.pdf): 상표명완전일치 응답은 페이지네이션되며 items 는 한 페이지분
    (기본 30건)만 온다. 전체 건수는 항상 TotalSearchCount 에 담기므로
    /name-check 총계(total_found)는 len(items) 가 아니라 이 값을 써야 한다.
    """
    root = ET.fromstring(xml_text)
    node = root.find(".//TotalSearchCount")
    if node is None or not (node.text or "").strip():
        return None
    try:
        return int(node.text.strip())
    except ValueError:
        return None


def filter_registered(items: list[dict]) -> list[dict]:
    """ApplicationStatus == '등록' 만 채택 (등록/소멸/거절 중)."""
    return [it for it in items if it.get("ApplicationStatus") == "등록"]


def summarize_name_search(
    query: str, items: list[dict], total_found: Optional[int] = None
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
    exact = [it for it in registered if it.get("Title", "").strip() == query.strip()]
    return {
        "query": query,
        "total_found": total_found if total_found is not None else len(items),
        "registered_count": len(registered),
        "exact_registered_count": len(exact),
    }


# ====================================================================
# HTTP 호출
# ====================================================================

def _require_config(url: str, url_env_name: str) -> None:
    if not ACCESS_KEY:
        raise KiprisError(
            "KIPRIS_ACCESS_KEY 가 설정되지 않았습니다. "
            "KIPRIS Plus 에서 상품 신청 후 .env 에 키를 넣으세요 (커밋 금지)."
        )
    if not url:
        raise KiprisError(
            f"{url_env_name} 가 설정되지 않았습니다. "
            f"API 통합설명서에서 오퍼레이션 URL 을 확인해 .env 에 넣으세요."
        )


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
                follow_redirects=True,
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


def _get(url: str, params: dict, auth_param: str = "accessKey") -> str:
    """리미터를 통과한 뒤 GET. 응답 본문(XML 텍스트) 반환.

    auth_param: 인증키를 실을 파라미터 이름. 상표명완전일치/openapi-rest 계열은
      accessKey(기본), getAdvancedSearch/kipo-api 계열은 ServiceKey 다(실측).
      값은 두 계열 모두 같은 KIPRIS_ACCESS_KEY 를 쓰고 파라미터 이름만 다르다 —
      잘못 붙이면 resultCode=10 (INVALID_REQUEST_PARAMETER_ERROR).
    """
    limiter.acquire()
    resp = _get_client().get(url, params={**params, auth_param: ACCESS_KEY})
    resp.raise_for_status()
    return resp.text


# 상표명완전일치 페이지네이션 설정 (백엔드-7). 실측(TODO.pdf):
#  - 기본 30건/페이지 → docsCount 로 한 번에 더 받는다(docsCount=100 이면 59건 전부).
#  - TotalSearchCount 는 항상 전체 건수, SerialNumber 는 페이지마다 1부터 재시작.
#  - 다음 페이지는 docsStart(=이미 받은 건수+1)로 이어 받는다.
# 아래 두 상한은 월 1,000회 예산 보호용 — 초과하면 수집분으로만 진행한다.
NAME_SEARCH_DOCS_COUNT: int = 500   # 페이지당 요청 건수(docsCount) — 대부분 1회로 끝난다
NAME_SEARCH_MAX_ITEMS: int = 500    # 수집 상한 (초과분 버림 → summarize 는 total 로 별도 보고)
NAME_SEARCH_MAX_PAGES: int = 5      # 추가 호출 폭주 방지 상한


def name_match_search(name: str) -> tuple[list[dict], int]:
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
    total: Optional[int] = None
    start = 1   # docsStart 는 1-기반. 첫 페이지(1)는 파라미터를 생략한다.
    pages = 0
    while True:
        params: dict = {TM_NAME_PARAM: name, "docsCount": NAME_SEARCH_DOCS_COUNT}
        if start > 1:
            params["docsStart"] = start
        # 페이지 호출마다 _get 내장 limiter(예산+딜레이)를 그대로 통과한다.
        xml_text = _get(TM_NAME_SEARCH_URL, params)
        page_items = parse_items(xml_text)
        if total is None:
            total = parse_total_count(xml_text)
        items.extend(page_items)
        pages += 1
        # --- 종료 조건 ---
        if not page_items:
            break  # 빈 페이지 → 더 이상 없음
        if total is not None and len(items) >= total:
            break  # 전체 건수 도달
        if len(items) >= NAME_SEARCH_MAX_ITEMS or pages >= NAME_SEARCH_MAX_PAGES:
            break  # 월 예산 보호 상한 — 수집분으로만 진행
        start += len(page_items)  # 다음 페이지 시작 위치
    return items, (total if total is not None else len(items))


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
    return _get(ADVANCED_SEARCH_URL, params, auth_param="ServiceKey")


def parse_advanced_total_count(xml_text: str) -> Optional[int]:
    """항목별검색 응답의 <totalCount>(전체 건수)를 반환. 없거나 숫자가 아니면 None.

    상표명완전일치의 <TotalSearchCount> 와 태그명이 다르다(실측: camelCase totalCount).
    """
    root = ET.fromstring(xml_text)
    node = root.find(".//totalCount")
    if node is None or not (node.text or "").strip():
        return None
    try:
        return int(node.text.strip())
    except ValueError:
        return None


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


def download_file_now(url: str, dest: Path) -> Path:
    """
    fileToss.jsp 류의 일회성 링크를 즉시 다운로드한다.

    주의: 이 링크는 시한부다 — 응답에서 받자마자 호출할 것 (모아뒀다 열면 만료).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    # 파일 다운로드는 본문이 커 검색 API 보다 여유 있는 타임아웃을 준다.
    resp = _get_client().get(url, timeout=30)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest
