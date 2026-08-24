# MarkLens 모델·데이터 카드

버전: `visual-v2-uncalibrated`  
기준일: 2026-08-15

## 목적

MarkLens는 입력 표장과 **현재 로컬 비교 표본**에서 시각적으로 가까운 이미지를
검색하는 교육·연구용 시스템입니다. 결과는 후보 탐색을 돕기 위한 것이며 다음 용도로
사용하면 안 됩니다.

- 상표 등록 가능성, 침해 또는 법적 안전 판정
- 출처 혼동 확률이나 권리 부재 주장
- 변리사·변호사 또는 KIPRIS 공식 검색의 대체
- 자동 거절, 순위 결정 또는 권리 집행

## 모델

| 항목 | 값 |
|---|---|
| Encoder | OpenCLIP `ViT-B-32` |
| Pretrained | `laion2b_s34b_b79k` |
| Embedding | 512차원, float32, L2 정규화 |
| Search | FAISS `IndexFlatIP` |
| Device | CPU 기본 |
| 정식 전처리 | legacy OpenCLIP validation transform |
| 평가 후보 | `global-letterbox-dual-bg-v1` |

현재 인덱스와 query는 legacy 전처리를 사용합니다. OpenCLIP 기본 validation transform은
짧은 변 resize 뒤 중앙 crop을 수행하므로 긴 워드마크에 불리합니다. 새 global 후보는
letterbox와 투명 표장의 흰색·검은색 배경 view를 지원합니다. 확장 전 105장 내부 paired
비교는 전환 gate를 통과하지 못했고 원본이 모두 RGB라 dual-background도 검증되지
않았으므로 운영 인덱스에는 사용하지 않습니다.

입력 전처리는 EXIF 회전, 지원 형식 확인, 치수·픽셀 제한을 적용합니다. 빈 이미지,
빈 alpha, 낮은 대비처럼 판정할 정보가 부족한 입력은 검색 결과 대신 재업로드를
요청합니다. 사진과 화면 캡처는 사용자가 관심 표장을 직접 crop한 뒤 검색합니다.

## 상태 산출

정식 상태는 top-1 cosine similarity만 사용해 단조적으로 정합니다.

| top-1 | 상태 |
|---:|---|
| `>= 0.75` | `STRONG_MATCH` |
| `>= 0.55` | `POSSIBLE_MATCH` |
| `>= 0.45` | `WEAK_MATCH` |
| `< 0.45` | `NO_CLOSE_MATCH` |

이 임계값은 사람 라벨로 교정되지 않은 임시값입니다. 후보 간 gap이 0.04보다 작으면
`MULTIPLE_CLOSE_CANDIDATES` 불확실성을 추가하지만 상태를 낮추지 않습니다. NaN,
infinite, 범위 밖 유사도는 fail-closed로 거부합니다.

판정은 내부 고정 `scoring_k=20`을 사용합니다. 화면의 `top_k`를 1, 5 또는 20으로
바꿔도 같은 입력의 상태는 변하지 않습니다.

## 현재 데이터

감사 기준 artifact:

- generation `20260815T023540Z-0d79c662f4c8`, manifest `git.dirty=true`
- 서로 다른 출원번호, 이미지, index vector, metadata 각각 1,000개
- 파일·인덱스 누락, 고아 이미지, 중복 출원번호, 구조 차단 이슈 0건
- Nice 분류 45개 중 45개 포함, 출원일자 1962~2026년
- 출원인 문자열 203개, 최다 출원인 삼성카드 주식회사 22건(2.2%)
- 35류 185건(18.5%); 12개 류는 10건 미만이며 23류가 4건으로 가장 적음
- byte-identical 도안 123그룹, 총 330개 파일; 정규화 동일 명칭 141그룹
- 유사군 값 보유 100/1,000건(10.0%); 신규 895건은 이번 달 서지상세 보강을 하지 않음

같은 도안이 여러 류로 출원된 레코드는 별도 권리로 보존됩니다. 현재 UI는 이들을
시각 패밀리로 묶지 않으므로 유사 후보가 반복될 수 있습니다.

수집 표본은 등록 상태와 선택된 출원인 중심이며 대한민국의 전체 선행 권리,
진행 중 출원, 소멸·거절 이력 또는 실제 출원 전 조사 모집단을 대표하지 않습니다.

## 현재 v4 강건성 실측

현재 generation에서 25개 원본과 네 변형 100개, 총 125 query를 평가했으며 decode
실패는 0건입니다.

| 입력 | exact R@1 | exact R@5 | 상태 안정성 | 평균 target similarity |
|---|---:|---:|---:|---:|
| 원본 | 0.76 | 1.0 | 1.0 | 1.000000 |
| 90% center crop | 0.72 | 1.0 | 1.0 | 0.945949 |
| 회색 여백 20% | 0.76 | 1.0 | 1.0 | 0.909052 |
| JPEG 품질 60 | 0.76 | 1.0 | 1.0 | 0.982898 |
| 8도 회전 | 0.76 | 1.0 | 1.0 | 0.936337 |

원본 exact R@1 miss 6건은 모두 byte-identical 이미지 그룹에 속했고 정답 파일은
rank 2~3에 있었습니다. 확장으로 동일 이미지와 동률 기회가 늘어난 사실을 함께 봐야
하지만, v4는 family R@1을 측정하지 않았으므로 패밀리 단위 성능을 추정할 수 없습니다.
이 평가는 내부 표본의 변형 강건성이지 새로운 상표나 법적 위험의 일반화 정확도가 아닙니다.

## 확장 전 기준선 실측

기존 paired 보고서가 원본을 다시 임베딩해 만든 in-memory legacy gallery의 105장 전체
self-retrieval:

- exact Recall@1 `0.961905` (동일 파일 tie 영향)
- 동일 도안 family Recall@1 `1.000`
- exact/family Recall@5 `1.000`
- source vector 재생성 cosine 평균 약 `1.0`

이는 artifact 재현성 확인이지 일반화 정확도가 아닙니다.

감사 시 24장 종횡비 층화 perturbation 기준선:

| 변형 | family R@1 | family R@5 | 기존 상태 유지 |
|---|---:|---:|---:|
| 10도 회전 | 95.8% | 100% | 16/24 |
| 10% crop | 100% | 100% | 21/24 |
| 회색 여백 25% | 100% | 100% | 15/24 |
| JPEG 품질 60 | 100% | 100% | 24/24 |

이 측정은 순위가 살아남아도 과거 등급 규칙이 불안정했음을 보여 줍니다. 이후 점수
규칙을 top-1 단조 상태로 바꿨습니다.

확장 전 세대의 v3 opt-in 전체 run은 25장, 원본 25개와 네 변형 100개를 합한 125 query로
실행했습니다. 원본과 모든 변형의 exact Recall@1은 `0.96`, Recall@5는 `1.0`입니다.
R@1 한 건은 byte-identical 세 파일 family 내부의 rank-2 tie입니다. Target similarity
평균은 crop `0.956777`, 회색 여백 `0.919369`, JPEG 품질 60 `0.989764`, 8도 회전
`0.953514`였습니다. 상태는 crop/JPEG/회전에서 모두 유지됐고 회색 여백은
24/25(`0.96`)가 유지됐습니다. 나머지 한 건은 rank 1을 유지했지만 similarity가
`0.716410`으로 내려가 `STRONG_MATCH`에서 `POSSIBLE_MATCH`로 바뀌었습니다.

이 25장은 당시 105건 인덱스에서 뽑은 내부 강건성 표본입니다. 새로운 상표나 실제 촬영
환경에 대한 일반화 정확도 근거가 아니며, 임계값 교정 근거로도 사용하지 않습니다.

동일 105장에 대한 전처리 paired 비교는 모드별 525 query(원본 105, 변형 420)로
실행했습니다. Legacy와 global 후보의 exact/family Recall@1 차이는 0이었고, target
cosine 차이 `+0.003082`의 95% CI는 `[-0.001159, 0.007541]`, non-family margin 차이
`-0.003746`의 95% CI는 `[-0.014142, 0.006248]`이었습니다. Paired gate는
통과하지 못해 legacy 전처리를 유지합니다. 모든 원본이 RGB라 transparent-alpha
dual-background 분기는 평가되지 않았고, 현재 사람 라벨은 0/200이므로 fine-tuning도
금지됩니다.

## 라벨링과 교정

`ml/evaluation/labeling_pack_v2.json`은 200개 visual-only pair를 포함합니다.

현재 blank pack `vlp2_d32d53e3b6c101517517`은 generation
`20260815T023540Z-0d79c662f4c8`에서 생성됐으며 사람 라벨은 0/200입니다. 동일 bytes
또는 embedding similarity `>=0.995` 규칙으로 자동 그룹화한 visual family는 769개입니다.

- development 160쌍
- frozen holdout 40쌍
- 생성 라벨은 모두 `null`
- similarity 네 구간별 development 40쌍, holdout 10쌍
- 동일 bytes 또는 embedding similarity `>=0.995`인 family를 split 전에 결합
- image/family-disjoint split과 pair, image, index hash 고정

검수자는 상표명, 소유자, 류, 검색 점수와 법률 정보를 보지 않고 보이는 외관만
다음 중 하나로 표시합니다.

- `same_or_near_duplicate`
- `visually_similar`
- `visually_distinct`
- `cannot_assess`

따라서 같은 이미지나 near-duplicate family가 두 split에 동시에 나타나지 않습니다.
v1은 가까운 쌍에 편중되고 split 간 이미지가 겹친 역사 산출물이므로 검수·교정에
사용하지 않습니다.

160쌍으로 규칙과 임계값을 정한 뒤 40쌍 holdout을 한 번만 엽니다. 최소 보고 지표는
Recall@K, precision/recall, PR-AUC, Brier score, ECE, perturbation 안정성 및 문자체계,
종횡비, Nice 분류 slice입니다. 라벨이 돌아오기 전에는 임계값 재조정이나 교정 완료를
주장하지 않습니다.

## Artifact 계약

새 index generation은 다음을 manifest에 기록합니다.

- 모델, pretrained, 차원, embedding·preprocess version
- FAISS 구현, metric, L2 normalization, vector count
- authoritative source와 image/artifact SHA-256
- Git 상태와 핵심 패키지 버전

production 서버는 manifest, metadata, FAISS 파일의 generation과 SHA-256이 다르거나
현재 query model 계약과 다르면 기동하지 않습니다. DB image key와 index key가 다르거나
수집기의 index dirty marker가 남아 있어도 기동하지 않습니다. production에서 결과 이미지 공개를
활성화하면 metadata key·hash coverage, 안전한 상대 경로, 파일 존재, 각 이미지와 전체
image-set SHA-256까지 일치해야 기동합니다. 이미지가 비공개인 경로에서는 startup 파일
전체 읽기를 수행하지 않습니다.

현재 로컬 1,000-vector generation `20260815T023540Z-0d79c662f4c8`에는 manifest가
있지만 통합 작업 중 생성되어 `git.dirty=true`입니다. 이 세대는 실행·평가 증거로만
사용하고 배포할 수 없습니다.
통합 변경을 커밋한 뒤 clean tree에서 index와 모든 현재 평가 artifact를 다시 생성해야
production 승인 세대로 사용할 수 있습니다. 기존 v2 라벨링 팩은 모든 사람 라벨·메모가
빈 상태에서만 evaluation CLI의 명시적 `--replace-blank`으로 교체합니다.

## 알려진 한계와 다음 게이트

1. 200쌍 사람 검수와 40쌍 frozen holdout 평가
2. 최소 30개 동의받은 실제 사진·화면 캡처 crop 표본 평가
3. 실제 crop·투명 alpha 라벨 표본에서 legacy와 global 후보 재비교
4. visually identical filing family grouping
5. pending·active registration을 포함한 데이터 범위 설계
6. X1·X3·X4는 별도 검증 후에만 추가하며 결측을 0점으로 취급하지 않음

상세 실행 명령과 JSON Schema는 [ML evaluation README](../ml/evaluation/README.md)에
있습니다.
