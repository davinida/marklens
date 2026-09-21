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

## 호칭(발음) 유사도 검색 (X1 최소 통합, 2026-09-17)

입력 상표명과 **로컬 DB(현재 게시 세대)** 상표명의 X1 호칭(발음) 유사도를 계산해 상위
후보를 돌려줍니다. KIPRIS를 호출하지 않으며 키·네트워크 없이 동작합니다. 결과는 호칭 한
축만 반영한 참고 정보이고 외관·관념·지정상품·법적 판단은 포함하지 않습니다.

### 브라우저 API

`POST /api/phonetic-search`

```json
{
  "name": "스타박스",
  "turnstileToken": "browser-token",
  "top_k": 5
}
```

`top_k`는 선택(1..20)입니다. BFF는 Turnstile을 검증한 뒤 토큰을 제거하고 내부
`POST /phonetic-search`로 전달합니다. Turnstile 토큰은 1회용이므로 프런트는 `/api/name-check`
와 같은 토큰을 재사용하지 않고 위젯을 리셋해 받은 새 토큰으로 이 요청을 보냅니다.

### 내부 API

`POST /phonetic-search`

```json
{ "name": "스타박스", "top_k": 5 }
```

`name`은 공백 제거 후 1..100자(공백만이면 422), `top_k` 미지정 시 서버 기본값
`MARKLENS_PHONETIC_TOP_K_DEFAULT`(기본 5)를 씁니다. 후보 하한은
`MARKLENS_PHONETIC_MIN_SIMILARITY`(기본 0.5), 한도는 `MARKLENS_PHONETIC_RATELIMIT`
(기본 30/minute)이며 `/name-check`와 같은 API 키·요청 ID 규칙을 따릅니다.

응답:

```json
{
  "query": { "name": "스타박스", "has_pronunciation": true, "candidates": ["스타박스"] },
  "matches": [
    {
      "rank": 1,
      "similarity": 0.9636,
      "출원번호": "4020210000001",
      "상표한글명": "스타벅스",
      "이미지URL": "/images/4020210000001.png",
      "출원인": "스타벅스 코포레이션",
      "류": [43]
    }
  ],
  "searched_count": 947,
  "excluded_no_pronunciation": 153,
  "dataset_info": {},
  "params": { "top_k": 5, "min_similarity": 0.5 },
  "axis": "X1",
  "note": "호칭(발음) 유사도만 반영한 참고 정보"
}
```

- `query.candidates`는 입력의 발음 후보(설명용)입니다. 입력에 호칭이 없으면(기호만 등)
  `has_pronunciation=false`, `matches=[]`로 200을 반환합니다.
- `matches`는 `similarity` 내림차순(동점은 출원번호 순)이며 `min_similarity` 미만은
  제외됩니다. `searched_count`는 발음 후보가 있어 비교한 DB 레코드 수,
  `excluded_no_pronunciation`은 상표명이 없거나 호칭이 없어 제외한 수입니다.
- `이미지URL`은 현재 인덱스에 있는 이미지만 연결하며 `/search`와 같은 `/images` 규칙을
  따릅니다(브라우저는 `/api/images/...`로 접근).
- 발음 후보 캐시는 서버 기동 시 만들고, 인덱스가 재게시되면 다음 요청에서 다시 만듭니다.

## 상품 검색·류 목록 (상품↔유사군 변환표, 프론트-6 지정상품 입력용, 2026-09-21)

지식재산처 고시상품명칭 13판(2026)을 변환한 로컬 변환표(`shared/goods_map/goods_map.json.gz`,
91,591건, 제35류 병합 항목 38,433건에 원 명칭 `aliases` 230,598개)에서 상품명을 찾아 유사군
코드를 돌려줍니다. KIPRIS를 호출하지 않는 읽기 전용 조회입니다. `similarity_codes`는 X4 상품
견련성(자카드) 계산의 입력이며 법적 유사 판단이 아닙니다.

### 브라우저 API

`GET /api/goods/search?q=화장품 소매업&limit=20&nice_class=35`

| 파라미터 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `q` | string 1..50자 | 예 | 앞뒤 공백 제거 후 1자 이상(공백만이면 422). `name`과 원 명칭 `aliases`에 부분 일치 |
| `limit` | 1..50 | 아니오 | 기본 20 |
| `nice_class` | 1..45 | 아니오 | 류 번호로 좁히기 |

`GET /api/goods/classes` — NICE 45개 류의 명칭과 변환표 항목 수(정적 데이터, 성공 응답은 1시간 캐시).

두 라우트는 Turnstile 토큰을 요구하지 않습니다. 읽기 전용 로컬 조회(KIPRIS 쿼터·CPU 모델
미사용)이고 개인정보·질의 저장이 없으며, 자동완성이 키 입력마다 호출하므로 1회용 토큰과 맞지
않기 때문입니다(`/api/images`·`/api/health`와 같은 부류). 남용 방지는 백엔드 IP 한도
`MARKLENS_GOODS_RATELIMIT`(기본 60/minute)와 gateway 한도가 맡습니다. BFF는 파라미터를 검증한
뒤 서버 키를 붙여 내부 `GET /goods/search`, `GET /goods/classes`로 전달합니다.

### 내부 API

`GET /goods/search?q=화장품 소매업&limit=3`

```json
{
  "query": "화장품 소매업",
  "matches": [
    {
      "name": "화장품 판매업(도소매·중개·대행)",
      "nice_class": 35,
      "similarity_codes": ["S2012"],
      "matched_alias": "화장품 소매업"
    }
  ],
  "total": 61,
  "source": "고시상품명칭 13판(2026)"
}
```

- 순위: 정확 일치 > 접두 > 부분. 같은 순위에서는 `name` 일치가 alias 일치보다 앞이고 `name`이
  짧은 순 → 가나다순. NFKC·대소문자·연속 공백을 정규화해 비교합니다.
- `matched_alias`는 `name`이 아니라 제35류 병합 항목의 원 명칭(alias)으로 잡혔을 때만 값이
  있고 그 외 `null`입니다. `total`은 `limit`과 무관한 전체 일치 건수입니다.
- 일치가 없으면 `matches=[]`, `total=0`으로 200을 반환합니다. 실측(2026-09-21, 1,100건 서버):
  "화장품 소매업" 61건 12ms, "커피" 214건 6ms, 1글자 광범위 질의("업" 53,991건) 46ms.

`GET /goods/classes`

```json
{
  "classes": [{ "nice_class": 3, "title": "화장품·세제", "count": 1331 }],
  "total_entries": 91591,
  "source": "고시상품명칭 13판(2026)"
}
```

45개 류 전부를 번호순으로 돌려주며 `title`은 서버 상수(NICE 류 요약 명칭)입니다.

변환표는 서버 기동 시 적재합니다(`MARKLENS_GOODS_MAP_PATH`, 기본 `shared/goods_map/goods_map.json.gz`
→ `.json`). 파일이 없어도 서버는 기동하며 이 두 엔드포인트만 503과 이유를 반환합니다(`/name-check`가
KIPRIS 키 없이 503을 내는 것과 같은 방식). 다른 엔드포인트에는 영향이 없습니다.

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
| 422 | `top_k` 또는 스키마 검증 실패, `/phonetic-search`의 공백 상표명, `/goods/search`의 공백·범위 밖 파라미터 |
| 429 | gateway/backend 요청 한도 또는 KIPRIS 월 예산 한도 |
| 502 | KIPRIS/내부 upstream 응답 계약 실패 |
| 503 | Turnstile·엔진·KIPRIS 설정·인덱스가 준비되지 않음, 상품↔유사군 변환표 파일 없음(`/goods/*`) |
| 504 | Turnstile 또는 내부 upstream 응답 시간 초과 |

서버 오류 응답에는 내부 예외, 요청 URL, KIPRIS 키 또는 검색어를 포함하지 않습니다.
gateway가 `X-Request-ID`를 생성하고 BFF와 FastAPI에 전달합니다. BFF 직접 실행 시에는
BFF가 새 ID를 생성합니다. 응답과 운영 로그는 같은 ID로 추적합니다.

## 상태 확인

- 브라우저·외부 모니터: `GET /api/health`
- 내부 FastAPI: `GET /health`

외부 응답은 현재 artifact generation과 준비 상태 확인에 필요한 필드만 전달합니다.
