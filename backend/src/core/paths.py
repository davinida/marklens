"""
프로젝트 경로 상수.

backend/src/core/paths.py 의 위치를 기준으로 프로젝트 루트를 동적으로
계산합니다. 현재 작업 디렉토리(cwd)에 의존하지 않으므로, uvicorn을
어디서 띄우든 동일하게 동작합니다.

중요: kipris_metadata.json 이라는 동일한 이름의 파일이 두 곳에 있습니다.
혼동을 막기 위해 절대 같은 변수명으로 다루지 않습니다.

- INDEX_META_PATH      : ml/data/index/kipris_metadata.json
                         build_index.py가 만든 인덱스 메타.
                         FAISS 벡터 순번 ↔ 파일명 매핑이 들어 있음.
- TRADEMARK_META_PATH  : ml/data/kipris_metadata.json
                         Phase 2-D가 만든 상표 상세 정보 메타데이터.
                         출원번호, 상표명, 출원인, 비엔나코드, 류 등.
"""

from pathlib import Path


# backend/src/core/paths.py  →  backend/src/core  →  backend/src  →  backend  →  <project root>
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

# ml 모듈
ML_ROOT: Path = PROJECT_ROOT / "ml"
ML_SRC_DIR: Path = ML_ROOT / "src"

# 데이터 디렉토리
ML_DATA_DIR: Path = ML_ROOT / "data"
IMAGES_DIR: Path = ML_DATA_DIR / "images"

# 인덱스 산출물 (build_index.py)
INDEX_PATH: Path = ML_DATA_DIR / "index" / "kipris.faiss"
INDEX_META_PATH: Path = ML_DATA_DIR / "index" / "kipris_metadata.json"

# 상표 상세 정보 (Phase 2-D 산출물)
TRADEMARK_META_PATH: Path = ML_DATA_DIR / "kipris_metadata.json"
