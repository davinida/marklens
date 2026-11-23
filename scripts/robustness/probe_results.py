"""결과가 이상한 입력(오류는 아니지만) — 묶음마다 기대 결과를 먼저 적어 두고(EXPECT, 실행 전에 고정)
실제 엔진 응답(API 직접, top_k 5)과 견준다. 같아야 하는 입력 묶음은 전체 등급과 상위 5개 출원번호가
같은지 본다.

    ml/venv/bin/python scripts/robustness/probe_results.py [--out DIR]
결과: DIR/probe_results.json. 이미지 파일은 make_images.py 가 만든 것(DB 로고 사본은 비공개
폴더에만). EXPECT 는 2026-11-23 첫 실행 전에 고정했다(그때 파일 sha256 c1aee7be… — 보관 폴더
probe_results_expect.sha256·probe_results.as_run.py). POST_HOC 은 결과를 본 뒤 원인 확인용으로 더한
것이라 따로 표시한다.
"""

from __future__ import annotations

import argparse
import json
import time
import unicodedata
from datetime import date
from pathlib import Path

import requests

API = "http://127.0.0.1:8000"
CAFE = ["G0301", "G0502", "S120602"]  # 카페 세트(커피전문점업·커피·커피 소매업)

# 기대 결과(실행 전에 적음) ------------------------------------------------------------------------
# grade_max: 이 등급보다 높으면 이상, grade_min: 이 등급보다 낮으면 이상, top1: 1위에 있어야 할
# 상표명 조각
EXPECT = {
    "식별력 없는 낱말: 커피": {
        "name": "커피",
        "goods": CAFE,
        "grade_max": "주의",
        "why": "업종의 보통명칭 — 모든 카페 상표와 겹치는 낱말이라 비슷하다고 보면 안 된다",
    },
    "식별력 없는 문장: 맛있는 커피 전문점": {
        "name": "맛있는 커피 전문점",
        "goods": CAFE,
        "grade_max": "주의",
        "why": "기술적 표장 낱말만 — 요부가 없다",
    },
    "1글자: 가": {"name": "가", "grade_max": "주의", "why": "한 글자는 우연히 겹치는 상표가 많다"},
    "2글자: 별빛": {"name": "별빛", "why": "판단 기준 없음 — 관찰만"},
    "숫자만: 1004": {"name": "1004", "grade_max": "주의", "why": "숫자만은 식별력이 약하다"},
    "기호만: ★★★": {"name": "★★★", "grade_max": "주의", "why": "호칭이 없다 — 후보 없음 + 안내"},
    "유명 상표와 같은 이름: 스타벅스(카페)": {
        "name": "스타벅스",
        "goods": CAFE,
        "grade_min": "위험",
        "top1": "STARBUCKS",
        "why": "DB 에 STARBUCKS 등록상표",
    },
    "유명 상표와 같은 이름: STARBUCKS(업종 없음)": {
        "name": "STARBUCKS",
        "grade_min": "위험",
        "top1": "STARBUCKS",
        "why": "같은 이름",
    },
    "한 글자 다른 이름: 스타벅수(카페)": {
        "name": "스타벅수",
        "goods": CAFE,
        "grade_min": "검토 권장",
        "why": "시연 시나리오 F1 — 호칭이 거의 같다",
    },
    "한 글자 다른 이름: 크린토피야(세탁)": {
        "name": "크린토피야",
        "goods": ["S1282"],
        "grade_min": "위험",
        "why": "시연 시나리오 F2",
    },
    "하얀 빈 이미지": {
        "image": "white.png",
        "status": 400,
        "why": "판단할 수 없는 입력 — 계약 §5-1 은 콘텐츠 품질 400(사용자가 이해하는 한국어 문구)",
    },
    "글자만 있는 이미지(COFFEE)": {
        "image": "text_only_coffee.png",
        "grade_max": "주의",
        "why": "글자만 — OCR 이 이름 제안, 도형 유사로 높게 나오면 이상",
    },
    "상표 두 개가 든 이미지": {
        "image": "two_marks.png",
        "why": "관찰 — 둘 중 하나라도 상위 5에 나오는지",
    },
    "간판 사진 + 이름(칠우불고기)": {
        "image_path": "ml/data/trials/images/2024100001460/target.png",
        "name": "칠우불고기",
        "grade_max": "주의",
        "why": "시연 시나리오 N5 — v1.4.1 에서 주의",
    },
    "이름과 로고가 다른 브랜드(STARBUCKS 로고 + 블루커피)": {
        "image_path": "ml/data/images/4020200011726.png",
        "name": "블루커피",
        "grade_min": "위험",
        "why": (
            "로고는 등록된 STARBUCKS 와 같다 — 이름이 달라도 위험이 나와야 한다"
            "(이름이 로고 일치를 가리면 이상)"
        ),
    },
}
SAME_NAME_SETS = {
    "대소문자": ["STARBUCKS", "starbucks", "StarBucks"],
    "띄어쓰기": ["블루커피", "블루 커피", "블 루 커 피"],
    "앞뒤 공백": ["블루커피", "  블루커피  ", "\t블루커피\n"],
    "전각 문자": ["STARBUCKS", "ＳＴＡＲＢＵＣＫＳ"],
    "NFC·NFD": ["블루커피", unicodedata.normalize("NFD", "블루커피")],
    "폭 없는 문자": ["블루커피", "블\u200b루커피", "블루\u2060커피", "블루\u00ad커피"],
    "모양이 같은 다른 글자(키릴)": [
        "STARBUCKS",
        "ST\u0410RBUCKS",
        "S\u0422\u0410RBU\u0421KS",
    ],  # U+0410·U+0422·U+0421 = 라틴 A·T·C 와 모양이 같은 키릴 글자
}
SAME_IMAGE_SETS = {
    "같은 로고 크기·형식·여백": [
        "logo_same.png",
        "logo_half.png",
        "logo.jpg",
        "logo.webp",
        "logo_padded.png",
    ],
    "EXIF 회전": ["ok.jpg", "exif_rotated.jpg"],
    "투명 배경": ["transparent.png"],
}
# 사후 추가(결과를 본 뒤, 원인 확인·고친 뒤 재실행용) — must_include: 상위 5개에 있어야 할 출원번호
STARBUCKS_LOGO = "4020200011726"
POST_HOC = {
    "등록 로고 그대로 + 관련 없는 이름(STARBUCKS 로고 + 몬테로사)": {
        "image_path": "ml/data/images/4020200011726.png",
        "name": "몬테로사",
        "grade_min": "검토 권장",
        "must_include": STARBUCKS_LOGO,
        "why": "R-P0-1 — 이름이 다르면 같은 로고가 목록에서 사라지는지",
    },
    "등록 로고 그대로 + 블루커피 — 같은 로고가 상위 5에": {
        "image_path": "ml/data/images/4020200011726.png",
        "name": "블루커피",
        "must_include": STARBUCKS_LOGO,
        "why": "R-P0-1",
    },
    "설명어만: 맛있는 김밥 전문점(업종 없음)": {
        "name": "맛있는 김밥 전문점",
        "grade_max": "주의",
        "why": "R-P0-2 — 약한 낱말 둘이 같은 순서면 요부로 보는 규칙(combined_weak_run)",
    },
}
GRADES = ["안전", "주의", "검토 권장", "위험"]


def call(key: str, *, name=None, goods=None, image=None, image_path=None, out_dir: Path) -> dict:
    files = []
    if name is not None:
        files.append(("name", (None, name)))
    for code in goods or []:
        files.append(("goods_codes", (None, code)))
    path = None
    if image:
        path = out_dir / "images" / image
    elif image_path:
        path = Path(__file__).resolve().parents[2] / image_path
    if path is not None:
        mime = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}[path.suffix[1:]]
        files.append(("image", (path.name, path.read_bytes(), mime)))
    started = time.perf_counter()
    response = requests.post(
        f"{API}/search/v2?top_k=5", files=files, headers={"X-API-Key": key}, timeout=120
    )
    body = response.json()
    if response.status_code != 200:
        return {
            "status": response.status_code,
            "detail": body.get("detail"),
            "ms": round((time.perf_counter() - started) * 1000),
        }
    overall = body["overall"]
    return {
        "status": 200,
        "grade": overall["grade"],
        "prob": overall["prob"],
        "pattern": overall.get("pattern"),
        "type": overall["query_type"]["type"],
        "suggested": overall["query_type"].get("suggested_name"),
        "caveats": overall["caveats"],
        "ms": round((time.perf_counter() - started) * 1000),
        "top5": [
            (c["id"], c["title"], c["risk"]["grade"], c["risk"]["prob"]) for c in body["candidates"]
        ],
    }


def judge(expect: dict, result: dict) -> str:
    problems = []
    if "status" in expect and result["status"] != expect["status"]:
        problems.append(f"상태 {result['status']}(기대 {expect['status']})")
    if result["status"] == 200:
        grade = result["grade"]
        if (
            expect.get("grade_max")
            and grade
            and GRADES.index(grade) > GRADES.index(expect["grade_max"])
        ):
            problems.append(f"등급 {grade} > 기대 최대 {expect['grade_max']}")
        if expect.get("grade_min") and (
            not grade or GRADES.index(grade) < GRADES.index(expect["grade_min"])
        ):
            problems.append(f"등급 {grade} < 기대 최소 {expect['grade_min']}")
        if expect.get("must_include") and expect["must_include"] not in [
            t[0] for t in result["top5"]
        ]:
            problems.append(f"{expect['must_include']} 가 상위 {len(result['top5'])}개 밖")
        if expect.get("top1") and not (
            result["top5"] and expect["top1"] in (result["top5"][0][1] or "")
        ):
            problems.append(
                f"1위 {result['top5'][0][1] if result['top5'] else None}(기대 {expect['top1']})"
            )
    elif "status" not in expect:
        problems.append(f"상태 {result['status']}")
    return "기대대로" if not problems else "; ".join(problems)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path.home() / "marklens-archive" / f"robustness-{date.today():%Y%m%d}",
    )
    args = parser.parse_args()
    key = (args.out / "api_key").read_text(encoding="utf-8").strip()
    out: dict = {
        "기대": {},
        "사후": {},
        "같아야_하는_이름": {},
        "같아야_하는_이미지": {},
        "같은_요청_두_번": {},
    }
    for section, table in (("기대", EXPECT), ("사후", POST_HOC)):
        for label, expect in table.items():
            result = call(
                key,
                name=expect.get("name"),
                goods=expect.get("goods"),
                image=expect.get("image"),
                image_path=expect.get("image_path"),
                out_dir=args.out,
            )
            verdict = judge(expect, result)
            out[section][label] = {
                "기대": {k: v for k, v in expect.items() if k != "goods"},
                "결과": result,
                "판정": verdict,
            }
            print(
                f"[{section}] {label}: {result.get('status')} {result.get('grade')} "
                f"{result.get('prob')} → {verdict}",
                flush=True,
            )
    for label, names in SAME_NAME_SETS.items():
        rows = [call(key, name=n, out_dir=args.out) for n in names]
        same = all(
            (r.get("grade"), [t[0] for t in r.get("top5", [])])
            == (rows[0].get("grade"), [t[0] for t in rows[0].get("top5", [])])
            for r in rows
        )
        out["같아야_하는_이름"][label] = {
            "입력": [repr(n) for n in names],
            "결과": rows,
            "같음": same,
        }
        print(
            f"[이름] {label}: {'같음' if same else '다름'} — "
            + " | ".join(f"{r.get('grade')} {r.get('prob')}" for r in rows),
            flush=True,
        )
    for label, images in SAME_IMAGE_SETS.items():
        rows = [call(key, image=i, out_dir=args.out) for i in images]
        same = all(
            (r.get("grade"), [t[0] for t in r.get("top5", [])])
            == (rows[0].get("grade"), [t[0] for t in rows[0].get("top5", [])])
            for r in rows
        )
        out["같아야_하는_이미지"][label] = {"입력": images, "결과": rows, "같음": same}
        print(
            f"[이미지] {label}: {'같음' if same else '다름'} — "
            + " | ".join(
                f"{r.get('grade')} {r.get('prob')} 1위 {r['top5'][0][0] if r.get('top5') else None}"
                for r in rows
            ),
            flush=True,
        )
    for label, kwargs in (
        ("이름+업종", {"name": "블루커피", "goods": CAFE}),
        ("이미지", {"image": "logo_same.png"}),
    ):
        first, second = call(key, out_dir=args.out, **kwargs), call(key, out_dir=args.out, **kwargs)
        same = (first.get("grade"), first.get("prob"), first.get("top5")) == (
            second.get("grade"),
            second.get("prob"),
            second.get("top5"),
        )
        out["같은_요청_두_번"][label] = {"같음": same, "첫째": first, "둘째": second}
        print(f"[두 번] {label}: {'같음' if same else '다름'}", flush=True)
    (args.out / "probe_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
