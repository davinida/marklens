# MarkLens API 계약 v2 — 3입력 통합 검색 `POST /search/v2`

- 기준일: 2026-10-24 · 상태: **서비스 연결의 기준 문서 — 엔진 몫(§6 E-1~E-6)은 구현됨(2026-10-24, `feat/engine-multiaxis`:
  `engine.multi_search()` → `SearchV2Result.to_dict()` 가 §2 키 그대로), API·BFF·zod·gateway(2026-10-26, PR #69)·결과 화면 v2(2026-10-27, PR #72)·E2E v2 15건까지 **연결 완료(2026-10-27)** — 실제 모델로 BFF 경유
  시나리오 8종을 §2·§2-4·§2-5 규칙으로 검산**. 백엔드와 프론트는 이 문서의 §3 예시 JSON 과 엔진 결과만으로 스텁과 목업을 만들어 병렬로 구현했다.
- 관련: [API 계약 v1](MarkLens_API계약_v1.md)(경계·Turnstile·오류·한도 — v2 는 이를 그대로 상속), [통합 모델 설계](MarkLens_통합모델_설계.md)
  §3(입력)·§7-2(등급·단독·도형 규칙)·§7-3(v1.3 결측 패턴별 계수·결합 제약), [식별력 설계](MarkLens_식별력_설계.md) §2(요부·약한 토큰·결합 규칙),
  README "다음 단계"(서비스 연결 범위).
- 코드 근거(2026-10-24 현재): 런타임 `ml/src/model/risk_model.py`(`risk_score → RiskResult(prob, grade, contributions, figure_caveat)`),
  계수 `shared/model/risk_model_v1.json`(version `risk_model_v1.3`), 식별력 `ml/src/axes/distinctiveness.py`(`salient_tokens`·
  `pair_generic`·`judge`), 축 함수 X1 `phonetic_similarity`·X2 철자 `orthographic_similarity`·X3 `semantic_similarity`·X4
  `goods_similarity`, 프론트-6 선택 지정상품 `frontend/lib/goods.ts`(`SelectedGood`·`goodsCodeUnion`).
- §3 의 숫자는 위 코드로 **실제 계산한 값**이다(모델 한계도 그대로 드러난다 — §3-2, §5-3).

## 0. 한눈에

| 항목 | 내용 |
|---|---|
| 입력 | `image`(파일) · `name`(상표명) · `goods_codes[]`(유사군 코드) 중 **하나 이상** + 선택 `type_override`(문자/도형/결합) |
| 처리 | 입력별 후보 풀(CLIP·발음·철자·관념·유사군)을 합쳐 → 후보마다 4축 점수(식별력 필터 적용) → 통합 모델 v1.3 `risk_score`(입력의 결측 패턴에 맞는 계수 집합) → 위험도 내림차순 |
| 출력 | `overall`(등급·위험도·주의 문구·유형) · `candidates[]`(축 점수·위험도·등급·근거 축 기여도·규칙·요부·지정상품) · `meta`(모델 버전·등급 정밀도·임계값·소요) |
| 경계 | v1 과 같다 — 브라우저는 same-origin BFF `/api/search/v2` 만, FastAPI 는 내부(`X-API-Key`), Turnstile 1회용 토큰, `X-Request-ID` |
| 한도 | v1 `/search` 와 같은 설정값·같은 버킷(`MARKLENS_SEARCH_RATELIMIT` 기본 10/minute, gateway 사용자별 5회/분) |
| v1 | `POST /search`·`/phonetic-search`·`/semantic-search` 는 최종 발표(2026-12-20)까지 유지, 이후 제거 PR(§5-5) |

결과는 참고 정보이며 법적 판단이 아니다(`legal_conclusion: false`, `research_beta: true` — v1 과 같은 플래그).

## 1. 요청

### 1-1. 브라우저 API

`POST /api/search/v2?top_k=1..20` (기본 5)

헤더:

| 헤더 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `X-Turnstile-Token` | string | 예 | 5분 내 발급된 1회용 토큰(v1 과 같음). 상표명 확인 패널의 토큰과 재사용하지 않는다 |

`multipart/form-data` 본문 — **세 입력 중 하나 이상**:

| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `image` | PNG/JPEG/WebP, 최대 10 MiB, 32..4096px | 셋 중 하나 이상 | v1 `file` 과 같은 검증(413/415/400). 수동 크롭 결과를 그대로 보낸다 |
| `name` | string | 〃 | 상표명. 앞뒤 공백 제거 후 1..100자(공백만이면 없는 것으로 본다). NFKC·대소문자 정규화는 서버가 한다 |
| `goods_codes` | string, **반복 필드**(`goods_codes=G0502&goods_codes=S120602`) 또는 쉼표로 이은 1개 | 〃 | 유사군 코드 `^[GS][0-9]{4,6}$`, 대소문자 무시, 중복 제거, 최대 60개(프론트-6 선택 20개의 유사군 합집합 `goodsCodeUnion`) |
| `type_override` | `문자` \| `도형` \| `결합` | 아니오 | 사용자가 결과 화면에서 유형을 고쳐 다시 요청할 때. 있으면 `query_type.source = "user"` |

BFF 는 v1 `/api/search` 와 같은 순서로 처리한다: `content-length` 상한(10 MiB + 1 MiB) → `top_k` 검증(422) → Turnstile
검증(403/503/504) → 폼 파싱(400) → `image` 크기·MIME(413/415) → `name`·`goods_codes`·`type_override` 형식(422) → 세 입력이
모두 비면 400 → 토큰을 떼고 내부 `POST /search/v2?top_k=`로 **같은 필드 이름**으로 전달 → 응답 본문·상태를 그대로 돌려준다
(`safeResponseHeaders`). 이미지 URL 은 응답에 `/api/images/...` 로 들어 있으므로 BFF 가 바꾸지 않는다.

### 1-2. 내부 API

`POST /search/v2?top_k=1..20` — 필드·검증은 1-1 과 같다. 추가 검증: `image` 는 v1 과 같은 디코딩·치수 검사, `goods_codes` 는
정규식·개수, `type_override` 는 열거값. 세 입력이 모두 없으면 **400** `{"detail": "image, name, goods_codes 중 하나는 있어야
합니다."}`(§5-1). 한도는 `MARKLENS_SEARCH_RATELIMIT`(v1 `/search` 와 같은 값·같은 버킷 — 한 IP 가 v1+v2 합쳐 10/minute).

### 1-3. 입력 조합 → 계산되는 축·후보 풀·유형 출처

| 입력 | 계산되는 축 | 후보 풀(합집합, 출원번호로 중복 제거) | `query_type.source` |
|---|---|---|---|
| 이미지만 | `x2_img` | CLIP 코사인 상위 20(v1 `scoring_k`) | `ocr`(도형계: 글자 영역 ≥ 0.05 면 결합-도형요부, 읽은 글자는 `suggested_name`; 실패 시 `fallback` → 도형) |
| 이름만 | `x1`·`x2_text`·`x3`(게이트) | 발음 상위 20 ∪ 철자 상위 20 ∪ 관념 상위 5(하한 0.55) | `fallback` → 문자 |
| 이름 + 지정상품 | 위 + `x4` | 위 ∪ 유사군이 겹치는 DB 상표 상위 20(자카드 순) | `fallback` → 문자 |
| 이미지 + 이름(+ 지정상품) | 전부 | 위 전부 | `ocr`(fig_ratio 로 문자/결합-문자요부 — 이름이 있으면 항상 문자계; 실패 시 `fallback` → 문자) |
| 지정상품만 | `x4` | 유사군이 겹치는 DB 상표 상위 20 | `fallback` → 문자 (caveat `GOODS_ONLY`) |

후보 풀의 크기는 `meta.pool` 로 돌려준다. 풀을 합친 뒤 후보마다 축을 계산하고(§2-2 `axes`), `risk_score` 로 위험도를 낸 다음
**위험도 내림차순**(동점은 `x2_img` 내림차순 → 출원번호 오름차순 — 이미지만 넣으면 p 가 모두 같아 시각 유사가 순서를 정한다)으로
정렬해 `top_k` 개를 돌려준다. 정렬 기준은 CLIP 유사도가 아니라 `risk.prob` 다. 발음·철자 풀은 유사도 0 인 후보를 넣지 않는다.

## 2. 응답 스키마

최상위:

| 필드 | 형식 | null | 뜻 |
|---|---|---|---|
| `api_version` | string | 아니오 | `"2026-10-24"` |
| `research_beta` | `true` | 아니오 | v1 과 같음 |
| `legal_conclusion` | `false` | 아니오 | 법적 판단이 아님 |
| `overall` | object | 아니오 | §2-1 |
| `candidates` | array | 아니오(빈 배열 가능) | §2-2, 위험도 내림차순 |
| `meta` | object | 아니오 | §2-3 |
| `dataset_info` | object | 아니오 | v1 과 같음(`총_상표수`·`출원일자_범위`·`데이터_기준`·`생성일자`) |
| `index_size` | int | 아니오 | 비교 대상 DB 레코드 수(현재 1,100) |
| `top_k_requested` / `top_k_returned` | int | 아니오 | 요청·반환 수 |

### 2-1. `overall`

| 필드 | 형식 | null | 뜻 |
|---|---|---|---|
| `grade` | `"안전"` \| `"주의"` \| `"검토 권장"` \| `"위험"` | 후보 0건이면 null | 후보 중 **가장 높은 등급**(규칙 하한 적용 뒤). 등급 순서는 안전 < 주의 < 검토 권장 < 위험 |
| `prob` | 0~1 | 후보 0건이면 null | 후보 `risk.prob` 의 최댓값(소수 3자리) |
| `caveats` | string[] | 아니오(빈 배열 가능) | 사용자에게 **그대로** 보여 줄 주의 문구. 문구는 §2-5 표의 것만 쓴다(프론트가 문자열 비교로 아이콘을 고를 수 있게) |
| `query_type.type` | `"문자"` \| `"도형"` \| `"결합-문자요부"` \| `"결합-도형요부"` | 아니오 | 모델이 쓴 유형(교호작용 `x1×문자계`·`x2_img×도형계` 와 도형 규칙의 기준). **이름이 있으면 항상 문자계**, 도형계는 이름 없는 이미지 질의·사용자 선택만(§2-4 5항) |
| `query_type.suggested_name` | string | 읽은 글자가 없으면 null(이름이 있거나 이미지가 없으면 항상 null) | 이름 없는 이미지 질의에서 OCR 이 읽은 글자(확신도 ≥ 0.5 박스만, 읽기 순서, 최대 60자). 화면이 "상표명으로 넣기"를 제안하고 사용자 확인 뒤 `name` 으로 재요청한다(이 요청에서 이름 축은 계산하지 않음 — 토큰 1회용) |
| `query_type.source` | `"ocr"` \| `"fallback"` \| `"user"` | 아니오 | `ocr` 이미지 글자 면적으로 판정, `fallback` OCR 없음·실패라 입력 구성으로 정함, `user` `type_override` |
| `query_type.detail` | `{ "text_ratio": 0~1, "fig_ratio": 0~1 }` | `ocr` 가 아니면 null | OCR 글자 박스 면적 비율·글자를 지운 뒤 남은 면적 비율(판정 근거, 디버그·툴팁용) |
| `visual_status` | v1 `status_code`(`STRONG_MATCH`…`NO_CLOSE_MATCH`) | 이미지가 없으면 null | **제안(선택)**: 이미지 입력에 대한 v1 시각 4상태(임계 0.75/0.55/0.45). 모델이 도형계에서 CLIP 효과를 0 으로 학습해(§3-2) 이미지만 넣으면 `prob` 가 0.02 안팎이므로, 화면이 시각 유사 자체를 계속 보여 주기 위해 둔다. 받아들이지 않으면 필드를 뺀다 |

### 2-2. `candidates[]`

| 필드 | 형식 | null | 뜻 |
|---|---|---|---|
| `id` | string | 아니오 | 출원번호(v1 `trademark.출원번호`, 13자리) |
| `title` | string | 상표명이 없으면(순수 도형) null | `상표한글명`, 없으면 `상표영문명` |
| `image_url` | string | 이미지 비공개(`MARKLENS_PUBLIC_RESULT_IMAGES=false`)·없음이면 null | 엔진·내부 API 는 v1 과 같이 `/images/<key>` 를 내고(`storage.public_url`), 브라우저 표시는 프론트의 v1 `imageUrl()` 이 `/api/images/<key>` 로 바꾼다. 예시 JSON 은 브라우저 측 값 |
| `type` | `"문자"` \| `"도형"` \| `"결합"` \| null | 알 수 없으면 null | **표시용** 후보 유형. DB `상표구분` → `도형상표`=도형, `도형복합`=결합, 비어 있으면 비엔나코드 + 상표명 있음=결합, 비엔나코드만=도형, 비엔나코드 없음=문자. 모델은 이 값이 아니라 `overall.query_type.type` 을 쓴다 |
| `applicant` | string | 없으면 null | **제안(선택)**: 출원인(v1 `출원인`) — 현재 화면이 보여 주는 값이라 재조회를 피하려 둔다 |
| `nice_classes` | int[] | 아니오(빈 배열 가능) | **제안(선택)**: 류(v1 `류`) |
| `axes.x1` | 0~1 | 이름 없음·어느 쪽이든 호칭 없음(`has_pronunciation` false)이면 null | X1 호칭 `phonetic_similarity(query, title, extra_generic=removed)` — 학습의 `x1_d` |
| `axes.x2_text` | 0~1 | 이름 없음·어느 쪽이든 글자 토큰 없음(`has_spelling` false)이면 null | X2 철자 `orthographic_similarity(…, extra_generic=removed)` — `x2_text_d` |
| `axes.x2_img` | 0~1 | 이미지 없음·후보 이미지 없음이면 null | X2 전체 이미지 CLIP 코사인(v1 `similarity`, 음수는 0 으로 자른다) — `x2_whole` |
| `axes.x3` | 0~1 | 이름 없음·어느 쪽이든 관념 없음(`has_meaning` false — 조어·기호)이면 null | X3 관념 `semantic_similarity(…, extra_generic=removed)` — `x3_d`. 두 이름 모두 사전어가 있어야 값이 있다(게이트) |
| `axes.x4` | 0~1 | `goods_codes` 없음·후보에 유사군 없음이면 null | X4 `goods_similarity(goods_codes, candidate.goods.codes)` 자카드 |
| `risk.prob` | 0~1 | 아니오 | 통합 모델 위험도(소수 3자리). v1.3: null 인 이미지·상품 축은 지시변수가 아니라 **결측 패턴별 계수 집합**으로 — 관측된 축 조합(base / x2_whole / x4 / x2_whole+x4)마다 계수·절편이 따로 있고 런타임이 입력에 맞는 집합을 고른다(설계 §7-3). 관념 축이 null 이면 값 0 |
| `risk.grade` | 4등급 | 아니오 | §2-4 규칙 적용 뒤 등급 |
| `risk.contributions` | `{ "X1": n, "X2": n, "X3": n, "X4": n, "요부": n }` | 아니오 | 축별 **로짓 기여도**(계수×값, 양·음 가능). 점수 항만 모은다 — `x1`·`x1×문자계`·`x1×요부없음` → X1, `x2_text`·`x2_img`·`x2_img×도형계` → X2, `x3` → X3, `x4` → X4, `any_no_distinctive` → 요부. 결측 보정(`miss_pattern`)은 넣지 않는다(아래 `missing_adjustment`). 런타임 `axis_contributions()` 는 결측 항을 포함하므로 엔진이 `miss_` 항을 떼어 낸다 |
| `risk.missing_adjustment` | number | 아니오 | 결측 패턴 절편 보정 = 쓰인 패턴의 절편 − 기준 절편(기준 = 이미지·상품 모두 관측한 패턴 `x2_whole+x4`, 절편 -3.4712). v1.3 패턴 절편: base -3.6361·x2_whole -3.8103·x4 -3.4535 → 보정 -0.165·-0.339·0.018·0(음수 가능, 결측 지시변수 아님). `intercept(-3.4712) + Σcontributions + missing_adjustment = logit(prob)` 가 성립해야 한다(엔진 테스트 조건; §3 예시는 소수 3자리로 반올림했으므로 되계산한 p 는 ±0.001 안) |
| `risk.figure_caveat` | bool | 아니오 | 유형이 도형계(도형·결합-도형요부)면 true — `RiskResult.figure_caveat` |
| `risk.rule_triggers` | string[] | 아니오(빈 배열 가능) | 등급 하한을 "검토 권장"으로 올린 규칙: `standalone_x1`(x1 ≥ 0.98), `standalone_x2_text`(≥ 0.75), `standalone_x3`(≥ 0.7707), `figure_x2_img`(도형계이고 x2_img ≥ 0.9). `x2_img`·`x4` 의 단독 임계값은 null(비활성)이라 없다. 규칙이 걸려도 `prob` 는 바뀌지 않는다 |
| `salient.query_tokens` | string[] | 아니오 | 입력 상표명의 **요부 후보**(식별력 점수 ≥ θ 0.5, 이름 순서, NFKC·소문자 정규화). 이름이 없으면 빈 배열. 비어 있고 이름이 있으면 "요부 없음 → 전체 대비"(2000후2453) |
| `salient.candidate_tokens` | string[] | 아니오 | 후보 상표명의 요부 후보(같은 규칙) |
| `salient.removed[]` | `{ "token": s, "reason": s, "side": "query" \| "candidate" \| "both" }` | 아니오(빈 배열 가능) | 이 쌍의 비교에서 **실제로 뺀 토큰**(`pair_generic(query, title, goods_codes)` 결과)과 판정 사유(`judge().reasons` 를 `·` 로 이음: `1호 보통명칭`, `3호 기술적 표장:원재료(류 30,35,43)`, `4호 지명`, `5호 흔한 성`, `6호 간단 표장`, `일반어(zipf 4.6)`, `다수 등록(A=53, N=54)`). 결합 규칙 v0.2·v0.3 이 요부로 되돌린 토큰은 여기 없다(비교에 쓰였으므로) |
| `goods.codes` | string[] | 아니오(빈 배열 가능) | 후보의 유사군 코드(v1 `유사군`). DB 보유 589/1,100 건(2026-10-27 — 시연 업종 7개 류 전부) — 없으면 빈 배열이고 `x4` 는 null |
| `goods.jaccard` | 0~1 | `x4` 와 같은 조건으로 null | `axes.x4` 와 같은 값(지정상품 요약 영역용 중복 제공) |

### 2-3. `meta`

| 필드 | 형식 | 뜻 |
|---|---|---|
| `model_version` | string | 계수 JSON `version` — `"risk_model_v1.3"` |
| `grade_precision` | 0~1 | **"위험" 등급의 정밀도** = 검증 데이터(심결 314행 + 쉬운 음성 700, 사건 단위 5겹×3반복 OOF, 행마다 자기 결측 패턴)에서 "위험"으로 분류된 152쌍 중 심결이 유사로 본 107쌍 → 0.7039 ≈ **0.70**(v1.3, 설계 §7-3; v1.2.1 은 159쌍 중 109 → 0.6855). 엔진은 JSON `meta.grade_precision` 을 읽는다(E-6) |
| `thresholds.grade` | `{ "주의": 0.0902, "검토 권장": 0.1805, "위험": 0.5902 }` | 등급 하한 p(JSON `grade_thresholds`, v1.3). 안전은 0~0.0902 |
| `thresholds.standalone` | `{ "x1": 0.98, "x2_text": 0.75, "x2_img": null, "x3": 0.7707, "x4": null }` | 단독 임계값 τ(JSON `standalone_thresholds`, 정밀도 ≥ 0.7 지점). null 은 비활성 |
| `thresholds.figure` | 0.9 | 도형 규칙 τ(JSON `figure_rule.threshold`, 미검증) |
| `pool` | `{ "image": n, "phonetic": n, "spelling": n, "semantic": n, "goods": n, "total": n }` | 후보 풀 크기(§1-3). 입력이 없는 축은 0 |
| `elapsed_ms` | int | 서버 처리 시간(임베딩·축 계산·모델 포함, 네트워크 제외) |

임계값은 **응답의 `meta.thresholds` 가 단일 소스**다. 프론트는 상수를 두지 않고 이 값으로 등급 경계·바 눈금을 그린다(v1 `grade.thresholds` 와
같은 원칙).

### 2-4. 등급 규칙(요약 — 정본은 통합 모델 설계 §7-2)

1. `prob = sigmoid(intercept + Σ 계수×값)`. 계수 집합은 입력의 결측 패턴(이미지 유무 × 상품 유무, v1.3 §7-3)에 따라 넷 중 하나 —
   관측된 축만 입력에 있고 결측 지시변수는 없다(관념 축이 null 이면 값 0). 축 하나를 하한값(현실 분포 비유사 쌍 평균: 이미지
   0.3487·상품 0.0252) 이상으로 더 관측하면 `prob` 는 내려가지 않는다(결합 제약, 적재 때 검증). 유형은 `overall.query_type.type`
   하나를 쌍 전체에 쓴다(학습이 이 사건 표장의 유형으로 했으므로).
2. `grade` 는 `meta.thresholds.grade` 의 하한으로 — 0.5902 이상 위험, 0.1805 이상 검토 권장, 0.0902 이상 주의, 그 아래 안전(v1.3).
3. **단독 규칙**(97후3050 후단): 어느 축이든 τ 이상이면 등급 하한 "검토 권장"(자동 "위험" 아님) → `rule_triggers`.
4. **도형 규칙**(미검증 제품 규칙): 도형계 유형이면 `figure_caveat = true` + `caveats` 에 도형 문구, `x2_img ≥ 0.9` 면 등급 하한 "검토 권장".
5. 유형 규칙(2026-10-24 개정 — OCR 은 유형의 최종 결정자가 아니라 이름이 없을 때 글자를 찾아 주는 도우미):
   - `type_override` 가 있으면 그대로(`source: user`; `결합` 은 이름이 있을 때 결합-문자요부, 없을 때 결합-도형요부).
   - **`name` 이 있으면 유형은 항상 문자계**: 이미지가 없거나 OCR `fig_ratio < 0.08` → 문자, 그 외(이미지에 뚜렷한 도형
     영역) → 결합-문자요부. OCR 이 글자를 못 읽어도(실패·시간 초과·비활성) 도형계로 가지 않고 문자(`source: fallback`,
     caveat `OCR_FALLBACK`). 근거: 사용자가 이름을 입력했다 = 상표에 문자 부분이 있다, 판례상 문자가 있는 결합상표는 호칭이
     중요(97후3050). `source` 는 비율을 썼으면 `ocr`, 아니면 `fallback`.
   - **도형계(도형·결합-도형요부)는 두 경우만**: (a) `name` 없는 이미지 질의 — OCR 글자 영역 `text_ratio ≥ 0.05` 면
     결합-도형요부, 그 외·OCR 실패면 도형 (b) `type_override` 로 사용자가 직접 선택.
   - `name` 없는 이미지 질의에서 OCR 이 글자를 읽으면 `query_type.suggested_name`(확신도 ≥ 0.5 박스, 최대 60자)과
     caveat `NAME_SUGGESTED` 를 돌려준다. 못 읽으면 기존대로 도형 + `FIGURE_LOW_DATA`. 이 요청에서 이름 축을 자동
     계산하지는 않는다(사용자 확인 뒤 재요청 — Turnstile 토큰 1회용 규약).
   - 비고(개정 이유): 이전 규칙은 OCR 자동 유형(`auto_type`)이 최종 결정자여서, 글자가 작은 결합상표를 도형으로 오판하면
     (X2 설계 §7 유형 일치 76% — 오판 24%) 이름이 있어도 `x1×문자계` 교호작용(계수 2.26)이 빠져 호칭 가중치가 깎였다.
     셋 다 입력 실측(2026-10-24): 같은 "블루커피" / BLU hands 쌍이 이름만 넣으면 p 0.58(위험), 도형 이미지를 더하면 OCR 이
     도형으로 판정해 p 0.08(검토 권장)로 떨어졌다 → 이름이 있으면 문자계로 고정.
     개정 후 실측(2026-10-25): 같은 셋 다 입력이 결합-문자요부(OCR `fig_ratio` 0.717)로 판정돼 **p 0.47(검토 권장)** —
     `x1×문자계` 는 돌아왔고, 이름만(0.58 위험)과의 남은 차이는 유형이 아니라 이미지 결측 보정(`miss_x2img` +0.50 로짓)이
     실제 x2_img 0.36 의 기여(+0.08, 1.0 이어도 +0.21)보다 큰 v1.2.1 모델 성질이었다 → **통합 모델 v1.3(2026-10-25, 설계
     §7-3)** 이 결측 지시변수를 결측 패턴별 계수 집합 + 결합 제약으로 바꿔 닫았다: 같은 쌍 이름만 p 0.530, 셋 다(x2_img 0.36)
     0.531 — 입력을 더 주면 위험도가 내려가지 않는다(둘 다 검토 권장; 위험 하한 0.5902).

### 2-5. `caveats` 문구 표(응답은 문구 문자열만 싣는다)

| 코드(구현 참고) | 문구(그대로) | 언제 |
|---|---|---|
| `FIGURE_LOW_DATA` | 도형 유사는 검증 데이터가 적어 참고용 | `query_type.type` 이 도형계(JSON `figure_rule.caveat` 와 같은 문자열) |
| `NO_IMAGE` | 이미지가 없어 외관(이미지) 축은 비교하지 않았습니다 | `image` 없음 |
| `NO_NAME` | 상표명이 없어 호칭·철자·관념 축은 비교하지 않았습니다 | `name` 없음 |
| `NO_PRONUNCIATION` | 입력 상표명에 호칭이 없어(기호·한자만) 호칭 축은 비교하지 않았습니다 | `name` 은 있으나 `has_pronunciation` false |
| `NO_MEANING` | 입력 상표명에 사전적 의미가 없어(조어) 관념 축은 비교하지 않았습니다 | `name` 은 있으나 `has_meaning` false |
| `NO_GOODS` | 지정상품이 없어 상품 견련성은 비교하지 않았습니다 | `goods_codes` 없음 |
| `GOODS_COVERAGE` | 비교 대상 중 지정상품 정보가 있는 상표는 100/1,100건입니다 | `goods_codes` 있음(수치는 유사군 보유 수·`index_size` 로 서버가 채움 — 2026-10-27 백필 뒤 589/1,100. 아래 §3-1 예시는 백필 전 값) |
| `GOODS_ONLY` | 지정상품만으로는 유사군이 겹치는 상표를 나열할 뿐 표장 유사는 비교하지 않았습니다 | 지정상품만 입력 |
| `OCR_FALLBACK` | 이미지에서 글자를 읽지 못해 유형을 {도형\|문자}(으)로 두었습니다. 아니면 유형을 고쳐 주세요 | `image` 있고 `source = fallback` |
| `NO_CANDIDATES` | 비교할 후보가 없습니다 — 안전하다는 뜻이 아닙니다 | `candidates` 0건 |
| `NAME_SUGGESTED` | 이미지에서 '{텍스트}'를 읽었습니다 — 상표명으로 넣으면 호칭·철자·관념도 비교합니다 | `name` 없는 이미지 질의에서 OCR 이 글자를 읽음(`query_type.suggested_name` 과 같은 문자열) |
| `X3_DISABLED` | 관념 축이 꺼져 있어(MARKLENS_X3_ENABLED=0) 관념 유사도는 비교하지 않았습니다 | `name` 은 있으나 X3 비활성(`MARKLENS_X3_ENABLED=0`) 또는 관념 캐시·모델 실패 — `x3` 는 null, `pool.semantic` 0 |

## 3. 예시 JSON

두 예시 모두 2026-10-25 현재 코드로 계산한 값이다(식별력 v0.3, X1 v1.6, X2 철자, X3 MiniLM 재보정, X4 자카드, 모델 v1.3 — 축
값은 2026-10-24 와 같고 `risk.*`·`meta` 만 v1.3 으로 다시 계산).
후보의 출원번호·출원인은 가짜고 상표명·유사군만 의미가 있다. 프론트는 이 두 응답을 Vitest 픽스처로, 백엔드는 스텁 응답으로 그대로 쓴다.

### 3-1. 문자상표 — 이름 "블루커피" + 카페 세트, 이미지 없음

요청(BFF): `POST /api/search/v2?top_k=4`, `X-Turnstile-Token`, multipart
`name=블루커피`, `goods_codes=G0301`, `goods_codes=G0502`, `goods_codes=S120602`, `goods_codes=S2005`
(업종 세트 "카페" = 커피전문점업 43류·커피 30류·커피 소매업 35류의 유사군 합집합).

판정 흐름: 입력 토큰 `블루`(0.62 — 일반어 zipf 4.6·다수 등록 A=4, 요부 후보로 남음)·`커피`(0.0 — 1호 보통명칭·3호 기술적 표장
원재료 → 제외). 후보 쪽에서는 `blue`(일반어·다수 등록 A=53), `cafe`(3호 용도 류 35·43)가 제외된다. 네 후보 중 위험 2·검토 권장 2.

```json
{
  "api_version": "2026-10-24",
  "research_beta": true,
  "legal_conclusion": false,
  "overall": {
    "grade": "위험",
    "prob": 0.604,
    "caveats": [
      "이미지가 없어 외관(이미지) 축은 비교하지 않았습니다",
      "비교 대상 중 지정상품 정보가 있는 상표는 100/1,100건입니다"
    ],
    "query_type": { "type": "문자", "source": "fallback", "detail": null, "suggested_name": null },
    "visual_status": null
  },
  "candidates": [
    {
      "id": "4020230001001",
      "title": "BLUE CAFE 블루카페",
      "image_url": "/api/images/4020230001001.png",
      "type": "결합",
      "applicant": "예시 출원인 1",
      "nice_classes": [43],
      "axes": { "x1": 0.891, "x2_text": 0.556, "x2_img": null, "x3": 0.548, "x4": 0.25 },
      "risk": {
        "prob": 0.604,
        "grade": "위험",
        "contributions": { "X1": 3.162, "X2": 0.475, "X3": 0.0, "X4": 0.24, "요부": 0.0 },
        "missing_adjustment": 0.018,
        "figure_caveat": false,
        "rule_triggers": []
      },
      "salient": {
        "query_tokens": ["블루"],
        "candidate_tokens": ["블루카페"],
        "removed": [
          { "token": "커피", "reason": "1호 보통명칭·3호 기술적 표장:원재료(류 30,35,43)", "side": "query" },
          { "token": "blue", "reason": "일반어(zipf 5.1)·다수 등록(A=53, N=54)", "side": "candidate" },
          { "token": "cafe", "reason": "3호 기술적 표장:용도(류 35,43)", "side": "candidate" }
        ]
      },
      "goods": { "codes": ["S120602"], "jaccard": 0.25 }
    },
    {
      "id": "4020220000777",
      "title": "블루보틀 BLUE BOTTLE",
      "image_url": "/api/images/4020220000777.png",
      "type": "결합",
      "applicant": "예시 출원인 2",
      "nice_classes": [30, 43],
      "axes": { "x1": 0.673, "x2_text": 0.5, "x2_img": null, "x3": 0.52, "x4": 0.75 },
      "risk": {
        "prob": 0.52,
        "grade": "검토 권장",
        "contributions": { "X1": 2.388, "X2": 0.427, "X3": 0.0, "X4": 0.719, "요부": 0.0 },
        "missing_adjustment": 0.018,
        "figure_caveat": false,
        "rule_triggers": []
      },
      "salient": {
        "query_tokens": ["블루"],
        "candidate_tokens": ["블루보틀", "bottle"],
        "removed": [
          { "token": "커피", "reason": "1호 보통명칭·3호 기술적 표장:원재료(류 30,35,43)", "side": "query" },
          { "token": "blue", "reason": "일반어(zipf 5.1)·다수 등록(A=53, N=54)", "side": "candidate" }
        ]
      },
      "goods": { "codes": ["G0301", "G0502", "S120602"], "jaccard": 0.75 }
    },
    {
      "id": "4020210000333",
      "title": "블루밍 BLOOMING",
      "image_url": null,
      "type": "결합",
      "applicant": "예시 출원인 3",
      "nice_classes": [3],
      "axes": { "x1": 0.778, "x2_text": 0.625, "x2_img": null, "x3": 0.539, "x4": 0.0 },
      "risk": {
        "prob": 0.46,
        "grade": "검토 권장",
        "contributions": { "X1": 2.761, "X2": 0.534, "X3": 0.0, "X4": 0.0, "요부": 0.0 },
        "missing_adjustment": 0.018,
        "figure_caveat": false,
        "rule_triggers": []
      },
      "salient": {
        "query_tokens": ["블루"],
        "candidate_tokens": ["블루밍", "blooming"],
        "removed": [
          { "token": "커피", "reason": "1호 보통명칭·3호 기술적 표장:원재료(류 30,35,43)", "side": "query" }
        ]
      },
      "goods": { "codes": ["G1201"], "jaccard": 0.0 }
    },
    {
      "id": "4020200002222",
      "title": "레드커피",
      "image_url": "/api/images/4020200002222.png",
      "type": "결합",
      "applicant": "예시 출원인 4",
      "nice_classes": [30, 43],
      "axes": { "x1": 0.473, "x2_text": 0.0, "x2_img": null, "x3": 0.0, "x4": 0.5 },
      "risk": {
        "prob": 0.215,
        "grade": "검토 권장",
        "contributions": { "X1": 1.679, "X2": 0.0, "X3": 0.0, "X4": 0.479, "요부": 0.0 },
        "missing_adjustment": 0.018,
        "figure_caveat": false,
        "rule_triggers": []
      },
      "salient": {
        "query_tokens": ["블루"],
        "candidate_tokens": ["레드"],
        "removed": [
          { "token": "커피", "reason": "1호 보통명칭·3호 기술적 표장:원재료(류 30,35,43)", "side": "both" }
        ]
      },
      "goods": { "codes": ["G0502", "S120602"], "jaccard": 0.5 }
    }
  ],
  "meta": {
    "model_version": "risk_model_v1.3",
    "grade_precision": 0.7039,
    "thresholds": {
      "grade": { "주의": 0.0902, "검토 권장": 0.1805, "위험": 0.5902 },
      "standalone": { "x1": 0.98, "x2_text": 0.75, "x2_img": null, "x3": 0.7707, "x4": null },
      "figure": 0.9
    },
    "pool": { "image": 0, "phonetic": 20, "spelling": 20, "semantic": 5, "goods": 20, "total": 41 },
    "elapsed_ms": 180
  },
  "dataset_info": {
    "총_상표수": 1100,
    "출원일자_범위": "2021-01-05 ~ 2026-08-20",
    "데이터_기준": "KIPRIS Plus 등록상표, generation 20260827T035002Z-25f84a6eeb26",
    "생성일자": "2026-08-27"
  },
  "index_size": 1100,
  "top_k_requested": 4,
  "top_k_returned": 4
}
```

검산(v1.3, 이미지 없음·상품 있음 → 패턴 `x4`, 절편 -3.4535): 후보 1 의 로짓 = -3.4712(기준 절편) + 3.162 + 0.475 + 0.0 + 0.24 +
0.018(패턴 절편 보정) = 0.424 → sigmoid 0.604. 후보 2 는 0.52 로 "위험" 하한 0.5902 아래의 "검토 권장"(v1.2.1 에서는 0.564 위험 — 결측
지시변수 +0.5 가 빠진 만큼 내려갔다). X3 기여가 0 인 것은 v1.3 관념 계수가 0(단조 하한)이기 때문. "레드커피"는 `커피`를 양쪽에서 떼면 `블루` 대 `레드`라 철자 0·관념 0(재보정 뒤
0 으로 잘림)이고 호칭 0.473(제거 전 전체 결합음 "블루커피/레드커피"가 X1 후보에 남아 0 이 아니다).

### 3-2. 도형상표 — 이미지만, 상표명·지정상품 없음

요청: `POST /api/search/v2?top_k=3`, multipart `image=<png>`. OCR 글자 면적 0.01 → 도형(`source: ocr`). 후보는 CLIP 상위 20 중 위험도
순 3건. 호칭·철자·관념·상품 축은 전부 null 이라 패턴 `x2_whole`(절편 -3.8103)의 이미지 항만 남고(`prob` 0.06·0.053·0.043), 1위는
`x2_img 0.93 ≥ 0.9` 도형 규칙으로 "검토 권장", 2·3위는 "안전"이다. `visual_status` 는 같은 이미지의 v1 판정(top-1 0.93 ≥ 0.75 → `STRONG_MATCH`).

```json
{
  "api_version": "2026-10-24",
  "research_beta": true,
  "legal_conclusion": false,
  "overall": {
    "grade": "검토 권장",
    "prob": 0.06,
    "caveats": [
      "도형 유사는 검증 데이터가 적어 참고용",
      "상표명이 없어 호칭·철자·관념 축은 비교하지 않았습니다",
      "지정상품이 없어 상품 견련성은 비교하지 않았습니다"
    ],
    "query_type": {
      "type": "도형", "source": "ocr", "detail": { "text_ratio": 0.01, "fig_ratio": 0.62 }, "suggested_name": null
    },
    "visual_status": "STRONG_MATCH"
  },
  "candidates": [
    {
      "id": "4020190004444",
      "title": null,
      "image_url": "/api/images/4020190004444.png",
      "type": "도형",
      "applicant": "예시 출원인 5",
      "nice_classes": [25],
      "axes": { "x1": null, "x2_text": null, "x2_img": 0.93, "x3": null, "x4": null },
      "risk": {
        "prob": 0.06,
        "grade": "검토 권장",
        "contributions": { "X1": 0.0, "X2": 1.059, "X3": 0.0, "X4": 0.0, "요부": 0.0 },
        "missing_adjustment": -0.339,
        "figure_caveat": true,
        "rule_triggers": ["figure_x2_img"]
      },
      "salient": { "query_tokens": [], "candidate_tokens": [], "removed": [] },
      "goods": { "codes": [], "jaccard": null }
    },
    {
      "id": "4020210005555",
      "title": "뫼비우스 MOBIUS",
      "image_url": "/api/images/4020210005555.png",
      "type": "결합",
      "applicant": "예시 출원인 6",
      "nice_classes": [9, 42],
      "axes": { "x1": null, "x2_text": null, "x2_img": 0.81, "x3": null, "x4": null },
      "risk": {
        "prob": 0.053,
        "grade": "안전",
        "contributions": { "X1": 0.0, "X2": 0.922, "X3": 0.0, "X4": 0.0, "요부": 0.0 },
        "missing_adjustment": -0.339,
        "figure_caveat": true,
        "rule_triggers": []
      },
      "salient": { "query_tokens": [], "candidate_tokens": ["뫼비우스", "mobius"], "removed": [] },
      "goods": { "codes": ["G390802"], "jaccard": null }
    },
    {
      "id": "4020220006666",
      "title": "INFINITY",
      "image_url": null,
      "type": "결합",
      "applicant": "예시 출원인 7",
      "nice_classes": [35],
      "axes": { "x1": null, "x2_text": null, "x2_img": 0.62, "x3": null, "x4": null },
      "risk": {
        "prob": 0.043,
        "grade": "안전",
        "contributions": { "X1": 0.0, "X2": 0.706, "X3": 0.0, "X4": 0.0, "요부": 0.0 },
        "missing_adjustment": -0.339,
        "figure_caveat": true,
        "rule_triggers": []
      },
      "salient": { "query_tokens": [], "candidate_tokens": ["infinity"], "removed": [] },
      "goods": { "codes": [], "jaccard": null }
    }
  ],
  "meta": {
    "model_version": "risk_model_v1.3",
    "grade_precision": 0.7039,
    "thresholds": {
      "grade": { "주의": 0.0902, "검토 권장": 0.1805, "위험": 0.5902 },
      "standalone": { "x1": 0.98, "x2_text": 0.75, "x2_img": null, "x3": 0.7707, "x4": null },
      "figure": 0.9
    },
    "pool": { "image": 20, "phonetic": 0, "spelling": 0, "semantic": 0, "goods": 0, "total": 20 },
    "elapsed_ms": 410
  },
  "dataset_info": {
    "총_상표수": 1100,
    "출원일자_범위": "2021-01-05 ~ 2026-08-20",
    "데이터_기준": "KIPRIS Plus 등록상표, generation 20260827T035002Z-25f84a6eeb26",
    "생성일자": "2026-08-27"
  },
  "index_size": 1100,
  "top_k_requested": 3,
  "top_k_returned": 3
}
```

검산(v1.3): 도형계에서 패턴 `x2_whole` 의 `x2_img` 계수 0.5 + 교호작용 `x2_img×도형계` 0.6382 → 1위 X2 = 1.059, 로짓 = -3.4712 +
-0.339(패턴 절편 보정) + 1.059 = -2.751 → 0.06. 도형계 이미지 계수는 결합 제약이 정한 값이지 심결 데이터의 증거가 아니다(설계
§7-3 — 도형계 쌍 37 뿐, 판례 조건 (ii) 불성립 그대로). 이미지만 넣은 질의는 모델이 아니라 **도형 규칙과 `visual_status`** 로 읽어야
하며 화면은 `axes.x2_img` 값과 caveat 를 함께 보여 준다(§4-5).

## 4. 화면 문구 규약(프론트가 그대로 구현)

### 4-1. 근거 축(`risk.contributions`)

- 표시 순서: 기여도 **내림차순**. 0 이하인 축은 목록에서 빼고(음수는 "위험을 낮춘 요소"로 접힘 영역에만), null 축(`axes.*` 가 null)은
  "정보 없음"으로 회색 처리해 맨 뒤.
- 라벨: `X1` → 호칭(발음), `X2` → 외관(철자·이미지), `X3` → 관념(뜻), `X4` → 지정상품, `요부` → 요부(식별력).
- 바 길이 = 해당 축 기여도 ÷ 양수 기여도 합(예 3-1 후보 1: X1 3.628/4.688 = 77%, X2 13%, X4 8%, X3 2%).
- 축 값 표기는 `axes.*` 를 백분율 정수로("호칭 89%"), 바는 기여도로 — 둘을 섞지 않는다(점수가 높아도 계수가 작으면 기여도가 작다: X3).
- `rule_triggers` 가 있으면 등급 옆에 한 줄: `standalone_x1` "호칭이 거의 같아 검토 권장으로 올렸습니다", `standalone_x2_text` "철자가
  매우 비슷해 …", `standalone_x3` "뜻이 매우 비슷해 …", `figure_x2_img` "도형이 매우 비슷해 …(검증 데이터 부족, 참고용)".

### 4-2. 요부·제외 토큰(`salient`)

생성 규칙 — 후보 카드마다 `removed` 가 비어 있지 않으면 한 문장:

```
'{removed 토큰들을 ·로}'은(는) {사유 표현}이라 제외, '{query_tokens 를 ·로}'(으)로 비교
```

예 3-1 후보 1: **'커피'는 흔한 말이라 제외, '블루'로 비교** (후보 쪽 제외 토큰 `blue`·`cafe` 는 같은 틀로 두 번째 문장:
"'blue·cafe'는 흔한 말이라 제외, '블루카페'로 비교"). `side: both` 는 한 문장으로 합친다. 조사(은/는, 으로/로)는 마지막 글자의 받침으로
고른다(라틴 문자 토큰은 "는"·"로").

사유 → 표현(첫 사유 기준, 여러 개면 가장 앞의 것):

| `reason` 접두 | 표현 |
|---|---|
| `1호 보통명칭` | 흔한 말(상품 이름) → 짧은 문장에서는 **흔한 말** |
| `3호 기술적 표장` | 상품을 설명하는 말 |
| `4호 지명` | 지명 |
| `5호 흔한 성` | 흔한 성씨 |
| `6호 간단 표장` | 간단한 표장 |
| `일반어` / `다수 등록` | 흔한 말 / 여러 상표에 흔히 쓰이는 말 |

전체 `reason` 문자열은 툴팁(또는 "자세히")에 그대로 보여 준다. `query_tokens` 가 비어 있고 이름이 있으면 "식별력 있는 부분이 없어 전체로
비교했습니다"(2000후2453).

### 4-3. 등급 정밀도(`meta.grade_precision`)

- 문구: **"검증 데이터 기준 10건 중 {round(grade_precision × 10)}건"** → 0.69 → "검증 데이터 기준 10건 중 7건". 전체 문장:
  "'위험'으로 분류된 상표 쌍은 검증 데이터 기준 10건 중 7건이 심결에서 유사로 판단됐습니다".
- 표시 위치: `overall.grade` 또는 후보 `risk.grade` 가 **"위험"** 일 때 등급 배지 옆 한 줄. 다른 등급에는 쓰지 않는다(정밀도 값이 위험
  등급의 것이므로).
- 값은 응답에서 읽는다(상수 금지). 모델이 재학습되면 숫자가 바뀐다.

### 4-4. 등급 표기

| 등급 | 색(제안) | 한 줄 설명 |
|---|---|---|
| 안전 | 회색 | 비교 표본에서 가까운 후보를 찾지 못했습니다 — 안전 판정이 아닙니다 |
| 주의 | 노랑 | 일부 축이 비슷한 후보가 있습니다 |
| 검토 권장 | 주황 | 비슷한 선행 상표가 있을 수 있습니다. 전문가 검토를 권장합니다 |
| 위험 | 빨강 | 여러 축이 비슷한 선행 상표가 있습니다 + §4-3 문구 |

`overall.grade` 가 null(후보 0건)이면 등급 배지 대신 `caveats` 의 "비교할 후보가 없습니다 — 안전하다는 뜻이 아닙니다"를 1층에 둔다.

### 4-5. 도형 caveat·시각 상태

- `risk.figure_caveat` 가 true 인 카드와 `overall` 에 "도형 유사는 검증 데이터가 적어 참고용" 배지. 이미지 입력이면 `axes.x2_img` 를
  "이미지 유사 93%"로 항상 표시하고, `visual_status`(있으면)를 v1 과 같은 4상태 문구로 1층에 함께 둔다 — 이미지만 넣었을 때 모델
  위험도(0.02 안팎)만 보여 주면 사용자가 "안전"으로 오독한다(§3-2).
- `query_type` 은 1층에 "유형: 도형(이미지에서 판정)" 식으로 보여 주고 "유형 고치기" 버튼 → `type_override` 로 재요청(토큰 새로 발급).
  `source: fallback` 이면 caveat 의 `OCR_FALLBACK` 문구를 버튼 옆에 둔다.
- `query_type.suggested_name` 이 있으면(이름 없는 이미지 질의) 1층에 "이미지에서 '…'를 읽었습니다" + **"상표명으로 넣기"**
  버튼 → 사용자가 확인·수정하면 `name` 을 채워 **재요청**(새 Turnstile 토큰). 자동으로 다시 검색하지 않는다.

## 5. 오류·경계

### 5-1. 오류 응답(v1 표와 같은 규약, v2 추가분만)

| HTTP | 언제 | `detail` |
|---:|---|---|
| 400 | `image`·`name`·`goods_codes` 가 모두 없음(공백 `name`, 빈 `goods_codes` 포함) | `image, name, goods_codes 중 하나는 있어야 합니다.` |
| 400 | 빈 파일·치수·콘텐츠 품질 | v1 `/search` 와 같음 |
| 413 / 415 | 이미지 크기·형식 | v1 과 같음 |
| 422 | `top_k` 범위, `name` 100자 초과, `goods_codes` 형식(`^[GS][0-9]{4,6}$`)·60개 초과, `type_override` 열거값 밖 | 필드별 메시지 |
| 429 | 한도(v1 `/search` 와 같은 버킷) | — |
| 503 | 엔진·인덱스 미준비(`RuntimeError`), 계수 JSON·식별력 모델 적재 실패(`ModelNotReadyError`). X3 비활성(`MARKLENS_X3_ENABLED=0`)은 **503 이 아니라** `x3` null + caveat `X3_DISABLED` 로 진행 | — |

### 5-2. OCR 실패·유형

이미지 OCR(글자 면적 판정)이 실패하면 — 라이브러리 없음·예외·시간 초과(상한 2초) — 500 이 아니라 **진행**한다: `query_type.source =
"fallback"`, `type` 은 이름이 있으면 문자, 없으면 도형, `caveats` 에 `OCR_FALLBACK` 문구. `type_override` 가 있으면 OCR 을 돌리지 않는다.

### 5-3. 축 결측과 모델 한계

- 이미지·상품 축이 null 이면 모델은 그 축 없이 학습한 계수 집합(결측 패턴, v1.3 §7-3)으로 계산한다(결측은 비유사가 아니다). 축을
  하한값(현실 분포 비유사 평균) 이상으로 더 관측하면 `prob` 는 내려가지 않고, 하한 아래(비유사 평균보다 덜 비슷한 이미지·겹치지 않는
  상품)면 내려갈 수 있다 — 음의 증거. v1.2.1 의 "입력을 더 주면 내려가는" 결측 지시변수 편향은 없다.
- 이미지만 입력하면 `prob` 는 0.05 안팎이고 등급은 도형 규칙으로만 오른다(§3-2). 지정상품만 입력하면 `x4` 뿐이라 `prob` 는 최대
  0.08 안팎(패턴 `x4` 절편 -3.4535 + x4 0.9583) → "안전"이 상한이다. 두 경우 모두 `caveats` 로 알린다.
- "위험" 정밀도 0.70(v1.3; v1.2.1 0.69) 은 검증 데이터(경계 사례 심결 + 쉬운 음성) 기준이며 서비스 분포의 정확도가 아니다(README "경계 사례 데이터").

### 5-4. 후보 0건

후보 풀이 비면(이름에 호칭·관념이 없고 이미지도 없음, 또는 모든 축의 하한 미달) `candidates: []`, `overall.grade: null`,
`overall.prob: null`, `caveats` 에 `NO_CANDIDATES`(+ 해당 `NO_*`), `meta.pool.total: 0` 으로 **200** 을 돌려준다.

### 5-5. v1 엔드포인트 유지

`POST /search`(이미지 4상태), `POST /phonetic-search`, `POST /semantic-search` 와 BFF `/api/search`·`/api/phonetic-search`·
`/api/semantic-search` 는 **최종 발표(2026-12-20, `docs/course/2026-2`)까지 유지**한다. 결과 화면이 v2 로 바뀐 뒤에도 상표명 확인
패널의 발음·관념 섹션은 v1 두 엔드포인트를 그대로 쓴다(검색과 별개 흐름). 제거는 발표 뒤 별도 PR 로 하며 v1 문서의 deprecated 필드
(`grade_code`·`grade_name`)도 그때 함께 지운다.

### 5-6. 엔진 예외 ↔ HTTP (B-1 매핑 기준, 2026-10-24 구현)

`engine.multi_search(image=None, name=None, goods_codes=None, type_override=None, top_k=5)` 는 동기 함수이고
`SearchV2Result`(`to_dict()` 가 §2 키 그대로)를 돌려준다. 예외 이름은 `backend/src/core/multi_search.py`.

| 예외 | 언제 | 메시지(그대로 `detail` 로) | HTTP |
|---|---|---|---:|
| `multi_search.EmptyQueryError`(ValueError) | `image`·`name`(공백만 포함)·`goods_codes`(빈 값만 포함)가 모두 없음 | `image, name, goods_codes 중 하나는 있어야 합니다.` | 400 |
| `ValueError` | `top_k` 가 1~20 밖, `type_override` 가 문자·도형·결합 밖 | `top_k 는 1~20 정수여야 합니다 (받은 값: …).` / `type_override 는 문자·도형·결합 중 하나여야 합니다.` | 422 |
| `multi_search.ModelNotReadyError`(RuntimeError) | 계수 JSON(`shared/model/risk_model_v1.json`, `meta.grade_precision` 포함) 또는 식별력 모델을 기동 때 못 읽음 — 서버는 떠 있고 이 기능만 | `multi_search.state.error`(원인 목록) | 503 |
| `RuntimeError` | 엔진(인덱스·CLIP) 미준비 — v1 `run_search` 와 같은 메시지 | `Engine 이 아직 초기화되지 않았습니다.` | 503 |
| (이미지 디코딩 `ValueError`) | v1 과 같이 API 의 `validation.validate_and_decode` 단계에서 — 엔진은 검증된 PIL 이미지를 받는다 | v1 과 같음 | 400 |

OCR 실패·시간 초과·비활성(`MARKLENS_OCR_ENABLED=0`)은 예외가 아니라 `query_type.source = "fallback"` + caveat 로 진행한다(§5-2).

## 6. 구현 분담표

| 번호 | 담당 | 할 일 | 만드는 필드 | 비고 |
|---|---|---|---|---|
| E-1 | 엔진(다빈) | 후보 풀 합치기 — CLIP 상위 20 ∪ 발음 상위 20 ∪ 철자 상위 20 ∪ 관념 상위 5 ∪ 유사군 겹침 상위 20, 출원번호로 중복 제거 | `candidates[].id`·`title`·`type`·`applicant`·`nice_classes`·`goods.codes`, `meta.pool` | 발음·관념 캐시는 기동 시 것 재사용. 철자 캐시(정규화 토큰)는 새로 |
| E-2 | 엔진 | 쌍별 축 계산 — `pair_generic` 으로 제외 토큰을 구해 `x1_d`·`x2_text_d`·`x3_d`, CLIP 코사인 `x2_whole`, 자카드 `x4`; 게이트(`has_pronunciation`·`has_spelling`·`has_meaning`·`has_goods`)로 null | `axes.*`, `salient.*`, `goods.jaccard` | 학습 `ml/scripts/pairs_features.py::name_axes` 와 같은 식 |
| E-3 | 엔진 | **고시 명칭 접미 분리** — 붙여쓴 한글 이름(블루커피)에서 끝이 고시 단일 명칭(커피)이면 토큰을 나눠 판정. 2026-10-24 현재 `normalize_name("블루커피")` 은 한 토큰이라 `커피` 가 제외되지 않는다(X1 설계 §4 한계 5). §3-1 예시는 이 규칙이 있는 상태의 값 | `salient.removed` 의 `커피` 행, `x1`·`x2_text`·`x3` 값 | 규칙은 식별력 `Distinctiveness` 에 넣고 X1·X2 철자·X3 가 같은 토큰을 받게 한다 |
| E-4 | 엔진 | 유형 판정 — OCR 글자 면적(`x2_split.auto_type` 규칙 0.05/0.08)으로 문자·도형·결합(+요부), 실패·미설치면 fallback, `type_override` 우선 → 2026-10-25 개정(§2-4 5항): 이름이 있으면 항상 문자계, OCR 은 이름 없는 질의의 글자 제안 `suggested_name` | `overall.query_type` | **결정 대기**: OCR 라이브러리(벤치마크는 easyocr)를 서비스 의존성에 넣을지(`constraints.txt`·Dockerfile·CI 설치 시간). 안 넣으면 `source` 는 항상 `fallback`/`user` |
| E-5 | 엔진 | `risk_score` 호출, 기여도를 축별로 묶되 `miss_*`(v1.3 은 `miss_pattern` = 패턴 절편 보정)는 `missing_adjustment` 로 분리, 단독·도형 규칙 판정을 `rule_triggers` 로, 위험도 내림차순 정렬, `overall` 집계(최대 등급·최대 p·caveat 합집합) | `risk.*`, `overall.grade`·`prob`·`caveats` | 테스트: `intercept + Σcontributions + missing_adjustment = logit(prob)`, 예시 3-1·3-2 와 같은 값 |
| E-6 | 엔진 | 학습 스크립트가 `meta.grade_precision`(위험 등급 OOF 정밀도)을 계수 JSON 에 쓰도록 한 줄 추가 → 재학습 없이 JSON 만 갱신(값 0.6855; v1.3 재학습 뒤 0.7039) | `meta.grade_precision` | 그 전까지 엔진 상수 0.69 |
| B-1 | 백엔드(현수) | `POST /search/v2` — multipart 파싱(`image`·`name`·`goods_codes` 반복 필드·`type_override`), 검증 400/413/415/422, 한도 버킷 공유, `X-Request-ID`·로깅(검색어·이미지 미기록) | 요청 전체, 오류 응답 | pydantic 응답 모델 `SearchV2Response` 를 `backend/src/schemas/search_v2.py` 에 — §2 표가 필드 정의 |
| B-2 | 백엔드 | BFF `frontend/app/api/search/v2/route.ts` — v1 `/api/search` 복제 + 세 필드 검증·전달 | — | Turnstile 검증 뒤 토큰 제거(v1 과 같음) |
| B-3 | 백엔드 | zod `SearchV2ResponseSchema`(`frontend/lib/contracts.ts`) — null 허용 축·등급 열거·`caveats` 문자열 배열, `.passthrough()` 로 전진 호환 | 응답 검증 | §3 두 JSON 이 통과해야 한다(테스트 픽스처) |
| B-4 | 백엔드 | 캐시 — 발음·관념 캐시 재사용, 철자 토큰 캐시 추가, 결과 캐시는 두지 않음(토큰 1회용·입력 조합 다양) | — | 기동 로그 "X2 철자 캐시 준비: n건" |
| B-5 | 백엔드 | gateway(`deploy/`)에 `/api/search/v2` location — 검색 5회/분 사용자별 한도 적용, `deployment-config` CI 검증 통과 | — | compose 계약 검증기(`compose.production.yml`) 갱신 |
| F-1 | 프론트(지원) | 요청 조립 — `FormData`(`image`·`name`·`goods_codes` 반복·`type_override`), 세 입력 중 하나 이상일 때만 버튼 활성, 토큰 1회용 처리(`lib/api.ts` `searchV2`) | 요청 | 선택 지정상품은 `goodsCodeUnion(selectedGoods)` |
| F-2 | 프론트 | 결과 1층 — `overall.grade` 배지(§4-4)·`prob`·`caveats` 목록·`query_type` + "유형 고치기"·`visual_status`(이미지 입력) | — | 등급 null 처리(§5-4) |
| F-3 | 프론트 | 후보 카드 — 이미지·제목·유형·류·축 백분율·근거 축 바(§4-1)·규칙 한 줄·요부 문장(§4-2)·지정상품 자카드 | — | `axes` null 은 "정보 없음" |
| F-4 | 프론트 | "검증 데이터 기준 10건 중 7건" 문구(§4-3), 도형 caveat 배지(§4-5) | — | 값은 응답에서 |
| F-5 | 프론트 | Vitest 픽스처 = §3-1·§3-2 JSON, 오류·빈 상태(400·후보 0건·`OCR_FALLBACK`) 화면 | — | zod 통과 확인 |

결정됨(2026-10-24): ① OCR 은 **easyocr 채택**(ko·en, CPU, 지연 로드; `MARKLENS_OCR_ENABLED` 기본 1, 실패·`MARKLENS_OCR_TIMEOUT`
2초 초과면 fallback; 모델 디렉터리 `EASYOCR_MODULE_PATH` — 컨테이너는 빌드 때 모델을 미리 내려받아야 한다) ② 제안 필드
`visual_status`·`applicant`·`nice_classes` **포함** ③ v1 엔드포인트는 최종 발표(2026-12-20)까지 유지 뒤 별도 PR 로 제거(§5-5) ④ 접미
분리(E-3)는 **고시 단일 명칭만**(2음절 이상 접미·2음절 이상 앞부분, 1음절 앞부분은 오분리가 많아 제외 — `Distinctiveness.
split_goods_suffix`). 엔진 몫 E-1~E-6 은 `feat/engine-multiaxis` 에 구현됐고(`backend/src/core/multi_search.py`·`ocr.py`,
`ml/src/axes/pair_axes.py`, `ml/src/mark_type.py`, `ml/scripts/precompute_types.py`). B-1~B-5의 API·문서용 Pydantic 스키마·BFF·zod·gateway는 2026-10-26 구현했다(PR #69 — 실제 모델로 BFF까지 §2 스키마·등급 규칙·로짓 검산 확인). F-1~F-5 화면(PR #72)과 E2E v2 15건도 2026-10-27 연결을 마쳤다(연결 완료; 발표 전 보완 2026-10-28 — 1층 위험도 %, 제외 사유 원문 "자세히", 시각 4상태 문구, 위험 등급 후보 카드의 정밀도 문구). 운영 배포 검증은 별도다.
