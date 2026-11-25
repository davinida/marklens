"""famous_check_measure.py(유명 상표 확인 2-1단계 측정 — 통합 모델 설계 §7-14)의 순수 함수: 표본
만들기(1단계 그대로), 확인용 보호, 기준·S 선택 규칙, 목표, 기대표."""

from __future__ import annotations

import json

import pytest
from src import famous_check as fc

from scripts import famous_check_measure as fm


def _notation(text: str, *, weak: bool = False, kind: str | None = None) -> fc.Notation:
    key = fc.text_key(text)
    return fc.Notation(text=text, key=key, pieces=tuple(fc.split_pieces(fc.normalize_text(text))),
                       script=fc.script_label(key), length=fc.length_class(key),
                       kind=kind or (fc.KIND_WEAK if weak else fc.KIND_NORMAL), base_weak=weak)


def _brand(name: str, notations, *, preset="cafe", codes=("G0301",)) -> fc.Brand:
    return fc.Brand(name=name, notations=tuple(notations), applicants=(name,),
                    applicant_keys=frozenset({name}), preset=preset, preset_label=None,
                    preset_codes=frozenset(codes), evidence="", evidence_urls=(),
                    protection=fc.PROTECT_ANY, goods_codes=frozenset(codes),
                    goods_source="업종 세트", marks=())


def test_settings_hash_and_fixed_lists():
    assert fm.rule_sha256() == fm.rule_sha256()
    assert {"목적", "1_표기_종류", "2_낱말_나누기", "3_설명_낱말", "4_통째_비교",
            "5_보통_표기의_경로", "6_약한_철자의_소리_조건", "7_약한_표기", "8_브랜드_업종",
            "9_로고", "10_그대로", "표본", "기준_선택", "목표", "기대표", "함께_잴_것",
            "스모크"} == set(fm.RULE)
    assert len(fm.P2_PAIRS) == 28 and len(fm.N4_TRAPS) == 38
    assert (fm.STRONG_SPELLING_GRID, fm.WEAK_SOUND_GRID, fm.WEAK_SPELLING_GRID) == (
        (0.90, 0.95), (0.90, 0.92, 0.94, 0.96), (0.75, 0.80, 0.85, 0.90))
    assert fm.SOUND_CONDITION_GRID == (None, 0.70, 0.80) and fm.RECALL_DROP_MAX == 0.02
    assert (fm.N1_RATE_MAX, fm.N3_RATE_MAX, fc.STRONG_SOUND) == (0.005, 0.02, 0.98)
    assert fm.STAGE1_SAMPLES_SHA256.startswith("5bec460c")  # 표본은 1단계에 고정한 것 그대로
    counts = {label: sum(1 for row in fm.EXPECT if row[0] == label)
              for label in (fm.E_STRONG, fm.E_WEAK_PLUS, fm.E_WEAK, fm.E_NOTICE, fm.E_NONE,
                            fm.E_WISH_WEAK, fm.E_WISH_NONE)}
    assert list(counts.values()) == [35, 6, 6, 4, 24, 3, 3]
    assert fm.TARGETS["N1_강함"] == 0 and fm.TARGETS["N1_약함_최대"] == 2
    assert fm.TARGETS["P3_보통_약함_이상_최소"] == 0.95
    names = [name for name, _ in fm.PREVIEW_NAMES]
    assert names.count("스타벅스") == 3 and {"@F1", "@F2", "@F3", "@S1"} <= set(names)
    assert fm.PREVIEW_HOLDOUT_SEEN == ("헤르메스",)  # P2 확인용 중 지시의 목록에 든 것


def test_frozen_rule_matches_the_script_when_present():
    path = fm._paths(fm.TRIALS)["rule"]  # noqa: SLF001
    if not path.exists():
        pytest.skip("고정본 없음(비공개 데이터)")
    frozen = json.loads(path.read_text(encoding="utf-8"))
    assert frozen["설정_sha256"] == fm.rule_sha256()  # 고정한 뒤 규칙을 바꾸지 않았다
    assert frozen["표본_sha256"] == fm.STAGE1_SAMPLES_SHA256


def test_variant_generators():
    assert fm.spacing_variant("스타벅스") == "스타 벅스" and fm.spacing_variant("CU") == "C U"
    assert fm.spacing_variant("로레알 파리") == "로레알파리" and fm.spacing_variant("본") is None
    assert fm.case_variant("bhc") == "BHC" and fm.case_variant("STARBUCKS") == "starbucks"
    assert fm.case_variant("PAIK'S") == "paik's" and fm.case_variant("샤넬") is None
    hangul = dict(fm.hangul_variants("샤넬"))
    assert hangul == {"쌰넬": "예사·된·거센소리", "샬넬": "받침 ㄹ 넣기", "샤낼": "모음 ㅐ↔ㅔ",
                      "샤네": "받침 ㄹ 빼기"}
    kinds = {kind for _, kind in fm.hangul_variants("본죽")}
    assert {"모음 ㅓ↔ㅗ", "모음 ㅗ↔ㅜ", "모음 ㅡ↔ㅜ", "예사·된·거센소리",
            "받침 ㄴ↔ㅇ↔ㅁ"} <= kinds  # 본 → 번·분·폰·뽄·봉·봄, 죽 → 즉·족·쭉·축
    assert ("봉죽", "받침 ㄴ↔ㅇ↔ㅁ") in fm.hangul_variants("본죽")
    latin = fm.latin_variants("Google")
    assert ("Gogle", "겹글자 빼기") in latin and ("GGoogle", "겹글자 넣기") in latin
    assert ("Googla", "a↔e") in latin and ("Googlee", "겹글자 넣기") in latin
    assert ("GS25", "s↔z") not in fm.latin_variants("GS25")
    assert ("GZ25", "s↔z") in fm.latin_variants("GS25")  # 숫자는 건드리지 않는다
    assert all(kind != "겹글자 넣기" or len(text) == 7 for text, kind in latin)


def test_p3_variants_are_deterministic_and_avoid_taken_names():
    notation = _notation("스타벅스")
    first = fm.p3_variants("스타벅스", notation, set())
    again = fm.p3_variants("스타벅스", notation, set())
    assert first == again and len(first) == fm.P3_PER_NOTATION
    assert [item["반"] for item in first] == [fm.BASE, fm.BASE, fm.HOLDOUT, fm.HOLDOUT]
    assert all(item["길이"] == "김" and item["표기"] == "스타벅스" for item in first)
    taken = {fc.text_key(item["이름"]) for item in first}
    other = fm.p3_variants("스타벅스", notation, taken)
    assert not taken & {fc.text_key(item["이름"]) for item in other}
    short = fm.p3_variants("샤넬", _notation("샤넬"), {"샤낼", "쌰넬"})  # P2 의 이름은 뺀다
    assert sorted(item["이름"] for item in short) == ["샤네", "샬넬"]
    assert [item["반"] for item in short] == [fm.BASE, fm.BASE]


def test_sample_builders_keep_the_stage1_definition_of_weak():
    brand = _brand("교촌치킨", [_notation("교촌치킨"), _notation("교촌"), _notation("KYOCHON")])
    assert fm.target_notation("교춘", brand).text == "교촌"
    assert fm.target_notation("교촌치퀸", brand).text == "교촌치킨"
    assert fm.target_notation("KYOCHONE", brand).text == "KYOCHON"
    # 1단계의 약한 표기(base_weak)만 뺀다 — 소리가 같아 약한 표기가 된 표기(지에스25)는 그대로
    # 겨냥한 표기이고 변형도 만든다(표본이 1단계와 같아야 하므로)
    gs = _brand("GS25", [_notation("GS25", weak=True),
                         _notation("지에스25", kind=fc.KIND_WEAK)])
    assert fm.target_notation("GS24", gs).text == "지에스25"
    assert fm.target_notation("쥐에스25", gs).text == "지에스25"
    assert not gs.notations[1].base_weak and gs.notations[1].weak


def test_p2_kind_follows_the_notation_the_variant_imitates():
    kimgane = _brand("김가네", [_notation("김가네", weak=True), _notation("GIMGANE")])
    gs = _brand("GS25", [_notation("GS25", weak=True),
                         _notation("지에스25", kind=fc.KIND_WEAK)])
    bhc = _brand("bhc", [_notation("bhc", kind=fc.KIND_INITIAL),
                         _notation("비에이치씨", kind=fc.KIND_INITIAL)])
    star = _brand("스타벅스", [_notation("스타벅스"), _notation("STARBUCKS")])
    matcher = fm.Matcher(fc.Registry(fc.REGISTRY_VERSION, (kimgane, gs, bhc, star)), None, 0.0)

    def kind(name, brand, labelled, variant=fm.P2_VARIANT):
        return matcher.kind({"이름": name, "브랜드": brand, "표기": labelled, "변형": variant})

    # 1단계 표본은 김가내의 표기를 GIMGANE(약하지 않은 표기)로 적었지만 겨냥한 것은 김가네다
    assert kind("김가내", "김가네", "GIMGANE") == fc.KIND_WEAK
    assert kind("GS24", "GS25", "지에스25") == fc.KIND_WEAK
    assert kind("비에치씨", "bhc", "비에이치씨") == fc.KIND_INITIAL
    assert kind("스타벅수", "스타벅스", "스타벅스") == fc.KIND_NORMAL
    assert fm.imitated_notation("GIMGANA", kimgane, "GIMGANE").text == "GIMGANE"
    # P3 는 변형을 만든 그 표기의 종류 그대로
    assert kind("GIMGANA", "김가네", "GIMGANE", variant="a↔e") == fc.KIND_NORMAL
    assert kind("김가내", "김가네", "GIMGANE", variant="모음 ㅐ↔ㅔ") == fc.KIND_NORMAL


def test_unrelated_preset_and_own_words():
    presets = [{"id": f"p{i}", "별칭": [f"낱말{i}"]} for i in range(10)]
    codes = {f"p{i}": [f"G{i:04d}"] for i in range(10)}
    brand = _brand("가", [_notation("가나다")], preset="p1", codes=("G0001", "G0008"))
    assert fm.unrelated_preset(brand, presets, codes)["id"] == "p9"  # p8 은 겹쳐서 건너뜀
    everywhere = _brand("나", [_notation("가나다")], preset="p1",
                        codes=tuple(f"G{i:04d}" for i in range(10)))
    assert fm.unrelated_preset(everywhere, presets, codes)["id"] != "p1"  # 겹침이 가장 작은 것

    class Dist:
        goods_names = frozenset({"커피", "떡볶이"})

    assert fm.own_words({"별칭": ["카페", "커피숍", "커피"]}, Dist()) == [
        ("업종 낱말", "카페"), ("상품 낱말", "커피")]
    assert fm.own_words({"별칭": ["떡볶이", "분식"]}, Dist()) == [("업종 낱말", "떡볶이")]
    assert fm.own_words({"별칭": ["세탁소", "세탁"]}, Dist()) == [("업종 낱말", "세탁소")]


def test_holdout_items_are_never_evaluated():
    items = [{"이름": "가", "반": fm.BASE}, {"이름": "나", "반": fm.HOLDOUT},
             {"이름": "다", "반": None}, {"이름": "라", "반": fm.BASE, "중복": True}]
    assert [item["이름"] for item in fm.base_items(items)] == ["가", "다"]
    assert [item["이름"] for item in fm.base_items(items, 1)] == ["가"]
    matcher = fm.Matcher(fc.Registry(fc.REGISTRY_VERSION, ()), None, 0.0252)
    with pytest.raises(ValueError):
        matcher.evidence({"이름": "나", "반": fm.HOLDOUT, "업종": None})
    samples = {"P1": [{"이름": "CU", "반": None}], "P2": [{"이름": "헤르메스", "반": fm.HOLDOUT}],
               "P3": [], "N1": [{"이름": "C U", "반": fm.HOLDOUT}, {"이름": "가", "반": fm.BASE}],
               "N2": [{"이름": "가", "반": None}], "N3": [], "N4": []}
    overlap = fm.holdout_overlap(samples)
    assert overlap["P1"] == [{"이름": "CU", "확인용": ["N1 확인용"]}]
    assert {"이름": "헤르메스", "확인용": ["P2 확인용"]} in overlap["미리 보기"]
    assert {"이름": "헤르메스", "확인용": ["P2 확인용"]} in overlap["기대표"]
    assert "N2" not in overlap and "N1" not in overlap


class _FakeMatcher:
    """근거를 손으로 준 Matcher — 질의마다 (길이, 소리, 철자) 한 표기, 대상 브랜드는 "가"."""

    dist, floor = None, 0.0252

    def decide(self, item: dict, thresholds: fc.Thresholds) -> fc.FamousResult:
        units = ((item["이름"], item["소리"], item["철자"]),)
        evidence = [fc.BrandEvidence(brand="가", protection=fc.PROTECT_ANY, overlap=None,
                                     overlap_value=None, items=(fc.Evidence(
                                         notation="가", key="가", length=item["길이"],
                                         kind=item.get("종류", fc.KIND_NORMAL),
                                         exact=item.get("같음", False), units=units,
                                         weak_use=item.get("쓰임"),
                                         foreign_weak=item.get("다른_업종_약함")),))]
        return fc.decide(evidence, thresholds)

    def own(self, item: dict, thresholds: fc.Thresholds) -> fc.BrandMatch | None:
        return next((m for m in self.decide(item, thresholds).matches
                     if m.brand == item.get("브랜드", "가")), None)

    def kind(self, item: dict) -> str:
        return item.get("종류", fc.KIND_NORMAL)


def _queries(count: int, length: str, sound: float, spelling: float, **more) -> list[dict]:
    return [{"이름": f"{length}{sound}{spelling}{index}", "길이": length, "소리": sound,
             "철자": spelling, "브랜드": "가", "표기": "가", "변형": "ㄱ", "업종_표시": "없음",
             "업종": None, **more} for index in range(count)]


def test_threshold_selection_follows_the_fixed_rule():
    # N1 1,000 질의(한도 0.5% = 5건), N3 100 질의(한도 2% = 2건)
    n1 = (_queries(6, "김", 0.91, 0.0)        # 김·약한 소리 0.90 이면 6건 → 한도 초과, 0.92 부터 0
          + _queries(5, "중간", 0.95, 0.0)    # 중간·약한 소리 0.90 에서 5건 = 한도 → 0.90
          + _queries(4, "김", 0.75, 0.82)     # 김·약한 철자 0.80 이하면 4건(소리 0.75)
          + _queries(3, "김", 0.93, 0.0)      # 김·약한 소리 0.92 에서 3건 — 철자와 합쳐 누적
          + _queries(1, "짧음", 0.0, 0.96)    # 짧음·강한 철자 0.90·0.95 둘 다 새 강한 일치 1건
          + _queries(1, "중간", 0.0, 0.93)    # 중간·강한 철자 0.90 이면 1건 → 0.95
          + _queries(2, "짧음", 0.0, 0.92, 같음=True)  # 이미 같음으로 잡힌 것 — 새 일치가 아님
          + _queries(978, "김", 0.5, 0.5))
    n3 = (_queries(3, "짧음", 0.97, 0.0)      # 짧음·약한 소리는 N3 3건(3%) → 어떤 값도 안 됨
          + _queries(97, "김", 0.1, 0.1))
    p2 = _queries(10, "김", 0.5, 0.86)        # 소리 0.5 — S 를 걸면 모두 놓친다
    p3 = _queries(40, "김", 0.75, 0.86) + _queries(60, "김", 0.99, 0.0)
    table = fm.select_thresholds(_FakeMatcher(), n1, n3, p2, p3)
    chosen = table["고른_기준"]
    assert chosen["strong_sound"] == 0.98
    # 강한 철자는 길이 구간별, 새로 생기는 강한 일치 0건
    assert chosen["strong_spelling"] == {"짧음": None, "중간": 0.95, "김": 0.9}
    short = {row["값"]: row for row in table["강한_철자"]["격자"]["짧음"]}
    assert short[0.9]["N1_새_강한_일치"] == 1 and short[0.9]["조건(0건)"] is False
    assert short[0.9]["0.5%·2%_한도로_보면"] is True  # 1/1000 은 0.5% 안 — 그래도 고르지 않는다
    assert chosen["weak_sound"] == {"짧음": None, "중간": 0.9, "김": 0.92}
    # 조건 없이: 김은 약한 소리 0.92(3건)에 철자 0.80 이하(4건)를 더하면 7 > 5 → 0.85
    assert table["약한_철자(조건_없음)"]["고른_값"]["김"] == 0.85
    # S: P2 는 소리 0.5 라 0.70 만 걸어도 재현율 1.0 → 0.0 — 통과하는 값이 없어 조건 없음
    assert table["S"]["고른_값"] is None and chosen["spelling_sound"] is None
    rows = {row["S"]: row for row in table["S"]["격자"]}
    assert rows[None]["P2_재현율"] == 1.0 and rows[0.7]["P2_재현율"] == 0.0
    assert rows[0.7]["조건"] is False and rows[0.7]["P3_떨어진_폭"] == 0.0
    assert chosen["weak_spelling"] == table["약한_철자(조건_없음)"]["고른_값"]
    # 짧음: 철자 0.96 한 건(강한 철자로는 못 고른 것)이 약한 철자 0.75 로 들어온다. 중간: 약한 소리
    # 5건에 철자 0.93 한 건을 더하면 6 > 5 — 어떤 값도 안 됨
    assert chosen["weak_spelling"] == {"짧음": 0.75, "중간": None, "김": 0.85}
    assert table["고른_기준에서_새로_더한_일치(전체)"]["N1"] == 9  # 중간 5 + 김 3 + 짧음 1


def test_sound_condition_is_chosen_and_spelling_is_picked_again():
    n1 = (_queries(4, "김", 0.75, 0.82)       # S 0.80 을 걸면 사라지는 철자 헛일치
          + _queries(3, "김", 0.93, 0.0) + _queries(993, "김", 0.5, 0.5))
    n3 = _queries(100, "김", 0.1, 0.1)
    p2 = _queries(10, "김", 0.85, 0.86)
    p3 = _queries(98, "김", 0.9, 0.86) + _queries(2, "김", 0.75, 0.86)  # S 0.80 에서 2% 놓침
    table = fm.select_thresholds(_FakeMatcher(), n1, n3, p2, p3)
    assert table["약한_소리"]["고른_값"]["김"] == 0.9  # 3건 = 0.3%
    assert table["약한_철자(조건_없음)"]["고른_값"]["김"] == 0.85  # 0.80 이하면 누적 7 > 5
    rows = {row["S"]: row for row in table["S"]["격자"]}
    assert rows[0.8]["P3_떨어진_폭"] == 0.02 and rows[0.8]["조건"] is True  # 2%p 까지는 된다
    assert table["S"]["고른_값"] == 0.8  # 통과하는 값 중 가장 높은 것
    # 고른 S 로 약한 철자만 다시 — 소리 0.75 인 헛일치 4건이 빠져 0.75 까지 내려간다
    assert table["약한_철자"]["고른_값"]["김"] == 0.75
    assert table["고른_기준"]["spelling_sound"] == 0.8
    assert table["고른_기준"]["weak_spelling"]["김"] == 0.75
    worse = fm.select_thresholds(_FakeMatcher(), n1, n3, p2,
                                 _queries(97, "김", 0.9, 0.86) + _queries(3, "김", 0.75, 0.86))
    assert worse["S"]["고른_값"] == 0.7  # 0.80 은 3%p 떨어져 안 되고 0.70 은 된다


def test_recall_tables_and_match_lists():
    matcher = _FakeMatcher()
    thresholds = fc.Thresholds(weak_sound={"김": 0.9})
    items = (_queries(1, "김", 0.99, 0.0) + _queries(1, "김", 0.93, 0.0)
             + _queries(1, "중간", 0.93, 0.0, 변형="ㄴ")
             + _queries(1, "김", 0.99, 0.0, 종류=fc.KIND_INITIAL))
    table = fm.recall_table(matcher, items[:3], thresholds)
    assert table["전체"] == {"n": 3, "강함": 1, "약함": 1, "안내": 0, "놓침": 1,
                           "약함_이상_비율": 0.6667}
    assert table["길이별"]["중간"]["놓침"] == 1 and table["변형별"]["ㄱ"]["강함"] == 1
    assert [row["이름"] for row in table["놓친_것"]] == [items[2]["이름"]]
    by_kind = fm.recall_by_kind(matcher, items, thresholds)
    assert by_kind[fc.KIND_NORMAL]["전체"]["n"] == 3  # 보통 표기만 따로
    assert by_kind[fc.KIND_INITIAL]["전체"] == {"n": 1, "강함": 0, "약함": 0, "안내": 0,
                                            "놓침": 1, "약함_이상_비율": 0.0}
    assert by_kind[fc.KIND_WEAK]["전체"]["n"] == 0
    assert fm.recall(matcher, items[:3], thresholds) == pytest.approx(2 / 3)
    assert fm.recall(matcher, [], thresholds) is None
    listed = fm.match_list(matcher, items[:3], thresholds)
    assert listed["질의"] == 3 and listed["일치한_질의"] == 2
    assert listed["수준"] == {"강함": 1, "약함": 1} and listed["경로"] == {"소리": 2}
    assert fm.grade_max("주의", None, "검토 권장") == "검토 권장" and fm.grade_max(None) is None


def test_p1_table_allows_only_weak_notations_in_another_industry():
    matcher = _FakeMatcher()
    weak = {"종류": fc.KIND_WEAK, "쓰임": fc.WEAK_USE_ALONE}
    items = (_queries(2, "김", 0.0, 0.0, 같음=True)  # 강함
             + _queries(1, "짧음", 0.0, 0.0, **weak)  # 약한 표기 단독·업종 없음 → 강함
             + _queries(1, "짧음", 0.0, 0.0, **weak, 다른_업종_약함=True, 업종=["S1"],
                        업종_표시="무관한 업종(x)", 변형="무관한 업종 낱말")
             + _queries(1, "짧음", 0.0, 0.0, 종류=fc.KIND_WEAK,
                        쓰임=fc.WEAK_USE_WITH_OTHERS, 변형="업종 낱말 띄어서")
             + _queries(1, "김", 0.0, 0.0, 변형="업종 낱말 붙여서"))
    # 업종이 다른 경우는 겹침이 False 여야 안내가 된다 — 가짜 근거의 겹침을 맞춘다
    original = matcher.decide

    def decide(item, thresholds):
        result = original(item, thresholds)
        if item["업종"] is None:
            return result
        evidence = [fc.BrandEvidence(brand="가", protection=fc.PROTECT_ANY, overlap=False,
                                     overlap_value=0.0, items=(fc.Evidence(
                                         notation="가", key="가", length="짧음",
                                         kind=fc.KIND_WEAK, weak_use=fc.WEAK_USE_ALONE,
                                         foreign_weak=True),))]
        return fc.decide(evidence, thresholds)

    matcher.decide = decide
    table = fm.p1_table(matcher, items, fc.Thresholds())
    assert (table["n"], table["강함"], table[fm.P1_ALLOWED], table["그_밖"]) == (6, 3, 1, 2)
    reasons = list(table["그_밖_사유별"])
    assert any("다른 말과 함께" in reason for reason in reasons)
    assert any(reason.endswith("일치 없음") for reason in reasons)
    results = {"P1": table, "N1": {"수준": {"약함": 2}}, "N2": {"수준": {"강함": 1}},
               "N3": {"수준": {}},
               "P2": {fc.KIND_NORMAL: {"전체": {"n": 50, "약함_이상_비율": 1.0}}},
               "P3": {fc.KIND_NORMAL: {"전체": {"n": 200, "약함_이상_비율": 0.94}}}}
    done = fm.targets(results)
    assert [row["통과"] for row in done.values()] == [True, True, False, True, True, False, False]


def test_expectation_table_compares_levels():
    matcher = _FakeMatcher()
    lookup = {"스타벅스": {"같음": True}, "스타벅수": {"소리": 0.95}, "블루커피": {},
              "텍사스 BBQ": {"종류": fc.KIND_WEAK, "쓰임": fc.WEAK_USE_WITH_OTHERS}}
    original = matcher.decide

    def decide(item, thresholds):
        extra = lookup.get(item["이름"], {})
        return original({"길이": "김", "소리": 0.0, "철자": 0.0, **item, **extra}, thresholds)

    matcher.decide = decide
    control = {"대조군": {"이름": {fm.BASE: [
        {"이름": f"지어낸{i}", "유사군": ["S1"], "업종_세트": "x"} for i in range(3)]}}}
    samples = {"N1": [{"이름": "Airline Seoul", "업종": ["S9"], "반": fm.BASE},
                      {"이름": "숨긴 이름", "업종": ["S9"], "반": fm.HOLDOUT}]}
    table = fm.expectation(matcher, fc.Thresholds(weak_sound={"김": 0.9}),
                           lambda key: (None if key is None else [key], key or "없음"),
                           control, samples)
    rows = {(row["입력"], row["업종"]): row for row in table["행"]}
    assert rows[("스타벅스", "cafe")]["맞음"] is True and rows[("스타벅수", "없음")]["맞음"] is True
    assert rows[("블루커피", "cafe")]["결과"] == "없음" and rows[("블루커피", "cafe")]["맞음"]
    assert rows[("텍사스 BBQ", "korean_restaurant")]["결과"] == "설명적 사용 안내"
    assert rows[("BBQ", "chicken")]["맞음"] is False  # 가짜 근거에는 일치가 없다
    assert rows[("Airline Seoul", "그 상표의 지정상품(N1 기준용)")]["맞음"] is True
    assert rows[("지어낸0", "x(대조군 배정)")]["맞음"] is True
    assert any(row["결과"] == "표본에 없음" for row in table["행"])  # PLAY KIA 등은 표본에 없음
    assert rows[("헤르메스", "clothing")]["확인용"] is True
    summary = table["요약"]
    assert summary[fm.E_NOTICE]["n"] == 4 and summary[fm.E_NOTICE]["맞음"] == 1
    assert summary[fm.E_NONE]["맞음"] >= 19


def test_recheck_drops_samples_the_registry_can_no_longer_judge():
    star = _brand("스타벅스", [_notation("스타벅스")])  # STARBUCKS 표기를 지운 등록부
    samsung = fc.Brand(**{**_brand("삼성", [_notation("삼성")]).__dict__,
                          "applicant_keys": frozenset({"삼성전자"}), "is_new": True})
    registry = fc.Registry(fc.REGISTRY_VERSION, (star, samsung))
    matcher = fm.Matcher(registry, None, 0.0)
    samples = {
        "P1": [{"이름": "스타벅스", "브랜드": "스타벅스", "표기": "스타벅스", "반": None},
               {"이름": "STARBUCKS", "브랜드": "스타벅스", "표기": "STARBUCKS", "반": None}],
        "P3": [{"이름": "STARBUCKZ", "브랜드": "스타벅스", "표기": "STARBUCKS",
                "반": fm.BASE}],
        "P2": [{"이름": "스타벅수", "브랜드": "스타벅스", "표기": "스타벅스", "반": fm.BASE,
                "변형": fm.P2_VARIANT},
               {"이름": "STARBUCKSS", "브랜드": "스타벅스", "표기": "STARBUCKS", "반": fm.BASE,
                "변형": fm.P2_VARIANT},
               {"이름": "스타벅슈", "브랜드": "스타벅스", "표기": "스타벅스", "반": fm.HOLDOUT,
                "변형": fm.P2_VARIANT}],
        "N1": [{"이름": "Galaxy", "출원인": "삼성전자", "반": fm.BASE},
               {"이름": "IDEA", "출원인": "다른 회사", "반": fm.BASE},
               {"이름": "확인용", "출원인": "다른 회사", "반": fm.HOLDOUT}],
        "N2": [{"이름": "ON PACKS", "반": None}], "N3": [], "N4": []}
    items, dropped = fm.usable_samples(samples, registry, matcher,
                                       lambda text: frozenset({text}))
    assert [item["이름"] for item in items["P1"]] == ["스타벅스"]
    assert items["P3"] == [] and [item["이름"] for item in items["P2"]] == ["스타벅수"]
    assert [item["이름"] for item in items["N1"]] == ["IDEA"]  # 확인용은 애초에 빠진다
    assert len(dropped["지운_표기의_표본"]) == 3  # STARBUCKS 를 겨냥한 P1·P3·P2
    assert dropped["등록부_출원인이_된_N1"] == ["Galaxy — 삼성전자"]


def test_matcher_finds_a_renamed_brand_by_its_table_name():
    renamed = fc.Brand(**{**_brand("본죽", [_notation("본죽")]).__dict__,
                          "table_name": "본죽&비빔밥"})
    matcher = fm.Matcher(fc.Registry(fc.REGISTRY_VERSION, (renamed,)), None, 0.0)
    assert matcher.kind({"브랜드": "본죽&비빔밥", "표기": "본죽"}) == fc.KIND_NORMAL
    assert matcher.names == {"본죽&비빔밥": "본죽"}
    assert fc.Registry(fc.REGISTRY_VERSION, (renamed,)).brand("본죽&비빔밥") is renamed


def test_recheck_diff_reports_only_what_changed():
    def result(n1_weak, rows, n1_names, p1=(865, 870), dropped=()):
        match = {"브랜드": "자라", "수준": "약함", "경로": "철자"}
        return {
            "목표": {"N1 기준용 약함 2건 이하": {"값": n1_weak, "통과": n1_weak <= 2},
                   "N3 기준용 0건": {"값": 0, "통과": True}},
            "기대표": {"행": [{"기대": "없음", "입력": name, "업종": "없음", "결과": value}
                          for name, value in rows]},
            "N1": {"목록": [{"이름": name, "일치": match} for name in n1_names]},
            "N2": {"목록": []}, "N3": {"목록": []},
            "P1": {"강함": p1[0], "n": p1[1]},
            "P2": {fc.KIND_NORMAL: {"전체": {"n": 50, "강함": 26}}},
            "P3": {fc.KIND_NORMAL: {"전체": {"n": 228, "강함": 110}}},
            "뺀_표본": {"등록부_출원인이_된_N1": list(dropped)}}

    before = result(4, [("삼성", "설명적 사용 안내"), ("구굴", "약함")], ["PARA PARA", "ZARI"])
    same = fm.recheck_diff(before, before)
    assert same["같음"] and fm.recheck_diff_text(same) == "직전 결과와 달라진 것: 없음"
    after = result(3, [("삼성", "강함"), ("구굴", "약함")], ["ZARI", "ZARO"], p1=(866, 870),
                   dropped=["Q7F — 삼성전자"])
    diff = fm.recheck_diff(before, after)
    assert not diff["같음"]
    assert diff["목표"] == {"N1 기준용 약함 2건 이하": {"직전": 4, "지금": 3, "통과": False}}
    assert diff["기대표"] == [{"기대": "없음", "입력": "삼성", "업종": "없음",
                            "직전": "설명적 사용 안내", "지금": "강함"}]
    assert diff["일치_목록"]["N1"] == {"새로_생김": ["ZARO → 자라 약함(철자)"],
                                   "없어짐": ["PARA PARA → 자라 약함(철자)"]}
    assert diff["재현율"] == {"P1": {"직전": [865, 870], "지금": [866, 870]}}
    assert diff["뺀_표본"]["등록부_출원인이_된_N1"]["새로_빠짐"] == ["Q7F — 삼성전자"]
    text = fm.recheck_diff_text(diff)
    assert "기대표 [없음] 삼성 + 없음: 설명적 사용 안내 → 강함" in text and "ZARO" in text


def test_logo_strong_applies_the_text_and_photo_rule():
    """확정 단계의 로고 규칙 — 강함(이미지만 판단이 위험)만, 대표 로고와 질의가 둘 다 글자 위주면
    유사도 0.98 이상, 사진으로 판정된 대표 로고는 보지 않는다(prepare 뒤에만)."""
    from types import SimpleNamespace

    import numpy as np

    def mark(appno: str) -> fc.Mark:
        return fc.Mark(appno=appno, title="x", kind="도형복합", role=fc.ROLE_LOGO_NOW,
                       auto_role=fc.ROLE_NAME, source="s", image=f"{appno}.png",
                       image_exists=True, codes=frozenset())

    def brand(name: str, *appnos: str) -> fc.Brand:
        made = _brand(name, [_notation(name)])
        return fc.Brand(**{**made.__dict__, "marks": tuple(mark(a) for a in appnos)})

    registry = fc.Registry(fc.REGISTRY_VERSION, (brand("가", "1", "2"), brand("나", "3")))
    ms = SimpleNamespace(
        state=SimpleNamespace(
            model=None, by_appno={str(i + 1): SimpleNamespace(pos=i) for i in range(3)},
            embeddings=np.array([[0.95, 0.0], [0.985, 0.0], [0.91, 0.0]], dtype=np.float32)),
        _image_only_features=lambda value, kind: value,
        _judge=lambda value, model, kind: SimpleNamespace(result=SimpleNamespace(
            grade=fc.GRADE_RISK if value >= 0.9 else fc.GRADE_REVIEW)),
        is_photo_query=lambda embedding: False)
    logo = fm.Logo({"ms": ms, "engine": None, "direct": None}, registry)
    query = np.array([1.0, 0.0], dtype=np.float32)
    assert logo.is_risk(0.9) and not logo.is_risk(0.8999)
    assert {name: hit["표장"] for name, hit in logo.strong(query).items()} == {"가": "2", "나": "3"}
    text, figure = fc.LOGO_KIND_TEXT, "도형 위주"
    logo.kinds, logo.photos = [figure, text, text], [False, False, False]
    # 글자 위주끼리는 0.98 이상만 — "나"의 글자 로고(0.91)는 빠지고, "가"는 0.985 로 남는다
    by_text = logo.strong(query, query_kind=text)
    assert {name: hit["표장"] for name, hit in by_text.items()} == {"가": "2"}
    assert set(logo.strong(query, query_kind=figure)) == {"가", "나"}  # 질의가 글자가 아니면 그대로
    assert set(logo.strong(query, query_kind=text, rule=False)) == {"가", "나"}
    logo.photos = [False, True, False]  # 사진으로 판정된 대표 로고는 보지 않는다
    assert {name: hit["표장"] for name, hit in logo.strong(query, query_kind=figure).items()} == {
        "가": "1", "나": "3"}
    # 뺄 표장(그 상표 자신)과 사진 로고를 빼면 도형 위주 로고 하나만 남는다
    assert {name: hit["표장"] for name, hit in logo.strong(
        query, exclude="3", query_kind=text).items()} == {"가": "1"}

