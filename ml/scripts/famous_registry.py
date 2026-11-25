"""유명 상표 등록부 만들기 — shared/famous_registry.json (통합 모델 설계 §7-14).

입력: shared/famous_brands.txt 의 [브랜드] 표(표기·출원인·업종 세트·근거), 수집 계획
ml/data/staging/famous_brands.plan.json(출원번호 → 브랜드), DB 메타데이터
ml/data/kipris_metadata.json,
사람이 정한 값 shared/famous_registry_overrides.json(보호 범위·표장 역할). 등록부의 내용과 규칙은
`src.famous_check`(build_registry·analyze_notation) — 이 스크립트는 파일을 읽고 쓰는 일만 한다.

    ml/venv/bin/python ml/scripts/famous_registry.py build     # shared/famous_registry.json 을 쓴다
    ml/venv/bin/python ml/scripts/famous_registry.py check     # 다시 만든 것 = 파일(다르면 1)
    ml/venv/bin/python ml/scripts/famous_registry.py report    # 요약 표(브랜드별 역할 수·표기·차이)

KIPRIS 호출 0. ml/data(비공개 데이터 저장소)가 있어야 한다. 변환표·업종 세트·식별력 통계는 기본
경로(shared/)의 것을 쓴다 — MARKLENS_GOODS_MAP_PATH 같은 환경 변수로 바꾼 채 돌리면 다른 등록부가
나온다(시험은 그 변수들을 뺀 새 프로세스에서 check 를 돌린다).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
for _root in (ML_ROOT, REPO_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from src import famous_check as fc  # noqa: E402
from src.axes import distinctiveness as dx  # noqa: E402
from src.axes import goods_map as gm  # noqa: E402

DEFAULT_PLAN = ML_ROOT / "data" / "staging" / "famous_brands.plan.json"
DEFAULT_METADATA = ML_ROOT / "data" / "kipris_metadata.json"
DEFAULT_IMAGES = ML_ROOT / "data" / "images"
DEFAULT_ALIASES = REPO_ROOT / "shared" / "applicant_aliases.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def applicant_key_function(aliases_path: Path = DEFAULT_ALIASES):
    """출원인 칸 → 정규화한 이름 집합(별칭 표 적용) — 이름 없는 하한 때의 규칙 그대로
    (nameless_search_thresholds.split_applicants)."""
    from scripts import nameless_search_thresholds as nst

    aliases = nst.load_aliases(aliases_path)
    return lambda text: nst.split_applicants(text, aliases)


def build(*, brands_path: Path = fc.DEFAULT_BRANDS_PATH, plan_path: Path = DEFAULT_PLAN,
          metadata_path: Path = DEFAULT_METADATA, images_dir: Path = DEFAULT_IMAGES,
          overrides_path: Path = fc.DEFAULT_OVERRIDES_PATH,
          aliases_path: Path = DEFAULT_ALIASES) -> fc.Registry:
    rows = fc.read_brand_table(brands_path)
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    records = metadata.get("trademarks", metadata) if isinstance(metadata, dict) else metadata
    goods_map = gm.load_goods_map()
    presets = gm.load_business_presets(goods_map)
    preset_codes, preset_labels = {}, {}
    for row in rows:
        preset = presets.get(row["preset"])
        if preset is None:
            raise ValueError(f"업종 세트가 없습니다: {row['preset']}")
        preset_codes[row["preset"]] = sorted(
            {code for good in preset.goods for code in good.similarity_codes})
        preset_labels[row["preset"]] = getattr(preset, "label", None) or getattr(
            preset, "name", None)
    info = metadata.get("dataset_info", {}) if isinstance(metadata, dict) else {}
    sources = {
        "brands_file": "shared/famous_brands.txt", "brands_sha256": _sha256(brands_path),
        "plan": "ml/data/staging/famous_brands.plan.json", "plan_sha256": _sha256(plan_path),
        "metadata": "ml/data/kipris_metadata.json",
        "metadata_generation": info.get("generation_id") or info.get("generation"),
        "metadata_count": len(records),
        "overrides": "shared/famous_registry_overrides.json",
        "overrides_sha256": (_sha256(overrides_path) if Path(overrides_path).exists() else None),
        "aliases_sha256": _sha256(aliases_path),
        "note": ("표장 역할은 자동(이름·도형·다른 이름) 뒤 overrides 로 덮는다. 표기 종류: 약한 "
                 "표기 = 유명 예외를 뺀 식별력 판정으로 브랜드 자신의 업종에서 조각이 모두 약한 "
                 "표기(base_weak)와 그 표기와 소리가 0.98 이상인 표기, 머리글자 표기 = 약한 표기가 "
                 "아닌 영문 3자 이하 표기와 그 표기와 소리가 0.98 이상인 표기, 나머지는 보통 "
                 "표기."),
    }
    return fc.build_registry(
        rows, plan_records=plan["records"], db_records=records, preset_codes=preset_codes,
        preset_labels=preset_labels, dist=dx.load_distinctiveness(),
        applicant_keys=applicant_key_function(aliases_path),
        overrides=fc.load_overrides(overrides_path),
        image_exists=lambda name: (Path(images_dir) / name).is_file(), sources=sources)


def to_text(registry: fc.Registry) -> str:
    return json.dumps(fc.registry_to_json(registry), ensure_ascii=False, indent=1) + "\n"


def summary(registry: fc.Registry) -> dict:
    """보고용 요약 — 브랜드별 역할 수, 표기 종류, 한쪽 문자 표기만 있는 브랜드, 이름·도형 표장이
    없는 브랜드, 등록부 표기와 식별력 유명 토큰의 차이."""
    famous = dx.famous_tokens()
    rows, weak, one_script, no_marks, token_rows = [], [], [], [], []
    kinds: dict[str, list[dict]] = {kind: [] for kind in fc.KINDS}
    for brand in registry.brands:
        counts: dict[str, int] = {}
        for mark in brand.marks:
            counts[mark.role] = counts.get(mark.role, 0) + 1
        rows.append({"브랜드": brand.name, "업종": brand.preset, "보호": brand.protection,
                     "표기": [n.text for n in brand.notations], "역할": counts,
                     "표장": len(brand.marks),
                     "이미지_없음": sum(1 for mark in brand.marks if not mark.image_exists),
                     "업종_맥락": brand.goods_source})
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
        if not counts.get(fc.ROLE_NAME):
            no_marks.append({"브랜드": brand.name, "이름": 0,
                             "도형": counts.get(fc.ROLE_FIGURE, 0),
                             "다른 이름": counts.get(fc.ROLE_OTHER, 0),
                             "이름·도형_둘_다_없음": not counts.get(fc.ROLE_FIGURE)})
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
        "유명_토큰": {
            "토큰_수": len(famous),
            "등록부_조각_수": len(registry_pieces),
            "둘_다": sorted(registry_pieces & famous),
            "등록부에만": sorted(registry_pieces - famous),
            "토큰에만_수": len(famous - registry_pieces),
            "표기별": token_rows},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("build", "check", "report"))
    parser.add_argument("--out", type=Path, default=fc.DEFAULT_REGISTRY_PATH)
    args = parser.parse_args(argv)
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
    print(json.dumps(summary(registry), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
