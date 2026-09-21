"""상품↔유사군 변환표 로더 테스트 — 10건짜리 fixture JSON(aliases 포함), 실제 변환표 불필요."""

import gzip
import json

import pytest
from src.axes import goods_map
from src.axes.goods_map import (
    NICE_CLASS_TITLES,
    TIER_EXACT,
    TIER_PARTIAL,
    TIER_PREFIX,
    GoodsMap,
    load_goods_map,
    normalize,
)

SUFFIXES = ("도매업", "소매업", "중개업", "판매대행업", "판매알선업", "구매대행업")
COSMETICS_35 = "화장품 판매업(도소매·중개·대행)"
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
    {"name": "화장품용 스펀지", "nice_class": 21, "similarity_codes": ["G4001"]},
    {"name": "기능성 화장품", "nice_class": 3, "similarity_codes": ["G1201"]},
    {"name": "커피", "nice_class": 30, "similarity_codes": ["G0502"]},
    _class35("커피", "S2039"),
    {"name": "의류", "nice_class": 25, "similarity_codes": ["G430301", "G450101"]},
    {"name": "신발", "nice_class": 25, "similarity_codes": ["G4503"]},
    {"name": "장갑", "nice_class": 25, "similarity_codes": ["G4501"]},
    {"name": "장갑", "nice_class": 28, "similarity_codes": ["G5701"]},
]


@pytest.fixture(scope="module")
def fixture_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("goods") / "goods_map.json"
    path.write_text(json.dumps(FIXTURE, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def gm(fixture_path) -> GoodsMap:
    return load_goods_map(fixture_path)


def test_loads_all_entries_and_aliases(gm, fixture_path):
    assert len(gm) == 10
    assert gm.alias_count == 12
    assert gm.path == fixture_path


def test_search_ranks_exact_then_prefix_then_partial(gm):
    names = [(m.name, m.tier, m.matched_alias) for m in gm.search("화장품")]
    assert names == [
        ("화장품", TIER_EXACT, None),
        ("화장품용 스펀지", TIER_PREFIX, None),  # 접두 안에서는 짧은 name 이 먼저
        (COSMETICS_35, TIER_PREFIX, None),  # name 도 접두 일치 → alias 표기 없음
        ("기능성 화장품", TIER_PARTIAL, None),
    ]


def test_search_matches_alias_and_reports_it(gm):
    hits = gm.search("화장품 소매업")
    assert [(m.name, m.tier, m.matched_alias) for m in hits] == [
        (COSMETICS_35, TIER_EXACT, "화장품 소매업")
    ]
    assert hits[0].similarity_codes == ("S2012",)

    partial = gm.search("소매업")
    assert [(m.name, m.matched_alias) for m in partial] == [
        (COFFEE_35, "커피 소매업"),  # 같은 순위면 짧은 name 이 먼저
        (COSMETICS_35, "화장품 소매업"),
    ]
    assert all(m.tier == TIER_PARTIAL for m in partial)


def test_search_normalizes_case_width_and_spaces(gm):
    assert [m.name for m in gm.search("  화장품   소매업 ")] == [COSMETICS_35]
    assert normalize("ＡＢＣ  def") == "abc def"


def test_search_limit_and_class_filter(gm):
    assert [m.name for m in gm.search("화장품", limit=2)] == ["화장품", "화장품용 스펀지"]
    assert gm.search("화장품", limit=0) == []
    assert [m.name for m in gm.search("화장품", nice_class=3)] == ["화장품", "기능성 화장품"]
    assert [m.name for m in gm.search("화장품", nice_class=35)] == [COSMETICS_35]
    assert gm.search("화장품", nice_class=44) == []


def test_search_blank_or_unknown_query_is_empty(gm):
    assert gm.search("") == []
    assert gm.search("   ") == []
    assert gm.search("없는상품") == []


def test_codes_for_name_alias_class_and_union(gm):
    assert gm.codes_for("화장품") == frozenset({"G1201", "S120907", "S128302"})
    assert gm.codes_for("화장품", nice_class=3) == frozenset({"G1201", "S120907", "S128302"})
    assert gm.codes_for("화장품", nice_class=35) == frozenset()  # 35류에는 '화장품' 이름이 없음
    assert gm.codes_for("화장품 소매업") == frozenset({"S2012"})  # alias 정확 일치
    assert gm.codes_for("장갑") == frozenset({"G4501", "G5701"})  # 여러 류 → 합집합
    assert gm.codes_for("장갑", nice_class=28) == frozenset({"G5701"})
    assert gm.codes_for("장") == frozenset()  # 부분 일치는 안 됨
    assert gm.codes_for("없는상품") == frozenset()
    assert gm.codes_for("") == frozenset()


def test_classes_cover_all_45_with_counts(gm):
    classes = gm.classes()
    assert [c["nice_class"] for c in classes] == list(range(1, 46))
    counts = {c["nice_class"]: c["count"] for c in classes}
    assert counts[3] == 2 and counts[25] == 3 and counts[35] == 2 and counts[44] == 0
    assert sum(counts.values()) == 10
    assert len(NICE_CLASS_TITLES) == 45 and all(NICE_CLASS_TITLES[c] for c in range(1, 46))


def test_gzip_file_loads_the_same(fixture_path, tmp_path):
    gz_path = tmp_path / "goods_map.json.gz"
    with gzip.open(gz_path, "wt", encoding="utf-8") as handle:
        json.dump(FIXTURE, handle, ensure_ascii=False)
    gz = load_goods_map(gz_path)
    assert len(gz) == 10
    assert gz.codes_for("커피 도매업") == frozenset({"S2039"})


def test_load_is_cached_per_path(fixture_path):
    assert load_goods_map(fixture_path) is load_goods_map(str(fixture_path))


def test_env_var_selects_path(fixture_path, monkeypatch):
    monkeypatch.setenv(goods_map.ENV_PATH, str(fixture_path))
    assert load_goods_map() is load_goods_map(fixture_path)


def test_missing_file_error_lists_searched_locations(tmp_path, monkeypatch):
    missing = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError) as excinfo:
        load_goods_map(missing)
    assert str(missing) in str(excinfo.value)

    monkeypatch.delenv(goods_map.ENV_PATH, raising=False)
    monkeypatch.setattr(
        goods_map, "DEFAULT_CANDIDATES", (tmp_path / "a.json.gz", tmp_path / "b.json")
    )
    with pytest.raises(FileNotFoundError) as excinfo:
        load_goods_map()
    message = str(excinfo.value)
    assert "a.json.gz" in message and "b.json" in message and goods_map.ENV_PATH in message
