# MarkLens

MarkLens는 상표(도형·결합상표)의 출처 혼동 위험도를 외관·호칭·관념·상품 견련성
4축으로 평가하는 비상업적 교육·연구용 웹 서비스입니다. 1학기에 외관(CLIP) 검색과
백엔드를 완성했고, 2학기에 다축 모델로 확장 중입니다 — 호칭 축(X1)과 관념 축(X3)은
서비스에 연결했고, 상품 축(X4)은 라이브러리로 구현했으며, 통합 모델은 정답 데이터(심결례
라벨, 2026-10-11 마감)로 v1.2.1 까지 학습을 마쳤습니다(모델 단계 마감 — 서비스 연결은 아래 "다음 단계").

결과는 참고 정보입니다. 상표 등록 가능성, 침해 여부, 법적 위험 확률 또는 검색
범위 밖 권리의 부재를 판정하지 않습니다.

| 항목 | 2026-10-11 현재 |
|---|---|
| 마지막 갱신 | 2026-10-11 (`main` = `develop` = `2af05f3`, PR #45 까지; 이 브랜치 `chore/model-phase-wrapup` 스테이징 — 모델 단계 마감) |
| 데이터 | KIPRIS 등록상표 1,100건, generation `20260827T035002Z-25f84a6eeb26` (2026-08-27) |
| 테스트 | Python `1096 passed, 26 skipped`(가짜 ML 모드, 2026-10-11 v1.2.1 재학습 뒤 재실행 — 식별력 40·통합 모델 17·검토 화면 4·심결례 도구 포함; X3 실제 모델 검증은 별도 `219 passed`) · 프런트 Vitest `77 passed`(19 파일) · Playwright 스펙 5개 × 뷰포트 3개 = 15 |
| CI | GitHub Actions 3잡(python · frontend · deployment-config) 통과 — PR #45 병합(2026-10-11 develop `2af05f3`; #43·#44 도 통과) |

## 현재 범위

| 기능 | 상태 | 비고 |
|---|---|---|
| 이미지 검색 | 구현 | PNG/JPEG/WebP, 최대 10 MiB, 수동 크롭 지원 |
| 시각 후보 상태 | 구현 | 단조적 4개 상태, 교정 전 임시 임계값 |
| 상표명 완전일치 확인 | 구현 | KIPRIS 실시간 조회, 후보 상세·상태 분포·완전성 표시. **검색과 별개 기능**(검색 점수에 반영되지 않음) |
| KIPRIS 수집 및 인덱스 빌드 | 구현 | 체크포인트, authoritative key, manifest, 원자적 게시 |
| 호칭 유사도 X1 | 최소 연결 | `ml/src/axes/x1_phonetic.py` + `POST /phonetic-search`. 상표명 확인 패널에 "발음이 비슷한 등록상표" 섹션. 통합 점수에는 미반영 |
| 상품↔유사군 변환표·상품 검색 API | 구현 | 파서·검증기 + 로더(`ml/src/axes/goods_map.py`) + `GET /goods/search`·`/goods/classes`(BFF `/api/goods/*`). 변환표 `goods_map.json.gz` 저장소 포함(공공누리 제1유형, 출처표시). 지정상품 입력 화면(프론트-6)은 구현(`GoodsPicker`), `/search` 연동은 유사군 백필 후 |
| 상품 견련성 X4 | 라이브러리 | `ml/src/axes/x4_goods.py` 자카드. DB 유사군 보유 100/1,100건이라 서비스 적용은 백필 후 |
| 관념 X3 | 최소 연결 | `ml/src/axes/x3_semantic.py` 다국어 임베딩(paraphrase-multilingual-MiniLM-L12-v2) + 관념 게이트(wordfreq) + `POST /semantic-search`. 상표명 확인 패널에 "관념 유사 후보" 섹션(발음 섹션과 병렬 요청). 통합 점수에는 미반영 |
| 통합 모델 | **v1.2.1 학습 완료(2026-10-11, 모델 단계 마감, 서비스 미연결)** | [통합 모델 설계](docs/MarkLens_통합모델_설계.md) §7~§7-2: 판례 사전분포(σ 1.0 고정) + 단조 제약 로지스틱(결합 방법 4종 비교 뒤 채택; 심결 CV AUC 0.62·현실 분포 0.90 — 단순 축 평균 0.925 와 CI 겹침). v1.2 에서 절편 사전분포 제외·요부 플래그를 `any_no_distinctive` + x1 교호작용(2000후2453)으로·도형계 보류 규칙(caveat, x2_whole ≥ 0.9 면 검토 권장, 미검증)·쉬운 음성 50건 검토(혼동 가능 0), v1.2.1 에서 "위험" 등급 최소 지지 10 → 30(위험 하한 0.899 → 0.563 대체값 — 정밀도 0.69·159쌍·재현율 0.58)·σ CV 격자 → 1.0 고정(계수 CI 폭 약 ¼ 축소). 판례 검증 문자계 호칭·상품·요부 성립, 도형계 외관 불성립. 등급 4단계(주의 0.063·검토 권장 0.126·위험 0.563), 단독 임계값 호칭 0.98·철자 0.75·관념 0.77(정밀도 0.7) 활성. 계수 `shared/model/risk_model_v1.json`, 런타임 `ml/src/model/risk_model.py` `risk_score → (p, 등급, 기여도, figure_caveat)`. engine·API 연결은 "다음 단계". 지정상품 입력 UI(프론트-6)는 보이지만 `/search` 에는 아직 보내지 않음 |
| 정답 데이터(심결례) 수집·라벨링 | **마감(2026-10-11)** | `backend/scripts/trials_collect.py`·`trials_enrich.py`·`review_ui.py`: 수집 843건 → 자동 선별 → LLM 이중 라벨 430행(A↔B 96% → 처리 후 99%) → 보강(상표명 320/350·유사군 187) → 4축 벤치마크 → 사람 검증 37건(LLM↔사람 97%) → 식별력 v0.1 승인·v0.2·v0.3 → 학습 전 사람 결정 4행 제외. 라벨 유사 210·비유사 141·제외 79(특징 351행; 학습은 이름 있는 314행 + 쉬운 음성 700) — 아래 "정답 데이터" 소절 |
| 법적 위험 확률·등록 가능성 판단 | 미구현 | 제품 범위 밖 |
| 공개 클라우드 배포 | 템플릿만 제공 | 실제 도메인·TLS·계정 배포는 하지 않음 |

현재 로컬 검증 데이터는 서로 다른 출원번호 기준 1,100건의 제한된 연구 표본입니다.
이미지·metadata·FAISS vector가 각각 1,100개이고 Nice 45개 류를 모두 포함하지만,
선택된 출원인과 등록 상태 중심의 표본이므로 전체 선행 권리를 대표하지 않습니다.
현재 generation은 `20260827T035002Z-25f84a6eeb26`(2026-08-27 생성)이며 manifest가
`git.dirty=true`이므로 배포 artifact가 아닙니다. 상표명이 비어 있는 레코드(순수
도형 등)가 153건(14%)이고 유사군 코드는 100건에만 있습니다. 상표명 947건 중 X1 발음
후보가 있는 이름은 942건, X3 관념 게이트를 통과하는 이름은 515건(고유 374/653)입니다 —
상표명 프로파일은
[X1 설계 문서](docs/MarkLens_X1_호칭유사도_설계.md) §4·§6에 있습니다.
데이터 구성과 평가 한계는 [모델·데이터 카드](docs/MarkLens_모델카드_데이터카드.md)를
먼저 확인하세요(2026-08-15 1,000건 세대 기준으로 작성됨).

## 구현 현황 (방학 분배 항목 기준, 2026-10-11)

항목 번호는 `docs/MarkLens_작업가이드_*.md`의 분배 계획을 따릅니다.
상태: 완료 / 부분 / 미착수 / 보류.

| 항목 | 담당 | 상태 | 위치 | 비고 |
|---|---|---|---|---|
| 공통 축 함수 규약 `ml/src/axes/` | 다빈 | 완료(X1·X2 문자·X3·X4) | `ml/src/axes/` | 2026-10-08 X2 문자 외관(철자) `x2_ortho.py` 추가(`ml/tests/test_x2_ortho.py`) |
| 다빈-1 정답 데이터(심결 라벨표) | 다빈 | **완료(2026-10-11 마감 — 수집·자동 선별·LLM 이중 라벨·보강·사람 검증 37건·A≠B 규칙 처리·학습 전 사람 결정 4행; 남은 사람 결정은 표본 미처리 3행 — 통합 모델 설계 §6)** | `backend/scripts/trials_collect.py`(list/fetch/extract/sheet/show/label/confirm/review/sample/biblio/status), `backend/scripts/trials_kinds.json`, `backend/tests/test_trials_collect.py`(67건), `backend/scripts/trials_enrich.py`, `backend/tests/test_trials_enrich.py`(17건) | 2026-09-30 1~3단계(커밋 8fb53b0·f84e85d·6e24930) + 2026-10-01 4단계(규칙 공백 수정·큐레이션 보조·2차 배치, PR #29): 목록 129개월 42,474건, PDF·텍스트 843건(1차 373 + 시범 20 + 2차 450), `labels.csv` 1024행(자동 1등급 331: 거절 106·무효 30·권리범위 195), `curation_queue.csv` 355건. 호출 9월 924/950 · 10월 900/950. 라벨 도구(PR #30·#31)로 큐 355건(430행) LLM 이중 라벨링 완료(호출 0): 유사 225·비유사 140·제외 65, LLM A↔B 일치율 96%(414/430), LLM↔정규식 추정 80%, 재검토 큐 130행. 보강(2026-10-08, `feat/trials-enrich`): A·B 일치 350행의 상대 표장 상표명 320행(91%, 출원속보 번호 조회 138회 — 성공 138·0건 0·오류 0)·지정상품 유사군 매핑 63%(양쪽 187행)·`x4_goods`(유사 평균 0.44 · 비유사 0.32). 사람 검증·마감(2026-10-11, `feat/review-ui` → `feat/review-wrapup`): 검토 화면으로 표본 37/40 확인(LLM↔사람 97%), 명칭 검토 31, 약한 토큰 200, A≠B 16행 규칙 처리(A↔B 99%), 식별력 하락 14건 결정 → 유사 214·비유사 141·제외 75 → 학습 전 사람 결정 4행 제외(심결 미대비 2·상대 번호 오류 2) → 유사 210·비유사 141·제외 79, 학습 특징 351행 — 아래 "정답 데이터" 소절 |
| 다빈-2 호칭 X1 | 다빈 | **완료** | `ml/src/axes/x1_phonetic.py`, `korean_brands.py`, `ml/tests/test_axes.py`(123건), `docs/MarkLens_X1_호칭유사도_설계.md` | PR #21·#22. v1.5(2026-09-30, `normalize_name` 공개 — X3와 정규화 공유). v1.6(2026-10-09): 식별력 없는 토큰만으로 된 이름은 포함 검사·분리관찰 대상에서 제외(2017후2697·2000후2453, Zorbix Gate/GATE `{gate}` 0.95→0.36). 최소 연결(`/phonetic-search`, `backend/src/core/phonetic_search.py`) |
| 다빈-3 식별력 필터 | 다빈 | **v0.3(2026-10-11 — 3호 사람 승인 반영 + 결합 규칙 v0.2·v0.3; 통합 모델 입력 `x1_d`·`x2_text_d`·`x3_d`·`any_no_distinctive` 로 연결, 서비스 미연결)** | `ml/src/axes/distinctiveness.py`, `ml/scripts/distinctiveness_build.py`, `shared/distinctiveness/`(`token_stats.json`·`weak_tokens.json`·`report.md`·`descriptive_terms.json`·`weak_token_overrides.json`), `ml/tests/test_distinctiveness.py`(40건), `ml/tests/test_descriptive_candidates.py`(2건), `docs/MarkLens_식별력_설계.md` | 판례 요소를 토큰 점수로: 33조1항 1·4·5·6호 0점, 3호 기술적 표장은 판례 기준 분류 초안 447 → 사람 승인 449항목(절대어 57 승인·12 해제, 상대어 380 전부 승인; 절대어 0·류 일치 0·상품 미상 0.5 상한), 2017후2697 다수 등록(심판 목록 42,474 + DB 1,100 제목의 출원인 수 A·등장 수 N), wordfreq 본질적 식별력, 유명 브랜드 235(갤럭시·오리온 추가) 1.0, 사람 검토 제외 7 토큰은 통계 약화만 건너뜀. 약한 토큰 1,527개(점수 < 0.5)를 X1·X2 철자·X3 의 `extra_generic` 으로, 요부 없는 이름은 전체 대비(2000후2453), 결합 규칙 v0.2(약한 토큰 2개 이상이 같은 순서로 양쪽에 있으면 요부 후보 — 2015후1690, 식별력 하락 14건 중 후보 13)·v0.3(붙여쓴 결합어 SLIMLINE·혹달린신발·QUICKPATH 대 띄어쓴 토큰열 — 철자·X1 읽기 동일 또는 유사도 ≥ 0.9, 2026-10-11). 심결례 전후 AUC 변화 CI 안(distinct_drop 14 → 8) — 설계 문서 §4·§4-1·§4-2·§6 |
| 다빈-4 변환표 검증 | 다빈 | **완료** | `shared/goods_map/README.md` §4 절차 | 2026-09-17 원본 xlsx로 91,591건·표본 10개 대조. 35류 병합 항목은 원 명칭을 `aliases`로 보존(PR #23) |
| 프론트-1 변경 시안 확정 | 지원 | 미착수 | — | 저장소에 시안 산출물 없음 |
| 프론트-2 상품↔유사군 변환표 | 지원 | 부분 | `shared/goods_map/`, `shared/types/goods.ts` | 파서·검증기 완료(PR #19), 원 명칭 aliases 보존(PR #23). 변환표 gz 포함(공공누리 제1유형, 출처표시, 2026-09-30 확인). aliases 보존·검증기 확장·테스트: 다빈 |
| 프론트-3 유명 로고 브랜드 목록 | 지원 | 부분 | `shared/famous_brands.txt` | DRAFT 39건(출원인명), 아직 수집 전. 2026-10-11 식별력 요부 판단용 브랜드 토큰 줄 4(갤럭시·GALAXY·오리온·ORION — 출원인 검색에는 쓰지 않음) |
| 프론트-4 화면 골격(3층 결과 화면) | 현수 | 완료 | `frontend/app/page.tsx`, `frontend/components/ResultView.tsx` | 이후 추가: 상표명 패널의 발음 유사·관념 유사 두 섹션(병렬 요청, 1회용 Turnstile 토큰을 발음 → 관념 순으로 소비), 결과 화면 분석 범위의 "호칭·관념 조회됨" 표시(PR #22·#26) |
| 프론트-5 백엔드 1차 연동 | 현수 | 완료 | `frontend/app/api/*`(BFF) | |
| 프론트-6 지정상품 입력 UI | 다빈 | **완료(범위 ②, v1.1)** | `frontend/components/GoodsPicker.tsx`(+테스트), `lib/goods.ts`, `SearchForm.tsx`·`ResultView.tsx`, `shared/goods_map/business_presets.json`, `GET /goods/search`(q 선택·offset·`presets`)·`/goods/classes`, BFF `frontend/app/api/goods/*` | 2026-09-21 API·zod 계약(PR #24) → 2026-10-01 화면(PR #27): 상품명 검색(디바운스 250ms·2글자·류 배지·고시 명칭·키보드) + 분류로 찾기 + 선택 칩(최대 20, 유사군 합집합). v1.1: 업종 세트 25개·79건(일상어 → 여러 류 묶음, 고시 13판 원본으로 확인·실제 gz 검증 경고 0) 카드와 "자주 찾는 업종" 칩 12개, 류 목록 상품/서비스 두 묶음(모바일 접힘), 유사군 풀이. 이름 확인·검색을 거쳐도 유지, 결과 화면 상단 요약. ③ `/search` 연동은 유사군 백필 후 |
| 프론트-7 관념 X3 | 다빈 | **완료(축 함수 v1.3 + 최소 연결)** | `ml/src/axes/x3_semantic.py`, `ml/tests/test_x3_semantic.py`(219건), `ml/scripts/x3_benchmark.py`, `docs/MarkLens_X3_관념유사도_설계.md`, `backend/src/core/semantic_search.py`, `backend/src/api/semantic_search.py`, `frontend/components/SemanticMatchesSection.tsx` | PR #25·#26(2026-09-30). MiniLM-L12-v2 + wordfreq 표제어 게이트(합성어 폴백, 영문 3자 이상, 1음절 명사 목록), 하한 0.55. `POST /semantic-search`(BFF `/api/semantic-search`)로 상표명 확인 패널에 연결, 관념 없는 입력은 안내 문구. 통합 모델 입력 `x3_d`(계수 0.17, CI 0 포함)로 학습에 포함, 검색 등급 반영은 서비스 연결 뒤 |
| 프론트-8 상품 견련성 X4 | 다빈 | **완료(축 함수)** | `ml/src/axes/x4_goods.py`, `ml/src/axes/goods_map.py`(로더), `backend/src/api/goods.py`(상품 검색 API), `ml/tests/test_x4_goods.py`, `docs/MarkLens_X4_상품견련성_설계.md` | 2026-09-21(PR #24). 서비스 적용은 DB 유사군 백필(현재 100/1,100건) 후 |
| 프론트-9 통합 모델·재보정 | 다빈 | **부분(v1.2.1 학습 완료 2026-10-11 — 모델 단계 마감, 서비스 미연결)** | `ml/src/model/risk_model.py`, `ml/scripts/train_risk_model.py`, `ml/requirements-experiments.txt`, `shared/model/risk_model_v1.json`, `ml/tests/test_risk_model.py`(10)·`test_train_risk_model.py`(7), `docs/MarkLens_통합모델_설계.md` §7~§7-2 | 2026-10-01 초안(판례 구조·로지스틱 회귀 입력·검증 계획). 2026-10-08~11 §4-1~§4-4 벤치마크·입력 정리. 2026-10-11 1차 학습(`feat/risk-model-v1`): 최종 라벨 351쌍, 변형 A/B × 쉬운 음성 가중치 {0, 0.25, 0.5} × C, 사건 단위 5겹×3반복 CV → 채택 B/w0.5/C0.3: 심결 AUC 0.625(0.57~0.68)·현실 분포 0.908(기준선 축 평균 0.593/0.908), 계수 x1 문자계 2.86·철자 0.95·상품 0.74·CLIP 0.07(0 과 구분 안 됨), 판례 검증 (i) 문자계 호칭 1.00 (ii) 도형계 외관 0.00 (iii) 상품 0.99 (iv) 요부 0.88, 등급 하한 0.093/0.187/0.740(위험 정밀도 0.80·검토 권장 재현율 0.90), 단독 임계값 전부 비활성(정밀도 0.9 미달). `risk_score(features) → (p, 등급, 기여도)`. v1.1(같은 날, `feat/risk-model-v1.1`): 유형 주효과·miss_x1·miss_x2text 제거(이름 없는 37행 제외, 314행), 결합 방법 비교(로지스틱 0.619 / 판례 사전분포+단조 0.618 / EBM 0.608 / 단조 GBM 0.626 — 전부 기준 CI 안) → 판례 사전분포(σ 0.5)+단조 로지스틱 채택, 판례 (i) 1.00 (ii) 0.01 (iii) 1.00 (iv) 1.00, 등급 하한 0.091/0.181/0.591(위험 정밀도 0.69), 단독 임계값(정밀도 0.7) x1_d 0.98·x2_text_d 0.75·x3_d 0.77 활성. v1.2(같은 날, `feat/risk-model-v1.2`): 절편 사전분포 제외(절편 −4.86, 요부 플래그 +0.88 로 교차표와 일치), 요부 플래그 → `any_no_distinctive` + x1_d×any_no_distinctive(−1.10, 판례 (iv) 0.92), 도형 보류 규칙(figure_caveat·x2_whole ≥ 0.9 검토 권장, 미검증), 쉬운 음성 표본 50건 혼동 가능 0 → 임계 0.8 유지; 심결 AUC 0.621·현실 0.895(CI 안), 위험 하한 0.899(정밀도 0.82, 11쌍). v1.2.1(같은 날, `chore/model-phase-wrapup`): "위험" 최소 지지 10 → 30(위험 하한 0.899 → 0.563 대체값, 정밀도 0.69·159쌍·재현율 0.05 → 0.58), σ CV 격자 → 1.0 고정(x1_d CI 0.56~3.59 → 1.01~2.71), 심결 AUC 0.619·현실 0.897(CI 안). 다음: "다음 단계" 절(서비스 연결, 11월 도형상표 수집) |
| X2 외관 벤치마크(심결 이미지 쌍) | 다빈 | 부분(v0 기준선 + v1 ① 요부 분리) | `ml/scripts/trials_extract_images.py`, `ml/scripts/x2_benchmark.py`, `ml/scripts/x2_split.py`, `ml/scripts/x2_variants.py`, `ml/tests/test_trials_extract_images.py`·`test_x2_benchmark.py`·`test_x2_split.py`·`test_x2_variants.py`(52건), `docs/MarkLens_X2_외관_설계.md` | 2026-10-08 v0: 심결문 PDF에서 양쪽 표장 이미지를 뽑아 제목에 연결(QA 시트 30쌍 눈 확인) → LLM 라벨이 붙은 이미지 쌍 286/350행(82%). 현재 CLIP 코사인의 ROC AUC 전체 0.51 · 판단축 외관 0.62 — 섞은 라벨 0.50. v1 ①(같은 날): 소형 기준 32px → 306쌍, 결론 대신 **표장 라벨**(유사 189·비유사 95·제외 22), 부트스트랩 95% CI, easyocr로 문자·도형 영역 분리(유형 일치 76%, OCR 완전 일치 51%). 철자 유사(`x2_text_ortho`) 외관축 AUC 0.72(0.57~0.86), 전체 이미지 0.63, 도형 크롭은 쌍 80·도형 29로 판단 보류, 사진 표장에서는 역전. v1 ②(`x2_variants.py`): 전체 이미지 변형 5종(흑백·윤곽선·다중 해상도·DINOv2·앙상블) 모두 채택 없음(최대 외관축 +0.026, CI 겹침), OCR 노이즈 진단은 ±0.01(철자 신호 상한은 신호 자체), 유형 게이팅 `x2_gate` 외관축 0.70(잠정 후보). 서비스 반영은 "다음 단계"의 X2 v2 재설계(철자 축 `x2_text_d` + 전체 이미지 CLIP, 도형계 caveat)로 — X2 설계 §10 은 결정 대기. 데이터는 `ml/data/trials/`(비공개) |
| 축별 벤치마크(심결례 4축 특징) | 다빈 | 완료(측정 v1 + 10-09·10-11 재측정 — 통합 모델 v1.2.1 의 학습 입력) | `ml/scripts/pairs_features.py`, `ml/scripts/axes_benchmark.py`, `ml/src/axes/x2_ortho.py`, `ml/tests/test_pairs_features.py`·`test_axes_benchmark.py`·`test_x2_ortho.py`(119건) | 2026-10-08(`feat/axes-benchmark`): 라벨 일치 350쌍에 X1·X2 문자(철자)·X2 CLIP(전체·도형 크롭)·X3(실제 모델)·X4 점수와 결측 플래그 → `pairs_features.csv`. 표장 라벨 ROC AUC (a) 전체 / (b) 판단축 포함: X1 0.54/0.54, X2 철자 0.50/0.65, X2 CLIP 전체 0.49/0.63, X3 0.50/0.53(게이트 켜짐 75쌍뿐), X4 0.60(최종 라벨, 거절결정불복 0.83). 정밀도 0.9 단독 임계값 없음, X1↔X2 철자 ρ 0.63. 낮은 원인: 식별력 없는 공통 부분(GATE/GATE 비유사)을 분리관찰이 1.0 으로, 본문·OCR 명칭 오추출, 경계 사례 편중 — [통합 모델 설계 §4-1](docs/MarkLens_통합모델_설계.md). 2026-10-09 세 원인 처리 후 재측정(§4-2): 상대 명칭 LLM 추출(176/183행, 기존과 불일치 116) → X1 0.60·X2 철자 외관축 0.73; 식별력 v0 `x1_d` 등 +0.01 안; 쉬운 음성 700쌍(교차 350·DB 350, `--easy-negatives`/`--with-easy-negatives`)을 더한 현실 분포에서 X1 0.90·X2 철자 0.83·X4 0.81. 2026-10-11 마감 재측정(§4-3, 355행 — `유사여부_확정` 기준, pass b 일치 불요): X1 0.59·X2 철자 0.56(외관축 0.73)·X3 0.50·X4 0.60, 식별력 v0.2 `_d` 축 CI 안, 현실 분포 X1 0.89·X2 철자 0.82·X4 0.81. 학습 전 입력 정리 뒤(§4-4, 351행): X1 0.59(`x1_d` 0.60)·X2 철자 0.56(`x2_text_d` 0.58, 외관축 0.73)·X3 0.50·X4 0.60(n 184), 현실 분포 X1 0.89·X2 철자 0.83·X3 0.58·X4 0.82 — 모두 CI 안 |
| 백엔드-1 PostgreSQL 설계 | 현수 | 완료 | `backend/migrations/001_init.sql` | |
| 백엔드-2 JSON→DB 마이그레이션 | 현수 | 완료 | `backend/scripts/migrate_json_to_db.py` | |
| 백엔드-3 이미지 S3 | 현수 | 보류 | `backend/src/core/storage.py` | 로컬 심 계층 + 경로 오버라이드만 |
| 백엔드-4 검색-DB 연결 | 현수 | 완료 | `backend/src/core/engine.py` db 모드 | |
| 백엔드-5 수집 스크립트 | 현수 | 완료 | `backend/scripts/collect_pipeline.py` | 출원인명 검색 |
| 백엔드-6 데이터 확장 | 현수 | 완료 | `docs/MarkLens_데이터확장_실행계획_2026-08.md` | 현재 1,100건 세대(2026-08-27) |
| 백엔드-7 상표명 실시간 확인 | 현수 | 완료 | `backend/src/api/namecheck.py` | |
| 백엔드-8 다축 오케스트레이션 | 현수 | 미착수 | — | 축 함수·식별력 필터·통합 모델 v1.2.1 준비됨 — "다음 단계" 서비스 연결 |
| 백엔드-9 3입력·4축 응답 | 현수 | 미착수 | — | "다음 단계" 서비스 연결(3입력 `/search`·위험도·근거 축·요부·도형 caveat) |

네 가지를 분명히 해 둡니다.

- 검색 입력은 **아직 이미지 1개**입니다(`POST /search`는 `file`과 `top_k`만 받음).
- 상표명 확인(`/name-check`)은 검색과 분리된 별도 기능이며 검색 점수에 영향을 주지 않습니다.
- X1은 `POST /phonetic-search`로 최소 연결되어 상표명 확인 패널에 발음 유사 후보를 보여 줍니다. 검색 점수·등급에는 반영되지 않습니다(통합 모델 v1.2.1 은 학습을 마쳤고 서비스 연결은 "다음 단계").
- X3는 같은 방식으로 `POST /semantic-search`에 연결되어 같은 패널에 관념 유사 후보(최대 5건, 하한 0.55)를 보여 줍니다. 기동 시 DB 상표명 중 관념이 있는 515건을 임베딩해 캐시하며 `MARKLENS_X3_ENABLED=0`이면 이 엔드포인트만 503입니다.

## 다음 단계 (2026-10-11 모델 단계 마감 기준)

모델 단계(정답 데이터 → 축별 벤치마크 → 식별력 → 통합 모델 v1.2.1)는 여기서 닫습니다. 남은 일은 두 갈래입니다.

1. **서비스 연결** — `POST /search` 를 3입력(이미지 + 상표명 + 지정상품)으로 확장하고(백엔드-8·9, 프론트-6 ③),
   X2 를 v2 로 재설계(현재 CLIP 단독 4상태 → 철자 축 `x2_text_d` + 전체 이미지 CLIP, 유형별 가중), 후보마다 통합 모델의
   위험도 p·등급 4단계·근거 축 기여도·요부(식별력 필터가 떼어낸 약한 토큰)를 표시하고, 도형계 입력에는 `figure_caveat`
   문구("도형 유사는 검증 데이터가 적어 참고용")를 함께 보여 줍니다. 단독 임계값(호칭 0.98·철자 0.75·관념 0.77)이 걸리면
   등급 하한 "검토 권장". 등급 명칭·유형 판정·이름 없는 쌍 표시 같은 결정 대기 항목은
   [통합 모델 설계 §6](docs/MarkLens_통합모델_설계.md)에 사유와 함께 있습니다. engine·API 는 모델 단계에서 손대지 않았습니다.
2. **11월 도형상표 우선 수집·도형 규칙 τ 검증** — 심결례 대기열 621건(11월 KIPRIS 예산)에서 도형·결합-도형요부 사건을
   먼저 받아 도형계 쌍(현재 이름 있는 17, x2_whole ≥ 0.9 는 0건)을 늘리고, 도형 보류 규칙의 τ 0.9 와 판례 조건 (ii)
   (도형계 외관 > 호칭, 현재 불성립)를 검증한 뒤 재학습합니다. "위험" 등급 정밀도 0.8 을 지지 30 에서 채우는 것도
   표본 확대 뒤의 일입니다.

## 구조

```text
Browser
  -> Next.js same-origin BFF (/api/search, /api/name-check, /api/phonetic-search, /api/semantic-search, /api/goods/search, /api/goods/classes, /api/images, /api/health, /api/turnstile-config)
  -> private FastAPI
  -> OpenCLIP + FAISS index
  -> PostgreSQL / KIPRIS Plus
```

- `frontend/`: Next.js UI, 수동 크롭, Turnstile 검증, BFF(`app/api/*`)
- `backend/`: FastAPI, 업로드 검증, 검색·명칭 확인·발음 유사도·관념 유사도·상품 검색 API(`src/api/`), 기동 시 캐시(`src/core/phonetic_search.py`·`semantic_search.py`)와 변환표(`src/core/goods.py`), KIPRIS 수집 스크립트(`scripts/`), 심결례 수집·보강 스크립트(`scripts/trials_collect.py`·`trials_enrich.py`)
- `ml/`: 전처리, 임베딩, 검색, 점수, 인덱스 빌드, 평가 도구
- `ml/src/axes/`: 다축 모델의 축 함수 — X1 호칭 유사도(`x1_phonetic.py`, 브랜드·지명 로마자표 `korean_brands.py`), X3 관념 유사도(`x3_semantic.py`), X4 상품 견련성(`x4_goods.py`), 변환표 로더(`goods_map.py`)
- `ml/evaluation/`: 200-pair 라벨링 팩과 강건성 평가 계약
- `shared/`: 프런트·백엔드 공용 자산 — `goods_map/`(상품↔유사군 변환표 파서·검증기, 변환표 `goods_map.json.gz` 1.86MB 저장소 포함), `famous_brands.txt`(유명 브랜드 출원인 목록 DRAFT), `types/goods.ts`(변환표 타입)
- `scripts/`: 개발 서버 통합 시작·종료(`dev-start.sh`/`.ps1`, `dev-stop.sh`/`.ps1`)
- `deploy/`, `compose.production.yml`: 공개 배포 준비 템플릿
- `docs/`: API, 보안·운영, 모델·데이터, 설계 문서 — 색인은 [`docs/README.md`](docs/README.md)
- `.github/workflows/ci.yml`: CI 3잡

## 로컬 실행

### 0. 새 컴퓨터 사전 준비

| 도구 | 버전 | 비고 |
| --- | --- | --- |
| Python | 3.11 | 3.13은 `numpy<2` 휠이 없어 설치 실패 |
| Node.js | 20.19 이상 (LTS 권장) | `frontend/package.json`의 engines 기준. CI는 Node 22 |
| PostgreSQL | 16 | **db 모드를 쓸 때만** 필요. `DATABASE_URL`을 설정하지 않는 file 모드는 설치 불필요 |

PostgreSQL 설치 예시: Windows `winget install PostgreSQL.PostgreSQL.16` /
macOS `brew install postgresql@16` / Ubuntu `sudo apt install postgresql-16`.

- 최초 부팅 시 CLIP 가중치(ViT-B-32 laion2b, 약 578MB)를 사용자 홈의
  huggingface 캐시로 자동 다운로드하므로 인터넷 연결이 필요합니다.
- X3 관념 축 모델(paraphrase-multilingual-MiniLM-L12-v2, 약 480MB)도 첫 기동 때 같은
  캐시로 자동 다운로드합니다. 받지 않으려면 `.env`에 `MARKLENS_X3_ENABLED=0`을 둡니다
  (`/semantic-search`만 503, 나머지는 동일 — 아래 3. 백엔드의 실측 표).
- CLIP 가중치 로드에 시스템 커밋 메모리 여유가 약 5GB 필요합니다. 부족하면
  서버가 로그 없이 종료됩니다 —
  [`docs/MarkLens_트러블슈팅.md`](docs/MarkLens_트러블슈팅.md)의 TS-07 참고.

### 1. Python 환경

Python 3.11을 사용합니다. Windows PowerShell 예시:

```powershell
py -3.11 -m venv ml\venv
ml\venv\Scripts\python.exe -m pip install `
  torch==2.13.0 torchvision==0.28.0 `
  --index-url https://download.pytorch.org/whl/cpu
ml\venv\Scripts\python.exe -m pip install setuptools==83.0.0
ml\venv\Scripts\python.exe -m pip install -c constraints.txt `
  -r ml\requirements.txt `
  -r backend\requirements.txt `
  -r backend\requirements-dev.txt
```

macOS/Linux(bash) 예시:

```bash
python3.11 -m venv ml/venv
ml/venv/bin/python -m pip install \
  torch==2.13.0 torchvision==0.28.0 \
  --index-url https://download.pytorch.org/whl/cpu
ml/venv/bin/python -m pip install setuptools==83.0.0
ml/venv/bin/python -m pip install -c constraints.txt \
  -r ml/requirements.txt \
  -r backend/requirements.txt \
  -r backend/requirements-dev.txt
```

`setuptools==83.0.0` 단계는 CI(`.github/workflows/ci.yml`)·컨테이너 빌드
(`deploy/backend.Dockerfile`)와 동일한 순서입니다. 고정 버전은 `constraints.txt`에
있습니다(torch 2.13.0, faiss-cpu 1.14.3, open_clip_torch 2.32.0, sentence-transformers 6.1.0,
wordfreq 3.1.1, httpx2 2.13.0). 새 의존성은 `constraints.txt`에 정확한 버전으로 고정한 뒤
`requirements`에 범위로 적는 것이 원칙입니다(CI가 `-c constraints.txt`로 설치).

`ml/data/`는 Git에 포함되지 않습니다. 최소한 다음 파일이 필요합니다.

```text
ml/data/index/kipris.faiss
ml/data/index/kipris_metadata.json
ml/data/kipris_metadata.json
ml/data/images/*
```

새 인덱스는 `kipris_manifest.json`까지 생성해야 합니다. production 모드는
manifest가 없거나 모델·전처리·해시 계약이 다르면 기동하지 않습니다.

#### ml/data 입수와 머신 간 이전

`ml/data/`는 저작권 문제로 이 공개 저장소에는 포함되지 않으며, 팀 전용
private 저장소 <https://github.com/jhsoo0211/marklens-data> 로 관리합니다
(협업자 권한 필요, 공개 재배포 금지).

입수 방법(셋 중 하나):

- **A. git clone(권장)** — 프로젝트 루트에서
  `git clone https://github.com/jhsoo0211/marklens-data.git ml/data`.
  이후 갱신은 `git -C ml/data pull`로 받습니다.
- **B. GitHub ZIP** — 저장소 페이지의 Code → Download ZIP을 받아 풀면
  `marklens-data-main/` 폴더가 나옵니다. 그 안의 내용물(`images/`, `index/`,
  `kipris_metadata.json` 등)이 프로젝트 루트의 `ml/data/` 바로 아래에 오도록
  옮깁니다(최종 경로 예: `ml/data/index/kipris.faiss`).
- **C. 팀 공유 압축본(오프라인 폴백)** — 데이터가 있는 머신에서 압축해 전달:
  - PowerShell: `Compress-Archive -Path ml\data -DestinationPath marklens-data.zip`
  - bash: `zip -r marklens-data.zip ml/data`

  새 머신의 프로젝트 루트에 같은 구조(`ml/data/...`)로 풉니다.

배치 후 공통 절차:

1. file 모드는 그대로 기동하면 됩니다. db 모드는 먼저 DB에 적재합니다:
   `ml\venv\Scripts\python.exe -m backend.scripts.migrate_json_to_db --prune`
2. 서버 기동 후 `/health`의 `index_size`·`trademark_count`·
   `artifact_generation_id`가 원본 머신과 같은지 확인합니다.

주의사항:

- `ml/data/kipris_call_count.json`은 KIPRIS 월 쿼터 카운터입니다. 머신 간 값이
  병합되지 않으므로 실제 수집을 수행한 머신의 값이 정본이며, 더 낮은 값으로
  덮어쓰면 안 됩니다. 같은 이유로 데이터 저장소에서는 `.gitignore`로 제외되어
  있습니다 — 새 머신에 이 파일이 없어도 서빙은 되지만, **실제 수집은 정본
  카운터가 있는 머신에서만** 수행하세요(없는 머신에서 수집하면 카운터가 0부터
  시작해 월 쿼터를 초과 사용하게 됩니다).
- 현재 세대는 2026-08-27 생성 1,100건(generation `20260827T035002Z-25f84a6eeb26`,
  데이터 저장소 커밋 `61bd6a2`)입니다. 위 A/B 방법으로 받으면 됩니다. 2026-06의
  100건 세트는 태그 `v0.1-semester1`(1학기 종료 기준선, `a4e3f11`) 시점의
  데이터이며 현재 세대와 호환되지 않습니다.

이전 후 확인 목록(원본 머신과 대조):

- [ ] `/health`의 `artifact_generation_id` 일치
- [ ] `index_size` == `trademark_count` == 기대 건수
- [ ] db 모드: `migrate_json_to_db --prune` 후 재기동 시 키 불일치 오류 없음
- [ ] production 모드 기동은 `kipris_manifest.json`이 있어야 가능
- [ ] 검색 스모크: 인덱스에 있는 이미지 1건 업로드 시 자기일치 유사도 ≈ 1.0

#### Apple Silicon(M1 이후) 주의

- **서버는 그대로 뜹니다.** 2026-09-17 #18에서 `backend/src/core/engine.py`가
  `src.embedding`(torch)을 `faiss`보다 먼저 import하도록 고쳐 CLIP 워밍업 시
  SIGSEGV(exit 139)가 사라졌습니다(같은 날 이 순서로 `/health` 정상, 옛 순서는
  여전히 exit 139 재현). 이 import 순서는 `# noqa: I001`로 고정돼 있으니 자동
  정렬로 되돌리지 마세요.
- **`pytest`도 변수 없이 돕니다(2026-09-18 해결).** 이전에는 테스트 수집 단계에서
  `backend/tests/conftest.py`·`ml/tests/test_search.py`가 faiss를 먼저 올려 같은
  충돌이 나(`ml/tests/test_embedding.py`에서 exit 139) `OMP_NUM_THREADS=1` 우회가
  필요했습니다. 이제 `ml/src/search.py`가 torch를 faiss보다 먼저 import하고
  `ml/tests/conftest.py`·`backend/tests/conftest.py`도 torch를 선행 import하므로
  변수 없이 전체 pytest가 통과합니다. ML 스크립트는 모두 `src.search`를 통해
  faiss를 올리므로 별도 조치가 필요 없습니다. 이 순서들도 `# isort: split`·
  `# noqa`로 고정돼 있으니 자동 정렬로 되돌리지 마세요.
- Linux·Windows·CI에는 해당 없습니다.

### 2. 환경변수

백엔드는 루트 `.env`, 프런트는 `frontend/.env.local`을 읽습니다. 백엔드는 `.env`
없이 file 모드로 뜨고(이미지 검색만 쓸 때 필수 값 없음), 프런트는 `.env.local`에
dev bypass 한 줄만 있으면 됩니다.

| 값 | 어디에 | 언제 필요 |
|---|---|---|
| `KIPRIS_ACCESS_KEY` | `.env` | 상표명 확인(`/name-check`)과 데이터 수집. 월 1,000회 한도, 각자 발급 |
| `DATABASE_URL` | `.env` | PostgreSQL db 모드. 비우면 JSON file 모드 |
| `MARKLENS_TURNSTILE_DEV_BYPASS=1` | `frontend/.env.local` | 실제 Turnstile 키 없이 로컬 UI를 쓸 때. production에서는 무시됨 |
| `MARKLENS_X3_ENABLED` | `.env` | 관념 유사도(`/semantic-search`)를 끌 때 `0`. 기본 `1`(기동 시 임베딩 캐시). 하한은 `MARKLENS_X3_MIN_SCORE`(0.55), 한도 `MARKLENS_X3_RATELIMIT`(30/minute) |
| `KIPRIS_TRIAL_ACCESS_KEY` 등 `KIPRIS_TRIAL_*` | `.env`(`.env.example` 참고) | 심결례 수집. 출원속보 키·예산과 분리(월 950·일 300 기본, 카운터 `ml/data/trials/quota.json`) — 아래 "정답 데이터" 소절 |

전체 목록과 설명은 `.env.example`(백엔드)과 `frontend/.env.example`(프런트)에
있습니다.

```powershell
Copy-Item .env.example .env
Copy-Item frontend\.env.example frontend\.env.local
```

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env.local
```

비밀값은 Git에 커밋하지 마세요. KIPRIS URL은 HTTPS만 허용됩니다.
필요한 신청 상품과 장애 점검 순서는
[`docs/MarkLens_KIPRIS_API_신청가이드.md`](docs/MarkLens_KIPRIS_API_신청가이드.md)를
참고하세요.

### 3. 백엔드

반드시 프로젝트 루트에서 실행합니다.

```powershell
ml\venv\Scripts\python.exe -m uvicorn backend.src.main:app `
  --host 127.0.0.1 --port 8000 --reload
```

```bash
ml/venv/bin/python -m uvicorn backend.src.main:app \
  --host 127.0.0.1 --port 8000 --reload
```

- 상태: `http://127.0.0.1:8000/health`
- OpenAPI: `http://127.0.0.1:8000/docs`

기동 순서는 CLIP·FAISS 인덱스 → X1 발음 캐시(942건) → 변환표(91,591건) → X3 관념 임베딩
캐시(515건)입니다. 로그에 `X1 발음 캐시 준비: 942건`, `상품 변환표 준비: 91591건`,
`X3 관념 캐시 준비: 515건`이 찍히면 준비가 끝난 것입니다. 2026-09-30 실측(Apple Silicon Mac,
실제 1,100건 인덱스, 모델 캐시 후):

| `MARKLENS_X3_ENABLED` | 기동 시간 | 기동 후 RSS | 비고 |
|---|---|---|---|
| `1`(기본) | 11.4초 | 1.96GB | X3 캐시 6.4초 포함. 첫 실행은 MiniLM 다운로드(약 480MB)가 더 걸림 |
| `0` | 4.1초 | 1.31GB | `/semantic-search`만 503 + 이유, 나머지 엔드포인트 동일 |

### 4. 프런트엔드

```powershell
Copy-Item frontend\.env.example frontend\.env.local
Set-Location frontend
npm ci
npm run dev
```

```bash
cp frontend/.env.example frontend/.env.local
cd frontend
npm ci
npm run dev
```

브라우저는 FastAPI 주소나 서버 키를 직접 알지 않습니다. Next BFF가 서버 전용
`MARKLENS_BACKEND_URL`과 `MARKLENS_BACKEND_API_KEY`를 사용합니다. 로컬 기본값은
백엔드 `http://127.0.0.1:8000`입니다.

실제 Turnstile 키 없이 로컬 UI를 확인할 때는 `frontend/.env.local`에
`MARKLENS_TURNSTILE_DEV_BYPASS=1` 하나만 켭니다(위젯 설정 라우트와 서버 검증이
같은 값을 읽습니다). production에서는 이 bypass가 무시됩니다.

### 5. 두 프로세스를 한 번에

`scripts/`의 헬퍼가 백엔드(8000)와 프런트(3000)를 함께 띄우고 `/health`가
준비될 때까지 기다립니다. 파일에 실행 비트가 없으므로 bash로 호출합니다.

```bash
bash scripts/dev-start.sh     # --force: 포트 점유 프로세스 종료 후 진행
bash scripts/dev-stop.sh
```

```powershell
.\scripts\dev-start.ps1       # -Force, -NoBrowser
.\scripts\dev-stop.ps1
```

### 6. 모델 단계 스크립트 (KIPRIS 호출 0)

정답 데이터·식별력·통합 모델은 서비스 기동과 무관한 스크립트입니다. 입력 `ml/data/trials/`(비공개 데이터 저장소)가 있어야
하고, 산출물 중 저장소에 들어가는 것은 `shared/distinctiveness/*`와 `shared/model/risk_model_v1.json`뿐입니다.

```bash
# 심결례 사람 검토 웹 화면(개발 전용, http://127.0.0.1:8010, --port) — review --bundle 산출물을 카드로.
# 저장은 trials_collect 의 label·confirm·name-b 함수와 distinctiveness 의 승인·제외 함수만 거친다
ml/venv/bin/python -m backend.scripts.review_ui
ml/venv/bin/python -m backend.scripts.trials_collect status            # 라벨 집계·일치율·검토 묶음 처리/행

# 식별력 재집계(3~4초) → 특징 재생성(실제 X3 모델, 약 20초) → 4축 벤치마크(심결 + 현실 분포)
ml/venv/bin/python ml/scripts/distinctiveness_build.py
ml/venv/bin/python ml/scripts/pairs_features.py --easy-negatives
ml/venv/bin/python ml/scripts/axes_benchmark.py --with-easy-negatives

# 통합 모델 v1.2.1 재학습(기본 logistic·prior 2방법 약 8초) → shared/model/risk_model_v1.json + ml/data/trials/risk_model_v1_{report.md,results.json,calibration.png}
ml/venv/bin/python ml/scripts/train_risk_model.py
ml/venv/bin/python ml/scripts/train_risk_model.py --bootstrap 20 --repeats 1     # 빠른 확인
ml/venv/bin/python ml/scripts/train_risk_model.py --methods logistic,prior,ebm,gbm   # 비교 실험(아래 주의)
```

주의 — `--methods` 에 EBM·GBM 을 넣으려면 `ml/requirements-experiments.txt`(interpret-core·lightgbm·shap)를 반드시
`pip install -c constraints.txt -r ml/requirements-experiments.txt` 로 설치합니다(`-c` 없이 설치하면 numpy 가 2.x 로 올라가
서비스가 깨집니다). macOS 는 `brew install libomp` 가 먼저 필요하고, lightgbm 과 torch 를 한 프로세스에 올리면 SIGSEGV 가
나므로 학습 스크립트는 torch 를 import 하지 않으며 해당 테스트는 서브프로세스로 돕니다. 서비스·CI 에는 이 의존성이 없습니다.

### 졸업과제 시연·평가는 여기까지면 됩니다

file 모드(`DATABASE_URL` 없음) + Turnstile dev bypass로 검색·상표명 확인·발음/관념 유사
후보 화면을 모두 시연할 수 있습니다. Docker, Nginx, PostgreSQL, 실제 Turnstile 키는 공개
배포용이며 로컬 평가에는 필요 없습니다. 상표명 확인만 KIPRIS 키가 있어야 합니다.

## API 요약

정식 브라우저 경계는 same-origin `/api/*`입니다. FastAPI 직접 호출은 로컬 개발과
내부 서비스 통신용입니다.

| 경로 | 용도 | 한도(백엔드 IP 기준 기본값) |
|---|---|---|
| `POST /api/search?top_k=5` | Turnstile 검증 후 이미지 검색 프록시 | 백엔드 한도 적용(아래) |
| `POST /api/name-check` | `{ "name": "...", "turnstileToken": "..." }` 명칭 확인 프록시 | 〃 |
| `POST /api/phonetic-search` | `{ "name": "...", "turnstileToken": "...", "top_k"?: 1..20 }` X1 발음 유사 후보 프록시 | 〃 |
| `POST /api/semantic-search` | `{ "name": "...", "turnstileToken": "...", "top_k"?: 1..5 }` X3 관념 유사 후보 프록시 | 〃 |
| `GET /api/goods/search?q=&limit=&offset=&nice_class=` | 상품↔유사군 변환표 검색 프록시(프론트-6). `nice_class`가 있으면 `q` 생략 가능(류 목록). 읽기 전용이라 Turnstile 불필요 | 〃 |
| `GET /api/goods/classes` | NICE 45개 류 명칭·변환표 항목 수 프록시(성공 응답 1시간 캐시) | 〃 |
| `GET /api/health` | 외부용 BFF·FastAPI 준비 상태 | — |
| `GET /api/images/{path}` | 결과 이미지 프록시 | 〃 |
| `GET /api/turnstile-config` | 위젯 사이트 키·dev bypass 설정 전달 | — |
| `GET /health` | 내부 FastAPI 엔진·인덱스 상태 | 없음 |
| `POST /search` | 내부 이미지 검색 API (`file`, `top_k`) | 10/minute (`MARKLENS_SEARCH_RATELIMIT`) |
| `POST /name-check` | 내부 명칭 확인 API(KIPRIS 실시간) | 30/minute (`MARKLENS_NAMECHECK_RATELIMIT`) + KIPRIS 월 예산 |
| `POST /phonetic-search` | 내부 X1 호칭 유사도 검색 (`name`, `top_k` ≤ 20). 로컬 DB 계산, KIPRIS 무관 | 30/minute (`MARKLENS_PHONETIC_RATELIMIT`) |
| `POST /semantic-search` | 내부 X3 관념 유사도 검색 (`name`, `top_k` ≤ 5). 기동 시 임베딩 캐시, `MARKLENS_X3_ENABLED=0`이면 503 | 30/minute (`MARKLENS_X3_RATELIMIT`) |
| `GET /goods/search` | 내부 상품 검색 (`q` 1~50자, `limit` 1~50, `offset` 0 이상, `nice_class` 1~45). `q` 없이 `nice_class`만 주면 그 류의 항목을 이름순으로 나열, 둘 다 없으면 422. 변환표 파일 없으면 503 | 60/minute (`MARKLENS_GOODS_RATELIMIT`) |
| `GET /goods/classes` | 내부 NICE 45개 류 목록 | 60/minute (〃) |
| `GET /images/{key}` | 인덱스에 포함된 결과 이미지만 제공. `MARKLENS_PUBLIC_RESULT_IMAGES=true`(로컬 기본)일 때만 등록 | 120/minute (`MARKLENS_IMAGES_RATELIMIT`) |
| `GET /docs` | Swagger UI | 없음 |

production compose의 gateway는 여기에 사용자별 검색 5회/분·명칭 확인 2회/분 제한을 더합니다
(아래 "공개 배포 준비").

검색의 정식 판정 필드는 `grade.status_code`입니다.

- `STRONG_MATCH`: 매우 가까운 시각 후보
- `POSSIBLE_MATCH`: 가까울 수 있는 시각 후보
- `WEAK_MATCH`: 약한 시각 후보
- `NO_CLOSE_MATCH`: 현재 비교 표본에서 가까운 후보 미확인

`NO_CLOSE_MATCH`는 안전 판정이 아닙니다. `grade_code`와 `grade_name`은 기존
클라이언트를 위한 deprecated 필드이며 다음 계약 버전에서 제거할 예정입니다.
전체 요청·응답과 오류 계약은 [API 계약](docs/MarkLens_API계약_v1.md)에 있습니다.
그 문서의 `GET /name-check` 호환 경로 서술은 낡았습니다 — 해당 라우트는 현재
코드에 없습니다.

## 다축 모델과 축 함수

| 축 | 내용 | 상태 |
|---|---|---|
| X1 호칭 | 두 상표명의 발음 유사도. 판례 5규칙(호칭 최우선, 첫음절 강세, 여러 호칭 중 최댓값, 외국어의 국내 발음, 한영 병기 시 한글 우선) | **완료(v1.6)** — 서비스 연결(`/phonetic-search`, 검색 등급에는 미반영). 심결 AUC 0.59(식별력 적용 `x1_d` 0.60)·현실 분포 AUC 0.89 — 통합 모델 계수 1.81(+문자계 2.26), 통합 모델 설계 §4-4 |
| X2 외관 | OpenCLIP ViT-B/32 임베딩 + FAISS 코사인 검색 | 완료 — 현재 서비스. 심결 이미지 쌍 벤치마크(2026-10-08): v0 286쌍 AUC 0.51·외관축 0.62, v1 ① 표장 라벨·요부 분리 — 철자 유사 외관축 0.72, v1 ② 전체 이미지 변형 5종 채택 없음·유형 게이팅 0.70(잠정). 전체 이미지 CLIP `x2_whole` 심결 AUC 0.49(외관축 0.63)·현실 분포 0.86(통합 모델 기준선; 계수 0.21, 도형계 효과 0 — caveat). "다음 단계" X2 v2 = 철자 + 이미지. 문자 외관(철자) 축 함수 `ml/src/axes/x2_ortho.py`(2026-10-08: X1 정규화 + 자모 편집거리, 심결례 350쌍 상표명 기준 외관축 AUC 0.65) — [X2 외관 설계](docs/MarkLens_X2_외관_설계.md) §9 |
| X2 문자 외관(철자) | 상표명 문자열의 철자 유사(X1 정규화 토큰 + 자모 편집거리, `ml/src/axes/x2_ortho.py`). 결합상표의 문자 부분을 이미지와 별도로 본다 | **라이브러리 완료(2026-10-08)** — 심결 AUC 0.56(외관축 0.73; 식별력 적용 `x2_text_d` 0.58)·현실 분포 AUC 0.83, 통합 모델 계수 1.09, 서비스 미연결 — [X2 외관 설계](docs/MarkLens_X2_외관_설계.md) §9 |
| X3 관념 | 상표명 의미를 다국어 문장 임베딩(paraphrase-multilingual-MiniLM-L12-v2)의 코사인으로 비교(DB 200쌍 기준선으로 재보정). 관념 게이트(wordfreq 빈도표)로 조어·기호는 결측 | **완료(v1.3)** — 서비스 연결(`/semantic-search`, 검색 등급에는 미반영). 심결 AUC 0.50(`x3_d` 0.51; 게이트 켜진 쌍만)·현실 분포 AUC 0.58 — 통합 모델 계수 0.17(CI 0 포함) |
| X4 상품 견련성 | 유사군 코드 집합 간 자카드 계수 | **완료** — 라이브러리(서비스 적용은 DB 유사군 백필 후). 심결 AUC 0.60(n 184)·현실 분포 AUC 0.82 — 통합 모델 계수 1.43 |
| 식별력·요부 필터 | 상표명 토큰의 식별력 점수(33조1항 1·3·4·5·6호 0점, 다수 등록 A·N, 일반어 빈도, 유명 브랜드 1.0)로 약한 토큰을 X1·X2 철자·X3 의 `extra_generic` 으로 넘기고, 요부 없는 이름은 전체 대비, 약한 토큰 결합은 요부 후보(`ml/src/axes/distinctiveness.py`) | **v0.3(2026-10-11)** — 3호 기술적 표장 449항목 사람 승인, 결합 규칙 v0.2·v0.3. 심결 AUC 효과는 CI 안(`_d` 축 X1 0.59 → 0.60·X2 철자 0.56 → 0.58·X3 0.50 → 0.51, 현실 분포 같음) — [식별력 설계](docs/MarkLens_식별력_설계.md) |
| 통합 | 4축 점수를 판례 사전분포 + 단조 제약 로지스틱 회귀(유형·요부 교호작용)로 결합해 출처 혼동 위험도 p(0~1)·등급 4단계(안전/주의/검토 권장/위험)·근거 축 기여도. 축 하나가 단독 임계값(정밀도 0.7) 이상이면 등급 하한 "검토 권장", 도형계 입력은 참고용 표시(x2_whole ≥ 0.9 면 검토 권장, 미검증). 심결례 정답 데이터로 가중치 학습 | **v1.2.1 학습 완료(2026-10-11, 모델 단계 마감)** — `ml/src/model/risk_model.py` `risk_score`, 계수 `shared/model/risk_model_v1.json`. 심결 AUC 0.62(0.55~0.67)·현실 분포 AUC 0.90(0.87~0.92; 단순 축 평균 0.925 와 CI 겹침), 판례 검증은 문자계 호칭·상품·요부 성립, 도형계 외관 불성립. 등급 하한 주의 0.063·검토 권장 0.126·위험 0.563(최소 지지 30 규칙의 대체값, 위험 정밀도 0.69·159쌍), σ 1.0 고정 — [통합 모델 설계](docs/MarkLens_통합모델_설계.md) §7~§7-2. 서비스(engine·API) 연결은 "다음 단계" |

축 함수 공통 규약: 위치 `ml/src/axes/`, 입력은 상표명 문자열 2개(X1·X2 문자 외관·X3) 또는
유사군 코드 집합 2개(X4), 출력은 0.0~1.0 float(높을수록 유사), 순수 함수·대칭·
결정적이며 예외를 던지지 않습니다. 각 축은 `ml/tests/`에 테스트를 동봉합니다.

### X1 호칭 유사도 (`ml/src/axes/x1_phonetic.py`)

```python
import sys; sys.path.insert(0, "ml")   # 프로젝트 루트에서
from src.axes.x1_phonetic import phonetic_similarity, has_pronunciation
phonetic_similarity("스타벅스", "스타박스")                              # 0.96
has_pronunciation("東洋")                                                # False → X1 결측 처리
phonetic_similarity("카페 봄", "봄", extra_generic=frozenset({"카페"}))  # 1.0
```

- 서비스 연결(최소): `POST /phonetic-search`가 기동 시 DB 상표명의 발음 후보를 캐시해
  입력 상표명과 비교한 상위 후보를 돌려주고, 상표명 확인 패널이 "발음(호칭)이 비슷한
  등록상표" 섹션으로 보여 줍니다. 검색 등급·점수에는 아직 반영되지 않습니다.
- 이력: v1(2026-09-17) → v1.1~v1.4.1(같은 주, 유사 자모·브랜드표·G2P 룰 보강) → v1.5(2026-09-30,
  `normalize_name` 공개로 X3와 정규화 공유). 상세는 설계 문서 §9.
- 흐름: 정규화(회사 형태·부가어·기능어 제거) → 발음 후보(외래어 표기법 근사 룰
  G2P, 국내 브랜드 로마자표 101개·지명표 34개, 예외 사전 63개, 복수 읽기 사전 21개, 낱자·숫자 읽기,
  한영 병기 판정) → 후보 조합 → 위치 가중 음절 레벤슈타인 → 최댓값.
- `has_pronunciation`이 False인 상표(순수 도형·한자만)는 X1을 결측으로 두고
  다른 축만으로 판단합니다. `extra_generic`에는 식별력 필터(다빈-3, v0.2 `pair_generic`)가 넘길 상품
  의존 보통명칭 집합을 넣습니다.
- 성능: 데이터 상표명 1,000쌍 0.21초(cold) — DB 전수 계산이 가능한 수준.
  G2P 벤치마크 60단어는 순수 룰 기준 정확 일치 48/60(브랜드·지명 로마자표와 예외 사전은
  벤치마크에서 끔).
- 설계·상수·한계·검토 대기 항목: [X1 설계 문서](docs/MarkLens_X1_호칭유사도_설계.md).
  점수표 재현: `ml/venv/bin/python ml/scripts/x1_report.py`.

### X3 관념 (`ml/src/axes/x3_semantic.py`)

```python
import sys; sys.path.insert(0, "ml")   # 프로젝트 루트에서
from src.axes.x3_semantic import has_meaning, semantic_similarity
has_meaning("스타벅스")                     # False → X3 결측 처리(조어)
semantic_similarity("왕", "KING")          # 0.807 (첫 호출 때 모델 로드, 캐시 후 약 9초)
semantic_similarity("스타벅스", "커피빈")    # 0.0 — 결측이지 비유사가 아님
```

- 게이트 `has_meaning`(v1.3): X1과 같은 정규화(`normalize_name`) 뒤 토큰을 wordfreq 빈도표에서
  **통째로** 찾아(한국어 zipf ≥ 2.5, 영어 ≥ 3.0) 하나라도 실제 단어면 True. 붙여쓴 합성어는 두 표제어
  (관형형은 어간으로 조회, 각 zipf ≥ 4.0)로 나뉘면 인정하고(검은고양이·행복한집), 영문은 3자 이상만,
  한국어 1음절은 명사 목록 62개(왕·별·달 …)만 인정합니다(유·재·T 같은 빈도표 조각 배제). 조어(스타벅스)·
  기호·한자만은 결측입니다.
- 모델: 후보 3개(multilingual-e5-base·MiniLM-L12-v2·LaBSE)를 유사 12·비유사 8·상위개념 2쌍으로 재고
  재보정 분리도가 가장 크고(+0.299, 다음 LaBSE +0.230) 가장 빠른(5.9ms/건, 480MB)
  paraphrase-multilingual-MiniLM-L12-v2를 선정했습니다(`MARKLENS_X3_MODEL`로 교체 가능). 코사인은
  DB 상표명 200쌍의 평균 c₀ 0.331을 0으로 두는 재보정으로 0~1 점수가 됩니다.
- 서비스 연결(최소, 2026-09-30, PR #26): `POST /semantic-search`가 기동 시 DB 상표명 중 관념이 있는
  515건을 한 배치로 임베딩해 캐시하고(6.4초, 서버 RSS 1.31 → 1.96GB) 하한 0.55 이상인 상위 5건을
  돌려줍니다(cold 10~18ms, warm 2ms). 상표명 확인 패널이 발음 섹션 아래 "관념 유사 후보"로 보여 주고,
  관념이 없는 입력은 "사전적 의미가 없어(조어) 관념을 비교하지 않았어요"로 안내합니다.
  `MARKLENS_X3_ENABLED=0`이면 캐시를 만들지 않고(기동 4.1초) 이 엔드포인트만 503.
- 한계: 다의어(사과 = apple/apology → 사과/APPLE 0.617), 짧은 문자열끼리의 잡음(왕 → 너구리 0.656),
  상위개념(과일/사과 0.576)·연상(커피/카페 0.611)을 구분하지 못합니다. 하한 0.55는 정답 데이터로
  재조정할 잠정값입니다.
- 테스트 219건(실제 모델, xfail 0; 가짜 임베더에서는 174 통과·23 건너뜀). CI와 `MARKLENS_FAKE_ML=1`은
  가짜 임베더(모델 다운로드 없음). 실제 모델 검증은 `ml/venv/bin/python -m pytest ml/tests/test_x3_semantic.py -q`,
  점수표는 `ml/scripts/x3_benchmark.py`.
- 설계·게이트 결정표·모델 선정 표·서비스 실측: [X3 설계 문서](docs/MarkLens_X3_관념유사도_설계.md)(v1.3).

### X4 상품 견련성 (`ml/src/axes/x4_goods.py`)

```python
import sys; sys.path.insert(0, "ml")   # 프로젝트 루트에서
from src.axes.goods_map import load_goods_map
from src.axes.x4_goods import goods_similarity, has_goods
gm = load_goods_map()                                                          # shared/goods_map/goods_map.json.gz
goods_similarity(gm.codes_for("화장품", 3), {"G1201", "S120907", "G1202"})     # 0.5
has_goods(set())                                                               # False → X4 결측 처리
```

- 자카드 = |교집합| ÷ |합집합|. 유사군 코드는 근사 기준이며 제35류 도소매업("화장품" vs "화장품
  소매업" = 0.0)은 개별 판단 사항입니다.
- 서비스 연결: 상품 검색 API `GET /goods/search`·`/goods/classes`(BFF `/api/goods/*`)가 변환표에서
  상품명·원 명칭(aliases)을 찾아 유사군 코드를 돌려줍니다(2026-09-21 실측: 적재 약 0.5초, 검색 수 ms).
  DB 1,100건 중 유사군 보유는 100건뿐이라 DB 전건 X4 계산은 유사군 백필 후에 가능합니다.
- 설계·한계·실측: [X4 설계 문서](docs/MarkLens_X4_상품견련성_설계.md)(v1, 2026-09-21).

### 통합 모델 — 판례가 정한 구조 (설계 2026-10-01, 1차 학습·v1.1·v1.2·v1.2.1 2026-10-11)

4축 점수를 로지스틱 회귀로 결합해 출처 혼동 위험도(0~1)와 등급을 내는 모델입니다. 가중치는
심결례 정답 데이터(2026-10-11 기준 351쌍 + 쉬운 음성 700)로 학습했고(`ml/scripts/train_risk_model.py`),
런타임 `ml/src/model/risk_model.py` 의 `risk_score(features)` 가 계수 JSON(`shared/model/risk_model_v1.json`)을
읽어 위험도·등급·근거 축 기여도를 냅니다. 모델 단계는 v1.2.1 로 닫았고 서비스 연결은 "다음 단계"입니다. 구조는 판례를 따릅니다.

| 상황 | 원칙 | 근거 |
|---|---|---|
| 총론 | 외관·호칭·관념을 객관적·전체적·이격적으로 관찰. 하나가 유사해도 전체로 혼동을 피할 수 있으면 비유사, 다른 부분이 있어도 호칭·외관이 유사해 혼동하기 쉬우면 유사 | 대법원 2000. 2. 25. 선고 97후3050 |
| 문자상표 | 호칭의 유사 여부가 가장 중요한 요소 | 97후3050 |
| 도형상표 | 외관이 지배적 인상 | 대법원 2013. 3. 28. 선고 2010다58261(2011후1548) |
| 결합상표 | 전체관찰이 원칙, 요부가 있으면 요부로 대비 | 대법원 2018. 6. 15. 선고 2016후1109, 2018. 9. 13. 선고 2017후2932 |
| 관념 | 국내 수요자가 쉽게 아는 뜻만 관념으로 본다 | 대법원 2005. 9. 30. 선고 2004후2628 (X3 게이트의 근거) |

- 유형별 조건부 가중치: X1×문자계·X2×도형계 교호작용을 두고(유형 주효과 지시변수는 사건 구성을 배우는 편향이라 v1.1 에서
  제거), 문자계에서 X1·도형계에서 X2 효과가 가장 크게 학습되는지를 검증 기준으로 삼습니다(판례 조건 (i)·(ii)).
- 결측 축 마스킹: `has_pronunciation`·`has_meaning`·`has_goods`가 False인 축은 점수 0 + 결측 지시변수 1로
  넣어 "정보 없음"을 비유사와 구분합니다.
- 단독 임계값: 한 축이 축별 임계값을 넘으면 등급을 최소 "검토 권장"으로 올리되(97후3050 후단) 자동
  "위험"으로는 올리지 않습니다(전단). 거래실정(대법원 2013. 6. 27. 선고 2011다97065)과 인지도 조항
  (34조 1항 9·11·12·13호)은 범위 밖입니다.
- v1.2.1(2026-10-11, 설계 §7-2 끝 — 모델 단계 마감, 두 결정 반영): "위험" 등급 최소 지지 10 → 30(지지 11·재현율 0.05 인 등급은 경고 기능이
  없음) → 위험 하한 0.899 → 0.563(대체값: 지지 30 이상 최대 정밀도 0.74 < 0.8; 정밀도 0.69·159쌍·재현율 0.58), σ CV 격자 → 1.0 고정(CV 무차별·
  CI 겹침) → 계수 CI 폭 x1_d 3.03 → 1.70(12항 평균 2.06 → 1.52). 심결 AUC 0.619(0.55~0.67)·현실 0.897(0.87~0.92), 판례 (i)/(ii)/(iii)/(iv)
  1.00/0.00/1.00/0.96 — 모두 v1.2 와 CI 안. 단독 임계값·도형 규칙 변화 없음. JSON version risk_model_v1.2.1, `meta.sigma_fixed`·`risk_min_support`.
- v1.2(2026-10-11, 설계 §7-2): 절편 사전분포 제외 → 절편 −4.86, 요부 플래그 계수 +0.88(CI 0 포함)로 교차표(차이 0.01)와 일치;
  요부 플래그를 `any_no_distinctive` + x1_d×any_no_distinctive(−1.10, 2000후2453)로 바꿔 판례 (iv) 0.92; 도형계 보류 규칙
  (`figure_caveat`, x2_whole ≥ 0.9 면 검토 권장 — 심결 도형계 쌍 17 에 해당 0건이라 미검증); 쉬운 음성 표본 50건(0.6~0.8 대역 7 +
  0.4~0.6 보조 43) 서브에이전트 판정 혼동 가능 0 → 제외 임계 0.8 유지. 심결 AUC 0.621·현실 0.895(v1.1 과 CI 안), 위험 하한
  0.899(정밀도 0.82 이나 11쌍·재현율 0.05 — 규칙의 최소 지지 10 이 만든 값 → v1.2.1 에서 30 으로 결정).
- v1.1(2026-10-11, 설계 §7-1): 1차의 유형 주효과·이름 결측 항은 사건 구성을 배운 편향이라 제거(이름 없는 37행 제외, 314행). 결합 방법
  4종을 같은 사건 단위 CV 로 비교 — 로지스틱 0.619 / 판례 사전분포+단조 로지스틱 0.618 / EBM 0.608 / 단조 GBM 0.626(전부 기준
  CI 0.56~0.68 안) → 사전분포(μ: 호칭 1+1, 외관 0.5+1, 철자·관념 0.5, 상품 1; σ 0.5)·단조 제약 모델 채택. 계수 문자계 호칭 3.16·
  철자 1.05·상품 1.06·CLIP 0.05(경계)·관념 0.03(경계). 판례 (i) 1.00 (ii) 0.01 (iii) 1.00 (iv) 1.00. 등급 하한 주의 0.091·검토
  권장 0.181·위험 0.591 — 위험 정밀도 0.69(0.8 미달; 1차의 0.80 은 편향 항이 만든 값). 단독 임계값(정밀도 0.7): 호칭 0.98·철자
  0.75·관념 0.77 활성, CLIP·상품 비활성. 현실 분포에서는 단순 축 평균(0.925)이 모든 학습 모델(0.90~0.92)보다 높다 — 학습 모델의
  이득은 등급·판례 일관성·근거 축이다. 요부 플래그 계수 −0.65·−0.72 는 절편 사전분포가 옮겨 간 값(교차표 차이 0.05 안).
- 1차 학습 결과(2026-10-11, 설계 §7): 채택 변형 B(교호작용)·쉬운 음성 가중치 0.5·C 0.3, 사건 단위 5겹×3반복 CV AUC 심결
  0.625(0.57~0.68)·심결+cross+db 0.908 — 기준선 축 평균 0.593/0.908 과 CI 가 겹칩니다(이득은 등급·보정·근거 축). 계수: 문자계
  호칭 2.86(가장 큼)·철자 0.95·상품 0.74·CLIP 이미지 0.07(0 과 구분 안 됨)·관념 0.20. 판례 검증(부트스트랩 500): 문자계 호칭 >
  외관 1.00, **도형계 외관 > 호칭 0.00(불성립 — CLIP 축 신호 없음·도형 쌍 37)**, 상품 > 0 0.99, 요부 없음 → 호칭 효과 감소 0.88.
  등급 하한 주의 0.093·검토 권장 0.187·위험 0.740(위험 정밀도 0.80, 검토 권장 이상 재현율 0.90). 단독 임계값은 다섯 축 모두
  비활성(정밀도 0.9 미달). 한계: n 351 경계 사례, 유형 라벨 LLM, 쉬운 음성은 가정 라벨.
- 입력·학습·검증 계획, 학습 입력 정의 표(§4-3)와 결정 대기 항목: [통합 모델 설계](docs/MarkLens_통합모델_설계.md).

### 정답 데이터 — 심결례 수집

통합 모델의 학습 데이터입니다. 특허심판원 심결문을 KIPRIS Plus 심판사항 API(항목별 검색 →
심결문 조회 → PDF)로 받아 텍스트를 뽑고, 정규식으로 주문·결론 조문·선등록 번호를 추출해
3등급으로 자동 선별한 뒤 LLM 이중 라벨과 사람 검증으로 라벨링합니다. 2026-10-11 마감까지의 흐름:
**수집 843건 → 자동 선별(1등급 331) → LLM 이중 라벨 430행(A↔B 96% → 규칙 처리 후 99%) → 보강(상표명 320/350·
유사군 184) → 4축 벤치마크 → 사람 검증 37건(LLM↔사람 97%) + A≠B 16행 규칙 처리 → 식별력 v0.1 3호 승인·v0.2·v0.3
결합 규칙 → 학습 전 사람 결정 4행 제외 → 학습 특징 351행(유사 210·비유사 141·제외 79) → 통합 모델 v1.2.1**(이름 있는
314행 + 쉬운 음성 700: 심결 AUC 0.62·현실 분포 AUC 0.90, 판례 4조건 (i) 문자계 호칭 1.00·(ii) 도형계 외관 0.00·(iii) 상품 1.00·
(iv) 요부 0.96, 등급 "위험" 정밀도 0.69(159쌍)·"검토 권장" 이상 재현율 0.90, 단독 임계값 호칭 0.98·철자 0.75·관념 0.77, 도형계 caveat).
코드(`backend/scripts/trials_collect.py`,
`backend/scripts/trials_kinds.json`, `backend/tests/test_trials_collect.py` 67건)와 설정
(`KIPRIS_TRIAL_*`, `pymupdf==1.28.2`)은 저장소에 있고, 데이터(`ml/data/trials/`)는 저장소에 넣지
않습니다.

**경계 사례 데이터**: 심결례는 양쪽이 다투어 심판까지 간 쌍이라 서비스에서 만날 분포가 아니라 경계 사례의 모음입니다. 그래서
심결 AUC 0.62 는 "어려운 경계 사례에서의 변별력"이고, 무관한 상표를 섞은 현실 분포 AUC 0.90 은 "무관한 상표를 걸러내는 힘"이며,
둘을 합쳐 정확도라고 부르지 않습니다. 현실 분포에서는 단순 축 평균(0.925)도 같은 수준이라 학습 모델의 이득은 등급·판례 일관성·
근거 축 표시입니다. 쉬운 음성(교차 350·DB 350)은 라벨이 가정이라 가중치 0.5 로만 학습에 넣고 평가에 씁니다. 유형 라벨은 LLM
추정이고 도형계 쌍은 17 뿐이라 도형계 결과(판례 조건 (ii) 불성립, OOF AUC 0.0~0.07)는 그대로 적되 서비스에서는 caveat 로 다룹니다.

- 범위: 2016-01~2026-09 상표·특허심판원 심결 중 거절결정불복·무효·권리범위확인(적극·소극).
  취소(불사용취소 등)·보정각하불복·제척·기피는 유사 판단 사례가 아니라 제외합니다.
- 자동 3등급: 결론이 상표법 34조 1항 7호(유사)이고 저명·주지·부정한 목적 언급이 없으면 1등급(학습
  후보), 7호이지만 인지도 언급이 있거나 결론 조문을 못 뽑았으면 2등급(사람 확인), 각하·선등록상표
  소멸로 인한 취소·결론이 인지도 조항(9·11·12·13호)이나 식별력(33조)뿐인 사례는 3등급(유사 판단 없음).
  같은 청구인 + 같은 선등록 집합(family)은 첫 건만 1등급이고 나머지는 중복으로 표시합니다.
  권리범위확인은 34조 결론이 없는 것이 정상이라 판단 절의 표장 유사 소결(유사/비유사)로 1등급을 정하고,
  효력제한(90조)·자유실시·식별력 없음·상품 비유사만·확인대상표장 불특정·상표적 사용 아님은 3등급,
  유사여부 추정은 주문(속함/불속, 기각은 적극→불속·소극→속함)에서 읽습니다(2026-10-01 4단계). 결론을
  소결 제목 아래서 읽으면 신뢰도 high, 판단 절 끝에서 폴백으로 읽으면 low 로 표시하고, 상대 표장
  유형(선등록·선출원·선사용·국제등록·확인대상표장)·결정축·상표유형 추정 열을 함께 냅니다. 선출원 저촉
  (35조 1항 = 구 8조 1항) 결론은 7호와 같이 다루되 표장 유사 소결이 있어야 1등급이고, 상대 표장 번호를
  못 뽑은 건은 본문에서 "선등록·인용·선출원·확인대상·대비" 근처(±200자)의 번호를 `상대표장_번호_후보`로
  냅니다. 권리범위확인의 family 는 청구인·피청구인·이 사건 등록상표로 묶습니다(확인대상표장은 번호가 없음).
- 현황(2026-10-01, 호출 9월 924/950 · 10월 900/950): 목록 129개월 42,474건(`list_all.csv`),
  1차 층화 표본 373건 + 시범 20건 + 2차 배치 450건(권리범위확인 280·무효 100·거절결정불복 70)
  → PDF·텍스트 843건, `labels.csv` 1024행/843건 — 자동 1등급 331건(거절 106·무효 30·권리범위 195)·2등급 120·3등급 392,
  상대 표장 번호 후보 복구 68건. `sheet`가 `curation_queue.csv`(355건: 1등급을 권리범위확인 → 거절결정불복
  → 무효, 신뢰도 high → low 순, 그다음 권리범위 저명·주지 언급 2등급 24건, family 중복 제외)를 함께 만들고,
  `show --next`가 큐에서 유사여부_확정이 비어 있는 첫 건을 보여 줍니다(폴백으로 읽은 결론 문장은 `>>`). 확정 열을
  채우면 `sheet` 재생성 때 보존되고 `status`가 진행률을 보여 줍니다.
- 라벨 도구(PR #30, `labels.csv` 프로세스 간 잠금·원자적 쓰기는 PR #31): `show --batch n`이 라벨 없는 다음 n건을 `batch_<k>.md`(주문·판단 절만, 정규식
  추정은 넣지 않음)로 뽑고, `label <심판번호> <유사|비유사|제외> --source llm|human --evidence "소결 문장"
  --confidence high|low [--axis 외관,호칭,관념,상품] [--type …] [--reason …] [--b 상대번호] [--pass a|b]`가
  `labels.csv`에 판정·라벨출처·근거문장·확신도·확인여부를 기록합니다(llm은 사람이 확인한 행을 덮어쓰지 못하고,
  pass b는 `llm_b_*` 열에만). `confirm`은 LLM 라벨을 그대로 승인, `review`는 재검토 큐(LLM≠추정·확신도 low·
  메모 애매·pass A≠B), `sample --n 40 --seed 0`은 미확인 LLM 라벨의 종류×판정 층화 검증 표본, `status`는
  판정 집계와 LLM↔사람·LLM↔추정·LLM A↔B 일치율을 보여 줍니다. `review --bundle`(2026-10-09)은 사람 검토 묶음
  5개를 `review_bundle/*.csv`로 한 번에 뽑습니다 — verify_queue(표본 40, seed 0)·ab_disagree(A≠B)·name_review(판정자가
  검토를 요청한 명칭 행, `name_review_ids.txt` 없으면 메모의 "검토")·distinct_drop(유사 라벨인데 식별력 적용으로
  x1_d 또는 x2_text_d가 0.1 넘게 내려간 쌍, 떼어낸 토큰 표시)·weak_tokens_top200. 각 행에 `show` 명령과 `처리` 열이
  있고(재생성 때 보존) `status`가 묶음별 처리/행 수를 보여 줍니다. 묶음을 브라우저에서 카드 단위로 처리하려면
  `ml/venv/bin/python -m backend.scripts.review_ui`(개발 전용, http://127.0.0.1:8010, `--port`)를 띄웁니다 — 탭 6개
  (표본·A≠B·명칭 검토·식별력 하락·기술적 표장·약한 토큰), 키 Enter 승인·1/2/3 판정·a 판단축·m 메모·u undo·←/→
  이동. 저장은 `trials_collect.py`의 label·confirm·name-b 함수(잠금·사람 열 보존)와 `distinctiveness.py`의
  승인·제외 갱신 함수만 거치며, 식별력 하락·명칭 결정은 `ml/data/trials/review_decisions.json`, 약한 토큰 해제는
  `shared/distinctiveness/weak_token_overrides.json`(로더가 읽어 점수 1.0)에 남습니다.
- LLM 이중 라벨링(2026-10-01, 호출 0): 큐 355건(430행)을 독립 판정자 둘(pass a·b)이 같은 배치 파일만 보고 따로
  판정해 끝냈습니다 — 유사 225·비유사 140·제외 65(라벨출처 llm), LLM A↔B 일치율 96%(414/430, 불일치 16행은
  4건), LLM↔정규식 추정 80%(340/424). `review` 재검토 큐 130행(LLM≠추정 84·확신도 low 76·메모 애매 65·A≠B 16,
  중복 포함). 사람 검증은 `sample --n 40 --seed 0` 표본 40건을 검토 화면에서 `confirm`·사람 `label`로 확정해
  `status`의 LLM↔사람 일치율로 봅니다(2026-10-11: 36/37 = 97%, 미처리 3).
- 보강(2026-10-08, 브랜치 `feat/trials-enrich`, `backend/scripts/trials_enrich.py` targets/lookup/goods/status, 테스트 17건):
  LLM A·B가 일치한 유사·비유사 350행(유사 210·비유사 140)의 상대 표장 상표명과 양쪽 지정상품 유사군을 채웠습니다.
  상대 표장 유형은 선등록·선출원(번호 있음) 131·국제등록 7·확인대상표장(번호 없음) 204·선사용 1·기타 7. 번호 있는
  138건(등록 131 + 국제등록 7)은 출원속보 `getAdvancedSearch`(`registerNumber` 13자리 "40+7자리+0000",
  `internationalRegisterNumber`)로 `lookup --dry-run` 계획표(138회 ≤ 하드캡 400) 확인 뒤 138회 호출 — 성공 138·0건 0·
  오류 0, 일일 예산은 이 실행에만 명령 앞 `KIPRIS_DAILY_BUDGET=400`(10월 출원속보 누계 148/950) → `prior_marks.csv`(상표명·
  출원/등록번호·류·비엔나코드·출원인, 원본 XML `enrich_raw/`, 실행 집계 `enrich_calls.json`, 재실행은 조회된 번호를 건너뜀).
  번호 없는 행은 기초사실 본문의 "확인대상표장 … 구성" 문장(128) → OCR(55). 상표명 확보 320/350행(91.4%: kipris 137·
  본문 128·ocr 55, 없음 30). 지정상품은 기초사실의 지정상품/사용상품 줄(별지 참조 44행은 별지 절, 표장별 소제목이 있으면
  해당 절)을 나눠 변환표에 대응 — 완전일치(공백·류 무시 포함) → `search` 상위 1건(정확·접두 단계만, 부분일치 제외): 고유
  명칭 13,846건 중 8,753건(63.2%), 양쪽 유사군이 있는 행 187(이 사건만 112·상대만 30·없음 21·상대 블록 없음 23).
  2026-10-11 매핑 규칙 보강(접두 부분 일치 삭제, 키 정규화·alias·[동의어]·접미·토큰 자카드 ≥ 0.8 — X4 설계 §4-1): 355행 고유 명칭
  13,910건 중 9,152건(65.8%, 등장 가중 70.1%), 양쪽 유사군 행 184(접두 과매핑 제거로 9행 잃고 6행 얻음), 오매핑 눈 검사 20/20 정상.
  `x4_goods`(자카드)는 유사 107행 평균 0.44(중앙값 0.33)·비유사 80행 평균 0.32(중앙값 0.17). 못 찾은 명칭 상위:
  레스토랑업 25·간이식당업 19·카페업 16·카페테리아업 12·음식조리대행업 10(고시 43류에 단독 명칭 없음), 국제등록의 영문
  지정상품(namely 18·proteins 8). 새 열 `상대표장_번호_정규화`·`상대표장_명칭_본문`·`상대표장_명칭_ocr`·
  `상대표장_명칭_kipris`·`goods_codes_this`·`goods_codes_prior`·`x4_goods`(`labels.csv`, `sheet` 재생성 때 보존).
- 상대 명칭 LLM 추출(2026-10-09, 브랜치 `feat/distinctiveness-v0`, 호출 0): 이름 B 가 본문·OCR 추출이던 183행을
  `show --batch 10 --ids <목록 파일>` 명칭 배치(기초사실·판단 절, 라벨 여부 무관)로 뽑아 LLM 판정자가 판단 절의 문자 표기를
  그대로 `label <심판번호> --name-b "<문자열>" --source llm`(새 열 `상대표장_명칭_llm`, 도형만이면 빈 값 + `--memo 도형`)으로
  기록했습니다 — 성공 176·도형 6·실패 1, 기존 본문·OCR 명칭과 불일치 116/176. 특징 생성의 이름 우선순위는 kipris > llm >
  본문 > ocr 입니다(통합 모델 설계 §4-2).
- 학습 전 라벨 반영(2026-10-11, 브랜치 `feat/risk-model-v1`, 사람 결정·출처 human): 2016101003128 의 731170·28720(심결 미대비)과
  2017100002365·2020101002190(상대 표장 번호 오류, 11월 보강 때 재조회)을 제외 → 유사 210·비유사 141·제외 79, 확인 39(LLM↔사람
  35/39 = 89%, 수정 4), 특징 파일 351행. 이 데이터로 통합 모델 1차 학습(설계 §7).
- 마감(2026-10-11, 브랜치 `feat/review-wrapup`, 호출 0): 검토 화면(`review_ui`)으로 표본 37/40 확인(LLM↔사람 36/37 = 97%,
  미처리 3행은 "미처리(사람)"으로 표시만), 명칭 검토 31·약한 토큰 200 처리. A≠B 16행은 규칙으로 처리(`--source llm`, 사람
  출처로 기록하지 않음): 2016101003128 은 심결이 대비한 선등록상표4(제157519호)만 유사·나머지 제외 "심결 미대비"(사람이
  확정한 2행 731170·28720 은 llm 으로 덮지 않음), 2021100001808 은 90조1항1호 효력제한이라 제외, 2023100001455 는 표장
  동일·상품 대비에 이른 비사용 사건이라 비유사·상품, 2023100001617 은 family 상이라 유사(호칭) → LLM A↔B 일치 426/430(99%),
  라벨 유사 214·비유사 141·제외 75. 식별력 하락 14건은 LLM 판정자가 소결을 읽어 `review_decisions.json` 에 결정(결합 규칙
  후보 13·그대로 1) → 식별력 v0.2 결합 규칙 구현, 3호 사람 승인 반영(절대어 57·해제 12·상대어 380), 유명 브랜드 토큰
  갤럭시·오리온. 특징 파일은 `유사여부_확정` 기준 355행(pass b 일치 불요)으로 재생성, 벤치마크 재측정은 통합 모델 설계 §4-3
  (4축 완전 관측 134행). 남은 사람 결정: 표본 미처리 3행(사람 확정 2행·쌍 오류 의심 2행은 위 "학습 전 라벨 반영"에서 제외 — 통합 모델 설계 §6).
- 학습 전 입력 정리(2026-10-11, 브랜치 `feat/pretrain-cleanup`, 호출 0): ① 지정상품 매핑 규칙 보강(위) ② 식별력 결합 규칙 v0.3
  (붙여쓴 결합어 — 혹달린신발·QUICKPATH·SLIMLINE 복귀, 식별력 하락 12 → 8행) ③ `trials_enrich.target_rows` 를 특징 파일과 같은
  `유사여부_확정` 기준(355행)으로 통일 → 특징·벤치마크 재생성(AUC 변화 CI 안, X4 n 184, 네 축 완전 관측 133행) — 통합 모델 설계 §4-4.
- 다음 단계: 위 "다음 단계" 절 — 서비스 연결(3입력 `/search`·X2 v2·위험도·근거 축·요부 표시·도형 caveat), 11월 대기열 621건은
  도형상표 우선 수집 → 도형 규칙 τ 0.9·판례 조건 (ii) 검증 → 재학습.
- 예산: KIPRIS 월 1,000회 한도를 출원속보 키와 분리해 `KIPRIS_TRIAL_ACCESS_KEY`·
  `KIPRIS_TRIAL_MONTHLY_BUDGET`(기본 950)·`KIPRIS_TRIAL_DAILY_BUDGET`(기본 300)으로 관리하고, 호출마다
  `ml/data/trials/calls.log`, 누계는 `quota.json`에 남깁니다. PDF 다운로드도 1회로 셉니다(가정,
  `KIPRIS_TRIAL_COUNT_DOWNLOADS=1`). `--dry-run`은 호출 0회로 계획만, `--max-calls`는 실행별 상한입니다.

```bash
# 프로젝트 루트에서. 실호출은 --max-calls 상한을 두고 사람이 결정한다(--dry-run 으로 계획표·예산 확인).
ml/venv/bin/python -m backend.scripts.trials_collect list --all-kinds --from 201601 --to 202609 --dry-run
ml/venv/bin/python -m backend.scripts.trials_collect sample --scope 100 --invalidation 130 --refusal 145 --out ml/data/trials/sample.csv
KIPRIS_TRIAL_DAILY_BUDGET=900 ml/venv/bin/python -m backend.scripts.trials_collect fetch --queue ml/data/trials/fetch_queue.csv --max-calls 900 --kind-priority scope,invalidation,refusal --kind-cap scope=280,invalidation=100,refusal=70
ml/venv/bin/python -m backend.scripts.trials_collect extract
ml/venv/bin/python -m backend.scripts.trials_collect sheet      # 사람 열(유사여부_확정 등)은 보존
ml/venv/bin/python -m backend.scripts.trials_collect show --next           # 큐레이션 큐의 다음 미확정 건(또는 show 2023100000403)
ml/venv/bin/python -m backend.scripts.trials_collect show --batch 20       # 라벨 없는 다음 20건 → batch_<k>.md (--pass b 는 pass b 기준)
ml/venv/bin/python -m backend.scripts.trials_collect label 2023100000403 유사 --axis 호칭 --source llm --evidence "그 호칭이 동일하므로 …" --confidence high
ml/venv/bin/python -m backend.scripts.trials_collect confirm 2023100000403 # LLM 라벨을 그대로 승인(확인여부=Y)
ml/venv/bin/python -m backend.scripts.trials_collect review                # 재검토 큐 → review_queue.csv (LLM≠추정·확신도 low·메모 애매·A≠B)
ml/venv/bin/python -m backend.scripts.trials_collect sample --n 40 --seed 0 # 미확인 LLM 라벨의 종류×판정 층화 검증 표본
ml/venv/bin/python -m backend.scripts.trials_collect status                # 판정 집계·LLM↔사람·LLM↔추정·A↔B 일치율
```

### 상품↔유사군 변환표 (`shared/goods_map/`)

지식재산처 고시상품명칭 13판(2026) xlsx를 `[상품명, 류, 유사군코드 배열]` 1:N
JSON으로 바꾸는 도구입니다. 절차는 원본 다운로드(브라우저) → `parse_goods_map.py
inspect`/`convert` → `validate_goods_map.py` 순이며 명령은
[`shared/goods_map/README.md`](shared/goods_map/README.md)에 있습니다. 2026-09-17
검증에서 91,591건, Nice 45/45류, 유사군 2개 이상 5,798건을 원본과 대조했습니다.

변환표 `goods_map.json.gz`는 저장소에 포함되어 있습니다(공공누리 제1유형·출처표시, 2026-09-30
확인 — 근거는 [`shared/goods_map/README.md`](shared/goods_map/README.md) §5). 원본 xlsx와 24MB
`goods_map.json`은 `.gitignore`로 두고 각자 로컬에서 생성합니다(`--gzip`으로 `.gz` 재생성). 소비 측은
로더 `ml/src/axes/goods_map.py`(백엔드 `/goods/*` 상품 검색 API, X4 입력)이며 지정상품 입력
화면(프론트-6)은 `frontend/components/GoodsPicker.tsx`로 구현됐고(상표명 패널 아래 세 번째 입력 영역),
선택 결과는 검색 폼 상태와 결과 화면 요약에만 쓰입니다 — `/search` 요청에 유사군을 보내는 연동(③)은
유사군 백필 후입니다. 타입은 `shared/types/goods.ts`.

### 유명 브랜드 목록 (`shared/famous_brands.txt`)

로고가 널리 알려진 브랜드의 KIPRIS **출원인명** 39건(국내 23·해외 16) DRAFT입니다.
`backend/scripts/collect_pipeline.py --applicants-file shared/famous_brands.txt`의
입력용이며 아직 수집에 쓰지 않았습니다(팀 검토 전).

## 검증

```powershell
$env:MARKLENS_FAKE_ML = "1"
ml\venv\Scripts\python.exe -m pytest -v
ml\venv\Scripts\python.exe -m ruff check backend ml
ml\venv\Scripts\python.exe -m pip_audit --local --progress-spinner off

Set-Location frontend
npm run typecheck
npm run lint
npm test
npm run test:e2e
npm run build
npm audit --omit=dev --audit-level=high
```

```bash
export MARKLENS_FAKE_ML=1
ml/venv/bin/python -m pytest -q
ml/venv/bin/ruff check backend ml
ml/venv/bin/python -m pip_audit --local --progress-spinner off

cd frontend
npm run typecheck && npm run lint && npm test && npm run test:e2e && npm run build
npm audit --omit=dev --audit-level=high
```

2026-10-11 검증(`chore/model-phase-wrapup`, develop `2af05f3` 기준, v1.2.1 재학습 뒤): Python `1096 passed, 26 skipped`
(가짜 ML 모드, X1 123건·X3 174건·심결례 파이프라인·식별력 40건·통합 모델 17건·검토 화면 4건 포함), ruff 통과.
2026-10-01 검증: X3 실제 모델 검증 `219 passed`, frontend Vitest `77 passed`(19 파일), Playwright
`15 passed`(스펙 5개 × 뷰포트 3개 320x568, 667x375, desktop). 2026-09-30 file 모드 실서버 스모크에서 `/health`가 `index_size`·`trademark_count` 1,100과
generation `20260827T035002Z-25f84a6eeb26`을 반환했고, X3 캐시 515건·`/semantic-search`
cold 10~18ms·warm 2ms를 확인했습니다. 이 검증에서 KIPRIS `/name-check`는 호출하지 않았습니다.
직전 기록(2026-09-22, `b6b9bba`)은 Python `541 passed, 1 skipped`, Vitest `52 passed`였습니다.

### CI

`.github/workflows/ci.yml`은 `main`·`develop` push와 모든 PR에서 3잡을 돌립니다.

| 잡 | 내용 |
|---|---|
| python | Python 3.11, `ruff check backend ml`, `pip check`, `pytest -v`(`MARKLENS_FAKE_ML=1`, PostgreSQL 16 서비스), `pip-audit --local` |
| frontend | Node 22, `npm ci`, `npm audit --omit=dev --audit-level=high`, typecheck, lint, Vitest, `next build`, Chromium Playwright E2E |
| deployment-config | `compose.production.yml` 계약 검증, Nginx 문법 검증 |

`pip-audit`·`npm audit`은 실패 게이트입니다. 2026-09-17 #17에서 이 게이트에 걸린
의존성을 올렸습니다(next 16.3.5, httpx2 2.13.0).

실제 OpenCLIP 강건성 평가는 opt-in 명령입니다. 라벨 검수가 끝나기 전에는
임계값 재보정이나 정확도 주장을 하지 않습니다.

### 데이터 확장과 사람 검수

KIPRIS 수집은 먼저 `--plan`으로 호출 상한을 확인하고, DB가 없는 연구 환경에서는
`ml/data/staging/`에 메타·이미지를 격리합니다. 2026-08-15에는 105건을 기준으로
신규 895건을 수집·감사·승격해 index를 정확히 1,000벡터로 확장했습니다. 8월 로컬
호출 카운터는 `145/950`이며, 월 예산을 지키기 위해 신규 레코드의 서지상세·유사군
보강은 실행하지 않았습니다. 재현 명령, 백업, 격리와 승격 계약은
[데이터 확장 실행 기록](docs/MarkLens_데이터확장_실행계획_2026-08.md)에 있습니다.
2026-08-27에 1,100건 세대로 갱신되어 데이터 저장소에 커밋되어 있습니다.

현재 라벨링 팩 `vlp2_d32d53e3b6c101517517`은 1,000-vector generation에서 자동
그룹화한 769개 visual family를 바탕으로 200쌍(development 160, frozen holdout 40)을
만들었으며 사람 라벨은 `0/200`입니다. 따라서 fine-tuning gate는 닫혀 있습니다.

같은 generation의 v4 강건성 표본은 25개 원본과 100개 변형을 모두 처리했습니다.
exact Recall@1은 원본 `0.76`, crop `0.72`, 나머지 변형 `0.76`이고 모든 Recall@5와
상태 안정성은 `1.0`입니다. 원본 R@1 miss 6건은 모두 byte-identical 그룹의 rank 2~3
동률 사례였지만 family R@1은 측정하지 않았으므로 패밀리 검색 성능으로 해석하지 않습니다.
로컬 검수 도구는 `ml/`에서 실행합니다.

```powershell
venv\Scripts\python.exe scripts\review_labeling_pack.py `
  --annotator-id "<stable-reviewer-id>"
```

```bash
venv/bin/python scripts/review_labeling_pack.py --annotator-id "<stable-reviewer-id>"
```

기본 화면은 development 160쌍만 보여 줍니다. frozen holdout 40쌍은 development
결정과 임계값을 고정한 뒤에만 단방향으로 열 수 있습니다. 상세 계약은
[ML 평가·라벨링 가이드](ml/evaluation/README.md)를 참고하세요.

## 공개 배포 준비

`compose.production.yml`은 다음 경계를 구성합니다.

- 외부 노출: Nginx gateway와 Next.js만
- 내부 전용: FastAPI와 PostgreSQL
- 검색 5회/분, 명칭 확인 2회/분의 gateway 사용자별 제한
- Turnstile 서버 검증과 서버 전용 FastAPI 키
- production의 PostgreSQL·32자 이상 API 키·artifact manifest 필수화
- KIPRIS 재배포 권리 확인 전 결과 이미지 공개 비활성

실행 전 [공개 배포·보안 가이드](docs/MarkLens_공개배포_보안가이드.md)의 수동
게이트를 모두 완료해야 합니다. 특히 기존 KIPRIS 키 회전, 공식 약관 확인,
TLS 종료, 데이터 마이그레이션은 자동화할 수 없는 항목입니다.

TLS edge는 외부의 `X-MarkLens-Client-IP`를 제거한 뒤 검증한 원격 IP로 다시
설정해야 합니다. Compose gateway는 기본적으로 loopback에만 바인딩되어 이 신뢰
경계가 없는 평문 공개를 막습니다.

## 데이터와 권리

KIPRIS 원본, 이미지, FAISS 인덱스와 모델 캐시는 저장소에 포함되지 않습니다.
KIPRIS 콘텐츠의 공개 재배포 또는 수익 목적 사용은 별도 권리 확인이 필요합니다.
production 예시는 `MARKLENS_PUBLIC_RESULT_IMAGES=false`가 기본입니다.
고시상품명칭 변환표 `shared/goods_map/goods_map.json.gz`는 공공누리 제1유형(출처표시)으로
포함하며 출처는 "지식재산처 고시상품명칭 13판(2026), 공공누리 제1유형"입니다(`/goods/*` 응답의
`source` 필드도 같은 문구). 원본 xlsx와 유사상품 심사기준 PDF(공공누리 제4유형)는 포함하지
않습니다(`shared/goods_map/README.md` §5). 정답 데이터용 심결문(KIPRIS 심판사항 API로 받은 PDF·텍스트)은
저작권법 제7조(보호받지 못하는 저작물)의 심판 결정에 해당하지만 저장소에는 넣지 않으며
`ml/data/trials/`는 `.gitignore` 대상입니다. 심결문에 적힌 당사자명은 공개 심결 정보이고, 테스트
픽스처에는 실제 응답 1~2건만 씁니다.

## 브랜치·협업

- `develop`은 통합 브랜치, `main`은 안정 브랜치입니다. 기능 브랜치(`feat/…`,
  `fix/…`, `chore/…`, `docs/…`) → PR(base `develop`) → CI 통과 후 머지 → `develop`을
  `main`으로 동기화(PR)합니다.
- 2026-10-01 병합(base `develop`): PR #29 심결례 수집 1~4단계 → #30 라벨 도구(`label`·`confirm`·`show --batch`·
  `review`·`sample`·`status` 일치율) → #31 `labels.csv` 프로세스 간 잠금·원자적 쓰기(라벨링 에이전트 둘의 동시
  실행 대비). 병합 후 `main` = `develop` = `7e56b0a`. 2026-10-08~11 병합: PR #35 정답 데이터 보강 → #36 4축 벤치마크·X2 철자
  → #37 식별력 v0·명칭 LLM 추출·현실 분포 → #38 X1 v1.6·`review --bundle` → #39 3호 기술적 표장 v0.1 → #40 검토 웹 화면
  → #41 정답 데이터 단계 마감·식별력 v0.2 → #42 학습 전 입력 정리 → #43 통합 모델 1차 → #44 통합 모델 v1.1 → #45 통합 모델 v1.2(`main` = `develop` =
  `2af05f3`). 다음은 `chore/model-phase-wrapup`(모델 단계 마감 v1.2.1·문서 현행화).
- 커밋 메시지는 `유형(범위): 설명` 형식입니다. 예: `feat(ml): X1 호칭 유사도 축`,
  `fix(backend): …`, `docs(readme): …`.
- `.env`, `ml/data/`(데이터·인덱스·호출 카운터), 인증키는 커밋하지 않습니다.
- 태그 `v0.1-semester1`(`a4e3f11`, 2026-06-10)이 1학기 종료 기준선입니다.
- Dependabot(주간, pip·npm·docker·actions)이 열어 둔 PR 14건(#3~#32 사이, 2026-10-11 현재)의
  처리 방침은 결정 대기(사유: 팀에서 아직 논의하지 않음 — 올릴 때는 `constraints.txt` 고정과 CI 게이트 pip-audit·npm audit 을
  함께 바꿔야 함)입니다.

## 문서

- [전체 문서 색인](docs/README.md)
- [X1 호칭 유사도 설계](docs/MarkLens_X1_호칭유사도_설계.md)
- [X2 외관 벤치마크 설계](docs/MarkLens_X2_외관_설계.md)
- [X3 관념 유사도 설계](docs/MarkLens_X3_관념유사도_설계.md)
- [X4 상품 견련성 설계](docs/MarkLens_X4_상품견련성_설계.md)
- [식별력·요부 필터 설계](docs/MarkLens_식별력_설계.md)
- [통합 모델 설계](docs/MarkLens_통합모델_설계.md)
- [통합 모델 계수 안내](shared/model/README.md)
- [상품↔유사군 변환표 절차](shared/goods_map/README.md)
- [식별력 산출물 안내](shared/distinctiveness/README.md)
- [2026-2학기 16주 계획과 4주 단위 제출 문서](docs/course/2026-2/README.md)
- [2026-08 기술 재감사 보고서](docs/MarkLens_기술감사보고서_2026-08.md)
- [API 계약](docs/MarkLens_API계약_v1.md)
- [공개 배포·보안 가이드](docs/MarkLens_공개배포_보안가이드.md)
- [모델·데이터 카드](docs/MarkLens_모델카드_데이터카드.md)
- [ML 평가·라벨링](ml/evaluation/README.md)
- [트러블슈팅](docs/MarkLens_트러블슈팅.md)
- [설계 결정 기록](docs/MarkLens_설계결정기록.md)

## 팀

- 최다빈 — 데이터·법리·모델 총괄(정답 데이터, X1 호칭·X3 관념·X4 상품, 통합 모델 설계, 식별력 필터)
- 정현수 — 데이터 인프라·백엔드(수집, DB, API, 배포)
- 배지원 — 화면·변환표(프런트, 변환표 파서, 통합 모델 참여)

본 프로젝트는 건국대학교 컴퓨터공학부 졸업프로젝트이며 비상업적 교육·연구
목적으로 개발됩니다.
