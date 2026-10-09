# 식별력·요부 필터 v0 산출물 (다빈-3)

`ml/scripts/distinctiveness_build.py` 가 만든다(KIPRIS 호출 0, 3~4초). 설계·근거는 `docs/MarkLens_식별력_설계.md`, 런타임은 `ml/src/axes/distinctiveness.py`.

| 파일 | 내용 | 용도 |
|---|---|---|
| `token_stats.json` | 상표명 토큰별 [서로 다른 출원인 수 A, 등장 수 N] — 심판 목록 42,474건 + DB 1,100건 제목, N ≥ 2 인 7,118 토큰(집계값만, 당사자명 없음) | 런타임이 적재(다수 등록 계수, 2017후2697) |
| `weak_tokens.json` | 전역 판정 점수 < θ(0.5) 인 1,513 토큰·점수·A·N·zipf·사유 | 사람 검토·디버깅(런타임은 읽지 않는다) |
| `report.md` | 사유별 건수, 상위 200(등장 수 순), 임계 민감도 표(θ_A·θ_N 5/10/20 × θ 0.4/0.5/0.6) | 사람 검토 |

재생성(프로젝트 루트):

```bash
ml/venv/bin/python ml/scripts/distinctiveness_build.py            # 기본 θ 0.5 · θ_A 10 · θ_N 20
ml/venv/bin/python ml/scripts/distinctiveness_build.py --theta-a 5 --theta-n 10 --out-dir /tmp/dx   # 비교용
```

입력 `ml/data/trials/list_all.csv`·`ml/data/kipris_metadata.json` 은 비공개 데이터 저장소에 있다. 유명 브랜드 예외는 `shared/famous_brands.txt` 와 `ml/src/axes/korean_brands.py` 를 적재 때 읽는다.
