"""ml 테스트 공통 설정: ml/ 루트를 sys.path에 추가해 `src.*` import를 가능하게 한다.

ml 스크립트들과 동일한 규약 (예: scripts/build_index.py).
"""

import sys
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[1]
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

# macOS Apple Silicon: 테스트 모듈(test_search.py 등)이 faiss 를 torch 보다 먼저 import 하면
# 같은 프로세스의 이후 torch 연산에서 SIGSEGV 가 난다(ml/src/search.py 주석 참조). conftest 는
# 모든 테스트 모듈보다 먼저 로드되므로 여기서 torch 를 선행 import 해 순서를 고정한다.
import torch  # noqa: E402, F401
