"""이름 있는 입력의 공통 검토 권장 기준 2차 시도(ml/scripts/named_shared_threshold.py) — 공통 기준,
후보 JSON, 다시 매긴 전체 등급·출처, 강제 선형계획 검사, 시나리오 표(엔진·CLIP 없이, 배포 계수
JSON 과 합성 입력)."""

from __future__ import annotations

import copy
import json

import pytest
from src.model import risk_model as rm

from scripts import named_shared_threshold as shared

MODEL = rm.load_model(rm.V14_MODEL_PATH)
CURRENT = dict(MODEL["grade_thresholds"])
SHARED = {"주의": 0.0902, "검토 권장": 0.5059, "위험": 0.5902}
NAMED = {key: dict(SHARED) for key in MODEL["patterns"]}


def _row(label_maxima: dict[str, list[float]]) -> list[dict]:
    """방식마다 질의 하나씩 — 무관한 후보의 p 목록(그 방식의 자연스러운 계수 집합)."""
    rows = []
    patterns = {label: pattern for label, pattern, _, _ in shared.MODES}
    count = max(len(values) for values in label_maxima.values())
    for i in range(count):
        modes = {}
        for label, values in label_maxima.items():
            modes[label] = {"후보": [{"id": f"{label}{i}", "p": values[i], "무관": True,
                                    "pattern": patterns[label]}]}
        rows.append({"질의": f"q{i}", "방식": modes})
    return rows


def test_shared_threshold_is_largest_per_set_value_and_keeps_other_cuts():
    per_set = {"base": 0.4742, "x4": 0.5059, "x2_whole": 0.4645, "x2_whole+x4": 0.4994}
    assert shared.shared_thresholds(CURRENT, per_set) == {"주의": 0.0902, "검토 권장": 0.5059,
                                                         "위험": 0.5902}
    values = [i / 100 for i in range(100)]  # 0.00–0.99 → 11번째로 큰 값 0.89 → 0.8901
    rows = _row({label: values for label, *_ in shared.MODES})
    out = shared.per_set_values(rows, CURRENT)
    assert out == {"base": 0.8901, "x4": 0.8901, "x2_whole": 0.8901, "x2_whole+x4": 0.8901}
    low = _row({label: [0.01] * 20 for label, *_ in shared.MODES})
    assert set(shared.per_set_values(low, CURRENT).values()) == {0.1805}  # 올리기만


def test_candidate_model_changes_only_the_review_cut():
    base = json.loads(rm.V14_MODEL_PATH.read_text(encoding="utf-8"))
    thresholds = dict(SHARED)
    out = shared.candidate_model(base, thresholds, {"rule_sha256": "x"})
    assert out["version"] == shared.NEW_VERSION == "risk_model_v1.4.1"
    assert out["grade_thresholds"] == thresholds
    assert out["meta"]["named_grade_thresholds"]["previous"] == base["grade_thresholds"]
    for key in ("patterns", "nameless_patterns", "standalone_thresholds", "coupling", "figure_rule",
                "intercept", "coefficients"):
        assert out[key] == base[key]
    trimmed = copy.deepcopy(out)
    for document in (trimmed, copy.deepcopy(base)):
        document.pop("version"), document.pop("grade_thresholds"), document.pop("grade_basis")
        document["meta"].pop("named_grade_thresholds", None)
    assert trimmed == {k: v for k, v in base.items()
                       if k not in ("version", "grade_thresholds", "grade_basis")}
    assert base["version"] == "risk_model_v1.4"  # 원본은 그대로


def _candidate(cid, p, pattern="base", rules=(), title=True, grade=None):
    cuts = rm.grade_thresholds_for(MODEL, pattern)
    return {"id": cid, "p": p, "pattern": pattern, "규칙": list(rules), "이름": title,
            "등급": grade or rm.grade_for(p, cuts),
            "rank": list(shared.first.band_position(p, cuts)), "x2_img": None, "무관": True}


def test_regrade_overall_and_source_kind():
    named = NAMED
    entry = {"후보": [_candidate("A", 0.45), _candidate("B", 0.30),
                     _candidate("C", 0.12, rules=("standalone_x3",), grade="검토 권장"),
                     _candidate("D", 0.47, "noname:x2_whole+x4", title=False,
                                grade="검토 권장")]}
    grade, source = shared.regrade_overall(entry, named)
    assert grade == "검토 권장" and source["id"] == "D"  # 이름 있는 판단은 주의로 내려감
    assert shared.source_kind(source, named) == "상표명 없는 후보의 이름 없는 판단"
    assert shared.source_kind(entry["후보"][2], named) == "이름 있는 판단(단독 축 규칙)"
    assert shared.source_kind(_candidate("E", 0.55), named) == "이름 있는 판단"
    assert shared.regrade_overall({"후보": []}, named) == (None, None)
    assert shared.grade_counts(["주의", "주의", "위험"]) == {"주의": 2, "위험": 1}


def test_forced_lattice_check_runs_and_finds_no_drop_with_shared_cut():
    named = NAMED
    assert shared.first.exact_step_violations(MODEL, named)["검사"] == 0  # 같으면 건너뜀
    forced = shared.forced_thresholds(MODEL, named)
    review = {key: forced[key]["검토 권장"] for key in forced}
    assert review["x2_whole+x4"] > review["x4"] > review["base"]
    result = shared.first.exact_step_violations(MODEL, forced)
    assert result["검사"] > 0 and result["위반"] == 0  # 결합 제약이 지켜져 내려가는 입력이 없다


def test_scenario_table_skips_type_override_and_compares_others():
    named = NAMED
    pool = [_candidate("A", 0.45), _candidate("B", 0.30)]
    base = {"시나리오": {"S1": {"제목": "t", "유형": "문자", "전체": {"grade": "검토 권장"},
                              "상위": [{"title": "가"}], "풀": pool},
                       "S8": {"제목": "o", "유형": "결합-도형요부", "전체": {"grade": "검토 권장"},
                              "상위": [{"title": "나"}], "풀": pool}}}
    other = {"시나리오": {"S1": {"전체": {"grade": "주의"}, "상위": [{"title": "가"}]},
                        "S8": {"전체": {"grade": "검토 권장"}, "상위": [{"title": "나"}]}}}
    rows = {row["키"]: row for row in shared.scenario_table(base, other, named)}
    assert rows["S1"]["다시_매긴_전체"] == "주의" and rows["S1"]["일치"] is True
    assert rows["S8"]["일치"] is None  # 유형 고치기 — 다시 매기기 대상 밖


def test_rule_hash_is_stable(monkeypatch):
    first_hash = shared.rule_sha256()
    assert first_hash == shared.rule_sha256() and len(first_hash) == 64
    monkeypatch.setitem(shared.EXPECTED_PER_SET, "base", 0.5)
    assert shared.rule_sha256() != first_hash


@pytest.mark.parametrize("key", [key for key, _, _ in shared.SCENARIOS])
def test_scenario_specs_use_known_inputs(key):
    spec = {k: v for k, _, v in shared.SCENARIOS}[key]
    assert spec.get("image") in (None, *shared.SCENARIO_IMAGES)
    assert spec.get("goods") in (None, *shared.SCENARIO_GOODS)
    assert spec.get("override") in (None, "도형")
