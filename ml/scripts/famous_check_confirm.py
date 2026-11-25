"""유명 상표 확인 — 판정 규칙 확정 측정(통합 모델 설계 §7-14-12). 엔진·계약·화면·DB 불변.

고친 규칙(src.famous_check 의 "확정 단계")으로 ① 표본을 더하고(1단계에 고정한 표본은 그대로) ② 약한
일치 조건 네 가지(W0–W3)를 기준용 표본으로 견줘 하나를 고른 뒤 ③ 기준용 목표와 기대표를 보고
④ 모두 넘으면 확인용 표본을 한 번 본다. 넘으면 규칙·기준·등록부 해시를 확정 파일
(shared/famous_check_confirmed.json)로 남긴다. 규칙·표본·선택 규칙·목표는 `RULE`·`EXPECT`·
`SELECT_LIMITS`·`BASE_GOALS`·`HOLDOUT_GOALS`(실행 전에 해시를 남긴다).

    ml/venv/bin/python ml/scripts/famous_check_confirm.py freeze    # 더한 표본 + 설정·입력 해시
    ml/venv/bin/python ml/scripts/famous_check_confirm.py base      # 기준용: 조건 고르기·목표
                                                                    #   (미달이면 종료 코드 3)
    ml/venv/bin/python ml/scripts/famous_check_confirm.py holdout   # 확인용 한 번(base 가 모두
                                                                    #   통과했을 때만) → 확정 파일
    ml/venv/bin/python ml/scripts/famous_check_confirm.py images    # 로고·이미지 속 글자 헛일치,
                                                                    #   미리 보기 표(실제 엔진)
    ml/venv/bin/python ml/scripts/famous_check_confirm.py classes   # 서비스 연결 준비(보고만):
                                                                    #   질의의 류를 유사군 코드에서
                                                                    #   정하는 방법 안의 확인
    … freeze --out-dir <폴더> → base --smoke --out-dir <폴더> → holdout --smoke --out-dir <폴더>
                                                                    # 스모크: 일부 표본만 — 확인용
                                                                    #   자리는 기준용 일부로 채운다

KIPRIS 호출 0. base·holdout 은 엔진을 띄우지 않는다. 1단계 표본·2-1 측정은 famous_check_measure.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing
import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
for _root in (ML_ROOT, REPO_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from src import famous_check as fc  # noqa: E402
from src.axes import distinctiveness as dx  # noqa: E402
from src.axes import goods_map as gm  # noqa: E402
from src.model import risk_model as rm  # noqa: E402

from scripts import famous_check_measure as fm  # noqa: E402
from scripts import famous_registry as builder  # noqa: E402

TRIALS = fm.TRIALS
STEM = "famous_check_3"
TRIAL_LIST = TRIALS / "list_all.csv"  # 1차 수집 때의 심판 목록(상표명칭 칸) — N5
CONFIRMED_FILE = REPO_ROOT / "shared" / "famous_check_confirmed.json"
CONFIRMED_VERSION = "famous_check_confirmed_v1"
BASE, HOLDOUT, SEED = fm.BASE, fm.HOLDOUT, fm.SEED
EXIT_FAILED, EXIT_REFUSED = 3, 4
MODES = fc.WEAK_MODES
TIE_ORDER = ("W1", "W2", "W3", "W0")
# 기준값 — 2-1 에서 고른 그대로(freeze 가 2-1 결과 파일과 견준다)
STRONG_SPELLING = 0.90
WEAK_SOUND = {"짧음": 0.90, "중간": 0.92, "김": 0.90}
WEAK_SPELLING = 0.75
SELECT_LIMITS = {"N1_약함_최대": 2, "N3_약함_비율_최대": 0.02, "N5_약함_비율_최대": 0.003}
BASE_GOALS = {"N1_강함": 0, "N1_약함_최대": 2, "N3_강함": 0, "N3_약함_비율_최대": 0.02,
              "P2_보통_약함_이상_최소": 0.80}
HOLDOUT_GOALS = {"N1_강함(소리·철자·품음)_최대": 1, "N1_약함_최대": 4, "N3_강함": 0,
                 "N3_약함_최대": 2, "P2_재현율_하락_최대": 0.15, "N5_배수": 2.0,
                 "N5_더함": 0.001}
OWN_NAME_PATHS = (fc.PATH_EXACT, fc.PATH_CONTAIN_DESC)  # 브랜드 자신의 이름일 수 있는 강한 일치
SMOKE = {"P1_브랜드": 3, "P2": 4, "P3_표기": 4, "N1": 30, "N2": 30, "N3": 10, "N4": 5,
         "N5": 300, "기대표": 14, "음성_이미지": 5, "미리_보기": 6}
_LABEL = re.compile(r"\(([a-z_]+)\)$")  # 업종 표시 끝의 업종 세트 id — "자기 업종(cafe)"

# 새 브랜드의 P2(실제 모방 꼴) — (브랜드(등록부 이름), 기준용, 확인용). 지시의 목록 그대로.
P2_NEW = (
    ("나이키", "나이끼", "나이키이"), ("아디다스", "아디도스", "아디다쓰"),
    ("구찌", "구치", "꾸찌"), ("유니클로", "유니클러", "유니끌로"), ("자라", "쟈라", "자라아"),
    ("맥도날드", "맥도널드", "멕도날드"), ("롯데리아", "롯대리아", "롯데리야"),
    ("코카콜라", "코카콜러", "코카골라"), ("쿠팡", "쿠빵", "쿠퐝"),
    ("배달의민족", "배달의민죡", "베달의민족"), ("다이소", "다있소", "다이쏘"),
    ("세븐일레븐", "세분일레븐", "쎄븐일레븐"), ("맘스터치", "맘스타치", "맘스터취"),
    ("투썸플레이스", "투섬플레이스", "투썸플래이스"), ("메가MGC커피", "매가커피", "메가거피"),
    ("할리스", "할리쓰", "할리즈"), ("무신사", "무신싸", "무씬사"), ("도요타", "도요다", "토요다"),
)
# 기대표 — (기대, 이름, 업종: 업종 세트 id | "과일" | None | "@N1" | "@대조군"). 일치 수준만 본다.
E_STRONG, E_WEAK, E_NOTICE, E_NONE = "강함", "약함 이상", "안내만", "없음"
W_WEAK_OR_NONE, W_NONE = "바람: 약함 또는 없음", "바람: 없음"
W_WEAK, W_NOTICE = "바람: 약함 이상", "바람: 안내만"
EXPECT = (
    (E_STRONG, "BBQ", "chicken"), (E_STRONG, "BBQ치킨", "chicken"),
    (E_STRONG, "BBQ 치킨집", "chicken"), (E_STRONG, "비비큐", "chicken"),
    (E_STRONG, "맛있는 BBQ", "korean_restaurant"), (E_STRONG, "BBQ", "clothing"),
    (E_STRONG, "CU", "convenience"), (E_STRONG, "씨유편의점", "convenience"),
    (E_STRONG, "GS25", "convenience"), (E_STRONG, "지에스25", "convenience"),
    (E_STRONG, "김가네", "bunsik"), (E_STRONG, "bhc", "chicken"),
    (E_STRONG, "BHC치킨", "chicken"), (E_STRONG, "스타벅스", "cafe"),
    (E_STRONG, "스타벅스", "clothing"), (E_STRONG, "스타벅스", None),
    (E_STRONG, "STARBUCKS COFFEE", "cafe"), (E_STRONG, "스타벅스커피", None),
    (E_STRONG, "샤넬", "chicken"), (E_STRONG, "샤넬치킨", None), (E_STRONG, "네이버", "flower"),
    (E_STRONG, "크린토피아", "cafe"), (E_STRONG, "파리 바게뜨", "bakery"),
    (E_STRONG, "올리브영", "cosmetics"), (E_STRONG, "야 놀자", "lodging"),
    (E_STRONG, "에어비앤비", "lodging"), (E_STRONG, "던킨빵집", "bakery"),
    (E_STRONG, "본죽식당", "korean_restaurant"), (E_STRONG, "교촌치킨", "chicken"),
    (E_STRONG, "나이키", "clothing"), (E_STRONG, "나이키", "chicken"),
    (E_STRONG, "맥도날드", None), (E_STRONG, "애플", "software"),
    (E_WEAK, "크린토피야", None), (E_WEAK, "파리바게트", None), (E_WEAK, "샤낼", "cosmetics"),
    (E_WEAK, "STARBUCKSS", None), (E_WEAK, "뉴스타벅스", "cafe"),
    (E_WEAK, "스타벅수", "clothing"), (E_WEAK, "스타벅수", None),
    (E_NOTICE, "텍사스 BBQ", "korean_restaurant"), (E_NOTICE, "서울 BBQ", "korean_restaurant"),
    (E_NOTICE, "CU LATER", "cafe"), (E_NOTICE, "김가네", "software"), (E_NOTICE, "애플", "과일"),
    (E_NOTICE, "카카오", "cafe"),
    (E_NONE, "GS24", "convenience"), (E_NONE, "김가내", None), (E_NONE, "비에치씨", None),
    (E_NONE, "CUTE", None), (E_NONE, "씨유어게인", None), (E_NONE, "구글링", "software"),
    (E_NONE, "샤넬로", None), (E_NONE, "채널", "software"), (E_NONE, "CHANNEL", "software"),
    (E_NONE, "교촌마을", None), (E_NONE, "파리", None), (E_NONE, "바게뜨", None),
    (E_NONE, "올리브", "cosmetics"), (E_NONE, "비앤비", "lodging"), (E_NONE, "야놀이터", None),
    (E_NONE, "유토피아", None), (E_NONE, "블루커피", "cafe"),
    (E_NONE, "@대조군1", "@대조군"), (E_NONE, "@대조군2", "@대조군"),
    (E_NONE, "@대조군3", "@대조군"), (E_NONE, "Airline Seoul", "@N1"),
    (E_NONE, "BIO PHARM Dongsung", "@N1"), (E_NONE, "열매속풍요 Pungyo in Fruit", "@N1"),
    (W_WEAK_OR_NONE, "네이버후드", "cafe"), (W_WEAK_OR_NONE, "네이버스", None),
    (W_WEAK_OR_NONE, "넷플러스", None),
    (W_NONE, "like", None), (W_NONE, "BIKE", None), (W_NONE, "자리", None),
    (W_NONE, "PARA PARA", None), (W_NONE, "MOLLY'S", None), (W_NONE, "ZARI", None),
    (W_WEAK, "네이바", None), (W_WEAK, "구굴", None), (W_WEAK, "교춘", None),
    (W_WEAK, "헤르메스", "clothing"), (W_WEAK, "맥도널드", None),
    (W_NOTICE, "삼성", "chicken"), (W_NOTICE, "현대세탁소", "laundry"),
)
WISHES = (W_WEAK_OR_NONE, W_NONE, W_WEAK, W_NOTICE)
# 미리 보기 — 1단계 입력(시연 넷·애플 + 과일 포함)에 더한 것
PREVIEW_EXTRA = (("나이키", "clothing"), ("나이키", "chicken"), ("맥도날드", None))
PREVIEW = fm.PREVIEW_NAMES + PREVIEW_EXTRA

RULE = {
    "목적": (
        "유명 상표 확인의 판정 규칙을 확정한다 — 드러난 규칙 문제를 고치고(1), 표본을 더하고(2), "
        "약한 일치 조건을 기준용 표본으로 고른 뒤(3) 기준용 목표를 보고(4) 모두 넘으면 확인용 "
        "표본을 한 번 본다(5). 4에서 미달이면 확인용을 계산하지 않고 멈춘다. 판정 모듈·등록부·"
        "측정 스크립트만 바꾼다."),
    "1_규칙": (
        "(1) 판매업(35류): 약한 표기가 '그 업종에서도 식별력 없는 말인지' 볼 때와 이름 일치용 업종 "
        "겹침을 잴 때 35류를 빼고 본다. 질의 업종과 브랜드 업종 세트가 둘 다 35류뿐이면 그대로. "
        "(2) 그 밖의 판정(설명 낱말)에 쓰는 브랜드 업종은 핵심 "
        "업종(업종 세트의 유사군, 핵심 류)만. "
        "(3) 사람이 흔한 말로 표시한 표기는 업종이 다르면 항상 안내만. (4) 새 브랜드의 핵심 업종"
        "(세트·류)은 overrides 에. 이름 일치용 업종 겹침 = "
        "지금까지의 방식(업종 세트와 '관련 없음'이 "
        "아닌 표장의 유사군과의 겹침 ≥ 결합 하한) 또는 질의 업종의 "
        "류(35류 뺌)가 핵심 류와 하나라도 "
        "같음. (5) 로고: 강함(엔진의 이미지만 판단이 위험)만, 대표 로고와 질의 이미지가 둘 다 글자 "
        "위주면 유사도 0.98 이상일 때만, 사진으로 판정된 쪽이 있으면 보지 않는다. (6) 이미지 속 "
        "글자: 이름이 없고 OCR 제안 상표명이 있으면 그 글자로 같음·품음-설명만(강함). (7) 두 "
        "브랜드에 함께 걸린 표장은 상표명이 가리키는 브랜드 하나에만 "
        "잇고, 정할 수 없으면 어느 쪽의 "
        "대표 로고로도 쓰지 않는다."),
    "1_해석(지시에 없어 고정)": (
        "35류를 빼는 방법: 식별력 판정은 유사군 코드의 류에서 35류를 지우고 35류의 고시 명칭을 뺀 "
        "사본으로 한다(판정 식은 그대로). 업종 겹침은 35류뿐인 유사군 코드(변환표에서 그 코드가 "
        "붙은 상품이 모두 35류 — 61개)를 양쪽에서 빼고 잰다. 질의의 류: 업종 세트로 준 질의는 그 "
        "세트의 지정상품이 속한 류, 그 상표의 지정상품으로 준 질의(N1)는 DB 에 적힌 그 상표의 류, "
        "'과일 판매'는 31·35류. 류를 받지 못한 질의는 유사군 코드가 붙은 상품의 류 전부. 핵심 류는 "
        "사람이 준 브랜드에만 있다(업종 세트의 류로 채우지 않는다). 핵심 류로 하는 설명 낱말 판정 "
        "= 그 류의 고시 단일 명칭(1호)이거나 3호 사전의 낱말이 그 "
        "류에(절대어 포함). 흔한 말 표기를 "
        "소리로 따르는 표기(kakao·toss)도 흔한 말과 같게 다룬다. 표기 종류의 '자기 업종'(1단계 "
        "정의)은 그대로. 버거·패스트푸드에 가장 가까운 음식점 세트 = chicken(치킨집 — '패스트푸드"
        "식당업'이 든 세트는 이것뿐). 함께 걸린 표장: 사람이 출원번호로 고른 브랜드가 하나면 그 "
        "브랜드에(지금은 해당 없음)."),
    "2_표본": (
        "1단계에 고정한 표본(famous_check_samples.json, sha256 = STAGE1_SAMPLES_SHA256)은 그대로 "
        "읽는다. 지운 표기를 겨냥한 표본과 등록부 출원인이 된 상표의 N1 은 뺀다(2-1 recheck 와 "
        "같음). 더한 표본(더함 = true, 따로 둔 파일): ① 새 "
        "표기(1단계 P1 에 없는 표기 — 새 브랜드의 "
        "표기와 사람이 더한 표기)의 P1·P3 — 같은 규칙과 seed, P3 는 표기마다 기준용 2·확인용 2, "
        "업종 세트가 없는 브랜드는 자기 업종 질의와 자기 업종 낱말 변형을 만들지 않는다. 무관한 "
        "업종 = 파일 순서로 자기 세트(없으면 첫 세트) + 7번째부터 고친 규칙의 업종 겹침이 아닌 첫 "
        "세트. ② 새 브랜드의 P2 18쌍(P2_NEW — 첫째 기준용, 둘째 확인용). ③ N5 = 심판 목록"
        "(list_all.csv)의 상표명칭 — 붙여 쓴 꼴이 같은 것은 하나로, 다른 표본·기대표·미리 보기에 "
        "있는 이름은 빼고, seed 0 으로 섞어 앞 절반 기준용·뒤 절반 "
        "확인용, 업종 없음. 브랜드 자신의 "
        "이름: N1 은 출원인으로 뺀다. N2·N5 는 같음·품음-설명으로 강하게 일치한 이름을 '브랜드 "
        "자신의 이름일 수 있음'으로 따로 세고 목표(비율의 분모 포함)에서 뺀다."),
    "3_약한_일치_조건": (
        "강한 일치와 기준값은 2-1 에서 고른 그대로(강한 소리 0.98·강한 철자 0.90, t_s = 약한 소리 "
        "짧음 0.90·중간 0.92·김 0.90, t_p = 약한 철자 0.75). 약한 "
        "수준만 네 가지로 견준다 — W0: 소리 "
        "≥ t_s 또는 철자 ≥ t_p, W1: 소리 ≥ t_s, W2: 같은 문자끼리는 소리 ≥ 0.85 그리고 철자 ≥ t_p·"
        "문자가 다르면 소리 ≥ t_s, W3: 짧은·중간 표기는 W1·긴 표기는 W0. 품음-기타와 예외 낱말은 "
        "네 가지 모두 그대로. 선택: N1 기준용 약함 2건 이하·N3 기준용 약함 2% 이하·N5 기준용 약함 "
        "0.3% 이하를 모두 지키는 조건 가운데 보통 표기의 P2 기준용(기존 + 새) 약함 이상 재현율이 "
        "가장 높은 것. 같으면 음성 표본(N1·N2·N3·N5 기준용)의 약한 "
        "일치 합이 적은 쪽, 그래도 같으면 "
        "W1 → W2 → W3 → W0. 지키는 조건이 없으면 약한 일치 합이 가장 적은 것(한도 미달로 보고). "
        "P3 는 조건별로 보고만. 단위는 질의(이름 × 업종), 수준은 그 질의의 가장 강한 일치."),
    "4_기준용_목표": (
        "고른 조건으로 — N1 기준용 강함 0건·약함 2건 이하, N3 기준용 강함 0건·약함 2% 이하, 보통 "
        "표기의 P2 기준용 약함 이상 80% 이상, P1 은 강함이 아닌 것이 약한·흔한 말 표기의 업종 다름"
        "뿐, 기대표(EXPECT — 바람은 못 맞춰도 보고만). 하나라도 미달이면 5로 가지 않는다. 목표와 "
        "기대표가 부딪치면 헛일치 한도를 우선하고 부딪친 항목을 보고한다."),
    "5_확인용": (
        "한 번만 — N1 확인용: 소리·철자·품음으로 생긴 강함 1건 이하·약함 4건 이하(표기와 같음으로 "
        "생긴 강함은 목록으로만). N3 확인용: 강함 0건·약함 2건 이하. 보통 표기의 P2 확인용(기존 + "
        "새) 약함 이상 재현율이 기준용보다 15%p 넘게 낮지 않음. P3 확인용은 보고만. N5 확인용 약함 "
        "비율 ≤ 기준용 비율 × 2 + 0.1%p. 미달이면 확정하지 않는다. 넘으면 규칙·기준·등록부 해시를 "
        "확정 파일로 남긴다."),
    "스모크": (
        "일부 표본만(SMOKE), 다른 폴더에. 스모크의 확인용 단계는 확인용 표본 대신 기준용 일부로 "
        "코드만 확인한다(확인용은 건드리지 않는다)."),
    "기준용_결과를_본_뒤의_변경": (
        "1차 기준용 측정(설정 sha256 94311d19…2ed2b6 — 조건 W2, 목표 일곱 중 여섯 통과, P1 의 "
        "'당근 마켓' 2질의 미달로 멈춤; 확인용 표본은 계산하지 않았다) 뒤에 사람 결정으로 바꾼 것. "
        "(가) 가림의 예외: 낱말 묶음이 같은 브랜드의 약하지 않은 표기와 같으면 약한 표기의 가림과 "
        "상관없이 같음으로 본다. (나) 등록부(overrides): 인스타그램의 표기 '인스타', 자라의 표기 "
        "'자라'·'ZARA' 를 흔한 말로 표시, 예외 낱말 — 네이버에 '네이처', 나이키에 'like'·'nice', "
        "자라에 '자리'. (다) 고치지 않은 것: '네이버후드 + 카페'가 품음-설명인 까닭은 35류만이 "
        "아니다 — 질의 업종(카페)에서는 '후드'가 35류 때문에 설명 낱말이지만, 브랜드 업종(네이버 = "
        "소프트웨어 세트)에서는 유사군 코드 G390802 가 9류에도 걸쳐 있어 35류를 빼도 설명 낱말"
        "(3호 사전의 '후드'에 9류)이다. 그래서 나머지 판정의 35류는 그대로 두었다. 표본·선택 "
        "규칙·목표·기대표는 1차와 같다."),
    "질의의_류를_코드에서(보고만)": (
        "서비스의 계약은 업종을 유사군 코드로만 받는다. 안: ① 코드 집합이 어느 업종 세트의 코드와 "
        "같으면 그 세트의 류 ② 아니면 코드마다 대표 류(변환표에서 그 코드가 붙은 상품이 가장 많은 "
        "류, 같으면 번호가 작은 류)의 합집합. 판정에는 쓰지 않고, 이 방법으로 기대표와 N1 기준용 "
        "질의를 코드로만 넣었을 때 결과가 측정 때(류를 따로 준 것)와 같은지만 본다."),
}


# ---- 공통 --------------------------------------------------------------------------------------

def thresholds_for(mode: str) -> fc.Thresholds:
    return fc.Thresholds(
        strong_sound=fc.STRONG_SOUND,
        strong_spelling={length: STRONG_SPELLING for length in fc.LENGTHS},
        weak_sound=dict(WEAK_SOUND),
        weak_spelling={length: WEAK_SPELLING for length in fc.LENGTHS},
        spelling_sound=None, contain_other=True, weak_mode=mode)


def _settings() -> dict:
    return {"RULE": RULE, "EXPECT": EXPECT, "P2_NEW": P2_NEW, "SEED": SEED, "MODES": MODES,
            "TIE_ORDER": TIE_ORDER, "기준": thresholds_for("W0").to_dict(),
            "SELECT_LIMITS": SELECT_LIMITS, "BASE_GOALS": BASE_GOALS,
            "HOLDOUT_GOALS": HOLDOUT_GOALS, "OWN_NAME_PATHS": OWN_NAME_PATHS,
            "PREVIEW": PREVIEW, "STAGE1_SAMPLES_SHA256": fm.STAGE1_SAMPLES_SHA256,
            "SMOKE": SMOKE, "RETAIL_CLASS": fc.RETAIL_CLASS,
            "WEAK_PAIR_SOUND": fc.WEAK_PAIR_SOUND,
            "LOGO_TEXT_SIMILARITY": fc.LOGO_TEXT_SIMILARITY, "KIND_SOUND": fc.KIND_SOUND,
            "P3_PER_NOTATION": fm.P3_PER_NOTATION, "LOGO_N1_IMAGES": fm.LOGO_N1_IMAGES,
            "N4_TRAPS": fm.N4_TRAPS, "FRUIT_GOODS": fm.FRUIT_GOODS}


def rule_sha256() -> str:
    return fm.canonical_sha256(_settings())


def _inputs() -> dict[str, Path]:
    paths = dict(fm._inputs())  # noqa: SLF001
    paths.update({"측정_도우미": Path(fm.__file__), "등록부_스크립트": Path(builder.__file__),
                  "심판_목록": TRIAL_LIST, "1단계_표본": fm.SAMPLES_FILE,
                  "2-1_결과": fm.STAGE21_RESULTS})
    return paths


def _paths(out_dir: Path) -> dict[str, Path]:
    return {name: out_dir / f"{STEM}_{name}.json"
            for name in ("rule", "added_samples", "base", "holdout", "images", "classes")} | {
        "report": out_dir / f"{STEM}_report.md"}


def load_static() -> dict:
    goods_map = gm.load_goods_map()
    presets = gm.load_business_presets(goods_map)
    preset_list = json.loads(gm.DEFAULT_PRESETS_PATH.read_text(encoding="utf-8"))
    metadata = json.loads(fm.METADATA.read_text(encoding="utf-8"))
    return {
        "registry": fc.load_registry(), "dist": dx.load_distinctiveness(), "presets": presets,
        "preset_list": preset_list,
        "codes_of": {preset["id"]: fm._preset_codes(presets, preset["id"])  # noqa: SLF001
                     for preset in preset_list},
        "classes_of": builder.preset_classes(),
        "control": json.loads(fm.CONTROL.read_text(encoding="utf-8")),
        "records": {str(record["출원번호"]): record for record in metadata["trademarks"]},
        "applicant_keys": builder.applicant_key_function(),
        "floor": fc.default_goods_floor()}


def classes_resolver(classes_of: dict, records: dict):
    """질의의 류 — 항목에 적힌 값, 업종 표시 끝의 업종 세트 id 의 류, 그 상표(출원번호)의 DB 류.
    업종이 없으면 None, 알 수 없으면 None(판정 모듈이 유사군 코드에서 얻는다)."""
    def resolve(item: dict) -> list[int] | None:
        if item.get("류") is not None:
            return list(item["류"])
        if not item.get("업종"):
            return None
        hit = _LABEL.search(item.get("업종_표시") or "")
        if hit and hit.group(1) in classes_of:
            return list(classes_of[hit.group(1)])
        record = records.get(str(item.get("출원번호") or ""))
        if record is not None:
            return sorted(int(value) for value in record.get("류") or ())
        return None

    return resolve


class Matcher(fm.Matcher):
    """질의의 류를 함께 넘기는 판정 실행. holdout=True 일 때만 확인용 항목을 계산한다."""

    def __init__(self, registry: fc.Registry, dist, goods_floor: float, resolve, *,
                 holdout: bool = False):
        super().__init__(registry, dist, goods_floor)
        self.resolve, self.holdout = resolve, holdout

    def evidence(self, item: dict) -> list[fc.BrandEvidence]:
        if item.get("반") == HOLDOUT and not self.holdout:
            raise ValueError("확인용 표본은 holdout 단계에서만 계산합니다")
        classes = self.resolve(item)
        key = (item["이름"], tuple(item.get("업종") or ()),
               None if classes is None else tuple(classes))
        if key not in self._cache:
            query = fc.prepare_query(item["이름"], item.get("업종"), classes)
            self._cache[key] = fc.collect_evidence(query, self.registry, self.dist, self.floor)
        return self._cache[key]


# ---- 더한 표본 ---------------------------------------------------------------------------------

def unrelated_preset(brand: fc.Brand, static: dict) -> dict:
    """무관한 업종 세트(새 표기의 P1) — 파일 순서로 자기 세트(없으면 첫 세트) + 7번째부터 고친
    규칙의 업종 겹침이 아닌 첫 세트(없으면 유사군 겹침 값이 가장 작은 세트)."""
    preset_list, codes_of, classes_of = (static["preset_list"], static["codes_of"],
                                         static["classes_of"])
    ids = [preset["id"] for preset in preset_list]
    start = ((ids.index(brand.preset) if brand.preset in ids else 0) + 7) % len(ids)
    best: tuple[float, dict] | None = None
    for offset in range(len(ids)):
        preset = preset_list[(start + offset) % len(ids)]
        if preset["id"] == brand.preset:
            continue
        query = fc.prepare_query("x", codes_of[preset["id"]], classes_of[preset["id"]])
        keep = fc._retail_only(query.classes) and fc._retail_only(  # noqa: SLF001
            brand.preset_classes)
        hit, value, _ = fc._overlap(  # noqa: SLF001
            query, brand, static["floor"], static["dist"], query.classes, keep)
        if not hit:
            return preset
        if best is None or (value or 0.0) < best[0]:
            best = (value or 0.0, preset)
    return best[1]


def build_n5(old: dict, added: dict) -> tuple[list[dict], dict]:
    """N5 — 심판 목록의 상표명칭(붙여 쓴 꼴로 중복 제거, 다른 표본에 있는 이름 제외, seed 0 으로
    절반씩). 목록이나 상표명 칸이 없으면 빈 목록."""
    if not TRIAL_LIST.exists():
        return [], {"있음": False, "까닭": f"{TRIAL_LIST.name} 없음"}
    with TRIAL_LIST.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if "상표명칭" not in (reader.fieldnames or ()):
            return [], {"있음": False, "까닭": "상표명칭 칸 없음"}
        rows = [(row.get("상표명칭") or "", row.get("심판번호") or "") for row in reader]
    used = {fc.text_key(item["이름"]) for name in ("P1", "P2", "P3", "N1", "N2", "N3", "N4")
            for item in old[name]}
    used |= {fc.text_key(item["이름"]) for name in ("P1", "P2", "P3") for item in added[name]}
    used |= {fc.text_key(name) for _, name, _ in EXPECT if not name.startswith("@")}
    used |= {fc.text_key(name) for name, _ in PREVIEW if not name.startswith("@")}
    first: dict[str, tuple[str, str]] = {}
    named = 0
    for title, trial in rows:
        title = title.strip()
        named += bool(title)
        key = fc.text_key(title)
        if key and key not in first:
            first[key] = (title, trial)
    keys = sorted(key for key in first if key not in used)
    random.Random(f"{SEED}|N5").shuffle(keys)
    half = len(keys) // 2
    items = [{"이름": first[key][0], "업종": None, "업종_표시": "없음",
              "반": BASE if index < half else HOLDOUT, "심판번호": first[key][1], "더함": True}
             for index, key in enumerate(keys)]
    return items, {"있음": True, "목록_행": len(rows), "상표명칭_있는_행": named,
                   "붙여_쓴_꼴이_다른_이름": len(first),
                   "다른_표본에_있어_뺀_이름": len(first) - len(keys),
                   "기준용": half, "확인용": len(keys) - half}


def build_added(static: dict, old: dict) -> dict:
    """더한 표본 — 새 표기의 P1·P3, 새 브랜드의 P2, N5. 항목마다 더함 = true."""
    registry, dist, codes_of = static["registry"], static["dist"], static["codes_of"]
    presets = {preset["id"]: preset for preset in static["preset_list"]}
    old_pairs = {(item["브랜드"], item["표기"]) for item in old["P1"]}
    taken = {n.key for brand in registry.brands for n in brand.notations}
    taken |= {fc.text_key(item["이름"]) for name in ("P2", "P3") for item in old[name]}
    taken |= {fc.text_key(name) for _, first, second in P2_NEW for name in (first, second)}
    taken |= {fc.text_key(name) for name in fm.N4_TRAPS}
    taken |= {fc.text_key(name) for _, name, _ in EXPECT if not name.startswith("@")}
    taken |= {fc.text_key(name) for name, _ in PREVIEW if not name.startswith("@")}
    taken.discard("")
    weak_brands = {brand.name for brand in registry.brands
                   if any(n.base_weak for n in brand.notations)}
    p1, p2, p3 = [], [], []
    unrelated: dict[str, str] = {}
    for brand in registry.brands:
        names = {brand.name, brand.table_name or brand.name}
        fresh = [n for n in brand.notations
                 if not any((name, n.text) in old_pairs for name in names)]
        if not fresh:
            continue
        own_goods: list[tuple[str, list[str] | None]] = [("없음", None)]
        if brand.preset:
            own_goods.append((f"자기 업종({brand.preset})", codes_of[brand.preset]))
        other = unrelated_preset(brand, static)
        unrelated[brand.name] = other["id"]
        other_word = [alias for alias in other["별칭"] if alias.strip()][0]
        for notation in fresh:
            text = notation.text
            base = {"브랜드": brand.name, "표기": text, "약한_표기": notation.base_weak,
                    "반": None, "더함": True}
            variants = [("그대로", text), ("대소문자 바꿈", fm.case_variant(text)),
                        ("띄어쓰기 바꿈", fm.spacing_variant(text))]
            if brand.preset:  # 업종 세트가 없으면 자기 업종 낱말 변형을 만들지 않는다
                for kind, word in fm.own_words(presets[brand.preset], dist):
                    variants += [(f"{kind} 띄어서", f"{text} {word}"),
                                 (f"{kind} 붙여서", text + word)]
            for kind, name in variants:
                if name:
                    p1 += fm._with_goods(  # noqa: SLF001
                        {"이름": name, **base, "변형": kind}, own_goods)
            p1 += fm._with_goods(  # noqa: SLF001
                {"이름": f"{text} {other_word}", **base, "변형": "무관한 업종 낱말"},
                [("없음", None), (f"무관한 업종({other['id']})", codes_of[other["id"]])])
            if not notation.base_weak:
                for item in fm.p3_variants(brand.name, notation, taken):
                    taken.add(fc.text_key(item["이름"]))  # 뒤 표기의 변형과 겹치지 않게
                    p3 += fm._with_goods({**item, "더함": True}, own_goods)  # noqa: SLF001
    for name, first, second in P2_NEW:
        brand = registry.brand(name)
        if brand is None:
            raise ValueError(f"P2 의 브랜드가 등록부에 없습니다: {name}")
        own_goods = [("없음", None)]
        if brand.preset:
            own_goods.append((f"자기 업종({brand.preset})", codes_of[brand.preset]))
        for variant, half in ((first, BASE), (second, HOLDOUT)):
            target = fm.target_notation(variant, brand)
            p2 += fm._with_goods(  # noqa: SLF001
                {"이름": variant, "브랜드": brand.name, "표기": target.text,
                 "길이": target.length, "변형": fm.P2_VARIANT, "반": half,
                 "약한_표기_브랜드": brand.name in weak_brands, "더함": True}, own_goods)
    added = {"P1": p1, "P2": p2, "P3": p3}
    added["N5"], added["N5_정보"] = build_n5(old, added)
    added["무관한_업종"] = unrelated
    return added


def pick(items: list[dict], half: str) -> list[dict]:
    """그 단계에서 계산하는 항목 — 기준용 단계는 기준용과 나누지 않은 것, 확인용 단계는 확인용만."""
    wanted = (None, BASE) if half == BASE else (HOLDOUT,)
    return [item for item in items if not item.get("중복") and item.get("반") in wanted]


def usable(old: dict, added: dict, registry: fc.Registry, matcher: Matcher, applicant_keys,
           half: str) -> tuple[dict, dict]:
    """지금 등록부로 볼 수 있는 표본(기존 + 더한 것)과 뺀 것 — 지운 표기를 겨냥한 P 항목, 등록부
    출원인이 된 상표의 N1 항목."""
    dropped: dict[str, list] = {"지운_표기의_표본": [], "등록부_출원인이_된_N1": []}
    out: dict[str, list] = {}
    for name in ("P1", "P3"):
        out[name] = []
        for item in pick(old[name], half) + pick(added[name], half):
            if (item["브랜드"], item["표기"]) in matcher.kinds:
                out[name].append(item)
            else:
                dropped["지운_표기의_표본"].append(f"{name}: {item['이름']}({item['표기']})")
    out["P2"] = []
    for item in pick(old["P2"], half) + pick(added["P2"], half):
        brand = registry.brand(item["브랜드"])
        script = fc.script_label(fc.text_key(item["이름"]))
        if brand is not None and (any(n.script == script for n in brand.notations)
                                  or any(n.text == item["표기"] for n in brand.notations)):
            out["P2"].append(item)
        else:
            dropped["지운_표기의_표본"].append(f"P2: {item['이름']}({item['표기']})")
    keys = registry.applicant_keys
    out["N1"] = []
    for item in pick(old["N1"], half):
        if applicant_keys(str(item.get("출원인") or "")) & keys:
            dropped["등록부_출원인이_된_N1"].append(f"{item['이름']} — {item.get('출원인')}")
        else:
            out["N1"].append(item)
    for name in ("N2", "N3", "N4"):
        out[name] = pick(old[name], half)
    out["N5"] = pick(added["N5"], half)
    return out, dropped


# ---- 조건별 판정 -------------------------------------------------------------------------------

_SCAN: dict = {}


def _scan_chunk(chunk: list[dict]) -> list[dict]:
    """업종 없는 이름들 — 이름마다 조건별 가장 강한 일치(없으면 빈 사전). 근거는 남기지 않는다."""
    registry, dist, floor = _SCAN["registry"], _SCAN["dist"], _SCAN["floor"]
    out = []
    for item in chunk:
        evidence = fc.collect_evidence(fc.prepare_query(item["이름"], None), registry, dist, floor)
        row = {}
        for mode, limit in _SCAN["thresholds"].items():
            strongest = fc.decide(evidence, limit).strongest
            if strongest is not None:
                row[mode] = fm.match_row(strongest)
        out.append(row)
    return out


def scan(static: dict, items: list[dict], modes, workers: int) -> list[dict]:
    """N5 처럼 큰 표본을 여러 프로세스로(fork) — 엔진을 띄우지 않은 프로세스에서만 부른다."""
    _SCAN.update(registry=static["registry"], dist=static["dist"], floor=static["floor"],
                 thresholds={mode: thresholds_for(mode) for mode in modes})
    if workers <= 1 or len(items) < 600:
        return _scan_chunk(items)
    size = 150
    chunks = [items[index:index + size] for index in range(0, len(items), size)]
    with multiprocessing.get_context("fork").Pool(workers) as pool:
        parts = pool.map(_scan_chunk, chunks)
    return [row for part in parts for row in part]


def rows_for(matcher: Matcher, items: list[dict], modes) -> list[dict]:
    limits = {mode: thresholds_for(mode) for mode in modes}
    out = []
    for item in items:
        evidence = matcher.evidence(item)
        row = {}
        for mode, limit in limits.items():
            strongest = fc.decide(evidence, limit).strongest
            if strongest is not None:
                row[mode] = fm.match_row(strongest)
        out.append(row)
    return out


def describe(item: dict, row: dict) -> str:
    note = f": {row['메모']}" if row.get("메모") else ""
    goods = "" if item.get("업종_표시") in (None, "없음") else f" + {item['업종_표시']}"
    return (f"{item['이름']}{goods} → {row['브랜드']} {row['수준']}"
            f"({row['경로']} {row['표기']} {row['점수']}{note})")


def negative_summary(items: list[dict], rows: list[dict], mode: str, *,
                     own_names: bool) -> dict:
    """음성 표본의 조건별 요약. own_names 면 같음·품음-설명으로 강하게 일치한 이름을 '브랜드
    자신의 이름일 수 있음'으로 따로 세고 센 질의(분모)에서 뺀다."""
    strong, weak, notice, own = [], [], [], []
    paths: Counter = Counter()
    for item, by_mode in zip(items, rows):
        row = by_mode.get(mode)
        if row is None:
            continue
        text = describe(item, row)
        if row["수준"] == fc.LEVEL_STRONG:
            if own_names and row["경로"] in OWN_NAME_PATHS:
                own.append(text)
            else:
                strong.append(text)
                paths[row["경로"]] += 1
        elif row["수준"] == fc.LEVEL_WEAK:
            weak.append(text)
            paths[f"약함·{row['경로']}"] += 1
        else:
            notice.append(text)
    counted = len(items) - len(own)
    return {"질의": len(items), "브랜드_자신의_이름일_수_있음": len(own), "센_질의": counted,
            "강함": len(strong), "약함": len(weak), "안내": len(notice),
            "약함_비율": round(len(weak) / counted, 6) if counted else None,
            "경로": dict(paths), "강함_목록": strong, "약함_목록": weak,
            "안내_목록": notice[:60], "자신의_이름_목록": own}


def select_mode(tables: dict) -> tuple[str, bool]:
    """선택 규칙 — (고른 조건, 한도를 지켰는가)."""
    passing = [mode for mode in tables if tables[mode]["한도_모두"]]
    if passing:
        return max(passing, key=lambda mode: (
            round(tables[mode]["P2_보통_기준용_약함_이상"] or 0.0, 9),
            -tables[mode]["음성_약한_일치_합"], -TIE_ORDER.index(mode))), True
    return min(tables, key=lambda mode: (tables[mode]["음성_약한_일치_합"],
                                         TIE_ORDER.index(mode))), False


def split_recall(matcher: Matcher, items: list[dict], limit: fc.Thresholds) -> dict:
    old = [item for item in items if not item.get("더함")]
    new = [item for item in items if item.get("더함")]

    def rate(group: list[dict]) -> float | None:
        value = fm.recall(matcher, group, limit)
        return None if value is None else round(value, 4)

    return {"전체": rate(items), "n": len(items), "기존": rate(old), "기존_n": len(old),
            "새": rate(new), "새_n": len(new)}


def compare_modes(matcher: Matcher, items: dict, negative_rows: dict) -> dict:
    """조건 네 가지의 비교표 — 음성 표본별 약한 일치 수, 보통 표기의 P2·P3 재현율, 한도."""
    normal = fc.KIND_NORMAL
    p2 = [item for item in items["P2"] if matcher.kind(item) == normal]
    p3 = [item for item in items["P3"] if matcher.kind(item) == normal]
    tables = {}
    for mode in MODES:
        limit = thresholds_for(mode)
        summary = {name: negative_summary(items[name], negative_rows[name], mode,
                                          own_names=name in ("N2", "N5"))
                   for name in ("N1", "N2", "N3", "N5")}
        n3_rate = summary["N3"]["약함"] / len(items["N3"]) if items["N3"] else 0.0
        n5_rate = summary["N5"]["약함_비율"]
        ok = {"N1_약함_2건_이하": summary["N1"]["약함"] <= SELECT_LIMITS["N1_약함_최대"],
              "N3_약함_2%_이하": n3_rate <= SELECT_LIMITS["N3_약함_비율_최대"] + 1e-12,
              "N5_약함_0.3%_이하": (n5_rate is None
                                 or n5_rate <= SELECT_LIMITS["N5_약함_비율_최대"] + 1e-12)}
        p2_recall, p3_recall = split_recall(matcher, p2, limit), split_recall(matcher, p3, limit)
        tables[mode] = {
            "음성": {name: {key: value for key, value in part.items()
                          if key not in ("안내_목록", "자신의_이름_목록")}
                   for name, part in summary.items()},
            "N3_약함_비율": round(n3_rate, 4), "한도": ok, "한도_모두": all(ok.values()),
            "음성_약한_일치_합": sum(part["약함"] for part in summary.values()),
            "P2_보통_기준용_약함_이상": p2_recall["전체"], "P2_보통": p2_recall,
            "P3_보통_기준용_약함_이상": p3_recall["전체"], "P3_보통": p3_recall}
    return tables


# ---- 기대표·목표 -------------------------------------------------------------------------------

def expectation(matcher: Matcher, thresholds: fc.Thresholds, static: dict, old: dict,
                limit: int | None = None) -> dict:
    """기대표 — 입력마다 가장 강한 일치의 수준이 기대와 같은지(바람은 보고만)."""
    resolve = fm.goods_resolver(static["presets"])
    classes_of = static["classes_of"]
    fruit = sorted({nice for _, nice in fm.FRUIT_GOODS})
    by_name: dict[str, list[dict]] = {}
    for item in fm.base_items(old["N1"]):
        by_name.setdefault(item["이름"], []).append(item)
    base_names = static["control"]["대조군"]["이름"][BASE]
    strong, weak, notice = fc.LEVEL_STRONG, fc.LEVEL_WEAK, fc.LEVEL_NOTICE
    passes = {
        E_STRONG: lambda level: level == strong, E_WEAK: lambda level: level in (strong, weak),
        E_NOTICE: lambda level: level == notice, E_NONE: lambda level: level is None,
        W_WEAK_OR_NONE: lambda level: level in (None, weak),
        W_NONE: lambda level: level is None, W_WEAK: lambda level: level in (strong, weak),
        W_NOTICE: lambda level: level == notice}
    rows = []
    for expected, name, goods_key in EXPECT[:limit] if limit else EXPECT:
        if goods_key == "@N1":
            queries = [{**item, "업종_표시": "그 상표의 지정상품(N1 기준용)",
                        "류": matcher.resolve(item)} for item in by_name.get(name, [])]
        elif goods_key == "@대조군":
            item = base_names[int(name[-1]) - 1]
            queries = [{"이름": item["이름"], "업종": sorted(item["유사군"]),
                        "업종_표시": f"{item['업종_세트']}(대조군 배정)",
                        "류": classes_of[item["업종_세트"]], "반": None}]
        else:
            codes, label = resolve(goods_key)
            classes = None if goods_key is None else (
                fruit if goods_key == "과일" else classes_of[goods_key])
            queries = [{"이름": name, "업종": codes, "업종_표시": label, "류": classes,
                        "반": None}]
        if not queries:
            rows.append({"기대": expected, "입력": name, "업종": goods_key,
                         "결과": "표본에 없음", "맞음": None})
        for query in queries:
            result = matcher.decide(query, thresholds)
            strongest = result.strongest
            level = strongest.level if strongest else None
            rows.append({"기대": expected, "입력": query["이름"], "업종": query["업종_표시"],
                         "결과": level or "없음", "일치": fm.match_row(strongest),
                         "바닥": result.floor, "맞음": passes[expected](level)})
    summary = {}
    for label in (E_STRONG, E_WEAK, E_NOTICE, E_NONE, *WISHES):
        group = [row for row in rows if row["기대"] == label]
        summary[label] = {"n": len(group), "맞음": sum(1 for row in group if row["맞음"]),
                          "다름": [f"{row['입력']} + {row['업종']} → {row['결과']}"
                                 for row in group if not row["맞음"]]}
    required = [f"[{row['기대']}] {row['입력']} + {row['업종']} → {row['결과']}"
                for row in rows if row["기대"] not in WISHES and not row["맞음"]]
    return {"요약": summary, "바람_빼고_다른_것": required, "행": rows}


def base_goals(results: dict) -> dict:
    """4절 — 고른 조건으로 본 기준용 목표."""
    def level(name: str, value: str) -> int:
        return int(results[name]["수준"].get(value, 0))

    n3_weak = level("N3", fc.LEVEL_WEAK)
    n3_rate = n3_weak / results["N3"]["질의"] if results["N3"]["질의"] else 0.0
    p2 = results["P2"][fc.KIND_NORMAL]["전체"]
    different = results["기대표"]["바람_빼고_다른_것"]
    return {
        "N1 기준용 강함 0건": {"값": level("N1", fc.LEVEL_STRONG),
                          "통과": level("N1", fc.LEVEL_STRONG) <= BASE_GOALS["N1_강함"]},
        "N1 기준용 약함 2건 이하": {
            "값": level("N1", fc.LEVEL_WEAK),
            "통과": level("N1", fc.LEVEL_WEAK) <= BASE_GOALS["N1_약함_최대"]},
        "N3 기준용 강함 0건": {"값": level("N3", fc.LEVEL_STRONG),
                          "통과": level("N3", fc.LEVEL_STRONG) <= BASE_GOALS["N3_강함"]},
        "N3 기준용 약함 2% 이하": {
            "값": round(n3_rate, 4), "건": n3_weak, "질의": results["N3"]["질의"],
            "통과": n3_rate <= BASE_GOALS["N3_약함_비율_최대"] + 1e-12},
        "보통 표기의 P2 기준용 약함 이상 80% 이상": {
            "값": p2["약함_이상_비율"], "n": p2["n"],
            "통과": p2["n"] > 0 and p2["약함_이상_비율"] >= BASE_GOALS["P2_보통_약함_이상_최소"]},
        "P1 강함이 아닌 것은 약한·흔한 말 표기의 업종 다름뿐": {
            "값": results["P1"]["그_밖"], "허용": results["P1"][fm.P1_ALLOWED],
            "통과": results["P1"]["그_밖"] == 0},
        "기대표(바람 빼고) 모두 맞음": {"값": len(different), "다름": different,
                               "통과": not different},
    }


# ---- 명령: freeze ------------------------------------------------------------------------------

def sample_counts(old: dict, added: dict) -> dict:
    out = {}
    for label, source in (("기존", old), ("더함", added)):
        for name in ("P1", "P2", "P3", "N1", "N2", "N3", "N4", "N5"):
            if name in source:
                out[f"{name}_{label}"] = dict(Counter(
                    item.get("반") or "나누지 않음" for item in source[name]
                    if not item.get("중복")))
    return out


def command_freeze(args) -> int:
    paths = _paths(args.out_dir)
    if paths["rule"].exists() and not args.force:
        print(f"거절: {paths['rule']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    baseline = json.loads(fm.STAGE21_RESULTS.read_text(encoding="utf-8"))["기준_선택"]["고른_기준"]
    mine = thresholds_for("W0").to_dict()
    if any(mine[key] != baseline[key] for key in baseline):
        print("거절: 기준값이 2-1 에서 고른 값과 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    static = load_static()
    old = fm.frozen_samples()
    added = build_added(static, old)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    paths["added_samples"].write_text(
        json.dumps(added, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    registry = static["registry"]
    frozen = {
        "설정_sha256": rule_sha256(), "스크립트_sha256": fm.file_sha256(Path(__file__)),
        "1단계_표본_sha256": fm.canonical_sha256(old),
        "더한_표본_sha256": fm.canonical_sha256(added),
        "표본_수": sample_counts(old, added), "N5": added["N5_정보"],
        "새_표기의_무관한_업종": added["무관한_업종"],
        "입력_sha256": {key: fm.file_sha256(path) for key, path in _inputs().items()},
        "등록부": {"브랜드": len(registry.brands),
                 "표장": sum(len(brand.marks) for brand in registry.brands),
                 "표기_종류": fm.kind_summary(registry),
                 "DB_세대": registry.sources.get("metadata_generation")},
        "고정": fm._now(), "설정": _settings()}  # noqa: SLF001
    paths["rule"].write_text(json.dumps(frozen, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    print(f"설정 sha256 {frozen['설정_sha256']}\n스크립트 sha256 {frozen['스크립트_sha256']}\n"
          f"더한 표본 sha256 {frozen['더한_표본_sha256']} · 1단계 표본 "
          f"{frozen['1단계_표본_sha256'][:12]}…(그대로)")
    print(json.dumps(frozen["표본_수"], ensure_ascii=False))
    print(json.dumps(frozen["N5"], ensure_ascii=False))
    return 0


def _check_frozen(paths: dict) -> tuple[dict, dict] | None:
    """고정본과 지금의 설정·입력·더한 표본이 같은지 — (고정본, 더한 표본)."""
    if not paths["rule"].exists() or not paths["added_samples"].exists():
        print("거절: 먼저 freeze", file=sys.stderr)
        return None
    frozen = json.loads(paths["rule"].read_text(encoding="utf-8"))
    if frozen["설정_sha256"] != rule_sha256():
        print("거절: 설정이 고정본과 다릅니다", file=sys.stderr)
        return None
    added = json.loads(paths["added_samples"].read_text(encoding="utf-8"))
    if frozen["더한_표본_sha256"] != fm.canonical_sha256(added):
        print("거절: 더한 표본이 고정본과 다릅니다", file=sys.stderr)
        return None
    changed = [key for key, path in _inputs().items()
               if fm.file_sha256(path) != frozen["입력_sha256"].get(key)]
    if changed:
        print(f"거절: 입력이 고정 때와 다릅니다 — {changed}", file=sys.stderr)
        return None
    return frozen, added


# ---- 명령: base(기준용) ------------------------------------------------------------------------

def smoke_cut(items: dict) -> dict:
    """스모크 — 표본마다 앞의 일부만(기존과 더한 것이 고루 들게)."""
    def brands(rows: list[dict], count: int) -> set[str]:
        return set(list(dict.fromkeys(row["브랜드"] for row in rows))[:count])

    def halves(rows: list[dict], count: int) -> list[dict]:
        old = [row for row in rows if not row.get("더함")]
        new = [row for row in rows if row.get("더함")]
        return old[:count] + new[:count]

    keep = brands([r for r in items["P1"] if not r.get("더함")], SMOKE["P1_브랜드"]) | brands(
        [r for r in items["P1"] if r.get("더함")], SMOKE["P1_브랜드"])
    notations = set(list(dict.fromkeys(
        (r["브랜드"], r["표기"]) for r in items["P3"] if not r.get("더함")))[:SMOKE["P3_표기"]])
    notations |= set(list(dict.fromkeys(
        (r["브랜드"], r["표기"]) for r in items["P3"] if r.get("더함")))[:SMOKE["P3_표기"]])
    return {"P1": [r for r in items["P1"] if r["브랜드"] in keep],
            "P2": halves(items["P2"], SMOKE["P2"] * 2),
            "P3": [r for r in items["P3"] if (r["브랜드"], r["표기"]) in notations],
            "N1": items["N1"][:SMOKE["N1"]], "N2": items["N2"][:SMOKE["N2"]],
            "N3": items["N3"][:SMOKE["N3"] * 2], "N4": items["N4"][:SMOKE["N4"]],
            "N5": items["N5"][:SMOKE["N5"]]}


def base_report(results: dict) -> str:
    chosen = results["고른_조건"]
    lines = [f"# 유명 상표 확인 — 판정 규칙 확정: 기준용 ({results.get('끝', '')})", "",
             f"- 설정 sha256 `{results['설정_sha256']}`, 스모크 {results['스모크']}",
             f"- 계산한 질의: {json.dumps(results['계산한_질의'], ensure_ascii=False)}", "",
             "## 약한 일치 조건", "",
             "| 조건 | N1 약함 | N2 약함 | N3 약함(비율) | N5 약함(비율) | 한도 | P2 보통 약함 이상"
             " | P3 보통 약함 이상 |", "|---|---|---|---|---|---|---|---|"]
    for mode, row in results["조건_비교"].items():
        neg = row["음성"]
        lines.append(
            f"| {mode} | {neg['N1']['약함']} | {neg['N2']['약함']} | {neg['N3']['약함']}"
            f"({row['N3_약함_비율']}) | {neg['N5']['약함']}({neg['N5']['약함_비율']}) | "
            f"{'지킴' if row['한도_모두'] else '미달'} | {row['P2_보통_기준용_약함_이상']}"
            f"(n {row['P2_보통']['n']}) | {row['P3_보통_기준용_약함_이상']}"
            f"(n {row['P3_보통']['n']}) |")
    lines += ["", f"고른 조건: **{chosen['조건']}**" + ("" if chosen["한도_지킴"]
                                                    else " — 한도 미달"), "", "## 목표"]
    for name, row in results["목표"].items():
        detail = {key: value for key, value in row.items() if key != "통과"}
        lines.append(f"- {'통과' if row['통과'] else '미달'} — {name}: "
                     f"{json.dumps(detail, ensure_ascii=False)}")
    lines += ["", "## 기대표"]
    for label, row in results["기대표"]["요약"].items():
        lines.append(f"- {label}: {row['맞음']}/{row['n']}" + (
            f" — 다름: {'; '.join(row['다름'])}" if row["다름"] else ""))
    return "\n".join(lines) + "\n"


def command_base(args) -> int:
    paths = _paths(args.out_dir)
    smoke = bool(args.smoke)
    if smoke and args.out_dir.resolve() == TRIALS.resolve():
        print("거절: 스모크는 --out-dir 로 다른 폴더에", file=sys.stderr)
        return EXIT_REFUSED
    checked = _check_frozen(paths)
    if checked is None:
        return EXIT_REFUSED
    frozen, added = checked
    if paths["holdout"].exists() and not smoke:
        print("거절: 확인용을 이미 봤습니다 — 기준용을 다시 재지 않습니다", file=sys.stderr)
        return EXIT_REFUSED
    if paths["base"].exists() and not args.force:
        print(f"거절: {paths['base']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    static = load_static()
    old = fm.frozen_samples()
    registry = static["registry"]
    matcher = Matcher(registry, static["dist"], static["floor"],
                      classes_resolver(static["classes_of"], static["records"]))
    items, dropped = usable(old, added, registry, matcher, static["applicant_keys"], BASE)
    if smoke:
        items = smoke_cut(items)
    for name in ("P1", "P2", "P3", "N1", "N2", "N3", "N4"):
        for item in items[name]:
            matcher.evidence(item)
    print(f"  일치 근거 {time.perf_counter() - started:.1f}초", flush=True)
    negative_rows = {name: rows_for(matcher, items[name], MODES) for name in ("N1", "N2", "N3")}
    began = time.perf_counter()
    negative_rows["N5"] = scan(static, items["N5"], MODES, args.workers)
    print(f"  N5 {len(items['N5'])}질의 {time.perf_counter() - began:.1f}초", flush=True)
    tables = compare_modes(matcher, items, negative_rows)
    mode, within = select_mode(tables)
    thresholds = thresholds_for(mode)
    normal = fc.KIND_NORMAL
    results: dict = {
        "설정_sha256": frozen["설정_sha256"], "스모크": smoke, "시작": fm._now(),  # noqa: SLF001
        "스크립트_sha256(고정 때)": frozen["스크립트_sha256"],
        "스크립트_sha256(잴 때)": fm.file_sha256(Path(__file__)),
        "기본_모델": rm.MODEL_VERSION, "결합_하한": static["floor"],
        "등록부_sha256": fm.file_sha256(fc.DEFAULT_REGISTRY_PATH),
        "표기_종류": fm.kind_summary(registry), "뺀_표본": dropped,
        "계산한_질의": {name: len(rows) for name, rows in items.items()} | {
            "P2_보통_표기": sum(1 for i in items["P2"] if matcher.kind(i) == normal),
            "P3_보통_표기": sum(1 for i in items["P3"] if matcher.kind(i) == normal)},
        "조건_비교": tables,
        "고른_조건": {"조건": mode, "한도_지킴": within, "기준": thresholds.to_dict()},
        "P1": fm.p1_table(matcher, items["P1"], thresholds),
        "P2": fm.recall_by_kind(matcher, items["P2"], thresholds),
        "P3": fm.recall_by_kind(matcher, items["P3"], thresholds),
        "N1": fm.match_list(matcher, items["N1"], thresholds),
        "N2": fm.match_list(matcher, items["N2"], thresholds),
        "N3": fm.match_list(matcher, items["N3"], thresholds),
        "N4": {"행": [{"이름": item["이름"],
                      "일치": fm.match_row(matcher.decide(item, thresholds).strongest),
                      "바닥": matcher.decide(item, thresholds).floor} for item in items["N4"]]},
        "N5": negative_summary(items["N5"], negative_rows["N5"], mode, own_names=True),
        "N2_자신의_이름": negative_summary(items["N2"], negative_rows["N2"], mode,
                                      own_names=True),
    }
    results["기대표"] = expectation(matcher, thresholds, static, old,
                                 SMOKE["기대표"] if smoke else None)
    results["목표"] = base_goals(results)
    results["목표_모두_통과"] = all(row["통과"] for row in results["목표"].values())
    results.update(걸린_시간_s=round(time.perf_counter() - started, 1), 끝=fm._now())  # noqa: SLF001
    paths["base"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    paths["report"].write_text(base_report(results), encoding="utf-8")
    print(base_report(results))
    print(f"→ {paths['base']}")
    return 0 if results["목표_모두_통과"] else EXIT_FAILED


# ---- 명령: holdout(확인용 — 한 번) --------------------------------------------------------------

def holdout_goals(results: dict, base: dict) -> dict:
    n1 = results["N1"]
    other_strong = sum(count for path, count in n1["경로"].items()
                       if not path.startswith("약함") and path != fc.PATH_EXACT)
    p2_base = base["P2"][fc.KIND_NORMAL]["전체"]["약함_이상_비율"]
    p2_now = results["P2"][fc.KIND_NORMAL]["전체"]["약함_이상_비율"]
    goals = {
        "N1 확인용 소리·철자·품음 강함 1건 이하": {
            "값": other_strong, "같음으로_생긴_강함(목록만)": n1["경로"].get(fc.PATH_EXACT, 0),
            "통과": other_strong <= HOLDOUT_GOALS["N1_강함(소리·철자·품음)_최대"]},
        "N1 확인용 약함 4건 이하": {"값": n1["약함"],
                             "통과": n1["약함"] <= HOLDOUT_GOALS["N1_약함_최대"]},
        "N3 확인용 강함 0건": {"값": results["N3"]["강함"],
                          "통과": results["N3"]["강함"] <= HOLDOUT_GOALS["N3_강함"]},
        "N3 확인용 약함 2건 이하": {"값": results["N3"]["약함"],
                             "통과": results["N3"]["약함"] <= HOLDOUT_GOALS["N3_약함_최대"]},
        "보통 표기의 P2 확인용 재현율이 기준용보다 15%p 넘게 낮지 않음": {
            "값": p2_now, "기준용": p2_base, "n": results["P2"][fc.KIND_NORMAL]["전체"]["n"],
            "통과": p2_now is not None and p2_base is not None
            and p2_now >= p2_base - HOLDOUT_GOALS["P2_재현율_하락_최대"] - 1e-12},
    }
    base_rate, now_rate = base["N5"]["약함_비율"], results["N5"]["약함_비율"]
    if now_rate is not None and base_rate is not None:
        limit = base_rate * HOLDOUT_GOALS["N5_배수"] + HOLDOUT_GOALS["N5_더함"]
        goals["N5 확인용 약함 비율 ≤ 기준용 × 2 + 0.1%p"] = {
            "값": now_rate, "기준용": base_rate, "한도": round(limit, 6),
            "건": results["N5"]["약함"], "통과": now_rate <= limit + 1e-12}
    return goals


def holdout_report(results: dict) -> str:
    lines = [f"# 유명 상표 확인 — 판정 규칙 확정: 확인용 ({results.get('끝', '')})", "",
             f"- 설정 sha256 `{results['설정_sha256']}`, 스모크 {results['스모크']}, 조건 "
             f"{results['조건']}",
             f"- 계산한 질의: {json.dumps(results['계산한_질의'], ensure_ascii=False)}", "",
             "## 목표"]
    for name, row in results["목표"].items():
        detail = {key: value for key, value in row.items() if key != "통과"}
        lines.append(f"- {'통과' if row['통과'] else '미달'} — {name}: "
                     f"{json.dumps(detail, ensure_ascii=False)}")
    for name in ("N1", "N3", "N5"):
        part = results[name]
        own = part["브랜드_자신의_이름일_수_있음"]
        lines += ["", f"## {name} 확인용 — 질의 {part['질의']}, 강함 {part['강함']}, 약함 "
                      f"{part['약함']}, 자신의 이름일 수 있음 {own}"]
        lines += [f"- 강함: {text}" for text in part["강함_목록"]]
        lines += [f"- 약함: {text}" for text in part["약함_목록"]]
    return "\n".join(lines) + "\n"


def command_holdout(args) -> int:
    paths = _paths(args.out_dir)
    smoke = bool(args.smoke)
    if smoke and args.out_dir.resolve() == TRIALS.resolve():
        print("거절: 스모크는 --out-dir 로 다른 폴더에", file=sys.stderr)
        return EXIT_REFUSED
    checked = _check_frozen(paths)
    if checked is None or not paths["base"].exists():
        print("거절: 먼저 freeze → base", file=sys.stderr)
        return EXIT_REFUSED
    frozen, added = checked
    base = json.loads(paths["base"].read_text(encoding="utf-8"))
    if base["설정_sha256"] != frozen["설정_sha256"] or bool(base["스모크"]) != smoke:
        print("거절: 기준용 결과가 이 고정본의 것이 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    if not smoke and not base["목표_모두_통과"]:
        print("거절: 기준용 목표(4절)가 미달입니다 — 확인용은 계산하지 않습니다", file=sys.stderr)
        return EXIT_REFUSED
    if not smoke and base["등록부_sha256"] != fm.file_sha256(fc.DEFAULT_REGISTRY_PATH):
        print("거절: 등록부가 기준용을 잰 때와 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    if paths["holdout"].exists() and not smoke:
        print("거절: 확인용은 한 번만 봅니다(결과가 이미 있습니다)", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    static = load_static()
    old = fm.frozen_samples()
    registry = static["registry"]
    mode = base["고른_조건"]["조건"]
    thresholds = thresholds_for(mode)
    matcher = Matcher(registry, static["dist"], static["floor"],
                      classes_resolver(static["classes_of"], static["records"]),
                      holdout=not smoke)
    # 스모크는 확인용 대신 기준용의 일부로 코드만 확인한다(확인용은 건드리지 않는다)
    items, dropped = usable(old, added, registry, matcher, static["applicant_keys"],
                            BASE if smoke else HOLDOUT)
    if smoke:
        items = smoke_cut(items)
    rows = {name: rows_for(matcher, items[name], (mode,)) for name in ("N1", "N3")}
    rows["N5"] = scan(static, items["N5"], (mode,), args.workers)
    results: dict = {
        "설정_sha256": frozen["설정_sha256"], "스모크": smoke, "시작": fm._now(),  # noqa: SLF001
        "스크립트_sha256(잴 때)": fm.file_sha256(Path(__file__)), "조건": mode,
        "기준": thresholds.to_dict(), "뺀_표본": dropped,
        "등록부_sha256": fm.file_sha256(fc.DEFAULT_REGISTRY_PATH),
        "계산한_질의": {name: len(part) for name, part in items.items()},
        "N1": negative_summary(items["N1"], rows["N1"], mode, own_names=False),
        "N3": negative_summary(items["N3"], rows["N3"], mode, own_names=False),
        "N5": negative_summary(items["N5"], rows["N5"], mode, own_names=True),
        "P2": fm.recall_by_kind(matcher, items["P2"], thresholds),
        "P3": fm.recall_by_kind(matcher, items["P3"], thresholds),
    }
    results["목표"] = holdout_goals(results, base)
    results["목표_모두_통과"] = all(row["통과"] for row in results["목표"].values())
    results.update(걸린_시간_s=round(time.perf_counter() - started, 1), 끝=fm._now())  # noqa: SLF001
    paths["holdout"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    print(holdout_report(results))
    print(f"→ {paths['holdout']}")
    if smoke:
        return 0
    if not results["목표_모두_통과"]:
        print("확인용 목표 미달 — 규칙을 확정하지 않습니다")
        return EXIT_FAILED
    confirmed = confirmation(frozen, base, results, registry, static["floor"])
    CONFIRMED_FILE.write_text(json.dumps(confirmed, ensure_ascii=False, indent=1) + "\n",
                              encoding="utf-8")
    print(f"확정 → {CONFIRMED_FILE}")
    return 0


def confirmation(frozen: dict, base: dict, holdout: dict, registry: fc.Registry,
                 floor: float) -> dict:
    """확정 파일 — 규칙(판정 모듈)·기준·등록부의 해시와 측정 요약. 서비스에 연결할 때 이 값으로
    판정한다."""
    def goals(source: dict) -> dict:
        return {name: {key: value for key, value in row.items() if key != "다름"}
                for name, row in source["목표"].items()}

    return {
        "version": CONFIRMED_VERSION, "확정": fm._now(),  # noqa: SLF001
        "설정_sha256": frozen["설정_sha256"],
        "규칙": {"판정_모듈": "ml/src/famous_check.py",
               "판정_모듈_sha256": fm.file_sha256(ML_ROOT / "src" / "famous_check.py"),
               "약한_일치_조건": holdout["조건"], "기준": holdout["기준"], "결합_하한": floor,
               "로고_글자끼리_유사도": fc.LOGO_TEXT_SIMILARITY},
        "등록부": {"파일": "shared/famous_registry.json", "version": registry.version,
                 "sha256": fm.file_sha256(fc.DEFAULT_REGISTRY_PATH),
                 "overrides_sha256": fm.file_sha256(fc.DEFAULT_OVERRIDES_PATH),
                 "브랜드": len(registry.brands),
                 "DB_세대": registry.sources.get("metadata_generation")},
        "측정": {"스크립트": "ml/scripts/famous_check_confirm.py",
               "스크립트_sha256": holdout["스크립트_sha256(잴 때)"],
               "기준용_목표": goals(base), "확인용_목표": goals(holdout),
               "조건_비교": {mode: {"한도_모두": row["한도_모두"],
                                  "음성_약한_일치_합": row["음성_약한_일치_합"],
                                  "P2_보통_기준용_약함_이상": row["P2_보통_기준용_약함_이상"]}
                         for mode, row in base["조건_비교"].items()}},
        "note": ("등록부·판정 모듈·기준이 이 해시와 다르면 확정한 규칙이 아니다 — 고친 뒤에는 "
                 "famous_check_confirm.py 를 다시(확인용은 이미 본 표본이 된다)."),
    }


# ---- 명령: images(실제 엔진 — 로고·이미지 속 글자·미리 보기) ------------------------------------

def image_review(context: dict, static: dict, old: dict, thresholds: fc.Thresholds,
                 keep: int | None) -> dict:
    """로고(규칙 5)와 이미지 속 글자(규칙 6)의 헛일치 — 대표 로고끼리, 덜 닮은 이미지 대조군,
    표본 A 질의 이미지, N1 기준용 이미지. 확인용 이미지는 건드리지 않는다."""
    registry = static["registry"]
    logo = fm.Logo(context, registry)
    logo.prepare()
    rows = [{"브랜드": brand, "출원번호": mark.appno, "상표명": mark.title, "역할": mark.role,
             "구분": logo.kinds[index], "사진_판정": logo.photos[index]}
            for index, (brand, mark, _) in enumerate(logo.marks)]
    pairs, pairs_before = [], 0
    scores = logo.matrix @ logo.matrix.T
    for i, (brand_a, mark_a, _) in enumerate(logo.marks):
        for j in range(i + 1, len(logo.marks)):
            brand_b, mark_b, _ = logo.marks[j]
            value = round(min(1.0, max(0.0, float(scores[i, j]))), 4)
            if brand_a == brand_b or not logo.is_risk(value):
                continue
            pairs_before += 1
            if fc.logo_match(value, fc.GRADE_RISK, logo_kind=logo.kinds[i],
                             query_kind=logo.kinds[j], logo_photo=logo.photos[i],
                             query_photo=logo.photos[j]):
                pairs.append({"유사도": value, "가": f"{brand_a} {mark_a.appno}",
                              "나": f"{brand_b} {mark_b.appno}",
                              "구분": [logo.kinds[i], logo.kinds[j]]})
    owners = registry.applicant_keys
    own_logos = {mark.appno for _, mark, _ in logo.marks}

    def negatives(entries: list[dict]) -> dict:
        measured = photos = 0
        logo_hits, before_hits, text_hits = [], [], []
        for entry in entries:
            image = logo.direct(entry["경로"].read_bytes())
            if image is None:
                continue
            embedding = logo.embed(image)
            photo = bool(logo.photo(embedding))
            photos += photo
            measured += 1
            seen = fm.read_text(image)
            known = bool(entry.get("등록부_출원인"))
            if not photo:  # 사진으로 판정된 질의는 로고 일치를 보지 않는다
                for brand, hit in logo.strong(embedding, exclude=entry.get("출원번호"),
                                              query_kind=seen["유형"]).items():
                    logo_hits.append({"질의": entry["표시"], "질의_구분": seen["유형"],
                                      "브랜드": brand, **hit, "등록부_출원인의_표장": known})
                before_hits += [entry["표시"] for _ in logo.strong(
                    embedding, exclude=entry.get("출원번호"), rule=False)]
            if seen["글자"]:
                result = fc.check_famous(None, None, registry, thresholds, dist=static["dist"],
                                         goods_floor=static["floor"], ocr_text=seen["글자"])
                for match in result.matches:
                    text_hits.append({"질의": entry["표시"], "글자": seen["글자"],
                                      "브랜드": match.brand, "경로": match.path,
                                      "표기": match.notation, "등록부_출원인의_표장": known})
        return {"이미지": len(entries), "잰_이미지": measured, "사진으로_판정": photos,
                "로고_강함인_이미지": len({hit["질의"] for hit in logo_hits}),
                "로고_강함(등록부_출원인_빼고)": len({hit["질의"] for hit in logo_hits
                                             if not hit["등록부_출원인의_표장"]}),
                "로고_강함(글자·사진 규칙 전)": len(set(before_hits)),
                "글자로_강함인_이미지": len({hit["질의"] for hit in text_hits}),
                "글자로_강함(등록부_출원인_빼고)": len({hit["질의"] for hit in text_hits
                                              if not hit["등록부_출원인의_표장"]}),
                "로고_목록": logo_hits, "글자_목록": text_hits}

    queries = {query.key: query for query in context["A"]}
    control = static["control"]["대조군"]["이미지"]
    control_keys = (control[BASE] + control[HOLDOUT])[:keep]
    n1 = [item for item in fm.logo_n1_marks(old) if item["출원번호"] not in own_logos][:keep]
    return {
        "대표_로고": len(rows), "구분": dict(Counter(row["구분"] for row in rows)),
        "사진_판정": [f"{row['브랜드']} {row['출원번호']}" for row in rows if row["사진_판정"]],
        "다른_브랜드의_대표_로고끼리_강함": {"쌍": len(pairs), "규칙_전": pairs_before,
                                  "목록": pairs},
        "대조군_덜_닮은_이미지": negatives(
            [{"표시": key, "경로": queries[key].path} for key in control_keys]),
        "표본A_질의_이미지": negatives(
            [{"표시": f"{query.key} {query.name}", "경로": query.path}
             for query in context["A"][:keep]]),
        "N1_기준용_상표_이미지": negatives(
            [{"표시": f"{item['출원번호']} {item['이름']} ({item.get('출원인')})",
              "경로": fm.IMAGES_DIR / item["이미지"], "출원번호": item["출원번호"],
              "등록부_출원인": bool(static["applicant_keys"](
                  str(item.get("출원인") or "")) & owners)} for item in n1]),
        "행": rows}


def preview(context: dict, static: dict, thresholds: fc.Thresholds,
            limit: int | None) -> list[dict]:
    """미리 보기 — 지금 서비스의 전체 등급에 유명 상표 일치의 바닥(보호 범위 반영)을 얹으면."""
    from scripts import named_shared_threshold as second

    ms, engine, registry = context["ms"], context["engine"], static["registry"]
    resolve = fm.goods_resolver(static["presets"])
    classes_of, codes_of = static["classes_of"], static["codes_of"]
    fruit = sorted({nice for _, nice in fm.FRUIT_GOODS})
    scenarios = {key: (title, inputs)
                 for key, title, inputs in second.scenario_inputs(ms, context["service"])}
    base_names = static["control"]["대조군"]["이름"][BASE]
    rows = []

    def classes_for(codes) -> list[int] | None:
        for preset_id, preset_codes in codes_of.items():
            if codes and sorted(codes) == preset_codes:
                return classes_of[preset_id]
        return None

    def run(name: str, codes, classes, goods_label: str, note: str = "") -> None:
        data = engine.multi_search(image=None, name=name, goods_codes=codes,
                                   top_k=5).to_dict()
        overall = data["overall"]
        result = fc.check_famous(name, codes, registry, thresholds, dist=static["dist"],
                                 goods_floor=static["floor"], goods_classes=classes)
        strongest = result.strongest
        rows.append({
            "입력": name, "업종": goods_label, "지금_등급": overall["grade"],
            "지금_위험도": overall["prob"],
            "지금_1위": data["candidates"][0]["title"] if data["candidates"] else None,
            "일치": fm.match_row(strongest),
            "보호_범위": strongest.protection if strongest else None,
            "그_밖의_일치": [fm.match_row(match) for match in result.matches[1:3]],
            "바닥": result.floor,
            "바닥_적용_등급": fm.grade_max(overall["grade"], result.floor), "메모": note})

    for name, preset_id in PREVIEW[:limit] if limit else PREVIEW:
        if name.startswith("@대조군"):
            item = base_names[int(name[-1]) - 1]
            run(item["이름"], sorted(item["유사군"]), classes_of[item["업종_세트"]],
                f"{item['업종_세트']}(대조군 배정)", note="지어낸 이름 대조군 기준용")
        elif name.startswith("@"):
            title, inputs = scenarios[name[1:]]
            codes = inputs.get("goods_codes")
            run(inputs["name"], codes, classes_for(codes), title,
                note=f"시연 입력 그대로({name[1:]})")
        else:
            codes, label = resolve(preset_id)
            classes = None if preset_id is None else (
                fruit if preset_id == "과일" else classes_of[preset_id])
            run(name, codes, classes, label)
    return rows


def command_images(args) -> int:
    paths = _paths(args.out_dir)
    smoke = bool(args.smoke)
    checked = _check_frozen(paths)
    if checked is None or not paths["base"].exists():
        print("거절: 먼저 freeze → base", file=sys.stderr)
        return EXIT_REFUSED
    base = json.loads(paths["base"].read_text(encoding="utf-8"))
    thresholds = thresholds_for(base["고른_조건"]["조건"])
    started = time.perf_counter()
    static = load_static()
    old = fm.frozen_samples()
    context = fm.load_context()
    results = {"설정_sha256": checked[0]["설정_sha256"], "스모크": smoke,
               "조건": base["고른_조건"]["조건"], "기본_모델": rm.MODEL_VERSION,
               "로고·이미지_속_글자": image_review(
                   context, static, old, thresholds, SMOKE["음성_이미지"] if smoke else None),
               "미리_보기": preview(context, static, thresholds,
                                SMOKE["미리_보기"] if smoke else None)}
    results.update(걸린_시간_s=round(time.perf_counter() - started, 1), 끝=fm._now())  # noqa: SLF001
    paths["images"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")
    review = results["로고·이미지_속_글자"]
    print(f"대표 로고 {review['대표_로고']}건 {review['구분']} · 사진 판정 "
          f"{len(review['사진_판정'])} · 다른 브랜드의 대표 로고끼리 강함 "
          f"{review['다른_브랜드의_대표_로고끼리_강함']['쌍']}쌍")
    for key in ("대조군_덜_닮은_이미지", "표본A_질의_이미지", "N1_기준용_상표_이미지"):
        part = review[key]
        print(f"{key}: {part['잰_이미지']}장(사진 판정 {part['사진으로_판정']}) — 로고 강함 "
              f"{part['로고_강함인_이미지']}(등록부 출원인 빼고 "
              f"{part['로고_강함(등록부_출원인_빼고)']}, 규칙 전 "
              f"{part['로고_강함(글자·사진 규칙 전)']}) · 글자로 강함 "
              f"{part['글자로_강함인_이미지']}(등록부 출원인 빼고 "
              f"{part['글자로_강함(등록부_출원인_빼고)']})")
    print(f"미리 보기 {len(results['미리_보기'])}행 → {paths['images']}")
    return 0


# ---- 명령: classes(서비스 연결 준비 — 보고만) ---------------------------------------------------

def representative_classes(goods_map) -> dict[str, int]:
    """유사군 코드 → 대표 류(변환표에서 그 코드가 붙은 상품이 가장 많은 류, 같으면 작은 번호)."""
    counts: dict[str, Counter] = {}
    for entry in goods_map.entries:
        for code in entry.similarity_codes:
            counts.setdefault(code, Counter())[int(entry.nice_class)] += 1
    return {code: min(count, key=lambda nice: (-count[nice], nice))
            for code, count in counts.items()}


def classes_from_codes(codes, codes_of: dict, classes_of: dict,
                       representative: dict[str, int]) -> tuple[list[int], str]:
    """질의의 류를 유사군 코드만으로 정하는 안 — (류, 근거). ① 코드 집합이 어느 업종 세트의 코드와
    같으면 그 세트의 류 ② 아니면 코드마다 대표 류의 합집합. 판정에는 쓰지 않는다(보고용)."""
    wanted = sorted({str(code).strip().upper() for code in codes or () if str(code).strip()})
    same = [preset for preset, preset_codes in codes_of.items() if list(preset_codes) == wanted]
    if same:
        return (sorted({nice for preset in same for nice in classes_of[preset]}),
                f"업종 세트({'·'.join(same)})")
    return (sorted({representative[code] for code in wanted if code in representative}),
            "코드별 대표 류")


def command_classes(args) -> int:
    """질의의 류를 코드에서 정하는 안으로 기대표와 N1 기준용 질의를 다시 판정해 측정 때(류를 따로
    준 것)와 견준다. 확인용 표본은 쓰지 않는다."""
    paths = _paths(args.out_dir)
    if _check_frozen(paths) is None or not paths["base"].exists():
        print("거절: 먼저 freeze → base", file=sys.stderr)
        return EXIT_REFUSED
    base = json.loads(paths["base"].read_text(encoding="utf-8"))
    thresholds = thresholds_for(base["고른_조건"]["조건"])
    static = load_static()
    old = fm.frozen_samples()
    registry, dist = static["registry"], static["dist"]
    representative = representative_classes(gm.load_goods_map())
    explicit = classes_resolver(static["classes_of"], static["records"])
    resolve = fm.goods_resolver(static["presets"])
    fruit = sorted({nice for _, nice in fm.FRUIT_GOODS})
    base_names = static["control"]["대조군"]["이름"][BASE]
    by_name: dict[str, list[dict]] = {}
    for item in fm.base_items(old["N1"]):
        by_name.setdefault(item["이름"], []).append(item)
    queries: list[dict] = []
    for expected, name, goods_key in EXPECT:
        if goods_key == "@N1":
            queries += [{"묶음": "기대표", "기대": expected, "이름": item["이름"],
                         "업종": item["업종"], "업종_표시": "그 상표의 지정상품",
                         "류": explicit(item)} for item in by_name.get(name, [])]
        elif goods_key == "@대조군":
            item = base_names[int(name[-1]) - 1]
            queries.append({"묶음": "기대표", "기대": expected, "이름": item["이름"],
                            "업종": sorted(item["유사군"]), "업종_표시": item["업종_세트"],
                            "류": static["classes_of"][item["업종_세트"]]})
        elif goods_key is not None:
            codes, label = resolve(goods_key)
            given = fruit if goods_key == "과일" else static["classes_of"][goods_key]
            queries.append({"묶음": "기대표", "기대": expected, "이름": name, "업종": codes,
                            "업종_표시": label, "류": given})
    keys = registry.applicant_keys
    for item in pick(old["N1"], BASE):
        if item.get("업종") and not static["applicant_keys"](str(item.get("출원인") or "")) & keys:
            queries.append({"묶음": "N1 기준용", "이름": item["이름"], "업종": item["업종"],
                            "업종_표시": "그 상표의 지정상품", "류": explicit(item)})

    def judge(query: dict, classes) -> tuple:
        found = fc.collect_evidence(fc.prepare_query(query["이름"], query["업종"], classes),
                                    registry, dist, static["floor"])
        strongest = fc.decide(found, thresholds).strongest
        level = None if strongest is None else (strongest.brand, strongest.level, strongest.path)
        return level, {item.brand: item.overlap for item in found}

    rows, by_reason = [], Counter()
    summary = {name: {"질의": 0, "류가_같음": 0, "결과가_같음": 0, "겹침이_같음": 0,
                      "코드에서_전부_얻으면_결과가_같음": 0}
               for name in ("기대표", "N1 기준용")}
    for query in queries:
        given = sorted(query["류"] or [])
        derived, reason = classes_from_codes(query["업종"], static["codes_of"],
                                             static["classes_of"], representative)
        by_reason[reason.split("(")[0]] += 1
        measured, measured_overlap = judge(query, given)
        proposed, proposed_overlap = judge(query, derived)
        widest, _ = judge(query, None)  # 류를 주지 않으면 코드가 붙은 상품의 류 전부(지금 기본)
        part = summary[query["묶음"]]
        part["질의"] += 1
        part["류가_같음"] += given == derived
        part["결과가_같음"] += measured == proposed
        part["겹침이_같음"] += measured_overlap == proposed_overlap
        part["코드에서_전부_얻으면_결과가_같음"] += measured == widest
        if given != derived or measured != proposed or measured_overlap != proposed_overlap:
            changed = sorted(brand for brand in measured_overlap
                             if measured_overlap[brand] != proposed_overlap[brand])
            rows.append({"묶음": query["묶음"], "이름": query["이름"],
                         "업종": query["업종_표시"], "코드": sorted(query["업종"]),
                         "측정_때의_류": given, "코드에서_정한_류": derived, "근거": reason,
                         "측정_때의_결과": measured, "코드로_넣은_결과": proposed,
                         "겹침이_달라진_브랜드": changed})
    results = {"설정_sha256": base["설정_sha256"], "조건": base["고른_조건"]["조건"],
               "방법": RULE["질의의_류를_코드에서(보고만)"], "근거별_질의": dict(by_reason),
               "요약": summary, "달라진_것": rows, "때": fm._now()}  # noqa: SLF001
    paths["classes"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    print(json.dumps({"근거별": dict(by_reason), "요약": summary}, ensure_ascii=False))
    for row in rows:
        if row["측정_때의_결과"] != row["코드로_넣은_결과"] or row["겹침이_달라진_브랜드"]:
            print(f"  달라짐: [{row['묶음']}] {row['이름']} — 류 {row['측정_때의_류']} → "
                  f"{row['코드에서_정한_류']} · 결과 {row['측정_때의_결과']} → "
                  f"{row['코드로_넣은_결과']} · 겹침이 달라진 브랜드 "
                  f"{row['겹침이_달라진_브랜드']}")
    print(f"→ {paths['classes']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("freeze", "base", "holdout", "images", "classes"))
    parser.add_argument("--out-dir", type=Path, default=TRIALS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--smoke", action="store_true",
                        help="구현 확인 — 일부 표본만(다른 --out-dir 에)")
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1),
                        help="N5 를 나눠 계산하는 프로세스 수")
    args = parser.parse_args(argv)
    return {"freeze": command_freeze, "base": command_base, "holdout": command_holdout,
            "images": command_images, "classes": command_classes}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
