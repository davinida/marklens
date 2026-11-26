"""famous_check_confirm.py(유명 상표 판정 규칙 확정 측정 — 통합 모델 설계 §7-14-12)의 순수 함수:
고정한 설정, 약한 일치 조건의 선택 규칙, 음성 표본 요약(브랜드 자신의 이름일 수 있음), 표본 고르기,
기준용·확인용 목표. 비공개 데이터와 엔진은 쓰지 않는다."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
from src import famous_check as fc

from scripts import famous_check_confirm as cf
from scripts import famous_check_measure as fm


def test_fixed_settings():
    limit = cf.thresholds_for("W2")
    assert limit.weak_mode == "W2" and limit.strong_sound == 0.98
    assert limit.spelling_sound is None and limit.contain_other is True
    assert limit.weak_sound == {"짧음": 0.90, "중간": 0.92, "김": 0.90}
    assert set(limit.weak_spelling.values()) == {0.75}
    assert set(limit.strong_spelling.values()) == {0.90}
    assert cf.MODES == ("W0", "W1", "W2", "W3") and cf.TIE_ORDER == ("W1", "W2", "W3", "W0")
    assert len(cf.rule_sha256()) == 64 and cf.rule_sha256() == cf.rule_sha256()
    counts = Counter(expected for expected, _, _ in cf.EXPECT)
    assert (counts[cf.E_STRONG], counts[cf.E_WEAK], counts[cf.E_NOTICE], counts[cf.E_NONE]) == (
        33, 7, 6, 23)
    assert sum(counts[wish] for wish in cf.WISHES) == 16
    presets = {preset["id"] for preset in json.loads(fc.PRESETS_PATH.read_text(encoding="utf-8"))}
    keys = [goods for _, _, goods in cf.EXPECT] + [goods for _, goods in cf.PREVIEW]
    assert set(keys) <= presets | {None, "과일", "@N1", "@대조군"}
    assert len(cf.P2_NEW) == 18 == len({name for name, _, _ in cf.P2_NEW})
    assert set(cf.PREVIEW_EXTRA) <= set(cf.PREVIEW) and set(fm.PREVIEW_NAMES) <= set(cf.PREVIEW)


def test_shipped_registry_has_the_p2_brands_and_core_industries():
    registry = fc.load_registry()
    for name, _, _ in cf.P2_NEW:
        brand = registry.brand(name)
        assert brand is not None and any(n.script == "한글" for n in brand.notations), name
    core = {brand.name: (brand.preset, brand.core_classes)
            for brand in registry.brands if brand.is_new}
    assert len(core) == 28 and all(preset or classes for preset, classes in core.values())
    assert core["삼성"] == (None, (9, 11)) and core["애플"] == ("software", (9,))
    assert core["구찌"] == ("clothing", (14, 18)) and core["맥도날드"] == ("chicken", (29, 30))
    assert core["세븐일레븐"] == ("convenience", ()) and core["당근"] == ("software", ())
    assert registry.brand("CU").preset_classes == (35,)  # 편의점은 35류뿐 — 그대로 잰다
    # 기준용 결과를 본 뒤 사람이 정한 것 — 흔한 말과 예외 낱말
    assert [(n.text, n.kind, n.common) for n in registry.brand("자라").notations] == [
        ("자라", fc.KIND_WEAK, True), ("ZARA", fc.KIND_WEAK, True)]
    insta = {n.text: (n.kind, n.common) for n in registry.brand("인스타그램").notations}
    assert insta["인스타"] == (fc.KIND_WEAK, True) and insta["인스타그램"][0] == fc.KIND_NORMAL
    assert registry.brand("네이버").exceptions == ("네이처",)
    assert registry.brand("나이키").exceptions == ("like", "nice")
    assert registry.brand("자라").exceptions == ("자리",)
    shared = {(brand.name, mark.appno): mark.shared for brand in registry.brands
              for mark in brand.marks if mark.shared}
    assert set(shared.values()) <= {("투썸플레이스",), ("뚜레쥬르",)}
    assert not any(mark.shared for brand in registry.brands for mark in brand.logo_marks)


def _table(recall: float, negatives: int, ok: bool = True) -> dict:
    return {"한도_모두": ok, "P2_보통_기준용_약함_이상": recall, "음성_약한_일치_합": negatives}


def test_select_mode_follows_the_fixed_rule():
    tables = {"W0": _table(1.0, 80, ok=False), "W1": _table(0.95, 17), "W2": _table(1.0, 39),
              "W3": _table(0.95, 26)}
    assert cf.select_mode(tables) == ("W2", True)  # 한도를 지키는 것 가운데 P2 가 가장 높은 것
    tables["W2"] = _table(0.95, 39)
    assert cf.select_mode(tables) == ("W1", True)  # 같으면 음성 표본의 약한 일치가 적은 쪽
    tables["W3"] = _table(0.95, 17)
    assert cf.select_mode(tables) == ("W1", True)  # 그래도 같으면 W1 → W2 → W3 → W0
    tables["W1"] = _table(0.95, 17, ok=False)
    assert cf.select_mode(tables) == ("W3", True)
    none = {mode: _table(1.0, count, ok=False)
            for mode, count in zip(cf.MODES, (80, 17, 17, 26))}
    assert cf.select_mode(none) == ("W1", False)  # 지키는 조건이 없으면 약한 일치가 가장 적은 것


def _row(level: str, path: str, brand: str = "자라", notation: str = "ZARA",
         score: float = 1.0, note: str = "") -> dict:
    return {"브랜드": brand, "수준": level, "경로": path, "표기": notation, "점수": score,
            "메모": note}


def test_negative_summary_sets_possible_own_names_aside():
    items = [{"이름": name, "업종_표시": "없음"}
             for name in ("pasta ZARA", "ZARI", "자라옷가게", "INSTA", "아무 이름")]
    rows = [{"W2": _row("강함", "같음")},
            {"W2": _row("약함", "소리", score=0.87, note="zari(철자 0.75)")},
            {"W2": _row("강함", "품음-설명")},
            {"W2": _row("강함", "소리", brand="인스타그램", notation="인스타")}, {}]
    own = cf.negative_summary(items, rows, "W2", own_names=True)
    assert (own["브랜드_자신의_이름일_수_있음"], own["강함"], own["약함"], own["센_질의"]) == (
        2, 1, 1, 3)
    assert own["약함_비율"] == round(1 / 3, 6) and own["경로"] == {"약함·소리": 1, "소리": 1}
    assert own["자신의_이름_목록"][0].startswith("pasta ZARA → 자라 강함(같음")
    counted = cf.negative_summary(items, rows, "W2", own_names=False)  # N1: 출원인으로 이미 뺐다
    assert (counted["강함"], counted["브랜드_자신의_이름일_수_있음"], counted["센_질의"]) == (
        3, 0, 5)
    assert counted["경로"]["같음"] == 1
    assert cf.negative_summary(items, rows, "W1", own_names=True)["약함"] == 0


def test_pick_and_query_classes():
    items = [{"반": None}, {"반": "기준용"}, {"반": "확인용"}, {"반": "기준용", "중복": True}]
    assert cf.pick(items, cf.BASE) == items[:2] and cf.pick(items, cf.HOLDOUT) == [items[2]]
    resolve = cf.classes_resolver({"cafe": [30, 35, 43]}, {"4020200000001": {"류": ["9", 35]}})
    assert resolve({"업종": None, "업종_표시": "없음"}) is None
    assert resolve({"업종": ["G0301"], "업종_표시": "자기 업종(cafe)"}) == [30, 35, 43]
    assert resolve({"업종": ["G0301"], "업종_표시": "무작위 업종(cafe)"}) == [30, 35, 43]
    mark = {"업종": ["G1"], "업종_표시": "그 상표의 지정상품", "출원번호": "4020200000001"}
    assert resolve(mark) == [9, 35]  # 그 상표가 등록된 류
    assert resolve({**mark, "출원번호": "0"}) is None  # 모르면 판정 모듈이 유사군 코드에서 얻는다
    assert resolve({"업종": ["G1"], "업종_표시": "nail(대조군 배정)", "류": [44]}) == [44]


def test_holdout_items_need_the_holdout_stage():
    registry = fc.Registry(fc.REGISTRY_VERSION, ())
    item = {"이름": "나이키이", "업종": None, "반": cf.HOLDOUT}
    with pytest.raises(ValueError):
        cf.Matcher(registry, None, 0.0252, lambda _: None).evidence(item)
    assert cf.Matcher(registry, None, 0.0252, lambda _: None, holdout=True).evidence(item) == []


def _base(*, n1_strong=0, n1_weak=1, n3_weak=0, recall=1.0, p1_other=0, different=()) -> dict:
    return {"N1": {"수준": {"강함": n1_strong, "약함": n1_weak}},
            "N3": {"수준": {"약함": n3_weak}, "질의": 200},
            "P2": {fc.KIND_NORMAL: {"전체": {"약함_이상_비율": recall, "n": 83}}},
            "P1": {"그_밖": p1_other, fm.P1_ALLOWED: 21},
            "기대표": {"바람_빼고_다른_것": list(different)}}


def test_base_goals():
    def failed(**changes) -> list[str]:
        return [name for name, row in cf.base_goals(_base(**changes)).items() if not row["통과"]]

    assert failed() == [] and failed(n3_weak=4) == []  # 2% = 200 질의 중 4건까지
    assert failed(p1_other=2) == ["P1 강함이 아닌 것은 약한·흔한 말 표기의 업종 다름뿐"]
    assert failed(n1_weak=3) == ["N1 기준용 약함 2건 이하"]
    assert failed(n1_strong=1) == ["N1 기준용 강함 0건"]
    assert failed(n3_weak=5) == ["N3 기준용 약함 2% 이하"]
    assert failed(recall=0.79) == ["보통 표기의 P2 기준용 약함 이상 80% 이상"]
    assert failed(different=["[강함] BBQ + clothing → 설명적 사용 안내"]) == [
        "기대표(바람 빼고) 모두 맞음"]


def _holdout(paths: dict, *, n1_weak=0, n3=(0, 0), recall=0.9, rate=0.003) -> dict:
    return {"N1": {"경로": paths, "약함": n1_weak}, "N3": {"강함": n3[0], "약함": n3[1]},
            "P2": {fc.KIND_NORMAL: {"전체": {"약함_이상_비율": recall, "n": 83}}},
            "N5": {"약함_비율": rate, "약함": 40}}


def test_holdout_goals():
    base = {"P2": {fc.KIND_NORMAL: {"전체": {"약함_이상_비율": 1.0}}},
            "N5": {"약함_비율": 0.002462}}
    # 같음으로 생긴 강함은 목록으로만 · P2 는 기준용 − 15%p 까지 · N5 한도 = 0.2462% × 2 + 0.1%p
    passed = cf.holdout_goals(_holdout({"같음": 3, "소리": 1, "약함·소리": 2}, n1_weak=4,
                                       n3=(0, 2), recall=0.85, rate=0.005924), base)
    assert all(row["통과"] for row in passed.values()) and len(passed) == 6
    first = passed["N1 확인용 소리·철자·품음 강함 1건 이하"]
    assert (first["값"], first["같음으로_생긴_강함(목록만)"]) == (1, 3)
    missed = cf.holdout_goals(_holdout({"소리": 1, "품음-설명": 1}, n1_weak=5, n3=(1, 3),
                                       recall=0.84, rate=0.006), base)
    assert [row["통과"] for row in missed.values()] == [False] * 6


def test_classes_from_codes_proposal():
    """서비스 연결용 안(보고만) — 코드 집합이 업종 세트와 같으면 그 세트의 류, 아니면 코드별
    대표 류."""
    from types import SimpleNamespace

    goods = SimpleNamespace(entries=[
        SimpleNamespace(nice_class=25, similarity_codes=("G4503",)),
        SimpleNamespace(nice_class=25, similarity_codes=("G430301",)),
        SimpleNamespace(nice_class=9, similarity_codes=("G430301",)),
        SimpleNamespace(nice_class=9, similarity_codes=("G430301",)),
        SimpleNamespace(nice_class=35, similarity_codes=("S2045",)),
        SimpleNamespace(nice_class=42, similarity_codes=("G390802",)),
        SimpleNamespace(nice_class=9, similarity_codes=("G390802",))])
    representative = cf.representative_classes(goods)
    # 그 코드가 붙은 상품이 가장 많은 류, 같으면 작은 류
    assert representative == {"G4503": 25, "G430301": 9, "S2045": 35, "G390802": 9}
    codes_of = {"clothing": ["G430301", "G4503", "S2045"], "software": ["G390802"]}
    classes_of = {"clothing": [25, 35], "software": [42]}

    def classes(codes):
        return cf.classes_from_codes(codes, codes_of, classes_of, representative)

    assert classes(["S2045", "G4503", "g430301 "]) == ([25, 35], "업종 세트(clothing)")
    assert classes(["G390802"]) == ([42], "업종 세트(software)")  # 대표 류(9)가 아니라 세트의 류
    assert classes(["G4503", "S2045"]) == ([25, 35], "코드별 대표 류")
    assert classes(["G430301", "X9999"]) == ([9], "코드별 대표 류") and classes([]) == (
        [], "코드별 대표 류")


def _sha256(path: Path) -> str:
    """줄 끝을 LF 로 맞춘 내용의 sha256(체크아웃이 CRLF 로 바꿔도 같게)."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_confirmed_file_matches_the_shipped_rule_and_registry():
    """확정 파일의 해시와 기준이 지금의 판정 모듈·등록부·overrides 와 같다. 다르면 확정한 규칙이
    아니다 — 판정 모듈이나 등록부를 고쳤으면 famous_check_confirm.py 로 다시 확인하고 확정 파일을
    갱신한다(확인용 표본은 이미 본 표본이 된다)."""
    if not cf.CONFIRMED_FILE.exists():
        pytest.skip("확정 파일이 없다(규칙을 아직 확정하지 않음)")
    confirmed = json.loads(cf.CONFIRMED_FILE.read_text(encoding="utf-8"))
    assert confirmed["version"] == cf.CONFIRMED_VERSION
    rule, registry = confirmed["규칙"], confirmed["등록부"]
    assert rule["약한_일치_조건"] in cf.MODES
    assert rule["기준"] == cf.thresholds_for(rule["약한_일치_조건"]).to_dict()
    assert rule["로고_글자끼리_유사도"] == fc.LOGO_TEXT_SIMILARITY
    assert rule["판정_모듈_sha256"] == _sha256(cf.ML_ROOT / "src" / "famous_check.py")
    assert registry["sha256"] == _sha256(fc.DEFAULT_REGISTRY_PATH)
    assert registry["overrides_sha256"] == _sha256(fc.DEFAULT_OVERRIDES_PATH)
    assert registry["version"] == fc.REGISTRY_VERSION
    assert registry["브랜드"] == len(fc.load_registry().brands)
    for part in ("기준용_목표", "확인용_목표"):
        assert all(row["통과"] for row in confirmed["측정"][part].values()), part

