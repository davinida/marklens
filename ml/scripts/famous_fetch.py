"""유명 상표의 대표 표장 받기 — 고르기 도구에서 "받기"로 고른 표장을 KIPRIS 에서 받아 파일
스테이징에 넣는다(통합 모델 설계 §7-14-11). 운영 DB 는 건드리지 않는다 — 승격은 기존 절차
(`backend/scripts/promote_file_staging.py --staging … --plan/--apply`)로 따로 한다.

    ml/venv/bin/python ml/scripts/famous_fetch.py plan      # 호출 0 — 받을 목록·필요한 호출 수
    ml/venv/bin/python ml/scripts/famous_fetch.py status    # 호출 0 — 받은 것·못 받은 것(이유)
    TEAMMATE_KIPRIS_KEY=… KIPRIS_DAILY_BUDGET=0 ml/venv/bin/python \\
        ml/scripts/famous_fetch.py run --key-env TEAMMATE_KIPRIS_KEY \\
        --counter ml/data/kipris_counters/<키 이름>/kipris_call_count.json \\
        --max-calls 300 [--only 출원번호 …]

받을 목록 = shared/famous_registry_overrides.json 의 fetch(후보에서 고른 것·직접 적은 출원번호)
가운데 아직 DB 에 없는 것. 순서는 대표 로고(현재) → 과거 로고 → 그 밖(세션 상한에 걸리면 뒤의 것이
남는다).

받기는 기존 수집 절차(collect_pipeline.run_selection_plan)와 같은 순서·같은 함수로 한다: 표장마다
서지상세 1회(등록 상태·표장 구분·지정상품과 유사군·새 견본 링크) → 견본을 곧바로 받아 검증 → 파일
스테이징에 병합(수집 출처 SOURCE_LABEL). 상표명·출원인·출원일·등록일은 후보 찾기 때 받은 검색 응답
원본의 그 항목을 쓰고(없으면 — 직접 적은 출원번호 — 출원번호 검색 1회를 더 한다), 출원번호로 지정해
받으므로 표장마다 결과(받음 / 넣지 않은 까닭)를 남긴다. 넣지 않는 것: 등록 상태가 아님, 지정상품
(유사군)이 없음, 견본이 없거나 받지 못함. 한 건이 실패해도 나머지는 계속한다. 한도 초과 응답
(resultCode 22)·권한 오류·세션 상한·예산·연속 오류 5회면 멈추고 거기까지 스테이징에 남긴다.

키: 환경 변수 **이름**만 받는다(--key-env). 값은 kipris_client.ACCESS_KEY 에만 넣고 어디에도 쓰지
않는다(상태·원본을 쓰기 전에 키 값이 없는지 본다). 호출 수는 키별 카운터(--counter)와 세션 누계.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
for _root in (ML_ROOT, REPO_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from src import famous_check as fc  # noqa: E402

from scripts import famous_candidates as cand  # noqa: E402

VERSION = "famous_fetch_v1"
SOURCE_LABEL = fc.DB_SOURCE_LOGOS  # "유명 브랜드(대표 표장)" — 기존 283건("유명 브랜드")과 구분
DEFAULT_STAGING = ML_ROOT / "data" / "staging" / "famous_logos.json"
DEFAULT_STATE = ML_ROOT / "data" / "staging" / "famous_logos.fetch.json"
DEFAULT_METADATA = ML_ROOT / "data" / "kipris_metadata.json"
ROLE_ORDER = (fc.ROLE_LOGO_NOW, fc.ROLE_LOGO_OLD, fc.ROLE_BRAND_OTHER, fc.ROLE_UNRELATED)
SAVE_EVERY = 10
ERROR_STREAK_STOP = 5
CALL_PAUSE_S = 0.3
DONE = "받음"
_RESULT_CODE = re.compile(r"<resultCode>\s*(\d+)\s*</resultCode>")
_RESULT_MESSAGE = re.compile(r"<resultMsg>\s*([^<]*?)\s*</resultMsg>")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def db_appnos(metadata_path: Path = DEFAULT_METADATA) -> set[str]:
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    records = metadata.get("trademarks", metadata) if isinstance(metadata, dict) else metadata
    return {str(record["출원번호"]) for record in records}


def search_items(candidates: dict | None) -> dict[str, dict]:
    """후보 찾기 때 받은 검색 응답 원본에서 출원번호 → 그 항목(정규 키). 원본을 다시 읽는다
    (호출 0)."""
    from backend.src.core import kipris_client as kc

    items: dict[str, dict] = {}
    for brand in ((candidates or {}).get("브랜드") or {}).values():
        wanted = {c["출원번호"] for c in brand.get("후보") or ()}
        for call in brand.get("호출") or ():
            for item in cand.read_raw_items(call, kc.normalize_advanced_item):
                appno = str(item.get("ApplicationNumber") or "")
                if appno in wanted and appno not in items:
                    items[appno] = item
    return items


def fetch_plan(overrides: dict, in_db: set[str], items: dict[str, dict]) -> dict:
    """받을 목록 — overrides 의 fetch 를 역할 순(대표 로고(현재) → 과거 로고 → 그 밖)으로.
    이미 DB 에 있는 것은 받지 않는다(역할만 잇는다 — 등록부가 한다). 호출 수 = 서지 1회씩 +
    검색 응답이 없는 것(직접 적은 출원번호)은 출원번호 검색 1회씩."""
    rows, attach = [], []
    for brand, item in overrides["brands"].items():
        for entry in item.get("fetch") or ():
            row = {"출원번호": entry["appno"], "브랜드": item.get("name") or brand,
                   "역할": entry["role"], "출처": entry["source"],
                   "검색_응답_있음": entry["appno"] in items,
                   "국제등록": bool((items.get(entry["appno"]) or {}).get("NumberIsReference"))}
            (attach if entry["appno"] in in_db else rows).append(row)
    duplicated = sorted(appno for appno, count in Counter(
        row["출원번호"] for row in rows).items() if count > 1)
    order = {role: index for index, role in enumerate(ROLE_ORDER)}
    rows.sort(key=lambda row: order[row["역할"]])  # 안정 정렬 — 같은 역할은 overrides 순서
    seen: set[str] = set()
    unique = [row for row in rows if not (row["출원번호"] in seen or seen.add(row["출원번호"]))]
    return {
        "받을_표장": unique, "이미_DB에_있음": attach, "여러_브랜드가_고른_번호": duplicated,
        "필요한_호출": len(unique) + sum(1 for row in unique if not row["검색_응답_있음"]),
        "브랜드·역할별": {
            brand: dict(Counter(row["역할"] for row in rows if row["브랜드"] == brand))
            for brand in dict.fromkeys(row["브랜드"] for row in rows)},
        "역할별": dict(Counter(row["역할"] for row in unique)),
        "국제등록": [row["출원번호"] for row in unique if row["국제등록"]],
    }


def load_state(path: Path) -> dict:
    if Path(path).exists():
        state = json.loads(Path(path).read_text(encoding="utf-8"))
        if state.get("version") != VERSION:
            raise ValueError(f"famous_fetch: version 은 {VERSION} 여야 합니다")
        return state
    return {"version": VERSION, "세션": {"호출": 0, "견본": 0, "기록": []}, "표장": {}}


def save_state(path: Path, state: dict, secret: str = "") -> None:
    cand.save_state(path, state, secret)


def staged_item(item: dict, detail: dict, short_mark_kind) -> dict:
    """검색 응답 항목 + 서지상세 → 스테이징에 넣을 항목(기존 절차와 같은 채움 규칙)."""
    out = dict(item)
    out["SimilarCode"] = list(detail["similarity_codes"])
    if not out.get("GoodClassificationCode") and detail.get("nice_classes"):
        out["GoodClassificationCode"] = [str(c) for c in detail["nice_classes"]]
    if not out.get("DrawingKindName") and detail.get("mark_type"):
        out["DrawingKindName"] = short_mark_kind(detail["mark_type"])
    if not out.get("RegistrationNumber") and detail.get("registration_number"):
        out["RegistrationNumber"] = detail["registration_number"]
    if not out.get("ViennaCode") and detail.get("vienna_codes"):
        out["ViennaCode"] = list(detail["vienna_codes"])
    return out


def judge(detail: dict, item: dict) -> str | None:
    """넣지 않을 까닭(넣어도 되면 None) — 등록 상태가 아님, 지정상품(유사군) 없음, 견본 링크
    없음."""
    status = detail.get("register_status") or item.get("ApplicationStatus")
    if status != "등록":
        return f"등록 상태가 아님({status or '상태 없음'})"
    if not detail.get("similarity_codes"):
        return "지정상품(유사군) 없음"
    if not detail.get("image_url"):
        return "견본 링크 없음"
    return None


class Stop(Exception):
    """받기를 멈추는 까닭."""


class Fetcher:
    def __init__(self, args, state: dict):
        if not args.key_env:
            raise SystemExit("--key-env 가 필요합니다(.env 의 공용 키로는 부르지 않습니다)")
        if not args.counter:
            raise SystemExit("--counter 가 필요합니다(키별 호출 카운터 파일)")
        from backend.scripts import collect_pipeline as cp
        from backend.src.core import kipris_client as kc

        self.cp, self.kc, self.args, self.state = cp, kc, args, state
        self.info = cp.use_key_and_counter(key_env=args.key_env, counter=args.counter)
        self.secret = kc.ACCESS_KEY
        self.streak = 0
        self.rows: list[tuple] = []
        self.extras: list[dict] = []
        self.done: list[str] = []

    def _count(self) -> None:
        if self.state["세션"]["호출"] >= self.args.max_calls:
            raise Stop(f"세션 상한 {self.args.max_calls}회")
        self.state["세션"]["호출"] += 1

    def _raw(self, call, label: str) -> str:
        """호출 한 번 — 원본을 먼저 남기고(키 값은 지움) resultCode 를 직접 읽는다."""
        kc = self.kc
        self._count()
        try:
            raw = call()
        except kc.CallBudgetExceeded as exc:
            self.state["세션"]["호출"] -= 1
            raise Stop(f"카운터 예산: {cand.scrub(exc, self.secret)}") from None
        self.cp.save_raw_xml(label, cand.scrub(raw, self.secret))
        code = _RESULT_CODE.search(raw)
        if code and code.group(1) != "00":
            message = _RESULT_MESSAGE.search(raw)
            raise kc.KiprisError(
                f"resultCode {code.group(1)} {message.group(1) if message else ''}".strip(),
                result_code=code.group(1))
        time.sleep(CALL_PAUSE_S)
        return raw

    def flush(self) -> None:
        if not self.rows:
            return
        cp = self.cp
        cp.merge_file_staging_rows(self.rows, self.args.staging,
                                   extra={cp.SOURCE_LABEL_FIELD: SOURCE_LABEL},
                                   row_extras=self.extras)
        cp.update_checkpoint(self.done, path=cp.staging_checkpoint_path(self.args.staging))
        self.rows, self.extras, self.done = [], [], []

    def one(self, row: dict, item: dict | None) -> dict:
        """표장 하나 — 결과 기록을 돌려준다. 멈춰야 하면 Stop."""
        cp, kc = self.cp, self.kc
        appno = row["출원번호"]
        record = {"브랜드": row["브랜드"], "역할": row["역할"], "국제등록": row["국제등록"],
                  "때": _now(), "호출": 0}
        try:
            if item is None:  # 직접 적은 출원번호 — 출원번호 검색으로 상표명·출원인·날짜
                record["호출"] += 1
                raw = self._raw(lambda: kc.advanced_search_by_number_raw(
                    appno, kind="application"), f"number_{appno}")
                found = [cand.normalize_item(entry, kc.normalize_advanced_item)
                         for entry in kc.parse_items(raw)]
                item = next((entry for entry in found
                             if str(entry.get("ApplicationNumber")) == appno), None)
                if item is None:
                    self.streak = 0
                    return {**record, "결과": "출원번호 검색에 그 번호가 없음"}
            record["호출"] += 1
            raw = self._raw(lambda: kc.bibliography_detail_raw(appno), f"biblio_{appno}")
            detail = kc.parse_bibliography_detail(raw)
        except kc.KiprisConfigError:
            raise
        except kc.KiprisError as exc:
            code = getattr(exc, "result_code", None)
            self.streak += 1
            record.update({"결과": f"서지 실패({type(exc).__name__}: "
                                 f"{cand.scrub(exc, self.secret)})", "resultCode": code})
            if code in cand.LIMIT_CODES:
                raise Stop(f"한도 초과 응답(resultCode {code})") from None
            if code in cand.AUTH_CODES:
                raise Stop(f"권한 오류(resultCode {code})") from None
            if self.streak >= ERROR_STREAK_STOP:
                self.state["표장"][appno] = record
                raise Stop(f"연속 오류 {ERROR_STREAK_STOP}회") from None
            return record
        record.update({
            "등록_상태": detail.get("register_status"), "표장_구분": detail.get("mark_type"),
            "유사군_수": len(detail.get("similarity_codes") or ()),
            "류": list(detail.get("nice_classes") or ()),
            "지정상품_수": len(detail.get("goods") or ()),
            "서지의_출원번호": detail.get("application_number")})
        reason = judge(detail, item)
        if reason:
            self.streak = 0
            return {**record, "결과": reason}
        dest = cp.staging_image_path(self.args.staging, f"{appno}.png")
        try:
            kc.download_file_now(detail["image_url"], dest, validate_image=True)
            self.state["세션"]["견본"] += 1
        except (kc.KiprisError, ValueError, OSError) as exc:
            self.streak += 1
            if self.streak >= ERROR_STREAK_STOP:
                self.state["표장"][appno] = {**record, "결과": f"견본 실패({type(exc).__name__})"}
                raise Stop(f"연속 오류 {ERROR_STREAK_STOP}회") from None
            return {**record, "결과": f"견본 실패({type(exc).__name__})"}
        self.streak = 0
        staged = staged_item(item, detail, cp.short_mark_kind)
        self.rows.append(cp.item_to_row(staged))
        international = item.get("InternationalNumber") if item.get("NumberIsReference") else None
        self.extras.append({"메모": f"국제등록 {international} — 출원번호는 참조번호"}
                           if international else {})
        self.done.append(appno)
        return {**record, "결과": DONE, "상표명": staged.get("Title") or None,
                "출원인": staged.get("ApplicantName")}


def command_plan(args) -> int:
    candidates = (json.loads(args.candidates.read_text(encoding="utf-8"))
                  if args.candidates.exists() else None)
    plan = fetch_plan(fc.load_overrides(), db_appnos(args.metadata), search_items(candidates))
    print(json.dumps(plan, ensure_ascii=False, indent=1))
    return 0


def summarize(state: dict, plan: dict) -> dict:
    marks = state["표장"]
    got = [appno for appno, record in marks.items() if record["결과"] == DONE]
    failed = {appno: record for appno, record in marks.items() if record["결과"] != DONE}
    pending = [row for row in plan["받을_표장"] if row["출원번호"] not in marks]
    return {
        "세션": {key: value for key, value in state["세션"].items() if key != "기록"},
        "실행_기록": state["세션"]["기록"],
        "받을_표장": len(plan["받을_표장"]) + len(got), "받음": len(got),
        "받음_역할별": dict(Counter(marks[appno]["역할"] for appno in got)),
        "받음_브랜드별": dict(Counter(marks[appno]["브랜드"] for appno in got)),
        "넣지_않음": [{"출원번호": appno, "브랜드": record["브랜드"], "역할": record["역할"],
                    "국제등록": record.get("국제등록"), "까닭": record["결과"]}
                   for appno, record in failed.items()],
        "아직_안_받음": [{"출원번호": row["출원번호"], "브랜드": row["브랜드"], "역할": row["역할"]}
                     for row in pending if row["출원번호"] not in got],
    }


def command_status(args) -> int:
    candidates = (json.loads(args.candidates.read_text(encoding="utf-8"))
                  if args.candidates.exists() else None)
    plan = fetch_plan(fc.load_overrides(), db_appnos(args.metadata), search_items(candidates))
    print(json.dumps(summarize(load_state(args.state), plan), ensure_ascii=False, indent=1))
    return 0


def command_run(args) -> int:
    candidates = (json.loads(args.candidates.read_text(encoding="utf-8"))
                  if args.candidates.exists() else None)
    items = search_items(candidates)
    plan = fetch_plan(fc.load_overrides(), db_appnos(args.metadata), items)
    state = load_state(args.state)
    fetcher = Fetcher(args, state)
    cp = fetcher.cp
    ready, error = cp.inspect_file_staging(args.staging)
    if not ready:
        raise SystemExit(f"파일 스테이징 점검 실패: {error}")
    existing = cp.load_file_staging_app_numbers(args.staging)  # 스테이징 + 운영
    queue = [row for row in plan["받을_표장"] if row["출원번호"] not in existing
             and (not args.only or row["출원번호"] in set(args.only))
             and (args.retry or state["표장"].get(row["출원번호"], {}).get("결과") in (None,))]
    started = {"시작": _now(), "키": fetcher.info.get("키"), "카운터": fetcher.info.get("카운터"),
               "카운터_이번_달(시작)": fetcher.info.get("이번_달"),
               "호출(시작)": state["세션"]["호출"], "상한": args.max_calls, "대상": len(queue)}
    state["세션"]["기록"].append(started)
    print(f"[시작] {started['키']} · 카운터 이번 달 {started['카운터_이번_달(시작)']}회 · 세션 "
          f"{started['호출(시작)']}/{args.max_calls}회 · 대상 {len(queue)}건", flush=True)
    stopped = ""
    try:
        for row in queue:
            record = fetcher.one(row, items.get(row["출원번호"]))
            state["표장"][row["출원번호"]] = record
            print(f"  {row['출원번호']} {row['브랜드']} [{row['역할']}] → {record['결과']}",
                  flush=True)
            if len(fetcher.rows) >= SAVE_EVERY:
                fetcher.flush()
            save_state(args.state, state, fetcher.secret)
    except Stop as stop:
        stopped = str(stop)
        print(f"[멈춤] {stopped}", flush=True)
    finally:
        fetcher.flush()
        started.update({"끝": _now(), "호출(끝)": state["세션"]["호출"], "멈춤": stopped,
                        "카운터_이번_달(끝)": fetcher.kc.limiter.used_this_month()})
        save_state(args.state, state, fetcher.secret)
    ready, error = cp.inspect_file_staging(args.staging)
    summary = summarize(state, plan)
    print(f"[끝] 받음 {summary['받음']} · 넣지 않음 {len(summary['넣지_않음'])} · 세션 호출 "
          f"{state['세션']['호출']}회 · 카운터 이번 달 {started['카운터_이번_달(끝)']}회 · "
          f"스테이징 점검 {'통과' if ready else '실패: ' + str(error)}")
    return 3 if stopped or not ready else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("plan", "status", "run"))
    parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--candidates", type=Path, default=cand.DEFAULT_STATE)
    parser.add_argument("--key-env", metavar="NAME", help="키를 담은 환경 변수 이름(값이 아님)")
    parser.add_argument("--counter", type=Path, metavar="PATH", help="그 키의 호출 카운터 파일")
    parser.add_argument("--max-calls", type=int, default=300, help="세션 호출 상한(누계)")
    parser.add_argument("--only", nargs="+", metavar="출원번호", help="이 번호만(먼저 확인할 때)")
    parser.add_argument("--retry", action="store_true",
                        help="앞서 넣지 못한 것도 다시 받는다(호출을 다시 쓴다)")
    args = parser.parse_args(argv)
    return {"plan": command_plan, "status": command_status, "run": command_run}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
