"""X3 관념 유사도 — 임베딩 모델 벤치마크와 성능 실측 (보고 전용, assert 없음).

실행 (프로젝트 루트에서. 후보 모델을 처음 쓰면 HuggingFace 에서 내려받는다 — 합계 약 3.4GB):
    ml/venv/bin/python ml/scripts/x3_benchmark.py [--models A B ...] [--seed 0] [--pairs 200]
        [--out PATH]
    ml/venv/bin/python ml/scripts/x3_benchmark.py --perf [--pairs-perf 1000]   # 선정 모델 성능 실측

벤치마크(모델마다):
  1. 22쌍(유사 12·비유사 8·상위개념 2)의 원 코사인
  2. 기준선 c₀ = DB 상표명(has_meaning True) 무작위 --pairs 쌍의 코사인 평균 → 재보정 점수
  3. 분리도 = 유사 최소값 − 비유사 최댓값(원·재보정), 이름당 임베딩 시간(CPU, 1건씩·배치), 모델 크기
--perf 는 DEFAULT_MODEL(또는 MARKLENS_X3_MODEL)로 DB 전체 이름 임베딩 시간·메모리와 1,000쌍 계산
시간을 잰다.
"""

from __future__ import annotations

import argparse
import json
import random
import resource
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from src.axes import x3_semantic as x3  # noqa: E402
from src.axes.x3_semantic import (  # noqa: E402
    SentenceTransformerEmbedder,
    embedding_text,
    has_meaning,
    recalibrate,
)

DEFAULT_METADATA = ML_ROOT / "data" / "kipris_metadata.json"
CANDIDATES = [
    "intfloat/multilingual-e5-base",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "sentence-transformers/LaBSE",
]
# 벤치마크 정답 쌍(작업 명세 2026-09-30). 유사 12 / 비유사 8 / 상위개념 2(중간 이하 기대).
SIMILAR = [
    ("왕", "KING"), ("사과", "APPLE"), ("별", "STAR"), ("바다", "OCEAN"), ("하늘", "SKY"),
    ("검은고양이", "BLACK CAT"), ("봄", "SPRING"), ("달", "MOON"), ("사랑", "LOVE"),
    ("나무", "TREE"), ("태양", "SUN"), ("꽃", "FLOWER"),
]
DISSIMILAR = [
    ("왕", "사과"), ("별", "커피"), ("바다", "나무"), ("사랑", "자동차"), ("하늘", "신발"),
    ("달", "의자"), ("꽃", "컴퓨터"), ("태양", "가방"),
]
HYPERNYM = [("과일", "사과"), ("동물", "고양이")]
GROUPS = [("유사", SIMILAR), ("비유사", DISSIMILAR), ("상위개념", HYPERNYM)]
WARMUP = 3


def load_names(metadata: Path) -> list[str]:
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    names: list[str] = []
    for record in payload.get("trademarks", []):
        name = record.get("상표한글명")
        if isinstance(name, str) and name.strip():
            names.append(name)
    return names


def baseline_pairs(names: list[str], count: int, seed: int) -> list[tuple[str, str]]:
    """has_meaning True 인 DB 이름의 정규화 텍스트에서 무작위 쌍(서로 다른 텍스트)."""
    pool = sorted({embedding_text(n) for n in names if has_meaning(n)})
    rng = random.Random(seed)
    return [tuple(rng.sample(pool, 2)) for _ in range(count)]  # type: ignore[misc]


def cosine_table(
    embedder: SentenceTransformerEmbedder, pairs: list[tuple[str, str]]
) -> list[float]:
    texts = sorted({t for pair in pairs for t in pair})
    vectors = dict(zip(texts, embedder.embed_many(texts)))
    return [float(np.dot(vectors[a], vectors[b])) for a, b in pairs]


def cache_size_mb(model_name: str) -> float | None:
    try:
        from huggingface_hub import scan_cache_dir

        for repo in scan_cache_dir().repos:
            if repo.repo_id == model_name:
                return repo.size_on_disk / 1e6
    except Exception:  # 캐시 스캔 실패는 보고만 비운다
        return None
    return None


def rss_mb() -> float:
    """현재 프로세스 최대 RSS(MB). macOS 는 바이트, Linux 는 KB 단위."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return usage / 1e6 if sys.platform == "darwin" else usage / 1e3


def benchmark_model(name: str, names: list[str], pairs: int, seed: int) -> dict:
    started = time.perf_counter()
    embedder = SentenceTransformerEmbedder(name)
    load_sec = time.perf_counter() - started

    bench_pairs = [(embedding_text(a), embedding_text(b)) for _, group in GROUPS for a, b in group]
    raw = cosine_table(embedder, bench_pairs)
    base_pairs = baseline_pairs(names, pairs, seed)
    base_cos = cosine_table(embedder, base_pairs)
    c0 = statistics.fmean(base_cos)
    scores = [recalibrate(c, c0) for c in raw]

    unique = sorted({t for pair in bench_pairs for t in pair})
    for text in unique[:WARMUP]:
        embedder.embed_many([text])
    single: list[float] = []
    for text in unique:
        t0 = time.perf_counter()
        embedder.embed_many([text])
        single.append((time.perf_counter() - t0) * 1000)
    batch_texts = sorted({t for pair in base_pairs for t in pair})
    t0 = time.perf_counter()
    embedder.embed_many(batch_texts)
    batch_ms = (time.perf_counter() - t0) * 1000 / max(len(batch_texts), 1)

    params = sum(p.numel() for p in embedder.model.parameters())
    return {
        "name": name, "load_sec": load_sec, "dim": embedder.dim, "params_m": params / 1e6,
        "disk_mb": cache_size_mb(name), "c0": c0, "c0_std": statistics.pstdev(base_cos),
        "raw": raw, "scores": scores, "single_ms": statistics.fmean(single),
        "single_max_ms": max(single), "batch_ms": batch_ms, "batch_n": len(batch_texts),
        "gate": [has_meaning(a) and has_meaning(b) for _, g in GROUPS for a, b in g],
    }


def separation(values: list[float]) -> tuple[float, float, float]:
    """(유사 최소, 비유사 최대, 분리도). GROUPS 순서(유사 12, 비유사 8, 상위 2)를 따른다."""
    n_sim, n_dis = len(SIMILAR), len(DISSIMILAR)
    sim_min = min(values[:n_sim])
    dis_max = max(values[n_sim : n_sim + n_dis])
    return sim_min, dis_max, sim_min - dis_max


def report(results: list[dict], names: list[str], pairs: int, seed: int) -> str:
    lines: list[str] = []
    meaningful = sum(1 for n in names if has_meaning(n))
    lines.append(f"# X3 임베딩 모델 벤치마크 ({time.strftime('%Y-%m-%d')}, CPU)")
    lines.append("")
    lines.append(
        f"- DB 상표명 {len(names)}건 중 has_meaning True {meaningful}건 → 기준선 c₀ 는 그중 무작위 "
        f"{pairs}쌍(seed {seed}) 코사인 평균"
    )
    lines.append("- 점수 = clip((cos − c₀)/(1 − c₀), 0, 1). 분리도 = 유사 최소값 − 비유사 최댓값")
    lines.append("")
    lines.append("## 모델 요약")
    lines.append("")
    lines.append(
        "| 모델 | 차원 | 파라미터(M) | 디스크(MB) | 로드(s) | 1건 임베딩(ms, 최대) | 배치 ms/건 "
        "| c₀(±σ) | 원 분리도(유사min/비유사max) | 재보정 분리도 | 유사≥0.7 | 비유사≤0.3 |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|")
    for r in results:
        rs_min, rd_max, rsep = separation(r["raw"])
        ss_min, sd_max, ssep = separation(r["scores"])
        n_sim, n_dis = len(SIMILAR), len(DISSIMILAR)
        ok_sim = sum(1 for s in r["scores"][:n_sim] if s >= 0.7)
        ok_dis = sum(1 for s in r["scores"][n_sim : n_sim + n_dis] if s <= 0.3)
        disk = f"{r['disk_mb']:.0f}" if r["disk_mb"] is not None else "?"
        lines.append(
            f"| {r['name']} | {r['dim']} | {r['params_m']:.0f} | {disk} | {r['load_sec']:.1f} | "
            f"{r['single_ms']:.1f} ({r['single_max_ms']:.0f}) | {r['batch_ms']:.2f} | "
            f"{r['c0']:.3f} (±{r['c0_std']:.3f}) | {rsep:+.3f} ({rs_min:.3f}/{rd_max:.3f}) | "
            f"{ssep:+.3f} ({ss_min:.3f}/{sd_max:.3f}) | {ok_sim}/{n_sim} | {ok_dis}/{n_dis} |"
        )
    lines.append("")
    lines.append("## 쌍별 원 코사인 → 재보정 점수")
    lines.append("")
    short_names = " | ".join(r["name"].split("/")[-1] for r in results)
    header = f"| 구분 | A | B | 게이트 | {short_names} |"
    lines.append(header)
    lines.append("|---|---|---|---|" + "---|" * len(results))
    index = 0
    for label, group in GROUPS:
        for a, b in group:
            cells = [f"{r['raw'][index]:.3f} → {r['scores'][index]:.3f}" for r in results]
            gate = "통과" if results[0]["gate"][index] else "결측(0.0)"
            lines.append(f"| {label} | {a} | {b} | {gate} | " + " | ".join(cells) + " |")
            index += 1
    ranked = sorted(results, key=lambda r: (-separation(r["scores"])[2], r["single_ms"]))
    lines.append("")
    lines.append(
        f"선정(재보정 분리도 우선·속도 차선): **{ranked[0]['name']}** "
        f"(분리도 {separation(ranked[0]['scores'])[2]:+.3f}, 1건 {ranked[0]['single_ms']:.1f}ms)"
    )
    lines.append("BASELINES 후보: " + ", ".join(f'"{r["name"]}": {r["c0"]:.4f}' for r in results))
    return "\n".join(lines)


def perf(names: list[str], pairs: int, seed: int) -> str:
    """선정 모델로 DB 이름 사전 계산 시간·메모리, 1,000쌍 계산 시간(cold/warm)."""
    lines = [f"# X3 성능 실측 ({time.strftime('%Y-%m-%d')}, CPU, 모델 {x3.configured_model()})", ""]
    rss0 = rss_mb()
    t0 = time.perf_counter()
    embedder = x3._get_embedder()
    load = time.perf_counter() - t0
    rss1 = rss_mb()
    lines.append(f"- 모델 로드 {load:.1f}s, 최대 RSS {rss0:.0f} → {rss1:.0f} MB")
    texts_all = sorted({embedding_text(n) for n in names})
    t0 = time.perf_counter()
    embedder.embed_many(texts_all)
    all_sec = time.perf_counter() - t0
    meaningful = [n for n in names if has_meaning(n)]
    texts_meaning = sorted({embedding_text(n) for n in meaningful})
    t0 = time.perf_counter()
    embedder.embed_many(texts_meaning)
    meaning_sec = time.perf_counter() - t0
    rss2 = rss_mb()
    lines.append(
        f"- DB 이름 {len(names)}건(고유 텍스트 {len(texts_all)}) 배치 임베딩 {all_sec:.1f}s "
        f"({all_sec * 1000 / max(len(texts_all), 1):.1f} ms/건); has_meaning {len(meaningful)}건"
        f"(고유 {len(texts_meaning)}) {meaning_sec:.1f}s; 최대 RSS {rss2:.0f} MB"
    )
    rng = random.Random(seed)
    sample_pairs = [tuple(rng.sample(meaningful, 2)) for _ in range(pairs)]
    x3._embed_cached.cache_clear()
    t0 = time.perf_counter()
    cold = [x3.semantic_similarity(a, b) for a, b in sample_pairs]
    cold_sec = time.perf_counter() - t0
    t0 = time.perf_counter()
    warm = [x3.semantic_similarity(a, b) for a, b in sample_pairs]
    warm_sec = time.perf_counter() - t0
    assert cold == warm
    lines.append(
        f"- has_meaning 이름 {pairs}쌍 semantic_similarity: cold {cold_sec:.2f}s"
        f"(임베딩 1건씩 캐시 채움, 캐시 {x3._embed_cached.cache_info().currsize}건) → "
        f"warm {warm_sec * 1000:.0f} ms; "
        f"점수 평균 {statistics.fmean(cold):.3f}, ≥0.7 {sum(s >= 0.7 for s in cold)}쌍"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--models", nargs="+", default=CANDIDATES)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--pairs", type=int, default=200, help="기준선 c₀ 표본 쌍 수")
    parser.add_argument("--pairs-perf", type=int, default=1000, help="--perf 의 쌍 수")
    parser.add_argument("--out", type=Path, help="보고서(markdown) 저장 경로")
    parser.add_argument("--perf", action="store_true", help="선정 모델 성능 실측만")
    args = parser.parse_args()

    names = load_names(args.metadata)
    if args.perf:
        text = perf(names, args.pairs_perf, args.seed)
    else:
        results = []
        for name in args.models:
            print(f"... {name}", file=sys.stderr, flush=True)
            results.append(benchmark_model(name, names, args.pairs, args.seed))
        text = report(results, names, args.pairs, args.seed)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
