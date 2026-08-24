# MarkLens 기술 재감사 보고서

기준일: 2026-08-15  
대상: `develop` 기준 backend, ML, frontend, 데이터 파이프라인, 배포 경계, 문서  
판정: **로컬 연구 베타 적합, 공개 production 배포는 수동 게이트 완료 전 금지**

## 결론

이번 재감사에서는 보고서만 작성하지 않고 발견한 고위험 문제를 코드, 테스트,
배포 템플릿과 사용자 문구에 함께 반영했다. 현재 앱은 업로드 이미지와 제한된
로컬 표본의 **시각 유사 후보를 찾는 연구 도구**로 동작한다. 등록 가능성, 침해,
법적 안전 또는 전체 선행 권리 부재를 판정하는 제품은 아니다.

2026-08-15 데이터 확장 후 운영 metadata·이미지·FAISS index는 서로 다른 출원번호
기준으로 각각 1,000건이며, manifest의 authoritative key와 vector count도 1,000으로
일치한다. 현재 generation은 `20260815T023540Z-0d79c662f4c8`이다. 다만 인덱스
manifest는 작업 중 생성되어 `git.dirty=true`이므로 배포 증거로
사용할 수 없다. 통합 변경을 커밋한 뒤 clean tree에서 다시 빌드해야 한다.

## 감사 범위와 방법

- 정적 추적: 요청 경계, 설정, 예외, 파일·DB·index 수명주기, 브라우저 상태 전이
- 공격 관점: 비밀 노출, SSRF·redirect, 업로드 폭탄, 경로 순회, 요청 경합, rate limit
- ML 관점: 점수 단조성, 입력 기권, 전처리, index 계약, 데이터 편향, 강건성
- 실행 검증: Python·frontend 테스트, lint, typecheck, build, dependency audit, 실제 모델 smoke
- 운영 검증: Compose·Nginx·환경변수·health·request ID·비공개 네트워크 계약
- 문서 검증: README, API 계약, 보안 가이드, 모델·데이터 카드의 코드 일치 여부

KIPRIS는 먼저 BBQ 출원인 1페이지를 1회 호출해 5건을 파일럿 승격했다. 이어 월간
호출 예산 안에서 신규 895건을 격리 수집·감사해 총 1,000건으로 승격했다. 8월 로컬
카운터는 `145/950`이며 서지상세·유사군 보강은 실행하지 않았다. 실제 Cloudflare/도메인
배포와 production DB 변경은 수행하지 않았다.

## 주요 조치

### 검색과 ML

- 화면의 `top_k`와 무관한 내부 `scoring_k=20`으로 상태 판정을 고정했다.
- top-1 similarity가 높아질수록 상태가 내려가지 않는 단조 규칙으로 교체했다.
- `NaN`, infinite, 범위 밖 점수는 거부하고 `SAFE` 표현을 제거했다.
- 빈 이미지, 빈 alpha, 낮은 대비 입력은 결과 대신 재업로드를 요청한다.
- 업로드를 한 번만 decode하고 bytes, 가로·세로, 총 pixel 제한을 실제로 집행한다.
- index·metadata·manifest의 세대, 모델, 전처리, 차원, metric, key, SHA-256을 검증한다.
- production에서 결과 이미지를 공개할 때는 안전 경로, 파일별·전체 이미지 SHA-256까지 검증한다.
- Git provenance는 추적 파일뿐 아니라 새 untracked source도 `dirty`로 기록한다.
- authoritative key만 원자적으로 게시하며 수집 중 dirty marker가 남으면 기동하지 않는다.

### KIPRIS와 데이터 파이프라인

- KIPRIS endpoint를 HTTPS 공식 host로 제한하고 redirect를 따르지 않는다.
- key와 검색어가 들어간 URL 또는 upstream 예외를 로그·응답에 노출하지 않는다.
- 예상 밖 XML, 오류 result code, 반복 page를 빈 결과로 오인하지 않고 실패 처리한다.
- `/name-check`를 POST body 계약으로 전환하고 GET은 한 릴리스만 deprecated 유지한다.
- `complete`, `scanned_count`, `checked_at`, `source`를 제공하며 불완전 응답은 중립 처리한다.
- page 단위 저장·checkpoint, 실제 cursor, 요청 limit 조기 중단, dirty index 복구를 추가했다.
- 운영·스테이징 출원번호 합집합에 대한 `--target-total` 정확 중단과 source별 제한 재시도를 추가했다.
- 인덱싱 안전 한도를 넘는 스테이징 이미지는 삭제하지 않고 감사 manifest와 함께 격리한다.
- KIPRIS 호출 counter는 read-only data와 분리한 writable state에 원자적으로 저장한다.

### 브라우저와 API 경계

- 브라우저가 FastAPI key를 알 수 없도록 Next.js same-origin BFF를 도입했다.
- search, name-check, image, health BFF에 런타임 schema 검증과 안전한 오류 매핑을 적용했다.
- Turnstile은 multipart parsing 전에 검증하며 action과 production hostname을 고정한다.
- 중복 검색을 취소하고 generation을 확인해 늦은 응답이 reset 결과를 덮지 못하게 했다.
- 사진·화면 캡처용 수동 crop, object URL 정리, 결과 이미지 null·실패 상태를 구현했다.
- 300px 미만 Turnstile compact 전환과 세로·가로 mobile crop overflow를 보완했다.
- UI는 canonical `status_code`를 우선하며 deprecated grade는 호환 fallback으로만 읽는다.

### 공개 배포 경계

- 기본 host bind를 `127.0.0.1`로 두고 FastAPI·PostgreSQL은 외부에 게시하지 않는다.
- trusted TLS edge가 검증한 client IP만 gateway 전용 header로 전달하도록 계약했다.
- Nginx rate limit은 검색 5회/분, 명칭 2회/분이며 JSON `429`와 `Retry-After`를 반환한다.
- gateway, BFF, FastAPI가 같은 `X-Request-ID`를 생성·전달·응답·로그에 사용한다.
- production은 PostgreSQL, 32자 이상 API key, Turnstile, clean artifact manifest를
  fail-closed로 요구한다.
- 결과 이미지는 권리 확인 전 기본 비공개이며 임의 외부 HTTPS 이미지를 CSP로 허용하지 않는다.

## 검증 증거

전체 Python suite, frontend Vitest·E2E·lint·typecheck·build와 1,000건 runtime smoke는
2026-08-15 최종 실행값이다. 날짜를 따로 적은 ML 전용 suite와 105건 smoke는
2026-08-14 기준선이며 이번 최종 실행에서 다시 측정한 값으로 오인하지 않는다.

| 범위 | 결과 |
|---|---|
| 전체 Python suite | `337 passed, 5 skipped` |
| 2026-08-14 ML 전용 suite | `116 passed, 1 skipped` |
| Python Ruff E/F/I | 통과 |
| Frontend Vitest | `34/34 passed` |
| Frontend Playwright E2E | Chromium 320x568·667x375·desktop 각 3개, `9/9 passed` (`18.7s`) |
| Frontend lint·typecheck | 통과 |
| Next.js production build | 통과, BFF 4개 route 확인 |
| npm audit | 알려진 취약점 `0` |
| pip check | 통과 |
| pip-audit | 알려진 취약점 없음. 로컬 CPU torch wheel은 PyPI 외 배포라 별도 확인 |
| 2026-08-14 모델·index smoke | OpenCLIP 로드, 당시 index·metadata 각 105건, 신규 BBQ 이미지 top-1 `1.0000` |
| 2026-08-14 BFF health | `engine_ready=true`, 당시 index 105, generation 일치 |
| 현재 FastAPI·BFF health | generation `20260815T023540Z-0d79c662f4c8`, ready, index·metadata 각 1,000건 |
| 현재 BFF 검색 | unique sample `4019700003653.png`, top-1 `0.9999999404`, top-5 5건 |
| 현재 이미지 proxy | HTTP 200, `image/png`, 22,479 bytes |
| 현재 검수 서버 | pack `vlp2_d32d53e3b6c101517517`, development 160쌍, 라벨 0건 |
| runtime smoke의 KIPRIS 호출 | `/name-check` 미호출, 0회 |
| 2026-08-15 운영 데이터 감사 | 권리·이미지·벡터 각 1,000건, 누락·고아·중복 출원번호·차단 이슈 0건 |
| KIPRIS 확장 | 105 → 1,000건, 이번 확장 140회, 8월 카운터 `145/950`, 서지상세 0회 |
| 현재 라벨링 팩 | `vlp2_d32d53e3b6c101517517`, family 769개, 200쌍(160/40), 사람 라벨 0건 |
| 현재 v4 강건성 | 25 원본 + 100 변형, decode 실패 0, exact R@5·상태 안정성 모두 `1.0` |
| 2026-08-14 실제 브라우저 smoke | 데스크톱 검색·결과 이미지, 320/360px·가로 mobile crop·취소 확인 |
| Compose·CI YAML | 파싱 통과 |
| Git secret/history 확인 | 현재 key가 도달 가능한 Git blob에 없음 |

다섯 skip은 실데이터/임시 이미지 root 조건부 테스트 2건, 실제 KIPRIS 호출 방지 1건,
`MARKLENS_TEST_DATABASE_URL`이 없는 PostgreSQL integration 1건, 현재 Windows의
symlink 생성 권한 테스트 1건이다. GitHub Actions는 PostgreSQL service를 제공하므로
해당 integration을 실행하도록 구성했다.

현재 Windows에는 Docker/Nginx 실행 파일이 없어 image build, `nginx -t`, 실제 container
topology는 로컬에서 실행하지 못했다. CI에는 Compose config와 공식 Nginx image syntax
검사를 추가했다. 실제 배포 전에는 별도 release 환경에서 container startup smoke까지
통과해야 한다.

## ML 실측과 해석

현재 1,000-vector generation `20260815T023540Z-0d79c662f4c8`의 v4 강건성 평가는
25개 원본과 네 변형 100개, 총 125 query를 사용했고 decode 실패는 0건이었다.

| 입력 | exact R@1 | exact R@5 | 상태 안정성 | 평균 target similarity |
|---|---:|---:|---:|---:|
| 원본 | 0.76 | 1.0 | 1.0 | 1.000000 |
| 90% center crop | 0.72 | 1.0 | 1.0 | 0.945949 |
| 회색 여백 20% | 0.76 | 1.0 | 1.0 | 0.909052 |
| JPEG 품질 60 | 0.76 | 1.0 | 1.0 | 0.982898 |
| 8도 회전 | 0.76 | 1.0 | 1.0 | 0.936337 |

원본 exact R@1 miss 6건은 모두 byte-identical 그룹에 속했고 target 파일은 rank 2~3에
있었다. 105건 때보다 동일 이미지 그룹과 동률 기회가 늘어난 영향을 함께 봐야 하며,
세대와 표본이 다른 v3의 `0.96`과 직접 성능 비교할 수 없다. v4는 family R@1을
측정하지 않았으므로 family retrieval 성능이나 새로운 상표 일반화 성능은 알 수 없다.

현재 라벨링 팩 `vlp2_d32d53e3b6c101517517`은 같은 generation에서 자동 그룹화한
769개 visual family를 기준으로 development 160쌍과 frozen holdout 40쌍을 구성했다.
사람 라벨은 0/200이므로 임계값 교정과 fine-tuning은 계속 차단한다.

### 확장 전 v3 기준선

다음 v3 결과는 확장 전 105-vector generation `20260814T143910Z-99ed3be0ce04`의
역사적 기준선이다. 25개 원본과 네 변형 100개,
총 125 query에서 모든 변형의 exact Recall@1은 `0.96`, Recall@5는 `1.0`이었다.
R@1 miss 한 건은 byte-identical 3파일 family 내부 rank-2 tie다. 평균 target similarity는
crop `0.956777`, 회색 여백 `0.919369`, JPEG `0.989764`, 회전 `0.953514`였다.
회색 여백 한 건은 rank 1을 유지했지만 `STRONG_MATCH`에서 `POSSIBLE_MATCH`로 이동해
상태 안정성이 `0.96`이었고 나머지는 `1.0`이었다.

이 결과는 당시 105장 중 고정 25장 내부 표본의 변형 강건성이지 새로운 상표의 정확도나 법적
위험 예측 성능이 아니다. 현재 v4와도 세대·표본이 달라 직접 비교 근거로 쓰지 않는다.

같은 역사적 105장 전체에 대해 legacy center crop과 global letterbox를 모드별 525 query로
paired 비교했다. Global은 평균 target cosine이 `+0.003082`였지만 non-family margin은
`-0.003746`이고 family Recall@5도 `-0.002381`이어서 전환 gate를 통과하지 못했다.
운영 전처리는 legacy를 유지한다. 라벨이 `0/200`이므로 fine-tuning 실행도 차단한다.

## 남은 위험과 배포 게이트

1. 기존 KIPRIS key를 회전하고 새 key는 비밀 저장소에서 관리한다.
2. KIPRIS 이미지·metadata의 공개 재배포와 비상업적 사용 조건을 서면 확인한다.
3. clean 통합 커밋에서 index와 현재 1,000건 기준 평가 artifact를 다시 생성한다.
4. 200쌍 사람 라벨과 40쌍 frozen holdout 평가를 완료한다.
5. 실제 PostgreSQL migration, backup·restore, container startup을 release 환경에서 검증한다.
6. 실제 Turnstile key·hostname, TLS edge, firewall, request ID와 사용자 IP 전달을 검증한다.
7. release 환경에서 실제 Turnstile과 비공개 이미지 설정으로 upload, crop, cancel,
   search, image-null 흐름을 다시 확인한다.

현재 backend의 cache, outbound budget, 일부 rate limit은 단일 프로세스 계약이다. 제공된
Compose는 backend worker를 하나로 고정한다. 여러 worker나 인스턴스가 필요하면 Redis
또는 PostgreSQL 기반 공유 lock·counter로 전환하기 전까지 확장하면 안 된다.

## 제품 한계

- 데이터는 1,000건·Nice 45개 류로 확장했지만 등록 상태와 선택 출원인 중심의 편의 표본이다.
- 35류가 185건(18.5%)이며 12개 류는 10건 미만이다. 최저 23류는 4건이다.
- 유사군은 100/1,000건만 채워져 있어 서지상세 기반 보강 전에는 해당 축을 분석에 쓰지 않는다.
- 수집 범위는 전체 pending·active 선행 권리를 대표하지 않는다.
- 동일 이미지 해시는 123그룹·330파일이고 정규화 동일 명칭은 141그룹이다. 별도 권리를
  자동 삭제하지 않으며 결과 UI의 시각 family 묶음은 아직 제한적이다.
- 긴 워드마크용 global letterbox 전처리는 후보이며 운영 기본값은 아직 center crop이다.
- X1 호칭, X3 관념, X4 상품 견련성 및 통합 위험 모델은 구현되지 않았다.

따라서 현재 적절한 명칭은 **시각 후보 검색 연구 베타**다.

## 관련 문서

- [README](../README.md)
- [API 계약](MarkLens_API계약_v1.md)
- [공개 배포·보안 가이드](MarkLens_공개배포_보안가이드.md)
- [모델·데이터 카드](MarkLens_모델카드_데이터카드.md)
- [ML 평가·라벨링](../ml/evaluation/README.md)
- [Security policy](../SECURITY.md)
