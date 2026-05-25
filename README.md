# MarkLens

도형 및 도형+문자 결합상표의 시각적 유사도를 분석하는 웹 서비스

---

## 프로젝트 소개

MarkLens는 사용자가 업로드한 상표 이미지를 기존 상표 데이터와 비교하여,
시각적으로 유사한 상표를 검색하고 참고용 충돌 위험도를 제공하는 시스템입니다.

본 프로젝트는 다음과 같은 문제를 해결하고자 합니다:

- 상표 출원 전 유사 상표를 직접 검색하기 어려운 일반 사용자의 진입 장벽
- 텍스트 기반 검색만으로는 발견하기 어려운 시각적 유사 도형상표
- 비전문가도 이해할 수 있는 유사 근거(비엔나 코드 등) 제공의 필요성

본 프로젝트는 건국대학교 컴퓨터공학부 졸업프로젝트로 진행됩니다.

---

## 주요 기능

### 1학기 (MVP)
- 사용자 이미지 업로드
- CLIP 기반 이미지 임베딩 생성
- FAISS 기반 유사 상표 검색
- 검색 결과를 4단계 등급으로 변환 (주의 필요 / 검토 권장 / 특정 위협 없음 / 비교적 안전)
- 비엔나 코드 기반 보조 설명

### 2학기 (고도화)
- OCR을 통한 결합상표 문자 추출
- 이미지 + 문자 통합 유사도 분석
- 상품분류/등록상태 메타데이터 결합
- 충돌 위험도(Risk Score) 산출
- 비교 화면 UI

---

## 기술 스택

### Frontend
- Next.js 14 (App Router)
- TypeScript
- Fabric.js (2학기 도입 예정)

### Backend
- Python 3.11
- FastAPI
- uvicorn

### AI / ML
- OpenCLIP (ViT-B/32)
- FAISS
- EasyOCR (2학기 도입 예정)

### Data
- KIPRIS 등록상표 공보 (1학기 검증 데이터 100건)
- PostgreSQL (2학기 도입 예정)

### 시스템 의존성
- poppler (PDF 이미지 추출, KIPRIS 데이터 가공에 사용)

---

## 시스템 구조

```
사용자 이미지 업로드
        ↓
   이미지 전처리
        ↓
  CLIP Image Encoder → 512차원 벡터
        ↓
   FAISS 유사 검색
        ↓
  유사 상표 Top-K + 메타데이터
        ↓
   4단계 등급 변환 (scoring)
        ↓
     결과 출력
```

---

## 프로젝트 구조

```
marklens/
├── docs/         # 문서 (계획서, 회의록, 설계결정기록)
├── ml/           # ML 파이프라인 (CLIP, FAISS)
│   ├── src/        # 모듈 (embedding, preprocess, search, scoring)
│   ├── scripts/    # 인덱스 빌드/검색 + KIPRIS 데이터 가공 CLI
│   └── data/       # 원천 데이터·인덱스·이미지 (.gitignore 제외)
├── backend/      # FastAPI 서버
│   ├── src/
│   │   ├── main.py     # 앱 진입점 (lifespan startup, CORS, 정적 서빙)
│   │   ├── api/        # 엔드포인트 (health, search)
│   │   ├── core/       # 경로/설정/엔진/입력 검증
│   │   └── schemas/    # Pydantic 응답 모델
│   └── requirements.txt
├── frontend/     # Next.js 웹
└── shared/       # 공통 타입 정의
```

---

## 개발 환경 요구사항

- Python 3.11
- Node.js 20 LTS
- Git
- poppler (PDF 이미지 추출용 — `pdfimages` 명령 제공)

---

## 설치 및 실행

### 1. 저장소 복제

```bash
git clone https://github.com/[organization]/marklens.git
cd marklens
```

### 2. 시스템 의존성 설치

KIPRIS 데이터 가공에 poppler가 필요합니다.

```bash
# macOS (Homebrew)
brew install poppler

# Ubuntu/Debian
sudo apt install poppler-utils
```

설치 확인:

```bash
pdfimages -v
```

### 3. ML 모듈 설정

```bash
cd ml
python3.11 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. KIPRIS 데이터 준비 (선택)

저작권상 원본 KIPRIS 데이터는 저장소에 포함되어 있지 않습니다. 팀 내부 채널로 받은 원본을 다음 위치에 배치한 뒤 가공 스크립트를 실행합니다.

```
ml/data/raw_kipris/
├── pdfs/            # 상표공보 PDF (파일명 = 출원번호.pdf)
├── gongbo/          # TB_KT10.txt, TB_KT11.txt, TB_KT15.txt, APPLICANT.txt
└── registration/    # LAST_RG_HOLDER.txt
```

```bash
cd ml
source venv/bin/activate
python scripts/build_kipris_metadata.py   # txt 6개 → kipris_metadata.json
python scripts/extract_kipris_images.py   # PDF 로고 → data/images/*.png
```

### 5. Backend 설정

백엔드는 ML 모듈과 동일한 PyTorch/FAISS 스택을 공유하므로, **별도 venv를 만들지 않고 `ml/venv`를 그대로 사용**합니다. 처음 한 번 백엔드 추가 패키지만 설치하면 됩니다.

```bash
cd ml && source venv/bin/activate
pip install -r ../backend/requirements.txt
```

서버 실행은 **반드시 프로젝트 루트(`marklens/`)에서** 다음 명령을 사용합니다. backend 폴더 안에서 띄우면 `ml/src` import가 충돌하므로 그렇게 하지 마세요.

```bash
cd ~/marklens && source ml/venv/bin/activate
uvicorn backend.src.main:app --reload
```

- API 문서: <http://127.0.0.1:8000/docs> (Swagger), <http://127.0.0.1:8000/redoc>
- 헬스체크: `GET http://127.0.0.1:8000/health`
- 검색: `POST http://127.0.0.1:8000/search` (multipart, `file` 필드에 이미지)
- 정적 이미지: `GET http://127.0.0.1:8000/images/{출원번호.png}`

서버는 startup 시 CLIP 모델·FAISS 인덱스·KIPRIS 메타데이터를 1회 로딩하여 메모리에 보관합니다.

### 6. Frontend 설정

```bash
cd frontend
npm install
npm run dev
```

---

## 개발 단계

본 프로젝트는 다음의 단계적 접근으로 개발됩니다:

- **Phase 0:** 개발 환경 및 프로젝트 구조 세팅 (완료)
- **Phase 1:** ML 파이프라인 단독 검증 (완료)
- **Phase 2-A:** 검색 결과 → 4단계 등급 변환 모듈 (완료)
- **Phase 2-D:** KIPRIS 실데이터 파이프라인 (완료, 100건)
- **Phase 2-B:** Backend API 구현 (완료, `/search` `/health`)
- **Phase 3:** Frontend 최소 기능 구현 (예정)
- **Phase 4:** 통합 및 데이터 확장 (예정)

각 단계는 독립적으로 검증 가능한 결과물을 산출합니다.

---

## 팀 구성

- 최다빈
- 정현수
- 배지원

---

## 데이터 및 문서

### 데이터
- KIPRIS 등록상표 공보 원본은 저작권 문제로 본 저장소에 포함되지 않습니다.
- `ml/data/` 하위(원본 PDF/txt, 추출 이미지, FAISS 인덱스, 통합 메타데이터)는 `.gitignore`에 의해 git 추적에서 제외됩니다.
- 1학기 검증 데이터(100건)는 팀 내부 채널로 공유됩니다.

### 설계 결정 기록
주요 설계 결정(Risk Score 구조, 4단계 등급 정의, 격차 두 종의 의미 등)은
`docs/MarkLens_설계결정기록.md`에 정리되어 있습니다.

---

## 라이선스

본 프로젝트는 학술적 목적으로 진행되는 졸업프로젝트입니다.
