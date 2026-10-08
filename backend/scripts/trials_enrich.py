"""심결례 정답 데이터 보강(다빈-1) — 상대 표장 상표명(KIPRIS 출원속보)·양쪽 지정상품 유사군·X4.

실행 (프로젝트 루트에서. 실호출은 lookup 뿐이고 dry-run 계획표를 본 뒤 사람이 결정한다):
    ml/venv/bin/python -m backend.scripts.trials_enrich targets             # A. 대상 정리(호출 0)
    ml/venv/bin/python -m backend.scripts.trials_enrich lookup --dry-run    # B. 계획표(호출 0)
    KIPRIS_DAILY_BUDGET=400 ml/venv/bin/python -m backend.scripts.trials_enrich lookup \
        --max-calls 400                                                      # 실호출(사람이 결정)
    ml/venv/bin/python -m backend.scripts.trials_enrich goods     # C. 지정상품→유사군→X4(호출 0)
    ml/venv/bin/python -m backend.scripts.trials_enrich status              # 집계

A. 대상 = labels.csv 에서 pass a·b 가 일치하고 유사·비유사인 행. 상대 표장을 범주로 나눈다:
   선등록·선출원(번호 있음) / 국제등록 / 선사용(번호 없음) / 확인대상표장(번호 없음). 번호는
   kipris_metadata.json 형식(13자리, 하이픈 없음: 등록 40+7자리+0000, 출원 40+연도+7자리)으로 정규화
   하고 심결문 문구(상표등록/서비스표등록/국제등록)로 접두 40·41·45·국제를 정한다. 번호가 없는
   확인대상표장·선사용상표는 기초사실의 "(1) 구성 : …" 같은 줄 글자 또는 판단 절의 "확인대상표장은
   ‘…’로 구성" 문장에서 명칭을 뽑아 상대표장_명칭_본문 에, 없으면 ①의 OCR(image_parts.csv)을
   상대표장_명칭_ocr 에 적는다. → enrich_targets.csv, labels.csv(보존 병합).
B. lookup: 고유 번호마다 출원속보 getAdvancedSearch 1회(kipris_client.advanced_search_by_number_raw,
   키 KIPRIS_ACCESS_KEY, 현수 리미터·카운터 공유). 번호 종류마다 첫 1건으로 파라미터명·형식을
   검증한다(13자리가 0건이면 하이픈 형식으로 1회 더, 그래도 0건이면 그 종류를 건너뜀). 응답 원본은
   enrich_raw/ 에, 결과는 prior_marks.csv(Title·ApplicationNumber·RegistrationNumber·
   GoodClassificationCode·ViennaCode·ApplicantName)에. 이미 있는 번호는 건너뛰고(멱등), 이번 실행
   집계는 enrich_calls.json 에. 이미지는 내려받지 않는다.
   → labels.csv 상대표장_명칭_kipris.
C. goods: 심결문 기초사실에서 이 사건 표장·상대 표장의 "(3) 지정상품"(권리범위확인은 확인대상표장의
   "사용상품") 목록을 뽑아 쉼표·중점·줄바꿈으로 나누고, goods_map codes_for(정확·alias) → 실패하면
   search 상위 1건(정확·접두 일치만, 부분 일치는 실패)으로 유사군에 대응 → goods_codes_this·
   goods_codes_prior(; 구분) 와 X4 자카드 x4_goods. "별지N과 같다"는 [별지N] 절에서 읽는다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.scripts import trials_collect as tc  # noqa: E402
from backend.src.core import kipris_client as kc  # noqa: E402
from backend.src.core import paths  # noqa: E402

if str(paths.ML_ROOT) not in sys.path:
    sys.path.insert(0, str(paths.ML_ROOT))

from scripts.trials_extract_images import _HEADING_LINE_RE, classify_heading  # noqa: E402
from src.axes.goods_map import TIER_PREFIX, load_goods_map  # noqa: E402
from src.axes.x4_goods import goods_similarity  # noqa: E402

POSITIVE = ("유사", "비유사")
HARD_CAP = 400
CATEGORY_NUMBERED = "선등록·선출원(번호 있음)"
CATEGORY_INTL = "국제등록"
CATEGORY_USE = "선사용(번호 없음)"
CATEGORY_TARGET = "확인대상표장(번호 없음)"
CATEGORY_UNCONVERTIBLE = "번호 변환 불가"
CATEGORY_OTHER = "번호 없음(기타)"
TARGET_COLUMNS = [
    "심판번호", "종류", "상표B_번호", "상대표장_유형", "범주", "번호종류", "번호_정규화", "문구",
    "명칭_본문", "명칭_ocr", "후보번호",
]
PRIOR_MARK_COLUMNS = [
    "번호종류", "번호_정규화", "결과", "건수", "Title", "ApplicationNumber", "RegistrationNumber",
    "GoodClassificationCode", "ViennaCode", "ApplicantName", "조회일시", "오류",
]
NUMBER_PREFIX = {"서비스표": "41", "상표서비스표": "45"}
_WORDING_RE = re.compile(
    r"((?:상표\s*서비스표|서비스표|상표|국제\s*상표|국제)\s*등록)\s*제\s*([\d\-]+)\s*호"
    r"|국제\s*상표\s*(\d{6,8})"
)
_INLINE_NAME_RE = re.compile(
    r"(?m)^[ \t]*(?:\(\s*[\d가-힣]\s*\)|[\d가-힣]\))?[ \t]*(?:구\s*성|표\s*장)[ \t]*[:：][ \t]*"
    r"(\S[^\n]*)$"
)
_TARGET_SENTENCE_RE = re.compile(
    r"확인\s*대상\s*표장은[^\n.]{0,30}?[‘“\"']([^’”\"'\n]{1,30})[’”\"']"
)
_PRIOR_USE_SENTENCE_RE = re.compile(
    r"선\s*사용\s*(?:상표|서비스표)[^\n.]{0,30}?[‘“\"']([^’”\"'\n]{1,30})[’”\"']"
)
_NAME_NOISE_RE = re.compile(r"표장|상표|사건|이하|같다|구성|도형|기재|별지|\(\d+\)")
_GOODS_WORD = (
    r"(?:지정|사용)\s*(?:상품|서비스업?)(?:\s*/\s*서비스업|\s*\(\s*서비스(?:업)?\s*\))?[^:：\n]{0,6}"
    r"[:：]?[ \t]*"
)
_GOODS_HEAD_RE = re.compile(_GOODS_WORD)
# 항목 줄머리("(3) 지정상품 :")를 먼저 찾고, 없으면 본문 어디든
_GOODS_LINE_RE = re.compile(
    r"(?m)^[ \t]*(?:\(\s*[\d가-힣]\s*\)|[\d가-힣]\))[ \t]*" + _GOODS_WORD
)
_ITEM_BREAK_RE = re.compile(
    r"\n\s*(?:\(\d+\)|\([가-힣]\)|[가-힣]\.\s|\d+\.\s*[가-힣(]|[\d가-힣]\)\s)"
)
_APPENDIX_REF_RE = re.compile(  # "별지와 같다"·"[별지3]과 같다"·"별지1.과 같다"·"별지 기재와 같다"
    r"[\[<【(]?\s*별\s*지\s*(\d*)\s*\.?\s*[\]>】)’”\"']?\s*(?:기재|목록)?\s*(?:과|와|에)?\s*같"
)
_CLASS_RE = re.compile(r"(?:(?:상품|서비스업)\s*류\s*(?:구분)?\s*)?제?\s*(\d{1,2})\s*류\s*의?")
_SPLIT_RE = re.compile(r"[,，、;；·ㆍ]")
_LATIN_PAREN_RE = re.compile(r"\s*\([^()]*[A-Za-z][^()]*\)")  # "사탕(sweets)" 의 영문 괄호
_FACTS_START = r"(?m)^\s*\d+\.\s*기\s*초\s*사\s*실"
# 기초사실의 끝 = 글자로 시작하는 다음 최상위 번호 제목("2. 당사자의 주장"). 날짜 이어쓰기
# "1./1996. 2. 5." 는 제목이 아니다(trials_collect._TOP_HEADING 은 이를 제목으로 본다 — ①과 같은
# 수정)
_FACTS_END = r"(?m)^\s*\d+\.\s*[가-힣A-Za-z(\[]"


def now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def target_rows(rows: list[dict]) -> list[dict]:
    """pass a·b 가 일치하고 유사·비유사인 행(labels.csv 순서)."""
    return [
        r for r in rows
        if r.get("유사여부_확정") in POSITIVE and r.get("유사여부_확정") == r.get("llm_b_유사여부")
    ]


# ---- A. 번호 정규화·범주 ----

def number_wordings(text: str) -> dict[str, str]:
    """심결문에서 번호 → 문구(상표/서비스표/상표서비스표/국제). 처음 나온 문구를 쓴다."""
    found: dict[str, str] = {}
    for match in _WORDING_RE.finditer(text):
        if match.group(3):
            digits, wording = tc._digits(match.group(3)), "국제"
        else:
            digits = tc._digits(match.group(2))
            head = re.sub(r"\s+", "", match.group(1))
            if head.startswith("국제"):
                wording = "국제"
            elif head.startswith("상표서비스표"):
                wording = "상표서비스표"
            elif head.startswith("서비스표"):
                wording = "서비스표"
            else:
                wording = "상표"
        if digits and digits not in found:
            found[digits] = wording
    return found


def normalize_number(number: str, wording: str = "") -> tuple[str, str]:
    """(번호종류, 정규화 번호). 종류 registration|application|international|unknown|''.

    kipris_metadata.json 형식: 등록번호 '4000073530000'(40 + 7자리 + 0000), 출원번호
    '4019620001630'(40 + 연도 + 7자리). 13자리는 끝 0000·연도 자리로 가르고, 7자리 이하는 등록번호로
    보고 문구에 따라 접두 40(상표)·41(서비스표)·45(상표서비스표)를 붙인다. 국제등록번호는 그대로.
    """
    digits = tc._digits(number or "")
    if not digits:
        return "", ""
    if wording == "국제":
        return "international", digits
    if len(digits) == 13 and digits[:2] in {"40", "41", "42", "43", "44", "45"}:
        year = int(digits[2:6])
        if 1946 <= year <= 2030 and not digits.endswith("0000"):
            return "application", digits
        if digits.endswith("0000"):
            return "registration", digits
        return "application", digits
    if len(digits) <= 7:
        prefix = NUMBER_PREFIX.get(wording, "40")
        return "registration", f"{prefix}{int(digits):07d}0000"
    return "unknown", digits


def categorize(row: dict, wordings: dict[str, str]) -> dict:
    kinds = (row.get("상대표장_유형") or "").split("|")
    digits = tc._digits(row.get("상표B_번호") or "")
    wording = wordings.get(digits, "")
    if (row.get("종류") or "").startswith("권리범위확인"):
        return {"범주": CATEGORY_TARGET, "번호종류": "", "번호_정규화": "", "문구": ""}
    if digits:
        kind, normalized = normalize_number(digits, wording)
        if kind == "international":
            category = CATEGORY_INTL
        elif kind in ("registration", "application"):
            category = CATEGORY_NUMBERED
        else:
            category = CATEGORY_UNCONVERTIBLE
        return {"범주": category, "번호종류": kind, "번호_정규화": normalized, "문구": wording}
    if "선사용" in kinds:
        return {"범주": CATEGORY_USE, "번호종류": "", "번호_정규화": "", "문구": ""}
    return {"범주": CATEGORY_OTHER, "번호종류": "", "번호_정규화": "", "문구": ""}


# ---- A. 본문 명칭 ----

def clean_name(value: str) -> str:
    text = (value or "").strip().strip("‘’“”\"'「」『』 ").strip()
    if not text or len(text) > 30 or _NAME_NOISE_RE.search(text):
        return ""
    return text


def facts_text(text: str) -> str:
    """기초사실 절. 제목이 없는 문서는 첫 표장 제목부터 끝까지(주문·청구취지는 뺀다)."""
    stripped = tc._strip_footnotes(text)
    found = tc._find_block(stripped, _FACTS_START, (_FACTS_END,))
    if found:
        return found
    for match in re.finditer(r"(?m)^[^\n]*$", stripped):
        heading = _HEADING_LINE_RE.match(match.group(0))
        if heading and classify_heading(heading.group(2)):
            return stripped[match.start():]
    return stripped


def mark_blocks(text: str) -> list[dict]:
    """기초사실의 표장 블록 [{kind, role, heading, text}] — 제목 분류는 ① 의 classify_heading."""
    facts = facts_text(text)
    blocks: list[dict] = []
    current: dict | None = None
    for line in facts.splitlines():
        heading = _HEADING_LINE_RE.match(line)
        classified = classify_heading(heading.group(2)) if heading else None
        if classified:
            kind, provisional, number = classified
            if current is not None:
                # 묶음 제목("선등록상표들") 바로 아래 같은 종류의 하위 제목이 오면 묶음은 버린다.
                # 하위 제목 없이 본문이 이어지면(표 형식) 묶음 블록을 그대로 쓴다.
                if not (current["provisional"] and current["kind"] == kind and not provisional):
                    blocks.append(current)
            current = {"kind": kind, "heading": line.strip(), "text": "", "number": number,
                       "provisional": provisional}
            continue
        if current is not None:
            current["text"] += line + "\n"
    if current is not None:
        blocks.append(current)
    prior_count = target_count = 0
    for block in blocks:
        if block["kind"] == "this":
            block["role"] = "this"
        elif block["kind"] == "target":
            target_count += 1
            block["role"] = "target" if target_count == 1 else f"target_{target_count}"
        else:
            hint = int(block["number"]) if block["number"] else 0
            prior_count = max(prior_count + 1, hint)
            block["role"] = f"prior_{prior_count}"
    return blocks


def body_name(text: str, blocks: list[dict], category: str) -> str:
    """번호 없는 상대 표장의 명칭: 블록의 '구성 : …' 같은 줄 글자 → 판단 절의 따옴표 문장."""
    if category == CATEGORY_TARGET:
        kind, sentence = "target", _TARGET_SENTENCE_RE
    elif category == CATEGORY_USE:
        kind, sentence = "prior", _PRIOR_USE_SENTENCE_RE
    else:
        return ""
    for block in blocks:
        if block["kind"] != kind:
            continue
        if kind == "prior" and "선사용" not in block["heading"].replace(" ", ""):
            continue
        match = _INLINE_NAME_RE.search(block["text"])
        if match:
            name = clean_name(match.group(1))
            if name:
                return name
        break
    for match in sentence.finditer(text):
        name = clean_name(match.group(1))
        if name:
            return name
    return ""


def ocr_names(base: Path) -> dict[tuple[str, str], str]:
    path = base / "image_parts.csv"
    if not path.exists():
        return {}
    return {(r["심판번호"], r["role"]): r.get("ocr_text", "") for r in tc._read_csv(path)}


def counterpart_role(base: Path) -> dict[tuple[str, str], str]:
    path = base / "image_pairs_v1.csv"
    if not path.exists():
        path = base / "image_pairs.csv"
    if not path.exists():
        return {}
    return {
        (r["심판번호"], r.get("상대번호", "")): r.get("상대role", "") for r in tc._read_csv(path)
    }


def build_targets(paths_: tc.TrialPaths, rows: list[dict]) -> list[dict]:
    ocr = ocr_names(paths_.base)
    roles = counterpart_role(paths_.base)
    cache: dict[str, tuple[str, dict[str, str], list[dict]]] = {}
    targets: list[dict] = []
    for row in rows:
        number = row["심판번호"]
        if number not in cache:
            path = paths_.text_dir / f"{number}.txt"
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            cache[number] = (text, number_wordings(text), mark_blocks(text))
        text, wordings, blocks = cache[number]
        info = categorize(row, wordings)
        name_body = body_name(text, blocks, info["범주"])
        name_ocr = ""
        if info["범주"] in (CATEGORY_TARGET, CATEGORY_USE):
            role = roles.get((number, row.get("상표B_번호", "")), "")
            if not role and info["범주"] == CATEGORY_TARGET:
                role = "target"
            name_ocr = ocr.get((number, role), "") if role else ""
        targets.append({
            "심판번호": number, "종류": row.get("종류", ""),
            "상표B_번호": row.get("상표B_번호", ""),
            "상대표장_유형": row.get("상대표장_유형", ""), **info, "명칭_본문": name_body,
            "명칭_ocr": name_ocr, "후보번호": row.get("상대표장_번호_후보", ""),
        })
    return targets


def targets_summary(targets: list[dict]) -> dict:
    categories: dict[str, int] = {}
    for item in targets:
        categories[item["범주"]] = categories.get(item["범주"], 0) + 1
    numbered = {
        (item["번호종류"], item["번호_정규화"]) for item in targets
        if item["범주"] in (CATEGORY_NUMBERED, CATEGORY_INTL)
    }
    unconvertible = sorted({
        item["상표B_번호"] for item in targets if item["범주"] == CATEGORY_UNCONVERTIBLE
    })
    unnumbered = [t for t in targets if t["범주"] in (CATEGORY_TARGET, CATEGORY_USE)]
    candidates = sum(1 for t in targets if not t["번호_정규화"] and t["후보번호"])
    return {
        "대상_행": len(targets), "범주": categories,
        "고유_번호": {
            kind: sum(1 for k, _ in numbered if k == kind)
            for kind in ("registration", "application", "international")
        },
        "변환_불가": unconvertible,
        "번호없음_명칭": {
            "행": len(unnumbered),
            "본문": sum(1 for t in unnumbered if t["명칭_본문"]),
            "ocr만": sum(1 for t in unnumbered if not t["명칭_본문"] and t["명칭_ocr"]),
            "없음": sum(1 for t in unnumbered if not t["명칭_본문"] and not t["명칭_ocr"]),
        },
        "후보번호만_있는_행": candidates,
    }


# ---- labels.csv 병합(보존) ----

def merge_into_labels(paths_: tc.TrialPaths, updates: dict[tuple[str, str], dict[str, str]]) -> int:
    """(심판번호, 상표B_번호) → {열: 값} 을 labels.csv 에 잠금·원자적 쓰기로 넣는다. 다른 열은
    그대로 둔다."""
    with tc._labels_lock(paths_):
        fieldnames, rows = tc._load_labels(paths_)
        changed = 0
        for row in rows:
            values = updates.get((row["심판번호"], row.get("상표B_번호", "")))
            if not values:
                continue
            for column, value in values.items():
                if column not in fieldnames:
                    fieldnames.append(column)
                if row.get(column, "") != value:
                    row[column] = value
                    changed += 1
        for row in rows:
            for column in fieldnames:
                row.setdefault(column, "")
        tc._write_csv_atomic(paths_.labels_csv, fieldnames, rows)
    return changed


def run_targets(paths_: tc.TrialPaths) -> dict:
    labels = tc._read_csv(paths_.labels_csv)
    rows = target_rows(labels)
    targets = build_targets(paths_, rows)
    tc._write_csv(paths_.base / "enrich_targets.csv", TARGET_COLUMNS, targets)
    updates = {
        (t["심판번호"], t["상표B_번호"]): {
            "상대표장_번호_정규화": t["번호_정규화"], "상대표장_명칭_본문": t["명칭_본문"],
            "상대표장_명칭_ocr": t["명칭_ocr"],
        }
        for t in targets
    }
    changed = merge_into_labels(paths_, updates)
    summary = targets_summary(targets)
    summary["labels_갱신_칸"] = changed
    return summary


# ---- B. KIPRIS 조회 ----

def load_prior_marks(paths_: tc.TrialPaths) -> list[dict]:
    path = paths_.base / "prior_marks.csv"
    return tc._read_csv(path) if path.exists() else []


def format_variants(kind: str, number: str) -> list[str]:
    """검증용 형식 후보: 13자리 그대로 → 하이픈(등록 40-0666832-0000, 출원 40-2012-0012345)."""
    variants = [number]
    if kind == "registration" and len(number) == 13:
        variants.append(f"{number[:2]}-{number[2:9]}-{number[9:]}")
    elif kind == "application" and len(number) == 13:
        variants.append(f"{number[:2]}-{number[2:6]}-{number[6:]}")
    return variants


def lookup_plan(targets: list[dict], existing: list[dict], *,
                include_candidates: bool = False, retry_empty: bool = False) -> dict:
    done = {
        (r["번호종류"], r["번호_정규화"]) for r in existing
        if not (retry_empty and r.get("결과") in ("0건", "오류"))
    }
    wanted: dict[str, list[str]] = {"registration": [], "application": [], "international": []}
    for item in targets:
        kind, number = item["번호종류"], item["번호_정규화"]
        if kind in wanted and number and number not in wanted[kind]:
            wanted[kind].append(number)
        if include_candidates and not number and item["후보번호"]:
            for candidate in item["후보번호"].split(";"):
                c_kind, c_number = normalize_number(candidate)
                if c_kind in wanted and c_number and c_number not in wanted[c_kind]:
                    wanted[c_kind].append(c_number)
    plan = {}
    for kind, numbers in wanted.items():
        to_call = [n for n in numbers if (kind, n) not in done]
        plan[kind] = {
            "고유": len(numbers), "이미_있음": len(numbers) - len(to_call), "호출": to_call,
        }
    plan["예상_호출"] = sum(len(plan[k]["호출"]) for k in wanted)
    return plan


def plan_table(plan: dict) -> str:
    """lookup_plan 결과 또는 report['계획'](호출이 수인 것) 둘 다 받는다."""
    lines = ["| 번호 종류 | 고유 번호 | 이미 조회 | 예상 호출 |", "|---|---|---|---|"]
    total = 0
    for kind in ("registration", "application", "international"):
        item = plan[kind]
        calls = item["호출"] if isinstance(item["호출"], int) else len(item["호출"])
        total += calls
        lines.append(f"| {kind} | {item['고유']} | {item['이미_있음']} | {calls} |")
    lines.append(f"| **합계** | | | **{total}** |")
    return "\n".join(lines)


def pick_item(items: list[dict], kind: str, number: str) -> dict | None:
    key = "RegistrationNumber" if kind == "registration" else "ApplicationNumber"
    for item in items:
        if tc._digits(item.get(key, "")) == number:
            return item
    return items[0] if items else None


def lookup_one(kind: str, number: str, *, fetch=kc.advanced_search_by_number_raw,
               raw_dir: Path | None = None, send_as: str | None = None) -> dict:
    """번호 1건 조회 → prior_marks.csv 행. 오류는 사유와 함께 행으로 남긴다(호출은 소비됨).
    send_as 는 실제로 보내는 문자열(하이픈 형식 검증용), 행에는 정규화 번호를 적는다."""
    row = {column: "" for column in PRIOR_MARK_COLUMNS}
    row.update({"번호종류": kind, "번호_정규화": number, "조회일시": now_text()})
    try:
        xml_text = fetch(send_as or number, kind)
    except kc.CallBudgetExceeded:
        raise
    except kc.KiprisError as exc:
        row.update({"결과": "오류", "오류": f"{type(exc).__name__}: {exc}"[:200]})
        return row
    if raw_dir is not None:
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{kind}_{number}.xml").write_text(xml_text, encoding="utf-8")
    try:
        kc.check_result_code(xml_text)
        items = [kc.normalize_advanced_item(it) for it in kc.parse_items(xml_text)]
    except kc.KiprisError as exc:
        row.update({"결과": "오류", "오류": f"{type(exc).__name__}: {exc}"[:200]})
        return row
    row["건수"] = str(len(items))
    chosen = pick_item(items, kind, number)
    if chosen is None:
        row["결과"] = "0건"
        return row
    row.update({
        "결과": "ok", "Title": chosen.get("Title", ""),
        "ApplicationNumber": chosen.get("ApplicationNumber", ""),
        "RegistrationNumber": chosen.get("RegistrationNumber", ""),
        "GoodClassificationCode": "|".join(chosen.get("GoodClassificationCode") or []),
        "ViennaCode": "|".join(chosen.get("ViennaCode") or []),
        "ApplicantName": chosen.get("ApplicantName", ""),
    })
    return row


def run_lookup(paths_: tc.TrialPaths, *, max_calls: int = HARD_CAP, dry_run: bool = True,
               fetch=kc.advanced_search_by_number_raw, include_candidates: bool = False,
               retry_empty: bool = False) -> dict:
    targets_path = paths_.base / "enrich_targets.csv"
    if not targets_path.exists():
        raise SystemExit("enrich_targets.csv 가 없습니다 — targets 먼저")
    targets = tc._read_csv(targets_path)
    existing = load_prior_marks(paths_)
    plan = lookup_plan(targets, existing, include_candidates=include_candidates,
                       retry_empty=retry_empty)
    report: dict = {
        "계획": {
            k: {"고유": v["고유"], "이미_있음": v["이미_있음"], "호출": len(v["호출"])}
            for k, v in plan.items() if k != "예상_호출"
        },
        "예상_호출": plan["예상_호출"], "하드캡": max_calls, "dry_run": dry_run,
    }
    if dry_run:
        return report
    if plan["예상_호출"] > max_calls:
        raise SystemExit(f"예상 호출 {plan['예상_호출']} > 하드캡 {max_calls} — 중단")
    raw_dir = paths_.base / "enrich_raw"
    tally = {"일시": now_text(), "호출": 0, "ok": 0, "0건": 0, "오류": 0, "검증": {}, "중단": ""}
    new_rows: list[dict] = []
    try:
        for kind in ("registration", "application", "international"):
            numbers = plan[kind]["호출"]
            if not numbers:
                continue
            first = None
            send_as = {}
            for variant in format_variants(kind, numbers[0]):
                if tally["호출"] >= max_calls:
                    break
                first = lookup_one(kind, numbers[0], fetch=fetch, raw_dir=raw_dir,
                                   send_as=variant)
                tally["호출"] += 1
                tally[first["결과"] if first["결과"] in ("ok", "0건", "오류") else "오류"] += 1
                if first["결과"] == "ok":
                    send_as = {"hyphen": variant != numbers[0]}
                    break
            if first is None:
                break
            new_rows.append(first)
            if first["결과"] != "ok":
                tally["검증"][kind] = f"실패({first['결과']}) — 나머지 {len(numbers) - 1}건 건너뜀"
                continue
            tally["검증"][kind] = "ok" + ("(하이픈 형식)" if send_as.get("hyphen") else "")
            for number in numbers[1:]:
                if tally["호출"] >= max_calls:
                    tally["중단"] = f"하드캡 {max_calls} 도달"
                    break
                variant = format_variants(kind, number)[-1 if send_as.get("hyphen") else 0]
                row = lookup_one(kind, number, fetch=fetch, raw_dir=raw_dir, send_as=variant)
                tally["호출"] += 1
                tally[row["결과"] if row["결과"] in ("ok", "0건", "오류") else "오류"] += 1
                new_rows.append(row)
            if tally["중단"]:
                break
    except kc.CallBudgetExceeded as exc:
        tally["중단"] = f"예산 초과: {exc}"
    retried = {(r["번호종류"], r["번호_정규화"]) for r in new_rows}
    all_rows = [r for r in existing if (r["번호종류"], r["번호_정규화"]) not in retried] + new_rows
    tc._write_csv(paths_.base / "prior_marks.csv", PRIOR_MARK_COLUMNS, all_rows)
    log_path = paths_.base / "enrich_calls.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {"runs": []}
    log["runs"].append(tally)
    log["합계_호출"] = sum(run["호출"] for run in log["runs"])
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    report["이번_실행"] = tally
    report["병합"] = merge_kipris_names(paths_, targets, all_rows)
    return report


def merge_kipris_names(paths_: tc.TrialPaths, targets: list[dict], marks: list[dict]) -> dict:
    titles = {(m["번호종류"], m["번호_정규화"]): m.get("Title", "")
              for m in marks if m.get("결과") == "ok"}
    updates = {}
    for item in targets:
        title = titles.get((item["번호종류"], item["번호_정규화"]), "")
        if title:
            updates[(item["심판번호"], item["상표B_번호"])] = {"상대표장_명칭_kipris": title}
    changed = merge_into_labels(paths_, updates)
    return {"행": len(updates), "칸": changed}


# ---- C. 지정상품 → 유사군 ----

_APPENDIX_OPEN = r"[\[<【(]?\s*"
_APPENDIX_CLOSE = r"\s*[\]>】)]?"


def appendix_text(text: str, reference: str) -> str:
    """'별지N과 같다' → [별지N]·<별지N>·별지N 절(다음 별지 또는 문서 끝까지)."""
    number = re.escape(reference) if reference else r"\d*"
    pattern = r"(?m)^\s*" + _APPENDIX_OPEN + r"별\s*지\s*" + number + r"\s*\.?" + _APPENDIX_CLOSE
    next_header = (
        r"^\s*" + _APPENDIX_OPEN + r"별\s*지\s*\d*\s*\.?" + _APPENDIX_CLOSE + r"\s*$"
    )
    tail = r"[^\n]*\n(.*?)(?=" + next_header + r"|\Z)"
    match = re.search(pattern + tail, text, re.S)
    return match.group(1) if match else ""


class SpacelessIndex:
    """goods_map 의 name·alias 를 공백 없이 casefold 한 정확 일치 색인. PDF 텍스트는 명칭 안 공백이
    빠져 오므로("컴퓨터소프트웨어" vs 고시 "컴퓨터 소프트웨어") codes_for 다음에 한 번 더 찾는다."""

    def __init__(self, goods_map) -> None:
        self.table: dict[tuple[str, int], set[str]] = {}
        for entry in getattr(goods_map, "entries", []):
            for name in (entry.name, *entry.aliases):
                key = (self.key(name), entry.nice_class)
                self.table.setdefault(key, set()).update(entry.similarity_codes)

    @staticmethod
    def key(name: str) -> str:
        return re.sub(r"\s+", "", name or "").casefold()

    def codes_for(self, name: str, nice_class: int | None = None) -> frozenset[str]:
        key = self.key(name)
        if not key:
            return frozenset()
        if nice_class is not None:
            return frozenset(self.table.get((key, nice_class), set()))
        codes: set[str] = set()
        for (entry_key, _cls), values in self.table.items():
            if entry_key == key:
                codes.update(values)
        return frozenset(codes)


_SUBHEAD_RE = re.compile(r"(?m)^\s*[●○■□◆◇▪•ㅇo]\s*([^\n]*?(?:상표|서비스표|표장)[^\n]*)$")
_KIND_WORDS = {"this": ("이사건",), "prior": ("선등록", "선출원", "선사용", "인용"),
               "target": ("확인대상",)}


def _section_matches(header: str, block: dict) -> bool:
    """별지 소제목("●선등록상표 2의 지정상품", "●선등록상표 제40-737196호")이 블록을 가리키는가."""
    compact = re.sub(r"\s+", "", header)
    if not any(word in compact for word in _KIND_WORDS.get(block["kind"], ())):
        return False
    head_digits = [re.sub(r"\D", "", d) for d in re.findall(r"\d[\d\-]{4,}", compact)]
    if head_digits:
        block_digits = [
            re.sub(r"\D", "", d) for d in re.findall(r"\d[\d\-]{4,}", block["text"][:400])
        ]
        return any(
            h.endswith(b[-6:]) or b.endswith(h[-6:])
            for h in head_digits for b in block_digits if len(b) >= 5 and len(h) >= 5
        )
    ordinal = re.search(r"(?:상표|서비스표|표장)\s*(\d+)", compact)
    if ordinal:
        return bool(block["number"]) and ordinal.group(1) == str(block["number"])
    return True


def appendix_section(appendix: str, block: dict | None) -> str:
    """별지 절에 표장별 소제목이 있으면 소제목 줄을 떼고, 여럿이면 블록에 맞는 절만 남긴다."""
    heads = list(_SUBHEAD_RE.finditer(appendix))
    if not heads:
        return appendix
    sections: list[tuple[str, str]] = []
    prefix = appendix[:heads[0].start()]
    if prefix.strip():
        sections.append(("", prefix))
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(appendix)
        line = head.group(1)
        colon = re.search(r"[:：]", line)  # "●선등록상표2의지정상품: 상품류…" 는 콜론 뒤를 남긴다
        header = line[:colon.start()] if colon else line
        rest = (line[colon.end():] + "\n" if colon else "") + appendix[head.end():end]
        sections.append((header, rest))
    chosen = [rest for header, rest in sections if header and block is not None
              and _section_matches(header, block)]
    if len(sections) > 1 and chosen:
        return "\n".join(chosen)
    return "\n".join(rest for _, rest in sections)


def goods_text(block_text: str, full_text: str, block: dict | None = None) -> str:
    """블록의 지정상품/사용상품 줄부터 다음 항목 전까지. 별지 참조면 (블록에 맞는) 별지 절."""
    head = _GOODS_LINE_RE.search(block_text) or _GOODS_HEAD_RE.search(block_text)
    if not head:
        return ""
    rest = block_text[head.end():]
    stop = _ITEM_BREAK_RE.search(rest)
    body = rest[:stop.start()] if stop else rest
    reference = _APPENDIX_REF_RE.search(body)
    if reference:
        appendix = appendix_text(full_text, reference.group(1))
        if appendix:
            return appendix_section(appendix, block)
    return body


def split_goods(text: str) -> list[tuple[str, int | None]]:
    """'상품류 구분 제9류의 A, B·C' → [(A, 9), (B, 9), (C, 9)]. 줄바꿈은 PDF 줄 넘김이라 잇는다."""
    text = re.sub(r"\s*\n\s*", " ", text)
    items: list[tuple[str, int | None]] = []
    position = 0
    current_class: int | None = None
    markers = list(_CLASS_RE.finditer(text))
    segments: list[tuple[int | None, str]] = []
    for match in markers:
        segments.append((current_class, text[position:match.start()]))
        current_class = int(match.group(1))
        position = match.end()
    segments.append((current_class, text[position:]))
    for nice_class, segment in segments:
        for piece in _SPLIT_RE.split(segment):
            name = re.sub(r"\s+", " ", _LATIN_PAREN_RE.sub("", piece)).strip(" .:：-–—●○■□◆◇▪•")
            name = re.sub(r"^(?:및|그리고)\s+", "", name)
            name = re.sub(r"\s*등$", "", name)
            if len(name) < 2 or re.match(r"^(?:상품류|서비스업류|구분|별지)", name):
                continue
            items.append((name, nice_class))
    return items


def map_goods(names: list[tuple[str, int | None]], goods_map,
              spaceless: SpacelessIndex | None = None) -> tuple[set[str], list[dict]]:
    """codes_for(정확·alias) → 공백 무시 정확 → 류 무시 정확 → search 상위 1건(정확·접두만).
    (코드 집합, 상세)."""
    if spaceless is None:
        spaceless = SpacelessIndex(goods_map)
    codes: set[str] = set()
    details: list[dict] = []
    for name, nice_class in names:
        found = goods_map.codes_for(name, nice_class)
        method = "exact"
        if not found:
            found = spaceless.codes_for(name, nice_class)
            method = "exact(공백 무시)"
        if not found and nice_class is not None:
            found = goods_map.codes_for(name) or spaceless.codes_for(name)
            method = "exact(류 무시)"
        if not found:
            matches = goods_map.search(name, limit=1, nice_class=nice_class)
            if matches and matches[0].tier <= TIER_PREFIX:
                found = frozenset(matches[0].similarity_codes)
                method = f"search:{matches[0].name}"
        if found:
            codes.update(found)
            details.append(
                {"name": name, "class": nice_class, "codes": sorted(found), "method": method}
            )
        else:
            details.append({"name": name, "class": nice_class, "codes": [], "method": "fail"})
    return codes, details


def counterpart_block(row: dict, blocks: list[dict], ordinal: int) -> dict | None:
    if (row.get("종류") or "").startswith("권리범위확인"):
        return next((b for b in blocks if b["role"] == "target"), None)
    priors = [b for b in blocks if b["kind"] == "prior"]
    wanted = tc._digits(row.get("상표B_번호") or "")
    if wanted:
        for block in priors:
            if wanted in tc._registration_numbers(block["text"]):
                return block
    by_order = next((b for b in priors if b["role"] == f"prior_{ordinal}"), None)
    if by_order is not None:
        return by_order
    return priors[0] if ordinal == 1 and len(priors) == 1 else None


def run_goods(paths_: tc.TrialPaths, goods_map=None) -> dict:
    goods_map = goods_map or load_goods_map()
    spaceless = SpacelessIndex(goods_map)
    labels = tc._read_csv(paths_.labels_csv)
    rows = target_rows(labels)
    cache: dict[str, tuple[str, list[dict]]] = {}
    ordinal: dict[str, int] = {}
    updates: dict[tuple[str, str], dict[str, str]] = {}
    name_stats: dict[str, dict] = {}
    coverage = {"both": 0, "this만": 0, "prior만": 0, "none": 0, "상대_블록_없음": 0, "별지": 0}
    x4_by_label: dict[str, list[float]] = {"유사": [], "비유사": []}
    for row in rows:
        number = row["심판번호"]
        ordinal[number] = ordinal.get(number, 0) + 1
        if number not in cache:
            path = paths_.text_dir / f"{number}.txt"
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            cache[number] = (text, mark_blocks(text))
        text, blocks = cache[number]
        this = next((b for b in blocks if b["kind"] == "this"), None)
        other = counterpart_block(row, blocks, ordinal[number])
        sides = {}
        for key, block in (("this", this), ("prior", other)):
            if block is None:
                sides[key] = set()
                if key == "prior":
                    coverage["상대_블록_없음"] += 1
                continue
            raw = goods_text(block["text"], text, block)
            if _APPENDIX_REF_RE.search(block["text"]):
                coverage["별지"] += 1
            names = split_goods(raw)
            codes, details = map_goods(names, goods_map, spaceless)
            for detail in details:
                stat = name_stats.setdefault(
                    detail["name"], {"n": 0, "ok": detail["method"] != "fail"}
                )
                stat["n"] += 1
            sides[key] = codes
        this_codes, prior_codes = sides["this"], sides["prior"]
        if this_codes and prior_codes:
            coverage["both"] += 1
            x4 = goods_similarity(this_codes, prior_codes)
            x4_by_label[row["유사여부_확정"]].append(x4)
            x4_text = f"{x4:.4f}"
        else:
            coverage["this만" if this_codes else ("prior만" if prior_codes else "none")] += 1
            x4_text = ""
        updates[(number, row.get("상표B_번호", ""))] = {
            "goods_codes_this": ";".join(sorted(this_codes)),
            "goods_codes_prior": ";".join(sorted(prior_codes)), "x4_goods": x4_text,
        }
    changed = merge_into_labels(paths_, updates)
    mapped = sum(1 for s in name_stats.values() if s["ok"])
    failures = sorted(
        ((s["n"], name) for name, s in name_stats.items() if not s["ok"]), reverse=True
    )
    report = {
        "대상_행": len(rows),
        "명칭": {
            "고유": len(name_stats), "매핑": mapped,
            "매핑률": round(mapped / len(name_stats), 3) if name_stats else None,
        },
        "실패_상위20": [{"명칭": name, "횟수": n} for n, name in failures[:20]],
        "행_커버리지": coverage,
        "x4": {label: _dist(values) for label, values in x4_by_label.items()},
        "labels_갱신_칸": changed,
    }
    (paths_.base / "enrich_goods_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def _dist(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {
        "n": len(values), "평균": round(sum(values) / len(values), 4),
        "중앙값": round(ordered[len(ordered) // 2], 4),
        "0인_비율": round(sum(1 for v in values if v == 0) / len(values), 3),
    }


# ---- status ----

def run_status(paths_: tc.TrialPaths) -> dict:
    labels = tc._read_csv(paths_.labels_csv)
    rows = target_rows(labels)
    name_columns = ("상대표장_명칭_kipris", "상대표장_명칭_본문", "상대표장_명칭_ocr")
    named = sum(1 for r in rows if any(r.get(c) for c in name_columns))
    kipris = sum(1 for r in rows if r.get("상대표장_명칭_kipris"))
    marks = load_prior_marks(paths_)
    results = {}
    for mark in marks:
        results[mark["결과"]] = results.get(mark["결과"], 0) + 1
    log_path = paths_.base / "enrich_calls.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {"runs": []}
    return {
        "대상_행": len(rows),
        "상표명_확보": {
            "행": named, "비율": round(named / len(rows), 3) if rows else None, "kipris": kipris,
        },
        "prior_marks": {"행": len(marks), "결과": results},
        "x4_있음": sum(1 for r in rows if r.get("x4_goods")),
        "호출_누계": log.get("합계_호출", 0), "실행_횟수": len(log.get("runs", [])),
    }


# ---- CLI ----

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", type=Path, default=tc.DEFAULT_PATHS.base)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("targets", help="A. 대상 정리(호출 0)")
    lookup = sub.add_parser("lookup", help="B. KIPRIS 번호 조회")
    lookup.add_argument("--dry-run", action="store_true", help="계획표만(호출 0)")
    lookup.add_argument("--max-calls", type=int, default=HARD_CAP, help=f"하드캡(기본 {HARD_CAP})")
    lookup.add_argument("--include-candidates", action="store_true", help="후보 번호도 조회")
    lookup.add_argument("--retry-empty", action="store_true", help="0건·오류였던 번호 다시 조회")
    sub.add_parser("goods", help="C. 지정상품 → 유사군 → X4(호출 0)")
    sub.add_parser("status", help="집계")
    args = parser.parse_args(argv)
    paths_ = tc.TrialPaths(args.base)
    if args.command == "targets":
        report = run_targets(paths_)
    elif args.command == "lookup":
        report = run_lookup(paths_, max_calls=min(args.max_calls, HARD_CAP), dry_run=args.dry_run,
                            include_candidates=args.include_candidates,
                            retry_empty=args.retry_empty)
        if args.dry_run:
            print(plan_table(report["계획"]))
            print("호출 0회(dry-run). 예상 호출이 하드캡 이하일 때만 실호출:",
                  "가능" if report["예상_호출"] <= report["하드캡"] else "초과 — 중단")
            return 0
    elif args.command == "goods":
        report = run_goods(paths_)
    else:
        report = run_status(paths_)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
