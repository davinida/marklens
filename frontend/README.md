# MarkLens frontend

Next.js 16 기반 UI와 same-origin BFF입니다. 브라우저는 `/api/search`,
`/api/name-check`, `/api/images/*`, `/api/health`만 호출하며 백엔드 URL과 API key는
서버에서만 읽습니다.

## Local development

Node.js 20.19 이상이 필요합니다.

```bash
npm ci
npm run dev
```

`.env.example`을 참고해 로컬 환경 변수를 설정하세요. 실제 Cloudflare Turnstile을
쓰지 않는 로컬 개발에서는 아래 한 값만 설정하면 됩니다.

```dotenv
MARKLENS_TURNSTILE_DEV_BYPASS=1
```

위젯 설정 라우트(`/api/turnstile-config`)와 서버 검증이 모두 이 플래그 하나를
읽습니다. 이 bypass는 `NODE_ENV=production`에서는 작동하지 않습니다.

production에는 반드시 `MARKLENS_TURNSTILE_SECRET_KEY`,
`MARKLENS_TURNSTILE_SITE_KEY`, `MARKLENS_TURNSTILE_EXPECTED_HOSTNAMES`,
`MARKLENS_BACKEND_URL`, `MARKLENS_BACKEND_API_KEY`를 설정해야 합니다. 사이트 키는
`NEXT_PUBLIC_TURNSTILE_SITE_KEY`로도 폴백되지만, `NEXT_PUBLIC_*`은 빌드 시점에
인라인되므로 standalone 빌드에서는 그 경로로 키를 교체하려면 재빌드가 필요합니다.
재빌드 없이 교체하려면 `MARKLENS_TURNSTILE_SITE_KEY`를 쓰세요. 백엔드 API key에는
`NEXT_PUBLIC_` 접두사를 붙이지 마세요.

## Verification

```bash
npm run lint
npm run typecheck
npm test
npm run build
npm audit
```

`next.config.ts`는 standalone 서버 출력을 생성합니다. 런타임 컨테이너에는 `.next/standalone`,
`.next/static`, `public`과 위의 server-only 환경 변수가 필요합니다.

## Result UI and contracts

- 이름 확인 응답은 `candidates`를 정식 후보 배열로 사용하며, 이전 응답의 `examples`도
  읽기 호환합니다. `exact_registered_count`와 `exact_title_count`는 서로 다른 지표로
  보존해 각각 `동일 명칭 등록`, `동일 명칭 전체`로 표시합니다.
- 후보 이미지는 백엔드가 허용한 same-origin `local_image_url`만 렌더링합니다. 이미지가
  없으면 출원번호로 KIPRIS 공식 검색 결과를 새 탭에서 확인할 수 있습니다.
- 이름 입력이 바뀌면 이전 이름 확인 결과를 폐기합니다. 확인 후 이미지 검색을 실행하면
  동일 결과를 최종 대시보드의 `명칭 검색 근거`에 유지합니다.
- 시각 유사도는 OpenCLIP 특징 벡터의 코사인 유사도이며 확률이 아닙니다. 대시보드는
  최고 점수, 1·2위 격차, 1위·후보 평균 격차와 후보 분포만 시각화합니다. 호칭·관념과
  상품 견련성처럼 현재 모델이 계산하지 않는 축에는 점수를 만들지 않습니다.
