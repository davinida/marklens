"""견고성 점검 R-P0-2 — 식별력 결합 규칙의 약한 토큰열(combined_weak_run)을 두 이름 모두에서 붙어
있는 구간만 묶도록 고친다(식별력 v0.4, 규칙 2). 규칙·표본·채택 조건은 지시로 고정(2026-11-23).

    ml/venv/bin/python ml/scripts/weak_run_adjacent.py freeze   # 0. 규칙·입력·소스 해시
    ml/venv/bin/python ml/scripts/weak_run_adjacent.py run      # 1. 학습 특징(먼저) → 검색 전·후
    ml/venv/bin/python ml/scripts/weak_run_adjacent.py report   # 2. 채택 ①–⑤·전후 표
    ml/venv/bin/python ml/scripts/weak_run_adjacent.py apply    # 3. 채택일 때만 v1.4.3 JSON
    ml/venv/bin/python ml/scripts/weak_run_adjacent.py verify   # 4. 기본 모델 바꾼 뒤 확인

학습 특징을 만들 때도 이 규칙을 쓰므로 먼저 pairs_features 를 규칙 1·2 로 다시 만들어 지금 계수로
매긴 심결 AUC 를 견주고(0.01 넘게 떨어지면 검색 없이 멈춤), 통과하면 검색 표본을 잰다. 엔진의
규칙은 계수 JSON 의 weak_run.version 이 정한다 — 전 = v1.4.2(키 없음 → 1), 후 = 후보 v1.4.3(2).
같은 프로세스에서 엔진 계수(multi_search.state.model)만 바꿔 견준다. 산출(비공개):
ml/data/trials/weak_run_adjacent_{rule,results,candidate,verify}.json·_searches.json.gz·_report.md·
_features/(규칙 1·2 특징). 고정본과 다르면 거절(종료 코드 4), 검산 불일치·채택 미달이면 3. KIPRIS 0.
"""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import json
import random
import re
import shutil
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
for _root in (ML_ROOT, REPO_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from src.axes import distinctiveness as dx  # noqa: E402
from src.axes import pair_axes as pa  # noqa: E402
from src.model import risk_model as rm  # noqa: E402

from scripts import logo_floor_image_only as lo  # noqa: E402
from scripts import logo_floor_named as lf  # noqa: E402
from scripts import named_search_thresholds as first  # noqa: E402
from scripts import nameless_shared_threshold as ns  # noqa: E402

TRIALS = ML_ROOT / "data" / "trials"
STEM = "weak_run_adjacent"
EXIT_STOP = 3
EXIT_REFUSED = 4
REVIEW, RISK = "검토 권장", "위험"
BASE_VERSION = "risk_model_v1.4.2"
NEW_VERSION = "risk_model_v1.4.3"
BASE_MODEL_PATH = REPO_ROOT / "shared" / "model" / "risk_model_v1.4.2.json"
NEW_MODEL_PATH = REPO_ROOT / "shared" / "model" / "risk_model_v1.4.3.json"
FEATURES = TRIALS / "pairs_features.csv"
EASY = TRIALS / "pairs_features_easy.csv"
SAVED_SCENARIOS = TRIALS / "logo_floor_image_only_searches.json.gz"  # v1.4.2 확인 실행
WEAK_TOKENS = REPO_ROOT / "shared" / "distinctiveness" / "weak_tokens.json"
PRESETS = REPO_ROOT / "shared" / "goods_map" / "business_presets.json"
AUC_DROP_MAX = 0.01
SAMPLE_A_DROP_MAX = 0.02
PRECISION_MIN = 0.70
DROPPED_SIMILAR_MAX = 0.5
MIN_ROWS = 5
SEED = 0
NAMES_PER_SCRIPT = 100
WORD_COUNTS = (2, 3, 4)
SKIP_REASONS = ("5호", "6호")  # 나머지 낱말에서 뺄 약한 토큰 사유(흔한 성·간단 표장)
REPRO = ("맛있는 커피 전문점", "cafe")  # 견고성 점검 R-P0-2 재현 입력(이름, 업종 세트)
REPRO_EXTRA = ("맛있는 김밥 전문점", None)  # 같은 항목의 업종 없는 예(보고만)
DISPLAY_TOP = first.DISPLAY_TOP
CONTROL_MODES = (("이름만", False, False), ("이름+업종", False, True),
                 ("이름+이미지", True, False), ("이름+이미지+업종", True, True))
DESCRIPTIVE_MODES = (("이름만", False), ("이름+업종", True))
# 영문 업종어(업종 세트 id → 영어 낱말) — 약한 토큰 사전에 있는 것만 쓴다(한 낱말이 두 업종이면
# 앞쪽)
EN_INDUSTRY = {
    "cafe": ("coffee", "cafe", "espresso", "latte", "roasters", "brew"),
    "chicken": ("chicken", "fried", "wings"),
    "korean_restaurant": ("kitchen", "food", "table", "dining", "restaurant"),
    "bunsik": ("snack", "noodle", "kimbap"),
    "pub": ("beer", "pub", "bar", "brewing", "wine"),
    "bakery": ("bakery", "bread", "cake", "dessert", "sweet"),
    "pizza": ("pizza",),
    "lodging": ("hotel", "stay", "house", "inn"),
    "hair_salon": ("hair", "salon", "style"),
    "nail": ("nail", "nails"),
    "fitness": ("fitness", "gym", "body", "fit", "yoga"),
    "academy": ("academy", "school", "edu", "study", "class"),
    "realty": ("realty", "land", "estate"),
    "flower": ("flower", "flowers", "garden"),
    "clothing": ("fashion", "wear", "style", "shop"),
    "cosmetics": ("beauty", "skin", "cosmetic", "cosmetics", "care"),
    "health_food": ("health", "vita", "organic"),
    "pet": ("pet", "dog", "cat", "pets"),
    "convenience": ("mart", "market", "store"),
    "laundry": ("laundry", "clean", "wash"),
    "photo": ("photo", "studio", "picture"),
    "software": ("soft", "software", "app", "tech", "data"),
    "creator": ("media", "tv", "channel", "creator"),
    "interior": ("interior", "home", "design", "living"),
    "moving_cleaning": ("moving", "clean", "cleaning"),
}
WEAK_RUN = {
    "version": 2, "since": "2026-11-23",
    "rule": ("식별력 결합 규칙 v0.4 — combined_weak_run 은 두 이름 모두에서 연속으로 붙어 있는 "
             "공통 약한 토큰 구간(2개 이상)만 요부 후보로 묶는다(어느 한쪽에서라도 다른 낱말이 "
             "끼면 묶지 않음)"),
    "basis": ("견고성 점검 R-P0-2 — 설명적 낱말만으로 된 이름이 떨어진 약한 낱말(맛있는…전문점)을 "
             "결합으로 보아 '위험'(통합 모델 설계 §7-10). 계수는 다시 학습하지 않음 — 규칙 1 "
             "특징으로 학습"),
}

# 규칙(이 지시로 고정 — 실행 전에 해시를 남기고 결과를 보고 바꾸지 않는다) ------------------------
RULE = {
    "변경": (
        "ml/src/axes/distinctiveness.py combined_weak_run 규칙 2(식별력 v0.4): 두 이름 모두에서 "
        "연속으로 붙어 있는 공통 약한 토큰 구간(2개 이상)만 요부 후보로 묶는다 — 어느 "
        "한쪽에서라도 다른 낱말이 끼면 묶지 않는다, 구간이 여럿이면 모두. 규칙 1(v0.2–v0.3, 양쪽 "
        "약한 토큰열의 가장 긴 공통 부분열)은 version=1 로 남긴다. 다른 식별력 "
        "규칙(점수·요부·combined_single_match·접미 분리)은 그대로. 서비스: 엔진이 계수 JSON 의 "
        "weak_run.version(없으면 1)을 compute_pair_axes 로 넘긴다 — 후보 v1.4.3 = v1.4.2 + "
        "version + weak_run{version 2}(계수·하한·규칙 그대로)."),
    "바꾸기_전·후": (
        "같은 프로세스에서 엔진 계수만 바꾼다 — 전 = v1.4.2 JSON(weak_run 없음 → 규칙 1), 후 = "
        "후보 v1.4.3(규칙 2). 검산: 바꾸기 전 시나리오 16종(전체 grade·prob·pattern, 상위 5 "
        "출원번호)이 v1.4.2 확인 실행 저장값(logo_floor_image_only_searches.json.gz 의 시나리오 "
        "후)과 같아야 한다 — 다르면 멈춤."),
    "학습_특징": (
        "pairs_features.py 를 --weak-run-version 1·2 로 다시 만든다(같은 입력, 작업 폴더 — 심결 + "
        "--refresh-easy). 규칙 1 결과가 저장본 pairs_features.csv·pairs_features_easy.csv 와 "
        "바이트로 같아야 한다(다르면 멈춤). 바뀐 행 수(출처별)·열별 바뀐 칸·축 값 변화(평균·최대 "
        "절대 차이, 오름·내림 수)를 보고한다(행 수로 멈추지 않음)."),
    "채택_AUC": (
        "지금 계수(v1.4.2 JSON)로 심결 행(t4.load_dataset 의 pair_source trial, 최종라벨 "
        "유사·비유사 — 이름도 이미지도 없는 행은 load_dataset 이 뺌)을 규칙 1·2 특징으로 각각 "
        "매긴 위험도(t4.service_features(image_column=x2_whole_raw) → rm.risk_score 의 prob)의 "
        "AUC(가중 없음). 규칙 2 AUC 가 규칙 1 보다 0.01 넘게 낮으면 검색 없이 멈춘다. 사건 "
        "가중(_w) AUC 는 보고만. 통과하면 아래 심결 쌍·표본 A 인용상표 평가는 규칙 2 특징으로 "
        "매긴 위험도를 쓴다(바뀌지 않은 행은 같음)."),
    "설명적_이름": (
        "seed 0. 식별력 사전 shared/distinctiveness/weak_tokens.json 의 약한 토큰만으로 2–4 "
        "낱말(업종어 하나 포함) 이름을 한글 100·영문 100 만든다. 업종어: 한글은 업종 "
        "세트(business_presets.json)의 업종명·별칭·지정상품 명칭을 normalize_name 한 토큰 중 약한 "
        "토큰(그 업종 세트에 대응), 영문은 고정 표 EN_INDUSTRY 중 약한 토큰(한 낱말이 두 업종이면 "
        "표의 앞쪽). 나머지 낱말: 같은 문자(한글·영문)의 약한 토큰 중 첫 사유가 5호·6호가 아니고 "
        "업종어가 아닌 것(한글 2자 이상·영문 3자 이상). 업종 세트를 고르고(업종어가 있는 세트 중) "
        "그 업종어 하나, 낱말 수 2–4, 업종어 자리는 무작위. 이름의 토큰(judge_name — 업종 없이)이 "
        "고른 낱말과 같고 업종 없이·그 업종 세트 유사군으로 모든 토큰이 약해야(점수 < θ) 쓰고, "
        "아니면 다시 뽑는다(같은 이름 제외). 검색: 이름만·이름+업종(그 업종 세트 유사군), 전·후."),
    "채택_1": (
        "(가) R-P0-2 재현 '맛있는 커피 전문점' + 카페 업종 세트의 후 전체 등급(정렬 앞 5건의 최고 "
        "표시 등급)이 검토 권장 아래. (나) 설명적 이름 200 × 2방식의 후 검색에서 '떨어진 약한 "
        "낱말 묶음 때문에 검토 권장 이상'이 0 — 정의: 전체 등급 검토 권장 이상이고, 상위 5 중 "
        "표시 등급 검토 권장 이상인 후보 가운데 그 쌍의 규칙 1·2 제외 토큰(pair_generic — 엔진과 "
        "같은 정리·접미 분리·유사군)이 다르고 엔진이 실제로 뺀 토큰(candidate.removed)이 규칙 1 "
        "의 것과 같은 후보가 있는 경우(전에도 같은 정의로 세어 보고)."),
    "연속_구간": (
        "규칙 1 로 학습 특징을 다시 만들 때 pair_generic 을 부른 쌍(이름 A·B·유사군 — 심결 + 쉬운 "
        "음성) 전부에서 규칙 1 combined_weak_run 이 걸린 쌍을 모은다. 규칙 1 이 묶은 토큰열이 두 "
        "이름 모두의 토큰열(judge_name)에 연속 구간으로 있으면 '붙어 있음', 아니면 '떨어짐'. "
        "채택_2: '붙어 있음' 쌍 전부에서 규칙 2 결과가 규칙 1 의 토큰을 모두 포함(계속 걸림). "
        "'떨어짐' 쌍은 규칙 2 에서 빠짐(빈 결과)·일부 남음을, 규칙 2 에서만 걸리거나 규칙 1 에 "
        "없던 토큰이 생긴 쌍도 보고한다."),
    "대조군": (
        "1차 시도(named_search_thresholds) 대조군 확인용 100(대조군 sha256 f6b11d62…) — "
        "이름만·이름+업종·이름+이미지·이름+이미지+업종 400검색 전·후. 채택_3: 네 방식마다 전체 "
        "등급 검토 권장 이상 비율과 위험 이상 비율이 후 ≤ 전."),
    "표본A_인용상표": (
        "nameless_search_thresholds.prepare 의 표본 A 사건 — 심결 행 중 이름 있는 쌍(1차 시도 "
        "채택_4 의 정의: t4.service_features(image_column=x2_whole_raw), mark_type 이미지 있으면 "
        "결합-문자요부·없으면 문자, named_search_thresholds.features_grade)을 규칙 1·2 특징으로 "
        "매긴다. 채택_4: 검토 권장 이상 비율이 후 ≥ 전 − 0.02. 표본 A 검색(이름+이미지(+질의 "
        "업종) 184) 전체 등급 분포는 보고만."),
    "심결_쌍": (
        "채택_AUC 의 심결 행을 지금 계수로 규칙 1·2 특징 등급(features_grade)으로 매긴다. 채택_5: "
        "이번 변경으로 새로 위험이 된 행의 유사 비율 ≥ 0.70(5행 이상일 때), 위험에서 빠진 행 중 "
        "유사 비율 ≤ 0.5(5행 이상일 때) — 5행 미만이면 판정에 쓰지 않고 목록만. 전체 위험 정밀도 "
        "전·후는 보고만."),
    "시나리오": "named_shared_threshold.SCENARIOS 16종 multi_search(top_k 5) 전·후 — 시연 넷 포함.",
    "적용": (
        "채택될 때만 shared/model/risk_model_v1.4.3.json = 후보(v1.4.2 + version + weak_run), "
        "서비스 기본 모델 v1.4.3. verify 가 기본 엔진으로 재현 입력·설명적 이름·대조군·표본 "
        "A·시나리오를 다시 돌려 후 실행과 같은지 본다."),
}


def _settings() -> dict:
    return {"RULE": RULE, "BASE_VERSION": BASE_VERSION, "NEW_VERSION": NEW_VERSION,
            "WEAK_RUN": WEAK_RUN, "AUC_DROP_MAX": AUC_DROP_MAX,
            "SAMPLE_A_DROP_MAX": SAMPLE_A_DROP_MAX, "PRECISION_MIN": PRECISION_MIN,
            "DROPPED_SIMILAR_MAX": DROPPED_SIMILAR_MAX, "MIN_ROWS": MIN_ROWS, "SEED": SEED,
            "NAMES_PER_SCRIPT": NAMES_PER_SCRIPT, "WORD_COUNTS": WORD_COUNTS,
            "SKIP_REASONS": SKIP_REASONS, "REPRO": REPRO, "REPRO_EXTRA": REPRO_EXTRA,
            "DISPLAY_TOP": DISPLAY_TOP, "CONTROL_MODES": CONTROL_MODES,
            "DESCRIPTIVE_MODES": DESCRIPTIVE_MODES, "EN_INDUSTRY": EN_INDUSTRY,
            "CONTROL_SHA": ns.CONTROL_SHA}


def rule_sha256() -> str:
    return first.canonical_sha256(_settings())


def _inputs() -> dict[str, Path]:
    from scripts import nameless_search_thresholds as nst

    return {"계수_JSON(v1.4.2)": BASE_MODEL_PATH, "학습_특징": FEATURES, "쉬운_음성": EASY,
            "라벨": nst.DEFAULT_LABELS, "큐": TRIALS / "curation_queue.csv",
            "이미지_쌍": nst.DEFAULT_IMAGE_PAIRS, "메타데이터": nst.DEFAULT_METADATA,
            "색인": ML_ROOT / "data" / "index" / "kipris.faiss",
            "유형_사전": ML_ROOT / "data" / "types.json", "약한_토큰": WEAK_TOKENS,
            "업종_세트": PRESETS, "식별력_통계": dx.DEFAULT_STATS_PATH,
            "기술적_표장": dx.DEFAULT_DESCRIPTIVE_PATH, "약한_토큰_예외": dx.DEFAULT_OVERRIDES_PATH,
            "대조군": first._paths(TRIALS)["control"], "시나리오_저장값": SAVED_SCENARIOS,
            "심판_목록": nst.DEFAULT_LIST, "별칭": nst.DEFAULT_ALIASES,
            "식별력": ML_ROOT / "src" / "axes" / "distinctiveness.py",
            "쌍_축": ML_ROOT / "src" / "axes" / "pair_axes.py",
            "학습_특징_스크립트": ML_ROOT / "scripts" / "pairs_features.py",
            "엔진": REPO_ROOT / "backend" / "src" / "core" / "multi_search.py",
            "런타임": ML_ROOT / "src" / "model" / "risk_model.py"}


def _paths(out_dir: Path) -> dict[str, Path]:
    return {"rule": out_dir / f"{STEM}_rule.json", "results": out_dir / f"{STEM}_results.json",
            "report": out_dir / f"{STEM}_report.md",
            "candidate": out_dir / f"{STEM}_candidate.json",
            "searches": out_dir / f"{STEM}_searches.json.gz",
            "verify": out_dir / f"{STEM}_verify.json", "features": out_dir / f"{STEM}_features"}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---- 순수 함수(시험 대상) ----------------------------------------------------------------------

def candidate_model(base: dict) -> dict:
    """v1.4.2 JSON → v1.4.3: 버전과 weak_run 만 — 계수·하한·규칙은 그대로."""
    out = copy.deepcopy(base)
    out["version"] = NEW_VERSION
    out[rm.WEAK_RUN_KEY] = dict(WEAK_RUN)
    out.setdefault("meta", {})["weak_run"] = {
        "derived_from": base.get("version"), "rule_sha256": rule_sha256(),
        "script": "ml/scripts/weak_run_adjacent.py"}
    rm.validate_model({**out, "version": base["version"]})  # 구조 검증(새 버전 등록은 적용 때)
    return out


def auc(scores: list[float], labels: list[int], weights: list[float] | None = None) -> float:
    """만-휘트니 AUC(같은 점수는 0.5). weights 가 있으면 쌍마다 두 가중의 곱."""
    weights = weights or [1.0] * len(scores)
    pos = [(s, w) for s, y, w in zip(scores, labels, weights) if y == 1]
    neg = [(s, w) for s, y, w in zip(scores, labels, weights) if y == 0]
    total = sum(wp for _, wp in pos) * sum(wn for _, wn in neg)
    if not total:
        return float("nan")
    hit = 0.0
    for sp, wp in pos:
        for sn, wn in neg:
            if sp > sn:
                hit += wp * wn
            elif sp == sn:
                hit += 0.5 * wp * wn
    return hit / total


def contiguous_in(run: tuple[str, ...], tokens: list[str]) -> bool:
    """run 이 tokens 안에 연속 구간으로 있는가."""
    k = len(run)
    return any(tuple(tokens[i:i + k]) == tuple(run) for i in range(len(tokens) - k + 1))


def classify_pair(dist, name_a: str, name_b: str, goods) -> dict | None:
    """규칙 1 이 걸린 쌍이면 {붙어 있음, 계속 걸림, 규칙 1·2 토큰} — 아니면 None(규칙 2 만 걸리면
    '규칙2만')."""
    run1 = dist.combined_weak_run(name_a, name_b, goods, version=1)
    run2 = dist.combined_weak_run(name_a, name_b, goods, version=2)
    if not run1:
        return {"규칙2만": list(run2)} if run2 else None
    tokens_a = [j.token for j in dist.judge_name(name_a, goods)]
    tokens_b = [j.token for j in dist.judge_name(name_b, goods)]
    adjacent = contiguous_in(run1, tokens_a) and contiguous_in(run1, tokens_b)
    return {"붙어_있음": adjacent, "계속_걸림": set(run1) <= set(run2), "규칙1": list(run1),
            "규칙2": list(run2), "규칙1에_없던_토큰": sorted(set(run2) - set(run1))}


def check_preservation(records: list[dict]) -> dict:
    fired = [r for r in records if r["판정"] is not None and "규칙1" in r["판정"]]
    adjacent = [r for r in fired if r["판정"]["붙어_있음"]]
    separated = [r for r in fired if not r["판정"]["붙어_있음"]]
    kept = [r for r in adjacent if r["판정"]["계속_걸림"]]
    lost = [r for r in adjacent if not r["판정"]["계속_걸림"]]
    only2 = [r for r in records if r["판정"] is not None and "규칙2만" in r["판정"]]
    extra = [r for r in fired if r["판정"]["규칙1에_없던_토큰"]]
    return {"쌍": len(records), "규칙1_걸림": len(fired),
            "붙어_있음": {"쌍": len(adjacent), "계속_걸림": len(kept), "빠짐": len(lost),
                       "빠진_예": lost[:20]},
            "떨어짐": {"쌍": len(separated),
                     "규칙2_빈_결과": sum(1 for r in separated if not r["판정"]["규칙2"]),
                     "일부_남음": sum(1 for r in separated if r["판정"]["규칙2"]),
                     "예": separated[:15]},
            "규칙2만_걸림": len(only2), "규칙1에_없던_토큰이_생김": len(extra),
            "통과": len(lost) == 0}


def grade_rates(grades: list) -> dict:
    return {REVIEW: lf.rate([lf.at_least(g, REVIEW) for g in grades]),
            RISK: lf.rate([lf.at_least(g, RISK) for g in grades])}


def check_control(rows: list[dict]) -> dict:
    out = {}
    passed = True
    for label, _, _ in CONTROL_MODES:
        before = grade_rates([row["방식"][label]["전"]["전체"] for row in rows])
        after = grade_rates([row["방식"][label]["후"]["전체"] for row in rows])
        ok = all(after[k] is not None and before[k] is not None and after[k] <= before[k] + 1e-12
                 for k in before)
        out[label] = {"전": before, "후": after,
                      "분포_전": lf.distribution(row["방식"][label]["전"]["전체"] for row in rows),
                      "분포_후": lf.distribution(row["방식"][label]["후"]["전체"] for row in rows),
                      "통과": ok}
        passed = passed and ok
    return {"방식": out, "질의": len(rows), "통과": passed}


def check_grade_changes(rows: list[dict], before: list[str], after: list[str]) -> dict:
    """채택_5 — 심결 행(최종라벨) 의 등급이 규칙 1 → 2 로 바뀐 것만."""
    new_risk = [i for i, (b, a) in enumerate(zip(before, after)) if a == RISK and b != RISK]
    dropped = [i for i, (b, a) in enumerate(zip(before, after)) if b == RISK and a != RISK]

    def describe(index: int) -> dict:
        row = rows[index]
        return {"심판번호": row.get("심판번호"), "이름A": row.get("이름A"),
                "이름B": row.get("이름B"), "최종라벨": row.get("최종라벨"),
                "전": before[index], "후": after[index]}

    def similar_share(indices: list[int]) -> float | None:
        if not indices:
            return None
        return round(sum(rows[i].get("최종라벨") == "유사" for i in indices) / len(indices), 4)

    new_share, dropped_share = similar_share(new_risk), similar_share(dropped)
    judged_new, judged_dropped = len(new_risk) >= MIN_ROWS, len(dropped) >= MIN_ROWS
    passed = ((not judged_new or new_share >= PRECISION_MIN - 1e-12)
              and (not judged_dropped or dropped_share <= DROPPED_SIMILAR_MAX + 1e-12))

    def precision(grades: list[str]) -> dict:
        risk = [i for i, g in enumerate(grades) if g == RISK]
        return {"위험": len(risk), "유사": sum(rows[i].get("최종라벨") == "유사" for i in risk),
                "정밀도": similar_share(risk)}

    return {"행": len(rows), "바뀐_행": sum(1 for b, a in zip(before, after) if b != a),
            "등급_전": lf.distribution(before), "등급_후": lf.distribution(after),
            "새로_위험": {"행": len(new_risk), "유사_비율": new_share, "판정에_씀": judged_new,
                       "목록": [describe(i) for i in new_risk]},
            "위험에서_빠짐": {"행": len(dropped), "유사_비율": dropped_share,
                         "판정에_씀": judged_dropped, "목록": [describe(i) for i in dropped]},
            "전체_위험_정밀도": {"전": precision(before), "후": precision(after)},
            "통과": passed}


def descriptive_names(dist, presets: dict[str, tuple[str, ...]], weak_rows: list[dict],
                      preset_rows: list[dict]) -> list[dict]:
    """설명적 이름 200(seed 0) — 규칙 '설명적_이름'."""
    from src.axes.x1_phonetic import normalize_name

    weak = {row["token"]: row for row in weak_rows}
    ko_industry: dict[str, list[str]] = {}
    claimed: set[str] = set()  # 한 낱말이 두 업종이면 파일의 앞쪽 업종
    for preset in preset_rows:
        words: list[str] = []
        texts = [preset["업종명"], *preset.get("별칭", []),
                 *[good["name"] for good in preset.get("지정상품", [])]]
        for text in texts:
            for token in normalize_name(text):
                if (token in weak and re.fullmatch(r"[가-힣]+", token)
                        and token not in claimed and token not in words):
                    words.append(token)
        claimed.update(words)
        if words:
            ko_industry[preset["id"]] = words
    en_industry: dict[str, list[str]] = {}
    used_en: set[str] = set()
    for preset_id, words in EN_INDUSTRY.items():
        kept = [w for w in words if w in weak and w not in used_en]
        used_en.update(kept)
        if kept:
            en_industry[preset_id] = kept

    def modifiers(pattern: str, minimum: int, industry: set[str]) -> list[str]:
        return sorted(token for token, row in weak.items()
                      if re.fullmatch(pattern, token) and len(token) >= minimum
                      and token not in industry
                      and not row["reasons"][0].startswith(SKIP_REASONS))

    rng = random.Random(SEED)
    out: list[dict] = []
    seen: set[str] = set()
    for script, industry, pool in (
            ("한글", ko_industry,
             modifiers(r"[가-힣]+", 2, {w for v in ko_industry.values() for w in v})),
            ("영문", en_industry,
             modifiers(r"[a-z]+", 3, {w for v in en_industry.values() for w in v}))):
        preset_ids = sorted(p for p in industry if p in presets)
        made = attempts = 0
        while made < NAMES_PER_SCRIPT:
            attempts += 1
            if attempts > 50_000:
                raise RuntimeError(f"설명적 이름({script})을 {NAMES_PER_SCRIPT}개 만들지 못함")
            preset_id = rng.choice(preset_ids)
            word = rng.choice(industry[preset_id])
            count = rng.choice(WORD_COUNTS)
            words = rng.sample(pool, count - 1)
            words.insert(rng.randrange(count), word)
            name = " ".join(words)
            if name in seen:
                continue
            goods = presets[preset_id]
            plain = dist.judge_name(name)
            with_goods = dist.judge_name(name, goods)
            if ([j.token for j in plain] != [w.lower() for w in words]
                    or any(j.score >= dist.theta for j in plain)
                    or any(j.score >= dist.theta for j in with_goods)):
                continue
            seen.add(name)
            made += 1
            out.append({"이름": name, "문자": script, "업종": preset_id, "업종어": word,
                        "유사군": list(goods)})
    return out


# ---- 0. 고정 -----------------------------------------------------------------------------------

def command_freeze(args) -> int:
    paths = _paths(args.out_dir)
    if paths["rule"].exists() and not args.force:
        print(f"거절: {paths['rule']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    if control["대조군_sha256"] != ns.CONTROL_SHA:
        print("거절: 1차 시도 대조군 해시가 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    args.out_dir.mkdir(parents=True, exist_ok=True)
    frozen = {"설정_sha256": rule_sha256(), "스크립트_sha256": first.file_sha256(Path(__file__)),
              "입력_sha256": {k: first.file_sha256(p) for k, p in _inputs().items()},
              "고정": _now(), "설정": _settings()}
    paths["rule"].write_text(json.dumps(frozen, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    print(f"설정 sha256 {frozen['설정_sha256']} · 스크립트 sha256 {frozen['스크립트_sha256']} · "
          f"식별력 sha256 {frozen['입력_sha256']['식별력']}")
    return 0


def _check_frozen(paths: dict, *, model_may_change: bool = False) -> dict | None:
    if not paths["rule"].exists():
        print("거절: 먼저 freeze", file=sys.stderr)
        return None
    frozen = json.loads(paths["rule"].read_text(encoding="utf-8"))
    if frozen["설정_sha256"] != rule_sha256():
        print("거절: 설정이 고정본과 다릅니다", file=sys.stderr)
        return None
    skip = {"런타임"} if model_may_change else set()  # 적용 뒤에는 기본 경로·버전 상수가 바뀐다
    changed = [k for k, p in _inputs().items()
               if k not in skip and first.file_sha256(p) != frozen["입력_sha256"].get(k)]
    if changed:
        print(f"거절: 입력이 고정 때와 다릅니다 — {changed}", file=sys.stderr)
        return None
    return frozen


# ---- 1. 학습 특징(먼저) -------------------------------------------------------------------------

def regenerate(work: Path, version: int, record: list | None = None) -> None:
    """pairs_features.py 를 같은 프로세스에서 version 으로 다시 만든다(심결 + 쉬운 음성 새로 계산).
    record 가 있으면 pair_generic 호출(이름 A·B·유사군)을 모은다."""
    from scripts import pairs_features as pf

    work.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EASY, work / "pairs_features_easy.csv")
    original = dx.Distinctiveness.pair_generic

    def recording(self, name_a, name_b, goods_codes=None, **kwargs):
        if record is not None:
            record.append((name_a, name_b, tuple(sorted(goods_codes)) if goods_codes else None))
        return original(self, name_a, name_b, goods_codes, **kwargs)

    dx.Distinctiveness.pair_generic = recording
    try:
        out = work / "pairs_features.csv"
        for extra in ([], ["--refresh-easy"]):
            code = pf.main(["--out", str(out), "--weak-run-version", str(version), *extra])
            if code:
                raise RuntimeError(f"pairs_features 실패(규칙 {version}, {extra})")
    finally:
        dx.Distinctiveness.pair_generic = original


def _read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def feature_changes(v1_dir: Path, v2_dir: Path) -> dict:
    out = {}
    for name in ("pairs_features.csv", "pairs_features_easy.csv"):
        fields, rows1 = _read_csv(v1_dir / name)
        _, rows2 = _read_csv(v2_dir / name)
        if len(rows1) != len(rows2):
            raise RuntimeError(f"{name}: 행 수가 다름 {len(rows1)} ≠ {len(rows2)}")
        changed_rows = Counter()
        cells = Counter()
        deltas: dict[str, list[float]] = {}
        for r1, r2 in zip(rows1, rows2):
            columns = [c for c in fields if r1.get(c) != r2.get(c)]
            if not columns:
                continue
            changed_rows[r1.get("pair_source") or "trial"] += 1
            cells.update(columns)
            for column in columns:
                try:
                    deltas.setdefault(column, []).append(float(r2[column]) - float(r1[column]))
                except (TypeError, ValueError):
                    pass
        out[name] = {"행": len(rows1), "바뀐_행": dict(changed_rows),
                     "바뀐_행_합계": sum(changed_rows.values()), "열별_바뀐_칸": dict(cells),
                     "축_값_변화": {c: {"칸": len(v), "평균": round(sum(v) / len(v), 4),
                                    "최대_절대": round(max(abs(x) for x in v), 4),
                                    "오름": sum(1 for x in v if x > 0),
                                    "내림": sum(1 for x in v if x < 0)}
                               for c, v in deltas.items() if v}}
    return out


def trial_scores(features: Path, easy: Path, model: dict) -> dict:
    from scripts import train_risk_model_v14 as t4

    rows = [row for row in t4.load_dataset(features, easy).rows
            if row.get("pair_source") == "trial"]
    feats = [t4.service_features(row, image_column=t4.RAW_IMAGE) for row in rows]
    return {"rows": rows, "prob": [rm.risk_score(f, model).prob for f in feats],
            "grade": [first.features_grade(f, model, None) for f in feats],
            "y": [1 if row.get("최종라벨") == "유사" else 0 for row in rows],
            "w": [float(row.get("_w", 1.0)) for row in rows]}


def cited_pairs(features: Path, easy: Path, case_ids: set[str], model: dict) -> dict:
    """표본 A 인용상표 — 1차 시도 채택_4 의 쌍·서비스 채점식."""
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    grades: list[str] = []
    labels: list[str] = []
    for row in t4.load_dataset(features, easy).rows:
        if row.get("pair_source") != "trial" or str(row.get("심판번호")) not in case_ids:
            continue
        if not tr.has_name(row):
            continue
        feats = t4.service_features(row, image_column=t4.RAW_IMAGE)
        feats["mark_type"] = "결합-문자요부" if feats["x2_whole"] is not None else "문자"
        grades.append(first.features_grade(feats, model, None))
        labels.append(row.get("최종라벨"))
    return {"grades": grades, "labels": labels}


def training_phase(paths: dict, model: dict) -> dict:
    work = paths["features"]
    if work.exists():
        shutil.rmtree(work)
    record: list = []
    started = time.perf_counter()
    regenerate(work / "v1", 1, record)
    regenerate(work / "v2", 2)
    same = {name: (work / "v1" / name).read_bytes() == path.read_bytes()
            for name, path in (("pairs_features.csv", FEATURES),
                               ("pairs_features_easy.csv", EASY))}
    out = {"규칙1_저장본과_같음": same, "걸린_시간_s": round(time.perf_counter() - started, 1)}
    if not all(same.values()):
        out["멈춤"] = "규칙 1 로 다시 만든 특징이 저장본과 다름"
        return out
    out["특징_변화"] = feature_changes(work / "v1", work / "v2")
    s1 = trial_scores(work / "v1" / "pairs_features.csv", work / "v1" / "pairs_features_easy.csv",
                      model)
    s2 = trial_scores(work / "v2" / "pairs_features.csv", work / "v2" / "pairs_features_easy.csv",
                      model)
    keys = [(r.get("심판번호"), r.get("상대번호"), r.get("쌍키")) for r in s1["rows"]]
    if keys != [(r.get("심판번호"), r.get("상대번호"), r.get("쌍키")) for r in s2["rows"]]:
        raise RuntimeError("규칙 1·2 심결 행이 맞지 않음")
    auc1, auc2 = auc(s1["prob"], s1["y"]), auc(s2["prob"], s2["y"])
    out["AUC"] = {"행": len(s1["rows"]), "유사": sum(s1["y"]),
                  "규칙1": round(auc1, 4), "규칙2": round(auc2, 4),
                  "차이": round(auc2 - auc1, 4),
                  "가중_규칙1": round(auc(s1["prob"], s1["y"], s1["w"]), 4),
                  "가중_규칙2": round(auc(s2["prob"], s2["y"], s2["w"]), 4),
                  "바뀐_위험도_행": sum(1 for a, b in zip(s1["prob"], s2["prob"]) if a != b),
                  "통과": auc2 >= auc1 - AUC_DROP_MAX - 1e-12}
    out["심결_쌍"] = check_grade_changes(s1["rows"], s1["grade"], s2["grade"])
    dist = dx.load_distinctiveness(with_goods=True)
    unique = sorted(set(record), key=lambda item: (item[0], item[1], item[2] or ()))
    records = [{"이름A": a, "이름B": b, "유사군": list(g) if g else None,
                "판정": classify_pair(dist, a, b, list(g) if g else None)} for a, b, g in unique]
    out["연속_구간"] = check_preservation(records)
    return out


# ---- 2. 검색 -----------------------------------------------------------------------------------

def summarize(pooled, dist, query_name, query_goods) -> dict:
    """전체 등급·상위 5, 그리고 채택_1(나)의 '떨어진 약한 낱말 묶음' 후보."""
    top = pooled.candidates[:DISPLAY_TOP]
    flagged = []
    if query_name:
        a = dist.split_goods_suffix(pa.clean_name(query_name))
        for c in top:
            if not c.title or not lf.at_least(c.grade, REVIEW):
                continue
            b = dist.split_goods_suffix(pa.clean_name(c.title))
            record = _record_goods(c.id)
            goods = (pa.normalize_codes(query_goods) | pa.normalize_codes(record)) or None
            g1 = dist.pair_generic(a, b, goods, weak_run_version=1)
            g2 = dist.pair_generic(a, b, goods, weak_run_version=2)
            used = {item["token"] for item in c.removed}
            if g1 != g2 and used == set(g1):
                flagged.append({"id": c.id, "title": c.title, "등급": c.grade,
                                "규칙1_뺌": sorted(g1), "규칙2_뺌": sorted(g2)})
    overall = lf.overall_grade([c.grade for c in pooled.candidates])
    return {"전체": overall,
            "상위": [{"id": c.id, "title": c.title, "등급": c.grade, "p": round(float(c.prob), 6),
                    "pattern": c.pattern, "규칙": list(c.rule_triggers)} for c in top],
            "떨어진_묶음_후보": flagged,
            "떨어진_묶음_때문": bool(flagged) and lf.at_least(overall, REVIEW)}


_RECORD_GOODS: dict[str, tuple[str, ...]] = {}


def _record_goods(appno: str) -> tuple[str, ...]:
    return _RECORD_GOODS.get(appno, ())


def run_searches(context: dict, models: dict[str, dict], names: list[dict],
                 limit: int | None) -> dict:
    ms = context["ms"]
    dist = ms.state.distinct
    _RECORD_GOODS.clear()
    _RECORD_GOODS.update({r.appno: tuple(r.goods) for r in ms.state.records})
    presets = {pid: codes for pid, _, codes in first.preset_table(ms)}

    def pair(**inputs) -> dict:
        out = {}
        for mode in ("전", "후"):
            with ns.using_model(ms, models[mode]):
                pooled = ms.search_pool(**inputs)
            out[mode] = summarize(pooled, dist, inputs.get("name"), inputs.get("goods_codes"))
        return out

    timing: dict[str, float] = {}

    def tick(label: str, began: float) -> None:
        timing[label] = round(time.perf_counter() - began, 1)
        print(f"  {label} {timing[label]}초", flush=True)

    began = time.perf_counter()
    repro = {}
    for name, preset_id in (REPRO, REPRO_EXTRA):
        goods = list(presets[preset_id]) if preset_id else None
        repro[f"{name} + {preset_id or '업종 없음'}"] = pair(name=name, goods_codes=goods)
    descriptive = []
    for item in names[:limit]:
        row = {**item, "방식": {}}
        for label, with_goods in DESCRIPTIVE_MODES:
            row["방식"][label] = pair(name=item["이름"],
                                      goods_codes=item["유사군"] if with_goods else None)
        descriptive.append(row)
    tick("재현·설명적 이름", began)
    a_by_key = {query.key: query for query in context["A"]}
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    began = time.perf_counter()
    controls = []
    for item in control["대조군"]["이름"]["확인용"][:limit]:
        image = context["service"](a_by_key[item["이미지"]].path.read_bytes())
        goods = sorted(item["유사군"]) or None
        row = {"이름": item["이름"], "방식": {}}
        for label, with_image, with_goods in CONTROL_MODES:
            row["방식"][label] = pair(name=item["이름"], image=image if with_image else None,
                                      goods_codes=goods if with_goods else None)
        controls.append(row)
    tick("대조군", began)
    began = time.perf_counter()
    sample_a = []
    for query in context["A"][:limit]:
        image = context["service"](query.path.read_bytes())
        sample_a.append({"질의": query.key,
                         "이름+이미지": pair(image=image, name=query.name,
                                          goods_codes=sorted(query.goods) or None)})
    tick("표본A", began)
    return {"재현": repro, "설명적_이름": descriptive, "대조군": controls, "표본A": sample_a,
            "시간_s": timing}


def command_run(args) -> int:
    paths = _paths(args.out_dir)
    frozen = _check_frozen(paths)
    if frozen is None:
        return EXIT_REFUSED
    if paths["searches"].exists() and not args.force:
        print(f"거절: {paths['searches']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    base = rm.validate_model(json.loads(BASE_MODEL_PATH.read_text(encoding="utf-8")))
    if base.get("version") != BASE_VERSION or rm.weak_run_version(base) != 1:
        print("거절: 기준 모델이 weak_run 없는 v1.4.2 가 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    candidate = candidate_model(base)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    paths["candidate"].write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
    out = {"설정_sha256": frozen["설정_sha256"],
           "스크립트_sha256(고정 때)": frozen["스크립트_sha256"],
           "스크립트_sha256(잴 때)": first.file_sha256(Path(__file__)), "스모크": bool(args.smoke)}
    print("1. 학습 특징(규칙 1·2)", flush=True)
    out["학습"] = training_phase(paths, base)
    print(f"  {json.dumps(out['학습'].get('AUC'), ensure_ascii=False)}", flush=True)
    stop = out["학습"].get("멈춤") or (None if out["학습"]["AUC"]["통과"]
                                     else "학습 특징 AUC 가 0.01 넘게 떨어짐")
    if stop is None:
        print("2. 검색 전·후", flush=True)
        context = ns._context(BASE_MODEL_PATH)
        ms = context["ms"]
        if ms.state.model.get("version") != BASE_VERSION:
            print("거절: 엔진이 적재한 모델이 v1.4.2 가 아닙니다", file=sys.stderr)
            return EXIT_REFUSED
        lo.memo_ocr(ms)
        models = {"전": ms.state.model, "후": candidate}
        scenario_runs = lo.scenarios(context, models)
        fidelity = scenario_fidelity(scenario_runs["전"])
        out["검산_시나리오"] = fidelity
        out["시나리오"] = scenario_runs
        print(f"  시나리오 검산 {fidelity}", flush=True)
        if not fidelity["같음"]:
            stop = "바꾸기 전 시나리오가 저장값과 다름"
        else:
            weak_rows = json.loads(WEAK_TOKENS.read_text(encoding="utf-8"))["tokens"]
            preset_rows = json.loads(PRESETS.read_text(encoding="utf-8"))
            presets = {pid: codes for pid, _, codes in first.preset_table(ms)}
            names = descriptive_names(ms.state.distinct, presets, weak_rows, preset_rows)
            out["설명적_이름_목록"] = names
            out.update(run_searches(context, models, names, 4 if args.smoke else None))
    out["멈춤"] = stop
    out["걸린_시간_s"] = round(time.perf_counter() - started, 1)
    out["끝"] = _now()
    with gzip.open(paths["searches"], "wt", encoding="utf-8") as handle:
        json.dump(out, handle, ensure_ascii=False)
    print(f"→ {paths['searches']}")
    if stop:
        print(f"멈춤: {stop}", file=sys.stderr)
        return EXIT_STOP
    return 0


def scenario_fidelity(before: dict) -> dict:
    with gzip.open(SAVED_SCENARIOS, "rt", encoding="utf-8") as handle:
        saved = json.load(handle)["시나리오"]["후"]
    differ = [key for key, item in saved.items()
              if item.get("전체") != before.get(key, {}).get("전체")
              or [c["id"] for c in item.get("상위", [])]
              != [c["id"] for c in before.get(key, {}).get("상위", [])]]
    return {"견준_시나리오": len(saved), "다른_것": differ, "같음": not differ}


# ---- 3. 채택 조건·보고 ------------------------------------------------------------------------

def check_repro_and_descriptive(searches: dict) -> dict:
    key = f"{REPRO[0]} + {REPRO[1]}"
    repro = searches["재현"][key]
    repro_ok = not lf.at_least(repro["후"]["전체"], REVIEW)
    table = {}
    flagged_after = flagged_before = 0
    for label, _ in DESCRIPTIVE_MODES:
        rows = searches["설명적_이름"]
        block = {}
        for script in ("한글", "영문", "합계"):
            sel = [r for r in rows if script == "합계" or r["문자"] == script]
            block[script] = {"전": lf.distribution(r["방식"][label]["전"]["전체"] for r in sel),
                             "후": lf.distribution(r["방식"][label]["후"]["전체"] for r in sel)}
        before = sum(1 for r in rows if r["방식"][label]["전"]["떨어진_묶음_때문"])
        after = sum(1 for r in rows if r["방식"][label]["후"]["떨어진_묶음_때문"])
        flagged_before += before
        flagged_after += after
        table[label] = {**block, "떨어진_묶음_때문_검토권장이상": {"전": before, "후": after}}
    return {"재현": {"입력": key, "전": repro["전"]["전체"], "후": repro["후"]["전체"],
                   "후_상위": repro["후"]["상위"][:3], "통과": repro_ok},
            "재현_업종없음": {k: {"전": v["전"]["전체"], "후": v["후"]["전체"]}
                         for k, v in searches["재현"].items() if k != key},
            "설명적_이름": table, "떨어진_묶음_때문": {"전": flagged_before, "후": flagged_after},
            "질의": len(searches["설명적_이름"]),
            "통과": repro_ok and flagged_after == 0}


def check_sample_a(paths: dict, model: dict, case_ids: set[str]) -> dict:
    work = paths["features"]
    before = cited_pairs(work / "v1" / "pairs_features.csv",
                         work / "v1" / "pairs_features_easy.csv", case_ids, model)
    after = cited_pairs(work / "v2" / "pairs_features.csv",
                        work / "v2" / "pairs_features_easy.csv", case_ids, model)
    r0 = lf.rate([lf.at_least(g, REVIEW) for g in before["grades"]])
    r1 = lf.rate([lf.at_least(g, REVIEW) for g in after["grades"]])
    changed = Counter(f"{label} {g0}→{g1}" for label, g0, g1
                      in zip(before["labels"], before["grades"], after["grades"]) if g0 != g1)
    return {"쌍": len(before["grades"]), "사건": len(case_ids),
            "등급_전": lf.distribution(before["grades"]),
            "등급_후": lf.distribution(after["grades"]),
            "검토_권장_이상": {"전": r0, "후": r1,
                         "차이": None if r0 is None or r1 is None else round(r1 - r0, 4)},
            "바뀐_쌍": dict(changed),
            "통과": r0 is not None and r1 is not None and r1 >= r0 - SAMPLE_A_DROP_MAX - 1e-12}


def scenario_table(scenarios: dict) -> list[dict]:
    return lo.scenario_table(scenarios)


def command_report(args) -> int:
    paths = _paths(args.out_dir)
    frozen = _check_frozen(paths)
    if frozen is None:
        return EXIT_REFUSED
    with gzip.open(paths["searches"], "rt", encoding="utf-8") as handle:
        searches = json.load(handle)
    if searches["설정_sha256"] != frozen["설정_sha256"]:
        print("거절: 검색 원자료가 다른 설정으로 만들어졌습니다", file=sys.stderr)
        return EXIT_REFUSED
    base = rm.validate_model(json.loads(BASE_MODEL_PATH.read_text(encoding="utf-8")))
    results = {key: searches.get(key) for key in (
        "설정_sha256", "스크립트_sha256(고정 때)", "스크립트_sha256(잴 때)", "스모크",
        "검산_시나리오")}
    results["스크립트_sha256(보고 때)"] = first.file_sha256(Path(__file__))
    results["식별력_sha256"] = frozen["입력_sha256"]["식별력"]
    learn = searches["학습"]
    results["학습_특징"] = {k: learn.get(k) for k in ("규칙1_저장본과_같음", "특징_변화", "AUC",
                                                  "걸린_시간_s", "멈춤")}
    if searches.get("멈춤"):
        results.update(채택=False, 멈춤=searches["멈춤"], 끝=_now())
        if "연속_구간" in learn:
            results["연속_구간"] = learn["연속_구간"]
            results["채택_5"] = learn["심결_쌍"]
        return _finish(paths, results)
    case_ids = {row["질의"].split(":")[1] for row in searches["표본A"]}
    results["채택_1"] = check_repro_and_descriptive(searches)
    results["채택_2"] = learn["연속_구간"]
    results["채택_3"] = check_control(searches["대조군"])
    results["채택_4"] = check_sample_a(paths, base, case_ids)
    results["채택_5"] = learn["심결_쌍"]
    results["표본A_검색"] = {
        "질의": len(searches["표본A"]),
        "전": lf.distribution(r["이름+이미지"]["전"]["전체"] for r in searches["표본A"]),
        "후": lf.distribution(r["이름+이미지"]["후"]["전체"] for r in searches["표본A"]),
        "바뀐_질의": sum(1 for r in searches["표본A"]
                     if r["이름+이미지"]["전"]["전체"] != r["이름+이미지"]["후"]["전체"])}
    results["시나리오"] = scenario_table(searches["시나리오"])
    results["설명적_이름_예"] = [r["이름"] for r in searches["설명적_이름"][:10]]
    results["시간_s"] = searches.get("시간_s")
    results["채택"] = all(results[f"채택_{i}"]["통과"] for i in range(1, 6)) and (
        learn["AUC"]["통과"])
    results["끝"] = _now()
    return _finish(paths, results)


def _finish(paths: dict, results: dict) -> int:
    paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    paths["report"].write_text(report_text(results), encoding="utf-8")
    print(json.dumps({k: results.get(k) for k in ("채택", "멈춤")}, ensure_ascii=False))
    print(f"→ {paths['results']}\n→ {paths['report']}")
    return 0 if results.get("채택") else EXIT_STOP


def report_text(results: dict) -> str:
    lines = ["# R-P0-2 — 식별력 결합 규칙의 약한 토큰열을 붙어 있는 구간만 — 확인 표본 보고", "",
             f"- 설정 sha256 `{results['설정_sha256']}` · 식별력 sha256 "
             f"`{results.get('식별력_sha256')}`",
             f"- 스크립트 고정 `{results['스크립트_sha256(고정 때)']}` · 잴 때 "
             f"`{results['스크립트_sha256(잴 때)']}` · 보고 때 "
             f"`{results.get('스크립트_sha256(보고 때)')}`",
             f"- 스모크 {results['스모크']} · 채택 **{results.get('채택')}** · 멈춤 "
             f"{results.get('멈춤')}", "", "## 학습 특징(먼저)", "", "```",
             json.dumps(results.get("학습_특징"), ensure_ascii=False)[:3000], "```"]
    for i in range(1, 6):
        if f"채택_{i}" in results:
            lines += ["", f"## 채택 {i} — {results[f'채택_{i}'].get('통과')}", "", "```",
                      json.dumps(results[f"채택_{i}"], ensure_ascii=False)[:3000], "```"]
    if "시나리오" in results:
        lines += ["", "## 시나리오 16종", "", "| 키 | 제목 | 전 | 후 | 1위(전 → 후) |",
                  "|---|---|---|---|---|"]
        for row in results["시나리오"]:
            if row.get("건너뜀"):
                lines.append(f"| {row['키']} | {row['제목']} | — | — | — |")
                continue
            lines.append(f"| {row['키']} | {row['제목']} | {row['전']['grade']} "
                         f"{row['전']['prob']} | {row['후']['grade']} {row['후']['prob']} | "
                         f"{row['전_1위']} → {row['후_1위']} |")
    return "\n".join(lines) + "\n"


# ---- 4·5. 적용·확인 ---------------------------------------------------------------------------

def command_apply(args) -> int:
    paths = _paths(args.out_dir)
    if _check_frozen(paths, model_may_change=True) is None:
        return EXIT_REFUSED
    results = json.loads(paths["results"].read_text(encoding="utf-8"))
    if not results.get("채택") or results.get("스모크"):
        print("거절: 채택되지 않았거나 스모크 결과입니다 — 적용하지 않습니다", file=sys.stderr)
        return EXIT_REFUSED
    if NEW_MODEL_PATH.exists() and not args.force:
        print(f"거절: {NEW_MODEL_PATH} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    candidate = json.loads(paths["candidate"].read_text(encoding="utf-8"))
    rm.validate_model({**candidate, "version": BASE_VERSION})
    NEW_MODEL_PATH.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    print(f"썼다: {NEW_MODEL_PATH} ({candidate['version']})")
    return 0


def command_verify(args) -> int:
    """기본 모델을 v1.4.3 으로 바꾼 뒤 — 기본 엔진으로 다시 돌려 후 실행과 같은지."""
    paths = _paths(args.out_dir)
    if _check_frozen(paths, model_may_change=True) is None:
        return EXIT_REFUSED
    if rm.MODEL_VERSION != NEW_VERSION or rm.resolve_model_path() != NEW_MODEL_PATH:
        print("거절: 서비스 기본 모델이 v1.4.3 이 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    with gzip.open(paths["searches"], "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    context = ns._context(NEW_MODEL_PATH)
    ms = context["ms"]
    if ms.state.model.get("version") != NEW_VERSION or rm.weak_run_version(ms.state.model) != 2:
        print("거절: 엔진이 적재한 모델이 weak_run 2 인 v1.4.3 이 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    lo.memo_ocr(ms)
    models = {"전": ms.state.model, "후": ms.state.model}
    again = run_searches(context, models, saved["설명적_이름_목록"], None)
    mismatch = Counter()
    checked = 0

    def same(a: dict, b: dict) -> bool:
        return (a["전체"] == b["전체"]
                and [c["id"] for c in a["상위"]] == [c["id"] for c in b["상위"]])

    for key, value in again["재현"].items():
        checked += 1
        mismatch["재현"] += int(not same(value["후"], saved["재현"][key]["후"]))
    for new, old in zip(again["설명적_이름"], saved["설명적_이름"]):
        for label, _ in DESCRIPTIVE_MODES:
            checked += 1
            mismatch["설명적_이름"] += int(not same(new["방식"][label]["후"],
                                                old["방식"][label]["후"]))
    for new, old in zip(again["대조군"], saved["대조군"]):
        for label, _, _ in CONTROL_MODES:
            checked += 1
            mismatch["대조군"] += int(not same(new["방식"][label]["후"], old["방식"][label]["후"]))
    for new, old in zip(again["표본A"], saved["표본A"]):
        checked += 1
        mismatch["표본A"] += int(not same(new["이름+이미지"]["후"], old["이름+이미지"]["후"]))
    default = lo.scenarios(context, {"기본": ms.state.model})["기본"]
    after = saved["시나리오"]["후"]
    scenario_diff = [key for key, item in default.items()
                     if item.get("전체") != after.get(key, {}).get("전체")
                     or [c["id"] for c in item.get("상위", [])]
                     != [c["id"] for c in after.get(key, {}).get("상위", [])]]
    verify = {"모델": ms.state.model["version"], "다시_돌린_질의": checked,
              "불일치": dict(mismatch), "시나리오_다른_것": scenario_diff,
              "통과": not any(mismatch.values()) and not scenario_diff,
              "걸린_시간_s": round(time.perf_counter() - started, 1), "끝": _now()}
    paths["verify"].write_text(json.dumps(verify, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")
    print(json.dumps(verify, ensure_ascii=False))
    return 0 if verify["통과"] else EXIT_STOP


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("freeze", "run", "report", "apply", "verify"))
    parser.add_argument("--out-dir", type=Path, default=TRIALS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--smoke", action="store_true",
                        help="시험 실행 — 설명적 이름·대조군·표본 A 4건씩(--out-dir 를 따로)")
    args = parser.parse_args(argv)
    if args.smoke and args.out_dir.resolve() == TRIALS.resolve():
        print("거절: --smoke 는 --out-dir 를 따로 주세요", file=sys.stderr)
        return EXIT_REFUSED
    return {"freeze": command_freeze, "run": command_run, "report": command_report,
            "apply": command_apply, "verify": command_verify}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
