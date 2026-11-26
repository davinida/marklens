"""유명 상표 등록부 만들기 — shared/famous_registry.json (통합 모델 설계 §7-14).

입력: shared/famous_brands.txt 의 [브랜드] 표(표기·출원인·업종 세트·근거), 수집 계획
ml/data/staging/famous_brands.plan.json(출원번호 → 브랜드), DB 메타데이터
ml/data/kipris_metadata.json,
사람이 정한 값 shared/famous_registry_overrides.json(고르기 도구가 내보내는 JSON — 표기 지우기·
더하기·흔한 말, 예외 낱말, 보호 범위, 표장 역할, 새 브랜드, 받을 표장). 등록부의 내용과 규칙은
`src.famous_check`(build_registry·parse_overrides) — 이 스크립트는 파일을 읽고 쓰는 일만 한다.

    ml/venv/bin/python ml/scripts/famous_registry.py build     # shared/famous_registry.json 을 쓴다
    ml/venv/bin/python ml/scripts/famous_registry.py check     # 다시 만든 것 = 파일(다르면 1)
    ml/venv/bin/python ml/scripts/famous_registry.py report    # 요약(JSON — 브랜드별 역할 수·표기)
    ml/venv/bin/python ml/scripts/famous_registry.py review    # 점검 보고(글): 대표 로고가 없는
                                                               #   브랜드·바뀐 표기·예외 낱말·
                                                               #   받을 표장
    ml/venv/bin/python ml/scripts/famous_registry.py apply 내보낸.json
                                                               # 내보낸 파일을 확인해 overrides 에
                                                               #   두고 등록부를 다시 만든 뒤 review

KIPRIS 호출 0. ml/data(비공개 데이터 저장소)가 있어야 한다. 변환표·업종 세트·식별력 통계는 기본
경로(shared/)의 것을 쓴다 — MARKLENS_GOODS_MAP_PATH 같은 환경 변수로 바꾼 채 돌리면 다른 등록부가
나온다(시험은 그 변수들을 뺀 새 프로세스에서 check 를 돌린다).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
for _root in (ML_ROOT, REPO_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from src import famous_check as fc  # noqa: E402
from src import famous_runtime as fr  # noqa: E402
from src.axes import distinctiveness as dx  # noqa: E402
from src.axes import goods_map as gm  # noqa: E402

DEFAULT_PLAN = ML_ROOT / "data" / "staging" / "famous_brands.plan.json"
DEFAULT_METADATA = ML_ROOT / "data" / "kipris_metadata.json"
DEFAULT_IMAGES = ML_ROOT / "data" / "images"
DEFAULT_MANIFEST = ML_ROOT / "data" / "index" / "kipris_manifest.json"
DEFAULT_ALIASES = REPO_ROOT / "shared" / "applicant_aliases.json"
DEFAULT_RAW_BIBLIO = ML_ROOT / "data" / "raw_kipris" / "collect" / "xml"  # 서지 응답 원본
GOODS_SHOWN = 4  # 업종 표에 보이는 대표 지정상품 수
_ENGLISH_NOTE = re.compile(r"\s*\([^()]*[A-Za-z][^()]*\)")  # 상품명에 병기한 영문 괄호
OVERRIDES_PURPOSE = (
    "유명 상표 등록부(shared/famous_registry.json)에서 사람이 정하는 값. 고르기 도구(curate.html — "
    "ml/scripts/famous_curate.py 가 만든다)의 \"내보내기\"가 이 형식으로 쓴다. 손으로 고치지 말고 "
    "`ml/scripts/famous_registry.py apply 내보낸.json` 으로 둔다. 형식은 "
    "ml/src/famous_check.parse_overrides 의 설명.")


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def applicant_key_function(aliases_path: Path = DEFAULT_ALIASES):
    """출원인 칸 → 정규화한 이름 집합(별칭 표 적용) — 이름 없는 하한 때의 규칙 그대로
    (nameless_search_thresholds.split_applicants)."""
    from scripts import nameless_search_thresholds as nst

    aliases = nst.load_aliases(aliases_path)
    return lambda text: nst.split_applicants(text, aliases)


def db_generation(manifest_path: Path = DEFAULT_MANIFEST) -> str | None:
    """DB 세대(색인 manifest 의 generation_id) — 없으면 None."""
    try:
        return json.loads(Path(manifest_path).read_text(encoding="utf-8")).get("generation_id")
    except (OSError, ValueError):
        return None


def preset_tables() -> tuple[dict, dict]:
    """업종 세트 전부의 (유사군, 이름) — 사람이 브랜드의 업종 세트를 바꿀 수 있어 전부 싣는다."""
    presets = gm.load_business_presets(gm.load_goods_map()).presets
    codes = {preset.id: sorted({code for good in preset.goods
                                for code in good.similarity_codes}) for preset in presets}
    labels = {preset.id: getattr(preset, "label", None) or getattr(preset, "name", None)
              for preset in presets}
    return codes, labels


def build(*, brands_path: Path = fc.DEFAULT_BRANDS_PATH, plan_path: Path = DEFAULT_PLAN,
          metadata_path: Path = DEFAULT_METADATA, images_dir: Path = DEFAULT_IMAGES,
          overrides_path: Path = fc.DEFAULT_OVERRIDES_PATH,
          aliases_path: Path = DEFAULT_ALIASES, overrides: dict | None = None) -> fc.Registry:
    """등록부를 만든다. overrides 를 주면 파일 대신 그 값을 쓴다(고르기 도구의 미리 보기용)."""
    rows = fc.read_brand_table(brands_path)
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    records = metadata.get("trademarks", metadata) if isinstance(metadata, dict) else metadata
    preset_codes, preset_labels = preset_tables()
    for row in rows:
        if row["preset"] not in preset_codes:
            raise ValueError(f"업종 세트가 없습니다: {row['preset']}")
    info = metadata.get("dataset_info", {}) if isinstance(metadata, dict) else {}
    sources = {
        "brands_file": "shared/famous_brands.txt", "brands_sha256": _sha256(brands_path),
        "plan": "ml/data/staging/famous_brands.plan.json", "plan_sha256": _sha256(plan_path),
        "metadata": "ml/data/kipris_metadata.json",
        "metadata_generation": (info.get("generation_id") or info.get("generation")
                                or db_generation()),
        "metadata_count": len(records),
        "overrides": "shared/famous_registry_overrides.json",
        "overrides_sha256": (_sha256(overrides_path) if Path(overrides_path).exists() else None),
        "aliases_sha256": _sha256(aliases_path),
        "note": ("표장 역할은 사람이 고른다(대표 로고(현재)·과거 로고·브랜드 이름이 든 그 밖의 "
                 "표장·관련 없음) — 고르기 전 기본값은 자동 역할(상표명으로 정한 이름·도형·다른 "
                 "이름)에서 이름 → 브랜드 이름이 든 그 밖의 표장, 도형·다른 이름 → 관련 없음. "
                 "표기 종류: 약한 표기 = 유명 예외를 뺀 식별력 판정으로 브랜드 자신의 업종에서 "
                 "조각이 모두 약한 표기(base_weak)·사람이 흔한 말로 표시한 표기(common)와 그 "
                 "표기와 소리가 0.98 이상인 표기, 머리글자 표기 = 약한 표기가 아닌 영문 3자 이하 "
                 "표기와 그 표기와 소리가 0.98 이상인 표기, 나머지는 보통 표기. 핵심 업종 = "
                 "업종 세트(industry.codes·classes)와 핵심 류(industry.core_classes — 사람이 "
                 "정함). 두 브랜드의 목록에 함께 든 표장은 상표명이 가리키는 브랜드 하나에만 잇고, "
                 "정할 수 없으면 marks[].shared 에 다른 브랜드를 적어 어느 쪽의 대표 로고로도 쓰지 "
                 "않는다."),
    }
    return fc.build_registry(
        rows, plan_records=plan["records"], db_records=records, preset_codes=preset_codes,
        preset_labels=preset_labels, dist=dx.load_distinctiveness(),
        applicant_keys=applicant_key_function(aliases_path),
        overrides=overrides if overrides is not None else fc.load_overrides(overrides_path),
        image_exists=lambda name: (Path(images_dir) / name).is_file(), sources=sources,
        preset_classes=preset_classes())


def to_text(registry: fc.Registry) -> str:
    return json.dumps(fc.registry_to_json(registry), ensure_ascii=False, indent=1) + "\n"


def overrides_text(overrides: dict) -> str:
    """overrides 파일의 글 — 설명(purpose)을 붙여 쓴다."""
    data = {"version": fc.OVERRIDES_VERSION, "purpose": OVERRIDES_PURPOSE,
            "brands": overrides["brands"]}
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def summary(registry: fc.Registry) -> dict:
    """보고용 요약 — 브랜드별 역할 수, 표기 종류, 한쪽 문자 표기만 있는 브랜드, 이름·도형 표장이
    없는 브랜드, 등록부 표기와 식별력 유명 토큰의 차이, 그리고 점검 보고의 항목(대표 로고가 없는
    브랜드·바뀐 표기·예외 낱말·받을 표장)."""
    famous = dx.famous_tokens()
    rows, weak, one_script, no_marks, token_rows = [], [], [], [], []
    kinds: dict[str, list[dict]] = {kind: [] for kind in fc.KINDS}
    for brand in registry.brands:
        counts: dict[str, int] = {}
        auto: dict[str, int] = {}
        for mark in brand.marks:
            counts[mark.role] = counts.get(mark.role, 0) + 1
            auto[mark.auto_role] = auto.get(mark.auto_role, 0) + 1
        rows.append({"브랜드": brand.name, "새_브랜드": brand.is_new, "업종": brand.preset,
                     "보호": brand.protection,
                     "표기": [n.text for n in brand.notations], "역할": counts,
                     "자동_역할": auto, "표장": len(brand.marks),
                     "대표_로고": len(brand.logo_marks),
                     "이미지_없음": sum(1 for mark in brand.marks if not mark.image_exists),
                     "업종_맥락": brand.goods_source, "근거": brand.evidence_label or "있음"})
        for notation in brand.notations:
            kinds[notation.kind].append({
                "브랜드": brand.name, "표기": notation.text, "길이": notation.length,
                "문자": notation.script, "근거": notation.kind_reason,
                "따르는_표기": list(notation.inherits)})
            if notation.base_weak:
                weak.append({"브랜드": brand.name, "표기": notation.text,
                             "사유": [f"{j['token']}: {'·'.join(j['reasons'])}"
                                    for j in notation.judgements]})
        scripts = {notation.script for notation in brand.notations}
        has_hangul = any("한글" in script for script in scripts)
        has_latin = any("영문" in script for script in scripts)
        if not (has_hangul and has_latin):
            one_script.append({"브랜드": brand.name, "표기": [n.text for n in brand.notations],
                               "있는_문자": "한글" if has_hangul else "영문"})
        if not auto.get(fc.ROLE_NAME):
            no_marks.append({"브랜드": brand.name, "이름": 0,
                             "도형": auto.get(fc.ROLE_FIGURE, 0),
                             "다른 이름": auto.get(fc.ROLE_OTHER, 0),
                             "이름·도형_둘_다_없음": not auto.get(fc.ROLE_FIGURE)})
        for notation in brand.notations:
            pieces = list(notation.pieces)
            token_rows.append({
                "브랜드": brand.name, "표기": notation.text, "조각": pieces,
                "유명_토큰에_있음": [piece for piece in pieces if piece in famous],
                "유명_토큰에_없음": [piece for piece in pieces if piece not in famous]})
    registry_pieces = {piece for row in token_rows for piece in row["조각"]}
    return {
        "브랜드": len(registry.brands), "표기": sum(len(b.notations) for b in registry.brands),
        "표장": sum(len(b.marks) for b in registry.brands), "브랜드별": rows,
        "표기_종류": {kind: len(items) for kind, items in kinds.items()},
        "약한_표기_목록": kinds[fc.KIND_WEAK], "머리글자_표기_목록": kinds[fc.KIND_INITIAL],
        "약한_표기": weak,
        "한쪽_문자만": one_script, "이름_표장_없음": no_marks,
        "점검": review(registry),
        "유명_토큰": {
            "토큰_수": len(famous),
            "등록부_조각_수": len(registry_pieces),
            "둘_다": sorted(registry_pieces & famous),
            "등록부에만": sorted(registry_pieces - famous),
            "토큰에만_수": len(famous - registry_pieces),
            "표기별": token_rows},
    }


def preset_classes() -> dict[str, list[int]]:
    """업종 세트 → 그 세트의 지정상품이 속한 류(브랜드의 핵심 업종을 류로 본 것)."""
    return fr.preset_tables(gm.load_business_presets(gm.load_goods_map()))[1]


def raw_goods(appno: str, raw_dir: Path = DEFAULT_RAW_BIBLIO) -> list[tuple[int, str]]:
    """표장의 지정상품 (류, 상품명) — 받아 둔 서지 응답 원본에서(호출 0). 원본이 없으면 빈 목록."""
    from backend.src.core import kipris_client as kc

    found = sorted(Path(raw_dir).glob(f"biblio_{appno}_*.xml")) if Path(raw_dir).is_dir() else []
    if not found:
        return []
    try:
        goods = kc.parse_bibliography_detail(found[-1].read_text(encoding="utf-8"))["goods"]
    except (kc.KiprisError, OSError, ValueError):
        return []
    out = []
    for item in goods:
        name = str(item.get("productName") or "")
        for _ in range(3):  # 겹친 괄호까지
            name = _ENGLISH_NOTE.sub("", name)
        name = " ".join(name.replace(";", " ").split())
        if str(item.get("mainCode") or "").isdigit() and name:
            out.append((int(item["mainCode"]), name))
    return out


def industry_table(registry: fc.Registry, *, classes_of: dict[str, list[int]] | None = None,
                   goods_of=None) -> list[dict]:
    """브랜드별 업종 표 — 업종 세트(와 그 류), 보호 범위, 대표 표장(대표 로고(현재)·과거 로고)이
    등록된 류와 대표 지정상품. 표시: 업종 세트가 비어 있음 / 받은 표장이 그 브랜드의 핵심 업종
    (업종 세트의 류)이 아닌 류뿐임."""
    classes_of = preset_classes() if classes_of is None else classes_of
    goods_of = raw_goods if goods_of is None else goods_of
    rows = []
    for brand in registry.brands:
        logos = brand.logo_marks
        core = set(classes_of.get(brand.preset or "", ()))
        logo_classes = sorted({nice for mark in logos for nice in mark.classes})
        counts: dict[str, list] = {}
        for mark in logos:
            for nice, name in goods_of(mark.appno):
                entry = counts.setdefault(name, [nice in core, 0, len(counts)])
                entry[1] += 1
        ranked = sorted(counts.items(), key=lambda kv: (not kv[1][0], -kv[1][1], kv[1][2]))
        received = [mark for mark in brand.marks if mark.source == fc.SOURCE_RECEIVED]
        received_classes = sorted({nice for mark in received for nice in mark.classes})
        flags = []
        if not brand.preset:
            flags.append("업종 세트 없음" + ("(핵심 류만)" if brand.core_classes else ""))
        elif received and not core & set(received_classes):
            flags.append("받은 표장이 핵심 업종 밖의 류뿐")
        rows.append({
            "브랜드": brand.name, "새_브랜드": brand.is_new, "업종_세트": brand.preset,
            "업종_세트_이름": brand.preset_label, "업종_세트의_류": sorted(core),
            "핵심_류": list(brand.core_classes), "보호": brand.protection,
            "대표_로고_현재": sum(1 for mark in logos if mark.role == fc.ROLE_LOGO_NOW),
            "대표_로고_과거": sum(1 for mark in logos if mark.role == fc.ROLE_LOGO_OLD),
            "대표_표장의_류": logo_classes,
            "대표_표장의_류_이름": [f"{nice}류 {gm.NICE_CLASS_TITLES.get(nice, '')}".strip()
                              for nice in logo_classes],
            "대표_지정상품": [name for name, _ in ranked[:GOODS_SHOWN]],
            "받은_표장": len(received), "받은_표장의_류": received_classes,
            "표시": flags})
    return rows


def review(registry: fc.Registry, *, with_industry: bool = False) -> dict:
    """점검 보고 — 대표 로고가 없는 브랜드, 지워지거나 더해진 표기와 그 종류(흔한 말 포함),
    예외 낱말, 받을 표장 목록, 새 브랜드, 보호 범위. with_industry 면 브랜드별 대표 로고 수와
    업종 표(업종 세트·대표 표장의 류·대표 지정상품)도."""
    no_logo, removed, added, common, exceptions, fetch, new, picked = [], [], [], [], [], [], [], []
    shared = []
    for brand in registry.brands:
        logos = brand.logo_marks
        if not any(mark.role == fc.ROLE_LOGO_NOW for mark in logos):
            no_logo.append({"브랜드": brand.name,
                            "과거_로고": sum(1 for m in logos if m.role == fc.ROLE_LOGO_OLD),
                            "받을_대표_로고": sum(1 for entry in brand.fetch
                                             if entry["role"] == fc.ROLE_LOGO_NOW)})
        for text in brand.removed_notations:
            removed.append({"브랜드": brand.name, "표기": text})
        for notation in brand.notations:
            row = {"브랜드": brand.name, "표기": notation.text, "종류": notation.kind,
                   "근거": notation.kind_reason}
            if notation.added and not brand.is_new:
                added.append(row)
            if notation.common:
                common.append(row)
        if brand.exceptions:
            exceptions.append({"브랜드": brand.name, "예외_낱말": list(brand.exceptions)})
        for entry in brand.fetch:
            fetch.append({"출원번호": entry["appno"], "브랜드": brand.name, "역할": entry["role"],
                          "출처": entry["source"], "상표명": entry.get("title"),
                          "출원인": entry.get("applicant")})
        if brand.is_new:
            new.append({"브랜드": brand.name,
                        "표기": [f"{n.text}({n.kind})" for n in brand.notations],
                        "출원인": list(brand.applicants), "업종": brand.preset,
                        "핵심_류": list(brand.core_classes),
                        "보호": brand.protection, "근거": brand.evidence_label or "있음",
                        "DB_표장": len(brand.marks)})
        for mark in brand.marks:
            if mark.picked:
                picked.append({"출원번호": mark.appno, "브랜드": brand.name, "역할": mark.role,
                               "자동_역할": mark.auto_role, "상표명": mark.title})
            if mark.shared:
                shared.append({"출원번호": mark.appno, "브랜드": brand.name,
                               "함께_걸린_브랜드": list(mark.shared), "역할": mark.role,
                               "상표명": mark.title, "류": list(mark.classes)})
    table = industry_table(registry) if with_industry else []
    return {
        "브랜드": len(registry.brands),
        "업종_표": table,
        "더한_출원인": [{"브랜드": b.name, "출원인": list(b.added_applicants)}
                    for b in registry.brands if b.added_applicants],
        "대표_로고(현재)가_없는_브랜드": no_logo,
        "지운_표기": removed, "더한_표기": added, "흔한_말_표기": common,
        "예외_낱말": exceptions, "받을_표장": fetch, "새_브랜드": new,
        "역할을_고른_표장": picked,
        "함께_걸린_표장": shared,
        "보호_범위": {protection: [b.name for b in registry.brands
                                 if b.protection == protection]
                    for protection in fc.PROTECTIONS},
        "근거_없음": [b.name for b in registry.brands if b.evidence_label],
        "표기_종류별": {kind: [f"{b.name}: {n.text}" for b in registry.brands
                              for n in b.notations if n.kind == kind]
                     for kind in fc.KINDS},
    }


def _short(text: str, limit: int = 22) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def review_text(data: dict) -> str:
    """점검 보고를 사람이 읽는 글로."""
    lines = [f"유명 상표 등록부 점검 — 브랜드 {data['브랜드']}개"]

    def section(title: str, rows: list, render) -> None:
        lines.append(f"\n■ {title} — {len(rows)}건" if rows else f"\n■ {title} — 없음")
        lines.extend(f"  · {render(row)}" for row in rows)

    def no_logo(row: dict) -> str:
        notes = [f"과거 로고 {row['과거_로고']}"] if row["과거_로고"] else []
        if row["받을_대표_로고"]:
            notes.append(f"받을 대표 로고 {row['받을_대표_로고']}")
        return row["브랜드"] + (f" ({', '.join(notes)})" if notes else "")

    def new_brand(row: dict) -> str:
        core = ("·".join(map(str, row["핵심_류"])) + "류") if row.get("핵심_류") else "없음"
        return (f"{row['브랜드']} — 표기 {' / '.join(row['표기'])} · 업종 세트 "
                f"{row['업종'] or '없음'} · 핵심 류 {core} · {row['보호']} · 근거 {row['근거']} "
                f"· DB 표장 {row['DB_표장']}")

    def picked(row: dict) -> str:
        return (f"{row['출원번호']} {row['브랜드']} → {row['역할']} "
                f"({row['상표명'] or '상표명 없음'})")

    section("대표 로고(현재)가 없는 브랜드", data["대표_로고(현재)가_없는_브랜드"], no_logo)
    section("지운 표기", data["지운_표기"], lambda r: f"{r['브랜드']}: {r['표기']}")
    section("더한 표기", data["더한_표기"],
            lambda r: f"{r['브랜드']}: {r['표기']} → {r['종류']}"
                      + (f" ({r['근거']})" if r["근거"] else ""))
    section("흔한 말로 표시한 표기(약한 표기와 같게 다룸)", data["흔한_말_표기"],
            lambda r: f"{r['브랜드']}: {r['표기']}")
    section("예외 낱말", data["예외_낱말"],
            lambda r: f"{r['브랜드']}: {' · '.join(r['예외_낱말'])}")
    section("새 브랜드", data["새_브랜드"], new_brand)
    section("역할을 고른 표장(DB 에 있음)", data["역할을_고른_표장"], picked)
    section("받을 표장(아직 DB 에 없음)", data["받을_표장"],
            lambda r: (f"{r['출원번호']} {r['브랜드']} → {r['역할']} [{r['출처']}]"
                       + (f" {r['상표명']}" if r["상표명"] else "")
                       + (f" · {r['출원인']}" if r["출원인"] else "")))
    section("받은 대표 표장의 출원인이라 더한 출원인", data.get("더한_출원인") or [],
            lambda r: f"{r['브랜드']}: {' / '.join(r['출원인'])}")
    section("두 브랜드에 함께 걸린 표장(정할 수 없어 어느 쪽의 대표 로고로도 쓰지 않음)",
            data.get("함께_걸린_표장") or [],
            lambda r: (f"{r['출원번호']} {r['브랜드']} ↔ {' · '.join(r['함께_걸린_브랜드'])} "
                       f"({r['상표명'] or '상표명 없음'}, {r['역할']}, 류 "
                       f"{','.join(map(str, r['류'])) or '-'})"))
    for kind, rows in data["표기_종류별"].items():
        lines.append(f"\n■ {kind} — {len(rows)}건: " + (" · ".join(rows) if rows else "없음"))
    if data.get("업종_표"):
        lines.append("\n■ 브랜드별 업종 표 — 브랜드 | 업종 세트(류) | 핵심 류 | 보호 범위 | 대표 "
                     "로고 현재·과거 | 대표 표장의 류 | 대표 지정상품 | 표시")
        for row in data["업종_표"]:
            preset = (f"{row['업종_세트']}({','.join(map(str, row['업종_세트의_류']))})"
                      if row["업종_세트"] else "없음")
            lines.append(
                f"  · {row['브랜드']} | {preset} | "
                f"{','.join(map(str, row.get('핵심_류') or ())) or '-'} | {row['보호']} | "
                f"{row['대표_로고_현재']}·"
                f"{row['대표_로고_과거']} | {','.join(map(str, row['대표_표장의_류'])) or '-'} | "
                f"{', '.join(_short(name) for name in row['대표_지정상품']) or '-'} | "
                f"{' · '.join(row['표시']) or '-'}")
    for protection, names in data["보호_범위"].items():
        lines.append(f"\n■ 보호 범위 {protection} — {len(names)}개: " + " · ".join(names))
    if data["근거_없음"]:
        lines.append(f"\n■ 근거 없음 — {len(data['근거_없음'])}개: "
                     + " · ".join(data["근거_없음"]))
    return "\n".join(lines)


def command_apply(args) -> int:
    """내보낸 파일을 확인해 shared/famous_registry_overrides.json 에 두고 등록부를 다시 만든다."""
    if args.file is None:
        raise SystemExit("apply 에는 내보낸 JSON 파일 경로가 필요합니다")
    try:
        overrides = fc.parse_overrides(json.loads(Path(args.file).read_text(encoding="utf-8")))
        registry = build(overrides=overrides)  # 먼저 만들어 본다 — 틀리면 아무것도 쓰지 않는다
    except ValueError as exc:
        print(f"[거절] {exc}")
        return 1
    fc.DEFAULT_OVERRIDES_PATH.write_text(overrides_text(overrides), encoding="utf-8")
    registry = build()  # 파일 해시(sources)를 넣어 다시
    args.out.write_text(to_text(registry), encoding="utf-8")
    print(f"썼다: {fc.DEFAULT_OVERRIDES_PATH.name} · {args.out.name} (브랜드 "
          f"{len(registry.brands)}, 표장 {sum(len(b.marks) for b in registry.brands)})\n")
    print(review_text(review(registry, with_industry=True)))
    print("\n다음: 등록부가 바뀌었으므로 확정 측정(ml/scripts/famous_check_confirm.py — "
          "freeze → base → holdout)의 확정 파일은 더 이상 이 등록부의 것이 아니다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("build", "check", "report", "review", "apply"))
    parser.add_argument("file", nargs="?", type=Path, help="apply: 고르기 도구가 내보낸 JSON")
    parser.add_argument("--out", type=Path, default=fc.DEFAULT_REGISTRY_PATH)
    parser.add_argument("--json", action="store_true", help="review 를 JSON 으로")
    args = parser.parse_args(argv)
    if args.command == "apply":
        return command_apply(args)
    registry = build()
    text = to_text(registry)
    if args.command == "build":
        args.out.write_text(text, encoding="utf-8")
        print(f"썼다: {args.out} (브랜드 {len(registry.brands)}, 표장 "
              f"{sum(len(b.marks) for b in registry.brands)})")
        return 0
    if args.command == "check":
        same = args.out.exists() and args.out.read_text(encoding="utf-8") == text
        print("같음" if same else "다름 — build 로 다시 만든다")
        return 0 if same else 1
    if args.command == "review":
        data = review(registry, with_industry=True)
        print(json.dumps(data, ensure_ascii=False, indent=1) if args.json
              else review_text(data))
        return 0
    print(json.dumps(summary(registry), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
