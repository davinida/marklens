"""다축 위험도 모델의 축 함수 패키지 (공통-2 규약).

각 축은 외부 상태가 없는 순수 함수이며 0.0~1.0 float(높을수록 유사)를 반환한다.

- x1_phonetic: 호칭(발음) 유사도 — 상표명 문자열 2개 입력
- x3_semantic: 관념 유사도 (구현 예정)
- x4_goods:    상품 견련성 (구현 예정)

무거운 모듈(torch 등)을 이 패키지에서 자동 import 하지 않도록 재수출은 하지 않는다.
`from src.axes.x1_phonetic import phonetic_similarity` 처럼 축 모듈을 직접 import 한다.
"""
