"""famous_check_measure.py(유명 상표 확인 1단계 측정 — 통합 모델 설계 §7-14)의 순수 함수: 표본
만들기, 확인용 보호, 기준 선택 규칙."""

from __future__ import annotations

import pytest
from src import famous_check as fc

from scripts import famous_check_measure as fm


def _notation(text: str, *, weak: bool = False) -> fc.Notation:
    key = fc.text_key(text)
    return fc.Notation(text=text, key=key, pieces=tuple(fc.split_pieces(fc.normalize_text(text))),
                       script=fc.script_label(key), length=fc.length_class(key), weak=weak)


def _brand(name: str, notations, *, preset="cafe", codes=("G0301",)) -> fc.Brand:
    return fc.Brand(name=name, notations=tuple(notations), applicants=(name,),
                    applicant_keys=frozenset({name}), preset=preset, preset_label=None,
                    preset_codes=frozenset(codes), evidence="", evidence_urls=(),
                    protection=fc.PROTECT_ANY, goods_codes=frozenset(codes),
                    goods_source="업종 세트", marks=())


def test_settings_hash_and_fixed_lists():
    assert fm.rule_sha256() == fm.rule_sha256()
    assert {"목적", "정리", "식별력_없는_말", "경로", "길이_구간", "약한_표기", "설명적_사용",
            "업종_겹침", "수준과_바닥", "이미지_속_글자", "표본", "기준_선택", "보고", "로고",
            "미리_보기", "다른_업종_규모", "스모크"} == set(fm.RULE)
    assert len(fm.P2_PAIRS) == 28 and len(fm.N4_TRAPS) == 38
    assert (fm.STRONG_SPELLING_GRID, fm.WEAK_SOUND_GRID, fm.WEAK_SPELLING_GRID) == (
        (0.90, 0.95), (0.90, 0.92, 0.94, 0.96), (0.75, 0.80, 0.85, 0.90))
    assert (fm.N1_RATE_MAX, fm.N3_RATE_MAX, fc.STRONG_SOUND) == (0.005, 0.02, 0.98)
    names = [name for name, _ in fm.PREVIEW_NAMES]
    assert names.count("스타벅스") == 3 and {"@F1", "@F2", "@F3", "@S1"} <= set(names)
    assert fm.PREVIEW_HOLDOUT_SEEN == ("헤르메스",)  # P2 확인용 중 미리 보기에 든 것


def test_frozen_rule_matches_the_script_when_present():
    path = fm._paths(fm.TRIALS)["rule"]  # noqa: SLF001
    if not path.exists():
        pytest.skip("고정본 없음(비공개 데이터)")
    import json

    frozen = json.loads(path.read_text(encoding="utf-8"))
    assert frozen["설정_sha256"] == fm.rule_sha256()  # 고정한 뒤 규칙을 바꾸지 않았다


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


def test_target_notation_uses_no_similarity():
    brand = _brand("교촌치킨", [_notation("교촌치킨"), _notation("교촌"), _notation("KYOCHON")])
    assert fm.target_notation("교춘", brand).text == "교촌"
    assert fm.target_notation("교촌치퀸", brand).text == "교촌치킨"
    assert fm.target_notation("KYOCHONE", brand).text == "KYOCHON"
    weak = _brand("GS25", [_notation("GS25", weak=True), _notation("지에스25")])
    assert fm.target_notation("GS24", weak).text == "지에스25"  # 약한 표기는 겨냥한 표기가 아니다
    assert fm.target_notation("쥐에스25", weak).text == "지에스25"


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
    assert "N2" not in overlap and "N1" not in overlap


class _FakeMatcher:
    """근거를 손으로 준 Matcher — 질의마다 (길이, 소리, 철자) 한 표기."""

    def __init__(self):
        self.calls = 0

    def decide(self, item: dict, thresholds: fc.Thresholds) -> fc.FamousResult:
        self.calls += 1
        evidence = [fc.BrandEvidence(brand="가", protection=fc.PROTECT_ANY, overlap=None,
                                     overlap_value=None, items=(fc.Evidence(
                                         notation="가", key="가", length=item["길이"],
                                         weak_notation=False, exact=item.get("같음", False),
                                         sound=item["소리"], spelling=item["철자"]),))]
        return fc.decide(evidence, thresholds)


def _queries(count: int, length: str, sound: float, spelling: float, **more) -> list[dict]:
    return [{"이름": f"{length}{sound}{spelling}{index}", "길이": length, "소리": sound,
             "철자": spelling, **more} for index in range(count)]


def test_threshold_selection_follows_the_fixed_rule():
    # N1 1,000 질의(한도 0.5% = 5건), N3 100 질의(한도 2% = 2건)
    n1 = (_queries(6, "김", 0.91, 0.0)        # 김·약한 소리 0.90 이면 6건 → 한도 초과, 0.92 부터 0
          + _queries(5, "중간", 0.95, 0.0)    # 중간·약한 소리 0.90 에서 5건 = 한도 → 0.90
          + _queries(4, "김", 0.0, 0.82)      # 김·약한 철자 0.80 이하면 4건
          + _queries(3, "김", 0.93, 0.0)      # 김·약한 소리 0.92 에서 3건 — 철자와 합쳐 누적
          + _queries(2, "짧음", 0.0, 0.92, 같음=True)  # 이미 같음으로 잡힌 것 — 새 일치가 아님
          + _queries(980, "김", 0.5, 0.5))
    n3 = (_queries(3, "짧음", 0.97, 0.0)      # 짧음·약한 소리는 N3 3건(3%) → 어떤 값도 안 됨
          + _queries(97, "김", 0.1, 0.1))
    table = fm.select_thresholds(_FakeMatcher(), n1, n3)
    chosen = table["고른_기준"]
    assert chosen["strong_sound"] == 0.98 and chosen["strong_spelling"] == 0.9
    assert chosen["weak_sound"] == {"짧음": None, "중간": 0.9, "김": 0.92}
    # 김: 약한 소리 0.92 가 3건을 더한 상태 — 철자 0.80 이하는 4건을 더해 누적 7 > 5, 0.85 부터 통과
    assert chosen["weak_spelling"] == {"짧음": 0.75, "중간": 0.75, "김": 0.85}
    rows = {row["값"]: row for row in table["약한_철자"]["격자"]["김"]}
    assert rows[0.8]["N1_새_일치(누적)"] == 7 and rows[0.8]["N1_철자만_더함(증분)"] == 4
    assert rows[0.8]["조건"] is False and rows[0.8]["증분으로_보면_조건"] is True
    assert rows[0.85]["N1_새_일치(누적)"] == 3 and rows[0.85]["조건"] is True
    short = {row["값"]: row for row in table["약한_소리"]["격자"]["짧음"]}
    assert all(row["N3_새_일치"] == 3 and row["조건"] is False for row in short.values())
    assert table["고른_기준에서_새로_더한_일치(전체)"] == {
        "N1": 8, "N1_비율": 0.008, "N3": 0, "N3_비율": 0.0}


def test_strong_spelling_is_dropped_when_it_adds_matches():
    n1 = _queries(1, "김", 0.0, 0.96) + _queries(199, "김", 0.1, 0.1)
    table = fm.select_thresholds(_FakeMatcher(), n1, _queries(50, "김", 0.1, 0.1))
    assert table["강한_철자"]["고른_값"] is None  # 0.90·0.95 둘 다 새 강한 일치 1건
    assert [row["새로_생기는_일치"] for row in table["강한_철자"]["격자"]] == [1, 1]
    assert table["고른_기준"]["strong_spelling"] is None
    one = _queries(1, "김", 0.0, 0.93) + _queries(199, "김", 0.1, 0.1)
    assert fm.select_thresholds(_FakeMatcher(), one, [])["강한_철자"]["고른_값"] == 0.95


def test_recall_and_match_lists():
    matcher = _FakeMatcher()
    thresholds = fc.Thresholds(weak_sound={"짧음": None, "중간": None, "김": 0.9})
    items = [{"이름": "가", "브랜드": "가", "표기": "가", "변형": "ㄱ", "업종_표시": "없음",
              "길이": "김", "소리": 0.99, "철자": 0.0},
             {"이름": "나", "브랜드": "가", "표기": "가", "변형": "ㄱ", "업종_표시": "없음",
              "길이": "김", "소리": 0.93, "철자": 0.0},
             {"이름": "다", "브랜드": "가", "표기": "가", "변형": "ㄴ", "업종_표시": "자기",
              "길이": "중간", "소리": 0.93, "철자": 0.0}]
    table = fm.recall_table(matcher, items, thresholds)
    assert table["전체"] == {"n": 3, "강함": 1, "약함": 1, "안내": 0, "놓침": 1,
                           "약함_이상_비율": 0.6667}
    assert table["길이별"]["중간"]["놓침"] == 1 and table["변형별"]["ㄱ"]["강함"] == 1
    assert [row["이름"] for row in table["놓친_것"]] == ["다"]
    listed = fm.match_list(matcher, items, thresholds)
    assert listed["질의"] == 3 and listed["일치한_질의"] == 2
    assert listed["수준"] == {"강함": 1, "약함": 1} and listed["경로"] == {"소리": 2}
    assert fm.grade_max("주의", None, "검토 권장") == "검토 권장" and fm.grade_max(None) is None
    assert fm.grade_max("위험", "검토 권장") == "위험"
