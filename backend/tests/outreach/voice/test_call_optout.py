"""통화 중 수신 거부(H1 · 격자 S-04): 상대 말에 수신 거부 말(door.is_stop — 한 낱말 규칙 「그만」은 빼고)이 들리면 코드가 도구
길(mark_do_not_contact)로 그 번호를 표시하고 끊는다. 통화 중 표시가 실패했으면 통화 뒤 일(after.finish)이 다시 표시한다.
음성은 가짜(SimulatedVoice)뿐이고 시각은 정해 둔 값이다 — 실제 SDK·모델·망이 없다.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.outreach.voice import call_run, inbound, kat_listen
from app.outreach.voice.simulated import Hangup, Ring, Say
from app.security import crypto
from app.store import outreach as store
from app.store.tables_outreach import DoNotContactNumber, VoiceSettings
from tests.outreach.harness.test_door_class import account
from tests.outreach.harness.test_gate import connect, person
from tests.outreach.voice.test_inbound import AGENT_NUMBER, AT, STRANGER, calls_in, ring
from tests.outreach.voice.test_inbound import rules as inbound_rules
from tests.outreach.voice.test_runner import place, queued, reread, rules
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY, assert_clean

pytestmark = pytest.mark.usefixtures("time_guard")

MARK = "tool:mark_do_not_contact"


def _marked(session) -> list[str]:
    session.expire_all()
    return list(session.scalars(select(DoNotContactNumber.number)))


def _flaky(monkeypatch, fails: int = 1) -> list[int]:
    """번호 기준 수신 거부 쓰기가 처음 fails 번은 터진다(DB 가 바쁜 것과 같다)."""
    real, tries = store.mark_do_not_contact, []

    def flaky(session_, number, *, reason):
        tries.append(1)
        if len(tries) <= fails:
            raise RuntimeError("database is locked")
        return real(session_, number, reason=reason)

    monkeypatch.setattr(store, "mark_do_not_contact", flaky)
    return tries


@pytest.fixture(autouse=True)
def fresh_inbound(monkeypatch):
    """받는 통화의 메모리 상태는 시험마다 새것(test_inbound 와 같다)."""
    monkeypatch.setattr(inbound, "_state", inbound._State())
    monkeypatch.setattr(kat_listen, "AGENTS", {})


@pytest.fixture
def side(session, sid):
    """알림 연결(ok·시험 모드 끔·승인 받기·받는 범위 「모두」) + 음성 설정 + 연락처 한 사람 — 걸기·받기 둘 다."""
    row = connect(session, inbound_mode="all")  # 모르는 번호 전화도 받는다(고침 1 — 도구 없는 등급)
    session.add(VoiceSettings(connection_id=row.id, provider="google", secret_ciphertext=crypto.encrypt(SENTINEL_KEY),
                              secret_last4="9999", model="sim-model", agent_number=AGENT_NUMBER, voices_by_language_json={},
                              voice_unknown="sim-n1", voice_male_contact="sim-f1", status="ok"))
    who = person(session, sid, gender="male", language="ko")
    session.commit()
    return type("Side", (), {"who": who})


# ── 거는 통화 ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("said", ["수신거부", "수신 거부할게요.", "수신거부 해 주세요", "수신 거부 부탁드립니다",
                                  "다시는 전화하지 마세요.", "네. 앞으로 연락하지 말아 주세요"])
async def test_opt_out_on_an_outbound_call_marks_and_hangs_up(session, side, said, caplog):
    row = queued(session, side.who)

    sim = await place(row, [Say("peer", "네 맞습니다", t=2), Say("peer", said, t=4), Say("peer", "그리고요", t=6),
                            Hangup("peer")])

    assert _marked(session) == [side.who.phone]
    assert sim.ended == [("agent", 4)]  # 그 말을 들은 때 우리가 끊었다 — 뒤의 말은 오지 않았다
    marks = [(rule, verdict) for rule, verdict, _ in rules(session, row) if rule == MARK]
    assert marks == [(MARK, "allowed")]  # 도구 길 그대로(사건 하나), 통화 뒤 다시 표시하지 않음
    assert reread(session, row).status == "completed"
    assert SENTINEL_DIGITS not in str(rules(session, row))
    assert_clean(caplog)


async def test_stop_said_in_passing_does_not_end_the_call(session, side):
    row = queued(session, side.who)

    sim = await place(row, [Say("peer", "그만 말씀하세요", t=2), Say("peer", "그만", t=4), Hangup("peer")])

    assert _marked(session) == []
    assert sim.ended == [("peer", 4)]
    assert MARK not in [rule for rule, _, _ in rules(session, row)]


async def test_failed_in_call_mark_is_recovered_after_the_call(session, side, monkeypatch):
    tries = _flaky(monkeypatch)
    row = queued(session, side.who)

    sim = await place(row, [Say("peer", "수신거부요", t=2), Hangup("peer")])

    assert sim.ended == [("agent", 2)]  # 표시가 실패해도 끊는다
    assert len(tries) == 2 and _marked(session) == [side.who.phone]
    assert [rule for rule, _, _ in rules(session, row)].count(MARK) == 1  # 실패한 통화 중 호출은 사건이 없다(되돌림)


async def test_after_call_does_nothing_when_nothing_was_heard(session, side, monkeypatch):
    tries = _flaky(monkeypatch, fails=0)
    row = queued(session, side.who)

    await place(row, [Say("peer", "네 맞습니다", t=2), Hangup("peer")])

    assert tries == [] and _marked(session) == []


# ── 받는 통화 ──────────────────────────────────────────────────────────


async def test_opt_out_on_an_inbound_call_marks_and_hangs_up(session, side):
    sim = await ring(Ring(side.who.phone, AT), Say("peer", "수신 거부 해주세요", t=2), Say("peer", "그리고요", t=4),
                     Hangup("peer"))

    (row,) = calls_in(session)
    assert _marked(session) == [side.who.phone]
    assert sim.calls[0].ended == ("agent", 2)
    assert [rule for rule, _, _ in inbound_rules(row)].count(MARK) == 1


async def test_failed_in_call_mark_on_an_inbound_call_is_recovered(session, side, monkeypatch):
    tries = _flaky(monkeypatch)

    await ring(Ring(side.who.phone, AT), Say("peer", "수신거부", t=2), Hangup("peer"))

    (row,) = calls_in(session)
    assert len(tries) == 2 and _marked(session) == [side.who.phone]
    assert [rule for rule, _, _ in inbound_rules(row)].count(MARK) == 1


async def test_inbound_stop_word_alone_is_not_an_opt_out(session, side):
    sim = await ring(Ring(side.who.phone, AT), Say("peer", "그만", t=2), Hangup("peer"))

    assert _marked(session) == [] and sim.calls[0].ended == ("peer", 2)


# ── 고침 1: 묶음에 도구가 없는 등급(모르는 번호·내부) ──────────────────────


def _caller(session, who):
    """그 등급으로 걸려 오는 번호 — 모르는 번호, 내부 계정의 번호."""
    if who == "internal":
        account(session, number="01000000122")
        session.commit()
        return "01000000122"
    return STRANGER


@pytest.mark.parametrize("who", ["unknown", "internal"])
async def test_caller_without_the_tool_is_still_marked(session, side, who, caplog):
    number = _caller(session, who)

    sim = await ring(Ring(number, AT), Say("peer", "다시는 전화하지 마세요", t=2), Say("peer", "그리고요", t=4), Hangup("peer"))

    (row,) = calls_in(session)
    assert row.caller_class == who
    assert _marked(session) == [number]
    assert sim.calls[0].ended == ("agent", 2)
    seen = [(rule, verdict) for rule, verdict, _ in inbound_rules(row)]
    assert seen.count((MARK, "noted")) == 1 and ("tool_not_allowed", "blocked") not in seen  # 도구 호출이 아니라 코드가 남김
    assert number not in str(inbound_rules(row))
    assert_clean(caplog, number)


async def test_caller_without_the_tool_is_marked_after_the_call_if_it_failed(session, side, monkeypatch):
    tries = _flaky(monkeypatch)

    await ring(Ring(STRANGER, AT), Say("peer", "수신거부", t=2), Hangup("peer"))

    (row,) = calls_in(session)
    assert len(tries) == 2 and _marked(session) == [STRANGER]
    assert [(rule, verdict) for rule, verdict, _ in inbound_rules(row)].count((MARK, "noted")) == 1


async def test_withheld_caller_has_nothing_to_mark(session, side, monkeypatch):
    tries = _flaky(monkeypatch, fails=0)

    sim = await ring(Ring(None, AT), Say("peer", "수신거부", t=2), Hangup("peer"))

    (row,) = calls_in(session)
    assert row.caller_class == "withheld" and tries == [] and _marked(session) == []
    assert sim.calls[0].ended == ("agent", 2)  # 끊기는 한다
    assert MARK not in [rule for rule, _, _ in inbound_rules(row)]


# ── 한 통화에 한 번 ────────────────────────────────────────────────────


class _Box:
    names = frozenset({"mark_do_not_contact"})

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def call(self, name, args):
        self.calls.append((name, args))
        return {"ok": True}


class _Control:
    def __init__(self) -> None:
        self.hung = 0

    async def hangup(self) -> None:
        self.hung += 1


async def test_opt_out_is_marked_once_per_call(session):
    run = call_run.CallRun(999_999, None, datetime(2026, 11, 27, 1, 0, tzinfo=UTC), None)  # 없는 줄 — 받아쓰기 쓰기는 지나간다
    run.box, run.control = _Box(), _Control()

    for t, text in enumerate(("수신거부", "수신거부 할게요", "수신거부요")):
        await run.on_transcript("peer", text, float(t))
    await asyncio.sleep(0)

    assert [name for name, _ in run.box.calls] == ["mark_do_not_contact"]
    assert run.control.hung == 1 and run.closing
    assert AGENT_NUMBER not in str(run.box.calls)
