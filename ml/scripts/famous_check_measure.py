"""유명 상표 확인 단계 — 2-1단계 측정(통합 모델 설계 §7-14-9). 엔진·계약·화면은 바꾸지 않는다.

1단계 측정에서 드러난 규칙 문제를 고친 일치 판정 함수(src.famous_check — 엔진에서 부르지 않음)를
1단계와 같은 표본의 기준용으로 다시 잰다: 기준값 다시 고르기(강한 철자·약한 소리·약한 철자, 약한
철자의 소리 조건 S), 목표(헛일치·재현율), 기대표, 이미지 속 글자 경로, 로고 강함, 미리 보기.
규칙·선택 규칙·목표는 `RULE`·`TARGETS`·`EXPECT`(실행 전에 해시를 남긴다).

    ml/venv/bin/python ml/scripts/famous_check_measure.py freeze   # 설정·표본·입력 해시
    ml/venv/bin/python ml/scripts/famous_check_measure.py run      # 측정(고정본과 다르면 4)
    ml/venv/bin/python ml/scripts/famous_check_measure.py run --smoke --out-dir <폴더>
    ml/venv/bin/python ml/scripts/famous_check_measure.py sheet    # 확인용 시트만 다시(측정 없음)
    ml/venv/bin/python ml/scripts/famous_check_measure.py logos    # 대표 로고 점검(§7-14-11, 실제
                                                                   #   엔진 약 3분)
    ml/venv/bin/python ml/scripts/famous_check_measure.py recheck  # 등록부를 고친 뒤(§7-14-10) —
                                                                   #   2-1 에서 고른 기준 그대로
                                                                   #   기준용 목표·기대표 유지 확인

표본은 1단계에 고정한 것 그대로다(다시 만든 표본의 sha256 이 1단계 값과 같아야 한다). 확인용 표본
(P2 둘째·P3 뒤 둘·N1·N3 확인용)은 이번에도 계산하지 않는다 — 규칙을 다 고친 뒤 다음 단계에서 한
번만 본다. KIPRIS 호출 0. run 은 실제 CLIP·OCR·X3 엔진(이미지 속 글자·로고·미리 보기).
1단계 측정은 커밋 ea1d0ef 의 이 파일과 `ml/data/trials/famous_check_{rule,samples,results}.json`.

recheck 는 고정한 표본 파일(famous_check_samples.json)을 그대로 읽고(다시 만들지 않는다) 엔진을
띄우지 않는다 — 사람이 표기를 지우거나 더하고 흔한 말·예외 낱말·새 브랜드를 정한 뒤(overrides)
목표와 기대표가 2-1 결과와 같은지, 무엇이 달라졌는지 낸다(다르면 종료 코드 3). 지운 표기를 겨냥한
표본과 등록부 출원인이 된 상표의 N1 항목은 빼고 그 수를 적는다. 등록부·판정 모듈이 바뀌었으므로
freeze·run(전체 측정)은 `freeze --force` 뒤에만 돈다.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import io
import json
import random
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
for _root in (ML_ROOT, REPO_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from src import famous_check as fc  # noqa: E402
from src import famous_runtime as fr  # noqa: E402
from src.axes import distinctiveness as dx  # noqa: E402
from src.axes import goods_map as gm  # noqa: E402
from src.axes.x1_phonetic import (  # noqa: E402
    _compose,
    _decompose_syllable,
    _is_syllable,
)
from src.axes.x4_goods import goods_similarity  # noqa: E402
from src.model import risk_model as rm  # noqa: E402

TRIALS = ML_ROOT / "data" / "trials"
STEM = "famous_check_2_1"
# 1단계에 고정한 표본(ml/data/trials/famous_check_samples.json)의 sha256 — 표본은 그대로 쓴다
STAGE1_SAMPLES_SHA256 = "5bec460c4cd8c12c2cdf9ae15051d5aedf1c721842b468ba0fb322f5e7fff79c"
EXIT_REFUSED = 4
SEED = 0
BASE, HOLDOUT = "기준용", "확인용"
REVIEW_DIR = Path.home() / "marklens-archive" / "famous-check-20261124"
SAMPLES_FILE = TRIALS / "famous_check_samples.json"  # 1단계에 고정한 표본(recheck 가 그대로 읽는다)
STAGE21_RESULTS = TRIALS / "famous_check_2_1_results.json"  # recheck 가 견주는 2-1 결과
METADATA = ML_ROOT / "data" / "kipris_metadata.json"
FEATURES = TRIALS / "pairs_features.csv"
IMAGE_PARTS = TRIALS / "image_parts.csv"
CONTROL = TRIALS / "named_search_thresholds_control.json"
IMAGES_DIR = ML_ROOT / "data" / "images"
STRONG_SPELLING_GRID = (0.90, 0.95)
WEAK_SOUND_GRID = (0.90, 0.92, 0.94, 0.96)
WEAK_SPELLING_GRID = (0.75, 0.80, 0.85, 0.90)
SOUND_CONDITION_GRID = (None, 0.70, 0.80)  # S 후보 — None 은 조건 없음
# S 를 걸었을 때 보통 표기의 P2·P3 기준용 "약함 이상" 재현율이 떨어져도 되는 폭
RECALL_DROP_MAX = 0.02
N1_RATE_MAX, N3_RATE_MAX = 0.005, 0.02
LOGO_N1_IMAGES = 300
OCR_TIMEOUT_S = 20.0  # 측정에서는 OCR 을 끝까지 기다린다(서비스 상한 2초를 넘긴 수는 따로 센다)
OCR_SERVICE_LIMIT_MS = 2000.0
KIND_NAMES = fr.KIND_NAMES  # 자동 유형 → 보고 이름(서비스와 같은 표 — src.famous_runtime)
P3_PER_NOTATION = 4
FRUIT_GOODS = (("신선한 과실", 31), ("신선한 과실 판매업(도소매·중개·대행)", 35))
SMOKE = {"P1_브랜드": 2, "P2": 3, "P3_표기": 3, "N1": 30, "N2": 30, "N3": 10, "N4": 5,
         "이름_표장": 6, "음성_이미지": 5, "미리_보기": 6, "기대표": 12}

# P2 실제 모방 꼴 — (브랜드(등록부 이름), 기준용, 확인용). 1단계 지시의 목록 그대로.
P2_PAIRS = (
    ("컴포즈커피", "콤포즈커피", "컴포스커피"), ("이디야커피", "이디아", "에디야"),
    ("빽다방", "백다방", "빽따방"), ("스타벅스", "스타벅수", "스타박스"),
    ("bhc", "비에치씨", "비에이치시"), ("교촌치킨", "교춘", "쿄촌"),
    ("동대문엽기떡볶이", "엽기떡복이", "엽끼떡볶이"), ("김가네", "김가내", "킴가네"),
    ("뚜레쥬르", "뚜레주르", "뚜래쥬르"), ("던킨", "덩킨", "던킨스"),
    ("파리바게뜨", "파리바게트", "빠리바게뜨"), ("GS25", "GS24", "쥐에스25"),
    ("크린토피아", "크린토피야", "클린토피아"), ("본죽&비빔밥", "본쥭", "뽄죽"),
    ("마이크로소프트", "마이크로쏘프트", "마이크로소프드"), ("구글", "구굴", "구글르"),
    ("네이버", "네이바", "내이버"), ("인스타그램", "인스타그람", "인스타그렘"),
    ("넷플릭스", "넷플렉스", "넷프릭스"), ("에르메스", "에르매스", "헤르메스"),
    ("루이비통", "루이비똥", "루이뷔통"), ("샤넬", "샤낼", "쌰넬"),
    ("로레알 파리", "로레얄", "로래알"), ("올리브영", "올리브용", "올리부영"),
    ("세포라", "쎄포라", "세포나"), ("이케아", "이캐아", "이케야"),
    ("에어비앤비", "에어비엔비", "애어비앤비"), ("야놀자", "야놀쟈", "야널자"),
)
N4_TRAPS = (
    "스타", "벅스", "파리", "바게뜨", "올리브", "본", "김가", "비앤비", "에어", "넷", "플릭스",
    "인스타", "그램", "마이크로", "소프트", "다방", "엽기", "떡볶이", "컴포즈", "루이", "토피아",
    "네이버후드", "네이버스", "구글링", "교촌마을", "스타벅스리", "샤넬로", "채널", "CHANNEL",
    "유토피아", "넷플러스", "야놀이터", "씨유어게인", "CUTE", "CU LATER", "텍사스 BBQ",
    "맛있는 BBQ", "서울 BBQ",
)
# 미리 보기 입력 — (이름, 업종 세트 id | "과일" | None). 1단계와 같은 입력.
PREVIEW_NAMES = (
    ("BBQ", "chicken"), ("BBQ치킨", "chicken"), ("비비큐", "chicken"),
    ("텍사스 BBQ", "korean_restaurant"), ("맛있는 BBQ", "korean_restaurant"),
    ("BBQ", "clothing"),
    ("스타벅스", "cafe"), ("스타벅스", "clothing"), ("스타벅스", None),
    ("STARBUCKS COFFEE", "cafe"), ("뉴스타벅스", "cafe"), ("스타벅수", "clothing"),
    ("스타벅수", None),
    ("샤넬", "chicken"), ("샤낼", "cosmetics"), ("채널", "software"), ("CHANNEL", "software"),
    ("네이버", "flower"), ("네이버후드", "cafe"), ("헤르메스", "clothing"),
    ("구글링", "software"),
    ("@F2", None), ("@F3", None), ("@F1", None), ("@S1", None),  # 시연 입력 그대로
    ("크린토피아", "cafe"), ("파리 바게뜨", "bakery"),
    ("CU", "convenience"), ("CU LATER", "cafe"), ("씨유", "convenience"),
    ("GS25", "convenience"), ("GS24", "convenience"),
    ("김가네", "bunsik"), ("김가네", "software"), ("본죽", "korean_restaurant"),
    ("올리브", "cosmetics"), ("올리브영", "cosmetics"), ("야 놀자", "lodging"),
    ("에어비앤비", "lodging"), ("비앤비", "lodging"),
    ("애플", "과일"), ("삼성", "chicken"),
    ("@대조군1", None), ("@대조군2", None), ("@대조군3", None),
)
# P2 확인용이지만 지시의 목록(미리 보기·기대표)에 있어 계산한다
PREVIEW_HOLDOUT_SEEN = ("헤르메스",)
CHO_GROUPS = (("ㄱ", "ㄲ", "ㅋ"), ("ㄷ", "ㄸ", "ㅌ"), ("ㅂ", "ㅃ", "ㅍ"), ("ㅈ", "ㅉ", "ㅊ"),
              ("ㅅ", "ㅆ"))
JUNG_SWAPS = (("ㅐ", "ㅔ"), ("ㅓ", "ㅗ"), ("ㅡ", "ㅜ"), ("ㅗ", "ㅜ"))
JONG_NASALS = ("ㄴ", "ㅇ", "ㅁ")
LETTER_SWAPS = (("a", "e"), ("i", "y"), ("c", "k"), ("s", "z"))

# 기대표 — (기대, 이름, 업종: 업종 세트 id | "과일" | None | "@N1"(N1 기준용의 그 이름, 그 상표의
# 지정상품) | "@대조군"). 일치 수준만 본다. 지시의 목록 그대로.
E_STRONG, E_WEAK_PLUS, E_WEAK = "강함", "약함 이상(강함이면 더 좋음)", "약함 이상"
E_NOTICE, E_NONE = "안내만", "없음"
E_WISH_WEAK, E_WISH_NONE = "바람: 약함 또는 없음", "바람: 없음"
EXPECT = (
    (E_STRONG, "BBQ", "chicken"), (E_STRONG, "BBQ치킨", "chicken"),
    (E_STRONG, "BBQ 치킨집", "chicken"), (E_STRONG, "비비큐", "chicken"),
    (E_STRONG, "맛있는 BBQ", "korean_restaurant"), (E_STRONG, "BBQ", "clothing"),
    (E_STRONG, "CU", "convenience"), (E_STRONG, "CU 편의점", "convenience"),
    (E_STRONG, "씨유", "convenience"), (E_STRONG, "씨유편의점", "convenience"),
    (E_STRONG, "GS25", "convenience"), (E_STRONG, "지에스25", "convenience"),
    (E_STRONG, "김가네", "bunsik"), (E_STRONG, "김가네 분식집", "bunsik"),
    (E_STRONG, "bhc", "chicken"), (E_STRONG, "BHC치킨", "chicken"),
    (E_STRONG, "비에이치씨", "chicken"), (E_STRONG, "스타벅스", "cafe"),
    (E_STRONG, "스타벅스", "clothing"), (E_STRONG, "스타벅스", None),
    (E_STRONG, "STARBUCKS COFFEE", "cafe"), (E_STRONG, "스타벅스커피", None),
    (E_STRONG, "샤넬", "chicken"), (E_STRONG, "샤넬치킨", None),
    (E_STRONG, "샤넬옷가게", "clothing"), (E_STRONG, "네이버", "flower"),
    (E_STRONG, "크린토피아", "cafe"), (E_STRONG, "파리 바게뜨", "bakery"),
    (E_STRONG, "올리브영", "cosmetics"), (E_STRONG, "야 놀자", "lodging"),
    (E_STRONG, "에어비앤비", "lodging"), (E_STRONG, "던킨빵집", "bakery"),
    (E_STRONG, "본죽", "korean_restaurant"), (E_STRONG, "본죽식당", "korean_restaurant"),
    (E_STRONG, "교촌치킨", "chicken"),
    (E_WEAK_PLUS, "크린토피야", None), (E_WEAK_PLUS, "파리바게트", None),
    (E_WEAK_PLUS, "샤낼", "cosmetics"), (E_WEAK_PLUS, "STARBUCKSS", None),
    (E_WEAK_PLUS, "뉴스타벅스", "cafe"), (E_WEAK_PLUS, "스타벅스리", None),
    (E_WEAK, "스타벅수", "clothing"), (E_WEAK, "스타벅수", None), (E_WEAK, "네이바", None),
    (E_WEAK, "구굴", None), (E_WEAK, "교춘", None), (E_WEAK, "헤르메스", "clothing"),
    (E_NOTICE, "텍사스 BBQ", "korean_restaurant"), (E_NOTICE, "서울 BBQ", "korean_restaurant"),
    (E_NOTICE, "CU LATER", "cafe"), (E_NOTICE, "김가네", "software"),
    (E_NONE, "GS24", "convenience"), (E_NONE, "김가내", None), (E_NONE, "비에치씨", None),
    (E_NONE, "CUTE", None), (E_NONE, "씨유어게인", None), (E_NONE, "구글링", "software"),
    (E_NONE, "샤넬로", None), (E_NONE, "채널", "software"), (E_NONE, "교촌마을", None),
    (E_NONE, "파리", None), (E_NONE, "바게뜨", None), (E_NONE, "올리브", "cosmetics"),
    (E_NONE, "비앤비", "lodging"), (E_NONE, "야놀이터", None), (E_NONE, "유토피아", None),
    (E_NONE, "블루커피", "cafe"), (E_NONE, "애플", "과일"), (E_NONE, "삼성", "chicken"),
    (E_NONE, "@대조군1", "@대조군"), (E_NONE, "@대조군2", "@대조군"),
    (E_NONE, "@대조군3", "@대조군"), (E_NONE, "Airline Seoul", "@N1"),
    (E_NONE, "BIO PHARM Dongsung", "@N1"), (E_NONE, "열매속풍요 Pungyo in Fruit", "@N1"),
    (E_WISH_WEAK, "네이버후드", "cafe"), (E_WISH_WEAK, "네이버스", None),
    (E_WISH_WEAK, "넷플러스", None),
    (E_WISH_NONE, "CHANNEL", "software"), (E_WISH_NONE, "PLAY KIA", "@N1"),
    (E_WISH_NONE, "씨츄 SeeCHU", "@N1"),
)
TARGETS = {
    "N1_강함": 0, "N1_약함_최대": 2, "N2_강함": 0, "N3_일치": 0,
    "P2_보통_약함_이상_최소": 1.0, "P3_보통_약함_이상_최소": 0.95,
    "P1": "강함이 아닌 것은 약한 표기의 '업종 다름' 경우뿐",
}

RULE = {
    "목적": (
        "유명 상표 확인 2-1단계 — 1단계 측정에서 드러난 규칙 문제를 고치고 기준용 표본으로 다시 "
        "잰다. 일치 판정 모듈·등록부·측정 스크립트만 바꾼다. 확인용 표본(P2 둘째·P3 뒤 둘·N1·N3 "
        "확인용)은 계산하지 않는다. 목표를 못 채우는 항목이 있어도 멈추지 않고, 구현으로 풀 수 "
        "있는 것은 풀고 규칙 자체가 막는 것은 이유와 함께 보고한다. 목표와 기대표가 부딪치면 "
        "헛일치 한도를 우선한다."),
    "1_표기_종류": (
        "약한 표기 = 1단계 정의(유명 예외를 뺀 식별력 판정으로 자기 업종에서 조각이 모두 식별력 "
        "없음)에 더해 같은 브랜드에서 약한 표기와 소리가 0.98 이상인 표기. 머리글자 표기 = 약한 "
        "표기가 아닌 영문 3자 이하 표기와 같은 브랜드에서 그 표기와 소리가 0.98 이상인 표기 — "
        "같음과 품음-설명만 인정하고 소리·철자·품음-기타는 쓰지 않는다. 보통 표기 = 나머지. 여기서 "
        "소리 = 통째 소리(4번)."),
    "2_낱말_나누기": (
        "공백·기호로만 나눈다. split_goods_suffix 는 쓰지 않는다. 붙여 쓴 꼴은 품음에서 나머지 "
        "판정으로 처리한다."),
    "3_설명_낱말": (
        "업종 낱말 = 업종 세트 25개의 이름·별칭 전부와 가게 형태 낱말(가게·전문점·매장·샵·숍·"
        "스토어·마트·하우스·본점·지점·직영점) — 판정 모듈 안의 사전. 질의 업종이나 브랜드 업종에서 "
        "보통명칭·성질표시(1호·3호)로 판정되는 말(유명 예외를 뺀 판정). 4호·5호·6호로만 식별력이 "
        "없는 말(지명·흔한 성·한 글자)은 설명 낱말이 아니다. 나머지는 설명 낱말 하나 또는 둘을 "
        "이어 쓴 꼴까지 인정한다. 식별력 모듈의 동작과 학습 특징은 바꾸지 않는다. 해석(지시에 없어 "
        "고정): 이름·별칭이 여러 낱말이면(커피 전문점·식당(한식)) 공백·기호로 나눈 낱말 하나하나를 "
        "사전에 넣는다. 업종 낱말은 어느 업종의 질의에서나 설명 낱말이다."),
    "4_통째_비교": (
        "소리·철자는 표기 전체와 견주는 구간 전체를 통째로 견준다. 조각끼리의 최댓값을 쓰지 않고, "
        "숫자는 숫자끼리 같아야 한다. 해석(고정): 소리 = 두 붙여 쓴 꼴 전체의 읽기(문자 종류 "
        "조각마다 X1 의 읽기를 순서대로 이은 것)끼리 X1 음절 유사도의 최댓값 — 읽기가 여럿이면 "
        "(25 = 이십오·이오) 전체 읽기의 변형으로만 쓰고, X1 의 분리관찰 후보와 붙여쓴 결합어 포함 "
        "점수(_contain_sim — 한쪽이 다른 쪽의 앞·뒤 일부일 때 주는 점수)는 쓰지 않는다. 철자 = 두 "
        "붙여 쓴 꼴 전체를 자모로 푼 편집거리 유사도(x2_ortho v1 이 전체 문자열에 쓰는 식), 토큰별 "
        "후보는 쓰지 않는다. 숫자 조각의 열이 다르면 소리·철자 모두 0."),
    "5_보통_표기의_경로": (
        "같음: 낱말 묶음 = 표기. 품음: 한 낱말이 표기 + 나머지(앞이나 뒤) — 나머지가 설명 낱말이면 "
        "품음-설명(강함), 아니면 품음-기타(약함, 짧은 표기는 인정하지 않음). 소리·철자(철자는 같은 "
        "문자끼리): 대상은 낱말 묶음, 그리고 한 낱말의 앞·뒤 구간으로서 나머지가 설명 낱말인 것. "
        "해석(고정): 표기에 기호·공백이 있어 질의에서 여러 낱말로 나뉘는 경우(PAIK'S카페 → paik·"
        "s카페)를 위해 품음과 구간은 낱말 묶음에도 적용한다 — 나머지는 묶음의 끝 낱말의 뒷부분"
        "(또는 첫 낱말의 앞부분)이어야 한다. 구간은 표기의 길이 구간과 상관없이 대상이다(1단계는 "
        "중간·김만)."),
    "6_약한_철자의_소리_조건": (
        "약한 철자 일치는 같은 대상의 소리(통째)가 S 이상일 때만 인정한다. 강한 철자에는 걸지 "
        "않는다."),
    "7_약한_표기": (
        "질의에서 설명 낱말(붙여 쓴 것 포함)을 뺀 나머지가 그 표기 하나뿐일 때만 일치로 본다. "
        "업종이 없거나 브랜드 업종과 겹치면 강함. 업종이 다르고 그 표기가 그 업종에서도 식별력 "
        "없는 말이면(5호·6호는 어느 업종에서나) 안내만. 업종이 다르고 그 업종에서는 식별력이 "
        "있으면 보통 표기의 같음과 같게 다룬다. 다른 말과 함께 쓰였으면 안내만. 가림(약한 표기 "
        "조각을 같은 브랜드의 다른 표기와 견주지 않음)은 1단계대로. 해석(고정): 소리가 같아 약한 "
        "표기가 된 표기(비비큐·씨유·지에스25)의 '그 업종에서의 식별력'은 그 표기 자신이나 그것이 "
        "따르는 약한 표기(BBQ·CU·GS25) 중 하나라도 식별력 없는 말이면 없는 것으로 본다."),
    "8_브랜드_업종": (
        "이름 일치용 브랜드 업종 = 업종 세트와 역할 '이름' 표장의 지정상품(표장별 겹침의 최댓값 ≥ "
        "결합 하한 0.0252 면 겹침). 도형·다른 이름 표장의 지정상품은 쓰지 않는다. 설명 낱말 판정의 "
        "'브랜드 업종'도 같은 유사군의 합집합. 표기 종류의 '자기 업종'(1단계 정의)은 그대로."),
    "9_로고": "강함(이미지만 판단이 위험)만 쓰고 약함은 버린다.",
    "10_그대로": (
        "그 밖의 설명적 사용 안내(약한 표기가 아니어도 질의 업종에서 그 표기가 식별력 없는 말이고 "
        "브랜드 업종과 겹치지 않으면 안내), 보호 범위에 따른 전체 등급 바닥은 1단계대로."),
    "표본": (
        "1단계에 고정한 표본 그대로(다시 만든 표본의 sha256 = STAGE1_SAMPLES_SHA256). 확인용은 "
        "계산하지 않는다. 표기 종류별 집계는 표본의 '표기'(P2 는 겨냥한 표기)를 새 등록부의 종류로 "
        "나눈다 — 보통 표기의 P2 = 28쌍 중 김가네·GS25(약한 표기)·bhc(머리글자 표기)를 뺀 것."),
    "기준_선택": (
        "기준용만, 1단계와 같은 격자·한도. 단위는 질의(이름 × 업종). 강한 소리 0.98 고정. 강한 "
        "철자 {0.90, 0.95}·약한 소리 {0.90, 0.92, 0.94, 0.96}·약한 철자 {0.75, 0.80, 0.85, 0.90}을 "
        "길이 구간별로 가장 낮은 값, 없으면 그 구간에서 그 경로를 쓰지 않는다. 해석(고정): 한도는 "
        "1단계의 것 — 강한 철자는 N1·N3 기준용에서 새로 생기는 강한 일치가 0건(목표 'N1 강함 "
        "0건'과 같은 뜻; 0.5%·2% 로 보면 어떤지도 표에 적는다), 약한 소리·약한 철자는 같음·품음·"
        "강한 경로로 이미 잡힌 질의를 뺀 '새로 더하는 일치'가 N1 기준용의 0.5% 이하·N3 기준용의 2% "
        "이하. "
        "약한 철자는 그 구간의 약한 소리(고른 값)까지 켠 누적으로 센다(1단계와 같음). S: 먼저 조건 "
        "없이 기준을 고른다. 그 기준에서 {조건 없음, 0.70, 0.80} 중 보통 표기의 P2·P3 기준용 '약함 "
        "이상' 재현율이 조건 없음보다 2%p 넘게 떨어지지 않는(P2 와 P3 각각) 가장 높은 값을 S 로 "
        "한다. 고른 S 로 약한 철자 기준만 다시 고른다."),
    "목표": (
        "N1 기준용 강함 0건·약함 2건 이하, N2 강함 0건(약함은 목록), N3 기준용 0건. 보통 표기의 P2 "
        "기준용 약함 이상 100%, 보통 표기의 P3 기준용 약함 이상 95% 이상, 약한 표기·머리글자 "
        "표기의 변형은 따로 집계. P1: 강함이 아닌 것은 약한 표기의 '업종 다름' 경우뿐 — 그 밖의 "
        "것은 사유별 목록으로. 단위는 질의, 수준은 그 질의의 가장 강한 일치. 약함에는 품음-기타도 "
        "센다. N3 의 0건은 강함·약함 일치(설명적 사용 안내는 바닥이 없어 따로 적는다)."),
    "기대표": (
        "EXPECT 의 입력마다 일치 수준만 본다(가장 강한 일치). 업종은 가장 가까운 업종 세트, 업종을 "
        "적지 않은 것은 업종 없음, N1 의 이름(Airline Seoul 등)은 N1 기준용의 그 질의 그대로. "
        "'헤르메스 + 의류'는 P2 확인용이지만 지시의 목록에 있어 계산한다. 바람은 못 맞춰도 "
        "보고만."),
    "함께_잴_것": (
        "이미지 속 글자 경로: 역할 '이름' 표장 이미지 전부에서 OCR 제안 상표명(엔진이 이름 없는 "
        "이미지 질의에 주는 suggested_name = ocr.detect 의 text)이 나오는 비율과 그 글자로 자기 "
        "브랜드와 강함인 비율(업종 없음), 대조군의 덜 닮은 이미지 92장과 N1 기준용 이미지 296장"
        "(1단계 로고 음성과 같은 300장 중 사진 판정을 뺀 것)에서 어느 브랜드와든 강함인 비율(업종 "
        "없음 — N1 은 그 상표의 지정상품을 넣은 값도). 로고 강함 헛일치 2건이 어떤 상표끼리인지. "
        "1단계 미리 보기 표를 같은 입력으로 다시(보호 범위는 overrides 그대로)."),
    "스모크": "일부 표본만(SMOKE), 다른 폴더에. 확인용은 스모크에서도 계산하지 않는다.",
}


# ---- 공통 --------------------------------------------------------------------------------------

def canonical_sha256(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _settings() -> dict:
    return {"RULE": RULE, "TARGETS": TARGETS, "EXPECT": EXPECT, "SEED": SEED,
            "STAGE1_SAMPLES_SHA256": STAGE1_SAMPLES_SHA256, "P2_PAIRS": P2_PAIRS,
            "N4_TRAPS": N4_TRAPS, "PREVIEW_NAMES": PREVIEW_NAMES,
            "STRONG_SOUND": fc.STRONG_SOUND, "KIND_SOUND": fc.KIND_SOUND,
            "INITIAL_MAX_LETTERS": fc.INITIAL_MAX_LETTERS, "SHOP_WORDS": fc.SHOP_WORDS,
            "DESCRIPTIVE_REASONS": fc.DESCRIPTIVE_REASONS,
            "MAX_DESCRIPTIVE_WORDS": fc.MAX_DESCRIPTIVE_WORDS,
            "STRONG_SPELLING_GRID": STRONG_SPELLING_GRID, "WEAK_SOUND_GRID": WEAK_SOUND_GRID,
            "WEAK_SPELLING_GRID": WEAK_SPELLING_GRID,
            "SOUND_CONDITION_GRID": SOUND_CONDITION_GRID, "RECALL_DROP_MAX": RECALL_DROP_MAX,
            "N1_RATE_MAX": N1_RATE_MAX, "N3_RATE_MAX": N3_RATE_MAX,
            "LOGO_N1_IMAGES": LOGO_N1_IMAGES, "OCR_TIMEOUT_S": OCR_TIMEOUT_S,
            "P3_PER_NOTATION": P3_PER_NOTATION, "MAX_BUNDLE_WORDS": fc.MAX_BUNDLE_WORDS,
            "ALNUM_WEIGHT": fc.ALNUM_WEIGHT, "FRUIT_GOODS": FRUIT_GOODS, "SMOKE": SMOKE,
            "CHO_GROUPS": CHO_GROUPS, "JUNG_SWAPS": JUNG_SWAPS, "JONG_NASALS": JONG_NASALS,
            "LETTER_SWAPS": LETTER_SWAPS}


def rule_sha256() -> str:
    return canonical_sha256(_settings())


def _inputs() -> dict[str, Path]:
    shared, axes = REPO_ROOT / "shared", ML_ROOT / "src" / "axes"
    return {
        "등록부": fc.DEFAULT_REGISTRY_PATH, "등록부_overrides": fc.DEFAULT_OVERRIDES_PATH,
        "브랜드_표": fc.DEFAULT_BRANDS_PATH, "별칭": shared / "applicant_aliases.json",
        "계수_JSON": rm.DEFAULT_MODEL_PATH, "업종_세트": gm.DEFAULT_PRESETS_PATH,
        "변환표": shared / "goods_map" / "goods_map.json.gz",
        "식별력_통계": shared / "distinctiveness" / "token_stats.json",
        "식별력_3호": shared / "distinctiveness" / "descriptive_terms.json",
        "식별력_제외": shared / "distinctiveness" / "weak_token_overrides.json",
        "메타데이터": METADATA, "학습_특징": FEATURES, "이미지_유형": IMAGE_PARTS,
        "대조군": CONTROL, "색인": ML_ROOT / "data" / "index" / "kipris.faiss",
        "유형_사전": ML_ROOT / "data" / "types.json",
        "판정_모듈": ML_ROOT / "src" / "famous_check.py", "식별력": axes / "distinctiveness.py",
        "호칭": axes / "x1_phonetic.py", "철자": axes / "x2_ortho.py",
        "브랜드표_X1": axes / "korean_brands.py",
        "엔진": REPO_ROOT / "backend" / "src" / "core" / "multi_search.py",
        "OCR": REPO_ROOT / "backend" / "src" / "core" / "ocr.py",
        "런타임": ML_ROOT / "src" / "model" / "risk_model.py",
    }


def _paths(out_dir: Path) -> dict[str, Path]:
    return {"rule": out_dir / f"{STEM}_rule.json", "results": out_dir / f"{STEM}_results.json",
            "report": out_dir / f"{STEM}_report.md"}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _preset_codes(presets, preset_id: str) -> list[str]:
    return sorted({code for good in presets.get(preset_id).goods
                   for code in good.similarity_codes})


def goods_resolver(presets):
    """업종 표시(업종 세트 id | "과일" | None) → (유사군, 보고용 이름)."""
    goods_map = gm.load_goods_map()
    fruit = sorted({code for name, nice in FRUIT_GOODS
                    for code in goods_map.find(name, nice).similarity_codes})

    def resolve(key: str | None) -> tuple[list[str] | None, str]:
        if key is None:
            return None, "없음"
        if key == "과일":
            return fruit, "과일 판매(신선한 과실·그 판매업)"
        return _preset_codes(presets, key), key

    return resolve


# ---- 표본 --------------------------------------------------------------------------------------

# 1단계(커밋 ea1d0ef)의 표본 만들기 그대로 — 약한 표기는 1단계 정의(base_weak), 업종 겹침은 1단계의
# goods_sets 를 써서 같은 표본이 다시 나오게 한다(다시 만든 표본의 sha256 을 1단계 값과 견준다).

def own_words(preset: dict, dist) -> list[tuple[str, str]]:
    """자기 업종 낱말 — (종류, 낱말): 업종 낱말 = 첫 별칭, 상품 낱말 = 사전에 있는 첫 별칭."""
    aliases = [alias for alias in preset["별칭"] if alias.strip()]
    words = [("업종 낱말", aliases[0])]
    in_dictionary = next(
        (alias for alias in aliases
         if len(fc.split_pieces(fc.normalize_text(alias))) == 1
         and fc.text_key(alias) in dist.goods_names), None)
    if in_dictionary and in_dictionary != aliases[0]:
        words.append(("상품 낱말", in_dictionary))
    return words


def unrelated_preset(brand: fc.Brand, preset_list: list[dict], codes_of: dict) -> dict:
    """무관한 업종 세트 — 파일 순서로 자기 세트 + 7번째부터 브랜드 업종과 X4 가 0 인 첫 세트
    (없으면 겹침 최댓값이 가장 작은 세트)."""
    ids = [preset["id"] for preset in preset_list]
    start = (ids.index(brand.preset) + 7) % len(ids)
    best: tuple[float, dict] | None = None
    for offset in range(len(ids)):
        preset = preset_list[(start + offset) % len(ids)]
        if preset["id"] == brand.preset:
            continue
        codes = codes_of[preset["id"]]
        value = max((goods_similarity(codes, goods) for goods in brand.goods_sets), default=0.0)
        if value == 0.0:
            return preset
        if best is None or value < best[0]:
            best = (value, preset)
    return best[1]  # 겹침이 0 인 세트가 없으면 겹침 최댓값이 가장 작은 세트


def spacing_variant(text: str) -> str | None:
    if " " in text:
        return text.replace(" ", "")
    if len(text) < 2:
        return None
    middle = (len(text) + 1) // 2
    return f"{text[:middle]} {text[middle:]}"


def case_variant(text: str) -> str | None:
    if not any("a" <= ch.lower() <= "z" for ch in text):
        return None
    return text.lower() if text == text.upper() else text.upper()


def hangul_variants(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for index, ch in enumerate(text):
        if not _is_syllable(ch):
            continue
        cho, jung, jong = _decompose_syllable(ch)

        def put(c: str, j: str, g: str | None, kind: str) -> None:
            out.append((text[:index] + _compose(c, j, g) + text[index + 1:], kind))

        for a, b in JUNG_SWAPS:
            if jung == a:
                put(cho, b, jong, f"모음 {a}↔{b}")
            elif jung == b:
                put(cho, a, jong, f"모음 {a}↔{b}")
        for group in CHO_GROUPS:
            if cho in group:
                for other in group:
                    if other != cho:
                        put(other, jung, jong, "예사·된·거센소리")
        if jong in JONG_NASALS:
            for other in JONG_NASALS:
                if other != jong:
                    put(cho, jung, other, "받침 ㄴ↔ㅇ↔ㅁ")
        if jong is None:
            put(cho, jung, "ㄹ", "받침 ㄹ 넣기")
        elif jong == "ㄹ":
            put(cho, jung, None, "받침 ㄹ 빼기")
    return out


def latin_variants(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    low = text.lower()
    for index, ch in enumerate(low):
        if not "a" <= ch <= "z":
            continue
        original = text[index]
        following = low[index + 1] if index + 1 < len(low) else ""
        previous = low[index - 1] if index else ""
        if ch != following and ch != previous:
            out.append((text[:index + 1] + original + text[index + 1:], "겹글자 넣기"))
        if ch == following:
            out.append((text[:index] + text[index + 1:], "겹글자 빼기"))
        for a, b in LETTER_SWAPS:
            swap = b if ch == a else (a if ch == b else None)
            if swap:
                swap = swap.upper() if original.isupper() else swap
                out.append((text[:index] + swap + text[index + 1:], f"{a}↔{b}"))
    return out


def p3_variants(brand: str, notation: fc.Notation, taken: set[str]) -> list[dict]:
    """표기 하나의 비슷한 소리 변형 4개(기준용 2·확인용 2) — 전체를 정렬 뒤 seed 로 섞어 앞에서."""
    seen: set[str] = set()
    pool: list[tuple[str, str]] = []
    for variant, kind in sorted(hangul_variants(notation.text) + latin_variants(notation.text)):
        key = fc.text_key(variant)
        if key and key != notation.key and key not in taken and key not in seen:
            seen.add(key)
            pool.append((variant, kind))
    random.Random(f"{SEED}|P3|{brand}|{notation.text}").shuffle(pool)
    out = []
    for index, (variant, kind) in enumerate(pool[:P3_PER_NOTATION]):
        out.append({"이름": variant, "브랜드": brand, "표기": notation.text,
                    "길이": notation.length, "변형": kind,
                    "반": BASE if index < P3_PER_NOTATION // 2 else HOLDOUT})
    return out


def _with_goods(item: dict, variants: list[tuple[str, list[str] | None]]) -> list[dict]:
    return [{**item, "업종_표시": label, "업종": codes} for label, codes in variants]


def target_notation(name: str, brand: fc.Brand) -> fc.Notation:
    """모방 꼴이 겨냥한 표기(재현율을 길이 구간별로 나누는 데만 쓴다) — 같은 문자 종류의 약하지
    않은 표기 중 붙여 쓴 꼴의 글자 수가 가장 가까운 것(같으면 표의 앞쪽), 없으면 약하지 않은 첫
    표기. 유사도를 쓰지 않는다 — 확인용 이름으로는 어떤 점수도 계산하지 않는다."""
    key = fc.text_key(name)
    usable = [n for n in brand.notations if not n.base_weak] or list(brand.notations)
    same = [n for n in usable if n.script == fc.script_label(key)]
    if same:
        return min(same, key=lambda n: abs(len(n.key) - len(key)))
    return usable[0]


def build_samples(registry: fc.Registry, dist, *, preset_list: list[dict], codes_of: dict,
                  control: dict, db_records: list[dict], feature_rows: list[dict],
                  applicant_keys) -> dict:
    presets = {preset["id"]: preset for preset in preset_list}
    taken = {n.key for brand in registry.brands for n in brand.notations}
    taken |= {fc.text_key(name) for _, first, second in P2_PAIRS for name in (first, second)}
    taken |= {fc.text_key(name) for name in N4_TRAPS}
    taken |= {fc.text_key(name) for name, _ in PREVIEW_NAMES if not name.startswith("@")}
    weak_brands = {brand.name for brand in registry.brands
                   if any(n.base_weak for n in brand.notations)}
    p1, p2, p3 = [], [], []
    for brand in registry.brands:
        own = codes_of[brand.preset]
        own_goods = [("없음", None), (f"자기 업종({brand.preset})", own)]
        other = unrelated_preset(brand, preset_list, codes_of)
        other_word = [alias for alias in other["별칭"] if alias.strip()][0]
        for notation in brand.notations:
            text = notation.text
            variants = [("그대로", text), ("대소문자 바꿈", case_variant(text)),
                        ("띄어쓰기 바꿈", spacing_variant(text))]
            for kind, word in own_words(presets[brand.preset], dist):
                variants += [(f"{kind} 띄어서", f"{text} {word}"), (f"{kind} 붙여서", text + word)]
            for kind, name in variants:
                if name:
                    p1 += _with_goods({"이름": name, "브랜드": brand.name, "표기": text,
                                       "약한_표기": notation.base_weak, "변형": kind, "반": None},
                                      own_goods)
            p1 += _with_goods(
                {"이름": f"{text} {other_word}", "브랜드": brand.name, "표기": text,
                 "약한_표기": notation.base_weak, "변형": "무관한 업종 낱말", "반": None},
                [("없음", None), (f"무관한 업종({other['id']})", codes_of[other["id"]])])
            if not notation.base_weak:
                for item in p3_variants(brand.name, notation, taken):
                    taken.add(fc.text_key(item["이름"]))  # 뒤 표기의 변형과 겹치지 않게
                    p3 += _with_goods(item, own_goods)
    for name, first, second in P2_PAIRS:
        brand = registry.brand(name)
        if brand is None:
            raise ValueError(f"P2 의 브랜드가 등록부에 없습니다: {name}")
        own_goods = [("없음", None), (f"자기 업종({brand.preset})", codes_of[brand.preset])]
        for variant, half in ((first, BASE), (second, HOLDOUT)):
            target = target_notation(variant, brand)
            p2 += _with_goods({"이름": variant, "브랜드": name, "표기": target.text,
                               "길이": target.length, "변형": "실제 모방 꼴", "반": half,
                               "약한_표기_브랜드": name in weak_brands}, own_goods)
    # N1 — 등록부 출원인이 아닌 기존 수집 상표의 이름(이름 단위로 절반씩)
    owners = registry.applicant_keys
    by_name: dict[str, list[dict]] = {}
    for record in db_records:
        # 유명 브랜드로 모은 것(283건)과 대표 표장으로 받은 것은 어떤 표본에도 넣지 않는다
        if str(record.get("수집_출처") or "").startswith("유명 브랜드"):
            continue
        if applicant_keys(str(record.get("출원인") or "")) & owners:
            continue
        title = str(record.get("상표한글명") or record.get("상표영문명") or "").strip()
        key = fc.text_key(title)
        if not key:
            continue
        codes = sorted(fc.normalize_codes(record.get("유사군") or ()))
        by_name.setdefault(key, []).append(
            {"이름": title, "업종": codes or None, "업종_표시": "그 상표의 지정상품",
             "출원번호": str(record["출원번호"]), "출원인": record.get("출원인"),
             "이미지": record.get("이미지파일"), "상표구분": record.get("상표구분")})
    names = sorted(by_name)
    random.Random(f"{SEED}|N1").shuffle(names)
    half = len(names) // 2
    n1 = []
    for index, key in enumerate(names):
        seen: set[tuple] = set()
        for item in by_name[key]:
            signature = (item["이름"], tuple(item["업종"] or ()))
            n1.append({**item, "반": BASE if index < half else HOLDOUT,
                       "중복": signature in seen})
            seen.add(signature)
    # N2 — 심결 데이터의 이름(양쪽 표장, 중복 제거, 업종 없음)
    n2, seen_keys = [], set()
    for row in feature_rows:
        if row.get("pair_source") != "trial":
            continue
        for column in ("이름A", "이름B"):
            title = str(row.get(column) or "").strip()
            key = fc.text_key(title)
            if key and key not in seen_keys:
                seen_keys.add(key)
                n2.append({"이름": title, "업종": None, "업종_표시": "없음", "반": None,
                           "심판번호": row.get("심판번호"), "쪽": column})
    n3 = []
    for half_name in (BASE, HOLDOUT):
        for item in control["대조군"]["이름"][half_name]:
            n3 += _with_goods({"이름": item["이름"], "반": half_name},
                              [("없음", None),
                               (f"무작위 업종({item['업종_세트']})", sorted(item["유사군"]))])
    n4 = [{"이름": name, "업종": None, "업종_표시": "없음", "반": None} for name in N4_TRAPS]
    return {"P1": p1, "P2": p2, "P3": p3, "N1": n1, "N2": n2, "N3": n3, "N4": n4,
            "약한_표기_브랜드": sorted(weak_brands)}


def holdout_overlap(samples: dict) -> dict:
    """확인용 이름과 붙여 쓴 꼴이 같은, 계산하는 목록의 이름 — 지시가 계산하라고 한 목록(P1·N2·N4·
    미리 보기)과 기준용이라 그대로 계산하고, 무엇이 겹쳤는지 남긴다."""
    held: dict[str, set[str]] = {}
    for name in ("P2", "P3", "N1", "N3"):
        for item in samples[name]:
            if item.get("반") == HOLDOUT:
                held.setdefault(fc.text_key(item["이름"]), set()).add(f"{name} 확인용")
    computed: dict[str, list[str]] = {name: [item["이름"] for item in samples[name]
                                             if item.get("반") != HOLDOUT]
                                      for name in ("P1", "P2", "P3", "N1", "N2", "N3", "N4")}
    computed["미리 보기"] = [name for name, _ in PREVIEW_NAMES if not name.startswith("@")]
    computed["기대표"] = [name for _, name, goods in EXPECT
                       if not name.startswith("@") and goods != "@N1"]
    out: dict[str, list[dict]] = {}
    for source, names in computed.items():
        seen: set[str] = set()
        for name in names:
            key = fc.text_key(name)
            if key in held and key not in seen:
                seen.add(key)
                out.setdefault(source, []).append({"이름": name, "확인용": sorted(held[key])})
    return out


def base_items(items: list[dict], limit: int | None = None) -> list[dict]:
    """계산해도 되는 항목 — 확인용은 뺀다(2단계에서 처음 본다)."""
    usable = [item for item in items if item.get("반") != HOLDOUT and not item.get("중복")]
    return usable[:limit] if limit else usable


# ---- 일치 판정 실행 ----------------------------------------------------------------------------

class Matcher:
    def __init__(self, registry: fc.Registry, dist, goods_floor: float):
        self.registry, self.dist, self.floor = registry, dist, goods_floor
        self.kinds = {(name, notation.text): notation.kind
                      for brand in registry.brands for notation in brand.notations
                      for name in {brand.name, brand.table_name or brand.name}}
        self.names = {brand.table_name or brand.name: brand.name for brand in registry.brands}
        self._cache: dict[tuple, list[fc.BrandEvidence]] = {}

    def evidence(self, item: dict) -> list[fc.BrandEvidence]:
        if item.get("반") == HOLDOUT:
            raise ValueError("확인용 표본은 이 단계에서 계산하지 않습니다")
        key = (item["이름"], tuple(item.get("업종") or ()))
        if key not in self._cache:
            query = fc.prepare_query(item["이름"], item.get("업종"))
            self._cache[key] = fc.collect_evidence(query, self.registry, self.dist, self.floor)
        return self._cache[key]

    def decide(self, item: dict, thresholds: fc.Thresholds) -> fc.FamousResult:
        return fc.decide(self.evidence(item), thresholds)

    def kind(self, item: dict) -> str:
        """표본 항목이 겨냥한 표기의 종류(새 등록부 기준). P2(실제 모방 꼴)의 '표기'는 1단계에서
        약한 표기를 빼고 고른 것이라(김가내 → GIMGANE) 겨냥한 표기를 다시 정한다."""
        if item.get("변형") == P2_VARIANT:
            return imitated_notation(item["이름"], self.registry.brand(item["브랜드"]),
                                     item["표기"]).kind
        return self.kinds[(item["브랜드"], item["표기"])]

    def own(self, item: dict, thresholds: fc.Thresholds) -> fc.BrandMatch | None:
        """대상 브랜드와의 일치."""
        result = self.decide(item, thresholds)
        target = self.names.get(item["브랜드"], item["브랜드"])
        return next((match for match in result.matches if match.brand == target), None)


P2_VARIANT = "실제 모방 꼴"  # build_samples 가 P2 항목에 적는 변형 이름


def imitated_notation(name: str, brand: fc.Brand, fallback: str) -> fc.Notation:
    """모방 꼴이 겨냥한 표기 — 같은 문자 종류의 표기(종류를 가리지 않고) 가운데 붙여 쓴 꼴의 글자
    수가 가장 가까운 것(같으면 표의 앞쪽), 없으면 표본에 적힌 표기. 유사도는 쓰지 않는다."""
    key = fc.text_key(name)
    same = [n for n in brand.notations if n.script == fc.script_label(key)]
    if same:
        return min(same, key=lambda n: abs(len(n.key) - len(key)))
    return next(n for n in brand.notations if n.text == fallback)


def match_row(match: fc.BrandMatch | None) -> dict | None:
    if match is None:
        return None
    return {"브랜드": match.brand, "수준": match.level, "경로": match.path, "표기": match.notation,
            "종류": match.kind, "점수": match.score, "바닥": match.floor, "겹침": match.overlap,
            "결정_대기": match.pending, "메모": match.note, "기준": match.basis}


def _with(base: fc.Thresholds, **changes) -> fc.Thresholds:
    return fc.Thresholds.from_dict({**base.to_dict(), **changes})


def _only(length: str, value: float | None) -> dict:
    return {**{other: None for other in fc.LENGTHS}, length: value}


def recall(matcher: Matcher, items: list[dict], thresholds: fc.Thresholds) -> float | None:
    """대상 브랜드와 약함 이상으로 일치한 질의의 비율."""
    if not items:
        return None
    hit = sum(1 for item in items if getattr(matcher.own(item, thresholds), "level", None)
              in (fc.LEVEL_STRONG, fc.LEVEL_WEAK))
    return hit / len(items)


def select_thresholds(matcher: Matcher, n1: list[dict], n3: list[dict], p2: list[dict],
                      p3: list[dict]) -> dict:
    """기준 선택 규칙(RULE['기준_선택'])을 적용 — 고른 기준·S 와 근거 표. p2·p3 = 보통 표기의
    P2·P3 기준용(S 선택에 쓴다)."""
    def caught(item: dict, thresholds: fc.Thresholds, strong_only: bool = False) -> bool:
        matches = matcher.decide(item, thresholds).matches
        if strong_only:
            return any(match.level == fc.LEVEL_STRONG for match in matches)
        return bool(matches)

    def count_new(items: list[dict], before: fc.Thresholds, after: fc.Thresholds,
                  strong_only: bool = False) -> list[dict]:
        return [item for item in items if not caught(item, before, strong_only)
                and caught(item, after, strong_only)]

    def within(new1: list, new3: list) -> tuple[float, float, bool]:
        rate1 = len(new1) / len(n1) if n1 else 0.0
        rate3 = len(new3) / len(n3) if n3 else 0.0
        return rate1, rate3, rate1 <= N1_RATE_MAX + 1e-12 and rate3 <= N3_RATE_MAX + 1e-12

    def names(items: list[dict]) -> list[str]:
        return [item["이름"] for item in items[:8]]

    table: dict = {"단위": {"N1_기준용_질의": len(n1), "N3_기준용_질의": len(n3),
                          "P2_보통_표기_질의": len(p2), "P3_보통_표기_질의": len(p3)}}
    base = fc.Thresholds()  # 같음·품음·강한 소리
    # 1) 강한 철자 — 길이 구간별, 새로 생기는 강한 일치가 0건인 가장 낮은 값
    strong_spelling, rows = {}, {}
    for length in fc.LENGTHS:
        rows[length], strong_spelling[length] = [], None
        for value in STRONG_SPELLING_GRID:
            trial = _with(base, strong_spelling=_only(length, value))
            new1, new3 = count_new(n1, base, trial, True), count_new(n3, base, trial, True)
            ok = not new1 and not new3
            rows[length].append({
                "값": value, "N1_새_강한_일치": len(new1), "N3_새_강한_일치": len(new3),
                "조건(0건)": ok, "0.5%·2%_한도로_보면": within(new1, new3)[2],
                "예": names(new1 + new3)})
            if strong_spelling[length] is None and ok:
                strong_spelling[length] = value
    table["강한_철자"] = {"격자": rows, "고른_값": strong_spelling}
    base = _with(base, strong_spelling=strong_spelling)
    # 2) 약한 소리 — 구간마다 그 구간 표기만 켜고, 이미 잡힌 질의를 뺀 새 일치
    weak_sound, rows = {}, {}
    for length in fc.LENGTHS:
        rows[length], weak_sound[length] = [], None
        for value in WEAK_SOUND_GRID:
            trial = _with(base, weak_sound=_only(length, value))
            new1, new3 = count_new(n1, base, trial), count_new(n3, base, trial)
            rate1, rate3, ok = within(new1, new3)
            rows[length].append({
                "값": value, "N1_새_일치": len(new1), "N1_비율": round(rate1, 4),
                "N3_새_일치": len(new3), "N3_비율": round(rate3, 4), "조건": ok,
                "예": names(new1 + new3)})
            if weak_sound[length] is None and ok:
                weak_sound[length] = value
    table["약한_소리"] = {"격자": rows, "고른_값": weak_sound}
    sounded = _with(base, weak_sound=weak_sound)

    def pick_spelling(sound_floor: float | None) -> tuple[dict, dict]:
        """약한 철자 — 그 구간의 약한 소리(고른 값)까지 켠 누적으로 같은 한도."""
        chosen, grid = {}, {}
        for length in fc.LENGTHS:
            grid[length], chosen[length] = [], None
            for value in WEAK_SPELLING_GRID:
                trial = _with(base, weak_sound=_only(length, weak_sound[length]),
                              weak_spelling=_only(length, value), spelling_sound=sound_floor)
                new1, new3 = count_new(n1, base, trial), count_new(n3, base, trial)
                rate1, rate3, ok = within(new1, new3)
                extra = _with(sounded, weak_spelling=_only(length, value),
                              spelling_sound=sound_floor)
                more1, more3 = count_new(n1, sounded, extra), count_new(n3, sounded, extra)
                grid[length].append({
                    "값": value, "N1_새_일치(누적)": len(new1), "N1_비율": round(rate1, 4),
                    "N3_새_일치(누적)": len(new3), "N3_비율": round(rate3, 4), "조건": ok,
                    "N1_철자만_더함(증분)": len(more1), "N3_철자만_더함(증분)": len(more3),
                    "예": names(more1 + more3)})
                if chosen[length] is None and ok:
                    chosen[length] = value
        return chosen, grid

    # 3) 약한 철자 — 먼저 소리 조건 없이
    free_spelling, rows = pick_spelling(None)
    table["약한_철자(조건_없음)"] = {"격자": rows, "고른_값": free_spelling}
    first = _with(sounded, weak_spelling=free_spelling)
    # 4) S — 보통 표기의 P2·P3 기준용 "약함 이상" 재현율이 2%p 넘게 떨어지지 않는 가장 높은 값
    reference = (recall(matcher, p2, first), recall(matcher, p3, first))
    chosen_sound: float | None = None
    rows_sound = []
    for value in SOUND_CONDITION_GRID:
        trial = _with(first, spelling_sound=value)
        now = (recall(matcher, p2, trial), recall(matcher, p3, trial))
        drops = [None if ref is None or got is None else ref - got
                 for ref, got in zip(reference, now)]
        ok = all(drop is None or drop <= RECALL_DROP_MAX + 1e-12 for drop in drops)
        new1, new3 = count_new(n1, base, trial), count_new(n3, base, trial)
        rows_sound.append({
            "S": value, "P2_재현율": None if now[0] is None else round(now[0], 4),
            "P3_재현율": None if now[1] is None else round(now[1], 4),
            "P2_떨어진_폭": None if drops[0] is None else round(drops[0], 4),
            "P3_떨어진_폭": None if drops[1] is None else round(drops[1], 4), "조건": ok,
            "N1_새_일치(전체)": len(new1), "N3_새_일치(전체)": len(new3)})
        if value is not None and ok:
            chosen_sound = value  # 격자가 오름차순이라 마지막으로 통과한 값이 가장 높은 값
    table["S"] = {"격자": rows_sound, "고른_값": chosen_sound}
    # 5) 고른 S 로 약한 철자만 다시
    weak_spelling, rows = pick_spelling(chosen_sound)
    table["약한_철자"] = {"격자": rows, "고른_값": weak_spelling}
    final = _with(sounded, weak_spelling=weak_spelling, spelling_sound=chosen_sound)
    total1, total3 = count_new(n1, base, final), count_new(n3, base, final)
    table["고른_기준에서_새로_더한_일치(전체)"] = {
        "N1": len(total1), "N1_비율": round(len(total1) / len(n1), 4) if n1 else None,
        "N3": len(total3), "N3_비율": round(len(total3) / len(n3), 4) if n3 else None,
        "N1_이름": [item["이름"] for item in total1], "N3_이름": [item["이름"] for item in total3]}
    table["고른_기준"] = final.to_dict()
    return table


def recall_table(matcher: Matcher, items: list[dict], thresholds: fc.Thresholds) -> dict:
    """대상 브랜드와의 일치 — 강함·약함 이상 비율(길이 구간·변형 종류·업종별)과 놓친 목록."""
    rows = []
    for item in items:
        result = matcher.decide(item, thresholds)
        own = next((m for m in result.matches if m.brand == item["브랜드"]), None)
        rows.append({**{k: item[k] for k in ("이름", "브랜드", "표기", "변형", "업종_표시")},
                     "길이": item.get("길이"), "종류": matcher.kind(item),
                     "대상_일치": match_row(own),
                     "다른_브랜드": [m.brand for m in result.matches if m.brand != item["브랜드"]],
                     "바닥": result.floor})

    def rates(group: list[dict]) -> dict:
        strong = sum(1 for r in group if (r["대상_일치"] or {}).get("수준") == fc.LEVEL_STRONG)
        weak = sum(1 for r in group if (r["대상_일치"] or {}).get("수준") == fc.LEVEL_WEAK)
        notice = sum(1 for r in group if (r["대상_일치"] or {}).get("수준") == fc.LEVEL_NOTICE)
        return {"n": len(group), "강함": strong, "약함": weak, "안내": notice,
                "놓침": len(group) - strong - weak - notice,
                "약함_이상_비율": round((strong + weak) / len(group), 4) if group else None}

    def by(field: str) -> dict:
        keys = sorted({str(r[field]) for r in rows})
        return {key: rates([r for r in rows if str(r[field]) == key]) for key in keys}

    paths = Counter((r["대상_일치"] or {}).get("경로") or "놓침" for r in rows)
    return {"전체": rates(rows), "길이별": by("길이"), "변형별": by("변형"),
            "경로": dict(paths),
            "놓친_것": [r for r in rows if r["대상_일치"] is None
                      or r["대상_일치"]["수준"] == fc.LEVEL_NOTICE], "행": rows}


def recall_by_kind(matcher: Matcher, items: list[dict], thresholds: fc.Thresholds) -> dict:
    """표기 종류별 재현율 표 — 보통 표기와 약한 표기·머리글자 표기의 변형을 따로."""
    return {kind: recall_table(matcher, [item for item in items if matcher.kind(item) == kind],
                               thresholds) for kind in (fc.KIND_NORMAL, fc.KIND_WEAK,
                                                        fc.KIND_INITIAL)}


def match_list(matcher: Matcher, items: list[dict], thresholds: fc.Thresholds) -> dict:
    """일치 목록 — 질의마다 가장 강한 일치(경로·출원인)와 수준별 수."""
    rows = []
    levels: Counter = Counter()
    for item in items:
        result = matcher.decide(item, thresholds)
        if not result.matches:
            continue
        levels[result.strongest.level] += 1
        rows.append({"이름": item["이름"], "업종": item.get("업종_표시"),
                     "출원인": item.get("출원인"), "출원번호": item.get("출원번호"),
                     "심판번호": item.get("심판번호"), "일치": match_row(result.strongest),
                     "품음_기타만": all(match.pending for match in result.matches),
                     "그_밖": [match_row(m) for m in result.matches[1:4]],
                     "바닥": result.floor})
    return {"질의": len(items), "일치한_질의": len(rows), "수준": dict(levels),
            "경로": dict(Counter(r["일치"]["경로"] for r in rows)), "목록": rows}


P1_ALLOWED = "약한 표기의 업종 다름"


def p1_table(matcher: Matcher, items: list[dict], thresholds: fc.Thresholds) -> dict:
    """P1 — 강함이 아닌 것을 사유별로. 목표는 약한 표기의 "업종 다름"(무관한 업종의 질의에서 그
    표기가 그 업종에서도 식별력 없는 말이라 안내만) 말고는 없는 것."""
    strong, allowed = 0, []
    others: dict[str, list[dict]] = {}
    for item in items:
        own = matcher.own(item, thresholds)
        if own is not None and own.level == fc.LEVEL_STRONG:
            strong += 1
            continue
        kind = matcher.kind(item)
        foreign = item["업종_표시"].startswith("무관한 업종(")
        row = {"이름": item["이름"], "브랜드": item["브랜드"], "표기": item["표기"],
               "종류": kind, "변형": item["변형"], "업종": item["업종_표시"],
               "대상_일치": match_row(own)}
        if (kind == fc.KIND_WEAK and foreign and own is not None
                and own.level == fc.LEVEL_NOTICE and own.note.startswith("약한 표기 — 업종이")):
            allowed.append(row)
            continue
        goods = "업종 없음" if item["업종"] is None else ("무관한 업종" if foreign else "자기 업종")
        result = "일치 없음" if own is None else f"{own.level}({own.path}; {own.note})"
        others.setdefault(f"{kind} · {item['변형']} · {goods} → {result}", []).append(row)
    return {"n": len(items), "강함": strong, P1_ALLOWED: len(allowed),
            "그_밖": sum(len(rows) for rows in others.values()),
            "그_밖_사유별": {reason: {"수": len(rows), "이름": [r["이름"] for r in rows]}
                         for reason, rows in sorted(others.items(), key=lambda kv: -len(kv[1]))},
            "허용_목록": allowed}


def expectation(matcher: Matcher, thresholds: fc.Thresholds, resolve, control: dict,
                samples: dict, limit: int | None = None) -> dict:
    """기대표 — 입력마다 가장 강한 일치의 수준이 기대와 같은지. resolve = goods_resolver."""
    by_name: dict[str, list[dict]] = {}
    for item in base_items(samples["N1"]):
        by_name.setdefault(item["이름"], []).append(item)
    base_names = control["대조군"]["이름"][BASE]
    passes = {
        E_STRONG: lambda level: level == fc.LEVEL_STRONG,
        E_WEAK_PLUS: lambda level: level in (fc.LEVEL_STRONG, fc.LEVEL_WEAK),
        E_WEAK: lambda level: level in (fc.LEVEL_STRONG, fc.LEVEL_WEAK),
        E_NOTICE: lambda level: level == fc.LEVEL_NOTICE,
        E_NONE: lambda level: level is None,
        E_WISH_WEAK: lambda level: level in (None, fc.LEVEL_WEAK),
        E_WISH_NONE: lambda level: level is None,
    }
    rows = []
    for expected, name, goods_key in EXPECT[:limit] if limit else EXPECT:
        if goods_key == "@N1":
            queries = [(item["이름"], item["업종"], "그 상표의 지정상품(N1 기준용)")
                       for item in by_name.get(name, [])]
        elif goods_key == "@대조군":
            item = base_names[int(name[-1]) - 1]
            queries = [(item["이름"], sorted(item["유사군"]), f"{item['업종_세트']}(대조군 배정)")]
        else:
            codes, label = resolve(goods_key)
            queries = [(name, codes, label)]
        if not queries:
            rows.append({"기대": expected, "입력": name, "업종": goods_key, "결과": "표본에 없음",
                         "맞음": None})
        for query_name, codes, label in queries:
            result = matcher.decide({"이름": query_name, "업종": codes, "반": None}, thresholds)
            strongest = result.strongest
            level = strongest.level if strongest else None
            rows.append({"기대": expected, "입력": query_name, "업종": label,
                         "결과": level or "없음", "일치": match_row(strongest),
                         "바닥": result.floor, "맞음": passes[expected](level),
                         "확인용": query_name in PREVIEW_HOLDOUT_SEEN})
    summary = {}
    for label in (E_STRONG, E_WEAK_PLUS, E_WEAK, E_NOTICE, E_NONE, E_WISH_WEAK, E_WISH_NONE):
        group = [row for row in rows if row["기대"] == label]
        summary[label] = {"n": len(group), "맞음": sum(1 for row in group if row["맞음"]),
                          "다름": [f"{row['입력']} + {row['업종']} → {row['결과']}"
                                 for row in group if not row["맞음"]]}
    stronger = [row["입력"] for row in rows if row["기대"] == E_WEAK_PLUS
                and row["결과"] == fc.LEVEL_STRONG]
    return {"요약": summary, "약함_이상_중_강함": stronger, "행": rows}


def targets(results: dict) -> dict:
    """목표(TARGETS)별 결과."""
    def level_count(name: str, level: str) -> int:
        return int(results[name]["수준"].get(level, 0))

    p2 = results["P2"][fc.KIND_NORMAL]["전체"]
    p3 = results["P3"][fc.KIND_NORMAL]["전체"]
    n3 = level_count("N3", fc.LEVEL_STRONG) + level_count("N3", fc.LEVEL_WEAK)
    rows = {
        "N1 기준용 강함 0건": (level_count("N1", fc.LEVEL_STRONG), TARGETS["N1_강함"]),
        "N1 기준용 약함 2건 이하": (level_count("N1", fc.LEVEL_WEAK), TARGETS["N1_약함_최대"]),
        "N2 강함 0건": (level_count("N2", fc.LEVEL_STRONG), TARGETS["N2_강함"]),
        "N3 기준용 0건": (n3, TARGETS["N3_일치"]),
    }
    out = {name: {"값": value, "한도": limit, "통과": value <= limit}
           for name, (value, limit) in rows.items()}
    out["보통 표기의 P2 기준용 약함 이상 100%"] = {
        "값": p2["약함_이상_비율"], "n": p2["n"],
        "통과": p2["n"] > 0 and p2["약함_이상_비율"] >= TARGETS["P2_보통_약함_이상_최소"]}
    out["보통 표기의 P3 기준용 약함 이상 95% 이상"] = {
        "값": p3["약함_이상_비율"], "n": p3["n"],
        "통과": p3["n"] > 0 and p3["약함_이상_비율"] >= TARGETS["P3_보통_약함_이상_최소"]}
    out["P1 강함이 아닌 것은 약한 표기의 업종 다름뿐"] = {
        "값": results["P1"]["그_밖"], "허용": results["P1"][P1_ALLOWED],
        "통과": results["P1"]["그_밖"] == 0}
    return out


# ---- 엔진을 쓰는 측정(이미지 속 글자·로고·미리 보기) ---------------------------------------------

def load_context():
    from scripts import nameless_shared_threshold as ns

    # 유명 상표 확인을 켜기 전의 서비스 모델(v1.4.6) — 이 측정은 "바닥을 얹기 전"의 등급과 이미지만
    # 판단을 잰다. 서비스 기본 모델(v1.4.7 부터)은 계수·기준이 같고 전체 등급에 바닥만 더한다
    context = ns._context(rm.V146_MODEL_PATH)  # noqa: SLF001
    context["ns"] = ns
    return context


def image_types() -> dict[str, str]:
    with IMAGE_PARTS.open(encoding="utf-8") as handle:
        return {row["경로"]: row["자동유형"] for row in csv.DictReader(handle)}


class Logo(fr.LogoIndex):
    """로고 — 질의 이미지와 브랜드의 대표 이미지(역할 "대표 로고(현재)"·"과거 로고") 사이의 엔진
    '이미지만' 판단 등급이 위험이면 강함. 약함(검토 권장)은 쓰지 않는다. 사람이 대표 로고를 고르기
    전에는 견줄 표장이 없다(2-1 측정은 그때의 역할 — 이름·도형 — 로 쟀다). 판정(is_risk·strong)은
    서비스와 같은 코드(src.famous_runtime.LogoIndex)이고, 여기는 측정용 준비(대표 로고의 구분을 OCR
    로 구하기·임베딩·사진 판정)만 더한다."""

    def __init__(self, context: dict, registry: fc.Registry):
        import numpy as np

        self.np = np
        self.ms, self.engine = context["ms"], context["engine"]
        self.model = self.ms.state.model
        self.direct = context["direct"]
        marks, _ = fr.LogoIndex.entries(registry, self.ms.state.by_appno)
        # 구분(kinds)·사진 판정(photos)은 확정 단계의 로고 규칙(fc.logo_match)에 쓰는 것 — prepare()
        # 가 채운다(그 전에는 규칙 없이 이미지만 판단의 위험만 본다)
        super().__init__(marks, self.ms.state.embeddings[[pos for _, _, pos in marks]],
                         self._grade_level)
        self.texts: list[str | None] = []

    def prepare(self) -> None:
        """대표 로고마다 글자 위주·결합·도형 위주(엔진의 OCR 자동 유형)와 사진 판정을 구해 둔다 —
        strong() 이 로고 규칙(둘 다 글자 위주면 유사도 0.98 이상, 사진은 보지 않음)을 쓰게."""
        kinds, photos, texts = [], [], []
        for index, (_, mark, _) in enumerate(self.marks):
            image = self.direct((IMAGES_DIR / mark.image).read_bytes())
            seen = read_text(image) if image is not None else {"글자": None, "유형": "유형 모름"}
            kinds.append(seen["유형"])
            texts.append(seen["글자"])
            photos.append(bool(self.photo(self.matrix[index])))
        self.kinds, self.photos, self.texts = kinds, photos, texts

    def _grade_level(self, x2: float, level: str) -> str:
        """엔진의 이미지만 판단 등급(유형 level — 측정은 자동 유형의 이름 없는 질의처럼 도형)."""
        ms = self.ms
        features = ms._image_only_features(x2, level)  # noqa: SLF001
        return ms._judge(features, self.model, level).result.grade  # noqa: SLF001

    def _grade(self, x2: float) -> str:
        return self._grade_level(x2, fr.LOGO_LEVEL)

    def embed(self, image):
        return self.np.asarray(self.engine.encode_image(image),
                               dtype=self.np.float32).reshape(-1)

    def photo(self, embedding) -> bool:
        return bool(self.ms.is_photo_query(embedding))


def read_text(image) -> dict:
    """엔진이 이름 없는 이미지 질의에 주는 OCR 제안 상표명(ocr.detect 의 text)과 걸린 시간."""
    from backend.src.core import ocr

    detection = ocr.detect(image, timeout=OCR_TIMEOUT_S)
    if detection is None:
        return {"글자": None, "ms": None, "유형": "유형 모름"}
    return {"글자": detection.text or None, "ms": round(float(detection.elapsed_ms), 1),
            "유형": fr.kind_name(detection.kind)}


def logo_n1_marks(samples: dict) -> list[dict]:
    """N1 기준용 상표(이미지 파일 있음) 가운데 300(seed 0) — 1단계 로고 음성과 같은 표본. 확인용
    절반은 이미지도 건드리지 않는다."""
    pool = sorted({item["출원번호"]: item for item in samples["N1"]
                   if item.get("반") == BASE and item.get("이미지")
                   and (IMAGES_DIR / item["이미지"]).is_file()}.values(),
                  key=lambda item: item["출원번호"])
    return random.Random(f"{SEED}|로고|N1").sample(pool, min(LOGO_N1_IMAGES, len(pool)))


def image_measure(context: dict, registry: fc.Registry, matcher: Matcher,
                  thresholds: fc.Thresholds, samples: dict, control: dict,
                  cut: dict | None) -> dict:
    """이미지 속 글자 경로(OCR 제안 상표명 → 같음·품음만)와 로고 강함."""
    logo = Logo(context, registry)
    kinds = image_types()
    queries = {query.key: query for query in context["A"]}

    def by_text(text: str | None, codes=None) -> fc.FamousResult | None:
        if not text:
            return None
        return fc.check_famous(None, codes, registry, thresholds, dist=matcher.dist,
                               goods_floor=matcher.floor, ocr_text=text)

    def strong_brands(result: fc.FamousResult | None) -> list[str]:
        return [] if result is None else [
            match.brand for match in result.matches if match.level == fc.LEVEL_STRONG]

    # 1) 역할 "이름" 표장 이미지 전부 — 제안 상표명이 나오는가, 그 글자로 자기 브랜드와 강함인가
    name_marks = [(brand.name, mark) for brand in registry.brands for mark in brand.marks
                  if mark.auto_role == fc.ROLE_NAME and mark.image_exists]
    if cut:
        name_marks = name_marks[:cut["이름_표장"]]
    rows = []
    for brand, mark in name_marks:
        image = logo.direct((IMAGES_DIR / mark.image).read_bytes())
        seen = read_text(image)
        result = by_text(seen["글자"])
        own = None if result is None else next(
            (match for match in result.matches if match.brand == brand), None)
        rows.append({"브랜드": brand, "출원번호": mark.appno, "상표명": mark.title,
                     "글자": seen["글자"], "ms": seen["ms"],
                     "자기_브랜드": own.level if own else None,
                     "자기_경로": own.path if own else None,
                     "다른_브랜드_강함": [name for name in strong_brands(result) if name != brand]})
    with_text = [row for row in rows if row["글자"]]
    own_strong = [row for row in rows if row["자기_브랜드"] == fc.LEVEL_STRONG]
    slow = [row for row in rows if row["ms"] is not None and row["ms"] > OCR_SERVICE_LIMIT_MS]
    per_brand = {}
    for row in rows:
        entry = per_brand.setdefault(row["브랜드"], {"표장": 0, "글자": 0, "자기_강함": 0})
        entry["표장"] += 1
        entry["글자"] += bool(row["글자"])
        entry["자기_강함"] += row["자기_브랜드"] == fc.LEVEL_STRONG
    out: dict = {"이름_표장": {
        "이미지": len(rows), "제안_상표명_있음": len(with_text),
        "제안_비율": round(len(with_text) / len(rows), 4) if rows else None,
        "자기_브랜드와_강함": len(own_strong),
        "강함_비율(전체)": round(len(own_strong) / len(rows), 4) if rows else None,
        "강함_비율(글자_있는_것)": (round(len(own_strong) / len(with_text), 4)
                             if with_text else None),
        "자기_브랜드_수준": dict(Counter(row["자기_브랜드"] or "일치 없음" for row in with_text)),
        "다른_브랜드와_강함": [row for row in rows if row["다른_브랜드_강함"]],
        "서비스_상한(2초)_넘김": len(slow), "브랜드별": per_brand,
        "글자는_있는데_강함_아님": [row for row in with_text
                             if row["자기_브랜드"] != fc.LEVEL_STRONG], "행": rows}}

    # 2) 음성 — 대조군의 덜 닮은 이미지, N1 기준용 이미지(사진 판정 제외), 표본 A(로고만)
    def negatives(entries: list[dict], *, text: bool) -> dict:
        measured, photos, text_rows, logo_rows = 0, 0, [], []
        texts = slow_count = 0
        for entry in entries:
            image = logo.direct(entry["경로"].read_bytes())
            if image is None:
                continue
            embedding = logo.embed(image)
            if logo.photo(embedding):
                photos += 1
                continue
            measured += 1
            for brand, hit in logo.strong(embedding).items():
                logo_rows.append({"질의": entry["표시"], "질의_이미지": str(entry["경로"]),
                                  "유형": entry.get("유형"), "브랜드": brand, **hit})
            if not text:
                continue
            seen = read_text(image)
            texts += bool(seen["글자"])
            slow_count += seen["ms"] is not None and seen["ms"] > OCR_SERVICE_LIMIT_MS
            free = strong_brands(by_text(seen["글자"]))
            with_goods = strong_brands(by_text(seen["글자"], entry.get("업종")))
            if free or with_goods:
                text_rows.append({"질의": entry["표시"], "글자": seen["글자"],
                                  "강함(업종 없음)": free, "강함(그 상표의 지정상품)": with_goods})
        result = {"이미지": len(entries), "사진으로_판정": photos, "잰_이미지": measured,
                  "로고_강함": len({row["질의"] for row in logo_rows}), "로고_강함_목록": logo_rows}
        if text:
            free_count = sum(1 for row in text_rows if row["강함(업종 없음)"])
            goods_count = sum(1 for row in text_rows if row["강함(그 상표의 지정상품)"])
            result.update({
                "제안_상표명_있음": texts, "서비스_상한(2초)_넘김": slow_count,
                "글자로_강함(업종 없음)": free_count,
                "글자로_강함_비율": round(free_count / measured, 4) if measured else None,
                "글자로_강함(그 상표의 지정상품)": goods_count, "글자로_강함_목록": text_rows})
        return result

    def trial_kind(path: Path) -> str:
        relative = path.resolve().relative_to(TRIALS.resolve()).as_posix()
        return KIND_NAMES.get(kinds.get(relative, ""), "유형 모름")

    keep = cut["음성_이미지"] if cut else None
    control_keys = control["대조군"]["이미지"][BASE] + control["대조군"]["이미지"][HOLDOUT]
    out["대조군_덜_닮은_이미지"] = negatives(
        [{"표시": key, "경로": queries[key].path, "유형": trial_kind(queries[key].path)}
         for key in control_keys[:keep]], text=True)
    out["N1_기준용_상표_이미지"] = negatives(
        [{"표시": f"{item['출원번호']} {item['이름']} ({item.get('출원인')})",
          "경로": IMAGES_DIR / item["이미지"], "업종": item["업종"]}
         for item in logo_n1_marks(samples)[:keep]], text=True)
    out["표본A_질의_이미지(로고만)"] = negatives(
        [{"표시": f"{query.key} {query.name}", "경로": query.path,
          "유형": trial_kind(query.path)} for query in context["A"][:keep]], text=False)
    return out


def logo_review(context: dict, registry: fc.Registry, samples: dict, control: dict,
                applicant_keys) -> dict:
    """대표 로고(대표 로고(현재)·과거 로고) 점검 — 새 기준 없이 엔진의 '이미지만' 판단이 위험이면
    강함. ① 대표 로고마다 글자 위주·결합·도형 위주(엔진이 이름 없는 이미지 질의에 쓰는 OCR 자동
    유형) ② 서로 다른 브랜드의 대표 로고끼리 강함인 쌍 ③ 덜 닮은 이미지 대조군·표본 A 질의
    이미지·N1 기준용 이미지가 어느 브랜드의 대표 로고와든 강함인 수와 목록. 확인용은 건드리지
    않는다."""
    logo = Logo(context, registry)
    rows = []
    for brand, mark, _ in logo.marks:
        image = logo.direct((IMAGES_DIR / mark.image).read_bytes())
        seen = read_text(image) if image is not None else {"글자": None, "유형": "유형 모름"}
        rows.append({"브랜드": brand, "출원번호": mark.appno, "상표명": mark.title,
                     "역할": mark.role, "상표구분": mark.kind, "출처": mark.source,
                     "구분": seen["유형"], "읽은_글자": seen["글자"],
                     "사진_판정": bool(logo.photo(logo.matrix[len(rows)]))})
    per_brand: dict[str, dict] = {}
    for row in rows:
        entry = per_brand.setdefault(row["브랜드"], {"대표 로고": 0})
        entry["대표 로고"] += 1
        entry[row["구분"]] = entry.get(row["구분"], 0) + 1
    pairs = []
    if len(logo.marks) > 1:
        scores = logo.matrix @ logo.matrix.T
        for i, (brand_a, mark_a, _) in enumerate(logo.marks):
            for j in range(i + 1, len(logo.marks)):
                brand_b, mark_b, _ = logo.marks[j]
                value = round(min(1.0, max(0.0, float(scores[i, j]))), 4)
                if brand_a != brand_b and logo._grade(value) == fc.GRADE_RISK:  # noqa: SLF001
                    pairs.append({"유사도": value, "가": f"{brand_a} {mark_a.appno} "
                                  f"{mark_a.title or '(상표명 없음)'}",
                                  "나": f"{brand_b} {mark_b.appno} "
                                  f"{mark_b.title or '(상표명 없음)'}",
                                  "구분": [rows[i]["구분"], rows[j]["구분"]]})
    pairs.sort(key=lambda pair: -pair["유사도"])
    own_logos = {mark.appno for _, mark, _ in logo.marks}
    owners = registry.applicant_keys

    def negatives(entries: list[dict]) -> dict:
        measured = photos = 0
        hits = []
        for entry in entries:
            image = logo.direct(entry["경로"].read_bytes())
            if image is None:
                continue
            embedding = logo.embed(image)
            if logo.photo(embedding):
                photos += 1
                continue
            measured += 1
            for brand, hit in logo.strong(embedding, exclude=entry.get("출원번호")).items():
                hits.append({"질의": entry["표시"], "브랜드": brand, **hit,
                             "등록부_출원인의_표장": bool(entry.get("등록부_출원인"))})
        return {"이미지": len(entries), "사진으로_판정": photos, "잰_이미지": measured,
                "강함인_이미지": len({hit["질의"] for hit in hits}),
                "그중_등록부_출원인의_표장": len({hit["질의"] for hit in hits
                                          if hit["등록부_출원인의_표장"]}),
                "목록": sorted(hits, key=lambda hit: -hit["유사도"])}

    queries = {query.key: query for query in context["A"]}
    control_keys = control["대조군"]["이미지"][BASE] + control["대조군"]["이미지"][HOLDOUT]
    n1 = [item for item in logo_n1_marks(samples) if item["출원번호"] not in own_logos]
    return {
        "대표_로고": len(rows),
        "역할": dict(Counter(row["역할"] for row in rows)),
        "구분": dict(Counter(row["구분"] for row in rows)),
        "사진_판정": [f"{row['브랜드']} {row['출원번호']}" for row in rows if row["사진_판정"]],
        "브랜드별": per_brand, "행": rows,
        "다른_브랜드의_대표_로고끼리_강함": {"쌍": len(pairs), "목록": pairs},
        "대조군_덜_닮은_이미지": negatives(
            [{"표시": key, "경로": queries[key].path} for key in control_keys]),
        "표본A_질의_이미지": negatives(
            [{"표시": f"{query.key} {query.name}", "경로": query.path}
             for query in context["A"]]),
        "N1_기준용_상표_이미지": negatives(
            [{"표시": f"{item['출원번호']} {item['이름']} ({item.get('출원인')})",
              "경로": IMAGES_DIR / item["이미지"], "출원번호": item["출원번호"],
              "등록부_출원인": bool(applicant_keys(str(item.get("출원인") or "")) & owners)}
             for item in n1]),
    }


def logo_review_text(results: dict) -> str:
    lines = [f"대표 로고 {results['대표_로고']}건 — 역할 {results['역할']} · 구분 {results['구분']}"
             f" · 사진으로 판정 {len(results['사진_판정'])}"]
    pairs = results["다른_브랜드의_대표_로고끼리_강함"]
    lines.append(f"서로 다른 브랜드의 대표 로고끼리 강함: {pairs['쌍']}쌍")
    lines.extend(f"  · {pair['유사도']} {pair['가']} ↔ {pair['나']} ({'/'.join(pair['구분'])})"
                 for pair in pairs["목록"])
    for key in ("대조군_덜_닮은_이미지", "표본A_질의_이미지", "N1_기준용_상표_이미지"):
        group = results[key]
        lines.append(f"{key.replace('_', ' ')}: {group['잰_이미지']}장(사진 판정 "
                     f"{group['사진으로_판정']} 제외) 중 강함 {group['강함인_이미지']}장"
                     f"(등록부 출원인의 표장 {group['그중_등록부_출원인의_표장']})")
        lines.extend(f"  · {hit['유사도']} {hit['질의']} ↔ {hit['브랜드']} {hit['표장']} "
                     f"{hit['표장_이름'] or '(상표명 없음)'}"
                     + (" [같은 출원인]" if hit["등록부_출원인의_표장"] else "")
                     for hit in group["목록"])
    return "\n".join(lines)


def command_logos(args) -> int:
    """대표 로고 점검(실제 엔진, 약 3분) — 등록부에서 대표 로고를 고른 뒤."""
    from scripts import famous_registry as builder

    context = load_context()
    control = json.loads(CONTROL.read_text(encoding="utf-8"))
    results = logo_review(context, fc.load_registry(), frozen_samples(), control,
                          builder.applicant_key_function())
    results["때"] = _now()
    out = (args.out_dir if args.out_dir != TRIALS else TRIALS) / "famous_check_logos.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(logo_review_text(results))
    print(f"→ {out}")
    return 0


def grade_max(*grades: str | None) -> str | None:
    usable = [grade for grade in grades if grade]
    return max(usable, key=fc.GRADES.index) if usable else None


def preview(context: dict, registry: fc.Registry, matcher: Matcher, thresholds: fc.Thresholds,
            presets, control: dict, limit: int | None) -> list[dict]:
    from scripts import named_shared_threshold as second

    ms, engine = context["ms"], context["engine"]
    resolve = goods_resolver(presets)
    scenarios = {key: (title, inputs)
                 for key, title, inputs in second.scenario_inputs(ms, context["service"])}
    rows = []

    def notice_of(result: fc.FamousResult) -> str:
        match = result.strongest
        if match is None:
            return "없음"
        text = f"유명 상표 일치({match.level})" if match.level != fc.LEVEL_NOTICE else match.level
        if match.pending:
            text += " · 품음-기타(결정 대기)"
        if match.basis == fc.BASIS_OCR:
            text += " · 이미지 속 글자 기준"
        return text

    def run(label: str, name: str | None, codes: list[str] | None, goods_label: str,
            note: str = "") -> None:
        data = engine.multi_search(image=None, name=name, goods_codes=codes,
                                   top_k=5).to_dict()
        overall = data["overall"]
        result = fc.check_famous(name, codes, registry, thresholds, dist=matcher.dist,
                                 goods_floor=matcher.floor)
        rows.append({"입력": label, "업종": goods_label, "지금_등급": overall["grade"],
                     "지금_위험도": overall["prob"],
                     "지금_1위": (data["candidates"][0]["title"] if data["candidates"] else None),
                     "일치": match_row(result.strongest),
                     "그_밖의_일치": [match_row(m) for m in result.matches[1:3]],
                     "바닥": result.floor,
                     "바닥_적용_등급": grade_max(overall["grade"], result.floor),
                     "안내": notice_of(result), "메모": note})

    entries = PREVIEW_NAMES[:limit] if limit else PREVIEW_NAMES
    base_names = control["대조군"]["이름"][BASE]
    for name, preset_id in entries:
        if name.startswith("@대조군"):
            item = base_names[int(name[-1]) - 1]
            run(item["이름"], item["이름"], sorted(item["유사군"]),
                f"{item['업종_세트']}(대조군 배정)", note="지어낸 이름 대조군 기준용")
        elif name.startswith("@"):
            title, inputs = scenarios[name[1:]]
            run(inputs["name"], inputs["name"], inputs.get("goods_codes"), title,
                note=f"시연 입력 그대로({name[1:]})")
        else:
            codes, label = resolve(preset_id)
            note = "P2 확인용 — 지시의 목록이라 계산" if name in PREVIEW_HOLDOUT_SEEN else ""
            if name in ("삼성", "애플"):
                note = "등록부에 없음 — 한계 확인용"
            run(name, name, codes, label, note=note)
    return rows


def preview_images(context: dict, registry: fc.Registry, matcher: Matcher,
                   thresholds: fc.Thresholds, presets, control: dict,
                   limit: int | None) -> list[dict]:
    from scripts import named_shared_threshold as second

    engine = context["engine"]
    logo = Logo(context, registry)
    starbucks = (REPO_ROOT / second.SCENARIO_IMAGES["starbucks"]).read_bytes()
    instagram = next(mark for mark in sorted(registry.brand("인스타그램").marks,
                                             key=lambda m: m.appno)
                     if mark.auto_role == fc.ROLE_FIGURE and mark.image_exists)
    queries = {query.key: query for query in context["A"]}
    control_key = control["대조군"]["이미지"][BASE][0]
    entries = [
        ("STARBUCKS 로고(이름 없음)", starbucks, None, "clothing"),
        ("STARBUCKS 로고 + 몬테로사", starbucks, "몬테로사", "cafe"),
        (f"인스타그램 로고 도형({instagram.appno}, 이름 없음)",
         (IMAGES_DIR / instagram.image).read_bytes(), None, None),
        (f"대조군의 덜 닮은 이미지({control_key})", queries[control_key].path.read_bytes(),
         None, "cafe"),
    ]
    rows = []
    for label, raw, name, preset_id in entries[:limit] if limit else entries:
        image = context["service"](raw) or context["direct"](raw)
        codes = _preset_codes(presets, preset_id) if preset_id else None
        data = engine.multi_search(image=image, name=name, goods_codes=codes,
                                   top_k=5).to_dict()
        overall = data["overall"]
        suggested = overall["query_type"].get("suggested_name")
        result = fc.check_famous(name, codes, registry, thresholds, dist=matcher.dist,
                                 goods_floor=matcher.floor, ocr_text=suggested)
        embedding = logo.embed(image)
        photo = logo.photo(embedding)
        hits = {} if photo else logo.strong(embedding)
        best = max(hits.items(), key=lambda kv: kv[1]["유사도"]) if hits else None
        logo_floor = fc.GRADE_RISK if best else None
        rows.append({
            "입력": label, "업종": preset_id or "없음", "지금_등급": overall["grade"],
            "지금_위험도": overall["prob"],
            "지금_1위": data["candidates"][0]["title"] if data["candidates"] else None,
            "OCR_제안": suggested, "글자_일치": match_row(result.strongest),
            "글자_기준": result.basis, "글자_바닥": result.floor, "사진": photo,
            "로고_강함": ({"브랜드": best[0], **best[1]} if best else None),
            "로고_바닥(같은 대응을 쓴다면)": logo_floor,
            "바닥_적용_등급": grade_max(overall["grade"], result.floor, logo_floor)})
    return rows


# ---- 확인용 시트 -------------------------------------------------------------------------------

def _thumb(path: Path, size: int = 120) -> str | None:
    from PIL import Image

    try:
        with Image.open(path) as source:
            image = source.convert("RGBA")
            image.thumbnail((size, size))
            canvas = Image.new("RGB", image.size, "white")
            canvas.paste(image, mask=image.split()[3])
            buffer = io.BytesIO()
            canvas.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:
        return None


def review_html(registry: fc.Registry, out_path: Path, limit: int | None = None) -> dict:
    """사람이 볼 시트 — 브랜드마다 표기(종류)·출원인·업종·보호 범위·근거, 표장 썸네일을 역할별로.
    고르는 일은 고르기 도구(curate.html — famous_curate.py)에서 한다."""
    order = list(fc.MARK_ROLES)
    parts = ["""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>유명 상표 등록부 확인</title><style>
:root{--bg:#fbfaf7;--ink:#1d1c19;--sub:#5f5b52;--line:#d9d5cb;--mark:#f6e7b4;--warn:#b4541a}
@media (prefers-color-scheme:dark){:root{--bg:#191815;--ink:#ece9e1;--sub:#a8a397;--line:#3a372f;
--mark:#4a3f16;--warn:#e8935a}}
body{background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,sans-serif;margin:0;
padding:24px 16px;max-width:1180px;margin-inline:auto}
h1{font-size:22px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 6px;padding-top:14px;
border-top:1px solid var(--line)}h3{font-size:14px;margin:14px 0 6px}
.sub{color:var(--sub);font-size:13px}.flag{background:var(--mark);padding:1px 6px;border-radius:3px}
.warn{color:var(--warn);font-weight:600}table{border-collapse:collapse;font-size:13px}
td,th{border:1px solid var(--line);padding:3px 8px;text-align:left}
td.n,th.n{white-space:nowrap}.scroll{overflow-x:auto}
.marks{display:flex;flex-wrap:wrap;gap:10px}
figure{margin:0;width:132px;font-size:11.5px;color:var(--sub);overflow-wrap:anywhere}
figure img{display:block;width:120px;height:120px;object-fit:contain;background:#fff;
border:1px solid var(--line)}figure.look img{outline:3px solid var(--warn)}
a{color:inherit}</style></head><body>
<h1>유명 상표 등록부 확인</h1>
<p class="sub">shared/famous_registry.json 의 지금 상태. <span class="warn">주황 테두리</span>는
아직 고르지 않아 기본값 "관련 없음"인 표장(상표명이 없거나 브랜드 표기가 없는 것)입니다. 역할은
고르기 도구(curate.html)에서 고릅니다.
표기 종류: <span class=flag>약한 표기</span>는 그 표기 하나뿐일 때만 일치,
<span class=flag>머리글자 표기</span>는 같음·품음-설명만 인정합니다.</p>"""]
    brands = registry.brands[:limit] if limit else registry.brands
    index = []
    for number, brand in enumerate(brands):
        roles = Counter(mark.auto_role for mark in brand.marks)
        special = ", ".join(f"{n.text}({n.kind})" for n in brand.notations
                            if n.kind != fc.KIND_NORMAL)
        index.append(
            f'<tr><td class=n><a href="#b{number}">{html.escape(brand.name)}</a></td>'
            f"<td>{html.escape(' · '.join(n.text for n in brand.notations))}</td>"
            f"<td class=n>{brand.preset}</td><td class=n>{roles.get(fc.ROLE_NAME, 0)}</td>"
            f"<td class=n>{roles.get(fc.ROLE_FIGURE, 0) or ''}</td>"
            f"<td class=n>{roles.get(fc.ROLE_OTHER, 0) or ''}</td>"
            f"<td>{html.escape(special)}</td></tr>")
    parts.append(
        "<div class=scroll><table><tr><th>브랜드</th><th>표기</th><th class=n>업종 세트</th>"
        "<th class=n>이름</th><th class=n>도형</th><th class=n>다른 이름</th>"
        "<th>약한·머리글자 표기</th></tr>" + "".join(index) + "</table></div>")
    for number, brand in enumerate(brands):
        rows = "".join(
            f"<tr><td>{html.escape(n.text)}</td><td class=n>{n.script}</td>"
            f"<td class=n>{n.length}</td><td class=n>"
            + (f"<span class=flag>{n.kind}</span>" if n.kind != fc.KIND_NORMAL else n.kind)
            + f"</td><td>{html.escape(n.kind_reason or _reasons(n))}</td></tr>"
            for n in brand.notations)
        links = " ".join(f'<a href="{html.escape(url)}">근거</a>' for url in brand.evidence_urls)
        parts.append(
            f'<h2 id="b{number}">{html.escape(brand.name)}</h2><p class=sub>출원인 '
            f"{html.escape(' / '.join(brand.applicants))} · 업종 세트 {brand.preset}"
            f"({html.escape(brand.preset_label or '')}) · 보호 범위 <b>{brand.protection}</b>"
            f" · {links}<br>{html.escape(_strip_urls(brand.evidence))}</p>"
            "<table><tr><th>표기</th><th class=n>문자</th><th class=n>길이</th>"
            f"<th class=n>종류</th><th>근거(유명 예외를 뺀 식별력)</th></tr>{rows}</table>")
        for role in order:
            marks = [mark for mark in brand.marks if mark.role == role]
            if not marks:
                continue
            parts.append(f"<h3>{role} {len(marks)}건</h3><div class=marks>")
            for mark in marks:
                look = role == fc.ROLE_UNRELATED and not mark.picked
                data = _thumb(IMAGES_DIR / mark.image) if mark.image else None
                img = (f'<img alt="" src="data:image/png;base64,{data}">' if data
                       else "<div>(이미지 없음)</div>")
                note = " · ".join(part for part in (mark.kind, mark.source) if part)
                parts.append(
                    f"<figure{' class=look' if look else ''}>{img}{mark.appno}<br>"
                    f"{html.escape(mark.title or '(상표명 없음)')}<br>"
                    f"{html.escape(note)}</figure>")
            parts.append("</div>")
    parts.append("</body></html>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts), encoding="utf-8")
    return {"경로": str(out_path), "브랜드": len(brands),
            "크기_KB": round(out_path.stat().st_size / 1024)}


def _reasons(notation: fc.Notation) -> str:
    return "; ".join(f"{j['token']}: {'·'.join(j['reasons'])}" for j in notation.judgements)


def _strip_urls(text: str) -> str:
    return " ".join(part for part in text.split() if not part.startswith("http"))


# ---- 명령 --------------------------------------------------------------------------------------

def _load_static():
    from scripts import famous_registry as builder

    registry = fc.load_registry()
    dist = dx.load_distinctiveness()
    goods_map = gm.load_goods_map()
    presets = gm.load_business_presets(goods_map)
    preset_list = json.loads(gm.DEFAULT_PRESETS_PATH.read_text(encoding="utf-8"))
    codes_of = {preset["id"]: _preset_codes(presets, preset["id"]) for preset in preset_list}
    control = json.loads(CONTROL.read_text(encoding="utf-8"))
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    with FEATURES.open(encoding="utf-8") as handle:
        feature_rows = list(csv.DictReader(handle))
    samples = build_samples(
        registry, dist, preset_list=preset_list, codes_of=codes_of, control=control,
        db_records=metadata["trademarks"], feature_rows=feature_rows,
        applicant_keys=builder.applicant_key_function())
    return registry, dist, presets, control, samples


def sample_summary(samples: dict) -> dict:
    out = {}
    for name in ("P1", "P2", "P3", "N1", "N2", "N3", "N4"):
        halves = Counter(item.get("반") or "나누지 않음" for item in samples[name]
                         if not item.get("중복"))
        out[name] = dict(halves)
    return out


def kind_summary(registry: fc.Registry) -> dict:
    return {kind: [f"{brand.name}: {notation.text}" for brand in registry.brands
                   for notation in brand.notations if notation.kind == kind]
            for kind in (fc.KIND_WEAK, fc.KIND_INITIAL)} | {
        fc.KIND_NORMAL: sum(1 for brand in registry.brands for notation in brand.notations
                            if notation.kind == fc.KIND_NORMAL)}


def _same_samples(samples: dict) -> bool:
    """표본이 1단계에 고정한 것과 같은가."""
    if canonical_sha256(samples) == STAGE1_SAMPLES_SHA256:
        return True
    print("거절: 다시 만든 표본이 1단계에 고정한 표본과 다릅니다"
          f"({canonical_sha256(samples)[:12]}… ≠ {STAGE1_SAMPLES_SHA256[:12]}…)", file=sys.stderr)
    return False


def command_freeze(args) -> int:
    paths = _paths(args.out_dir)
    if paths["rule"].exists() and not args.force:
        print(f"거절: {paths['rule']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    registry, _, _, _, samples = _load_static()
    if not _same_samples(samples):
        return EXIT_REFUSED
    args.out_dir.mkdir(parents=True, exist_ok=True)
    frozen = {"설정_sha256": rule_sha256(), "스크립트_sha256": file_sha256(Path(__file__)),
              "표본_sha256": canonical_sha256(samples), "표본_수": sample_summary(samples),
              "확인용과_겹치는_이름": holdout_overlap(samples),
              "입력_sha256": {k: file_sha256(p) for k, p in _inputs().items()},
              "등록부": {"브랜드": len(registry.brands),
                       "표장": sum(len(b.marks) for b in registry.brands),
                       "표기_종류": kind_summary(registry)},
              "고정": _now(), "설정": _settings()}
    paths["rule"].write_text(json.dumps(frozen, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    print(f"설정 sha256 {frozen['설정_sha256']} · 스크립트 sha256 {frozen['스크립트_sha256']} · "
          f"표본 sha256 {frozen['표본_sha256']}(1단계와 같음)")
    print(json.dumps(frozen["표본_수"], ensure_ascii=False))
    return 0


def _check_frozen(paths: dict, samples: dict) -> dict | None:
    if not paths["rule"].exists():
        print("거절: 먼저 freeze", file=sys.stderr)
        return None
    frozen = json.loads(paths["rule"].read_text(encoding="utf-8"))
    if frozen["설정_sha256"] != rule_sha256():
        print("거절: 설정이 고정본과 다릅니다", file=sys.stderr)
        return None
    if frozen["표본_sha256"] != canonical_sha256(samples):
        print("거절: 표본이 고정본과 다릅니다", file=sys.stderr)
        return None
    changed = [k for k, p in _inputs().items()
               if file_sha256(p) != frozen["입력_sha256"].get(k)]
    if changed:
        print(f"거절: 입력이 고정 때와 다릅니다 — {changed}", file=sys.stderr)
        return None
    return frozen


def command_run(args) -> int:
    paths = _paths(args.out_dir)
    smoke = bool(args.smoke)
    if smoke and args.out_dir.resolve() == TRIALS.resolve():
        print("거절: 스모크는 --out-dir 로 다른 폴더에", file=sys.stderr)
        return EXIT_REFUSED
    registry, dist, presets, control, samples = _load_static()
    if not _same_samples(samples):
        return EXIT_REFUSED
    frozen = _check_frozen(paths, samples)
    if frozen is None:
        return EXIT_REFUSED
    if paths["results"].exists() and not args.force:
        print(f"거절: {paths['results']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    started, timing = time.perf_counter(), {}

    def tick(name: str, began: float) -> None:
        timing[name] = round(time.perf_counter() - began, 1)
        print(f"  {name} {timing[name]}초", flush=True)

    cut = SMOKE if smoke else {}
    floor = fc.default_goods_floor()
    matcher = Matcher(registry, dist, floor)
    results: dict = {"설정_sha256": frozen["설정_sha256"], "스모크": smoke, "시작": _now(),
                     "스크립트_sha256(고정 때)": frozen["스크립트_sha256"],
                     "스크립트_sha256(잴 때)": file_sha256(Path(__file__)),
                     "기본_모델": rm.MODEL_VERSION, "결합_하한": floor,
                     "표본_sha256": frozen["표본_sha256"], "표본_수": sample_summary(samples),
                     "확인용과_겹치는_이름": holdout_overlap(samples),
                     "표기_종류": kind_summary(registry),
                     "업종_낱말_수": len(fc.industry_words())}
    began = time.perf_counter()
    p1 = base_items(samples["P1"])
    if smoke:
        keep = {brand.name for brand in registry.brands[:cut["P1_브랜드"]]}
        p1 = [item for item in p1 if item["브랜드"] in keep]
    p2 = base_items(samples["P2"], cut.get("P2", 0) * 2 or None)
    p3 = base_items(samples["P3"])
    if smoke:
        keep_notations = sorted({(i["브랜드"], i["표기"]) for i in p3})[:cut["P3_표기"]]
        p3 = [item for item in p3 if (item["브랜드"], item["표기"]) in keep_notations]
    n1 = base_items(samples["N1"], cut.get("N1"))
    n2 = base_items(samples["N2"], cut.get("N2"))
    n3 = base_items(samples["N3"], cut.get("N3", 0) * 2 or None)
    n4 = base_items(samples["N4"], cut.get("N4"))
    for item in p1 + p2 + p3 + n1 + n2 + n3 + n4:
        matcher.evidence(item)
    normal = fc.KIND_NORMAL
    p2_normal = [item for item in p2 if matcher.kind(item) == normal]
    p3_normal = [item for item in p3 if matcher.kind(item) == normal]
    results["계산한_질의"] = {
        "P1": len(p1), "P2": len(p2), "P2_보통_표기": len(p2_normal), "P3": len(p3),
        "P3_보통_표기": len(p3_normal), "N1": len(n1), "N2": len(n2), "N3": len(n3),
        "N4": len(n4)}
    tick("일치 근거", began)

    began = time.perf_counter()
    selection = select_thresholds(matcher, n1, n3, p2_normal, p3_normal)
    thresholds = fc.Thresholds.from_dict(selection["고른_기준"])
    results["기준_선택"] = selection
    results["P1"] = p1_table(matcher, p1, thresholds)
    results["P2"] = recall_by_kind(matcher, p2, thresholds)
    results["P3"] = recall_by_kind(matcher, p3, thresholds)
    results["N1"] = match_list(matcher, n1, thresholds)
    results["N2"] = match_list(matcher, n2, thresholds)
    results["N3"] = match_list(matcher, n3, thresholds)
    results["N4"] = {"행": [
        {"이름": item["이름"],
         "일치": match_row(matcher.decide(item, thresholds).strongest),
         "그_밖": [match_row(m) for m in matcher.decide(item, thresholds).matches[1:3]],
         "바닥": matcher.decide(item, thresholds).floor} for item in n4]}
    results["목표"] = targets(results)
    results["기대표"] = expectation(matcher, thresholds, goods_resolver(presets), control,
                                 samples, cut.get("기대표"))
    tick("기준 선택·목표·기대표", began)

    began = time.perf_counter()
    context = load_context()
    tick("엔진", began)
    began = time.perf_counter()
    results["이미지"] = image_measure(context, registry, matcher, thresholds, samples, control,
                                   cut or None)
    tick("이미지 속 글자·로고", began)
    began = time.perf_counter()
    results["미리_보기"] = preview(context, registry, matcher, thresholds, presets, control,
                               cut.get("미리_보기"))
    results["미리_보기_이미지"] = preview_images(context, registry, matcher, thresholds, presets,
                                          control, 1 if smoke else None)
    tick("미리 보기", began)
    began = time.perf_counter()
    review_path = (args.out_dir / "review.html") if smoke else (REVIEW_DIR / "review.html")
    results["확인용_시트"] = review_html(registry, review_path, 2 if smoke else None)
    tick("확인용 시트", began)
    results.update(시간_s=timing, 걸린_시간_s=round(time.perf_counter() - started, 1), 끝=_now())
    paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    paths["report"].write_text(report_text(results), encoding="utf-8")
    print(json.dumps({"고른_기준": selection["고른_기준"]}, ensure_ascii=False))
    print(json.dumps({name: row["통과"] for name, row in results["목표"].items()},
                     ensure_ascii=False))
    print(f"→ {paths['results']}")
    return 0


def report_text(results: dict) -> str:
    chosen = results["기준_선택"]["고른_기준"]
    lines = [f"# 유명 상표 확인 2-1단계 측정 ({results.get('끝', '')})", "",
             f"- 설정 sha256 `{results['설정_sha256']}`, 스모크 {results['스모크']}, 기본 모델 "
             f"{results['기본_모델']}",
             f"- 고른 기준: {json.dumps(chosen, ensure_ascii=False)}",
             f"- 계산한 질의: {json.dumps(results['계산한_질의'], ensure_ascii=False)}", "",
             "## 목표"]
    for name, row in results["목표"].items():
        detail = {key: value for key, value in row.items() if key != "통과"}
        lines.append(f"- {'통과' if row['통과'] else '미달'} — {name}: "
                     f"{json.dumps(detail, ensure_ascii=False)}")
    lines += ["", "## 기대표"]
    for label, row in results["기대표"]["요약"].items():
        lines.append(f"- {label}: {row['맞음']}/{row['n']}" + (
            f" — 다름: {'; '.join(row['다름'])}" if row["다름"] else ""))
    for name in ("N1", "N2", "N3"):
        part = results[name]
        lines.append(f"- {name}: 질의 {part['질의']} 중 일치 {part['일치한_질의']} — "
                     f"{json.dumps(part['수준'], ensure_ascii=False)}")
    lines.append(f"- 확인용 시트: {results['확인용_시트']['경로']}")
    return "\n".join(lines) + "\n"


def frozen_samples() -> dict:
    """1단계에 고정한 표본 파일을 그대로 읽는다(다시 만들지 않는다 — 등록부의 표기가 바뀌면 다시
    만든 표본은 달라진다)."""
    samples = json.loads(SAMPLES_FILE.read_text(encoding="utf-8"))
    if canonical_sha256(samples) != STAGE1_SAMPLES_SHA256:
        raise SystemExit(f"거절: {SAMPLES_FILE.name} 이 1단계에 고정한 표본이 아닙니다")
    return samples


def usable_samples(samples: dict, registry: fc.Registry, matcher: Matcher,
                   applicant_keys) -> tuple[dict, dict]:
    """지금 등록부로 볼 수 있는 기준용 표본과, 뺀 것의 까닭 — 지운 표기를 겨냥한 P1·P3·P2 항목,
    등록부 출원인이 된 상표의 N1 항목(새 브랜드를 넣으면 그 회사의 상표는 음성이 아니다)."""
    dropped: dict[str, list] = {"지운_표기의_표본": [], "등록부_출원인이_된_N1": []}
    out: dict[str, list] = {}
    for name in ("P1", "P3"):
        out[name] = []
        for item in base_items(samples[name]):
            if (item["브랜드"], item["표기"]) in matcher.kinds:
                out[name].append(item)
            else:
                dropped["지운_표기의_표본"].append(f"{name}: {item['이름']}({item['표기']})")
    out["P2"] = []
    for item in base_items(samples["P2"]):
        brand = registry.brand(item["브랜드"])
        script = fc.script_label(fc.text_key(item["이름"]))
        if brand is not None and (any(n.script == script for n in brand.notations)
                                  or any(n.text == item["표기"] for n in brand.notations)):
            out["P2"].append(item)
        else:
            dropped["지운_표기의_표본"].append(f"P2: {item['이름']}({item['표기']})")
    keys = registry.applicant_keys
    out["N1"] = []
    for item in base_items(samples["N1"]):
        if applicant_keys(str(item.get("출원인") or "")) & keys:
            dropped["등록부_출원인이_된_N1"].append(f"{item['이름']} — {item.get('출원인')}")
        else:
            out["N1"].append(item)
    for name in ("N2", "N3", "N4"):
        out[name] = base_items(samples[name])
    return out, dropped


def recheck(registry: fc.Registry, dist, presets, control: dict, samples: dict,
            baseline: dict, applicant_keys) -> dict:
    """등록부(표기·흔한 말·예외 낱말·새 브랜드)가 바뀐 뒤의 2-1 기준용 재측정 — 2-1 에서 고른
    기준 그대로 목표와 기대표를 다시 내고 2-1 결과와 견준다. 엔진을 쓰지 않는다(이미지 속 글자·
    로고·미리 보기 없음). 확인용 표본은 계산하지 않는다."""
    floor = fc.default_goods_floor()
    matcher = Matcher(registry, dist, floor)
    thresholds = fc.Thresholds.from_dict(baseline["기준_선택"]["고른_기준"])
    items, dropped = usable_samples(samples, registry, matcher, applicant_keys)
    normal = fc.KIND_NORMAL
    p2_normal = [item for item in items["P2"] if matcher.kind(item) == normal]
    p3_normal = [item for item in items["P3"] if matcher.kind(item) == normal]
    results: dict = {
        "때": _now(), "2-1_설정_sha256": baseline["설정_sha256"], "결합_하한": floor,
        "등록부_sha256": file_sha256(fc.DEFAULT_REGISTRY_PATH),
        "overrides_sha256": file_sha256(fc.DEFAULT_OVERRIDES_PATH),
        "기준(2-1 에서 고른 값)": thresholds.to_dict(),
        "표기_종류": kind_summary(registry), "뺀_표본": dropped,
        "계산한_질의": {name: len(rows) for name, rows in items.items()} | {
            "P2_보통_표기": len(p2_normal), "P3_보통_표기": len(p3_normal)},
        "P1": p1_table(matcher, items["P1"], thresholds),
        "P2": recall_by_kind(matcher, items["P2"], thresholds),
        "P3": recall_by_kind(matcher, items["P3"], thresholds),
        "N1": match_list(matcher, items["N1"], thresholds),
        "N2": match_list(matcher, items["N2"], thresholds),
        "N3": match_list(matcher, items["N3"], thresholds),
    }
    results["목표"] = targets(results)
    results["기대표"] = expectation(matcher, thresholds, goods_resolver(presets), control, samples)
    selection = select_thresholds(matcher, items["N1"], items["N3"], p2_normal, p3_normal)
    results["기준을_다시_고르면"] = {
        "고른_기준": selection["고른_기준"], "S": selection["S"]["고른_값"],
        "2-1 과_같음": selection["고른_기준"] == baseline["기준_선택"]["고른_기준"]}
    # 2-1 결과와 견주기
    before = {(row["기대"], row["입력"], row["업종"]): row["결과"]
              for row in baseline["기대표"]["행"]}
    changed = [{"기대": row["기대"], "입력": row["입력"], "업종": row["업종"],
                "2-1": before.get((row["기대"], row["입력"], row["업종"])), "지금": row["결과"],
                "일치": row.get("일치")}
               for row in results["기대표"]["행"]
               if before.get((row["기대"], row["입력"], row["업종"])) != row["결과"]]
    target_changes = {name: {"2-1": baseline["목표"][name], "지금": row}
                      for name, row in results["목표"].items()
                      if baseline["목표"][name]["통과"] != row["통과"]
                      or baseline["목표"][name]["값"] != row["값"]}

    def names(key: str, source: dict) -> list[str]:
        return sorted(f"{row['이름']} → {row['일치']['브랜드']} {row['일치']['수준']}"
                      f"({row['일치']['경로']})" for row in source[key]["목록"])

    lists = {}
    for key in ("N1", "N2", "N3"):
        now, then = names(key, results), names(key, baseline)
        lists[key] = {"새로_생긴_일치": sorted(set(now) - set(then)),
                      "없어진_일치": sorted(set(then) - set(now))}
    results["2-1 과_견줌"] = {
        "목표가_모두_통과": all(row["통과"] for row in results["목표"].values()),
        "목표에서_달라진_것": target_changes,
        "기대표_요약이_같음": results["기대표"]["요약"] == baseline["기대표"]["요약"],
        "기대표에서_달라진_행": changed, "일치_목록에서_달라진_것": lists}
    return results


def recheck_text(results: dict) -> str:
    compare = results["2-1 과_견줌"]
    lines = ["유명 상표 확인 — 2-1 기준용 재측정(확인용은 계산하지 않음)", ""]
    lines.append("표기 종류: " + " · ".join(
        f"{kind} {len(value) if isinstance(value, list) else value}"
        for kind, value in results["표기_종류"].items()))
    for reason, rows in results["뺀_표본"].items():
        if rows:
            lines.append(f"뺀 표본 — {reason} {len(rows)}건: " + " · ".join(rows[:12])
                         + (" …" if len(rows) > 12 else ""))
    lines.append("")
    lines.append("목표(2-1 에서 고른 기준 그대로):")
    for name, row in results["목표"].items():
        lines.append(f"  {'통과' if row['통과'] else '미달'}  {name} — 값 {row['값']}"
                     + (f" (n {row['n']})" if "n" in row else ""))
    lines.append("")
    lines.append("기대표:")
    for label, row in results["기대표"]["요약"].items():
        lines.append(f"  {label}: {row['맞음']}/{row['n']}"
                     + (f" — 다름: {' / '.join(row['다름'])}" if row["다름"] else ""))
    lines.append("")
    lines.append("2-1 결과와 견줌: 목표가 모두 통과 "
                 f"{'예' if compare['목표가_모두_통과'] else '아니오'} · 기대표 요약이 같음 "
                 f"{'예' if compare['기대표_요약이_같음'] else '아니오'} · 달라진 기대표 행 "
                 f"{len(compare['기대표에서_달라진_행'])}")
    for row in compare["기대표에서_달라진_행"]:
        lines.append(f"  · [{row['기대']}] {row['입력']} + {row['업종']}: {row['2-1']} → "
                     f"{row['지금']}")
    for key, change in compare["일치_목록에서_달라진_것"].items():
        for label, rows in change.items():
            if rows:
                lines.append(f"  · {key} {label.replace('_', ' ')} {len(rows)}: "
                             + " / ".join(rows[:10]) + (" …" if len(rows) > 10 else ""))
    again = results["기준을_다시_고르면"]
    lines.append(f"기준을 다시 고르면 2-1 과 같은 값: {'예' if again['2-1 과_같음'] else '아니오'}")
    return "\n".join(lines)


def recheck_diff(previous: dict, results: dict) -> dict:
    """직전 recheck 결과와 달라진 것만 — 목표 값, 기대표 행, N1·N2·N3 일치 목록, 재현율 표, 뺀
    표본."""
    def names(source: dict, key: str) -> set[str]:
        return {f"{row['이름']} → {row['일치']['브랜드']} {row['일치']['수준']}"
                f"({row['일치']['경로']})" for row in source[key]["목록"]}

    def rows(source: dict) -> dict:
        return {(row["기대"], row["입력"], row["업종"]): row["결과"]
                for row in source["기대표"]["행"]}

    before, after = rows(previous), rows(results)
    out: dict = {
        "목표": {name: {"직전": previous["목표"][name]["값"], "지금": row["값"],
                      "통과": row["통과"]}
               for name, row in results["목표"].items()
               if previous["목표"].get(name, {}).get("값") != row["값"]},
        "기대표": [{"기대": key[0], "입력": key[1], "업종": key[2], "직전": before.get(key),
                  "지금": value} for key, value in after.items() if before.get(key) != value],
        "일치_목록": {}, "재현율": {}, "뺀_표본": {},
    }
    for key in ("N1", "N2", "N3"):
        new, gone = names(results, key) - names(previous, key), names(previous, key) - names(
            results, key)
        if new or gone:
            out["일치_목록"][key] = {"새로_생김": sorted(new), "없어짐": sorted(gone)}
    for key in ("P2", "P3"):
        for kind, table in results[key].items():
            old = previous[key].get(kind, {}).get("전체")
            if old != table["전체"]:
                out["재현율"][f"{key} {kind}"] = {"직전": old, "지금": table["전체"]}
    if previous["P1"]["강함"] != results["P1"]["강함"] or previous["P1"]["n"] != results["P1"]["n"]:
        out["재현율"]["P1"] = {"직전": [previous["P1"]["강함"], previous["P1"]["n"]],
                             "지금": [results["P1"]["강함"], results["P1"]["n"]]}
    for reason, items in results["뺀_표본"].items():
        old = previous["뺀_표본"].get(reason, [])
        if old != items:
            out["뺀_표본"][reason] = {"직전": len(old), "지금": len(items),
                                    "새로_빠짐": sorted(set(items) - set(old)),
                                    "다시_들어옴": sorted(set(old) - set(items))}
    out["같음"] = not (out["목표"] or out["기대표"] or out["일치_목록"] or out["재현율"]
                     or out["뺀_표본"])
    return out


def recheck_diff_text(diff: dict) -> str:
    if diff["같음"]:
        return "직전 결과와 달라진 것: 없음"
    lines = ["직전 결과와 달라진 것:"]
    for name, row in diff["목표"].items():
        lines.append(f"  · 목표 {name}: {row['직전']} → {row['지금']}"
                     f"({'통과' if row['통과'] else '미달'})")
    for row in diff["기대표"]:
        lines.append(f"  · 기대표 [{row['기대']}] {row['입력']} + {row['업종']}: {row['직전']} → "
                     f"{row['지금']}")
    for key, change in diff["일치_목록"].items():
        for label, rows in change.items():
            if rows:
                lines.append(f"  · {key} {label.replace('_', ' ')} {len(rows)}: "
                             + " / ".join(rows))
    for key, change in diff["재현율"].items():
        lines.append(f"  · {key}: {change['직전']} → {change['지금']}")
    for reason, change in diff["뺀_표본"].items():
        lines.append(f"  · 뺀 표본 {reason.replace('_', ' ')}: {change['직전']} → {change['지금']}"
                     + (f" — 새로 빠짐: {' · '.join(change['새로_빠짐'][:12])}"
                        if change["새로_빠짐"] else ""))
    return "\n".join(lines)


def command_recheck(args) -> int:
    """등록부를 고친 뒤(apply·build) 2-1 기준용 목표와 기대표가 유지되는지 본다."""
    from scripts import famous_registry as builder

    if not STAGE21_RESULTS.exists():
        raise SystemExit(f"거절: 2-1 결과가 없습니다({STAGE21_RESULTS.name})")
    baseline = json.loads(STAGE21_RESULTS.read_text(encoding="utf-8"))
    presets = gm.load_business_presets(gm.load_goods_map())
    control = json.loads(CONTROL.read_text(encoding="utf-8"))
    results = recheck(fc.load_registry(), dx.load_distinctiveness(), presets, control,
                      frozen_samples(), baseline, builder.applicant_key_function())
    out = (args.out_dir if args.out_dir != TRIALS else TRIALS) / "famous_check_recheck.json"
    if args.previous:  # 읽고 나서 쓴다(같은 파일을 가리켜도 되게)
        previous = json.loads(Path(args.previous).read_text(encoding="utf-8"))
        results["직전_결과와_견줌"] = recheck_diff(previous, results)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(recheck_text(results))
    if args.previous:
        print(recheck_diff_text(results["직전_결과와_견줌"]))
    print(f"→ {out}")
    compare = results["2-1 과_견줌"]
    return 0 if compare["목표가_모두_통과"] and compare["기대표_요약이_같음"] else 3


def command_sheet(args) -> int:
    """확인용 시트만 다시 만든다(측정 없음 — 등록부·overrides 를 고친 뒤)."""
    target = (args.out_dir / "review.html") if args.out_dir != TRIALS else (
        REVIEW_DIR / "review.html")
    print(json.dumps(review_html(fc.load_registry(), target), ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("freeze", "run", "sheet", "recheck", "logos"))
    parser.add_argument("--previous", type=Path,
                        help="recheck: 직전 recheck 결과(JSON) — 달라진 것만 따로 낸다")
    parser.add_argument("--out-dir", type=Path, default=TRIALS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--smoke", action="store_true",
                        help="구현 확인 — 일부 표본만(다른 --out-dir 에)")
    args = parser.parse_args(argv)
    return {"freeze": command_freeze, "run": command_run, "sheet": command_sheet,
            "recheck": command_recheck, "logos": command_logos}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
