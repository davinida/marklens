"""질의 이름의 낱말별 식별력을 응답에 싣기(설명적 이름 안내 — 계약 v2 §2-7) — FAKE_ML 픽스처.

엔진이 새로 판정하지 않고 식별력 모듈의 판정을 그대로 싣는지, 후보 목록·전체 등급이 그대로인지,
이름이 없는 질의에는 싣지 않는지, 정리에서 예외가 나도 검색은 그대로 나가는지를 본다. 분류표와
정리 규칙 자체는 ml/tests/test_name_words.py 가 본다.
"""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.src.core import engine
from backend.src.core import multi_search as ms
from backend.src.main import app
from backend.src.schemas.search_v2 import SearchV2Response

nw = ms.nw  # src.name_words — 엔진이 쓰는 것과 같은 객체

CAFE = ["G0502", "S2039"]  # 픽스처 변환표의 커피(30류)·커피 판매업(35류)
NAME = "더미상표1 커피"  # 낱말: 더미상표(조어) · 1(한 글자) · 커피(카페의 상품 이름)


@pytest.fixture(scope="module")
def client(fake_ml_mode):
    if not fake_ml_mode:
        pytest.skip("FAKE_ML 픽스처(더미 9건) 전용 테스트")
    with TestClient(app) as test_client:
        yield test_client


def _image():
    return Image.new("RGB", (64, 64), (200, 40, 40))


def _judged(name: str, goods) -> list:
    """엔진이 후보마다 요부를 정할 때와 같은 이름(접미어 분리 뒤)·같은 함수 — 업종은 질의의 것만."""
    distinct = ms.state.distinct
    codes = frozenset(goods) if goods else None
    return distinct.judge_name(distinct.split_goods_suffix(ms.clean_name(name)), codes)


def _plain(data: dict) -> str:
    data = json.loads(json.dumps(data))
    data.pop("name_words", None)
    data["meta"].pop("elapsed_ms")
    return json.dumps(data, ensure_ascii=False)


def test_named_query_carries_the_engines_word_judgements(client):
    data = engine.multi_search(name=NAME, goods_codes=CAFE, top_k=5).to_dict()
    words = data["name_words"]
    judged = _judged(NAME, CAFE)
    assert [w["word"] for w in words["words"]] == [j.token for j in judged] == [
        "더미상표", "1", "커피"]
    for word, judgement in zip(words["words"], judged):
        assert word["distinctive"] is (not judgement.is_weak)
        assert word["reason"] == "·".join(judgement.reasons)
        assert word["category"] == (nw.category(judgement.reasons) if judgement.is_weak else None)
    assert [(w["distinctive"], w["category"]) for w in words["words"]] == [
        (True, None), (False, "짧고 흔한 글자"), (False, "상품 이름")]
    assert (words["generic"], words["more"], words["more_generic"]) == ("some", 0, 0)
    # 응답의 자리 — 최상위(유명 상표 확인 다음, 후보 앞)
    keys = list(data)
    assert keys.index("famous") < keys.index("name_words") < keys.index("candidates")
    SearchV2Response.model_validate(data)


def test_all_words_generic(client):
    data = engine.multi_search(name="커피", goods_codes=CAFE).to_dict()
    assert data["name_words"] == {
        "generic": "all",
        "words": [{"word": "커피", "distinctive": False, "category": "상품 이름",
                   "reason": "3호 기술적 표장:원재료(류 30,35)·1호 보통명칭"}],
        "more": 0, "more_generic": 0}
    plain = engine.multi_search(name="더미상표").to_dict()["name_words"]
    assert plain["generic"] == "none" and plain["words"][0]["distinctive"] is True


def test_goods_suffix_split_word_is_listed(client):
    """붙여 쓴 이름의 끝이 고시 명칭이면 엔진이 뗀다(더미커피 → 더미 / 커피) — 뗀 낱말도 실린다."""
    words = engine.multi_search(name="더미커피", goods_codes=CAFE).to_dict()["name_words"]
    assert [(w["word"], w["distinctive"], w["category"]) for w in words["words"]] == [
        ("더미", True, None), ("커피", False, "상품 이름")]
    assert words["generic"] == "some"


def test_absent_without_a_name(client):
    assert "name_words" not in engine.multi_search(image=_image()).to_dict()
    assert "name_words" not in engine.multi_search(goods_codes=CAFE).to_dict()
    assert "name_words" not in engine.multi_search(image=_image(), goods_codes=CAFE).to_dict()
    assert "name_words" in engine.multi_search(image=_image(), name=NAME).to_dict()


def test_candidates_and_overall_grade_are_untouched(client, monkeypatch):
    """새 선택 필드 말고는 응답이 그대로다 — 낱말 정리를 끈 엔진과 글자까지 같다."""
    inputs = [dict(name=NAME, goods_codes=CAFE, top_k=9), dict(name=NAME, top_k=5),
              dict(name="커피", goods_codes=CAFE, top_k=5), dict(name="스타벅스", top_k=5),
              dict(image=_image(), name=NAME, goods_codes=CAFE, top_k=5),
              dict(name=NAME, type_override="도형", top_k=5)]
    with_field = [engine.multi_search(**kwargs).to_dict() for kwargs in inputs]
    monkeypatch.setattr(ms, "_name_words", lambda *args: None)
    without = [engine.multi_search(**kwargs).to_dict() for kwargs in inputs]
    for new, old in zip(with_field, without):
        assert "name_words" in new and "name_words" not in old
        assert _plain(new) == _plain(old)


def test_word_the_engine_used_as_salient_is_not_called_generic(client):
    """업종이 없는 질의 — 식별력 모듈은 '장갑'을 어느 업종의 상품 이름(전역 보통명칭)이라 약하다고
    보지만, 엔진은 후보의 업종(장갑과 무관)으로 판정해 요부 후보로 쓴다. 그런 낱말은 식별력 있음으로
    싣는다(응답이 식별력 없다고 한 낱말을 엔진이 요부로 쓴 일이 없게)."""
    name = "장갑 더미상표1"
    function = {j.token: j for j in _judged(name, None)}
    assert function["장갑"].is_weak and function["장갑"].reasons == ("1호 보통명칭(전역)",)
    pooled = ms.search_pool(name=name)
    assert all("장갑" in c.query_tokens for c in pooled.candidates if c.title)
    words = {w["word"]: w for w in pooled.name_words.to_dict()["words"]}
    assert words["장갑"]["distinctive"] is True and words["장갑"]["category"] is None
    assert "1호" not in words["장갑"]["reason"]  # 그 쌍의 판정(후보의 업종 기준)
    assert words["1"]["distinctive"] is False  # 업종과 무관한 사유는 그대로
    # 응답이 식별력 없다고 한 낱말은 어느 후보와 견줄 때도 요부 후보가 아니다
    for kwargs in (dict(name=name), dict(name=NAME, goods_codes=CAFE), dict(name="커피 장갑"),
                   dict(name="화장품 신발 의류", goods_codes=["G1201"])):
        pooled = ms.search_pool(**kwargs)
        weak = {w.word for w in pooled.name_words.words if not w.distinctive}
        for candidate in pooled.candidates:
            assert not weak & set(candidate.query_tokens)
    # 업종을 고른 질의에서는 식별력 모듈의 판정 그대로다
    for name, goods in ((NAME, CAFE), ("화장품 신발 의류", ["G1201"]), ("커피 장갑", CAFE)):
        got = ms.search_pool(name=name, goods_codes=goods).name_words.words
        assert [(w.word, w.distinctive, w.reason) for w in got] == [
            (j.token, not j.is_weak, "·".join(j.reasons)) for j in _judged(name, goods)]


def test_more_than_six_words(client):
    name = "더미상표1 커피 화장품 의류 신발 장갑 가나다라 마바사아"
    words = engine.multi_search(name=name, goods_codes=CAFE).to_dict()["name_words"]
    total = len({j.token for j in _judged(name, CAFE)})
    assert len(words["words"]) == nw.WORD_LIMIT == 6 and words["more"] == total - 6 > 0
    assert 0 <= words["more_generic"] <= words["more"]
    SearchV2Response.model_validate(engine.multi_search(name=name, goods_codes=CAFE).to_dict())


def test_failure_does_not_fail_the_search(client, monkeypatch, caplog):
    """정리에서 예외가 나면 그 필드만 빠진다 — 후보·등급은 그대로, 로그에 질의 이름 없음."""
    secret = "비밀이름 커피"
    expected = engine.multi_search(name=secret, goods_codes=CAFE).to_dict()

    def boom(*args, **kwargs):
        raise RuntimeError(f"질의 {secret} 처리 실패")

    monkeypatch.setattr(nw, "describe", boom)
    with caplog.at_level(logging.INFO):
        data = engine.multi_search(name=secret, goods_codes=CAFE).to_dict()
    assert "name_words" not in data
    assert _plain(data) == _plain(expected)
    assert "낱말별 식별력 정리 실패(RuntimeError)" in caplog.text
    assert "비밀이름" not in caplog.text and "커피" not in caplog.text


def test_search_log_does_not_gain_the_query_name(client, caplog):
    with caplog.at_level(logging.DEBUG):
        engine.multi_search(name="비밀이름 커피", goods_codes=CAFE, top_k=3)
    assert "multi_search:" in caplog.text
    assert "비밀이름" not in caplog.text and "커피" not in caplog.text


def test_api_passes_the_field_through(client):
    response = client.post("/search/v2", files={"name": (None, "커피"),
                                                "goods_codes": (None, "G0502,S2039")})
    assert response.status_code == 200
    body = response.json()
    assert body["name_words"]["generic"] == "all"
    assert body["name_words"]["words"][0]["category"] == "상품 이름"
    assert "name_words" not in client.post(
        "/search/v2", files={"goods_codes": (None, "G0502")}).json()
