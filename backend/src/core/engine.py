"""
ML 리소스 로딩 및 검색 실행 엔진.

서버 startup 시점에 1회만 모델/인덱스/메타를 로딩하고, 이후 요청에서는
메모리에 보관된 자원을 재사용합니다.

이 모듈은 ml/scripts/kipris_search.py 의 흐름을
"검색 → 메타 결합 → 등급" 그대로 옮긴 함수 run_search() 를 제공합니다.
"""

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

from . import config, paths


# === macOS Apple Silicon의 PyTorch + FAISS OpenMP 충돌 방지 ===
# 이 줄은 ml 모듈을 import 하기 전에 효력 발생해야 함.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# ml/src 를 sys.path 에 추가하여 from src.X import Y 형태로 import.
# kipris_search.py 와 동일한 패턴.
if str(paths.ML_ROOT) not in sys.path:
    sys.path.insert(0, str(paths.ML_ROOT))

from src.embedding import encode_image  # noqa: E402
from src.search import load_index, search  # noqa: E402
from src.scoring import score_results  # noqa: E402


@dataclass
class EngineState:
    """startup 시 로딩되어 메모리에 보관되는 리소스 컨테이너."""

    index: object = None  # faiss.Index
    image_paths: list[str] = field(default_factory=list)  # 인덱스 순번 → 파일명
    trademark_lookup: dict = field(default_factory=dict)  # 파일명 → trademark dict (file 모드 전용)
    dataset_info: dict = field(default_factory=dict)
    storage_mode: str = "file"  # "file" | "db" (config.STORAGE_MODE 복사본)
    trademark_count: int = 0  # /health 용. db 모드에선 startup 시점의 DB 건수
    ready: bool = False


# 모듈 전역 인스턴스. main.py 의 startup 핸들러가 load_all() 로 채움.
state = EngineState()


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

    # ---- 상표 상세 메타 로드 (백엔드-4: 저장소 모드 분기) ----
    state.storage_mode = config.STORAGE_MODE
    if state.storage_mode == "db":
        # DB 모드: 메타는 요청 시점에 후보만 조회. startup 에서는 연결 검증 +
        # dataset_info/건수만 읽는다. (JSON 전체 메모리 적재 제거)
        from . import db

        db.init_pool()
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
    _dummy = PILImage.new("RGB", (64, 64), color=(128, 128, 128))
    encode_image(_dummy)

    state.ready = True


def shutdown() -> None:
    """서버 shutdown 시 외부 자원 정리 (main.py lifespan 이 호출)."""
    if state.storage_mode == "db":
        from . import db

        db.close_pool()


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

    # 1) 임베딩 + 검색
    query_emb = encode_image(image_input)
    distances, indices = search(state.index, query_emb, k=top_k)

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
    grade = score_results(distances)

    return {
        "grade": grade,
        "matches": matches,
        "index_size": int(state.index.ntotal),
        "top_k_requested": int(top_k),
        "top_k_returned": int(len(matches)),
    }
