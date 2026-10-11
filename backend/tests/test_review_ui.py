"""검토 웹 화면 테스트 — 임시 데이터 디렉터리(라벨·텍스트·이미지·검토 묶음·3호 JSON)와 TestClient
만. 네트워크·KIPRIS 없음. 저장은 trials_collect 함수(잠금·보존)와 distinctiveness 갱신 함수를
거친다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.scripts import review_ui as ui
from backend.scripts import trials_collect as tc

dx = ui.dx  # ml/src/axes/distinctiveness — review_ui 가 sys.path 를 맞춘 뒤 적재한 모듈
T1, T2, T3 = "2023100000001", "2023100000002", "2023100000003"
EVIDENCE = '확인대상표장은 "Q-FIRE" 부분만으로 호칭되므로'
TEXT = """심판번호 2023당1
사건표시 상표등록 제1697796호 권리범위확인(적극)
주       문
1. 확인대상표장은 상표등록 제1697796호의 권리범위에 속한다.
2. 심판비용은 피청구인이 부담한다.
이       유
1. 기초사실
가. 이 사건 등록상표
(1) 등록번호 : 상표등록 제1697796호
(2) 구성 : 큐파이어
나. 확인대상표장
(1) 구성 : Q-FIRE
2. 당사자의 주장
가. 청구인의 주장
3. 확인대상표장이 이 사건 등록상표의 권리범위에 속하는지 여부
가. 판단
확인대상표장은 "Q-FIRE" 부분만으로 호칭되므로 이 사건 등록상표와 호칭이 동일하여 유사하다.
나. 소결
따라서 확인대상표장은 이 사건 등록상표의 권리범위에 속한다.
4. 결론
"""
DONE = tc.BUNDLE_DONE


def _label(**values) -> dict:
    row = {column: "" for column in tc.LABEL_COLUMNS}
    row.update(values)
    return row


def _bundle_rows(name: str, columns: list[str], rows: list[dict], base: Path) -> None:
    for row in rows:
        row.setdefault("show", "")
        row.setdefault(DONE, "")
    tc._write_csv(tc.TrialPaths(base).review_bundle_dir / f"{name}.csv",
                  columns + ["show", DONE], rows)


@pytest.fixture
def base(tmp_path: Path) -> Path:
    paths_ = tc.TrialPaths(tmp_path)
    scope, refusal = "권리범위확인(적극적)", "거절결정불복"
    rows = [
        _label(심판번호=T1, 종류=scope, 상표A_명칭="큐파이어", 유사여부_확정="유사",
               판단축_확정="호칭", 확신도="high", 근거문장=EVIDENCE, 라벨출처="llm",
               llm_b_유사여부="유사",
               llm_b_판단축="호칭", llm_b_확신도="high", 상대표장_명칭_llm="Q-FIRE",
               상대표장_명칭_본문="본문명칭", 메모="애매: 축 명시 없음"),
        _label(심판번호=T2, 종류=refusal, 상표A_명칭="GATE", 상표B_번호="111",
               유사여부_확정="비유사", 판단축_확정="외관", 확신도="low", 근거문장="외관이 다르다",
               라벨출처="llm",
               llm_b_유사여부="유사", llm_b_판단축="호칭", 상대표장_명칭_kipris="GATE"),
        _label(심판번호=T3, 종류="무효", 상표A_명칭="Zorbix Gate", 상표B_번호="222",
               유사여부_확정="유사", 라벨출처="llm", 확신도="high", 근거문장="e",
               llm_b_유사여부="유사", 상대표장_명칭_kipris="Hello Gate"),
    ]
    tc._write_csv(paths_.labels_csv, tc.LABEL_COLUMNS, rows)
    paths_.text_dir.mkdir()
    (paths_.text_dir / f"{T1}.txt").write_text(TEXT, encoding="utf-8")
    images = tmp_path / "images" / T1
    images.mkdir(parents=True)
    Image.new("RGB", (8, 8), (200, 30, 30)).save(images / "this.png")
    Image.new("RGB", (8, 8), (30, 30, 200)).save(images / "target.png")
    tc._write_csv(tmp_path / "image_pairs_v1.csv", ["심판번호", "상대번호", "이미지A", "이미지B"],
                  [{"심판번호": T1, "상대번호": "", "이미지A": f"images/{T1}/this.png",
                    "이미지B": f"images/{T1}/target.png"}])
    paths_.review_bundle_dir.mkdir()
    _bundle_rows("verify_queue", tc.VERIFY_COLUMNS, [
        {"순번": 1, "층": "scope/유사", "심판번호": T1, "상표B_번호": "", "종류": scope,
         "유사여부_확정": "유사"},
        {"순번": 2, "층": "refusal/비유사", "심판번호": T2, "상표B_번호": "111", "종류": refusal,
         "유사여부_확정": "비유사"},
    ], tmp_path)
    _bundle_rows("ab_disagree", tc.AB_DISAGREE_COLUMNS, [
        {"순번": 1, "심판번호": T2, "상표B_번호": "111", "종류": refusal, "유사여부_확정": "비유사",
         "llm_b_유사여부": "유사"},
    ], tmp_path)
    _bundle_rows("name_review", tc.NAME_REVIEW_COLUMNS, [
        {"순번": 1, "심판번호": T1, "상표B_번호": "", "종류": scope, "상표A_명칭": "큐파이어",
         "상대표장_명칭_llm": "Q-FIRE", "사유": "검토"},
    ], tmp_path)
    _bundle_rows("distinct_drop", tc.DISTINCT_DROP_COLUMNS, [
        {"순번": 1, "심판번호": T3, "상대번호": "222", "종류": "무효", "표장라벨": "유사",
         "최종라벨": "유사", "이름A": "Zorbix Gate", "이름B": "Hello Gate", "x1": "1.0000",
         "x1_d": "0.3000", "x2_text": "1.0000", "x2_text_d": "0.2000", "떼어낸_토큰_A": "gate",
         "떼어낸_토큰_B": "gate"},
    ], tmp_path)
    _bundle_rows("weak_tokens_top200", tc.WEAK_TOKENS_COLUMNS, [
        {"순번": 1, "토큰": "coffee", "점수": "0.0", "A": 112, "N": 119, "zipf": 4.9,
         "사유": "다수 등록"},
        {"순번": 2, "토큰": "gate", "점수": "0.0", "A": 12, "N": 30, "zipf": 4.5, "사유": "일반어"},
    ], tmp_path)
    terms = {
        "best": {"kind": "품질", "absolute": True, "classes": None, "note": "판례 예시",
                 "examples": ["Best Cosme"], "approved": False},
        "커피": {"kind": "원재료", "absolute": False, "classes": [30, 43], "note": "원재료",
                "examples": [], "approved": False},
        "fresh": {"kind": "품질", "absolute": False, "classes": [29, 30], "note": "신선",
                  "examples": [], "approved": True},
    }
    (tmp_path / "descriptive_terms.json").write_text(
        json.dumps({"meta": {}, "terms": terms}, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def client(base: Path) -> TestClient:
    config = ui.ReviewConfig(base=base, descriptive_path=base / "descriptive_terms.json",
                             weak_path=base / "weak_tokens.json",
                             overrides_path=base / "weak_token_overrides.json")
    return TestClient(ui.create_app(config))


def _decide(client: TestClient, **body):
    return client.post("/api/decide", json=body)


def _labels(base: Path) -> dict[tuple[str, str], dict]:
    rows = tc._read_csv(tc.TrialPaths(base).labels_csv)
    return {(r["심판번호"], r["상표B_번호"]): r for r in rows}


def test_bundle_cards_images_and_status(client: TestClient):
    page = client.get("/")
    assert page.status_code == 200 and "MarkLens 검토" in page.text
    data = client.get("/api/bundle/verify_queue").json()
    assert data["progress"] == {"done": 0, "total": 2} and data["exists"]
    first, second = data["items"]
    assert first["심판번호"] == T1 and first["key"] == f"{T1}|||"
    assert first["이름A"] == "큐파이어" and first["이름B"] == "Q-FIRE"
    assert first["이름B_출처"] == "llm"
    assert first["주문"].startswith("1. 확인대상표장은 상표등록 제1697796호의 권리범위에 속한다.")
    assert "3. 확인대상표장이 이 사건 등록상표의 권리범위에 속하는지 여부" in first["판단절"]
    assert first["llm_a"] == {"판정": "유사", "판단축": "호칭", "확신도": "high", "근거": EVIDENCE,
                              "제외사유": "", "상표유형": ""}
    assert first["llm_b"]["판정"] == "유사"
    assert first["이미지"] == {"A": f"/img/{T1}/this", "B": f"/img/{T1}/target"}
    assert second["이름B_출처"] == "kipris" and second["텍스트"] is False
    assert second["이미지"] == {"A": None, "B": None}  # 이미지 없음
    img = client.get(f"/img/{T1}/this")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert client.get(f"/img/{T1}/missing").status_code == 400  # 역할 형식
    assert client.get("/img/abc/this").status_code == 400  # 심판번호 형식
    assert client.get(f"/img/{T2}/this").status_code == 404
    assert client.get("/api/bundle/nope").status_code == 404
    ab = client.get("/api/bundle/ab_disagree").json()["items"][0]
    assert ab["llm_a"]["판정"] == "비유사" and ab["llm_b"]["판정"] == "유사"
    status = client.get("/api/status").json()["lines"]
    assert any(line.startswith("라벨: ") for line in status)
    assert any("검토 묶음(처리/행): verify_queue 0/2" in line for line in status)


def test_decide_confirm_label_undo_name_and_decision(client: TestClient, base: Path):
    # confirm → 확인여부 Y, 묶음 처리 표시
    res = _decide(client, tab="verify_queue", 심판번호=T1, b="", key=f"{T1}|||",
                  action="confirm").json()
    assert res["ok"] and res["message"] == "승인 1행" and res["card"]["확인여부"] == "Y"
    assert _labels(base)[(T1, "")]["라벨출처"] == "human-confirmed"
    assert res["card"]["처리"].startswith("confirm ")
    assert client.get("/api/bundle/verify_queue").json()["progress"]["done"] == 1
    # label(사람) — 근거·확신도는 기존 LLM 값을 잇고 판단축을 바꾼다
    res = _decide(client, tab="ab_disagree", 심판번호=T2, b="111", key=f"{T2}|111||",
                  action="label", verdict="유사", axis="호칭,외관").json()
    row = _labels(base)[(T2, "111")]
    assert row["유사여부_확정"] == "유사" and row["판단축_확정"] == "외관|호칭"
    assert row["라벨출처"] == "human" and row["llm_판정_원본"] == "비유사"
    assert row["근거문장"] == "외관이 다르다" and row["확신도"] == "low" and row["확인여부"] == "Y"
    assert res["card"]["llm_a"]["판정"] == "유사"
    # 제외는 사유 필수(409), 모르는 action 400, 심판번호 형식 400
    assert _decide(client, tab="ab_disagree", 심판번호=T2, b="111", action="label",
                   verdict="제외").status_code == 409
    assert _decide(client, tab="ab_disagree", 심판번호=T2, action="x").status_code == 400
    assert _decide(client, tab="ab_disagree", 심판번호="1;rm", action="confirm").status_code == 400
    # undo → 라벨 열 비움, 처리 취소
    res = _decide(client, tab="ab_disagree", 심판번호=T2, b="111", key=f"{T2}|111||",
                  action="undo").json()
    assert _labels(base)[(T2, "111")]["유사여부_확정"] == "" and res["card"]["처리"] == ""
    # name_b(사람 수정) → 상대표장_명칭_llm 갱신 + review_decisions 기록, 메모는 그대로
    res = _decide(client, tab="name_review", 심판번호=T1, b="", key=f"{T1}|||", action="name_b",
                  name=" Q-FIRE 500MP ").json()
    assert _labels(base)[(T1, "")]["상대표장_명칭_llm"] == "Q-FIRE 500MP"
    assert res["card"]["명칭_llm"] == "Q-FIRE 500MP"
    assert _labels(base)[(T1, "")]["메모"] == "애매: 축 명시 없음"
    decisions = json.loads((base / "review_decisions.json").read_text(encoding="utf-8"))
    assert decisions["name_review"][f"{T1}|||"]["name"] == "Q-FIRE 500MP"
    # distinct_drop 결정 → review_decisions.json 만(라벨 불변), 처리 표시
    res = _decide(client, tab="distinct_drop", 심판번호=T3, b="222", key=f"{T3}||222|",
                  action="decision", decision="결합 규칙 후보", memo="gate 공통").json()
    assert res["card"]["결정"]["decision"] == "결합 규칙 후보"
    decisions = json.loads((base / "review_decisions.json").read_text(encoding="utf-8"))
    assert decisions["distinct_drop"][f"{T3}||222|"]["memo"] == "gate 공통"
    assert _labels(base)[(T3, "222")]["유사여부_확정"] == "유사"
    assert client.get("/api/bundle/distinct_drop").json()["progress"] == {"done": 1, "total": 1}
    assert _decide(client, tab="distinct_drop", 심판번호=T3, b="222", action="decision",
                   decision="모름").status_code == 409


def test_approve_updates_descriptive_terms_and_loader_skips_rejected(client: TestClient,
                                                                       base: Path):
    groups = client.get("/api/bundle/descriptive").json()
    assert [g["name"] for g in groups["groups"]] == ["절대어", "품질", "원재료"]  # 절대어 먼저
    assert groups["progress"] == {"done": 1, "total": 3}
    res = _decide(client, action="approve",
                  approvals={"best": True, "커피": False, "zzz": True}).json()
    assert res["승인"] == 1 and res["해제"] == 1 and res["없음"] == ["zzz"]
    data = json.loads((base / "descriptive_terms.json").read_text(encoding="utf-8"))
    assert data["terms"]["best"]["approved"] is True and "rejected" not in data["terms"]["best"]
    assert data["terms"]["커피"]["approved"] is False and data["terms"]["커피"]["rejected"] is True
    assert data["meta"] == {"승인": 2, "해제": 1}
    terms = dx.read_descriptive_terms(base / "descriptive_terms.json")
    assert set(terms) == {"best", "fresh"} and terms["best"].approved  # 해제 항목은 적용 안 함
    assert client.get("/api/bundle/descriptive").json()["progress"] == {"done": 3, "total": 3}
    assert _decide(client, action="approve", approvals="best").status_code == 400


def test_override_writes_file_and_loader_excludes(client: TestClient, base: Path, monkeypatch):
    res = _decide(client, action="override", excluded=["coffee"], kept=["gate"], memo="검토").json()
    assert res["excluded"] == 1 and res["kept"] == 1
    overrides = base / "weak_token_overrides.json"
    saved = json.loads(overrides.read_text(encoding="utf-8"))
    assert set(saved["excluded"]) == {"coffee"} and set(saved["kept"]) == {"gate"}
    assert dx.read_weak_overrides(overrides) == frozenset({"coffee"})
    bundle = client.get("/api/bundle/weak_tokens_top200").json()
    assert bundle["progress"] == {"done": 2, "total": 2}
    assert [(t["토큰"], t["excluded"], t["kept"]) for t in bundle["items"]] == [
        ("coffee", True, False), ("gate", False, True)
    ]
    # 유지 → 제외로 바꾸면 kept 에서 빠진다
    _decide(client, action="override", excluded=["gate"], kept=[])
    assert dx.read_weak_overrides(overrides) == frozenset({"coffee", "gate"})
    # 로더: excluded 토큰은 점수 1.0(다수 등록이어도)
    model = dx.Distinctiveness({"coffee": (112, 119)}, overrides=dx.read_weak_overrides(overrides),
                               descriptive={})  # 실제 3호 목록과 분리(coffee 는 3호 상대어)
    assert model.judge("coffee") == dx.TokenJudgement(
        "coffee", 1.0, ("사람 검토 제외(weak_token_overrides)",)
    )
    assert dx.Distinctiveness({"coffee": (112, 119)}).token_score("coffee") == 0.0
    monkeypatch.setenv(dx.ENV_OVERRIDES_PATH, str(overrides))
    assert dx.resolve_overrides_path() == overrides
    judged = dx.build({"coffee": (112, 119)}, famous=set()).judge("coffee")
    # 환경변수 경로의 overrides 가 적용된다(실제 3호 목록에 coffee 가 상대어라 상품 미상 상한 0.5)
    assert judged.reasons[0] == "사람 검토 제외(weak_token_overrides)" and judged.score >= dx.THETA
    assert dx.read_weak_overrides(base / "none.json") == frozenset()
