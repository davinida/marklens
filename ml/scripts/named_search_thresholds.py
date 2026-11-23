"""이름 있는 입력의 등급 하한 — 실제 검색 기준(대조군). 계수·축·후보 풀·규칙은 그대로 두고, 이름
있는 계수 집합 4벌(base·x2_whole·x4·x2_whole+x4)의 모델 위험도 등급 하한만 질의 단위(무관한 후보 중
최고 위험도)로 다시 맞춘다. 지금 하한(주의 0.0902·검토 권장 0.1805·위험 0.5902)은 심결 쌍 단위로
정한 값이라, 후보 수십 개 중 최고 등급인 화면의 전체 등급은 지어낸 이름도 늘 검토 권장 이상이다(UI
평가 P0-1). KIPRIS 호출 0.

    ml/venv/bin/python ml/scripts/named_search_thresholds.py freeze    # 0. 규칙 해시(실행 전)
    ml/venv/bin/python ml/scripts/named_search_thresholds.py control   # 1. 대조군 만들기(약 15분)
    ml/venv/bin/python ml/scripts/named_search_thresholds.py run       # 2. 진단·하한·채택 조건

산출(비공개, ml/data/trials/): named_search_thresholds_{rule,control,results}.json·_report.md·
_searches.json.gz. 규칙·목표·채택 조건(RULE)은 실행 전에 고정해 해시를 남기고 진단 결과를 보고
바꾸지 않는다. 고정본과 다르면 거절(종료 코드 4), 멈춤·미달이면 종료 코드 3(새 계수 JSON 은 쓰지
않는다 — 적용은 채택된 뒤 따로).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import multiprocessing
import os
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
for _root in (ML_ROOT, REPO_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from src.model import risk_model as rm  # noqa: E402

TRIALS = ML_ROOT / "data" / "trials"
STEM = "named_search_thresholds"
SEED = 0
EXIT_STOP = 3
EXIT_REFUSED = 4
NEW_VERSION = "risk_model_v1.4.1"
V13_INPUTS = Path.home() / "marklens-archive" / "trials-backup-20261119-enrich"  # v1.3 학습 입력
N_PER_LANG = 100
STREAM_FACTOR = 6  # 언어마다 뽑아 두는 후보 이름 수 = N_PER_LANG × 이 값
TARGETS = {"검토 권장": 0.10, "위험": 0.02}
CONFIRM_TOLERANCE = 0.0224  # 이름 없는 하한의 표본 A−B 차이 최댓값(이미지+상품 위험 0.7892−0.7668)
PRECISION_MIN = 0.70
CITED_RATIO_MIN = 0.5
STOP_SHARE = 0.5
DISPLAY_TOP = 5  # 서비스 표시 개수(API top_k 기본) — 전체 등급은 이 안의 최고 등급(엔진 _overall)
LP_EPS = 1e-6
REVIEW, RISK = "검토 권장", "위험"
GOODS_FLOOR, NAMELESS_FLOOR, FIGURE_TRIGGER = "goods_floor", "nameless_floor", "figure_x2_img"
NAME_AXES = ("x1_d", "x2_text_d", "x3_d")
# (방식, 이 방식의 이름 있는 후보가 쓰는 계수 집합, 업종, 이미지)
MODES = (("이름만", "base", False, False), ("이름+업종", "x4", True, False),
         ("이름+이미지", "x2_whole", False, True), ("이름+이미지+업종", "x2_whole+x4", True, True))
FULL_MODE = MODES[-1][0]
# 권리범위확인의 인용상표(상표A) 권리자 = 질의(확인대상표장) 쪽의 상대 당사자
CITED_OWNER_PARTY = {"권리범위확인(적극적)": "청구인", "권리범위확인(소극적)": "피청구인"}
NAMELESS_REFERENCE = {  # 이름 없는 하한의 목표(참고) — 이름 알 때 그 등급 이상 쌍 비율(설계 §7-4-4)
    "이미지만": {"주의": 0.520, "검토 권장": 0.112, "위험": 0.0023},
    "이미지+상품": {"주의": 0.786, "검토 권장": 0.307, "위험": 0.0028}}

WORDS = {
    "ko": {
        "mod": ["푸른", "작은", "따뜻한", "행복한", "맑은", "고운", "오래된", "조용한",
                "달콤한", "하얀", "노란", "빨간", "초록", "둥근", "느린", "즐거운", "멋진",
                "소박한", "포근한", "싱그러운", "반짝이는", "우리", "오늘", "매일", "첫", "옛",
                "큰", "새벽", "단골", "정다운"],
        "noun": ["숲", "정원", "마을", "바다", "하늘", "언덕", "골목", "등대", "다락", "창가",
                 "달빛", "햇살", "구름", "바람", "섬", "호수", "나무", "꽃밭", "들판", "우물",
                 "시냇물", "별빛", "노을", "봄날", "여름", "가을", "겨울", "고양이", "곰", "토끼",
                 "참새", "사과", "감귤", "보리", "소나무", "대나무", "돌담", "마당", "오솔길",
                 "징검다리"],
        "biz": ["커피", "베이커리", "식당", "공방", "서점", "꽃집", "세탁소", "치킨", "분식",
                "미용실", "문구", "약국", "안경", "피자", "국수", "떡집", "정육점", "반찬", "카페",
                "제과", "김밥", "수선", "철물", "사진관", "학원"],
    },
    "en": {
        "mod": ["Blue", "Little", "Golden", "Happy", "Green", "Urban", "Sunny", "Daily", "Cozy",
                "Quiet", "Silver", "Wild", "Lucky", "Gentle", "Bright", "Sweet", "Fresh",
                "Humble", "Northern", "Rustic", "Velvet", "Morning", "Honest", "Simple", "Merry",
                "Brave", "Calm", "Hidden", "Proud", "Tiny"],
        "noun": ["Bear", "Garden", "Forest", "River", "Harbor", "Lantern", "Meadow", "Orchard",
                 "Pebble", "Willow", "Maple", "Sparrow", "Fox", "Otter", "Owl", "Cedar", "Clover",
                 "Harvest", "Island", "Valley", "Canyon", "Lighthouse", "Cottage", "Barn",
                 "Bridge", "Feather", "Pine", "Acorn", "Comet", "Ember", "Fern", "Hollow",
                 "Lagoon", "Moss", "Thistle", "Wren", "Badger", "Juniper", "Tide", "Breeze"],
        "biz": ["Coffee", "Bakery", "Kitchen", "Studio", "Market", "Books", "Florist", "Laundry",
                "Pizza", "Noodle", "Salon", "Pharmacy", "Optical", "Deli", "Bistro", "Diner",
                "Grill", "Creamery", "Tailor", "Hardware", "Photo", "Academy", "Butcher",
                "Tea House", "Bagel"],
    },
}
TEMPLATES = (("mod", "noun"), ("noun", "biz"), ("mod", "noun", "biz"))

# 규칙(실행 전에 고정 — 진단 결과를 보고 바꾸지 않는다) ------------------------------------------
RULE = {
    "대조군_이름": (
        "실제 가게 이름처럼 보이는 지어낸 상표명. 낱말 목록 WORDS(한글·영문 각각 꾸밈말 30·"
        "명사 40·업종어 25)와 틀 TEMPLATES(꾸밈말+명사, 명사+업종어, 꾸밈말+명사+업종어)에서 "
        "언어마다 random.Random('0|<언어>') 로 틀 하나·칸마다 낱말 하나를 뽑아 띄어 쓴다(같은 "
        "낱말 두 번·이미 나온 이름은 건너뜀, 언어마다 600개까지). 무작위 글자 조합은 쓰지 "
        "않는다. 한글 100·영문 100."),
    "대조군_거르기": (
        "뽑은 순서대로, DB 의 상표명 있는 레코드(multi_search.state.records 중 title 있는 것) "
        "전부와 서비스 쌍 축(compute_pair_axes(질의 업종, 후보 유사군, X3 켬) → model_features)"
        "을 계산해 단독 축 규칙(계수 JSON standalone_thresholds — x1_d 0.98·x2_text_d 0.75·"
        "x3_d 0.7707, 결측 아닐 때 이상)이 하나라도 걸리면 뺀다. 질의 업종은 '없음'과 '그 "
        "이름의 업종 세트' 두 맥락 모두. 언어마다 앞에서부터 100개가 남을 때까지(모자라면 "
        "멈춤)."),
    "대조군_나누기": (
        "언어마다 남은 100개를 random.Random(0) 으로 섞어 앞 50 기준용·뒤 50 확인용 — 기준용 "
        "100(한글 50·영문 50)·확인용 100. 확인용은 하한을 정할 때 쓰지 않는다."),
    "업종": (
        "이름마다 업종 세트(shared/goods_map/business_presets.json 25개 — 지정상품을 변환표로 "
        "푼 유사군의 합집합, 서비스 형식 필터) 하나: int(sha256('0|preset|<이름>'), 16) % 25 "
        "번째(파일 순서)."),
    "이미지": (
        "표본 A(nameless_search_thresholds.prepare 의 표본 A 그대로 — 이미지 없음·디코딩 "
        "실패·DB 에 있음·이름 없음·해상도·사진·중복 이미지를 뺀 질의) 질의 이미지마다 서비스 "
        "색인 벡터 전부와의 최대 코사인을 재서 낮은 순(같으면 질의 키 순)으로 앞 절반(⌊n/2⌋). "
        "random.Random(0) 으로 섞어 앞 절반 기준용·나머지 확인용 이미지 집합. 그 집합의 i번째 "
        "이름에 i mod 집합 크기 번째 이미지를 붙인다."),
    "무관한_후보": (
        "후보 풀에서 자기 자신·인용상표(라벨의 인용상표 번호를 DB 출원·등록번호에 대조)·같은 "
        "출원인 후보를 뺀 나머지. 같은 출원인 = 출원인 칸을 '|' 로 나눠 정규화·별칭 표"
        "(shared/applicant_aliases.json) 적용한 이름이 하나라도 겹침. 견줄 출원인 — 대조군: "
        "이미지를 쓴 방식만, 그 이미지의 표본 A 질의 출원·사용자(표본 A 정의 그대로)와 인용상표 "
        "권리자(권리범위확인은 상대 당사자 — 적극적 청구인·소극적 피청구인; 거절결정불복은 "
        "목록에 없어 번호 대조만), 이미지 없는 방식은 빼지 않는다(지어낸 이름). 표본 A: 그 "
        "질의의 출원·사용자와 인용상표 권리자. 표본 B: 자기 자신과 자기 출원인."),
    "검색": (
        "서비스 엔진(multi_search.search_pool, 기본 모델 v1.4, 실제 CLIP·OCR·X3)으로 방식 "
        "이름만·이름+업종·이름+이미지·이름+이미지+업종의 후보 풀 전부를 채점한다(표본 A 는 "
        "업종 있는 질의만 업종 방식). 전체 등급 = 엔진 정렬 앞 5건(API top_k 기본)의 최고 "
        "등급(엔진 _overall)."),
    "검산": (
        "① 지금 하한으로 다시 매긴 후보 등급·정렬·전체 등급이 엔진과 모두 같아야 한다 ② 대조군 "
        "검색에서 단독 축 규칙이 걸린 후보 0. 어긋나면 구현 불일치라 멈춘다."),
    "진단": (
        "대조군 기준용(네 방식)과 표본 A 의 후보 풀에서 최종 등급이 검토 권장 이상인 무관한 "
        "후보(질의·방식·후보마다 한 건)를 등급을 올린 경로로 나눈다: 그 밖의 하한 규칙(업종 "
        "하한 goods_floor·nameless_floor 가 쓰인 판단, 또는 모델 등급이 검토 권장 아래인데 도형 "
        "규칙) / 모델 위험도 기준(그 판단의 계수 집합 하한으로 위험도만으로 검토 권장 이상 — 이름 "
        "있는·없는 판단을 나눠 보고하되 둘 다 모델로 센다) / 단독 축 규칙(모델 등급이 검토 권장 "
        "아래인데 단독 축 규칙). 대조군 기준용과 표본 A 를 합친 건수에서 모델이 아닌 경로가 "
        "절반을 넘으면 멈춘다. 끌어올리는 축: 방식별로 검토 권장 이상인 무관한 후보(이름 있는 "
        "판단)의 축별 평균 기여도·축 값을 그 아래 후보와 견준다."),
    "하한": (
        "이름 있는 계수 집합 P(base·x4·x2_whole·x2_whole+x4)마다, P 가 자연스러운 방식(이름만·"
        "이름+업종·이름+이미지·이름+이미지+업종)의 대조군 기준용 질의 q 에서 M_q = P 로 판단한 "
        "무관한 후보(풀 전체) 중 최고 위험도(그런 후보가 없는 질의는 뺀다, n = 남은 질의). 등급 "
        "g(검토 권장 10%·위험 2%)마다 k = ⌊목표·n⌋, 맞춘 값 = (k+1)번째로 큰 M_q 보다 큰 가장 "
        "작은 넷째 자리 값(그 값 이상인 질의 ≤ k). 새 하한 = max(지금 하한, 맞춘 값)(올리기만), "
        "주의는 지금 값 그대로. 이 값으로 채택 조건을 본다 — 못 넘으면 값을 바꿔 다시 맞추지 "
        "않는다."),
    "채택_1": (
        "대조군 확인용·표본 B 의 같은 방식에서 계수 집합·등급마다 M_q ≥ 새 하한인 질의 비율 ≤ "
        "목표. 넘으면 그 표본에 같은 규칙('하한')을 적용한 하한 − 새 하한 ≤ 0.0224(이름 없는 "
        "하한 때 받아들인 표본 A−B 차이 최댓값, 이미지+상품 위험 0.7892−0.7668)일 때만 통과. "
        "질의가 없으면 잴 수 없어 미달."),
    "채택_2": (
        "위험 등급 정밀도를 지금과 같은 방식으로: v1.3 학습(train_risk_model.run, 기본 설정)을 "
        "학습 입력 사본(~/marklens-archive/trials-backup-20261119-enrich/pairs_features"
        "{,_easy}.csv)으로 다시 돌려 OOF 위험도를 얻고(재현 하한·grade_precision 이 v1.3 JSON 과 "
        "같아야 함, 아니면 멈춤), 심결+cross+db 행에서 행마다 그 행의 계수 집합(관측 축) 새 위험 "
        "하한 이상인 행의 유사 비율 ≥ 0.70(그런 행이 없으면 잴 수 없어 미달)."),
    "채택_3": (
        "① 계수 집합마다 주의 < 검토 권장 < 위험 ② 단조 위반 0(rm.monotone_violations — 계수 "
        "그대로) ③ 같은 후보에 입력을 더 넣어도 최종 등급(단독·도형 규칙 포함)이 내려가지 "
        "않는다: (가) 이름 있는 판단에 이미지·업종 축 하나를 더함(더한 축 ≥ coupling.floors — "
        "결합 제약이 로짓을 보장하는 범위) — 유형 4·관념 게이트·요부 유무 조합마다 선형계획으로 "
        "'아래 집합 최종 등급 ≥ g 이고 위 집합 최종 등급 < g' 인 입력이 있는지 정확히 찾는다 "
        "(나) 이름 없는 판단(업종 하한 포함)에 후보와 같은 이름을 더함(coupling.same_name 범위) "
        "— 같은 방식 (다) 실제 쌍에서 센 (가)의 수 — 학습 행(이름 있는 심결·쉬운 음성, 서비스 "
        "입력)·실제 검색 쌍(대조군·표본 A·B 이름+이미지+업종의 이름 있는 무관한 후보). 셋 다 0. "
        "nameless_floor(사용자가 유형을 도형으로 고친 질의)는 넣지 않는다(보수적)."),
    "채택_4": (
        "표본 A 질의 사건의 인용상표 쌍 = 학습 특징(train_risk_model_v14.load_dataset)의 그 "
        "사건 행 중 두 이름이 다 있는 행(인용상표가 DB 에 없어 검색 결과로는 잴 수 없다)을 "
        "서비스 채점식(유형 문자계 — 이미지 있으면 결합-문자요부, 이미지 축은 원래 값 — 표본 A "
        "질의는 사진이 아님)으로 채점한 검토 권장 이상 비율. 새 하한 비율 ≥ 지금 비율의 0.5배. "
        "유사·비유사 라벨별 비율도 보고."),
    "적용": (
        "채택될 때만 새 계수 JSON(risk_model_v1.4.1): 이름 있는 계수 집합마다 patterns[키]."
        "grade_thresholds, 최상위 grade_thresholds 는 base 의 값. 업종 하한·이름 없는 입력 "
        "하한·사진 규칙·단독 축 규칙·도형 규칙은 그대로."),
}


def _settings() -> dict:
    return {"RULE": RULE, "WORDS": WORDS, "TEMPLATES": TEMPLATES, "N_PER_LANG": N_PER_LANG,
            "STREAM_FACTOR": STREAM_FACTOR, "TARGETS": TARGETS,
            "CONFIRM_TOLERANCE": CONFIRM_TOLERANCE, "PRECISION_MIN": PRECISION_MIN,
            "CITED_RATIO_MIN": CITED_RATIO_MIN, "STOP_SHARE": STOP_SHARE,
            "DISPLAY_TOP": DISPLAY_TOP, "SEED": SEED, "MODES": MODES,
            "CITED_OWNER_PARTY": CITED_OWNER_PARTY, "NEW_VERSION": NEW_VERSION}


def canonical_sha256(value) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rule_sha256() -> str:
    return canonical_sha256(_settings())


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---- 대조군 이름(순수 함수) --------------------------------------------------------------------

def name_stream(lang: str, count: int, seed=SEED) -> list[str]:
    """언어마다 정해진 순서의 후보 이름(같은 낱말 두 번·이미 나온 이름은 건너뜀)."""
    rng = random.Random(f"{seed}|{lang}")
    words = WORDS[lang]
    seen: set[str] = set()
    out: list[str] = []
    attempts = 0
    while len(out) < count and attempts < count * 50:
        attempts += 1
        template = rng.choice(TEMPLATES)
        picked = [rng.choice(words[slot]) for slot in template]
        if len(set(picked)) < len(picked):
            continue
        name = " ".join(picked)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def preset_index(name: str, count: int, seed=SEED) -> int:
    digest = hashlib.sha256(f"{seed}|preset|{name}".encode("utf-8")).hexdigest()
    return int(digest, 16) % count


def split_half(items: list, seed=SEED) -> tuple[list, list]:
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)
    half = len(shuffled) // 2
    return shuffled[:half], shuffled[half:]


def standalone_hits(features: dict, model: dict) -> list[str]:
    """risk_score·엔진 _rule_triggers 와 같은 판정식 — 걸린 단독 축."""
    values = rm.design_values(features)
    return [axis for axis, tau in (model.get("standalone_thresholds") or {}).items()
            if tau is not None and values[rm.MISS_OF[axis]] == 0.0
            and values[axis] >= float(tau)]


# ---- 하한·등급(순수 함수) ----------------------------------------------------------------------

def fit_cut(maxima: list[float], share: float) -> tuple[float | None, int, int]:
    """(맞춘 값, k, n) — (k+1)번째로 큰 값보다 큰 가장 작은 넷째 자리 값, k = ⌊share·n⌋."""
    values = sorted((float(v) for v in maxima), reverse=True)
    n = len(values)
    if not n:
        return None, 0, 0
    k = math.floor(share * n + 1e-9)
    if k >= n:
        return 0.0001, k, n
    return round(math.floor(values[k] * 10000 + 1e-9) / 10000 + 0.0001, 4), k, n


def new_thresholds(current: dict, fitted: dict) -> dict:
    """올리기만 — 주의는 그대로, 검토 권장·위험은 max(지금, 맞춘 값)."""
    out = {"주의": float(current["주의"])}
    for grade in (REVIEW, RISK):
        value = fitted.get(grade)
        out[grade] = round(max(float(current[grade]), 0.0 if value is None else float(value)), 4)
    return out


def rate_at_least(maxima: list[float], cut: float) -> float | None:
    return (sum(1 for v in maxima if v >= cut) / len(maxima)) if maxima else None


def ordered(thresholds: dict) -> bool:
    cuts = [float(thresholds[g]) for g in rm.GRADE_THRESHOLD_KEYS]
    return all(a < b for a, b in zip(cuts, cuts[1:]))


def at_least(grade: str, floor: str = REVIEW) -> bool:
    return rm.GRADES.index(grade) >= rm.GRADES.index(floor)


def higher(a: str, b: str) -> str:
    return a if rm.GRADES.index(a) >= rm.GRADES.index(b) else b


def lifted_by_rule(triggers) -> bool:
    return any(t.startswith("standalone_") or t == FIGURE_TRIGGER for t in triggers)


def named_grade(prob: float, thresholds: dict, triggers) -> str:
    """이름 있는 판단의 최종 등급 — 그 하한으로 정한 등급, 단독·도형 규칙이면 검토 권장 이상."""
    grade = rm.grade_for(prob, thresholds)
    return higher(grade, REVIEW) if lifted_by_rule(triggers) else grade


def recomputed(candidate: dict, named: dict) -> bool:
    """이름 있는 하한으로 등급이 정해지는 후보인가(이름 없는 판단·하한 규칙 판단은 엔진 값
    그대로)."""
    rules = set(candidate["규칙"])
    return (not rm.is_nameless_pattern(candidate["pattern"]) and candidate["pattern"] in named
            and GOODS_FLOOR not in rules and NAMELESS_FLOOR not in rules)


def offline_grade(candidate: dict, named: dict) -> str:
    if not recomputed(candidate, named):
        return candidate["등급"]
    return named_grade(candidate["p"], named[candidate["pattern"]], candidate["규칙"])


def band_position(prob: float, thresholds: dict) -> tuple[int, float]:
    """multi_search.rank_position 과 같은 식(하한을 인자로)."""
    value = round(float(prob), 6)
    grade = rm.grade_for(value, thresholds)
    index = rm.GRADES.index(grade)
    low = 0.0 if index == 0 else float(thresholds[grade])
    high = next((float(thresholds[up]) for up in rm.GRADES[index + 1:]
                 if thresholds.get(up) is not None), 1.0)
    return index, ((value - low) / (high - low) if high > low else 0.0)


def offline_rank(candidate: dict, named: dict) -> tuple[int, float]:
    if not recomputed(candidate, named):
        return tuple(candidate["rank"])
    return band_position(candidate["p"], named[candidate["pattern"]])


def offline_order(candidates: list[dict], named: dict) -> list[dict]:
    """엔진 _candidate_sort_key 와 같은 정렬(하한만 바꿔)."""
    def key(candidate):
        index, band = offline_rank(candidate, named)
        x2_img = candidate["x2_img"]
        return (-index, -band, -(x2_img if x2_img is not None else -1.0), candidate["id"])

    return sorted(candidates, key=key)


def offline_overall(candidates: list[dict], named: dict, top: int = DISPLAY_TOP) -> str | None:
    shown = offline_order(candidates, named)[:top]
    if not shown:
        return None
    return max((offline_grade(c, named) for c in shown), key=rm.GRADES.index)


def path_of(candidate: dict, model: dict) -> str:
    """최종 등급이 검토 권장 이상인 후보를 올린 경로(규칙 '진단')."""
    rules = set(candidate["규칙"])
    if GOODS_FLOOR in rules or NAMELESS_FLOOR in rules:
        return "그 밖의 하한 규칙(업종 하한·nameless_floor)"
    pattern = candidate["pattern"]
    model_grade = rm.grade_for(candidate["p"], rm.grade_thresholds_for(model, pattern))
    if at_least(model_grade):
        return "모델(이름 없는 판단)" if rm.is_nameless_pattern(pattern) else "모델(이름 있는 판단)"
    if any(t.startswith("standalone_") for t in rules):
        return "단독 축 규칙"
    if FIGURE_TRIGGER in rules:
        return "그 밖의 하한 규칙(도형 규칙)"
    return "알 수 없음"


def is_model_path(path: str) -> bool:
    return path.startswith("모델")


def nameless_final_grade(features: dict, model: dict) -> str:
    """이름 없는 판단의 최종 등급 — 엔진 _nameless_judgment(업종 하한)와 같은 판정."""
    result = rm.risk_score(features, model)
    grade = result.grade
    floor = ((model.get("coupling") or {}).get("floors") or {}).get("x4")
    x4 = features.get("x4")
    if (rm.is_nameless_pattern(result.pattern) and features.get("x2_whole") is not None
            and x4 is not None and floor is not None and float(x4) >= float(floor)):
        grade = higher(rm.risk_score({**features, "x4": None}, model).grade, grade)
    return grade


def features_grade(features: dict, model: dict, named: dict | None) -> str:
    """입력 → 최종 등급. 이름 있는 판단은 named 의 그 계수 집합 하한(None 이면 지금 하한) + 단독·
    도형 규칙, 이름 없는 판단은 업종 하한까지(하한 그대로)."""
    result = rm.risk_score(features, model)
    if rm.is_nameless_pattern(result.pattern):
        return nameless_final_grade(features, model)
    if named is None or result.pattern not in named:
        return result.grade
    values = rm.design_values(features)
    triggers = [f"standalone_{axis}" for axis in standalone_hits(features, model)]
    rule = model.get("figure_rule")
    if rule and rm.mark_type_level(features.get("mark_type")) in rm.FIGURE_FAMILY:
        threshold = rule.get("threshold")
        if threshold is not None and values["miss_x2img"] == 0.0 and (
                values["x2_whole"] >= float(threshold)):
            triggers.append(FIGURE_TRIGGER)
    return named_grade(result.prob, named[result.pattern], triggers)


# ---- 입력을 더 넣으면 등급이 내려가는가(채택_3) -------------------------------------------------

def pattern_steps(model: dict) -> list[tuple[str, str, str]]:
    """(아래 계수 집합, 위 계수 집합, 더한 축) — 축 하나를 더 관측하는 이름 있는 패턴 쌍."""
    axes = list(model["pattern_axes"])
    steps = []
    for key in model["patterns"]:
        present = rm.pattern_present(key)
        for axis in present:
            steps.append((rm.pattern_key([x for x in present if x != axis], axes), key, axis))
    return steps


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _affine(block: dict, features: dict, variables: list[str]) -> tuple[float, np.ndarray]:
    """계수 집합 로짓 = c0 + c·v (variables 외 입력은 features 그대로 — 유형·플래그가 정해지면
    설계 항이 축 점수의 아핀 함수라 차분이 정확하다)."""
    base = {**features, **{name: 0.0 for name in variables}}
    c0 = rm.block_logit(block, rm.design_values(base))
    coefs = [rm.block_logit(block, rm.design_values({**base, name: 1.0})) - c0
             for name in variables]
    return c0, np.asarray(coefs, dtype=np.float64)


def _lp_min(c: np.ndarray, constraints: list[tuple[np.ndarray, float]], bounds) -> tuple:
    """min c·v (A v ≤ b, bounds) → (값, v) 또는 (None, None)(불가능)."""
    from scipy.optimize import linprog

    if any(lo > hi for lo, hi in bounds):
        return None, None
    result = linprog(c, A_ub=np.asarray([row for row, _ in constraints]),
                     b_ub=np.asarray([rhs for _, rhs in constraints]), bounds=bounds,
                     method="highs")
    if result.status != 0:
        return None, None
    return float(result.fun), result.x


def exact_step_violations(model: dict, named: dict) -> dict:
    """규칙 '채택_3' (가) — 이름 있는 판단에 축 하나(≥ 결합 하한)를 더해 최종 등급이 내려가는 입력이
    있는가. 단독·도형 규칙은 검토 권장 이상으로만 올리므로, g ≤ 검토 권장 이면 규칙이 안 걸리는
    구역(이름 축 < τ, 도형계면 이미지 < 도형 τ)에서만, g = 위험이면 상자 전체에서 찾는다."""
    floors = model["coupling"]["floors"]
    taus = model.get("standalone_thresholds") or {}
    figure = (model.get("figure_rule") or {}).get("threshold")
    axes = list(model["pattern_axes"])
    checked, violations = 0, []
    for lower, upper, axis in pattern_steps(model):
        present = rm.pattern_present(upper)
        for grade in rm.GRADE_THRESHOLD_KEYS:
            low_cut, high_cut = named[lower][grade], named[upper][grade]
            if low_cut is None or high_cut is None or float(high_cut) <= float(low_cut):
                continue  # 위 집합 하한이 높지 않으면 그 등급에서는 내려갈 수 없다
            for level in rm.TYPE_LEVELS:
                for meaning in (False, True):
                    for part_a in (True, False):
                        for part_b in (True, False):
                            checked += 1
                            upper_f = {"has_meaning_both": meaning,
                                       "has_distinctive_part_a": part_a,
                                       "has_distinctive_part_b": part_b, "mark_type": level,
                                       **{a: (0.0 if a in present else None) for a in axes}}
                            lower_f = {**upper_f, axis: None}
                            names = list(NAME_AXES) + present
                            lower_names = [n for n in names if n != axis]
                            cu0, cu = _affine(model["patterns"][upper], upper_f, names)
                            cl0, partial = _affine(model["patterns"][lower], lower_f, lower_names)
                            cl = np.asarray([0.0 if n == axis else partial[lower_names.index(n)]
                                             for n in names])
                            bounds = []
                            for n in names:
                                lo, hi = (float(floors[axis]) if n == axis else 0.0), 1.0
                                if n == "x3_d" and not meaning:
                                    hi = 0.0
                                if grade != RISK:
                                    tau = taus.get(n)
                                    if tau is not None and (n != "x3_d" or meaning):
                                        hi = min(hi, float(tau) - LP_EPS)
                                    if (n == "x2_whole" and level in rm.FIGURE_FAMILY
                                            and figure is not None):
                                        hi = min(hi, float(figure) - LP_EPS)
                                bounds.append((lo, hi))
                            value, point = _lp_min(
                                cu, [(-cl, cl0 - _logit(float(low_cut)) - LP_EPS)], bounds)
                            if value is None or cu0 + value >= _logit(float(high_cut)) - LP_EPS:
                                continue
                            raw = {n: float(x) for n, x in zip(names, point)}
                            up_input = {**upper_f, **raw}
                            low_input = {**up_input, axis: None}
                            violations.append({
                                "단계": f"{lower} → {upper} ({axis})", "등급": grade,
                                "유형": level, "관념": meaning, "요부없음": not (part_a and part_b),
                                "입력": {n: round(x, 6) for n, x in raw.items()},
                                "아래_p": round(rm.risk_score(low_input, model).prob, 6),
                                "위_p": round(rm.risk_score(up_input, model).prob, 6),
                                "아래_등급": features_grade(low_input, model, named),
                                "위_등급": features_grade(up_input, model, named)})
    by_step = Counter(item["단계"] + " · " + item["등급"] for item in violations)
    confirmed = sum(1 for item in violations
                    if rm.GRADES.index(item["위_등급"]) < rm.GRADES.index(item["아래_등급"]))
    return {"검사": checked, "위반": len(violations), "확인된_위반": confirmed,
            "단계별": dict(by_step), "예": violations[:12]}


def exact_same_name_violations(model: dict, named: dict) -> dict:
    """규칙 '채택_3' (나) — 이름 없는 판단(업종 하한 포함)에 후보와 같은 이름을 더하면 최종 등급이
    내려가는 입력이 있는가. 같은 이름(호칭 1.0 ≥ 0.98)은 단독 규칙으로 검토 권장 이상이라 위험에서만
    내려갈 수 있다."""
    nameless = model.get(rm.NAMELESS_KEY) or {}
    same = (model.get("coupling") or {}).get(rm.SAME_NAME_KEY)
    if not nameless or same is None:
        return {"검사": 0, "위반": 0, "확인된_위반": 0, "예": []}
    floors = model["coupling"]["floors"]
    axes = list(model["pattern_axes"])
    checked, violations = 0, []
    for key, block in nameless.items():
        present = rm.pattern_present(key)
        own = block.get("grade_thresholds") or model["grade_thresholds"]
        for level in rm.TYPE_LEVELS:
            base_f = {"x1_d": None, "x2_text_d": None, "x3_d": None, "has_meaning_both": False,
                      "has_distinctive_part_a": True, "has_distinctive_part_b": True,
                      "mark_type": level, **{a: (0.0 if a in present else None) for a in axes}}
            cases = []
            if own.get(RISK) is not None:
                c0, c = _affine(block, base_f, present)
                cases.append(("이름 없는 판단", c0, c, float(own[RISK]), {}))
            image_only = nameless.get("x2_whole")
            if "x4" in present and "x2_whole" in present and image_only is not None:
                image_cuts = image_only.get("grade_thresholds") or model["grade_thresholds"]
                if image_cuts.get(RISK) is not None:
                    c0, partial = _affine(image_only, {**base_f, "x4": None}, ["x2_whole"])
                    c = np.asarray([partial[0] if a == "x2_whole" else 0.0 for a in present])
                    cases.append(("업종 하한", c0, c, float(image_cuts[RISK]),
                                  {"x4": float(floors["x4"])}))
            for distinctive in (True, False):
                upper_f = rm.same_name_input(base_f, same, distinctive=distinctive)
                cu0, cu = _affine(model["patterns"][key], upper_f, present)
                high_cut = float(named[key][RISK])
                for label, cl0, cl, low_cut, lows in cases:
                    checked += 1
                    bounds = [(lows.get(a, 0.0), 1.0) for a in present]
                    value, point = _lp_min(cu, [(-cl, cl0 - _logit(low_cut) - LP_EPS)], bounds)
                    if value is None or cu0 + value >= _logit(high_cut) - LP_EPS:
                        continue
                    raw = {a: float(x) for a, x in zip(present, point)}
                    low_input = {**base_f, **raw}
                    up_input = {**upper_f, **raw}
                    violations.append({
                        "집합": key, "경로": label, "유형": level, "요부없음": not distinctive,
                        "입력": {a: round(x, 6) for a, x in raw.items()},
                        "아래_등급": nameless_final_grade(low_input, model),
                        "위_등급": features_grade(up_input, model, named),
                        "위_p": round(rm.risk_score(up_input, model).prob, 6)})
    confirmed = sum(1 for item in violations
                    if rm.GRADES.index(item["위_등급"]) < rm.GRADES.index(item["아래_등급"]))
    return {"검사": checked, "위반": len(violations), "확인된_위반": confirmed,
            "예": violations[:12]}


def data_step_violations(features_list: list[dict], model: dict, named: dict) -> dict:
    """규칙 '채택_3' (다) — 실제 입력에서 축 하나(≥ 결합 하한)를 빼면 최종 등급이 더 높은 경우."""
    floors = model["coupling"]["floors"]
    axes = list(model["pattern_axes"])
    out: dict[str, dict] = {}
    for features in features_list:
        observed = [a for a in axes if features.get(a) is not None]
        for lower, upper, axis in pattern_steps(model):
            present = rm.pattern_present(upper)
            if any(a not in observed for a in present) or float(features[axis]) < float(
                    floors[axis]):
                continue
            up_input = {**features, **{a: None for a in axes if a not in present}}
            low_input = {**up_input, axis: None}
            item = out.setdefault(f"{lower} → {upper} ({axis})", {"n": 0, "위반": 0, "예": []})
            item["n"] += 1
            high, low = features_grade(up_input, model, named), features_grade(
                low_input, model, named)
            if rm.GRADES.index(high) < rm.GRADES.index(low):
                item["위반"] += 1
                if len(item["예"]) < 3:
                    item["예"].append({"아래": low, "위": high, "입력": {
                        k: features.get(k) for k in (*NAME_AXES, *axes, "mark_type")}})
    return out


# ---- 엔진·검색 ----------------------------------------------------------------------------------

def _paths(out_dir: Path) -> dict[str, Path]:
    return {"rule": out_dir / f"{STEM}_rule.json", "control": out_dir / f"{STEM}_control.json",
            "results": out_dir / f"{STEM}_results.json", "report": out_dir / f"{STEM}_report.md",
            "searches": out_dir / f"{STEM}_searches.json.gz"}


def _context(limit: int = 0) -> dict:
    from scripts import nameless_search_thresholds as nst

    args = argparse.Namespace(model=nst.DEFAULT_MODEL, metadata=nst.DEFAULT_METADATA,
                              labels=nst.DEFAULT_LABELS, trial_list=nst.DEFAULT_LIST,
                              image_pairs=nst.DEFAULT_IMAGE_PAIRS, aliases=nst.DEFAULT_ALIASES,
                              limit=limit)
    context = nst.prepare(args)
    context["nst"] = nst
    context["trial_list"] = {row["심판번호"]: row for row in nst._read_csv(nst.DEFAULT_LIST)}
    context["labels"] = nst._read_csv(nst.DEFAULT_LABELS)
    numbers: dict[str, str] = {}
    metadata = json.loads(nst.DEFAULT_METADATA.read_text(encoding="utf-8"))
    for record in metadata.get("trademarks", metadata):
        for field_name in ("출원번호", "등록번호"):
            value = str(record.get(field_name) or "").strip()
            if value:
                numbers[value] = str(record["출원번호"])
    context["db_numbers"] = numbers
    return context


def preset_table(ms) -> list[tuple[str, str, tuple[str, ...]]]:
    from src.axes import goods_map as gm

    presets = gm.load_business_presets(gm.load_goods_map())
    out = []
    for preset in presets.presets:
        codes: set[str] = set()
        for good in preset.goods:
            codes |= set(good.similarity_codes)
        valid, _ = ms.valid_goods(codes)
        out.append((preset.id, preset.label, tuple(sorted(valid))))
    return out


def a_relations(context: dict, query) -> tuple[set[str], frozenset]:
    """표본 A 질의의 (인용상표 DB 출원번호, 견줄 출원인 — 질의 출원·사용자 ∪ 인용상표 권리자)."""
    nst = context["nst"]
    _, case, side = query.key.split(":")
    cited = set()
    for row in context["labels"]:
        if row.get("심판번호") != case or row.get("유사여부_확정") not in ("유사", "비유사"):
            continue
        number = (row.get("상대표장_번호_정규화") if side == "this"
                  else row.get("상표A_번호")) or ""
        if number.strip() in context["db_numbers"]:
            cited.add(context["db_numbers"][number.strip()])
    owners = frozenset(query.applicants)
    party = CITED_OWNER_PARTY.get(query.kind)
    if party:
        listed = context["trial_list"].get(case) or {}
        owners |= nst.split_applicants(listed.get(party, ""), context["aliases"])
    for appno in cited:
        owners |= nst.split_applicants(context["applicants"].get(appno, ""), context["aliases"])
    return cited, owners


def unrelated_filter(context: dict, owners: frozenset, excluded: set[str]):
    nst, aliases, applicants = context["nst"], context["aliases"], context["applicants"]

    def unrelated(candidate_id: str) -> bool:
        if candidate_id in excluded:
            return False
        return not (nst.split_applicants(applicants.get(candidate_id, ""), aliases) & owners)

    return unrelated


def search_query(ms, image, name: str, goods: frozenset, modes, filters: dict) -> dict:
    """방식마다 search_pool 후보 풀 전부(엔진 정렬 순서)."""
    out = {}
    for label, _, with_goods, with_image in modes:
        pooled = ms.search_pool(image=image if with_image else None, name=name,
                                goods_codes=sorted(goods) if with_goods else None)
        unrelated = filters[label]
        rows = []
        for c in pooled.candidates:
            rows.append({
                "id": c.id, "등급": c.grade, "p": float(c.prob), "pattern": c.pattern,
                "규칙": list(c.rule_triggers), "rank": [int(c.rank[0]), float(c.rank[1])],
                "무관": bool(unrelated(c.id)), "이름": bool(c.title),
                "x2_img": c.axes["x2_img"], "x4": c.axes["x4"], "x1": c.axes["x1"],
                "x2_text": c.axes["x2_text"],
                "기여": {k: round(float(v), 4) for k, v in c.contributions.items()},
                "결측": round(float(c.missing_adjustment), 4)})
        out[label] = {"유형": pooled.query_type.type, "사진": bool(pooled.query_photo),
                      "후보": rows}
    return out


# ---- 거르기(여러 프로세스) ---------------------------------------------------------------------

_WORKER: dict = {}


def _screen_init(titles: list, model_path: str) -> None:
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[var] = "1"
    import torch

    torch.set_num_threads(1)
    from src.axes.distinctiveness import load_distinctiveness

    _WORKER["titles"] = titles
    _WORKER["distinct"] = load_distinctiveness(with_goods=True)
    _WORKER["model"] = rm.load_model(model_path)


def _screen_one(task: tuple[str, tuple[str, ...]]) -> dict:
    from src.axes.pair_axes import compute_pair_axes

    name, codes = task
    model, distinct = _WORKER["model"], _WORKER["distinct"]
    for context_name, goods in (("없음", None), ("세트", frozenset(codes) or None)):
        for appno, title, record_goods in _WORKER["titles"]:
            axes = compute_pair_axes(name, title, model=distinct, goods_a=goods,
                                     goods_b=frozenset(record_goods), x3_enabled=True,
                                     spelling_version=rm.spelling_version(model))
            hits = standalone_hits(axes.model_features(x2_img=None, mark_type="문자"), model)
            if hits:
                return {"이름": name, "통과": False, "걸린_상표": appno, "걸린_이름": title,
                        "축": hits, "업종_맥락": context_name}
    return {"이름": name, "통과": True}


# ---- 0. 규칙 고정 ------------------------------------------------------------------------------

def command_freeze(args) -> int:
    paths = _paths(args.out_dir)
    if paths["rule"].exists() and not args.force:
        print(f"거절: {paths['rule']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    frozen = {"설정_sha256": rule_sha256(), "스크립트_sha256": file_sha256(Path(__file__)),
              "고정": _now(),
              "설정": _settings()}
    paths["rule"].write_text(json.dumps(frozen, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    print(f"설정 sha256 {frozen['설정_sha256']} · 스크립트 sha256 {frozen['스크립트_sha256']}")
    return 0


def _check_rule(paths: dict) -> dict | None:
    if not paths["rule"].exists():
        print("거절: 먼저 freeze", file=sys.stderr)
        return None
    frozen = json.loads(paths["rule"].read_text(encoding="utf-8"))
    if frozen["설정_sha256"] != rule_sha256():
        print("거절: 설정이 고정본과 다릅니다", file=sys.stderr)
        return None
    return frozen


# ---- 1. 대조군 ---------------------------------------------------------------------------------

def command_control(args) -> int:
    paths = _paths(args.out_dir)
    frozen = _check_rule(paths)
    if frozen is None:
        return EXIT_REFUSED
    if paths["control"].exists() and not args.force:
        print(f"거절: {paths['control']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    seed = "smoke" if args.smoke else SEED
    per_lang = 2 if args.smoke else N_PER_LANG
    started = time.perf_counter()
    context = _context(limit=6 if args.smoke else 0)
    ms, engine = context["ms"], context["engine"]
    presets = preset_table(ms)
    model = ms.state.model
    titles = [(r.appno, r.title, tuple(sorted(r.goods))) for r in ms.state.records if r.title]
    accepted: dict[str, list[dict]] = {}
    rejected: list[dict] = []
    pool_context = multiprocessing.get_context("spawn")
    with pool_context.Pool(processes=args.workers, initializer=_screen_init,
                           initargs=(titles, str(rm.resolve_model_path()))) as pool:
        for lang in ("ko", "en"):
            stream = name_stream(lang, per_lang * STREAM_FACTOR, seed)
            kept: list[dict] = []
            position = 0
            while len(kept) < per_lang and position < len(stream):
                batch = stream[position:position + args.workers * 2]
                position += len(batch)
                tasks = [(name, presets[preset_index(name, len(presets), seed)][2])
                         for name in batch]
                for name, verdict in zip(batch, pool.map(_screen_one, tasks, chunksize=1)):
                    if len(kept) >= per_lang:
                        break
                    if verdict["통과"]:
                        preset = presets[preset_index(name, len(presets), seed)]
                        kept.append({"이름": name, "언어": lang, "업종_세트": preset[0],
                                     "업종": preset[1], "유사군": list(preset[2])})
                    else:
                        rejected.append({**verdict, "언어": lang})
                print(f"  {lang} {position}개 거름 → 통과 {len(kept)}"
                      f" ({time.perf_counter() - started:.0f}초)", flush=True)
            if len(kept) < per_lang:
                print(f"멈춤: {lang} 통과 이름 {len(kept)} < {per_lang}", file=sys.stderr)
                return EXIT_STOP
            accepted[lang] = kept
    sets: dict[str, list[dict]] = {"기준용": [], "확인용": []}
    for lang in ("ko", "en"):
        first, second = split_half(accepted[lang], seed)
        sets["기준용"] += first
        sets["확인용"] += second
    images = []
    for query in context["A"]:
        image = context["service"](query.path.read_bytes())
        vector = np.asarray(engine.encode_image(image), dtype=np.float32).reshape(-1)
        images.append({"키": query.key, "최대_유사도": round(float(np.max(
            ms.state.embeddings @ vector)), 6)})
    images.sort(key=lambda item: (item["최대_유사도"], item["키"]))
    low = images[:len(images) // 2]
    pools = dict(zip(("기준용", "확인용"), split_half([item["키"] for item in low], seed)))
    for set_name, items in sets.items():
        for index, item in enumerate(items):
            item["이미지"] = pools[set_name][index % len(pools[set_name])]
    control = {"이름": sets, "이미지": pools, "업종_세트": [list(p) for p in presets],
               "거른_이름": rejected, "표본A_이미지_최대유사도": images}
    record = {"설정_sha256": frozen["설정_sha256"], "대조군": control,
              "대조군_sha256": canonical_sha256(control), "모델": model.get("version"),
              "스모크": bool(args.smoke), "시간_s": round(time.perf_counter() - started, 1),
              "끝": _now()}
    paths["control"].write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    print(f"대조군 sha256 {record['대조군_sha256']} · 거른 이름 {len(rejected)} · "
          f"{record['시간_s']}초")
    return 0


# ---- 2. 진단·하한·채택 -------------------------------------------------------------------------

def per_query_max(rows: list[dict], label: str, pattern: str) -> list[float]:
    out = []
    for row in rows:
        entry = row["방식"].get(label)
        if entry is None:
            continue
        values = [c["p"] for c in entry["후보"] if c["무관"] and c["pattern"] == pattern]
        if values:
            out.append(max(values))
    return out


def diagnose(rows: list[dict], model: dict) -> dict:
    paths: Counter = Counter()
    by_mode: dict[str, Counter] = defaultdict(Counter)
    flagged_queries: Counter = Counter()
    overall: dict[str, Counter] = defaultdict(Counter)
    sums: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        for label, *_ in MODES:
            entry = row["방식"].get(label)
            if entry is None:
                continue
            shown = entry["후보"][:DISPLAY_TOP]
            overall[label][max((c["등급"] for c in shown), key=rm.GRADES.index)
                           if shown else "후보 없음"] += 1
            flagged = False
            for c in entry["후보"]:
                if not c["무관"]:
                    continue
                if at_least(c["등급"]):
                    path = path_of(c, model)
                    paths[path] += 1
                    by_mode[label][path] += 1
                    flagged = True
                if rm.is_nameless_pattern(c["pattern"]) or not c["이름"]:
                    continue
                group = "검토 권장 이상" if at_least(c["등급"]) else "그 아래"
                for axis, value in c["기여"].items():
                    sums[label][f"{group}|기여 {axis}"].append(value)
                sums[label][f"{group}|기여 결측"].append(c["결측"])
                for axis in ("x1", "x2_text", "x2_img", "x4"):
                    if c[axis] is not None:
                        sums[label][f"{group}|값 {axis}"].append(c[axis])
                sums[label][f"{group}|p"].append(c["p"])
            flagged_queries[label] += int(flagged)
    total = sum(paths.values())
    non_model = sum(v for k, v in paths.items() if not is_model_path(k))
    axes_table = {label: {key: {"평균": round(float(np.mean(values)), 4), "n": len(values)}
                          for key, values in sorted(table.items())}
                  for label, table in sums.items()}
    return {"경로": dict(paths), "방식별_경로": {k: dict(v) for k, v in by_mode.items()},
            "합계": total, "모델_아닌": non_model,
            "모델_아닌_비율": round(non_model / total, 4) if total else 0.0,
            "무관한_검토권장_이상_질의": dict(flagged_queries), "질의": len(rows),
            "전체_등급(지금)": {k: dict(v) for k, v in overall.items()}, "축": axes_table}


def consistency(samples: dict, model: dict) -> dict:
    """규칙 '검산' ① — 지금 하한으로 다시 매긴 등급·정렬·전체 등급이 엔진과 같은가."""
    current = {key: dict(model["grade_thresholds"]) for key in model["patterns"]}
    grade_miss = order_miss = overall_miss = 0
    for rows in samples.values():
        for row in rows:
            for entry in row["방식"].values():
                candidates = entry["후보"]
                grade_miss += sum(1 for c in candidates if offline_grade(c, current) != c["등급"])
                if [c["id"] for c in offline_order(candidates, current)] != [
                        c["id"] for c in candidates]:
                    order_miss += 1
                shown = candidates[:DISPLAY_TOP]
                engine_overall = (max((c["등급"] for c in shown), key=rm.GRADES.index)
                                  if shown else None)
                overall_miss += int(offline_overall(candidates, current) != engine_overall)
    return {"등급_불일치": grade_miss, "정렬_불일치": order_miss, "전체등급_불일치": overall_miss}


def oof_precision(named: dict) -> dict:
    """규칙 '채택_2' — v1.3 학습을 학습 입력 사본으로 다시 돌린 OOF 로 위험 정밀도."""
    import tempfile

    from scripts import train_risk_model as tr

    captured: dict = {}
    original = tr.subset_performance

    def spy(prob, y, rows, trial, **kwargs):
        captured.update(prob=np.asarray(prob).copy(), y=np.asarray(y).copy(), rows=rows)
        return original(prob, y, rows, trial, **kwargs)

    tr.subset_performance = spy
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            tr.run(V13_INPUTS / "pairs_features.csv", V13_INPUTS / "pairs_features_easy.csv",
                   out_dir=out, model_path=out / "model.json")
            reproduced = json.loads((out / "model.json").read_text(encoding="utf-8"))
    finally:
        tr.subset_performance = original
    current = json.loads(Path(rm.V13_MODEL_PATH).read_text(encoding="utf-8"))
    same = (reproduced["grade_thresholds"] == current["grade_thresholds"]
            and reproduced["meta"].get("grade_precision") == current["meta"].get(
                "grade_precision"))
    rows, prob, y = captured["rows"], captured["prob"], captured["y"]
    mask = tr.set_masks(rows)["심결+cross+db"]
    axes = list(current["pattern_axes"])
    observed = {axis: tr.observed(rows, axis) for axis in axes}
    keys = [rm.pattern_key([axis for axis in axes if observed[axis][i]], axes)
            for i in range(len(rows))]
    cut_now = float(current["grade_thresholds"][RISK])
    above_now = mask & (prob >= cut_now)
    above_new = mask & np.asarray([prob[i] >= named[keys[i]][RISK] for i in range(len(rows))])

    def block(selected):
        n = int(selected.sum())
        return {"위험_이상": n, "유사": int(y[selected].sum()),
                "정밀도": round(float(y[selected].mean()), 4) if n else None,
                "계수_집합별": dict(Counter(keys[i] for i in np.flatnonzero(selected)))}

    return {"재현_같음": bool(same), "재현_하한": reproduced["grade_thresholds"],
            "재현_정밀도": reproduced["meta"].get("grade_precision"), "행": int(mask.sum()),
            "지금": block(above_now), "새": block(above_new)}


def search_pair_features(ms, rows: list[dict], query_of: dict) -> list[dict]:
    """실제 검색 쌍(이름+이미지+업종의 이름 있는 무관한 후보)의 모델 입력 — score_record 와
    같은 식."""
    from src.axes.pair_axes import compute_pair_axes

    model = ms.state.model
    out = []
    for row in rows:
        query = query_of[row["질의"]]
        entry = row["방식"].get(FULL_MODE)
        if entry is None or entry["사진"]:
            continue
        for c in entry["후보"]:
            if not (c["무관"] and c["이름"]) or rm.is_nameless_pattern(c["pattern"]):
                continue
            record = ms.state.by_appno[c["id"]]
            axes = compute_pair_axes(query["이름"], record.title, model=ms.state.distinct,
                                     goods_a=query["유사군"] or None, goods_b=record.goods,
                                     x3_enabled=True, spelling_version=rm.spelling_version(model))
            out.append(axes.model_features(x2_img=c["x2_img"], mark_type=entry["유형"]))
    return out


def cited_pairs(context: dict, model: dict, named: dict) -> dict:
    """규칙 '채택_4' — 표본 A 사건의 인용상표 쌍을 서비스 채점식으로."""
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    cases = {query.key.split(":")[1] for query in context["A"]}
    counts: Counter = Counter()
    now_grades: Counter = Counter()
    new_grades: Counter = Counter()
    for row in t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY).rows:
        if row.get("pair_source") != "trial" or str(row.get("심판번호")) not in cases:
            continue
        counts["사건_행"] += 1
        if not tr.has_name(row):
            counts["이름_없는_행(뺌)"] += 1
            continue
        features = t4.service_features(row, image_column=t4.RAW_IMAGE)
        features["mark_type"] = "결합-문자요부" if features["x2_whole"] is not None else "문자"
        now = features_grade(features, model, None)
        new = features_grade(features, model, named)
        label = row.get("최종라벨")
        counts["쌍"] += 1
        counts[f"쌍_{label}"] += 1
        for tag, grade in (("지금", now), ("새", new)):
            if at_least(grade):
                counts[f"{tag}_이상"] += 1
                counts[f"{tag}_이상_{label}"] += 1
        now_grades[now] += 1
        new_grades[new] += 1
    n = counts["쌍"]
    rate_now = counts["지금_이상"] / n if n else None
    rate_new = counts["새_이상"] / n if n else None
    return {"사건": len(cases), "수": dict(counts), "지금_비율": rate_now, "새_비율": rate_new,
            "비": (rate_new / rate_now) if rate_now else None,
            "등급(지금)": dict(now_grades), "등급(새)": dict(new_grades),
            "통과": bool(rate_now and rate_new is not None
                       and rate_new >= CITED_RATIO_MIN * rate_now - 1e-12)}


def before_after(samples: dict, model: dict, named: dict) -> dict:
    current = {key: dict(model["grade_thresholds"]) for key in model["patterns"]}
    out = {}
    for sample_name, rows in samples.items():
        table = {}
        for label, *_ in MODES:
            now, new = Counter(), Counter()
            for row in rows:
                entry = row["방식"].get(label)
                if entry is None:
                    continue
                now[offline_overall(entry["후보"], current) or "후보 없음"] += 1
                new[offline_overall(entry["후보"], named) or "후보 없음"] += 1
            if now:
                table[label] = {"지금": dict(now), "새": dict(new)}
        out[sample_name] = table
    return out


def command_run(args) -> int:
    paths = _paths(args.out_dir)
    frozen = _check_rule(paths)
    if frozen is None:
        return EXIT_REFUSED
    if not paths["control"].exists():
        print("거절: 먼저 control", file=sys.stderr)
        return EXIT_REFUSED
    control_record = json.loads(paths["control"].read_text(encoding="utf-8"))
    if canonical_sha256(control_record["대조군"]) != control_record["대조군_sha256"]:
        print("거절: 대조군이 고정본 해시와 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    if paths["results"].exists() and not args.force:
        print(f"거절: {paths['results']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    context = _context(limit=6 if args.smoke else 0)
    ms = context["ms"]
    model = ms.state.model
    if model.get("version") != control_record["모델"]:
        print("거절: 엔진 모델이 대조군을 만들 때와 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    a_by_key = {query.key: query for query in context["A"]}
    everything = {label: (lambda _cid: True) for label, *_ in MODES}
    samples: dict[str, list[dict]] = {}
    query_of: dict[str, dict] = {}
    timing: dict[str, float] = {}

    def tick(name: str, began: float, count: int) -> None:
        timing[name] = round(time.perf_counter() - began, 1)
        print(f"  {name} {count}질의 {timing[name]}초", flush=True)

    for set_name in ("기준용", "확인용"):
        began = time.perf_counter()
        rows = []
        for item in control_record["대조군"]["이름"][set_name]:
            source = a_by_key[item["이미지"]]
            cited, owners = a_relations(context, source)
            related = unrelated_filter(context, owners, cited)
            filters = {label: (related if with_image else everything[label])
                       for label, _, _, with_image in MODES}
            image = context["service"](source.path.read_bytes())
            goods = frozenset(item["유사군"])
            key = f"대조군:{set_name}:{item['이름']}"
            rows.append({"질의": key, "이미지": item["이미지"], "인용상표": sorted(cited),
                         "방식": search_query(ms, image, item["이름"], goods, MODES, filters)})
            query_of[key] = {"이름": item["이름"], "유사군": goods}
        samples[f"대조군_{set_name}"] = rows
        tick(f"대조군_{set_name}", began, len(rows))
    began = time.perf_counter()
    rows = []
    for query in context["A"]:
        cited, owners = a_relations(context, query)
        related = unrelated_filter(context, owners, cited)
        modes = [mode for mode in MODES if not mode[2] or query.goods]
        image = context["service"](query.path.read_bytes())
        rows.append({"질의": query.key, "인용상표": sorted(cited), "방식": search_query(
            ms, image, query.name, query.goods, modes, {m[0]: related for m in modes})})
        query_of[query.key] = {"이름": query.name, "유사군": query.goods}
    samples["표본A"] = rows
    tick("표본A", began, len(rows))
    began = time.perf_counter()
    rows = []
    for query in context["B"]:
        related = unrelated_filter(context, frozenset(query.applicants), {query.self_id})
        image = context["direct"](query.path.read_bytes())
        rows.append({"질의": query.key, "방식": search_query(
            ms, image, query.name, query.goods, MODES, {m[0]: related for m in MODES})})
        query_of[query.key] = {"이름": query.name, "유사군": query.goods}
    samples["표본B"] = rows
    tick("표본B", began, len(rows))

    checks = consistency(samples, model)
    checks["대조군_단독규칙_후보"] = sum(
        1 for name in ("대조군_기준용", "대조군_확인용") for row in samples[name]
        for entry in row["방식"].values() for c in entry["후보"]
        if any(t.startswith("standalone_") for t in c["규칙"]))
    results: dict = {"설정_sha256": frozen["설정_sha256"],
                     "스크립트_sha256(고정 때)": frozen["스크립트_sha256"],
                     "스크립트_sha256(잴 때)": file_sha256(Path(__file__)),
                     "대조군_sha256": control_record["대조군_sha256"],
                     "모델": model.get("version"), "스모크": bool(args.smoke), "검산": checks,
                     "시간_s": timing, "질의": {k: len(v) for k, v in samples.items()},
                     "이름_없는_하한_목표(참고)": NAMELESS_REFERENCE}
    diagnosis = {"대조군_기준용": diagnose(samples["대조군_기준용"], model),
                 "표본A": diagnose(samples["표본A"], model)}
    pooled = Counter(diagnosis["대조군_기준용"]["경로"]) + Counter(diagnosis["표본A"]["경로"])
    total = sum(pooled.values())
    non_model = sum(v for k, v in pooled.items() if not is_model_path(k))
    diagnosis["합친_경로"] = dict(pooled)
    diagnosis["합친_모델_아닌_비율"] = round(non_model / total, 4) if total else 0.0
    diagnosis["멈춤"] = bool(total and non_model / total > STOP_SHARE)
    diagnosis["참고_대조군_확인용"] = diagnose(samples["대조군_확인용"], model)
    diagnosis["참고_표본B"] = diagnose(samples["표본B"], model)
    results["진단"] = diagnosis
    inconsistent = any(checks[k] for k in ("등급_불일치", "정렬_불일치", "전체등급_불일치",
                                            "대조군_단독규칙_후보"))
    if inconsistent or diagnosis["멈춤"]:
        results["판정"] = ("멈춤 — 검산 불일치" if inconsistent
                          else "멈춤 — 진단(모델 아닌 경로 절반 초과)")
        return _finish(paths, results, samples, started)

    current = model["grade_thresholds"]
    named: dict[str, dict] = {}
    fitted: dict[str, dict] = {}
    for label, pattern, _, _ in MODES:
        maxima = per_query_max(samples["대조군_기준용"], label, pattern)
        cuts, detail = {}, {}
        for grade, share in TARGETS.items():
            value, k, n = fit_cut(maxima, share)
            cuts[grade] = value
            detail[grade] = {"맞춘_값": value, "k": k, "n": n}
        named[pattern] = new_thresholds(current, cuts)
        fitted[pattern] = {"방식": label, "질의": len(maxima), "계산": detail,
                           "새": named[pattern],
                           "지금_하한_이상_비율": {g: rate_at_least(maxima, current[g])
                                           for g in TARGETS},
                           "M_q_분위": {
                               f"{round(q * 100)}%": round(float(np.quantile(maxima, q)), 4)
                               for q in (0.5, 0.8, 0.9, 0.95, 0.98)} if maxima else {}}
    results["하한"] = fitted
    results["새_하한"] = named

    confirm: dict = {}
    passed_1 = True
    for sample_name in ("대조군_확인용", "표본B"):
        confirm[sample_name] = {}
        for label, pattern, _, _ in MODES:
            maxima = per_query_max(samples[sample_name], label, pattern)
            own = new_thresholds(current, {g: fit_cut(maxima, s)[0] for g, s in TARGETS.items()})
            item: dict = {"방식": label, "질의": len(maxima)}
            for grade, share in TARGETS.items():
                cut = named[pattern][grade]
                rate = rate_at_least(maxima, cut)
                diff = round(own[grade] - cut, 4)
                ok = rate is not None and (rate <= share + 1e-12
                                           or diff <= CONFIRM_TOLERANCE + 1e-12)
                item[grade] = {"비율": rate, "그_표본_하한": own[grade], "차이": diff,
                               "지금_하한_비율": rate_at_least(maxima, current[grade]),
                               "통과": ok}
                passed_1 &= ok
            confirm[sample_name][pattern] = item
    results["채택_1"] = {"표": confirm, "통과": passed_1}

    precision = oof_precision(named)
    passed_2 = bool(precision["재현_같음"] and precision["새"]["정밀도"] is not None
                    and precision["새"]["정밀도"] >= PRECISION_MIN)
    results["채택_2"] = {**precision, "통과": passed_2}

    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    order_ok = {key: ordered(value) for key, value in named.items()}
    monotone = {key: rm.monotone_violations(block["coefficients"])
                for key, block in model["patterns"].items()}
    current_named = {key: dict(current) for key in model["patterns"]}
    steps = exact_step_violations(model, named)
    same_name = exact_same_name_violations(model, named)
    sanity = {"지금_하한_(가)": exact_step_violations(model, current_named)["위반"],
              "지금_하한_(나)": exact_same_name_violations(model, current_named)["위반"]}
    train_rows = [t4.service_features(row, image_column="x2_whole")
                  for row in t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY).rows
                  if tr.has_name(row)]
    pairs: list[dict] = []
    for sample_name in samples:
        pairs += search_pair_features(ms, samples[sample_name], query_of)
    data_train = data_step_violations(train_rows, model, named)
    data_search = data_step_violations(pairs, model, named)
    data_total = sum(item["위반"] for table in (data_train, data_search)
                     for item in table.values())
    passed_3 = (all(order_ok.values()) and not any(monotone.values()) and steps["위반"] == 0
                and same_name["위반"] == 0 and data_total == 0)
    results["채택_3"] = {"순서": order_ok, "단조_위반": {k: len(v) for k, v in monotone.items()},
                       "(가)_정확": steps, "(나)_같은이름": same_name, "검산_지금하한": sanity,
                       "(다)_학습행": data_train, "(다)_검색쌍": data_search,
                       "(다)_행수": {"학습": len(train_rows), "검색": len(pairs)},
                       "(다)_위반_합계": data_total, "통과": passed_3}

    cited = cited_pairs(context, model, named)
    results["채택_4"] = cited
    adopted = passed_1 and passed_2 and passed_3 and cited["통과"]
    results["채택"] = bool(adopted)
    results["판정"] = "채택" if adopted else "멈춤 — 채택 조건 미달(" + "·".join(
        f"{n}" for n, ok in (("①", passed_1), ("②", passed_2), ("③", passed_3),
                             ("④", cited["통과"])) if not ok) + ")"
    results["전후(오프라인)"] = before_after(samples, model, named)
    return _finish(paths, results, samples, started)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _finish(paths: dict, results: dict, samples: dict, started: float) -> int:
    results["걸린_시간_s"] = round(time.perf_counter() - started, 1)
    results["끝"] = _now()
    paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    with gzip.open(paths["searches"], "wt", encoding="utf-8") as handle:
        json.dump(samples, handle, ensure_ascii=False)
    text = report_text(results)
    paths["report"].write_text(text, encoding="utf-8")
    print(text)
    return 0 if results.get("채택") else EXIT_STOP


def _pct(value) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _dist(table: dict) -> str:
    return " · ".join(f"{grade} {table[grade]}" for grade in (*rm.GRADES, "후보 없음")
                      if table.get(grade))


def report_text(results: dict) -> str:
    lines = [f"# 이름 있는 입력의 등급 하한 — 실제 검색 기준 ({results['끝'][:10]})", "",
             f"설정 sha256 `{results['설정_sha256']}` · 대조군 sha256 `{results['대조군_sha256']}`"
             f" · 모델 {results['모델']}", "",
             f"**판정: {results['판정']}**", "",
             f"질의 `{json.dumps(results['질의'], ensure_ascii=False)}` · 검산 "
             f"`{json.dumps(results['검산'], ensure_ascii=False)}`", "", "## 진단(지금 하한)", "",
             "| 묶음 | 검토 권장 이상 무관한 후보 | 모델(이름 있는) | 모델(이름 없는) | 단독 축 | "
             "그 밖의 하한 | 모델 아닌 비율 |", "|---|---:|---:|---:|---:|---:|---:|"]
    diagnosis = results["진단"]
    for name in ("대조군_기준용", "표본A", "참고_대조군_확인용", "참고_표본B"):
        item = diagnosis[name]
        paths = item["경로"]
        other = sum(v for k, v in paths.items() if k.startswith("그 밖의"))
        lines.append(f"| {name} | {item['합계']} | {paths.get('모델(이름 있는 판단)', 0)} | "
                     f"{paths.get('모델(이름 없는 판단)', 0)} | {paths.get('단독 축 규칙', 0)} | "
                     f"{other} | {_pct(item['모델_아닌_비율'])} |")
    share = _pct(diagnosis["합친_모델_아닌_비율"])
    lines += ["", f"합친(대조군 기준용+표본 A) 모델 아닌 비율 {share} → 멈춤 "
              f"{diagnosis['멈춤']}", "", "전체 등급(지금, 표시 상위 5):", ""]
    for name in ("대조군_기준용", "대조군_확인용", "표본A", "표본B"):
        key = name if name in ("대조군_기준용", "표본A") else f"참고_{name}"
        for label, table in diagnosis[key]["전체_등급(지금)"].items():
            lines.append(f"- {name} {label}: {_dist(table)}")
    lines += ["", "끌어올리는 축(이름 있는 판단의 무관한 후보 — 검토 권장 이상 / 그 아래, "
              "평균):", "",
              "| 묶음 | 방식 | n | p | 기여 X1 | 기여 X2 | 기여 X4 | 기여 요부 | "
              "결측(집합 절편) | x1 | x2_img | x4 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in ("대조군_기준용", "표본A"):
        for label, table in diagnosis[name]["축"].items():
            def cell(key, _table=table):
                above = _table.get(f"검토 권장 이상|{key}", {}).get("평균")
                below = _table.get(f"그 아래|{key}", {}).get("평균")
                return f"{above} / {below}"

            count = (f"{table.get('검토 권장 이상|p', {}).get('n', 0)} / "
                     f"{table.get('그 아래|p', {}).get('n', 0)}")
            lines.append(f"| {name} | {label} | {count} | {cell('p')} | {cell('기여 X1')} | "
                         f"{cell('기여 X2')} | {cell('기여 X4')} | {cell('기여 요부')} | "
                         f"{cell('기여 결측')} | {cell('값 x1')} | {cell('값 x2_img')} | "
                         f"{cell('값 x4')} |")
    if "하한" in results:
        lines += ["", "## 새 하한(대조군 기준용)", "",
                  "| 계수 집합 | 방식 | 질의 | 지금 검토 권장 이상 | 지금 위험 이상 | "
                  "M_q 중앙·90%·98% | 새 검토 권장 | 새 위험 |",
                  "|---|---|---:|---:|---:|---|---:|---:|"]
        for pattern, item in results["하한"].items():
            now = item["지금_하한_이상_비율"]
            q = item["M_q_분위"]
            lines.append(f"| {pattern} | {item['방식']} | {item['질의']} | {_pct(now[REVIEW])} | "
                         f"{_pct(now[RISK])} | {q.get('50%')}·{q.get('90%')}·{q.get('98%')} | "
                         f"{item['새'][REVIEW]} | {item['새'][RISK]} |")
        lines += ["", "## 채택 조건", "", f"### ① 확인 — {results['채택_1']['통과']}", "",
                  "| 표본 | 계수 집합 | 질의 | 검토 권장 비율(지금→새) | 그 표본 하한·차이 | "
                  "위험 비율(지금→새) | 그 표본 하한·차이 |", "|---|---|---:|---|---|---|---|"]
        for sample_name, table in results["채택_1"]["표"].items():
            for pattern, item in table.items():
                review, risk = item[REVIEW], item[RISK]
                lines.append(
                    f"| {sample_name} | {pattern} | {item['질의']} | "
                    f"{_pct(review['지금_하한_비율'])}→{_pct(review['비율'])} | "
                    f"{review['그_표본_하한']}·{review['차이']}{'' if review['통과'] else ' ✗'} | "
                    f"{_pct(risk['지금_하한_비율'])}→{_pct(risk['비율'])} | "
                    f"{risk['그_표본_하한']}·{risk['차이']}{'' if risk['통과'] else ' ✗'} |")
        second = results["채택_2"]
        lines += ["", f"### ② 위험 정밀도 — {second['통과']}", "",
                  f"재현 {second['재현_같음']}(하한 {second['재현_하한']}, 정밀도 "
                  f"{second['재현_정밀도']}) · 행 {second['행']} · 지금 "
                  f"{second['지금']['위험_이상']}행 정밀도 {second['지금']['정밀도']} → 새 "
                  f"{second['새']['위험_이상']}행 정밀도 {second['새']['정밀도']}"]
        third = results["채택_3"]
        steps = third["(가)_정확"]
        lines += ["", f"### ③ 순서·단조·입력 더함 — {third['통과']}", "",
                  f"- 순서 {third['순서']} · 단조 위반 {third['단조_위반']}",
                  f"- (가) 이름 있는 판단에 축 더함(정확): 검사 {steps['검사']} · 위반 "
                  f"{steps['위반']}(확인 {steps['확인된_위반']}) · "
                  f"`{json.dumps(steps['단계별'], ensure_ascii=False)}`",
                  f"- (나) 같은 이름 더함(정확): 검사 {third['(나)_같은이름']['검사']} · 위반 "
                  f"{third['(나)_같은이름']['위반']}",
                  f"- 지금 하한 검산 `{json.dumps(third['검산_지금하한'], ensure_ascii=False)}`",
                  f"- (다) 실제 쌍 위반 합계 {third['(다)_위반_합계']} (학습 행 "
                  f"{third['(다)_행수']['학습']}·검색 쌍 {third['(다)_행수']['검색']})"]
        for table_name in ("(다)_학습행", "(다)_검색쌍"):
            for step, item in third[table_name].items():
                lines.append(f"  - {table_name} {step}: {item['위반']}/{item['n']}")
        fourth = results["채택_4"]
        lines += ["", f"### ④ 표본 A 인용상표 — {fourth['통과']}", "",
                  f"사건 {fourth['사건']} · `{json.dumps(fourth['수'], ensure_ascii=False)}` · "
                  f"검토 권장 이상 지금 {_pct(fourth['지금_비율'])} → 새 {_pct(fourth['새_비율'])}",
                  "", "## 전후(오프라인 — 하한만 바꿔 다시 매긴 전체 등급)", ""]
        for sample_name, table in results["전후(오프라인)"].items():
            for label, item in table.items():
                lines.append(f"- {sample_name} {label}: 지금 {_dist(item['지금'])} → 새 "
                             f"{_dist(item['새'])}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("freeze", "control", "run"))
    parser.add_argument("--out-dir", type=Path, default=TRIALS)
    parser.add_argument("--force", action="store_true", help="고정본·결과가 있어도 다시")
    parser.add_argument("--workers", type=int, default=6, help="거르기 프로세스 수")
    parser.add_argument("--smoke", action="store_true",
                        help="실행 확인용 — 다른 seed·이름 2개·표본 6질의(결과 판단에 쓰지 않음)")
    args = parser.parse_args(argv)
    if args.smoke and args.out_dir == TRIALS:
        parser.error("--smoke 는 --out-dir(임시 폴더)와 같이 쓴다")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    return {"freeze": command_freeze, "control": command_control,
            "run": command_run}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
