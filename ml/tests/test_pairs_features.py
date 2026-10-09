"""정답 데이터 특징 생성 테스트 — 가짜 임베더(MARKLENS_FAKE_ML)·작은 labels.csv 픽스처로 끝까지
돈다."""

from __future__ import annotations

import csv
import json

import pytest
from src.axes import x3_semantic as x3
from src.axes.distinctiveness import Distinctiveness, goods_index
from src.axes.goods_map import GoodsEntry, GoodsMap

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
        "x1": 1, "x2_text": 1, "x2_fig": 3, "x2_whole": 2, "x3": 1, "x3_raw": 1, "x4": 3,
        "x1_d": 1, "x2_text_d": 1, "x3_d": 1,
    }
    # 스타벅스(조어)·커피빈(붙여쓴 합성어 폴백 실패)·Zyqrt 가 has_meaning False → R1·R2·R5
    assert report["게이트_꺼짐"]["x3(has_meaning 한쪽 False)"] == 3
    assert report["표장라벨"] == {"유사": 2, "(없음)": 1, "비유사": 1}
    assert report["x3_모델"] == "fake"
    saved = json.loads(out.with_name("pairs_features_report.json").read_text(encoding="utf-8"))
    assert saved["대상_행"] == 4


# ---- 식별력 v0·LLM 명칭·쉬운 음성 ------------------------------------------------------------



def _fake_model() -> Distinctiveness:
    names, classes = goods_index(GoodsMap([GoodsEntry("커피", 30, ("G0301",))]))
    return Distinctiveness({"gate": (12, 30), "dream": (44, 48)}, famous={"스타벅스"},
                           goods_names=names, code_classes=classes)


def test_name_b_prefers_llm_over_body_and_respects_figure_memo():
    row = _label(상대표장_명칭_llm="큐파이어", 상대표장_명칭_본문="본문", 상대표장_명칭_ocr="ocr")
    assert pf.name_b(row) == ("큐파이어", "llm")
    row = _label(상대표장_명칭_kipris="K", 상대표장_명칭_llm="L")
    assert pf.name_b(row) == ("K", "kipris")
    figure = _label(상대표장_명칭_본문="㈜영명", 메모="애매: 축 명시 없음 · 도형")
    # LLM 이 도형만이라고 적은 행은 본문으로 내려가지 않는다
    assert pf.name_b(figure) == ("", "도형")
    assert pf.name_b(_label(상대표장_명칭_본문="본문", 메모="도형적")) == ("본문", "본문")


def test_distinctiveness_columns_and_whole_comparison_rule():
    model = _fake_model()
    rows = [
        _label(심판번호="D1", 종류="무효", 상표A_명칭="Zorbix Gate", 상표B_번호="1",
               유사여부_확정="비유사", 판단축_확정="외관|호칭", llm_b_유사여부="비유사",
               상대표장_명칭_kipris="Hello Gate"),
        _label(심판번호="D2", 종류="무효", 상표A_명칭="GATE", 상표B_번호="2",
               유사여부_확정="비유사", 판단축_확정="외관", llm_b_유사여부="비유사",
               상대표장_명칭_kipris="GATE"),
        # 상품 상대적: 커피 유사군이면 커피가 1호 → 약한 토큰, 화장품이면 둘 다 요부
        _label(심판번호="D3", 종류="무효", 상표A_명칭="Zorbix 커피", 상표B_번호="3",
               유사여부_확정="유사", 판단축_확정="호칭", llm_b_유사여부="유사",
               상대표장_명칭_kipris="Qwzk 커피", goods_codes_this="G0301",
               goods_codes_prior="G0301", x4_goods="1.0000"),
    ]
    features = {f["심판번호"]: f for f in pf.build_features(rows, [], model=model)}
    d1 = features["D1"]
    assert d1["x1"] == "1.0000" and float(d1["x1_d"]) < 0.5
    assert float(d1["x2_text_d"]) < 0.5
    assert d1["weak_a"] == "gate" and d1["weak_b"] == "gate"
    assert d1["has_distinctive_part_a"] == 1 and d1["has_distinctive_part_b"] == 1
    d2 = features["D2"]  # 양쪽 다 요부 없음 → 전체 대비, 값 변화 없음
    assert d2["has_distinctive_part_a"] == 0 and d2["x1_d"] == d2["x1"] == "1.0000"
    assert d2["x2_text_d"] == d2["x2_text"] and d2["x3_d"] == d2["x3"]
    d3 = features["D3"]
    assert d3["weak_a"] == "커피" and d3["x1"] == "1.0000" and float(d3["x1_d"]) < 0.6
    assert d3["pair_source"] == "trial" and list(d3) == pf.COLUMNS


def test_easy_negatives_are_deterministic_and_exclude_coincidental_similarity(tmp_path):
    model = _fake_model()
    rows = [
        _label(심판번호=f"E{i}", 종류="무효", 상표A_명칭=name_a, 상표B_번호=str(i),
               유사여부_확정="유사", 판단축_확정="호칭", llm_b_유사여부="유사",
               상대표장_명칭_kipris=name_b, goods_codes_this="G0301", goods_codes_prior="G0302")
        for i, (name_a, name_b) in enumerate([("Zorbix", "Zorbix"), ("Qwzk", "Qwzk"),
                                               ("Plumtaro", "Plumtaro"), ("Vexlin", "Vexlin")])
    ]
    features = pf.build_features(rows, [], model=model)
    db = [("Alpharo", frozenset({"G0301"})), ("Betamix", frozenset({"G0303"})),
          ("Zorbix", frozenset()), ("Gammatek", frozenset({"G0301"}))]
    easy, report = pf.easy_negatives(features, rows, db, model=model, seed=0, n_cross=6, n_db=4)
    again, _ = pf.easy_negatives(features, rows, db, model=model, seed=0, n_cross=6, n_db=4)
    assert [r["심판번호"] for r in easy] == [r["심판번호"] for r in again]  # seed 고정
    cross = [r for r in easy if r["pair_source"] == "cross"]
    db_rows = [r for r in easy if r["pair_source"] == "db"]
    assert len(cross) == 6 and len(db_rows) == 4 and report["cross"] == 6 and report["db"] == 4
    for row in easy:
        assert row["최종라벨"] == "비유사" and row["표장라벨"] == "비유사" and row["x2_whole"] == ""
        assert float(row["x1"]) < 0.8 and float(row["x2_text"]) < 0.8
        assert row["x1_d"] != "" and list(row) == pf.COLUMNS
    assert all(r["심판번호"].split(":")[1].split("|")[0] != r["심판번호"].split("|")[1]
               for r in cross)  # 다른 사건끼리
    assert any(r["x4"] for r in cross) and any(r["x4"] == "" for r in db_rows)  # 유사군 있을 때만
    assert report["우연_유사_제외"]["cross"] >= 0 and report["제외_기준"].startswith("x1 또는")
    # 같은 이름끼리(Zorbix/Zorbix 교차)는 1.0 이라 제외되어 cross 에 없다
    assert all(not (r["이름A"] == "Zorbix" and r["이름B"] == "Zorbix") for r in cross)


def test_run_with_easy_negatives_writes_second_csv(paths, monkeypatch):
    labels, pairs, out = paths
    metadata = out.parent / "meta.json"
    metadata.write_text(json.dumps({"trademarks": [
        {"상표한글명": "알파로", "출원인": "a", "유사군": ["G0301"]},
        {"상표한글명": None, "상표영문명": "Betamix", "출원인": "b", "유사군": []},
        {"상표한글명": "감마텍", "출원인": "c", "유사군": ["G0302"]},
    ]}, ensure_ascii=False), encoding="utf-8")
    report = pf.run(labels, pairs, out, model=_fake_model(), easy=True, metadata_path=metadata)
    easy_rows = pf.read_csv(out.with_name("pairs_features_easy.csv"))
    assert report["쉬운_음성"]["db_이름"] == 3 and report["쉬운_음성"]["db"] == len(
        [r for r in easy_rows if r["pair_source"] == "db"]
    )
    assert report["식별력"]["theta"] == 0.5 and "식별력_적용으로_바뀐_쌍" in report
    assert all(r["pair_source"] in ("cross", "db") for r in easy_rows)
