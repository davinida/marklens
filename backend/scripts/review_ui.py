"""심결례 사람 검토용 로컬 웹 화면(개발 전용) — 터미널 명령 대신 브라우저에서 카드 단위로 결정한다.

실행 (프로젝트 루트에서, KIPRIS 호출 0):
    ml/venv/bin/python -m backend.scripts.review_ui [--port 8010] [--data-dir ml/data/trials]
    → http://127.0.0.1:8010 (127.0.0.1 에만 바인드. 서비스 코드·인증·Turnstile 과 무관)

원칙
- 저장은 반드시 backend/scripts/trials_collect.py 의 기존 함수를 거친다(apply_label·confirm_labels·
  apply_name_b, 사람 열 보존·프로세스 간 잠금). 라벨 CSV 를 따로 쓰지 않는다.
- 입력: review --bundle 산출물(review_bundle/*.csv), labels.csv, text/{심판번호}.txt,
  images/{심판번호}/*.png, image_pairs_v1.csv(이미지 쌍 연결), shared/distinctiveness/
  descriptive_terms.json·weak_tokens.json. 기술적 표장 승인은 descriptive_terms.json 의 approved
  (해제는 approved false + rejected true), 약한 토큰 해제는 weak_token_overrides.json 에 기록하며
  둘 다 ml/src/axes/distinctiveness.py 의 갱신 함수를 쓴다. 식별력 하락·명칭 검토 결정은
  review_decisions.json(JSON, 라벨 아님)에 남긴다.
- 단일 HTML(인라인 JS, 외부 CDN 없음) + JSON API. 파일 경로는 심판번호·역할 정규식으로 검증한다.

API
    GET  /                      화면(HTML)
    GET  /api/bundle/{name}     verify_queue | ab_disagree | name_review | distinct_drop |
                                weak_tokens_top200 | descriptive — 카드 목록 + 진행률
    POST /api/decide            {tab, 심판번호, b, action: confirm|label|undo|name_b|decision|
                                approve|override, …}
    GET  /img/{심판번호}/{role}  images/{심판번호}/{role}.png (role: this|prior_N|target[_N][_fig])
    GET  /api/status            trials_collect 의 status 집계(라벨 진행·일치율·검토 묶음 처리 수)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ML_ROOT = PROJECT_ROOT / "ml"
for root in (PROJECT_ROOT, ML_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from src.axes import distinctiveness as dx  # noqa: E402

from backend.scripts import trials_collect as tc  # noqa: E402

DEFAULT_PORT = 8010
HOST = "127.0.0.1"
TRIAL_RE = re.compile(r"^\d{10,13}$")
ROLE_RE = re.compile(r"^(?:this|prior_\d{1,2}|target(?:_\d{1,2})?)(?:_fig)?$")
BUNDLE_TABS = ("verify_queue", "ab_disagree", "name_review", "distinct_drop", "weak_tokens_top200")
TABS = (
    ("verify_queue", "표본"), ("ab_disagree", "A≠B"), ("name_review", "명칭 검토"),
    ("distinct_drop", "식별력 하락"), ("descriptive", "기술적 표장"),
    ("weak_tokens_top200", "약한 토큰"),
)
NAME_SOURCES = (("kipris", "상대표장_명칭_kipris"), ("llm", "상대표장_명칭_llm"),
                ("본문", "상대표장_명칭_본문"), ("ocr", "상대표장_명칭_ocr"))
DECISIONS = ("결합 규칙 후보", "그대로")


@dataclass
class ReviewConfig:
    base: Path
    descriptive_path: Path = dx.DEFAULT_DESCRIPTIVE_PATH
    weak_path: Path = dx.DEFAULT_DIR / "weak_tokens.json"
    overrides_path: Path = dx.DEFAULT_OVERRIDES_PATH
    kinds_config: Path = tc.KINDS_CONFIG_PATH

    @property
    def paths(self) -> tc.TrialPaths:
        return tc.TrialPaths(self.base)

    @property
    def decisions_path(self) -> Path:
        return self.base / "review_decisions.json"

    @property
    def image_pairs_path(self) -> Path:
        return self.base / "image_pairs_v1.csv"


@dataclass
class _Cache:
    texts: dict[str, dict] = field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_trial(number: str) -> str:
    if not TRIAL_RE.match(number or ""):
        raise HTTPException(400, f"심판번호 형식이 아닙니다: {number!r}")
    return number


def name_b(row: dict) -> tuple[str, str]:
    """pairs_features 와 같은 우선순위: kipris > llm > 본문 > ocr."""
    for source, column in NAME_SOURCES:
        value = (row.get(column) or "").strip()
        if value:
            return value, source
    return "", ""


class ReviewService:
    """파일 읽기·카드 구성·결정 저장. 쓰기는 trials_collect / distinctiveness 함수만 부른다."""

    def __init__(self, config: ReviewConfig) -> None:
        self.config = config
        self.cache = _Cache()

    # ---- 읽기 ----
    def label_rows(self) -> list[dict]:
        path = self.config.paths.labels_csv
        return tc._read_csv(path) if path.exists() else []

    def label_row(self, number: str, b: str, rows: list[dict] | None = None) -> dict:
        rows = self.label_rows() if rows is None else rows
        for row in rows:
            if row.get("심판번호") == number and (not b or (row.get("상표B_번호") or "") == b):
                return row
        return {}

    def text_analysis(self, number: str) -> dict:
        if number in self.cache.texts:
            return self.cache.texts[number]
        path = self.config.paths.text_dir / f"{number}.txt"
        if not path.exists():
            result = {"주문": "", "판단절": "", "텍스트": False}
        else:
            text = path.read_text(encoding="utf-8")
            analysis = tc.analyze_text(text)
            marks = tc.fallback_marks(text, analysis)
            result = {
                "주문": analysis.get("주문", ""), "판단절": tc.judgment_text(text, marks),
                "텍스트": True, "주문결과": analysis.get("주문결과", ""),
            }
        self.cache.texts[number] = result
        return result

    def image_roles(self, number: str, b: str, kind: str) -> dict[str, str | None]:
        """이미지 쌍 CSV(image_pairs_v1.csv)의 연결을 우선, 없으면 파일 존재로 추정."""
        folder = self.config.paths.base / "images" / number
        pairs_path = self.config.image_pairs_path
        role_a, role_b = "this", None
        if pairs_path.exists():
            for row in tc._read_csv(pairs_path):
                if row.get("심판번호") != number:
                    continue
                if b and (row.get("상대번호") or "") not in ("", b):
                    continue
                role_a = Path(row.get("이미지A") or "this.png").stem
                role_b = Path(row.get("이미지B") or "").stem or None
                break
        if role_b is None:
            role_b = "target" if kind.startswith("권리범위확인") else "prior_1"
        out: dict[str, str | None] = {}
        for side, role in (("A", role_a), ("B", role_b)):
            ok = (bool(role) and ROLE_RE.match(role) is not None
                  and (folder / f"{role}.png").exists())
            out[side] = f"/img/{number}/{role}" if ok else None
        return out

    def card(self, row: dict, rows: list[dict]) -> dict:
        number = row.get("심판번호", "")
        b = row.get("상표B_번호") or row.get("상대번호") or ""
        label = self.label_row(number, b, rows)
        kind = label.get("종류") or row.get("종류") or ""
        name, source = name_b(label)
        analysis = self.text_analysis(number) if TRIAL_RE.match(number or "") else {}
        images = self.image_roles(number, b, kind) if TRIAL_RE.match(number or "") else {}
        return {
            **row, "b": b, "종류": kind, "이름A": label.get("상표A_명칭", ""), "이름B": name,
            "이름B_출처": source, "명칭_llm": label.get("상대표장_명칭_llm", ""),
            "명칭_본문": label.get("상대표장_명칭_본문", ""),
            "명칭_ocr": label.get("상대표장_명칭_ocr", ""),
            "명칭_kipris": label.get("상대표장_명칭_kipris", ""),
            "llm_a": {"판정": label.get("유사여부_확정", ""),
                      "판단축": label.get("판단축_확정", ""),
                      "확신도": label.get("확신도", ""), "근거": label.get("근거문장", ""),
                      "제외사유": label.get("제외사유", ""),
                      "상표유형": label.get("상표유형_확정", "")},
            "llm_b": {"판정": label.get("llm_b_유사여부", ""),
                      "판단축": label.get("llm_b_판단축", ""),
                      "확신도": label.get("llm_b_확신도", ""), "근거": label.get("llm_b_근거", "")},
            "라벨출처": label.get("라벨출처", ""), "확인여부": label.get("확인여부", ""),
            "llm_판정_원본": label.get("llm_판정_원본", ""), "메모": label.get("메모", ""),
            "주문": analysis.get("주문", ""), "판단절": analysis.get("판단절", ""),
            "텍스트": analysis.get("텍스트", False), "이미지": images,
        }

    def bundle(self, name: str) -> dict:
        if name == "descriptive":
            return self.descriptive_bundle()
        if name not in BUNDLE_TABS:
            raise HTTPException(404, f"모르는 묶음: {name}")
        path = self.config.paths.review_bundle_dir / f"{name}.csv"
        rows = tc._read_csv(path) if path.exists() else []
        if name == "weak_tokens_top200":
            excluded = dx.read_weak_overrides(self.config.overrides_path)
            kept = self._overrides().get("kept", {})
            items = [{**row, "key": tc._bundle_key(row), "excluded": row["토큰"] in excluded,
                      "kept": row["토큰"] in kept} for row in rows]
        else:
            labels = self.label_rows()
            items = [{**self.card(row, labels), "key": tc._bundle_key(row)} for row in rows]
            if name == "distinct_drop":
                decisions = self._decisions().get("distinct_drop", {})
                for item in items:
                    item["결정"] = decisions.get(item["key"], {})
        done = sum(1 for r in rows if (r.get(tc.BUNDLE_DONE) or "").strip())
        return {"name": name, "items": items, "progress": {"done": done, "total": len(rows)},
                "exists": path.exists()}

    def descriptive_bundle(self) -> dict:
        path = self.config.descriptive_path
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"terms": {}}
        terms = data.get("terms", {})
        items = []
        for token, item in terms.items():
            items.append({
                "토큰": token, "kind": item.get("kind", ""), "absolute": bool(item.get("absolute")),
                "classes": item.get("classes"), "note": item.get("note", ""),
                "examples": item.get("examples", []), "approved": bool(item.get("approved")),
                "rejected": bool(item.get("rejected")),
            })
        order = {kind: index for index, kind in enumerate(dx.DESCRIPTIVE_KINDS)}
        items.sort(key=lambda t: (0 if t["absolute"] else 1, order.get(t["kind"], 99), t["토큰"]))
        groups: list[dict] = []
        for item in items:
            name = "절대어" if item["absolute"] else item["kind"]
            if not groups or groups[-1]["name"] != name:
                groups.append({"name": name, "items": []})
            groups[-1]["items"].append(item)
        done = sum(1 for t in items if t["approved"] or t["rejected"])
        return {"name": "descriptive", "groups": groups, "items": items,
                "progress": {"done": done, "total": len(items)}, "exists": path.exists()}

    def _decisions(self) -> dict:
        path = self.config.decisions_path
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _overrides(self) -> dict:
        path = self.config.overrides_path
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def status_lines(self) -> list[str]:
        paths_ = self.config.paths
        rows = self.label_rows()
        lines: list[str] = []
        if rows:
            lines.append(tc.curation_progress(rows))
            queue = tc._read_csv(paths_.curation_queue) if paths_.curation_queue.exists() else []
            lines.extend(tc.label_summary(rows, queue))
        progress = tc.bundle_progress(paths_)
        if progress:
            lines.append("검토 묶음(처리/행): " + " · ".join(
                f"{name} {done}/{total}" for name, done, total in progress
            ))
        return lines

    # ---- 쓰기 ----
    def _mark(self, tab: str, key: str, value: str) -> None:
        if tab in BUNDLE_TABS and key:
            tc.mark_bundle_done(self.config.paths, tab, key, value)

    def _record(self, tab: str, key: str, payload: dict) -> None:
        path = self.config.decisions_path
        data = self._decisions()
        data.setdefault(tab, {})[key] = {**payload, "at": _now()}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def decide(self, body: dict) -> dict:
        action = body.get("action", "")
        tab = body.get("tab", "")
        if action in ("approve", "override"):
            return self._decide_tokens(action, body)
        number = _check_trial(str(body.get("심판번호", "")))
        b = str(body.get("b") or "") or None
        key = str(body.get("key") or "")
        paths_ = self.config.paths
        try:
            with tc._labels_lock(paths_):
                fieldnames, rows = tc._load_labels(paths_)
                if action == "confirm":
                    count = tc.confirm_labels(rows, number, b)
                    message = f"승인 {count}행"
                elif action == "label":
                    message = self._label(rows, number, b, body)
                elif action == "undo":
                    changed = tc.apply_label(rows, number, "", source="human", b=b, undo=True)
                    message = f"라벨 비움 {len(changed)}행"
                elif action == "name_b":
                    changed = tc.apply_name_b(
                        rows, number, str(body.get("name") or ""), b=b,
                        memo=(body.get("memo") or None), source="human",
                    )
                    message = f"명칭 기록 {len(changed)}행"
                elif action == "decision":
                    decision = str(body.get("decision") or "")
                    if decision not in DECISIONS:
                        raise tc.LabelError(f"결정은 {'|'.join(DECISIONS)} 중 하나")
                    self._record(tab or "distinct_drop", key, {
                        "심판번호": number, "b": b or "", "decision": decision,
                        "memo": str(body.get("memo") or ""),
                    })
                    message = f"결정 기록: {decision}"
                    rows = None  # 라벨은 손대지 않는다
                else:
                    raise HTTPException(400, f"모르는 action: {action}")
                if rows is not None and action != "decision":
                    tc._write_csv_atomic(paths_.labels_csv, fieldnames, rows)
        except tc.LabelError as error:
            raise HTTPException(409, str(error)) from error
        if action == "undo":
            self._mark(tab, key, "")
        else:
            self._mark(tab, key, f"{action} {_now()}")
        if action == "name_b":
            name = " ".join(str(body.get("name") or "").split())
            self._record("name_review", key, {"심판번호": number, "b": b or "", "name": name})
        return {"ok": True, "message": message, "card": self.refresh_card(tab, number, b or "")}

    def _label(self, rows: list[dict], number: str, b: str | None, body: dict) -> str:
        verdict = str(body.get("verdict") or "")
        current = self.label_row(number, b or "", rows)
        axis = body.get("axis")
        axis = current.get("판단축_확정", "") if axis is None else str(axis)
        evidence = (str(body.get("evidence") or "") or current.get("근거문장", "")
                    or "검토 화면에서 확정")
        confidence = str(body.get("confidence") or "") or current.get("확신도", "") or "high"
        reason = str(body.get("reason") or "") if verdict == "제외" else ""
        memo = body.get("memo")
        changed = tc.apply_label(
            rows, number, verdict, axis=axis, mark_type=current.get("상표유형_확정", ""),
            reason=reason, memo=(None if memo is None else str(memo)), b=b, source="human",
            evidence=evidence, confidence=confidence,
        )
        return f"라벨 {verdict} {len(changed)}행"

    def refresh_card(self, tab: str, number: str, b: str) -> dict:
        rows = self.label_rows()
        base = {"심판번호": number}
        if tab == "distinct_drop":
            base["상대번호"] = b
        else:
            base["상표B_번호"] = b
        card = self.card(base, rows)
        card["key"] = tc._bundle_key(base)
        bundle_path = self.config.paths.review_bundle_dir / f"{tab}.csv"
        if bundle_path.exists():
            for row in tc._read_csv(bundle_path):
                if tc._bundle_key(row) == card["key"]:
                    card[tc.BUNDLE_DONE] = row.get(tc.BUNDLE_DONE, "")
        if tab == "distinct_drop":
            card["결정"] = self._decisions().get("distinct_drop", {}).get(card["key"], {})
        return card

    def _decide_tokens(self, action: str, body: dict) -> dict:
        if action == "approve":
            approvals = body.get("approvals") or {}
            if not isinstance(approvals, dict):
                raise HTTPException(400, "approvals 는 {토큰: true|false}")
            result = dx.update_descriptive_approvals(
                {str(k): bool(v) for k, v in approvals.items()}, self.config.descriptive_path,
                memo=str(body.get("memo") or ""),
            )
            message = f"승인 {result['승인']} · 해제 {result['해제']}"
            return {"ok": True, "message": message, **result}
        excluded = [str(t) for t in (body.get("excluded") or [])]
        kept = [str(t) for t in (body.get("kept") or [])]
        result = dx.update_weak_overrides(excluded, kept, self.config.overrides_path,
                                          memo=str(body.get("memo") or ""))
        stamp = _now()
        for token in excluded + kept:
            self._mark("weak_tokens_top200", f"|||{token}", f"override {stamp}")
        return {"ok": True, "message": f"제외 {len(excluded)} · 유지 {len(kept)}", **result}


HTML_PATH = Path(__file__).with_name("review_ui.html")  # 단일 페이지(인라인 JS, 외부 CDN 없음)


def page_html() -> str:
    html = HTML_PATH.read_text(encoding="utf-8")
    return (html.replace("__TABS__", json.dumps(TABS, ensure_ascii=False))
            .replace("__REASONS__", json.dumps(list(tc.EXCLUDE_REASONS), ensure_ascii=False)))


def create_app(config: ReviewConfig) -> FastAPI:
    service = ReviewService(config)
    app = FastAPI(title="MarkLens 심결례 검토(개발 전용)", docs_url=None, redoc_url=None)
    app.state.service = service

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return page_html()

    @app.get("/api/bundle/{name}")
    def bundle(name: str) -> JSONResponse:
        return JSONResponse(service.bundle(name))

    @app.post("/api/decide")
    def decide(body: dict) -> JSONResponse:
        return JSONResponse(service.decide(body))

    @app.get("/img/{number}/{role}")
    def image(number: str, role: str) -> FileResponse:
        _check_trial(number)
        if not ROLE_RE.match(role):
            raise HTTPException(400, f"역할 형식이 아닙니다: {role!r}")
        path = config.paths.base / "images" / number / f"{role}.png"
        if not path.exists():
            raise HTTPException(404, "이미지 없음")
        return FileResponse(path, media_type="image/png")

    @app.get("/api/status")
    def status() -> JSONResponse:
        return JSONResponse({"lines": service.status_lines()})

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--data-dir", type=Path, default=tc.DEFAULT_PATHS.base)
    parser.add_argument("--descriptive", type=Path, default=dx.DEFAULT_DESCRIPTIVE_PATH)
    parser.add_argument("--overrides", type=Path, default=dx.DEFAULT_OVERRIDES_PATH)
    args = parser.parse_args(argv)
    import uvicorn

    config = ReviewConfig(base=args.data_dir, descriptive_path=args.descriptive,
                          overrides_path=args.overrides)
    print(f"MarkLens 검토 화면: http://{HOST}:{args.port}  (데이터 {config.base}, Ctrl+C 로 종료)")
    uvicorn.run(create_app(config), host=HOST, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
