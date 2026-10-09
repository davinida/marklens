"""식별력·요부 v0 — 상표명 토큰마다 식별력 점수(0 약함 ~ 1 강함)를 매기고 요부(식별력 있는 부분)를
고른다. X1·X2 문자 외관·X3 가 `extra_generic` 으로 넘겨받을 "식별력 없는 토큰"을 공급하는 필터다
(작업가이드 다빈-3). 축 함수가 아니므로 공통-2 규약(파일 없음)은 적용하지 않고, goods_map 처럼
집계 파일(`shared/distinctiveness/token_stats.json`)을 적재한다. 학습 없음, KIPRIS 호출 없음.

판례 근거 → v0 반영
    - 요부 판단 요소(대법원 2015후1690): 표장의 일부가 수요자에게 강한 인상을 주거나 전체에서 높은
      비중을 차지하는지, 그 부분이 주지·저명하거나 식별력이 없는지 등을 종합한다.
      → v0 는 "식별력이 없는 부분"만 점수로 걸러낸다. 강한 인상·전체 비중은 미반영(한계).
    - 다수 등록·출원공고(대법원 2017후2697): 같은 부분이 다수의 등록·출원공고 상표에 쓰였으면 그
      부분은 식별력이 약하다. 판단 요소는 등록 수, 출원인 수, 그 부분의 본질적 식별력, 지정상품과의
      관계. → 토큰별 서로 다른 출원인 수 A·등장 수 N(심판 목록 42,474건 + DB 1,100건 제목 집계),
      wordfreq 빈도(본질적 식별력), 지정상품 유사군(1호 판정의 상품 상대성)을 점수에 넣는다.
    - 전부 식별력이 없으면 전체로 대비(대법원 2000후2453) → `has_distinctive_part` False 인 이름은
      토큰을 제거하지 않고 전체 문자열로 대비한다(`pair_generic` 이 그 이름의 토큰을 넘기지 않는다).
    - 상표법 33조 1항: 1호 보통명칭(goods_codes 가 있으면 그 류·유사군의 고시 명칭과 일치할 때만,
      없으면 전역 고시 단일 명칭 일치), 4호 현저한 지리적 명칭(X1 지명표 34 + 시·군·구 목록),
      5호 흔한 성(상위 30 + "~네/~가네/~씨네"), 6호 간단하고 흔한 표장(영문 2자 이하·숫자 2자 이하·
      한글 1음절) → 0점. 3호 기술적 표장(산지·품질·원재료·효능·용도·수량·형상·가격·생산방법·
      가공방법·사용방법·시기를 보통으로 사용하는 방법으로 표시)은 `shared/distinctiveness/
      descriptive_terms.json`(사람이 편집·승인)을 `DESCRIPTIVE_TERMS` 로 적재한다 — 절대적 기술
      표장(Best·No1·Super·최고 … 지정상품 불문)은 0점, 상대적 표장은 지정상품의 류가 항목의
      `classes` 안이면 0점·류가 다르면 영향 없음·상품 미상이면 0.5 상한. 판단 기준·후보 생성·승인
      절차는 docs/MarkLens_식별력_설계.md §3-3.

점수 구성(토큰 하나)
    유명 브랜드(브랜드표 101 + famous_brands.txt) → 1.0 고정.
    33조 1항 유형(1·3·4·5·6호)에 해당 → 0.0.
    그 외 → 본질적 식별력 × 다수 등록 계수.
        본질적 식별력 = 1 − 0.5 × clamp((zipf − 3.0) / (5.5 − 3.0), 0, 1)  (일반어 0.5 하한, 조어 1)
        다수 등록 계수 = 1 − min(1, A/θ_A) × min(1, N/θ_N)                  (A·N 둘 다 커야 0)
    요부 후보 = 점수 ≥ θ(0.5) 인 토큰. 하나도 없으면 요부 없음(전체 대비).

알려진 한계(v0): 3호 기술적 표장 미반영(후속), 강한 인상·전체 비중·결합으로 인한 새 관념 미반영,
A·N 은 등록원부가 아니라 심판 목록 표본이라 실제보다 작다, 영문 고시 명칭 미대조, 한자 토큰은
버린다.

    token_score("커피", {"G0301"})     # 0.0 — 커피 유사군이면 1호 보통명칭(화장품 유사군이면 아님)
    salient_tokens("스타벅스 커피")      # [("스타벅스", 1.0)] — 유명 브랜드 예외
    has_distinctive_part("GATE")        # 토큰 점수에 따라 False 면 전체 대비
"""

from __future__ import annotations

import functools
import json
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .korean_brands import KOREAN_BRAND_ROMANIZATION, KOREAN_PLACE_ROMANIZATION
from .x1_phonetic import normalize_name
from .x3_semantic import token_zipf

__all__ = [
    "Distinctiveness", "TokenJudgement", "DescriptiveTerm", "load_distinctiveness", "token_score",
    "salient_tokens", "weak_tokens", "has_distinctive_part", "pair_generic", "famous_tokens",
    "goods_index", "read_descriptive_terms", "validate_descriptive_terms", "unapproved_terms",
    "DESCRIPTIVE_TERMS", "DESCRIPTIVE_KINDS", "THETA", "THETA_A", "THETA_N",
]

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DIR = REPO_ROOT / "shared" / "distinctiveness"
DEFAULT_STATS_PATH = DEFAULT_DIR / "token_stats.json"
DEFAULT_FAMOUS_PATH = REPO_ROOT / "shared" / "famous_brands.txt"
ENV_STATS_PATH = "MARKLENS_DISTINCTIVENESS_STATS"

# ---- 설계 상수 (검토·조정 대상) ----------------------------------------------------------------
THETA = 0.5  # 요부 후보 임계: 점수 ≥ θ 면 요부 후보, < θ 면 식별력 없는 토큰(extra_generic 으로)
THETA_A = 10  # 다수 등록: 서로 다른 출원인 수 포화점(5/10/20 비교는 build 보고서)
THETA_N = 20  # 다수 등록: 등장 수 포화점(θ_A 의 2배)
ZIPF_LOW = 3.0  # 이 이하 빈도(희귀어·조어)는 본질적 식별력 1
ZIPF_HIGH = 5.5  # 이 이상(아주 흔한 일반어)은 0.5 하한
INTRINSIC_FLOOR = 0.5
MIN_TOKEN_CHARS = 2  # 1글자 토큰은 6호(간단 표장)로 0점이라 집계 대상에서도 뺀다

# ---- 3호 기술적 표장: shared/distinctiveness/descriptive_terms.json 적재(코드엔 로더·검증만) --
DESCRIPTIVE_KINDS: tuple[str, ...] = (
    "산지", "품질", "원재료", "효능", "용도", "수량", "형상", "가격", "생산방법", "가공방법",
    "사용방법", "시기",
)
DEFAULT_DESCRIPTIVE_PATH = DEFAULT_DIR / "descriptive_terms.json"
ENV_DESCRIPTIVE_PATH = "MARKLENS_DESCRIPTIVE_TERMS"
DESCRIPTIVE_UNKNOWN_SCORE = 0.5  # 상대적 기술 표장인데 지정상품을 모르면(또는 류 미지정) 점수 상한
NICE_CLASS_RANGE = range(1, 46)


@dataclass(frozen=True, slots=True)
class DescriptiveTerm:
    """3호 항목. kind 는 DESCRIPTIVE_KINDS 중 하나, absolute 면 지정상품 불문 0점(Best·No1·최고 …),
    아니면 classes(류)의 상품에서만 0점. approved 는 사람 승인 여부(미승인도 적용, 보고서에
    표시)."""

    kind: str
    absolute: bool = False
    classes: frozenset[int] | None = None
    note: str = ""
    approved: bool = False


def validate_descriptive_terms(data: dict) -> dict[str, DescriptiveTerm]:
    """JSON({"terms": {토큰: {kind, absolute, classes, note, approved}}}) → 항목 사전. 어긋나면
    ValueError.

    토큰은 X1 정규화 형태(소문자·공백 없는 단일 토큰)여야 한다.
    """
    terms = data.get("terms", data) if isinstance(data, dict) else None
    if not isinstance(terms, dict):
        raise ValueError("descriptive_terms: 'terms' 객체가 필요합니다")
    out: dict[str, DescriptiveTerm] = {}
    for token, item in terms.items():
        if not isinstance(item, dict):
            raise ValueError(f"descriptive_terms[{token!r}]: 객체가 아닙니다")
        if normalize_name(token) != [token]:
            raise ValueError(f"descriptive_terms[{token!r}]: 정규화 형태(소문자·공백 없는 단일 "
                             "토큰)가 아닙니다")
        missing = [key for key in ("kind", "absolute") if key not in item]
        if missing:
            raise ValueError(f"descriptive_terms[{token!r}]: 필수 필드 없음 {missing}")
        kind = item["kind"]
        if kind not in DESCRIPTIVE_KINDS:
            raise ValueError(f"descriptive_terms[{token!r}]: kind {kind!r} 는 "
                             f"{'|'.join(DESCRIPTIVE_KINDS)} 중 하나여야 합니다")
        absolute = item["absolute"]
        if not isinstance(absolute, bool):
            raise ValueError(f"descriptive_terms[{token!r}]: absolute 는 true/false")
        classes_raw = item.get("classes")
        classes: frozenset[int] | None = None
        if classes_raw is not None:
            if not isinstance(classes_raw, list) or not all(
                isinstance(c, int) and c in NICE_CLASS_RANGE for c in classes_raw
            ):
                raise ValueError(f"descriptive_terms[{token!r}]: classes 는 1~45 류 정수 "
                                 "목록이거나 null")
            classes = frozenset(classes_raw)
        note = item.get("note", "")
        approved = item.get("approved", False)
        if not isinstance(note, str) or not isinstance(approved, bool):
            raise ValueError(f"descriptive_terms[{token!r}]: note 는 문자열, approved 는 "
                             "true/false")
        out[token] = DescriptiveTerm(kind, absolute, classes, note, approved)
    return out


def resolve_descriptive_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get(ENV_DESCRIPTIVE_PATH, "").strip()
    return Path(env) if env else DEFAULT_DESCRIPTIVE_PATH


def read_descriptive_terms(
    path: str | os.PathLike[str] | None = None,
) -> dict[str, DescriptiveTerm]:
    """descriptive_terms.json → 항목 사전. 파일이 없으면 {}(3호 미적용)."""
    resolved = resolve_descriptive_path(path)
    if not resolved.exists():
        return {}
    return validate_descriptive_terms(json.loads(resolved.read_text(encoding="utf-8")))


def unapproved_terms(terms: dict[str, DescriptiveTerm]) -> list[str]:
    return sorted(token for token, term in terms.items() if not term.approved)


DESCRIPTIVE_TERMS: dict[str, DescriptiveTerm] = read_descriptive_terms()

# ---- 5호 흔한 성(통계청 2015 기준 상위 30) + 로마자(단어와 겹치지 않는 표기만) ---------
COMMON_SURNAMES: frozenset[str] = frozenset(
    "김 이 박 최 정 강 조 윤 장 임 한 오 서 신 권 황 안 송 전 홍 유 고 문 양 손 배 백 허 남 심"
    .split()
)
COMMON_SURNAMES_ROMAN: frozenset[str] = frozenset(
    "kim lee park choi jung jeong kang cho yoon yun jang lim im oh seo shin kwon hwang ahn jeon "
    "hong yoo yu ko mun yang sohn bae baek heo huh nam shim sim".split()
)
SURNAME_SUFFIXES: tuple[str, ...] = ("가네", "씨네", "네")

# ---- 4호 현저한 지리적 명칭: X1 지명표 34 + 시·도·시·군·구 + 널리 알려진 동·산·강·외국 지명 --
_PLACES_KO = """
서울 부산 대구 인천 광주 대전 울산 세종 경기 강원 충북 충남 전북 전남 경북 경남 제주 충청 전라 경상
수원 성남 의정부 안양 부천 광명 평택 동두천 안산 고양 과천 구리 남양주 오산 시흥 군포 의왕 하남 용인
파주 이천 안성 김포 화성 양주 포천 여주 춘천 원주 강릉 동해 태백 속초 삼척 청주 충주 제천 천안 공주
보령 아산 서산 논산 계룡 당진 전주 군산 익산 정읍 남원 김제 목포 여수 순천 나주 광양 포항 경주 김천
안동 구미 영주 영천 상주 문경 경산 창원 진주 통영 사천 김해 밀양 거제 양산 서귀포
연천 가평 양평 홍천 횡성 영월 평창 정선 철원 화천 양구 인제 고성 양양 보은 옥천 영동 증평 진천 괴산
음성 단양 금산 부여 서천 청양 홍성 예산 태안 완주 진안 무주 장수 임실 순창 고창 부안 담양 곡성 구례
고흥 보성 화순 장흥 강진 해남 영암 무안 함평 영광 장성 완도 진도 신안 군위 의성 청송 영양 영덕 청도
고령 성주 칠곡 예천 봉화 울진 울릉 의령 함안 창녕 남해 하동 산청 함양 거창 합천
종로 중구 용산 성동 광진 동대문 중랑 성북 강북 도봉 노원 은평 서대문 마포 양천 강서 구로 금천 영등포
동작 관악 서초 강남 송파 강동 영도 부산진 동래 해운대 사하 금정 연제 수영 사상 기장 수성 달서 달성
미추홀 연수 남동 부평 계양 강화 옹진 광산 유성 대덕 울주
홍대 이태원 명동 여의도 신촌 압구정 청담 잠실 건대 성수 가로수길 북촌 인사동 남대문 광화문 을지로
한남 연남 망원 한강 한라 백두 설악 지리산 금강 낙동 영산 섬진 독도 한국 대한민국 조선 한반도
파리 뉴욕 런던 도쿄 홍콩 하와이 발리 베를린 로마 밀라노 캘리포니아 텍사스 이탈리아 프랑스 일본 중국
미국 유럽 아시아 아프리카 북경 베이징 상하이 방콕 싱가포르 시드니 토론토 모스크바 마드리드 스위스
""".split()
_PLACES_EN = """
paris newyork london tokyo hongkong hawaii bali berlin roma rome milano milan california texas
italia italy france japan china usa america europe asia africa beijing shanghai bangkok singapore
sydney
toronto moscow madrid swiss switzerland korea jeju dokdo
""".split()
PLACE_NAMES: frozenset[str] = frozenset(
    _PLACES_KO + _PLACES_EN + list(KOREAN_PLACE_ROMANIZATION)
    + list(KOREAN_PLACE_ROMANIZATION.values())
)
PLACE_SUFFIXES: tuple[str, ...] = (
    "특별시", "광역시", "시", "군", "구", "도", "동", "읍", "면", "리",
)

# ---- 유명 브랜드 예외: famous_brands.txt 출원인명에서 상호 핵심 토큰을 뽑을 때 건너뛰는 토큰 --
_FAMOUS_SKIP: frozenset[str] = frozenset({
    "더", "인터", "인두스트리아", "바이에리셰", "가부시키가이샤", "데", "에스", "에이", "비", "씨",
    "브이", "엘엘씨", "인크", "코포레이션", "컴파니", "엘티디", "악티엔게젤샤프트", "테크놀로지스",
    "이노베이트", "말레띠에", "프로퍼티", "시스템스", "리테이링구", "디세노", "텍스틸", "모토렌",
    "베르케", "지도샤", "에프", "앤",
})

_HANGUL = ((0xAC00, 0xD7A3), (0x3131, 0x318E), (0x1100, 0x11FF))


def _script(token: str) -> str:
    """H(한글) / L(영문) / D(숫자) / O."""
    if not token:
        return "O"
    code = ord(token[0])
    if any(low <= code <= high for low, high in _HANGUL):
        return "H"
    if "a" <= token[0] <= "z":
        return "L"
    if "0" <= token[0] <= "9":
        return "D"
    return "O"


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def intrinsic_score(token: str) -> tuple[float, float]:
    """(본질적 식별력, zipf). wordfreq 표제어 빈도가 높은 일반어일수록 낮다(0.5 하한), 조어·숫자는
    1."""
    zipf = token_zipf(token)
    if zipf <= 0.0:
        return 1.0, 0.0
    ratio = _clamp((zipf - ZIPF_LOW) / (ZIPF_HIGH - ZIPF_LOW))
    return 1.0 - INTRINSIC_FLOOR * ratio, zipf


def registration_factor(applicants: int, marks: int, *, theta_a: int = THETA_A,
                        theta_n: int = THETA_N) -> float:
    """다수 등록 계수(2017후2697): 서로 다른 출원인 수 A 와 등장 수 N 이 둘 다 클수록 0 에
    가깝다."""
    if applicants <= 0 or marks <= 0:
        return 1.0
    return 1.0 - min(1.0, applicants / theta_a) * min(1.0, marks / theta_n)


def is_place(token: str) -> bool:
    """4호: 지명 목록 일치, 또는 행정 접미사(시·군·구·도·동…)를 뗀 2글자 이상이 지명."""
    if token in PLACE_NAMES:
        return True
    if _script(token) == "H":
        for suffix in PLACE_SUFFIXES:
            base = token[: -len(suffix)] if token.endswith(suffix) else ""
            if len(base) >= 2 and base in PLACE_NAMES:
                return True
    return False


def is_common_surname(token: str) -> bool:
    """5호: 흔한 성 자체, 성 + 네/가네/씨네(김가네·박네), 로마자 성."""
    if token in COMMON_SURNAMES or token in COMMON_SURNAMES_ROMAN:
        return True
    for suffix in SURNAME_SUFFIXES:
        if token.endswith(suffix) and token[: -len(suffix)] in COMMON_SURNAMES:
            return True
    return False


def is_simple_mark(token: str) -> bool:
    """6호: 영문 2자 이하, 숫자 2자 이하, 한글 1음절(토큰은 문자 종류 경계로 이미 나뉘어
    있다)."""
    script = _script(token)
    if script == "L":
        return len(token) <= 2
    if script == "D":
        return len(token) <= 2
    if script == "H":
        return len(token) <= 1
    return False


@dataclass(frozen=True, slots=True)
class TokenJudgement:
    token: str
    score: float
    reasons: tuple[str, ...]

    @property
    def is_weak(self) -> bool:
        return self.score < THETA


GoodsNameIndex = dict[str, tuple[tuple[int, frozenset[str]], ...]]


def goods_index(goods_map) -> tuple[GoodsNameIndex, dict[str, frozenset[int]]]:
    """변환표 → (단일 토큰 고시 명칭 → ((류, 유사군 코드), …), 유사군 코드 → 류 집합).

    이름·별칭 중 공백 없는 2글자 이상만(토큰 하나와 비교하므로). X1 과 같은 정규화를 쓴다.
    """
    names: dict[str, list[tuple[int, frozenset[str]]]] = {}
    classes: dict[str, set[int]] = {}
    for entry in goods_map.entries:
        codes = frozenset(entry.similarity_codes)
        for code in codes:
            classes.setdefault(code, set()).add(entry.nice_class)
        for text in (entry.name, *entry.aliases):
            tokens = normalize_name(text)
            if len(tokens) != 1 or len(tokens[0]) < MIN_TOKEN_CHARS:
                continue
            names.setdefault(tokens[0], []).append((entry.nice_class, codes))
    return (
        {name: tuple(items) for name, items in names.items()},
        {code: frozenset(items) for code, items in classes.items()},
    )


def famous_tokens(path: Path | None = DEFAULT_FAMOUS_PATH) -> frozenset[str]:
    """유명 브랜드 토큰: 브랜드표 키·값 + famous_brands.txt 출원인명의 상호 핵심 토큰(첫 토큰,
    회사 형태·국적 표기는 건너뜀)."""
    tokens: set[str] = set(KOREAN_BRAND_ROMANIZATION) | set(KOREAN_BRAND_ROMANIZATION.values())
    if path is not None and Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            core = [t for t in normalize_name(line) if t not in _FAMOUS_SKIP and len(t) >= 2]
            if core:
                tokens.add(core[0])
    return frozenset(tokens)


class Distinctiveness:
    """적재된 식별력 모델: 토큰 통계(A·N) + 유명 브랜드 + 고시 명칭 색인 + 임계."""

    def __init__(
        self,
        stats: dict[str, tuple[int, int]],
        *,
        famous: Iterable[str] = (),
        goods_names: GoodsNameIndex | None = None,
        code_classes: dict[str, frozenset[int]] | None = None,
        theta: float = THETA,
        theta_a: int = THETA_A,
        theta_n: int = THETA_N,
        descriptive: dict[str, DescriptiveTerm] | None = None,
    ) -> None:
        self.stats = {token: (int(a), int(n)) for token, (a, n) in stats.items()}
        self.famous = frozenset(famous)
        self.goods_names: GoodsNameIndex = goods_names or {}
        self.code_classes = code_classes or {}
        self.theta, self.theta_a, self.theta_n = theta, theta_a, theta_n
        self.descriptive = descriptive  # None 이면 모듈 상수 DESCRIPTIVE_TERMS 를 본다

    # ---- 1호 ----
    def is_generic_name(self, token: str, goods_codes: frozenset[str] | None) -> bool:
        items = self.goods_names.get(token)
        if not items:
            return False
        if not goods_codes:
            return True  # 전역: 고시 단일 명칭과 일치
        classes: set[int] = set()
        for code in goods_codes:
            classes.update(self.code_classes.get(code, ()))
        return any(codes & goods_codes or nice_class in classes for nice_class, codes in items)

    # ---- 토큰 ----
    def judge(self, token: str, goods_codes: Iterable[str] | None = None) -> TokenJudgement:
        token = unicodedata.normalize("NFKC", str(token or "")).casefold().strip()
        if not token:
            return TokenJudgement(token, 0.0, ("빈 토큰",))
        goods = frozenset(c.strip().upper() for c in (goods_codes or ()) if c and c.strip())
        if token in self.famous:
            return TokenJudgement(token, 1.0, ("유명 브랜드",))
        reasons: list[str] = []
        descriptive = DESCRIPTIVE_TERMS if self.descriptive is None else self.descriptive
        cap: float | None = None
        cap_reason = ""
        term = descriptive.get(token)
        if term is not None:
            if term.absolute:
                reasons.append(f"3호 기술적 표장(절대):{term.kind}")
            elif not goods or term.classes is None:
                cap = DESCRIPTIVE_UNKNOWN_SCORE
                cap_reason = (f"3호 기술적 표장({'상품 미상' if not goods else '류 미지정'}):"
                              f"{term.kind}")
            else:
                goods_classes: set[int] = set()
                for code in goods:
                    goods_classes.update(self.code_classes.get(code, ()))
                hit = sorted(goods_classes & term.classes)
                if hit:
                    reasons.append(f"3호 기술적 표장:{term.kind}(류 {','.join(map(str, hit))})")
        if self.is_generic_name(token, goods):
            reasons.append("1호 보통명칭" + ("" if goods else "(전역)"))
        if is_place(token):
            reasons.append("4호 지명")
        if is_common_surname(token):
            reasons.append("5호 흔한 성")
        if is_simple_mark(token):
            reasons.append("6호 간단 표장")
        if reasons:
            return TokenJudgement(token, 0.0, tuple(reasons))
        intrinsic, zipf = intrinsic_score(token)
        applicants, marks = self.stats.get(token, (0, 0))
        factor = registration_factor(applicants, marks, theta_a=self.theta_a, theta_n=self.theta_n)
        if intrinsic < 1.0:
            reasons.append(f"일반어(zipf {zipf:.1f})")
        if factor < 1.0:
            reasons.append(f"다수 등록(A={applicants}, N={marks})")
        score = intrinsic * factor
        if cap is not None and score > cap:
            score = cap
            reasons.append(cap_reason)
        if not reasons:
            reasons.append("조어")
        return TokenJudgement(token, round(score, 4), tuple(reasons))

    def token_score(self, token: str, goods_codes: Iterable[str] | None = None) -> float:
        return self.judge(token, goods_codes).score

    # ---- 이름 ----
    def judge_name(
        self, name: str, goods_codes: Iterable[str] | None = None
    ) -> list[TokenJudgement]:
        return [self.judge(token, goods_codes) for token in normalize_name(name or "")]

    def salient_tokens(
        self, name: str, goods_codes: Iterable[str] | None = None
    ) -> list[tuple[str, float]]:
        """요부 후보 = 점수 ≥ θ 인 토큰(이름 순서). 빈 목록이면 요부 없음 → 전체 대비
        (2000후2453)."""
        judgements = self.judge_name(name, goods_codes)
        return [(j.token, j.score) for j in judgements if j.score >= self.theta]

    def weak_tokens(self, name: str, goods_codes: Iterable[str] | None = None) -> frozenset[str]:
        """점수 < θ 인 토큰(extra_generic 으로 넘길 집합)."""
        judgements = self.judge_name(name, goods_codes)
        return frozenset(j.token for j in judgements if j.score < self.theta)

    def has_distinctive_part(self, name: str, goods_codes: Iterable[str] | None = None) -> bool:
        return bool(self.salient_tokens(name, goods_codes))

    def pair_generic(
        self, name_a: str, name_b: str, goods_codes: Iterable[str] | None = None
    ) -> frozenset[str]:
        """축 연결용: 두 이름의 약한 토큰 합집합. 요부가 하나도 없는 이름은 토큰을 넘기지 않는다
        (전부 식별력이 없으면 전체로 대비 — 2000후2453). X1 의 제거 전 전체 결합 후보는 X1 이
        유지한다."""
        generic: set[str] = set()
        for name in (name_a, name_b):
            if self.has_distinctive_part(name, goods_codes):
                generic |= self.weak_tokens(name, goods_codes)
        return frozenset(generic)


# ---- 적재 ------------------------------------------------------------------------------------

def resolve_stats_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get(ENV_STATS_PATH, "").strip()
    return Path(env) if env else DEFAULT_STATS_PATH


def read_stats(path: Path) -> dict[str, tuple[int, int]]:
    """token_stats.json → {토큰: (A, N)}. 파일이 없으면 빈 통계(다수 등록 계수 1)."""
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    tokens = data.get("tokens", data)
    return {token: (int(value[0]), int(value[1])) for token, value in tokens.items()}


def build(
    stats: dict[str, tuple[int, int]], *, goods_map=None, famous: Iterable[str] | None = None,
    theta: float = THETA, theta_a: int = THETA_A, theta_n: int = THETA_N,
) -> Distinctiveness:
    goods_names, code_classes = goods_index(goods_map) if goods_map is not None else ({}, {})
    return Distinctiveness(
        stats, famous=famous_tokens() if famous is None else famous, goods_names=goods_names,
        code_classes=code_classes, theta=theta, theta_a=theta_a, theta_n=theta_n,
    )


@functools.lru_cache(maxsize=4)
def _load_cached(path_text: str, with_goods: bool) -> Distinctiveness:
    goods_map = None
    if with_goods:
        from .goods_map import load_goods_map

        goods_map = load_goods_map()
    return build(read_stats(Path(path_text)), goods_map=goods_map)


def load_distinctiveness(
    path: str | os.PathLike[str] | None = None, *, with_goods: bool = True
) -> Distinctiveness:
    """기본 통계 파일(또는 MARKLENS_DISTINCTIVENESS_STATS)과 변환표로 모델을 적재한다(프로세스
    캐시)."""
    return _load_cached(str(resolve_stats_path(path)), with_goods)


def token_score(token: str, goods_codes: Iterable[str] | None = None) -> float:
    """토큰 식별력 점수 0(약함)~1(강함). 기본 모델 사용."""
    return load_distinctiveness().token_score(token, goods_codes)


def salient_tokens(name: str, goods_codes: Iterable[str] | None = None) -> list[tuple[str, float]]:
    return load_distinctiveness().salient_tokens(name, goods_codes)


def weak_tokens(name: str, goods_codes: Iterable[str] | None = None) -> frozenset[str]:
    return load_distinctiveness().weak_tokens(name, goods_codes)


def has_distinctive_part(name: str, goods_codes: Iterable[str] | None = None) -> bool:
    return load_distinctiveness().has_distinctive_part(name, goods_codes)


def pair_generic(
    name_a: str, name_b: str, goods_codes: Iterable[str] | None = None
) -> frozenset[str]:
    return load_distinctiveness().pair_generic(name_a, name_b, goods_codes)
