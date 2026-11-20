"""통합 모델 v1.4 학습 스크립트 테스트 — 합성 특징 CSV 로 끝까지(모델 다운로드·실데이터 없음).
v1.3 학습 테스트(test_train_risk_model.py)와 같은 방식이고, v1.4 에서 넓힌 것(이름 없는 행·사건
가중·사진 규칙·쌍 키 묶음·짝 차이·채택 기준)을 본다."""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest
from src.model import risk_model as rm

from scripts import train_risk_model as tr
from scripts import train_risk_model_v14 as t4

TYPES = ("문자", "도형", "결합-문자요부", "결합-도형요부", "문자", "문자")
COLUMNS = [
    "심판번호", "종류", "상대번호", "최종라벨", "표장라벨", "상표유형", "상표유형_출처", "이름A",
    "이름B", "이름B_출처", "pair_source", "회차", "쌍키", "보강", "사진A", "사진B", "x1_d",
    "x2_text_d", "x3_d", "x2_whole", "x4", "has_names", "has_meaning_a", "has_meaning_b",
    "has_goods", "has_image", "has_distinctive_part_a", "has_distinctive_part_b",
]


def _trial_rows(n: int = 260, seed: int = 0) -> list[dict]:
    """이름 축(이름 있는 행)과 이미지 축(도형계·이름 없는 행)이 라벨과 함께 움직이는 합성 행.
    6행마다 이름 없음, 9행마다 이미지 없음, 13행마다 사진, 한 사건(BIG)은 8행."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        similar = i % 5 not in (0, 3)
        base = 0.7 if similar else 0.3
        named = i % 6 != 0
        image = i % 9 != 0
        kind = TYPES[i % 6] if named else ("도형", "결합-도형요부")[i % 2]
        row = {column: "" for column in COLUMNS}
        row.update({
            "심판번호": "BIG" if 40 <= i < 48 else f"T{i // 2}", "상대번호": str(i % 2),
            "종류": "무효", "최종라벨": "유사" if similar else "비유사",
            "표장라벨": "유사" if similar else "비유사", "상표유형": kind, "상표유형_출처": "확정",
            "이름A": "a", "이름B": "b" if named else "", "이름B_출처": "kipris" if named else "",
            "pair_source": "trial", "회차": "1" if i < n // 2 else "2",
            "쌍키": "같은||쌍" if i in (10, 100) else "", "보강": "1" if i % 17 == 0 else "",
            "x1_d": f"{float(np.clip(base + rng.normal(0, 0.15), 0, 1)):.4f}" if named else "",
            "x2_text_d": f"{float(np.clip(base + rng.normal(0, 0.2), 0, 1)):.4f}" if named else "",
            "x3_d": f"{float(np.clip(base + rng.normal(0, 0.3), 0, 1)):.4f}" if named else "",
            "x2_whole": f"{float(np.clip(base + rng.normal(0, 0.15), 0, 1)):.4f}" if image else "",
            "x4": f"{float(np.clip(base + rng.normal(0, 0.3), 0, 1)):.4f}" if i % 4 else "",
            "has_names": int(named), "has_meaning_a": 1 if i % 7 else 0, "has_meaning_b": 1,
            "has_goods": 1 if i % 4 else 0, "has_image": int(image),
            "has_distinctive_part_a": 1, "has_distinctive_part_b": 1 if i % 8 else 0,
        })
        if image:
            row["사진A"], row["사진B"] = "0", "1" if i % 13 == 0 else "0"
        rows.append(row)
    return rows


def _easy_rows(n: int = 160, seed: int = 1) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        source = "cross" if i % 2 == 0 else "db"
        image = i % 5 != 0
        row = {column: "" for column in COLUMNS}
        row.update({
            "심판번호": f"{source}:T{i % 40}|X{i}", "최종라벨": "비유사", "표장라벨": "비유사",
            "상표유형": "", "이름A": "a", "이름B": "c", "이름B_출처": source,
            "pair_source": source,
            "x1_d": f"{float(np.clip(0.2 + rng.normal(0, 0.08), 0, 1)):.4f}",
            "x2_text_d": f"{float(np.clip(0.1 + rng.normal(0, 0.08), 0, 1)):.4f}",
            "x3_d": "0.0000",
            "x2_whole": f"{float(np.clip(0.35 + rng.normal(0, 0.1), 0, 1)):.4f}" if image else "",
            "x4": f"{0.0 if i % 3 else 0.2:.4f}" if i % 4 else "",
            "has_names": 1, "has_meaning_a": 0, "has_meaning_b": 1,
            "has_goods": 1 if i % 4 else 0, "has_image": int(image),
            "has_distinctive_part_a": 1, "has_distinctive_part_b": 1,
        })
        if image:
            row["사진A"], row["사진B"] = "1" if i % 20 == 1 else "0", "0"
        rows.append(row)
    return rows


def _write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def data(tmp_path):
    features, easy = tmp_path / "pairs_features.csv", tmp_path / "pairs_features_easy.csv"
    _write(features, _trial_rows())
    _write(easy, _easy_rows())
    return features, easy


def test_weighted_metrics_match_unweighted_and_axes_benchmark():
    from scripts import axes_benchmark as ab

    rng = np.random.default_rng(3)
    scores = np.round(rng.random(120), 2)  # 동점 포함
    labels = (scores + rng.normal(0, 0.3, 120) > 0.5).astype(float)
    ones = np.ones(120)
    assert t4.weighted_auc(scores, labels, ones) == pytest.approx(tr.roc_auc(scores, labels))
    weights = rng.choice([1.0, 0.5, 0.075], 120)
    assert t4.weighted_auc(scores, labels, weights) == pytest.approx(
        ab.weighted_auc(scores, labels.astype(int), weights))
    # 가중치 2 는 그 행을 두 번 넣은 것과 같다
    doubled = np.where(np.arange(120) < 30, 2.0, 1.0)
    repeat = np.concatenate([np.arange(120), np.arange(30)])
    assert t4.weighted_auc(scores, labels, doubled) == pytest.approx(
        tr.roc_auc(scores[repeat], labels[repeat]))
    assert t4.weighted_brier(scores, labels, doubled) == pytest.approx(
        float(np.mean((scores[repeat] - labels[repeat]) ** 2)))
    assert t4.weighted_auc(scores, np.ones(120), ones) is None
    assert t4.weighted_auc(np.zeros(0), np.zeros(0), np.zeros(0)) is None
    assert t4.weighted_brier(scores, labels, np.zeros(120)) is None


def test_case_weights_and_groups_merge_cases_sharing_a_pair_key():
    rows = [
        {"pair_source": "trial", "심판번호": "A", "쌍키": "k1"},
        {"pair_source": "trial", "심판번호": "A", "쌍키": ""},
        {"pair_source": "trial", "심판번호": "B", "쌍키": "k1"},  # A 와 같은 표장 쌍 → 한 묶음
        {"pair_source": "trial", "심판번호": "C", "쌍키": "k2"},
        {"pair_source": "trial", "심판번호": "D", "쌍키": "k2"},
        {"pair_source": "trial", "심판번호": "D", "쌍키": "k3"},
        {"pair_source": "trial", "심판번호": "E", "쌍키": "k3"},  # C–D–E 가 사슬로 한 묶음
        {"pair_source": "trial", "심판번호": "F", "쌍키": ""},
        {"pair_source": "cross", "심판번호": "cross:B|F", "쌍키": ""},  # 이름 A 쪽 사건의 묶음
        {"pair_source": "db", "심판번호": "db:1|2", "쌍키": ""},
    ] + [{"pair_source": "trial", "심판번호": "G", "쌍키": ""} for _ in range(6)]
    groups = t4.group_ids(rows)
    assert groups[0] == groups[1] == groups[2] == groups[8]
    assert groups[3] == groups[4] == groups[5] == groups[6] != groups[0]
    assert groups[7] not in (groups[0], groups[3]) and groups[9] == "db:1|2"
    assert len(set(groups)) == 5
    weights = t4.case_weights(rows)
    assert list(weights[:8]) == [1.0] * 8  # 행 수 ≤ 3 인 사건
    assert weights[8] == weights[9] == 1.0  # 쉬운 음성
    assert list(weights[10:]) == pytest.approx([0.5] * 6)  # 6행 사건: 3/6
    assert list(t4.case_weights(rows, cap=None)) == [1.0] * 16


def test_load_dataset_photo_rule_exclusion_and_sensitivity_options(data):
    features, easy = data
    base = t4.load_dataset(features, easy)
    summary = base.summary
    assert summary["심결_행(특징 파일)"] == 260
    assert summary["심결_행(학습)"] + summary["이름도_이미지도_없어_제외"]["n"] == 260
    # 이름 없는 행(6의 배수) 가운데 이미지가 없거나(18의 배수) 사진이라 이미지를 잃은(78의 배수) 행
    assert summary["이름도_이미지도_없어_제외"]["n"] == len(
        [i for i in range(260) if i % 6 == 0 and (i % 9 == 0 or i % 13 == 0)])
    assert summary["이름도_이미지도_없어_제외"]["사진_규칙으로_이미지를_잃은_행"] == len(
        [i for i in range(260) if i % 6 == 0 and i % 9 != 0 and i % 13 == 0])
    photo_trial = [i for i in range(260) if i % 9 != 0 and i % 13 == 0]
    assert summary["사진_규칙"]["사진_낀_쌍"]["trial"] == len(photo_trial)
    assert summary["사진_규칙"]["이미지_있는_쌍"]["trial"] == len(
        [i for i in range(260) if i % 9 != 0])
    photo_rows = [r for r in base.rows + base.excluded if t4.has_photo(r)]
    assert photo_rows and all(np.isnan(r["x2_whole"]) for r in photo_rows)
    assert all(not np.isnan(r[t4.RAW_IMAGE]) for r in photo_rows)  # 원래 값은 따로 남는다
    big = [r for r in base.rows if r["심판번호"] == "BIG"]
    assert all(r["_w"] == pytest.approx(3 / 8) for r in big) and len(
        [r for r in big + base.excluded if r["심판번호"] == "BIG"]) == 8
    # 같은 쌍키(행 10·100)의 사건 T5·T50 은 한 묶음
    group_of = {r["심판번호"]: r["_group"] for r in base.rows if r["pair_source"] == "trial"}
    assert group_of["T5"] == group_of["T50"] != group_of["T6"]
    assert summary["사건_가중"]["묶음"] == summary["사건_가중"]["사건"] - 1
    assert summary["쉬운_음성"] == {"cross": 80, "db": 80}
    # 민감도 옵션
    raw = t4.load_dataset(features, easy, photo_rule=False)
    assert raw.summary["사진_규칙"]["적용"] is False
    assert not any(np.isnan(r["x2_whole"]) for r in raw.rows if t4.has_photo(r))
    assert raw.summary["이름도_이미지도_없어_제외"]["n"] < summary["이름도_이미지도_없어_제외"]["n"]
    without_big = t4.load_dataset(features, easy, drop_cases=("BIG",))
    assert without_big.summary["민감도_제외"]["사건"] == 8
    assert not any(r["심판번호"] == "BIG" for r in without_big.rows)
    without_augmented = t4.load_dataset(features, easy, drop_augmented=True)
    assert without_augmented.summary["민감도_제외"]["보강"] == len(
        [i for i in range(260) if i % 17 == 0])
    # 이름 없는 행은 런타임(엔진)이 넘기는 꼴로 — 이름 축 None·요부 플래그 True
    nameless = next(r for r in base.rows if r["pair_source"] == "trial" and not tr.has_name(r))
    inputs = t4.service_features(nameless)
    assert inputs["x1_d"] is None and inputs["x2_text_d"] is None and inputs["x3_d"] is None
    assert inputs["has_distinctive_part_a"] and inputs["has_distinctive_part_b"]
    assert inputs["x2_whole"] == pytest.approx(nameless["x2_whole"])


def test_design_blocks_and_constraints(data):
    features, easy = data
    rows = t4.load_dataset(features, easy).rows
    a = t4.arrays(rows)
    design = t4.Design(rows)
    assert design.ids == ["base", "x2_whole", "x4", "x2_whole+x4", "noname:x2_whole",
                          "noname:x2_whole+x4"]
    assert design.names["noname:x2_whole"] == ["x2_whole", "x2_whole×도형계"]
    assert design.names["noname:x2_whole+x4"] == ["x2_whole", "x2_whole×도형계", "x4"]
    image = tr.observed(rows, "x2_whole")
    goods = tr.observed(rows, "x4")
    # 이름 없는 집합은 그 축이 관측된 모든 행(이름 있는 행도 이름을 가리고 참여)
    assert np.array_equal(design.mask["noname:x2_whole"], image)
    assert np.array_equal(design.mask["noname:x2_whole+x4"], image & goods)
    # 이름 있는 집합은 이름 있는 행만(v1.3 과 같음)
    assert np.array_equal(design.mask["x2_whole"], image & (a["named"] | a["easy"]))
    assert not design.mask["base"][~a["named"] & a["trial"]].any()
    nameless_rows = a["trial"] & ~a["named"]
    assert set(design.own[nameless_rows]) <= {"noname:x2_whole", "noname:x2_whole+x4"}
    assert not any(block.startswith("noname:") for block in design.own[a["named"]])
    old = t4.Design(rows, structure="v1.3")
    assert old.ids == ["base", "x2_whole", "x4", "x2_whole+x4"]
    assert set(old.own[nameless_rows]) <= {"x2_whole", "x2_whole+x4"}  # 런타임처럼 이름 항 0
    floors, name_floors, detail = t4.floors_for(rows, a["y"], a["easy"])
    assert set(floors) == {"x2_whole", "x4"} and set(name_floors) == {"x1_d", "x2_text_d", "x3_d"}
    assert name_floors["x3_d"] == 0.0 and 0.1 < name_floors["x1_d"] < 0.3
    assert detail["x1_d"]["근거"] == "쉬운 음성 비유사 평균"
    constraints = t4.build_constraints(design, floors, name_floors)
    kinds = {kind: sum(1 for c in constraints if c.kind == kind)
             for kind in {c.kind for c in constraints}}
    assert kinds["결합(이름)"] == 8 + 16  # 유형 2 × 이미지 2 × 요부 2 (+ 상품 2)
    assert kinds["결합(이름 없음, 축)"] == 4  # 이미지만 → 이미지+상품: 유형 2 × 이미지 2
    assert kinds["결합(축)"] == 32 + 32 + 64 + 64 == 192 and kinds["단조"] > 0  # v1.3 과 같은 수
    assert all(c.row.shape == (design.size,) for c in constraints)
    plain = t4.build_constraints(old, floors, name_floors)
    assert {c.kind for c in plain} == {"단조", "결합(축)"}


def test_joint_fit_satisfies_constraints_and_kkt(data):
    features, easy = data
    rows = t4.load_dataset(features, easy).rows
    result = t4.train_once(rows, folds=3, repeats=1, min_minority=5)
    design, final = result["design"], result["final"]
    assert final.success and final.kkt_residual <= t4.KKT_TOLERANCE and final.min_slack >= -1e-6
    assert result["cv"]["수렴_실패"] == 0 and result["cv"]["겹_수"] == 3
    assert np.all((result["cv"]["own"] >= 0) & (result["cv"]["own"] <= 1))
    monotone = t4.monotonicity(design, final.blocks, rows, result["floors"],
                               result["name_floors"])
    assert {"noname:x2_whole → x2_whole (이름)", "noname:x2_whole+x4 → x2_whole+x4 (이름)",
            "noname:x2_whole → noname:x2_whole+x4 (x4)", "base → x2_whole (x2_whole)"} <= set(
        monotone)
    assert all(block["하한_이상"]["위반(p 내려감)"] == 0 for block in monotone.values())
    active = t4.active_constraints(result["constraints"], final.theta)
    assert active["경계_수"] == sum(active["종류별"].values()) <= active["제약_수"]
    # 반올림한 계수 집합도 런타임 검증(단조·결합)을 통과한다
    named, nameless = t4.rounded_model_blocks(design, final.blocks, result["floors"],
                                              result["name_floors"])
    probe = {"patterns": named, rm.NAMELESS_KEY: nameless, "pattern_axes": list(design.axes),
             "coupling": {"floors": result["floors"], "name_floors": result["name_floors"]}}
    assert rm.coupling_violations(probe) == []
    # 순차 적합(사후 진단): 이름 있는 패턴은 이름 없는 패턴 없이 적합한 값과 같다
    sequential = t4.train_once(rows, folds=3, repeats=1, min_minority=5, mode="sequential")
    old = t4.train_once(rows, folds=3, repeats=1, min_minority=5, structure="v1.3")
    for key in design.named_keys:
        np.testing.assert_allclose(sequential["final"].blocks[key][0], old["final"].blocks[key][0],
                                   atol=2e-3)
    loose = t4.train_once(rows, folds=3, repeats=1, min_minority=5, name_coupling=False)
    assert not any(c.kind == "결합(이름)" for c in loose["constraints"])
    with pytest.raises(ValueError, match="모르는 적합 방식"):
        t4.train_once(rows, folds=3, repeats=1, min_minority=5, mode="other")


def test_nameless_patterns_need_minority_and_kkt_residual():
    rng = np.random.default_rng(0)

    def row(named: bool, similar: bool, image: bool, goods: bool) -> dict:
        return {"pair_source": "trial", "심판번호": f"N{rng.integers(1e9)}", "최종라벨":
                "유사" if similar else "비유사", "상표유형": "도형",
                "x1_d": 0.5 if named else np.nan, "x2_text_d": 0.5 if named else np.nan,
                "x3_d": 0.0 if named else np.nan, "x2_whole": 0.5 if image else np.nan,
                "x4": 0.5 if goods else np.nan, "_w": 1.0, "_group": "g",
                "has_distinctive_part_a": 1, "has_distinctive_part_b": 1}

    rows = ([row(False, True, True, i < 3) for i in range(12)]
            + [row(False, False, True, i < 20) for i in range(30)])
    a = t4.arrays(rows)
    keys, detail = t4.choose_nameless_keys(rows, a, 10)
    assert keys == ("x2_whole",)  # 이미지+상품은 유사 3 < 10
    assert detail["패턴"]["noname:x2_whole"] == {"n": 42, "유사": 12, "비유사": 30, "가능": True}
    assert detail["패턴"]["noname:x2_whole+x4"]["가능"] is False
    assert t4.choose_nameless_keys(rows, a, 13)[0] == ()
    assert t4.choose_nameless_keys(rows, a, 3)[0] == t4.NAMELESS_KEYS
    # KKT 잔차: 경계에 붙은 제약의 음이 아닌 결합으로 기울기를 설명하면 0
    G = np.asarray([[1.0, 0.0], [0.0, 1.0]])
    assert t4._kkt_residual(np.asarray([2.0, 0.0]), G, np.asarray([0.0, 5.0])) == pytest.approx(0)
    assert t4._kkt_residual(np.asarray([-2.0, 0.0]), G, np.asarray([0.0, 5.0])) > 0.5  # λ < 0
    assert t4._kkt_residual(np.asarray([0.0, 3.0]), G, np.asarray([0.0, 5.0])) > 0.5  # 안 붙은 제약
    assert t4._kkt_residual(np.zeros(2), G, np.asarray([1.0, 1.0])) == 0.0


def test_bootstrap_paired_difference_and_thresholds():
    rng = np.random.default_rng(1)
    n = 200
    y = (rng.random(n) < 0.5).astype(float)
    good = np.clip(0.5 + (y - 0.5) * 0.5 + rng.normal(0, 0.15, n), 0.01, 0.99)
    bad = np.clip(0.5 + rng.normal(0, 0.15, n), 0.01, 0.99)
    weights = np.ones(n)
    mask = np.ones(n, dtype=bool)
    groups = np.asarray([f"g{i // 2}" for i in range(n)])
    boot = t4.Bootstrap(groups, 200, seed=0)
    again = t4.Bootstrap(groups, 200, seed=0)
    assert all(np.array_equal(a, b) for a, b in zip(boot.draws, again.draws))  # 같은 묶음을 뽑는다
    assert all(draw[0] == draw[1] for draw in boot.draws)  # 묶음 단위(같은 묶음은 같은 횟수)
    diff = t4.paired_difference(good, bad, y, weights, mask, boot)
    assert diff["auc"]["차이"] > 0.2 and diff["auc"]["ci95"][0] > 0  # 새 모델이 낫다 → 양수
    assert diff["brier"]["차이"] > 0 and diff["brier"]["ci95"][0] > 0  # Brier 는 옛 − 새
    same = t4.paired_difference(good, good, y, weights, mask, boot)
    assert same["auc"] == {"차이": 0.0, "ci95": [0.0, 0.0]}
    block = t4.metric_block(good, y, weights, mask, boot)
    assert block["auc_가중_ci95"][0] <= block["auc_가중"] <= block["auc_가중_ci95"][1]
    assert block["auc"] == block["auc_가중"] and block["n"] == n
    # 채택 기준 ①: 짝 차이 CI 상한이 0 미만이면 멈춘다
    table = {"1차": {"짝_차이": t4.paired_difference(bad, good, y, weights, mask, boot)},
             "전체": {"짝_차이": same}}
    fine = {key: True for key in tr.CONDITIONS}
    rates = {key: 1.0 for key in tr.CONDITIONS}
    stopped = t4.adoption_check(table, fine, rates, {}, [])
    assert stopped["채택"] is False and stopped["판정"].startswith("멈춤")
    assert [m["지표"] for m in stopped["①_CI_상한_0_미만"]] == ["가중 AUC — 1차"]
    passed = t4.adoption_check({"전체": {"짝_차이": same}}, fine, rates, {}, [])
    assert passed["채택"] is True and passed["판정"] == "v1.4 채택"
    # ②: v1.3 이 성립한 조건이 불성립으로 바뀌거나 부트스트랩 성립 비율이 0.10 넘게 낮아지면 멈춘다
    worse = t4.adoption_check({}, {**fine, tr.CONDITIONS[0]: False}, rates, {}, [])
    assert [c["조건"] for c in worse["②_나빠진_판례_조건"]] == [tr.CONDITIONS[0]]
    dropped = t4.adoption_check({}, fine, {**rates, tr.CONDITIONS[3]: 0.85}, {}, [])
    assert [c["조건"] for c in dropped["②_나빠진_판례_조건"]] == [tr.CONDITIONS[3]]
    kept = t4.adoption_check({}, {**fine, tr.CONDITIONS[1]: False},
                             {**rates, tr.CONDITIONS[1]: 0.4, tr.CONDITIONS[3]: 0.95}, {}, [])
    assert kept["채택"] is True  # (ii) 는 v1.3 에서도 불성립(0.44) — 0.4 는 0.10 안
    # ③: 하한 이상 행에서 로짓이 내려가거나 런타임 결합 검증 위반
    broken = t4.adoption_check({}, fine, rates, {"x": {"하한_이상": {"위반(p 내려감)": 2}}}, [])
    assert broken["채택"] is False and broken["③_단조성"]["학습_행_위반"] == 2
    assert t4.adoption_check({}, fine, rates, {}, ["위반"])["채택"] is False
    # 등급 하한(사건 가중): 가중치를 바꾸면 정밀도 계산이 달라진다
    prob = np.concatenate([np.full(40, 0.9), np.full(60, 0.4), np.full(100, 0.05)])
    label = np.concatenate([np.ones(34), np.zeros(6), np.ones(20), np.zeros(40), np.zeros(100)])
    grades = t4.grade_thresholds_weighted(prob, label, np.ones(200))
    assert grades["thresholds"]["위험"] == 0.9 and grades["thresholds"]["검토 권장"] == 0.4
    assert grades["thresholds"]["주의"] == 0.2
    risk_row = next(row for row in grades["등급별"] if row["등급"] == "위험")
    assert risk_row["정밀도_가중"] == pytest.approx(0.85) and risk_row["n"] == 40
    down = np.ones(200)
    down[:34] = 0.1  # 위험 구간의 유사 34행이 한 사건이라 가중이 낮다 → 정밀도 0.8 미달
    weighted = t4.grade_thresholds_weighted(prob, label, down)
    assert weighted["thresholds"]["위험"] != 0.9 and "가중 정밀도 0.8 에 이르는 p 가 없음" in (
        weighted["기준"][0])
    point = t4.precision_threshold_weighted(prob, label, np.ones(200), target=0.7,
                                            min_support=10)
    assert point["threshold"] == 0.9 and point["precision"] == pytest.approx(0.85)
    assert t4.precision_threshold_weighted(prob, label, np.ones(200), target=0.99,
                                           min_support=10)["threshold"] is None


def test_run_end_to_end_writes_candidate_unless_adopted(data, tmp_path):
    features, easy = data
    out_dir = tmp_path / "out"
    model_path = tmp_path / "model" / "risk_model_v1.4.json"
    results = t4.run(features, easy, out_dir=out_dir, model_path=model_path, folds=3, repeats=1,
                     bootstrap=4, metric_bootstrap=30, seed=0, min_pattern_minority=5)
    assert results["구조"] == "v1.4" and results["적합_방식"] == "joint"
    assert set(results["계수_집합"]) == {"base", "x2_whole", "x4", "x2_whole+x4",
                                      "noname:x2_whole", "noname:x2_whole+x4"}
    first = results["평가_1_v1.3을_2차에_그대로"]
    assert set(first) == {"이름 없는 행 포함(247행 전체)", "이름 없는 행 제외", "이름 없는 행만"}
    assert first["이름 없는 행 포함(247행 전체)"]["n"] == 130  # 2차 행 전부(제외된 행 포함)
    table = results["평가_2_OOF"]
    assert {"전체", "1차", "2차", "문자계", "도형계", "이름 없는 행", "심결+cross+db"} <= set(table)
    for entry in table.values():
        assert {"v1.3 그대로", "v1.4", "v1.3 구조 재학습", "짝_차이",
                "짝_차이_구조_재학습_대비"} <= set(entry)
        assert set(entry["짝_차이"]) == {"auc", "brier"}
    assert set(results["평가_3_판례_조건"]["v1.4"]) == set(tr.CONDITIONS)
    assert set(results["평가_4_계수"]) == set(results["계수_집합"])
    assert results["평가_4_계수"]["noname:x2_whole"]["x2_whole"]["v1.3"] is None
    assert results["평가_4_계수"]["x2_whole"]["x2_whole"]["v1.3"] is not None
    assert set(results["평가_5_등급"]["v1.4_하한"]) == {"주의", "검토 권장", "위험"}
    standalone = results["평가_5_단독_임계값"]["v1.4"]
    assert standalone["thresholds"]["x2_whole"] is None and standalone["thresholds"]["x4"] is None
    assert results["평가_5_단독_임계값"]["도형_단독_규칙_τ"] == 0.9
    image_only = results["평가_6_이미지만"]
    assert [row["x2_whole"] for row in image_only[:4]] == [0.5, 0.7, 0.9, 1.0]
    assert all(row["v1.4"]["패턴"] == "noname:x2_whole" and row["v1.3"]["패턴"] == "x2_whole"
               for row in image_only)
    assert all(block["하한_이상"]["위반(p 내려감)"] == 0
               for block in results["평가_7_단조성"].values())
    assert [row["조건"] for row in results["평가_8_민감도"]] == [
        "주 실행", "사건 2025101001193 제외", "사진 규칙 없음", "2등급에서 살아난 행 제외"]
    assert [row["변형"] for row in results["사후_진단"]] == [
        "순차 적합", "이름 결합 제약 없음", "v1.3 구조 재학습"]
    adoption = results["채택"]
    assert adoption["기준"] == t4.ADOPTION and adoption["③_단조성"]["학습_행_위반"] == 0
    assert set(adoption["원인_진단"]) == {"noname:x2_whole", "noname:x2_whole+x4"}
    written = out_dir / "risk_model_v1.4_candidate.json"
    if adoption["채택"]:
        assert results["모델_파일"] == str(model_path) and model_path.exists()
        assert not written.exists()
    else:  # 채택 기준 미달이면 배포 경로에는 쓰지 않는다
        assert results["모델_파일"] == str(written) and not model_path.exists()
    model = rm.load_model(results["모델_파일"])
    assert model["version"] == "risk_model_v1.4" and rm.coupling_violations(model) == []
    assert sorted(model[rm.NAMELESS_KEY]) == ["x2_whole", "x2_whole+x4"]
    assert set(model["coupling"]["name_floors"]) == {"x1_d", "x2_text_d", "x3_d"}
    assert model["meta"]["adoption"]["채택"] is adoption["채택"]
    assert model["meta"]["case_weight"]["rule"] == "w = min(1, 3 / 그 사건의 행 수)"
    assert model["meta"]["photo"]["적용"] is True and "grade_precision" in model["meta"]
    assert model["meta"]["n_trial"] == results["데이터"]["심결_행(학습)"]
    assert model["meta"]["n_nameless"] == results["데이터"]["이름_없는_행"]["n"]
    nameless = rm.risk_score({"x2_whole": 0.9, "mark_type": "도형"}, model)
    assert nameless.pattern == "noname:x2_whole" and nameless.figure_caveat
    assert rm.risk_score({"x1_d": 0.9, "x2_text_d": 0.9, "x2_whole": 0.9, "mark_type": "문자"},
                         model).pattern == "x2_whole"
    report = (out_dir / "risk_model_v1.4_report.md").read_text(encoding="utf-8")
    for heading in ("## 채택 판단", "## 평가 1", "## 평가 2", "## 평가 3", "## 평가 4",
                    "## 평가 5", "## 평가 6", "## 평가 7", "## 평가 8", "## 사후 진단"):
        assert heading in report
    saved = json.loads((out_dir / "risk_model_v1.4_results.json").read_text(encoding="utf-8"))
    assert saved["채택"]["채택"] is adoption["채택"]
    # --force-model: 기준에 못 미쳐도 지정 경로에 쓴다(사람이 채택을 결정했을 때)
    forced = t4.run(features, easy, out_dir=tmp_path / "forced", model_path=model_path, folds=3,
                    repeats=1, bootstrap=0, metric_bootstrap=10, sensitivity=False,
                    diagnostics=False, force_model=True, min_pattern_minority=5)
    assert forced["모델_파일"] == str(model_path) and model_path.exists()
    assert "평가_8_민감도" not in forced and "사후_진단" not in forced


def test_run_v13_structure_has_no_nameless_patterns(data, tmp_path):
    """폴백 구조(이름 있는 행만): 이름 없는 계수 집합을 만들지 않고, 이름 없는 입력은 런타임이
    종전대로 이름 있는 패턴에 이름 항 0 으로 계산한다."""
    features, easy = data
    results = t4.run(features, easy, out_dir=tmp_path / "out", model_path=tmp_path / "m.json",
                     structure="v1.3", folds=3, repeats=1, bootstrap=2, metric_bootstrap=10,
                     min_pattern_minority=5, force_model=True)
    assert set(results["계수_집합"]) == {"base", "x2_whole", "x4", "x2_whole+x4"}
    assert "평가_8_민감도" not in results and "사후_진단" not in results
    assert results["채택"]["원인_진단"] == {}
    model = rm.load_model(tmp_path / "m.json")
    assert rm.NAMELESS_KEY not in model and "name_floors" not in model["coupling"]
    assert model["meta"]["structure"] == "이름 있는 행만(v1.3 구조)"
    assert rm.risk_score({"x2_whole": 0.9, "mark_type": "도형"}, model).pattern == "x2_whole"
    assert rm.coupling_violations(model) == []


# ---- 2차 시도: 이름 있는 4벌은 v1.3 그대로, 이름 없는 2벌만 학습 ------------------------------

from scripts import train_risk_model_v14_nameless as t4n  # noqa: E402


def test_attempt2_constraints_use_same_name_and_keep_named_blocks_fixed(data):
    features, easy = data
    model_old = rm.load_model(rm.V13_MODEL_PATH)
    rows = t4.load_dataset(features, easy).rows
    a = t4.arrays(rows)
    design = t4.Design(rows)
    fixed = t4n.fixed_named(design, model_old)
    assert set(fixed) == {"base", "x2_whole", "x4", "x2_whole+x4"}
    for key, (coef, intercept) in fixed.items():  # v1.3 JSON 의 값 그대로
        block = model_old["patterns"][key]
        assert intercept == block["intercept"]
        assert list(coef) == [block["coefficients"][name] for name in design.names[key]]
    broken = {**model_old, "patterns": {**model_old["patterns"], "base": {
        **model_old["patterns"]["base"], "features": ["x1_d"]}}}
    with pytest.raises(ValueError, match="입력 항이 설계와 다릅니다"):
        t4n.fixed_named(design, broken)
    floors = model_old["coupling"]["floors"]
    constraints = t4n.build_constraints(design, floors)
    kinds = {kind: sum(1 for c in constraints if c.kind == kind)
             for kind in {c.kind for c in constraints}}
    # 같은 이름: (유형 2 × 이미지 2 [× 상품 2]) × 요부 2 = 8 + 16, 이름 하한 결합(1차 시도)은 없다
    assert kinds == {"단조": 5, "결합(이름 없음, 축)": 4, "결합(같은 이름)": 24}
    labels = [c.label for c in constraints if c.kind == "결합(같은 이름)"]
    assert all("(같은 이름)" in label and "요부없음=" in label for label in labels)
    # 이름 있는 블록의 매개변수에는 단조·축 결합 제약이 걸리지 않는다(같은 이름 제약에만 상수로)
    named_columns = np.zeros(design.size, dtype=bool)
    for key in design.named_keys:
        start = design.offset[key]
        named_columns[start:start + len(design.names[key]) + 1] = True
    for constraint in constraints:
        touches = bool(np.abs(constraint.row[named_columns]).sum() > 0)
        assert touches == (constraint.kind == "결합(같은 이름)")
    result = t4n.fit(design, a, np.arange(len(rows)), constraints, fixed)
    assert result.success and result.min_slack >= -1e-6
    for key, (coef, intercept) in fixed.items():  # 적합 뒤에도 이름 있는 4벌은 그대로
        np.testing.assert_array_equal(result.blocks[key][0], coef)
        assert result.blocks[key][1] == intercept
    # 이름 없는 집합은 같은 이름을 더한 v1.3 로짓을 넘지 않는다(모든 꼭짓점)
    theta = result.theta
    assert min(float(c.row @ theta) for c in constraints) >= -1e-6


def test_attempt2_random_inputs_and_identity_check():
    inputs = t4n.random_inputs(500, seed=3)
    assert inputs == t4n.random_inputs(500, seed=3) and inputs != t4n.random_inputs(500, seed=4)
    assert all(f["x1_d"] is not None or f["x2_text_d"] is not None for f in inputs)  # 이름 있음
    assert any(f["x1_d"] is None for f in inputs) and any(f["x2_whole"] is None for f in inputs)
    assert any(f["x4"] is None for f in inputs) and len({f["mark_type"] for f in inputs}) == 6
    model = rm.load_model(rm.V13_MODEL_PATH)
    assert t4n.count_differences(inputs, model, model) == 0
    shifted = {**model, "patterns": {key: {**block, "intercept": block["intercept"] + 1e-4}
                                     for key, block in model["patterns"].items()}}
    assert t4n.count_differences(inputs, shifted, model) == len(inputs)  # 아주 작은 차이도 센다


def test_attempt2_adoption_rules():
    ok_identity = {"통과": True, "무작위_이름_있는_입력": {"n": 10, "차이": 0}}
    ok_monotone = {"통과": True, "위반_합계": {"축_결합": 0, "같은_이름": 0},
                   "런타임_결합_검증_위반": []}

    def table(brier, auc, mixed):
        return {"이름 없는 행": {t4n.NEW: {"n": 75}, "짝_차이_brier": {"차이": brier[0],
                                                                  "ci95": list(brier[1:])},
                             "짝_차이_auc": {"차이": auc[0], "ci95": list(auc[1:])}},
                "심결+cross+db": {"짝_차이_auc": {"차이": mixed[0], "ci95": list(mixed[1:])}}}

    good = table((-0.3, -0.4, -0.2), (0.03, -0.04, 0.09), (0.05, 0.02, 0.08))
    passed = t4n.adoption_check(ok_identity, good, ok_monotone)
    assert passed["채택"] is True and passed["판정"] == "v1.4 채택"
    assert all(item["통과"] for item in passed["판정표"].values())
    assert passed["기준"] == t4n.ADOPTION and set(passed["판정표"]) == {"①", "②", "③", "④"}

    def verdict(identity=ok_identity, tab=good, monotone=ok_monotone):
        result = t4n.adoption_check(identity, tab, monotone)
        return result["채택"], [key for key, item in result["판정표"].items() if not item["통과"]]

    assert verdict(identity={"통과": False}) == (False, ["①"])
    # ② Brier 짝 차이(v1.4 − v1.3) CI 상한이 0 이상이면 미달
    assert verdict(tab=table((-0.1, -0.2, 0.0), (0.03, -0.04, 0.09), (0.05, 0.02, 0.08))) == (
        False, ["②"])
    # ② AUC 짝 차이 CI 상한이 0 미만이면(유의하게 나빠짐) 미달 — 0 을 걸치면 통과
    assert verdict(tab=table((-0.3, -0.4, -0.2), (-0.1, -0.2, -0.01), (0.05, 0.02, 0.08))) == (
        False, ["②"])
    assert verdict(tab=table((-0.3, -0.4, -0.2), (-0.05, -0.2, 0.0), (0.05, 0.02, 0.08)))[0]
    # ③ 쉬운 음성 섞은 AUC 짝 차이 CI 하한이 0 이하면 미달
    assert verdict(tab=table((-0.3, -0.4, -0.2), (0.03, -0.04, 0.09), (0.05, 0.0, 0.08))) == (
        False, ["③"])
    assert verdict(monotone={**ok_monotone, "통과": False}) == (False, ["④"])
    failed = t4n.adoption_check({"통과": False}, {}, {"통과": False})
    assert failed["채택"] is False and failed["판정"].startswith("v1.3 유지로 확정")
    assert [k for k, item in failed["판정표"].items() if not item["통과"]] == ["①", "②", "③", "④"]
    # Brier 부호 뒤집기: t4.paired_difference 는 옛 − 새, 기준은 새 − 옛
    assert t4n.new_minus_old({"차이": 0.3, "ci95": [0.2, 0.4]}) == {"차이": -0.3,
                                                                  "ci95": [-0.4, -0.2]}
    assert t4n.new_minus_old({"차이": None, "ci95": [None, None]})["차이"] is None


def test_attempt2_run_end_to_end_copies_v13_and_adds_nameless_blocks(data, tmp_path):
    features, easy = data
    out_dir = tmp_path / "out"
    model_path = tmp_path / "model" / "risk_model_v1.4.json"
    results = t4n.run(features, easy, out_dir=out_dir, model_path=model_path, folds=3, repeats=1,
                      bootstrap=4, metric_bootstrap=30, seed=0, n_random=300,
                      min_pattern_minority=5)
    model_old = rm.load_model(rm.V13_MODEL_PATH)
    adoption = results["채택"]
    assert set(adoption["판정표"]) == {"①", "②", "③", "④"} and adoption["기준"] == t4n.ADOPTION
    # ① 이름 있는 입력의 출력은 v1.3 과 같다(구조상 언제나) · ④ 단조성도 제약이 보장한다
    assert adoption["판정표"]["①"]["통과"] is True and adoption["판정표"]["④"]["통과"] is True
    identity = adoption["판정표"]["①"]["근거"]
    assert identity["무작위_이름_있는_입력"] == {"n": 300, "차이": 0}
    assert identity["이름_있는_심결_행(원래 이미지 값)"]["차이"] == 0
    assert identity["이름_있는_심결_행(원래 이미지 값)"]["n"] == results["데이터"]["이름_있는_행"]
    assert identity["쉬운_음성(참고)"]["차이"] == 0
    assert identity["이름도_이미지도_없는_입력(참고)"]["차이"] == 0
    table = results["평가_2_OOF"]
    assert table["이름 있는 행"]["짝_차이_auc"] == {"차이": 0.0, "ci95": [0.0, 0.0]}
    assert table["이름 있는 행"][t4n.NEW] == table["이름 있는 행"][t4n.OLD]
    assert table["이름 없는 행"][t4n.NEW]["n"] == results["데이터"]["이름_없는_행"]["n"]
    assert set(table["이름 없는 행"]) == {t4n.OLD, t4n.NEW, "짝_차이_auc", "짝_차이_brier"}
    assert results["쉬운_음성_평균_p"][t4n.NEW] == results["쉬운_음성_평균_p"][t4n.OLD]
    monotone = results["단조성(행)"]
    assert monotone["위반_합계"] == {"축_결합": 0, "같은_이름": 0}
    assert "noname:x2_whole → noname:x2_whole+x4 (x4)" in monotone["축_결합"]
    assert "base → x2_whole (x2_whole)" in monotone["축_결합"]
    assert len(monotone["같은_이름"]) == 8  # 키 2 × 유형 보기 2 × 요부 2
    assert set(results["계수"]) == {"noname:x2_whole", "noname:x2_whole+x4"}
    boot = results["계수"]["noname:x2_whole"]["부트스트랩"]
    assert "도형계 기울기(x2_whole + ×도형계)" in boot and boot["x2_whole"]["ci95"][0] >= -1e-9
    assert [row["조건"] for row in results["평가_8_민감도"]] == [
        "주 실행", "사건 2025101001193 제외", "사진 규칙 없음", "2등급에서 살아난 행 제외"]
    assert set(results["등급(v1.3 하한 그대로)"]["표"]) == {"이름 없는 행", "도형계",
                                                    "심결+cross+db"}
    image_only = results["평가_6_이미지만_같은_이름"]
    assert len(image_only) == 16 and [row["x2_whole"] for row in image_only[:4]] == [
        0.5, 0.7, 0.9, 1.0]
    for row in image_only:  # 같은 이름을 더하면(요부 유무 양쪽) 이미지만 입력보다 낮지 않다
        assert row["v1.4"]["패턴"].startswith("noname:")
        assert row["같은_이름(요부 있음)"]["p"] >= row["v1.4"]["p"]
        assert row["같은_이름(요부 없음)"]["p"] >= row["v1.4"]["p"]
        assert row["같은_이름(요부 있음)"]["패턴"] in ("x2_whole", "x2_whole+x4")
    candidate = out_dir / "risk_model_v1.4_attempt2_candidate.json"
    if adoption["채택"]:
        assert results["모델_파일"] == str(model_path) and not candidate.exists()
    else:  # 기준 미달이면 배포 경로에 쓰지 않는다(v1.3 유지)
        assert results["모델_파일"] == str(candidate) and not model_path.exists()
    model = rm.load_model(results["모델_파일"])
    assert model["version"] == "risk_model_v1.4" and rm.coupling_violations(model) == []
    # 이름 있는 4벌·등급 하한·단독 임계값·grade_precision·도형 규칙은 v1.3 을 그대로 복사
    for key in ("patterns", "features", "coefficients", "intercept", "grade_thresholds",
                "standalone_thresholds", "figure_rule", "pattern_axes", "reference_pattern"):
        assert model[key] == model_old[key]
    assert model["meta"]["grade_precision"] == model_old["meta"]["grade_precision"]
    assert model["meta"]["n_trial"] == model_old["meta"]["n_trial"]
    assert model["meta"]["named_from"]["version"] == "risk_model_v1.3"
    assert model["coupling"]["floors"] == model_old["coupling"]["floors"]
    assert model["coupling"]["same_name"]["x1_d"] == 1.0 and "name_floors" not in model["coupling"]
    assert sorted(model[rm.NAMELESS_KEY]) == ["x2_whole", "x2_whole+x4"]
    nameless_meta = model["meta"]["nameless"]
    assert nameless_meta["adoption"]["채택"] is adoption["채택"]
    assert nameless_meta["n_nameless"] == results["데이터"]["이름_없는_행"]["n"]
    assert nameless_meta["case_weight"]["rule"] == "w = min(1, 3 / 그 사건의 행 수)"
    assert rm.risk_score({"x2_whole": 0.9, "mark_type": "도형"}, model).pattern == "noname:x2_whole"
    named = {"x1_d": 0.9, "x2_text_d": 0.8, "x2_whole": 0.9, "x4": 0.5, "mark_type": "문자"}
    assert tuple(rm.risk_score(named, model)) == tuple(rm.risk_score(named, model_old))
    report = (out_dir / "risk_model_v1.4_attempt2_report.md").read_text(encoding="utf-8")
    for heading in ("## 채택 판단", "## 이름 없는 2벌", "## 평가 2", "## 등급별 건수",
                    "## 평가 6", "## 단조성", "## 평가 8"):
        assert heading in report
    saved = json.loads((out_dir / "risk_model_v1.4_attempt2_results.json").read_text(
        encoding="utf-8"))
    assert saved["채택"]["채택"] is adoption["채택"]


def test_attempt2_only_nameless_rows_change_and_minority_rule(data):
    features, easy = data
    model_old = rm.load_model(rm.V13_MODEL_PATH)
    rows = t4.load_dataset(features, easy).rows
    result = t4n.train_once(rows, model_old, folds=3, repeats=1, min_minority=5)
    a, design = result["arrays"], result["design"]
    nameless_rows = a["trial"] & ~a["named"]
    changed = result["prob_new"] != result["prob_old"]
    assert changed[nameless_rows].all() and not changed[~nameless_rows].any()
    np.testing.assert_array_equal(result["prob_old"], t4.v13_probabilities(rows, model_old))
    assert set(design.own[changed]) <= {"noname:x2_whole", "noname:x2_whole+x4"}
    assert result["floors"] == model_old["coupling"]["floors"]  # 하한은 v1.3 JSON 의 값
    with pytest.raises(ValueError, match="소수 클래스 기준"):
        t4n.train_once(rows, model_old, folds=3, repeats=1, min_minority=10_000)


def test_attempt2_image_only_population_is_a_reference_diagnostic(data):
    """판정 뒤에 덧붙인 참고 진단: 이름 없는 심결 행 + 이름을 가린 쉬운 음성 이미지 쌍을 도형계
    입력으로 본 집합의 지표·등급. 채택 판정표에는 들어가지 않는다."""
    features, easy = data
    model_old = rm.load_model(rm.V13_MODEL_PATH)
    rows = t4.load_dataset(features, easy).rows
    result = t4n.train_once(rows, model_old, folds=3, repeats=1, min_minority=5)
    a, design = result["arrays"], result["design"]
    block = "noname:x2_whole"
    index = np.arange(len(rows))
    # 도형계로 본 로짓 = 기울기에 ×도형계 계수를 더한 것
    coef, intercept = result["final"].blocks[block]
    x2_whole = design.X[block][:, design.names[block].index("x2_whole")]
    np.testing.assert_allclose(t4n.figure_logit(design, result["final"].blocks, block, index),
                               intercept + (coef[0] + coef[1]) * x2_whole)
    assert set(result["cv"]["per_block_figure"]) == set(result["cv"]["per_block"])
    boot = t4.Bootstrap(a["groups"], 20, seed=0)
    extra = t4n.image_only_population(rows, a, design, result["cv"], model_old, boot)
    image = design.mask[block]
    assert extra["이름_없는_심결_행"] == int((a["trial"] & ~a["named"] & image).sum())
    assert extra["쉬운_음성(이름 가림)"] == int((a["easy"] & image).sum())
    assert extra["n"] == extra["이름_없는_심결_행"] + extra["쉬운_음성(이름 가림)"]
    assert {t4n.OLD, t4n.NEW, "등급", "짝_차이_auc", "짝_차이_brier"} <= set(extra)
    for label in (t4n.OLD, t4n.NEW):
        assert sum(row["n"] for row in extra["등급"][label]) == extra["n"]
        grades = extra["쉬운_음성(이름 가림)_등급"][label]
        assert sum(grades[grade] for grade in rm.GRADES) == extra["쉬운_음성(이름 가림)"]
    model = t4n.build_model(model_old, design, result["final"], {"집합": {
        "noname:x2_whole": {}, "noname:x2_whole+x4": {}}})
    bounds = t4n.grade_boundaries(model)
    assert set(bounds) == {"문자계", "도형계"} and set(bounds["도형계"]) == {"주의", "검토 권장",
                                                                     "위험"}
    assert bounds["도형계"]["위험"] <= bounds["문자계"]["위험"]  # 도형계 기울기가 같거나 더 크다
    assert t4n.grade_boundaries(model_old) == {}
    full = t4n.run(features, easy, out_dir=features.parent / "o", model_path=features.parent / "m",
                   folds=3, repeats=1, bootstrap=0, metric_bootstrap=10, n_random=50,
                   sensitivity=False, min_pattern_minority=5)
    assert "참고_이미지만_질의_가정(판정 뒤 추가)" in full and "평가_8_민감도" not in full
    assert "이미지만_질의" not in json.dumps(full["채택"], ensure_ascii=False)  # 판정과 무관
