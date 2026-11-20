"""철자 v1 대 v2 측정(ml/scripts/x2_ortho_v2_benchmark.py) 테스트 — 작은 labels.csv·특징 파일을
만들어 끝까지 돌린다(실데이터·KIPRIS 없음, X3 는 가짜 임베더)."""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest
from src.axes import x3_semantic as x3
from src.axes.distinctiveness import Distinctiveness, goods_index
from src.axes.goods_map import GoodsEntry, GoodsMap

from scripts import pairs_features as pf
from scripts import x2_ortho_v2_benchmark as bench


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch):
    monkeypatch.setenv(x3.ENV_FAKE, "1")
    x3._reset_embedder()
    yield
    x3._reset_embedder()


def _model() -> Distinctiveness:
    names, classes = goods_index(GoodsMap([GoodsEntry("커피", 30, ("G0301",))]))
    return Distinctiveness({"gate": (12, 30)}, famous=set(), goods_names=names,
                           code_classes=classes)


def _label(case: str, name_a: str, name_b: str, label: str, axes: str = "외관") -> dict:
    return {"심판번호": case, "종류": "무효", "상표A_명칭": name_a, "상표B_번호": f"{case}9",
            "유사여부_확정": label, "판단축_확정": axes, "상표유형_확정": "문자",
            "llm_b_유사여부": label, "상대표장_명칭_kipris": name_b}


LABELS = [
    _label("T1", "HELLO DREAM", "DREAM", "비유사", "외관|호칭"),  # 공통 토큰 일부 → v1 1.0
    _label("T2", "커피빈", "커피 빈", "유사", "호칭"),  # 띄어쓰기만 다름 → v1·v2 1.0
    _label("T3", "BLUE BOTTLE", "BOTTLE BLUE", "유사", "외관"),  # 같은 토큰 → v1·v2 1.0
    _label("T4", "ZORBIX", "ZORBIK", "유사", "외관"),  # 토큰 하나씩 → v1 = v2
    _label("T5", "GATE ZORBIX", "GATE QWZK", "비유사", "외관"),  # gate 는 약한 토큰(제외)
    _label("T6", "QWERTY", "ASDFGH", "비유사", "외관"),
]
DB = [{"상표한글명": "알파로", "유사군": ["G0301"], "수집_출처": "기존 수집"},
      {"상표영문명": "BETA MIX", "유사군": ["G0302"], "수집_출처": "기존 수집"},
      {"상표한글명": "감마 텍", "유사군": [], "수집_출처": "기존 수집"}]


@pytest.fixture
def files(tmp_path):
    model = _model()
    features = pf.build_features(LABELS, [], model=model)
    pf.write_csv(tmp_path / "pairs_features.csv", features)
    easy = [pf._easy_row("db", f"db:{i}|{j}", pf._db_name(DB[i]), pf._db_name(DB[j]),
                         frozenset(DB[i]["유사군"]), frozenset(DB[j]["유사군"]), model)
            for i, j in ((0, 1), (1, 2), (0, 2))]
    pf.write_csv(tmp_path / "pairs_features_easy.csv", easy)
    labels = tmp_path / "labels.csv"
    columns = sorted({key for row in LABELS for key in row})
    with labels.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(LABELS)
    metadata = tmp_path / "meta.json"
    metadata.write_text(json.dumps({"trademarks": DB}, ensure_ascii=False), encoding="utf-8")
    return tmp_path, model


def test_features_carry_both_spelling_versions(files):
    tmp_path, _ = files
    rows = {row["심판번호"]: row for row in pf.read_csv(tmp_path / "pairs_features.csv")}
    assert float(rows["T1"]["x2_text_d"]) == 1.0 and float(rows["T1"]["x2_text_d_v2"]) < 1.0
    for case in ("T2", "T3"):
        assert float(rows[case]["x2_text_d"]) == float(rows[case]["x2_text_d_v2"]) == 1.0
    assert rows["T4"]["x2_text_d"] == rows["T4"]["x2_text_d_v2"]  # 토큰 하나씩 — 같은 값


def test_run_end_to_end(files):
    tmp_path, model = files
    results = bench.run(tmp_path / "pairs_features.csv", tmp_path / "pairs_features_easy.csv",
                        out_dir=tmp_path / "out", labels_path=tmp_path / "labels.csv",
                        metadata_path=tmp_path / "meta.json", rounds=40, model=model)
    problems = results["문제_사례"]
    assert problems["수"] == {"v1_1.0": 3, "토큰_구성_같음": 1, "띄어쓰기만_다름": 1,
                             "공통_토큰_일부": 1}
    partial = [case for case in problems["사례"] if case["구분"] == "공통_토큰_일부"]
    assert [(c["심판번호"], c["토큰A"], c["토큰B"]) for c in partial] == [
        ("T1", ["hello", "dream"], ["dream"])]
    assert problems["공통_토큰_일부(심결)_표장라벨"] == {"유사": 0, "비유사": 1, "없음": 0}
    main = results["x2_text_d(표장)"]
    assert {"어려운 문제(a)", "쉬운 음성 섞음"} <= set(main)
    hard = main["어려운 문제(a)"]
    assert hard["v1"]["n"] == hard["v2"]["n"] == 6
    assert hard["v2"]["auc_가중"] > hard["v1"]["auc_가중"]  # T1(비유사)이 1.0 → 0.75
    assert hard["짝_차이"]["차이"] == pytest.approx(hard["v2"]["auc_가중"] - hard["v1"]["auc_가중"],
                                                 abs=1e-4)
    assert main["쉬운 음성 섞음"]["v1"]["n"] == 9
    changed = results["바뀐_쌍"]["trial"]
    assert changed["n"] == 6 and changed["바뀐_쌍"] == changed["내려감"] == 1
    assert changed["v1_1.0_에서_내려감"] == 1 and changed["표장_라벨"]["유사_비율"] == 0.0
    assert results["판정"]["조건"] == bench.PROCEED
    assert set(results["판정"]["CI_하한"]) == {"어려운 문제(a)", "쉬운 음성 섞음"}
    saved = json.loads((tmp_path / "out" / "x2_ortho_v2_results.json").read_text(encoding="utf-8"))
    assert saved["판정"] == results["판정"]
    report = (tmp_path / "out" / "x2_ortho_v2_report.md").read_text(encoding="utf-8")
    assert "## 문제 사례" in report and "HELLO DREAM" in report and "## 바뀐 쌍" in report


def test_decide_uses_ci_lower_bounds_of_both_sets():
    def main(hard_low, mixed_low):
        return {"어려운 문제(a)": {"짝_차이": {"차이": 0.01, "ci95": [hard_low, 0.05]}},
                "쉬운 음성 섞음": {"짝_차이": {"차이": 0.01, "ci95": [mixed_low, 0.03]}}}

    assert bench.decide(main(-0.019, -0.001))["진행"] is True
    # 2026-11-20 실측 — 어려운 문제의 CI 하한이 미달
    assert bench.decide(main(-0.0235, 0.0006))["진행"] is False
    assert bench.decide(main(0.01, -0.021))["진행"] is False
    assert bench.decide(main(-0.02, 0.0))["진행"] is False  # 경계는 미달(> −0.02 이어야)
    assert bench.decide({})["진행"] is False
    assert bench.decide(main(0.0, 0.0))["판정"].startswith("진행")


def test_load_requires_v2_columns(tmp_path):
    path = tmp_path / "f.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["심판번호", "x2_text_d", "최종라벨"])
        writer.writeheader()
        writer.writerow({"심판번호": "T1", "x2_text_d": "0.5", "최종라벨": "유사"})
    with pytest.raises(SystemExit, match="x2_text_d_v2"):
        bench.load(path, tmp_path / "missing.csv")
    labels = bench.labels([{"표장라벨": "유사"}, {"표장라벨": "비유사"}, {"표장라벨": ""}])
    assert list(labels) == [1, 0, -1] and labels.dtype == np.int64
