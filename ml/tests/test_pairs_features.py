"""정답 데이터 특징 생성 테스트 — 가짜 임베더(MARKLENS_FAKE_ML)·작은 labels.csv 픽스처로 끝까지
돈다."""

from __future__ import annotations

import csv
import json

import numpy as np
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
    # 3: pass a·b 불일치 — 2026-10-11 부터 유사여부_확정 우선(대상). 이름 B 없음
    _label(
        심판번호="R3", 종류="거절결정불복", 상표A_명칭="A", 상표B_번호="333",
        유사여부_확정="유사", 판단축_확정="호칭", llm_b_유사여부="비유사",
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
    assert [r["심판번호"] for r in rows] == ["R1", "R2", "R3", "R4", "R5"]
    assert pf.target_rows([_label(유사여부_확정="제외", llm_b_유사여부="유사")]) == []
    assert pf.name_b(LABELS[0]) == ("스타박스", "kipris")
    assert pf.name_b(LABELS[1]) == ("커피빈", "본문")
    assert pf.name_b(LABELS[4]) == ("ZYQRT", "ocr")
    assert pf.name_b(LABELS[3]) == ("", "")
    assert pf.judging_axes(LABELS[1]) == ("상품", "llm_b")
    assert pf.mark_type(LABELS[0]) == ("문자", "확정")
    assert pf.mark_type(LABELS[1]) == ("문자", "추정")


def test_build_features_scores_flags_and_image_join():
    features = {f["심판번호"]: f for f in pf.build_features(LABELS, IMAGE_PAIRS)}
    assert set(features) == {"R1", "R2", "R3", "R4", "R5"}
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


def test_label_rounds_puts_augmented_items_in_last_round(tmp_path):
    """회차 = 라벨링 회차: 큐의 round, 보강 열이 찬 항목은 큐의 마지막 회차(1차 수집분이라도 2차
    라벨링). 큐에 없는 사건은 labels.csv 의 round, 둘 다 없으면 빈 값."""
    queue = [
        {"심판번호": "R1", "round": "1", "보강": ""},
        {"심판번호": "R2", "round": "1", "보강": "도형 추정"},
        {"심판번호": "R4", "round": "2", "보강": ""},
    ]
    rounds = pf.label_rounds(queue)
    assert rounds == {"R1": "1", "R2": "2", "R4": "2"}
    assert pf.label_rounds([]) == {}
    labels = [dict(row) for row in LABELS]
    labels[2]["round"] = "1"  # R3: 큐에 없음 → labels 의 round
    features = {f["심판번호"]: f for f in pf.build_features(labels, IMAGE_PAIRS, rounds=rounds)}
    assert {k: f["회차"] for k, f in features.items()} == {
        "R1": "1", "R2": "2", "R3": "1", "R4": "2", "R5": "",
    }
    labels_path = tmp_path / "labels.csv"
    with labels_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_COLUMNS)
        writer.writeheader()
        writer.writerows(LABELS)
    with (tmp_path / "curation_queue.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["심판번호", "round", "보강"])
        writer.writeheader()
        writer.writerows(queue)
    report = pf.run(labels_path, tmp_path / "none.csv", tmp_path / "pairs_features.csv")
    assert report["회차"] == {"(없음)": 2, "2": 2, "1": 1}  # run 은 labels 옆 큐를 읽는다


def test_x3_raw_matches_gated_when_gate_is_on():
    gated, raw = pf.x3_scores("왕", "KING")
    assert raw is not None and gated == pytest.approx(raw)
    assert pf.x3_scores("Zyqrt", "Qwzx") == (0.0, pytest.approx(pf.x3_scores("Qwzx", "Zyqrt")[1]))
    assert pf.x3_scores("", "왕") == (0.0, None)


def test_run_writes_csv_and_report(paths):
    labels, pairs, out = paths
    report = pf.run(labels, pairs, out)
    rows = pf.read_csv(out)
    assert len(rows) == 5 and list(rows[0]) == pf.COLUMNS
    assert report["대상_행"] == 5
    assert report["이름B_출처"] == {"kipris": 1, "본문": 1, "ocr": 1, "(없음)": 2}
    assert report["축별_결측"] == {
        "x1": 2, "x2_text": 2, "x2_fig": 4, "x2_whole": 3, "x3": 2, "x3_raw": 2, "x4": 4,
        "x1_d": 2, "x2_text_d": 2, "x3_d": 2,
        "x2_text_v2": 2, "x2_text_d_v2": 2,  # 철자 v2 열도 이름이 있는 행에만
    }
    # 스타벅스(조어)·커피빈(붙여쓴 합성어 폴백 실패)·Zyqrt 가 has_meaning False → R1·R2·R5
    assert report["게이트_꺼짐"]["x3(has_meaning 한쪽 False)"] == 3
    assert report["표장라벨"] == {"유사": 3, "(없음)": 1, "비유사": 1}
    assert report["x3_모델"] == "fake"
    saved = json.loads(out.with_name("pairs_features_report.json").read_text(encoding="utf-8"))
    assert saved["대상_행"] == 5


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


def test_easy_image_scores_fills_cross_and_db_pairs():
    """쉬운 음성 이미지 축(v1.3): cross 는 이름 A 쪽 this 이미지 × 이름 B 쪽 상대 이미지(같은
    이름이 둘이면 상대번호 순 첫 것), db 는 색인 벡터. 코사인(음수는 0)을 x2_whole 에,
    has_image 1."""
    features = [
        {"심판번호": "C1", "상대번호": "11", "이름A": "Alpha", "이름B": "Bravo"},
        {"심판번호": "C2", "상대번호": "", "이름A": "Charlie", "이름B": "Delta"},
        {"심판번호": "C2", "상대번호": "22", "이름A": "Charlie", "이름B": "Delta"},
        {"심판번호": "C3", "상대번호": "33", "이름A": "Echo", "이름B": "Foxtrot"},  # 이미지 쌍 없음
    ]
    image_rows = [
        {"심판번호": "C1", "상대번호": "11", "이미지A": "images/C1/this.png",
         "이미지B": "images/C1/prior_1.png"},
        {"심판번호": "C2", "상대번호": "", "이미지A": "images/C2/this.png",
         "이미지B": "images/C2/target.png"},
        {"심판번호": "C2", "상대번호": "22", "이미지A": "images/C2/this.png",
         "이미지B": "images/C2/prior_1.png"},
    ]
    db_records = [{"이미지파일": "a.png"}, {"이미지파일": "b.png"}, {"이미지파일": ""}]

    def easy(key, source, name_b):
        return {"심판번호": key, "pair_source": source, "이름A": "x", "이름B": name_b,
                "x2_whole": "", "has_image": 0}

    rows = [
        easy("cross:C1|C2", "cross", "Delta"),  # B 둘(target·prior_1) → 상대번호 "" 먼저 → target
        easy("cross:C3|C1", "cross", "Bravo"),  # A 이미지 없음
        easy("cross:C1|C3", "cross", "Foxtrot"),  # B 이미지 없음
        easy("db:0|1", "db", "y"),
        easy("db:1|2", "db", "z"),  # DB 이미지 없음
        easy("db:0|0", "db", "w"),  # 같은 이미지 → 코사인 1
    ]

    def unit(*values):
        vector = np.asarray(values, dtype=np.float32)
        return vector / np.linalg.norm(vector)

    trial = {"images/C1/this.png": unit(1, 0), "images/C2/target.png": unit(1, 1),
             "images/C2/prior_1.png": unit(0, 1)}
    db = {"a.png": unit(1, 0), "b.png": unit(-1, 0)}
    report = pf.easy_image_scores(
        rows, features, image_rows, db_records,
        trial_embeddings=lambda paths: {p: trial[p] for p in paths if p in trial},
        db_embeddings=lambda names: {n: db[n] for n in names if n in db},
    )
    assert rows[0]["x2_whole"] == "0.7071" and rows[0]["has_image"] == 1
    assert rows[1]["x2_whole"] == "" and rows[2]["x2_whole"] == ""
    assert rows[3]["x2_whole"] == "0.0000" and rows[3]["has_image"] == 1  # 코사인 −1 → 0
    assert rows[4]["x2_whole"] == "" and rows[4]["has_image"] == 0
    assert report["cross"] == 1 and report["db"] == 2 and rows[5]["x2_whole"] == "1.0000"
    assert report["없음"]["A 이미지 없음"] == 1 and report["없음"]["B 이미지 없음"] == 1
    assert report["없음"]["B 모호(상대번호 순 첫 이미지)"] == 1
    assert report["없음"]["DB 이미지 없음"] == 1 and report["없음"]["임베딩 없음"] == 0
    assert report["x2_whole_평균"] == {"cross": 0.7071, "db": 0.5}
    sides, reasons = pf.easy_image_sides(rows, features, image_rows, db_records)
    assert sides[0] == ("images/C1/this.png", "images/C2/target.png") and sides[1] is None
    assert sides[5] == ("a.png", "a.png") and reasons["DB 이미지 없음"] == 1


# ---- 통합 모델 v1.4 입력: 쌍 키·2등급 보강·사진 판정·쉬운 음성 다시 계산 ----------------------

def _photo_vectors() -> tuple[np.ndarray, np.ndarray]:
    """(사진 쪽, 그래픽 쪽) 임베딩 — 저장소의 방향 벡터와 같은 방향/반대 방향."""
    from src import photo_mark

    direction, _ = photo_mark.load_direction()
    unit = direction / np.linalg.norm(direction)
    return unit.astype(np.float32), (-unit).astype(np.float32)


def test_pair_key_matches_trials_collect_rule():
    """쌍 키는 dedupe(trials_collect.pair_key)와 같은 규칙 — 번호 우선, 상대 표장 명칭은 판정자가
    적은 명칭만. 교차검증에서 같은 표장 쌍이 걸친 사건을 한 묶음으로 묶는 데 쓴다."""
    from backend.scripts import trials_collect as tc

    rows = [
        _label(상표A_명칭="Star Bucks", 상표B_번호="4020200001234"),
        {**_label(상표A_명칭="Star Bucks", 상표B_번호="4020200001234"), "상표A_번호": "40-1"},
        _label(상표A_명칭="커피 빈!", 상대표장_명칭_llm="COFFEE-BEAN"),
        _label(상표A_명칭="커피 빈", 상대표장_명칭_본문="본문만"),  # 본문 명칭은 키가 아니다
        _label(상표A_명칭="", 상대표장_명칭_llm="이름"),
        _label(상표A_명칭="ＡＢＣ", 상대표장_명칭_llm="abc"),  # NFKC·소문자
    ]
    for row in rows:
        expected = tc.pair_key(row)
        assert pf.pair_key(row) == (pf.PAIR_KEY_SEPARATOR.join(expected) if expected else "")
    assert pf.pair_key(rows[0]) == "starbucks||번호:4020200001234"
    assert pf.pair_key(rows[1]) == "번호:40-1||번호:4020200001234"
    assert pf.pair_key(rows[3]) == "" and pf.pair_key(rows[4]) == ""
    assert pf.pair_key(rows[5]) == "abc||abc"


def test_build_features_fills_pair_key_augment_and_photo_flags():
    photo, graphic = _photo_vectors()
    image_rows = [
        {"심판번호": "R1", "상대번호": "111", "x2_whole": "0.8000", "x2_fig": "0.7000",
         "이미지A": "images/R1/this.png", "이미지B": "images/R1/prior_1.png"},
        {"심판번호": "R4", "상대번호": "", "x2_whole": "0.3000", "x2_fig": "",
         "이미지A": "images/R4/this.png", "이미지B": "images/R4/target.png"},
    ]
    vectors = {"images/R1/this.png": graphic, "images/R1/prior_1.png": photo,
               "images/R4/this.png": graphic}  # R4 의 상대 이미지는 임베딩 없음 → 판정 불가
    asked: list[list[str]] = []

    def embeddings(paths):
        asked.append(list(paths))
        return {path: vectors[path] for path in paths if path in vectors}

    features = {f["심판번호"]: f for f in pf.build_features(
        LABELS, image_rows, photo_embeddings=embeddings, augmented={"R4", "R9"})}
    assert asked == [sorted(["images/R1/this.png", "images/R1/prior_1.png",
                             "images/R4/this.png", "images/R4/target.png"])]
    r1, r2, r4 = features["R1"], features["R2"], features["R4"]
    assert (r1["사진A"], r1["사진B"]) == ("0", "1")
    assert (r4["사진A"], r4["사진B"]) == ("0", "")  # 임베딩이 없으면 빈 칸(사진으로 치지 않음)
    assert (r2["사진A"], r2["사진B"]) == ("", "") and r2["has_image"] == 0  # 이미지 축 없는 행
    assert r1["쌍키"] == "스타벅스||번호:111" and r2["쌍키"] == ""  # R2 는 판정자 명칭이 없다
    assert r4["보강"] == "1" and r1["보강"] == ""
    assert {"쌍키", "보강", "사진A", "사진B"} <= set(pf.COLUMNS)
    plain = pf.build_features(LABELS, image_rows)  # 임베딩을 주지 않으면 판정하지 않는다
    assert all(f["사진A"] == "" and f["사진B"] == "" and f["보강"] == "" for f in plain)
    summary = pf.summarize(list(features.values()))
    assert summary["사진"]["판정한_쌍"] == 1 and summary["사진"]["사진_낀_쌍"] == 1
    assert summary["사진"]["한쪽만_판정한_쌍"] == 1  # R4
    assert summary["보강"] == 1 and summary["쌍키_있음"] == 3  # R1·R3·R4(번호가 있는 행)
    assert pf.augmented_cases([{"심판번호": "A", "보강": "도형 추정"},
                               {"심판번호": "B", "보강": ""},
                               {"심판번호": "", "보강": "x"}]) == {"A"}


def test_read_db_records_keeps_original_sample_frame(tmp_path):
    """쉬운 음성 db 쌍의 색인은 표본을 뽑던 때의 DB("기존 수집") 기준 — 유명 브랜드가 더해진 뒤에도
    같은 색인이 같은 레코드를 가리킨다. 출처 필드가 없는 옛 메타는 전부."""
    path = tmp_path / "meta.json"
    records = [
        {"상표한글명": "알파", "수집_출처": "기존 수집"},
        {"상표한글명": "스타벅스", "수집_출처": "유명 브랜드"},
        {"상표한글명": "", "상표영문명": "", "수집_출처": "기존 수집"},  # 이름 없음
        {"상표영문명": "Beta", "수집_출처": "기존 수집"},
        {"상표한글명": "감마"},  # 출처 필드 없음(옛 메타)
    ]
    path.write_text(json.dumps({"trademarks": records}, ensure_ascii=False), encoding="utf-8")
    assert [pf._db_name(r) for r in pf.read_db_records(path)] == ["알파", "Beta", "감마"]
    assert [pf._db_name(r) for r in pf.read_db_records(path, source=None)] == [
        "알파", "스타벅스", "Beta", "감마"]
    assert [name for name, _goods in pf.read_db_names(path)] == ["알파", "Beta", "감마"]
    assert pf.read_db_records(tmp_path / "missing.json") == []


def test_refresh_easy_rows_recomputes_names_and_goods_but_keeps_pairs_and_images():
    model = _fake_model()
    label_rows = [
        _label(심판번호="E0", 종류="무효", 상표A_명칭="Zorbix", 상표B_번호="1",
               유사여부_확정="유사", 판단축_확정="호칭", 상대표장_명칭_kipris="Zorbik",
               goods_codes_this="G0301", goods_codes_prior="G0301;G0302"),
        _label(심판번호="E1", 종류="무효", 상표A_명칭="Qwzk", 상표B_번호="5",
               유사여부_확정="유사", 판단축_확정="호칭", 상대표장_명칭_kipris="Plumtaro",
               goods_codes_this="G0302", goods_codes_prior="G0301"),
        _label(심판번호="E1", 종류="무효", 상표A_명칭="Qwzk", 상표B_번호="6",
               유사여부_확정="유사", 판단축_확정="호칭", 상대표장_명칭_kipris="Plumtaro",
               goods_codes_this="G0302", goods_codes_prior="G0303"),  # 같은 이름의 상대 표장 둘
    ]
    features = pf.build_features(label_rows, [], model=model)
    db_records = [{"상표한글명": "알파로", "유사군": ["G0301"]},
                  {"상표영문명": "Betamix", "유사군": ["G0301", "G0302"]},
                  {"상표한글명": "감마텍", "유사군": []}]

    def stale(key, source, name_a, name_b, **values):
        row = {column: "" for column in pf.COLUMNS}
        row.update({"심판번호": key, "pair_source": source, "이름A": name_a, "이름B": name_b,
                    "최종라벨": "비유사", "표장라벨": "비유사", "이름B_출처": source,
                    "x1": "0.9999", "x2_text": "0.9999", "x1_d": "0.9999", "x4": "",
                    "has_goods": "0", "x2_whole": "0.4321", "has_image": "1", "사진A": "0",
                    "사진B": "1", "회차": ""})
        row.update(values)
        return row

    easy = [
        stale("cross:E0|E1", "cross", "Zorbix", "Plumtaro"),  # 후보 둘 — 상대번호 순 첫 것(5)
        stale("cross:E0|E1", "cross", "Zorbix", "Plumtaro", x4="0.0000", has_goods="1"),  # → 6
        stale("db:0|1", "db", "알파로", "Betamix"),  # 유사군이 생겼다 → x4 0.5
        stale("db:0|2", "db", "알파로", "감마텍"),  # 한쪽 유사군 없음 → x4 없음
        # 색인이 가리키는 레코드의 이름이 다르다 → 유사군 출처를 못 찾음
        stale("db:0|1", "db", "알파로", "다른이름", x4="0.7777", has_goods="1"),
        stale("cross:E9|E1", "cross", "없는사건", "Plumtaro", x4="0.1111", has_goods="1"),
    ]
    rows, report = pf.refresh_easy_rows(easy, features, label_rows, db_records, model=model)
    assert [(r["심판번호"], r["이름A"], r["이름B"], r["pair_source"]) for r in rows] == [
        (r["심판번호"], r["이름A"], r["이름B"], r["pair_source"]) for r in easy]  # 쌍 목록 그대로
    assert all(list(r) == pf.COLUMNS for r in rows)
    for row in rows:  # 이미지 축·사진 판정은 기존 값
        assert row["x2_whole"] == "0.4321" and str(row["has_image"]) == "1"
        assert (row["사진A"], row["사진B"]) == ("0", "1")
        assert row["x1"] != "0.9999" and float(row["x1"]) < 0.8  # 이름 축은 다시 계산
    assert rows[0]["x4"] == "1.0000" and rows[0]["has_goods"] == 1  # G0301 대 G0301
    assert rows[1]["x4"] == "0.0000"  # 기존 x4 를 그대로 내는 후보(G0303)를 고른다
    assert rows[2]["x4"] == "0.5000" and rows[2]["has_goods"] == 1
    assert rows[3]["x4"] == "" and rows[3]["has_goods"] == 0
    assert rows[4]["x4"] == "0.7777" and str(rows[4]["has_goods"]) == "1"  # 출처 못 찾음 → 기존 값
    assert rows[5]["x4"] == "0.1111"
    assert report["쌍"] == 6 and report["출처_못_찾음"] == {"cross": 1, "db": 1}
    assert report["유지한_열"] == ["x2_whole", "has_image", "회차"]
    assert report["바뀐_칸"]["x4"] == {"cross": 1, "db": 1, "합계": 2}
    assert report["바뀐_칸"]["x1"]["합계"] == 6 and "x2_whole" not in report["바뀐_칸"]
    assert report["바뀐_행"] == 6 and report["바뀐_칸_합계"] >= 8
    assert report["상품_축_있음"] == {"cross": 3, "db": 2}
    assert report["우연_유사_기준_초과"]["쌍"] == []


def test_easy_photo_flags_judges_only_rows_whose_image_pair_is_reproduced():
    photo, graphic = _photo_vectors()
    features = [{"심판번호": "C1", "상대번호": "11", "이름A": "Alpha", "이름B": "Bravo"},
                {"심판번호": "C2", "상대번호": "22", "이름A": "Charlie", "이름B": "Delta"}]
    image_rows = [
        {"심판번호": "C1", "상대번호": "11", "이미지A": "images/C1/this.png",
         "이미지B": "images/C1/prior_1.png"},
        {"심판번호": "C2", "상대번호": "22", "이미지A": "images/C2/this.png",
         "이미지B": "images/C2/prior_1.png"},
    ]
    db_records = [{"이미지파일": "a.png"}, {"이미지파일": "b.png"}]
    trial = {"images/C1/this.png": graphic, "images/C2/prior_1.png": photo,
             "images/C2/this.png": graphic, "images/C1/prior_1.png": graphic}
    db = {"a.png": graphic, "b.png": graphic}

    def easy(key, source, name_b, x2_whole):
        return {"심판번호": key, "pair_source": source, "이름A": "x", "이름B": name_b,
                "x2_whole": x2_whole, "has_image": 1 if x2_whole else 0, "사진A": "9",
                "사진B": "9"}

    rows = [
        easy("cross:C1|C2", "cross", "Delta", "0.0000"),  # 그래픽 × 사진(코사인 −1 → 0)
        easy("cross:C2|C1", "cross", "Bravo", "1.0000"),  # 그래픽 × 그래픽
        easy("db:0|1", "db", "y", "1.0000"),
        easy("db:0|1", "db", "y", "0.2500"),  # 저장된 값과 다시 계산한 값이 다름 → 판정하지 않음
        easy("db:0|1", "db", "y", ""),  # 이미지 축 없음
    ]
    report = pf.easy_photo_flags(
        rows, features, image_rows, db_records,
        trial_embeddings=lambda paths: {p: trial[p] for p in paths if p in trial},
        db_embeddings=lambda names: {n: db[n] for n in names if n in db})
    assert [(r["사진A"], r["사진B"]) for r in rows] == [
        ("0", "1"), ("0", "0"), ("0", "0"), ("", ""), ("", "")]
    assert report == {"판정한_쌍": 3, "사진_낀_쌍": 1, "이미지_식별_불일치": 1, "이미지_축_있음": 4}
