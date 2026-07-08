"""
backend 테스트 공통 설정.

실행 (project root 기준):
    ml\\venv\\Scripts\\python.exe -m pytest backend/tests -v

계약 테스트(test_api_contract.py)는 더미 데이터(ml/data)와 CLIP 모델이 필요하다.
없으면 해당 테스트만 skip 되고 순수 단위 테스트는 항상 돈다.
"""

import sys
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가 (backend.src.* / ml sys.path 주입은 engine 이 수행)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
