# 백엔드 작업 가이드 (역사 계획서, 담당: 현수)

> 이 문서는 2026-07-07 당시의 실행 계획을 보존한 기록이며 현재 API 계약이 아닙니다.
> 현재 구현은 [API 계약](MarkLens_API계약_v1.md)과
> [공개 배포·보안 가이드](MarkLens_공개배포_보안가이드.md)를 기준으로 합니다.
> 특히 신규 명칭 확인은 `POST /name-check`, `GET`은 deprecated이며, 검색 상태는
> `status_code`를 사용하고 `SAFE`를 반환하지 않습니다.

> 데이터 인프라 + 수집 + 검색·API. 기준: `assets/TODO.pdf` 백엔드-1~9 + 2026-07-07 검증 세션 발견 사항.
> 전체 일정·의존성은 [로드맵](MarkLens_로드맵_마일스톤.md) 참조.

## ⚡ 진행 현황 (2026-07-07 구현 세션 반영)

| 작업 | 상태 | 산출물 |
|---|---|---|
| 백엔드-0 버그 수정 4건 | ✅ 완료 | `main.py`(images dir 보장), `api/search.py`(빈 인덱스 503, Content-Length 선검사, 응답 조립 보호), `engine.py`(dataset_info 기동 시 검증) |
| 출원번호 정규화 | ✅ 완료 | `backend/src/core/appno.py` + 테스트 |
| 백엔드-1 스키마 | ✅ 완료 (팀 공유·확인 필요) | `backend/migrations/001_init.sql`, `backend/src/core/db.py` |
| 백엔드-2 마이그레이션 | ✅ 스크립트 완료 | `backend/scripts/migrate_json_to_db.py` (DB 자동 생성·멱등·검증 리포트) |
| 백엔드-3 1단계 | ✅ 완료 | `MARKLENS_DATA_DIR`/`MARKLENS_IMAGES_DIR` 환경변수 오버라이드 (`paths.py`), S3 전환은 후반 |
| 백엔드-4 검색-DB 연결 | ✅ 완료 | `engine.py` 파일/DB 듀얼 모드 — `DATABASE_URL` 설정 시 db 모드(요청당 배치 쿼리 1회), 미설정 시 기존 file 모드 |
| 백엔드-5 수집 파이프라인 | ✅ 스크립트 완료 / ⏳ 실행은 키 발급 후 | `backend/scripts/collect_pipeline.py` (①카운터+딜레이 ②즉시 다운로드 ③등록만 ④비엔나 필수 ⑤0건 시 명시적 실패, `--mock-xml` 오프라인 테스트) |
| 백엔드-7 호칭 검색 | ✅ 모듈 완료 / ⏳ 실호출은 키 발급 후 | `backend/src/core/kipris_client.py`, `GET /name-check` + 24h 캐시 |
| 회귀 테스트 | ✅ 완료 | `backend/tests/` — 단위 16 + API 계약 16 (파일·DB 모드 공용) |
| 백엔드-6 데이터 확장 | 🔜 키 + 수집 기준 합의 후 | — |
| 백엔드-8·9 다축 | 🔜 2학기 (축 함수 선행) | — |

남은 수동 절차: KIPRIS Plus 계정·키 발급(공통-1) → `.env` 작성(`.env.example` 참고) → API 통합설명서에서 오퍼레이션 URL 확인 → `collect_pipeline.py --dry-run`으로 첫 실측.

## 현재 백엔드가 어떻게 생겼나 (2026-07-07 실측)

```
요청 흐름:  POST /search
  main.py (lifespan에서 engine.load_all() 1회)
    └► api/search.py: 업로드 수신 → core/validation.py (Content-Type→크기→디코드→포맷→최소치수)
         └► core/engine.py: run_search()
              ├ ml/src/embedding.encode_image()  ← sys.path에 ml/ 주입해 import
              ├ ml/src/search.search()           ← FAISS IndexFlatIP (코사인)
              ├ state.image_paths / trademark_lookup (startup에 JSON 통째 적재)
              └ ml/src/scoring.score_results()   ← 4단계 등급
         └► _to_response(): Pydantic 직렬화 (+ /images URL 변환)

데이터(전부 파일):  ml/data/index/kipris.faiss + kipris_metadata.json (인덱스 순서↔파일명)
                   ml/data/kipris_metadata.json (상표 상세, 파일명이 조인 키)
                   ml/data/images/*.png (StaticFiles로 서빙)
```

- 검증 결과: HTTP 계약 23/23 통과 (정상 검색·top_k 클램프·메타 누락 시 trademark:null·422/415/400/413/404·정적 서빙·health). **현재 구조는 건전하며, 아래 작업들은 이 구조를 "파일 → DB/스토리지"로 갈아끼우는 것.**
- 실행: 저장소 루트에서 `ml\venv\Scripts\python.exe -m uvicorn backend.src.main:app --port 8000` (venv 공유, 여유 메모리 ~5GB 필요)

---

## 백엔드-0. 사전 정비 — 검증 세션에서 발견된 결함 수정 ⚡즉시, 반나절

새 기능 전에 고치면 이후 모든 작업의 디버깅이 편해진다.

| # | 결함 | 위치 | 수정 방법 |
|---|---|---|---|
| 0-1 | `ml/data/images` 없으면 서버가 **안내 메시지 없이 import 시점 크래시** — lifespan의 친절한 `[FATAL]` 안내가 나올 기회가 없음 | `backend/src/main.py:66-70` | 마운트 직전에 `IMAGES_DIR.mkdir(parents=True, exist_ok=True)` 추가 (또는 `StaticFiles(..., check_dir=False)`) |
| 0-2 | 응답 조립이 try/except 밖 — 메타 JSON의 `dataset_info` 4필드 중 하나라도 빠지면 **미처리 500** | `backend/src/api/search.py:97` | `_to_response()` 호출을 try 블록 안으로; 더 좋게는 `load_all()`에서 `DatasetInfo(**...)` 선검증해 기동 시점에 실패시키기 |
| 0-3 | 빈 인덱스면 `score_results`가 ValueError → 클라이언트에 400 (서버 상태 문제인데 4xx) | `backend/src/api/search.py:84-89` | `engine.state.index.ntotal == 0`이면 503으로 분기 |
| 0-4 | 업로드 전체를 메모리에 받은 뒤 크기 검사 — 10MB 제한이 피크 메모리를 못 지킴 | `api/search.py:78` → `validation.py:24` | (우선순위 낮음) `request.headers["content-length"]` 선확인 또는 스트리밍 읽기. DB 전환보다 급하지 않음 — 이슈로만 기록해도 됨 |

완료 기준: `ml/data`를 지운 상태에서 서버 기동 → "인덱스가 없습니다. build_index.py를 실행하세요" 류의 **읽을 수 있는 에러**가 나온다.

---

## 백엔드-1. PostgreSQL 도입 · 상표 테이블 설계 ⚡독립, 즉시

**목표**: `ml/data/kipris_metadata.json`의 필드를 정규화된 테이블로. 이후 모든 작업(2·4·5·6)의 토대.

**방법(권장 순서)**
1. 로컬 PostgreSQL 설치(팀원 각자) 또는 Docker: `docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=... postgres:16`
2. 스키마 초안 — 핵심 규칙은 TODO에 명시돼 있다: **비엔나·류·유사군은 한 상표에 여러 개 → 절대 한 덩어리 문자열 금지** (자카드 집합 연산·검색이 안 됨). 1:N 별도 테이블 또는 배열 타입 중 택1. 시작은 배열 타입이 간단하고, 유사군으로 조건 검색이 많아지면 1:N으로:

```sql
CREATE TABLE trademark (
    application_no   TEXT PRIMARY KEY,          -- 출원번호 (조인 키, 정규화된 숫자만)
    registration_no  TEXT,
    name_ko          TEXT,
    name_en          TEXT,
    mark_type        TEXT,                      -- 도형상표/도형복합
    applicant        TEXT,
    right_holder     TEXT,
    application_date DATE,
    registration_date DATE,
    image_key        TEXT NOT NULL,             -- 스토리지 키 or 상대경로 (백엔드-3)
    vienna_codes     TEXT[] NOT NULL DEFAULT '{}',
    nice_classes     SMALLINT[] NOT NULL DEFAULT '{}',
    similarity_codes TEXT[] NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_tm_name_ko ON trademark (name_ko);
CREATE INDEX idx_tm_applicant ON trademark (applicant);
CREATE INDEX idx_tm_simcodes ON trademark USING GIN (similarity_codes);  -- 배열 검색용
```

3. 접속 정보는 `.env`(`DATABASE_URL=postgresql://...`) — python 쪽은 `psycopg[binary]` 또는 SQLAlchemy 2.x. 백엔드 규모상 **SQLAlchemy Core(또는 그냥 psycopg)면 충분** — ORM 전면 도입은 과함.
4. 스키마 1장 단톡 공유 → 다빈이 필드 누락 확인 (규약).

**함정**
- 출원번호 포맷: KIPRIS 원천에 따라 `40-2021-0126877`/`4020210126877` 혼재 가능 → **저장 전 숫자만 남기는 정규화 함수를 공용 모듈로** 만들고 (예: `backend/src/core/appno.py`), 모든 입출력에서 통일. 추출 스크립트의 파일명 조인(extract_kipris_images.py:112)이 이 문제로 조용히 0건이 될 수 있음이 확인됨.
- 한글 필드명은 API 응답 계약(스키마)에만 유지하고, DB 컬럼은 영문으로 — 위 표처럼.

**완료 기준**: 스키마 마이그레이션 스크립트(`backend/migrations/001_init.sql` 등)가 저장소에 있고, 빈 DB에 1회 실행으로 테이블 생성.

---

## 백엔드-2. JSON 100건 → DB 마이그레이션 (백엔드-1 후)

**방법**
1. `ml/scripts/` 또는 `backend/scripts/`에 `migrate_json_to_db.py`: `ml/data/kipris_metadata.json` 읽기 → 출원번호 정규화 → INSERT (UPSERT: `ON CONFLICT (application_no) DO UPDATE`) — 재실행 가능(멱등)하게.
2. **무결성 검증을 스크립트 안에**: 건수 일치, 필수 필드 non-null, 배열 필드 원소 수 표본 대조, `이미지파일`이 실제 images/에 존재하는지 → 요약 리포트 출력.
3. 데이터는 깃허브에 없음 — 공유 폴더의 프로젝트 압축본을 받아 `ml/data/`에 배치 후 실행.

**함정**: JSON의 `이미지파일`(예: `4020210126877.png`)이 조인 키다. DB에서는 `image_key`로 승격하되, 추출 실패로 실물이 없는 레코드(reconcile 미구현 이슈)를 이 단계에서 걸러 **"DB에 있으면 이미지도 있다"를 불변식으로** 만들면 좋다.

**완료 기준**: 검증 리포트 100건 전부 OK + 재실행해도 결과 동일.

---

## 백엔드-3. 이미지 폴더 → 스토리지 전환 (백엔드-1 후, 2와 병행 가능)

**단계적 접근(TODO 권장 그대로)**
- 1단계(무료·즉시): 이미지 폴더를 코드와 분리(예: `E:\marklens-data\images\`)하고 DB `image_key`에 경로 저장. `/images` 서빙은 `paths.py`의 `IMAGES_DIR`를 환경변수(`MARKLENS_IMAGES_DIR`)로 오버라이드 가능하게 변경.
- 2단계(후반): S3(또는 Cloudflare R2 — 프리 티어 10GB/월 무료, 이그레스 무료라 학생 프로젝트에 유리) 업로드 → DB에는 키만, 응답의 `이미지URL`은 presigned URL 또는 CDN URL로. **착수 전 예상 비용 확인 필수**(TODO 명시).

**함정**: `main.py`의 StaticFiles 마운트는 로컬 경로 전제 — 2단계로 가면 `/images` 라우트를 제거하고 `이미지URL`을 절대 URL로 바꾸는 쪽이 깔끔. 프론트는 이미 `imageUrl()` 헬퍼(frontend/lib/api.ts)로 감싸놔서 무변경 대응 가능.

**완료 기준**: 서버 코드에 하드코딩 이미지 경로가 없고, 환경변수만 바꿔 다른 위치/스토리지로 전환 가능.

---

## 백엔드-4. 검색-DB 연결 — JSON 전체 메모리 적재 제거 (백엔드-2 후)

**현재**: `engine.load_all()`이 `trademark_lookup`(파일명→dict)을 통째로 메모리에 (engine.py:94-99). 100건이면 문제없지만 수천 건+다축 메타면 DB 조회가 맞다.

**방법**
1. FAISS 검색 결과 인덱스 → `image_paths[i]`(파일명) → 출원번호 목록 추출 (현재 인덱스 메타의 `image_paths`가 곧 매핑 테이블. **이 매핑은 유지** — TODO도 "FAISS 인덱스↔출원번호 매핑 테이블 유지"라고 명시)
2. `SELECT ... FROM trademark WHERE application_no = ANY(%s)` 한 방으로 후보 메타 일괄 조회 → 기존 dict 조인 로직 대체 (engine.py:145-162 자리)
3. `dataset_info`는 별도 테이블(1행) 또는 집계 쿼리로.
4. startup에서는 인덱스 + `image_paths`만 로드 → `trademark_lookup` 제거.

**함정**: 요청마다 DB 커넥션 생성 금지 — lifespan에서 커넥션 풀(psycopg_pool) 생성. `/health`에 DB 연결 상태 추가 권장.

**완료 기준**: 서버 RSS가 메타 크기와 무관해지고, 검색 응답이 기존과 동일(위 23종 매트릭스 재실행으로 회귀 확인 — 스크립트는 검증 세션 산출물 `http_matrix.py` 참고).

---

## 백엔드-5. 수집 파이프라인 스크립트 ⚡개발은 독립·즉시 (실행은 키 발급 후)

**목표**: 한 명령으로 `출원인명 검색 API → 견본 이미지 다운로드 → 스토리지 적재 → DB insert → FAISS append`.

**필수 반영(TODO 명시 + 검증 발견)**
1. **호출 카운터 + 초당 딜레이** — 월 1,000회/초당 50회. 카운터는 파일(예: `ml/data/kipris_call_count.json`)에 월별 누적 저장해 스크립트 재시작에도 유지.
2. **ImagePath는 일회성/시한부 링크** — 응답 받는 즉시 다운로드 (모아뒀다 나중에 열면 만료).
3. `ApplicationStatus == "등록"`만 수집.
4. `ViennaCode` 빈 값(순수 문자상표 가능성) → 제외.
5. (검증 발견) **출원번호 정규화** 공용 함수 사용 + 배치 종료 시 "대상 N / 성공 M / 제외 사유별 카운트" 리포트. 매칭 0건이면 에러로 종료.
6. FAISS append: 현재 `build_index.py`는 전체 재빌드 방식. 소규모(수백~수천)면 **매번 재빌드가 가장 단순하고 안전** — append는 IndexFlatIP에 `index.add()`로 가능하지만 인덱스 메타(`image_paths`) 순서 동기화를 함께 관리해야 함. H-5(IVF)는 수만 건 전까지 불필요.

**뼈대 구조 제안** (`ml/scripts/collect_pipeline.py`):
```
parse_args(출원인 목록 파일 | 기간, --dry-run, --limit)
for 출원인 in 목록:
    rows = kipris_applicant_search(출원인)         # 카운터+딜레이 내장 클라이언트
    for row in rows:
        if row.ApplicationStatus != "등록": skip
        if not row.ViennaCode: skip
        img = download_now(row.ImagePath)          # 즉시!
        save_to_storage(img, appno)                # 백엔드-3의 저장 함수 재사용
        upsert_trademark(row)                      # 백엔드-2의 upsert 재사용
rebuild_or_append_index()
print(리포트)
```

**완료 기준**: `--dry-run`으로 API 1~2회만 써서 전체 흐름이 로그로 확인되고, 실 실행 1회에 수십 건이 DB+인덱스에 들어간다.

---

## 백엔드-6. 데이터 확장 실행 (백엔드-1~5 + 프론트-3 후)

1. **실행 전 수집 기준 합의(필수)**: 초안 제안 → 단톡 합의. 예: "최근 N년 등록분 ○건 + 유명 브랜드 ○건, 류 편중 방지". 확정 기간·건수는 프론트에 전달 — 결과 화면 "데이터 범위 안내 문구"(현재 `dataset_info.데이터_기준`)에 그대로 사용.
2. 월 한도 계산: 1건당 호출 2~4회 → 월 1,000회로는 250~500건. **목표 500~1,000건이면 2개월 분배 또는 팀원 키 분산**(각자 키로 각자 실행 — 키 공유가 아니라 실행 분담) 계획을 먼저 세운다.
3. 실행 후: 인덱스 재빌드 → `dataset_info` 갱신 → README §10 데이터 범위 문구 갱신.

**완료 기준**: DB 500건↑, `/health`의 index_size·trademark_count 일치, 프론트 문구 갱신.

---

## 백엔드-7. 호칭 실시간 검색 모듈 ⚡독립·즉시 (실측 완료 상태)

**목표**: 사용자 입력 상표명 → `trademarkNameMatchSearchInfo`(상표명완전일치) 호출 → "동일 명칭의 선행 등록상표 N건" 반환. TODO 기준 **API 실측은 이미 완료**("삼성전자" → 59건).

**방법**
1. `backend/src/core/kipris_client.py`(신규): `GET {오퍼레이션URL}?{상표명파라미터}={이름}&accessKey={키}` — 키는 `.env`.
2. 필터: `ApplicationStatus == "등록"`만 채택. **주의: 완전일치여도 해당 문구를 포함한 상표까지 잡힌다**("삼성전자 SAM SUNG ELECTRONICS" 포함) → 응답 Title과 입력의 정확 일치 여부를 나눠서 반환하면 좋음 (`exact_count` / `contains_count`).
3. **동일 질의 캐시 필수**(월 한도 잠식 방지): 시작은 TTL 붙은 인메모리 dict(예: 24h), DB 도입 후엔 `name_search_cache` 테이블로.
4. 호출 카운터 공용 모듈 재사용 (백엔드-5와 동일).
5. 노출: 우선 별도 엔드포인트 `GET /name-check?name=...` → 2학기 백엔드-8에서 오케스트레이션에 흡수.

**에러 처리**: `resultCode 31`(DEADLINE_HAS_EXPIRED_ERROR) = 상품 미신청/기간 만료, `00` = 정상 — 31이면 "키/상품 신청 상태를 확인하세요"로 안내.

**완료 기준**: 같은 이름 2회 조회 시 2번째는 API 호출 없이 캐시 응답(로그로 확인), 등록 외 상태 미포함.

---

## 백엔드-8. 다축 검색 오케스트레이션 (2학기 — 다빈-2 + 프론트-7·8·9 후)

**설계 방향** (현재 `engine.run_search()`가 이미 "추림→메타→등급" 단계로 분리돼 있어 삽입 지점 명확):
1. 후보 추림 = 외관(FAISS top-M, M≈50) ∪ 호칭 후보 (※ **호칭 고속 추림은 미해결 설계 포인트** — 2학기 초 다빈+현수 협의. 아이디어: DB에 G2P 변환 발음열 컬럼을 미리 저장 + trigram 인덱스(pg_trgm)로 근사 후보 → X1 정밀 계산은 후보에만)
2. 후보만 DB 메타 조회 (백엔드-4 재사용)
3. 각 후보에 X1·X2·X3·X4 계산 — `ml/src/axes/` 순수 함수 호출 (X4는 사용자의 유사군 배열 vs 후보의 similarity_codes)
4. 통합 모델(E) 호출 → 위험도 % → 정렬 반환
- 안전장치: 표장 축 하나라도 매우 높으면(수치는 F에서 결정) 모델 결과와 무관하게 최소 '검토 권장' 이상. **검증 세션에서 확인된 등급 역전 사례가 이 안전장치의 필요성을 실증**함.

## 백엔드-9. 입출력 확장 (백엔드-8과 연계 — 2학기)

- `/search`가 3입력: `file`(이미지) + `mark_name`(str) + `similarity_codes`(list[str]) — multipart 필드 추가.
- 응답 확장: `axes: {x1, x2, x3, x4}` 점수 + `risk_percent` + `distinctiveness_warning` + `mark_similar_goods_different_warning`.
- **프론트는 이미 이 확장을 받을 준비가 됨**: 입력 UI(상표명·지정상품 칩)와 결과 1층 경고 자리가 "반영 예정" 상태로 구현돼 있음 (frontend/components/SearchForm.tsx, ResultView.tsx).

---

## 부록 A. KIPRIS API 실측 정보 (TODO.pdf 2026-07-06 검증분 요약)

- 가입 → 데이터 목록에서 상품 신청(활용목적=학술연구, 서비스명="상표 유사도 분석 서비스 MarkLens (건국대학교 컴퓨터공학부 졸업프로젝트)") → 처리상태 "사용중" → 마이페이지에서 **상품별** 인증키
- 한도: 상품별 월 1,000회(매월 1일 초기화) + 초당 50회. 초과 필요 시 일 단위 유료
- 상표명완전일치: 주요 응답 필드 `Title, ApplicationStatus(등록/소멸/거절), ApplicationNumber, GoodClassificationCode(류, | 구분), ViennaCode(| 구분, 빈 값=문자상표 가능성), ApplicantName, RegistrationRightholderName, ImagePath/ThumbnailPath`
- 파일 다운로드 공통: `fileToss.jsp?arg=...` 형태는 **일회성/시한부** — 응답 수신 즉시 다운로드
- 심판사항 API: 오퍼레이션 4그룹(검색 일반/항목별 · 서지 · 부가 · 심판(결)문). 목록 검색에는 심결문 없음 → 심판번호로 심판(결)문 오퍼레이션 별도 호출 → PDF 경로 XML. 검색 결과에 특허 섞임 → **출원번호 40/41 시작(상표)만 필터**. 심결문 PDF는 텍스트 레이어 있음(OCR 불필요, pdfplumber/PyMuPDF로 추출)
- API 통합설명서: 사이트 상단 링크 (상표 출원속보: 오퍼레이션 54개)

## 부록 B. 로컬 개발 환경 메모 (검증 세션 실측)

- venv: `ml/venv` 하나를 ml+backend가 공유 (README §6-4). **Python 3.11 필수** — 3.13은 `numpy<2` 휠이 없어 설치 실패.
- CLIP 로드(빌드·검색·서버 기동)는 **여유 커밋 메모리 ~4.5GB 필요.** 부족하면 `OSError 1455(페이징 파일이 너무 작습니다)` 또는 트레이스백 없이 프로세스 사망. 페이지파일이 고정 크기인 PC는 '시스템 관리'로 변경 권장.
- `kipris_search.py`는 상대경로 하드코딩 → **CWD=ml/ 필수.** 서버는 반드시 저장소 루트에서.
- 검증용 HTTP 계약 테스트(23 어서션)는 회귀 테스트로 재사용 가치 있음 — `backend/tests/`로 옮겨 pytest화 권장.
