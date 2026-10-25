"""통합 모델 v1.3 학습 — 심결례 정답 데이터(`pairs_features.csv`) + 쉬운
음성(`pairs_features_easy.csv`)으로 4축 결합 방법을 비교하고 판례 사전분포 + 단조 제약 로지스틱을
채택한다(통합 모델 설계 §3·§4-3·§7·§7-1·§7-2·§7-3). KIPRIS 호출 0, 서비스 코드 미접촉.
산출물은 계수 JSON(`shared/model/risk_model_v1.json`, version
risk_model_v1.3)·보고서(`ml/data/trials/risk_model_v1_report.md`·`_results.json`)·신뢰도
곡선·EBM 형상 곡선 PNG.

v1.3(§7-3) — "입력을 더 주면 위험도가 내려가는" 결측 편향 제거:
  ① 쉬운 음성 쌍에도 x2_whole 이 있다(pairs_features.py --fill-easy-images: cross 는 심결 추출
     이미지, db 는 서비스 색인 벡터). 그래서 이미지 블록을 심결 행만으로 맞추던 2단계
     오프셋(fit_linear 의 image_offset)은 패턴 학습에서 쓰지 않는다.
  ② 결측 지시변수(miss_x2img·miss_x3·miss_x4) 대신 **결측 패턴별 계수 집합**: 패턴 축(기본
     x2_whole·x4)의 관측 조합(base / x2_whole / x4 / x2_whole+x4)마다 그 축들이 관측된 모든 행으로
     계수 집합을 적합한다(하위 패턴은 상위 패턴 행도 쓴다 — 축을 빼고 보면 되므로). X3 는 게이트
     결측이라 값 0, 지시변수 없음. 패턴마다 소수 클래스(심결+쉬운 음성)가 MIN_PATTERN_MINORITY
     미만이면 축을 하나 줄인다(이미지만 → 패턴 없음).
  ③ 결합 제약(prior 방법): 네 계수 집합을 한 SLSQP 로 풀면서 "축 하나를 하한값(쉬운 음성 비유사 쌍
     평균 — 현실 분포에서 '보통의 서로 다른 상표' 수준)으로 더 관측해도 로짓이 내려가지 않음"을
     설계 항 상자의 모든 꼭짓점(rm.coupling_vertices)에서 선형 제약으로 건다. 런타임은 적재 때 같은
     제약을 검증(rm.coupling_violations) — 입력을 더 주면 p 가 내려가지 않는다는 보장.
  JSON: pattern_axes·patterns[키]{features, coefficients, intercept, meta}·reference_pattern(모든
  축 관측, 최상위 features·coefficients·intercept 는 그 집합)·coupling{floors}. 등급 임계값은
  행마다 자기 패턴의 OOF 확률을 모은 뒤(심결+cross+db) v1.2.1 과 같은 규칙으로. 참고로 v1.2.1
  구조(지시변수)에 ①만 적용한 모델도 적합해 meta.indicator_reference 에 둔다(원인 확인용).

    ml/venv/bin/python ml/scripts/train_risk_model.py                  # 로지스틱 + 사전분포(기본)
    ml/venv/bin/python ml/scripts/train_risk_model.py --methods logistic,prior,ebm,gbm
        # EBM·GBM 은 ml/requirements-experiments.txt 설치 뒤(pip install -c constraints.txt -r …)
    ml/venv/bin/python ml/scripts/train_risk_model.py --bootstrap 50 --repeats 1   # 빠른 확인

v1.1 입력(§7-1 ① 편향 제거): x1_d·x2_text_d·x2_whole·x3_d·x4, has_distinctive_part_a/b,
교호작용 x1_d×문자계·x2_whole×도형계. 상표 유형 주효과(type_*)와 miss_x1·miss_x2text 는 뺐고
상대 이름이 없는 심결 행은 학습에서 제외한다 — 유형은 "어느 축을 보느냐"만 바꾸고(교호작용), 이름
없음은 서비스에 없는 상황이다. 표준화 없음(계수 = 점수 1.0 당 로짓). v1.2(§7-2): 절편은 사전분포
없이 자유, 요부 플래그는 `any_no_distinctive` + x1_d×any_no_distinctive(사전평균 −0.5, 2000후2453),
단조 제약은 x1 효과의 모든 조합 ≥ 0, 도형 규칙(figure_rule)은 미검증 제품 규칙으로 JSON 에만 기록.

방법(같은 입력·같은 사건 단위 5겹×3반복 CV·같은 쉬운 음성 가중치 w_easy 0.5):
  1. logistic — 패턴마다 독립 L2 로지스틱(½‖w‖² + C·Σ s·logloss, scipy L-BFGS), C 는 CV.
     결합 제약 없음(기준).
  2. prior — 판례 사전분포 + 단조 제약 + 결합 제약 로지스틱(MAP, SLSQP): 계수마다 N(μ_j, σ²)(μ:
     x1 1.0·x1×문자계 +1.0, x2_whole 0.5·x2_whole×도형계 +1.0, x2_text 0.5, x3 0.5, x4 1.0, 요부
     교호작용 −0.5; σ 1.0 고정), 유사도 축 본체 ≥ 0 과 본체 + 교호작용 ≥ 0.
  3. ebm — interpret ExplainableBoostingClassifier(max_bins 16, interactions 3, 강한 정규화) —
     지시변수 입력(TREE_FEATURES), 비교 전용.
  4. gbm — lightgbm(num_leaves 4, max_depth 2, n_estimators CV, 유사도 축 단조 +1) + SHAP — 비교
     전용.
  판례 4조건은 모든 방법에서 로짓 부분의존 기울기(축을 0 → 1 로 올렸을 때 로짓 변화의 부분집합
  평균)로 잰다 — 선형 모델에서는 계수(합)와 같다(패턴 모델은 모든 축을 관측한 집합으로). 채택 규칙:
  심결 CV AUC 가 기준(logistic)보다 CI 밖으로 높은 방법이 없으면 2 를 채택(변별력이 같으면 판례
  일관성·안전성 우선), 있으면 보고하고 채택은 사람이.
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
# σ: v1.1·v1.2 의 CV 격자 {0.5, 1, 2} 는 심결 AUC 차이가 0.006 안(CI 겹침)으로 무차별이라 v1.2.1
# 부터 설계 원칙대로 중간값 1.0 고정(JSON meta.sigma_fixed). 격자를 다시 보려면 run(sigma_grid=…).
SIGMA_GRID = (1.0,)
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
# 위험 등급의 최소 지지: v1.2 는 10 이라 정밀도 0.8 을 채우는 p 0.899 위에 11쌍(재현율 0.05)만 남아
# 경고 기능이 없었다(설계 §7-2). v1.2.1 부터 30 — 미달이면 대체값(검토 권장 하한과 1.0 의 중간).
RISK_MIN_SUPPORT = 30
# v1.2.1 입력(지시변수 구조) — 트리 방법·참고 지시변수 모델·fit_linear 테스트가 쓴다.
FEATURES = [
    "x1_d", "x2_text_d", "x2_whole", "x3_d", "x4",
    "miss_x2img", "miss_x3", "miss_x4",
    "any_no_distinctive",
    "x1_d×문자계", "x2_whole×도형계", "x1_d×any_no_distinctive",
]
REMOVED_TERMS = ["type_도형", "type_결합-문자요부", "type_결합-도형요부", "miss_x1", "miss_x2text",
                 "has_distinctive_part_a", "has_distinctive_part_b"]  # 뒤 둘은 v1.2 에서 대체
# v1.3 결측 패턴: 패턴 축의 관측 조합마다 계수 집합. 공통 항 + 관측된 축의 항(+ 패턴으로 가르지 않는
# 축은 값 + 지시변수 — 폴백).
PATTERN_AXES = ("x2_whole", "x4")
PATTERN_BASE = ["x1_d", "x2_text_d", "x3_d", "any_no_distinctive", "x1_d×문자계",
                "x1_d×any_no_distinctive"]
PATTERN_AXIS_TERMS = {"x2_whole": ["x2_whole", "x2_whole×도형계"], "x4": ["x4"]}
MIN_PATTERN_MINORITY = 50  # 패턴마다 소수 클래스(심결+쉬운 음성)가 이 미만이면 패턴 축을 줄인다
FLOOR_BASIS = ("쉬운 음성(cross·db, 현실 분포) 비유사 쌍 평균 — 심결 비유사는 다툼이 있던 경계 "
               "쌍이라 '보통의 서로 다른 상표'보다 비슷하다")
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
COUPLING_TOLERANCE = 1e-9


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


def observed(rows: list[dict], axis: str) -> np.ndarray:
    """축 점수가 관측된 행(NaN 이 아님)."""
    return np.asarray([
        not (row.get(axis) is None or (isinstance(row.get(axis), float)
                                      and np.isnan(row.get(axis)))) for row in rows
    ])


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
               *, method: str, hyper: float, image_offset: bool = True) -> tuple[np.ndarray, float]:
    """지시변수 구조(FEATURES) 단일 모델. image_offset(≤ v1.2.1 방식): 심결 행만으로 전체 적합
    (1단계) → 쉬운 음성이 있으면 이미지 블록을 고정하고 나머지를 다시 적합(2단계).
    image_offset=False 면 모든 행을 한 번에 적합(쉬운 음성에 이미지 축이 있을 때 — v1.3 참고
    지시변수 모델)."""
    fitter = fit_logistic if method == "logistic" else None
    trial = ~easy

    def fit(Xs, ys, ws, sub_names, offset=None):
        if method == "logistic":
            return fitter(Xs, ys, ws, hyper, offset=offset)
        return fit_prior(Xs, ys, ws, sub_names, hyper, offset=offset)

    if not image_offset:
        return fit(X, y, weight, names)
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


# ---- v1.3 결측 패턴 ----------------------------------------------------------------------------

def pattern_features(key: str, pattern_axes) -> list[str]:
    """패턴 키의 입력 항: 공통 항 + 관측된 패턴 축의 항. 패턴으로 가르지 않는 축(폴백)은 값 +
    지시변수."""
    present = rm.pattern_present(key)
    names = list(PATTERN_BASE)
    for axis in PATTERN_AXES:
        if axis in present:
            names += PATTERN_AXIS_TERMS[axis]
        elif axis not in pattern_axes:
            names += PATTERN_AXIS_TERMS[axis] + [MISS_OF[axis]]
    return names


def row_pattern_keys(rows: list[dict], pattern_axes) -> np.ndarray:
    """행마다 자기 결측 패턴 키(관측된 패턴 축의 조합) — 서비스가 그 입력에 고를 계수 집합."""
    flags = {axis: observed(rows, axis) for axis in pattern_axes}
    return np.asarray([
        rm.pattern_key([axis for axis in pattern_axes if flags[axis][i]], pattern_axes)
        for i in range(len(rows))
    ])


def pattern_masks(rows: list[dict], pattern_axes) -> dict[str, np.ndarray]:
    """패턴 키 → 그 패턴의 축이 모두 관측된 행(하위 패턴은 상위 패턴 행도 포함)."""
    flags = {axis: observed(rows, axis) for axis in pattern_axes}
    out = {}
    for key in rm.pattern_keys(pattern_axes):
        mask = np.ones(len(rows), dtype=bool)
        for axis in rm.pattern_present(key):
            mask &= flags[axis]
        out[key] = mask
    return out


def choose_pattern_axes(rows: list[dict], y: np.ndarray, *,
                        min_minority: int = MIN_PATTERN_MINORITY) -> tuple[tuple[str, ...], dict]:
    """패턴 축 결정: 이미지×상품 4패턴 → 소수 클래스(심결+쉬운 음성) < min_minority 인 패턴이 있으면
    이미지만 2패턴 → 그래도 안 되면 패턴 없음(지시변수 구조). 시도별 집계를 함께 돌려준다."""
    attempts = []
    for axes in (PATTERN_AXES, PATTERN_AXES[:1], ()):
        counts = {}
        feasible = True
        for key, mask in pattern_masks(rows, axes).items():
            pos, neg = int((y[mask] == 1).sum()), int((y[mask] == 0).sum())
            counts[key] = {"n": int(mask.sum()), "유사": pos, "비유사": neg}
            feasible &= min(pos, neg) >= min_minority
        attempts.append({"축": list(axes), "패턴": counts, "가능": feasible})
        if feasible:
            return tuple(axes), {"기준": f"패턴마다 소수 클래스 ≥ {min_minority}", "시도": attempts}
    return (), {"기준": f"패턴마다 소수 클래스 ≥ {min_minority}", "시도": attempts}


def dissimilar_floors(rows: list[dict], y: np.ndarray, easy: np.ndarray,
                      pattern_axes) -> tuple[dict[str, float], dict]:
    """결합 제약 하한: 축마다 쉬운 음성(현실 분포) 비유사 쌍의 평균(FLOOR_BASIS). 쉬운 음성에 관측이
    없으면 심결 비유사 평균, 그것도 없으면 0. 참고로 심결 비유사·전체 비유사 평균도 함께."""
    floors, detail = {}, {}
    for axis in pattern_axes:
        values = np.asarray([row.get(axis, np.nan) for row in rows], dtype=np.float64)
        seen = ~np.isnan(values) & (y == 0)
        easy_mean = float(values[seen & easy].mean()) if (seen & easy).any() else None
        trial_mean = float(values[seen & ~easy].mean()) if (seen & ~easy).any() else None
        all_mean = float(values[seen].mean()) if seen.any() else None
        if easy_mean is not None:
            floor, basis = easy_mean, "쉬운 음성 비유사 평균"
        elif trial_mean is not None:
            floor, basis = trial_mean, "심결 비유사 평균(쉬운 음성에 관측 없음)"
        else:
            floor, basis = 0.0, "관측 없음 → 0"
        floors[axis] = round(floor, 4)
        detail[axis] = {
            "하한": floors[axis], "근거": basis, "쉬운_음성_비유사_평균": _round(easy_mean),
            "심결_비유사_평균": _round(trial_mean), "전체_비유사_평균": _round(all_mean),
            "쉬운_음성_관측_n": int((seen & easy).sum()),
        }
    return floors, detail


class PatternDesign:
    """패턴별 설계행렬·행 마스크·자기 패턴 키·공동 매개변수 θ 의 블록 위치."""

    def __init__(self, rows: list[dict], pattern_axes):
        self.axes = tuple(pattern_axes)
        self.keys = rm.pattern_keys(self.axes)
        self.full = self.keys[-1]  # 모든 패턴 축 관측(기준 패턴)
        self.names = {key: pattern_features(key, self.axes) for key in self.keys}
        self.X = {key: design_matrix(rows, self.names[key]) for key in self.keys}
        self.mask = pattern_masks(rows, self.axes)
        self.own = row_pattern_keys(rows, self.axes)
        self.offset: dict[str, int] = {}
        self.size = 0
        for key in self.keys:
            self.offset[key] = self.size
            self.size += len(self.names[key]) + 1

    def block(self, theta: np.ndarray, key: str) -> tuple[np.ndarray, float]:
        start, d = self.offset[key], len(self.names[key])
        return theta[start:start + d], float(theta[start + d])

    def split(self, theta: np.ndarray) -> dict[str, tuple[np.ndarray, float]]:
        return {key: self.block(theta, key) for key in self.keys}

    def logit(self, fitted: dict, key: str, index: np.ndarray) -> np.ndarray:
        coef, intercept = fitted[key]
        return self.X[key][index] @ coef + intercept

    def own_prob(self, fitted: dict, index: np.ndarray) -> np.ndarray:
        """행마다 자기 패턴의 계수 집합으로 낸 확률(서비스와 같은 선택)."""
        out = np.empty(len(index))
        own = self.own[index]
        for key in self.keys:
            where = own == key
            if where.any():
                out[where] = expit(self.logit(fitted, key, index[where]))
        return out


def monotone_rows(design: PatternDesign) -> np.ndarray:
    """패턴마다 단조 제약(monotone_constraints)을 θ 전체 길이로 — 블록 대각."""
    rows = []
    for key in design.keys:
        for g in monotone_constraints(design.names[key]):
            row = np.zeros(design.size)
            start = design.offset[key]
            row[start:start + len(g)] = g
            rows.append(row)
    return np.asarray(rows) if rows else np.zeros((0, design.size))


def coupling_rows(design: PatternDesign, floors: dict[str, float]) -> np.ndarray:
    """결합 제약 A·θ ≥ 0: 상위 패턴(축 하나 더 관측, 그 축 = 하한값)의 로짓 − 하위 패턴의 로짓
    ≥ 0 을 설계 항 상자의 모든 꼭짓점(rm.coupling_vertices)에서."""
    rows = []
    for key in design.keys:
        present = rm.pattern_present(key)
        for axis in present:
            lower_key = rm.pattern_key([a for a in present if a != axis], design.axes)
            for vertex in rm.coupling_vertices(design.names[lower_key]):
                row = np.zeros(design.size)
                high = rm.design_vector({**vertex, axis: floors[axis]}, design.names[key])
                low = rm.design_vector(vertex, design.names[lower_key])
                start = design.offset[key]
                row[start:start + len(high)] += high
                row[start + len(high)] += 1.0
                start = design.offset[lower_key]
                row[start:start + len(low)] -= low
                row[start + len(low)] -= 1.0
                rows.append(row)
    return np.asarray(rows) if rows else np.zeros((0, design.size))


def _select(index: np.ndarray, mask: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """index(중복 허용 — 부트스트랩) 중 mask 와 가중치 > 0 인 것."""
    index = np.asarray(index)
    return index[mask[index] & (weight[index] > 0)]


def fit_patterns_prior(design: PatternDesign, y: np.ndarray, weight: np.ndarray,
                       index: np.ndarray, sigma: float, floors: dict[str, float], *,
                       mu: dict[str, float] | None = None) -> dict[str, tuple[np.ndarray, float]]:
    """모든 패턴의 계수 집합을 한 번에: Σ_패턴 [사전분포 벌점 + Σ s·logloss(그 패턴 축이 관측된
    행)] 을 단조 제약(패턴마다) + 결합 제약(패턴 사이) 아래 SLSQP 로 최소화."""
    mu_map = mu or PRIOR_MU
    blocks = []
    start = np.zeros(design.size)
    for key in design.keys:
        rows_index = _select(index, design.mask[key], weight)
        names = design.names[key]
        mu_vector = np.asarray([mu_map.get(name, 0.0) for name in names])
        precision = np.asarray([1.0 / (sigma * sigma) if name in mu_map else 0.0
                                for name in names])
        offset = design.offset[key]
        start[offset:offset + len(names)] = mu_vector
        blocks.append((design.X[key][rows_index], y[rows_index], weight[rows_index], mu_vector,
                       precision, offset))

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        value = 0.0
        gradient = np.zeros_like(theta)
        for X, yy, ww, mu_vector, precision, offset in blocks:
            d = X.shape[1]
            coef, b = theta[offset:offset + d], theta[offset + d]
            z = X @ coef + b
            loss = np.logaddexp(0.0, z) - yy * z
            diff = coef - mu_vector
            value += 0.5 * float(np.sum(precision * diff * diff)) + float(np.sum(ww * loss))
            residual = ww * (expit(z) - yy)
            gradient[offset:offset + d] = precision * diff + X.T @ residual
            gradient[offset + d] = float(residual.sum())
        return value, gradient

    G = np.vstack([monotone_rows(design), coupling_rows(design, floors)])
    constraints = ([{"type": "ineq", "fun": lambda t: G @ t, "jac": lambda t: G}]
                   if G.shape[0] else [])
    result = minimize(objective, start, jac=True, method="SLSQP", constraints=constraints,
                      options={"maxiter": 2000, "ftol": 1e-12})
    theta = result.x
    if G.shape[0]:
        theta = _project_feasible(theta, G)
    return design.split(theta)


def fit_patterns_logistic(design: PatternDesign, y: np.ndarray, weight: np.ndarray,
                          index: np.ndarray, C: float) -> dict[str, tuple[np.ndarray, float]]:
    """패턴마다 독립 L2 로지스틱(기준 방법 — 제약 없음)."""
    out = {}
    for key in design.keys:
        rows_index = _select(index, design.mask[key], weight)
        out[key] = fit_logistic(design.X[key][rows_index], y[rows_index], weight[rows_index], C)
    return out


def fit_patterns(method: str, design: PatternDesign, y: np.ndarray, weight: np.ndarray,
                 index: np.ndarray, hyper, floors: dict[str, float]) -> dict:
    if method == "prior":
        return fit_patterns_prior(design, y, weight, index, float(hyper), floors)
    if method == "logistic":
        return fit_patterns_logistic(design, y, weight, index, float(hyper))
    raise ValueError(f"패턴 적합은 선형 방법만: {method}")


def full_fitted(design: PatternDesign, fitted: dict, method: str) -> "Fitted":
    """기준 패턴(모든 축 관측) 계수 집합을 Fitted 로 — 판례 조건·기울기 계산용."""
    coef, intercept = fitted[design.full]
    return Fitted(method, design.names[design.full], coef=coef, intercept=intercept)


def cv_patterns(method: str, design: PatternDesign, y: np.ndarray, weight: np.ndarray,
                groups: np.ndarray, hyper, floors: dict[str, float], *, folds: int, repeats: int,
                seed: int) -> tuple[np.ndarray, dict[str, np.ndarray], list]:
    """사건 단위 반복 교차검증: 행마다 자기 패턴의 OOF 확률(반복 평균), 패턴별 OOF 확률(모든 행에
    그 패턴의 계수 집합을 적용 — 적용 가능 행만 평가에 쓴다), 겹 모델 목록."""
    own_total = np.zeros(y.size)
    per_total = {key: np.zeros(y.size) for key in design.keys}
    fold_fits = []
    for repeat in range(repeats):
        for train, test in folds_for(y, groups, folds=folds, seed=seed + repeat):
            fitted = fit_patterns(method, design, y, weight, train, hyper, floors)
            own_total[test] += design.own_prob(fitted, test)
            for key in design.keys:
                per_total[key][test] += expit(design.logit(fitted, key, test))
            fold_fits.append((fitted, test))
    return own_total / repeats, {k: v / repeats for k, v in per_total.items()}, fold_fits


def bootstrap_patterns(method: str, design: PatternDesign, y: np.ndarray, weight: np.ndarray,
                       groups: np.ndarray, easy: np.ndarray, family: np.ndarray,
                       distinct: np.ndarray, hyper, floors: dict[str, float], *, rounds: int,
                       seed: int) -> dict:
    """심결 사건 복원추출(쉬운 음성 고정) 부트스트랩: 패턴별 계수 분포 + 기준 패턴의 판례 조건 성립
    비율."""
    rng = np.random.default_rng(seed)
    trial_index = np.flatnonzero(~easy)
    easy_index = np.flatnonzero(easy)
    by_group: dict[str, list[int]] = {}
    for index in trial_index:
        by_group.setdefault(groups[index], []).append(index)
    group_keys = np.asarray(list(by_group))
    group_rows = {key: np.asarray(value) for key, value in by_group.items()}
    samples = {key: [] for key in design.keys}
    intercepts = {key: [] for key in design.keys}
    checks: list[dict] = []
    for _ in range(rounds):
        chosen = rng.choice(group_keys, group_keys.size, replace=True)
        index = np.concatenate([group_rows[key] for key in chosen] + [easy_index])
        fitted = fit_patterns(method, design, y, weight, index, hyper, floors)
        for key in design.keys:
            samples[key].append(fitted[key][0])
            intercepts[key].append(fitted[key][1])
        checks.append(condition_checks(full_fitted(design, fitted, method), design.X[design.full],
                                       family, ~easy, distinct))
    tables = {}
    for key in design.keys:
        matrix = np.asarray(samples[key])
        table = {}
        for i, name in enumerate(design.names[key]):
            column = matrix[:, i]
            table[name] = {"평균": _round(float(column.mean())),
                           "ci95": [_round(float(np.percentile(column, 2.5))),
                                    _round(float(np.percentile(column, 97.5)))]}
        b = np.asarray(intercepts[key])
        table["intercept"] = {"평균": _round(float(b.mean())),
                              "ci95": [_round(float(np.percentile(b, 2.5))),
                                       _round(float(np.percentile(b, 97.5)))]}
        tables[key] = table
    return {"rounds": rounds, "계수": tables[design.full], "패턴": tables,
            "판례_조건_성립_비율": condition_rates(checks)}


def monotonicity_report(design: PatternDesign, fitted: dict, rows: list[dict],
                        floors: dict[str, float]) -> dict:
    """결합 제약 검사(학습 행): 축 하나를 더 관측한 패턴과 그렇지 않은 패턴의 로짓 차 — 실제 값이
    하한 이상인 행에서 음수면 위반(제약이 맞으면 0건), 하한 미만인 행은 내려갈 수 있다(음의 증거).
    하한값을 대입한 차의 최소도 함께(꼭짓점 제약의 데이터 확인)."""
    out = {}
    for key in design.keys:
        present = rm.pattern_present(key)
        for axis in present:
            lower_key = rm.pattern_key([a for a in present if a != axis], design.axes)
            index = np.flatnonzero(design.mask[key])
            if index.size == 0:
                continue
            values = np.asarray([rows[i][axis] for i in index], dtype=np.float64)
            delta = design.logit(fitted, key, index) - design.logit(fitted, lower_key, index)
            floor_rows = np.asarray([
                rm.design_vector({**row_features(rows[i]), axis: floors[axis]}, design.names[key])
                for i in index
            ])
            coef, intercept = fitted[key]
            delta_floor = (floor_rows @ coef + intercept) - design.logit(fitted, lower_key, index)
            above = values >= floors[axis]
            out[f"{lower_key} → {key} ({axis})"] = {
                "하한": floors[axis], "n": int(index.size),
                "하한_이상": {
                    "n": int(above.sum()),
                    "위반(p 내려감)": int((delta[above] < -COUPLING_TOLERANCE).sum()),
                    "로짓차_평균": _round(float(delta[above].mean())) if above.any() else None,
                    "로짓차_최소": _round(float(delta[above].min())) if above.any() else None,
                },
                "하한_미만": {"n": int((~above).sum()),
                          "내려간_수": int((delta[~above] < 0).sum()),
                          "로짓차_평균": _round(float(delta[~above].mean())) if (~above).any()
                          else None},
                "하한값_대입_로짓차_최소": _round(float(delta_floor.min())),
            }
    return out


def coupling_slack(blocks: dict[str, dict], axes, floors: dict[str, float], upper: str) -> float:
    """상위 패턴 upper 의 결합 제약 최소 여유(음수면 위반) — 반올림 뒤 보정에 쓴다."""
    present = rm.pattern_present(upper)
    worst = float("inf")
    for axis in present:
        lower = blocks[rm.pattern_key([a for a in present if a != axis], axes)]
        for vertex in rm.coupling_vertices(lower["features"]):
            low = rm.block_logit(lower, rm.design_values(vertex))
            high = rm.block_logit(blocks[upper], rm.design_values({**vertex, axis: floors[axis]}))
            worst = min(worst, high - low)
    return worst


def rounded_blocks(design: PatternDesign, fitted: dict, floors: dict[str, float] | None,
                   digits: int = 4) -> dict[str, dict]:
    """계수·절편을 반올림한 계수 집합. 반올림이 만든 작은 위반은 보정한다 — 단조: 교호작용 항을
    1e-4 씩 올림, 결합: 패턴 키 순서(축 적은 것부터)로 상위 패턴 절편을 1e-4 단위로 올림(하위
    패턴은 이미 확정)."""
    step = 10.0 ** -digits
    blocks = {}
    for key in design.keys:
        coef, intercept = fitted[key]
        blocks[key] = {"features": list(design.names[key]),
                       "coefficients": {name: round(float(value), digits)
                                        for name, value in zip(design.names[key], coef)},
                       "intercept": round(float(intercept), digits)}
    for block in blocks.values():
        for _ in range(20):
            violations = rm.monotone_violations(block["coefficients"])
            if not violations:
                break
            for name in ("x2_whole×도형계", "x1_d×문자계", "x1_d×any_no_distinctive"):
                if name in block["coefficients"] and any(name in v for v in violations):
                    block["coefficients"][name] = round(block["coefficients"][name] + step, digits)
            for axis in AXES:
                if any(v.startswith(f"{axis} ") and "+" not in v for v in violations):
                    block["coefficients"][axis] = 0.0
    if floors:
        for key in design.keys:
            if key == rm.PATTERN_BASE_KEY:
                continue
            for _ in range(10_000):
                slack = coupling_slack(blocks, design.axes, floors, key)
                if slack >= -COUPLING_TOLERANCE:
                    break
                blocks[key]["intercept"] = round(blocks[key]["intercept"] + max(step, -slack),
                                                 digits)
    return blocks


def indicator_reference(rows: list[dict], y: np.ndarray, weight: np.ndarray, easy: np.ndarray,
                        groups: np.ndarray, masks: dict[str, np.ndarray], sigma: float, *,
                        folds: int, repeats: int, seed: int) -> dict:
    """참고 — v1.2.1 구조(결측 지시변수) + ①(쉬운 음성 이미지 축)만 적용, 오프셋 없이 전체 행 적합.
    지시변수 계수가 어떻게 바뀌는지(원인 확인)와 성능을 보고한다."""
    names = list(FEATURES)
    X = design_matrix(rows, names)
    prob, _ = cv_predictions("prior", X, y, weight, names, easy, groups, sigma, folds=folds,
                             repeats=repeats, seed=seed, image_offset=False)
    final = fit_method("prior", X, y, weight, names, easy, sigma, seed=seed, image_offset=False)
    return {
        "설명": "v1.2.1 지시변수 구조 + 쉬운 음성 이미지 축(오프셋 없이 전체 행 적합) — 참고",
        "계수": {name: round(float(value), 4) for name, value in zip(names, final.coef)},
        "절편": round(final.intercept, 4),
        "cv_auc": {name: _round(roc_auc(prob[mask], y[mask])) for name, mask in masks.items()},
        "brier": {name: _round(float(np.mean((prob[mask] - y[mask]) ** 2)))
                  for name, mask in masks.items() if name in ("심결", "심결+cross+db")},
    }


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
               easy: np.ndarray, hyper, seed: int = 0, *, image_offset: bool = True) -> Fitted:
    if method in ("logistic", "prior"):
        coef, intercept = fit_linear(X, y, weight, names, easy, method=method, hyper=hyper,
                                     image_offset=image_offset)
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
                   repeats: int, seed: int, image_offset: bool = True
                   ) -> tuple[np.ndarray, list[tuple[Fitted, np.ndarray]]]:
    """반복 교차검증 OOF 확률(반복 평균)과 겹 모델 목록(판례 조건 안정성용) — 단일 모델(트리·
    참고 지시변수 모델)."""
    total = np.zeros(y.size)
    fold_models: list[tuple[Fitted, np.ndarray]] = []
    for repeat in range(repeats):
        for train, test in folds_for(y, groups, folds=folds, seed=seed + repeat):
            fitted = fit_method(method, X[train], y[train], weight[train], names, easy[train],
                                hyper, seed=seed + repeat, image_offset=image_offset)
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
                     distinct: np.ndarray, hyper, *, rounds: int, seed: int,
                     image_offset: bool = True) -> dict:
    """심결 사건 복원추출(쉬운 음성 고정) 부트스트랩: 계수 분포 + 판례 조건 성립 비율(단일 모델).
    (iv) 는 x1_d×any_no_distinctive 계수(요부 없는 쌍의 x1 기울기 차) < 0 으로 condition_checks 가
    잰다."""
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
        fitted = fit_method(method, X[index], y[index], weight[index], names, easy[index], hyper,
                            image_offset=image_offset)
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
                     recall_review: float = RECALL_REVIEW,
                     min_support: int = RISK_MIN_SUPPORT) -> dict:
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


def risk_grade_precision(grade_block: dict) -> float | None:
    """"위험" 등급의 정밀도(등급 안 유사율, OOF) — 계수 JSON `meta.grade_precision`. 서비스가 화면
    문구 "검증 데이터 기준 10건 중 N건"(API 계약 v2 §4-3)에 쓰며 상수로 두지 않는다(E-6)."""
    for row in grade_block.get("등급별", []):
        if row.get("등급") == "위험":
            return row.get("정밀도(등급 안 유사율)")
    return None


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
    reasons: dict = {}
    table: list[dict] = []
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


def _pattern_summary(design: PatternDesign, y: np.ndarray, easy: np.ndarray,
                     per_prob: dict[str, np.ndarray], masks: dict[str, np.ndarray]) -> dict:
    """패턴별 행 수·클래스·적용 가능 행 OOF AUC(심결 / 심결+cross+db)."""
    out = {}
    for key in design.keys:
        mask = design.mask[key]
        own = design.own == key
        out[key] = {
            "관측_축": rm.pattern_present(key), "입력": design.names[key],
            "n": int(mask.sum()), "n_심결": int((mask & ~easy).sum()),
            "n_쉬운_음성": int((mask & easy).sum()),
            "유사": int((y[mask] == 1).sum()), "비유사": int((y[mask] == 0).sum()),
            "자기_패턴_행": int(own.sum()),
            "cv_auc": {name: _round(roc_auc(per_prob[key][mask & set_mask], y[mask & set_mask]))
                       for name, set_mask in masks.items() if name in ("심결", "심결+cross+db")},
        }
    return out


def run(features_path: Path, easy_path: Path | None, *, out_dir: Path, model_path: Path,
        methods=DEFAULT_METHODS, c_grid=C_GRID, sigma_grid=SIGMA_GRID,
        estimators_grid=ESTIMATORS_GRID, w_easy: float = W_EASY, folds: int = FOLDS,
        repeats: int = REPEATS, bootstrap: int = BOOTSTRAP, seed: int = 0,
        min_pattern_minority: int = MIN_PATTERN_MINORITY) -> dict:
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
    pattern_axes, pattern_choice = choose_pattern_axes(rows, y, min_minority=min_pattern_minority)
    design = PatternDesign(rows, pattern_axes)
    floors, floor_detail = dissimilar_floors(rows, y, easy, pattern_axes)
    removed = REMOVED_TERMS + [MISS_OF[axis] for axis in pattern_axes] + ["miss_x3"]
    full_names = design.names[design.full]
    data_summary = {
        "라벨": "최종", "심결_행": n_trial, "유사": n_pos, "비유사": n_neg,
        "이름_없어_제외": {"행": len(excluded),
                      "유사": sum(1 for r in excluded if r["최종라벨"] == "유사"),
                      "비유사": sum(1 for r in excluded if r["최종라벨"] == "비유사")},
        "쉬운_음성": {name: int((np.asarray([r["pair_source"] for r in rows]) == name).sum())
                   for name in ("cross", "db")},
        "쉬운_음성_이미지_있음": int((easy & observed(rows, "x2_whole")).sum()),
        "쉬운_음성_상품_있음": int((easy & observed(rows, "x4")).sum()),
        "w_easy": w_easy, "입력": full_names,
        "입력(패턴별)": {key: design.names[key] for key in design.keys},
        "패턴_축": list(pattern_axes), "패턴_결정": pattern_choice,
        "결합_하한": floor_detail, "결합_하한_근거": FLOOR_BASIS,
        "제거_항": removed, "트리_입력(이미지 블록 제외)": TREE_FEATURES,
        "소수_클래스_대_입력(EPV)": _round(min(n_pos, n_neg) / len(full_names)),
    }
    results: dict[str, dict] = {}
    for method in methods:
        linear = method in ("logistic", "prior")
        names = full_names if linear else feature_names_for(method)
        X = design.X[design.full] if linear else design_matrix(rows, names)
        per_hyper = {}
        for hyper in hyper_grid(method, c_grid=c_grid, sigma_grid=sigma_grid,
                                estimators_grid=estimators_grid):
            if linear:
                prob, per_prob, fold_fits = cv_patterns(method, design, y, weight, groups, hyper,
                                                        floors, folds=folds, repeats=repeats,
                                                        seed=seed)
                fold_models = [(full_fitted(design, fitted, method), test)
                               for fitted, test in fold_fits]
            else:
                prob, fold_models = cv_predictions(method, X, y, weight, names, easy, groups,
                                                   hyper, folds=folds, repeats=repeats, seed=seed)
                per_prob = None
            per_hyper[hyper] = (prob, fold_models, per_prob,
                                auc_block(prob, y, masks["심결"], seed=seed, bootstrap=0)["auc"])
        best = max(per_hyper, key=lambda h: per_hyper[h][3] or 0.0)
        prob, fold_models, per_prob, _ = per_hyper[best]
        started = time.perf_counter()
        if linear:
            fitted = fit_patterns(method, design, y, weight, np.arange(y.size), best, floors)
            final = full_fitted(design, fitted, method)
        else:
            fitted = None
            final = fit_method(method, X, y, weight, names, easy, best, seed=seed)
        elapsed = time.perf_counter() - started
        fold_checks = [condition_checks(model, X, family, trial, distinct)
                       for model, _ in fold_models]
        final_check = condition_checks(final, X, family, trial, distinct)
        item = {
            "method": method, "hyper": best, "features": names,
            "hyper_후보": {str(h): _round(per_hyper[h][3]) for h in per_hyper},
            "cv": {name: auc_block(prob, y, mask, seed=seed, bootstrap=bootstrap)
                   for name, mask in masks.items()},
            "calibration": {name: calibration(prob[mask], y[mask]) for name, mask in masks.items()
                            if name in ("심결", "심결+cross+db")},
            "학습_시간_초": _round(elapsed),
            "판례_조건(최종 적합)": {k: v for k, v in final_check.items() if k != "_기울기"},
            "로짓_기울기(최종 적합)": {k: (_round(v) if v is not None else None)
                               for k, v in final_check["_기울기"].items()},
            "판례_조건_겹_성립_비율": condition_rates(fold_checks),
            "_prob": prob, "_final": final, "_X": X, "_fitted": fitted,
        }
        if linear:
            item["계수"] = {name: round(float(value), 4) for name, value in zip(names, final.coef)}
            item["절편"] = round(final.intercept, 4)
            item["패턴"] = _pattern_summary(design, y, easy, per_prob, masks)
            item["패턴_계수"] = {
                key: {"계수": {n: round(float(v), 4) for n, v in zip(design.names[key],
                                                                   fitted[key][0])},
                      "절편": round(float(fitted[key][1]), 4)}
                for key in design.keys
            }
            item["부트스트랩"] = bootstrap_patterns(method, design, y, weight, groups, easy, family,
                                               distinct, best, floors, rounds=bootstrap,
                                               seed=seed)
            item["단조성"] = monotonicity_report(design, fitted, rows, floors)
            item["해석"] = "계수(점수 1.0 당 로짓) — 기준 패턴(모든 축 관측); 패턴별은 패턴_계수"
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
    prob = adopted["_prob"]
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
    reference_sigma = float(results["prior"]["hyper"]) if "prior" in results else (
        float(sigma_grid[0]))
    indicator = indicator_reference(rows, y, weight, easy, groups, masks, reference_sigma,
                                    folds=folds, repeats=repeats, seed=seed)
    coupled = adopted_method == "prior" and bool(pattern_axes)
    blocks = rounded_blocks(design, adopted["_fitted"], floors if coupled else None)
    reference = blocks[design.full]
    pattern_meta = adopted["패턴"]
    model = {
        "version": rm.MODEL_VERSION, "trained_at": date.today().isoformat(), "label": "최종",
        "method": "prior_monotone_logistic" if adopted_method == "prior" else "logistic_l2",
        "w_easy": w_easy, "hyper": adopted["hyper"],
        "removed_terms": removed,
        "prior": ({"mu": {name: PRIOR_MU[name] for name in full_names if name in PRIOR_MU},
                   "sigma": adopted["hyper"],
                   "applies_to": [name for name in full_names if name in PRIOR_MU],
                   "intercept_prior": False} if adopted_method == "prior" else None),
        "monotone": {"features": [n for n in MONOTONE_FEATURES if n in full_names],
                     "constraint": ("유사도 축 본체 ≥ 0; x2_whole 본체 + 도형계 교호작용 ≥ 0; "
                                    "x1 본체 + {문자계, 요부없음} 교호작용 모든 조합 ≥ 0 — "
                                    "패턴마다")}
        if adopted_method == "prior" else None,
        "figure_rule": {"threshold": FIGURE_X2_THRESHOLD, "caveat": FIGURE_CAVEAT,
                        "validated": False,
                        "basis": ("97후3050 후단(한 축의 유사로 혼동 우려) — 도형계 쌍 17 로 "
                                  "데이터 검증 불가, 제품 규칙(미검증). 도형계 입력은 "
                                  "figure_caveat True")},
        "pattern_axes": list(pattern_axes),
        "pattern_rule": pattern_choice["기준"],
        "reference_pattern": design.full,
        "patterns": {
            key: {"requires": rm.pattern_present(key), **blocks[key],
                  "meta": {k: pattern_meta[key][k] for k in ("n", "n_심결", "n_쉬운_음성", "유사",
                                                           "비유사", "자기_패턴_행", "cv_auc")}}
            for key in design.keys
        },
        "features": reference["features"],
        "coefficients": reference["coefficients"],
        "intercept": reference["intercept"],
        "coupling": ({"floors": floors, "basis": FLOOR_BASIS,
                      "constraint": ("상위 패턴(축 하나 더 관측, 그 축 = 하한값) 로짓 ≥ 하위 패턴 "
                                     "로짓 — 설계 항 상자의 모든 꼭짓점(rm.coupling_vertices); "
                                     "학습은 SLSQP 선형 제약, 런타임은 적재 때 검증")}
                     if coupled else None),
        "grade_thresholds": grades["심결+cross+db"]["thresholds"],
        "grade_basis": (f"심결+cross+db OOF 확률(행마다 자기 결측 패턴의 계수 집합; 위험 정밀도 ≥ "
                        f"{PRECISION_RISK}·최소 지지 {RISK_MIN_SUPPORT}, 검토 권장 재현율 ≥ "
                        f"{RECALL_REVIEW}, 안전/주의 등분; 미달이면 위험 하한은 검토 권장 하한과 "
                        "1.0 의 중간)"),
        "standalone_thresholds": standalone["thresholds"],
        "standalone_precision": STANDALONE_PRECISION,
        "standalone_reason": standalone["이유"],
        "meta": {
            "n_trial": n_trial, "n_pos": n_pos, "n_neg": n_neg,
            "n_excluded_no_name": len(excluded), "n_easy": int(easy.sum()),
            "n_easy_with_image": data_summary["쉬운_음성_이미지_있음"],
            "n_easy_with_goods": data_summary["쉬운_음성_상품_있음"],
            "folds": folds, "repeats": repeats, "bootstrap": bootstrap,
            "cv_auc": {name: block["auc"] for name, block in adopted["cv"].items()},
            "cv_auc_ci95": {name: block["auc_ci95"] for name, block in adopted["cv"].items()},
            "brier": {name: block["brier"] for name, block in adopted["calibration"].items()},
            "comparison_cv_auc": {name: item["cv"]["심결"]["auc"]
                                  for name, item in results.items()},
            "adoption_notes": adopt_notes, "adoption_pending": pending,
            "sigma_selection": ("fixed" if len(tuple(sigma_grid)) == 1 else "cv"),
            "sigma_fixed": ("CV 무차별(심결 AUC 차 0.006 안, CI 겹침) → 설계 원칙에 따라 중간값 1.0"
                            if len(tuple(sigma_grid)) == 1 else None),
            "risk_min_support": RISK_MIN_SUPPORT,
            # 계약 v2 meta.grade_precision — "위험" 등급의 OOF 정밀도(심결+cross+db). 서비스 화면
            # 문구 "검증 데이터 기준 10건 중 N건"의 출처(E-6).
            "grade_precision": risk_grade_precision(grades["심결+cross+db"]),
            "pattern_choice": pattern_choice,
            "coupling_floors": floor_detail,
            "monotonicity": adopted["단조성"],
            "indicator_reference": indicator,
            "feature_definitions": (
                "축 점수 0~1. 결측 패턴(pattern_axes 의 관측 조합)마다 계수 집합 — 관측된 축만 "
                "입력, "
                "결측 지시변수 없음(x3_d 는 has_meaning_both False 면 값 0). "
                "any_no_distinctive = 1 − has_distinctive_part_a·b, 교호작용 x1_d×문자계(문자·"
                "결합-문자요부·미상·결합)·x2_whole×도형계(도형·결합-도형요부)·"
                "x1_d×any_no_distinctive. 유형 주효과·miss_*·요부 플래그 2개 없음. 표준화 없음. "
                "기여도 miss_pattern = 패턴 절편 − 기준 절편."
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
        "요부_교차표": crosstab, "참고_지시변수_모델": indicator, "모델_파일": str(model_path),
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
    lines = [f"# 통합 모델 v1.3 학습 보고 ({summary['기준일']})", ""]
    lines.append(f"- 라벨 최종 · 심결 {data['심결_행']}행(유사 {data['유사']}·비유사 "
                 f"{data['비유사']}; 이름 없어 제외 {data['이름_없어_제외']['행']}행) · 쉬운 음성 "
                 f"cross "
                 f"{data['쉬운_음성']['cross']}·db {data['쉬운_음성']['db']} (w_easy "
                 f"{data['w_easy']}; 이미지 있음 {data['쉬운_음성_이미지_있음']}·상품 있음 "
                 f"{data['쉬운_음성_상품_있음']}) · 기준 패턴 입력 {len(data['입력'])}개 · 패턴 축 "
                 f"{data['패턴_축']} · 제거 항 {data['제거_항']} · EPV "
                 f"{data['소수_클래스_대_입력(EPV)']}")
    lines.append(f"- 결합 제약 하한({data['결합_하한_근거']}): " + ", ".join(
        f"{axis} {d['하한']}({d['근거']}; 심결 비유사 {d['심결_비유사_평균']}·전체 비유사 "
        f"{d['전체_비유사_평균']})" for axis, d in data["결합_하한"].items()))
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
        if "패턴" in item:
            lines += ["", "### 결측 패턴별 계수 집합", "",
                      "| 패턴 | 관측 축 | n(심결·쉬운 음성) | 유사/비유사 | 자기 패턴 행 | "
                      "OOF AUC 심결 | 심결+cross+db | 절편 | 계수 |",
                      "|---|---|---|---|---|---|---|---|---|"]
            for key, block in item["패턴"].items():
                coefficients = item["패턴_계수"][key]
                lines.append(
                    f"| {key} | {'·'.join(block['관측_축']) or '—'} | "
                    f"{block['n']}({block['n_심결']}·"
                    f"{block['n_쉬운_음성']}) | {block['유사']}/{block['비유사']} | "
                    f"{block['자기_패턴_행']} | {block['cv_auc'].get('심결')} | "
                    f"{block['cv_auc'].get('심결+cross+db')} | {coefficients['절편']} | "
                    + ", ".join(f"{n} {v}" for n, v in coefficients["계수"].items()) + " |")
        if "계수" in item:
            boot = item["부트스트랩"]
            lines += ["", f"기준 패턴(모든 축 관측) 계수 — 부트스트랩 {boot['rounds']}회", "",
                      "| 항 | 계수 | 부트스트랩 평균 | 95% 구간 |",
                      "|---|---|---|---|", f"| intercept | {item['절편']} | — | — |"]
            for term, value in item["계수"].items():
                b = boot["계수"][term]
                lines.append(f"| {term} | {value} | {b['평균']} | {b['ci95'][0]} ~ "
                             f"{b['ci95'][1]} |")
            b = boot["계수"]["intercept"]
            lines.append(f"| intercept(부트스트랩) | — | {b['평균']} | {b['ci95'][0]} ~ "
                         f"{b['ci95'][1]} |")
            if "패턴" in boot:
                lines += ["", "패턴별 절편(부트스트랩 평균, 95% 구간): " + ", ".join(
                    f"{key} {table['intercept']['평균']} ({table['intercept']['ci95'][0]} ~ "
                    f"{table['intercept']['ci95'][1]})" for key, table in boot["패턴"].items())]
            lines += ["", "부트스트랩 판례 조건 성립 비율: " + ", ".join(
                f"{k} {_rate(v)}" for k, v in boot["판례_조건_성립_비율"].items())]
        if "단조성" in item:
            lines += ["", "### 단조성(결합 제약) 검사 — 축 하나를 더 관측했을 때 로짓 차", "",
                      "| 패턴 | 하한 | n | 하한 이상 n / 위반 / 로짓차 평균·최소 | "
                      "하한 미만 n / 내려간 수 / 로짓차 평균 | 하한값 대입 최소 |",
                      "|---|---|---|---|---|---|"]
            for name_, block in item["단조성"].items():
                above, below = block["하한_이상"], block["하한_미만"]
                lines.append(
                    f"| {name_} | {block['하한']} | {block['n']} | {above['n']} / "
                    f"{above['위반(p 내려감)']} / {above['로짓차_평균']}·{above['로짓차_최소']} | "
                    f"{below['n']} / {below['내려간_수']} / {below['로짓차_평균']} | "
                    f"{block['하한값_대입_로짓차_최소']} |")
        if "형상_곡선" in item:
            lines.append("")
            for axis, cells in item["형상_곡선"].items():
                lines.append(f"- {axis}: " + ", ".join(f"{c['구간']} {c['점수']}" for c in cells))
        if "shap_평균절대값" in item:
            lines += ["", "| 항 | 평균 \\|SHAP\\|(로짓) |", "|---|---|"]
            for term, value in sorted(item["shap_평균절대값"].items(), key=lambda kv: -kv[1]):
                lines.append(f"| {term} | {value} |")
    indicator = summary.get("참고_지시변수_모델")
    if indicator:
        lines += ["", "## 참고 — 지시변수 모델(v1.2.1 구조 + 쉬운 음성 이미지 축, 오프셋 없음)", "",
                  f"- {indicator['설명']}",
                  f"- 심결 AUC {indicator['cv_auc'].get('심결')} · 심결+cross+db "
                  f"{indicator['cv_auc'].get('심결+cross+db')} · Brier {indicator['brier']}",
                  "- 계수: " + ", ".join(f"{k} {v}" for k, v in indicator["계수"].items())
                  + f", intercept {indicator['절편']}"]
    lines += ["", "## 등급 임계값 (채택 모델 OOF, 행마다 자기 패턴)", ""]
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
    parser.add_argument("--min-pattern-minority", type=int, default=MIN_PATTERN_MINORITY,
                        help="패턴마다 소수 클래스 최소 행 수(미달이면 패턴 축을 줄인다)")
    args = parser.parse_args(argv)
    methods = tuple(m.strip() for m in args.methods.split(",") if m.strip())
    unknown = [m for m in methods if m not in METHODS]
    if unknown:
        parser.error(f"모르는 방법 {unknown} (가능: {METHODS})")
    summary = run(args.features, args.easy, out_dir=args.out_dir, model_path=args.model,
                  methods=methods, w_easy=args.w_easy, folds=args.folds, repeats=args.repeats,
                  bootstrap=args.bootstrap, seed=args.seed,
                  min_pattern_minority=args.min_pattern_minority)
    print(report_text(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
