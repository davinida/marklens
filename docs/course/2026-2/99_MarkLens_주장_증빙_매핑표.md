# MarkLens 주장·증빙 매핑표

작성 기준일: 2026-08-15
용도: 4·8·12·16주차 보고서의 완료 주장과 검증 근거 연결
상태: 현재 기준선 증빙 확정, 학기 중 수행·재현 증빙 슬롯 준비

## 1. 사용 규칙

1. 보고서의 완료 문장에는 이 문서의 주장 ID를 연결합니다.
2. `완료`에는 commit 또는 파일 산출물이 필요합니다.
3. `검증완료`에는 날짜·환경·명령·결과가 추가로 필요합니다.
4. 수치는 source artifact의 generation·SHA·표본 수를 함께 기록합니다.
5. 화면 캡처만으로 backend·ML 기능 완료를 주장하지 않습니다.
6. 테스트 통과만으로 live KIPRIS·production 배포를 확인했다고 쓰지 않습니다.
7. 미래 행은 증거가 생기기 전까지 `계획`으로 둡니다.
8. 작성 기준일에 확보된 기능은 `기준선 확보`로 기록하고 근거가 되는 실제 날짜를
   유지합니다.
9. 9~10월 보고서에는 각 주차의 **구현 정리·clean 재현·분석·시연·보고 활동**을
   기록합니다.
10. 학기 활동을 실제로 수행하기 전에는 `학기 수행·재현일`을 `예정`으로 두며,
    기존 기준선만으로 `검증완료`로 올리지 않습니다.

## 2. 상태와 최소 증거

| 상태 | 최소 증거 |
|---|---|
| 기준선 확보 | 구현을 확인할 수 있는 commit/file + artifact·실행 기록 + 미완료 경계 |
| 계획 | 목표와 완료 기준만 존재 |
| 진행 | 부분 commit 또는 중간 artifact와 남은 범위 |
| 완료 | commit/file + 변경 설명 |
| 검증완료 | 완료 증거 + 실행 날짜·환경·명령·결과 |
| 차단 | 반복 가능한 오류·외부 상태와 다음 확인 조건 |
| 보류 | 선택 사유와 재개 gate |

## 3. 증거 기록 형식

| 필드 | 작성 예 |
|---|---|
| 기준일 | `2026-10-11T18:30:00+09:00` |
| commit | short hash가 아닌 제출 branch의 full hash 권장 |
| 환경 | Windows 11, Python, Node, CPU/GPU, dependency lock hash |
| 명령 | 비밀값 없는 재현 명령 |
| 결과 | passed/failed/skipped, sample N, 주요 metric |
| artifact | generation ID, manifest/index/report SHA-256 |
| 화면 | viewport, route, mock/live 구분, 민감정보 제거 여부 |
| 한계 | 표본·환경·외부 API·법적 해석 한계 |

동일 기능에 날짜가 두 개 생길 수 있습니다. `기준 증거일`은 해당 기능과 실측값을
확인한 날짜이고, `학기 수행·재현일`은 수업 주차에 실행·분석·시연한 날짜입니다.
제출할 때는 두 날짜와 artifact generation을 각각 기록합니다.

## 4. 작성 기준선 주장

| ID | 주장 | 상태 | 기준일 | 근거 | 비고 |
|---|---|---|---:|---|---|
| `B-001` | 1학기 `main`은 OpenCLIP·FAISS·FastAPI MVP와 README 기록상 100건 기준선이다 | 기준선 확보 | 2026-06-10 | [개발 경과 회고](../../MarkLens_2개학기_개발경과_및_향후계획.md), `main@a4e3f11` | `ml/data`는 Git 제외라 main만으로 실데이터 재현 불가 |
| `B-002` | 현재 권리·이미지·벡터는 각각 1,000건이다 | 기준선 확보 | 2026-08-15 | [데이터 확장 실행계획](../../MarkLens_데이터확장_실행계획_2026-08.md), [모델·데이터 카드](../../MarkLens_모델카드_데이터카드.md) | 권리 수가 독립 도안 수는 아님 |
| `B-003` | Nice 45/45류, visual family 769개다 | 기준선 확보 | 2026-08-15 | [모델·데이터 카드](../../MarkLens_모델카드_데이터카드.md) | 12개 류는 10건 미만 |
| `B-004` | 작성 기준일의 사람 라벨은 0/200이다 | 기준선 확보 | 2026-08-15 | [ML 평가 가이드](../../../ml/evaluation/README.md) | fine-tuning 근거 없음 |
| `B-005` | Python 337 passed, 5 skipped 기록이 있다 | 기준선 확보 | 2026-08-15 | [기술 감사보고서](../../MarkLens_기술감사보고서_2026-08.md) | 학기 시작 뒤 재실행 필요 |
| `B-006` | frontend unit 34/34, E2E 9/9 기록이 있다 | 기준선 확보 | 2026-08-15 | [기술 감사보고서](../../MarkLens_기술감사보고서_2026-08.md) | 학기 시작 뒤 재실행 필요 |
| `B-007` | 사용자 업로드는 PNG·JPEG·WebP만 지원한다 | 기준선 확보 | 2026-08-15 | `frontend/components/SearchForm.tsx`, `backend/src/core/config.py` | SVG/PDF/EPS 미지원 |
| `B-008` | 손글씨 raster는 입력 가능하지만 전용 평가가 없다 | 기준선 확보 | 2026-08-15 | [모델·데이터 카드](../../MarkLens_모델카드_데이터카드.md), 현행 코드 | 정확도 주장 금지 |
| `B-009` | 이름 확인은 사용자 입력 문자열의 KIPRIS 조회다 | 기준선 확보 | 2026-08-15 | [API 계약](../../MarkLens_API계약_v1.md) | OCR·X1 알고리즘 구현 아님 |
| `B-010` | `.png` 1,000개 중 실제 decode는 JPEG 900, PNG 100이다 | 기준선 확보 | 2026-08-15 | 로컬 Pillow 전체 decode audit | canonicalization 전 format/MIME mismatch |

### B-010 재현 기록

확장자 계수:

```powershell
Get-ChildItem -File ml/data/images |
  Group-Object { $_.Extension.ToLowerInvariant() } |
  Select-Object Name, Count
```

2026-08-15 결과: `.png` 1,000개.

실제 디코드 형식 계수:

```powershell
@'
from pathlib import Path
from collections import Counter
from PIL import Image

counts = Counter()
for path in Path("ml/data/images").iterdir():
    if path.is_file():
        with Image.open(path) as image:
            counts[image.format] += 1
print(dict(sorted(counts.items())))
'@ | ml/venv/Scripts/python.exe -
```

2026-08-15 결과: `{'JPEG': 900, 'PNG': 100}`, decode failure 0. 이 검사는
이미지 의미나 검색 정확도를 측정하지 않고 실제 컨테이너 형식만 확인합니다.

## 5. 현재 기준선 구현 증빙

아래 항목은 작성 기준일에 코드·artifact·실행 기록으로 확인한 구현입니다. 해당 주차는
`학기 검증 예정`으로 두고, 실제 재현 뒤 날짜·환경·명령·결과를 주차별 `R*` 행에
추가합니다.

| ID | 기준선 구현 주장 | 상태 | 기준 증거일 | 학기 검증 예정 주차 | 근거 | 사실 경계 |
|---|---|---|---:|---:|---|---|
| `PRE-ML-01` | OpenCLIP ViT-B-32의 정규화된 512차원 벡터와 FAISS `IndexFlatIP` 기반 Top-K 검색을 구현했다 | 기준선 확보 | 2026-05-11~06-10 | 1주, 08/31~09/06 | `ml/src/embedding.py`, `ml/src/search.py`, `ml/scripts/build_index.py`, `ml/tests/` | 법적 유사성·등록 가능성 판정이 아님 |
| `PRE-ML-02` | 절대 유사도와 후보 격차를 결합한 참고용 scoring을 구현하고 역전 사례를 보완했다 | 기준선 확보 | 2026-05-11~07-11 | 7주, 10/12~10/18 | `ml/src/scoring.py`, `ml/tests/test_scoring.py`, [설계결정기록](../../MarkLens_설계결정기록.md) | 확률·법률 위험 점수가 아니며 사람 라벨 교정 전 |
| `PRE-ML-03` | 모델·전처리·데이터·index generation과 SHA를 연결하고 불일치 시 로딩을 중단하는 artifact 계약을 구현했다 | 기준선 확보 | 2026-08-14~08-15 | 7주, 10/12~10/18 | `ml/evaluation/artifacts.py`, `backend/src/core/engine.py`, `backend/tests/test_engine_manifest.py` | 현재 세대는 `git.dirty=true`라 release artifact가 아님 |
| `PRE-KIP-01` | HTTPS KIPRIS Plus client와 `POST /name-check` 완전일치 조회·후보 응답 경로를 구현했다 | 기준선 확보 | 2026-07-08~07-11 | 3주, 09/14~09/20 | `backend/src/core/kipris_client.py`, `backend/src/api/namecheck.py`, [API 계약](../../MarkLens_API계약_v1.md) | 사용자 입력 문자열 조회이며 OCR·호칭 유사 알고리즘이 아님 |
| `PRE-KIP-02` | 105건 세대에서 `마크렌즈`를 live API로 1회 조회해 `resultCode=00`, 완전일치 0건을 확인했다 | 기준선 확보 | 2026-08-14 | 3주, 09/14~09/20 | [KIPRIS API 신청 가이드](../../MarkLens_KIPRIS_API_신청가이드.md) | BBQ 후보 화면은 fixture/E2E이며 live BBQ 결과로 주장하지 않음 |
| `PRE-KIP-03` | 수집·명칭 확인의 월 호출 예산을 분리하고 cache·counter·950회 내부 상한·서지상세 opt-in 방어를 구현했다 | 기준선 확보 | 2026-07-08~08-15 | 5주, 09/28~10/04 | `backend/src/api/namecheck.py`, `backend/scripts/collect_pipeline.py`, [데이터 확장 실행계획](../../MarkLens_데이터확장_실행계획_2026-08.md) | 공급자 한도·권한·정책은 운영 전 다시 확인 필요 |
| `PRE-DATA-01` | BBQ 5건 파일럿 뒤 신규 895건을 추가해 권리·이미지·벡터를 105건에서 1,000건으로 확장했다 | 기준선 확보 | 2026-08-14~08-15 | 5~6주, 09/28~10/11 | [데이터 확장 실행계획](../../MarkLens_데이터확장_실행계획_2026-08.md) | 1,000은 권리 레코드 수이며 독립 도안 수가 아님 |
| `PRE-DATA-02` | 1,000건의 키 정합성·전체 decode·Nice 45/45류와 구조 차단 이슈 0건을 감사했다 | 기준선 확보 | 2026-08-15 | 6주, 10/05~10/11 | `backend/scripts/audit_dataset.py`, [기술 감사보고서](../../MarkLens_기술감사보고서_2026-08.md) | 품질·대표성·검색 정확도 검증과는 별개 |
| `PRE-DATA-03` | 원본 선저장·checkpoint·기수집 skip·격리·quarantine·원자 승격·dirty marker 복구 경로를 구현했다 | 기준선 확보 | 2026-07-08~08-15 | 5~6주, 09/28~10/11 | `backend/scripts/collect_pipeline.py`, `backend/scripts/promote_file_staging.py`, 관련 tests | 실제 장애 복구와 운영 backup/restore 훈련은 미완료 |
| `PRE-DATA-04` | 769개 자동 visual family, 동일 bytes 123그룹·330파일, 희소 Nice 12류, 유사군 100/1,000의 한계를 계수했다 | 기준선 확보 | 2026-08-15 | 6~7주, 10/05~10/18 | [모델·데이터 카드](../../MarkLens_모델카드_데이터카드.md), [데이터 확장 실행계획](../../MarkLens_데이터확장_실행계획_2026-08.md) | 자동 family는 사람 정답 라벨이 아니며 `.png` 1,000개 중 실제 JPEG 900개 |
| `PRE-UI-01` | PNG·JPEG·WebP 업로드, crop·취소·오류 상태와 반응형 검색 흐름을 구현했다 | 기준선 확보 | 2026-07-08~08-15 | 4주, 09/21~09/27 | `frontend/components/SearchForm.tsx`, `frontend/components/ImageCropDialog.tsx`, `frontend/e2e/marklens.spec.ts` | SVG·PDF·EPS 입력은 지원하지 않음 |
| `PRE-UI-02` | 점수 분포·후보 비교·근거·권리 상세를 보여 주는 결과 대시보드를 구현했다 | 기준선 확보 | 2026-08-14~08-15 | 4주, 09/21~09/27 | `frontend/components/ResultView.tsx`, `frontend/app/page.tsx`, frontend tests | 화면 설명은 모델 정확도 증거가 아님 |
| `PRE-UI-03` | 명칭 후보 목록·상태 분포와 클릭 상세 UI를 구현하고 BBQ fixture로 브라우저 흐름을 검증했다 | 기준선 확보 | 2026-08-14~08-15 | 3~4주, 09/14~09/27 | `frontend/components/NameCheckPanel.tsx`, `frontend/e2e/marklens.spec.ts` | BBQ 데이터는 mock/fixture이며 live KIPRIS 조회 증거가 아님 |
| `PRE-UI-04` | 현재 입력·평가 경계를 조사해 SVG·PDF·EPS vector graphic upload와 손글씨 전용 benchmark가 없음을 확인했다 | 기준선 확보 | 2026-08-15 | 9~12주, 10/26~11/22 | `frontend/components/SearchForm.tsx`, [모델·데이터 카드](../../MarkLens_모델카드_데이터카드.md) | raster 손글씨는 입력 가능하지만 별도 성능 주장은 불가 |
| `PRE-SEC-01` | 브라우저가 backend URL·key를 직접 받지 않는 Next.js same-origin BFF를 구현했다 | 기준선 확보 | 2026-07-08~08-15 | 4·8주, 09/21~10/25 | `frontend/app/api/`, `frontend/lib/server/backend.ts`, [공개배포·보안 가이드](../../MarkLens_공개배포_보안가이드.md) | 로컬 경계 검증이며 공개 배포 완료가 아님 |
| `PRE-SEC-02` | 업로드 검증, API key, rate limit, CORS, HTTPS 강제, request ID와 안전한 오류 매핑을 구현했다 | 기준선 확보 | 2026-07-08~08-15 | 8주, 10/19~10/25 | `backend/src/core/validation.py`, `auth.py`, `ratelimit.py`, `request_id.py`, `backend/tests/test_hardening.py` | 외부 침투시험·운영 TLS 검증은 미완료 |
| `PRE-SEC-03` | production 배포 전 gate와 잔여 위험을 문서화했다 | 기준선 확보 | 2026-08-15 | 8주, 10/19~10/25 | [공개배포·보안 가이드](../../MarkLens_공개배포_보안가이드.md), [기술 감사보고서](../../MarkLens_기술감사보고서_2026-08.md) | Turnstile production key·hostname, 실제 TLS·도메인·production DB는 미검증 |
| `PRE-EVAL-01` | 769 family 기반 200쌍 라벨 팩, 160 development·40 frozen holdout 분리와 검수 UI를 준비했다 | 기준선 확보 | 2026-08-15 | 13~15주, 11/23~12/13 | `ml/evaluation/labeling.py`, `ml/evaluation/review.py`, `ml/evaluation/review_ui/` | 사람 라벨은 0/200이고 holdout은 아직 평가하지 않음 |
| `PRE-EVAL-02` | 25개 원본과 100개 변형의 v4 내부 강건성 평가를 실행했다 | 기준선 확보 | 2026-08-15 | 7주, 10/12~10/18 | `ml/evaluation/robustness_model_full_v4.json`, [모델·데이터 카드](../../MarkLens_모델카드_데이터카드.md) | exact R@5 1.0은 내부 변형 복원 결과이며 전체 정확도가 아님 |
| `PRE-EVAL-03` | 현행 전처리와 대안 전처리의 비교 실행·보고 경로를 구현했다 | 기준선 확보 | 2026-08-15 | 7·9주, 10/12~11/01 | `ml/evaluation/preprocess_comparison.py`, `ml/evaluation/preprocess_comparison_full_v1.json`, 관련 tests | 운영 전처리는 아직 legacy이며 사람 라벨 교정·fine-tuning 없음 |
| `PRE-TEST-01` | Python 337 passed·5 skipped, frontend 34/34, E2E 9/9, lint·typecheck·build를 통과했다 | 기준선 확보 | 2026-08-15 | 1·8주, 08/31~10/25 | [기술 감사보고서](../../MarkLens_기술감사보고서_2026-08.md) | 학기 제출 시 같은 명령을 다시 실행해야 함 |
| `PRE-RUN-01` | 1,000건 FastAPI·BFF health, 검색, 결과 이미지와 검수 화면 runtime smoke를 통과했다 | 기준선 확보 | 2026-08-15 | 1·8주, 08/31~10/25 | [기술 감사보고서](../../MarkLens_기술감사보고서_2026-08.md) | 이 smoke의 KIPRIS `/name-check` 호출은 0회 |
| `PRE-DB-01` | PostgreSQL schema·migration·JSON 이관과 file/DB 저장 추상화를 구현했다 | 기준선 확보 | 2026-07-08~07-11 | 2주, 09/07~09/13 | `backend/migrations/001_init.sql`, `backend/scripts/migrate_json_to_db.py`, `backend/src/core/storage.py`, DB tests | 현재 1,000건 실행은 `DATABASE_URL` 없는 file mode이며 production backup/restore 미검증 |
| `PRE-DEP-01` | Dockerfile·nginx·Compose/CI 구조와 공개배포 보안 절차를 준비했다 | 기준선 확보 | 2026-07-08~08-15 | 8주, 10/19~10/25 | `deploy/`, `compose.production.yml`, `.github/workflows/`, [공개배포·보안 가이드](../../MarkLens_공개배포_보안가이드.md) | 실제 production 배포·공개 도메인 운영을 완료하지 않음 |

## 6. 1차 보고서 증빙, 1~4주

| ID | 목표 주장 | 요구 증거 | 상태 | 실제 근거·결과 |
|---|---|---|---|---|
| `R1-W01-A` | 1학기 MVP와 현재 통합본의 차이·구조·기능 경계를 수업 기준선으로 정리했다 | baseline commit, architecture note, PRE ID 연결 | 계획 | `PRE-ML-01`, `PRE-ML-02`; 학기 활동 후 날짜 입력 |
| `R1-W01-T` | 전체 자동 검증을 학기 환경에서 재통과했다 | 명령, 날짜, passed/skipped, dependency 환경 | 계획 | 8월 기준 `PRE-TEST-01`; 재실행 결과 별도 입력 |
| `R1-W01-S` | backend·BFF·검색·이미지 runtime smoke를 재현했다 | health/search/image response, generation, request ID | 계획 | 8월 기준 `PRE-RUN-01`; live name-check 여부 분리 |
| `R1-W02-D` | PostgreSQL과 file mode의 저장 계약·migration을 분석·재현했다 | migration/test 명령, row/hash 비교, 모드 설정 | 계획 | `PRE-DB-01`; 실제 1,000건은 file mode |
| `R1-W02-R` | 반복 실행 가능한 로컬 시작·종료와 설정 경계를 확인했다 | clean start/stop log, 환경변수 목록, secret 미노출 | 계획 | `PRE-DB-01`, `PRE-SEC-02`; 제출 전 재현 |
| `R1-W03-K` | KIPRIS 명칭 확인 흐름과 후보 응답 계약을 재현했다 | mock tests + 승인 시 live 결과, query·호출 수 | 계획 | `PRE-KIP-01`, `PRE-KIP-02` |
| `R1-W03-B` | BBQ 명칭 후보 클릭 시나리오를 시연했다 | fixture 선언, E2E trace, 화면 | 계획 | `PRE-UI-03`; live BBQ로 표기 금지 |
| `R1-W04-U` | 업로드·crop·결과 대시보드·후보 상세를 통합 시연했다 | desktop/mobile E2E, 화면, route | 계획 | `PRE-UI-01`, `PRE-UI-02`, `PRE-UI-03` |
| `R1-W04-S` | BFF에서 backend URL·key 비노출 경계를 재확인했다 | browser network trace, server env, regression | 계획 | `PRE-SEC-01` |
| `R1-W04-D` | 1차 보고서에 기준 증거일과 학기 실행일을 구분해 제출했다 | 제출 파일, PRE/R1 mapping, 발표일 | 계획 | 제출 전 입력 |

## 7. 2차 보고서 증빙, 5~8주

| ID | 목표 주장 | 요구 증거 | 상태 | 실제 근거·결과 |
|---|---|---|---|---|
| `R2-W05-C` | 수집기의 원본 선저장·checkpoint·retry·기수집 skip을 재현했다 | 제한 표본 dry-run, counter, checkpoint, recovery log | 계획 | `PRE-KIP-03`, `PRE-DATA-03` |
| `R2-W05-B` | BBQ 100→105 파일럿 계보와 fixture/live 경계를 설명했다 | 호출·격리·승격 기록, 화면 출처 표기 | 계획 | `PRE-DATA-01`, `PRE-KIP-02`, `PRE-UI-03` |
| `R2-W06-X` | 105→1,000 격리 수집·감사·원자 승격 과정을 분석·재현했다 | generation, audit JSON, 호출 counter, promotion plan | 계획 | `PRE-DATA-01`, `PRE-DATA-02`, `PRE-DATA-03` |
| `R2-W06-Q` | 1,000건의 권리·family·분류·유사군·format 한계를 함께 보고했다 | count table, source artifact hash, decode report | 계획 | `PRE-DATA-04`, `B-010` |
| `R2-W07-S` | scoring 역전 보완과 512D·FAISS 검색 계약을 분석했다 | unit tests, score examples, algorithm note | 계획 | `PRE-ML-01`, `PRE-ML-02` |
| `R2-W07-A` | artifact generation·SHA 불일치 차단을 재현했다 | valid/mismatch fixtures, loader result | 계획 | `PRE-ML-03` |
| `R2-W07-R` | 25+100 내부 강건성과 전처리 비교 결과를 한계와 함께 재생성했다 | source JSON, hashes, command, paired report | 계획 | `PRE-EVAL-02`, `PRE-EVAL-03` |
| `R2-W08-S` | BFF·입력·egress·rate·request-ID 보안 경계를 통합 재검증했다 | security tests, browser trace, config audit | 계획 | `PRE-SEC-01`, `PRE-SEC-02` |
| `R2-W08-D` | production 미검증 항목과 배포 gate를 판정했다 | deployment checklist, TLS/DB/Turnstile 상태 | 계획 | `PRE-SEC-03`, `PRE-DEP-01`; 미운영을 완료로 표기 금지 |
| `R2-W08-T` | 1,000건 통합 회귀·runtime smoke를 재통과하고 2차 보고서를 제출했다 | suite 결과, runtime response, 제출 파일 | 계획 | 8월 기준 `PRE-TEST-01`, `PRE-RUN-01`; 제출 전 재실행 |

## 8. 3차 보고서 증빙, 9~12주

| ID | 목표 주장 | 요구 증거 | 상태 | 실제 근거·결과 |
|---|---|---|---|---|
| `R3-W09-C` | 실제 컨테이너와 확장자·MIME가 일치하는 canonical image contract를 고정했다 | ADR, version, source/output provenance schema | 계획 | `B-010`을 입력으로 신규 수행 |
| `R3-W09-A` | 1,000개를 canonical format으로 재생성·감사했다 | decode report, source/output hash, failure·mismatch count | 계획 | 제출 전 입력 |
| `R3-W09-T` | 정상·손상·고용량 이미지 회귀를 추가했다 | fixture, resource limit, test result | 계획 | 제출 전 입력 |
| `R3-W10-P` | 격리 SVG rasterizer v1이 유효 입력을 결정적으로 처리했다 | code, renderer/version, deterministic output | 계획 | `PRE-UI-04`에서 미지원 확인 후 신규 수행 |
| `R3-W10-S` | 악성 SVG의 네트워크·파일 접근·외부 참조를 차단했다 | threat fixtures, sandbox log, timeout result | 계획 | 제출 전 입력 |
| `R3-W10-E` | 기존 raster 입력과 SVG query E2E를 함께 검증했다 | API contract, desktop/mobile E2E | 계획 | 제출 전 입력 |
| `R3-W11-V` | 30개 이상 SVG source로 120개 이상 vector query cohort를 평가했다 | source/license/family/hash manifest, deterministic report | 계획 | 제출 전 입력 |
| `R3-W11-P` | rasterization p50/p95·memory와 원본 대비 검색 지표를 측정했다 | benchmark environment, raw result, paired metrics | 계획 | 제출 전 입력 |
| `R3-W11-D` | vector 기능의 채택·보류 gate를 판정했다 | threshold, decision record, failure examples | 계획 | 제출 전 입력 |
| `R3-W12-H` | 30개 identity로 90개 이상 handwriting query를 평가했다 | consent/license, family split, hashes, slice report | 계획 | `PRE-UI-04`에서 전용 평가 부재 확인 후 신규 수행 |
| `R3-W12-S` | 필기 도구·배경·기울기 slice별 실패를 분석했다 | Recall/MRR/margin table, error examples | 계획 | 전체 손글씨 정확도로 일반화 금지 |
| `R3-W12-D` | vector·handwriting 결과와 개인정보·EXIF 원칙을 3차 보고서로 제출했다 | 제출 파일, evidence, 채택·보류 결정 | 계획 | 실제 서명·실명 필기 제외 |

### 3차 보고서 세부 실행 ID

아래 ID는 위의 주차별 목표 주장을 실제 파일 단위로 나눈 증빙 슬롯이다. 상위 주장과
세부 ID를 함께 기록해 보고서 본문과 이 표를 일대일로 찾을 수 있게 한다.

| 세부 ID | 연결 상위 주장 | 제출할 증거 | 상태 |
|---|---|---|---|
| `R3-W09-MANIFEST` | `R3-W09-C`, `R3-W09-A` | source·actual format·canonical key·SHA manifest | 계획 |
| `R3-W09-NORMALIZE` | `R3-W09-A` | 정규화 실행 receipt와 성공·격리 수량 | 계획 |
| `R3-W09-REGRESSION` | `R3-W09-T` | 정규화 전후 검색·이미지 응답 회귀 결과 | 계획 |
| `R3-W10-SVG` | `R3-W10-P` | renderer/version과 정상 SVG 실행 결과 | 계획 |
| `R3-W10-SEC` | `R3-W10-S` | XXE·script·외부 참조·file 접근 차단 로그 | 계획 |
| `R3-W10-LIMIT` | `R3-W10-S` | bytes·DOM·path·pixel·timeout 상한 결과 | 계획 |
| `R3-W10-SCOPE` | `R3-W10-E` | SVG 채택 범위와 PDF·EPS 제외 결정 | 계획 |
| `R3-W11-PACK` | `R3-W11-V` | 30 source·120+ query provenance·family·hash manifest | 계획 |
| `R3-W11-EVAL` | `R3-W11-P` | vector equivalence 전체 paired metric | 계획 |
| `R3-W11-SLICE` | `R3-W11-P` | 배경·해상도·wide slice별 metric | 계획 |
| `R3-W11-REPORT` | `R3-W11-D` | 실패 사례와 채택·보류 decision record | 계획 |
| `R3-W12-PACK` | `R3-W12-H` | 30 identity·90+ query 동의·license·hash manifest | 계획 |
| `R3-W12-EVAL` | `R3-W12-S` | handwriting 전체·slice metric | 계획 |
| `R3-W12-GALLERY` | `R3-W12-S` | 공개 가능한 비식별 성공·실패 사례 | 계획 |
| `R3-W12-REPORT` | `R3-W12-D` | 개인정보·한계·후속 판단 보고서 | 계획 |
| `R3-CONTROL-MODEL` | `R3-W11-P`, `R3-W12-S` | model·index generation·환경 고정 receipt | 계획 |
| `R3-CONTROL-HOLDOUT` | `R3-W12-D` | 기존 frozen holdout 미열람 확인 | 계획 |

## 9. 최종보고서 증빙, 13~16주

| ID | 목표 주장 | 요구 증거 | 상태 | 실제 근거·결과 |
|---|---|---|---|---|
| `RF-W13-L` | development 1차 80쌍을 사람 검수했다 | pack revision, label/confidence/annotator completeness | 계획 | 시작 기준 `PRE-EVAL-01`, 사람 라벨 0/200 |
| `RF-W13-U` | 검수 UI가 frozen holdout을 노출하지 않았다 | route/state test, browser evidence | 계획 | 제출 전 입력 |
| `RF-W13-T` | 동시 저장·receipt 정책 테스트를 재통과했다 | process-lock test result | 계획 | 제출 전 입력 |
| `RF-W14-L` | development 160/160 검수를 완결하고 저신뢰 항목을 재검토했다 | pack hash, label 분포, review log | 계획 | 제출 전 입력 |
| `RF-W14-E` | development만으로 임계값·오류 유형을 비교했다 | script/version, dev-only metrics | 계획 | holdout 미열람 유지 |
| `RF-W14-F` | code·threshold·dev hash를 동결했다 | full commit, canonical dev SHA, ADR | 계획 | 제출 전 입력 |
| `RF-W15-R` | canonical receipt로 frozen holdout 40쌍을 한 번 열었다 | receipt path·SHA·timestamp | 계획 | 제출 전 입력 |
| `RF-W15-E` | frozen holdout을 단회 평가하고 이후 결정을 바꾸지 않았다 | immutable report, code/threshold hash comparison | 계획 | 제출 전 입력 |
| `RF-W15-O` | 부하·PostgreSQL backup/restore·보안 경계를 rehearsal했다 | load report, commands, logs, row/hash, TLS/Turnstile 상태 | 계획 | 미운영 항목은 차단·보류로 기록 |
| `RF-W16-F` | 최종 보고서·발표자료를 제출했다 | 파일 hash와 제출 시각 | 계획 | 제출 전 입력 |
| `RF-W16-V` | 최종 시연 영상을 만들었다 | 영상 경로, 길이, 시나리오 | 계획 | 제출 전 입력 |
| `RF-W16-C` | clean 재현·전체 회귀·문서·팀 기여도를 최종 정리했다 | independent run, suite 결과, docs diff, member mapping | 계획 | 제출 전 입력 |

### 최종보고서 세부 실행 ID

| 세부 ID | 연결 상위 주장 | 제출할 증거 | 상태 |
|---|---|---|---|
| `RF-W13-SPLIT` | `RF-W13-U` | dev·holdout split hash와 비노출 확인 | 계획 |
| `RF-W13-L80` | `RF-W13-L` | 첫 80쌍 label·confidence·annotator receipt | 계획 |
| `RF-W13-QA` | `RF-W13-T` | 누락·cannot_assess·동시 저장 품질검사 | 계획 |
| `RF-W14-L160` | `RF-W14-L` | dev 160/160 완결 hash와 분포 | 계획 |
| `RF-W14-CAL` | `RF-W14-E` | dev-only calibration·오류 분석 report | 계획 |
| `RF-W14-FREEZE` | `RF-W14-F` | code·threshold·dev hash freeze receipt | 계획 |
| `RF-W15-HOLDOUT` | `RF-W15-R`, `RF-W15-E` | 단회 unlock receipt와 immutable result | 계획 |
| `RF-W15-LOAD` | `RF-W15-O` | 부하 환경·raw result·p50/p95/RPS | 계획 |
| `RF-W15-DB` | `RF-W15-O` | PostgreSQL migration·backup·restore·checksum | 계획 |
| `RF-W15-SEC` | `RF-W15-O` | TLS·Turnstile·secret·rate-limit rehearsal | 계획 |
| `RF-W16-REL` | `RF-W16-C` | clean commit/tag와 release manifest | 계획 |
| `RF-W16-DOC` | `RF-W16-F` | 최종보고서·모델카드·재현 안내서 hash | 계획 |
| `RF-W16-SLIDE` | `RF-W16-F` | 발표자료 파일과 제출 시각 | 계획 |
| `RF-W16-VIDEO` | `RF-W16-V` | 시연 영상·시나리오·길이 | 계획 |

## 10. 화면·그래프 파일 규칙

화면과 그래프는 저장소에 포함할 권리가 확인된 경우에만 다음 규칙을 사용합니다.

```text
docs/course/2026-2/evidence/
  w04/
    R1-W03-B_bbq-fixture-detail_1280x800.png
    R1-W04-U_dashboard_1280x800.png
  w08/
    R2-W06-Q_dataset-distribution.png
    R2-W07-R_robustness-summary.png
  w12/
    R3-W10-S_svg-security-result.png
    R3-W11-P_vector-paired-metrics.png
    R3-W12-S_handwriting-failure-slices.png
  w16/
    RF-W14-E_dev-confusion-matrix.png
    RF-W15-E_holdout-summary.png
    RF-W15-O_latency-distribution.png
```

현재 `evidence/` 파일이 없다는 이유로 빈 이미지나 가짜 그래프를 만들지 않습니다.
실험 report에서 그래프를 재생성할 명령과 source JSON을 함께 보존합니다.

## 11. 제출별 마감 점검

### 1차, 2026-09-27

- [ ] `R1-*` 상태와 실제 증거 입력
- [ ] PRE 기준 증거일과 R1 학기 실행일 기록
- [ ] MVP·file/DB·KIPRIS·BFF 실행 재현
- [ ] BBQ 화면을 fixture로 명시하고 live `마크렌즈` 기록과 분리

### 2차, 2026-10-25

- [ ] `R2-*` 상태와 실제 증거 입력
- [ ] BBQ 100→105와 105→1,000 계보·호출 수
- [ ] 1,000 rights와 769 family·format mismatch 동시 보고
- [ ] scoring·artifact·강건성 재현과 production 미운영 경계

### 3차, 2026-11-22

- [ ] `R3-*` 상태와 실제 증거 입력
- [ ] canonical image 전후 decode·hash·회귀 결과
- [ ] SVG threat model과 정상·악성 fixture
- [ ] vector 120+와 handwriting 90+ query, paired metric, license

### 최종, 2026-12-20

- [ ] `RF-*` 상태와 실제 증거 입력
- [ ] development 160/160과 holdout 미열람 확인
- [ ] freeze·receipt·holdout·code hash 일치
- [ ] 부하·DB backup/restore·보안 rehearsal 결과
- [ ] 미완료·보류·법적 한계 표시
