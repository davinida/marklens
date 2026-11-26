"""유명 상표 확인의 런타임(src.famous_runtime — 통합 모델 설계 §7-14-13).

기동 때의 해시 대조, 유사군 코드에서 류 정하기, 로고 판정, 질의 하나의 확인(이름·이미지 속 글자·
로고를 합치기)과 맞은 글자. 판정 규칙(src.famous_check)은 확정된 것 — 여기서는 감싼 쪽이 그 판정을
그대로 전하는지만 본다.
"""

from __future__ import annotations

import json
import shutil
from types import SimpleNamespace

import numpy as np
import pytest
from src import famous_check as fc
from src import famous_runtime as fr
from src.axes import distinctiveness as dx
from src.model import risk_model as rm

STARBUCKS = "스타벅스"


def _goods():
    """작은 변환표와 업종 세트(시험용) — 표의 꼴만 실제와 같다."""
    entries = [
        SimpleNamespace(nice_class=25, similarity_codes=("G4503",)),
        SimpleNamespace(nice_class=25, similarity_codes=("G430301",)),
        SimpleNamespace(nice_class=9, similarity_codes=("G430301",)),
        SimpleNamespace(nice_class=9, similarity_codes=("G430301",)),
        SimpleNamespace(nice_class=35, similarity_codes=("S2045",)),
        SimpleNamespace(nice_class=42, similarity_codes=("G390802",)),
        SimpleNamespace(nice_class=9, similarity_codes=("G390802",)),
    ]
    presets = SimpleNamespace(presets=[
        SimpleNamespace(id="clothing", goods=[
            SimpleNamespace(nice_class=25, similarity_codes=("G4503", "G430301")),
            SimpleNamespace(nice_class=35, similarity_codes=("S2045",))]),
        SimpleNamespace(id="software", goods=[
            SimpleNamespace(nice_class=42, similarity_codes=("G390802",))]),
    ])
    return SimpleNamespace(entries=entries), presets


@pytest.fixture(scope="module")
def runtime() -> fr.Runtime:
    """저장소의 확정 파일·등록부·대표 로고 구분으로 만든 런타임(업종 표만 시험용)."""
    goods_map, presets = _goods()
    config = rm.famous_check_config(rm.load_model(rm.V147_MODEL_PATH))
    return fr.load_runtime(config, dist=dx.load_distinctiveness(), goods_map=goods_map,
                           presets=presets)


def _with_logos(runtime: fr.Runtime, brands: tuple[str, ...], *, kinds=None, photos=None,
                risk_from: float = 0.9) -> tuple[fr.Runtime, np.ndarray]:
    """브랜드마다 대표 로고 하나씩을 서로 수직인 벡터로 둔 로고 색인(이미지만 판단은 유사도
    risk_from 이상이면 위험이라고 둔다)."""
    marks = []
    for position, name in enumerate(brands):
        mark = runtime.registry.brand(name).logo_marks[0]
        marks.append((name, mark, position))
    matrix = np.eye(len(marks), 8, dtype=np.float32)

    def grade_of(x2: float, level: str) -> str:
        return fc.GRADE_RISK if level != "문자" and x2 >= risk_from else fc.GRADE_REVIEW

    logos = fr.LogoIndex(marks, matrix, grade_of, kinds=kinds or ["도형 위주"] * len(marks),
                         photos=photos or [False] * len(marks))
    table = fr.brand_logo_table(runtime.registry, lambda appno: True)
    return fr.with_engine(runtime, logos=logos, brand_logos=table), matrix


# ---- 파일·해시 ---------------------------------------------------------------------------------

def test_hash_ignores_line_endings(tmp_path):
    unix, windows = tmp_path / "a.json", tmp_path / "b.json"
    unix.write_bytes(b'{\n "a": 1\n}\n')
    windows.write_bytes(b'{\r\n "a": 1\r\n}\r\n')
    assert fr.file_sha256(unix) == fr.file_sha256(windows)


def test_shipped_files_load_and_agree(runtime):
    """저장소의 계수 JSON(v1.4.7)이 가리키는 확정 파일, 확정 파일이 가리키는 등록부, 대표 로고
    구분 파일이 서로 맞는다."""
    confirmed = json.loads(fr.CONFIRMED_PATH.read_text(encoding="utf-8"))
    assert runtime.confirmed_sha256 == fr.file_sha256(fr.CONFIRMED_PATH)
    assert runtime.registry_sha256 == confirmed["등록부"]["sha256"]
    assert runtime.brand_count == confirmed["등록부"]["브랜드"] == len(runtime.registry.brands)
    assert runtime.thresholds.to_dict() == confirmed["규칙"]["기준"]
    assert runtime.thresholds.weak_mode == confirmed["규칙"]["약한_일치_조건"]
    assert runtime.goods_floor == confirmed["규칙"]["결합_하한"]
    # 대표 로고 구분 — 등록부의 대표 로고(이미지가 있는 것) 전부에 구분이 있다
    logos = {mark.appno for brand in runtime.registry.brands for mark in brand.logo_marks
             if mark.image_exists}
    assert set(runtime.logo_kinds) == logos
    assert set(runtime.logo_kinds.values()) <= set(fr.KIND_NAMES.values()) | {fr.KIND_UNKNOWN}
    # 등록부의 표장 → 브랜드("관련 없음"과 함께 걸린 표장은 없다)
    for brand in runtime.registry.brands:
        for mark in brand.marks:
            listed = runtime.brand_of_mark.get(mark.appno)
            if mark.role == fc.ROLE_UNRELATED or mark.shared:
                assert listed != brand.name or any(
                    other.appno == mark.appno and other.role != fc.ROLE_UNRELATED
                    and not other.shared for other in brand.marks)
            else:
                assert listed is not None


def test_load_refuses_missing_broken_or_mismatched_files(tmp_path):
    goods_map, presets = _goods()
    dist = dx.load_distinctiveness()
    config = rm.famous_check_config(rm.load_model(rm.V147_MODEL_PATH))

    def load(**paths):
        return fr.load_runtime(config, dist=dist, goods_map=goods_map, presets=presets, **paths)

    def copy(source, name):
        target = tmp_path / name
        shutil.copyfile(source, target)
        return target

    assert load().brand_count > 0
    # 없는 파일
    for key in ("registry_path", "confirmed_path", "logo_kinds_path"):
        with pytest.raises(fr.FamousUnavailable):
            load(**{key: tmp_path / "없음.json"})
    # 깨진 파일
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    for key in ("confirmed_path", "logo_kinds_path"):
        with pytest.raises(fr.FamousUnavailable):
            load(**{key: broken})
    # 등록부가 확정 파일에 적힌 것과 다름(한 글자)
    registry = copy(fc.DEFAULT_REGISTRY_PATH, "registry.json")
    registry.write_text(registry.read_text(encoding="utf-8").replace("스타벅스", "스타벅수", 1),
                        encoding="utf-8")
    with pytest.raises(fr.FamousUnavailable, match="등록부의 해시"):
        load(registry_path=registry)
    # 확정 파일이 계수 JSON 에 적힌 것과 다름
    confirmed = copy(fr.CONFIRMED_PATH, "confirmed.json")
    confirmed.write_text(confirmed.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(fr.FamousUnavailable, match="확정 파일의 해시"):
        load(confirmed_path=confirmed)
    with pytest.raises(fr.FamousUnavailable, match="확정 파일의 해시"):
        fr.load_runtime({**config, "confirmed_sha256": "0" * 64}, dist=dist,
                        goods_map=goods_map, presets=presets)
    # 대표 로고 구분 파일이 다른 등록부의 것
    kinds = json.loads(fr.LOGO_KINDS_PATH.read_text(encoding="utf-8"))
    stale = tmp_path / "kinds.json"
    stale.write_text(json.dumps({**kinds, "registry_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(fr.FamousUnavailable, match="등록부의 것이 아님"):
        load(logo_kinds_path=stale)
    # 이유 글에 경로가 없다(응답·상태 코드에 쓰지 않지만 로그에도 길게 남기지 않는다)
    with pytest.raises(fr.FamousUnavailable) as caught:
        load(registry_path=tmp_path / "없음.json")
    assert str(tmp_path) not in str(caught.value)


def test_paths_can_be_set_by_environment(tmp_path, monkeypatch):
    goods_map, presets = _goods()
    monkeypatch.setenv(fr.ENV_REGISTRY, str(tmp_path / "없음.json"))
    with pytest.raises(fr.FamousUnavailable, match="등록부 없음"):
        fr.load_runtime(None, dist=None, goods_map=goods_map, presets=presets)


# ---- 질의의 류 ---------------------------------------------------------------------------------

def test_classes_from_codes_is_the_measured_proposal():
    """세트의 코드와 같으면 그 세트의 류, 아니면 코드별 대표 류 — 측정 스크립트와 같은 함수."""
    from scripts import famous_check_confirm as cf

    assert cf.classes_from_codes is fr.classes_from_codes
    assert cf.representative_classes is fr.representative_classes
    goods_map, presets = _goods()
    representative = fr.representative_classes(goods_map)
    assert representative == {"G4503": 25, "G430301": 9, "S2045": 35, "G390802": 9}
    codes_of, classes_of = fr.preset_tables(presets)
    assert codes_of == {"clothing": ["G430301", "G4503", "S2045"], "software": ["G390802"]}
    assert classes_of == {"clothing": [25, 35], "software": [42]}

    def classes(codes):
        return fr.classes_from_codes(codes, codes_of, classes_of, representative)

    assert classes(["S2045", "G4503", "g430301 "]) == ([25, 35], "업종 세트(clothing)")
    assert classes(["G390802"]) == ([42], "업종 세트(software)")
    assert classes(["G4503", "S2045"]) == ([25, 35], "코드별 대표 류")
    assert classes(["G430301", "X9999"]) == ([9], "코드별 대표 류")
    assert classes([]) == ([], "코드별 대표 류")


def test_check_passes_the_derived_classes(runtime):
    outcome = fr.check(runtime, name="아무이름", goods={"G430301", "G4503", "S2045"})
    assert outcome.classes == (25, 35) and outcome.classes_basis == "업종 세트(clothing)"
    outcome = fr.check(runtime, name="아무이름", goods=["G4503"])
    assert outcome.classes == (25,) and outcome.classes_basis == "코드별 대표 류"
    assert fr.check(runtime, name="아무이름").classes is None


# ---- 구분 --------------------------------------------------------------------------------------

def test_kind_names():
    assert fr.kind_name("문자") == "글자 위주" == fc.LOGO_KIND_TEXT
    assert fr.kind_name("결합") == "결합" and fr.kind_name("도형") == "도형 위주"
    assert fr.kind_name(None) == fr.kind_name("?") == fr.KIND_UNKNOWN
    assert fr.kind_from_ratios(0.4, 0.01) == "글자 위주"  # 글자를 지우면 남는 것이 없다
    assert fr.kind_from_ratios(0.0, 0.5) == "도형 위주"
    assert fr.kind_from_ratios(0.3, 0.4) == "결합"
    assert fr.kind_from_ratios(None, 0.4) is None and fr.kind_from_ratios(0.3, None) is None
    assert fr.kind_from_type("문자") == "글자 위주" and fr.kind_from_type("도형") == "도형 위주"
    assert fr.kind_from_type("결합-문자요부") == fr.kind_from_type("결합-도형요부") == "결합"
    assert fr.kind_from_type(None) is None


# ---- 로고 --------------------------------------------------------------------------------------

def test_logo_index_risk_threshold_and_rule(runtime):
    with_logos, matrix = _with_logos(runtime, (STARBUCKS, "샤넬", "나이키"),
                                     kinds=["글자 위주", "도형 위주", "글자 위주"],
                                     photos=[False, False, True], risk_from=0.8958)
    logos = with_logos.logos
    assert logos.risk_min("도형") == 0.8958 and logos.is_risk(0.8958) and not logos.is_risk(0.8957)
    assert logos.risk_min("문자") == 2.0 and not logos.is_risk(1.0, "문자")  # 위험에 닿지 않는 유형

    def near(index: int, value: float) -> np.ndarray:
        """index 번째 로고와 유사도 value 인 단위 벡터."""
        other = np.zeros(8, dtype=np.float32)
        other[7] = 1.0
        return (value * matrix[index] + (1.0 - value**2) ** 0.5 * other).astype(np.float32)

    # 도형 위주 로고 — 이미지만 판단이 위험이면 강함
    assert set(logos.strong(near(1, 0.95))) == {"샤넬"}
    assert logos.strong(near(1, 0.85)) == {}
    hit = logos.strong(near(1, 0.95))["샤넬"]
    assert hit["유사도"] == 0.95 and hit["표장"] == logos.marks[1][1].appno
    # 글자 위주끼리는 0.98 이상일 때만
    assert logos.strong(near(0, 0.95), query_kind="글자 위주") == {}
    assert set(logos.strong(near(0, 0.985), query_kind="글자 위주")) == {STARBUCKS}
    assert set(logos.strong(near(0, 0.95), query_kind="도형 위주")) == {STARBUCKS}
    assert set(logos.strong(near(0, 0.95))) == {STARBUCKS}  # 질의의 구분을 모르면 글자 규칙 없음
    assert set(logos.strong(near(0, 0.95), query_kind="글자 위주", rule=False)) == {STARBUCKS}
    # 사진으로 판정된 대표 로고는 보지 않는다, 뺄 표장, 위험에 닿지 않는 유형
    assert logos.strong(near(2, 1.0)) == {}
    assert logos.strong(near(1, 1.0), exclude=logos.marks[1][1].appno) == {}
    assert logos.strong(near(1, 1.0), level="문자") == {}


def test_logo_entries_skip_marks_missing_from_the_index(runtime):
    marks = [mark for brand in runtime.registry.brands for mark in brand.logo_marks]
    by_appno = {mark.appno: SimpleNamespace(pos=index) for index, mark in enumerate(marks)}
    found, skipped = fr.LogoIndex.entries(runtime.registry, by_appno)
    assert len(found) == len(marks) and skipped == 0
    by_appno[marks[0].appno] = SimpleNamespace(pos=None)  # 색인에 없음
    del by_appno[marks[1].appno]  # DB 에 없음
    found, skipped = fr.LogoIndex.entries(runtime.registry, by_appno)
    assert len(found) == len(marks) - 2 and skipped == 2
    embeddings = np.eye(len(marks), dtype=np.float32)
    index, stats = fr.build_logo_index(runtime.registry, by_appno, embeddings,
                                       lambda x2, level: fc.GRADE_RISK, runtime.logo_kinds,
                                       photo_of=lambda row: False)
    assert stats == {"등록부의_대표_로고": len(marks), "쓰는_것": len(marks) - 2,
                     "색인에_없음": 2, "구분_없음": 0}
    assert len(index.marks) == len(index.kinds) == len(index.photos) == len(marks) - 2
    # 구분이 적히지 않은 표장은 쓰지 않는다
    partial = {appno: kind for appno, kind in list(runtime.logo_kinds.items())[5:]}
    _, stats = fr.build_logo_index(runtime.registry, by_appno, embeddings,
                                   lambda x2, level: fc.GRADE_RISK, partial)
    assert stats["구분_없음"] > 0 and stats["쓰는_것"] == len(marks) - 2 - stats["구분_없음"]


def test_brand_logos_put_current_logos_first(runtime):
    table = fr.brand_logo_table(runtime.registry, lambda appno: True)
    for brand in runtime.registry.brands:
        roles = [next(m.role for m in brand.logo_marks if m.appno == appno)
                 for appno in table[brand.name]]
        assert roles == sorted(roles, key=fc.LOGO_ROLES.index)
        assert len(table[brand.name]) == len(brand.logo_marks)
    none = fr.brand_logo_table(runtime.registry, lambda appno: False)
    assert all(appnos == () for appnos in none.values())


# ---- 질의 하나의 확인 --------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["스타벅스", "스타벅수", "뉴스타벅스", "STARBUCKS COFFEE",
                                  "텍사스 BBQ", "당근 마켓", "파리 바게뜨", "블루커피",
                                  "네이버후드", "like", "샤넬 구글"])
def test_check_gives_the_modules_judgement(runtime, name):
    """감싼 쪽의 판정 = 판정 모듈(fc.check_famous)의 판정 — 브랜드·수준·경로·표기·바닥과 순서."""
    outcome = fr.check(runtime, name=name)
    direct = fc.check_famous(name, None, runtime.registry, runtime.thresholds, dist=runtime.dist,
                             goods_floor=runtime.goods_floor)
    assert outcome.result == direct and outcome.floor == direct.floor
    assert outcome.brands == len(direct.matches)
    assert [(m.brand, m.path, m.notation, m.floor, m.protection, m.overlap)
            for m in outcome.matches] == [
        (m.brand, m.path, m.notation, m.floor, m.protection, m.overlap)
        for m in direct.matches[:fr.MAX_MATCHES]]
    assert [m.level for m in outcome.matches] == [
        fr.LEVEL_NAMES[m.level] for m in direct.matches[:fr.MAX_MATCHES]]
    assert all(m.basis == fr.BASIS_NAME for m in outcome.matches)


def test_check_reports_the_matched_text(runtime):
    def first(name, **kwargs):
        return fr.check(runtime, name=name, **kwargs).matches[0]

    exact = first("스타벅스")
    assert exact.matched_text == "스타벅스" and exact.notation == "스타벅스"
    weak = first("스타벅수")
    assert (weak.level, weak.matched_text, weak.notation) == ("약함", "스타벅수", "스타벅스")
    assert first("파리 바게뜨").matched_text == "파리 바게뜨"  # 띄어 쓴 그대로
    assert first("STARBUCKS Coffee").matched_text in ("STARBUCKS", "STARBUCKS Coffee")
    notice = first("텍사스 BBQ")
    assert (notice.level, notice.matched_text, notice.floor) == ("설명적 사용", "BBQ", None)
    assert fr.original_span("L'OREAL paris", "loreal") == "L'OREAL"
    assert fr.original_span("ＳＴＡＲ 벅스", "star") == "ＳＴＡＲ"  # 전각 문자도 원래 글자로
    assert fr.original_span("스타벅스", "없는말") == "없는말"
    assert fr.original_span("x", None) is None


def test_check_uses_image_text_only_without_a_name(runtime):
    seen = fr.check(runtime, ocr_text="STARBUCKS COFFEE")
    assert seen.matches and seen.matches[0].basis == fr.BASIS_OCR
    assert seen.matches[0].brand == STARBUCKS and seen.matches[0].level == "강함"
    assert seen.result == fc.check_famous(
        None, None, runtime.registry, runtime.thresholds, dist=runtime.dist,
        goods_floor=runtime.goods_floor, ocr_text="STARBUCKS COFFEE")
    # 이미지 속 글자로는 같음·품음-설명(강함)만 — 소리로 닮은 글자는 일치가 아니다
    assert fr.check(runtime, ocr_text="스타벅수").matches == ()
    # 이름이 있으면 이름으로만 본다
    named = fr.check(runtime, name="블루커피", ocr_text="STARBUCKS")
    assert named.matches == () and named.result.basis == fc.BASIS_NAME
    assert fr.check(runtime).matches == () and fr.check(runtime).result is None


def test_check_merges_logo_matches(runtime):
    with_logos, matrix = _with_logos(runtime, (STARBUCKS, "샤넬"))
    mark = with_logos.logos.marks[0][1].appno
    # 로고만 — 강함, 바닥은 위험, 맞은 표장이 대표 로고의 맨 앞
    logo = fr.check(with_logos, name="몬테로사", embedding=matrix[0])
    assert [(m.brand, m.level, m.basis, m.floor) for m in logo.matches] == [
        (STARBUCKS, "강함", fr.BASIS_LOGO, fc.GRADE_RISK)]
    only = logo.matches[0]
    assert only.notation is None and only.matched_text is None and only.overlap is None
    assert only.mark == mark and only.logos[0] == mark and len(only.logos) <= fr.MAX_LOGOS
    assert only.protection == runtime.registry.brand(STARBUCKS).protection
    assert logo.floor == fc.GRADE_RISK and set(logo.logo_hits) == {STARBUCKS}
    # 같은 브랜드의 이름 일치가 강함이면 이름이 앞(한 브랜드는 한 줄)
    both = fr.check(with_logos, name="스타벅스", embedding=matrix[0])
    assert [(m.brand, m.basis) for m in both.matches] == [(STARBUCKS, fr.BASIS_NAME)]
    # 이름이 약함이고 로고가 강함이면 로고가 그 브랜드의 줄이 된다 — 바닥도 위험
    weak = fr.check(with_logos, name="스타벅수", embedding=matrix[0])
    assert [(m.brand, m.basis, m.level) for m in weak.matches] == [
        (STARBUCKS, fr.BASIS_LOGO, "강함")]
    assert weak.floor == fc.GRADE_RISK
    # 다른 브랜드의 이름 강함과 로고 강함 — 이름이 먼저, 둘 다 싣는다
    mixed = fr.check(with_logos, name="구글", embedding=matrix[1])
    assert [(m.brand, m.basis) for m in mixed.matches] == [
        ("구글", fr.BASIS_NAME), ("샤넬", fr.BASIS_LOGO)]
    # 사진으로 판정된 질의·로고 색인이 없는 런타임은 로고를 보지 않는다
    photo = fr.check(with_logos, name="몬테로사", embedding=matrix[0], query_photo=True)
    assert photo.matches == () and photo.logo_hits == {}
    assert fr.check(runtime, name="몬테로사", embedding=matrix[0]).matches == ()
    # 이미지만 판단에 쓰는 유형이 위험에 닿지 않으면(문자로 고친 질의) 일치가 없다
    assert fr.check(with_logos, name="몬테로사", embedding=matrix[0], level="문자").matches == ()


def test_check_keeps_two_brands_and_the_highest_floor(runtime):
    outcome = fr.check(runtime, name="스타벅스 샤넬 구글")
    assert outcome.brands == 3 and len(outcome.matches) == fr.MAX_MATCHES
    assert outcome.floor == fc.GRADE_RISK
    assert [m.brand for m in outcome.matches] == [m.brand for m in outcome.result.matches[:2]]
    assert fr.check(runtime, name="블루커피").floor is None
    weak = fr.check(runtime, name="스타벅수")
    assert weak.floor == fc.GRADE_REVIEW and weak.matches[0].floor == fc.GRADE_REVIEW
