"""X2 외관 벤치마크 테스트 — 지표 계산(합성 점수)과 가짜 임베더로 끝까지 도는 파이프라인·캐시."""

from __future__ import annotations

import json

import numpy as np
import pytest
import torch
from PIL import Image, ImageDraw
from src import embedding

from scripts import trials_extract_images as tei
from scripts import x2_benchmark as x2b


class FakeModel:
    """채널 평균을 임베딩 앞 세 칸에 넣는다(ml/tests/test_embedding.py 와 같은 꼴)."""

    def encode_image(self, batch):
        output = torch.zeros((batch.shape[0], embedding.EMBEDDING_DIM))
        for channel in range(3):
            output[:, channel] = batch[:, channel].mean(dim=(1, 2)) + 0.05
        return output


def fake_preprocess(image):
    values = np.asarray(image, dtype=np.float32).copy() / 255.0
    return torch.from_numpy(values).permute(2, 0, 1)


@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    monkeypatch.setattr(embedding, "_load_model", lambda: (FakeModel(), fake_preprocess))


def _mark(path, color):
    image = Image.new("RGB", (64, 64), color)
    ImageDraw.Draw(image).rectangle((16, 16, 48, 48), fill=(255, 255, 255))
    image.save(path)


@pytest.fixture
def pairs_csv(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    colors = {
        "a1": (220, 20, 20), "b1": (200, 40, 40),  # 유사(빨강끼리)
        "a2": (20, 20, 220), "b2": (40, 40, 200),  # 유사(파랑끼리)
        "a3": (210, 30, 30), "b3": (20, 220, 20),  # 비유사 (a1 과 다른 파일이어야 캐시 키가 8개)
        "a4": (30, 30, 210), "b4": (220, 220, 20),  # 비유사
    }
    for name, color in colors.items():
        _mark(images / f"{name}.png", color)
    rows = [
        {"심판번호": "1", "종류": "무효", "라벨": "유사", "판단축": "외관|호칭", "상표유형": "도형",
         "이미지A": "images/a1.png", "이미지B": "images/b1.png", "연결신뢰도": "high"},
        {"심판번호": "2", "종류": "거절결정불복", "라벨": "유사", "판단축": "호칭",
         "상표유형": "문자", "이미지A": "images/a2.png", "이미지B": "images/b2.png",
         "연결신뢰도": "low"},
        {"심판번호": "3", "종류": "권리범위확인(적극적)", "라벨": "비유사", "판단축": "외관",
         "상표유형": "결합-도형요부", "이미지A": "images/a3.png", "이미지B": "images/b3.png",
         "연결신뢰도": "high"},
        {"심판번호": "4", "종류": "무효", "라벨": "비유사", "판단축": "관념", "상표유형": "문자",
         "이미지A": "images/a4.png", "이미지B": "images/b4.png", "연결신뢰도": "high"},
    ]
    for row in rows:
        row.update({"상대번호": "", "상표유형_출처": "확정", "rendered": 0, "상대role": "prior_1",
                    "매칭": "번호"})
    path = tmp_path / "image_pairs.csv"
    tei.write_csv(path, tei.PAIR_COLUMNS, rows)
    return path


def test_roc_auc_perfect_reversed_and_ties():
    labels = np.array([1, 1, 0, 0])
    assert x2b.roc_auc(np.array([0.9, 0.8, 0.2, 0.1]), labels) == 1.0
    assert x2b.roc_auc(np.array([0.1, 0.2, 0.8, 0.9]), labels) == 0.0
    assert x2b.roc_auc(np.array([0.5, 0.5, 0.5, 0.5]), labels) == 0.5
    assert x2b.roc_auc(np.array([0.5, 0.6]), np.array([1, 1])) is None


def test_best_threshold_and_separation():
    scores = np.array([0.9, 0.7, 0.3, 0.1])
    labels = np.array([1, 1, 0, 0])
    threshold, accuracy = x2b.best_threshold(scores, labels)
    assert accuracy == 1.0 and 0.3 < threshold < 0.7
    assert x2b.separation(scores[:2], scores[2:]) == pytest.approx(0.75 - 0.25, abs=1e-6)
    assert x2b.separation(np.array([]), scores) is None
    assert x2b.best_threshold(np.array([]), np.array([])) == (None, None)


def test_distribution_and_shuffled_baseline():
    stats = x2b.distribution(np.array([0.1, 0.2, 0.3, 0.4]))
    assert stats["n"] == 4 and stats["median"] == 0.25 and stats["q1"] == 0.175
    assert x2b.distribution(np.array([])) == {"n": 0}
    rng = np.random.default_rng(0)
    scores = rng.random(60)
    labels = np.array([1] * 30 + [0] * 30)
    baseline = x2b.shuffled_auc(scores, labels, seed=0, rounds=100)
    assert 0.4 < baseline["mean"] < 0.6 and baseline["p5"] < baseline["p95"]


def test_subset_masks(pairs_csv):
    pairs = x2b.load_pairs(pairs_csv)
    assert x2b.subset_mask(pairs, "a_전체").sum() == 4
    assert x2b.subset_mask(pairs, "b_외관축").tolist() == [True, False, True, False]
    assert x2b.subset_mask(pairs, "c_도형").tolist() == [True, False, True, False]
    assert x2b.subset_mask(pairs, "d_문자").tolist() == [False, True, False, True]
    assert x2b.subset_mask(pairs, "e_신뢰high").tolist() == [True, False, True, True]
    with pytest.raises(ValueError):
        x2b.subset_mask(pairs, "없는 키")


def test_run_end_to_end_with_fake_embedder_and_cache(pairs_csv, tmp_path):
    cache = tmp_path / "cache.npz"
    out = tmp_path / "report.json"
    hist = tmp_path / "hist.png"
    calls = []

    def counting_encode(path):
        calls.append(path)
        return embedding.encode_image(path)

    report = x2b.run(pairs_csv, cache_path=cache, out_path=out, hist_path=hist, seed=0,
                     shuffles=20, encode=counting_encode)
    assert len(calls) == 8 and cache.exists() and out.exists() and hist.exists()
    assert report["쌍"] == 4 and report["점수_있는_쌍"] == 4 and report["임베딩_실패"] == {}
    whole = report["부분집합"]["a_전체"]
    assert whole["n"] == 4 and whole["n_유사"] == 2 and whole["n_비유사"] == 2
    assert whole["auc"] == 1.0  # 같은 색끼리가 더 가깝다
    assert whole["유사_분포"]["min"] > whole["비유사_분포"]["max"]
    assert report["부분집합"]["c_도형"]["n"] == 2
    assert json.loads(out.read_text(encoding="utf-8"))["계약"]["model"] == "ViT-B-32"
    assert "| 전체 |" in x2b.markdown_table(report["부분집합"])

    calls.clear()
    second = x2b.run(pairs_csv, cache_path=cache, out_path=out, hist_path=None, seed=0,
                     shuffles=20, encode=counting_encode)
    assert calls == [] and second["부분집합"]["a_전체"]["auc"] == 1.0  # 캐시 재사용


def test_cache_is_dropped_when_contract_changes(pairs_csv, tmp_path, monkeypatch):
    cache = tmp_path / "cache.npz"
    x2b.run(pairs_csv, cache_path=cache, out_path=tmp_path / "r.json", hist_path=None,
            shuffles=5)
    assert len(x2b.load_cache(cache)) == 8
    monkeypatch.setattr(x2b, "_contract", lambda: {"model": "other"})
    assert x2b.load_cache(cache) == {}


def test_embed_paths_records_failures(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    result = x2b.embed_paths([bad], tmp_path / "cache.npz")
    assert str(bad) in result[x2b.FAILURES_KEY] and str(bad) not in result


def test_evaluate_features_uses_mark_label_and_reports_exclusions(pairs_csv):
    pairs = x2b.load_pairs(pairs_csv)
    for pair, whole, fig in zip(pairs, (0.9, 0.8, 0.3, 0.2), ("0.95", "", "0.4", "0.1")):
        pair["x2_whole"] = f"{whole:.4f}"
        pair["x2_fig"] = fig
    pairs[3]["판단축"] = "상품"  # 비유사인데 상품 축뿐 → 표장 라벨 제외
    pairs[3]["_mark"] = None
    result = x2b.evaluate_features(pairs, ["x2_whole", "x2_fig"], shuffles=5, bootstrap=20)
    assert result["표장라벨_제외"] == 1 and result["표장라벨_유사"] == 2
    assert result["표장라벨_비유사"] == 1
    whole = result["표장라벨"]["x2_whole"]["a_전체"]
    assert whole["n"] == 3 and whole["auc"] == 1.0 and whole["auc_ci95"] == [1.0, 1.0]
    assert result["v0라벨"]["x2_whole"]["a_전체"]["n"] == 4
    assert result["표장라벨"]["x2_fig"]["a_전체"]["n"] == 2  # 결측 1 + 제외 1
    table = x2b.feature_table(result)
    assert "### 표장라벨" in table and "x2_fig" in table and "### v0라벨" in table


def test_rank_auc_matches_pairwise_definition():
    rng = np.random.default_rng(1)
    scores = np.round(rng.random(40), 1)  # 동점이 생기도록
    labels = rng.integers(0, 2, 40)
    positive, negative = scores[labels == 1], scores[labels == 0]
    greater = (positive[:, None] > negative[None, :]).sum()
    equal = (positive[:, None] == negative[None, :]).sum()
    pairwise = (greater + 0.5 * equal) / (positive.size * negative.size)
    assert x2b.roc_auc(scores, labels) == pytest.approx(float(pairwise))
