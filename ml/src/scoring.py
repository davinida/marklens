"""Convert visual-search similarities into a monotonic assessment.

The assessment status depends only on the strongest similarity. Candidate
separation is reported as uncertainty metadata; it never lowers the status.
This keeps the result stable when callers request a different display ``top_k``.
"""

from __future__ import annotations

from typing import Final

import numpy as np

# Temporary thresholds. They must be recalibrated on a versioned, labelled set.
SIM_CAUTION: Final = 0.75
SIM_REVIEW: Final = 0.55
SIM_LOW: Final = 0.45

# Separation thresholds describe ambiguity, not legal or visual risk.
GAP_REVIEW: Final = 0.04

SIM_MAX_VALID: Final = 1.01
SIM_MIN_VALID: Final = -1.01


STATUS_STRONG_MATCH: Final = {
    "status_code": "STRONG_MATCH",
    "status_name": "매우 가까운 시각 후보",
    "grade_code": "CAUTION",
    "grade_name": "주의 필요",
    "message": (
        "매우 가까운 시각 후보가 있습니다. 이 결과만으로 등록 가능 여부를 "
        "판단할 수 없으므로 선행상표와 지정상품을 함께 검토하세요."
    ),
}

STATUS_POSSIBLE_MATCH: Final = {
    "status_code": "POSSIBLE_MATCH",
    "status_name": "가까울 수 있는 시각 후보",
    "grade_code": "REVIEW",
    "grade_name": "검토 권장",
    "message": (
        "가까울 수 있는 시각 후보가 있습니다. 상표명과 지정상품을 포함한 추가 검토가 필요합니다."
    ),
}

STATUS_WEAK_MATCH: Final = {
    "status_code": "WEAK_MATCH",
    "status_name": "약한 시각 후보",
    "grade_code": "LOW",
    "grade_name": "가까운 후보 미확인",
    "message": (
        "현재 비교 데이터에서는 강한 시각 후보를 확인하지 못했습니다. "
        "이는 등록 가능 여부나 권리 충돌 여부에 대한 결론이 아닙니다."
    ),
}

STATUS_NO_CLOSE_MATCH: Final = {
    "status_code": "NO_CLOSE_MATCH",
    "status_name": "가까운 시각 후보 미확인",
    # Legacy API compatibility: deliberately do not emit the old SAFE code.
    "grade_code": "LOW",
    "grade_name": "가까운 후보 미확인",
    "message": (
        "현재 비교 데이터에서는 가까운 시각 후보를 확인하지 못했습니다. "
        "데이터 범위 밖의 권리가 없다는 뜻은 아닙니다."
    ),
}


def _validated_distances(distances: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Return a finite descending float64 copy and any normalization warnings."""
    values = np.asarray(distances, dtype=np.float64)
    if values.ndim != 1:
        raise ValueError(f"distances must be a 1-D array, got shape {values.shape}")
    if values.size == 0:
        raise ValueError("distances is empty; cannot score")
    if not np.all(np.isfinite(values)):
        raise ValueError("distances contains NaN or infinite values; refusing to score")

    sim_min = float(values.min())
    sim_max = float(values.max())
    if sim_min < SIM_MIN_VALID or sim_max > SIM_MAX_VALID:
        raise ValueError(
            "similarity is outside the normalized cosine range: "
            f"min={sim_min:.6f}, max={sim_max:.6f}"
        )

    warnings: list[str] = []
    if values.size >= 2 and np.any(np.diff(values) > 0):
        warnings.append(
            "입력이 내림차순 정렬되어 있지 않아 내부적으로 정렬했습니다."
        )
        values = np.sort(values)[::-1]
    else:
        values = values.copy()
    return values, warnings


def _status_for_similarity(top1: float) -> dict:
    """Map similarity to a status monotonically; higher never becomes weaker."""
    if top1 >= SIM_CAUTION:
        return STATUS_STRONG_MATCH
    if top1 >= SIM_REVIEW:
        return STATUS_POSSIBLE_MATCH
    if top1 >= SIM_LOW:
        return STATUS_WEAK_MATCH
    return STATUS_NO_CLOSE_MATCH


def score_results(distances: np.ndarray) -> dict:
    """Assess a descending vector of cosine similarities.

    ``status_code`` is the canonical contract. Legacy ``grade_*`` fields remain
    during migration, but ``SAFE`` is never emitted. Status is based only on the
    strongest result, making it independent of the caller's display ``top_k``.

    A small top-1/top-2 gap means multiple candidates are similarly plausible.
    It is exposed through ``uncertain`` and ``uncertainty_reasons`` instead of
    being used as a downgrade condition.
    """
    values, warnings = _validated_distances(distances)
    top1 = float(values[0])

    uncertainty_reasons: list[str] = []
    if values.size >= 2:
        top2 = float(values[1])
        gap_a = top1 - top2
    else:
        gap_a = 0.0
        uncertainty_reasons.append("INSUFFICIENT_CANDIDATES")
        warnings.append(
            "후보가 1개뿐이라 후보 간 격차를 계산할 수 없습니다."
        )

    mean_sim = float(values.mean())
    gap_b = top1 - mean_sim

    if values.size >= 2 and top1 >= SIM_REVIEW and gap_a < GAP_REVIEW:
        uncertainty_reasons.append("MULTIPLE_CLOSE_CANDIDATES")
        warnings.append(
            "비슷한 점수의 후보가 여러 개 있어 대표 후보 순위가 불확실합니다."
        )

    status = _status_for_similarity(top1)
    return {
        "status_code": status["status_code"],
        "status_name": status["status_name"],
        "grade_code": status["grade_code"],
        "grade_name": status["grade_name"],
        "message": status["message"],
        "top1_similarity": top1,
        "separability_a": gap_a,
        "separability_b": gap_b,
        "uncertain": bool(uncertainty_reasons),
        "uncertainty_reasons": uncertainty_reasons,
        "warnings": warnings,
        "scored_candidate_count": int(values.size),
        "threshold_version": "visual-v2-uncalibrated",
        # 판정에 실제 사용한 경계값. 프런트 색 구간·눈금은 이 값을 그대로 쓰므로
        # 재보정(threshold_version 교체) 시 이 파일만 고치면 표시가 함께 따라온다.
        "thresholds": {
            "strong_match": float(SIM_CAUTION),
            "possible_match": float(SIM_REVIEW),
            "weak_match": float(SIM_LOW),
        },
    }
