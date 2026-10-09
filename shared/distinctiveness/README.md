# 식별력·요부 필터 v0 산출물 (다빈-3)

`ml/scripts/distinctiveness_build.py` 가 만든다(KIPRIS 호출 0, 3~4초). 설계·근거는 `docs/MarkLens_식별력_설계.md`, 런타임은 `ml/src/axes/distinctiveness.py`.

| 파일 | 내용 | 용도 |
|---|---|---|
| `token_stats.json` | 상표명 토큰별 [서로 다른 출원인 수 A, 등장 수 N] — 심판 목록 42,474건 + DB 1,100건 제목, N ≥ 2 인 7,118 토큰(집계값만, 당사자명 없음) | 런타임이 적재(다수 등록 계수, 2017후2697) |
| `weak_tokens.json` | 전역 판정 점수 < θ(0.5) 인 1,513 토큰·점수·A·N·zipf·사유 | 사람 검토·디버깅(런타임은 읽지 않는다) |
| `report.md` | 사유별 건수, 상위 200(등장 수 순), 임계 민감도 표(θ_A·θ_N 5/10/20 × θ 0.4/0.5/0.6) | 사람 검토 |
| `descriptive_terms.json` | 3호 기술적 표장 항목(토큰 → kind·absolute·classes·note·examples·approved). 2026-10-09 초안 447항목, 모두 `approved: false` | 런타임이 적재(사람이 승인·편집) |
| `descriptive_candidates.md` | 3호 후보 1,444개의 판례 기준 분류표(포함 447 kind 별·보류 101·제외 896, 증거·이유) | 사람 승인용 |

재생성(프로젝트 루트):

```bash
ml/venv/bin/python ml/scripts/distinctiveness_build.py            # 기본 θ 0.5 · θ_A 10 · θ_N 20
ml/venv/bin/python ml/scripts/distinctiveness_build.py --theta-a 5 --theta-n 10 --out-dir /tmp/dx   # 비교용
ml/venv/bin/python ml/scripts/descriptive_candidates.py                # 3호 후보·분류표·descriptive_terms.json 초안(분류는 ml/scripts/descriptive_judgements.json)
```

3호 승인: `descriptive_candidates.md` 를 보고 `descriptive_terms.json` 의 `approved` 를 `true` 로 바꾸거나 항목을 지운다(근거·절차는 `docs/MarkLens_식별력_설계.md` §3-3).

입력 `ml/data/trials/list_all.csv`·`ml/data/kipris_metadata.json` 은 비공개 데이터 저장소에 있다. 유명 브랜드 예외는 `shared/famous_brands.txt` 와 `ml/src/axes/korean_brands.py` 를 적재 때 읽는다.
