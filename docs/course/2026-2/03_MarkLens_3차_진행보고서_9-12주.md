# MarkLens 3차 진행보고서

대상 기간: 2026-10-26 ~ 2026-11-22, 9~12주차

제출 기준일: 2026-11-22

초안 작성일: 2026-08-15

현재 문서 상태: `계획 템플릿 · 신규 수행 예정`

> MarkLens의 핵심 기능과 1,000건 데이터는 2026-08-15 현재 기준선으로 확보돼 있다.
> 1~8주차에는 이 기준선을 9~10월 결과로 재현·분석·시연하고, 이 문서의
> 9~12주차에는 아직 구현·평가하지 않은
> 이미지 형식 정규화, SVG 질의, 벡터 등가성, 손글씨 강건성 연구를 신규 수행한다.
> 아래 계획 항목은 실제 수행 전까지 `완료`로 표시하지 않는다.

연계 문서:

- [16주 마스터 계획](./00_MarkLens_16주_마스터계획.md)
- [2차 중간보고서](./02_MarkLens_2차_중간보고서_5-8주.md)
- [주장·증빙 매핑표](./99_MarkLens_주장_증빙_매핑표.md)
- [데이터 확장 실행계획](../../MarkLens_데이터확장_실행계획_2026-08.md)

## 1. 제출 정보

| 항목 | 내용 |
|---|---|
| 과목명 | 제출 전 입력 |
| 팀명·팀원 | 제출 전 입력 |
| 담당 범위 | 제출 전 입력 |
| 제출 commit | 제출 전 입력 |
| 실험 환경 | 제출 전 입력 |
| 기준 artifact generation | 제출 전 입력 |
| 실험 manifest hash | 제출 전 입력 |

## 2. 이번 기간의 위치

### 2.1 9~10월 결과의 현재 기준선

다음 항목은 9~12주차에 처음 구현하는 내용이 아니다. 1·2차 보고 기간에 clean 재현,
결과 분석, 사용자 시연, 증빙 고정을 수행해 9~10월 결과로 제시하는 기준선이다.

| 기준선 | 현재 확인값 | 이 문서에서의 역할 |
|---|---:|---|
| 권리·이미지·벡터 | 각 1,000건 | 신규 질의 형식의 검색 대상 corpus |
| 임베딩 | OpenCLIP ViT-B-32, 512차원, 정규화 | 모델을 고정한 비교 기준 |
| 벡터 검색 | FAISS `IndexFlatIP` | 모든 신규 query의 동일 검색 경로 |
| Nice class | 45/45 | slice 분포 확인용 metadata |
| 자동 visual family | 769개 | 중복 누수 점검 단위 |
| byte-identical group | 123그룹, 330파일 | 중복으로 인한 순위 착시 분석 |
| similarity code | 100/1,000건 | 시각 실험과 분리해 관리하는 보조 정보 |
| 업로드 지원 | PNG·JPEG·WebP raster | 현재 제품 계약 |
| SVG·PDF·EPS 업로드 | 미지원 | 이번 연구의 출발점 |
| 손글씨 전용 평가 | 없음 | 12주차 신규 benchmark 대상 |

이 표는 계획서 작성일인 2026-08-15의 기준선이다. 3차 제출본에는 2차 보고서의
재현 결과와 artifact 식별자를 다시 연결한다.

### 2.2 이번 기간에 새로 답할 질문

1. 파일명 확장자와 실제 이미지 형식이 다른 현재 corpus를 검색 의미를 바꾸지 않고
   정규화할 수 있는가?
2. SVG를 기존 raster 업로드 계약과 섞지 않고 격리된 실험 경로에서 안전하게
   rasterize해 검색할 수 있는가?
3. 동일한 로고를 SVG와 PNG로 표현했을 때 현재 임베딩·검색 결과가 얼마나
   일관적인가?
4. 별도 학습 없이 손글씨·캘리그래피 변형에서 현재 visual baseline이 어느 정도
   유지되고, 어떤 오류 유형에서 무너지는가?

### 2.3 목표 산출물

- 실제 포맷을 검사한 canonical image manifest와 정규화 전후 대응표
- 원본·생성 파일을 분리하고 원자적으로 승격하는 정규화 generation
- 외부 참조·스크립트·과도한 자원을 차단한 격리 SVG query prototype
- SVG 원본 30개와 120개 이상 query로 구성한 vector equivalence pack
- 손글씨·캘리그래피 30 identity와 90개 이상 query benchmark
- 동일 모델·동일 index에서 비교한 rank·score·Top-K 일관성 표
- 실패 사례 gallery, slice 분석, 재현 명령, 환경·의존성·hash 기록
- 지원 범위와 한계를 사용자가 오해하지 않도록 정리한 기술 결정 기록

### 2.4 이번 기간의 비범위

- OpenCLIP 또는 다른 모델의 fine-tuning
- 손글씨 생성 모델이나 전용 OCR 모델 학습
- PDF는 필수 범위에서 제외하고 일정 여유가 있을 때만 page-1 feasibility를 `Stretch`로 검토
- EPS·AI·CDR 업로드 지원
- SVG를 1,000건 corpus 전체의 영구 원본 형식으로 마이그레이션
- 시각 점수를 법적 위험 확률이나 등록 가능성으로 해석
- 개발 중인 SVG 경로를 검증 없이 기본 업로드 API에 공개

데이터를 추가하거나 benchmark를 만드는 일은 모델을 다시 학습시키는 것과 다르다.
이번 기간에는 모델 파라미터를 고정하고 입력 형식과 표현 변형에 대한 강건성을
측정한다.

## 3. 제출 시 핵심 지표

| 지표 | 완료 기준 | 실제 결과 | 상태 |
|---|---:|---:|---|
| canonical manifest coverage | 1,000/1,000 | 제출 전 실측 | 신규 수행 예정 |
| 정규화 decode failure | 0건 | 제출 전 실측 | 신규 수행 예정 |
| source-to-canonical 매핑 누락 | 0건 | 제출 전 실측 | 신규 수행 예정 |
| SVG source | 30개 | 제출 전 실측 | 신규 수행 예정 |
| vector equivalence query | 120개 이상 | 제출 전 실측 | 신규 수행 예정 |
| SVG 차단 정책 test | 정의한 위협 case 100% | 제출 전 실측 | 신규 수행 예정 |
| handwriting identity | 30개 | 제출 전 실측 | 신규 수행 예정 |
| handwriting query | 90개 이상 | 제출 전 실측 | 신규 수행 예정 |
| benchmark query decode failure | 0건 | 제출 전 실측 | 신규 수행 예정 |
| 모델 fine-tuning | 0회 | 제출 전 확인 | 신규 수행 예정 |
| frozen holdout 열람 | 0쌍 | 제출 전 확인 | 신규 수행 예정 |

검색 품질 수치는 데이터 수만으로 목표치를 미리 정하지 않는다. 11·12주차에
identity 단위 ground truth를 고정한 뒤 Top-1, Top-5, MRR, score drift와 실패율을
함께 보고한다.

## 4. 지난 제출 대비 변화

| 항목 | 2차 보고 기준 | 3차 보고 목표 | 증빙 ID |
|---|---|---|---|
| corpus 이미지 | 파일명은 `.png`, 실제 형식은 JPEG 900·PNG 100 | 실제 형식 기반 canonical generation | `R3-W09-MANIFEST` |
| raster query | PNG·JPEG·WebP 지원 | 계약 유지, 회귀 0 확인 | `R3-W09-REGRESSION` |
| SVG query | 미지원 | 격리 prototype과 제한 명시 | `R3-W10-SVG` |
| PDF·EPS query | 미지원 | 미지원 유지 | `R3-W10-SCOPE` |
| vector equivalence | 전용 평가 없음 | 30 source·120+ query 평가 | `R3-W11-EVAL` |
| handwriting | raster 업로드만 가능 | 30 identity·90+ query 전용 평가 | `R3-W12-EVAL` |
| 모델 | 고정 baseline | 동일 모델·가중치 유지 | `R3-CONTROL-MODEL` |
| 사람 라벨·holdout | 미완료·잠금 | 13~15주차로 유지 | `R3-CONTROL-HOLDOUT` |

## 5. 주차별 수행 계획과 결과

### 9주차, 2026-10-26 ~ 2026-11-01

핵심 질문: **파일명과 실제 형식이 다른 1,000건 이미지를 손실 없이 정규화할 수 있는가?**

| 구분 | 내용 |
|---|---|
| 현재 문제 | 파일 경로 확장자는 모두 `.png`지만 실제 magic bytes는 JPEG 900건, PNG 100건 |
| 계획 | 전체 파일 탐지, 원본 hash 고정, 포맷별 decode, canonical 출력, 대응 manifest 생성 |
| 보존 원칙 | 원본은 읽기 전용으로 유지하고 신규 generation에만 정규화 결과 작성 |
| 비교 | 원본 decode 결과와 canonical decode 결과의 크기·색상 모드·embedding·검색 순위 |
| 회귀 확인 | 기존 PNG·JPEG·WebP 업로드와 1,000건 검색 경로 |
| 완료 기준 | 1,000건 매핑, decode failure 0, 누락 0, 원본 변경 0, rollback 확인 |
| 증빙 ID | `R3-W09-MANIFEST`, `R3-W09-NORMALIZE`, `R3-W09-REGRESSION` |
| 실제 결과 | 제출 전 실측 |
| 상태 | 신규 수행 예정 |

예정 산출물:

- `source_path`, 탐지 형식, 원본 SHA-256, canonical path, canonical SHA-256를 가진 manifest
- 형식별 수량과 예외 목록
- 정규화 전후 embedding cosine과 Top-K 변화 요약
- 생성 도중 중단한 뒤 이전 generation이 유지되는지 확인한 복구 기록
- 파일 확장자만 보고 decoder를 선택하지 않는 입력 계약

### 10주차, 2026-11-02 ~ 2026-11-08

핵심 질문: **SVG를 기존 업로드 경계에 바로 노출하지 않고 안전한 실험 query로 처리할 수 있는가?**

| 구분 | 내용 |
|---|---|
| 계획 | 별도 실험 명령 또는 내부 endpoint에서 SVG parse·검사·rasterize·embedding 수행 |
| 격리 | 운영 업로드 allowlist와 분리하고 기본 API의 지원 형식은 변경하지 않음 |
| 차단 | script, event handler, 외부 URL, 네트워크 fetch, 로컬 파일 참조, 과도한 data URI |
| 자원 제한 | 입력 byte, XML node, path/segment, 치수, viewBox, raster pixel, 처리시간 상한 |
| 출력 | 고정 배경·크기 정책의 PNG와 변환 metadata, 실패 reason code |
| 완료 기준 | 정상 fixture 통과, 악성·초과 fixture 차단, 네트워크 접근 0, 임시 파일 잔존 0 |
| 증빙 ID | `R3-W10-SVG`, `R3-W10-SEC`, `R3-W10-LIMIT`, `R3-W10-SCOPE` |
| 실제 결과 | 제출 전 실측 |
| 상태 | 신규 수행 예정 |

PDF와 EPS는 이 단계에서 제품 기능으로 지원하지 않는다. PDF page-1은 필수 과제가
완료된 경우에만 오프라인 feasibility `Stretch`로 검토하고, EPS는 제외한다. 두 형식은
parser·폰트·PostScript 실행 경계가 SVG와 달라 별도 위협 모델과 sandbox 설계 없이
같은 변환기로 묶지 않는다.

### 11주차, 2026-11-09 ~ 2026-11-15

핵심 질문: **같은 vector source에서 만든 SVG·PNG 변형의 검색 결과가 일관적인가?**

| 구분 | 내용 |
|---|---|
| 데이터 | 권리·출처를 기록할 수 있는 SVG source 30개 |
| query | source당 최소 4개, 총 120개 이상 |
| 변형 | SVG 직접 변환, 고해상도 PNG, 저해상도 PNG, 투명·흰 배경 조합 |
| 통제 | 동일 OpenCLIP 모델, 동일 전처리, 동일 1,000건 index, 동일 Top-K |
| 지표 | pair cosine, Top-1 일치, Top-5 overlap, MRR, rank delta, score drift |
| slice | 선형 로고, 채움 도형, wordmark, 세부 path가 많은 복합 로고 |
| 완료 기준 | 30 source·120+ query 완결, 누락 0, 실패 사례와 채택 판단 문서화 |
| 증빙 ID | `R3-W11-PACK`, `R3-W11-EVAL`, `R3-W11-SLICE`, `R3-W11-REPORT` |
| 실제 결과 | 제출 전 실측 |
| 상태 | 신규 수행 예정 |

평가에서는 동일 source에서 파생된 query를 하나의 identity로 묶는다. 같은 로고의
여러 변형이 서로 다른 split에 흩어져 성능이 부풀려지지 않도록 source 단위로
manifest와 집계를 고정한다. 원본이 corpus 안에 없는 경우에는 인위적인 Top-1 정답을
만들지 않고 SVG·PNG 쌍의 순위 일관성과 후보 overlap만 보고한다.

### 12주차, 2026-11-16 ~ 2026-11-22

핵심 질문: **fine-tuning 없이 현재 시각 검색이 손글씨·캘리그래피 변형을 얼마나 견디는가?**

| 구분 | 내용 |
|---|---|
| 데이터 | 사용 권한과 제작 provenance를 기록한 30 identity |
| query | identity당 최소 3개, 총 90개 이상 |
| 변형 | 원본, 굵기·기울기·획 연결 변화, 촬영·스캔 노이즈 중 사전 정의 조합 |
| 통제 | 모델·가중치·index 고정, benchmark 결과로 threshold를 즉시 변경하지 않음 |
| 지표 | Top-1, Top-5, MRR, identity별 rank, similarity 분포, query failure |
| slice | 한글, Latin, 혼합 표기와 단일어·다단어 구성 |
| 정성 분석 | 획 손실, 배경 간섭, 긴 wordmark, 해상도 저하, 유사 서체 오탐 |
| 완료 기준 | 30 identity·90+ query, provenance 누락 0, slice 표와 오류 gallery 완성 |
| 증빙 ID | `R3-W12-PACK`, `R3-W12-EVAL`, `R3-W12-GALLERY`, `R3-W12-REPORT` |
| 실제 결과 | 제출 전 실측 |
| 상태 | 신규 수행 예정 |

손글씨 입력도 현재 제품에서는 PNG·JPEG·WebP로 업로드할 수 있지만, 그것만으로
손글씨에 특화된 성능이 검증된 것은 아니다. 12주차 결과는 현 모델의 적용 범위를
측정하는 benchmark이며, 전용 모델을 학습했다는 주장으로 사용하지 않는다.

## 6. 9주차 상세 설계: 실제 형식 정규화

### 6.1 문제 정의

현재 1,000개 이미지 경로는 `.png` 확장자를 사용하지만 파일 내용을 검사하면 JPEG
900개와 PNG 100개로 나뉜다. 현재 decode failure는 0건이므로 이미지 자체가 깨졌다는
뜻은 아니다. 문제는 확장자와 내용이 불일치해 다음 작업자가 포맷을 잘못 추론하거나,
서버·브라우저·도구별 처리 차이가 생길 수 있다는 점이다.

### 6.2 정규화 파이프라인

```text
기존 generation 원본
  -> magic bytes와 decoder로 실제 형식 판별
  -> 원본 SHA-256·크기·색상 모드 기록
  -> EXIF orientation 반영과 RGB/RGBA 정책 적용
  -> canonical raster 생성
  -> 재decode·dimension·pixel budget 검증
  -> embedding과 Top-K 회귀 비교
  -> staging audit 통과
  -> 새 generation 원자적 승격
```

### 6.3 불변 조건

- 원본 파일을 덮어쓰거나 이름만 일괄 변경하지 않음
- 권리 ID와 이미지의 1:1 대응을 유지함
- alpha가 의미 있는 이미지의 투명도 정책을 manifest에 기록함
- EXIF·ICC·animation 등 제거되는 metadata를 명시함
- 실패 항목을 조용히 제외하지 않고 generation 승격을 중단함
- 이전 generation으로 되돌릴 수 있어야 함

### 6.4 제출 표

| 실제 형식 | 기준선 수 | 정규화 성공 | 실패 | canonical 형식 | 비고 |
|---|---:|---:|---:|---|---|
| JPEG | 900 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 | 확장자 불일치 대상 |
| PNG | 100 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 | alpha 별도 집계 |
| 기타 | 0 | 제출 전 실측 | 제출 전 실측 | 해당 없음 | 발견 시 즉시 기록 |
| 합계 | 1,000 | 제출 전 실측 | 제출 전 실측 | - | 누락 0 필요 |

## 7. 10주차 상세 설계: 격리 SVG query v1

### 7.1 제품 경계

SVG는 XML 기반 문서이므로 단순 이미지 파일과 같은 신뢰 경계로 처리할 수 없다.
v1은 다음 구조를 따른다.

```text
연구용 SVG fixture
  -> byte·구조·참조 검사
  -> 격리된 rasterizer
  -> pixel·시간·메모리 한도 검사
  -> 고정 크기 raster query
  -> 기존 embedding/search 함수
  -> 실험 결과 저장
```

기본 `/upload` 계약은 그대로 유지한다. 실험 endpoint를 만들더라도 개발 환경에서만
활성화하고, 인증·rate limit·timeout·egress deny 조건을 갖추기 전에는 외부에 공개하지
않는다.

### 7.2 위협·제한 검증표

| 범주 | fixture 예시 | 기대 동작 | 실제 결과 |
|---|---|---|---|
| script 실행 | `script`, event attribute | 거부 | 제출 전 실측 |
| 외부 참조 | remote image·font·stylesheet | 거부, 네트워크 0 | 제출 전 실측 |
| 로컬 파일 | `file:` 또는 경로 참조 | 거부 | 제출 전 실측 |
| 과도한 크기 | 거대 width·height·viewBox | 변환 전 거부 | 제출 전 실측 |
| 구조 폭발 | 과다 node·path·filter | 상한 초과 거부 | 제출 전 실측 |
| 처리 지연 | 복잡 filter·timeout fixture | 시간 제한 종료 | 제출 전 실측 |
| 정상 SVG | 단순 path·text outline | raster 변환 성공 | 제출 전 실측 |

지원 여부는 “파서가 열었다”가 아니라 위 표의 제한과 회귀 검증까지 통과했을 때만
판정한다.

## 8. 11주차 상세 설계: vector equivalence

### 8.1 데이터 구성

| Slice | Source 목표 | Query 최소 | 확인 목적 |
|---|---:|---:|---|
| 단순 선·기하 도형 | 8 | 32 | stroke와 작은 해상도 영향 |
| 채움·다색 도형 | 8 | 32 | alpha·배경·색상 영향 |
| wordmark | 7 | 28 | 긴 비율과 작은 글자 손실 |
| 복합 로고 | 7 | 28 | 세부 path와 rasterization 영향 |
| 합계 | 30 | 120 | 전체 일관성 |

source와 query는 라이선스·제작자·획득일·변환 옵션을 manifest에 남긴다. 상표권이
있는 실제 표장을 공개 보고서에 재배포할 수 없는 경우에는 썸네일 대신 비식별 ID와
수치만 제출하고, 원본 접근 경로는 비공개 증빙으로 분리한다.

### 8.2 지표 정의

| 지표 | 계산 단위 | 해석 |
|---|---|---|
| pair cosine | 같은 source의 SVG raster·PNG embedding | 표현 방식에 따른 벡터 변화 |
| Top-1 agreement | 같은 source의 query 쌍 | 첫 후보가 같은 비율 |
| Top-5 overlap | 같은 source의 query 쌍 | 상위 후보 집합 일관성 |
| rank delta | 기준 후보의 순위 차이 | 표현 변화에 따른 순위 이동 |
| score drift | 같은 후보에 대한 similarity 차이 | 점수 안정성 |
| MRR | identity 정답이 있는 subset | 정답 순위 품질 |

평균만 제시하지 않고 중앙값, 하위 분위수, 최악 사례를 함께 기록한다. byte-identical
후보가 많은 family는 일반 query와 분리해 tie가 지표를 왜곡하는지 확인한다.

### 8.3 채택 판단

- SVG 경로가 기존 PNG보다 항상 우수하다고 전제하지 않음
- 전체 평균과 slice 최저 성능을 함께 검토함
- 실패가 특정 rasterizer 옵션에 집중되면 옵션을 고정하고 version을 기록함
- 보안 제한을 완화해야만 성능이 나오는 기능은 제품 채택하지 않음
- 지표가 불안정하면 SVG는 연구 prototype 상태로 유지함

## 9. 12주차 상세 설계: 손글씨·캘리그래피 benchmark

### 9.1 데이터 계약

각 identity는 같은 표기 내용을 공유하는 원본과 변형 query의 묶음이다. 임의의 다른
단어를 같은 identity로 취급하지 않으며, 이미지 제작·수집 권한과 변환 이력을 남긴다.

| 필드 | 필수 여부 | 설명 |
|---|---|---|
| identity_id | 필수 | 개인 정보가 없는 내부 ID |
| script | 필수 | Korean, Latin, mixed |
| text_length_band | 필수 | 단일어·다단어 등 길이 구간 |
| source_provenance | 필수 | 직접 제작·허가·공개 라이선스 구분 |
| transformation | 필수 | 원본 또는 적용한 변형 |
| expected_relation | 필수 | 같은 identity 여부 |
| sha256 | 필수 | 파일 변경 검출 |
| notes | 선택 | 판독 불가·특수 획 등 |

### 9.2 변형 원칙

- 원본 의미를 바꾸는 글자 삭제·추가는 하지 않음
- 굵기·기울기·획 연결은 정해진 범위와 seed로 재현함
- 촬영·스캔 노이즈는 과도한 합성으로 benchmark를 왜곡하지 않음
- 배경 제거 전후를 같은 slice에 섞지 않고 별도 표시함
- 사람이 읽을 수 없는 이미지는 성능 실패와 데이터 품질 실패를 구분함

### 9.3 결과 표

| Slice | Identity | Query | Top-1 | Top-5 | MRR | 주요 오류 |
|---|---:|---:|---:|---:|---:|---|
| Korean | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| Latin | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| mixed | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |
| 전체 | 30 목표 | 90 이상 목표 | 제출 전 실측 | 제출 전 실측 | 제출 전 실측 | 제출 전 입력 |

### 9.4 결과 해석 경계

- 30 identity는 적용 가능성을 확인하는 소규모 benchmark이지 모집단 성능 보장이 아님
- corpus에 해당 identity 정답이 없는 query는 retrieval accuracy에서 제외하고 후보
  일관성 분석으로 분리함
- 결과가 낮아도 즉시 fine-tuning하지 않고 데이터·전처리·모델 한계를 구분함
- 결과가 높아도 “손글씨 상표를 정확히 판별한다”는 제품 주장으로 확대하지 않음
- 법률적 유사성, 등록 여부, 침해 판단과 시각 검색 지표를 동일시하지 않음

## 10. 공통 실험 통제와 재현성

### 10.1 고정 항목

| 항목 | 고정 내용 | 제출 증빙 |
|---|---|---|
| 모델 | OpenCLIP ViT-B-32 | model/config hash |
| embedding | 512차원, 정규화 | shape·norm 검증 로그 |
| index | FAISS `IndexFlatIP` | artifact generation·hash |
| corpus | 1,000건 기준선 | rights/images/vectors count |
| 검색 수 | 동일 Top-K | 실험 config |
| seed | 변형 생성별 명시 | manifest |
| code | 제출 commit 고정 | commit hash |
| 환경 | Python·library·OS·CPU/GPU | environment receipt |

모델·전처리·corpus를 동시에 바꾸지 않는다. 변경이 필요하면 하나의 실험 변수만
바꾸고 별도 run ID를 부여한다.

### 10.2 실행 단위

각 run은 최소한 다음 정보를 기록한다.

```text
run_id
created_at
git_commit
git_dirty
artifact_generation
model_id
preprocess_id
input_manifest_sha256
query_count
success_count
failure_count
metrics_path
error_report_path
```

`git_dirty=true`인 실행은 탐색용으로만 남기고 최종 제출 수치에는 사용하지 않는다.
최종 수치는 clean commit, 고정 manifest, 단일 generation으로 다시 실행한다.

### 10.3 누수 방지

- vector source와 그 파생 query는 identity 단위로 묶음
- handwriting identity도 동일한 단위로 묶음
- 13~15주차 사람 라벨·frozen holdout pair는 이번 benchmark에 사용하지 않음
- threshold나 상태 문구를 이번 소규모 benchmark에 맞춰 즉시 조정하지 않음
- 결과를 본 뒤 제외한 실패 case는 전체 지표에서도 삭제하지 않음

## 11. 보안·운영·비용 검토

| 위험 | 통제 | 확인 방법 | 상태 |
|---|---|---|---|
| SVG 외부 통신 | 모든 외부 reference 거부, egress 0 | 요청 감시·fixture test | 신규 수행 예정 |
| XML·path 자원 고갈 | byte·node·path·pixel·time 상한 | 경계값 test | 신규 수행 예정 |
| 파일 덮어쓰기 | staging generation과 atomic promotion | 중단·rollback test | 신규 수행 예정 |
| 임시 파일 노출 | run별 격리 경로, 종료 시 정리 | 잔존 파일 검사 | 신규 수행 예정 |
| 라이선스 위반 | source별 provenance와 공개 범위 기록 | manifest review | 신규 수행 예정 |
| 개인정보 포함 손글씨 | 이름·서명 수집 금지, 합성·허가 표장 사용 | 데이터 검수 | 신규 수행 예정 |
| API 월 한도 | 이번 benchmark는 로컬 artifact 사용 | KIPRIS call counter 0 확인 | 신규 수행 예정 |
| 과장된 제품 노출 | feature flag·연구용 표기 | UI/API route review | 신규 수행 예정 |

이번 9~12주차 실험은 기존 1,000건 artifact를 사용하므로 KIPRIS 실시간 호출을
필수로 하지 않는다. 데이터 누락을 보강할 필요가 생기면 별도 호출 예산을 산정하고
2차 보고서의 월 상한·예비량 규칙을 따른다.

## 12. 예상 위험과 의사결정 기준

| 위험 또는 관찰 | 대응 | 중단·축소 조건 |
|---|---|---|
| canonical 변환 뒤 rank가 크게 변함 | 색상·alpha·resize 변수를 분리 재실험 | 원인 미확인 시 승격 중단 |
| SVG rasterizer가 외부 참조를 허용함 | 설정 차단과 별도 격리 보강 | egress 1건이라도 발생하면 공개 금지 |
| 30개 SVG source 확보가 어려움 | 직접 제작·공개 라이선스 source로 범위 고정 | provenance 없는 자료 제외 |
| vector equivalence가 낮음 | 실패 slice와 raster 옵션 분석 | 지원을 제품 기능으로 승격하지 않음 |
| 손글씨 정답이 corpus에 없음 | identity retrieval과 후보 일관성 분리 | 정확도 분모를 임의 확장하지 않음 |
| 손글씨 slice가 불균형함 | 30 identity 내 층화 구성 | 특정 script 5개 미만이면 별도 결론 보류 |
| 일정 지연 | W10 보안 gate를 우선하고 UI polish 축소 | 보안 gate 미통과 시 SVG 연구 결과만 보고 |

## 13. 제출 증빙 구성

| 증빙 ID | 내용 | 예상 형식 | 제출 전 확인 |
|---|---|---|---|
| `R3-W09-MANIFEST` | 1,000건 원본·실제 형식·canonical 대응 | CSV/JSON + hash | [ ] |
| `R3-W09-NORMALIZE` | 정규화 실행 receipt와 수량 | JSON/로그 | [ ] |
| `R3-W09-REGRESSION` | 정규화 전후 검색 회귀 | Markdown/CSV | [ ] |
| `R3-W10-SVG` | SVG query v1 실행 결과 | JSON/스크린샷 | [ ] |
| `R3-W10-SEC` | 악성·외부 참조 차단 test | test log | [ ] |
| `R3-W10-LIMIT` | 크기·복잡도·시간 상한 test | test log | [ ] |
| `R3-W10-SCOPE` | SVG/PDF/EPS 지원 범위 결정 | decision record | [ ] |
| `R3-W11-PACK` | 30 source·120+ query manifest | CSV/JSON + hash | [ ] |
| `R3-W11-EVAL` | vector equivalence 전체 지표 | CSV/Markdown | [ ] |
| `R3-W11-SLICE` | 형태별 slice 분석 | 표·차트 | [ ] |
| `R3-W11-REPORT` | 실패 사례와 채택 판단 | Markdown | [ ] |
| `R3-W12-PACK` | 30 identity·90+ query manifest | CSV/JSON + hash | [ ] |
| `R3-W12-EVAL` | handwriting 전체·slice 지표 | CSV/Markdown | [ ] |
| `R3-W12-GALLERY` | 대표 성공·실패 사례 | 비식별 이미지/HTML | [ ] |
| `R3-W12-REPORT` | 한계와 후속 판단 | Markdown | [ ] |
| `R3-CONTROL-MODEL` | 모델·index·환경 고정 receipt | JSON | [ ] |
| `R3-CONTROL-HOLDOUT` | frozen holdout 미열람 확인 | hash/로그 | [ ] |

모든 증빙 ID는 제출 전에 [주장·증빙 매핑표](./99_MarkLens_주장_증빙_매핑표.md)에
실제 파일 경로, 생성 명령, 관찰일, commit, 상태와 함께 연결한다. 파일이 없거나
재현하지 못한 항목은 보고서에서도 `계획` 또는 `미검증`으로 남긴다.

## 14. 4주 운영표

| 주차 | 월~수 | 목~금 | 주말 gate |
|---|---|---|---|
| 9주차 | 포맷 탐지·manifest | canonical 생성·회귀 | 1,000건 누락 0 |
| 10주차 | SVG parser·격리 경계 | 정상·악성 fixture | egress 0, 한도 test 통과 |
| 11주차 | 30 source·120+ query 구성 | 전체·slice 평가 | vector 보고서 고정 |
| 12주차 | 30 identity·90+ query 구성 | 평가·gallery·문서 | 제출 evidence 연결 |

각 주차 gate를 통과하지 못하면 다음 단계의 수치를 완료로 보고하지 않는다. 특히
10주차 보안 gate 실패는 11주차 연구용 오프라인 변환만 허용하며 제품 endpoint
노출을 금지한다.

## 15. 다음 4주 계획, 13~16주차

1. 13주차에 development 사람 라벨 1차 80쌍을 검수한다.
2. 14주차에 나머지 80쌍과 저신뢰·평가불가 사례를 재검토한다.
3. dev-only 결과로 임계값·전처리 후보를 비교하고 결정·code hash를 동결한다.
4. 15주차에 frozen holdout 40쌍을 한 번만 열어 최종 평가한다.
5. PostgreSQL migration·backup·restore와 보안·부하 rehearsal을 수행한다.
6. 16주차에 모델·데이터 카드, 최종 보고서, 발표 자료, 데모를 고정한다.

## 16. 교수님께 확인받을 사항

1. vector equivalence를 30 source·120개 이상 query로 구성하는 규모가 학부 프로젝트의
   탐색 실험으로 충분한가?
2. 손글씨 benchmark를 30 identity·90개 이상 query로 제한하고 성능 보장이 아닌
   적용 가능성 분석으로 제출해도 되는가?
3. PDF page-1은 `Stretch`로만 두고 EPS·AI·CDR은 제외한 채 SVG만 격리 prototype으로 다루어도 되는가?
4. 모델 fine-tuning 없이 frozen baseline의 입력 강건성에 집중하는 연구 설계가
   적절한가?
5. 권리 문제로 실제 SVG 이미지를 공개 보고서에 싣기 어려운 경우 비식별 ID·수치와
   제한된 비공개 증빙으로 대체해도 되는가?
6. 13~15주차 사람 검수 전에 이번 형식·강건성 연구를 독립 benchmark로 수행하는
   순서가 타당한가?

## 17. 제출 전 확인

- [ ] 이 문서의 9~12주차가 신규 수행 기간임을 명시함
- [ ] 현재 기준선의 관찰일과 학기 중 수행 결과의 날짜를 섞지 않음
- [ ] 기준선 수치는 2차 보고 evidence와 같은 artifact인지 확인함
- [ ] JPEG 900·PNG 100을 재검사하고 실제값으로 갱신함
- [ ] 원본 1,000건을 변경하지 않았음을 hash로 확인함
- [ ] SVG 외부 참조·script·자원 제한 test를 실행함
- [ ] PDF·EPS 미지원 상태를 문서와 UI에 동일하게 표시함
- [ ] SVG 30 source·120+ query의 provenance와 hash를 기록함
- [ ] 손글씨 30 identity·90+ query의 provenance와 hash를 기록함
- [ ] 모델·가중치·index·Top-K와 전처리 version을 고정함
- [ ] fine-tuning 0회와 frozen holdout 미열람을 확인함
- [ ] 평균뿐 아니라 slice·하위 성능·실패 사례를 포함함
- [ ] 법적 위험 확률·등록 가능성으로 오해될 표현을 제거함
- [ ] 모든 완료 주장을 증빙 매핑표의 실제 artifact에 연결함

## 18. 완료 확인 후 작성할 요약 문장 틀

> 9~12주차에는 9~10월 결과 기준선을 바탕으로 입력 형식과
> 표현 변형에 대한 신규 연구를 수행했다. 먼저 파일명은 `.png`이나 실제 형식이
> JPEG 900건·PNG 100건이던 1,000건 corpus를 원본 보존 원칙 아래 canonical
> generation으로 정규화했고, `제출 전 실측`건을 누락 없이 검증했다. 이어 외부
> 참조와 자원 사용을 제한한 격리 SVG query v1을 구현·검증하고, SVG source 30개와
> 120개 이상 query에서 vector 표현 등가성을 측정했다. 마지막으로 별도 fine-tuning
> 없이 손글씨·캘리그래피 30 identity와 90개 이상 query를 평가해 `제출 전 실측`의
> 결과와 주요 실패 slice를 확인했다. PDF·EPS 정식 지원과 법적 판단 기능은 범위에서
> 제외했고 PDF page-1 feasibility는 `제출 전 입력`으로 판정했으며,
> 모든 결론은 고정 모델·artifact·manifest와 재현 가능한 증빙에 한정했다.
