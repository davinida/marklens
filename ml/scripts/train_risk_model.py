"""통합 모델 v1.2 학습 — 심결례 정답 데이터(`pairs_features.csv`)로 4축 결합 방법을 비교하고 판례
사전분포 + 단조 제약 로지스틱을 채택한다(통합 모델 설계 §3·§4-3·§7·§7-1·§7-2). KIPRIS 호출 0, 서비스
코드 미접촉. 산출물은 계수 JSON(`shared/model/risk_model_v1.json`, version risk_model_v1.2)·보고서
(`ml/data/trials/risk_model_v1_report.md`·`_results.json`)·신뢰도 곡선·EBM 형상 곡선 PNG.

v1.2(§7-2): 절편은 사전분포 없이 자유, 사전분포는 유사도 축·교호작용에만. 요부 플래그 두 개 대신
`any_no_distinctive`(한쪽이라도 요부 없음) + x1_d×any_no_distinctive(사전평균 −0.5, 2000후2453 —
요부 없는 쌍은 호칭을 덜 믿음; 판례 (iv) 는 이 계수 < 0). 단조 제약은 x1 효과의 모든 조합(본체·
+문자계·+요부없음·+둘 다) ≥ 0 으로 SLSQP 선형 제약. 도형 규칙(figure_rule: 도형계 입력은 caveat,
x2_whole ≥ 0.9 면 등급 하한 검토 권장)은 데이터로 검증하지 않은 제품 규칙으로 JSON 에만 기록한다.

    ml/venv/bin/python ml/scripts/train_risk_model.py                  # 로지스틱 + 사전분포(기본)
    ml/venv/bin/python ml/scripts/train_risk_model.py --methods logistic,prior,ebm,gbm
        # EBM·GBM 은 ml/requirements-experiments.txt 설치 뒤(pip install -c constraints.txt -r …)
    ml/venv/bin/python ml/scripts/train_risk_model.py --bootstrap 50 --repeats 1   # 빠른 확인

v1.1 입력(§7-1 ① 편향 제거): x1_d·x2_text_d·x2_whole·x3_d·x4, 결측 지시변수 miss_x2img·miss_x3·
miss_x4, has_distinctive_part_a/b, 교호작용 x1_d×문자계·x2_whole×도형계. 상표 유형 주효과(type_*)와
miss_x1·miss_x2text 는 뺐고 상대 이름이 없는 심결 행은 학습에서 제외한다 — 유형은 "어느 축을
보느냐"만 바꾸고(교호작용), 이름 없음은 서비스에 없는 상황이다. 표준화 없음(계수 = 점수 1.0 당
로짓).

방법(같은 입력·같은 사건 단위 5겹×3반복 CV·같은 쉬운 음성 가중치 w_easy 0.5):
  1. logistic — L2 로지스틱(v1 과 같은 목적함수 ½‖w‖² + C·Σ s·logloss, scipy L-BFGS), C 는 CV.
  2. prior — 판례 사전분포 + 단조 제약 로지스틱: 계수마다 N(μ_j, σ²)(μ: x1 1.0·x1×문자계 +1.0,
     x2_whole 0.5·x2_whole×도형계 +1.0, x2_text 0.5, x3 0.5, x4 1.0, 나머지·절편 0; σ ∈ {0.5, 1, 2}
     는 CV),
     유사도 축의 본체 계수 ≥ 0 과 본체 + 교호작용 ≥ 0 (L-BFGS-B 경계 + 재매개화).
  3. ebm — interpret ExplainableBoostingClassifier(max_bins 16, interactions 3, 강한 정규화).
  4. gbm — lightgbm(num_leaves 4, max_depth 2, n_estimators CV, 유사도 축 단조 +1) + SHAP.
  쉬운 음성에는 이미지가 없어 1·2 는 이미지 블록(x2_whole·miss_x2img·x2_whole×도형계)을 심결
  행만으로 적합한 값에 고정(오프셋)하고, 3·4 는 이미지 블록을 입력에서 뺀다("이미지 없음 = 쉬운
  음성"을 배우지 않도록). 판례 4조건은 모든 방법에서 로짓 부분의존 기울기(축을 0 → 1 로 올렸을 때
  로짓 변화의 부분집합 평균)로 잰다 — 선형 모델에서는 계수(합)와 같다. 채택 규칙: 심결 CV AUC 가
  기준(logistic)보다 CI 밖으로 높은 방법이 없으면 2 를 채택(변별력이 같으면 판례 일관성·안전성
  우선), 있으면 보고하고 채택은 사람이.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from scipy.optimize import minimize  # noqa: E402
from scipy.special import expit  # noqa: E402
from scipy.stats import rankdata  # noqa: E402
from src.model import risk_model as rm  # noqa: E402

# axes_benchmark·x2_benchmark 를 import 하지 않는다 — 그 모듈은 torch 를 적재하는데, lightgbm(brew
# libomp)과 torch 의 OpenMP 런타임이 한 프로세스에 겹치면 macOS 에서 SIGSEGV 가 난다. 아래 평가
# 도우미는 x2_benchmark 의 정의를 그대로 옮긴 것(테스트가 같은 값을 내는지 확인).

DEFAULT_BASE = ML_ROOT / "data" / "trials"
DEFAULT_FEATURES = DEFAULT_BASE / "pairs_features.csv"
DEFAULT_EASY = DEFAULT_BASE / "pairs_features_easy.csv"
DEFAULT_OUT_DIR = DEFAULT_BASE
DEFAULT_MODEL = rm.DEFAULT_MODEL_PATH
NUMERIC = ("x1", "x2_text", "x2_fig", "x2_whole", "x3", "x3_raw", "x4", "x1_d", "x2_text_d", "x3_d")
FLAGS = ("has_names", "has_pron_a", "has_pron_b", "has_meaning_a", "has_meaning_b",
         "has_spelling_a", "has_spelling_b", "has_goods", "has_image", "has_fig")
KINDS = ("거절결정불복", "무효", "권리범위확인(적극적)", "권리범위확인(소극적)")

METHODS = ("logistic", "prior", "ebm", "gbm")
DEFAULT_METHODS = ("logistic", "prior")
C_GRID = (0.1, 0.3, 1.0, 3.0)
SIGMA_GRID = (0.5, 1.0, 2.0)
ESTIMATORS_GRID = (50, 100, 200, 400)
W_EASY = 0.5
FOLDS = 5
REPEATS = 3
BOOTSTRAP = 500
CALIBRATION_BINS = 10
PRECISION_RISK = 0.8
RECALL_REVIEW = 0.9
STANDALONE_PRECISION = 0.7  # ③ 단독 임계값: 축 하나의 정밀도 ≥ 0.7 이면 등급 하한 "검토 권장"
MIN_SUPPORT = 10
FEATURES = [
    "x1_d", "x2_text_d", "x2_whole", "x3_d", "x4",
    "miss_x2img", "miss_x3", "miss_x4",
    "any_no_distinctive",
    "x1_d×문자계", "x2_whole×도형계", "x1_d×any_no_distinctive",
]
REMOVED_TERMS = ["type_도형", "type_결합-문자요부", "type_결합-도형요부", "miss_x1", "miss_x2text",
                 "has_distinctive_part_a", "has_distinctive_part_b"]  # 뒤 둘은 v1.2 에서 대체
FIGURE_X2_THRESHOLD = 0.9  # 도형 규칙: 도형계 입력에서 x2_whole ≥ 이 값이면 하한 검토 권장(미검증)
FIGURE_CAVEAT = "도형 유사는 검증 데이터가 적어 참고용"
IMAGE_BLOCK = ("x2_whole", "miss_x2img", "x2_whole×도형계")
TREE_FEATURES = [name for name in FEATURES if name not in IMAGE_BLOCK]
AXES = ("x1_d", "x2_text_d", "x2_whole", "x3_d", "x4")
INTERACTION_OF = {"x1_d": "x1_d×문자계", "x2_whole": "x2_whole×도형계"}
MISS_OF = {"x2_whole": "miss_x2img", "x3_d": "miss_x3", "x4": "miss_x4"}
MONOTONE_FEATURES = ("x1_d", "x2_text_d", "x2_whole", "x3_d", "x4", "x1_d×문자계",
                     "x2_whole×도형계", "x1_d×any_no_distinctive")
PRIOR_MU = {
    "x1_d": 1.0, "x1_d×문자계": 1.0, "x2_whole": 0.5, "x2_whole×도형계": 1.0,
    "x2_text_d": 0.5, "x3_d": 0.5, "x4": 1.0, "x1_d×any_no_distinctive": -0.5,
}
PRIOR_FEATURES = tuple(PRIOR_MU)  # 사전분포는 유사도 축·교호작용에만(절편·결측·요부 플래그는 자유)
SETS = (("심결", ("trial",)), ("심결+cross", ("trial", "cross")),
        ("심결+cross+db", ("trial", "cross", "db")))
SOURCES = ("kipris", "llm", "본문", "ocr", "도형", "")
CONDITIONS = ("(i) 문자계: x1 > x2_whole", "(ii) 도형계: x2_whole > x1", "(iii) x4 > 0",
              "(iv) 요부 없음 → x1 효과 감소")


# ---- 평가 도우미(x2_benchmark·axes_benchmark 와 같은 정의) --------------------------------------

def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def roc_auc(scores: np.ndarray, labels: np.ndarray) -> float | None:
    """Mann-Whitney 순위 AUC(동점은 평균 순위). 한쪽 클래스가 비면 None."""
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    n_pos, n_neg = int((labels == 1).sum()), int((labels == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = rankdata(scores, method="average")
    rank_sum = float(ranks[labels == 1].sum())
    return float((rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def bootstrap_auc(scores: np.ndarray, labels: np.ndarray, *, rounds: int,
                  seed: int = 0) -> tuple[float | None, float | None]:
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    if rounds <= 0 or roc_auc(scores, labels) is None:
        return None, None
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(rounds):
        index = rng.integers(0, scores.size, scores.size)
        auc = roc_auc(scores[index], labels[index])
        if auc is not None:
            values.append(auc)
    if not values:
        return None, None
    return _round(np.percentile(values, 2.5)), _round(np.percentile(values, 97.5))


def evaluate_subset(scores: np.ndarray, labels: np.ndarray, *, seed: int, bootstrap: int) -> dict:
    similar, dissimilar = scores[labels == 1], scores[labels == 0]
    low, high = bootstrap_auc(scores, labels, rounds=bootstrap, seed=seed)
    return {
        "n": int(scores.size), "n_유사": int(similar.size), "n_비유사": int(dissimilar.size),
        "auc": _round(roc_auc(scores, labels)), "auc_ci95": [low, high],
        "유사_중앙값": _round(float(np.median(similar))) if similar.size else None,
        "비유사_중앙값": _round(float(np.median(dissimilar))) if dissimilar.size else None,
    }


def precision_threshold(scores: np.ndarray, labels: np.ndarray, *, target: float,
                        min_support: int) -> dict:
    """정밀도(점수 ≥ t 인 쌍 중 유사 비율) ≥ target 이 되는 최소 t(지지 n ≥ min_support)."""
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    n_pos = int((labels == 1).sum())
    result = {"threshold": None, "precision": None, "recall": None, "n_above": 0,
              "최대_정밀도": None}
    if scores.size == 0 or n_pos == 0:
        return result
    best: dict | None = None
    for threshold in np.unique(scores):
        above = scores >= threshold
        count = int(above.sum())
        if count < min_support:
            break
        precision = float(labels[above].mean())
        point = {"threshold": _round(float(threshold)), "precision": _round(precision),
                 "recall": _round(float((labels[above] == 1).sum() / n_pos)), "n_above": count}
        if best is None or precision > best["precision"]:
            best = point
        if precision >= target and result["threshold"] is None:
            result.update(point)
    result["최대_정밀도"] = best
    return result


def load_features(path: Path) -> list[dict]:
    import csv

    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for column in NUMERIC:
            raw = row.get(column, "")
            row[column] = float(raw) if raw not in (None, "") else np.nan
        for column in FLAGS:
            row[column] = int(row.get(column) or 0)
        row.setdefault("pair_source", "trial")
    return rows


def labels_for(features: list[dict], kind: str) -> np.ndarray:
    column = "표장라벨" if kind == "표장" else "최종라벨"
    return np.asarray([1 if row.get(column, "") == "유사" else
                       (0 if row.get(column, "") == "비유사" else -1) for row in features],
                      dtype=np.int64)


def _font(size: int):
    from PIL import ImageFont

    for candidate in ("/System/Library/Fonts/AppleSDGothicNeo.ttc",
                      "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                      "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


# ---- 데이터 ----------------------------------------------------------------------------------

def load_rows(features_path: Path, easy_path: Path | None) -> list[dict]:
    rows = load_features(features_path)
    for row in rows:
        row["pair_source"] = row.get("pair_source") or "trial"
    if easy_path is not None and Path(easy_path).exists():
        for row in load_features(easy_path):
            row["pair_source"] = row.get("pair_source") or "cross"
            rows.append(row)
    return rows


def row_features(row: dict) -> dict:
    """특징 CSV 행(load_features 뒤) → 런타임 입력 사전(§4-3 규약)."""
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


def families(rows: list[dict]) -> np.ndarray:
    """행별 유형 가족: text(문자·결합-문자요부·미상·결합) / figure(도형·결합-도형요부)."""
    return np.asarray([
        "figure" if rm.mark_type_level(row.get("상표유형", "")) in rm.FIGURE_FAMILY else "text"
        for row in rows
    ])


def has_name(row: dict) -> bool:
    value = row.get("x1_d", np.nan)
    return not (value is None or (isinstance(value, float) and np.isnan(value)))


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


# ---- 선형 적합(로지스틱·사전분포) -------------------------------------------------------------

def fit_logistic(X: np.ndarray, y: np.ndarray, weight: np.ndarray, C: float, *,
                 offset: np.ndarray | None = None) -> tuple[np.ndarray, float]:
    """½‖w‖² + C·Σ s_i·logloss_i (절편 비벌점, sklearn 과 같은 목적함수)를 L-BFGS 로 푼다."""
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


def monotone_constraints(names: list[str]) -> np.ndarray:
    """단조 제약 G(행마다 G·coef ≥ 0): 유사도 축 본체 ≥ 0, x2_whole 본체 + 도형계 교호작용 ≥ 0,
    x1 본체 + {문자계, 요부없음} 교호작용의 모든 조합 ≥ 0. 입력에 없는 항은 건너뛴다."""
    index = {name: i for i, name in enumerate(names)}
    rows: list[np.ndarray] = []

    def row(*terms: str) -> None:
        vector = np.zeros(len(names))
        for term in terms:
            vector[index[term]] = 1.0
        rows.append(vector)

    for axis in AXES:
        if axis in index:
            row(axis)
    if "x2_whole" in index and "x2_whole×도형계" in index:
        row("x2_whole", "x2_whole×도형계")
    if "x1_d" in index:
        extras = [name for name in ("x1_d×문자계", "x1_d×any_no_distinctive") if name in index]
        for mask in range(1, 2 ** len(extras)):
            row("x1_d", *[name for bit, name in enumerate(extras) if mask >> bit & 1])
    return np.asarray(rows) if rows else np.zeros((0, len(names)))


def fit_prior(X: np.ndarray, y: np.ndarray, weight: np.ndarray, names: list[str], sigma: float, *,
              offset: np.ndarray | None = None, mu: dict[str, float] | None = None
              ) -> tuple[np.ndarray, float]:
    """판례 사전분포 + 단조 제약 로지스틱(MAP): Σ_{j∈사전분포 항} (coef_j − μ_j)²/(2σ²) +
    Σ s_i·logloss_i. 절편·결측 지시변수·요부 플래그는 사전분포 없이 자유(v1.2). 선형 부등식 제약
    (monotone_constraints)은 SLSQP 로 푼다."""
    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    weight = np.asarray(weight, dtype=np.float64)
    offset = np.zeros(X.shape[0]) if offset is None else np.asarray(offset, dtype=np.float64)
    keep = weight > 0
    X, y, weight, offset = X[keep], y[keep], weight[keep], offset[keep]
    d = X.shape[1]
    mu_map = mu or PRIOR_MU
    mu_vector = np.asarray([mu_map.get(name, 0.0) for name in names])
    precision = np.asarray([1.0 / (sigma * sigma) if name in mu_map else 0.0 for name in names])
    G = monotone_constraints(names)
    G_theta = np.column_stack([G, np.zeros(G.shape[0])]) if G.size else np.zeros((0, d + 1))

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        coef, b = theta[:d], theta[d]
        z = X @ coef + b + offset
        loss = np.logaddexp(0.0, z) - y * z
        diff = coef - mu_vector
        value = 0.5 * float(np.sum(precision * diff * diff)) + float(np.sum(weight * loss))
        residual = weight * (expit(z) - y)
        gradient = np.concatenate([precision * diff + X.T @ residual, [float(residual.sum())]])
        return value, gradient

    start = np.concatenate([mu_vector, [0.0]])  # 사전평균은 제약을 만족한다(실행 가능 시작점)
    constraints = ([{"type": "ineq", "fun": lambda t: G_theta @ t, "jac": lambda t: G_theta}]
                   if G_theta.shape[0] else [])
    result = minimize(objective, start, jac=True, method="SLSQP", constraints=constraints,
                      options={"maxiter": 1000, "ftol": 1e-12})
    coef = result.x[:d]
    if G.size:
        coef = _project_feasible(coef, G)
    return coef, float(result.x[d])


def _project_feasible(coef: np.ndarray, G: np.ndarray, tolerance: float = 1e-9) -> np.ndarray:
    """SLSQP 의 작은 수치 위반(1e-9 수준)을 0 으로 다듬는다 — 런타임 단조 검증과 맞추기 위해."""
    out = coef.copy()
    for _ in range(3):
        slack = G @ out
        for row, value in zip(G, slack):
            if value < 0 and value > -1e-6:
                positive = row > 0
                out[positive] -= value / positive.sum()
    out[np.abs(out) < tolerance] = 0.0
    return out


def fit_linear(X: np.ndarray, y: np.ndarray, weight: np.ndarray, names: list[str], easy: np.ndarray,
               *, method: str, hyper: float) -> tuple[np.ndarray, float]:
    """심결 행만으로 전체 적합(1단계) → 쉬운 음성이 있으면 이미지 블록을 고정하고 나머지를 다시
    적합(2단계). 쉬운 음성 가중치가 0 이면 1단계 해 그대로."""
    fitter = fit_logistic if method == "logistic" else None
    trial = ~easy

    def fit(Xs, ys, ws, sub_names, offset=None):
        if method == "logistic":
            return fitter(Xs, ys, ws, hyper, offset=offset)
        return fit_prior(Xs, ys, ws, sub_names, hyper, offset=offset)

    coef, intercept = fit(X[trial], y[trial], weight[trial], names)
    if not np.any(easy & (weight > 0)):
        return coef, intercept
    image = np.asarray([name in IMAGE_BLOCK for name in names])
    if not image.any():
        return fit(X, y, weight, names)
    offset = X[:, image] @ coef[image]
    rest_names = [name for name, is_image in zip(names, image) if not is_image]
    rest_coef, intercept = fit(X[:, ~image], y, weight, rest_names, offset=offset)
    full = coef.copy()
    full[~image] = rest_coef
    return full, intercept


# ---- 트리 방법(실험 의존성) ----------------------------------------------------------------------

def fit_ebm(X: np.ndarray, y: np.ndarray, weight: np.ndarray, names: list[str], seed: int):
    from interpret.glassbox import ExplainableBoostingClassifier

    model = ExplainableBoostingClassifier(
        feature_names=list(names), max_bins=16, max_interaction_bins=8, interactions=3,
        max_leaves=2, min_samples_leaf=10, learning_rate=0.01, outer_bags=8, reg_lambda=2.0,
        early_stopping_rounds=50, n_jobs=1, random_state=seed,
    )
    keep = weight > 0
    return model.fit(X[keep], y[keep], sample_weight=weight[keep])


def fit_gbm(X: np.ndarray, y: np.ndarray, weight: np.ndarray, names: list[str], seed: int,
            n_estimators: int):
    import lightgbm as lgb

    constraints = [1 if name in MONOTONE_FEATURES else 0 for name in names]
    model = lgb.LGBMClassifier(
        num_leaves=4, max_depth=2, n_estimators=n_estimators, learning_rate=0.05,
        min_child_samples=10, reg_lambda=1.0, monotone_constraints=constraints,
        verbose=-1, random_state=seed, n_jobs=1,
    )
    keep = weight > 0
    return model.fit(X[keep], y[keep], sample_weight=weight[keep])


class Fitted:
    """적합된 모델 하나 — logit(X) 를 통일된 방식으로 낸다."""

    def __init__(self, method: str, names: list[str], model=None, coef=None, intercept=0.0):
        self.method, self.names, self.model = method, names, model
        self.coef, self.intercept = coef, intercept

    def logit(self, X: np.ndarray) -> np.ndarray:
        if self.method in ("logistic", "prior"):
            return X @ self.coef + self.intercept
        if self.method == "ebm":
            return np.asarray(self.model.decision_function(X), dtype=np.float64)
        return np.asarray(self.model.predict(X, raw_score=True), dtype=np.float64)

    def prob(self, X: np.ndarray) -> np.ndarray:
        return expit(self.logit(X))


def fit_method(method: str, X: np.ndarray, y: np.ndarray, weight: np.ndarray, names: list[str],
               easy: np.ndarray, hyper, seed: int = 0) -> Fitted:
    if method in ("logistic", "prior"):
        coef, intercept = fit_linear(X, y, weight, names, easy, method=method, hyper=hyper)
        return Fitted(method, names, coef=coef, intercept=intercept)
    if method == "ebm":
        return Fitted(method, names, model=fit_ebm(X, y, weight, names, seed))
    if method == "gbm":
        return Fitted(method, names, model=fit_gbm(X, y, weight, names, seed, int(hyper)))
    raise ValueError(f"모르는 방법: {method}")


def feature_names_for(method: str) -> list[str]:
    return list(FEATURES) if method in ("logistic", "prior") else list(TREE_FEATURES)


def hyper_grid(method: str, *, c_grid, sigma_grid, estimators_grid) -> tuple:
    return {"logistic": tuple(c_grid), "prior": tuple(sigma_grid), "ebm": (None,),
            "gbm": tuple(estimators_grid)}[method]


# ---- 교차검증·평가 ---------------------------------------------------------------------------

def folds_for(y: np.ndarray, groups: np.ndarray, *, folds: int, seed: int):
    from sklearn.model_selection import StratifiedGroupKFold

    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)
    return list(splitter.split(np.zeros((y.size, 1)), y, groups))


def cv_predictions(method: str, X: np.ndarray, y: np.ndarray, weight: np.ndarray,
                   names: list[str], easy: np.ndarray, groups: np.ndarray, hyper, *, folds: int,
                   repeats: int, seed: int) -> tuple[np.ndarray, list[tuple[Fitted, np.ndarray]]]:
    """반복 교차검증 OOF 확률(반복 평균)과 겹 모델 목록(판례 조건 안정성용)."""
    total = np.zeros(y.size)
    fold_models: list[tuple[Fitted, np.ndarray]] = []
    for repeat in range(repeats):
        for train, test in folds_for(y, groups, folds=folds, seed=seed + repeat):
            fitted = fit_method(method, X[train], y[train], weight[train], names, easy[train],
                                hyper, seed=seed + repeat)
            total[test] += fitted.prob(X[test])
            fold_models.append((fitted, test))
    return total / repeats, fold_models


def set_masks(rows: list[dict]) -> dict[str, np.ndarray]:
    sources = np.asarray([row["pair_source"] for row in rows])
    return {name: np.isin(sources, members) for name, members in SETS}


def auc_block(prob: np.ndarray, y: np.ndarray, mask: np.ndarray, *, seed: int,
              bootstrap: int) -> dict:
    if not mask.any():
        return {"n": 0, "auc": None, "auc_ci95": [None, None]}
    return evaluate_subset(prob[mask], y[mask], seed=seed, bootstrap=bootstrap)


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
            "예측_평균": _round(float(prob[inside].mean())) if n else None,
            "관측_유사율": _round(float(y[inside].mean())) if n else None,
        })
    return {"brier": _round(float(np.mean((prob - y) ** 2))), "곡선": curve}


# ---- 판례 조건(로짓 부분의존 기울기) -----------------------------------------------------------

def perturbed(X: np.ndarray, names: list[str], family: np.ndarray, axis: str,
              value: float) -> np.ndarray:
    """축 점수를 value 로 바꾼 설계행렬(교호작용·결측 지시변수를 함께 맞춘다). 축이 입력에 없으면
    None."""
    index = {name: i for i, name in enumerate(names)}
    if axis not in index:
        return None
    out = X.copy()
    out[:, index[axis]] = value
    interaction = INTERACTION_OF.get(axis)
    if interaction in index:
        active = family == ("text" if axis == "x1_d" else "figure")
        out[:, index[interaction]] = np.where(active, value, 0.0)
    if axis == "x1_d" and "x1_d×any_no_distinctive" in index:
        flag = out[:, index["any_no_distinctive"]] if "any_no_distinctive" in index else 0.0
        out[:, index["x1_d×any_no_distinctive"]] = value * flag
    miss = MISS_OF.get(axis)
    if miss in index:
        out[:, index[miss]] = 0.0
    return out


def pd_slope(fitted: Fitted, X: np.ndarray, family: np.ndarray, axis: str,
             mask: np.ndarray) -> float | None:
    """부분집합 mask 에서 축을 0 → 1 로 올렸을 때 로짓 변화의 평균(선형 모델이면 계수 합)."""
    if not mask.any():
        return None
    high = perturbed(X[mask], fitted.names, family[mask], axis, 1.0)
    low = perturbed(X[mask], fitted.names, family[mask], axis, 0.0)
    if high is None:
        return None
    return float(np.mean(fitted.logit(high) - fitted.logit(low)))


def condition_checks(fitted: Fitted, X: np.ndarray, family: np.ndarray, trial: np.ndarray,
                     distinct: np.ndarray) -> dict[str, bool | None]:
    """판례 4조건(설계 §3·§7): 부분집합별 로짓 기울기 비교. 축이 입력에 없으면 None(평가 불가)."""
    text, figure = trial & (family == "text"), trial & (family == "figure")
    x1_text = pd_slope(fitted, X, family, "x1_d", text)
    x2_text = pd_slope(fitted, X, family, "x2_whole", text)
    x1_fig = pd_slope(fitted, X, family, "x1_d", figure)
    x2_fig = pd_slope(fitted, X, family, "x2_whole", figure)
    x4_all = pd_slope(fitted, X, family, "x4", trial)
    x1_without = pd_slope(fitted, X, family, "x1_d", trial & ~distinct)
    x1_with = pd_slope(fitted, X, family, "x1_d", trial & distinct)
    return {
        CONDITIONS[0]: None if x2_text is None else x1_text > x2_text,
        CONDITIONS[1]: None if x2_fig is None or x1_fig is None else x2_fig > x1_fig,
        CONDITIONS[2]: None if x4_all is None else x4_all > 0,
        CONDITIONS[3]: None if x1_without is None or x1_with is None else x1_without < x1_with,
        "_기울기": {"x1 문자계": x1_text, "x2_whole 문자계": x2_text, "x1 도형계": x1_fig,
                 "x2_whole 도형계": x2_fig, "x4": x4_all, "x1 요부 없음": x1_without,
                 "x1 요부 있음": x1_with},
    }


def condition_rates(checks: list[dict]) -> dict[str, float | None]:
    out = {}
    for key in CONDITIONS:
        values = [c[key] for c in checks if c.get(key) is not None]
        out[key] = _round(sum(values) / len(values)) if values else None
    return out


def bootstrap_linear(method: str, X: np.ndarray, y: np.ndarray, weight: np.ndarray,
                     names: list[str], easy: np.ndarray, groups: np.ndarray, family: np.ndarray,
                     distinct: np.ndarray, hyper, *, rounds: int, seed: int) -> dict:
    """심결 사건 복원추출(쉬운 음성 고정) 부트스트랩: 계수 분포 + 판례 조건 성립 비율. (iv) 는
    x1_d×any_no_distinctive 계수(요부 없는 쌍의 x1 기울기 차) < 0 으로 condition_checks 가 잰다."""
    rng = np.random.default_rng(seed)
    trial_index = np.flatnonzero(~easy)
    easy_index = np.flatnonzero(easy)
    by_group: dict[str, list[int]] = {}
    for index in trial_index:
        by_group.setdefault(groups[index], []).append(index)
    group_keys = np.asarray(list(by_group))
    group_rows = {key: np.asarray(value) for key, value in by_group.items()}
    samples: list[np.ndarray] = []
    intercepts: list[float] = []
    checks: list[dict] = []
    for _ in range(rounds):
        chosen = rng.choice(group_keys, group_keys.size, replace=True)
        index = np.concatenate([group_rows[key] for key in chosen] + [easy_index])
        fitted = fit_method(method, X[index], y[index], weight[index], names, easy[index], hyper)
        samples.append(fitted.coef)
        intercepts.append(fitted.intercept)
        checks.append(condition_checks(fitted, X, family, ~easy, distinct))
    matrix = np.asarray(samples)
    table = {}
    for i, name in enumerate(names):
        column = matrix[:, i]
        table[name] = {"평균": _round(float(column.mean())),
                       "ci95": [_round(float(np.percentile(column, 2.5))),
                                _round(float(np.percentile(column, 97.5)))]}
    b = np.asarray(intercepts)
    table["intercept"] = {"평균": _round(float(b.mean())),
                          "ci95": [_round(float(np.percentile(b, 2.5))),
                                   _round(float(np.percentile(b, 97.5)))]}
    return {"rounds": rounds, "계수": table, "판례_조건_성립_비율": condition_rates(checks)}


# ---- 등급·단독 임계값·부분집합 -----------------------------------------------------------------

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
    thresholds = {"주의": _round(caution), "검토 권장": _round(review),
                  "위험": _round(risk)}
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
            "정밀도(등급 안 유사율)": _round(float(y[inside].mean())) if inside.any() else None,
            "재현율(이 등급 이상이 잡는 유사)": _round(float((y[at_least] == 1).sum() / n_pos))
            if n_pos else None,
        })
    return out


def standalone_thresholds(rows: list[dict], y: np.ndarray, mask: np.ndarray, *,
                          target: float = STANDALONE_PRECISION) -> dict:
    """③ 축별 정밀도 ≥ target 인 최소 점수 τ(지지 ≥ 10). 넘으면 등급 하한 "검토 권장". 없으면
    null."""
    out: dict = {}
    table: list[dict] = {}
    reasons: dict = {}
    table = []
    for axis in AXES:
        scores = np.asarray([row.get(axis, np.nan) for row in rows], dtype=np.float64)
        valid = mask & ~np.isnan(scores)
        result = precision_threshold(scores[valid], y[valid], target=target,
                                        min_support=MIN_SUPPORT)
        out[axis] = result["threshold"]
        best = result.get("최대_정밀도") or {}
        active = result["threshold"] is not None
        reasons[axis] = (
            f"τ {result['threshold']}: 정밀도 {result['precision']} 재현율 {result['recall']} "
            f"(점수 ≥ τ 인 쌍 {result['n_above']})" if active else
            f"비활성 — 지지 {MIN_SUPPORT} 이상에서 최대 정밀도 {best.get('precision')} "
            f"(t ≥ {best.get('threshold')}, n {best.get('n_above')}) < {target}"
        )
        table.append({"축": axis, "τ": result["threshold"], "정밀도": result["precision"],
                      "재현율": result["recall"], "지지_n": result["n_above"],
                      "최대_정밀도": best.get("precision"), "활성": active})
    return {"thresholds": out, "이유": reasons, "표": table, "목표_정밀도": target}


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


def distinctive_crosstab(rows: list[dict], y: np.ndarray, trial: np.ndarray) -> dict:
    """④ 요부 유무 × 라벨 교차표(심결, 이름 있는 행)."""
    out = {}
    for side in ("a", "b"):
        flags = np.asarray([int(row.get(f"has_distinctive_part_{side}") or 0) for row in rows])
        block = {}
        for value, label in ((1, "요부 있음"), (0, "요부 없음")):
            mask = trial & (flags == value)
            n = int(mask.sum())
            block[label] = {"n": n, "유사": int(y[mask].sum()),
                            "유사율": _round(float(y[mask].mean())) if n else None}
        out[f"has_distinctive_part_{side}"] = block
    both = np.asarray([int(row.get("has_distinctive_part_a") or 0) and
                       int(row.get("has_distinctive_part_b") or 0) for row in rows])
    block = {}
    for value, label in ((1, "둘 다 요부 있음"), (0, "한쪽이라도 요부 없음")):
        mask = trial & (both == value)
        n = int(mask.sum())
        block[label] = {"n": n, "유사": int(y[mask].sum()),
                        "유사율": _round(float(y[mask].mean())) if n else None}
    out["any_no_distinctive"] = block
    return out


# ---- 그림 --------------------------------------------------------------------------------------

def calibration_png(curves: dict[str, dict], path: Path) -> None:
    """신뢰도 곡선(예측 확률 구간 평균 대 관측 유사율), Pillow."""
    from PIL import Image, ImageDraw

    size, left, top, plot = 640, 70, 50, 520
    image = Image.new("RGB", (size + 60, size + 40), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = _font(14)
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


def ebm_shapes(model, names: list[str]) -> dict[str, list[dict]]:
    """EBM 주효과 형상 곡선: 축별 (구간 상한, 점수). 첫·끝 칸(결측·미관측)은 뺀다."""
    out: dict[str, list[dict]] = {}
    for term_index, term_name in enumerate(model.term_names_):
        if term_name not in names:
            continue
        feature_index = names.index(term_name)
        cuts = np.asarray(model.bins_[feature_index][0], dtype=np.float64)
        scores = np.asarray(model.term_scores_[term_index], dtype=np.float64)
        interior = scores[1:len(cuts) + 2] if scores.size >= cuts.size + 3 else scores
        edges = np.concatenate([[0.0], cuts, [1.0]])
        out[term_name] = [
            {"구간": f"{edges[i]:.2f}~{edges[i + 1]:.2f}", "점수": _round(float(interior[i]))}
            for i in range(min(interior.size, edges.size - 1))
        ]
    return out


def ebm_shape_png(shapes: dict[str, list[dict]], path: Path) -> None:
    """축별 형상 곡선(계단, 로짓 기여)을 한 그림에 — Pillow."""
    from PIL import Image, ImageDraw

    axes = [axis for axis in AXES if axis in shapes] or list(shapes)[:5]
    if not axes:
        return
    width, height, left, top = 300, 220, 50, 30
    image = Image.new("RGB", (width * len(axes) + 40, height + 70), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = _font(12)
    values = [c["점수"] for axis in axes for c in shapes[axis]]
    low, high = min(values + [0.0]), max(values + [0.0])
    span = (high - low) or 1.0
    for k, axis in enumerate(axes):
        x0 = 20 + k * width + left
        plot_w, plot_h = width - left - 20, height - top
        draw.rectangle((x0, top, x0 + plot_w, top + plot_h), outline=(120, 120, 120))
        zero_y = top + plot_h * (1 - (0.0 - low) / span)
        draw.line((x0, zero_y, x0 + plot_w, zero_y), fill=(200, 200, 200))
        bins = shapes[axis]
        for i, cell in enumerate(bins):
            lo_x = x0 + plot_w * i / len(bins)
            hi_x = x0 + plot_w * (i + 1) / len(bins)
            y = top + plot_h * (1 - (cell["점수"] - low) / span)
            draw.line((lo_x, y, hi_x, y), fill=(40, 90, 220), width=3)
        draw.text((x0, 8), f"{axis} (EBM 로짓 기여)", fill=(30, 30, 30), font=font)
        draw.text((x0, top + plot_h + 6), "0", fill=(60, 60, 60), font=font)
        draw.text((x0 + plot_w - 8, top + plot_h + 6), "1", fill=(60, 60, 60), font=font)
        draw.text((x0 - 45, top - 6), f"{high:.1f}", fill=(60, 60, 60), font=font)
        draw.text((x0 - 45, top + plot_h - 8), f"{low:.1f}", fill=(60, 60, 60), font=font)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def gbm_shap_summary(model, X: np.ndarray, names: list[str]) -> dict[str, float]:
    import shap

    values = np.asarray(shap.TreeExplainer(model).shap_values(X))
    if values.ndim == 3:  # (클래스, n, d) 형태면 양성 클래스
        values = values[-1]
    return {name: _round(float(np.mean(np.abs(values[:, i])))) for i, name in enumerate(names)}


# ---- 실행 --------------------------------------------------------------------------------------

def adopt(results: dict, baseline: str = "logistic", preferred: str = "prior") -> tuple[str, bool,
                                                                                        list[str]]:
    """채택 규칙: 심결 CV AUC 가 기준(logistic)의 95% CI 상한보다 높은 방법이 없으면
    preferred(사전분포·단조) 채택. 있으면 사람 결정(JSON 은 preferred 로 내보내되
    adoption_pending)."""
    base = results[baseline]["cv"]["심결"]
    upper = base["auc_ci95"][1] if base["auc_ci95"][1] is not None else base["auc"]
    better = [name for name, item in results.items()
              if name != baseline and item["cv"]["심결"]["auc"] is not None
              and item["cv"]["심결"]["auc"] > upper]
    notes = [f"기준 {baseline} 심결 AUC {base['auc']} (CI 상한 {upper})"]
    if better:
        notes.append(f"CI 밖으로 높은 방법 {better} — 채택은 사람 결정(JSON 은 {preferred} 로 둠)")
        return preferred, True, notes
    notes.append(f"CI 밖으로 높은 방법 없음 → {preferred}(판례 사전분포·단조 제약) 채택")
    return preferred, False, notes


def run(features_path: Path, easy_path: Path | None, *, out_dir: Path, model_path: Path,
        methods=DEFAULT_METHODS, c_grid=C_GRID, sigma_grid=SIGMA_GRID,
        estimators_grid=ESTIMATORS_GRID, w_easy: float = W_EASY, folds: int = FOLDS,
        repeats: int = REPEATS, bootstrap: int = BOOTSTRAP, seed: int = 0) -> dict:
    all_rows = load_rows(features_path, easy_path)
    y_all = labels_for(all_rows, "최종")
    rows = [row for row, label in zip(all_rows, y_all) if label >= 0]
    excluded = [row for row in rows if row["pair_source"] == "trial" and not has_name(row)]
    rows = [row for row in rows if row["pair_source"] != "trial" or has_name(row)]
    y = labels_for(rows, "최종").astype(np.float64)
    easy = np.asarray([row["pair_source"] != "trial" for row in rows])
    trial = ~easy
    groups = groups_for(rows)
    family = families(rows)
    weight = sample_weights(rows, w_easy)
    masks = set_masks(rows)
    distinct = np.asarray([
        bool(int(row.get("has_distinctive_part_a") or 0)) and
        bool(int(row.get("has_distinctive_part_b") or 0)) for row in rows
    ])
    n_trial, n_pos, n_neg = int(trial.sum()), int(y[trial].sum()), int((1 - y[trial]).sum())
    data_summary = {
        "라벨": "최종", "심결_행": n_trial, "유사": n_pos, "비유사": n_neg,
        "이름_없어_제외": {"행": len(excluded),
                      "유사": sum(1 for r in excluded if r["최종라벨"] == "유사"),
                      "비유사": sum(1 for r in excluded if r["최종라벨"] == "비유사")},
        "쉬운_음성": {name: int((np.asarray([r["pair_source"] for r in rows]) == name).sum())
                   for name in ("cross", "db")},
        "w_easy": w_easy, "입력": FEATURES, "제거_항": REMOVED_TERMS,
        "트리_입력(이미지 블록 제외)": TREE_FEATURES,
        "소수_클래스_대_입력(EPV)": _round(min(n_pos, n_neg) / len(FEATURES)),
    }
    results: dict[str, dict] = {}
    for method in methods:
        names = feature_names_for(method)
        X = design_matrix(rows, names)
        per_hyper = {}
        for hyper in hyper_grid(method, c_grid=c_grid, sigma_grid=sigma_grid,
                                estimators_grid=estimators_grid):
            prob, fold_models = cv_predictions(method, X, y, weight, names, easy, groups, hyper,
                                               folds=folds, repeats=repeats, seed=seed)
            per_hyper[hyper] = (prob, fold_models,
                                auc_block(prob, y, masks["심결"], seed=seed, bootstrap=0)["auc"])
        best = max(per_hyper, key=lambda h: per_hyper[h][2] or 0.0)
        prob, fold_models, _ = per_hyper[best]
        started = time.perf_counter()
        final = fit_method(method, X, y, weight, names, easy, best, seed=seed)
        elapsed = time.perf_counter() - started
        fold_checks = [condition_checks(fitted, X, family, trial, distinct)
                       for fitted, _ in fold_models]
        final_check = condition_checks(final, X, family, trial, distinct)
        item = {
            "method": method, "hyper": best, "features": names,
            "hyper_후보": {str(h): _round(per_hyper[h][2]) for h in per_hyper},
            "cv": {name: auc_block(prob, y, mask, seed=seed, bootstrap=bootstrap)
                   for name, mask in masks.items()},
            "calibration": {name: calibration(prob[mask], y[mask]) for name, mask in masks.items()
                            if name in ("심결", "심결+cross+db")},
            "학습_시간_초": _round(elapsed),
            "판례_조건(최종 적합)": {k: v for k, v in final_check.items() if k != "_기울기"},
            "로짓_기울기(최종 적합)": {k: (_round(v) if v is not None else None)
                               for k, v in final_check["_기울기"].items()},
            "판례_조건_겹_성립_비율": condition_rates(fold_checks),
            "_prob": prob, "_final": final, "_X": X,
        }
        if method in ("logistic", "prior"):
            item["계수"] = {name: round(float(value), 4) for name, value in zip(names, final.coef)}
            item["절편"] = round(final.intercept, 4)
            item["부트스트랩"] = bootstrap_linear(method, X, y, weight, names, easy, groups, family,
                                             distinct, best, rounds=bootstrap, seed=seed)
            item["해석"] = "계수(점수 1.0 당 로짓)"
        elif method == "ebm":
            shapes = ebm_shapes(final.model, names)
            item["형상_곡선"] = shapes
            ebm_shape_png(shapes, Path(out_dir) / "risk_model_v1_ebm_shapes.png")
            item["해석"] = "축별 형상 곡선(risk_model_v1_ebm_shapes.png)"
        elif method == "gbm":
            item["shap_평균절대값"] = gbm_shap_summary(final.model, X[trial], names)
            item["해석"] = "SHAP 기여도(평균 |SHAP|, 로짓)"
        results[method] = item
    adopted_method, pending, adopt_notes = adopt(results) if "logistic" in results and (
        "prior" in results) else (methods[0], False, ["기준·사전분포 둘 다 없어 첫 방법 사용"])
    adopted = results[adopted_method]
    names = adopted["features"]
    prob = adopted["_prob"]
    final = adopted["_final"]
    baselines = {
        name: {set_name: auc_block(scores, y, mask, seed=seed, bootstrap=bootstrap)
               for set_name, mask in masks.items()}
        for name, scores in baseline_scores(rows).items()
    }
    grades = {name: grade_thresholds(prob[mask], y[mask]) for name, mask in masks.items()
              if name in ("심결", "심결+cross+db")}
    standalone = standalone_thresholds(rows, y, trial)
    subsets = subset_performance(prob, y, rows, trial, seed=seed, bootstrap=bootstrap)
    crosstab = distinctive_crosstab(rows, y, trial)
    if adopted_method not in ("logistic", "prior"):
        raise ValueError("런타임은 선형 계수만 지원 — 채택 방법이 선형이어야 합니다")
    model = {
        "version": rm.MODEL_VERSION, "trained_at": date.today().isoformat(), "label": "최종",
        "method": "prior_monotone_logistic" if adopted_method == "prior" else "logistic_l2",
        "w_easy": w_easy, "hyper": adopted["hyper"],
        "removed_terms": REMOVED_TERMS,
        "prior": ({"mu": {name: PRIOR_MU[name] for name in names if name in PRIOR_MU},
                   "sigma": adopted["hyper"],
                   "applies_to": [name for name in names if name in PRIOR_MU],
                   "intercept_prior": False} if adopted_method == "prior" else None),
        "monotone": {"features": [n for n in MONOTONE_FEATURES if n in names],
                     "constraint": ("유사도 축 본체 ≥ 0; x2_whole 본체 + 도형계 교호작용 ≥ 0; "
                                    "x1 본체 + {문자계, 요부없음} 교호작용 모든 조합 ≥ 0")}
        if adopted_method == "prior" else None,
        "figure_rule": {"threshold": FIGURE_X2_THRESHOLD, "caveat": FIGURE_CAVEAT,
                        "validated": False,
                        "basis": ("97후3050 후단(한 축의 유사로 혼동 우려) — 도형계 쌍 17 로 "
                                  "데이터 검증 불가, 제품 규칙(미검증). 도형계 입력은 "
                                  "figure_caveat True")},
        "features": names,
        "coefficients": {name: round(float(value), 4) for name, value in zip(names, final.coef)},
        "intercept": round(final.intercept, 4),
        "grade_thresholds": grades["심결+cross+db"]["thresholds"],
        "grade_basis": ("심결+cross+db OOF 확률(위험 정밀도 ≥ 0.8, 검토 권장 재현율 ≥ 0.9, "
                        "안전/주의 등분)"),
        "standalone_thresholds": standalone["thresholds"],
        "standalone_precision": STANDALONE_PRECISION,
        "standalone_reason": standalone["이유"],
        "meta": {
            "n_trial": n_trial, "n_pos": n_pos, "n_neg": n_neg,
            "n_excluded_no_name": len(excluded), "n_easy": int(easy.sum()),
            "folds": folds, "repeats": repeats, "bootstrap": bootstrap,
            "cv_auc": {name: block["auc"] for name, block in adopted["cv"].items()},
            "cv_auc_ci95": {name: block["auc_ci95"] for name, block in adopted["cv"].items()},
            "brier": {name: block["brier"] for name, block in adopted["calibration"].items()},
            "comparison_cv_auc": {name: item["cv"]["심결"]["auc"]
                                  for name, item in results.items()},
            "adoption_notes": adopt_notes, "adoption_pending": pending,
            "feature_definitions": (
                "축 점수 0~1(결측 0 + miss_*=1; x3_d 는 has_meaning_both False 면 결측), "
                "any_no_distinctive = 1 − has_distinctive_part_a·b, 교호작용 x1_d×문자계(문자·"
                "결합-문자요부·미상·결합)·x2_whole×도형계(도형·결합-도형요부)·"
                "x1_d×any_no_distinctive. "
                "유형 주효과·miss_x1·miss_x2text·요부 플래그 2개 없음. 표준화 없음."
            ),
        },
    }
    rm.validate_model(model)
    model_path = Path(model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    calibration_png(adopted["calibration"], out_dir / "risk_model_v1_calibration.png")
    summary = {
        "기준일": date.today().isoformat(), "데이터": data_summary,
        "방법": {name: {k: v for k, v in item.items() if not k.startswith("_")}
               for name, item in results.items()},
        "채택": {"method": adopted_method, "pending": pending, "규칙": adopt_notes,
               "hyper": adopted["hyper"]},
        "기준선": baselines, "등급": grades, "단독_임계값": standalone, "부분집합": subsets,
        "요부_교차표": crosstab, "모델_파일": str(model_path),
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


def _rate(value) -> str:
    return "평가 불가" if value is None else f"{value:.2f}"


def report_text(summary: dict) -> str:
    data = summary["데이터"]
    lines = [f"# 통합 모델 v1.2 학습 보고 ({summary['기준일']})", ""]
    lines.append(f"- 라벨 최종 · 심결 {data['심결_행']}행(유사 {data['유사']}·비유사 "
                 f"{data['비유사']}; 이름 없어 제외 {data['이름_없어_제외']['행']}행) · 쉬운 음성 "
                 f"cross "
                 f"{data['쉬운_음성']['cross']}·db {data['쉬운_음성']['db']} (w_easy "
                 f"{data['w_easy']}) · 입력 {len(data['입력'])}개 · 제거 항 {data['제거_항']} · "
                 f"EPV {data['소수_클래스_대_입력(EPV)']}")
    lines += ["", "## 방법 비교 (같은 입력·사건 단위 CV·w_easy 0.5)", "",
              "| 방법 | 하이퍼 | 심결 AUC | 심결+cross | 심결+cross+db | Brier 심결/현실 | "
              "판례 (i)/(ii)/(iii)/(iv) 겹 성립 | 학습 시간 | 해석 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for name, item in summary["방법"].items():
        cv, cal, rates = item["cv"], item["calibration"], item["판례_조건_겹_성립_비율"]
        lines.append(
            f"| {name} | {item['hyper']} | {_auc(cv['심결'])} | {_auc(cv['심결+cross'])} | "
            f"{_auc(cv['심결+cross+db'])} | {cal['심결']['brier']} / "
            f"{cal['심결+cross+db']['brier']} | "
            f"{' / '.join(_rate(rates[k]) for k in CONDITIONS)} | {item['학습_시간_초']}s | "
            f"{item['해석']} |")
    adopted = summary["채택"]
    pending = ", 사람 결정 대기" if adopted["pending"] else ""
    lines += ["", f"채택: **{adopted['method']}** (하이퍼 {adopted['hyper']}{pending}) — "
              + " · ".join(adopted["규칙"]), ""]
    lines += ["## 기준선", "", "| 기준선 | 심결 | 심결+cross | 심결+cross+db |",
              "|---|---|---|---|"]
    for name, block in summary["기준선"].items():
        lines.append(f"| {name} | {_auc(block['심결'])} | {_auc(block['심결+cross'])} | "
                     f"{_auc(block['심결+cross+db'])} |")
    for name, item in summary["방법"].items():
        lines += ["", f"## {name} — 세부", "",
                  f"- 하이퍼 후보(심결 CV AUC): {item['hyper_후보']}",
                  f"- 로짓 기울기(최종 적합, 0 → 1): {item['로짓_기울기(최종 적합)']}",
                  f"- 판례 조건(최종 적합): {item['판례_조건(최종 적합)']}"]
        if "계수" in item:
            boot = item["부트스트랩"]
            lines += ["", f"| 항 | 계수 | 부트스트랩 {boot['rounds']}회 평균 | 95% 구간 |",
                      "|---|---|---|---|", f"| intercept | {item['절편']} | — | — |"]
            for term, value in item["계수"].items():
                b = boot["계수"][term]
                lines.append(f"| {term} | {value} | {b['평균']} | {b['ci95'][0]} ~ "
                             f"{b['ci95'][1]} |")
            b = boot["계수"]["intercept"]
            lines.append(f"| intercept(부트스트랩) | — | {b['평균']} | {b['ci95'][0]} ~ "
                         f"{b['ci95'][1]} |")
            lines += ["", "부트스트랩 판례 조건 성립 비율: " + ", ".join(
                f"{k} {_rate(v)}" for k, v in boot["판례_조건_성립_비율"].items())]
        if "형상_곡선" in item:
            lines.append("")
            for axis, cells in item["형상_곡선"].items():
                lines.append(f"- {axis}: " + ", ".join(f"{c['구간']} {c['점수']}" for c in cells))
        if "shap_평균절대값" in item:
            lines += ["", "| 항 | 평균 \\|SHAP\\|(로짓) |", "|---|---|"]
            for term, value in sorted(item["shap_평균절대값"].items(), key=lambda kv: -kv[1]):
                lines.append(f"| {term} | {value} |")
    lines += ["", "## 등급 임계값 (채택 모델 OOF)", ""]
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
    standalone = summary["단독_임계값"]
    lines += [f"## 단독 임계값 (축별 정밀도 ≥ {standalone['목표_정밀도']}, 심결 최종 라벨 — 넘으면 "
              "등급 하한 검토 권장)", "",
              "| 축 | τ | 정밀도 | 재현율 | 지지 n | 최대 정밀도 | 활성 |",
              "|---|---|---|---|---|---|---|"]
    for row in standalone["표"]:
        lines.append(f"| {row['축']} | {row['τ']} | {row['정밀도']} | {row['재현율']} | "
                     f"{row['지지_n']} | {row['최대_정밀도']} | "
                     f"{'활성' if row['활성'] else '비활성'} |")
    lines += ["", "## 요부 유무 × 라벨 (심결, 이름 있는 행)", "",
              "| 항 | 요부 있음 n(유사·유사율) | 요부 없음 n(유사·유사율) |", "|---|---|---|"]
    for term, block in summary["요부_교차표"].items():
        keys = list(block)
        a, b = block[keys[0]], block[keys[1]]
        lines.append(f"| {term} | {keys[0]} {a['n']} ({a['유사']}·{a['유사율']}) | "
                     f"{keys[1]} {b['n']} ({b['유사']}·{b['유사율']}) |")
    lines += ["", "## 부분집합 (심결, 채택 모델 OOF)", ""]
    for title, block in summary["부분집합"].items():
        lines += [f"### {title}", "", "| 수준 | AUC |", "|---|---|"]
        for level, item in block.items():
            lines.append(f"| {level} | {_auc(item)} |")
        lines.append("")
    lines.append(f"모델 파일: {summary['모델_파일']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--easy", type=Path, default=DEFAULT_EASY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--methods", default=",".join(DEFAULT_METHODS),
                        help="쉼표 구분: logistic,prior,ebm,gbm (ebm·gbm 은 실험 의존성 필요)")
    parser.add_argument("--w-easy", type=float, default=W_EASY)
    parser.add_argument("--folds", type=int, default=FOLDS)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--bootstrap", type=int, default=BOOTSTRAP)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    methods = tuple(m.strip() for m in args.methods.split(",") if m.strip())
    unknown = [m for m in methods if m not in METHODS]
    if unknown:
        parser.error(f"모르는 방법 {unknown} (가능: {METHODS})")
    summary = run(args.features, args.easy, out_dir=args.out_dir, model_path=args.model,
                  methods=methods, w_easy=args.w_easy, folds=args.folds, repeats=args.repeats,
                  bootstrap=args.bootstrap, seed=args.seed)
    print(report_text(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
