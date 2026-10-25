"""상표 유형 판정 규칙 — 이미지의 글자·도형 면적 비율(OCR)과 메타데이터(상표구분·비엔나코드)로
문자·도형·결합을 가른다.

X2 v1 ① 실험(ml/scripts/x2_split.py)의 `auto_type` 규칙(text_ratio < 0.05 → 도형, fig_ratio < 0.08 →
문자, 그 외 결합·큰 쪽이 요부)을 서비스(backend/src/core/ocr.py·multi_search.py, API 계약 v2 §2-4)와
사전 계산 스크립트(ml/scripts/precompute_types.py)가 같이 쓰도록 옮긴 것이다. x2_split 은 여기서
import 해 쓴다(규칙이 두 곳에서 어긋나지 않게). torch·easyocr 를 import 하지 않는다 — OCR 호출은
호출자가 하고 여기에는 박스 목록만 넘긴다.

통합 모델(ml/src/model/risk_model.py)이 쓰는 유형은 네
수준(문자·도형·결합-문자요부·결합-도형요부)이고,
후보 표시용 유형(계약 §2-2 `candidates[].type`)은 세 수준(문자·도형·결합)이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

__all__ = [
    "TEXT_RATIO_FIGURE", "FIG_RATIO_TEXT", "MIN_TEXT_CONF", "ERASE_DIFF", "UPSCALE_MIN_SIDE",
    "MODEL_TYPES", "DISPLAY_TYPES", "OVERRIDE_TYPES", "TextBox", "auto_type", "area_ratios",
    "background_color", "content_bbox", "model_type", "display_type", "classify_metadata",
    "type_from_metadata",
]

TEXT_RATIO_FIGURE = 0.05  # 글자 박스 면적이 이보다 작으면 도형
FIG_RATIO_TEXT = 0.08  # 글자를 지운 뒤 남은 내용이 이보다 작으면 문자
MIN_TEXT_CONF = 0.2  # 인식 확신도 하한 — 도형의 거짓 박스(0.02) 제거
ERASE_DIFF = 24  # 배경 중앙값과 채널 차이가 이보다 크면 내용
UPSCALE_MIN_SIDE = 160  # OCR 입력의 짧은 변 하한(px)

# 통합 모델 입력 유형(risk_model.TYPE_LEVELS 와 같은 네 수준)
MODEL_TYPES = ("문자", "도형", "결합-문자요부", "결합-도형요부")
DISPLAY_TYPES = ("문자", "도형", "결합")  # 후보 표시용(계약 §2-2)
OVERRIDE_TYPES = ("문자", "도형", "결합")  # 요청 type_override 허용값(계약 §1-1)


@dataclass(frozen=True)
class TextBox:
    bbox: tuple[int, int, int, int]  # x0, y0, x1, y1 (원본 픽셀)
    text: str
    conf: float


def auto_type(text_ratio: float, fig_ratio: float) -> tuple[str, str]:
    """(자동 유형, 요부). 문자·도형은 요부가 곧 유형, 결합은 둘 중 큰 쪽."""
    if text_ratio < TEXT_RATIO_FIGURE:
        return "도형", "도형"
    if fig_ratio < FIG_RATIO_TEXT:
        return "문자", "문자"
    return "결합", ("도형" if fig_ratio >= text_ratio else "문자")


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


def area_ratios(image, boxes: Iterable[TextBox], *, min_conf: float = MIN_TEXT_CONF,
                diff: int = ERASE_DIFF) -> tuple[float, float]:
    """(text_ratio, fig_ratio) — x2_split.split_image 와 같은 계산(도형 크롭은 만들지 않는다).

    text_ratio = 확신도 ≥ min_conf 인 글자 박스 합집합 면적 / 전체. 글자 박스를 배경색으로 지운 뒤
    배경과 diff 넘게 다른 픽셀의 bbox 면적 / 전체 = fig_ratio.
    """
    arr = np.asarray(image.convert("RGB"))
    height, width = arr.shape[:2]
    if height == 0 or width == 0:
        return 0.0, 0.0
    kept = [box for box in boxes if box.conf >= min_conf and box.text.strip()]
    mask = np.zeros((height, width), dtype=bool)
    for box in kept:
        x0, y0, x1, y1 = box.bbox
        mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True
    text_ratio = float(mask.mean())
    background = background_color(arr)
    erased = arr.copy()
    erased[mask] = background.astype(arr.dtype)
    bbox = content_bbox(erased, background, diff=diff)
    fig_ratio = 0.0
    if bbox is not None:
        x0, y0, x1, y1 = bbox
        fig_ratio = (x1 - x0) * (y1 - y0) / float(width * height)
    return round(text_ratio, 4), round(fig_ratio, 4)


def model_type(kind: str, dominant: str, *, has_name: bool) -> str:
    """OCR 자동 유형(문자·도형·결합 + 요부) 또는 사용자 유형(type_override)을 통합 모델의 네
    수준으로.

    결합은 요부(OCR 이면 면적이 큰 쪽)에 따라 결합-문자요부·결합-도형요부. 요부를 모르면(사용자가
    "결합"만 고름) 이름이 있을 때 결합-문자요부, 없을 때 결합-도형요부(계약 §2-4 5항).
    """
    if kind == "결합":
        if dominant in ("문자", "도형"):
            return f"결합-{dominant}요부"
        return "결합-문자요부" if has_name else "결합-도형요부"
    if kind in ("문자", "도형"):
        return kind
    raise ValueError(f"알 수 없는 유형: {kind!r}")


def display_type(level: str) -> str:
    """통합 모델 네 수준 → 표시용 세 수준."""
    return "결합" if level.startswith("결합") else level


def classify_metadata(
    mark_kind: object, vienna_codes: object, name: object
) -> tuple[str | None, str]:
    """KIPRIS 메타데이터로 후보 표시용 유형과 근거(계약 §2-2): 상표구분 '도형상표' → 도형,
    '도형복합' →
    결합(근거 "상표구분"); 비어 있으면 비엔나코드 + 상표명 → 결합, 비엔나코드만 → 도형(근거
    "비엔나코드");
    비엔나코드 없이 상표명만 → 문자(근거 "상표명"). 셋 다 비어 있으면 (None, "없음") — OCR 폴백
    대상."""
    kind = str(mark_kind or "").strip()
    if kind == "도형상표":
        return "도형", "상표구분"
    if kind == "도형복합":
        return "결합", "상표구분"
    vienna = [str(code).strip() for code in (vienna_codes or []) if str(code).strip()]
    has_name = bool(str(name or "").strip())
    if vienna:
        return ("결합" if has_name else "도형"), "비엔나코드"
    if has_name:
        return "문자", "상표명"
    return None, "없음"


def type_from_metadata(mark_kind: object, vienna_codes: object, name: object) -> str | None:
    """classify_metadata 의 유형만."""
    return classify_metadata(mark_kind, vienna_codes, name)[0]
