"""문서의 범위 표기 검사 — 숫자 사이 물결표를 쓰지 않는다(범위는 en dash –).

GitHub(GFM)는 물결표 한 쌍 사이를 취소선으로 그린다: "0.61~0.83 … 0.5~0.7" 이면
두 물결표 사이 글이 <del> 이 된다. 범위는 0.61–0.83 · 10/26–28 · E-1–E-6 처럼 쓴다.
코드 블록·인라인 코드 안은 실제 문자열(오류 문구·데이터 값)이라 보지 않는다. 네트워크 없음.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC_PATTERNS = ("README.md", "docs/**/*.md", "shared/**/README.md")
# 숫자 바로 뒤 물결표 + (접두 글자·부호 하나씩 선택) 숫자: 0.61~0.83 · −0.1~+0.2 · E-1~E-6 · v1~v1.2
RANGE_TILDE = re.compile(r"(?<=\d)~(?=[A-Za-z§#]?[+\-−]?\d)")
FENCE = re.compile(r"(`{3,}|~{3,})")
# 인라인 코드는 블록 안에서만 짝을 찾는다 — 표 행·제목은 한 줄이 한 블록, 목록 항목·HTML 은 새 블록
LINE_BLOCK = re.compile(r"\s*(\||#{1,6}\s)")
BLOCK_START = re.compile(r"\s*([-*+]\s|\d+[.)]\s|<)")


def doc_files() -> list[Path]:
    files: set[Path] = set()
    for pattern in DOC_PATTERNS:
        files.update(ROOT.glob(pattern))
    return sorted(files)


def mask_code(text: str) -> str:
    """울타리 코드 블록과 인라인 코드(줄을 넘는 것 포함)를 공백으로 바꾼 글. 줄 위치는 그대로."""
    out = list(text)

    def blank(start: int, end: int) -> None:
        for i in range(start, end):
            if out[i] != "\n":
                out[i] = " "

    blocks: list[tuple[int, int]] = []
    cur: tuple[int, int] | None = None
    fence: str | None = None
    pos, prev_quote = 0, False
    for line in text.split("\n"):
        start, end = pos, pos + len(line)
        pos = end + 1
        stripped = line.lstrip()
        m = FENCE.match(stripped)
        if fence is not None:
            blank(start, end)
            closing = m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)
            if closing and stripped.rstrip() == m.group(1):
                fence = None
            continue
        quote = stripped.startswith(">")
        single = bool(LINE_BLOCK.match(line))
        new_quote = quote and not prev_quote
        if cur and (m or not stripped or single or BLOCK_START.match(line) or new_quote):
            blocks.append(cur)
            cur = None
        prev_quote = quote
        if m:
            fence = m.group(1)
            blank(start, end)
        elif single:
            blocks.append((start, end))
        elif stripped:
            cur = (cur[0] if cur else start, end)
    if cur:
        blocks.append(cur)
    for b_start, b_end in blocks:
        runs = [(r.start() + b_start, r.end() + b_start)
                for r in re.finditer(r"`+", text[b_start:b_end])]
        k = 0
        while k < len(runs):
            s, e = runs[k]
            for j in range(k + 1, len(runs)):
                if runs[j][1] - runs[j][0] == e - s:
                    blank(s, runs[j][1])
                    k = j + 1
                    break
            else:
                k += 1
    return "".join(out)


def range_tildes(text: str) -> list[tuple[int, int]]:
    """코드 밖 숫자 사이 물결표 — (줄 번호, 글 안 위치) 목록."""
    return [(text.count("\n", 0, m.start()) + 1, m.start())
            for m in RANGE_TILDE.finditer(mask_code(text))]


def test_range_tilde_detector_skips_code_and_non_ranges():
    sample = (
        "AUC 0.61~0.83 · CI −0.12~+0.05 · E-1~E-6 · v1~v1.2\n"
        "\n"
        '여유 ~4.5GB · 사본 ~/marklens-archive · "~네" · (9월~) · 0.61–0.83\n'
        "`top_k 는 1~20` 과 `줄을 넘는\n"
        "코드 3~4초` 는 코드\n"
        "## 제목 `3~4`\n"
        "```bash\n# 3~4초\n```\n"
        "~~~\n0~1\n~~~\n"
        "| 0.5~0.7 | `1~2` |\n"
    )
    hits = [(line, sample[i - 1:i + 2]) for line, i in range_tildes(sample)]
    assert hits == [(1, "1~0"), (1, "2~+"), (1, "1~E"), (1, "1~v"), (13, "5~0")]


def test_docs_have_no_tilde_between_numbers():
    files = doc_files()
    assert ROOT / "README.md" in files and len(files) > 10
    found = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        found += [f"{path.relative_to(ROOT)}:{line}: …{text[max(0, i - 12):i + 13]}…"
                  for line, i in range_tildes(text)]
    assert not found, (
        "숫자 사이 물결표는 GitHub 에서 취소선 짝이 됩니다 — 범위는 en dash(–)로 쓰세요"
        f"(코드 안은 예외). {len(found)}곳:\n" + "\n".join(found[:30])
    )
