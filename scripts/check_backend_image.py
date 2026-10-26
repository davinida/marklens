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
    from src.axes.distinctiveness import load_distinctiveness
    from src.model.risk_model import load_model, risk_score

    for relative in (
        "model/risk_model_v1.json",
        "distinctiveness/token_stats.json",
        "distinctiveness/descriptive_terms.json",
        "distinctiveness/weak_token_overrides.json",
        "goods_map/goods_map.json.gz",
        "famous_brands.txt",
    ):
        path = root / "shared" / relative
        assert path.is_file() and path.stat().st_size > 0, f"Missing shared asset: {relative}"
    model = load_model()
    assert model["version"] == "risk_model_v1.3"
    assert 0 <= risk_score({}, model).prob <= 1
    distinct = load_distinctiveness()
    assert distinct.stats and distinct.goods_names and distinct.famous
    assert distinct.token_score("커피", {"G0301"}) == 0.0
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
