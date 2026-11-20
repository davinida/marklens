"""실제 검색 기준 이름 없는 하한(ml/scripts/nameless_search_thresholds.py) — 표본 A·B 규칙, 정규화,
하한 계산, JSON 쓰기(엔진·CLIP 없이, 합성 데이터)."""

from __future__ import annotations

import copy
import io
import re

import numpy as np
import pytest
from PIL import Image
from src.model import risk_model as rm

from scripts import nameless_search_thresholds as nst


def _valid(codes):
    kept = frozenset(code for code in codes if re.fullmatch(r"[GS]\d{4,6}", code))
    return kept, len(list(codes)) - len(kept)


def test_applicant_and_name_normalization():
    assert nst.normalize_applicant("(주) 비지에프리테일") == "비지에프리테일"
    assert nst.normalize_applicant("㈜비지에프리테일") == "비지에프리테일"  # NFKC → (주)
    assert nst.normalize_applicant("동성제약주식회사") == "동성제약"
    assert nst.normalize_applicant("넷플릭스, 인크.") == "넷플릭스인크"
    assert nst.normalize_applicant("Starbucks  Corporation") == "starbuckscorporation"
    assert nst.split_applicants("A 주식회사|(주)B") == frozenset({"a", "b"})
    assert nst.split_applicants("더 포린 캔디 컴퍼니, 인코포레이티드") == frozenset(
        {"더포린캔디컴퍼니인코포레이티드"})  # 쉼표로 나누지 않는다
    assert nst.split_applicants("") == frozenset()
    assert nst.name_key("Hello  Dream!") == nst.name_key("hello dream") == "hellodream"


def test_calibrate_three_grades_with_figure_rule():
    named = ["안전"] * 5 + ["주의"] * 2 + ["검토 권장"] * 2 + ["위험"]  # ≥주의 5·≥검토 3·위험 1
    prob = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.95, 0.15]
    lifted = [False] * 9 + [True]
    out = nst.calibrate(named, prob, lifted)
    assert out["n"] == 10 and out["도형_규칙_발동"] == 1
    assert out["주의"]["k′"] == 4 and out["주의"]["하한"] == 0.6
    assert out["검토 권장"]["k′"] == 2 and out["검토 권장"]["하한"] == 0.8
    assert out["위험"]["이름_알_때_이상"] == 1 and out["위험"]["하한"] == 0.95  # 전체 p 1번째
    values = nst.thresholds_of(out)
    grades = [nst.final_grade(p, values, flag) for p, flag in zip(prob, lifted)]
    assert nst.at_least_counts(grades) == nst.at_least_counts(named)  # 이름 알 때와 같은 수


def test_calibrate_nulls_and_figure_only_report():
    out = nst.calibrate(["안전", "안전", "검토 권장"], [0.1, 0.2, 0.3], [True, True, False])
    assert out["위험"]["하한"] is None  # 이름 알 때 위험 0
    assert out["검토 권장"]["하한"] is None and out["검토 권장"]["도형_규칙만으로_목표_이상"]
    assert out["주의"]["하한"] is None
    floored = nst.calibrate(["주의", "안전"], [0.123456, 0.1], [False, False])
    assert floored["주의"]["하한"] == 0.1234


def test_ascending_final_grade_and_similarity_stop():
    assert nst.ascending({"주의": 0.2, "검토 권장": 0.3, "위험": None})
    assert nst.ascending({"주의": 0.2, "검토 권장": None, "위험": 0.5})
    assert not nst.ascending({"주의": 0.3, "검토 권장": 0.2, "위험": 0.5})
    thresholds = {"주의": 0.3, "검토 권장": 0.5, "위험": None}
    assert nst.final_grade(0.1, thresholds, True) == "검토 권장"
    assert nst.final_grade(0.99, thresholds, False) == "검토 권장"
    b = {"중앙값": 0.70, "상위10%": 0.80}
    assert nst.similarity_stop({"중앙값": 0.67, "상위10%": 0.77}, b)
    assert not nst.similarity_stop({"중앙값": 0.67, "상위10%": 0.79}, b)  # 둘 다여야 멈춤
    assert not nst.similarity_stop({"중앙값": None, "상위10%": None}, b)


def _png(path, size, color=(10, 20, 30)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())
    return path


def _label(case, kind, **extra):
    row = {"심판번호": case, "종류": kind, "유사여부_확정": "유사", "상표A_명칭": "",
           "상표A_번호": "", "goods_codes_this": "", "goods_codes_prior": "",
           "상대표장_번호_정규화": "",
           "상대표장_명칭_kipris": "", "상대표장_명칭_llm": "", "상대표장_명칭_본문": "",
           "상대표장_명칭_ocr": ""}
    return {**row, **extra}


def test_sample_a_sides_names_goods_applicants_and_screening(tmp_path):
    for case in ("c1", "c2", "c3", "c4", "c5", "c6", "c7"):
        (tmp_path / "images" / case).mkdir(parents=True)
    _png(tmp_path / "images/c1/this.png", (120, 90))
    _png(tmp_path / "images/c2/target.png", (100, 100), (1, 2, 3))
    _png(tmp_path / "images/c3/this.png", (50, 200), (4, 5, 6))  # 짧은 변 50 → 해상도
    _png(tmp_path / "images/c4/this.png", (120, 90))  # c1 과 같은 바이트 → 중복
    _png(tmp_path / "images/c5/this.png", (90, 90), (7, 8, 9))  # DB 번호
    _png(tmp_path / "images/c6/target.png", (99, 99), (9, 9, 9))  # 사진(가짜 판정)
    _png(tmp_path / "images/c7/this.png", (80, 80), (3, 3, 3))  # 이름 없음
    labels = [
        _label("c1", "거절결정불복", 상표A_명칭="SPINNER", 상표A_번호="4020130000001",
               goods_codes_this="G0301;V1004"),
        _label("c1", "거절결정불복", 상표A_명칭="SPINNER", 상표A_번호="4020130000001"),
        _label("c2", "권리범위확인(적극적)", 상대표장_명칭_llm="Teddy Bear",
               goods_codes_prior="S2005"),
        _label("c3", "거절결정불복", 상표A_명칭="LOWRES"),
        _label("c4", "거절결정불복", 상표A_명칭="COPY"),
        _label("c5", "거절결정불복", 상표A_명칭="INDB", 상표A_번호="4020990000009"),
        _label("c6", "권리범위확인(소극적)", 상대표장_명칭_ocr="PHOTO"),
        _label("c7", "거절결정불복"),
        _label("c8", "무효", 상표A_명칭="SKIP"),  # 무효는 표본 밖
        {**_label("c9", "거절결정불복", 상표A_명칭="UNLABELED"), "유사여부_확정": "제외"},
    ]
    trial_list = {"c1": {"청구인": "(주)스피너|B 주식회사", "피청구인": ""},
                  "c2": {"청구인": "권리자", "피청구인": "사용자 주식회사"},
                  "c6": {"청구인": "청구 사용자", "피청구인": "권리자"}}
    pairs = [{"심판번호": c, "이미지A": f"images/{c}/this.png", "이미지B": "",
              "상대role": "prior_1"} for c in ("c1", "c3", "c4", "c5", "c7")]
    pairs += [{"심판번호": c, "이미지A": f"images/{c}/this.png",
               "이미지B": f"images/{c}/target.png", "상대role": "target"} for c in ("c2", "c6")]
    candidates = nst.sample_a_candidates(labels, trial_list, pairs, tmp_path, _valid)
    by_key = {query.key: query for query in candidates}
    assert set(by_key) == {"A:c1:this", "A:c2:target", "A:c3:this", "A:c4:this", "A:c5:this",
                           "A:c6:target", "A:c7:this"}
    c1, c2 = by_key["A:c1:this"], by_key["A:c2:target"]
    assert c1.name == "SPINNER" and c1.name_source == "목록" and c1.goods == {"G0301"}
    assert c1.applicants == {"스피너", "b"} and "4020130000001" in c1.numbers
    assert c2.name == "Teddy Bear" and c2.name_source == "llm" and c2.goods == {"S2005"}
    assert c2.applicants == {"사용자"}  # 적극적 → 피청구인
    assert by_key["A:c6:target"].applicants == {"청구사용자"}  # 소극적 → 청구인

    def load(raw):
        return Image.open(io.BytesIO(raw))

    kept, reasons, listing = nst.screen_a(candidates, {"4020990000009"}, load,
                                          lambda image: image.size == (99, 99))
    assert [query.key for query in kept] == ["A:c1:this", "A:c2:target"]
    assert reasons == {"이미지 없음": 0, "디코딩 실패": 0, "DB에 있음": 1, "이름 없음": 1,
                       "해상도": 1, "사진": 1, "중복 이미지": 1}
    assert listing["중복 이미지"] == ["A:c4:this"] and kept[0].size == (120, 90)
    assert [label for label, _, _ in nst.mode_list(kept[0])] == ["이미지만", "이미지+상품"]


def test_keep_reason_self_and_same_applicant():
    query = nst.Query(key="B:1", sample="B", kind="", name="x", name_source="DB",
                      goods=frozenset(), applicants=frozenset({"비지에프리테일"}),
                      applicant_text="(주) 비지에프리테일", path=nst.Path(), self_id="1")
    assert nst.keep_reason(query, "1", "다른 회사") == "자기"
    assert nst.keep_reason(query, "2", "주식회사 비지에프리테일") == "같은 출원인"
    assert nst.keep_reason(query, "3", "지에스리테일") is None
    # DB 출원인 칸은 '|' 로 나뉜 공동 출원인 — 하나라도 겹치면 같은 출원인
    assert nst.keep_reason(query, "4", "주식회사 조흥|(주)비지에프리테일") == "같은 출원인"
    people = nst.split_applicants("김우정|이석준|오명준")
    assert people == nst.split_applicants("이석준|김우정|오명준")
    assert nst.mode_list(query) == [("이미지만", "x2_whole", False)]  # 유사군 없으면 ①만


def _base_model() -> dict:
    model = copy.deepcopy(rm.load_model(rm.V14_MODEL_PATH))
    model["meta"]["nameless"]["grade_thresholds"] = {"method": "옛 방식", "calibrated_at": "x"}
    model["figure_rule"]["caveat"] = "옛 문구"
    model["meta"].pop("figure_caveat_history", None)
    return model


def test_apply_to_model_history_caveat_and_idempotence():
    model = _base_model()
    old = {key: copy.deepcopy(block.get("grade_thresholds"))
           for key, block in model[rm.NAMELESS_KEY].items()}
    new = {"x2_whole": {"주의": 0.4, "검토 권장": 0.6, "위험": 0.8},
           "x2_whole+x4": {"주의": 0.35, "검토 권장": 0.55, "위험": None}}
    out = nst.apply_to_model(model, new, {"samples": {"A": 1}}, today="2026-11-20")
    for key, values in new.items():
        assert rm.grade_thresholds_for(out, rm.NAMELESS_PREFIX + key) == values
    meta = out["meta"]["nameless"]["grade_thresholds"]
    assert meta["method"] == nst.METHOD and meta["samples"] == {"A": 1}
    assert meta["rule_sha256"] == nst.rule_sha256() and len(meta["rule_sha256"]) == 64
    assert [entry["method"] for entry in meta["history"]] == ["옛 방식", nst.ATTEMPT1["method"]]
    assert meta["history"][0]["thresholds"] == old and meta["history"][1]["thresholds"] is None
    assert out["figure_rule"]["caveat"] == nst.FIGURE_CAVEAT
    assert out["meta"]["figure_caveat_history"][0]["이전"] == "옛 문구"
    for key in ("grade_thresholds", "patterns", "standalone_thresholds", "coupling"):
        assert out[key] == model[key]  # 이름 있는 쪽은 그대로
    again = nst.apply_to_model(out, new, {"samples": {"A": 1}}, today="2026-11-21")
    assert again["meta"]["nameless"]["grade_thresholds"]["history"] == meta["history"]
    assert again["meta"]["figure_caveat_history"] == out["meta"]["figure_caveat_history"]
    with pytest.raises(ValueError):  # 오름차순이 아니면 검증에서 막힌다
        nst.apply_to_model(model, {"x2_whole": {"주의": 0.5, "검토 권장": 0.4, "위험": None}},
                           {}, today="2026-11-20")


def test_percentile_and_quantiles():
    assert nst.percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert nst.percentile([], 0.5) is None
    summary = nst._quantiles([64, 100, 200])
    assert summary["n"] == 3 and summary["최소"] == 64 and summary["p50"] == 100.0
    assert np.isclose(nst.percentile(list(range(11)), 0.9), 9.0)


def test_applicant_alias_table(tmp_path):
    """출원인 별칭 표(shared/applicant_aliases.json, 사람 결정) — 묶음 안 이름은 한 출원인."""
    aliases = nst.load_aliases()
    ikea = nst.split_applicants("인터 이케아 시스템 비. 브이.", aliases)
    assert ikea == nst.split_applicants("인터 이케아 시스템스 비. 브이.", aliases)
    skt = nst.split_applicants("에스케이텔레콤 주식회사", aliases)
    assert skt == nst.split_applicants("에스케이텔레콤씨에스티원 주식회사", aliases)
    assert ikea != skt and len(set(aliases.values())) == 2  # 묶음 두 개
    assert nst.split_applicants("네이버 주식회사", aliases) != nst.split_applicants(
        "넷플릭스, 인크.", aliases)  # 같은 이름 다른 출원인은 그대로
    query = nst.Query(key="B:1", sample="B", kind="", name="T1", name_source="DB",
                      goods=frozenset(), applicants=nst.split_applicants(
                          "에스케이텔레콤씨에스티원 주식회사", aliases),
                      applicant_text="", path=nst.Path(), self_id="1")
    assert nst.keep_reason(query, "2", "에스케이텔레콤 주식회사", aliases) == "같은 출원인"
    plain = nst.Query(key="B:1", sample="B", kind="", name="T1", name_source="DB",
                      goods=frozenset(), applicants=nst.split_applicants(
                          "에스케이텔레콤씨에스티원 주식회사"),
                      applicant_text="", path=nst.Path(), self_id="1")
    assert nst.keep_reason(plain, "2", "에스케이텔레콤 주식회사") is None  # 별칭 없이는 다름
    broken = tmp_path / "aliases.json"
    for groups in ([{"names": ["A 주식회사", "(주)A"]}],  # 정규화하면 같은 이름 하나
                   [{"names": ["가", "나"]}, {"names": ["나", "다"]}]):  # 두 묶음에 같은 이름
        broken.write_text(nst.json.dumps({"groups": groups}, ensure_ascii=False),
                          encoding="utf-8")
        with pytest.raises(ValueError):
            nst.load_aliases(broken)
