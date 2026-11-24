"""개발 콘솔 ⑤(Task 98): 하네스 탭의 「연락 하네스」 묶음 — 상황 격자(S-01…S-24 × 네 열 + 채널에만 있는 것)·상한·원칙.

- **격자 칸은 서버 프로세스에서 돌지 않는다**[리뷰 판정 12]. 가짜 통로·음성·글 세션은 서버에서 끼울 수 없고(registry.pinned 가
  RuntimeError), 무르기(breaks)는 서버에서 불러오지도 못한다. 그래서 칸마다 모래상자 자식 프로세스
  (`python -m app.outreach.scenarios.prove <rule_id> [--broken]`)를 띄운다: CHRONOS_HARNESS_SANDBOX=1 · 새 임시 data 폴더(끝나면
  지움) · 비밀 없는 환경(서버의 환경 변수를 물려주지 않는다) · TIMEOUT_S 뒤 죽임 · 표준 출력 OUTPUT_CAP 바이트까지. 한꺼번에
  MAX_CHILDREN 개까지(넘으면 429). 서버의 os.environ·문·도구는 건드리지 않는다. 이 모듈은 상황 대본을 불러오지 않는다.
- 격자의 모양(줄·칸 표시·지키는 곳·칸 말)도 자식이 준다(`--layout`, 한 번 읽으면 이 프로세스 동안 그대로 쓴다).
- 칸은 운영 상한이 아니라 대본이 적어 둔 상한으로 돈다. 운영 상한은 알림 연결 API(/api/notify/connections/{id}/limits)가 한 곳에서
  보이고 고친다 — 콘솔은 기본 연결의 id 만 싣는다(상한을 읽거나 쓰는 코드가 여기 없다).
"""

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.errors import ApiError
from app.programs.devconsole.outreach_view import GROUP_LABELS, group_of
from app.store import outreach

MODULE = "app.outreach.scenarios.prove"
BACKEND = Path(__file__).resolve().parents[3]
TIMEOUT_S = 30
OUTPUT_CAP = 256 * 1024  # 바이트 — 자식은 그 안(prove.OUTPUT_CAP)으로 줄여 쓴다
MAX_CHILDREN = 2  # 서버 전체에서 한꺼번에 도는 자식 수(전부 돌리기는 화면이 하나씩 차례로 보낸다)
_children = threading.BoundedSemaphore(MAX_CHILDREN)
_layout_lock = threading.Lock()
_layout: dict[str, Any] | None = None
RULE_ID = re.compile(r"(S-\d{2}@(call_out|call_in|sms_in|sms_reply)|C-[VSK]\d{1,2})")
COLUMN_LABELS = {"call_out": "전화 걸기", "call_in": "전화 받기", "sms_in": "문자 받기", "sms_reply": "우리 문자·카카오톡에 온 답"}
GROUP = "연락 하네스"
UNKNOWN = "알 수 없는 사건"
BASELINE_FAILS = "그냥 돌려도 실패 — 가드를 확인할 수 없음"
NO_GUARD = "이 칸에는 무를 지키는 곳이 없습니다(공통 겹만 — 구조로만 지킴)."
LIMITS_NOTE = "격자의 칸은 운영 상한이 아니라 대본이 적어 둔 상한으로 돈다 — 아래 운영 상한을 바꿔도 칸의 결과는 바뀌지 않는다."
SANDBOX_NOTE = "모래상자 자식 프로세스(임시 DB · 가짜 통로·음성·글 세션·LLM)에서 진짜 문·도구·뒤 확인·받기 판정으로 grid 실실행"
PRINCIPLES = [  # 설계 「연락 하네스 — 한 벌로 두는 것」 일곱 줄
    "나가는 문: 보내기·걸기는 채널과 상관없이 같은 검사를 같은 차례로 — 시험 모드 → 차단·수신 거부 → 근무시간 → 상한 → 권한 → 중복, 채널은 마지막에 고른다",
    "들어오는 문: 번호로 발신자 등급을 정한다(등급표 하나) — 전화든 문자든 같은 등급, 같은 받기·거절 규칙, 같은 되풀이 상한",
    "도구 묶음: 음성·글 에이전트가 같은 도구를 등급별로 받고, 도구마다 범위를 다시 본다 — 통화에만 있는 것은 end_call·전환뿐",
    "신원 규칙: 말이나 글로 한 신원 주장은 등급을 올리지 않는다 → 등록된 번호로 회신",
    "바꾸지 않는다: 어느 채널로 들어와도 일정·승인은 바뀌지 않는다 — 보고·요청으로 기록해 사람이 확인한다",
    "기록: 메시지와 통화가 같은 하네스 사건 형식(어느 규칙이 무엇을 막았나·허용했나)을 남긴다",
    "뒤 확인: 말하거나 쓴 사실마다 도구 결과에 근거가 있는지, 범위 밖 내용이 나갔는지 본다",
]


def _command(args: list[str]) -> list[str]:
    # -E: 서버 셸의 PYTHON* 변수를 듣지 않음 · -s: 사용자 site 를 보지 않음. -m 은 cwd(BACKEND)에서 app 을 찾는다
    return [sys.executable, "-E", "-s", "-m", MODULE, *args]


def _child_env(home: Path) -> dict[str, str]:
    """자식의 환경 — 서버의 것을 물려주지 않고 새로 만든다(키·관리자 비밀번호·서버 data 폴더 없음)."""
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home), "LANG": "C.UTF-8",
            "CHRONOS_HARNESS_SANDBOX": "1", "CHRONOS_DATA_DIR": str(home / "data"), "CHRONOS_QDRANT_URL": "",
            "CHRONOS_OUTREACH_WORKER": "off"}


def _kill_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass  # 이미 모두 끝남


def _spawn(args: list[str]) -> tuple[int, dict[str, Any]]:
    """자식 하나를 끝까지(제한 시간·출력 상한 안에서) 돌려 (종료 코드, JSON) 을 준다. 자식은 어떤 길로든 거둔다."""
    if not _children.acquire(blocking=False):
        raise ApiError(429, "sandbox_busy", "다른 칸을 돌리는 중입니다. 끝난 뒤 다시 눌러 주세요.")
    try:
        with tempfile.TemporaryDirectory(prefix="chronos-prove-") as where:
            home = Path(where)
            proc = subprocess.Popen(_command(args), cwd=BACKEND, env=_child_env(home), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
            box: dict[str, bytes] = {}
            reader = threading.Thread(target=lambda: box.setdefault("out", proc.stdout.read(OUTPUT_CAP + 1)), daemon=True)
            reader.start()
            reader.join(TIMEOUT_S)
            out = box.get("out", b"")
            timed_out = reader.is_alive()
            code = None
            if not timed_out and len(out) <= OUTPUT_CAP:
                try:
                    code = proc.wait(timeout=max(0.1, TIMEOUT_S / 10))
                except subprocess.TimeoutExpired:
                    code = None
            if code is None or reader.is_alive():
                # 묶음째(start_new_session — 묶음 id = 자식 pid). 묶음에 산 것이 있는 동안은 그 id 가 다른 묶음에 쓰이지 않는다
                _kill_group(proc.pid)
            proc.wait()
            reader.join(1)
            if not reader.is_alive():  # 읽는 중에 닫으면 읽기가 끝날 때까지 붙잡힌다
                proc.stdout.close()
    finally:
        _children.release()
    if timed_out:
        raise ApiError(504, "sandbox_timeout", f"모래상자 실행이 {TIMEOUT_S}초 안에 끝나지 않아 멈췄습니다.")
    if len(out) > OUTPUT_CAP:
        raise ApiError(502, "sandbox_output", "모래상자 실행의 출력이 상한을 넘어 버렸습니다.")
    try:
        body = json.loads(out.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        body = None
    if code is None or not isinstance(body, dict):
        raise ApiError(502, "sandbox_failed", "모래상자 실행이 결과를 주지 못했습니다.")
    return code, body


def _layout_once() -> dict[str, Any]:
    global _layout
    with _layout_lock:
        if _layout is None:
            code, body = _spawn(["--layout"])
            if code != 0 or "rows" not in body:
                raise ApiError(502, "sandbox_failed", "격자 모양을 읽지 못했습니다.")
            _layout = body
        return _layout


def grid(session: Session) -> dict[str, Any]:
    """카탈로그의 「연락 하네스」 묶음 자리. 격자를 읽지 못하면 그 까닭만 싣는다(카탈로그 전체는 그대로)."""
    conn = outreach.connection(session)
    head = {"group": GROUP, "principles": PRINCIPLES, "limits_note": LIMITS_NOTE,
            "connection_id": None if conn is None else conn.id}
    try:
        layout = _layout_once()
    except ApiError as exc:
        return {**head, "columns": [], "rows": [], "channel_only": [], "error": exc.message}
    columns = [{"key": c, "label": COLUMN_LABELS[c]} for c in layout["columns"]]
    return {**head, "columns": columns, "rows": layout["rows"], "channel_only": layout["channel_only"], "error": None}


def is_cell(rule_id: str) -> bool:
    """격자 칸 id 의 꼴(S-07@call_in · C-V1)인가 — 있는 칸인지는 run 이 격자 모양으로 본다."""
    return RULE_ID.fullmatch(rule_id) is not None


def _cell_of(rule_id: str) -> dict[str, Any] | None:
    """격자 모양에서 그 칸(돌릴 수 있는 칸만). 없으면 None — 자식을 띄우기 전에 거른다."""
    if not is_cell(rule_id):
        return None
    layout = _layout_once()
    sid, _, column = rule_id.partition("@")
    if column:
        row = next((r for r in layout["rows"] if r["id"] == sid), None)
        cell = row["cells"].get(column) if row else None
        return cell if cell and cell["runnable"] else None
    return next((c for c in layout["channel_only"] if c["id"] == rule_id), None)


def run(rule_id: str, broken: bool = False) -> dict[str, Any]:
    """칸 하나를 자식 프로세스에서. 기존 차단 시험의 꼴 + passed · checks · events · note · broken_guard · guard_confirmed."""
    cell = _cell_of(rule_id)
    if cell is None:
        raise ApiError(404, "not_found", f"하네스 규칙을 찾을 수 없습니다: {rule_id}")
    if broken and cell["guard"] is None:
        raise ApiError(422, "no_guard", NO_GUARD)
    t0 = time.perf_counter()
    code, body = _spawn([rule_id, *(["--broken"] if broken else [])])
    if code == 2:
        raise ApiError(404, "not_found", f"하네스 규칙을 찾을 수 없습니다: {rule_id}")
    if code == 3:
        raise ApiError(422, "no_guard", NO_GUARD)
    if code != 0 or "error" in body or not isinstance(body.get("passed"), bool):
        raise ApiError(502, "sandbox_failed", f"모래상자 실행이 터졌습니다({body.get('kind') or body.get('error') or '알 수 없음'}).")
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    passed = body["passed"] is True
    events = [{**e, "group": group_of(e.get("rule")), "group_label": GROUP_LABELS.get(group_of(e.get("rule")) or "", UNKNOWN)}
              for e in body.get("events", [])]
    failed = [c["text"] for c in body.get("checks", []) if not c.get("ok")]
    return {
        "rule_id": rule_id, "title": f"{rule_id.split('@')[0]} · {COLUMN_LABELS.get(body.get('column'), '')}",
        "blocked": passed, "engine": "live_harness", "elapsed_ms": elapsed_ms,
        "simulated_input": SANDBOX_NOTE + (f" — 지키는 곳 「{body['broken_guard']}」 를 그 실행 안에서만 무름" if broken else ""),
        "model_feedback": {"passed": passed, "failed_checks": failed, "note": body.get("note"),
                           "sessions": body.get("sessions", []), "channel": body.get("channel"),
                           "events_omitted": body.get("events_omitted", 0)},
        "passed": passed, "checks": [{"text": c["text"], "ok": c["ok"] is True, "guarded": c.get("guarded", False)}
                                     for c in body.get("checks", [])],
        "events": events, "note": body.get("note"), "broken_guard": body.get("broken_guard"),
        **_guard_fields(body, broken),
    }


def guard_verdict(body: dict[str, Any]) -> tuple[bool | None, str]:
    """가드 끄고 돌리기의 판정. 같은 자식의 그냥 돌리기(baseline)가 통과하고, 무른 실행이 **지키는 곳 기대**에서 실패해야
    True. 그냥 돌려도 실패하면 None(확인할 수 없음 — 증거가 아님), 그 밖은 False."""
    if (body.get("baseline") or {}).get("passed") is not True:
        return None, BASELINE_FAILS
    if body.get("passed") is False and any(c.get("guarded") and c.get("ok") is False for c in body.get("checks", [])):
        return True, "그냥은 통과 · 무르니 지키는 곳 기대가 거짓"
    if body.get("passed") is True:
        return False, "물러도 통과 — 시험이 이 지키는 곳을 보지 않음"
    return False, "무르니 실패했지만 지키는 곳 기대는 참 — 이 지키는 곳의 증거가 아님"


def _guard_fields(body: dict[str, Any], broken: bool) -> dict[str, Any]:
    if not broken:
        return {"guard_confirmed": None, "guard_reason": None, "baseline_passed": None}
    confirmed, reason = guard_verdict(body)
    return {"guard_confirmed": confirmed, "guard_reason": reason, "baseline_passed": (body.get("baseline") or {}).get("passed")}
