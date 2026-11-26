"""시작 단계 점검 — 모델 JSON·색인·메타데이터가 없거나 깨졌을 때 서버가 기동 단계에서 멈추는지, 떠
있다면 조용히 엉뚱한 결과를 내지 않고 503 으로 알리는지 본다. 원본 데이터는 건드리지 않고 임시
폴더에 심볼릭 링크로 데이터 폴더를 만든 뒤 한 파일만 바꾼다. 포트 8002 를 잠깐씩 쓴다.

    ml/venv/bin/python scripts/robustness/probe_startup.py [--out DIR] [--only famous]
결과: DIR/probe_startup.json(--only famous 면 DIR/probe_startup_famous.json)

유명 상표 확인(v1.4.7)의 경우: 등록부·확정 파일·대표 로고 구분 파일이 없거나 등록부가 확정 파일의
해시와 다르면 모델 파일 문제와 같게(떠서 /health 503 FAMOUS_CHECK_UNAVAILABLE·검색 503), 대표 로고가
색인에 없는 DB(--old-data 로 준 폴더)에서는 그 표장만 건너뛰고 이름 확인은 그대로, v1.4.6 JSON 으로
띄우면 유명 상표 확인 없이 예전처럼 동작하는지 본다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "ml" / "data"
PORT = 8002


def data_copy(tmp: Path, replace: dict[str, bytes | None]) -> Path:
    """ml/data 의 각 항목을 심볼릭 링크로 잇고, index/ 는 파일 단위로 이어 replace 만 바꾼다."""
    target = tmp / "data"
    target.mkdir()
    for item in DATA.iterdir():
        if item.name == "index":
            continue
        (target / item.name).symlink_to(item)
    index = target / "index"
    index.mkdir()
    for item in (DATA / "index").iterdir():
        relative = f"index/{item.name}"
        if relative in replace:
            if replace[relative] is not None:
                (index / item.name).write_bytes(replace[relative])
            continue
        (index / item.name).symlink_to(item)
    for relative, content in replace.items():
        if not relative.startswith("index/"):
            path = target / relative
            if path.is_symlink():
                path.unlink()
            if content is not None:
                path.write_bytes(content)
    return target


def run(label: str, env: dict, key: str, wait: float = 150, name: str = "블루커피") -> dict:
    full = {
        **os.environ,
        "KIPRIS_ACCESS_KEY": "",
        "KIPRIS_TRIAL_ACCESS_KEY": "",
        "MARKLENS_API_KEY": key,
        **env,
    }
    full.pop("MARKLENS_FAKE_ML", None)
    log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
    process = subprocess.Popen(
        [
            str(ROOT / "ml/venv/bin/python"),
            "-m",
            "uvicorn",
            "backend.src.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
        ],
        cwd=ROOT,
        env=full,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    started = time.time()
    outcome: dict = {"이름": label}
    try:
        while time.time() - started < wait:
            if process.poll() is not None:
                outcome["기동"] = f"멈춤(종료 코드 {process.returncode})"
                break
            try:
                health = requests.get(f"http://127.0.0.1:{PORT}/health", timeout=2)
                outcome["기동"] = "떴음"
                outcome["health"] = {"상태": health.status_code, "본문": health.json()}
                search = requests.post(
                    f"http://127.0.0.1:{PORT}/search/v2",
                    headers={"X-API-Key": key},
                    files=[("name", (None, name))],
                    timeout=60,
                )
                body = search.json()
                famous = body.get("famous")
                outcome["검색"] = {
                    "이름": name,
                    "상태": search.status_code,
                    "detail": body.get("detail"),
                    "전체": (body.get("overall") or {}).get("grade"),
                    "모델": (body.get("meta") or {}).get("model_version"),
                    "유명_상표": None if famous is None else {
                        "status": famous.get("status"),
                        "일치": [f"{m['brand']} {m['level']}({m['basis']}) 로고 {len(m['logos'])}"
                               for m in famous.get("matches", [])],
                        "바닥이_정함": (body.get("overall") or {}).get("famous_floor"),
                    },
                }
                break
            except requests.RequestException:
                time.sleep(2)
        else:
            outcome["기동"] = "시간 초과"
        outcome["초"] = round(time.time() - started, 1)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
        log.seek(0)
        text = log.read()
        lines = [
            line
            for line in text.splitlines()
            if any(k in line for k in ("FATAL", "ERROR", "실패", "Error", "error", "모델", "통합",
                                       "유명 상표"))
        ]
        outcome["로그_요약"] = [line[-220:] for line in lines[-6:]]
        outcome["로그_경로_노출"] = text.count("/Users/")
        log.close()
        os.unlink(log.name)
    print(json.dumps(outcome, ensure_ascii=False)[:900], flush=True)
    return outcome


def famous_cases(tmp: Path, key: str, old_data: Path | None) -> list[dict]:
    """유명 상표 확인(v1.4.7)의 시작 단계 — 파일이 없거나 해시가 다를 때, 대표 로고가 색인에 없을
    때, 유명 상표 확인이 없는 v1.4.6 JSON 으로 띄울 때."""
    missing = str(tmp / "없는_파일.json")
    changed = tmp / "famous_registry_changed.json"
    text = (ROOT / "shared/famous_registry.json").read_text(encoding="utf-8")
    changed.write_text(text.replace("스타벅스", "스타벅수", 1), encoding="utf-8")
    name = "스타벅스"
    results = [
        run("유명 상표: 그대로(v1.4.7)", {}, key, name=name),
        run("유명 상표: 등록부 없음", {"MARKLENS_FAMOUS_REGISTRY": missing}, key, name=name),
        run("유명 상표: 확정 파일 없음", {"MARKLENS_FAMOUS_CONFIRMED": missing}, key, name=name),
        run("유명 상표: 대표 로고 구분 파일 없음", {"MARKLENS_FAMOUS_LOGO_KINDS": missing}, key,
            name=name),
        run("유명 상표: 등록부가 확정 파일의 해시와 다름",
            {"MARKLENS_FAMOUS_REGISTRY": str(changed)}, key, name=name),
        run("유명 상표: v1.4.6 JSON 으로 띄움(확인 꺼짐)",
            {"MARKLENS_RISK_MODEL": str(ROOT / "shared/model/risk_model_v1.4.6.json")}, key,
            name=name),
    ]
    if old_data is not None and old_data.is_dir():
        results.append(run(
            "유명 상표: 대표 로고가 색인에 없는 DB(승격 전 사본)",
            {"MARKLENS_DATA_DIR": str(old_data),
             "MARKLENS_IMAGES_DIR": str(ROOT / "ml/data/images")}, key, name=name))
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=("famous",), default=None)
    parser.add_argument("--old-data", type=Path, default=None,
                        help="대표 로고가 없는 예전 DB 사본(index/·메타데이터·types.json)")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path.home() / "marklens-archive" / f"robustness-{date.today():%Y%m%d}",
    )
    args = parser.parse_args()
    key = (args.out / "api_key").read_text(encoding="utf-8").strip()
    results = []
    if args.only == "famous":
        with tempfile.TemporaryDirectory() as tmp_text:
            results = famous_cases(Path(tmp_text), key, args.old_data)
        (args.out / "probe_startup_famous.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return 0
    with tempfile.TemporaryDirectory() as tmp_text:
        tmp = Path(tmp_text)
        broken = tmp / "broken.json"
        broken.write_text("{ 이건 JSON 이 아님", encoding="utf-8")
        tampered = tmp / "tampered.json"
        model = json.loads(
            (ROOT / "shared/model/risk_model_v1.4.1.json").read_text(encoding="utf-8")
        )
        model["grade_thresholds"] = {"주의": 0.9, "검토 권장": 0.5, "위험": 0.1}
        tampered.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        results.append(
            run("모델 JSON 없음", {"MARKLENS_RISK_MODEL": str(tmp / "missing.json")}, key)
        )
        results.append(run("모델 JSON 깨짐", {"MARKLENS_RISK_MODEL": str(broken)}, key))
        results.append(
            run("모델 JSON 하한 순서 뒤집힘", {"MARKLENS_RISK_MODEL": str(tampered)}, key)
        )
        for label, replace in (
            ("색인 파일 없음", {"index/kipris.faiss": None}),
            ("색인 파일 깨짐", {"index/kipris.faiss": os.urandom(4096)}),
            ("메타데이터 깨짐", {"index/kipris_metadata.json": b"{broken"}),
            ("유형 사전 없음", {"types.json": None}),
        ):
            case_dir = Path(tempfile.mkdtemp(dir=tmp))
            data = data_copy(case_dir, replace)
            results.append(run(label, {"MARKLENS_DATA_DIR": str(data)}, key))
            shutil.rmtree(case_dir, ignore_errors=True)
        results += famous_cases(tmp, key, args.old_data)
    (args.out / "probe_startup.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
