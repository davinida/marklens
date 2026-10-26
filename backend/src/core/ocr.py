"""표장 이미지 유형 판정(OCR) — 3입력 통합 검색의 `query_type`(API 계약 v2 §2-4, 엔진 E-4).

easyocr(CRAFT 검출 + ko·en 인식, CPU)를 **첫 호출 때 지연 로드**하고 글자 박스
면적(text_ratio)·글자를
지운 뒤 남은 내용 면적(fig_ratio)으로 `src.mark_type.auto_type` 규칙(0.05/0.08, x2_split 과 같은
식)을
적용한다. 결과가 없으면(비활성·시간 초과·예외) None 을 돌려주고 호출자(multi_search)가 fallback 으로
간다 — 이름이 있으면 문자, 없으면 도형, caveat `OCR_FALLBACK`.

- `MARKLENS_OCR_ENABLED`(기본 1): 0 이면 항상 None(easyocr 를 import 하지 않는다).
- `MARKLENS_OCR_TIMEOUT`(기본 2.0초): 로드·인식이 이 시간을 넘으면 그 요청은 None. 작업은 전용
스레드 1개
  에서 이어지므로 첫 로드(모델 다운로드·초기화 수 초)가 끝난 뒤의 요청부터 OCR 결과가 나온다 —
  그래서 서버 기동 때 `warm_up()` 으로 미리 적재하고, 큰 업로드는 긴 변 `OCR_MAX_SIDE` 로
  줄여 넣는다.
- `EASYOCR_MODULE_PATH`: 모델 디렉터리(비우면 easyocr 기본 ~/.EasyOCR). 컨테이너는 빌드 때 받아
둔다.
- `MARKLENS_FAKE_ML`: 가짜 OCR — 글자 박스를 찾지 않고 면적 비율만 계산한다(결정적, 모델 없음). 단색
  정사각형 픽스처는 도형, 테스트가 글자 박스를 흉내 내려면 `detect` 를 몽키패치한다.

동기 함수다. API 는 engine.multi_search 를 기존 검색과 같은 스레드 풀에서 부르고, 그 안에서 이
모듈이
자체 워커 스레드로 시간 상한을 건다(이벤트 루프를 막지 않는다). 로그에 이미지·글자 내용은 남기지
않는다.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field

import numpy as np

from . import config, paths

if str(paths.ML_ROOT) not in sys.path:
    sys.path.insert(0, str(paths.ML_ROOT))

from src import mark_type as mt  # noqa: E402

logger = logging.getLogger(__name__)

LANGUAGES = ("ko", "en")
ENV_FAKE = "MARKLENS_FAKE_ML"
# 이름 없는 이미지 질의에서 "읽은 글자"를 제안할 때(계약 §2-4 5항·§2-5 NAME_SUGGESTED): 확신도 ≥
# 0.5 인 박스만 읽기 순서(위→아래, 왼→오른)로 이어 붙이고 60자에서 자른다. 면적 비율의
# 하한(MIN_TEXT_CONF 0.2)보다 엄격하다.
SUGGEST_MIN_CONF = 0.5
SUGGEST_MAX_CHARS = 60
# OCR 입력의 긴 변 상한(px). 서비스 업로드는 수천 px(폰 사진·로고 원본)이라 CPU CRAFT 검출이
# 원본 그대로면 6~31초 걸려 2초 상한에 항상 걸리고 fallback 된다. 실측(Apple Silicon,
# 2026-10-26, 합성 로고 4종): 원본 6.5~31초 → 640px 0.6~1.1초, 읽은 글자는 같다(심결 PDF 의
# 작은 표장은 이 상한에 걸리지 않아 벤치마크와 같다).
OCR_MAX_SIDE = 640


@dataclass(frozen=True)
class TypeDetection:
    """OCR 판정 결과 — 계약 `query_type.detail` 의 text_ratio·fig_ratio 와 auto_type 결과."""

    text_ratio: float
    fig_ratio: float
    kind: str  # 문자 | 도형 | 결합
    dominant: str  # 결합의 요부(문자 | 도형), 문자·도형은 유형과 같음
    boxes: int  # 확신도 하한을 넘은 글자 박스 수
    text: str  # 확신도 ≥ SUGGEST_MIN_CONF 박스의 글자(읽기 순서, 최대 60자) — 없으면 ""
    elapsed_ms: float = field(compare=False)  # 결정성 비교(테스트)에서 제외


@dataclass
class OcrState:
    reader: object | None = None
    loads: int = 0
    calls: int = 0
    timeouts: int = 0
    failures: int = 0
    last_error: str = ""


state = OcrState()
_lock = threading.Lock()
# 워커 1개: easyocr 는 스레드 안전을 보장하지 않고, CPU 추론을 겹쳐 돌리면 전부 느려진다.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="marklens-ocr")


def enabled() -> bool:
    return bool(config.OCR_ENABLED)


def is_fake() -> bool:
    return bool(os.environ.get(ENV_FAKE))


def reset() -> None:
    """테스트용: 로드된 리더와 카운터를 비운다."""
    with _lock:
        state.reader = None
        state.loads = 0
        state.calls = 0
        state.timeouts = 0
        state.failures = 0
        state.last_error = ""


def _get_reader():
    """easyocr Reader 지연 로드(프로세스 1개). 모델 디렉터리는 EASYOCR_MODULE_PATH."""
    with _lock:
        if state.reader is None:
            import easyocr  # 무거운 import — OCR 을 실제로 쓸 때만

            kwargs: dict = {"gpu": False, "verbose": False}
            if config.EASYOCR_MODULE_PATH:
                kwargs["model_storage_directory"] = config.EASYOCR_MODULE_PATH
            started = time.perf_counter()
            state.reader = easyocr.Reader(list(LANGUAGES), **kwargs)
            state.loads += 1
            logger.info("easyocr 로드 완료(%.0fms)", (time.perf_counter() - started) * 1000)
        return state.reader


def _ocr_scale(width: int, height: int) -> float:
    """OCR 입력 배율 — 작은 이미지는 짧은 변 160px 로 키우고(x2_split 과 같음), 그 결과의 긴 변이
    OCR_MAX_SIDE 를 넘으면 긴 변을 OCR_MAX_SIDE 로 줄인다(시간 상한 우선)."""
    scale = max(1.0, mt.UPSCALE_MIN_SIDE / max(1, min(width, height)))
    if max(width, height) * scale > OCR_MAX_SIDE:
        scale = OCR_MAX_SIDE / max(width, height)
    return scale


def _easyocr_boxes(image) -> list[mt.TextBox]:
    """x2_split.EasyOcrDetector 와 같은 방식 — 작은 이미지는 짧은 변 160px 로 키워 넣고(큰 이미지는
    긴 변 OCR_MAX_SIDE 로 줄여) 좌표를 원본 크기로 되돌린다."""
    reader = _get_reader()
    rgb = image.convert("RGB")
    width, height = rgb.size
    scale = _ocr_scale(width, height)
    if scale != 1.0:
        from PIL import Image

        rgb = rgb.resize((round(width * scale), round(height * scale)), Image.LANCZOS)
    boxes: list[mt.TextBox] = []
    for points, text, conf in reader.readtext(np.asarray(rgb), detail=1):
        xs = [float(p[0]) / scale for p in points]
        ys = [float(p[1]) / scale for p in points]
        bbox = (
            max(0, int(min(xs))), max(0, int(min(ys))),
            min(width, int(np.ceil(max(xs)))), min(height, int(np.ceil(max(ys)))),
        )
        boxes.append(mt.TextBox(bbox, str(text), float(conf)))
    return boxes


def suggested_text(boxes: list[mt.TextBox]) -> str:
    """읽은 글자 제안 — 확신도 ≥ SUGGEST_MIN_CONF 박스를 읽기 순서(y → x)로 이어 붙여 최대
    SUGGEST_MAX_CHARS 자."""
    kept = [box for box in boxes if box.conf >= SUGGEST_MIN_CONF and box.text.strip()]
    kept.sort(key=lambda box: (box.bbox[1], box.bbox[0]))
    text = " ".join(" ".join(box.text.split()) for box in kept)
    return text[:SUGGEST_MAX_CHARS].rstrip()


def _detection(image, boxes: list[mt.TextBox], started: float) -> TypeDetection:
    text_ratio, fig_ratio = mt.area_ratios(image, boxes)
    kind, dominant = mt.auto_type(text_ratio, fig_ratio)
    kept = sum(1 for box in boxes if box.conf >= mt.MIN_TEXT_CONF and box.text.strip())
    return TypeDetection(text_ratio, fig_ratio, kind, dominant, kept, suggested_text(boxes),
                         round((time.perf_counter() - started) * 1000, 1))


def _detect_sync(image) -> TypeDetection:
    started = time.perf_counter()
    return _detection(image, _easyocr_boxes(image), started)


def detect_fake(image) -> TypeDetection:
    """가짜 OCR(MARKLENS_FAKE_ML): 글자 박스 없음 → 면적 비율만. 내용이 있는 이미지는 도형, 없으면
    도형(0/0)."""
    return _detection(image, [], time.perf_counter())


def warm_up() -> Future | None:
    """기동 때 리더를 OCR 워커에서 미리 적재한다(기다리지 않음). 첫 적재는 수 초(모델이 없으면
    다운로드 수 분)라 그대로 두면 재기동 뒤 첫 이미지 요청들이 2초 상한에 걸려 fallback 된다. 같은
    워커라 적재 중에 온 요청은 그 뒤에 줄을 선다. 비활성·가짜 모드면 아무것도 하지 않는다. 실패해도
    기동은 계속하고 요청 때 다시 시도한다."""
    if not enabled() or is_fake():
        return None

    def load() -> None:
        try:
            # 첫 readtext 는 추론 경로 초기화로 느리다 — 작은 흰 이미지로 한 번 돌려 둔다
            _get_reader().readtext(np.full((mt.UPSCALE_MIN_SIDE,) * 2 + (3,), 255, np.uint8))
        except Exception as exc:
            state.failures += 1
            state.last_error = type(exc).__name__
            logger.warning("OCR 미리 적재 실패(%s) — 요청 때 다시 시도", type(exc).__name__)

    return _executor.submit(load)


def detect(image, *, timeout: float | None = None) -> TypeDetection | None:
    """표장 이미지(PIL)의 유형 판정. 비활성·시간 초과·오류면 None(호출자가 fallback)."""
    if not enabled():
        return None
    if is_fake():
        return detect_fake(image)
    limit = config.OCR_TIMEOUT if timeout is None else timeout
    state.calls += 1
    future = _executor.submit(_detect_sync, image)
    try:
        return future.result(timeout=limit)
    except FutureTimeoutError:
        state.timeouts += 1
        logger.warning("OCR 시간 초과(%.1fs) — 유형은 fallback 으로", limit)
        return None
    except Exception as exc:  # 모델 다운로드 실패·디코딩 오류 등 — 입력이 아니라 환경 문제
        state.failures += 1
        state.last_error = type(exc).__name__
        logger.warning("OCR 실패(%s) — 유형은 fallback 으로", type(exc).__name__)
        return None
