"""견고성 점검 R-P0-1 3차 — 이름 있는 이미지 질의를 "이미지만" 판단과만 견주는 좁은 방식(지시로
고정, 2026-11-23). 1차(설계 §7-7)는 업종이 들어간 이름 없는 판단까지 견줘 대조군을 올렸고,
2차(§7-8)는 이름 없는 기준 다시 맞추기가 인용상표를 잃었다. 이번엔 이름도 업종도 뺀 이미지만
판단(지금 계수·기준 그대로)과만 견준다 — 대조군의 무관한 로고는 이미지만 판단으로 최고 0.41(검토
권장 0.491 아래).

    ml/venv/bin/python ml/scripts/logo_floor_image_only.py freeze   # 0. 규칙·입력·엔진 소스 해시
    ml/venv/bin/python ml/scripts/logo_floor_image_only.py run      # 1. 실제 엔진 — 전·후 검색
    ml/venv/bin/python ml/scripts/logo_floor_image_only.py report   # 2. 채택 ①–④·전후 표
    ml/venv/bin/python ml/scripts/logo_floor_image_only.py apply    # 3. 채택일 때만 v1.4.2 JSON
    ml/venv/bin/python ml/scripts/logo_floor_image_only.py verify   # 4. 기본 모델 바꾼 뒤 확인

엔진의 새 비교는 계수 JSON 의 logo_floor 표시가 켠다(risk_model.logo_floor_enabled) — 바꾸기 전 =
v1.4.1 JSON(표시 없음, 예전 동작 그대로), 후 = 후보 v1.4.2(v1.4.1 + 버전 + 표시, 계수·기준 그대로).
같은 프로세스에서 엔진의 계수(multi_search.state.model)만 바꿔 견준다. 산출(비공개):
ml/data/trials/logo_floor_image_only_{rule,results,candidate,verify}.json·_searches.json.gz·
_report.md. 고정본과 다르면 거절(종료 코드 4), 검산 불일치·채택 미달이면 종료 코드 3. KIPRIS 0.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import statistics
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

from scripts import logo_floor_named as lf  # noqa: E402
from scripts import named_search_thresholds as first  # noqa: E402
from scripts import nameless_shared_threshold as ns  # noqa: E402

TRIALS = ML_ROOT / "data" / "trials"
STEM = "logo_floor_image_only"
EXIT_STOP = 3
EXIT_REFUSED = 4
REVIEW, RISK = "검토 권장", "위험"
BASE_VERSION = "risk_model_v1.4.1"
NEW_VERSION = "risk_model_v1.4.2"
NEW_MODEL_PATH = REPO_ROOT / "shared" / "model" / "risk_model_v1.4.2.json"
POSITIVES = TRIALS / "logo_floor_named_searches.json.gz"  # 1차 시도 양성 200
SAVED_SCENARIOS = TRIALS / "named_shared_threshold_scenarios_default.json"  # v1.4.1 확인 실행
POSITIVE_MIN = 0.95
MARGIN_2 = {REVIEW: 0.02, RISK: 0.01}
PRECISION_MIN = 0.70
NEW_RISK_MIN_ROWS = 5
FIGURE_LEVEL = "도형"  # 자동 유형의 이름 없는 질의는 도형계(결합-도형요부와 같은 위험도)
DISPLAY_TOP = first.DISPLAY_TOP
COMBOS = (("이름+이미지", False), ("이름+이미지+업종", True))
LOGO_FLOOR = {
    "enabled": True, "since": "2026-11-23",
    "scope": ("이미지가 있는 이름 있는 질의(질의 이미지가 사진이면 제외, 유형을 도형계로 고친 "
              "질의는 예전 nameless_floor 그대로)에서 후보마다 이름도 업종도 뺀 이미지만 "
              "판단(noname:x2_whole — 계수·기준 그대로, 유형은 이름 없이 넣었을 때의 유형)과 "
              "견줘 높은 등급·정렬 위치(rule_triggers nameless_floor)"),
    "basis": ("견고성 점검 R-P0-1 — 등록 로고를 그대로 쓰고 이름만 다르게 넣으면 그 등록상표가 "
              "목록에서 사라짐(통합 모델 설계 §7-9)"),
}

# 규칙(이 지시로 고정 — 실행 전에 해시를 남기고 결과를 보고 바꾸지 않는다) ------------------------
RULE = {
    "변경": (
        "backend/src/core/multi_search.py: 이미지가 있는 이름 있는 질의(질의 이미지가 사진이면 "
        "제외 — 사진 규칙 그대로; 사용자가 유형을 도형계로 고친 질의는 지금의 nameless_floor 를 "
        "그대로 둔다)에서 후보마다(상표명 없는 후보 포함) 이름도 업종도 뺀 이미지만 판단 = "
        "rm.risk_score(x2_whole = 그 후보 이미지 유사도, 이름 축·x4 결측, 유형 = 이름 없이 "
        "넣었을 때의 유형 nameless_level — 자동은 도형계)을 계산해 등급이 높으면 "
        "그쪽(rule_triggers 에 nameless_floor, prob·기여도·pattern 은 그쪽 것), 같으면 원래 "
        "판단, 정렬 위치는 둘 중 높은 쪽. 업종이 들어간 이름 없는 판단은 이 비교에 쓰지 않는다. "
        "계수 JSON 의 logo_floor.enabled 가 켤 때만(v1.4.2 = v1.4.1 + 버전 + 표시, 계수·기준 "
        "그대로)."),
    "바꾸기_전·후": (
        "같은 프로세스에서 엔진 계수(multi_search.state.model)를 바꾼다 — 전 = v1.4.1 JSON(표시 "
        "없음, 예전 동작), 후 = 후보 v1.4.2. 검산: 바꾸기 전 시나리오 16종(전체 "
        "grade·prob·pattern, 상위 5 출원번호)이 v1.4.1 확인 실행 "
        "저장값(named_shared_threshold_scenarios_default.json)과 모두 같아야 한다 — 다르면 멈춤."),
    "검색": (
        "실제 엔진 search_pool(CLIP·OCR·X3), 전체 등급 = 정렬 앞 5건의 최고 표시 등급. OCR "
        "판정은 이미지마다 첫 값을 다시 쓴다. 질의마다 시간에 넣지 않는 데우기 검색(후) 한 번 뒤 "
        "전·후를 순번 짝수면 전→후, 홀수면 후→전으로."),
    "양성": (
        "1차 시도(logo_floor_named) 양성 200 그대로(검색 원자료의 '양성' — 같은 로고 "
        "이미지·지어낸 이름·유사군·인정 상표), 업종 없음·같은 업종(그 유사군) 두 방식."),
    "음성": (
        "1차 시도(named_search_thresholds) 대조군 확인용 100 그대로(이름·표본 A 저유사 "
        "이미지·업종 세트, 대조군 sha256 f6b11d62…) — 이름+이미지·이름+이미지+업종."),
    "표본A": (
        "nameless_search_thresholds.prepare 의 표본 A 질의 전부 — 이름+이미지(+질의 업종) 전·후."),
    "이미지만_질의": (
        "채택 ③ 비교용 — 양성·음성·표본 A 의 이미지마다 이름·업종 없이 이미지만 넣은 질의 "
        "하나(후; 전과 같은지도 본다)."),
    "시나리오": "named_shared_threshold.SCENARIOS 16종 — multi_search(top_k 5) 전·후.",
    "채택_1": (
        "양성, 업종 방식마다: 인정 상표가 상위 5 안에 표시 등급 검토 권장 이상으로 나온 질의 "
        "비율(후) ≥ 95%."),
    "채택_2": (
        "음성, 방식(이름+이미지·이름+이미지+업종)마다: 전체 등급 검토 권장 이상 비율 증가(후 − "
        "전) ≤ 2%p, 위험 이상 증가 ≤ 1%p."),
    "채택_3": (
        "(가) 후의 이름을 더한 질의(양성 두 방식·음성 두 방식·표본 A)의 전체 등급 < 같은 "
        "이미지만(이름·업종 없이) 넣은 질의의 전체 등급인 경우 0 — 질의 이미지가 사진으로 판정된 "
        "질의는 사진 규칙에 따른 의도된 차이라 빼고 건수만 보고 (나) 기존 단조성 검사 — 계수 "
        "집합마다 rm.monotone_violations 0·rm.coupling_violations 0."),
    "채택_4": (
        "1차 시도 채택_2 의 OOF 위험(v1.3 학습을 학습 입력 사본으로 다시 돌림, 심결+cross+db 행, "
        "위험 하한 0.5902 — 재현 하한·정밀도가 v1.3 JSON 과 다르면 멈춤)에 이 비교를 더함: "
        "이미지 축이 있고 질의 쪽이 사진이 아닌 행(사진A — 지금 특징 파일을 "
        "(pair_source·심판번호·상대번호)로 맞춤, 없으면 사진 아님)은 이미지만 판단(배포 이름 "
        "없는 이미지만 계수·기준, 유형 도형, 이미지 축 그 행 값)이 위험이면 위험. 이 비교 때문에 "
        "새로 위험이 된 행이 5 이상이면 그 행의 유사 비율 ≥ 0.70, 5 미만이면 판정에 쓰지 않고 "
        "보고만. 전체 위험 정밀도도 보고(출처별 수 포함)."),
    "보고": (
        "전후 표 — 양성(상위 5 검토 권장 이상 비율·원래 상표 순위), 음성(등급 분포), 표본 A "
        "인용상표 등급 분포(1차 시도 채택_4 의 쌍·서비스 채점식에 이미지만 판단을 더함), "
        "시나리오 16종, 질의당 시간(이름+이미지 질의의 search_pool 전체·모델 단계)."),
    "적용": (
        "채택될 때만 shared/model/risk_model_v1.4.2.json = 후보(v1.4.1 + version "
        "risk_model_v1.4.2 + logo_floor), 서비스 기본 모델 v1.4.2. verify 가 기본 엔진으로 "
        "양성·음성·표본 A·시나리오를 다시 돌려 후 실행과 같은지 본다."),
}


def _settings() -> dict:
    return {"RULE": RULE, "BASE_VERSION": BASE_VERSION, "NEW_VERSION": NEW_VERSION,
            "LOGO_FLOOR": LOGO_FLOOR, "POSITIVE_MIN": POSITIVE_MIN, "MARGIN_2": MARGIN_2,
            "PRECISION_MIN": PRECISION_MIN, "NEW_RISK_MIN_ROWS": NEW_RISK_MIN_ROWS,
            "FIGURE_LEVEL": FIGURE_LEVEL, "DISPLAY_TOP": DISPLAY_TOP, "COMBOS": COMBOS,
            "CONTROL_SHA": ns.CONTROL_SHA}


def rule_sha256() -> str:
    return first.canonical_sha256(_settings())


def _inputs() -> dict[str, Path]:
    from scripts import nameless_search_thresholds as nst

    return {"계수_JSON(v1.4.1)": rm.V141_MODEL_PATH, "v1.3_JSON": rm.V13_MODEL_PATH,
            "대조군": first._paths(TRIALS)["control"], "양성(1차 시도)": POSITIVES,
            "메타데이터": nst.DEFAULT_METADATA,
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
            "엔진": REPO_ROOT / "backend" / "src" / "core" / "multi_search.py",
            "런타임": REPO_ROOT / "ml" / "src" / "model" / "risk_model.py"}


def _paths(out_dir: Path) -> dict[str, Path]:
    return {"rule": out_dir / f"{STEM}_rule.json", "results": out_dir / f"{STEM}_results.json",
            "report": out_dir / f"{STEM}_report.md",
            "candidate": out_dir / f"{STEM}_candidate.json",
            "searches": out_dir / f"{STEM}_searches.json.gz",
            "verify": out_dir / f"{STEM}_verify.json"}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---- 순수 함수(시험 대상) ----------------------------------------------------------------------

def candidate_model(base: dict) -> dict:
    """v1.4.1 JSON → v1.4.2: 버전과 logo_floor 표시만 — 계수·하한·규칙은 그대로."""
    out = copy.deepcopy(base)
    out["version"] = NEW_VERSION
    out[rm.LOGO_FLOOR_KEY] = dict(LOGO_FLOOR)
    out.setdefault("meta", {})["logo_floor"] = {
        "derived_from": base.get("version"), "rule_sha256": rule_sha256(),
        "script": "ml/scripts/logo_floor_image_only.py"}
    rm.validate_model({**out, "version": base["version"]})  # 구조 검증(새 버전 등록은 적용 때)
    return out


def image_only_grade(x2: float, model: dict, level: str = FIGURE_LEVEL) -> str:
    """이름도 업종도 뺀 이미지만 판단의 등급(엔진 _image_only_features → risk_score, 도형 규칙
    포함)."""
    features = {"x1_d": None, "x2_text_d": None, "x2_whole": float(x2), "x3_d": None, "x4": None,
                "has_meaning_both": False, "has_distinctive_part_a": True,
                "has_distinctive_part_b": True, "mark_type": level}
    return rm.risk_score(features, model).grade


def higher(a: str, b: str) -> str:
    return a if rm.GRADES.index(a) >= rm.GRADES.index(b) else b


def summarize(pooled, elapsed_ms: float, accepted: set[str] | None = None) -> dict:
    top = pooled.candidates[:DISPLAY_TOP]
    out = {"사진": bool(pooled.query_photo), "유형": pooled.query_type.type,
           "전체": lf.overall_grade([c.grade for c in pooled.candidates]),
           "상위": [{"id": c.id, "등급": c.grade, "p": round(float(c.prob), 6),
                    "pattern": c.pattern, "규칙": list(c.rule_triggers), "이름": bool(c.title),
                    "x2_img": c.axes["x2_img"]} for c in top],
           "ms": round(elapsed_ms, 1), "모델_ms": round(float(pooled.timings.get("모델", 0.0)), 2)}
    if accepted is not None:
        found = [{"id": c.id, "순위": i, "등급": c.grade, "pattern": c.pattern,
                  "규칙": list(c.rule_triggers)}
                 for i, c in enumerate(pooled.candidates, 1) if c.id in accepted]
        out["인정"] = found
        out["인정_성공"] = any(f["순위"] <= DISPLAY_TOP and lf.at_least(f["등급"], REVIEW)
                           for f in found)
    return out


def check_positive(positives: list[dict]) -> dict:
    out = {}
    for mode in ("업종 없음", "같은 업종"):
        before = [p["방식"][mode]["전"] for p in positives]
        after = [p["방식"][mode]["후"] for p in positives]

        def ranks(searches):
            best = [min((f["순위"] for f in s["인정"]), default=None) for s in searches]
            present = [r for r in best if r is not None]
            return {"1위": sum(1 for r in present if r == 1),
                    "상위5": sum(1 for r in present if r <= DISPLAY_TOP),
                    "상위20": sum(1 for r in present if r <= 20),
                    "풀_밖": sum(1 for r in best if r is None),
                    "중앙값": statistics.median(present) if present else None}

        rate_after = lf.rate([s["인정_성공"] for s in after])
        out[mode] = {"질의": len(positives), "전": lf.rate([s["인정_성공"] for s in before]),
                     "후": rate_after, "순위_전": ranks(before), "순위_후": ranks(after),
                     "통과": rate_after is not None and rate_after >= POSITIVE_MIN - 1e-12}
    return {"방식": out, "통과": all(block["통과"] for block in out.values())}


def check_negative(negatives: list[dict]) -> dict:
    out = {}
    for label, _ in COMBOS:
        before = [row["방식"][label]["전"]["전체"] for row in negatives]
        after = [row["방식"][label]["후"]["전체"] for row in negatives]
        block = {"질의": len(negatives), "전": lf.distribution(before),
                 "후": lf.distribution(after)}
        passed = True
        for floor, margin in MARGIN_2.items():
            r0 = lf.rate([lf.at_least(g, floor) for g in before])
            r1 = lf.rate([lf.at_least(g, floor) for g in after])
            block[f"{floor}_이상"] = {"전": r0, "후": r1, "증가": None if r0 is None else r1 - r0,
                                    "한도": margin}
            passed = passed and r0 is not None and r1 - r0 <= margin + 1e-12
        block["통과"] = passed
        out[label] = block
    return {"방식": out, "통과": all(block["통과"] for block in out.values())}


def check_never_lower(searches: dict, model: dict) -> dict:
    """채택_3 — 후의 이름 있는 질의 전체 등급 < 이미지만 질의 전체 등급(사진 질의는 빼고 센다)."""
    pairs = []
    for p in searches["양성"]:
        for mode in ("업종 없음", "같은 업종"):
            pairs.append(("양성:" + mode, p["출원번호"], p["방식"][mode]["후"], p["이미지만"]))
    for row in searches["음성"]:
        for label, _ in COMBOS:
            pairs.append(("음성:" + label, row["이름"], row["방식"][label]["후"], row["이미지만"]))
    for row in searches["표본A"]:
        pairs.append(("표본A", row["질의"], row["이름+이미지"]["후"], row["이미지만"]))
    photo = [item for item in pairs if item[2]["사진"] or item[3]["사진"]]
    kept = [item for item in pairs if not (item[2]["사진"] or item[3]["사진"])]
    lower = [{"표본": s, "질의": q, "이름": a["전체"], "이미지만": b["전체"]} for s, q, a, b in kept
             if lf.grade_index(a["전체"]) < lf.grade_index(b["전체"])]
    lower_photo = sum(1 for _, _, a, b in photo
                      if lf.grade_index(a["전체"]) < lf.grade_index(b["전체"]))
    blocks = {"base": model, **(model.get("patterns") or {}),
              **{rm.NAMELESS_PREFIX + k: v for k, v in (model.get(rm.NAMELESS_KEY) or {}).items()}}
    monotone = {key: len(rm.monotone_violations(block["coefficients"]))
                for key, block in blocks.items() if "coefficients" in block}
    coupling = rm.coupling_violations(model)
    return {"쌍": len(kept), "낮아진_경우": len(lower), "낮아진_예": lower[:20],
            "사진_질의(뺌)": len(photo), "사진_질의_중_낮아짐(보고만)": lower_photo,
            "단조_위반": monotone, "결합_위반": len(coupling),
            "통과": not lower and not any(monotone.values()) and not coupling}


def precision(model: dict) -> dict:
    """채택_4 — 1차 시도 채택_2 OOF 위험에 이미지만 판단 비교를 더한 위험 정밀도."""
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
    named = mask & (prob >= float(model["grade_thresholds"][RISK]))
    photos = lf.photo_flags()
    floor = np.zeros(len(rows), dtype=bool)
    counts = Counter()
    for i, row in enumerate(rows):
        if not mask[i]:
            continue
        x2 = lf._number(row.get("x2_whole"))
        if x2 is None:
            continue
        key = (row.get("pair_source") or "trial", str(row.get("심판번호")),
               str(row.get("상대번호") if row.get("상대번호") is not None else ""))
        if photos.get(key, False):
            counts["질의_사진(견주지_않음)"] += 1
            continue
        counts["견준_행"] += 1
        if image_only_grade(x2, model) == RISK:
            floor[i] = True
    final = named | floor
    added = final & ~named

    def block(selected):
        n = int(selected.sum())
        sources = Counter(rows[i].get("pair_source") or "trial" for i in np.flatnonzero(selected))
        return {"위험": n, "유사": int(y[selected].sum()),
                "정밀도": round(float(y[selected].mean()), 4) if n else None,
                "출처": dict(sources)}

    new_block = block(added)
    judged = new_block["위험"] >= NEW_RISK_MIN_ROWS
    passed = bool(same and (not judged or (new_block["정밀도"] is not None
                                           and new_block["정밀도"] >= PRECISION_MIN - 1e-12)))
    return {"재현_같음": bool(same), "행": int(mask.sum()), "세기": dict(counts),
            "지금": block(named), "새로_위험": new_block, "전체(후)": block(final),
            "판정에_씀": judged,
            "새로_위험_행": [{"pair_source": rows[i].get("pair_source"),
                             "심판번호": rows[i].get("심판번호"),
                             "x2_whole": lf._number(rows[i].get("x2_whole")), "유사": int(y[i]),
                             "OOF_p": round(float(prob[i]), 4)} for i in np.flatnonzero(added)],
            "통과": passed}


def cited_pairs(case_ids: set[str], model: dict) -> dict:
    """표본 A 인용상표 — 1차 시도 채택_4 의 쌍·서비스 채점식에 이미지만 판단을 더함(보고)."""
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    before, after = Counter(), Counter()
    risk = {"전": Counter(), "후": Counter()}
    changed: Counter = Counter()
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
            grade_after = higher(grade_before, image_only_grade(features["x2_whole"], model))
        label = row.get("최종라벨")
        pairs += 1
        before[grade_before] += 1
        after[grade_after] += 1
        if grade_after != grade_before:
            changed[f"{label} {grade_before}→{grade_after}"] += 1
        for tag, grade in (("전", grade_before), ("후", grade_after)):
            if grade == RISK:
                risk[tag][label] += 1

    def rate(counter):
        n = sum(counter.values())
        return round(sum(v for g, v in counter.items() if lf.at_least(g, REVIEW)) / n, 4) if n \
            else None

    def prec(counter):
        n = sum(counter.values())
        return {"위험": n, "유사": counter.get("유사", 0),
                "정밀도": round(counter.get("유사", 0) / n, 4) if n else None}

    return {"쌍": pairs, "사건": len(case_ids), "등급(전)": lf.distribution(before.elements()),
            "등급(후)": lf.distribution(after.elements()), "검토_권장_이상(전)": rate(before),
            "검토_권장_이상(후)": rate(after), "위험_정밀도(전)": prec(risk["전"]),
            "위험_정밀도(후)": prec(risk["후"]), "바뀐_쌍": dict(changed)}


def timing_table(searches: dict) -> dict:
    groups = {"양성 이름+이미지": [p["방식"][m] for p in searches["양성"]
                               for m in ("업종 없음", "같은 업종")],
              "음성 이름+이미지": [row["방식"][label] for row in searches["음성"]
                               for label, _ in COMBOS],
              "표본A 이름+이미지": [row["이름+이미지"] for row in searches["표본A"]]}
    out = {}
    for name, items in groups.items():
        if not items:
            continue
        block = {"질의": len(items)}
        for field_name in ("ms", "모델_ms"):
            b = [item["전"][field_name] for item in items]
            a = [item["후"][field_name] for item in items]
            diff = [y - x for x, y in zip(b, a)]
            block[field_name] = {"전_중앙": round(statistics.median(b), 2),
                                 "후_중앙": round(statistics.median(a), 2),
                                 "전_95%": round(float(np.percentile(b, 95)), 2),
                                 "후_95%": round(float(np.percentile(a, 95)), 2),
                                 "차이_중앙": round(statistics.median(diff), 2),
                                 "차이_평균": round(statistics.fmean(diff), 2)}
        out[name] = block
    return out


def scenario_table(scenarios: dict) -> list[dict]:
    rows = []
    for key, before in scenarios["전"].items():
        after = scenarios["후"].get(key, {})
        if "전체" not in before or "전체" not in after:
            rows.append({"키": key, "제목": before.get("제목"), "건너뜀": True})
            continue
        rows.append({"키": key, "제목": before["제목"], "전": before["전체"], "후": after["전체"],
                     "전_1위": before["상위"][0]["title"] if before["상위"] else None,
                     "후_1위": after["상위"][0]["title"] if after["상위"] else None,
                     "후_nameless_floor": sum(1 for c in after["상위"]
                                              if "nameless_floor" in c["rules"]),
                     "바뀜": before["전체"] != after["전체"]
                     or [c["id"] for c in before["상위"]] != [c["id"] for c in after["상위"]]})
    return rows


# ---- 0. 고정 -----------------------------------------------------------------------------------

def command_freeze(args) -> int:
    paths = _paths(args.out_dir)
    if paths["rule"].exists() and not args.force:
        print(f"거절: {paths['rule']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    if control["대조군_sha256"] != ns.CONTROL_SHA:
        print("거절: 1차 시도 대조군 해시가 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    args.out_dir.mkdir(parents=True, exist_ok=True)
    frozen = {"설정_sha256": rule_sha256(), "스크립트_sha256": first.file_sha256(Path(__file__)),
              "입력_sha256": {k: first.file_sha256(p) for k, p in _inputs().items()},
              "고정": _now(), "설정": _settings()}
    paths["rule"].write_text(json.dumps(frozen, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    print(f"설정 sha256 {frozen['설정_sha256']} · 스크립트 sha256 {frozen['스크립트_sha256']} · "
          f"엔진 sha256 {frozen['입력_sha256']['엔진']}")
    return 0


def _check_frozen(paths: dict, *, model_may_change: bool = False) -> dict | None:
    if not paths["rule"].exists():
        print("거절: 먼저 freeze", file=sys.stderr)
        return None
    frozen = json.loads(paths["rule"].read_text(encoding="utf-8"))
    if frozen["설정_sha256"] != rule_sha256():
        print("거절: 설정이 고정본과 다릅니다", file=sys.stderr)
        return None
    skip = {"런타임"} if model_may_change else set()  # 적용 뒤에는 기본 경로·버전 상수가 바뀐다
    changed = [k for k, p in _inputs().items()
               if k not in skip and first.file_sha256(p) != frozen["입력_sha256"].get(k)]
    if changed:
        print(f"거절: 입력이 고정 때와 다릅니다 — {changed}", file=sys.stderr)
        return None
    return frozen


# ---- 1. 검색 -----------------------------------------------------------------------------------

def memo_ocr(ms) -> None:
    detect = ms.ocr.detect
    memo: dict[str, object] = {}

    def memo_detect(image, **kwargs):
        key = hashlib.sha1(image.tobytes()).hexdigest() + f"|{image.size}|{image.mode}"
        if key not in memo:
            memo[key] = detect(image, **kwargs)
        return memo[key]

    ms.ocr.detect = memo_detect


def searcher(ms, models: dict[str, dict]):
    def search(mode: str, **inputs):
        with ns.using_model(ms, models[mode]):
            started = time.perf_counter()
            pooled = ms.search_pool(**inputs)
            return pooled, (time.perf_counter() - started) * 1000.0
    return search


def paired(search, index: int, accepted=None, **inputs) -> dict:
    search("후", **inputs)  # 데우기(시간에 넣지 않음)
    out = {}
    for mode in (("전", "후") if index % 2 == 0 else ("후", "전")):
        pooled, elapsed = search(mode, **inputs)
        out[mode] = summarize(pooled, elapsed, accepted)
    return out


def image_alone(search, **inputs) -> dict:
    """이미지만(이름·업종 없이) — 후로 재고 전과 같은지도 본다."""
    after, elapsed = search("후", **inputs)
    before, _ = search("전", **inputs)
    out = summarize(after, elapsed)
    out["전과_같음"] = ([c.id for c in after.candidates[:DISPLAY_TOP]]
                     == [c.id for c in before.candidates[:DISPLAY_TOP]]
                     and lf.overall_grade([c.grade for c in after.candidates])
                     == lf.overall_grade([c.grade for c in before.candidates]))
    return out


def scenarios(context: dict, models: dict[str, dict]) -> dict:
    from scripts import named_shared_threshold as second

    ms = context["ms"]
    out = {}
    for label, model in models.items():
        out[label] = {}
        suggested = None
        with ns.using_model(ms, model):
            for key, title, inputs in second.scenario_inputs(ms, context["service"]):
                if inputs.get("name") == "@S3":
                    if not suggested:
                        out[label][key] = {"제목": title, "건너뜀": True}
                        continue
                    inputs["name"] = suggested
                data = ms.multi_search(**inputs, top_k=DISPLAY_TOP).to_dict()
                if key == "S3":
                    suggested = data["overall"]["query_type"].get("suggested_name")
                out[label][key] = {
                    "제목": title,
                    "전체": {k: data["overall"][k] for k in ("grade", "prob", "pattern")},
                    "상위": [{"id": c["id"], "title": c["title"], "grade": c["risk"]["grade"],
                            "prob": c["risk"]["prob"], "pattern": c["risk"]["pattern"],
                            "rules": c["risk"]["rule_triggers"]} for c in data["candidates"]]}
    return out


def scenario_fidelity(before: dict) -> dict:
    saved = json.loads(SAVED_SCENARIOS.read_text(encoding="utf-8"))["시나리오"]
    differ = [key for key, item in saved.items()
              if item.get("전체") != before.get(key, {}).get("전체")
              or [c["id"] for c in item.get("상위", [])]
              != [c["id"] for c in before.get(key, {}).get("상위", [])]]
    return {"견준_시나리오": len(saved), "다른_것": differ, "같음": not differ}


def run_all(context: dict, models: dict[str, dict], limit: int | None) -> dict:
    ms = context["ms"]
    search = searcher(ms, models)
    timing: dict[str, float] = {}

    def tick(name: str, began: float, count: int) -> None:
        timing[name] = round(time.perf_counter() - began, 1)
        print(f"  {name} {count}질의 {timing[name]}초", flush=True)

    with gzip.open(POSITIVES, "rt", encoding="utf-8") as handle:
        source = json.load(handle)["양성"][:limit]
    began = time.perf_counter()
    positives = []
    index = 0
    for item in source:
        image = context["service"]((ML_ROOT / "data" / item["이미지"]).read_bytes())
        accepted = set(item["인정"])
        row = {"출원번호": item["출원번호"], "이름": item["이름"], "방식": {}}
        for mode, goods in (("업종 없음", None), ("같은 업종", sorted(item["유사군"]) or None)):
            row["방식"][mode] = paired(search, index, accepted, image=image, name=item["이름"],
                                       goods_codes=goods)
            index += 1
        row["이미지만"] = image_alone(search, image=image)
        positives.append(row)
        if len(positives) % 50 == 0:
            print(f"    양성 {len(positives)}/{len(source)}", flush=True)
    tick("양성", began, len(positives))
    a_by_key = {query.key: query for query in context["A"]}
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    began = time.perf_counter()
    negatives = []
    for i, item in enumerate(control["대조군"]["이름"]["확인용"][:limit]):
        image = context["service"](a_by_key[item["이미지"]].path.read_bytes())
        goods = sorted(item["유사군"]) or None
        row = {"이름": item["이름"], "이미지": item["이미지"], "방식": {}}
        for label, with_goods in COMBOS:
            row["방식"][label] = paired(search, i, image=image, name=item["이름"],
                                        goods_codes=goods if with_goods else None)
        row["이미지만"] = image_alone(search, image=image)
        negatives.append(row)
    tick("음성", began, len(negatives))
    began = time.perf_counter()
    sample_a = []
    for i, query in enumerate(context["A"][:limit]):
        image = context["service"](query.path.read_bytes())
        goods = sorted(query.goods) or None
        sample_a.append({"질의": query.key,
                         "이름+이미지": paired(search, i, image=image, name=query.name,
                                            goods_codes=goods),
                         "이미지만": image_alone(search, image=image)})
    tick("표본A", began, len(sample_a))
    return {"양성": positives, "음성": negatives, "표본A": sample_a, "시간_s": timing}


def command_run(args) -> int:
    paths = _paths(args.out_dir)
    frozen = _check_frozen(paths)
    if frozen is None:
        return EXIT_REFUSED
    if paths["searches"].exists() and not args.force:
        print(f"거절: {paths['searches']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    base = rm.validate_model(json.loads(rm.V141_MODEL_PATH.read_text(encoding="utf-8")))
    context = ns._context(rm.V141_MODEL_PATH)
    ms = context["ms"]
    if ms.state.model.get("version") != BASE_VERSION or rm.logo_floor_enabled(ms.state.model):
        print("거절: 엔진 모델이 표시 없는 v1.4.1 이 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    memo_ocr(ms)
    candidate = candidate_model(base)
    models = {"전": ms.state.model, "후": candidate}
    began = time.perf_counter()
    scenario_runs = scenarios(context, models)
    fidelity = scenario_fidelity(scenario_runs["전"])
    print(f"  시나리오 {round(time.perf_counter() - began, 1)}초 · 검산 {fidelity}", flush=True)
    out = {"설정_sha256": frozen["설정_sha256"],
           "스크립트_sha256(고정 때)": frozen["스크립트_sha256"],
           "스크립트_sha256(잴 때)": first.file_sha256(Path(__file__)),
           "스모크": bool(args.smoke), "검산_시나리오": fidelity, "시나리오": scenario_runs}
    if fidelity["같음"]:
        out.update(run_all(context, models, 4 if args.smoke else None))
    out["걸린_시간_s"] = round(time.perf_counter() - started, 1)
    out["끝"] = _now()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    paths["candidate"].write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
    with gzip.open(paths["searches"], "wt", encoding="utf-8") as handle:
        json.dump(out, handle, ensure_ascii=False)
    print(f"→ {paths['searches']}")
    if not fidelity["같음"]:
        print(f"멈춤: 바꾸기 전 시나리오가 저장값과 다릅니다 — {fidelity['다른_것']}",
              file=sys.stderr)
        return EXIT_STOP
    return 0


# ---- 2. 채택 조건·보고 ------------------------------------------------------------------------

def command_report(args) -> int:
    paths = _paths(args.out_dir)
    frozen = _check_frozen(paths)
    if frozen is None:
        return EXIT_REFUSED
    with gzip.open(paths["searches"], "rt", encoding="utf-8") as handle:
        searches = json.load(handle)
    if searches["설정_sha256"] != frozen["설정_sha256"]:
        print("거절: 검색 원자료가 다른 설정으로 만들어졌습니다", file=sys.stderr)
        return EXIT_REFUSED
    candidate = json.loads(paths["candidate"].read_text(encoding="utf-8"))
    results = {key: searches[key] for key in ("설정_sha256", "스크립트_sha256(고정 때)",
                                              "스크립트_sha256(잴 때)", "스모크", "검산_시나리오")}
    results["스크립트_sha256(보고 때)"] = first.file_sha256(Path(__file__))
    results["엔진_sha256"] = frozen["입력_sha256"]["엔진"]
    if not searches["검산_시나리오"]["같음"]:
        results.update(채택=False, 멈춤="바꾸기 전 시나리오가 저장값과 다름", 끝=_now())
        return _finish(paths, results)
    case_ids = {row["질의"].split(":")[1] for row in searches["표본A"]}
    results["채택_1"] = check_positive(searches["양성"])
    results["채택_2"] = check_negative(searches["음성"])
    results["채택_3"] = check_never_lower(searches, candidate)
    results["채택_4"] = precision(candidate)
    results["표본A_인용상표"] = cited_pairs(case_ids, candidate)
    results["표본A_전체등급"] = {
        "전": lf.distribution(row["이름+이미지"]["전"]["전체"] for row in searches["표본A"]),
        "후": lf.distribution(row["이름+이미지"]["후"]["전체"] for row in searches["표본A"]),
        "이미지만": lf.distribution(row["이미지만"]["전체"] for row in searches["표본A"])}
    alone = [row["이미지만"]["전과_같음"] for key in ("양성", "음성", "표본A")
             for row in searches[key]]
    results["이미지만_질의_전후_같음"] = f"{sum(alone)}/{len(alone)}"
    results["시나리오"] = scenario_table(searches["시나리오"])
    results["시간"] = timing_table(searches)
    results["질의"] = {key: len(searches[key]) for key in ("양성", "음성", "표본A")}
    results["채택"] = all(results[f"채택_{i}"]["통과"] for i in range(1, 5))
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
    lines = ["# R-P0-1 3차 — 이미지만 판단과 견주기 — 확인 표본 보고", "",
             f"- 설정 sha256 `{results['설정_sha256']}` · 엔진 sha256 "
             f"`{results.get('엔진_sha256')}`",
             f"- 스크립트 고정 `{results['스크립트_sha256(고정 때)']}` · 잴 때 "
             f"`{results['스크립트_sha256(잴 때)']}` · 보고 때 "
             f"`{results.get('스크립트_sha256(보고 때)')}`",
             f"- 스모크 {results['스모크']} · 채택 **{results.get('채택')}** · 검산 "
             f"{results['검산_시나리오']}"]
    if "채택_1" not in results:
        return "\n".join(lines + ["", f"멈춤: {results.get('멈춤')}", ""])
    for i in range(1, 5):
        lines += ["", f"## 채택 {i} — {results[f'채택_{i}']['통과']}", "", "```",
                  json.dumps(results[f"채택_{i}"], ensure_ascii=False)[:2000], "```"]
    cited = results["표본A_인용상표"]
    lines += ["", "## 표본 A 인용상표(보고)", "",
              f"- 쌍 {cited['쌍']} · 등급 전 {_dist(cited['등급(전)'])} → 후 "
              f"{_dist(cited['등급(후)'])}"
              f" · 검토 권장 이상 {_pct(cited['검토_권장_이상(전)'])} → "
              f"{_pct(cited['검토_권장_이상(후)'])} · 위험 정밀도 {cited['위험_정밀도(전)']} → "
              f"{cited['위험_정밀도(후)']} · 바뀐 쌍 {cited['바뀐_쌍']}",
              f"- 표본 A 검색 전체 등급: 전 {_dist(results['표본A_전체등급']['전'])} → 후 "
              f"{_dist(results['표본A_전체등급']['후'])} · 이미지만 "
              f"{_dist(results['표본A_전체등급']['이미지만'])}",
              f"- 이미지만 질의 전후 같음 {results['이미지만_질의_전후_같음']}",
              "", "## 시나리오 16종", "", "| 키 | 제목 | 전 | 후 | 1위(전 → 후) |",
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


# ---- 3·4. 적용·확인 ---------------------------------------------------------------------------

def command_apply(args) -> int:
    paths = _paths(args.out_dir)
    if _check_frozen(paths, model_may_change=True) is None:
        return EXIT_REFUSED
    results = json.loads(paths["results"].read_text(encoding="utf-8"))
    if not results.get("채택") or results.get("스모크"):
        print("거절: 채택되지 않았거나 스모크 결과입니다 — 적용하지 않습니다", file=sys.stderr)
        return EXIT_REFUSED
    if NEW_MODEL_PATH.exists() and not args.force:
        print(f"거절: {NEW_MODEL_PATH} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    candidate = json.loads(paths["candidate"].read_text(encoding="utf-8"))
    rm.validate_model({**candidate, "version": BASE_VERSION})
    NEW_MODEL_PATH.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    print(f"썼다: {NEW_MODEL_PATH} ({candidate['version']})")
    return 0


def command_verify(args) -> int:
    """기본 모델을 v1.4.2 로 바꾼 뒤 — 기본 엔진으로 다시 돌려 후 실행과 같은지."""
    paths = _paths(args.out_dir)
    if _check_frozen(paths, model_may_change=True) is None:
        return EXIT_REFUSED
    if rm.MODEL_VERSION != NEW_VERSION or rm.resolve_model_path() != NEW_MODEL_PATH:
        print("거절: 서비스 기본 모델이 v1.4.2 가 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    with gzip.open(paths["searches"], "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    context = ns._context(NEW_MODEL_PATH)
    ms = context["ms"]
    if ms.state.model.get("version") != NEW_VERSION or not rm.logo_floor_enabled(ms.state.model):
        print("거절: 엔진이 적재한 모델이 logo_floor 를 켠 v1.4.2 가 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    memo_ocr(ms)
    search = searcher(ms, {"후": ms.state.model, "전": ms.state.model})
    mismatch = Counter()
    checked = 0
    with gzip.open(POSITIVES, "rt", encoding="utf-8") as handle:
        source = {item["출원번호"]: item for item in json.load(handle)["양성"]}
    for row in saved["양성"]:
        item = source[row["출원번호"]]
        image = context["service"]((ML_ROOT / "data" / item["이미지"]).read_bytes())
        for mode, goods in (("업종 없음", None), ("같은 업종", sorted(item["유사군"]) or None)):
            pooled, _ = search("후", image=image, name=item["이름"], goods_codes=goods)
            got = summarize(pooled, 0.0, set(item["인정"]))
            want = row["방식"][mode]["후"]
            checked += 1
            mismatch["양성"] += int((got["전체"], got["인정_성공"]) != (want["전체"],
                                                                     want["인정_성공"]))
    a_by_key = {query.key: query for query in context["A"]}
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))
    by_name = {row["이름"]: row for row in saved["음성"]}
    for item in control["대조군"]["이름"]["확인용"]:
        image = context["service"](a_by_key[item["이미지"]].path.read_bytes())
        for label, with_goods in COMBOS:
            pooled, _ = search("후", image=image, name=item["이름"],
                               goods_codes=sorted(item["유사군"]) if with_goods else None)
            checked += 1
            mismatch["음성"] += int(lf.overall_grade([c.grade for c in pooled.candidates])
                                  != by_name[item["이름"]]["방식"][label]["후"]["전체"])
    for row in saved["표본A"]:  # 규칙 "적용" 의 표본 A(보고 뒤 더함 — 판정과 무관)
        query = a_by_key[row["질의"]]
        pooled, _ = search("후", image=context["service"](query.path.read_bytes()),
                           name=query.name, goods_codes=sorted(query.goods) or None)
        want = row["이름+이미지"]["후"]
        checked += 1
        mismatch["표본A"] += int(
            lf.overall_grade([c.grade for c in pooled.candidates]) != want["전체"]
            or [c.id for c in pooled.candidates[:DISPLAY_TOP]] != [c["id"] for c in want["상위"]])
    default = scenarios(context, {"기본": ms.state.model})["기본"]
    after = saved["시나리오"]["후"]
    scenario_diff = [key for key, item in default.items()
                     if item.get("전체") != after.get(key, {}).get("전체")
                     or [c["id"] for c in item.get("상위", [])]
                     != [c["id"] for c in after.get(key, {}).get("상위", [])]]
    verify = {"모델": ms.state.model["version"], "다시_돌린_질의": checked,
              "불일치": dict(mismatch), "시나리오_다른_것": scenario_diff,
              "통과": not any(mismatch.values()) and not scenario_diff,
              "걸린_시간_s": round(time.perf_counter() - started, 1), "끝": _now()}
    paths["verify"].write_text(json.dumps(verify, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")
    print(json.dumps(verify, ensure_ascii=False))
    return 0 if verify["통과"] else EXIT_STOP


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("freeze", "run", "report", "apply", "verify"))
    parser.add_argument("--out-dir", type=Path, default=TRIALS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--smoke", action="store_true",
                        help="시험 실행 — 양성·음성·표본 A 4건씩(--out-dir 를 따로)")
    args = parser.parse_args(argv)
    if args.smoke and args.out_dir.resolve() == TRIALS.resolve():
        print("거절: --smoke 는 --out-dir 를 따로 주세요", file=sys.stderr)
        return EXIT_REFUSED
    return {"freeze": command_freeze, "run": command_run, "report": command_report,
            "apply": command_apply, "verify": command_verify}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
