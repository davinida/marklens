"""3호 후보 생성·분류 스크립트 테스트 — 가짜 약한 토큰·통계·목록·변환표·분류표로 표와 초안 형식을
확인."""

from __future__ import annotations

import csv
import json

from src.axes import distinctiveness as dx
from src.axes.goods_map import GoodsEntry, GoodsMap

from scripts import descriptive_candidates as dc

GOODS = GoodsMap([
    GoodsEntry("커피", 30, ("G0301",)), GoodsEntry("천연 비누", 3, ("G1201",)),
    GoodsEntry("천연가스", 4, ("G0401",)),
])


def _fixture(tmp_path):
    weak = tmp_path / "weak_tokens.json"
    weak.write_text(json.dumps({"tokens": [
        {"token": "premium", "score": 0.0, "A": 40, "N": 41,
         "reasons": ["일반어(zipf 4.3)", "다수 등록"]},
        {"token": "서울", "score": 0.0, "A": 6, "N": 6, "reasons": ["4호 지명"]},  # 법정 0점 → 제외
        {"token": "zorbixx", "score": 0.2, "A": 3, "N": 8, "reasons": ["다수 등록"]},
    ]}, ensure_ascii=False), encoding="utf-8")
    stats = tmp_path / "token_stats.json"
    stats.write_text(json.dumps({"tokens": {
        "premium": [40, 41], "커피": [14, 14], "cloud": [26, 34], "1994": [5, 6], "zorbixx": [3, 8],
        "천연": [1, 2], "dream": [44, 48],
    }}), encoding="utf-8")
    list_all = tmp_path / "list_all.csv"
    with list_all.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["심판번호", "종류", "상표명칭", "청구인", "피청구인"]
        )
        writer.writeheader()
        for i, title in enumerate(["PREMIUM COFFEE", "Premium Cloud", "커피 공방", "DREAM 1994",
                                   "프리미엄 커피", "Premium Coffee"]):
            writer.writerow({"심판번호": f"T{i}", "종류": "무효", "상표명칭": title,
                             "청구인": f"o{i}", "피청구인": ""})
    metadata = tmp_path / "meta.json"
    metadata.write_text(json.dumps({"trademarks": [{"상표한글명": "클라우드 커피", "출원인": "x"}]},
                                   ensure_ascii=False), encoding="utf-8")
    judgements = {
        "premium": dc.J("포함", "품질", True, None, "판례 예시와 같은 품질 우수성 표시"),
        "커피": dc.J("포함", "원재료", False, [30, 35, 43], "커피 원재료·취급품"),
        "cloud": dc.J("보류", "품질", False, None, "암시인지 애매"),
        "dream": dc.J("제외", reason="암시·강조에 그침"),
        "유기농": dc.J("포함", "생산방법", False, [29, 30], "후보 풀에 없던 전형적 성질 표시어"),
    }
    return weak, stats, list_all, metadata, judgements


def test_candidates_sources_evidence_and_eligibility(tmp_path):
    weak, stats, list_all, metadata, judgements = _fixture(tmp_path)
    sources = dc.collect_candidates(weak, stats, GOODS, judgements)
    assert sources["premium"] == {"a", "b", "d"} and sources["cloud"] == {"b"}
    assert "서울" not in sources  # 1·4·5·6호 약한 토큰은 후보가 아니다
    assert sources["커피"] == {"b", "c"}  # c: 고시 단일 명칭
    assert sources["유기농"] == {"e"}  # e: 분류표 추가
    assert sources["best"] == {"d"} and "천연" not in sources  # 천연 비누는 두 토큰이라 c 가 아니다
    examples = dc.example_index(dc.read_titles(list_all, metadata), set(sources))
    # 토큰 일치만(한글 "프리미엄" 은 다른 토큰), 같은 제목(대소문자)은 한 번만
    assert examples["premium"] == ["PREMIUM COFFEE", "Premium Cloud"]
    assert examples["커피"][0] == "커피 공방" and "클라우드 커피" in examples["커피"]
    evidence = dc.goods_class_evidence(GOODS, {"커피", "천연", "coffee"})
    assert evidence["커피"] == [(30, 1)]
    assert evidence["천연"] == [(3, 1), (4, 1)]  # 한글은 부분 문자열
    assert dc.is_eligible("zorbixx") == (False, "빈도 미달(zipf 0.0 < 3.0)")
    assert dc.is_eligible("premium")[0] and dc.is_eligible("커피")[0] and dc.is_eligible("1994")[0]


def test_run_writes_table_and_draft_with_approved_false(tmp_path):
    weak, stats, list_all, metadata, judgements = _fixture(tmp_path)
    md, out = tmp_path / "cand.md", tmp_path / "terms.json"
    meta = dc.run(weak_path=weak, stats_path=stats, list_all=list_all, metadata=metadata,
                  md_path=md, json_path=out, goods_map=GOODS, judgements=judgements)
    assert meta["판정"]["포함"] == 3 and meta["판정"]["보류"] >= 2 and meta["출처"]["e"] == 1
    assert meta["절대어"] == ["premium"]
    assert meta["kind별_포함"] == {"품질": 1, "원재료": 1, "생산방법": 1}
    text = md.read_text(encoding="utf-8")
    assert text.startswith("# 3호 기술적 표장 후보 분류표")
    assert "## 포함 (kind 별)" in text and "## 보류" in text
    assert "## 제외 (사유 유형별 건수)" in text
    assert "| premium | 품질 | O | 불문 | 40 | 41 |" in text
    assert "| 커피 | 원재료 |  | 30,35,43 | 14 | 14 |" in text and "30류1" in text
    assert "| 1994 | 수량 |" in text  # 숫자는 목록에 없으면 보류
    assert "| dream | 44 | 48 |" in text and "암시·강조에 그침" in text  # 개별 판단 제외 표
    assert "zorbixx" in text and "빈도 미달" in text
    draft = json.loads(out.read_text(encoding="utf-8"))
    assert set(draft["terms"]) == {"premium", "커피", "유기농"}
    assert draft["terms"]["premium"] == {
        "kind": "품질", "absolute": True, "classes": None,
        "note": "판례 예시와 같은 품질 우수성 표시",
        "examples": ["PREMIUM COFFEE", "Premium Cloud"], "approved": False,
    }
    assert draft["terms"]["커피"]["classes"] == [30, 35, 43] and draft["meta"]["승인"] == 0
    terms = dx.validate_descriptive_terms(draft)  # 초안은 로더 검증을 통과한다
    assert dx.unapproved_terms(terms) == ["premium", "유기농", "커피"]
    model = dx.Distinctiveness({}, descriptive=terms, goods_names=dx.goods_index(GOODS)[0],
                               code_classes=dx.goods_index(GOODS)[1])
    assert model.token_score("premium", {"G1201"}) == 0.0  # 절대
    reasons = model.judge("커피", {"G0301"}).reasons  # 같은 류: 3호(류 30)와 1호가 함께 0점 사유
    assert "1호 보통명칭" in reasons and "3호 기술적 표장:원재료(류 30)" in reasons
    assert model.judge("커피", {"G1201"}).score < 1.0  # 3류: 커피 류(30·35·43) 아님 → 일반어 점수만
    assert model.judge("커피").score == 0.0  # 상품 미상: 1호(전역)
