#!/usr/bin/env python3
"""
프론트-2: 특허청/지식재산처 "고시상품명칭" 엑셀 -> [상품명, 류, 유사군코드] JSON 변환.

원본: 지식재산처 고시상품명칭 13판(2026)
  https://www.kipo.go.kr/ko/kpoContFileDown.do?seq=26&fileNum=19
  (지식재산처 홈페이지 > 지식재산제도 > 분류코드조회 > 상품분류코드 에서도 찾을 수 있음)
  ※ 헤더 없는 curl 은 403(WAF)이 날 수 있음 — README §1의 UA·referer 예시 또는 브라우저로 받는다.

사용법:
    # 1) 먼저 실제 컬럼 구조를 모른 채로 파싱하면 안 되므로, 시트/헤더를 확인한다.
    python parse_goods_map.py inspect raw/고시상품명칭_13판.xlsx

    # 2) 확인한 컬럼명(또는 열 문자, 예: "B")을 지정해 변환한다.
    python parse_goods_map.py convert raw/고시상품명칭_13판.xlsx \\
        --name-col 상품명 --class-col 류 --codes-col 유사군코드 \\
        --out goods_map.json --gzip
    # --gzip: goods_map.json.gz 도 만든다 — 백엔드·로더(ml/src/axes/goods_map.py)가 우선 읽는 파일

출력 스키마 (1:N 필수 — 한 상품에 유사군 코드가 여러 개 붙을 수 있음):
    [{ "name": "화장품", "nice_class": 3, "similarity_codes": ["G1201", "S120907", "S128302"] }]
    제35류 도소매업 6종을 하나로 합친 항목에만 "aliases": [합쳐진 원 명칭 6개] 가 추가된다.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path


def _load_workbook(path: Path):
    """엑셀을 읽기 전용으로 연다. openpyxl 은 inspect/convert 를 실제로 돌릴 때만 필요하므로
    여기서 지연 import 한다 — 순수 함수(_collapse_class35_services 등)의 단위 테스트가
    openpyxl 이 없는 CI 에서도 이 모듈을 import 할 수 있게 하기 위함이다."""
    try:
        from openpyxl import load_workbook
    except ImportError:
        print(
            "openpyxl이 없습니다. 먼저 설치하세요:\n"
            "  ml/venv/bin/python -m pip install -r shared/goods_map/requirements.txt",
            file=sys.stderr,
        )
        raise
    return load_workbook(path, read_only=True, data_only=True)


# 유사군코드 형식: 문자(류 그룹) + 숫자 4자리 내외 (예: G1201, S120907, M1201)
CODE_RE = re.compile(r"[A-Za-z]\d{3,7}")
# 상품명 셀 안에서 여러 유사군코드를 나누는 구분자 후보
CODE_SPLIT_RE = re.compile(r"[,\s/|、，]+")


def _col_letter_to_index(letter: str) -> int | None:
    """'B' 같은 엑셀 열 문자를 0-based 인덱스로. 헤더 텍스트면 None."""
    if re.fullmatch(r"[A-Za-z]{1,3}", letter):
        idx = 0
        for ch in letter.upper():
            idx = idx * 26 + (ord(ch) - ord("A") + 1)
        return idx - 1
    return None


def _find_header_row(rows: list[tuple], max_scan: int = 15) -> int:
    """빈 행/병합 안내 행을 건너뛰고 실제 헤더로 보이는 첫 행의 인덱스를 추정."""
    for i, row in enumerate(rows[:max_scan]):
        non_empty = [c for c in row if c not in (None, "")]
        if len(non_empty) >= 2:
            return i
    return 0


def inspect(path: Path, max_rows: int = 5) -> None:
    wb = _load_workbook(path)
    print(f"파일: {path}")
    print(f"시트 목록: {wb.sheetnames}\n")
    for name in wb.sheetnames:
        ws = wb[name]
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            rows.append(row)
            if i >= 30:
                break
        header_idx = _find_header_row(rows)
        print(f"--- 시트 '{name}' ({len(rows)}행 미리보기 로드) ---")
        print(f"추정 헤더 행(0-based): {header_idx} -> {rows[header_idx] if rows else '(빈 시트)'}")
        for r in rows[header_idx + 1 : header_idx + 1 + max_rows]:
            print("  ", r)
        print()


def _resolve_index(header: tuple, spec: str) -> int:
    letter_idx = _col_letter_to_index(spec)
    if letter_idx is not None and letter_idx < len(header):
        return letter_idx
    for i, cell in enumerate(header):
        if cell is not None and spec.strip() in str(cell).strip():
            return i
    raise SystemExit(
        f"컬럼 '{spec}'을 헤더 {header} 에서 찾지 못했습니다. "
        f"먼저 `inspect`로 실제 헤더를 확인하세요."
    )


# 제35류 소매/도매업 고시는 상품마다 "OOO 도매업/소매업/중개업/판매대행업/판매알선업/구매대행업"
# 6종이 동일한 유사군코드로 기계적으로 반복 생성된다 (실측: base 상품 38,445건 중
# 38,433건이 6종 전부 동일 코드). 코드 기준 유사도 판단(X4)에는 중복 정보라 하나로 합친다.
_CLASS35_SERVICE_SUFFIXES = (
    "도매업", "소매업", "중개업", "판매대행업", "판매알선업", "구매대행업",
)


def _collapse_class35_services(
    merged: dict[tuple[str, int], set[str]]
) -> list[dict]:
    suffix_re = re.compile("(" + "|".join(_CLASS35_SERVICE_SUFFIXES) + ")$")
    # base 상품 -> {접미사: (원 명칭, 코드)}. 원 명칭은 병합 항목의 aliases 로 보존한다.
    groups: dict[str, dict[str, tuple[str, tuple[str, ...]]]] = {}
    passthrough: dict[tuple[str, int], set[str]] = {}

    for (name, nice_class), codes in merged.items():
        m = suffix_re.search(name) if nice_class == 35 else None
        if not m:
            passthrough[(name, nice_class)] = codes
            continue
        base = name[: -len(m.group(1))].strip()
        groups.setdefault(base, {})[m.group(1)] = (name, tuple(sorted(codes)))

    result = [
        {"name": name, "nice_class": nice_class, "similarity_codes": sorted(codes)}
        for (name, nice_class), codes in passthrough.items()
    ]

    for base, by_suffix in groups.items():
        code_sets = {codes for _name, codes in by_suffix.values()}
        if len(code_sets) == 1 and len(by_suffix) == len(_CLASS35_SERVICE_SUFFIXES):
            # 6종 전부 존재 + 코드 완전히 동일 -> 하나로 합친다.
            # 합쳐진 원 명칭 전부를 aliases 로 보존한다(접미사 상수 순, 중복 없음).
            # 프론트-6 상품 검색이 원 명칭("화장품 소매업")으로도 찾을 수 있게 하기 위함.
            (codes,) = code_sets
            result.append(
                {
                    "name": f"{base} 판매업(도소매·중개·대행)",
                    "nice_class": 35,
                    "similarity_codes": list(codes),
                    "aliases": [by_suffix[suffix][0] for suffix in _CLASS35_SERVICE_SUFFIXES],
                }
            )
        else:
            # 일부만 존재하거나 접미사별로 코드가 다르면 정보 손실 방지를 위해 원 명칭 그대로 유지
            for original_name, codes in by_suffix.values():
                result.append(
                    {
                        "name": original_name,
                        "nice_class": 35,
                        "similarity_codes": list(codes),
                    }
                )

    result.sort(key=lambda e: (e["name"], e["nice_class"]))
    return result


def convert(
    path: Path,
    out_path: Path,
    name_col: str,
    class_col: str | None,
    codes_col: str,
    sheet: str | None,
    gzip_out: bool = False,
) -> None:
    wb = _load_workbook(path)
    sheets = [sheet] if sheet else wb.sheetnames

    entries: list[dict] = []
    skipped = 0

    for sheet_name in sheets:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header_idx = _find_header_row(rows)
        header = rows[header_idx]

        name_idx = _resolve_index(header, name_col)
        codes_idx = _resolve_index(header, codes_col)
        class_idx = _resolve_index(header, class_col) if class_col else None

        # 클래스 컬럼이 없으면 시트 이름에서 류 번호를 추정 (예: "3류", "제3류")
        sheet_class_guess = None
        if class_idx is None:
            m = re.search(r"\d{1,2}", sheet_name)
            sheet_class_guess = int(m.group()) if m else None

        for row in rows[header_idx + 1 :]:
            if name_idx >= len(row) or codes_idx >= len(row):
                continue
            name = row[name_idx]
            codes_raw = row[codes_idx]
            if not name or not codes_raw:
                skipped += 1
                continue

            nice_class = None
            if class_idx is not None and class_idx < len(row) and row[class_idx] is not None:
                m = re.search(r"\d{1,2}", str(row[class_idx]))
                nice_class = int(m.group()) if m else None
            elif sheet_class_guess is not None:
                nice_class = sheet_class_guess

            codes = sorted(set(CODE_RE.findall(str(codes_raw))))
            if not codes:
                # 정규식이 안 맞으면 구분자 기준으로라도 분리해서 넣는다 (수동 검수 대상)
                codes = [c for c in CODE_SPLIT_RE.split(str(codes_raw).strip()) if c]

            if not codes or nice_class is None:
                skipped += 1
                continue

            entries.append(
                {
                    "name": str(name).strip(),
                    "nice_class": nice_class,
                    "similarity_codes": codes,
                }
            )

    # 같은 상품명이 여러 행에 걸쳐 있으면 유사군코드를 합친다 (1:N 유지)
    merged: dict[tuple[str, int], set[str]] = {}
    for e in entries:
        key = (e["name"], e["nice_class"])
        merged.setdefault(key, set()).update(e["similarity_codes"])

    result = _collapse_class35_services(merged)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    out_path.write_text(text, encoding="utf-8")

    multi = sum(1 for e in result if len(e["similarity_codes"]) > 1)
    print(f"변환 완료: {len(result)}건 (유사군 2개 이상 = {multi}건, 건너뜀 = {skipped}행)")
    print(f"저장: {out_path}")
    if gzip_out:
        # 로더(ml/src/axes/goods_map.py)·백엔드가 우선 읽는 압축본. mtime=0 → 같은 입력이면 같은 바이트.
        gz_path = out_path.with_name(out_path.name + ".gz")
        with gz_path.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as handle:
                handle.write(text.encode("utf-8"))
        print(f"gzip 저장: {gz_path} ({gz_path.stat().st_size / 1e6:.1f}MB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="시트/헤더/샘플 행을 출력해 구조를 확인")
    p_inspect.add_argument("xlsx", type=Path)
    p_inspect.add_argument("--rows", type=int, default=5)

    p_convert = sub.add_parser("convert", help="확인한 컬럼으로 실제 변환 실행")
    p_convert.add_argument("xlsx", type=Path)
    p_convert.add_argument("--out", type=Path, default=Path("shared/goods_map/goods_map.json"))
    p_convert.add_argument("--sheet", default=None, help="미지정 시 모든 시트를 순회")
    p_convert.add_argument("--name-col", required=True, help="상품명 컬럼 (헤더 텍스트 또는 'B' 같은 열 문자)")
    p_convert.add_argument("--class-col", default=None, help="류 컬럼. 없으면 시트 이름에서 추정")
    p_convert.add_argument("--codes-col", required=True, help="유사군코드 컬럼")
    p_convert.add_argument(
        "--gzip",
        action="store_true",
        help="goods_map.json.gz 도 함께 생성(백엔드·로더가 우선 읽는 파일)",
    )

    args = parser.parse_args()

    if args.command == "inspect":
        inspect(args.xlsx, max_rows=args.rows)
    elif args.command == "convert":
        convert(
            args.xlsx,
            args.out,
            name_col=args.name_col,
            class_col=args.class_col,
            codes_col=args.codes_col,
            sheet=args.sheet,
            gzip_out=args.gzip,
        )


if __name__ == "__main__":
    main()
