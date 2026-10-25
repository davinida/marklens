"""상표 유형 규칙(ml/src/mark_type.py) — x2_split 과 같은 auto_type, 면적 비율, 메타데이터 규칙,
모델 유형."""

from __future__ import annotations

import numpy as np
import pytest
import torch  # noqa: F401  (x2_split 이 faiss 를 올리기 전에 torch 가 먼저 — ml/src/search.py 주석)
from PIL import Image, ImageDraw
from src import mark_type as mt

from scripts import x2_split as xs


@pytest.mark.parametrize("text_ratio,fig_ratio", [
    (0.0, 0.0), (0.01, 0.9), (0.049, 0.05), (0.05, 0.0), (0.2, 0.079), (0.2, 0.08), (0.3, 0.6),
    (0.6, 0.3), (0.5, 0.5), (1.0, 1.0),
])
def test_auto_type_is_shared_with_x2_split(text_ratio, fig_ratio):
    assert mt.auto_type(text_ratio, fig_ratio) == xs.auto_type(text_ratio, fig_ratio)
    assert xs.TEXT_RATIO_FIGURE == mt.TEXT_RATIO_FIGURE == 0.05
    assert xs.FIG_RATIO_TEXT == mt.FIG_RATIO_TEXT == 0.08
    assert xs.TextBox is mt.TextBox


def test_auto_type_rule_boundaries():
    assert mt.auto_type(0.0, 0.5) == ("도형", "도형")
    assert mt.auto_type(0.1, 0.0) == ("문자", "문자")
    assert mt.auto_type(0.1, 0.5) == ("결합", "도형")
    assert mt.auto_type(0.5, 0.1) == ("결합", "문자")
    assert mt.auto_type(0.3, 0.3) == ("결합", "도형")  # 같으면 도형


def test_area_ratios_text_box_and_figure():
    image = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(image).ellipse((120, 10, 190, 90), fill="black")  # 오른쪽 도형
    boxes = [mt.TextBox((0, 0, 100, 50), "TEXT", 0.9), mt.TextBox((0, 0, 200, 100), "x", 0.05)]
    text_ratio, fig_ratio = mt.area_ratios(image, boxes)
    assert text_ratio == pytest.approx(0.25, abs=1e-4)  # 확신도 0.05 박스는 제외
    assert 0.2 < fig_ratio < 0.4  # 타원 bbox(70×80)/전체(200×100) = 0.28
    assert mt.auto_type(text_ratio, fig_ratio) == ("결합", "도형")
    blank = Image.new("RGB", (64, 64), (200, 40, 40))
    assert mt.area_ratios(blank, []) == (0.0, 0.0)
    assert mt.auto_type(*mt.area_ratios(blank, [])) == ("도형", "도형")


def test_area_ratios_matches_x2_split_split_image():
    image = Image.new("RGB", (120, 60), "white")
    ImageDraw.Draw(image).rectangle((70, 10, 110, 50), fill="blue")
    boxes = [mt.TextBox((5, 20, 60, 40), "COCO", 0.8)]
    text_ratio, fig_ratio = mt.area_ratios(image, boxes)
    result = xs.split_image(image, boxes)
    assert (text_ratio, fig_ratio) == (result.text_ratio, result.fig_ratio)
    assert mt.auto_type(text_ratio, fig_ratio) == (result.auto_type, result.dominant)


def test_model_type_and_display_type():
    assert mt.model_type("문자", "문자", has_name=True) == "문자"
    assert mt.model_type("도형", "도형", has_name=False) == "도형"
    assert mt.model_type("결합", "문자", has_name=False) == "결합-문자요부"
    assert mt.model_type("결합", "도형", has_name=True) == "결합-도형요부"
    assert mt.model_type("결합", "", has_name=True) == "결합-문자요부"  # 사용자 '결합' + 이름
    assert mt.model_type("결합", "", has_name=False) == "결합-도형요부"
    with pytest.raises(ValueError):
        mt.model_type("사진", "", has_name=True)
    assert [mt.display_type(level) for level in mt.MODEL_TYPES] == ["문자", "도형", "결합", "결합"]


@pytest.mark.parametrize("mark_kind,vienna,name,expected", [
    ("도형상표", ["270522"], "이름", ("도형", "상표구분")),
    ("도형복합", [], None, ("결합", "상표구분")),
    ("", ["020901"], "이름", ("결합", "비엔나코드")),
    (None, ["020901"], "", ("도형", "비엔나코드")),
    ("", [], "이름", ("문자", "상표명")),
    (None, None, None, (None, "없음")),
])
def test_classify_metadata_rule(mark_kind, vienna, name, expected):
    assert mt.classify_metadata(mark_kind, vienna, name) == expected
    assert mt.type_from_metadata(mark_kind, vienna, name) == expected[0]


def test_background_and_content_bbox():
    arr = np.full((20, 30, 3), 255, dtype=np.uint8)
    arr[5:10, 8:12] = 0
    background = mt.background_color(arr)
    assert tuple(background) == (255.0, 255.0, 255.0)
    assert mt.content_bbox(arr, background) == (8, 5, 12, 10)
    assert mt.content_bbox(np.full((4, 4, 3), 9, dtype=np.uint8), np.array([9, 9, 9])) is None
