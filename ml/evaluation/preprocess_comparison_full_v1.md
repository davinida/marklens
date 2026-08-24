# MarkLens 전처리 비교 평가 v1

생성 시각: `2026-08-14T14:43:29.306245+00:00`

## 결론

- 내부 paired gate: **미통과**
- 전처리 결정: `retain_legacy_pending_better_evidence`
- OpenCLIP fine-tuning: `prohibited_label_data_not_ready`
- 이 평가는 전처리 비교 근거이며 모델 가중치 학습 필요성의 근거가 아닙니다.

## 평가 범위

- 검증된 현재 이미지: 105개
- 모드별 질의: 525개 (원본 105 + 변형 420)
- 변형: rotate_8deg, center_crop_90pct, gray_margin_20pct, jpeg_q60
- 갤러리: 각 전처리로 원본을 메모리에서 다시 임베딩; 운영 FAISS 인덱스 미사용
- 원본 모드: `{'RGB': 105}`
- 종횡비: `{'near_square': 76, 'tall': 1, 'wide': 28}`

## 변형별 결과

| 변형 | 전처리 | exact R@1 | family R@1 | family R@5 | target cosine | non-family margin |
|---|---|---:|---:|---:|---:|---:|
| original | legacy | 96.2% | 100.0% | 100.0% | 1.000000 | 0.392762 |
| original | global | 96.2% | 100.0% | 100.0% | 1.000000 | 0.381650 |
| rotate_8deg | legacy | 95.2% | 99.0% | 100.0% | 0.942973 | 0.347720 |
| rotate_8deg | global | 95.2% | 99.0% | 100.0% | 0.944921 | 0.340673 |
| center_crop_90pct | legacy | 96.2% | 100.0% | 100.0% | 0.954452 | 0.346143 |
| center_crop_90pct | global | 96.2% | 100.0% | 100.0% | 0.958337 | 0.344445 |
| gray_margin_20pct | legacy | 94.3% | 98.1% | 100.0% | 0.906979 | 0.308023 |
| gray_margin_20pct | global | 94.3% | 98.1% | 99.0% | 0.909132 | 0.308131 |
| jpeg_q60 | legacy | 96.2% | 100.0% | 100.0% | 0.987250 | 0.382697 |
| jpeg_q60 | global | 96.2% | 100.0% | 100.0% | 0.991592 | 0.376349 |

## 종횡비 Slice

| Slice | N queries/mode | legacy family R@1 | global family R@1 | legacy margin | global margin |
|---|---:|---:|---:|---:|---:|
| near_square | 304 | 99.0% | 99.0% | 0.327480 | 0.322448 |
| tall | 4 | 100.0% | 100.0% | 0.380144 | 0.487927 |
| wide | 112 | 100.0% | 100.0% | 0.395594 | 0.391355 |

## Paired Bootstrap

105개 원본 이미지를 재표집 단위로 사용하고, 이미지별 네 변형 평균의 `global - legacy` 차이에 대해 결정적 bootstrap을 수행했습니다.

| 지표 | 평균 차이 | 95% CI | 이미지 win/tie/loss |
|---|---:|---:|---:|
| exact_recall_at_1 | 0.000000 | [0.000000, 0.000000] | 0/105/0 |
| family_recall_at_1 | 0.000000 | [0.000000, 0.000000] | 0/105/0 |
| target_similarity | 0.003082 | [-0.001159, 0.007541] | 56/0/49 |
| target_to_nonfamily_margin | -0.003746 | [-0.014142, 0.006248] | 44/0/61 |

## 학습 데이터 Readiness Gate

- 상태: **not_ready**
- pack: `vlp2_8f31ac6b34d96b71bd51`
- 라벨 완료: 0/200
- fine-tuning data gate: `False`
- holdout의 학습 사용: `false`
- 미통과 사유: `['dev_has_zero_labels', 'dev_confidence_incomplete', 'dev_annotator_provenance_incomplete', 'dev_trainable_class_minimum_not_met', 'frozen_holdout_has_zero_labels', 'frozen_holdout_confidence_incomplete', 'frozen_holdout_annotator_provenance_incomplete', 'frozen_holdout_trainable_class_minimum_not_met']`

| Split | 라벨 | missing confidence | missing annotator | cannot_assess | class floor |
|---|---:|---:|---:|---:|---:|
| dev | 0/160 | 160 | 160 | n/a | False |
| frozen_holdout | 0/40 | 40 | 40 | n/a | False |

## 해석 제한

- 동일 105개 원본이 갤러리와 질의의 정답인 closed-world self-retrieval입니다.
- 변형은 합성 회전·crop·여백·JPEG이며 실제 촬영·화면 캡처 표본이 아닙니다.
- family 정답은 원본 파일 SHA-256이 같은 출원들만 묶습니다. 사람이 판단한 near-duplicate나 법적 유사 범위가 아닙니다.
- 현재 105개 원본은 모두 RGB이므로 global 후보의 dual-background 분기는 이번 평가에서 실행되지 않았습니다.
- 데이터는 특정 출원인·등록표장 중심 105건이며 독립 holdout이나 전체 상표 모집단을 대표하지 않습니다.
- 전처리를 바꾸면 갤러리와 질의를 함께 재임베딩하고 임계값을 다시 검증해야 합니다.
- fine-tuning은 사람이 라벨한 development/동결 holdout과 외부 실제 입력에서 사전학습 모델의 실패가 재현된 뒤에만 검토합니다.

## 재현 명령

```powershell
.\ml\venv\Scripts\python.exe ml\scripts\compare_preprocessing.py --with-model
```
