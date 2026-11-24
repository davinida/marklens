"""goods_cap.py(업종 상한만 켠 v1.4.6 — 통합 모델 설계 §7-13)의 순수 함수·확인 조건."""

from __future__ import annotations

import pytest
from src.model import risk_model as rm

from scripts import goods_cap as gc


@pytest.fixture(scope="module")
def base() -> dict:
    return rm.load_model(rm.V145_MODEL_PATH)


def _named(x1, x2t, x4, *, x2=None, level="문자") -> dict:
    return {"x1_d": x1, "x2_text_d": x2t, "x3_d": None, "x2_whole": x2, "x4": x4,
            "has_meaning_both": False, "has_distinctive_part_a": True,
            "has_distinctive_part_b": True, "mark_type": level}


def test_settings_hash_and_rules():
    assert gc.rule_sha256() == gc.rule_sha256()
    assert {"결정", "바꾸는_것", "질의", "확인_1", "확인_2", "확인_3", "확인_4", "검산", "판정",
            "적용", "스모크"} == set(gc.RULE)
    assert gc.DEMO == {"F2": "크린토피야", "F1": "스타벅수", "F3": "파리바게트", "S1": "블루커피"}
    assert gc.CITED_DROP_MAX == 0.02 and gc.CHANGE_MIN_ROWS == 5
    assert (gc.BASE_VERSION, gc.NEW_VERSION) == ("risk_model_v1.4.5", "risk_model_v1.4.6")


def test_candidate_only_turns_the_cap_on(base):
    candidate = gc.candidate_model(base, rule_sha="abc")
    assert gc.differing_keys(base, candidate) == ["goods_cap", "version", "meta.goods_cap"]
    assert rm.goods_cap_enabled(candidate) and not rm.goods_cap_enabled(base)
    assert candidate["meta"]["goods_cap"]["derived_from"] == "risk_model_v1.4.5"
    assert rm.validate_model(candidate) is candidate
    with pytest.raises(ValueError):
        gc.candidate_model(candidate, rule_sha="abc")  # v1.4.5 에서만 만든다


def _scenario(grade: str, top: tuple[str, str], pool: dict) -> dict:
    return {"제목": "t", "전체": {"grade": grade, "prob": 0.5, "pattern": "x4"},
            "상위": [{"id": "1", "title": top[0], "grade": top[1], "prob": 0.5, "pattern": "x4",
                    "rules": []}], "풀": pool}


def test_check_1_needs_the_same_demo_grade_and_top_candidate():
    pool = {"1": ["A", "검토 권장", 0.5, "x4", []], "2": ["B", "주의", 0.2, "x4", []]}
    lowered = {"1": ["A", "검토 권장", 0.5, "x4", []],
               "2": ["B", "안전", 0.05, "base", ["goods_cap"]]}
    before = {key: _scenario("검토 권장", ("A", "검토 권장"), pool) for key in gc.DEMO}
    after = {key: _scenario("검토 권장", ("A", "검토 권장"), lowered) for key in gc.DEMO}
    out = gc.check_1({gc.BEFORE: before, gc.AFTER: after})
    assert out["통과"] is True
    assert len(out["그_밖의_변화"]) == 4
    assert out["그_밖의_변화"][0]["후보_등급_변화"][0]["후보"] == "2"
    after["F1"] = _scenario("주의", ("A", "주의"), lowered)  # 스타벅수가 내려가면 멈춤
    assert gc.check_1({gc.BEFORE: before, gc.AFTER: after})["통과"] is False
    partial = gc.check_1({gc.BEFORE: {"S6": before["F2"]}, gc.AFTER: {"S6": after["F2"]}})
    assert partial["통과"] is None  # 시연 넷을 돌리지 않음(스모크)


def _entry(overall: str, grades: dict) -> dict:
    return {"전체": overall, "상위": list(grades)[:5],
            "후보": {cid: [g, 0.1, "x4", 0.0, None, []] for cid, g in grades.items()}}


def test_check_2_stops_on_any_raised_query():
    down = {gc.BEFORE: _entry("검토 권장", {"a": "검토 권장"}),
            gc.AFTER: _entry("주의", {"a": "주의"})}
    up = {gc.BEFORE: _entry("주의", {"a": "주의"}),
          gc.AFTER: _entry("검토 권장", {"a": "검토 권장"})}
    same = {gc.BEFORE: _entry("주의", {"a": "주의"}), gc.AFTER: _entry("주의", {"a": "주의"})}
    named = [{"반": "확인용", "이름": "x", "방식": {"이름+업종": down, "이름만": same}}]
    out = gc.check_2(named, [], [])
    assert out["통과"] and out["내려감"] == 1 and out["올라감"] == 0
    assert out["후보_등급_변화"] == {"지어낸 이름 대조군 확인용 이름+업종 내려감": 1}
    sample = [{"질의": "q", "이름_있음": same, "이름_없음": up}]
    out = gc.check_2(named, [], sample)
    assert not out["통과"] and out["올라감"] == 1


def test_check_3_counts_the_drop_and_the_similar_share(base):
    candidate = gc.candidate_model(base, rule_sha="abc")
    lowered = _named(0.16, 0.7, 0.01)  # v1.4.5: x4 집합 주의 > base 안전 → 상한으로 안전
    kept = _named(1.0, 1.0, 1.0)
    pairs = [{"심판번호": str(i), "상대번호": None, "쌍키": None, "라벨": label, "특징": f}
             for i, (f, label) in enumerate([(lowered, "비유사"), (kept, "유사")])]
    out = gc.check_3(pairs, base, candidate)
    assert [d["전"] + "→" + d["후"] for d in out["내려간_쌍"]] == ["주의→안전"]
    assert out["검토_권장_이상"] == {gc.BEFORE: 0.5, gc.AFTER: 0.5} and out["통과"]
    assert out["판정에_씀"] is False and out["올라간_쌍"] == 0


def test_engine_rules_match_the_definition(base):
    candidate = gc.candidate_model(base, rule_sha="abc")
    assert gc.named_final(_named(0.16, 0.7, 0.01), base) == ("주의", "안전")
    assert gc.named_final(_named(0.16, 0.7, 0.01), candidate) == ("안전", "안전")
    assert gc.named_final(_named(0.16, 0.7, 0.5), candidate)[0] == gc.named_final(
        _named(0.16, 0.7, 0.5), base)[0]  # 겹치면 상한 없음
    assert gc.nameless_final(1.0, 0.0, candidate) == gc.nameless_final(1.0, 0.0, base)


def test_run_refuses_smoke_in_the_trials_folder_and_without_freeze(tmp_path):
    assert gc.main(["run", "--smoke"]) == gc.EXIT_REFUSED
    assert gc.main(["run", "--out-dir", str(tmp_path)]) == gc.EXIT_REFUSED  # freeze 없음
    assert gc.main(["apply", "--out-dir", str(tmp_path)]) == gc.EXIT_REFUSED
