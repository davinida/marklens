"""통합 모델 학습 스크립트(v1.1) 테스트 — 합성 특징 CSV 로 끝까지(모델 다운로드·실데이터 없음).
EBM·GBM 은 실험 의존성이 있을 때만, 그리고 서브프로세스로(torch 가 적재된 pytest 프로세스에서
lightgbm 을 부르면 macOS 에서 OpenMP 충돌로 SIGSEGV)."""

from __future__ import annotations

import csv
import json
import subprocess
import sys

import numpy as np
import pytest
from src.model import risk_model as rm

from scripts import train_risk_model as tr

KINDS = ("거절결정불복", "무효", "권리범위확인(적극적)", "권리범위확인(소극적)")
TYPES = ("문자", "도형", "결합-문자요부", "결합-도형요부", "미상")
META_COLUMNS = ["심판번호", "종류", "상대번호", "최종라벨", "표장라벨", "판단축", "판단축_출처",
                "상표유형", "상표유형_출처", "이름A", "이름B", "이름B_출처", "메모", "pair_source"]
AXIS_COLUMNS = ["x1", "x2_text", "x2_fig", "x2_whole", "x3", "x3_raw", "x4", "x1_d", "x2_text_d",
                "x3_d"]
FLAG_COLUMNS = ["has_names", "has_pron_a", "has_pron_b", "has_meaning_a", "has_meaning_b",
                "has_spelling_a", "has_spelling_b", "has_goods", "has_image", "has_fig",
                "has_distinctive_part_a", "has_distinctive_part_b", "weak_a", "weak_b"]
COLUMNS = META_COLUMNS + AXIS_COLUMNS + FLAG_COLUMNS
EASY_COLUMNS = [c for c in COLUMNS if c not in ("weak_a", "weak_b")]


def _trial_rows(n: int = 120, seed: int = 0) -> list[dict]:
    """x1·x2_text 가 라벨과 함께 움직이고 x4 도 약하게 움직이는 합성 행(일부 결측·게이트 꺼짐·이름
    없음)."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        similar = i % 5 != 0 and i % 3 != 1
        base = 0.65 if similar else 0.3
        row = {column: "" for column in COLUMNS}
        x1 = float(np.clip(base + rng.normal(0, 0.15), 0, 1))
        x2 = float(np.clip(base + rng.normal(0, 0.2), 0, 1))
        named = i % 11 != 0
        row.update({
            "심판번호": f"T{i // 2}", "상대번호": str(i % 2), "종류": KINDS[i % 4],
            "최종라벨": "유사" if similar else "비유사",
            "표장라벨": ("유사" if similar else "비유사") if i % 9 else "",
            "상표유형": TYPES[i % 5], "상표유형_출처": "확정", "이름A": "a",
            "이름B": "b" if named else "",
            "이름B_출처": ("kipris", "llm")[i % 2] if named else "", "pair_source": "trial",
            "x1_d": f"{x1:.4f}" if named else "", "x2_text_d": f"{x2:.4f}" if named else "",
            "x2_whole": f"{float(np.clip(0.5 + rng.normal(0, 0.1), 0, 1)):.4f}" if i % 7 else "",
            "x3_d": f"{float(np.clip(base + rng.normal(0, 0.3), 0, 1)):.4f}" if named else "",
            "x4": f"{float(np.clip(base + rng.normal(0, 0.3), 0, 1)):.4f}" if i % 4 else "",
            "has_names": int(named), "has_pron_a": 1, "has_pron_b": 1,
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
    _write(features, _trial_rows(), COLUMNS)
    _write(easy, _easy_rows(), EASY_COLUMNS)
    return features, easy


def test_metric_helpers_match_x2_benchmark():
    from scripts import x2_benchmark as x2b

    rng = np.random.default_rng(5)
    scores = rng.random(80)
    labels = (scores + rng.normal(0, 0.3, 80) > 0.5).astype(int)
    assert tr.roc_auc(scores, labels) == pytest.approx(x2b.roc_auc(scores, labels))
    assert tr.bootstrap_auc(scores, labels, rounds=50, seed=1) == x2b.bootstrap_auc(
        scores, labels, rounds=50, seed=1)
    assert tr.roc_auc(scores, np.ones(80, dtype=int)) is None
    point = tr.precision_threshold(scores, labels, target=0.7, min_support=10)
    assert point["threshold"] is None or point["precision"] >= 0.7


def test_fit_logistic_matches_sklearn_and_image_offset():
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
    # 2단계 적합: 쉬운 음성 가중치 0 이면 심결 행만의 적합, 양수면 이미지 블록만 고정된다
    names = ["x1_d", "x2_whole", "miss_x2img", "x4"]
    easy = np.zeros(200, dtype=bool)
    easy[150:] = True
    X2 = np.column_stack([X[:, :2], (rng.random(200) < 0.3).astype(float), X[:, 3]])
    X2[easy, 1] = 0.0
    X2[easy, 2] = 1.0
    y2 = y.copy()
    y2[easy] = 0.0
    direct, _ = tr.fit_logistic(X2[~easy], y2[~easy], np.ones(int((~easy).sum())), 1.0)
    only_trial, _ = tr.fit_linear(X2, y2, np.where(easy, 0.0, 1.0), names, easy,
                                  method="logistic", hyper=1.0)
    assert np.allclose(direct, only_trial)
    mixed, _ = tr.fit_linear(X2, y2, np.where(easy, 0.5, 1.0), names, easy, method="logistic",
                             hyper=1.0)
    assert mixed[1] == pytest.approx(only_trial[1]) and mixed[2] == pytest.approx(only_trial[2])
    assert not np.allclose(mixed[[0, 3]], only_trial[[0, 3]])


def test_fit_prior_respects_prior_mean_free_intercept_and_monotone_combos():
    rng = np.random.default_rng(7)
    names = ["x1_d", "x2_whole", "x4", "miss_x4", "any_no_distinctive", "x1_d×문자계",
             "x2_whole×도형계", "x1_d×any_no_distinctive"]
    n = 300
    text = rng.random(n) < 0.7
    no_distinct = (rng.random(n) < 0.15).astype(float)
    x1, x2, x4 = rng.random(n), rng.random(n), rng.random(n)
    X = np.column_stack([x1, x2, x4, (rng.random(n) < 0.2).astype(float), no_distinct,
                         np.where(text, x1, 0.0), np.where(~text, x2, 0.0), x1 * no_distinct])
    # x4 가 라벨과 반대로 움직이는 자료 — 제약 없는 적합은 x4 계수가 음수
    y = (2.0 * x1 - 1.5 * x4 - 0.2 + rng.normal(0, 0.4, n) > 0).astype(float)
    weight = np.ones(n)
    free, _ = tr.fit_logistic(X, y, weight, 3.0)
    assert free[names.index("x4")] < 0
    coef, intercept = tr.fit_prior(X, y, weight, names, 1.0)
    assert rm.monotone_violations(dict(zip(names, coef))) == []
    G = tr.monotone_constraints(names)
    assert G.shape == (7, len(names)) and np.all(G @ coef >= -1e-9)  # 축 3 + x2 합 + x1 조합 3
    # σ 가 아주 작으면 사전분포 항은 사전평균으로 가고, 절편은 자유라 0 에 묶이지 않는다
    tight, tight_b = tr.fit_prior(X, y, weight, names, 0.02)
    for name in ("x1_d", "x4", "x1_d×문자계", "x1_d×any_no_distinctive"):
        assert abs(tight[names.index(name)] - tr.PRIOR_MU[name]) < 0.1
    assert abs(tight_b) > 0.3  # 절편은 자료가 정한다(사전분포 없음)
    assert "miss_x4" not in tr.PRIOR_FEATURES and "any_no_distinctive" not in tr.PRIOR_FEATURES
    # σ 가 크면 사전분포 영향이 작아 자료 쪽(x1 계수가 1.0 에서 멀어진다)
    loose, _ = tr.fit_prior(X, y, weight, names, 5.0)
    assert abs(loose[names.index("x1_d")] - 1.0) > abs(tight[names.index("x1_d")] - 1.0)
    # 사전분포 항이 없는 입력(제약만) — 제약이 걸리지 않는 자료면 로지스틱(C 큼)과 거의 같다
    plain = ["x1_d", "x2_text_d", "miss_x4"]
    Xp = np.column_stack([x1, x2, X[:, 3]])
    yp = (2.0 * x1 + 1.0 * x2 - 1.2 + rng.normal(0, 0.4, n) > 0).astype(float)
    mle, mle_b = tr.fit_logistic(Xp, yp, weight, 1e6)
    near, near_b = tr.fit_prior(Xp, yp, weight, plain, 1e3)
    assert np.allclose(mle, near, atol=0.05) and abs(mle_b - near_b) < 0.05
    # 선형 모델의 부분의존 기울기는 계수(합)와 같다 — 요부 없는 행은 교호작용이 더해진다
    fitted = tr.Fitted("prior", names, coef=coef, intercept=intercept)
    family = np.where(text, "text", "figure")
    slope = tr.pd_slope(fitted, X, family, "x1_d", text & (no_distinct == 0))
    assert slope == pytest.approx(coef[names.index("x1_d")] + coef[names.index("x1_d×문자계")])
    slope_nd = tr.pd_slope(fitted, X, family, "x1_d", text & (no_distinct == 1))
    assert slope_nd == pytest.approx(slope + coef[names.index("x1_d×any_no_distinctive")])
    assert tr.pd_slope(fitted, X, family, "x4", np.ones(n, dtype=bool)) == pytest.approx(
        coef[names.index("x4")])
    assert tr.pd_slope(fitted, X, family, "x3_d", np.ones(n, dtype=bool)) is None  # 입력에 없음


def test_grade_thresholds_calibration_and_adopt_rule():
    prob = np.linspace(0.01, 0.99, 50)
    y = (prob > 0.45).astype(float)
    y[48] = 0.0
    result = tr.grade_thresholds(prob, y)
    cuts = result["thresholds"]
    assert cuts["주의"] < cuts["검토 권장"] < cuts["위험"] <= 1.0
    stats = {g["등급"]: g for g in result["등급별"]}
    assert stats["위험"]["정밀도(등급 안 유사율)"] >= 0.8
    assert stats["검토 권장"]["재현율(이 등급 이상이 잡는 유사)"] >= 0.9
    calib = tr.calibration(prob, y, bins=5)
    assert len(calib["곡선"]) == 5 and sum(c["n"] for c in calib["곡선"]) == 50
    # 채택 규칙: 기준 CI 상한을 넘는 방법이 없으면 prior, 있으면 사람 결정 대기
    results = {"logistic": {"cv": {"심결": {"auc": 0.60, "auc_ci95": [0.55, 0.65]}}},
               "prior": {"cv": {"심결": {"auc": 0.61, "auc_ci95": [0.56, 0.66]}}},
               "gbm": {"cv": {"심결": {"auc": 0.64, "auc_ci95": [0.58, 0.70]}}}}
    assert tr.adopt(results) == ("prior", False, tr.adopt(results)[2])
    results["gbm"]["cv"]["심결"]["auc"] = 0.66
    method, pending, notes = tr.adopt(results)
    assert method == "prior" and pending and "gbm" in notes[1]


def test_run_end_to_end_logistic_and_prior(data, tmp_path):
    features, easy = data
    out_dir = tmp_path / "out"
    model_path = tmp_path / "model" / "risk_model_v1.json"
    summary = tr.run(features, easy, out_dir=out_dir, model_path=model_path,
                     methods=("logistic", "prior"), c_grid=(0.3, 1.0), sigma_grid=(0.5, 2.0),
                     folds=3, repeats=1, bootstrap=8, seed=0, min_pattern_minority=5)
    data_summary = summary["데이터"]
    assert data_summary["심결_행"] == 120 - data_summary["이름_없어_제외"]["행"]
    assert data_summary["이름_없어_제외"]["행"] == 11
    assert data_summary["패턴_축"] == ["x2_whole", "x4"]
    assert data_summary["제거_항"] == tr.REMOVED_TERMS + ["miss_x2img", "miss_x4", "miss_x3"]
    assert data_summary["쉬운_음성_이미지_있음"] == 0  # 합성 쉬운 음성에는 이미지가 없다
    assert data_summary["결합_하한"]["x2_whole"]["근거"].startswith("심결 비유사 평균")
    assert data_summary["결합_하한"]["x4"]["근거"] == "쉬운 음성 비유사 평균"
    assert set(data_summary["입력(패턴별)"]) == {"base", "x2_whole", "x4", "x2_whole+x4"}
    assert set(summary["방법"]) == {"logistic", "prior"}
    for item in summary["방법"].values():
        assert 0.0 <= item["cv"]["심결"]["auc"] <= 1.0
        assert set(item["판례_조건_겹_성립_비율"]) == set(tr.CONDITIONS)
        assert "intercept" in item["부트스트랩"]["계수"]
        assert set(item["부트스트랩"]["패턴"]) == set(data_summary["입력(패턴별)"])
        assert "x1_d×any_no_distinctive" in item["부트스트랩"]["계수"]
        assert set(item["패턴"]) == set(data_summary["입력(패턴별)"])
        assert item["패턴"]["base"]["n"] >= item["패턴"]["x2_whole+x4"]["n"]
        assert set(item["단조성"]) == {"base → x2_whole (x2_whole)", "base → x4 (x4)",
                                      "x4 → x2_whole+x4 (x2_whole)", "x2_whole → x2_whole+x4 (x4)"}
    for block in summary["방법"]["prior"]["단조성"].values():  # 결합 제약 → 하한 이상 위반 0
        assert block["하한_이상"]["위반(p 내려감)"] == 0
        assert block["하한값_대입_로짓차_최소"] >= -1e-6
    assert summary["채택"]["method"] in ("prior", "logistic")
    assert set(summary["단독_임계값"]["thresholds"]) == set(tr.AXES)
    assert summary["단독_임계값"]["목표_정밀도"] == 0.7
    assert set(summary["요부_교차표"]) == {"has_distinctive_part_a", "has_distinctive_part_b",
                                       "any_no_distinctive"}
    assert "miss_x2img" in summary["참고_지시변수_모델"]["계수"]
    assert (out_dir / "risk_model_v1_report.md").exists()
    assert (out_dir / "risk_model_v1_calibration.png").stat().st_size > 0
    report = (out_dir / "risk_model_v1_report.md").read_text(encoding="utf-8")
    assert "## 방법 비교" in report and "## 요부 유무 × 라벨" in report
    assert "### 결측 패턴별 계수 집합" in report and "### 단조성(결합 제약) 검사" in report
    assert "## 참고 — 지시변수 모델" in report
    model = rm.load_model(model_path)
    assert model["version"] == "risk_model_v1.3"
    assert model["removed_terms"] == data_summary["제거_항"]
    assert model["meta"]["sigma_selection"] == "cv" and model["meta"]["risk_min_support"] == 30
    assert "grade_precision" in model["meta"] and "monotonicity" in model["meta"]
    assert model["meta"]["indicator_reference"]["계수"]["miss_x2img"] is not None
    assert model["pattern_axes"] == ["x2_whole", "x4"]
    assert model["reference_pattern"] == "x2_whole+x4"
    assert sorted(model["patterns"]) == sorted(rm.pattern_keys(["x2_whole", "x4"]))
    reference = model["patterns"]["x2_whole+x4"]
    assert model["features"] == reference["features"]
    assert model["intercept"] == reference["intercept"]
    assert reference["requires"] == ["x2_whole", "x4"]
    assert model["patterns"]["base"]["requires"] == []
    for key, block in model["patterns"].items():
        assert not any(name.startswith("type_") or name.startswith("miss_")
                       for name in block["features"])
        assert "any_no_distinctive" in block["features"]
        assert "x1_d×any_no_distinctive" in block["features"]
        assert ("x2_whole" in block["features"]) == ("x2_whole" in key)
        assert ("x4" in block["features"]) == ("x4" in key)
        assert block["meta"]["n"] > 0 and "cv_auc" in block["meta"]
    assert model["figure_rule"] == {"threshold": tr.FIGURE_X2_THRESHOLD, "caveat": tr.FIGURE_CAVEAT,
                                    "validated": False, "basis": model["figure_rule"]["basis"]}
    if model["method"] == "prior_monotone_logistic":
        assert model["prior"]["sigma"] in (0.5, 2.0) and model["monotone"]
        assert model["prior"]["intercept_prior"] is False
        assert set(model["prior"]["applies_to"]) <= set(tr.PRIOR_FEATURES)
        assert model["coupling"]["floors"] == {
            axis: data_summary["결합_하한"][axis]["하한"] for axis in ("x2_whole", "x4")}
        for block in model["patterns"].values():
            assert rm.monotone_violations(block["coefficients"]) == []
        assert rm.coupling_violations(model) == []
    else:
        assert model["coupling"] is None
    result = rm.risk_score({"x1_d": 0.9, "x2_text_d": 0.9, "x4": 1.0, "mark_type": "문자"}, model)
    assert 0.0 <= result.prob <= 1.0 and result.grade in rm.GRADES and not result.figure_caveat
    assert result.pattern == "x4"
    assert rm.risk_score({"x2_whole": 0.95, "mark_type": "도형"}, model).figure_caveat
    assert rm.risk_score({"x2_whole": 0.95, "mark_type": "도형"}, model).pattern == "x2_whole"
    saved = json.loads((out_dir / "risk_model_v1_results.json").read_text(encoding="utf-8"))
    assert saved["채택"]["method"] == summary["채택"]["method"]


def test_run_falls_back_to_fewer_patterns_when_minority_small(data, tmp_path):
    """패턴마다 소수 클래스가 기준 미만이면 이미지만 → 패턴 없음(지시변수 구조)으로 내려간다."""
    features, easy = data
    summary = tr.run(features, easy, out_dir=tmp_path / "out", model_path=tmp_path / "m.json",
                     methods=("prior",), sigma_grid=(1.0,), folds=3, repeats=1, bootstrap=2,
                     seed=0, min_pattern_minority=10_000)
    assert summary["데이터"]["패턴_축"] == [] and len(summary["데이터"]["패턴_결정"]["시도"]) == 3
    model = rm.load_model(tmp_path / "m.json")
    assert model["pattern_axes"] == [] and list(model["patterns"]) == ["base"]
    assert model["reference_pattern"] == "base" and model["coupling"] is None
    assert {"x2_whole", "miss_x2img", "x4", "miss_x4"} <= set(model["features"])
    assert "miss_x3" not in model["features"]
    assert rm.risk_score({"x1_d": 0.5, "mark_type": "문자"}, model).pattern == "base"


def test_run_ebm_and_gbm_in_subprocess(data, tmp_path):
    pytest.importorskip("interpret")
    pytest.importorskip("lightgbm")
    pytest.importorskip("shap")
    features, easy = data
    out_dir = tmp_path / "out"
    model_path = tmp_path / "model" / "risk_model_v1.json"
    command = [sys.executable, str(tr.ML_ROOT / "scripts" / "train_risk_model.py"),
               "--methods", "logistic,prior,ebm,gbm", "--features", str(features),
               "--easy", str(easy), "--out-dir", str(out_dir), "--model", str(model_path),
               "--folds", "3", "--repeats", "1", "--bootstrap", "5"]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=600)
    assert completed.returncode == 0, completed.stderr[-2000:]
    saved = json.loads((out_dir / "risk_model_v1_results.json").read_text(encoding="utf-8"))
    assert set(saved["방법"]) == {"logistic", "prior", "ebm", "gbm"}
    assert saved["방법"]["ebm"]["features"] == tr.TREE_FEATURES
    assert saved["방법"]["gbm"]["shap_평균절대값"]
    assert (out_dir / "risk_model_v1_ebm_shapes.png").exists()
    rates = saved["방법"]["ebm"]["판례_조건_겹_성립_비율"]
    assert rates["(i) 문자계: x1 > x2_whole"] is None  # 트리 입력에 이미지 축이 없다
    assert rm.load_model(model_path)["method"] in ("prior_monotone_logistic", "logistic_l2")


def test_groups_row_features_and_perturbation():
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
    vector = rm.design_vector(features, tr.FEATURES)
    assert vector[tr.FEATURES.index("x2_whole×도형계")] == 0.4
    assert vector[tr.FEATURES.index("miss_x3")] == 1.0
    assert vector[tr.FEATURES.index("any_no_distinctive")] == 1.0  # b 쪽 요부 없음
    assert vector[tr.FEATURES.index("x1_d×any_no_distinctive")] == 0.5
    X = np.asarray([vector])
    high = tr.perturbed(X, tr.FEATURES, np.asarray(["figure"]), "x2_whole", 1.0)
    assert high[0, tr.FEATURES.index("x2_whole")] == 1.0
    assert high[0, tr.FEATURES.index("x2_whole×도형계")] == 1.0
    assert high[0, tr.FEATURES.index("miss_x2img")] == 0.0
    low = tr.perturbed(X, tr.FEATURES, np.asarray(["text"]), "x1_d", 0.0)
    assert low[0, tr.FEATURES.index("x1_d×문자계")] == 0.0
    assert low[0, tr.FEATURES.index("x1_d×any_no_distinctive")] == 0.0
    high1 = tr.perturbed(X, tr.FEATURES, np.asarray(["text"]), "x1_d", 1.0)
    assert high1[0, tr.FEATURES.index("x1_d×any_no_distinctive")] == 1.0  # 요부 없음 유지
    assert tr.perturbed(X, tr.TREE_FEATURES[:3], np.asarray(["text"]), "x4", 1.0) is None


def test_pattern_helpers_and_choice():
    axes = tr.PATTERN_AXES
    assert tr.pattern_features("base", axes) == tr.PATTERN_BASE
    assert tr.pattern_features("x2_whole+x4", axes) == tr.PATTERN_BASE + [
        "x2_whole", "x2_whole×도형계", "x4"]
    assert tr.pattern_features("x2_whole", ("x2_whole",)) == tr.PATTERN_BASE + [
        "x2_whole", "x2_whole×도형계", "x4", "miss_x4"]  # 폴백: 패턴 밖 축은 값 + 지시변수
    assert tr.pattern_features("base", ()) == tr.PATTERN_BASE + [
        "x2_whole", "x2_whole×도형계", "miss_x2img", "x4", "miss_x4"]
    rows = [{"x2_whole": 0.4, "x4": np.nan}, {"x2_whole": np.nan, "x4": 0.0},
            {"x2_whole": 0.9, "x4": 1.0}, {"x2_whole": np.nan, "x4": np.nan}]
    assert list(tr.row_pattern_keys(rows, axes)) == ["x2_whole", "x4", "x2_whole+x4", "base"]
    masks = tr.pattern_masks(rows, axes)
    assert masks["base"].tolist() == [True] * 4
    assert masks["x2_whole"].tolist() == [True, False, True, False]
    assert masks["x4"].tolist() == [False, True, True, False]
    assert masks["x2_whole+x4"].tolist() == [False, False, True, False]
    y = np.asarray([1.0, 0.0, 1.0, 0.0])
    chosen, report = tr.choose_pattern_axes(rows, y, min_minority=1)
    assert chosen == () and len(report["시도"]) == 3  # x2_whole+x4 행 1개(비유사 0) → 축을 다 뺀다
    assert report["시도"][0]["패턴"]["x2_whole+x4"] == {"n": 1, "유사": 1, "비유사": 0}
    chosen, _ = tr.choose_pattern_axes(rows, y, min_minority=0)
    assert chosen == axes


def test_coupling_rows_feasible_at_prior_mean_and_joint_fit_satisfies_constraints(data):
    features, easy = data
    rows = [row for row in tr.load_rows(features, easy) if row["최종라벨"] in ("유사", "비유사")
            and (row["pair_source"] != "trial" or tr.has_name(row))]
    y = tr.labels_for(rows, "최종").astype(np.float64)
    weight = tr.sample_weights(rows, 0.5)
    design = tr.PatternDesign(rows, tr.PATTERN_AXES)
    assert design.keys == ["base", "x2_whole", "x4", "x2_whole+x4"] and design.full == "x2_whole+x4"
    assert design.size == sum(len(design.names[k]) + 1 for k in design.keys) == 7 + 9 + 8 + 10
    floors = {"x2_whole": 0.35, "x4": 0.03}
    A = tr.coupling_rows(design, floors)
    assert A.shape == (32 + 32 + 64 + 64, design.size)
    start = np.zeros(design.size)
    for key in design.keys:
        offset = design.offset[key]
        for i, name in enumerate(design.names[key]):
            start[offset + i] = tr.PRIOR_MU.get(name, 0.0)
    assert (A @ start >= -1e-12).all()  # 사전평균·절편 0 은 실행 가능 시작점
    assert (tr.monotone_rows(design) @ start >= -1e-12).all()
    fitted = tr.fit_patterns_prior(design, y, weight, np.arange(y.size), 1.0, floors)
    theta = np.concatenate([np.concatenate([fitted[k][0], [fitted[k][1]]]) for k in design.keys])
    assert (A @ theta >= -1e-6).all() and (tr.monotone_rows(design) @ theta >= -1e-6).all()
    blocks = tr.rounded_blocks(design, fitted, floors)
    model_like = {"patterns": blocks, "pattern_axes": list(design.axes),
                  "coupling": {"floors": floors}}
    assert rm.coupling_violations(model_like) == []
    for block in blocks.values():
        assert rm.monotone_violations(block["coefficients"]) == []
    # 패턴별 독립 L2 적합(기준 방법)은 제약이 없어 결합 제약을 어길 수 있다 — 함수는 돈다
    independent = tr.fit_patterns_logistic(design, y, weight, np.arange(y.size), 1.0)
    assert set(independent) == set(design.keys)
    own = design.own_prob(fitted, np.arange(y.size))
    assert own.shape == (y.size,) and ((own > 0) & (own < 1)).all()


def test_rounded_blocks_repairs_rounding_violations(data):
    features, easy = data
    rows = [row for row in tr.load_rows(features, easy) if row["최종라벨"] in ("유사", "비유사")]
    design = tr.PatternDesign(rows, tr.PATTERN_AXES)
    floors = {"x2_whole": 0.3, "x4": 0.02}
    # 공통 항·패턴 축 계수 0 → 결합 여유 = 절편 차. 상위 절편을 0.00009 낮게 두면 반올림 뒤
    # −0.0001 위반.
    fitted = {key: (np.zeros(len(design.names[key])), -3.0) for key in design.keys}
    fitted["x2_whole"] = (fitted["x2_whole"][0], -3.00009)
    fitted["x2_whole+x4"] = (fitted["x2_whole+x4"][0], -3.00018)
    assert tr.coupling_slack(
        {k: {"features": design.names[k], "coefficients": dict.fromkeys(design.names[k], 0.0),
             "intercept": round(v[1], 4)} for k, v in fitted.items()},
        design.axes, floors, "x2_whole") < 0
    blocks = tr.rounded_blocks(design, fitted, floors)
    assert blocks["x2_whole"]["intercept"] >= blocks["base"]["intercept"]
    assert blocks["x2_whole+x4"]["intercept"] >= max(blocks["x2_whole"]["intercept"],
                                                     blocks["x4"]["intercept"])
    assert rm.coupling_violations({"patterns": blocks, "pattern_axes": list(design.axes),
                                   "coupling": {"floors": floors}}) == []


def test_shipped_model_monotone_on_training_pairs():
    """배포 JSON(v1.3)·학습 데이터가 있을 때: 정답 데이터 전체 쌍에서 이미지·상품을 더 관측해도(값이
    하한 이상이면) p 가 내려가지 않는다 — 결합 제약의 데이터 확인."""
    if not rm.DEFAULT_MODEL_PATH.exists() or not tr.DEFAULT_FEATURES.exists():
        pytest.skip("계수 파일 또는 학습 데이터 없음")
    model = rm.load_model()
    if not model.get("patterns") or not model.get("coupling"):
        pytest.skip("패턴·결합 제약 없는 모델")
    floors = model["coupling"]["floors"]
    rows = [row for row in tr.load_rows(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY)
            if row["최종라벨"] in ("유사", "비유사")]
    checked = 0
    for row in rows:
        features = tr.row_features(row)
        for axis in model["pattern_axes"]:
            value = features.get(axis)
            if value is None or value < floors[axis]:
                continue
            with_axis = rm.risk_score(features, model).prob
            without = rm.risk_score({**features, axis: None}, model).prob
            assert with_axis >= without - 1e-9, (row["심판번호"], axis, value, with_axis, without)
            checked += 1
    assert checked > 100
