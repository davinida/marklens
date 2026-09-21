"""상품↔유사군 변환표 로더 — 상품명·원 명칭(aliases) 검색과 유사군 코드 조회.

X4 상품 견련성(x4_goods.goods_similarity)의 입력인 유사군 코드 집합을 상품명에서 얻는 진입점이고,
프론트-6 지정상품 검색 API(backend GET /goods/search, /goods/classes)의 데이터 소스다.
변환표는 shared/goods_map/parse_goods_map.py 가 만든 goods_map.json(.gz) 이며 스키마는
shared/types/goods.ts 의 GoodsMapEntry 와 같다(제35류 6종 병합 항목만 aliases 보유).

- 경로: 인자 > 환경변수 MARKLENS_GOODS_MAP_PATH > shared/goods_map/goods_map.json.gz > .json.
  없으면 FileNotFoundError(찾아본 위치 포함). 적재는 functools.lru_cache 로 경로당 1회.
- 매칭 정규화: NFKC → casefold → 연속 공백 1칸. 검색 순위는 정확 일치 > 접두 > 부분이고,
  같은 순위 안에서는 name 일치가 alias 일치보다 앞, 그다음 name 이 짧은 순 → 가나다 순.
- 부분 일치는 문자열 322,189개(name 91,591 + alias 230,598)를 "\\x00" 으로 이어붙인 하나의
  str 에서 str.find 로 찾는다(C 속도). 항목당 1번만 세도록 같은 항목의 alias 블록은 첫 적중
  후 건너뛴다 — 한 항목의 aliases 는 같은 base 상품명에 접미사만 다르므로 첫 적중이 가장
  좋은 순위다.
- 표준 라이브러리만 사용. torch·faiss·backend 를 import 하지 않는다.
"""

from __future__ import annotations

import gzip
import json
import os
import unicodedata
from array import array
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DIR = REPO_ROOT / "shared" / "goods_map"
DEFAULT_CANDIDATES: tuple[Path, ...] = (
    DEFAULT_DIR / "goods_map.json.gz",
    DEFAULT_DIR / "goods_map.json",
)
ENV_PATH = "MARKLENS_GOODS_MAP_PATH"

# 변환표 원본 판 표기. 파일 안에 판 정보가 없어 상수로 둔다 — 14판으로 바꾸면 여기와
# shared/goods_map/README.md 를 같이 고친다.
SOURCE_LABEL = "고시상품명칭 13판(2026)"

# NICE 국제상품분류 45개 류의 요약 명칭(지식재산처 류 제목을 화면용으로 줄인 것).
NICE_CLASS_TITLES: dict[int, str] = {
    1: "화학제품",
    2: "페인트·도료",
    3: "화장품·세제",
    4: "연료·공업용 유지",
    5: "약제·의료용품",
    6: "금속·금속제품",
    7: "기계·동력공구",
    8: "수동공구·칼붙이",
    9: "전기전자·과학기기·소프트웨어",
    10: "의료기기",
    11: "조명·난방·조리·위생기기",
    12: "운송기계·차량",
    13: "화기·폭약",
    14: "귀금속·보석·시계",
    15: "악기",
    16: "종이·인쇄물·사무용품",
    17: "고무·플라스틱·절연재",
    18: "가죽제품·가방·우산",
    19: "비금속 건축재료",
    20: "가구·거울·액자",
    21: "주방용품·유리·도자기",
    22: "로프·텐트·섬유원료",
    23: "실",
    24: "직물·침구·커튼",
    25: "의류·신발·모자",
    26: "레이스·자수·단추·장식품",
    27: "카펫·매트·벽지",
    28: "완구·운동용품",
    29: "육류·가공식품·유제품",
    30: "커피·과자·빵·조미료",
    31: "농수산물·종자·사료",
    32: "맥주·비알코올 음료",
    33: "알코올 음료(맥주 제외)",
    34: "담배·흡연용품",
    35: "광고·사업관리·도소매업",
    36: "금융·보험·부동산업",
    37: "건설·수리·설치업",
    38: "통신업",
    39: "운송·여행·보관업",
    40: "재료처리·가공업",
    41: "교육·오락·스포츠·문화업",
    42: "과학기술·연구·IT 서비스업",
    43: "음식·숙박업",
    44: "의료·미용·농업 서비스업",
    45: "법률·보안·개인 서비스업",
}

_SEP = "\x00"

TIER_EXACT, TIER_PREFIX, TIER_PARTIAL = 0, 1, 2


def normalize(text: str) -> str:
    """매칭용 정규화: NFKC → casefold → 연속 공백 1칸. 구분자 문자는 공백으로 바꾼다."""
    folded = unicodedata.normalize("NFKC", text).casefold().replace(_SEP, " ")
    return " ".join(folded.split())


@dataclass(frozen=True, slots=True)
class GoodsEntry:
    """변환표 1행 (shared/types/goods.ts GoodsMapEntry 와 같은 필드)."""

    name: str
    nice_class: int
    similarity_codes: tuple[str, ...]
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Match:
    """검색 결과 1건. matched_alias 는 name 이 아니라 alias(원 명칭)로 잡혔을 때 그 alias."""

    name: str
    nice_class: int
    similarity_codes: tuple[str, ...]
    matched_alias: str | None
    tier: int  # TIER_EXACT / TIER_PREFIX / TIER_PARTIAL (정렬·디버깅용)


class _TextIndex:
    """문자열 목록을 구분자로 이어붙인 하나의 str 과 오프셋 표.

    str.find 로 부분 일치를 C 속도로 찾고, 적중 위치를 이진 탐색으로 문자열 번호에 대응시킨다.
    같은 항목(entry)의 문자열이 연속해 있다는 전제로, 적중 후에는 그 항목 블록 끝으로 건너뛰어
    항목당 최대 1번만 낸다.
    """

    __slots__ = ("text", "starts", "ends", "entry_of", "block_end")

    def __init__(self, strings: list[str], entry_of: list[int]) -> None:
        # 오프셋 표는 array('I')(4바이트 정수)로 둔다 — list[int] 는 32만 개 × 4개 표에서 약 40MB 를
        # 먹는다(2026-09-21 실측).
        # bisect 대상(starts)만 list 로 둔다 — array 는 비교마다 int 객체를 만들어 2배 느리다.
        starts: list[int] = []
        ends = array("I")
        position = 1  # text[0] 이 구분자
        for value in strings:
            starts.append(position)
            ends.append(position + len(value))
            position += len(value) + 1
        self.text = _SEP + _SEP.join(strings) + _SEP
        self.starts = starts
        self.ends = ends
        self.entry_of = array("I", entry_of)
        block_end = array("I", bytes(4 * len(strings)))
        for index in range(len(strings) - 1, -1, -1):
            last_of_block = index == len(strings) - 1 or entry_of[index + 1] != entry_of[index]
            block_end[index] = ends[index] if last_of_block else block_end[index + 1]
        self.block_end = block_end

    def scan(self, query: str) -> Iterator[tuple[int, int, int]]:
        """query 를 포함하는 문자열을 항목당 1개씩 (항목 번호, 문자열 번호, tier) 로 낸다."""
        text, starts, ends = self.text, self.starts, self.ends
        length = len(query)
        position = text.find(query, 1)
        while position != -1:
            index = bisect_right(starts, position) - 1
            start, end = starts[index], ends[index]
            if position == start:
                tier = TIER_EXACT if start + length == end else TIER_PREFIX
            else:
                tier = TIER_PARTIAL
            yield self.entry_of[index], index, tier
            position = text.find(query, self.block_end[index])

    def exact(self, query: str) -> Iterator[int]:
        """query 와 정확히 같은 문자열의 번호를 낸다."""
        needle = _SEP + query + _SEP
        position = self.text.find(needle)
        while position != -1:
            yield bisect_right(self.starts, position + 1) - 1
            position = self.text.find(needle, position + 1)


class GoodsMap:
    """적재된 변환표. 검색(search)·유사군 조회(codes_for)·류별 건수(classes)를 제공한다."""

    def __init__(self, entries: Iterable[GoodsEntry], path: Path | None = None) -> None:
        self.entries: tuple[GoodsEntry, ...] = tuple(entries)
        self.path = path
        names = [normalize(entry.name) for entry in self.entries]
        self._names = _TextIndex(names, list(range(len(self.entries))))
        alias_texts: list[str] = []
        alias_entry: list[int] = []
        alias_original: list[str] = []
        for index, entry in enumerate(self.entries):
            for alias in entry.aliases:
                alias_texts.append(normalize(alias))
                alias_entry.append(index)
                alias_original.append(alias)
        self._aliases = _TextIndex(alias_texts, alias_entry)
        self._alias_original = alias_original
        counts: dict[int, int] = {}
        for entry in self.entries:
            counts[entry.nice_class] = counts.get(entry.nice_class, 0) + 1
        self._class_counts = counts
        # 같은 순위 안의 정렬 기준(name 짧은 순 → 가나다 순)을 항목별 순위 번호로 미리 계산해
        # 검색 때 sort key 를 싸게 만든다(부분 일치 5만 건짜리 질의에서 체감됨).
        by_name = sorted(
            range(len(self.entries)),
            key=lambda i: (len(self.entries[i].name), self.entries[i].name),
        )
        order = array("I", bytes(4 * len(self.entries)))
        for rank, index in enumerate(by_name):
            order[index] = rank
        self._order = order

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def alias_count(self) -> int:
        return len(self._alias_original)

    def codes_for(self, name: str, nice_class: int | None = None) -> frozenset[str]:
        """name 또는 alias 와 정확히 일치하는 항목의 유사군 코드.

        같은 이름이 여러 류에 있으면 nice_class 로 좁히고, 안 주면 합집합. 없으면 빈 집합.
        """
        query = normalize(name)
        if not query:
            return frozenset()
        indexes = [self._names.entry_of[i] for i in self._names.exact(query)]
        indexes += [self._aliases.entry_of[i] for i in self._aliases.exact(query)]
        codes: set[str] = set()
        for index in indexes:
            entry = self.entries[index]
            if nice_class is None or entry.nice_class == nice_class:
                codes.update(entry.similarity_codes)
        return frozenset(codes)

    def _ranked(
        self, needle: str, nice_class: int | None
    ) -> list[tuple[int, int, int, str | None]]:
        """(항목 번호, tier, alias 로 잡혔는지 0/1, alias 원문) 을 순위대로."""
        entries = self.entries
        best: dict[int, tuple[int, int, str | None]] = {}
        for entry_index, _string_index, tier in self._names.scan(needle):
            if nice_class is None or entries[entry_index].nice_class == nice_class:
                best[entry_index] = (tier, 0, None)
        for entry_index, string_index, tier in self._aliases.scan(needle):
            if nice_class is not None and entries[entry_index].nice_class != nice_class:
                continue
            current = best.get(entry_index)
            if current is None or tier < current[0]:
                best[entry_index] = (tier, 1, self._alias_original[string_index])
        order = self._order
        return sorted(
            ((index, tier, via, alias) for index, (tier, via, alias) in best.items()),
            key=lambda item: (item[1], item[2], order[item[0]]),
        )

    def search_with_total(
        self, query: str, limit: int = 20, nice_class: int | None = None
    ) -> tuple[list[Match], int]:
        """search() 와 같되 전체 일치 건수(total)도 돌려준다 — API 응답의 total 용."""
        needle = normalize(query)
        if not needle:
            return [], 0
        ranked = self._ranked(needle, nice_class)
        matches = [
            Match(
                name=self.entries[index].name,
                nice_class=self.entries[index].nice_class,
                similarity_codes=self.entries[index].similarity_codes,
                matched_alias=alias,
                tier=tier,
            )
            for index, tier, _via, alias in ranked[: max(limit, 0)]
        ]
        return matches, len(ranked)

    def search(self, query: str, limit: int = 20, nice_class: int | None = None) -> list[Match]:
        """name·aliases 부분 일치 상위 limit 개 (정확 > 접두 > 부분)."""
        return self.search_with_total(query, limit, nice_class)[0]

    def classes(self) -> list[dict[str, int]]:
        """45개 류 전부의 항목 수 (없는 류는 0)."""
        return [
            {"nice_class": nice_class, "count": self._class_counts.get(nice_class, 0)}
            for nice_class in sorted(NICE_CLASS_TITLES)
        ]


def _to_entry(record: dict) -> GoodsEntry:
    aliases = record.get("aliases") or ()
    return GoodsEntry(
        name=str(record["name"]),
        nice_class=int(record["nice_class"]),
        similarity_codes=tuple(str(code) for code in record["similarity_codes"]),
        aliases=tuple(str(alias) for alias in aliases),
    )


def _read_records(path: Path) -> list[dict]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            data = json.load(handle)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"변환표 최상위는 배열이어야 합니다: {path}")
    return data


def resolve_path(path: str | os.PathLike[str] | None = None) -> Path:
    """인자 > MARKLENS_GOODS_MAP_PATH > 기본 .json.gz > .json 순으로 존재하는 파일을 고른다."""
    if path:
        candidates = [Path(path)]
    else:
        env_value = os.environ.get(ENV_PATH, "").strip()
        candidates = [Path(env_value)] if env_value else list(DEFAULT_CANDIDATES)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(
        f"상품↔유사군 변환표 파일을 찾지 못했습니다. 찾아본 위치: {searched}. "
        "shared/goods_map/README.md 절차로 goods_map.json(.gz) 을 만들거나 "
        f"{ENV_PATH} 로 경로를 지정하세요."
    )


@lru_cache(maxsize=4)
def _load_cached(path_text: str) -> GoodsMap:
    path = Path(path_text)
    return GoodsMap((_to_entry(record) for record in _read_records(path)), path=path)


def load_goods_map(path: str | os.PathLike[str] | None = None) -> GoodsMap:
    """변환표를 적재한다(경로당 1회 캐시). 파일이 없으면 FileNotFoundError."""
    return _load_cached(str(resolve_path(path).resolve()))
