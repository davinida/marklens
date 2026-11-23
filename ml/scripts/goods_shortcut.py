"""이름 없는 '이미지+업종' 판단의 업종 지름길을 고친다(2026-11-23, 지시로 고정). 학습의
쉬운 음성은 업종 겹침 0.5 이상이 2%뿐이라 noname:x2_whole+x4 가 "업종이 같으면 닮았다"를
배웠다(x4 1.5302) — 로고 + 업종만 넣으면 무관한 같은 업종 로고의 60%대가 검토 권장. 같은 업종
안에서 이미지가 안 닮은 DB 쌍을 음성으로 더해 그 계수 집합만 v1.4 절차로 다시 학습하고, 그 집합의
기준만 §7-8 1단계 방식으로 다시 맞춘다. KIPRIS 호출 0.

    ml/venv/bin/python ml/scripts/goods_shortcut.py freeze   # 0. 규칙·입력 해시
    ml/venv/bin/python ml/scripts/goods_shortcut.py run      # 1. 음성 → 학습 → 기준 → 검색 → ①–⑤
    ml/venv/bin/python ml/scripts/goods_shortcut.py apply    # 2. 채택일 때만 v1.4.4 JSON
    ml/venv/bin/python ml/scripts/goods_shortcut.py verify   # 3. 기본 모델 바꾼 뒤

전·후 = 같은 프로세스에서 엔진 계수(multi_search.state.model)만 v1.4.3 ↔ 후보. 산출(비공개):
ml/data/trials/goods_shortcut_{rule,results,candidate,verify}.json·_negatives.csv·
_easy_augmented.csv·_searches.json.gz·_report.md. 고정본과 다르면 거절(종료 코드 4), 검산 불일치·
채택 미달이면 3.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import random
import re
import statistics
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

from src.model import risk_model as rm  # noqa: E402

from scripts import logo_floor_image_only as lo  # noqa: E402
from scripts import named_search_thresholds as first  # noqa: E402
from scripts import nameless_shared_threshold as ns  # noqa: E402

TRIALS = ML_ROOT / "data" / "trials"
STEM = "goods_shortcut"
EXIT_STOP = 3
EXIT_REFUSED = 4
CAUTION, REVIEW, RISK = "주의", "검토 권장", "위험"
X, XG = ns.X, ns.XG  # "noname:x2_whole", "noname:x2_whole+x4"
XG_KEY = XG[len(rm.NAMELESS_PREFIX):]
X_KEY = X[len(rm.NAMELESS_PREFIX):]
SEED = 0
SAME_GOODS_MIN = 0.5
IMAGE_SHARE = 0.5  # 이미지 유사도 하위 50%
KEY_PREFIX = "samegoods"
REPEAT = ns.REPEAT  # 이미지 하나에 붙이는 업종 세트 수(10)
TARGETS = {REVIEW: 0.10, RISK: 0.02}
CAUTION_SHARE = 0.5  # 새 검토 권장 ≤ 지금 주의일 때만 — 무관한 질의의 50%
TOLERANCE = ns.TOLERANCE  # 0.0224
SAME_LOGO_MIN = ns.SAME_LOGO_MIN  # 0.95
CITED_RATIO_MIN = ns.CITED_RATIO_MIN  # 0.5
PRECISION_MIN = 0.70
PRECISION_MIN_ROWS = 10
EASY_MAX_SCORE = 0.8  # 쉬운 음성의 우연 유사 기준(보고만)
BASE_VERSION = "risk_model_v1.4.3"
NEW_VERSION = "risk_model_v1.4.4"
BASE_MODEL_PATH = REPO_ROOT / "shared" / "model" / "risk_model_v1.4.3.json"
NEW_MODEL_PATH = REPO_ROOT / "shared" / "model" / "risk_model_v1.4.4.json"
SAVED_SCENARIOS = TRIALS / "weak_run_adjacent_searches.json.gz"  # v1.4.3 확인 실행(시나리오 후)
CONTROL_MODES = (("이름만", False, False), ("이름+업종", False, True),
                 ("이름+이미지", True, False), ("이름+이미지+업종", True, True))
NAMED_GOODS_MODE = "이름+이미지+업종"
DISPLAY_TOP = first.DISPLAY_TOP

# 규칙(이 지시로 고정 — 실행 전에 해시를 남기고 결과를 보고 바꾸지 않는다) ------------------------
RULE = {
    "같은_업종_음성": (
        "seed 0. 서비스 DB(kipris_metadata.json 1,383건 — 기존 수집·유명 브랜드 모두)의 상표 "
        "쌍(순서 없음) 중 (가) 둘 다 서비스 색인 벡터가 있고 사진 아님(src.photo_mark.is_photo — "
        "학습 특징의 사진 판정과 같음) (나) 둘 다 유사군이 있고 업종 "
        "겹침(x4_goods.goods_similarity — 학습 특징 x4 와 같은 식, DB 유사군 그대로) ≥ 0.5 (다) "
        "다른 출원인 — DB 출원인 칸을 '|' 로 나눠 정규화하고 별칭 "
        "표(shared/applicant_aliases.json)로 묶은 집합이 겹치지 "
        "않음(nameless_search_thresholds.split_applicants — 표본 A·대조군의 같은 출원인 판정과 "
        "같음) (라) 심결에서 서로 인용·분쟁 관계 없음 — labels.csv 의 행마다 이 사건 표장(심판 "
        "목록의 출원번호·등록번호, 상표A_번호)과 상대 "
        "표장(상대표장_번호_정규화·상표B_번호·상대표장_번호_후보)을 DB 출원번호·등록번호에 "
        "대조(숫자만, 7자리 이하는 40 + 7자리 + 0000 등록번호 꼴로)해 한 행에 함께 나오는 쌍을 뺌 "
        "(마) 지금 쉬운 음성(pairs_features_easy.csv)의 db 쌍과 같은 쌍이 아님. 남은 쌍을 이미지 "
        "유사도(색인 벡터 코사인, 음수는 0 — 쉬운 음성 db 의 x2_whole 과 같은 식) 오름차순(같으면 "
        "출원번호 쌍 순)으로 놓고 앞의 ⌊n/2⌋(하위 50%)에서 random.Random(0).sample 로 N 쌍. N = "
        "지금 학습(학습 특징 + 쉬운 음성, t4.load_dataset·t4.Design v1.4)에서 noname:x2_whole+x4 "
        "학습 행에 드는 쉬운 음성 행 수."),
    "음성_행": (
        "행은 쉬운 음성 db 행과 같은 함수(pairs_features._easy_row — pair_source db, 최종라벨 "
        "비유사, 이름 축은 상표명(한글명 > 영문명), 이름 없는 상표는 이름 축 빈 칸)에 "
        "x2_whole·has_image·사진A·사진B('0')를 채운 것, 키 'samegoods:<출원번호>|<출원번호>'(묶음 "
        "= 자기 키). 이름 유사로 거르지 않는다(지시의 조건만) — 쉬운 음성의 우연 유사 "
        "기준(x1·x2_text ≥ 0.8)에 걸리는 쌍 수는 보고만. 늘린 쉬운 음성 = 지금 쉬운 음성 파일 "
        "그대로 + 새 행(앞부분은 원본과 바이트로 같아야 함)."),
    "다시_학습": (
        "v1.4 2차 학습 절차(train_risk_model_v14_nameless) 그대로: 데이터 t4.load_dataset(학습 "
        "특징, 늘린 쉬운 음성)(사진 규칙·사건 가중 상한 3·쉬운 음성 가중 0.5·묶음), 설계 "
        "t4.Design(v1.4), 제약 t2.build_constraints(설계, v1.3 JSON coupling.floors)(단조·이름 "
        "없는 두 집합 사이 축 결합 — 업종을 하한 이상 더하면 로짓 비감소·같은 이름), 사전분포 σ "
        "1.0, 교차검증 t2.cv_nameless(5겹 × 3반복, seed 0), 전체 적합 t4.fit_joint. 이름 있는 "
        "4벌(v1.3 JSON)과 noname:x2_whole(v1.4.3 계수 그대로)은 고정하고 noname:x2_whole+x4 만 "
        "적합. 반올림 t2.rounded_nameless(넷째 자리·단조 보정), 반올림이 만든 결합 위반(rm 적재 "
        "검증, 허용 1e-9)은 noname:x2_whole+x4 의 절편만 0.0001 씩 — 축 결합 위반이면 올리고 같은 "
        "이름 위반이면 내린다(이미지만 집합은 고정이라). 검산: 지금 교차검증 재현(t2.train_once, "
        "학습 특징 + 지금 쉬운 음성, v1.3 JSON)의 반올림 계수가 v1.4.3 의 이름 없는 두 집합 "
        "계수와 같아야 함(다르면 멈춤)."),
    "학습_진단": (
        "판정에 쓰지 않음. (가) OOF 심결 AUC — noname:x2_whole+x4 학습 행 중 심결 행의 교차검증 "
        "OOF 위험도(도형계로 본 값 per_block_figure, 행의 유형 per_block)로 AUC(가중 없음·사건 "
        "가중), 지금(재현 교차검증) 대 새 (나) noname:x2_whole+x4 계수·절편 전후 (다) 무관한 같은 "
        "업종 쌍(겹침 ≥ 0.5)과 다른 업종 쌍(겹침 < 결합 하한 0.0252)의 noname:x2_whole+x4 "
        "위험도(유형 도형) 평균·중앙과 그 차 — 대조군(기준용+확인용) 이미지+업종 질의의 무관한 "
        "후보, 이미지 유사도 구간(< 0.3·0.3–0.5·≥ 0.5)별로도 (라) 결합 제약 위반 수 — 적합의 최소 "
        "여유, 반올림 뒤 보정 걸음, 학습 행 단조성(t2.row_monotonicity), 적재 "
        "검증(rm.coupling_violations)."),
    "기준": (
        "noname:x2_whole+x4 의 검토 권장·위험만 다시 맞춘다(§7-8 1단계와 같은 방식): 대조군 = 1차 "
        "시도 대조군(sha256 f6b11d62…)의 이미지 기준용 46·확인용 46, 이미지마다 업종 세트 25개 중 "
        "random.Random('0|업종|<질의 키>').sample(…, "
        "10)(nameless_shared_threshold.control_queries 그대로), 서비스 엔진 후보 "
        "풀(search_pool)의 무관한 후보(인용상표·같은 출원인 뺌 — 1차 시도 "
        "a_relations·unrelated_filter). 질의 단위 M_q = 무관한 후보 중 새 계수의 "
        "noname:x2_whole+x4 위험도(업종 하한 전, 유형 도형 — set_prob) 최댓값. 기준용 460질의로 "
        "검토 권장 = fit_cut(M, 10%)·위험 = fit_cut(M, 2%)(1차 시도 fit_cut — 그 값 이상인 질의 ≤ "
        "⌊목표·n⌋ 인 가장 낮은 넷째 자리 값). noname:x2_whole 의 기준·업종 하한(goods_floor)·이름 "
        "있는 하한은 그대로. 주의 0.2944 그대로 — 단 새 검토 권장 ≤ 0.2944 이면 멈추지 않고 주의 "
        "= 기준용 fit_cut(M, 50%)."),
    "채택_1": (
        "(가) 대조군 확인용 460질의의 새 M_q 로 새 기준 이상인 질의 비율: 검토 권장 ≤ 10%·위험 ≤ "
        "2% — 넘으면 확인용에 같은 규칙으로 맞춘 값 − 새 기준 ≤ 0.0224 일 때만 통과(§7-8 채택_1 "
        "과 같음). (나) 1차 시도 대조군 확인용 100(지어낸 이름)의 이름+이미지+업종 질의에서 엔진 "
        "전체 등급(정렬 앞 5건의 최고 표시 등급)이 검토 권장 이상인 비율: 새 ≤ 지금(v1.4.3)."),
    "채택_2": (
        "같은 로고 200(1차 시도 logo_floor_named 양성 — 이미지·유사군·인정 상표)을 이름 없이 업종 "
        "없음·같은 업종(그 양성의 유사군) 두 방식으로: 새 모델로 엔진 정렬 1위가 인정 상표이고 그 "
        "표시 등급이 검토 권장 이상인 질의 비율이 방식마다 ≥ 95%(§7-8 채택_2 와 같음)."),
    "채택_3": (
        "표본 A 인용상표 — §7-8 채택_4 와 같은 쌍(표본 A 사건의 심결 행 중 이미지 축(원래 값, "
        "사진 규칙 전)이 있는 행)을 서비스 채점식의 이름 없는 판단(이름 없는 계수, 유형 도형, 그 "
        "행의 이미지·상품 축, 업종 하한·도형 규칙)으로 매긴 검토 권장 이상 비율: 새 ≥ 지금 × 0.5."),
    "채택_4": (
        "이름 없는 판단의 위험 정밀도(심결 쌍, OOF) — §7-8 채택_3 의 판정식: 이미지 축이 있는 "
        "심결 행(사진 규칙 뒤), 상품 축이 있으면 noname:x2_whole+x4 의 OOF 등급(겹침 ≥ 0.0252 면 "
        "noname:x2_whole OOF 등급과 견줘 높은 쪽), 없으면 noname:x2_whole OOF 등급, 이미지 ≥ 0.9 "
        "면 도형 규칙(검토 권장 이상). OOF 는 도형계로 본 값. 새 = noname:x2_whole+x4 는 새 "
        "교차검증 OOF·새 기준, noname:x2_whole 은 지금 교차검증 OOF·지금 기준(바뀌지 않는 집합). "
        "위험 행 ≥ 10 이면 그 유사 비율(가중 없음) ≥ 0.70, 10 미만이면 판정에 쓰지 않고 보고만."),
    "채택_5": (
        "(가) 모든 이름 없는 집합의 주의 < 검토 권장 < 위험 (나) 단조 위반 "
        "0(rm.monotone_violations — 모든 계수 집합)·결합 위반 0(rm.coupling_violations — 이름 "
        "없는 두 집합 사이 축 결합·같은 이름 포함) (다) 겹침 ≥ 결합 하한 0.0252 인 업종을 더했을 "
        "때 서비스 최종 등급(업종 하한·도형 규칙 포함 — first.nameless_final_grade)이 이미지만 "
        "최종 등급보다 낮은 경우 0: 격자 x2 0–1·x4 0.0252–1(0.002 간격) + 대조군 실제 쌍(같은 "
        "이미지의 이미지만·이미지+업종 질의에 모두 나온 후보). 업종 하한을 빼고 센 수와 겹침이 "
        "결합 하한 아래(0 < x4 < 0.0252)인 실제 쌍의 내려감은 보고만 — 지시가 이미지만 집합의 "
        "기준과 업종 하한을 그대로 두라고 해 두 집합의 기준이 달라 업종 하한 없이는 보장되지 "
        "않고, 서비스는 업종 하한을 그대로 둔다."),
    "전후": (
        "대조군(기준용·확인용) 이미지만·이미지+업종 엔진 전체 등급 분포(지금 v1.4.3 대 후보 — "
        "같은 프로세스에서 계수 JSON 만 바꿔 다시 검색), 같은 로고, 표본 A 인용상표 등급 분포, "
        "이름 있는 질의 쪽(상표명 없는 후보의 이름 없는 판단이 바뀜) — 1차 시도 대조군 확인용 100 "
        "× 네 방식과 표본 A 검색 184(이름+이미지, 질의 업종이 있으면 함께)의 전체 등급 분포·바뀐 "
        "질의, 시나리오 16종(named_shared_threshold.SCENARIOS — 시연 넷·로고만 N1·N2·S2 포함). "
        "검산: 바꾸기 전 시나리오 16종(전체 grade·prob·pattern, 상위 5 출원번호)이 v1.4.3 확인 "
        "실행 저장값(weak_run_adjacent_searches.json.gz 의 시나리오 후)과 같아야 함 — 다르면 "
        "멈춤."),
    "적용": (
        "채택될 때만 shared/model/risk_model_v1.4.4.json = v1.4.3 JSON 에서 "
        "nameless_patterns['x2_whole+x4'] 의 계수·절편·grade_thresholds·meta(학습 행 수)만 바꾸고 "
        "version risk_model_v1.4.4, meta.nameless.goods_shortcut(음성 표본·학습·기준 출처). 기본 "
        "모델을 v1.4.4 로 바꾼 뒤 verify 가 대조군 확인용·같은 로고·이름 있는 대조군·표본 A "
        "검색·시나리오를 기본 엔진으로 다시 돌려 후보 실행과 같은지 본다."),
}


def _settings() -> dict:
    return {"RULE": RULE, "SEED": SEED, "SAME_GOODS_MIN": SAME_GOODS_MIN,
            "IMAGE_SHARE": IMAGE_SHARE, "KEY_PREFIX": KEY_PREFIX, "REPEAT": REPEAT,
            "TARGETS": TARGETS, "CAUTION_SHARE": CAUTION_SHARE, "TOLERANCE": TOLERANCE,
            "SAME_LOGO_MIN": SAME_LOGO_MIN, "CITED_RATIO_MIN": CITED_RATIO_MIN,
            "PRECISION_MIN": PRECISION_MIN, "PRECISION_MIN_ROWS": PRECISION_MIN_ROWS,
            "EASY_MAX_SCORE": EASY_MAX_SCORE, "BASE_VERSION": BASE_VERSION,
            "NEW_VERSION": NEW_VERSION, "CONTROL_SHA": ns.CONTROL_SHA,
            "CONTROL_MODES": CONTROL_MODES, "DISPLAY_TOP": DISPLAY_TOP,
            "GRID_STEP": ns.GRID_STEP}


def rule_sha256() -> str:
    return first.canonical_sha256(_settings())


def _inputs() -> dict[str, Path]:
    from scripts import nameless_search_thresholds as nst
    from scripts import train_risk_model as tr

    scripts = ML_ROOT / "scripts"
    return {"계수_JSON(v1.4.3)": BASE_MODEL_PATH, "v1.3_JSON": rm.V13_MODEL_PATH,
            "학습_특징": tr.DEFAULT_FEATURES, "쉬운_음성": tr.DEFAULT_EASY,
            "라벨": nst.DEFAULT_LABELS, "심판_목록": nst.DEFAULT_LIST,
            "이미지_쌍": nst.DEFAULT_IMAGE_PAIRS, "메타데이터": nst.DEFAULT_METADATA,
            "색인": ML_ROOT / "data" / "index" / "kipris.faiss",
            "색인_메타": ML_ROOT / "data" / "index" / "kipris_metadata.json",
            "색인_manifest": ML_ROOT / "data" / "index" / "kipris_manifest.json",
            "유형_사전": ML_ROOT / "data" / "types.json", "별칭": nst.DEFAULT_ALIASES,
            "사진_방향": REPO_ROOT / "shared" / "model" / "photo_direction_v1.json",
            "대조군": first._paths(TRIALS)["control"], "양성(1차 시도)": ns.POSITIVES,
            "시나리오_저장값": SAVED_SCENARIOS,
            "엔진": REPO_ROOT / "backend" / "src" / "core" / "multi_search.py",
            "런타임": ML_ROOT / "src" / "model" / "risk_model.py",
            "학습_스크립트(2차)": scripts / "train_risk_model_v14_nameless.py",
            "학습_스크립트(v1.4)": scripts / "train_risk_model_v14.py",
            "학습_스크립트(v1.3)": scripts / "train_risk_model.py",
            "학습_특징_스크립트": scripts / "pairs_features.py",
            "식별력": ML_ROOT / "src" / "axes" / "distinctiveness.py"}


def _paths(out_dir: Path) -> dict[str, Path]:
    return {"rule": out_dir / f"{STEM}_rule.json", "results": out_dir / f"{STEM}_results.json",
            "report": out_dir / f"{STEM}_report.md",
            "candidate": out_dir / f"{STEM}_candidate.json",
            "negatives": out_dir / f"{STEM}_negatives.csv",
            "easy": out_dir / f"{STEM}_easy_augmented.csv",
            "searches": out_dir / f"{STEM}_searches.json.gz",
            "verify": out_dir / f"{STEM}_verify.json"}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _round(value, digits: int = 4):
    return None if value is None else round(float(value), digits)


# ---- 순수 함수(시험 대상) ----------------------------------------------------------------------

def normalize_number(value) -> str:
    """출원·등록번호 → 13자리(숫자만; 7자리 이하는 등록번호 꼴 40 + 7자리 + 0000)."""
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    return "40" + digits.zfill(7) + "0000" if len(digits) <= 7 else digits


def trial_related_pairs(labels: list[dict], trial_list: dict[str, dict],
                        numbers: dict[str, str]) -> tuple[set[tuple[str, str]], dict]:
    """심결 행마다 이 사건 표장·상대 표장을 DB 출원번호로 — 한 행에 함께 나오는 DB 쌍."""
    pairs: set[tuple[str, str]] = set()
    this_hits: set[str] = set()
    other_hits: set[str] = set()
    for row in labels:
        listed = trial_list.get(row.get("심판번호")) or {}
        this = {numbers[n] for n in map(normalize_number, (listed.get("출원번호"),
                                                           listed.get("등록번호"),
                                                           row.get("상표A_번호")))
                if n in numbers}
        raw = [row.get("상대표장_번호_정규화"), row.get("상표B_번호"),
               *re.split(r"[;|,\s]+", row.get("상대표장_번호_후보") or "")]
        other = {numbers[n] for n in map(normalize_number, raw) if n in numbers}
        this_hits |= this
        other_hits |= other
        for a in this:
            for b in other:
                if a != b:
                    pairs.add(tuple(sorted((a, b))))
    return pairs, {"이_사건_표장_DB": len(this_hits), "상대_표장_DB": len(other_hits),
                   "관계_쌍": len(pairs)}


def bottom_share(scored: list[tuple[float, str, str]], share: float = IMAGE_SHARE) -> list:
    """(이미지 유사도, 출원번호, 출원번호) 오름차순(같으면 번호 순)의 앞 ⌊share·n⌋."""
    ordered = sorted(scored, key=lambda item: (item[0], item[1], item[2]))
    return ordered[:int(len(ordered) * share)]


def sample_pairs(pool: list, n: int, seed: int = SEED) -> list:
    if n > len(pool):
        raise ValueError(f"표본 {n} 쌍을 뽑을 모집단이 {len(pool)} 쌍뿐입니다")
    picked = random.Random(seed).sample(pool, n)
    return sorted(picked, key=lambda item: (item[1], item[2]))


def summary_stats(values: list[float]) -> dict | None:
    if not values:
        return None
    q = np.percentile(values, [0, 25, 50, 75, 100])
    return {"n": len(values), "평균": _round(statistics.fmean(values)),
            "최소": _round(q[0]), "사분위25": _round(q[1]), "중앙": _round(q[2]),
            "사분위75": _round(q[3]), "최대": _round(q[4])}


def fit_goods_thresholds(values: list[float], caution_now: float) -> dict:
    """규칙 '기준' — noname:x2_whole+x4 의 새 기준과 근거."""
    review, k_review, n = first.fit_cut(values, TARGETS[REVIEW])
    risk, k_risk, _ = first.fit_cut(values, TARGETS[RISK])
    caution, refit, k_caution = float(caution_now), False, None
    if review is not None and review <= float(caution_now) + 1e-12:
        caution, k_caution, _ = first.fit_cut(values, CAUTION_SHARE)
        refit = True
    return {"기준": {CAUTION: caution, REVIEW: review, RISK: risk},
            "k": {REVIEW: k_review, RISK: k_risk, CAUTION: k_caution}, "n": n,
            "주의_다시_맞춤": refit}


def goods_block(base: dict, entry: dict, thresholds: dict | None = None,
                meta: dict | None = None) -> dict:
    """base 의 noname:x2_whole+x4 계수·절편(·기준·meta)만 바꾼 모델."""
    out = copy.deepcopy(base)
    block = out[rm.NAMELESS_KEY][XG_KEY]
    block["coefficients"] = {name: float(value) for name, value in entry["coefficients"].items()}
    block["intercept"] = float(entry["intercept"])
    if thresholds is not None:
        block["grade_thresholds"] = {grade: float(thresholds[grade])
                                     for grade in rm.GRADE_THRESHOLD_KEYS}
    if meta is not None:
        block["meta"] = meta
    return out


def repair_coupling(model: dict, *, digits: int = 4, limit: int = 10_000) -> tuple[dict, dict]:
    """반올림이 만든 결합 위반을 noname:x2_whole+x4 의 절편만 움직여 고친다(축 결합 위반 → 올림,
    같은 이름 위반 → 내림). 두 방향이 다 필요하면 고치지 못한 것으로 보고한다."""
    from scripts import train_risk_model as tr

    out = copy.deepcopy(model)
    block = out[rm.NAMELESS_KEY][XG_KEY]
    step = 10.0 ** -digits
    moves = Counter()
    for _ in range(limit):
        violations = rm._nameless_coupling_violations(out, tr.COUPLING_TOLERANCE)  # noqa: SLF001
        if not violations:
            break
        first_violation = violations[0]
        if first_violation.startswith(f"{X} → {XG} "):
            direction = "올림"
        elif first_violation.startswith(f"{XG} → {XG_KEY} "):
            direction = "내림"
        else:
            return out, {"걸음": dict(moves), "고침": False, "남은_위반": violations[:5]}
        moves[direction] += 1
        if len(moves) > 1:
            return out, {"걸음": dict(moves), "고침": False, "남은_위반": violations[:5]}
        sign = 1.0 if direction == "올림" else -1.0
        block["intercept"] = round(block["intercept"] + sign * step, digits)
    remaining = rm._nameless_coupling_violations(out, tr.COUPLING_TOLERANCE)  # noqa: SLF001
    return out, {"걸음": dict(moves), "고침": not remaining, "남은_위반": remaining[:5]}


def precision_check(grades: list[str], labels: list[int]) -> dict:
    risk = [y for g, y in zip(grades, labels) if g == RISK]
    n = len(risk)
    value = round(sum(risk) / n, 4) if n else None
    judged = n >= PRECISION_MIN_ROWS
    return {"위험": n, "유사": int(sum(risk)), "정밀도": value, "판정에_씀": judged,
            "통과": (not judged) or (value is not None and value >= PRECISION_MIN - 1e-12)}


def industry_gap(queries: list[dict], models: dict[str, dict]) -> dict:
    """학습 진단 (다) — 대조군 이미지+업종 질의의 무관한 후보: 같은 업종(겹침 ≥ 0.5) 대 다른
    업종(겹침 < 결합 하한)."""
    out: dict = {}
    for label, model in models.items():
        floor = float(model["coupling"]["floors"]["x4"])
        groups: dict[str, dict[str, list[float]]] = {}
        for item in queries:
            for entry in item["검색"]:
                if entry["방식"] != "이미지+업종":
                    continue
                for c in entry["풀"]:
                    if not c["무관"] or c["x2"] is None or c["x4"] is None:
                        continue
                    if c["x4"] >= SAME_GOODS_MIN:
                        kind = "같은 업종"
                    elif c["x4"] < floor:
                        kind = "다른 업종"
                    else:
                        continue
                    image = ("x2<0.3" if c["x2"] < 0.3 else ("0.3–0.5" if c["x2"] < 0.5
                                                              else "≥0.5"))
                    p = ns.set_prob(c["x2"], c["x4"], model)
                    for bucket in ("전체", image):
                        groups.setdefault(bucket, {}).setdefault(kind, []).append(p)
        table = {}
        for bucket, kinds in groups.items():
            same, other = kinds.get("같은 업종", []), kinds.get("다른 업종", [])
            row = {kind: summary_stats(values) for kind, values in kinds.items()}
            if same and other:
                row["평균_차(같은 − 다른)"] = _round(statistics.fmean(same)
                                                - statistics.fmean(other))
                row["중앙_차(같은 − 다른)"] = _round(statistics.median(same)
                                                - statistics.median(other))
            table[bucket] = row
        out[label] = table
    return out


def check_named(rows: list[dict]) -> dict:
    """채택_1 (나) — 이름 있는 대조군 이름+이미지+업종의 검토 권장 이상 비율이 늘지 않음."""
    def rate(label: str) -> float | None:
        flags = [ns.at_least(row["방식"][NAMED_GOODS_MODE][label]["전체"], REVIEW) for row in rows]
        return sum(flags) / len(flags) if flags else None

    now, new = rate("지금"), rate("새")
    return {"질의": len(rows), "지금": now, "새": new,
            "통과": now is not None and new is not None and new <= now + 1e-12}


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
    print(f"설정 sha256 {frozen['설정_sha256']} · 스크립트 sha256 {frozen['스크립트_sha256']}")
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


# ---- 1. 같은 업종 음성 --------------------------------------------------------------------------

def easy_goods_count(features: Path, easy: Path) -> int:
    from scripts import train_risk_model_v14 as t4

    rows = t4.load_dataset(features, easy).rows
    a = t4.arrays(rows)
    design = t4.Design(rows, structure="v1.4", nameless_keys=t4.NAMELESS_KEYS)
    return int((design.mask[XG] & a["easy"]).sum())


def build_negatives(n: int) -> tuple[list[dict], dict]:
    """규칙 '같은_업종_음성'·'음성_행'."""
    from src import photo_mark  # numpy 만 — torch·faiss 를 불러오지 않음

    from scripts import nameless_search_thresholds as nst
    from scripts import pairs_features as pf  # torch → faiss 순서(x2_benchmark)

    metadata = json.loads(pf.DEFAULT_METADATA.read_text(encoding="utf-8"))
    records = metadata.get("trademarks", metadata)
    vectors = pf.db_embedding_provider()([r["이미지파일"] for r in records
                                          if r.get("이미지파일")])
    aliases = nst.load_aliases(nst.DEFAULT_ALIASES)
    numbers: dict[str, str] = {}
    for record in records:
        for field_name in ("출원번호", "등록번호"):
            value = str(record.get(field_name) or "").strip()
            if value:
                numbers[value] = str(record["출원번호"])
    labels = nst._read_csv(nst.DEFAULT_LABELS)  # noqa: SLF001
    trial_list = {row["심판번호"]: row for row in nst._read_csv(nst.DEFAULT_LIST)}  # noqa: SLF001
    related, related_report = trial_related_pairs(labels, trial_list, numbers)
    easy_records = pf.read_db_records(pf.DEFAULT_METADATA)
    existing: set[tuple[str, str]] = set()
    for row in pf.read_csv(pf.DEFAULT_BASE / "pairs_features_easy.csv"):
        source, _, pair = row["심판번호"].partition(":")
        if source == "db":
            i, _, j = pair.partition("|")
            existing.add(tuple(sorted((str(easy_records[int(i)]["출원번호"]),
                                       str(easy_records[int(j)]["출원번호"])))))
    usable, dropped = [], Counter()
    for record in records:
        vector = vectors.get(record.get("이미지파일") or "")
        if vector is None:
            dropped["이미지 벡터 없음"] += 1
        elif not record.get("유사군"):
            dropped["유사군 없음"] += 1
        elif photo_mark.is_photo(vector):
            dropped["사진"] += 1
        else:
            usable.append(record)
    usable.sort(key=lambda r: str(r["출원번호"]))
    apps = [nst.split_applicants(r.get("출원인") or "", aliases) for r in usable]
    goods = [frozenset(r["유사군"]) for r in usable]
    matrix = np.stack([np.asarray(vectors[r["이미지파일"]], dtype=np.float64) for r in usable])
    cosine = matrix @ matrix.T
    counts = Counter()
    scored: list[tuple[float, str, str]] = []
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            if pf.goods_similarity(goods[i], goods[j]) < SAME_GOODS_MIN:
                continue
            counts["겹침 ≥ 0.5"] += 1
            a, b = str(usable[i]["출원번호"]), str(usable[j]["출원번호"])
            if apps[i] & apps[j]:
                counts["같은 출원인"] += 1
                continue
            if (a, b) in related:
                counts["심결 관계"] += 1
                continue
            if (a, b) in existing:
                counts["지금 쉬운 음성과 같음"] += 1
                continue
            scored.append((max(0.0, float(cosine[i, j])), a, b))
    pool = bottom_share(scored)
    picked = sample_pairs(pool, n)
    by_appno = {str(r["출원번호"]): r for r in usable}
    dist = pf.load_distinctiveness()
    rows = []
    for x2, a, b in picked:
        ra, rb = by_appno[a], by_appno[b]
        row = pf._easy_row("db", f"{KEY_PREFIX}:{a}|{b}", pf._db_name(ra),  # noqa: SLF001
                           pf._db_name(rb), frozenset(ra["유사군"]),  # noqa: SLF001
                           frozenset(rb["유사군"]), dist)
        row.update({"x2_whole": pf._fmt(x2), "has_image": 1,  # noqa: SLF001
                    "사진A": pf.photo_flag(False), "사진B": pf.photo_flag(False)})
        rows.append(row)
    x2s = [float(row["x2_whole"]) for row in rows]
    x4s = [float(row["x4"]) for row in rows]
    reuse = Counter(appno for _, a, b in picked for appno in (a, b))
    sources = Counter(by_appno[appno].get("수집_출처") or "기존 수집"
                      for _, a, b in picked for appno in (a, b))
    named = sum(1 for row in rows if row["x1"] != "")
    coincidental = sum(1 for row in rows if row["x1"] != "" and (
        float(row["x1"]) >= EASY_MAX_SCORE or float(row["x2_text"]) >= EASY_MAX_SCORE))
    report = {
        "DB": len(records), "쓸_수_있는_상표": len(usable), "뺀_상표": dict(dropped),
        "심결_관계": related_report, "쌍_거르기": dict(counts), "조건을_채운_쌍": len(scored),
        "하위_50%": len(pool),
        "하위_50%_이미지_유사도_상한": _round(pool[-1][0]) if pool else None,
        "조건을_채운_쌍_이미지_유사도": summary_stats([s for s, _, _ in scored]),
        "N": n, "뽑은_쌍": len(rows),
        "이미지_유사도": summary_stats(x2s), "업종_겹침": summary_stats(x4s),
        "업종_겹침_구간": dict(Counter("1" if v >= 1 else ("0.67–1" if v >= 0.67 else "0.5–0.67")
                                 for v in x4s)),
        "이름_축_있는_쌍": named, "우연_유사_기준_해당(보고만)": coincidental,
        "상표_출처(쌍의_양쪽)": dict(sources), "한_상표가_든_쌍_최대": max(reuse.values()),
        "서로_다른_상표": len(reuse)}
    return rows, report


def write_augmented(rows: list[dict], path: Path) -> dict:
    from scripts import pairs_features as pf

    original_path = pf.DEFAULT_BASE / "pairs_features_easy.csv"
    original = pf.read_csv(original_path)
    pf.write_csv(path, original + rows)
    head = original_path.read_bytes()
    written = path.read_bytes()
    return {"원본_행": len(original), "새_행": len(rows), "앞부분_원본과_같음": written[:len(head)]
            == head}


# ---- 2. 다시 학습 ------------------------------------------------------------------------------

def train_before(v13: dict, base: dict) -> dict:
    """지금 교차검증 재현(t2.train_once) — 반올림 계수가 배포 계수와 같아야 한다."""
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4
    from scripts import train_risk_model_v14_nameless as t2

    rows = t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY).rows
    result = t2.train_once(rows, v13)
    rounded = t2.rounded_nameless(result["design"], result["final"].blocks)
    same = {key: rounded[key]["coefficients"] == base[rm.NAMELESS_KEY][key]["coefficients"]
            for key in rounded}
    result["rows"] = rows
    result["재학습_같음"] = all(same.values())
    result["재학습_같음_집합별"] = same
    result["절편(재학습 → 배포)"] = {key: [rounded[key]["intercept"],
                                     base[rm.NAMELESS_KEY][key]["intercept"]] for key in rounded}
    return result


def train_after(easy_path: Path, v13: dict, base: dict) -> dict:
    """규칙 '다시_학습' — noname:x2_whole+x4 만(이름 있는 4벌·이미지만 집합 고정)."""
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4
    from scripts import train_risk_model_v14_nameless as t2

    dataset = t4.load_dataset(tr.DEFAULT_FEATURES, easy_path)
    rows = dataset.rows
    a = t4.arrays(rows)
    keys, choice = t4.choose_nameless_keys(rows, a, tr.MIN_PATTERN_MINORITY)
    if tuple(keys) != tuple(t4.NAMELESS_KEYS):
        raise ValueError(f"이름 없는 집합 구성이 다릅니다: {choice}")
    design = t4.Design(rows, structure="v1.4", nameless_keys=keys)
    floors = {axis: float(value) for axis, value in v13["coupling"]["floors"].items()}
    fixed = t2.fixed_named(design, v13)
    block = base[rm.NAMELESS_KEY][X_KEY]
    fixed[X] = (np.asarray([float(block["coefficients"][name]) for name in design.names[X]]),
                float(block["intercept"]))
    constraints = t2.build_constraints(design, floors)
    started = time.perf_counter()
    cv = t2.cv_nameless(design, a, constraints, fixed, folds=t4.FOLDS, repeats=t4.REPEATS,
                        seed=SEED)
    final = t2.fit(design, a, np.arange(len(rows)), constraints, fixed)
    rounded = t2.rounded_nameless(design, final.blocks)
    if (rounded[X_KEY]["coefficients"] != block["coefficients"]
            or rounded[X_KEY]["intercept"] != block["intercept"]):
        raise ValueError("고정한 이미지만 집합이 바뀌었습니다")
    counts = t4.block_counts(design, a["y"], a["fit_weight"], a["easy"])
    return {"rows": rows, "arrays": a, "design": design, "cv": cv, "final": final,
            "entry": rounded[XG_KEY], "summary": dataset.summary, "counts": counts[XG],
            "constraints": len(constraints), "seconds": round(time.perf_counter() - started, 1),
            "optimizer": {"solver": final.solver, "success": bool(final.success),
                          "kkt_residual": _round(final.kkt_residual, 9),
                          "min_slack": _round(final.min_slack, 9),
                          "cv_수렴_실패": cv["수렴_실패"], "cv_최소_여유": cv["최소_여유"]}}


def oof_auc(before: dict, after: dict) -> dict:
    """학습 진단 (가) — noname:x2_whole+x4 학습 행 중 심결 행."""
    from scripts import train_risk_model_v14 as t4

    out = {}
    for label, result in (("지금", before), ("새", after)):
        design, a, cv = result["design"], result["arrays"], result["cv"]
        index = np.flatnonzero(a["trial"] & design.mask[XG])
        y, w = a["y"][index], a["eval_weight"][index]
        ones = np.ones(index.size)
        figure = cv["per_block_figure"][XG][index]
        own = cv["per_block"][XG][index]
        out[label] = {"행": int(index.size), "유사": int(y.sum()),
                      "AUC(도형계)": _round(t4.weighted_auc(figure, y, ones)),
                      "AUC(도형계, 사건 가중)": _round(t4.weighted_auc(figure, y, w)),
                      "AUC(행의 유형)": _round(t4.weighted_auc(own, y, ones))}
    return out


def oof_precision(before: dict, after: dict, models: dict[str, dict]) -> dict:
    """채택_4 — 이름 없는 판단의 위험 정밀도(OOF, 도형계로 본 값)."""
    rows_b, rows_a = before["rows"], after["rows"]
    design_b, a_b = before["design"], before["arrays"]
    index = np.flatnonzero(a_b["trial"] & design_b.mask[X])
    keys = [(r["심판번호"], r.get("상대번호"), r.get("쌍키")) for r in rows_b]
    if any(keys[i] != (rows_a[i]["심판번호"], rows_a[i].get("상대번호"), rows_a[i].get("쌍키"))
           for i in index):
        raise ValueError("지금·새 학습 행의 심결 행 순서가 다릅니다")
    floor = float(models["지금"]["coupling"]["floors"]["x4"])
    out = {"행": int(index.size)}
    labels = [int(a_b["y"][i]) for i in index]
    for label, model in models.items():
        xg_cv = before["cv"] if label == "지금" else after["cv"]
        grades = []
        for i in index:
            x2 = float(rows_b[i]["x2_whole"])
            alone = rm.grade_for(float(before["cv"]["per_block_figure"][X][i]),
                                 rm.grade_thresholds_for(model, X))
            if design_b.mask[XG][i]:
                grade = rm.grade_for(float(xg_cv["per_block_figure"][XG][i]),
                                     rm.grade_thresholds_for(model, XG))
                if float(rows_b[i]["x4"]) >= floor:
                    grade = max(grade, alone, key=rm.GRADES.index)
            else:
                grade = alone
            tau = (model.get("figure_rule") or {}).get("threshold")
            if tau is not None and x2 >= float(tau) and not ns.at_least(grade, REVIEW):
                grade = REVIEW
            grades.append(grade)
        out[label] = {"등급": ns.distribution(grades), **precision_check(grades, labels)}
    out["통과"] = out["새"]["통과"]
    return out


# ---- 3. 검색 -----------------------------------------------------------------------------------

def named_searches(context: dict, models: dict[str, dict], limit: int | None) -> dict:
    """이름 있는 질의 쪽 — 1차 시도 대조군 확인용 100 × 네 방식, 표본 A 검색 184."""
    ms = context["ms"]
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    a_by_key = {query.key: query for query in context["A"]}

    def pair(**inputs) -> dict:
        out = {}
        for label, model in models.items():
            with ns.using_model(ms, model):
                out[label] = ns._summary(ms.search_pool(**inputs))  # noqa: SLF001
        return out

    controls = []
    for item in control["대조군"]["이름"]["확인용"][:limit]:
        image = context["service"](a_by_key[item["이미지"]].path.read_bytes())
        goods = sorted(item["유사군"]) or None
        row = {"이름": item["이름"], "이미지": item["이미지"], "방식": {}}
        for label, with_image, with_goods in CONTROL_MODES:
            row["방식"][label] = pair(name=item["이름"], image=image if with_image else None,
                                      goods_codes=goods if with_goods else None)
        controls.append(row)
    sample_a = []
    for query in context["A"][:limit]:
        image = context["service"](query.path.read_bytes())
        sample_a.append({"질의": query.key, "업종": bool(query.goods),
                         "이름+이미지": pair(image=image, name=query.name,
                                          goods_codes=sorted(query.goods) or None)})
    return {"대조군": controls, "표본A": sample_a}


def named_tables(searches: dict) -> dict:
    controls, sample_a = searches["대조군"], searches["표본A"]
    out = {"대조군_확인용": {}, "표본A": {}}
    for label, _, _ in CONTROL_MODES:
        before = [row["방식"][label]["지금"]["전체"] for row in controls]
        after = [row["방식"][label]["새"]["전체"] for row in controls]
        out["대조군_확인용"][label] = {
            "지금": ns.distribution(before), "새": ns.distribution(after),
            "검토_권장_이상": {label_: (sum(ns.at_least(g, REVIEW) for g in grades) / len(grades)
                                     if grades else None)
                         for label_, grades in (("지금", before), ("새", after))},
            "바뀐_질의": sum(1 for b, a in zip(before, after) if b != a)}
    for kind in ("업종 있음", "업종 없음", "전체"):
        rows = [row for row in sample_a
                if kind == "전체" or row["업종"] == (kind == "업종 있음")]
        before = [row["이름+이미지"]["지금"]["전체"] for row in rows]
        after = [row["이름+이미지"]["새"]["전체"] for row in rows]
        out["표본A"][kind] = {"질의": len(rows), "지금": ns.distribution(before),
                             "새": ns.distribution(after),
                             "바뀐_질의": [row["질의"] for row in rows
                                       if row["이름+이미지"]["지금"]["전체"]
                                       != row["이름+이미지"]["새"]["전체"]][:30]}
    return out


def scenario_fidelity(before: dict) -> dict:
    with gzip.open(SAVED_SCENARIOS, "rt", encoding="utf-8") as handle:
        saved = json.load(handle)["시나리오"]["후"]
    differ = [key for key, item in saved.items()
              if item.get("전체") != before.get(key, {}).get("전체")
              or [c["id"] for c in item.get("상위", [])]
              != [c["id"] for c in before.get(key, {}).get("상위", [])]]
    return {"견준_시나리오": len(saved), "다른_것": differ, "같음": not differ}


def check_1(found: dict, thresholds: dict, named: dict) -> dict:
    """채택_1 (가) 대조군 확인용 — noname:x2_whole+x4 만, (나) 이름 있는 대조군."""
    values = found["값"][XG]["확인용"]
    block, passed = {}, True
    for grade, share in TARGETS.items():
        cut = float(thresholds[grade])
        observed = ns.rate_at_least(values, cut)
        ok = observed is not None and observed <= share + 1e-12
        refit = None
        if not ok and values:
            refit, _, _ = first.fit_cut(values, share)
            ok = refit is not None and refit - cut <= TOLERANCE + 1e-12
        block[grade] = {"기준": cut, "목표": share, "확인용_비율": observed, "n": len(values),
                        "95%": ns.cluster_bootstrap(found["묶음"][XG]["확인용"],
                                                    lambda v, c=cut: ns.rate_at_least(v, c)),
                        "넘을_때_확인용_맞춘_값": refit, "통과": ok}
        passed = passed and ok
    return {"이미지+업종": block, "이름_있는_대조군": named,
            "통과": passed and named["통과"]}


def check_5(model: dict, queries: list[dict]) -> dict:
    floor = float(model["coupling"]["floors"]["x4"])
    thresholds = {key: rm.grade_thresholds_for(model, key) for key in (X, XG)}
    blocks = {"base": model, **(model.get("patterns") or {}),
              **{rm.NAMELESS_PREFIX + k: v for k, v in (model.get(rm.NAMELESS_KEY) or {}).items()}}
    monotone = {key: len(rm.monotone_violations(block["coefficients"]))
                for key, block in blocks.items() if "coefficients" in block}
    coupling = rm.coupling_violations(model)
    pairs = {"하한_이상": 0, "하한_이상_내려감": 0, "하한_아래": 0, "하한_아래_내려감": 0}
    for item in queries:
        alone = {c["id"]: c["x2"] for entry in item["검색"] if entry["방식"] == "이미지만"
                 for c in entry["풀"] if c["x2"] is not None}
        for entry in item["검색"]:
            if entry["방식"] != "이미지+업종":
                continue
            for c in entry["풀"]:
                if c["id"] not in alone or c["x4"] is None or c["x4"] <= 0:
                    continue
                down = int(rm.GRADES.index(ns.final_grade(c["x2"], c["x4"], model))
                           < rm.GRADES.index(ns.final_grade(alone[c["id"]], None, model)))
                bucket = "하한_이상" if c["x4"] >= floor else "하한_아래"
                pairs[bucket] += 1
                pairs[f"{bucket}_내려감"] += down
    grid = ns.grid_violations(model, goods_floor=True)
    grid_plain = ns.grid_violations(model, goods_floor=False)
    ordered = {key: ns.ordered(t) for key, t in thresholds.items()}
    passed = (all(ordered.values()) and not any(monotone.values()) and not coupling
              and grid == 0 and pairs["하한_이상_내려감"] == 0)
    return {"순서": ordered, "단조_위반": monotone, "결합_위반": len(coupling),
            "결합_위반_예": coupling[:5], "격자_내려감": grid,
            "격자_내려감(업종_하한_없이, 보고만)": grid_plain, "실제_쌍": pairs, "통과": passed}


def command_run(args) -> int:
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14_nameless as t2

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
    if base.get("version") != BASE_VERSION:
        print("거절: 기준 모델이 v1.4.3 이 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    args.out_dir.mkdir(parents=True, exist_ok=True)
    limit = 4 if args.smoke else None
    control_limit = 12 if args.smoke else None  # 질의가 적으면 10%·2% 지점이 동점으로 같아진다
    repeat = REPEAT
    timing: dict[str, float] = {}

    def tick(name: str, began: float) -> None:
        timing[name] = round(time.perf_counter() - began, 1)
        print(f"  {name} {timing[name]}초", flush=True)

    results: dict = {"설정_sha256": frozen["설정_sha256"],
                     "스크립트_sha256(고정 때)": frozen["스크립트_sha256"],
                     "스크립트_sha256(잴 때)": first.file_sha256(Path(__file__)),
                     "모델": BASE_VERSION, "스모크": bool(args.smoke)}

    def stop(reason: str) -> int:
        results.update(채택=False, 멈춤=reason, 시간_s=timing, 끝=_now())
        paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                    encoding="utf-8")
        paths["report"].write_text(report_text(results), encoding="utf-8")
        print(f"멈춤: {reason}", file=sys.stderr)
        return EXIT_STOP

    # 1. 같은 업종 음성
    began = time.perf_counter()
    n = easy_goods_count(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY)
    negatives, negative_report = build_negatives(n)
    from scripts import pairs_features as pf

    pf.write_csv(paths["negatives"], negatives)
    augmented = write_augmented(negatives, paths["easy"])
    negative_report["파일"] = {"음성_sha256": first.file_sha256(paths["negatives"]),
                             "늘린_쉬운_음성_sha256": first.file_sha256(paths["easy"]),
                             **augmented}
    results["같은_업종_음성"] = negative_report
    tick("같은 업종 음성", began)
    if not augmented["앞부분_원본과_같음"]:
        return stop("늘린 쉬운 음성 파일의 앞부분이 원본과 다름")

    # 2. 다시 학습
    began = time.perf_counter()
    before = train_before(v13, base)
    results["지금_재현"] = {"재학습_같음": before["재학습_같음"],
                        "집합별": before["재학습_같음_집합별"],
                        "절편(재학습 → 배포)": before["절편(재학습 → 배포)"]}
    if not before["재학습_같음"]:
        return stop("지금 교차검증 재현의 계수가 배포 계수와 다름")
    after = train_after(paths["easy"], v13, base)
    coefficients = goods_block(base, after["entry"])
    repaired, repair = repair_coupling(coefficients)
    entry = {"coefficients": repaired[rm.NAMELESS_KEY][XG_KEY]["coefficients"],
             "intercept": repaired[rm.NAMELESS_KEY][XG_KEY]["intercept"]}
    old_block = base[rm.NAMELESS_KEY][XG_KEY]
    results["학습"] = {
        "데이터": {"심결": after["summary"]["심결_행(학습)"],
                 "쉬운_음성": after["summary"]["쉬운_음성"],
                 "사진_규칙": after["summary"]["사진_규칙"]},
        "이미지+업종_학습_행": after["counts"], "제약": after["constraints"],
        "최적화": after["optimizer"], "반올림_보정": repair, "걸린_시간_s": after["seconds"],
        "계수": {"지금": {"coefficients": old_block["coefficients"],
                        "intercept": old_block["intercept"]}, "새": entry},
        "OOF_AUC": oof_auc(before, after)}
    tick("다시 학습", began)
    if not repair["고침"]:
        return stop("반올림 뒤 결합 위반을 이미지+업종 절편만으로 고치지 못함")

    # 3. 엔진·검산
    began = time.perf_counter()
    context = ns._context(BASE_MODEL_PATH)  # noqa: SLF001
    ms = context["ms"]
    if ms.state.model.get("version") != BASE_VERSION:
        return stop("엔진이 적재한 모델이 v1.4.3 이 아님")
    lo.memo_ocr(ms)
    scenario_runs = lo.scenarios(context, {"지금": ms.state.model})
    fidelity = scenario_fidelity(scenario_runs["지금"])
    results["검산_시나리오"] = fidelity
    tick("엔진·검산", began)
    if not fidelity["같음"]:
        return stop("바꾸기 전 시나리오가 저장값과 다름")

    # 4. 대조군(지금) → 새 계수의 M_q → 기준
    began = time.perf_counter()
    control_record = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    queries = ns.control_queries(control_record["대조군"], control_limit, repeat)
    ns.run_control(context, queries, {"지금": ms.state.model})
    tick("대조군(지금)", began)
    found = ns.query_maxima(queries, repaired)
    fitted = fit_goods_thresholds(found["값"][XG]["기준용"],
                                  rm.grade_thresholds_for(base, XG)[CAUTION])
    thresholds = fitted["기준"]
    results["기준"] = {"맞춤": fitted, "지금_기준": dict(rm.grade_thresholds_for(base, XG))}
    if None in thresholds.values() or not ns.ordered(thresholds):
        results["채택_5"] = {"순서": {XG: False}, "통과": False}
        return stop("새 기준의 순서(주의 < 검토 권장 < 위험)가 맞지 않음 — 채택 ⑤ 미달")
    meta_counts = {k: after["counts"][k] for k in (
        "n", "n_심결", "n_쉬운_음성", "유사", "비유사", "가중_유사", "가중_비유사",
        "자기_패턴_행", "자기_패턴_심결")}
    candidate = goods_block(base, entry, thresholds, meta_counts)
    candidate["version"] = NEW_VERSION
    candidate["meta"].setdefault("nameless", {})["goods_shortcut"] = {
        "calibrated_at": "2026-11-23", "derived_from": base["version"],
        "rule_sha256": frozen["설정_sha256"], "script": "ml/scripts/goods_shortcut.py",
        "negatives": {"n": len(negatives), "sha256": negative_report["파일"]["음성_sha256"],
                      "image_similarity": negative_report["이미지_유사도"],
                      "goods_overlap": negative_report["업종_겹침"]},
        "training": {"fixed": ["이름 있는 4벌(v1.3)", X], "optimizer": after["optimizer"],
                     "rounding_repair": repair["걸음"], "counts": meta_counts},
        "thresholds": {"method": (rm.SEARCH_THRESHOLDS_METHOD + " — 대조군(표본 A 저유사 이미지 "
                                  "46 × 업종 세트 10, 질의 단위·무관한 후보 최고 위험도), "
                                  "goods_shortcut.py"),
                       "fitted": thresholds, "k": fitted["k"], "n": fitted["n"],
                       "caution_refit": fitted["주의_다시_맞춤"],
                       "previous": dict(rm.grade_thresholds_for(base, XG))},
        "previous_block": {"coefficients": old_block["coefficients"],
                           "intercept": old_block["intercept"]},
        "adopted": None}
    rm.validate_model({**candidate, "version": BASE_VERSION})
    models = {"지금": ms.state.model, "새": candidate}
    results["기준"]["95%"] = {grade: ns.cluster_bootstrap(
        found["묶음"][XG]["기준용"], lambda v, s=share: first.fit_cut(v, s)[0])
        for grade, share in TARGETS.items()}

    # 5. 새 모델로 다시 검색
    began = time.perf_counter()
    a_by_key = {query.key: query for query in context["A"]}
    for item in queries:
        image = context["service"](a_by_key[item["키"]].path.read_bytes())
        codes_of = {preset["id"]: sorted(preset["유사군"]) for preset in item["업종"]}
        for entry_ in item["검색"]:
            codes = codes_of.get(entry_["업종_id"]) if entry_["방식"] == "이미지+업종" else None
            with ns.using_model(ms, candidate):
                entry_["새"] = ns._summary(ms.search_pool(image=image,  # noqa: SLF001
                                                          goods_codes=codes))
    tick("대조군(새)", began)
    began = time.perf_counter()
    with gzip.open(ns.POSITIVES, "rt", encoding="utf-8") as handle:
        positives = json.load(handle)["양성"][:limit]
    logo = ns.same_logo(context, positives, models)
    tick("같은 로고", began)
    began = time.perf_counter()
    named = named_searches(context, models, limit)
    tick("이름 있는 질의", began)
    began = time.perf_counter()
    scenario_runs.update(lo.scenarios(context, {"새": candidate}))
    tick("시나리오(새)", began)

    # 6. 채택 조건·보고
    began = time.perf_counter()
    case_ids = {query.key.split(":")[1] for query in context["A"]}
    named_rows = named["대조군"]
    results["채택_1"] = check_1(found, thresholds, check_named(named_rows))
    results["채택_2"] = ns.check_2(logo)
    results["채택_3"] = ns.cited_pairs(case_ids, models)
    results["채택_4"] = oof_precision(before, after, models)
    results["채택_5"] = check_5(candidate, queries)
    monotone_rows = t2.row_monotonicity(after["rows"], candidate)
    results["학습"]["결합_제약"] = {
        "적합_최소_여유": after["optimizer"]["min_slack"], "반올림_보정": repair["걸음"],
        "학습_행_단조성_위반": monotone_rows["위반_합계"],
        "적재_검증_위반": len(rm.coupling_violations(candidate))}
    results["학습"]["업종_차이"] = industry_gap(queries, models)
    results["전후"] = {"대조군": ns.before_after(queries), "이름_있는_질의": named_tables(named),
                     "같은_로고": results["채택_2"], "표본A_인용상표": results["채택_3"]}
    results["시나리오"] = lo.scenario_table({"전": scenario_runs["지금"],
                                          "후": scenario_runs["새"]})
    results["새_기준"] = thresholds
    results["채택"] = all(results[f"채택_{i}"]["통과"] for i in range(1, 6))
    candidate["meta"]["nameless"]["goods_shortcut"]["adopted"] = results["채택"]
    tick("채택 조건", began)
    results["시간_s"] = timing
    results["걸린_시간_s"] = round(time.perf_counter() - started, 1)
    results["끝"] = _now()
    paths["candidate"].write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
    with gzip.open(paths["searches"], "wt", encoding="utf-8") as handle:
        json.dump({"대조군": queries, "같은_로고": logo, "이름_있는_질의": named,
                   "시나리오": scenario_runs}, handle, ensure_ascii=False)
    paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    paths["report"].write_text(report_text(results), encoding="utf-8")
    print(json.dumps({"채택": results["채택"], "새_기준": thresholds,
                      "새_계수": entry}, ensure_ascii=False))
    print(f"→ {paths['results']}\n→ {paths['report']}")
    return 0 if results["채택"] else EXIT_STOP


# ---- 2·3. 적용·확인 ---------------------------------------------------------------------------

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
    """기본 모델을 v1.4.4 로 바꾼 뒤 — 기본 엔진으로 다시 돌려 후보 실행과 같은지."""
    paths = _paths(args.out_dir)
    if _check_frozen(paths, model_may_change=True) is None:
        return EXIT_REFUSED
    if rm.MODEL_VERSION != NEW_VERSION or rm.resolve_model_path() != NEW_MODEL_PATH:
        print("거절: 서비스 기본 모델이 v1.4.4 가 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    with gzip.open(paths["searches"], "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    context = ns._context(NEW_MODEL_PATH)  # noqa: SLF001
    ms = context["ms"]
    candidate = json.loads(paths["candidate"].read_text(encoding="utf-8"))
    if (ms.state.model.get("version") != NEW_VERSION
            or ms.state.model[rm.NAMELESS_KEY] != candidate[rm.NAMELESS_KEY]):
        print("거절: 엔진이 적재한 모델이 후보 v1.4.4 와 다릅니다", file=sys.stderr)
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
            mismatch["대조군"] += int(not same(got, entry["새"]))
    with gzip.open(ns.POSITIVES, "rt", encoding="utf-8") as handle:
        positives = {item["출원번호"]: item for item in json.load(handle)["양성"]}
    rows = [positives[row["출원번호"]] for row in saved["같은_로고"]["행"]]
    logo = ns.same_logo(context, rows, {"기본": ms.state.model})
    for row, old in zip(logo["행"], saved["같은_로고"]["행"]):
        for mode in ("업종 없음", "같은 업종"):
            checked["같은_로고"] += 1
            got, want = row["방식"][mode]["기본"], old["방식"][mode]["새"]
            mismatch["같은_로고"] += int(got["성공"] != want["성공"] or got["1위"] != want["1위"])
    again = named_searches(context, {"새": ms.state.model}, None)
    for new, old in zip(again["대조군"], saved["이름_있는_질의"]["대조군"]):
        for label, _, _ in CONTROL_MODES:
            checked["이름_있는_대조군"] += 1
            mismatch["이름_있는_대조군"] += int(not same(new["방식"][label]["새"],
                                                    old["방식"][label]["새"]))
    for new, old in zip(again["표본A"], saved["이름_있는_질의"]["표본A"]):
        checked["표본A"] += 1
        mismatch["표본A"] += int(not same(new["이름+이미지"]["새"], old["이름+이미지"]["새"]))
    default = lo.scenarios(context, {"기본": ms.state.model})["기본"]
    after = saved["시나리오"]["새"]
    scenario_diff = [key for key, item in default.items()
                     if item.get("전체") != after.get(key, {}).get("전체")
                     or [c["id"] for c in item.get("상위", [])]
                     != [c["id"] for c in after.get(key, {}).get("상위", [])]]
    verify = {"모델": ms.state.model["version"], "다시_돌린_질의": dict(checked),
              "불일치": dict(mismatch), "시나리오_다른_것": scenario_diff,
              "통과": not any(mismatch.values()) and not scenario_diff,
              "걸린_시간_s": round(time.perf_counter() - started, 1), "끝": _now()}
    paths["verify"].write_text(json.dumps(verify, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")
    print(json.dumps(verify, ensure_ascii=False))
    return 0 if verify["통과"] else EXIT_STOP


# ---- 보고 --------------------------------------------------------------------------------------

def report_text(results: dict) -> str:
    lines = ["# 이름 없는 '이미지+업종' 판단의 업종 지름길 — 보고", "",
             f"- 설정 sha256 `{results['설정_sha256']}` · 스크립트 고정 "
             f"`{results['스크립트_sha256(고정 때)']}` · 잴 때 "
             f"`{results['스크립트_sha256(잴 때)']}`",
             f"- 스모크 {results['스모크']} · 채택 **{results.get('채택')}** · 멈춤 "
             f"{results.get('멈춤')}", ""]
    for key in ("같은_업종_음성", "지금_재현", "학습", "기준", "검산_시나리오"):
        if key in results:
            lines += [f"## {key}", "", "```",
                      json.dumps(results[key], ensure_ascii=False)[:3500], "```", ""]
    for i in range(1, 6):
        key = f"채택_{i}"
        if key in results:
            lines += [f"## {key} — {results[key].get('통과')}", "", "```",
                      json.dumps(results[key], ensure_ascii=False)[:3000], "```", ""]
    if "전후" in results:
        lines += ["## 전후 — 대조군 전체 등급", ""]
        for name, block in results["전후"]["대조군"].items():
            lines.append(f"- {name}: 지금 {block.get('지금')} → 새 {block.get('새')}")
        lines += ["", "## 전후 — 이름 있는 질의", "", "```",
                  json.dumps(results["전후"]["이름_있는_질의"], ensure_ascii=False)[:3000],
                  "```", ""]
    if "시나리오" in results:
        lines += ["## 시나리오 16종", "", "| 키 | 제목 | 지금 | 새 | 1위(지금 → 새) |",
                  "|---|---|---|---|---|"]
        for row in results["시나리오"]:
            if row.get("건너뜀"):
                lines.append(f"| {row['키']} | {row['제목']} | — | — | — |")
                continue
            lines.append(f"| {row['키']} | {row['제목']} | {row['전']['grade']} "
                         f"{row['전']['prob']} | {row['후']['grade']} {row['후']['prob']} | "
                         f"{row['전_1위']} → {row['후_1위']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("freeze", "run", "apply", "verify"))
    parser.add_argument("--out-dir", type=Path, default=TRIALS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--smoke", action="store_true",
                        help=("시험 실행 — 대조군 이미지 반마다 12·양성 4·이름 있는 질의 4"
                              "(--out-dir 를 따로)"))
    args = parser.parse_args(argv)
    if args.smoke and args.out_dir.resolve() == TRIALS.resolve():
        print("거절: --smoke 는 --out-dir 를 따로 주세요", file=sys.stderr)
        return EXIT_REFUSED
    return {"freeze": command_freeze, "run": command_run, "apply": command_apply,
            "verify": command_verify}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
