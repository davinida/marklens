"""업종은 다르지만 표장이 닮은 후보(응답의 cross_goods·cross_goods_more)의 확인 — 통합 모델 설계
§7-15, API 계약 v2 §2-8.

후보별 선택 필드 cross_goods 는 새 판정이 아니다 — 엔진이 후보를 채점하는 같은 함수를 업종 축(x4)만
빼고 한 번 더 부른 등급이다(업종 상한 goods_cap 이 견주는 짝 판단에, 이미지만 판단과의 비교까지).
이 스크립트는 그것을 실제 엔진으로 확인한다(KIPRIS 호출 0, 실제 CLIP·OCR·관념 모델).

    (가) 후보 목록·전체 등급 불변 — 고치기 전 커밋의 엔진과 지금 엔진으로 같은 질의를 돌려 응답을
         글자까지 견준다(새 선택 필드 둘만 빼고). `dump` 를 두 트리에 한 번씩, `compare`.
    (나) 표시가 정의와 같다 — 후보 풀의 모든 후보에서 ① 업종이 다른지 = 업종 겹침 < 결합 하한
         ② 업종 없이 본 등급 = 업종 축만 가리고 엔진의 score_record 를 다시 부른 등급(이 스크립트가
         따로 부른다) ③ 표시 = 다름 그리고 그 등급이 검토 권장 이상, 그 반대도. 업종 없는 질의와
         업종 겹침을 모르는 후보에는 표시가 없다. 범위 밖 칸(cross_goods_more)은 풀에서 다시 고른
         것과 같다.
    (다) 보고 — 표본 A 의 업종 있는 질의와 지어낸 이름 대조군에서 표시가 붙는 질의 수·질의당 개수·
         처음 보이는 범위(앞 5) 밖의 수·그 가운데 유명 상표, 시연 넷의 앞 5 와 전체 등급 옆 한 줄.

질의: 시나리오 16종 · 지어낸 이름 대조군 확인용 100 × 네 방식(400검색) · 표본 A 184(이름 + 이미지,
업종이 있으면 업종도) · 표본 A 의 업종 있는 108(이름 없이 이미지 + 업종) · 예시 하나.

    ml/venv/bin/python ml/scripts/cross_goods_check.py queries            # 질의 목록(엔진을 띄운다)
    ml/venv/bin/python ml/scripts/cross_goods_check.py dump --root <트리> --out <파일.json.gz>
    ml/venv/bin/python ml/scripts/cross_goods_check.py compare <전> <후>   # (가) — 다르면 종료 3
    ml/venv/bin/python ml/scripts/cross_goods_check.py run                # (나)(다) — 어긋나면 3

`dump --root` 는 그 트리의 backend·ml 코드를 불러 쓴다 — 고치기 전 커밋은
`git archive <커밋> | tar -x -C <폴더>` 로 풀고 `ml/data` 를 지금 데이터로 이어 둔다. 결과는
ml/data/trials/cross_goods_check*.json(비공개 데이터 — 커밋하지 않는다).
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import gzip
import hashlib
import json
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
TRIALS = ML_ROOT / "data" / "trials"
QUERIES = TRIALS / "cross_goods_check_queries.json"
RESULTS = TRIALS / "cross_goods_check.json"
CONTROL = TRIALS / "named_search_thresholds_control.json"  # 지어낸 이름 대조군(설계 §7-6)
EXIT_STOP = 3
TOP_K = 5  # 화면 기본 — 처음 보이는 범위
CONTROL_MODES = (("이름만", False, False), ("이름+업종", False, True),
                 ("이름+이미지", True, False), ("이름+이미지+업종", True, True))
CANDIDATE_FIELD = "cross_goods"  # candidates[].cross_goods
MORE_FIELD = "cross_goods_more"  # 응답 최상위 — 처음 보이는 범위 밖의 후보
MORE_LIMIT = 5
GRADES = ("안전", "주의", "검토 권장", "위험")
REVIEW = GRADES.index("검토 권장")
# 시연 넷 — 시나리오 목록의 열쇠
DEMO = (("F2", "크린토피야 + 세탁"), ("F1", "스타벅수 + 카페"), ("F3", "파리바게트 + 빵집"),
        ("S1", "블루커피 + 카페"))
EXAMPLES = (("스타벅스", "clothing"),)  # 화면 캡처 장면 — 스타벅스 + 의류
OVERALL_LINE = "가장 닮은 상표가 다른 업종에 있어요. 업종이 다르면 함께 등록될 수도 있어요."


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")


def _open(path: Path, mode: str):
    if path.suffix == ".gz":
        return gzip.open(path, mode + "t", encoding="utf-8")
    return path.open(mode, encoding="utf-8")


# ---- 응답만으로 보는 것(순수 함수) ---------------------------------------------------------------

def strip_new_fields(response: dict) -> dict:
    """새 선택 필드 둘(최상위 cross_goods_more, 후보의 cross_goods)을 뺀 응답."""
    out = {key: value for key, value in response.items() if key != MORE_FIELD}
    out["candidates"] = [{key: value for key, value in candidate.items()
                          if key != CANDIDATE_FIELD} for candidate in response["candidates"]]
    return out


def has_new_fields(response: dict) -> bool:
    return MORE_FIELD in response or any(CANDIDATE_FIELD in c for c in response["candidates"])


def compare_dumps(before: dict, after: dict) -> dict:
    """고치기 전·후 덤프 — 질의마다 새 선택 필드를 뺀 응답이 글자까지 같은가."""
    problems: list[dict] = []
    groups: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    if list(before["응답"]) != list(after["응답"]):
        problems.append({"질의": "(목록)", "문제": "두 덤프의 질의 목록이 다름"})
    for key in before["응답"]:
        old, new = before["응답"][key], after["응답"].get(key)
        group = key.split(" | ")[0]
        groups[group]["질의"] += 1
        if new is None:
            problems.append({"질의": key, "문제": "후 덤프에 없음"})
            continue
        if has_new_fields(old):
            problems.append({"질의": key, "문제": "전 덤프에 새 필드가 있음"})
        stripped = strip_new_fields(new)
        same = json.dumps(old, ensure_ascii=False) == json.dumps(stripped, ensure_ascii=False)
        groups[group]["같음"] += same
        groups[group]["새_필드_있음"] += has_new_fields(new)
        if not same:
            differing = sorted(k for k in set(old) | set(stripped)
                               if old.get(k) != stripped.get(k))
            problems.append({"질의": key, "문제": "응답이 다름", "다른_키": differing})
    total = sum(counter["질의"] for counter in groups.values())
    return {"전": {k: before[k] for k in ("트리", "모델", "sha256") if k in before},
            "후": {k: after[k] for k in ("트리", "모델", "sha256") if k in after},
            "질의": total, "같음": sum(counter["같음"] for counter in groups.values()),
            "묶음별": {group: dict(counter) for group, counter in groups.items()},
            "어긋남": problems[:50], "어긋난_수": len(problems), "통과": not problems}


def expected_field(x4: float | None, grade_without_goods: str | None, floor: float) -> dict:
    """정의 — 업종 겹침(x4)과 업종 없이 본 등급에서 후보의 cross_goods 가 가져야 할 값. 겹침을
    모르면(x4 None) 다름이 아니라 모름(differs None)이고 표시하지 않는다. 겹치면(x4 ≥ 결합 하한)
    업종 없이 본 등급을 싣지 않는다."""
    if x4 is None:
        return {"differs": None, "grade_without_goods": None, "flagged": False}
    if float(x4) >= floor:
        return {"differs": False, "grade_without_goods": None, "flagged": False}
    return {"differs": True, "grade_without_goods": grade_without_goods,
            "flagged": GRADES.index(grade_without_goods) >= REVIEW}


def field_problems(response: dict, has_goods: bool, floor: float) -> list[str]:
    """응답 하나가 스스로 앞뒤가 맞는가(업종 없이 본 등급 자체는 run 이 엔진으로 따로 확인한다)."""
    problems: list[str] = []
    more = response.get(MORE_FIELD)
    shown = response["candidates"]
    if not has_goods:
        if more is not None:
            problems.append("업종 없는 질의에 cross_goods_more 가 있음")
        if any(CANDIDATE_FIELD in candidate for candidate in shown):
            problems.append("업종 없는 질의의 후보에 cross_goods 가 있음")
        return problems
    if more is None:
        return ["업종 있는 질의에 cross_goods_more 가 없음"]
    for candidate in [*shown, *more["candidates"]]:
        field = candidate.get(CANDIDATE_FIELD)
        if field is None:
            problems.append(f"{candidate['id']}: cross_goods 가 없음")
            continue
        x4 = candidate["axes"]["x4"]
        if x4 != candidate["goods"]["jaccard"]:
            problems.append(f"{candidate['id']}: axes.x4 와 goods.jaccard 가 다름")
        grade = field["grade_without_goods"]
        if x4 is not None and float(x4) < floor and grade not in GRADES:
            problems.append(f"{candidate['id']}: 업종이 다른데 업종 없이 본 등급이 없음")
            continue
        if field != expected_field(x4, grade, floor):
            problems.append(f"{candidate['id']}: cross_goods 가 정의와 다름 {field}")
        if field["differs"] and GRADES.index(candidate["risk"]["grade"]) > GRADES.index(grade):
            problems.append(f"{candidate['id']}: 화면 등급이 업종 없이 본 등급보다 높음")
    listed = more["candidates"]
    if len(listed) != min(more["count"], MORE_LIMIT):
        problems.append("cross_goods_more 의 후보 수가 count·상한과 다름")
    if any(not candidate.get(CANDIDATE_FIELD, {}).get("flagged") for candidate in listed):
        problems.append("cross_goods_more 에 정의에 맞지 않는 후보가 있음")
    if {candidate["id"] for candidate in listed} & {candidate["id"] for candidate in shown}:
        problems.append("cross_goods_more 의 후보가 처음 보이는 범위에도 있음")
    ranks = [(-GRADES.index(c[CANDIDATE_FIELD]["grade_without_goods"]), "famous_brand" not in c)
             for c in listed if c.get(CANDIDATE_FIELD, {}).get("grade_without_goods") in GRADES]
    if [rank[0] for rank in ranks] != sorted(rank[0] for rank in ranks):
        problems.append("cross_goods_more 가 업종 없이 본 등급 순서가 아님")
    elif ranks != sorted(ranks):
        problems.append("cross_goods_more 의 같은 등급 안에서 유명 상표가 먼저가 아님")
    return problems


def flagged(candidate: dict) -> bool:
    return bool((candidate.get(CANDIDATE_FIELD) or {}).get("flagged"))


def overall_line(response: dict) -> bool:
    """전체 등급 옆 한 줄이 보이는가(화면 규칙 — frontend/lib/crossGoods.ts 와 같다): 가장 위 후보가
    정의에 맞는 후보이고, 유명 상표 바닥이 전체 등급을 정한 것이 아닐 때."""
    shown = response["candidates"]
    return bool(shown) and flagged(shown[0]) and not response["overall"].get("famous_floor")


def folded_section(response: dict) -> int:
    """목록 아래 접힌 칸에 적히는 수 — 처음 보이는 범위 밖의 정의에 맞는 후보(없으면 0: 칸 없음)."""
    return int((response.get(MORE_FIELD) or {}).get("count", 0))


def expected_more(pool_fields: list[tuple[str, dict, bool]], top_k: int = TOP_K) -> dict:
    """후보 풀(정렬된 순서의 (출원번호, cross_goods, 유명 상표 등록부의 표장인가))에서 범위 밖 칸을
    다시 고른다 — 처음 보이는 범위(앞 top_k) 밖의 정의에 맞는 후보를 업종 없이 본 등급이 높은
    것부터, 같은 등급이면 유명 상표 등록부의 표장 먼저, 그다음 풀의 순서로."""
    outside = [item for item in pool_fields[top_k:] if item[1]["flagged"]]
    ordered = sorted(outside, key=lambda item: (
        -GRADES.index(item[1]["grade_without_goods"]), not item[2]))
    return {"count": len(outside), "ids": [item[0] for item in ordered[:MORE_LIMIT]]}


def numbers(values: list[int]) -> dict:
    """질의당 개수의 요약(표시가 하나라도 있는 질의만 넘긴다)."""
    if not values:
        return {"질의": 0}
    return {"질의": len(values), "합": sum(values), "평균": round(statistics.mean(values), 2),
            "중앙값": statistics.median(values), "최대": max(values)}


# ---- 질의 목록 -----------------------------------------------------------------------------------

def sample_a_path(key: str) -> str:
    """표본 A 이미지 열쇠("A:<심판번호>:<this|target>") → 저장소 기준 경로."""
    _, number, side = key.split(":")
    return f"ml/data/trials/images/{number}/{side}.png"


def build_queries() -> list[dict]:
    """질의 목록 — 이미지는 저장소 기준 경로로 적는다(두 트리가 같은 파일을 읽게). 표본 A 는 엔진을
    띄워 고른다(사진 판정으로 거르는 표본이라 — nameless_search_thresholds.screen_a)."""
    if str(ML_ROOT) not in sys.path:
        sys.path[:0] = [str(ML_ROOT), str(REPO_ROOT)]
    from src.axes import goods_map as gm
    from src.model import risk_model as rm

    from scripts import named_shared_threshold as second
    from scripts import nameless_shared_threshold as ns

    presets = gm.load_business_presets(gm.load_goods_map())
    rows: list[dict] = []

    def add(group: str, label: str, **inputs) -> None:
        rows.append({"묶음": group, "질의": f"{group} | {label}",
                     **{k: v for k, v in inputs.items() if v is not None}})

    for key, title, spec in second.SCENARIOS:
        add("시나리오", f"{key} {title}", name=spec.get("name"),
            image=second.SCENARIO_IMAGES[spec["image"]] if "image" in spec else None,
            goods_codes=list(second.SCENARIO_GOODS[spec["goods"]]) if "goods" in spec else None,
            type_override=spec.get("override"))
    control = json.loads(CONTROL.read_text(encoding="utf-8"))["대조군"]["이름"]
    for item in control["확인용"]:
        for label, with_image, with_goods in CONTROL_MODES:
            add("대조군 확인용", f"{item['이름']} · {label}", name=item["이름"],
                image=sample_a_path(item["이미지"]) if with_image else None,
                goods_codes=sorted(item["유사군"]) if with_goods else None)
    context = ns._context(rm.DEFAULT_MODEL_PATH)  # noqa: SLF001 — 표본 A(184질의)
    for query in context["A"]:
        image = sample_a_path(query.key)
        if (REPO_ROOT / image).resolve() != query.path.resolve():
            raise RuntimeError(f"표본 A 이미지 경로가 다릅니다: {query.key} {query.path}")
        goods = sorted(query.goods) or None
        add("표본 A", f"{query.key} 이름+이미지" + ("+업종" if goods else ""), name=query.name,
            image=image, goods_codes=goods)
    for query in context["A"]:
        if query.goods:
            add("표본 A 업종 있는 질의(이름 없이)", f"{query.key} 이미지+업종",
                image=sample_a_path(query.key), goods_codes=sorted(query.goods))
    for name, preset_id in EXAMPLES:
        preset = presets.get(preset_id)
        add("예시", f"{name} + {preset_id}", name=name, goods_codes=sorted(
            {code for good in preset.goods for code in good.similarity_codes}))
    missing = [row["image"] for row in rows
               if row.get("image") and not (REPO_ROOT / row["image"]).is_file()]
    if missing:
        raise FileNotFoundError(f"질의 이미지가 없습니다: {missing[:3]} … {len(missing)}개")
    return rows


def command_queries(args) -> int:
    rows = build_queries()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    counts = collections.Counter(row["묶음"] for row in rows)
    print(f"질의 {len(rows)}: {dict(counts)} → {args.out}")
    return 0


# ---- 엔진 띄우기(주어진 트리의 코드로) -----------------------------------------------------------

def load_tree(root: Path):
    """root 트리의 엔진을 띄운다 — (ms, 이미지 디코더). 이 프로세스에서 한 번만."""
    root = root.resolve()
    sys.path[:0] = [str(root / "ml"), str(root)]
    from backend.src.core import engine  # noqa: I001  (engine 이 torch 를 faiss 보다 먼저 올린다)
    from backend.src.core import multi_search as ms

    from scripts import nameless_search_thresholds as nst

    for module in (engine, ms, nst):
        if not Path(module.__file__).resolve().is_relative_to(root):
            raise RuntimeError(
                f"{module.__name__} 이 {root} 밖에서 들어왔습니다: {module.__file__}")
    engine.load_all()
    if ms.state.model is None:
        raise RuntimeError(f"통합 모델이 준비되지 않았습니다: {ms.state.error}")
    service, _ = nst.decoders()
    return ms, service


def iter_queries(ms, service, queries: list[dict]):
    """질의마다 (질의 줄, 엔진 입력, 응답 dict) — 응답은 top_k 5, elapsed_ms 는 뺀다. 시나리오 S5 의
    이름은 S3 응답의 OCR 제안 이름."""
    images: dict[str, object] = {}
    suggested = None
    started = time.perf_counter()
    for index, row in enumerate(queries):
        inputs = {key: row[key] for key in ("name", "goods_codes", "type_override") if key in row}
        if inputs.get("name") == "@S3":
            inputs["name"] = suggested
        if "image" in row:
            if row["image"] not in images:
                images[row["image"]] = service((REPO_ROOT / row["image"]).read_bytes())
            inputs["image"] = images[row["image"]]
        data = ms.multi_search(**inputs, top_k=TOP_K).to_dict()
        if row["질의"].startswith("시나리오 | S3 "):
            suggested = data["overall"]["query_type"].get("suggested_name")
        data["meta"].pop("elapsed_ms")
        yield row, inputs, data
        if (index + 1) % 100 == 0:
            print(f"  {index + 1}/{len(queries)} ({time.perf_counter() - started:.0f}초)",
                  flush=True)


# ---- (가) 덤프·견주기 ----------------------------------------------------------------------------

def command_dump(args) -> int:
    queries = json.loads(args.queries.read_text(encoding="utf-8"))[:args.limit]
    started = time.perf_counter()
    ms, service = load_tree(args.root)
    responses = {row["질의"]: data for row, _, data in iter_queries(ms, service, queries)}
    text = json.dumps(responses, ensure_ascii=False, sort_keys=False)
    out = {"때": _now(), "트리": str(args.root.resolve()),
           "모델": ms.state.model["version"], "질의": len(responses),
           "새_필드가_있는_응답": sum(has_new_fields(r) for r in responses.values()),
           "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
           "걸린_시간_s": round(time.perf_counter() - started, 1), "응답": responses}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with _open(args.out, "w") as handle:
        json.dump(out, handle, ensure_ascii=False)
    print(json.dumps({k: v for k, v in out.items() if k != "응답"}, ensure_ascii=False))
    return 0


def command_compare(args) -> int:
    with _open(args.before, "r") as handle:
        before = json.load(handle)
    with _open(args.after, "r") as handle:
        after = json.load(handle)
    result = compare_dumps(before, after)
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "어긋남"}, ensure_ascii=False,
                     indent=1))
    for problem in result["어긋남"][:10]:
        print("  어긋남:", json.dumps(problem, ensure_ascii=False))
    return 0 if result["통과"] else EXIT_STOP


# ---- (나)(다) 엔진으로 ---------------------------------------------------------------------------

def hidden_goods_grade(ms, record, ctx, *, image_floors: bool = True) -> str:
    """업종 축(x4)만 가리고 엔진의 score_record 를 다시 부른 등급 — 응답에 실린 "업종 없이 본 등급"
    을 엔진의 채점 경로로 따로 구한다(엔진이 싣는 값을 만드는 함수를 부르지 않는다). 이름 있는
    판단은 축을 그대로 두고(식별력 맥락도 그대로) x4 만 없앤다. 이름 없는 판단은 질의의 업종을
    없앤다(그 경로에서 업종은 x4 에만 쓰인다). image_floors=False 면 이미지만 판단과의 비교(logo_
    floor·nameless_floor)를 끈 것 — 업종 상한이 견주는 짝 판단만의 등급."""
    if not image_floors:
        ctx = dataclasses.replace(ctx, logo_floor=False, nameless_floor=False)
    if ctx.name and record.title:
        original = ms.compute_pair_axes
        ms.compute_pair_axes = lambda *a, **k: dataclasses.replace(original(*a, **k), x4=None)
        try:
            return ms.score_record(record, ctx).grade
        finally:
            ms.compute_pair_axes = original
    return ms.score_record(record, dataclasses.replace(ctx, goods=None)).grade


def check_query(ms, inputs: dict, response: dict, floor: float) -> dict:
    """질의 하나 — 풀 전체에서 표시가 정의와 같은가, 범위 밖 칸이 풀에서 다시 고른 것과 같은가."""
    has_goods = bool(inputs.get("goods_codes"))
    problems = field_problems(response, has_goods, floor)
    pooled = ms.search_pool(**inputs)
    famous = getattr(ms.state.famous, "brand_of_mark", {}) if ms.state.famous else {}
    out = {"업종_있음": has_goods, "풀": len(pooled.candidates), "문제": problems,
           "표시": [], "모름": 0, "다름": 0}
    if not has_goods:
        carried = sum(candidate.cross_goods is not None for candidate in pooled.candidates)
        if carried:
            problems.append(f"업종 없는 질의의 풀 후보 {carried}건에 cross_goods 가 있음")
        return out
    ctx = ms.make_context(pooled.query_name, pooled.goods, pooled.embedding, pooled.query_type,
                          pooled.x3_on)
    fields: list[tuple[str, dict, bool]] = []
    for index, candidate in enumerate(pooled.candidates):
        field = candidate.cross_goods
        x4 = candidate.axes["x4"]
        record = ms.state.by_appno[candidate.id]
        if field is None:
            problems.append(f"{candidate.id}: 풀 후보에 cross_goods 가 없음")
            continue
        fields.append((candidate.id, field, candidate.id in famous))
        if x4 is None:
            out["모름"] += 1
            if record.goods:
                problems.append(f"{candidate.id}: 유사군이 있는데 겹침이 없음(None)")
        independent = None
        if x4 is not None and float(x4) < floor:
            out["다름"] += 1
            independent = hidden_goods_grade(ms, record, ctx)
        want = expected_field(x4, independent, floor)
        if field != want:
            problems.append(f"{candidate.id}: 엔진 {field} ≠ 정의 {want}")
        if field["differs"] and GRADES.index(candidate.grade) > GRADES.index(
                field["grade_without_goods"]):
            problems.append(f"{candidate.id}: 등급이 업종 없이 본 등급보다 높음")
        if field["flagged"]:
            pair_only = hidden_goods_grade(ms, record, ctx, image_floors=False)
            out["표시"].append({
                "순위": index + 1, "id": candidate.id, "상표명": candidate.title,
                "등급": candidate.grade, "업종_없이": field["grade_without_goods"],
                "짝_판단만": pair_only, "유명_상표": famous.get(candidate.id),
                "겹침": x4, "규칙": list(candidate.rule_triggers)})
    shown_ids = [candidate["id"] for candidate in response["candidates"]]
    if shown_ids != [candidate.id for candidate in pooled.candidates[:len(shown_ids)]]:
        problems.append("응답의 후보가 풀의 앞과 다름")
    for candidate, pool_candidate in zip(response["candidates"], pooled.candidates):
        if candidate.get(CANDIDATE_FIELD) != pool_candidate.cross_goods:
            problems.append(f"{candidate['id']}: 응답과 풀의 cross_goods 가 다름")
    want_more = expected_more(fields, len(shown_ids))
    more = response.get(MORE_FIELD) or {"count": None, "candidates": []}
    if (more["count"] != want_more["count"]
            or [candidate["id"] for candidate in more["candidates"]] != want_more["ids"]):
        problems.append(f"cross_goods_more 가 풀에서 다시 고른 것과 다름: {more['count']} / "
                        f"{want_more}")
    for candidate in more["candidates"]:
        if candidate.get("famous_brand") != famous.get(candidate["id"]):
            problems.append(f"{candidate['id']}: 범위 밖 후보의 famous_brand 가 등록부와 다름")
    return out


def summarize(items: list[tuple[dict, dict, dict]], top_k: int = TOP_K) -> dict:
    """(다) 한 묶음 — (질의 줄, 응답, check_query 결과) 목록."""
    with_flags = [item for item in items if item[2]["표시"]]
    per_query = [len(check["표시"]) for _, _, check in with_flags]
    shown = [sum(1 for f in check["표시"] if f["순위"] <= top_k) for _, _, check in items]
    outside = [sum(1 for f in check["표시"] if f["순위"] > top_k) for _, _, check in items]
    flags = [flag for _, _, check in items for flag in check["표시"]]
    out_flags = [flag for flag in flags if flag["순위"] > top_k]
    listed = sum(len((data.get(MORE_FIELD) or {}).get("candidates", [])) for _, data, _ in items)
    left_out = [(data, flag) for _, data, check in items for flag in check["표시"]
                if flag["순위"] > top_k and flag["유명_상표"] and flag["id"] not in {
                    candidate["id"]
                    for candidate in (data.get(MORE_FIELD) or {}).get("candidates", [])}]
    return {
        "질의": len(items),
        "풀_후보": sum(check["풀"] for _, _, check in items),
        "업종이_다른_후보": sum(check["다름"] for _, _, check in items),
        "업종_겹침을_모르는_후보": sum(check["모름"] for _, _, check in items),
        "표시가_붙는_질의(풀_전체)": len(with_flags),
        "표시가_붙는_후보(풀_전체)": len(flags),
        "질의당_개수(표시가_있는_질의)": numbers(per_query),
        "처음_보이는_범위(앞_5)_안": {
            "질의": sum(1 for count in shown if count), "후보": sum(shown),
            "그_가운데_유명_상표": sum(
                1 for flag in flags if flag["순위"] <= top_k and flag["유명_상표"])},
        "처음_보이는_범위_밖": {
            "질의(접힌_칸이_생김)": sum(1 for count in outside if count), "후보": sum(outside),
            "질의당_개수": numbers([count for count in outside if count]),
            "다섯을_넘는_질의": sum(1 for count in outside if count > MORE_LIMIT),
            "그_가운데_유명_상표": sum(1 for flag in out_flags if flag["유명_상표"]),
            "유명_상표인데_칸의_다섯_안에_못_든_후보": len(left_out),
            "칸에_실린_후보": listed,
            "유명_상표가_있는_질의": sum(
                1 for _, _, check in items
                if any(f["순위"] > top_k and f["유명_상표"] for f in check["표시"]))},
        "전체_등급_옆_한_줄이_뜨는_질의": sum(overall_line(data) for _, data, _ in items),
        "표시된_후보의_화면_등급": dict(collections.Counter(flag["등급"] for flag in flags)),
        "표시된_후보의_업종_없이_본_등급": dict(
            collections.Counter(flag["업종_없이"] for flag in flags)),
        "짝_판단만으로는_표시가_아닌_후보(이미지만_판단으로_표시)": sum(
            1 for flag in flags if GRADES.index(flag["짝_판단만"]) < REVIEW),
    }


def describe(data: dict, check: dict) -> dict:
    """시연·예시 하나 — 앞 5 의 표시와 전체 등급 옆 한 줄."""
    return {
        "전체_등급": data["overall"]["grade"], "전체_위험도": data["overall"]["prob"],
        "유명_상표_바닥이_등급을_정함": data["overall"].get("famous_floor"),
        "앞_5": [{"상표명": c["title"], "등급": c["risk"]["grade"], "겹침": c["axes"]["x4"],
                 "업종이_다름": (c.get(CANDIDATE_FIELD) or {}).get("differs"),
                 "업종_없이_본_등급": (c.get(CANDIDATE_FIELD) or {}).get("grade_without_goods"),
                 "표시": flagged(c), "유명_상표": c.get("famous_brand")}
                for c in data["candidates"]],
        "앞_5_의_표시": sum(flagged(c) for c in data["candidates"]),
        "전체_등급_옆_한_줄": overall_line(data),
        "접힌_칸": folded_section(data),
        "접힌_칸의_후보": [{"상표명": c["title"], "등급": c["risk"]["grade"],
                         "업종_없이_본_등급": c[CANDIDATE_FIELD]["grade_without_goods"],
                         "유명_상표": c.get("famous_brand")}
                        for c in (data.get(MORE_FIELD) or {}).get("candidates", [])],
        "풀의_표시": len(check["표시"]),
    }


def command_run(args) -> int:
    queries = json.loads(args.queries.read_text(encoding="utf-8"))[:args.limit]
    started = time.perf_counter()
    ms, service = load_tree(REPO_ROOT)
    floor = ms.goods_floor_value(ms.state.model)
    rows: list[tuple[dict, dict, dict]] = [
        (row, data, check_query(ms, inputs, data, floor))
        for row, inputs, data in iter_queries(ms, service, queries)]
    by_group: dict[str, list] = collections.defaultdict(list)
    for item in rows:
        row = item[0]
        mode = row["질의"].rsplit(" · ", 1)[-1] if row["묶음"] == "대조군 확인용" else ""
        by_group[f"{row['묶음']}{' · ' + mode if mode else ''}"].append(item)
    sample_a = [item for item in by_group.get("표본 A", []) if item[2]["업종_있음"]]
    report = {
        "표본 A 업종 있는 질의 · 이름+이미지+업종": sample_a,
        "표본 A 업종 있는 질의 · 이름 없이 이미지+업종": by_group.get(
            "표본 A 업종 있는 질의(이름 없이)", []),
        "지어낸 이름 대조군 확인용 · 이름+업종": by_group.get("대조군 확인용 · 이름+업종", []),
        "지어낸 이름 대조군 확인용 · 이름+이미지+업종": by_group.get(
            "대조군 확인용 · 이름+이미지+업종", []),
    }
    demo = {}
    for key, label in DEMO:
        match = next((item for item in rows if item[0]["질의"].startswith(f"시나리오 | {key} ")),
                     None)
        if match is not None:
            demo[label] = describe(match[1], match[2])
    examples = {row["질의"].split(" | ", 1)[1]: describe(data, check)
                for row, data, check in rows if row["묶음"] == "예시"}
    with_goods = [item for item in rows if item[2]["업종_있음"]]
    without = [item for item in rows if not item[2]["업종_있음"]]
    problems = [{"질의": row["질의"], "문제": check["문제"][:5]}
                for row, _, check in rows if check["문제"]]
    most = sorted(((len(check["표시"]), row["질의"]) for row, _, check in sample_a),
                  reverse=True)[:10]
    out = {
        "때": _now(), "모델": ms.state.model["version"],
        "결합_하한": floor,
        "DB": {"index_size": len(ms.state.records),
               "유사군이_없는_등록상표": sum(1 for record in ms.state.records if not record.goods)},
        "질의": {"전체": len(rows), "업종_있음": len(with_goods), "업종_없음": len(without)},
        "(나)_표시가_정의와_같은가": {
            "확인한_풀_후보": sum(check["풀"] for _, _, check in with_goods),
            "업종이_다른_후보(업종_없이_본_등급을_따로_구함)": sum(
                check["다름"] for _, _, check in with_goods),
            "업종_겹침을_모르는_후보": sum(check["모름"] for _, _, check in with_goods),
            "표시된_후보": sum(len(check["표시"]) for _, _, check in with_goods),
            "업종_없는_질의의_표시": sum(
                has_new_fields(data) for _, data, _ in without),
            "어긋난_질의": len(problems)},
        "(다)_보고": {label: summarize(items) for label, items in report.items() if items},
        "(다)_시연_넷": demo,
        "(다)_예시": examples,
        "(다)_표시가_많은_표본_A_질의": most,
        "어긋남": problems[:50],
        "통과": not problems,
        "걸린_시간_s": round(time.perf_counter() - started, 1),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("질의", "(나)_표시가_정의와_같은가", "통과",
                                          "걸린_시간_s")}, ensure_ascii=False, indent=1))
    print(f"→ {args.out}")
    return 0 if out["통과"] else EXIT_STOP


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    queries = commands.add_parser("queries", help="질의 목록을 만든다(엔진을 띄운다)")
    queries.add_argument("--out", type=Path, default=QUERIES)
    queries.set_defaults(run=command_queries)
    dump = commands.add_parser("dump", help="한 트리의 엔진으로 질의를 돌려 응답을 덤프한다")
    dump.add_argument("--root", type=Path, required=True)
    dump.add_argument("--queries", type=Path, default=QUERIES)
    dump.add_argument("--out", type=Path, required=True)
    dump.add_argument("--limit", type=int, default=None)
    dump.set_defaults(run=command_dump)
    compare = commands.add_parser("compare", help="두 덤프를 새 선택 필드만 빼고 견준다")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.add_argument("--out", type=Path, default=None)
    compare.set_defaults(run=command_compare)
    run = commands.add_parser("run", help="표시가 정의와 같은지 확인하고 수를 센다")
    run.add_argument("--queries", type=Path, default=QUERIES)
    run.add_argument("--out", type=Path, default=RESULTS)
    run.add_argument("--limit", type=int, default=None)
    run.set_defaults(run=command_run)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
