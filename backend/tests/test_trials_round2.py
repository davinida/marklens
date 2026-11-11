"""다빈-1 정답 데이터 2차 수집 표본(trials_round2) — 네트워크 없이.

도형 추정 조건(상표명칭 → 정밀도 ≥ 0.5 채택·근거 < 20 추정 불안), 수율 비례 배분(상한 재배분·대체
수율), has_meaning 우선·최근 심결 우선, 제외(받은 건·family·취소·심결문 N·청구인 월 1건), seed 재현,
다시 돌릴 때 받은 건 유지.
"""

import csv
from pathlib import Path

import pytest

from backend.scripts import trials_collect as tc
from backend.scripts import trials_round2 as r2

KINDS = tc.load_kinds(tc.KINDS_CONFIG_PATH)
DESC = {"refusal": "거절결정불복", "invalidation": "무효", "scope": "권리범위확인(적극적)"}


def _trial(number, kind="refusal", condition=r2.CONDITION_OTHER, grade="3", *,
           llm=None, image=None, meaning=False) -> r2.Trial:
    figure = llm if llm is not None else image
    return r2.Trial(str(number), kind, condition, grade, "사유", figure, llm, image, meaning)


def _row(number, kind="refusal", title="가나다", *, month="202401", claimant=None,
         respondent="", registration="", doc="Y") -> dict:
    return {
        "심판번호": str(number), "종류": DESC.get(kind, kind), "심결월": month, "심판상태": "심결",
        "상표명칭": title, "출원번호": f"40{number}", "등록번호": registration,
        "청구인": f"청구인{number}" if claimant is None else claimant, "피청구인": respondent,
        "심결문유무": doc,
    }


def _meaning(name: str) -> bool:
    return name.startswith("뜻")


def _evidence(empty_known: int = 20, empty_figure: int = 20) -> list[r2.Trial]:
    """상표명칭이 빈 건 empty_known 개(그중 도형계 empty_figure) + 문자 사건들(종류별 수율 근거)."""
    trials = [
        _trial(f"E{i}", "scope", r2.CONDITION_EMPTY, "1" if i % 2 else "3", llm=i < empty_figure)
        for i in range(empty_known)
    ]
    for kind, hits in (("refusal", 12), ("invalidation", 4), ("scope", 16)):
        trials += [
            _trial(f"{kind}{i}", kind, grade="1" if i < hits else "3", llm=False, meaning=True)
            for i in range(30)
        ]
    return trials


def _select(list_rows, trials, *, total, seed=0, attempted=frozenset(), previous=()):
    evidence = r2.figure_evidence(trials)
    adopted = frozenset(item.condition for item in evidence if item.adopted)
    return r2.select_round(
        list_rows, KINDS, evidence=evidence, yields=r2.compute_yields(trials, adopted),
        attempted=set(attempted), previous_queue=list(previous), total=total, seed=seed,
        has_meaning=_meaning,
    )


# ---------------- 근거 ----------------

@pytest.mark.parametrize(
    "title, expected",
    [
        ("", r2.CONDITION_EMPTY), ("   ", r2.CONDITION_EMPTY),
        ("도형상표", r2.CONDITION_FIGURE_WORD), ("(도형)", r2.CONDITION_FIGURE_WORD),
        ("777", r2.CONDITION_SYMBOL), ("5·13", r2.CONDITION_SYMBOL), ("100%", r2.CONDITION_SYMBOL),
        ("M", r2.CONDITION_SHORT), ("K2", r2.CONDITION_SHORT), ("가 나", r2.CONDITION_SHORT),
        ("CLOVER", r2.CONDITION_OTHER), ("가나다", r2.CONDITION_OTHER),
    ],
)
def test_name_condition_buckets(title, expected):
    assert r2.name_condition(title) == expected


def test_figure_truth_sources_llm_and_image():
    labels = [
        {"심판번호": "A", "상표유형_확정": "문자"}, {"심판번호": "A", "상표유형_확정": "문자"},
        {"심판번호": "B", "상표유형_확정": "결합-도형요부"}, {"심판번호": "C", "상표유형_확정": ""},
        {"심판번호": "D", "상표유형_확정": "도형"},
    ]
    assert r2.llm_figure_types(labels) == {"A": False, "B": True, "D": True}
    parts = [
        {"심판번호": "A", "role": "this", "자동유형": "도형", "요부": "도형"},
        {"심판번호": "A", "role": "prior_1", "자동유형": "문자", "요부": "문자"},  # 상대 표장
        {"심판번호": "B", "role": "this", "자동유형": "결합", "요부": "문자"},
        {"심판번호": "C", "role": "this", "자동유형": "결합", "요부": "도형"},
        {"심판번호": "D", "role": "this", "자동유형": "", "요부": ""},  # 이미지 없음 — 모름
    ]
    assert r2.image_figure_types(parts) == {"A": True, "B": False, "C": True}


def test_figure_evidence_precision_recall_adoption_and_shaky():
    trials = [_trial(f"e{i}", "scope", r2.CONDITION_EMPTY, "1", llm=True) for i in range(17)]
    trials += [_trial(f"u{i}", "refusal", r2.CONDITION_EMPTY) for i in range(3)]  # 도형 여부 모름
    # LLM 이 문자라고 한 건은 이미지가 도형이어도 문자(LLM 우선). 이미지만 있는 건은 이미지로.
    trials += [_trial("s1", condition=r2.CONDITION_SHORT, llm=False, image=True),
               _trial("s2", condition=r2.CONDITION_SHORT, image=True),
               _trial("s3", condition=r2.CONDITION_SHORT, image=False),
               _trial("s4", condition=r2.CONDITION_SHORT, llm=False)]
    trials += [_trial(f"o{i}", llm=True) for i in range(3)]  # '그 외'는 전부 도형이어도 채택 안 함
    trials += [_trial("n1", condition=r2.CONDITION_SYMBOL)]  # 도형 여부를 아는 건 없음
    table = {item.condition: item for item in r2.figure_evidence(trials)}

    empty = table[r2.CONDITION_EMPTY]
    assert (empty.received, empty.known, empty.figure, empty.grade1) == (20, 17, 17, 17)
    assert empty.precision == 1.0 and empty.adopted and empty.shaky  # 근거 17 < 20
    assert empty.by_kind == {"refusal": [3, 0], "invalidation": [0, 0], "scope": [17, 17]}
    assert empty.recall == pytest.approx(17 / 21)  # 도형계 21 = 17 + 1(이미지) + 3('그 외')
    short = table[r2.CONDITION_SHORT]
    assert (short.llm_figure, short.llm_word, short.image_figure, short.image_word) == (0, 2, 2, 1)
    assert (short.known, short.figure) == (4, 1) and short.precision == 0.25
    assert not short.adopted and not short.shaky
    assert table[r2.CONDITION_OTHER].precision == 1.0 and not table[r2.CONDITION_OTHER].adopted
    assert table[r2.CONDITION_SYMBOL].precision is None and not table[r2.CONDITION_SYMBOL].adopted
    assert table[r2.CONDITION_FIGURE_WORD].received == 0

    enough = trials + [_trial(f"x{i}", "scope", r2.CONDITION_EMPTY, llm=True) for i in range(3)]
    empty = {item.condition: item for item in r2.figure_evidence(enough)}[r2.CONDITION_EMPTY]
    assert empty.known == 20 and empty.adopted and not empty.shaky
    # 정밀도가 0.5 아래로 내려가면 채택하지 않는다(가설을 억지로 살리지 않는다)
    wrong = [_trial(f"w{i}", condition=r2.CONDITION_EMPTY, image=i < 9) for i in range(20)]
    rejected = r2.figure_evidence(wrong)[0]
    assert not rejected.adopted and rejected.precision == 0.45


def test_yields_by_group_with_fallback_for_thin_evidence():
    adopted = frozenset({r2.CONDITION_EMPTY})
    trials = [_trial(f"f{i}", "refusal", r2.CONDITION_EMPTY) for i in range(5)]  # 도형 추정 0/5
    trials += [_trial(f"g{i}", "scope", r2.CONDITION_EMPTY, "1" if i < 12 else "3")
               for i in range(25)]  # 도형 추정 12/25
    trials += [_trial(f"m{i}", "refusal", grade="1" if i < 8 else "3", meaning=True)
               for i in range(20)]  # 문자·has_meaning 8/20
    trials += [_trial(f"p{i}", "refusal", grade="1" if i < 9 else "3")
               for i in range(10)]  # 문자 9/10
    yields = r2.compute_yields(trials, adopted)
    assert yields.overall["refusal"] == (35, 17) and yields.word["refusal"] == (30, 17)
    assert yields.groups[("refusal", r2.GROUP_FIGURE)] == (5, 0)
    # 근거 5건 < 20 → 그 종류 전체 수율로 대체(0/5 를 그대로 쓰지 않는다)
    assert yields.rate("refusal", r2.GROUP_FIGURE) == (pytest.approx(17 / 35), True)
    assert yields.rate("scope", r2.GROUP_FIGURE) == (pytest.approx(12 / 25), False)
    assert yields.rate("refusal", r2.GROUP_MEANING) == (pytest.approx(0.4), False)
    # 문자 묶음의 근거가 모자라면 그 종류 문자 사건 전체(17/30)
    assert yields.rate("refusal", r2.GROUP_PLAIN) == (pytest.approx(17 / 30), True)
    assert yields.rate("invalidation", r2.GROUP_MEANING) == (0.0, True)  # 받은 건이 없는 종류


# ---------------- 배분 ----------------

def test_allocate_weighted_proportional_caps_and_redistribution():
    big = {"a": 99, "b": 99, "c": 99}
    assert r2.allocate_weighted(10, {"a": 1, "b": 1, "c": 2}, big) == {"a": 3, "b": 2, "c": 5}
    assert r2.allocate_weighted(8, {"a": 0.455, "b": 0.13, "c": 0.48}, big) == {
        "a": 3, "b": 1, "c": 4,
    }
    # 상한에 걸린 몫은 나머지에 다시 비례로: c 는 2 까지만, 남은 8 을 a:b = 3:1 로
    assert r2.allocate_weighted(10, {"a": 3, "b": 1, "c": 4}, {"a": 99, "b": 99, "c": 2}) == {
        "a": 6, "b": 2, "c": 2,
    }
    # 가중치 0(수율 0)·상한 0 은 받지 않고, 전체가 상한보다 크면 상한까지만
    assert r2.allocate_weighted(10, {"a": 1, "b": 0, "c": 1}, {"a": 3, "b": 9, "c": 0}) == {
        "a": 3, "b": 0, "c": 0,
    }
    assert r2.allocate_weighted(0, {"a": 1}, {"a": 5}) == {"a": 0}
    assert sum(r2.allocate_weighted(460, {"a": 0.408, "b": 0.158, "c": 0.264}, big).values()) == 297


# ---------------- 선정 ----------------

def _pool() -> list[dict]:
    rows = []
    for i in range(8):  # 도형 추정(상표명칭 비어 있음) — 종류별
        rows.append(_row(f"FR{i}", "refusal", "", month=f"2023{i + 1:02d}"))
        rows.append(_row(f"FI{i}", "invalidation", "", month=f"2022{i + 1:02d}"))
    rows += [_row(f"FS{i}", "scope", "", month="202001") for i in range(2)]
    for i in range(12):  # 문자 — has_meaning True(뜻…)·False, 심결월 다양
        rows.append(_row(f"WR{i}", "refusal", f"뜻{i}" if i % 2 else f"조어{i}",
                         month=f"2024{i + 1:02d}"))
        rows.append(_row(f"WI{i}", "invalidation", f"뜻{i}", month=f"2021{i + 1:02d}"))
        rows.append(_row(f"WS{i}", "scope", f"뜻{i}" if i < 3 else f"조어{i}", month="201905"))
    return rows


def test_select_round_share_meaning_priority_and_exclusions():
    rows = _pool() + [
        _row("C1", "취소", ""),  # 유사 판단이 없는 종류
        _row("N1", "refusal", "", doc="N"),  # 심결문 없음
        _row("GOT", "scope", "", claimant="갑", respondent="을", registration="4000001"),
        _row("FAM", "scope", "", claimant="갑", respondent="을", registration="4000001"),
        _row("DUP1", "refusal", "", month="202312", claimant="한회사"),
        _row("DUP2", "refusal", "", month="202312", claimant="한 회사"),  # 같은 청구인·같은 달
    ]
    selection = _select(rows, _evidence(), total=20, attempted={"GOT"})
    queue = selection.queue
    numbers = [row["심판번호"] for row in queue]
    assert len(queue) == 20 and len(set(numbers)) == 20 and selection.kept == 0
    assert not {"C1", "N1", "GOT", "FAM"} & set(numbers)  # 받은 건과 그 family, 제외 종류
    assert len({"DUP1", "DUP2"} & set(numbers)) == 1  # 청구인당 월 1건
    figure = [row for row in queue if row["도형추정"] == "Y"]
    assert selection.figure_target == 12 and len(figure) == 12  # 60%
    assert all(row["상표명칭"] == "" and row["has_meaning"] == "" for row in figure)
    # 근거 20건이라 추정 불안이 아니다 → probe 표시 없음
    assert all(row["선정사유"] == "도형 추정(상표명칭 비어 있음)" for row in figure)
    # 도형 추정은 종류 수율에 비례(권리범위 0.5 > 거절 0.4 > 무효 0.13). 권리범위 후보는 2건뿐
    by_kind = {kind: sum(1 for row in figure if row["종류"] == DESC[kind]) for kind in r2.KINDS}
    assert by_kind["scope"] == 2 and by_kind["refusal"] > by_kind["invalidation"] >= 1
    # 도형 추정 안에서는 최근 심결월부터
    refusal_months = [row["심결월"] for row in figure if row["종류"] == DESC["refusal"]]
    assert refusal_months == sorted(refusal_months, reverse=True)

    words = [row for row in queue if row["도형추정"] != "Y"]
    assert len(words) == 8
    for kind in r2.KINDS:  # 종류 안에서 has_meaning True 가 먼저, 같은 값이면 최근 심결월 먼저
        picked = [row for row in words if row["종류"] == DESC[kind]]
        flags = [row["has_meaning"] for row in picked]
        assert flags == sorted(flags, reverse=True)  # "Y" 다음 "N"
        months = [row["심결월"] for row in picked if row["has_meaning"] == "Y"]
        assert months == sorted(months, reverse=True)
    assert all(row["선정사유"] == r2.GROUP_MEANING for row in words if row["has_meaning"] == "Y")
    refusal_words = [row for row in words if row["종류"] == DESC["refusal"]]
    assert refusal_words and refusal_words[0]["심판번호"] == "WR11"  # 뜻11, 2024-12
    # 문자 종류 가중치: 거절 0.4 > 권리범위 0.53×0.5 > 무효 0.13
    word_kinds = {kind: sum(1 for row in words if row["종류"] == DESC[kind]) for kind in r2.KINDS}
    assert word_kinds["refusal"] > word_kinds["scope"] > word_kinds["invalidation"] >= 1


def test_select_round_is_reproducible_for_a_seed():
    rows = [_row(f"T{i}", "refusal", "뜻", month="202401") for i in range(40)]  # 전부 동률
    trials = _evidence()
    first = _select(rows, trials, total=10, seed=0).queue
    assert first == _select(rows, trials, total=10, seed=0).queue
    assert first == _select(list(reversed(rows)), trials, total=10, seed=0).queue  # 입력 순서 무관
    others = [_select(rows, trials, total=10, seed=seed).queue for seed in range(1, 6)]
    assert any(queue != first for queue in others)
    # 후보가 줄어도(일부를 이미 받음) 남은 후보의 동률 순서는 그대로다
    rest = [row for row in rows if row["심판번호"] != first[0]["심판번호"]]
    assert [r["심판번호"] for r in _select(rest, trials, total=9, seed=0).queue] == [
        r["심판번호"] for r in first[1:]
    ]


def test_select_round_puts_probe_first_when_evidence_is_thin(monkeypatch):
    monkeypatch.setattr(r2, "PROBE_N", 9)
    selection = _select(_pool(), _evidence(empty_known=17, empty_figure=17), total=20)
    queue = selection.queue
    assert selection.probe == 9 and len(queue) == 20
    head = queue[:9]
    assert all(row["도형추정"] == "Y" and row["선정사유"].endswith("·probe") for row in head)
    assert not any("probe" in row["선정사유"] for row in queue[9:])
    # 도형 추정 12건 = 거절 7·무효 3·권리범위 2(후보 전부). probe 는 종류별로 고르게 3건씩 — 모자란
    # 종류(권리범위 2)의 몫은 남은 종류로 — 한 건씩 돌아가며 놓는다
    kinds = [row["종류"] for row in head]
    assert [kinds.count(DESC[kind]) for kind in r2.KINDS] == [4, 3, 2]
    assert set(kinds[:3]) == set(DESC.values())


def test_select_round_without_adopted_condition_uses_kind_yields_only():
    trials = _evidence(empty_known=20, empty_figure=5)  # 정밀도 0.25 → 채택 없음
    selection = _select(_pool(), trials, total=20)
    assert selection.figure_target == 0 and selection.probe == 0 and len(selection.queue) == 20
    assert all(row["도형추정"] == "" for row in selection.queue)
    # 상표명칭이 빈 건도 그냥 문자 묶음 후보(has_meaning N)라 뜻 있는 이름 뒤로 밀린다
    assert all(row["has_meaning"] == "N" for row in selection.queue if not row["상표명칭"])
    for kind in r2.KINDS:
        flags = [row["has_meaning"] for row in selection.queue if row["종류"] == DESC[kind]]
        assert flags == sorted(flags, reverse=True)
    # 종류는 수율(문자·has_meaning) × 가중치에 비례: 거절 0.4 > 권리범위 0.53×0.5 > 무효 0.13
    counts = [sum(1 for row in selection.queue if row["종류"] == DESC[kind]) for kind in r2.KINDS]
    assert counts == [10, 3, 7]


def test_rerun_keeps_attempted_rows_and_reallocates_the_rest():
    rows = _pool()
    trials = _evidence()
    first = _select(rows, trials, total=20).queue
    attempted = {row["심판번호"] for row in first[:6]}
    again = _select(rows, trials, total=20, attempted=attempted, previous=first)
    assert again.kept == 6 and again.queue[:6] == first[:6]  # 받은 건은 그대로 맨 앞
    assert len(again.queue) == 20 and len({row["심판번호"] for row in again.queue}) == 20
    assert sum(1 for row in again.queue if row["도형추정"] == "Y") == 12  # 받은 도형 건 포함 60%
    # 새 근거에서 가설이 깨지면(정밀도 < 0.5) 받은 도형 추정 건은 두고 나머지는 문자 사건으로
    broken = _evidence(empty_known=40, empty_figure=10)
    changed = _select(rows, broken, total=20, attempted=attempted, previous=first)
    kept_figure = sum(1 for row in first[:6] if row["도형추정"] == "Y")
    assert changed.queue[:6] == first[:6] and changed.figure_target == kept_figure
    assert sum(1 for row in changed.queue if row["도형추정"] == "Y") == kept_figure


# ---------------- CLI ----------------

def _analysis(number: str, **fields) -> dict:
    row = {column: "" for column in tc.PREFILTER_COLUMNS}
    row.update({"심판번호": number, "텍스트길이": 5000, "추출실패": 0, "주문결과": "기각"})
    row.update(fields)
    return row


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_sample_round_cli_writes_queue_and_plan(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(r2, "_load_has_meaning", lambda: _meaning)
    paths_ = tc.TrialPaths(tmp_path)
    received = []
    prefilter = []
    for i in range(20):  # 받은 권리범위확인 20건 — 상표명칭 비어 있음, 절반이 1등급
        number = f"S{i:02d}"
        received.append(_row(number, "scope", "", claimant=f"갑{i}", registration=f"40{i:05d}"))
        prefilter.append(_analysis(
            number, 주문결과="속함", 표장유사_소결="유사" if i % 2 else "",
            이사건_등록번호=f"40{i:05d}",
        ))
    for i in range(20):  # 받은 거절결정불복 20건 — 문자, 7호 긍정 8건
        number = f"R{i:02d}"
        received.append(_row(number, "refusal", f"뜻{i}"))
        prefilter.append(_analysis(
            number, 결론조문="34-7:긍정" if i < 8 else "33:긍정",
            선등록_등록번호=f"41{i:05d}",
        ))
    candidates = [_row(f"NF{i}", "refusal", "", month=f"2025{i + 1:02d}") for i in range(6)]
    candidates += [
        _row(f"NW{i}", "refusal", f"뜻새{i}", month=f"2026{i + 1:02d}") for i in range(6)
    ]
    tc._write_csv(paths_.list_all_csv, tc.LIST_COLUMNS, received + candidates)
    tc._write_csv(paths_.prefilter_csv, tc.PREFILTER_COLUMNS, prefilter)
    tc._write_csv(paths_.fetch_log, tc.FETCH_LOG_COLUMNS,
                  [{"심판번호": row["심판번호"], "결과": "ok"} for row in received])
    labels = [{"심판번호": f"S{i:02d}", "상표유형_확정": "도형"} for i in range(20)]
    tc._write_csv(paths_.labels_csv, ["심판번호", "상표유형_확정"], labels)

    args = ["--data-dir", str(tmp_path), "sample", "--round", "2", "--total", "10", "--seed", "0"]
    assert tc.main(args) == 0
    out = capsys.readouterr().out
    queue = _rows(paths_.round_queue(2))
    assert list(queue[0]) == r2.QUEUE_COLUMNS and len(queue) == 10
    assert [row["도형추정"] for row in queue].count("Y") == 6  # 60%
    assert "### 1. 종류별 1등급 수율" in out
    assert "거절결정불복: 받은 20건 중 1등급 8/20(0.40)" in out
    assert "비어 있음: 받은 20 · LLM 도형계 20/문자계 0" in out and "→ 채택" in out
    assert "추정 불안" not in out  # 근거 20건
    assert "예상 호출 20회(미수신 10건 × 2)" in out
    # 회차는 큐 파일에서 읽는다 — 이 큐의 건은 sheet 에서 round 2 가 된다
    assert tc.load_rounds(paths_) == {row["심판번호"]: "2" for row in queue}

    assert tc.main(args) == 0  # 다시 돌려도 같은 큐(멱등)
    assert _rows(paths_.round_queue(2)) == queue
    capsys.readouterr()
    assert tc.main(["--data-dir", str(tmp_path), "sample", "--round", "1"]) == 2
    assert "--round 는 2 이상" in capsys.readouterr().err
