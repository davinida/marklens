#!/usr/bin/env python3
"""
KIPRIS 인덱스에 대한 검증용 검색 스크립트.

이 스크립트는 다음 흐름을 한 번에 보여주는 청사진 역할입니다.
Phase 2-B FastAPI 백엔드가 동일한 결합 로직을 그대로 참고합니다.

    [쿼리 이미지] --encode--> [임베딩]
                              ↓
                           search()
                              ↓
              [(distances, indices) 튜플]
                              ↓
       [인덱스 메타]  image_paths[i]로 출원번호.png 회복
                              ↓
       [KIPRIS 메타]  이미지파일 키로 trademark 객체 조회
                              ↓
       [scoring]     distances 전체를 등급으로 변환
                              ↓
                       사람이 읽기 좋은 출력

사용법:
    python scripts/kipris_search.py --query <이미지경로> [--top-k 5]
"""

import os

# macOS Apple Silicon의 PyTorch + FAISS OpenMP 라이브러리 충돌 방지
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import argparse
import json
import sys
from pathlib import Path

# 이 스크립트는 ml/scripts/에 위치하므로, src 모듈을 import하려면
# 부모 디렉토리(ml/)를 sys.path에 추가해야 합니다.
ML_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_ROOT))

from src.embedding import encode_image
from src.scoring import score_results
from src.search import load_index, search

# === 고정 경로 ===
# Phase 2-D 산출물: 상표한글명/비엔나코드 등 풍부한 정보가 든 메타데이터
KIPRIS_META_PATH = Path("data/kipris_metadata.json")

# Phase 2 인덱싱 산출물: 인덱스 + image_paths(순번 ↔ 파일명) 매핑
INDEX_PATH = Path("data/index/kipris.faiss")
INDEX_META_PATH = Path("data/index/kipris_metadata.json")


def build_image_to_trademark_lookup(kipris_meta: dict) -> dict:
    """
    KIPRIS 메타데이터에서 '이미지파일명' → trademark 객체 사전을 만듭니다.

    이 사전 한 번 만들어두면 검색 결과의 어떤 파일명이든
    O(1)로 trademark 정보를 회복할 수 있습니다.
    """
    return {t["이미지파일"]: t for t in kipris_meta["trademarks"]}


def format_trademark_brief(tm: dict) -> str:
    """trademark 객체에서 핵심 식별 정보 한 줄을 만듭니다."""
    parts = [f"출원번호={tm['출원번호']}"]
    if tm.get("상표한글명"):
        parts.append(f"한글명='{tm['상표한글명']}'")
    elif tm.get("상표영문명"):
        parts.append(f"영문명='{tm['상표영문명']}'")
    if tm.get("출원인"):
        parts.append(f"출원인='{tm['출원인']}'")
    return ", ".join(parts)


def print_grade(grade: dict) -> None:
    """scoring.score_results 결과 dict를 보기 좋게 출력합니다."""
    print()
    print("─── 등급 판정 ───")
    print(f"  등급      : {grade['grade_name']} ({grade['grade_code']})")
    print(f"  메시지    : {grade['message']}")
    print(f"  top1 유사도 : {grade['top1_similarity']:.4f}")
    print(f"  격차 A      : {grade['separability_a']:.4f}  (top1 - top2)")
    print(f"  격차 B      : {grade['separability_b']:.4f}  (top1 - mean)")
    if grade["warnings"]:
        print("  경고:")
        for w in grade["warnings"]:
            print(f"    - {w}")


def main():
    parser = argparse.ArgumentParser(
        description="KIPRIS 인덱스 검색 + 상표 정보 결합 + 등급 산출"
    )
    parser.add_argument(
        "--query", type=Path, required=True,
        help="쿼리 이미지 파일 경로",
    )
    parser.add_argument(
        "--top-k", type=int, default=5,
        help="반환할 상위 결과 수 (기본: 5)",
    )
    args = parser.parse_args()

    if args.top_k < 1:
        raise ValueError(f"--top-k must be >= 1, got {args.top_k}")
    if not args.query.exists():
        raise FileNotFoundError(f"Query image not found: {args.query}")
    if not INDEX_PATH.exists():
        raise FileNotFoundError(f"Index not found: {INDEX_PATH}")
    if not INDEX_META_PATH.exists():
        raise FileNotFoundError(f"Index metadata not found: {INDEX_META_PATH}")
    if not KIPRIS_META_PATH.exists():
        raise FileNotFoundError(f"KIPRIS metadata not found: {KIPRIS_META_PATH}")

    # 1) 인덱스 + 두 메타데이터 로드
    index = load_index(INDEX_PATH)
    with open(INDEX_META_PATH, "r", encoding="utf-8") as f:
        index_meta = json.load(f)
    with open(KIPRIS_META_PATH, "r", encoding="utf-8") as f:
        kipris_meta = json.load(f)

    image_paths = index_meta["image_paths"]            # 인덱스 순번 → 파일명
    lookup = build_image_to_trademark_lookup(kipris_meta)  # 파일명 → trademark

    print(f"Query: {args.query}")
    print(f"Index: {INDEX_PATH} (벡터 {index.ntotal}개)")
    print(f"KIPRIS 상표 DB: {KIPRIS_META_PATH} ({len(kipris_meta['trademarks'])}건)")

    # 2) 쿼리 임베딩 + 검색
    query_emb = encode_image(args.query)
    distances, indices = search(index, query_emb, k=args.top_k)

    # 3) 결합 출력: 순번 → 파일명 → trademark 객체
    print()
    print(f"=== Top-{len(distances)} 검색 결과 ===")
    miss_count = 0
    for rank, (d, i) in enumerate(zip(distances, indices), 1):
        idx_int = int(i)
        if not (0 <= idx_int < len(image_paths)):
            print(f"  {rank}. <invalid index {i}>  similarity={float(d):.4f}")
            continue

        filename = image_paths[idx_int]
        tm = lookup.get(filename)
        if tm is None:
            # KIPRIS 메타에 매칭되는 항목이 없는 경우 — 계속 진행
            miss_count += 1
            print(f"  {rank}. [메타 매칭 실패: {filename}]  similarity={float(d):.4f}")
            continue

        brief = format_trademark_brief(tm)
        print(f"  {rank}. {brief}")
        print(f"      파일: {filename}    similarity={float(d):.4f}")
        # 부가 정보 (있을 때만)
        if tm.get("비엔나코드"):
            v = tm["비엔나코드"]
            vienna_preview = ", ".join(v[:3]) + (f" ... (+{len(v)-3})" if len(v) > 3 else "")
            print(f"      비엔나: {vienna_preview}")
        if tm.get("류"):
            print(f"      류    : {tm['류']}")

    if miss_count > 0:
        print()
        print(f"※ {miss_count}건의 결과가 KIPRIS 메타에 매칭되지 않았습니다.")

    # 4) 등급 산출
    grade = score_results(distances)
    print_grade(grade)


if __name__ == "__main__":
    main()
