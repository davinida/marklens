"""업종 상한(goods_cap)만 켠 서비스 모델 v1.4.6 — 확인 조건 ①–④ 를 모두 넘으면 적용(설계 §7-13).

2026-11-24 사람 결정: 4-b 변형 L·S(이름 있는 업종 두 벌의 곱하기 항)는 채택하지 않는다(채택
조건 ④ 미달 — 실제 분쟁 쌍의 위험이 빠지고 시연의 스타벅수가 주의로 내려감). 대신 v1.4.5 에
업종 상한만 켠다: v1.4.6 = v1.4.5 + 최상위 `goods_cap: {"enabled": true}` — 계수·기준·다른 규칙
그대로. 업종 상한은 업종이 다를 때(겹침 < 결합 하한 0.0252) 업종 집합(이름 없는 이미지+업종 ↔
이미지만, 이름+업종 ↔ 이름만, 이름+이미지+업종 ↔ 이름+이미지)의 등급을 업종 없는 짝 판단의
등급 — 단독 축·도형 규칙 등 그 판단에 걸리는 규칙까지 반영한 등급(엔진 `_judge` = `risk_score`)
— 이하로 내리기만 한다(엔진 `_nameless_judgment`·`_named_judgment`, rule_triggers `goods_cap`).

확인 조건(`RULE` — 실행 전에 해시를 남기고 결과를 보고 바꾸지 않는다):
① 시연 시나리오(크린토피야·스타벅수·파리바게트·블루커피)의 전체 등급과 1위 후보(이름·등급)가
   v1.4.5 와 같다.
② 대조군·표본 A 의 질의 전체 등급 변화는 내려간 것만.
③ 표본 A 인용상표(이름 있는 판단)의 검토 권장 이상 비율이 2%p 넘게 떨어지지 않고, 등급이
   내려간 쌍 중 심결 유사가 절반 이하(5쌍 미만이면 보고만).
④ 원칙 상설 시험(test_goods_principle.py)이 모두 통과 — run 은 같은 판정식을 후보 모델로 먼저
   본다.

    ml/venv/bin/python ml/scripts/goods_cap.py freeze   # 설정·입력 해시(있으면 종료 코드 4)
    ml/venv/bin/python ml/scripts/goods_cap.py run      # v1.4.5 대 v1.4.6 — ①–④, 미달이면 3
    ml/venv/bin/python ml/scripts/goods_cap.py apply    # 모두 통과면 risk_model_v1.4.6.json
    ml/venv/bin/python ml/scripts/goods_cap.py verify   # 기본 모델 v1.4.6 = run 의 v1.4.6 결과

KIPRIS 호출 0. 실제 CLIP·OCR·X3 엔진(`MARKLENS_FAKE_ML` 없이).
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
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

from src.model import risk_model as rm  # noqa: E402

from scripts import logo_floor_image_only as lo  # noqa: E402
from scripts import named_goods_product as ngp  # noqa: E402
from scripts import named_search_thresholds as first  # noqa: E402
from scripts import nameless_shared_threshold as ns  # noqa: E402

TRIALS = ML_ROOT / "data" / "trials"
STEM = "goods_cap"
EXIT_STOP = 3
EXIT_REFUSED = 4
BASE_MODEL_PATH = rm.V145_MODEL_PATH
BASE_VERSION = "risk_model_v1.4.5"
NEW_VERSION = "risk_model_v1.4.6"
NEW_MODEL_PATH = rm.V146_MODEL_PATH
BEFORE, AFTER = "v1.4.5", "v1.4.6"
SAVED_4B = TRIALS / "named_goods_product_searches.json.gz"  # 4-b 실행 — 시나리오 '지금' 검산
DECISION = ("2026-11-24 사람 결정: 4-b 변형 L·S 는 채택하지 않는다(채택 조건 ④ 미달 — 실제 분쟁 "
            "쌍의 위험이 빠지고 시연의 스타벅수가 주의로 내려감). 대신 업종 상한(goods_cap)만 "
            "v1.4.5 에 켜서 v1.4.6 으로 한다.")
DEMO = {"F2": "크린토피야", "F1": "스타벅수", "F3": "파리바게트", "S1": "블루커피"}
CITED_DROP_MAX = 0.02
CHANGE_MIN_ROWS = 5
DISPLAY_TOP = first.DISPLAY_TOP
REVIEW = "검토 권장"
NAMED_MODES = ngp.MODES  # 이름만·이름+업종·이름+이미지·이름+이미지+업종
REPEAT = ns.REPEAT  # 이름 없는 대조군 — 이미지 하나에 업종 세트 10
X4_GRID = tuple(round(0.002 * i, 3) for i in range(13)) + (0.0252, 0.05, 0.1, 0.3, 0.5, 1.0)
SMOKE = {"대조군_이름": 2, "이름_없는_대조군_이미지": 1, "표본A": 3, "시나리오": ("S6", "S7")}

RULE = {
    "결정": DECISION,
    "바꾸는_것": ("v1.4.6 = v1.4.5 + 최상위 goods_cap {\"enabled\": true}(이름 없는·이름 있는 판단 "
        "모두). 계수·기준·다른 규칙(logo_floor·weak_run·이름 없는 이미지+업종 집합의 "
        "goods_rule·업종 하한 goods_floor)은 그대로. 업종 상한은 업종이 다를 때(겹침 < "
        "coupling.floors.x4 = 0.0252) 등급을 업종 없는 짝 판단의 등급 이하로 내리기만 한다 — 짝 "
        "판단 등급은 단독 축 규칙 등 그 판단에 걸리는 규칙까지 반영한 등급(엔진 _judge = "
        "risk_score 의 단독 축·도형 규칙 — 구현이 이와 같음을 확인). 업종 집합과 짝: 이름 없는 "
        "이미지+업종 ↔ 이미지만, 이름+업종(x4) ↔ 이름만(base), 이름+이미지+업종(x2_whole+x4) ↔ "
        "이름+이미지(x2_whole)."),
    "질의": ("v1.4.5 와 v1.4.6 을 같은 프로세스에서 엔진 계수만 바꿔 같은 입력으로 검색. (가) "
        "지어낸 이름 대조군 기준용·확인용 각 100 이름 × 네 "
        "방식(이름만·이름+업종·이름+이미지·이름+이미지+업종 — 1차 시도 대조군의 이미지·업종 "
        "세트) (나) 이름 없는 대조군 기준용·확인용 각 46 이미지 × (이미지만 1 + 이미지+업종 10 — "
        "업종 세트는 nameless_shared_threshold.control_queries, seed 0) (다) 표본 A 184 질의 × "
        "이름 있는 질의(상표명 + 이미지 + 질의 업종이 있으면 업종)·이름 없는 질의(이미지 + "
        "업종이 있으면 업종). 질의 전체 등급 = 위험도 정렬 앞 5 후보 등급의 최댓값."),
    "확인_1": ("시연 시나리오 F2 크린토피야·F1 스타벅수·F3 파리바게트·S1 블루커피(시나리오 16종 — "
        "named_shared_threshold.scenario_inputs, 엔진 multi_search top_k 5): 전체 등급과 1위 "
        "후보(이름·등급)가 v1.4.5 와 같다. 다르면 적용하지 않고 멈춘다. 그 밖의 후보 등급 "
        "변화(16종 각 후보 풀 전체)와 나머지 시나리오의 변화(전체 등급·위험도·앞 5)는 목록으로 "
        "보고."),
    "확인_2": ("(가)–(다)의 질의 전체 등급 변화 목록: 내려간 것만 있어야 한다. 올라간 것이 "
        "하나라도 있으면 멈춘다."),
    "확인_3": ("표본 A 인용상표(이름 있는 판단 — 표본 A 사건의 심결 쌍 중 이름 축이 있는 행을 "
        "엔진과 같은 식 named_goods_product.engine_grade(업종 하한·상한·logo_floor)로): 검토 "
        "권장 이상 비율이 v1.4.5 보다 2%p 넘게 떨어지지 않음. 등급이 내려간 쌍은 목록, 그중 "
        "심결이 유사로 본 쌍(최종라벨)이 절반 이하 — 5쌍 미만이면 판정에 쓰지 않고 보고만."),
    "확인_4": ("원칙 상설 시험(ml/tests/test_goods_principle.py)이 모두 통과 — strict xfail 을 "
        "풀고 v1.4.6 을 기본으로 둔 뒤 pytest 로 확인. run 은 같은 판정식(격자 + 학습 특징 실제 "
        "쌍, 이름 없는·이름 있는 판단 — 업종이 겹치면 최종 등급 ≥ 짝, 다르면 최종 등급 ≤ 짝)을 "
        "후보 모델로 먼저 보고 위반이 있으면 멈춘다."),
    "검산": ("v1.4.5 의 시나리오 16종 전체·앞 5 가 4-b 실행 "
        "저장값(named_goods_product_searches.json.gz 의 '지금')과 같아야 한다 — 다르면 멈춤."),
    "판정": "①–④ 모두 통과면 적용(apply). 하나라도 미달이면 적용하지 않고 멈춘다(종료 코드 3).",
    "적용": ("shared/model/risk_model_v1.4.6.json(= 후보: version·goods_cap·meta.goods_cap 만 "
        "다름), 런타임 DEFAULT_MODEL_PATH·MODEL_VERSION, CI 이미지 검사, 계약 v2(업종 상한), "
        "Vitest 픽스처(실제 엔진), 시험. verify 는 기본 모델 v1.4.6 로 같은 질의·시나리오를 다시 "
        "돌려 run 의 v1.4.6 결과(전체·앞 5)와 같은지."),
    "스모크": ("구현 확인은 일부(지어낸 이름 반마다 2·이미지 반마다 1·표본 A 3·시나리오 S6·S7)로 "
        "다른 폴더에 — 채택 지표(①–④)는 본 실행에서 처음 본다."),
}


def _settings() -> dict:
    return {"RULE": RULE, "BASE_VERSION": BASE_VERSION, "NEW_VERSION": NEW_VERSION, "DEMO": DEMO,
            "CITED_DROP_MAX": CITED_DROP_MAX, "CHANGE_MIN_ROWS": CHANGE_MIN_ROWS,
            "DISPLAY_TOP": DISPLAY_TOP, "REPEAT": REPEAT, "X4_GRID": X4_GRID, "SMOKE": SMOKE,
            "CONTROL_SHA": ns.CONTROL_SHA}


def rule_sha256() -> str:
    return first.canonical_sha256(_settings())


def _inputs() -> dict[str, Path]:
    inputs = ngp._inputs()  # noqa: SLF001 — 4-b 와 같은 입력(계수 JSON v1.4.5·엔진·런타임·데이터)
    inputs.update({"4-b_실행_검색": SAVED_4B,
                   "4-b_평가_스크립트": ML_ROOT / "scripts" / "named_goods_product.py",
                   "원칙_시험": ML_ROOT / "tests" / "test_goods_principle.py"})
    return inputs


def _paths(out_dir: Path) -> dict[str, Path]:
    return {"rule": out_dir / f"{STEM}_rule.json",
            "results": out_dir / f"{STEM}_results.json",
            "report": out_dir / f"{STEM}_report.md",
            "candidate": out_dir / f"{STEM}_candidate.json",
            "searches": out_dir / f"{STEM}_searches.json.gz",
            "verify": out_dir / f"{STEM}_verify.json"}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def grade_index(grade: str | None) -> int:
    return -1 if grade is None else rm.GRADES.index(grade)


# ---- 후보 모델 --------------------------------------------------------------------------------

def candidate_model(base: dict, *, rule_sha: str) -> dict:
    """v1.4.6 = v1.4.5 + goods_cap 켬. 바뀌는 키는 version·goods_cap·meta.goods_cap 뿐."""
    if base.get("version") != BASE_VERSION:
        raise ValueError("기준 모델이 v1.4.5 가 아닙니다")
    model = copy.deepcopy(base)
    model["version"] = NEW_VERSION
    model[rm.GOODS_CAP_KEY] = {"enabled": True}
    model.setdefault("meta", {})["goods_cap"] = {
        "decided_at": datetime.now().date().isoformat(), "derived_from": BASE_VERSION,
        "decision": DECISION, "rule_sha256": rule_sha, "script": "ml/scripts/goods_cap.py",
        "rule": ("업종이 다르면(겹침 < coupling.floors.x4) 업종 집합의 등급을 업종 없는 짝 판단의 "
                 "등급(단독 축·도형 규칙 반영) 이하로 내리기만 한다 — 이름 없는 이미지+업종 ↔ "
                 "이미지만, x4 ↔ base, x2_whole+x4 ↔ x2_whole"),
        "checks": None}
    return model


def differing_keys(base: dict, model: dict) -> list[str]:
    """최상위에서 값이 다른 키(meta 는 안쪽 키까지)."""
    out = [k for k in sorted(set(base) | set(model)) if k != "meta" and base.get(k) != model.get(k)]
    meta_a, meta_b = base.get("meta") or {}, model.get("meta") or {}
    out += [f"meta.{k}" for k in sorted(set(meta_a) | set(meta_b))
            if meta_a.get(k) != meta_b.get(k)]
    return out


# ---- 검색 -------------------------------------------------------------------------------------

def run_named_control(context: dict, control: dict, models: dict, limit: int | None) -> list[dict]:
    a_by_key = {query.key: query for query in context["A"]}
    out = []
    for half in ("기준용", "확인용"):
        for item in ngp.control_items(control, half, limit):
            image = context["service"](a_by_key[item["이미지"]].path.read_bytes())
            goods = sorted(item["유사군"]) or None
            row = {"반": half, "이름": item["이름"], "방식": {}}
            for mode, with_image, with_goods in NAMED_MODES:
                row["방식"][mode] = ngp.search(context, models, None, name=item["이름"],
                                              image=image if with_image else None,
                                              goods_codes=goods if with_goods else None)
            out.append(row)
        print(f"    지어낸 이름 대조군 {half} {len(out)}", flush=True)
    return out


def run_nameless_control(context: dict, control: dict, models: dict,
                         limit: int | None) -> list[dict]:
    a_by_key = {query.key: query for query in context["A"]}
    out = []
    for item in ns.control_queries(control["대조군"], limit, REPEAT):
        image = context["service"](a_by_key[item["키"]].path.read_bytes())
        runs = [("이미지만", None, None)] + [("이미지+업종", preset["id"], sorted(preset["유사군"]))
                                          for preset in item["업종"]]
        for mode, preset_id, codes in runs:
            out.append({"반": item["반"], "키": item["키"], "방식": mode, "업종_id": preset_id,
                        "검색": ngp.search(context, models, None, image=image, goods_codes=codes)})
    print(f"    이름 없는 대조군 {len(out)}", flush=True)
    return out


def run_sample_a(context: dict, models: dict, limit: int | None) -> list[dict]:
    out = []
    for query in context["A"][:limit]:
        image = context["service"](query.path.read_bytes())
        goods = sorted(query.goods) or None
        out.append({"질의": query.key, "업종": bool(query.goods),
                    "이름_있음": ngp.search(context, models, None, image=image, name=query.name,
                                         goods_codes=goods),
                    "이름_없음": ngp.search(context, models, None, image=image, goods_codes=goods)})
    print(f"    표본 A {len(out)}", flush=True)
    return out


def run_scenarios(context: dict, models: dict, keys: tuple[str, ...] | None = None) -> dict:
    """시나리오 16종 — multi_search(top_k 5)의 전체·앞 5 와 후보 풀 전체(search_pool)의 등급."""
    from scripts import named_shared_threshold as second

    ms = context["ms"]
    out: dict = {}
    for label, model in models.items():
        out[label] = {}
        suggested = None
        with ns.using_model(ms, model):
            for key, title, inputs in second.scenario_inputs(ms, context["service"]):
                if keys is not None and key not in keys:
                    continue
                if inputs.get("name") == "@S3":
                    if not suggested:
                        out[label][key] = {"제목": title, "건너뜀": True}
                        continue
                    inputs["name"] = suggested
                data = ms.multi_search(**inputs, top_k=DISPLAY_TOP).to_dict()
                if key == "S3":
                    suggested = data["overall"]["query_type"].get("suggested_name")
                pooled = ms.search_pool(**inputs)
                out[label][key] = {
                    "제목": title,
                    "전체": {k: data["overall"][k] for k in ("grade", "prob", "pattern")},
                    "상위": [{"id": c["id"], "title": c["title"], "grade": c["risk"]["grade"],
                            "prob": c["risk"]["prob"], "pattern": c["risk"]["pattern"],
                            "rules": c["risk"]["rule_triggers"]} for c in data["candidates"]],
                    "풀": {c.id: [c.title, c.grade, round(float(c.prob), 6), c.pattern,
                                 list(c.rule_triggers)] for c in pooled.candidates}}
    return out


# ---- 확인 조건 ---------------------------------------------------------------------------------

def check_1(scenarios: dict) -> dict:
    """① 시연 넷의 전체 등급·1위 후보(이름·등급) 같음 + 그 밖의 변화 목록."""
    before, after = scenarios[BEFORE], scenarios[AFTER]
    demo, passed, judged = {}, True, 0
    for key, name in DEMO.items():
        b, a = before.get(key), after.get(key)
        if not b or not a or b.get("건너뜀") or a.get("건너뜀"):
            demo[key] = {"이름": name, "돌리지_않음": True}
            continue
        judged += 1
        top_b = [b["상위"][0]["title"], b["상위"][0]["grade"]] if b["상위"] else None
        top_a = [a["상위"][0]["title"], a["상위"][0]["grade"]] if a["상위"] else None
        same = b["전체"]["grade"] == a["전체"]["grade"] and top_b == top_a
        demo[key] = {"이름": name, "전": {"전체": b["전체"], "1위": top_b},
                     "후": {"전체": a["전체"], "1위": top_a}, "같음": same}
        passed = passed and same
    changes = []
    for key, b in before.items():
        a = after.get(key) or {}
        if b.get("건너뜀") or a.get("건너뜀"):
            continue
        pool = []
        for cid, (title, grade, prob, pattern, rules) in b["풀"].items():
            new = a["풀"].get(cid)
            if new is None or new[1] != grade:
                pool.append({"후보": cid, "이름": title, "전": [grade, prob, pattern, rules],
                             "후": None if new is None else [new[1], new[2], new[3], new[4]]})
        overall = b["전체"] != a["전체"]
        top = [c["id"] for c in b["상위"]] != [c["id"] for c in a["상위"]]
        if overall or top or pool:
            changes.append({"키": key, "제목": b["제목"], "시연": key in DEMO,
                            "전체": [b["전체"], a["전체"]] if overall else None,
                            "앞5_바뀜": top, "후보_등급_변화": pool})
    return {"시연": demo, "그_밖의_변화": changes,
            "통과": passed if judged == len(DEMO) else None}


def check_2(named: list[dict], nameless: list[dict], sample: list[dict]) -> dict:
    """② 질의 전체 등급 변화 — 내려간 것만."""
    counts, changed, candidates = Counter(), [], Counter()

    def visit(where: str, query: str, mode: str, entry: dict) -> None:
        b, a = entry[BEFORE], entry[AFTER]
        counts[where] += 1
        for cid, values in b["후보"].items():
            new = a["후보"].get(cid)
            if new is not None and new[0] != values[0]:
                direction = "내려감" if grade_index(new[0]) < grade_index(values[0]) else "올라감"
                candidates[f"{where} {direction}"] += 1
        if b["전체"] != a["전체"]:
            direction = "내려감" if grade_index(a["전체"]) < grade_index(b["전체"]) else "올라감"
            changed.append({"출처": where, "질의": query, "방식": mode, "전": b["전체"],
                            "후": a["전체"], "방향": direction,
                            "앞5_전": [[c, *b["후보"][c][:3]] for c in b["상위"]],
                            "앞5_후": [[c, *a["후보"][c][:3], a["후보"][c][5]] for c in a["상위"]]})

    for row in named:
        for mode, entry in row["방식"].items():
            visit(f"지어낸 이름 대조군 {row['반']} {mode}", row["이름"], mode, entry)
    for row in nameless:
        visit(f"이름 없는 대조군 {row['반']} {row['방식']}", f"{row['키']}|{row['업종_id']}",
              row["방식"], row["검색"])
    for row in sample:
        visit("표본 A 이름 있음", row["질의"], "이름 있음", row["이름_있음"])
        visit("표본 A 이름 없음", row["질의"], "이름 없음", row["이름_없음"])
    up = [item for item in changed if item["방향"] == "올라감"]
    return {"본_질의": dict(counts), "바뀐_질의": changed, "내려감": len(changed) - len(up),
            "올라감": len(up), "후보_등급_변화": dict(candidates), "통과": not up}


def cited_pairs(case_ids: set[str]) -> list[dict]:
    """표본 A 사건의 심결 쌍 중 이름 축이 있는 행(named_goods_product.cited_rows 와 같은 행·
    특징)."""
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    out = []
    for row in t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY).rows:
        if row.get("pair_source") != "trial" or str(row.get("심판번호")) not in case_ids:
            continue
        if not tr.has_name(row):
            continue
        features = t4.service_features(row, image_column=t4.RAW_IMAGE)
        features["mark_type"] = "결합-문자요부" if features["x2_whole"] is not None else "문자"
        out.append({"심판번호": str(row.get("심판번호")), "상대번호": row.get("상대번호"),
                    "쌍키": row.get("쌍키"), "라벨": row.get("최종라벨"), "특징": features})
    return out


def check_3(pairs: list[dict], base: dict, new: dict) -> dict:
    """③ 인용상표 검토 권장 이상 비율 하락 ≤ 2%p, 내려간 쌍 중 유사 ≤ 절반(5쌍 이상일 때)."""
    before = [ngp.engine_grade(p["특징"], base) for p in pairs]
    after = [ngp.engine_grade(p["특징"], new) for p in pairs]

    def rate(grades: list[str]) -> float | None:
        if not grades:
            return None
        return round(sum(ns.at_least(g, REVIEW) for g in grades) / len(grades), 4)

    dropped = [{"심판번호": p["심판번호"], "상대번호": p["상대번호"], "라벨": p["라벨"],
                "전": b, "후": a, "겹침": p["특징"].get("x4")}
               for p, b, a in zip(pairs, before, after) if grade_index(a) < grade_index(b)]
    raised = sum(1 for b, a in zip(before, after) if grade_index(a) > grade_index(b))
    now, later = rate(before), rate(after)
    drop_ok = now is not None and later is not None and later >= now - CITED_DROP_MAX - 1e-12
    similar = (round(sum(1 for d in dropped if d["라벨"] == "유사") / len(dropped), 4)
               if dropped else None)
    judged = len(dropped) >= CHANGE_MIN_ROWS
    similar_ok = (not judged) or similar <= 0.5 + 1e-12
    return {"쌍": len(pairs), "검토_권장_이상": {BEFORE: now, AFTER: later},
            "차": None if now is None or later is None else round(later - now, 4),
            "등급": {BEFORE: ns.distribution(before), AFTER: ns.distribution(after)},
            "내려간_쌍": dropped, "내려간_쌍_유사_비율": similar, "판정에_씀": judged,
            "올라간_쌍": raised, "통과": drop_ok and similar_ok}


def named_final(features: dict, model: dict) -> tuple[str, str]:
    """(이름 있는 업종 집합의 최종 등급, 짝 등급) — 엔진 _named_judgment 와 같은 규칙."""
    result = rm.risk_score(features, model)
    pair = rm.risk_score({**features, "x4": None}, model)
    grade, floor = result.grade, float(model["coupling"]["floors"]["x4"])
    rule = model["patterns"][result.pattern].get(rm.GOODS_RULE_KEY) == rm.GOODS_RULE_NO_RAISE
    if float(features["x4"]) >= floor:
        if rule:
            grade = max(grade, pair.grade, key=rm.GRADES.index)
    elif rm.goods_cap_enabled(model):
        grade = min(grade, pair.grade, key=rm.GRADES.index)
    return grade, pair.grade


def nameless_final(x2: float, x4: float, model: dict, level: str = "도형") -> tuple[str, str]:
    """(이름 없는 이미지+업종 판단의 최종 등급, 이미지만 등급) — 엔진 _nameless_judgment."""
    features = {**ns.nameless_features(x2, x4), "mark_type": level}
    grade = first.nameless_final_grade(features, model)  # 업종 하한까지
    alone = rm.risk_score({**features, "x4": None}, model).grade
    if float(x4) < float(model["coupling"]["floors"]["x4"]) and rm.goods_cap_enabled(model):
        grade = min(grade, alone, key=rm.GRADES.index)
    return grade, alone


def _violations(pairs, floor: float) -> dict[str, int]:
    out = {"겹침": 0, "다름": 0, "본_점": 0}
    for x4, final, pair in pairs:
        out["본_점"] += 1
        if x4 >= floor and rm.GRADES.index(final) < rm.GRADES.index(pair):
            out["겹침"] += 1
        elif x4 < floor and rm.GRADES.index(final) > rm.GRADES.index(pair):
            out["다름"] += 1
    return out


def principle_check(model: dict) -> dict:
    """④ 미리 보기 — test_goods_principle.py 와 같은 판정식(격자 + 학습 특징 실제 쌍)."""
    from scripts import train_risk_model as tr
    from scripts import train_risk_model_v14 as t4

    floor = float(model["coupling"]["floors"]["x4"])
    nameless_grid = [(x4, *nameless_final(x2 / 100, x4, model, level))
                     for level in ("도형", "문자") for x2 in range(101) for x4 in X4_GRID]
    named_grid = []
    for level in ("문자", "도형"):
        for distinctive in (True, False):
            for x1 in [i / 10 for i in range(11)]:
                for x2t in [i / 10 for i in range(11)]:
                    for x2 in (None, 0.0, 0.3, 0.6, 0.9, 1.0):
                        for x4 in X4_GRID:
                            features = {"x1_d": x1, "x2_text_d": x2t, "x3_d": None,
                                        "has_meaning_both": False, "x2_whole": x2, "x4": x4,
                                        "has_distinctive_part_a": True,
                                        "has_distinctive_part_b": distinctive,
                                        "mark_type": level}
                            named_grid.append((x4, *named_final(features, model)))
    named_real, nameless_real = [], []
    for row in t4.load_dataset(tr.DEFAULT_FEATURES, tr.DEFAULT_EASY).rows:
        features = t4.service_features(row)
        if features.get("x4") is None:
            continue
        if tr.has_name(row):
            named_real.append((float(features["x4"]), *named_final(features, model)))
        if features.get("x2_whole") is not None:
            nameless_real.append((float(features["x4"]), *nameless_final(
                float(features["x2_whole"]), float(features["x4"]), model)))
    parts = {"이름 없는 격자": _violations(nameless_grid, floor),
             "이름 없는 실제 쌍": _violations(nameless_real, floor),
             "이름 있는 격자": _violations(named_grid, floor),
             "이름 있는 실제 쌍": _violations(named_real, floor)}
    passed = all(part["겹침"] == 0 and part["다름"] == 0 for part in parts.values())
    return {**parts, "통과": passed}


def fidelity(scenarios: dict) -> dict:
    """검산 — v1.4.5 시나리오가 4-b 실행의 '지금' 저장값과 같은지."""
    with gzip.open(SAVED_4B, "rt", encoding="utf-8") as handle:
        saved = json.load(handle)["시나리오"]["지금"]
    now = scenarios[BEFORE]
    differ = [key for key in now if not now[key].get("건너뜀") and (
        now[key]["전체"] != saved.get(key, {}).get("전체")
        or [c["id"] for c in now[key]["상위"]]
        != [c["id"] for c in saved.get(key, {}).get("상위", [])])]
    return {"견준_시나리오": sum(1 for v in now.values() if not v.get("건너뜀")), "다른_것": differ,
            "같음": not differ}


# ---- 명령 -------------------------------------------------------------------------------------

def command_freeze(args) -> int:
    paths = _paths(args.out_dir)
    if paths["rule"].exists() and not args.force:
        print(f"거절: {paths['rule']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    base = rm.validate_model(json.loads(BASE_MODEL_PATH.read_text(encoding="utf-8")))
    if base.get("version") != BASE_VERSION or rm.goods_cap_enabled(base):
        print("거절: 기준 JSON 이 업종 상한 없는 v1.4.5 가 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))  # noqa: SLF001
    if control["대조군_sha256"] != ns.CONTROL_SHA:
        print("거절: 1차 시도 대조군 해시가 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    args.out_dir.mkdir(parents=True, exist_ok=True)
    frozen = {"설정_sha256": rule_sha256(), "스크립트_sha256": first.file_sha256(Path(__file__)),
              "입력_sha256": {k: first.file_sha256(p) for k, p in _inputs().items()},
              "고정": _now(), "설정": _settings()}
    paths["rule"].write_text(json.dumps(frozen, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    print(f"설정 sha256 {frozen['설정_sha256']} · 스크립트 sha256 {frozen['스크립트_sha256']}")
    return 0


def _check_frozen(paths: dict, *, model_may_change: bool = False) -> dict | None:
    if not paths["rule"].exists():
        print("거절: 먼저 freeze", file=sys.stderr)
        return None
    frozen = json.loads(paths["rule"].read_text(encoding="utf-8"))
    if frozen["설정_sha256"] != rule_sha256():
        print("거절: 설정이 고정본과 다릅니다", file=sys.stderr)
        return None
    skip = {"런타임", "엔진", "원칙_시험"} if model_may_change else set()
    changed = [k for k, p in _inputs().items()
               if k not in skip and first.file_sha256(p) != frozen["입력_sha256"].get(k)]
    if changed:
        print(f"거절: 입력이 고정 때와 다릅니다 — {changed}", file=sys.stderr)
        return None
    return frozen


def report_text(results: dict) -> str:
    lines = [f"# 업종 상한 v1.4.6 확인 ({results.get('끝', '')})", "",
             f"- 설정 sha256 `{results['설정_sha256']}`, 스모크 {results['스모크']}",
             f"- 검산(v1.4.5 시나리오 = 4-b 저장값): {results.get('검산', {}).get('같음')}"]
    for key in ("확인_1", "확인_2", "확인_3", "확인_4"):
        part = results.get(key)
        if part is not None:
            lines.append(f"- {key}: 통과 {part.get('통과')}")
    c2 = results.get("확인_2") or {}
    lines.append(f"- 질의 전체 등급: 내려감 {c2.get('내려감')}·올라감 {c2.get('올라감')}")
    c3 = results.get("확인_3") or {}
    lines.append(f"- 인용상표 검토 권장 이상 {c3.get('검토_권장_이상')} (차 {c3.get('차')}), "
                 f"내려간 쌍 {len(c3.get('내려간_쌍', []))}")
    lines.append(f"- 적용: {results.get('적용')} {results.get('멈춤', '')}")
    return "\n".join(lines) + "\n"


def command_run(args) -> int:
    paths = _paths(args.out_dir)
    frozen = _check_frozen(paths)
    if frozen is None:
        return EXIT_REFUSED
    if paths["results"].exists() and not args.force:
        print(f"거절: {paths['results']} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    if args.smoke and args.out_dir.resolve() == TRIALS.resolve():
        print("거절: 스모크는 --out-dir 로 다른 폴더에", file=sys.stderr)
        return EXIT_REFUSED
    started, timing = time.perf_counter(), {}
    smoke = bool(args.smoke)
    results: dict = {"설정_sha256": frozen["설정_sha256"],
                     "스크립트_sha256(고정 때)": frozen["스크립트_sha256"],
                     "스크립트_sha256(잴 때)": first.file_sha256(Path(__file__)), "스모크": smoke,
                     "시작": _now()}

    def tick(name: str, began: float) -> None:
        timing[name] = round(time.perf_counter() - began, 1)
        print(f"  {name} {timing[name]}초", flush=True)

    def finish(code: int) -> int:
        results.update(시간_s=timing, 걸린_시간_s=round(time.perf_counter() - started, 1),
                       끝=_now())
        paths["results"].write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                                    encoding="utf-8")
        paths["report"].write_text(report_text(results), encoding="utf-8")
        print(json.dumps({k: results.get(k) for k in ("적용", "멈춤")}, ensure_ascii=False))
        return code

    base = rm.validate_model(json.loads(BASE_MODEL_PATH.read_text(encoding="utf-8")))
    candidate = candidate_model(base, rule_sha=frozen["설정_sha256"])
    rm.validate_model(candidate)
    results["후보_다른_키"] = differing_keys(base, candidate)

    began = time.perf_counter()
    context = ns._context(BASE_MODEL_PATH)  # noqa: SLF001
    ms = context["ms"]
    if ms.state.model.get("version") != BASE_VERSION:
        results.update(적용=False, 멈춤="엔진 모델이 v1.4.5 가 아님")
        return finish(EXIT_STOP)
    lo.memo_ocr(ms)
    models = {BEFORE: ms.state.model, AFTER: candidate}
    tick("엔진", began)

    began = time.perf_counter()
    scenarios = run_scenarios(context, models, SMOKE["시나리오"] if smoke else None)
    results["검산"] = fidelity(scenarios)
    tick("시나리오", began)
    if not results["검산"]["같음"]:
        results.update(적용=False, 멈춤="v1.4.5 시나리오가 4-b 저장값과 다름")
        return finish(EXIT_STOP)

    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))  # noqa: SLF001
    began = time.perf_counter()
    named = run_named_control(context, control, models, SMOKE["대조군_이름"] if smoke else None)
    tick("지어낸 이름 대조군", began)
    began = time.perf_counter()
    nameless = run_nameless_control(context, control, models,
                                    SMOKE["이름_없는_대조군_이미지"] if smoke else None)
    tick("이름 없는 대조군", began)
    began = time.perf_counter()
    sample = run_sample_a(context, models, SMOKE["표본A"] if smoke else None)
    tick("표본 A", began)

    began = time.perf_counter()
    case_ids = {query.key.split(":")[1] for query in context["A"]}
    results["확인_1"] = check_1(scenarios)
    results["확인_2"] = check_2(named, nameless, sample)
    results["확인_3"] = check_3(cited_pairs(case_ids), base, candidate)
    results["확인_4"] = principle_check(candidate)
    results["확인_4(v1.4.5 — 보고만)"] = principle_check(base)
    tick("확인 조건", began)
    with gzip.open(paths["searches"], "wt", encoding="utf-8") as handle:
        json.dump({"지어낸_이름_대조군": named, "이름_없는_대조군": nameless, "표본A": sample,
                   "시나리오": scenarios}, handle, ensure_ascii=False)
    checks = [results[f"확인_{i}"]["통과"] for i in range(1, 5)]
    if smoke:
        results.update(적용=None, 멈춤="스모크 — 판정하지 않음")
        return finish(0)
    adopted = all(value is True for value in checks)
    candidate["meta"]["goods_cap"]["checks"] = {
        f"확인_{i}": results[f"확인_{i}"]["통과"] for i in range(1, 5)}
    paths["candidate"].write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
    results["적용"] = adopted
    if not adopted:
        failed = [f"확인_{i}" for i, value in enumerate(checks, start=1) if value is not True]
        results["멈춤"] = f"미달 {failed}"
        return finish(EXIT_STOP)
    return finish(0)


def command_apply(args) -> int:
    paths = _paths(args.out_dir)
    if _check_frozen(paths, model_may_change=True) is None:
        return EXIT_REFUSED
    results = json.loads(paths["results"].read_text(encoding="utf-8"))
    if results.get("스모크") or results.get("적용") is not True:
        print("거절: 확인 조건을 모두 넘은 본 실행 결과가 아닙니다 — 적용하지 않습니다",
              file=sys.stderr)
        return EXIT_REFUSED
    if NEW_MODEL_PATH.exists() and not args.force:
        print(f"거절: {NEW_MODEL_PATH} 가 있습니다(--force)", file=sys.stderr)
        return EXIT_REFUSED
    candidate = json.loads(paths["candidate"].read_text(encoding="utf-8"))
    base = json.loads(BASE_MODEL_PATH.read_text(encoding="utf-8"))
    if differing_keys(base, candidate) != ["goods_cap", "version", "meta.goods_cap"]:
        print("거절: 후보가 v1.4.5 와 version·goods_cap·meta.goods_cap 말고도 다릅니다",
              file=sys.stderr)
        return EXIT_REFUSED
    rm.validate_model(candidate)
    NEW_MODEL_PATH.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    print(f"썼다: {NEW_MODEL_PATH} ({candidate['version']})")
    return 0


def command_verify(args) -> int:
    """기본 모델을 v1.4.6 으로 바꾼 뒤 — 기본 엔진으로 같은 질의·시나리오를 다시 돌려 run 의
    v1.4.6 결과와 같은지(전체 등급·앞 5)."""
    paths = _paths(args.out_dir)
    if _check_frozen(paths, model_may_change=True) is None:
        return EXIT_REFUSED
    if rm.MODEL_VERSION != NEW_VERSION or rm.resolve_model_path() != NEW_MODEL_PATH:
        print("거절: 서비스 기본 모델이 v1.4.6 이 아닙니다", file=sys.stderr)
        return EXIT_REFUSED
    started = time.perf_counter()
    candidate = json.loads(paths["candidate"].read_text(encoding="utf-8"))
    with gzip.open(paths["searches"], "rt", encoding="utf-8") as handle:
        saved = json.load(handle)
    context = ns._context(NEW_MODEL_PATH)  # noqa: SLF001
    ms = context["ms"]
    if ms.state.model != candidate:
        print("거절: 엔진이 적재한 모델이 후보와 다릅니다", file=sys.stderr)
        return EXIT_REFUSED
    lo.memo_ocr(ms)
    models = {"기본": ms.state.model}
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))  # noqa: SLF001
    mismatch, checked = Counter(), Counter()

    def same(got: dict, old: dict) -> bool:
        return got["전체"] == old["전체"] and got["상위"] == old["상위"]

    for new, old in zip(run_named_control(context, control, models, None),
                        saved["지어낸_이름_대조군"]):
        for mode in new["방식"]:
            checked["지어낸 이름 대조군"] += 1
            mismatch["지어낸 이름 대조군"] += int(not same(new["방식"][mode]["기본"],
                                                    old["방식"][mode][AFTER]))
    for new, old in zip(run_nameless_control(context, control, models, None),
                        saved["이름_없는_대조군"]):
        checked["이름 없는 대조군"] += 1
        mismatch["이름 없는 대조군"] += int(not same(new["검색"]["기본"], old["검색"][AFTER]))
    for new, old in zip(run_sample_a(context, models, None), saved["표본A"]):
        for key in ("이름_있음", "이름_없음"):
            checked["표본 A"] += 1
            mismatch["표본 A"] += int(not same(new[key]["기본"], old[key][AFTER]))
    again = run_scenarios(context, models)["기본"]
    after = saved["시나리오"][AFTER]
    scenario_diff = [key for key, item in again.items()
                     if item.get("전체") != after.get(key, {}).get("전체")
                     or [c["id"] for c in item.get("상위", [])]
                     != [c["id"] for c in after.get(key, {}).get("상위", [])]]
    verify = {"모델": ms.state.model["version"], "다시_돌린_검색": dict(checked),
              "불일치": dict(mismatch), "시나리오_다른_것": scenario_diff,
              "통과": not any(mismatch.values()) and not scenario_diff,
              "걸린_시간_s": round(time.perf_counter() - started, 1), "끝": _now()}
    paths["verify"].write_text(json.dumps(verify, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")
    print(json.dumps(verify, ensure_ascii=False))
    return 0 if verify["통과"] else EXIT_STOP


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("freeze", "run", "apply", "verify"))
    parser.add_argument("--out-dir", type=Path, default=TRIALS)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--smoke", action="store_true",
                        help="구현 확인 — 일부 질의만(다른 --out-dir 에, 판정하지 않음)")
    args = parser.parse_args(argv)
    commands = {"freeze": command_freeze, "run": command_run, "apply": command_apply,
                "verify": command_verify}
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
