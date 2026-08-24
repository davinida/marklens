# MarkLens API 계약 v1

기준일: 2026-08-14

## 경계

브라우저의 정식 API는 Next.js의 same-origin `/api/*`입니다. FastAPI는 내부
서비스이며 production에서는 32자 이상의 `X-API-Key`가 필요합니다. 이 키를
`NEXT_PUBLIC_*` 환경변수나 브라우저 코드에 넣지 않습니다.

## 이미지 검색

### 브라우저 API

`POST /api/search?top_k=1..20`

헤더:

| 헤더 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `X-Turnstile-Token` | string | 예 | 5분 내 발급된 1회용 토큰 |

`multipart/form-data` 본문:

| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `file` | PNG/JPEG/WebP | 예 | 최대 10 MiB, 32..4096px |

BFF는 Turnstile의 action·hostname을 서버에서 확인한 뒤 토큰을 제거하고 내부
`POST /search`로 전달합니다.

### 응답 핵심 필드

```json
{
  "api_version": "2026-08-14",
  "research_beta": true,
  "grade": {
    "status_code": "POSSIBLE_MATCH",
    "status_name": "가까울 수 있는 시각 후보",
    "uncertain": true,
    "uncertainty_reasons": ["MULTIPLE_CLOSE_CANDIDATES"],
    "scored_candidate_count": 20,
    "threshold_version": "visual-v2-uncalibrated",
    "scope": "visual_similarity_only",
    "calibrated": false,
    "legal_conclusion": false,
    "grade_code": "REVIEW",
    "grade_name": "검토 권장",
    "message": "...",
    "top1_similarity": 0.71,
    "separability_a": 0.02,
    "separability_b": 0.18,
    "warnings": []
  },
  "matches": [],
  "dataset_info": {},
  "index_size": 100,
  "top_k_requested": 5,
  "top_k_returned": 5,
  "scoring_k": 20
}
```

`status_code`가 정식 계약입니다.

| 코드 | 의미 |
|---|---|
| `STRONG_MATCH` | 현재 표본에서 매우 가까운 시각 후보 |
| `POSSIBLE_MATCH` | 현재 표본에서 가까울 수 있는 시각 후보 |
| `WEAK_MATCH` | 현재 표본에서 약한 시각 후보 |
| `NO_CLOSE_MATCH` | 현재 표본에서 가까운 시각 후보 미확인 |

상태는 top-1 유사도에 대해 단조적입니다. 후보 간 작은 격차는 상태를 낮추지 않고
`uncertain`과 `uncertainty_reasons`로만 나타냅니다. 내부 `scoring_k`는 화면에
표시하는 `top_k`와 독립적이므로 `top_k=1`과 `top_k=5`의 상태가 같습니다.

`grade_code`, `grade_name`은 v1 호환용 deprecated 필드입니다. `SAFE`는 더 이상
반환하지 않습니다. v2 전환 전까지 유지하고, 모든 정식 클라이언트가
`status_code`로 이동한 다음 제거합니다.

`matches[].이미지URL`은 `null`일 수 있습니다. production 기본값은 KIPRIS 이미지
재배포 권리를 확인할 때까지 이미지 비공개입니다.

## 상표명 확인

### 브라우저 API

`POST /api/name-check`

```json
{
  "name": "확인할 상표명",
  "turnstileToken": "browser-token"
}
```

### 내부 API

`POST /name-check`

```json
{ "name": "확인할 상표명" }
```

응답:

```json
{
  "query": "확인할 상표명",
  "total_found": 12,
  "scanned_count": 12,
  "registered_count": 5,
  "exact_registered_count": 1,
  "exact_title_count": 2,
  "status_counts": {
    "등록": 5,
    "소멸": 4,
    "거절": 3
  },
  "candidates": [
    {
      "application_number": "4020210000001",
      "registration_number": "4012345670000",
      "application_date": "20210105",
      "registration_date": "20230519",
      "title": "확인할 상표명",
      "status": "등록",
      "mark_type": "도형복합",
      "applicant": "예시 출원인",
      "right_holder": null,
      "nice_classes": ["29", "43"],
      "vienna_codes": [],
      "similarity_codes": ["G0502"],
      "exact_title_match": true,
      "is_registered": true,
      "local_image_url": "/images/4020210000001.png"
    }
  ],
  "candidates_returned": 12,
  "candidates_truncated": false,
  "complete": true,
  "checked_at": "2026-08-14T12:34:56Z",
  "source": "KIPRIS Plus trademarkNameMatchSearchInfo",
  "cached": false,
  "message": "동일 명칭의 선행 등록상표 1건이 존재합니다."
}
```

`candidates`는 KIPRIS에서 이번 요청으로 확인한 항목의 표시용 allowlist입니다.
정확히 일치하면서 등록 상태인 후보를 먼저 반환하고, 정확 일치인 다른 상태,
등록 상태의 포함 명칭, 나머지 순으로 정렬합니다. 후보 상한은 서버 설정
`KIPRIS_NAME_CANDIDATE_LIMIT`으로 제한되며 `candidates_truncated=true`이면 일부만
표시된 것입니다.

`local_image_url`은 후보 출원번호가 현재 검증된 로컬 이미지 인덱스와 일치하고
이미지 공개 설정이 켜진 경우에만 존재합니다. KIPRIS의 일회성 `fileToss.jsp` URL은
응답에 노출하지 않으며, 후보 수만큼 서지 API를 자동 추가 호출하지 않습니다.
캐시는 앞뒤 공백을 제거한 원문 질의가 정확히 같은 경우에만 재사용합니다. KIPRIS가
대소문자·전각 표현을 같은 검색으로 처리한다는 공급자 보장이 없으므로 `BBQ`, `bbq`,
`ＢＢＱ`는 서로 다른 질의로 취급합니다. NFKC·대소문자 정규화는 반환된 후보의
표시용 `exact_title_match`를 계산할 때만 사용하며 KIPRIS 결과 집합을 공유하지 않습니다.

`complete=false`이면 일부 결과만 확인한 것입니다. 이때 `0건`을 부재나 사용 가능
판정으로 해석하면 안 되며 UI도 중립 상태를 표시합니다.

`GET /name-check?name=...`는 한 릴리스 동안만 유지되는 deprecated 호환 경로입니다.
검색어가 URL·프록시 로그에 남을 수 있으므로 신규 호출은 사용하지 않습니다.

## 결과 이미지

브라우저는 응답의 `/api/images/...`만 사용합니다. BFF는 안전한 path segment만
허용하고 내부 `/images/{image_key}`로 전달합니다. FastAPI도 현재 인덱스에 포함된
정확한 키만 제공하며 production에서 API 키로 보호됩니다.

## 오류

| HTTP | 의미 |
|---:|---|
| 400 | 빈 파일, 치수·픽셀·콘텐츠 품질 오류, 잘못된 본문 |
| 401 | 내부 API 키 누락 또는 불일치 |
| 403 | Turnstile 토큰·action·hostname 검증 실패 |
| 413 | 업로드 바이트 상한 초과 |
| 415 | 지원하지 않는 MIME 또는 실제 이미지 형식 |
| 422 | `top_k` 또는 스키마 검증 실패 |
| 429 | gateway/backend 요청 한도 또는 KIPRIS 월 예산 한도 |
| 502 | KIPRIS/내부 upstream 응답 계약 실패 |
| 503 | Turnstile·엔진·KIPRIS 설정·인덱스가 준비되지 않음 |
| 504 | Turnstile 또는 내부 upstream 응답 시간 초과 |

서버 오류 응답에는 내부 예외, 요청 URL, KIPRIS 키 또는 검색어를 포함하지 않습니다.
gateway가 `X-Request-ID`를 생성하고 BFF와 FastAPI에 전달합니다. BFF 직접 실행 시에는
BFF가 새 ID를 생성합니다. 응답과 운영 로그는 같은 ID로 추적합니다.

## 상태 확인

- 브라우저·외부 모니터: `GET /api/health`
- 내부 FastAPI: `GET /health`

외부 응답은 현재 artifact generation과 준비 상태 확인에 필요한 필드만 전달합니다.
