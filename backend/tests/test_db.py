"""
core/db.py (PostgreSQL 접근 계층) 단위 테스트 — 감사보고서 5-2 공백 보완.

실 DB 접속 없이 순수 로직만 검증한다:
- psycopg 커넥션/풀은 가짜(_FakePool/_FakeConn)로 대체(monkeypatch)해 SQL 실행/
  파라미터 바인딩/결과 매핑 계약만 확인한다. 실 PostgreSQL 은 건드리지 않는다.
- 실 DB 가 필요한 통합 검증은 test_migrations.py(MARKLENS_TEST_DATABASE_URL 관례)
  가 담당하고, 여기서는 mock 으로 끝낸다.

검증 대상(공개 함수):
  - row_to_trademark : row 튜플 → API 계약(한글 키) dict 매핑
  - init_pool        : 풀 생성 파라미터 + 기동 검증(SELECT 1) + 멱등성
  - close_pool       : 종료 + 전역 정리, 미초기화 시 무동작
  - fetch_trademarks_by_image_keys : 빈 입력 단축, 파라미터 바인딩, 결과 매핑
  - fetch_dataset_info / count_trademarks : 조회 결과 변환, 풀 미초기화 시 예외

실행 (project root 기준):
    ml\\venv\\Scripts\\python.exe -m pytest backend/tests/test_db.py -q
"""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest

from backend.src.core import config, db

# --------------------------------------------------------------------
# psycopg 대역 (실 커넥션 없이 계약만 흉내낸다)
# --------------------------------------------------------------------

class _FakeCursor:
    """conn.execute() 반환 대역 — fetchall/fetchone 만 제공."""

    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    """psycopg 커넥션 대역 — 실행된 (sql, params) 를 기록하고 미리 넣은 rows 를 돌려준다."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.executed = []  # [(sql, params), ...]

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return _FakeCursor(self.rows)


class _FakePool:
    """psycopg_pool.ConnectionPool 대역 — conninfo/kwargs 를 기록하고 close 여부를 남긴다."""

    def __init__(self, conninfo=None, **kwargs):
        self.conninfo = conninfo
        self.kwargs = kwargs
        self.closed = False
        self.conn = _FakeConn()

    @contextmanager
    def connection(self):
        yield self.conn

    def close(self):
        self.closed = True


def _make_row(
    image_key="4020210000001.png",
    *,
    application_date=None,
    registration_date=None,
    vienna_codes=("점",),
    nice_classes=(35,),
    similarity_codes=("S0101",),
):
    """_SELECT_COLUMNS 순서에 맞는 trademark row 튜플을 만든다."""
    return (
        image_key.removesuffix(".png"),  # application_no
        None,                            # registration_no
        application_date,                # application_date
        registration_date,               # registration_date
        "더미상표",                       # name_ko
        "DUMMY",                         # name_en
        "도형복합",                       # mark_type
        "테스트 출원인",                   # applicant
        "테스트 출원인",                   # right_holder
        image_key,                       # image_key
        vienna_codes,                    # vienna_codes
        nice_classes,                    # nice_classes
        similarity_codes,                # similarity_codes
    )


@pytest.fixture(autouse=True)
def _reset_pool(monkeypatch):
    """모듈 전역 _pool 오염 방지 — 각 테스트 시작 시 None 을 보장하고 종료 시 복원."""
    monkeypatch.setattr(db, "_pool", None, raising=False)
    yield


# --------------------------------------------------------------------
# row_to_trademark — 순수 매핑 (row 튜플 → 한글 키 dict)
# --------------------------------------------------------------------

def test_row_to_trademark_maps_all_korean_keys():
    """13개 컬럼이 schemas 계약의 한글 키로 정확히 매핑된다."""
    row = (
        "4020210000001", "4019990000009",
        date(2021, 4, 5), date(2023, 10, 26),
        "더미상표", "DUMMY", "도형복합",
        "테스트 출원인", "테스트 권리자",
        "4020210000001.png", ["점", "선"], [35, 9], ["S0101"],
    )
    assert db.row_to_trademark(row) == {
        "출원번호": "4020210000001",
        "등록번호": "4019990000009",
        "출원일자": "2021-04-05",
        "등록일자": "2023-10-26",
        "상표한글명": "더미상표",
        "상표영문명": "DUMMY",
        "상표구분": "도형복합",
        "출원인": "테스트 출원인",
        "최종권리자": "테스트 권리자",
        "이미지파일": "4020210000001.png",
        "비엔나코드": ["점", "선"],
        "류": [35, 9],
        "유사군": ["S0101"],
    }


def test_row_to_trademark_none_dates_become_none():
    """출원/등록일자가 없으면(NULL) 문자열이 아니라 None 을 준다."""
    tm = db.row_to_trademark(_make_row(application_date=None, registration_date=None))
    assert tm["출원일자"] is None
    assert tm["등록일자"] is None


def test_row_to_trademark_dates_are_stringified():
    """date 객체는 str 로 직렬화된다(응답 계약이 문자열)."""
    tm = db.row_to_trademark(
        _make_row(application_date=date(2021, 4, 5), registration_date=date(2023, 10, 26))
    )
    assert tm["출원일자"] == "2021-04-05"
    assert tm["등록일자"] == "2023-10-26"


def test_row_to_trademark_none_arrays_become_empty_lists():
    """배열 컬럼이 NULL 이면 None 이 아니라 빈 리스트로 정규화된다."""
    tm = db.row_to_trademark(
        _make_row(vienna_codes=None, nice_classes=None, similarity_codes=None)
    )
    assert tm["비엔나코드"] == []
    assert tm["류"] == []
    assert tm["유사군"] == []


def test_row_to_trademark_coerces_array_columns_to_list():
    """psycopg 가 배열 컬럼을 튜플로 돌려줘도 응답은 항상 list 여야 한다(JSON 계약)."""
    tm = db.row_to_trademark(
        _make_row(vienna_codes=("점",), nice_classes=(35, 9), similarity_codes=("S0101",))
    )
    assert tm["비엔나코드"] == ["점"] and isinstance(tm["비엔나코드"], list)
    assert tm["류"] == [35, 9] and isinstance(tm["류"], list)
    assert tm["유사군"] == ["S0101"] and isinstance(tm["유사군"], list)


# --------------------------------------------------------------------
# init_pool / close_pool — 풀 수명주기
# --------------------------------------------------------------------

def test_init_pool_creates_pool_with_expected_params(monkeypatch):
    """DATABASE_URL 을 conninfo 로, 개발 장비용 소규모 파라미터로 풀을 만들고
    기동 시점에 SELECT 1 로 연결을 검증한다."""
    created = []

    class _P(_FakePool):
        def __init__(self, conninfo=None, **kwargs):
            super().__init__(conninfo=conninfo, **kwargs)
            created.append(self)

    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://sentinel/db")
    monkeypatch.setattr(db, "ConnectionPool", _P)

    db.init_pool()

    assert len(created) == 1
    pool = created[0]
    assert pool.conninfo == "postgresql://sentinel/db"
    assert pool.kwargs == {"min_size": 1, "max_size": 4, "open": True, "timeout": 10}
    # 기동 검증 쿼리가 실제로 실행됐는지(첫 요청에서 터지지 않게 하는 계약)
    assert pool.conn.executed == [("SELECT 1", None)]
    assert db._pool is pool


def test_init_pool_is_idempotent(monkeypatch):
    """이미 초기화된 풀이 있으면 재생성하지 않는다(요청마다 새 풀 금지)."""
    created = []

    class _P(_FakePool):
        def __init__(self, conninfo=None, **kwargs):
            super().__init__(conninfo=conninfo, **kwargs)
            created.append(self)

    monkeypatch.setattr(db, "ConnectionPool", _P)

    db.init_pool()
    first = db._pool
    db.init_pool()

    assert len(created) == 1
    assert db._pool is first


def test_close_pool_closes_and_clears(monkeypatch):
    """close_pool 은 풀을 닫고 전역을 None 으로 되돌린다."""
    pool = _FakePool()
    monkeypatch.setattr(db, "_pool", pool)

    db.close_pool()

    assert pool.closed is True
    assert db._pool is None


def test_close_pool_noop_when_not_initialized(monkeypatch):
    """풀이 없으면 close_pool 은 예외 없이 아무 것도 하지 않는다."""
    monkeypatch.setattr(db, "_pool", None)
    db.close_pool()  # 예외가 나면 실패
    assert db._pool is None


# --------------------------------------------------------------------
# 풀 미초기화 시 조회 함수 동작 (_require_pool 경계, 공개 함수로 검증)
# --------------------------------------------------------------------

def test_fetch_dataset_info_raises_without_pool(monkeypatch):
    """db 모드가 아닌데 조회를 시도하면 RuntimeError 로 명확히 실패한다."""
    monkeypatch.setattr(db, "_pool", None)
    with pytest.raises(RuntimeError):
        db.fetch_dataset_info()


def test_count_trademarks_raises_without_pool(monkeypatch):
    """count_trademarks 도 풀 미초기화면 RuntimeError."""
    monkeypatch.setattr(db, "_pool", None)
    with pytest.raises(RuntimeError):
        db.count_trademarks()


# --------------------------------------------------------------------
# fetch_trademarks_by_image_keys — 후보 메타 일괄 조회
# --------------------------------------------------------------------

def test_fetch_by_image_keys_empty_returns_empty(monkeypatch):
    """빈 입력은 풀 없이도 즉시 {} — 불필요한 커넥션 점유/쿼리를 피한다."""
    monkeypatch.setattr(db, "_pool", None)  # 풀이 없어도 예외가 나면 안 됨
    assert db.fetch_trademarks_by_image_keys([]) == {}


def test_fetch_by_image_keys_uses_parameterized_query(monkeypatch):
    """키 목록을 SQL 문자열에 직접 넣지 않고 ANY(%s) 파라미터로 바인딩한다."""
    keys = ["a.png", "b.png"]
    pool = _FakePool()
    pool.conn.rows = []
    monkeypatch.setattr(db, "_pool", pool)

    db.fetch_trademarks_by_image_keys(keys)

    assert len(pool.conn.executed) == 1
    sql, params = pool.conn.executed[0]
    assert "image_key = ANY(%s)" in sql
    assert params == (keys,)


def test_fetch_by_image_keys_maps_rows_keyed_by_image(monkeypatch):
    """조회 결과가 이미지파일명 → trademark dict 형태로 매핑된다."""
    keys = ["4020210000001.png", "4020210000002.png"]
    pool = _FakePool()
    pool.conn.rows = [_make_row(keys[0]), _make_row(keys[1])]
    monkeypatch.setattr(db, "_pool", pool)

    result = db.fetch_trademarks_by_image_keys(keys)

    assert set(result.keys()) == set(keys)
    assert result[keys[0]]["이미지파일"] == keys[0]
    assert result[keys[0]]["출원번호"] == "4020210000001"
    assert result[keys[1]]["출원번호"] == "4020210000002"


def test_fetch_by_image_keys_missing_key_absent_from_result(monkeypatch):
    """DB 에 없는 파일명은 결과에서 키 자체가 빠진다(엔진이 None 처리)."""
    present = "4020210000001.png"
    pool = _FakePool()
    pool.conn.rows = [_make_row(present)]  # 요청 2건 중 1건만 존재
    monkeypatch.setattr(db, "_pool", pool)

    result = db.fetch_trademarks_by_image_keys([present, "4020219999999.png"])

    assert set(result.keys()) == {present}


def test_fetch_by_application_numbers_uses_parameterized_query(monkeypatch):
    numbers = ["4020210000001", "4020210000002"]
    pool = _FakePool()
    pool.conn.rows = [_make_row(f"{number}.png") for number in numbers]
    monkeypatch.setattr(db, "_pool", pool)

    result = db.fetch_trademarks_by_application_numbers(numbers)

    sql, params = pool.conn.executed[0]
    assert "application_no = ANY(%s)" in sql
    assert params == (numbers,)
    assert set(result) == set(numbers)


def test_fetch_by_application_numbers_empty_returns_empty(monkeypatch):
    monkeypatch.setattr(db, "_pool", None)
    assert db.fetch_trademarks_by_application_numbers([]) == {}


# --------------------------------------------------------------------
# fetch_dataset_info — meta 테이블 JSONB
# --------------------------------------------------------------------

def test_fetch_dataset_info_returns_stored_value(monkeypatch):
    """meta.value(JSONB) 를 그대로 돌려준다."""
    info = {"총_상표수": 10, "데이터_기준": "더미"}
    pool = _FakePool()
    pool.conn.rows = [(info,)]
    monkeypatch.setattr(db, "_pool", pool)

    assert db.fetch_dataset_info() == info


def test_fetch_dataset_info_empty_when_missing(monkeypatch):
    """dataset_info 행이 없으면 빈 dict."""
    pool = _FakePool()
    pool.conn.rows = []  # fetchone -> None
    monkeypatch.setattr(db, "_pool", pool)

    assert db.fetch_dataset_info() == {}


# --------------------------------------------------------------------
# count_trademarks — /health 용 개수
# --------------------------------------------------------------------

def test_count_trademarks_returns_int(monkeypatch):
    """count(*) 결과를 int 로 반환한다.

    이미 int 인 값을 넣으면 int() 강제 변환이 실행되지 않아 테스트가 헛돈다.
    드라이버가 다른 수치 타입(Decimal 등)을 돌려주는 상황을 넣어 변환을 실제로 태운다.
    """
    pool = _FakePool()
    pool.conn.rows = [(Decimal("42"),)]
    monkeypatch.setattr(db, "_pool", pool)

    n = db.count_trademarks()
    assert n == 42
    assert type(n) is int  # noqa: E721 — Decimal 이 그대로 새어 나오면 실패해야 한다


def test_fetch_all_image_keys_returns_authoritative_set(monkeypatch):
    pool = _FakePool()
    pool.conn.rows = [("a.png",), ("b.jpg",), ("a.png",)]
    monkeypatch.setattr(db, "_pool", pool)

    assert db.fetch_all_image_keys() == {"a.png", "b.jpg"}
    assert "WHERE image_key IS NOT NULL" in pool.conn.executed[0][0]
