"""통합 모델 v1.4 2차 시도(마지막) — 이름 있는 입력은 v1.3 그대로 두고, 이름 없는 입력(이미지만 /
이미지+상품)용 계수 집합 2벌만 새로 학습해 v1.3 에 덧붙인다(통합 모델 설계 §7-4 "2차 시도").
KIPRIS 호출 0. 서비스가 쓰는 모델 파일(`shared/model/risk_model_v1.json`)은 건드리지 않는다.

    ml/venv/bin/python ml/scripts/train_risk_model_v14_nameless.py           # 전체
    ml/venv/bin/python ml/scripts/train_risk_model_v14_nameless.py --bootstrap 20 \\
        --metric-bootstrap 100 --repeats 1 --no-sensitivity --out-dir /tmp/v14b   # 빠른 확인

왜: 1차 시도(train_risk_model_v14.py)는 이름 결합 제약의 하한(쉬운 음성 평균)이 데이터와 어긋나 이름
있는 입력의 변별력을 깎았다(채택 기준 ①·② 미달). 이득은 이름 없는 쪽에서만 나왔다.

방법(결과를 보기 전에 고정):
  - 이름 있는 4벌 = v1.3 의 계수·등급 하한·단독 임계값·grade_precision 을 그대로 복사(재학습 없음).
  - 이름 없는 2벌(`noname:x2_whole`·`noname:x2_whole+x4`): 데이터(이미지가 관측된 모든 행 — 이름이
    있는 행도 이름을 가리고 참여)·사건 가중·사진 규칙·사전분포는 1차 시도와 같다. 제약은 ① 단조
    (기울기 ≥ 0) ② 두 벌 사이의 축 결합(상품을 하한 이상으로 더하면 로짓 비감소 — 하한은 v1.3 JSON
    의 `coupling.floors`) ③ **같은 이름**: 이름 없는 입력에 후보와 같은 이름(호칭·철자 1.0)을 더했을
    때 v1.3 이 내는 로짓 ≥ 이름 없는 집합의 로짓. 더한 뒤의 유형은 서비스 규칙대로 문자계
    (`rm.type_with_name` — 도형계였던 입력은 결합-문자요부). 이미지·상품 값 0·1 의 모든 꼭짓점에서
    걸므로(두 로짓 모두 그 값들에 대해 다중선형) 이미지 유사도 전 구간에서 성립한다.
  - 명세가 정하지 않아 여기서 고정한 것: 같은 이름을 더한 입력의 요부 플래그는 요부 있음·없음 **둘
    다**(v1.3 은 호칭 1.0 에서 요부 없음이 로짓 −0.19 라 그쪽이 더 낮다), 관념은 게이트가 꺼진
    것으로(값 0 — 계수가 음이 아니므로 가장 낮은 경우), 이름 없는 입력의 유형은 문자계·도형계 둘 다.
  - 1차 시도의 이름 하한 결합은 쓰지 않는다. 다른 변형은 돌리지 않는다.

채택 기준(ADOPTION — 미리 고정, 이번이 마지막 시도): ① 이름 있는 입력의 출력이 v1.3 과 완전히 같다
② 이름 없는 행: Brier 짝 차이(v1.4 − v1.3) CI 상한 < 0, AUC 짝 차이 CI 상한이 0 미만이 아님
③ 쉬운 음성을 섞은 전체 AUC 짝 차이 CI 하한 > 0 ④ 단조성 위반 0(기존 축 결합 + 같은 이름 추가).
하나라도 미달이면 v1.3 유지로 확정한다 — 그때는 `shared/model/risk_model_v1.4.json` 을 쓰지 않고
후보만 `ml/data/trials/risk_model_v1.4_attempt2_candidate.json` 으로 남긴다(종료 코드 3).

2026-11-19 실행 결과: 네 기준 모두 통과 — 채택(설계 §7-4). 판정을 본 **뒤에** 참고 진단 하나를
덧붙였다(`image_only_population` — 이미지만 질의를 가정한 집합: 이름 없는 심결 행 + 이름을 가린 쉬운
음성 이미지 쌍). 채택 기준이 아니고 적합·판정에 영향을 주지 않는다. 서비스에 반영하기 전에 이름 없는
입력의 등급 하한을 정하는 근거로 쓴다.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from scipy.special import expit  # noqa: E402
from src.model import risk_model as rm  # noqa: E402

from scripts import nameless_grade_thresholds as ngt  # noqa: E402  (이름 없는 입력의 등급 하한)
from scripts import train_risk_model as tr  # noqa: E402
from scripts import train_risk_model_v14 as t4  # noqa: E402  (1차 시도 — 데이터·지표 도우미)

MODEL_VERSION = "risk_model_v1.4"
DEFAULT_MODEL = rm.REPO_ROOT / "shared" / "model" / "risk_model_v1.4.json"  # 채택되면 쓰는 경로
DEFAULT_V13 = t4.DEFAULT_V13
DEFAULT_OUT_DIR = t4.DEFAULT_OUT_DIR
REPORT_STEM = "risk_model_v1.4_attempt2"
RANDOM_INPUTS = 20_000  # 기준 ①: 무작위 이름 있는 입력 수
SAME_NAME = {"x1_d": 1.0, "x2_text_d": 1.0}  # 같은 이름 = 호칭·철자 1.0
IMAGE_LEVELS = t4.IMAGE_ONLY_LEVELS  # 0.5·0.7·0.9·1.0
PREFIX = rm.NAMELESS_PREFIX
NEW, OLD = "v1.4(2차 시도)", "v1.3 그대로"
# 채택 기준(결과를 보기 전에 고정) --------------------------------------------------------------
ADOPTION = {
    "기본": ("네 기준을 모두 채우면 v1.4 채택. 하나라도 미달이면 v1.3 유지로 확정(세 번째 시도 "
             "없음)"),
    "①": ("이름 있는 입력의 출력(확률·등급·기여도·패턴·도형 caveat)이 v1.3 과 완전히 같다 — 무작위 "
          f"이름 있는 입력 {RANDOM_INPUTS:,}개와 학습에 쓴 이름 있는 심결 행 전부에서 차이 0"),
    "②": ("이름 없는 행(사건 가중, 묶음 부트스트랩): Brier 짝 차이(v1.4 − v1.3)의 95% CI 상한 < 0, "
          "그리고 AUC 짝 차이(v1.4 − v1.3)의 95% CI 상한이 0 미만이 아님"),
    "③": ("쉬운 음성을 섞은 전체(심결+cross+db, 사건 가중) AUC 짝 차이(v1.4 − v1.3)의 95% CI "
          "하한 > 0"),
    "④": ("단조성: 기존 축 결합(이름 있는 패턴 사이·이름 없는 패턴 사이)에서 하한 이상 행의 위반 "
          "0, '같은 이름 추가'에서 위반 0(이미지가 관측된 모든 행 — 요부 있음·없음 둘 다), 런타임 "
          "적재 검증(coupling_violations) 위반 0"),
    "평가": ("이름 있는 행·쉬운 음성의 v1.4 확률 = v1.3 그대로(재학습·사진 규칙 없이), 이름 없는 "
             "행은 묶음 단위 5겹 × 3반복 OOF. v1.3 그대로 = 배포 JSON 을 그대로 적용한 값"),
}


def _round(value, digits: int = 4):
    return t4._round(value, digits)  # noqa: SLF001


# ---- 설계·제약 ---------------------------------------------------------------------------------

def nameless_ids(design: t4.Design) -> list[str]:
    return [PREFIX + key for key in design.nameless_keys]


def fixed_named(design: t4.Design, model_old: dict) -> dict[str, tuple[np.ndarray, float]]:
    """이름 있는 4벌 — v1.3 JSON 의 값 그대로(재학습 없음). 설계의 항 목록이 JSON 과 같아야 한다."""
    if tuple(model_old.get("pattern_axes") or ()) != tuple(design.axes):
        raise ValueError("v1.3 JSON 의 pattern_axes 가 설계와 다릅니다")
    out = {}
    for key in design.named_keys:
        block = model_old["patterns"][key]
        if list(block["features"]) != list(design.names[key]):
            raise ValueError(f"v1.3 JSON 의 patterns[{key}] 입력 항이 설계와 다릅니다")
        out[key] = (np.asarray([float(block["coefficients"][name])
                                for name in design.names[key]]), float(block["intercept"]))
    return out


def build_constraints(design: t4.Design, floors: dict[str, float],
                      same_name: dict | None = None) -> list[t4.Constraint]:
    """이름 없는 2벌의 제약 G·θ ≥ 0(이름 있는 4벌은 고정이라 상수항으로 들어간다): 단조, 두 벌
    사이의 축 결합(축 하나를 하한값으로 더 관측), 같은 이름(v1.3 의 로짓 ≥ 이름 없는 집합의
    로짓)."""
    same_name = SAME_NAME if same_name is None else same_name
    out: list[t4.Constraint] = []
    for block in nameless_ids(design):
        names = design.names[block]
        for g in tr.monotone_constraints(names):
            row = np.zeros(design.size)
            start = design.offset[block]
            row[start:start + len(g)] = g
            terms = " + ".join(name for name, value in zip(names, g) if value)
            out.append(t4.Constraint("단조", f"{block}: {terms} ≥ 0", row))
    for key in design.nameless_keys:
        block = PREFIX + key
        present = rm.pattern_present(key)
        for axis in present:
            lower_key = rm.pattern_key([a for a in present if a != axis], design.axes)
            if lower_key not in design.nameless_keys:
                continue
            lower = PREFIX + lower_key
            for vertex in rm.nameless_vertices(design.names[lower]):
                label = (f"{lower} → {block} ({axis}={floors[axis]}) @ "
                         f"{t4._vertex_label(vertex)}")  # noqa: SLF001
                out.append(t4.Constraint(
                    "결합(이름 없음, 축)", label,
                    t4._difference(design, block, {**vertex, axis: floors[axis]},  # noqa: SLF001
                                   lower, vertex)))
    for key in design.nameless_keys:
        block = PREFIX + key
        for vertex in rm.nameless_vertices(design.names[block]):
            for distinctive in (True, False):
                upper = rm.same_name_input(vertex, same_name, distinctive=distinctive)
                label = (f"{block} → {key} (같은 이름) @ {t4._vertex_label(vertex)}, "  # noqa: SLF001
                         f"요부없음={not distinctive}")
                out.append(t4.Constraint(
                    "결합(같은 이름)", label,
                    t4._difference(design, key, upper, block, vertex)))  # noqa: SLF001
    return out


def fit(design: t4.Design, a: dict, index: np.ndarray, constraints: list[t4.Constraint],
        fixed: dict) -> t4.Fit:
    return t4.fit_joint(design, a["y"], a["fit_weight"], index, constraints, fixed=fixed)


def figure_logit(design: t4.Design, blocks: dict, block: str, index: np.ndarray) -> np.ndarray:
    """이름 없는 집합의 로짓을 도형계 입력으로 본 값(×도형계 항에 이미지 값을 넣는다) — 서비스의
    이미지만 질의는 언제나 도형계다(계약 v2 §2-4 5항)."""
    names = design.names[block]
    X = design.X[block][index].copy()
    X[:, names.index("x2_whole×도형계")] = X[:, names.index("x2_whole")]
    coef, intercept = blocks[block]
    return X @ coef + intercept


def cv_nameless(design: t4.Design, a: dict, constraints: list[t4.Constraint], fixed: dict, *,
                folds: int, repeats: int, seed: int) -> dict:
    """묶음 단위 반복 교차검증 — 이름 없는 2벌의 OOF 확률(반복 평균). 겹은 1차 시도와 같다.
    per_block_figure 는 같은 겹 모델을 도형계 입력으로 본 값(참고 진단용)."""
    ids = nameless_ids(design)
    total = {block: np.zeros(a["y"].size) for block in ids}
    figure = {block: np.zeros(a["y"].size) for block in ids}
    success, slack = [], []
    for repeat in range(repeats):
        for train, test in tr.folds_for(a["y"], a["groups"], folds=folds, seed=seed + repeat):
            result = fit(design, a, train, constraints, fixed)
            success.append(result.success)
            slack.append(result.min_slack)
            for block in ids:
                total[block][test] += expit(design.logit(result.blocks, block, test))
                figure[block][test] += expit(figure_logit(design, result.blocks, block, test))
    return {"per_block": {block: value / repeats for block, value in total.items()},
            "per_block_figure": {block: value / repeats for block, value in figure.items()},
            "겹_수": len(success), "수렴_실패": int(len(success) - sum(success)),
            "최소_여유": _round(min(slack), 9) if slack else None}


def combine(design: t4.Design, prob_old: np.ndarray, per_block: dict) -> np.ndarray:
    """v1.4(2차 시도)의 행별 확률: 이름 없는 행(자기 집합이 이름 없는 집합)만 새 집합의 값, 나머지는
    v1.3 그대로."""
    prob = prob_old.copy()
    for block, values in per_block.items():
        where = design.own == block
        prob[where] = values[where]
    return prob


def train_once(rows: list[dict], model_old: dict, *, folds: int = t4.FOLDS,
               repeats: int = t4.REPEATS, seed: int = 0,
               min_minority: int = tr.MIN_PATTERN_MINORITY) -> dict:
    a = t4.arrays(rows)
    nameless_keys, choice = t4.choose_nameless_keys(rows, a, min_minority)
    if not nameless_keys:
        raise ValueError(f"이름 없는 패턴이 소수 클래스 기준을 못 채웁니다: {choice}")
    design = t4.Design(rows, structure="v1.4", nameless_keys=nameless_keys)
    floors = {axis: float(value) for axis, value in model_old["coupling"]["floors"].items()}
    fixed = fixed_named(design, model_old)
    constraints = build_constraints(design, floors)
    cv = cv_nameless(design, a, constraints, fixed, folds=folds, repeats=repeats, seed=seed)
    final = fit(design, a, np.arange(len(rows)), constraints, fixed)
    prob_old = t4.v13_probabilities(rows, model_old)
    return {"arrays": a, "design": design, "floors": floors, "fixed": fixed,
            "constraints": constraints, "cv": cv, "final": final, "prob_old": prob_old,
            "prob_new": combine(design, prob_old, cv["per_block"]), "nameless_choice": choice}


# ---- 모델 JSON ---------------------------------------------------------------------------------

def rounded_nameless(design: t4.Design, blocks: dict, digits: int = 4) -> dict:
    out = {}
    for key in design.nameless_keys:
        block = PREFIX + key
        coef, intercept = blocks[block]
        entry = {"requires": rm.pattern_present(key), "features": list(design.names[block]),
                 "coefficients": {name: round(float(value), digits) + 0.0
                                  for name, value in zip(design.names[block], coef)},
                 "intercept": round(float(intercept), digits)}
        step = 10.0 ** -digits
        for _ in range(20):  # 반올림이 만든 단조 위반 보정(1차 시도와 같은 방식)
            violations = rm.monotone_violations(entry["coefficients"])
            if not violations:
                break
            name = "x2_whole×도형계"
            if name in entry["coefficients"] and any(name in v for v in violations):
                entry["coefficients"][name] = round(entry["coefficients"][name] + step, digits)
            for axis in tr.AXES:
                if any(v.startswith(f"{axis} ") and "+" not in v for v in violations):
                    entry["coefficients"][axis] = 0.0
        out[key] = entry
    return out


def build_model(model_old: dict, design: t4.Design, final: t4.Fit, nameless_meta: dict,
                digits: int = 4) -> dict:
    """v1.3 JSON 을 그대로 복사하고 이름 없는 2벌과 같은 이름 제약의 기준점만 더한다. 반올림이 만든
    작은 결합 위반은 이름 없는 집합의 절편을 내려 고친다(이름 있는 집합은 손대지 않는다)."""
    model = copy.deepcopy(model_old)
    model["version"] = MODEL_VERSION
    model["trained_at"] = date.today().isoformat()
    nameless = rounded_nameless(design, final.blocks, digits)
    model[rm.NAMELESS_KEY] = nameless
    model["coupling"] = {
        **copy.deepcopy(model_old["coupling"]),
        rm.SAME_NAME_KEY: {
            **SAME_NAME,
            "basis": ("이름 없는 입력에 후보와 같은 이름(호칭·철자 1.0)을 더했을 때 이름 있는 패턴"
                      "(v1.3)의 로짓 ≥ 이름 없는 패턴의 로짓 — 더한 뒤의 유형은 문자계(도형계였던 "
                      "입력은 결합-문자요부), 요부 있음·없음 둘 다, 관념 게이트 꺼짐, 이미지·상품 "
                      "값의 모든 꼭짓점. 학습은 선형 제약, 런타임은 적재 때 검증"),
        },
    }
    step = 10.0 ** -digits
    for _ in range(10_000):
        violations = rm._nameless_coupling_violations(model, tr.COUPLING_TOLERANCE)  # noqa: SLF001
        if not violations:
            break
        key = violations[0].split(" → ")[0][len(PREFIX):]  # 위반한 쪽(하위) 집합의 절편을 내린다
        nameless[key]["intercept"] = round(nameless[key]["intercept"] - step, digits)
    for key in nameless:
        nameless[key]["meta"] = nameless_meta["집합"][PREFIX + key]
    model["meta"] = {
        **copy.deepcopy(model_old["meta"]),
        "named_from": {"version": model_old["version"], "trained_at": model_old.get("trained_at"),
                       "note": ("이름 있는 4벌(patterns)·등급 하한·단독 임계값·grade_precision·"
                                "figure_rule 은 v1.3 JSON 을 그대로 복사 — 위 meta 의 n·AUC 도 "
                                "v1.3 학습 때의 값")},
        "nameless": nameless_meta,
    }
    rm.validate_model(model)
    return model


# ---- 기준 ①: 이름 있는 입력의 출력이 v1.3 과 같은가 -------------------------------------------

def random_inputs(n: int, seed: int) -> list[dict]:
    """무작위 입력(런타임 입력 사전). 이름 축은 임의로 비우되 호칭·철자 중 하나는 있게(이름 있는
    입력), 이미지·상품·관념은 임의로 비운다."""
    rng = np.random.default_rng(seed)
    levels = (*rm.TYPE_LEVELS, "미상", "")
    out = []
    for _ in range(n):
        x1 = None if rng.random() < 0.15 else float(rng.random())
        x2_text = None if rng.random() < 0.15 else float(rng.random())
        if x1 is None and x2_text is None:
            if rng.random() < 0.5:
                x1 = float(rng.random())
            else:
                x2_text = float(rng.random())
        out.append({
            "x1_d": x1, "x2_text_d": x2_text,
            "x3_d": None if rng.random() < 0.4 else float(rng.random()),
            "x2_whole": None if rng.random() < 0.3 else float(rng.random()),
            "x4": None if rng.random() < 0.4 else float(rng.random()),
            "has_meaning_both": bool(rng.random() < 0.5),
            "has_distinctive_part_a": bool(rng.random() < 0.8),
            "has_distinctive_part_b": bool(rng.random() < 0.8),
            "mark_type": levels[int(rng.integers(len(levels)))],
        })
    return out


def count_differences(inputs: list[dict], model_new: dict, model_old: dict) -> int:
    """risk_score 결과(확률·등급·기여도·도형 caveat·패턴)가 한 칸이라도 다른 입력 수."""
    return sum(1 for features in inputs
               if tuple(rm.risk_score(features, model_new)) != tuple(
                   rm.risk_score(features, model_old)))


def named_identity(rows: list[dict], model_new: dict, model_old: dict, *,
                   n_random: int = RANDOM_INPUTS, seed: int = 0) -> dict:
    """기준 ① — 무작위 이름 있는 입력과 학습에 쓴 이름 있는 행(원래 이미지 값·사진 규칙 뒤 값 둘
    다), 참고로 쉬운 음성과 '이름도 이미지도 없는' 입력(상품만 등 — 종전대로여야 한다)."""
    named = [row for row in rows if row["pair_source"] == "trial" and tr.has_name(row)]
    easy = [row for row in rows if row["pair_source"] != "trial"]
    raw = [t4.service_features(row, image_column=t4.RAW_IMAGE) for row in named]
    ruled = [t4.service_features(row) for row in named]
    randoms = random_inputs(n_random, seed)
    no_image = [{**features, "x1_d": None, "x2_text_d": None, "x3_d": None, "x2_whole": None}
                for features in randoms[:2000]]
    out = {
        "무작위_이름_있는_입력": {"n": len(randoms),
                          "차이": count_differences(randoms, model_new, model_old)},
        "이름_있는_심결_행(원래 이미지 값)": {"n": len(raw),
                                  "차이": count_differences(raw, model_new, model_old)},
        "이름_있는_심결_행(사진 규칙 뒤)": {"n": len(ruled),
                                "차이": count_differences(ruled, model_new, model_old)},
        "쉬운_음성(참고)": {"n": len(easy), "차이": count_differences(
            [t4.service_features(row, image_column=t4.RAW_IMAGE) for row in easy],
            model_new, model_old)},
        "이름도_이미지도_없는_입력(참고)": {"n": len(no_image), "차이": count_differences(
            no_image, model_new, model_old)},
    }
    out["통과"] = all(out[key]["차이"] == 0 for key in (
        "무작위_이름_있는_입력", "이름_있는_심결_행(원래 이미지 값)",
        "이름_있는_심결_행(사진 규칙 뒤)"))
    return out


# ---- 기준 ④: 단조성(행 단위, 반올림한 배포 모델로) --------------------------------------------

def _nameless_input(row: dict, *, goods: bool, mark_type: str | None = None) -> dict:
    """행 → 이름 없는 입력(원래 이미지 값). goods=False 면 상품도 가린다."""
    features = t4.service_features(row, image_column=t4.RAW_IMAGE)
    return {"x1_d": None, "x2_text_d": None, "x3_d": None, "has_meaning_both": False,
            "has_distinctive_part_a": True, "has_distinctive_part_b": True,
            "x2_whole": features["x2_whole"], "x4": features["x4"] if goods else None,
            "mark_type": features["mark_type"] if mark_type is None else mark_type}


def row_monotonicity(rows: list[dict], model: dict,
                     tolerance: float = tr.COUPLING_TOLERANCE) -> dict:
    """(a) 기존 축 결합 — 이름 있는 패턴 사이(이름 있는 행·쉬운 음성)와 이름 없는 패턴 사이(이미지·
    상품이 관측된 모든 행, 이름을 가림): 더 관측한 축 값이 하한 이상인 행에서 로짓이 내려가면 위반.
    (b) 같은 이름 추가 — 이미지가 관측된 모든 행(원래 이미지 값; 상품이 있으면 두 키 모두, 행의
    유형과 도형으로 본 유형 둘 다, 요부 있음·없음 둘 다): 이름 없는 집합의 로짓 > v1.3 이 같은
    이름에 내는 로짓이면 위반."""
    floors = model["coupling"]["floors"]
    patterns, nameless = model["patterns"], model[rm.NAMELESS_KEY]
    axes = list(model["pattern_axes"])
    same_name = model["coupling"].get(rm.SAME_NAME_KEY)
    out: dict = {"축_결합": {}, "같은_이름": {}}

    def record(table: dict, label: str, delta: float, above: bool) -> None:
        item = table.setdefault(label, {"하한_이상_n": 0, "위반": 0, "로짓차_최소": None,
                                        "하한_미만_n": 0, "하한_미만_내려간_수": 0})
        if above:
            item["하한_이상_n"] += 1
            item["위반"] += int(delta < -tolerance)
            if item["로짓차_최소"] is None or delta < item["로짓차_최소"]:
                item["로짓차_최소"] = delta
        else:
            item["하한_미만_n"] += 1
            item["하한_미만_내려간_수"] += int(delta < 0)

    for row in rows:
        named = row["pair_source"] != "trial" or tr.has_name(row)
        features = t4.service_features(row, image_column=t4.RAW_IMAGE)
        observed = [axis for axis in axes if features[axis] is not None]
        if named:  # 이름 있는 패턴 사이(v1.3 그대로)
            values = rm.design_values(features)
            for key, upper in patterns.items():
                present = rm.pattern_present(key)
                if not present or any(axis not in observed for axis in present):
                    continue
                for axis in present:
                    lower_key = rm.pattern_key([x for x in present if x != axis], axes)
                    delta = rm.block_logit(upper, values) - rm.block_logit(
                        patterns[lower_key], values)
                    record(out["축_결합"], f"{lower_key} → {key} ({axis})", delta,
                           features[axis] >= float(floors[axis]))
        if features["x2_whole"] is None:
            continue
        for key, upper in nameless.items():  # 이름 없는 패턴 사이
            present = rm.pattern_present(key)
            if any(axis not in observed for axis in present):
                continue
            values = rm.design_values(_nameless_input(row, goods=True))
            for axis in present:
                lower_key = rm.pattern_key([x for x in present if x != axis], axes)
                if lower_key not in nameless:
                    continue
                delta = rm.block_logit(upper, values) - rm.block_logit(nameless[lower_key], values)
                record(out["축_결합"], f"{PREFIX}{lower_key} → {PREFIX}{key} ({axis})", delta,
                       features[axis] >= float(floors[axis]))
        for key, lower in nameless.items():  # 같은 이름 추가
            present = rm.pattern_present(key)
            if any(axis not in observed for axis in present):
                continue
            goods = "x4" in present
            for mark_type in (None, "도형"):
                base = _nameless_input(row, goods=goods, mark_type=mark_type)
                low = rm.block_logit(lower, rm.design_values(base))
                for distinctive in (True, False):
                    high = rm.block_logit(patterns[key], rm.design_values(
                        rm.same_name_input(base, same_name, distinctive=distinctive)))
                    label = (f"{PREFIX}{key} → {key} ("
                             f"{'행의 유형' if mark_type is None else '도형으로'}, "
                             f"요부 {'있음' if distinctive else '없음'})")
                    record(out["같은_이름"], label, high - low, True)
    for table in out.values():
        for item in table.values():
            item["로짓차_최소"] = _round(item["로짓차_최소"])
    out["위반_합계"] = {name: sum(item["위반"] for item in table.values())
                    for name, table in out.items() if isinstance(table, dict)}
    out["런타임_결합_검증_위반"] = rm.coupling_violations(model)[:5]
    out["통과"] = (sum(out["위반_합계"].values()) == 0 and not out["런타임_결합_검증_위반"])
    return out


# ---- 평가 표 -----------------------------------------------------------------------------------

def new_minus_old(diff: dict) -> dict:
    """t4.paired_difference 의 Brier(옛 − 새)를 새 − 옛으로 뒤집는다(음수면 개선)."""
    if diff.get("차이") is None:
        return {"차이": None, "ci95": [None, None]}
    low, high = diff["ci95"]
    return {"차이": _round(-diff["차이"]), "ci95": [_round(-high), _round(-low)]}


def comparison_table(rows: list[dict], a: dict, prob_new: np.ndarray, prob_old: np.ndarray,
                     boot: t4.Bootstrap | None) -> dict:
    """평가 2 — 부분집합마다 v1.3 그대로·v1.4(2차 시도)의 가중 AUC·Brier 와 짝 차이(둘 다 v1.4 −
    v1.3: AUC 는 양수가, Brier 는 음수가 개선)."""
    out = {}
    for name, mask in t4.subset_masks(rows).items():
        if not mask.any():
            continue
        entry = {OLD: t4.metric_block(prob_old, a["y"], a["eval_weight"], mask, boot),
                 NEW: t4.metric_block(prob_new, a["y"], a["eval_weight"], mask, boot)}
        if boot is not None:
            diff = t4.paired_difference(prob_new, prob_old, a["y"], a["eval_weight"], mask, boot)
            entry["짝_차이_auc"] = diff["auc"]
            entry["짝_차이_brier"] = new_minus_old(diff["brier"])
        out[name] = entry
    return out


def grade_tables(rows: list[dict], a: dict, prob_new: np.ndarray, prob_old: np.ndarray,
                 thresholds: dict) -> dict:
    """등급별 건수·정밀도(사건 가중) — 이름 없는 행, 도형계, 쉬운 음성을 섞은 전체. 등급 하한은 v1.3
    그대로(복사)."""
    masks = t4.subset_masks(rows)
    out = {}
    for name in ("이름 없는 행", "도형계", "심결+cross+db"):
        mask = masks[name]
        out[name] = {label: t4.grade_table(prob[mask], a["y"][mask], a["eval_weight"][mask],
                                           thresholds)
                     for label, prob in ((OLD, prob_old), (NEW, prob_new))}
    return out


def image_only_table(model_new: dict, model_old: dict) -> list[dict]:
    """평가 6 — 이미지만(·이미지+상품 1.0) 입력의 위험도 v1.3 대 v1.4, 그리고 거기에 후보와 같은
    이름을 더했을 때(v1.3 의 이름 있는 패턴 — 유형은 결합-문자요부로, 요부 있음/없음)."""
    same_name = model_new["coupling"].get(rm.SAME_NAME_KEY)
    out = []

    def cell(result: rm.RiskResult) -> dict:
        return {"p": _round(result.prob), "등급": result.grade, "패턴": result.pattern}

    for goods in (None, 1.0):
        for level in ("도형", "결합-도형요부"):
            for value in IMAGE_LEVELS:
                base = {"x1_d": None, "x2_text_d": None, "x3_d": None, "x4": goods,
                        "x2_whole": value, "has_meaning_both": False,
                        "has_distinctive_part_a": True, "has_distinctive_part_b": True,
                        "mark_type": level}
                out.append({
                    "유형": level, "x2_whole": value, "x4": goods,
                    "v1.3": cell(rm.risk_score(base, model_old)),
                    "v1.4": cell(rm.risk_score(base, model_new)),
                    "같은_이름(요부 있음)": cell(rm.risk_score(
                        rm.same_name_input(base, same_name, distinctive=True), model_new)),
                    "같은_이름(요부 없음)": cell(rm.risk_score(
                        rm.same_name_input(base, same_name, distinctive=False), model_new)),
                })
    return out


def image_only_population(rows: list[dict], a: dict, design: t4.Design, cv: dict,
                          model_old: dict, boot: t4.Bootstrap | None) -> dict:
    """참고(채택 기준 아님 — 판정을 본 뒤에 덧붙인 진단): 이미지만 질의를 가정한 집합 = 이름 없는
    심결 행 + 이미지가 있는 쉬운 음성 쌍의 이름을 가린 것(무관한 상표, 라벨 비유사). 모두 도형계
    입력으로 본다. v1.4 는 이미지만 집합의 OOF, v1.3 은 이름 항 0(지금 서비스의 계산). 두 모델 모두
    이미지 유사도의 증가함수라 순서는 거의 같고, 달라지는 것은 확률의 높이와 등급이다."""
    block = PREFIX + "x2_whole"
    if block not in design.ids:
        return {}
    image = design.mask[block]
    nameless = a["trial"] & ~a["named"] & image
    easy = a["easy"] & image
    mask = nameless | easy
    prob_new = cv["per_block_figure"][block]
    prob_old = np.asarray([
        rm.risk_score(_nameless_input(row, goods=False, mark_type="도형"), model_old).prob
        if keep else 0.0 for row, keep in zip(rows, mask)])
    thresholds = model_old["grade_thresholds"]
    y, weight = a["y"], a["eval_weight"]

    def easy_grades(prob: np.ndarray) -> dict:
        grades = [rm.grade_for(float(p), thresholds) for p in prob[easy]]
        return {"평균_p": _round(float(prob[easy].mean())) if easy.any() else None,
                **{grade: grades.count(grade) for grade in rm.GRADES}}

    out = {
        "n": int(mask.sum()), "이름_없는_심결_행": int(nameless.sum()),
        "쉬운_음성(이름 가림)": int(easy.sum()), "유사": int((y[mask] == 1).sum()),
        OLD: t4.metric_block(prob_old, y, weight, mask, boot),
        NEW: t4.metric_block(prob_new, y, weight, mask, boot),
        "등급": {label: t4.grade_table(prob[mask], y[mask], weight[mask], thresholds)
               for label, prob in ((OLD, prob_old), (NEW, prob_new))},
        "쉬운_음성(이름 가림)_등급": {OLD: easy_grades(prob_old), NEW: easy_grades(prob_new)},
    }
    if boot is not None:
        diff = t4.paired_difference(prob_new, prob_old, y, weight, mask, boot)
        out["짝_차이_auc"] = diff["auc"]
        out["짝_차이_brier"] = new_minus_old(diff["brier"])
    return out


def grade_boundaries(model: dict) -> dict:
    """이름 없는 이미지만 집합에서 각 등급 하한에 닿는 이미지 유사도(문자계·도형계)."""
    block = (model.get(rm.NAMELESS_KEY) or {}).get("x2_whole")
    if not block:
        return {}
    base = float(block["coefficients"]["x2_whole"])
    extra = float(block["coefficients"].get("x2_whole×도형계", 0.0))
    out = {}
    for family, slope in (("문자계", base), ("도형계", base + extra)):
        out[family] = {
            grade: _round((float(np.log(p / (1 - p))) - float(block["intercept"])) / slope, 3)
            if slope > 0 else None for grade, p in model["grade_thresholds"].items()}
    return out


def bootstrap_nameless(design: t4.Design, a: dict, constraints: list[t4.Constraint], fixed: dict,
                       *, rounds: int, seed: int) -> dict:
    """심결 묶음 복원추출(쉬운 음성 고정) 재적합 — 이름 없는 2벌의 계수 분포와 도형계 기울기
    (x2_whole + x2_whole×도형계)."""
    rng = np.random.default_rng(seed)
    by_group: dict[str, list[int]] = {}
    for index in np.flatnonzero(~a["easy"]):
        by_group.setdefault(a["groups"][index], []).append(index)
    keys = np.asarray(list(by_group))
    members = {key: np.asarray(value) for key, value in by_group.items()}
    easy_index = np.flatnonzero(a["easy"])
    ids = nameless_ids(design)
    samples = {block: [] for block in ids}
    failures = 0
    for _ in range(rounds):
        chosen = rng.choice(keys, keys.size, replace=True)
        index = np.concatenate([members[key] for key in chosen] + [easy_index])
        result = fit(design, a, index, constraints, fixed)
        failures += int(not result.success)
        for block in ids:
            coef, intercept = result.blocks[block]
            samples[block].append([*coef, intercept])
    out = {"rounds": rounds, "수렴_실패": failures, "집합": {}}
    for block in ids:
        matrix = np.asarray(samples[block])
        names = [*design.names[block], "intercept"]
        table = {name: {"평균": _round(matrix[:, i].mean()), "ci95": t4._ci(matrix[:, i])}  # noqa: SLF001
                 for i, name in enumerate(names)}
        slope = matrix[:, names.index("x2_whole")] + matrix[:, names.index("x2_whole×도형계")]
        table["도형계 기울기(x2_whole + ×도형계)"] = {"평균": _round(slope.mean()),
                                              "ci95": t4._ci(slope)}  # noqa: SLF001
        out["집합"][block] = table
    return out


def nameless_block_meta(design: t4.Design, a: dict, summary: dict, table: dict, cv: dict,
                        final: t4.Fit, adoption: dict | None, *, folds: int, repeats: int,
                        bootstrap: int, metric_bootstrap: int) -> dict:
    counts = t4.block_counts(design, a["y"], a["fit_weight"], a["easy"])
    return {
        "attempt": "v1.4 2차 시도 — 이름 있는 4벌은 v1.3 그대로, 이름 없는 2벌만 학습",
        "trained_at": date.today().isoformat(),
        "집합": {block: {k: counts[block][k] for k in (
            "n", "n_심결", "n_쉬운_음성", "유사", "비유사", "가중_유사", "가중_비유사",
            "자기_패턴_행", "자기_패턴_심결")} for block in nameless_ids(design)},
        "n_trial": summary["심결_행(학습)"], "n_nameless": summary["이름_없는_행"]["n"],
        "n_excluded_no_name_no_image": summary["이름도_이미지도_없어_제외"]["n"],
        "n_easy": sum(summary["쉬운_음성"].values()), "rounds": summary["회차"],
        "case_weight": {**summary["사건_가중"], "rule": "w = min(1, 3 / 그 사건의 행 수)"},
        "w_easy": t4.W_EASY,
        "photo": {**summary["사진_규칙"],
                  "rule": ("사진A·사진B(src.photo_mark) 가운데 하나라도 1 이면 이미지 축을 관측 "
                           "없음으로 — 이름 없는 집합의 학습 행에만 적용")},
        "prior": {"mu": {name: tr.PRIOR_MU[name] for name in ("x2_whole", "x2_whole×도형계", "x4")},
                  "sigma": t4.SIGMA, "intercept_prior": False},
        "constraints": ("단조(기울기 ≥ 0) + 두 벌 사이의 축 결합(coupling.floors) + 같은 이름"
                        "(coupling.same_name)"),
        "folds": folds, "repeats": repeats, "bootstrap": bootstrap,
        "metric_bootstrap": metric_bootstrap,
        "cv": {name: {"auc_가중": entry[NEW]["auc_가중"], "brier_가중": entry[NEW]["brier_가중"],
                      "auc_가중_v1.3": entry[OLD]["auc_가중"],
                      "brier_가중_v1.3": entry[OLD]["brier_가중"]}
               for name, entry in table.items()},
        "optimizer": {"solver": final.solver, "kkt_residual": final.kkt_residual,
                      "min_slack": final.min_slack, "cv_수렴_실패": cv["수렴_실패"]},
        "adoption": adoption,
    }


def adoption_check(identity: dict, table: dict, monotone: dict) -> dict:
    """미리 고정한 기준 ①~④ 적용."""
    nameless = table.get("이름 없는 행") or {}
    mixed = table.get("심결+cross+db") or {}
    brier = (nameless.get("짝_차이_brier") or {}).get("ci95") or [None, None]
    auc = (nameless.get("짝_차이_auc") or {}).get("ci95") or [None, None]
    mixed_auc = (mixed.get("짝_차이_auc") or {}).get("ci95") or [None, None]
    second = brier[1] is not None and brier[1] < 0 and auc[1] is not None and not auc[1] < 0
    third = mixed_auc[0] is not None and mixed_auc[0] > 0
    verdict = {
        "①": {"통과": bool(identity.get("통과")), "근거": {
            key: value for key, value in identity.items() if key != "통과"}},
        "②": {"통과": bool(second), "근거": {
            "이름 없는 행 n": (nameless.get(NEW) or {}).get("n"),
            "Brier 짝 차이(v1.4 − v1.3)": nameless.get("짝_차이_brier"),
            "AUC 짝 차이(v1.4 − v1.3)": nameless.get("짝_차이_auc")}},
        "③": {"통과": bool(third), "근거": {
            "심결+cross+db AUC 짝 차이(v1.4 − v1.3)": mixed.get("짝_차이_auc")}},
        "④": {"통과": bool(monotone.get("통과")), "근거": {
            "위반_합계": monotone.get("위반_합계"),
            "런타임_결합_검증_위반": monotone.get("런타임_결합_검증_위반")}},
    }
    passed = all(item["통과"] for item in verdict.values())
    return {"기준": ADOPTION, "판정표": verdict, "채택": passed,
            "판정": ("v1.4 채택" if passed
                     else "v1.3 유지로 확정 — 채택 기준 미달(세 번째 시도 없음)")}


def sensitivity_row(label: str, dataset: t4.Dataset, model_old: dict, *, folds: int,
                    repeats: int, seed: int, metric_bootstrap: int, min_minority: int) -> dict:
    """평가 8 — 조건을 바꿔 이름 없는 2벌을 다시 학습(이름 있는 쪽은 언제나 v1.3 그대로)."""
    result = train_once(dataset.rows, model_old, folds=folds, repeats=repeats, seed=seed,
                        min_minority=min_minority)
    a, design = result["arrays"], result["design"]
    boot = t4.Bootstrap(a["groups"], metric_bootstrap, seed) if metric_bootstrap else None
    table = comparison_table(dataset.rows, a, result["prob_new"], result["prob_old"], boot)
    first = PREFIX + design.nameless_keys[0]
    coef = dict(zip(design.names[first], result["final"].blocks[first][0]))
    last = PREFIX + design.nameless_keys[-1]
    last_coef = dict(zip(design.names[last], result["final"].blocks[last][0]))
    subsets = ("전체", "2차", "도형계", "이름 없는 행", "심결+cross+db")
    return {
        "조건": label, "심결_행": dataset.summary["심결_행(학습)"],
        "이름_없는_행": dataset.summary["이름_없는_행"]["n"],
        "제외": dataset.summary["이름도_이미지도_없어_제외"]["n"],
        "지표": {name: {"auc_가중_v1.3": table[name][OLD]["auc_가중"],
                       "auc_가중": table[name][NEW]["auc_가중"],
                       "brier_가중_v1.3": table[name][OLD]["brier_가중"],
                       "brier_가중": table[name][NEW]["brier_가중"],
                       "짝_차이_auc": table[name].get("짝_차이_auc"),
                       "짝_차이_brier": table[name].get("짝_차이_brier")}
               for name in subsets if name in table},
        "계수": {"절편": _round(result["final"].blocks[first][1]),
                "x2_whole": _round(coef.get("x2_whole")),
                "x2_whole×도형계": _round(coef.get("x2_whole×도형계")),
                "도형계 기울기": _round(coef.get("x2_whole", 0.0)
                                   + coef.get("x2_whole×도형계", 0.0)),
                "x4(이미지+상품)": _round(last_coef.get("x4"))},
        "수렴_실패": result["cv"]["수렴_실패"] + int(not result["final"].success),
    }


# ---- 실행 --------------------------------------------------------------------------------------

def run(features_path: Path, easy_path: Path, *, out_dir: Path, model_path: Path,
        v13_path: Path = DEFAULT_V13, folds: int = t4.FOLDS, repeats: int = t4.REPEATS,
        bootstrap: int = t4.BOOTSTRAP, metric_bootstrap: int = t4.METRIC_BOOTSTRAP,
        seed: int = 0, n_random: int = RANDOM_INPUTS, sensitivity: bool = True,
        min_pattern_minority: int = tr.MIN_PATTERN_MINORITY) -> dict:
    model_old = rm.validate_model(json.loads(Path(v13_path).read_text(encoding="utf-8")))
    dataset = t4.load_dataset(features_path, easy_path)
    rows, summary = dataset.rows, dataset.summary
    common = {"folds": folds, "repeats": repeats, "seed": seed}
    result = train_once(rows, model_old, min_minority=min_pattern_minority, **common)
    a, design, final = result["arrays"], result["design"], result["final"]
    prob_new, prob_old = result["prob_new"], result["prob_old"]
    boot = t4.Bootstrap(a["groups"], metric_bootstrap, seed)
    table = comparison_table(rows, a, prob_new, prob_old, boot)
    meta = nameless_block_meta(design, a, summary, table, result["cv"], final, None, folds=folds,
                               repeats=repeats, bootstrap=bootstrap,
                               metric_bootstrap=metric_bootstrap)
    model = build_model(model_old, design, final, meta)
    identity = named_identity(rows, model, model_old, n_random=n_random, seed=seed)
    monotone = row_monotonicity(rows, model)
    adoption = adoption_check(identity, table, monotone)
    adoption["안정성"] = {
        "최종_적합_KKT_잔차": final.kkt_residual, "최종_적합_최소_여유": final.min_slack,
        "교차검증_수렴_실패": result["cv"]["수렴_실패"], "교차검증_겹": result["cv"]["겹_수"],
    }
    model["meta"]["nameless"]["adoption"] = {"채택": adoption["채택"], "판정": adoption["판정"]}
    boot_fits = bootstrap_nameless(design, a, result["constraints"], result["fixed"],
                                   rounds=bootstrap, seed=seed) if bootstrap else None
    if boot_fits:
        adoption["안정성"]["부트스트랩_수렴_실패"] = boot_fits["수렴_실패"]
    active = t4.active_constraints(result["constraints"], final.theta)
    coefficients = {}
    for block in nameless_ids(design):
        coef, intercept = final.blocks[block]
        rounded = model[rm.NAMELESS_KEY][block[len(PREFIX):]]
        coefficients[block] = {
            "적합값": {**{name: _round(value) for name, value in zip(design.names[block], coef)},
                    "intercept": _round(intercept)},
            "JSON": {**rounded["coefficients"], "intercept": rounded["intercept"]},
            "부트스트랩": boot_fits["집합"][block] if boot_fits else None,
        }
    results = {
        "기준일": date.today().isoformat(), "시도": "v1.4 2차 시도(마지막)", "데이터": summary,
        "집합": meta["집합"], "결합_하한(v1.3 JSON)": result["floors"], "같은_이름": SAME_NAME,
        "이름_없는_패턴_결정": result["nameless_choice"],
        "채택": adoption,
        "평가_2_OOF": table,
        "계수": coefficients, "제약": active,
        "등급(v1.3 하한 그대로)": {"하한": model_old["grade_thresholds"],
                             "표": grade_tables(rows, a, prob_new, prob_old,
                                               model_old["grade_thresholds"])},
        "평가_6_이미지만_같은_이름": image_only_table(model, model_old),
        "단조성(행)": monotone,
        "쉬운_음성_평균_p": {OLD: _round(float(prob_old[a["easy"]].mean())),
                         NEW: _round(float(prob_new[a["easy"]].mean()))},
        "참고_이미지만_질의_가정(판정 뒤 추가)": {
            **image_only_population(rows, a, design, result["cv"], model_old, boot),
            "등급_하한에_닿는_이미지_유사도": grade_boundaries(model)},
    }
    if sensitivity:
        variants = (("주 실행", {}), (f"사건 {t4.BIG_CASE} 제외", {"drop_cases": (t4.BIG_CASE,)}),
                    ("사진 규칙 없음", {"photo_rule": False}),
                    ("2등급에서 살아난 행 제외", {"drop_augmented": True}))
        results["평가_8_민감도"] = [
            sensitivity_row(label, t4.load_dataset(features_path, easy_path, **options),
                            model_old, metric_bootstrap=metric_bootstrap,
                            min_minority=min_pattern_minority, **common)
            for label, options in variants]
    if adoption["채택"]:
        # 채택된 모델에는 이름 없는 입력의 등급 하한을 붙여서 쓴다(계수와 위 표들은 그대로 — 위 표의
        # 등급은 하한을 정하기 전, v1.3 하한 기준이다). 규칙·보고는 nameless_grade_thresholds.
        calibration = ngt.calibrate(rows, model_old, model)
        before, model = model, ngt.apply_thresholds(model, calibration)
        results["등급_하한(이름 없는 입력)"] = ngt.evaluate(
            rows, model_old, before, model, calibration, prob_new, design.own, a)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = Path(model_path)
    written = model_path if adoption["채택"] else out_dir / f"{REPORT_STEM}_candidate.json"
    written.parent.mkdir(parents=True, exist_ok=True)
    written.write_text(json.dumps(model, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    results["모델_파일"] = str(written)
    results["모델_파일_설명"] = ("채택 — 배포 경로(서비스 기본 모델 경로는 v1.3 그대로)"
                            if adoption["채택"] else
                            "채택 기준 미달 — 후보로만 저장(배포 경로에는 쓰지 않음), v1.3 유지")
    (out_dir / f"{REPORT_STEM}_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / f"{REPORT_STEM}_report.md").write_text(report_text(results), encoding="utf-8")
    return results


# ---- 보고서 ------------------------------------------------------------------------------------

def _f(value, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _ci(ci) -> str:
    return "" if not ci or ci[0] is None else f" ({ci[0]:.2f}~{ci[1]:.2f})"


def _diff(diff: dict | None) -> str:
    if not diff or diff.get("차이") is None:
        return "—"
    low, high = diff["ci95"]
    return f"{diff['차이']:+.3f} ({low:+.3f}~{high:+.3f})"


def report_text(results: dict) -> str:
    data = results["데이터"]
    adoption = results["채택"]
    lines = [f"# 통합 모델 v1.4 2차 시도 보고 ({results['기준일']})", "",
             f"## 채택 판단 — {adoption['판정']}", "",
             "| 기준 | 판정 | 근거 |", "|---|---|---|"]
    verdict = adoption["판정표"]
    first = verdict["①"]["근거"]
    lines.append("| ① 이름 있는 입력 = v1.3 | " + ("통과" if verdict["①"]["통과"] else "미달")
                 + " | " + "; ".join(f"{key} {item['n']}개 중 차이 {item['차이']}"
                                     for key, item in first.items()) + " |")
    second = verdict["②"]["근거"]
    lines.append("| ② 이름 없는 행 | " + ("통과" if verdict["②"]["통과"] else "미달")
                 + f" | n {second['이름 없는 행 n']} · Brier 짝 차이 "
                 f"{_diff(second['Brier 짝 차이(v1.4 − v1.3)'])} · AUC 짝 차이 "
                 f"{_diff(second['AUC 짝 차이(v1.4 − v1.3)'])} |")
    third = verdict["③"]["근거"]
    lines.append("| ③ 쉬운 음성 섞은 전체 AUC | " + ("통과" if verdict["③"]["통과"] else "미달")
                 + f" | 짝 차이 {_diff(third['심결+cross+db AUC 짝 차이(v1.4 − v1.3)'])} |")
    fourth = verdict["④"]["근거"]
    lines.append("| ④ 단조성 | " + ("통과" if verdict["④"]["통과"] else "미달")
                 + f" | 위반 {fourth['위반_합계']} · 런타임 결합 검증 위반 "
                 f"{len(fourth['런타임_결합_검증_위반'])} |")
    stability = adoption["안정성"]
    lines += ["", f"- 적합: KKT 잔차 {stability['최종_적합_KKT_잔차']:.1e}, 교차검증 수렴 실패 "
              f"{stability['교차검증_수렴_실패']}/{stability['교차검증_겹']}, 부트스트랩 수렴 실패 "
              f"{stability.get('부트스트랩_수렴_실패')}",
              f"- 모델 파일: {results['모델_파일']} — {results['모델_파일_설명']}",
              f"- 데이터: 심결 {data['심결_행(학습)']}행(이름 있는 {data['이름_있는_행']}·이름 "
              f"없는 {data['이름_없는_행']['n']}; 제외 {data['이름도_이미지도_없어_제외']['n']}) + "
              f"쉬운 음성 {sum(data['쉬운_음성'].values())}, 결합 하한 "
              f"{results['결합_하한(v1.3 JSON)']}",
              "", "## 이름 없는 2벌 — 학습 행·계수", "",
              "| 집합 | n(심결·쉬운 음성) | 유사/비유사 | 가중 유사/비유사 | 자기 패턴 행 |",
              "|---|---|---|---|---|"]
    for block, info in results["집합"].items():
        lines.append(f"| {block} | {info['n']}({info['n_심결']}·{info['n_쉬운_음성']}) | "
                     f"{info['유사']}/{info['비유사']} | {info['가중_유사']}/"
                     f"{info['가중_비유사']} | {info['자기_패턴_행']} |")
    for block, item in results["계수"].items():
        lines += ["", f"### {block}", "", "| 항 | 적합값 | JSON | 부트스트랩 95% |",
                  "|---|---|---|---|"]
        boot = item["부트스트랩"] or {}
        for name, value in item["적합값"].items():
            ci = (boot.get(name) or {}).get("ci95")
            lines.append(f"| {name} | {_f(value, 4)} | {item['JSON'][name]} | "
                         + (f"{ci[0]} ~ {ci[1]}" if ci and ci[0] is not None else "—") + " |")
        slope = boot.get("도형계 기울기(x2_whole + ×도형계)")
        if slope:
            lines.append(f"| 도형계 기울기(x2_whole + ×도형계) | — | — | {slope['ci95'][0]} ~ "
                         f"{slope['ci95'][1]} (평균 {slope['평균']}) |")
    active = results["제약"]
    lines += ["", f"경계에 붙은 제약: {active['경계_수']}/{active['제약_수']} — {active['종류별']}"]
    for item in active["목록"]:
        lines.append(f"- {item['종류']}: {item['제약']}")
    table = results["평가_2_OOF"]
    lines += ["", "## 평가 2 — OOF 지표(사건 가중, 괄호 95% CI; 짝 차이는 v1.4 − v1.3)", "",
              "| 부분 | n(유사/비유사) | v1.3 그대로 AUC | v1.4 AUC | 짝 차이 AUC | Brier v1.3 → "
              "v1.4 | 짝 차이 Brier |", "|---|---|---|---|---|---|---|"]
    for name, entry in table.items():
        old, new = entry[OLD], entry[NEW]
        lines.append(
            f"| {name} | {old['n']}({old['유사']}/{old['비유사']}) | {_f(old['auc_가중'])}"
            f"{_ci(old.get('auc_가중_ci95'))} | {_f(new['auc_가중'])}"
            f"{_ci(new.get('auc_가중_ci95'))} | {_diff(entry.get('짝_차이_auc'))} | "
            f"{_f(old['brier_가중'])} → {_f(new['brier_가중'])} | "
            f"{_diff(entry.get('짝_차이_brier'))} |")
    lines += ["", "비가중 AUC(참고, v1.3 그대로 / v1.4): " + "; ".join(
        f"{name} {_f(entry[OLD]['auc'])}/{_f(entry[NEW]['auc'])}"
        for name, entry in table.items()),
        "", f"쉬운 음성 쌍의 평균 p: {results['쉬운_음성_평균_p']}"]
    grades = results["등급(v1.3 하한 그대로)"]
    lines += ["", f"## 등급별 건수·정밀도(사건 가중, 하한 {grades['하한']})"]
    for name, sets in grades["표"].items():
        lines += ["", f"### {name}", "", "| 모델 | " + " | ".join(rm.GRADES) + " |",
                  "|---|" + "---|" * len(rm.GRADES)]
        for label, rows_ in sets.items():
            lines.append(f"| {label} | " + " | ".join(
                f"{row['n']}(유사 {row['유사']}) · {_f(row['정밀도_가중'])}"
                for row in rows_) + " |")
    lines += ["", "칸: n(유사 수) · 가중 정밀도.",
              "", "## 평가 6 — 이미지만 입력의 위험도와, 거기에 같은 이름을 더했을 때", "",
              "| 유형 | 이미지 | 상품 | v1.3 | v1.4 | + 같은 이름(요부 있음) | + 같은 이름(요부 "
              "없음) |",
              "|---|---|---|---|---|---|---|"]
    for row in results["평가_6_이미지만_같은_이름"]:
        cells = " | ".join(f"{row[key]['p']}({row[key]['등급']})" for key in (
            "v1.3", "v1.4", "같은_이름(요부 있음)", "같은_이름(요부 없음)"))
        goods = "—" if row["x4"] is None else row["x4"]
        lines.append(f"| {row['유형']} | {row['x2_whole']} | {goods} | {cells} |")
    monotone = results["단조성(행)"]
    lines += ["", "## 단조성(행 단위, 반올림한 모델)", "",
              "| 결합 | 하한 이상 n / 위반 / 로짓차 최소 | 하한 미만 n / 내려간 행 |",
              "|---|---|---|"]
    for group in ("축_결합", "같은_이름"):
        for label, item in monotone[group].items():
            lines.append(f"| {label} | {item['하한_이상_n']} / {item['위반']} / "
                         f"{item['로짓차_최소']} | {item['하한_미만_n']} / "
                         f"{item['하한_미만_내려간_수']} |")
    extra = results.get("참고_이미지만_질의_가정(판정 뒤 추가)") or {}
    if extra.get("n"):
        lines += ["", "## 참고 — 이미지만 질의를 가정한 집합(채택 기준 아님, 판정 뒤 추가)", "",
                  f"이름 없는 심결 행 {extra['이름_없는_심결_행']} + 이름을 가린 쉬운 음성 이미지 "
                  f"쌍 {extra['쉬운_음성(이름 가림)']}(무관한 상표) = {extra['n']}쌍(유사 "
                  f"{extra['유사']}), 모두 도형계 입력으로.", "",
                  "| 모델 | 가중 AUC | 가중 Brier | " + " | ".join(rm.GRADES) + " |",
                  "|---|---|---|" + "---|" * len(rm.GRADES)]
        for label in (OLD, NEW):
            block = extra[label]
            lines.append(
                f"| {label} | {_f(block['auc_가중'])}{_ci(block.get('auc_가중_ci95'))} | "
                f"{_f(block['brier_가중'])} | " + " | ".join(
                    f"{row['n']}(유사 {row['유사']}) · {_f(row['정밀도_가중'])}"
                    for row in extra["등급"][label]) + " |")
        lines += ["", f"- 짝 차이(v1.4 − v1.3): AUC {_diff(extra.get('짝_차이_auc'))}, Brier "
                  f"{_diff(extra.get('짝_차이_brier'))}",
                  "- 무관한 상표(이름을 가린 쉬운 음성)의 등급: "
                  f"{extra['쉬운_음성(이름 가림)_등급']}",
                  f"- 등급 하한에 닿는 이미지 유사도: {extra['등급_하한에_닿는_이미지_유사도']}"]
    thresholds = results.get("등급_하한(이름 없는 입력)")
    if thresholds:
        lines += ["",
                  "## 이름 없는 입력의 등급 하한(채택 뒤에 붙임 — 위 표의 등급은 v1.3 하한 기준)",
                  "", f"- 새 하한: {thresholds['새_하한']}",
                  f"- 해당하는 이미지 유사도(도형계): "
                  f"{thresholds['새_하한에_해당하는_이미지_유사도(도형계)']}",
                  "- 규칙·무관한 쌍의 등급 분포·전후 표: "
                  "`ml/scripts/nameless_grade_thresholds.py`(설계 §7-4-3)"]
    if "평가_8_민감도" in results:
        lines += ["", "## 평가 8 — 민감도(이름 없는 2벌을 조건을 바꿔 다시 학습)", "",
                  "| 조건 | 심결 행(이름 없는·제외) | 이름 없는 행 AUC v1.3 → v1.4 [짝 차이] | "
                  "이름 없는 행 Brier [짝 차이] | 도형계 AUC | 섞음 AUC [짝 차이] | 절편 · "
                  "x2_whole · ×도형계 · 도형계 기울기 |", "|---|---|---|---|---|---|---|"]
        for row in results["평가_8_민감도"]:
            m, c = row["지표"], row["계수"]
            nameless, mixed, figure = m["이름 없는 행"], m["심결+cross+db"], m.get("도형계", {})
            lines.append(
                f"| {row['조건']} | {row['심결_행']}({row['이름_없는_행']}·{row['제외']}) | "
                f"{_f(nameless['auc_가중_v1.3'])} → {_f(nameless['auc_가중'])} "
                f"[{_diff(nameless['짝_차이_auc'])}] | {_f(nameless['brier_가중_v1.3'])} → "
                f"{_f(nameless['brier_가중'])} [{_diff(nameless['짝_차이_brier'])}] | "
                f"{_f(figure.get('auc_가중_v1.3'))} → {_f(figure.get('auc_가중'))} | "
                f"{_f(mixed['auc_가중_v1.3'])} → {_f(mixed['auc_가중'])} "
                f"[{_diff(mixed['짝_차이_auc'])}] | {c['절편']} · {c['x2_whole']} · "
                f"{c['x2_whole×도형계']} · {c['도형계 기울기']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--features", type=Path, default=tr.DEFAULT_FEATURES)
    parser.add_argument("--easy", type=Path, default=tr.DEFAULT_EASY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL,
                        help="채택 기준을 모두 채우면 쓰는 계수 JSON 경로(서비스 기본 모델 경로가 "
                             "아니다)")
    parser.add_argument("--v13", type=Path, default=DEFAULT_V13,
                        help="이름 있는 4벌을 복사해 올 v1.3 JSON")
    parser.add_argument("--folds", type=int, default=t4.FOLDS)
    parser.add_argument("--repeats", type=int, default=t4.REPEATS)
    parser.add_argument("--bootstrap", type=int, default=t4.BOOTSTRAP, help="계수 재적합")
    parser.add_argument("--metric-bootstrap", type=int, default=t4.METRIC_BOOTSTRAP,
                        help="지표 CI·짝 차이(묶음 복원추출)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--random-inputs", type=int, default=RANDOM_INPUTS)
    parser.add_argument("--no-sensitivity", action="store_true")
    args = parser.parse_args(argv)
    results = run(args.features, args.easy, out_dir=args.out_dir, model_path=args.model,
                  v13_path=args.v13, folds=args.folds, repeats=args.repeats,
                  bootstrap=args.bootstrap, metric_bootstrap=args.metric_bootstrap,
                  seed=args.seed, n_random=args.random_inputs,
                  sensitivity=not args.no_sensitivity)
    print(report_text(results))
    return 0 if results["채택"]["채택"] else 3


if __name__ == "__main__":
    sys.exit(main())
