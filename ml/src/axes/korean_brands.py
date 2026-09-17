"""국내 브랜드·지명 로마자 → 한글 표 (X1 G2P 1단계).

두 표 모두 룰 G2P 보다 먼저 **토큰 완전일치**로 적용한다. 한국어 로마자 표기(samsung, seoul …)는
외래어 표기법 룰로 읽을 수 없어 표로 다룬다(판례 ④ "국내 거래자의 자연스러운 발음").

- 키: 소문자 영문 토큰 / 값: 한글 표기. 룰 G2P 결과가 이미 같은 항목은 중복이라 넣지 않는다.
- `KOREAN_BRAND_ROMANIZATION`: 씨앗 110개 중 룰과 같은 33개(kakao, naver 등)를 뺀 77개
  (2026-09-17) + 로마자 캐기 승인분 10개 + 유명 브랜드 목록 교차 확인 4개 = 91개.
- `KOREAN_PLACE_ROMANIZATION`: 국내 지명 39개 중 룰과 같은 5개(sejong, insadong, songdo,
  sokcho, mokpo)를 뺀 34개. **이 지명 목록은 향후 식별력 필터(현저한 지리적 명칭)에서 재사용
  예정**이므로 값은 표준 지명 표기를 유지한다.
- 새 항목은 `ml/scripts/x1_mine_romanization.py` 가 DB 에서 뽑은 후보를 **사람이 승인**해 옮긴다.
  스크립트가 이 파일을 자동으로 고치지 않는다.
- 벤치마크(`x1_report.py` 20단어)는 두 표를 모두 끈 순수 룰로 측정한다(`g2p_benchmark`).
"""

from typing import Final

KOREAN_BRAND_ROMANIZATION: Final[dict[str, str]] = {
    # 전자·자동차·중공업
    "samsung": "삼성",
    "hyundai": "현대",
    "kia": "기아",
    "daewoo": "대우",
    "hanwha": "한화",
    "doosan": "두산",
    "kumho": "금호",
    "ssangyong": "쌍용",
    "hanjin": "한진",
    "hankook": "한국",
    "hyosung": "효성",
    "kolon": "코오롱",
    "hansol": "한솔",
    "mando": "만도",
    "nexen": "넥센",
    "daelim": "대림",
    "seah": "세아",
    "poongsan": "풍산",
    "kwangdong": "광동",
    # 유통·플랫폼·IT
    "lotte": "롯데",
    "shinsegae": "신세계",
    "coupang": "쿠팡",
    "musinsa": "무신사",
    "baemin": "배민",
    "zigbang": "직방",
    "dabang": "다방",
    "daangn": "당근",
    "nexon": "넥슨",
    "himart": "하이마트",
    "danawa": "다나와",
    "gmarket": "지마켓",
    "wemakeprice": "위메프",
    "tmon": "티몬",
    "emart": "이마트",
    "homeplus": "홈플러스",
    "daum": "다음",
    "cyworld": "싸이월드",
    "watcha": "왓챠",
    "tving": "티빙",
    "wavve": "웨이브",
    "aladin": "알라딘",
    "inflearn": "인프런",
    "modetour": "모두투어",
    # 식음료·외식
    "ottogi": "오뚜기",
    "binggrae": "빙그레",
    "pulmuone": "풀무원",
    "maeil": "매일",
    "namyang": "남양",
    "chamisul": "참이슬",
    "kyochon": "교촌",
    "goobne": "굽네",
    "bonjuk": "본죽",
    "hansot": "한솥",
    "osulloc": "오설록",
    # 뷰티·패션
    "sulwhasoo": "설화수",
    "laneige": "라네즈",
    "tonymoly": "토니모리",
    "amore": "아모레",
    "amorepacific": "아모레퍼시픽",
    "blackyak": "블랙야크",
    "eider": "아이더",
    "hazzys": "헤지스",
    "topten": "탑텐",
    "mixxo": "미쏘",
    "xexymix": "젝시믹스",
    "andar": "안다르",
    # 금융·제약·항공
    "kyobo": "교보",
    "shinhan": "신한",
    "kookmin": "국민",
    "nonghyup": "농협",
    "mirae": "미래",
    "yuhan": "유한",
    "daewoong": "대웅",
    "hanmi": "한미",
    "boryung": "보령",
    "asiana": "아시아나",
    "tway": "티웨이",
    # 로마자 캐기 승인분 (2026-09-17, x1_mine_romanization.py 후보 중 사람이 승인)
    "gudaero": "그대로",
    "chengdamsu": "청담수",
    "yumbbokki": "얌볶이",
    "nakwon": "낙원",
    "luciel": "루씨엘",
    "netmarble": "넷마블",
    "petitzel": "쁘띠첼",
    "heyalfun": "헤이알펀",
    "honsul": "혼술",
    "sancheon": "산천",
    # 유명 브랜드 목록(shared/famous_brands.txt) 교차 확인 승인분 (2026-09-17)
    "sangmidang": "상미당",
    "eland": "이랜드",
    "woowa": "우아",
    "baedal": "배달",
}

# 국내 지명 로마자(국어의 로마자 표기법 기준).
# 룰 결과와 이미 같은 sejong·insadong·songdo·sokcho·mokpo 는 중복이라 제외.
KOREAN_PLACE_ROMANIZATION: Final[dict[str, str]] = {
    # 광역
    "seoul": "서울",
    "busan": "부산",
    "daegu": "대구",
    "incheon": "인천",
    "gwangju": "광주",
    "daejeon": "대전",
    "ulsan": "울산",
    "gyeonggi": "경기",
    "gangwon": "강원",
    # 서울 안 지명
    "gangnam": "강남",
    "hongdae": "홍대",
    "itaewon": "이태원",
    "myeongdong": "명동",
    "jongno": "종로",
    "yeouido": "여의도",
    # 시·군·구
    "haeundae": "해운대",
    "suwon": "수원",
    "seongnam": "성남",
    "yongin": "용인",
    "bucheon": "부천",
    "cheongju": "청주",
    "jeonju": "전주",
    "changwon": "창원",
    "pohang": "포항",
    "gyeongju": "경주",
    "gangneung": "강릉",
    "chuncheon": "춘천",
    "yeosu": "여수",
    "andong": "안동",
    "tongyeong": "통영",
    "taebaek": "태백",
    "hwacheon": "화천",
    # 국호
    "hanguk": "한국",
    "joseon": "조선",
}
