"""쌍별 축 공용 함수(ml/src/axes/pair_axes.py) — 서비스와 학습이 같은 식인지(E-2 회귀), 게이트·요부
정보, 모델 입력 키."""

from __future__ import annotations

import pytest
from src.axes import pair_axes as pa
from src.axes.distinctiveness import Distinctiveness, goods_index, load_distinctiveness
from src.axes.goods_map import GoodsEntry, GoodsMap
from src.model import risk_model as rm

from scripts import pairs_features as pf

# 정답 데이터 10쌍(이름A·이름B·이 사건 유사군·상대 유사군 — labels.csv 의 goods_codes_this/prior
# 앞부분).
# 접미 분리(E-3)에 걸리는 쌍 2개(메가커피·캡슐커피)를 포함한다.
FIXTURE = [
    ("Cool Touch", "쿨터치 COOL TOUCH", "G2102", "G120401;G1302;G1401;G1701"),
    ("DREAM", "Hello Dream!", "G4401;G4509;G4510", "G1002;G110303;G1401;G1803"),
    ("SPINNER", "SPINOS", "", "G390102;G3905;G390601;G390701"),
    ("SPINNER", "SPINA", "", ""),
    ("RIP ROLLS", "RIP ROLL", "", "G0301"),
    ("Fleurance nature", "프로랑스 PRORANCE", "", "G1201;S120907;S128302"),
    ("GATE", "Gate", "G3402;G3404;G390701", "G1824;G2202;G3002;G3402"),
    ("메가커피", "MEGA MGC COFFEE BIG SIZE 2 SHOT", "G0502;S120602", "G0502"),
    ("CoffeeRoad", "coffee lord 커피로드 캡슐커피", "G0502", "G0502;S120602"),
    ("야콘 YACON", "참야콘 야콘냉면", "G0301", "G0301;G0502"),
]

SMALL_GOODS = GoodsMap([
    GoodsEntry("커피", 30, ("G0301",)),
    GoodsEntry("화장품", 3, ("G1201",)),
])


def _codes(text: str) -> frozenset[str]:
    return frozenset(c for c in text.split(";") if c)


@pytest.fixture(scope="module")
def real_model() -> Distinctiveness:
    return load_distinctiveness()


@pytest.fixture
def small_model() -> Distinctiveness:
    names, classes = goods_index(SMALL_GOODS)
    return Distinctiveness({"gate": (12, 30)}, famous={"스타벅스"}, goods_names=names,
                           code_classes=classes, descriptive={})


@pytest.mark.parametrize("name_a,name_b,goods_a,goods_b", FIXTURE)
def test_matches_training_name_axes(real_model, name_a, name_b, goods_a, goods_b):
    """서비스 축 계산 == 학습 특징(pairs_features.name_axes) — 같은 입력에 같은 값(소수 4자리)."""
    codes_a, codes_b = _codes(goods_a), _codes(goods_b)
    axes = pa.compute_pair_axes(name_a, name_b, model=real_model, goods_a=codes_a, goods_b=codes_b)
    ref = pf.name_axes(name_a, name_b, codes_a | codes_b, real_model)
    assert f"{axes.x1_raw:.4f}" == ref["x1_d"]
    assert f"{axes.x2_text_raw:.4f}" == ref["x2_text_d"]
    assert f"{axes.x3_raw:.4f}" == ref["x3_d"]
    assert int(axes.has_distinctive_a) == ref["has_distinctive_part_a"]
    assert int(axes.has_distinctive_b) == ref["has_distinctive_part_b"]
    goods = (codes_a | codes_b) or None
    assert ";".join(sorted(real_model.weak_tokens(axes.name_a, goods))) == ref["weak_a"]
    assert ";".join(sorted(real_model.weak_tokens(axes.name_b, goods))) == ref["weak_b"]


def test_suffix_split_applies_to_both_sides(real_model):
    axes = pa.compute_pair_axes("메가커피", "캡슐커피", model=real_model, goods_a={"G0502"},
                                goods_b={"G0502"})
    assert axes.name_a == "메가 커피" and axes.name_b == "캡슐 커피"
    assert [item.token for item in axes.removed] == ["커피"]
    assert axes.removed[0].side == "both" and "1호 보통명칭" in axes.removed[0].reason


def test_removed_tokens_sides_and_salient(small_model):
    axes = pa.compute_pair_axes("블루커피", "Zorbix 커피", model=small_model, goods_a={"G0301"},
                                goods_b={"G0301"})
    assert axes.name_a == "블루 커피"
    assert axes.query_tokens == ("블루",) and axes.candidate_tokens == ("zorbix",)
    assert [(r.token, r.side) for r in axes.removed] == [("커피", "both")]
    assert axes.removed[0].reason == "1호 보통명칭"
    assert axes.x4 == 1.0 and axes.has_goods_both
    assert axes.has_distinctive_a and axes.has_distinctive_b


def test_gates_null_but_model_values_follow_training(small_model):
    # 기호만: 호칭·철자 없음 → 표시값 None, 모델 입력(원 값)은 함수가 주는 0.0
    axes = pa.compute_pair_axes("☆☆", "GATE", model=small_model)
    assert axes.x1 is None and axes.x2_text is None and axes.x3 is None and axes.x4 is None
    assert axes.x1_raw == 0.0 and axes.x2_text_raw == 0.0
    assert not axes.has_pronunciation_both and not axes.has_spelling_both
    assert not axes.has_goods_both
    features = axes.model_features(x2_img=None, mark_type="문자")
    values = rm.design_values(features)
    assert values["miss_x3"] == 1.0 and values["miss_x4"] == 1.0 and values["miss_x2img"] == 1.0


def test_x3_disabled_marks_meaning_missing(small_model):
    axes = pa.compute_pair_axes("왕", "KING", model=small_model, x3_enabled=False)
    assert axes.x3 is None and axes.x3_raw == 0.0 and not axes.has_meaning_both
    assert rm.design_values(axes.model_features(x2_img=None, mark_type="문자"))["miss_x3"] == 1.0


def test_model_features_match_coefficient_json_inputs(small_model):
    """모델 입력 키가 계수 JSON 입력 정의(설계 항)와 1:1 — risk_score 가 그대로 받는다."""
    axes = pa.compute_pair_axes("블루커피", "레드커피", model=small_model, goods_a={"G0301"},
                                goods_b={"G0301"})
    features = axes.model_features(x2_img=0.5, mark_type="문자")
    assert set(features) == {
        "x1_d", "x2_text_d", "x2_whole", "x3_d", "x4", "has_meaning_both",
        "has_distinctive_part_a", "has_distinctive_part_b", "mark_type",
        "x2_text_version",  # 철자 정의 버전(기본 1) — 런타임이 모델과 대조한다
    }
    assert features["x2_text_version"] == 1 == axes.spelling_version
    model = rm.load_model()
    values = rm.design_values(features)
    assert set(model["features"]) <= set(values)
    result = rm.risk_score(features, model)
    assert 0.0 < result.prob < 1.0 and result.grade in rm.GRADES


def test_clean_name_and_codes():
    assert pa.clean_name("  블루　커피  ") == "블루 커피"  # NFKC: 전각 공백 → 공백, 연속 공백 정리
    assert pa.clean_name(None) == ""
    assert pa.normalize_codes(["g0502", " S120602 ", "", None]) == frozenset({"G0502", "S120602"})
    assert pa.normalize_codes("G0301") == frozenset({"G0301"})


@pytest.mark.parametrize("version", [1, 2])
def test_spelling_version_matches_training_columns(real_model, version):
    """서비스 축(compute_pair_axes)의 철자는 학습 특징(name_axes)의 같은 버전 열과 같다 — v1 은
    x2_text_d, v2 는 x2_text_d_v2."""
    column = "x2_text_d" if version == 1 else "x2_text_d_v2"
    for name_a, name_b, goods in (("블루 보틀 커피", "블루 핸즈 커피", "G0301"),
                                  ("GATE HELLO", "GATE WORLD", ""),
                                  ("닥치고 떡볶이", "떡볶이 명가", "G0301;G0302"),
                                  ("스타벅스", "스타박스", "G0301")):
        codes = _codes(goods)
        axes = pa.compute_pair_axes(name_a, name_b, model=real_model, goods_a=codes,
                                    goods_b=codes, spelling_version=version)
        row = pf.name_axes(name_a, name_b, codes, real_model)
        assert axes.spelling_version == version
        assert round(axes.x2_text_raw, 4) == float(row[column]), (name_a, name_b, version)
        assert axes.model_features(x2_img=None, mark_type="문자")["x2_text_version"] == version
    assert pa.compute_pair_axes("GATE HELLO", "GATE WORLD", model=real_model).spelling_version == 1


def test_runtime_rejects_spelling_version_mismatch(small_model):
    """계수 JSON 의 철자 버전(axis_versions, 없으면 1)과 입력의 x2_text_version 이 다르면
    ValueError — x2_text_d 가 관측된 입력만. v1.3·v1.4 JSON 은 버전 표기 없는 입력도 그대로
    받는다."""
    import copy

    v13 = rm.load_model(rm.V13_MODEL_PATH)
    assert rm.spelling_version(v13) == 1
    axes_v1 = pa.compute_pair_axes("블루커피", "레드커피", model=small_model)
    axes_v2 = pa.compute_pair_axes("블루커피", "레드커피", model=small_model, spelling_version=2)
    features_v1 = axes_v1.model_features(x2_img=None, mark_type="문자")
    assert rm.risk_score(features_v1, v13).prob > 0
    legacy = {k: v for k, v in features_v1.items() if k != "x2_text_version"}
    assert tuple(rm.risk_score(legacy, v13)) == tuple(rm.risk_score(features_v1, v13))
    with pytest.raises(ValueError, match="철자 버전"):
        rm.risk_score(axes_v2.model_features(x2_img=None, mark_type="문자"), v13)
    v15 = copy.deepcopy(v13)
    v15["version"] = "risk_model_v1.5"
    v15[rm.AXIS_VERSIONS_KEY] = {rm.SPELLING_AXIS: 2}
    rm.validate_model(v15)
    assert rm.spelling_version(v15) == 2
    assert rm.risk_score(axes_v2.model_features(x2_img=None, mark_type="문자"), v15).prob > 0
    for wrong in (features_v1, legacy):  # 버전 표기가 없으면 v1 로 본다
        with pytest.raises(ValueError, match="철자 버전"):
            rm.risk_score(wrong, v15)
    nameless = {"x1_d": None, "x2_text_d": None, "x2_whole": 0.8, "mark_type": "도형"}
    assert rm.risk_score(nameless, v15).prob > 0  # 철자가 결측이면 검사하지 않는다
    for broken in ({"x2_text": 3}, {"x9": 1}, [2]):
        with pytest.raises(ValueError, match="axis_versions"):
            rm.validate_model({**v15, rm.AXIS_VERSIONS_KEY: broken})
