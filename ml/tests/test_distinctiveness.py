"""식별력·요부 v0 테스트 — 가짜 통계·작은 변환표·임시 파일만(네트워크·실데이터 없음)."""

from __future__ import annotations

import csv
import json

import pytest
from src.axes import distinctiveness as dx
from src.axes.goods_map import GoodsEntry, GoodsMap
from src.axes.x1_phonetic import phonetic_similarity
from src.axes.x2_ortho import orthographic_similarity

from scripts import distinctiveness_build as build

GOODS = GoodsMap([
    GoodsEntry("커피", 30, ("G0301",)),
    GoodsEntry("원두", 30, ("G0305",)),
    GoodsEntry("화장품", 3, ("G1201",)),
    GoodsEntry("커피 음료", 32, ("G0302",)),
    GoodsEntry("신발", 25, ("G2701",), aliases=("구두류",)),
])
STATS = {
    "dream": (44, 48), "gate": (6, 12), "series": (8, 14), "zorbix": (0, 0), "qwzx": (10, 20),
    "qwzy": (5, 10), "삼성": (100, 200),
}


def _model(descriptive=None) -> dx.Distinctiveness:
    names, classes = dx.goods_index(GOODS)
    return dx.Distinctiveness(STATS, famous={"삼성", "starbucks", "스타벅스"}, goods_names=names,
                              code_classes=classes, descriptive=descriptive)


@pytest.fixture
def model():
    return _model(descriptive={})  # 실제 descriptive_terms.json 과 분리(3호는 전용 테스트에서)


def test_goods_index_single_token_names_and_aliases():
    names, classes = dx.goods_index(GOODS)
    assert set(names) == {"커피", "원두", "화장품", "신발", "구두류"}  # "커피 음료"(2토큰)는 제외
    assert names["커피"] == ((30, frozenset({"G0301"})),)
    assert classes == {"G0301": frozenset({30}), "G0305": frozenset({30}), "G1201": frozenset({3}),
                       "G0302": frozenset({32}), "G2701": frozenset({25})}


def test_generic_name_is_goods_relative(model):
    assert model.judge("커피", {"G0301"}).reasons == ("1호 보통명칭",)  # 같은 유사군
    assert model.judge("커피", {"G0305"}).reasons == ("1호 보통명칭",)  # 같은 류(30)의 다른 유사군
    assert model.judge("커피", None).reasons == ("1호 보통명칭(전역)",)
    cosmetics = model.judge("커피", {"G1201"})  # 화장품 유사군이면 보통명칭이 아니다 → 일반어 점수
    assert cosmetics.score > 0.5 and cosmetics.reasons[0].startswith("일반어")
    assert model.judge("커피", {"G0302"}).score > 0  # 32류 커피 음료와는 류·유사군 모두 다르다
    assert model.token_score("구두류", {"G2701"}) == 0.0  # 별칭도 고시 명칭


@pytest.mark.parametrize("token", ["서울", "강남구", "제주도", "busan", "파리", "paris", "해운대"])
def test_place_names_are_zero(model, token):
    assert model.judge(token).reasons == ("4호 지명",) and model.token_score(token) == 0.0


def test_place_suffix_requires_known_base(model):
    assert not dx.is_place("서울우유") and not dx.is_place("강남스타일")
    assert dx.is_place("수원시") and not dx.is_place("수시")


@pytest.mark.parametrize("token", ["김가네", "박네", "최씨네", "kim", "lee"])
def test_common_surnames_are_zero(model, token):
    assert "5호 흔한 성" in model.judge(token).reasons and model.token_score(token) == 0.0


def test_surname_only_matches_listed_patterns():
    assert not dx.is_common_surname("김치") and not dx.is_common_surname("moon")
    assert dx.is_common_surname("김") and dx.is_common_surname("정가네")


@pytest.mark.parametrize("token,simple", [
    ("k", True), ("ab", True), ("24", True), ("한", True), ("abc", False), ("365", False),
    ("한국", False),
])
def test_simple_marks(token, simple):
    assert dx.is_simple_mark(token) is simple


def test_descriptive_terms_score_rules(monkeypatch):
    """3호: 절대 → 0 / classes 와 지정상품의 류가 겹치면 0 / 류 불일치면 영향 없음 / 상품 미상·류
    미지정은 0.5 상한."""
    model = _model(descriptive=None)  # 모듈 상수 DESCRIPTIVE_TERMS 를 본다(monkeypatch 대상)
    monkeypatch.setattr(dx, "DESCRIPTIVE_TERMS", {
        "best": dx.DescriptiveTerm("품질", absolute=True, note="판례 예시"),
        "zorbix": dx.DescriptiveTerm("원재료", classes=frozenset({30, 32})),
        "plumtaro": dx.DescriptiveTerm("용도"),  # 류 미지정
    })
    assert model.judge("best").reasons == ("3호 기술적 표장(절대):품질",)
    assert model.token_score("best", {"G1201"}) == 0.0 and model.token_score("best") == 0.0
    assert model.judge("zorbix", {"G0301"}).reasons == ("3호 기술적 표장:원재료(류 30)",)
    assert model.token_score("zorbix", {"G0301"}) == 0.0
    assert model.judge("zorbix", {"G1201"}) == dx.TokenJudgement("zorbix", 1.0, ("조어",))  # 3류
    unknown = model.judge("zorbix")  # 상품 미상
    assert unknown.score == 0.5 and unknown.reasons == ("3호 기술적 표장(상품 미상):원재료",)
    assert model.judge("plumtaro", {"G0301"}).reasons == ("3호 기술적 표장(류 미지정):용도",)
    assert model.token_score("plumtaro", {"G0301"}) == 0.5
    # 상한은 다른 요소보다 낮을 때만 작용한다(dream 은 이미 0)
    monkeypatch.setattr(dx, "DESCRIPTIVE_TERMS", {"dream": dx.DescriptiveTerm("효능")})
    assert model.judge("dream").score == 0.0 and "3호" not in " ".join(model.judge("dream").reasons)
    explicit = dx.Distinctiveness({}, descriptive={"수제": dx.DescriptiveTerm("생산방법", True)})
    assert explicit.judge("수제").reasons == ("3호 기술적 표장(절대):생산방법",)
    assert explicit.salient_tokens("수제 Zorbix") == [("zorbix", 1.0)]


def test_descriptive_terms_loader_validates(tmp_path, monkeypatch):
    good = {"meta": {"v": 1}, "terms": {
        "best": {"kind": "품질", "absolute": True, "classes": None, "note": "n", "approved": True},
        "천연": {"kind": "원재료", "absolute": False, "classes": [3, 5], "note": "",
               "approved": False},
    }}
    terms = dx.validate_descriptive_terms(good)
    assert terms["best"] == dx.DescriptiveTerm("품질", True, None, "n", True)
    assert terms["천연"].classes == frozenset({3, 5}) and not terms["천연"].approved
    assert dx.unapproved_terms(terms) == ["천연"]
    for bad in (
        {"terms": {"Best": {"kind": "품질", "absolute": True}}},  # 정규화 형태 아님(대문자)
        {"terms": {"천연 비누": {"kind": "원재료", "absolute": False}}},  # 두 토큰
        {"terms": {"best": {"kind": "최상", "absolute": True}}},  # kind 허용값 밖
        {"terms": {"best": {"absolute": True}}},  # kind 없음
        {"terms": {"best": {"kind": "품질", "absolute": "yes"}}},
        {"terms": {"best": {"kind": "품질", "absolute": False, "classes": [0, 3]}}},
        {"terms": {"best": {"kind": "품질", "absolute": False, "classes": "3"}}},
        {"terms": {"best": {"kind": "품질", "absolute": True, "approved": "true"}}},
        {"terms": "x"},
    ):
        with pytest.raises(ValueError):
            dx.validate_descriptive_terms(bad)
    path = tmp_path / "descriptive_terms.json"
    path.write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
    assert set(dx.read_descriptive_terms(path)) == {"best", "천연"}
    assert dx.read_descriptive_terms(tmp_path / "missing.json") == {}
    monkeypatch.setenv(dx.ENV_DESCRIPTIVE_PATH, str(path))
    assert dx.resolve_descriptive_path() == path
    monkeypatch.delenv(dx.ENV_DESCRIPTIVE_PATH)
    assert dx.resolve_descriptive_path() == dx.DEFAULT_DESCRIPTIVE_PATH


def test_registration_factor_and_thresholds(model):
    assert dx.registration_factor(0, 0) == 1.0
    assert dx.registration_factor(10, 20) == 0.0 and dx.registration_factor(5, 10) == 0.75
    assert dx.registration_factor(5, 10, theta_a=5, theta_n=10) == 0.0
    assert model.token_score("qwzx") == 0.0  # 조어라도 A=10·N=20 이면 0
    assert model.judge("qwzx").reasons == ("다수 등록(A=10, N=20)",)
    assert model.token_score("qwzy") == 0.75 and model.token_score("zorbix") == 1.0
    assert model.judge("zorbix").reasons == ("조어",)
    strict = dx.Distinctiveness(STATS, theta_a=5, theta_n=10)
    assert strict.token_score("qwzy") == 0.0


def test_intrinsic_floor_and_common_word_combined(model):
    score, zipf = dx.intrinsic_score("house")
    assert zipf > dx.ZIPF_HIGH and score == dx.INTRINSIC_FLOOR  # 아주 흔한 일반어는 0.5 하한
    assert dx.intrinsic_score("zorbix") == (1.0, 0.0)
    assert model.judge("dream").score == 0.0  # 일반어 × 다수 등록(44, 48)
    gate = model.judge("gate")
    assert 0.0 < gate.score < dx.THETA and gate.reasons[1] == "다수 등록(A=6, N=12)"
    assert model.judge("series").score == pytest.approx(
        dx.intrinsic_score("series")[0] * dx.registration_factor(8, 14), abs=1e-4
    )


def test_famous_brands_override_everything(model):
    assert model.judge("삼성").score == 1.0 and model.judge("삼성").reasons == ("유명 브랜드",)
    assert model.token_score("starbucks") == 1.0 and model.token_score("STARBUCKS") == 1.0
    famous = dx.famous_tokens()
    assert {"samsung", "삼성", "나이키", "스타벅스", "카카오", "네이버", "코카콜라"} <= famous
    assert "더" not in famous and "가부시키가이샤" not in famous
    assert dx.famous_tokens(None) == frozenset(dx.KOREAN_BRAND_ROMANIZATION) | frozenset(
        dx.KOREAN_BRAND_ROMANIZATION.values()
    )


def test_salient_tokens_and_whole_comparison_rule(model):
    assert model.salient_tokens("Zorbix Gate") == [("zorbix", 1.0)]
    assert model.weak_tokens("Zorbix Gate") == frozenset({"gate"})
    assert model.has_distinctive_part("Zorbix Gate")
    assert model.salient_tokens("GATE") == [] and not model.has_distinctive_part("GATE")
    assert model.salient_tokens("") == [] and not model.has_distinctive_part(None)
    # 2000후2453: 요부가 없는 이름(GATE)의 토큰은 넘기지 않고, 상대 이름의 약한 토큰만 넘긴다
    assert model.pair_generic("Zorbix Gate", "GATE") == frozenset({"gate"})
    assert model.pair_generic("GATE", "GATE") == frozenset()
    assert model.pair_generic("Dream Zorbix", "Gate Zorbix") == frozenset({"dream", "gate"})
    # 요부가 없는 "Gate Qwzx" 는 토큰을 넘기지 않는다
    assert model.pair_generic("Dream Zorbix", "Gate Qwzx") == frozenset({"dream"})
    # 상품 상대적: 커피 유사군이면 커피가 약해 요부는 Zorbix, 화장품이면 둘 다 요부
    assert model.salient_tokens("Zorbix 커피", {"G0301"}) == [("zorbix", 1.0)]
    assert [t for t, _ in model.salient_tokens("Zorbix 커피", {"G1201"})] == ["zorbix", "커피"]


def _model_with_weak(*tokens: str) -> dx.Distinctiveness:
    """픽스처 통계에 다수 등록 토큰을 더한 모델(A·N 이 포화점이라 점수 0 → 약한 토큰)."""
    names, classes = dx.goods_index(GOODS)
    stats = {**STATS, **{token: (20, 40) for token in tokens}}
    return dx.Distinctiveness(stats, famous={"삼성"}, goods_names=names, code_classes=classes,
                              descriptive={})


def test_combined_weak_run_keeps_cool_touch_whole():
    # v0.2 결합 규칙(2015후1690 결합상태): 약한 토큰 2개가 같은 순서로 양쪽에 있으면 그 결합은
    # 요부 후보 — pair_generic 이 넘기지 않아 Cool Touch / 쿨터치 COOL TOUCH 는 전체로 대비(1.0)
    model = _model_with_weak("cool", "touch")
    assert model.weak_tokens("쿨터치 COOL TOUCH") == frozenset({"cool", "touch"})
    assert model.combined_weak_run("Cool Touch", "쿨터치 COOL TOUCH") == ("cool", "touch")
    generic = model.pair_generic("Cool Touch", "쿨터치 COOL TOUCH")
    assert generic == frozenset()
    assert phonetic_similarity("Cool Touch", "쿨터치 COOL TOUCH", extra_generic=generic) == 1.0
    # 결합에 들지 않은 약한 토큰(mp)은 여전히 넘긴다
    model = _model_with_weak("q", "fire", "mp")
    assert model.combined_weak_run("Q-FIRE", "Q-FIRE 500MP") == ("q", "fire")
    assert model.pair_generic("Q-FIRE", "Q-FIRE 500MP") == frozenset({"mp"})


def test_combined_weak_run_ignores_single_shared_token(model):
    # 공통 약한 토큰이 하나뿐이면 결합이 아니다 — gate 는 그대로 넘긴다(v0·v1.6 과 같음)
    assert model.combined_weak_run("Zorbix Gate", "Hello Gate") == ()
    assert model.pair_generic("Zorbix Gate", "Hello Gate") == frozenset({"gate"})
    assert model.combined_weak_run("Zorbix Gate", "GATE") == ()
    assert model.pair_generic("Zorbix Gate", "GATE") == frozenset({"gate"})


def test_combined_weak_run_requires_same_order():
    model = _model_with_weak("cool", "touch")
    assert model.combined_weak_run("Touch Cool Zorbix", "Cool Touch Qwzy") == ()
    generic = model.pair_generic("Touch Cool Zorbix", "Cool Touch Qwzy")
    assert generic == frozenset({"cool", "touch"})
    assert phonetic_similarity("Touch Cool Zorbix", "Cool Touch Qwzy") == 1.0  # 공통 토큰 분리관찰
    assert phonetic_similarity("Touch Cool Zorbix", "Cool Touch Qwzy", extra_generic=generic) < 0.6
    # 인접하지 않아도 순서가 같으면 결합(공통 부분열)
    assert model.combined_weak_run("Cool Zorbix Touch", "Cool Touch Qwzy") == ("cool", "touch")
    assert dx._common_subsequence(["a", "b", "c"], ["b", "c", "a"]) == ("b", "c")
    assert dx._common_subsequence([], ["a"]) == ()


def test_combined_single_match_keeps_joined_pairs():
    # v0.3: 붙여쓴 결합어 대 띄어쓴 약한 토큰열 — 세 쌍 모두 pair_generic 이 비어 전체로 대비된다
    model = _model_with_weak("line", "royal", "bee", "cool", "touch", "quick", "pass")
    # 슬림라인 = 슬림 + 라인(토큰별 읽기 연결) → line 을 넘기지 않는다
    assert model.weak_tokens("Slim Line") == frozenset({"line"})
    assert model.combined_single_match("슬림라인", "Slim Line") == frozenset({"line"})
    assert model.pair_generic("슬림라인", "Slim Line") == frozenset()
    assert phonetic_similarity("슬림라인", "Slim Line", extra_generic=frozenset()) == 1.0
    # SLIMLINE: 정규화 철자 동일. QUICKPATH / QUICK PASS: 읽기 ‘퀵패스’ 동일
    assert model.combined_single_match("SLIMLINE", "Slim Line") == frozenset({"line"})
    assert model.combined_single_match("QUICKPATH", "퀵패스 QUICK PASS") == frozenset(
        {"quick", "pass"}
    )
    # ROYALEBEE / ROYAL BEE 와 쿨터치 / COOL TOUCH 는 토큰이 모두 약해 v0 규칙(2000후2453)으로 이미
    # 전체 대비 — v0.3 판정 자체는 편집거리 0.889·읽기 ‘타우치’ 라 임계 0.9 에 못 미친다
    assert model.combined_single_match("ROYALEBEE", "ROYAL BEE") == frozenset()
    assert model.pair_generic("ROYALEBEE", "ROYAL BEE") == frozenset()
    assert model.pair_generic("쿨터치", "COOL TOUCH") == frozenset()
    assert phonetic_similarity("ROYALEBEE", "ROYAL BEE", extra_generic=frozenset()) == (
        phonetic_similarity("ROYALEBEE", "ROYAL BEE")
    )
    # 결합어가 다른 토큰과 섞여 있어도(요부 있는 이름) 토큰열의 약한 토큰은 넘기지 않는다
    assert model.pair_generic("퀵패스 QUICKPATH", "Zorbix QUICK PASS") == frozenset()
    assert model.pair_generic("로얄비 ROYALEBEE", "Zorbix ROYAL BEE") == frozenset(
        {"royal", "bee"}
    )  # 0.889 — 임계 미달이면 그대로 넘긴다
    assert model.pair_generic("혹달린신발", "신광준의 혹 달린 신발") == frozenset()
    assert model.combined_single_match("혹달린신발", "신광준의 혹 달린 신발") == frozenset(
        {"혹", "신발"}
    )


def test_combined_single_match_ignores_single_weak_token(model):
    # 공통 약한 토큰 하나(gate)는 결합이 아니다 — v0·v1.6 과 같이 넘긴다
    assert model.combined_single_match("Zorbix Gate", "Hello Gate") == frozenset()
    assert model.pair_generic("Zorbix Gate", "Hello Gate") == frozenset({"gate"})
    assert model.combined_single_match("Gate Qwzy", "Zorbix Gate") == frozenset()
    assert model.pair_generic("Gate Qwzy", "Zorbix Gate") == frozenset({"gate"})


def test_combined_single_match_ignores_unrelated_pairs():
    model = _model_with_weak("cool", "touch")
    # 이어 붙인 ‘cooltouch’ 와 닮은 토큰이 상대 이름에 없으면 그대로 넘긴다
    assert model.combined_single_match("Cool Touch Zorbix", "Qwzy") == frozenset()
    assert model.pair_generic("Cool Touch Zorbix", "Qwzy") == frozenset({"cool", "touch"})
    assert model.combined_single_match("Dream Zorbix", "Gate Qwzy") == frozenset()
    assert dx._combined_match("zorbixgate", ["zorbix", "gate"])
    assert not dx._combined_match("gate", ["zorbix", "gate"])
    assert not dx._combined_match("fire", ["fire", "500", "mp"])  # 토큰 분리관찰로 잡지 않는다
    assert not dx._combined_match("에어부산", ["busan", "air"])  # 어순이 바뀌면 결합이 아니다
    assert dx._string_similarity("royalebee", "royalbee") == pytest.approx(1 - 1 / 9)
    assert dx._string_similarity("슬림라인", "슬림라인") == 1.0


def test_overrides_skip_statistics_but_not_legal_zero():
    # v0.2: 사람 검토 제외 토큰은 통계 약화만 건너뛴다 — 3호 상대어(류 일치)는 0, 류 불일치는 1.0,
    # 상품 미상이면 3호 상한 0.5
    term = dx.DescriptiveTerm("원재료", False, frozenset({3}), "", True)
    names, classes = dx.goods_index(GOODS)
    model = dx.Distinctiveness({"crystal": (20, 40)}, goods_names=names, code_classes=classes,
                               descriptive={"crystal": term}, overrides={"crystal"})
    assert model.judge("crystal", {"G1201"}) == dx.TokenJudgement(
        "crystal", 0.0, ("3호 기술적 표장:원재료(류 3)",)
    )
    assert model.judge("crystal", {"G0301"}) == dx.TokenJudgement(
        "crystal", 1.0, ("사람 검토 제외(weak_token_overrides)",)
    )
    assert model.judge("crystal", None) == dx.TokenJudgement(
        "crystal", 0.5,
        ("사람 검토 제외(weak_token_overrides)", "3호 기술적 표장(상품 미상):원재료"),
    )
    assert model.judge("서울", None).score == 0.0  # 4호 지명은 overrides 가 있어도 0
    assert dx.Distinctiveness({"서울": (20, 40)}, overrides={"서울"}).judge("서울").reasons == (
        "4호 지명",
    )


def test_axes_with_pair_generic_lower_shared_weak_token(model):
    generic = model.pair_generic("Zorbix Gate", "Hello Gate")
    assert generic == frozenset({"gate"})
    assert phonetic_similarity("Zorbix Gate", "Hello Gate") == 1.0
    assert phonetic_similarity("Zorbix Gate", "Hello Gate", extra_generic=generic) < 0.5
    assert orthographic_similarity("Zorbix Gate", "Hello Gate", extra_generic=generic) < 0.5
    # 요부가 없는 쪽(GATE)은 전체로 대비된다. 철자 축은 "zorbix" 대 "gate" 로 내려가고, X1 도
    # v1.6 부터는 약한 토큰만으로 된 "게이트" 를 포함 검사의 짧은 쪽으로 쓰지 않아 내려간다.
    generic = model.pair_generic("Zorbix Gate", "GATE")
    assert orthographic_similarity("Zorbix Gate", "GATE", extra_generic=generic) < 0.5
    assert phonetic_similarity("Zorbix Gate", "GATE", extra_generic=generic) < 0.5


def test_load_from_stats_file_and_env(tmp_path, monkeypatch):
    stats_path = tmp_path / "token_stats.json"
    stats_path.write_text(json.dumps({"meta": {}, "tokens": {"qwzx": [10, 20]}}), encoding="utf-8")
    assert dx.read_stats(stats_path) == {"qwzx": (10, 20)}
    assert dx.read_stats(tmp_path / "missing.json") == {}
    loaded = dx.load_distinctiveness(stats_path, with_goods=False)
    assert loaded.token_score("qwzx") == 0.0 and loaded.token_score("zorbix") == 1.0
    monkeypatch.setenv(dx.ENV_STATS_PATH, str(stats_path))
    assert dx.resolve_stats_path() == stats_path
    monkeypatch.delenv(dx.ENV_STATS_PATH)
    assert dx.resolve_stats_path() == dx.DEFAULT_STATS_PATH


# ---- build 스크립트 -------------------------------------------------------------------------

LIST_COLUMNS = ["심판번호", "종류", "상표명칭", "청구인", "피청구인"]


def _list_rows() -> list[dict]:
    rows = [
        {"심판번호": "R1", "종류": "거절결정불복", "상표명칭": "Qwzx Coffee",
         "청구인": "주식회사 갑", "피청구인": ""},
        {"심판번호": "R2", "종류": "거절결정불복", "상표명칭": "QWZX coffee", "청구인": "(주)갑",
         "피청구인": ""},  # 같은 제목·같은 소유자 → 한 번만
        {"심판번호": "N1", "종류": "무효", "상표명칭": "Qwzx Zorbix", "청구인": "을",
         "피청구인": "병"},
        {"심판번호": "S1", "종류": "권리범위확인(소극적)", "상표명칭": "Qwzx", "청구인": "정",
         "피청구인": "무"},
        {"심판번호": "C1", "종류": "취소", "상표명칭": "", "청구인": "기", "피청구인": "경"},
    ]
    return rows


def test_build_stats_owner_mapping_and_outputs(tmp_path):
    list_all = tmp_path / "list_all.csv"
    with list_all.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LIST_COLUMNS)
        writer.writeheader()
        writer.writerows(_list_rows())
    metadata = tmp_path / "meta.json"
    metadata.write_text(json.dumps({"trademarks": [
        {"상표한글명": "큐 Qwzx", "상표영문명": None, "출원인": "주식회사 신"},
        {"상표한글명": None, "상표영문명": "Zorbix", "출원인": "임"},
        {"상표한글명": None, "상표영문명": None, "출원인": "없음"},
    ]}, ensure_ascii=False), encoding="utf-8")
    assert build.owner_of({"종류": "무효", "청구인": "을", "피청구인": "병"}) == "병"
    assert build.owner_of({"종류": "거절결정불복", "청구인": "갑", "피청구인": ""}) == "갑"
    titles = build.collect_titles(build.read_list_all(list_all), build.read_metadata(metadata))
    assert len(titles) == 5  # R2 중복 제거, C1 제목 없음, DB 제목 없는 건 제외
    stats = build.token_stats(titles)
    assert stats["qwzx"] == (4, 4)  # 갑·병·무·신 (큐 Qwzx 포함) — 1글자 토큰 "큐" 는 세지 않는다
    assert stats["zorbix"] == (2, 2) and stats["coffee"] == (1, 1) and "큐" not in stats
    summary = build.run(list_all, metadata, tmp_path / "out", theta_a=4, theta_n=4, top=5,
                        goods_map=GOODS)
    stats_file = json.loads((tmp_path / "out" / "token_stats.json").read_text(encoding="utf-8"))
    assert stats_file["tokens"] == {"qwzx": [4, 4], "zorbix": [2, 2]}  # N ≥ 2 만
    weak = json.loads((tmp_path / "out" / "weak_tokens.json").read_text(encoding="utf-8"))
    weak_tokens = {row["token"]: row for row in weak["tokens"]}
    assert "qwzx" in weak_tokens and weak_tokens["qwzx"]["score"] == 0.0  # A=4·N=4 로 포화
    assert "zorbix" not in weak_tokens
    assert "coffee" not in weak_tokens  # 일반어 0.63 — 가짜 변환표에 영문 고시 명칭은 없다
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "## 상위 5" in report and "임계 민감도" in report and "| 5 / 10 |" in report
    assert summary["약한_토큰"] == len(weak["tokens"]) and len(summary["민감도"]) == 9
    assert summary["제목_소유자_쌍"] == 5
