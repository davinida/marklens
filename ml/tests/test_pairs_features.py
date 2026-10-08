"""정답 데이터 특징 생성 테스트 — 가짜 임베더(MARKLENS_FAKE_ML)·작은 labels.csv 픽스처로 끝까지
돈다."""

from __future__ import annotations

import csv
import json

import pytest
from src.axes import x3_semantic as x3

from scripts import pairs_features as pf

LABEL_COLUMNS = [
    "심판번호", "종류", "상표A_명칭", "상표B_번호", "유사여부_확정", "판단축_확정", "상표유형_확정",
    "상표유형_추정", "메모", "llm_b_유사여부", "llm_b_판단축", "상대표장_명칭_본문",
    "상대표장_명칭_ocr", "상대표장_명칭_kipris", "goods_codes_this", "goods_codes_prior",
    "x4_goods",
]


def _label(**values) -> dict:
    row = {column: "" for column in LABEL_COLUMNS}
    row.update(values)
    return row


LABELS = [
    # 1: 번호 있는 선등록 — kipris 이름이 본문보다 우선, 유사군 양쪽 있음, 이미지 쌍 번호로 연결
    _label(
        심판번호="R1", 종류="무효", 상표A_명칭="스타벅스", 상표B_번호="111", 유사여부_확정="유사",
        판단축_확정="외관|호칭", 상표유형_확정="문자", 상표유형_추정="결합", llm_b_유사여부="유사",
        상대표장_명칭_본문="본문이름", 상대표장_명칭_kipris="스타박스",
        goods_codes_this="G1201;G1202", goods_codes_prior="G1201", x4_goods="0.5000",
    ),
    # 2: 확인대상표장 — 본문 이름, 판단축 비어 llm_b 로, 유형 추정, 상품만 비유사 → 표장라벨 ""
    _label(
        심판번호="R2", 종류="권리범위확인(적극적)", 상표A_명칭="커피 빈", 유사여부_확정="비유사",
        llm_b_유사여부="비유사", llm_b_판단축="상품", 상표유형_추정="문자",
        상대표장_명칭_본문="커피빈", 상대표장_명칭_ocr="ocr이름",
    ),
    # 3: pass a·b 불일치 → 대상 아님
    _label(
        심판번호="R3", 종류="거절결정불복", 상표A_명칭="A", 상표B_번호="333",
        유사여부_확정="유사", llm_b_유사여부="비유사",
    ),
    # 4: 이름 B 없음(조회 결과 상표명 빈 도형) → 이름 축 결측, 이미지 쌍은 사건에 하나뿐이라 연결
    _label(
        심판번호="R4", 종류="거절결정불복", 상표A_명칭="XSR", 상표B_번호="444",
        유사여부_확정="비유사", 판단축_확정="외관|호칭|관념", 상표유형_확정="도형",
        llm_b_유사여부="비유사",
    ),
    # 5: ocr 이름만, 메모 '표장 유사'(상품 비유사로 끝난 건) → 표장라벨 유사, 조어라 has_meaning
    #    False
    _label(
        심판번호="R5", 종류="권리범위확인(소극적)", 상표A_명칭="Zyqrt", 유사여부_확정="비유사",
        판단축_확정="상품", llm_b_유사여부="비유사", 메모="표장 유사·상품 비유사",
        상대표장_명칭_ocr="ZYQRT",
    ),
    # 6: 제외 라벨 → 대상 아님
    _label(심판번호="R6", 종류="무효", 유사여부_확정="제외", llm_b_유사여부="제외"),
]
IMAGE_PAIRS = [
    {"심판번호": "R1", "상대번호": "111", "x2_whole": "0.8000", "x2_fig": "0.7000"},
    {"심판번호": "R1", "상대번호": "112", "x2_whole": "0.1000", "x2_fig": ""},
    {"심판번호": "R4", "상대번호": "", "x2_whole": "0.3000", "x2_fig": ""},
]


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch):
    monkeypatch.setenv(x3.ENV_FAKE, "1")
    x3._reset_embedder()
    yield
    x3._reset_embedder()


@pytest.fixture
def paths(tmp_path):
    labels = tmp_path / "labels.csv"
    with labels.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_COLUMNS)
        writer.writeheader()
        writer.writerows(LABELS)
    pairs = tmp_path / "image_pairs_v1.csv"
    with pairs.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["심판번호", "상대번호", "x2_whole", "x2_fig"])
        writer.writeheader()
        writer.writerows(IMAGE_PAIRS)
    return labels, pairs, tmp_path / "pairs_features.csv"


def test_target_rows_and_name_priority():
    rows = pf.target_rows(LABELS)
    assert [r["심판번호"] for r in rows] == ["R1", "R2", "R4", "R5"]
    assert pf.name_b(LABELS[0]) == ("스타박스", "kipris")
    assert pf.name_b(LABELS[1]) == ("커피빈", "본문")
    assert pf.name_b(LABELS[4]) == ("ZYQRT", "ocr")
    assert pf.name_b(LABELS[3]) == ("", "")
    assert pf.judging_axes(LABELS[1]) == ("상품", "llm_b")
    assert pf.mark_type(LABELS[0]) == ("문자", "확정")
    assert pf.mark_type(LABELS[1]) == ("문자", "추정")


def test_build_features_scores_flags_and_image_join():
    features = {f["심판번호"]: f for f in pf.build_features(LABELS, IMAGE_PAIRS)}
    assert set(features) == {"R1", "R2", "R4", "R5"}
    assert list(features["R1"]) == pf.COLUMNS
    r1 = features["R1"]
    assert r1["이름B"] == "스타박스" and r1["이름B_출처"] == "kipris" and r1["표장라벨"] == "유사"
    assert float(r1["x1"]) > 0.4 and float(r1["x2_text"]) >= 0.8
    assert r1["x4"] == "0.5000" and r1["has_goods"] == 1
    assert r1["x2_whole"] == "0.8000" and r1["x2_fig"] == "0.7000"  # 번호 111 쌍(112 아님)
    assert r1["has_image"] == 1 and r1["has_fig"] == 1
    assert r1["x3"] != "" and r1["x3_raw"] != ""
    r2 = features["R2"]
    assert r2["표장라벨"] == "" and r2["판단축_출처"] == "llm_b" and r2["상표유형_출처"] == "추정"
    assert r2["x2_text"] == "1.0000" and r2["x1"] == "1.0000"  # 커피 빈 / 커피빈
    assert r2["x4"] == "" and r2["has_goods"] == 0 and r2["has_image"] == 0
    r4 = features["R4"]
    assert r4["has_names"] == 0 and r4["x1"] == "" and r4["x2_text"] == "" and r4["x3"] == ""
    assert r4["x2_whole"] == "0.3000" and r4["has_fig"] == 0  # 사건에 쌍 하나 → 번호 없이 연결
    assert r4["has_spelling_a"] == 1 and r4["has_spelling_b"] == 0
    r5 = features["R5"]
    assert r5["표장라벨"] == "유사" and r5["이름B_출처"] == "ocr"
    assert r5["has_meaning_a"] == 0 and r5["x3"] == "0.0000" and r5["x3_raw"] == "1.0000"


def test_x3_raw_matches_gated_when_gate_is_on():
    gated, raw = pf.x3_scores("왕", "KING")
    assert raw is not None and gated == pytest.approx(raw)
    assert pf.x3_scores("Zyqrt", "Qwzx") == (0.0, pytest.approx(pf.x3_scores("Qwzx", "Zyqrt")[1]))
    assert pf.x3_scores("", "왕") == (0.0, None)


def test_run_writes_csv_and_report(paths):
    labels, pairs, out = paths
    report = pf.run(labels, pairs, out)
    rows = pf.read_csv(out)
    assert len(rows) == 4 and list(rows[0]) == pf.COLUMNS
    assert report["대상_행"] == 4
    assert report["이름B_출처"] == {"kipris": 1, "본문": 1, "ocr": 1, "(없음)": 1}
    assert report["축별_결측"] == {
        "x1": 1, "x2_text": 1, "x2_fig": 3, "x2_whole": 2, "x3": 1, "x3_raw": 1, "x4": 3
    }
    # 스타벅스(조어)·커피빈(붙여쓴 합성어 폴백 실패)·Zyqrt 가 has_meaning False → R1·R2·R5
    assert report["게이트_꺼짐"]["x3(has_meaning 한쪽 False)"] == 3
    assert report["표장라벨"] == {"유사": 2, "(없음)": 1, "비유사": 1}
    assert report["x3_모델"] == "fake"
    saved = json.loads(out.with_name("pairs_features_report.json").read_text(encoding="utf-8"))
    assert saved["대상_행"] == 4
