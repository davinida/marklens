# MarkLens

MarkLens는 상표(도형·결합상표)의 출처 혼동 위험도를 외관·호칭·관념·상품 견련성
4축으로 평가하는 비상업적 교육·연구용 웹 서비스입니다. 1학기에 외관(CLIP) 검색과
백엔드를 완성했고, 2학기에 다축 모델로 확장 중입니다 — 호칭 축(X1)은 구현을
마쳤고, 관념·상품 축과 통합 모델은 예정입니다.

결과는 참고 정보입니다. 상표 등록 가능성, 침해 여부, 법적 위험 확률 또는 검색
범위 밖 권리의 부재를 판정하지 않습니다.

| 항목 | 2026-09-17 현재 |
|---|---|
| 마지막 갱신 | 2026-09-17 (`main` = `develop` = `087a843`) |
| 데이터 | KIPRIS 등록상표 1,100건, generation `20260827T035002Z-25f84a6eeb26` (2026-08-27) |
| 테스트 | Python `440 passed, 1 skipped` · 프런트 Vitest `41 passed` · Playwright 스펙 3개 × 뷰포트 3개 |
| CI | GitHub Actions 3잡(python · frontend · deployment-config) 통과 — PR #20·#21 |

## 현재 범위

| 기능 | 상태 | 비고 |
|---|---|---|
| 이미지 검색 | 구현 | PNG/JPEG/WebP, 최대 10 MiB, 수동 크롭 지원 |
| 시각 후보 상태 | 구현 | 단조적 4개 상태, 교정 전 임시 임계값 |
| 상표명 완전일치 확인 | 구현 | KIPRIS 실시간 조회, 후보 상세·상태 분포·완전성 표시. **검색과 별개 기능**(검색 점수에 반영되지 않음) |
| KIPRIS 수집 및 인덱스 빌드 | 구현 | 체크포인트, authoritative key, manifest, 원자적 게시 |
| 호칭 유사도 X1 | 최소 연결 | `ml/src/axes/x1_phonetic.py` + `POST /phonetic-search`. 상표명 확인 패널에 "발음이 비슷한 등록상표" 섹션. 통합 점수에는 미반영 |
| 상품↔유사군 변환표 | 도구 구현 | 파서·검증기 완료. `goods_map.json`은 라이선스 확인 전이라 미커밋(로컬 생성) |
| 관념(X3)·상품 견련성(X4)·통합 모델 | 예정 | UI의 지정상품 입력도 현재 숨김 |
| 법적 위험 확률·등록 가능성 판단 | 미구현 | 제품 범위 밖 |
| 공개 클라우드 배포 | 템플릿만 제공 | 실제 도메인·TLS·계정 배포는 하지 않음 |

현재 로컬 검증 데이터는 서로 다른 출원번호 기준 1,100건의 제한된 연구 표본입니다.
이미지·metadata·FAISS vector가 각각 1,100개이고 Nice 45개 류를 모두 포함하지만,
선택된 출원인과 등록 상태 중심의 표본이므로 전체 선행 권리를 대표하지 않습니다.
현재 generation은 `20260827T035002Z-25f84a6eeb26`(2026-08-27 생성)이며 manifest가
`git.dirty=true`이므로 배포 artifact가 아닙니다. 상표명이 비어 있는 레코드(순수
도형 등)가 153건(14%)이고 유사군 코드는 100건에만 있습니다 — 상표명 프로파일은
[X1 설계 문서](docs/MarkLens_X1_호칭유사도_설계.md) §4·§6에 있습니다.
데이터 구성과 평가 한계는 [모델·데이터 카드](docs/MarkLens_모델카드_데이터카드.md)를
먼저 확인하세요(2026-08-15 1,000건 세대 기준으로 작성됨).

## 구현 현황 (방학 분배 항목 기준, 2026-09-17)

항목 번호는 `docs/MarkLens_작업가이드_*.md`의 분배 계획을 따릅니다.
상태: 완료 / 부분 / 미착수 / 보류.

| 항목 | 담당 | 상태 | 위치 | 비고 |
|---|---|---|---|---|
| 공통 축 함수 규약 `ml/src/axes/` | 다빈 | 완료(X1) | `ml/src/axes/` | X3·X4 파일은 예정 |
| 다빈-1 정답 데이터(심결 라벨표) | 다빈 | 미착수 | — | 통합 모델 학습 전제 |
| 다빈-2 호칭 X1 | 다빈 | **완료** | `ml/src/axes/x1_phonetic.py`, `korean_brands.py`, `ml/tests/test_axes.py`(90건), `docs/MarkLens_X1_호칭유사도_설계.md` | PR #21. 최소 연결(`/phonetic-search`, `backend/src/core/phonetic_search.py`) |
| 다빈-3 식별력 필터 | 다빈 | 미착수 | — | X1의 `extra_generic` 입력을 공급할 예정 |
| 다빈-4 변환표 검증 | 다빈 | **완료** | `shared/goods_map/README.md` §4 절차 | 2026-09-17 원본 xlsx로 91,591건·표본 10개 대조. 35류 병합 명칭 정책은 검토 중 |
| 프론트-1 변경 시안 확정 | 지원 | 미착수 | — | 저장소에 시안 산출물 없음 |
| 프론트-2 상품↔유사군 변환표 | 지원 | 부분 | `shared/goods_map/`, `shared/types/goods.ts` | 파서·검증기 완료(PR #19). JSON 미커밋 — 공공누리 확인 중 |
| 프론트-3 유명 로고 브랜드 목록 | 지원 | 부분 | `shared/famous_brands.txt` | DRAFT 39건(출원인명), 아직 수집 전 |
| 프론트-4 화면 골격(3층 결과 화면) | 현수 | 완료 | `frontend/app/page.tsx`, `frontend/components/ResultView.tsx` | |
| 프론트-5 백엔드 1차 연동 | 현수 | 완료 | `frontend/app/api/*`(BFF) | |
| 프론트-6 지정상품 입력 UI | 지원 | 미착수 | — | 프론트-2 후 |
| 프론트-7 관념 X3 | 지원 | 미착수 | — | |
| 프론트-8 상품 견련성 X4 | 지원 | 미착수 | — | DB 스키마의 `similarity_codes TEXT[]`만 준비 |
| 프론트-9 통합 모델·재보정 | 지원 | 미착수 | — | 로지스틱 회귀 예정 |
| 백엔드-1 PostgreSQL 설계 | 현수 | 완료 | `backend/migrations/001_init.sql` | |
| 백엔드-2 JSON→DB 마이그레이션 | 현수 | 완료 | `backend/scripts/migrate_json_to_db.py` | |
| 백엔드-3 이미지 S3 | 현수 | 보류 | `backend/src/core/storage.py` | 로컬 심 계층 + 경로 오버라이드만 |
| 백엔드-4 검색-DB 연결 | 현수 | 완료 | `backend/src/core/engine.py` db 모드 | |
| 백엔드-5 수집 스크립트 | 현수 | 완료 | `backend/scripts/collect_pipeline.py` | 출원인명 검색 |
| 백엔드-6 데이터 확장 | 현수 | 완료 | `docs/MarkLens_데이터확장_실행계획_2026-08.md` | 현재 1,100건 세대(2026-08-27) |
| 백엔드-7 상표명 실시간 확인 | 현수 | 완료 | `backend/src/api/namecheck.py` | |
| 백엔드-8 다축 오케스트레이션 | 현수 | 미착수 | — | 축 함수 선행 |
| 백엔드-9 3입력·4축 응답 | 현수 | 미착수 | — | |

세 가지를 분명히 해 둡니다.

- 검색 입력은 **아직 이미지 1개**입니다(`POST /search`는 `file`과 `top_k`만 받음).
- 상표명 확인(`/name-check`)은 검색과 분리된 별도 기능이며 검색 점수에 영향을 주지 않습니다.
- X1은 `POST /phonetic-search`로 최소 연결되어 상표명 확인 패널에 발음 유사 후보를 보여 줍니다. 검색 점수·등급에는 반영되지 않습니다(통합 모델 예정).

## 구조

```text
Browser
  -> Next.js same-origin BFF (/api/search, /api/name-check, /api/images, /api/health, /api/turnstile-config)
  -> private FastAPI
  -> OpenCLIP + FAISS index
  -> PostgreSQL / KIPRIS Plus
```

- `frontend/`: Next.js UI, 수동 크롭, Turnstile 검증, BFF(`app/api/*`)
- `backend/`: FastAPI, 업로드 검증, 검색·명칭 확인 API, KIPRIS 수집 스크립트(`scripts/`)
- `ml/`: 전처리, 임베딩, 검색, 점수, 인덱스 빌드, 평가 도구
- `ml/src/axes/`: 다축 모델의 축 함수 — X1 호칭 유사도(`x1_phonetic.py`, 브랜드·지명 로마자표 `korean_brands.py`). X3·X4는 예정
- `ml/evaluation/`: 200-pair 라벨링 팩과 강건성 평가 계약
- `shared/`: 프런트·백엔드 공용 자산 — `goods_map/`(상품↔유사군 변환표 파서·검증기), `famous_brands.txt`(유명 브랜드 출원인 목록 DRAFT), `types/goods.ts`(변환표 타입)
- `scripts/`: 개발 서버 통합 시작·종료(`dev-start.sh`/`.ps1`, `dev-stop.sh`/`.ps1`)
- `deploy/`, `compose.production.yml`: 공개 배포 준비 템플릿
- `docs/`: API, 보안·운영, 모델·데이터, 설계 문서 — 색인은 [`docs/README.md`](docs/README.md)
- `.github/workflows/ci.yml`: CI 3잡

## 로컬 실행

### 0. 새 컴퓨터 사전 준비

| 도구 | 버전 | 비고 |
| --- | --- | --- |
| Python | 3.11 | 3.13은 `numpy<2` 휠이 없어 설치 실패 |
| Node.js | 20.19 이상 (LTS 권장) | `frontend/package.json`의 engines 기준. CI는 Node 22 |
| PostgreSQL | 16 | **db 모드를 쓸 때만** 필요. `DATABASE_URL`을 설정하지 않는 file 모드는 설치 불필요 |

PostgreSQL 설치 예시: Windows `winget install PostgreSQL.PostgreSQL.16` /
macOS `brew install postgresql@16` / Ubuntu `sudo apt install postgresql-16`.

- 최초 부팅 시 CLIP 가중치(ViT-B-32 laion2b, 약 578MB)를 사용자 홈의
  huggingface 캐시로 자동 다운로드하므로 인터넷 연결이 필요합니다.
- CLIP 가중치 로드에 시스템 커밋 메모리 여유가 약 5GB 필요합니다. 부족하면
  서버가 로그 없이 종료됩니다 —
  [`docs/MarkLens_트러블슈팅.md`](docs/MarkLens_트러블슈팅.md)의 TS-07 참고.

### 1. Python 환경

Python 3.11을 사용합니다. Windows PowerShell 예시:

```powershell
py -3.11 -m venv ml\venv
ml\venv\Scripts\python.exe -m pip install `
  torch==2.13.0 torchvision==0.28.0 `
  --index-url https://download.pytorch.org/whl/cpu
ml\venv\Scripts\python.exe -m pip install setuptools==83.0.0
ml\venv\Scripts\python.exe -m pip install -c constraints.txt `
  -r ml\requirements.txt `
  -r backend\requirements.txt `
  -r backend\requirements-dev.txt
```

macOS/Linux(bash) 예시:

```bash
python3.11 -m venv ml/venv
ml/venv/bin/python -m pip install \
  torch==2.13.0 torchvision==0.28.0 \
  --index-url https://download.pytorch.org/whl/cpu
ml/venv/bin/python -m pip install setuptools==83.0.0
ml/venv/bin/python -m pip install -c constraints.txt \
  -r ml/requirements.txt \
  -r backend/requirements.txt \
  -r backend/requirements-dev.txt
```

`setuptools==83.0.0` 단계는 CI(`.github/workflows/ci.yml`)·컨테이너 빌드
(`deploy/backend.Dockerfile`)와 동일한 순서입니다. 고정 버전은 `constraints.txt`에
있습니다(torch 2.13.0, faiss-cpu 1.14.3, open_clip_torch 2.32.0, httpx2 2.13.0).

`ml/data/`는 Git에 포함되지 않습니다. 최소한 다음 파일이 필요합니다.

```text
ml/data/index/kipris.faiss
ml/data/index/kipris_metadata.json
ml/data/kipris_metadata.json
ml/data/images/*
```

새 인덱스는 `kipris_manifest.json`까지 생성해야 합니다. production 모드는
manifest가 없거나 모델·전처리·해시 계약이 다르면 기동하지 않습니다.

#### ml/data 입수와 머신 간 이전

`ml/data/`는 저작권 문제로 이 공개 저장소에는 포함되지 않으며, 팀 전용
private 저장소 <https://github.com/jhsoo0211/marklens-data> 로 관리합니다
(협업자 권한 필요, 공개 재배포 금지).

입수 방법(셋 중 하나):

- **A. git clone(권장)** — 프로젝트 루트에서
  `git clone https://github.com/jhsoo0211/marklens-data.git ml/data`.
  이후 갱신은 `git -C ml/data pull`로 받습니다.
- **B. GitHub ZIP** — 저장소 페이지의 Code → Download ZIP을 받아 풀면
  `marklens-data-main/` 폴더가 나옵니다. 그 안의 내용물(`images/`, `index/`,
  `kipris_metadata.json` 등)이 프로젝트 루트의 `ml/data/` 바로 아래에 오도록
  옮깁니다(최종 경로 예: `ml/data/index/kipris.faiss`).
- **C. 팀 공유 압축본(오프라인 폴백)** — 데이터가 있는 머신에서 압축해 전달:
  - PowerShell: `Compress-Archive -Path ml\data -DestinationPath marklens-data.zip`
  - bash: `zip -r marklens-data.zip ml/data`

  새 머신의 프로젝트 루트에 같은 구조(`ml/data/...`)로 풉니다.

배치 후 공통 절차:

1. file 모드는 그대로 기동하면 됩니다. db 모드는 먼저 DB에 적재합니다:
   `ml\venv\Scripts\python.exe -m backend.scripts.migrate_json_to_db --prune`
2. 서버 기동 후 `/health`의 `index_size`·`trademark_count`·
   `artifact_generation_id`가 원본 머신과 같은지 확인합니다.

주의사항:

- `ml/data/kipris_call_count.json`은 KIPRIS 월 쿼터 카운터입니다. 머신 간 값이
  병합되지 않으므로 실제 수집을 수행한 머신의 값이 정본이며, 더 낮은 값으로
  덮어쓰면 안 됩니다. 같은 이유로 데이터 저장소에서는 `.gitignore`로 제외되어
  있습니다 — 새 머신에 이 파일이 없어도 서빙은 되지만, **실제 수집은 정본
  카운터가 있는 머신에서만** 수행하세요(없는 머신에서 수집하면 카운터가 0부터
  시작해 월 쿼터를 초과 사용하게 됩니다).
- 현재 세대는 2026-08-27 생성 1,100건(generation `20260827T035002Z-25f84a6eeb26`,
  데이터 저장소 커밋 `61bd6a2`)입니다. 위 A/B 방법으로 받으면 됩니다. 2026-06의
  100건 세트는 태그 `v0.1-semester1`(1학기 종료 기준선, `a4e3f11`) 시점의
  데이터이며 현재 세대와 호환되지 않습니다.

이전 후 확인 목록(원본 머신과 대조):

- [ ] `/health`의 `artifact_generation_id` 일치
- [ ] `index_size` == `trademark_count` == 기대 건수
- [ ] db 모드: `migrate_json_to_db --prune` 후 재기동 시 키 불일치 오류 없음
- [ ] production 모드 기동은 `kipris_manifest.json`이 있어야 가능
- [ ] 검색 스모크: 인덱스에 있는 이미지 1건 업로드 시 자기일치 유사도 ≈ 1.0

#### Apple Silicon(M1 이후) 주의

- **서버는 그대로 뜹니다.** 2026-09-17 #18에서 `backend/src/core/engine.py`가
  `src.embedding`(torch)을 `faiss`보다 먼저 import하도록 고쳐 CLIP 워밍업 시
  SIGSEGV(exit 139)가 사라졌습니다(같은 날 이 순서로 `/health` 정상, 옛 순서는
  여전히 exit 139 재현). 이 import 순서는 `# noqa: I001`로 고정돼 있으니 자동
  정렬로 되돌리지 마세요.
- **`pytest`도 변수 없이 돕니다(2026-09-18 해결).** 이전에는 테스트 수집 단계에서
  `backend/tests/conftest.py`·`ml/tests/test_search.py`가 faiss를 먼저 올려 같은
  충돌이 나(`ml/tests/test_embedding.py`에서 exit 139) `OMP_NUM_THREADS=1` 우회가
  필요했습니다. 이제 `ml/src/search.py`가 torch를 faiss보다 먼저 import하고
  `ml/tests/conftest.py`·`backend/tests/conftest.py`도 torch를 선행 import하므로
  변수 없이 전체 pytest가 통과합니다. ML 스크립트는 모두 `src.search`를 통해
  faiss를 올리므로 별도 조치가 필요 없습니다. 이 순서들도 `# isort: split`·
  `# noqa`로 고정돼 있으니 자동 정렬로 되돌리지 마세요.
- Linux·Windows·CI에는 해당 없습니다.

### 2. 환경변수

백엔드는 루트 `.env`, 프런트는 `frontend/.env.local`을 읽습니다. 백엔드는 `.env`
없이 file 모드로 뜨고(이미지 검색만 쓸 때 필수 값 없음), 프런트는 `.env.local`에
dev bypass 한 줄만 있으면 됩니다.

| 값 | 어디에 | 언제 필요 |
|---|---|---|
| `KIPRIS_ACCESS_KEY` | `.env` | 상표명 확인(`/name-check`)과 데이터 수집. 월 1,000회 한도, 각자 발급 |
| `DATABASE_URL` | `.env` | PostgreSQL db 모드. 비우면 JSON file 모드 |
| `MARKLENS_TURNSTILE_DEV_BYPASS=1` | `frontend/.env.local` | 실제 Turnstile 키 없이 로컬 UI를 쓸 때. production에서는 무시됨 |

전체 목록과 설명은 `.env.example`(백엔드)과 `frontend/.env.example`(프런트)에
있습니다.

```powershell
Copy-Item .env.example .env
Copy-Item frontend\.env.example frontend\.env.local
```

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env.local
```

비밀값은 Git에 커밋하지 마세요. KIPRIS URL은 HTTPS만 허용됩니다.
필요한 신청 상품과 장애 점검 순서는
[`docs/MarkLens_KIPRIS_API_신청가이드.md`](docs/MarkLens_KIPRIS_API_신청가이드.md)를
참고하세요.

### 3. 백엔드

반드시 프로젝트 루트에서 실행합니다.

```powershell
ml\venv\Scripts\python.exe -m uvicorn backend.src.main:app `
  --host 127.0.0.1 --port 8000 --reload
```

```bash
ml/venv/bin/python -m uvicorn backend.src.main:app \
  --host 127.0.0.1 --port 8000 --reload
```

- 상태: `http://127.0.0.1:8000/health`
- OpenAPI: `http://127.0.0.1:8000/docs`

### 4. 프런트엔드

```powershell
Copy-Item frontend\.env.example frontend\.env.local
Set-Location frontend
npm ci
npm run dev
```

```bash
cp frontend/.env.example frontend/.env.local
cd frontend
npm ci
npm run dev
```

브라우저는 FastAPI 주소나 서버 키를 직접 알지 않습니다. Next BFF가 서버 전용
`MARKLENS_BACKEND_URL`과 `MARKLENS_BACKEND_API_KEY`를 사용합니다. 로컬 기본값은
백엔드 `http://127.0.0.1:8000`입니다.

실제 Turnstile 키 없이 로컬 UI를 확인할 때는 `frontend/.env.local`에
`MARKLENS_TURNSTILE_DEV_BYPASS=1` 하나만 켭니다(위젯 설정 라우트와 서버 검증이
같은 값을 읽습니다). production에서는 이 bypass가 무시됩니다.

### 5. 두 프로세스를 한 번에

`scripts/`의 헬퍼가 백엔드(8000)와 프런트(3000)를 함께 띄우고 `/health`가
준비될 때까지 기다립니다. 파일에 실행 비트가 없으므로 bash로 호출합니다.

```bash
bash scripts/dev-start.sh     # --force: 포트 점유 프로세스 종료 후 진행
bash scripts/dev-stop.sh
```

```powershell
.\scripts\dev-start.ps1       # -Force, -NoBrowser
.\scripts\dev-stop.ps1
```

### 졸업과제 시연·평가는 여기까지면 됩니다

file 모드(`DATABASE_URL` 없음) + Turnstile dev bypass로 검색·상표명 확인 화면을
모두 시연할 수 있습니다. Docker, Nginx, PostgreSQL, 실제 Turnstile 키는 공개
배포용이며 로컬 평가에는 필요 없습니다. 상표명 확인만 KIPRIS 키가 있어야 합니다.

## API 요약

정식 브라우저 경계는 same-origin `/api/*`입니다. FastAPI 직접 호출은 로컬 개발과
내부 서비스 통신용입니다.

| 경로 | 용도 |
|---|---|
| `POST /api/search?top_k=5` | Turnstile 검증 후 이미지 검색 프록시 |
| `POST /api/name-check` | `{ "name": "...", "turnstileToken": "..." }` 명칭 확인 프록시 |
| `POST /api/phonetic-search` | `{ "name": "...", "turnstileToken": "...", "top_k"?: 1..20 }` X1 발음 유사 후보 프록시 |
| `GET /api/health` | 외부용 BFF·FastAPI 준비 상태 |
| `GET /api/images/{path}` | 결과 이미지 프록시 |
| `GET /api/turnstile-config` | 위젯 사이트 키·dev bypass 설정 전달 |
| `GET /health` | 내부 FastAPI 엔진·인덱스 상태 |
| `POST /search` | 내부 이미지 검색 API (`file`, `top_k`) |
| `POST /name-check` | 내부 명칭 확인 API |
| `POST /phonetic-search` | 내부 X1 호칭 유사도 검색 (`name`, `top_k`). 로컬 DB 계산, KIPRIS 무관 |
| `GET /images/{key}` | 인덱스에 포함된 결과 이미지만 제공. `MARKLENS_PUBLIC_RESULT_IMAGES=true`(로컬 기본)일 때만 등록 |
| `GET /docs` | Swagger UI |

검색의 정식 판정 필드는 `grade.status_code`입니다.

- `STRONG_MATCH`: 매우 가까운 시각 후보
- `POSSIBLE_MATCH`: 가까울 수 있는 시각 후보
- `WEAK_MATCH`: 약한 시각 후보
- `NO_CLOSE_MATCH`: 현재 비교 표본에서 가까운 후보 미확인

`NO_CLOSE_MATCH`는 안전 판정이 아닙니다. `grade_code`와 `grade_name`은 기존
클라이언트를 위한 deprecated 필드이며 다음 계약 버전에서 제거할 예정입니다.
전체 요청·응답과 오류 계약은 [API 계약](docs/MarkLens_API계약_v1.md)에 있습니다.
그 문서의 `GET /name-check` 호환 경로 서술은 낡았습니다 — 해당 라우트는 현재
코드에 없습니다.

## 다축 모델과 축 함수

| 축 | 내용 | 상태 |
|---|---|---|
| X1 호칭 | 두 상표명의 발음 유사도. 판례 5규칙(호칭 최우선, 첫음절 강세, 여러 호칭 중 최댓값, 외국어의 국내 발음, 한영 병기 시 한글 우선) | **완료** — 라이브러리 |
| X2 외관 | OpenCLIP ViT-B/32 임베딩 + FAISS 코사인 검색 | 완료 — 현재 서비스 |
| X3 관념 | 상표명 의미를 사전학습 한국어 언어모델 임베딩으로 비교 | 예정 |
| X4 상품 견련성 | 유사군 코드 집합 간 자카드 계수 | 예정 |
| 통합 | 4축 점수를 로지스틱 회귀로 결합해 0~100% 위험 확률. 특허법원 심결 데이터로 가중치 학습 | 예정 |

축 함수 공통 규약: 위치 `ml/src/axes/`, 입력은 상표명 문자열 2개(X1·X3) 또는
유사군 코드 집합 2개(X4), 출력은 0.0~1.0 float(높을수록 유사), 순수 함수·대칭·
결정적이며 예외를 던지지 않습니다. 각 축은 `ml/tests/`에 테스트를 동봉합니다.

### X1 호칭 유사도 (`ml/src/axes/x1_phonetic.py`)

```python
import sys; sys.path.insert(0, "ml")   # 프로젝트 루트에서
from src.axes.x1_phonetic import phonetic_similarity, has_pronunciation
phonetic_similarity("스타벅스", "스타박스")                              # 0.96
has_pronunciation("東洋")                                                # False → X1 결측 처리
phonetic_similarity("카페 봄", "봄", extra_generic=frozenset({"카페"}))  # 1.0
```

- 서비스 연결(최소): `POST /phonetic-search`가 기동 시 DB 상표명의 발음 후보를 캐시해
  입력 상표명과 비교한 상위 후보를 돌려주고, 상표명 확인 패널이 "발음(호칭)이 비슷한
  등록상표" 섹션으로 보여 줍니다. 검색 등급·점수에는 아직 반영되지 않습니다.
- 흐름: 정규화(회사 형태·부가어·기능어 제거) → 발음 후보(외래어 표기법 근사 룰
  G2P, 국내 브랜드 로마자표 91개·지명표 34개, 예외 사전 39개, 낱자·숫자 읽기,
  한영 병기 판정) → 후보 조합 → 위치 가중 음절 레벤슈타인 → 최댓값.
- `has_pronunciation`이 False인 상표(순수 도형·한자만)는 X1을 결측으로 두고
  다른 축만으로 판단합니다. `extra_generic`에는 식별력 필터(예정)가 넘길 상품
  의존 보통명칭 집합을 넣습니다.
- 성능: 데이터 상표명 1,000쌍 0.21초(cold) — DB 전수 계산이 가능한 수준.
  G2P 벤치마크 60단어는 순수 룰 기준 정확 일치 48/60(브랜드·지명 로마자표와 예외 사전은
  벤치마크에서 끔).
- 설계·상수·한계·검토 대기 항목: [X1 설계 문서](docs/MarkLens_X1_호칭유사도_설계.md).
  점수표 재현: `ml/venv/bin/python ml/scripts/x1_report.py`.

### 상품↔유사군 변환표 (`shared/goods_map/`)

지식재산처 고시상품명칭 13판(2026) xlsx를 `[상품명, 류, 유사군코드 배열]` 1:N
JSON으로 바꾸는 도구입니다. 절차는 원본 다운로드(브라우저) → `parse_goods_map.py
inspect`/`convert` → `validate_goods_map.py` 순이며 명령은
[`shared/goods_map/README.md`](shared/goods_map/README.md)에 있습니다. 2026-09-17
검증에서 91,591건, Nice 45/45류, 유사군 2개 이상 5,798건을 원본과 대조했습니다.

`goods_map.json`과 원본 xlsx는 공공누리 유형(재배포 가능 여부) 확인 전이라
커밋하지 않고 각자 로컬에서 생성합니다(`.gitignore`). 소비 측은 프론트-6(지정상품
입력 UI)과 X4 자카드 계산이며 둘 다 예정입니다. 타입은 `shared/types/goods.ts`.

### 유명 브랜드 목록 (`shared/famous_brands.txt`)

로고가 널리 알려진 브랜드의 KIPRIS **출원인명** 39건(국내 23·해외 16) DRAFT입니다.
`backend/scripts/collect_pipeline.py --applicants-file shared/famous_brands.txt`의
입력용이며 아직 수집에 쓰지 않았습니다(팀 검토 전).

## 검증

```powershell
$env:MARKLENS_FAKE_ML = "1"
ml\venv\Scripts\python.exe -m pytest -v
ml\venv\Scripts\python.exe -m ruff check backend ml
ml\venv\Scripts\python.exe -m pip_audit --local --progress-spinner off

Set-Location frontend
npm run typecheck
npm run lint
npm test
npm run test:e2e
npm run build
npm audit --omit=dev --audit-level=high
```

```bash
export MARKLENS_FAKE_ML=1
ml/venv/bin/python -m pytest -q
ml/venv/bin/ruff check backend ml
ml/venv/bin/python -m pip_audit --local --progress-spinner off

cd frontend
npm run typecheck && npm run lint && npm test && npm run test:e2e && npm run build
npm audit --omit=dev --audit-level=high
```

2026-09-17 검증(`main` = `develop` = `087a843`): Python `440 passed, 1 skipped`
(X1 90건 포함), ruff 통과, frontend Vitest `41 passed`(12 파일), Playwright는
스펙 3개 × 뷰포트 3개(320x568, 667x375, desktop)를 같은 날 CI에서 통과했습니다.
file 모드 서버 스모크에서 `/health`가 `index_size`·`trademark_count` 1,100과
generation `20260827T035002Z-25f84a6eeb26`을 반환했습니다. 이 검증에서 KIPRIS
`/name-check`는 호출하지 않았습니다. 직전 기록(2026-08-15, 1,000건 세대)은 Python
`337 passed, 5 skipped`, Vitest `34/34`, Chromium E2E `9/9`였습니다.

### CI

`.github/workflows/ci.yml`은 `main`·`develop` push와 모든 PR에서 3잡을 돌립니다.

| 잡 | 내용 |
|---|---|
| python | Python 3.11, `ruff check backend ml`, `pip check`, `pytest -v`(`MARKLENS_FAKE_ML=1`, PostgreSQL 16 서비스), `pip-audit --local` |
| frontend | Node 22, `npm ci`, `npm audit --omit=dev --audit-level=high`, typecheck, lint, Vitest, `next build`, Chromium Playwright E2E |
| deployment-config | `compose.production.yml` 계약 검증, Nginx 문법 검증 |

`pip-audit`·`npm audit`은 실패 게이트입니다. 2026-09-17 #17에서 이 게이트에 걸린
의존성을 올렸습니다(next 16.3.5, httpx2 2.13.0).

실제 OpenCLIP 강건성 평가는 opt-in 명령입니다. 라벨 검수가 끝나기 전에는
임계값 재보정이나 정확도 주장을 하지 않습니다.

### 데이터 확장과 사람 검수

KIPRIS 수집은 먼저 `--plan`으로 호출 상한을 확인하고, DB가 없는 연구 환경에서는
`ml/data/staging/`에 메타·이미지를 격리합니다. 2026-08-15에는 105건을 기준으로
신규 895건을 수집·감사·승격해 index를 정확히 1,000벡터로 확장했습니다. 8월 로컬
호출 카운터는 `145/950`이며, 월 예산을 지키기 위해 신규 레코드의 서지상세·유사군
보강은 실행하지 않았습니다. 재현 명령, 백업, 격리와 승격 계약은
[데이터 확장 실행 기록](docs/MarkLens_데이터확장_실행계획_2026-08.md)에 있습니다.
2026-08-27에 1,100건 세대로 갱신되어 데이터 저장소에 커밋되어 있습니다.

현재 라벨링 팩 `vlp2_d32d53e3b6c101517517`은 1,000-vector generation에서 자동
그룹화한 769개 visual family를 바탕으로 200쌍(development 160, frozen holdout 40)을
만들었으며 사람 라벨은 `0/200`입니다. 따라서 fine-tuning gate는 닫혀 있습니다.

같은 generation의 v4 강건성 표본은 25개 원본과 100개 변형을 모두 처리했습니다.
exact Recall@1은 원본 `0.76`, crop `0.72`, 나머지 변형 `0.76`이고 모든 Recall@5와
상태 안정성은 `1.0`입니다. 원본 R@1 miss 6건은 모두 byte-identical 그룹의 rank 2~3
동률 사례였지만 family R@1은 측정하지 않았으므로 패밀리 검색 성능으로 해석하지 않습니다.
로컬 검수 도구는 `ml/`에서 실행합니다.

```powershell
venv\Scripts\python.exe scripts\review_labeling_pack.py `
  --annotator-id "<stable-reviewer-id>"
```

```bash
venv/bin/python scripts/review_labeling_pack.py --annotator-id "<stable-reviewer-id>"
```

기본 화면은 development 160쌍만 보여 줍니다. frozen holdout 40쌍은 development
결정과 임계값을 고정한 뒤에만 단방향으로 열 수 있습니다. 상세 계약은
[ML 평가·라벨링 가이드](ml/evaluation/README.md)를 참고하세요.

## 공개 배포 준비

`compose.production.yml`은 다음 경계를 구성합니다.

- 외부 노출: Nginx gateway와 Next.js만
- 내부 전용: FastAPI와 PostgreSQL
- 검색 5회/분, 명칭 확인 2회/분의 gateway 사용자별 제한
- Turnstile 서버 검증과 서버 전용 FastAPI 키
- production의 PostgreSQL·32자 이상 API 키·artifact manifest 필수화
- KIPRIS 재배포 권리 확인 전 결과 이미지 공개 비활성

실행 전 [공개 배포·보안 가이드](docs/MarkLens_공개배포_보안가이드.md)의 수동
게이트를 모두 완료해야 합니다. 특히 기존 KIPRIS 키 회전, 공식 약관 확인,
TLS 종료, 데이터 마이그레이션은 자동화할 수 없는 항목입니다.

TLS edge는 외부의 `X-MarkLens-Client-IP`를 제거한 뒤 검증한 원격 IP로 다시
설정해야 합니다. Compose gateway는 기본적으로 loopback에만 바인딩되어 이 신뢰
경계가 없는 평문 공개를 막습니다.

## 데이터와 권리

KIPRIS 원본, 이미지, FAISS 인덱스와 모델 캐시는 저장소에 포함되지 않습니다.
KIPRIS 콘텐츠의 공개 재배포 또는 수익 목적 사용은 별도 권리 확인이 필요합니다.
production 예시는 `MARKLENS_PUBLIC_RESULT_IMAGES=false`가 기본입니다.
고시상품명칭 원본 xlsx와 변환 산출물 `shared/goods_map/goods_map.json`도 공공누리
유형을 확인하기 전까지 커밋하지 않습니다.

## 브랜치·협업

- `develop`은 통합 브랜치, `main`은 안정 브랜치입니다. 기능 브랜치(`feat/…`,
  `fix/…`, `chore/…`, `docs/…`) → PR(base `develop`) → CI 통과 후 머지 → `develop`을
  `main`으로 동기화(PR)합니다.
- 커밋 메시지는 `유형(범위): 설명` 형식입니다. 예: `feat(ml): X1 호칭 유사도 축`,
  `fix(backend): …`, `docs(readme): …`.
- `.env`, `ml/data/`(데이터·인덱스·호출 카운터), 인증키는 커밋하지 않습니다.
- 태그 `v0.1-semester1`(`a4e3f11`, 2026-06-10)이 1학기 종료 기준선입니다.
- Dependabot(주간, pip·npm·docker·actions)이 열어 두는 PR의 처리 방침은 결정
  예정입니다.

## 문서

- [전체 문서 색인](docs/README.md)
- [X1 호칭 유사도 설계](docs/MarkLens_X1_호칭유사도_설계.md)
- [상품↔유사군 변환표 절차](shared/goods_map/README.md)
- [2026-2학기 16주 계획과 4주 단위 제출 문서](docs/course/2026-2/README.md)
- [2026-08 기술 재감사 보고서](docs/MarkLens_기술감사보고서_2026-08.md)
- [API 계약](docs/MarkLens_API계약_v1.md)
- [공개 배포·보안 가이드](docs/MarkLens_공개배포_보안가이드.md)
- [모델·데이터 카드](docs/MarkLens_모델카드_데이터카드.md)
- [ML 평가·라벨링](ml/evaluation/README.md)
- [트러블슈팅](docs/MarkLens_트러블슈팅.md)
- [설계 결정 기록](docs/MarkLens_설계결정기록.md)

## 팀

- 최다빈 — 데이터·법리·모델 총괄(정답 데이터, X1 호칭, 식별력 필터)
- 정현수 — 데이터 인프라·백엔드(수집, DB, API, 배포)
- 배지원 — 화면·모델(프런트, 변환표, X3 관념·X4 상품·통합 모델)

본 프로젝트는 건국대학교 컴퓨터공학부 졸업프로젝트이며 비상업적 교육·연구
목적으로 개발됩니다.
