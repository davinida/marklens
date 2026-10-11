# 통합 모델 계수 (다빈, 프론트-9)

`risk_model_v1.json` — `ml/scripts/train_risk_model.py` 가 심결례 정답 데이터(`ml/data/trials/pairs_features.csv` + 쉬운 음성)로
학습해 쓴 로지스틱 회귀 계수. 런타임 `ml/src/model/risk_model.py` 의 `risk_score(features)` 가 읽는다(픽클 없음).
학습 결과·해석·한계는 `docs/MarkLens_통합모델_설계.md` §7, 전체 표는 `ml/data/trials/risk_model_v1_report.md`(비공개).

| 키 | 내용 |
|---|---|
| `features`·`coefficients`·`intercept` | 설계 항 이름 순서와 계수(표준화 없음 — 0~1 점수에 바로 곱한다) |
| `grade_thresholds` | 등급 하한 p: 주의 / 검토 권장 / 위험(안전은 0~주의 하한). 심결+cross+db OOF 기준 |
| `standalone_thresholds` | 축별 단독 임계값 τ(97후3050 후단: τ 이상이면 최소 검토 권장). null 은 비활성 |
| `meta` | n·CV AUC·Brier·채택 규칙·입력 정의 |

재학습(프로젝트 루트, KIPRIS 호출 0): `ml/venv/bin/python ml/scripts/train_risk_model.py`
