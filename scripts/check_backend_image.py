"""Offline, non-root image smoke: real OCR weights and public canonical assets.

Run inside the built backend image with --network none. This does not start the
API, load a private trademark dataset, or initialize CLIP/sentence transformers.
"""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

import easyocr
import numpy as np
import torch
from easyocr.config import detection_models, recognition_models
from easyocr.utils import calculate_md5
from PIL import Image, ImageDraw, ImageFont


def check_shared_assets() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "ml"))
    from src import famous_runtime, name_words
    from src.axes import goods_map
    from src.axes.distinctiveness import load_distinctiveness
    from src.model.risk_model import famous_check_config, load_model, risk_score
    from src.photo_mark import load_direction

    for relative in (
        "model/risk_model_v1.json",
        "model/risk_model_v1.4.json",  # v1.4.1 의 원본(2026-11-20–22 서비스 기본)
        "model/risk_model_v1.4.1.json",  # v1.4.2 의 원본(2026-11-23 서비스 기본)
        "model/risk_model_v1.4.2.json",  # v1.4.3 의 원본(2026-11-23 서비스 기본 — logo_floor)
        "model/risk_model_v1.4.3.json",  # v1.4.5 의 원본(2026-11-23 서비스 기본 — weak_run 2)
        "model/risk_model_v1.4.5.json",  # v1.4.6 의 원본(2026-11-24 — 이미지+업종 곱하기 항)
        "model/risk_model_v1.4.6.json",  # v1.4.7 의 원본(2026-11-24 — 업종 상한 goods_cap)
        "model/risk_model_v1.4.7.json",  # 서비스 기본 모델(2026-11-26 — 유명 상표 확인 표시)
        "model/photo_direction_v1.json",  # 사진 질의 판정
        "distinctiveness/token_stats.json",
        "distinctiveness/descriptive_terms.json",
        "distinctiveness/weak_token_overrides.json",
        "goods_map/goods_map.json.gz",
        "famous_brands.txt",
    ):
        path = root / "shared" / relative
        assert path.is_file() and path.stat().st_size > 0, f"Missing shared asset: {relative}"
    # 유명 상표 확인이 런타임에 읽는 파일(ml/src/famous_runtime.RUNTIME_FILES) — 이미지에
    # 있어야 한다
    for relative in famous_runtime.RUNTIME_FILES:
        path = root / relative
        assert path.is_file() and path.stat().st_size > 0, (
            f"Missing famous-check file: {relative}")
    model = load_model()
    # 명시 값 — 기본 모델을 바꿀 때 이 검사도 의식적으로 같이 고치게 하는 가드
    assert model["version"] == "risk_model_v1.4.7", model["version"]
    # 유명 상표 확인 — 계수 JSON 의 표시가 켜져 있고 확정 파일의 해시를 가리킨다
    assert model["famous_check"]["enabled"] is True
    assert model["famous_check"]["confirmed_sha256"] == famous_runtime.file_sha256(
        famous_runtime.CONFIRMED_PATH)
    # 업종 상한 — 업종이 다르면 업종 없는 짝 판단의 등급 이하(엔진 규칙, 계수는 v1.4.5 그대로)
    assert model["goods_cap"]["enabled"] is True
    assert model["logo_floor"]["enabled"] is True  # 이름 있는 이미지 질의의 이미지만 판단 비교
    assert model["weak_run"]["version"] == 2  # 약한 토큰열은 두 이름 모두에서 붙어 있는 구간만
    # 이름 없는 이미지+업종 집합 — 로고 유사도 × 업종 겹침 곱하기 항, 업종이 안 겹치면 이미지만 이하
    goods = model["nameless_patterns"]["x2_whole+x4"]
    assert "x2_whole×x4" in goods["features"], goods["features"]
    assert goods["goods_rule"] == "no_raise_without_overlap"
    for x2 in (0.5, 1.0):
        figure = {"x2_whole": x2, "mark_type": "도형"}
        assert risk_score({**figure, "x4": 1.0}, model).pattern == "noname:x2_whole+x4"
        alone = risk_score(figure, model).prob
        assert risk_score({**figure, "x4": 0.0}, model).prob <= alone + 1e-9
    assert 0 <= risk_score({}, model).prob <= 1
    # 이름 없는 이미지 질의는 v1.4(= v1.4.1)의 이름 없는 계수 집합으로 채점된다
    assert risk_score({"x2_whole": 1.0, "mark_type": "도형"}, model).pattern == "noname:x2_whole"
    direction, _ = load_direction()
    assert direction.shape == (512,)
    distinct = load_distinctiveness()
    assert distinct.stats and distinct.goods_names and distinct.famous
    assert distinct.token_score("커피", {"G0301"}) == 0.0
    # 유명 상표 확인 — 서버 기동과 같은 적재(확정 파일·등록부·대표 로고 구분의 해시 대조, 업종 표)가
    # 이미지 안의 파일만으로 되고, 이름 판정이 돈다(로고는 DB 가 있어야 하므로 여기서는 보지 않는다)
    table = goods_map.load_goods_map()
    runtime = famous_runtime.load_runtime(
        famous_check_config(model), dist=distinct, goods_map=table,
        presets=goods_map.load_business_presets(table))
    assert runtime.brand_count > 0 and runtime.thresholds.weak_mode == "W2"
    strong = famous_runtime.check(runtime, name="스타벅스")
    assert strong.matches[0].brand == "스타벅스" and strong.floor == "위험", strong.matches
    assert famous_runtime.check(runtime, name="블루커피").matches == ()
    cafe = sorted({code for good in goods_map.load_business_presets(table).get("cafe").goods
                   for code in good.similarity_codes})
    assert famous_runtime.check(runtime, name="스타벅수", goods=cafe).classes_basis == (
        "업종 세트(cafe)")
    # 설명적 이름 안내(계약 v2 §2-7) — 낱말별 식별력을 응답 꼴로 옮기는 모듈이 이미지에 있고, 실제
    # 식별력 자산으로 카페 업종의 "맛있는 커피 전문점" 이 모두 설명하는 말로 나온다
    words = name_words.describe(distinct.judge_name("맛있는 커피 전문점", cafe))
    assert words.generic == name_words.GENERIC_ALL, words
    assert [word.category for word in words.words] == ["성질·품질", "상품 이름", "성질·품질"]
    print("Canonical risk/distinctiveness/goods/famous assets loaded", flush=True)


def check_offline_ocr() -> None:
    model_dir = Path(os.environ["EASYOCR_MODULE_PATH"])
    assert model_dir == Path("/models/easyocr"), "Unexpected OCR model directory"
    models = (
        detection_models["craft"],
        recognition_models["gen2"]["korean_g2"],
        recognition_models["gen2"]["english_g2"],
    )
    for model in models:
        path = model_dir / model["filename"]
        assert path.is_file(), f"Missing OCR weight: {path.name}"
        assert path.stat().st_uid == os.getuid(), (
            f"OCR weight not owned by runtime user: {path.name}"
        )
        assert calculate_md5(str(path)) == model["md5sum"], f"Bad OCR checksum: {path.name}"

    # Pillow's packaged font needs no extra system fonts or private image asset.
    image = Image.new("RGB", (720, 180), "white")
    ImageDraw.Draw(image).text(
        (30, 50), "MARKLENS 2026", fill="black", font=ImageFont.load_default(size=48)
    )
    pixels = np.asarray(image)
    torch.set_num_threads(2)
    for languages, recognizer in ((["ko", "en"], "korean_g2"), (["en"], "english_g2")):
        reader = easyocr.Reader(
            languages,
            gpu=False,
            detect_network="craft",
            recog_network=recognizer,
            model_storage_directory=str(model_dir),
            download_enabled=False,
            verbose=False,
        )
        assert reader.device == "cpu"
        result = reader.readtext(pixels, detail=1, workers=0, canvas_size=768)
        assert isinstance(result, list)
        # Recognition content is deliberately not a smoke-test accuracy gate.
        print(f"Offline {recognizer} readtext completed: {len(result)} regions", flush=True)
        del reader
        gc.collect()


def main() -> None:
    assert os.getuid() == 10001, "Image smoke must run as the non-root service user"
    assert not os.environ.get("MARKLENS_FAKE_ML"), "Smoke must use real OCR"
    check_shared_assets()
    check_offline_ocr()
    print("Backend image offline smoke passed", flush=True)


if __name__ == "__main__":
    main()
