"""업종 세트(business_presets.json) 초안용 후보 표 — 명칭을 지어내지 않고 goods_map 에서 찾는다.

업종 25개의 업종명·별칭(일상어)을 X3 임베더(ml/src/axes/x3_semantic.embed_texts)로 임베딩해
goods_map 명칭 전체(name 기준, 고유 명칭)와의 코사인 상위 N 개와, 로더 부분 일치 검색(정확 > 접두 >
부분) 상위 N 개를 합쳐 업종별 후보 표를 낸다. 세트를 고르는 것은 사람(1차는 Claude Code 초안,
최종 확정은 검수)이며, 이 스크립트는 후보만 만든다.

실행 (프로젝트 루트, 실제 변환표 gz 와 MiniLM 캐시 필요. 첫 실행은 91,591건 임베딩에 약 1~2분):
    ml/venv/bin/python ml/scripts/goods_presets_draft.py [--top 10]
        [--out ml/data/staging/goods_presets_candidates.md]
        [--json ml/data/staging/goods_presets_candidates.json]
명칭 임베딩은 ml/data/staging/goods_map_name_embeddings_<모델>.npz 에 캐시한다
(ml/data 는 gitignore).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

ML_ROOT = Path(__file__).resolve().parent.parent
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from src.axes import x3_semantic as x3  # noqa: E402
from src.axes.goods_map import TIER_EXACT, TIER_PREFIX, GoodsMap, load_goods_map  # noqa: E402

STAGING = ML_ROOT / "data" / "staging"
EMBED_CHUNK = 4096
TIER_LABEL = {TIER_EXACT: "정확", TIER_PREFIX: "접두"}

# (id, 업종명, 별칭 — 소상공인이 실제로 쓰는 일상어). 별칭에 업종명 자체도 포함한다.
BUSINESSES: list[tuple[str, str, list[str]]] = [
    ("cafe", "카페", ["카페", "커피숍", "커피집", "커피 전문점"]),
    ("chicken", "치킨집", ["치킨집", "치킨", "통닭", "닭강정"]),
    ("korean_restaurant", "식당(한식)", ["식당", "한식당", "한식", "밥집", "음식점"]),
    ("bunsik", "분식집", ["분식집", "분식", "떡볶이", "김밥"]),
    ("pub", "술집", ["술집", "호프집", "주점", "포차", "바"]),
    ("bakery", "빵집", ["빵집", "베이커리", "제과점", "케이크"]),
    ("pizza", "피자집", ["피자집", "피자"]),
    ("lodging", "펜션·숙박", ["펜션", "숙박", "게스트하우스", "민박", "모텔"]),
    ("hair_salon", "미용실", ["미용실", "헤어샵", "헤어살롱", "이발소"]),
    ("nail", "네일샵", ["네일샵", "네일아트", "네일"]),
    ("fitness", "헬스장·필라테스", ["헬스장", "필라테스", "피트니스", "요가"]),
    ("academy", "학원", ["학원", "교습소", "과외", "영어학원"]),
    ("realty", "부동산", ["부동산", "공인중개사", "부동산중개"]),
    ("flower", "꽃집", ["꽃집", "플라워샵", "꽃배달", "꽃"]),
    (
        "clothing",
        "옷가게·온라인 의류 쇼핑몰",
        ["옷가게", "의류", "옷", "의류 쇼핑몰", "온라인 쇼핑몰"],
    ),
    ("cosmetics", "화장품 브랜드", ["화장품", "코스메틱", "스킨케어"]),
    ("health_food", "건강식품", ["건강식품", "건강기능식품", "영양제", "홍삼"]),
    ("pet", "반려동물용품", ["반려동물", "펫샵", "애견용품", "사료"]),
    ("convenience", "편의점·마트", ["편의점", "마트", "슈퍼마켓", "슈퍼"]),
    ("laundry", "세탁소", ["세탁소", "세탁", "빨래방"]),
    ("photo", "사진관", ["사진관", "사진", "스튜디오", "포토"]),
    ("software", "앱·소프트웨어 스타트업", ["앱", "어플", "소프트웨어", "스타트업", "플랫폼"]),
    ("creator", "유튜브·콘텐츠 제작", ["유튜브", "유튜버", "콘텐츠", "영상 제작", "크리에이터"]),
    ("interior", "인테리어", ["인테리어", "실내장식", "리모델링"]),
    ("moving_cleaning", "이사·청소", ["이사", "이삿짐", "청소", "청소업체"]),
]


def name_embeddings(gm: GoodsMap) -> tuple[list[str], np.ndarray]:
    """고유 명칭 목록과 (n, dim) 단위 벡터. 모델별 npz 캐시."""
    names = sorted({entry.name for entry in gm.entries})
    model_tag = re.sub(r"[^A-Za-z0-9]+", "_", x3.configured_model())
    cache = STAGING / f"goods_map_name_embeddings_{model_tag}.npz"
    if cache.exists():
        data = np.load(cache, allow_pickle=False)
        cached = [str(n) for n in data["names"]]
        if cached == names:
            return names, data["vectors"]
    started = time.perf_counter()
    chunks = [
        x3.embed_texts(names[i : i + EMBED_CHUNK]) for i in range(0, len(names), EMBED_CHUNK)
    ]
    vectors = np.concatenate(chunks).astype(np.float32)
    STAGING.mkdir(parents=True, exist_ok=True)
    np.savez(cache, names=np.array(names), vectors=vectors)
    elapsed = time.perf_counter() - started
    print(f"... 명칭 {len(names)}개 임베딩 {elapsed:.0f}s → {cache}", file=sys.stderr)
    return names, vectors


def classes_of(gm: GoodsMap, name: str) -> list[int]:
    return sorted({entry.nice_class for entry in gm.entries if entry.name == name})


def embedding_candidates(
    gm: GoodsMap, names: list[str], vectors: np.ndarray, terms: list[str], top: int
) -> list[dict]:
    query = x3.embed_texts(terms)  # (t, dim)
    scores = vectors @ query.T  # (n, t)
    best = scores.max(axis=1)
    best_term = scores.argmax(axis=1)
    order = np.argsort(-best)[:top]
    return [
        {
            "name": names[i],
            "classes": classes_of(gm, names[i]),
            "score": round(float(best[i]), 3),
            "term": terms[int(best_term[i])],
        }
        for i in order
    ]


def search_candidates(gm: GoodsMap, terms: list[str], top: int) -> list[dict]:
    merged: dict[tuple[str, int], dict] = {}
    for term in terms:
        for match in gm.search(term, limit=top):
            key = (match.name, match.nice_class)
            row = {
                "name": match.name,
                "nice_class": match.nice_class,
                "tier": match.tier,
                "term": term,
                "alias": match.matched_alias,
            }
            if key not in merged or row["tier"] < merged[key]["tier"]:
                merged[key] = row
    rows = sorted(merged.values(), key=lambda r: (r["tier"], len(r["name"]), r["name"]))
    return rows[:top]


def render(business: tuple[str, str, list[str]], emb: list[dict], hit: list[dict]) -> str:
    pid, label, aliases = business
    lines = [f"### {label} (`{pid}`) — 별칭: {', '.join(aliases)}", "",
             "| 근거 | 후보 명칭 | 류 | 점수·일치 |", "|---|---|---|---|"]
    for row in emb:
        cls = "·".join(str(c) for c in row["classes"])
        lines.append(f"| 임베딩 | {row['name']} | {cls} | {row['score']:.3f} ({row['term']}) |")
    for row in hit:
        tier = TIER_LABEL.get(row["tier"], "부분")
        via = f"{tier}, {row['term']}" + (f", 고시 명칭 {row['alias']}" if row["alias"] else "")
        lines.append(f"| 부분 일치 | {row['name']} | {row['nice_class']} | {via} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--out", type=Path, default=STAGING / "goods_presets_candidates.md")
    parser.add_argument("--json", type=Path, default=STAGING / "goods_presets_candidates.json")
    args = parser.parse_args()

    gm = load_goods_map()
    names, vectors = name_embeddings(gm)
    sections: list[str] = [
        f"# 업종 세트 후보 표 ({time.strftime('%Y-%m-%d')}, 모델 {x3.configured_model()}, "
        f"명칭 {len(names)}개, 업종 {len(BUSINESSES)}개, 상위 {args.top})",
        "",
    ]
    payload: dict[str, dict] = {}
    for business in BUSINESSES:
        pid, label, aliases = business
        terms = list(dict.fromkeys([label, *aliases]))
        emb = embedding_candidates(gm, names, vectors, terms, args.top)
        hit = search_candidates(gm, terms, args.top)
        sections.append(render(business, emb, hit))
        payload[pid] = {"업종명": label, "별칭": aliases, "embedding": emb, "search": hit}
    text = "\n".join(sections)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + "\n", encoding="utf-8")
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(text)
    print(f"\n저장: {args.out}, {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
