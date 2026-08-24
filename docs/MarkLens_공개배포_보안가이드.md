# MarkLens 공개 배포·보안 가이드

기준일: 2026-08-14

이 문서는 **배포 준비 템플릿**의 운영 계약입니다. 현재 작업에서는 실제 클라우드,
도메인, TLS 인증서 또는 외부 계정을 만들지 않습니다.

## 지원 토폴로지

```text
Internet
  -> trusted TLS edge/Cloudflare or load balancer
       (strip and set X-MarkLens-Client-IP from the verified source IP)
  -> Nginx gateway :8080
  -> Next.js :3000
  -> private FastAPI :8000
  -> PostgreSQL :5432 + read-only data/model volumes
```

FastAPI와 PostgreSQL에는 host port를 열지 않습니다. 브라우저는 Next BFF만 호출하고
FastAPI 키는 Next 서버 환경에만 둡니다. Compose는 FastAPI worker를 1개로 고정합니다.

현재 slowapi, 명칭 TTL 캐시와 KIPRIS 월 예산 카운터는 단일 프로세스 계약입니다.
Redis 또는 PostgreSQL 기반 공유 카운터를 도입하기 전에는 backend 복제본을 늘리지
마세요. 수집기는 같은 KIPRIS 카운터를 사용하므로 운영 API를 중지한 maintenance
window에서만 실행합니다.

## 배포 전 수동 게이트

아래 항목이 하나라도 미완료이면 공개하지 않습니다.

1. KIPRIS 기존 키를 포털에서 회전하고 새 키를 비밀 저장소에 등록합니다.
2. KIPRIS 이미지·메타데이터의 공개 재배포 범위를 서면으로 확인합니다.
3. 실제 Turnstile site/secret key와 production hostname을 발급합니다.
4. 32자 이상의 무작위 `MARKLENS_API_KEY`와 강한 DB 암호를 생성합니다.
5. 현재 authoritative metadata 전체를 재빌드해 manifest를 생성합니다.
6. PostgreSQL migration과 데이터 적재를 완료합니다.
7. 외부 TLS 종료, 백업, 로그 보존·삭제 정책과 장애 연락처를 정합니다.
8. TLS edge가 외부의 `X-MarkLens-Client-IP`를 제거하고 검증한 원격 IP로 다시
   설정하며, gateway에는 그 edge만 접속할 수 있도록 방화벽을 제한합니다.

KIPRIS Plus의 공개 저작권 정책은 콘텐츠 이용과 출처 표시 조건을 별도로 두고
있습니다. 확인 전에는 `MARKLENS_PUBLIC_RESULT_IMAGES=false`를 유지합니다.

## 인덱스 준비

기존 legacy 인덱스는 개발 모드에서만 경고와 함께 읽습니다. production은
`kipris_manifest.json`이 필수입니다.

```powershell
ml\venv\Scripts\python.exe ml\scripts\build_index.py `
  --image-dir ml\data\images `
  --output-dir ml\data\index `
  --index-name kipris `
  --authoritative-metadata ml\data\kipris_metadata.json
```

빌더는 모델·가중치·차원·metric·전처리 계약, 입력과 artifact SHA-256, Git과
패키지 버전을 기록합니다. 모든 authoritative 이미지가 성공한 경우에만 임시 세대를
검증하고 manifest를 마지막으로 게시합니다.

production은 `git.dirty=false`인 manifest만 허용합니다. 기능 변경을 커밋한 뒤 clean
tree에서 승인 세대를 다시 빌드하고 `/api/health`의 generation ID를 기록합니다.

`global-letterbox-dual-bg-v1`은 평가 후보일 뿐 현재 운영 기본값이 아닙니다. 기존
인덱스와 동일한 legacy 전처리를 유지하고, 전체 평가와 승인 없이 옵션을 바꾸지 않습니다.

## 환경 설정

```powershell
Copy-Item .env.production.example .env.production
```

`.env.production`의 빈 값을 모두 채웁니다. 이 파일은 `.gitignore` 대상입니다.

필수 항목:

- `PUBLIC_ORIGIN`: 외부 HTTPS origin
- `MARKLENS_BIND_ADDRESS`: 기본 `127.0.0.1`; 신뢰 edge와 방화벽이 있을 때만 변경
- `POSTGRES_PASSWORD`: URL-safe 무작위 값 권장 (`openssl rand -hex 32`)
- `MARKLENS_API_KEY`: 32자 이상, 브라우저 비노출
- `NEXT_PUBLIC_TURNSTILE_SITE_KEY`: 공개 가능한 site key
- `MARKLENS_TURNSTILE_SECRET_KEY`: 서버 전용
- `MARKLENS_TURNSTILE_EXPECTED_HOSTNAMES`: 콤마 구분 hostname
- `KIPRIS_ACCESS_KEY`: 회전 완료한 새 키

production backend는 API 키나 `DATABASE_URL`이 없으면 fail-closed로 기동하지
않습니다. KIPRIS endpoint는 HTTPS와 `plus.kipris.or.kr`만 허용하고 redirect를
따르지 않습니다. 호출 카운터는 read-only `/data`와 분리된 `/state` named volume에
원자적으로 저장됩니다.

## 구성 검증과 기동

```powershell
docker compose --env-file .env.production `
  -f compose.production.yml config

docker compose --env-file .env.production `
  -f compose.production.yml build

docker compose --env-file .env.production `
  -f compose.production.yml run --rm backend `
  python -m backend.scripts.migrate_json_to_db

docker compose --env-file .env.production `
  -f compose.production.yml up -d
```

첫 backend 기동은 OpenCLIP 가중치 캐시 때문에 오래 걸릴 수 있습니다. 모델 캐시는
named volume에 보존됩니다. 공급망 정책상 런타임 다운로드를 금지한다면 승인된
가중치를 별도 read-only volume으로 사전 배치해야 합니다.

Nginx 템플릿은 HTTP 8080만 제공하고 host loopback에 바인딩됩니다. 실제 공개 시
Cloudflare, load balancer 또는 별도 ingress에서 TLS를 종료하고, gateway port를
인터넷에 직접 노출하지 않습니다. 다른 host의 edge가 직접 연결해야 한다면 bind
주소 변경과 동시에 security group을 그 edge 주소로 제한합니다.

## 요청 보호

- Gateway: 검색 `5/minute` burst 2, 명칭 확인 `2/minute` burst 1, 신뢰 edge가
  전달한 사용자 IP 기준. 초과 응답은 JSON `429`와 `Retry-After`
- Gateway: 검색 본문 11 MiB, 명칭 본문 32 KiB, 연결·본문·upstream timeout
- BFF: Turnstile server-side Siteverify, action `marklens`, hostname 일치
- Backend: 검색 동시 실행 2개, 내부 API 키, BFF 전체에 적용되는 aggregate ceiling
- Upload: `MAX+1` 바이트 읽기, 헤더 치수·총 픽셀 선검사, decompression bomb 차단
- Images: path segment 검증, 현재 인덱스 키 allowlist, 내부 API 키

Turnstile 토큰은 1회용이며 짧은 수명을 가집니다. 검증 실패 후 같은 토큰을 재사용하지
말고 위젯을 reset합니다. 개발 bypass는 `NODE_ENV=production`에서 작동하지 않습니다.

## 로그와 비밀

- access key와 상표명은 KIPRIS query parameter로 전송되므로 전체 upstream URL을
  로그에 남기지 않습니다.
- `httpx` URL 로그를 억제하고 외부 예외를 안전한 도메인 오류로 바꿉니다.
- `.env`, `.env.production`, counter, 원본 XML과 이미지에 접근 권한을 제한합니다.
- 응답에는 내부 예외 문자열이나 파일시스템 경로를 넣지 않습니다.
- gateway가 생성한 `X-Request-ID`를 BFF와 FastAPI까지 전달하고 검색어 본문은
  기록하지 않습니다.

키 노출이 의심되면 KIPRIS 키, FastAPI 키, Turnstile secret, DB 암호 순으로 회전하고
해당 시점 이후의 access log와 월 호출 카운터를 확인합니다.

## 데이터베이스와 백업

- 배포 전 migration의 멱등성 테스트를 통과시킵니다.
- PostgreSQL volume과 승인된 index generation을 함께 백업합니다.
- DB와 index의 generation이 어긋난 상태로 부분 복구하지 않습니다.
- 수집 중에는 DB 쓰기 전에 index dirty marker를 만들고, 전체 rebuild와 manifest
  게시가 성공한 뒤에만 제거합니다.

## KIPRIS smoke

코드 보강과 키 회전 뒤에만 수행합니다. 허용된 실호출은 최대 3회입니다.

1. 존재 가능성이 높은 명칭 1회
2. 결과가 적은 명칭 1회
3. 필요할 때만 캐시 재사용 확인 1회

`complete`, `scanned_count`, `total_found`, `checked_at`, `source`를 기록합니다.
`complete=false` 또는 upstream 계약 오류를 `0건`으로 보고하지 않습니다.

## Release 체크

```powershell
$env:MARKLENS_FAKE_ML = "1"
ml\venv\Scripts\python.exe -m pytest -v
ml\venv\Scripts\python.exe -m ruff check backend ml
ml\venv\Scripts\python.exe -m pip_audit --local --progress-spinner off

Set-Location frontend
npm ci
npm audit --omit=dev --audit-level=high
npm run typecheck
npm run lint
npm test
npm run test:e2e
npm run build
```

브라우저에서는 desktop/mobile 업로드, 크롭, 취소, 재검색, 명칭 incomplete 상태,
Turnstile 재발급, 이미지 비공개 상태를 확인합니다. 배포 후 외부
`GET /api/health`의 `artifact_generation_id`가 승인된 manifest와 같은지 확인합니다.
내부 FastAPI 점검은 다음처럼 컨테이너 안에서 수행합니다.

```powershell
docker compose --env-file .env.production -f compose.production.yml exec backend `
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
```

## 공식 참고

- KIPRIS Plus 저작권 정책: <https://plus.kipris.or.kr/portal/main/contents.do?menuNo=200032>
- KIPRIS Plus FAQ: <https://plus.kipris.or.kr/portal/bbs/Faq_info.do?buttonIndex=&pageIndex=3>
- Turnstile 서버 검증: <https://developers.cloudflare.com/turnstile/get-started/server-side-validation/>
