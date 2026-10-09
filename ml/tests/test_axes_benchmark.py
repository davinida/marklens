"""축별 벤치마크 테스트 — 합성 특징 CSV(실제 모델·네트워크 없음)로 부분집합·AUC·상관·임계값·게이트
효과."""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest

from scripts import axes_benchmark as ab
from scripts import pairs_features as pf

KINDS = ("거절결정불복", "무효", "권리범위확인(적극적)", "권리범위확인(소극적)")


def _rows(n: int = 48) -> list[dict]:
    """x1 은 표장 라벨을 완전히 가르고(게이트 꺼진 행은 0.0), x2_text 는 x1 과 같은 값(상관 1),
    x3 는 라벨과 반대(유사 0.1·비유사 0.9), x4 는 최종 라벨과 무관한 상수. 일부 행은 게이트 꺼짐·
    표장 라벨 제외·이름 없음·이미지 없음."""
    rows = []
    for i in range(n):
        similar = i % 2 == 0
        row = {column: "" for column in pf.COLUMNS}
        row.update({
            "심판번호": f"T{i}", "종류": KINDS[i % 4], "최종라벨": "유사" if similar else "비유사",
            "표장라벨": ("유사" if similar else "비유사") if i % 8 != 7 else "",
            "판단축": "호칭|관념" if i % 3 else "외관|상품", "이름A": "a", "이름B": "b",
            "이름B_출처": ("kipris", "본문", "ocr")[i % 3],
            "x1": f"{0.6 + i / (2 * n):.4f}" if similar else f"{i / (4 * n):.4f}",
            "x3": "0.1000" if similar else "0.9000", "x3_raw": "0.1000" if similar else "0.9000",
            "x4": "0.5000",
            "x2_whole": f"{0.5:.4f}" if i % 2 == 0 or i % 5 == 0 else "",
            "has_names": 1, "has_pron_a": 1, "has_pron_b": 1 if i % 6 else 0,
            "has_meaning_a": 1 if i % 5 else 0, "has_meaning_b": 1,
            "has_spelling_a": 1, "has_spelling_b": 1, "has_goods": 1,
            "has_image": 1 if row.get("x2_whole") else 0, "has_fig": 0,
        })
        row["has_image"] = 1 if row["x2_whole"] else 0
        if i % 6 == 0:  # 발음 후보 없음 → 함수는 0.0
            row["x1"] = "0.0000"
        row["x2_text"] = row["x1"]
        rows.append(row)
    rows[-1].update({"이름A": "", "이름B": "", "has_names": 0, "x1": "", "x2_text": "", "x3": "",
                     "x3_raw": ""})
    return rows


@pytest.fixture
def features_csv(tmp_path):
    path = tmp_path / "pairs_features.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=pf.COLUMNS)
        writer.writeheader()
        writer.writerows(_rows())
    return path


def test_load_features_parses_numbers_and_flags(features_csv):
    rows = ab.load_features(features_csv)
    assert len(rows) == 48 and np.isnan(rows[-1]["x1"]) and rows[-1]["has_names"] == 0
    assert rows[0]["x1"] == 0.0 and rows[0]["has_pron_b"] == 0 and rows[2]["x1"] > 0.6


def test_subsets_and_auc(features_csv, tmp_path):
    result = ab.run(features_csv, out_path=tmp_path / "out.json", hist_dir=tmp_path, bootstrap=30)
    x1 = result["축"]["x1"]["부분집합"]
    rows = ab.load_features(features_csv)
    mark = ab.labels_for(rows, "표장")
    scores = ab.scores_for(rows, "x1")
    valid = ~np.isnan(scores) & (mark >= 0)
    assert x1["a_전체"]["n"] == int(valid.sum()) and x1["a_전체"]["n"] < 48
    # x1 은 게이트 꺼진 0.0(비유사면 맞고 유사면 틀림)이 섞여 (a) < 1.0, (c) 는 완전 분리
    assert x1["c_게이트"]["auc"] == 1.0 and x1["a_전체"]["auc"] < 1.0
    gate_on = ab.gate_mask(rows, ("has_pron_a", "has_pron_b"))
    assert x1["c_게이트"]["n"] == int((valid & gate_on).sum())
    by_axis = np.asarray(["호칭" in r["판단축"] for r in rows])
    assert x1["b_판단축"]["n"] == int((valid & by_axis).sum())
    assert x1["c_게이트"]["auc_ci95"] == [1.0, 1.0]
    assert set(k for k in x1 if k.startswith("d_")) == {"d_kipris", "d_본문", "d_ocr"}
    assert set(k for k in x1 if k.startswith("e_")) == {f"e_{kind}" for kind in KINDS}
    assert "d_kipris" not in result["축"]["x4"]["부분집합"]  # 이름 축이 아니면 (d) 없음
    # x3 는 라벨과 반대라 (c) AUC 0, x4 는 상수라 0.5, x2_fig 는 전부 결측
    assert result["축"]["x3"]["부분집합"]["c_게이트"]["auc"] == 0.0
    assert result["축"]["x4"]["부분집합"]["a_전체"]["auc"] == 0.5
    assert result["축"]["x2_fig"]["부분집합"]["a_전체"]["auc"] is None
    assert result["축"]["x2_fig"]["결측"] == 48
    assert result["축"]["x4"]["라벨"] == "최종"
    assert result["축"]["x4"]["부분집합"]["a_전체"]["n"] == 48
    for column in ("x1", "x2_text", "x3", "x4", "x2_whole", "x2_fig"):
        assert (tmp_path / f"axes_hist_v1_{column}.png").exists()
    saved = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert saved["대상_행"] == 48 and saved["표장라벨"]["제외"] == 6


def test_spearman_and_correlation_matrix(features_csv):
    rows = ab.load_features(features_csv)
    x1, x2, x3 = (ab.scores_for(rows, c) for c in ("x1", "x2_text", "x3"))
    assert ab.spearman(x1, x2) == (1.0, 47)
    assert ab.spearman(np.arange(10.0), -np.arange(10.0)) == (-1.0, 10)
    assert ab.spearman(np.array([1.0, np.nan]), np.array([1.0, 2.0])) == (None, 1)
    assert ab.spearman(np.ones(5), np.arange(5.0)) == (None, 5)
    matrix = ab.correlation_matrix(rows)
    assert matrix["rho"]["x1"]["x2_text"] == 1.0 and matrix["n"]["x1"]["x2_text"] == 47
    assert matrix["rho"]["x2_fig"]["x1"] is None and matrix["n"]["x2_fig"]["x1"] == 0
    assert matrix["rho"]["x3"]["x1"] < 0


def test_precision_threshold():
    scores = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 0.95, 0.85])
    labels = np.array([0, 0, 0, 0, 1, 0, 1, 1, 1, 1, 1, 1])
    # 지지 10 이상이면서 정밀도 ≥ 0.9 인 최소 t 는 없다(0.3 이상 10개 중 유사 7 = 0.7)
    none = ab.precision_threshold(scores, labels)
    assert none["threshold"] is None and none["n_유사"] == 7
    assert none["최대_정밀도"] == {"threshold": 0.3, "precision": 0.7, "recall": 1.0, "n_above": 10}
    found = ab.precision_threshold(scores, labels, min_support=5)
    assert found["threshold"] == 0.7 and found["precision"] == 1.0
    assert found["recall"] == pytest.approx(6 / 7, abs=1e-4) and found["n_above"] == 6
    assert found["최대_정밀도"]["threshold"] == 0.7  # 동률(1.0)이면 낮은 t
    empty = ab.precision_threshold(np.array([]), np.array([]))
    assert empty["threshold"] is None and empty["n"] == 0


def test_gate_effect_counts(features_csv):
    rows = ab.load_features(features_csv)
    gate = ab.gate_effect(rows, seed=0, bootstrap=20)
    off = gate["x3_raw_게이트꺼짐"]
    assert off["n"] == sum(1 for r in rows if r["has_names"] and not r["has_meaning_a"]
                           and r["표장라벨"]) and off["auc"] is not None
    pron_off = sum(1 for r in rows if r["has_names"] and not r["has_pron_b"])
    assert gate["x1_게이트꺼짐"]["n"] == pron_off
    assert gate["x1_게이트꺼짐"]["x1_분포"]["max"] == 0.0
    assert gate["이름_없음"] == 1 and gate["x2_text_게이트꺼짐"]["n"] == 0


def test_report_text_lists_axes(features_csv, tmp_path):
    result = ab.run(features_csv, out_path=tmp_path / "out.json", hist_dir=None, bootstrap=10)
    text = ab.report_text(result)
    for column in ("x1", "x2_text", "x2_fig", "x2_whole", "x3", "x4"):
        assert f"({column})" in text
    assert "스피어만" in text and "단독 임계값" in text and "게이트 효과" in text
    assert result["히스토그램"] == {}


def _with_distinctiveness(rows: list[dict]) -> list[dict]:
    """x1_d: 유사 쌍은 그대로, 비유사 쌍 중 x1 = 1.0 은 0.2 로 내려간 것처럼."""
    for row in rows:
        for axis in ("x1", "x2_text", "x3"):
            value = row[axis]
            if value and row["최종라벨"] == "비유사" and float(value) >= 0.9:
                value = "0.2000"
            row[f"{axis}_d"] = value
        row["has_distinctive_part_a"] = 1
        row["has_distinctive_part_b"] = 1
        row["weak_a"] = row["weak_b"] = ""
        row["pair_source"] = "trial"
    return rows


def _easy_rows(n: int = 20) -> list[dict]:
    rows = []
    for i in range(n):
        row = {column: "" for column in pf.COLUMNS}
        row.update({
            "심판번호": f"cross:{i}", "최종라벨": "비유사", "표장라벨": "비유사", "이름A": "a",
            "이름B": "b", "pair_source": "cross" if i % 2 == 0 else "db",
            "x1": f"{0.05 + i / (4 * n):.4f}", "x1_d": f"{0.05 + i / (4 * n):.4f}",
            "x2_text": "0.1000", "x2_text_d": "0.1000", "x3": "0.0000", "x3_d": "0.0000",
            "x4": "0.0000" if i % 3 else "", "has_names": 1, "has_pron_a": 1, "has_pron_b": 1,
            "has_meaning_a": 0, "has_meaning_b": 0, "has_spelling_a": 1, "has_spelling_b": 1,
            "has_goods": 1 if i % 3 else 0,
        })
        rows.append(row)
    return rows


@pytest.fixture
def features_with_d(tmp_path):
    rows = _with_distinctiveness(_rows())
    # 비유사 쌍 둘에 x1 = 1.0 을 심어 "점수 1.0 쌍" 전후를 만든다
    rows[1]["x1"] = rows[3]["x1"] = "1.0000"
    rows[1]["x1_d"] = rows[3]["x1_d"] = "0.2000"
    path = tmp_path / "pairs_features.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=pf.COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    easy = tmp_path / "pairs_features_easy.csv"
    with easy.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=pf.COLUMNS)
        writer.writeheader()
        writer.writerows(_easy_rows())
    return path, easy


def test_distinctiveness_effect_and_realistic_distribution(features_with_d, tmp_path):
    path, easy = features_with_d
    result = ab.run(path, out_path=tmp_path / "out.json", hist_dir=None, bootstrap=20,
                    easy_path=easy)
    effect = result["식별력_전후"]["x1"]
    assert effect["부분집합"]["a_전체"]["전"] < effect["부분집합"]["a_전체"]["후"]
    ones = effect["점수_1.0_쌍"]
    assert ones["전"]["비유사"] == 2 and ones["후_그대로_1.0"]["비유사"] == 0
    assert effect["내려간_쌍"]["유사"]["n"] == 0 and effect["내려간_쌍"]["비유사"]["n"] >= 2
    assert set(result["식별력_전후"]) == {"x1", "x2_text", "x3"}
    assert "x1_d" in result["축"] and result["축"]["x1_d"]["부분집합"]["b_판단축"]["n"] > 0
    real = result["현실_분포"]
    assert real["쉬운_음성"] == {"cross": 10, "db": 10}
    x1 = real["축"]["x1"]
    base = result["축"]["x1"]["부분집합"]["a_전체"]["n"]
    assert x1["심결"]["n"] == base and x1["심결+cross"]["n"] == base + 10
    assert x1["심결+cross+db"]["n"] == base + 20
    assert x1["심결+cross+db"]["n_비유사"] > x1["심결"]["n_비유사"]
    assert x1["심결+cross+db"]["auc"] > x1["심결"]["auc"]  # 쉬운 음성은 점수가 낮아 AUC 가 오른다
    x4_base = result["축"]["x4"]["부분집합"]["a_전체"]["n"]
    assert real["축"]["x4"]["심결+cross+db"]["n"] == x4_base + 13
    text = ab.report_text(result)
    assert "식별력 v0 전후" in text and "현실 분포" in text and "| x1 |" in text
    no_easy = ab.run(path, out_path=tmp_path / "out2.json", hist_dir=None, bootstrap=10)
    assert "현실_분포" not in no_easy and "쉬운 음성 없음" in ab.report_text(no_easy)
