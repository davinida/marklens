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

import os
from pathlib import Path

# backend/src/core/paths.py  →  backend/src/core  →  backend/src  →  backend  →  <project root>
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

# === .env 로드 ===
# KIPRIS 키/DB 접속 정보는 커밋 금지 정책(.gitignore)에 따라 .env 로 관리한다.
# paths 모듈은 backend 에서 가장 먼저 import 되므로 여기서 1회 로드한다.
# python-dotenv 미설치 환경(구버전 venv)에서도 서버가 죽지 않도록 방어.
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:  # pragma: no cover
    pass

# ml 모듈
ML_ROOT: Path = PROJECT_ROOT / "ml"
ML_SRC_DIR: Path = ML_ROOT / "src"

# 데이터 디렉토리
# 백엔드-3(스토리지 분리) 1단계: 환경변수로 데이터/이미지 위치를 오버라이드할 수
# 있게 한다. 미설정 시 기존 기본값(ml/data)이라 팀원 환경은 그대로 동작한다.
ML_DATA_DIR: Path = Path(os.getenv("MARKLENS_DATA_DIR", str(ML_ROOT / "data")))
IMAGES_DIR: Path = Path(os.getenv("MARKLENS_IMAGES_DIR", str(ML_DATA_DIR / "images")))

# 인덱스 산출물 (build_index.py)
INDEX_PATH: Path = ML_DATA_DIR / "index" / "kipris.faiss"
INDEX_META_PATH: Path = ML_DATA_DIR / "index" / "kipris_metadata.json"
INDEX_MANIFEST_PATH: Path = ML_DATA_DIR / "index" / "kipris_manifest.json"
INDEX_DIRTY_PATH: Path = ML_DATA_DIR / "index" / ".kipris-index-dirty"

# 상표 상세 정보 (Phase 2-D 산출물)
TRADEMARK_META_PATH: Path = ML_DATA_DIR / "kipris_metadata.json"
