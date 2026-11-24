# 통합 모델 계수 (다빈, 프론트-9)

`risk_model_v1.json`(version `risk_model_v1.3`, 2026-10-25 — v1.2.1 은 2026-10-11 모델 단계 마감) — `ml/scripts/train_risk_model.py` 가 심결례 정답
데이터(`ml/data/trials/pairs_features.csv` + 쉬운 음성 `pairs_features_easy.csv`, 2026-10-25 부터 쉬운 음성에도 CLIP 이미지 축)로 학습해 쓴
**판례 사전분포 + 단조 제약 + 결합 제약 로지스틱 회귀** 계수. 런타임 `ml/src/model/risk_model.py` 의 `risk_score(features)` 가 읽어
`RiskResult(prob, grade, contributions, figure_caveat, pattern)` 를 내고(픽클 없음, 적재 때 단조·결합 제약 검증), 서비스 엔진
`backend/src/core/multi_search.py` 가 세 입력 통합 검색(API 계약 v2)에서 후보마다 호출한다. 학습 결과·해석·한계는
`docs/MarkLens_통합모델_설계.md` §7–§7-3(v1.3 은 §7-3), 전체 표는 `ml/data/trials/risk_model_v1_report.md`(비공개). EBM·GBM 비교 실험은
`ml/requirements-experiments.txt` 를 설치한 뒤 `--methods` 로.

| 키 | 내용 |
|---|---|
| `pattern_axes`·`patterns` | v1.3 **결측 패턴별 계수 집합**: 패턴 축 `x2_whole`(이미지)·`x4`(상품)의 관측 조합 네 개 `base` / `x2_whole` / `x4` / `x2_whole+x4` 마다 `requires`·`features`·`coefficients`·`intercept`·`meta`(n·클래스·자기 패턴 행·OOF AUC). 런타임이 입력에서 관측된 축으로 하나를 고른다(관측된 축만 입력, 결측 지시변수 없음; 관념 축은 게이트가 꺼지면 값 0). 각 집합은 그 축들이 관측된 모든 행(base 는 1,014행 전부)으로 적합 |
| `reference_pattern`·`features`·`coefficients`·`intercept` | 기준 패턴(`x2_whole+x4`, 모든 축 관측)의 계수 집합을 최상위에 그대로 둔다(옛 코드 호환, 절편 −3.4712). 표준화 없음 — 0–1 점수에 바로 곱한다. 기여도 `miss_pattern` = 쓰인 패턴 절편 − 기준 절편(엔진 `missing_adjustment`; base −0.165·x2_whole −0.339·x4 +0.018) |
| `coupling` | 결합 제약: 축 하나를 `floors`(쉬운 음성 비유사 쌍 평균 — 이미지 0.3487·상품 0.0252) 이상으로 더 관측하면 로짓이 내려가지 않는다(설계 항 상자의 모든 꼭짓점에서; 학습은 SLSQP 선형 제약, 런타임은 적재 때 `coupling_violations` 로 검증). "입력을 더 주면 위험도가 내려가지 않음" 성질의 근거 |
| `method`·`prior`·`monotone` | 채택 방법(prior_monotone_logistic), 사전평균 μ·σ(`applies_to` 유사도 축·교호작용만, 절편 자유; σ 1.0 고정 — `hyper` 1.0, `meta.sigma_selection` "fixed"), 단조 제약(유사도 축 본체 ≥ 0, x2_whole 본체 + 도형계 ≥ 0, x1 본체 + 문자계·요부없음 교호작용 모든 조합 ≥ 0 — 패턴마다) |
| `figure_rule` | 도형계(도형·결합-도형요부) 입력의 제품 규칙(v1.2, `validated` false): `figure_caveat` True + 화면 문구 `caveat`, x2_whole ≥ `threshold`(0.9) 면 등급 하한 검토 권장 |
| `grade_thresholds` | 등급 하한 p: 주의 0.0902 / 검토 권장 0.1805 / 위험 0.5902(안전은 0–주의 하한). 심결+cross+db OOF(행마다 자기 패턴) 기준 — 위험은 정밀도 ≥ 0.8·최소 지지 30(`meta.risk_min_support`)을 채우는 p 가 없어 대체값(검토 권장 하한과 1.0 의 중간; 위험 등급 정밀도 0.7039·152쌍 = `meta.grade_precision`, 계약 v2 "10건 중 7건"), 검토 권장은 재현율 ≥ 0.9, 주의는 검토 권장의 절반 |
| `standalone_thresholds`·`standalone_precision` | 축별 단독 임계값 τ(정밀도 ≥ 0.7 지점; 97후3050 후단: τ 이상이면 등급 하한 검토 권장): x1_d 0.98·x2_text_d 0.75·x3_d 0.7707, x2_whole·x4 는 null(비활성) |
| `removed_terms` | 쓰지 않는 항(유형 주효과·miss_x1·miss_x2text·has_distinctive_part_a/b·miss_x2img·miss_x4·miss_x3 — 요부는 `any_no_distinctive`, 결측은 패턴) |
| `meta` | n·CV AUC(심결 0.6184·현실 0.9113)·Brier·채택 규칙·입력 정의·`sigma_selection`·`risk_min_support`·`grade_precision`·`pattern_choice`·`coupling_floors`·`monotonicity`(학습 행 검사)·`indicator_reference`(지시변수 구조 참고 모델 — miss_x2img 0.56) |

재학습(프로젝트 루트, KIPRIS 호출 0, 기본 2방법 약 13초): `ml/venv/bin/python ml/scripts/pairs_features.py --fill-easy-images`(쉬운 음성 이미지 축, 5초) →
`ml/venv/bin/python ml/scripts/train_risk_model.py`(이 파일 `risk_model_v1.json` 에 쓴다 — 런타임 `V13_MODEL_PATH`). 2026-11-24 부터 서비스 기본 모델은 아래
`risk_model_v1.4.6.json`(런타임 `MODEL_VERSION` risk_model_v1.4.6, `DEFAULT_MODEL_PATH`; 같은 날 PR #112 는 `risk_model_v1.4.5.json`, 2026-11-23 은 `risk_model_v1.4.3.json`·`risk_model_v1.4.2.json`·`risk_model_v1.4.1.json`, 2026-11-20–22 는 `risk_model_v1.4.json`)이고 이 파일은 이름 있는 계수의 원본으로 남는다. v1–v1.2.1 JSON 도 적재한다
(패턴 없는 JSON 은 최상위 계수 집합 하나로, 없는 키는 규칙 미적용).

런타임은 이름 없는 이미지+업종 집합(`nameless_patterns["x2_whole+x4"]`)의 **곱하기 항**도 읽는다(2026-11-24, 설계 §7-12 — 서비스 기본
v1.4.5 가 선형 곱을 쓴다, 아래): `features` 의 `x2_whole×x4`·`x2_whole×도형계×x4`(선형 곱)나 `hinge(x2_whole;c문자계;c도형계)×x4`·
`…×도형계×x4`(꺾인 곱 — max(0, x2_whole − c)·x4, c 는 유형 묶음별), 계수 ≥ 0, 기여도는 X4. 그 집합에 `goods_rule:
"no_raise_without_overlap"` 가 있으면 적재 검증이 이미지만 → 이미지+업종 결합(겹침 하한에서 이상) 대신 "업종 겹침 0 에서 이미지만
이하"를 본다(업종이 겹칠 때 이미지만 등급 아래로 내려가지 않는 것은 엔진 업종 하한이 맡음). 곱하기 항이 없는 JSON 은 예전과 같다.

이름 있는 업종 두 벌(`patterns["x4"]`·`patterns["x2_whole+x4"]`)의 곱하기 항·업종 규칙과 업종 상한 표시도 읽는다(2026-11-24, 설계
§7-13 — 이름 있는 쪽 곱하기 항·`goods_rule`·자기 하한은 4-b 시도(미채택)의 형식이라 **지금 쓰는 JSON 은 없고**, 최상위 `goods_cap` 은
v1.4.6 이 켠다): 이름 곱 `x1_d×x4`·`x2_text_d×x4`·`x3_d×x4`·
`x1_d×문자계×x4`·`x1_d×any_no_distinctive×x4`(x2_whole+x4 는 이미지 곱 `x2_whole×x4`·`x2_whole×도형계×x4` 도), 짝 위험도 곱
`pair(base)×x4`·`pair(x2_whole)×x4`(짝 계수 집합의 위험도 × 겹침 — 그 짝일 때만), 계수 ≥ 0, 기여도는 X4. 그 집합의 `goods_rule:
"no_raise_without_overlap"` 은 적재 검증이 짝 → 그 집합 결합(겹침 하한에서 이상) 대신 "겹침 0 에서 짝 이하"를 보게 하고, 엔진은 업종이
겹치면(겹침 ≥ `coupling.floors.x4`) 짝 판단의 등급 아래로 내려가지 않게 한다(rule_triggers `goods_floor_named`). 그 집합의
`grade_thresholds` 는 그 집합만의 등급 하한이다(응답 `meta.thresholds.named`). 최상위 `goods_cap: {"enabled": true}` 는 엔진의 업종
상한이다 — 업종이 다르면(겹침 < `coupling.floors.x4`) 이름 없는 이미지+업종·이름 있는 업종 두 벌 모두 짝 판단의 등급 이하(rule_triggers
`goods_cap`; 짝 판단의 등급은 단독 축·도형 규칙까지 반영한 등급, 상한은 내리기만 함). 이 키들이 없는 JSON(v1.4.5 까지)은 예전과 같다.

## `risk_model_v1.4.6.json` — v1.4.6 (업종 상한), 서비스 기본 모델 (2026-11-24)

**2026-11-24 부터 서비스가 읽는 기본 모델이다**(`ml/src/model/risk_model.py` `DEFAULT_MODEL_PATH` = `V146_MODEL_PATH`, `MARKLENS_RISK_MODEL` 로 바꿀 수 있음 —
파일을 바꾸면 서버를 다시 띄운다). 아래 `risk_model_v1.4.5.json` 에 최상위 `goods_cap: {"enabled": true}` 만 켠 것이다 — 계수·기준·단독 임계값·도형 규칙·
`logo_floor`·`weak_run`·이름 없는 이미지+업종 집합의 `goods_rule`·`grade_precision` 은 v1.4.5 그대로. 엔진은 업종이 다를 때(겹침 < `coupling.floors.x4`
0.0252) 업종 집합의 등급을 업종 없는 짝 판단의 등급 이하로 내린다 — 이름 없는 이미지+업종 ↔ 이미지만, 이름+업종(`x4`) ↔ 이름만(`base`),
이름+이미지+업종(`x2_whole+x4`) ↔ 이름+이미지(`x2_whole`); 짝 판단 등급은 단독 축·도형 규칙까지 반영한 등급이고 상한은 내리기만 한다(rule_triggers
`goods_cap`, 계약 v2 §2-4 9항). 이름 있는 업종 두 벌에 곱하기 항을 넣는 4-b 시도는 채택 조건 ④ 미달·시연 스타벅수 하락으로 사람 결정 미채택이고
그 대신 켠 것이다(설계 §7-13). 미리 고정한 확인 조건 ①–④(시연 넷 그대로·질의 전체 등급은 내려간 것만 — 2,180 중 2·표본 A 인용상표 70.7% 그대로·원칙
상설 시험 통과)를 모두 넘었다(`meta.goods_cap` 에 결정 문구·설정 sha256·확인 결과). `ml/scripts/goods_cap.py apply` 가 v1.4.5 JSON 과 그 실행의
후보에서 만든다 — v1.4.5 와 다른 키는 `version`·`goods_cap`·`meta.goods_cap` 뿐이고 `ml/tests/test_risk_model.py` 가 이를 고정한다. v1.4.5 JSON 을
다시 쓰면 이 파일도 다시 만들어야 한다.

## `risk_model_v1.4.5.json` — v1.4.5 (이름 없는 이미지+업종 판단의 로고 유사도 × 업종 겹침 곱하기 항), v1.4.6 의 원본 (2026-11-24)

2026-11-24 PR #112 의 서비스 기본 모델이었고(`V145_MODEL_PATH`) 같은 날 v1.4.6(업종 상한)의 원본이 됐다. 아래 `risk_model_v1.4.3.json` 에서 이름 없는 이미지+업종 집합(`nameless_patterns["x2_whole+x4"]`)만 바꾼 것이다 — 이름
있는 4벌·이미지만 집합·등급 하한·단독 임계값·도형 규칙·`logo_floor`·`weak_run`·`grade_precision` 은 v1.4.3 그대로. 그 집합은 로고 유사도 × 업종 겹침의
곱하기 항(변형 L)으로 다시 학습했다 — 절편 −3.2887, `x2_whole` 3.5147·`x2_whole×도형계` 0.3229·`x4` 0.506·`x2_whole×x4` 0.9857·`x2_whole×도형계×x4` 0
(학습 데이터에 같은 업종 음성 449 포함, 이름 있는 4벌·이미지만 집합은 고정). 업종의 효과가 로고가 닮은 만큼만 생긴다 — 도형계 위험도는 이미지
0.3·0.5·0.7·0.9 에서 겹침 0 이면 0.106·0.203·0.354·0.541, 겹침 1 이면 0.208·0.408·0.644·0.826(v1.4.3 은 0.229·0.327·0.443·0.566 / 0.578·0.691·0.786·
0.857). 그 집합의 `goods_rule` "no_raise_without_overlap" 은 상품을 더 관측할 때의 결합 제약 대신 "업종 겹침 0 이면 이미지만 판단 이하"를 적재 때 검사하게
하고(겹침 ≥ 0.0252 일 때 이미지만 등급 아래로 내려가지 않는 것은 엔진의 업종 하한), 등급 하한은 이미지만 집합과 같은 0.3677·0.491·0.5724 다(같은 대조군으로
재 보니 목표 안 — v1.4.3 은 0.2944·0.4441·0.7892). 미리 고정한 채택 조건 일곱 가지 중 ③(표본 A 인용상표의 이름 없는 판단 검토 권장 이상 ≥ 지금의 절반)이
36.6% → 11.2% 로 미달이었지만 사람 결정으로 채택했다(`meta.nameless.goods_product.adopted` 에 결정 문구·규칙 판정). `ml/scripts/goods_product.py apply
--variant L --decision …` 가 v1.4.3 JSON 과 그 실행의 후보에서 만든다 — v1.4.3 과 다른 키는 `version`·`nameless_patterns["x2_whole+x4"]`·
`meta.nameless.goods_product`(변형·원본 버전·설정 sha256·학습·기준·이전 집합·채택 근거)뿐이고 `ml/tests/test_risk_model.py` 가 이를 고정한다. v1.4.3 JSON 을
다시 쓰면 이 파일도 다시 만들어야 한다.

## `risk_model_v1.4.3.json` — v1.4.3 (설명적 낱말만의 이름 — 식별력 결합 규칙 v0.4), v1.4.5 의 원본 (2026-11-23)

**2026-11-23 서비스가 읽던 기본 모델이고, 지금은 v1.4.5 의 원본이다**(런타임 `V143_MODEL_PATH`). 아래 `risk_model_v1.4.2.json` 에 `weak_run` 표시(`{"version": 2, …}` — 규칙·근거 문장 포함)만 더한 것이다 — 계수·하한·단독
임계값·도형 규칙·결합 제약·`logo_floor`·`grade_precision` 은 v1.4.2 그대로. 엔진이 이름 축을 계산할 때 식별력 결합 규칙의 약한 토큰열을 규칙 2(두 이름 모두에서
연속으로 붙어 있는 공통 약한 토큰 구간만 요부 후보로 묶음 — 어느 한쪽에서라도 다른 낱말이 끼면 묶지 않음)로 쓴다(`salient.removed` 가 그 결과, 식별력 v0.4, 견고성
점검 R-P0-2, 통합 모델 설계 §7-10). 계수가 학습된 특징은 규칙 1(v0.2–v0.3)이지만 규칙 2 로 다시 만들어도 바뀌는 행이 0이라 계수를 그대로 쓴다. 표시가 없는 v1.4.2
JSON 을 `MARKLENS_RISK_MODEL` 로 지정하면 예전 계산이다(런타임 `weak_run_version` — 없으면 1, 형식은 `validate_model` 이 1·2 만). `ml/scripts/weak_run_adjacent.py apply`
가 v1.4.2 JSON 에서 만든다 — v1.4.2 와 다른 키는 `version`·`weak_run`·`meta.weak_run`(원본 버전·설정 sha256·스크립트)뿐이고 `ml/tests/test_risk_model.py` 가 이를 고정한다.
v1.4.2 JSON 을 다시 쓰면 이 파일도 다시 만들어야 한다.

## `risk_model_v1.4.2.json` — v1.4.2 (같은 로고 + 다른 이름 — 이미지만 판단과 견주기), v1.4.3 의 원본 (2026-11-23)

**2026-11-23 그 전 서비스가 읽던 기본 모델이고, 지금은 v1.4.3 의 원본이다**(런타임 `V142_MODEL_PATH`). 아래 `risk_model_v1.4.1.json` 에 `logo_floor` 표시(`{"enabled": true, …}` — 적용 범위·근거 문장 포함)만 더한 것이다 — 계수·
하한·단독 임계값·도형 규칙·결합 제약·`grade_precision` 은 v1.4.1 그대로. 표시가 켜져 있으면 엔진이 이미지가 있는 이름 있는 질의(질의 이미지가 사진이 아니고 유형을
도형계로 고치지 않은 것)에서 후보마다 이름도 업종도 뺀 이미지만 판단(`noname:x2_whole`)과 견줘 높은 등급·정렬 위치를 쓴다(`rule_triggers` `nameless_floor`,
API 계약 v2 §2-4 6항, 견고성 점검 R-P0-1, 통합 모델 설계 §7-9). 표시가 없는 v1.4.1 JSON 을 `MARKLENS_RISK_MODEL` 로 지정하면 예전 동작이다(런타임
`logo_floor_enabled`, 형식은 `validate_model` 이 검사). `ml/scripts/logo_floor_image_only.py apply` 가 v1.4.1 JSON 에서 만든다 — v1.4.1 과 다른 키는 `version`·
`logo_floor`·`meta.logo_floor`(원본 버전·설정 sha256·스크립트)뿐이고 `ml/tests/test_risk_model.py` 가 이를 고정한다. v1.4.1 JSON 을 다시 쓰면 이 파일도 다시 만들어야 한다.

## `risk_model_v1.4.1.json` — v1.4.1 (이름 있는 판단의 검토 권장 하한), v1.4.2 의 원본 (2026-11-23)

**2026-11-23 그 전 서비스가 읽던 기본 모델이고, 지금은 v1.4.2 의 원본이다**(런타임 `V141_MODEL_PATH`). 아래 `risk_model_v1.4.json` 에서 최상위 `grade_thresholds` 의 검토 권장만 0.1805 → **0.5059** 로 바꾼 것이다(이름 있는 계수 집합 4벌이
같이 쓰는 하한 — 주의 0.0902·위험 0.5902·계수·이름 없는 집합과 그 하한·단독 임계값·도형 규칙·결합 제약·`grade_precision` 은 v1.4 그대로). 값은 실제 검색 기준이다 —
지어낸 상표명 대조군에서 무관한 후보 중 최고 위험도가 검토 권장 이상인 질의가 네 집합 모두 10% 이하가 되는 가장 낮은 공통 값(통합 모델 설계 §7-6-2).
`ml/scripts/named_shared_threshold.py apply` 가 v1.4 JSON 에서 만든다 — v1.4 와 다른 키는 `version`·`grade_thresholds`·`grade_basis`·`meta.named_grade_thresholds`(출처·설정
sha256·집합별 값·이전 값)뿐이고 `ml/tests/test_risk_model.py` 가 이를 고정한다. v1.4 JSON 을 다시 쓰면(이름 없는 하한 재계산 등) 이 파일도 다시 만들어야 한다(설정을 다시
고정한 뒤 `run`·`apply`).

## `risk_model_v1.4.json` — v1.4 (2차 학습), v1.4.1 의 원본 (2026-11-19 학습 · 2026-11-20–22 서비스 기본 모델)

**2026-11-20–22 서비스가 읽던 기본 모델이고, 지금은 v1.4.1 의 원본이다**(런타임 `V14_MODEL_PATH` — 이름 없는 하한 스크립트·v1.4 학습 스크립트가 이 파일을 쓴다). `risk_model_v1.4.json`(version `risk_model_v1.4`)은 v1.3 JSON 에 이름 없는 입력용 계수 집합 2벌을 덧붙인 것으로, `ml/scripts/train_risk_model_v14_nameless.py` 가
결과 전에 고정한 채택 기준 ①–④를 모두 채웠을 때만 쓴다(통합 모델 설계 §7-4-2). 이름 없는 입력의 등급 하한은 `ml/scripts/nameless_search_thresholds.py` 가 실제 검색
기준으로 쓴다(설계 §7-4-4) — 학습 스크립트·옛 하한 스크립트(`nameless_grade_thresholds.py`, §7-4-3)는 같은 값을 옛 방식으로 쓰므로 meta 에 실제 검색 기준
하한이 있으면 `--force` 없이는 쓰지 않는다(종료 코드 4). 런타임 엔진은 이름 없는 이미지+상품 판단에 업종 하한(`goods_floor`, 상품 겹침 ≥ `coupling.floors.x4`
0.0252 면 이미지만 판단과 견줘 높은 등급)을 적용한다.

| 키 | 내용 |
|---|---|
| `patterns`·`features`·`coefficients`·`intercept`·`grade_thresholds`·`standalone_thresholds`·`figure_rule`·`meta.grade_precision` | **v1.3 JSON 을 그대로 복사**(재학습 없음 — `figure_rule.caveat` 문구만 2026-11-20 서비스 문구로). 이름 있는 입력(호칭·철자 중 하나라도 있음)과 이름도 이미지도 없는 입력의 출력은 v1.3 과 완전히 같다 — 무작위 입력 20,000개·학습에 쓴 이름 있는 491행에서 차이 0. 위험 하한 0.5902 는 정밀도 0.8 목표(지지 30) 미달 대체값 |
| `nameless_patterns` | 이름 없는 입력(호칭·철자 둘 다 결측)에 이미지가 있을 때 쓰는 계수 집합: `x2_whole`(이미지만 — 절편 −1.9187, x2_whole 2.1447, x2_whole×도형계 0.3229) / `x2_whole+x4`(이미지+상품 — 절편 −1.9572, 같은 이미지 계수, x4 1.5302). 입력 항은 이미지·상품뿐이고 `RiskResult.pattern` 은 "noname:" + 키. 이미지가 관측된 모든 학습 행(1,010·727행 — 이름이 있는 행도 이름을 가리고 참여)으로 적합, 사건 단위 가중, 사진이 낀 쌍 제외 |
| `nameless_patterns[키].grade_thresholds` | **이름 없는 입력의 등급 하한**(그 계수 집합이 쓰인 판단에만 — `rm.grade_thresholds_for(model, pattern)`, 응답 `meta.thresholds.nameless`): `x2_whole` 주의 0.3677·검토 권장 0.4910·위험 0.5724 / `x2_whole+x4` 주의 0.2944·검토 권장 0.4441·위험 0.7892. 실제 검색 기준(2026-11-20, 설계 §7-4-4) — 심사를 거치지 않은 표장 184질의(정답 데이터의 거절결정불복 출원 표장·권리범위확인 확인대상표장 중 DB 에 없는 것)로 검색한 후보 쌍에서 이름 없는 판단이 그 등급 이상인 비율을 같은 쌍을 이름을 알고 채점했을 때와 맞춤(같은 출원인 후보는 `shared/applicant_aliases.json` 까지 써서 뺌). 산출 방법·표본·DB 300질의 확인값·규칙 sha256·이전 값 이력은 `meta.nameless.grade_thresholds`. 도형 caveat 문구(`figure_rule.caveat`)는 서비스 문구로 바꿨다(이전 문구는 `meta.figure_caveat_history`) |
| `coupling.same_name` | 이름 없는 입력에 후보와 **같은 이름**(호칭·철자 1.0)을 더했을 때 이름 있는 패턴의 로짓 ≥ 이름 없는 패턴의 로짓 — 더한 뒤의 유형은 서비스 규칙대로 문자계, 요부 있음·없음 둘 다, 이미지·상품 값의 모든 꼭짓점. 적재 때 검증한다(어기면 ValueError). `coupling.floors` 는 v1.3 값 그대로이고 이름 없는 두 집합 사이의 축 결합(상품을 하한 이상으로 더하면 비감소)에도 쓴다 |
| `meta.named_from`·`meta.nameless` | 이름 있는 쪽의 출처(v1.3, 2026-10-25)와 이름 없는 2벌의 학습 메타(행 수·사건 가중·사진 규칙·사전분포·OOF 지표·채택 판정). 최상위 `meta` 의 n·AUC·`grade_precision` 은 v1.3 학습 때의 값 |

- 채택 판정(설계 §7-4-2): ① 이름 있는 입력 불변 ② 이름 없는 75행 Brier 0.529 → 0.213(짝 차이 −0.316, CI −0.423–−0.200)·AUC 0.758 → 0.797 ③ 쉬운 음성을 섞은 AUC 0.816 →
  0.893(짝 차이 +0.077, CI +0.050–+0.104) ④ 단조성 위반 0. 이미지만 입력(도형계)의 위험도는 이미지 유사도 0.5 / 0.7 / 0.9 / 1.0 에서 0.335 / 0.452 / 0.575 / 0.634
  (v1.3 은 0.038–0.065) — 등급은 새 하한으로 주의 / 검토 권장 / 검토 권장 / 검토 권장(도형계 이미지 유사도 0.39 부터 주의, 0.66 부터 검토 권장).
- 등급 하한만 다시 계산: `ml/venv/bin/python ml/scripts/nameless_grade_thresholds.py`(1초 — 계수는 그대로 두고 이 파일의 하한만 갱신, `--dry-run` 은 쓰지 않음). 학습
  스크립트도 채택했을 때 같은 규칙으로 하한을 붙여서 쓴다. 보고는 `ml/data/trials/risk_model_v1.4_thresholds_{report.md,results.json}`.
- 재학습: `ml/venv/bin/python ml/scripts/pairs_features.py`(심결 특징) → `ml/venv/bin/python ml/scripts/pairs_features.py --refresh-easy`(쉬운 음성) →
  `ml/venv/bin/python ml/scripts/train_risk_model_v14_nameless.py`(6초, KIPRIS 호출 0 — 기준을 하나라도 못 채우면 이 파일을 쓰지 않고 종료 코드 3). 보고는 비공개 데이터
  저장소의 `ml/data/trials/risk_model_v1.4_attempt2_{report.md,results.json}`.
- 1차 시도(`ml/scripts/train_risk_model_v14.py` — 여섯 집합을 모두 다시 학습 + `coupling.name_floors`)는 채택 기준 ①·② 미달로 채택하지 않았다(설계 §7-4-1). 런타임은 그
  형식(`name_floors`)도 적재할 수 있지만 재현용이고, 이 디렉터리에 그 파일은 없다.
- 런타임 `MODEL_VERSION`·`DEFAULT_MODEL_PATH` 는 v1.4.1(2026-11-23 부터; 2026-11-20–22 는 v1.4). 다른 파일을 읽으려면 경로를 명시한다(`rm.load_model(path)` 또는 환경변수 `MARKLENS_RISK_MODEL`).
- 축 계산 버전(2026-11-20): 계수 JSON 은 `axis_versions`(예: `{"x2_text": 2}`)로 그 계수가 학습된 축 정의를 밝힐 수 있다 — 없으면 모두 1(v1.3·v1.4). 입력의
  `x2_text_version`(`pair_axes.model_features` 가 싣는다, 없으면 1)이 다르면 `risk_score` 가 ValueError 를 내고, 엔진은 모델이 요구하는 철자 버전으로 축을 계산한다.
  철자 v2 를 요구하는 JSON 은 아직 없다(통합 모델 설계 §7-5 — 철자 v2 는 측정의 진행 조건 미달로 v1 유지).

## `photo_direction_v1.json` — 사진 표장 판정 방향 벡터 (2026-11-19)

`ml/src/photo_mark.py` 가 읽는다. 표장 이미지가 실물·장면을 찍은 사진(간판·제품·포장·입체물)인지 그래픽(평면 로고·문자·스캔)인지를 CLIP 이미지 임베딩 e 하나로
가른다: `score = e · direction`, `score > threshold(0)` 이면 사진. direction = normalize(mean(사진 문장 8개의 텍스트 임베딩)) − normalize(mean(그래픽 문장 8개)) —
문장은 파일의 `prompts` 에 있고, 모델·임베딩 계약(`ViT-B-32`·`laion2b_s34b_b79k`·`openclip-image-v2`)이 `ml/src/contracts.py` 와 다르면 적재하지 않는다. 판정에는 텍스트
인코더가 필요 없다(numpy 내적). 눈으로 확인한 30쌍에서 쌍 27/30·이미지 55/60(통합 모델 설계 §7-4). 지금 쓰는 곳은 학습 특징의 `사진A`·`사진B` 열
(`pairs_features.py`)뿐이고 서비스 연결은 다음 단계다. 재생성(문장을 바꿨을 때만 — 바꾸면 표본 확인도 다시): `cd ml && venv/bin/python -m src.photo_mark`. 경로는
환경변수 `MARKLENS_PHOTO_DIRECTION` 으로 바꿀 수 있다.
