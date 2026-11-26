#!/usr/bin/env bash
# 견고성·보안 점검용 로컬 서버(서비스 코드는 고치지 않는다).
#   백엔드 8000  — 실제 모델, X-API-Key 켬, 검색·이미지 등 한도는 환경 변수로만 상향(점검용)
#   백엔드 8001  — 같은 설정에 한도만 기본값(한도 항목 점검용, --default-limits 일 때만)
#   프런트 3000  — 프로덕션 빌드(next build → .next/standalone/server.js), Turnstile 검증은
#                  mock_turnstile_fetch.cjs 로 로컬 모의(외부 호출 0), 백엔드 8000 에 중계
# KIPRIS 는 키를 빈 값으로 띄워 부르지 않는다(.env 는 이미 있는 환경 변수를 덮지 않는다).
#
#   bash scripts/robustness/servers.sh start [--default-limits] [--no-build]
#   bash scripts/robustness/servers.sh start-extra   # 3001→8001(기본 한도)·3002→8009(꺼진 백엔드)
#   bash scripts/robustness/servers.sh stop
#   bash scripts/robustness/servers.sh status
# 출력(로그·PID·임시 API 키)은 ROBUSTNESS_OUT(기본 ~/marklens-archive/robustness-YYYYMMDD) 아래.
# ROBUSTNESS_RISK_MODEL=<계수 JSON 경로> 를 주면 백엔드를 그 모델로 띄운다(전·후 비교용 — 예:
# shared/model/risk_model_v1.4.6.json 으로 띄우면 유명 상표 확인 없이 예전처럼 동작). 없으면 기본 모델.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${ROBUSTNESS_OUT:-$HOME/marklens-archive/robustness-$(date +%Y%m%d)}"
mkdir -p "$OUT/logs"
KEY_FILE="$OUT/api_key"
if [ ! -s "$KEY_FILE" ]; then  # 점검용 임시 키(로컬에서만 씀 — 화면에 찍지 않는다)
  "$ROOT/ml/venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(36), end='')" > "$KEY_FILE"
fi
KEY="$(cat "$KEY_FILE")"
RAISED=(MARKLENS_SEARCH_RATELIMIT=6000/minute MARKLENS_NAMECHECK_RATELIMIT=6000/minute
        MARKLENS_IMAGES_RATELIMIT=60000/minute MARKLENS_PHONETIC_RATELIMIT=6000/minute
        MARKLENS_X3_RATELIMIT=6000/minute MARKLENS_GOODS_RATELIMIT=6000/minute)
COMMON=(KIPRIS_ACCESS_KEY= KIPRIS_TRIAL_ACCESS_KEY= MARKLENS_API_KEY="$KEY")

wait_http() {  # 주소가 200 을 줄 때까지(최대 $2 초)
  local url="$1" limit="${2:-180}" waited=0
  until curl -fs -o /dev/null --max-time 3 "$url"; do
    sleep 2; waited=$((waited + 2))
    if [ "$waited" -ge "$limit" ]; then echo "시간 초과: $url" >&2; return 1; fi
  done
}

start_backend() {  # 포트, 로그 이름, 한도 상향 여부
  local port="$1" log="$2" raised="$3"
  local envs=("${COMMON[@]}")
  if [ "$raised" = "1" ]; then envs+=("${RAISED[@]}"); fi
  if [ -n "${ROBUSTNESS_RISK_MODEL:-}" ]; then envs+=(MARKLENS_RISK_MODEL="$ROBUSTNESS_RISK_MODEL"); fi
  (cd "$ROOT" && env -u MARKLENS_RISK_MODEL "${envs[@]}" nohup "$ROOT/ml/venv/bin/python" -m uvicorn \
    backend.src.main:app --host 127.0.0.1 --port "$port" > "$OUT/logs/$log.log" 2>&1 & echo $! > "$OUT/$log.pid")
  wait_http "http://127.0.0.1:$port/health" 300
  lsof -ti "tcp:$port" -sTCP:LISTEN | head -1 > "$OUT/$log.pid"  # 실제 uvicorn 프로세스(메모리 측정용)
  echo "백엔드 $port 준비(PID $(cat "$OUT/$log.pid"), 로그 $OUT/logs/$log.log)"
}

start_frontend() {
  local build="$1"
  local dir="$ROOT/frontend"
  if [ "$build" = "1" ]; then
    (cd "$dir" && NEXT_PUBLIC_TURNSTILE_SITE_KEY=1x00000000000000000000AA npx next build > "$OUT/logs/frontend_build.log" 2>&1)
    rm -rf "$dir/.next/standalone/.next/static" "$dir/.next/standalone/public"
    cp -R "$dir/.next/static" "$dir/.next/standalone/.next/static"
    cp -R "$dir/public" "$dir/.next/standalone/public"
  fi
  (cd "$dir/.next/standalone" && env PORT=3000 HOSTNAME=127.0.0.1 NODE_ENV=production \
    MARKLENS_BACKEND_URL=http://127.0.0.1:8000 MARKLENS_BACKEND_API_KEY="$KEY" \
    MARKLENS_TURNSTILE_SECRET_KEY=robustness-dummy-secret MARKLENS_TURNSTILE_SITE_KEY=1x00000000000000000000AA \
    MARKLENS_TURNSTILE_EXPECTED_HOSTNAMES=localhost ROBUSTNESS_TURNSTILE_LOG="$OUT/logs/turnstile.jsonl" \
    NODE_OPTIONS="--require $ROOT/scripts/robustness/mock_turnstile_fetch.cjs" \
    nohup node server.js > "$OUT/logs/frontend.log" 2>&1 & echo $! > "$OUT/frontend.pid")
  wait_http "http://127.0.0.1:3000/api/health" 120
  lsof -ti tcp:3000 -sTCP:LISTEN | head -1 > "$OUT/frontend.pid"
  echo "프런트 3000 준비(PID $(cat "$OUT/frontend.pid"), 로그 $OUT/logs/frontend.log)"
}

start_extra() {  # 3001 → 기본 한도 백엔드 8001(429 화면), 3002 → 아무도 없는 8009(백엔드 꺼짐 화면)
  local dir="$ROOT/frontend/.next/standalone" port backend
  for pair in "3001:8001" "3002:8009"; do
    port="${pair%%:*}"; backend="${pair##*:}"
    (cd "$dir" && env PORT="$port" HOSTNAME=127.0.0.1 NODE_ENV=production \
      MARKLENS_BACKEND_URL="http://127.0.0.1:$backend" MARKLENS_BACKEND_API_KEY="$KEY" \
      MARKLENS_TURNSTILE_SECRET_KEY=robustness-dummy-secret MARKLENS_TURNSTILE_SITE_KEY=1x00000000000000000000AA \
      MARKLENS_TURNSTILE_EXPECTED_HOSTNAMES=localhost ROBUSTNESS_TURNSTILE_LOG="$OUT/logs/turnstile_$port.jsonl" \
      NODE_OPTIONS="--require $ROOT/scripts/robustness/mock_turnstile_fetch.cjs" \
      nohup node server.js > "$OUT/logs/frontend_$port.log" 2>&1 &)
    wait_http "http://127.0.0.1:$port/api/turnstile-config" 60
    lsof -ti "tcp:$port" -sTCP:LISTEN | head -1 > "$OUT/frontend_$port.pid"
    echo "프런트 $port 준비 → 백엔드 $backend"
  done
}

stop_all() {
  for name in frontend frontend_3001 frontend_3002 backend backend_default; do
    if [ -s "$OUT/$name.pid" ]; then
      kill "$(cat "$OUT/$name.pid")" 2>/dev/null || true
      rm -f "$OUT/$name.pid"
    fi
  done
  echo "멈춤"
}

case "${1:-}" in
  start)
    shift
    default_limits=0; build=1
    for arg in "$@"; do
      case "$arg" in
        --default-limits) default_limits=1 ;;
        --no-build) build=0 ;;
      esac
    done
    start_backend 8000 backend 1
    if [ "$default_limits" = "1" ]; then start_backend 8001 backend_default 0; fi
    start_frontend "$build"
    ;;
  start-extra) start_extra ;;
  stop) stop_all ;;
  status)
    for name in frontend backend backend_default; do
      if [ -s "$OUT/$name.pid" ] && kill -0 "$(cat "$OUT/$name.pid")" 2>/dev/null; then
        echo "$name 실행 중(PID $(cat "$OUT/$name.pid"))"
      fi
    done
    ;;
  *) echo "사용: $0 start [--default-limits] [--no-build] | start-extra | stop | status" >&2; exit 2 ;;
esac
