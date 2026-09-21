"""GET /goods/search · /goods/classes 계약 테스트 — FAKE_ML 픽스처(변환표 10건, 제35류 병합 2건).

conftest 가 가짜 ML 환경에 goods_map.json(10건) 을 만들고 MARKLENS_GOODS_MAP_PATH 로 가리킨다.
KIPRIS 키·네트워크·실제 변환표 불필요.
"""

import pytest
from fastapi.testclient import TestClient

from backend.src.core import goods
from backend.src.core.ratelimit import limiter

COSMETICS_35 = "화장품 판매업(도소매·중개·대행)"


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
    assert body["source"] == goods.SOURCE == "고시상품명칭 13판(2026)"
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
    assert body == {"query": "없는상품", "matches": [], "total": 0, "source": goods.SOURCE}


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
    ],
)
def test_invalid_params_are_422(client, params):
    assert client.get("/goods/search", params=params).status_code == 422


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
