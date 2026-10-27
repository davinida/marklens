"""goods_backfill — 빈 유사군 백필(서지상세). 실제 KIPRIS 호출 없음(bibliography_detail_raw 를
바꿔 끼운다)."""

from __future__ import annotations

import json

import pytest

from backend.scripts import collect_pipeline as collect
from backend.scripts import goods_backfill as gb
from backend.src.core import kipris_client as kc

XML = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>00</resultCode></header><body><item>
  <biblioSummaryInfoArray><biblioSummaryInfo><applicationNumber>{appno}</applicationNumber>
  </biblioSummaryInfo></biblioSummaryInfoArray>
  <similarityCodeInfoArray>{codes}</similarityCodeInfoArray>
</item></body></response>"""


def _xml(appno: str, codes: list[str]) -> str:
    inner = "".join(f"<similarityCodeInfo><similarCode>{c}</similarCode></similarityCodeInfo>"
                    for c in codes)
    return XML.format(appno=appno, codes=inner)


def _record(appno: str, classes: list[int], codes: list[str] | None = None) -> dict:
    return {"출원번호": appno, "상표한글명": f"상표{appno[-1]}", "류": classes,
            "유사군": codes or []}


@pytest.fixture
def data(tmp_path, monkeypatch):
    """CRLF·들여쓰기 2·끝 줄바꿈 없음 메타 + 해시가 맞물린 authoritative keys·manifest."""
    meta = {"dataset_info": {"총_상표수": 4}, "trademarks": [
        _record("4020200000004", [3]),
        _record("4020200000001", [43], ["S120602"]),
        _record("4020200000003", [25, 43]),
        _record("4020200000002", [9]),
    ]}
    meta_path = tmp_path / "kipris_metadata.json"
    meta_path.write_bytes(
        json.dumps(meta, ensure_ascii=False, indent=2).replace("\n", "\r\n").encode()
    )
    auth_path = tmp_path / "kipris_authoritative_keys.json"
    auth_path.write_bytes(json.dumps({
        "schema_version": 1, "metadata_sha256": collect._sha256_file(meta_path),  # noqa: SLF001
        "image_keys": [],
    }, indent=2).replace("\n", "\r\n").encode())
    manifest_path = tmp_path / "kipris_manifest.json"
    manifest_path.write_text(json.dumps({"source": {
        "sha256": collect._sha256_file(auth_path), "type": "authoritative_keys",  # noqa: SLF001
    }}, indent=2), encoding="utf-8")
    raw_dir = tmp_path / "raw"
    monkeypatch.setattr(gb, "META_PATH", meta_path)
    monkeypatch.setattr(gb, "AUTH_PATH", auth_path)
    monkeypatch.setattr(gb, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(collect, "COLLECT_RAW_XML_DIR", raw_dir)
    monkeypatch.setattr(kc, "limiter", kc.RateLimiter(
        counter_path=tmp_path / "count.json", monthly_budget=950, min_interval=0, daily_budget=400,
    ))
    calls: list[str] = []
    responses = {"4020200000003": ["G2701", "G4503"], "4020200000004": [],
                 "4020200000002": ["G0901"]}

    def fake_raw(appno: str) -> str:
        kc.limiter.acquire()
        calls.append(appno)
        return _xml(appno, responses[appno])

    monkeypatch.setattr(kc, "bibliography_detail_raw", fake_raw)
    return tmp_path, calls


def _meta(tmp_path) -> dict:
    return json.loads((tmp_path / "kipris_metadata.json").read_bytes())


def test_plan_orders_by_class_priority_and_makes_no_calls(data, capsys):
    _, calls = data
    assert gb.main(["plan", "--classes", "25,3"]) == 0
    out = capsys.readouterr().out
    assert "대상 2건" in out and "25류 1 → 3류 1" in out
    assert calls == []
    meta = gb.MetaFile.load(gb.META_PATH)
    assert [r["출원번호"] for r in gb.targets(meta, (25, 3), True)] == [
        "4020200000003", "4020200000004", "4020200000002",
    ]


def test_run_fills_codes_keeps_format_and_rechains_hashes(data):
    tmp_path, calls = data
    before = (tmp_path / "kipris_metadata.json").read_bytes()
    assert gb.main(["run", "--classes", "25,3", "--max-calls", "10"]) == 0
    # 9류는 우선순위 밖이라 --all 없이는 부르지 않는다
    assert calls == ["4020200000003", "4020200000004"]
    records = {r["출원번호"]: r for r in _meta(tmp_path)["trademarks"]}
    assert records["4020200000003"]["유사군"] == ["G2701", "G4503"]
    assert records["4020200000004"]["유사군"] == []  # 유사군 없음 응답은 빈 채로
    after = (tmp_path / "kipris_metadata.json").read_bytes()
    assert b"\r\n" in after and not after.endswith(b"\r\n")
    assert after.replace(b"\r\n", b"\n").count(b"\n") > before.replace(b"\r\n", b"\n").count(b"\n")
    gb.check_chain()  # 메타 → authoritative keys → manifest 해시가 다시 맞물린다
    assert b"\r\n" in (tmp_path / "kipris_authoritative_keys.json").read_bytes()
    raws = sorted(p.name.split("_")[1] for p in (tmp_path / "raw").glob("biblio_*.xml"))
    assert raws == ["4020200000003", "4020200000004"]
    assert kc.limiter.used_today() == 2
    # 다시 돌리면 원본이 있는 출원번호는 부르지 않는다(유사군 없음 포함)
    assert gb.main(["run", "--classes", "25,3"]) == 0
    assert calls == ["4020200000003", "4020200000004"]


def test_broken_hash_chain_stops_before_any_call(data, capsys):
    tmp_path, calls = data
    (tmp_path / "kipris_manifest.json").write_text('{"source": {"sha256": "x"}}', "utf-8")
    assert gb.main(["run", "--all"]) == 2
    assert calls == [] and "manifest" in capsys.readouterr().err


def test_budget_exhaustion_saves_progress(data):
    tmp_path, calls = data
    counter = tmp_path / "count.json"
    month = kc.limiter._month_key()  # noqa: SLF001
    counter.write_text(json.dumps({month: 949}), "utf-8")  # 월 예산 1회 남음
    assert gb.main(["run", "--all", "--max-calls", "10"]) == 0
    assert calls == ["4020200000003"]
    assert {r["출원번호"]: r["유사군"] for r in _meta(tmp_path)["trademarks"]}[
        "4020200000003"] == ["G2701", "G4503"]
    gb.check_chain()


def test_consecutive_failures_stop_the_run(data, monkeypatch):
    _, calls = data

    def down(appno: str) -> str:
        kc.limiter.acquire()
        calls.append(appno)
        raise kc.KiprisNetworkError("down")

    monkeypatch.setattr(kc, "bibliography_detail_raw", down)
    monkeypatch.setattr(gb, "MAX_FAILURE_STREAK", 2)
    assert gb.main(["run", "--all", "--max-calls", "10"]) == 1
    assert len(calls) == 2  # 3건 대상이지만 2회 연속 실패에서 멈춘다


def test_missing_key_reports_config_error(data, monkeypatch, capsys):
    def no_key(appno: str) -> str:
        raise kc.KiprisConfigError("KIPRIS_ACCESS_KEY 가 설정되지 않았습니다.")

    monkeypatch.setattr(kc, "bibliography_detail_raw", no_key)
    assert gb.main(["run", "--all"]) == 2
    assert "KIPRIS_ACCESS_KEY" in capsys.readouterr().err
    gb.check_chain()  # 아무것도 쓰지 않았다
