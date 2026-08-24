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


def gif_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "blue").save(buf, "GIF")
    return buf.getvalue()


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


def post_search(client, content: bytes, mime="image/png", query=""):
    return client.post(
        f"/search{query}", files={"file": ("q.png", content, mime)}
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
# POST /search — 정상 경로
# ---------------------------------------------------------------

def test_search_happy_path(client, identity_query):
    r = post_search(client, identity_query, query="?top_k=5")
    assert r.status_code == 200
    body = r.json()

    # 랭킹: 완전 동일 이미지가 rank1, 유사도 ≈ 1.0
    top = body["matches"][0]
    assert top["rank"] == 1
    assert top["similarity"] >= 0.98
    assert top["이미지URL"] == f"/images/{top['이미지파일']}"
    # 메타 결합 (file/db 모드 공통 계약)
    assert top["trademark"] is not None
    assert top["trademark"]["출원번호"]
    assert isinstance(top["trademark"]["류"], list)

    # 등급 블록
    grade = body["grade"]
    for key in (
        "status_code", "status_name", "uncertain", "uncertainty_reasons",
        "scored_candidate_count", "threshold_version", "grade_code", "grade_name",
        "message", "top1_similarity", "separability_a", "separability_b", "warnings",
    ):
        assert key in grade
    assert grade["status_code"] in (
        "STRONG_MATCH", "POSSIBLE_MATCH", "WEAK_MATCH", "NO_CLOSE_MATCH"
    )
    assert grade["grade_code"] in ("CAUTION", "REVIEW", "LOW")
    assert grade["calibrated"] is False
    assert grade["legal_conclusion"] is False
    assert body["research_beta"] is True

    # 데이터셋 안내 4필드
    for key in ("총_상표수", "출원일자_범위", "데이터_기준", "생성일자"):
        assert key in body["dataset_info"]

    assert body["top_k_requested"] == 5
    assert body["top_k_returned"] == 5


def test_search_default_top_k(client):
    r = post_search(client, dup_query())
    assert r.status_code == 200
    assert r.json()["top_k_requested"] == config.DEFAULT_TOP_K


def test_search_assessment_is_independent_from_display_top_k(client):
    one = post_search(client, dup_query(), query="?top_k=1")
    five = post_search(client, dup_query(), query="?top_k=5")
    assert one.status_code == five.status_code == 200
    one_body = one.json()
    five_body = five.json()
    assert one_body["grade"] == five_body["grade"]
    assert one_body["scoring_k"] == five_body["scoring_k"]
    assert one_body["scoring_k"] == min(
        config.SCORING_TOP_K, one_body["index_size"]
    )
    assert one_body["top_k_returned"] == 1
    assert five_body["top_k_returned"] == 5


def test_search_top_k_clamped_to_index_size(client):
    r = post_search(client, dup_query(), query="?top_k=20")
    assert r.status_code == 200
    body = r.json()
    assert body["top_k_returned"] == min(20, body["index_size"])


def test_search_missing_metadata_yields_null_trademark(client, fake_ml_mode):
    if not fake_ml_mode:
        pytest.skip("더미 픽스처 전용 — 실데이터는 메타 완전")
    # 더미 데이터는 10번 상표를 메타에서 고의 누락 → trademark: null 경로 검증
    r = post_search(client, dup_query(), query="?top_k=20")
    nulls = [m for m in r.json()["matches"] if m["trademark"] is None]
    assert len(nulls) >= 1


# ---------------------------------------------------------------
# POST /search — 오류 계약
# ---------------------------------------------------------------

@pytest.mark.parametrize("bad_top_k", [0, 21])
def test_search_top_k_out_of_range_422(client, bad_top_k):
    r = post_search(client, dup_query(), query=f"?top_k={bad_top_k}")
    assert r.status_code == 422


def test_search_wrong_content_type_415(client):
    r = post_search(client, dup_query(), mime="text/plain")
    assert r.status_code == 415


def test_search_empty_file_400(client):
    r = post_search(client, b"")
    assert r.status_code == 400


def test_search_oversize_413(client):
    r = post_search(client, b"\x00" * (11 * 1024 * 1024))
    assert r.status_code == 413


def test_search_undecodable_415(client):
    r = post_search(client, b"\x00" * 4096)
    assert r.status_code == 415


def test_search_disallowed_format_gif_415(client):
    # 실제 GIF 를 image/png 으로 위장 → PIL 포맷 검증(디코드 후)에서 걸러야 함
    r = post_search(client, gif_bytes())
    assert r.status_code == 415


def test_search_too_small_400(client):
    r = post_search(client, png_bytes(size=(16, 16)))
    assert r.status_code == 400


def test_search_oversized_dimensions_rejected_before_decode(client):
    r = post_search(client, png_bytes(size=(config.MAX_IMAGE_DIM + 1, 32)))
    assert r.status_code == 400
    assert "치수 상한" in r.json()["detail"]


# ---------------------------------------------------------------
# /images 정적 서빙
# ---------------------------------------------------------------

def test_images_static_serving(client):
    r = post_search(client, dup_query())
    assert r.status_code == 200
    filename = r.json()["matches"][0]["이미지파일"]
    img = client.get(f"/images/{filename}")
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
    r = client.get("/name-check", params={"name": "삼성전자"})
    assert r.status_code == 503
    assert "KIPRIS" in r.json()["detail"]
