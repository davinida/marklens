"""shared/goods_map 파서·검증기 단위 테스트 (openpyxl 불필요 — 순수 함수만 다룬다).

CI 의 pytest 는 backend/tests 와 ml/tests 만 돌기 때문에 여기에 둔다. shared/goods_map 은
패키지가 아니므로 sys.path 로 주입해 import 한다.
"""

import sys
from pathlib import Path

import pytest

GOODS_MAP_DIR = Path(__file__).resolve().parents[2] / "shared" / "goods_map"
if str(GOODS_MAP_DIR) not in sys.path:
    sys.path.insert(0, str(GOODS_MAP_DIR))

import parse_goods_map  # noqa: E402
import validate_goods_map  # noqa: E402

SUFFIXES = parse_goods_map._CLASS35_SERVICE_SUFFIXES
COLLAPSED = "화장품 판매업(도소매·중개·대행)"


def _class35(base: str, codes: set[str], suffixes=SUFFIXES) -> dict:
    """원본처럼 '{상품} {접미사}' 6행을 (name, 35) -> 코드 집합 으로 만든다."""
    return {(f"{base} {suffix}", 35): set(codes) for suffix in suffixes}


def test_six_services_with_same_codes_collapse_and_keep_aliases():
    result = parse_goods_map._collapse_class35_services(_class35("화장품", {"S2039"}))

    assert len(result) == 1
    entry = result[0]
    assert entry["name"] == COLLAPSED
    assert entry["nice_class"] == 35
    assert entry["similarity_codes"] == ["S2039"]
    assert entry["aliases"] == [f"화장품 {suffix}" for suffix in SUFFIXES]
    assert len(set(entry["aliases"])) == len(SUFFIXES)


def test_partial_services_are_kept_as_is_without_aliases():
    merged = _class35("화장품", {"S2039"}, suffixes=("도매업", "소매업"))
    result = parse_goods_map._collapse_class35_services(merged)

    assert [e["name"] for e in result] == ["화장품 도매업", "화장품 소매업"]
    assert all("aliases" not in e for e in result)


def test_six_services_with_different_codes_are_not_collapsed():
    # 현재 규칙: 접미사별 코드가 하나라도 다르면 합집합으로 합치지 않고 6건을 각각 유지한다
    merged = _class35("의약품", {"S2043"})
    merged[("의약품 중개업", 35)] = {"S2043", "S2099"}
    result = parse_goods_map._collapse_class35_services(merged)

    assert len(result) == len(SUFFIXES)
    by_name = {e["name"]: e for e in result}
    assert by_name["의약품 중개업"]["similarity_codes"] == ["S2043", "S2099"]
    assert by_name["의약품 도매업"]["similarity_codes"] == ["S2043"]
    assert all("aliases" not in e for e in result)


def test_genuine_class35_service_and_other_classes_pass_through():
    merged = {
        ("광고중개업", 35): {"S0401"},
        ("화장품", 3): {"S128302", "G1201", "S120907"},
    }
    result = parse_goods_map._collapse_class35_services(merged)

    by_name = {e["name"]: e for e in result}
    assert set(by_name) == {"광고중개업", "화장품"}
    assert by_name["광고중개업"]["similarity_codes"] == ["S0401"]
    assert by_name["화장품"]["similarity_codes"] == ["G1201", "S120907", "S128302"]
    assert all("aliases" not in e for e in result)


VALID = [
    {"name": "화장품", "nice_class": 3, "similarity_codes": ["G1201", "S120907", "S128302"]},
    {
        "name": COLLAPSED,
        "nice_class": 35,
        "similarity_codes": ["S2039"],
        "aliases": [f"화장품 {suffix}" for suffix in SUFFIXES],
    },
]


def test_validate_accepts_valid_entries():
    assert validate_goods_map.validate(VALID) == []


@pytest.mark.parametrize(
    ("broken", "fragment"),
    [
        ({"name": " ", "nice_class": 3, "similarity_codes": ["G1201"]}, "name이 비어있음"),
        ({"name": "상품", "nice_class": 3, "similarity_codes": ["12AB"]}, "유사군코드 형식 이상"),
        (
            {
                "name": "상품 판매업(도소매·중개·대행)",
                "nice_class": 35,
                "similarity_codes": ["S2039"],
                "aliases": ["상품 도매업", "상품 도매업"],
            },
            "aliases 중복",
        ),
        (
            {
                "name": "상품 판매업(도소매·중개·대행)",
                "nice_class": 35,
                "similarity_codes": ["S2039"],
                "aliases": ["화장품"],
            },
            "name과 충돌",
        ),
    ],
)
def test_validate_reports_each_error(broken, fragment):
    errors = validate_goods_map.validate(VALID + [broken])
    assert any(fragment in msg for msg in errors), errors


def test_find_entries_matches_aliases_and_reports_which_alias():
    hits = validate_goods_map.find_entries(VALID, "화장품 소매업")
    assert [(e["name"], via) for e, via in hits] == [(COLLAPSED, ["화장품 소매업"])]

    hits = validate_goods_map.find_entries(VALID, "화장품")
    assert [e["name"] for e, _via in hits] == ["화장품", COLLAPSED]
    assert all(via == [] for _e, via in hits)  # name 일치는 alias 표기 없음
