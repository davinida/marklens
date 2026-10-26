"""유형 판정 OCR(backend/src/core/ocr.py) — 가짜 OCR·비활성 스위치·시간 초과·실패 폴백. easyocr 없이
돈다."""

from __future__ import annotations

import time

import pytest
from PIL import Image, ImageDraw

from backend.src.core import config, multi_search, ocr


def _square():
    return Image.new("RGB", (64, 64), (200, 40, 40))


@pytest.fixture(autouse=True)
def _reset_ocr():
    ocr.reset()
    yield
    ocr.reset()


def test_fake_detect_is_deterministic_figure(monkeypatch):
    monkeypatch.setenv("MARKLENS_FAKE_ML", "1")
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    first, second = ocr.detect(_square()), ocr.detect(_square())
    assert first == second
    assert first.kind == "도형" and first.dominant == "도형" and first.text_ratio == 0.0
    image = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(image).rectangle((20, 20, 80, 80), fill="black")
    detection = ocr.detect(image)
    assert detection.kind == "도형" and detection.fig_ratio == pytest.approx(0.3721, abs=1e-3)
    assert ocr.state.loads == 0  # 가짜 모드는 easyocr 를 올리지 않는다


def test_disabled_switch_returns_none(monkeypatch):
    monkeypatch.setenv("MARKLENS_FAKE_ML", "1")
    monkeypatch.setattr(config, "OCR_ENABLED", False)
    assert ocr.detect(_square()) is None
    assert ocr.state.calls == 0


def test_timeout_falls_back_and_counts(monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(ocr, "is_fake", lambda: False)

    def slow(image):
        time.sleep(0.3)
        return ocr.detect_fake(image)

    monkeypatch.setattr(ocr, "_detect_sync", slow)
    assert ocr.detect(_square(), timeout=0.05) is None
    assert ocr.state.timeouts == 1 and ocr.state.calls == 1
    time.sleep(0.35)  # 워커가 끝나길 기다렸다가 다음 요청은 결과를 받는다
    assert ocr.detect(_square(), timeout=1.0) is not None


def test_failure_falls_back_and_counts(monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(ocr, "is_fake", lambda: False)

    def broken(image):
        raise RuntimeError("model download failed")

    monkeypatch.setattr(ocr, "_detect_sync", broken)
    assert ocr.detect(_square()) is None
    assert ocr.state.failures == 1 and ocr.state.last_error == "RuntimeError"


def test_default_timeout_comes_from_config():
    assert config.OCR_TIMEOUT == 2.0 and config.OCR_ENABLED is True


def test_particle_for_fallback_caveat():
    assert multi_search._particle_ro("도형") == "으로"
    assert multi_search._particle_ro("문자") == "로"
    assert multi_search._particle_ro("결합") == "으로"
    assert multi_search.CAVEAT_OCR_FALLBACK.format(type="도형", ro="으로").startswith(
        "이미지에서 글자를 읽지 못해 유형을 도형으로 두었습니다"
    )


def test_suggested_text_filters_by_confidence_and_order():
    from src.mark_type import TextBox

    from backend.src.core.ocr import SUGGEST_MAX_CHARS, _detection, suggested_text

    boxes = [
        TextBox((0, 40, 50, 60), "hands", 0.91),
        TextBox((0, 0, 40, 20), "BLU", 0.88),
        TextBox((60, 0, 90, 20), "x", 0.3),  # 확신도 < 0.5 — 제외
        TextBox((0, 70, 50, 90), "  ", 0.99),  # 빈 글자 — 제외
    ]
    assert suggested_text(boxes) == "BLU hands"
    assert len(suggested_text([TextBox((0, 0, 1, 1), "가" * 100, 0.9)])) == SUGGEST_MAX_CHARS
    assert suggested_text([]) == ""
    detection = _detection(Image.new("RGB", (100, 100), "white"), boxes, time.perf_counter())
    assert detection.text == "BLU hands" and detection.boxes == 3  # 면적 하한 0.2 는 x 도 셈



@pytest.mark.parametrize("size,expected", [
    ((64, 64), (160, 160)),  # 작은 표장은 짧은 변 160px 로 키운다(x2_split 과 같음)
    ((500, 300), (500, 300)),  # 범위 안은 그대로
    ((1920, 892), (640, 297)),  # 큰 업로드는 긴 변 640px 로 줄인다
    ((3024, 4032), (480, 640)),
    ((1000, 100), (640, 64)),  # 키우면 상한을 넘는 가로형은 상한이 우선
])
def test_ocr_input_is_bounded_and_boxes_map_back(monkeypatch, size, expected):
    seen = []

    class Reader:
        def readtext(self, array, detail=1):
            seen.append((array.shape[1], array.shape[0]))
            h, w = array.shape[:2]
            return [([[0, 0], [w, 0], [w, h // 2], [0, h // 2]], "BLU", 0.9)]

    monkeypatch.setattr(ocr, "_get_reader", lambda: Reader())
    boxes = ocr._easyocr_boxes(Image.new("RGB", size, "white"))
    assert seen == [expected]
    x0, y0, x1, y1 = boxes[0].bbox  # 좌표는 원본 크기로 되돌린다(축소 입력의 1px 오차 안)
    tolerance = size[1] / expected[1] + 1
    assert (x0, y0) == (0, 0) and abs(x1 - size[0]) <= 1 and abs(y1 - size[1] / 2) <= tolerance


def test_warm_up_is_noop_when_disabled_or_fake(monkeypatch):
    monkeypatch.setattr(ocr, "_get_reader", lambda: pytest.fail("리더를 올리면 안 된다"))
    monkeypatch.setattr(config, "OCR_ENABLED", False)
    assert ocr.warm_up() is None
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setenv("MARKLENS_FAKE_ML", "1")
    assert ocr.warm_up() is None


def test_warm_up_loads_reader_in_background_and_survives_failure(monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(ocr, "is_fake", lambda: False)
    calls = []

    class Reader:
        def readtext(self, array, detail=1):
            calls.append(array.shape)
            return []

    monkeypatch.setattr(ocr, "_get_reader", lambda: Reader())
    ocr.warm_up().result(timeout=5)
    assert calls == [(160, 160, 3)]

    def broken():
        raise RuntimeError("download failed")

    monkeypatch.setattr(ocr, "_get_reader", broken)
    ocr.warm_up().result(timeout=5)  # 예외를 밖으로 내지 않는다
    assert ocr.state.failures == 1 and ocr.state.last_error == "RuntimeError"
