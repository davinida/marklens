"""
KIPRIS Plus Open API 클라이언트 (백엔드-5 수집 / 백엔드-7 호칭 검색 공용).

팀 공통 규칙(TODO.pdf)을 코드로 강제한다:
- 모든 호출에 호출 카운터 + 초당 딜레이 (상품별 월 1,000회 / 초당 50회)
- 인증키는 .env 로만 주입 (커밋 금지 — 키 공유는 약관 위반, 각자 발급)
- fileToss.jsp 형태의 파일 링크는 일회성/시한부 → 응답 수신 즉시 다운로드

오퍼레이션 URL/파라미터명은 KIPRIS "API 통합설명서"에서 확인해 .env 에 넣는다
(사이트 상단 링크에서 다운로드. 상표 출원속보: 오퍼레이션 54개):
    KIPRIS_ACCESS_KEY               = 상품 인증키 (마이페이지)
    KIPRIS_TM_NAME_SEARCH_URL       = 상표명완전일치(trademarkNameMatchSearchInfo) 오퍼레이션 URL
    KIPRIS_TM_NAME_PARAM            = 상표명 파라미터명 (기본 trademarkName)
    KIPRIS_APPLICANT_SEARCH_URL     = 출원인 검색 오퍼레이션 URL (백엔드-5)
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
TM_NAME_SEARCH_URL: str = os.getenv("KIPRIS_TM_NAME_SEARCH_URL", "")
TM_NAME_PARAM: str = os.getenv("KIPRIS_TM_NAME_PARAM", "trademarkName")
APPLICANT_SEARCH_URL: str = os.getenv("KIPRIS_APPLICANT_SEARCH_URL", "")
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
RESULT_CODE_MESSAGES = {
    "31": "상품 미신청 또는 사용 기간 만료 (DEADLINE_HAS_EXPIRED_ERROR) — "
          "KIPRIS Plus 마이페이지에서 상품 신청 상태와 키를 확인하세요.",
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


def parse_items(xml_text: str) -> list[dict]:
    """
    응답의 <item> 목록을 dict 리스트로 변환한다.

    - 자식 태그명 → 키, 텍스트 → 값
    - MULTI_VALUE_FIELDS 는 '|' 로 분리해 list[str] 로
    """
    check_result_code(xml_text)
    root = ET.fromstring(xml_text)
    items = []
    for item in root.iter("item"):
        row: dict = {}
        for child in item:
            value = (child.text or "").strip()
            if child.tag in MULTI_VALUE_FIELDS:
                row[child.tag] = [v.strip() for v in value.split("|") if v.strip()]
            else:
                row[child.tag] = value
        items.append(row)
    return items


def filter_registered(items: list[dict]) -> list[dict]:
    """ApplicationStatus == '등록' 만 채택 (등록/소멸/거절 중)."""
    return [it for it in items if it.get("ApplicationStatus") == "등록"]


def summarize_name_search(query: str, items: list[dict]) -> dict:
    """
    상표명완전일치 결과 요약.

    실측 주의: '완전일치'여도 해당 문구를 포함한 상표까지 잡힌다
    ("삼성전자 SAM SUNG ELECTRONICS" 포함) → 정확 일치와 포함을 나눠 센다.
    """
    registered = filter_registered(items)
    exact = [it for it in registered if it.get("Title", "").strip() == query.strip()]
    return {
        "query": query,
        "total_found": len(items),
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


def _get(url: str, params: dict) -> str:
    """리미터를 통과한 뒤 GET. 응답 본문(XML 텍스트) 반환."""
    limiter.acquire()
    with httpx.Client(timeout=15) as client:
        resp = client.get(url, params={**params, "accessKey": ACCESS_KEY})
        resp.raise_for_status()
        return resp.text


def name_match_search(name: str) -> list[dict]:
    """상표명완전일치 검색 (백엔드-7). 반환: item dict 리스트."""
    _require_config(TM_NAME_SEARCH_URL, "KIPRIS_TM_NAME_SEARCH_URL")
    xml_text = _get(TM_NAME_SEARCH_URL, {TM_NAME_PARAM: name})
    return parse_items(xml_text)


def applicant_search(applicant: str) -> list[dict]:
    """출원인(회사명) 검색 (백엔드-5). 반환: item dict 리스트."""
    _require_config(APPLICANT_SEARCH_URL, "KIPRIS_APPLICANT_SEARCH_URL")
    xml_text = _get(APPLICANT_SEARCH_URL, {APPLICANT_PARAM: applicant})
    return parse_items(xml_text)


def download_file_now(url: str, dest: Path) -> Path:
    """
    fileToss.jsp 류의 일회성 링크를 즉시 다운로드한다.

    주의: 이 링크는 시한부다 — 응답에서 받자마자 호출할 것 (모아뒀다 열면 만료).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest
