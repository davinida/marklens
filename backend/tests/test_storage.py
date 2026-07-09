"""
백엔드-3(스토리지 분리) 2단계: core/storage 심 3함수 단위 테스트.

실엔진/실DB/네트워크 불필요 — tmp_path 로 만든 임시 이미지 디렉터리를
paths.IMAGES_DIR 에 monkeypatch 로 주입해 로컬 백엔드 동작만 검증한다.
(storage 는 호출 시점에 paths.IMAGES_DIR 를 읽으므로 monkeypatch 가 반영된다.)

검증 대상 계약:
  - image_exists  : 파일 존재/부재를 정확히 판별
  - local_path    : 키 지정 시 파일 경로, 생략 시 루트 디렉터리
  - public_url    : "<IMAGES_URL_PREFIX>/<key>" 형식(외부 계약), 빈 키는 None

실행 (project root 기준):
    ml\\venv\\Scripts\\python.exe -m pytest backend/tests/test_storage.py -q
"""

import pytest

from backend.src.core import config, paths, storage


@pytest.fixture
def images_dir(tmp_path, monkeypatch):
    """임시 이미지 루트를 storage 가 읽는 paths.IMAGES_DIR 로 주입."""
    d = tmp_path / "images"
    d.mkdir()
    monkeypatch.setattr(paths, "IMAGES_DIR", d)
    return d


# --------------------------------------------------------------------
# local_path — 로컬 경로 획득
# --------------------------------------------------------------------

def test_local_path_without_key_returns_root_dir(images_dir):
    # 정적 마운트 대상: 키 생략 시 스토리지 루트 디렉터리
    assert storage.local_path() == images_dir


def test_local_path_with_key_joins_under_root(images_dir):
    # collect 파이프라인 저장 목적지: 키가 루트 아래로 결합
    assert storage.local_path("40202100000101.png") == images_dir / "40202100000101.png"


# --------------------------------------------------------------------
# image_exists — 존재 확인 (migrate reconcile)
# --------------------------------------------------------------------

def test_image_exists_true_when_file_present(images_dir):
    (images_dir / "present.png").write_bytes(b"\x89PNG")
    assert storage.image_exists("present.png") is True


def test_image_exists_false_when_missing(images_dir):
    assert storage.image_exists("missing.png") is False


def test_image_exists_uses_current_images_dir(tmp_path, monkeypatch):
    # 다른 디렉터리로 바꾸면 이전 파일은 더 이상 존재하지 않아야 한다(호출 시점 조회).
    first = tmp_path / "a"
    first.mkdir()
    (first / "x.png").write_bytes(b"x")
    monkeypatch.setattr(paths, "IMAGES_DIR", first)
    assert storage.image_exists("x.png") is True

    second = tmp_path / "b"
    second.mkdir()
    monkeypatch.setattr(paths, "IMAGES_DIR", second)
    assert storage.image_exists("x.png") is False


# --------------------------------------------------------------------
# public_url — 공개 URL 생성 (응답 조립)
# --------------------------------------------------------------------

def test_public_url_builds_prefixed_path():
    key = "40202100000101.png"
    assert storage.public_url(key) == f"{config.IMAGES_URL_PREFIX}/{key}"


def test_public_url_matches_external_contract_format():
    # 프론트/계약 테스트가 의존하는 "/images/<key>" 형식 고정
    assert storage.public_url("x.png") == "/images/x.png"


def test_public_url_none_for_missing_key():
    assert storage.public_url(None) is None
    assert storage.public_url("") is None
