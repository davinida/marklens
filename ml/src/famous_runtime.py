"""유명 상표 확인의 런타임 — 서비스 연결(통합 모델 설계 §7-14-13).

판정 규칙은 `src.famous_check`(확정 — shared/famous_check_confirmed.json 이 그 모듈과 등록부의
해시를 담는다)이고, 이 모듈은 그것을 고치지 않고 바깥에서 감싼다. 백엔드 엔진(backend/src/core/
multi_search.py)과 측정 스크립트(ml/scripts/famous_check_measure.py·famous_check_confirm.py·
famous_connect.py)가 같이 쓴다 — 로고 판정(LogoIndex), 글자 위주 구분의 이름(kind_name), 유사군
코드에서 질의의 류 정하기(classes_from_codes)는 여기 한 곳에만 있다. ml/scripts 의 코드는 부르지
않는다(백엔드 이미지에는 ml/src 만 들어간다).

기동 때 읽는 것(load_runtime — 하나라도 없거나 깨졌거나 해시가 다르면 FamousUnavailable):
    shared/famous_check_confirmed.json
        확정 파일(약한 일치 조건·기준·결합 하한·등록부 해시). 이 파일의 sha256 을 계수 JSON 의
        famous_check.confirmed_sha256 과 대조한다
    shared/famous_registry.json
        등록부 — sha256 을 확정 파일에 적힌 값과 대조한다
    shared/famous_logo_kinds.json
        대표 로고의 글자 위주·결합·도형 위주 구분(미리 계산한 것 — ml/scripts/famous_connect.py
        kinds). 그 파일을 만든 때의 등록부 sha256 을 담는다
    shared/goods_map/business_presets.json
        업종 세트(판정 모듈의 업종 낱말, 질의의 류)
    shared/goods_map/goods_map.json.gz
        상품↔유사군 변환표(유사군 코드의 대표 류, 업종 세트의 류)
    shared/distinctiveness/*
        식별력 자료(판정 모듈이 쓴다 — 엔진이 적재한 것을 받는다)
해시는 줄 끝을 LF 로 맞춘 내용으로 잰다(체크아웃이 CRLF 로 바꿔도 같게). 판정 모듈 자신의 해시는
여기서 보지 않는다(시험 ml/tests/test_famous_check_confirm.py 가 본다).

질의마다 하는 것(check):
    이름            질의 이름을 판정 모듈(fc.check_famous)에 그대로 넘긴다
    업종            유사군 코드만 받는다. 질의의 류 = 코드 집합이 어느 업종 세트의 코드와 같으면 그
                    세트의 류, 아니면 코드마다 대표 류(변환표에서 그 코드가 붙은 상품이 가장 많은
                    류)의 합집합(classes_from_codes — 규칙 세션에서 확인한 안)
    로고            질의 이미지가 있고 사진이 아니면, 대표 로고와의 유사도가 엔진의 "이미지만"
                    판단에서 위험일 때 강함(대표 로고와 질의가 둘 다 글자 위주면 0.98 이상 —
                    fc.logo_match). 로고 일치의 바닥은 위험
    이미지 속 글자  이름이 없고 OCR 제안 상표명이 있으면 그 글자로(같음·품음-설명 — 강함만)
    → 브랜드마다 가장 강한 일치 하나, 강한 것부터 MAX_MATCHES 개와 전체 등급 바닥
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from src import famous_check as fc
from src import mark_type as mt
from src.axes.pair_axes import clean_input_name, normalize_codes

REPO_ROOT = fc.REPO_ROOT
CONFIRMED_PATH = REPO_ROOT / "shared" / "famous_check_confirmed.json"
LOGO_KINDS_PATH = REPO_ROOT / "shared" / "famous_logo_kinds.json"
# 경로를 바꿔 띄울 때(시험·점검): 인자 > 환경 변수 > 기본 경로
ENV_REGISTRY = "MARKLENS_FAMOUS_REGISTRY"
ENV_CONFIRMED = "MARKLENS_FAMOUS_CONFIRMED"
ENV_LOGO_KINDS = "MARKLENS_FAMOUS_LOGO_KINDS"
# 유명 상표 확인이 런타임에 읽는 저장소 파일(저장소 루트 기준) — 백엔드 이미지에 들어 있어야 한다
# (scripts/check_backend_image.py 가 본다). 계수 JSON(shared/model/risk_model_v1.4.7.json)의
# famous_check 표시가 확정 파일을 가리키고, 대표 로고의 임베딩·이미지 경로는 엔진이 적재한 DB(색인·
# 메타데이터 — 비공개 데이터, 이미지에 없음)에서 온다.
RUNTIME_FILES = (
    "shared/famous_check_confirmed.json",  # 확정 파일(약한 일치 조건·기준·등록부 해시)
    "shared/famous_registry.json",  # 등록부
    "shared/famous_logo_kinds.json",  # 대표 로고의 글자 위주·결합·도형 위주 구분
    "shared/goods_map/business_presets.json",  # 업종 세트(업종 낱말, 질의의 류)
    "shared/goods_map/goods_map.json.gz",  # 상품↔유사군 변환표(대표 류, 식별력의 고시 명칭)
    "shared/distinctiveness/token_stats.json",  # 식별력 자료(판정 모듈의 설명 낱말 판정)
    "shared/distinctiveness/descriptive_terms.json",
    "shared/distinctiveness/weak_token_overrides.json",
    "shared/famous_brands.txt",  # 식별력 모듈의 유명 토큰
)
CONFIRMED_VERSION = "famous_check_confirmed_v1"
LOGO_KINDS_VERSION = "famous_logo_kinds_v1"

# OCR 자동 유형(src.mark_type.auto_type) → 로고 규칙이 쓰는 구분의 이름
KIND_NAMES = {"문자": "글자 위주", "결합": "결합", "도형": "도형 위주"}
KIND_UNKNOWN = "유형 모름"
# 응답에 쓰는 이름 — 종류(level)와 경로(basis)
LEVEL_NAMES = {fc.LEVEL_STRONG: "강함", fc.LEVEL_WEAK: "약함", fc.LEVEL_NOTICE: "설명적 사용"}
BASIS_NAME, BASIS_LOGO, BASIS_OCR = "이름", "로고", "이미지 속 글자"
BASIS_NAMES = {fc.BASIS_NAME: BASIS_NAME, fc.BASIS_OCR: BASIS_OCR}
LOGO_LEVEL = "도형"  # 이미지만 판단의 기본 유형(자동 유형의 이름 없는 이미지 질의 — 도형계)
LOGO_FLOOR = fc.GRADE_RISK  # 로고 일치(강함)가 주는 전체 등급 바닥
MAX_MATCHES = 2  # 응답에 싣는 브랜드 수
MAX_LOGOS = 2  # 브랜드마다 싣는 대표 로고 수
STATUS_CHECKED, STATUS_UNAVAILABLE = "checked", "unavailable"
_NOTE_SPELLING = re.compile(r"\(철자 [0-9.]+\)$")


class FamousUnavailable(RuntimeError):
    """유명 상표 확인에 필요한 자료를 쓸 수 없다(없음·깨짐·해시 다름). 엔진은 모델 파일 문제와 같게
    검색을 준비 안 됨으로 둔다 — 응답에는 이 글을 내보내지 않는다(원인은 기동 로그)."""


# ---- 파일·해시 ---------------------------------------------------------------------------------

def file_sha256(path: str | os.PathLike[str]) -> str:
    """줄 끝을 LF 로 맞춘 내용의 sha256(체크아웃이 CRLF 로 바꿔도 같게)."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def resolve_path(path: str | os.PathLike[str] | None, env: str, default: Path) -> Path:
    if path:
        return Path(path)
    value = os.environ.get(env, "").strip()
    return Path(value) if value else default


def _read_json(path: Path, label: str) -> dict:
    if not path.is_file():
        raise FamousUnavailable(f"{label} 없음")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FamousUnavailable(f"{label} 을 읽지 못함({type(exc).__name__})") from None
    if not isinstance(data, dict):
        raise FamousUnavailable(f"{label} 의 형식이 다름")
    return data


def load_confirmed(path: str | os.PathLike[str] | None = None, *,
                   expected_sha256: str | None = None,
                   expected_version: str | None = None) -> tuple[dict, str]:
    """확정 파일 — (내용, sha256). expected_sha256(계수 JSON 에 적힌 값)과 다르면 거절한다."""
    resolved = resolve_path(path, ENV_CONFIRMED, CONFIRMED_PATH)
    data = _read_json(resolved, "확정 파일")
    digest = file_sha256(resolved)
    if expected_sha256 is not None and digest != expected_sha256:
        raise FamousUnavailable("확정 파일의 해시가 계수 JSON 에 적힌 값과 다름")
    version = data.get("version")
    if version != CONFIRMED_VERSION or (expected_version is not None
                                        and version != expected_version):
        raise FamousUnavailable("확정 파일의 버전이 다름")
    rule, registry = data.get("규칙"), data.get("등록부")
    if not (isinstance(rule, dict) and isinstance(rule.get("기준"), dict)
            and isinstance(rule.get("결합_하한"), (int, float))
            and isinstance(registry, dict) and isinstance(registry.get("sha256"), str)):
        raise FamousUnavailable("확정 파일의 형식이 다름")
    if rule.get("로고_글자끼리_유사도") != fc.LOGO_TEXT_SIMILARITY:
        raise FamousUnavailable("확정 파일의 로고 기준이 판정 모듈과 다름")
    return data, digest


def confirmed_thresholds(confirmed: Mapping) -> fc.Thresholds:
    """확정 파일의 기준 → 판정 모듈의 기준값."""
    try:
        return fc.Thresholds.from_dict(confirmed["규칙"]["기준"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FamousUnavailable(f"확정 파일의 기준을 읽지 못함({type(exc).__name__})") from None


def load_logo_kinds(path: str | os.PathLike[str] | None = None, *,
                    registry_sha256: str | None = None) -> dict[str, str]:
    """대표 로고의 구분(출원번호 → 글자 위주·결합·도형 위주·유형 모름). 등록부가 그 파일을 만든 때의
    것과 다르면 거절한다."""
    data = _read_json(resolve_path(path, ENV_LOGO_KINDS, LOGO_KINDS_PATH), "대표 로고 구분 파일")
    kinds = data.get("kinds")
    if data.get("version") != LOGO_KINDS_VERSION or not isinstance(kinds, dict):
        raise FamousUnavailable("대표 로고 구분 파일의 형식이 다름")
    if registry_sha256 is not None and data.get("registry_sha256") != registry_sha256:
        raise FamousUnavailable("대표 로고 구분 파일이 지금 등록부의 것이 아님")
    return {str(appno): str(kind) for appno, kind in kinds.items()}


# ---- 질의의 류(유사군 코드에서) ----------------------------------------------------------------

def representative_classes(goods_map) -> dict[str, int]:
    """유사군 코드 → 대표 류(변환표에서 그 코드가 붙은 상품이 가장 많은 류, 같으면 작은 번호)."""
    counts: dict[str, Counter] = {}
    for entry in goods_map.entries:
        for code in entry.similarity_codes:
            counts.setdefault(code, Counter())[int(entry.nice_class)] += 1
    return {code: min(count, key=lambda nice: (-count[nice], nice))
            for code, count in counts.items()}


def preset_tables(presets) -> tuple[dict[str, list[str]], dict[str, list[int]]]:
    """업종 세트 → (유사군 코드, 그 세트의 지정상품이 속한 류)."""
    codes = {preset.id: sorted({code for good in preset.goods for code in good.similarity_codes})
             for preset in presets.presets}
    classes = {preset.id: sorted({good.nice_class for good in preset.goods if good.nice_class})
               for preset in presets.presets}
    return codes, classes


def classes_from_codes(codes, codes_of: Mapping, classes_of: Mapping,
                       representative: Mapping[str, int]) -> tuple[list[int], str]:
    """질의의 류를 유사군 코드만으로 정한다 — (류, 근거). ① 코드 집합이 어느 업종 세트의 코드와
    같으면 그 세트의 류 ② 아니면 코드마다 대표 류의 합집합."""
    wanted = sorted({str(code).strip().upper() for code in codes or () if str(code).strip()})
    same = [preset for preset, preset_codes in codes_of.items() if list(preset_codes) == wanted]
    if same:
        return (sorted({nice for preset in same for nice in classes_of[preset]}),
                f"업종 세트({'·'.join(same)})")
    return (sorted({representative[code] for code in wanted if code in representative}),
            "코드별 대표 류")


# ---- 글자 위주 구분 ----------------------------------------------------------------------------

def kind_name(ocr_kind: str | None) -> str:
    """OCR 자동 유형(문자·결합·도형) → 글자 위주·결합·도형 위주. 모르면 "유형 모름"."""
    return KIND_NAMES.get(ocr_kind or "", KIND_UNKNOWN)


def kind_from_ratios(text_ratio: float | None, fig_ratio: float | None) -> str | None:
    """검색이 이미 구한 OCR 면적 비율(query_type.detail) → 구분. 비율이 없으면 None."""
    if text_ratio is None or fig_ratio is None:
        return None
    return kind_name(mt.auto_type(float(text_ratio), float(fig_ratio))[0])


def kind_from_type(level: str | None) -> str | None:
    """사용자가 고른 유형(문자·도형·결합-…) → 구분. OCR 을 돌리지 않은 질의에 쓴다."""
    if not level:
        return None
    return kind_name(mt.display_type(level))


# ---- 로고 --------------------------------------------------------------------------------------

class LogoIndex:
    """대표 로고(역할 "대표 로고(현재)"·"과거 로고")와 질의 이미지의 일치 — 강함만. 둘 사이의 엔진
    "이미지만" 판단 등급이 위험인 유사도일 때 일치로 보고, 구분(kinds)이 있으면 로고 규칙
    (fc.logo_match — 둘 다 글자 위주면 0.98 이상, 사진으로 판정된 대표 로고는 보지 않음)까지 본다.

    marks 는 (브랜드, 표장, 색인 순번), matrix 는 그 순서의 단위 벡터, grade_of(유사도, 유형)는
    엔진의 이미지만 판단 등급."""

    def __init__(self, marks: list[tuple[str, fc.Mark, int]], matrix: np.ndarray,
                 grade_of: Callable[[float, str], str], *, kinds: list[str] | None = None,
                 photos: list[bool] | None = None):
        self.marks = marks
        self.matrix = matrix
        self.kinds = kinds
        self.photos: list[bool] = list(photos) if photos is not None else []
        self._grade_of = grade_of
        self._risk_min: dict[str, float] = {}

    @staticmethod
    def entries(registry: fc.Registry, by_appno: Mapping) -> tuple[list, int]:
        """등록부의 대표 로고 가운데 지금 색인에 있는 것 — ((브랜드, 표장, 순번) 목록, 건너뛴 수).
        by_appno 는 출원번호 → 레코드(pos = 색인 순번, 없으면 None)."""
        found, skipped = [], 0
        for brand in registry.brands:
            for mark in brand.logo_marks:
                record = by_appno.get(mark.appno)
                if record is None or record.pos is None or not mark.image_exists:
                    skipped += 1
                    continue
                found.append((brand.name, mark, record.pos))
        return found, skipped

    def risk_min(self, level: str = LOGO_LEVEL) -> float:
        """이미지만 판단이 위험이 되는 가장 작은 유사도(넷째 자리) — 등급이 바뀌는 곳을 유형마다
        한 번 찾아 둔다. 위험에 닿지 않는 유형이면 2.0."""
        found = self._risk_min.get(level)
        if found is None:
            if self._grade_of(1.0, level) != fc.GRADE_RISK:
                found = 2.0
            else:
                low, high = 0, 10000  # high 는 위험(1.0)
                while low < high:
                    middle = (low + high) // 2
                    if self._grade_of(middle / 10000, level) == fc.GRADE_RISK:
                        high = middle
                    else:
                        low = middle + 1
                found = low / 10000
            self._risk_min[level] = found
        return found

    def is_risk(self, value: float, level: str = LOGO_LEVEL) -> bool:
        return value >= self.risk_min(level) - 1e-9

    def strong(self, embedding, *, exclude: str | None = None, query_kind: str | None = None,
               level: str = LOGO_LEVEL, rule: bool = True) -> dict[str, dict]:
        """강함인 브랜드 — 브랜드마다 일치하는 표장 가운데 가장 닮은 것. 구분이 있고 rule 이면 로고
        규칙까지 본다. 사진으로 판정된 질의는 부르는 쪽이 거른다."""
        if not self.marks:
            return {}
        scores = self.matrix @ embedding
        use_rule = rule and self.kinds is not None
        best: dict[str, tuple[float, fc.Mark]] = {}
        for index, ((brand, mark, _), score) in enumerate(zip(self.marks, scores)):
            if mark.appno == exclude:
                continue
            value = round(min(1.0, max(0.0, float(score))), 4)
            if not self.is_risk(value, level):
                continue
            if use_rule and not fc.logo_match(
                    value, fc.GRADE_RISK, logo_kind=self.kinds[index], query_kind=query_kind,
                    logo_photo=self.photos[index]):
                continue
            if brand not in best or value > best[brand][0]:
                best[brand] = (value, mark)
        return {brand: {"유사도": value, "표장": mark.appno, "표장_이름": mark.title,
                        "역할": mark.role, "표장_이미지": mark.image}
                for brand, (value, mark) in best.items()}


def build_logo_index(registry: fc.Registry, by_appno: Mapping, embeddings: np.ndarray,
                     grade_of: Callable[[float, str], str], kinds: Mapping[str, str], *,
                     photo_of: Callable[[np.ndarray], bool] | None = None
                     ) -> tuple[LogoIndex, dict]:
    """서비스의 로고 색인 — 색인에 있고 구분이 적힌 대표 로고만. (색인, 건수: 등록부의 대표 로고·
    쓰는 것·색인에 없어 건너뜀·구분이 없어 건너뜀)."""
    found, skipped = LogoIndex.entries(registry, by_appno)
    usable = [entry for entry in found if entry[1].appno in kinds]
    matrix = (embeddings[[pos for _, _, pos in usable]] if usable
              else np.zeros((0, embeddings.shape[1]), dtype=np.float32))
    photos = [bool(photo_of(row)) if photo_of is not None else False for row in matrix]
    index = LogoIndex(usable, matrix, grade_of,
                      kinds=[kinds[mark.appno] for _, mark, _ in usable], photos=photos)
    stats = {"등록부의_대표_로고": len(found) + skipped, "쓰는_것": len(usable),
             "색인에_없음": skipped, "구분_없음": len(found) - len(usable)}
    return index, stats


def brand_logo_table(registry: fc.Registry,
                     available: Callable[[str], bool]) -> dict[str, tuple[str, ...]]:
    """브랜드 → 보여 줄 대표 로고의 출원번호("대표 로고(현재)" 먼저, 그다음 "과거 로고"; 받을 수
    있는 것만)."""
    table = {}
    for brand in registry.brands:
        marks = sorted(brand.logo_marks, key=lambda mark: fc.LOGO_ROLES.index(mark.role))
        table[brand.name] = tuple(mark.appno for mark in marks if available(mark.appno))
    return table


def mark_brand_table(registry: fc.Registry) -> dict[str, str]:
    """출원번호 → 브랜드("관련 없음"이 아닌 등록부의 표장). 두 브랜드에 함께 걸려 정할 수 없는
    표장은 뺀다."""
    table: dict[str, str] = {}
    for brand in registry.brands:
        for mark in brand.own_marks:
            if not mark.shared:
                table.setdefault(mark.appno, brand.name)
    return table


# ---- 기동 --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Runtime:
    """기동 때 한 번 만들어 두는 것 — 질의마다 check 가 읽기만 한다(스레드 안전)."""

    registry: fc.Registry
    thresholds: fc.Thresholds
    dist: object
    goods_floor: float
    codes_of: Mapping[str, list[str]]
    classes_of: Mapping[str, list[int]]
    representative: Mapping[str, int]
    logo_kinds: Mapping[str, str]
    confirmed_sha256: str
    registry_sha256: str
    logos: LogoIndex | None = None  # 없으면 로고 경로를 쓰지 않는다(가짜 ML·색인 벡터 없음)
    brand_logos: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    brand_of_mark: Mapping[str, str] = field(default_factory=dict)

    @property
    def brand_count(self) -> int:
        return len(self.registry.brands)


def load_runtime(config: Mapping | None, *, dist, goods_map, presets,
                 registry_path: str | os.PathLike[str] | None = None,
                 confirmed_path: str | os.PathLike[str] | None = None,
                 logo_kinds_path: str | os.PathLike[str] | None = None) -> Runtime:
    """확정 파일·등록부·대표 로고 구분·업종 표를 읽고 해시를 대조한다. config 는 계수 JSON 의
    famous_check(version·confirmed_sha256) — None 이면 계수 JSON 과의 대조만 건너뛴다(측정·시험).
    로고 색인(logos)·보여 줄 로고(brand_logos)는 엔진이 with_engine 으로 붙인다."""
    config = config or {}
    confirmed, confirmed_sha = load_confirmed(
        confirmed_path, expected_sha256=config.get("confirmed_sha256"),
        expected_version=config.get("version"))
    registry_file = resolve_path(registry_path, ENV_REGISTRY, fc.DEFAULT_REGISTRY_PATH)
    if not registry_file.is_file():
        raise FamousUnavailable("등록부 없음")
    registry_sha = file_sha256(registry_file)
    if registry_sha != confirmed["등록부"]["sha256"]:
        raise FamousUnavailable("등록부의 해시가 확정 파일에 적힌 값과 다름")
    try:
        registry = fc.load_registry(registry_file)
    except Exception as exc:  # 형식이 다른 등록부 — 판정 모듈이 거절
        raise FamousUnavailable(f"등록부를 읽지 못함({type(exc).__name__})") from None
    kinds = load_logo_kinds(logo_kinds_path, registry_sha256=registry_sha)
    try:
        fc.industry_words()  # 업종 낱말(업종 세트 파일) — 없으면 여기서 드러난다
        codes_of, classes_of = preset_tables(presets)
        representative = representative_classes(goods_map)
    except Exception as exc:
        raise FamousUnavailable(f"업종 세트·변환표를 읽지 못함({type(exc).__name__})") from None
    return Runtime(
        registry=registry, thresholds=confirmed_thresholds(confirmed), dist=dist,
        goods_floor=float(confirmed["규칙"]["결합_하한"]), codes_of=codes_of,
        classes_of=classes_of, representative=representative, logo_kinds=kinds,
        confirmed_sha256=confirmed_sha, registry_sha256=registry_sha,
        brand_of_mark=mark_brand_table(registry))


def with_engine(runtime: Runtime, *, logos: LogoIndex | None,
                brand_logos: Mapping[str, tuple[str, ...]]) -> Runtime:
    """엔진이 만든 로고 색인과 보여 줄 로고 표를 붙인 것."""
    return replace(runtime, logos=logos, brand_logos=dict(brand_logos))


# ---- 질의 --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Match:
    """브랜드 하나와의 일치 — 응답 한 줄."""

    brand: str
    level: str  # 강함 | 약함 | 설명적 사용
    basis: str  # 이름 | 로고 | 이미지 속 글자
    notation: str | None  # 일치한 표기(로고 일치는 없음)
    matched_text: str | None  # 질의에서 맞은 글자(로고 일치는 없음)
    protection: str
    overlap: bool | None  # 업종 겹침(업종이 없거나 로고 일치면 None)
    floor: str | None  # 위험 | 검토 권장 | None
    logos: tuple[str, ...]  # 대표 로고 출원번호(현재 먼저, 로고 일치는 맞은 표장 먼저)
    path: str | None = None  # 같음·품음-설명·품음-기타·소리·철자(응답에 싣지 않는다 — 검증용)
    score: float | None = None
    mark: str | None = None  # 로고 일치: 가장 닮은 대표 로고

    @property
    def order(self) -> tuple:
        """강한 것부터 — 종류 → 이름·글자가 로고보다 먼저 → 판정 모듈의 순서(경로·점수)."""
        rank = {"강함": 3, "약함": 2, "설명적 사용": 1}[self.level]
        return rank, self._path_rank, self.score or 0.0

    @property
    def _path_rank(self) -> tuple[int, int]:
        if self.basis == BASIS_LOGO:
            return 0, 0
        return 1, fc._PATH_RANK[self.path]  # noqa: SLF001 — 판정 모듈과 같은 순서


@dataclass(frozen=True)
class Outcome:
    matches: tuple[Match, ...]  # 강한 것부터 MAX_MATCHES 개
    floor: str | None  # 전체 등급 바닥(모든 일치 가운데 가장 높은 것)
    brands: int = 0  # 일치한 브랜드 수(자르기 전)
    result: fc.FamousResult | None = None  # 이름·이미지 속 글자의 판정(검증용)
    logo_hits: Mapping[str, dict] = field(default_factory=dict)  # 로고 판정(검증용)
    classes: tuple[int, ...] | None = None  # 질의의 류(업종이 없으면 None)
    classes_basis: str | None = None


def original_span(source: object, key: str | None) -> str | None:
    """질의 글자열에서 붙여 쓴 꼴 key 에 해당하는 부분을 원래 대소문자·띄어쓰기로. 못 찾으면 key."""
    if not key:
        return None
    text = clean_input_name(source)
    squeezed, owners = [], []
    for index, char in enumerate(text):
        for piece in fc.text_key(char):
            squeezed.append(piece)
            owners.append(index)
    joined = "".join(squeezed)
    start = joined.find(key) if joined == fc.text_key(text) else -1
    if start < 0:
        return key
    return text[owners[start]:owners[start + len(key) - 1] + 1].strip() or key


def _matched_key(match: fc.BrandMatch, evidence: fc.BrandEvidence | None) -> str | None:
    """일치가 질의의 어느 글자(붙여 쓴 꼴)에서 나왔는가."""
    if match.path == fc.PATH_EXACT:
        return fc.text_key(match.notation)
    item = next((entry for entry in (evidence.items if evidence else ())
                 if entry.notation == match.notation), None)
    if item is None:
        return None
    if match.path in (fc.PATH_CONTAIN_DESC, fc.PATH_CONTAIN_OTHER):
        return item.contain_word
    noted = _NOTE_SPELLING.sub("", match.note or "")
    if noted in {unit[0] for unit in item.units}:
        return noted
    return item.best(1 if match.path == fc.PATH_SOUND else 2)[1]


def _logos(runtime: Runtime, brand: str, first: str | None = None) -> tuple[str, ...]:
    listed = ([first] if first else []) + list(runtime.brand_logos.get(brand, ()))
    return tuple(dict.fromkeys(listed))[:MAX_LOGOS]


def check(runtime: Runtime, *, name: object = None, goods: Iterable[str] | None = None,
          ocr_text: object = None, embedding: np.ndarray | None = None,
          query_kind: str | None = None, query_photo: bool = False,
          level: str = LOGO_LEVEL) -> Outcome:
    """질의 하나의 유명 상표 확인.

    name        질의 이름
    goods       유사군 코드
    ocr_text    이름 없는 이미지 질의에서 검색이 읽은 글자(OCR 제안 상표명)
    embedding   질의 이미지 임베딩
    query_kind  질의 이미지의 글자 위주·결합·도형 위주(모르면 None)
    query_photo 질의 이미지의 사진 판정
    level       이미지만 판단에 쓰는 유형(엔진의 logo_floor 가 쓰는 것과 같은 것)
    """
    codes = sorted(normalize_codes(goods)) if goods else None
    classes: list[int] | None = None
    basis: str | None = None
    if codes:
        classes, basis = classes_from_codes(codes, runtime.codes_of, runtime.classes_of,
                                            runtime.representative)
    text = name if fc.normalize_text(name) else None
    seen = None if text is not None else (ocr_text if fc.normalize_text(ocr_text) else None)
    rows: list[Match] = []
    result: fc.FamousResult | None = None
    if text is not None or seen is not None:
        # fc.check_famous 와 같은 순서(질의 정리 → 근거 → 기준 적용)를 한 번에 — 근거를 따로 쥐고
        # 있어야 "질의에서 맞은 글자"를 찾을 수 있다. 이미지 속 글자는 같음·품음만(similarity=False)
        source = text if text is not None else seen
        gathered = fc.collect_evidence(
            fc.prepare_query(source, codes, classes), runtime.registry, runtime.dist,
            runtime.goods_floor, similarity=text is not None)
        result = fc.decide(gathered, runtime.thresholds,
                           basis=fc.BASIS_NAME if text is not None else fc.BASIS_OCR)
        evidence = {item.brand: item for item in gathered}
        for match in result.matches:
            rows.append(Match(
                brand=match.brand, level=LEVEL_NAMES[match.level],
                basis=BASIS_NAMES[match.basis], notation=match.notation,
                matched_text=original_span(
                    source, _matched_key(match, evidence.get(match.brand))),
                protection=match.protection, overlap=match.overlap, floor=match.floor,
                logos=_logos(runtime, match.brand), path=match.path, score=match.score))
    hits: dict[str, dict] = {}
    if embedding is not None and runtime.logos is not None and not query_photo:
        hits = runtime.logos.strong(embedding, query_kind=query_kind, level=level)
        protections = {brand.name: brand.protection for brand in runtime.registry.brands}
        for brand, hit in hits.items():
            rows.append(Match(
                brand=brand, level=LEVEL_NAMES[fc.LEVEL_STRONG], basis=BASIS_LOGO, notation=None,
                matched_text=None, protection=protections[brand], overlap=None,
                floor=LOGO_FLOOR, logos=_logos(runtime, brand, hit["표장"]), path=None,
                score=hit["유사도"], mark=hit["표장"]))
    floors = [row.floor for row in rows if row.floor]
    best: dict[str, Match] = {}
    for row in sorted(rows, key=lambda item: item.order, reverse=True):
        best.setdefault(row.brand, row)
    matches = tuple(best.values())
    return Outcome(
        matches=matches[:MAX_MATCHES],
        floor=max(floors, key=fc.GRADES.index) if floors else None, brands=len(matches),
        result=result, logo_hits=hits, classes=None if classes is None else tuple(classes),
        classes_basis=basis)
