"""도형 외관 세 방법 비교 테스트 — 합성 이미지·가짜 검출기·가짜 CLIP 으로(네트워크·실데이터
없음)."""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest
from PIL import Image, ImageDraw
from src.mark_type import TextBox

from scripts import x2_figure_methods as fm


def _mark(size=(120, 90), *, text=True, shape="circle", color=(200, 30, 30)) -> Image.Image:
    """흰 바탕에 도형 하나와(선택) 위쪽 검은 글자 막대."""
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    w, h = size
    box = (w // 4, h // 3, 3 * w // 4, h - 8)
    if shape == "circle":
        draw.ellipse(box, fill=color)
    else:
        draw.rectangle(box, fill=color)
    if text:
        draw.rectangle((10, 6, w - 10, 18), fill="black")
    return image


class FakeDetector:
    """위쪽 1/4 의 검은 픽셀 bbox 를 글자 박스 하나로(인식 글자는 'PET GARDEN')."""

    def detect(self, image):
        arr = np.asarray(image.convert("RGB"))
        top = arr[: arr.shape[0] // 4]
        ys, xs = np.nonzero(top.max(axis=2) < 60)
        if ys.size == 0:
            return []
        return [TextBox((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1),
                        "PET GARDEN", 0.9)]


def fake_encode(path):
    """8×8 색 축소를 펼친 뒤 512 차원으로 채우고 정규화 — 같은 그림이면 같은 벡터."""
    with Image.open(path) as image:
        small = np.asarray(image.convert("RGB").resize((8, 8)), dtype=np.float32).ravel()
    vector = np.zeros(512, dtype=np.float32)
    vector[: small.size] = small - small.mean()
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


# ---- 글자 지운 도형 ---------------------------------------------------------------------------


def test_name_matching_and_box_selection():
    boxes = [TextBox((0, 0, 10, 10), "PET", 0.9), TextBox((0, 0, 10, 10), "GARDEN", 0.8),
             TextBox((0, 0, 10, 10), "펫가든", 0.7), TextBox((0, 0, 10, 10), "@@", 0.02),
             TextBox((0, 0, 10, 10), "QXZ", 0.6)]
    name = "PET GARDEN 펫가든"
    assert fm.box_matches_name("Gardn", name)  # 느슨하게(유사도 ≥ 0.5)
    assert not fm.box_matches_name("QXZ", name) and not fm.box_matches_name("@@", name)
    assert [b.text for b in fm.select_boxes(boxes, "name", name)] == ["PET", "GARDEN", "펫가든"]
    assert fm.select_boxes(boxes, "all", name) == boxes  # 인식 결과를 쓰지 않는다
    assert fm.select_boxes(boxes, "name", None) == boxes  # 이름을 모르면 ①처럼 전부
    assert fm.select_boxes(boxes, "name", "") == []  # 없음으로 알려진 이름(도형 표장) — 안 지움
    assert fm.select_boxes(boxes, None, name) == []


def test_erase_boxes_inpaints_text_and_keeps_figure():
    image = _mark()
    box = FakeDetector().detect(image)[0]
    erased, ratio = fm.erase_boxes(image, [box])
    arr = np.asarray(erased)
    x0, y0, x1, y1 = box.bbox
    assert 0 < ratio < 0.2
    assert arr[y0:y1, x0:x1].mean() > 200  # 검은 막대가 주변(흰색)으로 채워졌다
    assert tuple(arr[60, 60]) == (200, 30, 30)  # 도형은 그대로
    same, zero = fm.erase_boxes(image, [])
    assert zero == 0.0 and np.array_equal(np.asarray(same), np.asarray(image))


def test_content_crop_and_logo_region():
    figure = fm.content_crop(_mark(text=False))
    assert figure is not None and figure.size[0] < 120 and figure.size[1] < 90
    assert fm.content_crop(Image.new("RGB", (100, 100), "white")) is None  # 내용 없음
    tiny = Image.new("RGB", (200, 200), "white")
    ImageDraw.Draw(tiny).rectangle((10, 10, 14, 14), fill="black")
    assert fm.content_crop(tiny) is None  # 너무 작다(< 32px)
    boxes = [TextBox((80, 80, 120, 100), "LOGO", 0.9)]
    region = fm.logo_region((300, 300), boxes)
    assert region == (60, 60, 140, 120)  # 긴 변 40 × 0.5 = 20 씩 넓힘
    assert fm.logo_region((300, 300), []) is None
    assert fm.logo_region((100, 100), [TextBox((0, 0, 100, 100), "X", 0.9)]) is None  # 거의 전체
    shifted = fm.shift_boxes(boxes + [TextBox((0, 0, 5, 5), "OUT", 0.9)], region)
    assert [b.bbox for b in shifted] == [(20, 20, 60, 40)]


def test_process_image_variants():
    image = _mark()
    boxes = FakeDetector().detect(image)
    unchanged = fm.process_image(image, boxes, name="", photo=False, erase="name", crop=False,
                                 photo_crop=True)
    assert unchanged.image is None and "지울 박스 없음" in unchanged.steps  # 도형 표장 — 그대로
    erased = fm.process_image(image, boxes, name="PET GARDEN", photo=False, erase="name",
                              crop=True, photo_crop=True)
    assert erased.image is not None and erased.steps[0].startswith("지움 1/1")
    assert "crop" in erased.steps and erased.image.size[1] < image.size[1]
    photo = fm.process_image(image, boxes, name=None, photo=True, erase=None, crop=False,
                             photo_crop=True)
    assert photo.steps == ["사진: 로고 영역"] and photo.image.size[0] <= image.size[0]
    text_only = Image.new("RGB", (120, 90), "white")
    ImageDraw.Draw(text_only).rectangle((10, 6, 110, 18), fill="black")
    blank = fm.process_image(text_only, FakeDetector().detect(text_only), name=None, photo=False,
                             erase="all", crop=False, photo_crop=False)
    assert blank.image is None and blank.steps == ["지우기 생략(남는 내용 없음)"]  # 문자 표장
    assert fm.is_blank(Image.new("RGB", (40, 40), "white")) and not fm.is_blank(image)


# ---- 비엔나코드 ----------------------------------------------------------------------------------


def test_codes_levels_and_jaccard():
    assert fm.parse_codes(["020901", "도안화된 산", "26011"]) == ["020901"]
    assert fm.parse_codes("261103|261107|") == ["261103", "261107"]
    assert fm.parse_codes(None) == []
    codes = ["020901", "260106", "260113", "270522"]
    assert fm.level_codes(codes, "major") == {"02", "26", "27"}
    assert fm.level_codes(codes, "mid") == {"0209", "2601", "2705"}
    assert fm.level_codes(codes, "mid", ("27", "29")) == {"0209", "2601"}
    assert fm.jaccard(frozenset({"a", "b"}), frozenset({"b", "c"})) == pytest.approx(1 / 3)
    assert fm.jaccard(frozenset(), frozenset({"a"})) == 0.0


def _vienna_index() -> fm.ViennaIndex:
    """두 무리: 0~4 는 벡터 e0 근처·코드 02xxxx, 5~9 는 e1 근처·코드 26xxxx. 출원인은 무리마다
    하나."""
    rng = np.random.default_rng(0)
    vectors, codes, applicants = [], [], []
    for i in range(10):
        base = np.zeros(8, dtype=np.float32)
        base[0 if i < 5 else 1] = 1.0
        vector = base + rng.normal(0, 0.05, 8).astype(np.float32)
        vectors.append(vector / np.linalg.norm(vector))
        codes.append(["020901", "020902"] if i < 5 else ["260106"])
        applicants.append("가" if i < 5 else "나")
    return fm.ViennaIndex(np.stack(vectors), codes, applicants)


def test_vienna_estimate_and_quality():
    index = _vienna_index()
    query = np.zeros(8, dtype=np.float32)
    query[1] = 1.0
    assert index.estimate(query, level="mid", k=5) == {"2601"}
    assert index.estimate(query, level="major", k=1) == {"26"}
    loo = fm.leave_one_out(index, level="mid", k=3)
    assert loo["n"] == 10 and loo["적중률"] == 1.0 and loo["자카드_평균"] == 1.0
    strict = fm.leave_one_out(index, level="mid", k=3, same_applicant=True)
    assert strict["적중률"] == 0.0  # 같은 출원인을 빼면 다른 무리만 남는다
    base = fm.prior_baseline(index, level="major")
    assert base["n"] == 10 and base["코드"] == ["02"] and base["적중률"] == 0.5
    quality = fm.estimate_quality([frozenset({"a"}), frozenset({"b"})],
                                  [frozenset({"a", "c"}), frozenset()])
    assert quality == {"n": 1, "자카드_평균": 0.5, "적중률": 1.0, "정밀도": 1.0, "재현율": 0.5,
                       "추정_코드수_평균": 1.0, "실제_코드수_평균": 2.0}


# ---- 평가 ----------------------------------------------------------------------------------------


def test_paired_diff_adoption_and_thresholds():
    rng = np.random.default_rng(1)
    labels = np.asarray([1, 0] * 30)
    groups = np.asarray([f"c{i // 2}" for i in range(60)])
    weights = np.ones(60)
    base = rng.random(60)
    same = fm.paired_diff(base, base.copy(), labels, groups, weights, rounds=50, seed=0)
    assert same["diff"] == 0.0 and same["ci95"] == [0.0, 0.0] and same["n"] == 60
    better = np.where(labels == 1, 0.9, 0.1) + rng.normal(0, 0.01, 60)
    up = fm.paired_diff(base, better, labels, groups, weights, rounds=50, seed=0)
    assert up["diff"] > 0.3 and up["ci95"][0] > 0 and up["ci95_w"][0] > 0
    assert fm.adoption(up, {"diff": 0.1}, {"diff": 0.2})["채택"]
    kept = fm.adoption(up, {"diff": 0.1}, {"diff": -0.05})
    assert not kept["채택"] and "2차" in kept["사유"]
    assert not fm.adoption(same, {"diff": 0.1}, {"diff": 0.1})["채택"]
    partial = np.where(np.arange(60) < 10, np.nan, base)
    assert fm.paired_diff(base, partial, labels, groups, weights, rounds=10, seed=0)["n"] == 50
    table = fm.threshold_table(np.asarray([0.95, 0.92, 0.5, 0.91]), np.asarray([1, 0, 1, 1]),
                               np.asarray([1.0, 0.5, 1.0, 1.0]), grid=(0.9,))
    assert table == [{"τ": 0.9, "지지_n": 3, "정밀도": 0.6667, "가중_정밀도": 0.8,
                      "재현율": 0.6667}]


# ---- 끝까지 -----------------------------------------------------------------------------------


def _write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_run_end_to_end_with_fakes(tmp_path):
    """도형계 12쌍(유사: 같은 도형, 비유사: 다른 도형) — 글자 막대는 유사·비유사에 고르게 섞어
    전체 이미지보다 글자 지운 도형이 라벨을 더 잘 가르게 만든다."""
    base = tmp_path / "trials"
    (base / "images").mkdir(parents=True)
    features, pairs, labels = [], [], []
    for i in range(12):
        similar = i % 2 == 0
        trial = f"T{i // 2}" if i < 8 else f"T{i}"
        a = _mark(text=i % 4 < 2, shape="circle")
        b = _mark(text=i % 3 == 0, shape="circle" if similar else "square",
                  color=(200, 30, 30) if similar else (30, 30, 200))
        rel_a, rel_b = f"images/{i}_a.png", f"images/{i}_b.png"
        a.save(base / rel_a)
        b.save(base / rel_b)
        features.append({
            "심판번호": trial, "상대번호": str(i), "상표유형": "도형" if i % 3 else "결합-도형요부",
            "has_image": "1", "표장라벨": "유사" if similar else "비유사",
            "회차": "1" if i < 6 else "2", "판단축": "외관", "이름A": "PET GARDEN" if i % 2 else "",
            "이름B": "", "이름B_출처": "도형" if i % 4 == 1 else "", "x2_whole": "", "x2_fig": "",
        })
        pairs.append({"심판번호": trial, "상대번호": str(i), "이미지A": rel_a, "이미지B": rel_b,
                      "this_사진추정": "0", "상대_사진추정": "1" if i == 3 else "0"})
        labels.append({"심판번호": trial, "상표B_번호": str(i),
                       "상대표장_번호_정규화": f"4000000{i:02d}0000"})
    for feature, pair in zip(features, pairs):  # x2_whole = 원본 가짜 임베딩의 코사인
        va, vb = fake_encode(base / pair["이미지A"]), fake_encode(base / pair["이미지B"])
        feature["x2_whole"] = f"{float(np.dot(va, vb)):.4f}"
    features.append({**features[0], "심판번호": "X", "상대번호": "99", "상표유형": "문자"})
    _write(base / "pairs_features.csv", features)
    _write(base / "image_pairs_v1.csv", pairs)
    _write(base / "labels.csv", labels)
    _write(base / "prior_marks.csv", [{"번호_정규화": "4000000000000", "결과": "ok", "Title": "",
                                       "ViennaCode": "010101|260106"}])
    db_vectors = np.stack([fake_encode(base / p["이미지B"]) for p in pairs])
    db = [{"file": f"{i}.png", "codes": ["260106"] if i % 2 == 0 else ["010101"],
           "applicant": f"A{i}", "name": "", "path": base / pairs[i]["이미지B"]}
          for i in range(12)]
    out = tmp_path / "out.json"
    result = fm.run(base, out_path=out, rounds=20, seed=0, with_easy=False,
                    detector=FakeDetector(), encode=fake_encode, db=db, db_matrix=db_vectors)
    assert result["표본"]["행"] == 12 and result["표본"]["회차"] == {"1": 6, "2": 6}
    assert result["비엔나_보유"]["도형계_표본"]["상대_실제"] == 1
    assert set(result["방법"]) == {"whole", "x2_fig_10월", *fm.FIGURE_VARIANTS,
                                  *fm.VIENNA_VARIANTS}
    assert result["방법"]["whole"]["전체"]["n"] == 12
    for name in ("fig_v2_crop", "vienna_mid_k5"):
        assert "짝_차이" in result["방법"][name] and "채택" in result["방법"][name]["판정"]
    assert result["채택_방법"] in ("whole", fm.PRIMARY_FIGURE, fm.PRIMARY_VIENNA)
    assert "사건 2025101001193 제외" in result["나눠_보기"]
    assert result["단독_규칙"]["whole"]["현재_τ"] == 0.9
    assert (base / "x2_figure_ocr.json").exists() and (base / "x2_cache_figure.npz").exists()
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["주_설정"]["글자_지운_도형"] == "fig_v2_crop"
    assert "## 방법별 AUC" in fm.report_text(result)
