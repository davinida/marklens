"""X4 상품 견련성 축 — 두 상표의 지정상품 유사군 코드 집합이 얼마나 겹치는지(자카드 계수).

규약(공통-2): 입력은 유사군 코드 집합 2개, 출력은 0.0~1.0 float(높을수록 견련성이 큼).
순수 함수·대칭·결정적이며 예외를 던지지 않는다(문자열이 아닌 항목·빈 문자열은 무시).
표준 라이브러리만 사용한다. 상품명 → 유사군 코드 변환은 goods_map.load_goods_map().codes_for().

    goods_similarity({"G1201", "S120907", "S128302"}, {"G1201", "S120907", "G1202"})  # 0.5
    has_goods(set())  # False → X4 결측

근사치 한계 — 유사군 코드는 근사 기준이다 (작업가이드 프론트 §프론트-8 규약)
- 유사군 코드는 특허청 심사 실무가 "유사하다고 추정"하는 상품 묶음이지 법적 결론이 아니다.
  대법원은 유사군 코드를 참고 자료로만 본다(상품의 품질·형상·용도·생산 부문·판매 부문·수요자
  범위 등 거래 실정으로 판단). 따라서 같은 유사군이라도 비유사로 판단된 예, 다른 유사군이라도
  유사로 판단된 예가 모두 있고, 이 함수는 그 예외를 반영하지 못한다.
- 제35류 도소매업 유사군(S20xx)은 취급 상품의 유사군과 묶이지 않는다. "화장품"(G1201) 과
  "화장품 소매업"(S2012) 은 자카드 0 이지만 실무에서는 상품과 그 소매업의 견련성을 사안별로
  판단한다(도소매업 개별 판단). 변환표의 aliases 는 검색용이며 이 계산에 쓰지 않는다.
- 통합 모델(작업가이드 ML §통합모델 6)에서 X4 는 표장 유사도를 증폭·억제하는 조정자다. 표장이
  매우 유사한데 상품만 다른 경우 위험도를 0 으로 내리지 말고 "표장 유사·상품 상이" 참고 경고를
  낸다(저명상표 무임승차 가능성).
- 서비스 적용 전제: DB 1,100건 중 유사군 코드가 있는 레코드는 100건뿐(2026-09-21 실측)이라
  DB 전건 X4 계산은 유사군 백필 후에 가능하다(docs/MarkLens_X4_상품견련성_설계.md).
"""

from __future__ import annotations

from typing import Iterable


def _codes(values: Iterable[str] | str | None) -> frozenset[str]:
    """유사군 코드 집합 정리.

    문자열이 아닌 항목·빈 문자열은 버리고 공백을 제거해 대문자로 맞춘다(G1201 == g1201).
    """
    if values is None:
        return frozenset()
    if isinstance(values, str):
        values = [values]
    cleaned: set[str] = set()
    for value in values:
        if isinstance(value, str):
            code = value.strip().upper()
            if code:
                cleaned.add(code)
    return frozenset(cleaned)


def has_goods(codes: Iterable[str] | str | None) -> bool:
    """유사군 코드가 하나라도 있으면 True. False 면 X4 를 결측으로 두고 다른 축만으로 판단한다
    (X1 의 has_pronunciation 과 같은 역할)."""
    return bool(_codes(codes))


def goods_similarity(
    codes_a: Iterable[str] | str | None,
    codes_b: Iterable[str] | str | None,
) -> float:
    """두 유사군 코드 집합의 자카드 계수 = |교집합| ÷ |합집합|.

    둘 중 하나라도 비면 0.0 — 유사도 0 이 아니라 비교 불가의 뜻이므로 has_goods 로 먼저 거른다.
    """
    a = _codes(codes_a)
    b = _codes(codes_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
