"""질의 이름의 낱말별 식별력(설명적 이름 안내)의 확인 — 식별력 설계 §9, API 계약 v2 §2-7.

응답의 선택 필드 name_words 는 새 판정이 아니라 엔진이 요부를 정할 때 쓰는 식별력 판정을 실은
것이다. 이 스크립트는 그것을 실제 엔진으로 확인한다(KIPRIS 호출 0, 실제 CLIP·OCR·관념 모델).

    (가) 후보 목록·전체 등급 불변 — 고치기 전 커밋의 엔진과 지금 엔진으로 같은 질의를 돌려 응답을
         글자까지 견준다(새 선택 필드 name_words 만 빼고). `dump` 를 두 트리에 한 번씩, `compare`.
    (나) 응답의 낱말별 판정 = 엔진이 요부를 정할 때 쓴 판정 — ① 식별력 판정 함수가 질의의 이름·
         업종에 내는 값과 같은가(다르면 그 낱말을 엔진이 어느 후보와 견줄 때 요부 후보로 쓴
         경우뿐인가) ② 응답이 식별력 없다고 한 낱말이 어느 후보(풀 전체)와 견줄 때도 요부 후보가
         아닌가.
    (다) 기대 넷 — 맛있는 커피 전문점·커피·블루커피·스타벅스(모두 카페 세트).
    (라) 보고 — 설명적 이름 표본 200·지어낸 이름 대조군 200 에서 큰 안내·작은 안내의 비율, 분류별
         낱말 수, "그 밖"으로 간 사유 코드, 예시 셋과 시연 넷의 맨 위 영역, "빼고 견줬다"·"이름
         전체를 견줬다"가 보이는 후보 모두에서 사실인 질의의 비율.

화면이 고르는 안내(frontend/lib/descriptiveNotice.ts 와 같은 규칙): 유명 상표 배너가 이름 쪽의 강한
일치(이름·이미지 속 글자)로 뜨면 안내 없음. 그 밖에는 — 모든 낱말이 식별력 없는 말이면 큰 안내, 다만
유명 상표 배너(약한 일치·로고로만 강한 일치)가 있거나 "흔히 쓰는 말"이 아닌 분류의 낱말이 하나도
없으면 작은 안내, 일부만이면 "빼고 비교했어요"가 보이는 후보 모두에서 사실일 때만 작은 안내.

질의: 시나리오 16종 · 지어낸 이름 대조군 확인용 100 × 네 방식(400검색) · 대조군 기준용 100 × 이름만·
이름+업종 · 설명적 이름 표본(R-P0-2 의 200개) × 이름만·이름+업종 · 예시 일곱.

    ml/venv/bin/python ml/scripts/name_words_check.py queries            # 질의 목록(엔진 없음)
    ml/venv/bin/python ml/scripts/name_words_check.py dump --root <트리> --out <파일.json.gz>
    ml/venv/bin/python ml/scripts/name_words_check.py compare <전> <후>   # (가) — 다르면 종료 3
    ml/venv/bin/python ml/scripts/name_words_check.py run                # (나)(다)(라) — 어긋나면 3

`dump --root` 는 그 트리의 backend·ml 코드를 불러 쓴다(이 파일의 다른 코드는 쓰지 않는다) — 고치기
전 커밋은 `git archive <커밋> | tar -x -C <폴더>` 로 풀고 `ml/data` 를 지금 데이터로 이어 둔다.
결과는 ml/data/trials/name_words_check*.json(비공개 데이터 — 커밋하지 않는다).
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
TRIALS = ML_ROOT / "data" / "trials"
QUERIES = TRIALS / "name_words_check_queries.json"
RESULTS = TRIALS / "name_words_check.json"
DESCRIPTIVE = TRIALS / "weak_run_adjacent_searches.json.gz"  # R-P0-2 의 설명적 이름 200(설계 §7-10)
CONTROL = TRIALS / "named_search_thresholds_control.json"  # 지어낸 이름 대조군(설계 §7-6)
EXIT_STOP = 3
TOP_K = 5  # 화면 기본

CONTROL_MODES = (("이름만", False, False), ("이름+업종", False, True),
                 ("이름+이미지", True, False), ("이름+이미지+업종", True, True))
NAME_MODES = (("이름만", False), ("이름+업종", True))
# (다) 기대 — (이름, 업종 세트, 기대하는 안내)
EXPECTED = (
    ("맛있는 커피 전문점", "cafe", "큰 안내"),
    ("커피", "cafe", "큰 안내"),
    ("블루커피", "cafe", "작은 안내(일부)"),
    ("스타벅스", "cafe", "없음"),
)
# (라) 맨 위 영역을 볼 예시 — 음식점은 업종 세트 "식당(한식)", 분식은 "분식집"
EXAMPLES = (
    ("텍사스 BBQ", "korean_restaurant"),
    ("김가네", "bunsik"),
    ("서울 식당", "korean_restaurant"),
)
# 시연 넷 — 시나리오 목록의 열쇠
DEMO = (("F2", "크린토피야 + 세탁"), ("F1", "스타벅수 + 카페"), ("F3", "파리바게트 + 빵집"),
        ("S1", "블루커피 + 카페"))
NEW_FIELD = "name_words"
NOTICE_BIG = "큰 안내"
NOTICE_ALL_SMALL_FAMOUS = "작은 안내(모두 — 유명 상표 배너 있음)"
NOTICE_ALL_SMALL_COMMON = "작은 안내(모두 — 흔히 쓰는 말뿐)"
NOTICE_SOME = "작은 안내(일부)"
NOTICE_SOME_HIDDEN = "없음(일부 — 빼고 견줬다가 보이는 후보 모두에서 사실이 아님)"
NOTICE_FAMOUS_HIDDEN = "없음(유명 상표 배너가 이름 쪽의 강한 일치 — 안내를 그리지 않음)"
NOTICE_NONE = "없음"
SMALL_NOTICES = (NOTICE_ALL_SMALL_FAMOUS, NOTICE_ALL_SMALL_COMMON, NOTICE_SOME)
HIDDEN_NOTICES = (NOTICE_NONE, NOTICE_SOME_HIDDEN, NOTICE_FAMOUS_HIDDEN)  # 화면에 안내가 없다
FAMOUS_BANNER_LEVELS = ("강함", "약함")  # 이 종류의 배너가 있으면 큰 안내 대신 작은 안내
FAMOUS_STRONG, FAMOUS_BASIS_LOGO = "강함", "로고"
BANNER_NONE, BANNER_SHOWN, BANNER_NAME_STRONG = "none", "banner", "name-strong"
# 큰 안내를 띄우는 분류 — "흔히 쓰는 말"(통계로 약해진 낱말)과 "그 밖"은 들지 않는다
BIG_NOTICE_CATEGORIES = frozenset({"상품 이름", "성질·품질", "지역 이름", "흔한 성·이름",
                                   "짧고 흔한 글자"})


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")


def _open(path: Path, mode: str):
    return gzip.open(path, mode + "t", encoding="utf-8") if path.suffix == ".gz" else open(
        path, mode, encoding="utf-8")


# ---- 화면이 고르는 안내(frontend/lib/descriptiveNotice.ts 와 같은 규칙) --------------------------

def famous_level(response: dict) -> str | None:
    famous = response.get("famous") or {}
    matches = famous.get("matches") or []
    return matches[0]["level"] if famous.get("status") == "checked" and matches else None


def famous_banner_state(response: dict) -> str:
    """맨 위 유명 상표 배너가 설명적 이름 안내에 주는 영향(프런트 famousBannerState 와 같은 규칙) —
    강함·약함 배너가 없으면 "none", 배너가 그리는 일치(앞의 둘) 가운데 로고가 아닌 근거(이름·이미지
    속 글자)의 강한 일치가 있으면 "name-strong"(안내를 그리지 않는다), 그 밖에는 "banner"."""
    if famous_level(response) not in FAMOUS_BANNER_LEVELS:
        return BANNER_NONE
    matches = response["famous"]["matches"][:2]
    strong = any(m["level"] == FAMOUS_STRONG and m["basis"] != FAMOUS_BASIS_LOGO for m in matches)
    return BANNER_NAME_STRONG if strong else BANNER_SHOWN


def removed_as_said(response: dict) -> bool:
    """작은 안내(일부)의 "빼고 비교했어요"가 보이는 후보 모두에서 사실인가 — 이름을 견준 후보
    (상표명이 있는 후보)마다 실린 식별력 없는 낱말이 모두 뺀 낱말(removed 의 side 가 query·both)에
    있고, 싣지 않은 식별력 없는 낱말 수만큼 질의 쪽에서 뺀 낱말이 더 있다. 이름을 견준 후보가 없으면
    거짓."""
    words = response.get(NEW_FIELD) or {}
    weak = {w["word"] for w in words.get("words", []) if not w["distinctive"]}
    named = [c for c in response["candidates"] if c["title"]]
    if not named:
        return False
    for candidate in named:
        removed = {item["token"] for item in candidate["salient"]["removed"]
                   if item["side"] != "candidate"}
        if not weak <= removed or len(removed) - len(weak) < words.get("more_generic", 0):
            return False
    return True


def notice_kind(response: dict) -> str:
    """응답으로 화면이 그릴 설명적 이름 안내의 종류."""
    words = response.get(NEW_FIELD) or {}
    generic = words.get("generic")
    banner = famous_banner_state(response)
    if generic in ("all", "some") and banner == BANNER_NAME_STRONG:
        return NOTICE_FAMOUS_HIDDEN
    if generic == "all":
        if banner == BANNER_SHOWN:
            return NOTICE_ALL_SMALL_FAMOUS
        decisive = any(not w["distinctive"] and w["category"] in BIG_NOTICE_CATEGORIES
                       for w in words["words"])
        return NOTICE_BIG if decisive else NOTICE_ALL_SMALL_COMMON
    if generic == "some":
        return NOTICE_SOME if removed_as_said(response) else NOTICE_SOME_HIDDEN
    return NOTICE_NONE


def top_area(response: dict) -> list[str]:
    """맨 위 안내 영역에 그려지는 것(위에서부터) — ① 유명 상표 배너(강함·약함) ② 설명적 이름 안내
    ③ 유명 상표의 설명적 사용 안내. 배너가 이름 쪽의 강한 일치로 뜨면 ② 는 없다."""
    level, kind = famous_level(response), notice_kind(response)
    brand = ((response.get("famous") or {}).get("matches") or [{}])[0].get("brand")
    banner = f"유명 상표 배너({level} — {brand})" if level else None
    shown = kind not in HIDDEN_NOTICES
    notice = f"설명적 이름 안내({kind})" if shown else None
    if (response.get("famous") or {}).get("status") == "unavailable":
        banner = "유명 상표 확인을 하지 못했어요(한 줄)"
    ordered = [notice, banner] if level == "설명적 사용" else [banner, notice]
    return [item for item in ordered if item]


def whole_name_line(response: dict) -> bool:
    """(라) "이름 전체를 견준 결과" 한 줄이 보이는가 — 모든 낱말이 식별력 없는 말이고, 보이는 후보
    가운데 질의의 낱말이 빠진 것이 없을 때. 유명 상표 배너가 이름 쪽의 강한 일치로 뜨면 안내와 함께
    이 줄도 그리지 않는다."""
    if (response.get(NEW_FIELD) or {}).get("generic") != "all":
        return False
    if famous_banner_state(response) == BANNER_NAME_STRONG:
        return False
    return all(item["side"] == "candidate" for candidate in response["candidates"]
               for item in candidate["salient"]["removed"])


# ---- (가) 견주기 ---------------------------------------------------------------------------------

def strip_new_field(response: dict) -> dict:
    return {key: value for key, value in response.items() if key != NEW_FIELD}


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
        if NEW_FIELD in old:
            problems.append({"질의": key, "문제": "전 덤프에 새 필드가 있음"})
        same = json.dumps(old, ensure_ascii=False) == json.dumps(
            strip_new_field(new), ensure_ascii=False)
        groups[group]["같음"] += same
        groups[group]["새_필드_있음"] += NEW_FIELD in new
        if not same:
            differing = sorted(k for k in set(old) | set(new)
                               if k != NEW_FIELD and old.get(k) != new.get(k))
            problems.append({"질의": key, "문제": "응답이 다름", "다른_키": differing})
    total = sum(counter["질의"] for counter in groups.values())
    return {"전": {k: before[k] for k in ("트리", "모델", "sha256") if k in before},
            "후": {k: after[k] for k in ("트리", "모델", "sha256") if k in after},
            "질의": total, "같음": sum(counter["같음"] for counter in groups.values()),
            "묶음별": {group: dict(counter) for group, counter in groups.items()},
            "어긋남": problems[:50], "어긋난_수": len(problems), "통과": not problems}


# ---- 질의 목록 -----------------------------------------------------------------------------------

def sample_a_path(key: str) -> str:
    """표본 A 이미지 열쇠("A:<심판번호>:<this|target>") → 저장소 기준 경로."""
    _, number, side = key.split(":")
    return f"ml/data/trials/images/{number}/{side}.png"


def build_queries() -> list[dict]:
    """질의 목록 — 이미지는 저장소 기준 경로로 적는다(두 트리가 같은 파일을 읽게)."""
    if str(ML_ROOT) not in sys.path:
        sys.path[:0] = [str(ML_ROOT), str(REPO_ROOT)]
    from src.axes import goods_map as gm

    from scripts import named_shared_threshold as second

    presets = gm.load_business_presets(gm.load_goods_map())

    def codes(preset_id: str) -> list[str]:
        preset = presets.get(preset_id)
        return sorted({code for good in preset.goods for code in good.similarity_codes})

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
    for item in control["기준용"]:
        for label, with_goods in NAME_MODES:
            add("대조군 기준용", f"{item['이름']} · {label}", name=item["이름"],
                goods_codes=sorted(item["유사군"]) if with_goods else None)
    with gzip.open(DESCRIPTIVE, "rt", encoding="utf-8") as handle:
        descriptive = json.load(handle)["설명적_이름_목록"]
    for item in descriptive:
        for label, with_goods in NAME_MODES:
            add("설명적 이름", f"{item['이름']} · {label}", name=item["이름"],
                goods_codes=sorted(item["유사군"]) if with_goods else None)
    for name, preset_id, _ in EXPECTED:
        add("기대", f"{name} + {preset_id}", name=name, goods_codes=codes(preset_id))
    for name, preset_id in EXAMPLES:
        add("예시", f"{name} + {preset_id}", name=name, goods_codes=codes(preset_id))
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


def run_queries(root: Path, queries: list[dict], limit: int | None = None):
    """(ms, [(질의, 입력, 응답 dict)]) — 응답은 top_k 5, elapsed_ms 는 뺀다. 시나리오 S5 의 이름은
    S3 응답의 OCR 제안 이름."""
    ms, service = load_tree(root)
    images: dict[str, object] = {}
    out = []
    suggested = None
    started = time.perf_counter()
    for index, row in enumerate(queries[:limit]):
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
        out.append((row, inputs, data))
        if (index + 1) % 200 == 0:
            print(f"  {index + 1}/{len(queries[:limit])} ({time.perf_counter() - started:.0f}초)",
                  flush=True)
    return ms, out


def command_dump(args) -> int:
    queries = json.loads(args.queries.read_text(encoding="utf-8"))
    started = time.perf_counter()
    ms, rows = run_queries(args.root, queries, args.limit)
    responses = {row["질의"]: data for row, _, data in rows}
    text = json.dumps(responses, ensure_ascii=False, sort_keys=False)
    out = {"때": _now(), "트리": str(args.root.resolve()), "모델": ms.state.model["version"],
           "질의": len(responses),
           "새_필드가_있는_응답": sum(NEW_FIELD in r for r in responses.values()),
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


# ---- (나)(다)(라) --------------------------------------------------------------------------------

def check_words(ms, inputs: dict, response: dict) -> dict:
    """한 질의의 (나) — 응답의 낱말별 판정을 식별력 판정 함수와 엔진의 쌍별 판정에 견준다."""
    from src import name_words as nw
    from src.axes.pair_axes import clean_name, normalize_codes

    dist = ms.state.distinct
    goods = normalize_codes(inputs.get("goods_codes")) or None
    split = dist.split_goods_suffix(clean_name(inputs["name"]))
    function = nw.describe(dist.judge_name(split, goods))
    shipped = response[NEW_FIELD]
    expected = function.to_dict()
    # ① 함수의 판정과 다른 낱말 — 응답은 식별력 있음, 함수는 없음이어야 한다(요부로 쓰인 낱말)
    changed = [(mine, theirs) for mine, theirs in zip(shipped["words"], expected["words"])
               if mine != theirs]
    same_words = [w["word"] for w in shipped["words"]] == [w["word"] for w in expected["words"]]
    # ② 쌍별 판정 — 풀 전체(top_k 로 자르지 않은 search_pool)
    pooled = ms.search_pool(**inputs)
    full = {w.word: w for w in pooled.name_words.words}
    weak = {word for word, item in full.items() if not item.distinctive}
    goods_of = {record.appno: record.goods for record in ms.state.records}
    pairs = collections.Counter()
    used_somewhere: set[str] = set()
    for candidate in pooled.candidates:
        if not candidate.title:
            continue
        pair_goods = (goods or frozenset()) | goods_of.get(candidate.id, frozenset())
        judged = dist.judge_name(split, pair_goods or None)
        pair_weak = {j.token for j in judged if j.is_weak}
        pairs["쌍"] += 1
        pairs["엔진의_요부_후보_=_쌍_판정"] += set(candidate.query_tokens) == {
            j.token for j in judged if not j.is_weak}
        pairs["응답이_약하다고_한_낱말을_요부로_씀"] += bool(weak & set(candidate.query_tokens))
        pairs["쌍_판정_=_응답"] += pair_weak == weak
        pairs["쌍에서만_더_약함(후보의_업종)"] += pair_weak > weak
        pairs["쌍에서_덜_약함"] += bool(weak - pair_weak)
        used_somewhere |= set(candidate.query_tokens)
    withdrawn = [mine["word"] for mine, theirs in changed
                 if mine["distinctive"] and not theirs["distinctive"]]
    return {
        "낱말_같음": same_words,
        "함수의_판정과_같음": not changed and shipped["generic"] == expected["generic"],
        "요부로_쓰여_식별력_있음으로_실은_낱말": withdrawn,
        "그_낱말의_함수_사유": sorted({nw.reason_code(theirs["reason"].split("·")[0])
                               for mine, theirs in changed if mine["word"] in withdrawn}),
        "설명_안_되는_차이": [mine["word"] for mine, theirs in changed
                         if mine["word"] not in withdrawn or mine["word"] not in used_somewhere],
        "쌍": dict(pairs), "업종_있음": goods is not None,
        "응답_=_풀": shipped == pooled.name_words.to_dict(),
    }


def summarize_words(rows: list[tuple[dict, dict, dict, dict]]) -> dict:
    """(나) 묶음별 합계."""
    out: dict[str, dict] = {}
    for with_goods in (True, False):
        picked = [check for _, _, _, check in rows if check["업종_있음"] == with_goods]
        pairs = collections.Counter()
        for check in picked:
            pairs.update(check["쌍"])
        out["업종 있는 질의" if with_goods else "업종 없는 질의"] = {
            "질의": len(picked),
            "낱말_같음": sum(c["낱말_같음"] for c in picked),
            "응답_=_풀": sum(c["응답_=_풀"] for c in picked),
            "함수의_판정과_같음": sum(c["함수의_판정과_같음"] for c in picked),
            "요부로_쓰여_식별력_있음으로_실은_낱말이_있는_질의": sum(
                bool(c["요부로_쓰여_식별력_있음으로_실은_낱말"]) for c in picked),
            "그_낱말의_함수_사유": dict(collections.Counter(
                code for c in picked for code in c["그_낱말의_함수_사유"])),
            "설명_안_되는_차이가_있는_질의": sum(bool(c["설명_안_되는_차이"]) for c in picked),
            "쌍": dict(pairs),
        }
    return out


def rates(rows: list[tuple[dict, dict, dict, dict]]) -> dict:
    """(라) 안내의 비율·분류별 낱말 수·그 밖의 사유 코드·한 줄들이 사실인 질의."""
    from src import name_words as nw

    kinds = collections.Counter(notice_kind(data) for _, _, data, _ in rows)
    small = sum(kinds.get(kind, 0) for kind in SMALL_NOTICES)
    categories = collections.Counter()
    other_codes = collections.Counter()
    codes = collections.Counter()
    for _, _, data, _ in rows:
        for word in data[NEW_FIELD]["words"]:
            if word["distinctive"]:
                continue
            categories[word["category"]] += 1
            for reason in word["reason"].split("·"):
                codes[nw.reason_code(reason)] += 1
            if word["category"] == nw.CATEGORY_OTHER:
                other_codes[word["reason"]] += 1
    all_generic = [data for _, _, data, _ in rows if data[NEW_FIELD]["generic"] == "all"]
    some_generic = [data for _, _, data, _ in rows if data[NEW_FIELD]["generic"] == "some"]
    name_strong = [data for _, _, data, _ in rows
                   if famous_banner_state(data) == BANNER_NAME_STRONG]
    total = len(rows)
    return {
        "질의": total,
        "안내": {kind: {"질의": count, "비율": round(count / total, 4)}
               for kind, count in sorted(kinds.items())},
        "큰_안내": {"질의": kinds.get(NOTICE_BIG, 0),
                 "비율": round(kinds.get(NOTICE_BIG, 0) / total, 4)},
        "작은_안내(세_가지_합)": {"질의": small, "비율": round(small / total, 4)},
        "유명_상표_배너가_이름_쪽의_강한_일치": {
            "질의": len(name_strong),
            "그_가운데_식별력_없는_낱말이_있어_안내를_그리지_않은_질의": kinds.get(
                NOTICE_FAMOUS_HIDDEN, 0)},
        "분류별_식별력_없는_낱말": dict(categories.most_common()),
        "사유_코드별(한_낱말에_여럿이면_각각)": dict(codes.most_common()),
        "그_밖으로_간_사유": dict(other_codes),
        "이름_전체를_견줬다는_줄": {
            "모든_낱말이_식별력_없는_질의": len(all_generic),
            "보이는_후보_모두에서_사실(줄이_보임)": sum(whole_name_line(d) for d in all_generic)},
        "빼고_비교했다는_줄": {
            "일부만_식별력_없는_질의": len(some_generic),
            "보이는_후보_모두에서_사실(작은_안내가_보임)": sum(
                removed_as_said(d) for d in some_generic)},
    }


def describe_example(inputs: dict, data: dict) -> dict:
    words = data[NEW_FIELD]
    return {
        "전체_등급": data["overall"]["grade"], "전체_위험도": data["overall"]["prob"],
        "유명_상표": [(m["brand"], m["level"], m["basis"], m["floor"])
                  for m in (data.get("famous") or {}).get("matches", [])],
        "유명_상표_바닥이_등급을_정함": data["overall"].get("famous_floor"),
        "낱말": [(w["word"], "식별력 있음" if w["distinctive"] else w["category"], w["reason"])
               for w in words["words"]],
        "구분": words["generic"], "안내": notice_kind(data), "맨_위_영역": top_area(data),
        "이름_전체를_견줬다는_줄": whole_name_line(data),
        "상위_후보": [{"상표명": c["title"], "등급": c["risk"]["grade"],
                    "요부_후보": c["salient"]["query_tokens"],
                    "뺀_낱말": [(r["token"], r["side"]) for r in c["salient"]["removed"]]}
                   for c in data["candidates"][:3]],
    }


def command_run(args) -> int:
    queries = [row for row in json.loads(args.queries.read_text(encoding="utf-8"))]
    started = time.perf_counter()
    ms, rows = run_queries(REPO_ROOT, queries, args.limit)
    named = [(row, inputs, data) for row, inputs, data in rows if inputs.get("name")]
    nameless = [data for row, inputs, data in rows if not inputs.get("name")]
    checked = [(row, inputs, data, check_words(ms, inputs, data)) for row, inputs, data in named]
    words = summarize_words(checked)
    by_group: dict[str, list] = collections.defaultdict(list)
    for item in checked:
        row = item[0]
        mode = row["질의"].rsplit(" · ", 1)[-1] if " · " in row["질의"] else "업종 있음"
        by_group[f"{row['묶음']} · {mode}"].append(item)
    rate_groups = {
        "설명적 이름 200 · 이름+업종": by_group.get("설명적 이름 · 이름+업종", []),
        "설명적 이름 200 · 이름만": by_group.get("설명적 이름 · 이름만", []),
        "지어낸 이름 대조군 200 · 이름+업종": (by_group.get("대조군 확인용 · 이름+업종", [])
                                      + by_group.get("대조군 기준용 · 이름+업종", [])),
        "지어낸 이름 대조군 200 · 이름만": (by_group.get("대조군 확인용 · 이름만", [])
                                   + by_group.get("대조군 기준용 · 이름만", [])),
    }
    expected = {}
    for name, preset_id, want in EXPECTED:
        match = next(((inputs, data) for row, inputs, data in named
                      if row["질의"] == f"기대 | {name} + {preset_id}"), None)
        if match is None:
            continue
        expected[f"{name} + {preset_id}"] = {
            "기대": want, **describe_example(*match), "맞음": notice_kind(match[1]) == want}
    examples = {row["질의"].split(" | ", 1)[1]: describe_example(inputs, data)
                for row, inputs, data in named if row["묶음"] == "예시"}
    demo = {}
    for key, label in DEMO:
        match = next(((inputs, data) for row, inputs, data in named
                      if row["질의"].startswith(f"시나리오 | {key} ")), None)
        if match is not None:
            demo[label] = describe_example(*match)
    violations = {
        "(나) 응답의 낱말이 식별력 판정의 낱말과 다른 질의": sum(
            not check["낱말_같음"] for *_, check in checked),
        "(나) 응답과 풀의 name_words 가 다른 질의": sum(not c["응답_=_풀"] for *_, c in checked),
        "(나) 함수의 판정과 다른데 요부로 쓰인 낱말이 아닌 질의": sum(
            bool(check["설명_안_되는_차이"]) for *_, check in checked),
        "(나) 업종 있는 질의에서 함수의 판정과 다른 질의": sum(
            check["업종_있음"] and not check["함수의_판정과_같음"] for *_, check in checked),
        "(나) 응답이 약하다고 한 낱말을 엔진이 요부 후보로 쓴 쌍": sum(
            check["쌍"].get("응답이_약하다고_한_낱말을_요부로_씀", 0) for *_, check in checked),
        "(나) 엔진의 요부 후보가 쌍 판정과 다른 쌍": sum(
            check["쌍"].get("쌍", 0) - check["쌍"].get("엔진의_요부_후보_=_쌍_판정", 0)
            for *_, check in checked),
        "(나) 업종 있는 질의에서 쌍이 응답보다 덜 약한 쌍": sum(
            check["쌍"].get("쌍에서_덜_약함", 0) for *_, check in checked if check["업종_있음"]),
        "이름 없는 질의에 새 필드가 있음": sum(NEW_FIELD in data for data in nameless),
        "이름 있는 질의에 새 필드가 없음": sum(NEW_FIELD not in data for _, _, data in named),
    }
    out = {
        "때": _now(), "모델": ms.state.model["version"],
        "DB": {"index_size": len(ms.state.records)},
        "질의": {"전체": len(rows), "이름_있음": len(named), "이름_없음": len(nameless)},
        "(나)_낱말별_판정": words,
        "(다)_기대": expected,
        "(라)_비율": {label: rates(items) for label, items in rate_groups.items() if items},
        "(라)_예시": examples,
        "(라)_시연_넷": demo,
        "위반": violations,
        "기대_모두_맞음": all(item["맞음"] for item in expected.values()),
        "통과": not any(violations.values()),
        "걸린_시간_s": round(time.perf_counter() - started, 1),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("질의", "위반", "기대_모두_맞음", "통과", "걸린_시간_s")},
                     ensure_ascii=False, indent=1))
    print(f"→ {args.out}")
    return 0 if out["통과"] else EXIT_STOP


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    queries = commands.add_parser("queries", help="질의 목록 만들기")
    queries.add_argument("--out", type=Path, default=QUERIES)
    queries.set_defaults(run=command_queries)
    dump = commands.add_parser("dump", help="주어진 트리의 엔진으로 응답 덤프")
    dump.add_argument("--root", type=Path, required=True)
    dump.add_argument("--queries", type=Path, default=QUERIES)
    dump.add_argument("--out", type=Path, required=True)
    dump.add_argument("--limit", type=int, default=None)
    dump.set_defaults(run=command_dump)
    compare = commands.add_parser("compare", help="(가) 두 덤프 견주기")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.add_argument("--out", type=Path, default=None)
    compare.set_defaults(run=command_compare)
    run = commands.add_parser("run", help="(나)(다)(라)")
    run.add_argument("--queries", type=Path, default=QUERIES)
    run.add_argument("--out", type=Path, default=RESULTS)
    run.add_argument("--limit", type=int, default=None)
    run.set_defaults(run=command_run)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
