"""개발 콘솔 「업데이트 내역」: 저장소의 deploy/updates.jsonl(한 줄 = 실서버에 올린 판 하나)을 새것부터 읽는다.

- 실서버는 git 작업 폴더(worktree)에서 돌므로 기록 파일은 그 커밋과 함께 실린다 — 경로는 저장소 뿌리 기준.
- 「지금 실서버 판」은 서버가 켤 때 한 번 읽은 자기 커밋(`git rev-parse --short HEAD`, 2초, 셸 없음). 못 읽으면 None.
- 모양이 틀린 줄은 건너뛴다. 파일이 MAX_BYTES 보다 크면 끝부분만 읽고, 많아야 MAX_ENTRIES 판.
"""

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.programs.devconsole.schemas import UpdateEntryOut, UpdateItemOut, UpdatesOut

REPO_ROOT = Path(__file__).resolve().parents[4]
UPDATES_FILE = REPO_ROOT / "deploy" / "updates.jsonl"
MAX_ENTRIES = 200
MAX_BYTES = 1_000_000
_SHA = re.compile(r"^[0-9a-f]{4,40}$")
KINDS = ("added", "fixed", "safety")


def read_running_commit() -> str | None:
    """이 서버 코드의 git HEAD 짧은 커밋. git 이 없거나 저장소가 아니거나 2초를 넘기면 None."""
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = done.stdout.strip() if done.returncode == 0 else ""
    return sha if _SHA.match(sha) else None


RUNNING_COMMIT: str | None = read_running_commit()  # 켤 때 한 번(라우터를 불러올 때)


def _item(raw: Any) -> UpdateItemOut | None:
    if isinstance(raw, str) and raw.strip():
        return UpdateItemOut(text=raw.strip())
    if isinstance(raw, dict) and isinstance(raw.get("text"), str) and raw["text"].strip():
        note = raw.get("note")
        if note is not None and not isinstance(note, str):
            return None
        return UpdateItemOut(text=raw["text"].strip(), note=note or None)
    return None


def _entry(line: str) -> UpdateEntryOut | None:
    """한 줄 → 판 하나. 모양이 틀리면 None(건너뜀)."""
    try:
        raw = json.loads(line)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    at, commit, title, notice = raw.get("at"), raw.get("commit"), raw.get("title"), raw.get("notice")
    if not (isinstance(at, str) and isinstance(commit, str) and _SHA.match(commit) and isinstance(title, str) and title.strip()):
        return None
    if notice is not None and not isinstance(notice, str):
        return None
    try:
        when = datetime.fromisoformat(at)
    except ValueError:
        return None
    if when.tzinfo is None:
        return None
    lists: dict[str, list[UpdateItemOut]] = {}
    for kind in KINDS:
        values = raw.get(kind, [])
        if not isinstance(values, list):
            return None
        items = [_item(v) for v in values]
        if any(i is None for i in items):
            return None
        lists[kind] = [i for i in items if i is not None]
    try:
        return UpdateEntryOut(at=when, commit=commit, title=title.strip(), notice=notice or None, **lists)
    except ValidationError:
        return None


def _lines(path: Path) -> list[str]:
    try:
        with path.open("rb") as f:
            size = f.seek(0, 2)
            start = max(0, size - MAX_BYTES - 1)
            f.seek(start)
            data = f.read()
    except OSError:
        return []
    if start > 0:  # 끝부분만 읽었으면 첫 줄바꿈까지(잘린 줄)는 버린다
        data = data[data.find(b"\n") + 1 :] if b"\n" in data else b""
    return data.decode("utf-8", errors="replace").splitlines()


def listing() -> UpdatesOut:
    entries = [e for e in (_entry(line) for line in _lines(UPDATES_FILE) if line.strip()) if e is not None]
    entries.sort(key=lambda e: e.at, reverse=True)
    return UpdatesOut(entries=entries[:MAX_ENTRIES], running_commit=RUNNING_COMMIT)
