#!/usr/bin/env python3
"""X1 호칭 유사도 보고 스크립트 (assert 없음 — 점수만 표로 출력, 기대값은 사람이 정한다).

출력 항목:
  1. G2P 20단어 표본: 브랜드·지명 표와 예외 사전을 끈 순수 룰(g2p_benchmark)과 정답의 음절 유사도
  2. C. 보고 전용 쌍: 점수와 양쪽 발음 후보
  3. 데이터 표본: ml/data/kipris_metadata.json 의 상표한글명에서 무작위 30건을 뽑아 인접 쌍 점수
  4. 성능: 데이터에서 만든 1,000쌍 phonetic_similarity 소요 시간
  5. (--baseline) 변경 전 점수와 비교: 달라진 C 쌍과 표본 30쌍 평균 변화폭(0.05 이상 상승 시 경고)

실행 (프로젝트 루트):
    ml/venv/bin/python ml/scripts/x1_report.py [--metadata PATH] [--seed N]
        [--baseline ml/data/staging/x1_baseline_v1.json] [--dump-scores PATH]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from src.axes.x1_phonetic import (  # noqa: E402
    _syllable_sim,
    g2p_benchmark,
    phonetic_similarity,
    pronunciation_candidates,
)

DEFAULT_BASELINE = ML_ROOT / "data" / "staging" / "x1_baseline_v1.json"
MEAN_SHIFT_WARNING = 0.05

# 정답은 외래어 표기법 기준. v1 20단어 + v1.4(2026-09-18) DB 빈출 일반 영단어 40개 = 60단어.
# 브랜드 고유명은 넣지 않는다(브랜드표는 벤치마크에서 꺼져 있다). 정답이 확실한 것만.
G2P_SAMPLE: list[tuple[str, str]] = [
    # --- v1 (20)
    ("STARBUCKS", "스타벅스"), ("MONTEROSA", "몬테로사"), ("SAMSUNG", "삼성"), ("COFFEE", "커피"),
    ("NIKE", "나이키"), ("APPLE", "애플"), ("GOOGLE", "구글"), ("BURGER", "버거"), ("KING", "킹"),
    ("STAR", "스타"), ("BLUE", "블루"), ("ORANGE", "오렌지"), ("CENTER", "센터"), ("PARIS", "파리"),
    ("GLOBAL", "글로벌"), ("TOUR", "투어"), ("PASS", "패스"), ("HOUSE", "하우스"),
    ("STUDIO", "스튜디오"), ("LEMON", "레몬"),
    # --- v1.4 DB 빈출 일반 영단어 (40) — science·beauty·design 필수 포함
    ("SCIENCE", "사이언스"), ("BEAUTY", "뷰티"), ("DESIGN", "디자인"), ("KITCHEN", "키친"),
    ("FRIENDS", "프렌즈"), ("MOTORS", "모터스"), ("CLUB", "클럽"), ("LIFE", "라이프"),
    ("TALK", "토크"), ("HEALTH", "헬스"), ("AIR", "에어"), ("PARK", "파크"),
    ("TIGERS", "타이거스"), ("ENTERTAINMENT", "엔터테인먼트"), ("LOVE", "러브"), ("HOT", "핫"),
    ("SKY", "스카이"), ("AUTO", "오토"), ("LIVING", "리빙"), ("MAKE", "메이크"),
    ("FUTURE", "퓨처"), ("ESPRESSO", "에스프레소"), ("HEAVEN", "헤븐"), ("EXPRESS", "익스프레스"),
    ("KOREAN", "코리안"), ("SPRING", "스프링"), ("GOOD", "굿"), ("SMART", "스마트"),
    ("NATURE", "네이처"), ("BIO", "바이오"), ("SWEET", "스위트"), ("PERFORMANCE", "퍼포먼스"),
    ("CHEESE", "치즈"), ("CLINIC", "클리닉"), ("ESSENTIAL", "에센셜"), ("BIG", "빅"),
    ("KIDS", "키즈"), ("DAY", "데이"), ("SINCE", "신스"), ("CONTENTS", "콘텐츠"),
]

# (A, B, extra_generic)
REPORT_PAIRS: list[tuple[str, str, frozenset[str]]] = [
    ("나이키", "마이키", frozenset()),
    ("리쥬", "리주", frozenset()),
    ("태백투어패스", "화천투어패스", frozenset()),
    ("블루 커피", "레드 커피", frozenset({"커피"})),
    ("몬테로사", "MONTEROSA", frozenset()),
    ("서울바쿠테", "바쿠테", frozenset()),
    ("스타벅스", "스타벅스커피", frozenset()),
    ("7-ELEVEN", "세븐일레븐", frozenset()),
    ("3M", "쓰리엠", frozenset()),
    ("THE NORTH FACE", "노스페이스", frozenset()),
    ("노스페이스 THE NORTH FACE", "노스페이스", frozenset()),
    ("나이스", "NICE", frozenset()),
    ("코카콜라", "코카-콜라", frozenset()),
    ("애플", "APPLE", frozenset()),
    ("애플", "사과", frozenset()),
    ("KR", "케이알", frozenset()),
    # 슬로건형(제거 후 4토큰 이상)은 전체관찰만 — 분리관찰 상한 도입(2026-09-17) 후 관찰용
    ("창창대로 SCIENCE START-UP PARK", "스타박스", frozenset()),
    ("HYUNDAI MOTOR GROUP Together for a better future", "현대", frozenset()),
    # v1.3.1 (2026-09-18): 병기형 한글 토큰 분리관찰, 결합어 포함 검사, extra_generic 읽기
    ("잇버거 EAT PREMIUM BURGER", "잇버거", frozenset()),
    ("BLUE COFFEE", "RED COFFEE", frozenset({"커피"})),
    ("STARBUCKS COFFEE", "스타벅스", frozenset({"커피"})),
]


def benchmark_rows(words: list[tuple[str, str]] = G2P_SAMPLE) -> list[tuple[str, str, str, float]]:
    """(단어, 정답, 순수 룰 읽기, 음절 유사도). 브랜드 표·예외 사전은 쓰지 않는다."""
    rows = []
    for word, answer in words:
        reading = g2p_benchmark(word.lower())
        rows.append((word, answer, reading, _syllable_sim(reading, answer)))
    return rows


def _load_names(metadata: Path) -> list[str]:
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    names = []
    for record in payload.get("trademarks", []):
        name = record.get("상표한글명")
        if isinstance(name, str) and name.strip():
            names.append(name)
    return names


def _pair_key(a: str, b: str, generic: frozenset[str]) -> str:
    return f"{a}\t{b}\t{','.join(sorted(generic))}"


def _sample_pairs(names: list[str], seed: int) -> list[tuple[str, str]]:
    rng = random.Random(seed)
    sample = rng.sample(names, min(30, len(names)))
    return [(a, sample[(index + 1) % len(sample)]) for index, a in enumerate(sample)]


def _print_g2p_sample() -> None:
    print("## 1. G2P 20단어 표본 — 순수 룰(브랜드·지명 표·예외 사전 비활성) vs 정답")
    print("| 단어 | 정답 | 룰 결과 | 음절 유사도 |")
    print("|---|---|---|---:|")
    rows = benchmark_rows()
    for word, answer, reading, score in rows:
        print(f"| {word} | {answer} | {reading} | {score:.3f} |")
    exact = sum(1 for _w, answer, reading, _s in rows if reading == answer)
    average = sum(score for *_rest, score in rows) / len(rows)
    print(f"\n정확 일치 {exact}/{len(rows)}, 평균 음절 유사도 {average:.3f}\n")


def _print_report_pairs() -> dict[str, float]:
    print("## 2. C. 보고 전용 쌍 (assert 없음)")
    print("| A | B | extra_generic | 점수 | 후보 A | 후보 B |")
    print("|---|---|---|---:|---|---|")
    scores: dict[str, float] = {}
    for a, b, generic in REPORT_PAIRS:
        score = phonetic_similarity(a, b, extra_generic=generic)
        scores[_pair_key(a, b, generic)] = score
        cand_a = ", ".join(pronunciation_candidates(a, extra_generic=generic))
        cand_b = ", ".join(pronunciation_candidates(b, extra_generic=generic))
        generic_text = ", ".join(sorted(generic)) if generic else ""
        print(f"| {a} | {b} | {generic_text} | {score:.3f} | {cand_a} | {cand_b} |")
    print()
    return scores


def _print_data_sample(names: list[str], seed: int) -> dict[str, float]:
    print(f"## 3. 데이터 표본 30건 인접 쌍 (seed={seed}, 총 {len(names)}건 중 표본)")
    scores: dict[str, float] = {}
    if len(names) < 2:
        print("(상표한글명 데이터가 없습니다)\n")
        return scores
    print("| A | B | 점수 | 후보 A | 후보 B |")
    print("|---|---|---:|---|---|")
    for a, b in _sample_pairs(names, seed):
        score = phonetic_similarity(a, b)
        scores[f"{a}\t{b}"] = score
        cand_a = ", ".join(pronunciation_candidates(a))
        cand_b = ", ".join(pronunciation_candidates(b))
        print(f"| {a} | {b} | {score:.3f} | {cand_a} | {cand_b} |")
    mean = sum(scores.values()) / len(scores)
    print(f"\n표본 30쌍 평균 점수: {mean:.4f}\n")
    return scores


def _print_timing(names: list[str], seed: int) -> None:
    print("## 4. 성능 — 데이터 상표명 1,000쌍 (cold cache)")
    if len(names) < 2:
        print("(데이터 없음)\n")
        return
    rng = random.Random(seed + 1)
    pairs = [(rng.choice(names), rng.choice(names)) for _ in range(1000)]
    started = time.perf_counter()
    for a, b in pairs:
        phonetic_similarity(a, b)
    elapsed = time.perf_counter() - started
    print(f"1,000쌍: {elapsed:.3f}s (쌍당 {elapsed / 1000 * 1000:.2f}ms)\n")


def _print_baseline_diff(
    baseline_path: Path, report_scores: dict[str, float], sample_scores: dict[str, float]
) -> None:
    print(f"## 5. 변경 전후 비교 (기준선: {baseline_path})")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    before_report = baseline.get("report_pairs", {})
    before_sample = baseline.get("sample_pairs", {})

    print("### 달라진 C 쌍")
    print("| A | B | extra_generic | 변경 전 | 변경 후 | 차이 |")
    print("|---|---|---|---:|---:|---:|")
    changed = 0
    for key, after in report_scores.items():
        before = before_report.get(key)
        if before is None or abs(after - before) < 0.0005:
            continue
        a, b, generic = key.split("\t")
        print(f"| {a} | {b} | {generic} | {before:.3f} | {after:.3f} | {after - before:+.3f} |")
        changed += 1
    if not changed:
        print("| (변화 없음) | | | | | |")

    common = [k for k in sample_scores if k in before_sample]
    print("\n### 표본 30쌍")
    if not common:
        print("(기준선과 표본이 일치하지 않아 비교 불가)\n")
        return
    mean_before = sum(before_sample[k] for k in common) / len(common)
    mean_after = sum(sample_scores[k] for k in common) / len(common)
    shift = mean_after - mean_before
    changed_pairs = [k for k in common if abs(sample_scores[k] - before_sample[k]) >= 0.0005]
    print(f"- 비교 쌍 {len(common)}개, 달라진 쌍 {len(changed_pairs)}개")
    print(f"- 평균 점수: {mean_before:.4f} → {mean_after:.4f} (변화폭 {shift:+.4f})")
    if shift >= MEAN_SHIFT_WARNING:
        print(
            f"- ⚠ 경고: 표본 평균이 {MEAN_SHIFT_WARNING:.2f} 이상 상승 — "
            "전반적 점수 팽창 여부 검토 필요"
        )
    for key in changed_pairs:
        a, b = key.split("\t")
        print(f"  - {a} / {b}: {before_sample[key]:.3f} → {sample_scores[key]:.3f}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="X1 호칭 유사도 보고")
    parser.add_argument(
        "--metadata", type=Path, default=ML_ROOT / "data" / "kipris_metadata.json"
    )
    parser.add_argument("--seed", type=int, default=20260917)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE if DEFAULT_BASELINE.exists() else None,
        help="변경 전 점수 JSON(--dump-scores 로 만든 파일). 있으면 전후 비교를 출력",
    )
    parser.add_argument(
        "--dump-scores", type=Path, help="현재 점수를 JSON 으로 저장(다음 비교의 기준선)"
    )
    args = parser.parse_args()

    _print_g2p_sample()
    report_scores = _print_report_pairs()
    names = _load_names(args.metadata) if args.metadata.exists() else []
    if not names:
        print(f"(메타데이터 없음 또는 비어 있음: {args.metadata})\n")
    sample_scores = _print_data_sample(names, args.seed)
    _print_timing(names, args.seed)
    if args.baseline is not None and args.baseline.exists():
        _print_baseline_diff(args.baseline, report_scores, sample_scores)
    if args.dump_scores is not None:
        payload = {"report_pairs": report_scores, "sample_pairs": sample_scores}
        args.dump_scores.parent.mkdir(parents=True, exist_ok=True)
        args.dump_scores.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"(점수 저장: {args.dump_scores})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
