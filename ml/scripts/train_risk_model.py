"""통합 모델 1차 학습 — 심결례 정답 데이터(`pairs_features.csv`)로 로지스틱 회귀(판례 구조: 유형
교호작용)를 학습하고, 계수가 판례 원칙과 맞는지 검증하고, 등급 임계값을 정한다(통합 모델 설계
§3·§4-3·§7).
KIPRIS 호출 0, 서비스 코드 미접촉. 산출물은 계수 JSON(`shared/model/risk_model_v1.json`)·보고서
(`ml/data/trials/risk_model_v1_report.md`·`_results.json`)·신뢰도 곡선 PNG.

    ml/venv/bin/python ml/scripts/train_risk_model.py          # 기본 격자(C 4 × w_easy 3 × 변형 2)
    ml/venv/bin/python ml/scripts/train_risk_model.py --bootstrap 100 --repeats 1   # 빠른 확인

입력(§4-3 표): x1_d·x2_text_d·x2_whole·x3_d·x4(결측 0 + 결측 지시변수), has_distinctive_part_a/b,
상표 유형 지시변수(기준 문자; 도형·결합-문자요부·결합-도형요부), 변형 B 는 교호작용 x1_d×문자계·
x2_whole×도형계. 연속 입력은 0~1 그대로(표준화 없음). has_meaning_both 는 miss_x3 의 보수(같은
정보)라 별도 열로 넣지 않고, x3_d×has_meaning_both 는 x3_d 와 같은 열이라 넣지 않는다(보고서 명시).

목적함수는 sklearn LogisticRegression(L2, lbfgs)과 같은 ½‖w‖² + C·Σ s_i·logloss_i(절편 비벌점)를
scipy L-BFGS 로 푼다 — 쉬운 음성(이미지 없음)을 가중치 w_easy 로 섞을 때 이미지 블록(x2_whole·
miss_x2img·교호작용)의 계수는 심결 행만으로 적합한 값에 고정(오프셋)해야 "이미지 없음 = 쉬운 음성"
이라는 거짓 상관을 배우지 않기 때문이다. w_easy = 0 이면 sklearn 과 같은 해(테스트로 확인).
교차검증은 사건(심판번호) 단위 StratifiedGroupKFold 5겹 × 반복 3, C 는 심결 OOF AUC 로 고른다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from scipy.optimize import minimize  # noqa: E402
from scipy.special import expit  # noqa: E402
from src.model import risk_model as rm  # noqa: E402

# x2_benchmark 가 torch → faiss 순서로 import 한다(ml/src/search.py 주석).
from scripts import axes_benchmark as ab  # noqa: E402
from scripts import x2_benchmark as x2b  # noqa: E402

DEFAULT_BASE = ML_ROOT / "data" / "trials"
DEFAULT_FEATURES = DEFAULT_BASE / "pairs_features.csv"
DEFAULT_EASY = DEFAULT_BASE / "pairs_features_easy.csv"
DEFAULT_OUT_DIR = DEFAULT_BASE
DEFAULT_MODEL = rm.DEFAULT_MODEL_PATH

C_GRID = (0.1, 0.3, 1.0, 3.0)
W_EASY_GRID = (0.0, 0.25, 0.5)
FOLDS = 5
REPEATS = 3
BOOTSTRAP = 500
CALIBRATION_BINS = 10
PRECISION_RISK = 0.8  # "위험" 등급의 최소 정밀도
RECALL_REVIEW = 0.9  # "검토 권장" 이상이 잡아야 하는 유사 재현율
STANDALONE_PRECISION = 0.9  # 단독 임계값: 축 하나의 정밀도 목표
MIN_SUPPORT = 10
ADOPT_AUC_SLACK = 0.01  # 채택 규칙: 심결 AUC 가 최고와 이 안이면 판례 구조·보정 우선
BASE_FEATURES = [
    "x1_d", "x2_text_d", "x2_whole", "x3_d", "x4",
    "miss_x1", "miss_x2text", "miss_x2img", "miss_x3", "miss_x4",
    "has_distinctive_part_a", "has_distinctive_part_b",
    "type_도형", "type_결합-문자요부", "type_결합-도형요부",
]
INTERACTIONS = ["x1_d×문자계", "x2_whole×도형계"]
VARIANTS = {"A": BASE_FEATURES, "B": BASE_FEATURES + INTERACTIONS}
IMAGE_BLOCK = ("x2_whole", "miss_x2img", "x2_whole×도형계")  # 심결 행만으로 적합(오프셋)
AXES = ("x1_d", "x2_text_d", "x2_whole", "x3_d", "x4")
SETS = (("심결", ("trial",)), ("심결+cross", ("trial", "cross")),
        ("심결+cross+db", ("trial", "cross", "db")))
KINDS = ab.KINDS
SOURCES = ("kipris", "llm", "본문", "ocr", "도형", "")


# ---- 데이터 ----------------------------------------------------------------------------------

def load_rows(features_path: Path, easy_path: Path | None) -> list[dict]:
    rows = ab.load_features(features_path)
    for row in rows:
        row["pair_source"] = row.get("pair_source") or "trial"
    if easy_path is not None and Path(easy_path).exists():
        for row in ab.load_features(easy_path):
            row["pair_source"] = row.get("pair_source") or "cross"
            rows.append(row)
    return rows


def row_features(row: dict) -> dict:
    """특징 CSV 행(ab.load_features 뒤) → 런타임 입력 사전(§4-3 규약)."""
    out: dict = {}
    for axis, _miss in rm.AXIS_INPUTS:
        value = row.get(axis, np.nan)
        out[axis] = None if value is None or (isinstance(value, float) and np.isnan(value)) else (
            float(value)
        )
    out["has_meaning_both"] = bool(row.get("has_meaning_a")) and bool(row.get("has_meaning_b"))
    out["has_distinctive_part_a"] = bool(int(row.get("has_distinctive_part_a") or 0))
    out["has_distinctive_part_b"] = bool(int(row.get("has_distinctive_part_b") or 0))
    out["mark_type"] = row.get("상표유형", "")
    return out


def design_matrix(rows: list[dict], names: list[str]) -> np.ndarray:
    return np.asarray([rm.design_vector(row_features(row), names) for row in rows],
                      dtype=np.float64)


def labels(rows: list[dict], kind: str) -> np.ndarray:
    return ab.labels_for(rows, kind)


def groups_for(rows: list[dict]) -> np.ndarray:
    """사건 단위 그룹: 심결 행은 심판번호, cross 행은 이름 A 의 사건, db 행은 자기 키."""
    out = []
    for row in rows:
        key = str(row.get("심판번호", ""))
        if row["pair_source"] == "cross" and ":" in key:
            out.append(key.split(":", 1)[1].split("|", 1)[0])
        else:
            out.append(key)
    return np.asarray(out)


def sample_weights(rows: list[dict], w_easy: float) -> np.ndarray:
    return np.asarray([1.0 if row["pair_source"] == "trial" else w_easy for row in rows])


# ---- 적합 --------------------------------------------------------------------------------------

def fit_logistic(X: np.ndarray, y: np.ndarray, weight: np.ndarray, C: float, *,
                 offset: np.ndarray | None = None) -> tuple[np.ndarray, float]:
    """½‖w‖² + C·Σ s_i·logloss_i (절편 비벌점, sklearn 과 같은 목적함수)를 L-BFGS 로 푼다.
    offset 은 고정된 로짓 기여(이미지 블록)."""
    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    weight = np.asarray(weight, dtype=np.float64)
    offset = np.zeros(X.shape[0]) if offset is None else np.asarray(offset, dtype=np.float64)
    keep = weight > 0
    X, y, weight, offset = X[keep], y[keep], weight[keep], offset[keep]
    d = X.shape[1]

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        w, b = theta[:d], theta[d]
        z = X @ w + b + offset
        loss = np.logaddexp(0.0, z) - y * z
        value = 0.5 * float(w @ w) + C * float(np.sum(weight * loss))
        residual = weight * (expit(z) - y)
        gradient = np.concatenate([w + C * (X.T @ residual), [C * float(residual.sum())]])
        return value, gradient

    result = minimize(objective, np.zeros(d + 1), jac=True, method="L-BFGS-B",
                      options={"maxiter": 1000, "gtol": 1e-9, "ftol": 1e-12})
    return result.x[:d], float(result.x[d])


def fit_model(X: np.ndarray, y: np.ndarray, weight: np.ndarray, names: list[str], C: float,
              easy: np.ndarray) -> tuple[np.ndarray, float]:
    """심결 행만으로 전체 적합(1단계) → 쉬운 음성이 있으면 이미지 블록을 고정하고 나머지를 다시
    적합(2단계). 쉬운 음성 가중치가 0 이면 1단계 해가 그대로다."""
    trial = ~easy
    coef, intercept = fit_logistic(X[trial], y[trial], weight[trial], C)
    if not np.any(easy & (weight > 0)):
        return coef, intercept
    image = np.asarray([name in IMAGE_BLOCK for name in names])
    offset = X[:, image] @ coef[image]
    rest_coef, intercept = fit_logistic(X[:, ~image], y, weight, C, offset=offset)
    full = coef.copy()
    full[~image] = rest_coef
    return full, intercept


def predict(X: np.ndarray, coef: np.ndarray, intercept: float) -> np.ndarray:
    return expit(X @ coef + intercept)


def folds_for(y: np.ndarray, groups: np.ndarray, *, folds: int, seed: int):
    from sklearn.model_selection import StratifiedGroupKFold

    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)
    return list(splitter.split(np.zeros((y.size, 1)), y, groups))


def cv_predictions(X: np.ndarray, y: np.ndarray, weight: np.ndarray, names: list[str],
                   easy: np.ndarray, groups: np.ndarray, C: float, *, folds: int, repeats: int,
                   seed: int) -> np.ndarray:
    """반복 교차검증 OOF 확률(반복 평균)."""
    total = np.zeros(y.size)
    for repeat in range(repeats):
        for train, test in folds_for(y, groups, folds=folds, seed=seed + repeat):
            coef, intercept = fit_model(X[train], y[train], weight[train], names, C, easy[train])
            total[test] += predict(X[test], coef, intercept)
    return total / repeats


# ---- 평가 --------------------------------------------------------------------------------------

def set_masks(rows: list[dict]) -> dict[str, np.ndarray]:
    sources = np.asarray([row["pair_source"] for row in rows])
    return {name: np.isin(sources, members) for name, members in SETS}


def auc_block(prob: np.ndarray, y: np.ndarray, mask: np.ndarray, *, seed: int,
              bootstrap: int) -> dict:
    if not mask.any():
        return {"n": 0, "auc": None, "auc_ci95": [None, None]}
    return ab.evaluate_subset(prob[mask], y[mask], seed=seed, bootstrap=bootstrap)


def baseline_scores(rows: list[dict]) -> dict[str, np.ndarray]:
    """기준선: 1학기 CLIP 단독(x2_whole), 축 최댓값, 축 평균(있는 축만; 전부 결측이면 0)."""
    matrix = np.asarray([[row.get(axis, np.nan) for axis in AXES] for row in rows],
                        dtype=np.float64)
    present = ~np.isnan(matrix)
    filled = np.where(present, matrix, 0.0)
    count = present.sum(axis=1)
    maximum = np.where(count > 0, np.where(present, matrix, -np.inf).max(axis=1), 0.0)
    mean = np.where(count > 0, filled.sum(axis=1) / np.maximum(count, 1), 0.0)
    clip = np.where(present[:, 2], filled[:, 2], 0.0)
    return {"CLIP 단독(x2_whole)": clip, "축 최댓값": maximum, "축 평균": mean}


def calibration(prob: np.ndarray, y: np.ndarray, bins: int = CALIBRATION_BINS) -> dict:
    edges = np.linspace(0.0, 1.0, bins + 1)
    curve = []
    for i in range(bins):
        inside = (prob >= edges[i]) & ((prob < edges[i + 1]) if i < bins - 1 else (prob <= 1.0))
        n = int(inside.sum())
        curve.append({
            "구간": f"{edges[i]:.1f}~{edges[i + 1]:.1f}", "n": n,
            "예측_평균": x2b._round(float(prob[inside].mean())) if n else None,
            "관측_유사율": x2b._round(float(y[inside].mean())) if n else None,
        })
    return {"brier": x2b._round(float(np.mean((prob - y) ** 2))), "곡선": curve}


def grade_thresholds(prob: np.ndarray, y: np.ndarray, *, precision_risk: float = PRECISION_RISK,
                     recall_review: float = RECALL_REVIEW, min_support: int = MIN_SUPPORT) -> dict:
    """위험: 정밀도 ≥ precision_risk 인 최소 p(지지 n ≥ min_support). 검토 권장: 유사 재현율 ≥
    recall_review 인 최대 p. 안전/주의 경계는 [0, 검토 권장) 등분."""
    n_pos = int((y == 1).sum())
    notes = []
    candidates = np.unique(prob)
    risk = None
    for threshold in candidates:
        above = prob >= threshold
        if int(above.sum()) < min_support:
            break
        if float(y[above].mean()) >= precision_risk:
            risk = float(threshold)
            break
    review = None
    for threshold in candidates[::-1]:
        above = prob >= threshold
        if n_pos and float((y[above] == 1).sum() / n_pos) >= recall_review:
            review = float(threshold)
            break
    if risk is None:
        best = max((float(y[prob >= t].mean()) for t in candidates
                    if (prob >= t).sum() >= min_support), default=0.0)
        notes.append(f"정밀도 {precision_risk} 에 이르는 p 가 없음(지지 {min_support} 이상 최대 "
                     f"정밀도 {best:.2f}) — 위험 하한은 검토 권장 하한과 1.0 의 중간으로 둠")
    if review is None:
        review = float(candidates[0]) if candidates.size else 0.5
        notes.append("재현율 조건을 만족하는 p 가 없어 최소 p 를 검토 권장 하한으로 둠")
    if risk is None:
        risk = (review + 1.0) / 2
    if review >= risk:
        notes.append(f"검토 권장 하한 {review:.3f} 이 위험 하한 {risk:.3f} 이상이라 위험 하한 바로 "
                     "아래로 내림(두 조건이 겹침)")
        review = max(min(review, risk - 1e-6), 0.0)
    caution = review / 2
    thresholds = {"주의": x2b._round(caution), "검토 권장": x2b._round(review),
                  "위험": x2b._round(risk)}
    thresholds = _monotone(thresholds)
    return {"thresholds": thresholds, "기준": notes, "등급별": grade_stats(prob, y, thresholds)}


def _monotone(thresholds: dict) -> dict:
    cuts = [thresholds[key] for key in rm.GRADE_THRESHOLD_KEYS]
    for i in range(1, len(cuts)):
        if cuts[i] <= cuts[i - 1]:
            cuts[i] = round(cuts[i - 1] + 0.0001, 4)
    cuts = [min(max(cut, 0.0001), 1.0) for cut in cuts]
    return dict(zip(rm.GRADE_THRESHOLD_KEYS, cuts))


def grade_stats(prob: np.ndarray, y: np.ndarray, thresholds: dict) -> list[dict]:
    grades = np.asarray([rm.grade_for(float(p), thresholds) for p in prob])
    n_pos = int((y == 1).sum())
    out = []
    for i, grade in enumerate(rm.GRADES):
        inside = grades == grade
        at_least = np.isin(grades, rm.GRADES[i:])
        out.append({
            "등급": grade, "n": int(inside.sum()), "유사": int((y[inside] == 1).sum()),
            "정밀도(등급 안 유사율)": x2b._round(float(y[inside].mean())) if inside.any() else None,
            "재현율(이 등급 이상이 잡는 유사)": x2b._round(float((y[at_least] == 1).sum() / n_pos))
            if n_pos else None,
        })
    return out


def standalone_thresholds(rows: list[dict], y: np.ndarray, mask: np.ndarray) -> dict:
    """축별 정밀도 ≥ 0.9 지점(지지 ≥ 10). 없으면 null + 이유."""
    out: dict = {}
    reasons: dict = {}
    for axis in AXES:
        scores = np.asarray([row.get(axis, np.nan) for row in rows], dtype=np.float64)
        valid = mask & ~np.isnan(scores)
        result = ab.precision_threshold(scores[valid], y[valid], target=STANDALONE_PRECISION,
                                        min_support=MIN_SUPPORT)
        out[axis] = result["threshold"]
        best = result.get("최대_정밀도") or {}
        reasons[axis] = (
            f"정밀도 {result['precision']} 재현율 {result['recall']} (n ≥ t {result['n_above']})"
            if result["threshold"] is not None else
            f"비활성 — 지지 {MIN_SUPPORT} 이상에서 최대 정밀도 {best.get('precision')} "
            f"(t ≥ {best.get('threshold')}, n {best.get('n_above')}) < {STANDALONE_PRECISION}"
        )
    return {"thresholds": out, "이유": reasons}


def subset_performance(prob: np.ndarray, y: np.ndarray, rows: list[dict], trial: np.ndarray, *,
                       seed: int, bootstrap: int) -> dict:
    out: dict = {}
    kinds = np.asarray([row.get("종류", "") for row in rows])
    types = np.asarray([rm.mark_type_level(row.get("상표유형", "")) for row in rows])
    sources = np.asarray([row.get("이름B_출처", "") for row in rows])
    for title, values, levels in (("종류별", kinds, KINDS), ("유형별", types, rm.TYPE_LEVELS),
                                  ("이름B 출처별", sources, SOURCES)):
        block = {}
        for level in levels:
            mask = trial & (values == level)
            if mask.sum() >= MIN_SUPPORT:
                block[level or "(없음)"] = auc_block(prob, y, mask, seed=seed, bootstrap=bootstrap)
        out[title] = block
    return out


def bootstrap_coefficients(X: np.ndarray, y: np.ndarray, weight: np.ndarray, names: list[str],
                           easy: np.ndarray, groups: np.ndarray, C: float, *, rounds: int,
                           seed: int, supplementary: np.ndarray) -> dict:
    """심결 사건을 복원추출(쉬운 음성은 고정)해 계수 분포와 판례 조건 성립 비율을 센다.
    (iv) 는 보조 항 x1_d×no_distinctive 를 더한 적합에서 그 계수 < 0 인 비율."""
    rng = np.random.default_rng(seed)
    trial_groups = np.unique(groups[~easy])
    easy_index = np.flatnonzero(easy)
    samples: list[np.ndarray] = []
    supplementary_samples: list[float] = []
    conditions = {"(i) 문자계: x1 > x2_whole": 0, "(ii) 도형계: x2_whole > x1": 0,
                  "(iii) x4 > 0": 0, "(iv) 요부 없음 → x1 효과 감소": 0}
    by_group: dict[str, np.ndarray] = {}
    trial_index = np.flatnonzero(~easy)
    for index in trial_index:
        by_group.setdefault(groups[index], []).append(index)
    by_group = {key: np.asarray(value) for key, value in by_group.items()}
    X_sup = np.column_stack([X, supplementary])
    for _ in range(rounds):
        chosen = rng.choice(trial_groups, trial_groups.size, replace=True)
        index = np.concatenate([by_group[g] for g in chosen] + [easy_index])
        coef, _ = fit_model(X[index], y[index], weight[index], names, C, easy[index])
        samples.append(coef)
        sup_names = names + ["x1_d×no_distinctive"]
        sup_coef, _ = fit_model(X_sup[index], y[index], weight[index], sup_names, C, easy[index])
        supplementary_samples.append(float(sup_coef[-1]))
        c = dict(zip(names, coef))
        x1_text = c["x1_d"] + c.get("x1_d×문자계", 0.0)
        x2_fig = c["x2_whole"] + c.get("x2_whole×도형계", 0.0)
        conditions["(i) 문자계: x1 > x2_whole"] += int(x1_text > c["x2_whole"])
        conditions["(ii) 도형계: x2_whole > x1"] += int(x2_fig > c["x1_d"])
        conditions["(iii) x4 > 0"] += int(c["x4"] > 0)
        conditions["(iv) 요부 없음 → x1 효과 감소"] += int(sup_coef[-1] < 0)
    matrix = np.asarray(samples)
    table = {}
    for i, name in enumerate(names):
        column = matrix[:, i]
        table[name] = {"평균": x2b._round(float(column.mean())),
                       "ci95": [x2b._round(float(np.percentile(column, 2.5))),
                                x2b._round(float(np.percentile(column, 97.5)))]}
    sup = np.asarray(supplementary_samples)
    table["x1_d×no_distinctive(보조)"] = {
        "평균": x2b._round(float(sup.mean())),
        "ci95": [x2b._round(float(np.percentile(sup, 2.5))),
                 x2b._round(float(np.percentile(sup, 97.5)))],
    }
    return {"rounds": rounds, "계수": table,
            "판례_조건_성립_비율": {key: x2b._round(value / rounds)
                              for key, value in conditions.items()}}


# ---- 그림 --------------------------------------------------------------------------------------

def calibration_png(curves: dict[str, dict], path: Path) -> None:
    """신뢰도 곡선(예측 확률 구간 평균 대 관측 유사율), Pillow."""
    from PIL import Image, ImageDraw

    size, left, top, plot = 640, 70, 50, 520
    image = Image.new("RGB", (size + 60, size + 40), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = x2b._font(14)
    draw.rectangle((left, top, left + plot, top + plot), outline=(120, 120, 120))
    draw.line((left, top + plot, left + plot, top), fill=(180, 180, 180))
    for tick in np.linspace(0, 1, 6):
        x = left + plot * tick
        y = top + plot * (1 - tick)
        draw.text((x - 10, top + plot + 6), f"{tick:.1f}", fill=(60, 60, 60), font=font)
        draw.text((left - 40, y - 8), f"{tick:.1f}", fill=(60, 60, 60), font=font)
    colors = ((40, 90, 220), (220, 60, 60), (30, 160, 90))
    legend_y = 12
    for (name, block), color in zip(curves.items(), colors):
        points = [(left + plot * c["예측_평균"], top + plot * (1 - c["관측_유사율"]))
                  for c in block["곡선"] if c["n"]]
        if len(points) > 1:
            draw.line(points, fill=color, width=2)
        for x, y in points:
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color)
        draw.text((left, legend_y), f"{name} (Brier {block['brier']})", fill=color, font=font)
        legend_y += 18
    draw.text((left + plot // 2 - 60, size + 18), "예측 위험도 p(구간 평균)", fill=(60, 60, 60),
              font=font)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


# ---- 실행 --------------------------------------------------------------------------------------

def adopt(results: dict, *, slack: float = ADOPT_AUC_SLACK) -> tuple[str, float, float, list[str]]:
    """채택 규칙: 심결 AUC 최고와 slack 안인 후보 중 (1) 변형 B(판례 구조) 우선, (2) 현실 분포 Brier
    최소. 어긋나면 그 이유를 적는다."""
    rows = [(key, item) for key, item in results.items()]
    best_auc = max(item["cv"]["심결"]["auc"] for _, item in rows)
    pool = [(key, item) for key, item in rows if item["cv"]["심결"]["auc"] >= best_auc - slack]
    notes = [f"심결 OOF AUC 최고 {best_auc:.3f}, 그 {slack} 안의 후보 {len(pool)}/{len(rows)}"]
    b_pool = [(key, item) for key, item in pool if item["variant"] == "B"]
    if b_pool:
        pool = b_pool
        notes.append("판례 구조(변형 B, 교호작용) 후보가 있어 B 로 한정")
    else:
        notes.append("변형 B 가 심결 AUC 허용 범위 밖 — 변형 A 로 한정(판례 구조 불채택)")
    pool.sort(key=lambda kv: (kv[1]["calibration"]["심결+cross+db"]["brier"], -kv[1]["w_easy"]))
    key, item = pool[0]
    notes.append(f"현실 분포 Brier 최소 → {key}")
    return item["variant"], item["w_easy"], item["C"], notes


def run(features_path: Path, easy_path: Path | None, *, out_dir: Path, model_path: Path,
        c_grid=C_GRID, w_easy_grid=W_EASY_GRID, folds: int = FOLDS, repeats: int = REPEATS,
        bootstrap: int = BOOTSTRAP, seed: int = 0, label_kind: str = "최종") -> dict:
    rows = load_rows(features_path, easy_path)
    y_all = labels(rows, label_kind)
    keep = y_all >= 0
    rows = [row for row, k in zip(rows, keep) if k]
    y = y_all[keep].astype(np.float64)
    easy = np.asarray([row["pair_source"] != "trial" for row in rows])
    groups = groups_for(rows)
    masks = set_masks(rows)
    trial = ~easy
    n_trial, n_pos, n_neg = int(trial.sum()), int(y[trial].sum()), int((1 - y[trial]).sum())
    data_summary = {
        "라벨": label_kind, "심결_행": n_trial, "유사": n_pos, "비유사": n_neg,
        "쉬운_음성": {name: int((np.asarray([r["pair_source"] for r in rows]) == name).sum())
                   for name in ("cross", "db")},
        "입력_수": {name: len(names) for name, names in VARIANTS.items()},
        "소수_클래스_대_입력(EPV)": {name: x2b._round(min(n_pos, n_neg) / len(names))
                                  for name, names in VARIANTS.items()},
    }
    results: dict[str, dict] = {}
    for variant, names in VARIANTS.items():
        X = design_matrix(rows, names)
        for w_easy in w_easy_grid:
            weight = sample_weights(rows, w_easy)
            per_c = {}
            for C in c_grid:
                prob = cv_predictions(X, y, weight, names, easy, groups, C, folds=folds,
                                      repeats=repeats, seed=seed)
                per_c[C] = (prob, auc_block(prob, y, masks["심결"], seed=seed, bootstrap=0)["auc"])
            best_c = max(per_c, key=lambda c: per_c[c][1] or 0.0)
            prob = per_c[best_c][0]
            key = f"{variant}/w{w_easy:g}"
            results[key] = {
                "variant": variant, "w_easy": w_easy, "C": best_c,
                "C_후보": {str(c): x2b._round(per_c[c][1]) for c in c_grid},
                "cv": {name: auc_block(prob, y, mask, seed=seed, bootstrap=bootstrap)
                       for name, mask in masks.items()},
                "calibration": {name: calibration(prob[mask], y[mask])
                                for name, mask in masks.items()
                                if name in ("심결", "심결+cross+db")},
                "_prob": prob,
            }
    variant, w_easy, C, adopt_notes = adopt(results)
    adopted_key = f"{variant}/w{w_easy:g}"
    adopted = results[adopted_key]
    names = VARIANTS[variant]
    X = design_matrix(rows, names)
    weight = sample_weights(rows, w_easy)
    prob = adopted["_prob"]
    baselines = {
        name: {set_name: auc_block(scores, y, mask, seed=seed, bootstrap=bootstrap)
               for set_name, mask in masks.items()}
        for name, scores in baseline_scores(rows).items()
    }
    supplementary = design_matrix(rows, ["x1_d×no_distinctive"])[:, 0]
    boot = bootstrap_coefficients(X, y, weight, names, easy, groups, C, rounds=bootstrap, seed=seed,
                                  supplementary=supplementary)
    coef, intercept = fit_model(X, y, weight, names, C, easy)
    grades = {name: grade_thresholds(prob[mask], y[mask]) for name, mask in masks.items()
              if name in ("심결", "심결+cross+db")}
    standalone = standalone_thresholds(rows, y, trial)
    subsets = subset_performance(prob, y, rows, trial, seed=seed, bootstrap=bootstrap)
    mark_experiment = None
    if label_kind == "최종":
        mark_y = labels(rows, "표장").astype(np.float64)
        mark_keep = mark_y >= 0
        mark_prob = cv_predictions(X[mark_keep], mark_y[mark_keep], weight[mark_keep], names,
                                   easy[mark_keep], groups[mark_keep], C, folds=folds,
                                   repeats=repeats, seed=seed)
        mark_experiment = {name: auc_block(mark_prob, mark_y[mark_keep], mask[mark_keep],
                                           seed=seed, bootstrap=bootstrap)
                           for name, mask in masks.items()}
    model = {
        "version": rm.MODEL_VERSION, "trained_at": date.today().isoformat(), "label": label_kind,
        "variant": variant, "w_easy": w_easy, "C": C,
        "features": names,
        "coefficients": {name: round(float(value), 4) for name, value in zip(names, coef)},
        "intercept": round(intercept, 4),
        "grade_thresholds": grades["심결+cross+db"]["thresholds"],
        "grade_basis": ("심결+cross+db OOF 확률(위험 정밀도 ≥ 0.8, 검토 권장 재현율 ≥ 0.9, "
                        "안전/주의 등분)"),
        "standalone_thresholds": standalone["thresholds"],
        "standalone_reason": standalone["이유"],
        "meta": {
            "n_trial": n_trial, "n_pos": n_pos, "n_neg": n_neg,
            "n_easy": int(easy.sum()), "folds": folds, "repeats": repeats, "bootstrap": bootstrap,
            "cv_auc": {name: block["auc"] for name, block in adopted["cv"].items()},
            "cv_auc_ci95": {name: block["auc_ci95"] for name, block in adopted["cv"].items()},
            "brier": {name: block["brier"] for name, block in adopted["calibration"].items()},
            "adopt_notes": adopt_notes,
            "feature_definitions": (
                "축 점수 0~1(결측 0 + miss_*=1; x3_d 는 has_meaning_both False 면 결측), "
                "has_distinctive_part_a/b 0/1, 유형 지시변수(기준 문자), 교호작용 x1_d×문자계(문자·"
                "결합-문자요부)·x2_whole×도형계(도형·결합-도형요부). 표준화 없음."
            ),
        },
    }
    rm.validate_model(model)
    model_path = Path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    calibration_png({name: adopted["calibration"][name] for name in adopted["calibration"]},
                    out_dir / "risk_model_v1_calibration.png")
    summary = {
        "기준일": date.today().isoformat(), "데이터": data_summary,
        "변형": {key: {k: v for k, v in item.items() if k != "_prob"}
               for key, item in results.items()},
        "채택": {"key": adopted_key, "규칙": adopt_notes, "variant": variant, "w_easy": w_easy,
               "C": C},
        "기준선": baselines, "부트스트랩": boot,
        "계수": model["coefficients"], "절편": model["intercept"],
        "등급": grades, "단독_임계값": standalone, "부분집합": subsets,
        "표장_라벨_보조실험": mark_experiment,
        "모델_파일": str(model_path),
    }
    (out_dir / "risk_model_v1_results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "risk_model_v1_report.md").write_text(report_text(summary), encoding="utf-8")
    return summary


# ---- 보고서 ------------------------------------------------------------------------------------

def _auc(block: dict | None) -> str:
    if not block or block.get("auc") is None:
        return "—"
    low, high = block.get("auc_ci95", [None, None])
    ci = f" ({low:.2f}~{high:.2f})" if low is not None else ""
    return f"{block['auc']:.3f}{ci} n {block['n']}"


def report_text(summary: dict) -> str:
    data = summary["데이터"]
    lines = [f"# 통합 모델 1차 학습 보고 ({summary['기준일']})", ""]
    lines.append(f"- 라벨 {data['라벨']} · 심결 {data['심결_행']}행(유사 {data['유사']}·비유사 "
                 f"{data['비유사']}) · 쉬운 음성 cross {data['쉬운_음성']['cross']}·db "
                 f"{data['쉬운_음성']['db']} · 입력 수 {data['입력_수']} · 소수 클래스/입력(EPV) "
                 f"{data['소수_클래스_대_입력(EPV)']}")
    lines += ["", "## 변형 × 쉬운 음성 가중치 — CV OOF AUC (C 는 심결 AUC 로 선택)", "",
              "| 변형/w_easy | C | 심결 | 심결+cross | 심결+cross+db | Brier 심결 / 현실 | "
              "C 후보 |",
              "|---|---|---|---|---|---|---|"]
    for key, item in summary["변형"].items():
        cv, cal = item["cv"], item["calibration"]
        lines.append(f"| {key} | {item['C']} | {_auc(cv['심결'])} | {_auc(cv['심결+cross'])} | "
                     f"{_auc(cv['심결+cross+db'])} | {cal['심결']['brier']} / "
                     f"{cal['심결+cross+db']['brier']} | {item['C_후보']} |")
    adopted = summary["채택"]
    lines += ["", f"채택: **{adopted['key']}** (C {adopted['C']}) — " + " · ".join(adopted["규칙"]),
              ""]
    lines += ["## 기준선", "", "| 기준선 | 심결 | 심결+cross | 심결+cross+db |",
              "|---|---|---|---|"]
    for name, block in summary["기준선"].items():
        lines.append(f"| {name} | {_auc(block['심결'])} | {_auc(block['심결+cross'])} | "
                     f"{_auc(block['심결+cross+db'])} |")
    boot = summary["부트스트랩"]
    lines += ["", f"## 채택 모델 계수 (전체 적합) 와 부트스트랩 {boot['rounds']}회 분포", "",
              "| 항 | 계수 | 부트스트랩 평균 | 95% 구간 |", "|---|---|---|---|",
              f"| intercept | {summary['절편']} | — | — |"]
    for name, value in summary["계수"].items():
        b = boot["계수"][name]
        lines.append(f"| {name} | {value} | {b['평균']} | {b['ci95'][0]} ~ {b['ci95'][1]} |")
    sup = boot["계수"]["x1_d×no_distinctive(보조)"]
    lines.append(f"| x1_d×no_distinctive(보조 적합) | — | {sup['평균']} | {sup['ci95'][0]} ~ "
                 f"{sup['ci95'][1]} |")
    lines += ["", "## 판례 검증 (부트스트랩 성립 비율)", "", "| 조건 | 성립 비율 |", "|---|---|"]
    for key, value in boot["판례_조건_성립_비율"].items():
        lines.append(f"| {key} | {value} |")
    lines += ["", "## 보정 (신뢰도 곡선 10구간, OOF)", ""]
    for set_name, block in summary["변형"][adopted["key"]]["calibration"].items():
        lines += [f"### {set_name} — Brier {block['brier']}", "",
                  "| 구간 | n | 예측 평균 | 관측 유사율 |", "|---|---|---|---|"]
        for c in block["곡선"]:
            lines.append(f"| {c['구간']} | {c['n']} | {c['예측_평균']} | {c['관측_유사율']} |")
        lines.append("")
    lines += ["## 등급 임계값", ""]
    for set_name, block in summary["등급"].items():
        lines += [f"### {set_name} 기준 — {block['thresholds']}", ""]
        for note in block["기준"]:
            lines.append(f"- {note}")
        lines += ["", "| 등급 | n | 유사 | 정밀도(등급 안 유사율) | 재현율(이 등급 이상) |",
                  "|---|---|---|---|---|"]
        for g in block["등급별"]:
            lines.append(f"| {g['등급']} | {g['n']} | {g['유사']} | "
                         f"{g['정밀도(등급 안 유사율)']} | "
                         f"{g['재현율(이 등급 이상이 잡는 유사)']} |")
        lines.append("")
    lines += ["## 단독 임계값 (축별 정밀도 ≥ 0.9, 심결 최종 라벨)", "", "| 축 | τ | 비고 |",
              "|---|---|---|"]
    for axis, tau in summary["단독_임계값"]["thresholds"].items():
        lines.append(f"| {axis} | {tau} | {summary['단독_임계값']['이유'][axis]} |")
    lines += ["", "## 부분집합 (심결, 채택 모델 OOF)", ""]
    for title, block in summary["부분집합"].items():
        lines += [f"### {title}", "", "| 수준 | AUC |", "|---|---|"]
        for level, item in block.items():
            lines.append(f"| {level} | {_auc(item)} |")
        lines.append("")
    if summary.get("표장_라벨_보조실험"):
        exp = summary["표장_라벨_보조실험"]
        lines += ["## 표장 라벨 보조 실험 (같은 설정, 표장 라벨 있는 행)", "",
                  f"- 심결 {_auc(exp['심결'])} · 심결+cross {_auc(exp['심결+cross'])} · "
                  f"심결+cross+db {_auc(exp['심결+cross+db'])}", ""]
    lines.append(f"모델 파일: {summary['모델_파일']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--easy", type=Path, default=DEFAULT_EASY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--folds", type=int, default=FOLDS)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--bootstrap", type=int, default=BOOTSTRAP)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--label", choices=("최종", "표장"), default="최종")
    args = parser.parse_args(argv)
    summary = run(args.features, args.easy, out_dir=args.out_dir, model_path=args.model,
                  folds=args.folds, repeats=args.repeats, bootstrap=args.bootstrap, seed=args.seed,
                  label_kind=args.label)
    print(report_text(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
