"""통합 모델 v1.4 **1차 시도**(채택되지 않음 — 재현용) — 1·2차 정답 데이터(`pairs_features.csv`
597행) + 쉬운 음성(`pairs_features_easy.csv` 700쌍)으로 v1.3 구조를 **이름 쪽으로 하나만** 넓혀
여섯 계수 집합을 모두 다시 학습하고, 기존 v1.3(`shared/model/risk_model_v1.json`)과 같은 표·같은
방식으로 비교한다(통합 모델 설계 §7-4-1). 채택된 v1.4 는 2차 시도
(`train_risk_model_v14_nameless.py` → `shared/model/risk_model_v1.4.json`)이고, 이 스크립트는 그
파일을 건드리지 않는다. KIPRIS 호출 0. 보고는 `ml/data/trials/risk_model_v1.4_{report.md,
results.json}`, 계수 JSON 은 미리 고정한 채택 기준(ADOPTION)을 통과하면 `--model` 경로(기본
`ml/data/trials/risk_model_v1.4_attempt1.json`), 못 미치면
`ml/data/trials/risk_model_v1.4_candidate.json`(후보로만 — 종료 코드 3). 데이터 적재·가중 지표·묶음
부트스트랩 같은 도우미는 2차 시도 스크립트가 그대로 가져다 쓴다.

    ml/venv/bin/python ml/scripts/train_risk_model_v14.py                    # 전체(약 40초)
    ml/venv/bin/python ml/scripts/train_risk_model_v14.py --bootstrap 20 --metric-bootstrap 100 \\
        --repeats 1 --no-sensitivity --no-diagnostics                        # 빠른 확인

2026-11-19 실행 결과: 채택 기준 ①·② 미달로 채택 보류(설계 §7-4-1) — 이름 결합 제약이 이름 있는
입력의 변별력을 깎는다. --fit-mode sequential·name_coupling=False·--structure v1.3 은 그 원인을
확인한 사후 진단이다(채택 판단 대상이 아니다). 그 뒤 2차 시도가 이름 있는 쪽을 v1.3 으로 고정하고
이름 결합을 "같은 이름" 하나로 바꿔 채택됐다.

v1.3 과 같은 것: 판례 사전분포(μ·σ 1.0) + 단조 제약 로지스틱, 결측 패턴별 계수 집합(이미지 ×
상품 4벌, 각 집합은 그 축들이 관측된 모든 행으로 적합), 결합 제약(축을 하한 이상으로 더 관측해도
로짓이 내려가지 않음 — 설계 항 상자의 모든 꼭짓점), 쉬운 음성 가중 0.5, 패턴당 소수 클래스 ≥ 50,
등급·단독 임계값 규칙. train_risk_model.py(v1.3 학습)의 도우미를 그대로 쓴다.

v1.4 에서 달라진 것:
  ① 이름 없는 행을 학습에 넣는다. 결측 패턴을 이름까지 넓혀 **이름 없음 2벌**(이미지만
     `noname:x2_whole` / 이미지+상품 `noname:x2_whole+x4`)을 더한다 — 입력은 이미지·상품 항뿐이고,
     이미지(·상품)가 관측된 모든 행으로 적합한다(이름이 있는 행도 이름을 가리고 참여). 결합 제약도
     같은 원리로 넓힌다: 이름 없는 패턴 안에서 상품을 하한 이상으로 더 관측하는 것, 이름을 하한(쉬운
     음성 평균; 관념은 게이트 결측이 값 0 이라 0) 이상으로 더 관측하는 것 모두 로짓 비감소.
     상품만 있는 입력은 학습 대상이 아니다(런타임은 종전대로 이름 있는 패턴에 이름 항 0). 이름도
     이미지도 없는 행은 제외하고 수를 보고한다.
  ② 사건 단위 가중 w = min(1, 3 / 그 사건의 행 수) — 학습·평가 모두(평가는 가중이 주 값).
  ③ 사진 표장: 이미지가 있는 모든 쌍에서 사진A·사진B(src.photo_mark 판정)가 하나라도 1 이면 이미지
     축을 관측 없음으로 둔다(--no-photo-rule 은 민감도용).
  ④ 교차검증·부트스트랩의 묶음: 심판번호, 그리고 같은 표장 쌍 키(쌍키)를 가진 사건들은 한 묶음.
     모델 비교는 같은 묶음을 다시 뽑는 짝 차이.

채택 기준(미리 고정 — ADOPTION): 기본은 v1.4 채택. 단 ① 기존 v1.3 과의 짝 차이 CI 상한이 0 미만인
지표가 있거나 ② 판례 조건이 v1.3 보다 나빠지거나 ③ 단조성이 깨지면 멈추고 보고한다. 새 패턴이
제약을 만족하지 못하거나 적합이 불안정하면 --structure v1.3(이름 있는 행만)으로 되돌린다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from scipy.optimize import minimize  # noqa: E402
from scipy.special import expit  # noqa: E402
from src.model import risk_model as rm  # noqa: E402

from scripts import train_risk_model as tr  # noqa: E402  (v1.3 학습 도구 — numpy·scipy 만)

MODEL_VERSION = "risk_model_v1.4"
# 1차 시도의 계수 JSON 기본 경로 — shared/model/risk_model_v1.4.json(2차 시도의 채택분)이 아니다
DEFAULT_MODEL = tr.DEFAULT_BASE / "risk_model_v1.4_attempt1.json"
DEFAULT_V13 = rm.DEFAULT_MODEL_PATH
DEFAULT_OUT_DIR = tr.DEFAULT_BASE
REPORT_STEM = "risk_model_v1.4"
SIGMA = 1.0  # v1.2.1 부터 고정(설계 §7-2)
W_EASY = tr.W_EASY
CASE_CAP = 3.0  # 사건 단위 가중: w = min(1, CASE_CAP / 그 사건의 행 수)
FOLDS, REPEATS = tr.FOLDS, tr.REPEATS
BOOTSTRAP = tr.BOOTSTRAP  # 계수·판례 조건(재적합)
METRIC_BOOTSTRAP = 1000  # 지표 CI·짝 차이(묶음 복원추출)
PATTERN_AXES = tr.PATTERN_AXES
NAMELESS_KEYS = ("x2_whole", "x2_whole+x4")  # 이름 없음 패턴(이미지가 관측된 것만)
NAME_FLOOR_BASIS = ("쉬운 음성(현실 분포) 비유사 쌍 평균 — 호칭·철자. 관념은 게이트 결측이 값 0 "
                    "이라 하한 0(이름을 관측했는데 관념 게이트가 꺼져 있어도 성립하도록)")
PHOTO_COLUMNS = ("사진A", "사진B")
RAW_IMAGE = "x2_whole_raw"  # 사진 규칙을 적용하기 전 이미지 축 값
BIG_CASE = "2025101001193"  # 한 사건 40행(민감도)
IMAGE_ONLY_LEVELS = (0.5, 0.7, 0.9, 1.0)
STANDALONE_AXES = ("x1_d", "x2_text_d", "x3_d")  # 단독 임계값을 두는 축(호칭·철자·관념)
# 채택 기준(결과를 보기 전에 고정) --------------------------------------------------------------
ADOPTION = {
    "기본": "v1.4 채택",
    "①": ("기존 v1.3(배포 JSON 을 그대로 적용)과의 짝 차이 95% CI 상한이 0 미만인 지표가 있으면 "
          "멈춤"),
    "①_지표": ["가중 AUC: 어려운 문제 전체·1차·2차·문자계·도형계·이름 없는 행, 쉬운 음성 섞은 것",
              "가중 Brier(v1.3 − v1.4 로 부호를 맞춤): 어려운 문제 전체, 쉬운 음성 섞은 것"],
    "②": ("판례 조건이 나빠지면 멈춤 — 최종 적합에서 v1.3 이 성립한 조건이 불성립으로 바뀌거나, "
          "부트스트랩 성립 비율이 v1.3 보다 0.10 넘게 낮아짐"),
    "③": "단조성이 깨지면 멈춤 — 하한 이상 행에서 로짓이 내려간 행이 있거나 런타임 결합 검증 위반",
}
V13_CONDITIONS = {  # 설계 §7-3 표(v1.3): 최종 적합 성립 여부·부트스트랩 성립 비율
    tr.CONDITIONS[0]: (True, 1.00), tr.CONDITIONS[1]: (False, 0.44),
    tr.CONDITIONS[2]: (True, 0.99), tr.CONDITIONS[3]: (True, 1.00),
}
CONDITION_DROP = 0.10


def _round(value, digits: int = 4):
    return None if value is None else round(float(value), digits)


# ---- 데이터 -----------------------------------------------------------------------------------

def has_photo(row: dict) -> bool:
    return any(str(row.get(column, "")).strip() == "1" for column in PHOTO_COLUMNS)


def case_weights(rows: list[dict], cap: float | None = CASE_CAP) -> np.ndarray:
    """심결 행 w = min(1, cap / 그 사건의 심결 행 수), 쉬운 음성은 1(axes_benchmark.case_weights 와
    같은 정의). cap 이 없으면 모두 1."""
    if not cap or cap <= 0:
        return np.ones(len(rows))
    counts: dict[str, int] = {}
    for row in rows:
        if row["pair_source"] == "trial":
            counts[row["심판번호"]] = counts.get(row["심판번호"], 0) + 1
    return np.asarray([min(1.0, cap / counts[row["심판번호"]]) if row["pair_source"] == "trial"
                       else 1.0 for row in rows], dtype=np.float64)


def group_ids(rows: list[dict]) -> np.ndarray:
    """교차검증·부트스트랩 묶음. 심결 행은 심판번호, 같은 쌍키를 가진 사건들은 한 묶음(합집합).
    cross 는 이름 A 쪽 사건의 묶음(v1.3 과 같음), db 는 자기 키."""
    parent: dict[str, str] = {}

    def find(key: str) -> str:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    first_case: dict[str, str] = {}
    for row in rows:
        if row["pair_source"] != "trial":
            continue
        case = find(str(row["심판번호"]))
        pair = (row.get("쌍키") or "").strip()
        if pair:
            if pair in first_case:
                parent[find(case)] = find(first_case[pair])
            else:
                first_case[pair] = case
    out = []
    for row, plain in zip(rows, tr.groups_for(rows)):
        out.append(find(str(plain)) if row["pair_source"] in ("trial", "cross") else str(plain))
    return np.asarray(out)


@dataclass
class Dataset:
    rows: list[dict]  # 학습·평가 행(심결 + 쉬운 음성)
    excluded: list[dict]  # 이름도 이미지도 없어 뺀 심결 행
    summary: dict


def load_dataset(features_path: Path, easy_path: Path | None, *, photo_rule: bool = True,
                 case_cap: float | None = CASE_CAP, drop_cases: tuple[str, ...] = (),
                 drop_augmented: bool = False) -> Dataset:
    """특징 파일 → 학습 행. 사진 규칙(이미지 축 관측 없음)·사건 가중·묶음을 행에 붙이고
    (`_w`·`_group`), 이름도 이미지도 없는 심결 행은 뺀다."""
    loaded = [row for row in tr.load_rows(features_path, easy_path)
              if row.get("최종라벨") in ("유사", "비유사")]
    dropped = {"사건": 0, "보강": 0}
    kept = []
    for row in loaded:
        if row["pair_source"] == "trial" and row["심판번호"] in drop_cases:
            dropped["사건"] += 1
            continue
        if row["pair_source"] == "trial" and drop_augmented and (row.get("보강") or "").strip():
            dropped["보강"] += 1
            continue
        kept.append(row)
    weights = case_weights(kept, case_cap)
    groups = group_ids(kept)
    photo = {"trial": 0, "cross": 0, "db": 0}
    with_image = {"trial": 0, "cross": 0, "db": 0}
    for row, weight, group in zip(kept, weights, groups):
        row["_w"], row["_group"] = float(weight), str(group)
        row[RAW_IMAGE] = row["x2_whole"]
        if not np.isnan(row["x2_whole"]):
            with_image[row["pair_source"]] += 1
            if has_photo(row):
                photo[row["pair_source"]] += 1
                if photo_rule:
                    row["x2_whole"] = np.nan
    rows, excluded = [], []
    for row in kept:
        nameless = row["pair_source"] == "trial" and not tr.has_name(row)
        if nameless and np.isnan(row["x2_whole"]):
            excluded.append(row)
        else:
            rows.append(row)
    trial = [row for row in rows if row["pair_source"] == "trial"]
    nameless_rows = [row for row in trial if not tr.has_name(row)]
    summary = {
        "심결_행(특징 파일)": sum(1 for row in loaded if row["pair_source"] == "trial"),
        "민감도_제외": dropped,
        "심결_행(학습)": len(trial),
        "유사": sum(1 for row in trial if row["최종라벨"] == "유사"),
        "비유사": sum(1 for row in trial if row["최종라벨"] == "비유사"),
        "이름_있는_행": len(trial) - len(nameless_rows),
        "이름_없는_행": {"n": len(nameless_rows),
                     "유사": sum(1 for r in nameless_rows if r["최종라벨"] == "유사"),
                     "비유사": sum(1 for r in nameless_rows if r["최종라벨"] == "비유사")},
        "이름도_이미지도_없어_제외": {
            "n": len(excluded), "유사": sum(1 for r in excluded if r["최종라벨"] == "유사"),
            "비유사": sum(1 for r in excluded if r["최종라벨"] == "비유사"),
            "사진_규칙으로_이미지를_잃은_행": sum(1 for r in excluded
                                       if not np.isnan(r[RAW_IMAGE])),
        },
        "회차": {key: sum(1 for row in trial if row.get("회차") == key) for key in ("1", "2")},
        "사진_규칙": {"적용": photo_rule, "이미지_있는_쌍": with_image, "사진_낀_쌍": photo},
        "사건_가중": {
            "상한": case_cap, "사건": len({row["심판번호"] for row in trial}),
            "묶음": len({row["_group"] for row in trial}),
            "1_미만_행": sum(1 for row in trial if row["_w"] < 1.0),
            "가중_합": _round(sum(row["_w"] for row in trial), 2),
        },
        "쉬운_음성": {source: sum(1 for row in rows if row["pair_source"] == source)
                   for source in ("cross", "db")},
        "w_easy": W_EASY,
    }
    return Dataset(rows, excluded, summary)


def service_features(row: dict, *, image_column: str = "x2_whole") -> dict:
    """특징 행 → 런타임 입력 사전. 이름 없는 행은 엔진(multi_search)이 이름 없는 쌍에 넘기는 꼴
    (이름 축 None·요부 플래그 True)로 맞춘다."""
    out = tr.row_features(row)
    value = row.get(image_column, np.nan)
    out["x2_whole"] = None if value is None or np.isnan(value) else float(value)
    if not tr.has_name(row):
        out.update({"x1_d": None, "x2_text_d": None, "x3_d": None, "has_meaning_both": False,
                    "has_distinctive_part_a": True, "has_distinctive_part_b": True})
    return out


def v13_probabilities(rows: list[dict], model: dict) -> np.ndarray:
    """기존 v1.3(배포 JSON)을 그대로 적용한 확률 — 재학습·사진 규칙 없이(이미지 축은 원래 값)."""
    return np.asarray([rm.risk_score(service_features(row, image_column=RAW_IMAGE), model).prob
                       for row in rows])


# ---- 설계: 계수 집합(블록) ---------------------------------------------------------------------

def nameless_features(key: str) -> list[str]:
    names: list[str] = []
    for axis in PATTERN_AXES:
        if axis in rm.pattern_present(key):
            names += tr.PATTERN_AXIS_TERMS[axis]
    return names


class Design:
    """계수 집합(블록)별 설계행렬·행 마스크·행의 자기 블록·공동 매개변수 θ 의 위치.

    블록 id: 이름 있는 패턴은 패턴 키("base"·"x2_whole"·"x4"·"x2_whole+x4"), 이름 없는 패턴은
    "noname:" + 키. structure="v1.3" 이면 이름 없는 블록을 만들지 않는다(이름 없는 행은 어느 블록의
    학습에도 들지 않고, 평가 때는 런타임처럼 이름 있는 패턴에 이름 항 0)."""

    def __init__(self, rows: list[dict], *, structure: str = "v1.4",
                 nameless_keys: tuple[str, ...] = NAMELESS_KEYS):
        self.structure = structure
        self.axes = tuple(PATTERN_AXES)
        self.named_keys = rm.pattern_keys(self.axes)
        self.nameless_keys = tuple(nameless_keys) if structure == "v1.4" else ()
        self.reference = self.named_keys[-1]
        named = np.asarray([tr.has_name(row) for row in rows])
        flags = {axis: tr.observed(rows, axis) for axis in self.axes}
        features = [service_features(row) for row in rows]
        self.ids: list[str] = []
        self.names: dict[str, list[str]] = {}
        self.mask: dict[str, np.ndarray] = {}
        for key in self.named_keys:
            mask = named.copy()
            for axis in rm.pattern_present(key):
                mask &= flags[axis]
            self._add(key, tr.pattern_features(key, self.axes), mask)
        for key in self.nameless_keys:
            mask = np.ones(len(rows), dtype=bool)
            for axis in rm.pattern_present(key):
                mask &= flags[axis]
            self._add(rm.NAMELESS_PREFIX + key, nameless_features(key), mask)
        self.X = {block: np.asarray([rm.design_vector(f, self.names[block]) for f in features],
                                    dtype=np.float64) for block in self.ids}
        own = []
        for i in range(len(rows)):
            key = rm.pattern_key([axis for axis in self.axes if flags[axis][i]], self.axes)
            own.append(rm.NAMELESS_PREFIX + key
                       if not named[i] and key in self.nameless_keys else key)
        self.own = np.asarray(own)
        self.named = named
        self.offset: dict[str, int] = {}
        self.size = 0
        for block in self.ids:
            self.offset[block] = self.size
            self.size += len(self.names[block]) + 1

    def _add(self, block: str, names: list[str], mask: np.ndarray) -> None:
        self.ids.append(block)
        self.names[block] = list(names)
        self.mask[block] = mask

    def split(self, theta: np.ndarray) -> dict[str, tuple[np.ndarray, float]]:
        out = {}
        for block in self.ids:
            start, d = self.offset[block], len(self.names[block])
            out[block] = (theta[start:start + d], float(theta[start + d]))
        return out

    def logit(self, fitted: dict, block: str, index: np.ndarray) -> np.ndarray:
        coef, intercept = fitted[block]
        return self.X[block][index] @ coef + intercept

    def own_prob(self, fitted: dict, index: np.ndarray) -> np.ndarray:
        """행마다 런타임이 고를 계수 집합으로 낸 확률."""
        index = np.asarray(index)
        out = np.empty(len(index))
        own = self.own[index]
        for block in self.ids:
            where = own == block
            if where.any():
                out[where] = expit(self.logit(fitted, block, index[where]))
        return out


def block_counts(design: Design, y: np.ndarray, weight: np.ndarray, easy: np.ndarray) -> dict:
    out = {}
    for block in design.ids:
        mask = design.mask[block] & (weight > 0)
        own = design.own == block
        out[block] = {
            "입력": design.names[block], "n": int(mask.sum()),
            "n_심결": int((mask & ~easy).sum()), "n_쉬운_음성": int((mask & easy).sum()),
            "유사": int((y[mask] == 1).sum()), "비유사": int((y[mask] == 0).sum()),
            "가중_유사": _round(float(weight[mask & (y == 1)].sum()), 1),
            "가중_비유사": _round(float(weight[mask & (y == 0)].sum()), 1),
            "자기_패턴_행": int(own.sum()), "자기_패턴_심결": int((own & ~easy).sum()),
        }
    return out


def floors_for(rows: list[dict], y: np.ndarray, easy: np.ndarray) -> tuple[dict, dict, dict]:
    """결합 제약 하한: (패턴 축 하한, 이름 하한, 근거). 패턴 축은 v1.3 과 같은 규칙
    (tr.dissimilar_floors — 쉬운 음성 비유사 평균), 이름은 호칭·철자의 쉬운 음성 비유사 평균과
    관념 0."""
    floors, detail = tr.dissimilar_floors(rows, y, easy, PATTERN_AXES)
    name_floors: dict[str, float] = {}
    for axis in ("x1_d", "x2_text_d"):
        values = np.asarray([row.get(axis, np.nan) for row in rows], dtype=np.float64)
        seen = ~np.isnan(values) & (y == 0) & easy
        name_floors[axis] = round(float(values[seen].mean()), 4) if seen.any() else 0.0
        detail[axis] = {"하한": name_floors[axis], "근거": "쉬운 음성 비유사 평균",
                        "쉬운_음성_관측_n": int(seen.sum())}
    name_floors["x3_d"] = 0.0
    detail["x3_d"] = {"하한": 0.0, "근거": "게이트 결측이 값 0 — 하한 0"}
    return floors, name_floors, detail


# ---- 제약 --------------------------------------------------------------------------------------

@dataclass
class Constraint:
    kind: str  # "단조" | "결합(축)" | "결합(이름 없음, 축)" | "결합(이름)"
    label: str
    row: np.ndarray


def _difference(design: Design, upper: str, upper_input: dict, lower: str,
                lower_input: dict) -> np.ndarray:
    row = np.zeros(design.size)
    high = rm.design_vector(upper_input, design.names[upper])
    low = rm.design_vector(lower_input, design.names[lower])
    start = design.offset[upper]
    row[start:start + len(high)] += high
    row[start + len(high)] += 1.0
    start = design.offset[lower]
    row[start:start + len(low)] -= low
    row[start + len(low)] -= 1.0
    return row


def _vertex_label(vertex: dict) -> str:
    parts = [f"{key}={value}" for key, value in vertex.items()
             if key in ("x1_d", "x2_text_d", "x3_d", "mark_type", "x2_whole", "x4")
             and value is not None]
    if "has_distinctive_part_b" in vertex:
        parts.append(f"요부없음={not vertex['has_distinctive_part_b']}")
    return ", ".join(parts)


def build_constraints(design: Design, floors: dict[str, float],
                      name_floors: dict[str, float]) -> list[Constraint]:
    """G·θ ≥ 0 의 행 목록: 블록마다 단조 제약, 이름 있는 패턴 사이·이름 없는 패턴 사이의 결합 제약
    (축 하나를 하한값으로 더 관측), 이름 결합 제약(이름을 하한값으로 더 관측)."""
    out: list[Constraint] = []
    for block in design.ids:
        names = design.names[block]
        for g in tr.monotone_constraints(names):
            row = np.zeros(design.size)
            start = design.offset[block]
            row[start:start + len(g)] = g
            terms = " + ".join(name for name, value in zip(names, g) if value)
            out.append(Constraint("단조", f"{block}: {terms} ≥ 0", row))
    for key in design.named_keys:
        present = rm.pattern_present(key)
        for axis in present:
            lower = rm.pattern_key([a for a in present if a != axis], design.axes)
            for vertex in rm.coupling_vertices(design.names[lower]):
                out.append(Constraint(
                    "결합(축)",
                    f"{lower} → {key} ({axis}={floors[axis]}) @ {_vertex_label(vertex)}",
                    _difference(design, key, {**vertex, axis: floors[axis]}, lower, vertex)))
    for key in design.nameless_keys:
        block = rm.NAMELESS_PREFIX + key
        present = rm.pattern_present(key)
        for axis in present:
            lower_key = rm.pattern_key([a for a in present if a != axis], design.axes)
            if lower_key not in design.nameless_keys:
                continue
            lower = rm.NAMELESS_PREFIX + lower_key
            for vertex in rm.nameless_vertices(design.names[lower]):
                out.append(Constraint(
                    "결합(이름 없음, 축)",
                    f"{lower} → {block} ({axis}={floors[axis]}) @ {_vertex_label(vertex)}",
                    _difference(design, block, {**vertex, axis: floors[axis]}, lower, vertex)))
        named_input = {axis: float(name_floors.get(axis, 0.0)) for axis in rm.NAME_FLOOR_AXES}
        for vertex in rm.name_coupling_vertices(design.names[block]):
            out.append(Constraint(
                "결합(이름)", f"{block} → {key} (이름={named_input}) @ {_vertex_label(vertex)}",
                _difference(design, key, {**vertex, **named_input, "has_meaning_both": True},
                            block, vertex)))
    return out


# ---- 적합 --------------------------------------------------------------------------------------

@dataclass
class Fit:
    blocks: dict[str, tuple[np.ndarray, float]]
    theta: np.ndarray
    success: bool  # KKT 잔차 검사(아래) 통과 여부
    kkt_residual: float
    min_slack: float
    solver: str


KKT_TOLERANCE = 1e-4  # ‖∇f − G_Aᵀλ‖ / max(1, ‖∇f‖) (λ ≥ 0, A = 경계에 붙은 제약)


def _kkt_residual(gradient: np.ndarray, G: np.ndarray, slack: np.ndarray) -> float:
    """제약 최적성 검사: 경계에 붙은 제약의 음이 아닌 결합으로 기울기를 설명하고 남는 잔차(상대값).
    SLSQP 는 경계가 겹친 최적점에서 status 8 로 끝나는 일이 잦아 result.success 를 믿을 수 없다."""
    from scipy.optimize import nnls

    scale = max(1.0, float(np.linalg.norm(gradient)))
    active = slack < 1e-7
    if not active.any():
        return float(np.linalg.norm(gradient)) / scale
    _, residual = nnls(G[active].T, gradient, maxiter=20 * G.shape[1] + 200)
    return float(residual) / scale


def fit_joint(design: Design, y: np.ndarray, weight: np.ndarray, index: np.ndarray,
              constraints: list[Constraint], *, sigma: float = SIGMA,
              mu: dict[str, float] | None = None,
              fixed: dict[str, tuple[np.ndarray, float]] | None = None) -> Fit:
    """모든 블록을 한 번에: Σ_블록 [사전분포 벌점 + Σ s·logloss(그 블록의 축이 관측된 행)] 을 제약
    G·θ ≥ 0 아래 최소화(tr.fit_patterns_prior 와 같은 목적함수 — 블록만 늘었다). SLSQP 로 풀고 KKT
    잔차로 최적성을 확인하며, 미달이면 trust-constr(정확한 헤시안)로 다시 푼다.

    fixed: 값을 고정할 블록(사후 진단의 순차 적합 — 이름 있는 패턴을 먼저 정하고 이름 없는 패턴만
    제약 아래 적합)."""
    mu_map = mu or tr.PRIOR_MU
    index = np.asarray(index)
    fixed = fixed or {}
    theta0 = np.zeros(design.size)
    free = np.ones(design.size, dtype=bool)
    data = []
    for block in design.ids:
        names = design.names[block]
        offset = design.offset[block]
        d = len(names)
        if block in fixed:
            theta0[offset:offset + d] = fixed[block][0]
            theta0[offset + d] = fixed[block][1]
            free[offset:offset + d + 1] = False
            continue
        rows_index = index[design.mask[block][index] & (weight[index] > 0)]
        mu_vector = np.asarray([mu_map.get(name, 0.0) for name in names])
        precision = np.asarray([1.0 / (sigma * sigma) if name in mu_map else 0.0
                                for name in names])
        theta0[offset:offset + d] = mu_vector
        # 이름 없는 블록의 절편은 낮게 시작(이름 결합 제약을 만족하는 쪽)
        theta0[offset + d] = -5.0 if block.startswith(rm.NAMELESS_PREFIX) else 0.0
        X = design.X[block][rows_index]
        data.append((X, np.column_stack([X, np.ones(X.shape[0])]), y[rows_index],
                     weight[rows_index], mu_vector, precision, offset))
    G_all = (np.asarray([c.row for c in constraints]) if constraints
             else np.zeros((0, design.size)))
    keep = np.abs(G_all[:, free]).sum(axis=1) > 0 if G_all.shape[0] else np.zeros(0, dtype=bool)
    G = G_all[keep][:, free]
    shift = G_all[keep][:, ~free] @ theta0[~free] if (~free).any() else np.zeros(G.shape[0])
    position = np.flatnonzero(free)

    def expand(x: np.ndarray) -> np.ndarray:
        theta = theta0.copy()
        theta[position] = x
        return theta

    def objective(x: np.ndarray) -> tuple[float, np.ndarray]:
        theta = expand(x)
        value = 0.0
        gradient = np.zeros(design.size)
        for X, _Xb, yy, ww, mu_vector, precision, offset in data:
            d = X.shape[1]
            coef, b = theta[offset:offset + d], theta[offset + d]
            z = X @ coef + b
            loss = np.logaddexp(0.0, z) - yy * z
            diff = coef - mu_vector
            value += 0.5 * float(np.sum(precision * diff * diff)) + float(np.sum(ww * loss))
            residual = ww * (expit(z) - yy)
            gradient[offset:offset + d] = precision * diff + X.T @ residual
            gradient[offset + d] = float(residual.sum())
        return value, gradient[position]

    def hessian(x: np.ndarray) -> np.ndarray:
        theta = expand(x)
        H = np.zeros((design.size, design.size))
        for X, Xb, _yy, ww, _mu, precision, offset in data:
            d = X.shape[1]
            prob = expit(X @ theta[offset:offset + d] + theta[offset + d])
            H[offset:offset + d + 1, offset:offset + d + 1] += Xb.T @ (
                Xb * (ww * prob * (1 - prob))[:, None])
            H[offset:offset + d, offset:offset + d] += np.diag(precision)
        return H[np.ix_(position, position)]

    def residual_of(x: np.ndarray) -> tuple[float, float]:
        slack = G @ x + shift if G.shape[0] else np.zeros(0)
        return (_kkt_residual(objective(x)[1], G, slack),
                float(slack.min()) if slack.size else 0.0)

    slsqp = ([{"type": "ineq", "fun": lambda t: G @ t + shift, "jac": lambda t: G}]
             if G.shape[0] else [])
    result = minimize(objective, theta0[position], jac=True, method="SLSQP", constraints=slsqp,
                      options={"maxiter": 3000, "ftol": 1e-12})
    x, solver = result.x, "SLSQP"
    kkt, slack = residual_of(x)
    if kkt > KKT_TOLERANCE or slack < -1e-7:
        from scipy.optimize import LinearConstraint

        linear = [LinearConstraint(G, -shift, np.inf)] if G.shape[0] else []
        retry = minimize(lambda t: objective(t)[0], x, jac=lambda t: objective(t)[1],
                         hess=hessian, method="trust-constr", constraints=linear,
                         options={"maxiter": 3000, "gtol": 1e-9, "xtol": 1e-12,
                                  "barrier_tol": 1e-10})
        retry_kkt, retry_slack = residual_of(retry.x)
        if retry_slack >= -1e-7 and (retry_kkt < kkt or slack < -1e-7):
            x, solver, kkt, slack = retry.x, "trust-constr", retry_kkt, retry_slack
    theta = expand(x)
    if G_all.shape[0] and not fixed:
        theta = tr._project_feasible(theta, G_all)  # noqa: SLF001 - v1.3 과 같은 다듬기
        slack = float((G_all @ theta).min())
    return Fit(design.split(theta), theta, bool(kkt <= KKT_TOLERANCE and slack >= -1e-6),
               float(kkt), float(slack), solver)


def fit_mode(design: Design, y: np.ndarray, weight: np.ndarray, index: np.ndarray,
             constraints: list[Constraint], mode: str = "joint") -> Fit:
    """mode "joint"(명세 — 여섯 집합을 한 번에) / "sequential"(사후 진단 — 이름 있는 패턴 네 벌을
    먼저 적합해 고정하고, 이름 없는 패턴 두 벌만 제약 아래 적합)."""
    if mode == "joint" or not design.nameless_keys:
        return fit_joint(design, y, weight, index, constraints)
    if mode != "sequential":
        raise ValueError(f"모르는 적합 방식: {mode}")
    named_only = [c for c in constraints if c.kind in ("단조", "결합(축)")
                  and not c.label.startswith(rm.NAMELESS_PREFIX)]
    nameless_ids = [rm.NAMELESS_PREFIX + key for key in design.nameless_keys]
    stage = fit_joint(design, y, weight, index, named_only,
                      fixed={block: (np.zeros(len(design.names[block])), -5.0)
                             for block in nameless_ids})
    final = fit_joint(design, y, weight, index, constraints,
                      fixed={block: stage.blocks[block] for block in design.named_keys})
    return Fit(final.blocks, final.theta, stage.success and final.success,
               max(stage.kkt_residual, final.kkt_residual), final.min_slack,
               f"{stage.solver}+{final.solver}")


def cv_oof(design: Design, y: np.ndarray, weight: np.ndarray, groups: np.ndarray,
           constraints: list[Constraint], *, folds: int, repeats: int, seed: int,
           mode: str = "joint") -> dict:
    """묶음 단위 반복 교차검증 — 행마다 자기 블록의 OOF 확률(반복 평균)과 블록별 OOF 확률."""
    own_total = np.zeros(y.size)
    per_total = {block: np.zeros(y.size) for block in design.ids}
    success, slack, solvers = [], [], []
    for repeat in range(repeats):
        for train, test in tr.folds_for(y, groups, folds=folds, seed=seed + repeat):
            fit = fit_mode(design, y, weight, train, constraints, mode)
            success.append(fit.success)
            slack.append(fit.min_slack)
            solvers.append(fit.solver)
            own_total[test] += design.own_prob(fit.blocks, test)
            for block in design.ids:
                per_total[block][test] += expit(design.logit(fit.blocks, block, test))
    return {"own": own_total / repeats,
            "per_block": {block: total / repeats for block, total in per_total.items()},
            "겹_수": len(success), "수렴_실패": int(len(success) - sum(success)),
            "최소_여유": _round(min(slack), 9) if slack else None,
            "trust-constr_재적합": sum(1 for name in solvers if "trust" in name)}


# ---- 평가: 가중 지표·묶음 부트스트랩·짝 차이 -----------------------------------------------------

def weighted_auc(scores: np.ndarray, labels: np.ndarray, weights: np.ndarray) -> float | None:
    """가중 ROC AUC — 유사 i·비유사 j 쌍을 w_i·w_j 로 센 Mann–Whitney(동점 0.5). axes_benchmark 와
    같은 정의(가중치가 모두 1 이면 순위 AUC)."""
    if scores.size == 0:
        return None
    _, tie = np.unique(scores, return_inverse=True)
    return _tie_auc(tie, weights * (labels == 1), weights * (labels == 0))


def _tie_auc(tie: np.ndarray, w_pos: np.ndarray, w_neg: np.ndarray) -> float | None:
    pos = np.bincount(tie, weights=w_pos)
    neg = np.bincount(tie, weights=w_neg)
    total_pos, total_neg = float(pos.sum()), float(neg.sum())
    if total_pos <= 0 or total_neg <= 0:
        return None
    below = np.cumsum(neg) - neg
    return float((pos * (below + 0.5 * neg)).sum() / (total_pos * total_neg))


def weighted_brier(prob: np.ndarray, labels: np.ndarray, weights: np.ndarray) -> float | None:
    total = float(weights.sum())
    return float((weights * (prob - labels) ** 2).sum() / total) if total > 0 else None


class Bootstrap:
    """묶음 복원추출 — 회차마다 행의 뽑힌 횟수(묶음 단위)를 가중치에 곱한다. 같은 seed 면 같은
    묶음이 뽑히므로 모델 사이 짝 차이를 낼 수 있다."""

    def __init__(self, groups: np.ndarray, rounds: int, seed: int = 0):
        _, self.group_id = np.unique(np.asarray(groups).astype(str), return_inverse=True)
        self.size = int(self.group_id.max()) + 1 if self.group_id.size else 0
        rng = np.random.default_rng(seed)
        self.draws = [np.bincount(rng.integers(0, self.size, self.size), minlength=self.size)
                      [self.group_id] for _ in range(rounds)] if self.size else []

    def values(self, metric, mask: np.ndarray, weights: np.ndarray) -> np.ndarray:
        """metric(행 가중치) → 값 또는 None. 회차별 값 배열(None 은 NaN)."""
        out = np.full(len(self.draws), np.nan)
        for k, counts in enumerate(self.draws):
            value = metric(weights[mask] * counts[mask])
            if value is not None:
                out[k] = value
        return out


def _ci(values: np.ndarray) -> list:
    values = values[~np.isnan(values)]
    if values.size == 0:
        return [None, None]
    return [_round(np.percentile(values, 2.5)), _round(np.percentile(values, 97.5))]


def metric_block(prob: np.ndarray, y: np.ndarray, weights: np.ndarray, mask: np.ndarray,
                 boot: Bootstrap | None) -> dict:
    """부분집합 하나의 지표: 가중 AUC·Brier(주 값, 묶음 부트스트랩 CI)와 비가중(참고)."""
    labels = y[mask]
    scores = prob[mask]
    ones = np.ones(int(mask.sum()))
    out = {
        "n": int(mask.sum()), "유사": int((labels == 1).sum()), "비유사": int((labels == 0).sum()),
        "가중_합": _round(float(weights[mask].sum()), 1),
        "auc_가중": _round(weighted_auc(scores, labels, weights[mask])),
        "auc": _round(weighted_auc(scores, labels, ones)),
        "brier_가중": _round(weighted_brier(scores, labels, weights[mask])),
        "brier": _round(weighted_brier(scores, labels, ones)),
    }
    if boot is not None and out["auc_가중"] is not None:
        _, tie = np.unique(scores, return_inverse=True)
        pos, neg = (labels == 1).astype(float), (labels == 0).astype(float)
        out["auc_가중_ci95"] = _ci(boot.values(
            lambda w: _tie_auc(tie, w * pos, w * neg), mask, weights))
        out["brier_가중_ci95"] = _ci(boot.values(
            lambda w: weighted_brier(scores, labels, w), mask, weights))
    return out


def paired_difference(prob_new: np.ndarray, prob_old: np.ndarray, y: np.ndarray,
                      weights: np.ndarray, mask: np.ndarray, boot: Bootstrap) -> dict:
    """같은 묶음을 다시 뽑는 짝 차이(가중): AUC 는 새 − 옛, Brier 는 옛 − 새(둘 다 양수면 새 모델이
    낫다)."""
    labels = y[mask]
    pos, neg = (labels == 1).astype(float), (labels == 0).astype(float)
    out = {}
    base = weights[mask]
    for name, (a, b) in {"auc": (prob_new[mask], prob_old[mask])}.items():
        _, tie_a = np.unique(a, return_inverse=True)
        _, tie_b = np.unique(b, return_inverse=True)
        point_a, point_b = _tie_auc(tie_a, base * pos, base * neg), _tie_auc(tie_b, base * pos,
                                                                           base * neg)
        if point_a is None or point_b is None:
            out[name] = {"차이": None, "ci95": [None, None]}
            continue
        diff = (boot.values(lambda w: _tie_auc(tie_a, w * pos, w * neg), mask, weights)
                - boot.values(lambda w: _tie_auc(tie_b, w * pos, w * neg), mask, weights))
        out[name] = {"차이": _round(point_a - point_b), "ci95": _ci(diff)}
    brier_new = weighted_brier(prob_new[mask], labels, base)
    brier_old = weighted_brier(prob_old[mask], labels, base)
    if brier_new is None or brier_old is None:
        out["brier"] = {"차이": None, "ci95": [None, None]}
    else:
        diff = (boot.values(lambda w: weighted_brier(prob_old[mask], labels, w), mask, weights)
                - boot.values(lambda w: weighted_brier(prob_new[mask], labels, w), mask, weights))
        out["brier"] = {"차이": _round(brier_old - brier_new), "ci95": _ci(diff)}
    return out


def subset_masks(rows: list[dict]) -> dict[str, np.ndarray]:
    """평가 부분집합(심결 행) + 쉬운 음성을 섞은 집합."""
    trial = np.asarray([row["pair_source"] == "trial" for row in rows])
    source = np.asarray([row["pair_source"] for row in rows])
    rounds = np.asarray([row.get("회차", "") for row in rows])
    family = tr.families(rows)
    named = np.asarray([tr.has_name(row) for row in rows])
    return {
        "전체": trial, "1차": trial & (rounds == "1"), "2차": trial & (rounds == "2"),
        "문자계": trial & (family == "text"), "도형계": trial & (family == "figure"),
        "이름 있는 행": trial & named, "이름 없는 행": trial & ~named,
        "심결+cross": np.isin(source, ("trial", "cross")),
        "심결+cross+db": np.ones(len(rows), dtype=bool),
        "이름 있는 심결+cross+db": ~trial | named,
    }


# ---- 등급·단독 임계값(사건 가중) -----------------------------------------------------------------

def grade_thresholds_weighted(prob: np.ndarray, y: np.ndarray, weights: np.ndarray, *,
                              precision_risk: float = tr.PRECISION_RISK,
                              recall_review: float = tr.RECALL_REVIEW,
                              min_support: float = tr.RISK_MIN_SUPPORT) -> dict:
    """v1.3(tr.grade_thresholds)과 같은 규칙을 사건 가중으로: 위험 = 가중 정밀도 ≥ precision_risk 인
    최소 p(가중 지지 ≥ min_support), 검토 권장 = 가중 재현율 ≥ recall_review 인 최대 p, 주의 = 그
    절반. 미달이면 위험 하한은 검토 권장 하한과 1.0 의 중간."""
    notes = []
    candidates = np.unique(prob)
    positive = weights * (y == 1)
    total_pos = float(positive.sum())
    risk = None
    best = 0.0
    for threshold in candidates:
        above = prob >= threshold
        support = float(weights[above].sum())
        if support < min_support:
            break
        precision = float(positive[above].sum() / support)
        best = max(best, precision)
        if precision >= precision_risk:
            risk = float(threshold)
            break
    review = None
    for threshold in candidates[::-1]:
        if total_pos and float(positive[prob >= threshold].sum() / total_pos) >= recall_review:
            review = float(threshold)
            break
    if risk is None:
        notes.append(f"가중 정밀도 {precision_risk} 에 이르는 p 가 없음(가중 지지 {min_support} "
                     f"이상 최대 정밀도 {best:.2f}) — 위험 하한은 검토 권장 하한과 1.0 의 중간")
    if review is None:
        review = float(candidates[0]) if candidates.size else 0.5
        notes.append("재현율 조건을 만족하는 p 가 없어 최소 p 를 검토 권장 하한으로 둠")
    if risk is None:
        risk = (review + 1.0) / 2
    if review >= risk:
        notes.append(f"검토 권장 하한 {review:.3f} 이 위험 하한 {risk:.3f} 이상이라 위험 하한 바로 "
                     "아래로 내림")
        review = max(min(review, risk - 1e-6), 0.0)
    thresholds = tr._monotone({"주의": _round(review / 2), "검토 권장": _round(review),  # noqa: SLF001
                               "위험": _round(risk)})
    return {"thresholds": thresholds, "기준": notes,
            "등급별": grade_table(prob, y, weights, thresholds)}


def grade_table(prob: np.ndarray, y: np.ndarray, weights: np.ndarray, thresholds: dict,
                grades: np.ndarray | None = None) -> list[dict]:
    """등급별 행 수·유사 수와 가중 정밀도·재현율(이 등급 이상이 잡는 유사)."""
    if grades is None:
        grades = np.asarray([rm.grade_for(float(p), thresholds) for p in prob])
    positive = weights * (y == 1)
    total_pos = float(positive.sum())
    out = []
    for i, grade in enumerate(rm.GRADES):
        inside = grades == grade
        at_least = np.isin(grades, rm.GRADES[i:])
        support = float(weights[inside].sum())
        out.append({
            "등급": grade, "n": int(inside.sum()), "유사": int((y[inside] == 1).sum()),
            "가중_n": _round(support, 1),
            "정밀도_가중": _round(float(positive[inside].sum() / support)) if support else None,
            "정밀도": _round(float(y[inside].mean())) if inside.any() else None,
            "재현율_가중(이 등급 이상)": _round(float(positive[at_least].sum() / total_pos))
            if total_pos else None,
        })
    return out


def precision_threshold_weighted(scores: np.ndarray, labels: np.ndarray, weights: np.ndarray, *,
                                 target: float, min_support: float) -> dict:
    """가중 정밀도(점수 ≥ t 인 쌍 중 유사 비율) ≥ target 이 되는 최소 t(가중 지지 ≥ min_support)."""
    result = {"threshold": None, "precision": None, "recall": None, "n_above": 0,
              "가중_지지": None, "최대_정밀도": None}
    positive = weights * (labels == 1)
    total_pos = float(positive.sum())
    if scores.size == 0 or total_pos <= 0:
        return result
    best = None
    for threshold in np.unique(scores):
        above = scores >= threshold
        support = float(weights[above].sum())
        if support < min_support:
            break
        precision = float(positive[above].sum() / support)
        point = {"threshold": _round(float(threshold)), "precision": _round(precision),
                 "recall": _round(float(positive[above].sum() / total_pos)),
                 "n_above": int(above.sum()), "가중_지지": _round(support, 1)}
        if best is None or precision > best["precision"]:
            best = point
        if precision >= target and result["threshold"] is None:
            result.update(point)
    result["최대_정밀도"] = best
    return result


def standalone_weighted(rows: list[dict], y: np.ndarray, weights: np.ndarray,
                        mask: np.ndarray) -> dict:
    """축별 단독 임계값 τ(가중 정밀도 ≥ 0.7, 가중 지지 ≥ 10, 심결 최종 라벨) — 넘으면 등급 하한 검토
    권장. 없으면 null."""
    thresholds, reasons, table = {}, {}, []
    for axis in tr.AXES:
        scores = np.asarray([row.get(axis, np.nan) for row in rows], dtype=np.float64)
        valid = mask & ~np.isnan(scores)
        result = precision_threshold_weighted(scores[valid], y[valid], weights[valid],
                                              target=tr.STANDALONE_PRECISION,
                                              min_support=tr.MIN_SUPPORT)
        best = result.get("최대_정밀도") or {}
        active = result["threshold"] is not None
        thresholds[axis] = result["threshold"]
        mixed = None  # 같은 τ 를 쉬운 음성까지 섞은 집합에 적용했을 때의 가중 정밀도(참고)
        if active:
            above = ~np.isnan(scores) & (scores >= result["threshold"])
            support = float(weights[above].sum())
            mixed = _round(float((weights[above] * (y[above] == 1)).sum() / support)) \
                if support else None
        reasons[axis] = (
            f"τ {result['threshold']}: 가중 정밀도 {result['precision']} 재현율 {result['recall']} "
            f"(점수 ≥ τ 인 쌍 {result['n_above']}, 가중 지지 {result['가중_지지']})" if active else
            f"비활성 — 가중 지지 {tr.MIN_SUPPORT} 이상에서 최대 정밀도 {best.get('precision')} "
            f"(t ≥ {best.get('threshold')}, n {best.get('n_above')}) < {tr.STANDALONE_PRECISION}")
        table.append({"축": axis, "τ": result["threshold"], "정밀도_가중": result["precision"],
                      "재현율_가중": result["recall"], "n": result["n_above"],
                      "가중_지지": result["가중_지지"], "최대_정밀도": best.get("precision"),
                      "쉬운_음성_섞은_정밀도_가중": mixed, "활성": active})
    # 단독 규칙은 호칭·철자·관념 축만 다시 산출한다. 이미지 축은 도형 단독 규칙(τ 0.9)이 맡고 상품
    # 축은 v1.3 처럼 비활성 — 계산값은 표에 참고로 남긴다(심결 행의 유사 비율이 높아져 정밀도 0.7 이
    # 낮은 점수에서도 채워지므로 그대로 켜면 규칙이 대부분의 쌍에서 발동한다).
    for axis in tr.AXES:
        if axis not in STANDALONE_AXES and thresholds[axis] is not None:
            reasons[axis] = (f"비활성 유지(단독 규칙은 호칭·철자·관념만) — 참고 계산값 τ "
                             f"{thresholds[axis]}")
            thresholds[axis] = None
    for row in table:
        row["활성"] = row["활성"] and row["축"] in STANDALONE_AXES
    return {"thresholds": thresholds, "이유": reasons, "표": table,
            "목표_정밀도": tr.STANDALONE_PRECISION}


def name_floor_gap(design: Design, rows: list[dict], a: dict, name_floors: dict[str, float],
                   band: float = 0.1) -> dict:
    """이름 결합 제약이 데이터와 얼마나 어긋나는지: 이름 없는 집합의 학습 행(이름을 가린 전체)의
    유사 비율과, 그 가운데 이름이 하한 근처(호칭 x1_d 가 하한 ± band)인 행의 유사 비율(학습 가중).
    제약은 뒤쪽 확률이 앞쪽 이상이기를 요구한다."""
    x1 = np.asarray([row.get("x1_d", np.nan) for row in rows], dtype=np.float64)
    weight, y, easy = a["fit_weight"], a["y"], a["easy"]

    def share(mask: np.ndarray) -> dict:
        total = float(weight[mask].sum())
        return {"n": int(mask.sum()), "심결": int((mask & ~easy).sum()),
                "쉬운_음성": int((mask & easy).sum()),
                "유사_비율_가중": _round(float((weight[mask] * y[mask]).sum() / total), 3)
                if total else None}

    out = {}
    for key in design.nameless_keys:
        block = rm.NAMELESS_PREFIX + key
        hidden = design.mask[block]
        seen = design.mask[key]  # 이름까지 관측된 행
        floor = name_floors["x1_d"]
        out[block] = {
            "이름을_가린_전체": share(hidden),
            f"이름_하한_근처(x1_d {floor} ± {band})": share(seen & (np.abs(x1 - floor) <= band)),
            f"이름_하한_이하(x1_d ≤ {floor})": share(seen & (x1 <= floor)),
            "x1_d ≥ 0.8": share(seen & (x1 >= 0.8)),
        }
    return out


# ---- 판례 조건·부트스트랩·단조성 -----------------------------------------------------------------

def reference_fitted(design: Design, blocks: dict) -> tr.Fitted:
    coef, intercept = blocks[design.reference]
    return tr.Fitted("prior", design.names[design.reference], coef=coef, intercept=intercept)


def conditions(design: Design, blocks: dict, family: np.ndarray, mask: np.ndarray,
               distinct: np.ndarray) -> dict:
    """판례 4조건 — v1.3 과 같은 방식(기준 패턴 = 이름·이미지·상품을 모두 관측한 집합의 로짓 기울기,
    이름 있는 심결 행에서)."""
    return tr.condition_checks(reference_fitted(design, blocks), design.X[design.reference],
                               family, mask, distinct)


def bootstrap_fits(design: Design, y: np.ndarray, weight: np.ndarray, groups: np.ndarray,
                   easy: np.ndarray, constraints: list[Constraint], family: np.ndarray,
                   condition_mask: np.ndarray, distinct: np.ndarray, *, rounds: int,
                   seed: int, mode: str = "joint") -> dict:
    """심결 묶음 복원추출(쉬운 음성 고정) 재적합 — 블록별 계수 분포와 판례 조건 성립 비율."""
    rng = np.random.default_rng(seed)
    by_group: dict[str, list[int]] = {}
    for index in np.flatnonzero(~easy):
        by_group.setdefault(groups[index], []).append(index)
    keys = np.asarray(list(by_group))
    members = {key: np.asarray(value) for key, value in by_group.items()}
    easy_index = np.flatnonzero(easy)
    samples = {block: [] for block in design.ids}
    intercepts = {block: [] for block in design.ids}
    checks, failures = [], 0
    for _ in range(rounds):
        chosen = rng.choice(keys, keys.size, replace=True)
        index = np.concatenate([members[key] for key in chosen] + [easy_index])
        fit = fit_mode(design, y, weight, index, constraints, mode)
        failures += int(not fit.success)
        for block in design.ids:
            samples[block].append(fit.blocks[block][0])
            intercepts[block].append(fit.blocks[block][1])
        checks.append(conditions(design, fit.blocks, family, condition_mask, distinct))
    tables = {}
    for block in design.ids:
        matrix = np.asarray(samples[block])
        table = {name: {"평균": _round(matrix[:, i].mean()), "ci95": _ci(matrix[:, i])}
                 for i, name in enumerate(design.names[block])}
        b = np.asarray(intercepts[block])
        table["intercept"] = {"평균": _round(b.mean()), "ci95": _ci(b)}
        tables[block] = table
    return {"rounds": rounds, "수렴_실패": failures, "블록": tables,
            "판례_조건_성립_비율": tr.condition_rates(checks)}


def monotonicity(design: Design, blocks: dict, rows: list[dict], floors: dict[str, float],
                 name_floors: dict[str, float]) -> dict:
    """단조성 검사(학습 행, v1.3 과 같은 방식): 더 관측한 집합과 덜 관측한 집합의 로짓 차 — 더
    관측한 값이 하한 이상인 행에서 음수면 위반. 하한 미만인 행은 내려갈 수 있다(음의 증거)."""
    out = {}

    def report(label: str, upper: str, lower: str, index: np.ndarray, above: np.ndarray,
               floor) -> None:
        if index.size == 0:
            return
        delta = design.logit(blocks, upper, index) - design.logit(blocks, lower, index)
        out[label] = {
            "하한": floor, "n": int(index.size),
            "하한_이상": {
                "n": int(above.sum()),
                "위반(p 내려감)": int((delta[above] < -tr.COUPLING_TOLERANCE).sum()),
                "로짓차_평균": _round(delta[above].mean()) if above.any() else None,
                "로짓차_최소": _round(delta[above].min()) if above.any() else None,
            },
            "하한_미만": {"n": int((~above).sum()), "내려간_수": int((delta[~above] < 0).sum()),
                      "로짓차_평균": _round(delta[~above].mean()) if (~above).any() else None},
        }

    def axis_values(axis: str, index: np.ndarray) -> np.ndarray:
        return np.asarray([rows[i][axis] for i in index], dtype=np.float64)

    for key in design.named_keys:
        present = rm.pattern_present(key)
        for axis in present:
            lower = rm.pattern_key([a for a in present if a != axis], design.axes)
            index = np.flatnonzero(design.mask[key])
            report(f"{lower} → {key} ({axis})", key, lower, index,
                   axis_values(axis, index) >= floors[axis], floors[axis])
    for key in design.nameless_keys:
        block = rm.NAMELESS_PREFIX + key
        present = rm.pattern_present(key)
        for axis in present:
            lower_key = rm.pattern_key([a for a in present if a != axis], design.axes)
            if lower_key not in design.nameless_keys:
                continue
            index = np.flatnonzero(design.mask[block])
            report(f"{rm.NAMELESS_PREFIX}{lower_key} → {block} ({axis})", block,
                   rm.NAMELESS_PREFIX + lower_key, index,
                   axis_values(axis, index) >= floors[axis], floors[axis])
        index = np.flatnonzero(design.mask[key])  # 이름과 그 패턴 축이 모두 관측된 행
        above = (axis_values("x1_d", index) >= name_floors["x1_d"]) & (
            axis_values("x2_text_d", index) >= name_floors["x2_text_d"])
        report(f"{block} → {key} (이름)", key, block, index, above,
               {axis: name_floors[axis] for axis in rm.NAME_FLOOR_AXES})
    return out


def active_constraints(constraints: list[Constraint], theta: np.ndarray,
                       tolerance: float = 1e-6) -> dict:
    """경계에 붙은 제약(여유 < tolerance) — 종류별 수와 목록."""
    slack = np.asarray([float(c.row @ theta) for c in constraints])
    active = [(c, s) for c, s in zip(constraints, slack) if s < tolerance]
    by_kind: dict[str, int] = {}
    for c, _ in active:
        by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
    return {"제약_수": len(constraints), "경계_수": len(active), "종류별": by_kind,
            "목록": [{"종류": c.kind, "제약": c.label, "여유": _round(s, 9)} for c, s in active]}


# ---- 계수 반올림·JSON --------------------------------------------------------------------------

def rounded_model_blocks(design: Design, blocks: dict, floors: dict[str, float],
                         name_floors: dict[str, float], digits: int = 4) -> tuple[dict, dict]:
    """(이름 있는 패턴 계수 집합, 이름 없는 패턴 계수 집합) — 계수·절편을 반올림하고 반올림이 만든
    작은 위반을 고친다: 이름 있는 패턴 사이는 v1.3 처럼 상위 패턴 절편을 올리고, 이름 결합은 이름
    없는 패턴의 절편을 내리며, 이름 없는 패턴 사이는 하위 패턴(이미지만)의 절편을 내린다."""
    step = 10.0 ** -digits
    named, nameless = {}, {}
    for block in design.ids:
        coef, intercept = blocks[block]
        entry = {"features": list(design.names[block]),
                 "coefficients": {name: round(float(value), digits)
                                  for name, value in zip(design.names[block], coef)},
                 "intercept": round(float(intercept), digits)}
        for _ in range(20):
            violations = rm.monotone_violations(entry["coefficients"])
            if not violations:
                break
            for name in ("x2_whole×도형계", "x1_d×문자계", "x1_d×any_no_distinctive"):
                if name in entry["coefficients"] and any(name in v for v in violations):
                    entry["coefficients"][name] = round(entry["coefficients"][name] + step, digits)
            for axis in tr.AXES:
                if any(v.startswith(f"{axis} ") and "+" not in v for v in violations):
                    entry["coefficients"][axis] = 0.0
        if block.startswith(rm.NAMELESS_PREFIX):
            nameless[block[len(rm.NAMELESS_PREFIX):]] = entry
        else:
            named[block] = entry
    for key in design.named_keys:
        if key == rm.PATTERN_BASE_KEY:
            continue
        for _ in range(10_000):
            slack = tr.coupling_slack(named, design.axes, floors, key)
            if slack >= -tr.COUPLING_TOLERANCE:
                break
            named[key]["intercept"] = round(named[key]["intercept"] + max(step, -slack), digits)
    probe = {"patterns": named, rm.NAMELESS_KEY: nameless, "pattern_axes": list(design.axes),
             "coupling": {"floors": floors, "name_floors": name_floors}}
    for _ in range(10_000):
        violations = rm._nameless_coupling_violations(probe, tr.COUPLING_TOLERANCE)  # noqa: SLF001
        if not violations:
            break
        first = violations[0]
        lower_block = first.split(" → ")[0][len(rm.NAMELESS_PREFIX):]
        nameless[lower_block]["intercept"] = round(nameless[lower_block]["intercept"] - step,
                                                   digits)
    return named, nameless


def image_only_table(model_new: dict, model_old: dict) -> list[dict]:
    """이미지만 입력했을 때(도형계, 이름·상품 없음) 이미지 유사도별 위험도 — v1.3 대 v1.4."""
    out = []
    for level in ("도형", "결합-도형요부"):
        for value in IMAGE_ONLY_LEVELS:
            features = {"x1_d": None, "x2_text_d": None, "x3_d": None, "x4": None,
                        "x2_whole": value, "has_meaning_both": False,
                        "has_distinctive_part_a": True, "has_distinctive_part_b": True,
                        "mark_type": level}
            old, new = rm.risk_score(features, model_old), rm.risk_score(features, model_new)
            out.append({"유형": level, "x2_whole": value,
                        "v1.3": {"p": _round(old.prob), "등급": old.grade, "패턴": old.pattern},
                        "v1.4": {"p": _round(new.prob), "등급": new.grade, "패턴": new.pattern}})
    return out


# ---- 한 번의 학습·평가(주 실행·민감도 공용) ---------------------------------------------------

def arrays(rows: list[dict]) -> dict:
    y = tr.labels_for(rows, "최종").astype(np.float64)
    easy = np.asarray([row["pair_source"] != "trial" for row in rows])
    case_weight = np.asarray([row["_w"] for row in rows])
    return {
        "y": y, "easy": easy, "trial": ~easy,
        "eval_weight": case_weight,  # 평가 가중: 사건 가중(쉬운 음성 1)
        "fit_weight": case_weight * np.where(easy, W_EASY, 1.0),  # 학습 가중
        "groups": np.asarray([row["_group"] for row in rows]),
        "family": tr.families(rows),
        "named": np.asarray([tr.has_name(row) for row in rows]),
        "distinct": np.asarray([
            bool(int(row.get("has_distinctive_part_a") or 0))
            and bool(int(row.get("has_distinctive_part_b") or 0)) for row in rows]),
    }


def choose_nameless_keys(rows: list[dict], a: dict, min_minority: int) -> tuple[tuple, dict]:
    """이름 없는 패턴마다 소수 클래스(심결 + 쉬운 음성 행 수) ≥ min_minority 인지 — 미달인 패턴은
    만들지 않는다(그 입력은 런타임이 종전대로 이름 있는 패턴에 이름 항 0)."""
    flags = {axis: tr.observed(rows, axis) for axis in PATTERN_AXES}
    keep, detail = [], {}
    for key in NAMELESS_KEYS:
        mask = np.ones(len(rows), dtype=bool)
        for axis in rm.pattern_present(key):
            mask &= flags[axis]
        pos, neg = int((a["y"][mask] == 1).sum()), int((a["y"][mask] == 0).sum())
        ok = min(pos, neg) >= min_minority
        detail[rm.NAMELESS_PREFIX + key] = {"n": int(mask.sum()), "유사": pos, "비유사": neg,
                                            "가능": ok}
        if ok:
            keep.append(key)
    return tuple(keep), {"기준": f"패턴마다 소수 클래스 ≥ {min_minority}", "패턴": detail}


def train_once(rows: list[dict], *, structure: str = "v1.4", mode: str = "joint",
               folds: int = FOLDS, repeats: int = REPEATS, seed: int = 0,
               min_minority: int = tr.MIN_PATTERN_MINORITY, name_coupling: bool = True) -> dict:
    """설계 → 하한·제약 → 교차검증 OOF → 전체 적합. 평가에 쓸 재료를 사전으로 돌려준다.
    name_coupling=False 는 사후 진단용(이름 결합 제약 없이 — 단조성 보장이 없다)."""
    a = arrays(rows)
    nameless_keys, choice = choose_nameless_keys(rows, a, min_minority)
    with_name = a["named"] | a["easy"]
    pattern_axes, pattern_choice = tr.choose_pattern_axes(
        [row for row, keep in zip(rows, with_name) if keep], a["y"][with_name],
        min_minority=min_minority)
    if tuple(pattern_axes) != tuple(PATTERN_AXES):
        raise ValueError(f"이름 있는 패턴이 소수 클래스 기준을 못 채웁니다: {pattern_choice}")
    design = Design(rows, structure=structure, nameless_keys=nameless_keys)
    floors, name_floors, floor_detail = floors_for(rows, a["y"], a["easy"])
    constraints = build_constraints(design, floors, name_floors)
    if not name_coupling:
        constraints = [c for c in constraints if c.kind != "결합(이름)"]
    cv = cv_oof(design, a["y"], a["fit_weight"], a["groups"], constraints, folds=folds,
                repeats=repeats, seed=seed, mode=mode)
    started = time.perf_counter()
    final = fit_mode(design, a["y"], a["fit_weight"], np.arange(len(rows)), constraints, mode)
    return {"arrays": a, "design": design, "floors": floors, "name_floors": name_floors,
            "floor_detail": floor_detail, "constraints": constraints, "cv": cv, "final": final,
            "fit_seconds": time.perf_counter() - started,
            "nameless_choice": choice, "pattern_choice": pattern_choice}


def evaluate(rows: list[dict], prob: np.ndarray, a: dict, *, boot: Bootstrap | None) -> dict:
    masks = subset_masks(rows)
    return {name: metric_block(prob, a["y"], a["eval_weight"], mask, boot)
            for name, mask in masks.items() if mask.any()}


# ---- 평가 표 -----------------------------------------------------------------------------------

def grade_precision(prob: np.ndarray, grades: np.ndarray, y: np.ndarray, weights: np.ndarray,
                    mask: np.ndarray) -> dict:
    """위험 등급의 정밀도(가중·비가중)와 검토 권장 이상이 잡는 유사 비율."""
    risk = mask & (grades == "위험")
    review = mask & np.isin(grades, ("검토 권장", "위험"))
    positive = weights * (y == 1)
    support = float(weights[risk].sum())
    total_pos = float(positive[mask].sum())
    return {
        "n": int(mask.sum()), "위험_n": int(risk.sum()), "위험_유사": int((y[risk] == 1).sum()),
        "위험_정밀도_가중": _round(float(positive[risk].sum() / support)) if support else None,
        "위험_정밀도": _round(float(y[risk].mean())) if risk.any() else None,
        "위험_재현율_가중": _round(float(positive[risk].sum() / total_pos)) if total_pos else None,
        "검토_권장_이상_재현율_가중": _round(float(positive[review].sum() / total_pos))
        if total_pos else None,
    }


def v13_on_round2(features_path: Path, model: dict, *, rounds: int, seed: int) -> dict:
    """평가 1 — 기존 v1.3 을 2차 247행에 그대로(재학습·사진 규칙 없이, 처음 보는 데이터). 이름 없는
    행 포함/제외 둘 다."""
    raw = load_dataset(features_path, None, photo_rule=False)
    rows = [row for row in raw.rows + raw.excluded if row.get("회차") == "2"]
    y = tr.labels_for(rows, "최종").astype(np.float64)
    weights = np.asarray([row["_w"] for row in rows])
    groups = np.asarray([row["_group"] for row in rows])
    results = [rm.risk_score(service_features(row, image_column=RAW_IMAGE), model)
               for row in rows]
    prob = np.asarray([r.prob for r in results])
    grades = np.asarray([r.grade for r in results])
    named = np.asarray([tr.has_name(row) for row in rows])
    boot = Bootstrap(groups, rounds, seed)
    out = {}
    for label, mask in (("이름 없는 행 포함(247행 전체)", np.ones(len(rows), dtype=bool)),
                        ("이름 없는 행 제외", named), ("이름 없는 행만", ~named)):
        block = metric_block(prob, y, weights, mask, boot)
        block["등급"] = grade_precision(prob, grades, y, weights, mask)
        out[label] = block
    return out


def comparison_table(rows: list[dict], a: dict, probs: dict[str, np.ndarray], *,
                     boot: Bootstrap, new: str, old: str, refit: str | None = None) -> dict:
    """평가 2 — 부분집합 × 모델의 지표와 new − old 짝 차이(채택 기준 ①의 대상). refit 이 있으면
    new − refit 짝 차이도(같은 겹으로 다시 학습한 v1.3 구조 — 기존 v1.3 이 1차 행을 학습 때 본
    이점을 뺀 비교)."""
    masks = subset_masks(rows)
    out = {}
    for name, mask in masks.items():
        if not mask.any():
            continue
        entry = {label: metric_block(prob, a["y"], a["eval_weight"], mask, boot)
                 for label, prob in probs.items()}
        entry["짝_차이"] = paired_difference(probs[new], probs[old], a["y"], a["eval_weight"],
                                          mask, boot)
        if refit is not None:
            entry["짝_차이_구조_재학습_대비"] = paired_difference(
                probs[new], probs[refit], a["y"], a["eval_weight"], mask, boot)
        out[name] = entry
    return out


ADOPTION_AUC_SUBSETS = ("전체", "1차", "2차", "문자계", "도형계", "이름 없는 행", "심결+cross+db")
ADOPTION_BRIER_SUBSETS = ("전체", "심결+cross+db")


def adoption_check(table: dict, condition_final: dict, condition_rates: dict,
                   monotone: dict, runtime_violations: list[str]) -> dict:
    """미리 고정한 채택 기준(ADOPTION) 적용."""
    failed_metrics = []
    for subset in ADOPTION_AUC_SUBSETS:
        diff = (table.get(subset) or {}).get("짝_차이", {}).get("auc")
        if diff and diff["ci95"][1] is not None and diff["ci95"][1] < 0:
            failed_metrics.append({"지표": f"가중 AUC — {subset}", **diff})
    for subset in ADOPTION_BRIER_SUBSETS:
        diff = (table.get(subset) or {}).get("짝_차이", {}).get("brier")
        if diff and diff["ci95"][1] is not None and diff["ci95"][1] < 0:
            failed_metrics.append({"지표": f"가중 Brier(v1.3 − v1.4) — {subset}", **diff})
    worse_conditions = []
    for key, (held, rate) in V13_CONDITIONS.items():
        now_held, now_rate = condition_final.get(key), condition_rates.get(key)
        if held and now_held is False:
            worse_conditions.append({"조건": key, "사유": "최종 적합에서 성립 → 불성립"})
        elif now_rate is not None and now_rate < rate - CONDITION_DROP:
            worse_conditions.append({"조건": key, "사유": f"부트스트랩 성립 비율 {rate} → "
                                                       f"{now_rate}"})
    violations = sum(block["하한_이상"]["위반(p 내려감)"] for block in monotone.values())
    broken = violations > 0 or bool(runtime_violations)
    passed = not failed_metrics and not worse_conditions and not broken
    return {
        "기준": ADOPTION, "채택": passed,
        "판정": "v1.4 채택" if passed else "멈춤 — 채택 기준 미달(사람 결정)",
        "①_CI_상한_0_미만": failed_metrics, "②_나빠진_판례_조건": worse_conditions,
        "③_단조성": {"학습_행_위반": violations, "런타임_결합_검증_위반": runtime_violations[:5]},
    }


def coefficient_table(design: Design, blocks: dict, boot: dict | None, model_old: dict) -> dict:
    """평가 4 — 계수 표 v1.3 → v1.4(블록별; 부트스트랩 구간은 v1.4)."""
    out = {}
    for block in design.ids:
        coef, intercept = blocks[block]
        old = None
        if not block.startswith(rm.NAMELESS_PREFIX):
            old = (model_old.get("patterns") or {}).get(block)
        table = {"intercept": {"v1.3": old["intercept"] if old else None,
                               "v1.4": _round(intercept),
                               "ci95": boot["블록"][block]["intercept"]["ci95"] if boot else None}}
        for name, value in zip(design.names[block], coef):
            table[name] = {"v1.3": (old["coefficients"].get(name) if old else None),
                           "v1.4": _round(value),
                           "ci95": boot["블록"][block][name]["ci95"] if boot else None}
        out[block] = table
    return out


def sensitivity_row(label: str, rows: list[dict], summary: dict, probs13: np.ndarray, *,
                    folds: int, repeats: int, seed: int, mode: str = "joint",
                    min_minority: int = tr.MIN_PATTERN_MINORITY) -> dict:
    """평가 8 — 조건을 바꿔 다시 학습한 v1.4 의 OOF 지표(가중)와 주요 계수."""
    result = train_once(rows, folds=folds, repeats=repeats, seed=seed, mode=mode,
                        min_minority=min_minority)
    a = result["arrays"]
    metrics = evaluate(rows, result["cv"]["own"], a, boot=None)
    old = evaluate(rows, probs13, a, boot=None)
    design, blocks = result["design"], result["final"].blocks
    reference = dict(zip(design.names[design.reference], blocks[design.reference][0]))
    nameless = {}
    if design.nameless_keys:
        block = rm.NAMELESS_PREFIX + design.nameless_keys[0]
        nameless = dict(zip(design.names[block], blocks[block][0]))
    check = conditions(design, blocks, a["family"], a["trial"] & a["named"], a["distinct"])
    return {
        "조건": label, "심결_행": summary["심결_행(학습)"],
        "이름_없는_행": summary["이름_없는_행"]["n"],
        "제외": summary["이름도_이미지도_없어_제외"]["n"],
        "auc_가중": {name: block["auc_가중"] for name, block in metrics.items()},
        "brier_가중": {name: block["brier_가중"] for name, block in metrics.items()},
        "v1.3_그대로_auc_가중": {name: block["auc_가중"] for name, block in old.items()},
        "계수": {
            "기준 패턴 x1_d": _round(reference.get("x1_d")),
            "기준 패턴 x1_d×문자계": _round(reference.get("x1_d×문자계")),
            "기준 패턴 x2_whole": _round(reference.get("x2_whole")),
            "기준 패턴 x2_whole×도형계": _round(reference.get("x2_whole×도형계")),
            "기준 패턴 x3_d": _round(reference.get("x3_d")),
            "기준 패턴 x4": _round(reference.get("x4")),
            "이름 없음 x2_whole": _round(nameless.get("x2_whole")),
            "이름 없음 x2_whole×도형계": _round(nameless.get("x2_whole×도형계")),
        },
        "판례_조건(최종 적합)": {k: v for k, v in check.items() if k != "_기울기"},
        "수렴_실패": result["cv"]["수렴_실패"] + int(not result["final"].success),
    }


def diagnostic_row(label: str, note: str, rows: list[dict], probs13: np.ndarray,
                   boot: Bootstrap, *, folds: int, repeats: int, seed: int, **kwargs) -> dict:
    """사후 진단 — 명세와 다른 방식으로 적합한 변형의 OOF 지표·짝 차이·주요 계수(채택 판단 대상이
    아니다)."""
    result = train_once(rows, folds=folds, repeats=repeats, seed=seed, **kwargs)
    a = result["arrays"]
    design, blocks = result["design"], result["final"].blocks
    prob = result["cv"]["own"]
    table = comparison_table(rows, a, {"v1.3 그대로": probs13, label: prob}, boot=boot,
                             new=label, old="v1.3 그대로")
    monotone = monotonicity(design, blocks, rows, result["floors"], result["name_floors"])
    check = conditions(design, blocks, a["family"], a["trial"] & a["named"], a["distinct"])
    named_mix = a["named"] | a["easy"]
    return {
        "변형": label, "설명": note,
        "지표": {name: {"auc_가중": entry[label]["auc_가중"],
                       "brier_가중": entry[label]["brier_가중"],
                       "짝_차이_auc": entry["짝_차이"]["auc"],
                       "짝_차이_brier": entry["짝_차이"]["brier"]}
               for name, entry in table.items()},
        "이름_있는_심결+쉬운_음성_auc_가중": _round(weighted_auc(
            prob[named_mix], a["y"][named_mix], a["eval_weight"][named_mix])),
        "쉬운_음성_평균_p": _round(float(prob[a["easy"]].mean())),
        "계수": {block: {"절편": _round(blocks[block][1]),
                        **{name: _round(value)
                           for name, value in zip(design.names[block], blocks[block][0])}}
               for block in design.ids},
        "판례_조건(최종 적합)": {k: v for k, v in check.items() if k != "_기울기"},
        "단조성_위반(하한 이상 행)": {name: block["하한_이상"]["위반(p 내려감)"]
                              for name, block in monotone.items()},
        "수렴_실패": result["cv"]["수렴_실패"] + int(not result["final"].success),
    }


# ---- 실행 --------------------------------------------------------------------------------------

def build_model(result: dict, summary: dict, grades: dict, standalone: dict, blocks_meta: dict,
                evaluation: dict, adoption: dict, *, folds: int, repeats: int, bootstrap: int,
                metric_bootstrap: int, photo_rule: bool) -> dict:
    design, final = result["design"], result["final"]
    floors, name_floors = result["floors"], result["name_floors"]
    named, nameless = rounded_model_blocks(design, final.blocks, floors, name_floors)
    reference = named[design.reference]
    full_names = design.names[design.reference]

    def meta_of(block: str) -> dict:
        info = blocks_meta[block]
        return {k: info[k] for k in ("n", "n_심결", "n_쉬운_음성", "유사", "비유사", "가중_유사",
                                     "가중_비유사", "자기_패턴_행", "자기_패턴_심결")}

    model = {
        "version": MODEL_VERSION, "trained_at": date.today().isoformat(), "label": "최종",
        "method": "prior_monotone_logistic", "w_easy": W_EASY, "hyper": SIGMA,
        "removed_terms": tr.REMOVED_TERMS + [tr.MISS_OF[axis] for axis in design.axes]
        + ["miss_x3"],
        "prior": {"mu": {name: tr.PRIOR_MU[name] for name in full_names if name in tr.PRIOR_MU},
                  "sigma": SIGMA,
                  "applies_to": [name for name in full_names if name in tr.PRIOR_MU],
                  "intercept_prior": False},
        "monotone": {"features": [n for n in tr.MONOTONE_FEATURES if n in full_names],
                     "constraint": ("유사도 축 본체 ≥ 0; x2_whole 본체 + 도형계 교호작용 ≥ 0; "
                                    "x1 본체 + {문자계, 요부없음} 교호작용 모든 조합 ≥ 0 — "
                                    "계수 집합마다(이름 없는 집합 포함)")},
        "figure_rule": {"threshold": tr.FIGURE_X2_THRESHOLD, "caveat": tr.FIGURE_CAVEAT,
                        "validated": False,
                        "basis": ("97후3050 후단 — τ 0.9 유지(거의 같은 로고 탐지 성격). 심결 "
                                  "도형계 쌍에서 x2_whole ≥ 0.9 는 0건이라 데이터로 검증하지 못한 "
                                  "제품 규칙. 도형계 입력은 figure_caveat True")},
        "pattern_axes": list(design.axes),
        "pattern_rule": f"패턴마다 소수 클래스 ≥ {tr.MIN_PATTERN_MINORITY}",
        "reference_pattern": design.reference,
        "patterns": {key: {"requires": rm.pattern_present(key), **named[key],
                           "meta": meta_of(key)} for key in design.named_keys},
        "features": reference["features"], "coefficients": reference["coefficients"],
        "intercept": reference["intercept"],
        "coupling": {
            "floors": floors, "basis": tr.FLOOR_BASIS,
            "constraint": ("더 관측한 계수 집합(더 관측한 축 = 하한값)의 로짓 ≥ 덜 관측한 집합의 "
                           "로짓 — 설계 항 상자의 모든 꼭짓점. 축 하나(이미지·상품)를 더 관측하는 "
                           "것(이름 있는 집합 사이·이름 없는 집합 사이)과 이름을 더 관측하는 "
                           "것(이름 없는 집합 → 같은 키의 이름 있는 집합). 학습은 선형 제약, "
                           "런타임은 적재 때 검증"),
        },
        "grade_thresholds": grades["thresholds"],
        "grade_basis": (f"심결+cross+db OOF 확률(행마다 자기 계수 집합), 사건 가중 — 위험: 가중 "
                        f"정밀도 ≥ {tr.PRECISION_RISK}·가중 지지 ≥ {tr.RISK_MIN_SUPPORT}, 검토 "
                        f"권장: 가중 재현율 ≥ {tr.RECALL_REVIEW}, 주의: 그 절반; 미달이면 위험 "
                        "하한은 검토 권장 하한과 1.0 의 중간"),
        "standalone_thresholds": standalone["thresholds"],
        "standalone_precision": tr.STANDALONE_PRECISION,
        "standalone_reason": standalone["이유"],
        "meta": {
            "n_trial": summary["심결_행(학습)"], "n_pos": summary["유사"],
            "n_neg": summary["비유사"], "n_named": summary["이름_있는_행"],
            "n_nameless": summary["이름_없는_행"]["n"],
            "n_excluded_no_name_no_image": summary["이름도_이미지도_없어_제외"]["n"],
            "n_easy": sum(summary["쉬운_음성"].values()),
            "rounds": summary["회차"],
            "case_weight": {**summary["사건_가중"], "rule": "w = min(1, 3 / 그 사건의 행 수)"},
            "photo": {**summary["사진_규칙"],
                      "rule": ("사진A·사진B(src.photo_mark, CLIP 임베딩 방향 판정) 가운데 하나라도 "
                               "1 이면 이미지 축을 관측 없음으로"),
                      "direction": "shared/model/photo_direction_v1.json"},
            "groups": "심판번호 + 같은 쌍키를 가진 사건은 한 묶음(교차검증·부트스트랩)",
            "folds": folds, "repeats": repeats, "bootstrap": bootstrap,
            "metric_bootstrap": metric_bootstrap,
            "sigma_selection": "fixed", "risk_min_support": tr.RISK_MIN_SUPPORT,
            "grade_precision": next((row["정밀도_가중"] for row in grades["등급별"]
                                     if row["등급"] == "위험"), None),
            "grade_precision_unweighted": next((row["정밀도"] for row in grades["등급별"]
                                                if row["등급"] == "위험"), None),
            "cv_auc_weighted": {name: block["auc_가중"] for name, block in evaluation.items()},
            "cv_auc_weighted_ci95": {name: block.get("auc_가중_ci95")
                                     for name, block in evaluation.items()},
            "cv_brier_weighted": {name: block["brier_가중"]
                                  for name, block in evaluation.items()},
            "nameless_choice": result["nameless_choice"],
            "pattern_choice": result["pattern_choice"],
            "coupling_floors": result["floor_detail"],
            "optimizer": {"solver": final.solver, "kkt_residual": final.kkt_residual,
                          "min_slack": final.min_slack},
            "adoption": {"채택": adoption["채택"], "판정": adoption["판정"]},
            "feature_definitions": (
                "축 점수 0~1. 이름 있는 입력은 결측 패턴(이미지 × 상품)마다 계수 집합, 이름 "
                "없는 입력(x1_d·x2_text_d 둘 다 결측)은 nameless_patterns 의 집합(이미지·상품 "
                "항뿐). 관측된 축만 입력이고 결측 지시변수는 없다(x3_d 는 게이트가 꺼지면 값 0). "
                "any_no_distinctive = 1 − has_distinctive_part_a·b, 교호작용 x1_d×문자계·"
                "x2_whole×도형계·x1_d×any_no_distinctive. 표준화 없음. 기여도 miss_pattern = "
                "쓰인 집합의 절편 − 기준 절편."
            ),
        },
    }
    if design.nameless_keys:  # 이름 없는 패턴이 없으면(폴백 구조) 키를 두지 않는다 — v1.3 꼴
        model[rm.NAMELESS_KEY] = {
            key: {"requires": rm.pattern_present(key), **nameless[key],
                  "meta": meta_of(rm.NAMELESS_PREFIX + key)} for key in design.nameless_keys}
        model["coupling"].update({"name_floors": name_floors, "name_basis": NAME_FLOOR_BASIS})
    model["meta"]["structure"] = ("이름 없는 패턴 " + "·".join(design.nameless_keys)
                                  if design.nameless_keys else "이름 있는 행만(v1.3 구조)")
    rm.validate_model(model)
    return model


def run(features_path: Path, easy_path: Path, *, out_dir: Path, model_path: Path,
        v13_path: Path = DEFAULT_V13, structure: str = "v1.4", mode: str = "joint",
        folds: int = FOLDS,
        repeats: int = REPEATS, bootstrap: int = BOOTSTRAP,
        metric_bootstrap: int = METRIC_BOOTSTRAP, seed: int = 0, photo_rule: bool = True,
        sensitivity: bool = True, diagnostics: bool = True, force_model: bool = False,
        min_pattern_minority: int = tr.MIN_PATTERN_MINORITY) -> dict:
    model_old = rm.validate_model(json.loads(Path(v13_path).read_text(encoding="utf-8")))
    dataset = load_dataset(features_path, easy_path, photo_rule=photo_rule)
    rows, summary = dataset.rows, dataset.summary
    common = {"folds": folds, "repeats": repeats, "seed": seed,
              "min_minority": min_pattern_minority}
    result = train_once(rows, structure=structure, mode=mode, **common)
    a, design, final = result["arrays"], result["design"], result["final"]
    blocks_meta = block_counts(design, a["y"], a["fit_weight"], a["easy"])
    prob_new = result["cv"]["own"]
    prob_old = v13_probabilities(rows, model_old)
    boot = Bootstrap(a["groups"], metric_bootstrap, seed)
    probs = {"v1.3 그대로": prob_old, "v1.4": prob_new}
    reference_structure = None
    if structure == "v1.4":
        reference_structure = train_once(rows, structure="v1.3", **common)
        probs["v1.3 구조 재학습"] = reference_structure["cv"]["own"]
    table = comparison_table(rows, a, probs, boot=boot, new="v1.4", old="v1.3 그대로",
                             refit="v1.3 구조 재학습" if reference_structure else None)
    evaluation = {name: entry["v1.4"] for name, entry in table.items()}
    easy_mean = {label: _round(float(prob[a["easy"]].mean())) for label, prob in probs.items()}
    mixed = subset_masks(rows)["심결+cross+db"]
    grades = grade_thresholds_weighted(prob_new[mixed], a["y"][mixed], a["eval_weight"][mixed])
    trial_grades = grade_table(prob_new[a["trial"]], a["y"][a["trial"]],
                               a["eval_weight"][a["trial"]], grades["thresholds"])
    old_grades = np.asarray([rm.grade_for(float(p), model_old["grade_thresholds"])
                             for p in prob_old])
    grade_compare = {
        "v1.3 그대로(자기 하한 " + json.dumps(model_old["grade_thresholds"], ensure_ascii=False)
        + ")": {"심결+cross+db": grade_table(prob_old, a["y"], a["eval_weight"],
                                           model_old["grade_thresholds"], old_grades),
                "심결": grade_table(prob_old[a["trial"]], a["y"][a["trial"]],
                                  a["eval_weight"][a["trial"]], model_old["grade_thresholds"],
                                  old_grades[a["trial"]])},
        "v1.4": {"심결+cross+db": grades["등급별"], "심결": trial_grades},
    }
    standalone = standalone_weighted(rows, a["y"], a["eval_weight"], a["trial"])
    condition_mask = a["trial"] & a["named"]
    final_check = conditions(design, final.blocks, a["family"], condition_mask, a["distinct"])
    boot_fits = bootstrap_fits(design, a["y"], a["fit_weight"], a["groups"], a["easy"],
                               result["constraints"], a["family"], condition_mask,
                               a["distinct"], rounds=bootstrap, seed=seed,
                               mode=mode) if bootstrap else None
    monotone = monotonicity(design, final.blocks, rows, result["floors"], result["name_floors"])
    active = active_constraints(result["constraints"], final.theta)
    condition_rates = boot_fits["판례_조건_성립_비율"] if boot_fits else {}
    provisional = {"채택": False, "판정": "계산 중"}
    model = build_model(result, summary, grades, standalone, blocks_meta, evaluation,
                        provisional, folds=folds, repeats=repeats, bootstrap=bootstrap,
                        metric_bootstrap=metric_bootstrap, photo_rule=photo_rule)
    runtime_violations = rm.coupling_violations(model)
    adoption = adoption_check(table, {k: v for k, v in final_check.items() if k != "_기울기"},
                              condition_rates, monotone, runtime_violations)
    stable = final.success and result["cv"]["수렴_실패"] == 0
    adoption["안정성"] = {
        "최종_적합_KKT_잔차": final.kkt_residual, "최종_적합_최소_여유": final.min_slack,
        "교차검증_수렴_실패": result["cv"]["수렴_실패"], "교차검증_겹": result["cv"]["겹_수"],
        "부트스트랩_수렴_실패": boot_fits["수렴_실패"] if boot_fits else None, "안정": stable,
    }
    model["meta"]["adoption"] = {"채택": adoption["채택"], "판정": adoption["판정"]}
    model["meta"]["fit_mode"] = mode
    adoption["원인_진단"] = name_floor_gap(design, rows, a, result["name_floors"])
    results = {
        "기준일": date.today().isoformat(), "구조": structure, "적합_방식": mode,
        "쉬운_음성_평균_p": easy_mean, "데이터": summary,
        "계수_집합": blocks_meta, "결합_하한": result["floor_detail"],
        "이름_없는_패턴_결정": result["nameless_choice"],
        "평가_1_v1.3을_2차에_그대로": v13_on_round2(features_path, model_old,
                                              rounds=metric_bootstrap, seed=seed),
        "평가_2_OOF": table,
        "평가_3_판례_조건": {
            "v1.3(설계 §7-3)": {key: {"최종_적합": held, "부트스트랩_성립_비율": rate}
                              for key, (held, rate) in V13_CONDITIONS.items()},
            "v1.4": {key: {"최종_적합": final_check[key],
                           "부트스트랩_성립_비율": condition_rates.get(key)}
                     for key in tr.CONDITIONS},
            "v1.4_로짓_기울기(기준 패턴)": {k: _round(v) for k, v in
                                      final_check["_기울기"].items()},
        },
        "평가_4_계수": coefficient_table(design, final.blocks, boot_fits, model_old),
        "제약": active,
        "평가_5_등급": {"v1.4_하한": grades["thresholds"], "기준": grades["기준"],
                     "v1.3_하한": model_old["grade_thresholds"], "등급별": grade_compare,
                     "v1.3_grade_precision(JSON)": model_old["meta"].get("grade_precision")},
        "평가_5_단독_임계값": {"v1.3": model_old["standalone_thresholds"], "v1.4": standalone,
                         "도형_단독_규칙_τ": tr.FIGURE_X2_THRESHOLD},
        "평가_6_이미지만": image_only_table(model, model_old),
        "평가_7_단조성": monotone,
        "채택": adoption,
    }
    if sensitivity and structure == "v1.4":
        variants = (
            (f"사건 {BIG_CASE} 제외", {"drop_cases": (BIG_CASE,)}),
            ("사진 규칙 없음", {"photo_rule": False}),
            ("2등급에서 살아난 행 제외", {"drop_augmented": True}),
        )
        base_row = sensitivity_row("주 실행", rows, summary, prob_old, mode=mode, **common)
        out_rows = [base_row]
        for label, kwargs in variants:
            options = {"photo_rule": photo_rule, **kwargs}
            variant = load_dataset(features_path, easy_path, **options)
            out_rows.append(sensitivity_row(
                label, variant.rows, variant.summary,
                v13_probabilities(variant.rows, model_old), mode=mode, **common))
        results["평가_8_민감도"] = out_rows
    if diagnostics and structure == "v1.4":
        other = "sequential" if mode == "joint" else "joint"
        other_label = {"sequential": "순차 적합", "joint": "한 번에 적합(명세)"}[other]
        other_note = {
            "sequential": ("이름 있는 패턴 네 벌을 먼저 적합해 고정하고 이름 없는 패턴 두 벌만 "
                           "같은 제약 아래 적합(단조성 보장은 그대로)"),
            "joint": "여섯 계수 집합을 한 번에 적합(명세의 방식)",
        }[other]
        results["사후_진단"] = [
            diagnostic_row(other_label, other_note, rows, prob_old, boot, mode=other,
                           **common),
            diagnostic_row("이름 결합 제약 없음", "이름 없는 패턴을 이름 결합 제약 없이 적합 — "
                           "이름을 더 관측하면 위험도가 내려갈 수 있다(단조성 보장 없음)", rows,
                           prob_old, boot, name_coupling=False, **common),
            diagnostic_row("v1.3 구조 재학습", "이름 있는 행만(이름 없는 행은 런타임처럼 이름 항 "
                           "0) — 폴백 구조", rows, prob_old, boot, structure="v1.3", **common),
        ]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = Path(model_path)
    written = model_path if (adoption["채택"] or force_model) else (
        out_dir / f"{REPORT_STEM}_candidate.json")
    written.parent.mkdir(parents=True, exist_ok=True)
    written.write_text(json.dumps(model, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    results["모델_파일"] = str(written)
    results["모델_파일_설명"] = ("채택 — 배포 경로" if written == model_path else
                            "채택 기준 미달 — 후보로만 저장(배포 경로에는 쓰지 않음)")
    (out_dir / f"{REPORT_STEM}_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / f"{REPORT_STEM}_report.md").write_text(report_text(results), encoding="utf-8")
    return results


# ---- 보고서 ------------------------------------------------------------------------------------

def _f(value, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _ci_text(ci) -> str:
    if not ci or ci[0] is None:
        return ""
    return f" ({ci[0]:.2f}~{ci[1]:.2f})"


def _diff_text(diff: dict | None) -> str:
    if not diff or diff.get("차이") is None:
        return "—"
    low, high = diff["ci95"]
    return f"{diff['차이']:+.3f} ({low:+.3f}~{high:+.3f})"


def report_text(results: dict) -> str:
    data = results["데이터"]
    lines = [f"# 통합 모델 v1.4 학습 보고 ({results['기준일']})", ""]
    excluded = data["이름도_이미지도_없어_제외"]
    photo = data["사진_규칙"]
    weight = data["사건_가중"]
    lines += [
        f"- 심결 {data['심결_행(특징 파일)']}행 중 학습 {data['심결_행(학습)']}행(유사 "
        f"{data['유사']}·비유사 {data['비유사']}; 1차 {data['회차']['1']}·2차 "
        f"{data['회차']['2']}) — "
        f"이름 있는 행 {data['이름_있는_행']}, 이름 없는 행 {data['이름_없는_행']['n']}"
        f"(유사 {data['이름_없는_행']['유사']}·비유사 {data['이름_없는_행']['비유사']}), 이름도 "
        f"이미지도 없어 제외 {excluded['n']}행(유사 {excluded['유사']}·비유사 "
        f"{excluded['비유사']}; "
        f"그중 사진 규칙으로 이미지를 잃은 행 {excluded['사진_규칙으로_이미지를_잃은_행']})",
        f"- 쉬운 음성 cross {data['쉬운_음성']['cross']}·db {data['쉬운_음성']['db']}(학습 가중 "
        f"{data['w_easy']})",
        f"- 사건 가중 상한 {weight['상한']}: 사건 {weight['사건']}·묶음 {weight['묶음']}, 가중 1 "
        f"미만 {weight['1_미만_행']}행, 심결 가중 합 {weight['가중_합']}",
        f"- 사진 규칙({'적용' if photo['적용'] else '미적용'}): 이미지 있는 쌍 "
        f"{photo['이미지_있는_쌍']} 중 사진 낀 쌍 {photo['사진_낀_쌍']}",
        "- 결합 하한: " + ", ".join(f"{axis} {d['하한']}" for axis, d in
                                 results["결합_하한"].items()),
        "",
        "## 계수 집합(블록)", "",
        "| 집합 | 입력 | n(심결·쉬운 음성) | 유사/비유사 | 가중 유사/비유사 | 자기 패턴 행(심결) |",
        "|---|---|---|---|---|---|",
    ]
    for block, info in results["계수_집합"].items():
        lines.append(f"| {block} | {'·'.join(info['입력'])} | {info['n']}({info['n_심결']}·"
                     f"{info['n_쉬운_음성']}) | {info['유사']}/{info['비유사']} | "
                     f"{info['가중_유사']}/{info['가중_비유사']} | {info['자기_패턴_행']}"
                     f"({info['자기_패턴_심결']}) |")
    adoption = results["채택"]
    lines += ["", f"## 채택 판단 — {adoption['판정']}", ""]
    for key in ("①", "②", "③"):
        lines.append(f"- 기준 {key}: {adoption['기준'][key]}")
    lines.append("- ① CI 상한 < 0 인 지표: " + (
        "; ".join(f"{m['지표']} {_diff_text(m)}" for m in adoption["①_CI_상한_0_미만"])
        or "없음"))
    lines.append("- ② 나빠진 판례 조건: " + (
        "; ".join(f"{c['조건']} — {c['사유']}" for c in adoption["②_나빠진_판례_조건"]) or "없음"))
    lines.append(f"- ③ 단조성: 학습 행 위반 {adoption['③_단조성']['학습_행_위반']}, 런타임 결합 "
                 f"검증 위반 {len(adoption['③_단조성']['런타임_결합_검증_위반'])}")
    for block, gap in (adoption.get("원인_진단") or {}).items():
        lines.append(f"- 이름 결합 제약과 데이터({block}): " + "; ".join(
            f"{label} 유사 비율 {info['유사_비율_가중']}(n {info['n']} = 심결 {info['심결']}·쉬운 "
            f"음성 {info['쉬운_음성']})" for label, info in gap.items()))
    stability = adoption["안정성"]
    lines.append(f"- 적합 안정성: 최종 적합 KKT 잔차 {stability['최종_적합_KKT_잔차']:.1e}, "
                 f"교차검증 수렴 실패 {stability['교차검증_수렴_실패']}/"
                 f"{stability['교차검증_겹']}, "
                 f"부트스트랩 수렴 실패 {stability['부트스트랩_수렴_실패']}")
    lines.append(f"- 모델 파일: {results['모델_파일']} — {results['모델_파일_설명']}")
    lines += ["", "## 평가 1 — 기존 v1.3 을 2차 행에 그대로(재학습·사진 규칙 없이)", "",
              "| 범위 | n(유사/비유사) | 가중 AUC | AUC(참고) | 위험 등급 n(유사) | 위험 정밀도 "
              "가중(비가중) | 검토 권장 이상 재현율 |", "|---|---|---|---|---|---|---|"]
    for label, block in results["평가_1_v1.3을_2차에_그대로"].items():
        grade = block["등급"]
        lines.append(
            f"| {label} | {block['n']}({block['유사']}/{block['비유사']}) | "
            f"{_f(block['auc_가중'])}{_ci_text(block.get('auc_가중_ci95'))} | {_f(block['auc'])} | "
            f"{grade['위험_n']}({grade['위험_유사']}) | {_f(grade['위험_정밀도_가중'])}"
            f"({_f(grade['위험_정밀도'])}) | {_f(grade['검토_권장_이상_재현율_가중'])} |")
    table = results["평가_2_OOF"]
    labels = [label for label in next(iter(table.values())) if not label.startswith("짝_차이")]
    lines += ["", "## 평가 2 — OOF 지표(사건 가중이 주 값, 괄호는 95% CI; 비가중은 참고)", "",
              "| 부분 | n(유사/비유사) | " + " | ".join(f"{label} 가중 AUC" for label in labels)
              + " | 짝 차이 AUC(v1.4 − v1.3 그대로) | " + " | ".join(
                  f"{label} 가중 Brier" for label in labels)
              + " | 짝 차이 Brier(v1.3 − v1.4) |",
              "|---|---|" + "---|" * (2 * len(labels) + 2)]
    for name, entry in table.items():
        first = entry[labels[0]]
        lines.append(
            f"| {name} | {first['n']}({first['유사']}/{first['비유사']}) | "
            + " | ".join(f"{_f(entry[label]['auc_가중'])}"
                         f"{_ci_text(entry[label].get('auc_가중_ci95'))}" for label in labels)
            + f" | {_diff_text(entry['짝_차이']['auc'])} | "
            + " | ".join(_f(entry[label]["brier_가중"]) for label in labels)
            + f" | {_diff_text(entry['짝_차이']['brier'])} |")
    if any("짝_차이_구조_재학습_대비" in entry for entry in table.values()):
        lines += ["", "짝 차이 AUC(v1.4 − v1.3 구조 재학습, 같은 겹 OOF — 기존 v1.3 이 1차 행을 "
                  "학습 때 본 이점을 뺀 비교): " + "; ".join(
                      f"{name} {_diff_text(entry['짝_차이_구조_재학습_대비']['auc'])}"
                      for name, entry in table.items() if "짝_차이_구조_재학습_대비" in entry)]
    lines += ["", f"쉬운 음성 쌍의 평균 p: {results.get('쉬운_음성_평균_p')}"]
    lines += ["", "비가중 AUC(참고): " + "; ".join(
        f"{name} " + "/".join(_f(entry[label]["auc"]) for label in labels)
        for name, entry in table.items()) + f" — 순서 {'/'.join(labels)}"]
    conditions_block = results["평가_3_판례_조건"]
    lines += ["", "## 평가 3 — 판례 4조건(기준 패턴의 로짓 기울기, 이름 있는 심결 행)", "",
              "| 조건 | v1.3 최종 적합 · 부트스트랩 | v1.4 최종 적합 · 부트스트랩 |",
              "|---|---|---|"]
    for key in tr.CONDITIONS:
        old, new = conditions_block["v1.3(설계 §7-3)"][key], conditions_block["v1.4"][key]
        lines.append(f"| {key} | {'성립' if old['최종_적합'] else '불성립'} · "
                     f"{_f(old['부트스트랩_성립_비율'], 2)} | "
                     f"{'성립' if new['최종_적합'] else '불성립'} · "
                     f"{_f(new['부트스트랩_성립_비율'], 2)} |")
    lines.append("")
    lines.append(f"v1.4 로짓 기울기(기준 패턴): {conditions_block['v1.4_로짓_기울기(기준 패턴)']}")
    lines += ["", "## 평가 4 — 계수 v1.3 → v1.4(부트스트랩 95% 구간은 v1.4)", ""]
    for block, terms in results["평가_4_계수"].items():
        lines += [f"### {block}", "", "| 항 | v1.3 | v1.4 | 95% 구간 |", "|---|---|---|---|"]
        for name, item in terms.items():
            ci = item["ci95"]
            lines.append(f"| {name} | {_f(item['v1.3'], 4)} | {_f(item['v1.4'], 4)} | "
                         + (f"{ci[0]} ~ {ci[1]}" if ci and ci[0] is not None else "—") + " |")
        lines.append("")
    active = results["제약"]
    lines += [f"경계에 붙은 제약: {active['경계_수']}/{active['제약_수']} — 종류별 "
              f"{active['종류별']}", ""]
    for item in active["목록"]:
        if item["종류"] in ("단조", "결합(이름)", "결합(이름 없음, 축)"):
            lines.append(f"- {item['종류']}: {item['제약']}")
    grade = results["평가_5_등급"]
    lines += ["", "## 평가 5 — 등급 하한·위험 등급 정밀도·단독 임계값(사건 가중)", "",
              f"- v1.3 하한 {grade['v1.3_하한']} → v1.4 하한 {grade['v1.4_하한']}"]
    for note in grade["기준"]:
        lines.append(f"- {note}")
    for model_label, sets in grade["등급별"].items():
        for set_name, rows_ in sets.items():
            lines += ["", f"### {model_label} — {set_name}", "",
                      "| 등급 | n(유사) | 가중 n | 정밀도 가중(비가중) | 재현율 가중(이 등급 "
                      "이상) |",
                      "|---|---|---|---|---|"]
            for row in rows_:
                lines.append(f"| {row['등급']} | {row['n']}({row['유사']}) | {row['가중_n']} | "
                             f"{_f(row['정밀도_가중'])}({_f(row['정밀도'])}) | "
                             f"{_f(row['재현율_가중(이 등급 이상)'])} |")
    standalone = results["평가_5_단독_임계값"]
    lines += ["", "| 축 | v1.3 τ | v1.4 τ(사건 가중) | 가중 정밀도 | 가중 재현율 | n(가중 지지) | "
              "쉬운 음성 섞은 정밀도(참고) | 최대 정밀도 |",
              "|---|---|---|---|---|---|---|---|"]
    for row in standalone["v1.4"]["표"]:
        tau = f"{row['τ']}" if row["활성"] else f"비활성(참고 계산값 {row['τ']})"
        lines.append(f"| {row['축']} | {standalone['v1.3'].get(row['축'])} | {tau} | "
                     f"{row['정밀도_가중']} | {row['재현율_가중']} | {row['n']}"
                     f"({row['가중_지지']}) | {row['쉬운_음성_섞은_정밀도_가중']} | "
                     f"{row['최대_정밀도']} |")
    lines.append(f"\n단독 임계값은 호칭·철자·관념만 다시 산출(이미지·상품 축은 v1.3 처럼 비활성). "
                 f"도형 단독 규칙 τ {standalone['도형_단독_규칙_τ']} 유지.")
    lines += ["", "## 평가 6 — 이미지만 입력했을 때(도형계, 이름·상품 없음)", "",
              "| 유형 | 이미지 유사도 | v1.3 p(등급·패턴) | v1.4 p(등급·패턴) |",
              "|---|---|---|---|"]
    for row in results["평가_6_이미지만"]:
        lines.append(f"| {row['유형']} | {row['x2_whole']} | {row['v1.3']['p']}"
                     f"({row['v1.3']['등급']}·{row['v1.3']['패턴']}) | {row['v1.4']['p']}"
                     f"({row['v1.4']['등급']}·{row['v1.4']['패턴']}) |")
    lines += ["", "## 평가 7 — 단조성 검사(학습 행, 더 관측한 집합 − 덜 관측한 집합의 로짓 차)", "",
              "| 결합 | 하한 | 하한 이상 n / 위반 / 평균·최소 | 하한 미만 n / 내려간 수 / 평균 |",
              "|---|---|---|---|"]
    for name, block in results["평가_7_단조성"].items():
        above, below = block["하한_이상"], block["하한_미만"]
        lines.append(f"| {name} | {block['하한']} | {above['n']} / {above['위반(p 내려감)']} / "
                     f"{above['로짓차_평균']}·{above['로짓차_최소']} | {below['n']} / "
                     f"{below['내려간_수']} / {below['로짓차_평균']} |")
    if "평가_8_민감도" in results:
        rows_ = results["평가_8_민감도"]
        subsets = [name for name in ("전체", "1차", "2차", "문자계", "도형계", "이름 없는 행",
                                     "심결+cross+db") if name in rows_[0]["auc_가중"]]
        lines += ["", "## 평가 8 — 민감도(조건을 바꿔 다시 학습, 가중 AUC OOF)", "",
                  "| 조건 | 심결 행(이름 없는·제외) | " + " | ".join(subsets)
                  + " | 가중 Brier 전체/섞음 | 기준 패턴 x1·×문자계 / x2_whole·×도형계 / x3 / x4 "
                  "| 이름 없음 x2_whole·×도형계 | 판례 (i)~(iv) |",
                  "|---|---|" + "---|" * (len(subsets) + 4)]
        for row in rows_:
            c = row["계수"]
            checks = "/".join("성립" if row["판례_조건(최종 적합)"][k] else "불성립"
                              for k in tr.CONDITIONS)
            lines.append(
                f"| {row['조건']} | {row['심결_행']}({row['이름_없는_행']}·{row['제외']}) | "
                + " | ".join(_f(row["auc_가중"].get(name)) for name in subsets)
                + f" | {_f(row['brier_가중'].get('전체'))}/"
                  f"{_f(row['brier_가중'].get('심결+cross+db'))} | "
                  f"{c['기준 패턴 x1_d']}·{c['기준 패턴 x1_d×문자계']} / "
                  f"{c['기준 패턴 x2_whole']}·{c['기준 패턴 x2_whole×도형계']} / "
                  f"{c['기준 패턴 x3_d']} / {c['기준 패턴 x4']} | {c['이름 없음 x2_whole']}·"
                  f"{c['이름 없음 x2_whole×도형계']} | {checks} |")
    if "사후_진단" in results:
        lines += ["", "## 사후 진단 — 명세와 다른 방식의 변형(채택 판단 대상 아님)", ""]
        subsets = ("전체", "1차", "2차", "문자계", "도형계", "이름 있는 행", "이름 없는 행",
                   "심결+cross+db")
        lines += ["| 변형 | " + " | ".join(subsets) + " | 이름 있는 심결+쉬운 음성 | 쉬운 음성 "
                  "평균 p | 단조성 위반 | 판례 (i)~(iv) |",
                  "|---|" + "---|" * (len(subsets) + 4)]
        for row in results["사후_진단"]:
            checks = "/".join("성립" if row["판례_조건(최종 적합)"][k] else "불성립"
                              for k in tr.CONDITIONS)
            lines.append(
                f"| {row['변형']} | " + " | ".join(
                    f"{_f(row['지표'][name]['auc_가중'])} "
                    f"[{_diff_text(row['지표'][name]['짝_차이_auc'])}]"
                    if name in row["지표"] else "—" for name in subsets)
                + f" | {_f(row['이름_있는_심결+쉬운_음성_auc_가중'])} | "
                  f"{_f(row['쉬운_음성_평균_p'])} | "
                  f"{sum(row['단조성_위반(하한 이상 행)'].values())} | {checks} |")
        lines.append("")
        lines.append("칸: 가중 AUC [v1.3 그대로와의 짝 차이(95% CI)].")
        for row in results["사후_진단"]:
            lines.append(f"- {row['변형']}: {row['설명']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--features", type=Path, default=tr.DEFAULT_FEATURES)
    parser.add_argument("--easy", type=Path, default=tr.DEFAULT_EASY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL,
                        help="채택 기준을 통과하면 쓰는 계수 JSON 경로(기본은 데이터 디렉터리 — "
                             "shared/model/risk_model_v1.4.json 은 2차 시도의 채택분이다)")
    parser.add_argument("--v13", type=Path, default=DEFAULT_V13, help="비교할 기존 v1.3 JSON")
    parser.add_argument("--structure", choices=("v1.4", "v1.3"), default="v1.4",
                        help="v1.3 = 이름 있는 행만(폴백 구조)")
    parser.add_argument("--fit-mode", choices=("joint", "sequential"), default="joint",
                        help="joint = 여섯 집합을 한 번에(명세), sequential = 이름 있는 패턴을 "
                             "먼저 적합해 고정하고 이름 없는 패턴만 제약 아래 적합")
    parser.add_argument("--folds", type=int, default=FOLDS)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--bootstrap", type=int, default=BOOTSTRAP, help="계수·판례 조건 재적합")
    parser.add_argument("--metric-bootstrap", type=int, default=METRIC_BOOTSTRAP,
                        help="지표 CI·짝 차이(묶음 복원추출)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-photo-rule", action="store_true")
    parser.add_argument("--no-sensitivity", action="store_true")
    parser.add_argument("--no-diagnostics", action="store_true")
    parser.add_argument("--force-model", action="store_true",
                        help="채택 기준에 못 미쳐도 --model 경로에 쓴다")
    args = parser.parse_args(argv)
    results = run(args.features, args.easy, out_dir=args.out_dir, model_path=args.model,
                  v13_path=args.v13, structure=args.structure, mode=args.fit_mode,
                  folds=args.folds,
                  repeats=args.repeats, bootstrap=args.bootstrap,
                  metric_bootstrap=args.metric_bootstrap, seed=args.seed,
                  photo_rule=not args.no_photo_rule, sensitivity=not args.no_sensitivity,
                  diagnostics=not args.no_diagnostics, force_model=args.force_model)
    print(report_text(results))
    return 0 if results["채택"]["채택"] else 3


if __name__ == "__main__":
    sys.exit(main())
