"""
API 계약 회귀 테스트 — 2026-07-07 더미 데이터 검증 매트릭스의 pytest 판.

전제: ml/data 에 더미(또는 실제) 인덱스·메타·이미지가 빌드되어 있어야 한다.
없으면 전체 skip. CLIP 로딩 때문에 첫 기동에 수십 초 + 메모리 ~2GB 를 쓴다.

저장소 모드: 현재 환경(config.STORAGE_MODE)을 그대로 따른다.
    file 모드 검증:  $env:DATABASE_URL=""  후 pytest
    db 모드 검증:    .env 의 DATABASE_URL 사용 (migrate 선행)
"""

import io
import json

import pytest
from PIL import Image, ImageDraw

from backend.src.core import config, paths

pytestmark = pytest.mark.skipif(
    not paths.INDEX_PATH.exists() or not paths.INDEX_META_PATH.exists(),
    reason="ml/data 인덱스가 없음 — 더미 데이터 빌드 후 실행 (가이드 부록 B)",
)


# ---------------------------------------------------------------
# 페이로드 (전부 메모리에서 생성 — 외부 파일 의존 없음)
# ---------------------------------------------------------------

def png_bytes(size=(256, 256), draw_fn=None) -> bytes:
    img = Image.new("RGB", size, "white")
    if draw_fn:
        draw_fn(ImageDraw.Draw(img))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def dup_query() -> bytes:
    """더미 1번(빨간 원)과 동일한 이미지 — rank1 완전 일치 검증용."""
    return png_bytes(draw_fn=lambda d: d.ellipse([48, 48, 208, 208], fill=(220, 30, 30)))


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from backend.src.main import app

    # with 블록이 lifespan(startup: CLIP+인덱스 로딩)을 실행한다
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function", autouse=True)
def reset_rate_limiter():
    """Keep the production rate limit while isolating each contract test."""
    from backend.src.core.ratelimit import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(scope="session")
def identity_query(fake_ml_mode) -> bytes:
    """'완전 동일 이미지가 rank1, 유사도 ≈ 1.0'을 두 모드 모두에서 보장하는 쿼리 바이트.

    가짜 모드: 더미 1번(빨간 원)과 픽셀 단위로 동일한 dup_query().
    실모드: 더미 이미지는 실인덱스에 없으므로 대신 실인덱스 0번 레코드의
    실제 이미지 파일을 그대로 읽어 자기 자신과 비교 → 완전 일치가 보장된다.
    """
    if fake_ml_mode:
        return dup_query()
    meta = json.loads(paths.INDEX_META_PATH.read_text(encoding="utf-8"))
    first_image = paths.IMAGES_DIR / meta["image_paths"][0]
    return first_image.read_bytes()


def post_search_v2(client, content: bytes, mime="image/png", query=""):
    """이미지만 질의하는 통합 검색 v2 — multipart 필드명은 계약 v2 상 "image"."""
    return client.post(
        f"/search/v2{query}", files={"image": ("q.png", content, mime)}
    )


# ---------------------------------------------------------------
# /health
# ---------------------------------------------------------------

def test_health_contract(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["engine_ready"] is True
    assert body["index_size"] > 0
    assert body["trademark_count"] > 0
    assert body["storage_mode"] == config.STORAGE_MODE


# ---------------------------------------------------------------
# POST /search/v2 — 이미지만 질의의 정상 경로
# (2026-11-21 v1 POST /search 를 없애며 v1 계약 테스트의 같은 항목을 옮김. 형식·크기·치수·
#  top_k 오류 계약은 test_search_v2_api.py 의 검증 테스트가 맡는다.)
# ---------------------------------------------------------------

VISUAL_STATUSES = ("STRONG_MATCH", "POSSIBLE_MATCH", "WEAK_MATCH", "NO_CLOSE_MATCH")


def test_search_v2_image_happy_path(client, identity_query, fake_ml_mode):
    from backend.src.schemas.search_v2 import SearchV2Response

    r = post_search_v2(client, identity_query, query="?top_k=5")
    assert r.status_code == 200, r.text
    body = r.json()
    # 응답 계약 — dataset_info 4필드·등급·후보 메타 형식까지
    SearchV2Response.model_validate(body)

    # 랭킹: 완전 동일 이미지가 1위, 이미지 유사도 ≈ 1.0
    top = body["candidates"][0]
    assert top["axes"]["x2_img"] >= 0.98
    assert top["image_url"].startswith(f"{config.IMAGES_URL_PREFIX}/")
    # 메타 결합 (file/db 모드 공통 계약)
    assert isinstance(top["nice_classes"], list)
    if fake_ml_mode:
        assert top["id"] == "4020210000001"
        assert top["image_url"] == f"{config.IMAGES_URL_PREFIX}/4020210000001.png"
        assert top["applicant"] == "테스트 출원인"

    assert body["overall"]["visual_status"] in VISUAL_STATUSES
    assert body["research_beta"] is True
    assert body["legal_conclusion"] is False
    for key in ("총_상표수", "출원일자_범위", "데이터_기준", "생성일자"):
        assert key in body["dataset_info"]
    assert body["top_k_requested"] == 5
    assert body["top_k_returned"] == len(body["candidates"]) == 5


def test_search_v2_assessment_is_independent_from_display_top_k(client):
    one = post_search_v2(client, dup_query(), query="?top_k=1")
    five = post_search_v2(client, dup_query(), query="?top_k=5")
    assert one.status_code == five.status_code == 200
    one_body = one.json()
    five_body = five.json()
    # 시각 4상태·전체 등급은 후보 풀 전체로 정한다 — 표시 개수와 무관
    assert one_body["overall"] == five_body["overall"]
    assert one_body["candidates"][0] == five_body["candidates"][0]
    assert one_body["top_k_returned"] == 1
    assert five_body["top_k_returned"] == 5


def test_search_v2_top_k_beyond_pool_returns_available(client, fake_ml_mode):
    r = post_search_v2(client, dup_query(), query="?top_k=20")
    assert r.status_code == 200
    body = r.json()
    assert body["top_k_returned"] == len(body["candidates"]) <= 20
    if fake_ml_mode:
        assert body["top_k_returned"] == 9  # 색인 10건 중 메타가 있는 9건


def test_search_v2_skips_index_entries_without_metadata(client, fake_ml_mode):
    if not fake_ml_mode:
        pytest.skip("더미 픽스처 전용 — 실데이터는 메타 완전")
    # 더미 데이터는 10번 상표를 메타에서 고의 누락. v1 은 trademark: null 로 냈고, v2 는 메타가 없는
    # 색인 항목을 후보에서 뺀다 — 응답은 깨지지 않는다.
    r = post_search_v2(client, dup_query(), query="?top_k=20")
    assert r.status_code == 200
    ids = [candidate["id"] for candidate in r.json()["candidates"]]
    assert "4020210000010" not in ids
    assert len(ids) == 9


# ---------------------------------------------------------------
# /images 정적 서빙
# ---------------------------------------------------------------

def test_images_static_serving(client):
    r = post_search_v2(client, dup_query())
    assert r.status_code == 200
    img = client.get(r.json()["candidates"][0]["image_url"])
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"


def test_images_nested_index_key_serving(client, fake_ml_mode):
    if not fake_ml_mode:
        pytest.skip("중첩 키 계약 테스트는 임시 fake image root에서만 실행")

    from backend.src.core import engine

    image_key = "nested/contract.png"
    image_path = paths.IMAGES_DIR / image_key
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(png_bytes(size=(64, 64)))
    engine.state.image_path_set.add(image_key)
    try:
        response = client.get("/images/nested/contract.png")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
    finally:
        engine.state.image_path_set.discard(image_key)
        image_path.unlink(missing_ok=True)
        image_path.parent.rmdir()


def test_images_missing_404(client):
    assert client.get("/images/nope.png").status_code == 404


# ---------------------------------------------------------------
# /name-check (백엔드-7) — 키 미설정 환경 계약
# ---------------------------------------------------------------

def test_name_check_without_key_503(client):
    if config.STORAGE_MODE and __import__("os").getenv("KIPRIS_ACCESS_KEY"):
        pytest.skip("KIPRIS 키가 설정된 환경 — 실호출 방지를 위해 skip")
    r = client.post("/name-check", json={"name": "삼성전자"})
    assert r.status_code == 503
    assert "KIPRIS" in r.json()["detail"]
