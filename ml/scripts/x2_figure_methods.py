"""도형 외관 세 방법 비교 — 전체 이미지 CLIP(기준선) · 글자 지운 도형(개선판) · 비엔나코드 겹침.

측정만 한다(서비스 코드·모델 계수 변경 없음, KIPRIS 호출 0). X2 설계 §7.6·§10, 통합 모델 설계 §6.

실행 (프로젝트 루트에서, 실제 모델. easyocr·CLIP 은 캐시가 있으면 다시 돌리지 않는다):
    ml/venv/bin/python ml/scripts/x2_figure_methods.py               # 전부(쉬운 음성 참고값 포함)
    ml/venv/bin/python ml/scripts/x2_figure_methods.py --no-easy     # 심결 도형계 쌍만
    ml/venv/bin/python ml/scripts/x2_figure_methods.py --bootstrap 200   # 빠른 확인

표본: pairs_features.csv 에서 상표유형이 도형·결합-도형요부이고 양쪽 이미지가 있으며 표장 라벨이
      있는 쌍(image_pairs_v1.csv 와 이어 붙인다). 쉬운 음성(cross·db, 비유사 가정)은 현실 분포
      참고값으로만.
평가: 표장 라벨 ROC AUC, 사건(심판번호) 단위 부트스트랩 95% CI, 사건 가중(w = min(1, 3 / 그 사건의
      특징 행 수)) 있음·없음. 기준선과의 짝 부트스트랩 AUC 차이(같은 사건 복원추출).
세 방법:
  1. whole — 전체 이미지 CLIP 코사인(image_pairs_v1.csv 의 x2_whole, 현재 서비스 x2_img).
  2. 글자 지운 도형(개선판, 변형 7개) — 10월 x2_fig 의 실패 원인을 고친 것:
     ① 글자 검출 박스(easyocr CRAFT; 인식 확신도·글자로 거르지 않는다)를 지우고 구멍을 주변으로
        채운다(OpenCV inpaint TELEA) — 10월은 배경색 사각형으로 덮고 확신도 0.2 미만 박스를 남겼다.
     ② 상표명을 알면 인식 글자와 느슨하게 맞는 박스만 지운다(도형을 글자로 오인해 지우지 않게).
        이름이 "없음"으로 알려진 표장(목록·KIPRIS 상표명이 빈 도형 표장, LLM 이 도형만이라고 적은
        상대 표장)은 아무것도 지우지 않고, 이름을 모르면(조회 실패) ①처럼 모두 지운다.
     ③ 사진 표장(trials_extract_images._photo_like 추정)은 검출 박스 합집합을 여백 50% 로 넓힌
        영역(로고 영역)만 잘라 본다 — 간단한 방법만.
     그 뒤 선택적으로 남은 내용의 bbox 로 자른다(crop). 처리 결과가 너무 작거나 비면 앞 단계
     이미지로 둔다.
  3. 비엔나코드 겹침 — 양쪽 코드 집합의 자카드를 대분류(앞 2자리)·중분류(앞 4자리)로. 실제 코드는
     상대 표장의 KIPRIS 조회 결과(prior_marks.csv ViennaCode)와 DB(kipris_metadata.json, 6자리
     코드 보유 1,000건)에만 있다. 없는 쪽은 그 이미지의 CLIP 임베딩으로 코드 보유 DB 1,000건 중
     가까운 k개를 찾아 k개 중 40% 이상에 나온 코드로 추정(서비스에서 질의 이미지에 쓸 방식). 추정
     품질은 DB 안에서 한 건씩 빼고(LOO, 같은 출원인 제외판 포함) 추정한 적중률과, 실제 코드가 있는
     심결 상대 표장으로 잰다.
미리 고정한 것(결과를 보기 전): 주 설정 PRIMARY_FIGURE·PRIMARY_VIENNA, 채택 기준 adoption() —
      기준선과의 짝 부트스트랩 AUC 차이의 CI 하한이 가중 없음·가중 둘 다 0 보다 크고, 1차·2차
      부분집합에서 차이가 모두 양수일 때만 바꾼다. 나머지 변형은 민감도로 전부 표에 남긴다.
도형 단독 규칙: 유지·채택 방법의 τ 별 정밀도·재현율, 현재 τ 0.9 와 정밀도 0.7(지지 ≥ 10) τ.
산출: ml/data/trials/x2_figure_methods.json(+ 표 stdout), 캐시 x2_figure_ocr.json(검출 박스)·
      x2_cache_figure.npz(처리 이미지 CLIP)·x2_figure/<변형>/*.png.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from scripts import x2_benchmark as x2b  # noqa: E402,I001  (torch → faiss 순서는 그 모듈이 지킨다)
from scripts import axes_benchmark as ab  # noqa: E402
from scripts import pairs_features as pf  # noqa: E402
from scripts import trials_extract_images as tei  # noqa: E402
from src.mark_type import TextBox, background_color, content_bbox  # noqa: E402

DEFAULT_BASE = ML_ROOT / "data" / "trials"
DEFAULT_DB_META = ML_ROOT / "data" / "kipris_metadata.json"
DEFAULT_DB_IMAGES = ML_ROOT / "data" / "images"
DEFAULT_OUT = DEFAULT_BASE / "x2_figure_methods.json"
FIGURE_TYPES = ("도형", "결합-도형요부")
BIG_CASE = "2025101001193"  # 한 사건 40행(2차 라벨링) — 도형계 표본에 있는지 따로 본다

# 방법 2 — 글자 지운 도형
MASK_DILATE = 2  # 검출 박스를 이만큼 넓혀 지운다(px)
INPAINT_RADIUS = 3
ERASE_MAX_RATIO = 0.9  # 지울 면적이 이 이상이면 지우지 않는다(남는 것이 없음)
CROP_MIN_SIDE = 32  # CLIP 전처리 최소 입력
CROP_MIN_RATIO = 0.02  # 남은 내용 bbox 가 이보다 작으면 자르지 않는다(잡음)
CROP_PAD = 2
PHOTO_MARGIN = 0.5  # 사진: 검출 박스 합집합을 긴 변의 이 비율만큼 넓힌 영역
PHOTO_MAX_RATIO = 0.9  # 로고 영역이 이미지의 이 이상이면 자르지 않는다
NAME_MATCH = 0.5  # 인식 글자 ↔ 상표명(전체·토큰) 문자 유사도 하한
FIGURE_VARIANTS = {
    "erase_all_full": {"erase": "all", "crop": False, "photo": False},
    "erase_all_crop": {"erase": "all", "crop": True, "photo": False},
    "erase_name_full": {"erase": "name", "crop": False, "photo": False},
    "erase_name_crop": {"erase": "name", "crop": True, "photo": False},
    "photo_crop": {"erase": None, "crop": False, "photo": True},
    "fig_v2_full": {"erase": "name", "crop": False, "photo": True},
    "fig_v2_crop": {"erase": "name", "crop": True, "photo": True},
    # 사후 진단(2026-11-19, 결과를 본 뒤 추가 — 채택 판단 대상 아님): 지우지 않고 crop 만
    "crop_only": {"erase": None, "crop": True, "photo": False},
}
DIAGNOSTIC_VARIANTS = ("crop_only",)
PRIMARY_FIGURE = "fig_v2_crop"  # ①②③ + 남은 내용 crop(10월 x2_fig 와 같은 "도형만" 비교)

# 방법 3 — 비엔나코드
VIENNA_SHARE = 0.4  # k 개 이웃 중 이 비율 이상에 나온 코드
VIENNA_LEVELS = {"major": 2, "mid": 4}
VIENNA_VARIANTS = {
    "vienna_major_k1": {"level": "major", "k": 1},
    "vienna_major_k5": {"level": "major", "k": 5},
    "vienna_major_k10": {"level": "major", "k": 10},
    "vienna_mid_k1": {"level": "mid", "k": 1},
    "vienna_mid_k5": {"level": "mid", "k": 5},
    "vienna_mid_k10": {"level": "mid", "k": 10},
    "vienna_mid_k5_no2729": {"level": "mid", "k": 5, "exclude": ("27", "29")},
    "vienna_mid_k5_est_both": {"level": "mid", "k": 5, "estimate_all": True},
}
PRIMARY_VIENNA = "vienna_mid_k5"
VIENNA_CODE_RE = re.compile(r"^\d{6}$")

# 평가
CASE_CAP = ab.CASE_CAP
TAU_GRID = (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95)
FIGURE_TAU = 0.9  # 통합 모델 figure_rule(미검증 제품 규칙)
STANDALONE_PRECISION = 0.7  # 다른 단독 임계값과 같은 정밀도 규칙(지지 ≥ 10)
MIN_SUPPORT = ab.MIN_SUPPORT


# ---- 글자 지운 도형 ---------------------------------------------------------------------------

def normalize_text(value: str) -> str:
    """NFKC·casefold 뒤 글자(한글·라틴·숫자·가나·한자)만."""
    folded = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[^0-9a-z가-힣ㄱ-ㅎㅏ-ㅣ぀-ヿ一-鿿]", "", folded)


def name_parts(name: str) -> tuple[str, list[str]]:
    """(정규화한 전체 이름, 정규화한 토큰들)."""
    tokens = [normalize_text(t) for t in re.split(r"[\s/·,()\[\]&+\-]+", name or "")]
    return normalize_text(name), [t for t in tokens if t]


def box_matches_name(text: str, name: str, *, minimum: float = NAME_MATCH) -> bool:
    """인식 글자가 상표명과 느슨하게 맞는가 — 포함 관계 또는 문자 유사도(전체·토큰) ≥ minimum."""
    box = normalize_text(text)
    full, tokens = name_parts(name)
    if not box or not full:
        return False
    if box in full or (len(full) >= 2 and full in box):
        return True
    candidates = [full, *tokens]
    return any(difflib.SequenceMatcher(None, box, c).ratio() >= minimum for c in candidates)


def select_boxes(boxes: list[TextBox], mode: str | None, name: str | None) -> list[TextBox]:
    """지울 박스. mode "all" = 검출 박스 전부(인식 결과를 쓰지 않음). "name" = name 이
    None(모름)이면 전부, ""(없음으로 알려짐 — 도형 표장)이면 하나도, 그 밖에는 상표명과 맞는
    박스만."""
    if not mode:
        return []
    if mode == "all" or name is None:
        return list(boxes)
    if not name.strip():
        return []
    return [box for box in boxes if box_matches_name(box.text, name)]


def erase_boxes(image: Image.Image, boxes: list[TextBox], *, dilate: int = MASK_DILATE,
                radius: int = INPAINT_RADIUS) -> tuple[Image.Image, float]:
    """박스 영역을 지우고 주변으로 채운다(OpenCV inpaint TELEA). (이미지, 지운 면적 비율)."""
    import cv2

    arr = np.asarray(image.convert("RGB"))
    height, width = arr.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    for box in boxes:
        x0, y0, x1, y1 = box.bbox
        mask[max(0, y0 - dilate):min(height, y1 + dilate),
             max(0, x0 - dilate):min(width, x1 + dilate)] = 255
    ratio = float((mask > 0).mean()) if mask.size else 0.0
    if not mask.any():
        return Image.fromarray(arr.copy()), 0.0
    bgr = np.ascontiguousarray(arr[:, :, ::-1])
    filled = cv2.inpaint(bgr, mask, radius, cv2.INPAINT_TELEA)
    return Image.fromarray(np.ascontiguousarray(filled[:, :, ::-1])), ratio


def content_crop(image: Image.Image, *, pad: int = CROP_PAD, min_side: int = CROP_MIN_SIDE,
                 min_ratio: float = CROP_MIN_RATIO) -> Image.Image | None:
    """배경(테두리 띠 중앙값)과 다른 내용의 bbox 로 자른다. 너무 작으면 None."""
    arr = np.asarray(image.convert("RGB"))
    height, width = arr.shape[:2]
    bbox = content_bbox(arr, background_color(arr))
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(width, x1 + pad), min(height, y1 + pad)
    if (x1 - x0) < min_side or (y1 - y0) < min_side:
        return None
    if (x1 - x0) * (y1 - y0) < min_ratio * width * height:
        return None
    return Image.fromarray(np.ascontiguousarray(arr[y0:y1, x0:x1]))


def logo_region(size: tuple[int, int], boxes: list[TextBox], *, margin: float = PHOTO_MARGIN,
                max_ratio: float = PHOTO_MAX_RATIO,
                min_side: int = CROP_MIN_SIDE) -> tuple[int, int, int, int] | None:
    """사진 표장의 로고 영역: 검출 박스 합집합을 긴 변의 margin 만큼 넓힌 bbox. 박스가 없거나 영역이
    이미지의 max_ratio 이상이거나 너무 작으면 None."""
    if not boxes:
        return None
    width, height = size
    x0 = min(b.bbox[0] for b in boxes)
    y0 = min(b.bbox[1] for b in boxes)
    x1 = max(b.bbox[2] for b in boxes)
    y1 = max(b.bbox[3] for b in boxes)
    grow = int(round(margin * max(x1 - x0, y1 - y0)))
    x0, y0 = max(0, x0 - grow), max(0, y0 - grow)
    x1, y1 = min(width, x1 + grow), min(height, y1 + grow)
    if (x1 - x0) < min_side or (y1 - y0) < min_side:
        return None
    if (x1 - x0) * (y1 - y0) >= max_ratio * width * height:
        return None
    return x0, y0, x1, y1


def shift_boxes(boxes: list[TextBox], region: tuple[int, int, int, int]) -> list[TextBox]:
    """잘라낸 영역 좌표계로 옮긴다(영역 밖 박스는 버리고 걸친 박스는 자른다)."""
    rx0, ry0, rx1, ry1 = region
    out = []
    for box in boxes:
        x0, y0, x1, y1 = box.bbox
        x0, y0, x1, y1 = max(x0, rx0), max(y0, ry0), min(x1, rx1), min(y1, ry1)
        if x1 > x0 and y1 > y0:
            out.append(TextBox((x0 - rx0, y0 - ry0, x1 - rx0, y1 - ry0), box.text, box.conf))
    return out


def is_blank(image: Image.Image) -> bool:
    """CLIP 전처리가 거부하는 빈·균일 이미지(채널 범위 < 4 또는 표준편차 < 1 —
    ml/src/preprocess.py)."""
    arr = np.asarray(image.convert("RGB"), dtype=np.float32)
    return arr.size == 0 or float(arr.max() - arr.min()) < 4 or float(arr.std()) < 1


@dataclass
class Processed:
    image: Image.Image | None  # None = 원본 그대로(바꾼 것이 없음)
    steps: list[str]


def process_image(image: Image.Image, boxes: list[TextBox], *, name: str | None, photo: bool,
                  erase: str | None, crop: bool, photo_crop: bool) -> Processed:
    """한 변형의 처리: (사진이면 로고 영역) → (지울 박스 inpaint) → (남은 내용 crop)."""
    current = image.convert("RGB")
    changed = False
    steps: list[str] = []
    work_boxes = list(boxes)
    if photo_crop and photo:
        region = logo_region(current.size, work_boxes)
        if region is None:
            steps.append("사진: 로고 영역 없음")
        else:
            current = current.crop(region)
            work_boxes = shift_boxes(work_boxes, region)
            changed = True
            steps.append("사진: 로고 영역")
    chosen = select_boxes(work_boxes, erase, name)
    if chosen:
        erased, ratio = erase_boxes(current, chosen)
        if ratio >= ERASE_MAX_RATIO:
            steps.append("지우기 생략(글자가 대부분)")
        elif is_blank(erased):
            steps.append("지우기 생략(남는 내용 없음)")
        else:
            current, changed = erased, True
            steps.append(f"지움 {len(chosen)}/{len(work_boxes)}")
    elif erase:
        steps.append("지울 박스 없음")
    if crop:
        cropped = content_crop(current)
        if cropped is None:
            steps.append("crop 생략(작음)")
        else:
            current, changed = cropped, True
            steps.append("crop")
    return Processed(current if changed else None, steps)


# ---- 비엔나코드 ----------------------------------------------------------------------------------

def parse_codes(value) -> list[str]:
    """6자리 비엔나코드만(DB 의 설명 문자열·빈 값은 버림). 리스트 또는 '|' 구분 문자열."""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).split("|")
    return [str(c).strip() for c in items if VIENNA_CODE_RE.match(str(c).strip())]


def level_codes(codes, level: str, exclude: tuple[str, ...] = ()) -> frozenset[str]:
    width = VIENNA_LEVELS[level]
    return frozenset(c[:width] for c in codes if c[:2] not in exclude)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """두 코드 집합의 자카드. 한쪽이라도 비면 0."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class ViennaIndex:
    """코드 보유 DB 상표의 CLIP 벡터와 코드 — 가까운 k 개의 코드로 추정."""

    def __init__(self, vectors: np.ndarray, codes: list[list[str]],
                 applicants: list[str] | None = None) -> None:
        self.vectors = np.asarray(vectors, dtype=np.float32)
        self.codes = codes
        self.applicants = applicants or [""] * len(codes)

    def neighbors(self, query: np.ndarray, k: int, *, exclude: set[int] | None = None) -> list[int]:
        sims = self.vectors @ np.asarray(query, dtype=np.float32)
        order = np.argsort(-sims, kind="stable")
        out: list[int] = []
        for index in order:
            if exclude and int(index) in exclude:
                continue
            out.append(int(index))
            if len(out) >= k:
                break
        return out

    def estimate(self, query: np.ndarray, *, level: str, k: int, share: float = VIENNA_SHARE,
                 exclude_codes: tuple[str, ...] = (),
                 exclude: set[int] | None = None) -> frozenset[str]:
        """k 개 이웃 중 share 이상에 나온 코드(수준 level). 하나도 없으면 가장 가까운 1개의 코드."""
        found = self.neighbors(query, k, exclude=exclude)
        if not found:
            return frozenset()
        counts: dict[str, int] = {}
        for index in found:
            for code in level_codes(self.codes[index], level, exclude_codes):
                counts[code] = counts.get(code, 0) + 1
        chosen = frozenset(c for c, n in counts.items() if n / len(found) >= share)
        return chosen or level_codes(self.codes[found[0]], level, exclude_codes)


def estimate_quality(estimated: list[frozenset[str]], actual: list[frozenset[str]]) -> dict:
    """추정 코드 vs 실제 코드: 평균 자카드, 적중률(겹침 ≥ 1), 마이크로 정밀도·재현율."""
    pairs = [(e, a) for e, a in zip(estimated, actual) if a]
    if not pairs:
        return {"n": 0}
    hits = sum(1 for e, a in pairs if e & a)
    inter = sum(len(e & a) for e, a in pairs)
    est_total = sum(len(e) for e, _ in pairs)
    act_total = sum(len(a) for _, a in pairs)
    return {
        "n": len(pairs), "자카드_평균": round(float(np.mean([jaccard(e, a) for e, a in pairs])), 4),
        "적중률": round(hits / len(pairs), 4),
        "정밀도": round(inter / est_total, 4) if est_total else None,
        "재현율": round(inter / act_total, 4) if act_total else None,
        "추정_코드수_평균": round(est_total / len(pairs), 2),
        "실제_코드수_평균": round(act_total / len(pairs), 2),
    }


def leave_one_out(index: ViennaIndex, *, level: str, k: int, same_applicant: bool = False,
                  share: float = VIENNA_SHARE) -> dict:
    """DB 안에서 한 건씩 빼고 나머지로 추정한 품질. same_applicant 이면 같은 출원인 이웃도 뺀다."""
    estimated, actual = [], []
    for i in range(len(index.codes)):
        exclude = {i}
        if same_applicant and index.applicants[i]:
            exclude |= {j for j, a in enumerate(index.applicants) if a == index.applicants[i]}
        estimated.append(index.estimate(index.vectors[i], level=level, k=k, share=share,
                                        exclude=exclude))
        actual.append(level_codes(index.codes[i], level))
    return estimate_quality(estimated, actual)


def prior_baseline(index: ViennaIndex, *, level: str) -> dict:
    """이미지를 보지 않는 기준선: 가장 흔한 코드 m 개(m = 실제 코드 수 평균의 반올림)를 모두에게."""
    actual = [level_codes(c, level) for c in index.codes]
    counts: dict[str, int] = {}
    for codes in actual:
        for code in codes:
            counts[code] = counts.get(code, 0) + 1
    m = max(1, int(round(np.mean([len(a) for a in actual if a]))))
    top = frozenset(sorted(counts, key=lambda c: (-counts[c], c))[:m])
    return {"코드": sorted(top), **estimate_quality([top] * len(actual), actual)}


# ---- 평가 ----------------------------------------------------------------------------------------

def auc_block(scores: np.ndarray, labels: np.ndarray, groups: np.ndarray, weights: np.ndarray, *,
              rounds: int, seed: int) -> dict:
    """AUC(가중 없음·가중) + 사건 단위 CI. 점수가 없는 행은 뺀다."""
    valid = ~np.isnan(scores) & (labels >= 0)
    s, y, g, w = scores[valid], labels[valid], groups[valid], weights[valid]
    out = ab.evaluate_subset(s, y, seed=seed, bootstrap=rounds, groups=g, weights=w)
    return {k: out[k] for k in ("n", "n_유사", "n_비유사", "n_사건", "auc", "auc_ci95", "auc_w",
                                "auc_w_ci95", "n_가중") if k in out}


def paired_diff(base: np.ndarray, other: np.ndarray, labels: np.ndarray, groups: np.ndarray,
                weights: np.ndarray, *, rounds: int, seed: int) -> dict:
    """AUC(other) − AUC(base) 의 점추정과 사건 단위 짝 부트스트랩 95% CI(가중 없음·가중). 두 점수가
    다 있는 행만. 같은 복원추출에서 두 AUC 를 함께 잰다."""
    valid = ~np.isnan(base) & ~np.isnan(other) & (labels >= 0)
    a, b, y, w = base[valid], other[valid], labels[valid], weights[valid]
    out: dict = {"n": int(valid.sum())}
    if a.size == 0 or (y == 1).all() or (y == 0).all():
        return {**out, "diff": None, "ci95": [None, None], "diff_w": None, "ci95_w": [None, None]}
    _, group_id = np.unique(groups[valid].astype(str), return_inverse=True)
    size = int(group_id.max()) + 1
    _, tie_a = np.unique(a, return_inverse=True)
    _, tie_b = np.unique(b, return_inverse=True)
    pos, neg = (y == 1).astype(np.float64), (y == 0).astype(np.float64)

    def pair(weight: np.ndarray) -> float | None:
        auc_a = ab._tie_auc(tie_a, weight * pos, weight * neg)
        auc_b = ab._tie_auc(tie_b, weight * pos, weight * neg)
        return None if auc_a is None or auc_b is None else auc_b - auc_a

    rng = np.random.default_rng(seed)
    draws: dict[str, list[float]] = {"plain": [], "weighted": []}
    for _ in range(rounds):
        counts = np.bincount(rng.integers(0, size, size), minlength=size)[group_id]
        for key, base_w in (("plain", np.ones_like(w)), ("weighted", w)):
            value = pair(base_w * counts)
            if value is not None:
                draws[key].append(value)

    def ci(values: list[float]) -> list[float | None]:
        if not values:
            return [None, None]
        return [x2b._round(np.percentile(values, 2.5)), x2b._round(np.percentile(values, 97.5))]

    return {**out, "diff": x2b._round(pair(np.ones_like(w))), "ci95": ci(draws["plain"]),
            "diff_w": x2b._round(pair(w)), "ci95_w": ci(draws["weighted"])}


def adoption(overall: dict, first: dict, second: dict) -> dict:
    """채택 기준(미리 고정): 전체 짝 차이의 CI 하한 > 0(가중 없음·가중 둘 다) 이고 1차·2차
    부분집합의 차이가 모두 양수. 아니면 기준선 유지."""
    low, low_w = (overall.get("ci95") or [None])[0], (overall.get("ci95_w") or [None])[0]
    ci_ok = low is not None and low > 0 and low_w is not None and low_w > 0
    d1, d2 = first.get("diff"), second.get("diff")
    same = d1 is not None and d2 is not None and d1 > 0 and d2 > 0
    reasons = []
    if not ci_ok:
        reasons.append(f"짝 차이 CI 하한 {low}·가중 {low_w} — 0 초과 아님")
    if not same:
        reasons.append(f"1차 {d1}·2차 {d2} — 둘 다 양수 아님")
    return {"채택": ci_ok and same, "사유": "; ".join(reasons) or "기준 충족"}


def threshold_table(scores: np.ndarray, labels: np.ndarray, weights: np.ndarray, *,
                    grid: tuple[float, ...] = TAU_GRID) -> list[dict]:
    """τ 별 정밀도(점수 ≥ τ 중 유사 비율)·재현율·지지, 가중 정밀도."""
    valid = ~np.isnan(scores) & (labels >= 0)
    s, y, w = scores[valid], labels[valid], weights[valid]
    n_pos = int((y == 1).sum())
    rows = []
    for tau in grid:
        above = s >= tau
        count = int(above.sum())
        precision = float(y[above].mean()) if count else None
        weighted = float((w[above] * y[above]).sum() / w[above].sum()) if count else None
        rows.append({
            "τ": tau, "지지_n": count, "정밀도": x2b._round(precision),
            "가중_정밀도": x2b._round(weighted),
            "재현율": x2b._round(float((y[above] == 1).sum() / n_pos)) if n_pos else None,
        })
    return rows


# ---- 데이터 --------------------------------------------------------------------------------------

def read_csv(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def case_counts(features: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in features:
        counts[row["심판번호"]] = counts.get(row["심판번호"], 0) + 1
    return counts


def name_state_b(feature: dict, prior: dict | None) -> str | None:
    """상대 표장 이름 상태: 이름이 있으면 그 이름, "도형"(LLM)·KIPRIS 조회 성공인데 상표명이 비면
    ""(없음으로 알려짐), 그 밖에는 None(모름)."""
    if feature.get("이름B"):
        return feature["이름B"]
    if feature.get("이름B_출처") == "도형":
        return ""
    if prior and prior.get("결과") == "ok" and not (prior.get("Title") or "").strip():
        return ""
    return None


def load_sample(base: Path) -> tuple[list[dict], list[dict]]:
    """(도형계 표본 행, 특징 전체). 행: 키·회차·유형·라벨·사건·가중·이미지·사진·이름 상태·
    x2_whole·x2_fig·상대 실제 비엔나코드."""
    features = read_csv(base / "pairs_features.csv")
    pairs = {(r["심판번호"], r["상대번호"]): r for r in read_csv(base / "image_pairs_v1.csv")}
    labels = {(r["심판번호"], r["상표B_번호"]): r for r in read_csv(base / "labels.csv")}
    priors = {r["번호_정규화"]: r for r in read_csv(base / "prior_marks.csv")}
    counts = case_counts(features)
    rows = []
    for f in features:
        key = (f["심판번호"], f["상대번호"])
        if f["상표유형"] not in FIGURE_TYPES or f["has_image"] != "1" or not f["표장라벨"]:
            continue
        pair = pairs.get(key)
        if pair is None:
            continue
        label_row = labels.get(key, {})
        prior = priors.get(label_row.get("상대표장_번호_정규화") or "")
        codes_b = parse_codes(prior.get("ViennaCode")) if prior and prior["결과"] == "ok" else []
        rows.append({
            "key": key, "심판번호": f["심판번호"], "회차": f.get("회차", ""), "유형": f["상표유형"],
            "종류": f.get("종류", ""),
            "판단축": f.get("판단축", ""), "label": 1 if f["표장라벨"] == "유사" else 0,
            "weight": min(1.0, CASE_CAP / counts[f["심판번호"]]),
            "image_a": base / pair["이미지A"], "image_b": base / pair["이미지B"],
            "photo_a": pair.get("this_사진추정") == "1",
            "photo_b": pair.get("상대_사진추정") == "1",
            "name_a": f.get("이름A") or "",  # 목록 상표명 — 비면 도형 표장(2차 "도형 추정")
            "name_b": name_state_b(f, prior),
            "x2_whole": float(f["x2_whole"]) if f["x2_whole"] else np.nan,
            "x2_fig": float(f["x2_fig"]) if f["x2_fig"] else np.nan,
            "codes_a": [], "codes_b": codes_b,
        })
    return rows, features


def load_db(meta_path: Path, image_dir: Path) -> list[dict]:
    data = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    out = []
    for record in data.get("trademarks", data):
        name = record.get("상표한글명") or record.get("상표영문명") or ""
        name = "" if str(name) == "None" else str(name).strip()
        out.append({"file": record.get("이미지파일") or "",
                    "codes": parse_codes(record.get("비엔나코드")),
                    "applicant": record.get("출원인") or "", "name": name,
                    "path": Path(image_dir) / (record.get("이미지파일") or "")})
    return out


def load_easy(base: Path, features: list[dict], db: list[dict],
              db_records: list[dict]) -> list[dict]:
    """쉬운 음성(비유사 가정) 중 양쪽 이미지가 있는 쌍. db 는 실제 코드, cross 는 양쪽 추정."""
    easy = read_csv(base / "pairs_features_easy.csv")
    image_rows = read_csv(base / "image_pairs_v1.csv")
    sides, _ = pf.easy_image_sides(easy, features, image_rows, db_records)
    by_file = {d["file"]: d for d in db}
    rows = []
    for row, side in zip(easy, sides):
        if side is None or not row.get("x2_whole"):
            continue
        source = row["pair_source"]
        if source == "cross":
            a, b = base / side[0], base / side[1]
            codes_a = codes_b = []
        else:
            da, db_ = by_file.get(side[0]), by_file.get(side[1])
            if not da or not db_:
                continue
            a, b, codes_a, codes_b = da["path"], db_["path"], da["codes"], db_["codes"]
        rows.append({
            "key": (row["심판번호"], ""), "심판번호": row["심판번호"], "회차": "", "유형": "",
            "종류": "",
            "판단축": "", "label": 0, "weight": 1.0, "image_a": a, "image_b": b,
            "photo_a": False, "photo_b": False, "name_a": row["이름A"], "name_b": row["이름B"],
            "x2_whole": float(row["x2_whole"]), "x2_fig": np.nan, "codes_a": codes_a,
            "codes_b": codes_b, "source": source,
        })
    return rows


# ---- 실행 단계 -----------------------------------------------------------------------------------

def detect_boxes(paths: list[Path], cache_path: Path, detector=None) -> dict[str, list[TextBox]]:
    """이미지 경로 → 검출 박스(파일 sha256 키 JSON 캐시). 캐시에 없는 것만 검출한다."""
    cache: dict = {}
    if Path(cache_path).exists():
        cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    out: dict[str, list[TextBox]] = {}
    added = 0
    for path in paths:
        key = x2b.file_sha256(path)
        if key not in cache:
            if detector is None:
                from scripts.x2_split import EasyOcrDetector

                detector = EasyOcrDetector()
            with Image.open(path) as image:
                boxes = detector.detect(image.convert("RGB"))
            cache[key] = [[*b.bbox, b.text, round(float(b.conf), 4)] for b in boxes]
            added += 1
            if added % 50 == 0:
                Path(cache_path).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        out[str(path)] = [TextBox(tuple(int(v) for v in item[:4]), str(item[4]), float(item[5]))
                          for item in cache[key]]
    if added:
        Path(cache_path).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return out


def photo_flags(rows: list[dict]) -> dict[str, bool]:
    """이미지 경로 → 사진 추정. 심결 도형계 표본은 쌍 파일의 플래그(image_index 와 같은 휴리스틱),
    쉬운 음성(cross·db)은 그 휴리스틱(trials_extract_images._photo_like)을 직접 돌린다."""
    flags: dict[str, bool] = {}
    for row in rows:
        for side in ("a", "b"):
            path = str(row[f"image_{side}"])
            if path in flags:
                continue
            if row.get("source"):
                flags[path] = bool(tei._photo_like(Path(path)))
            else:
                flags[path] = bool(row[f"photo_{side}"])
    return flags


def build_variants(rows: list[dict], boxes: dict[str, list[TextBox]], flags: dict[str, bool],
                   out_dir: Path) -> tuple[dict, dict]:
    """(변형 → {(행 번호, 쪽): 처리 이미지 경로}, 변형별 처리 단계 집계). 바꾼 것이 없으면
    원본 경로."""
    paths: dict[str, dict] = {name: {} for name in FIGURE_VARIANTS}
    steps: dict[str, dict[str, int]] = {name: {} for name in FIGURE_VARIANTS}
    for index, row in enumerate(rows):
        for side in ("a", "b"):
            source = Path(row[f"image_{side}"])
            sha = x2b.file_sha256(source)
            name = row[f"name_{side}"]
            with Image.open(source) as opened:
                image = opened.convert("RGB")
            for variant, spec in FIGURE_VARIANTS.items():
                result = process_image(
                    image, boxes[str(source)], name=name, photo=flags[str(source)],
                    erase=spec["erase"], crop=spec["crop"], photo_crop=spec["photo"],
                )
                for step in result.steps or ["그대로"]:
                    key = step.split(" ")[0] if step.startswith("지움") else step
                    steps[variant][key] = steps[variant].get(key, 0) + 1
                if result.image is None:
                    paths[variant][(index, side)] = source
                    continue
                state = "n" if name is None else hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
                target = out_dir / variant / f"{sha[:20]}_{state}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                result.image.save(target)  # 늘 덮어쓴다(규칙이 바뀌어도 낡은 파일을 쓰지 않게)
                paths[variant][(index, side)] = target
    return paths, steps


def cosine_scores(rows: list[dict], side_paths: dict, embeddings: dict) -> np.ndarray:
    out = np.full(len(rows), np.nan)
    for index in range(len(rows)):
        a, b = str(side_paths[(index, "a")]), str(side_paths[(index, "b")])
        if a in embeddings and b in embeddings:  # x2_whole 과 같은 소수 4자리
            out[index] = round(float(np.dot(embeddings[a], embeddings[b])), 4)
    return out


def vienna_scores(rows: list[dict], index: ViennaIndex, embeddings: dict, spec: dict) -> np.ndarray:
    """쌍마다 비엔나 자카드. 실제 코드가 있으면 쓰고(estimate_all 이면 무시), 없으면 원본
    이미지 CLIP 으로 추정."""
    out = np.full(len(rows), np.nan)
    exclude = spec.get("exclude", ())
    for i, row in enumerate(rows):
        sets = []
        for side in ("a", "b"):
            actual = row[f"codes_{side}"]
            vector = embeddings.get(str(row[f"image_{side}"]))
            if actual and not spec.get("estimate_all"):
                sets.append(level_codes(actual, spec["level"], exclude))
            elif vector is not None:
                sets.append(index.estimate(vector, level=spec["level"], k=spec["k"],
                                           exclude_codes=exclude))
            else:
                sets.append(None)
        if sets[0] is not None and sets[1] is not None:
            out[i] = jaccard(sets[0], sets[1])
    return out


SPLITS = (
    ("1차", lambda r: r["회차"] == "1"), ("2차", lambda r: r["회차"] == "2"),
    ("순수 도형", lambda r: r["유형"] == "도형"),
    ("결합-도형요부", lambda r: r["유형"] == "결합-도형요부"),
    ("로고끼리", lambda r: not (r["photo_a"] or r["photo_b"])),
    ("사진 포함", lambda r: r["photo_a"] or r["photo_b"]),
    ("이름A 있음", lambda r: bool(r["name_a"])), ("이름A 빈칸", lambda r: not r["name_a"]),
    (f"사건 {BIG_CASE} 제외", lambda r: r["심판번호"] != BIG_CASE),
    # 진단: 1차·2차 차이가 선정(이름 빈 도형)인지 이미지 종류(사진)인지 — 로고끼리만 다시 나눈다
    ("1차 로고끼리", lambda r: r["회차"] == "1" and not (r["photo_a"] or r["photo_b"])),
    ("2차 로고끼리", lambda r: r["회차"] == "2" and not (r["photo_a"] or r["photo_b"])),
    ("권리범위확인", lambda r: r["종류"].startswith("권리범위확인")),
    ("거절·무효", lambda r: not r["종류"].startswith("권리범위확인")),
)


def evaluate(rows: list[dict], methods: dict[str, np.ndarray], *, rounds: int, seed: int) -> dict:
    labels = np.asarray([r["label"] for r in rows])
    groups = np.asarray([r["심판번호"] for r in rows])
    weights = np.asarray([r["weight"] for r in rows])
    base = methods["whole"]
    masks = {name: np.asarray([test(r) for r in rows]) for name, test in SPLITS}
    out: dict = {}
    for name, scores in methods.items():
        item = {"전체": auc_block(scores, labels, groups, weights, rounds=rounds, seed=seed)}
        for split in ("1차", "2차"):
            m = masks[split]
            item[split] = auc_block(scores[m], labels[m], groups[m], weights[m], rounds=rounds,
                                    seed=seed)
        if name != "whole":
            diff = paired_diff(base, scores, labels, groups, weights, rounds=rounds, seed=seed)
            parts = {split: paired_diff(base[masks[split]], scores[masks[split]],
                                        labels[masks[split]], groups[masks[split]],
                                        weights[masks[split]], rounds=rounds, seed=seed)
                     for split in ("1차", "2차")}
            item["짝_차이"] = {"전체": diff, **parts}
            item["판정"] = adoption(diff, parts["1차"], parts["2차"])
            if name in DIAGNOSTIC_VARIANTS:
                item["판정"] = {"채택": False, "사유": "사후 진단 — 채택 판단 대상 아님",
                              "기준_충족_여부": item["판정"]["채택"]}
        out[name] = item
    return out


def evaluate_splits(rows: list[dict], methods: dict[str, np.ndarray], names: list[str], *,
                    rounds: int, seed: int) -> dict:
    labels = np.asarray([r["label"] for r in rows])
    groups = np.asarray([r["심판번호"] for r in rows])
    weights = np.asarray([r["weight"] for r in rows])
    out: dict = {}
    for split, test in SPLITS:
        m = np.asarray([test(r) for r in rows])
        cases = {r["심판번호"] for r, k in zip(rows, m) if k}
        out[split] = {"행": int(m.sum()), "사건": len(cases)}
        for name in names:
            out[split][name] = auc_block(methods[name][m], labels[m], groups[m], weights[m],
                                         rounds=rounds, seed=seed)
    return out


def realistic(rows: list[dict], easy: list[dict], methods: dict[str, np.ndarray],
              easy_methods: dict[str, np.ndarray], names: list[str], *, rounds: int,
              seed: int) -> dict:
    """심결 도형계 쌍 + 쉬운 음성(비유사 가정) — 참고값."""
    all_rows = rows + easy
    labels = np.asarray([r["label"] for r in all_rows])
    groups = np.asarray([r["심판번호"] for r in all_rows])
    weights = np.asarray([r["weight"] for r in all_rows])
    counts = {s: sum(1 for r in easy if r["source"] == s) for s in ("cross", "db")}
    out: dict = {"쉬운_음성": counts}
    for name in names:
        scores = np.concatenate([methods[name], easy_methods[name]])
        out[name] = auc_block(scores, labels, groups, weights, rounds=rounds, seed=seed)
    return out


def rule_block(rows: list[dict], scores: np.ndarray, *, easy: list[dict] | None = None,
               easy_scores: np.ndarray | None = None) -> dict:
    labels = np.asarray([r["label"] for r in rows])
    weights = np.asarray([r["weight"] for r in rows])
    valid = ~np.isnan(scores)
    out = {
        "표": threshold_table(scores, labels, weights),
        "정밀도_0.7_τ": ab.precision_threshold(scores[valid], labels[valid],
                                              target=STANDALONE_PRECISION,
                                              min_support=MIN_SUPPORT),
        "현재_τ": FIGURE_TAU,
    }
    if easy and easy_scores is not None:
        all_scores = np.concatenate([scores, easy_scores])
        all_labels = np.concatenate([labels, np.zeros(len(easy), dtype=int)])
        all_weights = np.concatenate([weights, np.ones(len(easy))])
        out["현실_분포_표"] = threshold_table(all_scores, all_labels, all_weights)
    return out


def vienna_quality(index: ViennaIndex, rows: list[dict], embeddings: dict) -> dict:
    out: dict = {"LOO": {}, "LOO_같은_출원인_제외": {}, "기준선_흔한_코드": {}, "심결_상대표장": {}}
    for level in VIENNA_LEVELS:
        out["기준선_흔한_코드"][level] = prior_baseline(index, level=level)
        for k in (1, 5, 10):
            out["LOO"][f"{level}_k{k}"] = leave_one_out(index, level=level, k=k)
            out["LOO_같은_출원인_제외"][f"{level}_k{k}"] = leave_one_out(
                index, level=level, k=k, same_applicant=True)
            estimated, actual = [], []
            for row in rows:
                vector = embeddings.get(str(row["image_b"]))
                if row["codes_b"] and vector is not None:
                    estimated.append(index.estimate(vector, level=level, k=k))
                    actual.append(level_codes(row["codes_b"], level))
            out["심결_상대표장"][f"{level}_k{k}"] = estimate_quality(estimated, actual)
    return out


def embed_all(paths: list[Path], cache_path: Path, encode=None) -> dict:
    kwargs = {"encode": encode} if encode is not None else {}
    result = x2b.embed_paths(sorted(set(paths)), cache_path, **kwargs)
    result.pop(x2b.FAILURES_KEY, None)
    return result


def db_vectors(db: list[dict], index_path: Path, meta_path: Path) -> np.ndarray:
    """DB 이미지 → 서비스 FAISS 색인 벡터(reconstruct), db 목록 순서."""
    from src.search import load_index

    index = load_index(index_path)
    names = json.loads(Path(meta_path).read_text(encoding="utf-8"))["image_paths"]
    position = {name: i for i, name in enumerate(names)}
    return np.stack([np.asarray(index.reconstruct(position[d["file"]]), dtype=np.float32)
                     for d in db])


def run(base: Path, *, out_path: Path, rounds: int, seed: int, with_easy: bool = True,
        detector=None, encode=None, db: list[dict] | None = None,
        db_matrix: np.ndarray | None = None, db_meta: Path = DEFAULT_DB_META) -> dict:
    rows, features = load_sample(base)
    db = db if db is not None else load_db(db_meta, DEFAULT_DB_IMAGES)
    if db_matrix is None:
        db_matrix = db_vectors(db, pf.DEFAULT_INDEX, pf.DEFAULT_INDEX_META)
    coded = [i for i, d in enumerate(db) if d["codes"]]
    vindex = ViennaIndex(db_matrix[coded], [db[i]["codes"] for i in coded],
                         [db[i]["applicant"] for i in coded])
    easy = []
    if with_easy and (base / "pairs_features_easy.csv").exists():
        easy = load_easy(base, features, db, pf.read_db_records(db_meta))
    groups = [("trial", rows)] + ([("easy", easy)] if easy else [])
    images = sorted({Path(r[f"image_{s}"]) for _, rs in groups for r in rs for s in ("a", "b")})
    boxes = detect_boxes(images, base / "x2_figure_ocr.json", detector=detector)
    out_dir = base / "x2_figure"
    trial_cache, figure_cache = base / "x2_cache_v0.npz", base / "x2_cache_figure.npz"
    db_paths = {str(d["path"]): db_matrix[i] for i, d in enumerate(db) if d["file"]}
    originals = embed_all([p for p in images if str(p) not in db_paths], trial_cache, encode)
    originals.update({p: v for p, v in db_paths.items() if p in {str(i) for i in images}})
    result: dict = {"기준일": date.today().isoformat(), "주_설정": {
        "글자_지운_도형": PRIMARY_FIGURE, "비엔나": PRIMARY_VIENNA,
        "채택_기준": ("짝 부트스트랩 AUC 차이 CI 하한 > 0(가중 없음·가중) 이고 1차·2차 차이 "
                     "모두 양수"),
    }, "부트스트랩": {"단위": "사건", "회": rounds, "seed": seed, "사건가중_상한": CASE_CAP}}
    method_scores: dict[str, dict[str, np.ndarray]] = {}
    step_report: dict = {}
    for label, group_rows in groups:
        flags = photo_flags(group_rows)
        side_paths, steps = build_variants(group_rows, boxes, flags, out_dir)
        step_report[label] = steps
        processed = [p for variant in side_paths.values() for p in variant.values()]
        embeddings = dict(originals)
        embeddings.update(embed_all([p for p in processed if str(p) not in embeddings],
                                    figure_cache, encode))
        for variant, mapping in side_paths.items():  # 임베딩 실패(안전장치) → 원본
            for (index, side), path in mapping.items():
                if str(path) not in embeddings:
                    mapping[(index, side)] = Path(group_rows[index][f"image_{side}"])
                    steps[variant]["임베딩 실패 → 원본"] = steps[variant].get(
                        "임베딩 실패 → 원본", 0) + 1
        scores = {"whole": np.asarray([r["x2_whole"] for r in group_rows], dtype=np.float64),
                  "x2_fig_10월": np.asarray([r["x2_fig"] for r in group_rows], dtype=np.float64)}
        for variant in FIGURE_VARIANTS:
            scores[variant] = cosine_scores(group_rows, side_paths[variant], embeddings)
        for variant, spec in VIENNA_VARIANTS.items():
            scores[variant] = vienna_scores(group_rows, vindex, embeddings, spec)
        method_scores[label] = scores
        if label == "trial":
            result["비엔나_추정_품질"] = vienna_quality(vindex, group_rows, embeddings)
    rows_scores = method_scores["trial"]
    result["표본"] = {
        "행": len(rows), "사건": len({r["심판번호"] for r in rows}),
        "유사": sum(r["label"] for r in rows), "비유사": sum(1 - r["label"] for r in rows),
        "회차": {k: sum(1 for r in rows if r["회차"] == k) for k in ("1", "2")},
        "유형": {k: sum(1 for r in rows if r["유형"] == k) for k in FIGURE_TYPES},
        "사진_포함_쌍": sum(1 for r in rows if r["photo_a"] or r["photo_b"]),
        f"사건_{BIG_CASE}": sum(1 for r in rows if r["심판번호"] == BIG_CASE),
        "이름_상태": {
            "this": {"있음": sum(1 for r in rows if r["name_a"]),
                     "없음(도형)": sum(1 for r in rows if not r["name_a"])},
            "상대": {"있음": sum(1 for r in rows if r["name_b"]),
                     "없음(도형)": sum(1 for r in rows if r["name_b"] == ""),
                     "모름": sum(1 for r in rows if r["name_b"] is None)},
        },
        "처리_단계": step_report,
    }
    result["비엔나_보유"] = {
        "DB": {"전체": len(db), "6자리_코드": len(coded),
               "설명_문자열만": sum(1 for d in db if not d["codes"])},
        "도형계_표본": {"this_실제": sum(1 for r in rows if r["codes_a"]),
                     "상대_실제": sum(1 for r in rows if r["codes_b"]), "행": len(rows)},
    }
    result["방법"] = evaluate(rows, rows_scores, rounds=rounds, seed=seed)
    main = ["whole", "x2_fig_10월", PRIMARY_FIGURE, PRIMARY_VIENNA]
    result["나눠_보기"] = evaluate_splits(rows, rows_scores, main, rounds=rounds, seed=seed)
    adopted = next((n for n in (PRIMARY_FIGURE, PRIMARY_VIENNA)
                    if result["방법"][n]["판정"]["채택"]), "whole")
    result["채택_방법"] = adopted
    easy_scores = method_scores.get("easy")
    if easy and easy_scores is not None:
        result["현실_분포"] = realistic(rows, easy, rows_scores, easy_scores, main[:1] + main[2:],
                                    rounds=rounds, seed=seed)
    result["단독_규칙"] = {
        name: rule_block(rows, rows_scores[name], easy=easy or None,
                         easy_scores=easy_scores[name] if easy_scores is not None else None)
        for name in dict.fromkeys(["whole", adopted])
    }
    result["점수_분포"] = {name: {
        "유사": x2b.distribution(s[~np.isnan(s) & (np.asarray([r["label"] for r in rows]) == 1)]),
        "비유사": x2b.distribution(s[~np.isnan(s) & (np.asarray([r["label"] for r in rows]) == 0)]),
    } for name, s in rows_scores.items() if name in main}
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


# ---- 표 ------------------------------------------------------------------------------------------

def _ci(item: dict, key: str = "auc") -> str:
    value = item.get(key)
    if value is None:
        return "-"
    low, high = item.get(f"{key}_ci95") or (None, None)
    return f"{value:.3f} ({low:.2f}~{high:.2f})" if low is not None else f"{value:.3f}"


def _diff(item: dict, weighted: bool = False) -> str:
    value = item.get("diff_w" if weighted else "diff")
    low, high = item.get("ci95_w" if weighted else "ci95") or (None, None)
    if value is None:
        return "-"
    return f"{value:+.3f} ({low:+.2f}~{high:+.2f})" if low is not None else f"{value:+.3f}"


def report_text(result: dict) -> str:
    sample = result["표본"]
    lines = [
        f"표본 {sample['행']}쌍(유사 {sample['유사']}·비유사 {sample['비유사']}, "
        f"사건 {sample['사건']}) · "
        f"회차 {sample['회차']} · 유형 {sample['유형']} · 사진 포함 {sample['사진_포함_쌍']}",
        "", "## 방법별 AUC(사건 단위 CI) · 기준선(whole)과의 짝 차이",
        "| 방법 | AUC | 가중 AUC | 짝 차이 | 가중 짝 차이 | 1차 차이 | 2차 차이 | 판정 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, item in result["방법"].items():
        whole = item["전체"]
        pairs = item.get("짝_차이", {})
        verdict = item.get("판정", {})
        lines.append(
            f"| {name} | {_ci(whole)} n {whole['n']} | {_ci(whole, 'auc_w')} | "
            f"{_diff(pairs['전체']) if pairs else '기준'} | "
            f"{_diff(pairs['전체'], True) if pairs else ''} | "
            f"{_diff(pairs['1차']) if pairs else ''} | {_diff(pairs['2차']) if pairs else ''} | "
            f"{('채택' if verdict.get('채택') else '유지') if verdict else ''} |"
        )
    lines += ["", "## 1차·2차별 AUC", "| 방법 | 1차 | 2차 |", "|---|---|---|"]
    for name, item in result["방법"].items():
        lines.append(f"| {name} | {_ci(item['1차'])} n {item['1차']['n']} | "
                     f"{_ci(item['2차'])} n {item['2차']['n']} |")
    names = [n for n in next(iter(result["나눠_보기"].values())) if n not in ("행", "사건")]
    lines += ["", "## 나눠 보기(가중 없음 / 가중)",
              "| 부분 | 행·사건 | " + " | ".join(names) + " |", "|---|---|" + "---|" * len(names)]
    for split, item in result["나눠_보기"].items():
        cells = [f"{_ci(item[n])} / {item[n].get('auc_w') or '-'}" for n in names]
        lines.append(f"| {split} | {item['행']}·{item['사건']} | " + " | ".join(cells) + " |")
    if "현실_분포" in result:
        real = result["현실_분포"]
        lines += ["", f"## 현실 분포 참고(심결 도형계 + 쉬운 음성 {real['쉬운_음성']})"]
        for name, item in real.items():
            if name != "쉬운_음성":
                lines.append(f"- {name}: {_ci(item)} n {item['n']} · 가중 {_ci(item, 'auc_w')}")
    quality = result["비엔나_추정_품질"]
    lines += ["", "## 비엔나 추정 품질(자카드 평균 · 적중률)"]
    for block in ("LOO", "LOO_같은_출원인_제외", "심결_상대표장"):
        cells = [f"{k} {v.get('자카드_평균')}·{v.get('적중률')} (n {v.get('n')})"
                 for k, v in quality[block].items()]
        lines.append(f"- {block}: " + " · ".join(cells))
    baseline = quality["기준선_흔한_코드"].items()
    lines.append("- 기준선(흔한 코드): " + " · ".join(
        f"{k} {v.get('자카드_평균')}·{v.get('적중률')}" for k, v in baseline))
    for name, block in result["단독_규칙"].items():
        best = block["정밀도_0.7_τ"]
        lines += ["", f"## 도형 단독 규칙 — {name}(정밀도 0.7 τ: {best.get('threshold')})",
                  "| τ | 지지 | 정밀도 | 가중 정밀도 | 재현율 |", "|---|---|---|---|---|"]
        for row in block["표"]:
            lines.append(f"| {row['τ']} | {row['지지_n']} | {row['정밀도']} | "
                         f"{row['가중_정밀도']} | {row['재현율']} |")
    lines.append(f"\n채택 방법: {result['채택_방법']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bootstrap", type=int, default=x2b.BOOTSTRAP_ROUNDS)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-easy", action="store_true", help="쉬운 음성 참고값 생략")
    args = parser.parse_args(argv)
    result = run(args.base, out_path=args.out, rounds=args.bootstrap, seed=args.seed,
                 with_easy=not args.no_easy)
    print(report_text(result))
    print(f"\nJSON: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
