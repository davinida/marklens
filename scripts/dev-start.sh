#!/usr/bin/env bash
# MarkLens dev 통합 시작 (macOS/Linux)
#
# 백엔드(uvicorn --reload, 8000) + 프론트(Next.js dev, 3000)를 백그라운드로
# 띄우고 /health 가 engine_ready 될 때까지 기다린다. 로그는 scripts/*.log.
#
# 사용:
#   ./scripts/dev-start.sh            # 기본
#   ./scripts/dev-start.sh --force    # 포트 점유 프로세스 종료 후 진행
# 종료: ./scripts/dev-stop.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS_DIR="$REPO_ROOT/scripts"
PID_FILE="$SCRIPTS_DIR/.dev-pids"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"  # CLIP 로딩 대기 (여유 메모리 ~4.5GB)
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

port_pids() { lsof -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null || true; }

# ---- 1) 포트 선점 검사 ----
for port in 8000 3000; do
    pids="$(port_pids "$port")"
    if [ -n "$pids" ]; then
        if [ "$FORCE" = 1 ]; then
            echo "[dev-start] 포트 $port 점유 프로세스 종료 (PID: $pids)"
            kill -9 $pids 2>/dev/null || true
        else
            echo "[dev-start] 포트 $port 가 이미 사용 중입니다 (PID: $pids)."
            echo "            ./scripts/dev-stop.sh 로 정리하거나 --force 를 사용하세요."
            exit 1
        fi
    fi
done

# ---- 2) 백엔드 기동 (저장소 루트에서, ml venv 공유 — README §6-6) ----
PYTHON="$REPO_ROOT/ml/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "[오류] ml/venv 가 없습니다. README §6-4 대로 가상환경을 먼저 만드세요."
    exit 1
fi
echo "[dev-start] 백엔드 기동 중... (로그: scripts/backend.log)"
(cd "$REPO_ROOT" && nohup "$PYTHON" -m uvicorn backend.src.main:app --reload \
    > "$SCRIPTS_DIR/backend.log" 2>&1 &
 echo $! > "$PID_FILE.backend")
BACKEND_PID="$(cat "$PID_FILE.backend")"

# ---- 3) /health 폴링 ----
ready=0
for _ in $(seq 1 $((HEALTH_TIMEOUT / 2))); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "[오류] 백엔드가 기동 중 종료됐습니다 — scripts/backend.log 확인."
        exit 1
    fi
    if curl -sf "http://127.0.0.1:8000/health" | grep -q '"engine_ready":true'; then
        ready=1; break
    fi
    sleep 2
done
if [ "$ready" != 1 ]; then
    echo "[오류] ${HEALTH_TIMEOUT}초 안에 /health 가 준비되지 않았습니다. scripts/backend.log 확인."
    exit 1
fi
echo "[dev-start] 백엔드 준비 완료."

# ---- 4) 프론트 기동 ----
cd "$REPO_ROOT/frontend"
if [ ! -d node_modules ]; then
    echo "[dev-start] frontend/node_modules 없음 — npm install (최초 1회)..."
    npm install
fi
echo "[dev-start] 프론트 기동 중... (로그: scripts/frontend.log)"
nohup npm run dev > "$SCRIPTS_DIR/frontend.log" 2>&1 &
echo $! > "$PID_FILE.frontend"

echo ""
echo "=========================================="
echo " MarkLens dev 환경 기동 완료"
echo "  백엔드  : http://127.0.0.1:8000  (docs: /docs, PID $BACKEND_PID)"
echo "  프론트  : http://localhost:3000  (PID $(cat "$PID_FILE.frontend"))"
echo "  종료    : ./scripts/dev-stop.sh"
echo "=========================================="
