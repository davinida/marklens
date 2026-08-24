"""
이미지 스토리지 심(shim) — 이미지 접근을 한 모듈로 모은다.

MarkLens 는 현재 검색 결과 이미지를 로컬 파일시스템(paths.IMAGES_DIR)에
보관하고 `/images` 로 정적 서빙한다. 이 모듈은 "이미지가 어디에 있고 어떻게
접근하는가"를 캡슐화하는 얇은 계층이며, 지금은 로컬 파일 구현만 둔다.

S3 전환 계약 (중요):
    나중에 이미지를 S3(또는 다른 오브젝트 스토리지)로 옮길 때, 호출부를
    고치지 말고 **이 모듈만 교체**하라. 아래 세 함수의 시그니처와 반환 계약이
    스토리지 백엔드 사이의 유일한 경계다. 특히 public_url 이 만드는
    "<IMAGES_URL_PREFIX>/<image_key>" 형식은 프론트/계약 테스트가 의존하는
    외부 계약이므로, 전환 후에도 같은 형식(또는 프리사인 URL)을 유지한다.

    - image_exists(image_key) : 키에 해당하는 이미지 실물이 있는가
    - local_path(image_key)   : 로컬 파일시스템 경로 (로컬 백엔드 전용)
    - public_url(image_key)   : 클라이언트가 접근할 공개 URL

    S3 백엔드에서 local_path 는 의미가 사라진다(정적 마운트가 없어지고 S3 가
    직접 서빙). 그때 local_path 의 두 호출부 — main.py 정적 마운트 디렉터리와
    collect 파이프라인 저장 목적지 — 는 각각 S3 업로드/프리사인 방식으로
    이 모듈 안에서 대체된다. 호출부 코드는 그대로다.
"""

from pathlib import Path

from . import config, paths


def image_exists(image_key: str) -> bool:
    """image_key 에 해당하는 이미지 실물이 스토리지에 존재하는지 반환한다.

    migrate reconcile 의 "DB에 있으면 이미지도 있다" 불변식 확인에 쓰인다.
    로컬 구현: IMAGES_DIR 아래 해당 파일 존재 여부.
    """
    return (paths.IMAGES_DIR / image_key).exists()


def local_path(image_key: str = "") -> Path:
    """이미지의 로컬 파일시스템 경로를 반환한다 (로컬 백엔드 전용).

    - image_key 지정: 그 키의 파일 경로 (collect 파이프라인 저장 목적지).
    - image_key 생략: 스토리지 루트 디렉터리 (main.py 정적 마운트 대상).

    S3 전환 시 이 함수의 호출부는 업로드/프리사인으로 대체된다(모듈 docstring).
    """
    return paths.IMAGES_DIR / image_key if image_key else paths.IMAGES_DIR


def public_url(image_key: str | None) -> str | None:
    """클라이언트가 이미지를 받을 공개 URL. 키가 없으면 None.

    형식: "<IMAGES_URL_PREFIX>/<image_key>" (예: "/images/40202100000101.png").
    이 형식은 외부 계약이다 — S3 전환 시에도 이 함수만 바꿔 형식을 보존한다.
    """
    if not image_key or not config.PUBLIC_RESULT_IMAGES:
        return None
    return f"{config.IMAGES_URL_PREFIX}/{image_key}"
