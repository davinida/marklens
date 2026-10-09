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


@pytest.fixture
def model():
    names, classes = dx.goods_index(GOODS)
    return dx.Distinctiveness(STATS, famous={"삼성", "starbucks", "스타벅스"}, goods_names=names,
                              code_classes=classes)


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


def test_descriptive_slot_is_empty_but_applied(model, monkeypatch):
    assert dx.DESCRIPTIVE_TERMS == {}
    before = model.token_score("프리미엄")
    monkeypatch.setattr(dx, "DESCRIPTIVE_TERMS", {"프리미엄": "품질", "천연": "원재료"})
    assert model.judge("프리미엄").reasons == ("3호 기술적 표장:품질",)
    assert model.token_score("프리미엄") == 0.0 and model.token_score("천연") == 0.0
    assert before > 0.0
    explicit = dx.Distinctiveness({}, descriptive={"수제": "생산방법"})
    assert explicit.judge("수제").reasons == ("3호 기술적 표장:생산방법",)


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
