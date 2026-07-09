"""MarkLens 부하 베이스라인 시나리오 (감사보고서 R13).

목적
----
9월 다축 확장(X1 호칭 / X3 관념 / X4 상품 견련성 + 통합 모델) 이전에 현재
백엔드의 응답 시간·처리량을 수치로 고정해 둔다. 확장 후 같은 시나리오를 다시
돌려 p50/p95·RPS 회귀를 잡는 것이 이 파일의 존재 이유다.

시나리오 (감사보고서 R13: "/search 5동시 + /health 1폴링")
----------------------------------------------------------------
- SearchUser    : POST /search — 이미지 업로드 → CLIP 인코딩 + FAISS 검색.
                  CPU 바운드라 처리량은 한 자릿수 RPS 수준. 이게 측정 본체.
- HealthPollUser: GET /health — 로드밸런서/부하테스트가 키 없이 폴링하는 경량
                  엔드포인트. 검색이 이벤트 루프를 막지 않는지(회귀 기준:
                  부하 중 /health p95 < 100ms) 확인용.
locust 의 fixed_count 로 "검색 5 + 헬스 1" 비율을 그대로 재현한다. 기본값은
env 로 조정 가능(MARKLENS_LOCUST_SEARCH_USERS / MARKLENS_LOCUST_HEALTH_USERS).

★★★ 반드시 읽을 것: 레이트리밋이 부하 테스트를 죽인다 ★★★
--------------------------------------------------------------
서버는 R12 하드닝으로 POST /search 에 IP 기준 레이트리밋(기본 10/minute)을 건다
(backend/src/core/ratelimit.py, config.SEARCH_RATE_LIMIT). 부하 테스트는 단일
머신 = 단일 IP 에서 수백~수천 요청을 쏘므로, 기본 한도로 서버를 띄우면 몇 초 만에
전부 429 로 튕겨 나가 측정이 무의미해진다. 429 는 아래 태스크에서 실패로 집계되니
로쿠스트 통계에서 바로 알아챌 수 있게 해 뒀다.

→ 측정용 서버는 반드시 한도를 넉넉히 올려 띄운다 (재배포 없이 env 오버라이드):

    # PowerShell
    $env:MARKLENS_SEARCH_RATELIMIT = "100000/minute"
    # (인증까지 켠 하드닝 서버를 재현하려면 아래도 함께)
    $env:MARKLENS_API_KEY = "<서버와 동일한 키>"
    uvicorn backend.src.main:app

    # 부하 클라이언트(별도 셸) — 서버와 같은 키를 env 로 전달하면 헤더에 자동 부착
    $env:MARKLENS_API_KEY = "<서버와 동일한 키>"
    locust -f backend/tests/perf/locustfile.py --host http://127.0.0.1:8000

  한도를 올리는 것은 어디까지나 "부하테스트 관측을 위한 상향"이며, 운영/시연
  기본값(10/minute)을 바꾸는 것이 아니다. 측정이 끝나면 env 를 원복한다.

인증 (X-API-Key)
----------------
서버가 MARKLENS_API_KEY 를 설정한 하드닝 모드로 떠 있으면 /search·/name-check 는
X-API-Key 헤더가 없으면 401 이다(/health 는 무인증). 이 파일은 클라이언트 쪽
env MARKLENS_API_KEY 가 있으면 모든 요청 헤더에 자동으로 붙여 하드닝 서버에도
그대로 부하를 넣을 수 있게 한다. 서버가 무인증(로컬 기본)이면 env 를 비워 두면 된다.

업로드 픽스처
-------------
업로드 이미지는 ml/data/queries/ 의 기존 브랜드 로고 픽스처를 재사용한다. 파일을
import 시점에 메모리로 한 번만 읽어 디스크 I/O 가 측정에 섞이지 않게 한다. 유효
픽스처가 하나도 없으면 import 단계에서 명확히 실패한다(측정 도중 조용히 400 이
나는 것을 방지).

실행 예 (헤드리스, 5분·정해진 사용자 수)
-----------------------------------------
    locust -f backend/tests/perf/locustfile.py \
        --host http://127.0.0.1:8000 \
        --headless -u 6 -r 2 -t 5m

  -u 6 = 검색 5 + 헬스 1(fixed_count 합). 결과 표(p50/p95/RPS)를
  docs/MarkLens_부하테스트_베이스라인.md 의 기록 템플릿에 옮겨 적는다.

주의: 이 파일은 pytest 수집 대상이 아니다. pytest 는 test_*.py / *_test.py 만
수집하므로 locustfile.py 라는 이름 자체로 자연히 제외된다(별도 설정 불필요).
"""

import os
import random
from pathlib import Path

from locust import HttpUser, between, task

# --------------------------------------------------------------------
# 경로 · 픽스처 로딩 (import 시점 1회)
# --------------------------------------------------------------------

# 이 파일: backend/tests/perf/locustfile.py → parents[3] 가 저장소 루트.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_QUERIES_DIR = _REPO_ROOT / "ml" / "data" / "queries"

# 부하에 사용할 브랜드 로고 픽스처(선호 순). queries/ 에는 검증 실패용 음성
# 픽스처(empty.bin·notimg.bin·tiny.png 등)도 섞여 있으므로, 검색이 실제로 통과할
# 정상 이미지만 화이트리스트로 골라 쓴다. 여기 없는 것이 있어도 존재하는 것만 쓴다.
_PREFERRED_FIXTURES = (
    "adidas.png",
    "apple.png",
    "chanel.png",
    "lacoste.png",
    "nike.png",
    "starbucks.png",
)


def _load_query_images() -> list[tuple[str, bytes]]:
    """queries/ 의 선호 픽스처를 (파일명, 바이트)로 메모리에 적재.

    유효 픽스처가 하나도 없으면 RuntimeError 로 즉시 실패한다 — 측정 도중 매
    요청이 조용히 400/404 로 빠지는 것보다, 시작 시점에 크게 실패하는 편이 낫다.
    """
    images: list[tuple[str, bytes]] = []
    for name in _PREFERRED_FIXTURES:
        path = _QUERIES_DIR / name
        if path.is_file() and path.stat().st_size > 0:
            images.append((name, path.read_bytes()))

    if not images:
        raise RuntimeError(
            "부하용 업로드 픽스처를 찾지 못했습니다. "
            f"다음 경로에 브랜드 로고 PNG 가 있어야 합니다: {_QUERIES_DIR}\n"
            f"기대 파일(하나 이상): {', '.join(_PREFERRED_FIXTURES)}"
        )
    return images


# import 시점에 적재 → 픽스처 부재는 locust 기동 즉시 드러난다.
_QUERY_IMAGES = _load_query_images()

# 클라이언트 쪽 API 키(있으면 하드닝 서버에 헤더로 붙인다).
_API_KEY = os.getenv("MARKLENS_API_KEY", "").strip()

# 시나리오 비율 — 감사보고서 R13 기본(검색 5 + 헬스 1). env 로 조정 가능.
_SEARCH_USERS = int(os.getenv("MARKLENS_LOCUST_SEARCH_USERS", "5"))
_HEALTH_USERS = int(os.getenv("MARKLENS_LOCUST_HEALTH_USERS", "1"))


# --------------------------------------------------------------------
# 사용자 클래스
# --------------------------------------------------------------------


class SearchUser(HttpUser):
    """POST /search 를 반복하는 검색 사용자 (측정 본체, CPU 바운드)."""

    # "검색 5동시" — 총 사용자 수와 무관하게 정확히 이 수만큼 스폰된다.
    fixed_count = _SEARCH_USERS
    # 사용자 사고시간(think time). 서버 CapacityLimiter(기본 2)와 레이트리밋이
    # 병목이므로 과하게 몰아치기보다 현실적 간격을 둔다. 필요 시 조정.
    wait_time = between(1, 3)

    def on_start(self) -> None:
        # 하드닝 서버(MARKLENS_API_KEY 설정)에도 부하가 들어가도록 키를 세션
        # 기본 헤더에 심는다. 키가 없으면(로컬 무인증) 아무 헤더도 붙지 않는다.
        if _API_KEY:
            self.client.headers["X-API-Key"] = _API_KEY

    @task
    def search(self) -> None:
        name, data = random.choice(_QUERY_IMAGES)
        # multipart 필드명은 API 계약상 반드시 "file".
        files = {"file": (name, data, "image/png")}
        # name= 로 통계 라벨을 고정(파일명이 달라도 한 줄로 집계).
        with self.client.post(
            "/search",
            files=files,
            name="POST /search",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 429:
                # 레이트리밋이 켜진 채 측정 중 — 결과가 무효다. 파일 상단 안내대로
                # MARKLENS_SEARCH_RATELIMIT 를 올려 서버를 다시 띄워야 한다.
                resp.failure(
                    "429 레이트리밋 — MARKLENS_SEARCH_RATELIMIT 를 올려 재측정하세요"
                )
            elif resp.status_code == 401:
                resp.failure(
                    "401 인증 실패 — 클라이언트/서버 MARKLENS_API_KEY 가 일치해야 합니다"
                )
            elif resp.status_code == 503:
                # 엔진 미준비/빈 인덱스 — 데이터 적재 후 측정.
                resp.failure("503 서비스 불가 — 엔진 미준비 또는 인덱스가 비어 있음")
            else:
                resp.failure(f"예상치 못한 상태 코드: {resp.status_code}")


class HealthPollUser(HttpUser):
    """GET /health 를 폴링하는 경량 사용자 (부하 중 응답성 관측용)."""

    # "헬스 1폴링".
    fixed_count = _HEALTH_USERS
    # 로드밸런서 헬스체크에 준하는 짧은 간격.
    wait_time = between(0.5, 1)

    @task
    def health(self) -> None:
        # /health 는 무인증 — 키 헤더 불필요. 200 이 아니면 실패로 집계.
        with self.client.get("/health", name="GET /health", catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"예상치 못한 상태 코드: {resp.status_code}")
