"""저장소·커밋 이력에서 키·.env 흔적을 찾는다 — 값은 출력하지 않는다. 걸린 줄은 "커밋 · 파일 · 줄"
위치와 값의 모양(대문자 A·소문자 a·숫자 9 로 가린 것)·길이만 낸다.

    ml/venv/bin/python scripts/robustness/scan_secrets.py [출력 파일]

값이 다른 변수 이름(대문자·밑줄만)이거나 자리표시(example·dummy·your…·xxx)면 오탐으로 따로 센다.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELF = "scripts/robustness/scan_secrets.py"
PATTERNS = {
    "KIPRIS 키": r"KIPRIS_[A-Z_]*KEY\s*[=:]\s*['\"]?([A-Za-z0-9+/=_-]{16,})",
    "Turnstile 비밀": r"TURNSTILE_SECRET[A-Z_]*\s*[=:]\s*['\"]?([A-Za-z0-9_.-]{16,})",
    "MarkLens API 키": r"MARKLENS_(?:BACKEND_)?API_KEY\s*[=:]\s*['\"]?([A-Za-z0-9_-]{24,})",
    "질의의 accessKey·ServiceKey": r"(?:accessKey|ServiceKey)=([A-Za-z0-9%+/=_-]{16,})",
    "개인 키 머리": r"(-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    "AWS 접근 키": r"(AKIA[0-9A-Z]{16})",
    "GitHub 토큰": r"(ghp_[A-Za-z0-9]{36})",
}
PLACEHOLDER = re.compile(
    r"(example|dummy|placeholder|your|xxxx|changeme|test|fake|robustness|ci-only|"
    r"not-used|<|\$\{)",
    re.I,
)
CLOUDFLARE_TEST = re.compile(r"[123]x0{30,}AA")  # Cloudflare 가 문서로 공개한 Turnstile 시험 키


def shape(value: str) -> str:
    return re.sub(r"[a-z]", "a", re.sub(r"[A-Z]", "A", re.sub(r"[0-9]", "9", value)))


def classify(value: str) -> str:
    if re.fullmatch(r"[A-Z_]+=?", value):
        return "오탐(다른 변수 이름)"
    if PLACEHOLDER.search(value):
        return "오탐(자리표시)"
    if CLOUDFLARE_TEST.fullmatch(value):
        return "오탐(Cloudflare 공개 시험 키)"
    return "확인 필요"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, errors="replace"
    ).stdout


def scan_text(text: str):
    for number, line in enumerate(text.splitlines(), 1):
        for label, pattern in PATTERNS.items():
            for match in re.finditer(pattern, line):
                value = match.group(1)
                yield number, label, classify(value), shape(value)[:40], len(value)


def main() -> int:
    out = []
    out.append("# 비밀값 흔적 검색 — 값은 출력하지 않음(모양·길이만)")
    out.append("## 지금 추적 파일")
    files = [f for f in git("ls-files").splitlines() if f != SELF]
    current = 0
    for name in files:
        path = ROOT / name
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, label, kind, value_shape, length in scan_text(text):
            out.append(f"- {name}:{number} · {label} · {kind} · 모양 {value_shape} · 길이 {length}")
            current += 1
    if not current:
        out.append("(없음)")
    out.append("## 커밋 이력(모든 브랜치의 추가된 줄)")
    history = 0
    combined = "|".join(f"(?:{p})" for p in PATTERNS.values())
    commits = git(
        "log",
        "--all",
        "-G",
        r"KIPRIS_[A-Z_]*KEY|TURNSTILE_SECRET|API_KEY|accessKey=|ServiceKey=|"
        r"PRIVATE KEY|AKIA|ghp_",
        "--format=%h",
    ).split()
    for commit in commits:
        diff = git("show", commit, "--format=", "--unified=0", "--no-color", "--", ".", f":!{SELF}")
        current_file = ""
        for line in diff.splitlines():
            if line.startswith("+++ "):
                current_file = line[6:] if line.startswith("+++ b/") else line[4:]
                continue
            if not line.startswith("+") or not re.search(combined, line):
                continue
            for _, label, kind, value_shape, length in scan_text(line[1:]):
                out.append(
                    f"- {commit} · {current_file} · {label} · {kind} · 모양 {value_shape} "
                    f"· 길이 {length}"
                )
                history += 1
    if not history:
        out.append("(없음)")
    out.append("## .env 계열 파일이 커밋된 적(이름만, 예시 파일 제외)")
    added = git("log", "--all", "--format=", "--name-only", "--diff-filter=A")
    env_files = sorted(
        {
            f
            for f in added.splitlines()
            if re.search(r"(^|/)\.env", f) and not f.endswith((".example",))
        }
    )
    out.append(", ".join(env_files) if env_files else "(없음)")
    out.append("## .gitignore 가 .env 를 막는지")
    for path in (".env", "frontend/.env.local", "backend/.env", "ml/data/x.env"):
        ignored = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0
        out.append(f"- {path}: {'무시됨' if ignored else '무시 안 됨(주의)'}")
    text = "\n".join(out) + "\n"
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
