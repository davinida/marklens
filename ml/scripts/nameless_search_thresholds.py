"""이름 없는 입력(이미지만·이미지+지정상품)의 등급 하한 — 실제 검색 기준. 표본 A(심사를 거치지 않은
표장)로 정하고 표본 B(DB 질의)로 나란히 확인한다. 서비스 v1.4 반영(2026-11-20, 통합 모델 설계
§7-4-4). 계수는 그대로, 이름 있는 입력의 계수·하한도 그대로. KIPRIS 호출 0.

    ml/venv/bin/python ml/scripts/nameless_search_thresholds.py --precheck  # 0. 사전 점검
    ml/venv/bin/python ml/scripts/nameless_search_thresholds.py             # 1. 계산·JSON·평가
    # → ml/data/trials/nameless_search_ab_{precheck,report}.md·…json, shared/model/
    #   risk_model_v1.4.json (실제 CLIP·OCR·관념 모델; 사전 점검 약 6분, 계산 약 25분)

표본 A: 정답 데이터(1·2차, 유사·비유사 행)의 거절결정불복 사건 출원 표장(this)과 권리범위확인 사건
확인대상표장(target) 가운데 DB 에 없는 것(번호 대조) — 사진 판정·짧은 변 64px 미만·이름 없음은
뺀다. 실제 사용자의 질의처럼 아직 등록되지 않은 표장이다. 표본 B: DB 레코드 300건(seed 0, 앞의
시도와 같다). 두 표본 모두 같은 출원인(정규화) 후보를 뺀다 — 실제 사용자 질의에는 형제 표장이 없다.

앞의 시도(2026-11-20, 표본 B + 심결 정밀도 위험 하한)는 순서 검사에서 멈췄다(규칙 sha256
a1a5ecb5…, 사본 ~/marklens-archive/nameless-search-attempt1-20261120/). 이 규칙은 심결 정밀도로
위험을 정하지 않는다.

순서: train_risk_model_v14_nameless.py(계수) → (nameless_grade_thresholds.py — 옛 방식 하한) →
이 스크립트. 앞의 두 스크립트는 같은 JSON 에 실제 검색 기준 하한이 있으면 --force 없이는 쓰지 않는다
(rm.check_nameless_overwrite, 종료 코드 4). --force 로 덮어썼으면 이 스크립트를 다시 돌린다(같은
입력이면 같은 값 — 이력은 겹쳐 쌓지 않는다). 엔진의 업종 하한(goods_floor)은 이 하한을 바꾸지 않는다
(판단 단계 규칙).
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import math
import os
import random
import statistics
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
for root in (ML_ROOT, REPO_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from src.model import risk_model as rm  # noqa: E402

from scripts import nameless_grade_thresholds as ngt  # noqa: E402
from scripts import train_risk_model as tr  # noqa: E402

DEFAULT_MODEL = rm.V14_MODEL_PATH
DEFAULT_V13 = rm.V13_MODEL_PATH
TRIALS = ML_ROOT / "data" / "trials"
DEFAULT_METADATA = ML_ROOT / "data" / "kipris_metadata.json"
DEFAULT_LABELS = TRIALS / "labels.csv"
DEFAULT_LIST = TRIALS / "list_all.csv"
DEFAULT_IMAGE_PAIRS = TRIALS / "image_pairs_v1.csv"
DEFAULT_ALIASES = REPO_ROOT / "shared" / "applicant_aliases.json"  # 출원인 별칭 표(사람 결정)
STEM = "nameless_search_ab"
SAMPLE_B, SEED = 300, 0
MIN_SHORT_SIDE = 64
SIMILARITY_MARGIN = 0.02  # 사전 점검: A 의 중앙값·상위 10% 가 둘 다 B 보다 이만큼 낮으면 멈춤
DISPLAY_TOP = 5  # 서비스 기본 표시 개수(API top_k 기본값)
FIGURE_CAVEAT = "로고 파일끼리 비교한 결과예요. 도형 유사는 검증 데이터가 적어 참고용이에요"
METHOD = "실제 검색 기준 — 표본 A(심사를 거치지 않은 표장), nameless_search_thresholds.py"
ATTEMPT1 = {"method": "실제 검색 1차 시도 — 표본 B(DB 300질의) + 심결 OOF 정밀도 위험",
            "rule_sha256": "a1a5ecb501cac8f41769368c9a01cd0b3d4ed6cfd7e3d6d9d7308521dbf91f7e",
            "result": ("순서 실패로 쓰지 않음 — 이미지만 주의 0.3525·검토 권장 0.4916·위험 "
                       "0.2987, 이미지+상품 0.3059·0.4464·0.3167")}
MODES = (("이미지만", "x2_whole", False), ("이미지+상품", "x2_whole+x4", True))
FULL = "이름+이미지+상품"
REVIEW = "검토 권장"
PREFIX = rm.NAMELESS_PREFIX
A_KINDS = {"거절결정불복": ("this", "청구인"),  # 종류 → (질의 이미지, 그 표장의 출원·사용자)
           "권리범위확인(적극적)": ("target", "피청구인"),
           "권리범위확인(소극적)": ("target", "청구인")}
EXCLUDE_ORDER = ("이미지 없음", "디코딩 실패", "DB에 있음", "이름 없음", "해상도", "사진",
                 "중복 이미지")
STOP_KEY = "유사도_멈춤(A 중앙값·상위10% 둘 다 B − 0.02 이하)"

# 규칙(계산 전에 고정) ---------------------------------------------------------------------------
RULE = {
    "표본_A": ("labels.csv 의 유사·비유사 행(1·2차)에서 거절결정불복 사건의 출원 표장(this.png, "
               "이름 상표A_명칭, 유사군 goods_codes_this, 출원인 청구인, 번호 상표A_번호·목록 "
               "출원번호·등록번호)과 권리범위확인 사건의 확인대상표장(target.png, 이름 "
               "pairs_features.name_b — kipris > llm > 본문 > ocr, 유사군 goods_codes_prior, "
               "출원인 적극적 피청구인·소극적 청구인, 번호 상대표장_번호_정규화). 사건마다 한 번, "
               "같은 이미지 바이트는 한 번. 뺄 것(이 순서로 첫 사유): 이미지 없음·디코딩 실패·"
               "번호가 DB 출원번호·등록번호에 있음·이름 없음·짧은 변 < "
               f"{MIN_SHORT_SIDE}px·사진 판정(서비스 임베딩)·중복 이미지. 이미지+상품 방식은 "
               "형식에 맞는 유사군이 있는 질의만"),
    "표본_B": ("DB 레코드 중 이미지·상표명·형식에 맞는 유사군이 있는 것을 출원번호 순으로 정렬해 "
               f"random.Random({SEED}).sample(…, {SAMPLE_B}) — 앞의 시도와 같은 질의. 검증용"),
    "검색": ("방식 ① 이미지만 ② 이미지 + 질의 유사군 — 서비스 엔진(multi_search.search_pool, "
             "기본 모델 v1.4)의 후보 풀 전부. 자기 자신(B)과 같은 출원인 후보(출원인 칸을 '|' 로 "
             "나눠 각각 정규화 = NFKC, '주식회사'·'(주)' 제거, 공백·문장부호 제거, 소문자 → "
             "출원인 별칭 표 shared/applicant_aliases.json 의 묶음은 한 출원인; 질의·후보 출원인이 "
             "하나라도 겹치면)를 뺀다. 상표명 없는 후보는 비교에서 뺀다(수를 보고)"),
    "두_번_채점": ("같은 쌍을 (a) 그 방식 입력 + 질의 이름(후보는 원래 상표명)으로 서비스 채점 "
                 "함수(score_record) — 유형은 서비스 규칙(이름 있으면 문자계, "
                 "_resolve_query_type), 사진 규칙 포함, 이름 있는 계수·하한(= v1.3)과 단독 "
                 "규칙까지 포함한 최종 등급 (b) 그 검색 응답의 후보 판단 그대로(이름 없는 계수, "
                 "유형은 OCR 로 도형계) — "
                 "위험도 p 와 도형 규칙(τ) 발동"),
    "하한": ("방식·표본마다 k_g = (a)의 최종 등급이 g 이상인 쌍 수. 주의·검토 권장: F = (b)에서 "
             "도형 규칙이 발동한 쌍(하한과 무관하게 검토 권장 이상), k′ = k_g − |F|, 하한 = F 밖 "
             "쌍의 p 가운데 k′번째로 큰 값의 소수 넷째 자리 내림; k′ ≤ 0 이면 null 로 두고 '도형 "
             "규칙만으로 목표 비율 이상'으로 보고. 위험: 도형 규칙은 위험으로 올리지 않으므로 "
             "하한 = 전체 쌍 p 의 k_위험번째로 큰 값의 넷째 자리 내림; k_위험 = 0 이면 null"),
    "채택": ("표본 A 의 값을 JSON 에 쓴다(B 는 같은 계산을 나란히 보고만). 심결 정밀도로 위험을 "
             "정하지 않는다. A 값이 오름차순(null 은 건너뜀)이 아니면 쓰지 않고 멈춘다(종료 "
             "코드 3)"),
    "쓰기": ("risk_model_v1.4.json 의 nameless_patterns[키].grade_thresholds ← A 값, "
             "meta.nameless.grade_thresholds 에 산출 방법·표본·B 값·규칙·이전 값 이력. 이름 있는 "
             "계수·하한은 그대로. 같은 쓰기에서 figure_rule.caveat 를 서비스 문구로 바꾸고 이전 "
             "문구를 meta 에 남긴다"),
}


def rule_sha256() -> str:
    return hashlib.sha256(
        json.dumps(RULE, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


# ---- 정규화·규칙 계산(엔진 없이 시험 가능) ---------------------------------------------------

def normalize_applicant(text: str) -> str:
    """출원인 정규화 — NFKC('㈜' → '(주)'), '주식회사'·'(주)' 제거, 공백·문장부호 제거, 소문자."""
    value = unicodedata.normalize("NFKC", str(text or ""))
    for word in ("주식회사", "(주)"):
        value = value.replace(word, "")
    return "".join(ch for ch in value if not ch.isspace()
                   and not unicodedata.category(ch).startswith("P")).lower()


def load_aliases(path: Path = DEFAULT_ALIASES) -> dict[str, str]:
    """출원인 별칭 표 → {정규화한 이름: 묶음 대표(첫 이름의 정규화)}. 묶음은 이름 둘 이상, 한
    이름이 두 묶음에 들어가면 ValueError."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for group in data.get("groups") or []:
        names = [normalize_applicant(name) for name in group.get("names") or []]
        names = [name for name in names if name]
        if len(set(names)) < 2:
            raise ValueError(f"출원인 별칭 묶음은 서로 다른 이름 둘 이상이어야 합니다: {group}")
        for name in names:
            if name in out and out[name] != names[0]:
                raise ValueError(f"출원인 별칭이 두 묶음에 있습니다: {name}")
            out[name] = names[0]
    return out


def split_applicants(text: str, aliases: dict[str, str] | None = None) -> frozenset[str]:
    """출원인 칸(DB 출원인·목록 청구인·피청구인) → 정규화한 이름 집합(별칭 묶음은 대표 이름으로).
    여러 명은 '|' 로 나뉜다(쉼표는 회사 이름 안에도 있어 나누지 않는다). 같은 출원인 = 이 집합이
    하나라도 겹침."""
    aliases = aliases or {}
    names = (normalize_applicant(part) for part in str(text or "").split("|"))
    return frozenset(aliases.get(name, name) for name in names if name)


def name_key(text: str) -> str:
    """같은 이름 비교용 — NFKC·소문자, 글자·숫자만."""
    return "".join(ch for ch in unicodedata.normalize("NFKC", str(text or "")).lower()
                   if ch.isalnum())


def floor4(value: float) -> float:
    return ngt._floor(value)


def calibrate(named_grades: list[str], nameless_prob, lifted) -> dict:
    """규칙 '하한' — 한 방식·한 표본의 비교 쌍에서 세 하한과 근거."""
    prob = np.asarray(nameless_prob, dtype=float)
    lifted = np.asarray(lifted, dtype=bool)
    rank = np.asarray([rm.GRADES.index(grade) for grade in named_grades], dtype=int)
    n, figure = int(prob.size), int(lifted.sum())
    free = np.sort(prob[~lifted])[::-1]
    every = np.sort(prob)[::-1]
    out = {"n": n, "도형_규칙_발동": figure}
    for grade in rm.GRADE_THRESHOLD_KEYS:
        k = int((rank >= rm.GRADES.index(grade)).sum())
        entry = {"이름_알_때_이상": k, "비율": ngt._round(k / n) if n else None}
        if grade == "위험":
            entry["하한"] = floor4(float(every[k - 1])) if k >= 1 else None
        else:
            k_free = k - figure
            entry["k′"] = k_free
            entry["하한"] = floor4(float(free[k_free - 1])) if k_free >= 1 else None
            if k_free <= 0 and figure > 0:
                entry["도형_규칙만으로_목표_이상"] = True
        out[grade] = entry
    return out


def thresholds_of(calibration: dict) -> dict:
    return {grade: calibration[grade]["하한"] for grade in rm.GRADE_THRESHOLD_KEYS}


def ascending(thresholds: dict) -> bool:
    cuts = [thresholds[grade] for grade in rm.GRADE_THRESHOLD_KEYS if thresholds[grade] is not None]
    return all(low <= high for low, high in zip(cuts, cuts[1:]))


def final_grade(prob: float, thresholds: dict, lifted: bool) -> str:
    """이름 없는 판단의 최종 등급 — 하한(null 건너뜀) + 도형 규칙(검토 권장으로 올림)."""
    grade = rm.grade_for(float(prob), thresholds)
    if lifted and rm.GRADES.index(grade) < rm.GRADES.index(REVIEW):
        grade = REVIEW
    return grade


def at_least_counts(grades: list[str]) -> dict:
    return {grade: sum(1 for value in grades if rm.GRADES.index(value) >= rm.GRADES.index(grade))
            for grade in rm.GRADE_THRESHOLD_KEYS}


def grade_counts(grades) -> dict:
    grades = list(grades)
    return {grade: grades.count(grade) for grade in rm.GRADES}


def percentile(values, q: float) -> float | None:
    if not len(values):
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def similarity_stop(a: dict, b: dict, margin: float = SIMILARITY_MARGIN) -> bool:
    """사전 점검의 멈춤 조건 — A 의 중앙값과 상위 10%(90분위)가 둘 다 B 보다 margin 이상 낮다."""
    if None in (a.get("중앙값"), b.get("중앙값"), a.get("상위10%"), b.get("상위10%")):
        return False
    return a["중앙값"] <= b["중앙값"] - margin and a["상위10%"] <= b["상위10%"] - margin


def apply_to_model(model: dict, thresholds: dict[str, dict], meta_extra: dict, *,
                   today: str) -> dict:
    """규칙 '쓰기' — 사본을 돌려준다. 같은 방법으로 이미 쓴 JSON 이면 이력을 겹쳐 쌓지 않는다."""
    out = copy.deepcopy(model)
    meta = out.setdefault("meta", {}).setdefault("nameless", {})
    current = copy.deepcopy(meta.get("grade_thresholds") or {})
    history = list(current.pop("history", []))
    if current.get("method") != METHOD:
        previous = {key: copy.deepcopy(out[rm.NAMELESS_KEY][key].get("grade_thresholds"))
                    for key in out.get(rm.NAMELESS_KEY) or {}}
        history.append({**current, "method": current.get("method", "쉬운 음성 기준(§7-4-3)"),
                        "thresholds": previous})
        history.append({**ATTEMPT1, "calibrated_at": today, "thresholds": None})
    for key, values in thresholds.items():
        out[rm.NAMELESS_KEY][key]["grade_thresholds"] = dict(values)
    meta["grade_thresholds"] = {
        "calibrated_at": today, "method": METHOD, "rule": RULE, "rule_sha256": rule_sha256(),
        **meta_extra,
        "note": ("null = 그 등급은 그 입력 종류에서 위험도로는 닿지 않는다. 이름 있는 입력은 "
                 "최상위 grade_thresholds 그대로(위험 = 정밀도 0.8 목표 미달 대체값 0.5902)"),
        "history": history,
    }
    rule = out.get("figure_rule")
    if rule is not None and rule.get("caveat") != FIGURE_CAVEAT:
        out["meta"].setdefault("figure_caveat_history", []).append(
            {"이전": rule.get("caveat"), "바꾼_날": today,
             "사유": "서비스 v1.4 반영 — 계약 v2 §2-5 FIGURE_LOW_DATA 문구"})
        rule["caveat"] = FIGURE_CAVEAT
    rm.validate_model(out)
    return out


# ---- 표본 ------------------------------------------------------------------------------------

@dataclass
class Query:
    key: str
    sample: str  # "A" | "B"
    kind: str
    name: str
    name_source: str
    goods: frozenset
    applicants: frozenset  # 정규화
    applicant_text: str
    path: Path
    self_id: str | None = None
    numbers: frozenset = frozenset()
    size: tuple = (0, 0)
    flags: dict = field(default_factory=dict)


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _codes(text: str, valid) -> set[str]:
    return set(valid([code for code in str(text or "").split(";") if code])[0])


def sample_a_candidates(labels: list[dict], trial_list: dict, image_pairs: list[dict],
                        base: Path, valid, aliases: dict[str, str] | None = None) -> list[Query]:
    """규칙 '표본_A' 의 후보(뺄 것 판정 전) — 사건마다 한 질의. valid = 유사군 형식 필터."""
    from scripts import pairs_features as pf

    rows_by_case: dict[str, list[dict]] = {}
    for row in labels:
        if row.get("유사여부_확정") in ("유사", "비유사") and row.get("종류") in A_KINDS:
            rows_by_case.setdefault(row["심판번호"], []).append(row)
    images: dict[tuple[str, str], str] = {}
    for pair in image_pairs:
        images.setdefault((pair["심판번호"], "this"), pair.get("이미지A") or "")
        if pair.get("상대role") == "target":
            images.setdefault((pair["심판번호"], "target"), pair.get("이미지B") or "")
    out = []
    for case in sorted(rows_by_case):
        rows = rows_by_case[case]
        kind = rows[0]["종류"]
        side, party = A_KINDS[kind]
        listed = trial_list.get(case) or {}
        if side == "this":
            names = [(row.get("상표A_명칭") or "").strip() for row in rows]
            sources = ["목록"] * len(rows)
            goods = set().union(*(_codes(row.get("goods_codes_this"), valid) for row in rows))
            numbers = {row.get("상표A_번호", "").strip() for row in rows}
            numbers |= {listed.get("출원번호", "").strip(), listed.get("등록번호", "").strip()}
        else:
            resolved = [pf.name_b(row) for row in rows]
            names = [name.strip() for name, _ in resolved]
            sources = [source for _, source in resolved]
            goods = set().union(*(_codes(row.get("goods_codes_prior"), valid) for row in rows))
            numbers = {row.get("상대표장_번호_정규화", "").strip() for row in rows}
        counted = Counter(name for name in names if name)
        name = counted.most_common(1)[0][0] if counted else ""
        source = sources[names.index(name)] if name else ""
        image = images.get((case, side)) or ""
        out.append(Query(
            key=f"A:{case}:{side}", sample="A", kind=kind, name=name, name_source=source,
            goods=frozenset(goods), applicants=split_applicants(listed.get(party, ""), aliases),
            applicant_text=listed.get(party, ""), path=(base / image) if image else Path(),
            numbers=frozenset(number for number in numbers if number)))
    return out


def screen_a(candidates: list[Query], db_numbers: set[str], load_image, is_photo) -> tuple:
    """규칙 '표본_A' 의 뺄 것 — (남은 질의, 사유별 수, 사유별 질의 목록)."""
    kept, reasons, seen = [], Counter(), {}
    listing: dict[str, list[str]] = {}
    for query in candidates:
        reason = None
        if not query.path.name or not query.path.exists():
            reason = "이미지 없음"
        else:
            raw = query.path.read_bytes()
            image = load_image(raw)
            if image is None:
                reason = "디코딩 실패"
            else:
                query.size = image.size
                digest = hashlib.sha256(raw).hexdigest()
                if query.numbers & db_numbers:
                    reason = "DB에 있음"
                elif not query.name:
                    reason = "이름 없음"
                elif min(image.size) < MIN_SHORT_SIDE:
                    reason = "해상도"
                elif is_photo(image):
                    reason = "사진"
                elif digest in seen:
                    reason = "중복 이미지"
                else:
                    seen[digest] = query.key
        if reason:
            reasons[reason] += 1
            listing.setdefault(reason, []).append(query.key)
        else:
            kept.append(query)
    return kept, {reason: reasons.get(reason, 0) for reason in EXCLUDE_ORDER}, listing


def sample_b(records, sources: dict, applicants: dict, image_root: Path,
             image_paths: list, aliases: dict[str, str] | None = None) -> list[Query]:
    eligible = sorted((record for record in records
                       if record.pos is not None and record.title and record.goods),
                      key=lambda record: record.appno)
    chosen = random.Random(SEED).sample(eligible, SAMPLE_B)
    out = []
    for record in chosen:
        text = applicants.get(record.appno, "")
        out.append(Query(key=f"B:{record.appno}", sample="B", kind=sources.get(record.appno) or "",
                         name=record.title, name_source="DB", goods=frozenset(record.goods),
                         applicants=split_applicants(text, aliases),
                         applicant_text=text, path=image_root / image_paths[record.pos],
                         self_id=record.appno))
    return out


def keep_reason(query: Query, candidate_id: str, candidate_applicant: str,
                aliases: dict[str, str] | None = None) -> str | None:
    """후보를 뺄 사유(자기 자신·같은 출원인) — 남기면 None."""
    if query.self_id is not None and candidate_id == query.self_id:
        return "자기"
    if split_applicants(candidate_applicant, aliases) & query.applicants:
        return "같은 출원인"
    return None


def mode_list(query: Query) -> list[tuple[str, str, bool]]:
    return [mode for mode in MODES if not mode[2] or query.goods]


# ---- 엔진 ------------------------------------------------------------------------------------

def load_engine(model_path: Path):
    os.environ[rm.ENV_MODEL_PATH] = str(model_path)
    from backend.src.core import engine  # noqa: I001  (engine 이 torch 를 faiss 보다 먼저 올린다)
    from backend.src.core import multi_search as ms

    engine.load_all()
    if ms.state.model is None:
        raise RuntimeError(f"통합 모델이 준비되지 않았습니다: {ms.state.error}")
    return engine, ms


def decoders():
    """(서비스 업로드 경로 디코더, 그 경로가 거절하면 같은 PIL 디코딩) — 바이트 → PIL 또는 None."""
    from fastapi import HTTPException
    from PIL import Image

    from backend.src.core import validation

    def service(raw: bytes):
        try:
            return validation.validate_and_decode(raw)
        except HTTPException:
            return None

    def direct(raw: bytes):
        image = service(raw)
        if image is not None:
            return image
        try:
            with Image.open(io.BytesIO(raw)) as source:
                source.load()
                return source.copy()
        except Exception:
            return None

    return service, direct


def _timed(function, *args, **kwargs):
    started = time.perf_counter()
    value = function(*args, **kwargs)
    return value, (time.perf_counter() - started) * 1000


def prepare(args):
    """엔진·표본·조회표 — 사전 점검과 계산이 같은 표본을 쓴다."""
    engine, ms = load_engine(args.model)
    service, direct = decoders()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    records = metadata.get("trademarks", metadata) if isinstance(metadata, dict) else metadata
    sources = {str(r.get("출원번호")): r.get("수집_출처") for r in records}
    applicants = {str(r.get("출원번호")): str(r.get("출원인") or "") for r in records}
    db_numbers = ({str(r.get("출원번호") or "").strip() for r in records}
                  | {str(r.get("등록번호") or "").strip() for r in records}) - {""}

    def photo(image) -> bool:
        return ms.is_photo_query(np.asarray(engine.encode_image(image), dtype=np.float32))

    aliases = load_aliases(args.aliases)
    trial_list = {row["심판번호"]: row for row in _read_csv(args.trial_list)}
    candidates = sample_a_candidates(_read_csv(args.labels), trial_list,
                                     _read_csv(args.image_pairs), TRIALS, ms.valid_goods, aliases)
    queries_a, reasons, listing = screen_a(candidates, db_numbers, service, photo)
    from backend.src.core import paths

    queries_b = sample_b(ms.state.records, sources, applicants, Path(paths.IMAGES_DIR),
                         engine.state.image_paths, aliases)
    for query in queries_b:
        raw = query.path.read_bytes()
        image = direct(raw)
        query.size = image.size
        query.flags = {"사진": photo(image), "업로드_상한_초과": service(raw) is None}
    if args.limit:
        queries_a, queries_b = queries_a[:args.limit], queries_b[:args.limit]
    return {"engine": engine, "ms": ms, "service": service, "direct": direct,
            "applicants": applicants, "aliases": aliases, "candidates": candidates,
            "A": queries_a, "B": queries_b, "reasons": reasons, "listing": listing,
            "aliases_sha256": hashlib.sha256(Path(args.aliases).read_bytes()).hexdigest()}


def decoder_for(context: dict, query: Query):
    return context["service"] if query.sample == "A" else context["direct"]


# ---- 0. 사전 점검 ----------------------------------------------------------------------------

def precheck(args) -> dict:
    started = time.perf_counter()
    context = prepare(args)
    ms, applicants, aliases = context["ms"], context["applicants"], context["aliases"]
    pools = []
    for query in context["A"] + context["B"]:
        image = decoder_for(context, query)(query.path.read_bytes())
        for label, _, with_goods in mode_list(query):
            pooled = ms.search_pool(image=image,
                                    goods_codes=sorted(query.goods) if with_goods else None)
            kept, removed = [], Counter()
            for candidate in pooled.candidates:
                reason = keep_reason(query, candidate.id, applicants.get(candidate.id, ""),
                                     aliases)
                if reason:
                    removed[reason] += 1
                    continue
                kept.append({"후보": candidate.id, "x2_img": candidate.axes["x2_img"],
                             "상표명": candidate.title or "",
                             "출원인": applicants.get(candidate.id, "")})
            pools.append({"질의": query, "방식": label, "남음": kept, "뺌": removed})
    results = {
        "기준일": date.today().isoformat(), "계산_규칙_sha256": rule_sha256(),
        "출원인_별칭_sha256": context["aliases_sha256"],
        "표본_A": summarize_sample(context["A"], context["candidates"], context["reasons"]),
        "표본_B": summarize_sample(context["B"], None, None),
        "후보_정리": pool_summary(pools),
        "같은_이름_다른_출원인": same_name_pairs(pools),
        "이미지_유사도": similarity_summary(pools, context["A"]),
        "뺀_질의_목록": context["listing"],
        "소요_초": round(time.perf_counter() - started, 1),
    }
    results[STOP_KEY] = similarity_stop(results["이미지_유사도"]["A"]["이미지만"],
                                        results["이미지_유사도"]["B"]["이미지만"])
    return results


def _quantiles(values: list[float]) -> dict:
    return {"n": len(values), "최소": min(values) if values else None,
            **{f"p{int(q * 100)}": ngt._round(percentile(values, q), 1)
               for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
            "최대": max(values) if values else None}


def summarize_sample(queries: list[Query], candidates, reasons) -> dict:
    out = {"질의": {"이미지만": len(queries),
                  "이미지+상품": sum(1 for query in queries if query.goods)},
           "종류": dict(Counter(query.kind for query in queries)),
           "이름_출처": dict(Counter(query.name_source for query in queries)),
           "짧은_변_px": _quantiles([min(query.size) for query in queries]),
           "긴_변_px": _quantiles([max(query.size) for query in queries])}
    if candidates is not None:
        out = {"후보(사건)": len(candidates), "뺀_수": reasons,
               "종류별_후보": dict(Counter(query.kind for query in candidates)), **out}
    else:
        out["사진_판정"] = sum(1 for query in queries if query.flags.get("사진"))
        out["업로드_상한_초과(엔진 직접)"] = sum(
            1 for query in queries if query.flags.get("업로드_상한_초과"))
    return out


def pool_summary(pools: list[dict]) -> dict:
    out: dict = {}
    for entry in pools:
        slot = out.setdefault(entry["질의"].sample, {}).setdefault(
            entry["방식"], {"검색": 0, "후보(남음)": 0, "자기": 0, "같은 출원인": 0,
                          "상표명_없는_후보(남음)": 0})
        slot["검색"] += 1
        slot["후보(남음)"] += len(entry["남음"])
        slot["상표명_없는_후보(남음)"] += sum(1 for c in entry["남음"] if not c["상표명"])
        for reason, count in entry["뺌"].items():
            slot[reason] += count
    return out


def same_name_pairs(pools: list[dict]) -> dict:
    """형제(같은 출원인)를 뺀 뒤에도 남는 '이름(정규화)이 똑같은데 출원인이 다른 쌍'(방식을 합쳐
    한 번)."""
    out: dict = {}
    for sample in ("A", "B"):
        seen, items = set(), []
        for entry in pools:
            query = entry["질의"]
            if query.sample != sample:
                continue
            key = name_key(query.name)
            for candidate in entry["남음"]:
                if not key or name_key(candidate["상표명"]) != key:
                    continue
                pair = (query.key, candidate["후보"])
                if pair in seen:
                    continue
                seen.add(pair)
                items.append({"질의": query.key, "질의_이름": query.name,
                              "질의_출원인": query.applicant_text, "후보": candidate["후보"],
                              "후보_이름": candidate["상표명"], "후보_출원인": candidate["출원인"],
                              "x2_img": candidate["x2_img"]})
        out[sample] = {"쌍": len(items), "질의": len({item["질의"] for item in items}),
                       "목록": items}
    return out


def similarity_summary(pools: list[dict], queries_a: list[Query]) -> dict:
    out: dict = {}
    for sample in ("A", "B"):
        for label, _, _ in MODES:
            chosen = [entry for entry in pools
                      if entry["질의"].sample == sample and entry["방식"] == label]
            values = [c["x2_img"] for entry in chosen for c in entry["남음"]
                      if c["x2_img"] is not None]
            top = [max((c["x2_img"] for c in entry["남음"] if c["x2_img"] is not None),
                       default=0.0) for entry in chosen]
            out.setdefault(sample, {})[label] = {
                "n": len(values), "중앙값": ngt._round(percentile(values, 0.5)),
                "상위10%": ngt._round(percentile(values, 0.9)),
                "질의별_최댓값_중앙값": ngt._round(percentile(top, 0.5))}
    if queries_a:
        middle = statistics.median(min(query.size) for query in queries_a)
        for half, low in (("낮은 해상도 절반", True), ("높은 해상도 절반", False)):
            values = [c["x2_img"] for entry in pools
                      if entry["질의"].sample == "A" and entry["방식"] == "이미지만"
                      and (min(entry["질의"].size) < middle) == low
                      for c in entry["남음"] if c["x2_img"] is not None]
            out.setdefault("A_해상도별(이미지만)", {})[half] = {
                "짧은_변_기준": middle, "n": len(values),
                "중앙값": ngt._round(percentile(values, 0.5)),
                "상위10%": ngt._round(percentile(values, 0.9))}
    return out


# ---- 1. 계산 ---------------------------------------------------------------------------------

def phase_a(ms, queries: list[Query], decode, applicants: dict,
            aliases: dict[str, str]) -> list[dict]:
    """계산용 — 방식 ①·② 의 풀(지금 JSON)과 같은 쌍의 이름 있는 재채점."""
    rows = []
    for number, query in enumerate(queries, 1):
        image = decode(query.path.read_bytes())
        named_type, _ = ms._resolve_query_type(image, query.name, None)
        entry = {"질의": query.key, "방식": {}}
        for label, _, with_goods in mode_list(query):
            pooled = ms.search_pool(image=image,
                                    goods_codes=sorted(query.goods) if with_goods else None)
            ctx = ms.make_context(query.name, query.goods if with_goods else None,
                                  pooled.embedding, named_type, pooled.x3_on)
            pairs, removed = [], Counter()
            for candidate in pooled.candidates:
                reason = keep_reason(query, candidate.id, applicants.get(candidate.id, ""),
                                     aliases)
                if reason:
                    removed[reason] += 1
                    continue
                other = ms.state.by_appno[candidate.id]
                pair = {"후보": candidate.id, "이름": bool(other.title), "p": candidate.prob,
                        "도형_규칙": "figure_x2_img" in candidate.rule_triggers}
                if other.title:
                    pair["이름_등급"] = ms.score_record(other, ctx).grade
                pairs.append(pair)
            entry["방식"][label] = {"쌍": pairs, "뺌": dict(removed)}
        rows.append(entry)
        if number % 25 == 0:
            print(f"  계산용 검색 {number}/{len(queries)}", file=sys.stderr, flush=True)
    return rows


def phase_b(ms, queries: list[Query], decode, applicants: dict,
            aliases: dict[str, str]) -> list[dict]:
    """평가용 — 새 하한을 실은 모델로 세 방식을 실제로 검색(등급 분포·응답 시간·단계 시간)."""
    rows = []
    for number, query in enumerate(queries, 1):
        image = decode(query.path.read_bytes())
        entry = {"질의": query.key, "방식": {}}
        plans = [("이미지만", None, False)]
        if query.goods:
            plans += [("이미지+상품", None, True), (FULL, query.name, True)]
        for label, name, with_goods in plans:
            pooled, elapsed = _timed(ms.search_pool, image=image, name=name,
                                     goods_codes=sorted(query.goods) if with_goods else None)
            kept = [c for c in pooled.candidates
                    if keep_reason(query, c.id, applicants.get(c.id, ""), aliases) is None]
            entry["방식"][label] = {
                "ms": round(elapsed, 1), "단계": dict(pooled.timings),
                "풀": dict(pooled.counts), "유형": pooled.query_type.type,
                "OCR_fallback": pooled.ocr_fallback,
                "후보": [{"후보": c.id, "등급": c.grade, "p": c.prob, "pattern": c.pattern}
                       for c in kept]}
        rows.append(entry)
        if number % 25 == 0:
            print(f"  평가용 검색 {number}/{len(queries)}", file=sys.stderr, flush=True)
    return rows


def calibrate_sample(rows: list[dict]) -> dict:
    out = {}
    for label, key, _ in MODES:
        pairs = [pair for row in rows if label in row["방식"]
                 for pair in row["방식"][label]["쌍"]]
        titled = [pair for pair in pairs if pair["이름"]]
        cal = calibrate([p["이름_등급"] for p in titled], [p["p"] for p in titled],
                        [p["도형_규칙"] for p in titled])
        values = thresholds_of(cal)
        nameless = [final_grade(p["p"], values, p["도형_규칙"]) for p in titled]
        named = [p["이름_등급"] for p in titled]
        removed = Counter()
        for row in rows:
            removed.update((row["방식"].get(label) or {}).get("뺌", {}))
        out[label] = {
            "pattern": PREFIX + key,
            "검색": sum(1 for row in rows if label in row["방식"]),
            "후보(자기·같은 출원인 뺀 뒤)": len(pairs), "뺀_후보": dict(removed),
            "상표명_없는_후보_제외": len(pairs) - len(titled), "하한_계산": cal, "하한": values,
            "그_등급_이상(이름 알 때 / 이름 없을 때)": {
                grade: [at_least_counts(named)[grade], at_least_counts(nameless)[grade]]
                for grade in rm.GRADE_THRESHOLD_KEYS},
            "등급_분포(비교 쌍)": {"이름 알 때": grade_counts(named),
                             "이름 없을 때": grade_counts(nameless)},
        }
    return out


def distribution(rows: list[dict]) -> dict:
    out = {}
    for label in ("이미지만", "이미지+상품", FULL):
        entries = [row["방식"][label] for row in rows if label in row["방식"]]
        if not entries:
            continue
        pool = {grade: [] for grade in rm.GRADES}
        top = {grade: [] for grade in rm.GRADES}
        patterns = Counter()
        for entry in entries:
            grades = [c["등급"] for c in entry["후보"]]
            shown = grades[:DISPLAY_TOP]
            patterns.update(c["pattern"] for c in entry["후보"])
            for grade in rm.GRADES:
                pool[grade].append(grades.count(grade))
                top[grade].append(shown.count(grade))
        elapsed = [entry["ms"] for entry in entries]
        out[label] = {
            "검색": len(entries), "후보": sum(len(e["후보"]) for e in entries),
            "검색당_평균(풀)": {g: ngt._round(statistics.fmean(v), 2) for g, v in pool.items()},
            f"검색당_평균(상위 {DISPLAY_TOP})": {g: ngt._round(statistics.fmean(v), 2)
                                           for g, v in top.items()},
            "pattern": dict(sorted(patterns.items())),
            "응답_ms": {"중앙값": ngt._round(statistics.median(elapsed), 1),
                      "95%": ngt._round(percentile(elapsed, 0.95), 1),
                      "최대": ngt._round(max(elapsed), 1)},
        }
    return out


def slowest(rows_by_sample: dict, count: int = 10) -> list[dict]:
    requests = []
    for sample, rows in rows_by_sample.items():
        for row in rows:
            for label, entry in row["방식"].items():
                stages = entry["단계"]
                main = max(stages.items(), key=lambda item: item[1]) if stages else ("", 0.0)
                requests.append({"표본": sample, "질의": row["질의"], "방식": label,
                                 "ms": entry["ms"], "단계": stages, "가장_긴_단계": main[0],
                                 "풀": entry["풀"], "유형": entry["유형"],
                                 "OCR_fallback": entry["OCR_fallback"]})
    requests.sort(key=lambda item: -item["ms"])
    return requests[:count]


def stage_medians(rows_by_sample: dict) -> dict:
    out: dict = {}
    for rows in rows_by_sample.values():
        for row in rows:
            for label, entry in row["방식"].items():
                slot = out.setdefault(label, {})
                for stage, value in entry["단계"].items():
                    slot.setdefault(stage, []).append(value)
    return {label: {stage: ngt._round(statistics.median(values), 1)
                    for stage, values in stages.items()} for label, stages in out.items()}


def trial_oof(model: dict, v13_path: Path) -> dict:
    """참고 표의 입력 — 심결 이름 없는 행의 OOF(도형계 입력, v1.4 2차 시도와 같은 겹)."""
    from scripts import train_risk_model_v14 as t4
    from scripts import train_risk_model_v14_nameless as t2

    model_old = rm.validate_model(json.loads(Path(v13_path).read_text(encoding="utf-8")))
    rows = t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY).rows
    result = t2.train_once(rows, model_old)
    design, a, cv = result["design"], result["arrays"], result["cv"]
    for key, block in t2.rounded_nameless(design, result["final"].blocks).items():
        if block["coefficients"] != model[rm.NAMELESS_KEY][key]["coefficients"]:
            raise RuntimeError(f"OOF 를 만든 학습이 배포 계수와 다릅니다({key})")
    nameless = a["trial"] & ~a["named"]
    out = {}
    for label, key, _ in MODES:
        block = PREFIX + key
        index = np.flatnonzero(nameless & design.mask[block])
        out[label] = {"prob": cv["per_block_figure"][block][index], "y": a["y"][index],
                      "w": a["eval_weight"][index],
                      "x2_whole": np.asarray([rows[i]["x2_whole"] for i in index], dtype=float)}
    return out


def trial_table(oof: dict, thresholds: dict, tau: float | None) -> dict:
    from scripts import train_risk_model_v14 as t4

    lifted = (oof["x2_whole"] >= tau) if tau is not None else np.zeros(oof["prob"].size, bool)
    grades = np.asarray([final_grade(p, thresholds, bool(flag))
                         for p, flag in zip(oof["prob"], lifted)])
    return {"n": int(oof["prob"].size), "유사": int((oof["y"] == 1).sum()),
            "도형_규칙_발동": int(lifted.sum()),
            "표": t4.grade_table(oof["prob"], oof["y"], oof["w"], thresholds, grades=grades)}


def compute(args) -> tuple[dict, int]:
    started = time.perf_counter()
    model = rm.load_model(args.model)
    tau = (model.get("figure_rule") or {}).get("threshold")
    context = prepare(args)
    ms, applicants, aliases = context["ms"], context["applicants"], context["aliases"]
    queries_a, queries_b = context["A"], context["B"]
    print(f"규칙 sha256 {rule_sha256()} · 질의 A {len(queries_a)} · B {len(queries_b)}",
          file=sys.stderr)
    rows_a = phase_a(ms, queries_a, context["service"], applicants, aliases)
    rows_b = phase_a(ms, queries_b, context["direct"], applicants, aliases)
    calibration = {"A": calibrate_sample(rows_a), "B": calibrate_sample(rows_b)}
    adopted = {key: calibration["A"][label]["하한"] for label, key, _ in MODES}
    previous = {key: model[rm.NAMELESS_KEY][key].get("grade_thresholds") for _, key, _ in MODES}
    difference = {}
    for label, _, _ in MODES:
        a_values, b_values = calibration["A"][label]["하한"], calibration["B"][label]["하한"]
        difference[label] = {grade: (None if None in (a_values[grade], b_values[grade])
                                     else ngt._round(a_values[grade] - b_values[grade]))
                             for grade in rm.GRADE_THRESHOLD_KEYS}
    queries = {"A": {"이미지만": len(queries_a),
                     "이미지+상품": sum(1 for q in queries_a if q.goods),
                     "뺀_수": context["reasons"]},
               "B": {"이미지만": len(queries_b),
                     "이미지+상품": sum(1 for q in queries_b if q.goods)}}
    results = {
        "기준일": date.today().isoformat(), "규칙": RULE, "규칙_sha256": rule_sha256(),
        "출원인_별칭_sha256": context["aliases_sha256"], "질의": queries, "계산": calibration,
        "채택(A)": adopted, "이전_하한": previous,
        "A−B": difference, "오름차순": all(ascending(v) for v in adopted.values()), "쓰기": False,
    }
    if not results["오름차순"]:
        results["소요_초"] = round(time.perf_counter() - started, 1)
        return results, 3
    meta_extra = {
        "samples": {"A": {"what": ("정답 데이터 1·2차의 거절결정불복 출원 표장 + 권리범위확인 "
                                   "확인대상표장 중 DB 에 없는 것"), "queries": queries["A"]},
                    "B": {"what": f"DB 레코드 {SAMPLE_B}건(seed {SEED}) — 검증용",
                          "queries": queries["B"]}},
        "exclusions": ("자기 자신·같은 출원인(정규화 + 별칭 표 shared/applicant_aliases.json) "
                       "후보, 상표명 없는 후보(비교에서)"),
        "applicant_aliases_sha256": context["aliases_sha256"],
        "kinds": {label: {"pattern": item["pattern"], "pairs": item["하한_계산"]["n"],
                          "figure_rule_pairs": item["하한_계산"]["도형_규칙_발동"],
                          "grades": {g: item["하한_계산"][g] for g in rm.GRADE_THRESHOLD_KEYS}}
                  for label, item in calibration["A"].items()},
        "validation_B": {label: item["하한"] for label, item in calibration["B"].items()},
    }
    updated = apply_to_model(model, adopted, meta_extra, today=date.today().isoformat())
    if not args.dry_run:
        Path(args.model).write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
        results["쓰기"] = True
        rm._load_cached.cache_clear()  # load_model 은 프로세스 캐시 — 쓴 파일을 다시 읽게
        ms.load_all()
    else:
        ms.state.model = updated
    if ms.state.model.get(rm.NAMELESS_KEY) != updated.get(rm.NAMELESS_KEY):
        raise RuntimeError("다시 적재한 모델의 이름 없는 집합이 쓴 값과 다릅니다")
    print("평가용 검색(새 하한)", file=sys.stderr)
    eval_a = phase_b(ms, queries_a, context["service"], applicants, aliases)
    eval_b = phase_b(ms, queries_b, context["direct"], applicants, aliases)
    results["분포"] = {"A": distribution(eval_a), "B": distribution(eval_b)}
    results["가장_느린_10"] = slowest({"A": eval_a, "B": eval_b})
    results["단계_중앙값(ms)"] = stage_medians({"A": eval_a, "B": eval_b})
    mismatch = 0
    for rows, evals in ((rows_a, eval_a), (rows_b, eval_b)):
        for row, entry in zip(rows, evals):
            for label, key, _ in MODES:
                if label not in row["방식"]:
                    continue
                expected = {p["후보"]: final_grade(p["p"], adopted[key], p["도형_규칙"])
                            for p in row["방식"][label]["쌍"]}
                mismatch += sum(int(expected.get(c["후보"]) != c["등급"])
                                for c in entry["방식"][label]["후보"])
    results["계산·평가_등급_불일치"] = mismatch
    oof = trial_oof(updated, args.v13)
    results["심결_이름_없는_행(참고)"] = {label: trial_table(oof[label], adopted[key], tau)
                                    for label, key, _ in MODES}
    results["유사도_환산"] = ngt.similarity_equivalents(updated)
    results["소요_초"] = round(time.perf_counter() - started, 1)
    return results, 0


# ---- 보고 ------------------------------------------------------------------------------------

def _cell(value) -> str:
    return "null" if value is None else str(value)


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _block(value) -> list[str]:
    return ["```", json.dumps(value, ensure_ascii=False, indent=1), "```", ""]


def precheck_text(results: dict) -> str:
    lines = ["# 이름 없는 하한 — 사전 점검(표본 A·B, 하한 계산 없음)", "",
             f"기준일 {results['기준일']} · 소요 {results['소요_초']}초 · KIPRIS 호출 0", "",
             "## 표본 A", "", *_block(results["표본_A"]), "## 표본 B", "",
             *_block(results["표본_B"]), "## 후보 정리(자기·같은 출원인 뺀 수)", "",
             *_block(results["후보_정리"]),
             "## 이름(정규화)이 똑같은데 출원인이 다른 쌍(형제를 뺀 뒤)", ""]
    for sample, item in results["같은_이름_다른_출원인"].items():
        lines += [f"- {sample}: {item['쌍']}쌍(질의 {item['질의']})", "",
                  "| 질의 | 질의 이름 | 질의 출원인 | 후보 | 후보 이름 | 후보 출원인 | x2_img |",
                  "|---|---|---|---|---|---|---:|",
                  *(f"| {i['질의']} | {i['질의_이름']} | {i['질의_출원인']} | {i['후보']} | "
                    f"{i['후보_이름']} | {i['후보_출원인']} | {i['x2_img']} |"
                    for i in item["목록"]), ""]
    lines += ["## 후보 이미지 유사도(자기·같은 출원인 뺀 뒤)", "",
              *_block(results["이미지_유사도"]),
              f"멈춤 조건(A 중앙값·상위 10% 둘 다 B − {SIMILARITY_MARGIN} 이하): "
              f"{results[STOP_KEY]}", ""]
    return "\n".join(lines) + "\n"


def report_text(results: dict) -> str:
    lines = ["# 이름 없는 입력의 등급 하한 — 실제 검색 기준(표본 A 채택, B 확인)", "",
             f"기준일 {results['기준일']} · 규칙 sha256 `{results['규칙_sha256']}` · 소요 "
             f"{results.get('소요_초')}초 · KIPRIS 호출 0", "", "## 규칙(계산 전에 고정)", "",
             *(f"- **{key}**: {value}" for key, value in results["규칙"].items()), "",
             f"질의: `{_dump(results['질의'])}`", "", "## 하한", "",
             "| 방식 | 등급 | A(채택) | B(확인) | A−B | 이전 |", "|---|---|---:|---:|---:|---:|"]
    for label, key, _ in MODES:
        for grade in rm.GRADE_THRESHOLD_KEYS:
            before = (results["이전_하한"].get(key) or {}).get(grade)
            lines.append(
                f"| {label} | {grade} | {_cell(results['계산']['A'][label]['하한'][grade])} | "
                f"{_cell(results['계산']['B'][label]['하한'][grade])} | "
                f"{_cell(results['A−B'][label][grade])} | {_cell(before)} |")
    lines += ["", f"오름차순 {results['오름차순']} · JSON 쓰기 {results['쓰기']}", ""]
    for sample in ("A", "B"):
        for label, item in results["계산"][sample].items():
            cal = item["하한_계산"]
            lines += [f"### 계산 {sample} — {label}", "",
                      f"- 검색 {item['검색']} · 후보 {item['후보(자기·같은 출원인 뺀 뒤)']}"
                      f"(뺀 후보 {_dump(item['뺀_후보'])}) · 상표명 없는 후보 제외 "
                      f"{item['상표명_없는_후보_제외']} → 비교 {cal['n']}쌍 · 도형 규칙 발동 "
                      f"{cal['도형_규칙_발동']}",
                      *(f"- {grade}: {_dump(cal[grade])}" for grade in rm.GRADE_THRESHOLD_KEYS),
                      "- 그 등급 이상(이름 알 때 / 이름 없을 때): " + " · ".join(
                          f"{g} {v[0]}/{v[1]}"
                          for g, v in item["그_등급_이상(이름 알 때 / 이름 없을 때)"].items()),
                      "- 비교 쌍 등급 분포: " + _dump(item["등급_분포(비교 쌍)"]), ""]
    if "분포" in results:
        lines += ["## 실제 검색 — 검색 한 번당 등급별 후보 수(새 하한, 자기·같은 출원인 뺌)", "",
                  "| 표본 | 방식 | 검색 | 풀: 안전·주의·검토 권장·위험 | "
                  f"상위 {DISPLAY_TOP}: 안전·주의·검토 권장·위험 | 응답 ms 중앙값·95%·최대 |",
                  "|---|---|---:|---|---|---|"]
        for sample in ("A", "B"):
            for label, item in results["분포"][sample].items():
                pool, top = item["검색당_평균(풀)"], item[f"검색당_평균(상위 {DISPLAY_TOP})"]
                timing = item["응답_ms"]
                lines.append(
                    f"| {sample} | {label} | {item['검색']} | "
                    + "·".join(str(pool[g]) for g in rm.GRADES) + " | "
                    + "·".join(str(top[g]) for g in rm.GRADES) + " | "
                    + f"{timing['중앙값']}·{timing['95%']}·{timing['최대']} |")
        lines += ["", "## 가장 느린 요청 10개(단계별 ms)", "",
                  "| 표본 | 질의 | 방식 | ms | 가장 긴 단계 | 단계 | 풀 |",
                  "|---|---|---|---:|---|---|---|",
                  *(f"| {r['표본']} | {r['질의']} | {r['방식']} | {r['ms']} | "
                    f"{r['가장_긴_단계']} | {_dump(r['단계'])} | {_dump(r['풀'])} |"
                    for r in results["가장_느린_10"]),
                  "", "단계 중앙값(ms): " + _dump(results["단계_중앙값(ms)"]), "",
                  f"계산·평가 등급 불일치: {results['계산·평가_등급_불일치']}", "",
                  "## 심결 이름 없는 행(참고 — OOF, 새 하한 + 도형 규칙)", ""]
        for label, item in results["심결_이름_없는_행(참고)"].items():
            lines += [f"- {label}: n {item['n']} · 유사 {item['유사']} · 도형 규칙 "
                      f"{item['도형_규칙_발동']}", "",
                      "| 등급 | n | 유사 | 가중 정밀도 | 정밀도 |", "|---|---:|---:|---:|---:|",
                      *(f"| {r['등급']} | {r['n']} | {r['유사']} | {_cell(r['정밀도_가중'])} | "
                        f"{_cell(r['정밀도'])} |" for r in item["표"]), ""]
        lines += ["하한의 이미지 유사도 환산(도형계): " + _dump(results["유사도_환산"]), ""]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--precheck", action="store_true", help="0. 사전 점검만(하한 계산 없음)")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--v13", type=Path, default=DEFAULT_V13)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--trial-list", type=Path, default=DEFAULT_LIST)
    parser.add_argument("--image-pairs", type=Path, default=DEFAULT_IMAGE_PAIRS)
    parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES, help="출원인 별칭 표")
    parser.add_argument("--limit", type=int, default=0, help="표본마다 앞 N 질의만(배관 확인용)")
    parser.add_argument("--out-dir", type=Path, default=TRIALS)
    parser.add_argument("--dry-run", action="store_true", help="계산·보고만(JSON 을 쓰지 않음)")
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.precheck:
        results = precheck(args)
        (args.out_dir / f"{STEM}_precheck.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8")
        (args.out_dir / f"{STEM}_precheck.md").write_text(precheck_text(results),
                                                         encoding="utf-8")
        same = results["같은_이름_다른_출원인"]
        print(f"A 질의 {_dump(results['표본_A']['질의'])} · B {_dump(results['표본_B']['질의'])} · "
              f"같은 이름 다른 출원인 A {same['A']['쌍']}·B {same['B']['쌍']} · 유사도 멈춤 "
              f"{results[STOP_KEY]} · {results['소요_초']}초")
        return 0
    results, code = compute(args)
    (args.out_dir / f"{STEM}_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    (args.out_dir / f"{STEM}_report.md").write_text(report_text(results), encoding="utf-8")
    print(f"채택(A) {_dump(results['채택(A)'])} · 오름차순 {results['오름차순']} · 쓰기 "
          f"{results['쓰기']} · {results.get('소요_초')}초")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
