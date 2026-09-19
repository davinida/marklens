#!/usr/bin/env python3
"""
프론트-2 완료 기준 점검: goods_map.json 로드 -> 구조 검증 -> 검색 데모.

    python validate_goods_map.py goods_map.json
    python validate_goods_map.py goods_map.json --search 화장품
    python validate_goods_map.py goods_map.json --search "화장품 소매업"   # alias 로도 검색

검사 항목: name 비어있지 않음 / nice_class 1~45 / 유사군코드 형식 / (name, nice_class) 중복 없음 /
aliases 가 있으면 비어있지 않은 문자열 배열·중복 없음·다른 항목의 name 과 충돌 없음.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CODE_RE = re.compile(r"^[A-Za-z]\d{3,7}$")


def load(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("최상위는 배열이어야 합니다 (1:N 구조).")
    return data


def validate(entries: list[dict]) -> list[str]:
    errors = []
    seen = set()
    # aliases(제35류 병합 항목의 원 명칭)는 어떤 항목의 name 과도 겹치면 안 된다
    # (겹치면 검색 결과가 이중으로 잡힌다)
    names = {e.get("name") for e in entries if isinstance(e, dict)}
    for i, e in enumerate(entries):
        where = f"[{i}] {e.get('name')!r}"
        if not isinstance(e.get("name"), str) or not e["name"].strip():
            errors.append(f"{where}: name이 비어있음")
        if not isinstance(e.get("nice_class"), int) or not (1 <= e["nice_class"] <= 45):
            errors.append(f"{where}: nice_class가 1~45 범위의 정수가 아님 ({e.get('nice_class')!r})")
        codes = e.get("similarity_codes")
        if not isinstance(codes, list) or not codes:
            errors.append(f"{where}: similarity_codes가 비어있거나 배열이 아님")
        else:
            for c in codes:
                if not isinstance(c, str) or not CODE_RE.match(c):
                    errors.append(f"{where}: 유사군코드 형식 이상 ({c!r})")
        if "aliases" in e:
            aliases = e["aliases"]
            if (
                not isinstance(aliases, list)
                or not aliases
                or not all(isinstance(a, str) and a.strip() for a in aliases)
            ):
                errors.append(f"{where}: aliases가 비어있지 않은 문자열 배열이 아님")
            else:
                if len(set(aliases)) != len(aliases):
                    errors.append(f"{where}: aliases 중복")
                for a in aliases:
                    if a in names:
                        errors.append(f"{where}: alias {a!r}가 다른 항목의 name과 충돌")
        key = (e.get("name"), e.get("nice_class"))
        if key in seen:
            errors.append(f"{where}: 동일 (name, nice_class) 중복 행 존재")
        seen.add(key)
    return errors


def summarize(entries: list[dict]) -> None:
    multi = [e for e in entries if len(e.get("similarity_codes", [])) > 1]
    classes = sorted({e["nice_class"] for e in entries if isinstance(e.get("nice_class"), int)})
    print(f"총 {len(entries)}건")
    print(f"유사군 2개 이상 보유 = {len(multi)}건 ({len(multi) / max(len(entries), 1):.1%})")
    print(f"커버된 NICE 류 수 = {len(classes)}/45")
    missing = sorted(set(range(1, 46)) - set(classes))
    if missing:
        print(f"누락된 류: {missing}")
    with_aliases = [e for e in entries if e.get("aliases")]
    alias_total = sum(len(e["aliases"]) for e in with_aliases)
    print(f"aliases 보유 항목(제35류 병합) = {len(with_aliases)}건, alias 총 {alias_total}개")


def find_entries(entries: list[dict], query: str) -> list[tuple[dict, list[str]]]:
    """name 또는 aliases 부분 일치 검색. (항목, 일치한 alias 목록) 쌍을 돌려준다.

    name 자체가 일치하면 alias 목록은 빈 리스트 — 어느 alias 로 잡혔는지는 name 이
    일치하지 않을 때만 의미가 있다.
    """
    hits: list[tuple[dict, list[str]]] = []
    for e in entries:
        if query in e["name"]:
            hits.append((e, []))
            continue
        via = [a for a in e.get("aliases", []) if query in a]
        if via:
            hits.append((e, via))
    return hits


def search(entries: list[dict], query: str) -> None:
    hits = find_entries(entries, query)
    print(f"'{query}' 검색 결과: {len(hits)}건 (name 또는 aliases 부분 일치)")
    for e, via in hits[:10]:
        note = f"  [alias: {', '.join(via)}]" if via else ""
        print(f"  - {e['name']} (제{e['nice_class']}류) -> {e['similarity_codes']}{note}")
    if len(hits) > 10:
        print(f"  ... 외 {len(hits) - 10}건")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--search", default=None, help="완료 기준 데모: 예) --search 화장품")
    args = parser.parse_args()

    entries = load(args.json_path)
    errors = validate(entries)

    if errors:
        print(f"검증 실패: {len(errors)}건 (최대 20개 표시)", file=sys.stderr)
        for msg in errors[:20]:
            print(f"  - {msg}", file=sys.stderr)
        sys.exit(1)

    print("구조 검증 통과 (1:N, nice_class 1~45, 유사군코드 형식, aliases)")
    summarize(entries)

    if args.search:
        print()
        search(entries, args.search)


if __name__ == "__main__":
    main()
