# MarkLens

> 상표 이미지의 **출처 혼동(出處混同) 위험**을 다각도로 평가하는 웹 서비스

MarkLens는 사용자가 업로드한 상표 이미지를 기존 등록상표 데이터와 비교하여,
시각적으로 유사한 선행상표를 찾아주고 참고용 위험도 등급을 제공합니다.

본 프로젝트는 건국대학교 컴퓨터공학부 졸업프로젝트로 진행됩니다.

---

## 목차

1. [프로젝트 소개](#1-프로젝트-소개)
2. [프로젝트 현황 (구현 완료 / 구현 예정)](#2-프로젝트-현황)
3. [기술 스택](#3-기술-스택)
4. [시스템 구조](#4-시스템-구조)
5. [프로젝트 폴더 구조](#5-프로젝트-폴더-구조)
6. [설치 및 실행](#6-설치-및-실행)
7. [API 사용 방법](#7-api-사용-방법)
8. [개발 단계 (로드맵)](#8-개발-단계-로드맵)
9. [팀 구성](#9-팀-구성)
10. [데이터 및 문서](#10-데이터-및-문서)

---

## 1. 프로젝트 소개

상표를 새로 출원하려는 사람은 **이미 등록된 상표와 충돌하지 않는지** 미리 확인해야
합니다. 하지만 기존 검색 시스템은 대부분 텍스트(상표명) 기반이라, 글자 없이 도형만으로
이루어진 상표나 그림이 비슷한 상표는 일반 사용자가 직접 찾아내기 어렵습니다.

MarkLens는 이 문제를 두 단계로 접근합니다.

- **(현재 구현)** 업로드한 상표 이미지를 **CLIP 이미지 임베딩**으로 변환하고,
  **FAISS** 벡터 검색으로 시각적으로 가장 닮은 선행상표를 찾아 등급으로 안내합니다.
- **(확장 예정)** 단순한 이미지 유사 검색에 머무르지 않고, **상표법상 유사 판단 기준**
  (호칭·외관·관념의 3요소 + 상품의 견련성)을 반영한 **다축(Multi-Axis) 위험 평가**로
  확장합니다. 최종적으로는 "이 상표가 기존 상표와 혼동될 확률"을 수치로 제시하는 것이
  목표입니다.

즉 MarkLens의 지향점은 *"그림이 비슷한 상표 찾기"*가 아니라
*"법적으로 출처 혼동을 일으킬 위험이 있는 상표를 다각도로 평가하기"*입니다.

> ⚠️ MarkLens가 제공하는 모든 위험도는 **참고용**이며, 실제 상표 등록 가능성에 대한
> 법적 판단을 대체하지 않습니다.

---

## 2. 프로젝트 현황

> 이 섹션은 **"지금 실제로 동작하는 것"**과 **"앞으로 만들 것"**을 명확히 구분합니다.

### ✅ 구현 완료 (현재 동작함)

| 항목 | 내용 | 위치 |
|------|------|------|
| ML 검색 엔진 | OpenCLIP(ViT-B/32)로 이미지를 512차원 벡터로 변환, FAISS 내적 검색으로 유사 이미지 탐색 | `ml/` |
| KIPRIS 실데이터 파이프라인 | 등록상표 공보(PDF)에서 로고 이미지 추출 + 메타데이터(상표명·출원인·비엔나코드·류·유사군 등) 정제, 검색 인덱스 구축 (**100건**) | `ml/scripts/`, `ml/data/` |
| FastAPI 백엔드 | `POST /search`(이미지 업로드 → 유사 상표 + 위험도 반환), `GET /health`(서버·엔진 상태), 결과 이미지 `/images` 정적 서빙. CLIP·인덱스를 서버 시작 시 1회 로딩 | `backend/` |
| 입력 이미지 검증 | 업로드 파일의 형식·크기·치수를 실제 디코딩으로 검증 | `backend/src/core/validation.py` |
| 초기 위험도 등급 | CLIP 시각 유사도 **단일 축**으로 4단계 등급 산출 (주의 필요 / 검토 권장 / 특정 위협 없음 / 비교적 안전) | `ml/src/scoring.py` |
| 프론트엔드 | 이미지 업로드 화면 + **3층 구조 결과 화면**(① 등급·권장 행동 → ② 유사 상표 비교 → ③ 상세 정보). 입력 → 검색중 → 결과 → 오류 4상태, 백엔드 `POST /search` 1차 연동 | `frontend/` |

### 🔜 구현 예정 (아직 없음)

| 항목 | 내용 |
|------|------|
| **다축(Multi-Axis) 위험 평가** | 현재의 시각 유사도(외관) 단일 축을, 상표법 **유사 3요소 + 상품 견련성**의 4개 축으로 확장 |
| ┗ X1 호칭 유사도 | 상표명을 **한글 자모 단위로 분해**한 뒤 변형된 편집 거리로 발음 유사도 계산. 대법원 판례 반영(첫 음절 강세, 외국어의 한글 발음 변환 등) |
| ┗ X2 외관 유사도 | **현재 구현된 CLIP 기반 검색을 그대로 재활용** |
| ┗ X3 관념 유사도 | 상표명의 *의미*를 사전학습 언어모델 임베딩으로 비교 |
| ┗ X4 상품 견련성 | 유사군 코드 집합 간 **자카드(Jaccard) 계수**로 상품 분야 겹침을 연속 수치화 |
| **통계적 위험 확률** | 4개 축 점수를 **로지스틱 회귀**로 결합하고, **특허법원 심결 데이터**로 가중치를 최적화하여 **0~100% 출처 혼동 위험 확률**을 산출 |
| **식별력 없는 상표 필터** | 보통명칭·기술적표장 등 애초에 등록받을 수 없는 표장을 유사 판단 전에 걸러내는 기능 |

### 🔄 초기 계획에서 변경된 점 (방향 전환)

졸업 프로젝트 진행 중 최종 보고서 단계에서 설계 방향이 일부 바뀌었습니다.
아래 항목은 **더 이상 사용하지 않습니다.**

- **OCR(EasyOCR) 폐기** — 결합상표의 문자를 이미지에서 자동 인식하는 대신,
  **사용자가 상표명을 직접 입력**받는 방식으로 변경했습니다(정확도·복잡도 문제).
- **비엔나 코드 기반 자동 분류/검색 제외** — 사용자 입력 부담과 정확도 문제로
  유사 판단 로직에서 제외했습니다. (단, DB 상표의 비엔나코드 데이터 자체는
  메타데이터로 **보존**되어 화면 참고 정보로만 활용)
- **Fabric.js 미사용** — 드로잉 캔버스 도입 계획을 보류했습니다.

---

## 3. 기술 스택

### 현재 사용 중

| 분류 | 기술 |
|------|------|
| 언어 / 런타임 | Python 3.11 |
| 백엔드 | FastAPI, uvicorn, Pydantic v2 |
| 프론트엔드 | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS |
| ML / AI | OpenCLIP (ViT-B/32, `laion2b_s34b_b79k`), PyTorch, FAISS (`faiss-cpu`) |
| 이미지 처리 | Pillow (PIL) |
| 데이터 | KIPRIS 등록상표 공보 (검증 데이터 100건), FAISS 인덱스 파일 + JSON 메타데이터 |
| 시스템 의존성 | poppler (`pdfimages` — KIPRIS PDF 이미지 추출에만 사용) |

### 도입 예정

| 분류 | 기술 | 용도 |
|------|------|------|
| 통계 모델 | 로지스틱 회귀 (예: scikit-learn 계열) | 4개 축 점수 결합 및 가중치 최적화 |
| 언어 모델 | 사전학습 한국어 임베딩 모델 | X3 관념 유사도 계산 |

> 데이터 저장은 **파일/DB 이중 모드**입니다. 기본은 파일 기반(FAISS 인덱스 + JSON)이며,
> `.env`에 `DATABASE_URL`을 설정하면 상표 메타데이터를 PostgreSQL에서 조회합니다(db 모드).
> FAISS 벡터 인덱스는 두 모드 공통으로 파일에 둡니다. (설정·마이그레이션은 §6-6 참조)

---

## 4. 시스템 구조

### 현재 동작 흐름 (구현 완료)

```
이미지 업로드  (POST /search, multipart)
      │
      ▼
입력 검증        형식(PNG/JPEG/WEBP) · 크기(≤10MiB) · 치수(≥32px) 확인
      │
      ▼
이미지 전처리     EXIF 회전 보정 · RGB 변환 · 리사이즈
      │
      ▼
CLIP Image Encoder ──▶ 512차원 임베딩 벡터 (L2 정규화)
      │
      ▼
FAISS 내적 검색   선행상표 인덱스에서 Top-K 추출
      │
      ▼
KIPRIS 메타 결합   매칭된 상표의 상표명·출원인·류·유사군 등 부착
      │
      ▼
4단계 등급 산출   top-1 유사도 + 후보 간 격차로 등급 판정 (scoring)
      │
      ▼
JSON 응답        등급 + Top-K 매칭(이미지 URL 포함) + 데이터셋 정보
```

### 확장 예정: 다축 위험 평가 (미구현)

현재는 위 흐름 중 **"외관(X2)" 한 축**만 위험도에 반영됩니다.
향후 다음과 같이 4개 축을 결합하는 구조로 확장할 예정입니다.

```
                     ┌── X1 호칭   (상표명 → 한글 자모 분해 + 편집 거리)
 상표 이미지          ├── X2 외관   (CLIP 시각 유사도 — ★현재 구현됨)
   +  상표명  ───────┤
 (사용자 입력)        ├── X3 관념   (상표명 의미 → 언어모델 임베딩 비교)
                     └── X4 견련성 (유사군 코드 집합 → 자카드 계수)
                                  │
                                  ▼
                    로지스틱 회귀로 결합 (특허법원 심결 데이터로 가중치 학습)
                                  │
                                  ▼
                       0 ~ 100 %  출처 혼동 위험 확률
```

---

## 5. 프로젝트 폴더 구조

```
marklens/
├── docs/         # 문서 (설계결정기록, 회의록)
├── ml/           # ML 파이프라인 (구현 완료)
│   ├── src/        # 모듈: embedding, preprocess, search, scoring
│   ├── scripts/    # 인덱스 빌드/검색 + KIPRIS 데이터 가공 CLI
│   └── data/       # 원천 데이터·인덱스·이미지 (.gitignore 제외)
├── backend/      # FastAPI 서버 (구현 완료)
│   ├── src/
│   │   ├── main.py     # 앱 진입점 (startup 로딩, CORS, 정적 서빙)
│   │   ├── api/        # 엔드포인트 (health, search)
│   │   ├── core/       # 경로·설정·엔진·입력 검증
│   │   └── schemas/    # Pydantic 응답 모델
│   └── requirements.txt
├── frontend/     # Next.js 16 웹 (구현 완료 — 업로드 + 3층 결과 화면, /search 연동)
└── shared/       # 공통 타입 정의 (예정)
```

---

## 6. 설치 및 실행

> 아래 명령은 모두 **실제로 동작이 확인된** 절차입니다.
> 프론트엔드 실행 방법은 **§6-8**을 참고하세요.

### 6-1. 사전 요구사항

- Python 3.11
- Git
- poppler (`pdfimages` 명령 제공 — KIPRIS PDF 가공 시에만 필요)

### 6-2. 저장소 복제

```bash
git clone https://github.com/[organization]/marklens.git
cd marklens
```

### 6-3. poppler 설치 (KIPRIS 데이터 가공 시에만 필요)

```bash
# macOS (Homebrew)
brew install poppler

# Ubuntu/Debian
sudo apt install poppler-utils

# 설치 확인
pdfimages -v
```

### 6-4. Python 환경 설정 (`ml/venv` 한 개를 백엔드와 공유)

백엔드는 ML 모듈과 동일한 PyTorch/FAISS 스택을 쓰므로 **venv를 따로 만들지 않고
`ml/venv` 하나를 공유**합니다.

```bash
# 1) ML 가상환경 생성 및 의존성 설치
cd ml
python3.11 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2) 같은 venv에 백엔드 패키지 추가 설치 (최초 1회)
pip install -r ../backend/requirements.txt
```

> **환경변수(.env):** KIPRIS 인증키·DB 접속 문자열 등 비밀값은 프로젝트 루트의
> `.env` 파일로 관리합니다(커밋 금지 — `.gitignore` 처리됨). 루트의
> `.env.example`을 복사해 `.env`로 저장하고 필요한 값만 채우면 서버가 자동으로
> 읽습니다. **아무것도 설정하지 않아도 기존과 동일하게 동작합니다.**

> **macOS(Apple Silicon) 참고:** PyTorch와 FAISS가 각각 OpenMP(libomp)를 내장해
> 충돌이 날 수 있어 `KMP_DUPLICATE_LIB_OK=TRUE` 환경변수가 필요합니다.
> 이 값은 인덱스 빌드 스크립트와 백엔드 엔진 코드 내부에서 **자동으로 설정**되므로
> 사용자가 직접 지정하지 않아도 됩니다.

### 6-5. KIPRIS 데이터 준비 및 인덱스 구축

> 원본 KIPRIS 데이터는 저작권상 저장소에 포함되지 않습니다.
> `ml/data/` 하위(원본·이미지·인덱스·메타)는 모두 `.gitignore`로 git에서 제외됩니다.
> 즉, 새로 clone한 환경에서는 아래 절차로 데이터와 인덱스를 먼저 만들어야
> 백엔드가 기동됩니다.

팀 내부 채널로 받은 원본을 다음 위치에 배치합니다.

```
ml/data/raw_kipris/
├── pdfs/            # 상표공보 PDF (파일명 = 출원번호.pdf)
├── gongbo/          # TB_KT10.txt, TB_KT11.txt, TB_KT15.txt, APPLICANT.txt
└── registration/    # LAST_RG_HOLDER.txt
```

그다음 `ml/` 폴더에서 venv를 활성화한 상태로 순서대로 실행합니다.

```bash
cd ml && source venv/bin/activate

# (1) txt 6개 → 통합 메타데이터(ml/data/kipris_metadata.json)
python scripts/build_kipris_metadata.py

# (2) PDF에서 로고 추출 → ml/data/images/*.png
python scripts/extract_kipris_images.py

# (3) 이미지 폴더 → FAISS 인덱스 빌드
#     결과: ml/data/index/kipris.faiss + kipris_metadata.json
python scripts/build_index.py --image-dir data/images --index-name kipris
```

### 6-6. 백엔드 서버 실행 ⚠️ 반드시 프로젝트 루트에서

백엔드는 **반드시 프로젝트 루트(`marklens/`)에서** 실행해야 합니다.
`cd backend` 후 실행하면 `ml/src` 모듈 import가 충돌하여 오류가 납니다.

```bash
# 프로젝트 루트에서:
cd ~/marklens
source ml/venv/bin/activate
uvicorn backend.src.main:app --reload
```

서버가 뜨면 startup 시점에 CLIP 모델·FAISS 인덱스·KIPRIS 메타데이터를
**1회 로딩**하여 메모리에 보관합니다. 기동에 성공하면 다음 주소를 사용할 수 있습니다.

- API 문서(Swagger): <http://127.0.0.1:8000/docs>
- API 문서(ReDoc): <http://127.0.0.1:8000/redoc>
- 헬스체크: <http://127.0.0.1:8000/health>

> **자주 겪는 오류:** `ModuleNotFoundError: No module named 'src.embedding'`
> → `backend` 폴더 안에서 서버를 띄운 경우입니다. 루트에서 위 명령으로 다시 실행하세요.

> **저장소 모드(선택):** `.env`에 `DATABASE_URL`을 설정하면 상표 메타데이터를
> PostgreSQL에서 조회합니다(db 모드). 최초 1회
> `python -m backend.scripts.migrate_json_to_db` 로 JSON 100건을 DB로 옮긴 뒤
> 서버를 재시작하세요. (JSON에 없는 DB 잔존 행까지 정리하려면 `--prune` 옵션을 붙입니다.)
> 설정하지 않으면 기존 JSON 파일 모드로 동작합니다.
> 상세: `docs/MarkLens_작업가이드_백엔드.md`

> **시연·배포 하드닝(선택, 미설정 시 로컬 개발 기본):** `.env`로 다음을 조절할 수 있습니다.
> `MARKLENS_API_KEY`(설정 시 `/search`·`/name-check`에 `X-API-Key` 헤더 일치를 요구, 미설정 시 무인증),
> `MARKLENS_CORS_ORIGINS`(허용 오리진 콤마 목록, 기본 `http://localhost:3000,http://127.0.0.1:3000`),
> `MARKLENS_SEARCH_RATELIMIT`(기본 `10/minute`)·`MARKLENS_NAMECHECK_RATELIMIT`(기본 `30/minute`) 인바운드 레이트리밋.
> `/health`·`/docs`·`/images`는 항상 인증에서 제외됩니다.

#### 서버 중지·포트 정리 (Windows)

터미널에서 직접 띄웠다면 `Ctrl+C`로 중지합니다. 백그라운드로 띄웠거나 터미널을
잃어버린 경우, **포트로 PID를 찾아 종료**합니다.

```powershell
# 8000 포트를 점유한 프로세스(PID) 확인
netstat -ano | findstr :8000

# 해당 PID 종료 (마지막 열의 숫자)
Stop-Process -Id <PID> -Force     # cmd 라면: taskkill /PID <PID> /F
```

- `--reload` 옵션으로 띄웠다면 감시 프로세스와 워커, **프로세스가 2개**일 수
  있습니다. 둘 다 종료해야 포트가 풀립니다.
- `[Errno 10048] address already in use` → 위 방법으로 기존 프로세스를 정리하거나
  `--port 8001`처럼 다른 포트로 실행하세요. (프론트도 동일: 3000 점유 시
  `npm run dev -- -p 3100`)

#### 메모리 부족(오류 1455) 트러블슈팅

CLIP 모델 로딩(인덱스 빌드·검색·서버 기동)에는 **여유 커밋 메모리 약 4.5GB**가
필요합니다. 부족하면 다음 증상이 나타납니다.

| 증상 | 원인·대응 |
|------|-----------|
| `OSError 1455: 페이징 파일이 너무 작습니다` 또는 트레이스백 없이 프로세스 사망 | 커밋 메모리 고갈. 브라우저·IDE·WSL(`wsl --shutdown`) 등을 닫아 여유 확보 후 재시도 |
| PostgreSQL 접속이 갑자기 끊김 (`server closed the connection unexpectedly`) 후 서비스 중지됨 | DB도 같은 원인(1455)으로 죽을 수 있음. 관리자 권한으로 `net start postgresql-x64-16` 재시작 |
| 프론트 `npm run dev`가 `VirtualAlloc failed`로 즉사 | `set NODE_OPTIONS=--max-old-space-size=768` 후 재실행 |
| 근본 해결 | 페이지파일을 "시스템이 관리"로 변경(제어판 → 고급 시스템 설정 → 성능 → 가상 메모리) 후 재부팅 |

### 6-7. 한 번에 시작/종료 (dev 통합 스크립트) ⭐ 권장

백엔드(6-6)와 프론트엔드(6-8)를 수동으로 따로 띄우는 대신, 한 명령으로
같이 시작/종료할 수 있습니다. 시작 스크립트는 포트 선점 검사 → 백엔드 기동
→ `/health` 준비 대기(CLIP 로딩) → 프론트 기동 순서로 진행하고, 종료
스크립트는 기록된 PID(+포트 폴백)로 `--reload` 워커까지 트리째 정리합니다.

```powershell
# Windows (PowerShell)
.\scripts\dev-start.ps1        # 시작 (-Force: 포트 점유 시 종료 후 진행)
.\scripts\dev-stop.ps1         # 종료
```

```bash
# macOS/Linux
./scripts/dev-start.sh         # 시작 (--force 지원, 로그: scripts/*.log)
./scripts/dev-stop.sh          # 종료
```

### 6-8. 프론트엔드 실행 (Next.js)

`frontend/`에 Next.js 앱이 구현되어 있습니다 (입력 → 검색중 → 결과 3층 → 오류 화면,
백엔드 `POST /search` 연동).

```bash
cd frontend
npm install        # 최초 1회
npm run dev        # http://localhost:3000 (포트 사용 중이면 npm run dev -- -p 3100)
```

백엔드 주소가 기본값(127.0.0.1:8000)과 다르면 `NEXT_PUBLIC_API_BASE` 환경변수로
지정합니다. 백엔드를 먼저 띄운 뒤 접속하세요.

---

## 7. API 사용 방법

서버를 띄운 뒤(섹션 6-6) 아래 엔드포인트를 사용합니다.
브라우저에서 <http://127.0.0.1:8000/docs> 에 접속하면 Swagger UI로 직접
요청을 보내볼 수도 있습니다.

### 7-1. `GET /health` — 서버·엔진 상태 확인

**요청**

```bash
curl http://127.0.0.1:8000/health
```

**응답 (200 OK)**

```json
{
  "status": "ok",
  "engine_ready": true,
  "index_size": 100,
  "trademark_count": 100,
  "storage_mode": "file"
}
```

| 필드 | 의미 |
|------|------|
| `status` | `"ok"`(정상) / `"loading"`(로딩 중) |
| `engine_ready` | 검색 엔진 준비 완료 여부 |
| `index_size` | 인덱스에 적재된 선행상표 벡터 수 |
| `trademark_count` | 메타데이터로 연결된 상표 수 |
| `storage_mode` | 상표 메타 저장소: `"file"`(JSON) / `"db"`(PostgreSQL) |

### 7-2. `POST /search` — 이미지로 유사 상표 검색

업로드한 상표 이미지로 KIPRIS 선행상표 DB에서 가장 닮은 Top-K를 찾고,
4단계 위험 등급을 함께 반환합니다.

**요청 파라미터**

| 위치 | 이름 | 타입 | 설명 |
|------|------|------|------|
| form-data (multipart) | `file` | 파일 | 검색할 상표 이미지 (PNG / JPEG / WEBP, ≤10MiB) |
| query | `top_k` | 정수 | 반환할 결과 개수 (기본 5, 범위 1~20) |

**요청 예시**

```bash
curl -X POST "http://127.0.0.1:8000/search?top_k=5" \
  -F "file=@my_logo.png"
```

**응답 예시 (200 OK)** — 아래 등급/유사도 값은 입력 이미지에 따라 달라지는 예시이며,
상표 레코드는 데이터셋의 실제 항목입니다.

```json
{
  "grade": {
    "grade_code": "LOW",
    "grade_name": "특정 위협 없음",
    "message": "특별히 가까운 선행상표가 발견되지 않았습니다. 본 결과는 참고용임을 유의하세요.",
    "top1_similarity": 0.4981,
    "separability_a": 0.0123,
    "separability_b": 0.0456,
    "warnings": []
  },
  "matches": [
    {
      "rank": 1,
      "similarity": 0.4981,
      "이미지파일": "4020210070072.png",
      "이미지URL": "/images/4020210070072.png",
      "trademark": {
        "출원번호": "4020210070072",
        "등록번호": "4021030920000",
        "출원일자": "2021-04-05",
        "등록일자": "2023-10-26",
        "상표한글명": "태백투어패스",
        "상표영문명": null,
        "상표구분": "도형복합",
        "출원인": "주식회사 단군",
        "최종권리자": "주식회사 단군",
        "비엔나코드": ["도안화(양식화)된 산 또는 화산", "점"],
        "류": [35, 39],
        "유사군": ["S123101", "S0101", "S1312", "S1370"]
      }
    }
  ],
  "dataset_info": {
    "총_상표수": 100,
    "출원일자_범위": "2021 ~ 2026",
    "데이터_기준": "KIPRIS 등록상표 공보",
    "생성일자": "2026-05-25"
  },
  "index_size": 100,
  "top_k_requested": 5,
  "top_k_returned": 5
}
```

**응답 주요 필드**

| 필드 | 의미 |
|------|------|
| `grade.grade_code` | 등급 코드: `CAUTION` / `REVIEW` / `LOW` / `SAFE` |
| `grade.grade_name` | 등급 이름: 주의 필요 / 검토 권장 / 특정 위협 없음 / 비교적 안전 |
| `grade.top1_similarity` | 1순위 후보와의 유사도 (클수록 닮음) |
| `grade.separability_a` | 1순위와 2순위의 격차 (작을수록 판정이 모호) |
| `grade.separability_b` | 1순위와 전체 평균의 격차 |
| `grade.warnings` | 모호 케이스·비정상 입력 등 주의 메시지 목록 |
| `matches[]` | 유사 상표 Top-K. `similarity`, `이미지URL`, `trademark` 상세 포함 |
| `matches[].이미지URL` | 결과 이미지의 정적 경로 (`/images/{출원번호}.png`) |
| `dataset_info` | 비교에 사용한 데이터셋 안내 |

**4단계 등급 판정 기준 (현재)**

| 등급 | 코드 | 조건(개략) |
|------|------|------------|
| 주의 필요 | `CAUTION` | top-1 유사도 ≥ 0.75 **그리고** 1·2순위 격차 ≥ 0.15 |
| 검토 권장 | `REVIEW` | top-1 유사도 ≥ 0.55 **그리고** 1·2순위 격차 ≥ 0.04 |
| 특정 위협 없음 | `LOW` | top-1 유사도 ≥ 0.45 |
| 비교적 안전 | `SAFE` | 그 외 |

> 위 임계값은 1학기 시연 데이터에서 역산한 **임시값**이며, 데이터가 쌓이면
> 통계적으로 재조정할 예정입니다.

**오류 응답**

| 상황 | 상태 코드 | 예시 메시지 |
|------|-----------|-------------|
| 지원하지 않는 형식 | 415 | `지원하지 않는 Content-Type: text/plain` |
| 빈 파일 | 400 | `빈 파일입니다.` |
| 용량 초과 | 413 | `파일 크기 상한(10485760 bytes)을 초과했습니다.` |
| `top_k` 범위 밖 | 422 | (Pydantic 검증 오류) |
| 엔진 미초기화 | 503 | `엔진이 아직 초기화되지 않았습니다.` |

### 7-3. `GET /images/{파일명}` — 결과 이미지

검색 응답의 `matches[].이미지URL` 경로로 실제 로고 이미지를 받을 수 있습니다.

```bash
curl http://127.0.0.1:8000/images/4020210070072.png --output result.png
```

### 7-4. `GET /name-check` — 동일 명칭 등록상표 확인 (KIPRIS 실시간)

입력한 상표명을 KIPRIS 상표명완전일치 API로 조회해 **등록 상태인 선행상표
건수**를 요약합니다. 동일 질의는 24시간 캐시되어 월 호출 한도를 아낍니다.

```bash
curl "http://127.0.0.1:8000/name-check?name=삼성전자"
```

```json
{
  "query": "삼성전자",
  "total_found": 59,
  "registered_count": 31,
  "exact_registered_count": 4,
  "cached": false,
  "message": "동일 명칭의 선행 등록상표 4건이 존재합니다."
}
```

> `.env`에 `KIPRIS_ACCESS_KEY`와 `KIPRIS_TM_NAME_SEARCH_URL`(API 통합설명서에서
> 확인)이 설정되어 있어야 하며, 미설정 시 503과 함께 설정 안내를 반환합니다.
> 한도 초과 시 429.

---

## 8. 개발 단계 (로드맵)

| 단계 | 내용 | 상태 |
|------|------|------|
| Phase 0 | 개발 환경 · 프로젝트 구조 세팅 | ✅ 완료 |
| Phase 1 | ML 파이프라인 단독 검증 (CLIP + FAISS) | ✅ 완료 |
| Phase 2 | KIPRIS 실데이터 100건 파이프라인 + 4단계 등급 모듈 | ✅ 완료 |
| Phase 3 | FastAPI 백엔드 API (`/search`, `/health`, `/name-check`) | ✅ 완료 |
| Phase 4 | 프론트엔드 (업로드 + 3층 결과 화면, 백엔드 1차 연동) | ✅ 완료 |
| Phase 5 | 다축 위험 평가 (호칭·외관·관념·견련성) + 통계적 위험 확률 | 🔜 예정 |
| Phase 6 | 식별력 없는 상표 필터 · 데이터 확장 | 🔜 예정 |

---

## 9. 팀 구성

- 최다빈
- 정현수
- 배지원

---

## 10. 데이터 및 문서

### 데이터

- KIPRIS 등록상표 공보 원본은 저작권 문제로 본 저장소에 포함되지 않습니다.
- `ml/data/` 하위(원본 PDF/txt, 추출 이미지, FAISS 인덱스, 통합 메타데이터)는
  `.gitignore`에 의해 git 추적에서 제외됩니다.
- 검증 데이터(100건)는 팀 내부 채널로 공유됩니다.

### 설계 결정 기록

주요 설계 결정(위험도 등급 구조, 4단계 등급 정의, 격차 두 종의 의미 등)은
`docs/MarkLens_설계결정기록.md`에 정리되어 있습니다.

---

## 라이선스

본 프로젝트는 학술적 목적으로 진행되는 졸업프로젝트입니다.
