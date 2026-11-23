"""logo_floor_image_only.py(견고성 점검 R-P0-1 3차 — 이름 있는 이미지 질의를 이미지만 판단과만
견주기)의 순수 함수·채택 판정과 logo_floor 표시(risk_model)."""

from __future__ import annotations

import pytest
from src.model import risk_model as rm

from scripts import logo_floor_image_only as lo


@pytest.fixture(scope="module")
def base() -> dict:
    return rm.load_model(rm.V141_MODEL_PATH)


def _summary(overall, *, success=None, photo=False):
    out = {"전체": overall, "상위": [], "ms": 10.0, "모델_ms": 1.0, "사진": photo}
    if success is not None:
        out["인정"] = [{"id": "1", "순위": 1 if success else 30, "등급": "위험"}]
        out["인정_성공"] = success
    return out


def test_settings_hash_is_stable_and_covers_rules():
    assert lo.rule_sha256() == lo.rule_sha256()
    assert {"변경", "바꾸기_전·후", "채택_1", "채택_2", "채택_3", "채택_4"} <= set(lo.RULE)


def test_candidate_only_adds_the_version_and_the_flag(base):
    new = lo.candidate_model(base)
    assert new["version"] == "risk_model_v1.4.2" and rm.logo_floor_enabled(new)
    assert not rm.logo_floor_enabled(base)
    for key in ("intercept", "coefficients", "grade_thresholds", "patterns", rm.NAMELESS_KEY,
                "standalone_thresholds", "figure_rule", "coupling"):
        assert new.get(key) == base.get(key), key


def test_flag_validation_rejects_malformed_values(base):
    rm.validate_model({**base, rm.LOGO_FLOOR_KEY: {"enabled": False}})
    with pytest.raises(ValueError):
        rm.validate_model({**base, rm.LOGO_FLOOR_KEY: {"enabled": "yes"}})
    with pytest.raises(ValueError):
        rm.validate_model({**base, rm.LOGO_FLOOR_KEY: True})


def test_image_only_grade_uses_the_name_free_level(base):
    assert lo.image_only_grade(1.0, base) == "위험"  # 도형계 0.634 ≥ 0.5724
    assert lo.image_only_grade(1.0, base, level="문자") == "검토 권장"  # ×도형계 없음 0.556
    assert lo.image_only_grade(0.41, base) == "안전"
    assert lo.higher("주의", "위험") == "위험" and lo.higher("위험", "주의") == "위험"


def _positives(flags: list[bool]) -> list[dict]:
    def block(flag: bool) -> dict:
        return {"전": _summary("주의", success=False), "후": _summary("위험", success=flag)}

    return [{"출원번호": str(i), "방식": {"업종 없음": block(f), "같은 업종": block(f)}}
            for i, f in enumerate(flags)]


def test_positive_condition_needs_ninety_five_percent():
    assert lo.check_positive(_positives([True] * 95 + [False] * 5))["통과"]
    assert not lo.check_positive(_positives([True] * 94 + [False] * 6))["통과"]


def _negatives(before: list[str], after: list[str]) -> list[dict]:
    rows = []
    for b, a in zip(before, after):
        named = {"전": _summary(b), "후": _summary(a)}
        rows.append({"이름": "x", "방식": {"이름+이미지": named, "이름+이미지+업종": named},
                     "이미지만": _summary("안전")})
    return rows


def test_negative_condition_limits_two_and_one_points():
    base_grades = ["주의"] * 100
    assert lo.check_negative(_negatives(base_grades, ["검토 권장"] * 2 + ["주의"] * 98))["통과"]
    assert not lo.check_negative(_negatives(base_grades,
                                            ["검토 권장"] * 3 + ["주의"] * 97))["통과"]
    assert not lo.check_negative(_negatives(base_grades, ["위험"] * 2 + ["주의"] * 98))["통과"]


def test_never_lower_excludes_photo_queries(base):
    searches = {"양성": [], "음성": [],
                "표본A": [{"질의": "A:1:this", "이름+이미지": {"후": _summary("주의")},
                          "이미지만": _summary("검토 권장")},
                         {"질의": "A:2:this", "이름+이미지": {"후": _summary("주의", photo=True)},
                          "이미지만": _summary("위험", photo=True)}]}
    result = lo.check_never_lower(searches, base)
    assert result["낮아진_경우"] == 1 and result["사진_질의(뺌)"] == 1
    assert result["사진_질의_중_낮아짐(보고만)"] == 1 and not result["통과"]
    searches["표본A"][0]["이름+이미지"]["후"] = _summary("위험")
    assert lo.check_never_lower(searches, base)["통과"]
