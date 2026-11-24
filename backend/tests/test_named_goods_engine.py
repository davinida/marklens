"""엔진의 업종 규칙(통합 모델 설계 §7-13) — 이름 있는 업종 하한(goods_floor_named: 업종이 겹치면
업종 없는 짝 판단의 등급 이상)·업종 상한(goods_cap: 업종이 다르면 짝 판단의 등급 이하, 이름 없는·
이름 있는 판단 모두). 이 키가 없는 JSON(≤ v1.4.5)은 예전 판단 그대로."""

from __future__ import annotations

import copy

from backend.src.core import multi_search as ms

rm = ms.rm  # 엔진이 쓰는 런타임(경로 설정은 엔진 모듈이 한다)


def _model() -> dict:
    return copy.deepcopy(rm.load_model(rm.V145_MODEL_PATH))


def _named(x1: float, x2t: float, x4: float | None) -> dict:
    return {"x1_d": x1, "x2_text_d": x2t, "x3_d": None, "x2_whole": None, "x4": x4,
            "has_meaning_both": False, "has_distinctive_part_a": True,
            "has_distinctive_part_b": True, "mark_type": "문자"}


def _nameless(x2: float, x4: float | None) -> dict:
    return {"x1_d": None, "x2_text_d": None, "x3_d": None, "x2_whole": x2, "x4": x4,
            "has_meaning_both": False, "has_distinctive_part_a": True,
            "has_distinctive_part_b": True, "mark_type": "도형"}


def test_without_the_new_keys_judgments_are_unchanged():
    model = _model()
    for features in (_named(0.16, 0.7, 0.01), _named(1.0, 1.0, 0.5), _named(0.5, 0.2, None)):
        judged, rank = ms._named_judgment(features, model, "문자")
        plain = ms._judge(features, model, "문자")
        assert judged == plain and rank == plain.rank
    assert "named" not in ms._thresholds(model)


def test_goods_cap_keeps_a_different_industry_at_the_pair_grade():
    model = _model()
    features = _named(0.16, 0.7, 0.01)  # v1.4.5: x4 집합 주의 0.093 > base 안전 0.080
    assert ms._judge(features, model, "문자").result.grade == "주의"
    model[rm.GOODS_CAP_KEY] = {"enabled": True}
    judged, rank = ms._named_judgment(features, model, "문자")
    pair = ms._judge({**features, "x4": None}, model, "문자")
    assert judged.result.pattern == "base" and judged.result.grade == pair.result.grade == "안전"
    assert ms.GOODS_CAP in judged.triggers and rank == pair.rank
    overlap, _ = ms._named_judgment({**features, "x4": 0.5}, model, "문자")
    assert overlap.result.pattern == "x4" and ms.GOODS_CAP not in overlap.triggers


def test_goods_cap_pair_grade_includes_the_rules_on_the_pair_judgment():
    """업종 상한의 짝 판단 등급은 단독 축 규칙 등 그 판단에 걸리는 규칙까지 반영한 등급이다(§7-13 —
    v1.4.6 결정의 정의): 업종이 달라 내려가도 짝 판단의 단독 규칙 검토 권장 아래로는 가지 않는다."""
    model = _model()
    block = model["patterns"]["x4"]
    block["intercept"] = round(block["intercept"] + 4.0, 4)  # 업종 집합이 짝보다 높게(장난감)
    model[rm.GOODS_CAP_KEY] = {"enabled": True}
    features = _named(0.0, 0.8, 0.01)  # 철자 0.8 — 단독 규칙(x2_text ≥ 0.75)으로 검토 권장
    raised = ms._judge(features, model, "문자")
    pair = ms._judge({**features, "x4": None}, model, "문자")
    assert raised.result.grade == "위험"
    assert pair.result.prob < 0.0902  # 짝은 위험도로만 보면 안전
    assert "standalone_x2_text" in pair.triggers and pair.result.grade == "검토 권장"
    judged, rank = ms._named_judgment(features, model, "문자")
    assert judged.result.grade == "검토 권장" and ms.GOODS_CAP in judged.triggers
    assert "standalone_x2_text" in judged.triggers and rank == pair.rank


def test_named_goods_floor_needs_the_goods_rule():
    model = _model()
    block = model["patterns"]["x4"]
    block["intercept"] = round(block["intercept"] - 2.0, 4)  # 업종을 넣으면 크게 내려가는 집합
    features = _named(1.0, 1.0, 0.5)
    lowered, _ = ms._named_judgment(features, model, "문자")
    pair = ms._judge({**features, "x4": None}, model, "문자")
    assert rm.GRADES.index(lowered.result.grade) < rm.GRADES.index(pair.result.grade)  # 규칙 없음
    block[rm.GOODS_RULE_KEY] = rm.GOODS_RULE_NO_RAISE
    judged, rank = ms._named_judgment(features, model, "문자")
    assert judged.result.pattern == "base" and judged.result.grade == pair.result.grade
    assert ms.GOODS_FLOOR_NAMED in judged.triggers and rank == max(lowered.rank, pair.rank)
    below, _ = ms._named_judgment({**features, "x4": 0.0251}, model, "문자")
    assert below.result.pattern == "x4" and ms.GOODS_FLOOR_NAMED not in below.triggers


def test_goods_cap_on_the_nameless_side():
    model = _model()
    block = model[rm.NAMELESS_KEY]["x2_whole+x4"]
    # 업종이 조금만 겹쳐도 이미지만보다 높은 집합
    block["intercept"] = round(block["intercept"] + 1.5, 4)
    hits = []
    for step in range(0, 101):
        features = _nameless(step / 100, 0.01)
        judged, _ = ms._nameless_judgment(features, model, "도형")
        alone = ms._judge({**features, "x4": None}, model, "도형")
        if rm.GRADES.index(judged.result.grade) > rm.GRADES.index(alone.result.grade):
            hits.append(step)
    assert hits  # 상한이 꺼져 있으면 업종이 달라도 더 높다
    model[rm.GOODS_CAP_KEY] = {"enabled": True}
    for step in hits:
        features = _nameless(step / 100, 0.01)
        judged, rank = ms._nameless_judgment(features, model, "도형")
        alone = ms._judge({**features, "x4": None}, model, "도형")
        assert judged.result.grade == alone.result.grade and ms.GOODS_CAP in judged.triggers
        assert judged.result.pattern == "noname:x2_whole" and rank == alone.rank


def test_named_thresholds_appear_in_meta_only_when_set():
    model = _model()
    model["patterns"]["x4"]["grade_thresholds"] = {"주의": 0.0902, "검토 권장": 0.55, "위험": 0.62}
    assert ms._thresholds(model)["named"] == {"x4": {"주의": 0.0902, "검토 권장": 0.55,
                                                     "위험": 0.62}}
    assert ms.rank_position(0.56, model, "x4")[0] == rm.GRADES.index("검토 권장")
    assert ms.rank_position(0.56, model, "base")[0] == rm.GRADES.index("검토 권장")
    assert ms.rank_position(0.6, model, "x4")[0] == rm.GRADES.index("검토 권장")
    assert ms.rank_position(0.6, model, "base")[0] == rm.GRADES.index("위험")
