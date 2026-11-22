"""손그림 입력(실험 기능) 실현성 — 사람이 그리지 않고 자동으로 확인한다. 평가 전용(서비스
코드·서비스 색인 불변), KIPRIS 호출 0.

시험 1(같은 로고 찾기): 유형 사전(ml/data/types.json) 기준 도형·결합-도형요부이고 사진이 아닌
DB 상표에서 외곽선 추적으로 손그림 세 단계(L1 깔끔·L2 보통·L3 거침)를 만들어 검색한다.
적중 = 원래 로고(엄격), 또는 같은 출원인이면서 원래 로고와 CLIP 유사도 0.95 이상인 상표(인정).
시험 2(같은 대상 찾기): Google Quick, Draw! 의 인식된 낙서를 공식 비엔나 분류(WIPO VCL 9판)로
대응한 범주마다 100장 — 상위 5 중 같은 분류 상표의 비율 대 DB 전체의 그 분류 비율(배수).
비교: (A) 서비스 전체 이미지 색인 그대로 (B) DB 이미지를 윤곽선 그림(Canny 경계, 손그림과 같은
선 굵기)으로 바꾼 임시 색인(데이터 폴더에만 둔다).

    ml/venv/bin/python ml/scripts/sketch_feasibility.py fetch   # 분류표·범주 목록·낙서 일부
    ml/venv/bin/python ml/scripts/sketch_feasibility.py freeze  # 설정 고정(검색 전) → config.json
    ml/venv/bin/python ml/scripts/sketch_feasibility.py run     # 고정본과 같을 때만 잰다

결과(비공개 데이터 폴더): ml/data/experiments/sketch_feasibility/ — config.json, results.json,
report.md, review.html(확인용 페이지), index_b/(임시 색인), quickdraw/(낙서 표본·출처 표기),
inputs/(분류표·범주 목록).

출처: Quick, Draw! Dataset — Google, CC BY 4.0
(https://github.com/googlecreativelab/quickdraw-dataset). Vienna Classification 9th edition
(2023-01-01) — © WIPO (https://www.wipo.int/classifications/vienna/).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import math
import os
import random
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
for _root in (ML_ROOT, REPO_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

DATA = ML_ROOT / "data"
OUT = DATA / "experiments" / "sketch_feasibility"
METADATA = DATA / "kipris_metadata.json"
INDEX = DATA / "index" / "kipris.faiss"
INDEX_META = DATA / "index" / "kipris_metadata.json"
TYPES = DATA / "types.json"
IMAGES = DATA / "images"
ALIASES = REPO_ROOT / "shared" / "applicant_aliases.json"
PHOTO_DIRECTION = REPO_ROOT / "shared" / "model" / "photo_direction_v1.json"

EXPERIMENT = "sketch_feasibility_v1"
SEED = 0
EXIT_REFUSED = 4  # 고정본과 다름·덮어쓰기 거절
EXIT_FETCH = 5  # 내려받기 실패 — 멈추고 보고

# ---- 입력(인터넷 공개 자료 — KIPRIS 아님) -------------------------------------------------------
VCL_URL = ("https://www.wipo.int/classifications/data/vienna/ITSupport_and_download_area/"
           "20230101/Reference/vcl_9_20230101.zip")
VCL_ZIP = "vcl_9_20230101.zip"
VCL_MEMBER = "vcl_9_20230101/en/full.xml"
QD_CATEGORIES_URL = ("https://raw.githubusercontent.com/googlecreativelab/quickdraw-dataset/"
                     "master/categories.txt")
QD_CATEGORIES = "quickdraw_categories.txt"
QD_URL = "https://storage.googleapis.com/quickdraw_dataset/full/simplified/{}.ndjson"
QD_FETCH = {"구간_수": 8, "구간_바이트": 65536,
            "방식": "HTTP Range — 파일 크기(HEAD)를 8등분한 위치에서 64 KiB 씩, 잘린 첫·끝 줄 버림"}
USER_AGENT = "sketch-feasibility/1.0"
ATTRIBUTION = (
    "Quick, Draw! Dataset — Google, Inc. Creative Commons Attribution 4.0 International "
    "(https://creativecommons.org/licenses/by/4.0/). "
    "출처: https://github.com/googlecreativelab/quickdraw-dataset")

# ---- 시험 설정(측정 전에 고정 — freeze 가 config.json 에 적는다) ---------------------------------
TARGET_SAMPLE = 200  # 시험 1 대상 수(가능한 대상이 이보다 적으면 전부, seed 0 순서)
TARGET_LEVELS = ("도형", "결합-도형요부")
REPRESENTATIVES = 20  # 확인용 페이지 대표(시험 1 단계별·시험 2 범주별)
DOODLES_PER_CATEGORY = 100
MIN_CLASS_MARKS = 10
LENIENT_MIN_COSINE = 0.95
TOP_KS = (1, 5, 20)
TEST2_TOP = 5
BOOTSTRAP = {"반복": 10000, "seed": SEED, "신뢰수준": 0.95, "방식": "백분위",
             "시험1_단위": "대상", "시험2_단위": "범주"}
DECISION = {
    "통과": ("방법마다 ① 시험 1 L2 인정 기준 상위 5 적중률 ≥ 0.50 ② 시험 2 배수 ≥ 2.0 "
             "③ 시험 2 배수의 95% 신뢰구간 하한 > 1.0(= 기준선보다 높음)"),
    "판정": ("통과한 방법이 있으면 진행(둘 다면 L2 인정 상위 5 적중률이 높은 쪽, 같으면 A), "
             "없으면 보류"),
    "시험2_배수": ("범주 평균 상위 5 같은 분류 비율 ÷ 범주 평균 기준 비율(기준 비율 = 색인 "
                   "전체에서 그 분류 상표의 비율), 범주 단위 부트스트랩"),
    "참고만": "L1·L3, 엄격 기준, 상위 1·20, 범주별 배수와 그 중앙값, 함께 볼 것",
    "L2_하한": 0.50, "배수_하한": 2.0, "배수_신뢰구간_하한": 1.0,
}

RENDER = {"캔버스_px": 512, "그림_긴변_px": 448, "선_굵기_px": 4, "잉크_문턱": 128,
          "선": "cv2.polylines(굵기 4, LINE_8 — 실제 폭 5px) 검정 · 흰 배경",
          "정규화": ("좌표의 외접 상자 긴 변을 448−선 굵기로 맞춰 512 캔버스 가운데"
                     "(여백 자르기·정사각형 패딩)")}
FOREGROUND = {"작업_긴변_px": 1024, "배경": "테두리 1px 의 RGB 중앙값",
              "거리": "배경색과의 RGB 유클리드 거리 ÷ 441.67 × 255", "문턱": "Otsu",
              "문턱_범위": [24, 128], "작은_조각_면적_비율": 0.0002,
              "정규화": "전경 외접 상자를 잘라 배경색으로 정사각형 패딩 → 긴 변 448 → 512 캔버스"}
SKETCH = {
    "방법": ("외곽선 추적 — 전경 마스크의 경계를 cv2.findContours(RETR_LIST, "
             "CHAIN_APPROX_NONE)로 따라가 다각선으로 그린다(방법 B 의 밝기 기울기 경계 검출과 "
             "다른 과정)"),
    "최소_윤곽_길이_px": 12,
    "L1": {"단순화_px": 0.75},
    "L2": {"작은_부분_대각_비율": 0.10, "작은_부분_생략_확률": 0.5, "단순화_px": 3.5,
           "재표본_간격_px": 4, "흔들림_px": 2.0, "흔들림_평활_점": 3, "회전_도": 10,
           "가로세로_배율": [0.9, 1.1]},
    "L3": {"바탕": "L2 의 생략·단순화·흔들림·회전·배율을 그대로 쓰고 아래를 더한다",
           "추가_흔들림_px": 3.4641, "비틀림_px": 12.0, "비틀림_격자": 4,
           "누락_비율": [0.20, 0.30], "누락_길이_px": [16, 40]},
    "난수": "numpy default_rng(sha256('sketch_feasibility_v1|0|<출원번호>|<단계>') 앞 8바이트)",
}
METHOD_B = {"방법": ("Canny 경계 → 5×5 팽창(손그림 선과 같은 실제 폭 5px) → 흰 배경 검은 선, "
                    "잉크 외접 상자로 여백 자르기"),
            "흐림_시그마": 1.0, "문턱": [50, 150], "L2_기울기": True, "최소_조각_화소": 12,
            "팽창_px": 5,
            "전경_못_찾음": "이미지 전체를 같은 상자에 넣고 경계 검출", "빈_그림": "색인에서 뺀다"}
MAX_RGB_DISTANCE = 441.6729559300637  # sqrt(3) * 255

# ---- 범주 대응표(VCL 9판 영문 공식 이름, 측정 전에 고정) ------------------------------------
MAPPING_RULES = (
    "M1 후보: Quick, Draw! 범주 이름(단·복수)이 VCL 9판 영문 공식 이름(중분류 제목·주 구분·"
    "보조 구분)에 낱말로 나온다.",
    "M2 같은 뜻만: 동음이의(다른 물건)와 수식어로만 나오는 항목(그 대상이 그림의 주제가 아닌 것 — "
    "말 탄 사람, 컵에 담긴 수프, 집이 있는 풍경 등)은 뺀다.",
    "M3 분류 단위: 대상이 중분류 제목의 첫 항목이면 그 중분류 전체에서 제목의 다른 항목에 속하는 "
    "구분만 뺀다(종·변형 구분이 대상 이름을 갖지 않아도 들어가게 — 새의 독수리·닭 등). 아니면 "
    "M2 를 통과한 구분(주·보조)의 합집합.",
    "M4 겹침: 두 범주의 분류가 겹치면 그 중분류 제목의 첫 항목인 범주가 갖고, 다른 범주는 겹치지 "
    "않는 구분만 남긴다.",
    "M5 DB 건수: 서비스 색인 전체 상표 중 숫자 비엔나 코드 하나라도 그 분류에 드는 상표가 10건 "
    "이상인 범주만.",
    "분류 소속: 상표의 숫자 비엔나 코드(6자리) 중 하나라도 분류에 들면 그 분류 상표(VCL 9판 표에 "
    "없는 코드도 중분류 앞 4자리가 맞으면 중분류 단위 분류에 든다).",
)
MAPPING = (
    {"범주": "star", "단위": "중분류", "중분류": "0101", "뺌": [],
     "근거": "1.1 STARS, COMETS 첫 항목. 혜성만의 구분 없음(1.1.15 는 꼬리 달린 별)"},
    {"범주": "bird", "단위": "중분류", "중분류": "0307", "뺌": ["030723"],
     "근거": "3.7 BIRDS, BATS 첫 항목. 박쥐만의 구분 3.7.23 Bats 를 뺌"},
    {"범주": "tree", "단위": "중분류", "중분류": "0501", "뺌": [],
     "근거": "5.1 TREES, BUSHES 첫 항목. 덤불만의 구분 없음"},
    {"범주": "leaf", "단위": "중분류", "중분류": "0503",
     "뺌": ["050317", "050318", "050319", "050320", "050322"],
     "근거": "5.3 LEAVES, NEEDLES, BRANCHES… 첫 항목. 가지(5.3.17–5.3.20)·바늘잎(5.3.22)을 뺌"},
    {"범주": "flower", "단위": "중분류", "중분류": "0505", "뺌": [],
     "근거": "5.5 FLOWERS, BLOSSOMS 첫 항목"},
    {"범주": "mountain", "단위": "중분류", "중분류": "0601", "뺌": ["060101", "060107"],
     "근거": ("6.1 MOUNTAINS, ROCKS, GROTTOES 첫 항목. 바위(6.1.1)·동굴(6.1.7)을 뺌"
              "(화산 6.1.3 은 산)")},
    {"범주": "crown", "단위": "중분류", "중분류": "2409", "뺌": ["240904"],
     "근거": "24.9 CROWNS, DIADEMS 첫 항목. 24.9.4 Diadems 를 뺌"},
    {"범주": "circle", "단위": "중분류", "중분류": "2601", "뺌": ["260109"],
     "근거": "26.1 CIRCLES, ELLIPSES 첫 항목. 타원이 주인 구분(26.1.9)을 뺌"},
    {"범주": "triangle", "단위": "중분류", "중분류": "2603", "뺌": ["260323"],
     "근거": "26.3 TRIANGLES, LINES FORMING AN ANGLE 첫 항목. 각을 이룬 선(26.3.23)을 뺌"},
    {"범주": "line", "단위": "중분류", "중분류": "2611", "뺌": [],
     "근거": "26.11 LINES, BANDS 첫 항목. 띠만의 구분 없음"},
    {"범주": "bear", "단위": "구분", "구분": ["030114"],
     "뺀_후보": {"011104": "큰곰·작은곰자리 — 별자리(다른 뜻)"},
     "근거": "3.1.14 Bears, koalas, wombats. 3.1 제목에서 BEARS 는 첫 항목이 아님"},
    {"범주": "lightning", "단위": "구분", "구분": ["011503"], "뺀_후보": {},
     "근거": "1.15.3 Lightning"},
    {"범주": "tornado", "단위": "구분", "구분": ["011523"], "뺀_후보": {},
     "근거": "1.15.23 Vortices, rotary movements, tornadoes"},
    {"범주": "smiley face", "단위": "구분", "구분": ["040507"], "뺀_후보": {},
     "근거": "4.5.7 Smiley faces"},
    {"범주": "cup", "단위": "구분", "구분": ["110301", "110304"],
     "뺀_후보": {"031102": "뱀과 컵 — 약국 상징(수식어)", "080701": "컵에 담긴 수프·음료(수식어)",
              "191313": "생리컵(다른 물건)"},
     "근거": "11.3.1 Drinking vessels, cups (trophies) + 보조 11.3.4 Cups, cups with saucers"},
    {"범주": "house", "단위": "구분", "구분": ["070108", "070109", "070110", "070112"],
     "뺀_후보": {"060706": "평지붕 집으로 된 시가지 — 풍경(수식어)",
              "061916": "집이 있는 풍경(수식어)"},
     "근거": "7.1.8 Houses, skyscrapers + 보조 7.1.9·7.1.10·7.1.12(집 종류)"},
    {"범주": "hand", "단위": "구분", "구분": ["020914", "020915", "020916"],
     "뺀_후보": {"020133": "허리에 손 얹은 남자(사람이 대상)",
              "020333": "허리에 손 얹은 여자(사람이 대상)",
              "140711": "손 드릴(다른 물건)", "170102": "시계 바늘(다른 뜻)",
              "170103": "시계 바늘(다른 뜻)", "170105": "시계 바늘(다른 뜻)"},
     "근거": "2.9.14 Hands, folded hands, fingers… + 보조 2.9.15 Open hands·2.9.16 Hands joined"},
    {"범주": "fork", "단위": "구분", "구분": ["110101", "110104", "110105"],
     "뺀_후보": {"071110": "갈림길(다른 뜻)", "110323": "식기가 놓인 접시(수식어)",
              "220122": "소리굽쇠(다른 물건)"},
     "근거": "11.1.1 Knives, forks and spoons + 보조 11.1.4 Forks·11.1.5 Sets(수저 세트)"},
)
# 느슨하게 모은 후보(M1 만)로는 10건 이상이지만 쓰지 않는 범주 — 빠짐없이 적는다
# (check_mapping 이 검사).
EXCLUDED = {
    "bat": {"규칙": "M4", "사유": "3.7 은 새(bird)가 첫 항목. 박쥐만의 구분은 3.7.23 Bats 뿐",
            "남는_분류": {"단위": "구분", "구분": ["030723"]}},
    "bush": {"규칙": "M4", "사유": "5.1 은 나무(tree)가 첫 항목. 덤불만의 구분 없음",
             "남는_분류": {"단위": "구분", "구분": []}},
    "zigzag": {"규칙": "M4",
               "사유": ("26.11.13 Wavy lines…, zigzag lines… 는 26.11(line)의 보조 구분. "
                      "그 밖은 배경 무늬(25.7.23)·글자 모양(27.1.13)"),
               "남는_분류": {"단위": "구분", "구분": []}},
    "face": {"규칙": "M2",
             "사유": ("Smiley faces(4.5.7)는 따로 있는 smiley face 범주의 대상. 사람 얼굴 "
                    "자체를 이름으로 가진 구분 없음(1.1.20 등은 의인화한 별·해·달)"),
             "남는_분류": {"단위": "구분", "구분": []}},
    "knife": {"규칙": "M3",
              "사유": "11.1 첫 항목이지만 포크·숟가락·주방용품에 속하는 구분을 빼면 셋만 남음",
              "남는_분류": {"단위": "구분", "구분": ["110101", "110103", "110105"]}},
    "spoon": {"규칙": "M3", "사유": "11.1 첫 항목 아님 — 숟가락을 이름으로 가진 구분",
              "남는_분류": {"단위": "구분", "구분": ["110101", "110102", "110105"]}},
    "cloud": {"규칙": "M2",
              "사유": "구름 있는 해·지구·달(1.3.10·1.5.10·1.7.10)은 해·지구·달이 대상",
              "남는_분류": {"단위": "구분", "구분": ["011511"]}},
    "pig": {"규칙": "M3", "사유": "3.4 제목의 첫 항목 아님 — 돼지를 이름으로 가진 구분",
            "남는_분류": {"단위": "구분", "구분": ["030418", "030420"]}},
    "scorpion": {"규칙": "M3", "사유": "3.9 제목의 첫 항목 아님 — 3.9.16 Crustaceans…, scorpions",
                 "남는_분류": {"단위": "구분", "구분": ["030916"]}},
    "skull": {"규칙": "M3",
              "사유": ("2.9 제목의 첫 항목 아님 — 2.9.23 Skulls. 3.6 은 네발짐승의 머리뼈"
                     "(다른 대상)"),
              "남는_분류": {"단위": "구분", "구분": ["020923"]}},
    "spider": {"규칙": "M3", "사유": "3.13 제목의 첫 항목 아님 — 거미를 이름으로 가진 구분",
               "남는_분류": {"단위": "구분", "구분": ["031308", "031321", "031324", "031325"]}},
    "square": {"규칙": "M2",
               "사유": "광장(6.7.2)·제도용 자(17.5.9)·네모난 빵·과자·치즈·삽은 다른 뜻·수식어",
               "남는_분류": {"단위": "구분", "구분": ["260401", "260403"]}},
    "wheel": {"규칙": "M2",
              "사유": ("바퀴 달린 마차(18.1.2·18.1.3)·물레(15.3)는 다른 대상. 15.7 WHEELS, "
                     "BEARINGS 첫 항목"),
              "남는_분류": {"단위": "중분류", "중분류": "1507", "뺌": []}},
}
IRREGULAR_PLURALS = {"knife": ("knives",), "leaf": ("leaves",), "mouse": ("mice",),
                     "foot": ("feet",), "tooth": ("teeth",), "goose": ("geese",),
                     "wolf": ("wolves",)}


class Refused(RuntimeError):
    """고정한 설정과 다르거나 결과를 덮어쓰려 할 때."""


class FetchFailed(RuntimeError):
    """필요한 자료를 받지 못함 — 멈추고 보고한다."""


# ---- 비엔나 분류표(VCL) ------------------------------------------------------------------------

@dataclass(frozen=True)
class VclEntry:
    code: str  # 중분류 4자리(예 "0101"), 구분 6자리(예 "010102")
    kind: str  # "중분류" | "주" | "보조"
    name: str
    associated: tuple[str, ...] = ()  # 보조 구분이 딸린 주 구분(6자리)


def _plain_text(element) -> str:
    """요소의 글자(하위 <note> 는 빼고 <ref> 등은 넣는다), 공백 정리."""
    parts = [element.text or ""]
    for child in element:
        if child.tag != "note":
            parts.append(_plain_text(child))
        parts.append(child.tail or "")
    return " ".join("".join(parts).split())


def _dotted_code(text: str) -> str:
    return "".join(f"{int(part):02d}" for part in text.split("."))


def parse_vcl(xml_bytes: bytes) -> dict[str, VclEntry]:
    """WIPO VCL 참조 XML(full.xml) → {코드: 항목}. 중분류·주 구분·보조 구분(딸린 주 구분 포함)."""
    root = ET.fromstring(xml_bytes)
    entries: dict[str, VclEntry] = {}
    for category in root.iter("category"):
        category_id = int(category.get("id"))
        for division in category.findall("division"):
            code = f"{category_id:02d}{int(division.get('id')):02d}"
            entries[code] = VclEntry(code, "중분류", " ".join((division.get("text") or "").split()))
            for section in division.findall("section"):
                section_code = f"{code}{int(section.get('id')):02d}"
                entries[section_code] = VclEntry(section_code, "주", _plain_text(section))
            for block in division.findall("auxiliaries"):
                head = block.find("head")
                linked = tuple(_dotted_code(found) for found in re.findall(
                    r"\d+\.\d+\.\d+", _plain_text(head))) if head is not None else ()
                for auxiliary in block.findall("auxiliary"):
                    aux_code = f"{code}{int(auxiliary.get('id')):02d}"
                    entries[aux_code] = VclEntry(aux_code, "보조", _plain_text(auxiliary), linked)
    if not entries:
        raise ValueError("VCL XML 에 분류 항목이 없습니다")
    return entries


def read_vcl_zip(path: Path) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read(VCL_MEMBER)


def word_pattern(word: str) -> re.Pattern:
    forms = {word, word + "s", word + "es", *IRREGULAR_PLURALS.get(word, ())}
    if word.endswith("y"):
        forms.add(word[:-1] + "ies")
    alternatives = "|".join(re.escape(form) for form in sorted(forms, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z])(?:{alternatives})(?![A-Za-z])", re.IGNORECASE)


def first_item(title: str) -> str:
    """중분류 제목의 첫 항목 — 첫 쉼표·괄호·쌍반점 앞."""
    return re.split(r"[,(;]", title, maxsplit=1)[0].strip()


def dotted(code: str) -> str:
    return ".".join(str(int(code[i:i + 2])) for i in range(0, len(code), 2))


def class_member(codes, spec: dict) -> bool:
    """숫자 비엔나 코드 집합이 분류(중분류 − 뺌 / 구분 합집합)에 드는가."""
    if spec["단위"] == "중분류":
        minus = set(spec.get("뺌") or ())
        return any(code[:4] == spec["중분류"] and code not in minus for code in codes)
    sections = set(spec["구분"])
    return any(code in sections for code in codes)


def candidates(word: str, entries: dict[str, VclEntry]) -> list[VclEntry]:
    pattern = word_pattern(word)
    return [entry for entry in entries.values() if entry.name and pattern.search(entry.name)]


def loose_class(found: list[VclEntry]) -> dict:
    """M1 후보 전부(뜻·단위 판단 없이) — 빠짐 검사용."""
    return {"단위": "느슨", "중분류": sorted({e.code for e in found if e.kind == "중분류"}),
            "구분": sorted({e.code for e in found if e.kind != "중분류"})}


def loose_member(codes, loose: dict) -> bool:
    divisions = tuple(loose["중분류"])
    return any(code in set(loose["구분"]) or (divisions and code.startswith(divisions))
               for code in codes)


def check_mapping(entries: dict[str, VclEntry], categories: list[str],
                  mark_codes: list[frozenset[str]], mapping=MAPPING, excluded=EXCLUDED,
                  minimum: int = MIN_CLASS_MARKS) -> list[dict]:
    """대응표를 분류표·범주 목록·DB 와 대조하고 범주별 건수를 낸다. 어긋나면 ValueError.

    - 범주가 실제 Quick, Draw! 범주인가, 코드가 VCL 9판에 있는가
    - 중분류 단위: 범주 이름이 제목의 첫 항목인가, 뺀 구분이 그 중분류 안인가
    - 구분 단위: 쓴 구분마다 이름에 범주 이름이 있는가, 이름에 범주 이름이 나오는 다른 구분은
      모두 '뺀_후보'에 사유와 함께 있는가
    - 서로 겹치는 분류가 없는가(M4), 쓴 범주는 DB 10건 이상인가(M5)
    - M1 후보만으로 10건 이상인 범주는 모두 대응표나 EXCLUDED 에 있는가
    """
    problems: list[str] = []
    known = set(categories)
    rows = []
    for spec in mapping:
        word = spec["범주"]
        pattern = word_pattern(word)
        if word not in known:
            problems.append(f"{word}: Quick, Draw! 범주 목록에 없음")
        if spec["단위"] == "중분류":
            division = entries.get(spec["중분류"])
            if division is None or division.kind != "중분류":
                problems.append(f"{word}: 중분류 {spec['중분류']} 없음")
                continue
            if not pattern.fullmatch(first_item(division.name)):
                problems.append(f"{word}: '{division.name}' 의 첫 항목이 아님")
            for code in spec["뺌"]:
                if code not in entries or code[:4] != spec["중분류"]:
                    problems.append(f"{word}: 뺀 구분 {code} 가 중분류 밖이거나 없음")
            names = {spec["중분류"]: division.name}
            names.update({code: entries[code].name for code in spec["뺌"] if code in entries})
        else:
            for code in spec["구분"]:
                entry = entries.get(code)
                if entry is None or entry.kind == "중분류":
                    problems.append(f"{word}: 구분 {code} 없음")
                elif not pattern.search(entry.name):
                    problems.append(f"{word}: {dotted(code)} '{entry.name}' 에 범주 이름 없음")
            seen = {e.code for e in candidates(word, entries) if e.kind != "중분류"}
            unexplained = seen - set(spec["구분"]) - set(spec.get("뺀_후보") or {})
            if unexplained:
                problems.append(f"{word}: 사유 없이 빠진 후보 {sorted(unexplained)}")
            names = {code: entries[code].name for code in spec["구분"] if code in entries}
        count = sum(1 for codes in mark_codes if class_member(codes, spec))
        if count < minimum:
            problems.append(f"{word}: DB {count}건 < {minimum}")
        rows.append({"범주": word, "분류": {k: v for k, v in spec.items()
                                          if k in ("단위", "중분류", "뺌", "구분")},
                     "공식_이름": {dotted(code): name for code, name in names.items()},
                     "뺀_후보": {dotted(code): reason
                               for code, reason in (spec.get("뺀_후보") or {}).items()},
                     "근거": spec["근거"], "DB_건수": count,
                     "기준_비율": count / len(mark_codes)})
    for index, left in enumerate(mapping):
        for right in mapping[index + 1:]:
            if _overlap(left, right, entries):
                problems.append(f"{left['범주']}·{right['범주']}: 분류가 겹침(M4)")
    mapped = {spec["범주"] for spec in mapping}
    for word in categories:
        found = candidates(word, entries)
        if not found or word in mapped:
            continue
        loose = loose_class(found)
        if sum(1 for codes in mark_codes if loose_member(codes, loose)) >= minimum \
                and word not in excluded:
            problems.append(f"{word}: M1 후보 {minimum}건 이상인데 대응표·EXCLUDED 어디에도 없음")
    if problems:
        raise ValueError("범주 대응표 검사 실패:\n- " + "\n- ".join(problems))
    return rows


def _codes_of(spec: dict, entries: dict[str, VclEntry]) -> set[str]:
    if spec["단위"] == "중분류":
        minus = set(spec.get("뺌") or ())
        return {code for code in entries if len(code) == 6 and code[:4] == spec["중분류"]
                and code not in minus}
    return set(spec["구분"])


def _overlap(left: dict, right: dict, entries: dict[str, VclEntry]) -> bool:
    return bool(_codes_of(left, entries) & _codes_of(right, entries))


def excluded_rows(entries: dict[str, VclEntry], mark_codes: list[frozenset[str]],
                  excluded=EXCLUDED) -> dict:
    out = {}
    for word, item in excluded.items():
        found = candidates(word, entries)
        loose = loose_class(found)
        remain = item["남는_분류"]
        out[word] = {"규칙": item["규칙"], "사유": item["사유"],
                     "M1_후보_건수": sum(1 for c in mark_codes if loose_member(c, loose)),
                     "남는_분류_건수": sum(1 for c in mark_codes if class_member(c, remain))
                     if remain.get("구분") or remain.get("중분류") else 0}
    return out


# ---- DB·대상 -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Mark:
    appno: str
    image: str
    applicant: str
    codes: frozenset[str]
    name: str
    position: int  # 서비스 색인 순번


def load_marks(metadata: Path = METADATA, index_meta: Path = INDEX_META) -> list[Mark]:
    records = json.loads(metadata.read_text(encoding="utf-8"))["trademarks"]
    by_image = {str(record["이미지파일"]): record for record in records}
    image_paths = json.loads(index_meta.read_text(encoding="utf-8"))["image_paths"]
    marks = []
    for position, image in enumerate(image_paths):
        record = by_image[image]
        codes = frozenset(str(code) for code in (record.get("비엔나코드") or [])
                          if re.fullmatch(r"\d{6}", str(code)))
        name = (str(record.get("상표한글명") or "").strip()
                or str(record.get("상표영문명") or "").strip())
        marks.append(Mark(str(record["출원번호"]), image, str(record.get("출원인") or ""),
                          codes, name, position))
    return marks


def target_level(kind: str | None, name: str) -> str | None:
    """유형 사전의 표시 유형 → 통합 모델 네 수준(요부를 모르면 이름 유무 — 계약 v2 §2-4 5항)."""
    from src.mark_type import model_type

    if kind not in ("문자", "도형", "결합"):
        return None
    return model_type(kind, "", has_name=bool(name))


def eligible_targets(marks: list[Mark], types: dict, photo: list[bool]) -> tuple[list[str], dict]:
    counts: dict[str, int] = {}
    eligible = []
    for mark in marks:
        level = target_level((types.get(mark.appno) or {}).get("type"), mark.name)
        key = f"{level}{'·사진' if photo[mark.position] else ''}"
        counts[key] = counts.get(key, 0) + 1
        if level in TARGET_LEVELS and not photo[mark.position]:
            eligible.append(mark.appno)
    return eligible, dict(sorted(counts.items()))


def order_targets(eligible: list[str], size: int = TARGET_SAMPLE, seed: int = SEED) -> list[str]:
    """seed 0 표본(가능한 대상이 size 보다 적으면 전부를 seed 0 순서로)."""
    pool = sorted(eligible)
    return random.Random(seed).sample(pool, min(size, len(pool)))


def lenient_sets(targets: list[str], marks: list[Mark], vectors: np.ndarray,
                 aliases_path: Path = ALIASES) -> dict[str, list[str]]:
    """인정 적중 집합 — 같은 출원인(정규화 + 별칭 표)이면서 원래 로고와 CLIP 유사도 ≥ 0.95 인
    다른 상표."""
    from scripts.nameless_search_thresholds import load_aliases, split_applicants

    aliases = load_aliases(aliases_path)
    owners = [split_applicants(mark.applicant, aliases) for mark in marks]
    by_appno = {mark.appno: mark for mark in marks}
    out = {}
    for appno in targets:
        target = by_appno[appno]
        similarity = vectors @ vectors[target.position]
        out[appno] = sorted(
            mark.appno for mark in marks
            if mark.appno != appno and owners[mark.position] & owners[target.position]
            and float(similarity[mark.position]) >= LENIENT_MIN_COSINE)
    return out


# ---- 그림 만들기(순수 함수 — 시험 대상) ---------------------------------------------------

def _seed_int(*parts) -> int:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def level_rng(key: str, level: str) -> np.random.Generator:
    return np.random.default_rng(_seed_int(EXPERIMENT, SEED, key, level))


def _downscale(rgb: np.ndarray, max_side: int) -> np.ndarray:
    height, width = rgb.shape[:2]
    scale = max_side / max(height, width)
    if scale >= 1:
        return rgb
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)


def background_color(rgb: np.ndarray) -> np.ndarray:
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]).astype(np.float32)
    return np.median(border, axis=0)


def distance_map(rgb: np.ndarray, background: np.ndarray) -> np.ndarray:
    diff = rgb.astype(np.float32) - background.astype(np.float32)
    distance = np.sqrt((diff * diff).sum(axis=-1)) / MAX_RGB_DISTANCE * 255.0
    return np.clip(np.rint(distance), 0, 255).astype(np.uint8)


def _threshold(distance: np.ndarray) -> int:
    value, _ = cv2.threshold(distance, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    low, high = FOREGROUND["문턱_범위"]
    return int(min(max(value, low), high))


def _clean(mask: np.ndarray, min_area: float) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    keep = np.zeros(count, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    return keep[labels]


def _place(square: np.ndarray, fill) -> np.ndarray:
    """정사각형 그림을 긴 변 448 로 맞춰 512 캔버스 가운데에."""
    canvas_px, box = RENDER["캔버스_px"], RENDER["그림_긴변_px"]
    side = square.shape[0]
    interpolation = cv2.INTER_AREA if side > box else cv2.INTER_CUBIC
    resized = cv2.resize(square, (box, box), interpolation=interpolation)
    shape = (canvas_px, canvas_px) + square.shape[2:]
    canvas = np.empty(shape, dtype=np.uint8)
    canvas[...] = fill
    offset = (canvas_px - box) // 2
    canvas[offset:offset + box, offset:offset + box] = resized
    return canvas


def _pad_square(image: np.ndarray, fill) -> np.ndarray:
    height, width = image.shape[:2]
    side = max(height, width)
    square = np.empty((side, side) + image.shape[2:], dtype=np.uint8)
    square[...] = fill
    top, left = (side - height) // 2, (side - width) // 2
    square[top:top + height, left:left + width] = image
    return square


def normalized_logo(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """원본 RGB → (512 캔버스 RGB, 전경 마스크). 전경을 못 찾으면 None.

    배경 = 테두리 중앙값, 전경 = 배경색과의 거리 > Otsu 문턱([24, 128]), 작은 조각 제거 → 전경 외접
    상자로 자르고 배경색으로 정사각형 패딩 → 긴 변 448 → 512 캔버스 가운데.
    """
    rgb = _downscale(rgb, FOREGROUND["작업_긴변_px"])
    background = background_color(rgb)
    distance = distance_map(rgb, background)
    threshold = _threshold(distance)
    area_frac = FOREGROUND["작은_조각_면적_비율"]
    mask = _clean(distance > threshold, area_frac * distance.size)
    if not mask.any():
        return None
    ys, xs = np.nonzero(mask)
    crop = rgb[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    fill = np.rint(background).astype(np.uint8)
    canvas = _place(_pad_square(crop, fill), fill)
    canvas_mask = _clean(distance_map(canvas, background) > threshold,
                         area_frac * canvas.shape[0] * canvas.shape[1])
    if not canvas_mask.any():
        return None
    return canvas, canvas_mask


def letterboxed(rgb: np.ndarray) -> np.ndarray:
    """전경을 못 찾을 때 — 이미지 전체를 같은 상자에."""
    rgb = _downscale(rgb, FOREGROUND["작업_긴변_px"])
    fill = np.rint(background_color(rgb)).astype(np.uint8)
    return _place(_pad_square(rgb, fill), fill)


def trace_outlines(mask: np.ndarray) -> list[np.ndarray]:
    """전경 마스크의 경계(바깥·구멍)를 외곽선 추적으로 — 닫힌 다각선 목록(캔버스 좌표)."""
    contours, _ = cv2.findContours(mask.astype(np.uint8) * 255, cv2.RETR_LIST,
                                   cv2.CHAIN_APPROX_NONE)
    out = []
    for contour in contours:
        if cv2.arcLength(contour, True) >= SKETCH["최소_윤곽_길이_px"]:
            out.append(contour[:, 0, :].astype(np.float64))
    return out


def simplify(points: np.ndarray, epsilon: float, closed: bool = True) -> np.ndarray:
    approx = cv2.approxPolyDP(points.astype(np.float32).reshape(-1, 1, 2), epsilon, closed)
    return approx[:, 0, :].astype(np.float64)


def path_length(points: np.ndarray, closed: bool) -> float:
    path = np.vstack([points, points[:1]]) if closed else points
    if len(path) < 2:
        return 0.0
    return float(np.hypot(*np.diff(path, axis=0).T).sum())


def resample(points: np.ndarray, step: float, closed: bool) -> np.ndarray:
    path = np.vstack([points, points[:1]]) if closed else points
    lengths = np.hypot(*np.diff(path, axis=0).T)
    total = float(lengths.sum())
    if total <= 0:
        return points[:1].copy()
    count = max(int(math.ceil(total / step)), 3 if closed else 2)
    targets = np.linspace(0.0, total, count, endpoint=not closed)
    cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
    return np.stack([np.interp(targets, cumulative, path[:, 0]),
                     np.interp(targets, cumulative, path[:, 1])], axis=1)


def jitter(points: np.ndarray, rng: np.random.Generator, amount: float, smooth: float,
           closed: bool) -> np.ndarray:
    """매끈한 흔들림 — 점마다 가우스 잡음을 평활한 뒤 변위 크기의 RMS 를 amount(px)로."""
    from scipy.ndimage import gaussian_filter1d

    if amount <= 0 or len(points) < 2:
        return points.copy()
    noise = rng.standard_normal(points.shape)
    noise = gaussian_filter1d(noise, sigma=smooth, axis=0, mode="wrap" if closed else "nearest")
    rms = float(np.sqrt((noise * noise).sum(axis=1).mean()))
    return points + (noise / rms * amount if rms > 0 else 0.0)


def omit_small(polylines: list[np.ndarray], rng: np.random.Generator, diag_frac: float,
               probability: float) -> list[np.ndarray]:
    """작은 부분(외접 상자 대각 < 그림 긴 변 × diag_frac)을 확률적으로 생략 — 가장 긴 윤곽은
    남긴다."""
    limit = diag_frac * RENDER["그림_긴변_px"]
    lengths = [path_length(points, True) for points in polylines]
    longest = int(np.argmax(lengths)) if lengths else -1
    kept = []
    for index, points in enumerate(polylines):
        span = points.max(axis=0) - points.min(axis=0)
        small = float(np.hypot(*span)) < limit
        draw = rng.random()
        if small and index != longest and draw < probability:
            continue
        kept.append(points)
    return kept


def affine(polylines: list[np.ndarray], angle_deg: float, scale_x: float,
           scale_y: float) -> list[np.ndarray]:
    stacked = np.vstack(polylines)
    center = (stacked.min(axis=0) + stacked.max(axis=0)) / 2
    theta = math.radians(angle_deg)
    rotation = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    matrix = rotation @ np.diag([scale_x, scale_y])
    return [(points - center) @ matrix.T + center for points in polylines]


def warp(polylines: list[np.ndarray], rng: np.random.Generator, amount: float,
         grid: int) -> list[np.ndarray]:
    """저주파 비틀림 — (grid+1)² 격자점의 무작위 변위(표준편차 amount px)를 3차 스플라인으로
    보간."""
    from scipy.ndimage import map_coordinates

    nodes = rng.standard_normal((grid + 1, grid + 1, 2)) * amount
    canvas_px = RENDER["캔버스_px"]
    out = []
    for points in polylines:
        u = np.clip(points[:, 0] / canvas_px * grid, 0, grid)
        v = np.clip(points[:, 1] / canvas_px * grid, 0, grid)
        shift = np.stack([map_coordinates(nodes[..., axis], [v, u], order=3, mode="nearest")
                          for axis in (0, 1)], axis=1)
        out.append(points + shift)
    return out


def dropout(polylines: list[np.ndarray], rng: np.random.Generator, fraction_range,
            gap_range) -> tuple[list[np.ndarray], float]:
    """선 누락 — 전체 길이의 U(fraction_range) 비율이 될 때까지 길이에 비례해 고른 위치에서
    U(gap_range) px 구간을 지운다. 닫힌 다각선(재표본 점) → 열린 조각들, 실제 지운 비율."""
    target = float(rng.uniform(*fraction_range))
    segments = []
    for points in polylines:
        following = np.roll(points, -1, axis=0)
        segments.append(np.hypot(*(following - points).T))
    lengths = np.array([float(seg.sum()) for seg in segments])
    total = float(lengths.sum())
    removed = [np.zeros(len(seg), dtype=bool) for seg in segments]
    if total <= 0:
        return [points.copy() for points in polylines], 0.0
    removed_length = 0.0
    for _ in range(100000):
        if removed_length >= target * total:
            break
        which = int(rng.choice(len(segments), p=lengths / total))
        start = float(rng.uniform(0, lengths[which]))
        gap = float(rng.uniform(*gap_range))
        seg = segments[which]
        starts = np.concatenate([[0.0], np.cumsum(seg)[:-1]])
        offset = (starts - start) % lengths[which]
        removed[which] |= offset < gap
        removed_length = float(sum(seg[mask].sum() for seg, mask in zip(segments, removed)))
    pieces = []
    for points, mask in zip(polylines, removed):
        count = len(points)
        if not mask.any():
            pieces.append(np.vstack([points, points[:1]]))
            continue
        begin = int(np.argmax(mask))  # 지운 구간에서 시작해 한 바퀴
        run: list[np.ndarray] = []
        for step in range(count):
            index = (begin + step) % count
            if mask[index]:
                if len(run) >= 2:
                    pieces.append(np.array(run))
                run = []
            else:
                if not run:
                    run.append(points[index])
                run.append(points[(index + 1) % count])
        if len(run) >= 2:
            pieces.append(np.array(run))
    return pieces, removed_length / total


@dataclass
class Drawing:
    polylines: list[np.ndarray]
    closed: list[bool]
    info: dict


def make_sketches(mask: np.ndarray, key: str) -> dict[str, Drawing]:
    """전경 마스크 → L1·L2·L3 손그림(다각선). key(출원번호)와 단계로 난수를 고정한다."""
    outlines = trace_outlines(mask)
    if not outlines:
        return {}
    level1 = [p for p in (simplify(o, SKETCH["L1"]["단순화_px"]) for o in outlines) if len(p) >= 2]
    p2, p3 = SKETCH["L2"], SKETCH["L3"]
    rng2 = level_rng(key, "L2")
    kept = omit_small(outlines, rng2, p2["작은_부분_대각_비율"], p2["작은_부분_생략_확률"])
    base = []
    for points in kept:
        simple = simplify(points, p2["단순화_px"])
        if len(simple) < 2:
            continue
        dense = resample(simple, p2["재표본_간격_px"], True)
        base.append(jitter(dense, rng2, p2["흔들림_px"], p2["흔들림_평활_점"], True))
    angle = float(rng2.uniform(-p2["회전_도"], p2["회전_도"]))
    scale_x = float(rng2.uniform(*p2["가로세로_배율"]))
    scale_y = float(rng2.uniform(*p2["가로세로_배율"]))
    level2 = affine(base, angle, scale_x, scale_y)
    rng3 = level_rng(key, "L3")
    rough = [jitter(points, rng3, p3["추가_흔들림_px"], p2["흔들림_평활_점"], True)
             for points in base]
    rough = affine(warp(rough, rng3, p3["비틀림_px"], p3["비틀림_격자"]), angle, scale_x, scale_y)
    pieces, removed = dropout(rough, rng3, p3["누락_비율"], p3["누락_길이_px"])
    shared = {"윤곽_수": len(outlines), "회전_도": round(angle, 3),
              "배율": [round(scale_x, 4), round(scale_y, 4)]}
    return {
        "L1": Drawing(level1, [True] * len(level1), {"윤곽_수": len(level1)}),
        "L2": Drawing(level2, [True] * len(level2), {**shared, "남은_윤곽": len(level2)}),
        "L3": Drawing(pieces, [False] * len(pieces),
                      {**shared, "남은_윤곽": len(base), "조각": len(pieces),
                       "누락_비율": round(removed, 4)}),
    }


def doodle_drawing(strokes) -> Drawing:
    """Quick, Draw! simplified 획([[x…], [y…]]) → 열린 다각선."""
    polylines = []
    for stroke in strokes:
        if len(stroke) >= 2 and len(stroke[0]) >= 1:
            polylines.append(np.column_stack([np.asarray(stroke[0], dtype=np.float64),
                                              np.asarray(stroke[1], dtype=np.float64)]))
    return Drawing(polylines, [False] * len(polylines), {"획": len(polylines)})


def fit_polylines(polylines: list[np.ndarray]) -> list[np.ndarray]:
    """여백 자르기·정사각형 패딩을 좌표에서 — 외접 상자 긴 변을 448−선 굵기로, 512 캔버스 가운데."""
    stacked = np.vstack(polylines)
    low, high = stacked.min(axis=0), stacked.max(axis=0)
    span = float((high - low).max())
    scale = (RENDER["그림_긴변_px"] - RENDER["선_굵기_px"]) / span if span > 0 else 1.0
    center = (low + high) / 2
    middle = RENDER["캔버스_px"] / 2
    return [(points - center) * scale + middle for points in polylines]


def render(drawing: Drawing) -> np.ndarray | None:
    """다각선 → 512×512 회색조(흰 배경 255·검은 선 0, cv2 굵기 4 = 실제 폭 5px). 선이 없으면
    None."""
    polylines = [points for points in drawing.polylines if len(points)]
    if not polylines:
        return None
    canvas_px, width = RENDER["캔버스_px"], RENDER["선_굵기_px"]
    canvas = np.full((canvas_px, canvas_px), 255, dtype=np.uint8)
    closed = [flag for points, flag in zip(drawing.polylines, drawing.closed) if len(points)]
    for points, is_closed in zip(fit_polylines(polylines), closed):
        pixels = np.rint(points).astype(np.int32)
        if len(pixels) == 1:
            cv2.circle(canvas, tuple(int(v) for v in pixels[0]), width // 2, 0, -1)
        else:
            cv2.polylines(canvas, [pixels.reshape(-1, 1, 2)], is_closed, 0, width, cv2.LINE_8)
    return canvas


def finalize_raster(gray: np.ndarray) -> np.ndarray | None:
    """래스터 선 그림의 여백 자르기·정사각형 패딩 — 잉크 외접 상자를 긴 변 448 로, 512 가운데."""
    ink = gray < RENDER["잉크_문턱"]
    if not ink.any():
        return None
    ys, xs = np.nonzero(ink)
    crop = gray[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return _place(_pad_square(crop, 255), 255)


def contour_drawing(rgb: np.ndarray) -> tuple[np.ndarray | None, str]:
    """방법 B — DB 이미지 → 윤곽선 그림(Canny 경계, 12화소 미만 조각 제거, 5px 폭으로 팽창, 흰
    배경 검은 선)."""
    normalized = normalized_logo(rgb)
    canvas, how = (normalized[0], "전경") if normalized is not None else (letterboxed(rgb), "전체")
    gray = cv2.cvtColor(canvas, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (0, 0), METHOD_B["흐림_시그마"])
    low, high = METHOD_B["문턱"]
    edges = cv2.Canny(blurred, low, high, L2gradient=METHOD_B["L2_기울기"])
    edges = (_clean(edges > 0, METHOD_B["최소_조각_화소"]) * 255).astype(np.uint8)
    width = METHOD_B["팽창_px"]
    ink = cv2.dilate(edges, np.ones((width, width), dtype=np.uint8))
    return finalize_raster(np.where(ink > 0, 0, 255).astype(np.uint8)), how


def drawing_stats(gray: np.ndarray) -> dict:
    """잉크 비율·그림 영역(외접 상자·볼록 껍질이 긴 변 정사각형을 채우는 비율)·선 굵기 중앙값."""
    from skimage.morphology import skeletonize

    ink = gray < RENDER["잉크_문턱"]
    if not ink.any():
        return {"잉크": 0.0, "상자_채움": 0.0, "껍질_채움": 0.0, "선_굵기_px": 0.0}
    ys, xs = np.nonzero(ink)
    width, height = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
    side = max(width, height)
    hull = cv2.convexHull(np.column_stack([xs, ys]).astype(np.int32))
    distance = cv2.distanceTransform(ink.astype(np.uint8), cv2.DIST_L2, 5)
    skeleton = skeletonize(ink)
    stroke = float(np.median(distance[skeleton]) * 2) if skeleton.any() else 0.0
    return {"잉크": round(float(ink.mean()), 5),
            "상자_채움": round(width * height / side ** 2, 4),
            "껍질_채움": round(float(cv2.contourArea(hull)) / side ** 2, 4),
            "선_굵기_px": round(stroke, 2)}


def png_bytes(gray: np.ndarray, size: int | None = None) -> bytes:
    from PIL import Image

    image = Image.fromarray(gray).convert("RGB")
    if size is not None:
        image = image.resize((size, size), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


# ---- Quick, Draw! 부분 내려받기 -----------------------------------------------------------------

def plan_ranges(size: int, chunks: int, chunk_bytes: int) -> list[tuple[int, int]]:
    """파일 크기를 chunks 등분한 위치의 [시작, 끝] 바이트(끝 포함). 작은 파일은 한 번에."""
    if size <= chunks * chunk_bytes:
        return [(0, size - 1)]
    last = size - chunk_bytes
    starts = [round(index * last / (chunks - 1)) for index in range(chunks)]
    return [(start, start + chunk_bytes - 1) for start in starts]


def parse_chunk(data: bytes, start: int, end: int, size: int) -> tuple[list[dict], int]:
    """바이트 구간 → 완전한 줄의 레코드(잘린 첫 줄·끝 줄 버림), 읽지 못한 줄 수."""
    pieces = data.split(b"\n")
    if start > 0:
        pieces = pieces[1:]
    if end < size - 1:
        pieces = pieces[:-1]
    records, bad = [], 0
    for piece in pieces:
        if not piece.strip():
            continue
        try:
            records.append(json.loads(piece))
        except ValueError:
            bad += 1
    return records, bad


def pick_doodles(records: list[dict], word: str, count: int = DOODLES_PER_CATEGORY,
                 seed: int = SEED) -> tuple[list[dict], int]:
    """인식된(recognized) 그 범주 낙서를 key_id 로 중복 제거·정렬해 seed 0 으로 count 장."""
    pool = {}
    for record in records:
        if record.get("recognized") is True and record.get("word") == word:
            pool.setdefault(str(record["key_id"]), record)
    ordered = [pool[key] for key in sorted(pool, key=int)]
    if len(ordered) < count:
        raise FetchFailed(f"{word}: 인식된 낙서 {len(ordered)}장 < {count}")
    return random.Random(seed).sample(ordered, count), len(ordered)


def _request(url: str, method: str = "GET", headers: dict | None = None):
    request = urllib.request.Request(url, method=method,
                                     headers={"User-Agent": USER_AGENT, **(headers or {})})
    return urllib.request.urlopen(request, timeout=60)


def download(url: str, path: Path) -> None:
    try:
        with _request(url) as response:
            data = response.read()
    except Exception as exc:  # noqa: BLE001 — 받지 못하면 멈춘다
        raise FetchFailed(f"{url}: {exc}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def fetch_category(word: str, out_dir: Path) -> dict:
    url = QD_URL.format(urllib.parse.quote(word))
    try:
        with _request(url, "HEAD") as response:
            size = int(response.headers["Content-Length"])
        records, bad, fetched = [], 0, 0
        ranges = plan_ranges(size, QD_FETCH["구간_수"], QD_FETCH["구간_바이트"])
        for start, end in ranges:
            with _request(url, headers={"Range": f"bytes={start}-{end}"}) as response:
                if response.status != 206 and (start, end) != (0, size - 1):
                    raise FetchFailed(f"{word}: 부분 응답이 아님(HTTP {response.status})")
                data = response.read()
            fetched += len(data)
            got, missing = parse_chunk(data, start, end, size)
            records += got
            bad += missing
    except FetchFailed:
        raise
    except Exception as exc:  # noqa: BLE001 — 받지 못하면 멈춘다
        raise FetchFailed(f"{word}: {exc}") from exc
    picked, pool = pick_doodles(records, word)
    path = out_dir / f"{word.replace(' ', '_')}.ndjson"
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in picked),
                    encoding="utf-8")
    return {"범주": word, "url": url, "파일_바이트": size, "받은_바이트": fetched,
            "구간": ranges, "줄": len(records), "읽지_못한_줄": bad, "인식된_후보": pool,
            "표본": len(picked), "파일": path.name}


def doodle_path(word: str) -> Path:
    return OUT / "quickdraw" / f"{word.replace(' ', '_')}.ndjson"


def read_doodles(word: str) -> list[dict]:
    path = doodle_path(word)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ---- 지표 -------------------------------------------------------------------------------------

def bootstrap_indices(count: int, reps: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, count, size=(reps, count))


def mean_ci(values: np.ndarray, indices: np.ndarray, level: float = 0.95) -> list[float]:
    means = values[indices].mean(axis=1)
    tail = (1 - level) / 2 * 100
    return [float(np.percentile(means, tail)), float(np.percentile(means, 100 - tail))]


def ratio_of_means(rates: np.ndarray, bases: np.ndarray, indices: np.ndarray,
                   level: float = 0.95) -> tuple[float, list[float]]:
    point = float(rates.sum() / bases.sum())
    resampled = rates[indices].sum(axis=1) / bases[indices].sum(axis=1)
    tail = (1 - level) / 2 * 100
    return point, [float(np.percentile(resampled, tail)),
                   float(np.percentile(resampled, 100 - tail))]


def first_rank(ranked: list[str], wanted: set[str]) -> int | None:
    for rank, appno in enumerate(ranked, start=1):
        if appno in wanted:
            return rank
    return None


def decide(test1: dict, test2: dict, rule: dict = DECISION) -> dict:
    """미리 고정한 판정 — 방법마다 통과 여부, 통과한 방법이 있으면 진행."""
    methods = {}
    for method in test1:
        level2 = test1[method]["L2"]["인정"]["5"]["비율"]
        multiple = test2[method]["배수"]
        lower = test2[method]["배수_CI"][0]
        checks = {"시험1_L2_인정_상위5": level2 >= rule["L2_하한"],
                  "시험2_배수": multiple >= rule["배수_하한"],
                  "시험2_CI_하한": lower > rule["배수_신뢰구간_하한"]}
        methods[method] = {"L2_인정_상위5": level2, "배수": multiple, "배수_CI_하한": lower,
                           "조건": checks, "통과": all(checks.values())}
    passed = [method for method, item in methods.items() if item["통과"]]
    if not passed:
        return {"방법": methods, "판정": "보류", "고른_방법": None}
    best = max(passed, key=lambda method: (methods[method]["L2_인정_상위5"], method == "A"))
    return {"방법": methods, "판정": "진행", "고른_방법": best}


def percentiles(values) -> dict:
    array = np.asarray(list(values), dtype=np.float64)
    if not array.size:
        return {}
    return {f"p{q}": round(float(np.percentile(array, q)), 4) for q in (5, 25, 50, 75, 95)}


# ---- 설정 고정 -------------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def settings_sha256(settings: dict) -> str:
    return hashlib.sha256(canonical(settings).encode("utf-8")).hexdigest()


def first_difference(left, right, path: str = "설정") -> str | None:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                return f"{path}.{key}"
            found = first_difference(left[key], right[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return f"{path}(길이 {len(left)} ≠ {len(right)})"
        for index, (a, b) in enumerate(zip(left, right)):
            found = first_difference(a, b, f"{path}[{index}]")
            if found:
                return found
        return None
    return None if left == right else path


def check_frozen(frozen: dict, current: dict) -> None:
    """고정본(config.json)이 손대지 않은 그대로이고 지금 다시 계산한 설정과 같은지. 다르면
    Refused."""
    if settings_sha256(frozen["설정"]) != frozen["sha256"]:
        raise Refused("config.json 의 설정이 고정 때 해시와 다릅니다(손으로 고침?)")
    current = json.loads(canonical(current))
    if canonical(current) != canonical(frozen["설정"]):
        raise Refused(f"지금 설정이 고정본과 다릅니다: {first_difference(frozen['설정'], current)}")


def _git(*args: str, cwd: Path = REPO_ROOT) -> str:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


class Service:
    """서비스와 같은 경로 — 업로드 디코더 → src.embedding.encode_image, FAISS 내적 검색,
    사진 판정."""

    def __init__(self):
        # src.search 가 torch 를 faiss 보다 먼저 올린다(ml/src/search.py 주석) — 순서 무관
        from src import contracts, embedding, photo_mark
        from src import search as search_module
        from src.preprocess import DEFAULT_PREPROCESS_VERSION, preprocess_image

        from backend.src.core import validation

        self.embedding, self.search_module, self.photo_mark = embedding, search_module, photo_mark
        self.validation, self.preprocess_image = validation, preprocess_image
        self.direction, self.threshold = photo_mark.load_direction(PHOTO_DIRECTION)
        self.index_a = search_module.load_index(INDEX)
        self.vectors = self.index_a.reconstruct_n(0, self.index_a.ntotal)
        self.contract = {"디코더": "backend.src.core.validation.validate_and_decode",
                         "인코더": "src.embedding.encode_image",
                         "전처리_계약": DEFAULT_PREPROCESS_VERSION,
                         "모델": f"{contracts.MODEL_NAME}/{contracts.PRETRAINED}",
                         "검색": "FAISS IndexFlatIP(정규화 벡터 내적 = 코사인)",
                         "사진_판정": (f"src.photo_mark({PHOTO_DIRECTION.name}, "
                                    f"문턱 {self.threshold})")}

    def is_photo(self, vector: np.ndarray) -> bool:
        return bool(self.photo_mark.is_photo(vector, direction=self.direction,
                                             threshold=self.threshold))

    def encode(self, gray: np.ndarray) -> np.ndarray:
        image = self.validation.validate_and_decode(png_bytes(gray))
        return np.asarray(self.embedding.encode_image(image), dtype=np.float32)

    def load_rgb(self, path: Path) -> np.ndarray:
        return np.asarray(self.preprocess_image(path, validate_content=False), dtype=np.uint8)

    def ranked(self, index, positions: list[str], vector: np.ndarray, k: int):
        scores, found = self.search_module.search(index, vector, k)
        return [(positions[int(i)], round(float(s), 5)) for s, i in zip(scores, found)]


def load_inputs() -> dict:
    inputs = OUT / "inputs"
    vcl_path, categories_path = inputs / VCL_ZIP, inputs / QD_CATEGORIES
    if not vcl_path.exists() or not categories_path.exists():
        raise Refused("입력이 없습니다 — 먼저 fetch")
    entries = parse_vcl(read_vcl_zip(vcl_path))
    categories = [line.strip() for line in categories_path.read_text(encoding="utf-8").splitlines()
                  if line.strip()]
    return {"entries": entries, "categories": categories, "vcl": vcl_path,
            "categories_path": categories_path}


def collect_settings(service: Service | None) -> tuple[dict, dict]:
    """고정할 설정 전부(대상·손그림 방식과 매개변수·대응표·지표·판정)와 실행에 쓸 자료."""
    inputs = load_inputs()
    marks = load_marks()
    mark_codes = [mark.codes for mark in marks]
    mapping_rows = check_mapping(inputs["entries"], inputs["categories"], mark_codes)
    types = json.loads(TYPES.read_text(encoding="utf-8"))["types"]
    if service is None:
        service = Service()
    if service.index_a.ntotal != len(marks):
        raise Refused(f"색인 {service.index_a.ntotal}건 ≠ 메타 {len(marks)}건")
    photo = [service.is_photo(vector) for vector in service.vectors]
    eligible, type_counts = eligible_targets(marks, types, photo)
    targets = order_targets(eligible)
    lenient = lenient_sets(targets, marks, service.vectors)
    doodles = {}
    plan = json.loads((OUT / "quickdraw" / "fetch_plan.json").read_text(encoding="utf-8"))
    for row in mapping_rows:
        word = row["범주"]
        path = doodle_path(word)
        if not path.exists():
            raise Refused(f"{word} 낙서가 없습니다 — 먼저 fetch")
        records = read_doodles(word)
        doodles[word] = {"key_id": [str(record["key_id"]) for record in records],
                         "sha256": sha256_file(path),
                         "인식된_후보": plan["범주"][word]["인식된_후보"]}
    index_meta = json.loads(INDEX_META.read_text(encoding="utf-8"))
    settings = {
        "실험": EXPERIMENT, "seed": SEED,
        "입력": {
            "kipris_metadata.json": sha256_file(METADATA),
            "index/kipris.faiss": sha256_file(INDEX),
            "index/kipris_metadata.json": sha256_file(INDEX_META),
            "types.json": sha256_file(TYPES),
            "shared/applicant_aliases.json": sha256_file(ALIASES),
            "shared/model/photo_direction_v1.json": sha256_file(PHOTO_DIRECTION),
            VCL_ZIP: sha256_file(inputs["vcl"]), QD_CATEGORIES: sha256_file(
                inputs["categories_path"]),
            "색인_세대": index_meta.get("generation_id"), "색인_상표_수": len(marks),
            "분류표": f"{VCL_URL} → {VCL_MEMBER}", "낙서": QD_URL.format("<범주>"),
        },
        "서비스_경로": service.contract,
        "렌더": RENDER, "전경": FOREGROUND, "손그림": SKETCH, "방법B": METHOD_B,
        "시험1": {
            "대상_규칙": ("유형 사전(types.json) 표시 유형 → 통합 모델 수준(요부를 모르면 "
                       "이름이 있으면 결합-문자요부·없으면 결합-도형요부)이 도형·결합-도형요부"
                       "이고, 서비스 색인 벡터의 사진 판정이 아닌 DB 상표. seed 0 으로 200개"
                       "(적으면 전부를 seed 0 순서로)"),
            "유형_집계": type_counts, "가능_대상_수": len(eligible), "표본_크기": TARGET_SAMPLE,
            "대상": targets, "대표": targets[:REPRESENTATIVES],
            "적중": {"엄격": "원래 로고(같은 출원번호)",
                     "인정": (f"원래 로고, 또는 같은 출원인(정규화 + {ALIASES.name}) 이면서 "
                              f"원래 로고와 CLIP 유사도(서비스 색인 벡터 내적) ≥ "
                              f"{LENIENT_MIN_COSINE}")},
            "인정_집합": lenient,
            "인정_집합_있는_대상": sum(1 for value in lenient.values() if value),
            "상위": list(TOP_KS),
        },
        "시험2": {
            "대응_규칙": list(MAPPING_RULES), "분류표": "WIPO VCL 9판(2023-01-01) 영문 참조 XML",
            "대응표": mapping_rows, "뺀_범주": excluded_rows(inputs["entries"], mark_codes),
            "최소_DB_건수": MIN_CLASS_MARKS, "내려받기": QD_FETCH,
            "낙서_수": DOODLES_PER_CATEGORY, "낙서": doodles, "대표": REPRESENTATIVES,
            "상위": TEST2_TOP,
            "지표": ("범주마다 낙서 100장의 (상위 5 중 그 분류 상표 수 ÷ 5) 평균 = 같은 분류 비율, "
                   "기준 비율 = 색인 전체에서 그 분류 상표의 비율"),
        },
        "부트스트랩": BOOTSTRAP, "판정": DECISION,
    }
    context = {"marks": marks, "service": service, "photo": photo, "inputs": inputs}
    return json.loads(canonical(settings)), context


# ---- 실행 ------------------------------------------------------------------------------------

def command_fetch(args) -> int:
    inputs = OUT / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    for url, name in ((VCL_URL, VCL_ZIP), (QD_CATEGORIES_URL, QD_CATEGORIES)):
        if args.refresh or not (inputs / name).exists():
            download(url, inputs / name)
    entries = parse_vcl(read_vcl_zip(inputs / VCL_ZIP))
    categories = [line.strip() for line in
                  (inputs / QD_CATEGORIES).read_text(encoding="utf-8").splitlines()
                  if line.strip()]
    marks = load_marks()
    rows = check_mapping(entries, categories, [mark.codes for mark in marks])
    out_dir = OUT / "quickdraw"
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / "fetch_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {
        "범주": {}}
    for row in rows:
        word = row["범주"]
        if not args.refresh and word in plan["범주"] and doodle_path(word).exists():
            continue
        plan["범주"][word] = fetch_category(word, out_dir)
        print(f"{word}: 받은 {plan['범주'][word]['받은_바이트']:,}B / 파일 "
              f"{plan['범주'][word]['파일_바이트']:,}B, 인식된 후보 "
              f"{plan['범주'][word]['인식된_후보']}")
    plan["방식"] = QD_FETCH
    plan["받은_날"] = datetime.now(timezone.utc).date().isoformat()
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out_dir / "ATTRIBUTION.md").write_text(
        "# 출처\n\n" + ATTRIBUTION + "\n\n이 폴더에는 범주마다 인식된 낙서 100장만 있다"
        "(원본 그대로, simplified ndjson). 전체 자료는 받지 않았다 — fetch_plan.json 의 바이트 "
        "구간만.\n",
        encoding="utf-8")
    print(f"범주 {len(rows)}개: {', '.join(row['범주'] for row in rows)}")
    return 0


def command_freeze(args) -> int:
    path = OUT / "config.json"
    if path.exists() and not args.force:
        raise Refused(f"{path} 가 이미 있습니다 — 고정본은 덮어쓰지 않습니다(--force 는 다시 고정)")
    settings, _ = collect_settings(None)
    frozen = {"설정": settings, "sha256": settings_sha256(settings),
              "고정_시각": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "git": {"HEAD": _git("rev-parse", "HEAD"), "브랜치": _git("branch", "--show-current"),
                      "ml/data": _git("rev-parse", "HEAD", cwd=DATA),
                      "스크립트_sha256": sha256_file(Path(__file__))}}
    path.write_text(json.dumps(frozen, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (OUT / "config.sha256").write_text(frozen["sha256"] + "  config.json#설정\n", encoding="utf-8")
    t1, t2 = settings["시험1"], settings["시험2"]
    print(f"고정: sha256 {frozen['sha256']}")
    print(f"시험 1 대상 {len(t1['대상'])}(가능 {t1['가능_대상_수']}), 인정 집합 있는 대상 "
          f"{t1['인정_집합_있는_대상']}")
    print("시험 2 범주: " + ", ".join(f"{row['범주']} {row['DB_건수']}" for row in t2["대응표"]))
    return 0


def _positions_b(service: Service, marks: list[Mark], out_dir: Path) -> tuple:
    drawings_dir = out_dir / "drawings"
    drawings_dir.mkdir(parents=True, exist_ok=True)
    vectors, positions, stats, how_counts, blank = [], [], [], {"전경": 0, "전체": 0}, []
    for mark in marks:
        gray, how = contour_drawing(service.load_rgb(IMAGES / mark.image))
        how_counts[how] += 1
        if gray is None:
            blank.append(mark.appno)
            continue
        (drawings_dir / f"{mark.appno}.png").write_bytes(png_bytes(gray))
        vector = service.encode(gray)
        vectors.append(vector)
        positions.append(mark.appno)
        stats.append({**drawing_stats(gray), "사진": service.is_photo(vector)})
    index = service.search_module.build_index(np.stack(vectors))
    service.search_module.save_index(index, out_dir / "contour.faiss")
    (out_dir / "positions.json").write_text(json.dumps(positions) + "\n", encoding="utf-8")
    return index, positions, stats, {"전경_정규화": how_counts, "빈_그림": blank}


def command_run(args) -> int:
    frozen_path = OUT / "config.json"
    if not frozen_path.exists():
        raise Refused("고정본이 없습니다 — 먼저 freeze")
    results_path = OUT / "results.json"
    if results_path.exists() and not args.force:
        raise Refused(f"{results_path} 가 이미 있습니다(--force 로 다시 잼)")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    started = time.perf_counter()
    service = Service()
    settings, context = collect_settings(service)
    check_frozen(frozen, settings)
    marks = context["marks"]
    by_appno = {mark.appno: mark for mark in marks}
    positions_a = [mark.appno for mark in marks]
    timing = {"준비_s": round(time.perf_counter() - started, 1)}

    started = time.perf_counter()
    index_b, positions_b, b_stats, b_info = _positions_b(service, marks, OUT / "index_b")
    timing["색인B_s"] = round(time.perf_counter() - started, 1)
    indexes = {"A": (service.index_a, positions_a), "B": (index_b, positions_b)}

    review = OUT / "review"
    started = time.perf_counter()
    t1 = settings["시험1"]
    t1_rows, t1_drawings, failed = [], [], []
    representatives = set(t1["대표"])
    for appno in t1["대상"]:
        mark = by_appno[appno]
        normalized = normalized_logo(service.load_rgb(IMAGES / mark.image))
        sketches = make_sketches(normalized[1], appno) if normalized is not None else {}
        wanted = {appno}
        lenient = wanted | set(t1["인정_집합"][appno])
        for level in ("L1", "L2", "L3"):
            drawing = sketches.get(level)
            gray = render(drawing) if drawing is not None else None
            if gray is None:
                failed.append([appno, level])
                for method in indexes:
                    t1_rows.append({"대상": appno, "단계": level, "방법": method, "엄격": None,
                                    "인정": None, "상위": []})
                continue
            vector = service.encode(gray)
            t1_drawings.append({"대상": appno, "단계": level, **drawing.info,
                                **drawing_stats(gray), "사진": service.is_photo(vector)})
            if appno in representatives:
                path = review / "t1" / level / f"{appno}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(png_bytes(gray, 192))
            for method, (index, positions) in indexes.items():
                top = service.ranked(index, positions, vector, max(TOP_KS))
                ranked = [found for found, _ in top]
                t1_rows.append({"대상": appno, "단계": level, "방법": method,
                                "엄격": first_rank(ranked, wanted),
                                "인정": first_rank(ranked, lenient), "상위": top})
    timing["시험1_s"] = round(time.perf_counter() - started, 1)

    started = time.perf_counter()
    t2 = settings["시험2"]
    t2_rows, t2_drawings = [], []
    for row in t2["대응표"]:
        word, spec = row["범주"], row["분류"]
        records = read_doodles(word)
        for order, record in enumerate(records):
            gray = render(doodle_drawing(record["drawing"]))
            vector = service.encode(gray)
            key = str(record["key_id"])
            t2_drawings.append({"범주": word, "key_id": key, **drawing_stats(gray),
                                "획": len(record["drawing"]), "사진": service.is_photo(vector)})
            if order < t2["대표"]:
                path = review / "t2" / word.replace(" ", "_") / f"{key}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(png_bytes(gray, 192))
            for method, (index, positions) in indexes.items():
                top = service.ranked(index, positions, vector, t2["상위"])
                same = sum(1 for found, _ in top if class_member(by_appno[found].codes, spec))
                t2_rows.append({"범주": word, "key_id": key, "순서": order, "방법": method,
                                "같은_분류": same, "상위": top})
    timing["시험2_s"] = round(time.perf_counter() - started, 1)

    summary1 = summarize_test1(t1_rows, t1["대상"], settings["부트스트랩"])
    summary2 = summarize_test2(t2_rows, t2["대응표"], settings["부트스트랩"])
    decision = decide(summary1, summary2, settings["판정"])
    extras = summarize_extras(t1_drawings, t2_drawings, b_stats, b_info)
    results = {
        "실험": EXPERIMENT, "설정_sha256": frozen["sha256"],
        "실행_시각": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": {"HEAD": _git("rev-parse", "HEAD"), "스크립트_sha256": sha256_file(Path(__file__)),
                "고정_때_스크립트_sha256": frozen["git"]["스크립트_sha256"]},
        "시간": timing, "시험1": summary1, "시험2": summary2, "판정": decision,
        "함께_볼_것": extras, "생성_실패": failed,
        "시험1_요청": t1_rows, "시험2_요청": t2_rows,
        "그림_통계": {"시험1": t1_drawings, "시험2": t2_drawings},
    }
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
    report_text = report(results, settings)
    (OUT / "report.md").write_text(report_text, encoding="utf-8")
    write_review(OUT / "review.html", results, settings, by_appno)
    print(report_text)
    return 0


def summarize_test1(rows: list[dict], targets: list[str], boot: dict) -> dict:
    indices = bootstrap_indices(len(targets), boot["반복"], boot["seed"])
    position = {appno: index for index, appno in enumerate(targets)}
    out: dict = {}
    for method in sorted({row["방법"] for row in rows}):
        out[method] = {}
        for level in ("L1", "L2", "L3"):
            picked = sorted((row for row in rows if row["방법"] == method and row["단계"] == level),
                            key=lambda row: position[row["대상"]])
            out[method][level] = {}
            for criterion in ("엄격", "인정"):
                ranks = [row[criterion] for row in picked]
                out[method][level][criterion] = {}
                for k in TOP_KS:
                    hits = np.array([1.0 if rank is not None and rank <= k else 0.0
                                     for rank in ranks])
                    out[method][level][criterion][str(k)] = {
                        "비율": round(float(hits.mean()), 4), "적중": int(hits.sum()),
                        "n": len(hits), "CI": [round(v, 4) for v in mean_ci(hits, indices,
                                                                             boot["신뢰수준"])]}
    return out


def summarize_test2(rows: list[dict], mapping_rows: list[dict], boot: dict) -> dict:
    words = [row["범주"] for row in mapping_rows]
    bases = np.array([row["기준_비율"] for row in mapping_rows])
    indices = bootstrap_indices(len(words), boot["반복"], boot["seed"])
    out = {}
    for method in sorted({row["방법"] for row in rows}):
        per = {}
        rates = []
        for word, base in zip(words, bases):
            picked = [row for row in rows if row["방법"] == method and row["범주"] == word]
            rate = float(np.mean([row["같은_분류"] / TEST2_TOP for row in picked]))
            rates.append(rate)
            per[word] = {"같은_분류_비율": round(rate, 4), "기준_비율": round(float(base), 4),
                         "배수": round(rate / float(base), 3), "낙서": len(picked)}
        rates_array = np.array(rates)
        multiple, interval = ratio_of_means(rates_array, bases, indices, boot["신뢰수준"])
        out[method] = {"범주": per, "같은_분류_비율_평균": round(float(rates_array.mean()), 4),
                       "기준_비율_평균": round(float(bases.mean()), 4),
                       "배수": round(multiple, 3), "배수_CI": [round(v, 3) for v in interval],
                       "범주별_배수_중앙값": round(float(np.median(rates_array / bases)), 3),
                       "기준선보다_높은_범주": int((rates_array > bases).sum())}
    return out


def summarize_extras(t1_drawings: list[dict], t2_drawings: list[dict], b_stats: list[dict],
                     b_info: dict) -> dict:
    groups = {f"시험1_{level}": [row for row in t1_drawings if row["단계"] == level]
              for level in ("L1", "L2", "L3")}
    groups["시험2_낙서"] = t2_drawings
    groups["방법B_DB_윤곽선"] = b_stats
    out = {}
    for name, rows in groups.items():
        photo = round(float(np.mean([r["사진"] for r in rows])), 4) if rows else None
        out[name] = {"n": len(rows), "사진_비율": photo}
        for key in ("잉크", "상자_채움", "껍질_채움", "선_굵기_px"):
            out[name][key] = percentiles(row[key] for row in rows)
    out["시험1_L3_누락_비율"] = percentiles(row["누락_비율"] for row in groups["시험1_L3"])
    out["시험2_범주별_사진_비율"] = {
        word: round(float(np.mean([r["사진"] for r in t2_drawings if r["범주"] == word])), 4)
        for word in sorted({row["범주"] for row in t2_drawings})}
    out["방법B"] = b_info
    return out


# ---- 보고·확인용 페이지 -------------------------------------------------------------------------

def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _ci(interval: list[float]) -> str:
    return f"{interval[0] * 100:.1f}–{interval[1] * 100:.1f}"


def report(results: dict, settings: dict) -> str:
    t1, t2, decision = results["시험1"], results["시험2"], results["판정"]
    lines = [f"# 손그림 입력 실현성 ({results['실행_시각'][:10]})", "",
             f"설정 sha256 `{results['설정_sha256']}` · 시험 1 대상 "
             f"{len(settings['시험1']['대상'])}(가능 {settings['시험1']['가능_대상_수']}) · "
             f"시험 2 범주 "
             f"{len(settings['시험2']['대응표'])} × 낙서 {settings['시험2']['낙서_수']}", "",
             f"**판정: {decision['판정']}**" + (f" — 방법 {decision['고른_방법']}"
                                                 if decision["고른_방법"] else ""), ""]
    lines += ["| 방법 | L2 인정 상위 5 | 시험 2 배수 (95% CI) | 통과 |", "|---|---:|---:|---|"]
    for method, item in decision["방법"].items():
        interval = t2[method]["배수_CI"]
        passed = "예" if item["통과"] else "아니오"
        lines.append(f"| {method} | {_pct(item['L2_인정_상위5'])} | {item['배수']:.2f} "
                     f"({interval[0]:.2f}–{interval[1]:.2f}) | {passed} |")
    lines += ["", "## 시험 1 — 같은 로고 찾기(적중률 %, 95% CI)", "",
              "| 방법 | 단계 | 기준 | 1위 | 상위 5 | 상위 20 |", "|---|---|---|---:|---:|---:|"]
    for method in t1:
        for level in ("L1", "L2", "L3"):
            for criterion in ("엄격", "인정"):
                cells = [f"{_pct(t1[method][level][criterion][str(k)]['비율'])} "
                         f"({_ci(t1[method][level][criterion][str(k)]['CI'])})" for k in TOP_KS]
                lines.append(f"| {method} | {level} | {criterion} | " + " | ".join(cells) + " |")
    lines += ["", "## 시험 2 — 같은 대상 찾기(상위 5 중 같은 비엔나 분류 비율)", "",
              "| 범주 | 분류 | DB 건수 | 기준 | A 비율 | A 배수 | B 비율 | B 배수 |",
              "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in settings["시험2"]["대응표"]:
        word = row["범주"]
        a, b = t2["A"]["범주"][word], t2["B"]["범주"][word]
        label = (dotted(row["분류"]["중분류"]) if row["분류"]["단위"] == "중분류"
                 else "·".join(dotted(code) for code in row["분류"]["구분"]))
        lines.append(f"| {word} | {label} | {row['DB_건수']} | {_pct(row['기준_비율'])} | "
                     f"{_pct(a['같은_분류_비율'])} | {a['배수']:.2f} | "
                     f"{_pct(b['같은_분류_비율'])} | {b['배수']:.2f} |")
    for method in t2:
        item = t2[method]
        lines.append(f"\n{method}: 범주 평균 비율 {_pct(item['같은_분류_비율_평균'])} ÷ 기준 "
                     f"{_pct(item['기준_비율_평균'])} = 배수 {item['배수']:.2f} (95% CI "
                     f"{item['배수_CI'][0]:.2f}–{item['배수_CI'][1]:.2f}) · 범주별 배수 중앙값 "
                     f"{item['범주별_배수_중앙값']:.2f} · 기준선보다 높은 범주 "
                     f"{item['기준선보다_높은_범주']}/{len(item['범주'])}")
    extras = results["함께_볼_것"]
    lines += ["", "## 함께 볼 것(판정에 안 씀)", "",
              "| 그림 | n | 사진 판정 | 잉크 중앙값(5–95%) | 껍질 채움 중앙값 | 선 굵기 중앙값 |",
              "|---|---:|---:|---|---:|---:|"]
    for name in ("시험1_L1", "시험1_L2", "시험1_L3", "시험2_낙서", "방법B_DB_윤곽선"):
        item = extras[name]
        ink = item["잉크"]
        lines.append(f"| {name} | {item['n']} | {_pct(item['사진_비율'])} | "
                     f"{_pct(ink['p50'])} ({_pct(ink['p5'])}–{_pct(ink['p95'])}) | "
                     f"{item['껍질_채움']['p50']:.2f} | {item['선_굵기_px']['p50']:.1f} |")
    lines += ["", f"생성 실패 {len(results['생성_실패'])} · 방법 B 빈 그림 "
              f"{len(extras['방법B']['빈_그림'])} · 전경 정규화 {extras['방법B']['전경_정규화']}",
              "", "확인용 페이지: review.html(같은 폴더)", ""]
    return "\n".join(lines)


def write_review(path: Path, results: dict, settings: dict, by_appno: dict) -> None:
    def thumb(appno: str, css: str = "", caption: str = "") -> str:
        source = os.path.relpath(IMAGES / by_appno[appno].image, path.parent)
        return (f'<div class="cell {css}"><img loading="lazy" src="{html.escape(source)}">'
                f"<span>{html.escape(caption or appno)}</span></div>")

    t1_rows = {(row["대상"], row["단계"], row["방법"]): row for row in results["시험1_요청"]}
    t2_rows = {(row["범주"], row["key_id"], row["방법"]): row for row in results["시험2_요청"]}
    t1 = settings["시험1"]
    parts = ['<!doctype html><html lang="ko"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             "<title>손그림 실현성 확인</title><style>",
             "body{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;margin:24px;"
             "color:#1d1d1f;background:#fff}h2{margin-top:28px}",
             ".row{display:flex;gap:10px;align-items:flex-start;padding:8px 0;"
             "border-bottom:1px solid #eee;flex-wrap:wrap}",
             ".cell{display:flex;flex-direction:column;align-items:center;font-size:10px;"
             "width:92px}",
             ".cell img{width:84px;height:84px;object-fit:contain;border:3px solid #ddd;"
             "background:#fff}.hit img{border-color:#1a7f37}.soft img{border-color:#0969da}",
             ".group{display:flex;gap:3px;padding:0 6px;border-left:2px solid #ccc}",
             ".tag{font-weight:600;font-size:12px;align-self:center;width:18px}",
             "details{margin:10px 0}summary{cursor:pointer;font-weight:600}",
             "p.note{color:#555;font-size:13px}</style></head><body>",
             "<h1>손그림 입력 실현성 — 확인용 페이지</h1>",
             f"<p class='note'>설정 sha256 {results['설정_sha256']} · 판정 "
             f"{html.escape(results['판정']['판정'])} · 테두리: 초록 = 엄격 적중(시험 1)·같은 분류"
             "(시험 2), 파랑 = 인정 적중(같은 출원인·CLIP ≥ 0.95). A = 서비스 색인, B = 윤곽선 "
             "임시 색인(썸네일은 원래 로고).</p>"]
    parts.append("<h2>시험 1 — 같은 로고 찾기(대표 20)</h2>")
    for level in ("L1", "L2", "L3"):
        parts.append(f"<details{' open' if level == 'L2' else ''}><summary>{level}</summary>")
        for appno in t1["대표"]:
            sketch = f"review/t1/{level}/{appno}.png"
            cells = [f'<div class="cell"><img src="{sketch}"><span>{level} 손그림</span></div>',
                     thumb(appno, caption="원래 로고")]
            contour = OUT / "index_b" / "drawings" / f"{appno}.png"
            if contour.exists():
                cells.append(f'<div class="cell"><img src="index_b/drawings/{appno}.png">'
                             "<span>B 윤곽선(원래)</span></div>")
            lenient = set(t1["인정_집합"][appno])
            for method in ("A", "B"):
                row = t1_rows.get((appno, level, method), {"상위": []})
                group = [f'<span class="tag">{method}</span>']
                for rank, (found, score) in enumerate(row["상위"][:5], start=1):
                    css = "hit" if found == appno else "soft" if found in lenient else ""
                    group.append(thumb(found, css, f"{rank}위 {score:.3f}"))
                cells.append('<div class="group">' + "".join(group) + "</div>")
            parts.append('<div class="row">' + "".join(cells) + "</div>")
        parts.append("</details>")
    parts.append("<h2>시험 2 — 같은 대상 찾기(범주별 대표 20)</h2>")
    for row in settings["시험2"]["대응표"]:
        word, spec = row["범주"], row["분류"]
        keys = settings["시험2"]["낙서"][word]["key_id"][:settings["시험2"]["대표"]]
        a = results["시험2"]["A"]["범주"][word]
        b = results["시험2"]["B"]["범주"][word]
        parts.append(f"<details><summary>{html.escape(word)} — 기준 {_pct(row['기준_비율'])} · "
                     f"A {_pct(a['같은_분류_비율'])} · B {_pct(b['같은_분류_비율'])}</summary>")
        for key in keys:
            doodle = f"review/t2/{word.replace(' ', '_')}/{key}.png"
            cells = [f'<div class="cell"><img src="{doodle}"><span>낙서 {key[-6:]}</span></div>']
            for method in ("A", "B"):
                found_row = t2_rows.get((word, key, method), {"상위": []})
                group = [f'<span class="tag">{method}</span>']
                for rank, (found, score) in enumerate(found_row["상위"], start=1):
                    css = "hit" if class_member(by_appno[found].codes, spec) else ""
                    group.append(thumb(found, css, f"{rank}위 {score:.3f}"))
                cells.append('<div class="group">' + "".join(group) + "</div>")
            parts.append('<div class="row">' + "".join(cells) + "</div>")
        parts.append("</details>")
    parts.append(f"<p class='note'>{html.escape(ATTRIBUTION)}</p></body></html>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="분류표·범주 목록·낙서 일부 내려받기(KIPRIS 아님)")
    fetch.add_argument("--refresh", action="store_true", help="이미 받은 것도 다시 받기")
    freeze = sub.add_parser("freeze", help="설정 고정(검색 전) → config.json")
    freeze.add_argument("--force", action="store_true", help="고정본을 다시 만든다(보고할 것)")
    run = sub.add_parser("run", help="고정본과 같을 때만 측정")
    run.add_argument("--force", action="store_true", help="results.json 이 있어도 다시 잰다")
    args = parser.parse_args(argv)
    handlers = {"fetch": command_fetch, "freeze": command_freeze, "run": command_run}
    try:
        return handlers[args.command](args)
    except Refused as exc:
        print(f"거절: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except FetchFailed as exc:
        print(f"내려받기 실패 — 멈춤: {exc}", file=sys.stderr)
        return EXIT_FETCH


if __name__ == "__main__":
    raise SystemExit(main())
