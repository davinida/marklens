"""이름 없는 입력의 등급 하한(ml/scripts/nameless_grade_thresholds.py) 테스트 — 규칙의 각 가지를
작은 합성 행으로 확인한다(실데이터 없음). 이름 있는 채점에는 저장소의 v1.3 계수를, 이름 없는
채점에는 거기에 간단한 이름 없는 집합을 붙인 모델을 쓴다."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest
from src.model import risk_model as rm

from scripts import nameless_grade_thresholds as ngt

NAN = float("nan")


def _model(image_only=(-2.0, 2.0, 0.5), with_goods=(-2.05, 2.0, 0.5, 1.5)) -> dict:
    """v1.3 JSON + 이름 없는 2벌(절편, x2_whole, ×도형계[, x4]). 결합 검증은 끈다(coupling null)."""
    model = copy.deepcopy(rm.load_model())
    model["version"] = "risk_model_v1.4"
    model["coupling"] = None
    model[rm.NAMELESS_KEY] = {
        "x2_whole": {"features": ["x2_whole", "x2_whole×도형계"],
                     "coefficients": {"x2_whole": image_only[1], "x2_whole×도형계": image_only[2]},
                     "intercept": image_only[0]},
        "x2_whole+x4": {"features": ["x2_whole", "x2_whole×도형계", "x4"],
                        "coefficients": {"x2_whole": with_goods[1],
                                         "x2_whole×도형계": with_goods[2], "x4": with_goods[3]},
                        "intercept": with_goods[0]},
    }
    return rm.validate_model(model)


def _row(x1: float, image: float, goods: float = NAN, source: str = "db", **extra) -> dict:
    """쉬운 음성 한 쌍(이름 있음). x1 로 이름 있는 등급을, image·goods 로 이름 없는 위험도를
    정한다."""
    row = {"pair_source": source, "심판번호": f"{source}:{x1}|{image}", "상표유형": "",
           "x1_d": x1, "x2_text_d": x1, "x3_d": 0.0, "x2_whole": image, "x4": goods,
           "has_meaning_a": 0, "has_meaning_b": 0, "has_distinctive_part_a": 1,
           "has_distinctive_part_b": 1, "최종라벨": "비유사"}
    row.update(extra)
    return row


def _named_levels(rows: list[dict], key: str) -> list[int]:
    old = rm.load_model()
    return [rm.GRADES.index(rm.risk_score(ngt.named_input(row, key), old).grade) for row in rows]


def _nameless_probs(rows: list[dict], key: str, model: dict) -> list[float]:
    return [rm.risk_score(ngt.nameless_input(row, key), model).prob for row in rows]


def test_reference_set_and_inputs():
    rows = [_row(0.2, 0.3), _row(0.2, NAN), _row(0.2, 0.4, 0.5, source="cross"),
            _row(0.2, 0.5, 0.0), _row(0.9, 0.6, 0.2, pair_source="trial")]
    image_only = ngt.reference_rows(rows, "x2_whole")
    with_goods = ngt.reference_rows(rows, "x2_whole+x4")
    assert [r["x2_whole"] for r in image_only] == [0.3, 0.4, 0.5]  # 심결 행·이미지 없는 쌍 제외
    assert [r["x2_whole"] for r in with_goods] == [0.4, 0.5]  # 상품도 관측된 쌍만
    named = ngt.named_input(rows[2], "x2_whole")
    assert named["x4"] is None and named["x1_d"] == 0.2 and named["x2_whole"] == 0.4  # 같은 축만
    assert ngt.named_input(rows[2], "x2_whole+x4")["x4"] == 0.5
    nameless = ngt.nameless_input(rows[2], "x2_whole")
    assert nameless["x1_d"] is None and nameless["x2_text_d"] is None and nameless["x4"] is None
    assert nameless["mark_type"] == "도형" and nameless["x2_whole"] == 0.4
    assert ngt.nameless_input(rows[2], "x2_whole+x4")["x4"] == 0.5
    model = _model()
    assert rm.risk_score(nameless, model).pattern == "noname:x2_whole"
    assert rm.risk_score(named, model).pattern == "x2_whole"


def test_threshold_is_kth_largest_nameless_probability():
    """이름 있는 입력에서 그 등급 이상인 쌍 수 k → 이름 없는 위험도의 k 번째로 큰 값(내림)."""
    model = _model()
    names = [0.05, 0.1, 0.2, 0.3, 0.45, 0.55, 0.62, 0.7, 0.75, 0.78, 0.1, 0.2]
    images = [0.9, 0.1, 0.5, 0.3, 0.7, 0.2, 0.6, 0.4, 0.8, 0.15, 0.35, 0.55]
    rows = [_row(x1, image) for x1, image in zip(names, images)]
    levels = _named_levels(rows, "x2_whole")
    probs = sorted(_nameless_probs(rows, "x2_whole", model), reverse=True)
    result = ngt.calibrate_kind(rows, "x2_whole", rm.load_model(), model)
    assert result["n"] == 12 and result["패턴"] == "noname:x2_whole"
    assert result["쌍_출처"] == {"cross": 0, "db": 12}
    assert result["이름_없는_위험도"]["최댓값"] == round(probs[0], 4)
    for level, grade in enumerate(rm.GRADE_THRESHOLD_KEYS, start=1):
        entry = result["등급"][grade]
        count = sum(1 for value in levels if value >= level)
        assert entry["이름_있는_입력에서_그_등급_이상"] == count
        assert entry["비율"] == round(count / 12, 4)
        if grade == rm.GRADES[-1] or count == 0:
            continue
        assert count >= 1  # 합성 값이 주의·검토 권장을 모두 만든다
        expected = math.floor(probs[count - 1] * 1e4 + 1e-9) / 1e4
        assert entry["맞춘_값"] == entry["하한"] == expected
        assert entry["새_하한에서_그_등급_이상"] == count  # 뜻이 같다: 같은 수의 무관한 쌍
        assert entry["사유"] == "U 에서 비율을 맞춤"
    counts = [result["등급"][g]["이름_있는_입력에서_그_등급_이상"] for g in rm.GRADE_THRESHOLD_KEYS]
    assert counts[0] > counts[1] >= counts[2] and counts[1] >= 1  # 등급이 실제로 갈린다
    cuts = [result["등급"][g]["하한"] for g in rm.GRADE_THRESHOLD_KEYS if result["등급"][g]["하한"]]
    assert cuts == sorted(cuts)


def test_zero_share_and_beyond_sample_maximum_leave_grade_to_standalone_rule():
    model = _model()
    old = rm.load_model()
    existing = old["grade_thresholds"]["위험"]
    # (가) 비율 0: 이름이 모두 다르다 → 이름 있는 입력에서 검토 권장·위험 0쌍
    rows = [_row(0.05, image) for image in (0.2, 0.4, 0.6, 0.8)]
    result = ngt.calibrate_kind(rows, "x2_whole", old, model)
    for grade in ("검토 권장", "위험"):
        entry = result["등급"][grade]
        assert entry["이름_있는_입력에서_그_등급_이상"] == 0 and entry["하한"] is None
        assert entry["맞춘_값"] is None and entry["사유"].startswith("비율 0")
        assert ngt.UNREACHABLE in entry["사유"] and entry["새_하한에서_그_등급_이상"] == 0
    # (나) 위험: 이름 있는 입력에 위험이 있지만 맞춘 값 < 기존 하한이고, 기존 하한이 표본 최댓값을
    #      넘는다(이름 없는 위험도가 모두 낮다) → 단독 규칙으로만
    rows = [_row(1.0, 0.3), _row(1.0, 0.2), _row(0.05, 0.1), _row(0.05, 0.25)]
    result = ngt.calibrate_kind(rows, "x2_whole", old, model)
    risk = result["등급"]["위험"]
    assert risk["이름_있는_입력에서_그_등급_이상"] == 2 and risk["맞춘_값"] < existing
    assert result["이름_없는_위험도"]["최댓값"] < existing
    assert risk["하한"] is None and "표본 최댓값" in risk["사유"]
    assert ngt.UNREACHABLE in risk["사유"]
    # (다) 위험: 맞춘 값 < 기존 하한 ≤ 표본 최댓값 → 기존 하한 유지(내리지 않는다)
    rows = [_row(1.0, 0.3), _row(1.0, 1.0), _row(0.05, 0.2), _row(0.05, 0.1)]
    result = ngt.calibrate_kind(rows, "x2_whole", old, model)
    risk = result["등급"]["위험"]
    assert risk["이름_있는_입력에서_그_등급_이상"] == 2  # 둘째로 큰 이름 없는 위험도는 이미지 0.3
    assert risk["맞춘_값"] < existing <= result["이름_없는_위험도"]["최댓값"]
    assert risk["하한"] == existing and "기존 위험 하한" in risk["사유"]
    assert risk["새_하한에서_그_등급_이상"] == 1  # 기존 하한을 넘는 것은 이미지 1.0 한 쌍뿐
    # (라) 위험: 맞춘 값이 기존 하한보다 높으면 맞춘 값
    high = _model(image_only=(0.0, 2.0, 0.5))
    rows = [_row(1.0, 0.9), _row(0.05, 1.0), _row(0.05, 0.1)]
    result = ngt.calibrate_kind(rows, "x2_whole", old, high)
    risk = result["등급"]["위험"]
    assert risk["맞춘_값"] > existing and risk["하한"] == risk["맞춘_값"]
    assert risk["사유"] == "U 에서 비율을 맞춤" and risk["새_하한에서_그_등급_이상"] == 1
    # 기준 집합이 비면 모든 등급이 단독 규칙으로만
    empty = ngt.calibrate_kind([], "x2_whole", old, model)
    assert empty["n"] == 0 and all(e["하한"] is None for e in empty["등급"].values())


def test_apply_thresholds_keeps_coefficients_and_runtime_uses_them():
    model = _model()
    old = rm.load_model()
    rows = ([_row(x1, image) for x1, image in zip((0.05, 0.3, 0.5, 0.62, 0.7, 0.78, 0.1, 0.2),
                                                   (0.9, 0.5, 0.7, 0.2, 0.6, 0.4, 0.8, 0.3))]
            + [_row(x1, image, goods) for x1, image, goods in (
                (0.05, 0.9, 0.0), (0.3, 0.5, 1.0), (0.62, 0.7, 0.2), (0.78, 0.2, 0.0),
                (0.1, 0.6, 0.5), (0.7, 0.3, 0.0))])
    calibration = ngt.calibrate(rows, old, model)
    assert set(calibration["종류"]) == {"이미지만", "이미지+상품"}
    assert calibration["종류"]["이미지만"]["n"] == 14
    assert calibration["종류"]["이미지+상품"]["n"] == 6
    assert calibration["규칙"] == ngt.RULE
    thresholds = ngt.thresholds_from(calibration)
    assert set(thresholds) == {"x2_whole", "x2_whole+x4"}
    after = ngt.apply_thresholds(model, calibration)
    assert model[rm.NAMELESS_KEY]["x2_whole"].get("grade_thresholds") is None  # 원본 불변
    for key in thresholds:
        assert after[rm.NAMELESS_KEY][key]["grade_thresholds"] == thresholds[key]
        for field in ("features", "coefficients", "intercept"):
            assert after[rm.NAMELESS_KEY][key][field] == model[rm.NAMELESS_KEY][key][field]
    assert after["patterns"] == old["patterns"] and after["grade_thresholds"] == old[
        "grade_thresholds"]
    meta = after["meta"]["nameless"]["grade_thresholds"]
    assert meta["rule"] == ngt.RULE and set(meta["kinds"]) == {"이미지만", "이미지+상품"}
    stored_caution = meta["kinds"]["이미지만"]["grades"]["주의"]["threshold"]
    assert stored_caution == thresholds["x2_whole"]["주의"]
    # 뗐다 다시 계산해도 같다(멱등)
    assert ngt.without_thresholds(after)[rm.NAMELESS_KEY] == model[rm.NAMELESS_KEY]
    again = ngt.calibrate(rows, old, after)
    assert ngt.thresholds_from(again) == thresholds
    # 런타임: 이름 없는 입력은 자기 하한, 이름 있는 입력은 종전 하한
    caution = thresholds["x2_whole"]["주의"]
    for row in ngt.reference_rows(rows, "x2_whole"):
        nameless = rm.risk_score(ngt.nameless_input(row, "x2_whole"), after)
        expected = rm.grade_for(nameless.prob, thresholds["x2_whole"])
        assert nameless.grade == expected  # 이미지 0.9 미만이라 도형 단독 규칙은 걸리지 않는다
        assert (nameless.prob >= caution) == (rm.GRADES.index(nameless.grade) >= 1)
        named = ngt.named_input(row, "x2_whole")
        assert tuple(rm.risk_score(named, after)) == tuple(rm.risk_score(named, old))
    # 무관한 쌍이 그 등급 이상을 받는 수가 이름 있는 입력과 같다(하한이 정해진 등급)
    distribution = ngt.unrelated_distribution(rows, old, model, after)
    for label, key in ngt.KINDS:
        item = distribution[label]
        named, new = item["이름 있는 입력(v1.3)"], item["이름 없는 입력(새 하한)"]
        assert sum(named.values()) == sum(new.values()) == item["n"]
        for level, grade in enumerate(rm.GRADE_THRESHOLD_KEYS, start=1):
            if thresholds[key][grade] is None:
                continue
            at_or_above = lambda counts: sum(counts[g] for g in rm.GRADES[level:])  # noqa: E731
            entry = calibration["종류"][label]["등급"][grade]
            assert at_or_above(new) == entry["새_하한에서_그_등급_이상"]
            if entry["사유"] == "U 에서 비율을 맞춤":
                assert at_or_above(new) == at_or_above(named)


def test_similarity_equivalents_invert_the_logit():
    model = _model()
    block = model[rm.NAMELESS_KEY]["x2_whole"]
    block["grade_thresholds"] = {"주의": 0.2, "검토 권장": 0.5, "위험": None}
    model[rm.NAMELESS_KEY]["x2_whole+x4"]["grade_thresholds"] = {"주의": 0.3, "검토 권장": 0.6,
                                                                "위험": 0.8}
    out = ngt.similarity_equivalents(model)
    assert out["이미지만"]["위험"] == {"하한": None, "상품 없음": None}
    for grade in ("주의", "검토 권장"):
        value = out["이미지만"][grade]["상품 없음"]
        prob = rm.risk_score({"x2_whole": value, "mark_type": "도형"}, model).prob
        assert prob == pytest.approx(out["이미지만"][grade]["하한"], abs=2e-3)
    for case, goods in (("상품 겹침 1.0", 1.0), ("상품 겹침 0.0", 0.0)):
        value = out["이미지+상품"]["위험"][case]
        logit = -2.05 + 2.5 * value + 1.5 * goods
        assert 1 / (1 + math.exp(-logit)) == pytest.approx(0.8, abs=2e-3)
    assert ngt.similarity_equivalents(rm.load_model()) == {}


def test_run_updates_only_thresholds_in_the_model_file(tmp_path):
    """끝까지: 합성 특징으로 2차 시도 학습 → 하한 계산 스크립트가 JSON 에 하한만 더한다(계수 불변,
    --dry-run 이면 JSON 을 쓰지 않음, 다시 돌려도 같은 값)."""
    import csv

    from scripts import train_risk_model_v14_nameless as t4n

    spec = __import__("importlib").util.spec_from_file_location(
        "v14_tests",
        __file__.replace("test_nameless_grade_thresholds", "test_train_risk_model_v14"))
    helpers = __import__("importlib").util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    features, easy = tmp_path / "pairs_features.csv", tmp_path / "pairs_features_easy.csv"
    for path, rows in ((features, helpers._trial_rows()), (easy, helpers._easy_rows())):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=helpers.COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
    trained = t4n.run(features, easy, out_dir=tmp_path / "train", model_path=tmp_path / "m.json",
                      folds=3, repeats=1, bootstrap=0, metric_bootstrap=20, n_random=50,
                      sensitivity=False, min_pattern_minority=5)
    stored = json.loads(Path(trained["모델_파일"]).read_text(encoding="utf-8"))  # 채택분 또는 후보
    path = tmp_path / "model.json"
    path.write_text(json.dumps(ngt.without_thresholds(stored), ensure_ascii=False),
                    encoding="utf-8")
    dry = ngt.run(features, easy, model_path=path, out_dir=tmp_path / "dry", write=False, folds=3,
                  repeats=1, min_pattern_minority=5)
    assert dry["JSON_갱신"] is False and dry["계수_불변"] is True
    assert "grade_thresholds" not in json.loads(path.read_text(encoding="utf-8"))[
        rm.NAMELESS_KEY]["x2_whole"]
    results = ngt.run(features, easy, model_path=path, out_dir=tmp_path / "out", folds=3,
                      repeats=1, min_pattern_minority=5)
    assert results["새_하한"] == dry["새_하한"] and results["JSON_갱신"] is True
    updated = rm.load_model(path)
    for key, thresholds in results["새_하한"].items():
        assert updated[rm.NAMELESS_KEY][key]["grade_thresholds"] == thresholds
        for field in ("features", "coefficients", "intercept"):
            assert updated[rm.NAMELESS_KEY][key][field] == stored[rm.NAMELESS_KEY][key][field]
    assert updated["patterns"] == stored["patterns"]
    assert set(results["무관한_쌍의_등급_분포"]) == {"이미지만", "이미지+상품"}
    tables = results["이름_없는_행_전후"]
    assert set(tables["표"]) == {"이름 없는 행", "도형계", "심결+cross+db"}
    assert set(tables["이름_없는_유사_쌍"]) == {"n", "전(v1.3 하한)", "후(새 하한)"}
    for sets in tables["표"].values():
        totals = {label: sum(row["n"] for row in rows_) for label, rows_ in sets.items()}
        assert totals["전(v1.3 하한)"] == totals["후(새 하한)"]
    again = ngt.run(features, easy, model_path=path, out_dir=tmp_path / "out", folds=3, repeats=1,
                    min_pattern_minority=5)
    assert again["새_하한"] == results["새_하한"]  # 하한이 이미 붙은 JSON 에 다시 돌려도 같다
    report = (tmp_path / "out" / "risk_model_v1.4_thresholds_report.md").read_text(encoding="utf-8")
    for heading in ("## 새 하한", "## 새 하한에 해당하는 이미지 유사도",
                    "## 무관한 쌍(U)의 등급 분포", "## 등급별 건수·가중 정밀도 전후"):
        assert heading in report
    # 학습 스크립트가 채택했을 때 쓴 JSON 에도 같은 하한이 붙어 있다
    if trained["채택"]["채택"]:
        assert trained["등급_하한(이름 없는 입력)"]["새_하한"] == results["새_하한"]
        for key, thresholds in results["새_하한"].items():
            assert stored[rm.NAMELESS_KEY][key]["grade_thresholds"] == thresholds
