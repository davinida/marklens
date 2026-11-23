"""이름 있는 입력의 공통 검토 권장 기준 — 2차 시도(통합 모델 설계 §7-6). 1차 시도
(named_search_thresholds.py, 설정 13a1ca26…)는 계수 집합마다 따로 맞춘 하한이 채택 조건
①(표본 B)·③(업종을 넣으면 등급이 내려감)에서 멈췄다. 이번에는 바꾸는 것이 둘뿐이다: ① 이름 있는
계수 집합 4벌에 같은 검토 권장 기준 하나(1차 시도의 고정 절차로 대조군 기준용에서 구한 집합별 값
중 가장 큰 값) ② 표본 B 는 채택 조건에서 빼고 참고로만. 주의·위험·업종 하한·이름 없는 입력
기준·사진 규칙·단독 축 규칙은 그대로. 1차 시도의 검색 원자료를 다시 매기고(새로 검색하지 않음),
시나리오 16종과 적용 뒤 확인만 실제 엔진으로 돌린다. KIPRIS 호출 0.

    ml/venv/bin/python ml/scripts/named_shared_threshold.py freeze     # 0. 설정·입력 해시
    ml/venv/bin/python ml/scripts/named_shared_threshold.py run        # 1. 다시 매기기·채택 조건
    ml/venv/bin/python ml/scripts/named_shared_threshold.py scenarios  # 2. 시나리오 16종(엔진)
    ml/venv/bin/python ml/scripts/named_shared_threshold.py apply      # 3. 채택일 때만 v1.4.1
    ml/venv/bin/python ml/scripts/named_shared_threshold.py verify     # 4. 적용 뒤 확인(엔진)

산출(비공개): ml/data/trials/named_shared_threshold_{rule,results,candidate,scenarios_*,
verify}.json·_report.md. 고정본과 다르면 거절(종료 코드 4), 멈춤·미달이면 종료 코드 3.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import os
import subprocess
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

from src.model import risk_model as rm  # noqa: E402

from scripts import named_search_thresholds as first  # noqa: E402

TRIALS = ML_ROOT / "data" / "trials"
STEM = "named_shared_threshold"
EXIT_STOP = 3
EXIT_REFUSED = 4
REVIEW, RISK, CAUTION = "검토 권장", "위험", "주의"
FIRST_RULE_SHA = "13a1ca266784c77ac8ccf0d7b67083f0682cf8994998400c059dab73be526a26"
FIRST_CONTROL_SHA = "f6b11d62b4ced35c73774c6a5a5e7701488cc4d8ce374b316379fd16983bf3f5"
EXPECTED_REVIEW = 0.5059  # 지시가 밝힌 값 — 다시 계산해 다르면 멈춘다
EXPECTED_PER_SET = {"base": 0.4742, "x4": 0.5059, "x2_whole": 0.4645, "x2_whole+x4": 0.4994}
EXPECTED_CITED_NOW = (242, 266)  # 1차 시도의 지금 하한 — 표본 A 인용상표 검토 권장 이상/쌍
NEW_VERSION = "risk_model_v1.4.1"
BASE_MODEL_PATH = rm.V14_MODEL_PATH
NEW_MODEL_PATH = REPO_ROOT / "shared" / "model" / "risk_model_v1.4.1.json"
TARGETS = first.TARGETS
CONFIRM_TOLERANCE = first.CONFIRM_TOLERANCE
PRECISION_MIN = first.PRECISION_MIN
CITED_RATIO_MIN = first.CITED_RATIO_MIN
DISPLAY_TOP = first.DISPLAY_TOP
MODES = first.MODES
FULL_MODE = first.FULL_MODE
SCENARIO_IMAGES = {  # 서비스 v1.4 반영 때(2026-11-20)의 시나리오 16종 입력 그대로
    "text": "ml/data/images/4020050047425.png",  # BLU hands(글자 있는 결합상표)
    "figure": "ml/data/images/4020240111417.png",  # 도형상표
    "starbucks": "ml/data/images/4020200011726.png",  # STARBUCKS COFFEE(DB 로고)
    "unrelated": "ml/data/trials/images/2014101005676/this.png",  # SPINNER(DB 밖)
    "sign": "ml/data/trials/images/2024100001460/target.png",  # 칠우불고기 간판 사진
}
SCENARIO_GOODS = {  # 같은 날 변환표에서 찾은 코드(시나리오 요약 _presets 그대로)
    "카페": ["G0301", "G0502", "S120602", "S2005"], "카페 세트": ["G0301", "G0502", "S120602"],
    "치킨": ["S120602", "G0703"], "세탁": ["S1282"], "빵집": ["G0301", "G0502", "S120602"]}
SCENARIOS = (  # (키, 제목, 입력) — S5 는 S3 의 OCR 제안 이름으로
    ("S1", "이름+카페 세트(블루커피)", {"name": "블루커피", "goods": "카페"}),
    ("S2", "이름+카페+로고(BLU hands)", {"image": "text", "name": "블루커피", "goods": "카페"}),
    ("S3", "로고만(글자 있는 BLU hands)", {"image": "text"}),
    ("S4", "로고만(도형상표)", {"image": "figure"}),
    ("S5", "상표명으로 넣기 재요청(S3 의 제안 이름)", {"image": "text", "name": "@S3"}),
    ("S6", "치킨 세트(굽네치킨)", {"name": "굽네치킨", "goods": "치킨"}),
    ("S7", "지정상품만(카페 세트)", {"goods": "카페"}),
    ("S8", "유형 고치기(도형) — BLU hands+블루커피+카페",
     {"image": "text", "name": "블루커피", "goods": "카페", "override": "도형"}),
    ("F1", "스타벅수 + 카페 세트", {"name": "스타벅수", "goods": "카페 세트"}),
    ("F2", "크린토피야 + 세탁 세트", {"name": "크린토피야", "goods": "세탁"}),
    ("F3", "파리바게트 + 빵집 세트", {"name": "파리바게트", "goods": "빵집"}),
    ("N1", "DB 로고 그대로 이미지만(STARBUCKS COFFEE)", {"image": "starbucks"}),
    ("N2", "같은 로고 + 카페 세트", {"image": "starbucks", "goods": "카페 세트"}),
    ("N3", "무관한 로고 이미지만(SPINNER)", {"image": "unrelated"}),
    ("N4", "유형 고치기(도형) + 다른 이름(STARBUCKS 로고 + 블루커피)",
     {"image": "starbucks", "name": "블루커피", "override": "도형"}),
    ("N5", "간판 사진 + 이름(칠우불고기)", {"image": "sign", "name": "칠우불고기"}),
)

# 규칙(이 지시로 고정 — 실행 전에 해시를 남기고 결과를 보고 바꾸지 않는다) ------------------------
RULE = {
    "바꾸는_것": (
        "두 가지만. ① 기준: 이름 있는 계수 집합 4벌(base·x4·x2_whole·x2_whole+x4)에 같은 검토 "
        "권장 기준 하나 — 1차 시도의 고정 절차('하한' "
        "규칙: 집합마다 자연스러운 방식의 대조군 기준용 "
        "M_q 에서 k = ⌊0.10·n⌋, (k+1)번째로 큰 값보다 큰 가장 작은 넷째 자리 값, 올리기만)로 구한 "
        "집합별 값 중 가장 큰 값(지시가 밝힌 0.5059 — "
        "다시 계산해 다르면 멈춤). 네 집합 모두 목표를 "
        "지키는 가장 낮은 공통 기준. 주의 0.0902·위험 0.5902 그대로. ② 확인 표본: 표본 B 는 다른 "
        "출원인의 실제로 비슷한 상표가 섞여 무관한 후보 "
        "확인에 맞지 않아 채택 조건에서 빼고 참고로만 "
        "보고."),
    "그대로": (
        "계수·축·후보 풀·업종 하한(goods_floor)·이름 없는 입력 기준·사진 규칙·단독 축 규칙·도형 "
        "규칙·nameless_floor."),
    "계산": (
        "1차 시도의 검색 원자료(named_search_thresholds_searches.json.gz — 고정 때 sha256 기록)를 "
        "다시 매긴다(새로 검색하지 않음). 먼저 지금 하한으로 다시 매긴 후보 등급·정렬·전체 등급이 "
        "원자료의 엔진 값과 같은지 확인하고(불일치가 "
        "있으면 멈춤), 집합별 값이 1차 시도와 같은지 확인. "
        "전체 등급 = 다시 정렬한 앞 5건의 최고 등급. "
        "실제 쌍의 축은 1차 시도와 같은 식으로 다시 계산. "
        "시나리오 16종과 적용 뒤 확인만 실제 엔진."),
    "채택_1": (
        "대조군 확인용 100: 네 집합 각각 자연스러운 방식에서 M_q ≥ 새 검토 권장 기준인 질의 ≤ 10%, "
        "M_q ≥ 위험 기준 ≤ 2%. 넘으면 그 표본에 같은 절차를 적용한 그 집합의 값 − 새 기준 ≤ 0.0224 "
        "(1차 시도와 같은 허용 차이)일 때만 통과."),
    "채택_2": (
        "위험 정밀도 — 1차 시도와 같은 방식(v1.3 학습 "
        "OOF 재현, 심결+cross+db, 행마다 그 집합의 위험 "
        "기준) ≥ 0.70. 재현 하한·정밀도가 v1.3 JSON 과 다르면 멈춤."),
    "채택_3": (
        "1차 시도의 검사 그대로: ① 주의 < 검토 권장 < 위험 ② 단조 위반 0 ③ 입력을 더 넣었을 "
        "때 최종 등급이 내려가는 경우 0 — (가) 이름 있는 판단에 이미지·업종 축(≥ 결합 하한)을 "
        "더함: 유형 4(문자계 포함)·관념 게이트·요부 유무 격자의 선형계획. 네 집합 기준이 같으면 "
        "1차 시도 함수는 그 단계를 건너뛰므로(내려갈 수 없음), 위 집합 기준을 관측 축 하나마다 "
        "1e-9 씩 올려 같은 선형계획을 강제로도 돌린다(결합 제약 위반이 있으면 잡힘) (나) 이름 없는 "
        "판단(업종 하한 포함)에 같은 이름을 더함: 같은 방식 (다) 실제 쌍 — 학습 행(이름 있는 "
        "심결·쉬운 음성)·검색 쌍(대조군 기준용·확인용·표본 A·B 이름+이미지+업종의 이름 있는 "
        "무관한 후보). 지금 하한으로도 같은 검사가 0 인지 확인."),
    "채택_4": (
        "표본 A 인용상표 쌍(1차 시도 '채택_4' 와 같은 행·서비스 채점식): 새 기준의 검토 권장 이상 "
        "비율 ≥ 지금 비율(242/266 = 91.0%)의 0.5배. 지금 비율이 1차 시도 값과 다르면 멈춤."),
    "함께_보고": (
        "판정과 별개: 대조군 확인용(방식별 전체 등급)·표본 A 인용상표(쌍별 등급)의 안전·주의·검토 "
        "권장·위험 분포 전후와 안전으로 떨어진 인용상표 쌍(주의 기준이 그대로라 0 이어야 함), "
        "이름+이미지+업종에서 남는 검토 권장 이상의 출처(이름 있는 판단 / 상표명 없는 후보의 이름 "
        "없는 판단), 시나리오 16종 등급 변화(실제 엔진 "
        "— v1.4 대 후보, 서비스 v1.4 반영 때의 입력), "
        "표본 B(참고 — 집합별 비율·그 표본 값·전체 등급)."),
    "적용": (
        "채택될 때만: shared/model/risk_model_v1.4.1.json = risk_model_v1.4.json 에서 "
        "grade_thresholds['검토 권장'] 만 새 값(이름 "
        "있는 4벌이 쓰는 최상위 하한 — 4벌 공통), version "
        "risk_model_v1.4.1, meta.named_grade_thresholds "
        "에 출처·이전 값. 서비스 기본 모델을 v1.4.1 로 "
        "(v1.4 JSON 은 이 파일의 원본으로 남긴다). 적용 뒤 확인: 새 기본 모델로 실제 엔진을 돌려 "
        "대조군 확인용 100 × 4방식의 후보 순서·등급·전체 "
        "등급이 다시 매긴 값과 같아야 하고(불일치 0), "
        "시나리오 16종이 후보 모델 실행과 같아야 한다."),
}


def _settings() -> dict:
    return {"RULE": RULE, "FIRST_RULE_SHA": FIRST_RULE_SHA, "FIRST_CONTROL_SHA": FIRST_CONTROL_SHA,
            "EXPECTED_REVIEW": EXPECTED_REVIEW, "EXPECTED_PER_SET": EXPECTED_PER_SET,
            "EXPECTED_CITED_NOW": EXPECTED_CITED_NOW, "NEW_VERSION": NEW_VERSION,
            "TARGETS": TARGETS, "CONFIRM_TOLERANCE": CONFIRM_TOLERANCE,
            "PRECISION_MIN": PRECISION_MIN, "CITED_RATIO_MIN": CITED_RATIO_MIN,
            "DISPLAY_TOP": DISPLAY_TOP, "MODES": MODES, "SCENARIOS": SCENARIOS,
            "SCENARIO_IMAGES": SCENARIO_IMAGES, "SCENARIO_GOODS": SCENARIO_GOODS}


def rule_sha256() -> str:
    return first.canonical_sha256(_settings())


def _inputs() -> dict[str, Path]:
    """고정 때 해시를 남기는 입력 — 1차 시도 원자료·대조군·규칙, 모델, 학습 특징·사본."""
    paths = first._paths(TRIALS)
    from scripts import train_risk_model as tr

    return {"1차_검색": paths["searches"], "1차_대조군": paths["control"],
            "1차_규칙": paths["rule"],
            "v1.4_JSON": BASE_MODEL_PATH, "v1.3_JSON": Path(rm.V13_MODEL_PATH),
            "학습_특징": tr.DEFAULT_FEATURES, "학습_쉬운음성": tr.DEFAULT_EASY,
            "v1.3_학습_입력": first.V13_INPUTS / "pairs_features.csv",
            "v1.3_학습_쉬운음성": first.V13_INPUTS / "pairs_features_easy.csv"}


def _paths(out_dir: Path) -> dict[str, Path]:
    return {key: out_dir / f"{STEM}_{key}{ext}" for key, ext in (
        ("rule", ".json"), ("results", ".json"), ("report", ".md"), ("candidate", ".json"),
        ("scenarios_base", ".json"), ("scenarios_candidate", ".json"),
        ("scenarios_default", ".json"), ("verify", ".json"))}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---- 기준(순수 함수 — 시험 대상) --------------------------------------------------------------

def shared_thresholds(current: dict, per_set: dict[str, float]) -> dict:
    """네 집합 공통 — 검토 권장 = 집합별 값의 최댓값, 주의·위험 그대로."""
    return {CAUTION: float(current[CAUTION]), REVIEW: round(max(per_set.values()), 4),
            RISK: float(current[RISK])}


def per_set_values(rows: list[dict], current: dict) -> dict[str, float]:
    """1차 시도의 고정 절차('하한')로 집합별 검토 권장 값(올리기만)."""
    out = {}
    for label, pattern, _, _ in MODES:
        maxima = first.per_query_max(rows, label, pattern)
        value, _, _ = first.fit_cut(maxima, TARGETS[REVIEW])
        out[pattern] = first.new_thresholds(current, {REVIEW: value, RISK: None})[REVIEW]
    return out


def candidate_model(base: dict, thresholds: dict, provenance: dict) -> dict:
    """v1.4 JSON → v1.4.1(검토 권장만). 이름 없는 집합·규칙은 그대로."""
    out = copy.deepcopy(base)
    previous = dict(out["grade_thresholds"])
    out["version"] = NEW_VERSION
    out["grade_thresholds"] = dict(thresholds)
    out["grade_basis"] = (
        "주의·위험 = v1.3 그대로(" + str(base.get("grade_basis")) + " — 위험은 그때의 대체값 "
        "0.5902 를 다시 계산하지 않고 둔다). 검토 권장 "
        "= 실제 검색 기준(지어낸 이름 대조군, 2차 시도 — "
        "이름 있는 4벌 공통, 집합별 값 중 가장 큰 값; meta.named_grade_thresholds)")
    out.setdefault("meta", {})["named_grade_thresholds"] = {
        **provenance, "previous": previous, "derived_from": base.get("version")}
    rm.validate_model(out)
    return out


FORCE_STEP = 1e-9  # 같은 기준에서 선형계획을 돌리려고 위 집합 기준을 관측 축 하나마다 올리는 양


def forced_thresholds(model: dict, named: dict) -> dict:
    """위 집합(관측 축이 많은 집합)일수록 기준을 FORCE_STEP 씩 올린 사본 — 모든 단계에서 위
    집합 기준이 아래보다 높아져 first.exact_step_violations 가 선형계획을 건너뛰지 않는다."""
    return {key: {grade: (None if value is None else
                          float(value) + FORCE_STEP * len(rm.pattern_present(key)))
                  for grade, value in named[key].items()} for key in model["patterns"]}


def regrade_overall(entry: dict, named: dict) -> tuple[str | None, dict | None]:
    """(전체 등급, 그 등급을 정한 후보) — 다시 정렬한 앞 5건."""
    shown = first.offline_order(entry["후보"], named)[:DISPLAY_TOP]
    if not shown:
        return None, None
    grade = max((first.offline_grade(c, named) for c in shown), key=rm.GRADES.index)
    return grade, next(c for c in shown if first.offline_grade(c, named) == grade)


def source_kind(candidate: dict, named: dict) -> str:
    """전체 등급을 정한 후보의 판단 종류(함께 보고 — 남는 검토 권장 이상의 출처)."""
    pattern = candidate["pattern"]
    if rm.is_nameless_pattern(pattern):
        return "상표명 없는 후보의 이름 없는 판단"
    if not candidate["이름"]:
        return "상표명 없는 후보(이미지 없음 — 이름 있는 집합)"
    if pattern in named and not first.at_least(rm.grade_for(candidate["p"], named[pattern])):
        return "이름 있는 판단(단독 축 규칙)"
    return "이름 있는 판단"


def grade_counts(grades) -> dict:
    counts = Counter(grades)
    return {grade: counts.get(grade, 0) for grade in (*rm.GRADES, "후보 없음") if counts.get(grade)}


# ---- 1. 다시 매기기·채택 조건 -----------------------------------------------------------------

def _load_samples() -> dict:
    with gzip.open(first._paths(TRIALS)["searches"], "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _cited_transitions(context: dict, model: dict, named: dict) -> dict:
    """표본 A 인용상표 쌍(first.cited_pairs 와 같은 행·채점식)의 쌍별 등급 전후."""
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    cases = {query.key.split(":")[1] for query in context["A"]}
    moves: Counter = Counter()
    by_label: dict[str, Counter] = {"유사": Counter(), "비유사": Counter()}
    for row in t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY).rows:
        if row.get("pair_source") != "trial" or str(row.get("심판번호")) not in cases:
            continue
        if not tr.has_name(row):
            continue
        features = t4.service_features(row, image_column=t4.RAW_IMAGE)
        features["mark_type"] = "결합-문자요부" if features["x2_whole"] is not None else "문자"
        now = first.features_grade(features, model, None)
        new = first.features_grade(features, model, named)
        moves[(now, new)] += 1
        by_label[row.get("최종라벨")][(now, new)] += 1
    to_safe = sum(v for (now, new), v in moves.items() if now != "안전" and new == "안전")
    return {"전후": {f"{now} → {new}": v for (now, new), v in sorted(
        moves.items(), key=lambda kv: (rm.GRADES.index(kv[0][0]), rm.GRADES.index(kv[0][1])))},
            "지금": grade_counts([now for (now, _), v in moves.items() for _ in range(v)]),
            "새": grade_counts([new for (_, new), v in moves.items() for _ in range(v)]),
            "라벨별": {label: {"지금": grade_counts([a for (a, _), v in table.items()
                                                  for _ in range(v)]),
                             "새": grade_counts([b for (_, b), v in table.items()
                                                for _ in range(v)])}
                     for label, table in by_label.items()},
            "안전으로_떨어진_쌍": to_safe}


def _confirm(rows: list[dict], named: dict, current: dict) -> dict:
    table, ok_all = {}, True
    for label, pattern, _, _ in MODES:
        maxima = first.per_query_max(rows, label, pattern)
        own = first.new_thresholds(current, {g: first.fit_cut(maxima, s)[0]
                                             for g, s in TARGETS.items()})
        item: dict = {"방식": label, "질의": len(maxima)}
        for grade, share in TARGETS.items():
            cut = named[pattern][grade]
            rate = first.rate_at_least(maxima, cut)
            diff = round(own[grade] - cut, 4)
            ok = rate is not None and (rate <= share + 1e-12 or diff <= CONFIRM_TOLERANCE + 1e-12)
            item[grade] = {"비율": rate,
                           "지금_기준_비율": first.rate_at_least(maxima, current[grade]),
                           "그_표본_값": own[grade], "차이": diff, "통과": ok}
            ok_all &= ok
        table[pattern] = item
    return {"표": table, "통과": ok_all}


def _residual_sources(samples: dict, named: dict) -> dict:
    out = {}
    for sample_name in ("대조군_기준용", "대조군_확인용", "표본A", "표본B"):
        table = {}
        for label, *_ in MODES:
            kinds: Counter = Counter()
            for row in samples[sample_name]:
                entry = row["방식"].get(label)
                if entry is None:
                    continue
                grade, source = regrade_overall(entry, named)
                if grade is None or not first.at_least(grade):
                    continue
                kinds[f"{grade} · {source_kind(source, named)} · "
                      f"{'무관' if source['무관'] else '관련'}"] += 1
            table[label] = dict(sorted(kinds.items()))
        out[sample_name] = table
    return out


def command_freeze(args) -> int:
    paths = _paths(args.out_dir)
    if paths["rule"].exists() and not args.force:
        print(f"거절: {paths['rule']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    first_rule = json.loads(first._paths(TRIALS)["rule"].read_text(encoding="utf-8"))
    first_control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    if (first_rule["설정_sha256"] != FIRST_RULE_SHA
            or first_control["대조군_sha256"] != FIRST_CONTROL_SHA):
        print("거절: 1차 시도의 규칙·대조군 해시가 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    frozen = {"설정_sha256": rule_sha256(), "스크립트_sha256": first.file_sha256(Path(__file__)),
              "1차_스크립트_sha256": first.file_sha256(Path(first.__file__)),
              "입력_sha256": {k: first.file_sha256(p) for k, p in _inputs().items()},
              "고정": _now(), "설정": _settings()}
    paths["rule"].write_text(json.dumps(frozen, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    print(f"설정 sha256 {frozen['설정_sha256']} · 스크립트 sha256 {frozen['스크립트_sha256']}")
    return 0


def _check_frozen(paths: dict) -> dict | None:
    if not paths["rule"].exists():
        print("거절: 먼저 freeze", file=sys.stderr)
        return None
    frozen = json.loads(paths["rule"].read_text(encoding="utf-8"))
    if frozen["설정_sha256"] != rule_sha256():
        print("거절: 설정이 고정본과 다릅니다", file=sys.stderr)
        return None
    changed = [k for k, p in _inputs().items()
               if first.file_sha256(p) != frozen["입력_sha256"].get(k)]
    if changed:
        print(f"거절: 입력이 고정 때와 다릅니다 — {changed}", file=sys.stderr)
        return None
    return frozen


def command_run(args) -> int:
    paths = _paths(args.out_dir)
    frozen = _check_frozen(paths)
    if frozen is None:
        return EXIT_REFUSED
    if paths["results"].exists() and not args.force:
        print(f"거절: {paths['results']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    model = rm.load_model(BASE_MODEL_PATH)
    current = dict(model["grade_thresholds"])
    samples = _load_samples()
    results: dict = {"설정_sha256": frozen["설정_sha256"],
                     "스크립트_sha256(고정 때)": frozen["스크립트_sha256"],
                     "스크립트_sha256(잴 때)": first.file_sha256(Path(__file__)),
                     "1차_설정_sha256": FIRST_RULE_SHA, "1차_대조군_sha256": FIRST_CONTROL_SHA,
                     "모델(원본)": model["version"], "지금_기준": current,
                     "질의": {k: len(v) for k, v in samples.items()}}
    checks = first.consistency(samples, model)
    per_set = per_set_values(samples["대조군_기준용"], current)
    shared = shared_thresholds(current, per_set)
    results["검산"] = {**checks, "집합별_값": per_set, "집합별_값_1차와_같음":
                     per_set == EXPECTED_PER_SET, "공통_검토권장": shared[REVIEW],
                     "지시_값과_같음": shared[REVIEW] == EXPECTED_REVIEW}
    if any(checks.values()) or per_set != EXPECTED_PER_SET or shared[REVIEW] != EXPECTED_REVIEW:
        results["판정"] = "멈춤 — 재현 불일치"
        return _finish(paths, results, started)
    named = {key: dict(shared) for key in model["patterns"]}
    results["새_기준"] = shared

    results["채택_1"] = _confirm(samples["대조군_확인용"], named, current)
    results["참고_표본B"] = _confirm(samples["표본B"], named, current)
    precision = first.oof_precision(named)
    passed_2 = bool(precision["재현_같음"] and precision["새"]["정밀도"] is not None
                    and precision["새"]["정밀도"] >= PRECISION_MIN)
    results["채택_2"] = {**precision, "통과": passed_2}
    if not precision["재현_같음"]:
        results["판정"] = "멈춤 — 재현 불일치(v1.3 OOF)"
        return _finish(paths, results, started)

    context = first._context()
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    query_of = {}
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))["대조군"]
    for set_name, items in control["이름"].items():
        for entry in items:
            query_of[f"대조군:{set_name}:{entry['이름']}"] = {
                "이름": entry["이름"], "유사군": frozenset(entry["유사군"])}
    for query in [*context["A"], *context["B"]]:
        query_of[query.key] = {"이름": query.name, "유사군": query.goods}
    order_ok = {key: first.ordered(value) for key, value in named.items()}
    monotone = {key: len(rm.monotone_violations(block["coefficients"]))
                for key, block in model["patterns"].items()}
    current_named = {key: dict(current) for key in model["patterns"]}
    steps = first.exact_step_violations(model, named)
    forced = first.exact_step_violations(model, forced_thresholds(model, named))
    same_name = first.exact_same_name_violations(model, named)
    sanity = {"지금_기준_(가)": first.exact_step_violations(model, current_named)["위반"],
              "지금_기준_(나)": first.exact_same_name_violations(model, current_named)["위반"]}
    train_rows = [t4.service_features(row, image_column="x2_whole")
                  for row in t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY).rows
                  if tr.has_name(row)]
    pairs: list[dict] = []
    for sample_name in samples:
        pairs += first.search_pair_features(context["ms"], samples[sample_name], query_of)
    data_train = first.data_step_violations(train_rows, model, named)
    data_search = first.data_step_violations(pairs, model, named)
    data_total = sum(item["위반"] for table in (data_train, data_search)
                     for item in table.values())
    text_family = (0 if steps["위반"] == 0 else  # 위반이 있으면 남긴 예(최대 12) 가운데 문자계 수
                   sum(1 for item in steps["예"] if item["유형"] in rm.TEXT_FAMILY))
    passed_3 = (all(order_ok.values()) and not any(monotone.values()) and steps["위반"] == 0
                and forced["위반"] == 0 and same_name["위반"] == 0 and data_total == 0
                and not any(sanity.values()))
    results["채택_3"] = {"순서": order_ok, "단조_위반": monotone, "(가)_격자": steps,
                       "(가)_격자_강제": forced,
                       "(가)_문자계_위반": text_family, "(나)_같은이름": same_name,
                       "검산_지금기준": sanity, "(다)_학습행": data_train,
                       "(다)_검색쌍": data_search,
                       "(다)_행수": {"학습": len(train_rows), "검색": len(pairs)},
                       "(다)_위반_합계": data_total, "통과": passed_3}

    cited = first.cited_pairs(context, model, named)
    now_pair = (cited["수"].get("지금_이상", 0), cited["수"].get("쌍", 0))
    cited["지금_1차와_같음"] = now_pair == EXPECTED_CITED_NOW
    results["채택_4"] = cited
    results["인용상표_전후"] = _cited_transitions(context, model, named)
    if not cited["지금_1차와_같음"]:
        results["판정"] = "멈춤 — 재현 불일치(인용상표 지금 비율)"
        return _finish(paths, results, started)

    results["전후(전체 등급)"] = first.before_after(samples, model, named)
    results["남는_검토권장_출처"] = _residual_sources(samples, named)
    results["이름_없는_하한_목표(참고)"] = first.NAMELESS_REFERENCE
    adopted = (results["채택_1"]["통과"] and passed_2 and passed_3 and cited["통과"])
    results["채택"] = bool(adopted)
    failed = [n for n, ok in (("①", results["채택_1"]["통과"]), ("②", passed_2),
                              ("③", passed_3), ("④", cited["통과"])) if not ok]
    results["판정"] = "채택" if adopted else f"멈춤 — 채택 조건 미달({'·'.join(failed)})"
    provenance = {"calibrated_at": _now()[:10],
                  "method": "실제 검색 기준 — 지어낸 이름 대조군(2차 시도: 이름 있는 4벌 공통 "
                            "검토 권장 = 집합별 값 중 가장 큰 값)",
                  "rule_sha256": frozen["설정_sha256"], "first_attempt_rule_sha256": FIRST_RULE_SHA,
                  "per_set": per_set, "adopted": bool(adopted)}
    candidate = candidate_model(json.loads(BASE_MODEL_PATH.read_text(encoding="utf-8")), shared,
                                provenance)
    paths["candidate"].write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
    results["후보_JSON"] = str(paths["candidate"])
    return _finish(paths, results, started)


def _finish(paths: dict, results: dict, started: float) -> int:
    results["걸린_시간_s"] = round(time.perf_counter() - started, 1)
    results["끝"] = _now()
    paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    text = report_text(results)
    paths["report"].write_text(text, encoding="utf-8")
    print(text)
    return 0 if results.get("채택") else EXIT_STOP


# ---- 2. 시나리오 16종(실제 엔진) ---------------------------------------------------------------

def scenario_inputs(ms, decode) -> list[tuple[str, str, dict]]:
    out = []
    for key, title, spec in SCENARIOS:
        inputs = {}
        if "image" in spec:
            raw = (REPO_ROOT / SCENARIO_IMAGES[spec["image"]]).read_bytes()
            inputs["image"] = decode(raw)
        if "name" in spec:
            inputs["name"] = spec["name"]
        if "goods" in spec:
            inputs["goods_codes"] = list(SCENARIO_GOODS[spec["goods"]])
        if "override" in spec:
            inputs["type_override"] = spec["override"]
        out.append((key, title, inputs))
    return out


def command_scenario_run(args) -> int:
    """하위 프로세스 — MARKLENS_RISK_MODEL(없으면 기본)로 엔진을 띄워 16종을 돌린다."""
    from scripts import nameless_search_thresholds as nst

    model_path = Path(args.model) if args.model else rm.resolve_model_path()
    engine, ms = nst.load_engine(model_path)
    service, _ = nst.decoders()
    results = {"모델": ms.state.model["version"], "모델_파일": str(model_path), "시나리오": {}}
    suggested = None
    for key, title, inputs in scenario_inputs(ms, service):
        if inputs.get("name") == "@S3":
            if not suggested:
                results["시나리오"][key] = {"제목": title, "건너뜀": "S3 제안 이름 없음"}
                continue
            inputs["name"] = suggested
            title = f"{title} — name={suggested!r}"
        data = ms.multi_search(**inputs, top_k=DISPLAY_TOP).to_dict()
        pooled = ms.search_pool(**inputs)
        if key == "S3":
            suggested = data["overall"]["query_type"].get("suggested_name")
        results["시나리오"][key] = {
            "제목": title, "전체": {k: data["overall"][k] for k in ("grade", "prob", "pattern")},
            "유형": data["overall"]["query_type"]["type"],
            "상위": [{"id": c["id"], "title": c["title"], "grade": c["risk"]["grade"],
                    "prob": c["risk"]["prob"], "pattern": c["risk"]["pattern"],
                    "rules": c["risk"]["rule_triggers"]} for c in data["candidates"]],
            "풀": [{"id": c.id, "등급": c.grade, "p": float(c.prob), "pattern": c.pattern,
                   "규칙": list(c.rule_triggers), "rank": [int(c.rank[0]), float(c.rank[1])],
                   "x2_img": c.axes["x2_img"], "이름": bool(c.title), "무관": True}
                  for c in pooled.candidates],
            "기준": data["meta"]["thresholds"]["grade"]}
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                              encoding="utf-8")
    return 0


def _spawn_scenarios(model: Path | None, out: Path) -> None:
    env = {**os.environ}
    env.pop(rm.ENV_MODEL_PATH, None)
    command = [sys.executable, str(Path(__file__)), "scenario-run", "--out", str(out)]
    if model is not None:
        command += ["--model", str(model)]
    subprocess.run(command, check=True, env=env, cwd=str(REPO_ROOT))


def scenario_table(base: dict, other: dict, named: dict) -> list[dict]:
    """시나리오별 전후 — 원본 풀을 새 기준으로 다시 매긴 값이 후보 모델 실행과 같은지도."""
    rows = []
    for key, before in base["시나리오"].items():
        after = other["시나리오"].get(key, {})
        if "전체" not in before or "전체" not in after:
            rows.append({"키": key, "제목": before.get("제목"), "건너뜀": True})
            continue
        spec = {k: v for k, _, v in SCENARIOS}.get(key, {})
        # 유형을 고친 질의는 엔진이 이름 있는·없는 판단을 견준다(nameless_floor) — 원자료에 이름
        # 없는 판단의 위험도가 없어 다시 매길 수 없다
        offline = None if "override" in spec else regrade_overall({"후보": before["풀"]}, named)[0]
        rows.append({"키": key, "제목": before["제목"], "유형": before["유형"],
                     "전": before["전체"], "후": after["전체"],
                     "후_1위": (after["상위"][0]["title"] if after["상위"] else None),
                     "전_1위": (before["상위"][0]["title"] if before["상위"] else None),
                     "다시_매긴_전체": offline,
                     "일치": None if offline is None else offline == after["전체"]["grade"]})
    return rows


def command_scenarios(args) -> int:
    paths = _paths(args.out_dir)
    if _check_frozen(paths) is None:
        return EXIT_REFUSED
    if not paths["candidate"].exists():
        print("거절: 먼저 run(후보 JSON)", file=sys.stderr)
        return EXIT_REFUSED
    _spawn_scenarios(BASE_MODEL_PATH, paths["scenarios_base"])
    _spawn_scenarios(paths["candidate"], paths["scenarios_candidate"])
    base = json.loads(paths["scenarios_base"].read_text(encoding="utf-8"))
    other = json.loads(paths["scenarios_candidate"].read_text(encoding="utf-8"))
    results = json.loads(paths["results"].read_text(encoding="utf-8"))
    named = {key: dict(results["새_기준"]) for key in rm.load_model(BASE_MODEL_PATH)["patterns"]}
    table = scenario_table(base, other, named)
    results["시나리오"] = {"원본": base["모델"], "후보": other["모델"], "표": table,
                       "불일치": sum(1 for row in table if row.get("일치") is False)}
    paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    paths["report"].write_text(report_text(results), encoding="utf-8")
    print(scenario_text(results["시나리오"]))
    return 0


# ---- 3. 적용·4. 적용 뒤 확인 -------------------------------------------------------------------

def command_apply(args) -> int:
    paths = _paths(args.out_dir)
    if _check_frozen(paths) is None:
        return EXIT_REFUSED
    results = json.loads(paths["results"].read_text(encoding="utf-8"))
    if not results.get("채택"):
        print("거절: 채택되지 않았습니다 — 적용하지 않습니다", file=sys.stderr)
        return EXIT_REFUSED
    if NEW_MODEL_PATH.exists() and not args.force:
        print(f"거절: {NEW_MODEL_PATH} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    candidate = json.loads(paths["candidate"].read_text(encoding="utf-8"))
    rm.validate_model(candidate)
    NEW_MODEL_PATH.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    print(f"썼다: {NEW_MODEL_PATH} ({candidate['version']}, 검토 권장 "
          f"{candidate['grade_thresholds'][REVIEW]})")
    return 0


def command_verify(args) -> int:
    """적용 뒤 확인 — 새 기본 모델로 실제 엔진: 대조군 확인용 100 × 4방식 + 시나리오 16종."""
    paths = _paths(args.out_dir)
    if _check_frozen(paths) is None:
        return EXIT_REFUSED
    results = json.loads(paths["results"].read_text(encoding="utf-8"))
    if rm.resolve_model_path() != NEW_MODEL_PATH or rm.MODEL_VERSION != NEW_VERSION:
        print("거절: 서비스 기본 모델이 v1.4.1 이 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    from scripts import nameless_search_thresholds as nst

    started = time.perf_counter()
    context = nst.prepare(argparse.Namespace(
        model=rm.resolve_model_path(), metadata=nst.DEFAULT_METADATA, labels=nst.DEFAULT_LABELS,
        trial_list=nst.DEFAULT_LIST, image_pairs=nst.DEFAULT_IMAGE_PAIRS,
        aliases=nst.DEFAULT_ALIASES, limit=0))
    context["nst"] = nst
    context["trial_list"] = {row["심판번호"]: row for row in nst._read_csv(nst.DEFAULT_LIST)}
    context["labels"] = nst._read_csv(nst.DEFAULT_LABELS)
    context["db_numbers"] = _db_numbers(nst)
    ms = context["ms"]
    if ms.state.model["version"] != NEW_VERSION:
        print("거절: 엔진이 적재한 모델이 v1.4.1 이 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    named = {key: dict(results["새_기준"]) for key in ms.state.model["patterns"]}
    samples = _load_samples()
    old_rows = {row["질의"]: row for row in samples["대조군_확인용"]}
    a_by_key = {query.key: query for query in context["A"]}
    everything = {label: (lambda _cid: True) for label, *_ in MODES}
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))["대조군"]
    mismatch = Counter()
    for item in control["이름"]["확인용"]:
        source = a_by_key[item["이미지"]]
        cited, owners = first.a_relations(context, source)
        related = first.unrelated_filter(context, owners, cited)
        filters = {label: (related if with_image else everything[label])
                   for label, _, _, with_image in MODES}
        image = context["service"](source.path.read_bytes())
        fresh = first.search_query(ms, image, item["이름"], frozenset(item["유사군"]), MODES,
                                   filters)
        old = old_rows[f"대조군:확인용:{item['이름']}"]
        for label, *_ in MODES:
            expected = first.offline_order(old["방식"][label]["후보"], named)
            got = fresh[label]["후보"]
            if [c["id"] for c in expected] != [c["id"] for c in got]:
                mismatch["순서"] += 1
            if [first.offline_grade(c, named) for c in expected] != [c["등급"] for c in got]:
                mismatch["후보_등급"] += 1
            want, _ = regrade_overall(old["방식"][label], named)
            shown = got[:DISPLAY_TOP]
            have = max((c["등급"] for c in shown), key=rm.GRADES.index) if shown else None
            mismatch["전체_등급"] += int(want != have)
    _spawn_scenarios(None, paths["scenarios_default"])
    default = json.loads(paths["scenarios_default"].read_text(encoding="utf-8"))
    candidate = json.loads(paths["scenarios_candidate"].read_text(encoding="utf-8"))
    scenario_diff = [key for key, item in default["시나리오"].items()
                     if item.get("전체") != candidate["시나리오"].get(key, {}).get("전체")
                     or [c["id"] for c in item.get("상위", [])] != [
                         c["id"] for c in candidate["시나리오"].get(key, {}).get("상위", [])]]
    verify = {"모델": ms.state.model["version"],
              "대조군_확인용_검색": len(control["이름"]["확인용"]),
              "불일치": dict(mismatch), "시나리오_기본모델": default["모델"],
              "시나리오_후보와_다른_것": scenario_diff,
              "통과": not any(mismatch.values()) and not scenario_diff,
              "걸린_시간_s": round(time.perf_counter() - started, 1), "끝": _now()}
    paths["verify"].write_text(json.dumps(verify, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")
    print(json.dumps(verify, ensure_ascii=False))
    return 0 if verify["통과"] else EXIT_STOP


def _db_numbers(nst) -> dict[str, str]:
    numbers: dict[str, str] = {}
    metadata = json.loads(nst.DEFAULT_METADATA.read_text(encoding="utf-8"))
    for record in metadata.get("trademarks", metadata):
        for field_name in ("출원번호", "등록번호"):
            value = str(record.get(field_name) or "").strip()
            if value:
                numbers[value] = str(record["출원번호"])
    return numbers


# ---- 보고 -------------------------------------------------------------------------------------

def _pct(value) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _dist(table: dict) -> str:
    return " · ".join(f"{grade} {table[grade]}" for grade in (*rm.GRADES, "후보 없음")
                      if table.get(grade))


def _match(value) -> str:
    return "—(유형 고치기)" if value is None else "같음" if value else "다름"


def scenario_text(block: dict) -> str:
    lines = [f"## 시나리오 16종(실제 엔진 — {block['원본']} 대 {block['후보']})", "",
             "| 키 | 시나리오 | 전(등급·위험도·집합) | 후(등급·위험도·집합) | 1위(전 → 후) | "
             "원본 풀을 다시 매긴 값 = 후 |", "|---|---|---|---|---|---|"]
    for row in block["표"]:
        if row.get("건너뜀"):
            lines.append(f"| {row['키']} | {row['제목']} | — | — | — | — |")
            continue
        before, after = row["전"], row["후"]
        lines.append(f"| {row['키']} | {row['제목']} | {before['grade']} {before['prob']} "
                     f"{before['pattern']} | {after['grade']} {after['prob']} {after['pattern']} | "
                     f"{row['전_1위']} → {row['후_1위']} | {_match(row['일치'])} |")
    lines += ["", f"불일치 {block['불일치']}"]
    return "\n".join(lines) + "\n"


def report_text(results: dict) -> str:
    lines = [f"# 이름 있는 입력의 공통 검토 권장 기준 — 2차 시도 ({results['끝'][:10]})", "",
             f"설정 sha256 `{results['설정_sha256']}` · 1차 설정 "
             f"`{results['1차_설정_sha256'][:8]}…` · 모델(원본) {results['모델(원본)']}", "",
             f"**판정: {results['판정']}**", "",
             f"검산 `{json.dumps(results['검산'], ensure_ascii=False)}`"]
    if "새_기준" not in results:
        return "\n".join(lines) + "\n"
    shared = results["새_기준"]
    header = ["| 집합 | 방식 | 질의 | 검토 권장 이상(지금 → 새) | 그 표본 값·차이 | "
              "위험 이상 |", "|---|---|---:|---|---|---|"]
    lines += ["", f"새 기준(이름 있는 4벌 공통): 주의 {shared[CAUTION]} · 검토 권장 "
              f"{shared[REVIEW]} · 위험 {shared[RISK]}", "",
              f"## 채택 조건 ① 대조군 확인용 — {results['채택_1']['통과']}", "", *header]
    for name in ("채택_1", "참고_표본B"):
        if name == "참고_표본B":
            lines += ["", "참고 — 표본 B(채택 조건 아님):", "", *header]
        for pattern, item in results[name]["표"].items():
            review, risk = item[REVIEW], item[RISK]
            lines.append(f"| {pattern} | {item['방식']} | {item['질의']} | "
                         f"{_pct(review['지금_기준_비율'])} → {_pct(review['비율'])} | "
                         f"{review['그_표본_값']}·{review['차이']} | {_pct(risk['비율'])} |")
    second = results["채택_2"]
    lines += ["", f"## ② 위험 정밀도 — {second['통과']}", "",
              f"재현 {second['재현_같음']} · 지금 {second['지금']['위험_이상']}행 "
              f"{second['지금']['정밀도']} → 새 {second['새']['위험_이상']}행 "
              f"{second['새']['정밀도']}"]
    if "채택_3" in results:
        third = results["채택_3"]
        lines += ["", f"## ③ 순서·단조·입력 더함 — {third['통과']}", "",
                  f"- 순서 {third['순서']} · 단조 위반 {third['단조_위반']}",
                  f"- (가) 격자 검사 {third['(가)_격자']['검사']} · 위반 "
                  f"{third['(가)_격자']['위반']}(문자계 {third['(가)_문자계_위반']}) · "
                  f"강제 검사 {third['(가)_격자_강제']['검사']} · 위반 "
                  f"{third['(가)_격자_강제']['위반']} · (나) 같은 이름 검사 "
                  f"{third['(나)_같은이름']['검사']} · 위반 {third['(나)_같은이름']['위반']}",
                  f"- 지금 기준 검산 `{json.dumps(third['검산_지금기준'], ensure_ascii=False)}`",
                  f"- (다) 실제 쌍 위반 {third['(다)_위반_합계']}(학습 "
                  f"{third['(다)_행수']['학습']}행·검색 {third['(다)_행수']['검색']}쌍)"]
    if "채택_4" in results:
        fourth = results["채택_4"]
        cited = results["인용상표_전후"]
        lines += ["", f"## ④ 표본 A 인용상표 — {fourth['통과']}", "",
                  f"검토 권장 이상 {_pct(fourth['지금_비율'])} → {_pct(fourth['새_비율'])}"
                  f"(비 {round(fourth['비'], 3) if fourth['비'] else '—'}) · 지금 비율 1차와 같음 "
                  f"{fourth['지금_1차와_같음']}", "",
                  f"쌍별 등급: 지금 {_dist(cited['지금'])} → 새 {_dist(cited['새'])} · "
                  f"안전으로 떨어진 쌍 {cited['안전으로_떨어진_쌍']}",
                  f"- 유사: {_dist(cited['라벨별']['유사']['지금'])} → "
                  f"{_dist(cited['라벨별']['유사']['새'])}",
                  f"- 비유사: {_dist(cited['라벨별']['비유사']['지금'])} → "
                  f"{_dist(cited['라벨별']['비유사']['새'])}",
                  f"- 전후: `{json.dumps(cited['전후'], ensure_ascii=False)}`"]
    if "전후(전체 등급)" in results:
        lines += ["", "## 전체 등급 분포(표시 상위 5, 다시 매김)", ""]
        for sample_name, table in results["전후(전체 등급)"].items():
            for label, item in table.items():
                lines.append(f"- {sample_name} {label}: {_dist(item['지금'])} → "
                             f"{_dist(item['새'])}")
        lines += ["", "## 남는 검토 권장 이상의 출처(새 기준)", ""]
        for sample_name, table in results["남는_검토권장_출처"].items():
            for label, kinds in table.items():
                lines.append(f"- {sample_name} {label}: `{json.dumps(kinds, ensure_ascii=False)}`")
    if "시나리오" in results:
        lines += ["", scenario_text(results["시나리오"])]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("freeze", "run", "scenarios", "scenario-run",
                                            "apply", "verify"))
    parser.add_argument("--out-dir", type=Path, default=TRIALS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--model", help="scenario-run: 계수 JSON(없으면 서비스 기본)")
    parser.add_argument("--out", help="scenario-run: 결과 파일")
    args = parser.parse_args(argv)
    commands = {"freeze": command_freeze, "run": command_run, "scenarios": command_scenarios,
                "scenario-run": command_scenario_run, "apply": command_apply,
                "verify": command_verify}
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

