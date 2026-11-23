"""부하 점검 — 같은 요청 동시 다발(동시 실행 상한·서버 멈춤 여부)과 서로 다른 긴 이름 수천 건(캐시
상한·메모리 증가가 멈추는지). 서버 메모리는 uvicorn·node 프로세스의 RSS 를 ps 로 잰다.

    ml/venv/bin/python scripts/robustness/probe_load.py [--out DIR] [--names 2000] [--skip-burst]
        [--skip-churn] [--repeat-big N]   # 결과는 probe_load.json 에 키 단위로 합침
결과: DIR/probe_load.json. 한도가 상향된 백엔드 8000·프런트 3000 을 쓴다(servers.sh start).
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import requests

API = "http://127.0.0.1:8000"
BFF = "http://127.0.0.1:3000"
SYLLABLES = list(
    "가나다라마바사아자차카타파하고노도로모보소오조초코토포호구누두루무부수우주추쿠투푸후"
)
WORDS = [
    "블루",
    "골든",
    "하늘",
    "바다",
    "커피",
    "베이커리",
    "STAR",
    "MOON",
    "LUCKY",
    "GREEN",
    "숲",
    "별빛",
    "KITCHEN",
    "HOUSE",
    "마을",
    "정원",
    "BEAR",
    "FOX",
    "노을",
    "햇살",
]


def rss_mb(pid: int) -> float | None:
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=True
        ).stdout.strip()
        return round(int(out) / 1024, 1)
    except (subprocess.CalledProcessError, ValueError):
        return None


def percentiles(values: list[float]) -> dict:
    if not values:
        return {}
    ordered = sorted(values)
    pick = lambda q: ordered[min(len(ordered) - 1, int(q * len(ordered)))]  # noqa: E731
    return {
        "n": len(values),
        "중앙": round(statistics.median(values), 3),
        "95%": round(pick(0.95), 3),
        "최대": round(ordered[-1], 3),
    }


def post(base: str, key: str, files: list, timeout: float = 120) -> tuple[int | None, float]:
    headers = {"X-API-Key": key} if base == API else {"x-turnstile-token": f"ok-{uuid.uuid4()}"}
    path = "/search/v2" if base == API else "/api/search/v2"
    started = time.perf_counter()
    try:
        response = requests.post(f"{base}{path}", files=files, headers=headers, timeout=timeout)
        return response.status_code, time.perf_counter() - started
    except requests.RequestException:
        return None, time.perf_counter() - started


def burst(label: str, base: str, key: str, files: list, count: int, pids: dict) -> dict:
    """동시 count 건 + 그동안 /health 지연을 0.2초마다."""
    health: list[float] = []
    peak = {name: rss_mb(pid) for name, pid in pids.items()}
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            started = time.perf_counter()
            try:
                requests.get(f"{API}/health", timeout=10)
            except requests.RequestException:
                pass
            health.append(time.perf_counter() - started)
            for name, pid in pids.items():
                value = rss_mb(pid)
                if value is not None and (peak[name] is None or value > peak[name]):
                    peak[name] = value
            time.sleep(0.2)

    poller = threading.Thread(target=poll, daemon=True)
    before = {name: rss_mb(pid) for name, pid in pids.items()}
    poller.start()
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=count) as pool:
        results = list(pool.map(lambda _: post(base, key, files), range(count)))
    wall = time.perf_counter() - started
    stop.set()
    poller.join()
    statuses: dict[str, int] = {}
    for status, _ in results:
        statuses[str(status)] = statuses.get(str(status), 0) + 1
    out = {
        "이름": label,
        "건수": count,
        "벽시계_s": round(wall, 1),
        "상태": statuses,
        "지연_s": percentiles([t for _, t in results]),
        "health_지연_s": percentiles(health),
        "RSS_전_MB": before,
        "RSS_최고_MB": peak,
        "RSS_후_MB": {name: rss_mb(pid) for name, pid in pids.items()},
    }
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return out


def long_names(count: int, seed: int = 0) -> list[str]:
    rng = random.Random(seed)
    names = set()
    while len(names) < count:
        parts = []
        while sum(len(p) + 1 for p in parts) < rng.randint(60, 98):
            parts.append(
                rng.choice(WORDS)
                if rng.random() < 0.4
                else "".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 5)))
            )
        names.add(" ".join(parts)[:100])
    return sorted(names)


def churn(key: str, count: int, pids: dict, workers: int = 4) -> dict:
    names = long_names(count)
    samples = [{"건": 0, **{name: rss_mb(pid) for name, pid in pids.items()}}]
    latencies: list[float] = []
    statuses: dict[str, int] = {}
    lock = threading.Lock()
    done = [0]

    def one(name: str):
        status, elapsed = post(API, key, [("name", (None, name))])
        with lock:
            latencies.append(elapsed)
            statuses[str(status)] = statuses.get(str(status), 0) + 1
            done[0] += 1
            if done[0] % 100 == 0:
                sample = {
                    "건": done[0],
                    **{n: rss_mb(pid) for n, pid in pids.items()},
                    "최근100_중앙_s": round(statistics.median(latencies[-100:]), 3),
                }
                samples.append(sample)
                print(json.dumps(sample, ensure_ascii=False), flush=True)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, names))
    out = {
        "이름": f"서로 다른 긴 이름 {count}건(동시 {workers})",
        "벽시계_s": round(time.perf_counter() - started, 1),
        "상태": statuses,
        "지연_s": percentiles(latencies),
        "RSS_추이": samples,
    }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path.home() / "marklens-archive" / f"robustness-{date.today():%Y%m%d}",
    )
    parser.add_argument("--names", type=int, default=2000)
    parser.add_argument("--skip-burst", action="store_true")
    parser.add_argument("--skip-churn", action="store_true")
    parser.add_argument(
        "--repeat-big",
        type=int,
        default=0,
        help="9.7MB 이미지 20건 동시를 N번 더 — 중계 서버 메모리가 돌아오는지",
    )
    args = parser.parse_args()
    key = (args.out / "api_key").read_text(encoding="utf-8").strip()
    pids = {
        name: int((args.out / f"{name}.pid").read_text().strip())
        for name in ("backend", "frontend")
    }
    images = args.out / "images"
    ok = [("image", ("ok.png", (images / "ok.png").read_bytes(), "image/png"))]
    big = [("image", ("near_10mb.png", (images / "near_10mb.png").read_bytes(), "image/png"))]
    result: dict = {"pids": pids}
    if not args.skip_burst:
        result["동시"] = [
            burst("API 직접 — 같은 이미지 30건 동시", API, key, ok, 30, pids),
            burst(
                "중계 경유 — 같은 이미지 + 이름 30건 동시",
                BFF,
                key,
                ok + [("name", (None, "블루커피"))],
                30,
                pids,
            ),
            burst("중계 경유 — 9.7MB 이미지 20건 동시", BFF, key, big, 20, pids),
        ]
    if args.repeat_big:
        result["큰_이미지_반복"] = [
            burst(
                f"중계 경유 — 9.7MB 이미지 20건 동시 ({i + 1}/{args.repeat_big})",
                BFF,
                key,
                big,
                20,
                pids,
            )
            for i in range(args.repeat_big)
        ]
    if not args.skip_churn:
        result["캐시"] = churn(key, args.names, pids)
    path = args.out / "probe_load.json"
    merged = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    merged.update(result)  # 부분 실행(--skip-burst 등)이 앞선 결과를 지우지 않게 키 단위로 합친다
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"→ {args.out / 'probe_load.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
