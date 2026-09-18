#!/usr/bin/env python3
"""DB 상표명에서 국내 브랜드 로마자 후보를 캔다 — 사람 승인용 도구 (자동 반영 금지).

대상: ml/data/kipris_metadata.json 의 상표한글명 중 한글 토큰과 영문 토큰이 함께 있는 것.
각 (영문 토큰, 한글 토큰) 쌍에 대해 순수 룰 G2P(g2p_benchmark)와 한글 토큰의 음절 유사도를
계산한다.

후보 조건 (한 쌍이 여러 상표명에 나오면 출현수를 센다):
  - 영문 토큰 길이 ≥ 3, 기능어·회사형태(UNIVERSAL_GENERIC) 제외
  - 0.4 ≤ 유사도 < 0.8 → "후보" (병기로 보이는데 룰이 못 읽는 구간)
  - 브랜드 표·지명 표·예외 사전(G2P_EXCEPTIONS)에 이미 있는 영문 토큰은 "후보" 대신
    "확인됨" 으로 표시. 표의 한글 값과 한글 토큰이 같은 쌍은 유사도 구간과 무관하게
    "확인됨" (표가 DB 로 뒷받침됨).

출력: ml/data/staging/x1_romanization_candidates.csv (영문, 한글, 룰읽기, 유사도, 출현수, 상태)
      빈도순 정렬 + 상위 50건 화면 출력.
      승인한 항목은 사람이 ml/src/axes/korean_brands.py 로 옮긴다.
추가로 메타데이터의 별도 영문 필드(상표영문명) 보유 현황을 보고한다.

실행 (프로젝트 루트):
    ml/venv/bin/python ml/scripts/x1_mine_romanization.py \
        [--metadata PATH] [--output PATH] [--top 50]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from src.axes.korean_brands import (  # noqa: E402
    KOREAN_BRAND_ROMANIZATION,
    KOREAN_PLACE_ROMANIZATION,
)
from src.axes.x1_phonetic import (  # noqa: E402
    G2P_EXCEPTIONS,
    _char_class,
    _normalize_tokens,
    _syllable_sim,
    g2p_benchmark,
)

MIN_LATIN_LEN = 3
CANDIDATE_LOW = 0.4
CANDIDATE_HIGH = 0.8
ENGLISH_NAME_FIELD = "상표영문명"
KOREAN_NAME_FIELD = "상표한글명"


def _records(metadata: Path) -> list[dict]:
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    return [r for r in payload.get("trademarks", []) if isinstance(r, dict)]


def mine(records: list[dict]) -> tuple[list[dict], int]:
    """(후보·확인됨 행 목록, 한영 혼재 상표명 수). 행은 출현수·유사도 내림차순."""
    counts: Counter[tuple[str, str]] = Counter()
    mixed = 0
    for record in records:
        name = record.get(KOREAN_NAME_FIELD)
        if not isinstance(name, str) or not name.strip():
            continue
        _pre, post = _normalize_tokens(name, frozenset())  # post: 기능어·회사형태 제거 후
        hangul = [t for t in post if _char_class(t[0]) == "H"]
        latin = [t for t in post if _char_class(t[0]) == "L" and len(t) >= MIN_LATIN_LEN]
        if not hangul or not latin:
            continue
        mixed += 1
        for en in latin:
            for ko in hangul:
                counts[(en, ko)] += 1

    rows: list[dict] = []
    for (en, ko), seen in counts.items():
        reading = g2p_benchmark(en)
        score = _syllable_sim(reading, ko) if reading else 0.0
        in_range = CANDIDATE_LOW <= score < CANDIDATE_HIGH
        table_value = (
            KOREAN_BRAND_ROMANIZATION.get(en)
            or KOREAN_PLACE_ROMANIZATION.get(en)
            or G2P_EXCEPTIONS.get(en)
        )
        if table_value is not None and (table_value == ko or in_range):
            status = "확인됨"
        elif table_value is None and in_range:
            status = "후보"
        else:
            continue
        rows.append(
            {"영문": en, "한글": ko, "룰읽기": reading, "유사도": round(score, 3),
             "출현수": seen, "상태": status}
        )
    rows.sort(key=lambda r: (-r["출현수"], -r["유사도"], r["영문"]))
    return rows, mixed


def report_english_field(records: list[dict]) -> None:
    filled = [r for r in records if str(r.get(ENGLISH_NAME_FIELD) or "").strip()]
    with_korean = [r for r in filled if str(r.get(KOREAN_NAME_FIELD) or "").strip()]
    unique_pairs = list(
        dict.fromkeys((r[KOREAN_NAME_FIELD], r[ENGLISH_NAME_FIELD]) for r in with_korean)
    )
    print(f"## 별도 영문 필드 '{ENGLISH_NAME_FIELD}'")
    print(
        f"- 값 있음: {len(filled)}/{len(records)}건, "
        f"그중 상표한글명도 있는 것: {len(with_korean)}건 (중복 제외 {len(unique_pairs)}쌍)"
    )
    for korean, english in unique_pairs[:10]:
        print(f"  - {korean!r} | {english!r}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="X1 국내 브랜드 로마자 후보 캐기")
    parser.add_argument(
        "--metadata", type=Path, default=ML_ROOT / "data" / "kipris_metadata.json"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ML_ROOT / "data" / "staging" / "x1_romanization_candidates.csv",
    )
    parser.add_argument("--top", type=int, default=50)
    args = parser.parse_args()

    if not args.metadata.exists():
        print(f"[오류] 메타데이터가 없습니다: {args.metadata}", file=sys.stderr)
        return 1
    records = _records(args.metadata)
    rows, mixed = mine(records)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["영문", "한글", "룰읽기", "유사도", "출현수", "상태"]
        )
        writer.writeheader()
        writer.writerows(rows)

    candidates = sum(1 for r in rows if r["상태"] == "후보")
    confirmed = len(rows) - candidates
    print(
        f"## 로마자 후보 캐기 — 한영 혼재 상표명 {mixed}건, "
        f"후보 {candidates}건, 확인됨 {confirmed}건"
    )
    print(f"CSV: {args.output}\n")
    print("| # | 영문 | 한글 | 룰읽기 | 유사도 | 출현수 | 상태 |")
    print("|---:|---|---|---|---:|---:|---|")
    for index, row in enumerate(rows[: args.top], start=1):
        print(
            f"| {index} | {row['영문']} | {row['한글']} | {row['룰읽기']} | {row['유사도']:.3f} | "
            f"{row['출현수']} | {row['상태']} |"
        )
    print()
    report_english_field(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
