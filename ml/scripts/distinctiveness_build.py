"""식별력 v0 집계·산출물 — 심판 목록(list_all.csv 42,474건)과 DB(kipris_metadata.json 1,100건)의
상표명 토큰마다 서로 다른 출원인 수 A·등장 수 N 을 세고(2017후2697 다수 등록), 모든 토큰을 식별력
모델로 채점해 약한 토큰 목록·검토 표·임계 민감도 표를 만든다. KIPRIS 호출 0, 학습 없음.

실행 (프로젝트 루트에서):
    ml/venv/bin/python ml/scripts/distinctiveness_build.py [--list-all ml/data/trials/list_all.csv]
        [--metadata ml/data/kipris_metadata.json] [--out-dir shared/distinctiveness]
        [--theta 0.5] [--theta-a 10] [--theta-n 20] [--top 200]

출원인(소유자) 열: 거절결정불복·권리범위확인(적극적)은 청구인(출원인·권리자), 무효·취소·권리범위확인
(소극적)은 피청구인(등록권리자), 그 밖은 청구인. 같은 (제목, 소유자) 는 한 번만 센다. 토큰은 X1
normalize_name(회사 형태·부가어 제거, 문자 종류 경계 분리)으로 뽑고 2글자 이상만 센다.

산출물(out-dir):
    token_stats.json  — {"meta", "tokens": {토큰: [A, N]}} (N ≥ 2 인 토큰; 런타임이 적재)
    weak_tokens.json  — 점수 < θ 인 토큰·점수·A·N·zipf·사유(전역 판정, 상품 없이)
    report.md         — 사유별 건수, 상위 200(사람 검토용), 임계 민감도 표(θ_A·θ_N 5/10/20 × θ)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from src.axes import distinctiveness as dx  # noqa: E402
from src.axes.goods_map import load_goods_map  # noqa: E402
from src.axes.x1_phonetic import normalize_name  # noqa: E402

DEFAULT_LIST_ALL = ML_ROOT / "data" / "trials" / "list_all.csv"
DEFAULT_METADATA = ML_ROOT / "data" / "kipris_metadata.json"
DEFAULT_OUT_DIR = dx.DEFAULT_DIR
OWNER_COLUMN = {
    "거절결정불복": "청구인", "권리범위확인(적극적)": "청구인", "무효": "피청구인",
    "취소": "피청구인", "권리범위확인(소극적)": "피청구인",
}
SENSITIVITY_GRID = ((5, 10), (10, 20), (20, 40))
THETA_GRID = (0.4, 0.5, 0.6)
LEGAL_PREFIXES = ("1호", "3호", "4호", "5호", "6호")


def owner_of(row: dict) -> str:
    column = OWNER_COLUMN.get(row.get("종류", ""), "청구인")
    return (row.get(column) or row.get("청구인") or "").strip()


def normalize_owner(name: str) -> str:
    return "".join(normalize_name(name or ""))


def read_list_all(path: Path) -> list[tuple[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [(row.get("상표명칭") or "", normalize_owner(owner_of(row))) for row in rows]


def read_metadata(path: Path) -> list[tuple[str, str]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    records = data.get("trademarks", data) if isinstance(data, dict) else data
    out = []
    for record in records:
        title = record.get("상표한글명") or record.get("상표영문명") or record.get("Title") or ""
        owner = record.get("출원인") or record.get("ApplicantName") or ""
        out.append((title, normalize_owner(owner)))
    return out


def collect_titles(*sources: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """제목이 있는 (제목, 소유자) — 같은 (제목(casefold), 소유자)는 한 번만."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for source in sources:
        for title, owner in source:
            title = (title or "").strip()
            if not title:
                continue
            key = (title.casefold(), owner)
            if key in seen:
                continue
            seen.add(key)
            out.append((title, owner))
    return out


def token_stats(titles: list[tuple[str, str]]) -> dict[str, tuple[int, int]]:
    """토큰 → (서로 다른 소유자 수 A, 등장 제목 수 N). 2글자 이상 토큰만."""
    marks: Counter[str] = Counter()
    owners: dict[str, set[str]] = defaultdict(set)
    for title, owner in titles:
        tokens = {t for t in normalize_name(title) if len(t) >= dx.MIN_TOKEN_CHARS}
        for token in tokens:
            marks[token] += 1
            if owner:
                owners[token].add(owner)
    return {token: (len(owners[token]), marks[token]) for token in marks}


def write_stats(path: Path, stats: dict[str, tuple[int, int]], meta: dict, *,
                min_marks: int = 2) -> int:
    kept = {t: list(v) for t, v in sorted(stats.items()) if v[1] >= min_marks}
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": {**meta, "min_marks": min_marks, "토큰_수": len(kept)}, "tokens": kept}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return len(kept)


def judge_all(model: dx.Distinctiveness, vocab: list[str]) -> list[dict]:
    rows = []
    for token in vocab:
        judgement = model.judge(token)
        applicants, marks = model.stats.get(token, (0, 0))
        rows.append({
            "token": token, "score": judgement.score, "A": applicants, "N": marks,
            "zipf": round(dx.token_zipf(token), 2), "reasons": list(judgement.reasons),
        })
    return rows


def weak_rows(rows: list[dict], theta: float) -> list[dict]:
    weak = [r for r in rows if r["score"] < theta]
    weak.sort(key=lambda r: (-r["N"], -r["A"], r["token"]))
    return weak


def reason_counts(weak: list[dict]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in weak:
        for reason in row["reasons"]:
            counts[reason.split("(")[0].split(":")[0]] += 1
    return dict(counts.most_common())


def sensitivity(stats: dict[str, tuple[int, int]], vocab: list[str], *, famous, goods_names,
                code_classes) -> list[dict]:
    """(θ_A, θ_N) × θ 별 약한 토큰 수와 그중 법정 0점(1·3·4·5·6호)이 아닌(다수 등록·일반어) 수."""
    out = []
    for theta_a, theta_n in SENSITIVITY_GRID:
        model = dx.Distinctiveness(stats, famous=famous, goods_names=goods_names,
                                   code_classes=code_classes, theta_a=theta_a, theta_n=theta_n)
        scored = [(model.judge(token), token) for token in vocab]
        for theta in THETA_GRID:
            weak = [j for j, _ in scored if j.score < theta]
            legal = sum(1 for j in weak if any(r.startswith(LEGAL_PREFIXES) for r in j.reasons))
            out.append({
                "theta_a": theta_a, "theta_n": theta_n, "theta": theta, "약한_토큰": len(weak),
                "법정_0점": legal, "다수등록·일반어": len(weak) - legal,
            })
    return out


def render_report(weak: list[dict], counts: dict[str, int], sens: list[dict], *, meta: dict,
                  top: int) -> str:
    lines = [
        f"# 식별력 v0 약한 토큰 보고 ({meta['생성일']})",
        "",
        f"- 입력: 심판 목록 제목 {meta['심판_제목']}건 + DB 제목 {meta['db_제목']}건 → 중복 제외 "
        f"{meta['제목_소유자_쌍']}쌍, 토큰 {meta['어휘']}개(2글자 이상)",
        f"- 임계: θ {meta['theta']} · θ_A {meta['theta_a']} · θ_N {meta['theta_n']} · "
        f"약한 토큰(점수 < θ) {len(weak)}개 · 유명 브랜드 예외 {meta['유명_브랜드']}개",
        "- 판정은 상품 정보 없이(1호는 전역 고시 단일 명칭 일치). 쌍 단위 판정은 그 쌍의 "
        "유사군으로 다시 한다.",
        "",
        "## 사유별 건수(중복 포함)",
        "",
        "| 사유 | 토큰 수 |", "|---|---|",
        *[f"| {reason} | {count} |" for reason, count in counts.items()],
        "",
        f"## 상위 {top} (등장 수 N 순, 사람 검토용)",
        "",
        "| # | 토큰 | 점수 | A | N | zipf | 사유 |", "|---|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(weak[:top], start=1):
        lines.append(
            f"| {index} | {row['token']} | {row['score']:.2f} | {row['A']} | {row['N']} | "
            f"{row['zipf']:.1f} | {'; '.join(row['reasons'])} |"
        )
    lines += [
        "",
        "## 임계 민감도(θ_A·θ_N × θ) — 약한 토큰 수(법정 0점 / 다수 등록·일반어)",
        "",
        "| θ_A / θ_N | θ 0.4 | θ 0.5 | θ 0.6 |", "|---|---|---|---|",
    ]
    for theta_a, theta_n in SENSITIVITY_GRID:
        cells = []
        for theta in THETA_GRID:
            row = next(r for r in sens if (r["theta_a"], r["theta_n"], r["theta"])
                       == (theta_a, theta_n, theta))
            cells.append(f"{row['약한_토큰']} ({row['법정_0점']} / {row['다수등록·일반어']})")
        lines.append(f"| {theta_a} / {theta_n} | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def run(list_all: Path, metadata: Path, out_dir: Path, *, theta: float = dx.THETA,
        theta_a: int = dx.THETA_A, theta_n: int = dx.THETA_N, top: int = 200,
        goods_map=None) -> dict:
    trial_titles = read_list_all(list_all) if Path(list_all).exists() else []
    db_titles = read_metadata(metadata) if Path(metadata).exists() else []
    titles = collect_titles(trial_titles, db_titles)
    stats = token_stats(titles)
    famous = dx.famous_tokens()
    goods_map = goods_map or load_goods_map()
    goods_names, code_classes = dx.goods_index(goods_map)
    meta = {
        "생성일": date.today().isoformat(), "심판_제목": sum(1 for t, _ in trial_titles if t),
        "db_제목": sum(1 for t, _ in db_titles if t), "제목_소유자_쌍": len(titles),
        "어휘": len(stats), "theta": theta, "theta_a": theta_a, "theta_n": theta_n,
        "유명_브랜드": len(famous), "출원인_열": OWNER_COLUMN,
    }
    out_dir = Path(out_dir)
    kept = write_stats(out_dir / "token_stats.json", stats, meta)
    model = dx.Distinctiveness(stats, famous=famous, goods_names=goods_names,
                               code_classes=code_classes, theta=theta, theta_a=theta_a,
                               theta_n=theta_n)
    vocab = sorted(stats)
    rows = judge_all(model, vocab)
    weak = weak_rows(rows, theta)
    counts = reason_counts(weak)
    sens = sensitivity(stats, vocab, famous=famous, goods_names=goods_names,
                       code_classes=code_classes)
    (out_dir / "weak_tokens.json").write_text(
        json.dumps({"meta": {**meta, "약한_토큰": len(weak), "사유별": counts}, "tokens": weak},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    (out_dir / "report.md").write_text(
        render_report(weak, counts, sens, meta=meta, top=top), encoding="utf-8"
    )
    return {**meta, "token_stats_토큰": kept, "약한_토큰": len(weak), "사유별": counts,
            "민감도": sens, "출력": str(out_dir)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--list-all", type=Path, default=DEFAULT_LIST_ALL)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--theta", type=float, default=dx.THETA)
    parser.add_argument("--theta-a", type=int, default=dx.THETA_A)
    parser.add_argument("--theta-n", type=int, default=dx.THETA_N)
    parser.add_argument("--top", type=int, default=200)
    args = parser.parse_args(argv)
    summary = run(args.list_all, args.metadata, args.out_dir, theta=args.theta,
                  theta_a=args.theta_a, theta_n=args.theta_n, top=args.top)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
