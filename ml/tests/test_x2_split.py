"""X2 v1 요부 분리 테스트 — 가짜 검출기·가짜 임베더만 쓴다(easyocr·CLIP 모델 다운로드 없음)."""

from __future__ import annotations

import json

import numpy as np
import pytest
import torch
from PIL import Image, ImageDraw
from src import embedding

from scripts import trials_extract_images as tei
from scripts import x2_benchmark as x2b
from scripts import x2_split as xs


class FakeDetector:
    """검은 픽셀 덩어리를 글자 박스 하나로 본다. 글자 내용은 이미지 크기별로 정해 둔다."""

    def __init__(self, texts: dict[tuple[int, int], str] | None = None, conf: float = 0.9,
                 extra: list[xs.TextBox] | None = None) -> None:
        self.texts = texts or {}
        self.conf = conf
        self.extra = extra or []
        self.calls = 0

    def detect(self, image: Image.Image) -> list[xs.TextBox]:
        self.calls += 1
        arr = np.asarray(image.convert("RGB"))
        black = (arr < 30).all(axis=2)
        boxes = list(self.extra)
        if black.any():
            ys, xs_ = np.nonzero(black)
            bbox = (int(xs_.min()), int(ys.min()), int(xs_.max()) + 1, int(ys.max()) + 1)
            boxes.append(xs.TextBox(bbox, self.texts.get(image.size, "TEXT"), self.conf))
        return boxes


def text_image(size=(200, 80)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).rectangle((20, 20, 179, 59), fill="black")
    return image


def figure_image(size=(200, 200), color=(220, 30, 30)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).ellipse((50, 50, 149, 149), fill=color)
    return image


def combined_image(size=(300, 150)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((20, 35, 99, 114), fill=(30, 30, 220))
    draw.rectangle((140, 55, 279, 94), fill="black")
    return image


def test_split_text_only_image_has_no_figure():
    result = xs.split_image(text_image(), FakeDetector({(200, 80): "COCO"}).detect(text_image()))
    assert result.auto_type == "문자" and result.dominant == "문자"
    assert result.text_ratio == pytest.approx(0.4, abs=0.01) and result.fig_ratio == 0.0
    assert result.figure is None and result.ocr_text == "COCO" and result.text_boxes == 1


def test_split_figure_only_image_is_tight_crop():
    result = xs.split_image(figure_image(), [])
    assert result.auto_type == "도형" and result.text_ratio == 0.0
    assert result.fig_ratio == pytest.approx(0.25, abs=0.02)
    assert result.figure is not None and 96 <= result.figure.width <= 106
    assert result.ocr_text == ""


def test_split_low_confidence_box_is_not_text():
    fake_box = xs.TextBox((0, 0, 200, 200), "값", 0.02)
    result = xs.split_image(figure_image(), [fake_box])
    assert result.auto_type == "도형" and result.boxes == 1 and result.text_boxes == 0


def test_split_combined_image_keeps_figure_without_text():
    image = combined_image()
    result = xs.split_image(image, FakeDetector({(300, 150): "BLUE"}).detect(image))
    assert result.auto_type == "결합" and result.dominant == "도형"
    assert result.text_ratio == pytest.approx(140 * 40 / 45000, abs=0.01)
    assert 0.12 < result.fig_ratio < 0.17
    arr = np.asarray(result.figure)
    assert not (arr < 30).all(axis=2).any()  # 글자 영역이 지워져 검은 픽셀이 없다
    assert (arr[:, :, 2] > 200).sum() > 1000  # 파란 도형은 남아 있다


@pytest.mark.parametrize(
    ("text_ratio", "fig_ratio", "expected"),
    [(0.01, 0.5, ("도형", "도형")), (0.3, 0.02, ("문자", "문자")), (0.3, 0.2, ("결합", "문자")),
     (0.2, 0.3, ("결합", "도형"))],
)
def test_auto_type(text_ratio, fig_ratio, expected):
    assert xs.auto_type(text_ratio, fig_ratio) == expected


def test_hangul_decomposition_and_spelling_similarity():
    assert xs.decompose_hangul("가") == "가"
    assert len(xs.decompose_hangul("각")) == 3 and xs.decompose_hangul("a1") == "a1"
    assert xs.levenshtein("abc", "abd") == 1 and xs.levenshtein("", "ab") == 2
    assert xs.ortho_similarity("COCO", "coco") == 1.0
    assert xs.ortho_similarity("(주)스타벅스", "스타벅스") == 1.0  # 회사표시 제거(normalize_name)
    partial = xs.ortho_similarity("하라구", "할라고")
    assert partial is not None and 0.3 < partial < 1.0
    assert xs.ortho_similarity("", "coco") is None and xs.ortho_similarity("abc", "xyz") == 0.0


def test_rule_combine_by_type_with_whole_fallback():
    assert xs.rule_combine("문자", 0.9, 0.4, 0.7) == (0.4, "text_ortho")
    assert xs.rule_combine("도형", 0.9, 0.4, 0.7) == (0.9, "fig")
    assert xs.rule_combine("결합", 0.9, 0.4, 0.7) == (0.9, "max")
    assert xs.rule_combine("결합", None, 0.4, 0.7) == (0.4, "max")
    assert xs.rule_combine("문자", 0.9, None, 0.7) == (0.7, "whole")
    assert xs.rule_combine("", 0.9, 0.4, 0.7) == (0.7, "whole")
    assert xs.rule_combine("도형", None, None, None) == (None, "whole")


def test_mark_label_rule():
    assert x2b.mark_label({"라벨": "유사", "판단축": "상품", "메모": ""}) == "유사"
    assert x2b.mark_label({"라벨": "비유사", "판단축": "외관|호칭", "메모": ""}) == "비유사"
    memo = {"라벨": "비유사", "판단축": "상품", "메모": "표장 유사·상품 비유사"}
    assert x2b.mark_label(memo) == "유사"
    assert x2b.mark_label({"라벨": "비유사", "판단축": "상품", "메모": ""}) == ""
    assert x2b.mark_label({"라벨": "비유사", "판단축": "", "메모": ""}) == ""


def test_bootstrap_ci_and_photo_subset():
    labels = np.array([1, 1, 1, 0, 0, 0])
    separated = np.array([0.9, 0.8, 0.7, 0.3, 0.2, 0.1])
    assert x2b.bootstrap_auc(separated, labels, rounds=50) == (1.0, 1.0)
    low, high = x2b.bootstrap_auc(np.array([0.9, 0.2, 0.7, 0.3, 0.8, 0.1]), labels, rounds=200)
    assert low <= 7 / 9 <= high
    assert x2b.bootstrap_auc(np.array([0.5, 0.6]), np.array([1, 1]), rounds=10) == (None, None)
    assert x2b.bootstrap_auc(np.array([0.5, 0.6]), np.array([1, 0]), rounds=0) == (None, None)
    pairs = [
        {"상대role": "target", "상대_사진추정": "1"}, {"상대role": "target", "상대_사진추정": "0"},
        {"상대role": "prior_1", "상대_사진추정": "1"},
    ]
    assert x2b.subset_mask(pairs, "f_사진").tolist() == [True, False, False]


def test_confusion_matrix_uses_this_image_only():
    parts = [
        {"심판번호": "1", "role": "this", "자동유형": "문자", "요부": "문자"},
        {"심판번호": "1", "role": "prior_1", "자동유형": "도형", "요부": "도형"},
        {"심판번호": "2", "role": "this", "자동유형": "결합", "요부": "도형"},
        {"심판번호": "3", "role": "this", "자동유형": "도형", "요부": "도형"},
    ]
    pairs = [
        {"심판번호": "1", "상표유형": "문자"},
        {"심판번호": "1", "상표유형": "문자"},  # 같은 사건 두 행
        {"심판번호": "2", "상표유형": "결합-도형요부"}, {"심판번호": "3", "상표유형": "미상"},
    ]
    result = xs.confusion(parts, pairs)
    assert result["n"] == 2 and result["일치"] == 2 and result["일치율"] == 1.0
    assert result["행_LLM_열_자동"]["문자"]["문자"] == 1
    assert result["결합_요부(행_LLM_열_자동)"]["결합-도형요부"] == {"문자": 0, "도형": 1}


class FakeModel:
    def encode_image(self, batch):
        output = torch.zeros((batch.shape[0], embedding.EMBEDDING_DIM))
        for channel in range(3):
            output[:, channel] = batch[:, channel].mean(dim=(1, 2)) + 0.05
        return output


def fake_preprocess(image):
    values = np.asarray(image, dtype=np.float32).copy() / 255.0
    return torch.from_numpy(values).permute(2, 0, 1)


@pytest.fixture
def trial_base(tmp_path, monkeypatch):
    """심판 3건: 문자 쌍(거절), 도형 쌍(무효), 결합·사진 쌍(권리범위확인)."""
    monkeypatch.setattr(embedding, "_load_model", lambda: (FakeModel(), fake_preprocess))
    base = tmp_path / "trials"
    images = base / "images"
    specs = {
        ("T1", "this"): text_image((200, 80)), ("T1", "prior_1"): text_image((202, 80)),
        ("T2", "this"): figure_image((200, 200)),
        ("T2", "prior_1"): figure_image((200, 202), (200, 40, 40)),
        ("T3", "this"): combined_image((300, 150)),
        ("T3", "target"): figure_image((180, 180), (40, 40, 220)),
    }
    index_rows = []
    for (number, role), image in specs.items():
        path = images / number / f"{role}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        index_rows.append({"심판번호": number, "role": role, "경로": f"images/{number}/{role}.png",
                           "사진추정": "1" if role == "target" else "0", "연결신뢰도": "high"})
    index_columns = ["심판번호", "role", "경로", "사진추정", "연결신뢰도"]
    tei.write_csv(base / "image_index.csv", index_columns, index_rows)

    def pair(number, kind, counterpart, label, axes, mark_type, memo=""):
        return {
            "심판번호": number, "종류": kind, "상대번호": "", "라벨": label, "판단축": axes,
            "상표유형": mark_type, "상표유형_출처": "확정", "이미지A": f"images/{number}/this.png",
            "이미지B": f"images/{number}/{counterpart}.png", "연결신뢰도": "high", "rendered": 0,
            "상대role": counterpart, "매칭": "순번", "메모": memo, "this_사진추정": "0",
            "상대_사진추정": "1" if counterpart == "target" else "0",
        }

    pairs = [
        pair("T1", "거절결정불복", "prior_1", "유사", "호칭", "문자"),
        pair("T2", "무효", "prior_1", "비유사", "외관", "도형"),
        pair("T3", "권리범위확인(적극적)", "target", "비유사", "상품", "결합-도형요부",
             memo="표장 유사·상품 비유사"),
    ]
    tei.write_csv(base / "image_pairs.csv", tei.PAIR_COLUMNS, pairs)
    tei.write_csv(base / "labels.csv", ["심판번호", "상표A_명칭"], [
        {"심판번호": "T1", "상표A_명칭": "COCO"}, {"심판번호": "T2", "상표A_명칭": ""},
        {"심판번호": "T3", "상표A_명칭": "BLUE MARK"},
    ])
    return base


def test_run_split_reuses_cache(trial_base):
    detector = FakeDetector({(200, 80): "COCO", (202, 80): "KOKO", (300, 150): "BLUE"})
    index_rows = tei.read_csv(trial_base / "image_index.csv")
    parts = xs.run_split(trial_base, index_rows, detector)
    assert detector.calls == 6 and len(parts) == 6
    by_key = {(r["심판번호"], r["role"]): r for r in parts}
    assert by_key[("T1", "this")]["자동유형"] == "문자"
    assert by_key[("T1", "this")]["ocr_text"] == "COCO"
    assert by_key[("T2", "this")]["자동유형"] == "도형" and by_key[("T2", "this")]["fig경로"]
    assert by_key[("T3", "this")]["자동유형"] == "결합"
    assert (trial_base / by_key[("T3", "this")]["fig경로"]).exists()
    again = xs.run_split(trial_base, index_rows, detector, previous=parts)
    assert detector.calls == 6 and [r["sha256"] for r in again] == [r["sha256"] for r in parts]
    forced = xs.run_split(trial_base, index_rows, detector, previous=parts, force=True)
    assert detector.calls == 12 and len(forced) == 6


def test_run_end_to_end_with_fake_detector_and_embedder(trial_base):
    detector = FakeDetector({(200, 80): "COCO", (202, 80): "KOKO", (300, 150): "BLUE"})
    report = xs.run(trial_base, detector=detector, shuffles=5, bootstrap=20)

    outputs = ("image_parts.csv", "image_pairs_v1.csv", "x2_split_qa.png", "x2_benchmark_v1.json")
    for name in outputs:
        assert (trial_base / name).exists(), name
    rows = tei.read_csv(trial_base / "image_pairs_v1.csv")
    by_trial = {r["심판번호"]: r for r in rows}
    assert by_trial["T1"]["표장라벨"] == "유사"
    assert by_trial["T2"]["표장라벨"] == "비유사"
    assert by_trial["T3"]["표장라벨"] == "유사"  # 메모 '표장 유사' → 유사
    assert by_trial["T1"]["x2_text_ortho"] and by_trial["T1"]["x2_fig"] == ""  # 문자 쌍: 크롭 없음
    assert by_trial["T2"]["x2_fig"] and by_trial["T2"]["x2_text_ortho"] == ""  # 도형 쌍: OCR 없음
    assert by_trial["T1"]["x2_rule_auto_src"] == "text_ortho"
    assert by_trial["T2"]["x2_rule_auto_src"] == "fig"
    assert by_trial["T3"]["x2_rule_llm_src"] in ("max", "whole")
    assert all(r["x2_whole"] for r in rows)

    assert report["표장라벨"] == {"유사": 2, "비유사": 1, "제외": 0}
    assert report["유형_혼동행렬"]["n"] == 3 and report["유형_혼동행렬"]["일치"] == 3
    assert report["OCR_품질(this_vs_상표A_명칭)"]["n"] == 2
    assert set(report["평가"]["표장라벨"]) == set(x2b.FEATURES)
    whole = report["평가"]["표장라벨"]["x2_whole"]["a_전체"]
    assert whole["n"] == 3 and "auc_ci95" in whole
    assert report["평가"]["v0라벨"]["x2_whole"]["a_전체"]["n_유사"] == 1
    saved = json.loads((trial_base / "x2_benchmark_v1.json").read_text(encoding="utf-8"))
    assert saved["min_size"] == 32
    assert all((trial_base / f"x2_hist_v1_{f}.png").exists() for f in x2b.FEATURES)
    assert "### 표장라벨" in x2b.feature_table(report["평가"])
    assert "| 문자 |" in xs.confusion_table(report["유형_혼동행렬"])
