"""DB 유사군 백필 — 서지상세(getBibliographyDetailInfoSearch)로 기존 레코드의 빈 유사군을 채운다.

실행 (프로젝트 루트에서. 실호출은 run 뿐이고 plan 계획표를 본 뒤 사람이 결정한다):
    ml/venv/bin/python -m backend.scripts.goods_backfill status          # 류별 보유 현황(호출 0)
    ml/venv/bin/python -m backend.scripts.goods_backfill plan            # 계획표·예산(호출 0)
    KIPRIS_DAILY_BUDGET=400 ml/venv/bin/python -m backend.scripts.goods_backfill run --max-calls 100

대상 = 파일 모드 상표 메타(ml/data/kipris_metadata.json)에서 유사군이 빈 레코드. 류 우선순위
(--classes, 기본은 업종 세트가 쓰는 43·30·35·29·25·3·42)대로 — 레코드의 류 가운데 가장 앞선 순위,
같으면 출원번호 순. --all 이면 우선순위 밖 류도 그 뒤에 붙인다(11월 이후 나머지 백필).

레코드당 1회(kipris_client 리미터·카운터 공유 — 월 KIPRIS_MONTHLY_BUDGET 950·일
KIPRIS_DAILY_BUDGET). 응답 원본은 파싱 전에 raw_kipris/collect/xml/biblio_<출원번호>_<시각>.xml 로
남기고(collect_pipeline enrich_item 과 같은 규약), 원본이 이미 있는 출원번호는 다시 부르지 않는다
(유사군 없음 응답 포함 — 멱등).

쓰기: 유사군 필드만 바꾸고 파일 바이트 형식(들여쓰기 2·줄바꿈 CRLF/LF·끝 줄바꿈)은 원본 그대로다.
이어서 index/kipris_authoritative_keys.json 의 metadata_sha256 → index/kipris_manifest.json 의
source.sha256 을 연쇄 갱신한다(FAISS·이미지 바이트는 그대로). 시작 전에 이 해시 연결이 맞는지
확인하고 어긋나 있으면 호출 없이 멈춘다. 20건마다·예산 소진·중단(Ctrl+C) 때도 그때까지 채운 것은
저장한다.
엔진은 다음 기동 때 자동 반영한다. DB 모드(운영)는 이 뒤 migrate_json_to_db 로 옮긴다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.scripts import collect_pipeline as collect  # noqa: E402
from backend.src.core import kipris_client as kc  # noqa: E402
from backend.src.core import paths  # noqa: E402

DEFAULT_CLASSES = (43, 30, 35, 29, 25, 3, 42)
SAVE_EVERY = 20
MAX_FAILURE_STREAK = 3
META_PATH: Path = paths.TRADEMARK_META_PATH
AUTH_PATH: Path = paths.ML_DATA_DIR / "index" / "kipris_authoritative_keys.json"
MANIFEST_PATH: Path = paths.INDEX_MANIFEST_PATH


class BackfillError(RuntimeError):
    """메타 형식·해시 연결이 맞지 않아 진행할 수 없다(호출 전에 멈춘다)."""


@dataclass
class MetaFile:
    """상표 메타와 원본 바이트 형식(재직렬화가 같은 바이트를 내는지 확인해 둔다)."""

    data: dict
    newline: str
    trailing: bool

    @classmethod
    def load(cls, path: Path) -> MetaFile:
        raw = path.read_bytes()
        newline = "\r\n" if b"\r\n" in raw else "\n"
        meta = cls(json.loads(raw), newline, raw.endswith(newline.encode()))
        if meta.dumps() != raw:
            raise BackfillError(
                f"{path.name} 을 같은 바이트로 다시 쓸 수 없습니다(들여쓰기·인코딩이 다름) — 중단"
            )
        return meta

    def dumps(self) -> bytes:
        text = json.dumps(self.data, ensure_ascii=False, indent=2).replace("\n", self.newline)
        return (text + (self.newline if self.trailing else "")).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def check_chain() -> None:
    """메타 → authoritative keys → manifest 해시 연결이 지금 맞는지 확인한다."""
    authoritative = json.loads(AUTH_PATH.read_bytes())
    manifest = json.loads(MANIFEST_PATH.read_bytes())
    if authoritative.get("metadata_sha256") != collect._sha256_file(META_PATH):  # noqa: SLF001
        raise BackfillError("authoritative keys 의 metadata_sha256 이 상표 메타와 다릅니다 — 중단")
    if manifest.get("source", {}).get("sha256") != collect._sha256_file(AUTH_PATH):  # noqa: SLF001
        raise BackfillError("manifest 의 source.sha256 이 authoritative keys 와 다릅니다 — 중단")


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_bytes()
    if text.count(old.encode()) != 1:
        raise BackfillError(f"{path.name} 에서 이전 해시를 정확히 한 번 찾지 못했습니다")
    _atomic_write(path, text.replace(old.encode(), new.encode()))


def save(meta: MetaFile) -> None:
    """메타를 원본 형식으로 쓰고 해시 연결을 갱신한다(줄 단위 치환이라 두 JSON 의 형식은 그대로)."""
    old_meta = collect._sha256_file(META_PATH)  # noqa: SLF001
    old_auth = collect._sha256_file(AUTH_PATH)  # noqa: SLF001
    _atomic_write(META_PATH, meta.dumps())
    _replace_once(AUTH_PATH, old_meta, collect._sha256_file(META_PATH))  # noqa: SLF001
    _replace_once(MANIFEST_PATH, old_auth, collect._sha256_file(AUTH_PATH))  # noqa: SLF001


def _attempted() -> set[str]:
    """원본 XML 이 이미 있는 출원번호(이전 실행에서 부른 것 — 유사군 없음 응답 포함)."""
    directory = collect.COLLECT_RAW_XML_DIR
    if not directory.exists():
        return set()
    return {path.name.split("_")[1] for path in directory.glob("biblio_*_*.xml")}


def targets(meta: MetaFile, classes: tuple[int, ...], include_rest: bool) -> list[dict]:
    """유사군이 빈 레코드를 류 우선순위 → 출원번호 순으로. 이미 부른 출원번호는 뺀다."""
    rank = {nice: index for index, nice in enumerate(classes)}
    attempted = _attempted()
    chosen: list[tuple[int, str, dict]] = []
    for record in meta.data["trademarks"]:
        if record.get("유사군") or record["출원번호"] in attempted:
            continue
        ranks = [rank[nice] for nice in record.get("류") or [] if nice in rank]
        if ranks:
            chosen.append((min(ranks), record["출원번호"], record))
        elif include_rest:
            chosen.append((len(classes), record["출원번호"], record))
    chosen.sort(key=lambda item: (item[0], item[1]))
    return [record for _, _, record in chosen]


def _first_class(record: dict, classes: tuple[int, ...]) -> str:
    for nice in classes:
        if nice in (record.get("류") or []):
            return str(nice)
    return "그 외"


def counter_note() -> str:
    limiter = kc.limiter
    daily = limiter.daily_budget if limiter.daily_budget > 0 else "무제한"
    return (f"카운터 {limiter.counter_path} — 이번 달 {limiter.used_this_month()}/"
            f"{limiter.monthly_budget}회, 오늘 {limiter.used_today()}/{daily}회")


def budget(max_calls: int) -> int:
    """이번 실행의 실제 상한 = min(--max-calls, 월 잔여, 일 잔여)."""
    limiter = kc.limiter
    month_left = max(0, limiter.monthly_budget - limiter.used_this_month())
    day_left = (max(0, limiter.daily_budget - limiter.used_today())
                if limiter.daily_budget > 0 else month_left)
    return min(max_calls, month_left, day_left)


def cmd_status(_args) -> int:
    meta = MetaFile.load(META_PATH)
    records = meta.data["trademarks"]
    filled = [record for record in records if record.get("유사군")]
    print(f"유사군 보유 {len(filled)}/{len(records)}건")
    for nice in DEFAULT_CLASSES:
        group = [record for record in records if nice in (record.get("류") or [])]
        have = sum(1 for record in group if record.get("유사군"))
        print(f"  {nice:>2}류 {have}/{len(group)}")
    return 0


def _plan(args) -> tuple[MetaFile, list[dict], int]:
    check_chain()
    meta = MetaFile.load(META_PATH)
    queue = targets(meta, args.classes, args.all)
    cap = budget(args.max_calls)
    counts: dict[str, int] = {}
    for record in queue:
        key = _first_class(record, args.classes)
        counts[key] = counts.get(key, 0) + 1
    order = " → ".join(f"{key}류 {value}" if key != "그 외" else f"그 외 {value}"
                       for key, value in counts.items())
    print(f"대상 {len(queue)}건(빈 유사군, 이미 부른 출원번호 제외): {order or '없음'}")
    print(f"{counter_note()} → 이번 실행 상한 {cap}회(--max-calls {args.max_calls})")
    if queue and cap:
        last = queue[min(cap, len(queue)) - 1]
        print(f"이번 실행: {min(cap, len(queue))}건 호출 — 마지막 {last['출원번호']}"
              f"({_first_class(last, args.classes)}류)")
    return meta, queue, cap


def cmd_plan(args) -> int:
    _plan(args)
    return 0


def cmd_run(args) -> int:
    meta, queue, cap = _plan(args)
    queue = queue[:cap]
    if not queue:
        print("부를 대상이 없습니다(대상 0 또는 예산 0).")
        return 0
    filled = empty = failed = dirty = streak = 0
    stopped = ""
    try:
        for done, record in enumerate(queue, 1):
            appno = record["출원번호"]
            try:
                raw = kc.bibliography_detail_raw(appno)
                collect.save_raw_xml(f"biblio_{appno}", raw)  # 파싱 전 원본 선저장
                codes = kc.parse_bibliography_detail(raw)["similarity_codes"]
            except kc.CallBudgetExceeded as exc:
                stopped = str(exc)
                break
            except kc.KiprisConfigError:
                raise
            except kc.KiprisError as exc:
                failed += 1
                streak += 1
                print(f"  [실패] {appno}: {type(exc).__name__}", file=sys.stderr)
                if streak >= MAX_FAILURE_STREAK:  # 네트워크·키 장애로 예산만 태우지 않게
                    stopped = f"{MAX_FAILURE_STREAK}회 연속 실패"
                    break
                continue
            streak = 0
            if codes:
                record["유사군"] = codes
                filled += 1
                dirty += 1
            else:
                empty += 1
            if dirty >= SAVE_EVERY:
                save(meta)
                dirty = 0
            if done % 20 == 0:
                print(f"  {done}/{len(queue)} — 채움 {filled}·유사군 없음 {empty}·실패 {failed}")
    except KeyboardInterrupt:
        stopped = "사용자 중단"
    finally:
        if dirty:
            save(meta)
    total = sum(1 for record in meta.data["trademarks"] if record.get("유사군"))
    print(f"채움 {filled}·유사군 없음 {empty}·실패 {failed} → 유사군 보유 {total}/"
          f"{len(meta.data['trademarks'])}건" + (f" (멈춤: {stopped})" if stopped else ""))
    print(counter_note())
    return 1 if failed else 0


def _classes(value: str) -> tuple[int, ...]:
    items = tuple(int(part) for part in value.split(",") if part.strip())
    if not items or any(not 1 <= item <= 45 for item in items):
        raise argparse.ArgumentTypeError("류는 1~45 정수를 쉼표로 잇습니다")
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="류별 유사군 보유 현황(호출 0)")
    for name in ("plan", "run"):
        command = sub.add_parser(name, help="계획표(호출 0)" if name == "plan" else "실호출")
        command.add_argument("--classes", type=_classes, default=DEFAULT_CLASSES,
                             help="류 우선순위(쉼표, 기본 43,30,35,29,25,3,42)")
        command.add_argument("--all", action="store_true", help="우선순위 밖 류도 뒤에 붙인다")
        command.add_argument("--max-calls", type=int, default=100, help="하드캡(기본 100)")
    args = parser.parse_args(argv)
    handler = {"status": cmd_status, "plan": cmd_plan, "run": cmd_run}[args.command]
    try:
        return handler(args)
    except (BackfillError, kc.KiprisConfigError) as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
