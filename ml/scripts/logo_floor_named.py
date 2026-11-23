"""견고성 점검 R-P0-1 — 이름 있는 이미지 질의에도 로고만 판단과 견주기(nameless_floor 넓히기)의
확인 표본·채택 조건(지시로 고정, 2026-11-23). 바꾸는 것: 이미지가 있는 이름 있는 질의에서 후보마다
같은 입력에서 이름을 뺀 판단(로고만, 업종이 있으면 로고+업종 — 이름 없는 계수·기준·업종 하한 그대로,
유형은 이름 없이 넣었을 때의 유형)도 계산해 등급이 높은 쪽(같으면 원래 판단)과 높은 정렬 위치를
쓴다. 질의 이미지가 사진이면 견주지 않는다(유형을 도형계로 고친 질의는 예전처럼 견준다). 계수 JSON
(v1.4.1)은 그대로다.

    ml/venv/bin/python ml/scripts/logo_floor_named.py freeze   # 0. 규칙·입력·엔진 소스 해시
    ml/venv/bin/python ml/scripts/logo_floor_named.py run      # 1. 실제 엔진 검색 — 바꾸기 전·후
    ml/venv/bin/python ml/scripts/logo_floor_named.py report   # 2. 채택 ①–④·전후 표

바꾸기 전 = 같은 프로세스에서 multi_search.make_context 의 nameless_floor 만 예전 범위(사용자가
유형을 도형계로 고친 질의)로 되돌린 엔진 — 새 코드는 예전 범위에서 예전과 같은 값을 낸다(이름 없이
넣었을 때의 유형 = 그 질의의 유형). run 이 먼저 시나리오 16종을 v1.4.1 확인 실행
(named_shared_threshold verify)의 저장값과 견줘 검산하고, 다르면 멈춘다. 산출(비공개):
ml/data/trials/logo_floor_named_{rule,results}.json·_searches.json.gz·_report.md. 고정본과 다르면
거절(종료 코드 4), 검산 불일치·채택 미달이면 종료 코드 3. KIPRIS 호출 0.
"""

from __future__ import annotations

import argparse
import dataclasses
import gzip
import hashlib
import json
import random
import statistics
import subprocess
import sys
import tempfile
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

from src.model import risk_model as rm  # noqa: E402

from scripts import named_search_thresholds as first  # noqa: E402

TRIALS = ML_ROOT / "data" / "trials"
STEM = "logo_floor_named"
EXIT_STOP = 3
EXIT_REFUSED = 4
REVIEW, RISK = "검토 권장", "위험"
SEED = 0
MODEL_VERSION = "risk_model_v1.4.1"
BASE_COMMIT = "3685a1e"  # 바꾸기 전 develop(PR #108 병합)
CONTROL_SHA = "f6b11d62b4ced35c73774c6a5a5e7701488cc4d8ce374b316379fd16983bf3f5"  # 1차 시도 대조군
N_POSITIVE = 200
LANGS = ("ko", "en")  # 양성 i 번째 이름의 언어 = LANGS[i % 2]
ACCEPT_COS = 0.95  # 인정 상표: 같은 출원인 + 원래 이미지와 CLIP 코사인 이상
GOODS_CAP = 60  # API 유사군 상한 — 원래 상표 유사군이 더 많으면 정렬해 앞 60
DISPLAY_TOP = first.DISPLAY_TOP  # 5 — 전체 등급 = 엔진 정렬 앞 5건의 최고 등급(엔진 _overall)
MARGIN_1 = 0.02
MARGIN_2 = {REVIEW: 0.05, RISK: 0.02}
PRECISION_MIN = first.PRECISION_MIN  # 0.70
NAMELESS_LEVEL_OFFLINE = "도형"  # 자동 유형의 이름 없는 질의는 늘 도형계(결합-도형요부와 같은 값)
SAVED_SCENARIOS = TRIALS / "named_shared_threshold_scenarios_default.json"
COMBOS = (("이름+이미지", False), ("이름+이미지+업종", True))  # 음성(대조군 확인용) 방식

# 규칙(이 지시로 고정 — 실행 전에 해시를 남기고 결과를 보고 바꾸지 않는다) ------------------------
RULE = {
    "변경": (
        "backend/src/core/multi_search.py: 이름 + 이미지 질의(질의 이미지가 사진이면 사용자가 "
        "유형을 도형계로 고친 질의만 — 예전 범위는 그대로 남김)에서 후보마다(상표명 없는 후보 "
        "포함) 같은 입력에서 이름을 뺀 판단 = _nameless_judgment(이름 축 결측·요부 True, "
        "x2_whole = 그 후보 이미지 유사도, 업종은 질의 그대로 — 업종 하한 적용)을 계산해 등급이 "
        "높으면 그쪽(rule_triggers 에 nameless_floor, prob·기여도·pattern 은 그쪽 것), 같으면 "
        "원래 판단. 정렬 위치는 둘 중 높은 쪽. 이름을 뺀 판단의 유형 = 같은 입력에서 이름을 뺀 "
        "질의가 받을 유형(nameless_level — 사용자 유형은 결합 → 결합-도형요부·문자·도형 그대로, "
        "자동 유형은 OCR 글자 영역 ≥ 0.05 면 결합-도형요부, 그 밖·OCR 실패면 도형). 계수 JSON 은 "
        "그대로."),
    "바꾸기_전": (
        "같은 프로세스에서 multi_search.make_context 를 감싸 nameless_floor 만 예전 범위(질의 "
        "유형 출처 user·유형 도형계·이름·이미지)로 되돌린다. 예전 범위에서는 nameless_level 이 "
        "그 질의 유형과 같아 새 코드가 예전 코드(develop 3685a1e)와 같은 값을 낸다. 검산: "
        "시나리오 16종의 바꾸기 전 결과(전체 grade·prob·pattern, 상위 5 출원번호)가 v1.4.1 확인 "
        "실행 저장값(named_shared_threshold_scenarios_default.json)과 모두 같아야 한다 — 다르면 "
        "멈춤."),
    "검색": (
        "실제 엔진(multi_search.search_pool, 기본 모델 v1.4.1, CLIP·OCR·X3). 같은 질의를 바꾸기 "
        "전·후로 한 번씩, 질의 순번이 짝수면 전→후·홀수면 후→전(캐시 데움 차이를 상쇄). OCR "
        "판정은 이미지마다 첫 호출 값을 다시 쓴다(2초 시간 제한으로 한쪽만 폴백하는 것을 막음). "
        "전체 등급 = 엔진 정렬 앞 5건의 최고 표시 등급. 이미지만(+업종) 질의도 전·후 둘 다 돌려 "
        "같은지 본다."),
    "양성_표본": (
        "색인에 이미지가 있고(pos) 그 색인 임베딩이 사진이 아닌(multi_search.is_photo_query) DB "
        "레코드를 출원번호 순으로 정렬해 random.Random(0).shuffle 한 순서에서, 이미지 파일이 "
        "서비스 업로드 경로(validation.validate_and_decode)를 통과하는 앞 200. 질의 이미지 = 그 "
        "파일을 그 경로로 디코딩한 것."),
    "양성_이름": (
        "1차 시도 대조군 생성 규칙(named_search_thresholds.name_stream — WORDS·TEMPLATES, "
        "random.Random('0|<언어>'), 언어마다 600개)의 이름. 양성 i 번째(표본 순서)는 언어 "
        "LANGS[i % 2](ko·en), 그 언어 흐름에서 아직 안 쓴 이름을 앞에서부터 보며 원래 상표명과 "
        "단독 축 규칙(standalone_hits — compute_pair_axes(이름, 원래 상표명, 질의 업종, 원래 "
        "유사군, X3 켬) → model_features(유형 문자))이 업종 두 맥락(없음·원래 유사군) 모두에서 "
        "안 걸리는 첫 이름. 원래 상표명이 없으면 안 쓴 첫 이름."),
    "양성_업종": (
        "두 방식 — 없음 / 원래 상표의 유사군(엔진 레코드 goods — 형식 필터 뒤, 60개가 넘으면 "
        "정렬해 앞 60: API 상한)."),
    "인정_상표": (
        "원래 상표 + 같은 출원인(출원인 칸 '|' 나눔·정규화·별칭 표, "
        "nameless_search_thresholds.split_applicants 가 겹침)이면서 색인 임베딩 코사인이 원래 "
        "상표와 0.95 이상인 상표."),
    "음성": (
        "1차 시도 대조군 확인용 100(named_search_thresholds_control.json 의 '확인용', 대조군 "
        "sha256 f6b11d62…) 그대로 — 이름·이미지(표본 A 저유사 이미지, 서비스 경로 디코딩)·업종 "
        "세트. 방식: 이름+이미지, 이름+이미지+업종(채택 ②), 비교용 이미지, 이미지+업종(채택 ③)."),
    "표본A": (
        "nameless_search_thresholds.prepare 의 표본 A 질의 전부(이름·이미지 있음, 사진 아님) — "
        "이름+이미지(+질의 업종이 있으면 업종) 바꾸기 전·후, 비교용 이미지(+업종). 인용상표 "
        "등급·위험 정밀도는 1차 시도 채택_4 와 같은 쌍(학습 특징의 그 사건 행 중 두 이름이 다 "
        "있는 행, 서비스 채점식 — 유형 결합-문자요부(이미지 있음)·문자, 이미지 축 원래 값)으로: "
        "바꾸기 전 = 그 등급, 후 = 이미지 축이 있으면 이름을 뺀 판단(유형 도형, 이미지·업종 축 "
        "그 행 값, 업종 하한)과 견준 높은 등급. 위험 정밀도 = 위험인 쌍 중 유사 라벨 "
        "비율(보고만)."),
    "시나리오": (
        "named_shared_threshold.SCENARIOS 16종(입력 그대로, S5 는 S3 의 OCR 제안 이름) — "
        "multi_search(top_k 5) 바꾸기 전·후, 전체 등급·위험도·상위 5."),
    "채택_1": (
        "양성, 업종 방식마다: 인정 상표가 상위 5 안에 표시 등급 검토 권장 이상으로 나온 질의 "
        "비율 — 이름+이미지(+업종) 바꾼 뒤 ≥ 같은 이미지(+업종)만 넣은 질의 − 0.02."),
    "채택_2": (
        "음성, 방식(이름+이미지·이름+이미지+업종)마다: 전체 등급이 검토 권장 이상인 질의 비율의 "
        "증가(바꾼 뒤 − 바꾸기 전) ≤ 0.05, 위험 이상 증가 ≤ 0.02."),
    "채택_3": (
        "(가) 바꾼 뒤 이름을 더한 질의의 전체 등급 < 같은 이미지(+같은 업종)만 넣은 질의의 전체 "
        "등급인 경우 0 — 양성(두 업종 방식)·음성(두 방식)·표본 A 전부 (나) 기존 단조성 검사 — "
        "계수 집합마다 rm.monotone_violations 0, rm.coupling_violations 0(계수 그대로)."),
    "채택_4": (
        "위험 정밀도 = 1차 시도 채택_2 방식(v1.3 학습을 학습 입력 사본 "
        "~/marklens-archive/trials-backup-20261119-enrich 로 다시 돌린 OOF 위험도, 심결+cross+db "
        "행, 위험 하한 0.5902 — 재현 하한·정밀도가 v1.3 JSON 과 다르면 멈춤)에 이 비교를 더함: "
        "이미지 축이 있고(x2_whole) 질의 쪽이 사진이 아닌 행(사진A — 지금 특징 파일 "
        "pairs_features{,_easy}.csv 를 (pair_source·심판번호·상대번호)로 맞춤, 맞는 행이 없으면 "
        "사진 아님)은 이름을 뺀 판단(배포 v1.4.1 이름 없는 계수·기준·업종 하한, 유형 도형, "
        "이미지·업종 축 그 행 값)이 위험이어도 위험. 위험인 행의 유사 비율 ≥ 0.70."),
    "보고": (
        "전후 표 — 양성(상위 5 검토 권장 이상 비율·원래 상표 순위), 음성(등급 분포), 표본 A "
        "인용상표 등급 분포, 시나리오 16종 등급 변화, 질의당 시간(이름+이미지 질의의 search_pool "
        "전체·모델 단계 ms)."),
}


def _settings() -> dict:
    return {"RULE": RULE, "SEED": SEED, "MODEL_VERSION": MODEL_VERSION,
            "BASE_COMMIT": BASE_COMMIT, "CONTROL_SHA": CONTROL_SHA, "N_POSITIVE": N_POSITIVE,
            "LANGS": LANGS, "ACCEPT_COS": ACCEPT_COS, "GOODS_CAP": GOODS_CAP,
            "DISPLAY_TOP": DISPLAY_TOP, "MARGIN_1": MARGIN_1, "MARGIN_2": MARGIN_2,
            "PRECISION_MIN": PRECISION_MIN, "NAMELESS_LEVEL_OFFLINE": NAMELESS_LEVEL_OFFLINE,
            "COMBOS": COMBOS, "N_PER_LANG×STREAM_FACTOR": first.N_PER_LANG * first.STREAM_FACTOR}


def rule_sha256() -> str:
    return first.canonical_sha256(_settings())


def _inputs() -> dict[str, Path]:
    from scripts import nameless_search_thresholds as nst

    return {"계수_JSON": rm.V141_MODEL_PATH, "v1.3_JSON": rm.V13_MODEL_PATH,
            "대조군": first._paths(TRIALS)["control"], "메타데이터": nst.DEFAULT_METADATA,
            "색인": ML_ROOT / "data" / "index" / "kipris.faiss",
            "색인_manifest": ML_ROOT / "data" / "index" / "kipris_manifest.json",
            "유형_사전": ML_ROOT / "data" / "types.json", "라벨": nst.DEFAULT_LABELS,
            "심판_목록": nst.DEFAULT_LIST, "이미지_쌍": nst.DEFAULT_IMAGE_PAIRS,
            "별칭": nst.DEFAULT_ALIASES,
            "v1.3_학습_특징": first.V13_INPUTS / "pairs_features.csv",
            "v1.3_학습_쉬운_음성": first.V13_INPUTS / "pairs_features_easy.csv",
            "특징(사진 열)": TRIALS / "pairs_features.csv",
            "쉬운_음성(사진 열)": TRIALS / "pairs_features_easy.csv",
            "시나리오_저장값": SAVED_SCENARIOS,
            "엔진": REPO_ROOT / "backend" / "src" / "core" / "multi_search.py"}


def _paths(out_dir: Path) -> dict[str, Path]:
    return {"rule": out_dir / f"{STEM}_rule.json", "searches": out_dir / f"{STEM}_searches.json.gz",
            "results": out_dir / f"{STEM}_results.json", "report": out_dir / f"{STEM}_report.md"}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _base_blob() -> str | None:
    try:
        spec = f"{BASE_COMMIT}:backend/src/core/multi_search.py"
        return subprocess.run(["git", "rev-parse", spec], cwd=REPO_ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


# ---- 순수 함수(시험 대상) ----------------------------------------------------------------------

def grade_index(grade: str | None) -> int:
    return -1 if grade is None else rm.GRADES.index(grade)


def at_least(grade: str | None, floor: str) -> bool:
    return grade_index(grade) >= rm.GRADES.index(floor)


def overall_grade(grades: list[str]) -> str | None:
    """엔진 _overall 과 같은 전체 등급 — 표시 순서 앞 5건의 최고 등급(후보가 없으면 None)."""
    shown = grades[:DISPLAY_TOP]
    return max(shown, key=rm.GRADES.index) if shown else None


def old_scope(query_type, name, embedding) -> bool:
    """바꾸기 전(develop 3685a1e) nameless_floor 범위 — 유형을 도형계로 고친 질의 + 이름 +
    이미지."""
    return (query_type.source == "user" and query_type.type in rm.FIGURE_FAMILY
            and name is not None and embedding is not None)


def capped_goods(codes) -> frozenset[str]:
    return frozenset(sorted(codes)[:GOODS_CAP])


def rate(flags: list[bool]) -> float | None:
    return (sum(1 for flag in flags if flag) / len(flags)) if flags else None


def distribution(grades) -> dict[str, int]:
    counts = Counter(grade or "후보 없음" for grade in grades)
    return {key: counts.get(key, 0) for key in [*rm.GRADES, "후보 없음"] if counts.get(key)}


def nameless_offline(x2_whole: float, x4: float | None, model: dict) -> str:
    """이름을 뺀 판단의 최종 등급(엔진 _nameless_judgment — 업종 하한 포함), 유형 도형."""
    features = {"x1_d": None, "x2_text_d": None, "x3_d": None, "x2_whole": float(x2_whole),
                "x4": x4, "has_meaning_both": False, "has_distinctive_part_a": True,
                "has_distinctive_part_b": True, "mark_type": NAMELESS_LEVEL_OFFLINE}
    return first.nameless_final_grade(features, model)


def _number(value) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    return None if np.isnan(number) else number


# ---- 엔진 전환(같은 프로세스) ------------------------------------------------------------------

class Engine:
    """바꾸기 전·후 전환과 OCR 판정 재사용. 전 = make_context 의 nameless_floor 만 예전 범위로."""

    def __init__(self, ms):
        self.ms = ms
        self.new_context = ms.make_context
        self.memo: dict[str, object] = {}
        detect = ms.ocr.detect

        def memo_detect(image, **kwargs):
            key = hashlib.sha1(image.tobytes()).hexdigest() + f"|{image.size}|{image.mode}"
            if key not in self.memo:
                self.memo[key] = detect(image, **kwargs)
            return self.memo[key]

        ms.ocr.detect = memo_detect

    def _old_context(self, name, goods, embedding, query_type, x3_on):
        ctx = self.new_context(name, goods, embedding, query_type, x3_on)
        return dataclasses.replace(ctx, nameless_floor=old_scope(query_type, name, embedding))

    def use(self, mode: str) -> None:
        self.ms.make_context = self.new_context if mode == "후" else self._old_context

    def search(self, mode: str, **inputs):
        self.use(mode)
        started = time.perf_counter()
        pooled = self.ms.search_pool(**inputs)
        return pooled, (time.perf_counter() - started) * 1000.0

    def multi(self, mode: str, **inputs) -> dict:
        self.use(mode)
        return self.ms.multi_search(**inputs, top_k=DISPLAY_TOP).to_dict()


def summarize(pooled, elapsed_ms: float, accepted: set[str] | None = None) -> dict:
    top = pooled.candidates[:DISPLAY_TOP]
    out = {"유형": pooled.query_type.type, "출처": pooled.query_type.source,
           "사진": bool(pooled.query_photo),
           "전체": overall_grade([c.grade for c in pooled.candidates]),
           "상위": [{"id": c.id, "등급": c.grade, "p": round(float(c.prob), 6),
                    "pattern": c.pattern, "규칙": list(c.rule_triggers), "이름": bool(c.title),
                    "x2_img": c.axes["x2_img"], "x4": c.axes["x4"]} for c in top],
           "ms": round(elapsed_ms, 1), "모델_ms": round(float(pooled.timings.get("모델", 0.0)), 2),
           "풀": len(pooled.candidates)}
    if accepted is not None:
        found = [{"id": c.id, "순위": i, "등급": c.grade, "p": round(float(c.prob), 6),
                  "pattern": c.pattern, "규칙": list(c.rule_triggers)}
                 for i, c in enumerate(pooled.candidates, 1) if c.id in accepted]
        out["인정"] = found
        out["인정_성공"] = any(f["순위"] <= DISPLAY_TOP and at_least(f["등급"], REVIEW)
                           for f in found)
    return out


def paired(engine: Engine, index: int, accepted=None, **inputs) -> dict:
    """바꾸기 전·후를 순번에 따라 번갈아(짝수 전→후, 홀수 후→전)."""
    order = ("전", "후") if index % 2 == 0 else ("후", "전")
    out = {}
    for mode in order:
        pooled, elapsed = engine.search(mode, **inputs)
        out[mode] = summarize(pooled, elapsed, accepted)
    return out


# ---- 0. 고정 -----------------------------------------------------------------------------------

def command_freeze(args) -> int:
    paths = _paths(args.out_dir)
    if paths["rule"].exists() and not args.force:
        print(f"거절: {paths['rule']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    if control["대조군_sha256"] != CONTROL_SHA:
        print("거절: 1차 시도 대조군 해시가 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    args.out_dir.mkdir(parents=True, exist_ok=True)
    frozen = {"설정_sha256": rule_sha256(), "스크립트_sha256": first.file_sha256(Path(__file__)),
              "입력_sha256": {k: first.file_sha256(p) for k, p in _inputs().items()},
              "바꾸기_전_엔진_blob": _base_blob(), "고정": _now(), "설정": _settings()}
    paths["rule"].write_text(json.dumps(frozen, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    print(f"설정 sha256 {frozen['설정_sha256']} · 스크립트 sha256 {frozen['스크립트_sha256']} · "
          f"엔진 sha256 {frozen['입력_sha256']['엔진']}")
    return 0


def _check_frozen(paths: dict) -> dict | None:
    if not paths["rule"].exists():
        print("거절: 먼저 freeze", file=sys.stderr)
        return None
    frozen = json.loads(paths["rule"].read_text(encoding="utf-8"))
    if frozen["설정_sha256"] != rule_sha256():
        print("거절: 설정이 고정본과 다릅니다", file=sys.stderr)
        return None
    changed = [k for k, p in _inputs().items()
               if first.file_sha256(p) != frozen["입력_sha256"].get(k)]
    if changed:
        print(f"거절: 입력이 고정 때와 다릅니다 — {changed}", file=sys.stderr)
        return None
    return frozen


# ---- 1. 검색 -----------------------------------------------------------------------------------

def _prepare():
    from scripts import nameless_search_thresholds as nst

    context = nst.prepare(argparse.Namespace(
        model=rm.V141_MODEL_PATH, metadata=nst.DEFAULT_METADATA, labels=nst.DEFAULT_LABELS,
        trial_list=nst.DEFAULT_LIST, image_pairs=nst.DEFAULT_IMAGE_PAIRS,
        aliases=nst.DEFAULT_ALIASES, limit=0))
    context["nst"] = nst
    return context


def run_scenarios(engine: Engine, context: dict) -> dict:
    from scripts import named_shared_threshold as second

    out: dict[str, dict] = {"전": {}, "후": {}}
    for mode in ("전", "후"):
        suggested = None
        for key, title, inputs in second.scenario_inputs(engine.ms, context["service"]):
            if inputs.get("name") == "@S3":
                if not suggested:
                    out[mode][key] = {"제목": title, "건너뜀": "S3 제안 이름 없음"}
                    continue
                inputs["name"] = suggested
            data = engine.multi(mode, **inputs)
            if key == "S3":
                suggested = data["overall"]["query_type"].get("suggested_name")
            out[mode][key] = {
                "제목": title,
                "전체": {k: data["overall"][k] for k in ("grade", "prob", "pattern")},
                "유형": data["overall"]["query_type"]["type"],
                "상위": [{"id": c["id"], "title": c["title"], "grade": c["risk"]["grade"],
                        "prob": c["risk"]["prob"], "pattern": c["risk"]["pattern"],
                        "rules": c["risk"]["rule_triggers"]} for c in data["candidates"]]}
    return out


def scenario_fidelity(before: dict) -> dict:
    saved = json.loads(SAVED_SCENARIOS.read_text(encoding="utf-8"))["시나리오"]
    differ = []
    for key, item in saved.items():
        mine = before.get(key, {})
        if item.get("전체") != mine.get("전체") or [c["id"] for c in item.get("상위", [])] != [
                c["id"] for c in mine.get("상위", [])]:
            differ.append(key)
    return {"견준_시나리오": len(saved), "다른_것": differ, "같음": not differ}


def build_positives(context: dict, limit: int, seed: int) -> list[dict]:
    from src.axes.pair_axes import compute_pair_axes

    from backend.src.core import paths as core_paths

    nst, ms, engine = context["nst"], context["ms"], context["engine"]
    model, distinct, embeddings = ms.state.model, ms.state.distinct, ms.state.embeddings
    image_root, image_paths = Path(core_paths.IMAGES_DIR), engine.state.image_paths
    eligible = [record for record in sorted(ms.state.records, key=lambda r: r.appno)
                if record.pos is not None and not ms.is_photo_query(
                    np.asarray(embeddings[record.pos], dtype=np.float32))]
    order = list(eligible)
    random.Random(seed).shuffle(order)
    chosen = []
    for record in order:
        if len(chosen) >= limit:
            break
        path = image_root / image_paths[record.pos]
        if path.exists() and context["service"](path.read_bytes()) is not None:
            chosen.append((record, path))
    streams = {lang: first.name_stream(lang, first.N_PER_LANG * first.STREAM_FACTOR, seed=seed)
               for lang in LANGS}
    cursor = {lang: 0 for lang in LANGS}
    used: set[str] = set()
    aliases = context["aliases"]
    positives = []
    for i, (record, path) in enumerate(chosen):
        lang = LANGS[i % 2]
        goods = capped_goods(record.goods)
        picked, skipped = None, []
        while cursor[lang] < len(streams[lang]):
            name = streams[lang][cursor[lang]]
            cursor[lang] += 1
            if name in used:
                continue
            hits = []
            if record.title:
                for goods_ctx in (None, goods or None):
                    axes = compute_pair_axes(name, record.title, model=distinct, goods_a=goods_ctx,
                                             goods_b=record.goods, x3_enabled=True,
                                             spelling_version=rm.spelling_version(model))
                    features = axes.model_features(x2_img=None, mark_type="문자")
                    hits += first.standalone_hits(features, model)
            if hits:
                skipped.append({"이름": name, "축": sorted(set(hits))})
                continue
            picked = name
            break
        if picked is None:
            raise RuntimeError(f"{lang} 이름이 모자랍니다")
        used.add(picked)
        owners = nst.split_applicants(record.applicant or "", aliases)
        base = np.asarray(embeddings[record.pos], dtype=np.float32)
        accepted = {record.appno}
        for other in ms.state.records:
            if other.pos is None or other.appno == record.appno or not owners:
                continue
            if nst.split_applicants(other.applicant or "", aliases) & owners and float(
                    np.asarray(embeddings[other.pos], dtype=np.float32) @ base) >= ACCEPT_COS:
                accepted.add(other.appno)
        positives.append({"출원번호": record.appno, "상표명": record.title, "이름": picked,
                          "언어": lang, "건너뛴_이름": skipped, "유사군": sorted(goods),
                          "원래_유사군_수": len(record.goods), "인정": sorted(accepted),
                          "이미지": str(path.relative_to(ML_ROOT / "data"))})
    return positives


def command_run(args) -> int:
    paths = _paths(args.out_dir)
    frozen = _check_frozen(paths)
    if frozen is None:
        return EXIT_REFUSED
    if paths["searches"].exists() and not args.force:
        print(f"거절: {paths['searches']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    context = _prepare()
    ms = context["ms"]
    if ms.state.model.get("version") != MODEL_VERSION:
        print("거절: 엔진 모델이 v1.4.1 이 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    engine = Engine(ms)
    seed = 1 if args.smoke else SEED
    limit = 4 if args.smoke else None
    timing: dict[str, float] = {}

    def tick(name: str, began: float, count: int) -> None:
        timing[name] = round(time.perf_counter() - began, 1)
        print(f"  {name} {count}질의 {timing[name]}초", flush=True)

    began = time.perf_counter()
    scenarios = run_scenarios(engine, context)
    fidelity = scenario_fidelity(scenarios["전"])
    tick("시나리오", began, 32)
    out = {"설정_sha256": frozen["설정_sha256"],
           "스크립트_sha256(고정 때)": frozen["스크립트_sha256"],
           "스크립트_sha256(잴 때)": first.file_sha256(Path(__file__)), "모델": MODEL_VERSION,
           "스모크": bool(args.smoke), "검산_시나리오": fidelity, "시나리오": scenarios}
    if not fidelity["같음"]:
        out.update(시간_s=timing, 끝=_now())
        _write_gz(paths["searches"], out)
        print(f"멈춤: 바꾸기 전 시나리오가 저장값과 다릅니다 — {fidelity['다른_것']}",
              file=sys.stderr)
        return EXIT_STOP

    began = time.perf_counter()
    positives = build_positives(context, limit or N_POSITIVE, seed)
    tick("양성_만들기", began, len(positives))
    began = time.perf_counter()
    index = 0
    for item in positives:
        image = context["service"]((ML_ROOT / "data" / item["이미지"]).read_bytes())
        accepted = set(item["인정"])
        item["방식"] = {}
        for label, goods in (("업종 없음", None), ("같은 업종", frozenset(item["유사군"]) or None)):
            named = paired(engine, index, accepted, image=image, name=item["이름"],
                           goods_codes=sorted(goods) if goods else None)
            alone = paired(engine, index, accepted, image=image,
                           goods_codes=sorted(goods) if goods else None)
            item["방식"][label] = {"이름+이미지": named, "이미지만": alone}
            index += 1
        if index % 50 == 0:
            print(f"    양성 {index // 2}/{len(positives)}", flush=True)
    tick("양성", began, len(positives))

    a_by_key = {query.key: query for query in context["A"]}
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    if control["대조군_sha256"] != CONTROL_SHA:
        print("거절: 대조군 해시가 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    items = control["대조군"]["이름"]["확인용"][:limit]
    began = time.perf_counter()
    negatives = []
    for i, item in enumerate(items):
        image = context["service"](a_by_key[item["이미지"]].path.read_bytes())
        goods = sorted(item["유사군"]) or None
        row = {"이름": item["이름"], "이미지": item["이미지"], "유사군": item["유사군"], "방식": {}}
        for label, with_goods in COMBOS:
            codes = goods if with_goods else None
            row["방식"][label] = paired(engine, i, image=image, name=item["이름"],
                                        goods_codes=codes)
            row["방식"][label.replace("이름+", "")] = paired(engine, i, image=image,
                                                           goods_codes=codes)
        negatives.append(row)
    tick("음성", began, len(negatives))

    began = time.perf_counter()
    sample_a = []
    for i, query in enumerate(context["A"][:limit]):
        image = context["service"](query.path.read_bytes())
        goods = sorted(query.goods) or None
        sample_a.append({"질의": query.key, "이름": query.name, "유사군": goods,
                         "이름+이미지": paired(engine, i, image=image, name=query.name,
                                            goods_codes=goods),
                         "이미지만": paired(engine, i, image=image, goods_codes=goods)})
    tick("표본A", began, len(sample_a))
    out.update(양성=positives, 음성=negatives, 표본A=sample_a, 시간_s=timing,
               걸린_시간_s=round(time.perf_counter() - started, 1), 끝=_now())
    _write_gz(paths["searches"], out)
    print(f"→ {paths['searches']}")
    return 0


def _write_gz(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)


# ---- 2. 채택 조건·보고 ------------------------------------------------------------------------

def check_positive(positives: list[dict]) -> dict:
    out = {}
    for label in ("업종 없음", "같은 업종"):
        named_after = [p["방식"][label]["이름+이미지"]["후"] for p in positives]
        named_before = [p["방식"][label]["이름+이미지"]["전"] for p in positives]
        alone = [p["방식"][label]["이미지만"]["후"] for p in positives]
        rates = {"이미지만": rate([s["인정_성공"] for s in alone]),
                 "이름+이미지_전": rate([s["인정_성공"] for s in named_before]),
                 "이름+이미지_후": rate([s["인정_성공"] for s in named_after])}

        def ranks(searches):
            best = [min((f["순위"] for f in s["인정"]), default=None) for s in searches]
            present = [r for r in best if r is not None]
            return {"1위": sum(1 for r in present if r == 1),
                    "상위5": sum(1 for r in present if r <= DISPLAY_TOP),
                    "상위20": sum(1 for r in present if r <= 20),
                    "풀_밖": sum(1 for r in best if r is None),
                    "중앙값": statistics.median(present) if present else None}

        out[label] = {"질의": len(positives), "비율": rates,
                      "원래_상표_순위": {"이미지만": ranks(alone),
                                   "이름+이미지_전": ranks(named_before),
                                   "이름+이미지_후": ranks(named_after)},
                      "통과": bool(rates["이름+이미지_후"] is not None
                                 and rates["이미지만"] is not None
                                 and rates["이름+이미지_후"]
                                 >= rates["이미지만"] - MARGIN_1 - 1e-12)}
    return {"방식": out, "통과": all(block["통과"] for block in out.values())}


def check_negative(negatives: list[dict]) -> dict:
    out = {}
    for label, _ in COMBOS:
        before = [row["방식"][label]["전"]["전체"] for row in negatives]
        after = [row["방식"][label]["후"]["전체"] for row in negatives]
        block = {"질의": len(negatives), "전": distribution(before), "후": distribution(after)}
        passed = True
        for floor, margin in MARGIN_2.items():
            r0 = rate([at_least(g, floor) for g in before])
            r1 = rate([at_least(g, floor) for g in after])
            block[f"{floor}_이상"] = {"전": r0, "후": r1, "증가": None if r0 is None else r1 - r0,
                                    "한도": margin}
            passed = passed and r0 is not None and r1 - r0 <= margin + 1e-12
        changed = Counter()
        for row in negatives:
            for c in row["방식"][label]["후"]["상위"]:
                if "nameless_floor" in c["규칙"]:
                    changed["상표명_있는_후보" if c["이름"] else "상표명_없는_후보"] += 1
        block["상위5_nameless_floor_후보"] = dict(changed)
        block["통과"] = passed
        out[label] = block
    return {"방식": out, "통과": all(block["통과"] for block in out.values())}


def check_never_lower(searches: dict, model: dict) -> dict:
    pairs = []
    for p in searches["양성"]:
        for label in ("업종 없음", "같은 업종"):
            block = p["방식"][label]
            pairs.append(("양성:" + label, p["출원번호"], block["이름+이미지"]["후"]["전체"],
                          block["이미지만"]["후"]["전체"]))
    for row in searches["음성"]:
        for label, _ in COMBOS:
            pairs.append(("음성:" + label, row["이름"], row["방식"][label]["후"]["전체"],
                          row["방식"][label.replace("이름+", "")]["후"]["전체"]))
    for row in searches["표본A"]:
        pairs.append(("표본A", row["질의"], row["이름+이미지"]["후"]["전체"],
                      row["이미지만"]["후"]["전체"]))
    lower = [{"표본": s, "질의": q, "이름+이미지": a, "이미지만": b} for s, q, a, b in pairs
             if grade_index(a) < grade_index(b)]
    lower_before = sum(1 for p in searches["양성"] for label in ("업종 없음", "같은 업종")
                       if grade_index(p["방식"][label]["이름+이미지"]["전"]["전체"])
                       < grade_index(p["방식"][label]["이미지만"]["전"]["전체"]))
    lower_before += sum(1 for row in searches["음성"] for label, _ in COMBOS
                        if grade_index(row["방식"][label]["전"]["전체"])
                        < grade_index(row["방식"][label.replace("이름+", "")]["전"]["전체"]))
    lower_before += sum(1 for row in searches["표본A"]
                        if grade_index(row["이름+이미지"]["전"]["전체"])
                        < grade_index(row["이미지만"]["전"]["전체"]))
    blocks = {"base": model}
    blocks.update({k: v for k, v in (model.get("patterns") or {}).items()})
    blocks.update({k: v for k, v in (model.get("nameless_patterns") or {}).items()})
    monotone = {key: len(rm.monotone_violations(block["coefficients"]))
                for key, block in blocks.items() if "coefficients" in block}
    coupling = rm.coupling_violations(model)
    same_alone = 0
    for p in searches["양성"]:
        for label in ("업종 없음", "같은 업종"):
            block = p["방식"][label]["이미지만"]
            same_alone += int(_strip(block["전"]) == _strip(block["후"]))
    alone_total = 2 * len(searches["양성"])
    return {"쌍": len(pairs), "낮아진_경우(후)": len(lower), "낮아진_예": lower[:20],
            "참고_낮아진_경우(전)": lower_before, "단조_위반": monotone,
            "결합_위반": len(coupling),
            "이미지만_질의_전후_같음": f"{same_alone}/{alone_total}",
            "통과": not lower and not any(monotone.values()) and not coupling}


def _strip(summary: dict) -> tuple:
    return summary["전체"], [(c["id"], c["등급"], c["p"], c["pattern"], tuple(c["규칙"]))
                           for c in summary["상위"]]


def photo_flags() -> dict[tuple[str, str, str], bool]:
    import csv

    out = {}
    for path in (TRIALS / "pairs_features.csv", TRIALS / "pairs_features_easy.csv"):
        with open(path, encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row.get("pair_source") or "trial", row["심판번호"], row["상대번호"])
                out[key] = str(row.get("사진A") or "").strip() in ("1", "1.0", "True")
    return out


def precision_with_floor(model: dict) -> dict:
    """채택_4 — 1차 시도 채택_2 의 OOF 위험 정밀도에 이름을 뺀 판단과의 비교를 더한다."""
    from scripts import train_risk_model as tr

    captured: dict = {}
    original = tr.subset_performance

    def spy(prob, y, rows, trial, **kwargs):
        captured.update(prob=np.asarray(prob).copy(), y=np.asarray(y).copy(), rows=rows)
        return original(prob, y, rows, trial, **kwargs)

    tr.subset_performance = spy
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            tr.run(first.V13_INPUTS / "pairs_features.csv",
                   first.V13_INPUTS / "pairs_features_easy.csv",
                   out_dir=out, model_path=out / "model.json")
            reproduced = json.loads((out / "model.json").read_text(encoding="utf-8"))
    finally:
        tr.subset_performance = original
    v13 = json.loads(Path(rm.V13_MODEL_PATH).read_text(encoding="utf-8"))
    same = (reproduced["grade_thresholds"] == v13["grade_thresholds"]
            and reproduced["meta"].get("grade_precision") == v13["meta"].get("grade_precision"))
    rows, prob, y = captured["rows"], captured["prob"], captured["y"]
    mask = tr.set_masks(rows)["심결+cross+db"]
    cut = float(model["grade_thresholds"][RISK])
    named = mask & (prob >= cut)
    photos = photo_flags()
    floor = np.zeros(len(rows), dtype=bool)
    counts = Counter()
    for i, row in enumerate(rows):
        if not mask[i]:
            continue
        x2 = _number(row.get("x2_whole"))
        if x2 is None:
            continue
        key = (row.get("pair_source") or "trial", str(row.get("심판번호")),
               str(row.get("상대번호") if row.get("상대번호") is not None else ""))
        if key not in photos:
            counts["사진_열_못_맞춤"] += 1
        if photos.get(key, False):
            counts["질의_사진(견주지_않음)"] += 1
            continue
        counts["견준_행"] += 1
        if nameless_offline(x2, _number(row.get("x4")), model) == RISK:
            floor[i] = True
            counts["이름_없는_판단_위험"] += 1
    final = named | floor

    def block(selected):
        n = int(selected.sum())
        return {"위험": n, "유사": int(y[selected].sum()),
                "정밀도": round(float(y[selected].mean()), 4) if n else None}

    added = final & ~named
    result = {"재현_같음": bool(same), "재현_하한": reproduced["grade_thresholds"],
              "재현_정밀도": reproduced["meta"].get("grade_precision"), "행": int(mask.sum()),
              "지금": block(named), "비교_더함": block(final), "새로_위험": block(added),
              "새로_위험_행": [{"pair_source": rows[i].get("pair_source"),
                             "심판번호": rows[i].get("심판번호"),
                             "상대번호": rows[i].get("상대번호"),
                             "x2_whole": _number(rows[i].get("x2_whole")),
                             "x4": _number(rows[i].get("x4")), "유사": int(y[i]),
                             "OOF_p": round(float(prob[i]), 4)}
                            for i in np.flatnonzero(added)],
              "세기": dict(counts)}
    precision = result["비교_더함"]["정밀도"]
    result["통과"] = bool(same and precision is not None and precision >= PRECISION_MIN - 1e-12)
    return result


def cited_pairs_with_floor(case_ids: set[str], model: dict) -> dict:
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    before, after = Counter(), Counter()
    by_label: dict[str, Counter] = {}
    risk = {"전": Counter(), "후": Counter()}
    pairs = 0
    for row in t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY).rows:
        if row.get("pair_source") != "trial" or str(row.get("심판번호")) not in case_ids:
            continue
        if not tr.has_name(row):
            continue
        features = t4.service_features(row, image_column=t4.RAW_IMAGE)
        features["mark_type"] = "결합-문자요부" if features["x2_whole"] is not None else "문자"
        grade_before = first.features_grade(features, model, None)
        grade_after = grade_before
        if features["x2_whole"] is not None:
            other = nameless_offline(features["x2_whole"], features.get("x4"), model)
            if grade_index(other) > grade_index(grade_after):
                grade_after = other
        label = row.get("최종라벨")
        pairs += 1
        before[grade_before] += 1
        after[grade_after] += 1
        by_label.setdefault(label, Counter())[(grade_before, grade_after)] += 1
        for tag, grade in (("전", grade_before), ("후", grade_after)):
            if grade == RISK:
                risk[tag][label] += 1

    def precision(counter):
        n = sum(counter.values())
        return {"위험": n, "유사": counter.get("유사", 0),
                "정밀도": round(counter.get("유사", 0) / n, 4) if n else None}

    def review_rate(counter):
        n = sum(counter.values())
        if not n:
            return None
        return round(sum(v for g, v in counter.items() if at_least(g, REVIEW)) / n, 4)

    return {"사건": len(case_ids), "쌍": pairs, "등급(전)": distribution(before.elements()),
            "등급(후)": distribution(after.elements()),
            "검토_권장_이상(전)": review_rate(before), "검토_권장_이상(후)": review_rate(after),
            "위험_정밀도(전)": precision(risk["전"]), "위험_정밀도(후)": precision(risk["후"]),
            "바뀐_쌍": {label: {f"{a}→{b}": n for (a, b), n in counter.items() if a != b}
                      for label, counter in by_label.items()}}


def scenario_table(scenarios: dict) -> list[dict]:
    rows = []
    for key, before in scenarios["전"].items():
        after = scenarios["후"].get(key, {})
        if "전체" not in before or "전체" not in after:
            rows.append({"키": key, "제목": before.get("제목"), "건너뜀": True})
            continue
        rows.append({"키": key, "제목": before["제목"], "유형": before["유형"],
                     "전": before["전체"], "후": after["전체"],
                     "전_1위": before["상위"][0]["title"] if before["상위"] else None,
                     "후_1위": after["상위"][0]["title"] if after["상위"] else None,
                     "후_nameless_floor": sum(1 for c in after["상위"]
                                              if "nameless_floor" in c["rules"]),
                     "바뀜": before["전체"] != after["전체"]
                     or [c["id"] for c in before["상위"]] != [c["id"] for c in after["상위"]]})
    return rows


def timing_table(searches: dict) -> dict:
    groups = {"양성 이름+이미지": [], "음성 이름+이미지": [], "표본A 이름+이미지": []}
    for p in searches["양성"]:
        for label in ("업종 없음", "같은 업종"):
            groups["양성 이름+이미지"].append(p["방식"][label]["이름+이미지"])
    for row in searches["음성"]:
        for label, _ in COMBOS:
            groups["음성 이름+이미지"].append(row["방식"][label])
    for row in searches["표본A"]:
        groups["표본A 이름+이미지"].append(row["이름+이미지"])
    out = {}
    for name, items in groups.items():
        if not items:
            continue
        block = {}
        for field_name in ("ms", "모델_ms"):
            before = [item["전"][field_name] for item in items]
            after = [item["후"][field_name] for item in items]
            diff = [b - a for a, b in zip(before, after)]
            block[field_name] = {"전_중앙": round(statistics.median(before), 2),
                                 "후_중앙": round(statistics.median(after), 2),
                                 "전_95%": round(float(np.percentile(before, 95)), 2),
                                 "후_95%": round(float(np.percentile(after, 95)), 2),
                                 "차이_평균": round(statistics.fmean(diff), 2),
                                 "차이_중앙": round(statistics.median(diff), 2)}
        out[name] = {"질의": len(items), **block}
    return out


def command_report(args) -> int:
    paths = _paths(args.out_dir)
    frozen = _check_frozen(paths)
    if frozen is None:
        return EXIT_REFUSED
    if not paths["searches"].exists():
        print("거절: 먼저 run", file=sys.stderr)
        return EXIT_REFUSED
    with gzip.open(paths["searches"], "rt", encoding="utf-8") as handle:
        searches = json.load(handle)
    if searches["설정_sha256"] != frozen["설정_sha256"]:
        print("거절: 검색 원자료가 다른 설정으로 만들어졌습니다", file=sys.stderr)
        return EXIT_REFUSED
    model = rm.load_model(rm.V141_MODEL_PATH)
    results = {"설정_sha256": frozen["설정_sha256"],
               "스크립트_sha256(고정 때)": frozen["스크립트_sha256"],
               "스크립트_sha256(잴 때)": searches["스크립트_sha256(잴 때)"],
               "스크립트_sha256(보고 때)": first.file_sha256(Path(__file__)),
               "엔진_sha256": frozen["입력_sha256"]["엔진"],
               "바꾸기_전_엔진_blob": frozen.get("바꾸기_전_엔진_blob"),
               "모델": searches["모델"], "스모크": searches["스모크"],
               "검산_시나리오": searches["검산_시나리오"]}
    if not searches["검산_시나리오"]["같음"]:
        results.update(채택=False, 멈춤="바꾸기 전 시나리오가 저장값과 다름", 끝=_now())
        return _finish(paths, results)
    case_ids = {row["질의"].split(":")[1] for row in searches["표본A"]}
    results["채택_1"] = check_positive(searches["양성"])
    results["채택_2"] = check_negative(searches["음성"])
    results["채택_3"] = check_never_lower(searches, model)
    results["채택_4"] = precision_with_floor(model)
    results["표본A_인용상표"] = cited_pairs_with_floor(case_ids, model)
    results["표본A_전체등급"] = {
        "전": distribution(row["이름+이미지"]["전"]["전체"] for row in searches["표본A"]),
        "후": distribution(row["이름+이미지"]["후"]["전체"] for row in searches["표본A"]),
        "이미지만": distribution(row["이미지만"]["후"]["전체"] for row in searches["표본A"])}
    results["시나리오"] = scenario_table(searches["시나리오"])
    results["시간"] = timing_table(searches)
    results["질의"] = {"양성": len(searches["양성"]), "음성": len(searches["음성"]),
                     "표본A": len(searches["표본A"])}
    results["양성_표본"] = {
        "언어": dict(Counter(p["언어"] for p in searches["양성"])),
        "상표명_없는_원래_상표": sum(1 for p in searches["양성"] if not p["상표명"]),
        "인정_상표_2개_이상": sum(1 for p in searches["양성"] if len(p["인정"]) > 1),
        "유사군_60_초과": sum(1 for p in searches["양성"] if p["원래_유사군_수"] > GOODS_CAP),
        "건너뛴_이름": sum(len(p["건너뛴_이름"]) for p in searches["양성"])}
    results["채택"] = all(results[k]["통과"] for k in ("채택_1", "채택_2", "채택_3", "채택_4"))
    results["끝"] = _now()
    return _finish(paths, results)


def _finish(paths: dict, results: dict) -> int:
    paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    paths["report"].write_text(report_text(results), encoding="utf-8")
    print(json.dumps({k: results.get(k) for k in ("채택", "멈춤")}, ensure_ascii=False))
    print(f"→ {paths['results']}\n→ {paths['report']}")
    return 0 if results.get("채택") else EXIT_STOP


def _pct(value) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _dist(table: dict) -> str:
    return " · ".join(f"{k} {v}" for k, v in table.items()) or "—"


def report_text(results: dict) -> str:
    lines = ["# R-P0-1 nameless_floor 넓히기 — 확인 표본 보고", "",
             f"- 설정 sha256 `{results['설정_sha256']}` · 엔진 sha256 `{results['엔진_sha256']}`",
             f"- 스크립트 sha256 고정 `{results['스크립트_sha256(고정 때)']}` · 잴 때 "
             f"`{results['스크립트_sha256(잴 때)']}` · 보고 때 "
             f"`{results['스크립트_sha256(보고 때)']}`",
             f"- 모델 {results['모델']} · 스모크 {results['스모크']} · 채택 "
             f"**{results.get('채택')}**",
             f"- 검산(바꾸기 전 = 저장값): {results['검산_시나리오']}"]
    if "채택_1" not in results:
        return "\n".join(lines + ["", f"멈춤: {results.get('멈춤')}", ""])
    one, two, three, four = (results[k] for k in ("채택_1", "채택_2", "채택_3", "채택_4"))
    lines += ["", f"## ① 양성 — {one['통과']}", "",
              "| 업종 | 이미지만 | 이름+이미지 전 | 이름+이미지 후 | 통과 |",
              "|---|---:|---:|---:|---|"]
    for label, block in one["방식"].items():
        r = block["비율"]
        lines.append(f"| {label} | {_pct(r['이미지만'])} | {_pct(r['이름+이미지_전'])} | "
                     f"{_pct(r['이름+이미지_후'])} | {block['통과']} |")
    lines += ["", "원래 상표(인정 상표 중 가장 앞) 순위:", ""]
    for label, block in one["방식"].items():
        for kind, ranks in block["원래_상표_순위"].items():
            lines.append(f"- {label} · {kind}: {ranks}")
    lines += ["", f"## ② 음성 — {two['통과']}", ""]
    for label, block in two["방식"].items():
        lines.append(f"- {label}: 전 {_dist(block['전'])} → 후 {_dist(block['후'])} · "
                     f"검토 권장 이상 {_pct(block[REVIEW + '_이상']['전'])} → "
                     f"{_pct(block[REVIEW + '_이상']['후'])} · 위험 이상 "
                     f"{_pct(block[RISK + '_이상']['전'])} → {_pct(block[RISK + '_이상']['후'])} · "
                     f"상위5 nameless_floor {block['상위5_nameless_floor_후보']} · {block['통과']}")
    lines += ["", f"## ③ 이름을 더해도 내려가지 않음 — {three['통과']}", "",
              f"- 쌍 {three['쌍']} · 낮아진 경우(후) {three['낮아진_경우(후)']} · 참고(전) "
              f"{three['참고_낮아진_경우(전)']} · 단조 위반 {three['단조_위반']} · 결합 위반 "
              f"{three['결합_위반']} · 이미지만 질의 전후 같음 {three['이미지만_질의_전후_같음']}"]
    lines += ["", f"## ④ 위험 정밀도 — {four['통과']}", "",
              f"- 재현 같음 {four['재현_같음']} · 행 {four['행']} · 지금 {four['지금']} → "
              f"비교 더함 {four['비교_더함']} · 새로 위험 {four['새로_위험']} · {four['세기']}"]
    cited = results["표본A_인용상표"]
    lines += ["", "## 표본 A 인용상표(보고)", "",
              f"- 쌍 {cited['쌍']}(사건 {cited['사건']}) · 등급 전 {_dist(cited['등급(전)'])} → 후 "
              f"{_dist(cited['등급(후)'])} · 검토 권장 이상 {_pct(cited['검토_권장_이상(전)'])} → "
              f"{_pct(cited['검토_권장_이상(후)'])} · 위험 정밀도 {cited['위험_정밀도(전)']} → "
              f"{cited['위험_정밀도(후)']}",
              f"- 표본 A 전체 등급(검색): 전 {_dist(results['표본A_전체등급']['전'])} → 후 "
              f"{_dist(results['표본A_전체등급']['후'])} · 이미지만 "
              f"{_dist(results['표본A_전체등급']['이미지만'])}"]
    lines += ["", "## 시나리오 16종", "", "| 키 | 제목 | 전 | 후 | 1위(전 → 후) |",
              "|---|---|---|---|---|"]
    for row in results["시나리오"]:
        if row.get("건너뜀"):
            lines.append(f"| {row['키']} | {row['제목']} | — | — | — |")
            continue
        lines.append(f"| {row['키']} | {row['제목']} | {row['전']['grade']} {row['전']['prob']} | "
                     f"{row['후']['grade']} {row['후']['prob']} | {row['전_1위']} → "
                     f"{row['후_1위']} |")
    lines += ["", "## 질의당 시간(ms)", ""]
    for name, block in results["시간"].items():
        lines.append(f"- {name}({block['질의']}): 전체 {block['ms']} · 모델 단계 "
                     f"{block['모델_ms']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("freeze", "run", "report"))
    parser.add_argument("--out-dir", type=Path, default=TRIALS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--smoke", action="store_true",
                        help="시험 실행 — seed 1·양성 4·음성 4·표본 A 4(--out-dir 를 따로)")
    args = parser.parse_args(argv)
    if args.smoke and args.out_dir.resolve() == TRIALS.resolve():
        print("거절: --smoke 는 --out-dir 를 따로 주세요", file=sys.stderr)
        return EXIT_REFUSED
    return {"freeze": command_freeze, "run": command_run, "report": command_report}[
        args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
