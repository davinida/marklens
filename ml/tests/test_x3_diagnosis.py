"""관념 축 진단 스크립트(ml/scripts/x3_diagnosis.py)의 계산 부분 — 엔진·비공개 데이터 없이."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from src.model import risk_model as rm

from scripts import x3_diagnosis as xd


def record(appno: str, name: str, codes=("G0502",)) -> dict:
    return {"출원번호": appno, "상표한글명": name, "유사군": list(codes)}


RECORDS = [
    record("4020200000002", "Whale", ("G0301", "V123456")),
    record("4020200000001", "WHALE", ("S120602", "G0502")),
    record("4020200000003", "golden shop"),
    record("4020200000004", "바다 (vada)"),
    record("4020200000005", ""),
]
PRESETS = [{"id": "cafe", "codes": ["G0502"]}, {"id": "nail", "codes": ["S128302"]}]
CONTROL = ([{"이름": f"한글{i}", "언어": "ko", "업종_세트": "cafe", "유사군": ["G0502"]}
            for i in range(30)]
           + [{"이름": f"name{i}", "언어": "en", "업종_세트": "nail", "유사군": ["S128302"]}
              for i in range(30)])


def resolve(source: dict, weak: dict | None = None):
    return xd.resolve_bundles(source, RECORDS, weak_records=weak or {}, control=CONTROL,
                              presets=PRESETS)


# ---- 묶음 --------------------------------------------------------------------------------------

def test_normalized_key_and_codes():
    assert xd.normalized_key("Golden  SHOP") == "golden shop"
    assert xd.valid_codes(["S120602", "G0502", "V123456", "g0502", " G0301 "]) == [
        "G0301", "G0502", "S120602"]
    assert xd.valid_codes("G0502|S2005|") == ["G0502", "S2005"]
    assert xd.valid_codes(None) == []
    assert len(xd.valid_codes([f"G{i:04d}" for i in range(100)])) == xd.MAX_CODES


def test_resolve_finds_every_record_with_the_same_name_and_uses_the_earliest_goods():
    bundles, problems = resolve({
        "가_번역어": [{"원래": "whale", "질의": "고래", "범위": "전체", "소리": "다름"}],
        "나_동의어": [{"원래": "golden shop", "질의": "gold store"}],
    })
    assert problems == []
    item = bundles["가_번역어"][0]
    assert item["원래_ids"] == ["4020200000001", "4020200000002"]  # 출원번호 순
    assert item["업종"] == ["G0502", "S120602"]  # 가장 앞선 레코드의 유사군(형식에 맞는 것만)
    assert item["원래_이름"] == "WHALE" and item["범위"] == "전체" and item["소리"] == "다름"
    assert bundles["나_동의어"][0]["원래_ids"] == ["4020200000003"]


def test_resolve_reports_problems_instead_of_guessing():
    _, problems = resolve({
        "가_번역어": [{"원래": "없는 이름", "질의": "nothing", "범위": "전체", "소리": "다름"}],
        "다_무관한_사전어": [{"질의": "shop", "언어": "영문"}, {"질의": "등대", "언어": "한글"},
                           {"질의": "등대", "언어": "한글"}],
        "라_흔한_낱말만": [{"약한_낱말": "golden", "질의": "황금 족제비"}],
    })
    text = "\n".join(problems)
    assert "DB 에 없는 이름 '없는 이름'" in text
    assert "DB 이름의 낱말과 같은 사전어 'shop'" in text
    assert "같은 질의가 2번 '등대'" in text
    assert "약한 낱말로 나오지 않는 'golden'" in text


def test_resolve_controls_are_deterministic_and_take_the_first_names_per_language():
    source = {"다_무관한_사전어": [{"질의": w, "언어": "한글"} for w in ("등대", "우산", "가위")],
              "라_흔한_낱말만": [{"약한_낱말": "golden", "질의": "황금 족제비"}]}
    first, problems = resolve(source, {"golden": RECORDS[2]})
    again, _ = resolve(source, {"golden": RECORDS[2]})
    assert problems == [] and first == again
    assert {item["업종_세트"] for item in first["다_무관한_사전어"]} <= {"cafe", "nail"}
    assert first["라_흔한_낱말만"][0]["든_id"] == "4020200000003"
    made = first["마_지어낸_이름"]
    assert len(made) == 2 * xd.CONTROL_PER_LANGUAGE
    assert [item["질의"] for item in made[:2]] == ["한글0", "한글1"]
    assert made[xd.CONTROL_PER_LANGUAGE]["질의"] == "name0"


def test_settings_hash_is_stable_and_covers_the_bundle_list_and_the_object_table(monkeypatch):
    first = xd.settings_sha256("abc")
    assert first == xd.settings_sha256("abc") and len(first) == 64
    assert first != xd.settings_sha256("abd")
    monkeypatch.setitem(xd.FIGURE_OBJECTS, "999999", ("thing", "것"))
    assert first != xd.settings_sha256("abc")


def test_settings_name_the_split_the_cases_and_the_expectation():
    text = json.dumps(xd.SETTINGS, ensure_ascii=False)
    for phrase in ("확인용으로 두고 열지 않는다", "기준용 100개", "통과선은 두지 않고",
                   "(a) 지금 = 관념 계수 0", "0 이상으로"):
        assert phrase in text
    assert xd.SETTINGS["부트스트랩"] == {"횟수": xd.BOOTSTRAP, "씨앗": xd.SEED,
                                     "단위": "묶음(사건) 복원추출"}


# ---- 표본 나누기 --------------------------------------------------------------------------------

def test_baseline_split_keeps_groups_whole_and_is_reproducible():
    rng = np.random.default_rng(1)
    groups = np.asarray([f"case{i // 3}" for i in range(300)])
    y = (rng.random(300) < 0.4).astype(float)
    base = xd.baseline_mask(y, groups)
    assert np.array_equal(base, xd.baseline_mask(y, groups))
    held = set(groups[~base])
    assert held and not (held & set(groups[base]))  # 한 묶음은 한쪽에만
    assert 0.1 < (~base).mean() < 0.3  # 다섯 겹 가운데 하나


# ---- 계수 다시 맞추기 ---------------------------------------------------------------------------

def synthetic(beta: float, n: int = 6000, seed: int = 0):
    rng = np.random.default_rng(seed)
    offset = rng.normal(-1.0, 1.0, n)
    x = rng.random(n)
    y = (rng.random(n) < 1.0 / (1.0 + np.exp(-(offset + beta * x)))).astype(float)
    return offset, x, y, np.ones(n)


def test_fit_recovers_a_positive_coefficient():
    offset, x, y, w = synthetic(1.5)
    assert xd.fit_x3(offset, x, y, w) == pytest.approx(1.5, abs=0.25)


def test_fit_sticks_to_zero_when_the_data_point_the_other_way():
    offset, x, y, w = synthetic(-1.5)
    assert xd.fit_x3(offset, x, y, w) == 0.0  # 0 이상 제약 — 정확히 0
    assert xd.fit_x3(offset, x, y, w, lower=None) == pytest.approx(-1.5, abs=0.25)


def test_fit_prior_pulls_toward_its_mean_only_when_data_are_few():
    offset, x, y, w = synthetic(0.0, n=40, seed=3)
    with_prior = xd.fit_x3(offset, x, y, w * 0.01, mu=0.5, sigma=1.0)
    assert with_prior == pytest.approx(0.5, abs=0.05)  # 자료가 거의 없으면 사전평균
    offset, x, y, w = synthetic(1.5)
    assert xd.fit_x3(offset, x, y, w, mu=0.5, sigma=1.0) == pytest.approx(1.5, abs=0.25)


def test_fit_ignores_rows_with_zero_weight():
    offset, x, y, w = synthetic(1.5, n=2000)
    half = w.copy()
    half[1000:] = 0.0
    assert xd.fit_x3(offset, x, y, half) == pytest.approx(
        xd.fit_x3(offset[:1000], x[:1000], y[:1000], w[:1000]), abs=1e-6)


def test_fit_with_missing_indicator_keeps_the_meaning_coefficient_non_negative():
    offset, x, y, w = synthetic(-1.0, n=3000)
    missing = (np.arange(3000) % 2).astype(float)
    beta, gamma = xd.fit_x3_with_missing(offset, x * (1 - missing), missing, y, w, mu=None)
    assert beta >= 0.0 and abs(gamma) <= xd.BETA_MAX


def test_variant_model_changes_only_the_meaning_coefficient():
    base = rm.load_model(rm.DEFAULT_MODEL_PATH)
    before = copy.deepcopy(base)
    coefficients = {key: 0.3 for key in base["patterns"]}
    model = xd.variant_model(base, coefficients, "t")
    assert base == before  # 원본은 그대로(파일도 쓰지 않는다)
    for key, block in model["patterns"].items():
        assert block["coefficients"]["x3_d"] == 0.3
        others = {k: v for k, v in block["coefficients"].items() if k != "x3_d"}
        assert others == {k: v for k, v in before["patterns"][key]["coefficients"].items()
                          if k != "x3_d"}
        assert block["intercept"] == before["patterns"][key]["intercept"]
    assert model["coefficients"]["x3_d"] == 0.3
    for key in ("grade_thresholds", "standalone_thresholds", "nameless_patterns", "coupling"):
        assert model[key] == before[key]
    assert model["version"].endswith("+x3:t")
    features = {"x1_d": 0.2, "x2_text_d": 0.2, "x3_d": 1.0, "x2_whole": None, "x4": None,
                "has_meaning_both": True, "mark_type": "문자"}
    assert rm.risk_score(features, model).prob > rm.risk_score(features, base).prob
    gated = {**features, "has_meaning_both": False}  # 뜻이 한쪽에라도 없으면 값 0 — 달라지지 않는다
    assert rm.risk_score(gated, model).prob == pytest.approx(rm.risk_score(gated, base).prob)


def test_three_cases_now_refit_and_spelling_sized():
    base = rm.load_model(rm.DEFAULT_MODEL_PATH)
    fitted = {"세트": {key: {"다시_맞춘_값": 0.1 * (i + 1)}
                     for i, key in enumerate(base["patterns"])}}
    cases = xd.case_coefficients(base, fitted)
    assert set(cases) == set(xd.CASES)
    assert set(cases["a"].values()) == {0.0}
    assert list(cases["b"].values()) == pytest.approx([0.1, 0.2, 0.3, 0.4])
    for key, block in base["patterns"].items():
        assert cases["c"][key] == block["coefficients"]["x2_text_d"]
    models = xd.case_models(base, fitted)
    assert models["a"]["patterns"] == base["patterns"] or all(
        block["coefficients"]["x3_d"] == 0.0 for block in models["a"]["patterns"].values())


def test_block_mask_follows_the_axes_of_each_coefficient_set():
    values = [{"miss_x2img": 0.0, "miss_x4": 0.0}, {"miss_x2img": 1.0, "miss_x4": 0.0},
              {"miss_x2img": 0.0, "miss_x4": 1.0}, {"miss_x2img": 1.0, "miss_x4": 1.0},
              {"miss_x2img": 0.0, "miss_x4": 0.0}]
    data = {"values": values, "named": np.asarray([True, True, True, True, False])}
    base = rm.load_model(rm.DEFAULT_MODEL_PATH)
    masks = {key: xd.block_mask(key, data).tolist() for key in base["patterns"]}
    assert masks["base"] == [True, True, True, True, False]  # 이름 있는 행 전부
    assert masks["x2_whole"] == [True, False, True, False, False]
    assert masks["x4"] == [True, True, False, False, False]
    assert masks["x2_whole+x4"] == [True, False, False, False, False]


# ---- 네 축 --------------------------------------------------------------------------------------

def test_auc_block_and_paired_difference_use_the_same_bootstrap_draws():
    from scripts import train_risk_model_v14 as t4

    rng = np.random.default_rng(0)
    n = 400
    y = (rng.random(n) < 0.5).astype(float)
    good = y + rng.normal(0, 0.8, n)
    noise = rng.normal(0, 1.0, n)
    groups = np.asarray([f"g{i // 2}" for i in range(n)])
    weight = np.ones(n)
    mask = np.ones(n, dtype=bool)
    boot = t4.Bootstrap(groups, 200, 0)
    block = xd.auc_block(good, y, weight, mask, boot)
    assert 0.7 < block["auc"] < 0.95 and block["ci95"][0] < block["auc"] < block["ci95"][1]
    assert block["n"] == n and block["유사"] + block["비유사"] == n
    diff = xd.auc_difference(noise, good, y, weight, mask, boot)
    assert diff["차이"] < -0.1 and diff["ci95"][1] < 0 and diff["0보다_큰_비율"] == 0.0
    same = xd.auc_difference(good, good, y, weight, mask, boot)
    assert same["차이"] == 0.0 and same["ci95"] == [0.0, 0.0]


# ---- 쌍 단위 ------------------------------------------------------------------------------------

def test_pair_label_prefers_the_mark_judgment():
    assert xd.pair_label({"표장라벨": "유사", "최종라벨": "비유사"}) == "유사"
    assert xd.pair_label({"표장라벨": "", "최종라벨": "비유사"}) == "비유사"
    assert xd.pair_label({"표장라벨": "없음", "최종라벨": "유사"}) == "유사"


def test_other_axis_only():
    assert xd.other_axis_only("호칭") and xd.other_axis_only("외관|상품")
    assert not xd.other_axis_only("호칭|관념") and not xd.other_axis_only("")


def test_tabulate_pair_types_counts_types_details_and_keeps_three_examples():
    items = [{"쌍키": f"k{i}", "뜻_점수": 0.0} for i in range(6)]
    assigned = {f"k{i}": [xd.PAIR_TYPES[0], "음역"] for i in range(4)}
    assigned["k4"] = [xd.PAIR_TYPES[5], "자료"]
    table = xd.tabulate_pair_types(items, assigned)
    assert table["건수"] == {xd.PAIR_TYPES[0]: 4, xd.PAIR_TYPES[5]: 1, "분류 안 함": 1}
    assert table["세부"][f"{xd.PAIR_TYPES[0]} — 음역"] == 4
    assert len(table["예"][xd.PAIR_TYPES[0]]) == 3


# ---- 검색 단위 ----------------------------------------------------------------------------------

def miss(**changes):
    case = {"query_meaning": True, "pair_meaning": True, "score": 0.9, "in_pool": True, "rank": 1,
            "card_grade": "검토 권장", "pool_floor": 0.55}
    case.update(changes)
    return xd.miss_type(**case)


def test_miss_type_orders_the_reasons():
    assert miss() is None and miss(rank=5, card_grade="위험") is None
    assert miss(card_grade="주의") == xd.MISS_TYPES[5]
    assert miss(rank=6) == xd.MISS_TYPES[4] and miss(rank=20) == xd.MISS_TYPES[4]
    assert miss(rank=21) == xd.MISS_TYPES[3]
    gone = {"rank": None, "card_grade": None, "in_pool": False}
    assert miss(**gone, query_meaning=False) == xd.MISS_TYPES[0]
    assert miss(**gone, pair_meaning=False, score=None) == xd.MISS_TYPES[1]
    assert miss(**gone, score=0.4) == xd.MISS_TYPES[2]
    assert miss(**gone, score=0.7) == xd.MISS_TYPES[3]  # 점수는 넘는데 풀의 다섯 자리에 못 듦


def found_row(rank, grade, overall, mismatch, score=0.8):
    return {"질의_뜻": True, "쌍_뜻": score is not None, "뜻_점수": score, "단독_규칙": bool(
        score and score >= 0.7707), "순위": rank, "카드_등급": grade, "전체_등급": overall,
            "어긋남": mismatch}


def test_summarize_found():
    rows = [found_row(1, "검토 권장", "검토 권장", None),
            found_row(7, "주의", "주의", xd.MISS_TYPES[4]),
            found_row(None, None, "안전", xd.MISS_TYPES[2], score=0.3),
            found_row(None, None, None, xd.MISS_TYPES[0], score=None)]
    summary = xd.summarize_found(rows)
    assert summary["질의"] == 4 and summary["풀에_듦"] == 0.5
    assert summary["앞_5"] == 0.25 and summary["앞_20"] == 0.5
    assert summary["앞_5·검토_권장_이상(기대)"] == 0.25
    assert summary["단독_규칙"] == 0.5 and summary["양쪽에_뜻(원래 상표와)"] == 0.75
    assert summary["전체_등급"] == {"안전": 1, "주의": 1, "검토 권장": 1, "없음": 1}
    assert summary["카드_등급(풀에 든 것)"] == {"주의": 1, "검토 권장": 1}
    assert summary["어긋난_까닭"] == {xd.MISS_TYPES[4]: 1, xd.MISS_TYPES[2]: 1, xd.MISS_TYPES[0]: 1}
    assert summary["뜻_점수"]["n"] == 3


def test_summarize_control_separates_rises_caused_by_meaning():
    def row(meaning, score, fired, grade, caused):
        return {"질의_뜻": meaning, "뜻_점수": score, "단독_규칙": fired, "전체_등급": grade,
                "뜻_때문": caused}

    rows = [row(True, 0.8, True, "검토 권장", True), row(True, 0.6, False, "위험", False),
            row(False, None, False, "주의", False), row(False, None, False, None, False)]
    summary = xd.summarize_control(rows)
    assert summary["전체_검토_권장_이상"] == 0.5 and summary["그중_뜻_때문"] == 0.25
    assert summary["뜻_때문_건수"] == 1 and summary["뜻이_있다고_판정"] == 0.5
    assert summary["단독_규칙"] == 0.25


def test_x3_off_restores_the_setting_even_after_an_error():
    class Config:
        X3_ENABLED = True

    class Engine:
        config = Config()

    engine = Engine()
    with pytest.raises(RuntimeError):
        with xd.X3Off(engine):
            assert engine.config.X3_ENABLED is False
            raise RuntimeError("boom")
    assert engine.config.X3_ENABLED is True


def test_scenario_changes_reports_grade_and_top_changes_only():
    def run(grade, top, top_grade):
        return {"제목": "t", "전체": {"grade": grade},
                "상위": [{"id": top, "title": top, "grade": top_grade}]}

    scenarios = {"a": {"S1": run("주의", "x", "주의"), "S2": run("위험", "y", "위험"),
                       "S3": {"제목": "t", "건너뜀": True}},
                 "c": {"S1": run("검토 권장", "x", "검토 권장"), "S2": run("위험", "y", "위험"),
                       "S3": {"제목": "t", "건너뜀": True}}}
    changes = xd.scenario_changes(scenarios)
    assert list(changes) == ["c"]
    assert [item["시나리오"] for item in changes["c"]["바뀐_것"]] == ["S1"]
    assert changes["c"]["바뀐_것"][0]["전체"] == ["주의", "검토 권장"]


# ---- 도형과 이름 --------------------------------------------------------------------------------

def test_figure_object_needs_exactly_one_object():
    assert xd.figure_object(["010102", "260118"]) == ("star", "별")  # 기하 도형·글자 코드는 무시
    assert xd.figure_object(["010102", "010109"]) == ("star", "별")  # 같은 사물의 두 구분
    assert xd.figure_object(["010102", "020901"]) is None  # 사물이 둘
    assert xd.figure_object(["260118"]) is None


def test_object_table_avoids_grouped_or_abstract_divisions():
    for code in ("030916", "020912", "260101", "270501", "250703"):  # 갑각류·머리카락·원·글자·바탕
        assert code not in xd.FIGURE_OBJECTS
    assert all(len(code) == 6 and code.isdigit() for code in xd.FIGURE_OBJECTS)
    assert all(english.isascii() for english, _ in xd.FIGURE_OBJECTS.values())


def test_pick_figures_caps_each_object_in_application_order():
    marks = [{"id": f"40{i:03d}", "codes": ["050520"], "순번": i} for i in range(9)]
    marks += [{"id": "30001", "codes": ["030903"], "순번": 20},
              {"id": "30002", "codes": ["010102", "020901"], "순번": 21}]
    picked = xd.pick_figures(marks, per_object=3)
    assert [mark["id"] for mark in picked] == ["30001", "40000", "40001", "40002"]
    assert picked[0]["사물"] == "whale" and picked[0]["사물_한글"] == "고래"


def test_pair_auc_perfect_reversed_and_ties():
    own = np.asarray([0, 1, 2])
    perfect = np.eye(3)
    assert xd.pair_auc(perfect, own) == 1.0
    assert xd.pair_auc(1.0 - perfect, own) == 0.0
    assert xd.pair_auc(np.ones((3, 3)), own) == 0.5
    weights = np.asarray([2.0, 0.0, 1.0])  # 뽑히지 않은 표장은 맞는 짝·틀린 짝 모두에서 빠진다
    assert xd.pair_auc(perfect, own, weights) == 1.0


def test_figure_metrics_report_auc_interval_and_top1():
    rng = np.random.default_rng(0)
    own = np.asarray([i % 5 for i in range(40)])
    similarity = rng.normal(0.2, 0.05, (40, 5))
    similarity[np.arange(40), own] += 0.1
    metrics = xd.figure_metrics(similarity, own, rounds=200)
    assert metrics["AUC"] > 0.85 and metrics["ci95"][0] <= metrics["AUC"] <= metrics["ci95"][1]
    assert metrics["무작위_1위"] == 0.2 and metrics["맞는_사물이_1위"] > 0.5
    assert metrics["맞는_짝_평균"] > metrics["틀린_짝_평균"]


# ---- 산출물의 자리 ------------------------------------------------------------------------------

def test_real_pairs_and_lists_go_outside_the_repository():
    archive = Path("/tmp/x3-archive")
    paths = xd._paths(archive)  # noqa: SLF001
    outside = ("source", "bundles", "pair_types", "pair_list", "pair_examples", "bundle_examples",
               "bundle_rows", "figures")
    for name in outside:
        assert paths[name].parent == archive
    for name in ("config", "offline", "engine", "figure", "report"):
        assert paths[name].parent == xd.TRIALS  # ml/data/trials — 저장소에 올리지 않는 곳
    assert xd.REPO_ROOT not in xd.ARCHIVE.parents


def test_report_text_renders_available_parts_only():
    assert "결과 표" in xd.report_text(None, None, None)
    figure = {"표장": 3, "사물": 2, "글자": {"문장(주)": {"AUC": 0.9}}}
    text = xd.report_text(None, None, figure)
    assert "도형과 이름" in text and "네 축" not in text
