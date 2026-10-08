"""심결문 PDF에서 양쪽 표장 이미지를 뽑아 X2(외관) 벤치마크용 이미지 쌍을 만든다. KIPRIS 호출 0.

실행 (프로젝트 루트에서):
    ml/venv/bin/python ml/scripts/trials_extract_images.py            # 추출 → 색인 → 쌍 → QA 시트
    ml/venv/bin/python ml/scripts/trials_extract_images.py --numbers 2014100002294 --no-qa
    ml/venv/bin/python ml/scripts/trials_extract_images.py --min-size 20   # 소형 기준 완화 실험

대상: labels.csv 에서 pass a(유사여부_확정)와 pass b(llm_b_유사여부)가 일치하고 둘 다 유사·비유사인
행의 심판번호(제외·불일치 행은 뺀다).

추출·연결(문서마다, backend/scripts/trials_collect.py 의 기초사실 제목·등록번호 패턴 재사용):
  1. 쪽마다 텍스트 줄(get_text("dict"))과 이미지(get_images(full=True) + get_image_rects)의 bbox 를
     읽어 읽기 순서(쪽, y, x)로 늘어놓는다.
  2. "1. 기초사실" 제목부터 다음 최상위 번호 제목("2. 당사자의 주장" 등) 앞까지를 표장 영역으로 본다
     (판단 절의 인라인 재사용 이미지는 여기서 걸러진다). 기초사실 제목이 없으면 문서 전체.
  3. 표장 제목 — "가. 이 사건 출원상표/등록상표(서비스표)", "나. 선등록상표 1"/"(2) 선등록상표",
     "나. 확인대상표장", "인용상표", "선출원상표", "선사용상표" — 를 만나면 블록을 연다.
     "나. 원결정 이유 및 선등록상표(들)" 은 묶음 제목이라 잠정 블록으로 두고 하위 "(2) 선등록상표 1"
     이 나오면 그것으로 바꾼다. 각 이미지는 읽기 순서상 직전 표장 제목에 연결한다.
  4. 제외: 같은 xref 가 전체 쪽의 절반 넘게 반복(머리말 로고·도장. 표장 이미지도 판단 절에서 2~4쪽
     재사용되므로 '여러 쪽'을 절반 초과로 잡는다), 폭 또는 높이가 --min-size(기본 40)px 미만(소형).
     한 표장에 이미지가 여럿이면 픽셀 면적이 가장 큰 것.
  5. 래스터 이미지가 없고 "(2) 구성:" 줄 아래에 벡터 그림(get_drawings)이 있으면 그 영역을 2배로
     clip 렌더해 저장하고 rendered=1. "구성:" 뒤에 글자만 있으면 "이미지 없음(문자)"(합성하지 않음).
  6. 연결 신뢰도: 제목과 이미지 사이에 다른 (가./1.) 제목이 끼거나, 거리가 멀면(같은 쪽 350pt 초과
     또는 두 쪽 이상 뒤) low, 아니면 high. "구성:" 줄 바로 옆의 이미지는 high.

저장: ml/data/trials/images/{심판번호}/{role}.png — role = this | prior_1, prior_2… |
      target(확인대상표장). ml/data/trials/image_index.csv (심판번호, role, 쪽, bbox, 폭, 높이,
      xref, 연결근거제목, 등록번호, rendered, 연결신뢰도, 경로, 사유, 사진추정).
쌍:   ml/data/trials/image_pairs.csv — labels.csv 행마다 this + 그 행의 상대 표장(상표B_번호 ↔ 색인
      등록번호, 없으면 순번 prior_N, 권리범위확인은 target). 양쪽 이미지가 있는 행만.
QA:   ml/data/trials/image_qa_sheet.png — seed 0 으로 30쌍(심판번호·this·상대·라벨·제목·신뢰도).
보고: image_coverage.json (대상 행 → 양쪽 확보 n, 종류·유형별, 이미지 없음 사유, target 사진 추정
      비율).
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ML_ROOT.parent
for _root in (ML_ROOT, PROJECT_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from backend.scripts.trials_collect import (  # noqa: E402
    _COUNTERPART_HEAD_RE,
    _REG_NUMBER_RE,
    _digits,
)

DEFAULT_BASE = ML_ROOT / "data" / "trials"
MIN_SIZE = 40
QA_ROWS = 30
ROLE_THIS = "this"
ROLE_TARGET = "target"
POSITIVE = ("유사", "비유사")
REPEAT_FRACTION = 0.5  # 전체 쪽의 절반 초과 반복 → 머리말 로고·도장
NEAR_GUSUNG_BELOW = 80.0  # "구성:" 줄 아래 이 거리(pt) 안의 이미지는 high
FAR_DISTANCE = 350.0  # 제목에서 이 거리(pt) 넘게 떨어지면 low
VECTOR_BAND = 150.0  # "구성:" 줄 아래 벡터 그림을 찾는 범위(pt)
RENDER_SCALE = 2.0

INDEX_COLUMNS = [
    "심판번호", "role", "쪽", "bbox", "폭", "높이", "xref", "연결근거제목", "등록번호",
    "rendered", "연결신뢰도", "경로", "사유", "사진추정",
]
PAIR_COLUMNS = [
    "심판번호", "종류", "상대번호", "라벨", "판단축", "상표유형", "상표유형_출처", "이미지A",
    "이미지B", "연결신뢰도", "rendered", "상대role", "매칭",
]

# 제목 줄: "(2)" / "(나)" / "가." / "1." 번호 뒤의 본문
_HEADING_LINE_RE = re.compile(
    r"^\s*(\(\s*\d+\s*\)|\(\s*[가-힣]\s*\)|[가-힣]\.|\d+\.(?!\s*\d))\s*(.*?)\s*$"
)
# 가./1. 제목(번호 제목은 글자로 시작해야 한다 — 날짜 이어쓰기 "2./1996. 2. 5." 는 제목이 아니다)
_LETTER_OR_NUMBER_HEAD_RE = re.compile(r"^\s*(?:[가-힣]\.\s*\S|\d+\.\s*[가-힣A-Za-z(\[])")
_FACTS_RE = re.compile(r"^\s*(\d+)\.\s*기\s*초\s*사\s*실")
_TOP_RE = re.compile(r"^\s*(\d+)\.\s*[가-힣A-Za-z(\[]")
# "(3) 확인대상표장의 사용 태양 :" 같은 번호 줄 아래 사진은 표장 구성이 아니다
_USAGE_RE = re.compile(r"사용\s*(?:태양|모습|실태|현황|사례|례)|사진|실\s*사용")
# 제목 꼬리: "들", 번호("선등록상표 2"), 각주 표시("등록서비스표1)"), 괄호·콜론·따옴표 뒤는 무시
_TRAIL = r"\s*들?\s*(\d*?)\s*(?:\d{1,2}\))?\s*(?:[(（:：“”‘’'\"].*)?$"
_MARK_WORD = r"(?:상표|서비스표|표장)(?:\s*/?\s*(?:서비스표|상표))?"  # "상표/서비스표"
_THIS_RE = re.compile(
    r"^이\s*사건\s*(?:국제\s*등록\s*출원|국제\s*출원|국제\s*등록|등록|출원)?\s*"
    + _MARK_WORD + _TRAIL
)
_PRIOR_RE = re.compile(
    r"^(원\s*결정\s*(?:의\s*)?(?:거절\s*)?이유\s*(?:및|와|과)\s*)?"
    r"(?:선\s*등록|선\s*사용|선\s*출원|인용|비교\s*대상)\s*(?:\(\s*(?:사용|등록)\s*\)\s*)?"
    + _MARK_WORD + _TRAIL
)
_TARGET_RE = re.compile(r"^확인\s*대상\s*표장" + _TRAIL)
# 묶음 제목("선등록상표들", "선등록서비스표들 및 선출원서비스표") — 하위 제목이 오면 그것으로 바꾼다
_CONTAINER_RE = re.compile(r"및|(?:상표|서비스표|표장)\s*들")
_JUDGMENT_WORD_RE = re.compile(r"여부|유사|해당|속하|사용되|주장|대비|비교\s*판단")
# "(2) 구성:" / "(나) 구 성 :" / "(2) 표 장 :" — 뒤에 글자가 오면 문자 표장
_GUSUNG_RE = re.compile(
    r"^\s*(?:\(\s*[\d가-힣]\s*\)|[\d가-힣]\))?\s*(?:구\s*성|표\s*장)\s*(?:[:：]\s*(.*))?$"
)
_REMARK_RE = re.compile(r"^\s*(?:\([^)]*\)\s*|\d{1,2}\)\s*)+")  # "(일반상표)", 각주 "2)"
_APP_NUMBER_RE = re.compile(r"출원\s*번호[^\n]{0,20}?제\s*([\d\-]+)\s*호")
_INLINE_TEXT_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")


@dataclass
class Line:
    page: int
    bbox: tuple[float, float, float, float]
    text: str


@dataclass
class ImageHit:
    page: int
    bbox: tuple[float, float, float, float]
    xref: int
    width: int
    height: int
    smask: int
    confidence: str


@dataclass
class MarkBlock:
    kind: str  # this | target | prior
    heading: str
    page: int
    y0: float
    y1: float
    provisional: bool = False  # 묶음 제목("선등록상표들") — 하위 제목이 이미지를 가져가면 버린다
    number_hint: str = ""  # 제목 안 번호("선등록상표 2")
    role: str = ""
    others: list[tuple[int, float]] = field(default_factory=list)  # 사이에 낀 다른 제목 (쪽, y0)
    cutoff: tuple[int, float] | None = None  # "사용 태양" 줄 — 이 아래 사진은 뺀다
    gusung: Line | None = None
    gusung_inline: str = ""
    text_after_gusung: str = ""
    images: list[ImageHit] = field(default_factory=list)
    small_seen: int = 0
    block_text: list[str] = field(default_factory=list)
    next_heading_y: float | None = None  # 같은 쪽의 다음 제목 위치(벡터 탐색 상한)

    @property
    def other_heading(self) -> bool:
        return bool(self.others)

    @property
    def number(self) -> str:
        text = "\n".join(self.block_text)
        for first, second in _REG_NUMBER_RE.findall(text):
            digits = _digits(first or second)
            if digits:
                return digits
        match = _APP_NUMBER_RE.search(text)
        return _digits(match.group(1)) if match else ""


def target_trials(label_rows: list[dict]) -> tuple[list[str], list[dict]]:
    """pass a·b 가 일치하고 둘 다 유사/비유사인 행과 그 심판번호(정렬)."""
    rows = [
        r for r in label_rows
        if r.get("유사여부_확정") in POSITIVE and r.get("유사여부_확정") == r.get("llm_b_유사여부")
    ]
    return sorted({r["심판번호"] for r in rows}), rows


def classify_heading(text: str) -> tuple[str, bool, str] | None:
    """제목 본문 → (종류 this|prior|target, 묶음 제목 여부, 제목 안 번호). 표장 제목 아니면 None."""
    body = text.strip()
    if not body:
        return None
    match = _THIS_RE.match(body)
    if match:
        return ROLE_THIS, False, match.group(1)
    match = _TARGET_RE.match(body)
    if match:
        return ROLE_TARGET, _CONTAINER_RE.search(body) is not None, match.group(1)
    match = _PRIOR_RE.match(body)
    if match:
        container = bool(match.group(1)) or _CONTAINER_RE.search(body) is not None
        return "prior", container, match.group(2)
    if _COUNTERPART_HEAD_RE.search(body) and not _JUDGMENT_WORD_RE.search(body) and len(body) <= 30:
        kind = ROLE_TARGET if "확인" in body else "prior"  # "선등록상표 등"처럼 꼬리가 붙은 제목
        return kind, _CONTAINER_RE.search(body) is not None, ""
    return None


def inline_text(value: str) -> str:
    """'구성:' 뒤 글자 — "(일반상표)"·각주 표시를 뺀 나머지. 비면 글자 없음."""
    rest = _REMARK_RE.sub("", value or "").strip()
    return rest if _INLINE_TEXT_RE.search(rest) else ""


def page_lines(page) -> list[Line]:
    """텍스트 줄. 같은 높이에 가까이 놓인 조각("(2) 구" + "성:" + "(일반상표)")은 한 줄로 합친다."""
    pieces: list[tuple[tuple[float, float, float, float], str]] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text:
                pieces.append((tuple(line["bbox"]), text))
    pieces.sort(key=lambda item: (item[0][1], item[0][0]))
    merged: list[tuple[list[float], str]] = []
    for bbox, text in pieces:
        if merged:
            previous_bbox, previous_text = merged[-1]
            same_height = abs(previous_bbox[1] - bbox[1]) < 4.0
            adjacent = -2.0 <= bbox[0] - previous_bbox[2] < 40.0
            if same_height and adjacent:
                previous_bbox[2] = max(previous_bbox[2], bbox[2])
                previous_bbox[3] = max(previous_bbox[3], bbox[3])
                merged[-1] = (previous_bbox, previous_text + " " + text)
                continue
        merged.append(([*bbox], text))
    return [Line(page.number, tuple(bbox), text) for bbox, text in merged]


def page_images(page) -> list[tuple[tuple[float, float, float, float], int, int, int, int]]:
    """(bbox, xref, 폭, 높이, smask) — 같은 xref 가 한 쪽에 여러 번 놓이면 각각."""
    found = []
    for item in page.get_images(full=True):
        xref, smask, width, height = item[0], item[1], item[2], item[3]
        for rect in page.get_image_rects(xref):
            found.append((tuple(rect), xref, int(width), int(height), int(smask)))
    return found


def repeated_xrefs(doc) -> set[int]:
    """머리말 로고·도장: 전체 쪽의 절반 넘게 나오면서 늘 같은 자리이거나, 표지(1쪽)에도 있거나,
    모든 쪽에 있는 이미지.

    표장 이미지도 짧은 문서에서는 판단 절의 인라인 재사용으로 절반 넘는 쪽에 나오지만, 자리가 매번
    다르고 표지에는 없다.
    """
    places: dict[int, list[tuple[int, tuple[int, int]]]] = {}
    for page in doc:
        for item in page.get_images(full=True):
            for rect in page.get_image_rects(item[0]):
                spot = (round(rect.x0 / 5), round(rect.y0 / 5))
                places.setdefault(item[0], []).append((page.number, spot))
    total = len(doc)
    if total < 2:
        return set()
    repeated: set[int] = set()
    for xref, found in places.items():
        pages = {page for page, _ in found}
        if len(pages) / total <= REPEAT_FRACTION:
            continue
        spots = {spot for _, spot in found}
        if 0 in pages or len(spots) == 1 or len(pages) == total:
            repeated.add(xref)
    return repeated


def _distance(block: MarkBlock, page_height: float, page: int, y0: float) -> float:
    if page == block.page:
        return y0 - block.y1
    if page == block.page + 1:
        return (page_height - block.y1) + y0
    return float("inf")


def _confidence(block: MarkBlock, page_height: float, page: int, bbox,
                center: tuple[int, float]) -> str:
    if any(other < center for other in block.others):
        return "low"  # 제목과 이미지 사이에 다른 제목이 끼었다
    if block.gusung and page == block.gusung.page:
        g0, g1 = block.gusung.bbox[1], block.gusung.bbox[3]
        if bbox[3] > g0 - 5 and bbox[1] < g1 + NEAR_GUSUNG_BELOW:
            return "high"
    return "high" if _distance(block, page_height, page, bbox[1]) <= FAR_DISTANCE else "low"


def _facts_start(all_lines: list[Line]) -> tuple[int, int] | None:
    """(줄 인덱스, 기초사실 번호)."""
    for index, line in enumerate(all_lines):
        match = _FACTS_RE.match(line.text)
        if match:
            return index, int(match.group(1))
    return None


def collect_blocks(doc, *, min_size: int = MIN_SIZE) -> list[MarkBlock]:
    """문서의 표장 영역을 읽기 순서로 훑어 표장 블록(제목·구성·이미지 후보)을 만든다.

    1) 줄을 훑어 블록(제목 위치·구성 줄·사이에 낀 다른 제목·사용 태양 컷오프)을 만든다.
    2) 이미지는 세로 중심이 속한 블록 구간[제목 y0, 다음 제목 y0)에 배정한다 — 표 레이아웃에서
       이미지 위쪽이 제목보다 위에 놓여도 맞는 블록에 간다.
    3) 묶음 제목은 이미지가 직접 붙은 경우만 남기고 역할 번호를 매긴다.
    """
    repeated = repeated_xrefs(doc)
    heights = [page.rect.height for page in doc]
    lines_by_page = {page.number: page_lines(page) for page in doc}
    images_by_page = {page.number: page_images(page) for page in doc}
    all_lines = [line for number in sorted(lines_by_page) for line in lines_by_page[number]]
    start = _facts_start(all_lines)
    if start is not None:
        first = all_lines[start[0]]
        begin, facts_number = (first.page, first.bbox[1]), start[1]
    else:
        begin, facts_number = (0, -1.0), 0
        for line in all_lines:  # 기초사실 제목이 없는 문서: 첫 표장 제목부터
            heading = _HEADING_LINE_RE.match(line.text)
            if heading and classify_heading(heading.group(2)):
                begin = (line.page, line.bbox[1])
                break

    blocks: list[MarkBlock] = []
    current: MarkBlock | None = None
    end: tuple[int, float] | None = None
    ordered = sorted(all_lines, key=lambda item: (item.page, item.bbox[1], item.bbox[0]))
    for line in ordered:
        position = (line.page, line.bbox[1])
        if position < begin:
            continue
        top = _TOP_RE.match(line.text)
        heading = _HEADING_LINE_RE.match(line.text)
        classified = classify_heading(heading.group(2)) if heading else None
        if top and classified is None and int(top.group(1)) > facts_number and position > begin:
            end = position
            break  # 표장 영역 끝(다음 최상위 제목 — 표장 제목이 아닌 것)
        if classified:
            kind, provisional, number = classified
            body = heading.group(2)
            current = MarkBlock(
                kind=kind, heading=line.text.strip(), page=line.page, y0=line.bbox[1],
                y1=line.bbox[3], provisional=provisional, number_hint=number,
            )
            current.gusung_inline = inline_text(body.split(":", 1)[1]) if ":" in body else ""
            current.block_text.append(line.text)
            blocks.append(current)
            continue
        if current is None:
            continue
        if (
            current.gusung is not None and current.cutoff is None and heading
            and _USAGE_RE.search(line.text)
        ):
            current.cutoff = position  # 이 아래 사진은 사용 태양이지 표장 구성이 아니다
            continue
        gusung = _GUSUNG_RE.match(line.text)
        if gusung and current.gusung is None:
            current.gusung = line
            current.gusung_inline = inline_text(gusung.group(1) or "")
            continue
        if _LETTER_OR_NUMBER_HEAD_RE.match(line.text):
            current.others.append(position)
            continue
        if (
            current.gusung is not None and not current.text_after_gusung
            and line.page == current.gusung.page and line.bbox[1] - current.gusung.bbox[3] < 30
            and not line.text.lstrip().startswith("(") and _INLINE_TEXT_RE.search(line.text)
        ):
            current.text_after_gusung = line.text
        if len(current.block_text) < 12:
            current.block_text.append(line.text)

    keys = [(block.page, block.y0) for block in blocks]
    last_page = end[0] if end is not None else len(doc) - 1
    for page in range(begin[0], last_page + 1):
        for bbox, xref, width, height, smask in images_by_page.get(page, []):
            center = (page, (bbox[1] + bbox[3]) / 2)
            if center < begin or (end is not None and center >= end):
                continue
            index = bisect.bisect_right(keys, center) - 1
            if index < 0:
                continue
            block = blocks[index]
            if block.cutoff is not None and center >= block.cutoff:
                continue
            if xref in repeated:
                continue
            if width < min_size or height < min_size:
                block.small_seen += 1
                continue
            confidence = _confidence(block, heights[page], page, bbox, center)
            block.images.append(ImageHit(page, bbox, xref, width, height, smask, confidence))

    kept: list[MarkBlock] = []
    prior_count = target_count = 0
    used: set[str] = set()
    for index, block in enumerate(blocks):
        following = blocks[index + 1] if index + 1 < len(blocks) else None
        parent_only = (  # "나. 확인대상표장" 바로 아래 "(1) 확인대상표장 1" — 위는 묶음 제목
            following is not None and following.kind == block.kind and not block.images
            and block.gusung is None and not block.small_seen
            and re.match(r"^\s*[가-힣]\.", block.heading)
            and following.heading.lstrip().startswith("(")
        )
        if (block.provisional or parent_only) and not block.images:
            continue  # 묶음 제목 — 하위 제목이 이미지를 가져갔다
        if block.kind == ROLE_THIS:
            role = ROLE_THIS
        elif block.kind == ROLE_TARGET:
            target_count += 1
            role = ROLE_TARGET if target_count == 1 else f"{ROLE_TARGET}_{target_count}"
        else:
            number = block.number_hint
            if number and not block.provisional and f"prior_{int(number)}" not in used:
                prior_count = max(prior_count, int(number))
                role = f"prior_{int(number)}"
            else:
                prior_count += 1
                role = f"prior_{prior_count}"
            while role in used:
                prior_count += 1
                role = f"prior_{prior_count}"
            used.add(role)
        block.role = role
        kept.append(block)
    heads = {(block.page, block.y0) for block in blocks}  # 버린 묶음 제목도 상한이 된다
    heads |= {other for block in blocks for other in block.others}
    if end is not None:
        heads.add(end)
    for block in kept:  # "구성:" 줄(없으면 제목) 아래 같은 쪽의 다음 제목 — 벡터 그림 탐색 상한
        anchor = (block.page, block.y1)
        if block.gusung is not None:
            anchor = (block.gusung.page, block.gusung.bbox[3])
        later = [y for page, y in heads if page == anchor[0] and y > anchor[1]]
        block.next_heading_y = min(later) if later else None
    return kept

def _save_pixmap(doc, hit: ImageHit, path: Path) -> None:
    import pymupdf

    pix = pymupdf.Pixmap(doc, hit.xref)
    if pix.n - pix.alpha >= 4:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    if hit.smask:
        try:
            mask = pymupdf.Pixmap(doc, hit.smask)
            if (mask.width, mask.height) == (pix.width, pix.height):
                pix = pymupdf.Pixmap(pix, mask)
        except Exception:  # noqa: BLE001 — 마스크가 깨진 PDF 는 원본만 저장
            pass
    pix.save(str(path))


def _vector_region(doc, block: MarkBlock):
    """'구성:' 줄 아래 벡터 그림의 합집합 영역(없으면 None)."""
    import pymupdf

    if block.gusung is None:
        return None
    page = doc[block.gusung.page]
    g0, g1 = block.gusung.bbox[1], block.gusung.bbox[3]
    limit = g1 + VECTOR_BAND
    if block.next_heading_y is not None and block.next_heading_y > g1:
        limit = min(limit, block.next_heading_y)
    union = None
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.y0 < g0 - 5 or rect.y0 > limit:
            continue
        if rect.height < 3 or rect.width < 3 or rect.width > page.rect.width * 0.8:
            continue  # 밑줄·표 괘선·쪽 테두리
        union = rect if union is None else union | rect
    if union is None or union.width < 15 or union.height < 8:
        return None
    return pymupdf.Rect(union.x0 - 2, union.y0 - 2, union.x1 + 2, union.y1 + 2)


def _photo_like(path: Path) -> int:
    """실사용 사진으로 보이는지 추정(색 수·중간 톤 비율). 선화·문자 표장은 0."""
    from PIL import Image

    with Image.open(path) as image:
        probe = image.convert("RGB")
        probe.thumbnail((64, 64))
        pixels = list(probe.getdata())
    if not pixels:
        return 0
    unique = len(set(pixels)) / len(pixels)
    midtone = sum(1 for r, g, b in pixels if 20 < min(r, g, b) and max(r, g, b) < 235) / len(pixels)
    return 1 if unique > 0.3 and midtone > 0.45 else 0


def _bbox_text(bbox) -> str:
    return ",".join(f"{value:.1f}" for value in bbox)


def extract_document(pdf_path: Path, out_dir: Path, *, min_size: int = MIN_SIZE) -> list[dict]:
    """PDF 한 건 → 색인 행(role 마다 한 줄. 이미지가 없는 표장도 사유와 함께 남긴다)."""
    import pymupdf

    number = pdf_path.stem
    rows: list[dict] = []
    with pymupdf.open(pdf_path) as doc:
        blocks = collect_blocks(doc, min_size=min_size)
        best_by_role: dict[str, dict] = {}
        for block in blocks:
            row = {
                "심판번호": number, "role": block.role, "쪽": "", "bbox": "", "폭": "", "높이": "",
                "xref": "", "연결근거제목": block.heading, "등록번호": block.number, "rendered": 0,
                "연결신뢰도": "", "경로": "", "사유": "", "사진추정": "",
            }
            if block.images:
                hit = max(block.images, key=lambda item: (item.width * item.height, -item.page))
                target_dir = out_dir / number
                target_dir.mkdir(parents=True, exist_ok=True)
                path = target_dir / f"{block.role}.png"
                try:
                    _save_pixmap(doc, hit, path)
                except Exception:  # noqa: BLE001 — 디코드 실패 시 쪽에서 잘라 렌더
                    clip = pymupdf.Rect(*hit.bbox)
                    doc[hit.page].get_pixmap(
                        matrix=pymupdf.Matrix(RENDER_SCALE, RENDER_SCALE), clip=clip
                    ).save(str(path))
                    row["rendered"] = 1
                row.update({
                    "쪽": hit.page + 1, "bbox": _bbox_text(hit.bbox), "폭": hit.width,
                    "높이": hit.height, "xref": hit.xref, "연결신뢰도": hit.confidence,
                    "경로": str(path.relative_to(out_dir.parent)), "사진추정": _photo_like(path),
                })
            else:
                # 래스터 이미지가 아예 없을 때만 벡터 그림을 찾는다(소형 래스터가 있던 표장은 소형)
                region = _vector_region(doc, block) if not block.small_seen else None
                if region is not None:
                    target_dir = out_dir / number
                    target_dir.mkdir(parents=True, exist_ok=True)
                    path = target_dir / f"{block.role}.png"
                    pix = doc[block.gusung.page].get_pixmap(
                        matrix=pymupdf.Matrix(RENDER_SCALE, RENDER_SCALE), clip=region
                    )
                    pix.save(str(path))
                    row.update({
                        "쪽": block.gusung.page + 1, "bbox": _bbox_text(tuple(region)),
                        "폭": pix.width, "높이": pix.height, "rendered": 1,
                        "연결신뢰도": "low" if block.other_heading else "high",
                        "경로": str(path.relative_to(out_dir.parent)), "사진추정": 0,
                    })
                elif block.gusung_inline or block.text_after_gusung:
                    row["사유"] = "문자"
                elif block.small_seen:
                    row["사유"] = "소형"
                else:
                    row["사유"] = "연결 실패"
            previous = best_by_role.get(block.role)
            if previous is None or _better(row, previous):
                best_by_role[block.role] = row
        rows.extend(best_by_role.values())
    return rows


def _better(candidate: dict, previous: dict) -> bool:
    def key(row: dict) -> tuple[int, int, int]:
        has_image = 1 if row["경로"] else 0
        confident = 1 if row["연결신뢰도"] == "high" else 0
        area = int(row["폭"] or 0) * int(row["높이"] or 0)
        return (has_image, confident, area)

    return key(candidate) > key(previous)


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_pairs(label_rows: list[dict], index_rows: list[dict]) -> tuple[list[dict], Counter]:
    """labels.csv 행 → (this, 상대 표장) 이미지 쌍. 양쪽 이미지가 있는 행만. (쌍, 탈락 집계)."""
    by_trial: dict[str, dict[str, dict]] = {}
    for row in index_rows:
        by_trial.setdefault(row["심판번호"], {})[row["role"]] = row
    order_in_trial: Counter = Counter()
    pairs: list[dict] = []
    dropped: Counter = Counter()
    for row in label_rows:
        number = row["심판번호"]
        order_in_trial[number] += 1
        roles = by_trial.get(number, {})
        this = roles.get(ROLE_THIS)
        counterpart, matched = _match_counterpart(row, roles, order_in_trial[number])
        if this is None or not this.get("경로"):
            dropped["this " + (this["사유"] if this and this.get("사유") else "연결 실패")] += 1
            continue
        if counterpart is None:
            dropped["상대 연결 실패"] += 1
            continue
        if not counterpart.get("경로"):
            dropped["상대 " + (counterpart.get("사유") or "연결 실패")] += 1
            continue
        mark_type, source = row.get("상표유형_확정") or "", "확정"
        if not mark_type:
            mark_type, source = row.get("상표유형_추정") or "", "추정"
        confidence = "high" if "high" == this["연결신뢰도"] == counterpart["연결신뢰도"] else "low"
        rendered = 1 if int(this["rendered"] or 0) or int(counterpart["rendered"] or 0) else 0
        pairs.append({
            "심판번호": number, "종류": row.get("종류", ""), "상대번호": row.get("상표B_번호", ""),
            "라벨": row["유사여부_확정"], "판단축": row.get("판단축_확정", ""),
            "상표유형": mark_type,
            "상표유형_출처": source if mark_type else "", "이미지A": this["경로"],
            "이미지B": counterpart["경로"], "연결신뢰도": confidence, "rendered": rendered,
            "상대role": counterpart["role"], "매칭": matched,
        })
    return pairs, dropped


def _match_counterpart(row: dict, roles: dict[str, dict], ordinal: int) -> tuple[dict | None, str]:
    if row.get("종류", "").startswith("권리범위확인"):
        return roles.get(ROLE_TARGET), ROLE_TARGET
    priors = {role: item for role, item in roles.items() if role.startswith("prior_")}
    wanted = _digits(row.get("상표B_번호") or "")
    if wanted:
        for item in priors.values():
            if item.get("등록번호") and _digits(item["등록번호"]) == wanted:
                return item, "번호"
    by_order = priors.get(f"prior_{ordinal}")
    if by_order is not None:
        return by_order, "순번"
    if ordinal == 1 and len(priors) == 1:
        return next(iter(priors.values())), "순번"
    return None, ""


def coverage(label_rows: list[dict], index_rows: list[dict], pairs: list[dict],
             dropped: Counter) -> dict:
    trials = sorted({row["심판번호"] for row in label_rows})
    by_role_reason: Counter = Counter()
    for row in index_rows:
        if not row.get("경로"):
            by_role_reason[f"{row['role']}: {row['사유']}"] += 1
    index_by_trial: dict[str, set[str]] = {}
    for row in index_rows:
        index_by_trial.setdefault(row["심판번호"], set()).add(row["role"])
    targets = [r for r in index_rows if r["role"] == ROLE_TARGET and r.get("경로")]
    photo = sum(int(r["사진추정"] or 0) for r in targets)
    return {
        "대상_행": len(label_rows),
        "대상_심판번호": len(trials),
        "이미지_확보_쌍": len(pairs),
        "쌍_종류별": dict(Counter(p["종류"] for p in pairs)),
        "쌍_유형별": dict(Counter(p["상표유형"] or "(없음)" for p in pairs)),
        "쌍_라벨별": dict(Counter(p["라벨"] for p in pairs)),
        "쌍_신뢰도": dict(Counter(p["연결신뢰도"] for p in pairs)),
        "쌍_매칭": dict(Counter(p["매칭"] for p in pairs)),
        "쌍_rendered": sum(int(p["rendered"]) for p in pairs),
        "탈락_사유": dict(dropped),
        "색인_이미지없음_사유": dict(by_role_reason),
        "색인_행": len(index_rows),
        "this_없는_심판번호": sum(
            1 for t in trials if ROLE_THIS not in index_by_trial.get(t, set())
        ),
        "target_이미지": len(targets),
        "target_사진추정": photo,
        "target_사진추정_비율": round(photo / len(targets), 3) if targets else None,
    }


def _font(size: int):
    from PIL import ImageFont

    for candidate in (
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ):
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def render_qa_sheet(pairs: list[dict], index_rows: list[dict], base: Path, out: Path, *,
                    n: int = QA_ROWS, seed: int = 0) -> list[dict]:
    """seed 로 n 쌍을 뽑아 [심판번호 | this | 상대 | 라벨 | 연결 근거 제목 | 신뢰도] 한 장 PNG."""
    from PIL import Image, ImageDraw

    sample = random.Random(seed).sample(pairs, min(n, len(pairs)))
    chosen = sorted(sample, key=lambda p: p["심판번호"])
    headings = {(r["심판번호"], r["role"]): r["연결근거제목"] for r in index_rows}
    row_h, thumb_w, thumb_h = 150, 200, 130
    cols = [110, thumb_w + 10, thumb_w + 10, 70, 300, 60]
    width = sum(cols) + 20
    sheet = Image.new("RGB", (width, 40 + row_h * max(1, len(chosen))), "white")
    draw = ImageDraw.Draw(sheet)
    font, small = _font(14), _font(12)
    x = 10
    for title, w in zip(("심판번호", "this", "상대", "라벨", "연결 근거 제목", "신뢰도"), cols):
        draw.text((x, 12), title, fill="black", font=font)
        x += w
    for i, pair in enumerate(chosen):
        y = 40 + i * row_h
        draw.line((0, y, width, y), fill=(200, 200, 200))
        x = 10
        draw.text((x, y + 8), pair["심판번호"], fill="black", font=small)
        draw.text((x, y + 28), pair["종류"][:8], fill=(90, 90, 90), font=small)
        x += cols[0]
        for key in ("이미지A", "이미지B"):
            path = base / pair[key]
            try:
                with Image.open(path) as image:
                    thumb = image.convert("RGB")
                    thumb.thumbnail((thumb_w, thumb_h))
                    sheet.paste(thumb, (x, y + 10))
            except OSError:
                draw.text((x, y + 10), "(열기 실패)", fill="red", font=small)
            x += thumb_w + 10
        draw.text((x, y + 8), pair["라벨"], fill="black", font=font)
        x += cols[3]
        this_head = headings.get((pair["심판번호"], ROLE_THIS), "")
        other_head = headings.get((pair["심판번호"], pair["상대role"]), "")
        draw.text((x, y + 8), f"A: {this_head[:34]}", fill="black", font=small)
        draw.text((x, y + 28), f"B: {other_head[:34]}", fill="black", font=small)
        note = f"{pair['상대role']} · {pair['매칭']} · {pair['상표유형']}"
        draw.text((x, y + 48), note, fill=(90, 90, 90), font=small)
        x += cols[4]
        draw.text((x, y + 8), pair["연결신뢰도"], fill="black", font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return chosen


def run(base: Path, *, numbers: list[str] | None = None, min_size: int = MIN_SIZE,
        qa: bool = True, qa_n: int = QA_ROWS, seed: int = 0) -> dict:
    labels = read_csv(base / "labels.csv")
    trials, rows = target_trials(labels)
    if numbers:
        wanted = set(numbers)
        trials = [t for t in trials if t in wanted]
        rows = [r for r in rows if r["심판번호"] in wanted]
    out_dir = base / "images"
    index_rows: list[dict] = []
    missing_pdf = 0
    for number in trials:
        pdf_path = base / "pdf" / f"{number}.pdf"
        if not pdf_path.exists():
            missing_pdf += 1
            continue
        index_rows.extend(extract_document(pdf_path, out_dir, min_size=min_size))
    write_csv(base / "image_index.csv", INDEX_COLUMNS, index_rows)
    pairs, dropped = build_pairs(rows, index_rows)
    write_csv(base / "image_pairs.csv", PAIR_COLUMNS, pairs)
    report = coverage(rows, index_rows, pairs, dropped)
    report["PDF_없음"] = missing_pdf
    report["min_size"] = min_size
    if qa and pairs:
        sheet = base / "image_qa_sheet.png"
        chosen = render_qa_sheet(pairs, index_rows, base, sheet, n=qa_n, seed=seed)
        report["QA_시트"] = {"경로": str(sheet), "쌍": len(chosen), "seed": seed}
    (base / "image_coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE, help="ml/data/trials")
    parser.add_argument("--numbers", nargs="*", help="이 심판번호만 (기본: 대상 전부)")
    parser.add_argument("--min-size", type=int, default=MIN_SIZE, help="폭·높이 하한 px (기본 40)")
    parser.add_argument("--no-qa", action="store_true", help="QA 시트 생략")
    parser.add_argument("--qa-n", type=int, default=QA_ROWS)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    report = run(args.base, numbers=args.numbers, min_size=args.min_size, qa=not args.no_qa,
                 qa_n=args.qa_n, seed=args.seed)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
