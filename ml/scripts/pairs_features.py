"""정답 데이터 특징 생성 — 라벨된 심결례 쌍마다 4축 점수와 결측 플래그를 계산해 학습 데이터
(`pairs_features.csv`)를 만든다. 학습(가중치 적합)은 하지 않는다. KIPRIS 호출 0.

실행 (프로젝트 루트에서. X3 는 실제 모델 — MARKLENS_FAKE_ML 없이. MiniLM 은 HuggingFace 캐시에서
읽는다):
    ml/venv/bin/python ml/scripts/pairs_features.py [--labels ml/data/trials/labels.csv]
        [--image-pairs ml/data/trials/image_pairs_v1.csv] [--out ml/data/trials/pairs_features.csv]

대상: labels.csv 에서 LLM pass a·b 판정이 일치한 유사·비유사 행(backend/scripts/trials_enrich.py
      target_rows 와 같은 규칙, 350행).
이름: A = 상표A_명칭. B = 상대표장_명칭_kipris > llm(label --name-b) > 본문 > ocr(`이름B_출처`).
      LLM 이 "도형만" 이라고 적은 행(메모 도형, llm 빈 값)은 본문·OCR 로 내려가지 않고 이름 없음
      (출처 "도형"). 이름이 없으면 이름 기반 축(x1·x2_text·x3)은 결측(빈 칸).
식별력 v0(ml/src/axes/distinctiveness.py, 다빈-3): 쌍의 유사군(goods_codes_this ∪ prior, 없으면
      전역)으로 두 이름의 약한 토큰(점수 < θ)을 모아 extra_generic 으로 넘긴 x1_d·x2_text_d·x3_d 와
      has_distinctive_part_a/b·weak_a/b(요부 없는 이름은 토큰을 넘기지 않고 전체 대비 — 2000후2453).
쉬운 음성(--easy-negatives, seed 0): 다른 심결 사건끼리 교차 쌍 350 + DB 1,100 무작위 쌍 350 을
      비유사로 가정해 pairs_features_easy.csv 에 쓴다(x1·x2_text ≥ 0.8 은 우연 유사로 제외·수 보고,
      pair_source = cross | db; 이미지 축은 없다).
축:   x1       phonetic_similarity(X1 호칭) — 발음 후보 없으면 함수가 0.0 을 돌려준다(게이트 꺼짐)
      x2_text  orthographic_similarity(X2 문자 외관) — 글자 토큰 없으면 0.0
      x2_fig   image_pairs_v1.csv 의 도형 크롭 CLIP 코사인(양쪽 크롭이 있을 때, x2_cache_v0 임베딩)
      x2_whole image_pairs_v1.csv 의 전체 이미지 CLIP 코사인(이미지 쌍이 있을 때) — 보조 열
      x3       semantic_similarity(X3 관념, 실제 모델) — has_meaning 이 한쪽이라도 False 면 0.0
      x3_raw   게이트를 끈 X3(정규화 텍스트 임베딩 코사인의 c₀ 재보정) — 게이트 효과 분석용
      x4       labels.csv 의 x4_goods(유사군 자카드, trials_enrich goods 단계) — 양쪽 유사군이
               없으면 결측
플래그: has_names(양쪽 이름), has_pron_a/b, has_meaning_a/b, has_spelling_a/b, has_goods, has_image,
      has_fig (1/0).
메타: 심판번호, 종류, 상대번호, 최종라벨(유사여부_확정), 표장라벨(x2_benchmark.mark_label —
      상품만으로 결론 난 비유사는 ""), 판단축(판단축_확정, 비면 llm_b_판단축),
      상표유형(확정 > 추정), 이름A, 이름B, 이름B_출처, 메모.
보고: 축별 결측 수, 이름B 출처 분포, 종류·유형 분포(stdout JSON + pairs_features_report.json).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

# x2_benchmark 가 torch → faiss 순서로 import 한다(ml/src/search.py 주석). 그 뒤에 축 함수.
from scripts.x2_benchmark import mark_label  # noqa: E402
from src.axes import x3_semantic as x3  # noqa: E402
from src.axes.distinctiveness import Distinctiveness, load_distinctiveness  # noqa: E402
from src.axes.x1_phonetic import has_pronunciation, phonetic_similarity  # noqa: E402
from src.axes.x2_ortho import has_spelling, orthographic_similarity  # noqa: E402
from src.axes.x4_goods import goods_similarity, has_goods  # noqa: E402

DEFAULT_BASE = ML_ROOT / "data" / "trials"
DEFAULT_LABELS = DEFAULT_BASE / "labels.csv"
DEFAULT_IMAGE_PAIRS = DEFAULT_BASE / "image_pairs_v1.csv"
DEFAULT_OUT = DEFAULT_BASE / "pairs_features.csv"
DEFAULT_METADATA = ML_ROOT / "data" / "kipris_metadata.json"
EASY_CROSS = 350
EASY_DB = 350
EASY_MAX_SCORE = 0.8  # x1·x2_text 가 이 이상이면 우연 유사 — 쉬운 음성에서 제외

POSITIVE = ("유사", "비유사")
NAME_B_SOURCES = (("kipris", "상대표장_명칭_kipris"), ("llm", "상대표장_명칭_llm"),
                  ("본문", "상대표장_명칭_본문"), ("ocr", "상대표장_명칭_ocr"))
FIGURE_MEMO = "도형"  # label --name-b "" --memo 도형 이 메모에 남기는 표시
META_COLUMNS = [
    "심판번호", "종류", "상대번호", "최종라벨", "표장라벨", "판단축", "판단축_출처", "상표유형",
    "상표유형_출처", "이름A", "이름B", "이름B_출처", "메모", "pair_source",
]
AXIS_COLUMNS = [
    "x1", "x2_text", "x2_fig", "x2_whole", "x3", "x3_raw", "x4", "x1_d", "x2_text_d", "x3_d",
]
FLAG_COLUMNS = [
    "has_names", "has_pron_a", "has_pron_b", "has_meaning_a", "has_meaning_b", "has_spelling_a",
    "has_spelling_b", "has_goods", "has_image", "has_fig", "has_distinctive_part_a",
    "has_distinctive_part_b", "weak_a", "weak_b",
]
COLUMNS = META_COLUMNS + AXIS_COLUMNS + FLAG_COLUMNS


def read_csv(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def target_rows(rows: list[dict]) -> list[dict]:
    """pass a·b 가 일치하고 유사·비유사인 행(labels.csv 순서) — trials_enrich.target_rows 와
    같다."""
    return [
        r for r in rows
        if r.get("유사여부_확정") in POSITIVE and r.get("유사여부_확정") == r.get("llm_b_유사여부")
    ]


def _memo_says_figure(row: dict) -> bool:
    return FIGURE_MEMO in [part.strip() for part in (row.get("메모") or "").split("·")]


def name_b(row: dict) -> tuple[str, str]:
    """상대 표장 이름과 출처: kipris > llm > 본문 > ocr. LLM 이 도형만이라고 적은 행은 ("", "도형").
    없으면 ("", "")."""
    for source, column in NAME_B_SOURCES:
        value = (row.get(column) or "").strip()
        if value:
            return value, source
        if source == "llm" and _memo_says_figure(row):
            return "", "도형"
    return "", ""


def judging_axes(row: dict) -> tuple[str, str]:
    """판단축: 판단축_확정(pass a) 우선, 비면 llm_b_판단축."""
    for source, column in (("확정", "판단축_확정"), ("llm_b", "llm_b_판단축")):
        value = (row.get(column) or "").strip()
        if value:
            return value, source
    return "", ""


def mark_type(row: dict) -> tuple[str, str]:
    """상표유형: LLM 확정 > 정규식 추정(값 체계가 다르다 — 확정은 결합-문자요부/결합-도형요부,
    추정은 결합)."""
    for source, column in (("확정", "상표유형_확정"), ("추정", "상표유형_추정")):
        value = (row.get(column) or "").strip()
        if value:
            return value, source
    return "", ""


def image_index(
    image_rows: list[dict],
) -> tuple[dict[tuple[str, str], dict], dict[str, list[dict]]]:
    by_key: dict[tuple[str, str], dict] = {}
    by_case: dict[str, list[dict]] = {}
    for row in image_rows:
        by_key.setdefault((row.get("심판번호", ""), row.get("상대번호", "") or ""), row)
        by_case.setdefault(row.get("심판번호", ""), []).append(row)
    return by_key, by_case


def find_image_row(row: dict, by_key: dict, by_case: dict) -> dict | None:
    """(심판번호, 상대번호)로 찾고, 없으면 그 사건의 이미지 쌍이 하나뿐일 때 그것."""
    key = (row["심판번호"], row.get("상표B_번호", "") or "")
    if key in by_key:
        return by_key[key]
    rows = by_case.get(row["심판번호"], [])
    return rows[0] if len(rows) == 1 else None


def _float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def x3_scores(name_a: str, name_b_: str) -> tuple[float, float | None]:
    """(게이트 적용 X3, 게이트 없는 X3). 게이트 없는 값은 정규화 텍스트가 한쪽이라도 비면 None."""
    gated = x3.semantic_similarity(name_a, name_b_)
    text_a, text_b = x3.embedding_text(name_a), x3.embedding_text(name_b_)
    if not text_a or not text_b:
        return gated, None
    if text_a == text_b:
        return gated, 1.0
    if text_b < text_a:  # semantic_similarity 와 같은 순서(대칭)
        text_a, text_b = text_b, text_a
    cosine = float(np.dot(x3.embed_text(text_a), x3.embed_text(text_b)))
    return gated, x3.recalibrate(cosine, x3.current_baseline())


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"


def _codes(value: str | None) -> frozenset[str]:
    return frozenset(c.strip() for c in (value or "").split(";") if c.strip())


def name_axes(name_a: str, name_b_: str, goods: frozenset[str], model: Distinctiveness) -> dict:
    """이름 축 5종 + 식별력 적용판 3종 + 요부 플래그. 이름이 하나라도 비면 빈 칸."""
    out = {"x1": "", "x2_text": "", "x3": "", "x3_raw": "", "x1_d": "", "x2_text_d": "", "x3_d": "",
           "has_distinctive_part_a": int(model.has_distinctive_part(name_a, goods or None)),
           "has_distinctive_part_b": int(model.has_distinctive_part(name_b_, goods or None)),
           "weak_a": ";".join(sorted(model.weak_tokens(name_a, goods or None))),
           "weak_b": ";".join(sorted(model.weak_tokens(name_b_, goods or None)))}
    if not (name_a and name_b_):
        return out
    gated, raw = x3_scores(name_a, name_b_)
    generic = model.pair_generic(name_a, name_b_, goods or None)
    out.update({
        "x1": _fmt(phonetic_similarity(name_a, name_b_)),
        "x2_text": _fmt(orthographic_similarity(name_a, name_b_)),
        "x3": _fmt(gated), "x3_raw": _fmt(raw),
        "x1_d": _fmt(phonetic_similarity(name_a, name_b_, extra_generic=generic)),
        "x2_text_d": _fmt(orthographic_similarity(name_a, name_b_, extra_generic=generic)),
        "x3_d": _fmt(x3.semantic_similarity(name_a, name_b_, extra_generic=generic)),
    })
    return out


def build_row(row: dict, image_row: dict | None, model: Distinctiveness) -> dict:
    name_a = (row.get("상표A_명칭") or "").strip()
    name_b_, source_b = name_b(row)
    axes, axes_source = judging_axes(row)
    kind, kind_source = mark_type(row)
    label = row.get("유사여부_확정", "")
    memo = row.get("메모", "") or ""
    mark = mark_label({"라벨": label, "메모": memo, "판단축": axes})
    has_names = bool(name_a and name_b_)
    goods_ok = has_goods(row.get("goods_codes_this", "").split(";")) and has_goods(
        row.get("goods_codes_prior", "").split(";")
    )
    x4 = _float(row.get("x4_goods")) if goods_ok else None
    x2_whole = _float(image_row.get("x2_whole")) if image_row else None
    x2_fig = _float(image_row.get("x2_fig")) if image_row else None
    goods = _codes(row.get("goods_codes_this")) | _codes(row.get("goods_codes_prior"))
    out = {
        "심판번호": row["심판번호"], "종류": row.get("종류", ""),
        "상대번호": row.get("상표B_번호", "") or "", "최종라벨": label, "표장라벨": mark,
        "판단축": axes, "판단축_출처": axes_source, "상표유형": kind, "상표유형_출처": kind_source,
        "이름A": name_a, "이름B": name_b_, "이름B_출처": source_b, "메모": memo,
        "pair_source": "trial",
        "x2_fig": _fmt(x2_fig), "x2_whole": _fmt(x2_whole), "x4": _fmt(x4),
        "has_names": int(has_names),
        "has_pron_a": int(has_pronunciation(name_a)), "has_pron_b": int(has_pronunciation(name_b_)),
        "has_meaning_a": int(x3.has_meaning(name_a)), "has_meaning_b": int(x3.has_meaning(name_b_)),
        "has_spelling_a": int(has_spelling(name_a)), "has_spelling_b": int(has_spelling(name_b_)),
        "has_goods": int(goods_ok), "has_image": int(x2_whole is not None),
        "has_fig": int(x2_fig is not None),
    }
    out.update(name_axes(name_a, name_b_, goods, model))
    return {column: out.get(column, "") for column in COLUMNS}


def build_features(label_rows: list[dict], image_rows: list[dict], *,
                   model: Distinctiveness | None = None) -> list[dict]:
    model = model or load_distinctiveness()
    by_key, by_case = image_index(image_rows)
    return [build_row(row, find_image_row(row, by_key, by_case), model)
            for row in target_rows(label_rows)]


# ---- 쉬운 음성 -------------------------------------------------------------------------------

def _easy_row(source: str, key: str, name_a: str, name_b_: str, goods_a: frozenset[str],
              goods_b: frozenset[str], model: Distinctiveness) -> dict:
    out = {column: "" for column in COLUMNS}
    goods = goods_a | goods_b
    has_goods_ = bool(goods_a) and bool(goods_b)
    out.update({
        "심판번호": key, "최종라벨": "비유사", "표장라벨": "비유사", "이름A": name_a,
        "이름B": name_b_,
        "이름B_출처": source, "pair_source": source, "x2_fig": "", "x2_whole": "",
        "x4": _fmt(goods_similarity(goods_a, goods_b)) if has_goods_ else "",
        "has_names": 1,
        "has_pron_a": int(has_pronunciation(name_a)), "has_pron_b": int(has_pronunciation(name_b_)),
        "has_meaning_a": int(x3.has_meaning(name_a)), "has_meaning_b": int(x3.has_meaning(name_b_)),
        "has_spelling_a": int(has_spelling(name_a)), "has_spelling_b": int(has_spelling(name_b_)),
        "has_goods": int(has_goods_), "has_image": 0, "has_fig": 0,
    })
    out.update(name_axes(name_a, name_b_, goods, model))
    return out


def read_db_names(path: Path) -> list[tuple[str, frozenset[str]]]:
    """DB(kipris_metadata.json) 상표명(한글명 > 영문명)과 유사군."""
    if not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    records = data.get("trademarks", data) if isinstance(data, dict) else data
    out = []
    for record in records:
        name = (record.get("상표한글명") or record.get("상표영문명") or "").strip()
        if name:
            out.append((name, frozenset(record.get("유사군") or ())))
    return out


def easy_negatives(features: list[dict], label_rows: list[dict],
                   db_names: list[tuple[str, frozenset[str]]], *, model: Distinctiveness,
                   seed: int = 0, n_cross: int = EASY_CROSS, n_db: int = EASY_DB,
                   max_score: float = EASY_MAX_SCORE) -> tuple[list[dict], dict]:
    """쉬운 음성: 다른 사건끼리 교차 쌍(이름A_i, 이름B_j) n_cross + DB 무작위 쌍 n_db.
    x1·x2_text 가 max_score 이상이면 우연 유사로 제외(수 보고). 결정적(seed)."""
    import random

    goods_by_key = {(r["심판번호"], r.get("상표B_번호", "") or ""):
                    (_codes(r.get("goods_codes_this")), _codes(r.get("goods_codes_prior")))
                    for r in label_rows}
    sides_a = [(f["심판번호"], f["이름A"], goods_by_key.get((f["심판번호"], f["상대번호"]),
                                                      (frozenset(), frozenset()))[0])
               for f in features if f["이름A"]]
    sides_b = [(f["심판번호"], f["이름B"], goods_by_key.get((f["심판번호"], f["상대번호"]),
                                                      (frozenset(), frozenset()))[1])
               for f in features if f["이름B"]]
    rng = random.Random(seed)
    rows: list[dict] = []
    excluded = {"cross": 0, "db": 0}
    seen: set[tuple[str, str]] = set()
    attempts = 0
    while sides_a and sides_b and len(rows) < n_cross and attempts < n_cross * 50:
        attempts += 1
        case_a, name_a, goods_a = rng.choice(sides_a)
        case_b, name_b_, goods_b = rng.choice(sides_b)
        if case_a == case_b or (name_a, name_b_) in seen:
            continue
        seen.add((name_a, name_b_))
        row = _easy_row("cross", f"cross:{case_a}|{case_b}", name_a, name_b_, goods_a, goods_b,
                        model)
        if float(row["x1"]) >= max_score or float(row["x2_text"]) >= max_score:
            excluded["cross"] += 1
            continue
        rows.append(row)
    n_cross_done = len(rows)
    attempts = 0
    while len(db_names) >= 2 and len(rows) - n_cross_done < n_db and attempts < n_db * 50:
        attempts += 1
        i, j = rng.sample(range(len(db_names)), 2)
        name_a, goods_a = db_names[i]
        name_b_, goods_b = db_names[j]
        if (name_a, name_b_) in seen or name_a.casefold() == name_b_.casefold():
            continue
        seen.add((name_a, name_b_))
        row = _easy_row("db", f"db:{i}|{j}", name_a, name_b_, goods_a, goods_b, model)
        if float(row["x1"]) >= max_score or float(row["x2_text"]) >= max_score:
            excluded["db"] += 1
            continue
        rows.append(row)
    report = {"seed": seed, "cross": n_cross_done, "db": len(rows) - n_cross_done,
              "우연_유사_제외": excluded, "제외_기준": f"x1 또는 x2_text ≥ {max_score}",
              "db_이름": len(db_names)}
    return rows, report


def _count(rows: list[dict], key: str) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key, "") or "(없음)"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def summarize(features: list[dict]) -> dict:
    n = len(features)
    return {
        "대상_행": n,
        "최종라벨": _count(features, "최종라벨"), "표장라벨": _count(features, "표장라벨"),
        "축별_결측": {
            axis: sum(1 for f in features if f[axis] == "") for axis in AXIS_COLUMNS
        },
        "게이트_꺼짐": {
            "x1(has_pron 한쪽 False)": sum(
                1 for f in features if f["has_names"] and not (f["has_pron_a"] and f["has_pron_b"])
            ),
            "x2_text(has_spelling 한쪽 False)": sum(
                1 for f in features
                if f["has_names"] and not (f["has_spelling_a"] and f["has_spelling_b"])
            ),
            "x3(has_meaning 한쪽 False)": sum(
                1 for f in features
                if f["has_names"] and not (f["has_meaning_a"] and f["has_meaning_b"])
            ),
        },
        "이름B_출처": _count(features, "이름B_출처"),
        "이름A_없음": sum(1 for f in features if not f["이름A"]),
        "요부_없음": {
            "A": sum(1 for f in features if f["이름A"] and not f["has_distinctive_part_a"]),
            "B": sum(1 for f in features if f["이름B"] and not f["has_distinctive_part_b"]),
        },
        "식별력_적용으로_바뀐_쌍": {
            axis: sum(1 for f in features if f[axis] and f[axis] != f[f"{axis}_d"])
            for axis in ("x1", "x2_text", "x3")
        },
        "종류": _count(features, "종류"), "상표유형": _count(features, "상표유형"),
        "상표유형_출처": _count(features, "상표유형_출처"),
        "판단축_출처": _count(features, "판단축_출처"),
    }


def write_csv(path: Path, features: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(features)


def run(labels_path: Path, image_pairs_path: Path, out_path: Path, *,
        model: Distinctiveness | None = None, easy: bool = False,
        metadata_path: Path = DEFAULT_METADATA, seed: int = 0) -> dict:
    model = model or load_distinctiveness()
    label_rows = read_csv(labels_path)
    image_rows = read_csv(image_pairs_path) if Path(image_pairs_path).exists() else []
    features = build_features(label_rows, image_rows, model=model)
    write_csv(out_path, features)
    report = summarize(features)
    report["식별력"] = {"theta": model.theta, "theta_a": model.theta_a, "theta_n": model.theta_n,
                      "통계_토큰": len(model.stats)}
    if easy:
        easy_rows, easy_report = easy_negatives(
            features, label_rows, read_db_names(metadata_path), model=model, seed=seed
        )
        easy_path = out_path.with_name(out_path.stem + "_easy.csv")
        write_csv(easy_path, easy_rows)
        report["쉬운_음성"] = {**easy_report, "출력": str(easy_path)}
    report["x3_모델"] = x3.embedder_name()
    report["출력"] = str(out_path)
    report_path = out_path.with_name(out_path.stem + "_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--image-pairs", type=Path, default=DEFAULT_IMAGE_PAIRS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--easy-negatives", action="store_true",
                        help="쉬운 음성(교차 350 + DB 350) → pairs_features_easy.csv")
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    report = run(args.labels, args.image_pairs, args.out, easy=args.easy_negatives,
                 metadata_path=args.metadata, seed=args.seed)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
