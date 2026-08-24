"""Regression and property tests for the monotonic visual assessment."""

import numpy as np
import pytest
from src.scoring import SIM_CAUTION, SIM_REVIEW, score_results

STATUS_RANK = {
    "NO_CLOSE_MATCH": 0,
    "WEAK_MATCH": 1,
    "POSSIBLE_MATCH": 2,
    "STRONG_MATCH": 3,
}


def _score(values):
    return score_results(np.asarray(values, dtype=np.float32))


def test_identical_logo_small_gap_remains_strong():
    result = _score([1.0, 0.8559, 0.52, 0.41, 0.33])
    assert result["status_code"] == "STRONG_MATCH"
    assert result["grade_code"] == "CAUTION"


def test_identical_pair_is_uncertain_but_not_downgraded():
    result = _score([1.0, 1.0, 0.9, 0.3])
    assert result["status_code"] == "STRONG_MATCH"
    assert result["uncertain"] is True
    assert "MULTIPLE_CLOSE_CANDIDATES" in result["uncertainty_reasons"]


@pytest.mark.parametrize(
    ("top1", "expected"),
    [
        (SIM_CAUTION, "STRONG_MATCH"),
        (SIM_REVIEW, "POSSIBLE_MATCH"),
        (0.50, "WEAK_MATCH"),
        (0.30, "NO_CLOSE_MATCH"),
    ],
)
def test_status_bands(top1, expected):
    assert _score([top1, 0.1])["status_code"] == expected


def test_display_top_k_does_not_change_status():
    short = _score([0.83])
    long = _score([0.83, 0.60, 0.40, 0.20])
    assert short["status_code"] == long["status_code"] == "STRONG_MATCH"


def test_small_gap_never_downgrades_high_similarity():
    high_crowded = _score([0.94, 0.94, 0.20])
    lower_isolated = _score([0.80, 0.60, 0.10])
    assert STATUS_RANK[high_crowded["status_code"]] >= STATUS_RANK[lower_isolated["status_code"]]


def test_status_is_monotonic_over_similarity_grid():
    previous = -1
    for top1 in np.linspace(-1.0, 1.0, 401):
        result = _score([top1, min(top1, 0.1)])
        rank = STATUS_RANK[result["status_code"]]
        assert rank >= previous
        previous = rank


@pytest.mark.parametrize("invalid", [[np.nan, 0.5], [np.inf], [-np.inf, 0.0]])
def test_non_finite_values_fail_closed(invalid):
    with pytest.raises(ValueError, match="NaN or infinite"):
        _score(invalid)


@pytest.mark.parametrize("invalid", [[1.5, 0.2], [-1.5]])
def test_out_of_range_values_fail_closed(invalid):
    with pytest.raises(ValueError, match="outside the normalized cosine range"):
        _score(invalid)


def test_empty_input_raises():
    with pytest.raises(ValueError, match="empty"):
        _score([])


def test_non_vector_input_raises():
    with pytest.raises(ValueError, match="1-D"):
        score_results(np.zeros((2, 2), dtype=np.float32))


def test_single_result_marks_uncertainty_without_downgrade():
    result = _score([0.80])
    assert result["status_code"] == "STRONG_MATCH"
    assert result["uncertainty_reasons"] == ["INSUFFICIENT_CANDIDATES"]


def test_unsorted_input_warns_and_sorts():
    result = _score([0.5, 0.9, 0.3])
    assert result["top1_similarity"] == pytest.approx(0.9, abs=1e-6)
    assert any("정렬" in warning for warning in result["warnings"])


def test_safe_legacy_code_is_never_emitted():
    assert _score([0.1, 0.0])["grade_code"] == "LOW"
    assert _score([0.1, 0.0])["status_code"] == "NO_CLOSE_MATCH"
