"""
ML 리소스 로딩 및 검색 실행 엔진.

서버 startup 시점에 1회만 모델/인덱스/메타를 로딩하고, 이후 요청에서는
메모리에 보관된 자원을 재사용합니다.

이 모듈은 ml/scripts/kipris_search.py 의 흐름을
"검색 → 메타 결합 → 등급" 그대로 옮긴 함수 run_search() 를 제공합니다.
"""

import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Optional

from . import appno, config, paths

logger = logging.getLogger(__name__)


# === macOS Apple Silicon의 PyTorch + FAISS OpenMP 충돌 방지 ===
# 이 줄은 ml 모듈을 import 하기 전에 효력 발생해야 함.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# ml/src 를 sys.path 에 추가하여 from src.X import Y 형태로 import.
# kipris_search.py 와 동일한 패턴.
if str(paths.ML_ROOT) not in sys.path:
    sys.path.insert(0, str(paths.ML_ROOT))

import faiss  # noqa: E402

from src.embedding import (  # noqa: E402
    EMBEDDING_CONTRACT_VERSION,
    EMBEDDING_DIM,
    MODEL_NAME,
    PRETRAINED,
    encode_image,
)
from src.preprocess import DEFAULT_PREPROCESS_VERSION  # noqa: E402
from src.scoring import score_results  # noqa: E402
from src.search import load_index, search  # noqa: E402


@dataclass
class EngineState:
    """startup 시 로딩되어 메모리에 보관되는 리소스 컨테이너."""

    index: object = None  # faiss.Index
    image_paths: list[str] = field(default_factory=list)  # 인덱스 순번 → 파일명
    image_path_set: set[str] = field(default_factory=set)
    trademark_lookup: dict = field(default_factory=dict)  # 파일명 → trademark dict (file 모드 전용)
    dataset_info: dict = field(default_factory=dict)
    storage_mode: str = "file"  # "file" | "db" (config.STORAGE_MODE 복사본)
    trademark_count: int = 0  # /health 용. db 모드에선 startup 시점의 DB 건수
    artifact_generation_id: str | None = None
    ready: bool = False


# 모듈 전역 인스턴스. main.py 의 startup 핸들러가 load_all() 로 채움.
state = EngineState()


def _sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise RuntimeError(f"{label} must be a lowercase SHA-256 hex digest.")
    return value


def _resolve_public_image(image_root: Path, image_key: object) -> tuple[str, Path]:
    if (
        not isinstance(image_key, str)
        or not image_key
        or image_key != image_key.strip()
        or "\\" in image_key
        or "\x00" in image_key
    ):
        raise RuntimeError(f"Unsafe image key in index metadata: {image_key!r}")

    relative = PurePosixPath(image_key)
    parts = image_key.split("/")
    if (
        relative.is_absolute()
        or relative.as_posix() != image_key
        or any(part in ("", ".", "..") or ":" in part for part in parts)
    ):
        raise RuntimeError(f"Unsafe image key in index metadata: {image_key!r}")

    try:
        image_path = image_root.joinpath(*relative.parts).resolve(strict=True)
        image_path.relative_to(image_root)
    except FileNotFoundError:
        raise RuntimeError(f"Published result image is missing: {image_key!r}") from None
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"Published result image escapes the configured image root: {image_key!r}"
        ) from exc
    if not image_path.is_file():
        raise RuntimeError(f"Published result image is not a file: {image_key!r}")
    return image_key, image_path


def _validate_public_image_artifacts(index_meta: dict, manifest: dict) -> None:
    """Verify every image that production exposes as a search result."""
    raw_keys = index_meta.get("image_paths")
    if not isinstance(raw_keys, list):
        raise RuntimeError("Index metadata image_paths must be a list.")

    try:
        image_root = Path(paths.IMAGES_DIR).resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise RuntimeError(
            f"Configured result image root is missing or inaccessible: {paths.IMAGES_DIR}"
        ) from exc
    if not image_root.is_dir():
        raise RuntimeError(f"Configured result image root is not a directory: {image_root}")

    resolved_images = [
        _resolve_public_image(image_root, image_key) for image_key in raw_keys
    ]
    image_keys = [image_key for image_key, _ in resolved_images]
    if len(set(image_keys)) != len(image_keys):
        raise RuntimeError("Index metadata image_paths contains duplicate keys.")

    raw_hashes = index_meta.get("image_hashes")
    if not isinstance(raw_hashes, dict) or set(raw_hashes) != set(image_keys):
        raise RuntimeError("Index metadata image_hashes must exactly cover image_paths.")

    verified_hashes: dict[str, str] = {}
    for image_key, image_path in resolved_images:
        expected_hash = _require_sha256(
            raw_hashes.get(image_key),
            f"Index metadata image hash for {image_key!r}",
        )
        try:
            actual_hash = _sha256_file(image_path)
        except OSError as exc:
            raise RuntimeError(
                f"Published result image is unreadable: {image_key!r}"
            ) from exc
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"Published result image SHA-256 mismatch: {image_key!r}"
            )
        verified_hashes[image_key] = expected_hash

    source = manifest.get("source")
    if not isinstance(source, dict):
        raise RuntimeError("Manifest source contract is required for public images.")
    expected_set_hash = _require_sha256(
        source.get("image_set_sha256"), "Manifest image_set_sha256"
    )
    digest = hashlib.sha256()
    for image_key in image_keys:
        digest.update(image_key.encode("utf-8"))
        digest.update(b"\0")
        digest.update(verified_hashes[image_key].encode("ascii"))
        digest.update(b"\n")
    if digest.hexdigest() != expected_set_hash:
        raise RuntimeError("Manifest image_set_sha256 does not match index metadata.")


def _validate_artifact_manifest(index, index_meta: dict, manifest: dict) -> str:
    """Validate the model/index/preprocess generation contract at startup."""
    try:
        generation_id = str(manifest["generation_id"])
        model = manifest["model"]
        index_contract = manifest["index"]
        preprocess = manifest["preprocess"]
        artifacts = manifest["artifacts"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"인덱스 manifest 필수 필드가 없습니다: {exc}") from None

    expected_model = {
        "name": MODEL_NAME,
        "pretrained": PRETRAINED,
        "embedding_dim": EMBEDDING_DIM,
        "embedding_contract": EMBEDDING_CONTRACT_VERSION,
    }
    for key, expected in expected_model.items():
        if model.get(key) != expected:
            raise RuntimeError(
                f"인덱스 모델 계약 불일치: {key}={model.get(key)!r}, expected={expected!r}"
            )
    if preprocess.get("version") != DEFAULT_PREPROCESS_VERSION:
        raise RuntimeError(
            "인덱스 전처리 계약 불일치: "
            f"{preprocess.get('version')!r} != {DEFAULT_PREPROCESS_VERSION!r}"
        )
    if index_contract.get("metric") != "inner_product":
        raise RuntimeError("인덱스 metric은 inner_product여야 합니다.")
    if index_contract.get("vectors_l2_normalized") is not True:
        raise RuntimeError("인덱스 벡터 L2 정규화 계약이 없습니다.")
    if int(index_contract.get("vector_count", -1)) != int(index.ntotal):
        raise RuntimeError("manifest의 vector_count가 실제 인덱스와 다릅니다.")
    if int(getattr(index, "d", -1)) != EMBEDDING_DIM:
        raise RuntimeError("FAISS 인덱스 임베딩 차원이 모델과 다릅니다.")
    if int(getattr(index, "metric_type", -1)) != int(faiss.METRIC_INNER_PRODUCT):
        raise RuntimeError("FAISS 인덱스 metric_type이 inner product가 아닙니다.")
    if index_meta.get("generation_id") != generation_id:
        raise RuntimeError("인덱스 메타와 manifest generation_id가 다릅니다.")

    if config.ENVIRONMENT == "production":
        git_contract = manifest.get("git")
        if not isinstance(git_contract, dict) or git_contract.get("dirty") is not False:
            raise RuntimeError(
                "production 인덱스는 clean Git source에서 생성되어야 합니다."
            )

    for label, path in (
        ("index", paths.INDEX_PATH),
        ("metadata", paths.INDEX_META_PATH),
    ):
        contract = artifacts.get(label) or {}
        if contract.get("filename") != path.name:
            raise RuntimeError(f"manifest {label} 파일명이 실제 경로와 다릅니다.")
        if contract.get("sha256") != _sha256_file(path):
            raise RuntimeError(f"manifest {label} SHA-256이 실제 파일과 다릅니다.")
    if config.ENVIRONMENT == "production" and config.PUBLIC_RESULT_IMAGES:
        _validate_public_image_artifacts(index_meta, manifest)
    return generation_id


def load_all() -> None:
    """
    모든 리소스를 메모리에 적재합니다. 서버 startup 시 1회만 호출하세요.

    로딩 항목:
    - FAISS 인덱스 (paths.INDEX_PATH)
    - 인덱스 메타 (paths.INDEX_META_PATH) → image_paths 리스트
    - 상표 상세 메타 (paths.TRADEMARK_META_PATH) → trademark_lookup, dataset_info
    - CLIP 모델 (encode_image 의 내부 lazy 캐시를 워밍업)

    실패 시 RuntimeError 를 발생시켜 서버 기동을 중단합니다 (조용히 넘어가지 않음).
    """
    state.ready = False
    state.artifact_generation_id = None

    if paths.INDEX_DIRTY_PATH.exists():
        raise RuntimeError(
            "DB 변경 뒤 인덱스 게시가 완료되지 않았습니다. "
            f"수집 파이프라인으로 재빌드하세요: {paths.INDEX_DIRTY_PATH}"
        )

    # ---- 인덱스 파일 ----
    if not paths.INDEX_PATH.exists():
        raise RuntimeError(
            f"FAISS 인덱스 파일이 없습니다: {paths.INDEX_PATH}\n"
            f"먼저 `python scripts/build_index.py --image-dir data/images "
            f"--index-name kipris` 로 빌드하세요."
        )
    if not paths.INDEX_META_PATH.exists():
        raise RuntimeError(
            f"인덱스 메타가 없습니다: {paths.INDEX_META_PATH}"
        )

    # ---- FAISS 인덱스 로드 ----
    logger.info("리소스 로딩 시작 (storage_mode=%s)", config.STORAGE_MODE)
    state.index = load_index(paths.INDEX_PATH)

    # ---- 인덱스 메타 로드 (image_paths) ----
    with open(paths.INDEX_META_PATH, "r", encoding="utf-8") as f:
        index_meta = json.load(f)
    state.image_paths = index_meta["image_paths"]

    # 일관성 검증: index.ntotal 과 image_paths 길이
    if state.index.ntotal != len(state.image_paths):
        raise RuntimeError(
            f"인덱스/메타 불일치: index.ntotal={state.index.ntotal}, "
            f"image_paths 길이={len(state.image_paths)}"
        )
    if len(set(state.image_paths)) != len(state.image_paths):
        raise RuntimeError("인덱스 메타 image_paths에 중복 키가 있습니다.")
    state.image_path_set = set(state.image_paths)

    if paths.INDEX_MANIFEST_PATH.exists():
        with open(paths.INDEX_MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        state.artifact_generation_id = _validate_artifact_manifest(
            state.index, index_meta, manifest
        )
    elif config.ENVIRONMENT == "production":
        raise RuntimeError(
            f"production에서는 인덱스 manifest가 필수입니다: {paths.INDEX_MANIFEST_PATH}"
        )
    else:
        logger.warning(
            "legacy 인덱스에 manifest가 없어 최소 호환성만 확인합니다: %s",
            paths.INDEX_MANIFEST_PATH,
        )

    # ---- 상표 상세 메타 로드 (백엔드-4: 저장소 모드 분기) ----
    state.storage_mode = config.STORAGE_MODE
    if state.storage_mode == "db":
        # DB 모드: 메타는 요청 시점에 후보만 조회. startup 에서는 연결 검증 +
        # dataset_info/건수만 읽는다. (JSON 전체 메모리 적재 제거)
        from . import db

        db.init_pool()
        db_image_keys = db.fetch_all_image_keys()
        if db_image_keys != state.image_path_set:
            missing_in_db = sorted(state.image_path_set - db_image_keys)[:5]
            missing_in_index = sorted(db_image_keys - state.image_path_set)[:5]
            raise RuntimeError(
                "DB image_key와 인덱스 authoritative key가 일치하지 않습니다. "
                f"DB 누락 예시={missing_in_db}, 인덱스 누락 예시={missing_in_index}"
            )
        state.dataset_info = db.fetch_dataset_info()
        state.trademark_count = db.count_trademarks()
        if state.trademark_count == 0:
            raise RuntimeError(
                "DB에 상표 데이터가 없습니다. 먼저 마이그레이션을 실행하세요:\n"
                "  python -m backend.scripts.migrate_json_to_db"
            )
    else:
        # 파일 모드: 기존 방식 그대로 (팀원 로컬 기본값 — DB 없이도 동작)
        if not paths.TRADEMARK_META_PATH.exists():
            raise RuntimeError(
                f"상표 메타가 없습니다: {paths.TRADEMARK_META_PATH}\n"
                f"먼저 `python scripts/build_kipris_metadata.py` 로 생성하세요."
            )
        with open(paths.TRADEMARK_META_PATH, "r", encoding="utf-8") as f:
            kipris_meta = json.load(f)
        state.dataset_info = kipris_meta.get("dataset_info", {})
        state.trademark_lookup = {
            t["이미지파일"]: t for t in kipris_meta.get("trademarks", [])
        }
        state.trademark_count = len(state.trademark_lookup)

    # ---- dataset_info 계약 검증 (기동 시점에 실패시키기) ----
    # 과거: 필드가 빠진 메타가 첫 검색 요청에서 미처리 500 을 만들었다.
    # 응답 조립(api/search.py)이 쓰는 스키마로 지금 검증해 조용한 배포 사고를 막는다.
    from ..schemas.search import DatasetInfo

    try:
        DatasetInfo(**state.dataset_info)
    except Exception as e:
        raise RuntimeError(
            f"dataset_info 가 응답 스키마와 맞지 않습니다 "
            f"(총_상표수/출원일자_범위/데이터_기준/생성일자 4필드 필수): {e}"
        )

    # ---- CLIP 모델 워밍업 ----
    # encode_image 가 _load_model() 을 lazy 호출. 작은 더미 이미지로 미리 트리거.
    # 이렇게 해두면 첫 요청에서 모델 로딩 시간이 사용자에게 노출되지 않음.
    from PIL import Image as PILImage
    from PIL import ImageDraw

    _dummy = PILImage.new("RGB", (64, 64), color="white")
    ImageDraw.Draw(_dummy).rectangle((16, 16, 48, 48), fill="black")
    encode_image(_dummy)

    state.ready = True
    logger.info(
        "리소스 로딩 완료: index=%d건, trademark=%d건, mode=%s",
        state.index.ntotal,
        state.trademark_count,
        state.storage_mode,
    )


def shutdown() -> None:
    """서버 shutdown 시 외부 자원 정리 (main.py lifespan 이 호출)."""
    if state.storage_mode == "db":
        from . import db

        db.close_pool()


def lookup_trademarks_by_application_numbers(
    application_numbers: list[str],
) -> dict[str, dict]:
    """현재 게시된 로컬 데이터에서 출원번호별 상표 메타를 조회한다.

    `/name-check`의 KIPRIS 후보에 이미 게시 권한과 무결성을 확인한 로컬 이미지만
    연결하기 위한 조인 경계다. 엔진이 준비되지 않았거나 번호 형식이 잘못된 후보는
    조용히 제외해 이름 확인 자체가 로컬 이미지 상태에 의존하지 않게 한다.
    """
    if not state.ready:
        return {}

    normalized_numbers: set[str] = set()
    for raw in application_numbers:
        try:
            normalized_numbers.add(appno.normalize_application_number(raw))
        except ValueError:
            continue
    if not normalized_numbers:
        return {}

    ordered_numbers = sorted(normalized_numbers)
    if state.storage_mode == "db":
        from . import db

        return db.fetch_trademarks_by_application_numbers(ordered_numbers)

    result: dict[str, dict] = {}
    for trademark in state.trademark_lookup.values():
        try:
            application_number = appno.normalize_application_number(
                str(trademark.get("출원번호") or "")
            )
        except ValueError:
            continue
        if application_number in normalized_numbers:
            result[application_number] = trademark
    return result


def run_search(image_input, top_k: int) -> dict:
    """
    쿼리 이미지에 대해 검색 + 메타 결합 + 등급 산출까지 수행합니다.

    Args:
        image_input: encode_image()가 받을 수 있는 형태
                     (bytes / str / Path / PIL.Image.Image).
        top_k: 반환할 결과 개수.

    Returns:
        dict 구조:
        {
            "grade": <score_results 반환 dict>,
            "matches": [
                {
                    "rank": int,
                    "similarity": float,
                    "이미지파일": str,
                    "trademark": <kipris_metadata.json 의 trademark 객체 또는 None>,
                }, ...
            ],
            "index_size": int,
            "top_k_requested": int,
            "top_k_returned": int,
        }
    """
    if not state.ready:
        raise RuntimeError("Engine 이 아직 초기화되지 않았습니다.")

    # 1) 임베딩 + 검색. 판정용 후보 수는 표시 top_k와 독립적으로 고정한다.
    query_emb = encode_image(image_input)
    scoring_k = min(
        max(int(top_k), config.SCORING_TOP_K),
        int(state.index.ntotal),
    )
    scoring_distances, scoring_indices = search(
        state.index, query_emb, k=scoring_k
    )
    display_count = min(int(top_k), len(scoring_distances))
    distances = scoring_distances[:display_count]
    indices = scoring_indices[:display_count]

    # 2) 후보 파일명 확정
    hits: list[tuple[int, float, Optional[str]]] = []  # (rank, similarity, filename)
    for rank, (d, i) in enumerate(zip(distances, indices), 1):
        idx_int = int(i)
        filename = (
            state.image_paths[idx_int]
            if 0 <= idx_int < len(state.image_paths)
            else None
        )
        hits.append((rank, float(d), filename))

    # 3) 메타 결합 — db 모드는 후보만 일괄 조회(쿼리 1회), file 모드는 dict 조회
    if state.storage_mode == "db":
        from . import db

        filenames = [f for _, _, f in hits if f]
        lookup = db.fetch_trademarks_by_image_keys(filenames)
    else:
        lookup = state.trademark_lookup

    matches = []
    for rank, similarity, filename in hits:
        matches.append({
            "rank": rank,
            "similarity": similarity,
            "이미지파일": filename,
            "trademark": lookup.get(filename) if filename else None,  # 없으면 None
        })

    # 3) 등급 산출
    grade = score_results(scoring_distances)

    return {
        "grade": grade,
        "matches": matches,
        "index_size": int(state.index.ntotal),
        "top_k_requested": int(top_k),
        "top_k_returned": int(len(matches)),
        "scoring_k": int(len(scoring_distances)),
    }
