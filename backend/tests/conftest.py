"""
backend 테스트 공통 설정.

실행 (project root 기준):
    ml\\venv\\Scripts\\python.exe -m pytest backend/tests -v

계약 테스트(test_api_contract.py) 실행 모드 두 가지:
- 실환경 모드: ml/data 에 인덱스·메타·이미지가 있으면 그대로 사용 (CLIP 실로딩).
- 가짜 ML 모드: 인덱스가 없거나 MARKLENS_FAKE_ML=1 이면, 임시 디렉토리에
  더미 FAISS 인덱스 + 메타 + 이미지 10건을 만들어 사용하고 encode_image 를
  결정적 벡터로 몽키패치한다 → CLIP 가중치 다운로드/로딩 없이 계약 테스트가
  어디서나(CI 포함) 항상 돈다. 검증 대상은 라우팅·검증·응답 계약이지
  모델 품질이 아니므로 이것으로 충분하다.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가 (backend.src.* / ml sys.path 주입은 engine 이 수행)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest  # noqa: E402

# macOS Apple Silicon: 아래 _build_fake_ml_env() 가 faiss 를 올리기 전에 torch 가 먼저 import
# 돼 있어야 한다(순서가 바뀌면 이후 torch 연산·CLIP 로딩에서 SIGSEGV — backend/src/core/engine.py
# 주석 참조). conftest 는 모든 테스트 모듈보다 먼저 로드되므로 여기서 순서를 고정한다.
import torch  # noqa: E402, F401

_REAL_INDEX = PROJECT_ROOT / "ml" / "data" / "index" / "kipris.faiss"
FAKE_ML_MODE = bool(os.getenv("MARKLENS_FAKE_ML")) or not _REAL_INDEX.exists()

_EMBED_DIM = 512
_N_RECORDS = 10
_fake_vectors = None  # numpy 배열 (지연 생성)

# 상품↔유사군 변환표 픽스처(10건). 제35류 병합 항목 2건은 원 명칭 aliases 6개씩 —
# test_goods_api.py 가 검색·alias 적중·류 필터를 이 내용으로 단언한다. 가짜 모드에서 매 TestClient
# 기동마다 실제 91,591건 파일을 읽지 않게 하는 목적도 있다(lifespan 이 항상 변환표를 적재한다).
_CLASS35_SUFFIXES = ("도매업", "소매업", "중개업", "판매대행업", "판매알선업", "구매대행업")


def _class35_entry(base: str, code: str) -> dict:
    return {
        "name": f"{base} 판매업(도소매·중개·대행)",
        "nice_class": 35,
        "similarity_codes": [code],
        "aliases": [f"{base} {suffix}" for suffix in _CLASS35_SUFFIXES],
    }


_GOODS_MAP_FIXTURE = [
    {"name": "화장품", "nice_class": 3, "similarity_codes": ["G1201", "S120907", "S128302"]},
    _class35_entry("화장품", "S2012"),
    {"name": "화장품용 스펀지", "nice_class": 21, "similarity_codes": ["G4001"]},
    {"name": "기능성 화장품", "nice_class": 3, "similarity_codes": ["G1201"]},
    {"name": "커피", "nice_class": 30, "similarity_codes": ["G0502"]},
    _class35_entry("커피", "S2039"),
    {"name": "의류", "nice_class": 25, "similarity_codes": ["G430301", "G450101"]},
    {"name": "신발", "nice_class": 25, "similarity_codes": ["G4503"]},
    {"name": "장갑", "nice_class": 25, "similarity_codes": ["G4501"]},
    {"name": "장갑", "nice_class": 28, "similarity_codes": ["G5701"]},
]


def _build_fake_ml_env(base: Path) -> None:
    """임시 디렉토리에 인덱스/메타/이미지로 구성된 완전한 가짜 ML 데이터셋 생성."""
    import faiss
    import numpy as np
    from PIL import Image

    global _fake_vectors
    rng = np.random.default_rng(42)
    vecs = rng.standard_normal((_N_RECORDS, _EMBED_DIM)).astype("float32")
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    _fake_vectors = vecs

    index = faiss.IndexFlatIP(_EMBED_DIM)
    index.add(vecs)

    index_dir = base / "index"
    images_dir = base / "images"
    index_dir.mkdir(parents=True)
    images_dir.mkdir(parents=True)

    filenames = [f"40202100000{i + 1:02d}.png" for i in range(_N_RECORDS)]
    for name in filenames:
        Image.new("RGB", (64, 64), (200, 40, 40)).save(images_dir / name)

    faiss.write_index(index, str(index_dir / "kipris.faiss"))
    (index_dir / "kipris_metadata.json").write_text(
        json.dumps(
            {"image_paths": filenames, "total_images": _N_RECORDS, "failed_count": 0},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # 상표 메타: 마지막 1건은 고의 누락 → trademark: null 경로 계약 검증용
    trademarks = [
        {
            "출원번호": name.removesuffix(".png"),
            "등록번호": None,
            "출원일자": "2021-04-05",
            "등록일자": "2023-10-26",
            "상표한글명": f"더미상표{i + 1}",
            "상표영문명": f"DUMMY {i + 1}",
            "상표구분": "도형복합",
            "출원인": "테스트 출원인",
            "최종권리자": "테스트 출원인",
            "비엔나코드": ["점"],
            "류": [35],
            "유사군": ["S0101"],
            "이미지파일": name,
        }
        for i, name in enumerate(filenames[:-1])
    ]
    (base / "kipris_metadata.json").write_text(
        json.dumps(
            {
                "dataset_info": {
                    "총_상표수": len(trademarks),
                    "출원일자_범위": "2021 ~ 2026",
                    "데이터_기준": "합성 더미 데이터 (테스트 픽스처)",
                    "생성일자": "2026-07-08",
                },
                "trademarks": trademarks,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (base / "goods_map.json").write_text(
        json.dumps(_GOODS_MAP_FIXTURE, ensure_ascii=False), encoding="utf-8"
    )


def pytest_configure(config):
    """테스트 모듈들이 backend.src.core.{paths,config} 를 import 하기 전에
    가짜 ML 환경 변수를 심는다 (paths/config 는 import 시점에 env 를 읽는다)."""
    # 계약 테스트 전체가 한 IP(TestClient)로 실행되므로 운영용 10/minute 제한이
    # 테스트 순서에 따라 누적되지 않도록 충분히 높은 테스트 전용 한도를 사용한다.
    os.environ["MARKLENS_SEARCH_RATELIMIT"] = "10000/minute"
    os.environ["MARKLENS_NAMECHECK_RATELIMIT"] = "10000/minute"

    if not FAKE_ML_MODE:
        return
    base = Path(tempfile.mkdtemp(prefix="marklens_fake_ml_"))
    _build_fake_ml_env(base)
    os.environ["MARKLENS_DATA_DIR"] = str(base)
    os.environ["MARKLENS_IMAGES_DIR"] = str(base / "images")
    os.environ["MARKLENS_GOODS_MAP_PATH"] = str(base / "goods_map.json")
    os.environ["DATABASE_URL"] = ""  # 가짜 모드는 항상 file 모드로


@pytest.fixture(scope="session")
def fake_ml_mode() -> bool:
    """현재 테스트 실행이 가짜 ML 모드인지 여부.

    실모드/가짜모드에서 서로 다른 단언이 필요한 테스트(예: 완전 동일 이미지
    쿼리 구성, 더미 전용 메타 누락 케이스)가 분기 조건으로 사용한다.
    """
    return FAKE_ML_MODE


@pytest.fixture(scope="session", autouse=True)
def _fake_encode_image():
    """가짜 모드에서 CLIP 인코딩을 결정적 벡터로 대체.

    engine.load_all() 의 워밍업이 encode_image 를 부르기 전에(autouse, session)
    engine 모듈의 바인딩을 패치한다 → 모델 가중치 다운로드/로딩이 일어나지 않는다.
    항상 인덱스 0번 벡터를 반환하므로 rank1 은 1번 레코드, 유사도는 1.0.
    """
    if not FAKE_ML_MODE:
        yield
        return

    from backend.src.core import engine

    original = engine.encode_image
    engine.encode_image = lambda image: _fake_vectors[0].copy()
    yield
    engine.encode_image = original
