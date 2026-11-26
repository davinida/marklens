"""유명 상표 확인의 서비스 연결(v1.4.7 — 통합 모델 설계 §7-14-13). KIPRIS 호출 0.

확정된 판정 규칙(src.famous_check — 고치지 않는다)을 엔진에 연결할 때 쓰는 것:

    ml/venv/bin/python ml/scripts/famous_connect.py kinds     # 대표 로고의 글자 위주·결합·도형 위주
                                                              #   구분을 미리 계산(실제 OCR, 1–2분)
                                                              #   → shared/famous_logo_kinds.json
    ml/venv/bin/python ml/scripts/famous_connect.py kinds --check   # 그 파일이 지금 등록부·DB 의
                                                              #   것인지(OCR 없음, 다르면 종료 1)
    ml/venv/bin/python ml/scripts/famous_connect.py apply     # shared/model/risk_model_v1.4.7.json
                                                              #   = v1.4.6 + famous_check 표시
    ml/venv/bin/python ml/scripts/famous_connect.py verify    # 확인 (가)–(다)·시연·추가 시간(실제
                                                              #   엔진, 약 14분) → ml/data/trials/
                                                              #   famous_connect_verify.json

verify 가 보는 것(어기면 종료 코드 3):
    (가) 후보 목록 불변 — 같은 프로세스에서 v1.4.6 JSON 과 v1.4.7 JSON 으로 각각 돌려 후보 배열(새
         선택 필드 famous_brand 제외)이 같은지: 시나리오 16종, 지어낸 이름 대조군 확인용 400검색,
         표본 A 184질의와 업종 있는 108질의, 같은 로고 400질의
    (나) 유명 상표 일치가 없는 질의는 전체 등급도 같고, 전체 등급이 내려간 질의는 0
    (다) 엔진의 판정 = 규칙 세션의 판정 — 미리 보기 48입력(바닥을 얹은 등급 = 엔진의 전체 등급)과
         이미지 입력, 기준용 표본에서 뽑은 300질의(업종은 유사군 코드로만), 대표 로고·대조군 이미지
         100장의 로고·이미지 속 글자 판정. 확인용 표본은 쓰지 않는다
그리고 시연 넷의 표와 유명 상표 확인에 든 시간(질의당 중앙값·95%)을 적는다.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
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
from src.model import risk_model as rm  # noqa: E402

TRIALS = ML_ROOT / "data" / "trials"
BASE_MODEL_PATH = rm.V146_MODEL_PATH
BASE_VERSION = "risk_model_v1.4.6"
NEW_MODEL_PATH = rm.V147_MODEL_PATH
NEW_VERSION = "risk_model_v1.4.7"
VERIFY_OUT = TRIALS / "famous_connect_verify.json"
SESSION_BASE = TRIALS / "famous_check_3_base.json"  # 규칙 세션의 기준용 결과
SESSION_IMAGES = TRIALS / "famous_check_3_images.json"  # 규칙 세션의 로고·미리 보기
SESSION_ADDED = TRIALS / "famous_check_3_added_samples.json"
SEED = 0
BASE_QUERIES = 300  # (다) 기준용 표본에서 뽑는 질의 수
IMAGE_QUERIES = 100  # (다) 대표 로고 50 + 대조군 이미지 50
TIME_LIMIT_MS = 30.0  # 추가 시간의 중앙값이 이보다 크면 보고(캐시·사전 계산 검토)
EXIT_STOP = 3
DEMO = (("크린토피야", "laundry"), ("파리바게트", "bakery"), ("스타벅수", "cafe"),
        ("블루커피", "cafe"))


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---- kinds -------------------------------------------------------------------------------------

def session_kinds() -> dict[str, str] | None:
    """규칙 세션이 잰 대표 로고의 구분(있으면) — 출원번호 → 구분."""
    if not SESSION_IMAGES.exists():
        return None
    rows = json.loads(SESSION_IMAGES.read_text(encoding="utf-8"))["로고·이미지_속_글자"]["행"]
    return {row["출원번호"]: row["구분"] for row in rows}


def kinds_file(kinds: dict[str, str], registry: fc.Registry) -> dict:
    return {
        "version": fr.LOGO_KINDS_VERSION,
        "made": _now(),
        "registry_sha256": fr.file_sha256(fc.DEFAULT_REGISTRY_PATH),
        "db_generation": registry.sources.get("metadata_generation"),
        "how": ("등록부의 대표 로고(역할 대표 로고(현재)·과거 로고) 가운데 DB 색인에 있는 표장의 "
                "이미지를 엔진의 OCR 로 읽은 자동 유형(src.mark_type.auto_type — 문자·결합·도형)을 "
                "글자 위주·결합·도형 위주로 적은 것. 규칙 세션의 측정(famous_check_confirm.py "
                "images)과 같은 방법 — ml/scripts/famous_connect.py kinds"),
        "counts": dict(sorted(Counter(kinds.values()).items())),
        "kinds": dict(sorted(kinds.items())),
    }


def command_kinds(args) -> int:
    registry = fc.load_registry()
    session = session_kinds()
    if args.check:
        from backend.src.core import engine, multi_search

        current = json.loads(fr.LOGO_KINDS_PATH.read_text(encoding="utf-8"))
        problems = []
        if current.get("registry_sha256") != fr.file_sha256(fc.DEFAULT_REGISTRY_PATH):
            problems.append("등록부가 그 파일을 만든 때의 것과 다름")
        engine.load_all()
        marks, _ = fr.LogoIndex.entries(registry, multi_search.state.by_appno)
        wanted = {mark.appno for _, mark, _ in marks}
        if set(current["kinds"]) != wanted:
            problems.append(f"표장이 다름(파일 {len(current['kinds'])} · 색인의 대표 로고 "
                            f"{len(wanted)})")
        if session is not None and session != current["kinds"]:
            problems.append("규칙 세션이 잰 구분과 다름")
        print("같음" if not problems else "다름: " + " / ".join(problems))
        return 0 if not problems else 1
    from scripts import famous_check_measure as fm

    started = time.perf_counter()
    logo = fm.Logo(fm.load_context(), registry)
    logo.prepare()
    kinds = {mark.appno: logo.kinds[index] for index, (_, mark, _) in enumerate(logo.marks)}
    data = kinds_file(kinds, registry)
    fr.LOGO_KINDS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                                  encoding="utf-8")
    same = None if session is None else session == kinds
    print(json.dumps({"대표_로고": len(kinds), "구분": data["counts"],
                      "사진_판정": sum(logo.photos),
                      "규칙_세션이_잰_구분과_같음": same,
                      "걸린_시간_s": round(time.perf_counter() - started, 1)},
                     ensure_ascii=False))
    print(f"→ {fr.LOGO_KINDS_PATH}")
    return 0 if same is not False else 1


# ---- apply -------------------------------------------------------------------------------------

def candidate_model(base: dict) -> dict:
    """v1.4.7 = v1.4.6 + famous_check 표시(계수·기준·다른 규칙은 그대로)."""
    confirmed, digest = fr.load_confirmed()
    model = json.loads(json.dumps(base))
    model["version"] = NEW_VERSION
    model[rm.FAMOUS_CHECK_KEY] = {
        "enabled": True,
        "version": fr.CONFIRMED_VERSION,
        "confirmed_sha256": digest,
        "since": "2026-11-26",
        "scope": ("질의마다 검색과 별개로 유명 상표를 확인한다 — 이름, 이름 없는 이미지 질의의 "
                  "OCR 제안 상표명, 사진이 아닌 질의 이미지와 대표 로고. 판정이 준 바닥(위험·검토 "
                  "권장)이 전체 등급보다 높으면 전체 등급만 올린다(후보 목록·후보 등급·위험도·"
                  "정렬은 그대로). 응답의 선택 필드 famous·overall.famous_floor·"
                  "candidates[].famous_brand"),
        "basis": ("유명 상표 확인 단계의 확정된 판정 규칙(통합 모델 설계 §7-14-12) — 확정 파일 "
                  "shared/famous_check_confirmed.json, 연결은 §7-14-13"),
    }
    model.setdefault("meta", {})[rm.FAMOUS_CHECK_KEY] = {
        "decided_at": "2026-11-26",
        "derived_from": BASE_VERSION,
        "script": "ml/scripts/famous_connect.py",
        "confirmed": {
            "약한_일치_조건": confirmed["규칙"]["약한_일치_조건"],
            "판정_모듈_sha256": confirmed["규칙"]["판정_모듈_sha256"],
            "등록부_sha256": confirmed["등록부"]["sha256"],
            "브랜드": confirmed["등록부"]["브랜드"],
            "DB_세대": confirmed["등록부"].get("DB_세대"),
        },
        "rule": ("계수·등급 기준·다른 규칙은 v1.4.6 그대로. 표시가 켜져 있을 때만 엔진이 유명 상표 "
                 "확인을 한다 — 표시가 없는 JSON 은 예전과 똑같이 동작"),
    }
    return rm.validate_model(model)


def differing_keys(base: dict, model: dict) -> list[str]:
    keys = [key for key in sorted(set(base) | set(model)) if base.get(key) != model.get(key)]
    out = []
    for key in keys:
        if key == "meta":
            out += [f"meta.{name}" for name in sorted(set(base["meta"]) | set(model["meta"]))
                    if base["meta"].get(name) != model["meta"].get(name)]
        else:
            out.append(key)
    return out


def command_apply(args) -> int:
    if NEW_MODEL_PATH.exists() and not args.force:
        print(f"거절: {NEW_MODEL_PATH} 가 있습니다(--force)", file=sys.stderr)
        return 4
    base = json.loads(BASE_MODEL_PATH.read_text(encoding="utf-8"))
    model = candidate_model(base)
    NEW_MODEL_PATH.write_text(json.dumps(model, ensure_ascii=False, indent=1) + "\n",
                              encoding="utf-8")
    print(json.dumps({"version": model["version"], "다른_키": differing_keys(base, model),
                      "famous_check": {key: model[rm.FAMOUS_CHECK_KEY][key]
                                       for key in ("enabled", "version", "confirmed_sha256")}},
                     ensure_ascii=False, indent=1))
    print(f"→ {NEW_MODEL_PATH}")
    return 0


# ---- verify ------------------------------------------------------------------------------------

TOP_K = 20  # 응답이 낼 수 있는 가장 긴 후보 배열로 견준다
SERVICE_TOP_K = 5  # 화면이 쓰는 기본값 — 규칙 세션의 미리 보기와 시연 표는 이 값으로 잰 전체 등급
PREVIEW_KEYS = ("브랜드", "수준", "경로", "표기", "바닥", "겹침")


def _plain(candidates: list[dict]) -> list[dict]:
    """새 선택 필드(famous_brand)를 뺀 후보 배열."""
    return [{key: value for key, value in candidate.items() if key != "famous_brand"}
            for candidate in candidates]


def _grade_index(grade: str | None) -> int:
    return -1 if grade is None else rm.GRADES.index(grade)


def _higher(*grades: str | None) -> str | None:
    usable = [grade for grade in grades if grade]
    return max(usable, key=rm.GRADES.index) if usable else None


def compare_responses(before: dict, after: dict) -> list[str]:
    """v1.4.6 응답(before)과 v1.4.7 응답(after) — 달라도 되는 것은 새 선택 필드와, 유명 상표 바닥이
    걸린 질의의 전체 등급뿐. 어긋난 것의 목록(없으면 빈 목록)."""
    problems = []
    if "famous" in before or "famous_floor" in before["overall"] or any(
            "famous_brand" in candidate for candidate in before["candidates"]):
        problems.append("v1.4.6 응답에 새 필드가 있음")
    if _plain(after["candidates"]) != before["candidates"]:
        problems.append("후보 배열이 다름")
    for key in ("prob", "pattern", "caveats", "query_type", "visual_status"):
        if before["overall"][key] != after["overall"][key]:
            problems.append(f"overall.{key} 가 다름")
    for key in ("grade_precision", "thresholds", "pool"):
        if before["meta"][key] != after["meta"][key]:
            problems.append(f"meta.{key} 가 다름")
    for key in ("api_version", "dataset_info", "index_size", "top_k_requested",
                "top_k_returned"):
        if before[key] != after[key]:
            problems.append(f"{key} 가 다름")
    famous = after.get("famous")
    if famous is None or famous.get("status") != fr.STATUS_CHECKED:
        problems.append("v1.4.7 응답에 유명 상표 확인이 없음")
        return problems
    old, new = before["overall"]["grade"], after["overall"]["grade"]
    floored = after["overall"].get("famous_floor")
    if _grade_index(new) < _grade_index(old):
        problems.append("전체 등급이 내려감")
    if not famous["matches"] and (new != old or floored):
        problems.append("일치가 없는데 전체 등급이 달라짐")
    if (new != old) != bool(floored):
        problems.append("전체 등급이 달라진 것과 famous_floor 가 어긋남")
    return problems


class Checker:
    """같은 프로세스에서 v1.4.6 JSON 과 v1.4.7 JSON 으로 같은 질의를 돌려 견준다."""

    def __init__(self, context: dict):
        from scripts import nameless_shared_threshold as ns

        self.ns, self.ms = ns, context["ms"]
        self.old = rm.load_model(BASE_MODEL_PATH)
        self.rows: list[dict] = []

    def run(self, group: str, label: str, *, top_k: int = TOP_K,
            **inputs) -> tuple[dict, dict, object]:
        ms = self.ms
        with self.ns.using_model(ms, self.old):
            before = ms.multi_search(**inputs, top_k=top_k).to_dict()
        result = ms.multi_search(**inputs, top_k=top_k)
        after = result.to_dict()
        matches = after.get("famous", {}).get("matches", [])
        self.rows.append({
            "묶음": group, "질의": label, "전": before["overall"]["grade"],
            "후": after["overall"]["grade"], "바닥이_정함": after["overall"].get("famous_floor"),
            "일치": [f"{m['brand']} {m['level']}({m['basis']})" for m in matches],
            "이름_있음": bool(inputs.get("name")), "이미지_있음": inputs.get("image") is not None,
            "어긋남": compare_responses(before, after), "ms": round(result.famous_ms, 2)})
        return before, after, result


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))], 2)


def timing(rows: list[dict]) -> dict:
    def table(selected: list[dict]) -> dict:
        values = [row["ms"] for row in selected]
        return {"질의": len(values),
                "중앙값_ms": round(statistics.median(values), 2) if values else None,
                "95%_ms": _percentile(values, 0.95), "최대_ms": max(values, default=None)}

    slowest = sorted(rows, key=lambda row: row["ms"], reverse=True)[:8]
    return {"전체": table(rows),
            "이름_있는_질의": table([row for row in rows if row["이름_있음"]]),
            "이름_없는_질의": table([row for row in rows if not row["이름_있음"]]),
            "일치가_있는_질의": table([row for row in rows if row["일치"]]),
            "가장_느린_질의": [{"묶음": row["묶음"], "질의": row["질의"], "ms": row["ms"]}
                          for row in slowest]}


def run_unchanged(checker: Checker, context: dict, smoke: bool) -> dict:
    """(가)·(나) — 시나리오 16종, 지어낸 이름 대조군 확인용 400검색, 표본 A 184질의와 업종 있는
    108질의, 같은 로고 400질의."""
    import gzip

    from scripts import logo_floor_image_only as third
    from scripts import named_goods_product as ngp
    from scripts import named_search_thresholds as first
    from scripts import named_shared_threshold as second

    ms, decode = context["ms"], context["service"]
    limit = 3 if smoke else None
    scenarios: dict[str, dict] = {}
    suggested = None
    for key, title, inputs in second.scenario_inputs(ms, decode)[:6 if smoke else None]:
        if inputs.get("name") == "@S3":
            if not suggested:
                continue
            inputs["name"] = suggested
        checker.run("시나리오(top_k 20)", f"{key} {title}", **inputs)
        before, after, _ = checker.run("시나리오", f"{key} {title}", top_k=SERVICE_TOP_K,
                                       **inputs)
        if key == "S3":
            suggested = after["overall"]["query_type"].get("suggested_name")
        scenarios[key] = {"제목": title, "전": before["overall"]["grade"],
                          "전_위험도": before["overall"]["prob"],
                          "후": after["overall"]["grade"], "famous": after["famous"],
                          "바닥이_정함": after["overall"]["famous_floor"]}
    print(f"    시나리오 {len(scenarios)}", flush=True)
    a_by_key = {query.key: query for query in context["A"]}
    control = json.loads(first._paths(TRIALS)["control"].read_text(encoding="utf-8"))  # noqa: SLF001
    for item in ngp.control_items(control, "확인용", limit):
        image = decode(a_by_key[item["이미지"]].path.read_bytes())
        goods = sorted(item["유사군"]) or None
        for mode, with_image, with_goods in ngp.MODES:
            checker.run("대조군 확인용", f"{item['이름']} · {mode}", name=item["이름"],
                        image=image if with_image else None,
                        goods_codes=goods if with_goods else None)
    print("    지어낸 이름 대조군", flush=True)
    for query in context["A"][:limit]:
        image = decode(query.path.read_bytes())
        goods = sorted(query.goods) or None
        checker.run("표본 A", f"{query.key} 이름+이미지", image=image, name=query.name,
                    goods_codes=goods)
        if goods:
            checker.run("표본 A 업종 있는 질의(이름 없이)", f"{query.key} 이미지+업종", image=image,
                        goods_codes=goods)
    print("    표본 A", flush=True)
    with gzip.open(third.POSITIVES, "rt", encoding="utf-8") as handle:
        positives = json.load(handle)["양성"][:limit]
    for item in positives:
        image = decode((ML_ROOT / "data" / item["이미지"]).read_bytes())
        for mode, goods in (("업종 없음", None), ("같은 업종", sorted(item["유사군"]) or None)):
            checker.run("같은 로고", f"{item['출원번호']} + {item['이름']} · {mode}", image=image,
                        name=item["이름"], goods_codes=goods)
    print("    같은 로고", flush=True)
    return scenarios


def summarize_unchanged(rows: list[dict]) -> dict:
    groups: dict[str, dict] = {}
    for row in rows:
        part = groups.setdefault(row["묶음"], {
            "질의": 0, "후보_배열_같음": 0, "일치_있음": 0, "전체_등급_오름": 0,
            "전체_등급_내려감": 0, "일치_없는데_등급_다름": 0, "어긋남": []})
        part["질의"] += 1
        part["후보_배열_같음"] += "후보 배열이 다름" not in row["어긋남"]
        part["일치_있음"] += bool(row["일치"])
        part["전체_등급_오름"] += _grade_index(row["후"]) > _grade_index(row["전"])
        part["전체_등급_내려감"] += _grade_index(row["후"]) < _grade_index(row["전"])
        part["일치_없는데_등급_다름"] += (not row["일치"]) and row["후"] != row["전"]
        if row["어긋남"]:
            part["어긋남"].append({"질의": row["질의"], "어긋남": row["어긋남"]})
    return groups


def _row_of(match: fc.BrandMatch | None) -> dict | None:
    if match is None:
        return None
    return {"브랜드": match.brand, "수준": match.level, "경로": match.path, "표기": match.notation,
            "바닥": match.floor, "겹침": match.overlap}


class Reference:
    """엔진을 거치지 않은 판정 — 확정된 판정 모듈(fc)을 직접 부르고, 로고는 규칙 세션이 잰 대표
    로고의 구분·사진 판정과 fc.logo_match 로. 런타임 모듈(src.famous_runtime)의 check·LogoIndex 는
    쓰지 않는다(질의의 류만 같은 함수 classes_from_codes 로 — 규칙 세션에서 확인한 안)."""

    def __init__(self, context: dict, static: dict, thresholds: fc.Thresholds):
        import numpy as np
        from src.axes import goods_map as gm

        self.np = np
        self.ms, self.engine, self.static = context["ms"], context["engine"], static
        self.thresholds = thresholds
        self.old = rm.load_model(BASE_MODEL_PATH)
        self.representative = fr.representative_classes(gm.load_goods_map())
        rows = json.loads(SESSION_IMAGES.read_text(encoding="utf-8"))["로고·이미지_속_글자"]["행"]
        self.logos = [(row["브랜드"], row["출원번호"], row["구분"], bool(row["사진_판정"]),
                       self.ms.state.embeddings[self.ms.state.by_appno[row["출원번호"]].pos])
                      for row in rows]
        self._risk: dict[float, bool] = {}

    def classes(self, codes) -> list[int] | None:
        if not codes:
            return None
        return fr.classes_from_codes(codes, self.static["codes_of"], self.static["classes_of"],
                                     self.representative)[0]

    def _is_risk(self, value: float) -> bool:
        if value not in self._risk:
            ms = self.ms
            judged = ms._judge(ms._image_only_features(value, "도형"), self.old,  # noqa: SLF001
                               "도형")
            self._risk[value] = judged.result.grade == fc.GRADE_RISK
        return self._risk[value]

    def judge(self, *, name=None, codes=None, image=None) -> dict:
        """(이름·이미지 속 글자의 판정, 로고가 강함인 브랜드, 바닥)."""
        np, ms = self.np, self.ms
        valid = sorted(ms.valid_goods(codes)[0]) if codes else None
        seen, hits, photo = None, set(), False
        if image is not None:
            embedding = np.asarray(self.engine.encode_image(image),
                                   dtype=np.float32).reshape(-1)
            photo = bool(ms.is_photo_query(embedding))
            detection = ms.ocr.detect(image)  # 검색이 돌린 것과 같은 결과(memo_ocr)
            kind = None if detection is None else fr.kind_name(detection.kind)
            seen = None if detection is None else (detection.text or None)
            if not photo:
                for brand, _, logo_kind, logo_photo, vector in self.logos:
                    value = round(min(1.0, max(0.0, float(vector @ embedding))), 4)
                    grade = fc.GRADE_RISK if self._is_risk(value) else None
                    if fc.logo_match(value, grade, logo_kind=logo_kind, query_kind=kind,
                                     logo_photo=logo_photo, query_photo=photo):
                        hits.add(brand)
        result = fc.check_famous(
            name, valid, self.static["registry"], self.thresholds, dist=self.static["dist"],
            goods_floor=self.static["floor"], ocr_text=None if name else seen,
            goods_classes=self.classes(valid))
        return {"판정": result, "로고": hits, "사진": photo,
                "바닥": _higher(result.floor, fc.GRADE_RISK if hits else None)}


def engine_against(reference: dict, before: dict, after: dict, result) -> list[str]:
    """엔진의 판정과 엔진을 거치지 않은 판정이 어긋난 곳."""
    problems = []
    outcome = result.famous_outcome
    if outcome is None:
        return ["엔진이 확인하지 못함"]
    judged = outcome.result
    expected = reference["판정"]
    if (judged.matches if judged is not None else ()) != expected.matches:
        problems.append("이름·이미지 속 글자의 판정이 다름")
    if set(outcome.logo_hits) != reference["로고"]:
        problems.append(f"로고가 강함인 브랜드가 다름({sorted(outcome.logo_hits)} 대 "
                        f"{sorted(reference['로고'])})")
    if outcome.floor != reference["바닥"]:
        problems.append("바닥이 다름")
    if after["overall"]["grade"] != _higher(before["overall"]["grade"], reference["바닥"]):
        problems.append("전체 등급이 바닥을 얹은 등급과 다름")
    return problems


def run_preview(checker: Checker, reference: Reference, context: dict, static: dict,
                smoke: bool) -> dict:
    """(다) 미리 보기 48입력 — 규칙 세션이 적어 둔 일치·바닥·"바닥을 얹으면" 등급과 엔진의 응답."""
    from scripts import famous_check_confirm as cf
    from scripts import famous_check_measure as fm
    from scripts import named_shared_threshold as second

    saved = json.loads(SESSION_IMAGES.read_text(encoding="utf-8"))["미리_보기"]
    resolve = fm.goods_resolver(static["presets"])
    scenarios = {key: inputs for key, _, inputs in second.scenario_inputs(
        context["ms"], context["service"])}
    base_names = static["control"]["대조군"]["이름"][cf.BASE]
    entries = cf.PREVIEW[:6] if smoke else cf.PREVIEW
    rows, different = [], []
    for (name, preset_id), row in zip(entries, saved):
        if name.startswith("@대조군"):
            item = base_names[int(name[-1]) - 1]
            name, codes = item["이름"], sorted(item["유사군"])
        elif name.startswith("@"):
            inputs = scenarios[name[1:]]
            name, codes = inputs["name"], inputs.get("goods_codes")
        else:
            codes = resolve(preset_id)[0]
        assert name == row["입력"], (name, row["입력"])
        before, after, result = checker.run("미리 보기", f"{name} + {row['업종']}",
                                            top_k=SERVICE_TOP_K, name=name, goods_codes=codes)
        strongest = None if result.famous_outcome.result is None else (
            result.famous_outcome.result.strongest)
        saved_match = None if row["일치"] is None else {
            key: row["일치"][key] for key in PREVIEW_KEYS}
        problems = engine_against(reference.judge(name=name, codes=codes), before, after, result)
        if _row_of(strongest) != saved_match:
            problems.append("규칙 세션이 적어 둔 일치와 다름")
        if result.famous_outcome.floor != row["바닥"]:
            problems.append("규칙 세션이 적어 둔 바닥과 다름")
        if before["overall"]["grade"] != row["지금_등급"]:
            problems.append("v1.4.6 의 전체 등급이 규칙 세션 때와 다름")
        if after["overall"]["grade"] != row["바닥_적용_등급"]:
            problems.append("엔진의 전체 등급이 '바닥을 얹으면' 등급과 다름")
        rows.append({"입력": name, "업종": row["업종"], "지금": before["overall"]["grade"],
                     "엔진": after["overall"]["grade"], "바닥을_얹으면": row["바닥_적용_등급"],
                     "일치": after["famous"]["matches"][:1], "어긋남": problems})
        if problems:
            different.append({"입력": f"{name} + {row['업종']}", "어긋남": problems})
    return {"입력": len(rows), "같음": len(rows) - len(different), "어긋남": different,
            "행": rows}


def run_image_preview(checker: Checker, reference: Reference, context: dict, static: dict,
                      smoke: bool) -> dict:
    """(다) 이미지 입력 — 2-1 측정의 이미지 미리 보기 넷(로고·이름 없는 로고·도형·대조군 이미지)."""
    from scripts import famous_check_measure as fm
    from scripts import named_shared_threshold as second

    registry = static["registry"]
    starbucks = (REPO_ROOT / second.SCENARIO_IMAGES["starbucks"]).read_bytes()
    instagram = next(mark for mark in sorted(registry.brand("인스타그램").marks,
                                             key=lambda m: m.appno)
                     if mark.auto_role == fc.ROLE_FIGURE and mark.image_exists)
    queries = {query.key: query for query in context["A"]}
    key = static["control"]["대조군"]["이미지"]["기준용"][0]
    entries = [
        ("STARBUCKS 로고(이름 없음) + 의류", starbucks, None, "clothing"),
        ("STARBUCKS 로고 + 몬테로사 + 카페", starbucks, "몬테로사", "cafe"),
        (f"인스타그램 로고 도형({instagram.appno}, 이름 없음)",
         (fm.IMAGES_DIR / instagram.image).read_bytes(), None, None),
        (f"대조군의 덜 닮은 이미지({key}) + 카페", queries[key].path.read_bytes(), None, "cafe"),
    ]
    rows = []
    for label, raw, name, preset_id in entries[:2] if smoke else entries:
        image = context["service"](raw) or context["direct"](raw)
        codes = static["codes_of"][preset_id] if preset_id else None
        before, after, result = checker.run("이미지 미리 보기", label, top_k=SERVICE_TOP_K,
                                            image=image, name=name, goods_codes=codes)
        expected = reference.judge(name=name, codes=codes, image=image)
        rows.append({"입력": label, "지금": before["overall"]["grade"],
                     "엔진": after["overall"]["grade"], "일치": after["famous"]["matches"],
                     "로고가_강함인_브랜드": sorted(expected["로고"]),
                     "어긋남": engine_against(expected, before, after, result)})
    return {"입력": len(rows), "같음": sum(not row["어긋남"] for row in rows), "행": rows}


def run_base_sample(checker: Checker, reference: Reference, static: dict,
                    thresholds: fc.Thresholds, smoke: bool) -> dict:
    """(다) 기준용 표본에서 뽑은 질의 — 업종은 유사군 코드로만 넣는다. 엔진의 판정을 (1) 엔진을
    거치지 않은 판정(같은 코드·같은 류)과 (2) 규칙 세션의 판정(류를 따로 준 것)과 견준다."""
    from scripts import famous_check_confirm as cf
    from scripts import famous_check_measure as fm

    old = fm.frozen_samples()
    added = json.loads(SESSION_ADDED.read_text(encoding="utf-8"))
    registry = static["registry"]
    matcher = cf.Matcher(registry, static["dist"], static["floor"],
                         cf.classes_resolver(static["classes_of"], static["records"]))
    items, _ = cf.usable(old, added, registry, matcher, static["applicant_keys"], cf.BASE)
    shares = {"P1": 60, "P2": 40, "P3": 60, "N1": 60, "N2": 20, "N3": 20, "N5": 40}
    picked = []
    for name, count in shares.items():
        pool = sorted(items[name], key=lambda item: (item["이름"], str(item.get("업종_표시"))))
        chosen = random.Random(f"{SEED}|연결|{name}").sample(pool, min(count, len(pool)))
        picked += [(name, item) for item in chosen]
    if smoke:
        picked = picked[::25]
    different, session_diff, invalid = [], [], 0
    counts = Counter()
    for name, item in picked:
        codes = item.get("업종") or None
        valid = sorted(checker.ms.valid_goods(codes)[0]) if codes else None
        invalid += bool(codes) and len(valid or []) != len(set(codes))
        before, after, result = checker.run(
            "기준용 표본", f"[{name}] {item['이름']} + {item.get('업종_표시') or '없음'}",
            name=item["이름"], goods_codes=codes)
        problems = engine_against(reference.judge(name=item["이름"], codes=codes), before,
                                  after, result)
        counts[name] += 1
        if problems:
            different.append({"질의": f"[{name}] {item['이름']}", "어긋남": problems})
        session = matcher.decide(item, thresholds)  # 류를 따로 준 판정(규칙 세션)
        judged = result.famous_outcome.result
        if _row_of(session.strongest) != _row_of(judged.strongest if judged else None) or (
                session.floor != result.famous_outcome.floor):
            session_diff.append({
                "질의": f"[{name}] {item['이름']} + {item.get('업종_표시') or '없음'}",
                "규칙_세션": _row_of(session.strongest), "엔진": _row_of(
                    judged.strongest if judged else None),
                "세션의_류": matcher.resolve(item), "코드에서_정한_류": reference.classes(valid)})
    return {"질의": len(picked), "표본별": dict(counts),
            "형식이_안_맞는_코드가_있던_질의": invalid,
            "엔진을_거치지_않은_판정과_같음": len(picked) - len(different), "어긋남": different,
            "규칙_세션의_판정(류를 따로 준 것)과_같음": len(picked) - len(session_diff),
            "규칙_세션과_다른_것": session_diff}


def run_images(checker: Checker, reference: Reference, context: dict, static: dict,
               smoke: bool) -> dict:
    """(다) 대표 로고 이미지 50 + 대조군 이미지 50 — 로고·이미지 속 글자 판정."""
    from scripts import famous_check_measure as fm

    session = json.loads(SESSION_IMAGES.read_text(encoding="utf-8"))["로고·이미지_속_글자"]
    registry = static["registry"]
    marks = {mark.appno: (brand.name, mark) for brand in registry.brands
             for mark in brand.logo_marks}
    rows = sorted(session["행"], key=lambda row: row["출원번호"])
    half = IMAGE_QUERIES // 2
    logos = random.Random(f"{SEED}|연결|로고").sample(rows, min(half, len(rows)))
    control = static["control"]["대조군"]["이미지"]
    keys = sorted(control["기준용"] + control["확인용"])
    controls = random.Random(f"{SEED}|연결|대조군").sample(keys, min(half, len(keys)))
    if smoke:
        logos, controls = logos[:3], controls[:3]
    queries = {query.key: query for query in context["A"]}
    hit_keys = {hit["질의"] for name in ("로고_목록", "글자_목록")
                for hit in session["대조군_덜_닮은_이미지"][name]}
    different, own, cross, text_hits = [], 0, [], 0
    for row in logos:
        brand, mark = marks[row["출원번호"]]
        image = context["direct"]((fm.IMAGES_DIR / mark.image).read_bytes())
        before, after, result = checker.run("대표 로고 이미지", f"{brand} {mark.appno}",
                                            image=image)
        expected = reference.judge(image=image)
        problems = engine_against(expected, before, after, result)
        hits = set(result.famous_outcome.logo_hits)
        own += brand in hits
        if hits - {brand}:
            cross.append(f"{brand} {mark.appno} → {sorted(hits - {brand})}")
        if (brand in hits) == bool(row["사진_판정"]):
            problems.append("자기 브랜드의 로고 일치가 사진 판정과 어긋남")
        text_hits += bool(result.famous_outcome.result and result.famous_outcome.result.matches)
        if problems:
            different.append({"질의": f"{brand} {mark.appno}", "어긋남": problems})
    clean = 0
    for key in controls:
        image = context["direct"](queries[key].path.read_bytes())
        before, after, result = checker.run("대조군 이미지", key, image=image)
        problems = engine_against(reference.judge(image=image), before, after, result)
        matched = bool(after["famous"]["matches"])
        if matched != (key in hit_keys):
            problems.append("규칙 세션이 적어 둔 대조군 이미지의 판정과 다름")
        clean += not matched
        if problems:
            different.append({"질의": key, "어긋남": problems})
    return {"대표_로고_이미지": len(logos), "자기_브랜드와_로고_강함": own,
            "사진으로_판정된_대표_로고": sum(bool(row["사진_판정"]) for row in logos),
            "다른_브랜드와_로고_강함": cross, "이미지_속_글자로_강함인_대표_로고": text_hits,
            "대조군_이미지": len(controls), "일치_없는_대조군_이미지": clean,
            "같음": len(logos) + len(controls) - len(different), "어긋남": different}


def demo_table(scenarios: dict) -> list[dict]:
    """시연 넷 — 크린토피야 + 세탁, 파리바게트 + 빵집, 스타벅수 + 카페, 블루커피 + 카페."""
    rows = []
    for key, name in (("F2", "크린토피야"), ("F3", "파리바게트"), ("F1", "스타벅수"),
                      ("S1", "블루커피")):
        row = scenarios.get(key)
        if row is None:
            continue
        match = (row["famous"]["matches"] or [None])[0]
        rows.append({"시연": f"{name}({row['제목']})", "v1.4.6": row["전"],
                     "v1.4.6_위험도": row["전_위험도"], "v1.4.7": row["후"],
                     "바닥이_정함": row["바닥이_정함"],
                     "배너": None if match is None else
                     f"{match['brand']} {match['level']}({match['basis']}) · 바닥 "
                     f"{match['floor'] or '없음'}"})
    return rows


def command_verify(args) -> int:
    from scripts import famous_check_confirm as cf
    from scripts import logo_floor_image_only as third
    from scripts import nameless_shared_threshold as ns

    smoke = bool(args.smoke)
    if smoke and args.out.resolve() == VERIFY_OUT.resolve():
        print("거절: 스모크는 --out 으로 다른 파일에", file=sys.stderr)
        return 4
    started = time.perf_counter()
    context = ns._context(rm.DEFAULT_MODEL_PATH)  # noqa: SLF001 — 서비스 기본 모델(v1.4.7)
    ms = context["ms"]
    if ms.state.model["version"] != NEW_VERSION or ms.state.famous is None:
        print("거절: 엔진이 v1.4.7(유명 상표 확인 켜짐)로 뜨지 않았습니다", file=sys.stderr)
        return 4
    third.memo_ocr(ms)  # 같은 이미지는 OCR 을 한 번만(전·후·견줄 판정이 같은 결과를 쓴다)
    static = cf.load_static()
    confirmed, digest = fr.load_confirmed()
    thresholds = fr.confirmed_thresholds(confirmed)
    checker = Checker(context)
    reference = Reference(context, static, thresholds)
    scenarios = run_unchanged(checker, context, smoke)
    unchanged_rows = list(checker.rows)
    print(f"  (가)·(나) {len(unchanged_rows)}질의 {time.perf_counter() - started:.0f}초",
          flush=True)
    preview = run_preview(checker, reference, context, static, smoke)
    image_preview = run_image_preview(checker, reference, context, static, smoke)
    base_sample = run_base_sample(checker, reference, static, thresholds, smoke)
    images = run_images(checker, reference, context, static, smoke)
    print(f"  (다) {len(checker.rows) - len(unchanged_rows)}질의 "
          f"{time.perf_counter() - started:.0f}초", flush=True)
    groups = summarize_unchanged(unchanged_rows)
    every = summarize_unchanged(checker.rows)
    times = timing(checker.rows)
    violations = {
        "(가) 후보 배열·그 밖의 필드": sum(len(part["어긋남"]) for part in every.values()),
        "(나) 전체 등급이 내려간 질의": sum(part["전체_등급_내려감"] for part in every.values()),
        "(나) 일치가 없는데 전체 등급이 다른 질의": sum(part["일치_없는데_등급_다름"]
                                               for part in every.values()),
        "(다) 미리 보기": len(preview["어긋남"]),
        "(다) 이미지 미리 보기": image_preview["입력"] - image_preview["같음"],
        "(다) 기준용 표본": len(base_sample["어긋남"]),
        "(다) 이미지": len(images["어긋남"]),
    }
    results = {
        "때": _now(), "스모크": smoke, "모델": {"전": BASE_VERSION, "후": NEW_VERSION},
        "확정_파일_sha256": digest, "등록부_sha256": ms.state.famous.registry_sha256,
        "DB": {"index_size": int(context["engine"].state.index.ntotal),
               "세대": context["engine"].state.artifact_generation_id},
        "(가)(나)_묶음별": groups, "(가)(나)_전체(다 의 질의 포함)": every,
        "(다)_미리_보기": preview, "(다)_이미지_미리_보기": image_preview,
        "(다)_기준용_표본": base_sample, "(다)_이미지": images,
        "(마)_시연": demo_table(scenarios), "추가_시간": times,
        "추가_시간_한도_ms": TIME_LIMIT_MS, "위반": violations,
        "통과": not any(violations.values()),
        "걸린_시간_s": round(time.perf_counter() - started, 1)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    print(json.dumps({"위반": violations, "추가_시간": {key: value for key, value in times.items()
                                                 if key != "가장_느린_질의"},
                      "시연": results["(마)_시연"],
                      "(가)(나)": {name: {key: value for key, value in part.items()
                                         if key != "어긋남"} for name, part in groups.items()}},
                     ensure_ascii=False, indent=1))
    print(f"→ {args.out}")
    return 0 if results["통과"] else EXIT_STOP


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("kinds", "apply", "verify"))
    parser.add_argument("--check", action="store_true", help="kinds: 파일이 지금 것인지만 본다")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="verify: 일부 질의만(다른 폴더에)")
    parser.add_argument("--out", type=Path, default=VERIFY_OUT)
    args = parser.parse_args(argv)
    return {"kinds": command_kinds, "apply": command_apply,
            "verify": command_verify}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
