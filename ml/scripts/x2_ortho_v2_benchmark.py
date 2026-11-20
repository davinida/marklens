"""철자 축 v1 대 v2 측정(한 번) — 통합 모델 설계 §7-5·X2 설계 §9. KIPRIS 호출 0.

    ml/venv/bin/python ml/scripts/x2_ortho_v2_benchmark.py   # 특징 파일에 x2_text_d_v2 열 필요

입력: `pairs_features.csv`(1·2차 597행)·`pairs_features_easy.csv`(쉬운 음성 700쌍)의 철자 v1 열
(`x2_text`·`x2_text_d`)과 v2 열(`x2_text_v2`·`x2_text_d_v2`) — `pairs_features.py` 가 같은 쌍에 두
정의를 모두 계산한다. 통합 모델 입력은 식별력 적용판 `x2_text_d` 이므로 주 비교는 그 열이다.

무엇을 재나(결과를 보기 전에 고정 — PROCEED·LABEL):
  1. 문제 사례: 철자 v1 = 1.0 인데 두 이름의 요부 토큰(정규화 + 식별력 제외 뒤) 구성이 다른 쌍 —
     띄어쓰기만 다른 쌍(이어 붙인 문자열이 같음)과 공통 토큰이 일부뿐인 쌍으로 나눈다.
  2. 사건 가중(한 사건의 가중 합 상한 3)·묶음 단위(심판번호 + 같은 표장 쌍) 부트스트랩 1,000회
     로 v1 대 v2: 어려운 문제 AUC, 판단축에 외관이 있는 부분집합, 쉬운 음성을 섞은 AUC, 같은 묶음을
     다시 뽑는 짝 차이(v2 − v1), 값이 바뀐 쌍의 수와 그 쌍의 유사 비율. 라벨은 축별 벤치마크와 같은
     표장 라벨(최종 라벨은 참고).
  3. 진행 조건: 어려운 문제·섞은 AUC 모두 짝 차이 CI 하한 > −0.02. 미달이면 재학습하지 않고 v1 유지.
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

from src.axes.distinctiveness import load_distinctiveness  # noqa: E402
from src.axes.x1_phonetic import normalize_name  # noqa: E402

from scripts import pairs_features as pf  # noqa: E402
from scripts import train_risk_model as tr  # noqa: E402
from scripts import train_risk_model_v14 as t4  # noqa: E402  (가중 AUC·묶음 부트스트랩)

DEFAULT_BASE = tr.DEFAULT_BASE
DEFAULT_OUT_STEM = "x2_ortho_v2"
V1, V2 = "x2_text_d", "x2_text_d_v2"  # 주 비교(식별력 적용판 — 통합 모델 입력)
RAW_V1, RAW_V2 = "x2_text", "x2_text_v2"  # 참고(식별력 적용 전)
LABEL = "표장"  # 축별 벤치마크(axes_benchmark)와 같은 라벨 — 최종 라벨은 참고
METRIC_BOOTSTRAP = 1000
MARGIN = -0.02
PROCEED = {
    "조건": ("어려운 문제(1·2차 이름 있는 행)와 쉬운 음성을 섞은 집합 모두에서 x2_text_d 의 가중 "
             f"AUC 짝 차이(v2 − v1) 95% CI 하한 > {MARGIN}"),
    "라벨": "표장 라벨(축별 벤치마크와 같음)",
    "가중·묶음": "사건 가중(상한 3) · 묶음 = 심판번호 + 같은 표장 쌍 키(v1.4 평가와 같음)",
    "미달이면": "재학습하지 않고 철자 v1 유지로 보고",
}
CHANGE_EPS = 5e-5  # CSV 는 소수 넷째 자리 — 반올림 차이는 바뀐 것으로 세지 않는다


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _round(value, digits: int = 4):
    return None if value is None else round(float(value), digits)


def load(features_path: Path, easy_path: Path) -> list[dict]:
    """심결 행 + 쉬운 음성 행. 철자 열을 숫자로, 사건 가중·묶음을 `_w`·`_group` 에."""
    rows = tr.load_rows(features_path, easy_path)
    if rows and V2 not in rows[0]:
        raise SystemExit(f"{features_path} 에 {V2} 열이 없습니다 — pairs_features.py 로 다시 "
                         "만드세요")
    for row in rows:
        for column in (V1, V2, RAW_V1, RAW_V2):
            row[column] = _float(row.get(column))
    weights = t4.case_weights(rows)
    groups = t4.group_ids(rows)
    for row, weight, group in zip(rows, weights, groups):
        row["_w"], row["_group"] = float(weight), str(group)
    return rows


def labels(rows: list[dict], kind: str = LABEL) -> np.ndarray:
    column = "표장라벨" if kind == "표장" else "최종라벨"
    return np.asarray([1 if row.get(column) == "유사" else
                       (0 if row.get(column) == "비유사" else -1) for row in rows], dtype=np.int64)


# ---- 1. 문제 사례 -------------------------------------------------------------------------------

def spelling_token_lists(rows: list[dict], label_rows: list[dict], db_records: list[dict],
                         model) -> list[tuple[list[str], list[str]] | None]:
    """행마다 철자 축이 비교한 토큰(정규화 + 식별력 제외 뒤, name_axes 와 같은 유사군) — 이름이
    한쪽이라도 없으면 None. 심결 행은 labels.csv 의 대상 행 순서(특징 파일과 같은 순서)로 맞춘다."""
    trial = [row for row in rows if row["pair_source"] == "trial"]
    easy = [row for row in rows if row["pair_source"] != "trial"]
    targets = pf.target_rows(label_rows)
    if len(targets) != len(trial):
        raise ValueError(f"labels.csv 대상 행 {len(targets)} 과 특징 행 {len(trial)} 이 "
                         "다릅니다")
    goods_by_row: list[frozenset[str]] = []
    for target, row in zip(targets, trial):
        if target["심판번호"] != row["심판번호"]:
            raise ValueError(f"행 순서가 다릅니다: {target['심판번호']} / {row['심판번호']}")
        goods_by_row.append(pf._codes(target.get("goods_codes_this"))  # noqa: SLF001
                            | pf._codes(target.get("goods_codes_prior")))  # noqa: SLF001
    for goods_a, goods_b in pf.easy_pair_goods(easy, trial, label_rows, db_records):
        goods_by_row.append((goods_a or frozenset()) | (goods_b or frozenset()))
    out = []
    for row, goods in zip(trial + easy, goods_by_row):
        name_a = model.split_goods_suffix(row.get("이름A") or "")
        name_b = model.split_goods_suffix(row.get("이름B") or "")
        if not (name_a and name_b):
            out.append(None)
            continue
        generic = model.pair_generic(name_a, name_b, goods or None)
        out.append((normalize_name(name_a, extra_generic=generic),
                    normalize_name(name_b, extra_generic=generic)))
    order = {id(row): i for i, row in enumerate(trial + easy)}
    return [out[order[id(row)]] for row in rows]


def problem_cases(rows: list[dict], tokens: list) -> dict:
    """철자 v1 = 1.0 인 쌍 가운데 요부 토큰 구성이 다른 쌍."""
    cases = []
    counts = {"v1_1.0": 0, "토큰_구성_같음": 0, "띄어쓰기만_다름": 0, "공통_토큰_일부": 0}
    for row, pair in zip(rows, tokens):
        if pair is None or not (row[V1] >= 1.0 - 1e-9):
            continue
        counts["v1_1.0"] += 1
        tokens_a, tokens_b = pair
        if sorted(tokens_a) == sorted(tokens_b):
            counts["토큰_구성_같음"] += 1
            continue
        kind = "띄어쓰기만_다름" if "".join(tokens_a) == "".join(tokens_b) else "공통_토큰_일부"
        counts[kind] += 1
        cases.append({"출처": row["pair_source"], "심판번호": row["심판번호"],
                      "이름A": row.get("이름A"), "이름B": row.get("이름B"),
                      "토큰A": tokens_a, "토큰B": tokens_b, "구분": kind,
                      "표장라벨": row.get("표장라벨") or "", "최종라벨": row.get("최종라벨") or "",
                      "판단축": row.get("판단축") or "", "v1": _round(row[V1]),
                      "v2": _round(row[V2])})
    by_source = {}
    for case in cases:
        key = (case["출처"], case["구분"])
        by_source[f"{key[0]}·{key[1]}"] = by_source.get(f"{key[0]}·{key[1]}", 0) + 1
    partial = [case for case in cases
               if case["구분"] == "공통_토큰_일부" and case["출처"] == "trial"]
    labelled = [case for case in partial if case["표장라벨"] in ("유사", "비유사")]
    return {"수": counts, "출처·구분별": by_source, "사례": cases,
            "공통_토큰_일부(심결)_표장라벨": {
                "유사": sum(1 for case in labelled if case["표장라벨"] == "유사"),
                "비유사": sum(1 for case in labelled if case["표장라벨"] == "비유사"),
                "없음": len(partial) - len(labelled)}}


# ---- 2. 축 측정 -------------------------------------------------------------------------------

def subsets(rows: list[dict], y: np.ndarray, column: str) -> dict[str, np.ndarray]:
    value = np.asarray([row[column] for row in rows])
    trial = np.asarray([row["pair_source"] == "trial" for row in rows])
    judged = np.asarray(["외관" in (row.get("판단축") or "") for row in rows])
    rounds = np.asarray([row.get("회차", "") for row in rows])
    family = tr.families(rows)
    base = ~np.isnan(value) & (y >= 0)
    return {
        "어려운 문제(a)": base & trial,
        "판단축 외관(b)": base & trial & judged,
        "1차": base & trial & (rounds == "1"), "2차": base & trial & (rounds == "2"),
        "문자계": base & trial & (family == "text"), "도형계": base & trial & (family == "figure"),
        "쉬운 음성 섞음": base,
    }


def compare(rows: list[dict], kind: str, old: str, new: str, *, rounds: int, seed: int) -> dict:
    """부분집합마다 v1·v2 가중 AUC(CI)와 짝 차이(v2 − v1). 두 열이 모두 있는 행만."""
    y = labels(rows, kind)
    weights = np.asarray([row["_w"] for row in rows])
    boot = t4.Bootstrap(np.asarray([row["_group"] for row in rows]), rounds, seed)
    score_old = np.nan_to_num(np.asarray([row[old] for row in rows]), nan=-1.0)
    score_new = np.nan_to_num(np.asarray([row[new] for row in rows]), nan=-1.0)
    both_new = subsets(rows, y, new)
    out = {}
    for name, mask in subsets(rows, y, old).items():
        mask = mask & both_new[name]
        if not (mask & (y == 1)).any() or not (mask & (y == 0)).any():
            continue
        entry = {"v1": t4.metric_block(score_old, y.astype(float), weights, mask, boot),
                 "v2": t4.metric_block(score_new, y.astype(float), weights, mask, boot)}
        entry["짝_차이"] = t4.paired_difference(score_new, score_old, y.astype(float), weights,
                                             mask, boot)["auc"]
        out[name] = entry
    return out


def changed_pairs(rows: list[dict]) -> dict:
    """x2_text_d 가 바뀐 쌍의 수(오름·내림)와 그 쌍의 유사 비율(표장·최종, 가중 포함)."""
    out = {}
    for source in ("trial", "easy"):
        picked = [row for row in rows if (row["pair_source"] == "trial") == (source == "trial")
                  and not np.isnan(row[V1]) and not np.isnan(row[V2])]
        changed = [row for row in picked if abs(row[V2] - row[V1]) > CHANGE_EPS]
        down = [row for row in changed if row[V2] < row[V1]]
        entry = {"n": len(picked), "바뀐_쌍": len(changed), "내려감": len(down),
                 "올라감": len(changed) - len(down),
                 "변화_평균": _round(np.mean([row[V2] - row[V1] for row in changed]))
                 if changed else None,
                 "v1_1.0_에서_내려감": sum(1 for row in down if row[V1] >= 1.0 - 1e-9)}
        if source == "trial":
            for kind in ("표장", "최종"):
                column = "표장라벨" if kind == "표장" else "최종라벨"
                labelled = [row for row in changed if row.get(column) in ("유사", "비유사")]
                similar = [row for row in labelled if row.get(column) == "유사"]
                weight = sum(row["_w"] for row in labelled)
                entry[f"{kind}_라벨"] = {
                    "있음": len(labelled), "유사": len(similar),
                    "유사_비율": _round(len(similar) / len(labelled)) if labelled else None,
                    "유사_비율_가중": _round(sum(row["_w"] for row in similar) / weight)
                    if weight else None}
                unchanged = [row for row in picked if row not in changed
                             and row.get(column) in ("유사", "비유사")]
                entry[f"{kind}_라벨"]["바뀌지_않은_쌍의_유사_비율"] = _round(
                    sum(1 for row in unchanged if row.get(column) == "유사") / len(unchanged)
                ) if unchanged else None
        out[source] = entry
    return out


def decide(main: dict) -> dict:
    lows = {name: (main.get(name) or {}).get("짝_차이", {}).get("ci95", [None, None])[0]
            for name in ("어려운 문제(a)", "쉬운 음성 섞음")}
    passed = all(low is not None and low > MARGIN for low in lows.values())
    return {"조건": PROCEED, "CI_하한": lows, "진행": passed,
            "판정": "진행 — 철자 v2 로 재학습" if passed else "멈춤 — 철자 v1 유지"}


def run(features_path: Path, easy_path: Path, *, out_dir: Path, labels_path: Path,
        metadata_path: Path, rounds: int = METRIC_BOOTSTRAP, seed: int = 0,
        model=None) -> dict:
    """model: 문제 사례의 토큰을 다시 계산할 식별력 모델(기본 load_distinctiveness — 특징을 만든
    모델과 같아야 한다)."""
    rows = load(features_path, easy_path)
    model = model or load_distinctiveness()
    tokens = spelling_token_lists(rows, pf.read_csv(labels_path),
                                  pf.read_db_records(metadata_path), model)
    main = compare(rows, LABEL, V1, V2, rounds=rounds, seed=seed)
    results = {
        "기준일": date.today().isoformat(), "진행_조건": PROCEED,
        "문제_사례": problem_cases(rows, tokens),
        "x2_text_d(표장)": main,
        "x2_text_d(최종, 참고)": compare(rows, "최종", V1, V2, rounds=rounds, seed=seed),
        "x2_text(표장, 식별력 전, 참고)": compare(rows, LABEL, RAW_V1, RAW_V2, rounds=rounds,
                                          seed=seed),
        "바뀐_쌍": changed_pairs(rows),
        "판정": decide(main),
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{DEFAULT_OUT_STEM}_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / f"{DEFAULT_OUT_STEM}_report.md").write_text(report_text(results), encoding="utf-8")
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
    verdict = results["판정"]
    lines = [f"# 철자 축 v1 대 v2 ({results['기준일']})", "", f"## 판정 — {verdict['판정']}", "",
             f"- 조건: {verdict['조건']['조건']}",
             f"- CI 하한: {verdict['CI_하한']}", ""]
    problems = results["문제_사례"]
    lines += ["## 문제 사례 — 철자 v1 = 1.0 인데 요부 토큰 구성이 다른 쌍", "",
              f"- 수: {problems['수']}", f"- 출처·구분별: {problems['출처·구분별']}",
              "- 공통 토큰 일부(심결)의 표장 라벨: "
              f"{problems['공통_토큰_일부(심결)_표장라벨']}", "",
              "| 출처 | 이름 A | 이름 B | 토큰 A | 토큰 B | 구분 | 표장 | 최종 | v1 | v2 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for case in problems["사례"]:
        lines.append(f"| {case['출처']} | {case['이름A']} | {case['이름B']} | "
                     f"{' '.join(case['토큰A'])} | {' '.join(case['토큰B'])} | {case['구분']} | "
                     f"{case['표장라벨'] or '—'} | {case['최종라벨']} | {_f(case['v1'])} | "
                     f"{_f(case['v2'])} |")
    for title in ("x2_text_d(표장)", "x2_text_d(최종, 참고)", "x2_text(표장, 식별력 전, 참고)"):
        lines += ["", f"## {title} — 사건 가중 AUC(95% CI), 짝 차이 v2 − v1", "",
                  "| 부분집합 | n(유사/비유사) | v1 | v2 | 짝 차이 | v1 비가중 | v2 비가중 |",
                  "|---|---|---|---|---|---|---|"]
        for name, entry in results[title].items():
            old, new = entry["v1"], entry["v2"]
            lines.append(f"| {name} | {old['n']}({old['유사']}/{old['비유사']}) | "
                         f"{_f(old['auc_가중'])}{_ci(old.get('auc_가중_ci95'))} | "
                         f"{_f(new['auc_가중'])}{_ci(new.get('auc_가중_ci95'))} | "
                         f"{_diff(entry['짝_차이'])} | {_f(old['auc'])} | {_f(new['auc'])} |")
    lines += ["", "## 바뀐 쌍(x2_text_d)", "", "```",
              json.dumps(results["바뀐_쌍"], ensure_ascii=False, indent=1), "```"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--features", type=Path, default=tr.DEFAULT_FEATURES)
    parser.add_argument("--easy", type=Path, default=tr.DEFAULT_EASY)
    parser.add_argument("--labels", type=Path, default=pf.DEFAULT_LABELS)
    parser.add_argument("--metadata", type=Path, default=pf.DEFAULT_METADATA)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--bootstrap", type=int, default=METRIC_BOOTSTRAP)
    args = parser.parse_args(argv)
    results = run(args.features, args.easy, out_dir=args.out_dir, labels_path=args.labels,
                  metadata_path=args.metadata, rounds=args.bootstrap)
    print(report_text(results))
    return 0 if results["판정"]["진행"] else 3


if __name__ == "__main__":
    sys.exit(main())
