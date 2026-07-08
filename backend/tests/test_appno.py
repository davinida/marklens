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


def test_patent_number_rejected():
    # 특허(10 시작)는 상표가 아니다 — 심판 검색 결과에 섞여 들어오는 실측 케이스
    assert not is_trademark_application_number("1020210126877")


def test_wrong_length_rejected():
    assert not is_trademark_application_number("40202101")
    assert not is_trademark_application_number("")
