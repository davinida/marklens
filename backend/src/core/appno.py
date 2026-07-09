"""
출원번호 정규화 공용 모듈.

KIPRIS 원천에 따라 출원번호가 "40-2021-0126877" / "4020210126877" 처럼
포맷이 섞여 들어온다. 이 번호는 파이프라인 전체의 조인 키(파일명, DB PK,
메타 매칭)이므로, 저장·비교 전에 반드시 이 모듈로 통일한다.

2026-07-07 검증에서 확인된 리스크: extract_kipris_images.py 가
pdf 파일명(stem)과 메타의 출원번호를 그대로 교집합해 — 포맷이 다르면
이미지 0건 추출을 조용히 통과한다. 모든 신규 코드는 이 모듈을 쓸 것.
"""

import re

# 상표(40)/서비스표(41)로 시작하는 출원번호만 상표 데이터로 취급한다.
# (심판사항 API 검색 결과에 특허가 섞여 들어오는 것이 실측 확인됨 — TODO.pdf)
#
# ⚠ 2026-07-09 실측: 이 화이트리스트는 공보 검색(getAdvancedSearch)에서 **정상 상표를 버린다.**
#   출원인 "삼성전자"의 등록 도형상표 500건 표본의 출원번호 접두 분포와 등록번호 접두:
#     40 → 374건 (등록번호 40)   41 → 69건 (등록번호 41)   45 → 15건 (등록번호 45)
#     50 → 18건 (등록번호 **40**)  51 → 12건 (등록번호 **41**)
#     56 → 10건 (등록번호 **40**)  70 →  2건 (등록번호 **40**)
#   즉 50/51/56/70 은 특허가 아니라 **상표·서비스표로 등록된 권리**다(등록번호가 40/41).
#   현행 정책은 그 표본의 8.4%(42/500)를 근거 없이 버린다.
#   화이트리스트를 넓힐지는 팀 결정 대기 중이므로 동작은 그대로 둔다 — 바꾸려면 이 상수만
#   고치면 된다. (근거: docs/MarkLens_백엔드6_데이터확장_수집기준_초안.md)
TRADEMARK_PREFIXES: tuple[str, ...] = ("40", "41")

# 상표가 명백히 아닌 권리(특허 10 / 실용신안 20 / 디자인 30). 화이트리스트를 넓힐 때
# 대신 쓸 블랙리스트 후보 — 원래 필터의 목적("심판 API에 섞인 특허 배제")을 그대로 달성한다.
NON_TRADEMARK_PREFIXES: tuple[str, ...] = ("10", "20", "30")

# 한국 상표 출원번호는 숫자 13자리 (예: 4020210126877).
APPLICATION_NO_LENGTH: int = 13


def normalize_application_number(raw: str) -> str:
    """
    출원번호 문자열에서 숫자만 남겨 표준형으로 만든다.

    "40-2021-0126877" → "4020210126877"

    Args:
        raw: 원천 출원번호 문자열 (하이픈/공백 포함 가능).

    Returns:
        숫자만 남긴 출원번호 문자열.

    Raises:
        ValueError: 숫자가 하나도 없는 입력.
    """
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        raise ValueError(f"출원번호로 해석할 수 없는 값: {raw!r}")
    return digits


def is_trademark_application_number(raw: str) -> bool:
    """
    상표/서비스표 출원번호(40/41 시작, 13자리)인지 검사한다.

    심판·검색 API 응답에서 특허(10 시작 등)를 걸러낼 때 사용.
    길이가 다르면 형식 오류로 보고 False.
    """
    try:
        digits = normalize_application_number(raw)
    except ValueError:
        return False
    return (
        len(digits) == APPLICATION_NO_LENGTH
        and digits.startswith(TRADEMARK_PREFIXES)
    )
