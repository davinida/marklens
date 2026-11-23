"""이름 없는 판단(이미지만·이미지+업종)의 등급 기준을 이름 있는 쪽(v1.4.1)을 고친 것과 같은 방식 —
질의 단위, 대조군, 집합 공통 기준 — 으로 다시 맞춘다(견고성 점검 R-P0-1 마무리 1단계, 2026-11-23,
지시로 고정). 11/20 기준(이름을 알 때 그 등급 이상인 쌍 비율을 표본 A 로 맞춤)은 이름 있는 하한이
0.1805 이던 때 맞춘 값이라 v1.4.1 과 어긋났다 — 무관한 로고도 업종만 겹치면 이름 없는 판단이 검토
권장(대조군 이미지+업종 62%). 11/20 절차를 되풀이하지 않는다. KIPRIS 호출 0.

    ml/venv/bin/python ml/scripts/nameless_shared_threshold.py freeze   # 0. 규칙·입력 해시
    ml/venv/bin/python ml/scripts/nameless_shared_threshold.py run      # 1. 대조군·맞추기·채택 ①–⑤
    ml/venv/bin/python ml/scripts/nameless_shared_threshold.py apply    # 2. 채택일 때만 v1.4.2 JSON
    ml/venv/bin/python ml/scripts/nameless_shared_threshold.py verify   # 3. 기본 모델 바꾼 뒤

새 기준으로 다시 검색할 때는 같은 프로세스에서 엔진의 계수(multi_search.state.model)를 후보 JSON
으로 바꾼다. 산출(비공개):
ml/data/trials/nameless_shared_threshold_{rule,results,candidate,verify}.json·
_searches.json.gz·_report.md. 고정본과 다르면 거절(종료 코드 4), 채택 미달이면 종료 코드 3.
"""

from __future__ import annotations

import argparse
import contextlib
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

from src.model import risk_model as rm  # noqa: E402

from scripts import named_search_thresholds as first  # noqa: E402

TRIALS = ML_ROOT / "data" / "trials"
STEM = "nameless_shared_threshold"
EXIT_STOP = 3
EXIT_REFUSED = 4
CAUTION, REVIEW, RISK = "주의", "검토 권장", "위험"
SEED = 0
REPEAT = 10  # 이미지 하나에 붙이는 업종 세트 수(이미지+업종 질의)
TARGETS = {REVIEW: 0.10, RISK: 0.02}
TOLERANCE = 0.0224  # 1차 시도 확인 표본 허용 차이 그대로
SAME_LOGO_MIN = 0.95
CITED_RATIO_MIN = 0.5
BOOTSTRAP = 2000
BASE_VERSION = "risk_model_v1.4.1"
NEW_VERSION = "risk_model_v1.4.2"
NEW_MODEL_PATH = REPO_ROOT / "shared" / "model" / "risk_model_v1.4.2.json"
CONTROL_SHA = "f6b11d62b4ced35c73774c6a5a5e7701488cc4d8ce374b316379fd16983bf3f5"
POSITIVES = TRIALS / "logo_floor_named_searches.json.gz"  # 1차 시도 양성 200(이미지·유사군·인정)
X, XG = "noname:x2_whole", "noname:x2_whole+x4"
SETS = ((X, "이미지만", False), (XG, "이미지+업종", True))
FIGURE_LEVEL = "도형"  # 자동 유형의 이름 없는 질의는 도형계(결합-도형요부와 같은 위험도)
GRID_STEP = 0.002

# 규칙(이 지시로 고정 — 실행 전에 해시를 남기고 결과를 보고 바꾸지 않는다) ------------------------
RULE = {
    "대조군": (
        "1차 시도(named_search_thresholds) 대조군의 이미지 — 표본 A 질의 이미지 중 DB 색인과의 "
        "최대 코사인이 낮은 절반 92(대조군 파일 sha256 f6b11d62… 의 '이미지' 기준용 46·확인용 46 "
        "그대로). 무관한 후보 = 후보 풀에서 그 표본 A 질의의 인용상표(라벨의 인용상표 번호를 DB "
        "번호에 대조)와 같은 출원인 후보(그 질의의 출원·사용자와 인용상표 권리자 — 1차 시도 "
        "a_relations·unrelated_filter 그대로)를 뺀 나머지."),
    "업종": (
        "이미지+업종 질의는 이미지마다 업종 세트 25개(대조군 파일의 '업종_세트' — 유사군 합집합 "
        "그대로) 중 random.Random('0|업종|<질의 키>').sample(…, 10) 로 고른 서로 다른 10개를 "
        "하나씩 붙인 10질의(이미지가 46장뿐이라 업종 세트를 바꿔 여러 번 쓴다). 이미지만 질의는 "
        "이미지마다 하나."),
    "검색": (
        "서비스 엔진(multi_search.search_pool, 기본 모델 v1.4.1, 실제 CLIP·OCR)의 후보 풀 전부. "
        "후보마다 이름 없는 계수 집합의 위험도를 후보의 이미지 유사도·상품 겹침으로 다시 "
        "계산한다(rm.risk_score — 이름 축 결측, 유형 도형): 이미지만 질의는 noname:x2_whole, "
        "이미지+업종 질의는 noname:x2_whole+x4(업종 하한 전의 그 집합 값)."),
    "원칙": (
        "질의 단위 — 집합 P 의 M_q = P 가 자연스러운 방식(noname:x2_whole → 이미지만, "
        "noname:x2_whole+x4 → 이미지+업종)의 질의 q 에서 무관한 후보 중 P 위험도의 최댓값."),
    "하한": (
        "집합 P·등급 g(검토 권장 10%·위험 2%)마다 기준용 질의의 M 으로 맞춘 값 = (k+1)번째로 큰 "
        "M 보다 큰 가장 작은 넷째 자리 값, k = ⌊목표·n⌋(1차 시도 fit_cut 그대로 — 그 값 이상인 "
        "질의 ≤ k). 공통 기준 = 두 집합의 맞춘 값 중 큰 값(등급마다) — 두 집합 모두 그 값을 "
        "쓴다(결합 제약으로 겹침 ≥ 0.0252 면 이미지+업종 위험도 ≥ 이미지만 위험도라, 업종을 더 "
        "넣어도 등급이 내려가지 않는다). 주의는 집합마다 지금 값 그대로(0.3677·0.2944). 올리기만 "
        "하지 않는다 — 맞춘 값을 그대로 쓴다."),
    "신뢰구간": (
        "기준용 맞춘 값과 확인용 비율의 95% 구간 = 이미지 단위 묶음 부트스트랩 "
        "2,000회(numpy.random.default_rng(0)), 백분위 2.5·97.5."),
    "채택_1": (
        "대조군 확인용에서 두 집합 모두, 등급마다 공통 기준 이상인 질의(M_q ≥ 기준) 비율 ≤ "
        "목표(검토 권장 10%·위험 2%). 넘으면 확인용에 같은 규칙('하한')으로 맞춘 값 − 공통 기준 "
        "≤ 0.0224 일 때만 통과."),
    "채택_2": (
        "같은 로고 질의 — 1차 시도(logo_floor_named) 양성 200의 이미지를 이름 없이, 업종 "
        "없음·같은 업종(그 양성의 유사군 그대로) 두 방식: 엔진 정렬 1위가 인정 상표(원래 + 같은 "
        "출원인·이미지 코사인 ≥ 0.95 — 1차 시도 기록 그대로)이고 그 표시 등급이 검토 권장 이상인 "
        "질의 비율이 방식마다 95% 이상(새 기준 — 같은 프로세스에서 엔진 계수를 후보 JSON 으로 "
        "바꿔 검색)."),
    "채택_3": (
        "이름 없는 판단의 위험 정밀도(심결 쌍): v1.4 2차 학습의 "
        "교차검증(train_risk_model_v14_nameless.train_once, v1.3 JSON 기준 — 재학습 계수가 배포 "
        "계수와 같아야 함, 아니면 멈춤)의 도형계 OOF 위험도로, 이미지 축이 있는 심결 행(사진 "
        "규칙 뒤): 상품 축이 있으면 noname:x2_whole+x4(겹침 ≥ 0.0252 면 이미지만 OOF 등급과 견줘 "
        "높은 쪽), 없으면 noname:x2_whole, 이미지 ≥ 0.9 면 도형 규칙. 위험인 행의 유사 비율(가중 "
        "없음)이 새 기준 ≥ 지금 기준. 새 기준에서 위험 행이 0 이면 잴 수 없어 미달."),
    "채택_4": (
        "표본 A 사건의 심결 행 중 이미지 축(원래 값, 사진 규칙 전)이 있는 행 — 서비스 "
        "채점식(이름 없는 계수, 유형 도형, 이미지·상품 축은 그 행 값, 업종 하한·도형 규칙)의 "
        "검토 권장 이상 비율: 새 기준 ≥ 지금의 0.5배."),
    "채택_5": (
        "(가) 집합마다 주의 < 검토 권장 < 위험 (나) 단조 위반 0(rm.monotone_violations — 이름 "
        "있는·없는 계수 집합 전부)·결합 위반 0(rm.coupling_violations) (다) 업종을 더 넣었을 때 "
        "등급이 내려가는 경우 0 — 같은 후보에 겹침 ≥ 결합 하한 0.0252 인 업종을 더한 최종 "
        "등급(업종 하한·도형 규칙 포함)이 이미지만 최종 등급보다 낮은 입력: 격자 x2_whole 0–1·x4 "
        "0.0252–1(0.002 간격; 업종 하한을 빼고도 따로 셈) + 대조군 실제 쌍(같은 이미지의 "
        "이미지만 질의와 이미지+업종 질의에 모두 나온 후보)."),
    "함께_보고": (
        "업종만 겹치는 무관한 로고의 위험도가 높은 까닭(판정과 별개) — 학습 행(쉬운 음성 "
        "cross·db, 심결 유사·비유사)의 상품 겹침 분포, 대조군 무관한 후보의 이미지+업종 위험도를 "
        "겹침 구간(0·0–0.5·0.5–1·1)·이미지 유사도 구간으로, 두 이름 없는 계수 집합의 계수."),
    "전후": (
        "대조군(기준용·확인용) 이미지만·이미지+업종의 엔진 전체 등급(정렬 앞 5건의 최고 표시 "
        "등급) 분포 — 지금(v1.4.1) 대 후보(같은 프로세스에서 계수를 바꿔 다시 검색), 같은 로고 "
        "질의, 표본 A 인용상표 등급 분포, 시나리오 16종(named_shared_threshold.SCENARIOS)."),
    "적용": (
        "채택될 때만 shared/model/risk_model_v1.4.2.json = v1.4.1 JSON 에서 이름 없는 두 집합의 "
        "검토 권장·위험만 공통 기준으로(주의·계수·이름 있는 하한·업종 하한·사진·단독·도형 규칙 "
        "그대로), version risk_model_v1.4.2, meta.nameless.grade_thresholds(방식 '실제 검색 기준 "
        "— 대조군 …', 규칙 sha256, 집합별 맞춘 값, 이전 값). 기본 모델을 v1.4.2 로 바꾼 뒤 "
        "verify 가 확인용 대조군·같은 로고·시나리오를 기본 엔진으로 다시 돌려 후보 실행과 같은지 "
        "본다."),
}


def _settings() -> dict:
    return {"RULE": RULE, "SEED": SEED, "REPEAT": REPEAT, "TARGETS": TARGETS,
            "TOLERANCE": TOLERANCE, "SAME_LOGO_MIN": SAME_LOGO_MIN,
            "CITED_RATIO_MIN": CITED_RATIO_MIN, "BOOTSTRAP": BOOTSTRAP,
            "BASE_VERSION": BASE_VERSION, "NEW_VERSION": NEW_VERSION, "CONTROL_SHA": CONTROL_SHA,
            "SETS": SETS, "FIGURE_LEVEL": FIGURE_LEVEL, "GRID_STEP": GRID_STEP,
            "DISPLAY_TOP": first.DISPLAY_TOP}


def rule_sha256() -> str:
    return first.canonical_sha256(_settings())


def _inputs() -> dict[str, Path]:
    from scripts import nameless_search_thresholds as nst
    from scripts import train_risk_model as tr

    return {"계수_JSON(v1.4.1)": rm.V141_MODEL_PATH, "v1.3_JSON": rm.V13_MODEL_PATH,
            "대조군": first._paths(TRIALS)["control"], "양성(1차 시도)": POSITIVES,
            "메타데이터": nst.DEFAULT_METADATA,
            "색인": ML_ROOT / "data" / "index" / "kipris.faiss",
            "색인_manifest": ML_ROOT / "data" / "index" / "kipris_manifest.json",
            "유형_사전": ML_ROOT / "data" / "types.json", "라벨": nst.DEFAULT_LABELS,
            "심판_목록": nst.DEFAULT_LIST, "이미지_쌍": nst.DEFAULT_IMAGE_PAIRS,
            "별칭": nst.DEFAULT_ALIASES, "학습_특징": tr.DEFAULT_FEATURES,
            "학습_쉬운_음성": tr.DEFAULT_EASY,
            "엔진": REPO_ROOT / "backend" / "src" / "core" / "multi_search.py"}


def _paths(out_dir: Path) -> dict[str, Path]:
    return {"rule": out_dir / f"{STEM}_rule.json", "results": out_dir / f"{STEM}_results.json",
            "report": out_dir / f"{STEM}_report.md",
            "candidate": out_dir / f"{STEM}_candidate.json",
            "searches": out_dir / f"{STEM}_searches.json.gz",
            "verify": out_dir / f"{STEM}_verify.json"}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---- 순수 함수(시험 대상) ----------------------------------------------------------------------

def nameless_features(x2, x4) -> dict:
    return {"x1_d": None, "x2_text_d": None, "x3_d": None, "x2_whole": x2, "x4": x4,
            "has_meaning_both": False, "has_distinctive_part_a": True,
            "has_distinctive_part_b": True, "mark_type": FIGURE_LEVEL}


def set_prob(x2: float, x4: float | None, model: dict) -> float:
    """후보의 이름 없는 집합 위험도(이미지만 = x4 None, 이미지+업종 = x4 값)."""
    return float(rm.risk_score(nameless_features(float(x2), x4), model).prob)


def final_grade(x2: float, x4: float | None, model: dict, *, goods_floor: bool = True) -> str:
    """이름 없는 판단의 최종 등급 — 엔진 _nameless_judgment(업종 하한)·도형 규칙과 같은 판정."""
    features = nameless_features(float(x2), x4)
    return (first.nameless_final_grade(features, model) if goods_floor
            else rm.risk_score(features, model).grade)


def shared_thresholds(base: dict, fitted: dict[str, dict]) -> dict[str, dict]:
    """집합마다 {주의: 지금 값, 검토 권장·위험: 두 집합의 맞춘 값 중 큰 값}."""
    shared = {grade: round(max(float(fitted[key][grade]) for key, _, _ in SETS), 4)
              for grade in (REVIEW, RISK)}
    return {key: {CAUTION: float(rm.grade_thresholds_for(base, key)[CAUTION]), **shared}
            for key, _, _ in SETS}


def candidate_model(base: dict, thresholds: dict[str, dict], provenance: dict) -> dict:
    """v1.4.1 JSON → v1.4.2(이름 없는 두 집합의 하한만). 그 밖은 그대로."""
    out = copy.deepcopy(base)
    previous = {key: dict(rm.grade_thresholds_for(base, key)) for key, _, _ in SETS}
    for key, _, _ in SETS:
        out[rm.NAMELESS_KEY][key[len(rm.NAMELESS_PREFIX):]]["grade_thresholds"] = dict(
            thresholds[key])
    out["version"] = NEW_VERSION
    nameless_meta = out.setdefault("meta", {}).setdefault("nameless", {})
    old = nameless_meta.get("grade_thresholds") or {}
    nameless_meta["grade_thresholds"] = {
        "calibrated_at": "2026-11-23",
        "method": (rm.SEARCH_THRESHOLDS_METHOD + " — 대조군(표본 A 저유사 이미지 92, 질의 단위·"
                   "무관한 후보 최고 위험도·이름 없는 두 집합 공통), nameless_shared_threshold.py"),
        **provenance, "previous": previous,
        "previous_calibration": {"calibrated_at": old.get("calibrated_at"),
                                 "method": old.get("method")},
        "derived_from": base.get("version")}
    rm.validate_model({**out, "version": base["version"]})  # 구조 검증(새 버전 등록은 적용 때)
    return out


def ordered(thresholds: dict) -> bool:
    cuts = [float(thresholds[g]) for g in rm.GRADE_THRESHOLD_KEYS]
    return all(a < b for a, b in zip(cuts, cuts[1:]))


def at_least(grade: str | None, floor: str) -> bool:
    return grade is not None and rm.GRADES.index(grade) >= rm.GRADES.index(floor)


def rate_at_least(values: list[float], cut: float) -> float | None:
    return (sum(1 for v in values if v >= cut) / len(values)) if values else None


def overall(grades: list[str]) -> str | None:
    shown = grades[:first.DISPLAY_TOP]
    return max(shown, key=rm.GRADES.index) if shown else None


def distribution(grades) -> dict[str, int]:
    counts = Counter(grade or "후보 없음" for grade in grades)
    return {key: counts[key] for key in [*rm.GRADES, "후보 없음"] if counts.get(key)}


def cluster_bootstrap(groups: dict[str, list[float]], statistic, *, rounds: int = BOOTSTRAP,
                      seed: int = SEED) -> list[float] | None:
    """이미지(묶음) 단위로 다시 뽑아 statistic(값 목록)의 95% 백분위 구간."""
    keys = sorted(groups)
    if not keys:
        return None
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(rounds):
        picked = rng.integers(0, len(keys), size=len(keys))
        values = [v for index in picked for v in groups[keys[index]]]
        value = statistic(values)
        if value is not None:
            out.append(float(value))
    if not out:
        return None
    return [round(float(np.percentile(out, 2.5)), 4), round(float(np.percentile(out, 97.5)), 4)]


def grid_violations(model: dict, *, goods_floor: bool, step: float = GRID_STEP) -> int:
    """채택_5 (다) 격자 — 겹침 ≥ 결합 하한인 업종을 더한 최종 등급 < 이미지만 최종 등급인 점 수."""
    floor = float(model["coupling"]["floors"]["x4"])
    x2s = np.round(np.arange(0.0, 1.0 + 1e-9, step), 6)
    x4s = np.round(np.arange(floor, 1.0 + 1e-9, step), 6)
    alone = [final_grade(x2, None, model) for x2 in x2s]
    bad = 0
    for i, x2 in enumerate(x2s):
        floor_index = rm.GRADES.index(alone[i])
        for x4 in x4s:
            if rm.GRADES.index(final_grade(x2, float(x4), model, goods_floor=goods_floor)) < (
                    floor_index):
                bad += 1
    return bad


# ---- 0. 고정 -----------------------------------------------------------------------------------

def command_freeze(args) -> int:
    paths = _paths(args.out_dir)
    if paths["rule"].exists() and not args.force:
        print(f"거절: {paths['rule']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    if control["대조군_sha256"] != CONTROL_SHA:
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


def _check_frozen(paths: dict, *, engine_may_change: bool = False) -> dict | None:
    if not paths["rule"].exists():
        print("거절: 먼저 freeze", file=sys.stderr)
        return None
    frozen = json.loads(paths["rule"].read_text(encoding="utf-8"))
    if frozen["설정_sha256"] != rule_sha256():
        print("거절: 설정이 고정본과 다릅니다", file=sys.stderr)
        return None
    skip = {"엔진"} if engine_may_change else set()
    changed = [k for k, p in _inputs().items()
               if k not in skip and first.file_sha256(p) != frozen["입력_sha256"].get(k)]
    if changed:
        print(f"거절: 입력이 고정 때와 다릅니다 — {changed}", file=sys.stderr)
        return None
    return frozen


# ---- 1. 검색·맞추기·채택 -----------------------------------------------------------------------

def _context(model_path: Path) -> dict:
    from scripts import nameless_search_thresholds as nst

    context = nst.prepare(argparse.Namespace(
        model=model_path, metadata=nst.DEFAULT_METADATA, labels=nst.DEFAULT_LABELS,
        trial_list=nst.DEFAULT_LIST, image_pairs=nst.DEFAULT_IMAGE_PAIRS,
        aliases=nst.DEFAULT_ALIASES, limit=0))
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


@contextlib.contextmanager
def using_model(ms, model: dict):
    """같은 프로세스에서 엔진 계수를 잠깐 바꾼다(make_context 가 state.model 을 읽는다)."""
    previous = ms.state.model
    ms.state.model = model
    try:
        yield
    finally:
        ms.state.model = previous


def _pool(pooled, unrelated=None) -> list[dict]:
    return [{"id": c.id, "x2": c.axes["x2_img"], "x4": c.axes["x4"],
             "무관": bool(unrelated(c.id)) if unrelated else None}
            for c in pooled.candidates]


def _summary(pooled) -> dict:
    top = pooled.candidates[:first.DISPLAY_TOP]
    return {"전체": overall([c.grade for c in pooled.candidates]),
            "상위": [{"id": c.id, "등급": c.grade, "p": round(float(c.prob), 6),
                    "pattern": c.pattern, "규칙": list(c.rule_triggers)} for c in top]}


def control_queries(control: dict, limit: int | None, repeat: int) -> list[dict]:
    presets = control["업종_세트"]
    out = []
    for half in ("기준용", "확인용"):
        for key in control["이미지"][half][:limit]:
            picked = random.Random(f"{SEED}|업종|{key}").sample(range(len(presets)), repeat)
            out.append({"반": half, "키": key,
                        "업종": [{"id": presets[i][0], "이름": presets[i][1],
                                "유사군": list(presets[i][2])} for i in picked]})
    return out


def run_control(context: dict, queries: list[dict], models: dict[str, dict]) -> None:
    """질의마다 이미지만 1 + 이미지+업종 REPEAT — 풀(이미지 유사도·겹침·무관)과 모델별 요약."""
    ms = context["ms"]
    a_by_key = {query.key: query for query in context["A"]}
    for index, item in enumerate(queries):
        source = a_by_key[item["키"]]
        cited, owners = first.a_relations(context, source)
        unrelated = first.unrelated_filter(context, owners, cited)
        image = context["service"](source.path.read_bytes())
        item["인용상표"] = sorted(cited)
        runs = [("이미지만", None, None)] + [
            ("이미지+업종", preset["id"], sorted(preset["유사군"])) for preset in item["업종"]]
        item["검색"] = []
        for mode, preset_id, codes in runs:
            entry = {"방식": mode, "업종_id": preset_id}
            for label, model in models.items():
                with using_model(ms, model):
                    pooled = ms.search_pool(image=image, goods_codes=codes)
                entry[label] = _summary(pooled)
                if "풀" not in entry:
                    entry["풀"] = _pool(pooled, unrelated)
            item["검색"].append(entry)
        if (index + 1) % 10 == 0:
            print(f"    대조군 {index + 1}/{len(queries)}", flush=True)


def query_maxima(queries: list[dict], model: dict) -> dict[str, dict[str, list[float]]]:
    """{집합: {반: [M_q ...]}} 과 이미지별 묶음 {집합: {반: {키: [M_q ...]}}}."""
    maxima = {key: {"기준용": [], "확인용": []} for key, _, _ in SETS}
    groups = {key: {"기준용": {}, "확인용": {}} for key, _, _ in SETS}
    for item in queries:
        for entry in item["검색"]:
            key = X if entry["방식"] == "이미지만" else XG
            values = [set_prob(c["x2"], None if key == X else c["x4"], model)
                      for c in entry["풀"] if c["무관"] and c["x2"] is not None]
            if not values:
                continue
            value = max(values)
            maxima[key][item["반"]].append(value)
            groups[key][item["반"]].setdefault(item["키"], []).append(value)
    return {"값": maxima, "묶음": groups}


def fit_all(maxima: dict, groups: dict) -> dict:
    fitted, detail = {}, {}
    for key, label, _ in SETS:
        fitted[key], detail[key] = {}, {"방식": label}
        values = maxima[key]["기준용"]
        for grade, share in TARGETS.items():
            value, k, n = first.fit_cut(values, share)
            fitted[key][grade] = value
            detail[key][grade] = {
                "맞춘_값": value, "k": k, "n": n,
                "95%": cluster_bootstrap(groups[key]["기준용"],
                                         lambda v, s=share: first.fit_cut(v, s)[0])}
    return {"맞춘_값": fitted, "자세히": detail}


def check_1(maxima: dict, groups: dict, thresholds: dict) -> dict:
    out, passed = {}, True
    for key, label, _ in SETS:
        block = {"방식": label}
        values = maxima[key]["확인용"]
        for grade, share in TARGETS.items():
            cut = float(thresholds[key][grade])
            observed = rate_at_least(values, cut)
            ok = observed is not None and observed <= share + 1e-12
            refit = None
            if not ok and values:
                refit, _, _ = first.fit_cut(values, share)
                ok = refit is not None and refit - cut <= TOLERANCE + 1e-12
            block[grade] = {"기준": cut, "목표": share, "확인용_비율": observed, "n": len(values),
                            "95%": cluster_bootstrap(groups[key]["확인용"],
                                                     lambda v, c=cut: rate_at_least(v, c)),
                            "넘을_때_확인용_맞춘_값": refit, "통과": ok}
            passed = passed and ok
        out[key] = block
    return {"집합": out, "통과": passed}


def same_logo(context: dict, positives: list[dict], models: dict[str, dict]) -> dict:
    ms = context["ms"]
    rows = []
    for item in positives:
        image = context["service"]((ML_ROOT / "data" / item["이미지"]).read_bytes())
        accepted = set(item["인정"])
        row = {"출원번호": item["출원번호"], "방식": {}}
        for mode, codes in (("업종 없음", None), ("같은 업종", item["유사군"] or None)):
            row["방식"][mode] = {}
            for label, model in models.items():
                with using_model(ms, model):
                    pooled = ms.search_pool(image=image, goods_codes=codes)
                top = pooled.candidates[0] if pooled.candidates else None
                best = min((i for i, c in enumerate(pooled.candidates, 1) if c.id in accepted),
                           default=None)
                row["방식"][mode][label] = {
                    "1위": top.id if top else None, "1위_등급": top.grade if top else None,
                    "1위_p": round(float(top.prob), 6) if top else None,
                    "성공": bool(top and top.id in accepted and at_least(top.grade, REVIEW)),
                    "인정_최고_순위": best, "전체": overall([c.grade for c in pooled.candidates])}
        rows.append(row)
    return {"행": rows}


def check_2(result: dict, label: str = "새") -> dict:
    out, passed = {}, True
    for mode in ("업종 없음", "같은 업종"):
        flags = [row["방식"][mode][label]["성공"] for row in result["행"]]
        before = [row["방식"][mode]["지금"]["성공"] for row in result["행"]
                  if "지금" in row["방식"][mode]]
        value = sum(flags) / len(flags) if flags else None
        ok = value is not None and value >= SAME_LOGO_MIN - 1e-12
        out[mode] = {"질의": len(flags), "비율": value,
                     "지금_비율": (sum(before) / len(before)) if before else None,
                     "1위_등급(새)": distribution(row["방식"][mode][label]["1위_등급"]
                                                for row in result["행"]),
                     "통과": ok}
        passed = passed and ok
    return {"방식": out, "통과": passed}


def oof_precision(models: dict[str, dict]) -> dict:
    """채택_3 — v1.4 2차 학습 교차검증의 도형계 OOF 로 이름 없는 판단의 위험 정밀도."""
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4
    from scripts import train_risk_model_v14_nameless as t2

    base = models["지금"]
    old = rm.validate_model(json.loads(rm.V13_MODEL_PATH.read_text(encoding="utf-8")))
    rows = t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY).rows
    result = t2.train_once(rows, old)
    design, a, cv = result["design"], result["arrays"], result["cv"]
    same = all(block["coefficients"] == base[rm.NAMELESS_KEY][key]["coefficients"]
               for key, block in t2.rounded_nameless(design, result["final"].blocks).items())
    floor = float(base["coupling"]["floors"]["x4"])
    tau = (base.get("figure_rule") or {}).get("threshold")
    index = np.flatnonzero(a["trial"] & design.mask[X])
    out = {"재학습_같음": bool(same), "행": int(index.size)}
    for label, model in models.items():
        grades = []
        for i in index:
            x2 = float(rows[i]["x2_whole"])
            if design.mask[XG][i]:
                grade = rm.grade_for(float(cv["per_block_figure"][XG][i]),
                                     rm.grade_thresholds_for(model, XG))
                if float(rows[i]["x4"]) >= floor:
                    other = rm.grade_for(float(cv["per_block_figure"][X][i]),
                                         rm.grade_thresholds_for(model, X))
                    grade = max(grade, other, key=rm.GRADES.index)
            else:
                grade = rm.grade_for(float(cv["per_block_figure"][X][i]),
                                     rm.grade_thresholds_for(model, X))
            if tau is not None and x2 >= float(tau) and not at_least(grade, REVIEW):
                grade = REVIEW
            grades.append(grade)
        y, w = a["y"][index], a["eval_weight"][index]
        risk = np.asarray([g == RISK for g in grades])
        n = int(risk.sum())
        out[label] = {"등급": distribution(grades), "위험": n, "유사": int(y[risk].sum()),
                      "정밀도": round(float(y[risk].mean()), 4) if n else None,
                      "가중_정밀도": (round(float((w[risk] * y[risk]).sum() / w[risk].sum()), 4)
                                 if n else None)}
    now, new = out["지금"]["정밀도"], out["새"]["정밀도"]
    out["통과"] = bool(same and now is not None and new is not None and new >= now - 1e-12)
    return out


def cited_pairs(case_ids: set[str], models: dict[str, dict]) -> dict:
    """채택_4 — 표본 A 사건의 이미지 있는 심결 행, 서비스 채점식의 이름 없는 판단."""
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    grades = {label: [] for label in models}
    labels = []
    for row in t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY).rows:
        if row.get("pair_source") != "trial" or str(row.get("심판번호")) not in case_ids:
            continue
        x2 = row.get(t4.RAW_IMAGE)
        if x2 is None or np.isnan(x2):
            continue
        x4 = row.get("x4")
        x4 = None if x4 is None or np.isnan(x4) else float(x4)
        labels.append(row.get("최종라벨"))
        for label, model in models.items():
            grades[label].append(final_grade(float(x2), x4, model))
    out = {"사건": len(case_ids), "쌍": len(labels)}
    for label in models:
        flags = [at_least(g, REVIEW) for g in grades[label]]
        risk = [lab for g, lab in zip(grades[label], labels) if g == RISK]
        out[label] = {"등급": distribution(grades[label]),
                      "검토_권장_이상": round(sum(flags) / len(flags), 4) if flags else None,
                      "유사_중_검토_권장_이상": sum(1 for f, lab in zip(flags, labels)
                                             if f and lab == "유사"),
                      "위험_정밀도": {"위험": len(risk), "유사": risk.count("유사")}}
    now, new = out["지금"]["검토_권장_이상"], out["새"]["검토_권장_이상"]
    out["비"] = round(new / now, 4) if now else None
    out["통과"] = bool(now and new is not None and new >= CITED_RATIO_MIN * now - 1e-12)
    return out


def check_5(model: dict, queries: list[dict]) -> dict:
    thresholds = {key: rm.grade_thresholds_for(model, key) for key, _, _ in SETS}
    blocks = {"base": model, **(model.get("patterns") or {}),
              **{rm.NAMELESS_PREFIX + k: v for k, v in (model.get(rm.NAMELESS_KEY) or {}).items()}}
    monotone = {key: len(rm.monotone_violations(block["coefficients"]))
                for key, block in blocks.items() if "coefficients" in block}
    coupling = rm.coupling_violations(model)
    floor = float(model["coupling"]["floors"]["x4"])
    data_bad, data_pairs = 0, 0
    for item in queries:
        alone = {c["id"]: c["x2"] for entry in item["검색"] if entry["방식"] == "이미지만"
                 for c in entry["풀"] if c["x2"] is not None}
        for entry in item["검색"]:
            if entry["방식"] != "이미지+업종":
                continue
            for c in entry["풀"]:
                if c["id"] not in alone or c["x4"] is None or c["x4"] < floor:
                    continue
                data_pairs += 1
                data_bad += int(rm.GRADES.index(final_grade(c["x2"], c["x4"], model))
                                < rm.GRADES.index(final_grade(alone[c["id"]], None, model)))
    grid = grid_violations(model, goods_floor=True)
    grid_plain = grid_violations(model, goods_floor=False)
    passed = (all(ordered(t) for t in thresholds.values()) and not any(monotone.values())
              and not coupling and grid == 0 and grid_plain == 0 and data_bad == 0)
    return {"순서": {key: ordered(t) for key, t in thresholds.items()}, "단조_위반": monotone,
            "결합_위반": len(coupling), "격자_내려감": grid,
            "격자_내려감(업종_하한_없이)": grid_plain,
            "실제_쌍": data_pairs, "실제_쌍_내려감": data_bad, "통과": passed}


def goods_reliance(queries: list[dict], model: dict) -> dict:
    """함께 보고 — 업종만 겹치는 무관한 로고의 위험도가 높은 까닭."""
    import csv

    from scripts import train_risk_model as tr

    def bins(value):
        if value is None:
            return "없음"
        if value == 0:
            return "0"
        if value < 0.5:
            return "0–0.5"
        if value < 1:
            return "0.5–1"
        return "1"

    learn: dict[str, Counter] = {}
    for path in (tr.DEFAULT_EASY, tr.DEFAULT_FEATURES):
        with open(path, encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                source = row.get("pair_source") or "trial"
                label = row.get("최종라벨") or ""
                if source == "trial" and label not in ("유사", "비유사"):
                    continue
                group = source if source != "trial" else f"심결 {label}"
                value = (row.get("x4") or "").strip()
                x4 = float(value) if value not in ("", "nan") else None
                learn.setdefault(group, Counter())[bins(x4)] += 1
    by_bin: dict[str, list[float]] = {}
    by_image: dict[str, list[float]] = {}
    for item in queries:
        for entry in item["검색"]:
            if entry["방식"] != "이미지+업종":
                continue
            for c in entry["풀"]:
                if not c["무관"] or c["x2"] is None:
                    continue
                p = set_prob(c["x2"], c["x4"], model)
                by_bin.setdefault(bins(c["x4"]), []).append(p)
                image_bin = "x2<0.3" if c["x2"] < 0.3 else ("0.3–0.5" if c["x2"] < 0.5 else "≥0.5")
                by_image.setdefault(image_bin, []).append(p)

    def stats(values):
        return {"n": len(values), "중앙": round(statistics.median(values), 4),
                "평균": round(statistics.fmean(values), 4),
                "검토_권장_이상(지금 0.4441)": round(sum(v >= 0.4441 for v in values) / len(values),
                                               4)} if values else None

    coefficients = {key: (model[rm.NAMELESS_KEY][key[len(rm.NAMELESS_PREFIX):]]["intercept"],
                          model[rm.NAMELESS_KEY][key[len(rm.NAMELESS_PREFIX):]]["coefficients"])
                    for key, _, _ in SETS}
    return {"학습_상품_겹침_분포": {k: dict(v) for k, v in learn.items()},
            "대조군_무관_후보_이미지+업종_위험도(겹침별)": {k: stats(v) for k, v in by_bin.items()},
            "대조군_무관_후보_이미지+업종_위험도(이미지별)": {k: stats(v)
                                                for k, v in by_image.items()},
            "계수": coefficients}


def scenarios(context: dict, models: dict[str, dict]) -> dict:
    from scripts import named_shared_threshold as second

    ms = context["ms"]
    out = {}
    for label, model in models.items():
        out[label] = {}
        suggested = None
        with using_model(ms, model):
            for key, title, inputs in second.scenario_inputs(ms, context["service"]):
                if inputs.get("name") == "@S3":
                    if not suggested:
                        out[label][key] = {"제목": title, "건너뜀": True}
                        continue
                    inputs["name"] = suggested
                data = ms.multi_search(**inputs, top_k=first.DISPLAY_TOP).to_dict()
                if key == "S3":
                    suggested = data["overall"]["query_type"].get("suggested_name")
                out[label][key] = {
                    "제목": title,
                    "전체": {k: data["overall"][k] for k in ("grade", "prob", "pattern")},
                    "상위": [{"id": c["id"], "title": c["title"], "grade": c["risk"]["grade"],
                            "prob": c["risk"]["prob"], "pattern": c["risk"]["pattern"],
                            "rules": c["risk"]["rule_triggers"]} for c in data["candidates"]]}
    return out


def before_after(queries: list[dict]) -> dict:
    out = {}
    for half in ("기준용", "확인용"):
        for mode in ("이미지만", "이미지+업종"):
            entries = [entry for item in queries if item["반"] == half for entry in item["검색"]
                       if entry["방식"] == mode]
            out[f"{half} {mode}"] = {label: distribution(e[label]["전체"] for e in entries)
                                     for label in ("지금", "새") if entries and label in entries[0]}
    return out


def command_run(args) -> int:
    paths = _paths(args.out_dir)
    frozen = _check_frozen(paths)
    if frozen is None:
        return EXIT_REFUSED
    if paths["results"].exists() and not args.force:
        print(f"거절: {paths['results']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    control_record = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    if control_record["대조군_sha256"] != CONTROL_SHA:
        print("거절: 대조군 해시가 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    base = rm.validate_model(json.loads(rm.V141_MODEL_PATH.read_text(encoding="utf-8")))
    context = _context(rm.V141_MODEL_PATH)
    ms = context["ms"]
    if ms.state.model.get("version") != BASE_VERSION:
        print("거절: 엔진 모델이 v1.4.1 이 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    limit = 4 if args.smoke else None
    repeat = 2 if args.smoke else REPEAT
    timing: dict[str, float] = {}

    def tick(name: str, began: float) -> None:
        timing[name] = round(time.perf_counter() - began, 1)
        print(f"  {name} {timing[name]}초", flush=True)

    # 1. 대조군(지금 모델) → 맞추기 → 후보 모델
    began = time.perf_counter()
    queries = control_queries(control_record["대조군"], limit, repeat)
    run_control(context, queries, {"지금": ms.state.model})
    tick("대조군(지금)", began)
    found = query_maxima(queries, base)
    fit = fit_all(found["값"], found["묶음"])
    thresholds = shared_thresholds(base, fit["맞춘_값"])
    provenance = {"rule_sha256": frozen["설정_sha256"], "per_set": fit["맞춘_값"],
                  "shared": {REVIEW: thresholds[X][REVIEW], RISK: thresholds[X][RISK]},
                  "targets": TARGETS, "repeat": repeat, "adopted": None}
    candidate = candidate_model(base, thresholds, provenance)
    models = {"지금": ms.state.model, "새": candidate}

    # 2. 새 기준으로 다시 검색(전후 분포·⑤ 실제 쌍은 풀에서)
    began = time.perf_counter()
    a_by_key = {query.key: query for query in context["A"]}
    for item in queries:
        image = context["service"](a_by_key[item["키"]].path.read_bytes())
        codes_of = {preset["id"]: sorted(preset["유사군"]) for preset in item["업종"]}
        for entry in item["검색"]:
            codes = codes_of.get(entry["업종_id"]) if entry["방식"] == "이미지+업종" else None
            with using_model(ms, candidate):
                entry["새"] = _summary(ms.search_pool(image=image, goods_codes=codes))
    tick("대조군(새)", began)

    began = time.perf_counter()
    with gzip.open(POSITIVES, "rt", encoding="utf-8") as handle:
        positives = json.load(handle)["양성"][:limit]
    logo = same_logo(context, positives, models)
    tick("같은 로고", began)
    began = time.perf_counter()
    scenario_runs = scenarios(context, models)
    tick("시나리오", began)
    began = time.perf_counter()
    case_ids = {query.key.split(":")[1] for query in context["A"]}
    results = {"설정_sha256": frozen["설정_sha256"],
               "스크립트_sha256(고정 때)": frozen["스크립트_sha256"],
               "스크립트_sha256(잴 때)": first.file_sha256(Path(__file__)), "모델": BASE_VERSION,
               "스모크": bool(args.smoke), "질의": {
                   "기준용_이미지": sum(1 for q in queries if q["반"] == "기준용"),
                   "확인용_이미지": sum(1 for q in queries if q["반"] == "확인용"),
                   "업종_반복": repeat},
               "맞추기": fit, "새_기준": thresholds,
               "지금_기준": {key: dict(rm.grade_thresholds_for(base, key)) for key, _, _ in SETS},
               "채택_1": check_1(found["값"], found["묶음"], thresholds),
               "채택_2": check_2(logo), "채택_3": oof_precision(models),
               "채택_4": cited_pairs(case_ids, models), "채택_5": check_5(candidate, queries),
               "함께_보고": goods_reliance(queries, base), "전후_대조군": before_after(queries),
               "시나리오": scenario_runs}
    tick("채택 조건", began)
    results["채택"] = all(results[f"채택_{i}"]["통과"] for i in range(1, 6))
    candidate["meta"]["nameless"]["grade_thresholds"]["adopted"] = results["채택"]
    results["시간_s"] = timing
    results["걸린_시간_s"] = round(time.perf_counter() - started, 1)
    results["끝"] = _now()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    paths["candidate"].write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
    with gzip.open(paths["searches"], "wt", encoding="utf-8") as handle:
        json.dump({"대조군": queries, "같은_로고": logo}, handle, ensure_ascii=False)
    paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    paths["report"].write_text(report_text(results), encoding="utf-8")
    print(json.dumps({"채택": results["채택"], "새_기준": thresholds}, ensure_ascii=False))
    print(f"→ {paths['results']}\n→ {paths['report']}")
    return 0 if results["채택"] else EXIT_STOP


# ---- 2·3. 적용·확인 ---------------------------------------------------------------------------

def command_apply(args) -> int:
    paths = _paths(args.out_dir)
    if _check_frozen(paths, engine_may_change=True) is None:
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
    """기본 모델을 v1.4.2 로 바꾼 뒤 — 확인용 대조군·같은 로고·시나리오를 기본 엔진으로 다시."""
    paths = _paths(args.out_dir)
    if _check_frozen(paths, engine_may_change=True) is None:
        return EXIT_REFUSED
    if rm.MODEL_VERSION != NEW_VERSION or rm.resolve_model_path() != NEW_MODEL_PATH:
        print("거절: 서비스 기본 모델이 v1.4.2 가 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    results = json.loads(paths["results"].read_text(encoding="utf-8"))
    with gzip.open(paths["searches"], "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    context = _context(NEW_MODEL_PATH)
    ms = context["ms"]
    if ms.state.model.get("version") != NEW_VERSION:
        print("거절: 엔진이 적재한 모델이 v1.4.2 가 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    a_by_key = {query.key: query for query in context["A"]}
    mismatch = Counter()
    checked = 0
    for item in saved["대조군"]:
        if item["반"] != "확인용":
            continue
        image = context["service"](a_by_key[item["키"]].path.read_bytes())
        codes_of = {preset["id"]: sorted(preset["유사군"]) for preset in item["업종"]}
        for entry in item["검색"]:
            codes = codes_of.get(entry["업종_id"]) if entry["방식"] == "이미지+업종" else None
            got = _summary(ms.search_pool(image=image, goods_codes=codes))
            checked += 1
            mismatch["전체_등급"] += int(got["전체"] != entry["새"]["전체"])
            mismatch["상위5"] += int([c["id"] for c in got["상위"]]
                                    != [c["id"] for c in entry["새"]["상위"]])
    positives = [{"출원번호": row["출원번호"], **_positive_of(row["출원번호"])}
                 for row in saved["같은_로고"]["행"]]
    logo = same_logo(context, positives, {"기본": ms.state.model})
    for row, old in zip(logo["행"], saved["같은_로고"]["행"]):
        for mode in ("업종 없음", "같은 업종"):
            mismatch["같은_로고"] += int(row["방식"][mode]["기본"]["성공"]
                                      != old["방식"][mode]["새"]["성공"])
    default = scenarios(context, {"기본": ms.state.model})["기본"]
    scenario_diff = [key for key, item in default.items()
                     if item.get("전체") != results["시나리오"]["새"].get(key, {}).get("전체")
                     or [c["id"] for c in item.get("상위", [])] != [
                         c["id"] for c in results["시나리오"]["새"].get(key, {}).get("상위", [])]]
    verify = {"모델": ms.state.model["version"], "확인용_검색": checked,
              "불일치": dict(mismatch), "시나리오_다른_것": scenario_diff,
              "통과": not any(mismatch.values()) and not scenario_diff,
              "걸린_시간_s": round(time.perf_counter() - started, 1), "끝": _now()}
    paths["verify"].write_text(json.dumps(verify, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")
    print(json.dumps(verify, ensure_ascii=False))
    return 0 if verify["통과"] else EXIT_STOP


_POSITIVE_CACHE: dict[str, dict] = {}


def _positive_of(appno: str) -> dict:
    if not _POSITIVE_CACHE:
        with gzip.open(POSITIVES, "rt", encoding="utf-8") as handle:
            for item in json.load(handle)["양성"]:
                _POSITIVE_CACHE[item["출원번호"]] = {"이미지": item["이미지"],
                                                 "유사군": item["유사군"], "인정": item["인정"]}
    return _POSITIVE_CACHE[appno]


# ---- 보고 --------------------------------------------------------------------------------------

def _pct(value) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _dist(table: dict) -> str:
    return " · ".join(f"{k} {v}" for k, v in table.items()) or "—"


def report_text(results: dict) -> str:
    lines = ["# 이름 없는 기준 다시 맞추기(R-P0-1 마무리 1단계) — 보고", "",
             f"- 설정 sha256 `{results['설정_sha256']}` · 스크립트 고정 "
             f"`{results['스크립트_sha256(고정 때)']}` · 잴 때 "
             f"`{results['스크립트_sha256(잴 때)']}`",
             f"- 질의 {results['질의']} · 스모크 {results['스모크']} · 채택 "
             f"**{results['채택']}**", "",
             "## 맞추기(기준용)", ""]
    for key, block in results["맞추기"]["자세히"].items():
        lines.append(f"- {key}({block['방식']}): 검토 권장 {block[REVIEW]['맞춘_값']}"
                     f"(95% {block[REVIEW]['95%']}, n {block[REVIEW]['n']}) · 위험 "
                     f"{block[RISK]['맞춘_값']}(95% {block[RISK]['95%']})")
    lines += ["", f"- 지금 기준 {results['지금_기준']}", f"- 새 기준 {results['새_기준']}", ""]
    for i in range(1, 6):
        lines += [f"## 채택 {i} — {results[f'채택_{i}']['통과']}", "",
                  "```", json.dumps(results[f"채택_{i}"], ensure_ascii=False)[:1800], "```", ""]
    lines += ["## 전후 — 대조군 전체 등급", ""]
    for name, block in results["전후_대조군"].items():
        lines.append(f"- {name}: 지금 {_dist(block.get('지금', {}))} → 새 "
                     f"{_dist(block.get('새', {}))}")
    lines += ["", "## 시나리오 16종", "", "| 키 | 제목 | 지금 | 새 |", "|---|---|---|---|"]
    for key, item in results["시나리오"]["지금"].items():
        new = results["시나리오"]["새"].get(key, {})
        if "전체" not in item or "전체" not in new:
            lines.append(f"| {key} | {item.get('제목')} | — | — |")
            continue
        lines.append(f"| {key} | {item['제목']} | {item['전체']['grade']} {item['전체']['prob']} | "
                     f"{new['전체']['grade']} {new['전체']['prob']} |")
    lines += ["", "## 함께 보고 — 업종 겹침", "", "```",
              json.dumps(results["함께_보고"], ensure_ascii=False)[:2500], "```"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("freeze", "run", "apply", "verify"))
    parser.add_argument("--out-dir", type=Path, default=TRIALS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--smoke", action="store_true",
                        help="시험 실행 — 이미지 반마다 4·업종 2·양성 4(--out-dir 를 따로)")
    args = parser.parse_args(argv)
    if args.smoke and args.out_dir.resolve() == TRIALS.resolve():
        print("거절: --smoke 는 --out-dir 를 따로 주세요", file=sys.stderr)
        return EXIT_REFUSED
    return {"freeze": command_freeze, "run": command_run, "apply": command_apply,
            "verify": command_verify}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
