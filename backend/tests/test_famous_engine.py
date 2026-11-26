"""유명 상표 확인의 엔진 연결(v1.4.7 — 통합 모델 설계 §7-14-13, 계약 v2 §2-6) — FAKE_ML 픽스처.

기동(등록부·확정 파일의 해시 대조, 못 읽으면 검색 준비 안 됨), 질의마다의 확인(이름·이미지 속 글자,
가짜 ML 에서는 로고 일치 없음), 전체 등급의 바닥, 응답의 선택 필드, v1.4.6 JSON 으로는 예전과 같은
응답, 확인에서 예외가 나도 검색은 그대로 나가는지를 본다. 판정 자체는 ml/tests 가 본다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.src.api import health
from backend.src.core import engine
from backend.src.core import multi_search as ms
from backend.src.main import app
from backend.src.schemas.search_v2 import SearchV2Response

# ml/src 의 모듈은 엔진이 경로를 넣은 뒤에 들어온다 — 엔진이 쓰는 것과 같은 객체를 쓴다
fr = ms.fr  # src.famous_runtime
fc = fr.fc  # src.famous_check(확정된 판정 모듈)
rm = ms.rm  # src.model.risk_model

NAME = "더미상표1"  # 픽스처 1번 상표명(등록부의 어느 브랜드와도 닮지 않았다)
FIRST = "4020210000001"  # 픽스처 1번 상표의 출원번호


@pytest.fixture(scope="module")
def client(fake_ml_mode):
    if not fake_ml_mode:
        pytest.skip("FAKE_ML 픽스처(더미 9건) 전용 테스트")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def v146():
    return json.loads(rm.V146_MODEL_PATH.read_text(encoding="utf-8"))


def _image():
    return Image.new("RGB", (64, 64), (200, 40, 40))


def _without_famous(data: dict) -> dict:
    """새 선택 필드와 모델 버전·걸린 시간을 뺀 응답."""
    data = json.loads(json.dumps(data))
    data.pop("famous", None)
    data["overall"].pop("famous_floor", None)
    for candidate in data["candidates"]:
        candidate.pop("famous_brand", None)
    data["meta"].pop("model_version")
    data["meta"].pop("elapsed_ms")
    return data


# ---- 기동 --------------------------------------------------------------------------------------

def test_startup_loads_the_confirmed_rule(client):
    assert ms.state.model["version"] == rm.MODEL_VERSION and rm.famous_check_enabled(ms.state.model)
    runtime = ms.state.famous
    assert runtime is not None and ms.unavailable_reason() is None
    assert runtime.confirmed_sha256 == ms.state.model["famous_check"]["confirmed_sha256"]
    assert runtime.brand_count == len(fc.load_registry().brands)
    assert runtime.thresholds.weak_mode == "W2"
    # 가짜 ML 에서는 로고 경로를 쓰지 않는다(가짜 임베딩은 유사도가 고정이라 모든 로고와 맞는다)
    assert runtime.logos is None
    assert client.get("/health").json()["search_ready"] is True


@pytest.mark.parametrize("variable", [fr.ENV_REGISTRY, fr.ENV_CONFIRMED, fr.ENV_LOGO_KINDS])
def test_missing_files_make_search_unavailable(client, monkeypatch, tmp_path, caplog, variable):
    """등록부·확정 파일(·대표 로고 구분)이 없으면 모델 파일 문제와 같게 — 검색 준비 안 됨,
    /health 503 과 이유 코드, 응답에 내부 경로 없음. 이름 확인 같은 다른 기능과 기동은 그대로."""
    missing = tmp_path / "없는_파일.json"
    monkeypatch.setenv(variable, str(missing))
    try:
        with caplog.at_level(logging.ERROR):
            ms.load_all()
        assert ms.state.famous is None and ms.state.model is not None
        assert ms.unavailable_reason() == "FAMOUS_CHECK_UNAVAILABLE"
        assert "유명 상표 확인 자료 적재 실패" in caplog.text
        with pytest.raises(ms.ModelNotReadyError):
            engine.multi_search(name=NAME)
        response = client.get("/health")
        body = response.json()
        assert response.status_code == 503 and body["reason"] == "FAMOUS_CHECK_UNAVAILABLE"
        assert body["status"] == "error" and body["search_ready"] is False
        assert str(tmp_path) not in response.text and "없는_파일" not in response.text
        searched = client.post("/search/v2", files={"name": (None, NAME)})
        assert searched.status_code == 503
        assert str(tmp_path) not in searched.text and "없는_파일" not in searched.text
    finally:
        monkeypatch.delenv(variable)
        ms.load_all()
    assert ms.unavailable_reason() is None and ms.state.famous is not None


def test_changed_registry_is_refused(client, monkeypatch, tmp_path):
    """등록부가 확정 파일에 적힌 해시와 다르면(한 글자라도) 쓰지 않는다."""
    changed = tmp_path / "famous_registry.json"
    text = fc.DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8")
    changed.write_text(text.replace("스타벅스", "스타벅수", 1), encoding="utf-8")
    monkeypatch.setenv(fr.ENV_REGISTRY, str(changed))
    try:
        ms.load_all()
        assert ms.unavailable_reason() == "FAMOUS_CHECK_UNAVAILABLE"
    finally:
        monkeypatch.delenv(fr.ENV_REGISTRY)
        ms.load_all()
    assert ms.unavailable_reason() is None


def test_health_reason_for_famous_check(monkeypatch):
    test_app = FastAPI()
    test_app.include_router(health.router)
    monkeypatch.setattr(health.engine, "state", SimpleNamespace(
        ready=True, index=SimpleNamespace(ntotal=10), trademark_count=10, storage_mode="file",
        artifact_generation_id="x"))
    enabled = {"famous_check": {"enabled": True}}
    monkeypatch.setattr(ms, "state", SimpleNamespace(
        model=enabled, distinct=object(), records=[object()], ready=True, famous=None,
        error="유명 상표 확인: FamousUnavailable"))
    response = TestClient(test_app).get("/health")
    assert response.status_code == 503
    assert response.json()["reason"] == "FAMOUS_CHECK_UNAVAILABLE"
    assert "FamousUnavailable" not in response.text


# ---- 질의 --------------------------------------------------------------------------------------

def test_famous_name_raises_only_the_overall_grade(client, monkeypatch, v146):
    """유명 상표 이름 — 전체 등급만 바닥으로 오르고(후보 목록·위험도·정렬은 그대로) 까닭이 남는다.
    같은 질의를 v1.4.6 JSON 으로 돌리면 새 필드가 없고 나머지는 같다."""
    data = engine.multi_search(name="스타벅스", top_k=5).to_dict()
    SearchV2Response.model_validate(data)
    famous = data["famous"]
    assert famous["status"] == "checked" and famous["brand_count"] == ms.state.famous.brand_count
    assert len(famous["matches"]) == 1
    match = famous["matches"][0]
    assert match == {
        "brand": "스타벅스", "level": "강함", "basis": "이름", "notation": "스타벅스",
        "matched_text": "스타벅스", "protection": "업종 불문", "goods_overlap": None,
        "floor": "위험", "logos": [],  # 픽스처 DB 에는 그 브랜드의 표장이 없다
    }
    assert data["overall"]["grade"] == "위험" and data["overall"]["famous_floor"] is True
    assert list(data)[:5] == ["api_version", "research_beta", "legal_conclusion", "overall",
                              "famous"]

    monkeypatch.setattr(ms.state, "model", v146)
    old = engine.multi_search(name="스타벅스", top_k=5).to_dict()
    assert "famous" not in old and "famous_floor" not in old["overall"]
    assert all("famous_brand" not in candidate for candidate in old["candidates"])
    assert old["meta"]["model_version"] == "risk_model_v1.4.6"
    assert old["overall"]["grade"] != "위험"  # 픽스처의 후보로는 위험이 아니다 — 바닥이 올린 것
    assert old["candidates"] == data["candidates"]
    assert old["overall"]["prob"] == data["overall"]["prob"]
    expected = _without_famous(data)
    expected["overall"]["grade"] = old["overall"]["grade"]
    assert _without_famous(old) == expected


def test_no_match_leaves_the_response_as_before(client, monkeypatch, v146):
    """일치가 없는 질의 — 전체 등급도 같고, 새 필드만 더해진다(확인함·일치 없음)."""
    for inputs in ({"name": NAME}, {"name": f"{NAME} 커피", "goods_codes": ["S0101"]},
                   {"image": _image()}, {"goods_codes": ["S0101"]}):
        data = engine.multi_search(top_k=5, **inputs).to_dict()
        assert data["famous"] == {"status": "checked", "matches": [],
                                  "brand_count": ms.state.famous.brand_count}
        assert data["overall"]["famous_floor"] is False
        with monkeypatch.context() as patch:
            patch.setattr(ms.state, "model", v146)
            old = engine.multi_search(top_k=5, **inputs).to_dict()
        assert "famous" not in old
        assert _without_famous(old) == _without_famous(data)


def test_weak_and_descriptive_matches(client):
    weak = engine.multi_search(name="스타벅수", top_k=3).to_dict()
    match = weak["famous"]["matches"][0]
    assert (match["brand"], match["level"], match["basis"], match["matched_text"],
            match["floor"]) == ("스타벅스", "약함", "이름", "스타벅수", "검토 권장")
    assert weak["overall"]["grade"] in ("검토 권장", "위험")
    # 설명적 사용 — 바닥이 없으니 전체 등급은 그대로
    notice = engine.multi_search(name="텍사스 BBQ", goods_codes=["S0101"], top_k=3)
    match = notice.to_dict()["famous"]["matches"][0]
    assert (match["brand"], match["level"], match["floor"]) == ("BBQ", "설명적 사용", None)
    assert notice.to_dict()["overall"]["famous_floor"] is False
    assert notice.famous_outcome.floor is None and notice.famous_ms >= 0.0


def test_floor_never_lowers_the_overall_grade(client, monkeypatch):
    def outcome(floor):
        return fr.Outcome(matches=(), floor=floor)

    before = engine.multi_search(name=NAME, top_k=3).to_dict()["overall"]["grade"]
    grades = list(rm.GRADES)
    for floor in ("검토 권장", "위험"):
        monkeypatch.setattr(fr, "check", lambda *args, floor=floor, **kwargs: outcome(floor))
        overall = engine.multi_search(name=NAME, top_k=3).to_dict()["overall"]
        raised = grades.index(floor) > grades.index(before)
        assert overall["grade"] == (floor if raised else before)
        assert overall["famous_floor"] is raised
    # 후보가 하나도 없어도(전체 등급 없음) 바닥은 등급이 된다
    monkeypatch.setattr(fr, "check", lambda *args, **kwargs: outcome("검토 권장"))
    monkeypatch.setattr(ms, "_overall", lambda top: (None, None, None))
    overall = engine.multi_search(name=NAME, top_k=3).to_dict()["overall"]
    assert overall["grade"] == "검토 권장" and overall["prob"] is None
    assert overall["famous_floor"] is True


def test_image_query_gives_no_logo_match_with_fake_ml(client, monkeypatch):
    """가짜 임베딩은 유사도가 고정이라 로고 경로는 일치를 내지 않는다 — 이름 경로는 그대로."""
    data = engine.multi_search(image=_image(), top_k=3).to_dict()
    assert data["famous"]["matches"] == [] and data["overall"]["famous_floor"] is False
    both = engine.multi_search(image=_image(), name="스타벅스", top_k=3).to_dict()
    assert [m["basis"] for m in both["famous"]["matches"]] == ["이름"]


def test_image_text_is_checked_only_without_a_name(client, monkeypatch):
    """이름이 없고 검색이 이미지에서 읽은 글자(OCR 제안 상표명)가 있으면 그 글자로 확인한다 — OCR 을
    새로 돌리지 않는다."""
    calls = []

    def resolve(image, name, override):
        calls.append(name)
        return ms.QueryType("결합-도형요부", "ocr", {"text_ratio": 0.3, "fig_ratio": 0.4},
                            suggested_name=None if name else "STARBUCKS COFFEE"), False

    monkeypatch.setattr(ms, "_resolve_query_type", resolve)
    data = engine.multi_search(image=_image(), top_k=3).to_dict()
    match = data["famous"]["matches"][0]
    assert (match["brand"], match["level"]) == ("스타벅스", "강함")
    assert match["basis"] == "이미지 속 글자"
    assert match["notation"] in ("STARBUCKS", "STARBUCKS COFFEE") and match["floor"] == "위험"
    assert match["matched_text"] and match["matched_text"].startswith("STARBUCKS")
    assert data["overall"]["grade"] == "위험" and len(calls) == 1
    named = engine.multi_search(image=_image(), name=NAME, top_k=3).to_dict()
    assert named["famous"]["matches"] == []


def test_query_kind_comes_from_the_searchs_type_detection():
    def kind(level, source, detail=None):
        return ms._famous_query_kind(ms.QueryType(level, source, detail))

    assert kind("도형", "ocr", {"text_ratio": 0.0, "fig_ratio": 0.5}) == "도형 위주"
    assert kind("문자", "ocr", {"text_ratio": 0.4, "fig_ratio": 0.01}) == "글자 위주"
    assert kind("결합-문자요부", "ocr", {"text_ratio": 0.3, "fig_ratio": 0.4}) == "결합"
    assert kind("도형", "fallback") is None  # OCR 실패 — 구분 모름
    assert kind("문자", "user") == "글자 위주" and kind("결합-도형요부", "user") == "결합"


def test_candidates_of_registry_marks_carry_the_brand(client, monkeypatch, v146):
    runtime = replace(ms.state.famous, brand_of_mark={FIRST: "스타벅스"},
                      brand_logos={"스타벅스": (FIRST, "4020210000002", "4020210000003")})
    monkeypatch.setattr(ms.state, "famous", runtime)
    data = engine.multi_search(name="스타벅스", top_k=9).to_dict()
    tagged = {c["id"]: c.get("famous_brand") for c in data["candidates"]}
    assert tagged[FIRST] == "스타벅스"
    assert all(brand is None for appno, brand in tagged.items() if appno != FIRST)
    assert all("famous_brand" not in c for c in data["candidates"] if c["id"] != FIRST)
    # 대표 로고는 최대 2건 — 출원번호와 기존 이미지 경로
    logos = data["famous"]["matches"][0]["logos"]
    assert [logo["id"] for logo in logos] == [FIRST, "4020210000002"]
    by_id = {c["id"]: c["image_url"] for c in data["candidates"]}
    assert logos[0]["image_url"] == by_id[FIRST] and logos[0]["image_url"]
    SearchV2Response.model_validate(data)
    monkeypatch.setattr(ms.state, "model", v146)
    old = engine.multi_search(name="스타벅스", top_k=9).to_dict()
    assert all("famous_brand" not in c for c in old["candidates"])


def test_failure_in_the_check_does_not_fail_the_search(client, monkeypatch, caplog):
    """확인에서 예외가 나면 검색은 그대로 내고 '확인하지 못함'만 남긴다 — 로그에 질의 이름 없음."""
    secret = "스타벅스 비밀이름"

    def boom(*args, **kwargs):
        raise RuntimeError(f"질의 {secret} 처리 실패")

    expected = engine.multi_search(name=secret, top_k=5).to_dict()
    monkeypatch.setattr(fr, "check", boom)
    with caplog.at_level(logging.INFO):
        data = engine.multi_search(name=secret, top_k=5).to_dict()
    assert data["famous"] == {"status": "unavailable", "matches": [],
                              "brand_count": ms.state.famous.brand_count}
    assert data["overall"]["famous_floor"] is False
    assert data["candidates"] == expected["candidates"]
    assert "유명 상표 확인 실패(RuntimeError)" in caplog.text
    assert secret not in caplog.text and "스타벅스" not in caplog.text
    SearchV2Response.model_validate(data)


def test_api_passes_the_new_fields_through(client):
    response = client.post("/search/v2", files={"name": (None, "스타벅스")})
    assert response.status_code == 200
    body = response.json()
    assert body["famous"]["matches"][0]["brand"] == "스타벅스"
    assert body["overall"]["famous_floor"] is True and body["overall"]["grade"] == "위험"
    assert body["meta"]["model_version"] == "risk_model_v1.4.7"


def test_search_log_has_no_query_text(client, caplog):
    with caplog.at_level(logging.INFO):
        engine.multi_search(name="스타벅스 비밀이름", top_k=3)
    assert "famous=checked" in caplog.text
    assert "스타벅스" not in caplog.text and "비밀이름" not in caplog.text
