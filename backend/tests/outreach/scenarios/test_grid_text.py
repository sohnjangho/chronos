"""상황 대본 S-01…S-24 의 글 열(문자 받기 · 우리 문자에 온 답) — Task 86.

칸마다 임시 DB 에 가상 주소록을 깔고, 대본의 받은 문자를 일꾼(받기 판정) → 응대(글 세션은 대본대로 도는 SimulatedText) → 도구 →
뒤 확인 → 나가는 문 → 가짜 통로(FakeChannel)로 돌린다. 지키는 곳을 하나 무르면(breaks) 같은 칸이 실패해야 한다 — 시험이 진짜
엔진을 보고 있다는 증거다. 번호·이름은 모두 가상이다.
"""

import os
import re
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

import pytest

from app.outreach import provider
from app.outreach.harness import door, events, gate, registry, review, tools, toolsets
from app.outreach.scenarios import drive_text
from app.outreach.scenarios.grid import CELLS, CHANNEL_ONLY, run_case, run_cell
from app.outreach.scenarios.situations import COLUMNS, SITUATIONS, USED_RULES, rule
from app.outreach.text import responder
from app.outreach.text import session as text_session
from app.outreach.text.simulated import SimulatedText
from app.store.outreach import Limits

pytestmark = pytest.mark.usefixtures("time_guard")

BACKEND = Path(__file__).resolve().parents[3]
DESIGN = BACKEND.parent / "docs/superpowers/specs/2026-11-23-contacts-outreach-design.md"
TEXT = ("sms_in", "sms_reply")
TEXT_CELLS = [(s.id, c) for s in SITUATIONS for c in TEXT if s.marks[c] != "none"]
BY_ID = {s.id: s for s in SITUATIONS}


def _failing(result) -> list[str]:
    return [c["text"] for c in result.checks if not c["ok"]]


def _digits_in(value: object) -> set[str]:
    """결과 안의 모든 글에서 숫자만 남겨, 대본의 가상 번호 가운데 든 것."""
    texts: list[str] = []

    def walk(item: object) -> None:
        if isinstance(item, str):
            texts.append(item)
        elif isinstance(item, dict):
            for key, inner in item.items():
                walk(key)
                walk(inner)
        elif isinstance(item, list | tuple):
            for inner in item:
                walk(inner)

    walk(value)
    found = set()
    for text in texts:
        digits = re.sub(r"[^0-9]", "", text)
        found |= {n for n in drive_text.NUMBERS.values() if n and (n in digits or n[1:] in digits)}
    return found


# ── 표 ─────────────────────────────────────────────────────────────────


def _design_marks() -> dict[tuple[str, str], str]:
    """설계서 「시나리오는 상황으로 한 번 쓰고」 표의 칸: ● → run, —·빈칸 → none, 「● 글」·「글」 → 글."""
    marks = {}
    for line in DESIGN.read_text(encoding="utf-8").splitlines():
        if not re.match(r"^\| S-\d\d \|", line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        sid, shown = cells[0], cells[2:6]
        for column, cell in zip(COLUMNS, shown, strict=True):
            if cell in ("", "—"):
                marks[(sid, column)] = "none"
            elif cell == "●":
                marks[(sid, column)] = "run"
            else:
                marks[(sid, column)] = cell.removeprefix("● ").strip()
    return marks


def test_twenty_four_situations_and_marks_match_design_table():
    design = _design_marks()
    assert [s.id for s in SITUATIONS] == [f"S-{n:02d}" for n in range(1, 25)]
    assert len(design) == 24 * 4
    assert dict(CELLS) == design
    assert {(s.id, c): s.marks[c] for s in SITUATIONS for c in COLUMNS} == design


# ── 칸이 통과하고, 지키는 곳을 무르면 실패한다 ────────────────────────


@pytest.mark.parametrize(("sid", "col"), TEXT_CELLS)
async def test_text_cell_passes(sid, col):
    result = await run_cell(sid, col)
    assert result.passed, _failing(result)
    assert result.checks and all(c["error"] is None for c in result.checks)
    assert not _digits_in([result.checks, result.events])  # 콘솔에 갈 결과에 번호가 없다


@pytest.mark.parametrize("case", [c.id for c in CHANNEL_ONLY if c.medium == "sms"])
async def test_text_only_case_passes(case):
    result = await run_case(case)
    assert result.passed, _failing(result)
    assert not _digits_in([result.checks, result.events])


@pytest.mark.parametrize(("sid", "col"), TEXT_CELLS)
async def test_text_cell_fails_when_its_guard_is_broken(sid, col):
    """지키는 곳을 무르면 그 칸이 실패한다 — 거짓이 되는 기대는 그 칸에 적어 둔 것(guarded)과 꼭 같다(「무언가」가 아니라 「이것」).
    그리고 그 가운데 적어도 하나는 검사가 터진 것이 아니라 거짓을 본 것이다."""
    result = await run_cell(sid, col, broken=True)
    failed = [c["text"] for c in result.checks if not c["ok"]]
    assert not result.passed
    assert failed == [c["text"] for c in result.checks if c["guarded"]] and failed
    assert [c for c in result.checks if not c["ok"] and c["error"] is None], result.checks


COMMON_ONLY = {("S-10", c) for c in TEXT} | {("S-11", c) for c in TEXT} | {("S-12", c) for c in TEXT}


@pytest.mark.parametrize(("sid", "col"), sorted(COMMON_ONLY | {("S-01", "sms_in")}))
async def test_grid_shows_honest_notes(sid, col):
    """공통 겹만으로 지키는 칸(S-10·11·12)과 설계와 다른 칸(S-01 문자 받기)은 격자 결과에 그렇게 적힌다."""
    note = (await run_cell(sid, col)).note
    assert note is not None and note.startswith("공통 겹만" if (sid, col) in COMMON_ONLY else "설계와 다름: 물려줄 요청 없음")


async def test_other_cells_carry_no_note():
    assert (await run_cell("S-06", "sms_in")).note is None


@pytest.mark.xfail(strict=True, reason="Task 71: channels.sms.length_kind 는 NFC 정리·앞뒤 공백 빼기를 하지 않아 화면 smsLength 와 갈린다 "
                                       "(끝에 빈칸을 붙인 한글 45자 — 화면 SMS, 통로 long)")
def test_sms_length_trailing_spaces_count_like_the_screen():
    from app.outreach.channels.sms import length_kind
    from app.outreach.scenarios.grid import SMS_BYTES, _sms_bytes

    text = "가" * 45 + "  "
    assert length_kind(text) == ("sms" if _sms_bytes(text) <= SMS_BYTES else "long")


def test_every_cell_names_a_guard():
    from app.outreach.scenarios.breaks import BREAKS

    for sid, col in TEXT_CELLS:
        assert BY_ID[sid].guards.get(col) in BREAKS, (sid, col)
    assert set(BREAKS) == {"gate.test_mode", "gate.block_dnc", "gate.hours", "gate.limits", "gate.permission",
                           "gate.duplicate", "door.class", "door.admit", "toolset.per_class", "tools.scope",
                           "tools.identity", "tools.no_change", "review.check"}


def test_every_situation_sets_the_limits_it_uses():
    """상한은 대본이 적는다 — 기본값에 기대는 칸이 없다(모든 칸을 적음). 상한에 걸리는 상황은 그 값을 brief 대로."""
    every = {f.name for f in fields(Limits)}
    for situation in SITUATIONS:
        assert set(situation.setup.limits) == every, situation.id
    for case in CHANNEL_ONLY:
        if case.situation is not None:
            assert set(case.situation.setup.limits) == every, case.id
    s20, s21 = BY_ID["S-20"].setup.limits, BY_ID["S-21"].setup.limits
    assert (s20["inbound_burst_count"], s20["inbound_burst_minutes"], s20["auto_reply_hourly"]) == (3, 5, 2)
    assert s21["reply_grace_minutes"] == 30
    assert {"daily_sms_total", "per_contact_sms_daily"} <= set(BY_ID["S-24"].setup.limits)
    [timed] = [c for c in CHANNEL_ONLY if c.id == "call_time_limit"]
    assert "max_call_seconds" in timed.limits


async def test_changing_a_limit_changes_the_cell_outcome():
    """S-20 의 폭주 문턱을 3 → 10 으로 바꾸면 같은 대본에서 「잦은 문자」로 거절되는 문자가 없다."""
    kept = await run_cell("S-20", "sms_in")
    loose = await run_cell("S-20", "sms_in", limits={"inbound_burst_count": 10})
    burst = rule("admission")
    assert kept.passed and not loose.passed
    assert [e for e in kept.events if e["rule"] == burst and e["detail"] == "burst_limit"]
    assert not [e for e in loose.events if e["rule"] == burst and e["detail"] == "burst_limit"]


def test_every_old_id_is_referenced_once():
    wanted = [f"V-{n:02d}" for n in range(1, 18)] + [f"R-{n:02d}" for n in range(1, 19)] + [f"T-{n:02d}" for n in range(1, 13)]
    seen = [ref for s in SITUATIONS for ref in s.refs] + [ref for c in CHANNEL_ONLY for ref in c.refs]
    assert sorted(seen) == sorted(wanted)


async def test_drivers_use_only_fakes(monkeypatch):
    """칸 하나를 돌리는 동안 글 세션은 SimulatedText, 통로는 FakeChannel, 받은 문자는 대본의 가짜 제공사뿐이다."""
    sessions, lanes, clients = [], [], []
    real_session, real_channel, real_client = text_session.session_for, registry.channel, provider.client_for

    def spy_session(session):
        sessions.append(real_session(session))
        return sessions[-1]

    def spy_channel(name):
        lanes.append(real_channel(name))
        return lanes[-1]

    from app.outreach import worker

    real_plan = worker._plan

    def spy_plan(at):
        plan = real_plan(at)
        clients.append(plan.client)
        return plan

    monkeypatch.setattr(text_session, "session_for", spy_session)
    monkeypatch.setattr(registry, "channel", spy_channel)
    monkeypatch.setattr(worker, "_plan", spy_plan)
    result = await run_cell("S-23", "sms_reply")  # 위임으로 실제로 나가는 칸

    assert clients and all(isinstance(c, drive_text._Inbox) for c in clients)  # 일꾼이 읽은 제공사는 대본의 가짜뿐
    assert result.passed and sessions and lanes
    assert all(isinstance(s, SimulatedText) for s in sessions)
    assert all(isinstance(lane, drive_text.FakeLane) for lane in lanes)
    assert provider.client_for is real_client  # 끝나면 제공사 자리는 그대로
    assert result.sessions and set(result.sessions) == {"SimulatedText"} and result.channel == "FakeChannel"


# ── 무르기는 그 실행 안에서만 ─────────────────────────────────────────


def _snapshot() -> dict:
    """무르기가 건드릴 수 있는 자리 전부의 지금 값."""
    spots = {
        (gate, "_barred"), (gate, "_working"), (gate, "_over_limit"), (gate, "_mode"), (gate, "_twin"),
        (tools, "_delegated"), (tools, "for_class"), (tools, "facts"), (tools, "contacts"), (tools, "_asking"),
        (tools, "_claim_callbacks"), (door, "resolve"), (door, "admit"), (toolsets, "for_class"),
        (responder, "_propose_language"), (review, "check"),
    }
    values = {f"{owner.__name__}.{name}": getattr(owner, name) for owner, name in spots}
    values["tools._TOOLS"] = dict(tools._TOOLS)
    return values


@pytest.mark.parametrize("name", sorted(["gate.test_mode", "gate.block_dnc", "gate.hours", "gate.limits",
                                         "gate.permission", "gate.duplicate", "door.class", "door.admit",
                                         "toolset.per_class", "tools.scope", "tools.identity", "tools.no_change",
                                         "review.check"]))
def test_break_undoes_one_thing_and_restores_it_even_after_an_error(name):
    from app.outreach.scenarios.breaks import BREAKS

    before = _snapshot()
    with pytest.raises(RuntimeError, match="일부러"), BREAKS[name]():
        during = _snapshot()
        assert during != before  # 무언가를 무른다
        raise RuntimeError("일부러 터뜨림")
    assert _snapshot() == before


def _fresh_python(code: str, env_extra: dict[str, str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != registry.SANDBOX_ENV} | env_extra
    return subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120,
                          check=False)


def test_breaks_are_refused_outside_tests_and_sandbox():
    code = "import app.outreach.scenarios.breaks\nprint('LOADED')"
    refused = _fresh_python(code, {})
    assert refused.returncode != 0 and "RuntimeError" in refused.stderr
    assert _fresh_python(code, {registry.SANDBOX_ENV: "1"}).stdout.strip() == "LOADED"


def test_server_does_not_import_scenarios():
    code = ("import sys\nimport app.main\n"
            "print(sorted(m for m in sys.modules if m.startswith('app.outreach.scenarios')))")
    done = _fresh_python(code, {})
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"
    assert "app.outreach.scenarios.drive_text" in registry.SANDBOX_MODULES


def test_expected_event_names_come_from_the_vocabulary():
    assert rule("scope_denied") == "scope_denied"
    with pytest.raises(ValueError):
        rule("scope_refused")
    assert USED_RULES and USED_RULES <= events.KNOWN_RULES


async def test_driver_refuses_while_the_worker_loop_runs(monkeypatch):
    """연락 일꾼이 도는 프로세스(서버)에서는 대본을 돌리지 않는다 — DB·통로를 바꿔 끼우지 않는다."""
    from app.outreach import worker

    monkeypatch.setattr(worker, "status", lambda: {"running": True})
    with pytest.raises(RuntimeError, match="일꾼"):
        await run_cell("S-01", "sms_in")


def test_driver_refuses_outside_tests_and_sandbox():
    code = ("from app.outreach.scenarios import drive_text\n"
            "try:\n    drive_text.temp_database().__enter__()\nexcept RuntimeError:\n    print('REFUSED')")
    assert _fresh_python(code, {}).stdout.strip() == "REFUSED"
