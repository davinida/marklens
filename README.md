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
- KIPRIS AI 도형상표 학습데이터
- PostgreSQL (2학기 도입 예정)

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
     결과 출력
```

---

## 프로젝트 구조

```
marklens/
├── docs/         # 문서 (계획서, 회의록)
├── ml/           # ML 파이프라인 (CLIP, FAISS)
├── backend/      # FastAPI 서버
├── frontend/     # Next.js 웹
└── shared/       # 공통 타입 정의
```

---

## 개발 환경 요구사항

- Python 3.11
- Node.js 20 LTS
- Git

---

## 설치 및 실행

### 1. 저장소 복제

```bash
git clone https://github.com/[organization]/marklens.git
cd marklens
```

### 2. ML 모듈 설정

```bash
cd ml
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Backend 설정

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --reload
```

### 4. Frontend 설정

```bash
cd frontend
npm install
npm run dev
```

---

## 개발 단계

본 프로젝트는 다음의 단계적 접근으로 개발됩니다:

- **Phase 0:** 개발 환경 및 프로젝트 구조 세팅
- **Phase 1:** ML 파이프라인 단독 검증
- **Phase 2:** Backend API 구현
- **Phase 3:** Frontend 최소 기능 구현
- **Phase 4:** 통합 및 데이터 확장

각 단계는 독립적으로 검증 가능한 결과물을 산출합니다.

---

## 팀 구성

- 최다빈
- 정현수
- 배지원

---

## 라이선스

본 프로젝트는 학술적 목적으로 진행되는 졸업프로젝트입니다.
