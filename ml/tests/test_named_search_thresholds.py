"""이름 있는 입력의 실제 검색 기준 하한(ml/scripts/named_search_thresholds.py) — 대조군 이름 규칙,
하한 계산, 다시 매긴 등급·정렬, 진단 경로, 입력을 더 넣었을 때 등급이 내려가는지 찾는 선형계획(엔진·
CLIP 없이, 배포 계수 JSON 과 합성 입력)."""

from __future__ import annotations

import itertools
import random
import re

import pytest
from src.model import risk_model as rm

from scripts import named_search_thresholds as nsth

MODEL = rm.load_model(rm.V14_MODEL_PATH)
CURRENT = {key: dict(MODEL["grade_thresholds"]) for key in MODEL["patterns"]}


def test_name_stream_is_fixed_word_combinations():
    for lang in ("ko", "en"):
        first = nsth.name_stream(lang, 120)
        assert first == nsth.name_stream(lang, 120)  # 같은 seed 면 같은 순서
        assert len(first) == len(set(first)) == 120
        assert first != nsth.name_stream(lang, 120, seed="smoke")
        words = set(itertools.chain.from_iterable(nsth.WORDS[lang].values()))
        for name in first:
            pattern = "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True))
            parts = re.findall(pattern, name)
            assert " ".join(parts) == name and 2 <= len(parts) <= 3  # 낱말만, 무작위 글자 없음
            assert len(set(parts)) == len(parts)
        if lang == "ko":
            assert all(re.search("[가-힣]", name) for name in first)
        else:
            assert all(name.isascii() for name in first)


def test_split_and_preset_are_deterministic():
    items = list(range(101))
    first, second = nsth.split_half(items)
    assert (first, second) == nsth.split_half(items)
    assert len(first) == 50 and len(second) == 51 and sorted(first + second) == items
    assert nsth.preset_index("푸른 숲 커피", 25) == nsth.preset_index("푸른 숲 커피", 25)
    assert all(0 <= nsth.preset_index(f"이름 {i}", 25) < 25 for i in range(200))


def test_fit_cut_keeps_at_most_k_queries_at_or_above():
    rng = random.Random(1)
    for n in (1, 7, 50, 100, 137):
        maxima = [round(rng.random(), 6) for _ in range(n)]
        for share in (0.10, 0.02):
            cut, k, size = nsth.fit_cut(maxima, share)
            assert size == n and k == int(share * n + 1e-9)
            assert sum(1 for v in maxima if v >= cut) <= k
            assert round(cut * 10000) == pytest.approx(cut * 10000)  # 넷째 자리 값
            lower = round(cut - 0.0001, 4)  # 한 칸 낮추면 k 를 넘는다(가장 작은 값)
            assert sum(1 for v in maxima if v >= lower) > k
    assert nsth.fit_cut([], 0.1) == (None, 0, 0)
    cut, _, _ = nsth.fit_cut([0.1235] * 3 + [0.01] * 7, 0.10)  # 같은 값이 경계
    assert cut == 0.1236
    assert nsth.new_thresholds(MODEL["grade_thresholds"], {"검토 권장": 0.1, "위험": 0.7}) == {
        "주의": 0.0902, "검토 권장": 0.1805, "위험": 0.7}  # 올리기만
    assert nsth.ordered({"주의": 0.09, "검토 권장": 0.3, "위험": 0.6})
    assert not nsth.ordered({"주의": 0.09, "검토 권장": 0.6, "위험": 0.6})


def _candidate(cid, p, pattern="base", rules=(), x2_img=None, grade=None, rank=None):
    thresholds = rm.grade_thresholds_for(MODEL, pattern)
    if grade is None:
        grade = nsth.named_grade(p, thresholds, rules)
    if rank is None:
        rank = nsth.band_position(p, thresholds)
    return {"id": cid, "p": p, "pattern": pattern, "규칙": list(rules), "등급": grade,
            "rank": list(rank), "x2_img": x2_img}


def test_band_position_matches_engine_formula():
    cuts = MODEL["grade_thresholds"]
    assert nsth.band_position(0.05, cuts) == (0, pytest.approx(0.05 / 0.0902))
    assert nsth.band_position(0.3, cuts) == (2, pytest.approx((0.3 - 0.1805) / (0.5902 - 0.1805)))
    assert nsth.band_position(0.7, cuts) == (3, pytest.approx((0.7 - 0.5902) / (1 - 0.5902)))
    nameless = {"주의": 0.2, "검토 권장": 0.4, "위험": None}
    assert nsth.band_position(0.5, nameless) == (2, 1.0 * (0.5 - 0.4) / (1.0 - 0.4))


def test_offline_regrade_reorders_and_keeps_rule_floors():
    candidates = [_candidate("A", 0.35, "x4"), _candidate("B", 0.30, "base"),
                  _candidate("C", 0.12, "base", rules=("standalone_x1",)),
                  _candidate("D", 0.6, "noname:x2_whole", x2_img=0.95, grade="위험", rank=(3, 0.2))]
    ordered_now = nsth.offline_order(candidates, CURRENT)
    assert [c["id"] for c in ordered_now] == ["D", "A", "B", "C"]
    assert all(nsth.offline_grade(c, CURRENT) == c["등급"] for c in candidates)
    named = {**CURRENT, "x4": {"주의": 0.0902, "검토 권장": 0.4, "위험": 0.7},
             "base": {"주의": 0.0902, "검토 권장": 0.25, "위험": 0.6}}
    assert nsth.offline_grade(candidates[0], named) == "주의"  # x4 하한이 올라 주의
    assert nsth.offline_grade(candidates[1], named) == "검토 권장"
    assert nsth.offline_grade(candidates[2], named) == "검토 권장"  # 단독 규칙은 그대로
    assert nsth.offline_grade(candidates[3], named) == "위험"  # 이름 없는 판단은 그대로
    assert [c["id"] for c in nsth.offline_order(candidates, named)] == ["D", "B", "A", "C"]
    assert nsth.offline_overall(candidates[:3], named, top=1) == "검토 권장"
    assert nsth.offline_overall(candidates[:1], named, top=5) == "주의"


def test_path_of_separates_model_rules_and_floors():
    assert nsth.path_of(_candidate("A", 0.3), MODEL) == "모델(이름 있는 판단)"
    assert nsth.path_of(_candidate("B", 0.1, rules=("standalone_x2_text",)),
                        MODEL) == "단독 축 규칙"
    nameless = _candidate("C", 0.5, "noname:x2_whole")
    assert nameless["등급"] == "검토 권장"
    assert nsth.path_of(nameless, MODEL) == "모델(이름 없는 판단)"
    floored = _candidate("D", 0.4, "noname:x2_whole", rules=("goods_floor",), grade="검토 권장")
    assert nsth.path_of(floored, MODEL).startswith("그 밖의 하한 규칙")
    assert not nsth.is_model_path("단독 축 규칙") and nsth.is_model_path("모델(이름 없는 판단)")


def _random_named_input(rng):
    features = {"x1_d": rng.random(), "x2_text_d": rng.random(), "x3_d": rng.random(),
                "has_meaning_both": rng.random() < 0.5,
                "has_distinctive_part_a": rng.random() < 0.8,
                "has_distinctive_part_b": rng.random() < 0.8,
                "mark_type": rng.choice(rm.TYPE_LEVELS)}
    for axis in MODEL["pattern_axes"]:
        features[axis] = rng.random() if rng.random() < 0.6 else None
    return features


def test_features_grade_with_current_thresholds_equals_risk_score():
    rng = random.Random(0)
    for _ in range(2000):
        features = _random_named_input(rng)
        assert nsth.features_grade(features, MODEL, CURRENT) == rm.risk_score(
            features, MODEL).grade
        nameless = {**features, "x1_d": None, "x2_text_d": None, "x3_d": None,
                    "has_meaning_both": False, "has_distinctive_part_a": True,
                    "has_distinctive_part_b": True}
        if nameless["x2_whole"] is not None:
            expected = rm.risk_score(nameless, MODEL).grade
            if nameless["x4"] is not None and nameless["x4"] >= MODEL["coupling"]["floors"]["x4"]:
                expected = nsth.higher(rm.risk_score({**nameless, "x4": None}, MODEL).grade,
                                       expected)
            assert nsth.features_grade(nameless, MODEL, CURRENT) == expected


def test_exact_step_check_finds_drops_only_when_upper_threshold_is_higher():
    assert nsth.exact_step_violations(MODEL, CURRENT)["위반"] == 0  # 하한이 같으면 내려갈 수 없다
    named = {**CURRENT, "x4": {"주의": 0.0902, "검토 권장": 0.45, "위험": 0.5902},
             "base": {"주의": 0.0902, "검토 권장": 0.30, "위험": 0.5902}}
    found = nsth.exact_step_violations(MODEL, named)
    assert found["위반"] > 0 and found["확인된_위반"] == found["위반"]
    assert all("x4" in step for step in found["단계별"])
    lowered = {**CURRENT, "x4": {"주의": 0.0902, "검토 권장": 0.1805, "위험": 0.5902},
               "base": {"주의": 0.0902, "검토 권장": 0.30, "위험": 0.5902}}
    assert nsth.exact_step_violations(MODEL, lowered)["위반"] == 0  # 위 집합이 낮으면 괜찮다
    rows = [{"x1_d": 0.82, "x2_text_d": 0.0, "x3_d": 0.0, "has_meaning_both": False,
             "has_distinctive_part_a": True, "has_distinctive_part_b": True,
             "mark_type": "문자", "x2_whole": None, "x4": 0.03}]
    table = nsth.data_step_violations(rows, MODEL, named)
    assert table["base → x4 (x4)"] == {"n": 1, "위반": 1, "예": table["base → x4 (x4)"]["예"]}
    assert nsth.data_step_violations(rows, MODEL, CURRENT)["base → x4 (x4)"]["위반"] == 0


def test_exact_same_name_check():
    assert nsth.exact_same_name_violations(MODEL, CURRENT)["위반"] == 0
    raised = {**CURRENT, "x2_whole": {"주의": 0.0902, "검토 권장": 0.1805, "위험": 0.95}}
    found = nsth.exact_same_name_violations(MODEL, raised)
    assert found["위반"] > 0 and found["확인된_위반"] == found["위반"]
    assert {item["집합"] for item in found["예"]} == {"x2_whole"}


def test_rule_hash_is_stable_and_covers_settings(monkeypatch):
    first = nsth.rule_sha256()
    assert first == nsth.rule_sha256() and len(first) == 64
    monkeypatch.setitem(nsth.TARGETS, "검토 권장", 0.2)
    assert nsth.rule_sha256() != first
