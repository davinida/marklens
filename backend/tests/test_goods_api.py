"""GET /goods/search · /goods/classes 계약 테스트 — FAKE_ML 픽스처(변환표 10건, 제35류 병합 2건).

conftest 가 가짜 ML 환경에 goods_map.json(10건) 을 만들고 MARKLENS_GOODS_MAP_PATH 로 가리킨다.
KIPRIS 키·네트워크·실제 변환표 불필요.
"""

import pytest
from fastapi.testclient import TestClient

from backend.src.core import goods
from backend.src.core.ratelimit import limiter

COSMETICS_35 = "화장품 판매업(도소매·중개·대행)"
COFFEE_35 = "커피 판매업(도소매·중개·대행)"


@pytest.fixture(scope="module")
def client():
    from backend.src.main import app

    # with 블록이 lifespan(엔진 + 발음 캐시 + 상품 변환표 적재)을 실행한다
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """운영 한도(60/min)를 유지하면서 케이스마다 카운터를 초기화한다."""
    limiter.reset()
    yield
    limiter.reset()


def test_goods_map_is_loaded_at_startup(client):
    assert goods.state.ready is True
    assert goods.state.error == ""
    assert goods.state.entry_count == 10
    assert goods.state.alias_count == 12
    assert goods.state.path.endswith("goods_map.json")


def test_openapi_exposes_both_get_routes(client):
    paths = client.app.openapi()["paths"]
    assert "get" in paths["/goods/search"]
    assert "get" in paths["/goods/classes"]


def test_search_contract_and_ranking(client):
    response = client.get("/goods/search", params={"q": "화장품"})
    assert response.status_code == 200
    body = response.json()

    assert body["query"] == "화장품"
    assert body["source"] == goods.SOURCE == "지식재산처 고시상품명칭 13판(2026), 공공누리 제1유형"
    assert body["total"] == 4
    # 정확 > 접두(짧은 name 먼저) > 부분
    assert [m["name"] for m in body["matches"]] == [
        "화장품",
        "화장품용 스펀지",
        COSMETICS_35,
        "기능성 화장품",
    ]
    assert body["matches"][0] == {
        "name": "화장품",
        "nice_class": 3,
        "similarity_codes": ["G1201", "S120907", "S128302"],
        "matched_alias": None,
    }


def test_search_hits_alias_and_reports_it(client):
    body = client.get("/goods/search", params={"q": "화장품 소매업"}).json()
    assert body["total"] == 1
    assert body["matches"] == [
        {
            "name": COSMETICS_35,
            "nice_class": 35,
            "similarity_codes": ["S2012"],
            "matched_alias": "화장품 소매업",
        }
    ]


def test_search_class_filter_and_limit(client):
    filtered = client.get("/goods/search", params={"q": "화장품", "nice_class": 3}).json()
    assert [m["name"] for m in filtered["matches"]] == ["화장품", "기능성 화장품"]
    assert filtered["total"] == 2

    limited = client.get("/goods/search", params={"q": "화장품", "limit": 2}).json()
    assert [m["name"] for m in limited["matches"]] == ["화장품", "화장품용 스펀지"]
    assert limited["total"] == 4  # total 은 limit 과 무관


def test_search_strips_query_and_handles_no_match(client):
    body = client.get("/goods/search", params={"q": "  커피  "}).json()
    assert body["query"] == "커피"
    assert body["matches"][0]["name"] == "커피"

    body = client.get("/goods/search", params={"q": "없는상품"}).json()
    assert body == {
        "query": "없는상품",
        "matches": [],
        "total": 0,
        "offset": 0,
        "presets": [],
        "source": goods.SOURCE,
    }


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "   "},
        {"q": "가" * 51},
        {"q": "커피", "limit": 0},
        {"q": "커피", "limit": 51},
        {"q": "커피", "nice_class": 0},
        {"q": "커피", "nice_class": 46},
        {"q": "커피", "nice_class": "x"},
        {"q": "커피", "offset": -1},
        {"nice_class": 25, "offset": 100_001},
    ],
)
def test_invalid_params_are_422(client, params):
    assert client.get("/goods/search", params=params).status_code == 422


def test_missing_query_and_class_is_422_with_reason(client):
    """q 도 nice_class 도 없으면(공백 q 포함) 422 + 이유. 류 번호만 있으면 목록 보기로 200."""
    for params in ({}, {"q": ""}, {"q": "   "}):
        response = client.get("/goods/search", params=params)
        assert response.status_code == 422
        assert "nice_class" in response.json()["detail"]
    assert client.get("/goods/search", params={"q": "  ", "nice_class": 25}).status_code == 200


def test_class_listing_without_query_is_sorted_by_name(client):
    body = client.get("/goods/search", params={"nice_class": 25}).json()
    assert body["query"] == ""
    assert body["total"] == 3 and body["offset"] == 0
    assert [m["name"] for m in body["matches"]] == ["신발", "의류", "장갑"]  # 가나다순
    assert all(m["matched_alias"] is None for m in body["matches"])
    assert body["matches"][0]["similarity_codes"] == ["G4503"]
    assert body["source"] == goods.SOURCE
    # 항목이 없는 류는 빈 목록 + total 0
    empty = client.get("/goods/search", params={"nice_class": 44}).json()
    assert empty["matches"] == [] and empty["total"] == 0


def test_offset_pages_listing_and_search(client):
    page = client.get("/goods/search", params={"nice_class": 25, "offset": 1, "limit": 1}).json()
    assert [m["name"] for m in page["matches"]] == ["의류"]
    assert page["total"] == 3 and page["offset"] == 1
    beyond = client.get("/goods/search", params={"nice_class": 25, "offset": 3}).json()
    assert beyond["matches"] == [] and beyond["total"] == 3 and beyond["offset"] == 3
    # 검색에도 같은 offset 이 적용된다(순위 목록의 페이지 넘김)
    first = client.get("/goods/search", params={"q": "화장품", "limit": 2}).json()
    second = client.get("/goods/search", params={"q": "화장품", "limit": 2, "offset": 2}).json()
    assert [m["name"] for m in first["matches"]] == ["화장품", "화장품용 스펀지"]
    assert [m["name"] for m in second["matches"]] == [COSMETICS_35, "기능성 화장품"]
    assert first["total"] == second["total"] == 4 and second["offset"] == 2


def test_search_returns_matching_business_presets(client):
    """검색어가 세트의 업종명·별칭에 부분 일치하면 presets 에 세트(유사군 해석 완료)를 함께 준다."""
    body = client.get("/goods/search", params={"q": "카페"}).json()
    assert [p["id"] for p in body["presets"]] == ["cafe"]
    cafe = body["presets"][0]
    assert cafe["업종명"] == "카페" and cafe["emoji"] == "☕" and cafe["hint"] == "테스트 힌트"
    assert [(g["name"], g["nice_class"], g["similarity_codes"]) for g in cafe["지정상품"]] == [
        ("커피", 30, ["G0502"]),
        ("커피 소매업", 35, ["S2039"]),  # alias 로 적은 명칭도 병합 항목의 유사군으로 해석
    ]
    # 별칭(커피숍)에 부분 일치해도 잡히고, 개별 검색 결과·total·offset 은 그대로다
    body = client.get("/goods/search", params={"q": "커피"}).json()
    assert [p["id"] for p in body["presets"]] == ["cafe"]
    assert body["total"] == 2 and body["offset"] == 0
    assert [m["name"] for m in body["matches"]] == ["커피", COFFEE_35]


def test_search_without_preset_match_has_empty_presets(client):
    assert client.get("/goods/search", params={"q": "장갑"}).json()["presets"] == []
    # 류 목록 보기(검색어 없음)에는 세트를 붙이지 않는다
    assert client.get("/goods/search", params={"nice_class": 25}).json()["presets"] == []
    assert client.get("/goods/search", params={"q": "화장품"}).json()["presets"][0]["id"] == (
        "cosmetics"
    )


def test_invalid_preset_names_are_excluded_with_warning(client):
    """변환표에 없는 명칭은 경고 + 제외, 유효한 지정상품이 없는 세트는 통째로 제외(기동은 정상)."""
    presets = goods.state.presets
    assert presets is not None and len(presets) == 2
    assert presets.get("ghost") is None
    assert any("cafe" in w and "없는상품" in w for w in goods.state.preset_warnings)
    assert any("ghost" in w for w in goods.state.preset_warnings)
    assert client.get("/health").status_code == 200


def test_classes_returns_all_45_with_titles_and_counts(client):
    response = client.get("/goods/classes")
    assert response.status_code == 200
    body = response.json()

    assert [c["nice_class"] for c in body["classes"]] == list(range(1, 46))
    assert body["classes"][2] == {"nice_class": 3, "title": "화장품·세제", "count": 2}
    assert body["classes"][34] == {"nice_class": 35, "title": "광고·사업관리·도소매업", "count": 2}
    assert body["classes"][43]["count"] == 0  # 픽스처에 없는 류는 0
    assert body["total_entries"] == 10
    assert body["source"] == goods.SOURCE


def test_endpoints_are_503_with_reason_when_goods_map_is_missing(client, monkeypatch):
    monkeypatch.setattr(goods.state, "ready", False)
    monkeypatch.setattr(goods.state, "error", "상품↔유사군 변환표 파일이 없습니다(테스트)")

    response = client.get("/goods/search", params={"q": "커피"})
    assert response.status_code == 503
    assert "변환표" in response.json()["detail"]
    assert client.get("/goods/classes").status_code == 503
    assert client.get("/health").status_code == 200  # 다른 엔드포인트는 영향 없음


def test_load_all_without_file_keeps_state_unready_and_does_not_raise(tmp_path):
    """서비스 단위: 파일이 없으면 예외 없이 ready=False + 이유. 끝나면 픽스처로 되돌린다."""
    try:
        state = goods.load_all(str(tmp_path / "missing.json.gz"))
        assert state.ready is False
        assert state.goods_map is None
        assert "변환표" in state.error and "MARKLENS_GOODS_MAP_PATH" in state.error
    finally:
        assert goods.load_all().ready is True  # conftest 의 MARKLENS_GOODS_MAP_PATH 픽스처
