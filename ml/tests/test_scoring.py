"""scoring.score_results 회귀 테스트.

핵심: 등급 역전 결함 고정 (2026-07-07 검증 세션 실측, 로드맵 §5).
완전 동일 로고(top1=1.0)가 격차 조건(gap_a < GAP_CAUTION) 때문에
REVIEW 이하로 강등되던 문제 — 절대 유사도 안전장치(SIM_IDENTICAL)가
격차와 무관하게 CAUTION을 보장해야 한다.
"""

import numpy as np
import pytest

from src.scoring import (
    GAP_CAUTION,
    SIM_IDENTICAL,
    score_results,
)


def _score(values):
    return score_results(np.asarray(values, dtype=np.float32))


# === 등급 역전 회귀 (필수 고정 케이스) ===


def test_identical_logo_small_gap_is_caution():
    """실측 재현: top1=1.0000, top2=0.8559 → gap_a=0.144 < 0.15.

    구버전은 REVIEW로 강등했음. 완전 동일 상표는 격차와 무관하게
    CAUTION이어야 한다.
    """
    result = _score([1.0, 0.8559, 0.52, 0.41, 0.33])
    assert result["grade_code"] == "CAUTION"


def test_identical_pair_in_db_is_caution():
    """DB에 동일 상표가 2건이면 gap_a=0.0 — 구버전은 LOW까지 추락했음."""
    result = _score([1.0, 1.0, 0.9, 0.3])
    assert result["grade_code"] == "CAUTION"


def test_guard_threshold_boundary():
    """SIM_IDENTICAL 경계값(float32 오차 감안) 이상에서 안전장치가 발동해야 한다."""
    result = _score([SIM_IDENTICAL + 1e-4, SIM_IDENTICAL - 0.01, 0.5])
    assert result["grade_code"] == "CAUTION"


def test_high_similarity_never_outranked_by_lower():
    """유사도가 더 높은 입력이 더 낮은 입력보다 약한 등급을 받으면 안 된다.

    실측 역전 쌍: (1.0, gap 작음) vs (0.835, gap 큼).
    """
    high = _score([1.0, 0.8559, 0.52])
    lower = _score([0.835, 0.60, 0.40])
    rank = {"SAFE": 0, "LOW": 1, "REVIEW": 2, "CAUTION": 3}
    assert rank[high["grade_code"]] >= rank[lower["grade_code"]]


# === 기존 사다리 동작 보존 (안전장치 미발동 구간) ===


def test_caution_band_with_clear_gap():
    result = _score([0.835, 0.60, 0.40])
    assert result["grade_code"] == "CAUTION"
    assert result["separability_a"] >= GAP_CAUTION


def test_review_band():
    result = _score([0.60, 0.50, 0.30])
    assert result["grade_code"] == "REVIEW"


def test_low_band_when_gaps_too_small():
    result = _score([0.50, 0.49, 0.48])
    assert result["grade_code"] == "LOW"


def test_safe_band():
    result = _score([0.30, 0.20])
    assert result["grade_code"] == "SAFE"


# === 입력 방어 동작 ===


def test_empty_input_raises():
    with pytest.raises(ValueError):
        _score([])


def test_single_result_warns_and_scores():
    result = _score([0.98])
    assert result["grade_code"] == "CAUTION"  # 안전장치는 격차 없이도 발동
    assert any("결과가 1개뿐" in w for w in result["warnings"])


def test_unsorted_input_warns_and_sorts():
    result = _score([0.5, 0.9, 0.3])
    assert result["top1_similarity"] == pytest.approx(0.9, abs=1e-6)
    assert any("내림차순" in w for w in result["warnings"])


def test_out_of_range_warns():
    result = _score([1.5, 0.2])
    assert any("비정상 유사도" in w for w in result["warnings"])
