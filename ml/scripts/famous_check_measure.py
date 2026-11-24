"""유명 상표 확인 단계 — 1단계 측정(통합 모델 설계 §7-14). 엔진·계약·화면은 바꾸지 않는다.

등록부(shared/famous_registry.json)와 일치 판정 함수(src.famous_check — 엔진에서 부르지 않음)를
표본으로 재고, 미리 정한 규칙으로 기준값을 고른다. 이번 단계에는 채택 조건이 없다. 정의·표본·
선택 규칙은 `RULE`(실행 전에 해시를 남기고 결과를 보고 바꾸지 않는다).

    ml/venv/bin/python ml/scripts/famous_check_measure.py freeze   # 설정·표본·입력 해시
    ml/venv/bin/python ml/scripts/famous_check_measure.py run      # 측정(고정본과 다르면 4)
    ml/venv/bin/python ml/scripts/famous_check_measure.py run --smoke --out-dir <폴더>
    ml/venv/bin/python ml/scripts/famous_check_measure.py sheet    # 확인용 시트만 다시(측정 없음)

확인용 표본(P2 둘째·P3 뒤 둘·N1·N3 확인용)은 정의만 고정하고 결과를 계산하지 않는다(2단계에서
처음 본다). KIPRIS 호출 0. run 은 실제 CLIP·OCR·X3 엔진(로고·미리 보기·다른 업종 규모).
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
STEM = "famous_check"
EXIT_REFUSED = 4
SEED = 0
BASE, HOLDOUT = "기준용", "확인용"
REVIEW_DIR = Path.home() / "marklens-archive" / "famous-check-20261124"
METADATA = ML_ROOT / "data" / "kipris_metadata.json"
FEATURES = TRIALS / "pairs_features.csv"
IMAGE_PARTS = TRIALS / "image_parts.csv"
CONTROL = TRIALS / "named_search_thresholds_control.json"
IMAGES_DIR = ML_ROOT / "data" / "images"
STRONG_SPELLING_GRID = (0.90, 0.95)
WEAK_SOUND_GRID = (0.90, 0.92, 0.94, 0.96)
WEAK_SPELLING_GRID = (0.75, 0.80, 0.85, 0.90)
N1_RATE_MAX, N3_RATE_MAX = 0.005, 0.02
LOGO_N1_IMAGES = 300
LIST_ROWS = 100
KIND_NAMES = {"문자": "글자 위주", "결합": "결합", "도형": "도형 위주"}  # 자동 유형 → 보고 이름
P3_PER_NOTATION = 4
FRUIT_GOODS = (("신선한 과실", 31), ("신선한 과실 판매업(도소매·중개·대행)", 35))
SMOKE = {"P1_브랜드": 2, "P2": 3, "P3_표기": 3, "N1": 30, "N2": 30, "N3": 10, "N4": 5,
         "로고_표장": 6, "로고_음성": 5, "미리_보기": 6, "규모": 3}

# P2 실제 모방 꼴 — (브랜드(등록부 이름), 기준용, 확인용). 지시의 목록 그대로.
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
# 미리 보기 입력 — (이름, 업종 세트 id | "과일" | None). 업종은 가장 가까운 업종 세트.
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
PREVIEW_HOLDOUT_SEEN = ("헤르메스",)  # P2 확인용이지만 지시의 미리 보기 목록에 있어 계산한다
CHO_GROUPS = (("ㄱ", "ㄲ", "ㅋ"), ("ㄷ", "ㄸ", "ㅌ"), ("ㅂ", "ㅃ", "ㅍ"), ("ㅈ", "ㅉ", "ㅊ"),
              ("ㅅ", "ㅆ"))
JUNG_SWAPS = (("ㅐ", "ㅔ"), ("ㅓ", "ㅗ"), ("ㅡ", "ㅜ"), ("ㅗ", "ㅜ"))
JONG_NASALS = ("ㄴ", "ㅇ", "ㅁ")
LETTER_SWAPS = (("a", "e"), ("i", "y"), ("c", "k"), ("s", "z"))

RULE = {
    "목적": (
        "유명 상표 확인 단계의 1단계 — 등록부를 만들고 일치 판정 함수를 서비스에 연결하지 않은 채 "
        "측정한다. 채택 조건 없음. 막히는 항목은 '확인 못 함'과 이유를 적는다."),
    "정리": (
        "clean_input_name → 상표 기호 제거·NFKC·소문자 → 엔진의 상품 접미어 분리"
        "(Distinctiveness.split_goods_suffix) → 공백·기호로 낱말. 붙여 쓴 꼴 = 한글·영문·숫자만 "
        "이은 것, 조각 = 문자 종류 경계(X1 토큰화). 낱말 묶음 = 이어진 낱말(최대 5)을 붙인 꼴. "
        "식별력 필터(요부 추출)는 거치지 않는다."),
    "식별력_없는_말": (
        "항상 유명 예외를 뺀 판정(judge(…, famous_exception=False))이 약함(< θ 0.5). 질의 업종이 "
        "있으면 그 업종이나 브랜드 업종 중 하나에서, 없으면 브랜드 업종에서 약하거나 상품 접미어 "
        "사전(고시 단일 명칭 goods_names)에 있는 말. 붙은 글자열은 조각이 모두 그래야 한다. "
        "브랜드 업종(판정 맥락) = 브랜드 표장(역할 이름·도형·브랜드 로고)의 유사군 합집합, 없으면 "
        "업종 세트의 유사군."),
    "경로": (
        "(가) 같음: 낱말 묶음 = 표기. (나) 품음: 한 낱말이 표기로 시작하거나 끝남 — 나머지가 "
        "식별력 없는 말이면 품음-설명, 아니면 품음-기타(짧은 표기는 품음-설명만). (다) 소리: X1 "
        "phonetic_similarity(extra_generic 없음), 한글·영문이 달라도 X1 발음 변환으로. 대상은 낱말 "
        "묶음과, 중간·김 표기에 한해 한 낱말의 앞·뒤 구간으로서 나머지가 식별력 없는 말인 것. "
        "(라) 철자: 같은 문자 종류끼리만 orthographic_similarity v1, 대상은 (다)와 같다."),
    "길이_구간": (
        "짧음 = 한글 2음절 이하 또는 영문·숫자 3자 이하, 중간 = 한글 3음절 또는 영문·숫자 4–5자, "
        "김 = 그 이상. 섞인 표기(지에스25)는 한글 음절 + 0.6 × 영문·숫자 글자 수 ≤ 2 / ≤ 3 / 그 위"
        "(순수 표기에서는 앞의 구간과 같다)."),
    "약한_표기": (
        "유명 예외를 뺀 판정으로 그 브랜드 자신의 업종에서 조각(접미어 분리 뒤)이 모두 약한 표기. "
        "(가)만: 질의 조각에서 상품·업종을 나타내는 말(사유가 1호 보통명칭·3호 기술적 표장으로 "
        "약한 말, 상품 접미어 사전의 말)을 뺀 나머지가 그 표기 하나뿐이면 일치 — 업종이 겹치거나 "
        "없으면 강함, 다르면 설명적 사용 안내. 다른 말과 함께면 설명적 사용 안내. 해석(지시에 "
        "없어 고정): 질의 안의 약한 표기 조각은 그 브랜드의 다른 표기와 견주지 않는다(가림) — "
        "안 그러면 '텍사스 BBQ'의 bbq 가 '비비큐'와 소리 1.0 이라 '그 표기 하나뿐일 때만'이 "
        "무력해진다. 낱말의 앞·뒤 구간이 약한 표기와 같을 때도 견주지 않는다."),
    "설명적_사용": (
        "약한 표기가 아니어도 질의 업종에서 그 표기(조각 모두)가 식별력 없는 말이고 브랜드 업종과 "
        "겹치지 않으면 일치를 설명적 사용 안내로 바꾼다."),
    "업종_겹침": (
        "질의 업종과 브랜드 업종 사이 X4(자카드)가 결합 하한(계수 JSON coupling.floors.x4 = "
        "0.0252) 이상. 브랜드 업종 = 브랜드 표장 하나하나의 유사군과 업종 세트의 유사군 — 그 "
        "가운데 최댓값으로 본다(해석: 합집합 하나로 재면 CU 0.012·네이버 0.015·이케아 0.000 으로 "
        "자기 업종 세트와도 '다름'이 되어, 엔진이 후보마다 재는 X4 와 같게 표장별로 본다)."),
    "수준과_바닥": (
        "강함 = 같음·품음-설명·소리 ≥ 강한 소리·철자 ≥ 강한 철자. 약함 = 소리·철자 ≥ 약한 기준"
        "(표기의 길이 구간별)·품음-기타(결정 대기 — 따로 센다). 전체 등급 바닥: 업종 불문 브랜드는 "
        "강함 → 위험·약함 → 검토 권장, 같은·가까운 업종 중심 브랜드는 업종이 겹치거나 없으면 같고 "
        "다르면 강함 → 검토 권장·약함 → 안내만. 설명적 사용 안내는 바닥 없음. 가장 강한 것 = "
        "수준 → 경로(같음·품음-설명·소리·철자·품음-기타) → 점수 순."),
    "이미지_속_글자": (
        "이름이 없는 이미지 입력은 엔진의 OCR 제안 상표명(overall.query_type.suggested_name)이 "
        "있으면 그 글자로 (가)(나)만 판정해 '이미지 속 글자 기준'으로 표시."),
    "표본": (
        "seed 0. P1 같은 이름: 모든 표기 × {그대로, 대소문자 바꿈(영문), 띄어쓰기 바꿈(공백 있으면 "
        "붙이고 없으면 가운데에 공백), 자기 업종 낱말을 띄어서·붙여서(업종 낱말 = 업종 세트의 첫 "
        "별칭, 상품 낱말 = 별칭 중 상품 접미어 사전에 있는 첫 낱말 — 다르면 둘 다), 무관한 업종 "
        "낱말(업종 세트 파일 순서로 자기 세트 + 7번째부터 브랜드 업종과 X4 가 0 인 첫 세트의 첫 "
        "별칭 — 그런 세트가 없으면 겹침 최댓값이 가장 작은 세트)} × 업종 {없음, 자기 업종 "
        "세트(무관한 낱말은 그 무관한 세트)}. P2 실제 모방 꼴: "
        "지시의 28쌍(첫째 기준용·둘째 확인용), 약한 표기가 있는 브랜드는 제외(따로 표시), 업종 "
        "없음·자기 업종, 겨냥한 표기(길이 구간 표시용) = 같은 문자 종류의 약하지 않은 표기 중 글자 "
        "수가 가장 가까운 것. P3 비슷한 소리 변형: 약하지 않은 표기마다 한 글자를 규칙 하나로 "
        "바꾼 것(한글: ㅐ↔ㅔ·ㅓ↔ㅗ·ㅡ↔ㅜ·ㅗ↔ㅜ, 예사·된·거센소리, 받침 ㄴ↔ㅇ↔ㅁ, 받침 ㄹ 넣기·"
        "빼기 / "
        "영문: 겹글자 넣기·빼기, a↔e·i↔y·c↔k·s↔z) 전체를 정렬 뒤 섞어 앞 4개(기준용 2·확인용 2), "
        "등록부 표기·P2 의 이름·N4·미리 보기 입력과 같은 것, 앞선 표기에서 이미 나온 것은 "
        "뺀다(확인용과 계산하는 표본이 겹치지 않게). 업종 없음·자기 업종. N1 실제 등록 상표명: "
        "DB 에서 수집 "
        "출처가 유명 브랜드가 아니고 출원인(별칭 표 적용)이 등록부 출원인이 아닌 상표의 이름"
        "(상표한글명, 없으면 영문명), 질의 업종 = 그 상표의 유사군, 이름 단위로 섞어 절반씩. N2 "
        "심결 데이터의 이름(학습 특징 심결 행의 이름A·이름B, 중복 제거, 업종 없음) — 기준 선택에 "
        "쓰지 않음. N3 지어낸 이름 대조군(named_search_thresholds 기준용 100·확인용 100) × 업종 "
        "{없음, 그 이름에 배정된 무작위 업종 세트}. N4 함정 낱말 38(업종 없음) — 기준 선택에 쓰지 "
        "않음. 확인용(P2 둘째·P3 뒤 둘·N1·N3 확인용)은 정의만 고정하고 결과를 계산하지 않는다. "
        "지시가 계산하라고 한 목록(P1·N2·N4·미리 보기)의 이름이 확인용 이름과 붙여 쓴 꼴이 같으면 "
        "그대로 계산하고 겹친 이름을 보고한다."),
    "기준_선택": (
        "단위는 질의(이름 × 업종). 강한 소리 = 0.98 고정. 강한 철자 = {0.90, 0.95} 중 N1·N3 "
        "기준용에서 새로 생기는 일치(그 경로가 없으면 강한 일치가 아니던 질의가 강한 일치가 "
        "되는 것)가 0건인 가장 낮은 값, 없으면 쓰지 않는다. 약한 소리(길이 구간별) = {0.90, 0.92, "
        "0.94, 0.96} 중 같음·품음·강한 경로로 이미 잡힌 질의(설명적 사용 안내 포함)를 뺀 '새로 "
        "더하는 일치'가 N1 기준용의 0.5% 이하이고 N3 기준용의 2% 이하인 가장 낮은 값 — 구간마다 "
        "그 구간 표기만 켜고 센다. 약한 철자(길이 구간별) = {0.75, 0.80, 0.85, 0.90} 중 그 "
        "구간의 약한 소리(고른 값)까지 켠 상태에서 같은 조건을 지키는 가장 낮은 값 — 해석: '새로 "
        "더하는 일치'의 정의(같음·품음·강한 경로로 잡히지 않은 것)를 그대로 써서 그 구간의 약한 "
        "소리와 약한 철자가 함께 더하는 수(누적)를 한도와 견준다. 철자만 따로 더하는 수(증분)도 "
        "표에 적는다. 조건을 지키는 값이 없으면 그 구간에서 그 경로를 쓰지 않는다."),
    "보고": (
        "고른 기준에서 P2·P3 기준용 재현율(대상 브랜드와의 일치 — 길이 구간·변형 종류·업종별), "
        "N1·N2·N3·N4 일치 목록(경로·출원인, 100행까지), 품음-기타로만 잡힌 것은 따로."),
    "로고": (
        "새 기준 없음. 질의 이미지와 한 브랜드의 표장(역할 이름·도형 전부) 사이의 엔진 '이미지만' "
        "판단(ms._judge(ms._image_only_features(x2, 도형))) 등급이 위험이면 강함, 검토 권장이면 "
        "약함(표장 가운데 가장 높은 것). 사진으로 판정된 질의(ms.is_photo_query)는 하지 않는다. "
        "자기 확인: 표장 이미지 각각을 이름 없이 넣었을 때 자기 브랜드와 강함인 비율(자기 자신 "
        "포함 / 자기 자신 빼고), 다른 브랜드와 약함 이상인 쌍. 음성: 대조군의 덜 닮은 이미지 92, "
        "표본 A 질의 이미지 전부, N1 기준용 상표의 이미지 300(seed 0 — 확인용 절반은 이미지도 "
        "건드리지 않는다) — 어느 브랜드와든 약함 이상인 비율과 목록. 글자 위주·결합·도형 위주 = "
        "자동 유형(mark_type.auto_type — 심결 이미지는 image_parts.csv, DB 이미지는 엔진 OCR "
        "ocr.detect 로 같은 규칙)."),
    "미리_보기": (
        "PREVIEW_NAMES + 이미지 넷: 지금(기본 모델, 실제 엔진 multi_search top_k 5) 전체 등급 / "
        "일치 / 바닥을 적용한 전체 등급(둘 중 높은 등급) / 안내 종류. '헤르메스 + 의류'는 P2 "
        "확인용이지만 지시의 목록에 있어 계산하고 표시한다."),
    "다른_업종_규모": (
        "업종을 넣은 질의에서 업종이 다르고(후보의 x4 < 결합 하한) 업종 없이 본 짝 판단(그 후보 "
        "첫 판단의 입력에서 x4 를 뺀 것) 등급이 검토 권장 이상인 후보. 지어낸 이름 대조군 "
        "기준용(이름+업종) 100, 표본 A 업종 있는 108 질의(이름+이미지+업종), 시나리오 16종 중 "
        "업종 있는 것: 질의당 개수 분포, 최종 등급 분포, 앞 5 안팎, 예시 10."),
    "스모크": "일부 표본만(SMOKE), 다른 폴더에. 확인용은 스모크에서도 계산하지 않는다.",
}


# ---- 공통 --------------------------------------------------------------------------------------

def canonical_sha256(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _settings() -> dict:
    return {"RULE": RULE, "SEED": SEED, "P2_PAIRS": P2_PAIRS, "N4_TRAPS": N4_TRAPS,
            "PREVIEW_NAMES": PREVIEW_NAMES, "STRONG_SOUND": fc.STRONG_SOUND,
            "STRONG_SPELLING_GRID": STRONG_SPELLING_GRID, "WEAK_SOUND_GRID": WEAK_SOUND_GRID,
            "WEAK_SPELLING_GRID": WEAK_SPELLING_GRID, "N1_RATE_MAX": N1_RATE_MAX,
            "N3_RATE_MAX": N3_RATE_MAX, "LOGO_N1_IMAGES": LOGO_N1_IMAGES,
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
        "런타임": ML_ROOT / "src" / "model" / "risk_model.py",
    }


def _paths(out_dir: Path) -> dict[str, Path]:
    return {"rule": out_dir / f"{STEM}_rule.json", "samples": out_dir / f"{STEM}_samples.json",
            "results": out_dir / f"{STEM}_results.json", "report": out_dir / f"{STEM}_report.md"}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _preset_codes(presets, preset_id: str) -> list[str]:
    return sorted({code for good in presets.get(preset_id).goods
                   for code in good.similarity_codes})


# ---- 표본 --------------------------------------------------------------------------------------

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
    usable = [n for n in brand.notations if not n.weak] or list(brand.notations)
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
    weak_brands = {brand.name for brand in registry.brands if any(n.weak for n in brand.notations)}
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
                                       "약한_표기": notation.weak, "변형": kind, "반": None},
                                      own_goods)
            p1 += _with_goods(
                {"이름": f"{text} {other_word}", "브랜드": brand.name, "표기": text,
                 "약한_표기": notation.weak, "변형": "무관한 업종 낱말", "반": None},
                [("없음", None), (f"무관한 업종({other['id']})", codes_of[other["id"]])])
            if not notation.weak:
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
        if record.get("수집_출처") == "유명 브랜드":
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
        self._cache: dict[tuple, list[fc.BrandEvidence]] = {}

    def evidence(self, item: dict) -> list[fc.BrandEvidence]:
        if item.get("반") == HOLDOUT:
            raise ValueError("확인용 표본은 이 단계에서 계산하지 않습니다")
        key = (item["이름"], tuple(item.get("업종") or ()))
        if key not in self._cache:
            query = fc.prepare_query(item["이름"], item.get("업종"), self.dist)
            self._cache[key] = fc.collect_evidence(query, self.registry, self.dist, self.floor)
        return self._cache[key]

    def decide(self, item: dict, thresholds: fc.Thresholds) -> fc.FamousResult:
        return fc.decide(self.evidence(item), thresholds)


def match_row(match: fc.BrandMatch | None) -> dict | None:
    if match is None:
        return None
    return {"브랜드": match.brand, "수준": match.level, "경로": match.path, "표기": match.notation,
            "점수": match.score, "바닥": match.floor, "겹침": match.overlap,
            "결정_대기": match.pending, "메모": match.note, "기준": match.basis}


def select_thresholds(matcher: Matcher, n1: list[dict], n3: list[dict]) -> dict:
    """기준 선택 규칙(RULE['기준_선택'])을 적용 — 고른 기준과 근거 표."""
    def caught(item: dict, thresholds: fc.Thresholds, strong_only: bool = False) -> bool:
        matches = matcher.decide(item, thresholds).matches
        if strong_only:
            return any(match.level == fc.LEVEL_STRONG for match in matches)
        return bool(matches)

    def count_new(items: list[dict], before: fc.Thresholds, after: fc.Thresholds,
                  strong_only: bool = False) -> list[dict]:
        return [item for item in items if not caught(item, before, strong_only)
                and caught(item, after, strong_only)]

    def with_(base: fc.Thresholds, **changes) -> fc.Thresholds:
        return fc.Thresholds.from_dict({**base.to_dict(), **changes})

    table: dict = {"단위": {"N1_기준용_질의": len(n1), "N3_기준용_질의": len(n3)}}
    base = fc.Thresholds()
    strong_rows, strong_spelling = [], None
    for value in STRONG_SPELLING_GRID:
        new = (count_new(n1, base, with_(base, strong_spelling=value), True)
               + count_new(n3, base, with_(base, strong_spelling=value), True))
        strong_rows.append({"값": value, "새로_생기는_일치": len(new),
                            "예": [item["이름"] for item in new[:10]]})
        if strong_spelling is None and not new:
            strong_spelling = value
    table["강한_철자"] = {"격자": strong_rows, "고른_값": strong_spelling}
    base = with_(base, strong_spelling=strong_spelling)

    def within(new1: list, new3: list) -> tuple[float, float, bool]:
        rate1 = len(new1) / len(n1) if n1 else 0.0
        rate3 = len(new3) / len(n3) if n3 else 0.0
        return rate1, rate3, rate1 <= N1_RATE_MAX + 1e-12 and rate3 <= N3_RATE_MAX + 1e-12

    def only(length: str, value: float | None) -> dict:
        return {**{other: None for other in fc.LENGTHS}, length: value}

    # 약한 소리 — 구간마다 그 구간 표기만 켜고, 같음·품음·강한 경로(base)로 안 잡힌 질의 중 새로
    weak_sound, rows = {}, {}
    for length in fc.LENGTHS:
        rows[length], weak_sound[length] = [], None
        for value in WEAK_SOUND_GRID:
            trial = with_(base, weak_sound=only(length, value))
            new1, new3 = count_new(n1, base, trial), count_new(n3, base, trial)
            rate1, rate3, ok = within(new1, new3)
            rows[length].append({
                "값": value, "N1_새_일치": len(new1), "N1_비율": round(rate1, 4),
                "N3_새_일치": len(new3), "N3_비율": round(rate3, 4), "조건": ok,
                "예": [item["이름"] for item in (new1 + new3)[:8]]})
            if weak_sound[length] is None and ok:
                weak_sound[length] = value
    table["약한_소리"] = {"격자": rows, "고른_값": weak_sound}
    # 약한 철자 — 그 구간의 약한 소리(고른 값)까지 켠 누적으로 같은 한도. 증분 = 약한 소리(모든
    # 구간)까지 정한 상태에서 철자만 따로 더하는 수(참고)
    sounded = with_(base, weak_sound=weak_sound)
    weak_spelling, rows = {}, {}
    for length in fc.LENGTHS:
        rows[length], weak_spelling[length] = [], None
        for value in WEAK_SPELLING_GRID:
            trial = with_(base, weak_sound=only(length, weak_sound[length]),
                          weak_spelling=only(length, value))
            new1, new3 = count_new(n1, base, trial), count_new(n3, base, trial)
            rate1, rate3, ok = within(new1, new3)
            extra = with_(sounded, weak_spelling=only(length, value))
            more1, more3 = count_new(n1, sounded, extra), count_new(n3, sounded, extra)
            rows[length].append({
                "값": value, "N1_새_일치(누적)": len(new1), "N1_비율": round(rate1, 4),
                "N3_새_일치(누적)": len(new3), "N3_비율": round(rate3, 4), "조건": ok,
                "N1_철자만_더함(증분)": len(more1), "N3_철자만_더함(증분)": len(more3),
                "증분으로_보면_조건": within(more1, more3)[2],
                "예": [item["이름"] for item in (more1 + more3)[:8]]})
            if weak_spelling[length] is None and ok:
                weak_spelling[length] = value
    table["약한_철자"] = {"격자": rows, "고른_값": weak_spelling}
    final = with_(sounded, weak_spelling=weak_spelling)
    total1, total3 = count_new(n1, base, final), count_new(n3, base, final)
    table["고른_기준에서_새로_더한_일치(전체)"] = {
        "N1": len(total1), "N1_비율": round(len(total1) / len(n1), 4) if n1 else None,
        "N3": len(total3), "N3_비율": round(len(total3) / len(n3), 4) if n3 else None}
    table["고른_기준"] = final.to_dict()
    return table


def recall_table(matcher: Matcher, items: list[dict], thresholds: fc.Thresholds) -> dict:
    """대상 브랜드와의 일치 — 강함·약함 이상 비율(길이 구간·변형 종류·업종별)과 놓친 목록."""
    rows = []
    for item in items:
        result = matcher.decide(item, thresholds)
        own = next((m for m in result.matches if m.brand == item["브랜드"]), None)
        rows.append({**{k: item[k] for k in ("이름", "브랜드", "표기", "변형", "업종_표시")},
                     "길이": item.get("길이"), "대상_일치": match_row(own),
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
            "업종별": by("업종_표시"), "경로": dict(paths),
            "놓친_것": [r for r in rows if r["대상_일치"] is None
                      or r["대상_일치"]["수준"] == fc.LEVEL_NOTICE], "행": rows}


def match_list(matcher: Matcher, items: list[dict], thresholds: fc.Thresholds) -> dict:
    """일치 목록 — 질의마다 가장 강한 일치(경로·출원인), 수준별 수, 품음-기타로만 잡힌 것 따로."""
    rows, pending_only = [], []
    levels: Counter = Counter()
    for item in items:
        result = matcher.decide(item, thresholds)
        if not result.matches:
            continue
        row = {"이름": item["이름"], "업종": item.get("업종_표시"),
               "출원인": item.get("출원인"), "출원번호": item.get("출원번호"),
               "심판번호": item.get("심판번호"), "일치": match_row(result.strongest),
               "그_밖": [match_row(m) for m in result.matches[1:4]], "바닥": result.floor}
        if all(match.pending for match in result.matches):
            pending_only.append(row)
            levels["품음-기타만"] += 1
        else:
            rows.append(row)
            levels[result.strongest.level] += 1
    return {"질의": len(items), "일치한_질의": len(rows) + len(pending_only),
            "수준": dict(levels), "경로": dict(Counter(r["일치"]["경로"] for r in rows)),
            "목록": rows, "품음_기타만": pending_only}


def p1_table(matcher: Matcher, items: list[dict], thresholds: fc.Thresholds) -> dict:
    rows = []
    for item in items:
        result = matcher.decide(item, thresholds)
        own = next((m for m in result.matches if m.brand == item["브랜드"]), None)
        rows.append({**{k: item[k] for k in ("이름", "브랜드", "표기", "변형", "업종_표시",
                                             "약한_표기")}, "대상_일치": match_row(own)})
    strong = [r for r in rows if (r["대상_일치"] or {}).get("수준") == fc.LEVEL_STRONG]
    not_strong = [r for r in rows if r not in strong]
    kinds = Counter((r["변형"], r["약한_표기"],
                     (r["대상_일치"] or {}).get("수준") or "일치 없음") for r in not_strong)
    return {"n": len(rows), "강함": len(strong), "강함_아님": len(not_strong),
            "강함_아님_분류": [{"변형": k[0], "약한_표기": k[1], "결과": k[2], "수": v}
                          for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])],
            "강함_아닌_목록": not_strong}


# ---- 엔진을 쓰는 측정(로고·미리 보기·다른 업종 규모) ---------------------------------------------

def load_context():
    from scripts import nameless_shared_threshold as ns

    context = ns._context(rm.DEFAULT_MODEL_PATH)  # noqa: SLF001
    context["ns"] = ns
    return context


def image_types() -> dict[str, str]:
    with IMAGE_PARTS.open(encoding="utf-8") as handle:
        return {row["경로"]: row["자동유형"] for row in csv.DictReader(handle)}


class Logo:
    """로고 측정 — 질의 이미지와 브랜드 표장 사이의 엔진 '이미지만' 판단 등급."""

    def __init__(self, context: dict, registry: fc.Registry):
        import numpy as np

        self.np = np
        self.ms, self.engine = context["ms"], context["engine"]
        self.model = self.ms.state.model
        self.direct = context["direct"]
        self.marks: list[tuple[str, fc.Mark, int]] = []
        self.skipped: list[dict] = []
        for brand in registry.brands:
            for mark in brand.marks:
                if mark.role not in (fc.ROLE_NAME, fc.ROLE_FIGURE):
                    continue
                record = self.ms.state.by_appno.get(mark.appno)
                if record is None or record.pos is None or not mark.image_exists:
                    self.skipped.append({"브랜드": brand.name, "출원번호": mark.appno,
                                         "이유": "색인·이미지 없음"})
                    continue
                self.marks.append((brand.name, mark, record.pos))
        self.matrix = self.ms.state.embeddings[[pos for _, _, pos in self.marks]]
        self.level_note = self._levels_agree()

    def _grade(self, x2: float, level: str = "도형") -> str:
        ms = self.ms
        return ms._judge(ms._image_only_features(x2, level), self.model, level).result.grade  # noqa: SLF001

    def _levels_agree(self) -> dict:
        """이미지만 판단의 유형(도형·결합-도형요부)이 등급을 바꾸지 않는지 — 같으면 OCR 없이
        도형으로 잰다."""
        differ = [x / 1000 for x in range(1001)
                  if self._grade(x / 1000) != self._grade(x / 1000, "결합-도형요부")]
        return {"다른_점": len(differ), "같음": not differ}

    def embed(self, image):
        return self.np.asarray(self.engine.encode_image(image),
                               dtype=self.np.float32).reshape(-1)

    def auto_kind(self, image) -> str:
        from backend.src.core import ocr

        detection = ocr.detect(image, timeout=20.0)
        return KIND_NAMES.get(detection.kind, "유형 모름") if detection else "유형 모름"

    def levels(self, embedding, *, exclude: str | None = None) -> dict[str, dict]:
        """브랜드마다 가장 닮은 표장의 (수준, 유사도, 출원번호). 약함 미만은 뺀다."""
        scores = self.matrix @ embedding
        best: dict[str, tuple[float, fc.Mark]] = {}
        for (brand, mark, _), score in zip(self.marks, scores):
            if mark.appno == exclude:
                continue
            value = round(min(1.0, max(0.0, float(score))), 4)
            if brand not in best or value > best[brand][0]:
                best[brand] = (value, mark)
        out = {}
        for brand, (value, mark) in best.items():
            grade = self._grade(value)
            level = (fc.LEVEL_STRONG if grade == fc.GRADE_RISK
                     else fc.LEVEL_WEAK if grade == fc.GRADE_REVIEW else None)
            if level:
                out[brand] = {"수준": level, "유사도": value, "표장": mark.appno,
                              "표장_이름": mark.title, "역할": mark.role}
        return out

    def query(self, image) -> dict:
        embedding = self.embed(image)
        if self.ms.is_photo_query(embedding):
            return {"사진": True, "일치": {}}
        return {"사진": False, "일치": self.levels(embedding), "embedding": embedding}


def logo_measure(context: dict, registry: fc.Registry, samples: dict, control: dict,
                 limit: dict | None) -> dict:
    logo = Logo(context, registry)
    out: dict = {"표장": len(logo.marks), "건너뜀": logo.skipped, "유형_확인": logo.level_note}
    marks = logo.marks[:limit["로고_표장"]] if limit else logo.marks
    self_rows, cross = [], []
    for brand, mark, _ in marks:
        image = logo.direct((IMAGES_DIR / mark.image).read_bytes())
        result = logo.query(image) if image is not None else {"사진": None, "일치": {}}
        row = {"브랜드": brand, "출원번호": mark.appno, "이름": mark.title, "역할": mark.role,
               "사진": result["사진"]}
        if result["사진"] is False:
            own = result["일치"].get(brand)
            others = logo.levels(result["embedding"], exclude=mark.appno).get(brand)
            row.update(자기_브랜드=(own or {}).get("수준"),
                       자기_빼고=(others or {}).get("수준"),
                       자기_빼고_유사도=(others or {}).get("유사도"))
            for other, hit in result["일치"].items():
                if other != brand:
                    cross.append({"표장_브랜드": brand, "출원번호": mark.appno,
                                  "이름": mark.title, "다른_브랜드": other, **hit})
        self_rows.append(row)
    judged = [r for r in self_rows if r["사진"] is False]
    out["자기_확인"] = {
        "표장": len(self_rows), "사진으로_판정": sum(1 for r in self_rows if r["사진"]),
        "읽지_못함": sum(1 for r in self_rows if r["사진"] is None), "잰_표장": len(judged),
        "자기_브랜드와_강함": sum(1 for r in judged if r["자기_브랜드"] == fc.LEVEL_STRONG),
        "자기_빼고_강함": sum(1 for r in judged if r["자기_빼고"] == fc.LEVEL_STRONG),
        "자기_빼고_약함": sum(1 for r in judged if r["자기_빼고"] == fc.LEVEL_WEAK),
        "자기_빼고_없음": [r for r in judged if not r["자기_빼고"]],
        "사진_목록": [r for r in self_rows if r["사진"]],
        "다른_브랜드와_약함_이상": cross}
    kinds = image_types()
    queries = {query.key: query for query in context["A"]}

    def negatives(name: str, entries: list[tuple[str, Path, str | None]]) -> dict:
        rows, photos, counts = [], 0, Counter()
        for label, path, kind in entries:
            image = logo.direct(path.read_bytes())
            if image is None:
                continue
            result = logo.query(image)
            if result["사진"]:
                photos += 1
                continue
            if kind is None:  # DB 이미지 — 엔진 OCR 로 자동 유형(심결 이미지와 같은 규칙)
                kind = logo.auto_kind(image)
            counts[f"{kind} 잰 것"] += 1
            if result["일치"]:
                strongest = max(result["일치"].items(), key=lambda kv: kv[1]["유사도"])
                counts[f"{kind} {strongest[1]['수준']}"] += 1
                rows.append({"질의": label, "유형": kind, "브랜드": strongest[0],
                             **strongest[1], "그_밖": len(result["일치"]) - 1})
        judged_count = sum(v for k, v in counts.items() if k.endswith("잰 것"))
        return {"이미지": len(entries), "사진으로_판정": photos, "잰_이미지": judged_count,
                "약함_이상": len(rows),
                "비율": round(len(rows) / judged_count, 4) if judged_count else None,
                "유형별": dict(counts), "목록": rows}

    def trial_kind(path: Path) -> str:
        relative = path.resolve().relative_to(TRIALS.resolve()).as_posix()
        return KIND_NAMES.get(kinds.get(relative, ""), "유형 모름")

    keep = limit["로고_음성"] if limit else None
    control_keys = control["대조군"]["이미지"][BASE] + control["대조군"]["이미지"][HOLDOUT]
    out["음성"] = {
        "대조군_덜_닮은_이미지": negatives("대조군", [
            (key, queries[key].path, trial_kind(queries[key].path))
            for key in control_keys[:keep]]),
        "표본A_질의_이미지": negatives("표본A", [
            (query.key, query.path, trial_kind(query.path)) for query in context["A"][:keep]]),
    }
    picked = logo_n1_marks(samples)
    out["음성"]["N1_기준용_상표_이미지"] = negatives("N1", [
        (f"{item['출원번호']} {item['이름']}", IMAGES_DIR / item["이미지"], None)
        for item in picked[:keep]])
    return out


def logo_n1_marks(samples: dict) -> list[dict]:
    """로고 음성의 N1 — 기준용 상표(이미지 파일 있음) 가운데 300(seed 0). 확인용 절반은 이미지도
    건드리지 않는다."""
    pool = sorted({item["출원번호"]: item for item in samples["N1"]
                   if item.get("반") == BASE and item.get("이미지")
                   and (IMAGES_DIR / item["이미지"]).is_file()}.values(),
                  key=lambda item: item["출원번호"])
    return random.Random(f"{SEED}|로고|N1").sample(pool, min(LOGO_N1_IMAGES, len(pool)))


def grade_max(*grades: str | None) -> str | None:
    usable = [grade for grade in grades if grade]
    return max(usable, key=fc.GRADES.index) if usable else None


def preview(context: dict, registry: fc.Registry, matcher: Matcher, thresholds: fc.Thresholds,
            presets, control: dict, limit: int | None) -> list[dict]:
    from scripts import named_shared_threshold as second

    ms, engine = context["ms"], context["engine"]
    goods_map = gm.load_goods_map()
    fruit = sorted({code for name, nice in FRUIT_GOODS
                    for code in goods_map.find(name, nice).similarity_codes})
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
            image=None, note: str = "") -> None:
        data = engine.multi_search(image=image, name=name, goods_codes=codes,
                                   top_k=5).to_dict()
        overall = data["overall"]
        suggested = overall["query_type"].get("suggested_name")
        result = fc.check_famous(name, codes, registry, thresholds, dist=matcher.dist,
                                 goods_floor=matcher.floor, ocr_text=suggested)
        floor = result.floor
        row = {"입력": label, "업종": goods_label, "지금_등급": overall["grade"],
               "지금_위험도": overall["prob"], "지금_1위": (data["candidates"][0]["title"]
                                                    if data["candidates"] else None),
               "일치": match_row(result.strongest),
               "그_밖의_일치": [match_row(m) for m in result.matches[1:3]],
               "OCR_제안": suggested, "바닥": floor,
               "바닥_적용_등급": grade_max(overall["grade"], floor), "안내": notice_of(result),
               "메모": note}
        rows.append(row)

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
        elif preset_id == "과일":
            run(name, name, fruit, "과일 판매(신선한 과실·그 판매업)",
                note="등록부에 없음 — 한계 확인용")
        else:
            codes = _preset_codes(presets, preset_id) if preset_id else None
            note = "P2 확인용 — 지시의 목록이라 계산" if name in PREVIEW_HOLDOUT_SEEN else ""
            if name == "삼성":
                note = "등록부에 없음 — 한계 확인용"
            run(name, name, codes, preset_id or "없음", note=note)
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
                     if mark.role == fc.ROLE_FIGURE and mark.image_exists)
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
        seen = logo.query(image)
        logo_hits = {brand: {k: v for k, v in hit.items()} for brand, hit in seen["일치"].items()}
        best = max(logo_hits.items(), key=lambda kv: kv[1]["유사도"]) if logo_hits else None
        logo_floor = None
        if best:
            logo_floor = (fc.GRADE_RISK if best[1]["수준"] == fc.LEVEL_STRONG
                          else fc.GRADE_REVIEW)
        rows.append({
            "입력": label, "업종": preset_id or "없음", "지금_등급": overall["grade"],
            "지금_위험도": overall["prob"],
            "지금_1위": data["candidates"][0]["title"] if data["candidates"] else None,
            "OCR_제안": suggested, "글자_일치": match_row(result.strongest),
            "글자_기준": result.basis, "글자_바닥": result.floor,
            "사진": seen["사진"],
            "로고_일치": ({"브랜드": best[0], **best[1]} if best else None),
            "로고_바닥(같은 대응을 쓴다면)": logo_floor,
            "바닥_적용_등급": grade_max(overall["grade"], result.floor, logo_floor)})
    return rows


def other_industry_scale(context: dict, presets, control: dict, limit: int | None) -> dict:
    """업종이 다르고(x4 < 결합 하한) 업종 없이 본 짝 판단 등급이 검토 권장 이상인 후보."""
    from scripts import named_goods_product as ngp
    from scripts import named_shared_threshold as second

    ms = context["ms"]
    model = ms.state.model
    floor = float(model["coupling"]["floors"]["x4"])
    review = fc.GRADES.index(fc.GRADE_REVIEW)
    capture = ngp.Capture(ms)
    out: dict = {}

    def measure(name: str, runs: list[tuple[str, dict]]) -> None:
        per_query, grades, in_top, examples = [], Counter(), Counter(), []
        for label, inputs in runs:
            capture.take()
            pooled = ms.search_pool(**inputs)
            features = capture.take()
            hits = 0
            for rank, candidate in enumerate(pooled.candidates, start=1):
                first = features.get(candidate.id)
                if not first or first.get("x4") is None or float(first["x4"]) >= floor:
                    continue
                level = pooled.query_type.type
                pair = ms._judge({**first, "x4": None}, model, level)  # noqa: SLF001
                if fc.GRADES.index(pair.result.grade) < review:
                    continue
                hits += 1
                grades[candidate.grade] += 1
                in_top["앞 5 안" if rank <= 5 else "앞 5 밖"] += 1
                if len(examples) < 10:
                    examples.append({
                        "질의": label, "후보": candidate.title, "출원번호": candidate.id,
                        "순위": rank, "겹침": first["x4"], "짝_등급": pair.result.grade,
                        "짝_위험도": round(pair.result.prob, 3), "최종_등급": candidate.grade,
                        "최종_위험도": round(float(candidate.prob), 3),
                        "집합": candidate.pattern, "규칙": list(candidate.rule_triggers)})
            per_query.append(hits)
        distribution = Counter(per_query)
        out[name] = {
            "질의": len(runs), "후보_수": sum(per_query),
            "있는_질의": sum(1 for value in per_query if value),
            "질의당_분포": {str(k): distribution[k] for k in sorted(distribution)},
            "최종_등급": dict(grades), "앞5": dict(in_top), "예시": examples}

    try:
        names = control["대조군"]["이름"][BASE][:limit]
        measure("지어낸 이름 대조군 기준용(이름+업종)", [
            (item["이름"], {"name": item["이름"], "goods_codes": sorted(item["유사군"])})
            for item in names if item["유사군"]])
        sample = [query for query in context["A"] if query.goods][:limit]
        measure("표본 A 업종 있는 질의(이름+이미지+업종)", [
            (query.key, {"image": context["service"](query.path.read_bytes()),
                         "name": query.name, "goods_codes": sorted(query.goods)})
            for query in sample])
        runs = [(f"{key} {title}", inputs)
                for key, title, inputs in second.scenario_inputs(ms, context["service"])
                if inputs.get("goods_codes")]  # 업종 없는 7종(S3·S4·S5·N1·N3·N4·N5)은 해당 없음
        measure("시나리오 16종 중 업종 있는 것", runs[:limit] if limit else runs)
    finally:
        capture.close()
    return out


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
    """사람이 볼 시트 — 브랜드마다 표기·출원인·업종·보호 범위·근거, 표장 썸네일을 역할별로."""
    order = [fc.ROLE_NAME, fc.ROLE_LOGO, fc.ROLE_FIGURE, fc.ROLE_OTHER, fc.ROLE_EXCLUDED]
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
<p class="sub">shared/famous_registry.json 초안. <span class="warn">주황 테두리</span>는 사람이 볼
"도형"·"다른 이름" 표장입니다. 정한 값은 shared/famous_registry_overrides.json 에 적습니다.</p>"""]
    brands = registry.brands[:limit] if limit else registry.brands
    index = []
    for number, brand in enumerate(brands):
        roles = Counter(mark.role for mark in brand.marks)
        weak = ", ".join(n.text for n in brand.notations if n.weak)
        index.append(
            f'<tr><td class=n><a href="#b{number}">{html.escape(brand.name)}</a></td>'
            f"<td>{html.escape(' · '.join(n.text for n in brand.notations))}</td>"
            f"<td class=n>{brand.preset}</td><td class=n>{roles.get(fc.ROLE_NAME, 0)}</td>"
            f"<td class=n>{roles.get(fc.ROLE_FIGURE, 0) or ''}</td>"
            f"<td class=n>{roles.get(fc.ROLE_OTHER, 0) or ''}</td>"
            f"<td class=n>{html.escape(weak)}</td></tr>")
    parts.append(
        "<div class=scroll><table><tr><th>브랜드</th><th>표기</th><th class=n>업종 세트</th>"
        "<th class=n>이름</th><th class=n>도형</th><th class=n>다른 이름</th>"
        "<th class=n>약한 표기</th></tr>" + "".join(index) + "</table></div>")
    for number, brand in enumerate(brands):
        weak = [n.text for n in brand.notations if n.weak]
        rows = "".join(
            f"<tr><td>{html.escape(n.text)}</td><td class=n>{n.script}</td>"
            f"<td class=n>{n.length}</td>"
            f"<td>{'<span class=flag>약한 표기</span> ' if n.weak else ''}"
            f"{html.escape(_reasons(n))}</td></tr>" for n in brand.notations)
        links = " ".join(f'<a href="{html.escape(url)}">근거</a>' for url in brand.evidence_urls)
        parts.append(
            f'<h2 id="b{number}">{html.escape(brand.name)}</h2><p class=sub>출원인 '
            f"{html.escape(' / '.join(brand.applicants))} · 업종 세트 {brand.preset}"
            f"({html.escape(brand.preset_label or '')}) · 보호 범위 <b>{brand.protection}</b>"
            f" · 식별력 판정 맥락 {brand.goods_source} · {links}<br>"
            f"{html.escape(_strip_urls(brand.evidence))}</p>"
            "<table><tr><th>표기</th><th class=n>문자</th><th class=n>길이</th>"
            f"<th>식별력(유명 예외 뺌)</th></tr>{rows}</table>"
            + (f"<p class=warn>약한 표기: {html.escape(', '.join(weak))}</p>" if weak else ""))
        for role in order:
            marks = [mark for mark in brand.marks if mark.role == role]
            if not marks:
                continue
            look = role in (fc.ROLE_FIGURE, fc.ROLE_OTHER)
            parts.append(f"<h3>{role} {len(marks)}건{' — 확인해 주세요' if look else ''}</h3>"
                         "<div class=marks>")
            for mark in marks:
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


def command_freeze(args) -> int:
    paths = _paths(args.out_dir)
    if paths["rule"].exists() and not args.force:
        print(f"거절: {paths['rule']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    registry, _, _, _, samples = _load_static()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    paths["samples"].write_text(json.dumps(samples, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    frozen = {"설정_sha256": rule_sha256(), "스크립트_sha256": file_sha256(Path(__file__)),
              "표본_sha256": canonical_sha256(samples), "표본_수": sample_summary(samples),
              "확인용과_겹치는_이름": holdout_overlap(samples),
              "입력_sha256": {k: file_sha256(p) for k, p in _inputs().items()},
              "등록부": {"브랜드": len(registry.brands),
                       "표장": sum(len(b.marks) for b in registry.brands)},
              "고정": _now(), "설정": _settings()}
    paths["rule"].write_text(json.dumps(frozen, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    print(f"설정 sha256 {frozen['설정_sha256']} · 스크립트 sha256 {frozen['스크립트_sha256']} · "
          f"표본 sha256 {frozen['표본_sha256']}")
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
                     "표본_수": sample_summary(samples),
                     "확인용과_겹치는_이름": holdout_overlap(samples),
                     "약한_표기_브랜드": samples["약한_표기_브랜드"]}
    began = time.perf_counter()
    p1 = base_items(samples["P1"])
    if smoke:
        keep = {brand.name for brand in registry.brands[:cut["P1_브랜드"]]}
        p1 = [item for item in p1 if item["브랜드"] in keep]
    p2_all = base_items(samples["P2"], cut.get("P2", 0) * 2 or None)
    p2 = [item for item in p2_all if not item["약한_표기_브랜드"]]
    p2_excluded = [item for item in p2_all if item["약한_표기_브랜드"]]
    p3 = base_items(samples["P3"])
    if smoke:
        keep_notations = sorted({(i["브랜드"], i["표기"]) for i in p3})[:cut["P3_표기"]]
        p3 = [item for item in p3 if (item["브랜드"], item["표기"]) in keep_notations]
    n1 = base_items(samples["N1"], cut.get("N1"))
    n2 = base_items(samples["N2"], cut.get("N2"))
    n3 = base_items(samples["N3"], cut.get("N3", 0) * 2 or None)
    n4 = base_items(samples["N4"], cut.get("N4"))
    for item in p1 + p2_all + p3 + n1 + n2 + n3 + n4:
        matcher.evidence(item)
    results["계산한_질의"] = {"P1": len(p1), "P2": len(p2), "P2_제외(약한 표기 브랜드)":
                          len(p2_excluded), "P3": len(p3), "N1": len(n1), "N2": len(n2),
                          "N3": len(n3), "N4": len(n4)}
    tick("일치 근거", began)

    began = time.perf_counter()
    selection = select_thresholds(matcher, n1, n3)
    thresholds = fc.Thresholds.from_dict(selection["고른_기준"])
    results["기준_선택"] = selection
    results["P1"] = p1_table(matcher, p1, thresholds)
    results["P2"] = recall_table(matcher, p2, thresholds)
    results["P2_제외(약한 표기 브랜드)"] = recall_table(matcher, p2_excluded, thresholds)
    results["P3"] = recall_table(matcher, p3, thresholds)
    results["N1"] = match_list(matcher, n1, thresholds)
    results["N2"] = match_list(matcher, n2, thresholds)
    results["N3"] = match_list(matcher, n3, thresholds)
    results["N4"] = {"행": [
        {"이름": item["이름"],
         "일치": match_row(matcher.decide(item, thresholds).strongest),
         "그_밖": [match_row(m) for m in matcher.decide(item, thresholds).matches[1:3]],
         "바닥": matcher.decide(item, thresholds).floor} for item in n4]}
    tick("기준 선택·표", began)

    began = time.perf_counter()
    context = load_context()
    tick("엔진", began)
    began = time.perf_counter()
    results["로고"] = logo_measure(context, registry, samples, control, cut or None)
    tick("로고", began)
    began = time.perf_counter()
    results["미리_보기"] = preview(context, registry, matcher, thresholds, presets, control,
                               cut.get("미리_보기"))
    results["미리_보기_이미지"] = preview_images(context, registry, matcher, thresholds, presets,
                                          control, 1 if smoke else None)
    tick("미리 보기", began)
    began = time.perf_counter()
    results["다른_업종_규모"] = other_industry_scale(context, presets, control, cut.get("규모"))
    tick("다른 업종 규모", began)
    began = time.perf_counter()
    review_path = (args.out_dir / "review.html") if smoke else (REVIEW_DIR / "review.html")
    results["확인용_시트"] = review_html(registry, review_path, 2 if smoke else None)
    tick("확인용 시트", began)
    results.update(시간_s=timing, 걸린_시간_s=round(time.perf_counter() - started, 1), 끝=_now())
    paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    paths["report"].write_text(report_text(results), encoding="utf-8")
    print(json.dumps({"고른_기준": selection["고른_기준"]}, ensure_ascii=False))
    print(f"→ {paths['results']}")
    return 0


def report_text(results: dict) -> str:
    chosen = results["기준_선택"]["고른_기준"]
    lines = [f"# 유명 상표 확인 1단계 측정 ({results.get('끝', '')})", "",
             f"- 설정 sha256 `{results['설정_sha256']}`, 스모크 {results['스모크']}, 기본 모델 "
             f"{results['기본_모델']}",
             f"- 고른 기준: {json.dumps(chosen, ensure_ascii=False)}",
             f"- 계산한 질의: {json.dumps(results['계산한_질의'], ensure_ascii=False)}"]
    for name in ("P2", "P3"):
        lines.append(f"- {name} 기준용: {json.dumps(results[name]['전체'], ensure_ascii=False)}")
    for name in ("N1", "N2", "N3"):
        part = results[name]
        lines.append(f"- {name}: 질의 {part['질의']} 중 일치 {part['일치한_질의']} — "
                     f"{json.dumps(part['수준'], ensure_ascii=False)}")
    lines.append(f"- P1: {results['P1']['n']} 중 강함 {results['P1']['강함']}")
    lines.append(f"- 확인용 시트: {results['확인용_시트']['경로']}")
    return "\n".join(lines) + "\n"


def command_sheet(args) -> int:
    """확인용 시트만 다시 만든다(측정 없음 — 등록부·overrides 를 고친 뒤)."""
    target = (args.out_dir / "review.html") if args.out_dir != TRIALS else (
        REVIEW_DIR / "review.html")
    print(json.dumps(review_html(fc.load_registry(), target), ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("freeze", "run", "sheet"))
    parser.add_argument("--out-dir", type=Path, default=TRIALS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--smoke", action="store_true",
                        help="구현 확인 — 일부 표본만(다른 --out-dir 에)")
    args = parser.parse_args(argv)
    return {"freeze": command_freeze, "run": command_run,
            "sheet": command_sheet}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
