"""이름 있는 판단 중 업종이 들어가는 두 벌 — x4(이름+업종)·x2_whole+x4(이름+이미지+업종) — 에
곱하기 항을 넣어 다시 학습한다(4-b, 2026-11-24, 지시로 고정). 4-a(이름 없는 이미지+업종, v1.4.5)와
같은 원칙 — 업종의 효과는 표장이 닮은 만큼만. 변형 L(표장 항 × 업종)·S(짝 위험도 × 업종)를 v1.4
절차로 학습하고 같은 조건으로 잰다. 업종 상한(업종이 다르면 짝 판단 이하)도 함께 둔다. KIPRIS 호출
0.

    ml/venv/bin/python ml/scripts/named_goods_product.py freeze   # 0. 규칙·입력 해시
    ml/venv/bin/python ml/scripts/named_goods_product.py run      # 1. 음성·학습·기준·검색·①–⑦
    ml/venv/bin/python ml/scripts/named_goods_product.py apply    # 2. 고른 변형만 v1.4.6 JSON
    ml/venv/bin/python ml/scripts/named_goods_product.py verify   # 3. 기본 모델 바꾼 뒤

전·후 = 같은 프로세스에서 엔진 계수만 v1.4.5 ↔ 변형. 산출(비공개):
ml/data/trials/named_goods_product_{rule,results,candidate_L,candidate_S,verify}.json·
_negatives.csv·_easy_augmented.csv·_searches.json.gz·_report.md. 고정본과 다르면 거절(종료
코드 4), 검산 불일치·둘 다 미달이면 3. --smoke 는 학습까지 일부 표본으로만 돌린다(채택 지표는
본 실행에서 처음 본다).
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import random
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

from scipy.special import expit  # noqa: E402
from src.model import risk_model as rm  # noqa: E402

from scripts import goods_shortcut as gs  # noqa: E402
from scripts import logo_floor_image_only as lo  # noqa: E402
from scripts import named_search_thresholds as first  # noqa: E402
from scripts import nameless_shared_threshold as ns  # noqa: E402

TRIALS = ML_ROOT / "data" / "trials"
STEM = "named_goods_product"
EXIT_STOP = 3
EXIT_REFUSED = 4
CAUTION, REVIEW, RISK = "주의", "검토 권장", "위험"
SETS = ("x4", "x2_whole+x4")
PAIR = {"x4": "base", "x2_whole+x4": "x2_whole"}
MODE_OF = {"x4": "이름+업종", "x2_whole+x4": "이름+이미지+업종"}
NO_GOODS_MODE = {"이름+업종": "이름만", "이름+이미지+업종": "이름+이미지"}
MODES = (("이름만", False, False), ("이름+업종", False, True), ("이름+이미지", True, False),
         ("이름+이미지+업종", True, True))
VARIANTS = ("L", "S")
SEED = 0
TARGETS = {REVIEW: 0.10, RISK: 0.02}
TOLERANCE = 0.0224
SAME_GOODS_MIN = 0.5
NAME_SHARE = 0.5
IMAGE_SHARE = 0.5
KEY_PREFIX = "namedgoods"
SAME_NAME_N = 200
SAME_NAME_MIN = 0.95
CITED_DROP_MAX = 0.05
PRECISION_MIN = 0.70
CHANGE_MIN_ROWS = 5
AUC_DROP_MAX = 0.05
PRODUCT_PRIOR_MU = 0.0
SIMILARITY_LEVELS = (0.3, 0.5, 0.7, 0.9)
NAME_GRID = {"x4": 0.05, "x2_whole+x4": 0.1}
X2_GRID = 0.1
X4_GRID = tuple(round(0.002 * i, 3) for i in range(13)) + (0.0252, 0.03, 0.05, 0.1, 0.2, 0.3,
                                                            0.5, 0.75, 1.0)
LEVELS = ("문자", "도형")
SMOKE = {"학습_비율": 0.35, "DB_상표": 300, "음성": 60, "대조군_이름": 6, "같은_이름": 6,
         "표본A": 6}
BASE_VERSION = "risk_model_v1.4.5"
NEW_VERSION = "risk_model_v1.4.6"
BASE_MODEL_PATH = REPO_ROOT / "shared" / "model" / "risk_model_v1.4.5.json"
NEW_MODEL_PATH = REPO_ROOT / "shared" / "model" / "risk_model_v1.4.6.json"
SAVED_V145 = TRIALS / "goods_product_searches.json.gz"  # v1.4.5(변형 L) 실행 — 시나리오·대조군 풀
DISPLAY_TOP = first.DISPLAY_TOP
MAIN_TERMS = ("x1_d", "x2_text_d", "x3_d", "x2_whole", "x4")

# 규칙(이 지시로 고정 — 실행 전에 해시를 남기고 결과를 보고 바꾸지 않는다) ------------------------
RULE = {
    "구조": (
        "바꾸는 것은 이름 있는 계수 집합 x4(이름+업종, 짝 base)와 x2_whole+x4(이름+이미지+업종, "
        "짝 x2_whole) 둘. 지금(v1.4.5 = v1.3 계수) 두 벌의 항: "
        "x1_d·x2_text_d·x3_d·any_no_distinctive·x1_d×문자계·x1_d×any_no_distinctive(+ "
        "x2_whole·x2_whole×도형계)·x4. 변형 L(선형 곱): 그 집합의 표장 항(이름 축 "
        "x1_d·x2_text_d·x3_d·x1_d×문자계·x1_d×any_no_distinctive, x2_whole+x4 는 이미지 항 "
        "x2_whole·x2_whole×도형계도 — 모델이 쓰는 꼴 그대로, 요부 플래그 any_no_distinctive "
        "본체는 표장 유사가 아니라 뺌)마다 x4 를 곱한 항을 더한다. 변형 S(짝 위험도 곱): 업종 "
        "없는 짝 집합의 위험도(0–1, 짝 계수 v1.4.5 고정) × x4 항 "
        "하나(pair(base)×x4·pair(x2_whole)×x4)를 더한다."),
    "제약": (
        "두 변형 공통: (a) 곱하기 항 계수마다 ≥ 0, 업종 단독 x4 ≥ 0 (b) x4 = 0 에서 그 집합 로짓 "
        "≤ 짝 집합 로짓 — 짝 입력의 결합 꼭짓점(rm.coupling_vertices: 이름 축 0·1, 관념 게이트, "
        "요부 유무, 문자계·도형계, x2_whole+x4 는 이미지 0·1) 모두에서(x4 = 0 이면 곱하기 항이 "
        "사라져 축에 다중선형이므로 모든 값에서 성립) (c) v1.4 절차의 다른 제약 그대로 — "
        "단조(tr.monotone_constraints), 이미지 결합(x4 → x2_whole+x4, 이미지 = 하한 0.3487 에서 "
        "이상, x4 입력 꼭짓점), 같은 이름(이름 있는 x2_whole+x4 에 같은 이름을 더한 로짓 ≥ 이름 "
        "없는 x2_whole+x4(v1.4.5) 로짓, 이름 없는 꼭짓점 × 요부 둘). 위험도 수준의 업종 결합(짝 "
        "→ 그 집합, x4 = 0.0252 에서 이상)은 뺀다 — 대신 등급 규칙: 업종이 겹치면(x4 ≥ 0.0252) "
        "최종 등급 ≥ 짝 판단의 등급(이름 있는 업종 하한 goods_floor_named, 계수 JSON 의 그 집합 "
        "goods_rule)과 업종 상한(아래 '업종_상한'). 변형 S 의 짝 위험도 항은 꼭짓점 값(짝 계수 "
        "고정이라 상수)으로 걸어 제약이 계수에 선형이다 — (b)·단조는 정확, 이미지 결합·같은 "
        "이름은 꼭짓점에서만 걸리므로 안쪽은 채택_5 의 격자로 본다."),
    "업종_상한": (
        "업종이 다르면(x4 < 결합 하한 0.0252) 업종 집합의 최종 등급 ≤ 업종 없는 짝 판단의 등급 — "
        "이름 없는 이미지+업종(짝 이미지만)과 이번 두 벌 모두. 계수 JSON 최상위 "
        "goods_cap.enabled 로 켠다(학습 제약은 겹침 0 에만). 변형 후보에 켠다. v1.4.5 에 켰을 때 "
        "등급이 바뀌는 수는 따로 보고만(이름 없는 쪽 — 4-a 실행의 대조군·표본 A 풀과 시나리오, "
        "이름 있는 쪽 — 이 실행의 지금 검색)."),
    "학습": (
        "v1.4 2차 학습 절차: t4.load_dataset(학습 특징, 쉬운 음성 — 변형은 지금 쉬운 음성 + 새 "
        "음성)(사진 규칙·사건 가중 상한 3·쉬운 음성 가중 0.5), t4.Design(v1.4) 에 두 벌의 항을 "
        "변형대로 바꾸고 고정 집합의 항은 그 JSON 그대로(이름 있는 base·x2_whole = v1.4.5, 이름 "
        "없는 두 벌 = v1.4.5 — 곱하기 항 포함), 설계 값은 rm.design_vector(짝 위험도 항은 v1.4.5 "
        "짝 계수로), 사전분포 σ 1.0(기존 항 tr.PRIOR_MU, 곱하기 항·짝 위험도 항 μ 0 — 4-a 와 "
        "같게), 교차검증 5겹 × 3반복(tr.folds_for(y, 묶음, seed 0 + 반복)), 전체 적합 "
        "t4.fit_joint. 반올림 넷째 자리(음수가 된 본체 항·곱하기 항은 0, x1 본체 + 교호작용 < 0 "
        "이면 교호작용을 0.0001 씩 올림, x2 본체 + ×도형계 < 0 이면 ×도형계를 올림), 반올림이 "
        "만든 적재 결합 위반은 절편으로 고친다 — (b) 넘침·이미지 결합 부족은 그 집합(이미지 "
        "결합은 x4)의 절편을 0.0001 씩 내리고, 같은 이름 부족은 x2_whole+x4 절편을 올림(못 "
        "고치면 멈춤)."),
    "지금_재현": (
        "채택_4·채택_7 의 '지금' OOF: 지금 구조(곱하기 항 없음, 업종 결합 x4 = 0.0252 에서 짝 "
        "이상, 이미지 결합·같은 이름·단조)를 지금 데이터(학습 특징 + 지금 쉬운 음성)로 같은 "
        "절차·같은 겹으로 다시 학습한 OOF(그 계수는 보고만 — 배포 v1.4.5 의 두 벌은 v1.3 "
        "학습(1차 314행) 계수라 같지 않다). 그 밖의 '지금'은 배포 v1.4.5 를 같은 방법으로 잰 값."),
    "새_음성": (
        "DB 상표(kipris_metadata.json) 중 상표명(한글명 > 영문명)과 유사군이 있는 것의 "
        "쌍(출원번호 순, seed 0): 업종 겹침(유사군 자카드) ≥ 0.5, 다른 출원인(출원인 칸 '|' "
        "분리·정규화 + 별칭 표), 심결 관계 없음(goods_shortcut.trial_related_pairs), 지금 쉬운 "
        "음성과 같은 쌍 아님, 이름 축 (pairs_features.name_axes)이 있는 쌍 → 이 쌍들(P) 중 이름 "
        "축 합(x1_d + x2_text_d, 두 이름 모두 관념이 있으면 + x3_d)이 하위 50%(합·출원번호 "
        "오름차순 앞 ⌊n/2⌋), 그리고 두 쪽 모두 이미지(색인 벡터)가 있으면 그 이미지 유사도(CLIP "
        "코사인)도 P 중 두 쪽 이미지가 있는 쌍의 하위 50%(같은 식) → 그 안에서 N 쌍을 seed 0 "
        "으로. N = 지금 이름 있는 쪽 쉬운 음성 수(700 — 쉬운 음성 700 모두 이름 축이 있음). 행은 "
        "pairs_features._easy_row(키 namedgoods:<출원번호>|<출원번호>) + 두 쪽 이미지가 있으면 "
        "x2_whole·사진A·사진B(src.photo_mark)."),
    "기준": (
        "두 벌의 기준은 지금 이름 있는 공통 기준(주의 0.0902·검토 권장 0.5059·위험 0.5902)에서 "
        "시작한다. 1차 시도 대조군(지어낸 이름) 기준용 100 의 질의마다(x4 = 이름+업종, "
        "x2_whole+x4 = 이름+이미지+업종 — 이름·이미지·업종 세트는 대조군 그대로) M_q = 무관한 "
        "후보(그 이름의 이미지인 표본 A 질의의 인용상표·같은 출원인을 뺀 후보 — "
        "first.a_relations·unrelated_filter) 중 그 집합으로 채점되는 후보(rm.select_pattern 이 "
        "그 집합)의 변형 계수 위험도 최댓값(업종 규칙 전; 특징은 v1.4.5 검색에서 엔진이 쓴 입력 "
        "그대로). 그 기준 이상인 질의 비율이 목표(검토 권장 10%·위험 2%)를 넘는 등급만 "
        "fit_cut(목표) 값으로 올린다(공통 기준보다 낮추지 않음, 주의 그대로). base·x2_whole 의 "
        "기준은 그대로. 공통과 같으면 그 집합에 자기 기준을 두지 않는다."),
    "채택_1": (
        "1차 시도 대조군 확인용 100 의 이름+업종(x4)·이름+이미지+업종(x2_whole+x4): (가) "
        "'기준'과 같은 M_q(확인용)로 변형 기준 이상 비율 검토 권장 ≤ 10%·위험 ≤ 2% — 넘으면 "
        "확인용에 같은 fit_cut 으로 맞춘 값 − 변형 기준 ≤ 0.0224 일 때만 통과 (나) 엔진 전체 "
        "등급(정렬 앞 5건의 최고 등급) 검토 권장 이상·위험 비율이 두 방식 모두 지금(v1.4.5)보다 "
        "늘지 않음."),
    "채택_2": (
        "같은 이름 질의: DB 상표 중 상표명·유사군이 있는 것에서 200(seed 0) — 이름 = 그 상표명, "
        "업종 = 그 상표의 유사군(이미지 없음). 원래 상표 또는 같은 출원인(별칭 표) 형제가 정렬 "
        "앞 5 안에 검토 권장 이상으로 나오는 비율 ≥ 95%. 위험 비율, 그리고 무관한 업종(대조군 "
        "업종 세트 25 중 그 상표 유사군과 겹침 0 인 것에서 seed 0 + 출원번호로 하나)으로 넣었을 "
        "때 인정 후보의 최고 등급·전체 등급 분포는 보고만."),
    "채택_3": (
        "표본 A 인용상표(이름 있는 판단) — §7-6 의 정의(표본 A 사건의 이름 있는 심결 행, "
        "이미지가 있으면 결합-문자요부·없으면 문자, 이미지 축은 사진 규칙 전 값)를 엔진과 같은 "
        "식(그 행의 판단 — 업종 집합이면 업종 하한·상한, 이미지가 있으면 이미지만 판단(도형계)과 "
        "견줌 logo_floor)으로 매긴 검토 권장 이상 비율: 변형 ≥ 지금(v1.4.5) − 0.05."),
    "채택_4": (
        "이번 변경으로 등급이 바뀐 심결 쌍: 두 벌로 채점되는 심결 행(자기 패턴이 "
        "x4·x2_whole+x4)의 OOF 등급 — 그 집합 OOF 위험도 → 그 집합 기준·단독·도형 규칙, 변형은 "
        "업종 하한·상한(짝 판단은 고정 짝 계수의 그 행 판단), 이미지가 있으면 이미지만 판단과 "
        "견줌(행의 유형). 지금 = '지금_재현' OOF·v1.4.5 규칙. 새로 위험이 된 쌍의 유사 비율 ≥ "
        "0.70, 위험에서 빠진 쌍 중 유사 비율 ≤ 0.5 — 각각 5쌍 미만이면 판정에 쓰지 않고 목록만. "
        "두 벌 행 전체의 위험 정밀도는 보고만."),
    "채택_5": (
        "(가) 업종이 겹치는(x4 ≥ 0.0252) 후보의 최종 등급(업종 하한 뒤) ≥ 짝 판단 등급, 업종이 "
        "다른 (< 0.0252) 후보의 업종 집합 등급(rm.risk_score — 단독·도형 규칙 포함, 상한 전) ≤ "
        "짝 판단 등급: 격자(이름 축 x1·x2_text 0–1 — x4 집합 0.05·x2_whole+x4 0.1 간격, 관념 "
        "게이트 꺼짐·켜짐 0·0.5·1, 요부 유무, 유형 문자·도형, x2_whole+x4 는 이미지 0–1 0.1 "
        "간격, 겹침 0–0.024 0.002 간격 + 0.0252·0.03·0.05·0.1·0.2·0.3·0.5·0.75·1) + 실제 후보(이 "
        "실행의 지금 검색에서 두 벌로 채점된 후보 전부의 엔진 입력) (나) 등급 "
        "순서·단조(rm.monotone_violations — 곱하기 항 ≥ 0 포함)·적재 결합 "
        "검증(rm.coupling_violations — (b)·이미지 결합·같은 이름) 위반 0."),
    "채택_6": (
        "대조군(기준용·확인용 200 이름)의 이름+업종·이름+이미지+업종 검색에서 업종이 다른(x4 < "
        "0.0252) 후보가 엔진 최종 등급 위험인데, 업종 없이 넣었을 때(이름만·이름+이미지 검색의 "
        "같은 후보 — 풀에 없으면 그 후보의 엔진 입력에서 x4 를 뺀 짝 판단)는 위험이 아닌 경우 0."),
    "채택_7": (
        "두 벌 각각 OOF 심결 AUC(그 집합 학습 행 중 심결 행, 행의 유형, 가중 없음): 변형 ≥ "
        "지금('지금_재현') − 0.05."),
    "판정": (
        "변형마다 ①–⑦을 모두 넘으면 통과. 둘 다 통과하면 ③이 높은 변형(같으면 S), 하나만 "
        "통과하면 그 변형, 둘 다 못 넘으면 적용하지 않고 멈춘다(종료 코드 3)."),
    "진단": (
        "판정에 안 씀. (가) 바꾸기 전(v1.4.5): 대조군 확인용 100·표본 A 184 검색에서 두 벌로 "
        "채점된 후보 중 업종이 다른데 집합 등급 > 짝 등급인 수(원칙 위반), 표장이 안 닮은 "
        "구간(짝 위험도 < 주의 0.0902 · 주의 구간 · 검토 권장 이상)마다 무관한 후보의 같은 "
        "업종(x4 ≥ 0.5) − 다른 업종(< 0.0252) 위험도 평균 차(지름길 크기) — 변형도 같은 식으로 "
        "(나) 학습 진단: 계수, 표장 유사 구간(이름 축 x1·x2_text·관념 = s, s = 0.3·0.5·0.7·0.9, "
        "문자, 요부 있음; x2_whole+x4 는 이미지 = s, 결합-문자요부)마다 겹침 0·1 의 위험도와 짝 "
        "위험도 (다) 이름 없는 쪽과의 일관성: 같은 이름 제약의 최소 여유, 이미지 s 에서 이름 축 "
        "0·1 일 때 이름 있는 x2_whole+x4 의 업종 몫(겹침 1 − 0 위험도)과 이름 없는 "
        "x2_whole+x4(v1.4.5)의 업종 몫."),
    "전후": (
        "변형별: 대조군 기준용·확인용 네 방식의 전체 등급 분포, 같은 이름(원래 업종·무관한 "
        "업종), 표본 A 검색 184(업종 있음·없음), 시나리오 16종(named_shared_threshold.SCENARIOS "
        "— 보고만, 시연 넷 크린토피야·스타벅수·파리바게트·블루커피를 맨 위에). 지금 = v1.4.5 를 "
        "같은 프로세스에서 같은 방법으로 다시 잰 값. 검산: 바꾸기 전 시나리오 16종 = v1.4.5 확인 "
        "실행 저장값(다르면 멈춤)."),
    "적용": (
        "고른 변형만 shared/model/risk_model_v1.4.6.json = v1.4.5 JSON 에서 "
        "patterns['x4']·patterns['x2_whole+x4'] 를 변형의 "
        "features·coefficients·intercept·goods_rule·(올렸으면) grade_thresholds·meta 로, 최상위 "
        "기준 패턴 사본, goods_cap.enabled, version risk_model_v1.4.6, "
        "meta.named_goods_product(출처). verify 가 기본 엔진으로 대조군·같은 이름·표본 "
        "A·시나리오를 다시 돌려 후보 실행과 같은지 본다."),
}


def _settings() -> dict:
    return {"RULE": RULE, "SETS": SETS, "PAIR": PAIR, "MODE_OF": MODE_OF, "VARIANTS": VARIANTS,
            "SEED": SEED, "TARGETS": TARGETS, "TOLERANCE": TOLERANCE,
            "SAME_GOODS_MIN": SAME_GOODS_MIN, "NAME_SHARE": NAME_SHARE,
            "IMAGE_SHARE": IMAGE_SHARE, "KEY_PREFIX": KEY_PREFIX, "SAME_NAME_N": SAME_NAME_N,
            "SAME_NAME_MIN": SAME_NAME_MIN, "CITED_DROP_MAX": CITED_DROP_MAX,
            "PRECISION_MIN": PRECISION_MIN, "CHANGE_MIN_ROWS": CHANGE_MIN_ROWS,
            "AUC_DROP_MAX": AUC_DROP_MAX, "PRODUCT_PRIOR_MU": PRODUCT_PRIOR_MU,
            "SIMILARITY_LEVELS": SIMILARITY_LEVELS, "NAME_GRID": NAME_GRID, "X2_GRID": X2_GRID,
            "X4_GRID": X4_GRID, "LEVELS": LEVELS, "SMOKE": SMOKE, "BASE_VERSION": BASE_VERSION,
            "NEW_VERSION": NEW_VERSION, "CONTROL_SHA": ns.CONTROL_SHA, "DISPLAY_TOP": DISPLAY_TOP}


def rule_sha256() -> str:
    return first.canonical_sha256(_settings())


def _inputs() -> dict[str, Path]:
    inputs = gs._inputs()  # noqa: SLF001 — 같은 입력(v1.4.3 JSON 자리는 v1.4.5 로)
    inputs.pop("계수_JSON(v1.4.3)", None)
    inputs.update({"계수_JSON(v1.4.5)": BASE_MODEL_PATH, "v1.4.5_실행_검색": SAVED_V145,
                   "학습_스크립트(4-a)": ML_ROOT / "scripts" / "goods_product.py"})
    return inputs


def _paths(out_dir: Path) -> dict[str, Path]:
    return {"rule": out_dir / f"{STEM}_rule.json", "results": out_dir / f"{STEM}_results.json",
            "report": out_dir / f"{STEM}_report.md",
            **{f"candidate_{v}": out_dir / f"{STEM}_candidate_{v}.json" for v in VARIANTS},
            "negatives": out_dir / f"{STEM}_negatives.csv",
            "easy": out_dir / f"{STEM}_easy_augmented.csv",
            "searches": out_dir / f"{STEM}_searches.json.gz",
            "verify": out_dir / f"{STEM}_verify.json"}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _round(value, digits: int = 4):
    return None if value is None else round(float(value), digits)


# ---- 순수 함수(시험 대상) ----------------------------------------------------------------------

def product_names(variant: str, key: str) -> list[str]:
    """변형의 곱하기 항 — L 은 그 집합의 표장 항 × x4, S 는 짝 위험도 × x4."""
    if variant == "L":
        names = list(rm.NAME_PRODUCT_TERMS)
        if key == "x2_whole+x4":
            names += list(rm.PRODUCT_TERMS)
        return names
    if variant == "S":
        return [rm.pair_term_name(PAIR[key])]
    raise ValueError(f"모르는 변형: {variant}")


def start_thresholds(values: list[float], common: dict) -> dict:
    """규칙 '기준' — 공통 기준에서 시작, 목표를 넘는 등급만 fit_cut 으로 올린다."""
    out = {CAUTION: float(common[CAUTION])}
    detail = {}
    for grade, share in TARGETS.items():
        start = float(common[grade])
        rate = ns.rate_at_least(values, start)
        fitted, k, n = first.fit_cut(values, share)
        raise_ = rate is not None and rate > share + 1e-12
        out[grade] = round(max(start, fitted), 4) if raise_ and fitted is not None else start
        detail[grade] = {"시작": start, "기준용_비율(시작)": rate, "fit_cut": fitted, "k": k,
                         "n": n, "올림": raise_}
    return {"기준": out, "자세히": detail}


def choose(passed: dict[str, bool], cited: dict[str, float | None]) -> str | None:
    """규칙 '판정' — 둘 다면 ③이 높은 쪽, 같으면 S."""
    ok = [v for v in VARIANTS if passed.get(v)]
    if not ok:
        return None
    if len(ok) == 1:
        return ok[0]
    return max(ok, key=lambda v: (cited.get(v) or 0.0, v == "S"))


def round_named(names: list[str], coef, intercept: float, digits: int = 4) -> dict:
    """넷째 자리 반올림 + 단조 보정(규칙 '학습')."""
    values = {name: round(float(value), digits) + 0.0 for name, value in zip(names, coef)}
    step = 10.0 ** -digits
    for name in names:
        if (name in MAIN_TERMS or rm.is_product_term(name)) and values[name] < 0:
            values[name] = 0.0
    for _ in range(200):
        if not rm.monotone_violations(values):
            break
        if "x2_whole×도형계" in values and values["x2_whole"] + values["x2_whole×도형계"] < 0:
            values["x2_whole×도형계"] = round(values["x2_whole×도형계"] + step, digits)
        extras = [n for n in ("x1_d×문자계", "x1_d×any_no_distinctive") if n in values]
        x1 = values.get("x1_d", 0.0)
        for extra in extras:
            if x1 + values[extra] < -1e-12:
                values[extra] = round(values[extra] + step, digits)
        if len(extras) == 2 and x1 + values[extras[0]] + values[extras[1]] < -1e-12:
            values[extras[1]] = round(values[extras[1]] + step, digits)
    return {"features": list(names), "coefficients": values,
            "intercept": round(float(intercept), digits)}


def with_named(base: dict, entries: dict[str, dict], *, rule: bool = True,
               thresholds: dict | None = None, cap: bool = True) -> dict:
    """base 의 두 벌을 entries 로 — goods_rule·(다르면) 자기 기준·최상위 기준 패턴 사본·업종
    상한."""
    out = copy.deepcopy(base)
    common = base["grade_thresholds"]
    for key, entry in entries.items():
        block = out["patterns"][key]
        block["features"] = list(entry["features"])
        block["coefficients"] = dict(entry["coefficients"])
        block["intercept"] = float(entry["intercept"])
        if rule:
            block[rm.GOODS_RULE_KEY] = rm.GOODS_RULE_NO_RAISE
        own = (thresholds or {}).get(key)
        if own is not None and any(float(own[g]) != float(common[g])
                                   for g in rm.GRADE_THRESHOLD_KEYS):
            block["grade_thresholds"] = {g: float(own[g]) for g in rm.GRADE_THRESHOLD_KEYS}
        else:
            block.pop("grade_thresholds", None)
    reference = out["patterns"][out["reference_pattern"]]
    out.update(features=list(reference["features"]), coefficients=dict(reference["coefficients"]),
               intercept=float(reference["intercept"]))
    if cap:
        out[rm.GOODS_CAP_KEY] = {"enabled": True, "rule": (
            "업종이 다르면(겹침 < coupling.floors.x4) 업종 집합의 최종 등급 ≤ 업종 없는 짝 판단의 "
            "등급 — 이름 없는·이름 있는 판단 모두(설계 §7-13)")}
    return out


def repair_intercepts(model: dict, *, digits: int = 4, limit: int = 400) -> tuple[dict, dict]:
    """반올림이 만든 적재 결합 위반을 절편으로 고친다(규칙 '학습')."""
    out = copy.deepcopy(model)
    step = 10.0 ** -digits
    moves: Counter = Counter()
    for _ in range(limit):
        violations = rm.coupling_violations(out)
        if not violations:
            break
        changed = False
        for key, lower_at in (("x4", "x4 (x4 = 0) >"), ("x2_whole+x4", "x2_whole+x4 (x4 = 0) >")):
            if any(v.startswith(lower_at) for v in violations):
                out["patterns"][key]["intercept"] = round(out["patterns"][key]["intercept"] - step,
                                                          digits)
                moves[f"{key} 내림"] += 1
                changed = True
        if any(v.startswith("x4 → x2_whole+x4") for v in violations):
            out["patterns"]["x4"]["intercept"] = round(out["patterns"]["x4"]["intercept"] - step,
                                                       digits)
            moves["x4 내림(이미지 결합)"] += 1
            changed = True
        if any("→ x2_whole+x4 (같은 이름)" in v for v in violations):
            block = out["patterns"]["x2_whole+x4"]
            block["intercept"] = round(block["intercept"] + step, digits)
            moves["x2_whole+x4 올림(같은 이름)"] += 1
            changed = True
        if not changed:
            return out, {"걸음": dict(moves), "고침": False, "남은_위반": violations[:5]}
        reference = out["patterns"][out["reference_pattern"]]
        out["intercept"] = float(reference["intercept"])
    remaining = rm.coupling_violations(out)
    return out, {"걸음": dict(moves), "고침": not remaining, "남은_위반": remaining[:5]}


def grade_with_rules(prob: float, features: dict, model: dict, pattern: str) -> str:
    """위험도 → 등급(그 집합 기준) + 단독·도형 규칙 — rm.risk_score 의 등급과 같은 판정."""
    values = rm.design_values(features)
    grade = rm.grade_for(prob, rm.grade_thresholds_for(model, pattern))
    for axis, tau in (model.get("standalone_thresholds") or {}).items():
        if tau is not None and values[rm.MISS_OF[axis]] == 0.0 and values[axis] >= float(tau):
            grade = max(grade, REVIEW, key=rm.GRADES.index)
    rule = model.get("figure_rule") or {}
    level = rm.mark_type_level(features.get("mark_type"))
    if (level in rm.FIGURE_FAMILY and rule.get("threshold") is not None
            and values["miss_x2img"] == 0.0 and values["x2_whole"] >= float(rule["threshold"])):
        grade = max(grade, REVIEW, key=rm.GRADES.index)
    return grade


def goods_rules(grade: str, features: dict, model: dict, pattern: str,
                pair_grade: str) -> tuple[str, str | None]:
    """엔진 _named_judgment 와 같은 업종 하한·상한 — (등급, 쓰인 규칙)."""
    x4 = features.get("x4")
    floor = float(model["coupling"]["floors"]["x4"])
    if pattern not in SETS or x4 is None:
        return grade, None
    floor_on = (model["patterns"][pattern].get(rm.GOODS_RULE_KEY) == rm.GOODS_RULE_NO_RAISE)
    if float(x4) >= floor:
        if floor_on and rm.GRADES.index(pair_grade) > rm.GRADES.index(grade):
            return pair_grade, "goods_floor_named"
    elif rm.goods_cap_enabled(model) and rm.GRADES.index(grade) > rm.GRADES.index(pair_grade):
        return pair_grade, "goods_cap"
    return grade, None


def engine_grade(features: dict, model: dict, *, set_prob: float | None = None) -> str:
    """엔진과 같은 식의 이름 있는 판단 최종 등급 — 그 판단(set_prob 이 있으면 그 위험도로) → 업종
    하한·상한 → 이미지가 있으면 이미지만 판단(도형계)과 견줌(logo_floor)."""
    result = rm.risk_score(features, model)
    pattern = result.pattern
    grade = (result.grade if set_prob is None
             else grade_with_rules(set_prob, features, model, pattern))
    if pattern in SETS and features.get("x4") is not None:
        pair = rm.risk_score({**features, "x4": None}, model)
        grade, _ = goods_rules(grade, features, model, pattern, pair.grade)
    if rm.logo_floor_enabled(model) and features.get("x2_whole") is not None:
        image = rm.risk_score(ns.nameless_features(float(features["x2_whole"]), None), model)
        grade = max(grade, image.grade, key=rm.GRADES.index)
    return grade


def level_point(key: str, s: float, x4: float | None) -> dict:
    """진단 — 표장 유사 s 의 입력(이름 축 = s, 관념 = s, 요부 있음; x2_whole+x4 는 이미지 = s)."""
    features = {"x1_d": s, "x2_text_d": s, "x3_d": s, "has_meaning_both": True,
                "has_distinctive_part_a": True, "has_distinctive_part_b": True, "x4": x4,
                "x2_whole": s if key == "x2_whole+x4" else None,
                "mark_type": "결합-문자요부" if key == "x2_whole+x4" else "문자"}
    return features


def probe_table(model: dict) -> dict:
    out = {}
    for key in SETS:
        rows = {}
        for s in SIMILARITY_LEVELS:
            zero = rm.risk_score(level_point(key, s, 0.0), model)
            full = rm.risk_score(level_point(key, s, 1.0), model)
            pair = rm.risk_score(level_point(key, s, None), model)
            assert zero.pattern == full.pattern == key and pair.pattern == PAIR[key]
            rows[str(s)] = {"겹침 0": _round(zero.prob), "겹침 1": _round(full.prob),
                            "짝": _round(pair.prob)}
        out[key] = rows
    return out


def grid_points(key: str):
    name_step = NAME_GRID[key]
    names = [round(i * name_step, 4) for i in range(int(round(1 / name_step)) + 1)]
    images = ([round(i * X2_GRID, 4) for i in range(int(round(1 / X2_GRID)) + 1)]
              if key == "x2_whole+x4" else [None])
    meanings = [(False, None), (True, 0.0), (True, 0.5), (True, 1.0)]
    for level in LEVELS:
        for distinctive in (True, False):
            for meaning, x3 in meanings:
                for x1 in names:
                    for x2t in names:
                        for x2 in images:
                            yield {"x1_d": x1, "x2_text_d": x2t, "x3_d": x3,
                                   "has_meaning_both": meaning, "has_distinctive_part_a": True,
                                   "has_distinctive_part_b": distinctive, "x2_whole": x2,
                                   "mark_type": level}


def direction_check(features_list, model: dict) -> dict:
    """채택_5 (가) — 업종이 겹치면 최종 ≥ 짝, 다르면 집합 등급 ≤ 짝."""
    floor = float(model["coupling"]["floors"]["x4"])
    bad: Counter = Counter()
    checked: Counter = Counter()
    examples: list = []
    for features in features_list:
        result = rm.risk_score(features, model)
        if result.pattern not in SETS:
            continue
        pair = rm.risk_score({**features, "x4": None}, model)
        x4 = float(features["x4"])
        if x4 >= floor:
            final, _ = goods_rules(result.grade, features, model, result.pattern, pair.grade)
            violated = rm.GRADES.index(final) < rm.GRADES.index(pair.grade)
            kind = "겹침"
        else:
            violated = rm.GRADES.index(result.grade) > rm.GRADES.index(pair.grade)
            kind = "다름"
        checked[f"{result.pattern} {kind}"] += 1
        if violated:
            bad[f"{result.pattern} {kind}"] += 1
            if len(examples) < 5:
                examples.append({k: features.get(k) for k in ("x1_d", "x2_text_d", "x3_d",
                                                              "x2_whole", "x4", "mark_type")})
    return {"본_점": dict(checked), "어김": dict(bad), "예": examples}


def grid_check(model: dict) -> dict:
    out = {}
    for key in SETS:
        points = ({**point, "x4": x4} for point in grid_points(key) for x4 in X4_GRID)
        out[key] = direction_check(points, model)
    return out


# ---- 0. 고정 -----------------------------------------------------------------------------------

def command_freeze(args) -> int:
    paths = _paths(args.out_dir)
    if paths["rule"].exists() and not args.force:
        print(f"거절: {paths['rule']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    base = rm.validate_model(json.loads(BASE_MODEL_PATH.read_text(encoding="utf-8")))
    if base.get("version") != BASE_VERSION:
        print("거절: 기준 JSON 이 v1.4.5 가 아닙니다", file=sys.stderr)
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
    skip = {"런타임", "엔진"} if model_may_change else set()
    changed = [k for k, p in _inputs().items()
               if k not in skip and first.file_sha256(p) != frozen["입력_sha256"].get(k)]
    if changed:
        print(f"거절: 입력이 고정 때와 다릅니다 — {changed}", file=sys.stderr)
        return None
    return frozen


# ---- 1. 새 음성 --------------------------------------------------------------------------------

def build_negatives(n: int, *, record_limit: int | None = None) -> tuple[list[dict], dict]:
    """규칙 '새_음성'."""
    from src import photo_mark  # numpy 만

    from scripts import nameless_search_thresholds as nst
    from scripts import pairs_features as pf  # torch → faiss 순서

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
    related, related_report = gs.trial_related_pairs(labels, trial_list, numbers)
    easy_records = pf.read_db_records(pf.DEFAULT_METADATA)
    existing: set[tuple[str, str]] = set()
    for row in pf.read_csv(pf.DEFAULT_BASE / "pairs_features_easy.csv"):
        source, _, pair = row["심판번호"].partition(":")
        if source == "db":
            i, _, j = pair.partition("|")
            existing.add(tuple(sorted((str(easy_records[int(i)]["출원번호"]),
                                       str(easy_records[int(j)]["출원번호"])))))
    usable = sorted((r for r in records if pf._db_name(r) and r.get("유사군")),  # noqa: SLF001
                    key=lambda r: str(r["출원번호"]))
    if record_limit is not None:
        usable = usable[:record_limit]
    apps = [nst.split_applicants(r.get("출원인") or "", aliases) for r in usable]
    goods = [frozenset(r["유사군"]) for r in usable]
    vec = [vectors.get(r.get("이미지파일") or "") for r in usable]
    dist = pf.load_distinctiveness()
    counts: Counter = Counter()
    pool: list[dict] = []
    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            overlap = pf.goods_similarity(goods[i], goods[j])
            if overlap < SAME_GOODS_MIN:
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
            name_a, name_b = pf._db_name(usable[i]), pf._db_name(usable[j])  # noqa: SLF001
            axes = pf.name_axes(name_a, name_b, goods[i] | goods[j], dist)
            if axes["x1_d"] == "" or axes["x2_text_d"] == "":
                counts["이름 축 없음"] += 1
                continue
            meaning = bool(pf.x3.has_meaning(name_a)) and bool(pf.x3.has_meaning(name_b))
            total = float(axes["x1_d"]) + float(axes["x2_text_d"]) + (
                float(axes["x3_d"]) if meaning and axes["x3_d"] != "" else 0.0)
            image = (max(0.0, float(np.dot(vec[i], vec[j])))
                     if vec[i] is not None and vec[j] is not None else None)
            pool.append({"a": a, "b": b, "i": i, "j": j, "이름_합": round(total, 6),
                         "관념": meaning, "이미지": image, "겹침": overlap})
    by_name = sorted(pool, key=lambda p: (p["이름_합"], p["a"], p["b"]))
    name_keep = {(p["a"], p["b"]) for p in by_name[:int(len(by_name) * NAME_SHARE)]}
    imaged = sorted((p for p in pool if p["이미지"] is not None),
                    key=lambda p: (p["이미지"], p["a"], p["b"]))
    image_keep = {(p["a"], p["b"]) for p in imaged[:int(len(imaged) * IMAGE_SHARE)]}
    eligible = [p for p in pool if (p["a"], p["b"]) in name_keep
                and (p["이미지"] is None or (p["a"], p["b"]) in image_keep)]
    if n > len(eligible):
        raise ValueError(f"새 음성 {n} 쌍을 뽑을 모집단이 {len(eligible)} 쌍뿐입니다")
    picked = sorted(random.Random(SEED).sample(eligible, n), key=lambda p: (p["a"], p["b"]))
    rows = []
    for p in picked:
        ra, rb = usable[p["i"]], usable[p["j"]]
        row = pf._easy_row("db", f"{KEY_PREFIX}:{p['a']}|{p['b']}", pf._db_name(ra),  # noqa: SLF001
                           pf._db_name(rb), goods[p["i"]], goods[p["j"]], dist)  # noqa: SLF001
        if p["이미지"] is not None:
            row.update({"x2_whole": pf._fmt(p["이미지"]), "has_image": 1,  # noqa: SLF001
                        "사진A": pf.photo_flag(photo_mark.is_photo(vec[p["i"]])),
                        "사진B": pf.photo_flag(photo_mark.is_photo(vec[p["j"]]))})
        rows.append(row)
    stats = gs.summary_stats
    report = {
        "DB": len(records), "쓸_수_있는_상표(상표명·유사군)": len(usable),
        "심결_관계": related_report, "쌍_거르기": dict(counts), "조건을_채운_쌍(P)": len(pool),
        "이름_축_합_하위_50%": len(name_keep), "이미지_있는_쌍": len(imaged),
        "이미지_하위_50%": len(image_keep), "뽑을_모집단": len(eligible), "N": n,
        "P_이름_축_합": stats([p["이름_합"] for p in pool]),
        "P_이미지_유사도": stats([p["이미지"] for p in pool if p["이미지"] is not None]),
        "뽑은_쌍": {"이름_축_합": stats([p["이름_합"] for p in picked]),
                  "호칭": stats([float(r["x1_d"]) for r in rows]),
                  "철자": stats([float(r["x2_text_d"]) for r in rows]),
                  "관념_있는_쌍": sum(1 for p in picked if p["관념"]),
                  "이미지_있는_쌍": sum(1 for p in picked if p["이미지"] is not None),
                  "이미지_유사도": stats([p["이미지"] for p in picked if p["이미지"] is not None]),
                  "업종_겹침": stats([p["겹침"] for p in picked]),
                  "서로_다른_상표": len({x for p in picked for x in (p["a"], p["b"])})}}
    return rows, report


def write_augmented(rows: list[dict], path: Path) -> dict:
    from scripts import pairs_features as pf

    original_path = pf.DEFAULT_BASE / "pairs_features_easy.csv"
    original = pf.read_csv(original_path)
    pf.write_csv(path, original + rows)
    head = original_path.read_bytes()
    return {"원본_행": len(original), "새_행": len(rows),
            "앞부분_원본과_같음": path.read_bytes()[:len(head)] == head}


def write_negatives(rows: list[dict], path: Path) -> None:
    from scripts import pairs_features as pf

    pf.write_csv(path, rows)


# ---- 2. 학습 -----------------------------------------------------------------------------------

def smoke_subset(rows: list[dict]) -> list[dict]:
    """스모크 — 행 쌍키로 정한 일부(seed 와 다른 문자열)만."""
    keep = []
    for row in rows:
        key = f"{row.get('심판번호')}|{row.get('상대번호')}|{row.get('쌍키')}"
        if random.Random(f"스모크|{key}").random() < SMOKE["학습_비율"]:
            keep.append(row)
    return keep


def named_design(rows: list[dict], names_by_block: dict[str, list[str]], model_ctx: dict):
    """t4.Design(v1.4) 에 집합 항을 바꾼 설계 — 값은 rm.design_vector(짝 위험도 항은 model_ctx)."""
    from scripts import train_risk_model_v14 as t4

    design = t4.Design(rows, structure="v1.4", nameless_keys=t4.NAMELESS_KEYS)
    features = [t4.service_features(row) for row in rows]
    for block, names in names_by_block.items():
        default = list(design.names[block])
        if list(names[:len(default)]) != default and block in SETS:
            raise ValueError(f"{block} 의 기존 항이 v1.4 설계와 다릅니다")
        design.names[block] = list(names)
        design.X[block] = np.asarray([rm.design_vector(f, names, model_ctx) for f in features],
                                     dtype=np.float64)
    design.offset, design.size = {}, 0
    for block in design.ids:
        design.offset[block] = design.size
        design.size += len(design.names[block]) + 1
    return design, features


def _difference(design, upper: str, upper_input: dict, lower: str, lower_input: dict,
                model_ctx: dict) -> np.ndarray:
    row = np.zeros(design.size)
    high = rm.design_vector(upper_input, design.names[upper], model_ctx)
    low = rm.design_vector(lower_input, design.names[lower], model_ctx)
    start = design.offset[upper]
    row[start:start + len(high)] += high
    row[start + len(high)] += 1.0
    start = design.offset[lower]
    row[start:start + len(low)] -= low
    row[start + len(low)] -= 1.0
    return row


def build_constraints(design, structure: str, model_ctx: dict) -> list:
    """규칙 '제약'(변형)·'지금_재현'(지금 구조)."""
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4
    from scripts import train_risk_model_v14_nameless as t2

    floors = model_ctx["coupling"]["floors"]
    out = []
    for block in SETS:
        names = design.names[block]
        start = design.offset[block]
        for g in tr.monotone_constraints(names):
            row = np.zeros(design.size)
            row[start:start + len(g)] = g
            out.append(t4.Constraint("단조", f"{block}: " + " + ".join(
                n for n, v in zip(names, g) if v) + " ≥ 0", row))
        for name in names:
            if rm.is_product_term(name):
                row = np.zeros(design.size)
                row[start + names.index(name)] = 1.0
                out.append(t4.Constraint("(a) 곱하기 항", f"{block}: {name} ≥ 0", row))
        pair = PAIR[block]
        for vertex in rm.coupling_vertices(design.names[pair]):
            label = f"{block} ↔ {pair} @ {t4._vertex_label(vertex)}"  # noqa: SLF001
            if structure == "지금":
                out.append(t4.Constraint("결합(업종)", label, _difference(
                    design, block, {**vertex, "x4": float(floors["x4"])}, pair, vertex,
                    model_ctx)))
            else:
                out.append(t4.Constraint("(b) 겹침 0 → 짝 이하", label, _difference(
                    design, pair, vertex, block, {**vertex, "x4": 0.0}, model_ctx)))
    for vertex in rm.coupling_vertices(design.names["x4"]):
        out.append(t4.Constraint(
            "결합(이미지)", f"x4 → x2_whole+x4 @ {t4._vertex_label(vertex)}",  # noqa: SLF001
            _difference(design, "x2_whole+x4", {**vertex, "x2_whole": float(floors["x2_whole"])},
                        "x4", vertex, model_ctx)))
    nameless = rm.NAMELESS_PREFIX + "x2_whole+x4"
    for vertex in rm.nameless_vertices(design.names[nameless]):
        for distinctive in (True, False):
            upper = rm.same_name_input(vertex, t2.SAME_NAME, distinctive=distinctive)
            out.append(t4.Constraint(
                "결합(같은 이름)", f"{nameless} → x2_whole+x4 @ "
                f"{t4._vertex_label(vertex)}, 요부없음={not distinctive}",  # noqa: SLF001
                _difference(design, "x2_whole+x4", upper, nameless, vertex, model_ctx)))
    return out


def fixed_blocks(design, base: dict) -> dict:
    out = {}
    for key in ("base", "x2_whole"):
        block = base["patterns"][key]
        out[key] = (np.asarray([float(block["coefficients"][n]) for n in design.names[key]]),
                    float(block["intercept"]))
    for key, block in base[rm.NAMELESS_KEY].items():
        name = rm.NAMELESS_PREFIX + key
        out[name] = (np.asarray([float(block["coefficients"][n]) for n in design.names[name]]),
                     float(block["intercept"]))
    return out


def train(structure: str, rows: list[dict], base: dict) -> dict:
    """structure = '지금'(지금 구조) 또는 변형 L·S."""
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    a = t4.arrays(rows)
    keys, choice = t4.choose_nameless_keys(rows, a, tr.MIN_PATTERN_MINORITY)
    if tuple(keys) != tuple(t4.NAMELESS_KEYS):
        raise ValueError(f"이름 없는 집합 구성이 다릅니다: {choice}")
    names = {key: list(base["patterns"][key]["features"]) for key in ("base", "x2_whole")}
    names.update({rm.NAMELESS_PREFIX + key: list(block["features"])
                  for key, block in base[rm.NAMELESS_KEY].items()})
    for key in SETS:
        names[key] = list(base["patterns"][key]["features"]) + (
            [] if structure == "지금" else product_names(structure, key))
    design, features = named_design(rows, names, base)
    fixed = fixed_blocks(design, base)
    constraints = build_constraints(design, "지금" if structure == "지금" else "변형", base)
    mu = dict(tr.PRIOR_MU)
    for key in SETS:
        mu.update({name: PRODUCT_PRIOR_MU for name in design.names[key]
                   if rm.is_product_term(name)})
    started = time.perf_counter()
    oof = {key: np.zeros(a["y"].size) for key in SETS}
    success, slack = [], []
    for repeat in range(t4.REPEATS):
        for train_index, test in tr.folds_for(a["y"], a["groups"], folds=t4.FOLDS,
                                              seed=SEED + repeat):
            fit = t4.fit_joint(design, a["y"], a["fit_weight"], train_index, constraints,
                               fixed=fixed, mu=mu)
            success.append(fit.success)
            slack.append(fit.min_slack)
            for key in SETS:
                coef, intercept = fit.blocks[key]
                oof[key][test] += expit(design.X[key][test] @ coef + intercept)
    oof = {key: value / t4.REPEATS for key, value in oof.items()}
    final = t4.fit_joint(design, a["y"], a["fit_weight"], np.arange(len(rows)), constraints,
                         fixed=fixed, mu=mu)
    entries = {key: round_named(design.names[key], *final.blocks[key]) for key in SETS}
    counts = t4.block_counts(design, a["y"], a["fit_weight"], a["easy"])
    return {"structure": structure, "rows": rows, "arrays": a, "design": design,
            "features": features, "oof": oof, "final": final, "entries": entries,
            "counts": {key: counts[key] for key in SETS},
            "constraints": dict(Counter(c.kind for c in constraints)),
            "seconds": round(time.perf_counter() - started, 1),
            "optimizer": {"solver": final.solver, "success": bool(final.success),
                          "kkt_residual": _round(final.kkt_residual, 9),
                          "min_slack": _round(final.min_slack, 9),
                          "cv_겹": len(success), "cv_수렴_실패": int(len(success) - sum(success)),
                          "cv_최소_여유": _round(min(slack), 9) if slack else None}}


def oof_auc(result: dict) -> dict:
    from scripts import train_risk_model_v14 as t4

    design, a = result["design"], result["arrays"]
    out = {}
    for key in SETS:
        index = np.flatnonzero(a["trial"] & design.mask[key])
        y, w = a["y"][index], a["eval_weight"][index]
        out[key] = {"행": int(index.size), "유사": int(y.sum()),
                    "AUC": _round(t4.weighted_auc(result["oof"][key][index], y,
                                                  np.ones(index.size))),
                    "AUC(사건 가중)": _round(t4.weighted_auc(result["oof"][key][index], y, w))}
    return out


def oof_changes(now: dict, new: dict, now_model: dict, new_model: dict) -> dict:
    """채택_4 — 두 벌로 채점되는 심결 행의 OOF 등급(지금 대 변형)."""
    rows_now, design_now = now["rows"], now["design"]
    key_of = {(r["심판번호"], r.get("상대번호"), r.get("쌍키")): i
              for i, r in enumerate(new["rows"])}
    changed_in, changed_out, totals = [], [], {"지금": Counter(), "변형": Counter()}
    for i, row in enumerate(rows_now):
        if row.get("pair_source") != "trial" or design_now.own[i] not in SETS:
            continue
        j = key_of.get((row["심판번호"], row.get("상대번호"), row.get("쌍키")))
        if j is None:
            raise ValueError("지금·변형 학습 행의 심결 행이 다릅니다")
        block = design_now.own[i]
        features = now["features"][i]
        before = engine_grade(features, now_model, set_prob=float(now["oof"][block][i]))
        after = engine_grade(features, new_model, set_prob=float(new["oof"][block][j]))
        label = int(now["arrays"]["y"][i])
        for tag, grade in (("지금", before), ("변형", after)):
            totals[tag][grade] += 1
            if grade == RISK:
                totals[tag]["위험_유사"] += label
        item = {"심판번호": row["심판번호"], "상대번호": row.get("상대번호"), "집합": block,
                "라벨": "유사" if label else "비유사", "지금": before, "변형": after}
        if after == RISK and before != RISK:
            changed_in.append(item)
        elif before == RISK and after != RISK:
            changed_out.append(item)

    def share(items: list[dict]) -> float | None:
        return round(sum(i["라벨"] == "유사" for i in items) / len(items), 4) if items else None

    precision_in, similar_out = share(changed_in), share(changed_out)
    judged_in = len(changed_in) >= CHANGE_MIN_ROWS
    judged_out = len(changed_out) >= CHANGE_MIN_ROWS
    passed = ((not judged_in or precision_in >= PRECISION_MIN - 1e-12)
              and (not judged_out or similar_out <= 0.5 + 1e-12))
    overall = {tag: {"위험": c[RISK], "유사": c["위험_유사"],
                     "정밀도": round(c["위험_유사"] / c[RISK], 4) if c[RISK] else None}
               for tag, c in totals.items()}
    return {"새로_위험": {"수": len(changed_in), "유사_비율": precision_in,
                       "판정에_씀": judged_in, "목록": changed_in[:40]},
            "위험에서_빠짐": {"수": len(changed_out), "유사_비율": similar_out,
                         "판정에_씀": judged_out, "목록": changed_out[:40]},
            "전체_위험_정밀도(보고만)": overall, "통과": passed}


# ---- 3. 검색 -----------------------------------------------------------------------------------

class Capture:
    """엔진 score_record 의 첫 판단 입력(_judge 의 features)을 후보마다 남긴다 — 엔진 코드는
    그대로."""

    def __init__(self, ms):
        self.ms = ms
        self.slot: dict | None = None
        self.last: dict[str, dict] = {}
        self._score, self._judge = ms.score_record, ms._judge  # noqa: SLF001
        capture = self

        def judge(features, model, query_type):
            if capture.slot is not None and capture.slot.get("features") is None:
                capture.slot["features"] = dict(features)
            return capture._judge(features, model, query_type)

        def score(record, ctx, *args, **kwargs):
            capture.slot = {"features": None}
            try:
                result = capture._score(record, ctx, *args, **kwargs)
            finally:
                slot, capture.slot = capture.slot, None
            capture.last[result.id] = slot["features"]
            return result

        ms._judge, ms.score_record = judge, score  # noqa: SLF001

    def take(self) -> dict[str, dict]:
        out, self.last = self.last, {}
        return out

    def close(self) -> None:
        self.ms._judge, self.ms.score_record = self._judge, self._score  # noqa: SLF001


def _entry(pooled) -> dict:
    return {"전체": ns.overall([c.grade for c in pooled.candidates]),
            "상위": [c.id for c in pooled.candidates[:DISPLAY_TOP]],
            "후보": {c.id: [c.grade, round(float(c.prob), 6), c.pattern, c.axes["x4"],
                          c.axes["x2_img"], list(c.rule_triggers)]
                   for c in pooled.candidates}}


def search(context: dict, models: dict, capture: Capture | None, **inputs) -> dict:
    ms = context["ms"]
    out = {}
    for label, model in models.items():
        with ns.using_model(ms, model):
            if capture is not None and label == "지금":
                capture.take()
            pooled = ms.search_pool(**inputs)
        out[label] = _entry(pooled)
        if capture is not None and label == "지금":
            out["특징"] = capture.take()
    return out


def control_items(control: dict, half: str, limit: int | None) -> list[dict]:
    return control["대조군"]["이름"][half][:limit]


def run_control(context: dict, items: list[dict], models: dict, capture: Capture | None,
                *, modes=MODES) -> list[dict]:
    a_by_key = {query.key: query for query in context["A"]}
    out = []
    for index, item in enumerate(items):
        source = a_by_key[item["이미지"]]
        cited, owners = first.a_relations(context, source)
        unrelated = first.unrelated_filter(context, owners, cited)
        image = context["service"](source.path.read_bytes())
        goods = sorted(item["유사군"]) or None
        row = {"이름": item["이름"], "이미지": item["이미지"], "방식": {}}
        for mode, with_image, with_goods in modes:
            entry = search(context, models, capture, name=item["이름"],
                           image=image if with_image else None,
                           goods_codes=goods if with_goods else None)
            entry["무관"] = sorted(c for c in entry[next(iter(models))]["후보"] if unrelated(c))
            row["방식"][mode] = entry
        out.append(row)
        if (index + 1) % 20 == 0:
            print(f"    대조군 {index + 1}/{len(items)}", flush=True)
    return out


def query_maxima(rows: list[dict], model: dict, key: str) -> list[float]:
    """규칙 '기준' — 질의마다 무관한 후보 중 그 집합으로 채점되는 후보의 위험도 최댓값."""
    out = []
    for row in rows:
        entry = row["방식"][MODE_OF[key]]
        values = []
        for appno in entry["무관"]:
            features = entry["특징"].get(appno)
            if features is None:
                continue
            result = rm.risk_score(features, model)
            if result.pattern == key:
                values.append(float(result.prob))
        if values:
            out.append(max(values))
    return out


def same_name_queries(context: dict, limit: int | None) -> list[dict]:
    """규칙 '채택_2' — DB 상표명·유사군 있는 것에서 200(seed 0)."""
    ms = context["ms"]
    records = sorted((r for r in ms.state.records if r.title and r.goods), key=lambda r: r.appno)
    picked = random.Random(SEED).sample(records, min(SAME_NAME_N, len(records)))[:limit]
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    presets = control["대조군"]["업종_세트"]
    owner_of = {r.appno: context["nst"].split_applicants(r.applicant or "", context["aliases"])
                for r in ms.state.records}
    out = []
    for record in sorted(picked, key=lambda r: r.appno):
        owners = owner_of[record.appno]
        accepted = {r.appno for r in ms.state.records
                    if r.appno == record.appno or (owners and owner_of[r.appno] & owners)}
        free = [p for p in presets if not (set(p[2]) & set(record.goods))]
        other = random.Random(f"{SEED}|업종|{record.appno}").choice(free) if free else None
        out.append({"출원번호": record.appno, "이름": record.title, "유사군": sorted(record.goods),
                    "인정": sorted(accepted), "무관_업종": other})
    return out


def run_same_name(context: dict, queries: list[dict], models: dict,
                  capture: Capture | None) -> list[dict]:
    out = []
    for index, query in enumerate(queries):
        row = {"출원번호": query["출원번호"], "인정": query["인정"], "방식": {}}
        row["방식"]["원래 업종"] = search(context, models, capture, name=query["이름"],
                                      goods_codes=query["유사군"])
        if query["무관_업종"]:
            row["방식"]["무관한 업종"] = search(context, models, None, name=query["이름"],
                                         goods_codes=sorted(query["무관_업종"][2]))
        out.append(row)
        if (index + 1) % 40 == 0:
            print(f"    같은 이름 {index + 1}/{len(queries)}", flush=True)
    return out


def run_sample_a(context: dict, models: dict, capture: Capture | None,
                 limit: int | None) -> list[dict]:
    out = []
    for query in context["A"][:limit]:
        cited, owners = first.a_relations(context, query)
        unrelated = first.unrelated_filter(context, owners, cited)
        image = context["service"](query.path.read_bytes())
        entry = search(context, models, capture, image=image, name=query.name,
                       goods_codes=sorted(query.goods) or None)
        entry["무관"] = sorted(c for c in entry[next(iter(models))]["후보"] if unrelated(c))
        out.append({"질의": query.key, "업종": bool(query.goods), "검색": entry})
    return out


# ---- 4. 채택 조건·진단 --------------------------------------------------------------------------

def check_1(validation: list[dict], thresholds: dict, label: str, model: dict) -> dict:
    block, passed = {}, True
    for key in SETS:
        values = query_maxima(validation, model, key)
        cuts = thresholds[key]
        part = {}
        for grade, share in TARGETS.items():
            cut = float(cuts[grade])
            observed = ns.rate_at_least(values, cut)
            ok = observed is not None and observed <= share + 1e-12
            refit = None
            if not ok and values:
                refit, _, _ = first.fit_cut(values, share)
                ok = refit is not None and refit - cut <= TOLERANCE + 1e-12
            part[grade] = {"기준": cut, "확인용_비율": observed, "n": len(values),
                           "넘을_때_확인용_맞춘_값": refit, "통과": ok}
            passed = passed and ok
        mode = MODE_OF[key]
        engine = {}
        for tag in ("지금", label):
            grades = [row["방식"][mode][tag]["전체"] for row in validation]
            engine[tag] = {g: sum(ns.at_least(x, g) for x in grades) / len(grades)
                           for g in (REVIEW, RISK)} if grades else None
        not_more = engine["지금"] is not None and all(
            engine[label][g] <= engine["지금"][g] + 1e-12 for g in (REVIEW, RISK))
        part["엔진_전체_등급"] = {**engine, "통과": not_more}
        passed = passed and not_more
        block[key] = part
    return {"집합": block, "통과": passed}


def check_2(rows: list[dict], label: str) -> dict:
    def best(entry: dict, accepted: set[str], top_only: bool) -> str | None:
        ids = entry["상위"] if top_only else list(entry["후보"])
        grades = [entry["후보"][i][0] for i in ids if i in accepted]
        return max(grades, key=rm.GRADES.index) if grades else None

    out = {}
    for tag in ("지금", label):
        success, risk, other_best, other_overall = [], [], Counter(), Counter()
        for row in rows:
            accepted = set(row["인정"])
            entry = row["방식"]["원래 업종"][tag]
            top = best(entry, accepted, True)
            success.append(ns.at_least(top, REVIEW))
            risk.append(top == RISK)
            unrelated = row["방식"].get("무관한 업종")
            if unrelated:
                other_best[best(unrelated[tag], accepted, False) or "풀 밖"] += 1
                other_overall[unrelated[tag]["전체"] or "후보 없음"] += 1
        out[tag] = {"질의": len(rows), "성공": round(sum(success) / len(rows), 4) if rows else None,
                    "위험(보고만)": round(sum(risk) / len(rows), 4) if rows else None,
                    "무관한_업종_인정_최고_등급(보고만)": dict(other_best),
                    "무관한_업종_전체_등급(보고만)": dict(other_overall)}
    value = out[label]["성공"]
    return {**out, "통과": value is not None and value >= SAME_NAME_MIN - 1e-12}


def cited_rows(case_ids: set[str]) -> list[tuple[dict, str]]:
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    out = []
    for row in t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY).rows:
        if row.get("pair_source") != "trial" or str(row.get("심판번호")) not in case_ids:
            continue
        if not tr.has_name(row):
            continue
        features = t4.service_features(row, image_column=t4.RAW_IMAGE)
        features["mark_type"] = "결합-문자요부" if features["x2_whole"] is not None else "문자"
        out.append((features, row.get("최종라벨")))
    return out


def check_3(rows: list[tuple[dict, str]], models: dict, label: str) -> dict:
    out = {"쌍": len(rows)}
    for tag in ("지금", label):
        grades = [engine_grade(features, models[tag]) for features, _ in rows]
        flags = [ns.at_least(g, REVIEW) for g in grades]
        out[tag] = {"등급": ns.distribution(grades),
                    "검토_권장_이상": round(sum(flags) / len(flags), 4) if flags else None,
                    "유사_중_검토_권장_이상": sum(1 for f, (_, lab) in zip(flags, rows)
                                           if f and lab == "유사")}
    now, new = out["지금"]["검토_권장_이상"], out[label]["검토_권장_이상"]
    out["차"] = None if now is None or new is None else round(new - now, 4)
    out["통과"] = now is not None and new is not None and new >= now - CITED_DROP_MAX - 1e-12
    return out


def real_features(*sources) -> list[dict]:
    out = []
    for source in sources:
        for item in source:
            for entry in _entries(item):
                out.extend(f for f in entry.get("특징", {}).values()
                           if f is not None and f.get("x4") is not None)
    return out


def _entries(item: dict) -> list[dict]:
    if "방식" in item:
        return list(item["방식"].values())
    return [item["검색"]]


def check_5(model: dict, features_list: list[dict]) -> dict:
    blocks = {"base": model, **model["patterns"],
              **{rm.NAMELESS_PREFIX + k: v for k, v in model[rm.NAMELESS_KEY].items()}}
    monotone = {key: len(rm.monotone_violations(block["coefficients"]))
                for key, block in blocks.items()}
    coupling = rm.coupling_violations(model)
    ordered = {key: ns.ordered(rm.grade_thresholds_for(model, key)) for key in SETS}
    grid = grid_check(model)
    real = direction_check(features_list, model)
    grid_bad = sum(sum(v["어김"].values()) for v in grid.values())
    passed = (all(ordered.values()) and not any(monotone.values()) and not coupling
              and grid_bad == 0 and not real["어김"])
    return {"순서": ordered, "단조_위반": monotone, "결합_위반": len(coupling),
            "결합_위반_예": coupling[:5], "격자": grid, "실제_후보": real, "통과": passed}


def check_6(controls: list[dict], model: dict, label: str) -> dict:
    floor = float(model["coupling"]["floors"]["x4"])
    bad, examples, seen = 0, [], 0
    for row in controls:
        for mode, plain_mode in NO_GOODS_MODE.items():
            entry, plain = row["방식"][mode], row["방식"][plain_mode]
            for appno, values in entry[label]["후보"].items():
                grade, _, _, x4 = values[:4]
                if x4 is None or x4 >= floor:
                    continue
                seen += 1
                if grade != RISK:
                    continue
                if appno in plain[label]["후보"]:
                    without = plain[label]["후보"][appno][0]
                else:
                    features = entry["특징"].get(appno)
                    without = (rm.risk_score({**features, "x4": None}, model).grade
                               if features else None)
                if without != RISK:
                    bad += 1
                    if len(examples) < 10:
                        examples.append({"이름": row["이름"], "방식": mode, "후보": appno,
                                         "x4": x4, "업종_없이": without})
    return {"본_후보(업종 다름)": seen, "어긴_후보": bad, "예": examples, "통과": bad == 0}


def check_7(now_auc: dict, new_auc: dict) -> dict:
    out, passed = {}, True
    for key in SETS:
        a, b = now_auc[key]["AUC"], new_auc[key]["AUC"]
        ok = a is not None and b is not None and b >= a - AUC_DROP_MAX - 1e-12
        out[key] = {"지금": a, "변형": b, "차": None if a is None or b is None else round(b - a, 4),
                    "통과": ok}
        passed = passed and ok
    return {"집합": out, "통과": passed}


def diagnosis(controls: list[dict], sample_a: list[dict], model: dict) -> dict:
    """진단 (가) — 원칙 위반 수·지름길 크기(무관한 후보)."""
    floor = float(model["coupling"]["floors"]["x4"])
    common = model["grade_thresholds"]
    violations: Counter = Counter()
    checked: Counter = Counter()
    gaps: dict = {}

    def visit(entry: dict, source: str) -> None:
        unrelated = set(entry.get("무관") or ())
        for appno, features in entry.get("특징", {}).items():
            if features is None or features.get("x4") is None:
                continue
            result = rm.risk_score(features, model)
            if result.pattern not in SETS:
                continue
            pair = rm.risk_score({**features, "x4": None}, model)
            x4 = float(features["x4"])
            if x4 < floor:
                checked[f"{source} {result.pattern}"] += 1
                if rm.GRADES.index(result.grade) > rm.GRADES.index(pair.grade):
                    violations[f"{source} {result.pattern}"] += 1
            if appno not in unrelated:
                continue
            kind = "같은 업종" if x4 >= SAME_GOODS_MIN else ("다른 업종" if x4 < floor else None)
            if kind is None:
                continue
            bucket = ("짝 안전" if pair.prob < common[CAUTION] else
                      ("짝 주의" if pair.prob < common[REVIEW] else "짝 검토 권장 이상"))
            gaps.setdefault(result.pattern, {}).setdefault(bucket, {}).setdefault(
                kind, []).append(float(result.prob))

    for row in controls:
        for mode in NO_GOODS_MODE:
            visit(row["방식"][mode], "대조군")
    for row in sample_a:
        if row["업종"]:
            visit(row["검색"], "표본A")
    table = {}
    for key, buckets in gaps.items():
        table[key] = {}
        for bucket, kinds in buckets.items():
            same, other = kinds.get("같은 업종", []), kinds.get("다른 업종", [])
            mean_same = _round(statistics.fmean(same)) if same else None
            mean_other = _round(statistics.fmean(other)) if other else None
            table[key][bucket] = {"같은 업종 n": len(same), "다른 업종 n": len(other),
                                  "같은 업종 평균": mean_same, "다른 업종 평균": mean_other,
                                  "차": (_round(statistics.fmean(same) - statistics.fmean(other))
                                        if same and other else None)}
    return {"원칙_위반(업종 다름, 집합 등급 > 짝)": dict(violations), "본_후보": dict(checked),
            "지름길_크기": table}


def consistency(model: dict) -> dict:
    """진단 (다) — 같은 이름 제약 최소 여유, 업종 몫 비교."""
    from scripts import train_risk_model_v14_nameless as t2

    nameless = model[rm.NAMELESS_KEY]["x2_whole+x4"]
    named = model["patterns"]["x2_whole+x4"]
    slack = []
    for vertex in rm.nameless_vertices(nameless["features"]):
        low = rm.block_logit(nameless, rm.design_values(vertex), model)
        for distinctive in (True, False):
            high = rm.block_logit(named, rm.design_values(rm.same_name_input(
                vertex, t2.SAME_NAME, distinctive=distinctive)), model)
            slack.append(high - low)
    shares = {}
    for s in SIMILARITY_LEVELS:
        row = {}
        for name_level in (0.0, 1.0):
            point = {"x1_d": name_level, "x2_text_d": name_level, "x3_d": None,
                     "has_meaning_both": False, "has_distinctive_part_a": True,
                     "has_distinctive_part_b": True, "x2_whole": s, "mark_type": "결합-문자요부"}
            row[f"이름 {name_level:g}"] = _round(rm.risk_score({**point, "x4": 1.0}, model).prob
                                                - rm.risk_score({**point, "x4": 0.0}, model).prob)
        image = ns.nameless_features(s, None)
        row["이름 없음(도형계)"] = _round(rm.risk_score({**image, "x4": 1.0}, model).prob
                                     - rm.risk_score({**image, "x4": 0.0}, model).prob)
        shares[str(s)] = row
    return {"같은_이름_최소_여유(로짓)": _round(min(slack)), "업종_몫(겹침 1 − 0)": shares}


def cap_effect_v145(base: dict) -> dict:
    """업종 상한을 v1.4.5 에 켰을 때 — 이름 없는 쪽(4-a 실행의 대조군·표본 A 풀)."""
    floor = float(base["coupling"]["floors"]["x4"])
    with gzip.open(SAVED_V145, "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    changed, seen, examples = 0, 0, []

    def visit(x2, x4, where):
        nonlocal changed, seen
        if x2 is None or x4 is None or x4 >= floor:
            return
        seen += 1
        goods = first.nameless_final_grade(ns.nameless_features(float(x2), float(x4)), base)
        alone = first.nameless_final_grade(ns.nameless_features(float(x2), None), base)
        if rm.GRADES.index(goods) > rm.GRADES.index(alone):
            changed += 1
            if len(examples) < 10:
                examples.append({"어디": where, "x2": x2, "x4": x4, "등급": goods,
                                 "이미지만": alone})

    for item in saved["대조군"]:
        for entry in item["검색"]:
            if entry["방식"] == "이미지+업종":
                for c in entry["풀"]:
                    visit(c["x2"], c["x4"], f"대조군 {item['키']}")
    for row in saved["표본A_이미지+업종"]:
        for c in row["풀"]:
            visit(c["x2"], c["x4"], f"표본A {row['질의']}")
    return {"본_후보(업종 다름)": seen, "등급이_바뀌는_후보": changed, "예": examples}


# ---- 5. 실행 -----------------------------------------------------------------------------------

def command_run(args) -> int:  # noqa: C901 — 단계가 많을 뿐 순서대로
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    paths = _paths(args.out_dir)
    frozen = _check_frozen(paths)
    if frozen is None:
        return EXIT_REFUSED
    if paths["results"].exists() and not args.force:
        print(f"거절: {paths['results']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    base = rm.validate_model(json.loads(BASE_MODEL_PATH.read_text(encoding="utf-8")))
    smoke = bool(args.smoke)
    limit = SMOKE["대조군_이름"] if smoke else None
    timing: dict[str, float] = {}
    results: dict = {"설정_sha256": frozen["설정_sha256"],
                     "스크립트_sha256(고정 때)": frozen["스크립트_sha256"],
                     "스크립트_sha256(잴 때)": first.file_sha256(Path(__file__)),
                     "모델": BASE_VERSION, "스모크": smoke}
    args.out_dir.mkdir(parents=True, exist_ok=True)

    def tick(name: str, began: float) -> None:
        timing[name] = round(time.perf_counter() - began, 1)
        print(f"  {name} {timing[name]}초", flush=True)

    def stop(reason: str) -> int:
        results.update(채택=None, 멈춤=reason, 시간_s=timing, 끝=_now())
        paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                    encoding="utf-8")
        paths["report"].write_text(report_text(results), encoding="utf-8")
        print(f"멈춤: {reason}", file=sys.stderr)
        return EXIT_STOP

    # 1. 새 음성
    began = time.perf_counter()
    current = t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY)
    named_easy = sum(1 for row in current.rows if row.get("pair_source") != "trial"
                     and tr.has_name(row))
    n = SMOKE["음성"] if smoke else named_easy
    negatives, report = build_negatives(n, record_limit=SMOKE["DB_상표"] if smoke else None)
    write_negatives(negatives, paths["negatives"])
    augmented = write_augmented(negatives, paths["easy"])
    results["새_음성"] = {**report, "지금_이름_있는_쉬운_음성": named_easy, "파일": augmented,
                       "sha256": first.file_sha256(paths["negatives"])}
    tick("새 음성", began)

    # 2. 학습(지금 재현 + 변형 둘)
    began = time.perf_counter()
    rows_now = current.rows
    rows_new = t4.load_dataset(tr.DEFAULT_FEATURES, paths["easy"]).rows
    if smoke:
        rows_now, rows_new = smoke_subset(rows_now), smoke_subset(rows_new)
    trained = {"지금": train("지금", rows_now, base)}
    for variant in VARIANTS:
        trained[variant] = train(variant, rows_new, base)
    aucs = {tag: oof_auc(result) for tag, result in trained.items()}
    coefficient_models, repairs = {}, {}
    for variant in VARIANTS:
        model, repair = repair_intercepts(with_named(base, trained[variant]["entries"]))
        repairs[variant] = repair
        if not repair["고침"]:
            return stop(f"변형 {variant}: 반올림 뒤 결합 위반을 절편으로 고치지 못함")
        coefficient_models[variant] = model
    results["학습"] = {
        tag: {"계수": {key: (trained[tag]["entries"][key] if tag == "지금" else
                           {k: coefficient_models[tag]["patterns"][key][k]
                            for k in ("features", "coefficients", "intercept")})
                     for key in SETS},
              "학습_행": trained[tag]["counts"], "제약": trained[tag]["constraints"],
              "최적화": trained[tag]["optimizer"], "OOF_AUC": aucs[tag],
              "걸린_시간_s": trained[tag]["seconds"],
              **({"반올림_보정": repairs[tag]} if tag in repairs else {})}
        for tag in trained}
    results["학습"]["배포_v1.4.5(보고만)"] = {key: {k: base["patterns"][key][k] for k in (
        "features", "coefficients", "intercept")} for key in SETS}
    tick("학습", began)

    # 3. 엔진·검산
    began = time.perf_counter()
    context = ns._context(BASE_MODEL_PATH)  # noqa: SLF001
    ms = context["ms"]
    if ms.state.model.get("version") != BASE_VERSION:
        return stop("엔진이 적재한 모델이 v1.4.5 가 아님")
    context["aliases"] = context.get("aliases") or context["nst"].load_aliases(
        context["nst"].DEFAULT_ALIASES)
    lo.memo_ocr(ms)
    scenario_runs = lo.scenarios(context, {"지금": ms.state.model})
    with gzip.open(SAVED_V145, "rt", encoding="utf-8") as handle:
        saved = json.load(handle)["시나리오"]["L"]
    differ = [key for key, item in saved.items()
              if item.get("전체") != scenario_runs["지금"].get(key, {}).get("전체")
              or [c["id"] for c in item.get("상위", [])]
              != [c["id"] for c in scenario_runs["지금"].get(key, {}).get("상위", [])]]
    results["검산_시나리오"] = {"견준_시나리오": len(saved), "다른_것": differ, "같음": not differ}
    tick("엔진·검산", began)
    if differ:
        return stop("바꾸기 전 시나리오가 v1.4.5 저장값과 다름")

    # 4. 대조군 기준용(지금, 특징) → 기준 → 후보
    began = time.perf_counter()
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    capture = Capture(ms)
    try:
        base_rows = run_control(context, control_items(control, "기준용", limit),
                                {"지금": ms.state.model}, capture)
        tick("대조군 기준용(지금)", began)
        candidates, results["기준"] = {}, {}
        for variant in VARIANTS:
            fitted = {key: start_thresholds(query_maxima(base_rows, coefficient_models[variant],
                                                         key), base["grade_thresholds"])
                      for key in SETS}
            results["기준"][variant] = fitted
            thresholds = {key: fitted[key]["기준"] for key in SETS}
            if not all(ns.ordered(t) for t in thresholds.values()):
                return stop(f"변형 {variant}: 기준 순서가 맞지 않음")
            candidate = with_named(coefficient_models[variant],
                                   {key: {k: coefficient_models[variant]["patterns"][key][k]
                                          for k in ("features", "coefficients", "intercept")}
                                    for key in SETS}, thresholds=thresholds)
            candidate["version"] = NEW_VERSION
            for key in SETS:
                candidate["patterns"][key]["meta"] = {
                    k: trained[variant]["counts"][key][k] for k in (
                        "n", "n_심결", "n_쉬운_음성", "유사", "비유사", "가중_유사", "가중_비유사",
                        "자기_패턴_행", "자기_패턴_심결")}
            candidate["meta"]["named_goods_product"] = {
                "calibrated_at": datetime.now().date().isoformat(), "variant": variant,
                "derived_from": base["version"], "rule_sha256": frozen["설정_sha256"],
                "script": "ml/scripts/named_goods_product.py",
                "training": {"negatives_sha256": results["새_음성"]["sha256"],
                             "negatives": n, "fixed": ["base", "x2_whole", "noname:x2_whole",
                                                       "noname:x2_whole+x4"],
                             "constraints": trained[variant]["constraints"],
                             "optimizer": trained[variant]["optimizer"],
                             "rounding_repair": repairs[variant]["걸음"]},
                "thresholds": fitted,
                "previous_blocks": {key: {k: base["patterns"][key][k] for k in (
                    "features", "coefficients", "intercept")} for key in SETS},
                "adopted": None}
            rm.validate_model({**candidate, "version": BASE_VERSION})
            candidates[variant] = candidate
        models = {"지금": ms.state.model, **candidates}

        # 5. 검색(지금·L·S)
        began = time.perf_counter()
        for row in base_rows:  # 기준용 — 변형만 더 돌린다
            source_models = {v: candidates[v] for v in VARIANTS}
            image = context["service"]({q.key: q for q in context["A"]}[row["이미지"]]
                                       .path.read_bytes())
            item = next(i for i in control_items(control, "기준용", limit)
                        if i["이름"] == row["이름"])
            goods = sorted(item["유사군"]) or None
            for mode, with_image, with_goods in MODES:
                extra = search(context, source_models, None, name=row["이름"],
                               image=image if with_image else None,
                               goods_codes=goods if with_goods else None)
                row["방식"][mode].update(extra)
        tick("대조군 기준용(변형)", began)
        began = time.perf_counter()
        validation = run_control(context, control_items(control, "확인용", limit), models,
                                 capture)
        tick("대조군 확인용", began)
        began = time.perf_counter()
        same_queries = same_name_queries(context, SMOKE["같은_이름"] if smoke else None)
        same_rows = run_same_name(context, same_queries, models, capture)
        tick("같은 이름", began)
        began = time.perf_counter()
        sample_rows = run_sample_a(context, models, capture, SMOKE["표본A"] if smoke else None)
        tick("표본 A", began)
    finally:
        capture.close()
    began = time.perf_counter()
    cap_model = copy.deepcopy(ms.state.model)
    cap_model[rm.GOODS_CAP_KEY] = {"enabled": True}
    scenario_runs.update(lo.scenarios(context, {**candidates, "지금+업종 상한": cap_model}))
    tick("시나리오", began)

    # 6. 채택 조건·진단
    began = time.perf_counter()
    case_ids = {query.key.split(":")[1] for query in context["A"]}
    cited = cited_rows(case_ids)
    features_real = real_features(validation, same_rows, sample_rows) + real_features(base_rows)
    passed, cited_rate = {}, {}
    results["변형"] = {}
    for variant in VARIANTS:
        candidate = candidates[variant]
        thresholds = {key: results["기준"][variant][key]["기준"] for key in SETS}
        block = {"채택_1": check_1(validation, thresholds, variant, candidate),
                 "채택_2": check_2(same_rows, variant),
                 "채택_3": check_3(cited, models, variant),
                 "채택_4": oof_changes(trained["지금"], trained[variant], base, candidate),
                 "채택_5": check_5(candidate, features_real),
                 "채택_6": check_6(base_rows + validation, candidate, variant),
                 "채택_7": check_7(aucs["지금"], aucs[variant])}
        block["통과"] = all(block[f"채택_{i}"]["통과"] for i in range(1, 8))
        block["진단"] = {"학습": probe_table(candidate), "일관성": consistency(candidate),
                       "지름길·원칙(변형)": diagnosis(validation, sample_rows, candidate)}
        block["전후"] = before_after(base_rows, validation, same_rows, sample_rows, variant)
        results["변형"][variant] = block
        passed[variant] = block["통과"]
        cited_rate[variant] = block["채택_3"][variant]["검토_권장_이상"]
    results["진단_바꾸기_전"] = {"원칙·지름길": diagnosis(validation, sample_rows, base),
                           "학습": probe_table(base), "일관성": consistency(base),
                           "채택_6(지금)": check_6(base_rows + validation, base, "지금")}
    results["업종_상한_v1.4.5"] = {
        "이름_없는_쪽(4-a 실행 풀)": cap_effect_v145(base),
        "이름_있는_쪽(이 실행 지금 검색 — 진단 (가) 의 원칙 위반)":
            results["진단_바꾸기_전"]["원칙·지름길"]["원칙_위반(업종 다름, 집합 등급 > 짝)"],
        "시나리오": [key for key in scenario_runs["지금"]
                  if scenario_runs["지금"][key].get("전체")
                  != scenario_runs["지금+업종 상한"].get(key, {}).get("전체")]}
    results["시나리오"] = {tag: lo.scenario_table({"전": scenario_runs["지금"],
                                                "후": scenario_runs[tag]})
                        for tag in (*VARIANTS, "지금+업종 상한")}
    chosen = choose(passed, cited_rate)
    results["판정"] = {"통과": passed, "인용상표_검토_권장_이상": cited_rate, "고른_변형": chosen}
    results["채택"] = chosen is not None
    for variant in VARIANTS:
        candidates[variant]["meta"]["named_goods_product"]["adopted"] = (variant == chosen)
    tick("채택 조건", began)
    results["시간_s"] = timing
    results["걸린_시간_s"] = round(time.perf_counter() - started, 1)
    results["끝"] = _now()
    for variant in VARIANTS:
        paths[f"candidate_{variant}"].write_text(
            json.dumps(candidates[variant], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with gzip.open(paths["searches"], "wt", encoding="utf-8") as handle:
        json.dump({"대조군_기준용": base_rows, "대조군_확인용": validation, "같은_이름": same_rows,
                   "표본A": sample_rows, "시나리오": scenario_runs}, handle, ensure_ascii=False)
    paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    paths["report"].write_text(report_text(results), encoding="utf-8")
    print(json.dumps(results["판정"], ensure_ascii=False))
    print(f"→ {paths['results']}\n→ {paths['report']}")
    return 0 if results["채택"] else EXIT_STOP


def before_after(base_rows: list[dict], validation: list[dict], same_rows: list[dict],
                 sample_rows: list[dict], label: str) -> dict:
    out: dict = {"대조군": {}, "같은_이름": {}, "표본A": {}}
    for half, rows in (("기준용", base_rows), ("확인용", validation)):
        for mode, _, _ in MODES:
            out["대조군"][f"{half} {mode}"] = {
                tag: ns.distribution(row["방식"][mode][tag]["전체"] for row in rows)
                for tag in ("지금", label)}
    for mode in ("원래 업종", "무관한 업종"):
        rows = [row for row in same_rows if mode in row["방식"]]
        out["같은_이름"][mode] = {
            tag: ns.distribution(row["방식"][mode][tag]["전체"] for row in rows)
            for tag in ("지금", label)}
    for kind in ("업종 있음", "업종 없음"):
        rows = [row for row in sample_rows if row["업종"] == (kind == "업종 있음")]
        before = [row["검색"]["지금"]["전체"] for row in rows]
        after = [row["검색"][label]["전체"] for row in rows]
        out["표본A"][kind] = {"질의": len(rows), "지금": ns.distribution(before),
                             "변형": ns.distribution(after),
                             "바뀐_질의": sum(1 for b, a in zip(before, after) if b != a)}
    return out


# ---- 6. 적용·확인 -----------------------------------------------------------------------------

def command_apply(args) -> int:
    paths = _paths(args.out_dir)
    if _check_frozen(paths, model_may_change=True) is None:
        return EXIT_REFUSED
    results = json.loads(paths["results"].read_text(encoding="utf-8"))
    if results.get("스모크"):
        print("거절: 스모크 결과입니다 — 적용하지 않습니다", file=sys.stderr)
        return EXIT_REFUSED
    chosen = (results.get("판정") or {}).get("고른_변형")
    if not results.get("채택") or chosen not in VARIANTS:
        print("거절: 규칙상 채택된 변형이 없습니다 — 적용하지 않습니다", file=sys.stderr)
        return EXIT_REFUSED
    if NEW_MODEL_PATH.exists() and not args.force:
        print(f"거절: {NEW_MODEL_PATH} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    candidate = json.loads(paths[f"candidate_{chosen}"].read_text(encoding="utf-8"))
    rm.validate_model({**candidate, "version": BASE_VERSION})
    NEW_MODEL_PATH.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    print(f"썼다: {NEW_MODEL_PATH} ({candidate['version']}, 변형 {chosen})")
    return 0


def command_verify(args) -> int:
    """기본 모델을 v1.4.6 으로 바꾼 뒤 — 기본 엔진으로 다시 돌려 고른 변형의 실행과 같은지."""
    paths = _paths(args.out_dir)
    if _check_frozen(paths, model_may_change=True) is None:
        return EXIT_REFUSED
    if rm.MODEL_VERSION != NEW_VERSION or rm.resolve_model_path() != NEW_MODEL_PATH:
        print("거절: 서비스 기본 모델이 v1.4.6 이 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    results = json.loads(paths["results"].read_text(encoding="utf-8"))
    chosen = results["판정"]["고른_변형"]
    with gzip.open(paths["searches"], "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    context = ns._context(NEW_MODEL_PATH)  # noqa: SLF001
    ms = context["ms"]
    candidate = json.loads(paths[f"candidate_{chosen}"].read_text(encoding="utf-8"))
    if ms.state.model.get("version") != NEW_VERSION or ms.state.model["patterns"] != candidate[
            "patterns"]:
        print("거절: 엔진이 적재한 모델이 고른 변형의 후보와 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    context["aliases"] = context.get("aliases") or context["nst"].load_aliases(
        context["nst"].DEFAULT_ALIASES)
    lo.memo_ocr(ms)
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    mismatch, checked = Counter(), Counter()

    def same(got: dict, old: dict) -> bool:
        return got["전체"] == old["전체"] and got["상위"] == old["상위"]

    for half, key in (("기준용", "대조군_기준용"), ("확인용", "대조군_확인용")):
        again = run_control(context, control_items(control, half, None), {"기본": ms.state.model},
                            None)
        for new, old in zip(again, saved[key]):
            for mode, _, _ in MODES:
                checked[key] += 1
                mismatch[key] += int(not same(new["방식"][mode]["기본"], old["방식"][mode][chosen]))
    queries = same_name_queries(context, None)
    again = run_same_name(context, queries, {"기본": ms.state.model}, None)
    for new, old in zip(again, saved["같은_이름"]):
        for mode in new["방식"]:
            checked["같은_이름"] += 1
            mismatch["같은_이름"] += int(not same(new["방식"][mode]["기본"],
                                                old["방식"][mode][chosen]))
    again = run_sample_a(context, {"기본": ms.state.model}, None, None)
    for new, old in zip(again, saved["표본A"]):
        checked["표본A"] += 1
        mismatch["표본A"] += int(not same(new["검색"]["기본"], old["검색"][chosen]))
    default = lo.scenarios(context, {"기본": ms.state.model})["기본"]
    after = saved["시나리오"][chosen]
    scenario_diff = [key for key, item in default.items()
                     if item.get("전체") != after.get(key, {}).get("전체")
                     or [c["id"] for c in item.get("상위", [])]
                     != [c["id"] for c in after.get(key, {}).get("상위", [])]]
    verify = {"모델": ms.state.model["version"], "변형": chosen, "다시_돌린_검색": dict(checked),
              "불일치": dict(mismatch), "시나리오_다른_것": scenario_diff,
              "통과": not any(mismatch.values()) and not scenario_diff,
              "걸린_시간_s": round(time.perf_counter() - started, 1), "끝": _now()}
    paths["verify"].write_text(json.dumps(verify, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")
    print(json.dumps(verify, ensure_ascii=False))
    return 0 if verify["통과"] else EXIT_STOP


# ---- 보고 --------------------------------------------------------------------------------------

def report_text(results: dict) -> str:
    lines = ["# 이름 있는 업종 두 벌의 곱하기 항(변형 L·S) — 보고", "",
             f"- 설정 sha256 `{results['설정_sha256']}` · 스크립트 고정 "
             f"`{results['스크립트_sha256(고정 때)']}` · 잴 때 "
             f"`{results['스크립트_sha256(잴 때)']}`",
             f"- 스모크 {results['스모크']} · 판정 {results.get('판정')} · 멈춤 "
             f"{results.get('멈춤')}",
             ""]
    for key in ("새_음성", "학습", "기준", "검산_시나리오", "진단_바꾸기_전", "업종_상한_v1.4.5"):
        if key in results:
            lines += [f"## {key}", "", "```",
                      json.dumps(results[key], ensure_ascii=False)[:5000], "```", ""]
    for variant, block in (results.get("변형") or {}).items():
        lines += [f"## 변형 {variant} — 통과 {block['통과']}", ""]
        for i in range(1, 8):
            lines += [f"### 채택_{i} — {block[f'채택_{i}']['통과']}", "", "```",
                      json.dumps(block[f"채택_{i}"], ensure_ascii=False)[:3000], "```", ""]
        lines += ["### 진단·전후", "", "```",
                  json.dumps({"진단": block["진단"], "전후": block["전후"]},
                             ensure_ascii=False)[:5000], "```", ""]
    demo = ("F2", "F1", "F3", "S1")
    for tag, rows in (results.get("시나리오") or {}).items():
        ordered_rows = sorted(rows, key=lambda r: (r["키"] not in demo,
                                                   demo.index(r["키"]) if r["키"] in demo else 0))
        lines += [f"## 시나리오 16종 — {tag}(시연 넷 먼저)", "",
                  "| 키 | 제목 | 지금 | 뒤 | 1위(지금 → 뒤) |", "|---|---|---|---|---|"]
        for row in ordered_rows:
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
    parser.add_argument("--smoke", action="store_true",
                        help="시험 실행 — 학습까지 일부 표본으로만(--out-dir 를 따로)")
    args = parser.parse_args(argv)
    if args.smoke and args.out_dir.resolve() == TRIALS.resolve():
        print("거절: --smoke 는 --out-dir 를 따로 주세요", file=sys.stderr)
        return EXIT_REFUSED
    return {"freeze": command_freeze, "run": command_run, "apply": command_apply,
            "verify": command_verify}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
