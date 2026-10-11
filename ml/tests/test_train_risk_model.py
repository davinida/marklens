"""통합 모델 학습 스크립트 테스트 — 합성 특징 CSV 로 끝까지(모델 다운로드·실데이터 없음)."""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest
from src.model import risk_model as rm

from scripts import pairs_features as pf
from scripts import train_risk_model as tr

KINDS = ("거절결정불복", "무효", "권리범위확인(적극적)", "권리범위확인(소극적)")
TYPES = ("문자", "도형", "결합-문자요부", "결합-도형요부", "미상")
EASY_COLUMNS = [c for c in pf.COLUMNS if c not in ("weak_a", "weak_b")]


def _trial_rows(n: int = 120, seed: int = 0) -> list[dict]:
    """x1·x2_text 가 라벨과 함께 움직이고 x4 도 약하게 움직이는 합성 행(일부 결측·게이트 꺼짐)."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        similar = i % 5 != 0 and i % 3 != 1
        base = 0.65 if similar else 0.3
        row = {column: "" for column in pf.COLUMNS}
        x1 = float(np.clip(base + rng.normal(0, 0.15), 0, 1))
        x2 = float(np.clip(base + rng.normal(0, 0.2), 0, 1))
        row.update({
            "심판번호": f"T{i // 2}", "상대번호": str(i % 2), "종류": KINDS[i % 4],
            "최종라벨": "유사" if similar else "비유사",
            "표장라벨": ("유사" if similar else "비유사") if i % 9 else "",
            "상표유형": TYPES[i % 5], "상표유형_출처": "확정", "이름A": "a", "이름B": "b",
            "이름B_출처": ("kipris", "llm")[i % 2], "pair_source": "trial",
            "x1_d": f"{x1:.4f}" if i % 11 else "", "x2_text_d": f"{x2:.4f}" if i % 11 else "",
            "x2_whole": f"{float(np.clip(0.5 + rng.normal(0, 0.1), 0, 1)):.4f}" if i % 7 else "",
            "x3_d": f"{float(np.clip(base + rng.normal(0, 0.3), 0, 1)):.4f}" if i % 11 else "",
            "x4": f"{float(np.clip(base + rng.normal(0, 0.3), 0, 1)):.4f}" if i % 4 else "",
            "has_names": 1 if i % 11 else 0, "has_pron_a": 1, "has_pron_b": 1,
            "has_meaning_a": 1 if i % 6 else 0, "has_meaning_b": 1,
            "has_spelling_a": 1, "has_spelling_b": 1, "has_goods": 1 if i % 4 else 0,
            "has_image": 1 if i % 7 else 0, "has_fig": 0,
            "has_distinctive_part_a": 1, "has_distinctive_part_b": 1 if i % 8 else 0,
        })
        rows.append(row)
    return rows


def _easy_rows(n: int = 60, seed: int = 1) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        source = "cross" if i % 2 == 0 else "db"
        row = {column: "" for column in EASY_COLUMNS}
        row.update({
            "심판번호": f"{source}:T{i % 20}|X{i}", "최종라벨": "비유사", "표장라벨": "비유사",
            "이름A": "a", "이름B": "c", "이름B_출처": "db", "pair_source": source,
            "x1_d": f"{float(np.clip(0.15 + rng.normal(0, 0.1), 0, 1)):.4f}",
            "x2_text_d": f"{float(np.clip(0.1 + rng.normal(0, 0.1), 0, 1)):.4f}",
            "x3_d": "0.0000", "x4": f"{0.0 if i % 3 else 0.2:.4f}" if i % 2 else "",
            "has_names": 1, "has_pron_a": 1, "has_pron_b": 1, "has_meaning_a": 0,
            "has_meaning_b": 1, "has_spelling_a": 1, "has_spelling_b": 1,
            "has_goods": 1 if i % 2 else 0, "has_image": 0, "has_fig": 0,
            "has_distinctive_part_a": 1, "has_distinctive_part_b": 1,
        })
        rows.append(row)
    return rows


def _write(path, rows, columns):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def data(tmp_path):
    features = tmp_path / "pairs_features.csv"
    easy = tmp_path / "pairs_features_easy.csv"
    _write(features, _trial_rows(), pf.COLUMNS)
    _write(easy, _easy_rows(), EASY_COLUMNS)
    return features, easy


def test_fit_logistic_matches_sklearn_and_two_stage_offset():
    pytest.importorskip("sklearn")
    from sklearn.linear_model import LogisticRegression

    rng = np.random.default_rng(3)
    X = rng.random((200, 4))
    y = (X[:, 0] + 0.5 * X[:, 1] - 0.6 + rng.normal(0, 0.3, 200) > 0).astype(float)
    weight = np.ones(200)
    for C in (0.3, 3.0):
        coef, intercept = tr.fit_logistic(X, y, weight, C)
        reference = LogisticRegression(C=C, solver="lbfgs", tol=1e-10, max_iter=5000).fit(X, y)
        assert np.allclose(coef, reference.coef_[0], atol=2e-3)
        assert abs(intercept - reference.intercept_[0]) < 2e-3
    # 오프셋 0 이면 그냥 적합과 같다
    coef0, b0 = tr.fit_logistic(X, y, weight, 1.0)
    coef1, b1 = tr.fit_logistic(X, y, weight, 1.0, offset=np.zeros(200))
    assert np.allclose(coef0, coef1) and b0 == pytest.approx(b1)
    # 2단계 적합: 쉬운 음성 가중치 0 이면 1단계 해 그대로, 양수면 이미지 블록만 고정된다
    names = ["x1_d", "x2_whole", "miss_x2img", "x4"]
    easy = np.zeros(200, dtype=bool)
    easy[150:] = True
    X2 = np.column_stack([X[:, :2], (rng.random(200) < 0.3).astype(float), X[:, 3]])
    X2[easy, 1] = 0.0
    X2[easy, 2] = 1.0
    y2 = y.copy()
    y2[easy] = 0.0
    direct, _ = tr.fit_logistic(X2[~easy], y2[~easy], np.ones(int((~easy).sum())), 1.0)
    only_trial, _ = tr.fit_model(X2, y2, np.where(easy, 0.0, 1.0), names, 1.0, easy)
    assert np.allclose(direct, only_trial)
    mixed, _ = tr.fit_model(X2, y2, np.where(easy, 0.5, 1.0), names, 1.0, easy)
    assert mixed[1] == pytest.approx(only_trial[1]) and mixed[2] == pytest.approx(only_trial[2])
    assert not np.allclose(mixed[[0, 3]], only_trial[[0, 3]])


def test_grade_thresholds_and_calibration():
    prob = np.linspace(0.01, 0.99, 50)
    y = (prob > 0.45).astype(float)
    y[48] = 0.0  # 높은 쪽에 비유사 하나
    result = tr.grade_thresholds(prob, y)
    cuts = result["thresholds"]
    assert cuts["주의"] < cuts["검토 권장"] < cuts["위험"] <= 1.0
    assert cuts["주의"] == pytest.approx(cuts["검토 권장"] / 2, abs=1e-3)
    stats = {g["등급"]: g for g in result["등급별"]}
    assert stats["위험"]["정밀도(등급 안 유사율)"] >= 0.8
    assert stats["검토 권장"]["재현율(이 등급 이상이 잡는 유사)"] >= 0.9
    # 정밀도 0.8 에 못 미치면 위험 하한은 검토 권장과 1.0 의 중간 + 기준 메모
    noisy = tr.grade_thresholds(np.linspace(0.3, 0.7, 40), np.tile([1.0, 0.0], 20))
    assert noisy["기준"] and noisy["thresholds"]["위험"] > noisy["thresholds"]["검토 권장"]
    calib = tr.calibration(prob, y, bins=5)
    assert len(calib["곡선"]) == 5 and sum(c["n"] for c in calib["곡선"]) == 50
    assert 0.0 <= calib["brier"] <= 1.0


def test_run_end_to_end_writes_model_report_and_png(data, tmp_path):
    features, easy = data
    out_dir = tmp_path / "out"
    model_path = tmp_path / "model" / "risk_model_v1.json"
    summary = tr.run(features, easy, out_dir=out_dir, model_path=model_path, c_grid=(0.3, 1.0),
                     w_easy_grid=(0.0, 0.5), folds=3, repeats=1, bootstrap=8, seed=0)
    assert summary["데이터"]["심결_행"] == 120
    assert summary["데이터"]["쉬운_음성"] == {"cross": 30, "db": 30}
    assert set(summary["변형"]) == {"A/w0", "A/w0.5", "B/w0", "B/w0.5"}
    for item in summary["변형"].values():
        assert 0.0 <= item["cv"]["심결"]["auc"] <= 1.0 and item["cv"]["심결+cross+db"]["n"] == 180
    adopted = summary["채택"]
    assert adopted["key"] in summary["변형"] and adopted["C"] in (0.3, 1.0)
    assert set(summary["부트스트랩"]["판례_조건_성립_비율"]) == {
        "(i) 문자계: x1 > x2_whole", "(ii) 도형계: x2_whole > x1", "(iii) x4 > 0",
        "(iv) 요부 없음 → x1 효과 감소"}
    assert all(0.0 <= v <= 1.0 for v in summary["부트스트랩"]["판례_조건_성립_비율"].values())
    assert (out_dir / "risk_model_v1_report.md").exists()
    assert (out_dir / "risk_model_v1_results.json").exists()
    assert (out_dir / "risk_model_v1_calibration.png").stat().st_size > 0
    assert "## 판례 검증" in (out_dir / "risk_model_v1_report.md").read_text(encoding="utf-8")
    # 계수 JSON 은 런타임 검증을 통과하고 risk_score 가 돌아간다
    model = rm.load_model(model_path)
    assert model["variant"] == adopted["variant"] and model["w_easy"] == adopted["w_easy"]
    assert set(model["coefficients"]) == set(tr.VARIANTS[model["variant"]])
    prob, grade, contributions = rm.risk_score({"x1_d": 0.9, "x2_text_d": 0.9, "x4": 1.0,
                                                "mark_type": "문자"}, model)
    assert 0.0 <= prob <= 1.0 and grade in rm.GRADES
    assert set(summary["단독_임계값"]["thresholds"]) == set(tr.AXES)
    assert summary["표장_라벨_보조실험"]["심결"]["n"] > 0
    saved = json.loads((out_dir / "risk_model_v1_results.json").read_text(encoding="utf-8"))
    assert saved["채택"]["key"] == adopted["key"]


def test_groups_and_row_features():
    trial = {"심판번호": "2020100000001", "pair_source": "trial"}
    cross = {"심판번호": "cross:2020100000001|2021100000002", "pair_source": "cross"}
    db = {"심판번호": "db:3|7", "pair_source": "db"}
    assert list(tr.groups_for([trial, cross, db])) == ["2020100000001", "2020100000001", "db:3|7"]
    row = {"x1_d": 0.5, "x2_text_d": float("nan"), "x2_whole": 0.4, "x3_d": 0.2,
           "x4": float("nan"), "has_meaning_a": 1, "has_meaning_b": 0,
           "has_distinctive_part_a": "1", "has_distinctive_part_b": "0",
           "상표유형": "결합-도형요부"}
    features = tr.row_features(row)
    assert features["x2_text_d"] is None and features["x4"] is None
    assert features["has_meaning_both"] is False and features["has_distinctive_part_b"] is False
    vector = rm.design_vector(features, tr.VARIANTS["B"])
    assert vector[tr.VARIANTS["B"].index("x2_whole×도형계")] == 0.4
    assert vector[tr.VARIANTS["B"].index("miss_x3")] == 1.0
