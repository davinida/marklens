"""engine.multi_search(3입력 통합 검색, API 계약 v2) — FAKE_ML 픽스처(더미 9건, 가짜 CLIP·X3·OCR,
실제 계수 JSON).

입력 조합 7가지·caveat 문구·로짓 검산·정렬·규칙 트리거·§3 예시와 키 집합·예외·로그를 본다.
엔드포인트는 다른 사람 몫이라 여기서는 엔진 함수만 부른다(TestClient 는 lifespan 으로 엔진을 띄우는
용도).
"""

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.src.core import config, engine
from backend.src.core import multi_search as ms
from backend.src.main import app

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "MarkLens_API계약_v2.md"
GOODS = ["S0101"]  # 픽스처 9건 전부의 유사군
NAME = "더미상표1"  # 픽스처 1번 상표명(정확 일치 → 단독 규칙이 걸린다)
# 질의 이름 — "커피"는 약한 토큰이라 제외 토큰(removed)이 생기고, 나머지는 1번 상표명과 같다.
NAME_Q = "더미상표1 커피"


@pytest.fixture(scope="module")
def client(fake_ml_mode):
    if not fake_ml_mode:
        pytest.skip("FAKE_ML 픽스처(더미 9건) 전용 테스트")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def ocr_on(monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)


def _image():
    return Image.new("RGB", (64, 64), (200, 40, 40))


def _key_paths(obj, prefix: str = "") -> set[str]:
    """중첩 키 경로 집합 — 목록은 모든 원소의 합집합, null 은 잎."""
    paths: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            paths.add(path)
            paths |= _key_paths(value, path)
    elif isinstance(obj, list):
        for item in obj:
            paths |= _key_paths(item, prefix)
    return paths


def _contract_examples() -> list[dict]:
    text = CONTRACT.read_text(encoding="utf-8")
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)```", text, flags=re.S)]


def _assert_logit(candidate: dict, intercept: float) -> None:
    risk = candidate["risk"]
    logit = intercept + sum(risk["contributions"].values()) + risk["missing_adjustment"]
    assert abs(1.0 / (1.0 + math.exp(-logit)) - risk["prob"]) <= 0.001


def test_startup_prepared_caches(client):
    assert ms.state.ready and ms.state.error == ""
    assert len(ms.state.records) == 9 and len(ms.state.spelling_entries) == 9
    assert ms.state.goods_index == {"S0101": tuple(r.appno for r in ms.state.records)}
    assert ms.state.embeddings is not None and ms.state.embeddings.shape[0] == 10
    assert ms.state.model["version"] == "risk_model_v1.2.1"
    assert ms.state.grade_precision == ms.state.model["meta"]["grade_precision"]


def test_name_only(client, ocr_on):
    result = engine.multi_search(name=NAME_Q, top_k=5)
    data = result.to_dict()
    assert data["overall"]["query_type"] == {
        "type": "문자", "source": "fallback", "detail": None, "suggested_name": None,
    }
    assert data["overall"]["visual_status"] is None
    caveats = data["overall"]["caveats"]
    assert ms.CAVEAT_NO_IMAGE in caveats and ms.CAVEAT_NO_GOODS in caveats
    assert ms.CAVEAT_NO_NAME not in caveats and ms.CAVEAT_NO_CANDIDATES not in caveats
    pool = data["meta"]["pool"]
    assert pool["image"] == 0 and pool["goods"] == 0
    assert pool["phonetic"] > 0 and pool["spelling"] > 0
    assert pool["total"] >= max(pool["phonetic"], pool["spelling"])
    assert data["top_k_requested"] == 5 and data["top_k_returned"] == len(data["candidates"]) == 5
    probs = [c["risk"]["prob"] for c in data["candidates"]]
    assert probs == sorted(probs, reverse=True)
    assert data["overall"]["prob"] == probs[0]
    for candidate in data["candidates"]:
        assert candidate["axes"]["x2_img"] is None and candidate["axes"]["x4"] is None
        assert candidate["axes"]["x1"] is not None and candidate["axes"]["x2_text"] is not None
        assert set(candidate["risk"]["contributions"]) == set(ms.CONTRIBUTION_KEYS)
        _assert_logit(candidate, ms.state.model["intercept"])
    top = data["candidates"][0]
    assert top["id"] == "4020210000001" and top["title"] == NAME
    assert top["axes"]["x1"] == 1.0 and top["axes"]["x2_text"] == 1.0
    assert "standalone_x1" in top["risk"]["rule_triggers"]
    assert "standalone_x2_text" in top["risk"]["rule_triggers"]
    assert top["risk"]["grade"] in ("검토 권장", "위험")
    assert top["salient"]["query_tokens"] == ["더미상표"]
    assert [item["token"] for item in top["salient"]["removed"]] == ["커피"]
    assert top["salient"]["removed"][0]["side"] == "query"
    # 1호는 상품 상대적 — 후보 유사군(S0101)과 커피(30류)가 달라 통계(일반어·다수 등록)로 약해진다
    reason = top["salient"]["removed"][0]["reason"]
    assert any(key in reason for key in ("1호", "일반어", "다수 등록"))
    assert top["type"] == "결합" and top["applicant"] == "테스트 출원인"
    assert top["nice_classes"] == [35]
    assert top["image_url"] == "/images/4020210000001.png"


def test_image_only_uses_fake_ocr_and_figure_rule(client, ocr_on):
    data = engine.multi_search(image=_image(), top_k=3).to_dict()
    query_type = data["overall"]["query_type"]
    assert query_type["type"] == "도형" and query_type["source"] == "ocr"
    assert set(query_type["detail"]) == {"text_ratio", "fig_ratio"}
    assert query_type["suggested_name"] is None  # 가짜 OCR 은 글자를 읽지 않는다
    assert data["overall"]["visual_status"] == "STRONG_MATCH"  # 가짜 CLIP 은 1번 벡터와 1.0
    caveats = data["overall"]["caveats"]
    assert caveats[0] == ms.state.model["figure_rule"]["caveat"] == ms.CAVEAT_FIGURE_LOW_DATA
    assert ms.CAVEAT_NO_NAME in caveats and ms.CAVEAT_NO_GOODS in caveats
    assert ms.CAVEAT_NO_IMAGE not in caveats
    pool = data["meta"]["pool"]
    assert pool["image"] == 9 and pool["total"] == 9 and pool["phonetic"] == 0
    top = data["candidates"][0]
    assert top["id"] == "4020210000001" and top["axes"]["x2_img"] == 1.0
    assert top["risk"]["figure_caveat"] is True
    assert top["risk"]["rule_triggers"] == ["figure_x2_img"] and top["risk"]["grade"] == "검토 권장"
    for candidate in data["candidates"]:
        assert all(candidate["axes"][key] is None for key in ("x1", "x2_text", "x3", "x4"))
        assert candidate["salient"]["query_tokens"] == [] and candidate["salient"]["removed"] == []
        assert candidate["risk"]["contributions"]["X2"] == 0.0  # 도형계: CLIP 효과 상쇄(설계 §7-2)
        _assert_logit(candidate, ms.state.model["intercept"])
    x2 = [c["axes"]["x2_img"] for c in data["candidates"]]
    assert x2 == sorted(x2, reverse=True)  # 동점 p 는 x2_img 내림차순


def test_goods_only(client):
    data = engine.multi_search(goods_codes=GOODS, top_k=20).to_dict()
    assert data["meta"]["pool"] == {
        "image": 0, "phonetic": 0, "spelling": 0, "semantic": 0, "goods": 9, "total": 9,
    }
    caveats = data["overall"]["caveats"]
    assert ms.CAVEAT_GOODS_ONLY in caveats and ms.CAVEAT_NO_IMAGE in caveats
    assert ms.CAVEAT_NO_NAME in caveats and ms.CAVEAT_NO_GOODS not in caveats
    assert "9/10건" in next(c for c in caveats if c.startswith("비교 대상 중"))
    assert data["overall"]["query_type"]["type"] == "문자"
    assert all(c["axes"]["x4"] == 1.0 and c["goods"]["jaccard"] == 1.0 for c in data["candidates"])
    assert all(c["goods"]["codes"] == ["S0101"] for c in data["candidates"])
    # 상품만 넣으면 x4 뿐이라 등급 상한은 "주의"(계약 §5-3)
    assert all(c["risk"]["grade"] in ("안전", "주의") for c in data["candidates"])


def test_image_and_name(client, ocr_on):
    data = engine.multi_search(image=_image(), name=NAME).to_dict()
    caveats = data["overall"]["caveats"]
    assert ms.CAVEAT_NO_IMAGE not in caveats and ms.CAVEAT_NO_NAME not in caveats
    assert ms.CAVEAT_NO_GOODS in caveats
    assert data["overall"]["query_type"]["source"] == "ocr"
    # 이름이 있으면 문자계 — 단색 이미지는 fig_ratio 0 이라 문자
    assert data["overall"]["query_type"]["type"] == "문자"
    assert data["overall"]["query_type"]["suggested_name"] is None
    assert ms.CAVEAT_FIGURE_LOW_DATA not in caveats
    assert data["meta"]["pool"]["image"] == 9 and data["meta"]["pool"]["phonetic"] > 0
    top = data["candidates"][0]
    assert top["axes"]["x2_img"] is not None and top["axes"]["x1"] is not None


def test_name_and_goods(client):
    data = engine.multi_search(name=NAME, goods_codes=GOODS).to_dict()
    caveats = data["overall"]["caveats"]
    assert ms.CAVEAT_NO_IMAGE in caveats and ms.CAVEAT_NO_GOODS not in caveats
    assert any(c.startswith("비교 대상 중 지정상품 정보가 있는 상표는") for c in caveats)
    assert ms.CAVEAT_GOODS_ONLY not in caveats
    assert all(c["axes"]["x4"] == 1.0 for c in data["candidates"])


def test_all_three_inputs(client, ocr_on):
    data = engine.multi_search(image=_image(), name=NAME, goods_codes=GOODS, top_k=2).to_dict()
    caveats = data["overall"]["caveats"]
    for text in (ms.CAVEAT_NO_IMAGE, ms.CAVEAT_NO_NAME, ms.CAVEAT_NO_GOODS, ms.CAVEAT_GOODS_ONLY):
        assert text not in caveats
    assert ms.CAVEAT_FIGURE_LOW_DATA not in caveats  # 이름이 있으면 도형계가 아니다
    assert data["overall"]["query_type"]["type"] == "문자"
    assert data["top_k_returned"] == 2
    top = data["candidates"][0]
    assert all(top["axes"][key] is not None for key in ("x1", "x2_text", "x2_img", "x4"))
    _assert_logit(top, ms.state.model["intercept"])


def test_type_override_wins_over_ocr(client, ocr_on):
    with_name = engine.multi_search(image=_image(), name=NAME, type_override="결합").to_dict()
    assert with_name["overall"]["query_type"] == {
        "type": "결합-문자요부", "source": "user", "detail": None, "suggested_name": None,
    }
    without_name = engine.multi_search(image=_image(), type_override="결합").to_dict()
    assert without_name["overall"]["query_type"]["type"] == "결합-도형요부"
    plain = engine.multi_search(name=NAME, type_override="도형").to_dict()
    assert plain["overall"]["query_type"]["type"] == "도형"
    assert ms.CAVEAT_FIGURE_LOW_DATA in plain["overall"]["caveats"]
    assert all(c["risk"]["figure_caveat"] for c in plain["candidates"])


def test_ocr_fallback_caveat(client, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", False)
    with_name = engine.multi_search(image=_image(), name=NAME).to_dict()
    expected = {"type": "문자", "source": "fallback", "detail": None, "suggested_name": None}
    assert with_name["overall"]["query_type"] == expected
    assert ms.CAVEAT_OCR_FALLBACK.format(type="문자", ro="로") in with_name["overall"]["caveats"]
    image_only = engine.multi_search(image=_image()).to_dict()
    assert image_only["overall"]["query_type"]["type"] == "도형"
    assert ms.CAVEAT_OCR_FALLBACK.format(type="도형", ro="으로") in image_only["overall"]["caveats"]


def test_key_sets_match_contract_examples(client, ocr_on):
    text_example, image_example = _contract_examples()
    name_result = engine.multi_search(name=NAME_Q, top_k=4).to_dict()
    image_result = engine.multi_search(image=_image(), top_k=3).to_dict()
    assert _key_paths(name_result) == _key_paths(text_example)
    assert _key_paths(image_result) == _key_paths(image_example)
    for payload in (name_result, image_result):
        json.dumps(payload, ensure_ascii=False)  # 직렬화 가능(numpy 타입 없음)


def test_caveat_texts_match_contract_table():
    text = CONTRACT.read_text(encoding="utf-8")
    table = {}
    for line in text.splitlines():
        match = re.match(r"^\| `([A-Z0-9_]+)` \| (.+?) \| ", line)
        if match:
            table[match.group(1)] = match.group(2).replace("\\|", "|")
    assert table["FIGURE_LOW_DATA"] == ms.CAVEAT_FIGURE_LOW_DATA
    assert table["NO_IMAGE"] == ms.CAVEAT_NO_IMAGE
    assert table["NO_NAME"] == ms.CAVEAT_NO_NAME
    assert table["NO_PRONUNCIATION"] == ms.CAVEAT_NO_PRONUNCIATION
    assert table["NO_MEANING"] == ms.CAVEAT_NO_MEANING
    assert table["NO_GOODS"] == ms.CAVEAT_NO_GOODS
    assert table["GOODS_ONLY"] == ms.CAVEAT_GOODS_ONLY
    assert table["NO_CANDIDATES"] == ms.CAVEAT_NO_CANDIDATES
    assert table["X3_DISABLED"] == ms.CAVEAT_X3_DISABLED
    suggested = ms.CAVEAT_NAME_SUGGESTED.format(text="BLU")
    assert table["NAME_SUGGESTED"].replace("{텍스트}", "BLU") == suggested
    coverage = ms.CAVEAT_GOODS_COVERAGE.format(with_goods="100", total="1,100")
    assert table["GOODS_COVERAGE"] == coverage
    assert table["OCR_FALLBACK"].replace("{도형|문자}(으)로", "도형으로") == (
        ms.CAVEAT_OCR_FALLBACK.format(type="도형", ro="으로")
    )


def test_meta_thresholds_come_from_model_json(client):
    data = engine.multi_search(name=NAME).to_dict()
    model = ms.state.model
    assert data["meta"]["model_version"] == model["version"]
    assert data["meta"]["grade_precision"] == model["meta"]["grade_precision"] == 0.6855
    assert data["meta"]["thresholds"]["grade"] == model["grade_thresholds"]
    assert data["meta"]["thresholds"]["standalone"] == {
        "x1": model["standalone_thresholds"]["x1_d"],
        "x2_text": model["standalone_thresholds"]["x2_text_d"],
        "x2_img": model["standalone_thresholds"]["x2_whole"],
        "x3": model["standalone_thresholds"]["x3_d"],
        "x4": model["standalone_thresholds"]["x4"],
    }
    assert data["meta"]["thresholds"]["figure"] == model["figure_rule"]["threshold"]
    assert data["api_version"] == ms.API_VERSION and data["research_beta"] is True
    assert data["legal_conclusion"] is False and data["index_size"] == 10
    assert set(data["dataset_info"]) == {"총_상표수", "출원일자_범위", "데이터_기준", "생성일자"}


def test_errors(client, monkeypatch):
    with pytest.raises(ms.EmptyQueryError):
        engine.multi_search()
    with pytest.raises(ms.EmptyQueryError):
        engine.multi_search(name="   ", goods_codes=["", " "])
    with pytest.raises(ValueError):
        engine.multi_search(name=NAME, top_k=0)
    with pytest.raises(ValueError):
        engine.multi_search(name=NAME, top_k=21)
    with pytest.raises(ValueError):
        engine.multi_search(name=NAME, type_override="사진")
    monkeypatch.setattr(ms.state, "model", None)
    monkeypatch.setattr(ms.state, "error", "계수 JSON: 테스트")
    with pytest.raises(ms.ModelNotReadyError):
        engine.multi_search(name=NAME)


def test_engine_not_ready_raises_runtime_error(client, monkeypatch):
    monkeypatch.setattr(engine.state, "ready", False)
    with pytest.raises(RuntimeError):
        engine.multi_search(name=NAME)


def test_logs_do_not_contain_query(client, caplog):
    with caplog.at_level(logging.INFO, logger="backend.src.core.multi_search"):
        engine.multi_search(name=NAME, goods_codes=GOODS)
    assert any("multi_search: pool=" in record.message for record in caplog.records)
    assert NAME not in caplog.text and "S0101" not in caplog.text


def test_no_candidates_when_name_has_no_match(client, monkeypatch):
    monkeypatch.setattr(ms.state, "spelling_entries", ())
    monkeypatch.setattr(ms.state, "by_appno", {})
    data = engine.multi_search(name="☆☆☆").to_dict()
    assert data["candidates"] == [] and data["overall"]["grade"] is None
    assert data["overall"]["prob"] is None
    assert ms.CAVEAT_NO_CANDIDATES in data["overall"]["caveats"]
    assert ms.CAVEAT_NO_PRONUNCIATION in data["overall"]["caveats"]
    assert data["meta"]["pool"]["total"] == 0


def _figure_image():
    """글자 없이 뚜렷한 도형 영역만 있는 이미지 — 가짜 OCR: text_ratio 0, fig_ratio 0.36."""
    from PIL import ImageDraw

    image = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(image).rectangle((20, 20, 80, 80), fill="black")
    return image


def _ocr_reads(text: str, text_ratio: float = 0.3, fig_ratio: float = 0.5):
    from backend.src.core.ocr import TypeDetection

    def fake(image, timeout=None):
        return TypeDetection(text_ratio, fig_ratio, "결합", "도형", 1, text, 1.0)

    return fake


def test_rule_name_with_figure_image_is_text_family(client, ocr_on):
    data = engine.multi_search(image=_figure_image(), name=NAME).to_dict()
    query_type = data["overall"]["query_type"]
    assert query_type["type"] == "결합-문자요부" and query_type["source"] == "ocr"
    assert query_type["detail"]["fig_ratio"] >= 0.08 and query_type["suggested_name"] is None
    assert ms.CAVEAT_FIGURE_LOW_DATA not in data["overall"]["caveats"]
    assert all(c["risk"]["figure_caveat"] is False for c in data["candidates"])
    top = data["candidates"][0]
    assert top["id"] == "4020210000001" and "standalone_x1" in top["risk"]["rule_triggers"]


def test_rule_name_with_ocr_failure_stays_text(client, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(ms.ocr, "detect", lambda image, timeout=None: None)
    data = engine.multi_search(image=_figure_image(), name=NAME).to_dict()
    assert data["overall"]["query_type"] == {
        "type": "문자", "source": "fallback", "detail": None, "suggested_name": None,
    }
    assert ms.CAVEAT_OCR_FALLBACK.format(type="문자", ro="로") in data["overall"]["caveats"]
    assert ms.CAVEAT_FIGURE_LOW_DATA not in data["overall"]["caveats"]


def test_rule_image_only_with_ocr_text_suggests_name(client, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(ms.ocr, "detect", _ocr_reads("BLU hands"))
    data = engine.multi_search(image=_image()).to_dict()
    query_type = data["overall"]["query_type"]
    assert query_type["type"] == "결합-도형요부"  # 글자 영역 ≥ 0.05 → 결합-도형요부(도형계)
    assert query_type["source"] == "ocr"
    assert query_type["suggested_name"] == "BLU hands"
    caveats = data["overall"]["caveats"]
    assert ms.CAVEAT_NAME_SUGGESTED.format(text="BLU hands") in caveats
    assert ms.CAVEAT_FIGURE_LOW_DATA in caveats and ms.CAVEAT_NO_NAME in caveats
    assert data["meta"]["pool"]["phonetic"] == 0  # 이름 축은 자동 계산하지 않는다(재요청)
    assert all(c["axes"]["x1"] is None for c in data["candidates"])
    assert all(c["risk"]["figure_caveat"] for c in data["candidates"])


def test_rule_image_only_without_text_is_figure(client, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(ms.ocr, "detect", _ocr_reads("", text_ratio=0.0, fig_ratio=0.7))
    data = engine.multi_search(image=_image()).to_dict()
    assert data["overall"]["query_type"]["type"] == "도형"
    assert data["overall"]["query_type"]["suggested_name"] is None
    assert not any(c.startswith("이미지에서 '") for c in data["overall"]["caveats"])
    disabled = engine.multi_search(image=_image(), type_override="도형", name=NAME).to_dict()
    assert disabled["overall"]["query_type"]["type"] == "도형"  # 사용자 선택은 그대로 도형계
    assert disabled["overall"]["query_type"]["source"] == "user"
    assert ms.CAVEAT_FIGURE_LOW_DATA in disabled["overall"]["caveats"]

