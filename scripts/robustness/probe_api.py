"""입력 경계·이상한 입력 점검 — API 직접(백엔드 8000, X-API-Key)과 브라우저 중계(프런트 3000,
Turnstile 모의 토큰) 두 경로에 같은 입력을 보내고 상태 코드·오류 문구·응답 시간·정보 노출을 본다.

    bash scripts/robustness/servers.sh start            # 먼저(실제 모델, 프로덕션 빌드)
    ml/venv/bin/python scripts/robustness/make_images.py
    ml/venv/bin/python scripts/robustness/probe_api.py [--out DIR] [--only 접두어]

기대 상태는 API 계약 v2 §1·§5 에서 왔다. 계약이 정하지 않은 입력은 expect=None("계약 공백")으로 두고
판정하지 않는다. 결과: DIR/probe_api.{json,md}. KIPRIS 를 부르는 경로는 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import uuid
from datetime import date
from pathlib import Path

import requests

API = "http://127.0.0.1:8000"
BFF = "http://127.0.0.1:3000"
SLOW_SECONDS = 5.0
LEAK_PATTERNS = [
    r"/Users/",
    r"/home/",
    r"site-packages",
    r"Traceback",
    r'File "',
    r"\bPIL\b",
    r"Errno",
    r"pydantic",
    r"starlette",
    r"fastapi",
    r"undici",
    r"TypeError",
    r"\bat \S+:\d+",
    r"ml/data",
    r"backend/src",
    r"node_modules",
]
TECH_WORDS = [
    r"\bimage\b",
    r"\bname\b",
    r"goods_codes",
    r"type_override",
    r"multipart",
    r"bytes",
    r"Content-Type",
    r"image/\w+",
    r"top_k",
    r"Engine",
    r"PNG|JPEG|WEBP|GIF",
]


# 빈 이미지(완전 투명·한 가지 색) — 처음 점검(2026-11-23)은 200 을 기대해 "기대와 다름"이었다
BLANK_NOTE = "빈 이미지는 계약 v2 §5-1 의 콘텐츠 품질 400(R-P1-1)"


def default_out() -> Path:
    return Path.home() / "marklens-archive" / f"robustness-{date.today():%Y%m%d}"


class Case:
    def __init__(
        self,
        cid,
        group,
        title,
        *,
        fields=None,
        raw=None,
        content_type=None,
        method="POST",
        query="",
        expect=None,
        gap=None,
        note="",
    ):
        self.cid, self.group, self.title = cid, group, title
        self.fields = fields or []  # (필드 이름, 값 str 또는 (파일 이름, 바이트, MIME 또는 None))
        self.raw, self.content_type, self.method, self.query = raw, content_type, method, query
        self.expect = expect  # {"api": 코드 또는 집합, "bff": …} — None 이면 계약 공백
        self.gap, self.note = gap, note


def _codes(n: int) -> list[str]:
    return [f"G{1000 + i:04d}" for i in range(n)]


def build_cases(images: Path) -> list[Case]:
    def img(name, mime=None, filename=None):
        data = (images / name).read_bytes()
        meta = json.loads((images / "manifest.json").read_text(encoding="utf-8")).get(name, {})
        return ("image", (filename or name, data, mime if mime is not None else meta.get("mime")))

    both = lambda code: {"api": code, "bff": code}  # noqa: E731
    nfd = unicodedata.normalize("NFD", "블루커피")
    long_nfd = unicodedata.normalize("NFD", "강" * 40)  # 40음절 = 120 코드 포인트
    cases = [
        Case(
            "A1",
            "빈 입력",
            "아무 필드도 없음(빈 multipart)",
            raw=b"--B--\r\n",
            content_type="multipart/form-data; boundary=B",
            expect=both(400),
        ),
        Case(
            "A2",
            "빈 입력",
            "업종만(카페 G0301)",
            fields=[("goods_codes", "G0301")],
            expect=both(200),
        ),
        Case("A3", "빈 입력", "이름이 공백뿐", fields=[("name", "   ")], expect=both(400)),
        Case("A4", "빈 입력", "이름이 줄바꿈뿐", fields=[("name", "\n\n\r\n")], expect=both(400)),
        Case(
            "A5",
            "빈 입력",
            "이름이 전각 공백뿐(U+3000)",
            fields=[("name", "　　")],
            expect=both(400),
        ),
        Case(
            "A6",
            "빈 입력",
            "이름이 폭 없는 공백뿐(U+200B)",
            fields=[("name", "​​")],
            gap="폭 없는 문자만인 이름을 빈 입력으로 볼지 계약에 없음",
        ),
        Case(
            "A7",
            "빈 입력",
            "goods_codes 가 빈 문자열",
            fields=[("goods_codes", "")],
            expect=both(400),
        ),
        Case(
            "A8",
            "빈 입력",
            "goods_codes 가 쉼표·공백뿐",
            fields=[("goods_codes", " , ,")],
            expect=both(400),
        ),
        Case("B1", "이름", "1글자 한글", fields=[("name", "가")], expect=both(200)),
        Case("B2", "이름", "1글자 영문", fields=[("name", "A")], expect=both(200)),
        Case("B3", "이름", "100자(경계)", fields=[("name", "블루커피" * 25)], expect=both(200)),
        Case("B4", "이름", "101자", fields=[("name", "블루커피" * 25 + "가")], expect=both(422)),
        Case("B5", "이름", "1천 자", fields=[("name", "가" * 1000)], expect=both(422)),
        Case("B6", "이름", "1만 자", fields=[("name", "가" * 10000)], expect=both(422)),
        Case("B7", "이름", "이모지 섞음", fields=[("name", "☕블루커피🍰")], expect=both(200)),
        Case(
            "B8",
            "이름",
            "이모지만(가족 ZWJ)",
            fields=[("name", "👨‍👩‍👧‍👦")],
            expect=both(200),
            note="§5-4 후보 0건이면 200 + NO_CANDIDATES",
        ),
        Case(
            "B9",
            "이름",
            "NUL·제어 문자",
            fields=[("name", "블루\x00커피\x07")],
            gap="제어 문자가 든 이름의 처리(거절/제거)가 계약에 없음",
        ),
        Case(
            "B10",
            "이름",
            "ANSI 이스케이프",
            fields=[("name", "\x1b[31m블루커피\x1b[0m")],
            gap="제어 문자가 든 이름의 처리가 계약에 없음",
        ),
        Case("B11", "이름", "폭 없는 문자 끼움", fields=[("name", "블​루‍커피")], expect=both(200)),
        Case("B12", "이름", "한글 자모만", fields=[("name", "ㅂㄹㄹㅋㅍ")], expect=both(200)),
        Case("B13", "이름", "NFD 로 분해된 한글", fields=[("name", nfd)], expect=both(200)),
        Case(
            "B14",
            "이름",
            "NFD 40음절(NFC 40자·코드 포인트 120)",
            fields=[("name", long_nfd)],
            gap=(
                "100자를 코드 포인트로 셀지 정규화 뒤 글자로 셀지 계약에 없음"
                "(지금은 정규화 전 코드 포인트)"
            ),
        ),
        Case("B15", "이름", "한자", fields=[("name", "藍色咖啡")], expect=both(200)),
        Case("B16", "이름", "일본어", fields=[("name", "ブルーコーヒー")], expect=both(200)),
        Case("B17", "이름", "숫자만", fields=[("name", "1234")], expect=both(200)),
        Case(
            "B18",
            "이름",
            "스크립트 조각",
            fields=[("name", "<script>alert(1)</script>")],
            expect=both(200),
        ),
        Case(
            "B19",
            "이름",
            "이미지 태그 조각",
            fields=[("name", '<img src=x onerror="alert(1)">')],
            expect=both(200),
        ),
        Case(
            "B20",
            "이름",
            "오른쪽→왼쪽 덮어쓰기(U+202E)",
            fields=[("name", "‮블루커피")],
            gap="방향 제어 문자 처리가 계약에 없음",
        ),
        Case(
            "B21",
            "이름",
            "잘못된 UTF-8 바이트",
            raw=(
                b'--B\r\nContent-Disposition: form-data; name="name"\r\n\r\n'
                b"\xff\xfe\xbf\r\n--B--\r\n"
            ),
            content_type="multipart/form-data; boundary=B",
            gap="UTF-8 이 아닌 텍스트 필드 처리가 계약에 없음",
        ),
        Case("B22", "이름", "기호만", fields=[("name", "!!!@@@###")], expect=both(200)),
        Case(
            "C1",
            "업종",
            "없는 코드(형식은 맞음)",
            fields=[("goods_codes", "G9999")],
            expect=both(200),
        ),
        Case(
            "C2",
            "업종",
            "중복 코드",
            fields=[("goods_codes", "G0301"), ("goods_codes", "G0301,g0301")],
            expect=both(200),
        ),
        Case(
            "C3",
            "업종",
            "60개(경계)",
            fields=[("goods_codes", ",".join(_codes(60)))],
            expect=both(200),
        ),
        Case(
            "C4", "업종", "61개", fields=[("goods_codes", ",".join(_codes(61)))], expect=both(422)
        ),
        Case("C5", "업종", "소문자·공백", fields=[("goods_codes", " g0301 ")], expect=both(200)),
        Case(
            "C6", "업종", "형식이 틀림(G03X1)", fields=[("goods_codes", "G03X1")], expect=both(422)
        ),
        Case(
            "C7",
            "업종",
            "세미콜론으로 이음",
            fields=[("goods_codes", "G0301;S2005")],
            expect=both(422),
        ),
        Case(
            "C8", "업종", "1만 자 문자열", fields=[("goods_codes", "G" * 10000)], expect=both(422)
        ),
        Case(
            "C9",
            "업종",
            "같은 코드 필드 2천 개",
            fields=[("goods_codes", "G0301")] * 2000,
            gap="필드 개수 상한이 계약에 없음(Starlette 기본 1,000 필드)",
        ),
        Case(
            "D1",
            "유형 고치기",
            "도형 + 이름",
            fields=[("name", "블루커피"), ("type_override", "도형")],
            expect=both(200),
        ),
        Case(
            "D2",
            "유형 고치기",
            "허용되지 않은 값(로고)",
            fields=[("name", "블루커피"), ("type_override", "로고")],
            expect=both(422),
        ),
        Case(
            "D3",
            "유형 고치기",
            "영어 값(Text)",
            fields=[("name", "블루커피"), ("type_override", "Text")],
            expect=both(422),
        ),
        Case(
            "D4",
            "유형 고치기",
            "빈 문자열",
            fields=[("name", "블루커피"), ("type_override", "")],
            gap="빈 type_override 를 없음으로 볼지 계약에 없음(지금 422)",
        ),
        Case(
            "D5",
            "유형 고치기",
            "뒤 공백(도형␠)",
            fields=[("name", "블루커피"), ("type_override", "도형 ")],
            gap="열거값 앞뒤 공백 처리가 계약에 없음",
        ),
        Case(
            "D6",
            "유형 고치기",
            "유형만(다른 입력 없음)",
            fields=[("type_override", "도형")],
            expect=both(400),
        ),
        Case("E1", "이미지", "정상 PNG", fields=[img("ok.png")], expect=both(200)),
        Case("E2", "이미지", "정상 JPEG", fields=[img("ok.jpg")], expect=both(200)),
        Case("E3", "이미지", "정상 WebP", fields=[img("ok.webp")], expect=both(200)),
        Case(
            "E4", "이미지", "깨진 PNG(절반)", fields=[img("broken_truncated.png")], expect=both(400)
        ),
        Case("E5", "이미지", "무작위 바이트", fields=[img("broken_garbage.png")], expect=both(415)),
        Case("E6", "이미지", "0 바이트", fields=[img("empty.png")], expect=both(400)),
        Case(
            "E7",
            "이미지",
            "JPEG 를 png 로 위장",
            fields=[img("jpeg_named_png.png")],
            expect=both(200),
            note="Content-Type 은 1차 필터, 내용이 허용 형식이면 통과(validation.py)",
        ),
        Case(
            "E8",
            "이미지",
            "PNG 를 jpg 로 위장",
            fields=[img("png_named_jpg.jpg")],
            expect=both(200),
        ),
        Case(
            "E9", "이미지", "WebP 를 png 로 위장", fields=[img("webp_as_png.png")], expect=both(200)
        ),
        Case("E10", "이미지", "정적 GIF", fields=[img("static.gif")], expect=both(415)),
        Case("E11", "이미지", "HEIC(image/heic)", fields=[img("fake.heic")], expect=both(415)),
        Case(
            "E12",
            "이미지",
            "HEIC 내용 + image/jpeg",
            fields=[img("heic_as_jpeg.jpg")],
            expect=both(415),
        ),
        Case("E13", "이미지", "애니메이션 GIF", fields=[img("animated.gif")], expect=both(415)),
        Case(
            "E14",
            "이미지",
            "APNG(2프레임)",
            fields=[img("animated.png")],
            gap="애니메이션 이미지의 어느 프레임을 쓸지 계약에 없음",
        ),
        Case(
            "E15",
            "이미지",
            "애니메이션 WebP",
            fields=[img("animated.webp")],
            gap="애니메이션 이미지의 어느 프레임을 쓸지 계약에 없음",
        ),
        Case("E16", "이미지", "CMYK JPEG", fields=[img("cmyk.jpg")], expect=both(200)),
        Case("E17", "이미지", "16비트 회색조 PNG", fields=[img("gray16.png")], expect=both(200)),
        Case("E18", "이미지", "투명 배경 PNG", fields=[img("transparent.png")], expect=both(200)),
        Case(
            "E19",
            "이미지",
            "완전 투명 PNG",
            fields=[img("fully_transparent.png")],
            expect=both(400),
            note=BLANK_NOTE,
        ),
        Case("E20", "이미지", "팔레트 PNG", fields=[img("palette.png")], expect=both(200)),
        Case("E21", "이미지", "EXIF 회전 JPEG", fields=[img("exif_rotated.jpg")], expect=both(200)),
        Case("E22", "이미지", "1×1", fields=[img("1x1.png")], expect=both(400)),
        Case("E23", "이미지", "31×31", fields=[img("31x31.png")], expect=both(400)),
        Case("E24", "이미지", "32×32(경계)", fields=[img("32x32.png")], expect=both(200)),
        Case(
            "E25", "이미지", "가늘고 긴 4000×32", fields=[img("thin_4000x32.png")], expect=both(200)
        ),
        Case(
            "E26", "이미지", "가늘고 긴 32×4000", fields=[img("thin_32x4000.png")], expect=both(200)
        ),
        Case(
            "E27",
            "이미지",
            "4096×4096(경계, 흰색)",
            fields=[img("max_4096.png")],
            expect=both(400),
            note=BLANK_NOTE,
        ),
        Case(
            "E28", "이미지", "4097×64(상한 + 1)", fields=[img("over_4097x64.png")], expect=both(400)
        ),
        Case(
            "E29",
            "이미지",
            "픽셀 수 폭탄 20000×20000",
            fields=[img("bomb_20000.png")],
            expect=both(400),
        ),
        Case(
            "E30",
            "이미지",
            "4096×4096 회색조 폭탄(허용 범위)",
            fields=[img("bomb_4096_gray.png")],
            expect=both(400),
            note=BLANK_NOTE,
        ),
        Case("E31", "이미지", "약 17MB(상한 초과)", fields=[img("big_12mb.png")], expect=both(413)),
        Case(
            "E32", "이미지", "약 9.7MB(상한 아래)", fields=[img("near_10mb.png")], expect=both(200)
        ),
        Case("E33", "이미지", "SVG", fields=[img("logo.svg")], expect=both(415)),
        Case(
            "E34",
            "이미지",
            "이미지 필드 두 개",
            fields=[img("ok.png"), img("ok.jpg")],
            expect=both(422),
        ),
        Case(
            "E35",
            "이미지",
            "옛 필드 이름 file 만",
            fields=[("file", ("ok.png", (images / "ok.png").read_bytes(), "image/png"))],
            expect=both(400),
        ),
        Case(
            "E36", "이미지", "image 를 텍스트로", fields=[("image", "not-a-file")], expect=both(415)
        ),
        Case(
            "E37",
            "이미지",
            "파일 이름에 경로(../../x.png)",
            fields=[img("ok.png", filename="../../x.png")],
            expect=both(200),
        ),
        Case(
            "E38",
            "이미지",
            "파트에 Content-Type 없음",
            fields=[img("ok.png", mime="")],
            gap="이미지 파트의 Content-Type 이 없을 때 계약에 없음(BFF 415·API 는 디코딩으로 통과)",
        ),
        Case("F1", "메서드", "GET", method="GET", expect=both(405)),
        Case("F2", "메서드", "PUT", method="PUT", fields=[("name", "블루커피")], expect=both(405)),
        Case("F3", "메서드", "DELETE", method="DELETE", expect=both(405)),
        Case(
            "F4",
            "Content-Type",
            "JSON 본문",
            raw=json.dumps({"name": "블루커피"}).encode(),
            content_type="application/json",
            gap="multipart 가 아닌 본문의 상태 코드가 계약에 없음(400/415)",
        ),
        Case(
            "F5",
            "Content-Type",
            "urlencoded 본문(name=블루커피)",
            raw="name=블루커피".encode(),
            content_type="application/x-www-form-urlencoded",
            gap="계약은 multipart 만 — urlencoded 를 받을지 없음",
        ),
        Case(
            "F6",
            "Content-Type",
            "multipart 인데 boundary 없음",
            raw=b"name=x",
            content_type="multipart/form-data",
            expect=both(400),
        ),
        Case(
            "F7",
            "Content-Type",
            "text/plain",
            raw="블루커피".encode(),
            content_type="text/plain",
            gap="multipart 가 아닌 본문의 상태 코드가 계약에 없음",
        ),
        Case("G1", "top_k", "0", query="?top_k=0", fields=[("name", "블루커피")], expect=both(422)),
        Case(
            "G2", "top_k", "21", query="?top_k=21", fields=[("name", "블루커피")], expect=both(422)
        ),
        Case(
            "G3",
            "top_k",
            "abc",
            query="?top_k=abc",
            fields=[("name", "블루커피")],
            expect=both(422),
        ),
        Case(
            "G4",
            "top_k",
            "1.5",
            query="?top_k=1.5",
            fields=[("name", "블루커피")],
            expect=both(422),
        ),
        Case(
            "G5",
            "top_k",
            "두 번(5·6)",
            query="?top_k=5&top_k=6",
            fields=[("name", "블루커피")],
            expect=both(422),
        ),
        Case(
            "G6",
            "top_k",
            "20(경계)",
            query="?top_k=20",
            fields=[("name", "블루커피")],
            expect=both(200),
        ),
        Case(
            "G7",
            "top_k",
            "앞자리 0(05)",
            query="?top_k=05",
            fields=[("name", "블루커피")],
            expect=both(200),
        ),
    ]
    return cases


def _send(base: str, case: Case, key: str) -> dict:
    path = "/search/v2" if base == API else "/api/search/v2"
    headers = {"X-API-Key": key} if base == API else {"x-turnstile-token": f"ok-{uuid.uuid4()}"}
    url = f"{base}{path}{case.query}"
    started = time.perf_counter()
    try:
        if case.raw is not None:
            headers["Content-Type"] = case.content_type
            response = requests.request(
                case.method, url, data=case.raw, headers=headers, timeout=120
            )
        elif case.fields:
            files = []
            for name, value in case.fields:
                if isinstance(value, tuple):
                    filename, data, mime = value
                    files.append((name, (filename, data, mime) if mime else (filename, data)))
                else:
                    files.append((name, (None, value)))
            response = requests.request(case.method, url, files=files, headers=headers, timeout=120)
        else:
            response = requests.request(case.method, url, headers=headers, timeout=120)
    except requests.RequestException as exc:
        return {
            "status": None,
            "error": type(exc).__name__,
            "ms": round((time.perf_counter() - started) * 1000),
        }
    elapsed = time.perf_counter() - started
    text = response.text
    detail = None
    try:
        body = response.json()
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, list):
            detail = json.dumps(detail, ensure_ascii=False)[:300]
        overall = body.get("overall") if isinstance(body, dict) else None
    except ValueError:
        body, overall = None, None
    leaks = [p for p in LEAK_PATTERNS if re.search(p, text)]
    if key and key in text:
        leaks.append("API 키")
    out = {
        "status": response.status_code,
        "ms": round(elapsed * 1000),
        "bytes": len(response.content),
        "detail": detail if isinstance(detail, str) else None,
        "leaks": leaks,
        "slow": elapsed > SLOW_SECONDS,
        "content_type": response.headers.get("content-type"),
    }
    if isinstance(detail, str):
        out["korean"] = bool(re.search(r"[가-힣]", detail))
        out["tech_words"] = [p for p in TECH_WORDS if re.search(p, detail)]
    if overall:
        out["overall"] = {k: overall.get(k) for k in ("grade", "prob", "pattern")}
        out["caveats"] = overall.get("caveats")
        out["query_type"] = (overall.get("query_type") or {}).get("type")
        out["candidates"] = len(body.get("candidates") or [])
    return out


def verdict(case: Case, side: str, result: dict) -> str:
    if result.get("status") is None:
        return "연결 실패"
    if result["status"] >= 500:
        return "500대"
    if case.expect is None:
        return "계약 공백"
    expected = case.expect[side]
    expected = expected if isinstance(expected, (set, tuple, list)) else {expected}
    return "통과" if result["status"] in expected else "기대와 다름"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=default_out())
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    key = (args.out / "api_key").read_text(encoding="utf-8").strip()
    cases = [c for c in build_cases(args.out / "images") if c.cid.startswith(args.only)]
    rows = []
    for case in cases:
        api = _send(API, case, key)
        bff = _send(BFF, case, key)
        row = {
            "id": case.cid,
            "group": case.group,
            "title": case.title,
            "expect": case.expect,
            "gap": case.gap,
            "note": case.note,
            "api": api,
            "bff": bff,
            "verdict": {"api": verdict(case, "api", api), "bff": verdict(case, "bff", bff)},
        }
        rows.append(row)
        print(
            f"{case.cid:4} {case.title[:28]:28} API {api.get('status')} {api.get('ms')}ms "
            f"{row['verdict']['api']:6} | BFF {bff.get('status')} {bff.get('ms')}ms "
            f"{row['verdict']['bff']}",
            flush=True,
        )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "probe_api.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    lines = [
        "| ID | 입력 | 기대 | API(ms) | BFF(ms) | 판정 | BFF 문구 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        expect = (
            "계약 공백"
            if row["expect"] is None
            else f"{row['expect']['api']}/{row['expect']['bff']}"
        )
        detail = (row["bff"].get("detail") or "").replace("|", "\\|")[:80]
        lines.append(
            f"| {row['id']} | {row['title']} | {expect} | {row['api'].get('status')}"
            f"({row['api'].get('ms')}) | {row['bff'].get('status')}({row['bff'].get('ms')}) | "
            f"{row['verdict']['api']}·{row['verdict']['bff']} | {detail} |"
        )
    (args.out / "probe_api.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    bad = [
        r
        for r in rows
        if "기대와 다름" in r["verdict"].values() or "500대" in r["verdict"].values()
    ]
    print(f"\n{len(rows)}건 — 기대와 다름·500대 {len(bad)}건 → {args.out / 'probe_api.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
