# MarkLens 1차 진행보고서

대상 기간: 2026-08-31 ~ 2026-09-27, 1~4주차
제출 기준일: 2026-09-27
초안 작성일: 2026-08-15
현재 문서 상태: `기준선 확보 / 학기 검증 예정`

> 1학기 MVP 구현 이력: 2026-05-11 ~ 2026-06-10
> 작성 기준선 측정일: 2026-08-15
> 1~4주차 수행·검증 기간: 2026-08-31 ~ 2026-09-27

이 문서는 작성 시점의 API·UI·데이터·보안 구현 상태를 기준선으로 삼고, 1~4주차에
실제로 수행한 재현·분석·시연·문서화 결과를 기록하는 보고 템플릿입니다. 2026-08-15에
측정한 수치는 해당 날짜를 유지하고, 9월 수치는 같은 실행 경로를 다시 검증한 뒤
실제 실행일과 제출 commit을 함께 기록합니다.

## 1. 제출 정보

| 항목 | 내용 |
|---|---|
| 과목명 | 제출 전 입력 |
| 팀명·팀원 | 제출 전 입력 |
| 담당 범위 | 제출 전 입력 |
| 제출 commit | 제출 전 입력 |
| artifact generation | 제출 전 입력 |

## 2. 한 페이지 요약

### 작성 시점에 확보한 기준선

MarkLens는 2026-08-15 기준으로 다음 범위까지 로컬에서 구현·검증했습니다.

- OpenCLIP ViT-B/32 512차원 임베딩과 FAISS 검색
- 권리·이미지·벡터 각 1,000건, Nice 45/45류
- Next.js 업로드·crop·결과 대시보드와 FastAPI 검색
- 사용자 입력 상표명의 KIPRIS 완전일치 확인과 후보 상세
- API key·Turnstile·rate limit·request ID·해시 manifest
- Python 337 passed, 5 skipped, frontend 34/34, E2E 9/9의 2026-08-15 기준 기록

1~4주차에는 같은 실행 경로를 재현하고 구조·수치·한계를 교수 시연 자료로 정리합니다.
작성 기준선과 9월 실행 결과는 측정일·commit·artifact generation으로 구분합니다.
1,000건은 권리 수이며 독립 도안 수는 아닙니다. 자동 시각 그룹은 769개입니다.

### 1~4주차 목표

첫 4주는 현재 기준선을 다음 네 개 수행·검증 패키지로 나누어 진행합니다.

1. 1학기 MVP와 현재 통합 작업본의 Git·아키텍처 기준선
2. PostgreSQL 저장 계층, file/DB 경계와 재실행 환경
3. KIPRIS API·명칭 확인·후보 상세와 BBQ 시연
4. Next.js 검색·crop·근거 대시보드·모바일 E2E

### 제출 시 핵심 결과

| 결과 | 2026-08-15 작성 기준선 | 9월 학기 실행 결과 | 상태 |
|---|---:|---:|---|
| OpenCLIP 임베딩 | 512차원 L2 벡터 | 제출 전 실측 | 기준선 확보 |
| FAISS vector | 1,000 | 제출 전 실측 | 기준선 확보 |
| 권리·이미지·metadata | 각 1,000 | 제출 전 실측 | 기준선 확보 |
| Nice coverage | 45/45류 | 제출 전 실측 | 기준선 확보 |
| Python 검증 | 337 passed, 5 skipped | 제출 전 실측 | 기준선 확보 |
| Frontend 검증 | unit 34/34, E2E 9/9 | 제출 전 실측 | 기준선 확보 |
| KIPRIS live 명칭 확인 | 105건 세대에서 1회 정상 | 승인 후 실측 또는 미실행 | 부분실측 |

## 3. 주차별 수행·검증 계획

### 1주차, 08/31~09/06

핵심 질문: **1학기 MVP와 현재 통합 작업의 차이를 재현 가능한 기준선으로 설명할 수 있는가?**

| 구분 | 내용 |
|---|---|
| 작성 기준선 | `main` README 기록상 100건 OpenCLIP·FAISS·FastAPI MVP, 이후 API·UI·데이터·보안 확장 |
| 학기 실행 | Git 기준선·아키텍처·실행 경로를 다시 확인하고 1학기 대비표와 재현 체크리스트 작성 |
| 완료 기준 | `main@a4e3f11`, `develop@f95aaa1 + working tree`, 현재 generation을 한 표에 연결 |
| 증빙 ID | `PRE-ML-01`, `PRE-ML-03`, `R1-W01-A` |
| 9월 결과 | 제출 전 입력 |
| 상태 | 기준선 확보 / 학기 검증 예정 |

### 2주차, 09/07~09/13

핵심 질문: **파일과 PostgreSQL 저장 경로를 어디까지 구현했고 무엇이 아직 운영 검증 전인가?**

| 구분 | 내용 |
|---|---|
| 작성 기준선 | PostgreSQL schema·migration, 출원번호 정규화, JSON→DB, file/DB storage abstraction |
| 학기 실행 | migration·env·시작/종료 절차를 재현하고 현재 1,000건은 file mode임을 분리 설명 |
| 완료 기준 | 구현 경로·단위테스트·미검증 production backup/restore를 같은 표에 기록 |
| 증빙 ID | `PRE-DB-01`, `R1-W02-D` |
| 9월 결과 | 제출 전 입력 |
| 상태 | 기준선 확보 / 학기 검증 예정 |

### 3주차, 09/14~09/20

핵심 질문: **KIPRIS 명칭 중복 결과와 권리 후보를 사용자가 직접 확인할 수 있는가?**

| 구분 | 내용 |
|---|---|
| 작성 기준선 | HTTPS KIPRIS client, POST `/name-check`, complete/scanned counts, 후보 상세와 상태 분포 |
| 학기 실행 | 사용자 입력→KIPRIS→후보 목록→클릭 상세를 재현하고 BBQ fixture 시나리오 시연 |
| 사실 경계 | live 확인은 2026-08-14 `마크렌즈` 1회·105건 세대, BBQ 화면은 fixture/E2E |
| 증빙 ID | `PRE-KIP-01`, `PRE-KIP-02`, `PRE-UI-03`, `R1-W03-K`, `R1-W03-B` |
| 9월 결과 | 제출 전 입력 |
| 상태 | 기준선 확보 / 학기 검증 예정 |

### 4주차, 09/21~09/27

핵심 질문: **비개발자도 검색 근거와 이름 중복 후보를 모바일에서 확인할 수 있는가?**

| 구분 | 내용 |
|---|---|
| 작성 기준선 | Next.js upload·crop·loading·cancel·result/error, 점수 분포와 명칭 후보 클릭 상세 |
| 보안 경계 | same-origin BFF, Turnstile, server-only key, safe image proxy |
| 학기 실행 | 320x568·667x375·1280x800 흐름과 1,000건 검색을 재실행하고 화면 증거 생성 |
| 증빙 ID | `PRE-UI-01`, `PRE-UI-02`, `PRE-SEC-01`, `PRE-TEST-01`, `R1-W04-U`, `R1-W04-S`, `R1-W04-D` |
| 9월 결과 | 제출 전 입력 |
| 상태 | 기준선 확보 / 학기 검증 예정 |

## 4. 11월 신규 연구 후보: 입력 정규화 설계

다음 내용은 1차 보고 범위가 아니라 9주차 이후 신규 구현 후보입니다.

### 현재 경로

```text
KIPRIS image bytes -> {출원번호}.png 이름으로 저장 -> 인덱스 -> 확장자 기반 MIME
```

이 경로는 bytes가 JPEG여도 `.png`로 저장될 수 있습니다.

### 목표 경로

```text
remote/user bytes
  -> body size·Content-Type 1차 검사
  -> 안전 decode와 픽셀·치수 제한
  -> EXIF 보정·RGB/RGBA 정규화
  -> canonical PNG 또는 WebP 재인코딩
  -> decoded format·suffix·MIME 일치 검사
  -> source/canonical SHA와 변환 버전 기록
  -> staging audit
  -> index build·atomic publish
```

SVG는 XML을 기존 Pillow 경로에 바로 넣지 않습니다. 별도 격리 renderer에서 안전한
raster를 만든 뒤 위 canonical 경로의 decode 단계부터 합류시킵니다.

## 5. 11월 신규 연구 후보: SVG 위협 모델

| 위협 | 예시 | 방어 목표 | 제출 시 결과 |
|---|---|---|---|
| XML entity | DOCTYPE, XXE | parsing 전 차단 | 제출 전 실측 |
| active content | script, event handler | 허용 요소·속성 목록 밖 차단 | 제출 전 실측 |
| 외부 리소스 | HTTP image/font, file URI | network·filesystem 접근 0 | 제출 전 실측 |
| embedded payload | 과대 data URI | 전체·노드별 bytes 상한 | 제출 전 실측 |
| 복잡도 DoS | 깊은 group, 과다 path | DOM depth·element/path 상한 | 제출 전 실측 |
| raster 폭발 | 거대 viewBox·filter | 출력 픽셀·시간·메모리 상한 | 제출 전 실측 |
| 브라우저 노출 | raw SVG preview | 서버가 만든 safe raster만 preview | 제출 전 실측 |

## 6. 11월 신규 연구 후보: 손글씨 평가 설계

손글씨 연구는 OCR 정확도가 아니라 **동일 또는 가까운 외관 후보가 유지되는지**를
측정합니다. 이름은 사용자가 직접 입력하며 KIPRIS 명칭 확인 기능과 분리합니다.

| 축 | 구간 |
|---|---|
| 문자체계 | Korean, Latin, mixed |
| 도구 | pen, marker, brush, licensed synthetic font |
| 배경 | clean export, transparent, paper scan/photo |
| 종횡비 | square, medium wordmark, wide wordmark |
| 변형 | stroke width, rotation, crop, contrast, margin, JPEG |

표본별로 identity, family, source/license, capture type, script, aspect ratio, SHA-256을
기록합니다. 같은 identity family가 개발·평가 split을 넘지 않게 합니다.

## 7. 산출물 목록

| 산출물 | 목표 경로 또는 형태 | 상태 | 증빙 ID |
|---|---|---|---|
| ML·Git 기준선 비교 | 구현 이력과 현재 manifest | 기준선 확보 | `PRE-ML-01`, `PRE-ML-03` |
| PostgreSQL·file 경계 | schema·migration·storage code | 기준선 확보 | `PRE-DB-01` |
| KIPRIS 명칭 확인 | API 계약·후보 schema·fixture | 기준선 확보 | `PRE-KIP-01`, `PRE-KIP-02` |
| 검색·근거 대시보드 | frontend UI·unit·E2E | 기준선 확보 | `PRE-UI-01`~`PRE-UI-03` |
| 9월 수행·검증 보고 | 실행 명령·화면·수치 | 작성 예정 | `R1-W01-A`~`R1-W04-D` |
| canonical·SVG·손글씨 설계 | 9주차 이후 신규 연구 | 계획 | 후속 보고서 |

## 8. 정량 결과 표

첫 번째 수치 열은 2026-08-15 작성 기준선이고, 1차 보고 결과 열은 9월에 같은 경로를
다시 실행한 값입니다.

| 지표 | 기준선 | 1차 보고 결과 | 해석 |
|---|---:|---:|---|
| rights/images/vectors | 1,000/1,000/1,000 | 제출 전 실측 | generation·hash 포함 |
| Nice coverage | 45/45류 | 제출 전 실측 | 류별 편중과 별도 보고 |
| backend·ML Python | 337 passed, 5 skipped | 제출 전 실측 | skip 이유 포함 |
| frontend unit | 34/34 | 제출 전 실측 | dependency version 포함 |
| Chromium E2E | 9/9 | 제출 전 실측 | viewport와 mock/live 구분 |
| runtime search | index 1,000, top1 0.9999999404 표본 | 제출 전 실측 | name-check 호출 0임을 구분 |
| format/MIME mismatch | 900/1,000 | 11월 개선 예정 | 1차 보고에서는 발견·위험 분석 |

## 9. 문제와 결정 기록

| 결정 | 이유 | 대안 | 상태 |
|---|---|---|---|
| 1~4주를 수행·검증 패키지로 구성 | 구현 상태와 실행 근거를 주차별로 재현·분석 | 수치만 단순 나열 | 계획 |
| 1,000건은 권리 수로 보고 | 769 자동 family와 중복 권리를 분리 | 독립 도안 1,000개 주장 | 기준선 반영 |
| SVG는 11월 신규 연구 | 현재 사용자 업로드 미지원 | 9월 완료 주장 | 계획 |
| raw SVG browser preview 금지 | 외부 참조·canvas taint·비결정 렌더 위험 | client 직접 렌더 | 계획 |
| OCR을 주 경로로 사용하지 않음 | 현재 이름 기능·데이터·평가 계약과 맞지 않음 | 손글씨 OCR | 계획 |
| fine-tuning 보류 | 사람 라벨 0/200이며 holdout 미평가 | 즉시 재학습 | 계획 |

## 10. 다음 4주 계획

1. BBQ 5건 파일럿의 호출·격리·승격 계보 재현
2. 105→1,000건 확장의 월 한도·실패·복구 분석
3. OpenCLIP·FAISS·scoring·manifest·강건성 근거 시각화
4. 769 visual family와 동일 이미지·희소 류·유사군 누락 분석
5. BFF·Turnstile·rate limit·배포 경계와 통합 테스트 재실행

## 11. 교수님께 확인받을 사항

1. 1~4주차를 기능·저장소·외부 API·UI 검증 패키지로 나눈 보고 방식이 적절한지
2. 파일 모드와 구현된 PostgreSQL 경로를 어느 수준까지 시연할지
3. KIPRIS live 호출을 쿼터 보존 때문에 최소화해도 되는지
4. 1,000권리·769 자동 family를 함께 보고하는 방식이 적절한지
5. 11월 SVG·손글씨 연구와 사람 라벨 중 무엇을 우선할지

## 12. 제출 전 확인

- [ ] 모든 `제출 전 입력`과 `제출 전 실측`을 실제값으로 교체
- [ ] 2026-08-15 기준선과 9월 실행 결과의 commit·실측 날짜를 각각 기록
- [ ] 학기 중 재검증을 실제로 실행한 항목만 `검증완료`로 표시
- [ ] commit, test command, artifact hash를 증빙 매핑표에 기록
- [ ] 화면 캡처에서 key·절대경로·개인정보 제거
- [ ] 표본의 사용권과 EXIF 제거 여부 기록
- [ ] 법적 등록 가능성·침해·전체 정확도 표현 제거

## 13. 완료 확인 후 작성할 요약 문장 틀

아래 문장은 실제 수치와 증빙 ID를 채운 뒤에만 사용합니다.

> 1~4주차에는 MarkLens의 OpenCLIP·FAISS 검색 엔진, PostgreSQL·file 저장 경계,
> KIPRIS 명칭 확인과 Next.js 근거 대시보드를 순서대로 수행·검증했다. 자동검증
> `제출 전 실측`, 1,000건 검색과 BBQ 명칭 중복 fixture 시연 결과를 제출 증거로
> 정리했으며, 2026-08-15 작성 기준선과 9월 실행 결과의 날짜·commit·artifact를
> 구분해 기록했다.
