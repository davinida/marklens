# MarkLens X4 상품 견련성 설계

- 기준일: 2026-09-21 (v1) · 구현: `ml/src/axes/x4_goods.py` · 상품명 → 유사군 변환표 로더: `ml/src/axes/goods_map.py` · 테스트: `ml/tests/test_x4_goods.py`, `ml/tests/test_goods_map_loader.py` · 서비스: `GET /goods/search`, `GET /goods/classes`(`backend/src/core/goods.py`, `backend/src/api/goods.py`, BFF `frontend/app/api/goods/*`)
- 규약(공통-2): `goods_similarity(codes_a, codes_b) -> float` 0.0~1.0(높을수록 견련성 큼), 순수 함수·대칭·결정적, 예외 없음, 표준 라이브러리만. `has_goods(codes) -> bool` 은 X1 의 `has_pronunciation` 과 같은 결측 판정이다.

## 1. 정의

자카드 계수 = |A ∩ B| ÷ |A ∪ B|. A·B 는 두 상표의 지정상품 **유사군 코드 집합**이다(상품명 → 코드는 변환표 `codes_for`). 코드는 공백 제거·대문자로 정규화하고, 둘 중 하나라도 비면 0.0 을 돌려준다 — 이때 0.0 은 "비유사"가 아니라 "비교 불가"이므로 `has_goods` 로 먼저 걸러 X4 를 결측 처리한다.

| A | B | 교집합 | 합집합 | X4 |
|---|---|---:|---:|---:|
| {G1201, S120907, S128302} (화장품, 3류) | 같은 집합 | 3 | 3 | 1.000 |
| {G1201, S120907, S128302} | {G1201, S120907, G1202} | 2 | 4 | 0.500 |
| {G1201} (화장품) | {S2012} (화장품 소매업, 35류) | 0 | 2 | 0.000 |
| {G4502} (의류) | {G4503} (신발) | 0 | 2 | 0.000 |
| {G1201} | ∅ | — | — | 0.0 (결측: `has_goods` False) |

## 2. 근사 한계 — 유사군 코드는 근사 기준이다

1. 유사군 코드는 심사 실무의 "유사 추정" 묶음이지 법적 결론이 아니다. 대법원은 유사군 코드를 참고 자료로 보고 상품의 품질·형상·용도·생산 부문·판매 부문·수요자 범위 등 거래 실정으로 판단한다. 같은 유사군이어도 비유사, 다른 유사군이어도 유사로 판단된 사례가 있고 이 함수는 그 예외를 반영하지 못한다.
2. **도소매업은 개별 판단**: 제35류 도소매업 유사군(S20xx)은 취급 상품의 유사군과 묶이지 않아 "화장품"(G1201) 과 "화장품 소매업"(S2012) 은 0.0 이다. 실무에서는 상품과 그 소매업의 견련성을 사안별로 본다. 변환표의 `aliases`(원 명칭 6종)는 검색용이며 계산에 쓰지 않는다.
3. 부분 겹침의 크기와 위험의 크기는 비례하지 않는다(핵심 상품 1개만 겹쳐도 실무상 견련성이 인정될 수 있음). 통합 모델에서 X4 는 표장 유사도를 증폭·억제하는 조정자이며, 표장이 매우 유사한데 상품만 다르면 위험도를 0 으로 내리지 않고 "표장 유사·상품 상이" 참고 경고를 낸다(작업가이드 ML §통합모델 6).
4. 점수는 교정 전 원점수다. 로지스틱 회귀 학습 전 정답 데이터(다빈-1)로 재검토한다.

## 3. 서비스 적용 전제 — DB 유사군 백필 필요

- 현재 DB 1,100건 중 유사군 코드(`유사군` 필드)가 있는 레코드는 **100건(2026-09-21 실측)** 이다. 나머지 1,000건은 2026-08 확장 때 월 예산을 지키려고 서지상세·유사군 보강을 실행하지 않았다(README §데이터 확장과 사람 검수).
- 따라서 입력 상표 ↔ DB 전건 X4 계산은 지금 할 수 없다. 백필은 KIPRIS 서지상세 조회 약 1,000회(월 1,000회 한도, 일일 80회 기본)라 수집 담당과 월별 예산 조율이 먼저다. 백필 전까지 X4 는 결측 처리(`has_goods` False → 다른 축만) 또는 사용자가 입력한 지정상품끼리의 비교에만 쓴다.
- 지정상품 입력(프론트-6)의 데이터 경로는 준비됐다: 화면 → `GET /api/goods/search` → `similarity_codes` → `goods_similarity`. 화면 자체는 미착수.

## 4. 인터페이스

```python
import sys; sys.path.insert(0, "ml")   # 프로젝트 루트에서
from src.axes.goods_map import load_goods_map
from src.axes.x4_goods import goods_similarity, has_goods

gm = load_goods_map()                       # shared/goods_map/goods_map.json.gz → .json (MARKLENS_GOODS_MAP_PATH 로 덮어쓰기)
a = gm.codes_for("화장품", nice_class=3)    # frozenset({'G1201', 'S120907', 'S128302'})
b = gm.codes_for("화장품 소매업")            # alias 정확 일치 → frozenset({'S2012'})
goods_similarity(a, b)                      # 0.0
has_goods(a)                                # True
gm.search("화장품 소매업", limit=3)          # [Match(name='화장품 판매업(도소매·중개·대행)', matched_alias='화장품 소매업', tier=0), ...]
gm.classes()[:2]                            # [{'nice_class': 1, 'count': 2316}, {'nice_class': 2, 'count': 403}]
```

- `codes_for(name, nice_class=None)`: name·aliases 정확 일치(NFKC·casefold·연속 공백 정규화). 같은 이름이 여러 류에 있으면 `nice_class` 로 좁히고 안 주면 합집합, 없으면 빈 집합.
- `search(query, limit=20, nice_class=None)`: 부분 일치. 순위는 정확 > 접두 > 부분, 같은 순위에서 name 일치 > alias 일치, name 짧은 순 → 가나다순. alias 로 잡히면 `matched_alias`.
- 로더 실측(2026-09-21, 이 Mac, 91,591건 + aliases 230,598개): 적재 0.4~0.6초(.gz 440ms, .json 490ms, 서버 기동 로그 599ms — 파싱 0.3초 + 정규화·색인), 정상 상태 객체 메모리 약 78MB(파싱 중 RSS 피크 약 270MB). 검색은 322,189개 문자열을 구분자로 이어붙인 한 str 에서 `str.find` 로 찾아 "화장품 소매업" 61건 3ms(서버 12ms), "커피" 214건 5ms, 광범위한 1~2글자 질의("업" 53,991건·"판매" 38,510건)도 40~50ms. 자동완성 UI 는 디바운스와 2글자 이상 조건을 권장한다.
- API: `GET /goods/search?q&limit&nice_class`, `GET /goods/classes`(45류 명칭·건수). 계약은 `docs/MarkLens_API계약_v1.md`. 변환표가 없으면 서버는 뜨고 두 엔드포인트만 503 + 이유. 한도 `MARKLENS_GOODS_RATELIMIT`(기본 60/minute), 경로 `MARKLENS_GOODS_MAP_PATH`.

## 5. 변경 이력

- **v1 (2026-09-21)**: 자카드 축 함수 `goods_similarity`·`has_goods`, 변환표 로더(경로 우선순위·gzip·lru_cache·name/aliases 검색·`codes_for`·`classes`), 상품 검색 API 2종 + BFF 라우트 + `lib/api.ts` `searchGoods`·`fetchGoodsClasses`, `parse_goods_map.py --gzip`. 테스트: X4 15건, 로더 12건, API 18건, BFF 3건, 프런트 클라이언트 2건.
