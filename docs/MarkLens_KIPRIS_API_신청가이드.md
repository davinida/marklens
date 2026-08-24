# MarkLens KIPRIS Plus API 신청 가이드

> 확인일: 2026-08-14  
> 범위: MarkLens 명칭 확인과 상표 데이터 수집

## 결론

MarkLens에 필요한 KIPRIS Plus Open API 상품은 **`상표 출원 속보` 1개**다.
오퍼레이션마다 상품을 따로 신청하는 구조가 아니며, 아래 기능이 모두 같은 상품에
포함된다.

- 상표명 완전일치 검색
- 전체·항목별·출원인 검색
- 서지상세, 지정상품, 유사군, 비엔나도형분류
- 견본이미지 경로

현재 구현에는 `상표 행정처리 이력`, `상표 분류코드 변동 이력`, `상표 공보` BULK,
`출원인 법인` 상품을 추가 신청할 필요가 없다. 이 상품들은 해당 기능을 실제로
구현할 때 별도로 검토한다.

공식 상품: <https://plus.kipris.or.kr/portal/data/clas/DBII_000000000000012/view.do?menuNo=210002>

## 코드와 API 매핑

| MarkLens 기능 | 오퍼레이션 | 경로 계열 | 인증 파라미터 | 신청 상품 |
|---|---|---|---|---|
| 실시간 명칭 확인 | `trademarkNameMatchSearchInfo` | `/openapi/rest/**` | `accessKey` | 상표 출원 속보 |
| 수집용 고급·출원인 검색 | `getAdvancedSearch` | `/kipo-api/kipi/**` | `ServiceKey` | 상표 출원 속보 |
| 서지·지정상품·유사군 보강 | `getBibliographyDetailInfoSearch` | `/kipo-api/kipi/**` | `ServiceKey` | 상표 출원 속보 |

두 경로 계열은 같은 승인 키를 사용하되 쿼리 파라미터 이름이 다르다. `.env`에는
키 하나만 `KIPRIS_ACCESS_KEY`로 저장하고, 클라이언트가 경로에 맞는 이름으로
전송한다. 키와 전체 요청 URL을 로그·문서·Git에 남기지 않는다.

KIPRIS 팝업 예시에 HTTP 주소가 남아 있어도 MarkLens 설정은 HTTPS를 유지한다.
2026-08-14 실제 HTTPS 완전일치 호출이 정상 응답했으므로 HTTP로 내릴 이유가 없다.

## 신청 절차

1. KIPRIS Plus에 로그인한다.
2. `데이터서비스 > 데이터목록`에서 `API > 국내 IP데이터 > 공보 > 상표`를 선택한다.
3. `상표 출원 속보`를 선택해 신청한다.
4. 신청 화면에는 아래처럼 입력한다.
5. `마이페이지 > 서비스 구매내역`에서 상품이 사용 가능한 상태인지 확인한다.
6. `마이페이지 > APIKEY관리`의 REST 인증키를 `.env`의 `KIPRIS_ACCESS_KEY`에 넣는다.

공식 절차: <https://plus.kipris.or.kr/portal/main/contents.do?menuNo=210104>

권장 신청 문구:

```text
활용 서비스명: MarkLens

활용 목적:
연구·비상업 베타용 상표 이미지 및 명칭 유사도 분석. 상표 출원 속보 Open API의
상표명 완전일치, 전체·출원인 검색, 서지, 지정상품, 유사군, 견본이미지 경로를
서버 측에서 조회하여 검색 인덱스와 결과를 구성하며, 원문 데이터나 인증키를
재판매·공개하지 않음.

요청사항:
상표 출원 속보 Open API 상품의 REST 기능 사용.
/kipo-api/kipi 계열 ServiceKey 및 /openapi/rest 계열 accessKey 사용 권한 확인 요청.
```

국내 대학생·교직원 비용면제는 단체회원 가입, 학교 이메일, 최근 3개월 이내
재학·재직증명서 제출과 관리자 확인이 필요하며 당해연도 말까지 유효하다. 무료
Open API는 계정의 전체 상품 호출 합계 월 1,000회이며 매월 1일 초기화된다.

- 수수료·대학생 절차: <https://plus.kipris.or.kr/portal/bbs/Faq_info.do?buttonIndex=&pageIndex=2>
- 호출 한도·장애 확인: <https://plus.kipris.or.kr/portal/bbs/Faq_info.do?buttonIndex=&pageIndex=3>

## 이름 확인 장애 점검

사용자가 제시한 `API Status`는 **내 계정의 신청 현황이 아니라 전체 서버 상태**다.
계정 권한과 잔여량은 마이페이지에서 별도로 확인해야 한다.

1. `/api/name-check`가 401·403이면 BFF API 키 또는 Turnstile 설정을 확인한다.
2. 백엔드가 `resultCode=31`을 받으면 상품 미신청·승인대기·이용기간을 확인한다.
3. `resultCode` 없는 `KiprisNetworkError`면 DNS, TLS, 방화벽, 프록시, 외부 인터넷
   제한 또는 HTTP 상태 오류를 먼저 확인한다.
4. 계정 전체 Open API 호출 합계가 월 1,000회를 넘지 않았는지 확인한다.
5. 공식 상태 페이지에서 두 경로 계열의 `상표 출원 속보` 상태를 확인한다.

상태 페이지: <https://plus.kipris.or.kr/portal/main/apiStatus.do?menuNo=210157>

문제가 계속되면 키나 검색어를 보내지 말고 `resultCode`, `resultMsg`, 발생 시각,
오퍼레이션명만 정리해 KIPRIS Plus에 문의한다.

- 전화: `02-6915-1553` 연결 후 `1`
- 이메일: `kiprisplus@kipi.or.kr`
- HelpDesk: 로그인 후 `HelpDesk > 문의하기`

### 이름 후보 상세 표시 원칙

- 명칭 검색 응답에 이미 포함된 출원번호, 상표명, 상태, 출원인, 상품류, 유사군과
  비엔나코드만 표시한다.
- 현재 로컬 인덱스와 출원번호가 일치할 때만 검증된 로컬 이미지를 연결한다.
- KIPRIS 일회성 이미지 URL은 브라우저에 직접 노출하지 않는다.
- 후보마다 서지상세 API를 자동 호출하지 않는다. `BBQ`처럼 후보가 많은 이름에서
  월 1,000회 쿼터를 한 번에 소진할 수 있기 때문이다.
- 후보 목록 일부만 반환됐거나 원 검색이 불완전하면 UI에서 부재·사용가능 결론을
  내리지 않는다.

## 2026-08-14 확인 기록

- 공용 API Status에서 `/openapi/rest/**`와 `/kipo-api/kipi/**`의 `상표 출원 속보`가
  모두 정상으로 표시됐다.
- 현재 `.env`의 키를 노출하지 않고 HTTPS `trademarkNameMatchSearchInfo`를 1회
  호출했다.
- `마크렌즈` 검색은 `resultCode=00`에 해당하는 정상 응답으로 완료됐고 완전일치
  결과는 0건이었다.
- 따라서 현재 키에는 필요한 상품 권한이 이미 있으며, 당시 UI의 502는 외부
  통신이 제한된 로컬 백엔드 프로세스가 원인이었다.
- 백엔드를 외부 통신 가능한 로컬 프로세스로 재기동하고 `/health`의
  `engine_ready=true`, 당시 인덱스 105건을 확인했다.

## 2026-08-15 인덱스 확장 후 확인 기록

현재 artifact generation은 `20260815T023540Z-0d79c662f4c8`이며 manifest의 vector와
authoritative key는 각각 1,000개다. 같은 generation으로 백엔드와 BFF를 재기동해
정적 artifact와 실제 runtime이 일치하는 것도 확인했다.

- FastAPI `/health`: `engine_ready=true`, `index_size=1000`, `trademark_count=1000`,
  generation이 manifest와 일치
- same-origin BFF `/api/health`: backend ready, index·metadata 각 1,000건,
  generation `20260815T023540Z-0d79c662f4c8`
- unique sample `4019700003653.png`의 BFF 검색: top-1 `0.9999999404`, top-5 5건
- 결과 이미지 proxy: HTTP 200, `image/png`, 22,479 bytes
- 검수 서버: pack `vlp2_d32d53e3b6c101517517`, development 160쌍, 라벨 0건

이 smoke에서는 `/name-check`를 호출하지 않아 KIPRIS 월간 호출은 0회였다. 이후 artifact를
다시 빌드하거나 서버를 재배포하면 같은 검증을 새 generation에 대해 반복해야 한다.

실제 검색 결과는 법적 판단이 아니며, KIPRIS 공식 검색 및 전문가 검토를 대체하지
않는다. KIPRIS 이미지·원문을 공개 배포하기 전에는 재배포 권한을 별도로 확인한다.
