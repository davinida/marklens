# MarkLens 기술 감사 보고서 (Technical Audit & Plan Report)

> [!WARNING]
> 2026-07 시점의 역사 스냅샷입니다. 현재 기능·보안·API 기준은 루트
> [README](../README.md), [API 계약](MarkLens_API계약_v1.md),
> [모델·데이터 카드](MarkLens_모델카드_데이터카드.md),
> [2026-08 기술 재감사 보고서](MarkLens_기술감사보고서_2026-08.md)를 따릅니다.

> **감사일**: 2026-07-08 · **감사 범위**: backend / ml / frontend / 인프라 / 개발 프로세스 전체
> **성격**: 시점 스냅샷. 진행 관리의 정본(living doc)은 [로드맵·마일스톤](MarkLens_로드맵_마일스톤.md)이며, 이 보고서는 그 기준선을 코드 실측으로 검증하고 실행 계획을 확정한다.
> **표기**: 「✔ 조치완료」= 이번 감사 세션(2026-07-08)에서 즉시 수정·검증까지 마친 항목.

---

## 작업 1 — 웹앱 구현 상태 전반 진단: 핵심 진단 지표 5가지

각 지표는 **정의 → 측정 방법 → 실측 판정** 순이다. 판정 등급: 🟢 양호 / 🟡 보통 / 🔴 미흡.

### 지표 1. 아키텍처 경계·결합도 — 🟡 보통

**정의**: 계층(ml ↔ backend ↔ frontend)이 명시적 인터페이스로 분리되어 있는가.
**측정**: import 구조 추적, 계약(스키마) 중복 여부, 실행 위치 의존성.
**실측**:
- backend→ml 경계가 패키지가 아니라 **sys.path 주입 + 최상위 이름 `src`** 로 연결된다([engine.py:30](../backend/src/core/engine.py)). 이름 충돌 위험이 있고, 9월 다축 확장 시 ml 모듈 import가 4개+로 늘면 부채가 복리로 커진다.
- frontend는 백엔드 Pydantic 스키마를 [lib/api.ts](../frontend/lib/api.ts)에 **수동 미러링**한다(shared/types는 빈 폴더). 지금은 필드 수가 적어 관리 가능하나 백엔드-9(다축 응답)에서 계약이 2배로 늘 때 어긋나기 시작할 지점.
- 반면 계층 내부는 깨끗하다: api/core/schemas 분리, ml의 preprocess→embedding→search→scoring 단방향 흐름, 프론트의 API_BASE env 분리 + `imageUrl()` 심(스토리지 전환 대비)은 설계 의도가 명확하다.

### 지표 2. 데이터 계층 성숙도 — 🟡 보통 (전환 중, 방향은 옳음)

**정의**: 데이터 저장·조회·이관이 규모 확장(100→1,000건)을 견디는 구조인가.
**측정**: 저장 모드, 쿼리 패턴, 마이그레이션 체계, 스토리지 분리 여부.
**실측**:
- file/db **이중 저장 모드**([config.py:90](../backend/src/core/config.py))가 구현·검증됨. db 모드는 후보만 배치 조회(`WHERE image_key = ANY(%s)`, [db.py:104](../backend/src/core/db.py)) — N+1 없음, 전체 메모리 적재 제거(백엔드-4 선반영). GIN 인덱스(비엔나/류/유사군 배열)까지 잡혀 있다.
- 마이그레이션이 "매번 전체 *.sql 재실행 + 멱등성 의존"이었다 → ✔ **조치완료**: `schema_migrations` 버전 테이블 도입([migrate_json_to_db.py:105](../backend/scripts/migrate_json_to_db.py)), 2회 연속 실행 시 "0 applied" 실검증(PostgreSQL 16.14, `marklens_test`).
- 이미지가 여전히 `ml/data/images` 폴더 + git 외부 수동 공유 — 스토리지 분리(백엔드-3)는 미착수. FAISS는 `IndexFlatIP`([search.py:50](../ml/src/search.py)) — 1,000건 규모에는 브루트포스가 **정답**이며 IVF 전환은 시기상조다.

### 지표 3. 신뢰성·관측성 — 🔴→🟡 (이번 감사로 최하점 탈출)

**정의**: 장애가 났을 때 원인을 추적할 수 있고, 실패가 예측 가능한 방식으로 드러나는가.
**측정**: 로깅 체계, 예외 처리 경로, 요청 추적성, 기동 실패 동작.
**실측**:
- 감사 시점 **로깅 프레임워크 0** — 진단 출력은 print() 뿐, 요청 ID 없음, 전역 예외 핸들러 없음. 에러 재현 문의가 오면 대조할 로그가 없는 상태였다.
- ✔ **조치완료**: stdlib `logging.dictConfig` + uvicorn 로거 통일([logging_conf.py](../backend/src/core/logging_conf.py)), 요청별 8자리 ID를 로그·`X-Request-ID` 응답 헤더에 주입([request_id.py](../backend/src/core/request_id.py), [main.py:75](../backend/src/main.py)), 전역 예외 핸들러(스택 미노출 JSON 500, [main.py:64](../backend/src/main.py)). 실측: `curl -i /health` → `x-request-id: 1c20dea5` 확인.
- 원래 잘 되어 있던 것: 엔드포인트별 오류 계약(415/400/413/422/503), fail-fast 기동 + dataset_info 스키마 선검증, StaticFiles 기동 크래시 수정(백엔드-0). 이 부분은 학부 프로젝트 수준을 상회한다.

### 지표 4. 성능·확장성 — 🔴→🟡 (구조적 결함 1건 해소)

**정의**: 동시 사용자와 데이터 증가를 현 아키텍처가 감당하는가.
**측정**: 이벤트 루프 점유, CPU 추론 경합, 캐시 상한, 외부 API 쿼터 방어.
**실측**:
- **치명 결함(해소)**: `POST /search`(async)가 CPU 바운드 CLIP 인코딩+FAISS+동기 DB 쿼리를 이벤트 루프에서 직접 실행 — 검색 1건이 도는 동안 /health까지 전부 동결되는 구조였다. ✔ **조치완료**: `anyio.to_thread.run_sync` + `CapacityLimiter(2)` 오프로드([search.py:124](../backend/src/api/search.py), [config.py:58](../backend/src/core/config.py)). **실측: /search 2건 동시 진행 중 /health 응답 6~7ms** (조치 전에는 검색 완료까지 블록).
- /name-check의 httpx.Client 호출마다 생성 → ✔ **조치완료**: 모듈 공용 클라이언트 + 커넥션 풀 + lifespan 정리.
- /name-check 캐시가 상한 없는 수제 dict(무한 성장 가능) → ✔ **조치완료**: `TTLCache(maxsize=1024)`([namecheck.py:27](../backend/src/api/namecheck.py)).
- KIPRIS 쿼터 방어는 원래 견고: 월 950회 파일 영속 카운터 + 0.1s 간격 + 24h 캐시. **인바운드** 레이트리밋은 없음(R12, 시연 배포 전 필수).
- CLIP 추론은 CPU 고정(`DEVICE = "cpu"`, [embedding.py:32](../ml/src/embedding.py)), 기동 여유 메모리 ~4.5GB 요구(OSError 1455 실측 이력). 시연 규모에서는 수용 가능 — R13 부하 베이스라인으로 수치를 확정할 것.

### 지표 5. 개발 프로세스 품질 — 🔴→🟡 (git 위기 해소, CI 도입)

**정의**: 작업이 안전하게 보존·검증·공유되는가.
**측정**: git 이력, 테스트 실행 가능성, CI 유무, 문서 정합성.
**실측**:
- **최대 리스크였던 것**: 마지막 커밋 2026-06-10 이후 **한 달치 작업 전부 미커밋** — 프론트엔드 전체, 백엔드 확장(db/kipris/namecheck/tests/migrations/scripts), 문서 4종. 디스크 1개 고장 = 프로젝트 소멸이었다. 팀 규칙(브랜치→PR→리뷰)도 커밋이 없으니 성립 불가. ✔ **조치완료**: `feat/phase2-baseline` 브랜치에 논리 단위 6커밋으로 전량 보존, 낡은 중복 클론 `marklens/`(동일 커밋·고유 작업 없음 확인) 삭제.
- 테스트는 존재했으나(계약 23/23 이력) **인덱스가 없으면 전부 skip**되는 구조 + pytest 설정/CI 전무, ml/tests 빈 폴더. ✔ **조치완료**: 루트 [pyproject.toml](../pyproject.toml) pytest 설정, **더미 FAISS 인덱스 인프로세스 픽스처 + encode_image 몽키패치**([conftest.py](../backend/tests/conftest.py))로 계약 테스트가 CLIP 다운로드 없이 어디서나 실행, [GitHub Actions CI](../.github/workflows/ci.yml)(postgres 서비스 컨테이너 포함) 작성. **실측: 전체 48 passed / 0 skipped** (실모드), 가짜 ML 모드 35 passed.
- 문서 불일치 잔존: 설계결정기록(2026-05-25)이 폐기된 OCR 설계를 정본처럼 기술, README의 프론트 상태 서술 내부 모순(§2 "시안만 완성" vs §6-7 실행 안내). → M1 내 30분 작업으로 개정 권고.

**종합**: 기능 진척(외관 축 E2E + 프론트 1차 연동)은 일정 대비 우수하고 코드 단위 품질도 높다. 문제는 기능이 아니라 **기반(보존·관측·동시성·검증 자동화)** 이었고, 이번 감사에서 그 중 구조적 결함 대부분을 즉시 해소했다. 남은 것은 아래 작업 2~4의 계획대로 실행하면 된다.

---

## 작업 2 — Phase 2(3개월) 마일스톤 및 파트별 구현 목표

> 기준: [로드맵·마일스톤](MarkLens_로드맵_마일스톤.md)의 M1~M4와 정합. 주차는 2026-07-07(월) 시작.
> 파트 = 실제 R&R: **백엔드·인프라(현수)** / **프론트+모델(지원)** / **데이터·법리(다빈)**.
> 크리티컬 패스: **다빈-1 정답 데이터 → 통합 모델(E) → 등급 재보정(F) → 백엔드-8·9**. 데이터 수집이 늦으면 전부 늦는다.

| 마일스톤 (기간) | 파트 | 구현 목표 | 완료 기준 (Definition of Done) |
|---|---|---|---|
| **M0 잔여 정리** (즉시) | 전원 | 기반선 정리 | ✔ 미커밋 1개월분 커밋(6개 논리 커밋) · ✔ 중복 클론 제거 · ✔ 등급 역전 회귀 테스트 고정 — **전부 2026-07-08 완료**. 남은 것: 브랜치 push + PR 머지, 원격 토폴로지 합의(로컬 `master` vs 원격 `main`/`develop`) |
| **M1 착수** (7/7~7/19) | 전원 | KIPRIS Plus 계정·키 각자 발급 | 처리상태 "사용중" + 키를 .env에 보관(커밋 금지). **유일한 외부 하드 의존 — 1주차에 신청** |
| | 백엔드 | ✔R2 등급역전 ✔R3 로깅 ✔R4 루프차단 (완료) + 백엔드-2 실데이터 마이그레이션 | 실데이터 100건 기준 `migrate_json_to_db` 실행, `SELECT count(*) FROM trademark` = reconcile 후 건수와 일치 |
| | 프론트+모델 | 프론트-1 변경 시안 확정 + 프론트-2 상품↔유사군 변환표 | 시안 단톡 확정. 변환표 JSON(1:N 구조) `shared/`에 커밋 + 다빈 검증 통과 |
| | 데이터·법리 | 다빈-1 수집 개시(상시) + 다빈-2 X1 호칭 v1 | `ml/src/axes/x1_phonetic.py` 순수 함수(0~1 float) + 테스트: 스타벅스↔스타박스 > 스타벅스↔커피빈 |
| **M2 인프라 전환 + 축 구현** (7/20~8/16) | 백엔드 | R5 설정 통합 → R9+백엔드-3 스토리지 분리 → R10 ml 패키징 → 백엔드-5 파이프라인 실호출 검증 | pydantic-settings로 기동 시 env 검증 실패가 필드명 명시. 이미지가 `STORAGE_DIR`로 분리(서버가 ml/data/images 없이 기동). `pip install -e ./ml` 후 `grep -rn "sys.path" backend ml` 0건. `collect_pipeline --dry-run` → 실호출 1건 성공 |
| | 프론트+모델 | 프론트-3 브랜드 목록(8/8 마감) + 프론트-6 지정상품 검색 UI + 프론트-7 X3 관념 + 프론트-8 X4 자카드 | `ml/src/axes/`에 x3·x4 순수 함수+테스트 (X3: King↔왕 높음/King↔사과 낮음). 상품 검색 UI가 유사군 코드 배열을 전송 형태로 산출 |
| | 데이터·법리 | 다빈-3 식별력 필터(명백 유형) + 다빈-1 계속 | 명백 유형 사전 대조 + "단정 금지" 문구 출력. 라벨 표 진행량 주 1회 공유 |
| **M3 데이터 확장 + 통합 모델** (8/17~8/30) | 백엔드 | 백엔드-6 데이터 확장 + R12 시연 하드닝 + R13 부하 베이스라인 + R14 재보정 지원 | **DB 500~1,000건**(수집 기준 단톡 합의 → 월 쿼터 분배 계획 준수, 체크포인트+원본 선저장). slowapi 429 + X-API-Key 401 동작. locustfile 커밋 + /search p50/p95 기록(다축 전 공식 베이스라인). /health p95 <100ms 부하 중 유지 |
| | 프론트+모델 | 프론트-9 통합 모델(E) 1차 학습 | 4축 점수 → 로지스틱 회귀 → 위험 % 프로토타입 1회전. 교차검증·ROC-AUC 리포트 + 가중치 해석("호칭>외관"이 판례와 부합하는지) |
| | 데이터·법리 | 라벨 표 완성(수백 건 목표) + 등급 재보정(F) 협업 | [상표A/B 번호, 상표명, 유사군, 라벨, 근거] 표 — 번호 필수(공보 API 재조회용) |
| **M4 다축 서비스 통합** (9월~) | 백엔드 | R11 서비스 계층(8월 말 선행) 기반 백엔드-8 오케스트레이션 + 백엔드-9 3입력 확장 | 외관+호칭 후보 병합 → 배치 메타 조회 → 4축 `score_batch` → 위험 % 정렬 응답. 기존 응답 필드 전부 유지(가산적 확장) + 계약 테스트 green |
| | 프론트+모델 | 3입력·다축 결과 화면 업그레이드 | 경고 박스 2종(식별력/표장유사·상품상이) 실데이터 연동 |
| | 전원 | 미해결 포인트 확정 | 호칭 후보 고속 추림 방식(다빈+현수 협의), 단독 임계값 수치(데이터 분포 기반), X4 근사 한계 문서화 |

---

## 작업 3 — 백엔드 심층 체크리스트 (핵심)

> 판정: ✅ 충족 / ⚠️ 부분 충족(조건부) / ❌ 미충족. "현재 상태"는 2026-07-08 코드 실측.

| # | 영역 | 점검 항목 | 현재 상태 (실측) | 판정 | 요구 기준 (통과선) |
|---|---|---|---|---|---|
| 1-1 | **인증/인가 보안** | API 접근 통제 | 전 엔드포인트 무인증 개방. `Depends` 보안·토큰·키 전무 | ❌ | 시연 배포 전 정적 `X-API-Key` 의존성(설정 시에만 활성) — R12. 사용자 계정/JWT는 **불필요**(유저 없음) |
| 1-2 | | CORS | `allow_origins=["*"]` ([config.py:76](../backend/src/core/config.py), dev-only 주석 있음) | ⚠️ | 배포 시 실제 프론트 origin 한정. R5에서 env 설정화 + 기본값 localhost:3000 |
| 1-3 | | 시크릿 관리 | .env 관리 + .gitignore 검증됨. **커밋된 시크릿 0건** (git 이력 확인). KIPRIS 키 각자 발급 규칙 코드화 | ✅ | 유지. 실서비스 전 dev DB 암호 교체(주석에 이미 명시) |
| 2-1 | **DB 쿼리 최적화** | N+1 / 배치 조회 | 후보 메타를 단일 `ANY(%s)` 배치 조회 ([db.py:104](../backend/src/core/db.py)) | ✅ | 유지. 백엔드-8 후보 병합 시 `application_no` 버전 동일 패턴으로 추가 |
| 2-2 | | 인덱스 설계 | PK(출원번호) + image_key UNIQUE + 배열 컬럼 GIN 3종 (001_init.sql) | ✅ | 유지. X1 도입 시 name_ko 인덱스 검토 |
| 2-3 | | 커넥션 관리 | psycopg_pool(1~4) + 기동 시 SELECT 1 검증. 동기 드라이버 | ✅ | 유지 — 동기 드라이버는 R4 스레드 오프로드 안에서 실행되므로 **구조적으로 옳다**. asyncpg 전환 금지(과잉) |
| 2-4 | | 마이그레이션 체계 | ~~버전 추적 없음(매번 전체 재실행)~~ → ✔ `schema_migrations` 테이블 + 미적용분만 파일당 트랜잭션 적용 | ✅ | 2회 연속 실행 "0 applied" — 실검증 완료. 새 스키마는 새 파일로만 추가 |
| 3-1 | **API 응답 시간** | 이벤트 루프 비차단 | ~~CLIP+FAISS+DB가 루프 직접 점유~~ → ✔ `to_thread` + `CapacityLimiter(2)` ([search.py:124](../backend/src/api/search.py)) | ✅ | **실측: 검색 2건 동시 진행 중 /health 6~7ms**. 회귀 기준: 부하 중 /health p95 <100ms (R13에서 자동화) |
| 3-2 | | 무거운 리소스 수명 | CLIP·인덱스·메타 startup 1회 로딩 + 워밍업 + fail-fast | ✅ | 유지 |
| 3-3 | | 외부 API 클라이언트 | ~~httpx.Client 호출마다 생성~~ → ✔ 모듈 공용 클라이언트 + 커넥션 풀 + lifespan 정리 | ✅ | 유지 |
| 3-4 | | 응답 시간 베이스라인 | 측정 체계 없음 (단발 실측: /search ~0.2s @ 더미 10건·워밍업 후) | ⚠️ | R13 locust 베이스라인 — **다축 확장 전 필수** (9월 추가 비용을 측정하려면 기준점이 있어야 함) |
| 4-1 | **에러 핸들링·로깅** | 오류 계약 | 415/400/413/422/503/429/502 엔드포인트별 명시 + 이중 방어(응답 조립 try) | ✅ | 유지 |
| 4-2 | | 로깅 체계 | ~~logging 전무, print()만~~ → ✔ dictConfig + uvicorn 통일 포맷, `grep print backend/src` 0건 | ✅ | 새 코드도 logger 사용 (print 금지) |
| 4-3 | | 요청 추적성 | ~~없음~~ → ✔ 요청 ID(contextvars) 로그 주입 + `X-Request-ID` 헤더 — 실측 확인 | ✅ | 프론트 오류 화면에 요청 ID 노출 검토(후순위) |
| 4-4 | | 전역 예외 처리 | ~~미처리 예외는 프레임워크 기본~~ → ✔ `@app.exception_handler(Exception)`: traceback 로그 + 스택 미노출 JSON 500 | ✅ | 유지 |
| 5-1 | **테스트 커버리지** | 실행 가능성 | ~~인덱스 없으면 계약 테스트 전부 skip~~ → ✔ 더미 인덱스 픽스처 + 가짜 인코더로 무조건 실행 | ✅ | **48 passed / 0 skipped** (실모드 실측). CI에서도 0 skip |
| 5-2 | | 커버 범위 | 계약 23종 + appno 7 + KIPRIS 파싱·리미터 6 + ✔ scoring 12 + ✔ 캐시 3 + ✔ 마이그레이션 1 | ⚠️ | 남은 공백: collect_pipeline 파싱(레코딩 XML 픽스처), db.py 단위. M2 내 보강 |
| 5-3 | | CI | ~~전무~~ → ✔ GitHub Actions(torch CPU 휠 + postgres 컨테이너 + 가짜 ML 모드) 작성 | ⚠️ | push 후 첫 run green 확인 필요(원격 실행은 push 권한/계정 문제로 미검증). PR 필수화 규칙과 연동 |
| 6-1 | **입력 검증** (추가) | 업로드 방어 | Content-Length 선검사 + 실디코딩 검증(형식/크기/치수) + top_k 클램프 | ✅ | 유지 — 이 영역은 모범 사례 수준 |
| 6-2 | **외부 API 내구성** (추가) | KIPRIS 쿼터 방어 | 월 950 예산 파일 영속 + 초당 간격 + 24h 캐시(✔ 상한 1024 추가) + 429/503/502 매핑 | ✅ | 백엔드-6 실행 시 체크포인트+원본 선저장 추가(일회성 링크 재호출 방지) |
| 6-3 | **인바운드 보호** (추가) | 레이트리밋 | 없음 | ❌ | R12 slowapi: /search 10/min/IP(CPU 보호), /name-check 30/min/IP(쿼터 보호) — 시연 배포 전 |

**체크리스트 요약**: 감사 시점 ❌ 7건 → 조치 후 ❌ 2건(인증, 인바운드 레이트리밋 — 둘 다 R12로 시연 배포 전 해소), ⚠️ 4건. 미배포 로컬 개발 단계임을 감안하면 ❌ 2건은 일정상 허용 가능하나 **외부 시연 URL이 생기는 순간 차단 요건**이다.

---

## 작업 4 — 백엔드 리팩토링 및 고도화 실행 계획

### 원칙

1. **한 명(현수)이 기능과 리팩토링을 병행한다** — 리팩토링은 마일스톤당 가용 시간의 ~35%를 상한으로, 전부 백엔드-N 과업을 de-risk하거나 백엔드-8/9를 준비하는 것만 채택.
2. 순서는 위험×노력: 비가역 손실(git) → 정합성 버그(scoring) → 시연 가시 결함(루프 차단) → 마감(polish).
3. KIPRIS 키가 유일한 외부 하드 의존 — M1 1주차 신청, 쿼터 소모 작업은 전부 dry-run 모드 선비치.

### R-스텝 실행표

| 스텝 | 시기 | 내용 · 기술 선정 (근거) | 완료 기준 (검증 명령) | 상태 |
|---|---|---|---|---|
| R1 | M1 | **git 복구**: 논리 단위 커밋(마이그레이션·DB / KIPRIS / 이중모드 / 테스트 / 프론트 / 문서) → 브랜치 → PR. 중복 클론은 고유 커밋 無 + 클린 트리 확인 후 삭제 | `git status --porcelain` 빈 출력 | ✔ **완료** (6커밋, 클론 삭제. push/PR만 잔여) |
| R2 | M1 | **등급 역전 핫픽스**: 절대 유사도 안전장치 `SIM_IDENTICAL=0.95` — 격차 조건이 완전 일치를 강등 못 하게 ([scoring.py:154](../ml/src/scoring.py)). 회귀 테스트 선작성(TDD). 임계값 전면 재보정은 **R14로 연기**(더미 10건으로 보정은 통계적 무의미) | `pytest ml/tests` green + API 실측: top1=0.99999/gap 0.144 → CAUTION | ✔ **완료** (12 테스트 + API 실증) |
| R3 | M1 | **로깅**: stdlib dictConfig(× loguru — uvicorn 핸들러와 충돌, 수집기 없인 이득 0) + 요청 ID ASGI 미들웨어(contextvars ~50줄) + 전역 예외 핸들러 | `grep -rn "print(" backend/src` 0건, `curl -i /health`에 X-Request-ID | ✔ **완료** |
| R4 | M1 | **루프 차단 해소**: `anyio.to_thread.run_sync` + `CapacityLimiter(2)` (× asyncio 병렬화, × asyncpg 전환 — 동기 DB는 스레드 안에서 옳다). torch/FAISS는 GIL을 놓으므로 스레드 오프로드가 실효 있음. 동시 CLIP 2개 초과는 대기열로(스래싱 방지) | /search 진행 중 /health <100ms | ✔ **완료** (실측 6~7ms) |
| R7 | M2→선행 | **schema_migrations** (× Alembic — SQLAlchemy 모델이 없어 autogenerate 무용, raw SQL 철학에 30줄 업그레이드가 정합) | 2회 연속 실행 → "0 applied" | ✔ **완료** (PostgreSQL 실검증 + 테스트) |
| R8 | M2→선행 | **캐시 강화**: `cachetools.TTLCache(1024)` (× Redis — 단일 프로세스에 브로커 추가는 과잉). 쿼터 보호 장치이므로 백엔드-7 실호출 전 필수 | 가짜 시계 TTL 만료 테스트 green | ✔ **완료** (3 테스트) |
| R6 | M2→선행 | **테스트 인프라+CI**: 더미 FAISS 인덱스 인프로세스 생성 + encode_image 몽키패치 → CLIP 가중치 없이 계약 테스트 상시 실행. GitHub Actions: torch CPU 휠 인덱스(기본 리눅스 휠은 CUDA ~2GB), postgres:16 서비스 컨테이너 | 로컬 `pytest` 48/0 skip ✔. CI 첫 run green(push 후) | ✔ 로컬 완료 / CI run 확인 잔여 |
| R5 | M2 | **pydantic-settings 최소 도입**: env 유래 값만 `Settings` 클래스로(순수 상수는 현행 유지 — 근거 주석 스타일이 좋음). `config.py` 재수출로 호출부 무변경. CORS 기본값을 localhost:3000으로 교체 | 잘못된 env로 기동 시 필드명 명시 실패; `os.getenv`가 Settings 안에만 | 예정 |
| R9 | M2 | **스토리지 분리**(=백엔드-3): 저장소 밖 `STORAGE_DIR` + `core/storage.py` 심 3함수(save/url/open) (× MinIO — 관리할 컨테이너 추가, × AWS S3 지금 — 계정/과금 리스크. 실배포 확정 시 같은 심 뒤로 S3 드롭인). **수집 파이프라인은 파싱 전에 원본 바이트 저장**(일회성 링크 보호) | ml/data/images 없이 서버 기동; 이미지 URL 200 | 예정 |
| R10 | M2~M3 | **ml 패키징**: `ml/src`→`marklens_ml` rename + `pip install -e ./ml`, sys.path 핵 제거, 스크립트 `__file__` 상대화, `DEVICE` env화. **팀 조율 필요**(전원 import 변경) — 단일 PR로 공지 | `grep -rn "sys.path" backend ml` 0건; 아무 cwd에서나 import | 예정 |
| R11 | M3 | **서비스 계층 추출** — 백엔드-8의 실질적 enabler: engine.py → `core/resources.py`(수명) + `services/search_service.py`(오케스트레이터) 분리, `Retriever`/`AxisScorer` Protocol 정의. **축 인터페이스는 batch-first**(`score_batch(query, candidates) → ndarray`) — 후보별 파이썬 루프에서 torch를 부르는 함정 차단. 행위 보존은 R6 계약 테스트로 검증 | 응답 무변화(계약 테스트 green) + Protocol 2종 + CLIP retriever 구현체 | 예정 |
| R12 | M3 | **시연 하드닝**: slowapi(/search 10/min/IP, /name-check 30/min/IP) + 정적 X-API-Key 의존성(설정 시만 활성 — 로컬 무영향) + CORS 실오리진 (× JWT/OAuth — 유저 없음) | 11번째 /search→429; 키 미첨부→401; 타 오리진 차단 | 예정 |
| R13 | M3 | **부하 베이스라인**: locust (× k6 — 파이썬 팀, multipart 업로드 locust가 단순, CPU 바운드 한 자릿수 RPS엔 통찰이 필요하지 광량이 아님). 시나리오: /search 5동시 + /health 1폴링 | locustfile 커밋 + p50/p95 기록 + /health p95<100ms + 5xx 0 | 예정 |
| R14 | M3 | **등급 재보정(F)**: 실데이터 500+건에서 팀 라벨 평가셋 30~50쌍 → 임계값 스윕 → 골든 회귀 테스트로 고정. R2 안전장치는 유지. LR 피처 설계용 분포도 함께 산출 | 근거 주석 포함 임계값 커밋 + 평가 스크립트 + R2 테스트 green | 예정 (데이터 의존) |
| R15 | M4 | **다축 오케스트레이션**(=백엔드-8): ①이미지 1회 인코딩 ②X1·X2 retriever 후보 추림 → `application_no` 병합(출처 보존) ③병합 후보 **1회 배치 DB 조회**(기존 ANY 패턴 확장) ④4축 `score_batch` → 피처 행렬 ⑤LR `predict_proba` + 단독 임계값 오버라이드 ⑥정렬 응답. **전 파이프라인을 단일 to_thread 안의 동기 순수 함수로**(× 축별 asyncio.gather — 20~40 후보의 축 연산은 numpy 마이크로초, 루프 스케줄링 섞으면 지터+복잡도만 증가) | 3입력 검색 E2E + 계약 테스트 green | 예정 (9월) |
| R16 | M4 | **/search 3입력 확장**(=백엔드-9): 기존 필드 전부 유지 + `axes`/`risk_percent`/`verdict` **가산적** 추가 (× /v2 엔드포인트 — 프론트 1개·팀 1개에 버전 분기는 과잉) | 구 필드 생존을 계약 테스트가 강제 | 예정 (9월) |

### 하지 말 것 (과잉 설계 금지 목록)

| 함정 | 금지 근거 |
|---|---|
| Alembic / SQLAlchemy ORM | 모델이 없어 autogenerate 무용. raw SQL + 버전 테이블로 100% 커버 |
| asyncpg / psycopg-async 전환 | 동기 드라이버가 to_thread 안에서 실행되는 현 구조가 이 규모에선 영구히 옳다 |
| Redis (캐시·레이트리밋 백엔드) | 단일 프로세스. Postgres + 인메모리로 충분 |
| Celery / 작업 큐 | 검색은 1~3s 동기 작업. 브로커+워커+장애 모드만 추가된다 |
| MinIO / AWS S3 (현시점) | 이미지 수백 MB에 관리 대상 컨테이너/클라우드 계정 추가 — R9 심 뒤로 후환 |
| TorchServe/Triton/ONNX/GPU | 시연 규모 CPU로 충분. R13 p95가 불허할 때만 재검토 |
| JWT / OAuth / 사용자 시스템 | 유저가 없다. 정적 키 1개 |
| loguru / structlog / JSON 로그 | 수집기 없는 로그 파이프라인 고도화는 무의미 |
| k8s, (Postgres 외) Docker | — |
| 커버리지 % 목표 | 리스크 영역(scoring·db·migrate·KIPRIS 파싱) 타겟팅이 정답 |
| ml 마이크로서비스 분리 | R10 패키지 경계가 운영 비용 없이 같은 모듈성 제공 |

### 횡단 리스크

- **KIPRIS 쿼터 산수**: 500~1,000건 × 건당 2~4회 호출, 상품별 월 1,000회 → **한 번에 다 쓸 수 있는 예산이 아니다**. 수집 파이프라인에 ①레코드별 체크포인트 ②기수집 출원번호 skip ③파싱 전 원본(XML·이미지) 디스크 선저장(일회성 링크 + 파싱 버그가 재호출을 유발하면 안 됨)을 백엔드-5 DoD로 포함.
- **키 발급 지연 시**: R10/R11을 앞당기고 백엔드-6/7을 M2 후반~M3으로 밀어도 크리티컬 패스는 유지된다(계획이 우아하게 열화).
- **팀 조율 포인트 2건뿐**: R10 rename PR, R9 README 셋업 변경 — 각각 단일 공지 PR로.

---

## 부록 — 다음 단계 권고 (요청 템플릿 Next Steps 대응)

1. **CI/CD**: ✔ GitHub Actions 워크플로 작성 완료(테스트 자동화). 배포 자동화(CD)는 시연 호스팅 확정 후 — 현 단계 추가 작업 불요.
2. **부하 테스트**: R13(locust)로 계획 확정. JMeter/k6 대비 선택 근거는 R-스텝 표 참조. **다축 확장 전 베이스라인 확보가 목적** — 9월의 성능 회귀를 수치로 잡는다.
3. **모니터링·로깅 아키텍처**: 현 단계는 R3(요청 ID + 통일 로그)로 충분. Datadog(유료)·ELK(운영 부담)는 배제, 실배포 확정 시 Prometheus + Grafana(무료)를 후보로 — 그 전에 지표를 만들 서버가 1대뿐이다.
4. **API 문서 자동화**: FastAPI가 OpenAPI(/docs, /redoc)를 이미 자동 생성한다 — 별도 Swagger 파이프라인 불요. 실질 과제는 문서가 아니라 **계약의 기계 검증**이며, 이는 R6 계약 테스트가 수행 중. 프론트 계약 중복(수동 미러링)은 백엔드-9 확장 시 openapi-typescript 도입으로 해소 검토.

---

## 이번 감사 세션 실행 요약 (2026-07-08)

| 항목 | 검증 결과 |
|---|---|
| git 복구 | 미커밋 1개월분 → 6개 논리 커밋(`feat/phase2-baseline`), 중복 클론 안전 확인 후 삭제, 작업트리 클린 |
| 등급 역전(R2) | 단위 12 테스트 + API 실측: 동일 로고(top1 0.99999, gap 0.144) → **CAUTION** (구버전: REVIEW 강등) |
| 로깅(R3) | X-Request-ID 응답 헤더 실측, print 0건, 전역 500 핸들러 |
| 루프 차단(R4) | /search 2건 동시 진행 중 /health **6~7ms** |
| 마이그레이션(R7) | PostgreSQL 16.14 실검증: 2회차 실행 "0 applied" |
| 캐시(R8) | TTLCache 상한 1024 + 가짜 시계 만료 테스트 |
| 테스트/CI(R6) | **전체 48 passed / 0 skipped**(실모드), 가짜 ML 모드 35 passed, CI 워크플로 작성 |
| dev 스크립트 | start→health(engine_ready)→front 200→stop→포트 8000/3000 해제, 전 사이클 실동작 확인 |
