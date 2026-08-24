import faiss
import numpy as np
import pytest
from src.search import EMBEDDING_DIM, build_index, load_index, save_index, search


def unit_vectors(count: int) -> np.ndarray:
    values = np.zeros((count, EMBEDDING_DIM), dtype=np.float32)
    for index in range(count):
        values[index, index] = 1.0
    return values


def test_build_and_search_round_trip(tmp_path):
    embeddings = unit_vectors(3)
    index = build_index(embeddings)
    path = tmp_path / "marks.faiss"
    save_index(index, path)

    distances, indices = search(load_index(path), embeddings[1], k=5)

    assert indices[0] == 1
    assert set(indices[1:].tolist()) == {0, 2}
    assert distances.tolist() == pytest.approx([1.0, 0.0, 0.0])


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        np.zeros((1, EMBEDDING_DIM - 1), dtype=np.float32),
        np.zeros((1, EMBEDDING_DIM), dtype=np.float32),
        np.full((1, EMBEDDING_DIM), np.nan, dtype=np.float32),
        np.full((1, EMBEDDING_DIM), np.inf, dtype=np.float32),
    ],
)
def test_build_rejects_invalid_vectors(bad):
    with pytest.raises(ValueError):
        build_index(bad)


def test_build_accepts_numeric_input_and_noncontiguous_rows():
    source = unit_vectors(4).astype(np.float64)
    noncontiguous = source[::2]

    assert not noncontiguous.flags["C_CONTIGUOUS"]
    assert build_index(noncontiguous).ntotal == 2


@pytest.mark.parametrize(
    "bad_query",
    [
        np.zeros(EMBEDDING_DIM, dtype=np.float32),
        np.zeros(EMBEDDING_DIM - 1, dtype=np.float32),
        np.zeros((2, EMBEDDING_DIM), dtype=np.float32),
        np.full(EMBEDDING_DIM, np.nan, dtype=np.float32),
        np.full(EMBEDDING_DIM, np.inf, dtype=np.float32),
    ],
)
def test_search_rejects_invalid_query(bad_query):
    with pytest.raises(ValueError):
        search(build_index(unit_vectors(2)), bad_query)


@pytest.mark.parametrize("k", [0, -1, 1.5, True, "2"])
def test_search_rejects_invalid_k(k):
    with pytest.raises(ValueError):
        search(build_index(unit_vectors(2)), unit_vectors(1)[0], k=k)


def test_search_rejects_wrong_metric_and_dimension():
    query = unit_vectors(1)[0]
    with pytest.raises(ValueError, match="metric"):
        search(faiss.IndexFlatL2(EMBEDDING_DIM), query)
    with pytest.raises(ValueError, match="dimension"):
        search(faiss.IndexFlatIP(4), query)


def test_load_rejects_empty_index(tmp_path):
    path = tmp_path / "empty.faiss"
    faiss.write_index(faiss.IndexFlatIP(EMBEDDING_DIM), str(path))

    with pytest.raises(ValueError, match="at least one"):
        load_index(path)


def test_load_missing_index(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_index(tmp_path / "missing.faiss")
