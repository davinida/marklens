"""업종이 등급을 움직이는 원칙(통합 모델 설계 §7-13) — 상설 시험. 업종 집합(이름 없는 이미지+업종 ↔
짝 이미지만, 이름 있는 x4 ↔ 짝 base, x2_whole+x4 ↔ 짝 x2_whole)의 최종 등급(엔진과 같은 업종 하한·
상한 — 계수 JSON 의 goods_rule·goods_cap 이 켤 때만)은 업종이 겹치면(겹침 ≥ 결합 하한) 짝 판단의
등급 이상, 업종이 다르면(< 하한) 짝 판단의 등급 이하. 배포 기본 모델로 격자와 실제 쌍(학습 특징 행)
에서 본다.

기본 모델 v1.4.6(2026-11-24)은 업종 상한(goods_cap)을 켜 이름 있는 쪽의 "다르면 ≤" 도 등급에서
지킨다 — v1.4.5 까지는 이름 있는 업종 두 벌(v1.3 의 더하기 구조)이 업종이 달라도 짝 판단보다 높은
점이 있어 strict xfail 이었다(4-b 곱하기 항은 채택하지 않음, 설계 §7-13)."""

from __future__ import annotations

import pytest
from src.model import risk_model as rm

from scripts import named_search_thresholds as first
from scripts import nameless_shared_threshold as ns
from scripts import train_risk_model as tr
from scripts import train_risk_model_v14 as t4

X4_GRID = tuple(round(0.002 * i, 3) for i in range(13)) + (0.0252, 0.05, 0.1, 0.3, 0.5, 1.0)


@pytest.fixture(scope="module")
def model() -> dict:
    return rm.load_model()


def _final_named(features: dict, model: dict) -> tuple[str, str]:
    """(이름 있는 업종 집합의 최종 등급, 짝 판단의 등급) — 엔진 _named_judgment 와 같은 규칙."""
    result = rm.risk_score(features, model)
    pair = rm.risk_score({**features, "x4": None}, model)
    grade, floor = result.grade, float(model["coupling"]["floors"]["x4"])
    rule = model["patterns"][result.pattern].get(rm.GOODS_RULE_KEY) == rm.GOODS_RULE_NO_RAISE
    if float(features["x4"]) >= floor:
        if rule:
            grade = max(grade, pair.grade, key=rm.GRADES.index)
    elif rm.goods_cap_enabled(model):
        grade = min(grade, pair.grade, key=rm.GRADES.index)
    return grade, pair.grade


def _final_nameless(x2: float, x4: float, model: dict, level: str = "도형") -> tuple[str, str]:
    """(이름 없는 이미지+업종 판단의 최종 등급, 이미지만 판단의 등급) — 엔진 _nameless_judgment."""
    features = {**ns.nameless_features(x2, x4), "mark_type": level}
    grade = first.nameless_final_grade(features, model)  # 업종 하한까지
    alone = rm.risk_score({**features, "x4": None}, model).grade
    if float(x4) < float(model["coupling"]["floors"]["x4"]) and rm.goods_cap_enabled(model):
        grade = min(grade, alone, key=rm.GRADES.index)
    return grade, alone


def _violations(pairs: list[tuple[float, str, str]], floor: float) -> dict[str, int]:
    out = {"겹침": 0, "다름": 0}
    for x4, final, pair in pairs:
        if x4 >= floor and rm.GRADES.index(final) < rm.GRADES.index(pair):
            out["겹침"] += 1
        elif x4 < floor and rm.GRADES.index(final) > rm.GRADES.index(pair):
            out["다름"] += 1
    return out


def _named_grid(model: dict):
    for level in ("문자", "도형"):
        for distinctive in (True, False):
            for x1 in [i / 10 for i in range(11)]:
                for x2t in [i / 10 for i in range(11)]:
                    for x2 in (None, 0.0, 0.3, 0.6, 0.9, 1.0):
                        for x4 in X4_GRID:
                            features = {"x1_d": x1, "x2_text_d": x2t, "x3_d": None,
                                        "has_meaning_both": False, "x2_whole": x2, "x4": x4,
                                        "has_distinctive_part_a": True,
                                        "has_distinctive_part_b": distinctive,
                                        "mark_type": level}
                            yield (x4, *_final_named(features, model))


def _training_rows(named: bool) -> list[dict]:
    """실제 쌍 — 업종 축이 있는 학습 특징 행(심결 + 쉬운 음성). 이름 있는 쪽은 이름 축이 있는 행,
    이름 없는 쪽은 이미지도 있는 행 전부(이름 없는 집합의 학습처럼 이름을 가려 이미지·업종만)."""
    if not tr.DEFAULT_FEATURES.exists():
        pytest.skip("학습 특징 없음")
    rows = t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY).rows
    out = []
    for row in rows:
        features = t4.service_features(row)
        if features.get("x4") is None:
            continue
        if named and tr.has_name(row):
            out.append(features)
        elif not named and features.get("x2_whole") is not None:
            out.append(features)
    return out


def test_nameless_goods_judgment_follows_the_principle_on_a_grid(model):
    floor = float(model["coupling"]["floors"]["x4"])
    pairs = [(x4, *_final_nameless(x2 / 100, x4, model, level))
             for level in ("도형", "문자") for x2 in range(101) for x4 in X4_GRID]
    assert _violations(pairs, floor) == {"겹침": 0, "다름": 0}


def test_nameless_goods_judgment_follows_the_principle_on_real_pairs(model):
    floor = float(model["coupling"]["floors"]["x4"])
    rows = _training_rows(named=False)
    pairs = [(float(f["x4"]), *_final_nameless(float(f["x2_whole"]), float(f["x4"]), model))
             for f in rows]
    assert len(pairs) > 100 and _violations(pairs, floor) == {"겹침": 0, "다름": 0}


def test_named_goods_judgment_keeps_the_floor_when_goods_overlap(model):
    floor = float(model["coupling"]["floors"]["x4"])
    grid = _violations([p for p in _named_grid(model) if p[0] >= floor], floor)
    real = _violations([(float(f["x4"]), *_final_named(f, model))
                        for f in _training_rows(named=True) if float(f["x4"]) >= floor], floor)
    assert grid["겹침"] == 0 and real["겹침"] == 0


def test_named_goods_judgment_stays_at_or_below_the_pair_when_goods_differ(model):
    floor = float(model["coupling"]["floors"]["x4"])
    grid = _violations([p for p in _named_grid(model) if p[0] < floor], floor)
    real = _violations([(float(f["x4"]), *_final_named(f, model))
                        for f in _training_rows(named=True) if float(f["x4"]) < floor], floor)
    assert grid["다름"] == 0 and real["다름"] == 0
