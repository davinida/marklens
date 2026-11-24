"""유명 상표 확인 — 등록부와 일치 판정(1단계 측정용: 엔진·계약·화면에서 부르지 않는다).

통합 모델 설계 §7-14. 유명 상표 보호는 일반 유사 판단과 근거가 달라, 업종에 따라 움직이는 판단
앞에 따로 둔다. 질의 이름이 등록부(shared/famous_registry.json — `ml/scripts/famous_registry.py`
가 만든다)의 브랜드 표기와 일치하는지를 **표기 기준**으로 본다. 식별력 필터(요부 추출)는
거치지 않는다 — 설명 낱말로 빠지는 "bbq" 도 견줘야 한다.

용어
    붙여 쓴 꼴(key)  정리(clean_input_name → 상표 기호 제거·NFKC·소문자) 뒤 한글·영문·숫자만
                    이은 것.
    낱말            공백·기호로 나눈 것(접미어 분리 `split_goods_suffix` 뒤)의 붙여 쓴 꼴.
    낱말 묶음       이어진 낱말(최대 MAX_BUNDLE_WORDS)을 붙인 꼴.
    조각            낱말을 문자 종류(한글/영문/숫자) 경계로 나눈 것(X1 토큰화와 같은 기준).
    식별력 없는 말  유명 예외를 뺀 식별력 판정(`judge(…, famous_exception=False)`)이 약함(< θ) —
                    질의 업종이 있으면 그 업종이나 브랜드 업종 중 하나에서, 없으면 브랜드 업종에서
                    약하거나 상품 접미어 사전(고시 단일 명칭)에 있는 말.

경로(견주는 단위는 낱말 묶음과 표기의 붙여 쓴 꼴)
    (가) 같음       낱말 묶음 = 표기.
    (나) 품음       한 낱말이 표기로 시작하거나 끝남. 나머지가 식별력 없는 말이면 "품음-설명",
                    아니면 "품음-기타"(결정 대기). 짧은 표기는 품음-설명만.
    (다) 소리       X1 `phonetic_similarity`(식별력 필터 없이). 대상은 낱말 묶음과, 중간·김 표기에
                    한해 한 낱말의 앞·뒤 구간으로서 나머지가 식별력 없는 말인 것.
    (라) 철자       같은 문자 종류끼리만 `orthographic_similarity`(v1). 대상은 (다)와 같다.
    약한 표기       (가)만 — 질의에서 상품·업종을 나타내는 말(1호·3호로 약한 말, 상품 접미어)을 뺀
                    나머지가 그 표기 하나뿐이면 일치(업종이 겹치거나 없으면 강함, 다르면 설명적
                    사용 안내), 다른 말과 함께면 설명적 사용 안내. 질의 안의 약한 표기 조각은 그
                    브랜드의 다른 표기와 견주지 않는다(가림) — "텍사스 BBQ" 의 bbq 가 "비비큐"
                    와 소리 1.0 으로 강한 일치가 되면 "그 표기 하나뿐일 때만"이 무력해진다.

수준과 바닥
    강함 = 같음·품음-설명·소리 ≥ 강한 소리·철자 ≥ 강한 철자, 약함 = 소리·철자 ≥ 약한 기준·품음-기타.
    업종 불문 브랜드: 강함 → 위험, 약함 → 검토 권장. 같은·가까운 업종 중심 브랜드: 업종이 겹치거나
    없으면 같고, 다르면 강함 → 검토 권장·약함 → 안내만. 설명적 사용 안내는 바닥이 없다.
    업종 겹침 = 질의 업종과 브랜드 업종(브랜드 표장 하나하나의 유사군, 그리고 업종 세트의 유사군)
    사이 X4(자카드)의 최댓값 ≥ 결합 하한(계수 JSON coupling.floors.x4 = 0.0252).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping

from src.axes.distinctiveness import Distinctiveness, TokenJudgement, load_distinctiveness
from src.axes.pair_axes import clean_input_name, normalize_codes
from src.axes.x1_phonetic import (
    _basic_normalize,
    _char_class,
    _clean_chars,
    _tokenize,
    phonetic_similarity,
)
from src.axes.x2_ortho import orthographic_similarity
from src.axes.x4_goods import goods_similarity

__all__ = [
    "REGISTRY_VERSION", "OVERRIDES_VERSION", "DEFAULT_REGISTRY_PATH", "DEFAULT_OVERRIDES_PATH",
    "DEFAULT_BRANDS_PATH", "PROTECT_ANY", "PROTECT_NEAR", "ROLE_NAME", "ROLE_FIGURE",
    "ROLE_OTHER", "ROLE_LOGO", "ROLE_EXCLUDED", "LENGTHS", "LEVEL_STRONG", "LEVEL_WEAK",
    "LEVEL_NOTICE", "PATH_EXACT", "PATH_CONTAIN_DESC", "PATH_CONTAIN_OTHER", "PATH_SOUND",
    "PATH_SPELLING", "BASIS_NAME", "BASIS_OCR", "Notation", "Mark", "Brand", "Registry",
    "Thresholds", "PreparedQuery", "Evidence", "BrandEvidence", "BrandMatch", "FamousResult",
    "normalize_text", "split_pieces", "text_key", "script_label", "length_class",
    "analyze_notation", "read_brand_table", "title_has_notation", "auto_role",
    "build_registry", "registry_to_json", "load_registry", "load_overrides", "prepare_query",
    "collect_evidence", "decide", "check_famous", "default_goods_floor",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = REPO_ROOT / "shared" / "famous_registry.json"
DEFAULT_OVERRIDES_PATH = REPO_ROOT / "shared" / "famous_registry_overrides.json"
DEFAULT_BRANDS_PATH = REPO_ROOT / "shared" / "famous_brands.txt"
REGISTRY_VERSION = "famous_registry_v1"
OVERRIDES_VERSION = "famous_registry_overrides_v1"
BRAND_SECTION = "[브랜드]"

PROTECT_ANY = "업종 불문"
PROTECT_NEAR = "같은·가까운 업종 중심"
PROTECTIONS = (PROTECT_ANY, PROTECT_NEAR)
ROLE_NAME, ROLE_FIGURE, ROLE_OTHER = "이름", "도형", "다른 이름"
ROLE_LOGO, ROLE_EXCLUDED = "브랜드 로고", "제외"  # overrides 로만
AUTO_ROLES = (ROLE_NAME, ROLE_FIGURE, ROLE_OTHER)
OVERRIDE_ROLES = (ROLE_LOGO, ROLE_EXCLUDED)
BRAND_MARK_ROLES = (ROLE_NAME, ROLE_FIGURE, ROLE_LOGO)  # 브랜드 자신의 표장으로 보는 역할
SOURCE_FAMOUS, SOURCE_EXISTING = "유명 브랜드 수집", "기존 수집(같은 출원인)"

LENGTH_SHORT, LENGTH_MID, LENGTH_LONG = "짧음", "중간", "김"
LENGTHS = (LENGTH_SHORT, LENGTH_MID, LENGTH_LONG)
ALNUM_WEIGHT = 0.6  # 길이 환산: 한글 음절 1 = 영문·숫자 1/0.6자(순수 표기에서는 지시의 구간과 같다)
LEVEL_STRONG, LEVEL_WEAK, LEVEL_NOTICE = "강함", "약함", "설명적 사용 안내"
PATH_EXACT, PATH_CONTAIN_DESC, PATH_CONTAIN_OTHER = "같음", "품음-설명", "품음-기타"
PATH_SOUND, PATH_SPELLING = "소리", "철자"
BASIS_NAME, BASIS_OCR = "이름", "이미지 속 글자 기준"
GRADES = ("안전", "주의", "검토 권장", "위험")
GRADE_REVIEW, GRADE_RISK = "검토 권장", "위험"
STRONG_SOUND = 0.98  # 단독 축 기준(standalone x1)과 같다
MAX_BUNDLE_WORDS = 5  # 낱말 묶음에 넣는 이어진 낱말 수 상한
WEAK_USE_ALONE, WEAK_USE_WITH_OTHERS = "단독", "다른 말과 함께"
# 상품·업종을 나타내는 말(보통명칭·성질표시)로 보는 판정 사유의 머리
GOODS_WORD_REASONS = ("1호 보통명칭", "3호 기술적 표장")
_LEVEL_RANK = {LEVEL_STRONG: 3, LEVEL_WEAK: 2, LEVEL_NOTICE: 1}
_PATH_RANK = {PATH_EXACT: 5, PATH_CONTAIN_DESC: 4, PATH_SOUND: 3, PATH_SPELLING: 2,
              PATH_CONTAIN_OTHER: 1}
_SCRIPT_NAMES = {"H": "한글", "L": "영문", "D": "숫자"}
_URL = re.compile(r"https?://\S+")
_INLINE_COMMENT = re.compile(r"\s+#.*$")
_HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
_TITLE_DROP = re.compile(r"['’`\-]")


# ---- 글자 정리 ---------------------------------------------------------------------------------

def normalize_text(text: object) -> str:
    """정리 — clean_input_name(서식 문자 제거·NFC) → 상표 기호 제거·NFKC·소문자(대소문자 무시)."""
    return _basic_normalize(clean_input_name(text))


def split_pieces(text: str) -> list[str]:
    """정리한 글자열 → 문자 종류(한글/영문/숫자) 경계 조각. 기호는 공백, 한자·기타 문자는 버린다
    (X1 토큰화와 같은 기준)."""
    return _tokenize(_clean_chars(text))


def text_key(text: object) -> str:
    """붙여 쓴 꼴 — 정리 뒤 한글·영문·숫자만 이은 것("L'OREAL" → "loreal")."""
    return "".join(split_pieces(normalize_text(text)))


def script_label(key: str) -> str:
    """문자 종류 — "한글"·"영문"·"숫자" 또는 섞인 것("영문+숫자")."""
    kinds = {_SCRIPT_NAMES[c] for c in map(_char_class, key) if c in _SCRIPT_NAMES}
    return "+".join(name for name in ("한글", "영문", "숫자") if name in kinds)


def length_class(key: str) -> str:
    """길이 구간 — 짧음 = 한글 2음절 이하 또는 영문·숫자 3자 이하, 중간 = 한글 3음절 또는 영문·
    숫자 4–5자, 김 = 그 이상. 섞인 표기는 한글 음절 수 + 0.6 × 영문·숫자 글자 수로 환산해 2 이하·
    3 이하·그 위로 나눈다(순수 표기에서는 앞의 구간과 같다)."""
    hangul = sum(1 for ch in key if _char_class(ch) == "H")
    alnum = sum(1 for ch in key if _char_class(ch) in ("L", "D"))
    size = hangul + ALNUM_WEIGHT * alnum
    if size <= 2.0 + 1e-9:
        return LENGTH_SHORT
    if size <= 3.0 + 1e-9:
        return LENGTH_MID
    return LENGTH_LONG


def _judge(dist: Distinctiveness, piece: str, goods: frozenset[str]) -> TokenJudgement:
    return dist.judge(piece, goods or None, famous_exception=False)


def _weak(dist: Distinctiveness, piece: str, goods: frozenset[str]) -> bool:
    return _judge(dist, piece, goods).score < dist.theta


def analyze_notation(text: str, dist: Distinctiveness, brand_codes: frozenset[str]) -> dict:
    """표기 하나의 등록부 항목 — 붙여 쓴 꼴·조각·문자 종류·길이 구간, 그리고 "약한 표기" 여부:
    유명 예외를 뺀 식별력 판정으로 그 브랜드 자신의 업종(brand_codes)에서 조각(접미어 분리 뒤)이
    모두 약하면 약한 표기. 조각별 판정(점수·사유)을 함께 남긴다."""
    clean = normalize_text(text)
    key = "".join(split_pieces(clean))
    judged = [_judge(dist, piece, brand_codes)
              for piece in split_pieces(dist.split_goods_suffix(clean))]
    weak = bool(judged) and all(j.score < dist.theta for j in judged)
    return {"text": text, "key": key, "pieces": split_pieces(clean),
            "script": script_label(key), "length": length_class(key), "weak": weak,
            "judgements": [{"token": j.token, "score": j.score, "reasons": list(j.reasons)}
                           for j in judged]}


# ---- 등록부 ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Notation:
    text: str  # 표에 적힌 표기 그대로
    key: str
    pieces: tuple[str, ...]
    script: str
    length: str
    weak: bool
    judgements: tuple[dict, ...] = ()


@dataclass(frozen=True)
class Mark:
    appno: str
    title: str | None
    kind: str | None  # 상표구분(도형복합·도형상표 …)
    role: str  # 이름 | 도형 | 다른 이름 | 브랜드 로고 | 제외
    auto_role: str  # overrides 적용 전 자동 역할
    source: str  # 유명 브랜드 수집 | 기존 수집(같은 출원인)
    image: str | None
    image_exists: bool
    codes: frozenset[str]
    classes: tuple[int, ...] = ()


@dataclass(frozen=True)
class Brand:
    name: str
    notations: tuple[Notation, ...]
    applicants: tuple[str, ...]
    applicant_keys: frozenset[str]  # 정규화 + 별칭 표 적용
    preset: str
    preset_label: str | None
    preset_codes: frozenset[str]
    evidence: str
    evidence_urls: tuple[str, ...]
    protection: str
    goods_codes: frozenset[str]  # 식별력 판정 맥락 — 브랜드 표장 유사군 합집합, 없으면 업종 세트
    goods_source: str
    marks: tuple[Mark, ...]

    @property
    def brand_marks(self) -> tuple[Mark, ...]:
        return tuple(mark for mark in self.marks if mark.role in BRAND_MARK_ROLES)

    @property
    def goods_sets(self) -> tuple[frozenset[str], ...]:
        """업종 겹침을 볼 유사군 집합들 — 브랜드 표장 하나하나와 업종 세트."""
        sets = [mark.codes for mark in self.brand_marks if mark.codes]
        if self.preset_codes:
            sets.append(self.preset_codes)
        return tuple(sets)


@dataclass(frozen=True)
class Registry:
    version: str
    brands: tuple[Brand, ...]
    sources: Mapping = field(default_factory=dict)

    def brand(self, name: str) -> Brand | None:
        return next((brand for brand in self.brands if brand.name == name), None)

    @property
    def applicant_keys(self) -> frozenset[str]:
        return frozenset(key for brand in self.brands for key in brand.applicant_keys)


def read_brand_table(path: Path = DEFAULT_BRANDS_PATH) -> list[dict]:
    """famous_brands.txt 의 [브랜드] 표 — 행마다 {notations, applicants, preset, evidence, urls}.
    표기·출원인은 ' / ' 로 이은 것을 나눈다(표에 있는 그대로, 새 표기를 지어내지 않는다)."""
    rows: list[dict] = []
    section: str | None = None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = _INLINE_COMMENT.sub("", line).strip()
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue
        if section != BRAND_SECTION:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 4 or not all(cells[:3]):
            raise ValueError(f"[브랜드] 행은 '브랜드 | 출원인명 | 업종 | 선정 근거' 입니다: {line}")
        evidence = " | ".join(cells[3:])
        rows.append({
            "notations": [part.strip() for part in cells[0].split(" / ") if part.strip()],
            "applicants": [part.strip() for part in cells[1].split(" / ") if part.strip()],
            "preset": cells[2], "evidence": evidence, "urls": _URL.findall(evidence)})
    return rows


def _latin_words(text: str) -> str:
    text = _TITLE_DROP.sub("", str(text or "").lower())
    return " ".join(re.sub(r"[^0-9a-z가-힣]+", " ", text).split())


def title_has_notation(title: str | None, notations: Iterable[str]) -> bool:
    """상표명에 브랜드 표기가 들어 있는가 — 수집 때의 규칙(collect_pipeline.title_has_brand)과
    같다: 한글 표기는 공백·기호를 뗀 부분 일치, 영문 표기는 소문자·아포스트로피·하이픈 제거 뒤 단어
    경계 일치('Nice to CU' ⊃ 'cu', 'cupon' ⊅ 'cu')."""
    words = _latin_words(title or "")
    compact = words.replace(" ", "")
    for name in notations:
        if _HANGUL.search(name):
            key = _latin_words(name).replace(" ", "")
            if key and key in compact:
                return True
        else:
            key = _latin_words(name)
            if key and re.search(rf"(?<![0-9a-z]){re.escape(key)}(?![0-9a-z])", words):
                return True
    return False


def auto_role(title: str | None, notations: Iterable[str]) -> str:
    """표장 역할(자동) — 상표명에 브랜드 표기가 있으면 "이름", 상표명이 없으면 "도형", 그 밖은
    "다른 이름"."""
    if not (title or "").strip():
        return ROLE_FIGURE
    return ROLE_NAME if title_has_notation(title, notations) else ROLE_OTHER


def load_overrides(path: Path = DEFAULT_OVERRIDES_PATH) -> dict:
    """사람이 정한 값 — {"brands": {브랜드: {"protection": …}}, "marks": {출원번호: {"role": …}}}.
    파일이 없으면 빈 틀. 모르는 값은 ValueError."""
    if not Path(path).exists():
        return {"version": OVERRIDES_VERSION, "brands": {}, "marks": {}}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != OVERRIDES_VERSION:
        raise ValueError(f"famous_registry_overrides: version 은 {OVERRIDES_VERSION} 여야 합니다")
    for name, item in (data.get("brands") or {}).items():
        protection = item.get("protection")
        if protection is not None and protection not in PROTECTIONS:
            raise ValueError(f"overrides: {name} 의 보호 범위는 {PROTECTIONS} 중 하나여야 합니다")
    for appno, item in (data.get("marks") or {}).items():
        if item.get("role") not in OVERRIDE_ROLES:
            raise ValueError(f"overrides: {appno} 의 역할은 {OVERRIDE_ROLES} 중 하나여야 합니다")
    return {"version": data["version"], "brands": dict(data.get("brands") or {}),
            "marks": dict(data.get("marks") or {})}


def _record_title(record: dict) -> str | None:
    parts = [str(record.get(key) or "").strip() for key in ("상표한글명", "상표영문명")]
    title = " ".join(part for part in parts if part)
    return title or None


def build_registry(
    rows: list[dict], *, plan_records: list[dict], db_records: list[dict],
    preset_codes: Mapping[str, Iterable[str]], preset_labels: Mapping[str, str],
    dist: Distinctiveness, applicant_keys: Callable[[str], frozenset[str]],
    overrides: dict | None = None, image_exists: Callable[[str], bool] | None = None,
    sources: Mapping | None = None,
) -> Registry:
    """[브랜드] 표(rows)·수집 계획 기록(plan_records: 출원번호 → 브랜드)·DB 메타데이터로 등록부를
    만든다. 브랜드의 DB 표장 = 계획 기록의 그 브랜드 표장 + 같은 출원인(별칭 표 적용)의 그 밖의
    DB 표장(기존 수집). 역할은 자동(auto_role) 뒤 overrides("브랜드 로고" 확정·"제외")로 덮는다."""
    overrides = overrides or {"brands": {}, "marks": {}}
    by_appno = {str(record["출원번호"]): record for record in db_records}
    planned: dict[str, list[str]] = {}
    for record in plan_records:
        planned.setdefault(record["브랜드"], []).append(str(record["출원번호"]))
    planned_all = {appno for items in planned.values() for appno in items}
    owner_of: dict[str, str] = {}
    brand_rows = []
    for row in rows:
        name = row["notations"][0]
        keys = frozenset(key for text in row["applicants"] for key in applicant_keys(text))
        for key in keys:
            if owner_of.setdefault(key, name) != name:
                raise ValueError(f"출원인 {key} 이 두 브랜드({owner_of[key]}, {name})에 있습니다")
        brand_rows.append((name, row, keys))
    extra: dict[str, list[str]] = {}
    for record in db_records:
        appno = str(record["출원번호"])
        if appno in planned_all:
            continue
        for key in applicant_keys(str(record.get("출원인") or "")):
            if key in owner_of:
                extra.setdefault(owner_of[key], []).append(appno)
                break
    brands: list[Brand] = []
    for name, row, keys in brand_rows:
        marks: list[Mark] = []
        listed = [(appno, SOURCE_FAMOUS) for appno in planned.get(name, [])]
        listed += [(appno, SOURCE_EXISTING) for appno in sorted(extra.get(name, []))]
        for appno, source in listed:
            record = by_appno.get(appno)
            if record is None:
                raise ValueError(f"계획 기록의 출원번호가 DB 에 없습니다: {appno}")
            title = _record_title(record)
            automatic = auto_role(title, row["notations"])
            role = (overrides["marks"].get(appno) or {}).get("role") or automatic
            image = record.get("이미지파일")
            marks.append(Mark(
                appno=appno, title=title, kind=record.get("상표구분"), role=role,
                auto_role=automatic, source=source, image=image,
                image_exists=bool(image) and (image_exists(image) if image_exists else True),
                codes=normalize_codes(record.get("유사군") or ()),
                classes=tuple(sorted(int(c) for c in record.get("류") or ()))))
        own = frozenset(code for mark in marks if mark.role in BRAND_MARK_ROLES
                        for code in mark.codes)
        preset = frozenset(normalize_codes(preset_codes.get(row["preset"]) or ()))
        goods_codes, goods_source = (own, "브랜드 표장") if own else (preset, "업종 세트")
        notations = tuple(
            Notation(text=item["text"], key=item["key"], pieces=tuple(item["pieces"]),
                     script=item["script"], length=item["length"], weak=item["weak"],
                     judgements=tuple(item["judgements"]))
            for item in (analyze_notation(text, dist, goods_codes) for text in row["notations"]))
        protection = (overrides["brands"].get(name) or {}).get("protection") or PROTECT_ANY
        brands.append(Brand(
            name=name, notations=notations, applicants=tuple(row["applicants"]),
            applicant_keys=keys, preset=row["preset"],
            preset_label=preset_labels.get(row["preset"]), preset_codes=preset,
            evidence=row["evidence"], evidence_urls=tuple(row["urls"]), protection=protection,
            goods_codes=goods_codes, goods_source=goods_source, marks=tuple(marks)))
    unknown = sorted(set(overrides["brands"]) - {brand.name for brand in brands})
    if unknown:
        raise ValueError(f"overrides 의 브랜드가 등록부에 없습니다: {unknown}")
    known = {mark.appno for brand in brands for mark in brand.marks}
    unknown = sorted(set(overrides["marks"]) - known)
    if unknown:
        raise ValueError(f"overrides 의 출원번호가 등록부에 없습니다: {unknown}")
    return Registry(version=REGISTRY_VERSION, brands=tuple(brands), sources=dict(sources or {}))


def registry_to_json(registry: Registry) -> dict:
    """등록부 → JSON(dict). load_registry 가 그대로 되읽는다."""
    brands = []
    for brand in registry.brands:
        counts: dict[str, int] = {}
        for mark in brand.marks:
            counts[mark.role] = counts.get(mark.role, 0) + 1
        brands.append({
            "name": brand.name,
            "notations": [{"text": n.text, "key": n.key, "pieces": list(n.pieces),
                           "script": n.script, "length": n.length, "weak": n.weak,
                           "judgements": list(n.judgements)} for n in brand.notations],
            "applicants": list(brand.applicants),
            "applicant_keys": sorted(brand.applicant_keys),
            "industry": {"preset": brand.preset, "label": brand.preset_label,
                         "codes": sorted(brand.preset_codes)},
            "evidence": {"text": brand.evidence, "urls": list(brand.evidence_urls)},
            "protection": brand.protection,
            "goods": {"source": brand.goods_source, "codes": sorted(brand.goods_codes)},
            "role_counts": counts,
            "marks": [{"appno": m.appno, "title": m.title, "kind": m.kind, "role": m.role,
                       "auto_role": m.auto_role, "source": m.source, "image": m.image,
                       "image_exists": m.image_exists, "codes": sorted(m.codes),
                       "classes": list(m.classes)} for m in brand.marks]})
    return {"version": registry.version, "sources": dict(registry.sources), "brands": brands}


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> Registry:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != REGISTRY_VERSION:
        raise ValueError(f"famous_registry: version 은 {REGISTRY_VERSION} 여야 합니다")
    brands = []
    for item in data["brands"]:
        if item["protection"] not in PROTECTIONS:
            raise ValueError(f"famous_registry: {item['name']} 의 보호 범위를 모릅니다")
        brands.append(Brand(
            name=item["name"],
            notations=tuple(Notation(
                text=n["text"], key=n["key"], pieces=tuple(n["pieces"]), script=n["script"],
                length=n["length"], weak=bool(n["weak"]),
                judgements=tuple(n.get("judgements") or ())) for n in item["notations"]),
            applicants=tuple(item["applicants"]),
            applicant_keys=frozenset(item["applicant_keys"]),
            preset=item["industry"]["preset"], preset_label=item["industry"].get("label"),
            preset_codes=frozenset(item["industry"]["codes"]),
            evidence=item["evidence"]["text"], evidence_urls=tuple(item["evidence"]["urls"]),
            protection=item["protection"], goods_codes=frozenset(item["goods"]["codes"]),
            goods_source=item["goods"]["source"],
            marks=tuple(Mark(
                appno=m["appno"], title=m.get("title"), kind=m.get("kind"), role=m["role"],
                auto_role=m.get("auto_role", m["role"]), source=m.get("source", SOURCE_FAMOUS),
                image=m.get("image"), image_exists=bool(m.get("image_exists")),
                codes=frozenset(m.get("codes") or ()),
                classes=tuple(m.get("classes") or ())) for m in item["marks"])))
    return Registry(version=data["version"], brands=tuple(brands),
                    sources=dict(data.get("sources") or {}))


# ---- 기준값 ------------------------------------------------------------------------------------

def _per_length(value: float | None = None) -> dict[str, float | None]:
    return {length: value for length in LENGTHS}


@dataclass(frozen=True)
class Thresholds:
    """기준값. None 은 그 경로를 쓰지 않는다는 뜻. 약한 기준은 표기의 길이 구간별."""

    strong_sound: float | None = STRONG_SOUND
    strong_spelling: float | None = None
    weak_sound: Mapping[str, float | None] = field(default_factory=_per_length)
    weak_spelling: Mapping[str, float | None] = field(default_factory=_per_length)
    contain_other: bool = True  # 품음-기타를 약한 일치로 둘지(결정 대기 — 따로 센다)

    def to_dict(self) -> dict:
        return {"strong_sound": self.strong_sound, "strong_spelling": self.strong_spelling,
                "weak_sound": dict(self.weak_sound), "weak_spelling": dict(self.weak_spelling),
                "contain_other": self.contain_other}

    @classmethod
    def from_dict(cls, data: Mapping) -> "Thresholds":
        return cls(strong_sound=data.get("strong_sound", STRONG_SOUND),
                   strong_spelling=data.get("strong_spelling"),
                   weak_sound={**_per_length(), **(data.get("weak_sound") or {})},
                   weak_spelling={**_per_length(), **(data.get("weak_spelling") or {})},
                   contain_other=bool(data.get("contain_other", True)))


def default_goods_floor() -> float:
    """업종 겹침 기준 — 서비스 기본 계수 JSON 의 결합 하한 coupling.floors.x4(0.0252)."""
    from src.model import risk_model as rm

    return float(rm.load_model()["coupling"]["floors"]["x4"])


# ---- 질의 정리 ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class PreparedQuery:
    text: str  # 정리한 이름(접미어 분리 뒤)
    words: tuple[str, ...]  # 낱말의 붙여 쓴 꼴
    word_pieces: tuple[tuple[str, ...], ...]  # 낱말마다 조각
    goods: frozenset[str]

    @property
    def pieces(self) -> tuple[str, ...]:
        return tuple(piece for pieces in self.word_pieces for piece in pieces)


def prepare_query(name: object, goods_codes: Iterable[str] | str | None,
                  dist: Distinctiveness) -> PreparedQuery:
    """이름 정리 — clean_input_name·소문자 → 엔진의 상품 접미어 분리(split_goods_suffix:
    "스타벅스커피" → "스타벅스 커피") → 공백·기호로 낱말. 식별력 필터는 거치지 않는다."""
    text = dist.split_goods_suffix(normalize_text(name))
    words: list[str] = []
    word_pieces: list[tuple[str, ...]] = []
    for raw in _clean_chars(text).split():
        pieces = tuple(_tokenize(raw))
        if pieces:
            words.append("".join(pieces))
            word_pieces.append(pieces)
    return PreparedQuery(text=text, words=tuple(words), word_pieces=tuple(word_pieces),
                         goods=normalize_codes(goods_codes))


def _bundles(words: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for start in range(len(words)):
        key = ""
        for word in words[start:start + MAX_BUNDLE_WORDS]:
            key += word
            if key not in out:
                out.append(key)
    return out


# ---- 근거(기준값 적용 전) ----------------------------------------------------------------------

@dataclass(frozen=True)
class Evidence:
    """브랜드 표기 하나에 대한 근거 — 기준값을 적용하기 전의 값(기준을 바꿔 가며 다시 판정)."""

    notation: str
    key: str
    length: str
    weak_notation: bool
    exact: bool = False
    contain: str | None = None  # "설명" | "기타"
    contain_word: str | None = None
    contain_rest: str | None = None
    sound: float = 0.0
    sound_unit: str | None = None
    spelling: float = 0.0
    spelling_unit: str | None = None
    weak_use: str | None = None  # 약한 표기: WEAK_USE_ALONE | WEAK_USE_WITH_OTHERS
    descriptive: bool = False  # 질의 업종에서 이 표기가 식별력 없는 말

    @property
    def any_signal(self) -> bool:
        return bool(self.exact or self.contain or self.weak_use or self.sound > 0.0
                    or self.spelling > 0.0)


@dataclass(frozen=True)
class BrandEvidence:
    brand: str
    protection: str
    overlap: bool | None  # 질의 업종과 브랜드 업종의 겹침(질의 업종이 없으면 None)
    overlap_value: float | None
    items: tuple[Evidence, ...]


def _overlap(goods: frozenset[str], brand: Brand, goods_floor: float
             ) -> tuple[bool | None, float | None]:
    if not goods:
        return None, None
    value = max((goods_similarity(goods, codes) for codes in brand.goods_sets), default=0.0)
    return value >= goods_floor, round(value, 4)


def _plain_checker(dist: Distinctiveness, query_goods: frozenset[str],
                   brand_codes: frozenset[str]) -> Callable[[str], bool]:
    """식별력 없는 말 — 붙여 쓴 글자열의 조각이 모두 약한가(모듈 설명의 맥락 규칙)."""
    memo: dict[str, bool] = {}

    def piece_plain(piece: str) -> bool:
        if query_goods:
            return _weak(dist, piece, query_goods) or _weak(dist, piece, brand_codes)
        return _weak(dist, piece, brand_codes) or piece in dist.goods_names

    def plain(text: str) -> bool:
        if text not in memo:
            pieces = _tokenize(text)
            memo[text] = bool(pieces) and all(piece_plain(piece) for piece in pieces)
        return memo[text]

    return plain


def _goods_word_checker(dist: Distinctiveness, query_goods: frozenset[str],
                        brand_codes: frozenset[str]) -> Callable[[str], bool]:
    """상품·업종을 나타내는 말 — 보통명칭(1호)·성질표시(3호)로 약하다고 판정되는 말이거나 상품
    접미어 사전에 있는 말."""
    contexts = [codes for codes in (query_goods, brand_codes) if codes]

    def goods_word(piece: str) -> bool:
        if piece in dist.goods_names:
            return True
        for codes in contexts:
            judged = _judge(dist, piece, codes)
            if judged.score < dist.theta and any(
                    reason.startswith(GOODS_WORD_REASONS) for reason in judged.reasons):
                return True
        return False

    return goods_word


def _occurrences(pieces: tuple[str, ...], key: str) -> list[tuple[int, int]]:
    """조각 열에서 이어 붙이면 key 와 같은 구간 [start, stop) 들."""
    found: list[tuple[int, int]] = []
    for start in range(len(pieces)):
        joined = ""
        for stop in range(start, len(pieces)):
            joined += pieces[stop]
            if len(joined) >= len(key):
                break
        if joined == key:
            found.append((start, stop + 1))
    return found


def _weak_use(query: PreparedQuery, notation: Notation,
              goods_word: Callable[[str], bool]) -> str | None:
    """약한 표기의 쓰임 — 질의 조각 가운데 표기와 같은 구간을 찾아, 나머지가 모두 상품·업종을
    나타내는 말이면 "단독", 다른 말이 있으면 "다른 말과 함께". 표기가 없으면 None."""
    pieces = query.pieces
    best: str | None = None
    for start, stop in _occurrences(pieces, notation.key):
        rest = pieces[:start] + pieces[stop:]
        if all(goods_word(piece) for piece in rest):
            return WEAK_USE_ALONE
        best = WEAK_USE_WITH_OTHERS
    return best


def _masked(query: PreparedQuery, notations: Iterable[Notation]) -> PreparedQuery:
    """질의에서 그 브랜드의 약한 표기 조각을 가린 것 — 가린 조각은 그 브랜드의 다른 표기와
    견주지 않는다(약한 표기의 쓰임은 _weak_use 가 정한다). 가릴 것이 없으면 질의 그대로."""
    pieces = query.pieces
    hidden: set[int] = set()
    for notation in notations:
        if notation.weak and notation.key:
            for start, stop in _occurrences(pieces, notation.key):
                hidden.update(range(start, stop))
    if not hidden:
        return query
    words: list[str] = []
    word_pieces: list[tuple[str, ...]] = []
    index = 0
    for group in query.word_pieces:
        kept = tuple(piece for offset, piece in enumerate(group) if index + offset not in hidden)
        index += len(group)
        if kept:
            words.append("".join(kept))
            word_pieces.append(kept)
    return PreparedQuery(text=query.text, words=tuple(words), word_pieces=tuple(word_pieces),
                         goods=query.goods)


def _segments(query: PreparedQuery, plain: Callable[[str], bool]) -> list[str]:
    """한 낱말의 앞·뒤 구간으로서 나머지가 식별력 없는 말인 것."""
    out: list[str] = []
    for word in query.words:
        for cut in range(1, len(word)):
            head, tail = word[:cut], word[cut:]
            if plain(tail) and head not in out:
                out.append(head)
            if plain(head) and tail not in out:
                out.append(tail)
    return out


def _notation_evidence(query: PreparedQuery, notation: Notation, bundles: list[str],
                       segments: list[str], plain: Callable[[str], bool],
                       goods_word: Callable[[str], bool], dist: Distinctiveness, *,
                       similarity: bool, hidden: frozenset[str] = frozenset()) -> Evidence:
    """표기 하나의 근거. hidden = 그 브랜드의 약한 표기(붙여 쓴 꼴) — 이것과 같은 단위는 견주지
    않는다(낱말의 앞·뒤 구간이 약한 표기와 같은 경우: "bbqs" 의 bbq)."""
    base = dict(notation=notation.text, key=notation.key, length=notation.length,
                weak_notation=notation.weak)
    if not notation.key:
        return Evidence(**base)
    if notation.weak:  # 약한 표기는 (가)만 — 쓰임을 따로 본다
        return Evidence(**base, weak_use=_weak_use(query, notation, goods_word))
    key = notation.key
    exact = key in bundles
    contain = word_hit = rest_hit = None
    for word in query.words:
        if word == key:
            continue
        rests = []
        if word.startswith(key):
            rests.append(word[len(key):])
        if word.endswith(key):
            rests.append(word[:-len(key)])
        for rest in rests:
            kind = "설명" if plain(rest) else "기타"
            if kind == "기타" and notation.length == LENGTH_SHORT:
                continue  # 짧은 표기는 품음-설명만 인정
            if contain is None or (kind == "설명" and contain == "기타"):
                contain, word_hit, rest_hit = kind, word, rest
    sound = spelling = 0.0
    sound_unit = spelling_unit = None
    if similarity:
        units = list(bundles)
        if notation.length != LENGTH_SHORT:
            units += [segment for segment in segments if segment not in units]
        for unit in units:
            if unit in hidden:
                continue
            score = phonetic_similarity(unit, key)
            if score > sound:
                sound, sound_unit = score, unit
            if script_label(unit) == notation.script:
                score = orthographic_similarity(unit, key)
                if score > spelling:
                    spelling, spelling_unit = score, unit
    descriptive = bool(query.goods) and bool(notation.pieces) and all(
        _weak(dist, piece, query.goods) for piece in notation.pieces)
    return Evidence(**base, exact=exact, contain=contain, contain_word=word_hit,
                    contain_rest=rest_hit, sound=round(sound, 4), sound_unit=sound_unit,
                    spelling=round(spelling, 4), spelling_unit=spelling_unit,
                    descriptive=descriptive)


def collect_evidence(query: PreparedQuery, registry: Registry, dist: Distinctiveness,
                     goods_floor: float, *, similarity: bool = True) -> list[BrandEvidence]:
    """질의와 등록부의 모든 브랜드 표기 사이의 근거. similarity=False 면 (가)(나)만(이미지 속 글자).
    근거가 하나도 없는 브랜드도 돌려준다(기준값 적용은 decide)."""
    all_bundles = _bundles(query.words)
    out: list[BrandEvidence] = []
    for brand in registry.brands:
        plain = _plain_checker(dist, query.goods, brand.goods_codes)
        goods_word = _goods_word_checker(dist, query.goods, brand.goods_codes)
        rest = _masked(query, brand.notations)  # 약한 표기 조각을 가린 질의(다른 표기용)
        bundles = all_bundles if rest is query else _bundles(rest.words)
        needs_segments = similarity and any(
            not n.weak and n.length != LENGTH_SHORT for n in brand.notations)
        segments = _segments(rest, plain) if needs_segments else []
        overlap, value = _overlap(query.goods, brand, goods_floor)
        hidden = frozenset(n.key for n in brand.notations if n.weak and n.key)
        items = tuple(
            _notation_evidence(query if notation.weak else rest, notation, bundles, segments,
                               plain, goods_word, dist, similarity=similarity, hidden=hidden)
            for notation in brand.notations)
        out.append(BrandEvidence(brand=brand.name, protection=brand.protection,
                                 overlap=overlap, overlap_value=value, items=items))
    return out


# ---- 판정 --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class BrandMatch:
    brand: str
    level: str  # 강함 | 약함 | 설명적 사용 안내
    path: str  # 같음 | 품음-설명 | 품음-기타 | 소리 | 철자
    notation: str
    score: float
    floor: str | None  # 이 일치가 주는 전체 등급 바닥(없으면 None)
    protection: str
    overlap: bool | None
    pending: bool = False  # 품음-기타(결정 대기)
    note: str = ""
    basis: str = BASIS_NAME

    @property
    def order(self) -> tuple[int, int, float]:
        return (_LEVEL_RANK[self.level], _PATH_RANK[self.path], self.score)


@dataclass(frozen=True)
class FamousResult:
    matches: tuple[BrandMatch, ...]  # 브랜드마다 가장 강한 일치 하나, 강한 것부터
    strongest: BrandMatch | None
    floor: str | None  # 전체 등급 바닥(위험 | 검토 권장 | None)
    basis: str


def _floor(level: str, protection: str, overlap: bool | None) -> str | None:
    if level == LEVEL_NOTICE:
        return None
    near_and_different = protection == PROTECT_NEAR and overlap is False
    if level == LEVEL_STRONG:
        return GRADE_REVIEW if near_and_different else GRADE_RISK
    return None if near_and_different else GRADE_REVIEW


def _candidates(item: Evidence, overlap: bool | None, thresholds: Thresholds
                ) -> list[tuple[str, str, float, bool, str]]:
    """표기 하나에서 나오는 (수준, 경로, 점수, 결정 대기, 메모) 후보."""
    if item.weak_notation:
        if item.weak_use == WEAK_USE_ALONE:
            level = LEVEL_NOTICE if overlap is False else LEVEL_STRONG
            note = "약한 표기 — 업종이 다름" if overlap is False else "약한 표기 — 그 표기 하나뿐"
            return [(level, PATH_EXACT, 1.0, False, note)]
        if item.weak_use == WEAK_USE_WITH_OTHERS:
            return [(LEVEL_NOTICE, PATH_EXACT, 1.0, False, "약한 표기 — 다른 말과 함께")]
        return []
    out: list[tuple[str, str, float, bool, str]] = []
    if item.exact:
        out.append((LEVEL_STRONG, PATH_EXACT, 1.0, False, ""))
    if item.contain == "설명":
        out.append((LEVEL_STRONG, PATH_CONTAIN_DESC, 1.0, False,
                    f"{item.contain_word} = 표기 + {item.contain_rest}"))
    if thresholds.strong_sound is not None and item.sound >= thresholds.strong_sound:
        out.append((LEVEL_STRONG, PATH_SOUND, item.sound, False, item.sound_unit or ""))
    if thresholds.strong_spelling is not None and item.spelling >= thresholds.strong_spelling:
        out.append((LEVEL_STRONG, PATH_SPELLING, item.spelling, False, item.spelling_unit or ""))
    weak_sound = thresholds.weak_sound.get(item.length)
    if weak_sound is not None and item.sound >= weak_sound:
        out.append((LEVEL_WEAK, PATH_SOUND, item.sound, False, item.sound_unit or ""))
    weak_spelling = thresholds.weak_spelling.get(item.length)
    if weak_spelling is not None and item.spelling >= weak_spelling:
        out.append((LEVEL_WEAK, PATH_SPELLING, item.spelling, False, item.spelling_unit or ""))
    if item.contain == "기타" and thresholds.contain_other:
        out.append((LEVEL_WEAK, PATH_CONTAIN_OTHER, 1.0, True,
                    f"{item.contain_word} = 표기 + {item.contain_rest}"))
    if item.descriptive and overlap is False:  # 그 밖의 설명적 사용
        out = [(LEVEL_NOTICE, path, score, pending, "질의 업종에서 식별력 없는 말 — 업종이 다름")
               for _, path, score, pending, _ in out]
    return out


def decide(evidence: Iterable[BrandEvidence], thresholds: Thresholds, *,
           basis: str = BASIS_NAME) -> FamousResult:
    """근거에 기준값을 적용 — 브랜드마다 가장 강한 일치, 그중 가장 강한 것, 전체 등급 바닥."""
    matches: list[BrandMatch] = []
    for brand in evidence:
        best: BrandMatch | None = None
        for item in brand.items:
            for level, path, score, pending, note in _candidates(item, brand.overlap,
                                                                 thresholds):
                match = BrandMatch(
                    brand=brand.brand, level=level, path=path, notation=item.notation,
                    score=round(float(score), 4),
                    floor=_floor(level, brand.protection, brand.overlap),
                    protection=brand.protection, overlap=brand.overlap, pending=pending,
                    note=note, basis=basis)
                if best is None or match.order > best.order:
                    best = match
        if best is not None:
            matches.append(best)
    matches.sort(key=lambda match: match.order, reverse=True)
    floors = [match.floor for match in matches if match.floor]
    floor = max(floors, key=GRADES.index) if floors else None
    return FamousResult(matches=tuple(matches), strongest=matches[0] if matches else None,
                        floor=floor, basis=basis)


def check_famous(
    name: object, goods_codes: Iterable[str] | str | None, registry: Registry,
    thresholds: Thresholds, *, dist: Distinctiveness | None = None,
    goods_floor: float | None = None, ocr_text: object = None,
) -> FamousResult:
    """유명 상표 일치 판정. 질의 이름이 없고 이미지에서 읽은 글자(ocr_text — OCR 제안 상표명)가
    있으면 그 글자로 (가)(나)만 판정해 "이미지 속 글자 기준"으로 표시한다. 이름도 글자도 없으면
    빈 결과."""
    dist = dist or load_distinctiveness()
    floor = default_goods_floor() if goods_floor is None else float(goods_floor)
    if normalize_text(name):
        query = prepare_query(name, goods_codes, dist)
        return decide(collect_evidence(query, registry, dist, floor), thresholds)
    if normalize_text(ocr_text):
        query = prepare_query(ocr_text, goods_codes, dist)
        return decide(collect_evidence(query, registry, dist, floor, similarity=False),
                      thresholds, basis=BASIS_OCR)
    return FamousResult(matches=(), strongest=None, floor=None, basis=BASIS_NAME)
