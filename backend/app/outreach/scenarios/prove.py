"""모래상자 자식 프로세스(Task 98 · 리뷰 판정 12): 개발 콘솔 「연락 하네스」 격자의 칸 하나를 **진짜** 하네스로 돌린다.

    CHRONOS_HARNESS_SANDBOX=1 python -m app.outreach.scenarios.prove <rule_id> [--broken]
    CHRONOS_HARNESS_SANDBOX=1 python -m app.outreach.scenarios.prove --layout

- 서버(devconsole.outreach_catalog)가 칸마다 이 프로세스를 띄운다 — 새 임시 data 폴더, 비밀 없는 환경, 30초 제한.
  가짜 통로·음성·글 세션·LLM 은 **이 프로세스 안에서만** 끼우고(registry.pinned 등은 이 변수가 있어야 열린다), 문·도구·
  뒤 확인·받기 판정은 진짜(grid.run_cell → drive_text / drive_voice). DB 는 그 실행의 임시 파일(drive_text.temp_database).
- rule_id: `S-07@call_in`(상황@열 — 설계 표에서 「—」 인 칸은 없음) · `C-V1`(채널에만 있는 것: V 통화 · S 문자 · K 카카오톡,
  grid.CHANNEL_ONLY 의 매체별 차례). `--broken` 은 그 칸을 지키는 곳(Situation.guards[열]) 하나를 그 실행 안에서만 무른다.
- `--layout` 은 격자의 모양(줄·칸 표시·지키는 곳·칸 말)만 — 아무것도 돌리지 않는다.
- 표준 출력에 JSON 한 줄(ASCII). 모든 글은 redact.hide_phones 를 거치고, 출력은 OUTPUT_CAP 바이트 안(넘으면 사건을 덜어 낸다).
  종료 코드: 0 결과 · 2 모래상자 밖·틀린 인자 · 3 지키는 곳이 없는 칸의 --broken · 1 돌리다 터짐(종류만)·출력이 너무 큼.
- `--broken` 은 같은 자식 안에서 그냥 돌리기(기준)도 먼저 돌려 `baseline: {passed, checks}` 로 싣는다.
"""

import argparse
import asyncio
import json
import os
import re
import sys
from typing import Any

from app.outreach import redact
from app.outreach.harness.registry import SANDBOX_ENV

OUTPUT_CAP = 200_000  # 바이트 — 서버의 읽기 상한(outreach_catalog.OUTPUT_CAP)보다 작게
DETAIL_CHARS = 200  # 사건 detail 은 이만큼까지
MEDIUM_LETTER = {"call": "V", "sms": "S", "kakao": "K"}
DIVERGED = "하네스가 갈라짐"  # situations.DIVERGED_* 의 머리
COMMON_ONLY = "공통 겹만"  # situations.COMMON_ONLY · VOICE_COMMON_ONLY 등의 머리
_CELL = re.compile(r"S-\d{2}@[a-z_]+")
_CASE = re.compile(r"C-[A-Z]\d{1,2}")


def case_ids() -> dict[str, str]:
    """C-<매체 글자><차례> → 경우 id(grid.CHANNEL_ONLY 의 매체별 차례)."""
    from app.outreach.scenarios.grid import CHANNEL_ONLY

    counts: dict[str, int] = {}
    out = {}
    for case in CHANNEL_ONLY:
        counts[case.medium] = counts.get(case.medium, 0) + 1
        out[f"C-{MEDIUM_LETTER[case.medium]}{counts[case.medium]}"] = case.id
    return out


def parse(rule_id: str) -> tuple[str, str, str]:
    """("cell", 상황 id, 열) | ("case", 경우 id, 열). 표에 없는 칸·모양이 틀린 id 는 ValueError."""
    from app.outreach.scenarios.grid import _CASES, CELLS, case_column

    if _CELL.fullmatch(rule_id):
        sid, column = rule_id.split("@")
        if CELLS.get((sid, column), "none") != "none":
            return "cell", sid, column
    elif _CASE.fullmatch(rule_id) and rule_id in case_ids():
        case_id = case_ids()[rule_id]
        return "case", case_id, case_column(_CASES[case_id])
    raise ValueError("격자에 없는 칸입니다")


def _situation(kind: str, key: str):
    from app.outreach.scenarios.grid import _BY_ID, _CASES

    return _BY_ID[key] if kind == "cell" else _CASES[key].situation


def note_kind(note: str | None) -> str | None:
    """칸 말의 종류 — 화면이 「운영 동작이 아님」을 가려 보이게: simulated · diverged · common_only · design_diff."""
    from app.outreach.scenarios import situations as s

    if not note:
        return None
    if note.startswith(s.SIMULATED_ONLY):
        return "simulated"
    if note.startswith(DIVERGED):  # 격자의 지금 갈라진 칸(상수 목록이 아니라 note 머리 — 칸이 바뀌어도 따라간다)
        return "diverged"
    if note.startswith(COMMON_ONLY):
        return "common_only"
    return "design_diff"


def _cell(situation, column: str) -> dict[str, Any]:
    note = situation.notes.get(column)
    return {"mark": situation.marks[column], "runnable": situation.marks[column] != "none",
            "guard": situation.guards.get(column), "note": note, "note_kind": note_kind(note)}


def layout() -> dict[str, Any]:
    """격자의 모양 — 설계 표의 줄(S-01…S-24) × 네 열, 그리고 채널에만 있는 것."""
    from app.outreach.scenarios.grid import _CASES, case_column
    from app.outreach.scenarios.situations import COLUMNS, SITUATIONS

    rows = [{"id": s.id, "title": s.title, "refs": list(s.refs), "cells": {c: _cell(s, c) for c in COLUMNS}}
            for s in SITUATIONS]
    only = []
    for cid, case_id in case_ids().items():
        case = _CASES[case_id]
        column = case_column(case)
        only.append({"id": cid, "case": case.id, "title": case.title, "medium": case.medium, "refs": list(case.refs),
                     "column": column, **_cell(case.situation, column)})
    return {"columns": list(COLUMNS), "rows": rows, "channel_only": only}


class NoGuard(Exception):
    """그 칸에는 무를 지키는 곳이 없다(공통 겹만 · 구조로만 지킴)."""


async def run(rule_id: str, broken: bool) -> dict[str, Any]:
    from app.outreach.scenarios import grid

    kind, key, column = parse(rule_id)
    guard = _situation(kind, key).guards.get(column)
    if broken and guard is None:
        raise NoGuard(rule_id)

    async def once(off: bool):
        return await (grid.run_cell(key, column, broken=off) if kind == "cell" else grid.run_case(key, broken=off))

    # 가드 끄고 돌리기는 같은 자식 안에서 그냥 돌리기(기준)도 먼저 — 그냥 돌려도 실패하는 칸은 가드의 증거가 아니다
    baseline = await once(False) if broken else None
    result = await once(broken)
    out = {
        "rule_id": rule_id, "column": column, "passed": result.passed, "broken_guard": guard if broken else None,
        "checks": [{"text": c["text"], "ok": c["ok"], "guarded": bool(c.get("guarded")), "error": c.get("error")}
                   for c in result.checks],
        "events": [{"ref": e["ref"], "rule": e["rule"], "verdict": e["verdict"],
                    "detail": None if e.get("detail") is None else str(e["detail"])[:DETAIL_CHARS]} for e in result.events],
        "note": result.note, "sessions": list(result.sessions), "channel": result.channel,
    }
    if baseline is not None:
        out["baseline"] = {"passed": baseline.passed, "checks": [
            {"text": c["text"], "ok": c["ok"], "guarded": bool(c.get("guarded"))} for c in baseline.checks]}
    return out


def _hidden(value: Any) -> Any:
    if isinstance(value, str):
        return redact.hide_phones(value)
    if isinstance(value, list):
        return [_hidden(v) for v in value]
    if isinstance(value, dict):
        return {k: _hidden(v) for k, v in value.items()}
    return value


def dump(out: dict[str, Any]) -> str:
    """번호를 지운 JSON 한 줄. OUTPUT_CAP 을 넘으면 사건을 뒤에서부터 덜어 내고 덜어 낸 수를 적는다."""
    out = _hidden(out)
    text = json.dumps(out)
    events = list(out.get("events") or [])
    dropped = 0
    while len(text.encode()) > OUTPUT_CAP and events:
        cut = max(1, len(events) // 2)
        events, dropped = events[:-cut], dropped + cut
        text = json.dumps({**out, "events": events, "events_omitted": dropped})
    return text if len(text.encode()) <= OUTPUT_CAP else json.dumps({"error": "too_large"})


def _emit(out: dict[str, Any]) -> int:
    """한 줄을 내고, 그 줄이 오류(too_large)면 0 이 아닌 종료 코드."""
    text = dump(out)
    print(text)
    return 1 if "error" in json.loads(text) else 0


def main(argv: list[str] | None = None) -> int:
    if os.environ.get(SANDBOX_ENV) != "1":
        print(f"이 실행기는 모래상자 프로세스({SANDBOX_ENV}=1)에서만 돕니다", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(prog="prove")
    parser.add_argument("rule_id", nargs="?")
    parser.add_argument("--broken", action="store_true")
    parser.add_argument("--layout", action="store_true")
    args = parser.parse_args(argv)
    if args.layout:
        return _emit(layout())
    try:
        parse(args.rule_id or "")
    except ValueError:
        print(json.dumps({"error": "unknown_cell"}))
        return 2
    try:
        return _emit(asyncio.run(run(args.rule_id, args.broken)))
    except NoGuard:
        print(json.dumps({"error": "no_guard"}))
        return 3
    except Exception as exc:  # noqa: BLE001 — 종류만 넘긴다(글에 무엇이 들었는지 모른다)
        print(json.dumps({"error": "crashed", "kind": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
