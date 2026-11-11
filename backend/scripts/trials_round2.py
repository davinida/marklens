"""다빈-1 정답 데이터 2차 수집 — 선정 근거·배분·표본 (호출 0). `trials_collect sample --round 2`.

실행 (프로젝트 루트에서):
    ml/venv/bin/python -m backend.scripts.trials_collect sample --round 2 --total 460 --seed 0

1. 근거(받아서 텍스트를 뽑은 건 전부): 종류별 1등급 수율·3등급 주요 사유, 목록 상표명칭 조건별 도형
   여부 교차표 → 정밀도·재현율·조건별 1등급 수율.
   조건: 비어 있음 / '도형' 문자열 / 기호·숫자만 / 1~2자 / 그 외.
   도형 여부: LLM 상표유형(labels.csv 상표유형_확정 — 도형·결합-도형요부 = 도형계)이 있으면 그것,
   없으면 이 사건 표장 이미지의 자동유형(image_parts.csv·round_image_types.csv 의 role=this —
   요부가 도형이면 도형계).
2. 채택: 정밀도 ≥ 0.5 인 조건만 "도형 추정". 하나도 없으면 도형 우선 없이 종류 수율만으로 배분한다.
   채택 조건의 근거 표본(도형 여부를 아는 건) < 20 이면 "추정 불안" — 큐 맨 앞에 도형 추정 probe
   100건(종류별 고르게)을 두니 그것만 먼저 받아 extract 와 이미지 자동유형
   (ml/scripts/trials_round_images.py)을 잰 뒤 이 명령을 다시 돌린다. 다시 돌리면 이미 받은 건은
   큐에 그대로 두고 남은 자리만 새 근거로 다시 배분한다.
3. 대상: 목록의 거절결정불복·무효·권리범위확인 가운데 심결문 Y 이고, 아직 받지 않았고(pdf·
   fetch_log), 받은 건과 목록 단위 family(청구인·피청구인·등록번호 — 등록번호가 없으면 출원번호)가
   다른 건. 취소·보정각하불복 등은 유사 판단 사례가 아니라 뺀다.
4. 배분(총 --total): 수율은 종류 × 묶음(도형 추정 / 문자·has_meaning / 문자)으로 따로 잰다 —
   has_meaning True 인 문자 사건은 식별력(33조) 사건이 섞여 수율이 다르다. 묶음의 근거 < 20 이면
   도형 추정은 그 종류 전체, 문자 묶음은 그 종류 문자 사건 전체 수율로 대체(표에 * 표시).
   도형 추정 60%(후보가 모자라면 있는 만큼) — 종류는 도형 추정 수율에 비례. 나머지는 문자 사건 —
   문자·has_meaning 수율 × 가중치(권리범위확인 0.5: 1차 상대 표장의 58% 가 확인대상표장이던 쏠림
   완화)에 비례하므로 수율이 낮은 종류는 줄어든다.
   순서: 문자 사건은 has_meaning True → 최근 심결월 → seed, 도형 추정은 최근 심결월 → seed.
   청구인당 월 1건, 목록 단위 family 당 1건.
산출: round<N>_queue.csv(심판번호·종류·심결월·상표명칭·도형추정·has_meaning·선정사유 — 목록에는
심결일이 아니라 심결월만 있다) + 계획표(종류×도형추정×연도, 예상 1등급 = 건수×수율, 예상 호출 =
미수신 건수×2).
"""

from __future__ import annotations

import argparse
import random
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.scripts import trials_collect as tc  # noqa: E402

KINDS = ("refusal", "invalidation", "scope")
KIND_LABELS = {"refusal": "거절결정불복", "invalidation": "무효", "scope": "권리범위확인"}
CONDITION_EMPTY = "비어 있음"
CONDITION_FIGURE_WORD = "'도형' 문자열"
CONDITION_SYMBOL = "기호·숫자만"
CONDITION_SHORT = "1~2자"
CONDITION_OTHER = "그 외"
NAME_CONDITIONS = (
    CONDITION_EMPTY, CONDITION_FIGURE_WORD, CONDITION_SYMBOL, CONDITION_SHORT, CONDITION_OTHER,
)
FIGURE_TYPES = ("도형", "결합-도형요부")  # LLM 상표유형 중 도형계
MIN_PRECISION = 0.5  # 도형 추정 채택 하한(정밀도)
MIN_EVIDENCE = 20  # 근거 표본 하한 — 미만이면 "추정 불안"(조건), 종류 전체 수율로 대체(수율)
FIGURE_SHARE = 0.6  # 도형 추정 몫(풀이 허용하는 만큼)
KIND_WEIGHTS = {"scope": 0.5}  # 문자 사건 배분의 종류 가중치(없으면 1.0)
PROBE_N = 100  # 추정 불안일 때 먼저 받는 도형 추정 건수
CALLS_PER_TRIAL = 2  # 심결문 조회 1 + PDF 다운로드 1
YES = "Y"
QUEUE_COLUMNS = ["심판번호", "종류", "심결월", "상표명칭", "도형추정", "has_meaning", "선정사유"]
# 수율을 따로 재는 묶음 — has_meaning True 인 문자 사건은 식별력(33조) 사건이 섞여 수율이 다르다
GROUP_FIGURE = "도형 추정"
GROUP_MEANING = "문자·has_meaning"
GROUP_PLAIN = "문자"
GROUPS = (GROUP_FIGURE, GROUP_MEANING, GROUP_PLAIN)


# ====================================================================
# 1. 근거 — 받은 건의 등급·도형 여부
# ====================================================================

def name_condition(title: str) -> str:
    """목록 상표명칭의 조건(위에서부터 먼저 맞는 것 하나)."""
    text = (title or "").strip()
    if not text:
        return CONDITION_EMPTY
    if "도형" in text:
        return CONDITION_FIGURE_WORD
    core = "".join(text.split())
    if not any(unicodedata.category(char).startswith("L") for char in core):
        return CONDITION_SYMBOL
    if len(core) <= 2:
        return CONDITION_SHORT
    return CONDITION_OTHER


def llm_figure_types(label_rows: list[dict]) -> dict[str, bool]:
    """심판번호 → 도형계 여부. LLM 상표유형(상표유형_확정)이 있는 건만."""
    result: dict[str, bool] = {}
    for row in label_rows:
        value = (row.get("상표유형_확정") or "").strip()
        if value:
            number = row.get("심판번호", "")
            result[number] = result.get(number, False) or value in FIGURE_TYPES
    return result


def image_figure_types(part_rows: list[dict]) -> dict[str, bool]:
    """심판번호 → 도형계 여부. 이 사건 표장(role=this) 이미지의 자동유형이 있는 건만(요부 기준)."""
    result: dict[str, bool] = {}
    for row in part_rows:
        kind = (row.get("자동유형") or "").strip()
        if (row.get("role") or "") != "this" or not kind:
            continue
        dominant = (row.get("요부") or "").strip() or ("도형" if kind == "도형" else "문자")
        result.setdefault(row.get("심판번호", ""), dominant == "도형")
    return result


@dataclass(frozen=True)
class Trial:
    """받은 건 하나: 종류·상표명칭 조건·자동등급·도형 여부(모르면 None)·has_meaning."""

    number: str
    kind: str
    condition: str
    grade: str
    reason: str
    figure: bool | None
    llm: bool | None
    image: bool | None
    meaning: bool = False


def received_trials(
    list_rows: list[dict],
    prefilter_rows: list[dict],
    kinds: dict[str, dict],
    *,
    rounds: dict[str, str] | None = None,
    llm: dict[str, bool] | None = None,
    image: dict[str, bool] | None = None,
    has_meaning: Callable[[str], bool] | None = None,
) -> list[Trial]:
    """텍스트를 뽑은 건(prefilter) 가운데 대상 종류. 등급은 sheet 와 같은 규칙(family 중복 포함)."""
    llm, image = llm or {}, image or {}
    analysed = {row["심판번호"] for row in prefilter_rows}
    listed = [row for row in list_rows if row["심판번호"] in analysed]
    by_number = {row["심판번호"]: row for row in listed}
    first: dict[str, dict] = {}
    for row in tc.build_sheet_rows(listed, prefilter_rows, kinds, rounds=rounds):
        first.setdefault(row["심판번호"], row)
    trials: list[Trial] = []
    for number, row in first.items():
        kind = tc.kind_for_trial_desc(row.get("종류", ""), kinds)
        if kind not in KINDS:
            continue
        figure = llm.get(number, image.get(number))
        title = by_number[number].get("상표명칭", "")
        trials.append(Trial(
            number, kind, name_condition(title),
            row.get("자동등급", ""), row.get("등급사유", ""), figure,
            llm.get(number), image.get(number),
            bool(has_meaning(title)) if has_meaning and title.strip() else False,
        ))
    return trials


def _rate(hits: int, total: int) -> float:
    return hits / total if total else 0.0


def yield_counts(
    trials: list[Trial], keep: Callable[[Trial], bool] = lambda trial: True
) -> dict[str, tuple[int, int]]:
    """종류 → (받은 건, 1등급). keep 으로 부분집합을 고른다."""
    counts = {kind: [0, 0] for kind in KINDS}
    for trial in trials:
        if keep(trial):
            counts[trial.kind][0] += 1
            counts[trial.kind][1] += 1 if trial.grade == "1" else 0
    return {kind: (pair[0], pair[1]) for kind, pair in counts.items()}


def grade_reasons(trials: list[Trial], grade: str = "3", top: int = 3) -> dict[str, list]:
    """종류 → 그 등급의 주요 사유 [(사유, 건수)…]. 조문 번호 같은 꼬리는 떼고 묶는다."""
    counters: dict[str, Counter] = {kind: Counter() for kind in KINDS}
    for trial in trials:
        if trial.grade != grade:
            continue
        reason = trial.reason
        for prefix in ("결론에 인지도 조문", "결론 조문이 7호 아님"):
            if reason.startswith(prefix):
                reason = prefix
        counters[trial.kind][reason] += 1
    return {kind: counter.most_common(top) for kind, counter in counters.items()}


@dataclass
class Evidence:
    """상표명칭 조건 하나의 근거: 받은 건·도형 여부(출처별·합친 것)·1등급."""

    condition: str
    received: int = 0
    grade1: int = 0
    llm_figure: int = 0
    llm_word: int = 0
    image_figure: int = 0
    image_word: int = 0
    known: int = 0  # 도형 여부를 아는 건(LLM 우선, 없으면 이미지)
    figure: int = 0  # 그중 도형계
    by_kind: dict[str, list[int]] = field(default_factory=dict)  # 종류 → [받은 건, 1등급]
    precision: float | None = None
    recall: float | None = None
    adopted: bool = False
    shaky: bool = False


def figure_evidence(trials: list[Trial]) -> list[Evidence]:
    """조건별 교차표·정밀도·재현율과 채택 여부. '그 외'는 조건이 아니라 나머지라 채택하지 않는다."""
    table = {
        name: Evidence(name, by_kind={kind: [0, 0] for kind in KINDS})
        for name in NAME_CONDITIONS
    }
    for trial in trials:
        item = table[trial.condition]
        item.received += 1
        item.by_kind[trial.kind][0] += 1
        if trial.grade == "1":
            item.grade1 += 1
            item.by_kind[trial.kind][1] += 1
        if trial.llm is not None:
            item.llm_figure += 1 if trial.llm else 0
            item.llm_word += 0 if trial.llm else 1
        if trial.image is not None:
            item.image_figure += 1 if trial.image else 0
            item.image_word += 0 if trial.image else 1
        if trial.figure is not None:
            item.known += 1
            item.figure += 1 if trial.figure else 0
    total_figure = sum(item.figure for item in table.values())
    for item in table.values():
        if item.known:
            item.precision = item.figure / item.known
        if total_figure:
            item.recall = item.figure / total_figure
        item.adopted = (
            item.condition != CONDITION_OTHER
            and item.precision is not None
            and item.precision >= MIN_PRECISION
        )
        item.shaky = item.adopted and item.known < MIN_EVIDENCE
    return [table[name] for name in NAME_CONDITIONS]


def trial_group(trial: Trial, adopted: frozenset[str]) -> str:
    if trial.condition in adopted:
        return GROUP_FIGURE
    return GROUP_MEANING if trial.meaning else GROUP_PLAIN


def queue_group(row: dict) -> str:
    if row.get("도형추정") == YES:
        return GROUP_FIGURE
    return GROUP_MEANING if row.get("has_meaning") == YES else GROUP_PLAIN


@dataclass(frozen=True)
class Yields:
    """배분·예상에 쓰는 수율: 종류 × 묶음(도형 추정 / 문자·has_meaning / 문자)의
    (받은 건, 1등급)."""

    overall: dict[str, tuple[int, int]]
    word: dict[str, tuple[int, int]]  # 도형 추정이 아닌 건 전부
    groups: dict[tuple[str, str], tuple[int, int]]

    def rate(self, kind: str, group: str) -> tuple[float, bool]:
        """(수율, 대체 여부). 그 묶음의 근거가 MIN_EVIDENCE 미만이면 도형 추정은 그 종류 전체, 문자
        묶음은 그 종류의 문자 사건 전체 수율로 대체한다."""
        count, hits = self.groups[(kind, group)]
        if count >= MIN_EVIDENCE:
            return _rate(hits, count), False
        base = self.overall[kind] if group == GROUP_FIGURE else self.word[kind]
        if base[0] < MIN_EVIDENCE:
            base = self.overall[kind]
        return _rate(base[1], base[0]), True


def compute_yields(trials: list[Trial], adopted: frozenset[str]) -> Yields:
    groups: dict[tuple[str, str], tuple[int, int]] = {}
    for group in GROUPS:
        counts = yield_counts(
            trials, lambda trial, group=group: trial_group(trial, adopted) == group
        )
        for kind in KINDS:
            groups[(kind, group)] = counts[kind]
    return Yields(
        overall=yield_counts(trials),
        word=yield_counts(trials, lambda trial: trial.condition not in adopted),
        groups=groups,
    )


# ====================================================================
# 2. 배분·선정
# ====================================================================

def allocate_weighted(
    total: int, weights: dict[str, float], caps: dict[str, int]
) -> dict[str, int]:
    """가중치 비례 배분(큰 나머지법). 상한(caps)에 걸린 몫은 나머지 키에 다시 비례로 나눈다.

    가중치가 0 이거나 상한이 0 인 키는 받지 않는다. 동률은 키 이름 순.
    """
    allocation = {key: 0 for key in weights}
    active = sorted(key for key in weights if weights[key] > 0 and caps.get(key, 0) > 0)
    remaining = max(0, total)
    while remaining > 0 and active:
        weight_sum = sum(weights[key] for key in active)
        ideal = {key: remaining * weights[key] / weight_sum for key in active}
        capped = [key for key in active if ideal[key] >= caps[key] - allocation[key]]
        if capped:
            for key in capped:
                remaining -= caps[key] - allocation[key]
                allocation[key] = caps[key]
            active = [key for key in active if key not in capped]
            continue
        floors = {key: int(ideal[key]) for key in active}
        left = remaining - sum(floors.values())
        for key in sorted(active, key=lambda key: (-(ideal[key] - floors[key]), key))[:left]:
            floors[key] += 1
        for key in active:
            allocation[key] += floors[key]
        remaining = 0
    return allocation


def claimant_key(row: dict) -> str:
    return "".join((row.get("청구인") or "").split()).casefold()


def list_family_key(row: dict) -> str:
    """목록 단위 family: 청구인·피청구인·등록번호(없으면 출원번호). 심결문을 읽기 전이라 선등록
    번호는 모른다 — 같은 당사자가 같은 상표를 두고 낸 사건을 한 묶음으로 본다."""
    respondent = "".join((row.get("피청구인") or "").split()).casefold()
    number = tc._digits(row.get("등록번호", "")) or tc._digits(row.get("출원번호", ""))
    return f"{claimant_key(row)}|{respondent}|{number}"


@dataclass(frozen=True)
class Candidate:
    row: dict
    kind: str
    figure: bool  # 도형 추정(채택 조건에 해당)
    meaning: bool  # 상표명칭에 사전적 의미(has_meaning) — 문자 사건만 잰다
    tie: float  # seed 와 심판번호로 정한 동률 순서(풀이 바뀌어도 같은 값)

    @property
    def number(self) -> str:
        return self.row["심판번호"]

    @property
    def month(self) -> str:
        return self.row.get("심결월", "")

    def priority(self) -> tuple[int, int, float]:
        """has_meaning True → 최근 심결월 → seed."""
        month = int(self.month) if self.month.isdigit() else 0
        return (0 if self.meaning else 1, -month, self.tie)


def build_candidates(
    list_rows: list[dict],
    kinds: dict[str, dict],
    *,
    taken: set[str],
    taken_families: set[str],
    adopted: frozenset[str],
    has_meaning: Callable[[str], bool],
    seed: int,
) -> list[Candidate]:
    """대상 종류·심결문 Y·미수신·family 다른 건 → 후보(우선순위 순)."""
    candidates: list[Candidate] = []
    for row in list_rows:
        kind = tc.kind_for_trial_desc(row.get("종류", ""), kinds)
        if kind not in KINDS or (row.get("심결문유무") or "").upper() != YES:
            continue
        number = row["심판번호"]
        if number in taken or list_family_key(row) in taken_families:
            continue
        title = row.get("상표명칭", "")
        figure = name_condition(title) in adopted
        candidates.append(Candidate(
            row, kind, figure, (not figure) and bool(has_meaning(title)),
            random.Random(f"{seed}:{number}").random(),
        ))
    candidates.sort(key=lambda item: (item.priority(), item.number))
    return candidates


class Picker:
    """청구인당 월 1건·목록 단위 family 당 1건을 지키며 후보를 받는다."""

    def __init__(self) -> None:
        self.claimant_months: set[tuple[str, str]] = set()
        self.families: set[str] = set()

    def mark(self, row: dict) -> None:
        claimant = claimant_key(row)
        if claimant:
            self.claimant_months.add((claimant, row.get("심결월", "")))
        self.families.add(list_family_key(row))

    def accept(self, candidate: Candidate) -> bool:
        claimant = claimant_key(candidate.row)
        if claimant and (claimant, candidate.month) in self.claimant_months:
            return False
        if list_family_key(candidate.row) in self.families:
            return False
        self.mark(candidate.row)
        return True


def fill(
    picker: Picker, pools: dict[str, list[Candidate]], target: int, weights: dict[str, float]
) -> dict[str, list[Candidate]]:
    """종류별 풀에서 target 건을 가중치 비례로 고른다. 제약(청구인·family)이나 풀 소진으로 모자란
    몫은 남은 종류에 다시 나눈다."""
    cursors = {kind: 0 for kind in pools}
    picked: dict[str, list[Candidate]] = {kind: [] for kind in pools}
    need = max(0, target)
    while need > 0:
        caps = {kind: len(pools[kind]) - cursors[kind] for kind in pools}
        quota = allocate_weighted(need, weights, caps)
        progress = 0
        for kind in sorted(pools, key=lambda kind: (-weights.get(kind, 0.0), kind)):
            got = 0
            while got < quota.get(kind, 0) and cursors[kind] < len(pools[kind]):
                candidate = pools[kind][cursors[kind]]
                cursors[kind] += 1
                if picker.accept(candidate):
                    picked[kind].append(candidate)
                    got += 1
            progress += got
        if progress == 0:  # 풀이 비었거나 남은 종류의 가중치가 0
            break
        need -= progress
    return picked


@dataclass
class Selection:
    queue: list[dict]
    kept: int  # 이미 받은(시도한) 그 회차 건 — 큐에 그대로 둔다
    figure_target: int
    probe: int  # 큐 앞쪽 probe 건수(추정 불안일 때)
    figure_pool: dict[str, int]  # 도형 추정 후보 수(종류별, 청구인·family 제약 적용 전)
    figure_pool_years: dict[str, str]  # 종류 → "2016:3 2017:5 …"
    word_pool: dict[str, int]
    meaning_pool: dict[str, int]  # 문자 후보 중 has_meaning True
    figure_weights: dict[str, float]
    word_weights: dict[str, float]


def _queue_row(candidate: Candidate, reason: str) -> dict:
    row = candidate.row
    return {
        "심판번호": candidate.number,
        "종류": row.get("종류", ""),
        "심결월": candidate.month,
        "상표명칭": row.get("상표명칭", ""),
        "도형추정": YES if candidate.figure else "",
        "has_meaning": "" if candidate.figure else (YES if candidate.meaning else "N"),
        "선정사유": reason,
    }


def _interleave(groups: list[list]) -> list:
    """종류별 목록을 한 건씩 돌아가며 섞는다(처음 몇 건에 모든 종류가 들어가게)."""
    result: list = []
    for index in range(max((len(group) for group in groups), default=0)):
        result += [group[index] for group in groups if index < len(group)]
    return result


def select_round(
    list_rows: list[dict],
    kinds: dict[str, dict],
    *,
    evidence: list[Evidence],
    yields: Yields,
    attempted: set[str],
    previous_queue: list[dict],
    total: int,
    seed: int,
    has_meaning: Callable[[str], bool],
) -> Selection:
    """근거(evidence·yields)로 큐를 만든다. previous_queue 중 이미 시도한 건은 그대로 앞에 둔다."""
    adopted = frozenset(item.condition for item in evidence if item.adopted)
    shaky = any(item.shaky for item in evidence)
    by_number = {row["심판번호"]: row for row in list_rows}
    kept = [row for row in previous_queue if row.get("심판번호", "") in attempted]
    picker = Picker()
    for row in kept:
        if row["심판번호"] in by_number:
            picker.mark(by_number[row["심판번호"]])
    candidates = build_candidates(
        list_rows, kinds, taken=attempted,
        taken_families={list_family_key(by_number[n]) for n in attempted if n in by_number},
        adopted=adopted, has_meaning=has_meaning, seed=seed,
    )
    figure_pools = {
        kind: [item for item in candidates if item.figure and item.kind == kind] for kind in KINDS
    }
    word_pools = {
        kind: [item for item in candidates if not item.figure and item.kind == kind]
        for kind in KINDS
    }

    room = max(0, total - len(kept))
    kept_figure = sum(1 for row in kept if row.get("도형추정") == YES)
    figure_target = round(FIGURE_SHARE * total) if adopted else kept_figure
    figure_weights = {kind: yields.rate(kind, GROUP_FIGURE)[0] for kind in KINDS}
    figures = fill(picker, figure_pools, min(room, max(0, figure_target - kept_figure)),
                   figure_weights)
    figure_count = sum(len(items) for items in figures.values())
    word_weights = {  # 문자 사건은 has_meaning True 부터 고르므로 그 묶음의 수율이 가중치
        kind: yields.rate(kind, GROUP_MEANING)[0] * KIND_WEIGHTS.get(kind, 1.0) for kind in KINDS
    }
    words = fill(picker, word_pools, room - figure_count, word_weights)

    labels = "·".join(sorted(adopted, key=NAME_CONDITIONS.index))
    figure_reason = f"{GROUP_FIGURE}(상표명칭 {labels})"
    probe_size = max(0, PROBE_N - kept_figure) if shaky else 0
    probe_quota = allocate_weighted(
        probe_size, {kind: 1.0 for kind in KINDS}, {kind: len(figures[kind]) for kind in KINDS}
    )
    probe = _interleave([
        [_queue_row(c, figure_reason + "·probe") for c in figures[kind][:probe_quota[kind]]]
        for kind in KINDS
    ])
    rest_figure = [
        _queue_row(c, figure_reason) for kind in KINDS for c in figures[kind][probe_quota[kind]:]
    ]
    rest_word = [
        _queue_row(c, GROUP_MEANING if c.meaning else GROUP_PLAIN)
        for kind in KINDS for c in words[kind]
    ]
    queue = [{column: row.get(column, "") for column in QUEUE_COLUMNS} for row in kept]
    queue += probe + rest_figure + rest_word
    return Selection(
        queue=queue, kept=len(kept), figure_target=figure_target, probe=len(probe),
        figure_pool={kind: len(figure_pools[kind]) for kind in KINDS},
        figure_pool_years={
            kind: _years([item.row for item in figure_pools[kind]]) for kind in KINDS
        },
        word_pool={kind: len(word_pools[kind]) for kind in KINDS},
        meaning_pool={
            kind: sum(1 for item in word_pools[kind] if item.meaning) for kind in KINDS
        },
        figure_weights=figure_weights, word_weights=word_weights,
    )


# ====================================================================
# 3. 보고 — 근거 표·계획표
# ====================================================================

def _fraction(hits: int, total: int) -> str:
    return f"{hits}/{total}({_rate(hits, total):.2f})" if total else "0/0(-)"


def yield_lines(trials: list[Trial]) -> list[str]:
    counts = yield_counts(trials)
    reasons = grade_reasons(trials)
    lines = []
    for kind in KINDS:
        received, grade1 = counts[kind]
        grades = Counter(trial.grade for trial in trials if trial.kind == kind)
        top = ", ".join(f"{reason} {count}" for reason, count in reasons[kind]) or "-"
        lines.append(
            f"{KIND_LABELS[kind]}: 받은 {received}건 중 1등급 {_fraction(grade1, received)} · "
            f"2등급 {grades['2']} · 3등급 {grades['3']} — 3등급 사유: {top}"
        )
    return lines


def evidence_lines(evidence: list[Evidence]) -> list[str]:
    lines = []
    for item in evidence:
        if item.adopted:
            verdict = "채택" + (f"(추정 불안: 근거 {item.known}건 < {MIN_EVIDENCE})"
                              if item.shaky else "")
        elif item.condition == CONDITION_OTHER:
            verdict = "나머지(조건 아님)"
        elif not item.received:
            verdict = "해당 사건 없음"
        elif not item.known:
            verdict = "미채택(도형 여부를 아는 건 없음)"
        else:
            verdict = f"미채택(정밀도 {item.precision:.2f} < {MIN_PRECISION})"
        precision = "-" if item.precision is None else (
            f"{item.precision:.2f}({item.figure}/{item.known})")
        recall = "-" if item.recall is None else f"{item.recall:.2f}"
        by_kind = "·".join(
            f"{KIND_LABELS[kind][:2]} {item.by_kind[kind][1]}/{item.by_kind[kind][0]}"
            for kind in KINDS
        )
        lines.append(
            f"{item.condition}: 받은 {item.received} · LLM 도형계 {item.llm_figure}/문자계 "
            f"{item.llm_word} · 이미지 도형계 {item.image_figure}/문자계 {item.image_word} · "
            f"정밀도 {precision} · 재현율 {recall} · 1등급 {_fraction(item.grade1, item.received)}"
            f" [{by_kind}] → {verdict}"
        )
    return lines


def _years(rows: list[dict]) -> str:
    years = Counter((row.get("심결월") or "")[:4] for row in rows)
    return " ".join(f"{year}:{count}" for year, count in sorted(years.items())) or "-"


def plan_lines(
    queue: list[dict], kinds: dict[str, dict], yields: Yields, attempted: set[str]
) -> tuple[list[str], float, int]:
    """계획표(묶음×종류×연도, 예상 1등급 = 건수×수율)와 합계 예상 1등급·예상 호출."""
    lines: list[str] = []
    expected_total = 0.0
    for group in GROUPS:
        for kind in KINDS:
            rows = [
                row for row in queue
                if queue_group(row) == group
                and tc.kind_for_trial_desc(row.get("종류", ""), kinds) == kind
            ]
            if not rows:
                continue
            rate, fallback = yields.rate(kind, group)
            expected = len(rows) * rate
            expected_total += expected
            lines.append(
                f"{group} · {KIND_LABELS[kind]}: {len(rows)}건 × 수율 {rate:.3f}"
                f"{'*' if fallback else ''} = 예상 1등급 {expected:.1f} · 연도 {_years(rows)}"
            )
    pending = sum(1 for row in queue if row["심판번호"] not in attempted)
    return lines, expected_total, pending * CALLS_PER_TRIAL


def group_yield_lines(yields: Yields) -> list[str]:
    """종류마다 묶음별 1등급/받은 건 → 쓰는 수율(* = 근거가 모자라 대체)."""
    lines = []
    for kind in KINDS:
        parts = []
        for group in GROUPS:
            count, hits = yields.groups[(kind, group)]
            rate, fallback = yields.rate(kind, group)
            parts.append(f"{group} {hits}/{count} → {rate:.3f}{'*' if fallback else ''}")
        lines.append(f"{KIND_LABELS[kind]}: " + " · ".join(parts))
    return lines


def _load_has_meaning() -> Callable[[str], bool]:
    """X3 의 has_meaning(wordfreq 표제어 조회 — 임베딩 모델은 읽지 않는다). 같은 이름은 한 번만."""
    from backend.src.core import paths

    if str(paths.ML_ROOT) not in sys.path:
        sys.path.insert(0, str(paths.ML_ROOT))
    from src.axes.x3_semantic import has_meaning

    cache: dict[str, bool] = {}

    def cached(name: str) -> bool:
        if name not in cache:
            cache[name] = bool(has_meaning(name))
        return cache[name]

    return cached


def run_sample_round(
    args: argparse.Namespace,
    session: tc.Session,
    *,
    has_meaning: Callable[[str], bool] | None = None,
) -> int:
    paths_ = session.paths
    round_no = int(args.round)
    if round_no < 2:
        raise tc.LabelError(
            "--round 는 2 이상입니다(1차 표본은 sample --scope/--invalidation/--refusal)"
        )
    kinds = tc.load_kinds(args.kinds_config)
    source = Path(args.source) if getattr(args, "source", "") else paths_.list_all_csv
    list_rows = tc._read_csv(source)
    if not list_rows:
        raise tc.LabelError(f"{source} 가 없습니다 — list --all-kinds 먼저", 1)
    prefilter_rows = tc._read_csv(paths_.prefilter_csv)
    out = Path(args.out) if getattr(args, "out", "") else paths_.round_queue(round_no)
    previous_queue = tc._read_csv(out)
    rounds = tc.load_rounds(paths_)
    for row in previous_queue:  # --out 이 기본 이름이 아니어도 그 큐의 건은 이 회차로 본다
        rounds.setdefault(row.get("심판번호", ""), str(round_no))
    part_rows = tc._read_csv(paths_.image_parts_csv) + tc._read_csv(paths_.round_image_types_csv)
    has_meaning = has_meaning or _load_has_meaning()
    trials = received_trials(
        list_rows, prefilter_rows, kinds, rounds=rounds,
        llm=llm_figure_types(tc._read_csv(paths_.labels_csv)),
        image=image_figure_types(part_rows), has_meaning=has_meaning,
    )
    evidence = figure_evidence(trials)
    adopted = frozenset(item.condition for item in evidence if item.adopted)
    yields = compute_yields(trials, adopted)
    attempted = {p.stem for p in paths_.pdf_dir.glob("*.pdf")} if paths_.pdf_dir.exists() else set()
    attempted |= {row["심판번호"] for row in tc._read_csv(paths_.fetch_log)}
    selection = select_round(
        list_rows, kinds, evidence=evidence, yields=yields, attempted=attempted,
        previous_queue=previous_queue, total=args.total, seed=args.seed,
        has_meaning=has_meaning,
    )
    tc._write_csv(out, QUEUE_COLUMNS, selection.queue)

    by_round = Counter(rounds.get(trial.number, tc.FIRST_ROUND) for trial in trials)
    print(f"## sample --round {round_no} (호출 0): 목록 {len(list_rows)}건 · 받은 건(대상 종류, "
          f"텍스트 있음) {len(trials)} — "
          + " · ".join(f"{key}차 {by_round[key]}" for key in sorted(by_round, key=int)))
    print("### 1. 종류별 1등급 수율")
    for line in yield_lines(trials):
        print("- " + line)
    print("### 2. 상표명칭 조건 × 도형 여부(정밀도·재현율은 LLM 유형 우선, 없으면 이미지 자동유형)")
    for line in evidence_lines(evidence):
        print("- " + line)
    if adopted:
        print("- 도형 추정 = 상표명칭 " + "·".join(sorted(adopted, key=NAME_CONDITIONS.index))
              + (" — 추정 불안: probe 를 먼저 받고 extract·이미지 자동유형 뒤 다시 실행"
                 if any(item.shaky for item in evidence) else ""))
    else:
        print("- 채택한 조건 없음 — 도형 우선 없이 종류 수율만으로 배분")
    print("### 3. 미수집 후보(대상 종류·심결문 Y·받은 건과 family 다름, 청구인 월 1건 적용 전)")
    for kind in KINDS:
        print(f"- 도형 추정 · {KIND_LABELS[kind]} {selection.figure_pool[kind]}건: "
              f"{selection.figure_pool_years[kind]}")
    print("- 문자: " + " · ".join(
        f"{KIND_LABELS[kind]} {selection.word_pool[kind]}(has_meaning "
        f"{selection.meaning_pool[kind]})" for kind in KINDS))
    print(f"### 4. 배분(총 {args.total}, seed {args.seed})")
    print(f"- 묶음별 수율(1등급/받은 건 → 쓰는 수율, * = 근거 {MIN_EVIDENCE}건 미만이라 "
          "도형 추정은 종류 전체·문자는 그 종류 문자 사건 전체로 대체):")
    for line in group_yield_lines(yields):
        print("  - " + line)
    print(f"- 도형 추정 목표 {selection.figure_target}건({FIGURE_SHARE:.0%}, 후보가 모자라면 "
          f"있는 만큼) — 종류 가중치 = {GROUP_FIGURE} 수율")
    print(f"- 문자 종류 가중치 = {GROUP_MEANING} 수율 × " + "·".join(
        f"{KIND_LABELS[kind]} {KIND_WEIGHTS.get(kind, 1.0):g}" for kind in KINDS))
    figure_rows = sum(1 for row in selection.queue if row.get("도형추정") == YES)
    meaning_rows = sum(1 for row in selection.queue if row.get("has_meaning") == YES)
    print(f"- 큐 {len(selection.queue)}건 = 이미 받은 {selection.kept} + 새로 "
          f"{len(selection.queue) - selection.kept} · 도형 추정 {figure_rows}"
          f"({_rate(figure_rows, len(selection.queue)):.0%}) · 문자 "
          f"{len(selection.queue) - figure_rows}(has_meaning {meaning_rows})"
          + (f" · 앞 {selection.probe}건이 probe" if selection.probe else ""))
    print("### 5. 계획표(예상 1등급 = 건수 × 수율, * = 대체 수율)")
    lines, expected, calls = plan_lines(selection.queue, kinds, yields, attempted)
    for line in lines:
        print("- " + line)
    print(f"- 합계: 예상 1등급 {expected:.1f}건 · 예상 호출 {calls}회(미수신 {calls // 2}건 × "
          f"{CALLS_PER_TRIAL}) → {out}")
    return 0
