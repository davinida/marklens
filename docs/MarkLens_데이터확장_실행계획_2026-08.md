# MarkLens 데이터 확장 실행 계획 (2026-08)

이 문서는 2026-08-14 BBQ 파일럿과 2026-08-15 1,000건 확장의 실행 기록이다.
105건 운영 표본에서 시작해 신규 895건을 격리 수집·감사한 뒤 운영 파일에 원자적으로
승격했다. 서지상세 보강은 월 호출 예산을 위해 실행하지 않았다.

## 1. 현재 상태

| 항목 | 확인값 |
|---|---:|
| 1,000건 확장 전 운영 메타 / 이미지 / FAISS 벡터 | 각 105건 |
| 현재 운영 메타 / 이미지 / FAISS 벡터 | 각 1,000건 |
| 서로 다른 출원번호 | 1,000건 |
| 신규 승격 레코드 | 895건 |
| Nice 분류 coverage | 45 / 45개 류 |
| 서로 다른 출원인 문자열 | 203개 |
| 최다 출원인 | 삼성카드 주식회사 22건(2.2%) |
| 최다 류 | 35류 185건(18.5%) |
| 이미지 누락 / 고아 이미지 / 중복 출원번호 | 0 / 0 / 0건 |
| 동일 이미지 해시 | 123그룹, 330파일 |
| 정규화 동일 명칭 | 141그룹 |
| 유사군 값 보유 | 100 / 1,000건(10.0%) |
| 출원일자 범위 | 1962 ~ 2026년 |
| KIPRIS 2026-08 로컬 카운터 | 145 / 950회 |
| 수집용 PostgreSQL | 미설정 (`DATABASE_URL` 없음) |
| 운영 generation | `20260815T023540Z-0d79c662f4c8` |
| 운영 manifest Git 상태 | `dirty=true` |

동일 이미지와 동일 명칭은 서로 다른 상품류 또는 별도 권리일 수 있다. 자동 삭제하지
않고, 출원번호·상품류·권리자를 함께 사람이 검토한다. 현재 구조 차단 이슈는 0건이다.

감사 재실행(네트워크 0회):

```powershell
ml\venv\Scripts\python.exe -m backend.scripts.audit_dataset `
  --output ml/data/staging/current_dataset_1000_audit.json
```

## 2. 수집기가 실제로 검색하는 범위

`getAdvancedSearch`에 현재 전달하는 검색 축은 다음과 같다.

- 출원인: `applicantName`
- 행정 상태 8종 중 등록만 활성화
- 표장 유형 9종 전체 활성화
- 표장 구성 13종 중 도형·도형복합 활성화
- 페이징: `pageNo`, 설정 가능한 `numOfRows`(현재 기본 100)

`classificationCode`는 응답에서 읽는다. `--nice-class 29 --nice-class 43`은 응답을
받은 **뒤에 적용하는 로컬 필터**이며 KIPRIS 검색 호출 수를 줄이지 않는다. 서버측
Nice 류 검색 파라미터는 현재 계약에서 검증하지 않았으므로 사용하지 않는다.

유사군은 `getAdvancedSearch` 응답에 없다. `--enrich-biblio`를 켜면 출원번호별
`getBibliographyDetailInfoSearch`를 1회씩 추가 호출한다. 초기 수집에서는 끄고,
다음 달 별도 보강하는 것이 월 예산을 예측하기 쉽다.

## 3. 안전장치

- `--plan`: API, DB, 파일 쓰기 모두 0회. 환경과 호출 상·하한만 출력한다.
- `--max-pages-per-source 1`: 한 실행에서 출원인별 검색을 최대 1회로 제한한다.
- `--file-staging`: DB가 없는 연구 환경을 위한 명시적 경로다.
- 파일 스테이징은 `ml/data/staging/` 아래 JSON만 허용한다.
- 실행 당시 운영 105건 메타는 재수집 방지용 읽기 전용 기준으로만 사용했다.
- 스테이징 메타는 신규 레코드만 담고 출원번호 기준으로 원자 병합한다.
- 이미지는 `ml/data/staging/<이름>_images/`에 저장해 운영 이미지와 격리한다.
- 같은 출원번호의 내용이 다르면 덮어쓰지 않고 실패한다. `--force`와 함께 쓸 수 없다.
- 메타, 이미지, SHA-256 manifest, checkpoint, dirty marker를 운영 파일과 분리한다.
- 파일 스테이징은 운영 메타와 운영 인덱스를 자동 변경하지 않는다.

## 4. BBQ 1차 파일럿(확장 전 기록)

후보 메타에서 확인한 `주식회사 제너시스비비큐`를 출원인으로 사용했고, 1페이지
파일럿에서 29·43류 등록 도형상표가 정상 수신되는 것을 확인했다.

사전 계획(네트워크 0회):

```powershell
ml\venv\Scripts\python.exe -m backend.scripts.collect_pipeline `
  --applicant "주식회사 제너시스비비큐" `
  --plan --limit 5 --max-pages-per-source 1 `
  --nice-class 29 --nice-class 43 `
  --file-staging ml/data/staging/bbq_29_43.json
```

2026-08-14 사전 계획 결과는 `ready_for_collection=true`, 사용 4회, 잔여 946회,
검색 최소·최대 모두 1회였다. 이 단계에서는 파일과 카운터가 바뀌지 않았다.

실행한 첫 실호출 명령:

```powershell
ml\venv\Scripts\python.exe -m backend.scripts.collect_pipeline `
  --applicant "주식회사 제너시스비비큐" `
  --limit 5 --max-pages-per-source 1 `
  --nice-class 29 --nice-class 43 `
  --file-staging ml/data/staging/bbq_29_43.json
```

### 파일럿 실측 결과

| 항목 | 결과 |
|---|---:|
| 로컬 카운터 | 4 → 5회 |
| 검색 호출 | 1회 |
| KIPRIS 검색 결과 | 284건 |
| 첫 9건 중 29·43류가 아닌 항목 | 4건 |
| 스테이징 신규 적재 | 5건 |
| 이미지 실패 / 레코드 실패 | 0 / 0건 |
| 43류 | 5건 |
| 29류 | 2건(43류와 복수 분류) |

서지상세는 호출하지 않았다. 메타 5건, 전용 이미지 5장, authoritative key 5개가
일치했고, 이 격리 검증이 끝난 뒤에만 운영 승격을 실행했다.

`--limit 5`가 page 1의 9번째 응답에서 충족되어 체크포인트는 `page 1, offset 9`다.
같은 명령을 다시 실행하면 page 1을 1회 재조회한 뒤 앞의 9건을 로컬에서 건너뛰고
이어서 처리한다. `--max-pages-per-source 1` 하드 캡은 재실행에도 유지된다.

## 5. 파일럿 검증 결과(확장 전 기록)

| 검증 | 결과 |
|---|---|
| 카운터 증가 | 1회, 통과 |
| 스테이징 메타 / 이미지 / key exact coverage | 5 / 5 / 5, 통과 |
| 스테이징 감사 차단 이슈 | 0건, 통과 |
| 누락 이미지 / 고아 이미지 | 0 / 0건 |
| 동일 이미지 해시 그룹 | 0건 |
| 정규화 동일 명칭 그룹 | 1건, 삭제하지 않고 권리 단위 검토 |
| 격리 FAISS 벡터 | 5개, 512차원 |
| 격리 인덱스 미등재 이미지 | 0건 |
| 승격 plan | 신규 5, 이미지 복사 5, 병합 후 105건 |

감사 산출물은 `ml/data/staging/bbq_29_43_audit.json`, 격리 인덱스 manifest는
`ml/data/staging/bbq_29_43_index/bbq_29_43_manifest.json`이다.

실행 완료한 격리 인덱스 빌드(네트워크 0회):

```powershell
ml\venv\Scripts\python.exe ml/scripts/build_index.py `
  --image-dir ml/data/staging/bbq_29_43_images `
  --output-dir ml/data/staging/bbq_29_43_index `
  --index-name bbq_29_43 `
  --authoritative-keys ml/data/staging/bbq_29_43.authoritative_keys.json
```

격리 인덱스는 5벡터로 정상 게시됐다. 이 단계에서는 운영 파일을 교체하지 않았고,
아래 승격 사전검증을 추가로 통과한 뒤에만 반영했다.

승격 계획(운영 변경 0회):

```powershell
ml\venv\Scripts\python.exe -m backend.scripts.promote_file_staging `
  --staging ml/data/staging/bbq_29_43.json --plan
```

승격 적용에 사용한 명령:

```powershell
ml\venv\Scripts\python.exe -m backend.scripts.promote_file_staging `
  --staging ml/data/staging/bbq_29_43.json --apply
```

승격은 성공했다. 운영 메타·이미지·벡터는 각각 105건이며 manifest의 미등재
이미지는 0건, 누락·고아 이미지는 0건, index dirty marker는 없다. 승격 도구는
다음 계약을 fail-closed로 강제한다.

1. 스테이징 메타, authoritative key, 전용 이미지가 정확히 일치해야 한다.
2. 메타와 모든 이미지의 SHA-256이 manifest와 같아야 한다.
3. 같은 출원번호의 운영·스테이징 메타가 다르면 중단한다.
4. 같은 이미지 키의 운영 파일 내용이 다르면 중단한다.
5. 적용 전 운영 메타 백업과 index dirty marker를 만든다.
6. 이미지를 검증 복사하고 운영 메타를 원자 병합한다.
7. authoritative key를 만든 뒤 `build_index.py`의 원자 publish를 실행한다.
8. 모든 단계가 성공해야 dirty marker를 제거한다. 실패하면 marker를 유지하고 재시작하지 않는다.

DB 모드에서는 이 승격 도구를 사용할 수 없다. PostgreSQL을 도입하면 스테이징을 검증한
뒤 별도 DB 마이그레이션 절차를 사용한다.

## 6. 확장 예산

| 실행 | 검색 호출 상한 | 서지상세 상한 | 로컬 카운터 합계 상한 |
|---|---:|---:|---:|
| BBQ 파일럿 1출원인, 1페이지, 보강 끔 | 1 | 0 | 1 |
| 5출원인, 각 1페이지, 보강 끔 | 5 | 0 | 5 |
| 5출원인, 각 50건, 보강 켬 | 5 | 250 | 255 |
| 1,000건 전체 서지상세 보강 | 검색 호출 + | 1,000 | 월 한도 초과 |
| 이번 105 → 1,000건 기본 수집 실측 | 140 | 0 | 카운터 `5 → 145` |

따라서 기본 수집과 유사군 보강을 같은 달에 끝내지 않았다.

1. 1차 목표 500건과 2차 목표 1,000건은 정확한 출원번호 합집합 기준으로 달성했다.
2. 단일 류 25% 중단선은 넘지 않았다. 가장 큰 35류는 18.5%다.
3. 45개 류 공백은 해소했지만 2·4·6·8·13·15·17·19·22·23·24·34류는 10건 미만이다.
4. 다음 월 이후 유사군이 빈 레코드만 별도 서지상세 호출로 보강한다.
5. 사람 라벨과 임계값 검증이 끝나기 전에는 모델 재학습을 시작하지 않는다.

## 7. 1,000건 확장 실행 결과

실행은 `--target-total`로 운영·스테이징 출원번호 합집합의 정확한 목표를 지정하고,
출원인별 한 페이지와 월간 로컬 카운터 상한을 유지했다. 수집 기본값은 한 페이지
100건, 요청 timeout 30초, source별 재시도 1회와 2초 backoff다.

```powershell
ml\venv\Scripts\python.exe -m backend.scripts.collect_pipeline `
  --applicants-file ml/data/staging/expansion_applicants_1000.txt `
  --limit 10 --target-total 1000 --max-pages-per-source 1 `
  --rows-per-page 100 --search-retries 1 `
  --retry-backoff-seconds 2 --search-timeout-seconds 30 `
  --file-staging ml/data/staging/expansion_1000.json
```

| 단계 | 시작 합집합 | 신규 적재 | 검색 호출 | 종료 합집합 |
|---|---:|---:|---:|---:|
| 500건 checkpoint | 105 | 395 | 58 | 500 |
| 1,000건 checkpoint | 500 | 500 | 80 | 1,000 |
| 격리 레코드 대체 | 999 | 1 | 1 | 1,000 |

확장 명령 전 구형 500행·15초 설정의 첫 요청이 timeout되어 1회를 소비했다. 이를 포함해
이번 확장은 140회, 8월 전체 로컬 카운터는 `145/950`이다. 정상 수집 중 이미지 다운로드
실패 1건은 스테이징하지 않았고 뒤의 정상 레코드가 목표를 채웠다. 레코드 변환 실패와
재시도 후 source 실패는 0건이었다.

격리 895건의 첫 인덱스 빌드에서 출원번호 `4020240121569`의 8001x8000 이미지가
64,000,000 pixel 안전 한도를 초과해 fail-closed됐다. 한도를 올리지 않고 전용 격리
도구로 메타·이미지·authoritative key에서 제외하고 원본과 감사 manifest를 보존한 뒤,
검색 1회로 정상 레코드를 대체했다. 최종 운영 감사 결과는 다음과 같다.

- 운영 metadata, 이미지, FAISS vector, 서로 다른 출원번호: 각각 1,000개
- 구조 차단 이슈, 누락 이미지, 고아 이미지, index 미등재 이미지: 0건
- Nice 45/45개 류, 출원인 203개, 35류 185건(18.5%), 최다 출원인 22건(2.2%)
- 동일 이미지 해시 123그룹·330파일, 정규화 동일 명칭 141그룹
- 유사군 100/1,000건(10.0%): 이번 달 서지상세 보강을 실행하지 않은 잔여 한계

동일 이미지나 명칭은 복수 류·복수 권리일 수 있어 자동 삭제하지 않았다. 이 수치는
권리 레코드 수이며 독립적인 시각 도안 수나 학습 샘플 다양성 수와 같지 않다.
현행 감사 산출물은 `ml/data/staging/current_dataset_1000_audit.json`, 최종 격리 감사는
`ml/data/staging/expansion_1000_audit_final.json`이다. 인덱스 세대와 SHA-256의 최종
기준은 매 빌드 때 갱신되는 `ml/data/index/kipris_manifest.json`이다.

### 확장 후 평가 artifact

최종 generation `20260815T023540Z-0d79c662f4c8`에서 라벨링 팩과 강건성 표본을 다시
생성했다. 라벨링 팩 `vlp2_d32d53e3b6c101517517`은 byte-identical 또는 embedding
similarity `>=0.995` 규칙으로 자동 그룹화한 769개 visual family를 기준으로 200쌍을
구성한다. development 160쌍, frozen holdout 40쌍이며 사람 라벨은 0/200이다.

v4 강건성 평가는 원본 25개와 변형 100개, 총 125 query이며 decode 실패는 0건이다.

| 입력 | exact R@1 | exact R@5 | 상태 안정성 | 평균 target similarity |
|---|---:|---:|---:|---:|
| 원본 | 0.76 | 1.0 | 1.0 | 1.000000 |
| 90% center crop | 0.72 | 1.0 | 1.0 | 0.945949 |
| 회색 여백 20% | 0.76 | 1.0 | 1.0 | 0.909052 |
| JPEG 품질 60 | 0.76 | 1.0 | 1.0 | 0.982898 |
| 8도 회전 | 0.76 | 1.0 | 1.0 | 0.936337 |

원본 exact R@1 miss 6건은 모두 byte-identical 그룹에 속했고 정답 파일은 rank 2~3에
있어 exact 파일 키 동률의 영향을 받았다. 이는 1,000건 확장 후 중복 파일이 늘어난 것과
함께 읽어야 한다. 다만 v4는 family R@1을 계산하지 않았으므로 family retrieval 성능이나
일반화 성능을 추정하지 않는다.

## 8. 다음 확장·보강 전 확인이 필요한 사항

- KIPRIS 이미지의 저장, 팀 내부 연구 이용, 외부 공개·재배포 범위 확인
- 다음 대량 보강부터 PostgreSQL을 사용할지, 검증된 스테이징을 파일 모드로 계속
  승격할지 결정
- 10건 미만인 12개 류의 추가 표본 목표와 출원인 cohort 검토
- 빈 유사군 900건의 서지상세 호출을 월별로 나눌지 결정

다음 승격도 자동 실행하지 않는다. 위 항목과 격리 인덱스 검증을 통과한 뒤 `--plan`
결과를 확인하고, 별도 승인 후 `--apply`를 수행한다.

## 9. 인덱싱 불가 이미지의 스테이징 격리

수집과 SHA-256 검증을 통과했더라도 디코더 안전 한도 또는 모델 전처리 한도를 넘는
이미지는 운영 승격 대상에서 제외해야 한다. 파일을 직접 삭제하면 체크포인트, 메타,
authoritative manifest가 서로 달라지고 다음 실행에서 재수집될 수 있으므로 아래 전용
도구만 사용한다. 이 명령은 KIPRIS를 호출하지 않으며 운영 메타·이미지·인덱스를 변경하지
않는다.

`4020240121569`의 8001x8000 이미지에 대한 읽기 전용 사전검증:

```powershell
ml\venv\Scripts\python.exe -m backend.scripts.quarantine_file_staging `
  --staging ml/data/staging/expansion_1000.json `
  --application-number 4020240121569 `
  --reason "8001x8000 이미지가 64M 픽셀 디코더 안전 한도를 초과" `
  --plan
```

계획의 출원번호, 이미지 SHA-256, 전후 건수와 격리 경로를 확인한 뒤에만 적용한다.

```powershell
ml\venv\Scripts\python.exe -m backend.scripts.quarantine_file_staging `
  --staging ml/data/staging/expansion_1000.json `
  --application-number 4020240121569 `
  --reason "8001x8000 이미지가 64M 픽셀 디코더 안전 한도를 초과" `
  --apply
```

적용 계약은 다음과 같다.

1. `ml/data/staging/` 아래 JSON만 허용하고 기존 스테이징의 메타·이미지·manifest
   SHA-256이 모두 일치해야 한다.
2. 출원번호를 명시해야 하며 해당 번호가 checkpoint `collected`에 없으면 재수집 방지를
   보장할 수 없으므로 중단한다. 격리 후에도 checkpoint 원본 바이트를 그대로 유지한다.
3. 변경 전에 sibling 디렉터리
   `expansion_1000_quarantine/<timestamp>_<출원번호>/before/`에 메타, manifest,
   checkpoint를 백업하고 각 SHA-256을 다시 확인한다.
4. 원본 이미지는 삭제하지 않고 같은 격리 작업의 `image/` 아래로 원자 이동한다.
   `quarantine.json`에 사유, UTC 시각, 출원번호, 원본 레코드와 이미지 SHA-256을 남긴다.
5. 스테이징 메타와 authoritative key/hash는 각각 임시 파일로 쓴 뒤 원자 교체한다.
   두 파일을 바꾸는 동안에는 staging dirty marker가 모든 재수집·승격을 차단한다.
6. 최종 무결성 검사를 통과해야 dirty marker를 제거한다. 중간 실패 시에는 marker와
   백업 및 이동된 이미지를 유지하며, 원인을 확인하기 전 수동으로 marker를 삭제하지 않는다.
