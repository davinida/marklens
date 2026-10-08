"""정답 데이터 특징 생성 — 라벨된 심결례 쌍마다 4축 점수와 결측 플래그를 계산해 학습 데이터
(`pairs_features.csv`)를 만든다. 학습(가중치 적합)은 하지 않는다. KIPRIS 호출 0.

실행 (프로젝트 루트에서. X3 는 실제 모델 — MARKLENS_FAKE_ML 없이. MiniLM 은 HuggingFace 캐시에서
읽는다):
    ml/venv/bin/python ml/scripts/pairs_features.py [--labels ml/data/trials/labels.csv]
        [--image-pairs ml/data/trials/image_pairs_v1.csv] [--out ml/data/trials/pairs_features.csv]

대상: labels.csv 에서 LLM pass a·b 판정이 일치한 유사·비유사 행(backend/scripts/trials_enrich.py
      target_rows 와 같은 규칙, 350행).
이름: A = 상표A_명칭. B = 상대표장_명칭_kipris > 본문 > ocr(`이름B_출처`). 이름이 없으면 이름 기반
      축(x1·x2_text·x3)은 결측(빈 칸).
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
from src.axes.x1_phonetic import has_pronunciation, phonetic_similarity  # noqa: E402
from src.axes.x2_ortho import has_spelling, orthographic_similarity  # noqa: E402
from src.axes.x4_goods import has_goods  # noqa: E402

DEFAULT_BASE = ML_ROOT / "data" / "trials"
DEFAULT_LABELS = DEFAULT_BASE / "labels.csv"
DEFAULT_IMAGE_PAIRS = DEFAULT_BASE / "image_pairs_v1.csv"
DEFAULT_OUT = DEFAULT_BASE / "pairs_features.csv"

POSITIVE = ("유사", "비유사")
NAME_B_SOURCES = (("kipris", "상대표장_명칭_kipris"), ("본문", "상대표장_명칭_본문"),
                  ("ocr", "상대표장_명칭_ocr"))
META_COLUMNS = [
    "심판번호", "종류", "상대번호", "최종라벨", "표장라벨", "판단축", "판단축_출처", "상표유형",
    "상표유형_출처", "이름A", "이름B", "이름B_출처", "메모",
]
AXIS_COLUMNS = ["x1", "x2_text", "x2_fig", "x2_whole", "x3", "x3_raw", "x4"]
FLAG_COLUMNS = [
    "has_names", "has_pron_a", "has_pron_b", "has_meaning_a", "has_meaning_b", "has_spelling_a",
    "has_spelling_b", "has_goods", "has_image", "has_fig",
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


def name_b(row: dict) -> tuple[str, str]:
    """상대 표장 이름과 출처: kipris > 본문 > ocr. 없으면 ("", "")."""
    for source, column in NAME_B_SOURCES:
        value = (row.get(column) or "").strip()
        if value:
            return value, source
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


def build_row(row: dict, image_row: dict | None) -> dict:
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
    out = {
        "심판번호": row["심판번호"], "종류": row.get("종류", ""),
        "상대번호": row.get("상표B_번호", "") or "", "최종라벨": label, "표장라벨": mark,
        "판단축": axes, "판단축_출처": axes_source, "상표유형": kind, "상표유형_출처": kind_source,
        "이름A": name_a, "이름B": name_b_, "이름B_출처": source_b, "메모": memo,
        "x1": "", "x2_text": "", "x2_fig": _fmt(x2_fig), "x2_whole": _fmt(x2_whole), "x3": "",
        "x3_raw": "", "x4": _fmt(x4),
        "has_names": int(has_names),
        "has_pron_a": int(has_pronunciation(name_a)), "has_pron_b": int(has_pronunciation(name_b_)),
        "has_meaning_a": int(x3.has_meaning(name_a)), "has_meaning_b": int(x3.has_meaning(name_b_)),
        "has_spelling_a": int(has_spelling(name_a)), "has_spelling_b": int(has_spelling(name_b_)),
        "has_goods": int(goods_ok), "has_image": int(x2_whole is not None),
        "has_fig": int(x2_fig is not None),
    }
    if has_names:
        gated, raw = x3_scores(name_a, name_b_)
        out["x1"] = _fmt(phonetic_similarity(name_a, name_b_))
        out["x2_text"] = _fmt(orthographic_similarity(name_a, name_b_))
        out["x3"] = _fmt(gated)
        out["x3_raw"] = _fmt(raw)
    return out


def build_features(label_rows: list[dict], image_rows: list[dict]) -> list[dict]:
    by_key, by_case = image_index(image_rows)
    return [build_row(row, find_image_row(row, by_key, by_case)) for row in target_rows(label_rows)]


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


def run(labels_path: Path, image_pairs_path: Path, out_path: Path) -> dict:
    label_rows = read_csv(labels_path)
    image_rows = read_csv(image_pairs_path) if Path(image_pairs_path).exists() else []
    features = build_features(label_rows, image_rows)
    write_csv(out_path, features)
    report = summarize(features)
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
    args = parser.parse_args(argv)
    report = run(args.labels, args.image_pairs, args.out)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
