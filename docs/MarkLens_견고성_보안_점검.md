# MarkLens 견고성·보안 점검 (2026-11-23)

기준: `develop` = `main` = `3a1db95`(PR #107 병합 — 서비스 기본 모델 v1.4.1), 브랜치 `chore/robustness-review`.
입력 경계·예외 처리·보안과, 오류는 아니지만 결과가 이상한 입력을 점검했다. **점검과 보고만 했고 서비스 코드는 고치지 않았다.**
KIPRIS 호출 0(상표명 확인 경로는 모의 응답으로 요청 URL 만 봄), 공격성 요청은 이 Mac 의 로컬 서버에만 보냈다. 외부로 나간 것은
의존성 감사(`npm audit`·`pip-audit`)의 레지스트리 조회뿐이다.

캡처·원자료는 비공개 DB 로고와 임시 API 키가 들어 있어 저장소 밖에 둔다: `~/marklens-archive/robustness-20261123/`
(`ui/` 화면 캡처 U1–U21·`probe_*.json`·`logs/`·`images/` 시험 이미지·`npm_audit_*.json`·`pip_audit.json`·`scan_secrets.txt`).

## 0. 한눈에

| 우선순위 | 건수 | 항목 |
|---|---:|---|
| P0 결과를 잘못 믿게 | 2 | R-P0-1 등록 로고 그대로 + 다른 이름 → 그 등록상표가 목록에서 사라지고 '주의' · R-P0-2 설명적 낱말만으로 된 이름이 '위험'(호칭 100%) |
| P0 보안·서버 멈춤 | 0 | — |
| P1 | 6 | 빈 이미지 422·영어 문구 · 모델 적재 실패에도 /health 정상 · 503 에 내부 경로 · 가늘고 긴 이미지 자르기 축소 · 429 영어 한도 문자열 · 보이지 않는 서식 문자 |
| P2 | 13 | 3장 표 |
| 계약 공백 | 13 | 4장 |

잘 된 것: 응답 194개(입력 97가지 × API 직접·중계) 중 500 은 0, 응답에 키·스택·내부 경로가 나간 것 0(모델 적재 실패 503 만 예외 — R-P1-3),
서버가 멈춘 경우 0. 경로 이동·인코딩 우회로 `.env` 를 읽은 것 0, Turnstile 위조 토큰 전부 403, 커밋 이력의 키·`.env` 0, 운영 npm 의존성
취약점 0. 같은 요청 두 번·대소문자·전각·앞뒤 공백·NFC/NFD 는 같은 결과.

## 1. 준비

### 1-1. 환경(실제 모델, 프로덕션 빌드)

| 서버 | 설정 | 용도 |
|---|---|---|
| 백엔드 8000 | 실제 CLIP·OCR·X3, 한도는 환경 변수로만 상향(`MARKLENS_*_RATELIMIT=6000/minute`), `KIPRIS_ACCESS_KEY=`·`KIPRIS_TRIAL_ACCESS_KEY=` 비움, `MARKLENS_API_KEY` 임시값 | 입력 경계·결과·부하 |
| 백엔드 8001 | 위와 같고 한도만 기본(검색 10/minute) | 한도 점검 |
| 중계 3000·3001·3002 | `next build` 뒤 standalone `node server.js`(`NODE_ENV=production`), 3000 → 8000, 3001 → 8001, 3002 → 아무도 없는 8009 | 보안 헤더·용량 상한·중계 동작·백엔드 꺼짐 |
| 화면 | Playwright Chromium 1440×900, Cloudflare 스크립트 요청은 가짜 위젯으로 바꿈 | 화면 문구·캡처 |

- Turnstile 검증은 운영 코드(`lib/server/turnstile.ts` — hostname·action 확인 포함) 그대로 돌리고, `siteverify` 호출만 Node 시작 때 끼운 모의 함수가 받는다(`scripts/robustness/mock_turnstile_fetch.cjs` — 토큰 접두어로 성공·거부·다른 hostname·다른 action, 그 밖의 외부 요청은 모두 막음).
- 판정 기준: 기대 동작은 API 계약 v2(§1·§5). 계약이 정하지 않은 입력은 판정하지 않고 "계약 공백"(4장)으로 모았다. 요청 하나가 5초를 넘거나 서버 메모리가 계속 늘면 문제로 봤다.
- nginx·Docker 는 이 Mac 에 없어 `deploy/nginx.conf`·`compose.production.yml` 을 읽어 정적으로 점검했다 — **실행 확인 못 함**(5장).

### 1-2. 이미 있는 시험(입력 검증·예외·보안) — 다시 만들지 않음

| 파일 | 다루는 것 |
|---|---|
| `backend/tests/test_search_v2_api.py`(19) | 입력 조합 7가지, 필드 검증·중복 스칼라·파일을 텍스트 필드에, 치수 초과를 디코딩 전에 거절, `top_k` 잘못된 값·경계, 요청·업로드 크기 상한, 빈 요청, 색인 미준비 503, 실패 요청도 한도에 셈, 오류 매핑과 로그 비공개, 동시 실행 상한 공유 |
| `backend/tests/test_hardening.py`(12) | API 키 없음·틀림·맞음, `/health` 는 키 없이, 한도 429 한국어, CORS 기본값·환경 변수, 운영 비공개 자격 요구 |
| `backend/tests/test_api_contract.py`(9) | `/health` 계약, `/images` 정적·중첩 키·없는 파일 404, 상표명 확인 키 없음 503 |
| `backend/tests/test_engine_manifest.py`(12) | 산출물 해시 불일치·dirty 빌드 거절, 공개 이미지 누락·변조·안전하지 않은 키 거절 |
| `backend/tests/test_kipris_client.py`·`test_namecheck.py` | KIPRIS URL 정책(안전하지 않은 대상 거절), HTTP 오류에 키·질의 노출 없음, 요청별 시간 제한, 호출 카운터 손상 때 닫힘 |
| `backend/tests/test_request_id.py`(2) | 요청 ID 가 안전하지 않으면 바꿈 |
| `frontend/app/api/search-v2.test.ts`(25+) | 중계 순서(content-length → `top_k` → 토큰 → 파싱), 토큰 없음·검증 실패 403, 검증 설정 없음 503, MIME 3종·10 MiB 경계, 100자(코드 포인트), 유사군 형식·60개, `type_override`, 상류 상태·안전 헤더 전달, 취소 전달 |
| `frontend/app/api/routes.test.ts`(9) | 이미지 경로 조각 거절, 운영에서 개발 우회 무시, action 고정, 예상 밖 hostname 거절, 운영 hostname 목록 필수 |
| `frontend/lib/api.test.ts`(8) | 이미지 URL 은 중계 경유만(스킴·경로 이동 거절), 같은 출처로만 전송, 계약이 깨지면 닫힘 |
| `frontend/components/TurnstileWidget.test.tsx`(6)·`next.config.test.ts`(1) | 설정 없음 경고·재시도, 결과 이미지는 같은 출처만 |
| `frontend/e2e/marklens.spec.ts`(5) | 정상 흐름(자르기·결과·이름 근거·상품 유지·업종 세트). 오류·보안 전용 E2E 는 없음 |

### 1-3. 이번에 더한 시험(새 파일만, 팀원 시험 파일은 안 고침)

| 파일 | 지금 통과(가드) | 지금 실패 → strict xfail / `it.fails`(사유에 항목 번호) |
|---|---|---|
| `backend/tests/test_robustness_review.py` | 같은 로고만 넣으면 '위험'(가짜 엔진), 깨진·위장 업로드에 내부 정보 없음, KIPRIS 질의 인코딩 4가지(`&accessKey=` 덮어쓰기 불가), KIPRIS 요청 URL(키·이름)이 INFO 로그에 안 남음 | R-P0-1 · R-P1-1 · R-P1-2 · R-P1-3 · R-P1-5 |
| `ml/tests/test_robustness_results.py` | 약한 낱말 하나만 겹치면 낮음, 대소문자·전각·앞뒤 공백·NFD 는 같은 판단 | R-P0-2 · R-P1-6 |
| `frontend/lib/robustness.test.ts` | 보통 로고는 2048 이하로 비율 유지 | R-P1-4 |

고치면 해당 시험이 XPASS(엄격)·`it.fails` 실패로 바뀌어 표시를 지우라고 알린다. R-P0-1 을 고치면 기존
`backend/tests/test_multi_search.py::test_type_override_figure_uses_higher_nameless_grade` 의 "자동 유형에는 nameless_floor 없음" 단언도 함께 바뀌어야 한다.

## 2. 점검 결과

### 2-1. 입력 경계(API 직접·중계 경유) — `probe_api.py`

97가지 × 2경로 = 194: 통과 158 · 계약 공백 30 · 기대와 다름 6(E19·E27·E30 양쪽 — R-P1-1). 가장 느린 응답 1.1초.

| 묶음 | 결과 |
|---|---|
| 빈 입력(A, 8) | 필드 없음·공백·줄바꿈·전각 공백·빈 유사군·쉼표만 → 400 "image, name, goods_codes 중 하나는 있어야 합니다."(필드 이름이 문구에 — R-P2-6). 폭 없는 공백만은 200 "후보 없음"(R-P1-6) |
| 이름 변형(B, 22) | 100자 경계 200·101자·1천·1만 자 422 "상표명은 100자 이하로 입력해 주세요.", 이모지·한자·일본어·자모·기호·스크립트 조각 200(화면에서 스크립트 실행 안 됨), NFD 40음절 422(코드 포인트로 셈 — 계약 공백), 제어·ANSI·RTL·잘못된 UTF-8 200(계약 공백) |
| 업종(C, 9) | 없는 코드·중복·60개 경계·소문자 200, 61개·형식 틀림·세미콜론·1만 자 422, 같은 필드 2천 개는 API 400·중계 200(계약 공백) |
| 유형 고치기(D, 6) | 정상 3종 200, "로고"·"Text" 422, 빈 문자열·뒤 공백 422(계약 공백), 유형만 400 |
| 이미지(E, 38) | 깨진 PNG 400·무작위 바이트 415·0바이트 400, 내용과 MIME 이 다른 JPEG·PNG·WebP 200(내용으로 판정), GIF·HEIC·SVG 415, 1×1·31×31 400·32×32 200, 4000×32·32×4000 200, 4097×64 400, 픽셀 수 폭탄 20000² 400(1ms), 약 17MB 413·약 9.7MB 200, 하얀·완전 투명·균일 4096² 422 영어(R-P1-1), 애니메이션 PNG·WebP 첫 프레임 200(계약 공백) |
| 메서드·형식(F, 7) | GET·PUT·DELETE 405, boundary 없음 400, urlencoded 200·JSON·text/plain 400(계약 공백) |
| `top_k`(G, 7) | 0·21·abc·1.5·두 번 422 — 중계는 "결과 개수는 1개에서 20개 사이여야 해요.", API 직접은 pydantic 영어 JSON(내부 경로라 P2) |

### 2-2. 화면(프로덕션 빌드) — `probe_ui.mjs`, 캡처 `ui/U1–U21.png`

| 장면 | 화면 |
|---|---|
| U1·U2 빈 입력·공백 이름 | 검색 버튼 꺼짐 |
| U3 폭 없는 공백만 | 버튼 켜짐 → 200 "후보 없음"(R-P1-6) |
| U4 150자 입력 | 100자에서 잘림(`maxLength`) |
| U5 스크립트 조각 이름 | 200, 스크립트 실행 안 됨 |
| U7·U8 하얀·완전 투명 이미지 | 422 + "Image has insufficient visual contrast…"·"Image alpha channel is fully transparent" 그대로(R-P1-1) |
| U9·U10 17MB·SVG | 올리기 전에 "파일이 너무 커요…"·"PNG, JPG, WEBP 파일만…" |
| U11 깨진 PNG(절반) | 브라우저가 위 절반만 그려 자르기 창이 정상처럼 진행, 검색 버튼 켜짐(R-P2-10) |
| U12 1×1 | 자르기 창 "자를 영역은 가로와 세로가 각각 32px 이상이어야 해요." |
| U13 4000×32 | 400 "이미지가 너무 작습니다: 2048x16 (최소 32x32)"(R-P1-4) |
| U15 백엔드 꺼짐 | 1.3초 뒤 502 "검색 서비스에 연결할 수 없어요." |
| U16 백엔드 멈춤(SIGSTOP 35초) | 31.2초 뒤 504 "검색 서비스 응답 시간이 초과됐어요."(중계 30초 제한, nginx `/api/search/v2` 는 120초 — 중계가 먼저 답함) |
| U17 한도 초과 | 429 "요청이 너무 많습니다. 잠시 후 다시 시도하세요. (허용 한도: 10 per 1 minute)"(R-P1-5) |
| U18 STARBUCKS 로고 + "몬테로사" | '주의 위험도 22%', "시각 유사 상태: 매우 닮은 등록상표가 있어요"인데 STARBUCKS 는 목록에 없음(R-P0-1) |
| U19 "맛있는 커피 전문점" + 카페 세트 | '위험 위험도 67%' + "검증 데이터 기준 10건 중 7건 유사", 1위 "맛있는 만두 전문점 장수손만두 1976" 호칭 100%(R-P0-2) |
| U20·U21 로고 → 이름 / 이름 → 로고 | 둘 다 요청 본문에 이름이 실림(자르기 창이 닫히기 전에는 창 뒤 입력칸에 글자가 안 들어감 — 모달이라 정상) |

### 2-3. 부하·메모리 — `probe_load.py`

| 시험 | 결과 |
|---|---|
| API 직접 같은 이미지 30건 동시 | 전부 200, 최대 2.7초, `/health` 최대 15ms |
| 중계 경유 이미지 + 이름 30건 동시 | 전부 200, 중앙 4.4초·최대 8.7초(R-P2-11), `/health` 최대 72ms |
| 중계 경유 9.7MB 이미지 20건 동시 × 9번 | 전부 200, 최대 9.8–10.3초(R-P2-11). 백엔드 RSS 최고 4.3GB, 중계 RSS 332MB → 8번째 뒤 805MB 에서 멈춤(늘어나는 폭이 줄어듦), 가벼운 요청이 이어지면 332MB 로 돌아옴(앞선 실행에서 855 → 332MB) |
| 서로 다른 긴 이름 2,000건(4개씩) | 전부 200, 중앙 3.6초·95% 4.5초·최대 5.8초, 백엔드 RSS 1.6GB → 800건 무렵 약 2.0GB 에서 멈춤(1.7–2.0GB 사이 오르내림) — 캐시 상한이 듣는다 |

검색은 동시 실행 상한 2(`SEARCH_MAX_CONCURRENCY`)로 줄을 세워 서버가 멈추지 않는다(대기 중에도 `/health` 즉시). 운영 compose 에는 컨테이너 메모리 상한이 없다 —
두게 되면 위 최고값(백엔드 4.3GB, 중계 0.8GB)을 참고.

### 2-4. 시작 단계(모델 JSON·색인 누락·손상) — `probe_startup.py`

| 장면 | 기동 | `/health` | 검색 |
|---|---|---|---|
| 계수 JSON 없음 | 뜸 | 200 ok·engine_ready true(R-P1-2) | 503 "계수 JSON: [Errno 2] No such file or directory: '/var/folders/…/missing.json'"(R-P1-3) |
| 계수 JSON 깨짐 | 뜸 | ok | 503 "계수 JSON: Expecting property name enclosed in double quotes…" |
| 계수 JSON 하한 순서 뒤집음 | 뜸 | ok | 503 "…grade_thresholds 는 (0, 1] 안에서 오름차순이어야 합니다"(적재 검증이 잡음) |
| 색인 없음·색인 깨짐·메타데이터 깨짐 | 기동 실패(종료 코드 3) | — | — (조용히 틀린 결과를 내지 않음) |
| 유형 사전(types.json) 없음 | 뜸 | ok | 200(규칙 폴백) |

### 2-5. 결과가 이상한 입력 — `probe_results.py`(기대를 먼저 적음)

기대 결과는 실행 전에 스크립트 `EXPECT` 에 적고 파일 해시를 남겼다(2026-11-23 12:01, sha256 `c1aee7be…`, 보관 폴더 `probe_results_expect.sha256`·
실행본 `probe_results.as_run.py`). 결과를 본 뒤 원인 확인용으로 더한 항목은 `POST_HOC` 으로 따로 표시했다. 같은 스크립트를 다시 돌려도 값이 같았다.

| 입력 | 기대 | 실제 | 판정 |
|---|---|---|---|
| "커피" + 카페 | 주의 이하 | 주의 0.468 | 기대대로 |
| "맛있는 커피 전문점" + 카페 | 주의 이하 | **위험 0.686**(1위 맛있는 만두 전문점 장수손만두 1976, 호칭 1.0) | R-P0-2 |
| "가" · "별빛" · "1004" · "★★★" | 주의 이하(별빛은 관찰) | 주의 0.338 · 주의 0.199 · 주의 0.466 · 후보 없음 | 기대대로 |
| "스타벅스" + 카페 · "STARBUCKS" | 위험, 1위 STARBUCKS | 위험 0.612 · 위험 0.726, 1위 STARBUCKS COFFEE | 기대대로 |
| "스타벅수" + 카페 · "크린토피야" + 세탁 | 검토 권장 이상 · 위험 | 검토 권장 0.581 · 위험 0.712 | 기대대로 |
| 하얀 빈 이미지 | 400(계약 §5-1) | 422 영어 | R-P1-1 |
| 글자만 이미지(COFFEE) | 주의 이하 | 주의 0.467, OCR 이름 제안 "COFFEE" | 기대대로 |
| 상표 두 개가 든 이미지 | 관찰 | 검토 권장 0.502(BLU hands 1·2위), 도형상표는 5위 '안전' 0.333 | 관찰 |
| 간판 사진 + "칠우불고기" | 주의 이하 | 주의 0.233(사진 판정) | 기대대로 |
| STARBUCKS 로고 + "블루커피" | 위험 | 검토 권장 0.533(BLU hands), STARBUCKS 는 상위 20 밖 | R-P0-1 |
| (사후) STARBUCKS 로고 + "몬테로사" | 검토 권장 이상, STARBUCKS 상위 5 | 주의 0.225, STARBUCKS 상위 20 밖 | R-P0-1 |
| (사후) "맛있는 김밥 전문점"(업종 없음) | 주의 이하 | 검토 권장 0.574 | R-P0-2 |

같아야 하는 입력(전체 등급 + 상위 5개 출원번호):

| 묶음 | 결과 |
|---|---|
| 대소문자(STARBUCKS·starbucks·StarBucks) · 앞뒤 공백·탭 · 전각 · NFC/NFD | 같음 |
| 같은 요청 두 번(이름+업종·이미지) | 같음(위험도·순서까지) |
| 띄어쓰기 | "블루 커피" 등급·1위 같고 3–5위 다름 · "블 루 커 피" 주의 0.269(원본 검토 권장 0.53, R-P2-8) |
| 폭 없는 문자 | U+200B 를 낱말 가운데 넣으면 주의 0.248(R-P1-6) · U+2060·U+00AD 를 낱말 사이에 넣으면 같은 등급(띄어쓰기처럼 작동) |
| 모양이 같은 키릴 글자 | "STАRBUCKS"(А 하나) 주의 0.293 · "SТАRBUСKS"(셋) 주의 0.352·1위 RR(원본 위험 0.726, R-P2-9) |
| 같은 로고의 크기·형식·여백 | 원본 위험 0.634 · 절반 0.594 · JPEG 0.631 · WebP 0.611 · 흰 여백 30% 검토 권장 0.551 — 1위는 모두 같음(R-P2-7) |
| EXIF 회전 표시 | 반영됨(주의 0.399 대 0.393, 1위 같음) |

### 2-6. 보안 — `probe_security.py`

| 점검 | 결과 |
|---|---|
| 검색 한도(기본 설정 8001·3001) | 같은 IP 11번째부터 429. 백엔드 직접 X-Forwarded-For 위조 15건 전부 200(한도 우회 — R-P2-2). 중계 경유는 사용자 A 가 10건 쓰면 다른 사용자 B 도 첫 요청부터 429(백엔드 한도가 중계 하나로 묶임 — R-P2-2) |
| 이미지 경로(`/images`·`/api/images`) | `../`·`%2F`·`%252f`·`%2e%2e`·역슬래시·`%00`·전각 숫자 전부 404/400, `.env` 노출 0. 잘못된 퍼센트 인코딩(`%C0%AE` 등)만 중계 500 text/plain(R-P2-1) |
| 같은 출처·Turnstile | 토큰 없음·거부·다른 hostname·다른 action·3천 자 토큰 → 403. 다른 Origin·Referer 없음 + 유효 토큰은 200(R-P2-3). 중계 사전 요청에 ACAO 없음, 백엔드 CORS 는 허용 Origin 만 |
| 노출 경로 | 중계 3000: `/docs`·`/openapi.json`·`/.env`·`/.git/config`·`/admin`·`/debug`·`/server.js`·`/.next/BUILD_ID` 전부 404. 백엔드 8000: `/docs`·`/redoc`·`/openapi.json` 200(R-P2-4) |
| 보안 헤더(중계) | CSP(`frame-ancestors 'none'`·`object-src 'none'` 등, `script-src` 에 `'unsafe-inline'` — R-P2-5)·nosniff·X-Frame-Options DENY·HSTS·Referrer-Policy·Permissions-Policy·COOP 있음. 검색·상품 응답 `no-store`, 이미지 `public, max-age=3600`(R-P2-13) |
| 오류 응답·로그의 비밀 | 응답에 키·스택 0, 내부 경로는 모델 적재 실패 503 만(R-P1-3). 백엔드 로그 1,976줄에 입력 이름·Traceback·키 이름 0(경로는 기동 로그의 데이터·모델 경로 — 서버 쪽만) |
| 입력 보관 | 이름은 프로세스 메모리의 LRU 캐시(X1·X3·식별력 결합 규칙, 상한 있음 — 재기동 때 사라짐)에만, 디스크·로그 0. 이미지는 요청 처리 중 메모리(1MB 넘는 업로드는 Starlette 가 임시 파일로 받았다가 요청 끝에 지움) — 점검 뒤 임시 폴더에 남은 큰 새 파일 0. 상표명 확인은 이름을 KIPRIS 로 보낸다(화면에 "KIPRIS 이름 확인" 표시) |
| 상표명 확인 KIPRIS 요청 인코딩(모의) | `&`·`=`·`#`·`%`·`+`·`?`·`/`·줄바꿈·`<script>` 가 퍼센트 인코딩되어 한 값으로 감, 이름으로 `accessKey` 를 덮을 수 없음, httpx 로거가 WARNING 이라 요청 URL(키·이름)이 로그에 안 남음 — 새 시험으로 고정 |
| nginx(정적) | 클라이언트 IP = `X-MarkLens-Client-IP` 가 있으면 그 값(TLS 앞단이 지우고 다시 넣어야 — 보안 가이드 8항), 검색 5r/m·본문 11m, 127.0.0.1 바인드, 백엔드 공개 포트 없음, uvicorn `--forwarded-allow-ips "*"`(내부망). 실행 확인 못 함 |

### 2-7. 비밀·키 검색 — `scan_secrets.py`(값은 출력하지 않고 위치·모양·길이만)

추적 파일 3곳·커밋 이력(모든 브랜치) 4곳이 걸렸고 전부 오탐이다: CI 더미 값(`ci-only-…`·`ci-placeholder-not-used`), Cloudflare 공개 시험 비밀,
UI 평가 문서의 변수 이름. `.env` 계열 파일이 커밋된 적 없음, `.gitignore` 가 `.env`·`frontend/.env.local`·`backend/.env` 를 막음.

### 2-8. 의존성 감사

- `npm audit --omit=dev`: 0건.
- `npm audit`(개발 포함): 13건(높음 4 — `vite` 8.2.0–8.2.2·`brace-expansion`·`browserslist`·`js-yaml`, 보통 9 — `vitest`·`@vitest/mocker`(4.1.12 에서 고침)·`typescript-eslint` 계열·`minimatch`). 모두 시험·빌드 도구라 운영 서버에는 안 들어감.
- `pip-audit`(ml/venv): 6패키지, 모두 고친 버전 있음 — 운영 경로 `certifi` 2026.4.22 → 2026.10.18(httpx·requests), `opentelemetry-api` 1.45.1 → 1.45.2(FastAPI 의존), `fsspec` 2026.4.0 → 2026.6.0(torch·HF), `msgpack` 1.2.2 → 1.2.3(wordfreq), 개발 `brotli` 1.2.0 → 1.2.1·`werkzeug` 3.1.8 → 3.1.9(locust). `constraints.txt` 에 고정된 것은 없음.

## 3. 발견 항목

담당은 파일 기준이다 — 현수님(API·중계·배포), 지원님(결과 화면 표시), 다빈(엔진·모델·식별력). 크기 S(반나절 이내)·M(하루–이틀, 재측정 포함)·L.

### P0 — 결과를 잘못 믿게

#### R-P0-1 등록 로고와 똑같은 이미지에 다른 이름을 넣으면 그 등록상표가 목록에서 사라지고 '주의'

- **재현**: `ml/data/images/4020200011726.png`(STARBUCKS COFFEE 등록 로고) + 이름 "몬테로사"(또는 "블루커피"), 업종 없음 → `POST /search/v2?top_k=20`. 화면 U18. `probe_results.py` 사후 1·2번.
- **실제**: 전체 '주의' 0.225(블루커피는 BLU hands 때문에 검토 권장 0.533), 같은 로고 후보는 이름 있는 판단 0.092 로 상위 20(최대) 밖이라 화면에 없다. 화면에는 "시각 유사 상태: 매우 닮은 등록상표가 있어요" 한 줄만 있고 어느 상표인지 보여 주지 않는다. 이름 없이 같은 로고만 넣으면 '위험' 0.634·1위, 이름이 "스타벅스"면 '위험' 0.609·1위.
- **기대**: 등록 로고를 그대로 쓴 입력은 이름이 달라도 그 상표가 목록에 나오고 검토 권장 이상(로고 도용은 도형상표 점검의 핵심 경우).
- **원인**: 이름이 있으면 질의 유형이 늘 문자계(`backend/src/core/multi_search.py` `_resolve_query_type`, 계약 §2-4 5항 — 이 로고는 OCR 글자 면적 0.0·도형 면적 0.73 인데도 결합-문자요부) → 후보는 이름 있는 판단만 받는다. v1.4.1 이름 있는 `x2_whole` 집합에서는 이미지 1.0 이라도 이름이 무관하면 0.09 수준. 이름을 뺀 판단과 견주는 `nameless_floor` 는 유형을 도형계로 고친 질의에만(계약 §2-4 6항), 도형 규칙(이미지 ≥ 0.9 → 검토 권장)도 도형계 유형에만 걸린다. 정렬은 등급 → 등급 안 위치라 0.09 는 같은 '주의' 안에서도 20위 밖이다.
- **고치는 방향**: (가) 이미지가 있는 이름 있는 질의에도 이름을 뺀 판단과 견줘 높은 쪽을 쓴다(`nameless_floor` 를 자동 유형으로 — 등급·정렬 모두), 또는 (나) 이미지 유사도가 도형 규칙 τ(0.9) 이상인 후보는 유형과 상관없이 검토 권장 이상 + 목록에 남긴다. 어느 쪽이든 모델 결정이라 표본 A·대조군·시나리오 16종으로 영향을 잰 뒤 정한다. 화면은 "매우 닮은 등록상표" 줄에 그 상표를 함께 보여 주면 모델을 바꾸기 전에도 놓치지 않는다.
- **담당·크기**: 다빈(엔진·모델 결정) M, 화면 표시는 지원님 S.
- **시험**: `backend/tests/test_robustness_review.py::test_identical_logo_with_unrelated_name_is_flagged`(xfail — 가짜 엔진에서 같은 로고 + "블루커피" 가 '안전' 0.072).

#### R-P0-2 설명적 낱말만으로 된 이름이 '위험' — "호칭 100%"

- **재현**: 이름 "맛있는 커피 전문점" + 카페 세트 → '위험' 0.686(화면 U19 는 업종 세트 흐름으로 '위험' 67% + "검증 데이터 기준 10건 중 7건 유사"). 업종 없이 "맛있는 김밥 전문점" → 검토 권장 0.574. "맛있는 ○○ 전문점" 꼴이면 모두 같은 후보에 호칭 1.0.
- **실제**: 1위 "맛있는 만두 전문점 장수손만두 1976" 호칭 100%, 근거 칩 "호칭이 거의 같아 검토 권장으로 올렸습니다". 질의의 요부 후보는 없음(`salient.query_tokens` 빈 목록) — 후보의 요부는 "장수손".
- **기대**: 낱말이 모두 식별력이 약한 이름은 그 약한 낱말이 겹친다고 호칭이 같다고 보지 않는다(주의 이하). 이런 이름의 진짜 문제는 혼동이 아니라 식별력(상표법 33조 1항)이라 그 안내가 맞다.
- **원인**: 식별력 `ml/src/axes/distinctiveness.py` `pair_generic` — 요부가 없는 질의는 약한 토큰을 넘기지 않고(전체 대비, 2000후2453) `combined_weak_run` 이 양쪽에 같은 순서로 있는 약한 토큰 2개("맛있는"·"전문점" — 사이에 다른 낱말이 있어도)를 요부 후보로 보아 후보 쪽에서도 빼지 않는다 → X1 이 공통 부분을 같은 호칭으로 봐 1.0 → 모델 로짓 x1_d 1.40 + x1_d×문자계 2.15 + 요부 플래그 1.21 − 1.40. 연속 아닌 약한 토큰열을 요부로 안 보게 모의하면 호칭 0.401·'주의' 0.288.
- **고치는 방향**: `combined_weak_run` 을 양쪽 모두 이어진 토큰열로 좁히거나, 질의에 요부가 없을 때는 약한 토큰 일치를 호칭 근거로 쓰지 않는다. 함께 "이름이 모두 설명적인 낱말이라 등록 자체가 어려울 수 있어요" 안내(caveat). 식별력 규칙 v0.3 변경이라 학습 특징·벤치마크 재측정 뒤 결정.
- **담당·크기**: 다빈(식별력 규칙·모델) M, 안내 문구 화면은 지원님 S.
- **시험**: `ml/tests/test_robustness_results.py::test_descriptive_only_name_is_not_rated_danger`(xfail).

### P1 — 사용자에게 보이는 오류·이상한 문구

| ID | 항목 | 재현 → 실제 | 기대 | 원인 위치 | 고치는 방향 | 담당·크기 | 시험 |
|---|---|---|---|---|---|---|---|
| R-P1-1 | 하얀·완전 투명·균일한 이미지가 422 + 영어 내부 문구 | 흰 PNG(U7)·완전 투명(U8)·흰 4096² → 422 "Image has insufficient visual contrast; upload a non-blank mark (range=0.00, stddev=0.00)" 가 화면에 그대로 | 계약 §5-1: 콘텐츠 품질은 400, 사용자가 읽는 한국어 | `ml/src/preprocess.py` `validate_visual_content`(영어 ValueError) → `backend/src/api/search.py` 의 `except ValueError → 422 str(exc)` | 내용 검사 실패를 별도 예외로 받아 400 + "로고가 보이지 않는 빈 이미지예요. 로고가 있는 이미지를 올려 주세요." | 현수님 S | `test_blank_image_is_400_with_user_facing_korean` |
| R-P1-2 | 계수 JSON 이 없거나 깨져도 `/health` 정상 | `MARKLENS_RISK_MODEL` 을 없는·깨진 파일로 → 서버 뜸, `/health` "ok"·`engine_ready` true, 검색만 503 | 배포 헬스체크가 검색 불가를 알아챔 | `backend/src/api/health.py` 가 `engine.state` 만 봄(`multi_search.state` 미반영) | `search_ready` 필드 또는 status "degraded"(계약 §5-6 와 함께) | 현수님 S | `test_health_reports_unusable_search` |
| R-P1-3 | 모델 적재 실패 503 문구에 서버 내부 절대 경로·파이썬 오류 원문 | 위 상태에서 검색 → "계수 JSON: [Errno 2] No such file or directory: '/var/folders/…/missing.json'" | 사용자 응답은 고정 문구, 원인은 서버 로그 | `multi_search.state.error` 를 `detail` 로(계약 §5-6 이 그렇게 정함) | 고정 문구 "위험도 모델을 준비하지 못했어요. 잠시 뒤 다시 시도해 주세요." + 계약 §5-6 수정 | 현수님 S(계약은 다빈) | `test_model_not_ready_detail_hides_internal_paths` |
| R-P1-4 | 가늘고 긴 이미지가 자르기 축소 때문에 거절 | 4000×32 PNG → 자르기 "전체 이미지 사용" → 2048×16 로 줄어 400 "이미지가 너무 작습니다: 2048x16 (최소 32x32)"(U13). 같은 파일을 API 로 직접 보내면 200 | 서버 허용 범위(32..4096)에 드는 이미지는 그대로 검색 | `frontend/lib/crop.ts` `MAX_OUTPUT_DIMENSION` 2048 비율 축소 | 짧은 변이 32 아래로 내려가면 축소를 줄이거나(짧은 변 ≥ 32 보장), 자르기 단계에서 "너무 가늘어요" 안내 | 현수님 S | `frontend/lib/robustness.test.ts`(`it.fails`) |
| R-P1-5 | 429 문구 끝에 영어 한도 문자열 | 분당 10회 넘김 → "…다시 시도하세요. (허용 한도: 10 per 1 minute)"(U17) | 한국어만 | `backend/src/core/ratelimit.py` 가 slowapi 의 `exc.detail` 을 붙임 | 빼거나 "1분에 10번"으로 | 현수님 S | `test_rate_limit_message_has_no_english_fragment` |
| R-P1-6 | 이름 속 보이지 않는 서식 문자가 등급을 바꿈 | "블​루커피" → 주의 0.248(원본 검토 권장 0.53). U+200B·U+200C·U+200D·U+2060·U+FEFF·U+00AD 모두 낱말 가운데 넣으면 요부가 '루커피'로 바뀜. 폭 없는 공백만인 이름은 버튼이 켜지고 "후보 없음"(U3) | 웹·메신저에서 복사한 이름도 같은 결과, 보이지 않는 글자만이면 이름 없음 | `ml/src/axes/pair_axes.py` `clean_name` 이 NFKC 만(이 문자들은 NFKC 에서 남음) → X1 `normalize_name` 이 낱말 경계로 봄 | `clean_name` 에서 서식 문자(Cf) 제거 + 계약 §1 `name` 처리에 한 줄, 화면 입력도 같은 정리 | 다빈 S(계약·화면은 현수님) | `test_invisible_format_characters_do_not_change_the_judgment` |

### P2 — 다듬기

| ID | 항목 | 재현 → 실제 | 원인 위치 | 고치는 방향 | 담당·크기 |
|---|---|---|---|---|---|
| R-P2-1 | 이미지 중계가 잘못된 퍼센트 인코딩에 500 | `/api/images/%C0%AE%C0%AE/.env` → 500 text/plain(노출 없음) | `frontend/app/api/images/[...path]/route.ts`(경로 디코딩 예외) | 잡아서 400 | 현수님 S |
| R-P2-2 | 한도 키 — 중계 뒤는 사이트 전체 공용, 프록시 헤더 신뢰 | 중계 경유: 한 사람이 10건 쓰면 다른 사람도 429. 백엔드 직접: X-Forwarded-For 위조로 우회 | `backend/src/core/ratelimit.py`(`get_remote_address`), 중계가 클라이언트 IP 를 안 넘김, nginx 는 `X-MarkLens-Client-IP` 를 믿음 | 설계대로(compose 주석·보안 가이드 8항) — 사용자별 한도는 nginx + TLS 앞단에만 있으니 nginx 없이 띄우는 시연에서는 한도를 올려 두고, 보안 가이드에 "nginx 필수" 확인 항목 추가 | 현수님 S |
| R-P2-3 | 중계 POST 에 Origin 확인 없음 | 다른 Origin·Referer 없음 + 유효 토큰 → 200 | `frontend/app/api/search/v2/route.ts` | 1회용 Turnstile 토큰 + 사용자 정의 헤더가 CSRF 를 막지만, `Origin`/`Sec-Fetch-Site` 확인을 더해 이중으로 | 현수님 S |
| R-P2-4 | 백엔드 API 문서가 운영에서도 켜짐 | 8000 `/docs`·`/redoc`·`/openapi.json` 200 | `backend/src/main.py` `FastAPI(...)` | 운영(`MARKLENS_ENVIRONMENT=production`)에서 `docs_url`·`redoc_url`·`openapi_url` 을 None. 백엔드는 내부망이라 바깥 노출은 없음 | 현수님 S |
| R-P2-5 | CSP `script-src 'unsafe-inline'` | 중계 응답 헤더 | `frontend/next.config.ts` | Next 인라인 스크립트용 nonce 방식 | 현수님 M |
| R-P2-6 | 필드 이름·영어가 섞인 오류 문구 | "image, name, goods_codes 중 하나는 있어야 합니다."(중계·API), "type_override는 문자·도형·결합 중 하나여야 해요.", "image는 한 번만 보낼 수 있어요.", 20000² 폭탄에 "이미지 헤더를 읽을 수 없습니다."(실제는 크기). API 직접: `top_k` 가 pydantic 영어 JSON, 415 가 MIME 목록, 405 "Method Not Allowed", JSON 본문에 "image, name, goods_codes 중…" | `backend/src/api/search.py`·`frontend/app/api/search/v2/route.ts`·`backend/src/core/validation.py` | 사용자 말로("로고·상표 이름·지정상품 중 하나는 넣어 주세요" 등). 화면은 버튼이 막혀 보통 안 보이지만 중계 응답 그대로라 | 현수님 S |
| R-P2-7 | 같은 로고도 여백·크기에 따라 등급 경계에서 바뀜 | 원본 위험 0.634, 절반 0.594(하한 0.5724 바로 위), 흰 여백 30% 검토 권장 0.551 — 1위는 같음 | CLIP 임베딩이 여백에 민감(`ml/src/preprocess.py`) | 균일한 여백 자동 자르기(전처리 계약 변경 — 색인과 같이), 또는 결과에 "여백을 잘라 다시" 안내 | 다빈 M |
| R-P2-8 | 음절마다 띄운 이름 | "블 루 커 피" 주의 0.269(원본 검토 권장 0.53) | 토큰이 한 음절씩 갈림(식별력·X1) | 한 음절 토큰만 이어질 때 붙여서도 비교 — 드문 입력이라 낮음 | 다빈 S |
| R-P2-9 | 모양이 같은 키릴 글자 | "STАRBUCKS"(키릴 А) 주의 0.293, 셋이면 1위 RR(원본 위험 0.726) | X1 `normalize_name` 이 라틴·한글 밖 글자를 지워 'st'·'rbucks' | 혼동 문자(유니코드 TR39 confusables)를 라틴으로 바꾸거나 "다른 문자 체계 글자가 섞여 있어요" 안내 | 다빈 M |
| R-P2-10 | 깨진 PNG 를 반쪽으로 검색 | 절반에서 자른 PNG → 브라우저가 위 절반만 그림, 자르기 창 정상 진행, 버튼 켜짐(U11). 서버는 자른 WebP 만 받아 못 잡음(같은 파일을 API 로 보내면 400) | 이미지 고르기·`ImageCropDialog`(`frontend/components/ImageCropDialog.tsx`) | 원본을 먼저 `createImageBitmap`/디코드 검사, 실패면 "파일이 손상됐어요" | 현수님 S |
| R-P2-11 | 동시 다발 때 5초 넘는 응답 | 9.7MB 20건 동시 최대 10.3초, 이미지+이름 30건 동시 최대 8.7초, 긴 이름 4개씩 최대 5.8초. 서버는 안 멈춤 | 검색 동시 실행 상한 2(`SEARCH_MAX_CONCURRENCY`) | 운영 한도(nginx 사용자당 5r/m·사이트 120/min)로 보면 수용. 시연 때 동시 사용 주의, 필요하면 상한·작업자 수 조정 | 현수님 S |
| R-P2-12 | 의존성 취약점(운영 경로 아님·고친 버전 있음) | npm 개발 13(높음 4), pip 6패키지 | `frontend/package-lock.json`·`constraints.txt` | vitest 4.1.12 등 갱신 PR, `certifi`·`opentelemetry-api`·`fsspec`·`msgpack` 을 `constraints.txt` 에 고친 버전으로 | 다빈·현수님 S |
| R-P2-13 | 이미지 중계 응답이 공용 캐시 허용 | `/api/images/*` `Cache-Control: public, max-age=3600` | `frontend/app/api/images/[...path]/route.ts` | 운영은 이미지 비공개가 기본이라 영향 작음 — 공개로 바꿀 때 `private` 로 | 현수님 S |

## 4. 계약 공백(판정하지 않음 — 계약에 정할 것)

| # | 입력 | 지금 동작 | 정할 것 |
|---|---|---|---|
| G-1 | 이름 속 서식 문자(U+200B 등)·제어 문자(NUL·ANSI)·양방향 문자(U+202E) | NFKC 만, 그대로 처리(200) | 지울지(R-P1-6) |
| G-2 | 폭 없는 공백만인 이름 | 200 "후보 없음", 화면 버튼 켜짐 | "없는 이름"(400)으로 볼지 |
| G-3 | 100자 세는 단위 | 정규화 전 코드 포인트 — NFD 40음절이 422 | 정규화 뒤 글자로 셀지 |
| G-4 | 잘못된 UTF-8 바이트 이름 | 200(대체 문자) | 400 으로 거절할지 |
| G-5 | `type_override` 빈 문자열·앞뒤 공백 | 422 | 없는 것으로 볼지 |
| G-6 | 같은 `goods_codes` 필드 2천 개 | API 400 "multipart 폼을 읽을 수 없습니다."(Starlette 필드 1,000 상한) · 중계 200(중복 제거 뒤 1개 전달) | 필드 수 상한과 두 경로 일치 |
| G-7 | 애니메이션 PNG·WebP | 첫 프레임으로 200 | 허용할지·안내할지 |
| G-8 | 이미지 파트에 Content-Type 없음 | API 200 · 중계 415 | 두 경로 일치 |
| G-9 | multipart 가 아닌 본문 | urlencoded 200(둘 다), JSON·text/plain 400(API 문구는 "image, name, goods_codes 중…") | multipart 만 받을지(415) |
| G-10 | 오류 응답에 실을 내부 원인 | §5-6 이 `ModelNotReadyError` 원인 목록을 `detail` 로 | 고정 문구로(R-P1-3) |
| G-11 | `/health` 가 알릴 범위 | 엔진(색인·CLIP)만 | 검색 가능 여부(계수 JSON)까지(R-P1-2) |
| G-12 | 이름 + 이미지에서 이미지 단독 판단 | 자동 유형은 이름 있는 판단만(§2-4 5·6항) | R-P0-1 |
| G-13 | 질의에 요부가 없을 때(낱말이 모두 약함) | 약한 토큰열 일치로 호칭 1.0 가능 | 결과·안내(R-P0-2) |

## 5. 실행 확인 못 한 것·한계

- nginx(사용자별 한도·본문 상한·`X-MarkLens-Client-IP` 처리·바인드)와 Docker 이미지 안의 동작은 설정 파일만 읽었다(이 Mac 에 nginx·Docker 없음). 이미지 내용은 CI backend-image 잡이 본다.
- Turnstile 은 `siteverify` 응답을 모의했고(검증 코드는 운영 그대로), KIPRIS 는 모의 응답으로 요청 URL 만 봤다.
- 화면은 데스크톱 1440 만 봤다(휴대폰·발표 화면은 UI 평가 2026-11-22).
- 저장소 공개 여부는 외부 조회를 하지 않아 확인하지 않았다. 보안 P0 가 없어 보관 폴더에만 따로 둘 재현은 없다.
- 결과 점검(2-5)은 DB 1,383건 기준이다. R-P0-1·R-P0-2 가 얼마나 자주 나오는지(같은 로고 + 다른 이름, 약한 토큰열 일치)는 표본으로 재지 않았다.

## 6. 다시 돌리는 법(고친 뒤·손그림 입력을 더한 뒤)

모두 로컬 서버에만 요청한다(KIPRIS 0, 외부는 모의). 결과는 `~/marklens-archive/robustness-YYYYMMDD/` 에 쌓인다(`--out` 으로 바꿈).

```bash
bash scripts/robustness/servers.sh start --default-limits   # 백엔드 8000(한도 상향)·8001(기본 한도) + next build → 3000
bash scripts/robustness/servers.sh start-extra              # 3001 → 8001(429 화면), 3002 → 빈 포트(백엔드 꺼짐)
ml/venv/bin/python scripts/robustness/make_images.py         # 시험 이미지 43장(DB 로고 사본은 보관 폴더에만)
ml/venv/bin/python scripts/robustness/probe_api.py           # 입력 경계 97가지 × API·중계
node scripts/robustness/probe_ui.mjs                         # 화면 U1–U21 캡처(--only U7,U18 로 일부만)
ml/venv/bin/python scripts/robustness/probe_results.py       # 결과가 이상한 입력(기대 먼저, 2분)
ml/venv/bin/python scripts/robustness/probe_security.py      # 한도·경로·출처·노출·헤더·보관(한도 창을 기다림)
ml/venv/bin/python scripts/robustness/probe_load.py          # 동시 다발 + 긴 이름 2,000건(30분; --skip-churn·--repeat-big N)
ml/venv/bin/python scripts/robustness/probe_startup.py       # 모델 JSON·색인 누락·손상(포트 8002, 2분)
ml/venv/bin/python scripts/robustness/scan_secrets.py        # 키·.env 흔적(값은 안 찍음)
bash scripts/robustness/servers.sh stop
cd frontend && npm audit --omit=dev && cd .. && ml/venv/bin/pip-audit --timeout 60   # 레지스트리 조회(외부)
```

새 시험만: `MARKLENS_FAKE_ML=1 ml/venv/bin/python -m pytest -q backend/tests/test_robustness_review.py ml/tests/test_robustness_results.py`,
`cd frontend && npx vitest run lib/robustness.test.ts`.
