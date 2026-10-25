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

