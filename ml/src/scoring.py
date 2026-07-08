"""
검색 결과 유사도 배열을 사용자용 4단계 등급으로 변환하는 모듈.

이 모듈은 비즈니스 로직 계층(Layer 2)에 속하며, FastAPI 등 상위 계층과
독립적으로 import/테스트할 수 있도록 순수 계산만 수행합니다.
torch/faiss에 의존하지 않으며, numpy + 표준 라이브러리만 사용합니다.

입력:
    search.search() 결과의 distances (np.ndarray, shape (k,), float32).
    값이 클수록 유사 (IP 기반). 일반적으로 내림차순 정렬되어 있음.

출력:
    등급 코드/이름/사용자 메시지 + 격차 2종 + 경고 목록을 담은 dict.

자세한 인터페이스는 score_results() docstring 참조.
"""

import numpy as np


# === 등급 판정 경계값 ===
# 절대 유사도 안전장치: top1이 이 값 이상이면 격차 조건과 무관하게 CAUTION.
# 배경: 완전 동일 로고(top1=1.0)가 격차 조건(gap_a < GAP_CAUTION)에 걸려
# REVIEW 이하로 강등되는 등급 역전 실측(2026-07-07, 로드맵 §5).
# TODO.pdf E의 "단독 임계값 안전장치"를 외관 축에 선행 도입한 것.
# 임시값 - 정답 데이터 확보 후 F(등급 재보정)에서 축별 수치 재조정 예정
SIM_IDENTICAL = 0.95

# 임시값 - Phase 1 시연 데이터 9장에서 역산. 데이터 확보 후 튜닝 예정
SIM_CAUTION = 0.75

# 임시값 - Phase 1 시연 데이터 9장에서 역산. 데이터 확보 후 튜닝 예정
SIM_REVIEW = 0.55

# 임시값 - Phase 1 시연 데이터 9장에서 역산. 데이터 확보 후 튜닝 예정
SIM_LOW = 0.45

# 임시값 - Phase 1 시연 데이터 9장에서 역산. 데이터 확보 후 튜닝 예정
GAP_CAUTION = 0.15

# 임시값 - Phase 1 시연 데이터 9장에서 역산. 데이터 확보 후 튜닝 예정
GAP_REVIEW = 0.04


# === 비정상 입력 감지용 범위 ===
# IP 기반 코사인 유사도는 이론상 [-1, 1]. 약간의 float 오차 허용.
SIM_MAX_VALID = 1.01
SIM_MIN_VALID = -1.01


# === 등급 정의 (이름, 코드, 메시지를 한 곳에 묶음) ===
GRADE_CAUTION = {
    "grade_name": "주의 필요",
    "grade_code": "CAUTION",
    "message": (
        "명확히 닮은 선행상표가 있습니다. "
        "출원 전 전문가 상담을 강력히 권장합니다."
    ),
}

GRADE_REVIEW = {
    "grade_name": "검토 권장",
    "grade_code": "REVIEW",
    "message": (
        "닮았을 수 있는 선행상표가 있습니다. "
        "출원 전 확인을 권장합니다."
    ),
}

GRADE_LOW = {
    "grade_name": "특정 위협 없음",
    "grade_code": "LOW",
    "message": (
        "특별히 가까운 선행상표가 발견되지 않았습니다. "
        "본 결과는 참고용임을 유의하세요."
    ),
}

GRADE_SAFE = {
    "grade_name": "비교적 안전",
    "grade_code": "SAFE",
    "message": (
        "시각적으로 충돌하는 선행상표가 보이지 않습니다. "
        "본 결과는 참고용임을 유의하세요."
    ),
}


def score_results(distances: np.ndarray) -> dict:
    """
    검색 결과의 유사도 배열을 받아 등급과 격차 정보를 산출한다.

    반환 dict 구조:
    {
        "grade_name": str,        # "주의 필요" 등
        "grade_code": str,        # "CAUTION" 등
        "message": str,           # 사용자용 메시지 한 줄
        "top1_similarity": float, # top-1 유사도
        "separability_a": float,  # 격차 A (top1 - top2)
        "separability_b": float,  # 격차 B (top1 - mean)
        "warnings": list[str],    # 모호 케이스/비정상 입력 등 경고 목록
    }

    Args:
        distances: 1차원 numpy 배열. 값이 클수록 유사.
                   일반적으로 내림차순으로 정렬되어 있음.

    Raises:
        ValueError: distances가 비어 있는 경우.
    """
    warnings: list[str] = []

    # 1. 빈 입력 차단
    if distances.size == 0:
        raise ValueError("distances is empty; cannot score")

    # 2. 비정상 값 범위 검증 (이후 계산은 그대로 진행)
    sim_min = float(np.min(distances))
    sim_max = float(np.max(distances))
    if sim_min < SIM_MIN_VALID or sim_max > SIM_MAX_VALID:
        warnings.append(
            f"비정상 유사도 값 감지: min={sim_min:.4f}, max={sim_max:.4f}. "
            f"이론상 [-1, 1] 범위를 벗어남."
        )

    # 3. 정렬 상태 검증 (내림차순이 아니면 경고 + 내부 정렬)
    # np.diff > 0인 위치가 하나라도 있으면 내림차순 깨진 것
    if distances.size >= 2 and np.any(np.diff(distances) > 0):
        warnings.append(
            "입력이 내림차순 정렬되어 있지 않음. 내부적으로 정렬 후 처리함."
        )
        distances = np.sort(distances)[::-1]

    # 4. 핵심 통계량
    top1 = float(distances[0])

    if distances.size >= 2:
        top2 = float(distances[1])
        gap_a = top1 - top2
    else:
        # 결과가 1개뿐: 격차 계산 불가 → 0.0으로 채우고 경고
        gap_a = 0.0
        warnings.append(
            "결과가 1개뿐이라 격차를 계산할 수 없음. "
            "격차 A/B를 0.0으로 처리함."
        )

    mean_sim = float(np.mean(distances))
    gap_b = top1 - mean_sim

    # 5. 4단계 등급 판정 (if-elif 사다리, 위에서부터 검사)
    # 격차(gap) 조건은 절대 유사도가 매우 높은 경우를 강등시킬 수 있으므로,
    # SIM_IDENTICAL 이상은 격차와 무관하게 최상위 등급을 보장한다.
    if top1 >= SIM_IDENTICAL:
        grade = GRADE_CAUTION
    elif top1 >= SIM_CAUTION and gap_a >= GAP_CAUTION:
        grade = GRADE_CAUTION
    elif top1 >= SIM_REVIEW and gap_a >= GAP_REVIEW:
        grade = GRADE_REVIEW
    elif top1 >= SIM_LOW:
        grade = GRADE_LOW
    else:
        grade = GRADE_SAFE

    # 6. 모호 케이스 경고: 유사도는 높은데 격차가 작아 판정이 흔들리는 상황
    if top1 >= SIM_REVIEW and gap_a < GAP_REVIEW:
        warnings.append(
            "유사도는 높으나 경쟁 후보가 많아 판정이 모호함. "
            "전문가 확인 권장."
        )

    return {
        "grade_name": grade["grade_name"],
        "grade_code": grade["grade_code"],
        "message": grade["message"],
        "top1_similarity": top1,
        "separability_a": gap_a,
        "separability_b": gap_b,
        "warnings": warnings,
    }
