"""X2 v1 ② 변형·OCR 진단·게이팅 테스트 — 가짜 CLIP 임베더·가짜 DINO·가짜 검출기(다운로드 없음)."""

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
from scripts import x2_variants as xv


class FakeModel:
    def encode_image(self, batch):
        output = torch.zeros((batch.shape[0], embedding.EMBEDDING_DIM))
        for channel in range(3):
            output[:, channel] = batch[:, channel].mean(dim=(1, 2)) + 0.05
        return output


def fake_preprocess(image):
    values = np.asarray(image, dtype=np.float32).copy() / 255.0
    return torch.from_numpy(values).permute(2, 0, 1)


def fake_dino(image: Image.Image) -> np.ndarray:
    arr = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    vector = np.zeros(384, dtype=np.float32)
    vector[:3] = arr.mean(axis=(0, 1)) + 0.05
    return xv.l2_normalize(vector)


class FakeDetector:
    def __init__(self, texts: dict[tuple[int, int], str]) -> None:
        self.texts = texts

    def detect(self, image: Image.Image) -> list[xs.TextBox]:
        arr = np.asarray(image.convert("RGB"))
        black = (arr < 30).all(axis=2)
        if not black.any():
            return []
        ys, xs_ = np.nonzero(black)
        bbox = (int(xs_.min()), int(ys.min()), int(xs_.max()) + 1, int(ys.max()) + 1)
        return [xs.TextBox(bbox, self.texts.get(image.size, "TEXT"), 0.9)]


def figure_image(size=(200, 200), color=(220, 30, 30)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).ellipse((50, 50, 149, 149), fill=color)
    return image


def text_image(size=(200, 80)) -> Image.Image:
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).rectangle((20, 20, 179, 59), fill="black")
    return image


def test_input_transforms():
    gray = np.asarray(xv.to_gray(figure_image()))
    assert gray.shape[2] == 3 and (gray[:, :, 0] == gray[:, :, 1]).all()
    edge = np.asarray(xv.to_edge(figure_image()).convert("L"))
    assert set(np.unique(edge).tolist()) <= {0, 255}
    assert (edge == 255).mean() > 0.9 and (edge == 0).sum() > 100  # 흰 바탕, 원 둘레만 검다
    views = xv.multires_views(figure_image((120, 80)))
    assert len(views) == 3 and all(view.size == (120, 80) for view in views)


def test_embed_multires_is_unit_norm():
    calls = []

    def encode(image):
        calls.append(image.size)
        rng = np.random.default_rng(len(calls))
        return rng.random(512).astype(np.float32)

    vector = xv.embed_multires(figure_image(), encode=encode)
    assert vector.shape == (512,) and np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-5)
    assert len(calls) == 3
    with pytest.raises(ValueError):
        xv.l2_normalize(np.zeros(4))


def test_cosine_scores_match_faiss_path(tmp_path):
    rng = np.random.default_rng(0)
    vectors = {name: xv.l2_normalize(rng.random(512)) for name in ("a", "b", "c")}
    embeddings = {str(tmp_path / f"{name}.png"): vec for name, vec in vectors.items()}
    pairs = [{"이미지A": "a.png", "이미지B": "b.png"}, {"이미지A": "a.png", "이미지B": "c.png"},
             {"이미지A": "a.png", "이미지B": "missing.png"}]
    dot = xv.cosine_scores(pairs, embeddings, tmp_path)
    faiss = x2b.pair_scores(pairs, embeddings, tmp_path)
    assert np.allclose(dot[:2], faiss[:2], atol=1e-5) and np.isnan(dot[2]) and np.isnan(faiss[2])


def test_zscore_and_ensemble():
    z = xv.zscore(np.array([1.0, 2.0, 3.0, np.nan]))
    assert z[1] == 0.0 and z[0] == pytest.approx(-1.2247, abs=1e-3) and np.isnan(z[3])
    assert (xv.zscore(np.array([2.0, 2.0])) == 0.0).all()
    combined = xv.ensemble_scores(np.array([0.9, 0.5, 0.1, 0.4]), np.array([0.8, 0.6, np.nan, 0.2]))
    assert np.isnan(combined[2]) and combined[0] > combined[1] > combined[3]


def _result(auc_a, auc_b, ci_b):
    return {"a_전체": {"auc": auc_a, "auc_ci95": [None, None], "n": 10},
            "b_외관축": {"auc": auc_b, "auc_ci95": list(ci_b), "n": 10}}


def test_adoption_rule():
    results = {
        "whole": _result(0.50, 0.60, (0.50, 0.70)),
        "x": _result(0.52, 0.70, (0.62, 0.78)),  # +0.10, (a) 유지, CI 겹침 → 잠정 후보
        "y": _result(0.50, 0.72, (0.71, 0.80)),  # +0.12, CI 분리 → 채택
        "z": _result(0.45, 0.70, (0.60, 0.80)),  # (a) 하락 → 없음
        "w": _result(0.55, 0.63, (0.55, 0.71)),  # +0.03 → 없음
    }
    adopt = xv.adoption(results)
    verdicts = {k: v["판정"] for k, v in adopt["변형"].items()}
    assert verdicts == {"x": "잠정 후보", "y": "채택", "z": "채택 없음", "w": "채택 없음"}
    assert adopt["채택안"] == "y" and "하락" in adopt["변형"]["z"]["이유"]
    assert xv.adoption({"whole": _result(0.5, 0.6, (0.5, 0.7))})["채택안"] is None


def test_half_ortho_exclusions():
    names = {"1": "COCO", "2": "", "3": "도형", "4": "ABC", "5": " "}
    pairs = [
        {"심판번호": "1", "상대_ocr": "coco"}, {"심판번호": "2", "상대_ocr": "x"},
        {"심판번호": "3", "상대_ocr": "x"}, {"심판번호": "4", "상대_ocr": ""},
        {"심판번호": "5", "상대_ocr": "x"},
    ]
    scores, excluded = xv.half_ortho_scores(pairs, names)
    assert scores[0] == 1.0 and np.isnan(scores[1:]).all()
    assert excluded == {"명칭 없음": 2, "명칭 도형": 1, "상대 OCR 없음": 1}


def test_gate_type_and_scores():
    parts = {("T", "this"): {"요부": "도형"}}
    assert xv.gate_type({"상표유형_출처": "확정", "상표유형": "문자"}, parts) == "text"
    assert xv.gate_type({"상표유형_출처": "확정", "상표유형": "결합-도형요부"}, parts) == "figure"
    estimated = {"상표유형_출처": "추정", "상표유형": "결합", "this_자동유형": "결합",
                 "심판번호": "T"}
    assert xv.gate_type(estimated, parts) == "figure"
    assert xv.gate_type({"상표유형_출처": "", "this_자동유형": "문자"}, parts) == "text"
    assert xv.gate_type({"상표유형_출처": "", "this_자동유형": ""}, parts) == ""
    pairs = [
        {"심판번호": "A", "상표유형_출처": "확정", "상표유형": "문자"},
        {"심판번호": "B", "상표유형_출처": "확정", "상표유형": "도형"},
        {"심판번호": "C", "상표유형_출처": "확정", "상표유형": "문자"},
    ]
    half = np.array([0.9, np.nan, np.nan], dtype=np.float32)
    figure = np.array([0.1, 0.8, 0.3], dtype=np.float32)
    whole = np.array([0.5, 0.5, 0.5], dtype=np.float32)
    scores, sources = xv.gate_scores(pairs, {}, half, figure, whole)
    assert scores.tolist() == pytest.approx([0.9, 0.8, 0.5], abs=1e-6)
    assert sources == ["text_half", "figure", "whole"]


@pytest.fixture
def variant_base(tmp_path, monkeypatch):
    """① 파이프라인(가짜 검출기·임베더)으로 image_pairs_v1.csv·image_parts.csv 를 만든 디렉터리."""
    monkeypatch.setattr(embedding, "_load_model", lambda: (FakeModel(), fake_preprocess))
    base = tmp_path / "trials"
    images = base / "images"
    specs = {
        ("T1", "this"): text_image((200, 80)), ("T1", "prior_1"): text_image((202, 80)),
        ("T2", "this"): figure_image((200, 200)),
        ("T2", "prior_1"): figure_image((200, 202), (200, 40, 40)),
        ("T3", "this"): figure_image((180, 180), (30, 30, 220)),
        ("T3", "target"): figure_image((180, 182), (40, 40, 200)),
    }
    index_rows = []
    for (number, role), image in specs.items():
        path = images / number / f"{role}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        index_rows.append({"심판번호": number, "role": role, "경로": f"images/{number}/{role}.png",
                           "사진추정": "1" if role == "target" else "0", "연결신뢰도": "high"})
    tei.write_csv(base / "image_index.csv", ["심판번호", "role", "경로", "사진추정", "연결신뢰도"],
                  index_rows)

    def pair(number, kind, counterpart, label, axes, mark_type, source="확정"):
        return {
            "심판번호": number, "종류": kind, "상대번호": "", "라벨": label, "판단축": axes,
            "상표유형": mark_type, "상표유형_출처": source, "이미지A": f"images/{number}/this.png",
            "이미지B": f"images/{number}/{counterpart}.png", "연결신뢰도": "high", "rendered": 0,
            "상대role": counterpart, "매칭": "순번", "메모": "", "this_사진추정": "0",
            "상대_사진추정": "1" if counterpart == "target" else "0",
        }

    pairs = [
        pair("T1", "거절결정불복", "prior_1", "유사", "호칭|외관", "문자"),
        pair("T2", "무효", "prior_1", "비유사", "외관", "도형"),
        pair("T3", "권리범위확인(적극적)", "target", "유사", "외관", "결합", source="추정"),
    ]
    tei.write_csv(base / "image_pairs.csv", tei.PAIR_COLUMNS, pairs)
    tei.write_csv(base / "labels.csv", ["심판번호", "상표A_명칭"], [
        {"심판번호": "T1", "상표A_명칭": "COCO"}, {"심판번호": "T2", "상표A_명칭": "도형"},
        {"심판번호": "T3", "상표A_명칭": ""},
    ])
    detector = FakeDetector({(200, 80): "COCO", (202, 80): "KOKO"})
    xs.run(base, detector=detector, shuffles=5, bootstrap=10)
    return base


def test_run_end_to_end_with_fake_embedders(variant_base):
    report = xv.run(variant_base, dino=fake_dino, shuffles=5, bootstrap=20)

    assert set(report["변형"]) == set(xv.VARIANTS)
    for variant in ("whole", "gray", "edge", "multires", "dino"):
        assert report["변형"][variant]["ms_per_image"] is not None
        assert report["변형"][variant]["임베딩_실패"] == 0
    assert report["변형"]["whole"]["평가"]["a_전체"]["n"] == 3
    assert report["채택"]["기준"] == "whole"
    assert set(report["채택"]["변형"]) == set(xv.VARIANTS) - {"whole"}
    assert report["OCR_진단"]["제외"] == {"명칭 없음": 1, "명칭 도형": 1, "상대 OCR 없음": 0}
    assert report["OCR_진단"]["half_값_있음"] == 1 and "b_외관축" in report["OCR_진단"]
    assert set(report["게이팅"]["평가"]) == {"x2_whole", "x2_rule_llm", "x2_gate"}
    sources = report["게이팅"]["소스"]
    assert sources["text_half"] == 1 and sources.get("figure", 0) >= 1

    rows = tei.read_csv(variant_base / "image_pairs_v1_variants.csv")
    assert [r["x2_gate_src"] for r in rows] == ["text_half", "figure", "figure"]
    assert all(r["x2_gray"] and r["x2_edge"] and r["x2_multires"] and r["x2_dino"] for r in rows)
    assert rows[0]["x2_text_ortho_half"] and rows[1]["x2_text_ortho_half"] == ""
    saved = json.loads((variant_base / "x2_variants_v1.json").read_text(encoding="utf-8"))
    assert saved["dino"]["skipped"] is False
    results = {v: item["평가"] for v, item in report["변형"].items()}
    ms = {v: item["ms_per_image"] for v, item in report["변형"].items()}
    table = xv.variants_table(results, ms, report["채택"])
    assert "whole(기준)" in table and "DINOv2" in table
    assert "half(this 참값)" in xv.diagnosis_table(report["OCR_진단"])
    assert "x2_gate" in xv.gating_table(report["게이팅"]["평가"])

    again = xv.run(variant_base, dino=fake_dino, skip_dino=True, shuffles=5, bootstrap=5)
    assert "dino" not in again["변형"] and "ensemble" not in again["변형"]
    assert (variant_base / "x2_cache_v1_edge.npz").exists()
