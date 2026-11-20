"""이름 없는 입력(이미지만 / 이미지+상품)의 등급 하한 — 계수는 다시 학습하지 않고, 채택된 v1.4 JSON
(`shared/model/risk_model_v1.4.json`)의 이름 없는 계수 집합에 `grade_thresholds` 만 더한다(통합 모델
설계 §7-4-3). KIPRIS 호출 0. 서비스가 쓰는 모델 파일(v1.3)은 건드리지 않는다.

    ml/venv/bin/python ml/scripts/nameless_grade_thresholds.py            # JSON 갱신 + 보고
    ml/venv/bin/python ml/scripts/nameless_grade_thresholds.py --dry-run  # 계산·보고만

왜: v1.4(2차 시도)는 등급 하한을 이름 있는 입력용 v1.3 값 그대로 복사했다. 이름 없는 집합의 위험도는
학습 행(다툼이 있던 쌍이 많다)의 유사 비율에 맞춰져 있어, 이름을 가린 무관한 로고 쌍의 97% 가 "검토
권장"이 됐다(§7-4-2 참고 진단). 등급의 뜻을 입력 종류와 상관없이 같게 한다.

규칙(RULE — 계산 전에 고정, 한 번만 계산):
  - 등급의 뜻 = "무관한 상표 쌍이 그 등급 이상을 받는 비율". 이것을 이름 있는 입력과 맞춘다.
  - 기준 집합 U: 이미지가 있는 쉬운 음성 쌍(사진 규칙 뒤). 이미지+상품용은 상품도 관측된 쌍.
  - 같은 쌍을 ① 이름 있는 입력으로 v1.3 채점(같은 축만 — 이미지만용은 상품을 가린다; 등급은
    risk_score 가 내는 최종 등급) ② 이름을 가린 도형계 입력으로 이름 없는 집합(배포 계수)으로 채점.
    ①에서 그 등급 이상인 쌍 수 k 를 세고, ②의 위험도 가운데 k 번째로 큰 값(소수 넷째 자리 내림)을
    이름 없는 입력의 그 등급 하한으로 한다 — 주의·검토 권장. 이미지만 / 이미지+상품 각각.
  - 위험 하한 = max(기존 위험 하한, 같은 방식으로 맞춘 값).
  - 비율이 0 이거나 하한이 표본 최댓값(U 에서 ②의 위험도 최댓값)을 넘으면 그 등급은 그 입력 종류에서
    "단독 규칙으로만 도달"(하한 null)로 두고 그대로 보고한다. 다른 규칙은 시도하지 않는다.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from src.model import risk_model as rm  # noqa: E402

from scripts import train_risk_model as tr  # noqa: E402
from scripts import train_risk_model_v14 as t4  # noqa: E402  (데이터 적재·가중 지표 도우미)

DEFAULT_MODEL = rm.REPO_ROOT / "shared" / "model" / "risk_model_v1.4.json"
DEFAULT_V13 = rm.V13_MODEL_PATH
DEFAULT_OUT_DIR = t4.DEFAULT_OUT_DIR
REPORT_STEM = "risk_model_v1.4_thresholds"
KINDS = (("이미지만", "x2_whole"), ("이미지+상품", "x2_whole+x4"))  # (표시 이름, 이름 없는 패턴 키)
RISK_GRADE = rm.GRADES[-1]
UNREACHABLE = "단독 규칙으로만 도달"
DIGITS = 4
PREFIX = rm.NAMELESS_PREFIX
# 규칙(계산 전에 고정) ---------------------------------------------------------------------------
RULE = {
    "뜻": "등급의 뜻 = 무관한 상표 쌍이 그 등급 이상을 받는 비율 — 이름 있는 입력과 맞춘다",
    "기준_집합": ("U = 이미지가 있는 쉬운 음성 쌍(cross·db, 사진 규칙 뒤). 이미지+상품용은 상품도 "
                  "관측된 쌍"),
    "이름_있는_채점": ("v1.3(= v1.4 의 이름 있는 쪽)으로 같은 축만(이미지만용은 상품을 가린다), "
                     "행의 유형(쉬운 음성은 문자), 등급은 risk_score 의 최종 등급(단독 규칙 포함)"),
    "이름_없는_채점": "이름을 가린 도형계 입력을 v1.4 의 이름 없는 집합(배포 계수)으로",
    "하한": ("U 에서 이름 있는 등급이 그 등급 이상인 쌍 수 k → 이름 없는 위험도의 k 번째로 큰 값"
             f"(소수 {DIGITS}자리 내림). 주의·검토 권장"),
    "위험": "max(기존 위험 하한, 같은 방식으로 맞춘 값)",
    "예외": ("비율이 0 이거나 하한이 표본 최댓값(U 의 이름 없는 위험도 최댓값)을 넘으면 그 등급은 "
             f"그 입력 종류에서 '{UNREACHABLE}'(하한 null). 다른 규칙은 시도하지 않는다"),
}


def _round(value, digits: int = DIGITS):
    return None if value is None else round(float(value), digits)


def _floor(value: float, digits: int = DIGITS) -> float:
    scale = 10 ** digits
    return math.floor(float(value) * scale + 1e-9) / scale


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _logit(value: float) -> float:
    return math.log(value / (1.0 - value))


# ---- 기준 집합·입력 -----------------------------------------------------------------------------

def reference_rows(rows: list[dict], key: str) -> list[dict]:
    """기준 집합 U — 쉬운 음성(cross·db) 가운데 그 패턴의 축(이미지[·상품])이 관측된 쌍. rows 는
    t4.load_dataset 의 행(사진 규칙이 적용돼 사진 쌍의 이미지 축은 결측)."""
    present = rm.pattern_present(key)
    return [row for row in rows if row["pair_source"] != "trial"
            and all(not np.isnan(row[axis]) for axis in present)]


def named_input(row: dict, key: str) -> dict:
    """그 쌍의 이름 있는 입력 — 이름 없는 입력과 같은 축만(패턴에 없는 축은 가린다)."""
    features = t4.service_features(row)
    present = rm.pattern_present(key)
    for axis in tr.PATTERN_AXES:
        if axis not in present:
            features[axis] = None
    return features


def nameless_input(row: dict, key: str) -> dict:
    """그 쌍의 이름을 가린 도형계 입력(이미지만 / 이미지+상품)."""
    features = t4.service_features(row)
    present = rm.pattern_present(key)
    return {"x1_d": None, "x2_text_d": None, "x3_d": None, "has_meaning_both": False,
            "has_distinctive_part_a": True, "has_distinctive_part_b": True, "mark_type": "도형",
            **{axis: (features[axis] if axis in present else None) for axis in tr.PATTERN_AXES}}


def without_thresholds(model: dict) -> dict:
    """이름 없는 집합의 자기 등급 하한을 뗀 사본 — 하한을 정하기 전(최상위 하한을 쓰는) 모델."""
    out = copy.deepcopy(model)
    for block in (out.get(rm.NAMELESS_KEY) or {}).values():
        block.pop("grade_thresholds", None)
    return out


# ---- 하한 계산 ----------------------------------------------------------------------------------

def calibrate_kind(rows: list[dict], key: str, model_named: dict, model: dict) -> dict:
    """입력 종류 하나의 하한. model 은 이름 없는 집합을 가진 v1.4(자기 하한은 쓰지 않는다 —
    위험도만), model_named 는 이름 있는 채점에 쓰는 v1.3."""
    reference = reference_rows(rows, key)
    block_id = PREFIX + key
    named_grades, probs = [], []
    for row in reference:
        named = rm.risk_score(named_input(row, key), model_named)
        nameless = rm.risk_score(nameless_input(row, key), model)
        if named.pattern != key or nameless.pattern != block_id:
            raise ValueError(f"기준 집합의 패턴이 어긋납니다: {named.pattern}·{nameless.pattern}")
        named_grades.append(rm.GRADES.index(named.grade))
        probs.append(nameless.prob)
    n = len(reference)
    values = np.sort(np.asarray(probs, dtype=np.float64))[::-1]
    grades = np.asarray(named_grades, dtype=int)
    maximum = float(values[0]) if n else None
    existing_risk = float(model_named["grade_thresholds"][RISK_GRADE])
    table = {}
    for level, grade in enumerate(rm.GRADE_THRESHOLD_KEYS, start=1):
        count = int((grades >= level).sum()) if n else 0
        entry = {"이름_있는_입력에서_그_등급_이상": count, "비율": _round(count / n) if n else None,
                 "맞춘_값": None, "하한": None, "사유": None, "새_하한에서_그_등급_이상": 0}
        if count == 0:
            entry["사유"] = f"비율 0 — {UNREACHABLE}"
        else:
            matched = _floor(values[count - 1])
            threshold = matched
            reason = "U 에서 비율을 맞춤"
            if grade == RISK_GRADE and existing_risk > matched:
                threshold = existing_risk
                reason = f"기존 위험 하한 {existing_risk} 유지(맞춘 값 {matched} 보다 높다)"
            entry["맞춘_값"] = matched
            if threshold > maximum:
                entry["사유"] = (f"하한 {threshold} 이 표본 최댓값 {_round(maximum)} 을 넘음 — "
                               f"{UNREACHABLE}")
            else:
                entry.update({"하한": threshold, "사유": reason,
                              "새_하한에서_그_등급_이상": int((values >= threshold).sum())})
        table[grade] = entry
    return {"패턴": block_id, "n": n,
            "쌍_출처": {source: sum(1 for row in reference if row["pair_source"] == source)
                     for source in ("cross", "db")},
            "이름_없는_위험도": {"최댓값": _round(maximum),
                           "최솟값": _round(values[-1]) if n else None,
                           "평균": _round(values.mean()) if n else None},
            "등급": table}


def calibrate(rows: list[dict], model_named: dict, model: dict) -> dict:
    """입력 종류마다 하한을 계산한다(RULE). model 의 이름 없는 집합에 없는 종류는 건너뛴다."""
    base = without_thresholds(model)
    kinds = {label: calibrate_kind(rows, key, model_named, base)
             for label, key in KINDS if key in (model.get(rm.NAMELESS_KEY) or {})}
    return {"규칙": RULE, "기존_하한(이름 있는 입력)": dict(model_named["grade_thresholds"]),
            "종류": kinds}


def thresholds_from(calibration: dict) -> dict[str, dict]:
    """계산 결과 → {이름 없는 패턴 키: {등급: 하한 또는 None}}."""
    return {item["패턴"][len(PREFIX):]: {grade: entry["하한"]
                                        for grade, entry in item["등급"].items()}
            for item in calibration["종류"].values()}


def _grade_meta(entry: dict) -> dict:
    return {"named_at_or_above": entry["이름_있는_입력에서_그_등급_이상"], "share": entry["비율"],
            "matched": entry["맞춘_값"], "threshold": entry["하한"], "reason": entry["사유"],
            "nameless_at_or_above": entry["새_하한에서_그_등급_이상"]}


def apply_thresholds(model: dict, calibration: dict) -> dict:
    """이름 없는 집합에 `grade_thresholds` 를, `meta.nameless.grade_thresholds` 에 계산 근거를 적은
    사본. 계수·이름 있는 쪽은 건드리지 않는다."""
    out = copy.deepcopy(model)
    for key, thresholds in thresholds_from(calibration).items():
        out[rm.NAMELESS_KEY][key]["grade_thresholds"] = thresholds
    meta = out.setdefault("meta", {}).setdefault("nameless", {})
    meta["grade_thresholds"] = {
        "calibrated_at": date.today().isoformat(),
        "rule": RULE,
        "kinds": {label: {"pattern": item["패턴"], "n": item["n"], "pairs": item["쌍_출처"],
                          "nameless_prob": item["이름_없는_위험도"],
                          "grades": {grade: _grade_meta(entry)
                                     for grade, entry in item["등급"].items()}}
                  for label, item in calibration["종류"].items()},
        "note": ("null = 그 등급은 그 입력 종류에서 위험도로는 닿지 않는다(단독 규칙으로만). 이름 "
                 "있는 입력은 최상위 grade_thresholds 그대로"),
    }
    rm.validate_model(out)
    return out


# ---- 보고(판정 기준이 아니다) --------------------------------------------------------------------

def similarity_equivalents(model: dict) -> dict:
    """새 하한에 해당하는 이미지 유사도(도형계) — 이미지만 집합은 상품 없음, 이미지+상품 집합은 상품
    겹침 1.0 과 0.0. 0~1 밖이면 그 상품 값에서는 이미지로 닿지 않거나(> 1) 언제나 넘는다(< 0)."""
    out = {}
    for label, key in KINDS:
        block = (model.get(rm.NAMELESS_KEY) or {}).get(key)
        if not block or not block.get("grade_thresholds"):
            continue
        coefficients = block["coefficients"]
        slope = float(coefficients["x2_whole"]) + float(coefficients.get("x2_whole×도형계", 0.0))
        goods = float(coefficients.get("x4", 0.0))
        cases = {"상품 없음": 0.0} if "x4" not in coefficients else {"상품 겹침 1.0": goods,
                                                                     "상품 겹침 0.0": 0.0}
        out[label] = {
            grade: {"하한": threshold,
                    **{case: (_round((_logit(threshold) - float(block["intercept"]) - shift)
                                     / slope, 3) if threshold is not None and slope > 0 else None)
                       for case, shift in cases.items()}}
            for grade, threshold in block["grade_thresholds"].items()}
    return out


def _grade_counts(grades: list[str]) -> dict:
    return {grade: grades.count(grade) for grade in rm.GRADES}


def unrelated_distribution(rows: list[dict], model_named: dict, before: dict, after: dict) -> dict:
    """무관한 쌍(U)의 등급 분포 — 이름 있는 입력(v1.3) 대 이름 없는 입력(하한을 정하기 전·뒤)."""
    out = {}
    for label, key in KINDS:
        if key not in (after.get(rm.NAMELESS_KEY) or {}):
            continue
        reference = reference_rows(rows, key)
        out[label] = {
            "n": len(reference),
            "이름 있는 입력(v1.3)": _grade_counts(
                [rm.risk_score(named_input(row, key), model_named).grade for row in reference]),
            "이름 없는 입력(전 — v1.3 하한)": _grade_counts(
                [rm.risk_score(nameless_input(row, key), before).grade for row in reference]),
            "이름 없는 입력(새 하한)": _grade_counts(
                [rm.risk_score(nameless_input(row, key), after).grade for row in reference]),
        }
    return out


def row_grades(prob: np.ndarray, own: np.ndarray, model: dict) -> np.ndarray:
    """행별 등급(위험도 하한만 — 단독 규칙 없이, 2차 시도 보고의 표와 같은 방식). 행마다 자기 계수
    집합의 하한을 쓴다."""
    return np.asarray([rm.grade_for(float(p), rm.grade_thresholds_for(model, str(pattern)))
                       for p, pattern in zip(prob, own)])


def nameless_tables(rows: list[dict], a: dict, own: np.ndarray, prob: np.ndarray, before: dict,
                    after: dict) -> dict:
    """이름 없는 행·도형계·쉬운 음성을 섞은 전체의 등급별 건수·가중 정밀도 전후(위험도는 2차 시도와
    같은 OOF), 이름 없는 유사 쌍 가운데 검토 권장 이상으로 남는 수, 도형 단독 규칙이 올리는 행
    수."""
    masks = t4.subset_masks(rows)
    y, weight = a["y"], a["eval_weight"]
    grades = {"전(v1.3 하한)": row_grades(prob, own, before),
              "후(새 하한)": row_grades(prob, own, after)}
    out = {"표": {}}
    for name in ("이름 없는 행", "도형계", "심결+cross+db"):
        mask = masks[name]
        out["표"][name] = {label: t4.grade_table(prob[mask], y[mask], weight[mask], {},
                                                 grades=values[mask])
                          for label, values in grades.items()}
    nameless = masks["이름 없는 행"]
    similar = nameless & (y == 1)
    review = rm.GRADES.index(rm.REVIEW_GRADE)
    out["이름_없는_유사_쌍"] = {
        "n": int(similar.sum()),
        **{label: int(sum(rm.GRADES.index(g) >= review for g in values[similar]))
           for label, values in grades.items()}}
    out["이름_없는_비유사_쌍"] = {
        "n": int((nameless & (y == 0)).sum()),
        **{label: int(sum(rm.GRADES.index(g) >= review for g in values[nameless & (y == 0)]))
           for label, values in grades.items()}}
    rule = after.get("figure_rule") or {}
    tau = rule.get("threshold")
    lifted = 0
    if tau is not None:
        for index in np.flatnonzero(nameless):
            row = rows[index]
            figure = rm.mark_type_level(row.get("상표유형", "")) in rm.FIGURE_FAMILY
            below = rm.GRADES.index(grades["후(새 하한)"][index]) < review
            lifted += int(figure and below and not np.isnan(row["x2_whole"])
                          and row["x2_whole"] >= float(tau))
    out["도형_단독_규칙이_올리는_이름_없는_행"] = lifted
    return out


def evaluate(rows: list[dict], model_named: dict, before: dict, after: dict, calibration: dict,
             prob: np.ndarray | None = None, own: np.ndarray | None = None,
             a: dict | None = None) -> dict:
    results = {
        "기준일": date.today().isoformat(), "규칙": RULE,
        "기존_하한(이름 있는 입력)": dict(model_named["grade_thresholds"]),
        "계산": calibration["종류"], "새_하한": thresholds_from(calibration),
        "새_하한에_해당하는_이미지_유사도(도형계)": similarity_equivalents(after),
        "무관한_쌍의_등급_분포": unrelated_distribution(rows, model_named, before, after),
    }
    if prob is not None and own is not None and a is not None:
        results["이름_없는_행_전후"] = nameless_tables(rows, a, own, prob, before, after)
    return results


def run(features_path: Path, easy_path: Path, *, model_path: Path = DEFAULT_MODEL,
        v13_path: Path = DEFAULT_V13, out_dir: Path = DEFAULT_OUT_DIR, write: bool = True,
        folds: int = t4.FOLDS, repeats: int = t4.REPEATS, seed: int = 0,
        min_pattern_minority: int = tr.MIN_PATTERN_MINORITY, force: bool = False) -> dict:
    """채택된 v1.4 JSON 을 읽어 하한을 계산하고(계수는 그대로) JSON 과 보고를 쓴다. 이름 없는 행의
    전후 표에는 2차 시도와 같은 OOF 위험도를 쓴다(겹 적합은 표를 위한 것이고 JSON 의 계수와
    무관)."""
    from scripts import train_risk_model_v14_nameless as t4n  # 순환 import 를 피해 여기서

    if write:  # 실제 검색 기준 하한(§7-4-4)이 있으면 --force 없이는 계산 전에 멈춘다
        rm.check_nameless_overwrite(model_path, force=force)
    model_named = rm.validate_model(json.loads(Path(v13_path).read_text(encoding="utf-8")))
    stored = rm.validate_model(json.loads(Path(model_path).read_text(encoding="utf-8")))
    before = without_thresholds(stored)
    rows = t4.load_dataset(features_path, easy_path).rows
    calibration = calibrate(rows, model_named, before)
    after = apply_thresholds(before, calibration)
    trained = t4n.train_once(rows, model_named, folds=folds, repeats=repeats, seed=seed,
                             min_minority=min_pattern_minority)
    results = evaluate(rows, model_named, before, after, calibration, trained["prob_new"],
                       trained["design"].own, trained["arrays"])
    results["모델_파일"] = str(model_path)
    results["계수_불변"] = all(
        after[rm.NAMELESS_KEY][key][field] == before[rm.NAMELESS_KEY][key][field]
        for key in before[rm.NAMELESS_KEY] for field in ("features", "coefficients", "intercept")
    ) and after["patterns"] == before["patterns"]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if write:
        Path(model_path).write_text(json.dumps(after, ensure_ascii=False, indent=1) + "\n",
                                    encoding="utf-8")
    results["JSON_갱신"] = bool(write)
    (out_dir / f"{REPORT_STEM}_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / f"{REPORT_STEM}_report.md").write_text(report_text(results), encoding="utf-8")
    return results


# ---- 보고서 ------------------------------------------------------------------------------------

def _cell(value) -> str:
    return "—" if value is None else f"{value}"


def report_text(results: dict) -> str:
    lines = [f"# 이름 없는 입력의 등급 하한 ({results['기준일']})", "",
             "계수는 다시 학습하지 않았다. 규칙(계산 전에 고정):", ""]
    lines += [f"- {key}: {value}" for key, value in results["규칙"].items()]
    lines += ["", f"기존 하한(이름 있는 입력 — 그대로): {results['기존_하한(이름 있는 입력)']}", "",
              "## 새 하한", "",
              "| 입력 종류 | U | 등급 | 이름 있는 입력에서 그 등급 이상(비율) | 맞춘 값 | 하한 | "
              "새 하한에서 그 등급 이상 | 사유 |", "|---|---|---|---|---|---|---|---|"]
    for label, item in results["계산"].items():
        for grade, entry in item["등급"].items():
            threshold = UNREACHABLE if entry["하한"] is None else entry["하한"]
            lines.append(
                f"| {label} | {item['n']} | {grade} | {entry['이름_있는_입력에서_그_등급_이상']}"
                f"({_cell(entry['비율'])}) | {_cell(entry['맞춘_값'])} | {threshold} | "
                f"{entry['새_하한에서_그_등급_이상']} | {entry['사유']} |")
    lines += ["", "U 의 이름 없는 위험도: " + "; ".join(
        f"{label} {item['이름_없는_위험도']}" for label, item in results["계산"].items()),
        "", "## 새 하한에 해당하는 이미지 유사도(도형계)", ""]
    for label, grades in results["새_하한에_해당하는_이미지_유사도(도형계)"].items():
        for grade, entry in grades.items():
            cases = "; ".join(f"{case} {_cell(value)}" for case, value in entry.items()
                              if case != "하한")
            lines.append(f"- {label} · {grade}: 하한 {_cell(entry['하한'])} → {cases}")
    lines += ["", "## 무관한 쌍(U)의 등급 분포", "",
              "| 입력 종류 | 채점 | " + " | ".join(rm.GRADES) + " |",
              "|---|---|" + "---|" * len(rm.GRADES)]
    for label, item in results["무관한_쌍의_등급_분포"].items():
        for scoring, counts in item.items():
            if scoring == "n":
                continue
            lines.append(f"| {label}({item['n']}) | {scoring} | "
                         + " | ".join(str(counts[grade]) for grade in rm.GRADES) + " |")
    tables = results.get("이름_없는_행_전후")
    if tables:
        lines += ["", "## 등급별 건수·가중 정밀도 전후(위험도는 2차 시도와 같은 OOF)", "",
                  "| 집합 | 하한 | " + " | ".join(rm.GRADES) + " |",
                  "|---|---|" + "---|" * len(rm.GRADES)]
        for name, sets in tables["표"].items():
            for label, rows_ in sets.items():
                lines.append(f"| {name} | {label} | " + " | ".join(
                    f"{row['n']}(유사 {row['유사']}) · {_cell(row['정밀도_가중'])}"
                    for row in rows_) + " |")
        similar, different = tables["이름_없는_유사_쌍"], tables["이름_없는_비유사_쌍"]
        lines += ["", "칸: n(유사 수) · 가중 정밀도.",
                  f"- 이름 없는 유사 {similar['n']}쌍 중 검토 권장 이상: 전 "
                  f"{similar['전(v1.3 하한)']} → 후 {similar['후(새 하한)']}",
                  f"- 이름 없는 비유사 {different['n']}쌍 중 검토 권장 이상: 전 "
                  f"{different['전(v1.3 하한)']} → 후 {different['후(새 하한)']}",
                  f"- 도형 단독 규칙(τ)이 검토 권장으로 올리는 이름 없는 행: "
                  f"{tables['도형_단독_규칙이_올리는_이름_없는_행']}"]
    lines += ["", f"모델 파일: {results.get('모델_파일')} — JSON 갱신 {results.get('JSON_갱신')}, "
              f"계수 불변 {results.get('계수_불변')}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--features", type=Path, default=tr.DEFAULT_FEATURES)
    parser.add_argument("--easy", type=Path, default=tr.DEFAULT_EASY)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL,
                        help="하한을 더할 v1.4 JSON(계수는 그대로 둔다)")
    parser.add_argument("--v13", type=Path, default=DEFAULT_V13, help="이름 있는 채점에 쓰는 v1.3")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--dry-run", action="store_true", help="JSON 을 쓰지 않는다")
    parser.add_argument("--force", action="store_true",
                        help="실제 검색 기준 하한(§7-4-4)이 있는 JSON 도 덮어쓴다")
    args = parser.parse_args(argv)
    try:
        results = run(args.features, args.easy, model_path=args.model, v13_path=args.v13,
                      out_dir=args.out_dir, write=not args.dry_run, force=args.force)
    except rm.OverwriteRefused as exc:
        print(f"쓰지 않음: {exc}", file=sys.stderr)
        return 4
    print(report_text(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
