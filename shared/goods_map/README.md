# 프론트-2. 상품↔유사군 변환표

목표: `[상품명, 류, 유사군코드]` 1:N 표를 만들어 프론트-6(지정상품 입력 UI)과
프론트-8(X4 상품 견련성 자카드 계수)이 공동으로 쓴다. 근거:
[docs/MarkLens_작업가이드_프론트.md §프론트-2](../../docs/MarkLens_작업가이드_프론트.md).

## 1. 원본 다운로드 (수동)

지식재산처 고시상품명칭 13판(2026), 엑셀 파일.

- 다운로드 페이지: <https://kipo.go.kr/ko/kpoContentView.do?menuCd=SCD0201120>
  (지식재산처 홈페이지 > 지식재산제도 > 분류코드조회 > 상품분류코드)
- 직접 다운로드 링크: `https://www.kipo.go.kr/ko/kpoContFileDown.do?seq=26&fileNum=19`
  — 헤더 없는 `curl`은 WAF에 걸려 403이 나기도 하지만(2026-09-17 실측. 2026-09-19에는
  헤더 없이도 같은 파일이 받아짐), **브라우저 User-Agent와 referer 헤더를 주면 `curl`로도
  받아진다**(2026-09-17·19 실측 HTTP 200, 13,336,910바이트, `application/download`).
  브라우저로 페이지에 들어가 "지식재산처 고시상품명칭 13판(2026)" 항목을 클릭해 받아도 된다.

  ```bash
  mkdir -p shared/goods_map/raw
  curl -L -o shared/goods_map/raw/고시상품명칭13판.xlsx \
      -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36" \
      -e "https://kipo.go.kr/ko/kpoContentView.do?menuCd=SCD0201120" \
      "https://www.kipo.go.kr/ko/kpoContFileDown.do?seq=26&fileNum=19"
  ```
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

제35류 도소매업 6종을 하나로 합친 항목(§4 "제35류 도소매업 6종 자동 병합")에는 합쳐진
원 명칭 전부가 `aliases`로 붙는다(접미사 순: 도매업·소매업·중개업·판매대행업·판매알선업·
구매대행업, 중복 없음). 병합되지 않은 항목에는 `aliases` 키가 없다. 상품 검색은 `name`과
`aliases`를 함께 대조해야 "화장품 소매업" 같은 원 명칭으로도 찾을 수 있다
(`validate_goods_map.py --search`가 그렇게 동작한다).

```json
{
  "name": "화장품 판매업(도소매·중개·대행)",
  "nice_class": 35,
  "similarity_codes": ["S2012"],
  "aliases": ["화장품 도매업", "화장품 소매업", "화장품 중개업",
              "화장품 판매대행업", "화장품 판매알선업", "화장품 구매대행업"]
}
```

## 4. 검증 (완료 기준)

```bash
ml/venv/bin/python shared/goods_map/validate_goods_map.py \
    shared/goods_map/goods_map.json --search 화장품
```

통과 조건:
- 구조 검증 오류 0건 (name 비어있지 않음 / nice_class 1~45 / 유사군코드 형식)
- "화장품" 검색 시 유사군 코드가 여러 개(1개가 아니라) 나온다 — 1:N 구조 확인
- `aliases`가 있으면 비어있지 않은 문자열 배열·중복 없음·다른 항목 `name`과 충돌 없음
- `--search "화장품 소매업"` 결과에 병합 항목이 `[alias: 화장품 소매업]`으로 잡힌다 — 원 명칭 검색 확인

### 실측 결과 (13판 2026, 2026-09-16 변환 · aliases는 2026-09-19 재변환)

| 항목 | 값 |
|---|---:|
| 원본 행 수(전체 시트 합) | 283,756 |
| 제35류 도소매·중개·대행 6종 조합(중복) | 230,610 |
| **최종 건수** | **91,591** |
| 유사군 2개 이상 | 5,798 (6.3%) |
| NICE 류 커버리지 | 45/45 |
| 결측(빈 행) 스킵 | 154 |
| `aliases` 보유 항목(제35류 병합) | 38,433 (alias 총 230,598개) |
| 파일 크기 | 24.4MB (gzip 약 1.9MB) — aliases 추가 전 12.5MB (gzip 약 0.88MB) |
| 예시: "화장품"(제3류) | `["G1201", "S120907", "S128302"]` — 가이드 문서 예시와 정확히 일치 |

### ⚠️ 제35류 도소매업 6종 자동 병합

원본에는 상품 하나당 "OOO 도매업/소매업/중개업/판매대행업/판매알선업/구매대행업" 6개
행이 있는데, 실측 결과 38,445개 기준 상품 중 38,433개(99.97%)가 6종 모두 **동일한
유사군코드**를 가진다. 유사군 기반 유사도 판단(X4)에는 중복 정보이고, 그대로 두면 자동완성
검색에 같은 상품이 6번씩 뜨는 UX 문제도 생기므로 `parse_goods_map.py`가 자동으로 하나로
합친다:

```json
{ "name": "화장품 판매업(도소매·중개·대행)", "nice_class": 35, "similarity_codes": ["S2012"],
  "aliases": ["화장품 도매업", "화장품 소매업", "화장품 중개업", "화장품 판매대행업", "화장품 판매알선업", "화장품 구매대행업"] }
```

합쳐진 원 명칭 6개는 `aliases`에 보존한다(§3). 병합되지 않고 남는 12건은 도소매 변형이
아니라 **본표(26년 지정상품 고시목록)에 원래 있는 진짜 제35류 서비스업**이다: 광고중개업,
과외 중개업, 상업적 중개업, 전기통신에 의한 통신판매중개업, 공연 종사자 중개업, 광고 관련
중개업, 광고시간 및 공간 임대 관련 중개업, 상품매매 계약중개업, 상품매매에 관한 협상중개업,
상품 및 서비스 매매를 위한 사업중개업, 다양한 전문가와 고객간 매칭 관련 사업중개업, 잠재적
개인 투자자와 자금이 필요한 기업가의 매칭 관련 사업중개업. 이름이 "중개업"으로 끝나 분리
대상에 걸렸다가 6종이 갖춰지지 않아 원문 그대로 남는다(2026-09-19 확인: 12건 모두 본표에만
있고 35류 6개 시트에는 없음). 2026-09-19부터 이 12건은 원문 띄어쓰기를 그대로 유지한다
(이전 변환은 "과외 중개업"을 "과외중개업"처럼 붙여 썼음 — 5건 해당).

## 5. 다음 단계

1. 다빈에게 검증 요청 (다빈-4: 1:N 구조 표본 확인)
2. `shared/goods_map/goods_map.json` 커밋 여부를 팀과 결정 (공공데이터 재배포 가능 여부
   확인 후) — 확정되면 `.gitignore`의 해당 줄을 제거
   - 공공누리 확인 결과 기록: (미확인 — 확인한 사람·날짜·유형·근거 URL을 여기에 적는다)
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
