"""이름 없는 '이미지+업종' 판단에 로고 유사도 × 업종 겹침의 곱하기 항을 넣어 다시 학습한다
(2026-11-24, 지시로 고정). 더하기 구조(로짓 = 절편 + 이미지 + 업종)는 "로고가 닮았고 그리고 업종이
같다"를 표현하지 못해, 업종이 로고와 상관없이 위험도를 올리거나(v1.4.3) 같은 업종 음성을 넣으면
업종이 아예 빠졌다(통합 모델 설계 §7-11). 변형 L(선형 곱)·H(꺾인 곱)를 v1.4 절차로 학습하고 같은
조건으로 잰다. KIPRIS 호출 0.

    ml/venv/bin/python ml/scripts/goods_product.py freeze   # 0. 규칙·입력 해시(꺾인 곱의 c 포함)
    ml/venv/bin/python ml/scripts/goods_product.py run      # 1. 학습 → 기준 → 검색 → ①–⑦ → 판정
    ml/venv/bin/python ml/scripts/goods_product.py apply    # 2. 고른 변형만 v1.4.5 JSON
    ml/venv/bin/python ml/scripts/goods_product.py verify   # 3. 기본 모델 바꾼 뒤

전·후 = 같은 프로세스에서 엔진 계수만 v1.4.3 ↔ 변형. 산출(비공개):
ml/data/trials/goods_product_{rule,results,candidate_L,candidate_H,verify}.json·_searches.json.gz·
_report.md. 고정본과 다르면 거절(종료 코드 4), 검산 불일치·둘 다 미달이면 3.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
for _root in (ML_ROOT, REPO_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from scipy.special import expit  # noqa: E402
from src.model import risk_model as rm  # noqa: E402

from scripts import goods_shortcut as gs  # noqa: E402
from scripts import logo_floor_image_only as lo  # noqa: E402
from scripts import named_search_thresholds as first  # noqa: E402
from scripts import nameless_shared_threshold as ns  # noqa: E402

TRIALS = ML_ROOT / "data" / "trials"
STEM = "goods_product"
EXIT_STOP = 3
EXIT_REFUSED = 4
CAUTION, REVIEW, RISK = "주의", "검토 권장", "위험"
X, XG = ns.X, ns.XG
X_KEY, XG_KEY = gs.X_KEY, gs.XG_KEY
VARIANTS = ("L", "H")
SEED = 0
REPEAT = ns.REPEAT  # 10
TARGETS = {REVIEW: 0.10, RISK: 0.02}
TOLERANCE = ns.TOLERANCE  # 0.0224
SAME_LOGO_MIN = ns.SAME_LOGO_MIN  # 0.95
CITED_RATIO_MIN = ns.CITED_RATIO_MIN  # 0.5
PRECISION_MIN, PRECISION_MIN_ROWS = gs.PRECISION_MIN, gs.PRECISION_MIN_ROWS  # 0.70, 10
AUC_DROP_MAX = 0.05
GRID_STEP = 0.002
PROBE_IMAGES = (0.3, 0.5, 0.7, 0.9)
HINGE_C = {"문자계": 0.6419, "도형계": 0.5579}  # 이미지만 집합(v1.4.3)이 주의 0.3677 이 되는 유사도
PRODUCT_PRIOR_MU = 0.0
BASE_VERSION = "risk_model_v1.4.3"
NEW_VERSION = "risk_model_v1.4.5"
BASE_MODEL_PATH = REPO_ROOT / "shared" / "model" / "risk_model_v1.4.3.json"
NEW_MODEL_PATH = REPO_ROOT / "shared" / "model" / "risk_model_v1.4.5.json"
EASY_AUGMENTED = TRIALS / "goods_shortcut_easy_augmented.csv"  # 지난 시도의 같은 업종 음성 449 포함
EASY_AUGMENTED_SHA = "6cd1a8ce02fa6565b7e476209ddcc9aae0ce25eeca77b5152398e29a6a184270"
SAVED_SCENARIOS = gs.SAVED_SCENARIOS
CONTROL_MODES = gs.CONTROL_MODES
NAMED_GOODS_MODE = gs.NAMED_GOODS_MODE
DISPLAY_TOP = first.DISPLAY_TOP
LEVELS = ("도형", "문자")

# 규칙(이 지시로 고정 — 실행 전에 해시를 남기고 결과를 보고 바꾸지 않는다) ------------------------
RULE = {
    "구조": (
        "바꾸는 것은 이름 없는 이미지+업종 집합(noname:x2_whole+x4) 하나. 지금(v1.4.3) 로짓 = "
        "절편 + b·x2 + d·x2·도형계 + c·x4 — 유형 묶음(문자계: 문자·결합-문자요부·미상, 도형계: "
        "도형·결합-도형요부)은 ×도형계 항 하나로 갈린다. 변형 L(선형 곱): 이미지 "
        "항(x2_whole·x2_whole×도형계)마다 x4 를 곱한 항 x2_whole×x4·x2_whole×도형계×x4 를 "
        "더한다. 변형 H(꺾인 곱): 이미지 항 대신 h = max(0, x2_whole − c_묶음)에 x4 를 곱한 항 "
        "h×x4·h×도형계×x4(항 이름 hinge(x2_whole;c문자계;c도형계)×x4·…×도형계×x4)를 더한다 — c "
        "는 유형 묶음별로 이미지만 집합(v1.4.3)의 위험도가 이미지만 주의 기준(0.3677)이 되는 "
        "이미지 유사도(넷째 자리 반올림 — 문자계 0.6419·도형계 0.5579; 0–1 밖이면 1 = 곱하기 항 "
        "없음), 학습 전에 계산해 설정에 고정."),
    "제약": (
        "(a) 곱하기 항 계수마다 ≥ 0, 업종 단독(x4) ≥ 0 (b) x4 = 0 에서 이미지+업종 로짓 ≤ "
        "이미지만 로짓 — x4 = 0 이면 곱하기 항이 사라져 이미지 유사도에 선형이라 꼭짓점 x2 ∈ {0, "
        "1} × 유형 {문자, 도형} 4곳에 걸면 모든 이미지 유사도에서 성립 (c) v1.4 "
        "단조(tr.monotone_constraints — x2 ≥ 0·x2 + ×도형계 ≥ 0·x4 ≥ 0). 같은 이름 제약(v1.4 — "
        "같은 이름을 더한 이름 있는 이미지+업종 로짓 ≥ 이름 없는 로짓, 꼭짓점 x2·x4 ∈ {0, 1} × "
        "유형 × 요부 둘 다)은 빼라는 지시가 없어 그대로 둔다(곱하기 항은 x2·x4 에 다중선형, 꺾인 "
        "곱은 x2 에 볼록이라 꼭짓점으로 충분). 위험도 수준의 결합 제약(이미지만 → 이미지+업종, "
        "x4 = 0.0252 에서 이상)은 뺀다 — 업종이 겹칠 때 이미지만 등급 아래로 내려가지 않는 것은 "
        "엔진의 업종 하한(goods_floor)이 맡는다. 그 집합에 goods_rule 'no_raise_without_overlap' "
        "를 적어 런타임 적재 검증이 결합 하한 대신 (b) 를 본다. (b) 는 지시대로 겹침 0 에서만 "
        "건다 — 0 < 겹침 < 결합 하한(0.0252)에서 이미지만보다 높아지지 않는지는 제약이 아니라 "
        "채택_5 (다)가 잰다(그 구간에서 넘으면 미달)."),
    "학습": (
        "v1.4 2차 학습 절차: t4.load_dataset(학습 특징, 늘린 쉬운 음성 = 지난 시도(§7-11)의 "
        "goods_shortcut_easy_augmented.csv — 지금 쉬운 음성 700 + 같은 업종 음성 449 를 다시 "
        "뽑지 않고 그대로, sha256 6cd1a8ce…·앞부분 = 지금 쉬운 음성 바이트)(사진 규칙·사건 가중 "
        "상한 3·쉬운 음성 가중 0.5·묶음), t4.Design(v1.4)의 이미지+업종 집합에 변형의 곱하기 "
        "항을 더한 설계(런타임 rm.design_vector 로 계산 — 서비스와 같은 식), 이름 있는 4벌(v1.3 "
        "JSON)·noname:x2_whole(v1.4.3 계수) 고정, 사전분포 σ 1.0(기존 항은 v1.4 의 μ, 곱하기 "
        "항은 μ 0 — 판례 μ 가 없어 0), 교차검증 5겹 × 3반복(tr.folds_for(y, 묶음, seed 0 + 반복) "
        "— v1.4 와 같은 겹 만드는 법), 전체 적합 t4.fit_joint. 도형계로 본 OOF 는 각 행을 유형 "
        "도형으로 다시 계산한 설계(꺾인 곱은 도형계 c). 반올림 넷째 자리(음수가 된 단조 항은 0, "
        "x2 + ×도형계 < 0 이면 ×도형계를 0.0001 올림), 반올림이 만든 적재 결합 위반((b)·같은 "
        "이름 — 둘 다 이미지+업종 쪽이 높아서 생김)은 그 집합의 절편만 0.0001 씩 내려 고친다. "
        "검산: 지금 교차검증 재현(t2.train_once, 학습 특징 + 지금 쉬운 음성)의 반올림 계수 = "
        "v1.4.3 의 이름 없는 두 집합(다르면 멈춤)."),
    "진단": (
        "변형마다(판정에 안 씀): 계수, 이미지+업종 학습 행 중 심결 행의 OOF AUC(도형계로 본 "
        "값·사건 가중·행의 유형), 대조군 이미지+업종 질의의 무관한 후보에서 같은 업종(겹침 ≥ "
        "0.5) 대 다른 업종(< 0.0252) 위험도 평균·중앙과 그 차(이미지 구간별로도), 이미지 유사도 "
        "0.3·0.5·0.7·0.9 × 겹침 0·1 의 이미지+업종 위험도(유형 도형·문자)와 같은 이미지의 "
        "이미지만 위험도."),
    "기준": (
        "변형의 이미지+업종 기준은 이미지만 기준(주의 0.3677·검토 권장 0.491·위험 0.5724)에서 "
        "시작한다. 대조군 기준용(§7-8·§7-11 과 같은 대조군 — 1차 시도 대조군 이미지 기준용 46 × "
        "업종 세트 10, nameless_shared_threshold.control_queries, 무관한 후보 = 인용상표·같은 "
        "출원인 뺌) 의 질의 단위 M_q(무관한 후보 중 변형 계수의 이미지+업종 위험도 최댓값, 유형 "
        "도형, 업종 하한 전 — set_prob)로 그 기준 이상인 질의 비율이 목표(검토 권장 10%·위험 "
        "2%)를 넘는 등급만 fit_cut(목표) 값으로 올린다(이미지만 기준보다 낮추지 않음, 주의는 "
        "그대로). 업종 하한·사진 규칙·logo_floor·이름 있는 판단은 그대로."),
    "채택_1": (
        "(가) 대조군 확인용 460질의의 변형 M_q 로 변형 기준 이상인 질의 비율: 검토 권장 ≤ "
        "10%·위험 ≤ 2% — 넘으면 확인용에 같은 fit_cut 으로 맞춘 값 − 변형 기준 ≤ 0.0224 일 때만 "
        "통과 (나) 1차 시도 대조군 확인용 100(지어낸 이름)의 이름+이미지+업종에서 엔진 전체 "
        "등급(정렬 앞 5건의 최고 표시 등급) 검토 권장 이상 비율: 변형 ≤ 지금(v1.4.3, 같은 "
        "실행에서 다시 잰 값)."),
    "채택_2": (
        "같은 로고 200(1차 시도 logo_floor_named 양성 — 이미지·유사군·인정 상표)을 이름 없이 "
        "업종 없음·같은 업종(그 양성의 유사군) 두 방식으로: 엔진 정렬 1위가 인정 상표이고 그 "
        "표시 등급이 검토 권장 이상인 비율이 방식마다 ≥ 95%."),
    "채택_3": (
        "표본 A 인용상표 — §7-8 채택_4·§7-11 채택_3 과 같은 쌍(표본 A 사건의 심결 행 중 이미지 "
        "축(원래 값, 사진 규칙 전)이 있는 행)을 서비스 채점식의 이름 없는 판단(이름 없는 계수, "
        "유형 도형, 그 행의 이미지·상품 축, 업종 하한·도형 규칙)으로 매긴 검토 권장 이상 비율: "
        "변형 ≥ 지금 × 0.5."),
    "채택_4": (
        "이름 없는 판단의 위험 정밀도(심결 쌍, OOF) — §7-8 채택_3 의 판정식(이미지 축이 있는 "
        "심결 행 — 사진 규칙 뒤 —, 상품 축이 있으면 이미지+업종 OOF 등급(겹침 ≥ 0.0252 면 "
        "이미지만 OOF 등급과 견줘 높은 쪽), 없으면 이미지만 OOF 등급, 이미지 ≥ 0.9 면 도형 "
        "규칙(검토 권장 이상); OOF 는 도형계로 본 값). 이미지+업종 OOF 는 변형의 교차검증·변형 "
        "기준, 이미지만 OOF 는 지금 교차검증·지금 기준. 위험 행 ≥ 10 이면 그 유사 비율(가중 "
        "없음) ≥ 0.70, 10 미만이면 판정에 쓰지 않고 보고만."),
    "채택_5": (
        "(가) 모든 이름 없는 집합의 주의 < 검토 권장 < 위험 (나) 단조 위반 "
        "0(rm.monotone_violations — 모든 계수 집합, 곱하기 항 ≥ 0 포함)·적재 결합 검증 위반 "
        "0(rm.coupling_violations — (b)·같은 이름) (다) 업종 겹침 ≥ 결합 하한 0.0252 인 후보는 "
        "서비스 최종 등급(업종 하한·도형 규칙 — first.nameless_final_grade) ≥ 이미지만 등급, < "
        "0.0252 인 후보는 이미지+업종 등급(도형 규칙 포함, 업종 하한은 걸리지 않음) ≤ 이미지만 "
        "등급: 격자(x2·x4 0–1, 0.002 간격, 유형 도형·문자) + 대조군 실제 쌍(같은 이미지의 "
        "이미지만·이미지+업종 질의에 모두 나온 후보) + 표본 A 업종 있는 108질의(이름 없이)의 "
        "후보 풀 전부."),
    "채택_6": (
        "표본 A 중 질의 업종이 있는 108질의를 이름 없이 이미지+업종으로(엔진 search_pool): 상위 "
        "5 의 무관하고(인용상표·같은 출원인 아님 — 1차 시도 a_relations·unrelated_filter) 업종이 "
        "다른(겹침 < 0.0252) 후보 중 변형 등급이 위험인데 그 후보의 이미지만 등급(이미지 "
        "유사도로 본 이미지만 판단, 유형 도형, 도형 규칙)이 위험이 아닌 경우 0. 전체 등급이 "
        "위험인 질의 수는 지금과 함께 보고만."),
    "채택_7": (
        "이미지+업종 학습 행 중 심결 행의 OOF AUC(도형계로 본 값, 가중 없음): 변형 ≥ 지금(같은 "
        "실행의 지금 교차검증 재현) − 0.05."),
    "판정": (
        "변형마다 ①–⑦을 모두 넘으면 통과. 둘 다 통과하면 ③(인용상표 검토 권장 이상 비율)이 높은 "
        "변형, 같으면 L; 하나만 통과하면 그 변형; 둘 다 못 넘으면 적용하지 않고 멈춘다(종료 코드 "
        "3)."),
    "전후": (
        "변형별: 학습 진단, 대조군 등급 분포(기준용·확인용 × 이미지만·이미지+업종), 같은 로고, "
        "표본 A 인용상표·무관 후보(⑥), 이름 있는 질의(지어낸 이름 대조군 확인용 100 × 네 방식, "
        "표본 A 검색 184), 시나리오 16종(named_shared_threshold.SCENARIOS). 지금 = v1.4.3 을 "
        "같은 프로세스에서 같은 방법으로 다시 잰 값. 검산: 바꾸기 전 시나리오 16종 = v1.4.3 확인 "
        "실행 저장값(다르면 멈춤)."),
    "적용": (
        "고른 변형만 shared/model/risk_model_v1.4.5.json = v1.4.3 JSON 에서 "
        "nameless_patterns['x2_whole+x4'] 를 그 변형의 "
        "features·coefficients·intercept·grade_thresholds·goods_rule·meta 로, version "
        "risk_model_v1.4.5, meta.nameless.goods_product(출처). verify 가 기본 엔진으로 대조군 "
        "확인용·같은 로고·이름 있는 질의·표본 A 업종 있는 108(이름 없이)·시나리오를 다시 돌려 "
        "후보 실행과 같은지 본다."),
}


def _settings() -> dict:
    return {"RULE": RULE, "VARIANTS": VARIANTS, "SEED": SEED, "REPEAT": REPEAT, "TARGETS": TARGETS,
            "TOLERANCE": TOLERANCE, "SAME_LOGO_MIN": SAME_LOGO_MIN,
            "CITED_RATIO_MIN": CITED_RATIO_MIN, "PRECISION_MIN": PRECISION_MIN,
            "PRECISION_MIN_ROWS": PRECISION_MIN_ROWS, "AUC_DROP_MAX": AUC_DROP_MAX,
            "GRID_STEP": GRID_STEP, "PROBE_IMAGES": PROBE_IMAGES, "HINGE_C": HINGE_C,
            "PRODUCT_PRIOR_MU": PRODUCT_PRIOR_MU, "BASE_VERSION": BASE_VERSION,
            "NEW_VERSION": NEW_VERSION, "EASY_AUGMENTED_SHA": EASY_AUGMENTED_SHA,
            "CONTROL_SHA": ns.CONTROL_SHA, "CONTROL_MODES": CONTROL_MODES,
            "DISPLAY_TOP": DISPLAY_TOP, "LEVELS": LEVELS}


def rule_sha256() -> str:
    return first.canonical_sha256(_settings())


def _inputs() -> dict[str, Path]:
    inputs = gs._inputs()  # noqa: SLF001 — 지난 시도와 같은 입력(+ 늘린 쉬운 음성·이 시도의 런타임)
    inputs.update({"늘린_쉬운_음성": EASY_AUGMENTED,
                   "지난_시도_스크립트": ML_ROOT / "scripts" / "goods_shortcut.py"})
    return inputs


def _paths(out_dir: Path) -> dict[str, Path]:
    return {"rule": out_dir / f"{STEM}_rule.json", "results": out_dir / f"{STEM}_results.json",
            "report": out_dir / f"{STEM}_report.md",
            **{f"candidate_{v}": out_dir / f"{STEM}_candidate_{v}.json" for v in VARIANTS},
            "searches": out_dir / f"{STEM}_searches.json.gz",
            "verify": out_dir / f"{STEM}_verify.json"}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _round(value, digits: int = 4):
    return None if value is None else round(float(value), digits)


# ---- 순수 함수(시험 대상) ----------------------------------------------------------------------

def hinge_points(model: dict) -> dict[str, float]:
    """유형 묶음별 c — 이미지만 집합의 위험도가 그 집합의 주의 기준이 되는 이미지 유사도
    (0–1 밖이면 1)."""
    block = model[rm.NAMELESS_KEY][X_KEY]
    caution = float(rm.grade_thresholds_for(model, X)[CAUTION])
    target = math.log(caution / (1.0 - caution))
    slope = float(block["coefficients"]["x2_whole"])
    figure = slope + float(block["coefficients"].get("x2_whole×도형계", 0.0))
    out = {}
    for family, value in (("문자계", slope), ("도형계", figure)):
        point = (target - float(block["intercept"])) / value if value > 0 else math.inf
        out[family] = round(point, 4) if 0.0 <= point <= 1.0 else 1.0
    return out


def product_names(variant: str, hinge: dict[str, float] = HINGE_C) -> list[str]:
    if variant == "L":
        return list(rm.PRODUCT_TERMS)
    if variant == "H":
        return [rm.hinge_term_name(hinge["문자계"], hinge["도형계"]),
                rm.hinge_term_name(hinge["문자계"], hinge["도형계"], figure=True)]
    raise ValueError(f"모르는 변형: {variant}")


def start_thresholds(values: list[float], image_only: dict) -> dict:
    """규칙 '기준' — 이미지만 기준에서 시작, 목표를 넘는 등급만 fit_cut 으로 올린다."""
    out = {CAUTION: float(image_only[CAUTION])}
    detail = {}
    for grade, share in TARGETS.items():
        start = float(image_only[grade])
        rate = ns.rate_at_least(values, start)
        fitted, k, n = first.fit_cut(values, share)
        raise_ = rate is not None and rate > share + 1e-12
        out[grade] = round(max(start, fitted), 4) if raise_ and fitted is not None else start
        detail[grade] = {"시작": start, "기준용_비율(시작)": rate, "fit_cut": fitted, "k": k,
                         "n": n, "올림": raise_}
    return {"기준": out, "자세히": detail}


def choose(passed: dict[str, bool], cited: dict[str, float | None]) -> str | None:
    """규칙 '판정'."""
    ok = [v for v in VARIANTS if passed.get(v)]
    if not ok:
        return None
    if len(ok) == 1:
        return ok[0]
    return max(ok, key=lambda v: (cited.get(v) or 0.0, v == "L"))


def round_block(names: list[str], coef: np.ndarray, intercept: float, digits: int = 4) -> dict:
    """넷째 자리 반올림 — 음수가 된 단조 항(x2_whole·x4·곱하기 항)은 0, x2 + ×도형계 < 0 이면
    ×도형계를 올림."""
    values = {name: round(float(value), digits) + 0.0 for name, value in zip(names, coef)}
    for name in names:
        if (name in ("x2_whole", "x4") or rm.is_product_term(name)) and values[name] < 0:
            values[name] = 0.0
    if "x2_whole×도형계" in values:
        while values["x2_whole"] + values["x2_whole×도형계"] < 0:
            values["x2_whole×도형계"] = round(values["x2_whole×도형계"] + 10.0 ** -digits, digits)
    return {"features": list(names), "coefficients": values,
            "intercept": round(float(intercept), digits)}


def with_block(base: dict, entry: dict, *, thresholds: dict | None = None,
               meta: dict | None = None) -> dict:
    """base 의 이름 없는 이미지+업종 집합을 entry(features·coefficients·intercept)로 —
    goods_rule 포함."""
    out = copy.deepcopy(base)
    block = out[rm.NAMELESS_KEY][XG_KEY]
    block["features"] = list(entry["features"])
    block["coefficients"] = dict(entry["coefficients"])
    block["intercept"] = float(entry["intercept"])
    block[rm.GOODS_RULE_KEY] = rm.GOODS_RULE_NO_RAISE
    if thresholds is not None:
        block["grade_thresholds"] = {g: float(thresholds[g]) for g in rm.GRADE_THRESHOLD_KEYS}
    if meta is not None:
        block["meta"] = meta
    return out


def repair_intercept(model: dict, *, digits: int = 4, limit: int = 10_000) -> tuple[dict, dict]:
    """반올림이 만든 적재 결합 위반(이미지+업종 쪽이 높음)을 그 집합의 절편만 내려 고친다."""
    out = copy.deepcopy(model)
    block = out[rm.NAMELESS_KEY][XG_KEY]
    steps = 0
    for _ in range(limit):
        violations = rm.coupling_violations(out)
        if not violations:
            break
        if not all(v.startswith(f"{XG} ") for v in violations):
            return out, {"걸음": steps, "고침": False, "남은_위반": violations[:5]}
        block["intercept"] = round(block["intercept"] - 10.0 ** -digits, digits)
        steps += 1
    remaining = rm.coupling_violations(out)
    return out, {"걸음": steps, "고침": not remaining, "남은_위반": remaining[:5]}


def level_features(x2: float, x4: float | None, level: str) -> dict:
    return {**ns.nameless_features(float(x2), x4), "mark_type": level}


def grade_pair(x2: float, x4: float | None, model: dict, base: dict, level: str = "도형"
               ) -> tuple[str, str]:
    """(이미지+업종 판단의 서비스 최종 등급, 같은 이미지의 이미지만 등급)."""
    final = first.nameless_final_grade(level_features(x2, x4, level), model)
    alone = first.nameless_final_grade(level_features(x2, None, level), base)
    return final, alone


def direction_violation(x2: float, x4: float, model: dict, base: dict, level: str = "도형") -> bool:
    """채택_5 (다) — 겹침 ≥ 하한이면 최종 ≥ 이미지만, < 하한이면 이미지+업종 ≤ 이미지만."""
    floor = float(model["coupling"]["floors"]["x4"])
    final, alone = grade_pair(x2, x4, model, base, level)
    if x4 >= floor:
        return rm.GRADES.index(final) < rm.GRADES.index(alone)
    return rm.GRADES.index(final) > rm.GRADES.index(alone)


def grid_check(model: dict, base: dict, step: float = GRID_STEP) -> dict:
    """채택_5 (다) 격자 — direction_violation 과 같은 판정(이미지만 등급은 이미지 유사도마다
    한 번)."""
    values = [float(v) for v in np.round(np.arange(0.0, 1.0 + 1e-9, step), 6)]
    floor = float(model["coupling"]["floors"]["x4"])
    out = {}
    for level in LEVELS:
        bad: Counter = Counter()
        examples: list[dict] = []
        for x2 in values:
            alone = rm.GRADES.index(first.nameless_final_grade(level_features(x2, None, level),
                                                               base))
            for x4 in values:
                final = rm.GRADES.index(first.nameless_final_grade(
                    level_features(x2, x4, level), model))
                if (final < alone) if x4 >= floor else (final > alone):
                    kind = "하한_이상" if x4 >= floor else "하한_아래"
                    bad[kind] += 1
                    if len(examples) < 5:
                        examples.append({"x2": x2, "x4": x4, "구간": kind})
        out[level] = {"점": len(values) ** 2, "어김": dict(bad), "예": examples}
    return out


def probe_table(model: dict, base: dict) -> dict:
    """진단 — 이미지 0.3·0.5·0.7·0.9 × 겹침 0·1 의 이미지+업종 위험도와 같은 이미지의 이미지만
    위험도."""
    out = {}
    for level in LEVELS:
        rows = {}
        for x2 in PROBE_IMAGES:
            rows[str(x2)] = {
                "겹침 0": _round(rm.risk_score(level_features(x2, 0.0, level), model).prob),
                "겹침 1": _round(rm.risk_score(level_features(x2, 1.0, level), model).prob),
                "이미지만": _round(rm.risk_score(level_features(x2, None, level), base).prob)}
        out[level] = rows
    return out


def check_named(rows: list[dict], label: str) -> dict:
    def rate(name: str) -> float | None:
        flags = [ns.at_least(row["방식"][NAMED_GOODS_MODE][name]["전체"], REVIEW) for row in rows]
        return sum(flags) / len(flags) if flags else None

    now, new = rate("지금"), rate(label)
    return {"질의": len(rows), "지금": now, "변형": new,
            "통과": now is not None and new is not None and new <= now + 1e-12}


# ---- 0. 고정 -----------------------------------------------------------------------------------

def command_freeze(args) -> int:
    paths = _paths(args.out_dir)
    if paths["rule"].exists() and not args.force:
        print(f"거절: {paths['rule']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    base = rm.validate_model(json.loads(BASE_MODEL_PATH.read_text(encoding="utf-8")))
    if hinge_points(base) != HINGE_C:
        print(f"거절: 꺾인 곱의 c 가 설정과 다릅니다 — {hinge_points(base)}", file=sys.stderr)
        return EXIT_REFUSED
    if first.file_sha256(EASY_AUGMENTED) != EASY_AUGMENTED_SHA:
        print("거절: 늘린 쉬운 음성 파일이 지난 시도의 것과 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    args.out_dir.mkdir(parents=True, exist_ok=True)
    frozen = {"설정_sha256": rule_sha256(), "스크립트_sha256": first.file_sha256(Path(__file__)),
              "입력_sha256": {k: first.file_sha256(p) for k, p in _inputs().items()},
              "고정": _now(), "설정": _settings()}
    paths["rule"].write_text(json.dumps(frozen, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    print(f"설정 sha256 {frozen['설정_sha256']} · 스크립트 sha256 {frozen['스크립트_sha256']} · "
          f"c {HINGE_C}")
    return 0


def _check_frozen(paths: dict, *, model_may_change: bool = False) -> dict | None:
    if not paths["rule"].exists():
        print("거절: 먼저 freeze", file=sys.stderr)
        return None
    frozen = json.loads(paths["rule"].read_text(encoding="utf-8"))
    if frozen["설정_sha256"] != rule_sha256():
        print("거절: 설정이 고정본과 다릅니다", file=sys.stderr)
        return None
    skip = {"런타임"} if model_may_change else set()
    changed = [k for k, p in _inputs().items()
               if k not in skip and first.file_sha256(p) != frozen["입력_sha256"].get(k)]
    if changed:
        print(f"거절: 입력이 고정 때와 다릅니다 — {changed}", file=sys.stderr)
        return None
    return frozen


# ---- 1. 학습 ----------------------------------------------------------------------------------

def extend_design(design, rows: list[dict], names: list[str]):
    """t4.Design 의 이미지+업종 집합에 곱하기 항을 더한다(설계는 rm.design_vector — 서비스와
    같은 식) → (design, 도형계로 본 그 집합의 설계 행렬)."""
    from scripts import train_risk_model_v14 as t4

    full = list(t4.nameless_features(XG_KEY)) + list(names)
    if list(design.names[XG]) != full[:len(design.names[XG])]:
        raise ValueError("이미지+업종 집합의 기존 항이 v1.4 설계와 다릅니다")
    features = [t4.service_features(row) for row in rows]
    old_x = design.X[XG]
    design.names[XG] = full
    design.X[XG] = np.asarray([rm.design_vector(f, full) for f in features], dtype=np.float64)
    figure = np.asarray([rm.design_vector({**f, "mark_type": "도형"}, full) for f in features],
                        dtype=np.float64)
    width = old_x.shape[1]
    old_figure = old_x.copy()  # t2.figure_logit 과 같은 변환(×도형계 열에 이미지 값)
    old_figure[:, full.index("x2_whole×도형계")] = old_x[:, full.index("x2_whole")]
    if not (np.array_equal(design.X[XG][:, :width], old_x)
            and np.array_equal(figure[:, :width], old_figure)):
        raise ValueError("곱하기 항을 더한 설계 행렬의 기존 열이 v1.4 설계와 다릅니다")
    design.offset, design.size = {}, 0
    for block in design.ids:
        design.offset[block] = design.size
        design.size += len(design.names[block]) + 1
    return design, figure


def constraints_for(design, products: list[str]) -> list:
    """규칙 '제약' — 이미지+업종 집합의 (c) 단조·(a) 곱하기 항 ≥ 0·(b) x4 = 0 → 이미지만 이하·같은
    이름(이미지만 집합과 이름 있는 4벌은 고정이라 상수항)."""
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4
    from scripts import train_risk_model_v14_nameless as t2

    names = design.names[XG]
    start = design.offset[XG]
    out = []
    for g in tr.monotone_constraints(names):
        row = np.zeros(design.size)
        row[start:start + len(g)] = g
        out.append(t4.Constraint("단조", " + ".join(n for n, v in zip(names, g) if v) + " ≥ 0",
                                 row))
    for name in products:
        row = np.zeros(design.size)
        row[start + names.index(name)] = 1.0
        out.append(t4.Constraint("(a) 곱하기 항", f"{name} ≥ 0", row))
    for vertex in rm.nameless_vertices(design.names[X]):
        out.append(t4.Constraint(
            "(b) 업종 0 → 이미지만 이하", f"{t4._vertex_label(vertex)}",  # noqa: SLF001
            t4._difference(design, X, vertex, XG, {**vertex, "x4": 0.0})))  # noqa: SLF001
    for vertex in rm.nameless_vertices(names):
        for distinctive in (True, False):
            upper = rm.same_name_input(vertex, t2.SAME_NAME, distinctive=distinctive)
            out.append(t4.Constraint(
                "결합(같은 이름)", f"{t4._vertex_label(vertex)}, 요부없음={not distinctive}",  # noqa: SLF001
                t4._difference(design, XG_KEY, upper, XG, vertex)))  # noqa: SLF001
    return out


def fit_block(design, a: dict, index: np.ndarray, constraints: list, fixed: dict,
              products: list[str]):
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    mu = {**tr.PRIOR_MU, **{name: PRODUCT_PRIOR_MU for name in products}}
    return t4.fit_joint(design, a["y"], a["fit_weight"], index, constraints, fixed=fixed, mu=mu)


def cv_block(design, a: dict, constraints: list, fixed: dict, products: list[str],
             figure: np.ndarray, *, folds: int, repeats: int, seed: int) -> dict:
    """v1.4 와 같은 겹 — 이미지+업종 집합의 OOF(행의 유형·도형계로 본 값, 반복 평균)."""
    from scripts import train_risk_model as tr

    own = np.zeros(a["y"].size)
    fig = np.zeros(a["y"].size)
    success, slack = [], []
    for repeat in range(repeats):
        for train, test in tr.folds_for(a["y"], a["groups"], folds=folds, seed=seed + repeat):
            result = fit_block(design, a, train, constraints, fixed, products)
            success.append(result.success)
            slack.append(result.min_slack)
            coef, intercept = result.blocks[XG]
            own[test] += expit(design.X[XG][test] @ coef + intercept)
            fig[test] += expit(figure[test] @ coef + intercept)
    return {"own": own / repeats, "figure": fig / repeats, "겹_수": len(success),
            "수렴_실패": int(len(success) - sum(success)),
            "최소_여유": _round(min(slack), 9) if slack else None}


def train_variant(variant: str, v13: dict, base: dict) -> dict:
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4
    from scripts import train_risk_model_v14_nameless as t2

    dataset = t4.load_dataset(tr.DEFAULT_FEATURES, EASY_AUGMENTED)
    rows = dataset.rows
    a = t4.arrays(rows)
    keys, choice = t4.choose_nameless_keys(rows, a, tr.MIN_PATTERN_MINORITY)
    if tuple(keys) != tuple(t4.NAMELESS_KEYS):
        raise ValueError(f"이름 없는 집합 구성이 다릅니다: {choice}")
    products = product_names(variant)
    design = t4.Design(rows, structure="v1.4", nameless_keys=keys)
    design, figure = extend_design(design, rows, products)
    fixed = t2.fixed_named(design, v13)
    block = base[rm.NAMELESS_KEY][X_KEY]
    fixed[X] = (np.asarray([float(block["coefficients"][n]) for n in design.names[X]]),
                float(block["intercept"]))
    constraints = constraints_for(design, products)
    started = time.perf_counter()
    cv = cv_block(design, a, constraints, fixed, products, figure, folds=t4.FOLDS,
                  repeats=t4.REPEATS, seed=SEED)
    final = fit_block(design, a, np.arange(len(rows)), constraints, fixed, products)
    coef, intercept = final.blocks[XG]
    entry = round_block(design.names[XG], coef, intercept)
    counts = t4.block_counts(design, a["y"], a["fit_weight"], a["easy"])[XG]
    kinds = Counter(c.kind for c in constraints)
    return {"variant": variant, "rows": rows, "arrays": a, "design": design, "figure": figure,
            "cv": cv, "final": final, "entry": entry, "counts": counts,
            "summary": {k: dataset.summary.get(k) for k in ("쉬운_음성", "심결_행(학습)")},
            "constraints": dict(kinds), "seconds": round(time.perf_counter() - started, 1),
            "optimizer": {"solver": final.solver, "success": bool(final.success),
                          "kkt_residual": _round(final.kkt_residual, 9),
                          "min_slack": _round(final.min_slack, 9),
                          "cv_수렴_실패": cv["수렴_실패"], "cv_최소_여유": cv["최소_여유"]}}


def oof_auc(before: dict, result: dict | None) -> dict:
    """진단·채택_7 — 이미지+업종 학습 행 중 심결 행의 OOF AUC."""
    from scripts import train_risk_model_v14 as t4

    if result is None:
        design, a, cv = before["design"], before["arrays"], before["cv"]
        own, fig = cv["per_block"][XG], cv["per_block_figure"][XG]
    else:
        design, a = result["design"], result["arrays"]
        own, fig = result["cv"]["own"], result["cv"]["figure"]
    index = np.flatnonzero(a["trial"] & design.mask[XG])
    y, w = a["y"][index], a["eval_weight"][index]
    ones = np.ones(index.size)
    return {"행": int(index.size), "유사": int(y.sum()),
            "AUC(도형계)": _round(t4.weighted_auc(fig[index], y, ones)),
            "AUC(도형계, 사건 가중)": _round(t4.weighted_auc(fig[index], y, w)),
            "AUC(행의 유형)": _round(t4.weighted_auc(own[index], y, ones))}


def oof_precision(before: dict, results: dict, models: dict) -> dict:
    """채택_4 — 이름 없는 판단의 위험 정밀도(OOF, 도형계)."""
    rows_b, design_b, a_b = before["rows"], before["design"], before["arrays"]
    index = np.flatnonzero(a_b["trial"] & design_b.mask[X])
    floor = float(models["지금"]["coupling"]["floors"]["x4"])
    labels = [int(a_b["y"][i]) for i in index]
    out = {"행": int(index.size)}
    for label, model in models.items():
        if label == "지금":
            xg = before["cv"]["per_block_figure"][XG]
        else:
            result = results[label]
            keys = [(r["심판번호"], r.get("상대번호"), r.get("쌍키")) for r in result["rows"]]
            if any(keys[i] != (rows_b[i]["심판번호"], rows_b[i].get("상대번호"),
                               rows_b[i].get("쌍키")) for i in index):
                raise ValueError("지금·변형 학습 행의 심결 행 순서가 다릅니다")
            xg = result["cv"]["figure"]
        tau = (model.get("figure_rule") or {}).get("threshold")
        grades = []
        for i in index:
            alone = rm.grade_for(float(before["cv"]["per_block_figure"][X][i]),
                                 rm.grade_thresholds_for(model, X))
            if design_b.mask[XG][i]:
                grade = rm.grade_for(float(xg[i]), rm.grade_thresholds_for(model, XG))
                if float(rows_b[i]["x4"]) >= floor:
                    grade = max(grade, alone, key=rm.GRADES.index)
            else:
                grade = alone
            if tau is not None and float(rows_b[i]["x2_whole"]) >= float(tau) and not ns.at_least(
                    grade, REVIEW):
                grade = REVIEW
            grades.append(grade)
        out[label] = {"등급": ns.distribution(grades), **gs.precision_check(grades, labels)}
    return out


# ---- 2. 검색 -----------------------------------------------------------------------------------

def nameless_goods(context: dict, models: dict, limit: int | None) -> list[dict]:
    """채택_6·⑤ — 표본 A 업종 있는 질의를 이름 없이 이미지+업종으로: 상위 5 와 후보 풀 전부."""
    ms = context["ms"]
    out = []
    for query in [q for q in context["A"] if q.goods][:limit]:
        cited, owners = first.a_relations(context, query)
        unrelated = first.unrelated_filter(context, owners, cited)
        image = context["service"](query.path.read_bytes())
        row = {"질의": query.key, "인용상표": sorted(cited), "모델": {}}
        for label, model in models.items():
            with ns.using_model(ms, model):
                pooled = ms.search_pool(image=image, goods_codes=sorted(query.goods))
            top = pooled.candidates[:DISPLAY_TOP]
            row["모델"][label] = {
                "전체": ns.overall([c.grade for c in pooled.candidates]),
                "상위": [{"id": c.id, "등급": c.grade, "x2": c.axes["x2_img"], "x4": c.axes["x4"],
                        "인용": c.id in cited, "무관": bool(unrelated(c.id)),
                        "pattern": c.pattern} for c in top]}
            if "풀" not in row:
                row["풀"] = [{"id": c.id, "x2": c.axes["x2_img"], "x4": c.axes["x4"]}
                            for c in pooled.candidates]
        out.append(row)
    return out


def check_6(rows: list[dict], label: str, base: dict) -> dict:
    floor = float(base["coupling"]["floors"]["x4"])
    bad, examples = 0, []
    for row in rows:
        for c in row["모델"][label]["상위"]:
            if c["인용"] or not c["무관"] or c["x2"] is None or c["x4"] is None or c["x4"] >= floor:
                continue
            alone = first.nameless_final_grade(level_features(c["x2"], None, "도형"), base)
            if c["등급"] == RISK and alone != RISK:
                bad += 1
                examples.append({"질의": row["질의"], "후보": c["id"], "x2": c["x2"],
                                 "x4": c["x4"]})
    def risk_queries(name: str) -> int:
        return sum(1 for row in rows if row["모델"][name]["전체"] == RISK)

    return {"질의": len(rows), "어긴_후보": bad, "예": examples[:10],
            "전체_위험_질의": {"지금": risk_queries("지금"), "변형": risk_queries(label)},
            "통과": bad == 0}


def check_5(model: dict, base: dict, queries: list[dict], goods_rows: list[dict]) -> dict:
    thresholds = {key: rm.grade_thresholds_for(model, key) for key in (X, XG)}
    blocks = {"base": model, **(model.get("patterns") or {}),
              **{rm.NAMELESS_PREFIX + k: v for k, v in (model.get(rm.NAMELESS_KEY) or {}).items()}}
    monotone = {key: len(rm.monotone_violations(block["coefficients"]))
                for key, block in blocks.items() if "coefficients" in block}
    coupling = rm.coupling_violations(model)
    real = Counter()
    for item in queries:
        alone_ids = {c["id"] for entry in item["검색"] if entry["방식"] == "이미지만"
                     for c in entry["풀"] if c["x2"] is not None}
        for entry in item["검색"]:
            if entry["방식"] != "이미지+업종":
                continue
            for c in entry["풀"]:
                if c["id"] in alone_ids and c["x2"] is not None and c["x4"] is not None:
                    real["대조군_쌍"] += 1
                    real["대조군_어김"] += int(direction_violation(c["x2"], c["x4"], model, base))
    for row in goods_rows:
        for c in row["풀"]:
            if c["x2"] is not None and c["x4"] is not None:
                real["표본A_후보"] += 1
                real["표본A_어김"] += int(direction_violation(c["x2"], c["x4"], model, base))
    grid = grid_check(model, base)
    ordered = {key: ns.ordered(t) for key, t in thresholds.items()}
    grid_bad = sum(sum(v["어김"].values()) for v in grid.values())
    passed = (all(ordered.values()) and not any(monotone.values()) and not coupling
              and grid_bad == 0 and real["대조군_어김"] == 0 and real["표본A_어김"] == 0)
    return {"순서": ordered, "단조_위반": monotone, "결합_위반": len(coupling),
            "결합_위반_예": coupling[:5], "격자": grid, "실제": dict(real), "통과": passed}


def command_run(args) -> int:  # noqa: C901 — 단계가 많을 뿐 순서대로
    paths = _paths(args.out_dir)
    frozen = _check_frozen(paths)
    if frozen is None:
        return EXIT_REFUSED
    if paths["results"].exists() and not args.force:
        print(f"거절: {paths['results']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    base = rm.validate_model(json.loads(BASE_MODEL_PATH.read_text(encoding="utf-8")))
    v13 = rm.validate_model(json.loads(rm.V13_MODEL_PATH.read_text(encoding="utf-8")))
    limit = 4 if args.smoke else None
    control_limit = 12 if args.smoke else None
    timing: dict[str, float] = {}
    results: dict = {"설정_sha256": frozen["설정_sha256"],
                     "스크립트_sha256(고정 때)": frozen["스크립트_sha256"],
                     "스크립트_sha256(잴 때)": first.file_sha256(Path(__file__)),
                     "모델": BASE_VERSION, "스모크": bool(args.smoke), "c": HINGE_C}

    def tick(name: str, began: float) -> None:
        timing[name] = round(time.perf_counter() - began, 1)
        print(f"  {name} {timing[name]}초", flush=True)

    def stop(reason: str) -> int:
        results.update(채택=None, 멈춤=reason, 시간_s=timing, 끝=_now())
        args.out_dir.mkdir(parents=True, exist_ok=True)
        paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                    encoding="utf-8")
        paths["report"].write_text(report_text(results), encoding="utf-8")
        print(f"멈춤: {reason}", file=sys.stderr)
        return EXIT_STOP

    # 1. 학습(지금 재현 + 변형 둘)
    began = time.perf_counter()
    before = gs.train_before(v13, base)
    results["지금_재현"] = {"재학습_같음": before["재학습_같음"],
                        "집합별": before["재학습_같음_집합별"]}
    if not before["재학습_같음"]:
        return stop("지금 교차검증 재현의 계수가 배포 계수와 다름")
    trained, coefficient_models = {}, {}
    for variant in VARIANTS:
        result = train_variant(variant, v13, base)
        model = with_block(base, result["entry"])
        model, repair = repair_intercept(model)
        result["repair"] = repair
        result["entry"] = {k: model[rm.NAMELESS_KEY][XG_KEY][k]
                           for k in ("features", "coefficients", "intercept")}
        trained[variant] = result
        coefficient_models[variant] = model
        if not repair["고침"]:
            return stop(f"변형 {variant}: 반올림 뒤 결합 위반을 절편으로 고치지 못함")
    old = base[rm.NAMELESS_KEY][XG_KEY]
    results["학습"] = {
        "지금": {"계수": {"features": old["features"], "coefficients": old["coefficients"],
                      "intercept": old["intercept"]}, "OOF_AUC": oof_auc(before, None)},
        **{v: {"계수": trained[v]["entry"], "학습_행": trained[v]["counts"],
               "제약": trained[v]["constraints"], "최적화": trained[v]["optimizer"],
               "반올림_보정": trained[v]["repair"], "걸린_시간_s": trained[v]["seconds"],
               "데이터": trained[v]["summary"],
               "OOF_AUC": oof_auc(before, trained[v])} for v in VARIANTS}}
    tick("학습", began)

    # 2. 엔진·검산
    began = time.perf_counter()
    context = ns._context(BASE_MODEL_PATH)  # noqa: SLF001
    ms = context["ms"]
    if ms.state.model.get("version") != BASE_VERSION:
        return stop("엔진이 적재한 모델이 v1.4.3 이 아님")
    lo.memo_ocr(ms)
    scenario_runs = lo.scenarios(context, {"지금": ms.state.model})
    results["검산_시나리오"] = gs.scenario_fidelity(scenario_runs["지금"])
    tick("엔진·검산", began)
    if not results["검산_시나리오"]["같음"]:
        return stop("바꾸기 전 시나리오가 저장값과 다름")

    # 3. 대조군(지금) → 변형마다 M_q → 기준 → 후보
    began = time.perf_counter()
    control_record = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    queries = ns.control_queries(control_record["대조군"], control_limit, REPEAT)
    ns.run_control(context, queries, {"지금": ms.state.model})
    tick("대조군(지금)", began)
    image_only = rm.grade_thresholds_for(base, X)
    candidates, found_by = {}, {}
    results["기준"] = {}
    for variant in VARIANTS:
        found = ns.query_maxima(queries, coefficient_models[variant])
        fitted = start_thresholds(found["값"][XG]["기준용"], image_only)
        found_by[variant] = found
        results["기준"][variant] = fitted
        if not ns.ordered(fitted["기준"]):
            return stop(f"변형 {variant}: 기준 순서가 맞지 않음")
        entry = trained[variant]["entry"]
        meta = {k: trained[variant]["counts"][k] for k in (
            "n", "n_심결", "n_쉬운_음성", "유사", "비유사", "가중_유사", "가중_비유사",
            "자기_패턴_행", "자기_패턴_심결")}
        candidate = with_block(base, entry, thresholds=fitted["기준"], meta=meta)
        candidate["version"] = NEW_VERSION
        candidate["meta"].setdefault("nameless", {})["goods_product"] = {
            "calibrated_at": datetime.now().date().isoformat(), "variant": variant,
            "derived_from": base["version"], "rule_sha256": frozen["설정_sha256"],
            "script": "ml/scripts/goods_product.py", "hinge_c": HINGE_C if variant == "H" else None,
            "training": {"easy_augmented_sha256": EASY_AUGMENTED_SHA, "fixed": [
                "이름 있는 4벌(v1.3)", X], "constraints": trained[variant]["constraints"],
                "optimizer": trained[variant]["optimizer"],
                "rounding_repair_steps": trained[variant]["repair"]["걸음"], "counts": meta},
            "thresholds": {"method": ("이미지만 기준에서 시작, 대조군(표본 A 저유사 이미지 46 × "
                                      "업종 세트 10, 질의 단위) 목표를 넘는 등급만 올림 — "
                                      "goods_product.py"), **fitted},
            "previous_block": {"features": old["features"], "coefficients": old["coefficients"],
                               "intercept": old["intercept"],
                               "grade_thresholds": dict(rm.grade_thresholds_for(base, XG))},
            "adopted": None}
        rm.validate_model({**candidate, "version": BASE_VERSION})
        candidates[variant] = candidate
    models = {"지금": ms.state.model, **candidates}

    # 4. 변형마다 다시 검색
    began = time.perf_counter()
    a_by_key = {query.key: query for query in context["A"]}
    for item in queries:
        image = context["service"](a_by_key[item["키"]].path.read_bytes())
        codes_of = {preset["id"]: sorted(preset["유사군"]) for preset in item["업종"]}
        for entry_ in item["검색"]:
            codes = codes_of.get(entry_["업종_id"]) if entry_["방식"] == "이미지+업종" else None
            for variant in VARIANTS:
                with ns.using_model(ms, candidates[variant]):
                    entry_[variant] = ns._summary(ms.search_pool(  # noqa: SLF001
                        image=image, goods_codes=codes))
    tick("대조군(변형)", began)
    began = time.perf_counter()
    with gzip.open(ns.POSITIVES, "rt", encoding="utf-8") as handle:
        positives = json.load(handle)["양성"][:limit]
    logo = ns.same_logo(context, positives, models)
    tick("같은 로고", began)
    began = time.perf_counter()
    named = gs.named_searches(context, models, limit)
    tick("이름 있는 질의", began)
    began = time.perf_counter()
    goods_rows = nameless_goods(context, models, limit)
    tick("표본 A 이미지+업종", began)
    began = time.perf_counter()
    scenario_runs.update(lo.scenarios(context, candidates))
    tick("시나리오(변형)", began)

    # 5. 채택 조건·판정
    began = time.perf_counter()
    case_ids = {query.key.split(":")[1] for query in context["A"]}
    precision = oof_precision(before, trained, models)
    auc_now = results["학습"]["지금"]["OOF_AUC"]["AUC(도형계)"]
    passed, cited = {}, {}
    results["변형"] = {}
    for variant in VARIANTS:
        candidate = candidates[variant]
        found = found_by[variant]
        check1 = gs.check_1(found, results["기준"][variant]["기준"],
                            check_named(named["대조군"], variant))
        check2 = ns.check_2(logo, variant)
        check3 = ns.cited_pairs(case_ids, {"지금": base, "새": candidate})
        check4 = {"행": precision["행"], "지금": precision["지금"], "변형": precision[variant],
                  "통과": precision[variant]["통과"]}
        check5 = check_5(candidate, base, queries, goods_rows)
        check6 = check_6(goods_rows, variant, base)
        auc = results["학습"][variant]["OOF_AUC"]["AUC(도형계)"]
        check7 = {"지금": auc_now, "변형": auc,
                  "차": None if auc is None or auc_now is None else round(auc - auc_now, 4),
                  "통과": auc is not None and auc_now is not None
                  and auc >= auc_now - AUC_DROP_MAX - 1e-12}
        block = {"채택_1": check1, "채택_2": check2, "채택_3": check3, "채택_4": check4,
                 "채택_5": check5, "채택_6": check6, "채택_7": check7}
        block["통과"] = all(block[f"채택_{i}"]["통과"] for i in range(1, 8))
        block["진단"] = {"위험도_표": probe_table(candidate, base)}
        block["전후"] = {
            "대조군": {name: {k: v for k, v in dist.items() if k in ("지금", variant)}
                    for name, dist in before_after(queries).items()},
            "이름_있는_질의": named_tables(named, variant)}
        results["변형"][variant] = block
        passed[variant] = block["통과"]
        cited[variant] = check3["새"]["검토_권장_이상"]
    results["지금_채택_5"] = check_5(base, base, queries, goods_rows)
    results["지금_채택_6"] = check_6(goods_rows, "지금", base)
    results["진단_업종_차이"] = gs.industry_gap(queries, models)
    results["진단_위험도_표_지금"] = probe_table(base, base)
    results["시나리오"] = {v: lo.scenario_table({"전": scenario_runs["지금"],
                                              "후": scenario_runs[v]}) for v in VARIANTS}
    chosen = choose(passed, cited)
    results["판정"] = {"통과": passed, "인용상표_검토_권장_이상": cited, "고른_변형": chosen}
    results["채택"] = chosen is not None
    for variant in VARIANTS:
        candidates[variant]["meta"]["nameless"]["goods_product"]["adopted"] = (variant == chosen)
    tick("채택 조건", began)
    results["시간_s"] = timing
    results["걸린_시간_s"] = round(time.perf_counter() - started, 1)
    results["끝"] = _now()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for variant in VARIANTS:
        paths[f"candidate_{variant}"].write_text(
            json.dumps(candidates[variant], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with gzip.open(paths["searches"], "wt", encoding="utf-8") as handle:
        json.dump({"대조군": queries, "같은_로고": logo, "이름_있는_질의": named,
                   "표본A_이미지+업종": goods_rows, "시나리오": scenario_runs}, handle,
                  ensure_ascii=False)
    paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    paths["report"].write_text(report_text(results), encoding="utf-8")
    print(json.dumps(results["판정"], ensure_ascii=False))
    print(f"→ {paths['results']}\n→ {paths['report']}")
    return 0 if results["채택"] else EXIT_STOP


def before_after(queries: list[dict]) -> dict:
    out = {}
    for half in ("기준용", "확인용"):
        for mode in ("이미지만", "이미지+업종"):
            entries = [entry for item in queries if item["반"] == half for entry in item["검색"]
                       if entry["방식"] == mode]
            out[f"{half} {mode}"] = {label: ns.distribution(e[label]["전체"] for e in entries)
                                     for label in ("지금", *VARIANTS)
                                     if entries and label in entries[0]}
    return out


def named_tables(searches: dict, label: str) -> dict:
    controls, sample_a = searches["대조군"], searches["표본A"]
    out = {"대조군_확인용": {}, "표본A": {}}
    for mode, _, _ in CONTROL_MODES:
        before = [row["방식"][mode]["지금"]["전체"] for row in controls]
        after = [row["방식"][mode][label]["전체"] for row in controls]
        out["대조군_확인용"][mode] = {
            "지금": ns.distribution(before), "변형": ns.distribution(after),
            "바뀐_질의": sum(1 for b, a in zip(before, after) if b != a)}
    for kind in ("업종 있음", "업종 없음"):
        rows = [row for row in sample_a if row["업종"] == (kind == "업종 있음")]
        before = [row["이름+이미지"]["지금"]["전체"] for row in rows]
        after = [row["이름+이미지"][label]["전체"] for row in rows]
        out["표본A"][kind] = {"질의": len(rows), "지금": ns.distribution(before),
                             "변형": ns.distribution(after),
                             "바뀐_질의": sum(1 for b, a in zip(before, after) if b != a)}
    return out


# ---- 2·3. 적용·확인 ---------------------------------------------------------------------------

def command_apply(args) -> int:
    paths = _paths(args.out_dir)
    if _check_frozen(paths, model_may_change=True) is None:
        return EXIT_REFUSED
    results = json.loads(paths["results"].read_text(encoding="utf-8"))
    if results.get("스모크"):
        print("거절: 스모크 결과입니다 — 적용하지 않습니다", file=sys.stderr)
        return EXIT_REFUSED
    chosen = (results.get("판정") or {}).get("고른_변형")
    decision = None
    if results.get("채택") and chosen in VARIANTS:
        if args.variant and args.variant != chosen:
            print(f"거절: 규칙이 고른 변형은 {chosen} 입니다", file=sys.stderr)
            return EXIT_REFUSED
    elif args.variant in VARIANTS and args.decision:
        # 규칙 '판정'으로는 채택이 없다 — 사람 결정으로 적용(2026-11-24 변형 L, ③ 미달).
        # 그 사실을 계수 JSON meta 에 남긴다
        chosen = args.variant
        decision = {"채택": True, "근거": "사람 결정", "결정일": datetime.now().date().isoformat(),
                    "결정": args.decision, "규칙_판정": results.get("판정")}
    else:
        print("거절: 규칙상 채택된 변형이 없습니다 — 사람 결정으로 적용하려면 --variant 와 "
              "--decision", file=sys.stderr)
        return EXIT_REFUSED
    if NEW_MODEL_PATH.exists() and not args.force:
        print(f"거절: {NEW_MODEL_PATH} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    candidate = json.loads(paths[f"candidate_{chosen}"].read_text(encoding="utf-8"))
    if decision is not None:
        candidate["meta"]["nameless"]["goods_product"]["adopted"] = decision
    rm.validate_model({**candidate, "version": BASE_VERSION})
    NEW_MODEL_PATH.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    print(f"썼다: {NEW_MODEL_PATH} ({candidate['version']}, 변형 {chosen})")
    return 0


def command_verify(args) -> int:
    """기본 모델을 v1.4.5 로 바꾼 뒤 — 기본 엔진으로 다시 돌려 고른 변형의 실행과 같은지."""
    paths = _paths(args.out_dir)
    if _check_frozen(paths, model_may_change=True) is None:
        return EXIT_REFUSED
    if rm.MODEL_VERSION != NEW_VERSION or rm.resolve_model_path() != NEW_MODEL_PATH:
        print("거절: 서비스 기본 모델이 v1.4.5 가 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    results = json.loads(paths["results"].read_text(encoding="utf-8"))
    applied = json.loads(NEW_MODEL_PATH.read_text(encoding="utf-8"))
    chosen = results["판정"]["고른_변형"] or applied["meta"]["nameless"]["goods_product"]["variant"]
    with gzip.open(paths["searches"], "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    context = ns._context(NEW_MODEL_PATH)  # noqa: SLF001
    ms = context["ms"]
    candidate = json.loads(paths[f"candidate_{chosen}"].read_text(encoding="utf-8"))
    if (ms.state.model.get("version") != NEW_VERSION
            or ms.state.model[rm.NAMELESS_KEY] != candidate[rm.NAMELESS_KEY]):
        print("거절: 엔진이 적재한 모델이 고른 변형의 후보와 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    lo.memo_ocr(ms)
    mismatch, checked = Counter(), Counter()

    def same(got: dict, old: dict) -> bool:
        return got["전체"] == old["전체"] and (
            [c["id"] for c in got["상위"]] == [c["id"] for c in old["상위"]])

    a_by_key = {query.key: query for query in context["A"]}
    for item in saved["대조군"]:
        if item["반"] != "확인용":
            continue
        image = context["service"](a_by_key[item["키"]].path.read_bytes())
        codes_of = {preset["id"]: sorted(preset["유사군"]) for preset in item["업종"]}
        for entry in item["검색"]:
            codes = codes_of.get(entry["업종_id"]) if entry["방식"] == "이미지+업종" else None
            got = ns._summary(ms.search_pool(image=image, goods_codes=codes))  # noqa: SLF001
            checked["대조군"] += 1
            mismatch["대조군"] += int(not same(got, entry[chosen]))
    with gzip.open(ns.POSITIVES, "rt", encoding="utf-8") as handle:
        positives = {item["출원번호"]: item for item in json.load(handle)["양성"]}
    logo = ns.same_logo(context, [positives[r["출원번호"]] for r in saved["같은_로고"]["행"]],
                        {"기본": ms.state.model})
    for row, old in zip(logo["행"], saved["같은_로고"]["행"]):
        for mode in ("업종 없음", "같은 업종"):
            checked["같은_로고"] += 1
            got, want = row["방식"][mode]["기본"], old["방식"][mode][chosen]
            mismatch["같은_로고"] += int(got["성공"] != want["성공"] or got["1위"] != want["1위"])
    again = gs.named_searches(context, {chosen: ms.state.model}, None)
    for new, old in zip(again["대조군"], saved["이름_있는_질의"]["대조군"]):
        for mode, _, _ in CONTROL_MODES:
            checked["이름_있는_대조군"] += 1
            mismatch["이름_있는_대조군"] += int(not same(new["방식"][mode][chosen],
                                                    old["방식"][mode][chosen]))
    for new, old in zip(again["표본A"], saved["이름_있는_질의"]["표본A"]):
        checked["표본A"] += 1
        mismatch["표본A"] += int(not same(new["이름+이미지"][chosen], old["이름+이미지"][chosen]))
    goods = nameless_goods(context, {chosen: ms.state.model}, None)
    for new, old in zip(goods, saved["표본A_이미지+업종"]):
        checked["표본A_이미지+업종"] += 1
        a, b = new["모델"][chosen], old["모델"][chosen]
        mismatch["표본A_이미지+업종"] += int(a["전체"] != b["전체"] or [c["id"] for c in a["상위"]]
                                       != [c["id"] for c in b["상위"]])
    default = lo.scenarios(context, {"기본": ms.state.model})["기본"]
    after = saved["시나리오"][chosen]
    scenario_diff = [key for key, item in default.items()
                     if item.get("전체") != after.get(key, {}).get("전체")
                     or [c["id"] for c in item.get("상위", [])]
                     != [c["id"] for c in after.get(key, {}).get("상위", [])]]
    verify = {"모델": ms.state.model["version"], "변형": chosen, "다시_돌린_질의": dict(checked),
              "불일치": dict(mismatch), "시나리오_다른_것": scenario_diff,
              "통과": not any(mismatch.values()) and not scenario_diff,
              "걸린_시간_s": round(time.perf_counter() - started, 1), "끝": _now()}
    paths["verify"].write_text(json.dumps(verify, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")
    print(json.dumps(verify, ensure_ascii=False))
    return 0 if verify["통과"] else EXIT_STOP


# ---- 보고 --------------------------------------------------------------------------------------

def report_text(results: dict) -> str:
    lines = ["# 이름 없는 '이미지+업종' 판단의 곱하기 항(변형 L·H) — 보고", "",
             f"- 설정 sha256 `{results['설정_sha256']}` · 스크립트 고정 "
             f"`{results['스크립트_sha256(고정 때)']}` · 잴 때 "
             f"`{results['스크립트_sha256(잴 때)']}` · c {results.get('c')}",
             f"- 스모크 {results['스모크']} · 판정 {results.get('판정')} · 멈춤 "
             f"{results.get('멈춤')}", ""]
    for key in ("지금_재현", "학습", "기준", "검산_시나리오"):
        if key in results:
            lines += [f"## {key}", "", "```",
                      json.dumps(results[key], ensure_ascii=False)[:4000], "```", ""]
    for variant, block in (results.get("변형") or {}).items():
        lines += [f"## 변형 {variant} — 통과 {block['통과']}", ""]
        for i in range(1, 8):
            lines += [f"### 채택_{i} — {block[f'채택_{i}']['통과']}", "", "```",
                      json.dumps(block[f"채택_{i}"], ensure_ascii=False)[:2500], "```", ""]
        lines += ["### 전후", "", "```", json.dumps(block["전후"], ensure_ascii=False)[:3000],
                  "```", ""]
    for variant, rows in (results.get("시나리오") or {}).items():
        lines += [f"## 시나리오 16종 — 변형 {variant}", "",
                  "| 키 | 제목 | 지금 | 변형 | 1위(지금 → 변형) |",
                  "|---|---|---|---|---|"]
        for row in rows:
            if row.get("건너뜀"):
                lines.append(f"| {row['키']} | {row['제목']} | — | — | — |")
                continue
            lines.append(f"| {row['키']} | {row['제목']} | {row['전']['grade']} "
                         f"{row['전']['prob']} | {row['후']['grade']} {row['후']['prob']} | "
                         f"{row['전_1위']} → {row['후_1위']} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("freeze", "run", "apply", "verify"))
    parser.add_argument("--out-dir", type=Path, default=TRIALS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--variant", choices=VARIANTS,
                        help=("apply: 규칙상 채택이 없을 때 사람 결정으로 적용할 변형"
                              "(--decision 과 함께)"))
    parser.add_argument("--decision", help="apply: 사람 결정 문구(계수 JSON meta 에 남김)")
    parser.add_argument("--smoke", action="store_true",
                        help=("시험 실행 — 대조군 이미지 반마다 12·양성 4·이름 있는 질의 4·"
                              "표본 A 업종 4(--out-dir 를 따로)"))
    args = parser.parse_args(argv)
    if args.smoke and args.out_dir.resolve() == TRIALS.resolve():
        print("거절: --smoke 는 --out-dir 를 따로 주세요", file=sys.stderr)
        return EXIT_REFUSED
    return {"freeze": command_freeze, "run": command_run, "apply": command_apply,
            "verify": command_verify}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
