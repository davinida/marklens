"""ml 테스트 공통 설정: ml/ 루트를 sys.path에 추가해 `src.*` import를 가능하게 한다.

ml 스크립트들과 동일한 규약 (예: scripts/build_index.py).
"""

import sys
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[1]
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))
