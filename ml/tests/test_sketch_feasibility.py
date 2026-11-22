"""손그림 입력 실현성(ml/scripts/sketch_feasibility.py) — 손그림 생성 결정성, 비엔나 분류표 해석과
범주 대응표 검사, 낙서 부분 내려받기 해석, 지표·판정, 설정 고정 검사. 네트워크·ml/data·CLIP 없이."""

from __future__ import annotations

import copy
import json

import cv2
import numpy as np
import pytest

from scripts import sketch_feasibility as sf

VCL_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<index>
 <category id="1" text="CELESTIAL BODIES">
  <division id="1" text="STARS, COMETS">
   <section id="1" aux="">Stars<note>Including <ref>1.1.2</ref> stars.</note></section>
   <section id="15">Comets, stars with tail</section>
   <section id="17">Compass cards (except <ref>17.5.21</ref>)</section>
   <auxiliaries><text>Auxiliary Sections of Division <ref>1.1</ref></text>
    <head>(associated with Principal Sections <ref>1.1.1</ref>, <ref>1.1.15</ref>)</head>
    <auxiliary id="2">One star</auxiliary>
    <auxiliary id="9">Stars with four points</auxiliary>
   </auxiliaries>
  </division>
  <division id="7" text="MOON">
   <section id="1">Full moon, several moons</section>
  </division>
 </category>
 <category id="3" text="ANIMALS">
  <division id="7" text="BIRDS, BATS">
   <section id="1">Eagles, falcons</section>
   <section id="23">Bats</section>
   <auxiliaries>
    <head>(associated with Principal Sections <ref>3.7.1</ref>)</head>
    <auxiliary id="24">Birds or bats stylized</auxiliary>
   </auxiliaries>
  </division>
 </category>
</index>
"""

STAR = {"범주": "star", "단위": "중분류", "중분류": "0101", "뺌": [], "근거": "t"}
BIRD = {"범주": "bird", "단위": "중분류", "중분류": "0307", "뺌": ["030723"], "근거": "t"}
BAT_EXCLUDED = {"bat": {"규칙": "M4", "사유": "t",
                        "남는_분류": {"단위": "구분", "구분": ["030723"]}}}
CATEGORIES = ["star", "bird", "bat", "moon", "cat"]
MARK_CODES = [frozenset(codes) for codes in (
    {"010102"}, {"010109", "260101"}, {"030701"}, {"030724"}, {"030723"}, {"010701"}, set())]


def _entries():
    return sf.parse_vcl(VCL_XML)


def test_parse_vcl_reads_divisions_sections_and_auxiliaries():
    entries = _entries()
    assert entries["0101"] == sf.VclEntry("0101", "중분류", "STARS, COMETS")
    assert entries["010101"].name == "Stars"  # <note> 는 이름이 아님
    assert entries["010117"].name == "Compass cards (except 17.5.21)"  # <ref> 글자는 넣는다
    assert entries["010109"].kind == "보조"
    assert entries["010109"].associated == ("010101", "010115")
    assert entries["030724"].associated == ("030701",)
    assert entries["010701"].kind == "주"
    assert sf.dotted("010117") == "1.1.17" and sf.dotted("2611") == "26.11"


def test_word_pattern_matches_whole_words_and_plurals():
    assert sf.word_pattern("knife").search("Knives, forks and spoons")
    assert sf.word_pattern("leaf").search("Stylized leaves")
    assert sf.word_pattern("fork").search("Sets consisting of knife(ves), fork(s)")
    assert sf.word_pattern("smiley face").search("Smiley faces")
    assert sf.word_pattern("butterfly").search("Butterflies")
    assert not sf.word_pattern("hand").search("Handprints or fingerprints")
    assert not sf.word_pattern("sun").search("Marguerites, sunflowers")
    assert sf.first_item("STARS, COMETS") == "STARS"
    assert sf.first_item("QUADRUPEDS (SERIES I (FELINES, CANINES, BEARS))") == "QUADRUPEDS"
    assert sf.first_item("MOON") == "MOON"


def test_class_member_uses_division_minus_or_listed_sections():
    assert sf.class_member({"030701"}, BIRD)
    assert sf.class_member({"030799"}, BIRD)  # 9판 표에 없는 코드도 앞 4자리로
    assert not sf.class_member({"030723"}, BIRD)
    assert sf.class_member({"030723", "030724"}, BIRD)
    sections = {"단위": "구분", "구분": ["110301", "110304"]}
    assert sf.class_member({"110304"}, sections)
    assert not sf.class_member({"110302", "1103"}, sections)


def test_check_mapping_counts_marks_and_reports_names():
    rows = sf.check_mapping(_entries(), CATEGORIES, MARK_CODES, mapping=(STAR, BIRD),
                            excluded=BAT_EXCLUDED, minimum=2)
    star, bird = rows
    assert star["DB_건수"] == 2 and bird["DB_건수"] == 2  # 030723(박쥐)만 가진 상표는 새가 아님
    assert star["기준_비율"] == pytest.approx(2 / len(MARK_CODES))
    assert bird["공식_이름"] == {"3.7": "BIRDS, BATS", "3.7.23": "Bats"}


@pytest.mark.parametrize(("mapping", "excluded", "minimum", "message"), [
    ((STAR, BIRD), {}, 2, "bat: M1 후보 2건 이상인데"),  # 느슨한 후보가 많은데 사유 없음
    ((STAR, BIRD), BAT_EXCLUDED, 3, "star: DB 2건 < 3"),
    (({"범주": "bat", "단위": "중분류", "중분류": "0307", "뺌": [], "근거": "t"},), BAT_EXCLUDED, 1,
     "첫 항목이 아님"),
    (({"범주": "star", "단위": "구분", "구분": ["010102"], "뺀_후보": {}, "근거": "t"},), {}, 1,
     "사유 없이 빠진 후보"),
    ((BIRD, {"범주": "bat", "단위": "구분", "구분": ["030723", "030724"], "뺀_후보": {},
             "근거": "t"}), {}, 1, "겹침"),
    (({"범주": "comet", "단위": "구분", "구분": ["010115"], "뺀_후보": {}, "근거": "t"},), {}, 9,
     "Quick, Draw! 범주 목록에 없음"),
])
def test_check_mapping_rejects_problems(mapping, excluded, minimum, message):
    with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)")):
        sf.check_mapping(_entries(), CATEGORIES, MARK_CODES, mapping=mapping, excluded=excluded,
                         minimum=minimum)


def test_real_mapping_table_is_well_formed():
    mapped = [spec["범주"] for spec in sf.MAPPING]
    assert len(mapped) == len(set(mapped))
    assert not set(mapped) & set(sf.EXCLUDED)
    for spec in sf.MAPPING:
        if spec["단위"] == "중분류":
            assert len(spec["중분류"]) == 4
            assert all(len(code) == 6 and code[:4] == spec["중분류"] for code in spec["뺌"])
        else:
            assert spec["구분"] and all(len(code) == 6 for code in spec["구분"])
            assert all(len(code) == 6 for code in spec["뺀_후보"])
            assert not set(spec["구분"]) & set(spec["뺀_후보"])
    for item in sf.EXCLUDED.values():
        assert item["규칙"] in {"M2", "M3", "M4"}
        assert item["남는_분류"]["단위"] in {"구분", "중분류"}


def _logo_rgb() -> np.ndarray:
    canvas = np.full((300, 400, 3), 255, dtype=np.uint8)
    star = np.array([[200, 40], [225, 120], [310, 120], [240, 170], [265, 250], [200, 200],
                     [135, 250], [160, 170], [90, 120], [175, 120]], dtype=np.int32)
    cv2.fillPoly(canvas, [star], (200, 30, 30))
    cv2.circle(canvas, (200, 150), 130, (20, 20, 160), 6)
    cv2.circle(canvas, (52, 30), 5, (0, 0, 0), -1)  # 작은 부분
    return canvas


def _ink_box(gray: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(gray < sf.RENDER["잉크_문턱"])
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def test_normalized_logo_crops_pads_and_masks():
    canvas, mask = sf.normalized_logo(_logo_rgb())
    assert canvas.shape == (512, 512, 3) and mask.shape == (512, 512)
    ys, xs = np.nonzero(mask)
    assert max(xs.max() - xs.min(), ys.max() - ys.min()) == pytest.approx(447, abs=3)
    assert sf.normalized_logo(np.full((80, 80, 3), 255, dtype=np.uint8)) is None


def test_sketch_generation_is_deterministic_per_target_and_level():
    _, mask = sf.normalized_logo(_logo_rgb())
    first = {level: sf.render(drawing) for level, drawing in sf.make_sketches(mask, "K1").items()}
    again = {level: sf.render(drawing) for level, drawing in sf.make_sketches(mask, "K1").items()}
    other = {level: sf.render(drawing) for level, drawing in sf.make_sketches(mask, "K2").items()}
    assert set(first) == {"L1", "L2", "L3"}
    for level in first:
        assert np.array_equal(first[level], again[level]), level
    assert np.array_equal(first["L1"], other["L1"])  # L1 은 난수 없음
    assert not np.array_equal(first["L2"], other["L2"])
    assert not np.array_equal(first["L3"], other["L3"])
    for gray in first.values():
        x0, y0, x1, y1 = _ink_box(gray)
        assert max(x1 - x0, y1 - y0) == pytest.approx(448, abs=3)  # 여백 자르기·정사각형 패딩


def test_rough_level_drops_twenty_to_thirty_percent_of_the_line():
    _, mask = sf.normalized_logo(_logo_rgb())
    for key in ("K1", "K2", "K3", "K4"):
        sketches = sf.make_sketches(mask, key)
        removed = sketches["L3"].info["누락_비율"]
        assert 0.20 <= removed <= 0.36, (key, removed)  # 마지막 구간 하나만큼 넘을 수 있다
        assert not any(sketches["L3"].closed)
        assert sketches["L2"].info["남은_윤곽"] >= 1


def test_dropout_and_resample_keep_geometry():
    square = np.array([[0, 0], [100, 0], [100, 100], [0, 100]], dtype=np.float64)
    dense = sf.resample(square, 4, True)
    assert sf.path_length(dense, True) == pytest.approx(400, rel=1e-6)
    pieces, removed = sf.dropout([dense], np.random.default_rng(0), (0.2, 0.3), (16, 40))
    kept = sum(sf.path_length(piece, False) for piece in pieces)
    assert 0.2 <= removed <= 0.4
    assert kept == pytest.approx(400 * (1 - removed), abs=8)


def test_doodle_render_fits_the_box_with_constant_line_width():
    strokes = [[[0, 100, 255], [0, 50, 0]], [[0, 255], [255, 255]], [[128], [128]]]
    gray = sf.render(sf.doodle_drawing(strokes))
    x0, y0, x1, y1 = _ink_box(gray)
    assert max(x1 - x0, y1 - y0) == pytest.approx(448, abs=3)
    assert (x0 + x1) / 2 == pytest.approx(256, abs=2) and (y0 + y1) / 2 == pytest.approx(256, abs=2)
    stats = sf.drawing_stats(gray)
    assert 4 <= stats["선_굵기_px"] <= 7
    assert 0 < stats["잉크"] < 0.1
    assert sf.render(sf.Drawing([], [], {})) is None


def test_contour_drawing_uses_edges_with_the_same_line_width():
    gray, how = sf.contour_drawing(_logo_rgb())
    assert how == "전경" and gray.shape == (512, 512)
    x0, y0, x1, y1 = _ink_box(gray)
    assert max(x1 - x0, y1 - y0) == pytest.approx(448, abs=3)
    assert 4 <= sf.drawing_stats(gray)["선_굵기_px"] <= 8
    blank, how = sf.contour_drawing(np.full((80, 80, 3), 255, dtype=np.uint8))
    assert blank is None and how == "전체"


def _ndjson(records) -> bytes:
    return ("".join(json.dumps(record) + "\n" for record in records)).encode("utf-8")


def test_parse_chunk_drops_partial_lines():
    records = [{"key_id": str(k), "word": "star", "recognized": k % 2 == 0,
                "drawing": [[[0, 10], [0, 10]]]} for k in range(1, 8)]
    data = _ndjson(records)
    size = len(data)
    start = data.index(b"\n") + 5  # 둘째 줄 가운데
    end = size - 10  # 마지막 줄 가운데
    got, bad = sf.parse_chunk(data[start:end + 1], start, end, size)
    assert [record["key_id"] for record in got] == ["3", "4", "5", "6"] and bad == 0
    whole, _ = sf.parse_chunk(data, 0, size - 1, size)
    assert len(whole) == 7
    assert sf.parse_chunk(b'{"a": 1}\nnot json\n{"b"', 0, 20, 99) == ([{"a": 1}], 1)


def test_pick_doodles_filters_dedupes_and_samples_with_seed():
    records = [{"key_id": str(k), "word": "star", "recognized": True} for k in (5, 1, 3, 9, 7)]
    records += [{"key_id": "3", "word": "star", "recognized": True},
                {"key_id": "11", "word": "star", "recognized": False},
                {"key_id": "13", "word": "moon", "recognized": True}]
    picked, pool = sf.pick_doodles(records, "star", count=3, seed=0)
    again, _ = sf.pick_doodles(list(reversed(records)), "star", count=3, seed=0)
    assert pool == 5
    assert [r["key_id"] for r in picked] == [r["key_id"] for r in again]
    assert {r["key_id"] for r in picked} <= {"1", "3", "5", "7", "9"}
    with pytest.raises(sf.FetchFailed):
        sf.pick_doodles(records, "star", count=6)


def test_plan_ranges_spread_over_the_file():
    assert sf.plan_ranges(100, 8, 64) == [(0, 99)]
    ranges = sf.plan_ranges(10_000, 8, 64)
    assert len(ranges) == 8 and ranges[0] == (0, 63) and ranges[-1] == (9936, 9999)
    assert all(end - start + 1 == 64 for start, end in ranges)
    assert [start for start, _ in ranges] == sorted(start for start, _ in ranges)


def test_metrics_and_bootstrap():
    indices = sf.bootstrap_indices(4, 200, 0)
    assert np.array_equal(indices, sf.bootstrap_indices(4, 200, 0))
    assert sf.mean_ci(np.ones(4), indices) == [1.0, 1.0]
    low, high = sf.mean_ci(np.array([0.0, 0.0, 1.0, 1.0]), indices)
    assert 0 <= low < 0.5 < high <= 1
    point, interval = sf.ratio_of_means(np.array([0.2, 0.4]), np.array([0.1, 0.1]),
                                        sf.bootstrap_indices(2, 200, 0))
    assert point == pytest.approx(3.0) and interval[0] <= 3.0 <= interval[1]
    assert sf.first_rank(["a", "b", "c"], {"c", "b"}) == 2
    assert sf.first_rank(["a"], {"z"}) is None


def _decision_inputs(level2_a=0.6, level2_b=0.6, multiple_a=2.5, multiple_b=2.5, low_a=1.2,
                     low_b=1.2):
    test1 = {method: {"L2": {"인정": {"5": {"비율": value}}}}
             for method, value in (("A", level2_a), ("B", level2_b))}
    test2 = {"A": {"배수": multiple_a, "배수_CI": [low_a, 3.0]},
             "B": {"배수": multiple_b, "배수_CI": [low_b, 3.0]}}
    return test1, test2


@pytest.mark.parametrize(("kwargs", "verdict", "method"), [
    ({}, "진행", "A"),  # 둘 다 통과·같으면 A
    ({"level2_b": 0.7}, "진행", "B"),  # 둘 다면 L2 가 높은 쪽
    ({"low_a": 1.0}, "진행", "B"),  # A 는 신뢰구간 하한이 기준선과 같아 탈락
    ({"multiple_a": 1.99, "level2_b": 0.49}, "보류", None),
    ({"level2_a": 0.5, "level2_b": 0.2}, "진행", "A"),  # 0.50 은 통과
])
def test_decision_rule_is_the_frozen_one(kwargs, verdict, method):
    result = sf.decide(*_decision_inputs(**kwargs))
    assert result["판정"] == verdict and result["고른_방법"] == method


def test_check_frozen_refuses_changed_or_tampered_settings():
    settings = {"시험1": {"대상": ["1", "2"]}, "손그림": {"L2": {"회전_도": 10}}}
    frozen = {"설정": copy.deepcopy(settings), "sha256": sf.settings_sha256(settings)}
    sf.check_frozen(frozen, settings)
    changed = copy.deepcopy(settings)
    changed["손그림"]["L2"]["회전_도"] = 15
    with pytest.raises(sf.Refused, match="손그림.L2.회전_도"):
        sf.check_frozen(frozen, changed)
    tampered = copy.deepcopy(frozen)
    tampered["설정"]["시험1"]["대상"].append("3")
    with pytest.raises(sf.Refused, match="해시"):
        sf.check_frozen(tampered, settings)


def _mark(appno, applicant="", name="", position=0, codes=()):
    return sf.Mark(appno, f"{appno}.png", applicant, frozenset(codes), name, position)


def test_targets_follow_the_type_dictionary_and_photo_flags():
    marks = [_mark("1", position=0), _mark("2", name="가나", position=1),
             _mark("3", position=2), _mark("4", position=3), _mark("5", name="다라", position=4)]
    types = {"1": {"type": "도형"}, "2": {"type": "결합"}, "3": {"type": "결합"},
             "4": {"type": "도형"}, "5": {"type": "문자"}}
    eligible, counts = sf.eligible_targets(marks, types, [False, False, False, True, False])
    assert eligible == ["1", "3"]  # 이름 없는 결합 = 결합-도형요부, 사진은 뺀다
    assert counts == {"결합-도형요부": 1, "결합-문자요부": 1, "도형": 1, "도형·사진": 1, "문자": 1}
    assert sorted(sf.order_targets(["3", "1"], size=200)) == ["1", "3"]
    assert sf.order_targets(["3", "1"], size=200) == sf.order_targets(["1", "3"], size=200)
    assert len(sf.order_targets(["1", "2", "3"], size=2)) == 2


def test_lenient_set_needs_same_applicant_and_high_similarity():
    marks = [_mark("1", "(주)가나|다라", position=0), _mark("2", "가나 주식회사", position=1),
             _mark("3", "마바", position=2), _mark("4", "가나", position=3)]
    vectors = np.array([[1.0, 0.0], [0.97, 0.2431], [0.99, 0.1411], [0.9, 0.4359]])
    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    assert sf.lenient_sets(["1"], marks, vectors) == {"1": ["2"]}  # 3 다른 출원인, 4 는 0.9
