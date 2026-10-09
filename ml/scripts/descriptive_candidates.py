"""3호 기술적 표장 후보 생성·분류 — 데이터에서 후보 토큰을 뽑아 증거(출원인 수·등장 수·빈도·상표
예시·고시 상품명칭의 류 분포)를 붙이고, 판례 기준으로 분류한 표(사람 승인용)와
descriptive_terms.json 초안(approved false)을 쓴다. KIPRIS 호출 0.

실행 (프로젝트 루트에서):
    ml/venv/bin/python ml/scripts/descriptive_candidates.py            # md 표 + JSON 초안
    ml/venv/bin/python ml/scripts/descriptive_candidates.py --dump     # 후보·증거만(분류 작업용)

후보 출처
    (a) weak_tokens.json 중 1·4·5·6호가 아닌 것(다수 등록·일반어)
    (b) token_stats.json 에서 서로 다른 출원인 5명 이상인 토큰
    (c) 고시 상품명칭의 단일 토큰 중 상표명에도 나오는 것(원재료·용도 후보)
    (d) 판례 예시 절대어(Best·No1·Nice·Super·최고·정상·제일)와 동의어
영어 토큰은 wordfreq zipf ≥ 3.0(직관적으로 뜻을 아는 단어)만 후보로 둔다(그 밖은 "빈도 미달" 제외).

    (e) 분류표(descriptive_judgements.json)에서 포함·보류로 판정했지만 (a)~(d) 풀에 없던 전형적
        성질 표시어(유기농·수제·순수 …)
분류(descriptive_judgements.json, docs/MarkLens_식별력_설계.md §3-3 의 판례 기준): 판정
포함|보류|제외, kind, 절대 여부, 적용 류(상대적이면 그 성질이 직감되는 류 — 고시 명칭의 류 분포로
근거), 한 줄 이유. 목록에 없는 후보는 "제외(성질 표시 아님)" 로 두되 유형 사유를 자동으로 붙인다
(숫자는 보류). 암시·강조에 그치는 것은 제외, 의심되면 보류.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from src.axes import distinctiveness as dx  # noqa: E402
from src.axes.goods_map import load_goods_map  # noqa: E402
from src.axes.x1_phonetic import normalize_name  # noqa: E402

DEFAULT_WEAK = dx.DEFAULT_DIR / "weak_tokens.json"
DEFAULT_STATS = dx.DEFAULT_STATS_PATH
DEFAULT_LIST_ALL = ML_ROOT / "data" / "trials" / "list_all.csv"
DEFAULT_METADATA = ML_ROOT / "data" / "kipris_metadata.json"
DEFAULT_MD = dx.DEFAULT_DIR / "descriptive_candidates.md"
DEFAULT_JSON = dx.DEFAULT_DESCRIPTIVE_PATH
MIN_APPLICANTS = 5
EN_MIN_ZIPF = 3.0
LEGAL = ("1호", "4호", "5호", "6호")
VERDICTS = ("포함", "보류", "제외")

# (d) 판례 예시 절대어(지정상품 불문 품질 표시)와 그 동의어·표기 변형
PRECEDENT_ABSOLUTE: tuple[str, ...] = (
    "best", "no1", "nice", "super", "최고", "정상", "제일",
    "베스트", "넘버원", "나이스", "슈퍼", "top", "탑", "톱", "premium", "프리미엄", "special",
    "스페셜", "excellent", "perfect", "퍼펙트", "good", "굿", "great", "fine", "quality", "퀄리티",
    "최상", "최우수", "일류", "일등", "으뜸", "명품", "고급", "특급", "특선", "deluxe", "디럭스",
    "ultra", "울트라", "first", "original", "오리지널", "정품", "진품", "참", "진짜", "real",
    "리얼",
    "100", "pro", "프로", "플러스", "plus", "max", "맥스", "supreme", "prime", "프라임", "elite",
    "엘리트", "royal", "로얄", "king", "킹", "master", "마스터", "no", "new", "뉴", "신", "신상",
    "famous", "유명", "best1", "number1", "numberone", "a", "aa", "aaa",
)


@dataclass(frozen=True)
class Judgement:
    verdict: str  # 포함 | 보류 | 제외
    kind: str = ""  # DESCRIPTIVE_KINDS
    absolute: bool = False
    classes: tuple[int, ...] | None = None
    reason: str = ""


def J(verdict: str, kind: str = "", absolute: bool = False, classes=None,
      reason: str = "") -> Judgement:
    return Judgement(verdict, kind, absolute, tuple(classes) if classes else None, reason)


# ---- 판례 기준 분류(사람 승인용 초안). 토큰은 X1 정규화 형태. ------------------------------
# 포함: 보통으로 사용하는 방법으로 성질을 표시(지정상품과의 관계·거래실정으로 직감). 절대어는 류
# 불문. 보류: 상품마다 성질 표시 여부가 갈리거나 암시인지 애매. 제외: 암시·강조, 또는 성질 표시가
# 아닌 일반어.
JUDGEMENTS: dict[str, Judgement] = {}
JUDGEMENTS_PATH = Path(__file__).with_name("descriptive_judgements.json")


def load_judgements(path: Path = JUDGEMENTS_PATH) -> dict[str, Judgement]:
    """분류표(JSON: 토큰 → {verdict, kind, absolute, classes, reason})."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for token, item in data.items():
        out[token] = J(item["verdict"], item.get("kind", ""), item.get("absolute", False),
                       item.get("classes"), item.get("reason", ""))
    return out


# ---- 후보·증거 -----------------------------------------------------------------------------

def _has_hangul(text: str) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


def read_titles(list_all: Path, metadata: Path) -> list[str]:
    titles: list[str] = []
    if Path(list_all).exists():
        with Path(list_all).open(encoding="utf-8", newline="") as handle:
            titles += [row.get("상표명칭") or "" for row in csv.DictReader(handle)]
    if Path(metadata).exists():
        data = json.loads(Path(metadata).read_text(encoding="utf-8"))
        records = data.get("trademarks", data) if isinstance(data, dict) else data
        titles += [(r.get("상표한글명") or r.get("상표영문명") or "") for r in records]
    return [t for t in titles if t]


def example_index(titles: list[str], tokens: set[str],
                  per_token: int = 3) -> dict[str, list[str]]:
    """토큰 → 그 토큰이 든 상표명 예시(중복 제외, 최대 per_token)."""
    examples: dict[str, list[str]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)
    for title in titles:
        for token in set(normalize_name(title)):
            if token in tokens and len(examples[token]) < per_token:
                key = title.casefold()
                if key not in seen[token]:
                    seen[token].add(key)
                    examples[token].append(title)
    return examples


def goods_class_evidence(goods_map, tokens: set[str],
                         top: int = 3) -> dict[str, list[tuple[int, int]]]:
    """토큰 → 그 토큰을 이름에 포함하는 고시 상품명칭의 류 분포 상위 top(류, 건수). 한글은 부분
    문자열, 영문은 토큰 일치."""
    korean = {t for t in tokens if _has_hangul(t)}
    latin = tokens - korean
    counts: dict[str, Counter] = defaultdict(Counter)
    for entry in goods_map.entries:
        name_tokens = normalize_name(entry.name)
        name_text = "".join(name_tokens)
        for token in latin & set(name_tokens):
            counts[token][entry.nice_class] += 1
        for token in korean:
            if token in name_text:
                counts[token][entry.nice_class] += 1
    return {token: counter.most_common(top) for token, counter in counts.items()}


def collect_candidates(weak_path: Path, stats_path: Path, goods_map,
                       judgements: dict[str, Judgement] | None = None) -> dict[str, set[str]]:
    """토큰 → 출처 집합 {a, b, c, d, e}."""
    sources: dict[str, set[str]] = defaultdict(set)
    if Path(weak_path).exists():
        weak = json.loads(Path(weak_path).read_text(encoding="utf-8")).get("tokens", [])
        for item in weak:
            if not any(r.startswith(LEGAL) for r in item.get("reasons", [])):
                sources[item["token"]].add("a")
    stats = dx.read_stats(Path(stats_path))
    for token, (applicants, _marks) in stats.items():
        if applicants >= MIN_APPLICANTS:
            sources[token].add("b")
    names, _classes = dx.goods_index(goods_map)
    for token in names:
        if token in stats:
            sources[token].add("c")
    for token in PRECEDENT_ABSOLUTE:
        sources[token].add("d")
    for token, judgement in (judgements or {}).items():
        if judgement.verdict in ("포함", "보류") and token not in sources:
            sources[token].add("e")
    return sources


def is_eligible(token: str) -> tuple[bool, str]:
    """영어는 wordfreq zipf ≥ EN_MIN_ZIPF 만. 한글·숫자는 모두 후보."""
    if _has_hangul(token):
        return True, ""
    if token.isdigit():
        return True, ""
    zipf = dx.token_zipf(token)
    if zipf >= EN_MIN_ZIPF:
        return True, ""
    return False, f"빈도 미달(zipf {zipf:.1f} < {EN_MIN_ZIPF})"


def auto_exclusion_reason(token: str, zipf: float) -> str:
    if _has_hangul(token):
        if zipf == 0:
            return "성질 표시 아님(한글 조어·고유명사)"
        return "성질 표시 아님(한글 일반어·수식어)"
    return "성질 표시 아님(영어 일반어·기능어·고유명사 — 관념이 상품 성질과 무관)"


def build_rows(sources: dict[str, set[str]], stats: dict[str, tuple[int, int]],
               examples: dict[str, list[str]], class_evidence: dict,
               judgements: dict[str, Judgement], weak_scores: dict[str, float]) -> list[dict]:
    rows = []
    for token in sorted(sources):
        eligible, why = is_eligible(token)
        zipf = dx.token_zipf(token)
        applicants, marks = stats.get(token, (0, 0))
        judgement = judgements.get(token)
        if not eligible:
            verdict, kind, absolute, classes, reason = "제외", "", False, None, why
        elif judgement is None and token.isdigit():
            verdict, kind, absolute, classes = "보류", "수량", False, None
            reason = "숫자 — 수량·연도·모델명 중 무엇인지 상품별로 갈림(목록 미등재)"
        elif judgement is None:
            verdict, kind, absolute, classes = "제외", "", False, None
            reason = auto_exclusion_reason(token, zipf)
        else:
            verdict, kind, absolute = judgement.verdict, judgement.kind, judgement.absolute
            classes, reason = judgement.classes, judgement.reason
        rows.append({
            "token": token, "sources": "".join(sorted(sources[token])), "A": applicants, "N": marks,
            "zipf": round(zipf, 1), "weak_score": weak_scores.get(token),
            "examples": examples.get(token, []),
            "goods_classes": class_evidence.get(token, []), "verdict": verdict, "kind": kind,
            "absolute": absolute, "classes": list(classes) if classes else None, "reason": reason,
            "judged": judgement is not None,
        })
    return rows


# ---- 출력 ---------------------------------------------------------------------------------

def _classes_text(row: dict) -> str:
    if row["absolute"]:
        return "불문"
    return ",".join(map(str, row["classes"])) if row["classes"] else "-"


def _evidence_text(row: dict) -> str:
    goods = " ".join(f"{c}류{n}" for c, n in row["goods_classes"]) or "-"
    return goods


def render_markdown(rows: list[dict], *, meta: dict) -> str:
    included = [r for r in rows if r["verdict"] == "포함"]
    held = [r for r in rows if r["verdict"] == "보류"]
    excluded = [r for r in rows if r["verdict"] == "제외"]
    kinds = Counter(r["kind"] for r in included)
    lines = [
        f"# 3호 기술적 표장 후보 분류표 ({meta['생성일']}) — 사람 승인용",
        "",
        f"- 후보 {len(rows)}개(출처 a {meta['출처']['a']} · b {meta['출처']['b']} · "
        f"c {meta['출처']['c']} · d {meta['출처']['d']} · e {meta['출처']['e']}, 합집합) → "
        f"포함 {len(included)} · 보류 {len(held)} · 제외 {len(excluded)}"
        f"(영어 빈도 미달 {meta['빈도_미달']} 포함)",
        "- kind 별 포함: " + " · ".join(f"{k} {n}" for k, n in sorted(kinds.items()))
        + f" · 절대어 {sum(1 for r in included if r['absolute'])}",
        "- 기준: docs/MarkLens_식별력_설계.md §3-3(판례). 증거의 '류' 는 그 토큰이 든 고시 "
        "상품명칭의 류 분포 상위 3. 출처 a 약한 토큰(1·4·5·6호 아님) · b 출원인 5명 이상 · "
        "c 고시 단일 명칭 · d 판례 절대어·동의어 · e 분류표 추가.",
        "- 승인: `shared/distinctiveness/descriptive_terms.json` 의 항목 `approved` 를 true 로. "
        "포함 항목은 승인 전에도 적용된다(보고서에 미승인 수 표시).",
        "",
        "## 포함 (kind 별)",
        "",
        "| 토큰 | kind | 절대 | 적용 류 | A | N | zipf | 상표 예시 | 고시 류 분포 | 이유 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    def kind_order(row: dict) -> tuple:
        kinds_ = dx.DESCRIPTIVE_KINDS
        return (kinds_.index(row["kind"]) if row["kind"] in kinds_ else 99, -row["N"], row["token"])

    for row in sorted(included, key=kind_order):
        lines.append(
            f"| {row['token']} | {row['kind']} | {'O' if row['absolute'] else ''} | "
            f"{_classes_text(row)} | "
            f"{row['A']} | {row['N']} | {row['zipf']} | {' · '.join(row['examples']) or '-'} | "
            f"{_evidence_text(row)} | {row['reason']} |"
        )
    lines += ["", "## 보류", "",
              "| 토큰 | kind(추정) | A | N | zipf | 상표 예시 | 고시 류 분포 | 이유 |",
              "|---|---|---|---|---|---|---|---|"]
    for row in sorted(held, key=lambda r: (-r["N"], r["token"])):
        lines.append(
            f"| {row['token']} | {row['kind'] or '-'} | {row['A']} | {row['N']} | {row['zipf']} | "
            f"{' · '.join(row['examples']) or '-'} | {_evidence_text(row)} | {row['reason']} |"
        )
    lines += ["", "## 제외 (사유 유형별 건수)", ""]
    by_reason = Counter(r["reason"].split("(")[0] for r in excluded)
    lines += ["| 사유 | 건수 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in by_reason.most_common()]
    lines += ["", "### 제외 — 개별 판단(암시·강조 등)", "",
              "| 토큰 | A | N | zipf | 상표 예시 | 이유 |", "|---|---|---|---|---|---|"]
    for row in sorted((r for r in excluded if r["judged"]), key=lambda r: (-r["N"], r["token"])):
        lines.append(f"| {row['token']} | {row['A']} | {row['N']} | {row['zipf']} | "
                     f"{' · '.join(row['examples']) or '-'} | {row['reason']} |")
    unjudged = sorted((r for r in excluded if not r["judged"]), key=lambda r: (-r["N"], r["token"]))
    lines += ["", "### 제외 — 자동 사유(목록 미등재: 성질 표시 아님)", "",
              ", ".join(r["token"] for r in unjudged), ""]
    return "\n".join(lines)


def draft_terms(rows: list[dict], *, meta: dict) -> dict:
    terms = {}
    for row in sorted((r for r in rows if r["verdict"] == "포함"), key=lambda r: r["token"]):
        terms[row["token"]] = {
            "kind": row["kind"], "absolute": bool(row["absolute"]),
            "classes": None if row["absolute"] else row["classes"],
            "note": row["reason"], "examples": row["examples"], "approved": False,
        }
    return {"meta": {**meta, "항목": len(terms), "승인": 0}, "terms": terms}


def run(*, weak_path=DEFAULT_WEAK, stats_path=DEFAULT_STATS, list_all=DEFAULT_LIST_ALL,
        metadata=DEFAULT_METADATA, md_path=DEFAULT_MD, json_path=DEFAULT_JSON, goods_map=None,
        judgements: dict[str, Judgement] | None = None, dump: bool = False) -> dict:
    goods_map = goods_map or load_goods_map()
    judgements = load_judgements() if judgements is None else judgements
    sources = collect_candidates(weak_path, stats_path, goods_map, judgements)
    stats = dx.read_stats(Path(stats_path))
    tokens = set(sources)
    examples = example_index(read_titles(list_all, metadata), tokens)
    class_evidence = goods_class_evidence(goods_map, tokens)
    weak_scores = {}
    if Path(weak_path).exists():
        for item in json.loads(Path(weak_path).read_text(encoding="utf-8")).get("tokens", []):
            weak_scores[item["token"]] = item.get("score")
    rows = build_rows(sources, stats, examples, class_evidence, judgements, weak_scores)
    meta = {
        "생성일": date.today().isoformat(),
        "출처": {key: sum(1 for s in sources.values() if key in s) for key in "abcde"},
        "빈도_미달": sum(1 for r in rows if r["reason"].startswith("빈도 미달")),
        "판정": dict(Counter(r["verdict"] for r in rows)),
        "kind별_포함": dict(Counter(r["kind"] for r in rows if r["verdict"] == "포함")),
        "절대어": sorted(r["token"] for r in rows if r["verdict"] == "포함" and r["absolute"]),
    }
    if dump:
        for row in rows:
            print(f"{row['token']}\t{row['sources']}\tA{row['A']}\tN{row['N']}\tz{row['zipf']}\t"
                  f"{' ; '.join(row['examples'])}\t{_evidence_text(row)}")
        return meta
    Path(md_path).parent.mkdir(parents=True, exist_ok=True)
    Path(md_path).write_text(render_markdown(rows, meta=meta), encoding="utf-8")
    Path(json_path).write_text(
        json.dumps(draft_terms(rows, meta=meta), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    # 초안이 로더 검증을 통과하는지 확인
    dx.validate_descriptive_terms(json.loads(Path(json_path).read_text(encoding="utf-8")))
    meta["출력"] = {"md": str(md_path), "json": str(json_path)}
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dump", action="store_true", help="후보·증거만 한 줄씩 출력(분류 작업용)")
    parser.add_argument("--md", type=Path, default=DEFAULT_MD)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    args = parser.parse_args(argv)
    meta = run(md_path=args.md, json_path=args.json, dump=args.dump)
    if not args.dump:
        print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
