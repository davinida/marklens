
# MarkLens 2차 중간보고서

대상 기간: 2026-09-28 ~ 2026-10-25, 5~8주차
제출 기준일: 2026-10-25
초안 작성일: 2026-08-15
현재 문서 상태: `기준선 확보 / 학기 검증 예정`

> 이 보고서는 데이터 수집, 1,000건 확장, 검색 알고리즘, 보안 경계와 통합검증을
> 5~8주차 수행 단위로 나누어 기록한다. 2026-08-15 실측값은 `작성 기준선`, 10월에
> 같은 조건으로 다시 얻은 값은 `학기 실행 결과`로 구분하며 실행일·commit·artifact
> generation을 함께 남긴다.

## 1. 제출 정보

| 항목                | 내용                                                       |
| ------------------- | ---------------------------------------------------------- |
| 과목명              | 제출 전 입력                                               |
| 팀명·팀원          | 제출 전 입력                                               |
| 담당 범위           | 제출 전 입력                                               |
| 작성 기준선 측정일  | 2026-08-15                                                 |
| 수행·검증 기간     | 2026-09-28 ~ 2026-10-25                                    |
| 제출 commit         | 제출 전 입력                                               |
| artifact generation | 제출 전 입력                                               |
| 1차 보고 대비 범위  | 수집 안정화, 1,000건 확장, 검색 근거 분석, 보안·통합 시연 |

## 2. 한 페이지 요약

### 이번 기간의 핵심 질문

1. KIPRIS 월 호출 한도를 넘지 않으면서 연구 데이터를 105건에서 1,000건으로 늘릴 수 있는가?
2. 권리 레코드 수와 실제로 서로 다른 시각 도안 수를 구분해 데이터 규모를 설명할 수 있는가?
3. 표시 후보 수가 달라져도 검색 상태가 뒤집히지 않고, 모델·전처리·인덱스가 같은 세대임을 검증할 수 있는가?
4. 브라우저, Next.js BFF, FastAPI, KIPRIS와 로컬 인덱스 사이의 보안 경계를 설명하고 재현할 수 있는가?
5. 현재 결과를 법적 판단으로 과장하지 않고 데이터 편향과 미완성 축을 화면과 문서에 드러낼 수 있는가?

### 작성 시점에 확보한 기준선

- KIPRIS 원본 선저장, page checkpoint, 재시도·backoff, 기수집 skip과 호출 예산 제어
- BBQ 업종 파일럿 5건의 격리 수집·감사·승격으로 100건에서 105건 확장
- `staging -> audit -> quarantine -> atomic promotion` 절차로 신규 895건 보강
- 서로 다른 출원번호·메타데이터·이미지·FAISS vector 각 1,000건 정합
- OpenCLIP ViT-B/32의 512차원 정규화 임베딩과 FAISS `IndexFlatIP` 검색
- 표시용 `top_k`와 판정용 `scoring_k=20` 분리, NaN·범위 오류 fail-closed 처리
- model, preprocess, dimension, metric, generation과 SHA-256을 묶는 artifact manifest
- Next.js same-origin BFF, 서버 전용 API key, Turnstile, request ID와 rate-limit 경계
- 1,000건 runtime health, 검색, 결과 이미지 proxy와 로컬 검수 UI smoke

### 작성 기준선과 10월 제출 시 재확인할 값

| 지표                     | 2026-08-15 작성 기준선 |   10월 학기 실행 결과 | 해석                                    |
| ------------------------ | ---------------------: | --------------------: | --------------------------------------- |
| 권리·메타·이미지·벡터 |               각 1,000 |        제출 전 재실행 | 네 계수와 generation이 같아야 함        |
| 임베딩 차원              |                    512 | 제출 전 manifest 확인 | OpenCLIP image embedding 차원           |
| Nice 분류 포함           |                  45/45 |          제출 전 감사 | 포함 여부이며 분류별 균형을 뜻하지 않음 |
| 자동 시각 family         |                    769 |          제출 전 감사 | 사람 검수 전 자동 grouping 값           |
| 동일 byte 이미지         |       123그룹·330파일 |          제출 전 감사 | 여러 권리가 같은 도안을 공유할 수 있음  |
| 10건 미만 Nice류         |                   12개 |          제출 전 감사 | 희소 분류 보강 필요                     |
| 유사군 보유              |              100/1,000 |          제출 전 감사 | X4 상품 견련성 적용에는 부족            |
| 최대 출원인 문자열 비중  |         22/1,000, 2.2% |          제출 전 감사 | 동일 법인 정규화 전 문자열 기준         |
| 사람 라벨                |                  0/200 |          제출 전 확인 | 임계값 교정·fine-tuning 미수행         |
| Python 회귀검사          |  337 passed, 5 skipped |        제출 전 재실행 | 작성 기준선과 학기 결과를 분리          |
| frontend unit            |                  34/34 |        제출 전 재실행 | Vitest 기준                             |
| Chromium E2E             |                    9/9 |        제출 전 재실행 | 320x568, 667x375, desktop               |

## 3. 지난 제출 대비 변화

1차 보고서가 사용자 기능과 실행 경로를 검증했다면, 2차 보고서는 그 기능이 의존하는
데이터·알고리즘·보안 근거를 분석한다.

| 구분   | 1차 보고 초점                     | 2차 보고 초점                                 | 핵심 증빙                       |
| ------ | --------------------------------- | --------------------------------------------- | ------------------------------- |
| 데이터 | 현재 1,000건 기준선 확인          | 100→105→1,000 수집 계보와 편향 분석         | `PRE-DATA-01`~`04`          |
| 검색   | 이미지 검색 사용자 흐름           | 512차원 벡터, FAISS, scoring과 manifest       | `PRE-ML-01`~`03`            |
| 명칭   | 후보 클릭 상세와 BBQ fixture 시연 | KIPRIS 호출 계약·예산·live 증거 범위 구분   | `PRE-KIP-01`~`03`           |
| UI     | crop, 결과, 후보 상세             | 점수·격차·분포와 데이터 한계 해석           | `PRE-UI-01`~`03`            |
| 보안   | BFF 경로 확인                     | key·Turnstile·rate limit·egress·배포 경계 | `PRE-SEC-01`~`03`           |
| 검증   | 브라우저·API 기준선              | 전체 자동검사와 1,000건 runtime smoke         | `PRE-TEST-01`, `PRE-RUN-01` |

## 4. 주차별 수행 내용

### 5주차, 09/28~10/04: 수집 파이프라인 안정화와 BBQ 파일럿

핵심 질문: **외부 API가 중단되거나 같은 레코드가 다시 나타나도 기존 데이터를 손상시키지 않고 재개할 수 있는가?**

증빙 ID: `R2-W05-C`, `R2-W05-B` (작성 기준선 근거: `PRE-KIP-03`, `PRE-DATA-01`, `PRE-DATA-03`)

| 구분   | 2026-08-15 작성 기준선                               | 10월 학기 실행                                | 완료 기준                        |
| ------ | ---------------------------------------------------- | --------------------------------------------- | -------------------------------- |
| 검색   | KIPRIS Advanced Search 페이지 단위 수집              | 요청·페이지·결과 수를 실행 로그와 함께 재현 | plan과 실제 호출 수 일치         |
| 복구   | page·offset checkpoint, rows 계약, 실패 source 분리 | 중단·재개 시나리오를 fixture로 설명·재실행  | 누락·중복 적재 0                |
| 예산   | 월 counter, 내부 950 상한, 목표 총량 cap             | 최악 호출 수와 reserve를 표로 제출            | 목표 도달 뒤 추가 호출 0         |
| 격리   | 신규 메타와 이미지를 운영 경로 밖 staging에 저장     | staging hash와 authoritative key 감사         | 누락·고아·unsafe key 0         |
| 파일럿 | BBQ 관련 5건을 수집해 100→105 확장                  | 수집·감사·승격 단계를 교수 시연             | 운영 인덱스와 metadata 같은 세대 |
| 상태   | 기준선 확보                                          | 학기 검증 예정                                | `PRE-DATA-03`, 주차 실행 기록  |

#### 수집기가 보장해야 하는 순서

```text
KIPRIS search page
  -> raw response 보존
  -> parse와 등록 상태·분류 필터
  -> 이미지 다운로드·decode 검증
  -> 격리 staging 저장
  -> metadata·image hash·authoritative key 감사
  -> checkpoint 기록
  -> 다음 page 또는 source
```

페이지 전체를 먼저 가져온 뒤 이미지를 나중에 받는 방식은 일회성 이미지 경로 만료와
부분 실패 복구에 취약하다. 따라서 현재 수집기는 페이지 단위로 저장과 검증을 끝낸 뒤
다음 요청으로 진행한다. 재시도도 무한 반복하지 않고 각 호출이 월 예산을 소비한다는
전제에서 상한을 둔다.

### 6주차, 10/05~10/11: 월 한도 내 105→1,000건 확장

핵심 질문: **수량을 늘리면서도 메타·이미지·벡터의 정합성과 데이터 계보를 유지할 수 있는가?**

증빙 ID: `R2-W06-X`, `R2-W06-Q` (작성 기준선 근거: `PRE-DATA-01`, `PRE-DATA-02`, `PRE-DATA-03`, `PRE-DATA-04`, `B-010`)

| 항목                         | 2026-08-15 기준값 | 10월 학기 실행 항목                        |
| ---------------------------- | ----------------: | ------------------------------------------ |
| 시작 데이터                  |             105건 | 시작 generation과 hash 기록                |
| 신규 수집·승격              |             895건 | staging audit와 promotion 기록 재검토      |
| 확장 검색 호출               |             140회 | counter·실행 로그 대조                    |
| 2026-08-15 로컬 누적 counter |           145/950 | 작성 기준값으로만 인용                     |
| 격리한 비정상 이미지         |               1건 | 8001x8000, 64M pixel fail-closed 근거      |
| 최종 권리·이미지·벡터      |          각 1,000 | manifest와 runtime health 재확인           |
| 구조적 blocker               |                 0 | 중복 출원번호·누락·고아·unsafe key 감사 |

#### 원자 승격 계약

1. `--plan`에서 신규·동일·충돌 레코드와 최종 총량을 계산한다.
2. staging metadata, authoritative key와 실제 image hash의 exact coverage를 검사한다.
3. 충돌이나 누락이 있으면 운영 artifact를 건드리지 않고 중단한다.
4. 적용 시작 전에 backup과 dirty marker를 만든다.
5. 이미지를 검증 복사하고 metadata를 원자 교체한다.
6. 같은 입력으로 FAISS index와 manifest를 새 generation으로 생성한다.
7. index·metadata SHA와 vector count를 검증한 뒤에만 dirty marker를 지운다.

`1,000건`은 1,000개의 권리 레코드라는 뜻이다. 동일 이미지가 여러 상품류 또는 여러
출원번호에 걸쳐 등록될 수 있으므로 이를 1,000개의 독립 도안이나 1,000개의 학습표본으로
표현하지 않는다. 현재 자동 기준의 시각 family는 769개이며, 이 값도 사람 판정 전의
연구용 grouping이다.

### 7주차, 10/12~10/18: 벡터 검색·판정 규칙·artifact 정합성

핵심 질문: **검색 결과가 어떤 계산으로 만들어졌고, 같은 모델·전처리·데이터에서 나온 결과임을 증명할 수 있는가?**

증빙 ID: `R2-W07-S`, `R2-W07-A`, `R2-W07-R` (작성 기준선 근거: `PRE-ML-01`, `PRE-ML-02`, `PRE-ML-03`, `PRE-EVAL-02`, `PRE-EVAL-03`)

#### 검색 계산 흐름

```text
검증된 raster image
  -> OpenCLIP ViT-B/32 image encoder
  -> 512차원 float32 vector
  -> L2 normalization
  -> FAISS IndexFlatIP
  -> cosine-equivalent Top-K candidates
  -> 고정 scoring_k=20으로 참고 상태 산출
  -> 화면 top_k만 별도로 잘라 표시
```

| 주제      | 2026-08-15 기준값                                     | 과장하지 않는 해석                           |
| --------- | ----------------------------------------------------- | -------------------------------------------- |
| 임베딩    | 512차원 L2 정규화 vector                              | 모델을 새로 학습한 것이 아님                 |
| 검색      | FAISS inner product Top-K                             | 후보 검색이며 법적 동일성 판정이 아님        |
| 상태 규칙 | top-1 단조 임계값, gap은 불확실성에만 사용            | `visual-v2-uncalibrated`, 사람 교정 전     |
| 표시 후보 | UI top_k와 scoring_k=20 분리                          | 사용자가 표시 수를 바꿔 판정이 흔들리지 않음 |
| 오류      | NaN·무한대·범위 밖 점수 fail-closed                 | 잘못된 값이 낮은 위험으로 보이지 않게 함     |
| artifact  | model/preprocess/dimension/metric/SHA/generation 검증 | 세대가 다르면 startup 중단                   |

#### 1,000건 generation 내부 강건성 기준선

25개 원본과 crop, gray margin, JPEG, rotation 각 25개를 합쳐 125 query를 측정했다.

| 변형        | Exact R@1 | Exact R@5 | 상태 안정성 | 평균 target cosine |
| ----------- | --------: | --------: | ----------: | -----------------: |
| original    |      0.76 |      1.00 |        1.00 |           1.000000 |
| crop        |      0.72 |      1.00 |        1.00 |           0.945949 |
| gray margin |      0.76 |      1.00 |        1.00 |           0.909052 |
| JPEG        |      0.76 |      1.00 |        1.00 |           0.982898 |
| rotation    |      0.76 |      1.00 |        1.00 |           0.936337 |

원본 R@1 miss 6건은 동일 byte 이미지 family 내부의 rank 2~3 tie였다. 이 결과는
동일 소스의 변형에 대한 내부 재현성 근거이지, 새로운 상표에 대한 일반화 정확도나 법적
판단 정확도가 아니다. 이 평가에서는 family R@1을 별도로 측정하지 않았다는 한계도 함께
표시한다.

### 8주차, 10/19~10/25: 보안·운영 경계와 통합 시연

핵심 질문: **사용자 브라우저부터 외부 KIPRIS와 로컬 모델까지 각 신뢰 경계를 설명하고 실패 시 안전하게 중단할 수 있는가?**

증빙 ID: `R2-W08-S`, `R2-W08-D`, `R2-W08-T` (작성 기준선 근거: `PRE-SEC-01`, `PRE-SEC-02`, `PRE-SEC-03`, `PRE-DEP-01`, `PRE-TEST-01`, `PRE-RUN-01`)

| 경계            | 2026-08-15 작성 기준선                                   | 2차 제출 시 시연·확인                            |
| --------------- | -------------------------------------------------------- | ------------------------------------------------- |
| 브라우저→BFF   | same-origin route, Turnstile token, schema validation    | backend key가 브라우저 bundle·응답에 없는지 확인 |
| BFF→FastAPI    | 서버 전용 API key, request ID 전달                       | 잘못된 key 401, 설정 누락 fail-closed             |
| 업로드          | byte size, 실제 decode, dimension·pixel·aspect 검증    | 정상·blank·oversized fixture 결과               |
| FastAPI→KIPRIS | HTTPS official host allowlist, redirect 금지, safe error | URL·key·검색어가 로그에 노출되지 않는지 확인    |
| 결과 이미지     | 허용 key·hash·generation 검증 후 BFF proxy             | 누락·변조 시 비공개 또는 실패 처리               |
| gateway         | Nginx rate limit, JSON 429, request ID                   | 설정 정적검사와 운영 미검증 항목 분리             |
| 저장소          | 파일 모드 실측, PostgreSQL path·migration 구현          | 현재 1,000건이 file mode임을 명시                 |

#### 2026-08-15 작성 기준선

- Python: 337 passed, 5 skipped
- Ruff: 통과
- frontend Vitest: 34/34
- frontend lint, typecheck, production build: 통과
- Chromium E2E: 9/9
- npm audit known vulnerability: 0
- FastAPI와 BFF health: 1,000건·generation 일치
- 로컬 인덱스 검색: top-5 반환, 선택한 원본의 top-1 약 1.0
- 결과 이미지 BFF proxy: 200과 image content 확인
- 검수 UI: development 160개, labeled 0 상태 확인
- 최종 1,000건 smoke에서 KIPRIS `/name-check` 호출: 0회

10월에는 같은 검증을 제출 commit과 clean artifact 기준으로 다시 실행한다. 2026-08-15
기준값을 그대로 복사해 `10월 검증완료`라고 표시하지 않는다.

## 5. 데이터 품질 분석

### 규모와 대표성

| 항목               |         값 | 해석                                    |
| ------------------ | ---------: | --------------------------------------- |
| 권리 레코드        |      1,000 | 서로 다른 출원번호 기준                 |
| 자동 시각 family   |        769 | byte hash와 고유사도 기반 자동 grouping |
| 동일 byte 그룹     |        123 | 중복 삭제보다 권리 묶음으로 관리        |
| 동일 byte 파일     |        330 | 후보 순위 tie의 주요 원인               |
| Nice 분류          |      45/45 | 모든 류 포함                            |
| 35류               | 185, 18.5% | 가장 큰 류, 20% 미만                    |
| 10건 미만 류       |       12개 | 분류별 평가 전 추가 보강 필요           |
| 출원인 문자열      |        203 | 법인 표기 정규화 전 기준                |
| 최다 출원인 문자열 |   22, 2.2% | 단일 문자열 편중은 제한됨               |
| 유사군 보유        |   100, 10% | 상품 축 연구의 직접 사용은 보류         |

### 현재 발견한 형식 정합성 문제

이미지 파일명은 1,000개 모두 `.png`이지만 Pillow 전수 decode 기준 실제 payload는 JPEG
900개와 PNG 100개다. 검색 임베딩은 decode 기반이라 현재 동작하지만, 확장자 기반 image
response가 JPEG bytes를 `image/png`로 전달할 수 있다. 이 문제는 현재 미해결 항목으로
기록하고 11월 9주차 canonical image normalization에서 처리한다.

## 6. 명칭 확인 기능의 증거 범위

`/name-check`는 사용자가 직접 입력한 문자열을 KIPRIS 완전일치 검색에 보내고, 등록 중
정확일치 수, 상태별 수, 후보 상세와 검색 완전성을 반환한다. 후보 UI는 상표명, 상태,
출원·등록번호, 출원인·권리자, 상품류·유사군·비엔나 코드와 허용된 로컬 이미지를
클릭 상세로 보여 준다.

증거의 범위는 다음처럼 구분한다.

- 실제 KIPRIS HTTPS 호출: 2026-08-14, 105건 generation, `마크렌즈` 1회,
  `resultCode=00`, 완전일치 0건
- BBQ 후보 클릭 화면: mock/fixture 기반 browser E2E
- 최종 1,000건 runtime smoke: 쿼터 보존을 위해 `/name-check` 호출 0회

따라서 2차 발표에서 “1,000건 세대에서 BBQ live 조회 완료”라고 말하지 않는다. BBQ는
상세 UX 시나리오, `마크렌즈` 1회는 외부 API 연결 증거로 각각 설명한다.

## 7. 현재 배포 가능 범위

| 항목                       | 현재 상태                         | 2차 보고 판정                        |
| -------------------------- | --------------------------------- | ------------------------------------ |
| 로컬 연구 beta             | runtime smoke 완료                | 시연 가능                            |
| clean release artifact     | 현재 generation`git.dirty=true` | 재생성 전 배포 금지                  |
| PostgreSQL 코드·migration | 구현·자동검증                    | 실제 1,000건 migration 미검증        |
| Compose·Nginx topology    | 설정·문서 존재                   | Docker startup·`nginx -t` 미실측  |
| Turnstile                  | 코드·fixture·개발 경로 검증     | production site key·hostname 미검증 |
| TLS·도메인·firewall      | 가이드 존재                       | 실제 운영 미검증                     |
| KIPRIS 재배포 권리         | 확인 필요                         | 공개 이미지 기능 기본 비활성 유지    |

## 8. 교수 시연 구성

1. 데이터 감사 화면 또는 표에서 권리 1,000과 자동 family 769를 분리해 설명한다.
2. 동일 이미지가 여러 출원번호에 연결된 사례를 보여 주고 R@1 tie의 원인을 설명한다.
3. 이미지 한 장을 업로드·crop하고 Top-K 후보와 점수 분포·격차를 확인한다.
4. BBQ mock 명칭 결과에서 후보를 클릭해 상태·권리정보·분류 근거를 연다.
5. manifest의 generation, vector count와 hash 계약을 보여 준다.
6. oversized·blank 입력과 잘못된 API key가 fail-closed 되는 테스트를 시연한다.
7. 마지막 화면에서 현재 한계와 11월 신규 실험을 분리해 제시한다.

## 9. 문제와 해결

| 문제                                 | 원인                                          | 적용한 해결                                                | 남은 한계                                |
| ------------------------------------ | --------------------------------------------- | ---------------------------------------------------------- | ---------------------------------------- |
| 표시 top_k에 따라 상태가 바뀜        | 같은 후보 배열로 순위 표시와 판정을 함께 계산 | 내부 scoring_k=20 고정                                     | 사람 라벨 교정 전 임시 threshold         |
| 높은 동일 후보가 낮은 단계로 내려감  | 작은 gap을 위험 감소로 취급                   | top-1 단조 규칙, gap은 불확실성으로만 표시                 | 법적 위험 확률 아님                      |
| NaN이 안전하게 보일 수 있음          | 유한값 검증 없음                              | finite·range fail-closed                                  | 입력 품질 abstain 확장 필요              |
| 수집 실패 뒤 메타·이미지 불일치     | 순차 비원자 저장                              | staging, authoritative key, dirty marker, atomic promotion | 외부 API 자체 장애는 재시도 필요         |
| 64M pixel 이미지                     | 작은 전송 bytes 대비 과도한 decode 크기       | dimension·pixel 제한 후 격리·대체                        | 다운로드 stream size 상한 보강 필요      |
| 권리 수가 독립 도안 수로 오해됨      | 다류·중복 출원                               | visual family와 rights를 별도 집계                         | 자동 family의 사람 검수 필요             |
| DB가 실제 운영된 것처럼 보일 수 있음 | 코드 구현과 실행 경로 혼용                    | file mode 실측과 DB path 구현을 분리 표기                  | migration·backup/restore rehearsal 필요 |

## 10. 11월 신규 연구 계획

2차 제출 이후에는 현재 미지원인 입력 형식과 손글씨 강건성을 신규 연구로 다룬다.

1. 9주차: JPEG 900/PNG 100 payload를 실제 형식과 일치하는 canonical PNG/WebP로 정규화
2. 10주차: raw SVG를 브라우저에서 실행하지 않는 격리 SVG rasterization PoC
3. 11주차: 최소 30 SVG source, 120개 이상 query의 SVG↔PNG 벡터 동등성 평가
4. 12주차: 최소 30 identity, 90개 이상 query의 손글씨·캘리그래피 강건성 평가
5. SVG에는 XXE, script, 외부 URL·file, data URI, 과다 path·viewBox, timeout fixture를 적용
6. 손글씨는 실제 서명·실명 대신 허구 문자열 또는 동의받은 창작 워드마크만 사용
7. 성능 근거가 없으면 feature를 채택하지 않고 후속 연구로 보류

## 11. 교수님께 확인받을 사항

1. 권리 1,000건과 자동 시각 family 769개를 분리한 데이터 규모 설명이 적절한지
2. 동일 이미지 권리를 제거하지 않고 한 family 아래 권리 레코드로 유지하는 방식이 적절한지
3. 유사군 완성도 10%인 상태에서 상품 견련성 연구를 보류하는 판단이 적절한지
4. 임시 상태를 확률이나 법적 위험으로 표현하지 않는 현재 UI 범위를 유지할지
5. 11월 SVG·손글씨 실험에서 Recall@5, MRR, margin과 실패 taxonomy를 핵심 평가로 삼을지
6. 실제 공개배포보다 clean artifact와 PostgreSQL rehearsal을 학기 최종 범위로 우선할지

## 12. 제출 전 확인

- [ ] 2026-08-15 작성 기준선과 10월 학기 실행일을 각각 기재
- [ ] 제출 commit과 clean artifact generation 입력
- [ ] 권리·metadata·image·vector 1,000과 hash 일치 재확인
- [ ] 769 family, 123그룹·330파일, 희소 12류를 감사 산출물에서 재확인
- [ ] Python, frontend, E2E를 제출 commit에서 다시 실행
- [ ] BBQ fixture와 실제 KIPRIS 1회 증거를 구분
- [ ] file mode 실측과 PostgreSQL 구현 경로를 구분
- [ ] 2026-08-15 counter 기준값을 10월 호출량처럼 표현하지 않음
- [ ] `git.dirty=false` release artifact가 없으면 공개배포 완료로 표시하지 않음
- [ ] 법적 판단·모델 학습·OCR·SVG 지원 완료 표현 제거
- [ ] 실패 사례, 데이터 편향과 미검증 운영 경계를 발표에 포함

## 13. 완료 확인 후 사용할 요약 문장 틀

> 5~8주차에는 KIPRIS 수집·검색·보안 경계를 같은 계약으로 재현·분석하였다. 수집
> 파이프라인은 월 호출 예산 안에서 105건을 권리·이미지·512차원 벡터 각 1,000건으로
> 확장했으며, 10월 학기 실행 결과에서 `제출 전 입력` generation과 hash 일치를
> 확인했다. 1,000 권리는 자동 시각 family
> 769개로 구성되고 동일 byte 이미지 123그룹·330파일이 있어, 권리 수와 독립 도안 수를
> 구분해 보고했다. 또한 scoring, manifest, BFF와 입력·외부통신 경계를 재검증했으며,
> 사람 라벨 0/200, 유사군 10%, clean release·production 배포 미검증을 다음 단계의
> 제한으로 남겼다.

## 14. 근거 문서

- [16주 마스터 계획](00_MarkLens_16주_마스터계획.md)
- [주장·증빙 매핑표](99_MarkLens_주장_증빙_매핑표.md)
- [데이터 확장 실행계획](../../MarkLens_데이터확장_실행계획_2026-08.md)
- [모델·데이터 카드](../../MarkLens_모델카드_데이터카드.md)
- [기술 감사보고서](../../MarkLens_기술감사보고서_2026-08.md)
- [API 계약](../../MarkLens_API계약_v1.md)
- [공개배포·보안 가이드](../../MarkLens_공개배포_보안가이드.md)
- [ML 평가·라벨링 가이드](../../../ml/evaluation/README.md)
