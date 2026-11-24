"""유명 상표 확인(src.famous_check, 통합 모델 설계 §7-14) — 등록부와 일치 판정의 단위 시험.
장난감 등록부·식별력 모델로 규칙을 보고, 저장소의 등록부(shared/famous_registry.json)가 표·수집
계획·DB 와 어긋나지 않는지는 데이터가 있을 때만 본다."""

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

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN = REPO_ROOT / "ml" / "data" / "staging" / "famous_brands.plan.json"
METADATA = REPO_ROOT / "ml" / "data" / "kipris_metadata.json"
GOODS = GoodsMap([
    GoodsEntry("커피", 30, ("G0301",)),
    GoodsEntry("치킨", 29, ("G0703",)),
    GoodsEntry("의류", 25, ("G4502",)),
    GoodsEntry("세탁업", 37, ("S1282",)),
])
CAFE, CHICKEN, CLOTHES, LAUNDRY = ({"G0301"}, {"G0703"}, {"G4502"}, {"S1282"})
FLOOR = 0.0252
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
]
DB = [
    {"출원번호": "1", "상표한글명": "STARBUCKS COFFEE", "상표구분": "도형복합", "유사군": ["G0301"],
     "류": [30], "이미지파일": "1.png", "출원인": "스타벅스 코포레이션",
     "수집_출처": "유명 브랜드"},
    {"출원번호": "2", "상표한글명": None, "상표구분": "도형상표", "유사군": ["G0301"], "류": [30],
     "이미지파일": "2.png", "출원인": "스타벅스 코포레이션", "수집_출처": "유명 브랜드"},
    {"출원번호": "3", "상표한글명": "로제치킨 bbq", "상표구분": "도형복합", "유사군": ["G0703"],
     "류": [29], "이미지파일": "3.png", "출원인": "주식회사 제너시스비비큐",
     "수집_출처": "유명 브랜드"},
    {"출원번호": "4", "상표한글명": "치킨대학", "상표구분": "도형복합", "유사군": ["G0703"],
     "류": [29], "이미지파일": "4.png", "출원인": "(주)제너시스비비큐", "수집_출처": "기존 수집"},
    {"출원번호": "5", "상표한글명": "샤넬 CHANEL", "상표구분": "도형복합", "유사군": ["G4502"],
     "류": [25], "이미지파일": "5.png", "출원인": "샤넬", "수집_출처": "유명 브랜드"},
    {"출원번호": "9", "상표한글명": "무관한 상표", "상표구분": "도형복합", "유사군": ["G0301"],
     "류": [30], "이미지파일": "9.png", "출원인": "다른 회사", "수집_출처": "기존 수집"},
]
PLAN_RECORDS = [{"출원번호": "1", "브랜드": "스타벅스"}, {"출원번호": "2", "브랜드": "스타벅스"},
                {"출원번호": "3", "브랜드": "BBQ"}, {"출원번호": "5", "브랜드": "샤넬"}]
PRESETS = {"cafe": ["G0301"], "chicken": ["G0703"], "clothing": ["G4502"]}


def _keys(text: str) -> frozenset[str]:
    value = str(text or "").replace("주식회사", "").replace("(주)", "").replace(" ", "")
    return frozenset({value}) if value else frozenset()


@pytest.fixture(scope="module")
def dist() -> dx.Distinctiveness:
    names, classes = dx.goods_index(GOODS)
    descriptive = dx.validate_descriptive_terms({"terms": {
        "bbq": {"kind": "용도", "absolute": False, "classes": [29, 43]},
        "맛있는": {"kind": "품질", "absolute": True}}})
    return dx.Distinctiveness({}, famous={"스타벅스", "샤넬", "네이버"}, goods_names=names,
                              code_classes=classes, descriptive=descriptive)


@pytest.fixture(scope="module")
def registry(dist) -> fc.Registry:
    return fc.build_registry(
        TABLE, plan_records=PLAN_RECORDS, db_records=DB, preset_codes=PRESETS,
        preset_labels={"cafe": "카페"}, dist=dist, applicant_keys=_keys,
        image_exists=lambda name: name != "2.png")


def _check(name, goods, registry, dist, **kwargs):
    thresholds = kwargs.pop("thresholds", fc.Thresholds())
    return fc.check_famous(name, goods, registry, thresholds, dist=dist, goods_floor=FLOOR,
                           **kwargs)


def test_text_helpers():
    assert fc.text_key("L'OREAL") == "loreal" and fc.text_key("본죽&비빔밥") == "본죽비빔밥"
    assert fc.text_key(" Star​Bucks® ") == "starbucks"
    assert fc.script_label("gs25") == "영문+숫자" and fc.script_label("지에스25") == "한글+숫자"
    assert [fc.length_class(k) for k in ("샤넬", "bhc", "네이버", "paiks", "스타벅스", "loreal",
                                         "지에스25", "gs25")] == [
        "짧음", "짧음", "중간", "중간", "김", "김", "김", "중간"]


def test_registry_roles_goods_and_weak_notations(registry):
    star, bbq = registry.brand("스타벅스"), registry.brand("BBQ")
    assert [(m.appno, m.role, m.image_exists) for m in star.marks] == [
        ("1", "이름", True), ("2", "도형", False)]
    assert [(m.appno, m.role, m.source) for m in bbq.marks] == [
        ("3", "이름", fc.SOURCE_FAMOUS), ("4", "다른 이름", fc.SOURCE_EXISTING)]
    assert bbq.goods_codes == {"G0703"} and bbq.goods_source == "브랜드 표장"
    assert {n.text: n.weak for n in bbq.notations} == {"BBQ": True, "비비큐": False}
    assert not any(n.weak for n in star.notations)  # 유명 예외를 빼도 조어
    naver = registry.brand("네이버")
    assert naver.marks == () and naver.goods_source == "업종 세트"
    assert naver.goods_sets == (frozenset({"G0301"}),)
    assert registry.applicant_keys >= {"스타벅스코포레이션", "제너시스비비큐", "샤넬"}
    assert star.evidence_urls == ("https://example.org/a",) and star.protection == fc.PROTECT_ANY


def test_registry_json_round_trip_and_overrides(registry, dist, tmp_path):
    data = fc.registry_to_json(registry)
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert fc.load_registry(path) == registry
    overrides = {"brands": {"샤넬": {"protection": fc.PROTECT_NEAR}},
                 "marks": {"2": {"role": fc.ROLE_EXCLUDED}, "4": {"role": fc.ROLE_LOGO}}}
    changed = fc.build_registry(
        TABLE, plan_records=PLAN_RECORDS, db_records=DB, preset_codes=PRESETS,
        preset_labels={}, dist=dist, applicant_keys=_keys, overrides=overrides)
    assert changed.brand("샤넬").protection == fc.PROTECT_NEAR
    assert [m.role for m in changed.brand("스타벅스").marks] == ["이름", "제외"]
    assert [(m.role, m.auto_role) for m in changed.brand("BBQ").marks] == [
        ("이름", "이름"), ("브랜드 로고", "다른 이름")]
    assert len(changed.brand("BBQ").brand_marks) == 2
    with pytest.raises(ValueError):
        fc.build_registry(TABLE, plan_records=PLAN_RECORDS, db_records=DB, preset_codes=PRESETS,
                          preset_labels={}, dist=dist, applicant_keys=_keys,
                          overrides={"brands": {}, "marks": {"404": {"role": fc.ROLE_LOGO}}})


def test_overrides_file_is_validated(tmp_path):
    assert fc.load_overrides(tmp_path / "none.json")["marks"] == {}
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"version": fc.OVERRIDES_VERSION, "brands": {},
                               "marks": {"1": {"role": "이름"}}}), encoding="utf-8")
    with pytest.raises(ValueError):
        fc.load_overrides(bad)
    shipped = fc.load_overrides()
    assert shipped["brands"] == {} and shipped["marks"] == {}  # 처음엔 빈 틀


def test_exact_and_contain_paths(registry, dist):
    exact = _check("스타벅스", CAFE, registry, dist)
    assert (exact.strongest.level, exact.strongest.path, exact.floor) == ("강함", "같음", "위험")
    assert _check("STARBUCKS COFFEE", None, registry, dist).strongest.path == "같음"
    assert _check("스타벅스커피", None, registry, dist).strongest.path == "같음"  # 접미어 분리
    spaced = _check("스타 벅스", None, registry, dist)  # 낱말 묶음을 붙인 꼴
    assert spaced.strongest.path == "같음" and spaced.strongest.brand == "스타벅스"
    desc = _check("뉴스타벅스", CAFE, registry, dist).strongest  # 나머지 1음절 = 식별력 없는 말
    assert (desc.path, desc.level) == ("품음-설명", "강함")
    other = _check("스타벅스플래닛", CAFE, registry, dist).strongest
    assert (other.path, other.level, other.pending) == ("품음-기타", "약함", True)
    assert other.floor == "검토 권장"
    off = _check("스타벅스플래닛", CAFE, registry, dist,
                 thresholds=fc.Thresholds(strong_sound=None, contain_other=False))
    assert off.strongest is None
    # 1음절 나머지는 식별력 없는 말(6호)이라 앞 구간 "스타벅스리"가 소리 대상이 된다 — X1 의
    # 붙여쓴 결합어 포함 점수(4/5 음절 → 0.98)로 강한 소리
    trimmed = _check("스타벅스리움", CAFE, registry, dist).strongest
    assert (trimmed.path, trimmed.level, trimmed.score) == ("소리", "강함", 0.98)
    short = _check("샤넬리움", None, registry, dist,
                   thresholds=fc.Thresholds(strong_sound=None))  # 짧은 표기는 품음-설명만
    assert short.strongest is None
    assert _check("샤넬로", None, registry, dist).strongest.path == "품음-설명"


def test_sound_and_spelling_levels(registry, dist):
    none = fc.Thresholds()
    assert _check("스타벅수", None, registry, dist, thresholds=none).strongest is None
    weak = fc.Thresholds(weak_sound={"짧음": None, "중간": None, "김": 0.94})
    hit = _check("스타벅수", None, registry, dist, thresholds=weak).strongest
    assert (hit.brand, hit.level, hit.path, hit.floor) == ("스타벅스", "약함", "소리", "검토 권장")
    cross = _check("스타벅스", None, fc.Registry(fc.REGISTRY_VERSION, tuple(
        fc.Brand(**{**b.__dict__, "notations": b.notations[1:]}) for b in registry.brands
        if b.name == "스타벅스")), dist)
    assert (cross.strongest.path, cross.strongest.notation) == ("소리", "STARBUCKS")  # 한글 ↔ 영문
    spelled = _check("STARBUCKZ", None, registry, dist, thresholds=fc.Thresholds(
        strong_sound=None, weak_spelling={"짧음": None, "중간": None, "김": 0.85}))
    assert (spelled.strongest.path, spelled.strongest.level) == ("철자", "약함")
    assert _check("STARBUCKZ", None, registry, dist, thresholds=fc.Thresholds(
        strong_sound=None, strong_spelling=0.85)).strongest.level == "강함"
    # 철자는 같은 문자 종류끼리만 — 한글 질의는 영문 표기와 철자를 견주지 않는다
    evidence = fc.collect_evidence(fc.prepare_query("스타벅수", None, dist), registry, dist, FLOOR)
    star = next(e for e in evidence if e.brand == "스타벅스")
    assert star.items[1].spelling == 0.0 and star.items[0].spelling > 0.8


def test_weak_notation_only_matches_alone(registry, dist):
    alone = _check("BBQ", CHICKEN, registry, dist).strongest
    assert (alone.level, alone.path, alone.notation) == ("강함", "같음", "BBQ")
    assert _check("BBQ치킨", CHICKEN, registry, dist).strongest.level == "강함"  # 치킨 = 상품 말
    assert _check("맛있는 BBQ", None, registry, dist).strongest.level == "강함"  # 성질표시
    with_others = _check("텍사스 BBQ", CHICKEN, registry, dist)
    assert with_others.strongest.level == "설명적 사용 안내" and with_others.floor is None
    different = _check("BBQ", LAUNDRY, registry, dist)
    assert different.strongest.level == "설명적 사용 안내" and different.floor is None
    assert _check("BBQ", None, registry, dist).strongest.level == "강함"  # 업종 없음
    assert _check("bbqs", CHICKEN, registry, dist).strongest is None  # 조각이 아니면 표기가 아님
    hangul = _check("비비큐", LAUNDRY, registry, dist).strongest  # 약하지 않은 표기는 보통 규칙
    assert (hangul.level, hangul.notation) == ("강함", "비비큐")


def test_descriptive_use_of_a_normal_notation(dist):
    names, classes = dx.goods_index(GOODS)
    plain = dx.Distinctiveness({}, famous={"커피"}, goods_names=names, code_classes=classes,
                               descriptive={})
    table = [{"notations": ["커피"], "applicants": ["커피 회사"], "preset": "clothing",
              "evidence": "", "urls": []}]
    registry = fc.build_registry(table, plan_records=[], db_records=[], dist=plain,
                                 preset_codes=PRESETS, preset_labels={}, applicant_keys=_keys)
    assert not registry.brands[0].notations[0].weak  # 자기 업종(의류)에서는 식별력 있음
    cafe = fc.check_famous("커피", CAFE, registry, fc.Thresholds(), dist=plain,
                           goods_floor=FLOOR)
    assert cafe.strongest.level == "설명적 사용 안내" and cafe.floor is None
    same = fc.check_famous("커피", CLOTHES, registry, fc.Thresholds(), dist=plain,
                           goods_floor=FLOOR)
    assert same.strongest.level == "강함" and same.floor == "위험"


def test_floor_depends_on_protection_and_overlap(registry, dist):
    near = fc.Registry(fc.REGISTRY_VERSION, tuple(
        fc.Brand(**{**b.__dict__, "protection": fc.PROTECT_NEAR}) for b in registry.brands))
    weak = fc.Thresholds(weak_sound={"짧음": None, "중간": None, "김": 0.94})

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
    weak = fc.Thresholds(weak_sound={"짧음": None, "중간": None, "김": 0.90})
    by_text = _check(None, CLOTHES, registry, dist, ocr_text="STARBUCKS COFFEE")
    assert by_text.basis == fc.BASIS_OCR and by_text.strongest.basis == fc.BASIS_OCR
    assert by_text.strongest.path == "같음" and by_text.floor == "위험"
    missed = _check(None, None, registry, dist, ocr_text="스타벅수", thresholds=weak)
    assert missed.strongest is None  # 이미지 속 글자는 소리·철자로 견주지 않는다
    assert _check("", None, registry, dist).matches == ()
    named = _check("스타벅수", None, registry, dist, ocr_text="STARBUCKS", thresholds=weak)
    assert named.basis == fc.BASIS_NAME and named.strongest.path == "소리"  # 이름이 있으면 이름으로


def test_thresholds_round_trip():
    thresholds = fc.Thresholds(strong_spelling=0.95, weak_sound={"김": 0.9},
                               weak_spelling={"중간": 0.85}, contain_other=False)
    again = fc.Thresholds.from_dict(json.loads(json.dumps(thresholds.to_dict())))
    assert again.strong_sound == 0.98 and again.strong_spelling == 0.95
    assert again.weak_sound == {"짧음": None, "중간": None, "김": 0.9}
    assert again.weak_spelling["중간"] == 0.85 and again.contain_other is False


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


def test_shipped_registry_follows_the_brand_table():
    registry = fc.load_registry()
    rows = fc.read_brand_table()
    assert [b.name for b in registry.brands] == [row["notations"][0] for row in rows]
    for brand, row in zip(registry.brands, rows):
        assert [n.text for n in brand.notations] == row["notations"]  # 표기는 표에 있는 그대로
        assert list(brand.applicants) == row["applicants"] and brand.preset == row["preset"]
        assert brand.protection in fc.PROTECTIONS and brand.goods_codes
        for notation in brand.notations:
            assert notation.key == fc.text_key(notation.text)
            assert notation.length == fc.length_class(notation.key)
            assert notation.script == fc.script_label(notation.key)
        for mark in brand.marks:
            assert mark.role in (*fc.AUTO_ROLES, *fc.OVERRIDE_ROLES)
    assert len({m.appno for b in registry.brands for m in b.marks}) == sum(
        len(b.marks) for b in registry.brands)  # 한 표장은 한 브랜드에만


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
    marks = {m.appno: (b, m) for b in registry.brands for m in b.marks}
    for record in plan["records"]:  # 수집 계획의 표장은 그 브랜드에, 이름 여부도 수집 때와 같게
        brand, mark = marks[str(record["출원번호"])]
        assert brand.name == record["브랜드"] and mark.source == fc.SOURCE_FAMOUS
        assert (mark.auto_role == fc.ROLE_NAME) == bool(record["브랜드명_포함"])
    for appno, (brand, mark) in marks.items():
        record = records[appno]
        assert mark.codes == fc.normalize_codes(record.get("유사군") or ())
        assert mark.image == record.get("이미지파일")
        if mark.source == fc.SOURCE_EXISTING:  # 같은 출원인의 기존 수집 표장
            assert record.get("수집_출처") != "유명 브랜드"
