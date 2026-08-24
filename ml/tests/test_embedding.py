import numpy as np
import pytest
import torch
from PIL import Image, ImageDraw
from src import embedding
from src.preprocess import GLOBAL_PREPROCESS_VERSION, LEGACY_PREPROCESS_VERSION


class FakeModel:
    def __init__(self, output_factory=None):
        self.output_factory = output_factory

    def encode_image(self, batch):
        if self.output_factory is not None:
            return self.output_factory(batch)
        output = torch.zeros((batch.shape[0], embedding.EMBEDDING_DIM))
        output[:, 0] = batch[:, 0].mean(dim=(1, 2)) + 1.0
        output[:, 1] = batch[:, 1].mean(dim=(1, 2)) + 1.0
        return output


def fake_preprocess(image):
    values = np.asarray(image, dtype=np.float32).copy() / 255.0
    return torch.from_numpy(values).permute(2, 0, 1)


def mark_image():
    image = Image.new("RGBA", (80, 40), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((10, 10, 70, 30), fill=(255, 255, 255, 255))
    return image


@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    monkeypatch.setattr(
        embedding,
        "_load_model",
        lambda: (FakeModel(), fake_preprocess),
    )


@pytest.mark.parametrize(
    "version",
    [LEGACY_PREPROCESS_VERSION, GLOBAL_PREPROCESS_VERSION],
)
def test_encode_image_returns_finite_unit_vector(version):
    result = embedding.encode_image(mark_image(), preprocess_version=version)

    assert result.shape == (embedding.EMBEDDING_DIM,)
    assert result.dtype == np.float32
    assert np.isfinite(result).all()
    assert np.linalg.norm(result) == pytest.approx(1.0, abs=1e-6)


def test_global_contract_aggregates_two_background_views(monkeypatch):
    seen = {}

    class RecordingModel(FakeModel):
        def encode_image(self, batch):
            seen["batch"] = batch.clone()
            output = torch.zeros((batch.shape[0], embedding.EMBEDDING_DIM))
            output[0, 0] = 1.0
            output[1, 1] = 1.0
            return output

    monkeypatch.setattr(
        embedding,
        "_load_model",
        lambda: (RecordingModel(), fake_preprocess),
    )
    result = embedding.encode_image(
        mark_image(),
        preprocess_version=GLOBAL_PREPROCESS_VERSION,
    )

    assert seen["batch"].shape[0] == 2
    assert result[:2].tolist() == pytest.approx([2**-0.5, 2**-0.5])


@pytest.mark.parametrize(
    "factory, message",
    [
        (lambda batch: torch.full((batch.shape[0], 512), float("nan")), "non-finite"),
        (lambda batch: torch.zeros((batch.shape[0], 512)), "zero-norm"),
        (lambda batch: torch.ones((batch.shape[0], 3)), "unexpected"),
    ],
)
def test_encode_image_rejects_invalid_model_output(monkeypatch, factory, message):
    monkeypatch.setattr(
        embedding,
        "_load_model",
        lambda: (FakeModel(factory), fake_preprocess),
    )

    with pytest.raises(ValueError, match=message):
        embedding.encode_image(mark_image())
