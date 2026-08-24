# MarkLens 최종보고서: 13~16주차

| 항목 | 내용 |
|---|---|
| 대상 기간 | 2026-11-23 ~ 2026-12-20 |
| 최종 제출 기준일 | 2026-12-20 |
| 계획 초안 작성일 | 2026-08-15 |
| 문서 상태 | `계획 템플릿 · 신규 수행 예정` |
| 연결 문서 | [16주 마스터 계획](./00_MarkLens_16주_마스터계획.md), [9~12주차 보고서](./03_MarkLens_3차_진행보고서_9-12주.md), [주장·증빙 매핑표](./99_MarkLens_주장_증빙_매핑표.md) |

> MarkLens의 핵심 서비스와 1,000건 데이터는 2026-08-15 현재 기준선으로 확보돼 있으며,
> 1~8주차 보고에서 9~10월 결과로 재현·분석·시연한다. 이 문서의 13~16주차는
> **사람 라벨 200쌍 평가, frozen holdout 단회 평가,
> 운영 리허설, 최종 문서화와 시연을 새로 수행하는 구간**이다.

> 현재 확인된 라벨은 `0/200`이며, 현재 1,000건 artifact는 `git.dirty=true`이다.
> PostgreSQL 실행 경로와 migration은 구현되어 있지만 현재 1,000건 실행은 file mode이고,
> production 환경의 backup·restore는 검증되지 않았다. 최종 제출 전까지 실제로 수행하고
> 증빙한 항목만 `완료`와 과거형으로 바꾼다.

## 1. 제출 정보

| 항목 | 제출본 기입값 |
|---|---|
| 과목명 | 제출 전 입력 |
| 팀명·팀원 | 제출 전 입력 |
| 담당 범위 | 제출 전 입력 |
| 최종 commit/tag | 제출 전 입력 |
| release artifact generation | 제출 전 입력 |
| labeling pack ID | 제출 전 입력 |
| dev freeze receipt | 제출 전 입력 |
| holdout unlock receipt | 제출 전 입력 |
| 실행 환경 | OS, CPU, RAM, Python, Node.js, DB 버전 입력 |

## 2. 보고 범위와 연구 질문

MarkLens는 입력 로고와 수집된 국내 상표 표본 사이의 시각적 근접 후보를 탐색하고,
사용자 입력 상표명의 KIPRIS 완전일치 후보와 권리 근거를 함께 보여 주는 교육·연구용
시스템이다. 등록 가능성, 침해 여부, 법적 안전성을 판정하는 서비스는 아니다.

최종보고서는 다음 질문에 증빙으로 답한다.

1. 사람 라벨 200쌍을 dev 160쌍과 frozen holdout 40쌍으로 오염 없이 분리했는가?
2. dev 160쌍만 사용해 상태 기준과 threshold를 교정하고 재현 가능한 receipt로 동결했는가?
3. 동결 후 holdout 40쌍을 한 번만 평가하고 불리한 결과도 그대로 보존했는가?
4. 1,000건 기준선의 검색 지연, 오류율, 메모리 사용량을 명시된 부하 조건에서 측정했는가?
5. PostgreSQL migration, backup·restore와 주요 보안 경계를 production-like 환경에서 리허설했는가?
6. 현재 기준선, 9~12주차 결과, 이번 기간 신규 성과와 미검증 범위를 날짜와 증빙으로 구분했는가?

## 3. 시작 시점 기준선

아래 값은 2026-08-15에 기록된 **현재 기준선**이다. 13주차 시작 전에
같은 명령과 산출 기준으로 다시 측정하고, 값이 달라졌으면 변경 이유를 기록한다.

| 영역 | 2026-08-15 기준선 | 13주차 시작 시 재확인 | 최종 판정 |
|---|---|---|---|
| 데이터 | rights 1,000 · images 1,000 · vectors 1,000 | 제출 전 실측 | 기준선 확보 |
| 범위 | Nice 45/45 · 자동 visual family 769 | 제출 전 실측 | 기준선 확보 |
| 검색 엔진 | OpenCLIP ViT-B-32 · 512D 정규화 · FAISS IndexFlatIP | 제출 전 확인 | 기준선 확보 |
| 이미지 입력 | PNG/JPEG/WebP 지원 | 제출 전 회귀 | 기준선 확보 |
| SVG/PDF/EPS | 현재 직접 업로드 미지원 | 9~12주차 결과 반영 | 기준선 확보 · 미지원 |
| 손글씨 | raster 업로드 가능 · 전용 benchmark/model 없음 | 9~12주차 결과 반영 | 기준선 확보 · 미평가 |
| 사람 라벨 | 0/200 | 제출 전 실측 | 미착수 |
| 저장소 | PostgreSQL 경로·migration 구현 · 현재 1,000건은 file mode | 제출 전 확인 | 부분 구현 |
| DB 운영 | production backup·restore 미검증 | 15주차 리허설 | 미검증 |
| artifact 상태 | `git.dirty=true` | 제출 전 실측 | release 불가 |
| Python tests | 337 passed · 5 skipped | 제출 전 재실행 | 기준선 확보 |
| frontend tests | 34/34 passed | 제출 전 재실행 | 기준선 확보 |
| E2E tests | 9/9 passed | 제출 전 재실행 | 기준선 확보 |

### 상태 표기 원칙

| 상태 | 사용 조건 |
|---|---|
| 기준선 확보 | 2026-08-15 현재 구현·검증돼 있는 항목 |
| 신규 수행 예정 | 13~16주차에 아직 수행하지 않은 작업 |
| 진행 | 일부 결과와 증빙이 있으나 완료 기준을 충족하지 못한 작업 |
| 완료 | 해당 주차 완료 기준과 증빙 ID를 모두 충족한 작업 |
| 보류 | 수행하지 못한 이유와 후속 조건을 명시한 작업 |

## 4. 13~16주차 실행 요약

| 주차 | 기간 | 신규 수행 항목 | 핵심 산출물 | 제출 판단 기준 |
|---|---|---|---|---|
| 13주차 | 11/23~11/29 | dev 첫 80쌍 라벨링 | split receipt, label 1~80, 품질 점검표 | 유효 dev label 80쌍 |
| 14주차 | 11/30~12/06 | dev 남은 80쌍 라벨링, 교정·동결 | dev 160쌍, calibration report, freeze receipt | holdout 미열람 상태로 결정 동결 |
| 15주차 | 12/07~12/13 | holdout 40쌍 단회 평가, 부하·DB·보안 리허설 | holdout receipt, 성능표, DB 복구 기록, 보안 점검표 | 재교정 없는 단회 평가와 복구 증빙 |
| 16주차 | 12/14~12/20 | 최종 문서·발표·시연·재현 검수 | 최종보고서, 발표자료, 시연 영상, release manifest | 모든 완료 주장에 증빙 연결 |

## 5. 주차별 수행 계획과 결과

### 5.1 13주차: dev 첫 80쌍 라벨링

핵심 질문: **평가 표본을 고정하고 일관된 기준으로 첫 절반을 라벨링했는가?**

| 구분 | 계획 |
|---|---|
| 사전 고정 | 총 200쌍을 visual family 기준으로 dev 160, holdout 40으로 분리하고 split hash 저장 |
| 접근 통제 | holdout 결과와 모델 판정을 dev 교정이 끝날 때까지 숨기거나 봉인 |
| 라벨 스키마 | `similar`, `dissimilar`, `cannot_assess`와 confidence, annotator, reason 기록 |
| 신규 수행 | dev 1~80번 라벨링과 누락·중복·형식 오류 점검 |
| 표본 검수 | 동일 family의 dev·holdout 교차 포함 여부와 near-duplicate 누수 확인 |
| 완료 기준 | 유효 dev label 80쌍, 필수 필드 누락 0, family leakage 0 |
| 증빙 ID | `RF-W13-SPLIT`, `RF-W13-L80`, `RF-W13-QA` |
| 실제 결과 | 제출 전 입력 |
| 상태 | 신규 수행 예정 |

13주차 결과 기록:

| 지표 | 목표 | 실제값 | 증빙 |
|---|---:|---:|---|
| dev labeled | 80 | 제출 전 실측 | 제출 전 입력 |
| 필수 필드 누락 | 0 | 제출 전 실측 | 제출 전 입력 |
| 중복 pair | 0 | 제출 전 실측 | 제출 전 입력 |
| dev·holdout family leakage | 0 | 제출 전 실측 | 제출 전 입력 |
| `cannot_assess` | 관측값 보고 | 제출 전 실측 | 제출 전 입력 |

### 5.2 14주차: dev 160쌍 완성, 교정과 동결

핵심 질문: **holdout을 보지 않고 dev만으로 최종 판단 규칙을 정했는가?**

| 구분 | 계획 |
|---|---|
| 신규 수행 | dev 81~160번 라벨링, 전체 160쌍 품질 점검 |
| 교정 | dev에서 threshold와 사용자 상태 표현을 비교하고 선택 근거 기록 |
| 분석 | precision·recall·F1·PR-AUC, confusion matrix, slice, 대표 실패 사례 산출 |
| 동결 | commit, artifact generation, 전처리, 모델, score 식, threshold, 코드 hash를 receipt로 저장 |
| 금지 | holdout label·결과를 확인한 뒤 threshold, 모델, 전처리를 바꾸는 행위 |
| 완료 기준 | dev 160/160, 누락 0, calibration report, holdout 미열람 확인, freeze receipt 생성 |
| 증빙 ID | `RF-W14-L160`, `RF-W14-CAL`, `RF-W14-FREEZE` |
| 실제 결과 | 제출 전 입력 |
| 상태 | 신규 수행 예정 |

동결 항목:

| 항목 | 동결값 | hash 또는 경로 |
|---|---|---|
| source commit | 제출 전 입력 | 제출 전 입력 |
| artifact generation | 제출 전 입력 | 제출 전 입력 |
| model·weights | 제출 전 입력 | 제출 전 입력 |
| preprocessing contract | 제출 전 입력 | 제출 전 입력 |
| scoring formula | 제출 전 입력 | 제출 전 입력 |
| decision threshold | 제출 전 입력 | 제출 전 입력 |
| label pack | 제출 전 입력 | 제출 전 입력 |
| dev metrics | 제출 전 입력 | 제출 전 입력 |

### 5.3 15주차: frozen holdout 단회 평가와 운영 리허설

핵심 질문: **동결된 시스템을 한 번만 평가하고 운영 실패 경로까지 검증했는가?**

holdout 선행조건 중 하나라도 충족하지 못하면 평가를 시작하지 않고 차단 사유를 기록한다.

| 구분 | 계획 |
|---|---|
| holdout gate | dev 160/160, freeze receipt, unresolved issue 목록, commit·artifact hash 일치 확인 |
| 단회 평가 | frozen holdout 40쌍을 한 번 unlock하고 동일한 평가 코드로 결과 생성 |
| 결과 보존 | 기대보다 낮은 결과도 원본 receipt와 함께 보존하고 headline 지표를 재교정하지 않음 |
| 부하 시험 | warm/cold, 동시 사용자 수, 요청 수, 측정 시간을 고정해 p50/p95/p99와 오류율 측정 |
| PostgreSQL | migration 적용, file→DB 동등성, backup, 새 인스턴스 restore, checksum·조회 검증 |
| 보안 | API key, Turnstile, TLS proxy, rate limit, request ID, 입력 크기·MIME, egress와 변조 차단 리허설 |
| 완료 기준 | holdout unlock 1회, 재교정 0회, 부하 조건 공개, DB 복구 증빙, 보안 점검 결과 보존 |
| 증빙 ID | `RF-W15-HOLDOUT`, `RF-W15-LOAD`, `RF-W15-DB`, `RF-W15-SEC` |
| 실제 결과 | 제출 전 입력 |
| 상태 | 신규 수행 예정 |

> DB 항목은 실제 production 운영 완료를 주장하는 단계가 아니다. 로컬 또는 격리된
> production-like 환경에서 수행한 rehearsal의 환경, 명령, 소요 시간, 실패와 복구 결과를
> 기록한다. production에서 직접 확인하지 않았다면 최종 판정도 `production 미검증`으로 남긴다.

### 5.4 16주차: 최종 문서, 발표와 시연

핵심 질문: **성과, 실패, 미검증 범위를 다른 사람이 재현할 수 있게 설명했는가?**

| 구분 | 계획 |
|---|---|
| 결과 통합 | 현재 기준선, 9~12주차 신규 실험, dev·holdout, 운영 리허설을 날짜별로 통합 |
| release 검수 | clean worktree, 최종 tag, dependency lock, artifact manifest와 checksum 확인 |
| 문서 | README, API 계약, 데이터·모델 카드, 오류 taxonomy, 보안·배포 경계, 재현 안내서 갱신 |
| 발표 | 문제, 방법, 데이터, 지표, 시각화, 실패 사례, 한계, 후속 과제 순서로 발표자료 제작 |
| 시연 | raster 검색, 이름 근거, 상세 후보, 지원 형식, 실패 입력과 복구 흐름을 실제 화면으로 확인 |
| 표현 검수 | mock·fixture와 live 결과 구분, 등록 가능성·침해 확률·법적 안전 표현 제거 |
| 완료 기준 | 미측정 placeholder 0건, 모든 완료 주장에 증빙 ID, 최종 영상·발표자료·재현 기록 확보 |
| 증빙 ID | `RF-W16-REL`, `RF-W16-DOC`, `RF-W16-SLIDE`, `RF-W16-VIDEO` |
| 실제 결과 | 제출 전 입력 |
| 상태 | 신규 수행 예정 |

## 6. 라벨링과 평가 프로토콜

### 6.1 데이터 분리

| 구분 | 수량 | 사용 목적 | 교정 사용 | 공개 시점 |
|---|---:|---|---|---|
| Dev A | 80 | 13주차 1차 라벨링·기준 점검 | 가능 | 13주차 |
| Dev B | 80 | 14주차 2차 라벨링·최종 교정 | 가능 | 14주차 |
| Frozen holdout | 40 | 동결 뒤 단회 평가 | 금지 | 15주차 unlock 뒤 |
| 합계 | 200 | bounded 평가 팩 | 해당 없음 | 해당 없음 |

분할 단위는 개별 이미지가 아니라 visual family를 우선한다. 같은 원본 또는 byte-identical,
near-duplicate, 동일 visual family가 dev와 holdout에 동시에 들어가면 누수로 판정한다.

### 6.2 라벨 계약

| 필드 | 허용값 또는 규칙 |
|---|---|
| `label` | `similar`, `dissimilar`, `cannot_assess` |
| `confidence` | 문서에 고정한 척도 사용, 예: 1~5 |
| `annotator` | 익명 식별자, 빈 값 금지 |
| `reason` | 핵심 형태·문자·구도 또는 판정 불가 이유 |
| `created_at` | ISO 8601 timestamp |
| `pair_id` | 평가 팩에서 유일하며 수정 금지 |

검수자가 한 명이면 inter-rater agreement를 측정한 것처럼 쓰지 않는다. 두 명 이상이면
불일치율과 합의 절차를 별도로 보고하고, 원래 라벨도 보존한다.

### 6.3 holdout 오염 방지 규칙

1. 14주차 freeze receipt 생성 전에는 holdout 정답과 결과를 열지 않는다.
2. receipt에는 commit, artifact generation, 모델, 전처리, score 식, threshold를 포함한다.
3. 15주차 unlock 횟수는 1회이며 시간과 실행자를 기록한다.
4. holdout 실행 뒤 발생한 코드·설정 변경은 기존 성능의 일부로 합치지 않는다.
5. 재평가가 필요하면 첫 결과를 실패 포함 그대로 보존하고 새 평가 세대를 후속 과제로 분리한다.

## 7. 평가 결과 입력표

### 7.1 라벨 무결성

| 항목 | 기준선 | 목표 | 최종값 | 판정 | 증빙 |
|---|---:|---:|---:|---|---|
| dev labeled | 0 | 160 | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |
| holdout labeled/evaluated | 0 | 40 | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |
| 필수 필드 누락 | 해당 없음 | 0 | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |
| 중복 pair | 해당 없음 | 0 | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |
| family leakage | 해당 없음 | 0 | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |
| dev hash 일치 | 해당 없음 | true | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |
| holdout unlock | 0 | 1 | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |
| holdout 뒤 재교정 | 0 | 0 | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |

### 7.2 Dev calibration

| 후보 규칙 | Threshold | Precision | Recall | F1 | PR-AUC | 채택 여부·근거 |
|---|---:|---:|---:|---:|---:|---|
| 기존 기준선 | 제출 전 입력 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| 후보 A | 제출 전 입력 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| 후보 B | 제출 전 입력 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| 최종 동결 | 제출 전 입력 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |

### 7.3 Frozen holdout 단회 결과

| 지표 | Dev | Frozen holdout | 차이 | 해석 |
|---|---:|---:|---:|---|
| Precision | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| Recall | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| F1 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| PR-AUC | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| `cannot_assess` 비율 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |

| holdout 실행 기록 | 값 |
|---|---|
| unlock 일시 | 제출 전 입력 |
| unlock 횟수 | 제출 전 입력 |
| 실행 commit | 제출 전 입력 |
| artifact generation | 제출 전 입력 |
| freeze receipt hash | 제출 전 입력 |
| result hash | 제출 전 입력 |
| 실행 뒤 변경 여부 | 제출 전 입력 |

### 7.4 Slice와 실패 사례

| Slice | N | Precision | Recall | F1 | 대표 실패 원인 |
|---|---:|---:|---:|---:|---|
| 문자 중심 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| 도형 중심 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| 결합형 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| 동일·근접 family | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| 저품질 입력 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| 9~12주차 신규 cohort | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |

## 8. 운영 검증 결과 입력표

### 8.1 부하 시험

모든 수치는 hardware, dataset generation, warm-up 횟수, 동시성, 총 요청 수, 측정 도구와
timeout을 함께 기록해야 비교 가능한 값으로 인정한다.

| 시나리오 | N | 동시성 | p50 | p95 | p99 | RPS | 오류율 | peak memory |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| raster search warm | 제출 전 실측 | 제출 전 입력 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 |
| raster search cold | 제출 전 실측 | 제출 전 입력 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 |
| name-check cached | 제출 전 실측 | 제출 전 입력 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 |
| 9~12주차 신규 입력 경로 | 제출 전 실측 | 제출 전 입력 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 |

### 8.2 PostgreSQL migration과 복구

| 단계 | 수행 환경·명령 | 기대 결과 | 실제 결과 | 소요 시간 | 증빙 | 판정 |
|---|---|---|---|---:|---|---|
| migration apply | 제출 전 입력 | schema 생성 성공 | 제출 전 입력 | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |
| file→DB 적재 | 제출 전 입력 | 건수·키 보존 | 제출 전 입력 | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |
| 결과 동등성 | 제출 전 입력 | 표본 검색 결과 일치 | 제출 전 입력 | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |
| backup 생성 | 제출 전 입력 | 복원 가능한 dump | 제출 전 입력 | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |
| 새 인스턴스 restore | 제출 전 입력 | 오류 없이 복원 | 제출 전 입력 | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |
| 복구 후 검증 | 제출 전 입력 | row count·checksum·조회 통과 | 제출 전 입력 | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |
| rollback rehearsal | 제출 전 입력 | 정의된 복귀점으로 복구 | 제출 전 입력 | 제출 전 실측 | 제출 전 입력 | 제출 전 입력 |

최종 판정은 다음 중 하나만 사용한다.

- `file mode만 검증`: DB 경로를 실제 검증하지 못함
- `production-like rehearsal 완료`: 격리 환경에서 migration·backup·restore 증빙 확보
- `production 검증 완료`: 실제 production에서 별도 승인과 증빙을 확보한 경우에만 사용

### 8.3 보안 리허설

| 점검 항목 | 공격·실패 조건 | 기대 동작 | 실제 결과 | 증빙 | 판정 |
|---|---|---|---|---|---|
| API key 비노출 | 브라우저 bundle·응답·로그 확인 | secret 미노출 | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 |
| Turnstile | 무효 token·허용되지 않은 hostname | 요청 차단 | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 |
| TLS proxy | HTTP 직접 접근 | redirect 또는 차단 | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 |
| rate limit | 동일 client 반복 요청 | 정책대로 429 | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 |
| 입력 검증 | 초과 크기·위조 MIME·손상 파일 | 4xx와 안전한 오류 | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 |
| request ID | 프론트→BFF→API 오류 | 동일 ID 추적 | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 |
| egress 제한 | 허용 목록 밖 URL·redirect | 외부 요청 차단 | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 |
| artifact 변조 | index·manifest·image 불일치 | fail-closed | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 |
| 로그 위생 | token·개인정보 포함 요청 | 민감값 마스킹 | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 |

## 9. 학기 누적 성과 요약

| 영역 | 2026-08-15 현재 기준선 | 9~12주차 입력 | 13~16주차 신규 결과 | 최종 판정 |
|---|---|---|---|---|
| 데이터·검색 | 1,000 rights/images/vectors, 769 families | 제출 전 요약 | 재현·부하 결과 입력 | 제출 전 입력 |
| 입력 형식 | raster 지원, SVG/PDF/EPS 미지원 | 신규 실험 결과 입력 | 최종 지원 범위 동결 | 제출 전 입력 |
| 손글씨 | 일반 raster 가능, 전용 평가 없음 | bounded benchmark 결과 입력 | 최종 한계 반영 | 제출 전 입력 |
| 사람 라벨 | 0/200 | 해당 없음 | dev 160 + holdout 40 | 제출 전 입력 |
| 상태 기준 | 사람 교정 전 임시 기준 | 해당 없음 | dev calibration + holdout | 제출 전 입력 |
| 저장소 | PostgreSQL 경로 구현, file mode 실행 | 해당 없음 | backup·restore rehearsal | 제출 전 입력 |
| 보안·운영 | 로컬 테스트 기준선 | 신규 입력 보안 결과 입력 | 부하·보안 rehearsal | 제출 전 입력 |
| release | `git.dirty=true` artifact | 제출 전 갱신 | clean tag·manifest | 제출 전 입력 |

## 10. 주장과 증빙 매핑

최종 수치와 스크린샷 경로는 [주장·증빙 매핑표](./99_MarkLens_주장_증빙_매핑표.md)에
먼저 등록한 뒤 본문에 반영한다.

| 최종 주장 | 필요한 증빙 | 증빙 ID | 검수 상태 |
|---|---|---|---|
| dev 160쌍 라벨 완료 | label receipt, 누락·누수 검사 | 제출 전 입력 | 제출 전 입력 |
| threshold 동결 | calibration report, freeze receipt | 제출 전 입력 | 제출 전 입력 |
| holdout 40쌍 단회 평가 | unlock receipt, result hash, 실행 로그 | 제출 전 입력 | 제출 전 입력 |
| 부하 성능 | 환경 명세, 원시 결과, 요약표 | 제출 전 입력 | 제출 전 입력 |
| DB 복구 가능 | backup, restore log, checksum·query 결과 | 제출 전 입력 | 제출 전 입력 |
| 보안 경계 동작 | 음성·양성 fixture와 결과 로그 | 제출 전 입력 | 제출 전 입력 |
| 최종 release 재현 | clean commit/tag, manifest, test report | 제출 전 입력 | 제출 전 입력 |
| 시연 화면 동작 | 날짜가 보이는 캡처 또는 영상 | 제출 전 입력 | 제출 전 입력 |

## 11. 최종 산출물

| 산출물 | 경로 또는 링크 | 상태 | 증빙 ID |
|---|---|---|---|
| source code tag | 제출 전 입력 | 신규 수행 예정 | `RF-W16-REL` |
| release artifact manifest | 제출 전 입력 | 신규 수행 예정 | 제출 전 입력 |
| labeling pack·split receipt | 제출 전 입력 | 신규 수행 예정 | `RF-W13-SPLIT` |
| dev calibration·freeze receipt | 제출 전 입력 | 신규 수행 예정 | `RF-W14-FREEZE` |
| frozen holdout report | 제출 전 입력 | 신규 수행 예정 | `RF-W15-HOLDOUT` |
| load report | 제출 전 입력 | 신규 수행 예정 | `RF-W15-LOAD` |
| DB backup·restore report | 제출 전 입력 | 신규 수행 예정 | `RF-W15-DB` |
| security rehearsal report | 제출 전 입력 | 신규 수행 예정 | `RF-W15-SEC` |
| data·model card | 제출 전 입력 | 신규 수행 예정 | 제출 전 입력 |
| final slides | 제출 전 입력 | 신규 수행 예정 | `RF-W16-SLIDE` |
| demo video | 제출 전 입력 | 신규 수행 예정 | `RF-W16-VIDEO` |
| reproducibility guide | 제출 전 입력 | 신규 수행 예정 | `RF-W16-DOC` |

## 12. 최종 시연 시나리오

| 순서 | 시연 내용 | 반드시 보여 줄 근거 | 실패 시 대체 증빙 |
|---|---|---|---|
| 1 | 서비스와 artifact 상태 확인 | generation, rights/images/vectors 수, commit | manifest·검증 로그 |
| 2 | raster 로고 업로드와 후보 검색 | crop, 점수 구성, visual family, 상세 권리 | 녹화 영상 |
| 3 | 상표명 검색과 중복 후보 상세 | live 또는 fixture 표기, KIPRIS 근거 링크 | 응답 fixture와 계약 테스트 |
| 4 | 9~12주차 신규 입력 경로 | 지원 형식과 거부 형식, latency | 실험 보고서 |
| 5 | 실패 입력과 복구 | 안전한 오류, request ID, 재시도 경계 | E2E·보안 로그 |
| 6 | 평가 대시보드 | dev·holdout 분리, confusion matrix, slice | 정적 결과 이미지 |

BBQ 등 fixture로 만든 화면은 `fixture`라고 표시하고 live KIPRIS 1,000건 검증으로 표현하지
않는다. 화면의 후보 수와 실제 API 응답 범위가 다르면 양쪽을 별도 결과로 설명한다.

## 13. 실패 사례와 한계

| 범주 | 사례 수 | 대표 원인 | 대응 | 최종 상태 |
|---|---:|---|---|---|
| 시각 검색 false positive | 제출 전 실측 | 제출 전 입력 | 후보 근거·family 표시 | 제출 전 입력 |
| 시각 검색 false negative | 제출 전 실측 | 제출 전 입력 | slice와 재업로드 기준 기록 | 제출 전 입력 |
| `cannot_assess` | 제출 전 실측 | 제출 전 입력 | 별도 집계 | 제출 전 입력 |
| 이름 메타데이터 누락 | 제출 전 실측 | 제출 전 입력 | missing 명시 | 제출 전 입력 |
| DB rehearsal 실패 | 제출 전 실측 | 제출 전 입력 | file mode fallback·복구 기록 | 제출 전 입력 |
| 부하·보안 실패 | 제출 전 실측 | 제출 전 입력 | 차단 또는 후속 조건 | 제출 전 입력 |

반드시 남길 한계:

- 1,000건 수집 표본은 국내 전체 선행 권리를 대표하지 않는다.
- 권리 수, 이미지 수, visual family 수, 사람 라벨 수는 서로 다른 단위다.
- 사람 라벨 200쌍은 전체 정확도가 아니라 제한된 평가 팩의 결과다.
- holdout 40쌍은 신뢰구간과 slice 해석에 한계가 있으므로 과도하게 일반화하지 않는다.
- 검색 점수와 상태는 등록 가능성, 침해 가능성 또는 법적 안전 확률이 아니다.
- production-like rehearsal은 실제 production 운영 완료와 동일하지 않다.
- KIPRIS 공식 검색과 변리사 등 전문가의 판단을 대체하지 않는다.

## 14. 팀 기여도

팀 합의와 Git·문서·실험 증빙으로만 채운다.

| 팀원 | 구현 | 실험·데이터 | 문서·발표 | commit·증빙 |
|---|---|---|---|---|
| 제출 전 입력 | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 |
| 제출 전 입력 | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 |
| 제출 전 입력 | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 | 제출 전 입력 |

## 15. 교수님께 확인받을 사항

1. 사람 라벨 200쌍과 holdout 40쌍을 학부 프로젝트의 bounded 평가로 제시하는 범위가 적절한가?
2. holdout 성능이 기대보다 낮아도 재교정하지 않고 실패 결과 자체를 최종 성과로 보고해도 되는가?
3. 한 명이 라벨링하는 경우 agreement 대신 품질 규칙과 한계를 명시하는 방식이 충분한가?
4. production-like DB·보안 rehearsal을 운영 검증 범위로 인정받으려면 추가할 조건이 있는가?
5. 공개 시연에서 KIPRIS 이미지·메타데이터와 live·fixture 결과를 어느 수준까지 보여 줄 수 있는가?

## 16. 최종 제출 체크리스트

- [ ] 모든 `제출 전 입력`, `제출 전 실측`, `신규 수행 예정` placeholder를 실제 상태로 교체
- [ ] 기준선 관찰일, 학기 중 수행일, 최종 재검증일을 서로 바꾸지 않고 기록
- [ ] 모든 완료 주장과 핵심 수치를 증빙 ID에 연결
- [ ] dev 160과 holdout 40의 family leakage 0 확인
- [ ] freeze receipt와 holdout unlock 1회 기록 보존
- [ ] holdout 확인 뒤 재교정하지 않았거나, 변경을 별도 후속 실험으로 명시
- [ ] 부하 시험의 hardware·동시성·요청 수·warm-up·timeout 기록
- [ ] DB backup 파일뿐 아니라 새 인스턴스 restore와 검증 결과 첨부
- [ ] production-like와 production 검증을 구분
- [ ] 최종 commit/tag, dependency lock, artifact generation과 manifest 일치
- [ ] release artifact의 `git.dirty=false` 확인 또는 dirty 사유 명시
- [ ] backend·ML·frontend·E2E·artifact 회귀 결과 갱신
- [ ] mock·fixture·live API 결과를 화면과 문서에서 구분
- [ ] 성공 사례와 실패 사례를 같은 산출 기준으로 보고
- [ ] secrets, 개인정보, 실제 서명, 로컬 절대 경로 제거
- [ ] 등록 가능성·침해 확률·법적 안전성을 암시하는 표현 제거
- [ ] 최종 발표자료, 시연 영상, 재현 안내서의 링크와 접근 권한 확인

## 17. 최종 요약 작성 틀

아래 문장은 모든 placeholder를 실제 측정값으로 교체하고 증빙 검수를 마친 뒤에만 사용한다.

> MarkLens는 2026-08-15 현재 확보된 권리·이미지·벡터 1,000건 기준선을 바탕으로
> 2학기 연구를 진행했다. 13~14주차에는 사람 라벨 dev 160쌍을 구축하고
> `제출 전 입력` 기준으로 검색 상태와 threshold를 동결했다. 15주차에는 frozen holdout
> 40쌍을 한 번만 평가해 Precision `제출 전 실측`, Recall `제출 전 실측`, F1
> `제출 전 실측`을 얻었으며, 결과 확인 뒤 headline 기준을 재교정하지 않았다. 같은 주에
> `제출 전 입력` 조건의 부하 시험과 PostgreSQL backup·restore, 보안 리허설을 수행해
> `제출 전 입력` 범위까지 검증했다. 이 결과는 상표의 등록 가능성이나 침해를 판단하는
> 확률이 아니라, 시각적으로 검토할 선행 후보와 근거를 빠르게 찾기 위한 bounded 연구 결과다.
