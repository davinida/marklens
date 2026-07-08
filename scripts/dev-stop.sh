#!/usr/bin/env bash
# MarkLens dev 통합 종료 (macOS/Linux)
#
# dev-start.sh 가 기록한 PID 파일을 우선 사용하고, 포트 8000/3000 리스너를
# 폴백으로 정리한다 (uvicorn --reload 워커 등 잔존 프로세스 대응).
#
# 사용: ./scripts/dev-stop.sh

set -uo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPTS_DIR/.dev-pids"
killed=""

port_pids() { lsof -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null || true; }

# ---- 1) PID 파일 기반 종료 ----
for name in backend frontend; do
    f="$PID_FILE.$name"
    if [ -f "$f" ]; then
        pid="$(cat "$f")"
        if kill -0 "$pid" 2>/dev/null; then
            # 자식 프로세스(리로더 워커, next 서버)까지 함께 종료
            pkill -9 -P "$pid" 2>/dev/null || true
            kill -9 "$pid" 2>/dev/null || true
            killed="$killed $name(PID $pid)"
        fi
        rm -f "$f"
    fi
done

# ---- 2) 포트 기반 폴백 ----
for port in 8000 3000; do
    for pid in $(port_pids "$port"); do
        cmd="$(ps -p "$pid" -o comm= 2>/dev/null || true)"
        case "$cmd" in
            *python*|*node*|*npm*)
                kill -9 "$pid" 2>/dev/null || true
                killed="$killed 포트$port($cmd, PID $pid)"
                ;;
            *)
                echo "[dev-stop] 포트 $port 점유 PID $pid ($cmd) 는 python/node 가 아니라 건너뜁니다."
                ;;
        esac
    done
done

if [ -n "$killed" ]; then
    echo "[dev-stop] 종료됨:$killed"
else
    echo "[dev-stop] 실행 중인 dev 프로세스가 없습니다."
fi

# ---- 3) 포트 해제 확인 ----
sleep 1
for port in 8000 3000; do
    if [ -n "$(port_pids "$port")" ]; then
        echo "[주의] 포트 $port 가 아직 점유 중입니다."
    else
        echo "[dev-stop] 포트 $port 해제 확인."
    fi
done
