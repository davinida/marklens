# MarkLens

MarkLens는 업로드한 표장 이미지와 수집된 선행 상표 이미지를 비교해 가까운
시각 후보를 보여 주는 비상업적 교육·연구용 웹 애플리케이션입니다.

현재 결과는 OpenCLIP 기반 **시각 유사도 한 축**만 다룹니다. 상표 등록 가능성,
침해 여부, 법적 위험 확률 또는 검색 범위 밖 권리의 부재를 판정하지 않습니다.

## 현재 범위

| 기능 | 상태 | 비고 |
|---|---|---|
| 이미지 검색 | 구현 | PNG/JPEG/WebP, 최대 10 MiB, 수동 크롭 지원 |
| 시각 후보 상태 | 구현 | 단조적 4개 상태, 교정 전 임시 임계값 |
| 상표명 완전일치 확인 | 구현 | KIPRIS 실시간 조회, 후보 상세·상태 분포·완전성 표시 |
| KIPRIS 수집 및 인덱스 빌드 | 구현 | 체크포인트, authoritative key, manifest, 원자적 게시 |
| 호칭(X1)·관념(X3)·상품 견련성(X4) | 미구현 | UI의 지정상품 입력도 현재 숨김 |
| 법적 위험 확률·등록 가능성 판단 | 미구현 | 제품 범위 밖 |
| 공개 클라우드 배포 | 템플릿만 제공 | 실제 도메인·TLS·계정 배포는 하지 않음 |

현재 로컬 검증 데이터는 서로 다른 출원번호 기준 1,000건의 제한된 연구 표본입니다.
이미지·metadata·FAISS vector가 각각 1,000개이고 Nice 45개 류를 모두 포함하지만,
선택된 출원인과 등록 상태 중심의 표본이므로 전체 선행 권리를 대표하지 않습니다.
현재 generation은 `20260815T023540Z-0d79c662f4c8`이며 작업 중 빌드되어
`git.dirty=true`이므로 배포 artifact가 아닙니다.
데이터 구성과
평가 한계는 [모델·데이터 카드](docs/MarkLens_모델카드_데이터카드.md)를 먼저
확인하세요.

## 구조

```text
Browser
  -> Next.js same-origin BFF (/api/search, /api/name-check, /api/images)
  -> private FastAPI
  -> OpenCLIP + FAISS index
  -> PostgreSQL / KIPRIS Plus
```

- `frontend/`: Next.js UI, 수동 크롭, Turnstile 검증, BFF
- `backend/`: FastAPI, 업로드 검증, 검색·명칭 확인 API
- `ml/`: 전처리, 임베딩, 검색, 점수, 인덱스 빌드, 평가 도구
- `ml/evaluation/`: 200-pair 라벨링 팩과 강건성 평가 계약
- `deploy/`, `compose.production.yml`: 공개 배포 준비 템플릿
- `docs/`: API, 보안·운영, 모델·데이터 문서

## 로컬 실행

### 0. 새 컴퓨터 사전 준비

| 도구 | 버전 | 비고 |
| --- | --- | --- |
| Python | 3.11 | 3.13은 `numpy<2` 휠이 없어 설치 실패 |
| Node.js | 20.19 이상 (LTS 권장) | `frontend/package.json`의 engines 기준 |
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
(`deploy/backend.Dockerfile`)와 동일한 순서입니다.

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
- 2026-08 기준 1,000건 세대(generation `20260815T023540Z-0d79c662f4c8`)는 데이터
  저장소에 커밋되어 있습니다. 위 A/B 방법으로 받으면 되고, 데이터 저장소를
  받지 않은 머신은 2026-07의 100건 레거시 세트로 동작합니다.

이전 후 확인 목록(원본 머신과 대조):

- [ ] `/health`의 `artifact_generation_id` 일치
- [ ] `index_size` == `trademark_count` == 기대 건수
- [ ] db 모드: `migrate_json_to_db --prune` 후 재기동 시 키 불일치 오류 없음
- [ ] production 모드 기동은 `kipris_manifest.json`이 있어야 가능
- [ ] 검색 스모크: 인덱스에 있는 이미지 1건 업로드 시 자기일치 유사도 ≈ 1.0

### 2. 환경변수

`.env.example`을 참고해 루트 `.env`를 구성합니다. 이미지 검색만 사용할 때는
KIPRIS 키가 없어도 되지만 명칭 확인과 데이터 수집에는 필요합니다.

```powershell
Copy-Item .env.example .env
```

비밀값은 Git에 커밋하지 마세요. KIPRIS URL은 HTTPS만 허용됩니다.
필요한 신청 상품과 장애 점검 순서는
[`docs/MarkLens_KIPRIS_API_신청가이드.md`](docs/MarkLens_KIPRIS_API_신청가이드.md)를
참고하세요.

### 3. 백엔드

```powershell
ml\venv\Scripts\python.exe -m uvicorn backend.src.main:app `
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

브라우저는 FastAPI 주소나 서버 키를 직접 알지 않습니다. Next BFF가 서버 전용
`MARKLENS_BACKEND_URL`과 `MARKLENS_BACKEND_API_KEY`를 사용합니다. 로컬 기본값은
백엔드 `http://127.0.0.1:8000`입니다.

실제 Turnstile 키 없이 로컬 UI를 확인할 때만 `.env.local`의 서버·클라이언트 개발
bypass 두 값을 모두 `1`로 설정합니다. production에서는 이 bypass가 무시됩니다.

## API 요약

정식 브라우저 경계는 same-origin `/api/*`입니다. FastAPI 직접 호출은 로컬 개발과
내부 서비스 통신용입니다.

| 경로 | 용도 |
|---|---|
| `POST /api/search?top_k=5` | Turnstile 검증 후 이미지 검색 프록시 |
| `POST /api/name-check` | `{ "name": "...", "turnstileToken": "..." }` 명칭 확인 프록시 |
| `GET /api/health` | 외부용 BFF·FastAPI 준비 상태 |
| `GET /health` | 내부 FastAPI 엔진·인덱스 상태 |
| `POST /search` | 내부 이미지 검색 API |
| `POST /name-check` | 내부 명칭 확인 API |
| `GET /name-check` | 한 릴리스 호환용, deprecated |

검색의 정식 판정 필드는 `grade.status_code`입니다.

- `STRONG_MATCH`: 매우 가까운 시각 후보
- `POSSIBLE_MATCH`: 가까울 수 있는 시각 후보
- `WEAK_MATCH`: 약한 시각 후보
- `NO_CLOSE_MATCH`: 현재 비교 표본에서 가까운 후보 미확인

`NO_CLOSE_MATCH`는 안전 판정이 아닙니다. `grade_code`와 `grade_name`은 기존
클라이언트를 위한 deprecated 필드이며 다음 계약 버전에서 제거할 예정입니다.
전체 요청·응답과 오류 계약은 [API 계약](docs/MarkLens_API계약_v1.md)에 있습니다.

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

2026-08-15 최종 통합 검증은 Python `337 passed, 5 skipped`, frontend Vitest
`34/34`, Chromium E2E `9/9`(320x568, 667x375, desktop), lint·typecheck·production
build 통과입니다. generation
`20260815T023540Z-0d79c662f4c8`으로 FastAPI `/health`와 BFF `/api/health`가
index·metadata 각 1,000건을 반환했고, BFF 검색·결과 이미지 proxy와 160쌍 development
검수 화면도 확인했습니다. 이 smoke에서는 KIPRIS `/name-check`를 호출하지 않았습니다.

실제 OpenCLIP 강건성 평가는 opt-in 명령입니다. 라벨 검수가 끝나기 전에는
임계값 재보정이나 정확도 주장을 하지 않습니다.

### 데이터 확장과 사람 검수

KIPRIS 수집은 먼저 `--plan`으로 호출 상한을 확인하고, DB가 없는 연구 환경에서는
`ml/data/staging/`에 메타·이미지를 격리합니다. 2026-08-15에는 105건을 기준으로
신규 895건을 수집·감사·승격해 index를 정확히 1,000벡터로 확장했습니다. 8월 로컬
호출 카운터는 `145/950`이며, 월 예산을 지키기 위해 신규 레코드의 서지상세·유사군
보강은 실행하지 않았습니다. 재현 명령, 백업, 격리와 승격 계약은
[데이터 확장 실행 기록](docs/MarkLens_데이터확장_실행계획_2026-08.md)에 있습니다.

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

## 문서

- [전체 문서 색인](docs/README.md)
- [2026-2학기 16주 계획과 4주 단위 제출 문서](docs/course/2026-2/README.md)
- [2026-08 기술 재감사 보고서](docs/MarkLens_기술감사보고서_2026-08.md)
- [API 계약](docs/MarkLens_API계약_v1.md)
- [공개 배포·보안 가이드](docs/MarkLens_공개배포_보안가이드.md)
- [모델·데이터 카드](docs/MarkLens_모델카드_데이터카드.md)
- [ML 평가·라벨링](ml/evaluation/README.md)
- [트러블슈팅](docs/MarkLens_트러블슈팅.md)
- [설계 결정 기록](docs/MarkLens_설계결정기록.md)

## 팀

- 최다빈
- 정현수
- 배지원

본 프로젝트는 건국대학교 컴퓨터공학부 졸업프로젝트이며 비상업적 교육·연구
목적으로 개발됩니다.
