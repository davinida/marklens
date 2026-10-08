"""X2 외관 — 심결 이미지 쌍으로 현재 CLIP 외관 유사도의 분리 성능을 잰다(보고 전용, assert 없음).

실행 (프로젝트 루트에서, 실제 모델. MARKLENS_FAKE_ML 없이):
    ml/venv/bin/python ml/scripts/x2_benchmark.py [--pairs ml/data/trials/image_pairs.csv]
        [--cache ml/data/trials/x2_cache_v0.npz] [--out ml/data/trials/x2_benchmark_v0.json]
        [--hist ml/data/trials/x2_hist_v0.png] [--seed 0] [--shuffles 200]

입력: ml/scripts/trials_extract_images.py 가 만든 image_pairs.csv(이미지A = 이 사건 표장,
      이미지B = 상대 표장, 라벨 = 심결의 유사/비유사).
점수: ml/src/embedding.py 의 encode_image(전처리 계약 포함)로 두 이미지를 임베딩하고,
      ml/src/search.py 의 build_index + search(FAISS inner product = 정규화 벡터의 코사인)로 쌍
      점수를 읽는다 — 서비스 `/search` 와 같은 경로. 임베딩은 --cache(npz, 파일 sha256 키)에
      저장해 변형 실험에서 재사용한다.
지표(부분집합마다): ROC AUC, 유사·비유사 점수 분포(평균·중앙값·사분위), 정확도 최대 임계값,
      분리도(유사 하위 25% − 비유사 상위 25%), 라벨을 섞은 AUC 기준선(평균·5~95%).
부분집합: (a) 전체 (b) 판단축에 외관 포함 (c) 상표유형 도형·결합-도형요부 (d) 문자
      (e) 연결 신뢰도 high. (b)·(c)가 X2 의 공정한 시험대다 — 문자상표 쌍은 호칭·관념으로 갈린
      사건이라 외관 점수가 라벨과 맞을 이유가 없다.
산출: JSON + 표(stdout) + 점수 분포 히스토그램 PNG(유사·비유사 겹침, Pillow 로 그림).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from datetime import date
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

# macOS Apple Silicon: faiss(src.search)보다 torch(src.embedding)를 먼저 import 한다
# (ml/src/search.py 주석).
from src.contracts import EMBEDDING_CONTRACT_VERSION, MODEL_NAME, PRETRAINED  # noqa: E402
from src.embedding import encode_image  # noqa: E402, I001
from src.preprocess import DEFAULT_PREPROCESS_VERSION  # noqa: E402
from src.search import build_index, search  # noqa: E402

DEFAULT_BASE = ML_ROOT / "data" / "trials"
DEFAULT_PAIRS = DEFAULT_BASE / "image_pairs.csv"
DEFAULT_CACHE = DEFAULT_BASE / "x2_cache_v0.npz"
DEFAULT_OUT = DEFAULT_BASE / "x2_benchmark_v0.json"
DEFAULT_HIST = DEFAULT_BASE / "x2_hist_v0.png"
FIGURE_TYPES = ("도형", "결합-도형요부")
SUBSETS = (
    ("a_전체", "전체"),
    ("b_외관축", "판단축에 외관 포함"),
    ("c_도형", "상표유형 도형·결합-도형요부"),
    ("d_문자", "상표유형 문자"),
    ("e_신뢰high", "연결 신뢰도 high"),
)
FAILURES_KEY = "__failures__"


def load_pairs(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["_label"] = 1 if row["라벨"] == "유사" else 0
    return rows


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _contract() -> dict:
    return {
        "model": MODEL_NAME, "pretrained": PRETRAINED, "embedding": EMBEDDING_CONTRACT_VERSION,
        "preprocess": DEFAULT_PREPROCESS_VERSION,
    }


def load_cache(path: Path) -> dict[str, np.ndarray]:
    """sha256 → 임베딩. 모델·전처리 계약이 다르면 버린다."""
    if not Path(path).exists():
        return {}
    with np.load(path, allow_pickle=False) as data:
        meta = json.loads(str(data["meta"]))
        if meta.get("contract") != _contract():
            return {}
        return {key: vec for key, vec in zip(data["keys"].tolist(), data["embeddings"])}


def save_cache(path: Path, cache: dict[str, np.ndarray]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    keys = sorted(cache)
    np.savez(
        path,
        keys=np.array(keys),
        embeddings=np.stack([cache[key] for key in keys]).astype(np.float32),
        meta=np.array(json.dumps({"contract": _contract()})),
    )


def embed_paths(paths: list[Path], cache_path: Path, *, encode=encode_image) -> dict:
    """경로 → 임베딩. 캐시에 없는 파일만 encode 한다. 실패한 파일은 FAILURES_KEY 에 사유로."""
    cache = load_cache(cache_path)
    result: dict = {}
    failures: dict[str, str] = {}
    added = 0
    for path in paths:
        key = file_sha256(path)
        if key not in cache:
            try:
                cache[key] = np.asarray(encode(path), dtype=np.float32)
                added += 1
            except (ValueError, OSError) as exc:
                failures[str(path)] = str(exc)
                continue
        result[str(path)] = cache[key]
    if added:
        save_cache(cache_path, cache)
    result[FAILURES_KEY] = failures
    return result


def pair_scores(pairs: list[dict], embeddings: dict, base: Path) -> np.ndarray:
    """쌍마다 FAISS inner product(= 코사인). 임베딩이 없는 쌍은 NaN."""
    b_paths = sorted({
        str(base / p["이미지B"]) for p in pairs if str(base / p["이미지B"]) in embeddings
    })
    scores = np.full(len(pairs), np.nan, dtype=np.float32)
    if not b_paths:
        return scores
    index = build_index(np.stack([embeddings[path] for path in b_paths]))
    position = {path: i for i, path in enumerate(b_paths)}
    for i, pair in enumerate(pairs):
        a_path, b_path = str(base / pair["이미지A"]), str(base / pair["이미지B"])
        if a_path not in embeddings or b_path not in embeddings:
            continue
        distances, indices = search(index, embeddings[a_path], k=index.ntotal)
        hit = np.where(indices == position[b_path])[0]
        if hit.size:
            scores[i] = float(distances[hit[0]])
    return scores


def roc_auc(scores: np.ndarray, labels: np.ndarray) -> float | None:
    """Mann-Whitney 순위 AUC(동점은 0.5). 한쪽 클래스가 비면 None."""
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    positive, negative = scores[labels == 1], scores[labels == 0]
    if positive.size == 0 or negative.size == 0:
        return None
    greater = (positive[:, None] > negative[None, :]).sum()
    equal = (positive[:, None] == negative[None, :]).sum()
    return float((greater + 0.5 * equal) / (positive.size * negative.size))


def best_threshold(scores: np.ndarray, labels: np.ndarray) -> tuple[float | None, float | None]:
    """정확도가 최대인 임계값(점수 ≥ 임계값 → 유사). 동률이면 낮은 임계값."""
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    if scores.size == 0:
        return None, None
    unique = np.unique(scores)
    midpoints = (unique[:-1] + unique[1:]) / 2
    candidates = np.concatenate(([unique[0] - 1e-6], midpoints, [unique[-1] + 1e-6]))
    best_value, best_accuracy = None, -1.0
    for threshold in candidates:
        accuracy = float(((scores >= threshold).astype(int) == labels).mean())
        if accuracy > best_accuracy + 1e-12:
            best_value, best_accuracy = float(threshold), accuracy
    return best_value, best_accuracy


def distribution(values: np.ndarray) -> dict:
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return {"n": 0}
    q1, median, q3 = np.percentile(values, [25, 50, 75])
    return {
        "n": int(values.size), "mean": round(float(values.mean()), 4),
        "median": round(float(median), 4), "q1": round(float(q1), 4), "q3": round(float(q3), 4),
        "min": round(float(values.min()), 4), "max": round(float(values.max()), 4),
    }


def separation(similar: np.ndarray, dissimilar: np.ndarray) -> float | None:
    """유사 하위 25%(Q1) − 비유사 상위 25%(Q3). 양수면 사분위 범위가 겹치지 않는다."""
    if len(similar) == 0 or len(dissimilar) == 0:
        return None
    return round(float(np.percentile(similar, 25) - np.percentile(dissimilar, 75)), 4)


def shuffled_auc(scores: np.ndarray, labels: np.ndarray, *, seed: int = 0,
                 rounds: int = 200) -> dict:
    """라벨을 섞은 AUC 기준선(≈0.5) — 평균·5%·95%."""
    rng = random.Random(seed)
    labels = list(np.asarray(labels, dtype=np.int64))
    values = []
    for _ in range(rounds):
        shuffled = labels[:]
        rng.shuffle(shuffled)
        auc = roc_auc(scores, np.asarray(shuffled))
        if auc is not None:
            values.append(auc)
    if not values:
        return {"mean": None}
    return {
        "mean": round(float(np.mean(values)), 4),
        "p5": round(float(np.percentile(values, 5)), 4),
        "p95": round(float(np.percentile(values, 95)), 4), "rounds": len(values),
    }


def subset_mask(pairs: list[dict], key: str) -> np.ndarray:
    if key == "a_전체":
        return np.ones(len(pairs), dtype=bool)
    if key == "b_외관축":
        return np.array(["외관" in (p.get("판단축") or "") for p in pairs], dtype=bool)
    if key == "c_도형":
        return np.array([(p.get("상표유형") or "") in FIGURE_TYPES for p in pairs], dtype=bool)
    if key == "d_문자":
        return np.array([(p.get("상표유형") or "") == "문자" for p in pairs], dtype=bool)
    if key == "e_신뢰high":
        return np.array([p.get("연결신뢰도") == "high" for p in pairs], dtype=bool)
    raise ValueError(key)


def evaluate(pairs: list[dict], scores: np.ndarray, *, seed: int = 0,
             shuffles: int = 200) -> dict:
    labels = np.array([p["_label"] for p in pairs], dtype=np.int64)
    valid = ~np.isnan(scores)
    result: dict = {}
    for key, title in SUBSETS:
        mask = subset_mask(pairs, key) & valid
        sub_scores, sub_labels = scores[mask], labels[mask]
        similar, dissimilar = sub_scores[sub_labels == 1], sub_scores[sub_labels == 0]
        threshold, accuracy = best_threshold(sub_scores, sub_labels)
        result[key] = {
            "설명": title, "n": int(mask.sum()), "n_유사": int(similar.size),
            "n_비유사": int(dissimilar.size), "auc": _round(roc_auc(sub_scores, sub_labels)),
            "auc_섞은라벨": shuffled_auc(sub_scores, sub_labels, seed=seed, rounds=shuffles),
            "임계값": _round(threshold), "정확도": _round(accuracy),
            "유사_분포": distribution(similar), "비유사_분포": distribution(dissimilar),
            "분리도_Q1유사-Q3비유사": separation(similar, dissimilar),
        }
    return result


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)


def markdown_table(results: dict) -> str:
    lines = [
        "| 부분집합 | n (유사/비유사) | AUC | 섞은 AUC | 임계값 | 정확도 | 유사 중앙값 "
        "| 비유사 중앙값 | 분리도 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in results.values():
        shuffled = item["auc_섞은라벨"].get("mean")
        counts = f"{item['n']} ({item['n_유사']}/{item['n_비유사']})"
        lines.append(
            f"| {item['설명']} | {counts} | {_fmt(item['auc'])} | {_fmt(shuffled)} | "
            f"{_fmt(item['임계값'])} | {_fmt(item['정확도'])} | "
            f"{_fmt(item['유사_분포'].get('median'))} | "
            f"{_fmt(item['비유사_분포'].get('median'))} | "
            f"{_fmt(item['분리도_Q1유사-Q3비유사'])} |"
        )
    return "\n".join(lines)


def _fmt(value) -> str:
    return "-" if value is None else f"{value:.3f}"


def _font(size: int):
    from PIL import ImageFont

    for candidate in (
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ):
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def histogram_png(similar: np.ndarray, dissimilar: np.ndarray, path: Path, *, bins: int = 25,
                  title: str = "X2 코사인 점수 분포 (v0)") -> None:
    """유사(파랑)·비유사(빨강) 히스토그램을 반투명으로 겹쳐 그린다(Pillow)."""
    from PIL import Image, ImageDraw

    width, height, left, bottom, top = 900, 480, 70, 60, 50
    image = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = _font(14)
    low, high = 0.0, 1.0
    edges = np.linspace(low, high, bins + 1)
    counts = [np.histogram(np.asarray(values, dtype=np.float64), bins=edges)[0]
              for values in (similar, dissimilar)]
    peak = max(int(max(c)) if len(c) else 0 for c in counts) or 1
    plot_w, plot_h = width - left - 30, height - top - bottom
    draw.rectangle((left, top, left + plot_w, top + plot_h), outline=(120, 120, 120))
    for series, color in zip(counts, ((40, 90, 220, 110), (220, 60, 60, 110))):
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(layer)
        for i, count in enumerate(series):
            if count == 0:
                continue
            x0 = left + plot_w * i / bins
            x1 = left + plot_w * (i + 1) / bins
            y0 = top + plot_h * (1 - count / peak)
            layer_draw.rectangle((x0, y0, x1 - 1, top + plot_h), fill=color)
        image = Image.alpha_composite(image, layer)
    draw = ImageDraw.Draw(image)
    for tick in np.linspace(low, high, 11):
        x = left + plot_w * (tick - low) / (high - low)
        draw.line((x, top + plot_h, x, top + plot_h + 5), fill=(80, 80, 80))
        draw.text((x - 12, top + plot_h + 8), f"{tick:.1f}", fill=(60, 60, 60), font=font)
    for step in range(0, 5):
        count = int(round(peak * step / 4))
        y = top + plot_h * (1 - step / 4)
        draw.text((10, y - 8), f"{count}", fill=(60, 60, 60), font=font)
    draw.text((left, 15), title, fill=(30, 30, 30), font=font)
    legend = f"유사 n={len(similar)} (파랑) · 비유사 n={len(dissimilar)} (빨강)"
    draw.text((left + plot_w - 260, 15), legend, fill=(30, 30, 30), font=font)
    draw.text((left + plot_w // 2 - 40, height - 24), "코사인 점수", fill=(60, 60, 60), font=font)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path)


def run(pairs_path: Path, *, cache_path: Path, out_path: Path, hist_path: Path | None,
        seed: int = 0, shuffles: int = 200, encode=encode_image) -> dict:
    pairs = load_pairs(pairs_path)
    base = Path(pairs_path).parent
    paths = sorted({base / p[key] for p in pairs for key in ("이미지A", "이미지B")})
    embeddings = embed_paths(paths, cache_path, encode=encode)
    failures = embeddings.pop(FAILURES_KEY)
    scores = pair_scores(pairs, embeddings, base)
    results = evaluate(pairs, scores, seed=seed, shuffles=shuffles)
    labels = np.array([p["_label"] for p in pairs])
    valid = ~np.isnan(scores)
    report = {
        "생성일": date.today().isoformat(), "계약": _contract(), "쌍_파일": str(pairs_path),
        "캐시": str(cache_path), "쌍": len(pairs), "점수_있는_쌍": int(valid.sum()),
        "임베딩_실패": failures, "부분집합": results,
        "쌍별_점수": [
            {"심판번호": p["심판번호"], "상대role": p.get("상대role", ""), "라벨": p["라벨"],
             "점수": None if np.isnan(s) else round(float(s), 4)}
            for p, s in zip(pairs, scores)
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if hist_path is not None:
        histogram_png(scores[valid & (labels == 1)], scores[valid & (labels == 0)], hist_path)
        report["히스토그램"] = str(hist_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pairs", type=Path, default=DEFAULT_PAIRS)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--hist", type=Path, default=DEFAULT_HIST)
    parser.add_argument("--no-hist", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--shuffles", type=int, default=200)
    args = parser.parse_args(argv)
    hist = None if args.no_hist else args.hist
    report = run(args.pairs, cache_path=args.cache, out_path=args.out, hist_path=hist,
                 seed=args.seed, shuffles=args.shuffles)
    failed = len(report["임베딩_실패"])
    print(f"쌍 {report['쌍']} · 점수 {report['점수_있는_쌍']} · 임베딩 실패 {failed}")
    print(markdown_table(report["부분집합"]))
    print(f"JSON: {args.out}" + (f" · 히스토그램: {hist}" if hist else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
