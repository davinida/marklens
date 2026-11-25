"""유명 상표 등록부의 대표 표장 후보 찾기 — KIPRIS 항목별검색(통합 모델 설계 §7-14-10).

대표 로고가 없는 기존 브랜드와 새로 넣을 브랜드의 등록 표장을 KIPRIS 에서 찾아 후보 목록
(ml/data/staging/famous_candidates.json)과 썸네일(저장소 밖 보관 폴더)로 남긴다. 고르는 일은 사람이
고르기 도구(`ml/scripts/famous_curate.py` 가 만드는 curate.html)에서 한다. **DB·색인·등록부에는
아무것도 넣지 않는다** — 받기(서지·견본·승격)는 다음 단계다.

    ml/venv/bin/python ml/scripts/famous_candidates.py plan      # 호출 0 — 브랜드별 검색 계획
    ml/venv/bin/python ml/scripts/famous_candidates.py status    # 호출 0 — 지금까지 찾은 것
    ml/venv/bin/python ml/scripts/famous_candidates.py rebuild   # 호출 0 — 원본에서 후보 다시 뽑기
    TEAMMATE_KIPRIS_KEY=… KIPRIS_DAILY_BUDGET=0 ml/venv/bin/python \\
        ml/scripts/famous_candidates.py run --key-env TEAMMATE_KIPRIS_KEY \\
        --counter ml/data/kipris_counters/<키 이름>/kipris_call_count.json \\
        --max-calls 300 [--only 브랜드 …]

방법(브랜드당 호출 MAX_CALLS_PER_BRAND 이하)
    (가) 상표명칭 검색   표기마다 출원인 조건 없이, 등록 상태만, 첫 쪽(500건). 권리자가 지주사나
                        해외 본사일 수 있어 출원인으로 거르지 않는다(순서만 매긴다).
    (나) 출원인 검색     글자 없는 로고는 (가)로 못 찾으므로, 그 브랜드의 출원인으로 등록된 도형
                        표장(표장구성 = 도형)을 찾는다(2쪽까지). 출원인 = 2026-10-12 판
                        famous_brands.txt(커밋 049ddd9)의 출원인명(없으면 지금 표의 출원인) +
                        (가) 결과에서 가장 많이 나온 출원인. 출원인 검색은 낱말 일치라 결과는
                        출원인(또는 등록권리자)명이 같은 것만 남긴다.
    후보                응답마다 앞 순위만 고르고(썸네일은 응답 직후에 받는다 — 견본 링크가 시한부)
                        출원번호로 중복을 없앤 뒤 브랜드당 MAX_CANDIDATES 건. DB 에 이미 있으면
                        "DB에 있음"으로 표시(썸네일은 받지 않는다).

키: 환경 변수 **이름**만 받는다(--key-env). 값은 kipris_client.ACCESS_KEY 에만 넣고 어디에도 쓰지
않는다 — 저장하는 글(상태 JSON·원본 XML·오류 문구)은 쓰기 전에 키 값이 없는지 본다. --key-env 없이는
호출하지 않는다(.env 의 공용 키로 떨어지지 않게). 호출 수는 키별 카운터 파일(--counter, 기존
방식)과 이 스크립트의 세션 누계(상태 JSON)로 센다. 세션 상한(--max-calls)·예산·한도 초과
응답(resultCode 22)·권한 오류·연속 오류 5회면 멈추고 거기까지 저장한다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
for _root in (ML_ROOT, REPO_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from src import famous_check as fc  # noqa: E402

VERSION = "famous_candidates_v1"
DEFAULT_STATE = ML_ROOT / "data" / "staging" / "famous_candidates.json"
DEFAULT_RAW_DIR = ML_ROOT / "data" / "raw_kipris" / "famous_candidates"
DEFAULT_METADATA = ML_ROOT / "data" / "kipris_metadata.json"
ARCHIVE_DIR = Path.home() / "marklens-archive" / "famous-check-20261124"
DEFAULT_THUMBS = ARCHIVE_DIR / "curate_thumbs" / "cand"
OLD_LIST_COMMIT = "049ddd9"  # 2026-10-12 판 famous_brands.txt(출원인명 목록)

MAX_CALLS_PER_BRAND = 6
MAX_CANDIDATES = 80
ROWS_PER_PAGE = 500  # 항목별검색 공식 상한 — 첫 쪽을 가장 크게
NAME_QUOTA, NAME_QUOTA_OWN = 20, 14  # (가) 응답 하나에서 고르는 수, 그중 아는 출원인 몫
FIGURE_QUOTA, FIGURE_QUOTA_NEW = 24, 16  # (나) 응답 하나에서 고르는 수, 그중 최근 등록 몫
FIGURE_QUOTA_PAGE2 = 8
FIGURE_MAX_PAGES = 2
THUMB_SIZE = 420
ERROR_STREAK_STOP = 5
THUMB_FAIL_STOP = 8
CALL_PAUSE_S, THUMB_PAUSE_S = 0.5, 0.12
LIMIT_CODES = frozenset({"22"})  # LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS
AUTH_CODES = frozenset({"20", "21", "30", "31", "32", "33"})
NAME_PARAM = "trademarkName"  # 항목별검색의 상표명칭 조건(첫 호출로 되는지 확인한다)

# 대표 로고를 찾을 기존 브랜드(등록부 이름) — 표기·출원인은 등록부에서 읽는다
EXISTING_BRANDS = ("이디야커피", "BBQ", "던킨", "GS25", "올리브영", "에어비앤비")
# 새 브랜드: (이름, 검색에 쓸 표기, 2026-10-12 판 목록의 출원인명)
NEW_BRANDS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("삼성", ("삼성", "SAMSUNG"), ("삼성전자주식회사",)),
    ("LG", ("엘지", "LG"), ("주식회사 엘지",)),
    ("현대", ("현대", "HYUNDAI"), ("현대자동차주식회사",)),
    ("기아", ("기아", "KIA"), ("기아 주식회사",)),
    ("애플", ("애플", "APPLE"), ("애플 인크.",)),
    ("나이키", ("나이키", "NIKE"), ("나이키 이노베이트 씨.브이.",)),
    ("아디다스", ("아디다스", "ADIDAS"), ("아디다스 악티엔게젤샤프트",)),
    ("구찌", ("구찌", "GUCCI"), ("구치오구치쏘시에떼퍼아찌오니",)),
    ("유니클로", ("유니클로", "UNIQLO"), ("가부시키가이샤 파스토 리테이링구",)),
    ("자라", ("자라", "ZARA"), ("인두스트리아 데 디세노 텍스틸 에스.에이",)),
    ("맥도날드", ("맥도날드", "McDonald's"), ("맥도날즈 인터내셔널 프로퍼티 컴퍼니, 엘티디.",)),
    ("롯데리아", ("롯데리아", "LOTTERIA"), ("롯데지알에스 주식회사",)),
    ("코카콜라", ("코카콜라", "Coca-Cola"), ("더 코카콜라 컴파니",)),
    ("카카오", ("카카오", "kakao"), ("주식회사 카카오",)),
    ("쿠팡", ("쿠팡", "coupang"), ("쿠팡 주식회사",)),
    ("배달의민족", ("배달의민족", "배민"), ("주식회사 우아한형제들",)),
    ("토스", ("토스", "toss"), ("(주)비바리퍼블리카",)),
    ("당근", ("당근", "당근마켓"), ("당근 주식회사",)),
    ("다이소", ("다이소", "DAISO"), ("주식회사 아성다이소",)),
    ("세븐일레븐", ("세븐일레븐", "7-ELEVEN"), ("코리아세븐 주식회사",)),
    ("맘스터치", ("맘스터치", "MOM'S TOUCH"), ("주식회사 해마로푸드서비스",)),
    ("투썸플레이스", ("투썸플레이스", "투썸", "A TWOSOME PLACE"), ("주식회사 투썸플레이스",)),
    ("메가MGC커피", ("메가MGC커피", "메가커피"), ("주식회사 앤하우스",)),
    ("할리스", ("할리스", "HOLLYS"), ("주식회사 할리스에프앤비",)),
    ("무신사", ("무신사", "MUSINSA"), ("주식회사 무신사",)),
    ("아마존", ("아마존", "amazon"), ("아마존 테크놀로지스, 인크.",)),
    ("BMW", ("비엠더블유", "BMW"), ("바이에리셰 모토렌 베르케 악티엔게젤샤프트",)),
    ("도요타", ("도요타", "토요타", "TOYOTA"), ("도요타지도샤가부시키가이샤",)),
)
# 기존 브랜드의 2026-10-12 판 출원인명(그 판에 없으면 빈 것 — 지금 표의 출원인을 쓴다)
EXISTING_OLD_APPLICANTS = {
    "이디야커피": ("주식회사 이디야",), "BBQ": ("주식회사 제너시스비비큐",),
    "던킨": ("비알코리아 주식회사",), "GS25": ("주식회사 지에스리테일",),
    "올리브영": ("씨제이올리브영 주식회사",), "에어비앤비": (),
}
_LEGAL_FORMS = re.compile(r"주식회사|유한회사|유한책임회사|\(주\)|㈜")
_RESULT_CODE = re.compile(r"<resultCode>\s*(\d+)\s*</resultCode>")
_RESULT_MESSAGE = re.compile(r"<resultMsg>\s*([^<]*?)\s*</resultMsg>")
_NAME_NOISE = re.compile(r"[\s.,·()\[\]&'\"-]+")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def applicant_core(name: str) -> str:
    """출원인명 비교 키 — 수집 스크립트(collect_pipeline.applicant_core)와 같은 식."""
    return _NAME_NOISE.sub("", _LEGAL_FORMS.sub("", name or "")).lower()


def applicant_terms(name: str) -> list[str]:
    """출원인 검색에 보낼 말 — ① 이름에서 쉼표만 뺀 것(쉼표가 있으면 서버가 resultCode 10 을
    준다) ② 그걸로 그 출원인의 표장이 하나도 안 나오면 회사 형태(주식회사·(주) …)까지 뺀 것
    (등록된 표기의 띄어쓰기가 달라 안 나오는 경우 — '비알코리아 주식회사' ↔
    '비알코리아주식회사')."""
    primary = " ".join(str(name or "").replace(",", " ").split())
    stripped = " ".join(_LEGAL_FORMS.sub(" ", primary).split())
    return [term for term in dict.fromkeys((primary, stripped)) if term]


def applicant_parts(field: object) -> list[str]:
    return [part.strip() for part in str(field or "").split("|") if part.strip()]


def brand_plan(registry: fc.Registry | None) -> list[dict]:
    """검색 대상 — 기존 6 + 새 28. 항목: 이름·새 브랜드 여부·표기·출원인(출처와 함께)."""
    plan: list[dict] = []
    for name in EXISTING_BRANDS:
        brand = registry.brand(name) if registry is not None else None
        if brand is None:
            raise ValueError(f"등록부에 브랜드가 없습니다: {name}")
        old = EXISTING_OLD_APPLICANTS.get(name, ())
        applicants = [{"이름": text, "출처": "2026-10-12 판 목록"} for text in old]
        known = {applicant_core(text) for text in old}
        for text in brand.applicants:
            if applicant_core(text) not in known:
                applicants.append({"이름": text, "출처": "지금 [브랜드] 표"})
                known.add(applicant_core(text))
        plan.append({"이름": name, "새_브랜드": False,
                     "표기": [notation.text for notation in brand.notations],
                     "출원인": applicants})
    for name, notations, old in NEW_BRANDS:
        plan.append({"이름": name, "새_브랜드": True, "표기": list(notations),
                     "출원인": [{"이름": text, "출처": "2026-10-12 판 목록"} for text in old]})
    return plan


def planned_calls(item: dict, name_search: bool = True) -> int:
    """브랜드 하나의 최대 호출 수(브랜드당 상한 안에서)."""
    name_calls = len(item["표기"]) if name_search else 0
    applicant_calls = (len(item["출원인"]) + (1 if name_search else 0)) * FIGURE_MAX_PAGES
    return min(MAX_CALLS_PER_BRAND, name_calls + applicant_calls)


# ---- 상태 --------------------------------------------------------------------------------------

def load_state(path: Path) -> dict:
    if Path(path).exists():
        state = json.loads(Path(path).read_text(encoding="utf-8"))
        if state.get("version") != VERSION:
            raise ValueError(f"famous_candidates: version 은 {VERSION} 여야 합니다")
        return state
    return {"version": VERSION, "세션": {"호출": 0, "썸네일": 0, "썸네일_실패": 0, "기록": []},
            "상표명칭_검색": {"가능": None, "근거": ""}, "브랜드": {}}


def save_state(path: Path, state: dict, secret: str = "") -> None:
    text = json.dumps(state, ensure_ascii=False, indent=1) + "\n"
    if has_secret(text, secret):
        raise RuntimeError("상태에 키 값이 들어 있어 쓰지 않습니다")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def secret_forms(secret: str) -> list[str]:
    return [form for form in {secret, quote(secret, safe="")} if form] if secret else []


def has_secret(text: str, secret: str) -> bool:
    return any(form in text for form in secret_forms(secret))


def scrub(text: object, secret: str) -> str:
    out = str(text)
    for form in secret_forms(secret):
        out = out.replace(form, "***")
    return out


# ---- 고르기(순수 함수) -------------------------------------------------------------------------

def normalize_item(raw: dict, normalize) -> dict:
    """검색 응답 항목(camelCase) → 정규 키. 국제등록 표장은 출원번호 칸이 비어 있고 참조번호
    (appReferenceNumber — 40-…-7…… 꼴의 국내 번호)만 온다 — 그 번호를 출원번호로 쓰고
    국제등록번호를 함께 남긴다."""
    item = dict(normalize(raw))
    reference = str(raw.get("appReferenceNumber") or "").strip()
    international = str(raw.get("internationalRegisterNumber") or "").strip()
    if not str(item.get("ApplicationNumber") or "").strip() and reference:
        item["ApplicationNumber"] = reference
        item["NumberIsReference"] = True
    item["InternationalNumber"] = international or None
    if not str(item.get("RegistrationDate") or "").strip():
        item["RegistrationDate"] = str(raw.get("registrationDate") or "").strip()
    if not str(item.get("ApplicationDate") or "").strip():  # 국제등록은 국제등록일을 대신 적는다
        item["ApplicationDate"] = str(raw.get("internationalRegisterDate") or "").strip()
    return item


def candidate_from_item(item: dict, *, via: str, kind: str | None = None) -> dict:
    """정규화한 검색 항목 → 후보. 견본 링크는 담지 않는다(시한부이고 저장할 까닭이 없다)."""
    title = str(item.get("Title") or "").strip() or None
    vienna = [str(code) for code in item.get("ViennaCode") or ()]
    if kind is None:
        kind = "도형" if not title else ("결합(추정)" if vienna else "문자(추정)")
    return {
        "출원번호": str(item.get("ApplicationNumber") or "").strip(),
        "상표명": title, "유형": kind,
        "출원인": applicant_parts(item.get("ApplicantName")),
        "등록권리자": applicant_parts(item.get("RegistrationRightholderName")),
        "상태": str(item.get("ApplicationStatus") or "").strip(),
        "출원일": str(item.get("ApplicationDate") or "").strip() or None,
        "등록일": str(item.get("RegistrationDate") or "").strip() or None,
        "등록번호": str(item.get("RegistrationNumber") or "").strip() or None,
        "류": [str(code) for code in item.get("GoodClassificationCode") or ()],
        "비엔나": vienna, "찾은_길": [via], "썸네일": None, "DB에_있음": False,
        "국제등록번호": item.get("InternationalNumber"),
        "번호는_참조번호": bool(item.get("NumberIsReference")),
    }


def applicant_distribution(items: list[dict]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for item in items:
        for part in applicant_parts(item.get("ApplicantName")):
            counts[part] = counts.get(part, 0) + 1
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))


def _date_key(candidate: dict) -> str:
    return re.sub(r"\D", "", candidate.get("등록일") or candidate.get("출원일") or "")


def rank_name_results(items: list[dict], notation: str, known: set[str]) -> list[dict]:
    """(가) 응답 하나의 후보 순서 — 점수: 아는 출원인 4 + 그 응답에서 가장 많은 출원인(3건
    이상) 2 + 상표명이 표기와 같음 2(표기가 낱말로 들어 있음 1). 같으면 최근 등록 먼저."""
    distribution = applicant_distribution(items)
    top = distribution[0][0] if distribution and distribution[0][1] >= 3 else None
    key = fc.text_key(notation)
    ranked = []
    for item in items:
        candidate = candidate_from_item(item, via=f"가:{notation}")
        if not candidate["출원번호"]:
            continue
        cores = {applicant_core(part)
                 for part in candidate["출원인"] + candidate["등록권리자"]}
        score = 0
        own = bool(cores & known)
        if own:
            score += 4
        if top is not None and top in candidate["출원인"]:
            score += 2
        title_key = fc.text_key(candidate["상표명"] or "")
        if title_key and title_key == key:
            score += 2
        elif fc.title_has_notation(candidate["상표명"], [notation]):
            score += 1
        candidate["점수"], candidate["아는_출원인"] = score, own
        ranked.append(candidate)
    ranked.sort(key=lambda c: (-c["점수"], -int(_date_key(c) or 0), c["출원번호"]))
    return ranked


def pick_name_results(ranked: list[dict], quota: int = NAME_QUOTA,
                      own_quota: int = NAME_QUOTA_OWN) -> list[dict]:
    """(가) 응답 하나에서 고르기 — 아는 출원인 몫과 그 밖의 몫을 나눠 지주사·해외 본사 권리자도
    보이게 한다(한쪽이 모자라면 다른 쪽이 채운다)."""
    own = [c for c in ranked if c["아는_출원인"]]
    other = [c for c in ranked if not c["아는_출원인"]]
    take_own = own[:own_quota]
    take_other = other[:quota - len(take_own)]
    take_own = own[:quota - len(take_other)]
    return take_own + take_other


def pick_figure_results(items: list[dict], applicant: str, *, quota: int = FIGURE_QUOTA,
                        newest: int = FIGURE_QUOTA_NEW) -> tuple[list[dict], int]:
    """(나) 응답 하나에서 고르기 — 출원인명이 같은 도형 표장만 남기고, 최근 등록과 오래된
    등록을 섞는다(지금 로고와 오래 쓴 로고가 다 보이게). 돌려주는 것: (고른 후보, 출원인이
    같은 표장 수)."""
    core = applicant_core(applicant)
    same = []
    for item in items:
        candidate = candidate_from_item(item, via=f"나:{applicant}", kind="도형")
        if not candidate["출원번호"]:
            continue
        if core not in {applicant_core(part)
                        for part in candidate["출원인"] + candidate["등록권리자"]}:
            continue
        candidate["점수"], candidate["아는_출원인"] = 5, True
        same.append(candidate)
    same.sort(key=lambda c: (-int(_date_key(c) or 0), c["출원번호"]))
    if len(same) <= quota:
        return same, len(same)
    head = same[:newest]
    tail = same[len(same) - (quota - newest):]
    return head + tail, len(same)


def pick_for_call(call: dict, items: list[dict], known: set[str]) -> tuple[list[dict], dict]:
    """호출 기록 하나의 응답에서 후보 고르기 — (고른 후보, 기록에 더할 값)."""
    if call["종류"] == "가":
        ranked = rank_name_results(items, call["검색어"], known)
        return pick_name_results(ranked), {"출원인_분포": applicant_distribution(items)[:8]}
    quota = FIGURE_QUOTA if int(call.get("쪽", 1)) == 1 else FIGURE_QUOTA_PAGE2
    picked, same = pick_figure_results(items, call.get("출원인") or call["검색어"], quota=quota,
                                       newest=min(FIGURE_QUOTA_NEW, quota))
    return picked, {"출원인이_같은_것": same}


def merge_candidates(existing: list[dict], picked: list[dict]) -> list[dict]:
    """출원번호로 중복 없이 합친다 — 찾은 길은 모으고 점수는 높은 쪽."""
    by_appno = {candidate["출원번호"]: candidate for candidate in existing}
    for candidate in picked:
        old = by_appno.get(candidate["출원번호"])
        if old is None:
            by_appno[candidate["출원번호"]] = candidate
            continue
        old["찾은_길"] = list(dict.fromkeys(old["찾은_길"] + candidate["찾은_길"]))
        old["점수"] = max(old.get("점수", 0), candidate.get("점수", 0))
        old["아는_출원인"] = bool(old.get("아는_출원인") or candidate.get("아는_출원인"))
        old["썸네일"] = old.get("썸네일") or candidate.get("썸네일")
        if candidate["유형"] == "도형":
            old["유형"] = "도형"
    return list(by_appno.values())


def cap_candidates(candidates: list[dict], limit: int = MAX_CANDIDATES) -> list[dict]:
    """브랜드당 상한 — 도형((나))과 이름((가))을 절반씩, 한쪽이 모자라면 다른 쪽이 채운다."""
    def order(c: dict) -> tuple:
        return (-c.get("점수", 0), -int(_date_key(c) or 0), c["출원번호"])

    figures = sorted((c for c in candidates if c["유형"] == "도형"), key=order)
    names = sorted((c for c in candidates if c["유형"] != "도형"), key=order)
    half = limit // 2
    take_figures = figures[:half]
    take_names = names[:limit - len(take_figures)]
    take_figures = figures[:limit - len(take_names)]
    return take_figures + take_names


# ---- KIPRIS ------------------------------------------------------------------------------------

class Stop(Exception):
    """검색을 멈추는 까닭(상한·예산·한도 초과·권한 오류·연속 오류)."""


class Searcher:
    def __init__(self, args, state: dict):
        if not args.key_env:
            raise SystemExit("--key-env 가 필요합니다(.env 의 공용 키로는 호출하지 않습니다)")
        if not args.counter:
            raise SystemExit("--counter 가 필요합니다(키별 호출 카운터 파일)")
        from backend.scripts import collect_pipeline as cp
        from backend.src.core import kipris_client as kc

        self.kc, self.args, self.state = kc, args, state
        self.info = cp.use_key_and_counter(key_env=args.key_env, counter=args.counter)
        self.secret = kc.ACCESS_KEY
        self.streak = 0
        self.thumb_streak = 0
        self.thumbs_on = not args.no_thumbs
        metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
        records = metadata.get("trademarks", metadata) if isinstance(metadata, dict) else metadata
        self.db = {str(record["출원번호"]) for record in records}

    # -- 호출 한 번 --
    def call(self, brand: dict, record: dict, params: dict) -> list[dict] | None:
        session = self.state["세션"]
        if session["호출"] >= self.args.max_calls:
            raise Stop(f"세션 상한 {self.args.max_calls}회")
        if len(brand["호출"]) >= MAX_CALLS_PER_BRAND:
            return None
        kc = self.kc
        record.update({"시각": _now(), "쪽": int(params.get("pageNo", 1))})
        brand["호출"].append(record)
        session["호출"] += 1
        try:
            kc._require_config(kc.ADVANCED_SEARCH_URL, "KIPRIS_APPLICANT_SEARCH_URL")  # noqa: SLF001
            xml_text = kc._get(kc.ADVANCED_SEARCH_URL, params, auth_param="ServiceKey",  # noqa: SLF001
                               timeout=self.args.timeout)
        except kc.CallBudgetExceeded as exc:
            brand["호출"].pop()
            session["호출"] -= 1
            raise Stop(f"카운터 예산: {scrub(exc, self.secret)}") from None
        except kc.KiprisError as exc:
            return self._failed(record, exc)
        raw = self._save_raw(brand["이름"], record, xml_text)
        record["원본"] = raw
        code = _RESULT_CODE.search(xml_text)
        message = _RESULT_MESSAGE.search(xml_text)
        if code and code.group(1) not in ("00", "03"):  # 오류 응답에는 body 가 없다
            error = kc.KiprisError(
                f"resultCode {code.group(1)} {message.group(1) if message else ''}".strip(),
                result_code=code.group(1))
            return self._failed(record, error)
        try:
            if code and code.group(1) == "03":  # NODATA
                items, total = [], 0
            else:
                items = [normalize_item(item, kc.normalize_advanced_item)
                         for item in kc.parse_items(xml_text)]
                total = kc.parse_advanced_total_count(xml_text)
        except kc.KiprisError as exc:
            return self._failed(record, exc)
        self.streak = 0
        record.update({"totalCount": total, "받은": len(items), "오류": None})
        time.sleep(CALL_PAUSE_S)
        return items

    def _failed(self, record: dict, exc: Exception) -> None:
        code = getattr(exc, "result_code", None)
        record.update({"오류": f"{type(exc).__name__}: {scrub(exc, self.secret)}",
                       "resultCode": code})
        self.streak += 1
        print(f"  [오류] {record['종류']} {record['검색어']}: {record['오류']}", file=sys.stderr)
        if code in LIMIT_CODES:
            raise Stop(f"한도 초과 응답(resultCode {code})")
        if code in AUTH_CODES:
            raise Stop(f"권한 오류(resultCode {code})")
        if self.streak >= ERROR_STREAK_STOP:
            raise Stop(f"연속 오류 {ERROR_STREAK_STOP}회")
        return None

    def _save_raw(self, brand: str, record: dict, xml_text: str) -> str:
        safe = re.sub(r"[^0-9A-Za-z가-힣]+", "_", f"{brand}_{record['종류']}_{record['검색어']}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest = Path(self.args.raw_dir) / f"{safe.strip('_')[:60]}_p{record['쪽']}_{stamp}.xml"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(scrub(xml_text, self.secret), encoding="utf-8")
        try:
            return str(dest.relative_to(ML_ROOT / "data"))
        except ValueError:
            return str(dest)

    def name_search(self, brand: dict, notation: str) -> list[dict] | None:
        kc = self.kc
        flags = {"registration", *kc.ADVANCED_MARK_TYPE_FLAGS, *kc.ADVANCED_COMPOSITION_FLAGS}
        params = {NAME_PARAM: notation, **kc.build_advanced_flags(flags), "pageNo": "1",
                  "numOfRows": str(ROWS_PER_PAGE)}
        return self.call(brand, {"종류": "가", "검색어": notation}, params)

    def figure_search(self, brand: dict, applicant: str, term: str, page: int
                      ) -> list[dict] | None:
        kc = self.kc
        flags = {"registration", "figure", *kc.ADVANCED_MARK_TYPE_FLAGS}
        params = {kc.APPLICANT_PARAM: term, **kc.build_advanced_flags(flags),
                  "pageNo": str(page), "numOfRows": str(ROWS_PER_PAGE)}
        return self.call(brand, {"종류": "나", "검색어": term, "출원인": applicant}, params)

    # -- 썸네일(응답 직후) --
    def thumbs(self, picked: list[dict], items: list[dict]) -> None:
        urls = {str(item.get("ApplicationNumber") or "").strip(): item.get("ImagePath")
                for item in items}
        session = self.state["세션"]
        for candidate in picked:
            appno = candidate["출원번호"]
            candidate["DB에_있음"] = appno in self.db
            if candidate["DB에_있음"] or not self.thumbs_on:
                continue
            dest = Path(self.args.thumbs_dir) / f"{appno}.png"
            if dest.is_file():
                candidate["썸네일"] = dest.name
                continue
            url = urls.get(appno)
            if not url:
                continue
            if self._download(url, dest):
                candidate["썸네일"] = dest.name
                session["썸네일"] += 1
                self.thumb_streak = 0
            else:
                session["썸네일_실패"] += 1
                self.thumb_streak += 1
                if self.thumb_streak >= THUMB_FAIL_STOP:
                    self.thumbs_on = False
                    session["썸네일_멈춤"] = f"연속 실패 {THUMB_FAIL_STOP}회 — 그 뒤는 그림 없이"
                    print("  [썸네일] 연속 실패로 그 뒤는 받지 않습니다", file=sys.stderr)
                    return
            time.sleep(THUMB_PAUSE_S)

    def _download(self, url: str, dest: Path) -> bool:
        from PIL import Image

        kc = self.kc
        temporary = dest.with_suffix(".download")
        try:
            kc.download_file_now(str(url), temporary, validate_image=True)
            with Image.open(temporary) as image:
                image = image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB")
                image.thumbnail((THUMB_SIZE, THUMB_SIZE))
                dest.parent.mkdir(parents=True, exist_ok=True)
                image.save(dest, format="PNG", optimize=True)
            return True
        except (kc.KiprisError, OSError, ValueError):
            return False
        finally:
            temporary.unlink(missing_ok=True)


def judge_name_search(state: dict, notation: str, items: list[dict], total: int | None) -> None:
    """첫 (가) 응답들로 상표명칭 검색이 되는지 판정 — 응답의 상표명에 표기가 들어 있으면 됨,
    전체 건수가 터무니없이 많고 표기가 거의 없으면 조건이 무시된 것(안 됨)."""
    verdict = state["상표명칭_검색"]
    if verdict["가능"] is not None or not items:
        return
    hits = sum(1 for item in items if fc.title_has_notation(item.get("Title"), [notation])
               or fc.text_key(notation) in fc.text_key(item.get("Title") or ""))
    share = hits / len(items)
    if share >= 0.3:
        verdict.update({"가능": True, "근거": (
            f"{NAME_PARAM}={notation}: totalCount {total}, 받은 {len(items)}건 중 상표명에 "
            f"표기가 든 것 {hits}건({share:.0%})")})
    elif (total or 0) > 100_000 and share < 0.05:
        verdict.update({"가능": False, "근거": (
            f"{NAME_PARAM}={notation}: totalCount {total}, 상표명에 표기가 든 것 {hits}/"
            f"{len(items)} — 조건이 무시된 것으로 보임")})


def search_brand(searcher: Searcher, item: dict, brand: dict, state_path: Path) -> None:
    """브랜드 하나 — (가) 표기마다 → (나) 출원인마다(1쪽 먼저, 남으면 2쪽)."""
    state = searcher.state
    done = {(call["종류"], call["검색어"], call["쪽"]) for call in brand["호출"]}
    brand.pop("끝", None)
    known = {applicant_core(entry["이름"]) for entry in item["출원인"]}

    def keep(picked: list[dict], items: list[dict]) -> None:
        searcher.thumbs(picked, items)
        brand["후보"] = merge_candidates(brand["후보"], picked)
        save_state(state_path, state, searcher.secret)

    if state["상표명칭_검색"]["가능"] is not False:
        for notation in item["표기"]:
            if ("가", notation, 1) in done:
                continue
            items = searcher.name_search(brand, notation)
            save_state(state_path, state, searcher.secret)
            if items is None:
                continue
            judge_name_search(state, notation, items, brand["호출"][-1].get("totalCount"))
            if state["상표명칭_검색"]["가능"] is False:
                break
            picked, extra = pick_for_call(brand["호출"][-1], items, known)
            brand["호출"][-1].update(extra)
            brand["이름_출원인"] = _merge_counts(brand.get("이름_출원인", {}), items)
            keep(picked, items)
    # (나) 출원인 — 2026-10-12 판(없으면 표) + (가) 결과에서 가장 많이 나온 출원인
    applicants = [dict(entry) for entry in item["출원인"]]
    counts = sorted(brand.get("이름_출원인", {}).items(), key=lambda pair: (-pair[1], pair[0]))
    if counts and counts[0][1] >= 2:
        top, count = counts[0]
        brand["가장_많은_출원인"] = {"이름": top, "건수": count,
                                 "전체": sum(value for _, value in counts)}
        if applicant_core(top) not in {applicant_core(entry["이름"]) for entry in applicants}:
            applicants.append({"이름": top, "출처": f"(가) 결과에서 가장 많이 나옴({count}건)"})
    brand["쓴_출원인"] = applicants
    for entry in applicants:
        applicant = entry["이름"]
        sent: list[str] = []
        for term in applicant_terms(applicant):
            total = 0
            for page in range(1, FIGURE_MAX_PAGES + 1):
                previous = next((call for call in brand["호출"] if call["종류"] == "나"
                                 and call["검색어"] == term and call["쪽"] == page), None)
                if previous is None:
                    if page > 1 and total <= ROWS_PER_PAGE * (page - 1):
                        break
                    items = searcher.figure_search(brand, applicant, term, page)
                    save_state(state_path, state, searcher.secret)
                    if items is None:
                        break
                    record = brand["호출"][-1]
                    picked, extra = pick_for_call(record, items, known)
                    record.update(extra)
                    keep(picked, items)
                    previous = record
                total = int(previous.get("totalCount") or 0)
            sent.append(term)
            found = sum(int(call.get("출원인이_같은_것") or 0) for call in brand["호출"]
                        if call["종류"] == "나" and call["검색어"] == term)
            if found:  # 이 말로 그 출원인의 도형 표장이 나왔다 — 다음 말은 보내지 않는다
                break
        entry["보낸_말"] = sent
    brand["후보"] = cap_candidates(brand["후보"])
    if item["이름"] in set(searcher.args.refresh or ()):
        refresh_thumbs(searcher, brand, state_path)
    brand["끝"] = True
    save_state(state_path, state, searcher.secret)


def read_raw_items(call: dict, normalize) -> list[dict]:
    """호출 기록의 원본 XML 을 다시 읽어 정규화한 항목(호출 0)."""
    from backend.src.core import kipris_client as kc

    path = ML_ROOT / "data" / str(call.get("원본") or "")
    if call.get("오류") or not call.get("원본") or not path.is_file():
        return []
    return [normalize_item(item, normalize) for item in kc.parse_items(
        path.read_text(encoding="utf-8"))]


def refresh_thumbs(searcher: Searcher, brand: dict, state_path: Path) -> None:
    """썸네일이 없는 후보(DB 에 없는 것)가 든 검색을 다시 보내 새 견본 링크로 받는다 — 호출을
    쓰므로 브랜드당 상한 안에서만, 가장 많이 채우는 검색부터."""
    kc = searcher.kc
    wanted = {c["출원번호"]: c for c in brand["후보"] if not c["썸네일"] and not c["DB에_있음"]}
    plans = []
    for call in brand["호출"]:
        if call.get("오류") or call.get("다시"):
            continue
        ids = {str(item.get("ApplicationNumber") or "")
               for item in read_raw_items(call, kc.normalize_advanced_item)}
        plans.append((len(ids & set(wanted)), call))
    for _, call in sorted(plans, key=lambda pair: -pair[0]):
        missing = [c for c in wanted.values() if not c["썸네일"]]
        if not missing or len(brand["호출"]) >= MAX_CALLS_PER_BRAND:
            break
        if call["종류"] == "가":
            items = searcher.name_search(brand, call["검색어"])
        else:
            items = searcher.figure_search(brand, call.get("출원인") or call["검색어"],
                                           call["검색어"], int(call["쪽"]))
        if items is None:
            continue
        brand["호출"][-1]["다시"] = "썸네일"
        ids = {str(item.get("ApplicationNumber") or "") for item in items}
        searcher.thumbs([c for c in missing if c["출원번호"] in ids], items)
        save_state(state_path, searcher.state, searcher.secret)


def command_rebuild(args) -> int:
    """받아 둔 원본 XML 에서 후보를 다시 뽑는다(호출 0) — 고르는 규칙을 고친 뒤. 썸네일은 이미
    받은 파일만 잇는다."""
    from backend.src.core import kipris_client as kc

    registry = fc.load_registry()
    state = load_state(args.state)
    plan = {item["이름"]: item for item in brand_plan(registry)}
    metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    records = metadata.get("trademarks", metadata) if isinstance(metadata, dict) else metadata
    db = {str(record["출원번호"]) for record in records}
    rows = []
    for name, brand in state["브랜드"].items():
        known = {applicant_core(entry["이름"]) for entry in plan[name]["출원인"]}
        before = len(brand["후보"])
        candidates: list[dict] = []
        for call in brand["호출"]:
            if call.get("오류") or call.get("다시"):
                continue
            items = read_raw_items(call, kc.normalize_advanced_item)
            picked, extra = pick_for_call(call, items, known)
            call.update(extra)
            for candidate in picked:
                candidate["DB에_있음"] = candidate["출원번호"] in db
                thumb = Path(args.thumbs_dir) / f"{candidate['출원번호']}.png"
                if thumb.is_file() and not candidate["DB에_있음"]:
                    candidate["썸네일"] = thumb.name
            candidates = merge_candidates(candidates, picked)
        brand["후보"] = cap_candidates(candidates)
        rows.append({"브랜드": name, "후보(전)": before, "후보(뒤)": len(brand["후보"]),
                     "국제등록": sum(1 for c in brand["후보"] if c.get("국제등록번호")),
                     "썸네일_없음": sum(1 for c in brand["후보"]
                                    if not c["썸네일"] and not c["DB에_있음"])})
    save_state(args.state, state)
    print(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0


def _merge_counts(counts: dict, items: list[dict]) -> dict:
    out = dict(counts)
    for name, count in applicant_distribution(items):
        out[name] = out.get(name, 0) + count
    return out


# ---- 명령 --------------------------------------------------------------------------------------

def command_plan(args) -> int:
    registry = fc.load_registry()
    state = load_state(args.state)
    plan = brand_plan(registry)
    name_search = state["상표명칭_검색"]["가능"] is not False
    rows, total = [], 0
    for item in plan:
        calls = planned_calls(item, name_search)
        total += calls
        rows.append({"브랜드": item["이름"], "새": item["새_브랜드"], "표기": item["표기"],
                     "출원인": [entry["이름"] for entry in item["출원인"]], "최대_호출": calls})
    print(json.dumps({"브랜드": len(plan), "최대_호출_합": total,
                      "브랜드당_상한": MAX_CALLS_PER_BRAND, "계획": rows},
                     ensure_ascii=False, indent=1))
    return 0


def summarize(state: dict) -> dict:
    rows = []
    for name, brand in state["브랜드"].items():
        calls = brand["호출"]
        candidates = brand["후보"]
        rows.append({
            "브랜드": name, "새": brand["새_브랜드"], "끝": bool(brand.get("끝")),
            "호출": len(calls), "오류": sum(1 for call in calls if call.get("오류")),
            "가_전체건수": {call["검색어"]: call.get("totalCount") for call in calls
                        if call["종류"] == "가"},
            "나_전체건수": {call["검색어"]: call.get("totalCount") for call in calls
                        if call["종류"] == "나" and call["쪽"] == 1},
            "나_출원인이_같은_것": {call["검색어"]: call.get("출원인이_같은_것") for call in calls
                             if call["종류"] == "나" and call["쪽"] == 1},
            "쓴_출원인": brand.get("쓴_출원인", []),
            "가장_많은_출원인": brand.get("가장_많은_출원인"),
            "후보": len(candidates),
            "후보_도형": sum(1 for c in candidates if c["유형"] == "도형"),
            "DB에_있음": sum(1 for c in candidates if c["DB에_있음"]),
            "썸네일": sum(1 for c in candidates if c["썸네일"])})
    return {"세션": {key: value for key, value in state["세션"].items() if key != "기록"},
            "실행_기록": state["세션"]["기록"], "상표명칭_검색": state["상표명칭_검색"],
            "브랜드_수": len(rows), "끝난_브랜드": sum(1 for row in rows if row["끝"]),
            "후보_합": sum(row["후보"] for row in rows), "브랜드별": rows}


def command_status(args) -> int:
    print(json.dumps(summarize(load_state(args.state)), ensure_ascii=False, indent=1))
    return 0


def command_run(args) -> int:
    registry = fc.load_registry()
    state = load_state(args.state)
    plan = brand_plan(registry)
    if args.only:
        unknown = sorted(set(args.only) - {item["이름"] for item in plan})
        if unknown:
            raise SystemExit(f"대상에 없는 브랜드: {unknown}")
        plan = [item for item in plan if item["이름"] in set(args.only)]
    searcher = Searcher(args, state)
    started = {"시작": _now(), "키": searcher.info.get("키"),
               "카운터": searcher.info.get("카운터"),
               "카운터_이번_달(시작)": searcher.info.get("이번_달"),
               "호출(시작)": state["세션"]["호출"], "상한": args.max_calls}
    state["세션"]["기록"].append(started)
    print(f"[시작] {started['키']} · 카운터 {started['카운터']} 이번 달 "
          f"{started['카운터_이번_달(시작)']}회 · 세션 {started['호출(시작)']}/{args.max_calls}회")
    stopped = ""
    try:
        for item in plan:
            brand = state["브랜드"].setdefault(item["이름"], {
                "이름": item["이름"], "새_브랜드": item["새_브랜드"], "표기": item["표기"],
                "출원인": item["출원인"], "호출": [], "후보": []})
            if brand.get("끝") and item["이름"] not in {*(args.reopen or ()),
                                                      *(args.refresh or ())}:
                continue
            search_brand(searcher, item, brand, args.state)
            row = summarize({"세션": state["세션"], "상표명칭_검색": state["상표명칭_검색"],
                             "브랜드": {item["이름"]: brand}})["브랜드별"][0]
            print(f"[{item['이름']}] 호출 {row['호출']}(오류 {row['오류']}) · 후보 {row['후보']}"
                  f"(도형 {row['후보_도형']}, DB에 있음 {row['DB에_있음']}, 썸네일 "
                  f"{row['썸네일']}) · 세션 {state['세션']['호출']}/{args.max_calls}")
            if state["상표명칭_검색"]["가능"] is False and not args.only:
                print("  [알림] 상표명칭 검색이 되지 않아 그 뒤는 (나)만 합니다")
    except Stop as stop:
        stopped = str(stop)
        print(f"[멈춤] {stopped}")
    finally:
        started.update({"끝": _now(), "호출(끝)": state["세션"]["호출"], "멈춤": stopped,
                        "카운터_이번_달(끝)": searcher.kc.limiter.used_this_month()})
        save_state(args.state, state, searcher.secret)
    print(f"[끝] 세션 호출 {state['세션']['호출']}회 · 카운터 이번 달 "
          f"{started['카운터_이번_달(끝)']}회 · 상표명칭 검색 {state['상표명칭_검색']}")
    return 3 if stopped else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("plan", "status", "run", "rebuild"))
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--thumbs-dir", type=Path, default=DEFAULT_THUMBS)
    parser.add_argument("--key-env", metavar="NAME", help="키를 담은 환경 변수 이름(값이 아님)")
    parser.add_argument("--counter", type=Path, metavar="PATH", help="그 키의 호출 카운터 파일")
    parser.add_argument("--max-calls", type=int, default=300, help="세션 호출 상한(누계)")
    parser.add_argument("--only", nargs="+", metavar="브랜드")
    parser.add_argument("--reopen", nargs="+", metavar="브랜드",
                        help="끝난 브랜드를 다시 연다(안 보낸 검색만 보낸다)")
    parser.add_argument("--refresh", nargs="+", metavar="브랜드",
                        help="썸네일이 없는 후보가 든 검색을 다시 보내 그림을 받는다(호출을 쓴다)")
    parser.add_argument("--no-thumbs", action="store_true")
    parser.add_argument("--timeout", type=float, default=40.0)
    args = parser.parse_args(argv)
    commands = {"plan": command_plan, "status": command_status, "run": command_run,
                "rebuild": command_rebuild}
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
