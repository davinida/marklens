"""유명 상표 확인(src.famous_check, 통합 모델 설계 §7-14) — 등록부와 일치 판정의 단위 시험.
장난감 등록부·식별력 모델·업종 낱말 사전으로 2-1단계 규칙을 보고, 저장소의 등록부
(shared/famous_registry.json)가 표·수집 계획·DB 와 어긋나지 않는지는 데이터가 있을 때만 본다."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from src import famous_check as fc
from src.axes import distinctiveness as dx
from src.axes.goods_map import GoodsEntry, GoodsMap
from src.axes.x1_phonetic import phonetic_similarity

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN = REPO_ROOT / "ml" / "data" / "staging" / "famous_brands.plan.json"
METADATA = REPO_ROOT / "ml" / "data" / "kipris_metadata.json"
GOODS = GoodsMap([
    GoodsEntry("커피", 30, ("G0301",)),
    GoodsEntry("치킨", 29, ("G0703",)),
    GoodsEntry("의류", 25, ("G4502",)),
    GoodsEntry("세탁업", 37, ("S1282",)),
    GoodsEntry("편의점업", 35, ("S2090",)),
])
CAFE, CHICKEN, CLOTHES, LAUNDRY, STORE = (
    {"G0301"}, {"G0703"}, {"G4502"}, {"S1282"}, {"S2090"})
FLOOR = 0.0252
WORDS = frozenset({"카페", "커피", "치킨", "치킨집", "편의점", "옷가게", "전문점"})
TABLE = [
    {"notations": ["스타벅스", "STARBUCKS"], "applicants": ["스타벅스 코포레이션"],
     "preset": "cafe", "evidence": "근거 https://example.org/a",
     "urls": ["https://example.org/a"]},
    {"notations": ["BBQ", "비비큐"], "applicants": ["주식회사 제너시스비비큐"],
     "preset": "chicken", "evidence": "근거", "urls": []},
    {"notations": ["샤넬", "CHANEL"], "applicants": ["샤넬"], "preset": "clothing",
     "evidence": "근거", "urls": []},
    {"notations": ["네이버", "NAVER"], "applicants": ["네이버 주식회사"], "preset": "cafe",
     "evidence": "근거", "urls": []},
    {"notations": ["bhc", "비에이치씨"], "applicants": ["다이닝브랜즈그룹"], "preset": "chicken",
     "evidence": "근거", "urls": []},
    {"notations": ["CU", "씨유"], "applicants": ["비지에프리테일"], "preset": "store",
     "evidence": "근거", "urls": []},
    {"notations": ["김가네", "GIMGANE"], "applicants": ["주식회사 김가네"], "preset": "chicken",
     "evidence": "근거", "urls": []},
    {"notations": ["PAIK'S"], "applicants": ["더본코리아"], "preset": "cafe",
     "evidence": "근거", "urls": []},
]
DB = [
    {"출원번호": "1", "상표한글명": "STARBUCKS COFFEE", "상표구분": "도형복합", "유사군": ["G0301"],
     "류": [30], "이미지파일": "1.png", "출원인": "스타벅스 코포레이션",
     "수집_출처": "유명 브랜드"},
    {"출원번호": "2", "상표한글명": None, "상표구분": "도형상표", "유사군": ["G4502"], "류": [25],
     "이미지파일": "2.png", "출원인": "스타벅스 코포레이션", "수집_출처": "유명 브랜드"},
    {"출원번호": "3", "상표한글명": "로제치킨 bbq", "상표구분": "도형복합", "유사군": ["G0703"],
     "류": [29], "이미지파일": "3.png", "출원인": "주식회사 제너시스비비큐",
     "수집_출처": "유명 브랜드"},
    {"출원번호": "4", "상표한글명": "치킨대학", "상표구분": "도형복합", "유사군": ["S1282"],
     "류": [37], "이미지파일": "4.png", "출원인": "(주)제너시스비비큐", "수집_출처": "기존 수집"},
    {"출원번호": "5", "상표한글명": "샤넬 CHANEL", "상표구분": "도형복합", "유사군": ["G4502"],
     "류": [25], "이미지파일": "5.png", "출원인": "샤넬", "수집_출처": "유명 브랜드"},
    {"출원번호": "9", "상표한글명": "무관한 상표", "상표구분": "도형복합", "유사군": ["G0301"],
     "류": [30], "이미지파일": "9.png", "출원인": "다른 회사", "수집_출처": "기존 수집"},
]
PLAN_RECORDS = [{"출원번호": "1", "브랜드": "스타벅스"}, {"출원번호": "2", "브랜드": "스타벅스"},
                {"출원번호": "3", "브랜드": "BBQ"}, {"출원번호": "5", "브랜드": "샤넬"}]
PRESETS = {"cafe": ["G0301"], "chicken": ["G0703"], "clothing": ["G4502"], "store": ["S2090"]}
PRESET_CLASSES = {"cafe": [30], "chicken": [29], "clothing": [25], "store": [35]}


def _keys(text: str) -> frozenset[str]:
    value = str(text or "").replace("주식회사", "").replace("(주)", "").replace(" ", "")
    return frozenset({value}) if value else frozenset()


@pytest.fixture(scope="module")
def dist() -> dx.Distinctiveness:
    names, classes = dx.goods_index(GOODS)
    descriptive = dx.validate_descriptive_terms({"terms": {
        "bbq": {"kind": "용도", "absolute": False, "classes": [29, 25]},
        "맛있는": {"kind": "품질", "absolute": True},
        "뉴": {"kind": "시기", "absolute": True}}})
    return dx.Distinctiveness({}, famous={"스타벅스", "샤넬", "네이버"}, goods_names=names,
                              code_classes=classes, descriptive=descriptive)


@pytest.fixture(scope="module")
def registry(dist) -> fc.Registry:
    return fc.build_registry(
        TABLE, plan_records=PLAN_RECORDS, db_records=DB, preset_codes=PRESETS,
        preset_labels={"cafe": "카페"}, dist=dist, applicant_keys=_keys,
        image_exists=lambda name: name != "2.png", preset_classes=PRESET_CLASSES)


def _check(name, goods, registry, dist, **kwargs):
    thresholds = kwargs.pop("thresholds", fc.Thresholds())
    return fc.check_famous(name, goods, registry, thresholds, dist=dist, goods_floor=FLOOR,
                           words=WORDS, **kwargs)


def _level(name, goods, registry, dist, **kwargs):
    strongest = _check(name, goods, registry, dist, **kwargs).strongest
    return None if strongest is None else (strongest.level, strongest.path)


def test_text_helpers():
    assert fc.text_key("L'OREAL") == "loreal" and fc.text_key("본죽&비빔밥") == "본죽비빔밥"
    assert fc.text_key(" Star​Bucks® ") == "starbucks"
    assert fc.split_words("PAIK'S 카페") == ("paik", "s", "카페")
    assert fc.split_words("GS25편의점 漢字") == ("gs25편의점",)  # 문자 종류로는 나누지 않는다
    assert fc.script_label("gs25") == "영문+숫자" and fc.script_label("지에스25") == "한글+숫자"
    assert [fc.length_class(k) for k in ("샤넬", "bhc", "네이버", "paiks", "스타벅스", "loreal",
                                         "지에스25", "gs25")] == [
        "짧음", "짧음", "중간", "중간", "김", "김", "김", "중간"]


def test_whole_comparison_uses_no_pieces_and_matches_digits():
    assert fc.whole_sound("gs25", "지에스25") == 1.0 and fc.whole_sound("bbq", "비비큐") == 1.0
    assert fc.whole_sound("io", "지에스25") == 0.0  # 조각("25" = 이오)만으로는 견주지 않는다
    assert phonetic_similarity("io", "지에스25") == 1.0  # X1 은 조각끼리의 최댓값
    assert fc.whole_sound("gs24", "gs25") == 0.0 == fc.whole_spelling("gs24", "gs25")
    assert fc.whole_spelling("gs25", "gs25") == 1.0
    assert fc.whole_sound("스타벅", "스타벅스") < 0.98  # 붙여쓴 결합어 포함 점수(0.975)를 안 씀
    assert phonetic_similarity("스타벅", "스타벅스") == 0.975
    assert fc.whole_sound("paris", "parisbaguette") < 0.8
    assert fc.whole_sound("스타벅수", "스타벅스") == fc.whole_sound("스타벅스", "스타벅수") > 0.9
    assert fc.whole_spelling("스타벅수", "스타벅스") == pytest.approx(8 / 9)
    assert fc.whole_readings("gs25")[0] == "지에스이십오" and fc.whole_readings("漢") == ()


def test_industry_words_come_from_presets_and_shop_words():
    words = fc.industry_words()
    assert {"카페", "커피", "전문점", "치킨집", "편의점", "식당", "한식", "옷가게", "하우스",
            "직영점", "빵집", "유튜브"} <= words
    assert "스타벅스" not in words and "" not in words
    assert all(fc.text_key(word) == word for word in words)


def test_classify_notations(dist):
    def kinds(texts, codes):
        items = fc.classify_notations([fc.analyze_notation(t, dist, frozenset(codes))
                                       for t in texts])
        return {item["text"]: (item["kind"], item["inherits"]) for item in items}

    assert kinds(["BBQ", "비비큐"], CHICKEN) == {
        "BBQ": (fc.KIND_WEAK, ["BBQ"]), "비비큐": (fc.KIND_WEAK, ["BBQ"])}
    assert kinds(["bhc", "비에이치씨"], CHICKEN) == {
        "bhc": (fc.KIND_INITIAL, ["bhc"]), "비에이치씨": (fc.KIND_INITIAL, ["bhc"])}
    assert kinds(["김가네", "GIMGANE"], CHICKEN) == {  # 영문 읽기가 달라 따라가지 않는다
        "김가네": (fc.KIND_WEAK, ["김가네"]), "GIMGANE": (fc.KIND_NORMAL, [])}
    assert kinds(["CU", "씨유"], STORE)["씨유"] == (fc.KIND_WEAK, ["CU"])
    assert kinds(["스타벅스", "STARBUCKS"], CAFE)["STARBUCKS"] == (fc.KIND_NORMAL, [])
    # 자기 업종이 세탁이면 bbq 는 식별력이 있다 — 약한 표기가 아니라 영문 3자 머리글자 표기
    assert kinds(["BBQ", "비비큐"], LAUNDRY) == {
        "BBQ": (fc.KIND_INITIAL, ["BBQ"]), "비비큐": (fc.KIND_INITIAL, ["BBQ"])}


def _build(dist, overrides=None, table=None, db=None, plan=None):
    return fc.build_registry(
        TABLE if table is None else table,
        plan_records=PLAN_RECORDS if plan is None else plan, db_records=DB if db is None else db,
        preset_codes=PRESETS, preset_labels={"cafe": "카페"}, dist=dist, applicant_keys=_keys,
        overrides=fc.parse_overrides({"version": fc.OVERRIDES_VERSION,
                                      "brands": overrides or {}}),
        preset_classes=PRESET_CLASSES)


def test_registry_default_roles_goods_and_kinds(registry):
    star, bbq = registry.brand("스타벅스"), registry.brand("BBQ")
    # 고르기 전 기본 역할: 자동 "이름" → 브랜드 이름이 든 그 밖의 표장, 나머지 → 관련 없음
    assert [(m.appno, m.auto_role, m.role, m.picked, m.image_exists) for m in star.marks] == [
        ("1", "이름", fc.ROLE_BRAND_OTHER, False, True),
        ("2", "도형", fc.ROLE_UNRELATED, False, False)]
    assert [(m.appno, m.auto_role, m.role, m.source) for m in bbq.marks] == [
        ("3", "이름", fc.ROLE_BRAND_OTHER, fc.SOURCE_FAMOUS),
        ("4", "다른 이름", fc.ROLE_UNRELATED, fc.SOURCE_EXISTING)]
    assert all(b.logo_marks == () for b in registry.brands)  # 고르지 않으면 대표 로고는 0건
    assert bbq.goods_codes == {"G0703"} and bbq.goods_source == "브랜드 표장"
    assert {n.text: (n.kind, n.base_weak) for n in bbq.notations} == {
        "BBQ": (fc.KIND_WEAK, True), "비비큐": (fc.KIND_WEAK, False)}
    assert all(n.kind == fc.KIND_NORMAL for n in star.notations)  # 유명 예외를 빼도 조어
    # 이름 일치용 업종 = 업종 세트 + "관련 없음"이 아닌 표장(고르기 전에는 자동 "이름" 표장만)
    assert star.name_goods_sets == (frozenset({"G0301"}), frozenset({"G0301"}))
    # 1단계 표본 재현용 업종(자동 역할 이름·도형 + 업종 세트)과 식별력 맥락은 자동 역할 그대로
    assert star.goods_sets == (frozenset({"G0301"}), frozenset({"G4502"}), frozenset({"G0301"}))
    assert star.goods_codes == {"G0301", "G4502"}
    assert bbq.name_goods_codes == {"G0703"}
    naver = registry.brand("네이버")
    assert naver.marks == () and naver.goods_source == "업종 세트"
    assert naver.name_goods_sets == (frozenset({"G0301"}),)
    assert registry.applicant_keys >= {"스타벅스코포레이션", "제너시스비비큐", "샤넬"}
    assert star.evidence_urls == ("https://example.org/a",) and star.evidence_label is None
    # 보호 범위 기본값: 정해 둔 브랜드만 업종 불문, 나머지는 같은·가까운 업종 중심
    assert {b.name: b.protection for b in registry.brands} == {
        "스타벅스": fc.PROTECT_ANY, "샤넬": fc.PROTECT_ANY, "네이버": fc.PROTECT_ANY,
        "BBQ": fc.PROTECT_NEAR, "bhc": fc.PROTECT_NEAR, "CU": fc.PROTECT_NEAR,
        "김가네": fc.PROTECT_NEAR, "PAIK'S": fc.PROTECT_NEAR}


def test_registry_json_round_trip(registry, dist, tmp_path):
    changed = _build(dist, {
        "샤넬": {"protection": fc.PROTECT_NEAR, "exceptions": ["채널", "CHANNEL"],
                 "notations": {"add": ["샤넬르"], "common": ["샤넬르"]},
                 "fetch": [{"appno": "40-2020-0000001", "role": fc.ROLE_LOGO_NOW}], "memo": "확인"},
        "토스": {"new": True, "notations": {"add": ["토스", "toss"]}}})
    for source in (registry, changed):
        data = fc.registry_to_json(source)
        path = tmp_path / "registry.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        assert fc.load_registry(path) == source
    stale = tmp_path / "v2.json"
    stale.write_text(json.dumps({**fc.registry_to_json(registry),
                                 "version": "famous_registry_v2"}), encoding="utf-8")
    with pytest.raises(ValueError):
        fc.load_registry(stale)


def test_picked_roles_change_logos_and_brand_industry(dist):
    changed = _build(dist, {
        "스타벅스": {"marks": {"2": fc.ROLE_LOGO_NOW, "1": fc.ROLE_LOGO_OLD}},
        "BBQ": {"marks": {"3": fc.ROLE_UNRELATED, "4": fc.ROLE_BRAND_OTHER}}})
    star, bbq = changed.brand("스타벅스"), changed.brand("BBQ")
    assert [(m.appno, m.role, m.picked) for m in star.marks] == [
        ("1", fc.ROLE_LOGO_OLD, True), ("2", fc.ROLE_LOGO_NOW, True)]
    assert [m.appno for m in star.logo_marks] == ["1", "2"]  # 대표 로고(현재)·과거 로고만
    # 사람이 고른 표장은 "관련 없음"이 아니면 이름 일치용 업종에 든다(도형 표장이어도)
    assert star.name_goods_sets == (frozenset({"G0301"}), frozenset({"G0301"}),
                                    frozenset({"G4502"}))
    assert [m.appno for m in bbq.own_marks] == ["4"]
    assert bbq.name_goods_sets == (frozenset({"G0703"}), frozenset({"S1282"}))
    assert bbq.goods_codes == {"S1282"}  # 식별력 맥락도 사람이 고른 것을 따른다
    assert star.goods_sets == (frozenset({"G0301"}), frozenset({"G4502"}), frozenset({"G0301"}))
    evidence = fc.collect_evidence(fc.prepare_query("스타벅스", CLOTHES), changed, dist, FLOOR,
                                   words=WORDS)
    assert next(e for e in evidence if e.brand == "스타벅스").overlap is True
    with pytest.raises(ValueError):  # 그 브랜드의 표장이 아닌 출원번호
        _build(dist, {"샤넬": {"marks": {"1": fc.ROLE_LOGO_NOW}}})


def test_notation_edits_common_words_and_new_brands(dist):
    changed = _build(dist, {
        "스타벅스": {"notations": {"remove": ["STARBUCKS"], "add": ["스벅", "별다방"],
                               "common": ["별다방"]}},
        "토스": {"new": True, "notations": {"add": ["토스", "toss"], "common": ["토스"]},
                 "applicants": ["다른 회사"], "preset": "cafe"},
        "애플": {"new": True, "name": "애플(Apple)", "notations": {"add": ["애플"]},
                 "evidence_urls": ["https://example.org/apple"],
                 "protection": fc.PROTECT_ANY}})
    star = changed.brand("스타벅스")
    assert [(n.text, n.added, n.common, n.kind) for n in star.notations] == [
        ("스타벅스", False, False, fc.KIND_NORMAL), ("스벅", True, False, fc.KIND_NORMAL),
        ("별다방", True, True, fc.KIND_WEAK)]
    assert star.removed_notations == ("STARBUCKS",)
    assert star.notations[2].kind_reason == fc.COMMON_REASON
    # 지운 표기는 표기 목록에 없다 — 남은 표기와 소리가 같으면 그 경로로는 여전히 일치한다
    assert _level("STARBUCKS", CAFE, changed, dist) == ("강함", "소리")
    assert _level("스벅", CAFE, changed, dist) == ("강함", "같음")
    # 흔한 말로 표시한 표기는 약한 표기처럼 이름이 그 표기뿐일 때만 일치
    assert _level("별다방", CAFE, changed, dist) == ("강함", "같음")
    assert _level("별다방 카페", CAFE, changed, dist) == ("강함", "같음")
    assert _level("우리동네 별다방", CAFE, changed, dist) == ("설명적 사용 안내", "같음")
    assert _check("별다방이", CAFE, changed, dist).strongest is None
    toss, apple = changed.brand("토스"), changed.brand("애플")
    assert [brand.name for brand in changed.brands][-2:] == ["토스", "애플(Apple)"]
    assert (toss.is_new, toss.preset, toss.protection, toss.evidence_label) == (
        True, "cafe", fc.PROTECT_NEAR, fc.EVIDENCE_NONE)  # 근거 URL 이 없으면 "근거 없음"
    # 소리가 같은 표기도 흔한 말을 따른다(toss = 토스)
    assert [(n.text, n.kind, n.inherits) for n in toss.notations] == [
        ("토스", fc.KIND_WEAK, ("토스",)), ("toss", fc.KIND_WEAK, ("토스",))]
    assert [m.appno for m in toss.marks] == ["9"]  # 같은 출원인의 DB 표장
    assert (apple.table_name, apple.preset, apple.evidence_label, apple.protection) == (
        "애플", None, None, fc.PROTECT_ANY)
    assert changed.brand("애플") is apple and changed.brand("애플(Apple)") is apple
    assert apple.goods_codes == frozenset() and apple.name_goods_sets == ()
    assert _level("애플", CAFE, changed, dist) == ("강함", "같음")
    for bad in (
        {"스타벅스": {"notations": {"remove": ["없는 표기"]}}},
        {"스타벅스": {"notations": {"remove": ["스타벅스", "STARBUCKS"]}}},
        {"스타벅스": {"notations": {"common": ["없는 표기"]}}},
        {"스타벅스": {"notations": {"add": ["STAR BUCKS"]}}},  # 붙여 쓴 꼴이 같은 표기
        {"없는 브랜드": {"protection": fc.PROTECT_ANY}},
        {"샤넬": {"new": True, "notations": {"add": ["샤넬"]}}},
        {"스타벅스": {"preset": "없는 세트"}},
        {"새것": {"new": True, "name": "샤넬", "notations": {"add": ["새것"]}}},
    ):
        with pytest.raises(ValueError):
            _build(dist, bad)


def test_exception_words_block_only_weak_matches(dist):
    weak = fc.Thresholds(weak_spelling={"김": 0.75, "짧음": 0.75}, weak_sound={"짧음": 0.90})
    plain = _build(dist)
    excepted = _build(dist, {"샤넬": {"exceptions": ["채널", "CHANNEL"]},
                             "스타벅스": {"exceptions": ["스타벅스리"]}})

    def level(name, source, goods=None):
        return _level(name, goods, source, dist, thresholds=weak)

    assert level("CHANNEL", plain) == ("약함", "철자")
    assert level("CHANNEL", excepted) is None  # 질의 낱말이 예외 낱말과 같으면 약한 일치가 아니다
    assert level("channel 카페", excepted, CAFE) is None
    assert level("CHANNEL카페", excepted, CAFE) is None  # 설명 낱말을 뗀 구간도 같은 낱말
    assert level("CHANNELS", excepted) == ("약함", "철자")  # 다른 낱말은 그대로
    assert level("스타벅스리", plain) == ("약함", "철자")
    assert level("스타벅스리", excepted) is None
    # 품음-기타도 약한 일치라 같은 낱말이면 빠진다
    assert _level("스타벅스리", None, plain, dist) == ("약함", "품음-기타")
    assert _level("스타벅스리", None, excepted, dist) is None
    # 강한 일치에는 영향이 없다
    assert level("샤넬", excepted) == ("강함", "같음")
    assert level("CHANNEL 샤넬", excepted) == ("강함", "같음")
    strong = _build(dist, {"샤넬": {"exceptions": ["샤넬카페"]}})
    assert level("샤넬카페", strong, CAFE) == ("강함", "품음-설명")
    assert excepted.brand("샤넬").exception_keys == {"채널", "channel"}


def test_fetch_list_attaches_marks_once_they_are_in_the_database(dist):
    changed = _build(dist, {"샤넬": {"fetch": [
        {"appno": "4020200000009", "role": fc.ROLE_LOGO_NOW, "source": "후보",
         "title": "CC", "applicant": "샤넬"},
        {"appno": "40-2019-0000001", "role": fc.ROLE_LOGO_OLD}]}})
    chanel = changed.brand("샤넬")
    assert [(e["appno"], e["role"], e["source"]) for e in chanel.fetch] == [
        ("4020200000009", fc.ROLE_LOGO_NOW, "후보"), ("4020190000001", fc.ROLE_LOGO_OLD, "직접")]
    assert [m.appno for m in chanel.marks] == ["5"]  # 아직 DB 에 없는 것은 표장이 아니다
    db = DB + [{"출원번호": "4020200000009", "상표한글명": None, "상표구분": "도형상표",
                "유사군": ["S1282"], "류": [37], "이미지파일": "c.png", "출원인": "지주회사"}]
    later = _build(dist, {"샤넬": {"fetch": [
        {"appno": "4020200000009", "role": fc.ROLE_LOGO_NOW, "source": "후보"}]}}, db=db)
    chanel = later.brand("샤넬")
    assert chanel.fetch == ()  # 받은 뒤에는 받을 목록에서 빠지고 고른 역할의 표장이 된다
    assert [(m.appno, m.role, m.source, m.picked) for m in chanel.marks] == [
        ("5", fc.ROLE_BRAND_OTHER, fc.SOURCE_FAMOUS, False),
        ("4020200000009", fc.ROLE_LOGO_NOW, fc.SOURCE_PICKED, True)]
    assert [m.appno for m in chanel.logo_marks] == ["4020200000009"]


def test_received_marks_add_their_applicants_to_the_brand(dist):
    received = [
        {"출원번호": "4020200000009", "상표한글명": None, "상표구분": "도형상표",
         "유사군": ["S1282"], "류": [37], "이미지파일": "c.png",
         "출원인": "샤넬 홀딩|CHANEL HOLDING", "수집_출처": fc.DB_SOURCE_LOGOS},
        {"출원번호": "4020200000010", "상표한글명": "COCO", "상표구분": "도형복합",
         "유사군": ["G4502"], "류": [25], "이미지파일": "d.png", "출원인": "샤넬 홀딩",
         "수집_출처": "기존 수집"},
        {"출원번호": "4020200000011", "상표한글명": "남의 것", "상표구분": "도형복합",
         "유사군": ["G0301"], "류": [30], "이미지파일": "e.png", "출원인": "지주회사",
         "수집_출처": "기존 수집"}]
    overrides = {"샤넬": {"fetch": [
        {"appno": "4020200000009", "role": fc.ROLE_LOGO_NOW, "source": "후보"},
        {"appno": "4020200000011", "role": fc.ROLE_LOGO_OLD, "source": "직접"}]}}
    chanel = _build(dist, overrides, db=DB + received).brand("샤넬")
    # 받은 대표 표장(수집 출처가 대표 표장)의 출원인만 더한다 — 이미 DB 에 있던 표장은 역할만
    assert chanel.added_applicants == ("샤넬 홀딩", "CHANEL HOLDING")
    assert chanel.applicants == ("샤넬", "샤넬 홀딩", "CHANEL HOLDING")
    assert chanel.applicant_keys == {"샤넬", "샤넬홀딩", "CHANELHOLDING"}
    assert [(m.appno, m.source, m.role) for m in chanel.marks] == [
        ("5", fc.SOURCE_FAMOUS, fc.ROLE_BRAND_OTHER),
        ("4020200000010", fc.SOURCE_EXISTING, fc.ROLE_UNRELATED),  # 더한 출원인의 다른 표장
        ("4020200000009", fc.SOURCE_RECEIVED, fc.ROLE_LOGO_NOW),
        ("4020200000011", fc.SOURCE_PICKED, fc.ROLE_LOGO_OLD)]
    assert chanel.fetch == () and [m.appno for m in chanel.logo_marks] == [
        "4020200000009", "4020200000011"]
    data = fc.registry_to_json(_build(dist, overrides, db=DB + received))
    assert next(b for b in data["brands"] if b["name"] == "샤넬")["applicants_added"] == [
        "샤넬 홀딩", "CHANEL HOLDING"]


def test_brands_sharing_an_applicant_split_marks_by_title(dist):
    db = DB + [
        {"출원번호": "6", "상표한글명": "백스비어", "상표구분": "도형복합", "유사군": ["G0301"],
         "류": [30], "이미지파일": "6.png", "출원인": "더본코리아"},
        {"출원번호": "7", "상표한글명": "PAIK'S COFFEE", "상표구분": "도형복합",
         "유사군": ["G0301"], "류": [30], "이미지파일": "7.png", "출원인": "더본코리아"},
        {"출원번호": "8", "상표한글명": None, "상표구분": "도형상표", "유사군": ["G0301"],
         "류": [30], "이미지파일": "8.png", "출원인": "더본코리아"}]
    alone = _build(dist, db=db).brand("PAIK'S")
    assert [m.appno for m in alone.marks] == ["6", "7", "8"]
    shared = _build(dist, {"백스비어": {"new": True, "notations": {"add": ["백스비어"]},
                                     "applicants": ["더본코리아"]}}, db=db)
    # 상표명에 그 브랜드 표기가 든 표장은 그 브랜드에, 어느 표기도 없는 표장은 둘 다에 보인다
    assert [m.appno for m in shared.brand("PAIK'S").marks] == ["7", "8"]
    assert [(m.appno, m.auto_role) for m in shared.brand("백스비어").marks] == [
        ("6", "이름"), ("8", "도형")]
    # 정할 수 없는 표장은 양쪽에 보이되 함께 걸린 브랜드를 적고, 어느 쪽의 대표 로고로도 안 쓴다
    assert [m.shared for m in shared.brand("PAIK'S").marks] == [(), ("백스비어",)]
    assert [m.shared for m in shared.brand("백스비어").marks] == [(), ("PAIK'S",)]
    both = {"백스비어": {"new": True, "notations": {"add": ["백스비어"]},
                      "applicants": ["더본코리아"], "marks": {"8": fc.ROLE_LOGO_NOW}},
            "PAIK'S": {"marks": {"8": fc.ROLE_LOGO_NOW}}}
    picked_twice = _build(dist, both, db=db)
    assert picked_twice.brand("PAIK'S").logo_marks == ()
    assert picked_twice.brand("백스비어").logo_marks == ()
    # 사람이 한 브랜드에서만 고르면 그 브랜드에만 잇는다
    one = _build(dist, {"백스비어": both["백스비어"]}, db=db)
    assert [m.appno for m in one.brand("PAIK'S").marks] == ["7"]
    assert [m.appno for m in one.brand("백스비어").logo_marks] == ["8"]
    data = fc.registry_to_json(shared)
    assert next(b for b in data["brands"] if b["name"] == "백스비어")["marks"][1]["shared"] == [
        "PAIK'S"]


def test_overrides_are_validated(tmp_path):
    assert fc.load_overrides(tmp_path / "none.json") == {
        "version": fc.OVERRIDES_VERSION, "brands": {}}
    shipped = fc.load_overrides()  # 저장소의 것(사람이 고르기 도구에서 정한 값)은 형식에 맞다
    assert shipped["version"] == fc.OVERRIDES_VERSION and isinstance(shipped["brands"], dict)
    parsed = fc.parse_overrides({"version": fc.OVERRIDES_VERSION, "brands": {"샤넬": {
        "notations": {"add": [" 샤넬르 ", "샤넬르", ""]}, "exceptions": ["채널", "채널"],
        "marks": {" 4020200000001 ": fc.ROLE_LOGO_NOW}, "preset": "",
        "fetch": [{"appno": "4020200000002"}]}}})
    assert parsed["brands"]["샤넬"] == {
        "preset": None, "notations": {"add": ["샤넬르"]}, "exceptions": ["채널"],
        "marks": {"4020200000001": fc.ROLE_LOGO_NOW},
        "fetch": [{"appno": "4020200000002", "role": fc.ROLE_LOGO_NOW, "source": "직접"}]}
    assert fc.normalize_appno("40-2020-0011726") == "4020200011726"
    for bad in (
        {"version": "famous_registry_overrides_v1", "brands": {}},
        {"version": fc.OVERRIDES_VERSION, "brands": {"샤넬": {"모르는 칸": 1}}},
        {"version": fc.OVERRIDES_VERSION, "brands": {"샤넬": {"protection": "넓게"}}},
        {"version": fc.OVERRIDES_VERSION,
         "brands": {"샤넬": {"marks": {"4020200000001": "이름"}}}},
        {"version": fc.OVERRIDES_VERSION,
         "brands": {"샤넬": {"fetch": [{"appno": "12", "role": fc.ROLE_LOGO_NOW}]}}},
        {"version": fc.OVERRIDES_VERSION, "brands": {"샤넬": {"notations": {"rename": []}}}},
        {"version": fc.OVERRIDES_VERSION, "brands": {"샤넬": {"notations": {"add": "샤넬르"}}}},
        {"version": fc.OVERRIDES_VERSION, "brands": {"새것": {"new": True}}},
        {"version": fc.OVERRIDES_VERSION, "brands": {"샤넬": {"fetch": [
            {"appno": "4020200000002"}, {"appno": "40-2020-0000002"}]}}},
        {"version": fc.OVERRIDES_VERSION, "brands": {"샤넬": {"fetch": [
            {"appno": "4020200000002", "source": "어딘가"}]}}},
    ):
        with pytest.raises(ValueError):
            fc.parse_overrides(bad)


def test_exact_and_contain_paths(registry, dist):
    exact = _check("스타벅스", CAFE, registry, dist)
    assert (exact.strongest.level, exact.strongest.path, exact.floor) == ("강함", "같음", "위험")
    assert _level("STARBUCKS COFFEE", None, registry, dist) == ("강함", "같음")
    assert _level("스타 벅스", None, registry, dist) == ("강함", "같음")  # 낱말 묶음
    # 붙여 쓴 꼴은 접미어 분리가 아니라 품음 + 나머지 판정으로 — 업종 낱말이면 품음-설명
    assert _level("스타벅스커피", None, registry, dist) == ("강함", "품음-설명")
    assert _level("스타벅스커피전문점", None, registry, dist) == ("강함", "품음-설명")  # 둘까지
    assert _level("커피스타벅스", CAFE, registry, dist) == ("강함", "품음-설명")  # 앞에 붙어도
    assert _level("뉴스타벅스", CAFE, registry, dist) == ("강함", "품음-설명")  # 3호(시기)
    assert _level("샤넬치킨", None, registry, dist) == ("강함", "품음-설명")  # 다른 업종 낱말도
    other = _check("스타벅스리", CAFE, registry, dist).strongest  # 한 음절(6호)은 설명 낱말이 아님
    assert (other.path, other.level, other.pending, other.floor) == (
        "품음-기타", "약함", True, "검토 권장")
    off = fc.Thresholds(contain_other=False)
    assert _check("스타벅스리", CAFE, registry, dist, thresholds=off).strongest is None
    three = _level("스타벅스커피치킨카페", None, registry, dist)  # 설명 낱말 셋은 인정하지 않는다
    assert three == ("약함", "품음-기타")
    assert _check("샤넬로", None, registry, dist).strongest is None  # 짧은 표기는 품음-설명만
    # 표기에 기호가 있어 질의에서 여러 낱말로 나뉘어도 묶음으로 본다
    assert _level("PAIK'S", None, registry, dist) == ("강함", "같음")
    assert _level("PAIK'S카페", None, registry, dist) == ("강함", "품음-설명")
    assert _check("PAIK'S카페", None, registry, dist).strongest.note == "paiks카페 = 표기 + 카페"


def test_sound_and_spelling_levels(registry, dist):
    assert _check("스타벅수", None, registry, dist).strongest is None  # 기준이 없으면 일치도 없음
    weak = fc.Thresholds(weak_sound={"김": 0.94})
    hit = _check("스타벅수", None, registry, dist, thresholds=weak).strongest
    assert (hit.brand, hit.level, hit.path, hit.floor) == ("스타벅스", "약함", "소리", "검토 권장")
    assert hit.score == pytest.approx(0.9636, abs=1e-4) and hit.note == "스타벅수"
    # 구간(낱말에서 설명 낱말을 뗀 앞·뒤)도 대상 — 한 음절 나머지("수")로는 구간이 생기지 않는다
    assert _level("스타벅수커피", None, registry, dist, thresholds=weak) == ("약함", "소리")
    assert _check("스타벅스터", None, registry, dist, thresholds=fc.Thresholds(
        contain_other=False, weak_sound={"김": 0.9})).strongest is None
    spelled = fc.Thresholds(weak_spelling={"김": 0.85})
    assert _level("STARBUCKZ", None, registry, dist, thresholds=spelled) == ("약함", "철자")
    strong = fc.Thresholds(strong_spelling={"김": 0.85})
    assert _level("STARBUCKZ", None, registry, dist, thresholds=strong) == ("강함", "철자")
    assert _check("STARBUCKZ", None, registry, dist, thresholds=fc.Thresholds(
        strong_spelling={"짧음": 0.85, "중간": 0.85})).strongest is None  # 길이 구간별
    # 철자는 같은 문자 종류끼리만 — 한글 질의는 영문 표기와 철자를 견주지 않는다
    evidence = fc.collect_evidence(fc.prepare_query("스타벅수", None), registry, dist, FLOOR,
                                   words=WORDS)
    star = next(e for e in evidence if e.brand == "스타벅스")
    assert star.items[1].spelling == 0.0 and star.items[0].spelling > 0.8
    assert star.items[1].sound == star.items[0].sound  # 소리는 한글 ↔ 영문도 견준다


def test_weak_spelling_needs_the_sound_condition(registry, dist):
    # channel ↔ chanel: 철자 6/7, 소리(채넬 ↔ 차넬)는 0.8 아래
    evidence = fc.collect_evidence(fc.prepare_query("CHANNEL", None), registry, dist, FLOOR,
                                   words=WORDS)
    unit = next(e for e in evidence if e.brand == "샤넬").items[1].units[0]
    assert unit[0] == "channel" and unit[2] == pytest.approx(6 / 7, abs=1e-4)
    assert 0.7 <= unit[1] < 0.8
    free = fc.Thresholds(weak_spelling={"김": 0.85})
    assert _level("CHANNEL", None, registry, dist, thresholds=free) == ("약함", "철자")
    low = fc.Thresholds(weak_spelling={"김": 0.85}, spelling_sound=0.70)
    assert _level("CHANNEL", None, registry, dist, thresholds=low) == ("약함", "철자")
    high = fc.Thresholds(weak_spelling={"김": 0.85}, spelling_sound=0.80)
    assert _check("CHANNEL", None, registry, dist, thresholds=high).strongest is None
    strong = fc.Thresholds(strong_spelling={"김": 0.85}, spelling_sound=0.80)
    # 소리 조건은 약한 철자에만 걸린다
    assert _level("CHANNEL", None, registry, dist, thresholds=strong) == ("강함", "철자")


def test_weak_notation_only_matches_alone(registry, dist):
    alone = _check("BBQ", CHICKEN, registry, dist).strongest
    assert (alone.level, alone.path, alone.notation, alone.kind) == (
        "강함", "같음", "BBQ", fc.KIND_WEAK)
    for name in ("BBQ치킨", "BBQ 치킨집", "BBQ치킨집", "치킨 BBQ", "맛있는 BBQ", "BBQ 치킨 전문점",
                 "비비큐", "비비큐치킨"):
        assert _level(name, CHICKEN, registry, dist) == ("강함", "같음"), name
    assert _level("BBQ", None, registry, dist) == ("강함", "같음")  # 업종 없음
    with_others = _check("텍사스 BBQ", CHICKEN, registry, dist)
    assert with_others.strongest.level == "설명적 사용 안내" and with_others.floor is None
    assert _level("서울비비큐", CHICKEN, registry, dist) is None  # 낱말 안에 묻힌 것은 표기가 아님
    assert _check("bbqs", CHICKEN, registry, dist).strongest is None
    # 업종이 다를 때: 그 업종에서도 식별력 없는 말이면 안내만, 식별력이 있으면 같음처럼 강함
    assert _level("BBQ", CLOTHES, registry, dist) == ("설명적 사용 안내", "같음")  # 3호(류 25)
    assert _level("BBQ", LAUNDRY, registry, dist) == ("강함", "같음")
    assert _check("BBQ", LAUNDRY, registry, dist).floor == "검토 권장"  # 같은·가까운 업종 중심
    # 소리가 같아 약한 표기가 된 표기는 그 약한 표기의 식별력을 따른다
    assert _level("비비큐", CLOTHES, registry, dist) == ("설명적 사용 안내", "같음")
    assert _level("비비큐", LAUNDRY, registry, dist) == ("강함", "같음")
    assert _level("CU", CAFE, registry, dist) == ("설명적 사용 안내", "같음")  # 6호는 어디서나
    assert _level("씨유", CAFE, registry, dist) == ("설명적 사용 안내", "같음")
    assert _level("씨유편의점", STORE, registry, dist) == ("강함", "같음")
    assert _level("CU LATER", STORE, registry, dist) == ("설명적 사용 안내", "같음")
    assert _check("CUTE", STORE, registry, dist).strongest is None
    assert _check("씨유어게인", STORE, registry, dist).strongest is None
    assert _level("C U", STORE, registry, dist) == ("강함", "같음")  # 띄어 써도 묶음


def test_weak_notation_is_hidden_from_sibling_notations(registry, dist):
    loose = fc.Thresholds(weak_sound={"김": 0.5, "중간": 0.5, "짧음": 0.5})
    # "김가네"는 약한 표기 — 같은 브랜드의 보통 표기 GIMGANE 와 소리로 견주지 않는다
    gimgane = _check("김가네 떡볶이", CHICKEN, registry, dist, thresholds=loose)
    assert [(m.brand, m.level) for m in gimgane.matches if m.brand == "김가네"] == [
        ("김가네", "설명적 사용 안내")]
    assert _level("GIMGANE", CHICKEN, registry, dist) == ("강함", "같음")  # 보통 표기는 그대로
    evidence = fc.collect_evidence(fc.prepare_query("김가네", None), registry, dist, FLOOR,
                                   words=WORDS)
    assert next(e for e in evidence if e.brand == "김가네").items[1].units == ()


def test_initialism_matches_only_exact_and_contain_desc(registry, dist):
    assert _level("bhc", CHICKEN, registry, dist) == ("강함", "같음")
    assert _level("BHC치킨", CHICKEN, registry, dist) == ("강함", "품음-설명")
    assert _level("비에이치씨", None, registry, dist) == ("강함", "같음")
    loose = fc.Thresholds(weak_sound={"김": 0.5, "짧음": 0.5}, weak_spelling={"김": 0.5},
                          strong_spelling={"김": 0.6, "짧음": 0.6})
    for name in ("비에치씨", "비에이치시", "bhk", "bhcc", "비에이치씨월드"):
        assert _check(name, CHICKEN, registry, dist, thresholds=loose).strongest is None, name


def test_descriptive_use_of_a_normal_notation():
    names, classes = dx.goods_index(GOODS)
    plain = dx.Distinctiveness({}, famous={"커피"}, goods_names=names, code_classes=classes,
                               descriptive={})
    table = [{"notations": ["커피"], "applicants": ["커피 회사"], "preset": "clothing",
              "evidence": "", "urls": []}]
    registry = fc.build_registry(table, plan_records=[], db_records=[], dist=plain,
                                 preset_codes=PRESETS, preset_labels={}, applicant_keys=_keys)
    assert registry.brands[0].notations[0].kind == fc.KIND_NORMAL  # 자기 업종(의류)에선 식별력
    cafe = fc.check_famous("커피", CAFE, registry, fc.Thresholds(), dist=plain,
                           goods_floor=FLOOR, words=frozenset())
    assert cafe.strongest.level == "설명적 사용 안내" and cafe.floor is None
    same = fc.check_famous("커피", CLOTHES, registry, fc.Thresholds(), dist=plain,
                           goods_floor=FLOOR, words=frozenset())
    assert same.strongest.level == "강함" and same.floor == "위험"


def test_brand_industry_for_names_ignores_unrelated_marks(registry, dist):
    # 스타벅스의 도형 표장(2번 — 고르기 전 "관련 없음")은 의류에 등록돼 있지만 이름 일치의 업종
    # 겹침에는 쓰지 않는다
    evidence = fc.collect_evidence(fc.prepare_query("스타벅스", CLOTHES), registry, dist, FLOOR,
                                   words=WORDS)
    star = next(e for e in evidence if e.brand == "스타벅스")
    assert (star.overlap, star.overlap_value) == (False, 0.0)
    assert next(e for e in fc.collect_evidence(
        fc.prepare_query("스타벅스", CAFE), registry, dist, FLOOR, words=WORDS)
        if e.brand == "스타벅스").overlap is True


def test_floor_depends_on_protection_and_overlap(registry, dist):
    near = fc.Registry(fc.REGISTRY_VERSION, tuple(
        fc.Brand(**{**b.__dict__, "protection": fc.PROTECT_NEAR}) for b in registry.brands))
    weak = fc.Thresholds(weak_sound={"김": 0.94})

    def floor(name, goods, source=near):
        return _check(name, goods, source, dist, thresholds=weak).floor

    assert floor("스타벅스", CAFE) == "위험" and floor("스타벅스", None) == "위험"
    assert floor("스타벅스", LAUNDRY) == "검토 권장"  # 같은·가까운 업종 중심 + 업종 다름
    assert floor("스타벅수", CAFE) == "검토 권장" and floor("스타벅수", LAUNDRY) is None
    assert floor("스타벅스", LAUNDRY, registry) == "위험"  # 업종 불문
    assert floor("스타벅수", LAUNDRY, registry) == "검토 권장"
    match = _check("스타벅수", LAUNDRY, near, dist, thresholds=weak).strongest
    assert (match.level, match.overlap, match.floor) == ("약함", False, None)


def test_ocr_text_uses_exact_and_contain_only(registry, dist):
    weak = fc.Thresholds(weak_sound={"김": 0.90})
    by_text = _check(None, CLOTHES, registry, dist, ocr_text="STARBUCKS COFFEE")
    assert by_text.basis == fc.BASIS_OCR and by_text.strongest.basis == fc.BASIS_OCR
    assert by_text.strongest.path == "같음" and by_text.floor == "위험"
    assert _level(None, None, registry, dist, ocr_text="스타벅스커피") == ("강함", "품음-설명")
    missed = _check(None, None, registry, dist, ocr_text="스타벅수", thresholds=weak)
    assert missed.strongest is None  # 이미지 속 글자는 소리·철자로 견주지 않는다
    # 같음·품음-설명(강함)만 — 품음-기타와 약한 표기의 안내는 내지 않는다
    assert _level("스타벅스리", None, registry, dist) == ("약함", "품음-기타")
    assert _check(None, None, registry, dist, ocr_text="스타벅스리").strongest is None
    assert _level("텍사스 BBQ", CHICKEN, registry, dist) == ("설명적 사용 안내", "같음")
    assert _check(None, CHICKEN, registry, dist, ocr_text="텍사스 BBQ").strongest is None
    assert _level(None, CHICKEN, registry, dist, ocr_text="BBQ치킨") == ("강함", "같음")
    assert _check("", None, registry, dist).matches == ()
    named = _check("스타벅수", None, registry, dist, ocr_text="STARBUCKS", thresholds=weak)
    assert named.basis == fc.BASIS_NAME and named.strongest.path == "소리"  # 이름이 있으면 이름으로


def test_thresholds_round_trip():
    thresholds = fc.Thresholds(strong_spelling={"김": 0.95}, weak_sound={"김": 0.9},
                               weak_spelling={"중간": 0.85}, spelling_sound=0.8,
                               contain_other=False)
    again = fc.Thresholds.from_dict(json.loads(json.dumps(thresholds.to_dict())))
    assert again.strong_sound == 0.98 and again.spelling_sound == 0.8
    assert again.strong_spelling == {"짧음": None, "중간": None, "김": 0.95}
    assert again.weak_sound == {"짧음": None, "중간": None, "김": 0.9}
    assert again.weak_spelling["중간"] == 0.85 and again.contain_other is False
    assert fc.Thresholds.from_dict({}).spelling_sound is None
    assert again.weak_mode == "W0" and again.weak_pair_sound == fc.WEAK_PAIR_SOUND
    assert fc.Thresholds.from_dict({"weak_mode": "W2"}).weak_mode == "W2"
    with pytest.raises(ValueError):
        fc.Thresholds(weak_mode="W9")


def _decide_units(mode, units, *, length="김", script="한글"):
    """보통 표기 하나의 대상(이름, 소리, 철자)들에 약한 일치 조건을 적용한 결과(수준, 경로)."""
    thresholds = fc.Thresholds(
        weak_sound={"짧음": 0.90, "중간": 0.92, "김": 0.90},
        weak_spelling={"짧음": 0.75, "중간": 0.75, "김": 0.75}, weak_mode=mode)
    item = fc.Evidence(notation="표기", key="표기", length=length, kind=fc.KIND_NORMAL,
                       units=tuple(units), script=script, exempt=frozenset({"예외"}))
    result = fc.decide([fc.BrandEvidence("브랜드", fc.PROTECT_ANY, None, None, (item,))],
                       thresholds)
    return None if result.strongest is None else (result.strongest.level, result.strongest.path)


def test_weak_match_conditions():
    spelling_only = [("가나다라", 0.70, 0.80)]  # 철자만 닮음
    sound_only = [("가나다라", 0.91, 0.60)]  # 소리만 닮음
    both = [("가나다라", 0.86, 0.78)]  # 소리 0.85·철자 0.75 를 둘 다 넘지만 약한 소리에는 못 미침
    other_script = [("abcd", 0.91, 0.0)]  # 문자가 다르면 소리만
    assert [_decide_units("W0", u) for u in (spelling_only, sound_only, both, other_script)] == [
        ("약함", "철자"), ("약함", "소리"), ("약함", "철자"), ("약함", "소리")]
    assert [_decide_units("W1", u) for u in (spelling_only, sound_only, both, other_script)] == [
        None, ("약함", "소리"), None, ("약함", "소리")]
    assert [_decide_units("W2", u) for u in (spelling_only, sound_only, both, other_script)] == [
        None, None, ("약함", "소리"), ("약함", "소리")]
    # W3: 짧은·중간 표기는 소리만, 긴 표기는 소리 또는 철자
    assert _decide_units("W3", spelling_only, length="김") == ("약함", "철자")
    assert _decide_units("W3", spelling_only, length="중간") is None
    assert _decide_units("W3", [("가나다", 0.93, 0.5)], length="중간") == ("약함", "소리")
    assert _decide_units("W3", [("가나", 0.90, 0.5)], length="짧음") == ("약함", "소리")
    # 예외 낱말은 어느 조건에서나 약한 일치에 쓰지 않는다
    for mode in fc.WEAK_MODES:
        assert _decide_units(mode, [("예외", 0.95, 0.95)]) is None


def test_retail_class_is_left_out(dist):
    """35류(판매업)는 약한 표기의 다른 업종 판정과 이름 일치용 업종 겹침에서 뺀다 — 질의 업종과
    브랜드 업종 세트가 둘 다 35류뿐일 때만 그대로."""
    names, classes = dx.goods_index(GOODS)
    retail = dx.Distinctiveness({}, goods_names=names, code_classes=classes,
                                descriptive=dx.validate_descriptive_terms({"terms": {
                                    "bbq": {"kind": "용도", "absolute": False,
                                            "classes": [29, 35]}}}))
    registry = _build(retail)
    clothes_shop = CLOTHES | STORE  # 의류 + 그 판매업
    full = retail.judge("bbq", clothes_shop, famous_exception=False)
    assert full.score == 0.0  # 그대로 보면 35류 때문에 의류에서도 성질표시
    assert fc.retail_free(retail).judge("bbq", clothes_shop, famous_exception=False).score > 0.5
    assert fc.retail_free(retail) is fc.retail_free(retail) and retail.code_classes["S2090"]
    assert _level("BBQ", clothes_shop, registry, retail) == ("강함", "같음")
    assert _level("BBQ", CHICKEN, registry, retail) == ("강함", "같음")
    # 겹침: 판매업 코드만 같은 것은 겹침이 아니다 — 편의점(35류뿐)끼리는 그대로 잰다
    evidence = {e.brand: e for e in fc.collect_evidence(
        fc.prepare_query("CU", CAFE | STORE), registry, retail, FLOOR, words=WORDS)}
    assert evidence["CU"].overlap is False and evidence["스타벅스"].overlap is True
    store = {e.brand: e for e in fc.collect_evidence(
        fc.prepare_query("CU", STORE), registry, retail, FLOOR, words=WORDS)}
    assert (store["CU"].overlap, store["CU"].overlap_by) == (True, "유사군")
    assert store["스타벅스"].overlap is False  # 질의는 35류뿐이지만 브랜드 업종 세트는 아니다
    assert fc.goods_classes(CAFE | STORE, retail) == {30, 35}


def test_core_classes_join_overlap_and_descriptive_words(dist):
    goods = GoodsMap(list(GOODS.entries) + [GoodsEntry("운동화", 28, ("G4301",))])
    names, classes = dx.goods_index(goods)
    sports = dx.Distinctiveness({}, goods_names=names, code_classes=classes)
    overrides = {"나이키": {"new": True, "notations": {"add": ["나이키"]}, "core_classes": [28]}}
    registry = _build(sports, overrides)
    nike = registry.brand("나이키")
    assert nike.core_classes == (28,) and nike.preset is None and nike.preset_classes == ()

    def overlap(codes, classes=None):
        found = fc.collect_evidence(fc.prepare_query("나이키", codes, classes), registry, sports,
                                    FLOOR, words=WORDS)
        hit = next(e for e in found if e.brand == "나이키")
        return hit.overlap, hit.overlap_by

    assert overlap({"G4301"}) == (True, "핵심 류")  # 류는 유사군 코드에서 얻는다
    assert overlap(CAFE) == (False, None) and overlap(None) == (None, None)
    assert overlap(CAFE, [28]) == (True, "핵심 류")  # 받은 류가 먼저
    assert overlap({"G4301"}, [30]) == (False, None)
    # 핵심 류의 보통명칭은 설명 낱말 — 표장의 지정상품 전체로는 넓히지 않는다
    assert _level("나이키운동화", None, registry, sports) == ("강함", "품음-설명")
    assert _level("나이키세탁업", None, registry, sports) == ("약함", "품음-기타")
    data = fc.registry_to_json(registry)
    industry = next(b for b in data["brands"] if b["name"] == "나이키")["industry"]
    assert industry["core_classes"] == [28] and industry["classes"] == []
    for bad in ([0], [46], ["9"], 9, [True]):
        with pytest.raises(ValueError):
            fc.parse_overrides({"version": fc.OVERRIDES_VERSION,
                                "brands": {"스타벅스": {"core_classes": bad}}})


def test_common_notation_is_only_a_notice_in_another_industry(dist):
    overrides = {"애플": {"new": True, "preset": "cafe",
                         "notations": {"add": ["애플", "APPLE"], "common": ["애플"]}}}
    registry = _build(dist, overrides)
    assert [n.kind for n in registry.brand("애플").notations] == [fc.KIND_WEAK, fc.KIND_WEAK]
    assert _level("애플", CAFE, registry, dist) == ("강함", "같음")
    assert _level("애플", None, registry, dist) == ("강함", "같음")
    for name in ("애플", "APPLE"):  # 흔한 말과 그 표기를 소리로 따르는 표기 — 업종이 다르면 안내만
        other = _check(name, LAUNDRY, registry, dist)
        assert (other.strongest.level, other.strongest.note) == (
            "설명적 사용 안내", fc.COMMON_NOTE) and other.floor is None


def test_masking_does_not_hide_an_exact_match_with_a_longer_notation(dist):
    """가림의 예외 — 약한 표기가 같은 브랜드의 더 긴 표기의 앞 낱말일 때, 띄어 쓴 꼴도 같음이다."""
    overrides = {"당근": {"new": True, "preset": "cafe",
                         "notations": {"add": ["당근", "당근마켓"], "common": ["당근"]}}}
    registry = _build(dist, overrides)
    assert [n.kind for n in registry.brand("당근").notations] == [fc.KIND_WEAK, fc.KIND_NORMAL]
    for name in ("당근마켓", "당근 마켓"):
        hit = _check(name, None, registry, dist).strongest
        assert (hit.level, hit.path, hit.notation) == ("강함", "같음", "당근마켓"), name
    assert _check("당근 마켓", LAUNDRY, registry, dist).strongest.notation == "당근마켓"
    # 같음이 아닌 것은 그대로 가린다 — 약한 표기가 다른 말과 함께 쓰인 것으로 본다
    weak = fc.Thresholds(weak_sound={"짧음": 0.5, "중간": 0.5, "김": 0.5})
    other = _check("당근 마캣", None, registry, dist, thresholds=weak).strongest
    assert (other.level, other.notation, other.note) == (
        "설명적 사용 안내", "당근", "약한 표기 — 다른 말과 함께")
    assert _level("당근 카페", None, registry, dist) == ("강함", "같음")  # 설명 낱말과는 단독


def test_logo_match_rule():
    risk, review = "위험", "검토 권장"
    assert fc.logo_match(0.95, risk) and not fc.logo_match(0.95, review)
    text = fc.LOGO_KIND_TEXT
    assert not fc.logo_match(0.95, risk, logo_kind=text, query_kind=text)  # 글자끼리는 0.98 부터
    assert fc.logo_match(0.98, risk, logo_kind=text, query_kind=text)
    assert fc.logo_match(0.95, risk, logo_kind=text, query_kind="결합")
    assert not fc.logo_match(0.99, risk, logo_photo=True)
    assert not fc.logo_match(0.99, risk, query_photo=True)


def test_brand_table_matches_the_collection_parser():
    rows = fc.read_brand_table()
    assert len(rows) == 30 and rows[0]["notations"][0] == "컴포즈커피"
    assert all(row["urls"] for row in rows)  # 브랜드마다 근거 URL
    from backend.scripts import collect_pipeline as cp

    table = cp.read_brand_rows(fc.DEFAULT_BRANDS_PATH)
    assert [row["notations"] for row in rows] == [cp.brand_names(r.brand) for r in table]
    assert [row["applicants"] for row in rows] == [cp.applicant_names(r.applicant) for r in table]
    assert [row["preset"] for row in rows] == [r.industry for r in table]
    for title, names in (("Nice to CU", ["CU"]), ("cupon", ["CU"]),
                         ("동대문 엽기 떡볶이", ["엽기떡볶이"]), ("PAIK'S COFFEE", ["PAIK'S"]),
                         (None, ["CU"])):
        assert fc.title_has_notation(title, names) == cp.title_has_brand(title, names)


def test_shipped_registry_follows_the_brand_table_and_overrides():
    registry = fc.load_registry()
    rows = fc.read_brand_table()
    overrides = fc.load_overrides()["brands"]
    table_names = [row["notations"][0] for row in rows]
    # [브랜드] 표의 브랜드가 표의 순서로 먼저, 사람이 더한 새 브랜드가 그 뒤
    assert [b.table_name for b in registry.brands if not b.is_new] == table_names
    assert [b.table_name for b in registry.brands][:len(rows)] == table_names
    assert {b.table_name for b in registry.brands if b.is_new} == {
        name for name, item in overrides.items() if item.get("new")}
    for brand, row in zip(registry.brands, rows):
        edits = (overrides.get(brand.table_name) or {}).get("notations") or {}
        kept = [text for text in row["notations"] if text not in edits.get("remove", ())]
        # 표기 = 표의 표기에서 사람이 지운 것을 빼고 더한 것을 붙인 것(새 표기를 지어내지 않는다)
        assert [n.text for n in brand.notations] == kept + [
            text for text in edits.get("add", ()) if text not in kept]
        assert list(brand.removed_notations) == [
            text for text in row["notations"] if text in edits.get("remove", ())]
        if "applicants" not in (overrides.get(brand.table_name) or {}):
            assert list(brand.applicants) == row["applicants"] + list(brand.added_applicants)
        if "preset" not in (overrides.get(brand.table_name) or {}):
            assert brand.preset == row["preset"]
    for brand in registry.brands:
        assert brand.protection in fc.PROTECTIONS and brand.notations
        if "protection" not in (overrides.get(brand.table_name) or {}):
            assert brand.protection == (
                fc.PROTECT_ANY if brand.table_name in fc.PROTECT_ANY_BRANDS
                else fc.PROTECT_NEAR)
        texts = {n.text for n in brand.notations}
        for notation in brand.notations:
            assert notation.key == fc.text_key(notation.text)
            assert notation.length == fc.length_class(notation.key)
            assert notation.script == fc.script_label(notation.key)
            assert notation.kind in fc.KINDS and set(notation.inherits) <= texts
            assert not (notation.base_weak or notation.common) or notation.kind == fc.KIND_WEAK
        for mark in brand.marks:
            assert mark.role in fc.MARK_ROLES and mark.auto_role in fc.AUTO_ROLES
            if not mark.picked:  # 고르지 않은 표장은 자동 역할의 기본값
                assert mark.role == fc.DEFAULT_ROLE[mark.auto_role]
    # 한 표장이 여러 브랜드에 보이는 것은 출원인을 함께 쓰는 브랜드 사이에서만
    owners: dict[str, list[fc.Brand]] = {}
    for brand in registry.brands:
        for mark in brand.marks:
            owners.setdefault(mark.appno, []).append(brand)
    for brands in owners.values():
        for other in brands[1:]:
            assert brands[0].applicant_keys & other.applicant_keys
    kinds = {(b.table_name, n.text): n.kind for b in registry.brands for n in b.notations}
    for key in (("BBQ", "BBQ"), ("BBQ", "비비큐"), ("CU", "CU"), ("CU", "씨유"), ("GS25", "GS25"),
                ("GS25", "지에스25"), ("김가네", "김가네")):
        assert kinds[key] == fc.KIND_WEAK
    assert kinds[("bhc", "bhc")] == kinds[("bhc", "비에이치씨")] == fc.KIND_INITIAL


def test_shipped_registry_matches_plan_database_and_rebuild():
    if not PLAN.exists() or not METADATA.exists():
        pytest.skip("수집 계획·DB 메타데이터 없음(비공개 데이터)")
    # 다시 만들어도 같은 파일(overrides 적용 포함). 시험 환경은 변환표·업종 세트 경로를 가짜로
    # 바꿔 두므로(backend conftest), 그 변수들을 뺀 새 프로세스에서 만든다
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("MARKLENS_")}
    done = subprocess.run(
        [sys.executable, str(REPO_ROOT / "ml" / "scripts" / "famous_registry.py"), "check"],
        env=env, capture_output=True, text=True, cwd=REPO_ROOT, check=False)
    assert done.returncode == 0, done.stdout[-400:] + done.stderr[-400:]
    registry = fc.load_registry()
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    records = {str(r["출원번호"]): r for r in json.loads(
        METADATA.read_text(encoding="utf-8"))["trademarks"]}
    for record in plan["records"]:  # 수집 계획의 표장은 그 브랜드에, 이름 여부도 수집 때와 같게
        brand = registry.brand(record["브랜드"])
        mark = next(m for m in brand.marks if m.appno == str(record["출원번호"]))
        assert mark.source == fc.SOURCE_FAMOUS
        if not brand.removed_notations:  # 표기를 지운 브랜드는 자동 역할이 수집 때와 다를 수 있다
            assert bool(record["브랜드명_포함"]) <= (mark.auto_role == fc.ROLE_NAME)
    sources = {fc.SOURCE_FAMOUS: "유명 브랜드", fc.SOURCE_RECEIVED: fc.DB_SOURCE_LOGOS,
               fc.SOURCE_EXISTING: "기존 수집"}
    for brand in registry.brands:
        for mark in brand.marks:
            record = records[mark.appno]
            assert mark.codes == fc.normalize_codes(record.get("유사군") or ())
            assert mark.image == record.get("이미지파일")
            if mark.source in sources:  # 출처는 그 표장이 DB 에 들어온 길 그대로
                assert record.get("수집_출처") == sources[mark.source]
        for entry in brand.fetch:  # 받을 표장으로 남은 것은 아직 DB 에 없는 것뿐
            assert entry["appno"] not in records
