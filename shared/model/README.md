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

## `risk_model_v1.4.json` — v1.4 (2차 학습), 서비스 반영 전 (2026-11-19 · 이름 없는 입력의 등급 하한 2026-11-20)

**서비스가 읽는 기본 모델은 위 `risk_model_v1.json`(v1.3) 그대로다.** `risk_model_v1.4.json`(version `risk_model_v1.4`)은 v1.3 JSON 에 이름 없는 입력용 계수 집합 2벌을
덧붙인 것으로, `ml/scripts/train_risk_model_v14_nameless.py` 가 결과 전에 고정한 채택 기준 ①~④를 모두 채웠을 때만 쓴다(통합 모델 설계 §7-4-2). 이름 없는 입력의 등급
하한은 따로 정했다(2026-11-20, 설계 §7-4-3 — 이름 있는 입력용 v1.3 하한을 그대로 쓰면 이름을 가린 무관한 로고 쌍의 95% 가 "검토 권장"이 되기 때문). 서비스에 반영할 때 할 일은
설계 §6 맨 위 목록.

| 키 | 내용 |
|---|---|
| `patterns`·`features`·`coefficients`·`intercept`·`grade_thresholds`·`standalone_thresholds`·`figure_rule`·`meta.grade_precision` | **v1.3 JSON 을 그대로 복사**(재학습 없음). 이름 있는 입력(호칭·철자 중 하나라도 있음)과 이름도 이미지도 없는 입력의 출력은 v1.3 과 완전히 같다 — 무작위 입력 20,000개·학습에 쓴 이름 있는 491행에서 차이 0 |
| `nameless_patterns` | 이름 없는 입력(호칭·철자 둘 다 결측)에 이미지가 있을 때 쓰는 계수 집합: `x2_whole`(이미지만 — 절편 −1.9187, x2_whole 2.1447, x2_whole×도형계 0.3229) / `x2_whole+x4`(이미지+상품 — 절편 −1.9572, 같은 이미지 계수, x4 1.5302). 입력 항은 이미지·상품뿐이고 `RiskResult.pattern` 은 "noname:" + 키. 이미지가 관측된 모든 학습 행(1,010·727행 — 이름이 있는 행도 이름을 가리고 참여)으로 적합, 사건 단위 가중, 사진이 낀 쌍 제외 |
| `nameless_patterns[키].grade_thresholds` | **이름 없는 입력의 등급 하한**(그 계수 집합이 쓰인 입력에만 — `rm.grade_thresholds_for(model, pattern)`): `x2_whole` 주의 0.2790·검토 권장 0.4258·위험 null / `x2_whole+x4` 주의 0.2221·검토 권장 0.3709·위험 null. 기준 집합 U(이미지가 있는 쉬운 음성 쌍 — 557·449쌍)에서 "무관한 상표 쌍이 그 등급 이상을 받는 비율"을 이름 있는 입력(v1.3)과 맞춘 값(이미지만 주의 33.4%·검토 권장 4.5%, 이미지+상품 60.1%·10.7%). **null = 위험도로는 그 등급에 닿지 않는다**(단독 규칙으로만 — 이름 있는 입력에서 무관한 쌍이 위험을 받은 적이 없다; 이름 없는 입력에 걸리는 단독 규칙은 도형 규칙 τ 0.9 → 검토 권장뿐이라 지금은 위험에 닿지 않는다). 최상위 `grade_thresholds` 는 이름 있는 입력용으로 그대로다. 근거는 `meta.nameless.grade_thresholds` |
| `coupling.same_name` | 이름 없는 입력에 후보와 **같은 이름**(호칭·철자 1.0)을 더했을 때 이름 있는 패턴의 로짓 ≥ 이름 없는 패턴의 로짓 — 더한 뒤의 유형은 서비스 규칙대로 문자계, 요부 있음·없음 둘 다, 이미지·상품 값의 모든 꼭짓점. 적재 때 검증한다(어기면 ValueError). `coupling.floors` 는 v1.3 값 그대로이고 이름 없는 두 집합 사이의 축 결합(상품을 하한 이상으로 더하면 비감소)에도 쓴다 |
| `meta.named_from`·`meta.nameless` | 이름 있는 쪽의 출처(v1.3, 2026-10-25)와 이름 없는 2벌의 학습 메타(행 수·사건 가중·사진 규칙·사전분포·OOF 지표·채택 판정). 최상위 `meta` 의 n·AUC·`grade_precision` 은 v1.3 학습 때의 값 |

- 채택 판정(설계 §7-4-2): ① 이름 있는 입력 불변 ② 이름 없는 75행 Brier 0.529 → 0.213(짝 차이 −0.316, CI −0.423~−0.200)·AUC 0.758 → 0.797 ③ 쉬운 음성을 섞은 AUC 0.816 →
  0.893(짝 차이 +0.077, CI +0.050~+0.104) ④ 단조성 위반 0. 이미지만 입력(도형계)의 위험도는 이미지 유사도 0.5 / 0.7 / 0.9 / 1.0 에서 0.335 / 0.452 / 0.575 / 0.634
  (v1.3 은 0.038~0.065) — 등급은 새 하한으로 주의 / 검토 권장 / 검토 권장 / 검토 권장(도형계 이미지 유사도 0.39 부터 주의, 0.66 부터 검토 권장).
- 등급 하한만 다시 계산: `ml/venv/bin/python ml/scripts/nameless_grade_thresholds.py`(1초 — 계수는 그대로 두고 이 파일의 하한만 갱신, `--dry-run` 은 쓰지 않음). 학습
  스크립트도 채택했을 때 같은 규칙으로 하한을 붙여서 쓴다. 보고는 `ml/data/trials/risk_model_v1.4_thresholds_{report.md,results.json}`.
- 재학습: `ml/venv/bin/python ml/scripts/pairs_features.py`(심결 특징) → `ml/venv/bin/python ml/scripts/pairs_features.py --refresh-easy`(쉬운 음성) →
  `ml/venv/bin/python ml/scripts/train_risk_model_v14_nameless.py`(6초, KIPRIS 호출 0 — 기준을 하나라도 못 채우면 이 파일을 쓰지 않고 종료 코드 3). 보고는 비공개 데이터
  저장소의 `ml/data/trials/risk_model_v1.4_attempt2_{report.md,results.json}`.
- 1차 시도(`ml/scripts/train_risk_model_v14.py` — 여섯 집합을 모두 다시 학습 + `coupling.name_floors`)는 채택 기준 ①·② 미달로 채택하지 않았다(설계 §7-4-1). 런타임은 그
  형식(`name_floors`)도 적재할 수 있지만 재현용이고, 이 디렉터리에 그 파일은 없다.
- 런타임 `MODEL_VERSION`·`DEFAULT_MODEL_PATH` 는 v1.3 그대로다. v1.4 를 읽으려면 경로를 명시한다(`rm.load_model(path)` 또는 환경변수 `MARKLENS_RISK_MODEL`).

## `photo_direction_v1.json` — 사진 표장 판정 방향 벡터 (2026-11-19)

`ml/src/photo_mark.py` 가 읽는다. 표장 이미지가 실물·장면을 찍은 사진(간판·제품·포장·입체물)인지 그래픽(평면 로고·문자·스캔)인지를 CLIP 이미지 임베딩 e 하나로
가른다: `score = e · direction`, `score > threshold(0)` 이면 사진. direction = normalize(mean(사진 문장 8개의 텍스트 임베딩)) − normalize(mean(그래픽 문장 8개)) —
문장은 파일의 `prompts` 에 있고, 모델·임베딩 계약(`ViT-B-32`·`laion2b_s34b_b79k`·`openclip-image-v2`)이 `ml/src/contracts.py` 와 다르면 적재하지 않는다. 판정에는 텍스트
인코더가 필요 없다(numpy 내적). 눈으로 확인한 30쌍에서 쌍 27/30·이미지 55/60(통합 모델 설계 §7-4). 지금 쓰는 곳은 학습 특징의 `사진A`·`사진B` 열
(`pairs_features.py`)뿐이고 서비스 연결은 다음 단계다. 재생성(문장을 바꿨을 때만 — 바꾸면 표본 확인도 다시): `cd ml && venv/bin/python -m src.photo_mark`. 경로는
환경변수 `MARKLENS_PHOTO_DIRECTION` 으로 바꿀 수 있다.
