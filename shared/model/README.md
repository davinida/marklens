# 통합 모델 계수 (다빈, 프론트-9)

`risk_model_v1.json`(version `risk_model_v1.3`, 2026-10-25 — v1.2.1 은 2026-10-11 모델 단계 마감) — `ml/scripts/train_risk_model.py` 가 심결례 정답
데이터(`ml/data/trials/pairs_features.csv` + 쉬운 음성 `pairs_features_easy.csv`, 2026-10-25 부터 쉬운 음성에도 CLIP 이미지 축)로 학습해 쓴
**판례 사전분포 + 단조 제약 + 결합 제약 로지스틱 회귀** 계수. 런타임 `ml/src/model/risk_model.py` 의 `risk_score(features)` 가 읽어
`RiskResult(prob, grade, contributions, figure_caveat, pattern)` 를 내고(픽클 없음, 적재 때 단조·결합 제약 검증), 서비스 엔진
`backend/src/core/multi_search.py` 가 세 입력 통합 검색(API 계약 v2)에서 후보마다 호출한다. 학습 결과·해석·한계는
`docs/MarkLens_통합모델_설계.md` §7~§7-3(v1.3 은 §7-3), 전체 표는 `ml/data/trials/risk_model_v1_report.md`(비공개). EBM·GBM 비교 실험은
`ml/requirements-experiments.txt` 를 설치한 뒤 `--methods` 로.

| 키 | 내용 |
|---|---|
| `pattern_axes`·`patterns` | v1.3 **결측 패턴별 계수 집합**: 패턴 축 `x2_whole`(이미지)·`x4`(상품)의 관측 조합 네 개 `base` / `x2_whole` / `x4` / `x2_whole+x4` 마다 `requires`·`features`·`coefficients`·`intercept`·`meta`(n·클래스·자기 패턴 행·OOF AUC). 런타임이 입력에서 관측된 축으로 하나를 고른다(관측된 축만 입력, 결측 지시변수 없음; 관념 축은 게이트가 꺼지면 값 0). 각 집합은 그 축들이 관측된 모든 행(base 는 1,014행 전부)으로 적합 |
| `reference_pattern`·`features`·`coefficients`·`intercept` | 기준 패턴(`x2_whole+x4`, 모든 축 관측)의 계수 집합을 최상위에 그대로 둔다(옛 코드 호환, 절편 −3.4712). 표준화 없음 — 0~1 점수에 바로 곱한다. 기여도 `miss_pattern` = 쓰인 패턴 절편 − 기준 절편(엔진 `missing_adjustment`; base −0.165·x2_whole −0.339·x4 +0.018) |
| `coupling` | 결합 제약: 축 하나를 `floors`(쉬운 음성 비유사 쌍 평균 — 이미지 0.3487·상품 0.0252) 이상으로 더 관측하면 로짓이 내려가지 않는다(설계 항 상자의 모든 꼭짓점에서; 학습은 SLSQP 선형 제약, 런타임은 적재 때 `coupling_violations` 로 검증). "입력을 더 주면 위험도가 내려가지 않음" 성질의 근거 |
| `method`·`prior`·`monotone` | 채택 방법(prior_monotone_logistic), 사전평균 μ·σ(`applies_to` 유사도 축·교호작용만, 절편 자유; σ 1.0 고정 — `hyper` 1.0, `meta.sigma_selection` "fixed"), 단조 제약(유사도 축 본체 ≥ 0, x2_whole 본체 + 도형계 ≥ 0, x1 본체 + 문자계·요부없음 교호작용 모든 조합 ≥ 0 — 패턴마다) |
| `figure_rule` | 도형계(도형·결합-도형요부) 입력의 제품 규칙(v1.2, `validated` false): `figure_caveat` True + 화면 문구 `caveat`, x2_whole ≥ `threshold`(0.9) 면 등급 하한 검토 권장 |
| `grade_thresholds` | 등급 하한 p: 주의 0.0902 / 검토 권장 0.1805 / 위험 0.5902(안전은 0~주의 하한). 심결+cross+db OOF(행마다 자기 패턴) 기준 — 위험은 정밀도 ≥ 0.8·최소 지지 30(`meta.risk_min_support`)을 채우는 p 가 없어 대체값(검토 권장 하한과 1.0 의 중간; 위험 등급 정밀도 0.7039·152쌍 = `meta.grade_precision`, 계약 v2 "10건 중 7건"), 검토 권장은 재현율 ≥ 0.9, 주의는 검토 권장의 절반 |
| `standalone_thresholds`·`standalone_precision` | 축별 단독 임계값 τ(정밀도 ≥ 0.7 지점; 97후3050 후단: τ 이상이면 등급 하한 검토 권장): x1_d 0.98·x2_text_d 0.75·x3_d 0.7707, x2_whole·x4 는 null(비활성) |
| `removed_terms` | 쓰지 않는 항(유형 주효과·miss_x1·miss_x2text·has_distinctive_part_a/b·miss_x2img·miss_x4·miss_x3 — 요부는 `any_no_distinctive`, 결측은 패턴) |
| `meta` | n·CV AUC(심결 0.6184·현실 0.9113)·Brier·채택 규칙·입력 정의·`sigma_selection`·`risk_min_support`·`grade_precision`·`pattern_choice`·`coupling_floors`·`monotonicity`(학습 행 검사)·`indicator_reference`(지시변수 구조 참고 모델 — miss_x2img 0.56) |

재학습(프로젝트 루트, KIPRIS 호출 0, 기본 2방법 약 13초): `ml/venv/bin/python ml/scripts/pairs_features.py --fill-easy-images`(쉬운 음성 이미지 축, 5초) →
`ml/venv/bin/python ml/scripts/train_risk_model.py`. 런타임 `MODEL_VERSION` 은 risk_model_v1.3 이고 v1~v1.2.1 JSON 도 적재한다(패턴 없는 JSON 은 최상위
계수 집합 하나로, 없는 키는 규칙 미적용).

## v1.4 (2차 학습) — 채택 보류, 이 디렉터리에 파일 없음 (2026-11-19)

1·2차 정답 데이터(566행 + 쉬운 음성 700)로 다시 학습한 v1.4 는 결과 전에 고정한 채택 기준 ①·②에 걸려 채택하지 않았다(통합 모델 설계 §7-4 — 1차 가중 AUC 짝 차이
−0.074, 판례 (i)·(iv) 부트스트랩 성립 비율 하락; 원인은 이름 결합 제약). **`risk_model_v1.4.json` 은 만들지 않았고 서비스 기본 모델은 위 v1.3 파일 그대로다.** 후보
계수·표는 비공개 데이터 저장소의 `ml/data/trials/risk_model_v1.4_{candidate.json,report.md,results.json}`.

- 학습·평가: `ml/venv/bin/python ml/scripts/train_risk_model_v14.py`(약 40초, KIPRIS 호출 0). 채택 기준을 통과하면 `shared/model/risk_model_v1.4.json` 에 쓰고, 못
  미치면 후보 파일만 쓰고 종료 코드 3(`--force-model` 은 사람이 채택을 정했을 때). 먼저 `pairs_features.py`(심결 특징) → `pairs_features.py --refresh-easy`(쉬운 음성).
- 런타임은 v1.4 JSON 을 적재할 수 있다(version `risk_model_v1.4`): `nameless_patterns`(이름 없는 입력의 계수 집합 — 키 `x2_whole`·`x2_whole+x4`, 입력 항은 이미지·
  상품뿐, `RiskResult.pattern` = "noname:" + 키)와 `coupling.name_floors`(이름을 이 값 이상으로 더 관측하면 로짓 비감소 — 적재 때 검증). 이 키가 없는 JSON(v1.3
  이하)의 계산은 달라지지 않는다. `MODEL_VERSION`·`DEFAULT_MODEL_PATH` 는 v1.3 그대로.

## `photo_direction_v1.json` — 사진 표장 판정 방향 벡터 (2026-11-19)

`ml/src/photo_mark.py` 가 읽는다. 표장 이미지가 실물·장면을 찍은 사진(간판·제품·포장·입체물)인지 그래픽(평면 로고·문자·스캔)인지를 CLIP 이미지 임베딩 e 하나로
가른다: `score = e · direction`, `score > threshold(0)` 이면 사진. direction = normalize(mean(사진 문장 8개의 텍스트 임베딩)) − normalize(mean(그래픽 문장 8개)) —
문장은 파일의 `prompts` 에 있고, 모델·임베딩 계약(`ViT-B-32`·`laion2b_s34b_b79k`·`openclip-image-v2`)이 `ml/src/contracts.py` 와 다르면 적재하지 않는다. 판정에는 텍스트
인코더가 필요 없다(numpy 내적). 눈으로 확인한 30쌍에서 쌍 27/30·이미지 55/60(통합 모델 설계 §7-4). 지금 쓰는 곳은 학습 특징의 `사진A`·`사진B` 열
(`pairs_features.py`)뿐이고 서비스 연결은 다음 단계다. 재생성(문장을 바꿨을 때만 — 바꾸면 표본 확인도 다시): `cd ml && venv/bin/python -m src.photo_mark`. 경로는
환경변수 `MARKLENS_PHOTO_DIRECTION` 으로 바꿀 수 있다.
