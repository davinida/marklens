"""관념(뜻) 축 진단 — 재고 분석해서 보고만 한다(서비스 코드·모델 파일·등급 기준 불변).

뜻이 결정적인 유형(번역어·동의어·도형과 이름)을 지금 시스템이 실제로 잡는지, 잘못 켜지는 경우는
없는지, 통합 모델에서 관념 계수를 줄 근거가 있는지를 잰다. 개선 방법은 구현하지 않는다.

    bundles   1절 시험 묶음(저장소 밖 원본 목록)을 DB 와 맞춰 본다 → 저장소 밖 bundles.json
    freeze    분석 설정(표본·묶음 목록·부트스트랩·지표·기대)을 결과 전에 고정(있으면 종료 코드 4)
    offline   2절 네 축 AUC · 3절 관념 계수만 다시 맞추기 · 5절 어긋나는 쌍 · 4절의 쌍 단위
              (엔진 없음)
    engine    1절 묶음별 검색 · 4절 대조군·인용상표·시나리오(실제 엔진, 세 경우)
    figure    1절 (바) 도형과 이름 — 이미지 모델의 글자–그림 유사도(가능성만)
    report    위 결과를 표로(ml/data/trials/x3_diagnosis_report.md)

표본: 분쟁 쌍과 대조군은 기준용만 쓴다. v1.4 학습에는 따로 떼어 둔 확인용이 없었고(묶음 단위 5겹
교차검증) 그래서 같은 묶음 정의(train_risk_model_v14.group_ids)와 같은 나누기
(train_risk_model.folds_for, 5겹·seed 0)로 나눈 첫 겹을 확인용으로 두고 열지 않는다. 지어낸 이름
대조군은 이미 있는 기준용 100개(named_search_thresholds_control.json)만 쓴다.

세 경우: (a) 지금 = 관념 계수 0, (b) 다른 계수를 지금 값으로 고정하고 관념 계수만 0 이상으로 다시
맞춘 값, (c) 참고용 — 철자 계수와 같은 크기. 기준(등급 하한·단독 규칙)은 세 경우 모두 그대로.

정답 데이터·측정 결과(ml/data/trials)와 실제 분쟁 쌍의 예시는 저장소에 올리지 않는다 — 예시는
저장소 밖 폴더(--archive, 기본 ~/marklens-archive/x3-diagnosis-20261129/)에만 쓴다.
KIPRIS 호출 0. engine·figure 는 실제 CLIP·X3 엔진(`MARKLENS_FAKE_ML` 없이).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
for _root in (ML_ROOT, REPO_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from src.axes import x3_semantic as x3  # noqa: E402
from src.axes.x1_phonetic import normalize_name  # noqa: E402
from src.model import risk_model as rm  # noqa: E402

TRIALS = ML_ROOT / "data" / "trials"
STEM = "x3_diagnosis"
ARCHIVE = Path.home() / "marklens-archive" / "x3-diagnosis-20261129"
METADATA = ML_ROOT / "data" / "kipris_metadata.json"
TYPES = ML_ROOT / "data" / "types.json"
CONTROL = TRIALS / "named_search_thresholds_control.json"
VCL_ZIP = ML_ROOT / "data" / "experiments" / "sketch_feasibility" / "inputs" / "vcl_9_20230101.zip"
EXIT_STOP = 3
EXIT_REFUSED = 4

SEED = 0
FOLDS = 5
HOLDOUT_FOLD = 0  # 이 겹 = 확인용(열지 않는다)
BOOTSTRAP = 1000
ZERO = 1e-6  # 부트스트랩에서 "0 에 붙었다"고 보는 값
BETA_MAX = 10.0
LOW, HIGH = 0.35, 0.6  # 5절 — 뜻 점수가 낮다/높다(X3 설계 문서의 단언값)
REVIEW, RISK = "검토 권장", "위험"
TOP_SHOWN, TOP_WIDE = 5, 20
CASES = ("a", "b", "c")
CASE_TEXT = {"a": "(a) 지금(0)", "b": "(b) 다시 맞춘 값", "c": "(c) 철자 계수와 같은 크기"}
AXES = (("호칭", "x1_d", "miss_x1"), ("철자", "x2_text_d", "miss_x2text"),
        ("관념", "x3_d", "miss_x3"), ("상품", "x4", "miss_x4"))
BUNDLES = ("가_번역어", "나_동의어", "다_무관한_사전어", "라_흔한_낱말만", "마_지어낸_이름")
FOUND_BUNDLES = BUNDLES[:2]  # 원래 상표를 찾아야 하는 묶음
CONTROL_BUNDLES = BUNDLES[2:]  # 뜻 때문에 오르면 안 되는 묶음
MODES = ("이름만", "이름+업종")
CONTROL_PER_LANGUAGE = 25  # (마) 기준용 대조군에서 언어마다 앞에서부터
CODE_RE = re.compile(r"^[GS][0-9]{4,6}$")
MAX_CODES = 60
PAIR_TYPES = ("번역·한자 대응을 놓침", "흔한 낱말의 뜻을 견줌", "지어낸 말인데 뜻이 연상됨",
              "무관한 낱말을 가깝게 봄", "심결이 뜻이 아닌 다른 축으로 판단함", "그 밖")
MISS_TYPES = ("질의에 뜻이 없다고 판정", "원래 이름에 뜻이 없다고 판정(요부 기준)",
              "뜻 점수가 풀 하한(0.55) 아래", "풀에는 들었지만 앞 20 밖", "앞 20 안이지만 앞 5 밖",
              "앞 5 안이지만 검토 권장 아래")
FIGURE_PROMPT = "a logo of a {name}"
FIGURE_PER_OBJECT = 6
FIGURE_TARGET = 50

# (바) 도형 분류(비엔나 6자리) → 그린 사물의 이름(영어, 한글). 사물이 하나로 정해지는 구분만
# 적는다 —
# 여러 사물을 묶은 구분(갑각류, 머리카락·수염 등)·기하 도형(26)·글자(27)·바탕(25)은 뺀다.
FIGURE_OBJECTS: dict[str, tuple[str, str]] = {
    **{code: ("star", "별") for code in ("010102", "010109", "010110", "010125")},
    **{code: ("planet", "행성") for code in ("010524", "010525")},
    "011503": ("lightning", "번개"), "011505": ("flame", "불꽃"), "011511": ("cloud", "구름"),
    "011515": ("water drop", "물방울"), "011521": ("bubbles", "거품"),
    "020901": ("heart", "하트"), "020914": ("hand", "손"), "020916": ("handshake", "악수"),
    "020923": ("skull", "해골"), "030101": ("lion", "사자"), "030104": ("tiger", "호랑이"),
    "030106": ("cat", "고양이"), "030108": ("dog", "개"), "030114": ("bear", "곰"),
    "030501": ("rabbit", "토끼"), "030519": ("monkey", "원숭이"), "030702": ("eagle", "독수리"),
    "030703": ("chicken", "닭"),
    **{code: ("bird", "새") for code in ("030707", "030721", "030724")},
    "030717": ("wings", "날개"), "030903": ("whale", "고래"), "031308": ("spider", "거미"),
    **{code: ("insect", "곤충") for code in ("031302", "031324")},
    "040507": ("smiley face", "웃는 얼굴"),
    **{code: ("tree", "나무") for code in ("050102", "050116")},
    "050306": ("clover", "클로버"),
    **{code: ("leaf", "잎") for code in ("050313", "050314")},
    "050516": ("lotus", "연꽃"),
    **{code: ("flower", "꽃") for code in ("050519", "050520", "050521", "050522")},
    "050713": ("apple", "사과"), "050901": ("carrot", "당근"), "060104": ("mountain", "산"),
    **{code: ("house", "집") for code in ("070109", "070124")},
    "070112": ("building", "건물"), "070301": ("door", "문"), "090110": ("ribbon", "리본"),
    "090709": ("hat", "모자"), "090722": ("graduation cap", "학사모"),
    **{code: ("bag", "가방") for code in ("100310", "100311")},
    **{code: ("key", "열쇠") for code in ("140502", "140515")},
    "140523": ("padlock", "자물쇠"), "160105": ("television", "텔레비전"),
    "160301": ("camera", "카메라"), "160313": ("glasses", "안경"), "170107": ("watch", "시계"),
    "170119": ("hourglass", "모래시계"), "180510": ("rocket", "로켓"),
    **{code: ("bottle", "병") for code in ("190712", "190717")},
    "210301": ("ball", "공"),
    **{code: ("crown", "왕관") for code in ("240905", "240921")},
    "241501": ("arrow", "화살표"), "240103": ("shield", "방패"),
}

SETTINGS = {
    "목적": ("관념(뜻) 축 진단 — 뜻이 결정적인 유형을 잡는지, 잘못 켜지는지, 계수를 줄 근거가 "
           "있는지를 재서 보고만 한다. 서비스 코드·모델 파일·등급 기준은 바꾸지 않는다."),
    "표본_분쟁_쌍": ("v1.4 학습 표본(train_risk_model_v14.load_dataset "
        "— 특징 pairs_features.csv 의 "
        "유사·비유사 행 + 쉬운 음성 pairs_features_easy.csv, "
        "사진 규칙·사건 가중 상한 3)을 같은 묶음"
        "(group_ids: 심판번호, 같은 쌍키는 한 묶음)과 같은 나누기(train_risk_model.folds_for 5겹·"
        "seed 0 — StratifiedGroupKFold)로 나눠 첫 겹(0)을 확인용으로 두고 열지 않는다. 나머지 네 "
        "겹이 기준용. v1.4 학습에는 따로 떼어 둔 확인용이 없었다(묶음 단위 5겹 × 3반복 교차검증)."),
    "표본_대조군": ("지어낸 이름 대조군은 "
        "named_search_thresholds_control.json 의 기준용 100개(한글 "
        "50·영문 50)만. 확인용 100개는 쓰지 않는다."),
    "묶음": ("1절 — 원본 목록(저장소 밖 bundles_source.json)을 "
        "DB 와 맞춘 bundles.json 의 sha256 을 "
        "고정본에 적는다. (가) 번역어 (나) 동의어·유의어: "
        "원래 상표 = 정규화한 이름이 같은 DB 레코드 "
        "전부, 업종 = 그 가운데 출원번호가 가장 앞선 레코드의 유사군. (다) 무관한 사전어: 어느 DB "
        "이름의 낱말과도 글자가 같지 않은 사전어, 업종 "
        "= 대조군 파일의 업종 세트에서 random.Random(0) "
        "으로 하나씩. "
        "(라) 흔한 낱말만 같은 경우: 식별력 모델이 "
        "약하다고 한 DB 이름의 낱말 하나의 번역어 + 무관한 "
        "사전어, 업종 = 그 낱말이 든 DB 레코드(출원번호가 "
        "가장 앞선 것)의 유사군. (마) 지어낸 이름: "
        "기준용 대조군에서 언어마다 앞에서부터 25개, 업종 = 대조군 파일의 유사군."),
    "묶음_재는_것": ("묶음마다 이름만·이름+업종 두 "
        "방식으로: 뜻이 있다고 판정된 비율(x3.has_meaning), "
        "뜻 점수 분포((가)(나)는 원래 상표와의 쌍별 점수 — 엔진이 채점한 값, 풀에 없으면 같은 함수 "
        "compute_pair_axes 로; 대조 묶음은 후보 풀의 최댓값), 단독 규칙(standalone_x3)이 켜진 비율"
        "((가)(나)는 원래 상표의 카드, 대조 묶음은 풀의 "
        "어느 후보든), (가)(나) 원래 상표가 앞 5·앞 20 "
        "안에 드는 비율과 그 카드의 등급·전체 등급 분포, "
        "대조 묶음의 전체 등급 검토 권장 이상 비율과 "
        "그것이 뜻 때문인 비율. 전체 등급 = 엔진 multi_search(top_k 5)의 overall.grade(유명 상표 "
        "바닥 포함), 순위·카드 = search_pool 의 정렬. '뜻 때문' = 같은 질의를 관념 축을 끄고"
        "(config.X3_ENABLED False — 관념 후보 풀·뜻 점수·단독 규칙 모두 없음) 다시 검색했을 때 "
        "검토 권장 아래로 내려가는 경우."),
    "기대": ("(가)(나)는 원래 상표를 찾아(앞 5) 검토 권장 이상, (다)(라)(마)는 뜻 때문에 오르지 "
        "않는 것. 통과선은 두지 않고 값만 보고한다. 어긋난 사례는 유형별로 많은 순으로 20개씩."),
    "도형과_이름": ("(바) 유형 사전(types.json)이 도형인 DB 표장 가운데 비엔나 6자리 코드를 "
        "FIGURE_OBJECTS(코드 → 사물 이름)로 옮겼을 때 사물이 정확히 하나인 표장. 사물마다 출원번호 "
        f"순으로 {FIGURE_PER_OBJECT}개까지, 모두 {FIGURE_TARGET}개 안팎. 엔진의 이미지 모델"
        "(OpenCLIP ViT-B/32)의 글자 인코더로 사물 이름을 "
        "임베딩해 색인의 이미지 벡터와 코사인. 맞는 "
        "짝(표장, 그 사물 이름) 대 틀린 짝(표장, 다른 "
        "사물 이름 전부)의 AUC 와 표장 단위 부트스트랩 "
        f"95% 구간. 글자 = '{FIGURE_PROMPT}'(주), "
        f"낱말만(참고), 한글 낱말(참고 — 한글을 다루는지)."),
    "네_축": ("2절 — 호칭 x1_d·철자 x2_text_d·관념 "
        "x3_d·상품 x4(통합 모델 입력 그대로, 잴 수 없으면 "
        "모델이 쓰는 값 0). 세 표본: 기준용 분쟁 쌍 "
        "전체 / 그 축을 잴 수 있는 쌍(관념 = 양쪽에 뜻이 "
        "있는 쌍) / 쉬운 음성을 섞은 현실 분포(기준용 분쟁 쌍 + 기준용 쉬운 음성). 사건 가중 AUC"
        "(train_risk_model_v14.weighted_auc)와 묶음 단위 부트스트랩 95% 구간. 관념 − 철자 차이는 "
        "같은 부트스트랩 표본에서."),
    "부트스트랩": {"횟수": BOOTSTRAP, "씨앗": SEED, "단위": "묶음(사건) 복원추출"},
    "계수_다시_맞추기": ("3절 — 이름 있는 계수 세트 넷(base·x2_whole·x4·x2_whole+x4)마다 그 세트의 "
        "축이 모두 관측된 기준용 행(이름 있는 분쟁 쌍 + "
        "쉬운 음성)으로, 다른 계수·절편은 v1.4.7 값으로 "
        "고정(오프셋)하고 관념 계수만 0 이상으로. 목적함수는 학습 때와 같다: Σ w·logloss + "
        "(β − μ)²/(2σ²), w = 사건 가중 × (쉬운 음성 0.5), μ·σ = 계수 JSON 의 prior(관념 0.5·1.0). "
        "지금 모델에는 관념 결측 지시자가 없다(뜻이 한쪽에라도 없으면 값 0) — 주 결과는 관념 계수 "
        "하나만, 결측 지시자를 함께 둔 적합·사전분포 없는 적합·제약 없는 적합은 참고로. 부트스트랩"
        f"(묶음 {BOOTSTRAP}회)에서 값의 95% 구간과 0 에 붙는 비율(β < {ZERO})."),
    "세_경우": ("(a) 지금 = 관념 계수 0, (b) 다시 맞춘 값(세트별), (c) 참고용 — 철자 계수와 같은 "
        "크기(세트별 x2_text_d 계수). 등급 하한·단독 규칙·다른 규칙은 세 경우 모두 그대로."),
    "넣었을_때": ("4절(기준용만, 세 경우 각각) — 지어낸 이름 대조군 기준용 100개 × 네 방식의 검토 "
        "권장 이상 비율(search_pool 앞 5 후보 등급의 최댓값 — 이전 채택 평가와 같은 정의), 표본 A "
        "인용상표 쌍 가운데 기준용인 쌍의 등급 분포(엔진과 "
        "같은 식 named_goods_product.engine_grade)와 "
        "양쪽에 뜻이 있는 쌍만, 기준용 이름 있는 분쟁 "
        "쌍의 '위험' 정밀도, 시나리오 16종의 전체 등급·"
        "1위 가운데 바뀌는 것, 1절 묶음의 결과."),
    "어긋나는_쌍": (f"5절 — 기준용 분쟁 쌍 가운데 양쪽에 "
        f"뜻이 있는 쌍에서 유사인데 뜻 점수 < {LOW}, "
        f"비유사인데 뜻 점수 ≥ {HIGH}. 유사·비유사는 "
        f"표장라벨(심결의 표장 유사 판단)이 있으면 그것, "
        "없으면 최종라벨. 축별 판단은 데이터에 '어느 축을 봤는가'(판단축)만 있어 그것으로 '다른 "
        "축으로 판단'을 가른다. 원인 분류는 사람이(이 세션에서) 쌍을 읽고 저장소 밖 파일에 적는다. "
        "단독 규칙이 기준용 분쟁 쌍에서 켜진 횟수와 그 가운데 유사·비유사."),
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _round(value, digits: int = 4):
    if value is None:
        return None
    value = float(value)
    return None if np.isnan(value) else round(value, digits)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def settings_sha256(bundles_sha: str) -> str:
    payload = {"설정": SETTINGS, "묶음_sha256": bundles_sha,
               "도형_사물": {code: list(names) for code, names in sorted(FIGURE_OBJECTS.items())}}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def at_least(grade: str | None, floor: str) -> bool:
    return grade is not None and rm.GRADES.index(grade) >= rm.GRADES.index(floor)


def distribution(grades) -> dict[str, int]:
    counts = Counter(grade or "없음" for grade in grades)
    return {key: counts[key] for key in [*rm.GRADES, "없음"] if counts.get(key)}


def quantiles(values) -> dict | None:
    data = np.asarray([v for v in values if v is not None], dtype=np.float64)
    if data.size == 0:
        return None
    q = np.percentile(data, [10, 25, 50, 75, 90])
    return {"n": int(data.size), "평균": _round(data.mean()), "p10": _round(q[0]),
            "p25": _round(q[1]), "중앙": _round(q[2]), "p75": _round(q[3]), "p90": _round(q[4]),
            "최대": _round(data.max())}


def share(count: int, total: int) -> float | None:
    return round(count / total, 4) if total else None


# ---- 1절 묶음: 원본 목록 → DB 와 맞춘 목록 -----------------------------------------------------

def normalized_key(name: str) -> str:
    """이름의 정규화 키 — 관념 축이 쓰는 정규화(normalize_name)의 낱말을 공백으로 이은 것."""
    return " ".join(normalize_name(name or ""))


def valid_codes(value) -> list[str]:
    """레코드의 유사군 → 엔진이 받는 형식(G/S + 숫자 4–6)만, 정렬·최대 60개."""
    if isinstance(value, str):
        value = value.split("|")
    cleaned = (str(code).strip() for code in (value or []))
    codes = sorted({code for code in cleaned if CODE_RE.match(code)})
    return codes[:MAX_CODES]


def name_index(records: list[dict]) -> tuple[dict[str, list[dict]], set[str]]:
    """(정규화 키 → 레코드들(출원번호 순), DB 이름의 낱말 전체)."""
    by_key: dict[str, list[dict]] = {}
    tokens: set[str] = set()
    for record in sorted(records, key=lambda r: str(r.get("출원번호"))):
        name = str(record.get("상표한글명") or "").strip()
        if not name:
            continue
        parts = normalize_name(name)
        tokens.update(parts)
        by_key.setdefault(" ".join(parts), []).append(record)
    return by_key, tokens


def resolve_bundles(source: dict, records: list[dict], *, weak_records: dict[str, dict],
                    control: list[dict], presets: list[dict]) -> tuple[dict, list[str]]:
    """원본 목록을 DB 와 맞춘다 → (묶음, 문제 목록). 문제가 있으면 고정하지 않는다."""
    import random

    by_key, tokens = name_index(records)
    problems: list[str] = []
    out: dict[str, list[dict]] = {name: [] for name in BUNDLES}

    def original(key: str, label: str) -> dict | None:
        found = by_key.get(key)
        if not found:
            problems.append(f"{label}: DB 에 없는 이름 '{key}'")
            return None
        return {"원래_키": key, "원래_이름": str(found[0].get("상표한글명")).strip(),
                "원래_ids": [str(r["출원번호"]) for r in found],
                "업종": valid_codes(found[0].get("유사군"))}

    for item in source.get("가_번역어", []):
        base = original(item["원래"], "(가)")
        if base:
            out["가_번역어"].append({"질의": item["질의"], **base, "범위": item["범위"],
                                    "소리": item["소리"]})
    for item in source.get("나_동의어", []):
        base = original(item["원래"], "(나)")
        if base:
            out["나_동의어"].append({"질의": item["질의"], **base})
    rng = random.Random(SEED)
    for item in source.get("다_무관한_사전어", []):
        word = item["질의"]
        if set(normalize_name(word)) & tokens:
            problems.append(f"(다): DB 이름의 낱말과 같은 사전어 '{word}'")
        preset = rng.choice(presets)
        out["다_무관한_사전어"].append({"질의": word, "언어": item["언어"],
                                       "업종_세트": preset["id"],
                                       "업종": preset["codes"]})
    for item in source.get("라_흔한_낱말만", []):
        record = weak_records.get(item["약한_낱말"])
        if record is None:
            problems.append(f"(라): DB 이름에서 약한 낱말로 나오지 않는 '{item['약한_낱말']}'")
            continue
        out["라_흔한_낱말만"].append({"질의": item["질의"], "약한_낱말": item["약한_낱말"],
                                     "든_이름": str(record.get("상표한글명")).strip(),
                                     "든_id": str(record["출원번호"]),
                                     "업종": valid_codes(record.get("유사군"))})
    for language in ("ko", "en"):
        picked = [row for row in control if row.get("언어") == language][:CONTROL_PER_LANGUAGE]
        out["마_지어낸_이름"] += [{"질의": row["이름"], "언어": language,
                                  "업종_세트": row.get("업종_세트"),
                                  "업종": valid_codes(row.get("유사군"))} for row in picked]
    for name, items in out.items():
        queries = [item["질의"] for item in items]
        for query, count in Counter(queries).items():
            if count > 1:
                problems.append(f"{name}: 같은 질의가 {count}번 '{query}'")
    return out, problems


def weak_token_records(records: list[dict], distinct) -> dict[str, dict]:
    """DB 이름에서 식별력 모델이 약하다고 한 사전어 낱말 → 그 낱말이 든 레코드(출원번호 순 첫째)."""
    out: dict[str, dict] = {}
    for record in sorted(records, key=lambda r: str(r.get("출원번호"))):
        name = str(record.get("상표한글명") or "").strip()
        if not name:
            continue
        for judged in distinct.judge_name(name, None):
            if judged.is_weak and x3._is_word(judged.token):  # noqa: SLF001 — 게이트와 같은 판정
                out.setdefault(judged.token, record)
    return out


def load_presets(path: Path = CONTROL) -> list[dict]:
    """업종 세트와 그 유사군 — 대조군 파일에 적힌 것(대조군을 만들 때 쓴 세트 그대로)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [{"id": preset_id, "codes": valid_codes(codes)}
            for preset_id, _name, codes in data["대조군"]["업종_세트"]]


def load_records(path: Path = METADATA) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("trademarks", data) if isinstance(data, dict) else data


# ---- 표본: 기준용·확인용 ------------------------------------------------------------------------

def load_rows():
    """(v1.4 학습 행, y, 평가 가중, 학습 가중, 묶음, 쉬운 음성 여부, 설계 값)."""
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    rows = t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY).rows
    y = np.asarray([1.0 if row["최종라벨"] == "유사" else 0.0 for row in rows])
    weight = np.asarray([row["_w"] for row in rows], dtype=np.float64)
    easy = np.asarray([row["pair_source"] != "trial" for row in rows])
    groups = np.asarray([row["_group"] for row in rows])
    values = [rm.design_values(tr.row_features(row)) for row in rows]
    named = np.asarray([tr.has_name(row) for row in rows])
    return {"rows": rows, "y": y, "weight": weight,
            "fit_weight": weight * np.where(easy, tr.W_EASY, 1.0),
            "groups": groups, "easy": easy, "values": values, "named": named}


def baseline_mask(y: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """기준용 여부 — v1.4 학습의 나누기(묶음 단위 층화 5겹, seed 0)의 첫 겹을 확인용으로 뺀다."""
    from scripts import train_risk_model as tr

    holdout = np.zeros(y.size, dtype=bool)
    holdout[tr.folds_for(y, groups, folds=FOLDS, seed=SEED)[HOLDOUT_FOLD][1]] = True
    return ~holdout


def split_summary(data: dict, base: np.ndarray) -> dict:
    trial = ~data["easy"]

    def count(mask: np.ndarray) -> dict:
        return {"행": int(mask.sum()), "묶음": len(set(data["groups"][mask])),
                "유사": int((data["y"][mask] == 1).sum()),
                "비유사": int((data["y"][mask] == 0).sum())}

    return {"분쟁_쌍_기준용": count(trial & base), "분쟁_쌍_확인용(열지 않음)": {
        "행": int((trial & ~base).sum()), "묶음": len(set(data["groups"][trial & ~base]))},
            "쉬운_음성_기준용": count(~trial & base),
            "쉬운_음성_확인용(열지 않음)": {"행": int((~trial & ~base).sum())}}


# ---- 2절 네 축 --------------------------------------------------------------------------------

def axis_arrays(data: dict) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """축 이름 → (점수 — 잴 수 없으면 모델이 쓰는 값 0, 잴 수 있는 쌍)."""
    out = {}
    for label, column, miss in AXES:
        score = np.asarray([values[column] for values in data["values"]])
        measurable = np.asarray([values[miss] == 0.0 for values in data["values"]])
        out[label] = (score, measurable)
    return out


def auc_block(score: np.ndarray, y: np.ndarray, weight: np.ndarray, mask: np.ndarray, boot) -> dict:
    from scripts import train_risk_model_v14 as t4

    labels = y[mask]
    out = {"n": int(mask.sum()), "유사": int((labels == 1).sum()),
           "비유사": int((labels == 0).sum()),
           "auc": _round(t4.weighted_auc(score[mask], labels, weight[mask]))}
    if out["auc"] is not None:
        _, tie = np.unique(score[mask], return_inverse=True)
        pos, neg = (labels == 1).astype(float), (labels == 0).astype(float)
        out["ci95"] = t4._ci(boot.values(  # noqa: SLF001
            lambda w: t4._tie_auc(tie, w * pos, w * neg), mask, weight))  # noqa: SLF001
    return out


def auc_difference(score_a: np.ndarray, score_b: np.ndarray, y: np.ndarray, weight: np.ndarray,
                   mask: np.ndarray, boot) -> dict:
    """같은 부트스트랩 표본에서 AUC(a) − AUC(b)."""
    from scripts import train_risk_model_v14 as t4

    labels = y[mask]
    pos, neg = (labels == 1).astype(float), (labels == 0).astype(float)
    _, tie_a = np.unique(score_a[mask], return_inverse=True)
    _, tie_b = np.unique(score_b[mask], return_inverse=True)
    base = weight[mask]
    point_a, point_b = t4._tie_auc(tie_a, base * pos, base * neg), t4._tie_auc(  # noqa: SLF001
        tie_b, base * pos, base * neg)
    if point_a is None or point_b is None:
        return {"n": int(mask.sum()), "차이": None, "ci95": [None, None]}
    diff = (boot.values(lambda w: t4._tie_auc(tie_a, w * pos, w * neg), mask, weight)  # noqa: SLF001
            - boot.values(lambda w: t4._tie_auc(tie_b, w * pos, w * neg), mask, weight))  # noqa: SLF001
    return {"n": int(mask.sum()), "차이": _round(point_a - point_b), "ci95": t4._ci(diff),  # noqa: SLF001
            "0보다_큰_비율": _round(float(np.mean(diff[~np.isnan(diff)] > 0)))}


def four_axes(data: dict, base: np.ndarray, boot) -> dict:
    trial = ~data["easy"]
    arrays = axis_arrays(data)
    y, weight = data["y"], data["weight"]
    samples = {"분쟁_쌍_전체": lambda m: trial & base, "잴_수_있는_쌍": lambda m: trial & base & m,
               "현실_분포": lambda m: base}
    out: dict = {"축": {}, "관념−철자": {}}
    for label, (score, measurable) in arrays.items():
        out["축"][label] = {name: auc_block(score, y, weight, pick(measurable), boot)
                           for name, pick in samples.items()}
    meaning = arrays["관념"][1]
    for name, mask in (("분쟁_쌍_전체", trial & base),
                       ("양쪽에_뜻이_있는_쌍", trial & base & meaning),
                       ("현실_분포", base)):
        out["관념−철자"][name] = auc_difference(arrays["관념"][0], arrays["철자"][0], y, weight,
                                             mask, boot)
    return out


# ---- 3절 관념 계수만 다시 맞추기 ----------------------------------------------------------------

def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -700, 700)))


def fit_x3(offset: np.ndarray, x: np.ndarray, y: np.ndarray, w: np.ndarray, *,
           mu: float | None = None, sigma: float = 1.0, lower: float | None = 0.0) -> float:
    """다른 항을 offset 으로 고정하고 관념 계수 β 하나만: Σ w·logloss(offset + βx) +
    (β − μ)²/(2σ²)(μ 가 None 이면 사전분포 없음). lower 0 이면 β ≥ 0, None 이면 제약 없음.
    볼록 함수라 β = 0 에서의 기울기가 0 이상이면 최솟값은 정확히 0 이다."""
    from scipy.optimize import minimize_scalar

    keep = w > 0
    offset, x, y, w = offset[keep], x[keep], y[keep], w[keep]
    precision = 0.0 if mu is None else 1.0 / (sigma * sigma)
    center = 0.0 if mu is None else mu

    def value(beta: float) -> float:
        z = offset + beta * x
        loss = float(np.sum(w * (np.logaddexp(0.0, z) - y * z)))
        return loss + 0.5 * precision * (beta - center) ** 2

    def slope(beta: float) -> float:
        z = offset + beta * x
        return float(np.sum(w * (_sigmoid(z) - y) * x)) + precision * (beta - center)

    if lower is not None and slope(lower) >= 0.0:
        return float(lower)
    low = -BETA_MAX if lower is None else lower
    found = minimize_scalar(value, bounds=(low, BETA_MAX), method="bounded",
                            options={"xatol": 1e-9})
    return float(found.x)


def fit_x3_with_missing(offset, x, missing, y, w, *, mu: float | None, sigma: float = 1.0
                        ) -> tuple[float, float]:
    """참고 — 관념 계수 β(≥ 0)와 결측 지시자 γ(뜻이 한쪽에라도 없으면 1, 제약 없음)를 함께."""
    from scipy.optimize import minimize

    keep = w > 0
    offset, x, missing, y, w = offset[keep], x[keep], missing[keep], y[keep], w[keep]
    precision = 0.0 if mu is None else 1.0 / (sigma * sigma)
    center = 0.0 if mu is None else mu

    def objective(theta):
        z = offset + theta[0] * x + theta[1] * missing
        residual = w * (_sigmoid(z) - y)
        value = float(np.sum(w * (np.logaddexp(0.0, z) - y * z))) + 0.5 * precision * (
            theta[0] - center) ** 2
        return value, np.asarray([float(residual @ x) + precision * (theta[0] - center),
                                  float(residual @ missing)])

    found = minimize(objective, np.zeros(2), jac=True, method="L-BFGS-B",
                     bounds=[(0.0, BETA_MAX), (-BETA_MAX, BETA_MAX)])
    return float(found.x[0]), float(found.x[1])


def block_mask(key: str, data: dict) -> np.ndarray:
    """그 계수 세트의 축이 모두 관측된 이름 있는 행(하위 세트는 상위 세트의 행도 포함 — 학습과
    같다)."""
    present = rm.pattern_present(key)
    mask = data["named"].copy()
    for axis, miss in (("x2_whole", "miss_x2img"), ("x4", "miss_x4")):
        if axis in present:
            mask &= np.asarray([values[miss] == 0.0 for values in data["values"]])
    return mask


def refit(data: dict, base: np.ndarray, model: dict, boot) -> dict:
    prior = model.get("prior") or {}
    mu = (prior.get("mu") or {}).get("x3_d")
    sigma = float(prior.get("sigma") or 1.0)
    x_all = np.asarray([values["x3_d"] for values in data["values"]])
    missing_all = np.asarray([values["miss_x3"] for values in data["values"]])
    out: dict = {"사전분포": {"mu": mu, "sigma": sigma}, "세트": {}}
    for key, block in model["patterns"].items():
        mask = block_mask(key, data) & base
        offset = np.asarray([rm.block_logit(block, values, model) if use else 0.0
                             for values, use in zip(data["values"], mask)])
        x, y, w = x_all[mask], data["y"][mask], data["fit_weight"][mask]
        off = offset[mask]
        beta = fit_x3(off, x, y, w, mu=mu, sigma=sigma)
        draws = np.asarray([fit_x3(off, x, y, w * counts[mask], mu=mu, sigma=sigma)
                            for counts in boot.draws])
        both, gamma = fit_x3_with_missing(off, x, missing_all[mask], y, w, mu=mu, sigma=sigma)
        meaning = missing_all[mask] == 0.0
        trial = ~data["easy"][mask]
        out["세트"][key or "base"] = {
            "행": int(mask.sum()), "분쟁_쌍": int(trial.sum()), "쉬운_음성": int((~trial).sum()),
            "양쪽에_뜻이_있는_행": int(meaning.sum()),
            "양쪽에_뜻이_있는_분쟁_쌍": int((meaning & trial).sum()),
            "지금_계수": float(block["coefficients"].get("x3_d", 0.0)),
            "철자_계수": float(block["coefficients"]["x2_text_d"]),
            "다시_맞춘_값": _round(beta),
            "ci95": [_round(np.percentile(draws, 2.5)), _round(np.percentile(draws, 97.5))],
            "0에_붙는_비율": _round(float(np.mean(draws < ZERO))),
            "참고_사전분포_없이": _round(fit_x3(off, x, y, w, mu=None)),
            "참고_제약_없이": _round(fit_x3(off, x, y, w, mu=mu, sigma=sigma, lower=None)),
            "참고_제약·사전분포_없이": _round(fit_x3(off, x, y, w, mu=None, lower=None)),
            "참고_결측_지시자와_함께": {"관념": _round(both), "결측_지시자": _round(gamma)},
        }
    return out


def case_coefficients(model: dict, fitted: dict) -> dict[str, dict[str, float]]:
    """세 경우의 세트별 관념 계수."""
    keys = list(model["patterns"])
    return {"a": {key: 0.0 for key in keys},
            "b": {key: float(fitted["세트"][key or "base"]["다시_맞춘_값"]) for key in keys},
            "c": {key: float(model["patterns"][key]["coefficients"]["x2_text_d"]) for key in keys}}


def variant_model(base: dict, coefficients: dict[str, float], label: str) -> dict:
    """관념 계수만 바꾼 사본 — 그 밖의 계수·기준·규칙은 그대로(파일로 쓰지 않는다)."""
    model = copy.deepcopy(base)
    for key, value in coefficients.items():
        model["patterns"][key]["coefficients"]["x3_d"] = float(value)
    reference = model.get("reference_pattern")
    if reference in coefficients and "x3_d" in model.get("coefficients", {}):
        model["coefficients"]["x3_d"] = float(coefficients[reference])
    model["version"] = f"{base.get('version')}+x3:{label}"
    return model


def case_models(base: dict, fitted: dict) -> dict[str, dict]:
    return {label: variant_model(base, coefficients, label)
            for label, coefficients in case_coefficients(base, fitted).items()}


# ---- 4절(쌍 단위)·5절 --------------------------------------------------------------------------

def engine_features(row: dict) -> dict:
    """특징 행 → 엔진이 그 쌍에 넘기는 입력(이름 있는 질의는 이미지가 있으면 결합-문자요부, 없으면
    문자 — goods_cap.cited_pairs 와 같다)."""
    from scripts import train_risk_model_v14 as t4

    features = t4.service_features(row, image_column=t4.RAW_IMAGE)
    features["mark_type"] = "결합-문자요부" if features["x2_whole"] is not None else "문자"
    return features


def pair_label(row: dict) -> str:
    """유사·비유사 — 심결의 표장 유사 판단(표장라벨)이 있으면 그것, 없으면 전체 결론(최종라벨)."""
    mark = (row.get("표장라벨") or "").strip()
    return mark if mark in ("유사", "비유사") else row["최종라벨"]


def pair_grades(data: dict, base: np.ndarray, models: dict[str, dict]) -> dict:
    """기준용 이름 있는 분쟁 쌍의 등급 분포와 '위험' 정밀도(엔진과 같은 식, 세 경우)."""
    from scripts import named_goods_product as ngp

    picked = [i for i in range(len(data["rows"]))
              if base[i] and not data["easy"][i] and data["named"][i]]
    features = [engine_features(data["rows"][i]) for i in picked]
    meaning = np.asarray([data["values"][i]["miss_x3"] == 0.0 for i in picked])
    y = data["y"][picked]
    w = data["weight"][picked]
    out: dict = {"쌍": len(picked), "양쪽에_뜻이_있는_쌍": int(meaning.sum())}
    grades: dict[str, list[str]] = {}
    for label, model in models.items():
        grades[label] = [ngp.engine_grade(item, model) for item in features]
        risk = np.asarray([grade == RISK for grade in grades[label]])
        review = np.asarray([at_least(grade, REVIEW) for grade in grades[label]])
        out[label] = {
            "등급": distribution(grades[label]),
            "등급_양쪽에_뜻이_있는_쌍": distribution(
                [grade for grade, both in zip(grades[label], meaning) if both]),
            "위험": {"쌍": int(risk.sum()), "유사": int((risk & (y == 1)).sum()),
                   "정밀도": share(int((risk & (y == 1)).sum()), int(risk.sum())),
                   "정밀도_사건_가중": _round(float((w * risk * y).sum() / (w * risk).sum()))
                   if risk.any() else None},
            "검토_권장_이상": {"유사": share(int((review & (y == 1)).sum()), int((y == 1).sum())),
                           "비유사": share(int((review & (y == 0)).sum()), int((y == 0).sum()))},
        }
    for label in models:
        if label == "a":
            continue
        moved = Counter()
        for before, after, similar in zip(grades["a"], grades[label], y):
            if before != after:
                moved[f"{before} → {after} · {'유사' if similar == 1 else '비유사'}"] += 1
        out[label]["지금과_달라진_쌍"] = dict(moved.most_common())
    return out


def mismatched_pairs(data: dict, base: np.ndarray, model: dict) -> dict:
    """5절 — 양쪽에 뜻이 있는 기준용 분쟁 쌍에서 뜻 점수가 어긋나는 쌍, 단독 규칙이 켜진 쌍."""
    tau = (model.get("standalone_thresholds") or {}).get("x3_d")
    low, high, fired = [], [], []
    both = 0
    for index, row in enumerate(data["rows"]):
        if not base[index] or data["easy"][index]:
            continue
        values = data["values"][index]
        if values["miss_x3"] != 0.0:
            continue
        both += 1
        label = pair_label(row)
        axes = (row.get("판단축") or "").strip()
        item = {"쌍키": row.get("쌍키") or f"{row['심판번호']}|{row.get('상대번호')}",
                "심판번호": row["심판번호"], "이름A": row.get("이름A"), "이름B": row.get("이름B"),
                "뜻_점수": _round(values["x3_d"]), "호칭": _round(values["x1_d"]),
                "철자": _round(values["x2_text_d"]), "유사": label, "최종라벨": row["최종라벨"],
                "판단축": axes,
                "약한_낱말": f"{row.get('weak_a') or ''} / {row.get('weak_b') or ''}"}
        if label == "유사" and values["x3_d"] < LOW:
            low.append(item)
        if label == "비유사" and values["x3_d"] >= HIGH:
            high.append(item)
        if tau is not None and values["x3_d"] >= float(tau):
            fired.append(item)
    low.sort(key=lambda item: item["뜻_점수"])
    high.sort(key=lambda item: -item["뜻_점수"])
    return {"양쪽에_뜻이_있는_쌍": both, "유사인데_낮음": low, "비유사인데_높음": high,
            "단독_규칙": {"기준": tau, "켜진_쌍": len(fired),
                       "유사": sum(1 for item in fired if item["유사"] == "유사"),
                       "비유사": sum(1 for item in fired if item["유사"] == "비유사"),
                       "최종라벨_유사": sum(1 for item in fired if item["최종라벨"] == "유사"),
                       "쌍": fired}}


def other_axis_only(axes: str) -> bool:
    """심결이 본 축(판단축)에 관념이 없다 — 뜻이 아닌 다른 축으로 판단."""
    parts = [part for part in axes.split("|") if part]
    return bool(parts) and "관념" not in parts


def tabulate_pair_types(items: list[dict], assigned: dict[str, list[str]]) -> dict:
    """사람이 적은 분류(쌍키 → [유형, 세부])로 유형별 건수·세부 건수와 대표 예 셋씩."""
    counts: Counter = Counter()
    details: Counter = Counter()
    examples: dict[str, list[dict]] = {}
    for item in items:
        kind, detail = assigned.get(item["쌍키"]) or ["분류 안 함", ""]
        counts[kind] += 1
        if detail:
            details[f"{kind} — {detail}"] += 1
        examples.setdefault(kind, [])
        if len(examples[kind]) < 3:
            examples[kind].append(item)
    order = [kind for kind in (*PAIR_TYPES, "분류 안 함") if counts.get(kind)]
    return {"건수": {kind: counts[kind] for kind in order}, "세부": dict(details.most_common()),
            "예": {kind: examples[kind] for kind in order}}


# ---- 1절: 검색 단위 ----------------------------------------------------------------------------

def miss_type(*, query_meaning: bool, pair_meaning: bool, score: float | None, in_pool: bool,
              rank: int | None, card_grade: str | None, pool_floor: float) -> str | None:
    """(가)(나)에서 기대(앞 5 안 + 검토 권장 이상)와 어긋난 까닭 — 어긋나지 않았으면 None."""
    if rank is not None and rank <= TOP_SHOWN and at_least(card_grade, REVIEW):
        return None
    if rank is not None:
        if rank > TOP_WIDE:
            return MISS_TYPES[3]
        return MISS_TYPES[4] if rank > TOP_SHOWN else MISS_TYPES[5]
    if not query_meaning:
        return MISS_TYPES[0]
    if not pair_meaning or score is None:
        return MISS_TYPES[1]
    if not in_pool and score < pool_floor:
        return MISS_TYPES[2]
    return MISS_TYPES[3]


def within(row: dict, top: int) -> bool:
    return row["순위"] is not None and row["순위"] <= top


def summarize_found(rows: list[dict]) -> dict:
    """(가)(나) 한 묶음·한 방식의 요약."""
    total = len(rows)
    types = Counter(row["어긋남"] for row in rows if row["어긋남"])
    return {
        "질의": total,
        "뜻이_있다고_판정": share(sum(row["질의_뜻"] for row in rows), total),
        "양쪽에_뜻(원래 상표와)": share(sum(row["쌍_뜻"] for row in rows), total),
        "뜻_점수": quantiles([row["뜻_점수"] for row in rows]),
        "단독_규칙": share(sum(row["단독_규칙"] for row in rows), total),
        "풀에_듦": share(sum(row["순위"] is not None for row in rows), total),
        "앞_5": share(sum(within(row, TOP_SHOWN) for row in rows), total),
        "앞_20": share(sum(within(row, TOP_WIDE) for row in rows), total),
        "앞_5·검토_권장_이상(기대)": share(sum(row["어긋남"] is None for row in rows), total),
        "카드_등급(풀에 든 것)": distribution(
            [row["카드_등급"] for row in rows if row["순위"] is not None]),
        "전체_등급": distribution([row["전체_등급"] for row in rows]),
        "전체_검토_권장_이상": share(
            sum(at_least(row["전체_등급"], REVIEW) for row in rows), total),
        "어긋난_까닭": dict(types.most_common()),
    }


def summarize_control(rows: list[dict]) -> dict:
    """대조 묶음 한 방식의 요약 — 전체 등급이 검토 권장 이상인 비율과 그것이 뜻 때문인 비율."""
    total = len(rows)
    raised = [row for row in rows if at_least(row["전체_등급"], REVIEW)]
    by_meaning = [row for row in raised if row.get("뜻_때문")]
    return {
        "질의": total,
        "뜻이_있다고_판정": share(sum(row["질의_뜻"] for row in rows), total),
        "뜻_점수_최대": quantiles([row["뜻_점수"] for row in rows]),
        "단독_규칙": share(sum(row["단독_규칙"] for row in rows), total),
        "전체_등급": distribution([row["전체_등급"] for row in rows]),
        "전체_검토_권장_이상": share(len(raised), total),
        "그중_뜻_때문": share(len(by_meaning), total),
        "뜻_때문_건수": len(by_meaning),
    }


class X3Off:
    """같은 프로세스에서 관념 축을 잠깐 끈다(엔진이 config.X3_ENABLED 를 요청마다 읽는다)."""

    def __init__(self, ms):
        self.config = ms.config

    def __enter__(self):
        self.previous = self.config.X3_ENABLED
        self.config.X3_ENABLED = False

    def __exit__(self, *_):
        self.config.X3_ENABLED = self.previous


def probe(ms, query: str, goods: list[str] | None, original_ids: set[str]) -> dict:
    """질의 하나 — 후보 풀(정렬)에서 원래 상표의 순위·카드, 풀의 뜻 점수, 전체 등급(top_k 5)."""
    pooled = ms.search_pool(image=None, name=query, goods_codes=goods)
    overall = ms.multi_search(image=None, name=query, goods_codes=goods,
                              top_k=TOP_SHOWN).to_dict()["overall"]
    rank = card = None
    for index, candidate in enumerate(pooled.candidates, start=1):
        if candidate.id in original_ids:
            rank, card = index, candidate
            break
    scores = [c.axes.get("x3") for c in pooled.candidates if c.axes.get("x3") is not None]
    fired = [c for c in pooled.candidates if "standalone_x3" in c.rule_triggers]
    return {
        "전체_등급": overall["grade"], "유명_상표_바닥": bool(overall.get("famous_floor")),
        "순위": rank, "카드_등급": card.grade if card else None,
        "카드_뜻_점수": card.axes.get("x3") if card else None,
        "카드_규칙": list(card.rule_triggers) if card else [],
        "풀": len(pooled.candidates), "풀_뜻_점수_최대": max(scores) if scores else None,
        "풀_단독_규칙": len(fired),
        "앞_5": [[c.title, c.grade, c.axes.get("x3"), list(c.rule_triggers)]
                for c in pooled.candidates[:TOP_SHOWN]],
        "이름": pooled.split_name or pooled.query_name,
    }


def pair_meaning(ms, query: str, original: str, goods: list[str] | None,
                 codes_b: list[str]) -> dict:
    """원래 상표가 풀에 없을 때 — 엔진과 같은 함수로 쌍의 뜻 점수."""
    model = ms.state.model
    axes = ms.compute_pair_axes(query, original, model=ms.state.distinct, goods_a=goods,
                                goods_b=codes_b or None, x3_enabled=True,
                                spelling_version=rm.spelling_version(model),
                                weak_run_version=rm.weak_run_version(model))
    return {"뜻_점수": axes.x3, "양쪽에_뜻": axes.has_meaning_both}


def run_bundles(ms, bundles: dict, models: dict[str, dict], records_by_id: dict[str, dict],
                limit: int | None) -> dict:
    """1절 — 묶음 × 방식 × 세 경우. 관념 축을 끈 검색은 지금(a)에서만(뜻 때문인지 가르는 데)."""
    from scripts import nameless_shared_threshold as ns

    tau = float(models["a"]["standalone_thresholds"]["x3_d"])
    floor = float(ms.config.X3_MIN_SCORE)
    out: dict = {}
    for bundle in BUNDLES:
        items = bundles[bundle][:limit]
        found = bundle in FOUND_BUNDLES
        rows: dict = {mode: {label: [] for label in models} for mode in MODES}
        for item in items:
            ids = set(item.get("원래_ids") or [])
            query_meaning = bool(x3.has_meaning(item["질의"]))
            for mode in MODES:
                goods = (item.get("업종") or None) if mode == "이름+업종" else None
                with X3Off(ms), ns.using_model(ms, models["a"]):
                    off = probe(ms, item["질의"], goods, ids)
                for label, model in models.items():
                    with ns.using_model(ms, model):
                        seen = probe(ms, item["질의"], goods, ids)
                        row = {"질의": item["질의"], "질의_뜻": query_meaning,
                               "전체_등급": seen["전체_등급"],
                               "유명_상표_바닥": seen["유명_상표_바닥"],
                               "앞_5": seen["앞_5"],
                               "관념_끔_전체_등급": off["전체_등급"]}
                        if found:
                            original_goods = item.get("업종") or []
                            if seen["순위"] is not None:
                                score, both = seen["카드_뜻_점수"], seen["카드_뜻_점수"] is not None
                            else:
                                pair = pair_meaning(ms, seen["이름"], item["원래_이름"], goods,
                                                    original_goods)
                                score, both = pair["뜻_점수"], pair["양쪽에_뜻"]
                            fired = ("standalone_x3" in seen["카드_규칙"]
                                     if seen["순위"] is not None
                                     else bool(both and score is not None and score >= tau))
                            row.update({
                                "원래": item["원래_이름"], "순위": seen["순위"],
                                "카드_등급": seen["카드_등급"], "뜻_점수": score,
                                "쌍_뜻": bool(both),
                                "단독_규칙": bool(fired), "관념_끔_순위": off["순위"],
                                "갈래": f"{item.get('범위', '')}·{item.get('소리', '')}".strip("·"),
                                "어긋남": miss_type(query_meaning=query_meaning,
                                                  pair_meaning=bool(both), score=score,
                                                  in_pool=seen["순위"] is not None,
                                                  rank=seen["순위"], card_grade=seen["카드_등급"],
                                                  pool_floor=floor)})
                        else:
                            row.update({
                                "뜻_점수": seen["풀_뜻_점수_최대"],
                                "단독_규칙": seen["풀_단독_규칙"] > 0,
                                "뜻_때문": at_least(seen["전체_등급"], REVIEW)
                                and not at_least(off["전체_등급"], REVIEW)})
                    rows[mode][label].append(row)
        out[bundle] = rows
        print(f"    {bundle} {len(items)}", flush=True)
    return out


def summarize_bundles(rows: dict) -> dict:
    out: dict = {}
    for bundle, by_mode in rows.items():
        summarize = summarize_found if bundle in FOUND_BUNDLES else summarize_control
        out[bundle] = {mode: {label: summarize(items) for label, items in by_label.items()}
                       for mode, by_label in by_mode.items()}
        if bundle == "가_번역어":
            now = by_mode["이름만"]["a"]
            out[bundle]["갈래별(이름만·지금)"] = {
                kind: summarize_found([row for row in now if row["갈래"] == kind])
                for kind in sorted({row["갈래"] for row in now})}
    return out


def bundle_examples(rows: dict, per_type: int = 20) -> dict:
    """기대와 어긋난 사례(지금 — a) — (가)(나)는 까닭별로 많은 순, 대조 묶음은 뜻 때문에 오른 것."""
    out: dict = {}
    for bundle, by_mode in rows.items():
        out[bundle] = {}
        for mode, by_label in by_mode.items():
            items = by_label["a"]
            if bundle in FOUND_BUNDLES:
                grouped: dict[str, list[dict]] = {}
                for row in items:
                    if row["어긋남"]:
                        grouped.setdefault(row["어긋남"], []).append(
                            {key: row[key] for key in ("질의", "원래", "갈래", "뜻_점수", "순위",
                                                      "카드_등급", "전체_등급", "관념_끔_순위")})
                ordered = sorted(grouped.items(), key=lambda pair: -len(pair[1]))
                out[bundle][mode] = {kind: {"건수": len(found), "예": found[:per_type]}
                                     for kind, found in ordered}
            else:
                raised = [{key: row[key] for key in ("질의", "전체_등급", "관념_끔_전체_등급",
                                                    "뜻_점수", "앞_5")}
                          for row in items if row.get("뜻_때문")]
                out[bundle][mode] = {"뜻_때문에_오른_것": {"건수": len(raised),
                                                     "예": raised[:per_type]}}
    return out


# ---- 4절(엔진) ---------------------------------------------------------------------------------

def run_control(context: dict, control: dict, models: dict, limit: int | None) -> dict:
    """지어낸 이름 대조군 기준용 × 네 방식 — 검토 권장 이상 비율(search_pool 앞 5 의 최댓값)."""
    from scripts import named_goods_product as ngp

    a_by_key = {query.key: query for query in context["A"]}
    grades = {mode: {label: [] for label in models} for mode, _, _ in ngp.MODES}
    for item in ngp.control_items(control, "기준용", limit):
        image = context["service"](a_by_key[item["이미지"]].path.read_bytes())
        goods = sorted(item["유사군"]) or None
        for mode, with_image, with_goods in ngp.MODES:
            entry = ngp.search(context, models, None, name=item["이름"],
                               image=image if with_image else None,
                               goods_codes=goods if with_goods else None)
            for label in models:
                grades[mode][label].append(entry[label]["전체"])
    return {mode: {label: {"질의": len(found), "검토_권장_이상": share(
        sum(at_least(grade, REVIEW) for grade in found), len(found)),
        "위험": share(sum(grade == RISK for grade in found), len(found)),
        "등급": distribution(found)} for label, found in by_label.items()}
        for mode, by_label in grades.items()}


def cited_grades(context: dict, baseline_keys: set[tuple], models: dict) -> dict:
    """표본 A 인용상표 쌍 가운데 기준용인 쌍의 등급 분포 — 양쪽에 뜻이 있는 쌍은 따로."""
    from scripts import goods_cap as gc
    from scripts import named_goods_product as ngp

    case_ids = {query.key.split(":")[1] for query in context["A"]}
    pairs = [pair for pair in gc.cited_pairs(case_ids)
             if (pair["심판번호"], str(pair["상대번호"]), pair["쌍키"]) in baseline_keys]
    meaning = [bool(rm.design_values(pair["특징"])["miss_x3"] == 0.0) for pair in pairs]
    out: dict = {"쌍": len(pairs), "양쪽에_뜻이_있는_쌍": sum(meaning),
                 "유사": sum(1 for pair in pairs if pair["라벨"] == "유사")}
    for label, model in models.items():
        grades = [ngp.engine_grade(pair["특징"], model) for pair in pairs]
        both = [grade for grade, has in zip(grades, meaning) if has]
        out[label] = {"등급": distribution(grades),
                      "검토_권장_이상": share(sum(at_least(g, REVIEW) for g in grades),
                                           len(grades)),
                      "등급_양쪽에_뜻이_있는_쌍": distribution(both),
                      "검토_권장_이상_양쪽에_뜻이_있는_쌍": share(
                          sum(at_least(g, REVIEW) for g in both), len(both))}
    return out


def _title_grade(candidate: dict | None) -> list:
    return [(candidate or {}).get("title"), (candidate or {}).get("grade")]


def scenario_changes(scenarios: dict) -> dict:
    """시나리오 16종 — 지금(a)과 견줘 전체 등급·1위가 바뀐 것."""
    out: dict = {}
    for label, runs in scenarios.items():
        if label == "a":
            continue
        changed = []
        for key, now in scenarios["a"].items():
            new = runs.get(key) or {}
            if now.get("건너뜀") or new.get("건너뜀"):
                continue
            top_now = now["상위"][0] if now["상위"] else None
            top_new = new["상위"][0] if new["상위"] else None
            same_top = (top_now or {}).get("id") == (top_new or {}).get("id") and (
                top_now or {}).get("grade") == (top_new or {}).get("grade")
            if now["전체"]["grade"] != new["전체"]["grade"] or not same_top:
                changed.append({"시나리오": key, "제목": now["제목"],
                                "전체": [now["전체"]["grade"], new["전체"]["grade"]],
                                "1위": [_title_grade(top_now), _title_grade(top_new)]})
        out[label] = {"시나리오": len(scenarios["a"]), "바뀐_것": changed}
    return out


# ---- 1절 (바) 도형과 이름 ----------------------------------------------------------------------

def figure_object(codes) -> tuple[str, str] | None:
    """표장의 비엔나 코드 → 그린 사물(영어, 한글). 사물이 정확히 하나일 때만."""
    names = {FIGURE_OBJECTS[code] for code in codes if code in FIGURE_OBJECTS}
    return next(iter(names)) if len(names) == 1 else None


def pick_figures(marks: list[dict], *, per_object: int = FIGURE_PER_OBJECT) -> list[dict]:
    """도형 표장(유형 사전) 가운데 사물이 하나로 정해지는 것 — 사물마다 출원번호 순으로 몇
    개까지."""
    taken: Counter = Counter()
    out = []
    for mark in sorted(marks, key=lambda m: m["id"]):
        found = figure_object(mark["codes"])
        if found is None or taken[found[0]] >= per_object:
            continue
        taken[found[0]] += 1
        out.append({**mark, "사물": found[0], "사물_한글": found[1]})
    return out


def pair_auc(similarity: np.ndarray, own: np.ndarray, weights: np.ndarray | None = None) -> float:
    """맞는 짝(similarity[i, own[i]]) 대 틀린 짝(그 표장과 다른 사물 전부)의 AUC(동점 0.5)."""
    n, k = similarity.shape
    weights = np.ones(n) if weights is None else weights
    positive = similarity[np.arange(n), own]
    mask = np.ones((n, k), dtype=bool)
    mask[np.arange(n), own] = False
    wins = total = 0.0
    for i in range(n):  # 맞는 짝 하나를 모든 틀린 짝과 견준다
        if weights[i] == 0:
            continue
        greater = (positive[i] > similarity) & mask
        equal = (positive[i] == similarity) & mask
        row_weight = weights[:, None] * mask
        wins += weights[i] * float((row_weight * (greater + 0.5 * equal)).sum())
        total += weights[i] * float(row_weight.sum())
    return wins / total if total else float("nan")


def figure_metrics(similarity: np.ndarray, own: np.ndarray, *, rounds: int = BOOTSTRAP,
                   seed: int = SEED) -> dict:
    n = similarity.shape[0]
    rng = np.random.default_rng(seed)
    draws = np.asarray([pair_auc(similarity, own, np.bincount(rng.integers(0, n, n), minlength=n)
                                 .astype(float)) for _ in range(rounds)])
    top1 = float(np.mean(similarity.argmax(axis=1) == own))
    positive = similarity[np.arange(n), own]
    mask = np.ones_like(similarity, dtype=bool)
    mask[np.arange(n), own] = False
    return {"AUC": _round(pair_auc(similarity, own)),
            "ci95": [_round(np.percentile(draws, 2.5)), _round(np.percentile(draws, 97.5))],
            "맞는_사물이_1위": _round(top1), "무작위_1위": _round(1.0 / similarity.shape[1]),
            "맞는_짝_평균": _round(positive.mean()),
            "틀린_짝_평균": _round(similarity[mask].mean())}


# ---- 명령 --------------------------------------------------------------------------------------

def _paths(archive: Path) -> dict[str, Path]:
    return {"source": archive / "bundles_source.json", "bundles": archive / "bundles.json",
            "config": TRIALS / f"{STEM}_config.json", "offline": TRIALS / f"{STEM}_offline.json",
            "engine": TRIALS / f"{STEM}_engine.json", "figure": TRIALS / f"{STEM}_figure.json",
            "report": TRIALS / f"{STEM}_report.md",
            "pair_types": archive / "pair_types.json",
            "pair_list": archive / "pairs_to_classify.json",
            "pair_examples": archive / "pair_examples.json",
            "bundle_examples": archive / "bundle_examples.json",
            "bundle_rows": archive / "bundle_rows.json", "figures": archive / "figure_marks.json"}


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _inputs() -> dict[str, Path]:
    from scripts import train_risk_model as tr

    return {"특징": tr.DEFAULT_FEATURES, "쉬운_음성": tr.DEFAULT_EASY,
            "모델": rm.DEFAULT_MODEL_PATH,
            "대조군": CONTROL, "메타데이터": METADATA, "유형_사전": TYPES}


def command_bundles(args) -> int:
    from src.axes import distinctiveness as dx

    paths = _paths(args.archive)
    source = json.loads(paths["source"].read_text(encoding="utf-8"))
    records = load_records()
    control = json.loads(CONTROL.read_text(encoding="utf-8"))["대조군"]["이름"]["기준용"]
    bundles, problems = resolve_bundles(
        source, records, weak_records=weak_token_records(records, dx.load_distinctiveness()),
        control=control, presets=load_presets())
    print(json.dumps({name: len(items) for name, items in bundles.items()}, ensure_ascii=False))
    for problem in problems:
        print("문제:", problem)
    if problems:
        return EXIT_STOP
    _write(paths["bundles"], bundles)
    print("묶음 sha256", file_sha256(paths["bundles"]))
    return 0


def command_freeze(args) -> int:
    paths = _paths(args.archive)
    if paths["config"].exists() and not args.force:
        print(f"거절: {paths['config']} 가 있습니다(--force — 결과를 본 뒤라면 보고할 것)",
              file=sys.stderr)
        return EXIT_REFUSED
    bundles_sha = file_sha256(paths["bundles"])
    config = {"설정_sha256": settings_sha256(bundles_sha), "고정한_때": _now(),
              "묶음_sha256": bundles_sha, "설정": SETTINGS,
              "묶음_수": {name: len(items) for name, items in
                       json.loads(paths["bundles"].read_text(encoding="utf-8")).items()},
              "스크립트_sha256": file_sha256(Path(__file__)),
              "입력_sha256": {name: file_sha256(path) for name, path in _inputs().items()}}
    _write(paths["config"], config)
    print("설정 sha256", config["설정_sha256"])
    return 0


def _frozen(paths: dict) -> dict | None:
    if not paths["config"].exists():
        print("거절: 먼저 freeze", file=sys.stderr)
        return None
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    bundles_sha = file_sha256(paths["bundles"])
    if config["설정_sha256"] != settings_sha256(bundles_sha):
        print("거절: 설정이나 묶음 목록이 고정본과 "
            "다릅니다(freeze --force 는 결과를 본 뒤의 변경 — "
              "보고할 것)", file=sys.stderr)
        return None
    changed = [name for name, path in _inputs().items()
               if file_sha256(path) != config["입력_sha256"].get(name)]
    if changed:
        print(f"거절: 고정한 뒤 입력이 바뀌었습니다: {changed}", file=sys.stderr)
        return None
    return config


def _head(config: dict) -> dict:
    return {"설정_sha256": config["설정_sha256"],
            "스크립트_sha256(고정 때)": config["스크립트_sha256"],
            "스크립트_sha256(잴 때)": file_sha256(Path(__file__)), "시작": _now()}


def command_offline(args) -> int:
    from scripts import train_risk_model_v14 as t4

    paths = _paths(args.archive)
    config = _frozen(paths)
    if config is None:
        return EXIT_REFUSED
    started = time.perf_counter()
    model = rm.load_model(rm.DEFAULT_MODEL_PATH)
    data = load_rows()
    base = baseline_mask(data["y"], data["groups"])
    boot = t4.Bootstrap(data["groups"], args.bootstrap, SEED)
    results = {**_head(config), "모델": model["version"], "표본": split_summary(data, base)}
    results["네_축"] = four_axes(data, base, boot)
    print("  2절 네 축", flush=True)
    results["계수"] = refit(data, base, model, boot)
    print("  3절 계수", flush=True)
    models = case_models(model, results["계수"])
    results["세_경우_계수"] = case_coefficients(model, results["계수"])
    results["세_경우_결합_제약_위반"] = {label: len(rm.coupling_violations(item))
                                  for label, item in models.items()}
    results["쌍_등급"] = pair_grades(data, base, models)
    pairs = mismatched_pairs(data, base, model)
    _write(paths["pair_list"], {key: pairs[key] for key in ("유사인데_낮음", "비유사인데_높음")})
    assigned = (json.loads(paths["pair_types"].read_text(encoding="utf-8"))
                if paths["pair_types"].exists() else {})
    tables = {key: tabulate_pair_types(pairs[key], assigned)
              for key in ("유사인데_낮음", "비유사인데_높음")}
    _write(paths["pair_examples"],
           {"분류": tables, "단독_규칙이_켜진_쌍": pairs["단독_규칙"]["쌍"]})
    results["어긋나는_쌍"] = {
        "양쪽에_뜻이_있는_쌍": pairs["양쪽에_뜻이_있는_쌍"], "기준": {"낮음": LOW, "높음": HIGH},
        "유사인데_낮음": {"쌍": len(pairs["유사인데_낮음"]),
                       "판단축에_관념_없음": sum(other_axis_only(item["판단축"])
                                            for item in pairs["유사인데_낮음"]),
                       "유형": tables["유사인데_낮음"]["건수"],
                       "세부": tables["유사인데_낮음"]["세부"]},
        "비유사인데_높음": {"쌍": len(pairs["비유사인데_높음"]),
                        "판단축에_관념_없음": sum(other_axis_only(item["판단축"])
                                             for item in pairs["비유사인데_높음"]),
                        "유형": tables["비유사인데_높음"]["건수"],
                        "세부": tables["비유사인데_높음"]["세부"]},
        "단독_규칙": {key: value for key, value in pairs["단독_규칙"].items() if key != "쌍"},
        "분류한_쌍": len(assigned)}
    results.update(걸린_시간_s=round(time.perf_counter() - started, 1), 끝=_now())
    _write(paths["offline"], results)
    print(json.dumps({"표본": results["표본"], "세_경우_계수": results["세_경우_계수"]},
                     ensure_ascii=False))
    return 0


def command_engine(args) -> int:
    from scripts import goods_cap as gc
    from scripts import logo_floor_image_only as lo
    from scripts import nameless_shared_threshold as ns

    paths = _paths(args.archive)
    config = _frozen(paths)
    if config is None:
        return EXIT_REFUSED
    if not paths["offline"].exists():
        print("거절: 먼저 offline(다시 맞춘 계수가 있어야 한다)", file=sys.stderr)
        return EXIT_REFUSED
    out_path = args.out or paths["engine"]
    started, timing = time.perf_counter(), {}
    offline = json.loads(paths["offline"].read_text(encoding="utf-8"))
    bundles = json.loads(paths["bundles"].read_text(encoding="utf-8"))
    began = time.perf_counter()
    context = ns._context(rm.DEFAULT_MODEL_PATH)  # noqa: SLF001
    ms = context["ms"]
    lo.memo_ocr(ms)
    base = ms.state.model
    models = {"a": base, **{label: model for label, model in case_models(
        base, offline["계수"]).items() if label != "a"}}
    same_as_now = [label for label in ("b", "c")
                   if all(v == 0.0 for v in offline["세_경우_계수"][label].values())]
    for label in same_as_now:  # 계수가 모두 0 이면 지금과 같다 — 다시 검색하지 않는다
        models.pop(label)
    results = {**_head(config), "모델": base["version"], "스모크": bool(args.limit),
               "세_경우_계수": offline["세_경우_계수"], "지금과_같은_경우": same_as_now}
    timing["엔진"] = round(time.perf_counter() - began, 1)

    began = time.perf_counter()
    records_by_id = {str(record["출원번호"]): record for record in load_records()}
    rows = run_bundles(ms, bundles, models, records_by_id, args.limit)
    results["묶음"] = summarize_bundles(rows)
    if not args.limit:
        _write(paths["bundle_examples"], bundle_examples(rows))
        _write(paths["bundle_rows"], rows)
    timing["1절_묶음"] = round(time.perf_counter() - began, 1)
    print(f"  1절 묶음 {timing['1절_묶음']}초", flush=True)

    began = time.perf_counter()
    control = json.loads(CONTROL.read_text(encoding="utf-8"))
    results["대조군"] = run_control(context, control, models, args.limit)
    timing["4절_대조군"] = round(time.perf_counter() - began, 1)
    print(f"  4절 대조군 {timing['4절_대조군']}초", flush=True)

    data = load_rows()
    mask = baseline_mask(data["y"], data["groups"])
    keys = {(row["심판번호"], str(row.get("상대번호")), row.get("쌍키"))
            for row, keep in zip(data["rows"], mask) if keep}
    results["인용상표"] = cited_grades(context, keys, models)

    began = time.perf_counter()
    scenarios = gc.run_scenarios(context, models, ("S1", "F1") if args.limit else None)
    results["시나리오"] = scenario_changes(scenarios)
    results["시나리오_지금"] = {key: {"제목": item.get("제목"),
                                 "전체": (item.get("전체") or {}).get("grade"),
                                 "1위": ((item.get("상위") or [{}])[0]).get("title")}
                            for key, item in scenarios["a"].items()}
    timing["4절_시나리오"] = round(time.perf_counter() - began, 1)
    results.update(시간_s=timing, 걸린_시간_s=round(time.perf_counter() - started, 1), 끝=_now())
    _write(out_path, results)
    print(json.dumps(timing, ensure_ascii=False))
    return 0


def load_figure_marks() -> list[dict]:
    """유형 사전이 도형인 DB 표장 — id·비엔나 6자리 코드·색인 순번."""
    from scripts import sketch_feasibility as sf

    types = json.loads(TYPES.read_text(encoding="utf-8"))["types"]
    return [{"id": mark.appno, "codes": sorted(mark.codes), "순번": mark.position}
            for mark in sf.load_marks() if (types.get(mark.appno) or {}).get("type") == "도형"]


def command_figure(args) -> int:
    paths = _paths(args.archive)
    config = _frozen(paths)
    if config is None:
        return EXIT_REFUSED
    import open_clip  # noqa: I001 — torch 를 faiss 보다 먼저
    import torch

    from backend.src.core import engine
    from src import embedding

    picked = pick_figures(load_figure_marks())[:args.limit or None]
    objects = sorted({mark["사물"] for mark in picked})
    korean = {mark["사물"]: mark["사물_한글"] for mark in picked}
    own = np.asarray([objects.index(mark["사물"]) for mark in picked])
    engine.load_all()
    images = np.vstack([engine.state.index.reconstruct(int(mark["순번"])) for mark in picked])
    model, _ = embedding._load_model()  # noqa: SLF001
    tokenizer = open_clip.get_tokenizer(embedding.MODEL_NAME)

    def encode(texts: list[str]) -> np.ndarray:
        with torch.no_grad():
            vectors = model.encode_text(tokenizer(texts).to(embedding.DEVICE)).cpu().numpy()
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    prompts = {"문장(주)": [FIGURE_PROMPT.format(name=name) for name in objects],
               "낱말만(참고)": list(objects),
               "한글_낱말(참고)": [korean[name] for name in objects]}
    results = {**_head(config), "이미지_모델": f"{embedding.MODEL_NAME}/{embedding.PRETRAINED}",
               "표장": len(picked), "사물": len(objects),
               "사물별_표장": dict(Counter(mark["사물"] for mark in picked).most_common()),
               "글자": {}}
    for label, texts in prompts.items():
        similarity = images @ encode(texts).T
        results["글자"][label] = {"예": texts[:3], **figure_metrics(similarity, own,
                                                                rounds=args.bootstrap)}
        if label == "문장(주)":
            order = similarity.argsort(axis=1)[:, ::-1]
            _write(paths["figures"], [{"id": mark["id"], "사물": mark["사물"],
                                       "맞는_짝": _round(similarity[i, own[i]]),
                                       "가장_가까운_이름": [objects[j] for j in order[i, :3]]}
                                      for i, mark in enumerate(picked)])
    results["끝"] = _now()
    _write(args.out or paths["figure"], results)
    print(json.dumps(results["글자"], ensure_ascii=False))
    return 0


def report_text(offline: dict | None, engine: dict | None, figure: dict | None) -> str:
    lines = ["# 관념 축 진단 — 결과 표", ""]
    if offline:
        lines += [f"설정 sha256 `{offline['설정_sha256']}` · 모델 {offline['모델']}", "",
                  "## 표본", "", "```json",
                  json.dumps(offline["표본"], ensure_ascii=False, indent=1),
                  "```", "", "## 2절 네 축(AUC·95% 구간)", "",
                  "| 축 | 분쟁 쌍 전체 | 잴 수 있는 쌍 | 현실 분포 |", "|---|---|---|---|"]
        for label, by_sample in offline["네_축"]["축"].items():
            cells = [f"{item['auc']} ({item['ci95'][0]}–{item['ci95'][1]}) n={item['n']}"
                     if item.get("auc") is not None else "—" for item in by_sample.values()]
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
        lines += ["", "관념 − 철자:", ""]
        for name, item in offline["네_축"]["관념−철자"].items():
            lines.append(f"- {name}: {item['차이']} "
                f"({item['ci95'][0]}–{item['ci95'][1]}), n={item['n']}")
        lines += ["", "## 3절 관념 계수", "",
                  "| 세트 | 행(분쟁·쉬운 음성) | 뜻 있는 분쟁 "
                  "쌍 | 다시 맞춘 값 | 95% 구간 | 0 에 붙는 비율 "
                  "| 제약 없이 | 철자 계수 |", "|---|---|---:|---:|---|---:|---:|---:|"]
        for key, item in offline["계수"]["세트"].items():
            lines.append(
                f"| {key} | {item['행']}({item['분쟁_쌍']}·{item['쉬운_음성']}) | "
                f"{item['양쪽에_뜻이_있는_분쟁_쌍']} | {item['다시_맞춘_값']} | "
                f"{item['ci95'][0]}–{item['ci95'][1]} | {item['0에_붙는_비율']} | "
                f"{item['참고_제약_없이']} | {item['철자_계수']} |")
        lines += ["", "## 4절 분쟁 쌍 등급(기준용, 이름 있는 쌍)", "", "```json",
                  json.dumps(offline["쌍_등급"], ensure_ascii=False, indent=1), "```", "",
                  "## 5절 어긋나는 쌍", "", "```json",
                  json.dumps(offline["어긋나는_쌍"], ensure_ascii=False, indent=1), "```", ""]
    if engine:
        lines += ["## 1절 묶음", "", "```json",
                  json.dumps(engine["묶음"], ensure_ascii=False, indent=1), "```", "",
                  "## 4절 대조군·인용상표·시나리오", "", "```json",
                  json.dumps({key: engine[key] for key in ("대조군", "인용상표", "시나리오")},
                             ensure_ascii=False, indent=1), "```", ""]
    if figure:
        lines += ["## 1절 (바) 도형과 이름", "", "```json",
                  json.dumps({key: figure[key] for key in ("표장", "사물", "글자")},
                             ensure_ascii=False, indent=1), "```", ""]
    return "\n".join(lines) + "\n"


def command_report(args) -> int:
    paths = _paths(args.archive)
    loaded = [json.loads(paths[name].read_text(encoding="utf-8")) if paths[name].exists() else None
              for name in ("offline", "engine", "figure")]
    paths["report"].write_text(report_text(*loaded), encoding="utf-8")
    print(paths["report"])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--archive", type=Path, default=ARCHIVE,
                        help="저장소 밖 폴더(묶음 목록·실제 쌍의 예시)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bundles")
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--force", action="store_true")
    offline = sub.add_parser("offline")
    offline.add_argument("--bootstrap", type=int, default=BOOTSTRAP)
    engine = sub.add_parser("engine")
    engine.add_argument("--limit", type=int, default=None, help="스모크 — 묶음·대조군마다 앞 몇 개")
    engine.add_argument("--out", type=Path, default=None)
    figure = sub.add_parser("figure")
    figure.add_argument("--limit", type=int, default=None)
    figure.add_argument("--bootstrap", type=int, default=BOOTSTRAP)
    figure.add_argument("--out", type=Path, default=None)
    sub.add_parser("report")
    args = parser.parse_args(argv)
    return {"bundles": command_bundles, "freeze": command_freeze, "offline": command_offline,
            "engine": command_engine, "figure": command_figure, "report": command_report}[
                args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
