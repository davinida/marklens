"""업종 세트(business_presets.json) 로더 테스트 — 픽스처로 검증 규칙, 실제 gz 로 존재 검증(로컬).

실행: MARKLENS_FAKE_ML=1 ml/venv/bin/python -m pytest ml/tests/test_goods_presets.py -q  # CI
      ml/venv/bin/python -m pytest ml/tests/test_goods_presets.py -q                       # 실제 gz
"""

import json
import os

import pytest
from src.axes import goods_map
from src.axes.goods_map import (
    DEFAULT_CANDIDATES,
    DEFAULT_PRESETS_PATH,
    GoodsMap,
    load_business_presets,
    load_goods_map,
)

SUFFIXES = ("도매업", "소매업", "중개업", "판매대행업", "판매알선업", "구매대행업")
COFFEE_35 = "커피 판매업(도소매·중개·대행)"


def _class35(base: str, code: str) -> dict:
    return {
        "name": f"{base} 판매업(도소매·중개·대행)",
        "nice_class": 35,
        "similarity_codes": [code],
        "aliases": [f"{base} {suffix}" for suffix in SUFFIXES],
    }


FIXTURE = [
    {"name": "화장품", "nice_class": 3, "similarity_codes": ["G1201", "S120907", "S128302"]},
    _class35("화장품", "S2012"),
    {"name": "커피", "nice_class": 30, "similarity_codes": ["G0502"]},
    _class35("커피", "S2039"),
    {"name": "의류", "nice_class": 25, "similarity_codes": ["G430301", "G450101"]},
]

PRESETS = [
    {
        "id": "cafe",
        "업종명": "카페",
        "이모지": "☕",
        "hint": " 테스트 힌트 ",
        "별칭": ["카페", "커피숍", " 커피집 ", "커피숍"],
        "지정상품": [
            {"name": "커피", "nice_class": 30},
            {"name": "커피 소매업", "nice_class": 35},
            {"name": "없는상품", "nice_class": 43},
            {"name": "커피", "nice_class": 99},
        ],
    },
    {
        "id": "cosmetics",
        "업종명": "화장품 브랜드",
        "별칭": ["화장품"],
        "지정상품": [{"name": "화장품", "nice_class": 3}],
    },
    {
        "id": "ghost",
        "업종명": "유령",
        "별칭": ["유령"],
        "지정상품": [{"name": "없는상품", "nice_class": 1}],
    },
    {"id": "", "업종명": "무명", "지정상품": [{"name": "의류", "nice_class": 25}]},
]


@pytest.fixture(scope="module")
def gm(tmp_path_factory) -> GoodsMap:
    path = tmp_path_factory.mktemp("presets") / "goods_map.json"
    path.write_text(json.dumps(FIXTURE, ensure_ascii=False), encoding="utf-8")
    return load_goods_map(path)


@pytest.fixture(scope="module")
def presets_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("presets") / "business_presets.json"
    path.write_text(json.dumps(PRESETS, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def presets(gm, presets_path):
    return load_business_presets(gm, presets_path)


def test_find_matches_name_or_alias_with_class(gm):
    assert gm.find("커피", 30) is not None
    assert gm.find(" 커피 ", 30) is not None  # 정규화(공백)
    assert gm.find("커피 소매업", 35).name == COFFEE_35  # alias
    assert gm.find("커피", 35) is None  # 류가 다르면 없음
    assert gm.find("", 30) is None and gm.find("없는상품", 1) is None


def test_valid_names_resolve_by_name_and_alias(presets, presets_path):
    assert presets.path == presets_path
    cafe = presets.get("cafe")
    assert cafe is not None and cafe.label == "카페" and cafe.emoji == "☕"
    assert cafe.aliases == ("카페", "커피숍", "커피집")  # 공백 정리·중복 제거
    assert cafe.hint == "테스트 힌트" and presets.get("cosmetics").hint == ""
    assert [(g.name, g.nice_class, g.similarity_codes) for g in cafe.goods] == [
        ("커피", 30, ("G0502",)),
        ("커피 소매업", 35, ("S2039",)),  # JSON 에 적은 alias 를 그대로 두고 유사군만 해석
    ]
    assert presets.get("cosmetics").emoji == ""


def test_unknown_names_are_excluded_and_empty_or_invalid_presets_dropped(presets):
    assert [p.id for p in presets.presets] == ["cafe", "cosmetics"]
    assert any("cafe" in w and "'없는상품'(43류)" in w for w in presets.warnings)
    assert any("cafe" in w and "(99류)" in w for w in presets.warnings)  # 범위 밖 류
    assert any("ghost" in w and "제외" in w for w in presets.warnings)
    assert any("id/업종명 누락" in w for w in presets.warnings)


def test_match_is_partial_on_label_or_alias_in_file_order(presets):
    assert [p.id for p in presets.match("카페")] == ["cafe"]
    assert [p.id for p in presets.match("커피")] == ["cafe"]  # 별칭 '커피숍'에 부분 일치
    assert [p.id for p in presets.match("화장")] == ["cosmetics"]  # 업종명 '화장품 브랜드'
    assert presets.match("장갑") == [] and presets.match("") == [] and presets.match("   ") == []
    assert presets.match("커피", limit=0) == []


def test_missing_file_gives_empty_presets_with_warning(gm, tmp_path):
    empty = load_business_presets(gm, tmp_path / "none.json")
    assert len(empty) == 0 and empty.path is None and len(empty.warnings) == 1
    assert empty.match("카페") == []


def test_env_var_selects_presets_path(gm, presets_path, monkeypatch):
    monkeypatch.setenv(goods_map.ENV_PRESETS_PATH, str(presets_path))
    assert len(load_business_presets(gm)) == 2
    monkeypatch.setenv(goods_map.ENV_PRESETS_PATH, str(presets_path.parent / "missing.json"))
    assert len(load_business_presets(gm)) == 0


REAL_GZ = DEFAULT_CANDIDATES[0]
LOCAL_ONLY = (
    bool(os.getenv("MARKLENS_FAKE_ML"))
    or not REAL_GZ.is_file()
    or not DEFAULT_PRESETS_PATH.is_file()
)


@pytest.mark.slow
@pytest.mark.skipif(
    LOCAL_ONLY,
    reason="로컬 전용: 실제 gz 로 business_presets.json 의 명칭 존재 확인(CI 는 FAKE 픽스처)",
)
def test_real_presets_all_names_exist_in_real_goods_map():
    real = load_business_presets(load_goods_map(REAL_GZ), DEFAULT_PRESETS_PATH)
    assert real.warnings == ()  # 변환표에 없는 명칭·빈 세트가 없다
    assert len(real) == 25
    assert len({p.id for p in real.presets}) == 25
    for preset in real.presets:
        assert 2 <= len(preset.goods) <= 4
        assert preset.label and preset.aliases and preset.emoji
        assert all(g.similarity_codes for g in preset.goods)
    assert real.get("software").hint.startswith("앱 자체(9류)")
    # 35류 소매업 명칭은 병합 항목의 alias 로 해석돼 유사군이 붙는다
    retail = [g.similarity_codes for g in real.get("cafe").goods if g.nice_class == 35]
    assert retail == [("S2005",)]
