"""상황 대본 S-01…S-24 의 음성 열(전화 걸기 · 전화 받기)과 통화·카카오톡에만 있는 경우 — Task 97.

같은 대본(Task 86 의 SITUATIONS)을 음성 구동기가 가짜 통화(SimulatedVoice)로 돈다: 거는 통화는 문(gate.dispatch) → 통화 일꾼
(runner.run_one — 걸기 직전 다시 보기 · 하네스 도구 · 통화 뒤 일), 받는 통화는 벨(Ring) → 받기 전 판정(inbound.on_incoming) → 통화 →
통화 뒤 일. 요약 모델은 정해 둔 답을 주는 가짜, 통로는 FakeChannel. 실제 통화·문자·카카오톡·LLM·망이 없다. 번호·이름은 모두 가상이다.
지키는 곳을 하나 무르면 같은 칸이 실패해야 하고, 거짓이 되는 기대는 그 칸에 적어 둔 것(guarded)과 꼭 같아야 한다.
"""

import ast
from pathlib import Path

import pytest

from app.outreach.harness import registry
from app.outreach.scenarios import drive_text, drive_voice, grid
from app.outreach.scenarios.grid import CELLS, CHANNEL_ONLY, run_case, run_cell
from app.outreach.scenarios.situations import (
    COLUMNS,
    DIVERGED_DNC,
    DIVERGED_LANGUAGE,
    DIVERGED_REPEAT,
    SIMULATED_ONLY,
    SITUATIONS,
)
from app.outreach.voice import after
from app.outreach.voice import session as voice_session
from app.outreach.voice.simulated import SimulatedVoice
from tests.outreach.scenarios.test_grid_text import _digits_in, _failing

pytestmark = pytest.mark.usefixtures("time_guard")

SCENARIOS = Path(drive_voice.__file__).parent
VOICE = ("call_out", "call_in")
BY_ID = {s.id: s for s in SITUATIONS}
VOICE_CELLS = [(s.id, c) for s in SITUATIONS for c in VOICE if s.marks[c] != "none"]
DIVERGED = {(s.id, c): s.notes[c] for s in SITUATIONS for c in VOICE
            if s.notes.get(c) in (DIVERGED_DNC, DIVERGED_LANGUAGE, DIVERGED_REPEAT)}
UNGUARDED = {(s.id, c) for s in SITUATIONS for c in VOICE if s.marks[c] != "none" and c not in s.guards}


def _cells(*, broken: bool) -> list:
    """음성 칸 — 하네스가 갈라진 칸은 여기서 빠지고 test_divergent_cell_fails_on_exactly_these 가 깨지는 기대를 고정한다. 무를 곳이
    없는 칸은 무르기 시험에서 빠진다(까닭과 함께)."""
    found = []
    for sid, col in VOICE_CELLS:
        if (sid, col) in DIVERGED:
            continue
        if broken and (sid, col) in UNGUARDED:
            found.append(pytest.param(sid, col, marks=pytest.mark.skip(reason=BY_ID[sid].notes[col])))
        else:
            found.append((sid, col))
    return found


# ── 칸이 통과하고, 지키는 곳을 무르면 실패한다 ────────────────────────


def test_voice_grid_is_the_design_table():
    assert len(VOICE_CELLS) == 42  # 48 칸 가운데 설계 표의 — 6 칸이 빠진다
    assert {(sid, c) for (sid, c), mark in CELLS.items() if c in VOICE and mark == "none"} == {
        ("S-14", "call_out"), ("S-15", "call_out"), ("S-16", "call_out"), ("S-19", "call_out"), ("S-20", "call_out"),
        ("S-24", "call_in")}
    assert sorted(DIVERGED) == [("S-04", "call_in"), ("S-04", "call_out"), ("S-13", "call_in"), ("S-13", "call_out"),
                                ("S-20", "call_in")]


@pytest.mark.parametrize(("sid", "col"), _cells(broken=False))
async def test_voice_cell_passes(sid, col):
    result = await run_cell(sid, col)
    assert result.passed, _failing(result)
    assert result.checks and all(c["error"] is None for c in result.checks)
    assert not _digits_in([result.checks, result.events])  # 콘솔에 갈 결과에 번호가 없다
    assert result.channel == "FakeChannel" and set(result.sessions) <= {"SimulatedVoice"}


# 갈라진 칸에서 거짓이 되는 기대 — 꼭 이것들만(검사가 터진 것 없이). 제품이 고쳐지면(예: 통화의 수신 거부 듣기) 이 시험이 깨져 칸을 뒤집게 한다.
DNC_FALSE = ["번호 기준 수신 거부로 표시된다", "그 뒤 문자는 문이 수신 거부로 막는다(차례 blocked_or_dnc)",
             "그 뒤 전화도 문이 수신 거부로 막는다(차례 blocked_or_dnc)"]
DIVERGED_FALSE = {
    ("S-04", "call_out"): DNC_FALSE, ("S-04", "call_in"): DNC_FALSE,
    ("S-13", "call_out"): ["언어는 제안 한 줄(language, pending)로만"],
    ("S-13", "call_in"): ["언어는 제안 한 줄(language, pending)로만"],
    ("S-20", "call_in"): ["통화: 같은 번호가 짧은 시간에 거듭 걸면 문턱(5분에 3) 뒤부터 받지 않는다(burst_limit)"],
}


@pytest.mark.parametrize(("sid", "col"), sorted(DIVERGED_FALSE))
async def test_divergent_cell_fails_on_exactly_these(sid, col):
    """하네스가 갈라진 다섯 칸: 실패하되, 거짓이 되는 기대는 적어 둔 것과 꼭 같고 터진 기대가 없다(뜻밖의 고장을 삼키지 않는다)."""
    assert (sid, col) in DIVERGED
    result = await run_cell(sid, col)
    assert not result.passed
    assert [c["text"] for c in result.checks if not c["ok"]] == DIVERGED_FALSE[(sid, col)]
    assert all(c["error"] is None for c in result.checks), result.checks


@pytest.mark.parametrize("case", [c.id for c in CHANNEL_ONLY if c.medium in ("call", "kakao")])
async def test_call_and_kakao_only_case_passes(case):
    result = await run_case(case)
    assert result.passed, _failing(result)
    assert result.checks and all(c["error"] is None for c in result.checks)
    assert not _digits_in([result.checks, result.events])


@pytest.mark.parametrize("case", [c.id for c in CHANNEL_ONLY if c.medium == "call" and c.situation.guards])
async def test_call_only_case_fails_when_its_guard_is_broken(case):
    result = await run_case(case, broken=True)
    failed = [c["text"] for c in result.checks if not c["ok"]]
    assert not result.passed
    assert failed == [c["text"] for c in result.checks if c["guarded"]] and failed


@pytest.mark.parametrize(("sid", "col"), _cells(broken=True))
async def test_voice_cell_fails_when_its_guard_is_broken(sid, col):
    """지키는 곳을 무르면 그 칸이 실패한다 — 거짓이 되는 기대는 그 칸에 적어 둔 것(guarded)과 꼭 같고(「무언가」가 아니라 「이것」),
    그 가운데 적어도 하나는 검사가 터진 것이 아니라 거짓을 본 것이다."""
    result = await run_cell(sid, col, broken=True)
    failed = [c["text"] for c in result.checks if not c["ok"]]
    assert not result.passed
    assert failed == [c["text"] for c in result.checks if c["guarded"]] and failed
    assert [c for c in result.checks if not c["ok"] and c["error"] is None], result.checks


def test_every_voice_cell_names_a_guard_or_says_why_not():
    from app.outreach.scenarios.breaks import BREAKS, VOICE_BREAKS

    for sid, col in VOICE_CELLS:
        guard, note = BY_ID[sid].guards.get(col), BY_ID[sid].notes.get(col, "")
        assert guard in {**BREAKS, **VOICE_BREAKS} or note.startswith(("공통 겹만", "설계와 다름")), (sid, col)
    assert set(VOICE_BREAKS) == {"runner.hours", "call.silence", "call.time_limit"} and not set(VOICE_BREAKS) & set(BREAKS)


@pytest.mark.parametrize("name", ["runner.hours", "call.silence", "call.time_limit"])
def test_voice_break_restores_its_spot_even_after_an_error(name):
    from app.outreach.scenarios.breaks import VOICE_BREAKS
    from app.outreach.voice import call_run, runner

    before = (runner._working, call_run.SILENCE_S, call_run.CallRun.on_tick)
    with pytest.raises(RuntimeError, match="일부러"), VOICE_BREAKS[name]():
        assert (runner._working, call_run.SILENCE_S, call_run.CallRun.on_tick) != before
        raise RuntimeError("일부러 터뜨림")
    assert (runner._working, call_run.SILENCE_S, call_run.CallRun.on_tick) == before


# ── 같은 대본 ─────────────────────────────────────────────────────────


async def test_same_script_object_is_used_for_text_and_voice(monkeypatch):
    """두 구동기가 같은 Situation(같은 turns 객체)을 받고, 구동기 안에는 상황별 분기도 대본 걸음을 새로 짓는 곳도 없다."""
    seen = []
    for module in (drive_text, drive_voice):
        real = module.run

        async def spy(situation, column, factory, real=real):
            seen.append((column, situation.turns))
            return await real(situation, column, factory)

        monkeypatch.setattr(module, "run", spy)
    for column in COLUMNS:
        assert (await run_cell("S-06", column)).passed
    assert [column for column, _ in seen] == list(COLUMNS)
    assert all(turns is BY_ID["S-06"].turns for _, turns in seen)

    steps = {"Them", "Model", "ModelSays", "Wait", "Permit", "Situation", "Setup"}
    for path in (SCENARIOS / "drive_text.py", SCENARIOS / "drive_voice.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        texts = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        assert not [text for text in texts if "S-" in text], path.name  # 상황 번호로 가르는 곳이 없다
        built = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert not built & steps, path.name  # 대본을 고쳐 쓰지 않는다


async def test_same_events_shape_across_columns():
    """S-07 네 열: 도구 사건은 같은 rule·verdict(거절 셋, 일정 사실 0) — 매체는 사건의 꼴을 바꾸지 않는다."""
    shapes = {}
    for column in COLUMNS:
        result = await run_cell("S-07", column)
        assert result.passed, (column, _failing(result))
        shapes[column] = sorted((e["rule"], e["verdict"]) for e in result.events
                                if e["rule"] == "scope_denied" or e["rule"].startswith("tool"))
    assert all(shape == [("scope_denied", "blocked")] * 3 for shape in shapes.values()), shapes


def test_voice_drivers_place_no_real_call():
    """음성 구동기는 SDK·제공사·통로·모델 모듈을 불러오지 않는다 — 통화는 가짜(SimulatedVoice), 요약은 가짜(_Summary)뿐."""
    for path in (SCENARIOS / "drive_voice.py",):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imported |= {f"{node.module}.{alias.name}" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                     for alias in node.names}
        forbidden = ("clawops", "httpx", "kat_sdk", "kat_listen", "app.outreach.provider", "app.outreach.channels",
                     "app.llm.client.LlmClient", "google")
        assert not [name for name in imported if any(bad in name for bad in forbidden)], path.name
    assert "app.outreach.scenarios.drive_voice" in registry.SANDBOX_MODULES


async def test_voice_cell_uses_only_fakes(monkeypatch):
    """칸 하나를 돌리는 동안 음성 백엔드는 대본의 SimulatedVoice, 통로는 FakeLane, 요약 모델은 가짜뿐 — 끝나면 자리는 그대로."""
    backends, lanes = [], []
    real_backend, real_channel, real_summary = voice_session.backend_for, registry.channel, after.client_for

    def spy_backend(session):
        backends.append(real_backend(session))
        return backends[-1]

    def spy_channel(name):
        lanes.append(real_channel(name))
        return lanes[-1]

    monkeypatch.setattr(voice_session, "backend_for", spy_backend)
    monkeypatch.setattr(registry, "channel", spy_channel)
    result = await run_cell("S-01", "call_out")  # 문(통로)과 통화 일꾼·통화 뒤 일을 다 지나는 칸

    assert result.passed and backends and lanes
    assert all(isinstance(b, SimulatedVoice) for b in backends)
    assert all(isinstance(lane, drive_text.FakeLane) for lane in lanes)
    assert after.client_for is real_summary  # 요약 모델 자리는 끝나면 그대로
    assert result.sessions == ("SimulatedVoice",)


# ── 격자 ───────────────────────────────────────────────────────────────


async def test_run_all_covers_four_columns(monkeypatch):
    seen = []

    async def fake(sid, column, **kwargs):
        seen.append((sid, column))
        return drive_text.CellResult(True, [], [])

    monkeypatch.setattr(grid, "run_cell", fake)
    found = await grid.run_all()
    assert set(found) == {cell for cell, mark in CELLS.items() if mark != "none"} == set(seen)
    assert {column for _, column in found} == set(COLUMNS) and len(found) == 86


@pytest.mark.parametrize(("sid", "col", "start"), [
    ("S-10", "call_out", "공통 겹만"), ("S-11", "call_in", "공통 겹만"), ("S-12", "call_out", "공통 겹만"),
    ("S-23", "call_in", "공통 겹만"), ("S-24", "call_out", "공통 겹만"), ("S-01", "call_in", "설계와 다름"),
    ("S-17", "call_out", "설계와 다름"), ("S-18", "call_out", "설계와 다름"),
    ("S-04", "call_in", "하네스가 갈라짐")])
async def test_voice_grid_shows_honest_notes(sid, col, start):
    note = (await run_cell(sid, col)).note
    assert note is not None and note.startswith(start)


def _scripts() -> list:
    return [*SITUATIONS, *(case.situation for case in CHANNEL_ONLY)]


def test_simulated_only_expectations_are_labelled():
    """가짜에서만 참인 기대(코드가 control.say 로 시킨 말 — 실제 SDK 에는 「이 말을 하라」가 없다(Task 113) · 가짜 상태 조회의
    fell_back — 실제 제공사 클라이언트는 늘 False)는 표시(Check.simulated)를 달고, 그 기대가 도는 열의 note 는 「가짜에서만 — 」으로
    시작한다. code_said 를 읽는 기대는 모두 표시가 있어야 한다."""
    labelled = set()
    for script in _scripts():
        for check in script.expect:
            if "code_said" in check.fn.__code__.co_names:
                assert check.simulated, (script.id, check.text)
            if not check.simulated:
                continue
            for column in check.columns or COLUMNS:
                if script.marks[column] != "none":
                    labelled.add((script.id, column))
                    assert script.notes.get(column, "").startswith(SIMULATED_ONLY), (script.id, column)
                    assert check.simulated in script.notes[column], (script.id, column)
    assert labelled == {("S-21", "call_in"), ("silence", "call_out"), ("call_time_limit", "call_out"),
                        ("kakao_fell_back", "sms_reply")}


@pytest.mark.parametrize("case", ["silence", "call_time_limit", "kakao_fell_back"])
async def test_simulated_only_note_reaches_the_grid_output(case):
    note = (await run_case(case)).note
    assert note is not None and note.startswith(SIMULATED_ONLY)


async def test_voice_driver_refuses_while_the_call_runner_runs(monkeypatch):
    """통화 일꾼이 도는 프로세스(서버)에서는 음성 대본을 돌리지 않는다 — 일꾼·받는 쪽 상태와 음성 백엔드를 바꿔 끼우지 않는다."""
    from app.outreach.voice import runner

    monkeypatch.setattr(runner._state, "running", True)
    with pytest.raises(RuntimeError, match="통화 일꾼"):
        await run_cell("S-01", "call_out")


def test_silence_length_does_not_read_the_live_threshold():
    """침묵 경우의 길이 기대는 불러올 때의 SILENCE_S 를 쓴다 — 무르기(call.silence)가 그 값을 바꿔도 그 기대는 엉뚱한 까닭으로 깨지지 않는다."""
    from app.outreach.voice import call_run

    assert grid.SILENCE_S == call_run.SILENCE_S == 15
