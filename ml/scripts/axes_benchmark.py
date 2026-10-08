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

# (열, 표시, 판단축 단어, 라벨 종류, 게이트 플래그 열)
AXES = (
    ("x1", "X1 호칭", "호칭", "표장", ("has_pron_a", "has_pron_b")),
    ("x2_text", "X2 문자 외관(철자)", "외관", "표장", ("has_spelling_a", "has_spelling_b")),
    ("x2_fig", "X2 도형 크롭 CLIP", "외관", "표장", ("has_fig",)),
    ("x2_whole", "X2 전체 이미지 CLIP", "외관", "표장", ("has_image",)),
    ("x3", "X3 관념", "관념", "표장", ("has_meaning_a", "has_meaning_b")),
    ("x4", "X4 상품 견련성", "상품", "최종", ("has_goods",)),
)
NAME_AXES = ("x1", "x2_text", "x3")
SOURCES = ("kipris", "본문", "ocr")
KINDS = ("거절결정불복", "무효", "권리범위확인(적극적)", "권리범위확인(소극적)")
CORRELATION_AXES = ("x1", "x2_text", "x2_fig", "x2_whole", "x3", "x4")
NUMERIC = ("x1", "x2_text", "x2_fig", "x2_whole", "x3", "x3_raw", "x4")
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


def evaluate_subset(scores: np.ndarray, labels: np.ndarray, *, seed: int, bootstrap: int) -> dict:
    similar, dissimilar = scores[labels == 1], scores[labels == 0]
    low, high = x2b.bootstrap_auc(scores, labels, rounds=bootstrap, seed=seed)
    return {
        "n": int(scores.size), "n_유사": int(similar.size), "n_비유사": int(dissimilar.size),
        "auc": x2b._round(x2b.roc_auc(scores, labels)), "auc_ci95": [low, high],
        "유사_중앙값": x2b._round(float(np.median(similar))) if similar.size else None,
        "비유사_중앙값": x2b._round(float(np.median(dissimilar))) if dissimilar.size else None,
        "분리도_Q1유사-Q3비유사": x2b.separation(similar, dissimilar),
    }


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
        chosen = mask & valid
        subsets[key] = {"설명": description, **evaluate_subset(
            scores[chosen], labels[chosen], seed=seed, bootstrap=bootstrap
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
            **evaluate_subset(x3_raw[chosen], mark[chosen], seed=seed, bootstrap=bootstrap),
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


def run(features_path: Path, *, out_path: Path, hist_dir: Path | None, seed: int = 0,
        bootstrap: int = x2b.BOOTSTRAP_ROUNDS) -> dict:
    features = load_features(features_path)
    mark = labels_for(features, "표장")
    result: dict = {
        "기준일": date.today().isoformat(), "특징_파일": str(features_path),
        "대상_행": len(features),
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
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--hist-dir", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--no-hist", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--bootstrap", type=int, default=x2b.BOOTSTRAP_ROUNDS)
    args = parser.parse_args(argv)
    result = run(args.features, out_path=args.out, hist_dir=None if args.no_hist else args.hist_dir,
                 seed=args.seed, bootstrap=args.bootstrap)
    print(report_text(result))
    print(f"\nJSON: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
