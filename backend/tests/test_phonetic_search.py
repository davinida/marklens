"""POST /phonetic-search 계약 테스트 — FAKE_ML 픽스처(더미 9건), 네트워크·KIPRIS 키 불필요."""

import pytest
from fastapi.testclient import TestClient

from backend.src.core import config, engine, phonetic_search
from backend.src.core.ratelimit import limiter


@pytest.fixture(scope="module")
def client():
    from backend.src.main import app

    # with 블록이 lifespan(엔진 로딩 + 발음 캐시 구축)을 실행한다
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """운영 한도(30/min)를 유지하면서 케이스마다 카운터를 초기화한다."""
    limiter.reset()
    yield
    limiter.reset()


def test_cache_is_built_at_startup(client):
    assert phonetic_search.state.ready is True
    # 더미 픽스처: 상표 메타 9건(더미상표1~9), 마지막 인덱스 1건은 메타 없음 → 캐시 대상 아님
    assert len(phonetic_search.state.entries) == 9
    assert phonetic_search.state.excluded_no_pronunciation == 0
    assert phonetic_search.state.load_token == engine.state.load_token


def test_openapi_exposes_post_body(client):
    operations = client.app.openapi()["paths"]["/phonetic-search"]
    assert "requestBody" in operations["post"]
    assert "get" not in operations


def test_exact_name_ranks_first_with_contract_fields(client):
    response = client.post("/phonetic-search", json={"name": "더미상표1"})
    assert response.status_code == 200
    body = response.json()

    assert body["axis"] == "X1"
    assert body["note"]
    assert body["query"] == {
        "name": "더미상표1",
        "has_pronunciation": True,
        "candidates": body["query"]["candidates"],
    }
    assert body["query"]["candidates"]
    assert body["searched_count"] == 9
    assert body["excluded_no_pronunciation"] == 0
    assert body["params"] == {"top_k": 5, "min_similarity": 0.5}
    assert set(body["dataset_info"]) >= {"총_상표수", "출원일자_범위", "데이터_기준", "생성일자"}

    matches = body["matches"]
    assert 1 <= len(matches) <= 5
    assert [m["rank"] for m in matches] == list(range(1, len(matches) + 1))
    similarities = [m["similarity"] for m in matches]
    assert similarities == sorted(similarities, reverse=True)
    assert all(s >= body["params"]["min_similarity"] for s in similarities)
    top = matches[0]
    assert top["상표한글명"] == "더미상표1"
    assert top["similarity"] == 1.0
    assert top["출원번호"] == "4020210000001"
    assert top["이미지URL"] == "/images/4020210000001.png"
    assert top["출원인"] == "테스트 출원인"
    assert top["류"] == [35]


def test_top_k_bounds(client):
    def post(top_k: int):
        return client.post("/phonetic-search", json={"name": "더미상표1", "top_k": top_k})

    assert len(post(2).json()["matches"]) == 2
    assert post(0).status_code == 422
    assert post(21).status_code == 422
    body = client.post("/phonetic-search", json={"name": "더미상표1", "top_k": 20}).json()
    assert len(body["matches"]) == 9  # 더미 9건 전부 하한 이상(공통 토큰 '더미상표')
    assert body["params"]["top_k"] == 20


def test_min_similarity_filter_drops_unrelated_names(client, monkeypatch):
    unrelated = client.post("/phonetic-search", json={"name": "스타벅스"}).json()
    assert unrelated["query"]["has_pronunciation"] is True
    assert unrelated["matches"] == []  # 더미상표N 과의 유사도는 하한 0.5 미만

    monkeypatch.setattr(config, "PHONETIC_MIN_SIMILARITY", 0.0)
    everything = client.post("/phonetic-search", json={"name": "스타벅스", "top_k": 20}).json()
    assert everything["params"]["min_similarity"] == 0.0
    assert len(everything["matches"]) == 9


@pytest.mark.parametrize("name", ["", "   ", "\t\n", "가" * 101])
def test_invalid_name_is_422(client, name):
    assert client.post("/phonetic-search", json={"name": name}).status_code == 422


def test_query_without_pronunciation_returns_empty_matches(client):
    response = client.post("/phonetic-search", json={"name": "®™©"})
    assert response.status_code == 200
    body = response.json()
    assert body["query"]["has_pronunciation"] is False
    assert body["query"]["candidates"] == []
    assert body["matches"] == []
    assert body["searched_count"] == 9


def test_works_without_kipris_key_or_network(client, monkeypatch):
    monkeypatch.delenv("KIPRIS_ACCESS_KEY", raising=False)
    response = client.post("/phonetic-search", json={"name": "더미상표2", "top_k": 20})
    assert response.status_code == 200
    # 더미 9건은 공통 토큰 '더미상표' 때문에 전부 1.0 동점 → 출원번호 순. 대상은 포함돼야 한다.
    exact = [m for m in response.json()["matches"] if m["상표한글명"] == "더미상표2"]
    assert exact and exact[0]["similarity"] == 1.0


def test_records_without_pronunciation_are_excluded_and_ranked(client, monkeypatch):
    """서비스 단위: 호칭 없는 레코드 제외, 내림차순, 하한 필터. 엔진 재게시 시 자동 재구축."""
    def record(number: str, name: str, key: str) -> dict:
        return {"출원번호": number, "상표한글명": name, "이미지파일": key, "류": [43]}

    records = {
        "a.png": record("4020210000001", "스타벅스", "a.png"),
        "b.png": record("4020210000002", "스타박스", "b.png"),
        "c.png": record("4020210000003", "커피빈", "c.png"),
        "d.png": record("4020210000004", "®", "d.png"),  # 기호만 → 호칭 없음
        "e.png": record("4020210000005", "", "e.png"),  # 빈 이름 → 호칭 없음
    }
    monkeypatch.setattr(engine.state, "storage_mode", "file")
    monkeypatch.setattr(engine.state, "trademark_lookup", records)
    monkeypatch.setattr(engine.state, "load_token", "test-republish")

    result = phonetic_search.search("스타벅스", top_k=5, min_similarity=0.5)  # 토큰 불일치 → 재구축

    assert phonetic_search.state.load_token == "test-republish"
    assert result.searched_count == 3
    assert result.excluded_no_pronunciation == 2
    assert [(m.rank, m.entry.name) for m in result.matches] == [(1, "스타벅스"), (2, "스타박스")]
    assert result.matches[0].similarity == 1.0
    assert 0.5 <= result.matches[1].similarity < 1.0
    assert result.elapsed_ms >= 0.0

    with pytest.raises(ValueError):
        phonetic_search.search("   ", top_k=5, min_similarity=0.5)


def test_cache_rebuilds_after_engine_state_is_restored(client):
    """앞 테스트의 monkeypatch 가 풀리면 다음 요청에서 원래 픽스처로 다시 구축된다."""
    body = client.post("/phonetic-search", json={"name": "더미상표3"}).json()
    assert body["searched_count"] == 9
    assert phonetic_search.state.load_token == engine.state.load_token
