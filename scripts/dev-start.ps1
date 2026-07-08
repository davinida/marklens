# MarkLens dev 통합 시작 (Windows)
#
# 백엔드(uvicorn --reload, 포트 8000)와 프론트(Next.js dev, 포트 3000)를
# 각각 새 콘솔 창으로 띄우고, /health 가 engine_ready 될 때까지 기다린다.
#
# 사용:
#   .\scripts\dev-start.ps1              # 기본
#   .\scripts\dev-start.ps1 -Force       # 포트 점유 프로세스를 종료하고 진행
#   .\scripts\dev-start.ps1 -NoBrowser   # 브라우저 자동 열기 생략
#
# 규칙(README §6-6): 백엔드는 반드시 저장소 루트에서 ml\venv 파이썬으로 실행.
# 종료는 .\scripts\dev-stop.ps1

param(
    [switch]$Force,
    [switch]$NoBrowser,
    [int]$HealthTimeoutSec = 180   # CLIP 로딩(여유 메모리 ~4.5GB 필요)이 느릴 수 있음
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$PidFile  = Join-Path $PSScriptRoot ".dev-pids.json"

function Get-PortPids([int]$Port) {
    try {
        @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique)
    } catch { @() }
}

# ---- 1) 포트 선점 검사 ----
foreach ($port in 8000, 3000) {
    $occupied = Get-PortPids $port
    if ($occupied.Count -gt 0) {
        if ($Force) {
            foreach ($p in $occupied) { taskkill /PID $p /T /F 2>$null | Out-Null }
            Write-Host "[dev-start] 포트 $port 점유 프로세스 종료 (PID: $($occupied -join ', '))"
        } else {
            Write-Host "[dev-start] 포트 $port 가 이미 사용 중입니다 (PID: $($occupied -join ', '))."
            Write-Host "            .\scripts\dev-stop.ps1 로 정리하거나 -Force 를 사용하세요."
            exit 1
        }
    }
}

# ---- 2) 백엔드 기동 (저장소 루트에서, ml venv 공유) ----
$Python = Join-Path $RepoRoot "ml\venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "[오류] ml\venv 가 없습니다. README §6-4 대로 가상환경을 먼저 만드세요."
    exit 1
}
Write-Host "[dev-start] 백엔드 기동 중... (uvicorn backend.src.main:app --reload)"
$backend = Start-Process -FilePath $Python `
    -ArgumentList "-m", "uvicorn", "backend.src.main:app", "--reload" `
    -WorkingDirectory $RepoRoot -PassThru

# ---- 3) /health 폴링 (엔진 로딩 대기) ----
$deadline = (Get-Date).AddSeconds($HealthTimeoutSec)
$ready = $false
while ((Get-Date) -lt $deadline) {
    if ($backend.HasExited) {
        Write-Host "[오류] 백엔드 프로세스가 기동 중 종료됐습니다 — 백엔드 창의 로그를 확인하세요."
        Write-Host "       (자주 겪는 원인: 인덱스 미빌드, 메모리 부족 OSError 1455 — README §6-6)"
        exit 1
    }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3
        if ($health.engine_ready) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    Write-Host "[오류] $HealthTimeoutSec 초 안에 /health 가 준비되지 않았습니다. 백엔드 창을 확인하세요."
    exit 1
}
Write-Host "[dev-start] 백엔드 준비 완료 (index=$($health.index_size)건, mode=$($health.storage_mode))"

# ---- 4) 프론트 기동 ----
$FrontendDir = Join-Path $RepoRoot "frontend"
if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Host "[dev-start] frontend\node_modules 없음 — npm install 실행 (최초 1회)..."
    Push-Location $FrontendDir
    npm install
    Pop-Location
}
Write-Host "[dev-start] 프론트 기동 중... (npm run dev)"
$frontend = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "npm run dev" `
    -WorkingDirectory $FrontendDir -PassThru

# ---- 5) PID 기록 (dev-stop 이 사용) ----
@{
    backend  = $backend.Id
    frontend = $frontend.Id
    started  = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
} | ConvertTo-Json | Out-File -FilePath $PidFile -Encoding utf8

# ---- 6) 프론트 응답 대기 (선택적 — Next 첫 컴파일) ----
$frontUp = $false
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    try {
        Invoke-WebRequest -Uri "http://localhost:3000" -TimeoutSec 3 -UseBasicParsing | Out-Null
        $frontUp = $true; break
    } catch { Start-Sleep -Seconds 2 }
}

Write-Host ""
Write-Host "=========================================="
Write-Host " MarkLens dev 환경 기동 완료"
Write-Host "  백엔드  : http://127.0.0.1:8000  (docs: /docs, PID $($backend.Id))"
Write-Host "  프론트  : http://localhost:3000  (PID $($frontend.Id))$(if (-not $frontUp) { '  [아직 컴파일 중일 수 있음]' })"
Write-Host "  종료    : .\scripts\dev-stop.ps1"
Write-Host "=========================================="
if (-not $NoBrowser -and $frontUp) { Start-Process "http://localhost:3000" }
