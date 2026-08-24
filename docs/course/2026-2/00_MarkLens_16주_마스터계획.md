# MarkLens 2026-2학기 16주 마스터 계획

작성 기준일: 2026-08-15
학기: 2026-08-31 ~ 2026-12-20
문서 상태: `현재 기준선 + 학기 연구 계획`
보고 주기: 4주

## 1. 학기 목표

현재 MarkLens는 1,000건의 등록상표 권리 레코드에서 OpenCLIP·FAISS로 시각적으로
가까운 후보를 찾고, KIPRIS 상표명 완전일치 결과와 근거 대시보드를 보여 주는 로컬
연구 베타까지 구현했습니다.

현재 기준선은 코드·artifact·실행 기록으로 확인됩니다. 9~10월에는 이 기준선을
학기 프로젝트 일정에 맞춰 동일 환경에서 재현·분석·시연·문서화합니다.
아래 주차에는 학기 중 수행과 보고 활동을 배치하며, 제출 시 commit과 실측 날짜를
증빙 매핑표에 기록합니다.

2학기에는 기능 수를 무조건 늘리기보다 다음 연구 질문을 증거로 답합니다.

1. 벡터 그래픽 원본을 안전하고 재현 가능하게 래스터화해 기존 검색과 연결할 수 있는가?
2. 손글씨·캘리그래피형 워드마크에서도 현재 외관 검색이 어느 정도 유지되는가?
3. 사람 라벨을 이용해 현재 임시 상태 임계값을 교정할 수 있는가?
4. 중복 권리와 데이터 편향을 분리한 평가가 가능한가?
5. 같은 데이터·모델·전처리로 결과를 다시 만들고 운영 오류를 조기에 차단할 수 있는가?

결과는 상표 등록 가능성이나 침해 확률이 아니라 **선행 후보 탐색을 위한 판단 보조
근거**로 한정합니다.

## 2. 현재 기준선

아래 항목은 2026-08-15 현재 확보된 기준선이며, 학기 중 지정 주차에 다시 검증합니다.

| 항목 | 2026-08-15 상태 | 학기 중 개선 방향 |
|---|---|---|
| 검색 풀 | 권리·이미지·벡터 각 1,000건 | rights 수와 visual family 수를 분리해 평가 |
| 데이터 범위 | Nice 45/45류, 시각 그룹 769개 | 10건 미만 12개 류와 편향을 우선 보완 |
| 임베딩 | OpenCLIP ViT-B/32, 512차원 L2 벡터 | 새 모델보다 현 모델의 입력별 기준선부터 측정 |
| 검색 | FAISS IndexFlatIP Top-K | family 단위 반복 후보 완화 실험 |
| 사용자 이미지 | PNG·JPEG·WebP, 10MB 이하 | 안전한 SVG query v1을 실험적으로 추가 |
| 손글씨 | 래스터 파일 입력 자체는 가능 | 전용 표본·정답·성능 근거는 아직 없음 |
| 이름 확인 | 사용자 직접 입력 문자열로 KIPRIS 조회 | OCR이 아닌 X1 호칭 보조 실험을 후반부에 검토 |
| 사람 라벨 | development 160 + frozen holdout 40 팩, 라벨 0/200 | dev 완료 후 결정 동결, 마지막에 holdout 1회 평가 |
| 배포 | 로컬 연구 베타 | production 유사 환경의 부하·보안·DB rehearsal |

### 현재 확인된 입력 정규화 문제

운영 이미지 1,000개는 파일명이 모두 `.png`이지만 실제 디코드 결과는 PNG 100개,
JPEG 900개입니다. 파일은 모두 읽을 수 있으나, 수집 응답 bytes를 `.png` 이름으로
저장해 확장자·MIME·실제 형식이 어긋난 상태입니다. SVG 지원 전에 다음 계층을 먼저
고칩니다.

1. 다운로드 본문 크기와 Content-Type 상한 검증
2. 실제 이미지 디코드와 치수·픽셀·decompression-bomb 검사
3. EXIF 보정과 RGB/RGBA 변환
4. canonical PNG 또는 WebP 재인코딩
5. 실제 형식·확장자·MIME·SHA-256 일치 감사

이 작업은 새 알고리즘처럼 보이기 위한 부가 기능이 아니라 이후 벡터 입력의 재현성과
결과 이미지 전달 계약을 보장하는 선행조건입니다.

## 3. 16주 일정

1~8주차는 `기준선 확보 / 학기 검증 예정`이며, 해당 주차에 재실행·분석·발표합니다.
9~16주차 신규 연구는 작성 시점에 `계획`입니다.

| 주차 | 기간 | 학기 중 수행·연구 주제 | 주간 활동과 산출물 | 개발 상태 / 학기 활동 |
|---:|---|---|---|---|
| 1 | 08/31~09/06 | MVP 기준선과 전면 기술감사 | `main` 100건 기록, OpenCLIP·FAISS·FastAPI, post-main 작업을 학기 기준선으로 재현 | 기준선 확보 / 학기 검증 예정 |
| 2 | 09/07~09/13 | 저장 계층과 재실행 환경 | PostgreSQL schema·migration·file/DB 이중 경로·환경설정·시작/종료 절차 분석 | 기준선 확보 / 학기 검증 예정 |
| 3 | 09/14~09/20 | KIPRIS API와 명칭 중복 확인 | HTTPS client, `/name-check`, 후보 상세와 BBQ 시나리오 재현 | 기준선 확보 / 학기 검증 예정 |
| 4 | 09/21~09/27 | Next.js 대시보드와 1차 시연 | upload·crop·검색·명칭 후보·모바일 E2E를 시연하고 1차 보고서 제출 | 기준선 확보 / 학기 검증 예정 |
| 5 | 09/28~10/04 | 수집기 안정화와 BBQ 파일럿 | 원본 선저장·checkpoint·retry·Advanced Search, 100→105 계보 분석 | 기준선 확보 / 학기 검증 예정 |
| 6 | 10/05~10/11 | 월 한도 내 105→1,000건 확장 | staging·audit·quarantine·원자 승격과 데이터 분포를 재현·시각화 | 기준선 확보 / 학기 검증 예정 |
| 7 | 10/12~10/18 | 검색 알고리즘·artifact·강건성 | scoring 역전 수정, manifest·SHA, 25+100 query, 769 family를 분석 | 기준선 확보 / 학기 검증 예정 |
| 8 | 10/19~10/25 | 보안·운영 경계와 통합검증 | BFF·Turnstile·rate limit·CI·1,000 runtime 근거를 묶어 2차 시연 | 기준선 확보 / 학기 검증 예정 |
| 9 | 10/26~11/01 | canonical 이미지 정규화 | JPEG/PNG 불일치 해결, 다운로드 상한·decode·재인코딩·MIME 감사 | 신규 구현 계획 / 계획 |
| 10 | 11/02~11/08 | 격리 SVG query v1 | 외부 참조 차단, low-privilege renderer, safe raster preview | 신규 구현 계획 / 계획 |
| 11 | 11/09~11/15 | 벡터 동등성 평가 | SVG·기준 PNG·배경·wide 변형 120개 이상 paired benchmark | 신규 실험 계획 / 계획 |
| 12 | 11/16~11/22 | 손글씨 강건성 평가 | 30 identity·90 query 이상 slice 평가와 3차 보고서 | 신규 실험 계획 / 계획 |
| 13 | 11/23~11/29 | development 사람 검수 | visual-only dev 160쌍 중 1차 80쌍 | 신규 실험 계획 / 계획 |
| 14 | 11/30~12/06 | 라벨 완결과 dev 교정 | 나머지 80쌍, 저신뢰 재검토, 임계값 결정 동결 | 신규 실험 계획 / 계획 |
| 15 | 12/07~12/13 | holdout·운영·재현 검증 | frozen 40쌍 단회 평가, 부하·DB·보안 rehearsal | 신규 실험 계획 / 계획 |
| 16 | 12/14~12/20 | 최종 분석과 제출 | 전체 결과·한계·기여도, 최종보고서·발표·영상 | 신규 제출 계획 / 계획 |

## 4. 4주 단위 마일스톤

### M1. 1차 제출, 2026-09-27

현재 기준선을 학기 프로젝트 일정에 맞춰 다음과 같이 재현·시연합니다.

- OpenCLIP·FAISS·FastAPI MVP와 Git 기준선
- PostgreSQL 저장 계층과 현재 file mode의 차이
- KIPRIS 명칭 확인·후보 상세와 BBQ 시나리오
- Next.js 검색·crop·근거 대시보드·모바일 E2E

### M2. 2차 제출, 2026-10-25

10월까지의 핵심 성과는 **1,000건 데이터 운영과 검색·보안 근거의 통합 분석**입니다.

- BBQ 5건 파일럿과 100→105→1,000 데이터 계보
- 권리·이미지·벡터 1,000건, Nice 45/45류, 769 visual family
- scoring 역전 수정과 고정 `scoring_k`, manifest·해시 fail-closed
- 25개 원본·100개 변형의 bounded 강건성 실측
- BFF·API key·Turnstile·rate limit·request ID 보안 경계
- Python·frontend·E2E·1,000 runtime 검증의 학기 중 재실행 결과

8월 수치는 현재 기준선이며, 학기 중 다시 실행한 수치만 주차 검증 결과로 표시합니다.

### M3. 3차 제출, 2026-11-22

- canonical 이미지 형식·MIME 일치
- feature flag 뒤의 safe SVG query v1
- vector equivalence 120개 이상 query
- handwriting 30 identity·90 query 이상 benchmark

### M4. 최종 제출, 2026-12-20

- development 160쌍과 frozen holdout 40쌍의 분리 평가
- 부하·보안·PostgreSQL 운영 rehearsal
- 최종 모델·데이터 카드와 재현 안내서
- 완료·진행·보류를 구분한 최종 발표

## 5. 벡터 그래픽 실험 계약

### 5.1 11월 신규 실험 범위

| 형식 | 계획 | 이유 |
|---|---|---|
| SVG | query 입력 v1 실험 | XML 기반 공격면을 통제하면서 재현 가능한 rasterization 가능 |
| PDF | `Stretch`: page 1 단일 표장 feasibility만 | 다중 페이지·내장 폰트·복합 객체 정책이 별도 필요 |
| EPS/PostScript | 거부 | 인터프리터 공격면과 운영 복잡도가 큼 |
| AI/CDR | 거부 | 폐쇄 형식과 재현성 문제, 학기 핵심 범위 아님 |

### 5.2 보안 완료 기준

- DOCTYPE·entity·script·`foreignObject` 차단
- 외부 HTTP/HTTPS/file URI와 외부 font·image 참조 차단
- data URI 크기, DOM depth, element/path 수, viewBox와 렌더 시간 상한
- renderer에서 네트워크 0, 작업공간 파일 접근 0
- timeout·메모리 상한 초과 시 일반 4xx 오류로 중단
- raw SVG를 결과 이미지나 브라우저 crop 입력으로 직접 재사용하지 않음
- canonical output의 실제 MIME·확장자·SHA-256 기록

### 5.3 채택 지표

| 지표 | 최소 보고 |
|---|---|
| decode/raster 성공률 | 유효 fixture 성공, 악성 fixture 차단을 분리 |
| 결정성 | 같은 입력·renderer version의 output SHA 일치율 |
| 검색 동등성 | SVG raster와 기준 PNG의 top-1 agreement, family Recall@1/@5 |
| 표현 안정성 | 투명·흰·검정 배경, wide viewBox별 target cosine |
| 성능 | p50/p95 변환시간, 최대 메모리, timeout 비율 |
| 회귀 | 기존 PNG/JPEG/WebP 계약과 E2E가 그대로 통과하는지 |

## 6. 손글씨·캘리그래피 실험 계약

### 6.1 범위

손글씨를 문자로 읽는 OCR 기능이 아니라, 손글씨형 표장이 동일하거나 가까운 시각
후보를 유지하는지 측정합니다. 이름 확인은 계속 사용자가 입력한 문자열과 KIPRIS
결과를 사용합니다.

실제 서명, 주민 이름, 타인의 필체를 수집하지 않습니다. 창작한 허구 문자열,
동의받은 워드마크, 사용권이 확인된 font·brush source만 사용하고 EXIF를 제거합니다.

### 6.2 표본 층

- 문자: Korean, Latin, mixed
- 도구: pen, marker, brush 또는 합성 stroke
- 배경: clean, 투명, 종이 촬영
- 구도: square, wide wordmark
- 변형: 획 굵기, 회전, crop, 명암, JPEG, 배경 여백

최소 목표는 30개 identity × 3개 variant = 90 query입니다. 여력이 있으면 60개
identity까지 확장하되 같은 identity family가 dev와 holdout에 동시에 들어가지 않게 합니다.

### 6.3 보고 지표

- family Recall@1/@5와 MRR
- target cosine과 nearest non-family margin
- 현재 상태 분류의 안정성
- 유형별 실패율과 `cannot_assess` 비율
- center-crop과 global-letterbox paired 차이
- clean artwork와 photo-like input의 성능 차이

fine-tuning은 사람 라벨 gate와 holdout 분리 조건이 충족된 뒤 shadow experiment로만
검토합니다. 성능 이득이 확인되기 전 운영 모델을 바꾸지 않습니다.

## 7. KIPRIS 월간 호출 계획

공식 무료 호출 한도는 계정 전체 상품 합산 월 1,000회이고, 프로젝트 내부 상한은
월 950회입니다. 최소 150회를 장애 확인·재시도·이름 확인 예비로 남겨 계획 호출은
최대 800회를 넘기지 않습니다.

| 월 | 우선 작업 | live 호출 계획 | 원칙 |
|---|---|---:|---|
| 8월 | 1,000건 기준선 보존 | 추가 호출 계획 없음 | 기록된 145회 이후 실험은 로컬 artifact 사용 |
| 9월 | API 계약·명칭 확인 시연 | 원칙적으로 0회, 승인된 smoke만 최대 20회 | BBQ fixture와 실제 live 증거를 구분하고 로컬 재현 우선 |
| 10월 | 수집 계보·1,000건 artifact 재검증 | 원칙적으로 0회, 장애 확인 예비 최대 50회 | 수집 호출을 반복하지 않고 기존 raw·staging·audit 증거 사용 |
| 11월 | SVG·손글씨 실험, 필요 시 누락 유사군 보강 | 실험은 0회, 보강 승인 시 최대 800회 | bibliography cohort를 별도 plan하고 150회 예비 유지 |
| 12월 | 잔여 보강·최종 확인 | `--plan` 결과에 따라 최대 300회 | 최종 artifact 동결 뒤 수집 금지 |

호출 횟수는 목표가 아니라 상한입니다. 실제 실행 전 counter, 남은 월 한도,
`search_hard_max`, retry 포함 최악 호출량을 기록하고 승인된 값보다 크면 실행하지 않습니다.

## 8. 작업량 제어

다른 프로젝트와 병행할 수 있도록 매주 핵심 산출물은 하나로 제한합니다.

1. 코드는 실험과 운영 경로를 feature flag로 분리합니다.
2. 보고서의 반복 수치는 증빙 매핑표 한 곳에서 관리합니다.
3. KIPRIS live 호출은 문서·local fixture·dry plan이 끝난 뒤에만 수행합니다.
4. 필수 경로와 stretch를 분리합니다.

| 구분 | 필수 | Stretch |
|---|---|---|
| 9월 | MVP·저장계층·KIPRIS·웹 대시보드 수행과 재검증 | 승인된 live name-check 추가 smoke |
| 10월 | 수집기·1,000건·scoring·artifact·보안 통합 분석 | 희소 류 시각화, visual family 탐색 UI |
| 11월 | canonical raster, SVG v1, vector·handwriting benchmark | PDF page-1 feasibility |
| 12월 | dev 160, holdout 40 단회 평가, 운영 검증, 최종 문서 | 대체 encoder shadow benchmark, X1·X4 설계안 |

## 9. 제출 문서와 증거

각 제출서는 다음 구조를 유지합니다.

1. 한 페이지 요약
2. 지난 제출 대비 변화
3. 주차별 수행·결과
4. 구현 산출물과 아키텍처
5. 정량 지표와 시각화
6. 문제와 설계 결정
7. 보안·호출 예산·권리 범위
8. 다음 4주 계획
9. 교수님께 확인받을 사항
10. Git·테스트·artifact 증빙

완료 주장은 반드시 [주장·증빙 매핑표](99_MarkLens_주장_증빙_매핑표.md)의 ID를 함께
가집니다.
