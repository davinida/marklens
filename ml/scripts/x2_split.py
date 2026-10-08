"""X2 외관 v1 ① — 요부 분리: 표장 이미지를 문자 영역과 도형 영역으로 나누고 쌍 특징 세 가지를 잰다.

실행 (프로젝트 루트에서, 실제 모델. easyocr 모델(CRAFT + ko·en)은 첫 실행 때 ~/.EasyOCR 에
내려받는다):
    ml/venv/bin/python ml/scripts/x2_split.py            # 분리 → image_parts.csv → 혼동행렬·QA
                                                         #  → 특징 → image_pairs_v1.csv → v1 JSON
    ml/venv/bin/python ml/scripts/x2_split.py --skip-ocr # image_parts.csv 재사용(특징·평가만)
    ml/venv/bin/python ml/scripts/x2_split.py --force    # OCR 캐시 무시

이미지마다(image_index.csv 의 이미지 전부):
  1. 텍스트 박스 검출·인식(easyocr, CPU). 인식 확신도 < 0.2 인 박스는 글자가 아닌 것으로 본다
     (도형에서 전체 이미지 박스가 확신도 0.02 로 잡히는 것을 실측). text_ratio = 글자 박스 합집합
     면적 / 전체.
  2. ocr_text = 남은 박스의 글자(읽기 순서 y→x, ko+en).
  3. 글자 박스를 배경(테두리 2px 띠의 채널 중앙값)으로 지운 뒤 남은 내용(배경과 24 넘게 다른 픽셀)의
     bbox 로 도형 크롭(fig.png). fig_ratio = bbox 면적 / 전체.
  4. 자동 유형: text_ratio < 0.05 → 도형, fig_ratio < 0.08 → 문자, 그 외 결합(둘 중 큰 쪽이 요부).
결과 image_parts.csv(심판번호, role, text_ratio, fig_ratio, 자동유형, 요부, ocr_text, fig 경로 …).
유형 검증: 자동유형 vs LLM 상표유형(확정/추정) 혼동행렬. 확인대상표장이 사진으로 추정되는 쌍 20건은
크롭 전후 썸네일 QA 시트(x2_split_qa.png).
쌍 특징(image_pairs_v1.csv):
  x2_whole      = v0 그대로(전체 이미지 CLIP 코사인)
  x2_fig        = 양쪽 도형 크롭이 있을 때 CLIP 코사인(같은 encode_image·FAISS 경로), 없으면 결측
  x2_text_ortho = 양쪽 ocr_text 를 X1 normalize_name 으로 정리하고 자모 분해한 뒤 문자 단위 정규화
                  편집거리 1 − d/max — 문자상표의 외관(글자 구성) 근사. OCR 실패면 결측
  x2_rule_auto  = 자동유형(이 사건 표장)이 문자면 text_ortho·도형이면 fig·결합이면 둘의 max,
                  결측이면 whole
  x2_rule_llm   = 같은 규칙을 LLM 상표유형으로
가중치 학습은 하지 않는다(규칙 결합만). 평가는 ml/scripts/x2_benchmark.py 의 evaluate_features
(표장 라벨 기준, v0 라벨 병기, 부트스트랩 95% CI, 부분집합 (a)~(f)).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image, ImageDraw

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from src.axes.x1_phonetic import normalize_name  # noqa: E402

from scripts import trials_extract_images as tei  # noqa: E402
from scripts import x2_benchmark as x2b  # noqa: E402  (torch 가 faiss 보다 먼저 import 된다)

DEFAULT_BASE = tei.DEFAULT_BASE
TEXT_RATIO_FIGURE = 0.05  # 글자 박스 면적이 이보다 작으면 도형
FIG_RATIO_TEXT = 0.08  # 글자를 지운 뒤 남은 내용이 이보다 작으면 문자
MIN_TEXT_CONF = 0.2  # 인식 확신도 하한 — 도형의 거짓 박스(0.02) 제거
ERASE_DIFF = 24  # 배경 중앙값과 채널 차이가 이보다 크면 내용
UPSCALE_MIN_SIDE = 160  # OCR 입력의 짧은 변 하한(px)
FIG_PAD = 2
QA_ROWS = 20
PARTS_COLUMNS = [
    "심판번호", "role", "경로", "sha256", "폭", "높이", "박스수", "글자박스수", "text_ratio",
    "fig_ratio", "자동유형", "요부", "ocr_text", "ocr_conf", "fig경로",
]
FEATURE_COLUMNS = [
    "표장라벨", "this_자동유형", "상대_자동유형", "this_ocr", "상대_ocr", "x2_whole", "x2_fig",
    "x2_text_ortho", "x2_rule_auto", "x2_rule_llm", "x2_rule_auto_src", "x2_rule_llm_src",
]
LLM_TYPE_MAP = {
    "문자": "문자", "도형": "도형", "결합": "결합", "결합-문자요부": "결합",
    "결합-도형요부": "결합",
}
TYPES = ("문자", "도형", "결합")


@dataclass(frozen=True)
class TextBox:
    bbox: tuple[int, int, int, int]  # x0, y0, x1, y1 (원본 픽셀)
    text: str
    conf: float


class TextDetector(Protocol):
    def detect(self, image: Image.Image) -> list[TextBox]: ...


class EasyOcrDetector:
    """easyocr(CRAFT 검출 + ko·en 인식, CPU). 작은 이미지는 짧은 변 160px 로 키워 넣고 좌표를
    되돌린다."""

    def __init__(self, languages: tuple[str, ...] = ("ko", "en")) -> None:
        import easyocr  # 무거운 import — 실제 실행에서만

        self._reader = easyocr.Reader(list(languages), gpu=False, verbose=False)

    def detect(self, image: Image.Image) -> list[TextBox]:
        rgb = image.convert("RGB")
        width, height = rgb.size
        scale = max(1.0, UPSCALE_MIN_SIDE / max(1, min(width, height)))
        if scale > 1.0:
            rgb = rgb.resize((round(width * scale), round(height * scale)), Image.LANCZOS)
        boxes: list[TextBox] = []
        for points, text, conf in self._reader.readtext(np.asarray(rgb), detail=1):
            xs = [float(p[0]) / scale for p in points]
            ys = [float(p[1]) / scale for p in points]
            bbox = (
                max(0, int(min(xs))), max(0, int(min(ys))),
                min(width, int(np.ceil(max(xs)))), min(height, int(np.ceil(max(ys)))),
            )
            boxes.append(TextBox(bbox, str(text), float(conf)))
        return boxes


@dataclass
class SplitResult:
    text_ratio: float
    fig_ratio: float
    auto_type: str
    dominant: str
    ocr_text: str
    ocr_conf: float
    boxes: int
    text_boxes: int
    figure: Image.Image | None


def background_color(arr: np.ndarray) -> np.ndarray:
    """테두리 2px 띠의 채널별 중앙값."""
    height, width = arr.shape[:2]
    k = 2 if min(height, width) > 8 else 1
    ring = np.concatenate([
        arr[:k].reshape(-1, 3), arr[-k:].reshape(-1, 3),
        arr[:, :k].reshape(-1, 3), arr[:, -k:].reshape(-1, 3),
    ])
    return np.median(ring, axis=0)


def content_bbox(arr: np.ndarray, background: np.ndarray, *,
                 diff: int = ERASE_DIFF) -> tuple[int, int, int, int] | None:
    mask = np.abs(arr.astype(np.int16) - background.astype(np.int16)).max(axis=2) > diff
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def auto_type(text_ratio: float, fig_ratio: float) -> tuple[str, str]:
    """(자동 유형, 요부). 문자·도형은 요부가 곧 유형, 결합은 둘 중 큰 쪽."""
    if text_ratio < TEXT_RATIO_FIGURE:
        return "도형", "도형"
    if fig_ratio < FIG_RATIO_TEXT:
        return "문자", "문자"
    return "결합", ("도형" if fig_ratio >= text_ratio else "문자")


def split_image(image: Image.Image, boxes: list[TextBox], *,
                min_conf: float = MIN_TEXT_CONF) -> SplitResult:
    """글자 박스를 배경으로 지우고 남은 내용을 도형 크롭으로 낸다."""
    arr = np.asarray(image.convert("RGB"))
    height, width = arr.shape[:2]
    kept = [box for box in boxes if box.conf >= min_conf and box.text.strip()]
    mask = np.zeros((height, width), dtype=bool)
    for box in kept:
        x0, y0, x1, y1 = box.bbox
        mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True
    text_ratio = float(mask.mean()) if mask.size else 0.0
    background = background_color(arr)
    erased = arr.copy()
    erased[mask] = background.astype(arr.dtype)
    bbox = content_bbox(erased, background)
    fig_ratio = 0.0
    figure = None
    if bbox is not None:
        x0, y0, x1, y1 = bbox
        fig_ratio = (x1 - x0) * (y1 - y0) / float(width * height)
        x0, y0 = max(0, x0 - FIG_PAD), max(0, y0 - FIG_PAD)
        x1, y1 = min(width, x1 + FIG_PAD), min(height, y1 + FIG_PAD)
        figure = Image.fromarray(erased[y0:y1, x0:x1])
    kind, dominant = auto_type(text_ratio, fig_ratio)
    if kind == "문자":
        figure = None  # 글자를 지우면 남는 것이 잡음뿐 — 도형 크롭 없음
    ordered = sorted(kept, key=lambda box: (box.bbox[1], box.bbox[0]))
    ocr_text = " ".join(box.text.strip() for box in ordered)
    ocr_conf = float(np.mean([box.conf for box in kept])) if kept else 0.0
    return SplitResult(
        round(text_ratio, 4), round(fig_ratio, 4), kind, dominant, ocr_text, round(ocr_conf, 3),
        len(boxes), len(kept), figure,
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def analyze_image(path: Path, detector: TextDetector, fig_path: Path) -> dict:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
    result = split_image(rgb, detector.detect(rgb))
    fig_rel = ""
    if result.figure is not None and min(result.figure.size) >= 1:
        fig_path.parent.mkdir(parents=True, exist_ok=True)
        result.figure.save(fig_path)
        fig_rel = str(fig_path)
    return {
        "폭": rgb.width, "높이": rgb.height, "박스수": result.boxes,
        "글자박스수": result.text_boxes, "text_ratio": result.text_ratio,
        "fig_ratio": result.fig_ratio, "자동유형": result.auto_type, "요부": result.dominant,
        "ocr_text": result.ocr_text, "ocr_conf": result.ocr_conf, "fig경로": fig_rel,
    }


def run_split(base: Path, index_rows: list[dict], detector: TextDetector, *,
              previous: list[dict] | None = None, force: bool = False) -> list[dict]:
    """image_index.csv 의 이미지마다 분리. sha256 이 같은 기존 행은 재사용(--force 면 무시)."""
    cache = {} if force else {(r["경로"], r["sha256"]): r for r in (previous or [])}
    rows: list[dict] = []
    for row in index_rows:
        if not row.get("경로"):
            continue
        path = base / row["경로"]
        if not path.exists():
            continue
        sha = file_sha256(path)
        cached = cache.get((row["경로"], sha))
        if cached is not None:
            rows.append(dict(cached))
            continue
        stem = row["경로"][:-4] if row["경로"].endswith(".png") else row["경로"]
        fig_rel = stem + "_fig.png"
        analysis = analyze_image(path, detector, base / fig_rel)
        if analysis["fig경로"]:
            analysis["fig경로"] = fig_rel
        rows.append({
            "심판번호": row["심판번호"], "role": row["role"], "경로": row["경로"], "sha256": sha,
            **analysis,
        })
    return rows


# ---- 철자 유사도 ---------------------------------------------------------------------------------

_HANGUL_BASE, _HANGUL_END = 0xAC00, 0xD7A3


def decompose_hangul(text: str) -> str:
    """완성형 한글 음절을 초성·중성·종성(있을 때만) 세 글자로 푼다. 그 밖 글자는 그대로."""
    out: list[str] = []
    for char in text:
        code = ord(char)
        if _HANGUL_BASE <= code <= _HANGUL_END:
            index = code - _HANGUL_BASE
            cho, jung, jong = index // 588, (index % 588) // 28, index % 28
            out.append(chr(0x1100 + cho))
            out.append(chr(0x1161 + jung))
            if jong:
                out.append(chr(0x11A7 + jong))
        else:
            out.append(char)
    return "".join(out)


def spelling_key(text: str) -> str:
    """X1 normalize_name(NFKC·casefold·기호 제거·회사표시 제거) 토큰을 붙이고 자모로 푼 비교 키."""
    tokens = normalize_name(text or "")
    return decompose_hangul("".join(tokens).casefold())


def levenshtein(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (char_a != char_b)))
        previous = current
    return previous[-1]


def ortho_similarity(text_a: str, text_b: str) -> float | None:
    """문자 단위 정규화 편집거리 1 − d/max(len). 한쪽이라도 비면 None(결측)."""
    key_a, key_b = spelling_key(text_a), spelling_key(text_b)
    if not key_a or not key_b:
        return None
    return round(1.0 - levenshtein(key_a, key_b) / max(len(key_a), len(key_b)), 4)


# ---- 유형 검증 ----------------------------------------------------------------------------------

def llm_type(value: str) -> str:
    return LLM_TYPE_MAP.get((value or "").strip(), "")


def confusion(parts: list[dict], pairs: list[dict]) -> dict:
    """이 사건 표장(this)의 자동유형 vs LLM 상표유형(확정/추정). 미상은 뺀다."""
    auto_by_trial = {(r["심판번호"], r["role"]): r for r in parts}
    seen: set[str] = set()
    matrix = {llm: {auto: 0 for auto in TYPES} for llm in TYPES}
    dominant = {"결합-문자요부": {"문자": 0, "도형": 0}, "결합-도형요부": {"문자": 0, "도형": 0}}
    for pair in pairs:
        number = pair["심판번호"]
        if number in seen:
            continue
        seen.add(number)
        part = auto_by_trial.get((number, tei.ROLE_THIS))
        kind = llm_type(pair.get("상표유형", ""))
        if part is None or not kind:
            continue
        matrix[kind][part["자동유형"]] += 1
        fine = (pair.get("상표유형") or "").strip()
        if fine in dominant and part["자동유형"] == "결합":
            dominant[fine][part["요부"]] += 1
    total = sum(sum(row.values()) for row in matrix.values())
    agree = sum(matrix[t][t] for t in TYPES)
    return {
        "행_LLM_열_자동": matrix, "n": total, "일치": agree,
        "일치율": round(agree / total, 3) if total else None,
        "결합_요부(행_LLM_열_자동)": dominant,
    }


def ocr_quality(parts: list[dict], names: dict[str, str]) -> dict:
    """this 이미지의 ocr_text 와 labels 의 상표A_명칭 철자 유사도(OCR 품질 지표)."""
    values = []
    for row in parts:
        if row["role"] != tei.ROLE_THIS:
            continue
        name = names.get(row["심판번호"], "")
        if not name:
            continue
        similarity = ortho_similarity(row["ocr_text"], name)
        values.append(0.0 if similarity is None else similarity)
    if not values:
        return {"n": 0}
    array = np.asarray(values)
    return {
        "n": int(array.size), "평균": round(float(array.mean()), 3),
        "일치(1.0)": int((array >= 0.999).sum()), "0.8이상": int((array >= 0.8).sum()),
        "OCR없음(0)": int((array <= 0.0).sum()),
    }


# ---- 쌍 특징 ------------------------------------------------------------------------------------

def _nan(value) -> bool:
    return value is None or (isinstance(value, float) and np.isnan(value))


def rule_combine(kind: str, fig, ortho, whole) -> tuple[float | None, str]:
    """문자 → text_ortho, 도형 → fig, 결합 → max(fig, text_ortho); 결측이면 whole 로 대체."""
    if kind == "문자":
        chosen, source = ortho, "text_ortho"
    elif kind == "도형":
        chosen, source = fig, "fig"
    elif kind == "결합":
        candidates = [v for v in (fig, ortho) if not _nan(v)]
        chosen, source = (max(candidates) if candidates else None), "max"
    else:
        chosen, source = None, ""
    if _nan(chosen):
        return (None if _nan(whole) else float(whole)), "whole"
    return float(chosen), source


def build_features(pairs: list[dict], parts: list[dict], base: Path, cache_path: Path, *,
                   encode=x2b.encode_image) -> tuple[list[dict], dict]:
    """image_pairs.csv 행마다 표장라벨·자동유형·ocr·특징 다섯 가지를 붙인다. (행, 임베딩 실패)."""
    part_by_key = {(r["심판번호"], r["role"]): r for r in parts}
    whole_paths = sorted({base / p[k] for p in pairs for k in ("이미지A", "이미지B")})
    fig_rel: dict[tuple[str, str], str] = {
        key: r["fig경로"] for key, r in part_by_key.items() if r.get("fig경로")
    }
    fig_paths = sorted({base / rel for rel in fig_rel.values()})
    embeddings = x2b.embed_paths(whole_paths + fig_paths, cache_path, encode=encode)
    failures = embeddings.pop(x2b.FAILURES_KEY)
    whole_scores = x2b.pair_scores(pairs, embeddings, base)
    fig_pairs = []
    for pair in pairs:
        a = fig_rel.get((pair["심판번호"], tei.ROLE_THIS), "")
        b = fig_rel.get((pair["심판번호"], pair["상대role"]), "")
        fig_pairs.append({"이미지A": a or "__none__", "이미지B": b or "__none__"})
    fig_scores = x2b.pair_scores(fig_pairs, embeddings, base)
    rows: list[dict] = []
    for pair, whole, fig in zip(pairs, whole_scores, fig_scores):
        this_part = part_by_key.get((pair["심판번호"], tei.ROLE_THIS), {})
        other_part = part_by_key.get((pair["심판번호"], pair["상대role"]), {})
        ortho = ortho_similarity(this_part.get("ocr_text", ""), other_part.get("ocr_text", ""))
        whole_value = None if np.isnan(whole) else round(float(whole), 4)
        fig_value = None if np.isnan(fig) else round(float(fig), 4)
        auto_kind = this_part.get("자동유형", "")
        rule_auto, src_auto = rule_combine(auto_kind, fig_value, ortho, whole_value)
        llm_kind = llm_type(pair.get("상표유형", ""))
        rule_llm, src_llm = rule_combine(llm_kind, fig_value, ortho, whole_value)
        row = dict(pair)
        row.update({
            "표장라벨": x2b.mark_label(pair), "this_자동유형": auto_kind,
            "상대_자동유형": other_part.get("자동유형", ""),
            "this_ocr": this_part.get("ocr_text", ""), "상대_ocr": other_part.get("ocr_text", ""),
            "x2_whole": _fmt(whole_value), "x2_fig": _fmt(fig_value), "x2_text_ortho": _fmt(ortho),
            "x2_rule_auto": _fmt(rule_auto), "x2_rule_llm": _fmt(rule_llm),
            "x2_rule_auto_src": src_auto, "x2_rule_llm_src": src_llm,
        })
        rows.append(row)
    return rows, failures


def _fmt(value) -> str:
    return "" if _nan(value) else f"{float(value):.4f}"


# ---- QA 시트 ------------------------------------------------------------------------------------

def _part_line(label: str, part: dict) -> str:
    kind = f"{part.get('자동유형', '-')}/{part.get('요부', '-')}"
    ratios = f"t{part.get('text_ratio', '-')} f{part.get('fig_ratio', '-')}"
    return f"{label}: {kind} {ratios} «{(part.get('ocr_text') or '')[:22]}»"


def render_split_qa(pairs_v1: list[dict], parts: list[dict], base: Path, out: Path, *,
                    n: int = QA_ROWS, seed: int = 0) -> list[dict]:
    """확인대상표장이 사진으로 추정되는 쌍 n 건 — this·상대의 크롭 전후 썸네일과 OCR·비율."""
    photo = [p for p in pairs_v1 if str(p.get("상대_사진추정") or "") == "1"
             and (p.get("상대role") or "").startswith(tei.ROLE_TARGET)]
    sample = random.Random(seed).sample(photo, min(n, len(photo)))
    chosen = sorted(sample, key=lambda p: p["심판번호"])
    part_by_key = {(r["심판번호"], r["role"]): r for r in parts}
    thumb, row_h = 150, 190
    cols = [110, thumb + 10, thumb + 10, thumb + 10, thumb + 10, 330]
    width = sum(cols) + 20
    sheet = Image.new("RGB", (width, 40 + row_h * max(1, len(chosen))), "white")
    draw = ImageDraw.Draw(sheet)
    font, small = tei._font(14), tei._font(12)
    x = 10
    titles = ("심판번호", "this", "this fig", "상대", "상대 fig", "OCR·비율·유형")
    for title, w in zip(titles, cols):
        draw.text((x, 12), title, fill="black", font=font)
        x += w
    for i, pair in enumerate(chosen):
        y = 40 + i * row_h
        draw.line((0, y, width, y), fill=(200, 200, 200))
        x = 10
        draw.text((x, y + 8), pair["심판번호"], fill="black", font=small)
        label_text = f"{pair['라벨']} / 표장 {pair.get('표장라벨') or '-'}"
        draw.text((x, y + 28), label_text, fill=(90, 90, 90), font=small)
        x += cols[0]
        this_part = part_by_key.get((pair["심판번호"], tei.ROLE_THIS), {})
        other_part = part_by_key.get((pair["심판번호"], pair["상대role"]), {})
        for rel in (pair["이미지A"], this_part.get("fig경로", ""), pair["이미지B"],
                    other_part.get("fig경로", "")):
            if rel:
                try:
                    with Image.open(base / rel) as image:
                        t = image.convert("RGB")
                        t.thumbnail((thumb, thumb - 20))
                        sheet.paste(t, (x, y + 10))
                except OSError:
                    draw.text((x, y + 10), "(열기 실패)", fill="red", font=small)
            else:
                draw.text((x, y + 10), "(없음)", fill=(150, 150, 150), font=small)
            x += thumb + 10
        lines = [
            _part_line("A", this_part), _part_line("B", other_part),
            f"whole {pair.get('x2_whole') or '-'} · fig {pair.get('x2_fig') or '-'}"
            f" · ortho {pair.get('x2_text_ortho') or '-'}",
            f"LLM 유형 {pair.get('상표유형') or '-'} · 판단축 {pair.get('판단축') or '-'}",
        ]
        for j, line in enumerate(lines):
            draw.text((x, y + 8 + 22 * j), line, fill="black", font=small)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return chosen


# ---- 실행 --------------------------------------------------------------------------------------

def run(base: Path, *, detector: TextDetector | None = None, skip_ocr: bool = False,
        force: bool = False, seed: int = 0, shuffles: int = 200,
        bootstrap: int = x2b.BOOTSTRAP_ROUNDS, encode=x2b.encode_image) -> dict:
    index_rows = tei.read_csv(base / "image_index.csv")
    pairs = x2b.load_pairs(base / "image_pairs.csv")
    parts_path = base / "image_parts.csv"
    previous = tei.read_csv(parts_path) if parts_path.exists() else []
    if skip_ocr:
        parts = previous
    else:
        if detector is None:
            detector = EasyOcrDetector()
        parts = run_split(base, index_rows, detector, previous=previous, force=force)
        tei.write_csv(parts_path, PARTS_COLUMNS, parts)
    labels = tei.read_csv(base / "labels.csv")
    names: dict[str, str] = {}
    for row in labels:
        names.setdefault(row["심판번호"], row.get("상표A_명칭", ""))
    pairs_v1, failures = build_features(pairs, parts, base, base / "x2_cache_v0.npz", encode=encode)
    tei.write_csv(base / "image_pairs_v1.csv", tei.PAIR_COLUMNS + FEATURE_COLUMNS, pairs_v1)
    rows_for_eval = x2b.load_pairs(base / "image_pairs_v1.csv")
    evaluation = x2b.evaluate_features(rows_for_eval, list(x2b.FEATURES), seed=seed,
                                       shuffles=shuffles, bootstrap=bootstrap)
    hist: dict[str, str] = {}
    labels_mark = np.array([-1 if p["_mark"] is None else p["_mark"] for p in rows_for_eval])
    for feature in x2b.FEATURES:
        scores = x2b.feature_scores(rows_for_eval, feature)
        valid = ~np.isnan(scores) & (labels_mark >= 0)
        path = base / f"x2_hist_v1_{feature}.png"
        x2b.histogram_png(scores[valid & (labels_mark == 1)], scores[valid & (labels_mark == 0)],
                          path, title=f"{feature} 점수 분포 (v1, 표장 라벨)")
        hist[feature] = str(path)
    chosen = render_split_qa(pairs_v1, parts, base, base / "x2_split_qa.png", seed=seed)
    mark_counts = {k: 0 for k in ("유사", "비유사", "제외")}
    for pair in pairs_v1:
        mark_counts[pair["표장라벨"] or "제외"] += 1
    this_parts = [r for r in parts if r["role"] == tei.ROLE_THIS]
    report = {
        "생성일": x2b.date.today().isoformat(), "계약": x2b._contract(),
        "min_size": tei.MIN_SIZE, "쌍": len(pairs), "표장라벨": mark_counts,
        "이미지_분리": {
            "이미지": len(parts), "자동유형": _count(parts, "자동유형"),
            "this_자동유형": _count(this_parts, "자동유형"),
            "fig있음": sum(1 for r in parts if r.get("fig경로")),
            "ocr없음": sum(1 for r in parts if not r.get("ocr_text")),
        },
        "유형_혼동행렬": confusion(parts, pairs),
        "OCR_품질(this_vs_상표A_명칭)": ocr_quality(parts, names),
        "특징_결측": {
            f: int(np.isnan(x2b.feature_scores(rows_for_eval, f)).sum()) for f in x2b.FEATURES
        },
        "규칙_대체(whole)": {
            "auto": sum(1 for p in pairs_v1 if p["x2_rule_auto_src"] == "whole"),
            "llm": sum(1 for p in pairs_v1 if p["x2_rule_llm_src"] == "whole"),
        },
        "임베딩_실패": failures, "평가": evaluation, "히스토그램": hist,
        "QA_시트": {"경로": str(base / "x2_split_qa.png"), "쌍": len(chosen), "seed": seed},
    }
    (base / "x2_benchmark_v1.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                encoding="utf-8")
    return report


def _count(rows: list[dict], key: str) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key) or "(없음)"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def confusion_table(result: dict) -> str:
    matrix = result["행_LLM_열_자동"]
    lines = ["| LLM \\ 자동 | " + " | ".join(TYPES) + " |", "|---|" + "---|" * len(TYPES)]
    for llm in TYPES:
        lines.append(f"| {llm} | " + " | ".join(str(matrix[llm][auto]) for auto in TYPES) + " |")
    lines.append(f"\n일치 {result['일치']}/{result['n']} ({result['일치율']})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--skip-ocr", action="store_true",
                        help="image_parts.csv 재사용(특징·평가만)")
    parser.add_argument("--force", action="store_true", help="OCR 캐시 무시")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--shuffles", type=int, default=200)
    parser.add_argument("--bootstrap", type=int, default=x2b.BOOTSTRAP_ROUNDS)
    args = parser.parse_args(argv)
    report = run(args.base, skip_ocr=args.skip_ocr, force=args.force, seed=args.seed,
                 shuffles=args.shuffles, bootstrap=args.bootstrap)
    print(f"쌍 {report['쌍']} · 표장라벨 {report['표장라벨']} · 이미지 {report['이미지_분리']}")
    print("## 유형 혼동행렬(this)\n" + confusion_table(report["유형_혼동행렬"]))
    print("## OCR 품질:", report["OCR_품질(this_vs_상표A_명칭)"])
    print("## 특징 결측:", report["특징_결측"], "· 규칙 대체:", report["규칙_대체(whole)"])
    print(x2b.feature_table(report["평가"]))
    print(f"JSON: {args.base / 'x2_benchmark_v1.json'} · QA: {report['QA_시트']['경로']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
