"""출원번호 정규화 단위 테스트."""

import pytest

from backend.src.core.appno import (
    is_trademark_application_number,
    normalize_application_number,
)


def test_normalize_hyphenated():
    assert normalize_application_number("40-2021-0126877") == "4020210126877"


def test_normalize_with_spaces_and_text():
    assert normalize_application_number(" 40 2021 0126877 ") == "4020210126877"


def test_normalize_already_clean():
    assert normalize_application_number("4020210126877") == "4020210126877"


@pytest.mark.parametrize("bad", ["", None, "abc", "----"])
def test_normalize_rejects_empty(bad):
    with pytest.raises(ValueError):
        normalize_application_number(bad)


def test_trademark_prefix_40_and_41():
    assert is_trademark_application_number("4020210126877")
    assert is_trademark_application_number("41-2021-0126877")


@pytest.mark.parametrize("prefix", ["45", "50", "51", "56", "70"])
def test_measured_trademark_prefixes_accepted(prefix):
    # 2026-07-09 실측: 이 접두들은 등록번호가 40/41/45 인 정식 상표·서비스표다
    # (삼성전자 등록 도형상표 500건 표본). 화이트리스트 시절엔 11.4%가 버려졌다.
    assert is_trademark_application_number(f"{prefix}20210126877")


@pytest.mark.parametrize("prefix", ["10", "20", "30"])
def test_non_trademark_rights_rejected(prefix):
    # 특허(10)/실용신안(20)/디자인권(30)은 상표가 아닌 별개 권리 — 심판 검색
    # 결과에 섞여 들어오는 실측 케이스(원래 필터의 존재 이유)
    assert not is_trademark_application_number(f"{prefix}20210126877")


def test_wrong_length_rejected():
    assert not is_trademark_application_number("40202101")
    assert not is_trademark_application_number("")
