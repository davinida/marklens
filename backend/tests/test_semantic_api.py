"""POST /semantic-search 계약 테스트 — FAKE_ML 픽스처(가짜 임베더), 네트워크·모델 다운로드 불필요.

더미 픽스처 이름(더미상표N)은 관념 게이트를 통과하지 못하므로(더미 3.58·상표 3.92 < 4.0) 정상 경로는
meaningful_db 픽스처로 상표 메타를 실제 단어 이름으로 바꿔 검증한다(엔진 재게시와 같은 경로).
"""

import pytest
from fastapi.testclient import TestClient

from backend.src.core import config, engine, semantic_search
from backend.src.core.ratelimit import limiter


@pytest.fixture(scope="module")
def client():
    from backend.src.main import app

    # with 블록이 lifespan(엔진 로딩 + 발음 캐시 + 관념 캐시 구축)을 실행한다
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """운영 한도(30/min)를 유지하면서 케이스마다 카운터를 초기화한다."""
    limiter.reset()
    yield
    limiter.reset()


def _record(number: str, name: str, key: str) -> dict:
    return {
        "출원번호": number,
        "상표한글명": name,
        "이미지파일": key,
        "출원인": "테스트 출원인",
        "류": [35],
    }


MEANINGFUL_RECORDS = {
    "4020210000001.png": _record("4020210000001", "왕", "4020210000001.png"),
    "4020210000002.png": _record("4020210000002", "사과", "4020210000002.png"),
    "4020210000003.png": _record("4020210000003", "하늘", "4020210000003.png"),
    "4020210000004.png": _record("4020210000004", "현대", "4020210000004.png"),
    "4020210000005.png": _record("4020210000005", "바다", "4020210000005.png"),
    "4020210000006.png": _record("4020210000006", "나무", "4020210000006.png"),
    "4020210000007.png": _record("4020210000007", "스타벅스", "4020210000007.png"),  # 조어 → 제외
    "4020210000008.png": _record("4020210000008", "®", "4020210000008.png"),  # 기호만 → 제외
    "4020210000009.png": _record("4020210000009", "", "4020210000009.png"),  # 빈 이름 → 제외
}


@pytest.fixture
def meaningful_db(monkeypatch):
    """상표 메타를 실제 단어 6건 + 관념 없는 3건으로 바꾸고 재게시 토큰을 올린다.

    다음 요청이 토큰 불일치를 보고 캐시를 다시 만든다(엔진 재게시와 같은 경로).
    """
    monkeypatch.setattr(engine.state, "storage_mode", "file")
    monkeypatch.setattr(engine.state, "trademark_lookup", MEANINGFUL_RECORDS)
    monkeypatch.setattr(engine.state, "load_token", "semantic-test")
    yield
    # monkeypatch 가 원래 픽스처를 되돌리면 다음 요청이 토큰 불일치로 다시 구축한다.


def test_cache_is_built_at_startup(client):
    assert semantic_search.state.enabled is True
    assert semantic_search.state.ready is True
    assert semantic_search.state.model == "fake"  # MARKLENS_FAKE_ML 가짜 임베더
    assert semantic_search.state.load_token == engine.state.load_token
    # 더미 픽스처 9건은 모두 관념 게이트를 통과하지 못한다(조어 취급) → 비교 대상 0건
    assert semantic_search.state.entries == []
    assert semantic_search.state.excluded_no_meaning == 9


def test_openapi_exposes_post_body(client):
    operations = client.app.openapi()["paths"]["/semantic-search"]
    assert "requestBody" in operations["post"]
    assert "get" not in operations


def test_exact_name_ranks_first_with_contract_fields(client, meaningful_db):
    response = client.post("/semantic-search", json={"name": "왕"})
    assert response.status_code == 200
    body = response.json()

    assert body["axis"] == "X3"
    assert body["note"] == "관념(의미) 유사도만 반영한 참고 정보"
    assert body["model"] == "fake"
    assert body["query"] == {"name": "왕", "has_meaning": True, "text": "왕"}
    assert body["searched_count"] == 6
    assert body["excluded_no_meaning"] == 3
    assert body["params"] == {"top_k": 5, "min_score": 0.55}
    assert body["threshold"] == 0.55
    assert set(body["dataset_info"]) >= {"총_상표수", "출원일자_범위", "데이터_기준", "생성일자"}

    matches = body["matches"]
    assert 1 <= len(matches) <= 5
    assert [m["rank"] for m in matches] == list(range(1, len(matches) + 1))
    scores = [m["score"] for m in matches]
    assert scores == sorted(scores, reverse=True)
    assert all(s >= body["threshold"] for s in scores)
    top = matches[0]
    assert top["상표한글명"] == "왕"
    assert top["score"] == 1.0  # 정규화 텍스트가 같으면 1.0
    assert top["출원번호"] == "4020210000001"
    assert top["이미지URL"] == "/images/4020210000001.png"
    assert top["출원인"] == "테스트 출원인"
    assert top["류"] == [35]


def test_top_k_bounds_cap_at_five(client, meaningful_db, monkeypatch):
    def post(top_k: int):
        return client.post("/semantic-search", json={"name": "왕", "top_k": top_k})

    assert post(0).status_code == 422
    assert post(6).status_code == 422  # 상한 5
    monkeypatch.setattr(config, "X3_MIN_SCORE", 0.0)
    assert len(post(2).json()["matches"]) == 2
    body = post(5).json()
    assert len(body["matches"]) == 5  # 관념 있는 레코드 6건 중 상위 5건
    assert body["params"]["top_k"] == 5
    assert body["searched_count"] == 6


def test_min_score_filter_drops_unrelated_names(client, meaningful_db, monkeypatch):
    strict = client.post("/semantic-search", json={"name": "사과"}).json()
    assert strict["query"]["has_meaning"] is True
    # 가짜 임베더(문자 3-gram 해시)는 다른 이름과 공유 n-gram 이 없어 사과 자신만 하한 0.55 이상
    assert [m["상표한글명"] for m in strict["matches"]] == ["사과"]

    monkeypatch.setattr(config, "X3_MIN_SCORE", 0.0)
    everything = client.post("/semantic-search", json={"name": "사과", "top_k": 5}).json()
    assert everything["params"]["min_score"] == 0.0
    assert everything["threshold"] == 0.0
    assert len(everything["matches"]) == 5


@pytest.mark.parametrize("name", ["스타벅스", "엘쏘", "®™©", "1234"])
def test_query_without_meaning_returns_empty_matches_and_note(client, meaningful_db, name):
    response = client.post("/semantic-search", json={"name": name})
    assert response.status_code == 200
    body = response.json()
    assert body["query"]["has_meaning"] is False
    assert body["query"]["text"] == ""
    assert body["matches"] == []
    assert body["note"] == "관념 없음(조어)"
    assert body["searched_count"] == 6


@pytest.mark.parametrize("name", ["", "   ", "\t\n", "가" * 101])
def test_invalid_name_is_422(client, name):
    assert client.post("/semantic-search", json={"name": name}).status_code == 422


def test_disabled_flag_gives_503_with_reason(client, monkeypatch):
    monkeypatch.setattr(semantic_search.state, "enabled", False)
    monkeypatch.setattr(semantic_search.state, "error", semantic_search.DISABLED_REASON)

    response = client.post("/semantic-search", json={"name": "왕"})
    assert response.status_code == 503
    assert "MARKLENS_X3_ENABLED" in response.json()["detail"]
    assert client.get("/health").status_code == 200  # 다른 엔드포인트는 영향 없음
    assert client.post("/phonetic-search", json={"name": "왕"}).status_code == 200


def test_load_all_skips_model_when_disabled(client, monkeypatch):
    """서비스 단위: X3_ENABLED=0 이면 예외 없이 enabled=False + 이유. 끝나면 다시 적재한다."""
    monkeypatch.setattr(config, "X3_ENABLED", False)
    try:
        state = semantic_search.load_all()
        assert state.enabled is False
        assert state.ready is False
        assert state.entries == [] and state.matrix is None
        assert "MARKLENS_X3_ENABLED" in state.error
        with pytest.raises(RuntimeError):
            semantic_search.search("왕", top_k=5, min_score=0.5)
    finally:
        monkeypatch.setattr(config, "X3_ENABLED", True)
        assert semantic_search.load_all().enabled is True


def test_service_scores_match_the_axis_function(meaningful_db):
    """서비스 단위: 행렬 점수 = X3 semantic_similarity, 관념 없는 레코드 제외, 내림차순, 하한."""
    from src.axes.x3_semantic import semantic_similarity

    result = semantic_search.search("왕", top_k=5, min_score=0.0)  # 토큰 불일치 → 재구축

    assert semantic_search.state.load_token == "semantic-test"
    assert result.has_meaning is True
    assert result.query_text == "왕"
    assert result.searched_count == 6
    assert result.excluded_no_meaning == 3
    assert result.matches[0].entry.name == "왕" and result.matches[0].score == 1.0
    scores = [m.score for m in result.matches]
    assert scores == sorted(scores, reverse=True)
    for match in result.matches:
        expected = semantic_similarity("왕", match.entry.name)
        assert match.score == pytest.approx(expected, abs=1e-6)
    assert result.elapsed_ms >= 0.0

    with pytest.raises(ValueError):
        semantic_search.search("   ", top_k=5, min_score=0.5)


def test_cache_rebuilds_after_engine_state_is_restored(client):
    """앞 테스트의 monkeypatch 가 풀리면 다음 요청에서 원래 픽스처로 다시 구축된다."""
    body = client.post("/semantic-search", json={"name": "왕"}).json()
    assert body["searched_count"] == 0
    assert body["matches"] == []
    assert semantic_search.state.load_token == engine.state.load_token
