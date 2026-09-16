# 프론트-2. 상품↔유사군 변환표

목표: `[상품명, 류, 유사군코드]` 1:N 표를 만들어 프론트-6(지정상품 입력 UI)과
프론트-8(X4 상품 견련성 자카드 계수)이 공동으로 쓴다. 근거:
[docs/MarkLens_작업가이드_프론트.md §프론트-2](../../docs/MarkLens_작업가이드_프론트.md).

## 1. 원본 다운로드 (수동)

지식재산처 고시상품명칭 13판(2026), 엑셀 파일.

- 다운로드 페이지: <https://kipo.go.kr/ko/kpoContentView.do?menuCd=SCD0201120>
  (지식재산처 홈페이지 > 지식재산제도 > 분류코드조회 > 상품분류코드)
- 직접 다운로드 링크: `https://www.kipo.go.kr/ko/kpoContFileDown.do?seq=26&fileNum=19`
  — **`curl`로 직접 받으면 403(WAF)이 뜬다.** 반드시 브라우저로 페이지에 들어가서
  "지식재산처 고시상품명칭 13판(2026)" 항목을 클릭해 받는다.
- 받은 파일은 `shared/goods_map/raw/`에 둔다 (이 폴더는 `.gitignore`에 있어 커밋되지
  않음 — 공공데이터 재배포 가능 여부를 다빈이 확인하기 전까지는 원본을 커밋하지 않는다).
  실제 파일명: `shared/goods_map/raw/고시상품명칭13판.xlsx` (13.3MB, 시트 7개).

## 2. 구조 확인 (inspect) — 이미 확인 완료, 아래는 재현용

실제 구조 (2026-09-16 확인):

```
시트: 26년 지정상품 고시목록(출처미포함), 35-도매업, 35-소매업, 35-중개업,
      35-판매대행업, 35-판매알선업, 35-구매대행업  (총 7개)
헤더: 지정상품(국문) | NICE분류 | 유사군코드 | 지정상품(영문)
예)   화장품          | 3        | G1201      | cosmetics
```

새 판(14판 이후)을 받으면 구조가 바뀔 수 있으므로 먼저 재확인한다:

```bash
ml/venv/bin/python -m pip install -r shared/goods_map/requirements.txt
ml/venv/bin/python shared/goods_map/parse_goods_map.py inspect \
    shared/goods_map/raw/고시상품명칭13판.xlsx
```

## 3. 변환 (convert) — 이미 실행 완료, 아래는 재현용

```bash
ml/venv/bin/python shared/goods_map/parse_goods_map.py convert \
    shared/goods_map/raw/고시상품명칭13판.xlsx \
    --name-col "지정상품(국문)" --class-col "NICE분류" --codes-col "유사군코드" \
    --out shared/goods_map/goods_map.json
```

출력 스키마 (`shared/types/goods.ts`의 `GoodsMap`과 동일):

```json
[{ "name": "화장품", "nice_class": 3, "similarity_codes": ["G1201", "S120907", "S128302"] }]
```

같은 상품명이 여러 행에 걸쳐 나오면 유사군코드를 자동으로 합친다 (1:N 유지).

## 4. 검증 (완료 기준)

```bash
ml/venv/bin/python shared/goods_map/validate_goods_map.py \
    shared/goods_map/goods_map.json --search 화장품
```

통과 조건:
- 구조 검증 오류 0건 (name 비어있지 않음 / nice_class 1~45 / 유사군코드 형식)
- "화장품" 검색 시 유사군 코드가 여러 개(1개가 아니라) 나온다 — 1:N 구조 확인

### 실측 결과 (13판 2026, 2026-09-16 변환)

| 항목 | 값 |
|---|---:|
| 원본 행 수(전체 시트 합) | 283,756 |
| 제35류 도소매·중개·대행 6종 조합(중복) | 230,610 |
| **최종 건수** | **91,591** |
| 유사군 2개 이상 | 5,798 (6.3%) |
| NICE 류 커버리지 | 45/45 |
| 결측(빈 행) 스킵 | 154 |
| 파일 크기 | 12.5MB (gzip 약 0.88MB) |
| 예시: "화장품"(제3류) | `["G1201", "S120907", "S128302"]` — 가이드 문서 예시와 정확히 일치 |

### ⚠️ 제35류 도소매업 6종 자동 병합

원본에는 상품 하나당 "OOO 도매업/소매업/중개업/판매대행업/판매알선업/구매대행업" 6개
행이 있는데, 실측 결과 38,445개 기준 상품 중 38,433개(99.97%)가 6종 모두 **동일한
유사군코드**를 가진다. 유사군 기반 유사도 판단(X4)에는 중복 정보이고, 그대로 두면 자동완성
검색에 같은 상품이 6번씩 뜨는 UX 문제도 생기므로 `parse_goods_map.py`가 자동으로 하나로
합친다:

```json
{ "name": "화장품 판매업(도소매·중개·대행)", "nice_class": 35, "similarity_codes": ["S2039"] }
```

6종이 모두 존재하지 않거나 코드가 서로 다른 12건(예외 케이스)은 정보 손실을 막기 위해
원본 접미사를 유지한 채 그대로 남긴다. 이 정책이 맞는지는 다빈 검증(§5) 때 함께 확인 요청.

## 5. 다음 단계

1. 다빈에게 검증 요청 (다빈-4: 1:N 구조 표본 확인)
2. `shared/goods_map/goods_map.json` 커밋 여부를 팀과 결정 (공공데이터 재배포 가능 여부
   확인 후) — 확정되면 `.gitignore`의 해당 줄을 제거
3. 프론트-6에서 `goods_map.json`을 정적 import(또는 `/public`에 두고 fetch)해 상품 검색
   UI에 연결
4. 프론트-8에서 같은 파일의 `similarity_codes`로 두 유사군 집합의 자카드 계수 계산

## 파일 구성

```
shared/goods_map/
├ README.md              # 이 문서
├ requirements.txt        # openpyxl
├ parse_goods_map.py      # inspect / convert
├ validate_goods_map.py   # 구조 검증 + 검색 데모
├ raw/                    # 원본 엑셀 (gitignore, 로컬 전용)
└ goods_map.json          # 변환 산출물 (gitignore, 커밋 여부는 위 §5 참고)
```
