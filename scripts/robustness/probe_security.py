"""보안 점검 — 로컬 서버에만 보낸다(servers.sh start --default-limits·start-extra 뒤).

    ml/venv/bin/python scripts/robustness/probe_security.py [--out DIR]

1 검색 한도(사용자별로 세는지·헤더 위조로 피하는지) 2 이미지 경로(/images·/api/images 경로
이동·인코딩·없는 ID) 3 같은 출처·Turnstile(다른 Origin·Referer 없음·위조 토큰) 4 노출
경로(/docs·/openapi.json·내부 파일) 5 보안 헤더·캐시·CORS 6 로그·임시 파일에 남는 입력. 결과:
DIR/probe_security.json. nginx 는 이 Mac 에서 띄울 수 없어 설정 파일만 읽는다(정적 점검 — 실행
확인 못 함).
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
import uuid
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
API, API_DEFAULT = "http://127.0.0.1:8000", "http://127.0.0.1:8001"
BFF, BFF_DEFAULT = "http://127.0.0.1:3000", "http://127.0.0.1:3001"


def token() -> str:
    return f"ok-{uuid.uuid4()}"


def search(
    base: str,
    key: str | None = None,
    headers: dict | None = None,
    name: str = "블루커피",
    tok: str | None = "auto",
) -> requests.Response:
    hdr = dict(headers or {})
    if key:
        hdr["X-API-Key"] = key
    if tok == "auto" and base.endswith(("3000", "3001", "3002")):
        hdr["x-turnstile-token"] = token()
    elif tok not in (None, "auto"):
        hdr["x-turnstile-token"] = tok
    path = "/search/v2" if base.endswith(("8000", "8001")) else "/api/search/v2"
    return requests.post(
        f"{base}{path}",
        files=[("goods_codes", (None, "G0301")), ("name", (None, name))],
        headers=hdr,
        timeout=60,
    )


def wait_window() -> None:
    """slowapi 분 단위 창이 바뀔 때까지(최대 61초)."""
    time.sleep(61 - time.time() % 60)


def check_rate_limits(key: str) -> dict:
    out: dict = {}
    wait_window()
    codes = [search(API_DEFAULT, key).status_code for _ in range(12)]
    out["직접_같은_IP_12건"] = codes
    wait_window()
    spoofed = [
        search(API_DEFAULT, key, {"X-Forwarded-For": f"203.0.113.{i}"}).status_code
        for i in range(15)
    ]
    out["직접_XFF_위조_15건(uvicorn 기본 forwarded_allow_ips=127.0.0.1)"] = spoofed
    wait_window()
    first = [
        search(
            BFF_DEFAULT, None, {"X-Forwarded-For": "198.51.100.1", "X-Real-IP": "198.51.100.1"}
        ).status_code
        for _ in range(10)
    ]
    second = [
        search(
            BFF_DEFAULT, None, {"X-Forwarded-For": "198.51.100.2", "X-Real-IP": "198.51.100.2"}
        ).status_code
        for _ in range(3)
    ]
    out["중계_사용자A_10건"] = first
    out["중계_사용자B_3건(다른 IP 헤더)"] = second
    last = search(BFF_DEFAULT, None)
    out["중계_429_본문"] = (
        last.json().get("detail") if last.status_code == 429 else last.status_code
    )
    return out


IMAGE_PATHS = [
    "4020240111417.png",
    "not_exist_123.png",
    "",
    "..%2F..%2Fbackend%2F.env",
    "../../.env",
    "%2e%2e/%2e%2e/.env",
    "..%252f..%252f.env",
    "a/../../.env",
    "..\\..\\.env",
    "%00.png",
    "4020240111417.png%00.txt",
    "4020240111417.png/",
    "." * 300,
    "%C0%AE%C0%AE/.env",
    "４０２０２４０１１１４１７.png",
]


def check_images(key: str) -> dict:
    rows = []
    for raw in IMAGE_PATHS:
        for base, prefix, headers in (
            (API, "/images/", {"X-API-Key": key}),
            (BFF, "/api/images/", {}),
        ):
            url = f"{base}{prefix}{raw}"
            try:
                response = requests.get(url, headers=headers, timeout=10, allow_redirects=False)
                ctype = response.headers.get("content-type", "")
                rows.append(
                    {
                        "경로": raw[:60],
                        "곳": prefix,
                        "상태": response.status_code,
                        "형식": ctype[:30],
                        "바이트": len(response.content),
                        "env_노출": bool(
                            re.search(rb"(KIPRIS|MARKLENS|SECRET|API_KEY)", response.content)
                        ),
                    }
                )
            except requests.RequestException as exc:
                rows.append({"경로": raw[:60], "곳": prefix, "오류": type(exc).__name__})
    return {"표": rows}


def check_origin() -> dict:
    rows = {}
    rows["다른_Origin_유효토큰"] = search(
        BFF, None, {"Origin": "https://evil.example", "Referer": "https://evil.example/x"}
    ).status_code
    rows["Referer_없음_유효토큰"] = search(BFF, None, {"Origin": ""}).status_code
    rows["토큰_없음"] = search(BFF, None, tok=None).status_code
    rows["거부_토큰"] = search(BFF, None, tok="deny-1").status_code
    rows["다른_호스트_토큰"] = search(BFF, None, tok="wronghost-1").status_code
    rows["다른_action_토큰"] = search(BFF, None, tok="wrongaction-1").status_code
    rows["토큰_3천자"] = search(BFF, None, tok="ok-" + "a" * 3000).status_code
    preflight = requests.options(
        f"{BFF}/api/search/v2",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-turnstile-token",
        },
        timeout=10,
    )
    rows["사전요청(OPTIONS)"] = {
        "상태": preflight.status_code,
        "ACAO": preflight.headers.get("access-control-allow-origin"),
    }
    goods = requests.get(
        f"{BFF}/api/goods/search",
        params={"q": "커피"},
        headers={"Origin": "https://evil.example"},
        timeout=10,
    )
    rows["GET_상품검색_다른_Origin"] = {
        "상태": goods.status_code,
        "ACAO": goods.headers.get("access-control-allow-origin"),
    }
    api_cors = requests.options(
        f"{API}/search/v2",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        timeout=10,
    )
    rows["백엔드_CORS_다른_Origin"] = {
        "상태": api_cors.status_code,
        "ACAO": api_cors.headers.get("access-control-allow-origin"),
    }
    api_cors_ok = requests.options(
        f"{API}/search/v2",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
        timeout=10,
    )
    rows["백엔드_CORS_허용_Origin"] = {
        "상태": api_cors_ok.status_code,
        "ACAO": api_cors_ok.headers.get("access-control-allow-origin"),
    }
    return rows


EXPOSED = [
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/.env",
    "/.git/config",
    "/admin",
    "/debug",
    "/metrics",
    "/api/docs",
    "/api/openapi.json",
    "/server.js",
    "/package.json",
    "/.next/BUILD_ID",
    "/_next/static/../../server.js",
    "/api/health",
    "/api/turnstile-config",
    "/api/name-check",
    "/api/search",
    "/api/search/v1",
]


def check_exposed(key: str) -> dict:
    rows = []
    for path in EXPOSED:
        for base, headers in ((API, {}), (BFF, {})):
            try:
                response = requests.get(
                    f"{base}{path}", headers=headers, timeout=10, allow_redirects=False
                )
                rows.append(
                    {
                        "곳": base[-4:],
                        "경로": path,
                        "상태": response.status_code,
                        "형식": response.headers.get("content-type", "")[:30],
                        "바이트": len(response.content),
                        "요약": re.sub(r"\s+", " ", response.text[:120]),
                    }
                )
            except requests.RequestException as exc:
                rows.append({"곳": base[-4:], "경로": path, "오류": type(exc).__name__})
    return {"표": rows}


def check_headers() -> dict:
    out = {}
    for label, url, method in (
        ("홈", f"{BFF}/", "GET"),
        ("검색 API(BFF)", f"{BFF}/api/search/v2", "POST"),
        ("이미지(BFF)", f"{BFF}/api/images/4020240111417.png", "GET"),
        ("상품 검색(BFF)", f"{BFF}/api/goods/search?q=커피", "GET"),
        ("health(백엔드)", f"{API}/health", "GET"),
    ):
        if method == "POST":
            response = search(BFF, None)
        else:
            response = requests.get(url, timeout=10)
        keep = [
            "content-security-policy",
            "x-content-type-options",
            "x-frame-options",
            "referrer-policy",
            "strict-transport-security",
            "permissions-policy",
            "cross-origin-opener-policy",
            "cache-control",
            "access-control-allow-origin",
            "x-powered-by",
            "server",
            "x-request-id",
        ]
        out[label] = {
            "상태": response.status_code,
            **{k: response.headers.get(k) for k in keep if response.headers.get(k) is not None},
        }
    return out


def check_retention(out_dir: Path, names: list[str]) -> dict:
    logs = {}
    for log in sorted((out_dir / "logs").glob("*.log")):
        text = log.read_text(encoding="utf-8", errors="replace")
        logs[log.name] = {
            "줄": text.count("\n"),
            "입력한_이름": [n for n in names if n in text],
            "Traceback": text.count("Traceback"),
            "경로_노출": len(re.findall(r"/Users/\S+", text)),
            "키_이름": sorted(
                set(re.findall(r"(KIPRIS_\w*KEY|MARKLENS_API_KEY|TURNSTILE_SECRET\w*)", text))
            ),
        }
    tmp = Path(tempfile.gettempdir())
    recent = []
    cutoff = time.time() - 6 * 3600
    for path in tmp.rglob("*"):
        try:
            if (
                path.is_file()
                and path.stat().st_mtime > cutoff
                and path.stat().st_size > 512 * 1024
            ):
                recent.append(
                    {"파일": str(path)[:120], "MB": round(path.stat().st_size / 2**20, 1)}
                )
        except OSError:
            continue
    return {"로그": logs, "임시폴더_큰_새_파일": recent[:20], "임시폴더": str(tmp)}


def nginx_static() -> dict:
    text = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
    compose = (ROOT / "compose.production.yml").read_text(encoding="utf-8")
    return {
        "클라이언트_IP_출처": "X-MarkLens-Client-IP 헤더가 있으면 그 값을, 없으면 $remote_addr"
        if "$http_x_marklens_client_ip" in text
        else "?",
        "검색_한도": re.findall(r"zone=search_per_ip:\S+ rate=(\S+);", text),
        "본문_상한": re.findall(r"client_max_body_size (\S+);", text),
        "보안_헤더_추가": bool(
            re.search(r"add_header (Content-Security|X-Frame|Strict-Transport)", text)
        ),
        "포트_바인드": re.findall(r"MARKLENS_BIND_ADDRESS:-([0-9.]+)", compose),
        "백엔드_공개_포트": "ports" in compose.split("backend:")[1].split("\n  ")[0]
        if "backend:" in compose
        else None,
        "uvicorn": re.findall(
            r"forwarded-allow-ips\", \"(\S+)\"",
            (ROOT / "deploy" / "backend.Dockerfile").read_text(encoding="utf-8"),
        ),
        "판정": "실행 확인 못 함(이 Mac 에 nginx·Docker 없음) — 설정 파일만 읽음",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path.home() / "marklens-archive" / f"robustness-{date.today():%Y%m%d}",
    )
    parser.add_argument("--skip-limits", action="store_true")
    args = parser.parse_args()
    key = (args.out / "api_key").read_text(encoding="utf-8").strip()
    result = {
        "이미지_경로": check_images(key),
        "같은_출처": check_origin(),
        "노출_경로": check_exposed(key),
        "헤더": check_headers(),
        "nginx_정적": nginx_static(),
    }
    if not args.skip_limits:
        result["검색_한도"] = check_rate_limits(key)
    names = [
        "블루커피",
        "ブルーコーヒー",
        "藍色咖啡",
        "<script>alert(1)</script>",
        "멈춤 확인 커피",
        "☕블루커피🍰",
    ]
    result["보관"] = check_retention(args.out, names)
    (args.out / "probe_security.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("이미지_경로", "노출_경로")},
            ensure_ascii=False,
            indent=1,
        )[:6000]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
