"""검색 응답 시간 벤치마크 — 실제 엔진(CLIP·OCR·X3)으로 검색만 돌려 시간을 잰다. KIPRIS 호출 0.

질의·방식은 이름 없는 하한 계산(`nameless_search_thresholds.py`)의 평가용 검색과 같다:
표본 A(심사를 거치지 않은 표장 184질의)·B(DB 300질의) × 이미지만 · 이미지+상품 ·
이름+이미지+상품. 하한·모델 파일은 건드리지 않는다(같은 스크립트의 `phase_b` 를 그대로 부른다).

    ml/venv/bin/python ml/scripts/search_latency_benchmark.py --out <폴더>

결과: <폴더>/results.json — 엔진 기동 시간, 표본·방식별 응답 시간(중앙값·95%·최대), 가장 느린
요청 10개의 단계별 시간, 단계 중앙값, 요청별 시간·단계·후보(출원번호·등급·위험도·계수 집합 —
고치기 전후 결과 비교용). <폴더>/report.md 는 같은 내용의 표.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "ml", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts import nameless_search_thresholds as nst  # noqa: E402


def run(out: Path, limit: int = 0) -> dict:
    timing: dict[str, float] = {}
    load_engine = nst.load_engine

    def timed_load(model_path):
        started = time.perf_counter()
        loaded = load_engine(model_path)
        timing["엔진_기동_s"] = round(time.perf_counter() - started, 2)
        return loaded

    nst.load_engine = timed_load
    args = argparse.Namespace(model=nst.DEFAULT_MODEL, metadata=nst.DEFAULT_METADATA,
                              labels=nst.DEFAULT_LABELS, trial_list=nst.DEFAULT_LIST,
                              image_pairs=nst.DEFAULT_IMAGE_PAIRS, aliases=nst.DEFAULT_ALIASES,
                              limit=limit)
    started = time.perf_counter()
    context = nst.prepare(args)
    timing["준비_s"] = round(time.perf_counter() - started, 2)
    ms, applicants, aliases = context["ms"], context["applicants"], context["aliases"]
    started = time.perf_counter()
    rows = {"A": nst.phase_b(ms, context["A"], context["service"], applicants, aliases),
            "B": nst.phase_b(ms, context["B"], context["direct"], applicants, aliases)}
    timing["검색_s"] = round(time.perf_counter() - started, 1)
    requests = [{"표본": sample, "질의": row["질의"], "방식": label, "ms": entry["ms"],
                 "단계": entry["단계"], "후보": entry["후보"]}
                for sample, sample_rows in rows.items() for row in sample_rows
                for label, entry in row["방식"].items()]
    results = {
        "기준일": date.today().isoformat(), "python": platform.python_version(),
        "시간": timing, "질의": {sample: len(context[sample]) for sample in ("A", "B")},
        "분포": {sample: nst.distribution(sample_rows) for sample, sample_rows in rows.items()},
        "가장_느린_10": nst.slowest(rows),
        "단계_중앙값": nst.stage_medians(rows),
        "요청": requests,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")
    (out / "report.md").write_text(report(results), encoding="utf-8")
    return results


def report(results: dict) -> str:
    lines = [f"# 검색 응답 시간 ({results['기준일']})", "",
             f"엔진 기동 {results['시간']['엔진_기동_s']}초 · 검색 {results['시간']['검색_s']}초 · "
             f"질의 A {results['질의']['A']}·B {results['질의']['B']}", "",
             "| 표본 | 방식 | 검색 | 중앙값 ms | 95% ms | 최대 ms |",
             "|---|---|---:|---:|---:|---:|"]
    for sample, modes in results["분포"].items():
        for label, item in modes.items():
            ms = item["응답_ms"]
            lines.append(f"| {sample} | {label} | {item['검색']} | {ms['중앙값']} | {ms['95%']} | "
                         f"{ms['최대']} |")
    lines += ["", "## 가장 느린 요청 10개", "",
              "| 표본 | 질의 | 방식 | ms | 가장 긴 단계 | 단계별 ms |",
              "|---|---|---|---:|---|---|"]
    for item in results["가장_느린_10"]:
        stages = " · ".join(f"{k} {v:.0f}" for k, v in item["단계"].items() if v >= 1)
        lines.append(f"| {item['표본']} | {item['질의']} | {item['방식']} | {item['ms']} | "
                     f"{item['가장_긴_단계']} | {stages} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="결과 폴더")
    parser.add_argument("--limit", type=int, default=0,
                        help="표본마다 앞 N 질의만(배관 확인용)")
    args = parser.parse_args(argv)
    results = run(args.out, args.limit)
    print(report(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
