"""유명 상표 고르기 도구 만들기 — 저장소 밖의 정적 HTML 하나와 썸네일 폴더(통합 모델 설계
§7-14-10).

사람이 브랜드마다 표기(지우기·더하기·흔한 말)·예외 낱말·보호 범위·대표 표장(DB 표장의 역할)·받을
표장(KIPRIS 후보나 직접 적은 출원번호)을 고르고, 고른 것을 overrides JSON 으로 내보내는 도구다.
서버 없이 더블클릭으로 연다. 밖으로 아무것도 보내지 않는다(스크립트·스타일은 파일 안, 그림은 옆
폴더의 파일, CSP 로 연결을 막아 둠). 비공개 로고가 들어가므로 저장소 밖 보관 폴더에만 쓴다.

    ml/venv/bin/python ml/scripts/famous_curate.py build   # curate.html + curate_thumbs/ (호출 0)

입력: 등록부(지금의 overrides 를 입힌 것 + 후보 찾기의 새 브랜드를 "제안"으로 더한 미리 보기),
shared/famous_brands.txt 의 [브랜드] 표(자동 값), 후보 목록 ml/data/staging/famous_candidates.json
(`famous_candidates.py` — 없어도 된다), DB 메타데이터·이미지. 틀은 옆의 famous_curate.html.

반영: 도구에서 "내보내기" → `ml/scripts/famous_registry.py apply 내려받은_파일.json`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
for _root in (ML_ROOT, REPO_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from src import famous_check as fc  # noqa: E402
from src.axes import goods_map as gm  # noqa: E402

from scripts import famous_registry as builder  # noqa: E402

ARCHIVE_DIR = Path.home() / "marklens-archive" / "famous-check-20261124"
DEFAULT_OUT = ARCHIVE_DIR / "curate.html"
DEFAULT_CANDIDATES = ML_ROOT / "data" / "staging" / "famous_candidates.json"
TEMPLATE = Path(__file__).with_suffix(".html")
THUMBS_NAME = "curate_thumbs"  # curate.html 옆 폴더 — db/(DB 표장)·cand/(KIPRIS 후보)
THUMB_SIZE = 420
DATA_SLOT = "/*__DATA__*/"
_URL = re.compile(r"https?://\S+")


def proposed_brands(candidates: dict | None, overrides: dict, table_names: set[str]) -> dict:
    """후보 찾기의 새 브랜드 가운데 아직 등록부에 없는 것 — 미리 보기 등록부에 "새 브랜드"로
    더할 overrides 항목(표기 = 검색에 쓴 표기, 출원인 = 2026-10-12 판 목록의 출원인)."""
    out: dict[str, dict] = {}
    for name, brand in ((candidates or {}).get("브랜드") or {}).items():
        if not brand.get("새_브랜드") or name in table_names or name in overrides["brands"]:
            continue
        out[name] = {"new": True, "notations": {"add": list(brand["표기"])},
                     "applicants": [entry["이름"] for entry in brand.get("출원인") or ()]}
    return out


def goods_summary(classes) -> str:
    """지정상품 요약 — 류와 그 류의 이름(예: 30류 커피·차·과자 · 43류 음식점·숙박)."""
    parts = []
    for value in classes or ():
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        title = gm.NICE_CLASS_TITLES.get(number)
        parts.append(f"{number}류 {title}" if title else f"{number}류")
    return " · ".join(parts)


def make_thumb(source: Path, dest: Path, size: int = THUMB_SIZE) -> bool:
    """DB 이미지 → 썸네일(흰 바탕 PNG). 이미 있으면 그대로."""
    from PIL import Image

    if dest.is_file() and dest.stat().st_mtime >= source.stat().st_mtime:
        return True
    try:
        with Image.open(source) as opened:
            image = opened.convert("RGBA")
            image.thumbnail((size, size))
            canvas = Image.new("RGB", image.size, "white")
            canvas.paste(image, mask=image.split()[3])
            dest.parent.mkdir(parents=True, exist_ok=True)
            canvas.save(dest, format="PNG", optimize=True)
        return True
    except (OSError, ValueError):
        return False


def search_summary(brand: dict) -> dict:
    """후보 찾기 기록 요약 — 쓴 출원인(출처·보낸 말), (가)에서 가장 많이 나온 출원인, 호출·오류."""
    calls = brand.get("호출") or []
    top = brand.get("가장_많은_출원인")
    figures = sum(1 for c in brand.get("후보") or () if c["유형"] == "도형")
    return {
        "applicants": [{"name": entry["이름"], "source": entry["출처"],
                        "terms": entry.get("보낸_말") or []}
                       for entry in brand.get("쓴_출원인") or brand.get("출원인") or ()],
        "top": {"name": top["이름"], "count": top["건수"]} if top else None,
        "calls": len(calls),
        "errors": [f"{call['종류']} {call['검색어']}: {call['오류']}" for call in calls
                   if call.get("오류")],
        "name_totals": {call["검색어"]: call.get("totalCount") for call in calls
                        if call["종류"] == "가" and not call.get("다시")},
        "note": "" if figures else "이 출원인들로 등록된 도형 표장(글자 없는 로고)은 찾지 못함",
    }


def tool_data(*, registry: fc.Registry, table_rows: list[dict], overrides: dict,
              proposed: dict, candidates: dict | None, records: list[dict], presets: dict,
              thumb_of, cand_thumb_of) -> dict:
    """고르기 도구에 싣는 자료. thumb_of(출원번호, 이미지 파일) → DB 썸네일의 상대 경로(없으면
    None), cand_thumb_of(파일 이름) → 후보 썸네일의 상대 경로(없으면 None)."""
    by_table = {row["notations"][0]: row for row in table_rows}
    by_appno = {str(record["출원번호"]): record for record in records}
    state_brands = (candidates or {}).get("브랜드") or {}
    brands = []
    for brand in registry.brands:
        key = brand.table_name or brand.name
        row = by_table.get(key)
        if row is not None:
            base = {"name": key, "is_new": False, "applicants": list(row["applicants"]),
                    "preset": row["preset"], "urls": list(row["urls"]),
                    "evidence_text": " ".join(_URL.sub("", row["evidence"]).split()),
                    "protection_default": (fc.PROTECT_ANY if key in fc.PROTECT_ANY_BRANDS
                                           else fc.PROTECT_NEAR),
                    "notations": list(row["notations"])}
        else:
            guess = proposed.get(key) or {}
            base = {"name": key, "is_new": True, "applicants": list(guess.get("applicants", [])),
                    "preset": None, "urls": [], "evidence_text": "",
                    "protection_default": fc.PROTECT_NEAR,
                    "notations": list((guess.get("notations") or {}).get("add", []))}
        in_brand = {mark.appno for mark in brand.marks}
        # 사람이 출원번호로 고른 표장(받아서 DB 에 들어온 것 포함) — 내보낼 때 fetch 로 남아야
        # 그 브랜드에 계속 이어진다
        fetched = {entry["appno"]: entry.get("source") or fc.FETCH_DIRECT
                   for entry in (overrides["brands"].get(key) or {}).get("fetch") or ()}
        marks = []
        for mark in brand.marks:
            record = by_appno.get(mark.appno, {})
            marks.append({
                "via_fetch": fetched.get(mark.appno) if mark.appno in fetched else None,
                "appno": mark.appno, "title": mark.title, "kind": mark.kind,
                "auto_role": mark.auto_role, "default_role": fc.DEFAULT_ROLE[mark.auto_role],
                "source": mark.source, "app_date": mark.app_date, "reg_date": mark.reg_date,
                "goods": goods_summary(mark.classes),
                "codes": "유사군 " + " ".join(sorted(mark.codes)) if mark.codes else "",
                "applicant": str(record.get("출원인") or ""),
                "thumb": thumb_of(mark.appno, mark.image) if mark.image_exists else None})
        found = state_brands.get(brand.name) or state_brands.get(key)
        cands = []
        for candidate in (found or {}).get("후보") or ():
            appno = candidate["출원번호"]
            record = by_appno.get(appno)
            if record is not None:
                thumb = thumb_of(appno, record.get("이미지파일"))
            else:
                thumb = cand_thumb_of(candidate.get("썸네일")) if candidate.get("썸네일") else None
            cands.append({
                "appno": appno, "title": candidate.get("상표명"), "kind": candidate.get("유형"),
                "applicants": list(candidate.get("출원인") or ()),
                "rightholders": list(candidate.get("등록권리자") or ()),
                "app_date": candidate.get("출원일"), "reg_date": candidate.get("등록일"),
                "goods": goods_summary(candidate.get("류")), "codes": "",
                "via": list(candidate.get("찾은_길") or ()),
                "own": bool(candidate.get("아는_출원인")),
                "intl": candidate.get("국제등록번호"), "in_db": record is not None,
                "in_brand": appno in in_brand, "thumb": thumb})
        brands.append({
            "key": key, "proposed": key in proposed, "custom": False, "base": base,
            "kinds": {n.text: {"kind": n.kind, "reason": n.kind_reason} for n in brand.notations},
            "marks": marks, "candidates": cands,
            "search": search_summary(found) if found else None})
    return {
        "generated": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M"),
        "registry_version": registry.version, "overrides_version": fc.OVERRIDES_VERSION,
        "db_generation": builder.db_generation() or "", "db_count": len(by_appno),
        # 적용된 값이 바뀌면(핵심 업종을 더한 때처럼) 브라우저의 옛 작업 대신 이 값에서 시작한다
        "overrides_key": hashlib.sha256(json.dumps(
            overrides["brands"], ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12],
        "overrides_purpose": builder.OVERRIDES_PURPOSE,
        "roles": list(fc.MARK_ROLES), "protections": list(fc.PROTECTIONS),
        "kinds": list(fc.KINDS),
        "presets": [{"id": key, "label": label or key} for key, label in presets.items()],
        "db_appnos": sorted(by_appno), "initial_overrides": {"brands": overrides["brands"]},
        "brands": brands,
    }


def render(data: dict, template: str) -> str:
    """틀에 자료를 싣는다 — <script type="application/json"> 안이라 '</' 와 줄 구분 문자만
    막는다."""
    if template.count(DATA_SLOT) != 1:
        raise ValueError("틀에 자료 자리가 하나여야 합니다")
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return template.replace(DATA_SLOT, text)


def command_build(args) -> int:
    out: Path = args.out
    thumbs = out.parent / THUMBS_NAME
    table_rows = fc.read_brand_table()
    overrides = fc.load_overrides()
    candidates = (json.loads(args.candidates.read_text(encoding="utf-8"))
                  if args.candidates.exists() else None)
    proposed = {} if args.no_proposed else proposed_brands(
        candidates, overrides, {row["notations"][0] for row in table_rows})
    preview = {"version": fc.OVERRIDES_VERSION,
               "brands": {**overrides["brands"], **proposed}}
    registry = builder.build(overrides=fc.parse_overrides(preview))
    metadata = json.loads(builder.DEFAULT_METADATA.read_text(encoding="utf-8"))
    records = metadata.get("trademarks", metadata) if isinstance(metadata, dict) else metadata
    _, preset_labels = builder.preset_tables()
    made = {"db": 0, "db_failed": 0}

    def thumb_of(appno: str, image: str | None) -> str | None:
        if not image:
            return None
        source = builder.DEFAULT_IMAGES / image
        if not source.is_file():
            return None
        ok = make_thumb(source, thumbs / "db" / f"{appno}.png")
        made["db" if ok else "db_failed"] += 1
        return f"{THUMBS_NAME}/db/{appno}.png" if ok else None

    def cand_thumb_of(name: str) -> str | None:
        return f"{THUMBS_NAME}/cand/{name}" if (thumbs / "cand" / name).is_file() else None

    data = tool_data(registry=registry, table_rows=table_rows, overrides=overrides,
                     proposed=proposed, candidates=candidates, records=records,
                     presets=preset_labels, thumb_of=thumb_of, cand_thumb_of=cand_thumb_of)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.keep and out.exists():  # 앞서 만든 도구를 남긴다(브라우저에 남은 작업을 볼 수 있게)
        kept = out.with_name(f"{out.stem}_{args.keep}{out.suffix}")
        if not kept.exists():
            kept.write_bytes(out.read_bytes())
    out.write_text(render(data, TEMPLATE.read_text(encoding="utf-8")), encoding="utf-8")
    cands = [c for brand in data["brands"] for c in brand["candidates"]]
    print(json.dumps({
        "경로": str(out), "크기_KB": round(out.stat().st_size / 1024),
        "DB_세대": data["db_generation"], "DB_건수": data["db_count"],
        "브랜드": len(data["brands"]),
        "출원번호로_고른_표장(DB에_있음)": sum(1 for brand in data["brands"]
                                      for mark in brand["marks"] if mark["via_fetch"]),
        "새_브랜드(제안)": sum(1 for brand in data["brands"] if brand["proposed"]),
        "DB_표장": sum(len(brand["marks"]) for brand in data["brands"]),
        "DB_썸네일": made, "후보": len(cands),
        "후보_그림_없음": sum(1 for c in cands if not c["thumb"]),
        "후보_DB에_있음": sum(1 for c in cands if c["in_db"]),
        "후보_목록": str(args.candidates) if candidates else "없음(후보 없이 만듦)",
    }, ensure_ascii=False, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("build",))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--keep", metavar="이름",
                        help="이미 있는 curate.html 을 curate_<이름>.html 로 남기고 새로 쓴다")
    parser.add_argument("--no-proposed", action="store_true",
                        help="후보 찾기의 새 브랜드를 제안으로 싣지 않는다")
    args = parser.parse_args(argv)
    return command_build(args)


if __name__ == "__main__":
    raise SystemExit(main())
