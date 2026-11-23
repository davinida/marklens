"""견고성 점검(2026-11-23, docs/MarkLens_견고성_보안_점검.md) — 오류는 아니지만 결과가 이상한 입력의
회귀 시험. 실제 식별력 모델(shared/distinctiveness)과 배포 계수 JSON 으로 쌍 하나를 채점한다
(CLIP·X3 없이 — 관념 축은 결측으로 둔다). 지금 고쳐지지 않은 항목은 strict xfail, 사유에 점검 문서의
항목 번호(R-P1-6·R-P0-2 는 2026-11-23 고쳐 통과 시험 — R-P0-2 는 v1.4.3 의 weak_run 규칙 2).
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest
from src.axes import pair_axes as pa
from src.axes.distinctiveness import Distinctiveness, load_distinctiveness
from src.model import risk_model as rm

CAFE = ["G0301", "G0502", "S120602"]  # 업종 세트 카페(커피전문점업·커피·커피 소매업)
# 4020170150241 "맛있는 만두 전문점 장수손만두 1976" 의 유사군(DB 메타 그대로)
DUMPLING_GOODS = ["G020102", "G0206", "G0301", "G0502", "S120602", "S120603"]
INVISIBLE = {
    "U+200B 폭 없는 공백": "​",
    "U+200C 폭 없는 비결합자": "‌",
    "U+200D 폭 없는 결합자": "‍",
    "U+2060 낱말 결합자": "⁠",
    "U+FEFF BOM": "﻿",
    "U+00AD 부드러운 붙임표": "­",
}


@pytest.fixture(scope="module")
def dist() -> Distinctiveness:
    return load_distinctiveness()


def _score(dist: Distinctiveness, query: str, candidate: str, goods_a=None, goods_b=None, *,
           risk: dict | None = None):
    """엔진처럼 계수 JSON 의 weak_run 버전으로 이름 축을 계산해 그 JSON 으로 채점(기본 = 서비스
    모델)."""
    risk = risk or rm.load_model()
    axes = pa.compute_pair_axes(query, candidate, model=dist, goods_a=goods_a, goods_b=goods_b,
                                x3_enabled=False, weak_run_version=rm.weak_run_version(risk))
    return axes, rm.risk_score(axes.model_features(x2_img=None, mark_type="문자"), risk)


def test_descriptive_only_name_is_not_rated_danger(dist):
    """R-P0-2(2026-11-23 고침, v1.4.3): 설명적 낱말만으로 된 이름이 떨어진 약한 낱말 둘(맛있는…
    전문점)을 요부로 보아 호칭 1.0·'위험'이던 것 — 약한 토큰열을 붙어 있는 구간만 묶으면 주의
    이하."""
    pair = ("맛있는 커피 전문점", "맛있는 만두 전문점 장수손만두 1976")
    axes, result = _score(dist, *pair, CAFE, DUMPLING_GOODS)
    assert axes.query_tokens == ()  # 전제: 질의에 요부가 없다(낱말이 모두 약함)
    assert result.grade in ("안전", "주의"), (axes.x1_raw, result.prob)
    # 고친 이유의 가드: 옛 규칙(v1.4.2 — weak_run 없음 = 규칙 1)으로는 지금도 호칭 1.0·'위험'
    old_axes, old = _score(dist, *pair, CAFE, DUMPLING_GOODS,
                           risk=rm.load_model(rm.V142_MODEL_PATH))
    assert old_axes.x1_raw == 1.0 and old.grade == "위험", (old_axes.x1_raw, old.prob)


def test_weak_run_v04_does_not_join_separated_descriptive_words(dist):
    """R-P0-2 원인: 실제 사전에서 맛있는·전문점 은 사이에 커피/만두가 끼어 결합이 아니다(식별력
    v0.4, 규칙 2). 옛 규칙(1 — 같은 순서 부분열)은 묶었다."""
    pair = ("맛있는 커피 전문점", "맛있는 만두 전문점 장수손만두 1976")
    assert dist.combined_weak_run(*pair, CAFE) == ()
    assert dist.combined_weak_run(*pair, CAFE, version=1) == ("맛있는", "전문점")


def test_descriptive_only_name_with_one_shared_weak_word_stays_low(dist):
    """가드 — 약한 낱말 하나만 겹치면(맛있는 커피) 지금도 호칭이 낮다."""
    axes, result = _score(dist, "맛있는 커피", "맛있는 만두 전문점 장수손만두 1976",
                          CAFE, DUMPLING_GOODS)
    assert axes.x1_raw < 0.5 and result.grade in ("안전", "주의")


def test_invisible_format_characters_do_not_change_the_judgment(dist):
    """R-P1-6(고침, 2026-11-23): clean_name 이 서식 문자(Cf)를 지워 원본과 같은 판단."""
    plain_axes, plain = _score(dist, "블루커피", "BLU hands")
    differ = {}
    for label, char in INVISIBLE.items():
        axes, result = _score(dist, f"블{char}루커피", "BLU hands")
        seen = (round(axes.x1_raw, 4), round(axes.x2_text_raw, 4), axes.query_tokens, result.grade)
        want = (round(plain_axes.x1_raw, 4), round(plain_axes.x2_text_raw, 4),
                plain_axes.query_tokens, plain.grade)
        if seen != want:
            differ[label] = seen
    assert not differ, differ


def test_clean_input_name_removes_format_characters_and_composes_nfc():
    """R-P1-6: API·엔진 공통 정리 — 서식 문자(Cf: 폭 없는 공백·BOM·부드러운 붙임표·양방향 제어 문자)
    제거, NFC, 앞뒤 공백. 호환 문자·대소문자는 그대로(상표명 확인은 원문 질의), 엔진의 clean_name 은
    그 뒤 NFKC."""
    import unicodedata

    for char in (*INVISIBLE.values(), "\u202e", "\u2066", "\u200e"):
        assert pa.clean_input_name(f" 블{char}루커피 ") == "블루커피"
    assert pa.clean_input_name(unicodedata.normalize("NFD", "블루커피")) == "블루커피"
    assert pa.clean_input_name("\u200b\ufeff") == ""
    assert pa.clean_input_name("ＳＴＡＲ Bucks") == "ＳＴＡＲ Bucks"  # 호환 문자는 그대로
    assert pa.clean_name("ＳＴＡＲ\u200b  Bucks") == "STAR Bucks"  # 엔진은 NFKC·공백 정리까지



SHARED_CASES = (Path(__file__).resolve().parents[2] / "shared" / "text"
                / "clean_input_name_cases.json")


def test_clean_input_name_matches_the_shared_cases():
    """B14·U3: 프런트 frontend/lib/markName.ts 의 cleanInputName 과 같은 공용 사례(Vitest
    markName.test.ts 도 같은 파일) — 결과가 같고, 사례 파일의 서식 문자·공백 집합이 지금 파이썬과
    같다(파이썬을 올려 유니코드 판이 바뀌면 이 시험이 알린다 — 사례 파일과 markName.ts 를 다시
    만든다)."""
    data = json.loads(SHARED_CASES.read_text(encoding="utf-8"))
    for case in data["cases"]:
        assert pa.clean_input_name(case["input"]) == case["expected"], case["note"]
    assert data["python_unicode_version"] == unicodedata.unidata_version
    assert data["format_code_points"] == [
        cp for cp in range(0x110000) if unicodedata.category(chr(cp)) == "Cf"]
    assert data["strip_code_points"] == [cp for cp in range(0x110000) if chr(cp).isspace()]

def test_case_width_and_spacing_variants_give_the_same_judgment(dist):
    """가드 — 대소문자·전각·앞뒤 공백·NFD 는 지금도 같은 판단(점검 2 의 같아야 하는 입력)."""
    import unicodedata

    base_axes, base = _score(dist, "STARBUCKS", "STARBUCKS COFFEE")
    for variant in ("starbucks", "ＳＴＡＲＢＵＣＫＳ", "  STARBUCKS  ",
                    unicodedata.normalize("NFD", "STARBUCKS")):
        axes, result = _score(dist, variant, "STARBUCKS COFFEE")
        assert (round(axes.x1_raw, 4), axes.query_tokens, result.grade) == (
            round(base_axes.x1_raw, 4), base_axes.query_tokens, base.grade)
    hangul = _score(dist, "블루커피", "BLU hands")[1].grade
    assert _score(dist, unicodedata.normalize("NFD", "블루커피"), "BLU hands")[1].grade == hangul
