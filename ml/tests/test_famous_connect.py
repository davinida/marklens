"""famous_connect.py(유명 상표 확인의 서비스 연결 — 통합 모델 설계 §7-14-13)의 순수 함수.

v1.4.7 계수 JSON 만들기, 대표 로고 구분 파일의 꼴, v1.4.6 대 v1.4.7 응답 견주기, 시간 요약. 실제
엔진을 쓰는 kinds·verify 명령은 시험하지 않는다.
"""

from __future__ import annotations

import copy
import json

import pytest
from src import famous_check as fc
from src import famous_runtime as fr
from src.model import risk_model as rm

from scripts import famous_connect as cn


def test_apply_reproduces_the_shipped_model():
    """apply 가 만드는 것 = 저장소의 v1.4.7 JSON — v1.4.6 과 version·famous_check·
    meta.famous_check 만 다르고, 표시의 sha256 은 저장소의 확정 파일의 것."""
    if not rm.V147_MODEL_PATH.exists():
        pytest.skip("v1.4.7 계수 파일 없음")
    base = json.loads(rm.V146_MODEL_PATH.read_text(encoding="utf-8"))
    built = cn.candidate_model(base)
    assert built == json.loads(rm.V147_MODEL_PATH.read_text(encoding="utf-8"))
    assert cn.differing_keys(base, built) == ["famous_check", "meta.famous_check", "version"]
    assert built[rm.FAMOUS_CHECK_KEY]["confirmed_sha256"] == fr.file_sha256(fr.CONFIRMED_PATH)
    assert (cn.BASE_VERSION, cn.NEW_VERSION) == ("risk_model_v1.4.6", rm.MODEL_VERSION)
    assert base["version"] == cn.BASE_VERSION  # 원본은 그대로


def test_logo_kinds_file_shape():
    registry = fc.load_registry()
    data = cn.kinds_file({"4020200000002": "결합", "4020200000001": "글자 위주"}, registry)
    assert data["version"] == fr.LOGO_KINDS_VERSION
    assert data["registry_sha256"] == fr.file_sha256(fc.DEFAULT_REGISTRY_PATH)
    assert list(data["kinds"]) == ["4020200000001", "4020200000002"]  # 출원번호 순
    assert data["counts"] == {"결합": 1, "글자 위주": 1}
    # 저장소의 파일도 같은 꼴이고 지금 등록부의 것이다
    shipped = json.loads(fr.LOGO_KINDS_PATH.read_text(encoding="utf-8"))
    assert shipped["version"] == data["version"]
    assert shipped["registry_sha256"] == data["registry_sha256"]
    assert sum(shipped["counts"].values()) == len(shipped["kinds"])


def _response(grade="주의", *, famous=None, floored=None, brand=None) -> dict:
    candidate = {"id": "4020200000001", "risk": {"grade": grade, "prob": 0.3}}
    if brand:
        candidate["famous_brand"] = brand
    overall = {"grade": grade, "prob": 0.3, "pattern": "base", "caveats": [],
               "query_type": {"type": "문자"}, "visual_status": None}
    data = {"api_version": "2026-10-24", "overall": overall, "candidates": [candidate],
            "meta": {"model_version": "x", "grade_precision": 0.7, "thresholds": {}, "pool": {},
                     "elapsed_ms": 1},
            "dataset_info": {}, "index_size": 9, "top_k_requested": 5, "top_k_returned": 1}
    if famous is not None:
        overall["famous_floor"] = bool(floored)
        data["famous"] = famous
    return data


def _famous(*floors: str | None) -> dict:
    return {"status": fr.STATUS_CHECKED, "brand_count": 58,
            "matches": [{"brand": f"브랜드{index}", "level": "강함", "basis": "이름",
                         "floor": floor} for index, floor in enumerate(floors)]}


def test_compare_responses_allows_only_the_new_fields_and_the_floor():
    before = _response("주의")
    # 일치 없음 — 새 필드만 더해진 응답
    assert cn.compare_responses(before, _response("주의", famous=_famous())) == []
    # 바닥이 전체 등급을 올린 응답 — 후보에는 브랜드 표시가 더해질 수 있다
    raised = _response("주의", famous=_famous("위험"), floored=True, brand="브랜드0")
    raised["overall"]["grade"] = "위험"
    assert cn.compare_responses(before, raised) == []
    # 일치는 있지만 바닥이 등급을 바꾸지 않은 응답
    assert cn.compare_responses(_response("위험"),
                                _response("위험", famous=_famous("위험"))) == []

    def problems(after: dict, start: dict = before) -> list[str]:
        return cn.compare_responses(start, after)

    changed = _response("주의", famous=_famous())
    changed["candidates"][0]["risk"]["prob"] = 0.31
    assert "후보 배열이 다름" in problems(changed)
    lowered = _response("주의", famous=_famous())
    lowered["overall"]["grade"] = "안전"
    assert "전체 등급이 내려감" in problems(lowered)
    unexplained = _response("주의", famous=_famous())
    unexplained["overall"]["grade"] = "검토 권장"
    assert "일치가 없는데 전체 등급이 달라짐" in problems(unexplained)
    unmarked = copy.deepcopy(raised)
    unmarked["overall"]["famous_floor"] = False
    assert "전체 등급이 달라진 것과 famous_floor 가 어긋남" in problems(unmarked)
    other = _response("주의", famous=_famous())
    other["overall"]["caveats"] = ["새 문구"]
    assert "overall.caveats 가 다름" in problems(other)
    assert "v1.4.7 응답에 유명 상표 확인이 없음" in problems(_response("주의"))
    assert "v1.4.6 응답에 새 필드가 있음" in problems(
        _response("주의", famous=_famous()), _response("주의", famous=_famous()))


def test_timing_summary():
    rows = [{"묶음": "가", "질의": str(index), "ms": float(index), "이름_있음": index % 2 == 0,
             "일치": ["x"] if index == 9 else []} for index in range(1, 11)]
    table = cn.timing(rows)
    assert table["전체"] == {"질의": 10, "중앙값_ms": 5.5, "95%_ms": 10.0, "최대_ms": 10.0}
    assert table["이름_있는_질의"]["질의"] == 5 and table["이름_없는_질의"]["질의"] == 5
    assert table["일치가_있는_질의"] == {"질의": 1, "중앙값_ms": 9.0, "95%_ms": 9.0,
                                    "최대_ms": 9.0}
    assert [row["ms"] for row in table["가장_느린_질의"]][:3] == [10.0, 9.0, 8.0]
    assert cn.timing([])["전체"]["중앙값_ms"] is None
