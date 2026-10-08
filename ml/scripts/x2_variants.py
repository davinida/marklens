"""X2 외관 v1 ② — 전체 이미지 임베딩 변형 비교, OCR 노이즈 진단, 유형 게이팅(규칙, 학습 없음).

실행 (프로젝트 루트에서, 실제 모델. DINOv2 가중치(timm vit_small_patch14_dinov2.lvd142m, 약 88MB)는
첫 실행 때 HF 허브에서 내려받는다. ① 의 image_pairs_v1.csv·image_parts.csv 가 있어야 한다):
    ml/venv/bin/python ml/scripts/x2_variants.py               # 변형 5종 → 진단 → 게이팅 → JSON
    ml/venv/bin/python ml/scripts/x2_variants.py --skip-dino   # CLIP 변형만(DINOv2·앙상블 생략)

A. 전체 이미지 변형(같은 306쌍, 표장 라벨, 부트스트랩 95% CI) — whole(기준)과 나란히:
   gray      흑백 입력(L → RGB)
   edge      윤곽선 입력(Canny 100/200 → 흰 바탕에 검은 윤곽, 3채널)
   multires  다중 해상도 평균(원본·1/2·1/4 축소 후 원 크기로 복원해 CLIP 임베딩 3개를 평균·재정규화,
             이격적 관찰 모사)
   dino      DINOv2 ViT-S/14 코사인(timm, CPU, 384차원)
   ensemble  CLIP whole + DINOv2 — 각 코사인을 쌍 분포에서 z-정규화한 뒤 평균
   채택 규칙: (b) 외관축 점추정이 whole 보다 +0.05 이상이고 (a) 전체에서 낮아지지 않을 것. 충족해도
   CI 가 겹치면 "잠정 후보". 없으면 "채택 없음".
B. OCR 노이즈 진단: this 쪽은 OCR 대신 labels 의 상표A_명칭(참값), 상대 쪽만 OCR 인
   x2_text_ortho_half 를 같은 쌍에서 계산해 ① 의 x2_text_ortho(양쪽 OCR)와 (b)·(d)에서 비교.
   차이 = OCR 노이즈의 몫. 상표A_명칭이 비거나 "도형"인 쌍은 뺀다.
C. 게이팅: 유형(LLM 확정 우선, 없으면 자동유형·요부) 문자·결합-문자요부 → text_ortho_half,
   도형·결합-도형요부 → A 의 채택 변형(없으면 whole) → x2_gate. whole·x2_rule_llm 과 비교.
산출: x2_variants_v1.json, image_pairs_v1_variants.csv(쌍별 변형 점수·half·gate), 표(stdout).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from src.embedding import encode_image  # noqa: E402  (torch 가 faiss 보다 먼저)

from scripts import trials_extract_images as tei  # noqa: E402
from scripts import x2_benchmark as x2b  # noqa: E402
from scripts import x2_split as xs  # noqa: E402

DEFAULT_BASE = tei.DEFAULT_BASE
DINO_MODEL = "vit_small_patch14_dinov2.lvd142m"
VARIANTS = ("whole", "gray", "edge", "multires", "dino", "ensemble")
VARIANT_TITLES = {
    "whole": "whole(기준)", "gray": "흑백", "edge": "윤곽선(Canny)", "multires": "다중 해상도 평균",
    "dino": "DINOv2 ViT-S/14", "ensemble": "CLIP+DINOv2 z-평균",
}
EVAL_SUBSETS = ("a_전체", "b_외관축", "c_도형", "d_문자", "f_사진")
GATE_SUBSETS = ("a_전체", "b_외관축", "c_도형", "d_문자")
ADOPT_DELTA = 0.05
GATE_TEXT_TYPES = {"문자", "결합-문자요부"}
GATE_FIGURE_TYPES = {"도형", "결합-도형요부"}
CANNY = (100, 200)
EXTRA_COLUMNS = [
    "x2_gray", "x2_edge", "x2_multires", "x2_dino", "x2_ensemble", "x2_text_ortho_half",
    "x2_gate", "x2_gate_src",
]


# ---- 변형 입력 ----

def to_gray(image: Image.Image) -> Image.Image:
    return image.convert("L").convert("RGB")


def to_edge(image: Image.Image, *, low: int = CANNY[0], high: int = CANNY[1]) -> Image.Image:
    """Canny 윤곽선 — 흰 바탕에 검은 선(선화 표장과 같은 꼴), 3채널."""
    import cv2

    gray = np.asarray(image.convert("L"))
    edges = cv2.Canny(gray, low, high)
    return Image.fromarray(255 - edges).convert("RGB")


def multires_views(image: Image.Image, factors: tuple[int, ...] = (2, 4)) -> list[Image.Image]:
    """원본과, 1/f 로 줄였다 원 크기로 되돌린 흐린 view 들(이격적 관찰 모사)."""
    width, height = image.size
    views = [image]
    for factor in factors:
        small = image.resize((max(1, width // factor), max(1, height // factor)), Image.LANCZOS)
        views.append(small.resize((width, height), Image.BILINEAR))
    return views


def l2_normalize(vector: np.ndarray) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(array))
    if not np.isfinite(norm) or norm <= 0:
        raise ValueError("zero or non-finite embedding")
    return (array / norm).astype(np.float32)


def embed_multires(image: Image.Image, *, encode=encode_image) -> np.ndarray:
    vectors = [l2_normalize(encode(view)) for view in multires_views(image)]
    return l2_normalize(np.mean(vectors, axis=0))


class DinoEmbedder:
    """timm DINOv2 ViT-S/14(CPU). 모델 기본 전처리(518px, ImageNet 정규화)를 그대로 쓴다."""

    def __init__(self, model_name: str = DINO_MODEL, img_size: int | None = None) -> None:
        import timm
        import torch

        kwargs = {"img_size": img_size} if img_size else {}
        self._torch = torch
        self.model = timm.create_model(model_name, pretrained=True, num_classes=0, **kwargs).eval()
        config = timm.data.resolve_data_config({}, model=self.model)
        self.transform = timm.data.create_transform(**config)
        self.input_size = tuple(config["input_size"])
        self.dim = int(self.model.num_features)

    def __call__(self, image: Image.Image) -> np.ndarray:
        with self._torch.no_grad():
            batch = self.transform(image.convert("RGB")).unsqueeze(0)
            features = self.model(batch)[0].float().cpu().numpy()
        return l2_normalize(features)


# ---- 캐시(변형별 npz, 파일 sha256 키) ----

def variant_cache_path(base: Path, variant: str) -> Path:
    return base / f"x2_cache_v1_{variant}.npz"


def variant_contract(variant: str) -> dict:
    if variant == "dino":
        return {"model": DINO_MODEL, "variant": variant}
    return {**x2b._contract(), "variant": variant}


def load_variant_cache(path: Path, contract: dict) -> tuple[dict[str, np.ndarray], dict]:
    if not Path(path).exists():
        return {}, {}
    with np.load(path, allow_pickle=False) as data:
        meta = json.loads(str(data["meta"]))
        if meta.get("contract") != contract:
            return {}, {}
        cache = {key: vec for key, vec in zip(data["keys"].tolist(), data["embeddings"])}
    return cache, meta


def save_variant_cache(path: Path, cache: dict[str, np.ndarray], contract: dict,
                       ms_per_image: float | None) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    keys = sorted(cache)
    np.savez(
        path, keys=np.array(keys),
        embeddings=np.stack([cache[key] for key in keys]).astype(np.float32),
        meta=np.array(json.dumps({"contract": contract, "ms_per_image": ms_per_image})),
    )


def _embed_one(image: Image.Image, variant: str, *, encode, dino) -> np.ndarray:
    if variant == "whole":
        return l2_normalize(encode(image))
    if variant == "gray":
        return l2_normalize(encode(to_gray(image)))
    if variant == "edge":
        return l2_normalize(encode(to_edge(image)))
    if variant == "multires":
        return embed_multires(image, encode=encode)
    if variant == "dino":
        if dino is None:
            raise ValueError("dino embedder required")
        return dino(image)
    raise ValueError(variant)


def embed_variant(paths: list[Path], variant: str, base: Path, *, encode=encode_image,
                  dino=None) -> tuple[dict[str, np.ndarray], dict[str, str], float | None]:
    """경로 → 단위 벡터(변형별). (임베딩, 실패 사유, 이미지당 ms — 캐시만 썼으면 저장된 값)."""
    contract = variant_contract(variant)
    cache_file = variant_cache_path(base, variant)
    cache, meta = load_variant_cache(cache_file, contract)
    result: dict[str, np.ndarray] = {}
    failures: dict[str, str] = {}
    timings: list[float] = []
    added = 0
    for path in paths:
        key = x2b.file_sha256(path)
        if key not in cache:
            started = time.perf_counter()
            try:
                with Image.open(path) as opened:
                    image = opened.convert("RGB")
                vector = _embed_one(image, variant, encode=encode, dino=dino)
            except (ValueError, OSError) as exc:
                failures[str(path)] = str(exc)
                continue
            timings.append((time.perf_counter() - started) * 1000.0)
            cache[key] = vector
            added += 1
        result[str(path)] = cache[key]
    ms = round(float(np.mean(timings)), 1) if timings else meta.get("ms_per_image")
    if added:
        save_variant_cache(cache_file, cache, contract, ms)
    return result, failures, ms


def cosine_scores(pairs: list[dict], embeddings: dict[str, np.ndarray], base: Path) -> np.ndarray:
    """단위 벡터의 내적(= 코사인 = FAISS inner product 와 같은 값). 임베딩 없는 쌍은 NaN."""
    scores = np.full(len(pairs), np.nan, dtype=np.float32)
    for i, pair in enumerate(pairs):
        a = embeddings.get(str(base / pair["이미지A"]))
        b = embeddings.get(str(base / pair["이미지B"]))
        if a is not None and b is not None:
            scores[i] = float(np.dot(a, b))
    return scores


def zscore(values: np.ndarray) -> np.ndarray:
    """유효 값 기준 z-정규화(표준편차 0이면 0). NaN 은 그대로."""
    array = np.asarray(values, dtype=np.float64)
    valid = ~np.isnan(array)
    out = np.full(array.shape, np.nan)
    if valid.sum() == 0:
        return out
    mean, std = array[valid].mean(), array[valid].std()
    out[valid] = (array[valid] - mean) / std if std > 0 else 0.0
    return out


def ensemble_scores(clip: np.ndarray, dino: np.ndarray) -> np.ndarray:
    """두 코사인의 z-점수 평균. 한쪽이라도 없으면 NaN."""
    both = ~np.isnan(clip) & ~np.isnan(dino)
    z_clip = zscore(np.where(both, clip, np.nan))
    z_dino = zscore(np.where(both, dino, np.nan))
    return ((z_clip + z_dino) / 2.0).astype(np.float32)


# ---- A. 평가·채택 ----

def mark_labels(pairs: list[dict]) -> np.ndarray:
    return np.array([-1 if p.get("_mark") is None else p["_mark"] for p in pairs], dtype=np.int64)


def evaluate_scores(pairs: list[dict], scores: np.ndarray, *, seed: int = 0, shuffles: int = 200,
                    bootstrap: int = x2b.BOOTSTRAP_ROUNDS) -> dict:
    return x2b.evaluate(pairs, scores, labels=mark_labels(pairs), seed=seed, shuffles=shuffles,
                        bootstrap=bootstrap)


def _ci(item: dict) -> tuple[float | None, float | None]:
    low, high = item.get("auc_ci95", [None, None])
    return low, high


def adoption(results: dict, *, baseline: str = "whole", delta: float = ADOPT_DELTA) -> dict:
    """채택 규칙: (b) 점추정이 기준보다 +delta 이상이고 (a) 가 낮아지지 않음.
    충족해도 CI 가 겹치면 잠정 후보."""
    base_a = results[baseline]["a_전체"]["auc"]
    base_b = results[baseline]["b_외관축"]["auc"]
    _, base_b_high = _ci(results[baseline]["b_외관축"])
    verdicts: dict[str, dict] = {}
    candidates: list[tuple[float, str]] = []
    for variant, result in results.items():
        if variant == baseline:
            continue
        auc_a, auc_b = result["a_전체"]["auc"], result["b_외관축"]["auc"]
        if auc_a is None or auc_b is None or base_a is None or base_b is None:
            verdicts[variant] = {"판정": "평가 불가"}
            continue
        delta_b = round(auc_b - base_b, 4)
        a_ok = auc_a >= base_a
        met = delta_b >= delta and a_ok
        low_b, _ = _ci(result["b_외관축"])
        overlap = low_b is None or base_b_high is None or low_b <= base_b_high
        if met:
            verdict = "잠정 후보" if overlap else "채택"
            candidates.append((delta_b, variant))
        else:
            verdict = "채택 없음"
        verdicts[variant] = {
            "판정": verdict, "delta_b": delta_b, "a_유지": a_ok, "CI겹침": overlap,
            "이유": _reason(delta_b, a_ok, overlap, delta),
        }
    best = max(candidates)[1] if candidates else None
    return {"기준": baseline, "규칙": f"(b) +{delta} 이상 & (a) 유지, CI 겹치면 잠정 후보",
            "변형": verdicts, "채택안": best}


def _reason(delta_b: float, a_ok: bool, overlap: bool, delta: float) -> str:
    sign = "+" if delta_b >= 0 else ""
    parts = [f"(b) {sign}{delta_b:.3f}" + ("" if delta_b >= delta else f" < +{delta}")]
    parts.append("(a) 유지" if a_ok else "(a) 하락")
    if delta_b >= delta and a_ok:
        parts.append("CI 겹침" if overlap else "CI 분리")
    return " · ".join(parts)


# ---- B. OCR 노이즈 진단 ----

def half_ortho_scores(pairs: list[dict], names: dict[str, str]) -> tuple[np.ndarray, dict]:
    """this 는 상표A_명칭(참값), 상대는 OCR. 명칭이 비거나 '도형'이면 제외(NaN)."""
    scores = np.full(len(pairs), np.nan, dtype=np.float32)
    excluded = {"명칭 없음": 0, "명칭 도형": 0, "상대 OCR 없음": 0}
    for i, pair in enumerate(pairs):
        name = (names.get(pair["심판번호"]) or "").strip()
        if not name:
            excluded["명칭 없음"] += 1
            continue
        if name == "도형":
            excluded["명칭 도형"] += 1
            continue
        value = xs.ortho_similarity(name, pair.get("상대_ocr") or "")
        if value is None:
            excluded["상대 OCR 없음"] += 1
            continue
        scores[i] = value
    return scores, excluded


def diagnose_ocr(pairs: list[dict], half: np.ndarray, full: np.ndarray, *, seed: int = 0,
                 bootstrap: int = x2b.BOOTSTRAP_ROUNDS) -> dict:
    """같은 쌍(둘 다 값이 있고 표장 라벨이 있는 것)에서 half 와 full 의 AUC 를 부분집합별로 비교."""
    labels = mark_labels(pairs)
    shared = ~np.isnan(half) & ~np.isnan(full) & (labels >= 0)
    result: dict = {"같은_쌍": int(shared.sum())}
    for key in ("b_외관축", "d_문자", "a_전체"):
        mask = x2b.subset_mask(pairs, key) & shared
        sub_labels = labels[mask]
        entry = {"n": int(mask.sum()), "n_유사": int((sub_labels == 1).sum()),
                 "n_비유사": int((sub_labels == 0).sum())}
        for name, scores in (("full", full), ("half", half)):
            auc = x2b.roc_auc(scores[mask], sub_labels)
            low, high = x2b.bootstrap_auc(scores[mask], sub_labels, rounds=bootstrap, seed=seed)
            entry[name] = {"auc": x2b._round(auc), "ci95": [low, high]}
        if entry["full"]["auc"] is not None and entry["half"]["auc"] is not None:
            entry["차이_half-full"] = round(entry["half"]["auc"] - entry["full"]["auc"], 4)
        result[key] = entry
    return result


# ---- C. 게이팅 ----

def gate_type(pair: dict, parts_by_key: dict) -> str:
    """'text' | 'figure' | ''. LLM 확정 유형 우선, 없으면 자동유형(결합은 요부)."""
    if pair.get("상표유형_출처") == "확정":
        kind = (pair.get("상표유형") or "").strip()
        if kind in GATE_TEXT_TYPES:
            return "text"
        if kind in GATE_FIGURE_TYPES:
            return "figure"
    auto = (pair.get("this_자동유형") or "").strip()
    if auto == "문자":
        return "text"
    if auto == "도형":
        return "figure"
    if auto == "결합":
        part = parts_by_key.get((pair["심판번호"], tei.ROLE_THIS), {})
        return "figure" if part.get("요부") == "도형" else "text"
    return ""


def gate_scores(pairs: list[dict], parts_by_key: dict, half: np.ndarray, figure: np.ndarray,
                whole: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """문자 → half, 도형 → 채택 변형, 결측·미상 → whole."""
    scores = np.full(len(pairs), np.nan, dtype=np.float32)
    sources: list[str] = []
    for i, pair in enumerate(pairs):
        kind = gate_type(pair, parts_by_key)
        chosen = None
        source = "whole"
        if kind == "text" and not np.isnan(half[i]):
            chosen, source = half[i], "text_half"
        elif kind == "figure" and not np.isnan(figure[i]):
            chosen, source = figure[i], "figure"
        if chosen is None:
            chosen = whole[i]
        scores[i] = chosen
        sources.append(source)
    return scores, sources


# ---- 표 ----

def _cell(item: dict) -> str:
    return x2b._auc_ci(item) + f" n{item['n']}"


def _short(key: str) -> str:
    return key.split("_", 1)[1]


def variants_table(results: dict, ms: dict, adopt: dict) -> str:
    head = "| 변형 | " + " | ".join(_short(key) for key in EVAL_SUBSETS) + " | ms/이미지 | 판정 |"
    lines = [head, "|---|" + "---|" * (len(EVAL_SUBSETS) + 2)]
    for variant in VARIANTS:
        if variant not in results:
            continue
        cells = " | ".join(_cell(results[variant][key]) for key in EVAL_SUBSETS)
        if variant == adopt["기준"]:
            verdict = "기준"
        else:
            verdict = adopt["변형"].get(variant, {}).get("판정", "-")
        ms_text = "-" if ms.get(variant) is None else f"{ms[variant]:.0f}"
        lines.append(f"| {VARIANT_TITLES[variant]} | {cells} | {ms_text} | {verdict} |")
    return "\n".join(lines)


def diagnosis_table(diag: dict) -> str:
    lines = ["| 부분집합 | n (유사/비유사) | full(양쪽 OCR) | half(this 참값) | 차이 |",
             "|---|---|---|---|---|"]
    for key in ("b_외관축", "d_문자", "a_전체"):
        entry = diag[key]
        counts = f"{entry['n']} ({entry['n_유사']}/{entry['n_비유사']})"
        lines.append(
            f"| {_short(key)} | {counts} | {_fmt_ci(entry['full'])} | {_fmt_ci(entry['half'])} | "
            f"{entry.get('차이_half-full', '-')} |"
        )
    return "\n".join(lines)


def _fmt_ci(entry: dict) -> str:
    if entry["auc"] is None:
        return "-"
    low, high = entry["ci95"]
    if low is None:
        return f"{entry['auc']:.3f}"
    return f"{entry['auc']:.3f} ({low:.2f}~{high:.2f})"


def gating_table(gating: dict) -> str:
    columns = list(gating)
    lines = ["| 부분집합 | " + " | ".join(columns) + " |", "|---|" + "---|" * len(columns)]
    for key in GATE_SUBSETS:
        cells = " | ".join(_cell(gating[column][key]) for column in columns)
        lines.append(f"| {_short(key)} | {cells} |")
    return "\n".join(lines)


# ---- 실행 ----

def run(base: Path, *, encode=encode_image, dino=None, skip_dino: bool = False, seed: int = 0,
        shuffles: int = 200, bootstrap: int = x2b.BOOTSTRAP_ROUNDS) -> dict:
    pairs = x2b.load_pairs(base / "image_pairs_v1.csv")
    parts_rows = tei.read_csv(base / "image_parts.csv")
    parts_by_key = {(r["심판번호"], r["role"]): r for r in parts_rows}
    paths = sorted({base / p[key] for p in pairs for key in ("이미지A", "이미지B")})
    scores: dict[str, np.ndarray] = {}
    ms: dict[str, float | None] = {}
    failures: dict[str, dict] = {}
    for variant in ("whole", "gray", "edge", "multires"):
        embeddings, failed, ms_variant = embed_variant(paths, variant, base, encode=encode)
        scores[variant] = cosine_scores(pairs, embeddings, base)
        ms[variant], failures[variant] = ms_variant, failed
    if not skip_dino:
        embedder = dino if dino is not None else DinoEmbedder()
        embeddings, failed, ms_variant = embed_variant(paths, "dino", base, dino=embedder)
        scores["dino"] = cosine_scores(pairs, embeddings, base)
        ms["dino"], failures["dino"] = ms_variant, failed
        scores["ensemble"] = ensemble_scores(scores["whole"], scores["dino"])
        ms["ensemble"] = None
    results = {
        variant: evaluate_scores(pairs, scores[variant], seed=seed, shuffles=shuffles,
                                 bootstrap=bootstrap)
        for variant in scores
    }
    adopt = adoption(results)

    names: dict[str, str] = {}
    for row in tei.read_csv(base / "labels.csv"):
        names.setdefault(row["심판번호"], row.get("상표A_명칭", ""))
    half, excluded = half_ortho_scores(pairs, names)
    full = x2b.feature_scores(pairs, "x2_text_ortho")
    diagnosis = diagnose_ocr(pairs, half, full, seed=seed, bootstrap=bootstrap)
    diagnosis["제외"] = excluded
    diagnosis["half_값_있음"] = int((~np.isnan(half)).sum())

    best = adopt["채택안"] or "whole"
    gate, sources = gate_scores(pairs, parts_by_key, half, scores[best], scores["whole"])
    rule_llm = x2b.feature_scores(pairs, "x2_rule_llm")
    gating = {
        "x2_whole": results["whole"],
        "x2_rule_llm": evaluate_scores(pairs, rule_llm, seed=seed, shuffles=shuffles,
                                       bootstrap=bootstrap),
        "x2_gate": evaluate_scores(pairs, gate, seed=seed, shuffles=shuffles, bootstrap=bootstrap),
    }
    source_counts: dict[str, int] = {}
    for source in sources:
        source_counts[source] = source_counts.get(source, 0) + 1

    rows = []
    for i, pair in enumerate(pairs):
        row = {k: v for k, v in pair.items() if not k.startswith("_")}
        for variant in ("gray", "edge", "multires", "dino", "ensemble"):
            row[f"x2_{variant}"] = xs._fmt(float(scores[variant][i])) if variant in scores else ""
        row["x2_text_ortho_half"] = xs._fmt(float(half[i]))
        row["x2_gate"] = xs._fmt(float(gate[i]))
        row["x2_gate_src"] = sources[i]
        rows.append(row)
    columns = tei.PAIR_COLUMNS + xs.FEATURE_COLUMNS + EXTRA_COLUMNS
    tei.write_csv(base / "image_pairs_v1_variants.csv", columns, rows)
    report = {
        "생성일": x2b.date.today().isoformat(), "쌍": len(pairs),
        "표장라벨_제외": int((mark_labels(pairs) < 0).sum()),
        "변형": {
            variant: {
                "설명": VARIANT_TITLES[variant], "ms_per_image": ms.get(variant),
                "임베딩_실패": len(failures.get(variant, {})), "평가": results[variant],
            }
            for variant in results
        },
        "채택": adopt, "게이팅_도형_변형": best,
        "OCR_진단": diagnosis, "게이팅": {"소스": source_counts, "평가": gating},
        "dino": {"model": DINO_MODEL, "skipped": skip_dino},
    }
    (base / "x2_variants_v1.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--skip-dino", action="store_true", help="DINOv2·앙상블 생략")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--shuffles", type=int, default=200)
    parser.add_argument("--bootstrap", type=int, default=x2b.BOOTSTRAP_ROUNDS)
    args = parser.parse_args(argv)
    report = run(args.base, skip_dino=args.skip_dino, seed=args.seed, shuffles=args.shuffles,
                 bootstrap=args.bootstrap)
    results = {v: item["평가"] for v, item in report["변형"].items()}
    ms = {v: item["ms_per_image"] for v, item in report["변형"].items()}
    verdicts = {k: v["판정"] for k, v in report["채택"]["변형"].items()}
    print(f"쌍 {report['쌍']} · 표장라벨 제외 {report['표장라벨_제외']}")
    print("## A. 변형(표장 라벨, AUC 95% CI)\n" + variants_table(results, ms, report["채택"]))
    print("채택:", report["채택"]["채택안"], "·", verdicts)
    print("## B. OCR 노이즈 진단\n" + diagnosis_table(report["OCR_진단"]))
    print("제외:", report["OCR_진단"]["제외"], "· 같은 쌍:", report["OCR_진단"]["같은_쌍"])
    print(f"## C. 게이팅(도형 변형 = {report['게이팅_도형_변형']})")
    print(gating_table(report["게이팅"]["평가"]))
    print("소스:", report["게이팅"]["소스"])
    print(f"JSON: {args.base / 'x2_variants_v1.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
