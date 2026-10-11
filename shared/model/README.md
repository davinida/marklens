# 통합 모델 계수 (다빈, 프론트-9)

`risk_model_v1.json`(version `risk_model_v1.2.1`, 2026-10-11 모델 단계 마감) — `ml/scripts/train_risk_model.py` 가 심결례 정답 데이터(`ml/data/trials/pairs_features.csv`
+ 쉬운 음성)로 학습해 쓴 **판례 사전분포 + 단조 제약 로지스틱 회귀** 계수. 런타임 `ml/src/model/risk_model.py` 의 `risk_score(features)` 가
읽어 `RiskResult(prob, grade, contributions, figure_caveat)` 를 낸다(픽클 없음, 적재 때 단조 제약 검증). 학습 결과·해석·한계는
`docs/MarkLens_통합모델_설계.md` §7~§7-2(v1.2.1 은 §7-2 끝), 전체 표는 `ml/data/trials/risk_model_v1_report.md`(비공개). EBM·GBM 비교 실험은
`ml/requirements-experiments.txt` 를 설치한 뒤 `--methods` 로.

| 키 | 내용 |
|---|---|
| `features`·`coefficients`·`intercept` | 설계 항 이름 순서와 계수(표준화 없음 — 0~1 점수에 바로 곱한다). v1.1 은 유형 주효과·miss_x1·miss_x2text 없음(`removed_terms`) |
| `method`·`prior`·`monotone` | 채택 방법(prior_monotone_logistic), 사전평균 μ·σ(`applies_to` 유사도 축·교호작용만, 절편 자유; σ 는 v1.2.1 부터 1.0 고정 — `hyper` 1.0, `meta.sigma_selection` "fixed"·`meta.sigma_fixed` 사유), 단조 제약(유사도 축 본체 ≥ 0, x2_whole 본체 + 도형계 ≥ 0, x1 본체 + 문자계·요부없음 교호작용 모든 조합 ≥ 0) |
| `figure_rule` | 도형계(도형·결합-도형요부) 입력의 제품 규칙(v1.2, `validated` false): `figure_caveat` True + 화면 문구 `caveat`, x2_whole ≥ `threshold`(0.9) 면 등급 하한 검토 권장 |
| `grade_thresholds` | 등급 하한 p: 주의 0.063 / 검토 권장 0.126 / 위험 0.563(안전은 0~주의 하한). 심결+cross+db OOF 기준 — 위험은 정밀도 ≥ 0.8·최소 지지 30(`meta.risk_min_support`, v1.2.1) 을 채우는 p 가 없어 대체값(검토 권장 하한과 1.0 의 중간; 정밀도 0.69·159쌍), 검토 권장은 재현율 ≥ 0.9, 주의는 검토 권장의 절반 |
| `standalone_thresholds`·`standalone_precision` | 축별 단독 임계값 τ(정밀도 ≥ 0.7 지점; 97후3050 후단: τ 이상이면 등급 하한 검토 권장). null 은 비활성 |
| `removed_terms` | 쓰지 않는 항(유형 주효과·miss_x1·miss_x2text·has_distinctive_part_a/b — 요부는 `any_no_distinctive` 로) |
| `meta` | n·CV AUC·Brier·채택 규칙·입력 정의·`sigma_selection`/`sigma_fixed`·`risk_min_support`(v1.2.1) |

재학습(프로젝트 루트, KIPRIS 호출 0, 기본 2방법 약 8초): `ml/venv/bin/python ml/scripts/train_risk_model.py`. 런타임 `MODEL_VERSION` 은 risk_model_v1.2.1 이고 v1~v1.2 JSON 도 적재한다(없는 키는 규칙 미적용).
