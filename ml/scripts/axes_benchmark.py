"""축별 벤치마크 — pairs_features.csv 의 4축 점수가 심결 라벨을 얼마나 가르는지 잰다(측정만).

실행 (프로젝트 루트에서. 특징 CSV 만 읽으므로 X3 실제 모델은 필요 없다. x2_benchmark 의 지표 코드를
재사용하므로 torch 는 import 된다):
    ml/venv/bin/python ml/scripts/axes_benchmark.py [--features ml/data/trials/pairs_features.csv]
        [--out ml/data/trials/axes_benchmark_v1.json] [--hist-dir ml/data/trials] [--seed 0]
        [--bootstrap 1000]

축과 라벨: x1·x2_text·x2_fig·x2_whole·x3 는 **표장 라벨**(x2_benchmark.mark_label — 상품만으로
결론 난 비유사는 제외), x4 는 **최종 라벨**(심결 결론). 학습(가중치 적합)은 하지 않는다.
부분집합(축마다):
  (a) 전체   — 점수가 있는 쌍 전부(게이트가 꺼져 0.0 인 쌍 포함)
  (b) 판단축 — 그 축이 심결의 판단축에 포함된 쌍(X1→호칭, X2→외관, X3→관념, X4→상품)
  (c) 게이트 — 결측·게이트 꺼짐이 아닌 쌍(has_pron·has_spelling·has_meaning 양쪽 True, has_goods,
               이미지 있음)
  (d) 이름B 출처별(kipris·본문·ocr; 이름 축 x1·x2_text·x3 만)
  (e) 종류별(거절결정불복·무효·권리범위확인 적극·소극)
지표: ROC AUC + 부트스트랩 95% CI(x2_benchmark.roc_auc/bootstrap_auc), n(유사/비유사), 유사·비유사
      중앙값, 분리도(유사 Q1 − 비유사 Q3).
축 간 상관: 스피어만(쌍별 완전 관측) 행렬 — 특히 x1↔x2_text 공선성.
단독 임계값: 축마다 정밀도(점수 ≥ t 인 쌍 중 유사 비율) ≥ 0.9 가 되는 **최소 t**(지지 n ≥ 10)와
      그때의 재현율(유사 쌍 중 잡힌 비율) — 안전장치 설계용.
게이트 효과: has_meaning 꺼진 쌍의 x3_raw(게이트 없는 X3) 분포·AUC, has_pronunciation 꺼진 쌍의 x1.
히스토그램: 축마다 axes_hist_v1_<축>.png(유사·비유사, Pillow).
식별력 전후(v0, ml/src/axes/distinctiveness.py): x1_d·x2_text_d·x3_d(약한 토큰을 extra_generic 으로
      넘긴 값)를 같은 부분집합으로 평가하고 전후 표, x1 = 1.0 이던 쌍(비유사 포함)의 전후, 유사 쌍이
      내려간 수(부작용)를 낸다.
현실 분포(--with-easy-negatives [pairs_features_easy.csv]): 쉬운 음성(교차·DB, 비유사 가정)을 더해
      심결만 / 심결+cross / 심결+cross+db 세 묶음의 AUC 를 낸다(이름 축·x2_whole·x4).
부트스트랩 단위(--bootstrap-unit, 2026-11-19 부터 기본 case): case 는 사건(심판번호)을 복원추출해
      한 사건의 여러 행이 함께 뽑힌다(쉬운 음성은 행마다 한 사건). pair 는 행 복원추출 — 2026-10-08~
      10-11 측정(x2_benchmark.bootstrap_auc)과 같은 난수열·같은 값이다.
사건 단위 가중(--case-cap 3, 통합 모델 설계 §6 결정): 심결 행의 가중치 w = min(1, cap / 그 사건의
      행 수)(특징 파일 안의 행 수) — 한 사건의 가중 합이 cap 을 넘지 않는다. 쉬운 음성은 1. 모든
      부분집합에서 가중 없음(auc)과 가중 있음(auc_w)을 함께 낸다(CI 는 같은 단위·같은 난수열).
나눠 보기(분할): 특징의 `회차`(라벨링 회차)로 1차 / 2차 / 1+2차, 상표유형으로 전체 / 문자계(문자·
      결합-문자요부) / 도형계(도형·결합-도형요부)마다 축별 (a)·(b)·(c) 와 현실 분포(심결+cross+db).
      도형계의 이미지 축(x2_whole·x2_fig)은 도형 외관 비교의 기준선 표로 따로 낸다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from scripts import x2_benchmark as x2b  # noqa: E402  (torch → faiss 순서는 그 모듈이 지킨다)

DEFAULT_BASE = ML_ROOT / "data" / "trials"
DEFAULT_FEATURES = DEFAULT_BASE / "pairs_features.csv"
DEFAULT_OUT = DEFAULT_BASE / "axes_benchmark_v1.json"
DEFAULT_EASY = DEFAULT_BASE / "pairs_features_easy.csv"

# (열, 표시, 판단축 단어, 라벨 종류, 게이트 플래그 열)
AXES = (
    ("x1", "X1 호칭", "호칭", "표장", ("has_pron_a", "has_pron_b")),
    ("x2_text", "X2 문자 외관(철자)", "외관", "표장", ("has_spelling_a", "has_spelling_b")),
    ("x2_fig", "X2 도형 크롭 CLIP", "외관", "표장", ("has_fig",)),
    ("x2_whole", "X2 전체 이미지 CLIP", "외관", "표장", ("has_image",)),
    ("x3", "X3 관념", "관념", "표장", ("has_meaning_a", "has_meaning_b")),
    ("x4", "X4 상품 견련성", "상품", "최종", ("has_goods",)),
    ("x1_d", "X1 호칭 + 식별력", "호칭", "표장", ("has_pron_a", "has_pron_b")),
    ("x2_text_d", "X2 철자 + 식별력", "외관", "표장", ("has_spelling_a", "has_spelling_b")),
    ("x3_d", "X3 관념 + 식별력", "관념", "표장", ("has_meaning_a", "has_meaning_b")),
)
NAME_AXES = ("x1", "x2_text", "x3", "x1_d", "x2_text_d", "x3_d")
DISTINCT_PAIRS = (("x1", "x1_d"), ("x2_text", "x2_text_d"), ("x3", "x3_d"))
EASY_AXES = ("x1", "x1_d", "x2_text", "x2_text_d", "x2_whole", "x3", "x3_d", "x4")
BOOTSTRAP_UNITS = ("case", "pair")
CASE_CAP = 3.0  # 한 사건의 가중 합 상한(통합 모델 설계 §6, 2026-11-12 사람 결정)
SPLITS = (("1차", ("1",)), ("2차", ("2",)), ("1+2차", None))
TYPE_GROUPS = (("전체", None), ("문자계", ("문자", "결합-문자요부")),
               ("도형계", ("도형", "결합-도형요부")))
SPLIT_AXES = ("x1", "x1_d", "x2_text", "x2_text_d", "x2_whole", "x2_fig", "x3", "x3_d", "x4")
SPLIT_SUBSETS = ("a_전체", "b_판단축", "c_게이트")
FIGURE_IMAGE_AXES = ("x2_whole", "x2_fig")
EASY_GROUPS = (("심결", ("trial",)), ("심결+cross", ("trial", "cross")),
               ("심결+cross+db", ("trial", "cross", "db")))
SOURCES = ("kipris", "본문", "ocr")
KINDS = ("거절결정불복", "무효", "권리범위확인(적극적)", "권리범위확인(소극적)")
CORRELATION_AXES = ("x1", "x2_text", "x2_fig", "x2_whole", "x3", "x4")
NUMERIC = ("x1", "x2_text", "x2_fig", "x2_whole", "x3", "x3_raw", "x4", "x1_d", "x2_text_d", "x3_d")
FLAGS = (
    "has_names", "has_pron_a", "has_pron_b", "has_meaning_a", "has_meaning_b", "has_spelling_a",
    "has_spelling_b", "has_goods", "has_image", "has_fig",
)
PRECISION_TARGET = 0.9
MIN_SUPPORT = 10


def load_features(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for column in NUMERIC:
            raw = row.get(column, "")
            row[column] = float(raw) if raw not in (None, "") else np.nan
        for column in FLAGS:
            row[column] = int(row.get(column) or 0)
        row.setdefault("pair_source", "trial")
        if not row["pair_source"]:
            row["pair_source"] = "trial"
    return rows


def labels_for(features: list[dict], kind: str) -> np.ndarray:
    """표장 라벨(유사 1·비유사 0·제외 -1) 또는 최종 라벨(1/0)."""
    column = "표장라벨" if kind == "표장" else "최종라벨"
    out = []
    for row in features:
        value = row.get(column, "")
        out.append(1 if value == "유사" else (0 if value == "비유사" else -1))
    return np.asarray(out, dtype=np.int64)


def scores_for(features: list[dict], column: str) -> np.ndarray:
    return np.asarray([row[column] for row in features], dtype=np.float64)


def gate_mask(features: list[dict], flags: tuple[str, ...]) -> np.ndarray:
    return np.asarray([all(row[flag] for flag in flags) for row in features], dtype=bool)


# ---- 가중 AUC·사건 단위 부트스트랩 ---------------------------------------------------------------

def _tie_auc(tie: np.ndarray, w_pos: np.ndarray, w_neg: np.ndarray) -> float | None:
    """점수 동점 묶음 번호(오름차순)와 행별 유사·비유사 가중치로 가중 Mann–Whitney AUC.
    동점은 0.5. 한쪽 가중 합이 0 이면 None."""
    pos = np.bincount(tie, weights=w_pos)
    neg = np.bincount(tie, weights=w_neg)
    total_pos, total_neg = float(pos.sum()), float(neg.sum())
    if total_pos <= 0 or total_neg <= 0:
        return None
    below = np.cumsum(neg) - neg
    return float((pos * (below + 0.5 * neg)).sum() / (total_pos * total_neg))


def weighted_auc(scores: np.ndarray, labels: np.ndarray,
                 weights: np.ndarray | None = None) -> float | None:
    """가중 ROC AUC — 유사 i·비유사 j 쌍마다 w_i·w_j 로 센 Mann–Whitney(동점 0.5). 가중치가 모두
    1 이면 x2_benchmark.roc_auc(순위 AUC)와 같다."""
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    if scores.size == 0:
        return None
    weights = np.ones(scores.size) if weights is None else np.asarray(weights, dtype=np.float64)
    _, tie = np.unique(scores, return_inverse=True)
    return _tie_auc(tie, weights * (labels == 1), weights * (labels == 0))


def bootstrap_auc_grouped(scores: np.ndarray, labels: np.ndarray, *,
                          groups: np.ndarray | None = None, weights: np.ndarray | None = None,
                          rounds: int = x2b.BOOTSTRAP_ROUNDS,
                          seed: int = 0) -> tuple[float | None, float | None]:
    """(가중) AUC 의 부트스트랩 95% CI. groups 가 있으면 그 단위(사건)를 복원추출하고, 없으면 행을
    복원추출한다 — 행 단위는 x2_benchmark.bootstrap_auc 와 같은 난수열이라 같은 값이다(뽑힌 횟수를
    가중치에 곱하는 것과 행을 되풀이하는 것은 같은 AUC). 한쪽 클래스가 비는 회차는 버린다."""
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    base = np.ones(scores.size) if weights is None else np.asarray(weights, dtype=np.float64)
    if rounds <= 0 or weighted_auc(scores, labels, base) is None:
        return None, None
    _, tie = np.unique(scores, return_inverse=True)
    if groups is None:
        group_id, size = np.arange(scores.size), scores.size
    else:
        _, group_id = np.unique(np.asarray(groups).astype(str), return_inverse=True)
        size = int(group_id.max()) + 1
    is_pos, is_neg = (labels == 1).astype(np.float64), (labels == 0).astype(np.float64)
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(rounds):
        counts = np.bincount(rng.integers(0, size, size), minlength=size)
        drawn = base * counts[group_id]
        auc = _tie_auc(tie, drawn * is_pos, drawn * is_neg)
        if auc is not None:
            values.append(auc)
    if not values:
        return None, None
    return x2b._round(np.percentile(values, 2.5)), x2b._round(np.percentile(values, 97.5))


def case_weights(features: list[dict], cap: float | None = CASE_CAP) -> np.ndarray:
    """심결 행 w = min(1, cap / 그 사건의 심결 행 수), 쉬운 음성(pair_source ≠ trial)은 1.
    cap 이 없거나 0 이하면 모두 1."""
    if not cap or cap <= 0:
        return np.ones(len(features))
    sources = [row.get("pair_source") or "trial" for row in features]
    counts: dict[str, int] = {}
    for row, source in zip(features, sources):
        if source == "trial":
            counts[row["심판번호"]] = counts.get(row["심판번호"], 0) + 1
    return np.asarray([
        min(1.0, cap / counts[row["심판번호"]]) if source == "trial" else 1.0
        for row, source in zip(features, sources)
    ], dtype=np.float64)


def annotate(rows: list[dict], *, unit: str = "case", cap: float | None = CASE_CAP) -> None:
    """행마다 부트스트랩 묶음(_group)과 사건 가중치(_w)를 붙인다(제자리). 가중치는 넘긴 행 전체
    (심결 + 쉬운 음성)에서 센다 — 사건의 행은 모두 심결 특징 파일에 있다."""
    if unit not in BOOTSTRAP_UNITS:
        raise ValueError(f"부트스트랩 단위는 {BOOTSTRAP_UNITS} 중 하나: {unit!r}")
    weights = case_weights(rows, cap) if cap and cap > 0 else None
    for index, row in enumerate(rows):
        row["_group"] = row["심판번호"] if unit == "case" else None  # pair: 행 복원추출
        row["_w"] = float(weights[index]) if weights is not None else None


def row_meta(features: list[dict]) -> tuple[np.ndarray | None, np.ndarray | None]:
    """(묶음, 가중치) 배열. 묶음이 없는 행이 있으면 groups None(행 단위), 가중치가 없는 행이
    있으면 weights None(가중 없음만) — annotate 하지 않은 행은 (None, None)."""
    if not features:
        return None, None
    groups = None
    if all(row.get("_group") is not None for row in features):
        groups = np.asarray([row["_group"] for row in features])
    weights = None
    if all(row.get("_w") is not None for row in features):
        weights = np.asarray([row["_w"] for row in features], dtype=np.float64)
    return groups, weights


def evaluate_subset(scores: np.ndarray, labels: np.ndarray, *, seed: int, bootstrap: int,
                    groups: np.ndarray | None = None,
                    weights: np.ndarray | None = None) -> dict:
    """AUC(가중 없음) + CI, 가중치가 있으면 auc_w + CI. groups 가 있으면 CI 는 그 단위
    부트스트랩."""
    similar, dissimilar = scores[labels == 1], scores[labels == 0]
    low, high = bootstrap_auc_grouped(scores, labels, groups=groups, rounds=bootstrap, seed=seed)
    out = {
        "n": int(scores.size), "n_유사": int(similar.size), "n_비유사": int(dissimilar.size),
        "auc": x2b._round(x2b.roc_auc(scores, labels)), "auc_ci95": [low, high],
        "유사_중앙값": x2b._round(float(np.median(similar))) if similar.size else None,
        "비유사_중앙값": x2b._round(float(np.median(dissimilar))) if dissimilar.size else None,
        "분리도_Q1유사-Q3비유사": x2b.separation(similar, dissimilar),
    }
    if groups is not None:
        out["n_사건"] = int(np.unique(np.asarray(groups).astype(str)).size)
    if weights is not None:
        w_low, w_high = bootstrap_auc_grouped(scores, labels, groups=groups, weights=weights,
                                              rounds=bootstrap, seed=seed)
        out.update({
            "auc_w": x2b._round(weighted_auc(scores, labels, weights)),
            "auc_w_ci95": [w_low, w_high],
            "n_가중": x2b._round(float(np.asarray(weights).sum())),
        })
    return out


def evaluate_rows(features: list[dict], column: str, label_kind: str, mask: np.ndarray, *,
                  seed: int, bootstrap: int) -> dict:
    """features 에서 mask & (점수 있음) & (라벨 있음) 인 행으로 evaluate_subset."""
    scores = scores_for(features, column)
    labels = labels_for(features, label_kind)
    chosen = mask & ~np.isnan(scores) & (labels >= 0)
    groups, weights = row_meta(features)
    return evaluate_subset(
        scores[chosen], labels[chosen], seed=seed, bootstrap=bootstrap,
        groups=None if groups is None else groups[chosen],
        weights=None if weights is None else weights[chosen],
    )


def subset_masks(features: list[dict], axis: tuple) -> list[tuple[str, str, np.ndarray]]:
    column, _, axis_word, _, flags = axis
    n = len(features)
    masks = [
        ("a_전체", "전체", np.ones(n, dtype=bool)),
        ("b_판단축", f"판단축에 {axis_word} 포함",
         np.asarray([axis_word in (row.get("판단축") or "") for row in features], dtype=bool)),
        ("c_게이트", "결측·게이트 꺼짐 아님", gate_mask(features, flags)),
    ]
    if column in NAME_AXES:
        for source in SOURCES:
            masks.append((f"d_{source}", f"이름B 출처 {source}",
                          np.asarray([row.get("이름B_출처") == source for row in features])))
    for kind in KINDS:
        masks.append((f"e_{kind}", f"종류 {kind}",
                      np.asarray([row.get("종류") == kind for row in features])))
    return masks


def evaluate_axis(features: list[dict], axis: tuple, *, seed: int, bootstrap: int) -> dict:
    column, title, axis_word, label_kind, _ = axis
    scores = scores_for(features, column)
    labels = labels_for(features, label_kind)
    valid = ~np.isnan(scores) & (labels >= 0)
    subsets = {}
    for key, description, mask in subset_masks(features, axis):
        subsets[key] = {"설명": description, **evaluate_rows(
            features, column, label_kind, mask, seed=seed, bootstrap=bootstrap
        )}
    return {
        "표시": title, "판단축": axis_word, "라벨": label_kind,
        "결측": int(np.isnan(scores).sum()), "부분집합": subsets,
        "단독임계값": precision_threshold(scores[valid], labels[valid]),
    }


def precision_threshold(scores: np.ndarray, labels: np.ndarray, *,
                        target: float = PRECISION_TARGET, min_support: int = MIN_SUPPORT) -> dict:
    """정밀도(점수 ≥ t 인 쌍 중 유사 비율) ≥ target 이 되는 최소 t(지지 n ≥ min_support).
    없으면 threshold None. 재현율 = 유사 쌍 중 점수 ≥ t 인 비율."""
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    n_pos = int((labels == 1).sum())
    result = {"목표_정밀도": target, "최소_지지": min_support, "threshold": None, "precision": None,
              "recall": None, "n_above": 0, "n_유사": n_pos, "n": int(scores.size),
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
        point = {
            "threshold": x2b._round(float(threshold)), "precision": x2b._round(precision),
            "recall": x2b._round(float((labels[above] == 1).sum() / n_pos)), "n_above": count,
        }
        if best is None or precision > best["precision"]:
            best = point  # 지지 n ≥ min_support 인 임계값 중 정밀도 최대(동률이면 낮은 t)
        if precision >= target and result["threshold"] is None:
            result.update(point)
    result["최대_정밀도"] = best
    return result


def spearman(x: np.ndarray, y: np.ndarray) -> tuple[float | None, int]:
    """쌍별 완전 관측의 스피어만 상관(평균 순위)과 n. n < 3 이거나 분산 0 이면 (None, n)."""
    from scipy.stats import rankdata

    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    both = ~np.isnan(x) & ~np.isnan(y)
    n = int(both.sum())
    if n < 3:
        return None, n
    rx, ry = rankdata(x[both]), rankdata(y[both])
    if rx.std() == 0 or ry.std() == 0:
        return None, n
    return x2b._round(float(np.corrcoef(rx, ry)[0, 1])), n


def correlation_matrix(features: list[dict], axes: tuple[str, ...] = CORRELATION_AXES) -> dict:
    columns = {axis: scores_for(features, axis) for axis in axes}
    rho: dict[str, dict] = {}
    counts: dict[str, dict] = {}
    for a in axes:
        rho[a], counts[a] = {}, {}
        for b in axes:
            value, n = spearman(columns[a], columns[b])
            rho[a][b], counts[a][b] = value, n
    return {"rho": rho, "n": counts}


def gate_effect(features: list[dict], *, seed: int, bootstrap: int) -> dict:
    mark = labels_for(features, "표장")
    named = np.asarray([bool(row["has_names"]) for row in features])
    meaning_on = gate_mask(features, ("has_meaning_a", "has_meaning_b"))
    pron_on = gate_mask(features, ("has_pron_a", "has_pron_b"))
    spelling_on = gate_mask(features, ("has_spelling_a", "has_spelling_b"))
    x3_raw = scores_for(features, "x3_raw")
    x1 = scores_for(features, "x1")
    result: dict = {}
    for name, mask in (
        ("x3_raw_게이트꺼짐", named & ~meaning_on), ("x3_raw_게이트켜짐", named & meaning_on),
    ):
        chosen = mask & ~np.isnan(x3_raw) & (mark >= 0)
        result[name] = {
            "설명": "has_meaning 이 한쪽이라도 False 인 쌍의 게이트 없는 X3" if "꺼짐" in name
            else "양쪽 has_meaning True 인 쌍(비교용)",
            **evaluate_rows(features, "x3_raw", "표장", mask, seed=seed, bootstrap=bootstrap),
            "유사_분포": x2b.distribution(x3_raw[chosen & (mark == 1)]),
            "비유사_분포": x2b.distribution(x3_raw[chosen & (mark == 0)]),
        }
    pron_off = named & ~pron_on & ~np.isnan(x1)
    result["x1_게이트꺼짐"] = {
        "설명": "has_pronunciation 이 한쪽이라도 False 인 쌍의 x1(후보 없음 → 함수가 0.0)",
        "n": int(pron_off.sum()), "n_유사": int((pron_off & (mark == 1)).sum()),
        "n_비유사": int((pron_off & (mark == 0)).sum()), "x1_분포": x2b.distribution(x1[pron_off]),
    }
    result["x2_text_게이트꺼짐"] = {"n": int((named & ~spelling_on).sum())}
    result["이름_없음"] = int((~named).sum())
    return result


def distinctiveness_effect(features: list[dict], result: dict) -> dict:
    """식별력 전후: 부분집합별 AUC 전후 + x = 1.0 이던 쌍의 전후 + 유사 쌍 하락 수(부작용)."""
    mark = labels_for(features, "표장")
    out: dict = {}
    for before, after in DISTINCT_PAIRS:
        sub_b, sub_a = result["축"][before]["부분집합"], result["축"][after]["부분집합"]
        keys = ["a_전체", "b_판단축", "c_게이트"] + [f"e_{kind}" for kind in KINDS]
        x, y = scores_for(features, before), scores_for(features, after)
        valid = ~np.isnan(x) & ~np.isnan(y) & (mark >= 0)
        ones = valid & (x >= 0.9999)
        still = ones & (y >= 0.9999)
        similar, dissimilar = valid & (mark == 1), valid & (mark == 0)
        drop_similar = similar & (y < x - 1e-9)
        drop_dissimilar = dissimilar & (y < x - 1e-9)
        out[before] = {
            "부분집합": {key: {"전": sub_b[key]["auc"], "후": sub_a[key]["auc"],
                           "후_ci95": sub_a[key]["auc_ci95"], "n": sub_a[key]["n"]}
                      for key in keys},
            "점수_1.0_쌍": {
                "전": {"n": int(ones.sum()), "유사": int((ones & (mark == 1)).sum()),
                      "비유사": int((ones & (mark == 0)).sum())},
                "후_그대로_1.0": {"n": int(still.sum()), "유사": int((still & (mark == 1)).sum()),
                               "비유사": int((still & (mark == 0)).sum())},
            },
            "내려간_쌍": {
                "유사": {"n": int(drop_similar.sum()),
                       "평균_하락": x2b._round(float((x - y)[drop_similar].mean()))
                       if drop_similar.any() else None},
                "비유사": {"n": int(drop_dissimilar.sum()),
                        "평균_하락": x2b._round(float((x - y)[drop_dissimilar].mean()))
                        if drop_dissimilar.any() else None},
            },
        }
    return out


def realistic_distribution(features: list[dict], easy: list[dict], *, seed: int,
                           bootstrap: int) -> dict:
    """쉬운 음성을 더한 세 묶음의 AUC(이름 축·x4). 쉬운 음성은 비유사(0)."""
    rows = features + easy
    sources = np.asarray([r.get("pair_source") or "trial" for r in rows])
    out: dict = {"쉬운_음성": {src: int((sources == src).sum()) for src in ("cross", "db")},
                 "축": {}}
    for axis in EASY_AXES:
        label_kind = next(a[3] for a in AXES if a[0] == axis)
        out["축"][axis] = {}
        for name, allowed in EASY_GROUPS:
            out["축"][axis][name] = evaluate_rows(rows, axis, label_kind, np.isin(sources, allowed),
                                                 seed=seed, bootstrap=bootstrap)
    return out


# ---- 분할: 라벨링 회차 × 유형 -----------------------------------------------------------------

def split_mask(features: list[dict], rounds: tuple[str, ...] | None,
               types: tuple[str, ...] | None) -> np.ndarray:
    return np.asarray([
        (rounds is None or (row.get("회차") or "") in rounds)
        and (types is None or (row.get("상표유형") or "") in types)
        for row in features
    ], dtype=bool)


def split_results(features: list[dict], easy: list[dict] | None, *, seed: int,
                  bootstrap: int) -> dict:
    """회차(1차·2차·1+2차) × 유형(전체·문자계·도형계)마다 축별 (a)·(b)·(c), 회차마다 현실 분포
    (심결+cross+db, 유형 전체). 행이 없는 회차는 건너뛴다."""
    axes = {axis[0]: axis for axis in AXES}
    out: dict = {}
    easy = easy or []
    for split, rounds in SPLITS:
        in_split = split_mask(features, rounds, None)
        if not in_split.any():
            continue
        item: dict = {"행": int(in_split.sum()),
                      "사건": len({r["심판번호"] for r, m in zip(features, in_split) if m}),
                      "유형": {}}
        for group, types in TYPE_GROUPS:
            mask = split_mask(features, rounds, types)
            block: dict = {"행": int(mask.sum()),
                           "사건": len({r["심판번호"] for r, m in zip(features, mask) if m}),
                           "축": {}}
            for column in SPLIT_AXES:
                axis = axes[column]
                subsets = {key: sub_mask for key, _, sub_mask in subset_masks(features, axis)
                           if key in SPLIT_SUBSETS}
                block["축"][column] = {
                    key: evaluate_rows(features, column, axis[3], mask & subsets[key], seed=seed,
                                       bootstrap=bootstrap)
                    for key in SPLIT_SUBSETS
                }
            item["유형"][group] = block
        if easy:
            rows = [r for r, m in zip(features, in_split) if m] + easy
            item["현실_분포"] = {
                column: evaluate_rows(rows, column, axes[column][3], np.ones(len(rows), bool),
                                      seed=seed, bootstrap=bootstrap)
                for column in EASY_AXES
            }
        out[split] = item
    return out


def run(features_path: Path, *, out_path: Path, hist_dir: Path | None, seed: int = 0,
        bootstrap: int = x2b.BOOTSTRAP_ROUNDS, easy_path: Path | None = None,
        unit: str = "case", case_cap: float | None = CASE_CAP) -> dict:
    features = load_features(features_path)
    easy = load_features(easy_path) if easy_path is not None and Path(easy_path).exists() else None
    annotate(features + (easy or []), unit=unit, cap=case_cap)
    mark = labels_for(features, "표장")
    weights = case_weights(features, case_cap)
    result: dict = {
        "기준일": date.today().isoformat(), "특징_파일": str(features_path),
        "대상_행": len(features),
        "부트스트랩": {"단위": unit, "회": bootstrap, "seed": seed},
        "사건가중": {"상한": case_cap, "사건": len({r["심판번호"] for r in features}),
                  "가중_합": x2b._round(float(weights.sum())),
                  "1보다_작은_행": int((weights < 1).sum())},
        "표장라벨": {"유사": int((mark == 1).sum()), "비유사": int((mark == 0).sum()),
                   "제외": int((mark < 0).sum())},
        "최종라벨": {"유사": sum(1 for r in features if r["최종라벨"] == "유사"),
                   "비유사": sum(1 for r in features if r["최종라벨"] == "비유사")},
        "축": {}, "히스토그램": {},
    }
    for axis in AXES:
        column = axis[0]
        result["축"][column] = evaluate_axis(features, axis, seed=seed, bootstrap=bootstrap)
        if hist_dir is not None:
            scores = scores_for(features, column)
            labels = labels_for(features, axis[3])
            valid = ~np.isnan(scores) & (labels >= 0)
            path = Path(hist_dir) / f"axes_hist_v1_{column}.png"
            x2b.histogram_png(
                scores[valid & (labels == 1)], scores[valid & (labels == 0)], path,
                title=f"{axis[1]} 점수 분포 — (a) 전체, {axis[3]} 라벨",
            )
            result["히스토그램"][column] = str(path)
    result["상관_스피어만"] = correlation_matrix(features)
    result["게이트_효과"] = gate_effect(features, seed=seed, bootstrap=bootstrap)
    result["식별력_전후"] = distinctiveness_effect(features, result)
    if easy is not None:
        result["현실_분포"] = realistic_distribution(features, easy, seed=seed, bootstrap=bootstrap)
    result["분할"] = split_results(features, easy, seed=seed, bootstrap=bootstrap)
    for row in features + (easy or []):  # JSON 에 남기지 않는 보조 키
        row.pop("_group", None), row.pop("_w", None)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


# ---- 표 --------------------------------------------------------------------------------------

def _cell(item: dict | None) -> str:
    if not item or item.get("auc") is None:
        return "-"
    low, high = item.get("auc_ci95") or (None, None)
    ci = f" ({low:.2f}~{high:.2f})" if low is not None else ""
    return f"{item['auc']:.2f}{ci} n={item['n']} ({item['n_유사']}/{item['n_비유사']})"


def axis_table(result: dict, keys: tuple[str, ...], heading: str) -> str:
    lines = ["| 축 | " + " | ".join(heading.format(key=key) for key in keys) + " |",
             "|---|" + "---|" * len(keys)]
    for column, item in result["축"].items():
        cells = [_cell(item["부분집합"].get(key)) for key in keys]
        lines.append(f"| {item['표시']} ({column}) | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def correlation_table(result: dict) -> str:
    axes = list(result["상관_스피어만"]["rho"])
    lines = ["| ρ (n) | " + " | ".join(axes) + " |", "|---|" + "---|" * len(axes)]
    for a in axes:
        cells = []
        for b in axes:
            rho = result["상관_스피어만"]["rho"][a][b]
            n = result["상관_스피어만"]["n"][a][b]
            cells.append("-" if rho is None else f"{rho:.2f} ({n})")
        lines.append(f"| {a} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def threshold_table(result: dict) -> str:
    lines = [
        "| 축 | 최소 t (정밀도 ≥ 0.9, n ≥ 10) | 정밀도 | 재현율(유사 중) | t 이상 n | 유사 n "
        "| 최대 정밀도(n ≥ 10) |",
        "|---|---|---|---|---|---|---|",
    ]
    for column, item in result["축"].items():
        t = item["단독임계값"]
        best = t.get("최대_정밀도") or {}
        best_text = (
            f"{best['precision']:.2f} @ t≥{best['threshold']:.3f} (n={best['n_above']}, "
            f"재현율 {best['recall']:.2f})" if best else "-"
        )
        if t["threshold"] is None:
            lines.append(
                f"| {item['표시']} ({column}) | 없음 | - | - | - | {t['n_유사']} | {best_text} |"
            )
        else:
            lines.append(
                f"| {item['표시']} ({column}) | {t['threshold']:.3f} | {t['precision']:.2f} | "
                f"{t['recall']:.2f} | {t['n_above']} | {t['n_유사']} | {best_text} |"
            )
    return "\n".join(lines)


def distinctiveness_table(result: dict) -> str:
    keys = ["a_전체", "b_판단축", "c_게이트"] + [f"e_{kind}" for kind in KINDS]
    lines = ["| 축 | " + " | ".join(k.split("_", 1)[1] for k in keys)
             + " | 점수 1.0 쌍(유사/비유사) 전→후 | 유사 하락 n(평균) | 비유사 하락 n(평균) |",
             "|---|" + "---|" * (len(keys) + 3)]
    for axis, item in result["식별력_전후"].items():
        cells = []
        for key in keys:
            sub = item["부분집합"][key]
            before = "-" if sub["전"] is None else f"{sub['전']:.2f}"
            after = "-" if sub["후"] is None else f"{sub['후']:.2f}"
            cells.append(f"{before}→{after}")
        ones = item["점수_1.0_쌍"]
        drop = item["내려간_쌍"]
        lines.append(
            f"| {axis} | " + " | ".join(cells)
            + f" | {ones['전']['유사']}/{ones['전']['비유사']} → "
              f"{ones['후_그대로_1.0']['유사']}/{ones['후_그대로_1.0']['비유사']}"
            + f" | {drop['유사']['n']} ({drop['유사']['평균_하락']}) "
              f"| {drop['비유사']['n']} ({drop['비유사']['평균_하락']}) |"
        )
    return "\n".join(lines)


def realistic_table(result: dict) -> str:
    real = result.get("현실_분포")
    if not real:
        return "(쉬운 음성 없음 — --with-easy-negatives)"
    groups = [name for name, _ in EASY_GROUPS]
    lines = [f"쉬운 음성: cross {real['쉬운_음성']['cross']} · db {real['쉬운_음성']['db']}", "",
             "| 축 | " + " | ".join(groups) + " |", "|---|" + "---|" * len(groups)]
    for axis, items in real["축"].items():
        lines.append(f"| {axis} | " + " | ".join(_cell(items[g]) for g in groups) + " |")
    return "\n".join(lines)


def _cell_w(item: dict | None) -> str:
    """가중 AUC(사건 단위 가중) 칸 — 가중 합 n_가중."""
    if not item or item.get("auc_w") is None:
        return "-"
    low, high = item.get("auc_w_ci95") or (None, None)
    ci = f" ({low:.2f}~{high:.2f})" if low is not None else ""
    return f"{item['auc_w']:.2f}{ci} w={item.get('n_가중')}"


def _cell_cases(item: dict | None) -> str:
    text = _cell(item)
    if text != "-" and item.get("n_사건") is not None:
        text += f" 사건 {item['n_사건']}"
    return text


def split_table(result: dict, split: str, group: str) -> str:
    block = result["분할"][split]["유형"][group]
    heads = []
    for key in SPLIT_SUBSETS:
        heads += [f"{key} 가중 없음", f"{key} 가중"]
    lines = [f"행 {block['행']} · 사건 {block['사건']}", "", "| 축 | " + " | ".join(heads) + " |",
             "|---|" + "---|" * len(heads)]
    for column, subsets in block["축"].items():
        cells = []
        for key in SPLIT_SUBSETS:
            cells += [_cell_cases(subsets[key]), _cell_w(subsets[key])]
        lines.append(f"| {column} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def figure_image_table(result: dict) -> str:
    """도형계 이미지 축(CLIP) — 도형 외관 비교의 기준선."""
    lines = ["| 회차 | 축 | (a) 가중 없음 | (a) 가중 | (b) 판단축 외관 가중 없음 | (b) 가중 |",
             "|---|---|---|---|---|---|"]
    for split, item in result.get("분할", {}).items():
        block = item["유형"]["도형계"]["축"]
        for column in FIGURE_IMAGE_AXES:
            sub = block[column]
            lines.append(f"| {split} | {column} | {_cell_cases(sub['a_전체'])} | "
                         f"{_cell_w(sub['a_전체'])} | {_cell_cases(sub['b_판단축'])} | "
                         f"{_cell_w(sub['b_판단축'])} |")
    return "\n".join(lines)


def split_realistic_table(result: dict) -> str:
    splits = [s for s, item in result.get("분할", {}).items() if "현실_분포" in item]
    if not splits:
        return "(쉬운 음성 없음)"
    heads = []
    for split in splits:
        heads += [f"{split} 가중 없음", f"{split} 가중"]
    lines = ["| 축 | " + " | ".join(heads) + " |", "|---|" + "---|" * len(heads)]
    for column in EASY_AXES:
        cells = []
        for split in splits:
            sub = result["분할"][split]["현실_분포"][column]
            cells += [_cell(sub), _cell_w(sub)]
        lines.append(f"| {column} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def split_report(result: dict) -> list[str]:
    if not result.get("분할"):
        return []
    weight = result.get("사건가중", {})
    parts = [
        f"\n## 분할 — 라벨링 회차 × 유형 (부트스트랩 "
        f"{result.get('부트스트랩', {}).get('단위')} 단위, "
        f"사건 가중 상한 {weight.get('상한')} · 1 보다 작은 행 {weight.get('1보다_작은_행')})",
    ]
    for split, item in result["분할"].items():
        for group, _ in TYPE_GROUPS:
            parts += [f"\n### {split} · {group}", split_table(result, split, group)]
    parts += ["\n## 도형계 이미지 축(CLIP) — 도형 외관 비교 기준선", figure_image_table(result),
              "\n## 현실 분포(심결+cross+db) — 회차별", split_realistic_table(result)]
    return parts


def report_text(result: dict) -> str:
    parts = [
        f"대상 {result['대상_행']}행 · 표장 라벨 유사 {result['표장라벨']['유사']}·비유사 "
        f"{result['표장라벨']['비유사']}·제외 {result['표장라벨']['제외']} · 최종 라벨 유사 "
        f"{result['최종라벨']['유사']}·비유사 {result['최종라벨']['비유사']}",
        "\n## AUC (95% CI) n (유사/비유사) — (a) 전체 · (b) 판단축 포함 · (c) 게이트 켜짐",
        axis_table(result, ("a_전체", "b_판단축", "c_게이트"), "{key}"),
        "\n## (d) 이름B 출처별",
        axis_table(result, ("d_kipris", "d_본문", "d_ocr"), "{key}"),
        "\n## (e) 종류별",
        axis_table(result, tuple(f"e_{kind}" for kind in KINDS), "{key}"),
        "\n## 축 간 스피어만 상관 (쌍별 완전 관측)",
        correlation_table(result),
        "\n## 단독 임계값(정밀도 ≥ 0.9 가 되는 최소 점수)",
        threshold_table(result),
        "\n## 식별력 v0 전후 (AUC 전→후; 쌍 수는 _d 축 기준)",
        distinctiveness_table(result),
        "\n## 현실 분포 (쉬운 음성 추가, 비유사 가정)",
        realistic_table(result),
    ]
    gate = result["게이트_효과"]
    off, on, x1_off = gate["x3_raw_게이트꺼짐"], gate["x3_raw_게이트켜짐"], gate["x1_게이트꺼짐"]
    parts.append(
        f"\n## 게이트 효과\n- x3_raw 게이트 꺼짐: {_cell(off)} · 유사 중앙값 {off['유사_중앙값']}"
        " · "
        f"비유사 중앙값 {off['비유사_중앙값']}\n- x3_raw 게이트 켜짐: {_cell(on)}\n"
        f"- x1 게이트 꺼짐: n={x1_off['n']} (유사 {x1_off['n_유사']}·비유사 {x1_off['n_비유사']}), "
        f"x1 분포 {x1_off['x1_분포']}\n"
        f"- x2_text 게이트 꺼짐 n={gate['x2_text_게이트꺼짐']['n']} · 이름 없음 {gate['이름_없음']}"
    )
    parts += split_report(result)
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--hist-dir", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--no-hist", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--bootstrap", type=int, default=x2b.BOOTSTRAP_ROUNDS)
    parser.add_argument("--bootstrap-unit", choices=BOOTSTRAP_UNITS, default="case",
                        help="case = 사건(심판번호) 복원추출(기본), "
                             "pair = 행 복원추출(2026-10 측정)")
    parser.add_argument("--case-cap", type=float, default=CASE_CAP,
                        help="사건 가중 w = min(1, cap/사건의 행 수), 0 이면 가중 없음만")
    parser.add_argument("--with-easy-negatives", nargs="?", const=str(DEFAULT_EASY), default=None,
                        metavar="CSV", help="쉬운 음성 CSV(기본 pairs_features_easy.csv)를 더한 "
                                            "현실 분포 평가")
    args = parser.parse_args(argv)
    easy_path = Path(args.with_easy_negatives) if args.with_easy_negatives else None
    result = run(args.features, out_path=args.out, hist_dir=None if args.no_hist else args.hist_dir,
                 seed=args.seed, bootstrap=args.bootstrap, easy_path=easy_path,
                 unit=args.bootstrap_unit, case_cap=args.case_cap)
    print(report_text(result))
    print(f"\nJSON: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
