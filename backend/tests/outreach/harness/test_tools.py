"""도구 묶음(Task 67) — Toolbox 의 틀(사건 꼭 하나·거절 까닭), 범위를 다시 보는 도구, 신원 규칙, 바꾸지 않음, 후속.

번호·이름·회사는 모두 가상이다(이름표의 SENTINEL_PHONE). 아래 도우미는 test_scope_matrix·test_facts 도 같이 쓴다.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.model import Activity, CalendarSpec, Relation, Schedule, WbsNode
from app.outreach import hours, redact
from app.outreach.harness import door, events, gate, tools
from app.outreach.harness.tools import Toolbox
from app.outreach.harness.toolsets import ALL, for_class
from app.outreach.harness.types import TOOL_REFUSALS, Actor, Ref, Scope
from app.store import outreach as store
from app.store.schedules import create_schedule
from app.store.tables import Approval, DelayEvent, ScheduleRecord, User
from app.store.tables_outreach import (
    BlockedNumber,
    Contact,
    ContactCompany,
    ContactProposal,
    ContactReport,
    DoNotContactNumber,
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
)
from app.store.timeutil import as_utc
from tests.outreach_doubles import SENTINEL_DIGITS

KST = hours.KST
WORK = datetime(2026, 11, 27, 10, 0, tzinfo=KST)  # 금요일 10시 — 근무 중
OFF = datetime(2026, 11, 27, 19, 0, tzinfo=KST)  # 금요일 19시 — 근무 밖
PHONE = SENTINEL_DIGITS  # 박현장(가람 현장 철근)
LEE = "01000000188"  # 이설비(가람 현장 설비)
CHOI = "01000000177"  # 최철근(나래 현장 철근)
HANDOFF = "01000000166"  # 사람 담당자에게 넘길 번호
STRANGER = "01000000155"  # 주소록에 없는 번호
NEW = "010-0000-0144"  # 통화·문자에서 받은 새 번호
NEW_DIGITS = "01000000144"
SITE_A, SITE_B = "가람 현장", "나래 현장"
MARK_A, MARK_B = "표식-가", "표식-나"
CLOSED = Scope("unknown", (), (), False, "none")
REFUSED = "말씀드릴 수 없는 내용입니다"
ASK = "어느 현장 일인지 여쭤보세요"
TOOL_EVENTS = frozenset({f"tool:{name}" for name in ALL}) | TOOL_REFUSALS


# ── 도우미 ───────────────────────────────────────────────────────────


def project(session: Session, name: str, mark: str, start: date, other: str = "설비") -> int:
    """일정 하나: R 「<표식> 철근 배근」(3일, WBS 골조) → E 「<표식> 마감 작업」(4일, WBS <other>) → Z 「<표식> 준공」(마일스톤)."""
    schedule = Schedule(
        start=start, calendar=CalendarSpec(days_per_week=5),
        wbs=(WbsNode("1", "골조", None), WbsNode("2", other, None)),
        activities=(Activity("R", f"{mark} 철근 배근", "task", "1", 3), Activity("E", f"{mark} 마감 작업", "task", "2", 4),
                    Activity("Z", f"{mark} 준공", "finish_ms", "1", 0)),
        relations=(Relation("R", "E"), Relation("E", "Z")), resources=(),
    )
    return create_schedule(session, name=name, domain="construction", level="L3", schedule=schedule, conditions=[],
                           by_kind="agent", by_name="에이전트", note="처음 만듦")


def firm(session: Session, sid: int, name: str, trade: str, **over) -> ContactCompany:
    row = ContactCompany(schedule_id=sid, name=name, trade=trade, **over)
    session.add(row)
    session.flush()
    return row


def who(session: Session, company: ContactCompany, name: str, number: str | None, **over) -> Contact:
    row = Contact(schedule_id=company.schedule_id, company_id=company.id, name=name, phone=number, **over)
    session.add(row)
    session.flush()
    return row


def connect(session: Session, **over) -> NotifyConnection:
    """기본 알림 연결: 상태 ok, 시험 모드 끔, 모두 받기, 모두 「승인 받기」."""
    row = NotifyConnection(**{"name": "시험 연결", "base_url": "https://kat.invalid", "secret_ciphertext": "x",
                              "secret_last4": "9999", "account_id": "acct-test", "sender_number": "07000000000",
                              "is_default": True, "status": "ok", "test_mode": False, "inbound_mode": "all", **over})
    session.add(row)
    session.flush()
    return row


@dataclass
class World:
    a: int
    b: int
    rebar_a: ContactCompany
    mep_a: ContactCompany
    rebar_b: ContactCompany
    elec_b: ContactCompany
    park: Contact
    lee: Contact
    choi: Contact


def world(session: Session) -> World:
    """두 프로젝트·네 협력사: 가람 현장(철근 박현장·설비 이설비), 나래 현장(철근 최철근·전기 — 사람 없음)."""
    a = project(session, SITE_A, MARK_A, date(2027, 3, 1), "설비")
    b = project(session, SITE_B, MARK_B, date(2028, 5, 1), "전기")
    rebar_a, mep_a = firm(session, a, "가람철근", "철근"), firm(session, a, "가람설비", "설비")
    rebar_b, elec_b = firm(session, b, "나래철근", "철근"), firm(session, b, "나래전기", "전기")
    park = who(session, rebar_a, "박현장", PHONE, role_title="철근 반장")
    lee = who(session, mep_a, "이설비", LEE, role_title="설비 소장")
    choi = who(session, rebar_b, "최철근", CHOI, role_title="철근 반장")
    return World(a, b, rebar_a, mep_a, rebar_b, elec_b, park, lee, choi)


def message(session: Session, to: Contact | None = None, **over) -> OutreachMessage:
    values = {"direction": "out", "channel": "sms", "origin": "user", "origin_name": "김공정", "body": "내일 타설 가능하신가요",
              **over}
    if to is not None:
        values = {"schedule_id": to.schedule_id, "contact_id": to.id, **values}
    row = OutreachMessage(**values)
    session.add(row)
    session.flush()
    return row


def call(session: Session, to: Contact | None = None, **over) -> OutreachCall:
    values = {"direction": "out", "origin": "user", "origin_name": "김공정", "purpose": "타설 인원 확인", **over}
    if to is not None:
        values = {"schedule_id": to.schedule_id, "contact_id": to.id, **values}
    row = OutreachCall(**values)
    session.add(row)
    session.flush()
    return row


def incoming(session: Session, medium: str, person: Contact | None = None, number: str | None = None, **over):
    """들어온 문자·받는 통화 한 줄(연락처가 하나로 정해졌으면 그 사람, 아니면 번호만)."""
    values = {"direction": "in", "origin": "peer", "peer_number": None if person is not None else number, **over}
    if medium == "call":
        return call(session, person, **{"status": "in_call", "purpose": "", **values})
    return message(session, person, **{"status": "received", "body": "들어온 글", **values})


def ref_of(row) -> Ref:
    return Ref("call" if isinstance(row, OutreachCall) else "message", row.id)


def boxed(scope: Scope, row, cls: str, *, names=None, now: datetime = WORK) -> Toolbox:
    """그 줄에 붙은 Toolbox. names 를 주지 않으면 그 등급·매체의 묶음. 부르기 전에 session.commit() 을 해 둘 것."""
    medium = "call" if isinstance(row, OutreachCall) else "sms"
    return Toolbox(scope, medium, ref_of(row), names=for_class(cls, medium) if names is None else frozenset(names),
                   caller_class=cls, clock=lambda: now)


def inbound(session: Session, medium: str, number: str | None, *, names=None, now: datetime = WORK, **over):
    """그 번호에서 들어온 것의 (Toolbox, 줄) — 등급과 범위는 들어오는 문이 번호로 정한 그대로."""
    caller = door.resolve(session, number, now=now)
    scope = door.scope_of(session, caller)
    one = session.get(Contact, caller.candidates[0].contact_id) if len(caller.candidates) == 1 else None
    row = incoming(session, medium, one, number, caller_class=caller.caller_class, **over)
    session.commit()
    return boxed(scope, row, caller.caller_class, names=names, now=now), row


def outbound(session: Session, person: Contact, *, names=None, now: datetime = WORK, **over):
    """우리가 그 사람에게 건 통화의 (Toolbox, 줄)."""
    row = call(session, person, **{"status": "in_call", "caller_class": "outbound", **over})
    session.commit()
    scope = door.outbound_scope(session, person.schedule_id, person.id)
    return boxed(scope, row, "outbound", names=names, now=now), row


def log(session: Session, row) -> list[dict]:
    session.expire_all()
    return events.of(session, ref_of(row))


def trail(session: Session, row) -> list[tuple[str, str]]:
    """그 줄의 사건 (이름, 판정) — 남긴 차례대로."""
    return [(e["rule"], e["verdict"]) for e in log(session, row)]


def count(session: Session, model, *where) -> int:
    session.expire_all()
    return session.scalar(select(func.count(model.id)).where(*where)) or 0


def account(session: Session, number: str, role: str = "user") -> User:
    """그 번호가 등록된 로그인 계정(내부 등급)."""
    row = User(login_id=f"tools-{role}", name="이내부", role=role, phone=number, password_hash="x")
    session.add(row)
    session.flush()
    return row


def has_digits(value: object, digits: str) -> bool:
    """그 값 안의 어느 글에든(dict 는 열쇠도) 그 번호가 어느 꼴로든 있는가. 글마다 따로 본다(글끼리 이어 붙이지 않는다)."""
    if isinstance(value, dict):
        return any(has_digits(key, digits) or has_digits(item, digits) for key, item in value.items())
    if isinstance(value, list | tuple | set | frozenset):
        return any(has_digits(item, digits) for item in value)
    only = "".join(ch for ch in str(value) if ch.isdigit())
    return digits in only or digits[1:] in only


class FakeControl:
    """통화 손잡이 가짜: 전환한 번호·끊은 횟수를 쌓는다. accept 가 거짓이면 전환을 시작하지 못한다."""

    def __init__(self, accept: bool = True, error: Exception | None = None) -> None:
        self.transfers: list[str] = []
        self.hung = 0
        self.accept = accept
        self.error = error

    async def say(self, text: str) -> None:
        raise AssertionError("도구는 말을 시키지 않는다")

    async def hangup(self) -> None:
        self.hung += 1

    async def transfer(self, number: str) -> bool:
        self.transfers.append(number)
        if self.error is not None:
            raise self.error
        return self.accept


# ── Toolbox 의 틀 ────────────────────────────────────────────────────


async def test_tool_outside_set_is_refused_and_logged(session):
    world(session)
    connect(session)
    box, row = inbound(session, "sms", STRANGER)

    r = await box.call("schedule_fact", {"activity": f"{MARK_A} 철근 배근"})

    assert "error" in r and MARK_A not in json.dumps(r, ensure_ascii=False)
    assert trail(session, row) == [("tool_not_allowed", "blocked")]
    assert log(session, row)[0]["detail"] == "tool=schedule_fact"


async def test_model_supplied_tool_name_is_recorded_as_tool_unknown(session):
    world(session)
    connect(session)
    box, row = inbound(session, "sms", PHONE)

    for name in ("change_schedule", f"call {NEW}", "", None, 7, "tool:find_contact"):
        assert await box.call(name, {}) == {"error": "쓸 수 없는 도구입니다"}  # 모델이 준 이름을 되돌려 주지도 않는다

    assert trail(session, row) == [("tool:unknown", "blocked")] * 6
    assert {e["detail"] for e in log(session, row)} == {"tool=unknown"}
    assert not has_digits(log(session, row), NEW_DIGITS)


async def test_one_tool_call_leaves_exactly_one_event(session):
    """허용 → tool:<이름> 하나 · 범위 밖 → scope_denied 하나(tool:schedule_fact 없음) · 묶음 밖 → tool_not_allowed 하나 ·
    틀린 인자 → tool_bad_args 하나 · 모르는 이름 → tool:unknown 하나."""
    w = world(session)
    connect(session)
    box, row = inbound(session, "call", PHONE)
    seen = 0

    async def one(name, args, rule, verdict):
        nonlocal seen
        await box.call(name, args)
        added = log(session, row)[seen:]
        seen += len(added)
        assert [(e["rule"], e["verdict"]) for e in added] == [(rule, verdict)], name

    await one("schedule_fact", {"activity": "철근 배근"}, "tool:schedule_fact", "allowed")
    await one("schedule_fact", {"activity": "마감 작업"}, "scope_denied", "blocked")
    await one("confirm_person", {"is_person": True}, "tool_not_allowed", "blocked")
    await one("schedule_fact", {"activity": "철근", "schedule_id": w.b}, "tool_bad_args", "blocked")
    await one("schedule_fact", {}, "tool_bad_args", "blocked")
    await one("schedule_fact", "철근", "tool_bad_args", "blocked")
    await one("lookup_everything", {}, "tool:unknown", "blocked")
    await one("take_message", {"text": "내일 다시 연락 주세요"}, "tool:take_message", "allowed")
    await one("end_call", {"reason": "done"}, "tool:end_call", "allowed")


async def test_every_tool_call_leaves_one_event(session, fake_channel):
    """묶음의 모든 도구: 부를 때마다 사건이 꼭 하나, 이름은 상수 집합 안, detail 에 번호가 없다."""
    w = world(session)
    connect(session, handoff_number=HANDOFF)
    box, row = outbound(session, w.park)
    box.set_control(FakeControl())
    calls = {
        "find_contact": {"query": "이설비"},
        "propose_contact": {"name": "정새로", "role_title": "반장", "phone": NEW},
        "schedule_fact": {"activity": "철근"},
        "my_requests": {},
        "record_answer": {"question": "토요일 인원", "answer": "6명", "quote": f"6명 갑니다 {NEW} 로 연락 주세요"},
        "take_message": {"text": f"{NEW} 로 전화 달라고 함", "claimed_name": "최철근"},
        "report_from_contact": {"kind": "delay", "text": f"자재가 늦음 {NEW}", "quote": "자재가 모레 옵니다"},
        "schedule_callback": {"day_offset": 1, "hour": 15, "minute": 0},
        "mark_do_not_contact": {"reason": f"전화하지 말라고 함 {NEW}"},
        "handoff_to_human": {"reason": "asked_for_person", "note": f"{NEW} 로 연락 바람"},
        "confirm_person": {"is_person": True},
        "end_call": {"reason": "done"},
    }
    assert set(calls) == set(ALL)

    for index, (name, args) in enumerate(calls.items(), start=1):
        await box.call(name, args)
        got = [e for e in log(session, row) if e["rule"] in TOOL_EVENTS]
        assert len(got) == index, name
        assert got[-1]["rule"] == f"tool:{name}" and got[-1]["verdict"] == "allowed"

    assert {e["rule"] for e in log(session, row)} <= events.KNOWN_RULES
    for digits in (NEW_DIGITS, PHONE, HANDOFF, CHOI, LEE):
        assert not has_digits(log(session, row), digits)


async def test_bad_arguments_are_refused_without_echoing_them(session):
    world(session)
    connect(session)
    box, row = inbound(session, "sms", PHONE)

    for args in ({"query": "이설비", NEW: "x"}, {"query": NEW * 200}, {"query": "이설비", "contact_id": 3},
                 {"query": ["이설비"]}, None, [NEW]):
        r = await box.call("find_contact", args)
        assert "error" in r and "items" not in r and not has_digits(r, NEW_DIGITS)

    assert trail(session, row) == [("tool_bad_args", "blocked")] * 6
    assert all(e["detail"].startswith("tool=find_contact") for e in log(session, row))
    assert not has_digits(log(session, row), NEW_DIGITS)


async def test_ran_but_unsatisfied_is_allowed_with_outcome_detail(session):
    """돌았는데 못 해 준 것(근무시간을 못 찾은 회신·틀린 번호의 제안·0명·현장을 물음)은 거절이 아니다."""
    w = world(session)
    connect(session)
    w.park.hours_json = {"days": [], "start": "08:00", "end": "18:00"}  # 근무 시간대가 없는 사람
    box, row = inbound(session, "call", PHONE)

    back = await box.call("schedule_callback", {"day_offset": 1, "hour": 10, "minute": 0})
    new = await box.call("propose_contact", {"name": "정새로", "role_title": "반장", "phone": "12345"})
    none = await box.call("find_contact", {"query": "없는사람"})

    assert back == {"refused": "다시 연락드릴 시간을 정하지 못했습니다"}
    assert new["saved"] is False and "12345" not in json.dumps(new)
    assert none == {"items": [], "redirected": False}
    assert trail(session, row) == [("tool:schedule_callback", "allowed"), ("tool:propose_contact", "allowed"),
                                   ("tool:find_contact", "allowed")]
    assert not {e["rule"] for e in log(session, row)} & TOOL_REFUSALS
    assert all("→" in e["detail"] for e in log(session, row))
    assert count(session, OutreachCall, OutreachCall.direction == "out") == 0
    assert count(session, ContactProposal) == 0


async def test_database_trouble_is_an_error_result_not_a_crash(session, monkeypatch, caplog):
    world(session)
    connect(session)
    box, _ = inbound(session, "sms", PHONE)

    def locked(*_args, **_kwargs):
        raise OperationalError(f"UPDATE {NEW}", {}, Exception("database is locked"))

    monkeypatch.setattr(tools.outreach, "add_report", locked)
    r = await box.call("take_message", {"text": "내일 다시 연락 주세요"})

    assert set(r) == {"error"} and not has_digits(r, NEW_DIGITS)
    assert count(session, ContactReport) == 0
    assert not has_digits(caplog.text, NEW_DIGITS)


async def test_cancelled_followup_still_leaves_the_tool_event(session, monkeypatch):
    """위임 후속을 문에 넣는 도중 통화·응대가 취소돼도, 이미 한 일(메모·후속 줄)의 도구 사건은 하나 남는다."""
    world(session)
    connect(session, agent_sms="delegate")
    box, row = inbound(session, "sms", STRANGER)

    async def cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(tools.gate, "dispatch", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await box.call("take_message", {"text": "저 박현장입니다", "claimed_name": "박현장"})

    assert trail(session, row) == [("tool:take_message", "allowed")]
    assert "마치지 못함" in log(session, row)[0]["detail"]
    assert count(session, ContactReport) == 1


async def test_cancel_is_not_swallowed_when_the_event_cannot_be_written(session, monkeypatch):
    world(session)
    connect(session, agent_sms="delegate")
    box, _ = inbound(session, "sms", STRANGER)

    async def cancelled(*_args, **_kwargs):
        monkeypatch.setattr(tools.events, "record", locked)  # 후속이 도는 사이 DB 가 잠겼다
        raise asyncio.CancelledError

    def locked(*_args, **_kwargs):
        raise OperationalError("UPDATE", {}, Exception("database is locked"))

    monkeypatch.setattr(tools.gate, "dispatch", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await box.call("take_message", {"text": "저 박현장입니다", "claimed_name": "박현장"})


async def test_calls_on_one_box_run_one_at_a_time(session):
    """한 줄의 도구는 겹쳐 돌지 않는다 — 동시에 불러도 사건·결과가 부른 수만큼, 차례대로."""
    world(session)
    connect(session)
    box, row = inbound(session, "sms", PHONE)

    got = await asyncio.gather(*(box.call("record_answer", {"question": f"물음 {n}", "answer": "답", "quote": "네"})
                                 for n in range(6)))

    session.expire_all()
    assert got == [{"ok": True}] * 6 and box.results == got
    assert [answer["question"] for answer in session.get(OutreachMessage, row.id).answers_json] == [f"물음 {n}" for n in range(6)]
    assert trail(session, row) == [("tool:record_answer", "allowed")] * 6


def test_toolbox_is_built_closed(session):
    w = world(session)
    row = incoming(session, "sms", w.park)
    session.commit()
    scope = door.outbound_scope(session, w.a, w.park.id)
    good = {"names": frozenset({"take_message"}), "caller_class": "outbound"}
    Toolbox(scope, "sms", Ref("message", row.id), **good)
    for args, kwargs in (
        ((scope, "kakao", Ref("message", row.id)), good),  # 매체가 아님
        ((scope, "call", Ref("message", row.id)), good),  # 통화인데 메시지 줄
        ((scope, "sms", Ref("call", row.id)), good),  # 문자인데 통화 줄
        ((scope, "sms", Ref("message", row.id)), {**good, "names": frozenset({"change_schedule"})}),  # 묶음에 없는 이름
        ((scope, "sms", Ref("message", row.id)), {**good, "caller_class": "internal"}),  # 범위와 다른 등급
        ((scope, "sms", Ref("message", row.id)), {**good, "caller_class": "vip"}),
        (("outbound", "sms", Ref("message", row.id)), good),  # 범위가 아님
    ):
        with pytest.raises((ValueError, TypeError)):
            Toolbox(*args, **kwargs)
    with pytest.raises(TypeError):
        Toolbox(scope, "sms", Ref("message", row.id), names=frozenset({"take_message"}))  # 등급을 빼먹을 수 없다
    Toolbox(CLOSED, "sms", Ref("message", row.id), names=frozenset(), caller_class="internal")  # 닫힌 빈 범위는 어느 등급에나


# ── 범위를 다시 보는 도구 ────────────────────────────────────────────


async def test_contact_hears_own_trade_and_milestones_only(session):
    w = world(session)
    connect(session)
    box, _ = inbound(session, "call", PHONE)

    own = await box.call("schedule_fact", {"activity": "철근 배근"})
    end = await box.call("schedule_fact", {"activity": "준공"})
    other = await box.call("schedule_fact", {"activity": "마감 작업"})

    assert own == {"items": [{"id": "R", "name": f"{MARK_A} 철근 배근", "start": "2027-03-01", "finish": "2027-03-03",
                              "status": "on_plan"}]}
    assert [item["id"] for item in end["items"]] == ["Z"]
    assert other == {"refused": REFUSED}
    assert box.scope.schedule_ids == (w.a,)


async def test_refusal_text_is_same_for_missing_and_forbidden(session):
    """범위 밖 작업 · 없는 작업 · 다른 프로젝트의 작업 — 결과도 사건도 같다."""
    world(session)
    connect(session)
    box, row = inbound(session, "sms", PHONE)

    forbidden = await box.call("schedule_fact", {"activity": f"{MARK_A} 마감 작업"})
    missing = await box.call("schedule_fact", {"activity": "없는 작업 이름"})
    elsewhere = await box.call("schedule_fact", {"activity": f"{MARK_B} 철근 배근"})
    by_id = await box.call("schedule_fact", {"activity": "E"})

    assert forbidden == missing == elsewhere == by_id == {"refused": REFUSED}
    assert trail(session, row) == [("scope_denied", "blocked")] * 4
    asked = (f"{MARK_A} 마감 작업", "없는 작업 이름", f"{MARK_B} 철근 배근", "E")
    assert [e["detail"] for e in log(session, row)] == [f"tool=schedule_fact activity={name}" for name in asked]


async def test_outbound_callee_cannot_hear_other_trades(session):
    """우리가 건 통화의 상대도 자기 협력사·공종과 마일스톤까지만(all 이 아니다)."""
    w = world(session)
    connect(session)
    box, row = outbound(session, w.park)

    own = await box.call("schedule_fact", {"activity": "철근"})
    other = await box.call("schedule_fact", {"activity": "마감 작업"})

    assert [item["id"] for item in own["items"]] == ["R"]
    assert other == {"refused": REFUSED}
    assert trail(session, row) == [("tool:schedule_fact", "allowed"), ("scope_denied", "blocked")]


async def test_internal_hears_the_whole_schedule_of_the_chosen_site(session):
    w = world(session)
    connect(session)
    account(session, STRANGER)
    box, _ = inbound(session, "call", STRANGER)
    assert box.scope.caller_class == "internal" and box.scope.site_required

    first = await box.call("schedule_fact", {"activity": "마감 작업"})
    then = await box.call("schedule_fact", {"activity": "마감 작업", "site": SITE_B})
    after = await box.call("schedule_fact", {"activity": "철근"})  # 굳은 뒤에는 현장을 다시 말하지 않아도 된다

    assert first == {"ask": ASK, "sites": [SITE_A, SITE_B]}
    assert [item["name"] for item in then["items"]] == [f"{MARK_B} 마감 작업"]
    assert [item["name"] for item in after["items"]] == [f"{MARK_B} 철근 배근"]
    assert box.scope.schedule_ids == (w.b,)


async def test_multi_project_needs_site_first_then_pins(session):
    w = world(session)
    connect(session)
    park_b = who(session, w.rebar_b, "박현장", PHONE)
    box, row = inbound(session, "call", PHONE)
    assert box.scope.caller_class == "contact_multi" and row.schedule_id is None

    first = await box.call("schedule_fact", {"activity": "철근 배근"})
    wrong = await box.call("schedule_fact", {"activity": "철근 배근", "site": "다른 현장"})
    then = await box.call("schedule_fact", {"activity": "철근 배근", "site": "나래"})  # 후보 하나의 이름에 든 말
    later = await box.call("schedule_fact", {"activity": "철근 배근", "site": SITE_A})  # 굳힌 뒤에는 넓히지 못한다

    assert first == wrong == {"ask": ASK, "sites": [SITE_A, SITE_B]}
    assert [item["name"] for item in then["items"]] == [f"{MARK_B} 철근 배근"]
    assert [item["name"] for item in later["items"]] == [f"{MARK_B} 철근 배근"]
    assert box.scope.schedule_ids == (w.b,) and box.scope.contact_ids == (park_b.id,)
    assert trail(session, row) == [("tool:schedule_fact", "allowed"), ("tool:schedule_fact", "allowed"),
                                   ("site_pinned", "noted"), ("tool:schedule_fact", "allowed"),
                                   ("tool:schedule_fact", "allowed")]
    assert log(session, row)[2]["detail"] == SITE_B
    session.expire_all()
    pinned = session.get(OutreachCall, row.id)
    assert (pinned.schedule_id, pinned.contact_id) == (w.b, park_b.id)  # 그 줄도 그 현장의 대화로


async def test_unpinned_site_required_scope_gives_no_fact_at_all(session):
    """현장을 고르기 전에는 사실이 하나도 가지 않는다 — site 없이 불러도, 한 현장에만 있는 작업 이름으로 불러도."""
    w = world(session)
    connect(session)
    who(session, w.rebar_b, "박현장", PHONE)
    box, row = inbound(session, "sms", PHONE)

    for activity in ("철근 배근", f"{MARK_B} 철근 배근", f"{MARK_A} 준공", "R", "Z"):
        r = await box.call("schedule_fact", {"activity": activity})
        assert r == {"ask": ASK, "sites": [SITE_A, SITE_B]}
        assert MARK_A not in json.dumps(r, ensure_ascii=False) and "2027" not in json.dumps(r) and "2028" not in json.dumps(r)
    people = await box.call("find_contact", {"query": "박현장"})

    assert people == {"ask": ASK, "sites": [SITE_A, SITE_B]}
    assert box.scope.site_required
    assert ("site_pinned", "noted") not in trail(session, row)


async def test_site_outside_candidates_is_not_matched(session):
    """현장 이름은 그 상대의 후보 안에서만 맞춘다 — 있는 현장이어도 후보가 아니면 고를 수 없다."""
    w = world(session)
    connect(session)
    c = project(session, "다온 현장", "표식-다", date(2029, 1, 1))
    who(session, firm(session, c, "다온철근", "철근"), "박현장", PHONE)
    w.choi.phone = None
    box, row = inbound(session, "call", PHONE)  # 후보는 가람 현장·다온 현장
    assert set(box.scope.schedule_ids) == {w.a, c}

    for site in (SITE_B, "나래", "현장", "가람 현장 나래 현장", "", "가"):  # 한 글자는 한 후보에만 있어도 맞추지 않는다
        r = await box.call("schedule_fact", {"activity": "철근 배근", "site": site})
        assert r == {"ask": ASK, "sites": [SITE_A, "다온 현장"]}, site
    one = await box.call("my_requests", {"site": SITE_B})

    assert one == {"ask": ASK, "sites": [SITE_A, "다온 현장"]}
    assert box.scope.site_required and ("site_pinned", "noted") not in trail(session, row)


async def test_single_site_caller_cannot_move_to_another_site_by_naming_it(session):
    w = world(session)
    connect(session)
    box, _ = inbound(session, "sms", PHONE)

    r = await box.call("schedule_fact", {"activity": "철근 배근", "site": SITE_B})

    assert [item["name"] for item in r["items"]] == [f"{MARK_A} 철근 배근"]
    assert box.scope.schedule_ids == (w.a,)


async def test_my_requests_refuses_before_site_is_chosen(session):
    w = world(session)
    connect(session)
    park_b = who(session, w.rebar_b, "박현장", PHONE)
    message(session, w.park, status="accepted", sent_at=WORK - timedelta(days=1), body="가람 쪽 요청")
    message(session, park_b, status="accepted", sent_at=WORK - timedelta(days=1), body="나래 쪽 요청")
    box, _ = inbound(session, "call", PHONE)

    before = await box.call("my_requests", {})
    after = await box.call("my_requests", {"site": SITE_A})

    assert before == {"ask": ASK, "sites": [SITE_A, SITE_B]}
    assert [item["text"] for item in after["items"]] == ["가람 쪽 요청"]  # 두 프로젝트가 섞이지 않는다


async def test_my_requests_returns_recent_own_requests_without_numbers(session):
    w = world(session)
    connect(session)
    day = WORK - timedelta(days=2)
    message(session, w.park, status="accepted", sent_at=day, body=f"내일 3층 타설 가능하신가요 {NEW} 로 회신", activity_id="R")
    message(session, w.park, status="delivered", sent_at=day + timedelta(hours=1), body="가" * 300)
    message(session, w.park, status="draft", body="아직 보내지 않은 초안")
    message(session, w.park, status="accepted", sent_at=WORK - timedelta(days=9), body="아흐레 전 요청")
    message(session, w.park, status="accepted", sent_at=day, body="자동 답", kind="auto_reply")
    message(session, w.lee, status="accepted", sent_at=day, body="다른 사람에게 간 요청")
    message(session, w.park, direction="in", origin="peer", status="received", body="상대가 보낸 글")
    call(session, w.park, status="completed", started_at=WORK - timedelta(days=1), purpose=f"타설 인원 확인 {NEW}")
    call(session, w.park, status="draft", purpose="걸지 않은 통화")
    box, row = inbound(session, "sms", PHONE)

    r = await box.call("my_requests", {})

    assert [item["channel"] for item in r["items"]] == ["call", "sms", "sms"]
    assert r["items"][0] == {"channel": "call", "date": "11월 26일", "text": "타설 인원 확인 [번호]", "activity": None}
    assert r["items"][2] == {"channel": "sms", "date": "11월 25일", "text": "내일 3층 타설 가능하신가요 [번호] 로 회신",
                             "activity": f"{MARK_A} 철근 배근"}
    assert len(r["items"][1]["text"]) == 200
    assert not has_digits(r, NEW_DIGITS) and not has_digits(log(session, row), NEW_DIGITS)


async def test_my_requests_gives_at_most_five(session):
    w = world(session)
    connect(session)
    for n in range(8):
        message(session, w.park, status="accepted", sent_at=WORK - timedelta(hours=n + 1), body=f"요청 {n}번")
    box, _ = inbound(session, "sms", PHONE)

    r = await box.call("my_requests", {})

    assert [item["text"] for item in r["items"]] == [f"요청 {n}번" for n in range(5)]


async def test_shared_number_gets_company_scope_but_no_personal_requests(session):
    """대표번호(같은 협력사 두 사람): 그 협력사의 사실까지만, 개인에게 온 요청은 말하지 않는다."""
    w = world(session)
    connect(session)
    who(session, w.rebar_a, "김철근", PHONE)
    message(session, w.park, status="accepted", sent_at=WORK - timedelta(days=1), body="박현장에게만 간 요청")
    box, row = inbound(session, "call", PHONE)
    assert box.scope.caller_class == "shared"

    fact = await box.call("schedule_fact", {"activity": "철근"})
    other = await box.call("schedule_fact", {"activity": "마감 작업"})
    mine = await box.call("my_requests", {})

    assert [item["id"] for item in fact["items"]] == ["R"]
    assert other == {"refused": REFUSED}
    assert mine == {"refused": "개인에게 온 요청은 이 번호로 말씀드릴 수 없습니다"}
    assert trail(session, row)[-1] == ("scope_denied", "blocked")


async def test_shared_number_across_two_companies_hears_nothing(session):
    w = world(session)
    connect(session)
    who(session, w.mep_a, "김설비", PHONE)
    box, _ = inbound(session, "call", PHONE)
    assert box.scope.caller_class == "shared" and box.scope.facts == "none"

    for activity in ("철근", "마감 작업", "준공"):
        assert await box.call("schedule_fact", {"activity": activity}) == {"refused": REFUSED}
    assert await box.call("find_contact", {"query": "박현장"}) == {"items": [], "redirected": False}


async def test_find_contact_stays_in_own_company_for_callers(session):
    """받는 쪽 연락처 등급은 자기 협력사 사람만 찾는다. 다른 프로젝트 사람은 누구에게도 보이지 않는다."""
    w = world(session)
    connect(session)
    kim = who(session, w.rebar_a, "김철근", "01000000122", role_title="철근 기사")
    box, _ = inbound(session, "sms", PHONE)

    own = await box.call("find_contact", {"query": "철근"})
    other = await box.call("find_contact", {"query": "이설비"})
    elsewhere = await box.call("find_contact", {"query": "최철근"})

    assert own == {"items": [{"contact_id": kim.id, "name": "김철근", "role_title": "철근 기사", "company": "가람철근"},
                             {"contact_id": w.park.id, "name": "박현장", "role_title": "철근 반장", "company": "가람철근"}],
                   "redirected": False}
    assert other == elsewhere == {"items": [], "redirected": False}


async def test_notes_and_reasons_are_hidden_before_model(session):
    """find_contact 결과에는 note·dnc_reason 이 없고, 이름·담당·협력사 이름에 적힌 번호는 가려서 나간다."""
    w = world(session)
    connect(session)
    w.lee.note = f"개인 번호 {NEW}"
    w.lee.dnc_reason = f"{NEW} 로만 연락"
    w.lee.role_title = f"설비 소장 {NEW}"
    w.mep_a.name = f"가람설비 {NEW}"
    box, _ = outbound(session, w.park)

    r = await box.call("find_contact", {"query": "이설비"})

    assert r["items"] == [{"contact_id": w.lee.id, "name": "이설비", "role_title": "설비 소장 [번호]",
                           "company": "가람설비 [번호]"}]
    assert not has_digits(r, NEW_DIGITS) and not has_digits(r, LEE)
    assert "note" not in json.dumps(r) and "dnc" not in json.dumps(r)


async def test_scope_is_looked_at_again_on_every_call(session):
    """통화 도중 그 사람이 주소록에서 숨겨지면 다음 호출부터 아무것도 보이지 않는다."""
    w = world(session)
    connect(session)
    box, _ = inbound(session, "call", PHONE)
    assert "items" in await box.call("schedule_fact", {"activity": "철근"})

    w.park.hidden = True
    session.commit()

    assert await box.call("schedule_fact", {"activity": "철근"}) == {"refused": REFUSED}
    assert await box.call("find_contact", {"query": "박현장"}) == {"items": [], "redirected": False}
    assert box.scope.schedule_ids == ()


async def test_scope_narrows_when_a_pair_or_a_schedule_goes_away(session):
    """협력사가 숨겨지거나 연락처가 다른 협력사로 옮겨져도 그 짝은 사라진다. 내부 등급은 지워진 일정을 더 보지 않는다."""
    w = world(session)
    connect(session)
    park_b = who(session, w.rebar_b, "박현장", PHONE)
    box, _ = inbound(session, "call", PHONE)
    assert box.scope.site_required

    w.rebar_a.hidden = True
    session.commit()
    one = await box.call("schedule_fact", {"activity": "철근"})  # 남은 현장 하나 — 더 묻지 않는다

    assert [item["name"] for item in one["items"]] == [f"{MARK_B} 철근 배근"]
    assert box.scope.schedule_ids == (w.b,) and box.scope.caller_class == "contact_multi"

    park_b.company_id = w.elec_b.id
    session.commit()
    assert await box.call("schedule_fact", {"activity": "철근"}) == {"refused": REFUSED}
    assert box.scope.schedule_ids == ()

    account(session, STRANGER)
    staff, staff_row = inbound(session, "sms", STRANGER)
    session.delete(session.get(ScheduleRecord, w.a))
    session.commit()
    there = await staff.call("schedule_fact", {"activity": "철근"})  # 일정이 하나만 남았다
    session.delete(session.get(ScheduleRecord, w.b))
    session.commit()
    gone = await staff.call("schedule_fact", {"activity": "철근"})

    assert [item["name"] for item in there["items"]] == [f"{MARK_B} 철근 배근"] and staff_row.id
    assert gone == {"refused": REFUSED} and staff.scope.schedule_ids == ()


# ── 바꾸지 않음: 보고·답·제안 ────────────────────────────────────────


async def test_report_creates_open_report_and_changes_nothing(session):
    w = world(session)
    connect(session)
    box, row = inbound(session, "call", PHONE)
    before = session.get(ScheduleRecord, w.a).current_version

    r = await box.call("report_from_contact", {"kind": "delay", "text": f"철근 반입이 이틀 늦습니다 {NEW}",
                                               "quote": "모레나 들어옵니다"})

    session.expire_all()
    report = session.scalars(select(ContactReport)).one()
    assert r == {"say": "담당자가 확인하도록 전달했습니다"}
    assert (report.kind, report.status, report.medium, report.call_id, report.message_id) == ("delay", "open", "call", row.id, None)
    assert (report.schedule_id, report.contact_id) == (w.a, w.park.id)
    assert report.text == "철근 반입이 이틀 늦습니다 [번호]" and report.quote == "모레나 들어옵니다" and not report.quote_found
    assert session.get(ScheduleRecord, w.a).current_version == before
    assert count(session, DelayEvent) == 0 and count(session, Approval) == 0


async def test_record_answer_appends_to_the_row(session):
    w = world(session)
    connect(session)
    box, row = outbound(session, w.park)

    assert await box.call("record_answer", {"question": "토요일 인원", "answer": "6명", "quote": "6명 갑니다"}) == {"ok": True}
    assert await box.call("record_answer", {"question": "장비", "answer": f"{NEW} 로 문의", "quote": "모릅니다"}) == {"ok": True}

    session.expire_all()
    answers = session.get(OutreachCall, row.id).answers_json
    assert answers == [{"question": "토요일 인원", "answer": "6명", "quote": "6명 갑니다", "quote_found": False},
                       {"question": "장비", "answer": "[번호] 로 문의", "quote": "모릅니다", "quote_found": False}]


async def test_proposed_number_only_in_proposal_row(session):
    world(session)
    connect(session)
    box, row = inbound(session, "call", STRANGER)

    r = await box.call("propose_contact", {"name": "정새로", "role_title": "형틀 반장", "phone": NEW})

    session.expire_all()
    proposal = session.scalars(select(ContactProposal)).one()
    assert r["saved"] is True and not has_digits(r, NEW_DIGITS)
    assert (proposal.kind, proposal.status, proposal.name, proposal.role_title) == ("new", "pending", "정새로", "형틀 반장")
    assert (proposal.phone, proposal.call_id, proposal.message_id, proposal.schedule_id) == (NEW_DIGITS, row.id, None, None)
    assert not has_digits(log(session, row), NEW_DIGITS)
    assert count(session, Contact, Contact.phone == NEW_DIGITS) == 0  # 주소록에는 사람이 승인해야 든다
    assert count(session, ContactReport) == 0


async def test_proposed_number_is_never_put_into_the_event_at_all(session, monkeypatch):
    """가리개는 둘째 줄이다: 번호 가리기가 아무것도 못 가려도 제안의 번호는 결과·사건에 없다(값을 애초에 싣지 않는다)."""
    world(session)
    connect(session)
    box, row = inbound(session, "sms", STRANGER)
    monkeypatch.setattr(redact, "hide_phones", lambda text: text)

    r = await box.call("propose_contact", {"name": "정새로", "role_title": "형틀 반장", "phone": NEW})

    assert r["saved"] is True and not has_digits(r, NEW_DIGITS)
    assert not has_digits(log(session, row), NEW_DIGITS)
    assert "phone=[번호]" in log(session, row)[0]["detail"]


async def test_mark_do_not_contact_goes_through_number_store(session, monkeypatch):
    """수신 거부는 번호 기준 저장소 함수로만 — 번호는 줄에서 코드가 읽고, 연락처 줄을 직접 고치지 않는다."""
    w = world(session)
    connect(session)
    seen = []
    real = store.mark_do_not_contact

    def spy(session_, number, *, reason):
        seen.append((number, reason))
        return real(session_, number, reason=reason)

    monkeypatch.setattr(store, "mark_do_not_contact", spy)
    box, row = inbound(session, "sms", PHONE)

    r = await box.call("mark_do_not_contact", {"reason": f"연락하지 말라고 함 {NEW}"})

    session.expire_all()
    assert r == {"ok": True}
    assert seen == [(PHONE, "연락하지 말라고 함 [번호]")]
    assert session.scalars(select(DoNotContactNumber.number)).all() == [PHONE]
    assert store.is_do_not_contact(session, PHONE)
    assert session.get(Contact, w.park.id).do_not_contact is False and session.get(Contact, w.park.id).dnc_reason is None
    assert not has_digits(log(session, row), PHONE)


async def test_mark_do_not_contact_reads_the_number_of_a_row_without_a_contact(session):
    w = world(session)
    connect(session)
    who(session, w.rebar_a, "김철근", PHONE)  # 대표번호 — 줄에는 번호만 있다
    box, _ = inbound(session, "call", PHONE)

    assert await box.call("mark_do_not_contact", {"reason": "전화하지 말라고 함"}) == {"ok": True}
    assert store.is_do_not_contact(session, PHONE)


# ── 신원 규칙 ────────────────────────────────────────────────────────


@pytest.mark.parametrize("medium", ["sms", "call"])
async def test_claim_reply_is_same_whether_name_exists(session, medium):
    """말·글로 한 신원 주장: 그 이름이 주소록에 있든 없든 같은 글이고, 일정 내용은 가지 않는다."""
    world(session)
    connect(session)
    box, row = inbound(session, medium, STRANGER)

    known = await box.call("take_message", {"text": "저 박현장인데 다른 전화로 걸었습니다", "claimed_name": "박현장"})
    unknown = await box.call("take_message", {"text": "저 홍길동인데요", "claimed_name": "홍길동"})
    plain = await box.call("take_message", {"text": "담당자분께 전해 주세요"})

    assert known == unknown == {"say": "등록된 번호로 다시 연락드리겠습니다"}
    assert plain == {"say": "담당자가 확인 후 연락드리겠습니다"}
    assert box.scope.schedule_ids == () and box.scope.facts == "none"  # 등급도 범위도 그대로
    assert trail(session, row) == [("tool:take_message", "allowed")] * 3
    assert count(session, ContactReport, ContactReport.kind == "message") == 3


@pytest.mark.parametrize("medium", ["sms", "call"])
async def test_claim_makes_callback_draft_to_registered_number_in_same_medium(session, medium, fake_channel):
    w = world(session)
    connect(session)
    box, row = inbound(session, medium, STRANGER)

    await box.call("take_message", {"text": "저 박현장인데 다른 전화로 걸었습니다", "claimed_name": " 박현장 "})

    session.expire_all()
    model = OutreachCall if medium == "call" else OutreachMessage
    other = OutreachMessage if medium == "call" else OutreachCall
    draft = session.scalars(select(model).where(model.direction == "out")).one()
    assert (draft.schedule_id, draft.contact_id, draft.peer_number) == (w.a, w.park.id, None)  # 등록된 번호의 그 사람에게
    assert (draft.status, draft.origin, draft.send_mode) == ("draft", "agent", None)
    assert (draft.prev_call_id if medium == "call" else draft.reply_to_id) == row.id
    assert (draft.purpose if medium == "call" else draft.body).strip()
    assert count(session, other, other.direction == "out") == 0
    assert fake_channel.delivered == []  # 「승인 받기」 — 사람이 눌러야 나간다
    assert draft.fail_reason is None and events.of(session, ref_of(draft)) == []  # 문에 넣어 보지도 않는다(초안 그대로)
    assert not has_digits(log(session, row), PHONE)


async def test_claim_callback_goes_through_the_gate_when_delegated(session, fake_channel):
    w = world(session)
    connect(session, agent_sms="delegate")
    box, row = inbound(session, "sms", STRANGER)

    await box.call("take_message", {"text": "저 박현장입니다", "claimed_name": "박현장"})

    session.expire_all()
    sent = session.scalars(select(OutreachMessage).where(OutreachMessage.direction == "out")).one()
    assert (sent.status, sent.send_mode, sent.contact_id) == ("accepted", "delegated", w.park.id)
    assert [(d.channel, d.row_id) for d in fake_channel.delivered] == [("sms", sent.id)]
    assert [e["rule"] for e in events.of(session, Ref("message", sent.id))] == ["channel_choice", "delivery"]
    assert trail(session, row) == [("tool:take_message", "allowed")]


async def test_gate_refused_followup_leaves_gate_decision_and_tool_event(session, fake_channel):
    """위임이어도 회신은 나가는 문을 거친다: 시험 모드 밖 번호면 문이 자기 판정을 그 줄에, 도구는 자기 사건을 따로."""
    world(session)
    connect(session, agent_sms="delegate", test_mode=True, allow_numbers_json=[STRANGER])
    box, row = inbound(session, "sms", STRANGER)

    r = await box.call("take_message", {"text": "저 박현장입니다", "claimed_name": "박현장"})

    session.expire_all()
    held = session.scalars(select(OutreachMessage).where(OutreachMessage.direction == "out")).one()
    assert r == {"say": "등록된 번호로 다시 연락드리겠습니다"}
    assert held.status == "blocked_test" and fake_channel.delivered == []
    assert [(e["rule"], e["verdict"]) for e in events.of(session, Ref("message", held.id))] == [("test_mode", "blocked")]
    assert trail(session, row) == [("tool:take_message", "allowed")]
    assert "문이 막음" in log(session, row)[0]["detail"]


async def test_repeated_claims_make_one_callback_draft(session, fake_channel):
    """같은 주장을 되풀이해도 그 사람 앞으로 회신은 하나 — 승인 받기(초안)든 위임(이미 나감)이든."""
    w = world(session)
    conn = connect(session)
    box, _ = inbound(session, "sms", STRANGER)
    for _ in range(4):
        await box.call("take_message", {"text": "저 박현장입니다", "claimed_name": "박현장"})
    assert count(session, OutreachMessage, OutreachMessage.direction == "out") == 1

    conn.agent_sms = "delegate"
    lee_box, _ = inbound(session, "sms", "01000000133")
    for _ in range(4):
        await lee_box.call("take_message", {"text": "저 이설비입니다", "claimed_name": "이설비"})

    assert count(session, OutreachMessage, OutreachMessage.contact_id == w.lee.id) == 1
    assert len(fake_channel.delivered) == 1
    assert count(session, ContactReport) == 8  # 메모는 번번이 남는다


async def test_saying_ones_own_name_on_the_registered_number_makes_no_callback(session, fake_channel):
    world(session)
    connect(session)
    box, _ = inbound(session, "sms", PHONE)

    r = await box.call("take_message", {"text": "박현장입니다. 내일 연락 주세요", "claimed_name": "박현장"})

    assert r == {"say": "등록된 번호로 다시 연락드리겠습니다"}
    assert count(session, OutreachMessage, OutreachMessage.direction == "out") == 0
    assert count(session, ContactReport) == 1


async def test_claim_never_reaches_people_who_cannot_be_contacted(session, fake_channel):
    """수신 거부·잘못된 번호·번호 없는 사람, 그리고 이름이 같은 사람이 넷 이상이면 셋까지만."""
    w = world(session)
    connect(session)
    w.park.do_not_contact = True
    w.lee.phone_invalid = True
    w.choi.phone = None
    for n in range(5):
        who(session, w.elec_b, "동명이", f"0100000020{n}")
    box, _ = inbound(session, "sms", STRANGER)

    for name in ("박현장", "이설비", "최철근", "동명이"):
        await box.call("take_message", {"text": "저예요", "claimed_name": name})

    session.expire_all()
    drafts = session.scalars(select(OutreachMessage).where(OutreachMessage.direction == "out")).all()
    assert len(drafts) == 3 and {d.schedule_id for d in drafts} == {w.b}


# ── 회신 예약 ────────────────────────────────────────────────────────


async def test_callback_date_is_computed_by_code_and_clamped(session):
    """금요일에 「내일 22시」 → 코드가 날짜를 세고 근무시간 안으로: 월요일 08:00."""
    w = world(session)
    connect(session)
    box, row = outbound(session, w.park, purpose="타설 인원 확인", questions_json=["토요일 인원"], purpose_key="pour-3f")

    r = await box.call("schedule_callback", {"day_offset": 1, "hour": 22, "minute": 0})

    session.expire_all()
    back = session.scalars(select(OutreachCall).where(OutreachCall.id != row.id)).one()
    assert r == {"when": "11월 30일 08:00", "needs_approval": True}
    assert as_utc(back.scheduled_at) == datetime(2026, 11, 30, 8, 0, tzinfo=KST)
    assert (back.status, back.send_mode, back.origin, back.prev_call_id) == ("draft", None, "agent", row.id)
    assert (back.schedule_id, back.contact_id) == (w.a, w.park.id)
    assert (back.purpose, back.questions_json, back.purpose_key) == ("타설 인원 확인", ["토요일 인원"], "pour-3f")


@pytest.mark.parametrize("args, when", [
    ({"day_offset": 0, "hour": 15, "minute": 30}, "11월 27일 15:30"),  # 오늘 오후 — 그대로
    ({"day_offset": 0, "hour": 9, "minute": 0}, "11월 27일 10:00"),  # 이미 지난 시각 — 지금
    ({"day_offset": 3, "hour": 7, "minute": 0}, "11월 30일 08:00"),  # 월요일 새벽 — 근무 시작
    ({"day_offset": 14, "hour": 17, "minute": 59}, "12월 11일 17:59"),
])
async def test_callback_time_is_kst_and_inside_working_hours(session, args, when):
    world(session)
    connect(session)
    box, _ = inbound(session, "sms", PHONE)

    assert await box.call("schedule_callback", args) == {"when": when, "needs_approval": True}


@pytest.mark.parametrize("args", [{"day_offset": 15, "hour": 10, "minute": 0}, {"day_offset": -1, "hour": 10, "minute": 0},
                                  {"day_offset": 1, "hour": 24, "minute": 0}, {"day_offset": 1, "hour": 10, "minute": 60},
                                  {"day_offset": 1, "hour": 10}, {"when": "2026-12-01 10:00"}])
async def test_callback_takes_only_an_offset_and_a_clock_time(session, args):
    world(session)
    connect(session)
    box, row = inbound(session, "sms", PHONE)

    assert "error" in await box.call("schedule_callback", args)
    assert trail(session, row) == [("tool_bad_args", "blocked")]
    assert count(session, OutreachMessage, OutreachMessage.direction == "out") == 0


async def test_delegated_callback_is_scheduled_and_sms_callback_carries_the_original_request(session, fake_channel):
    w = world(session)
    connect(session, agent_sms="delegate")
    asked = message(session, w.park, status="accepted", sent_at=WORK - timedelta(hours=1), body="내일 3층 타설 가능하신가요")
    box, row = inbound(session, "sms", PHONE, reply_to_id=asked.id)

    r = await box.call("schedule_callback", {"day_offset": 3, "hour": 15, "minute": 0})
    again = await box.call("schedule_callback", {"day_offset": 4, "hour": 9, "minute": 0})  # 시간을 다시 말함 — 같은 줄을 고친다

    session.expire_all()
    back = session.scalars(select(OutreachMessage).where(OutreachMessage.direction == "out",
                                                         OutreachMessage.id != asked.id)).one()
    assert r == {"when": "11월 30일 15:00", "needs_approval": False}
    assert again == {"when": "12월 1일 09:00", "needs_approval": False}
    assert (back.status, back.send_mode, back.reply_to_id, back.body) == ("scheduled", "delegated", row.id, asked.body)
    assert as_utc(back.scheduled_at) == datetime(2026, 12, 1, 9, 0, tzinfo=KST)
    assert fake_channel.delivered == []  # 때가 되면 일꾼이 문에 넣는다


@pytest.mark.parametrize("medium", ["sms", "call"])
@pytest.mark.parametrize("still_delegated", [True, False])
async def test_scheduled_callback_carries_what_the_gate_needs_at_send_time(session, fake_channel, medium, still_delegated):
    """도구가 만든 예약 줄은 만들 때 위임이었을 때만 delegated 로 적힌다. 때가 돼 일꾼이 문에 넣으면 문이 처음부터 다시
    본다 — 그 사이 위임이 꺼졌으면 나가지 않고 초안으로 돌아간다(needs_approval)."""
    w = world(session)
    conn = connect(session, agent_sms="delegate", agent_call="delegate")
    box, row = inbound(session, medium, PHONE)

    r = await box.call("schedule_callback", {"day_offset": 3, "hour": 15, "minute": 0})

    session.expire_all()
    model = OutreachCall if medium == "call" else OutreachMessage
    back = session.scalars(select(model).where(model.direction == "out")).one()
    assert r == {"when": "11월 30일 15:00", "needs_approval": False}
    assert (back.status, back.send_mode, back.approved_by, back.origin) == ("scheduled", "delegated", None, "agent")
    assert (back.schedule_id, back.contact_id) == (w.a, w.park.id)

    if medium == "call":
        row.status = "completed"  # 그 통화는 끝났다(진행 중인 통화가 있으면 문이 다음 전화를 막는다)
    if not still_delegated:
        conn.agent_sms = conn.agent_call = "approve"
    session.commit()
    due = datetime(2026, 11, 30, 15, 0, tzinfo=KST)
    out = await gate.dispatch("call" if medium == "call" else "message", back.id, Actor("system", None, "일꾼", None), now=due)

    session.expire_all()
    back = session.get(model, back.id)
    if still_delegated:
        assert out.code == ("queued" if medium == "call" else "accepted") and len(fake_channel.delivered) == 1
    else:
        assert (out.code, back.status, back.send_mode) == ("needs_approval", "draft", None)
        assert fake_channel.delivered == []


@pytest.mark.parametrize("medium", ["sms", "call"])
async def test_tools_never_write_a_send_mode_without_delegation(session, fake_channel, medium):
    """「승인 받기」에서는 도구가 만든 어느 후속 줄에도 send_mode 가 없다(초안) — manual·approved 는 사람의 것이다."""
    w = world(session)
    connect(session)
    who(session, w.rebar_a, "김철근", "01000000122")
    asked = message(session, w.park, status="accepted", sent_at=WORK - timedelta(hours=1), body="내일 타설 가능하신가요")
    over = {"purpose": "타설 인원 확인"} if medium == "call" else {"reply_to_id": asked.id}
    box, _ = inbound(session, medium, PHONE, **over)

    await box.call("schedule_callback", {"day_offset": 1, "hour": 10, "minute": 0})
    await box.call("find_contact", {"query": "김철근", "redirect": True})
    await box.call("take_message", {"text": "저 최철근입니다", "claimed_name": "최철근"})

    session.expire_all()
    model = OutreachCall if medium == "call" else OutreachMessage
    made = session.scalars(select(model).where(model.direction == "out", model.origin == "agent")).all()
    assert len(made) == 3
    assert {(row.status, row.send_mode, row.approved_by) for row in made} == {("draft", None, None)}
    assert fake_channel.delivered == []


# ── 사람에게 넘기기 ──────────────────────────────────────────────────


async def test_handoff_transfers_to_the_configured_number(session):
    world(session)
    connect(session, handoff_number=HANDOFF)
    box, row = inbound(session, "call", PHONE)
    control = FakeControl()
    box.set_control(control)

    r = await box.call("handoff_to_human", {"reason": "asked_for_person", "note": "소장님과 통화하고 싶다고 함"})

    assert r == {"transferred": True, "say": "담당자가 다시 연락드리겠습니다"}
    assert control.transfers == [HANDOFF]
    assert trail(session, row) == [("tool:handoff_to_human", "allowed")]
    assert not has_digits(log(session, row), HANDOFF) and not has_digits(r, HANDOFF)
    assert count(session, ContactReport, ContactReport.kind == "message") == 1


@pytest.mark.parametrize("case", ["unknown_class", "no_number", "off_hours", "other_reason", "sms", "no_control",
                                  "blocked", "do_not_contact", "not_started", "control_error"])
async def test_handoff_transfer_needs_class_number_hours_and_allowed(session, case):
    """전환은 통화 · 사람을 찾음 · 내부·연락처 쪽 등급 · 넘길 번호 · 프로젝트 근무시간 · 문이 허락 — 모두일 때만."""
    world(session)
    connect(session, handoff_number=None if case == "no_number" else HANDOFF)
    if case == "blocked":
        session.add(BlockedNumber(number=HANDOFF, created_by="관리자"))
    if case == "do_not_contact":
        store.mark_do_not_contact(session, HANDOFF, reason="요청")
    box, row = inbound(session, "sms" if case == "sms" else "call", STRANGER if case == "unknown_class" else PHONE,
                       now=OFF if case == "off_hours" else WORK)
    control = FakeControl(accept=case != "not_started", error=RuntimeError(HANDOFF) if case == "control_error" else None)
    if case not in ("no_control", "sms"):
        box.set_control(control)

    r = await box.call("handoff_to_human", {"reason": "emergency" if case == "other_reason" else "asked_for_person",
                                            "note": "사람과 통화하고 싶다고 함"})

    assert r == {"transferred": False, "say": "담당자가 다시 연락드리겠습니다"}
    assert control.transfers == ([HANDOFF] if case in ("not_started", "control_error") else [])
    gate_event = [("blocked_or_dnc", "blocked")] if case in ("blocked", "do_not_contact") else []
    assert trail(session, row) == [*gate_event, ("tool:handoff_to_human", "allowed")]
    assert count(session, ContactReport) == 1  # 넘기지 못해도 사람에게 가는 메모는 남는다
    assert not has_digits(log(session, row), HANDOFF)


async def test_gate_refused_transfer_leaves_gate_decision_and_tool_event(session):
    """시험 모드 밖 번호로 전환 → 문의 판정(test_mode blocked) 하나 + 도구 사건(allowed) 하나 — 종류가 다른 둘."""
    world(session)
    connect(session, handoff_number=HANDOFF, test_mode=True, allow_numbers_json=[PHONE])
    box, row = inbound(session, "call", PHONE)
    control = FakeControl()
    box.set_control(control)

    r = await box.call("handoff_to_human", {"reason": "asked_for_person", "note": ""})

    assert r["transferred"] is False and control.transfers == []
    assert trail(session, row) == [("test_mode", "blocked"), ("tool:handoff_to_human", "allowed")]
    assert "문이 막음" in log(session, row)[1]["detail"]


async def test_outbound_callee_can_be_transferred(session):
    w = world(session)
    connect(session, handoff_number=HANDOFF)
    box, _ = outbound(session, w.park)
    control = FakeControl()
    box.set_control(control)

    r = await box.call("handoff_to_human", {"reason": "asked_for_person", "note": ""})

    assert r["transferred"] is True and control.transfers == [HANDOFF]


async def test_internal_staff_without_any_schedule_is_still_internal_for_transfer(session):
    """볼 일정이 없는 내부 계정: 범위는 닫혀 있어도(Scope 안의 등급은 unknown) 등급은 문이 정한 내부 그대로다."""
    connect(session, handoff_number=HANDOFF)
    account(session, STRANGER)
    box, _ = inbound(session, "call", STRANGER)
    assert box.scope.caller_class == "unknown" and box.scope.schedule_ids == ()
    control = FakeControl()
    box.set_control(control)

    r = await box.call("handoff_to_human", {"reason": "asked_for_person", "note": ""})
    nothing = await box.call("schedule_fact", {"activity": "철근"})

    assert r["transferred"] is True and control.transfers == [HANDOFF]
    assert nothing == {"refused": REFUSED}


def test_only_a_call_takes_a_control(session):
    w = world(session)
    row = incoming(session, "sms", w.park)
    session.commit()
    box = boxed(door.outbound_scope(session, w.a, w.park.id), row, "outbound")
    with pytest.raises(ValueError):
        box.set_control(FakeControl())


@pytest.mark.parametrize("number", [PHONE, STRANGER, None])
@pytest.mark.parametrize("medium", ["sms", "call"])
async def test_emergency_makes_open_report_for_any_class(session, number, medium):
    """안전사고·긴급: 누가 알렸든(연락처·모르는 번호·번호 숨김) 열린 긴급 보고 한 줄. 전환은 하지 않는다."""
    world(session)
    connect(session, handoff_number=HANDOFF)
    box, _ = inbound(session, medium, number)
    control = FakeControl()
    if medium == "call":
        box.set_control(control)

    r = await box.call("handoff_to_human", {"reason": "emergency", "note": f"3층에서 사람이 떨어졌습니다 {NEW}"})

    session.expire_all()
    report = session.scalars(select(ContactReport)).one()
    assert r == {"transferred": False, "say": "담당자가 다시 연락드리겠습니다"}
    assert (report.kind, report.status, report.medium) == ("emergency", "open", medium)
    assert report.text == "3층에서 사람이 떨어졌습니다 [번호]" and control.transfers == []


async def test_schedule_change_request_is_recorded_not_applied(session):
    w = world(session)
    connect(session)
    box, _ = inbound(session, "sms", PHONE)
    before = session.get(ScheduleRecord, w.a).current_version

    await box.call("handoff_to_human", {"reason": "schedule_change", "note": "타설을 하루 미뤄 달라고 함"})

    session.expire_all()
    report = session.scalars(select(ContactReport)).one()
    assert (report.kind, report.status) == ("change_request", "open")
    assert session.get(ScheduleRecord, w.a).current_version == before


# ── 통화에만 있는 것 ─────────────────────────────────────────────────


async def test_end_call_hangs_up_and_records_the_reason(session):
    w = world(session)
    connect(session)
    box, row = outbound(session, w.park)
    control = FakeControl()
    box.set_control(control)

    assert await box.call("confirm_person", {"is_person": False}) == {"ok": True}
    assert await box.call("end_call", {"reason": "wrong_person"}) == {"ok": True}

    assert control.hung == 1
    assert trail(session, row) == [("tool:confirm_person", "allowed"), ("tool:end_call", "allowed")]
    assert "wrong_person" in log(session, row)[1]["detail"]
    session.expire_all()
    assert session.get(Contact, w.park.id).phone_invalid is False


async def test_wrong_number_marks_the_contact_only_on_our_own_call(session):
    w = world(session)
    connect(session)
    box, _ = outbound(session, w.park)
    box.set_control(FakeControl())
    theirs, _ = inbound(session, "call", LEE, names=ALL)
    theirs.set_control(FakeControl())

    await box.call("end_call", {"reason": "wrong_number"})
    await theirs.call("end_call", {"reason": "wrong_number"})  # 걸려 온 통화에서는 주소록을 바꾸지 않는다

    session.expire_all()
    assert session.get(Contact, w.park.id).phone_invalid is True
    assert session.get(Contact, w.lee.id).phone_invalid is False


@pytest.mark.parametrize("delegated", [False, True])
async def test_voicemail_leaves_nothing_and_drafts_sms(session, fake_channel, delegated):
    """음성사서함: 남기지 않고 끊고, 문자 초안을 만든다(권한대로 — 위임이면 문을 거쳐 나간다)."""
    w = world(session)
    connect(session, agent_sms="delegate" if delegated else "approve")
    box, row = outbound(session, w.park, purpose=f"타설 인원 확인 {MARK_A}")
    control = FakeControl()
    box.set_control(control)

    r = await box.call("end_call", {"reason": "voicemail"})

    session.expire_all()
    text = session.scalars(select(OutreachMessage)).one()
    assert r == {"ok": True} and control.hung == 1
    assert (text.schedule_id, text.contact_id, text.channel, text.origin, text.call_id) == (w.a, w.park.id, "sms", "agent", row.id)
    assert text.status == ("accepted" if delegated else "draft")
    assert SITE_A in text.body and MARK_A not in text.body and not has_digits(text.body, PHONE)
    assert [(d.channel, d.row_id) for d in fake_channel.delivered] == ([("sms", text.id)] if delegated else [])
    assert count(session, ContactReport) == 0 and session.get(OutreachCall, row.id).answers_json == []


async def test_voicemail_without_a_mobile_number_drafts_nothing(session, fake_channel):
    w = world(session)
    connect(session)
    w.park.phone = "0220000199"  # 유선 번호 — 문자를 받을 수 없다
    box, _ = outbound(session, w.park)
    box.set_control(FakeControl())

    assert await box.call("end_call", {"reason": "voicemail"}) == {"ok": True}
    assert count(session, OutreachMessage) == 0


async def test_other_language_becomes_a_proposal_not_a_change(session):
    w = world(session)
    connect(session)
    box, row = outbound(session, w.park)
    box.set_control(FakeControl())

    await box.call("end_call", {"reason": "done", "language": "vi"})

    session.expire_all()
    proposal = session.scalars(select(ContactProposal)).one()
    assert (proposal.kind, proposal.language, proposal.contact_id, proposal.schedule_id, proposal.call_id) == (
        "language", "vi", w.park.id, w.a, row.id)
    assert session.get(Contact, w.park.id).language == "ko"

    same, _ = outbound(session, w.lee)
    same.set_control(FakeControl())
    await same.call("end_call", {"reason": "done", "language": "ko"})
    assert count(session, ContactProposal) == 1


# ── 담당자가 아님 → 그 사람에게 ──────────────────────────────────────


async def test_redirect_makes_followup_in_same_medium_per_permission(session, fake_channel):
    """통화 → 목적·질문을 물려받은 통화 초안, 문자 → 원래 요청 글의 문자 초안. 위임이면 문을 거친다."""
    w = world(session)
    conn = connect(session)
    kim = who(session, w.rebar_a, "김철근", "01000000122", role_title="철근 기사", language="vi")
    box, row = outbound(session, w.park, purpose="타설 인원 확인", questions_json=["토요일 인원"], purpose_key="pour-3f",
                        activity_id="R")

    r = await box.call("find_contact", {"query": "김철근", "redirect": True})

    session.expire_all()
    new_call = session.scalars(select(OutreachCall).where(OutreachCall.id != row.id)).one()
    assert r == {"items": [{"contact_id": kim.id, "name": "김철근", "role_title": "철근 기사", "company": "가람철근"}],
                 "redirected": True}
    assert (new_call.schedule_id, new_call.contact_id, new_call.status, new_call.origin) == (w.a, kim.id, "draft", "agent")
    assert (new_call.purpose, new_call.questions_json, new_call.prev_call_id, new_call.activity_id, new_call.language) == (
        "타설 인원 확인", ["토요일 인원"], row.id, "R", "vi")
    assert fake_channel.delivered == [] and count(session, OutreachMessage) == 0

    asked = message(session, w.park, status="accepted", sent_at=WORK - timedelta(hours=1), body="내일 3층 타설 가능하신가요")
    conn.agent_sms = "delegate"
    text_box, text_row = inbound(session, "sms", PHONE, reply_to_id=asked.id)

    again = await text_box.call("find_contact", {"query": "김철근", "redirect": True})
    twice = await text_box.call("find_contact", {"query": "김철근", "redirect": True})  # 되풀이해도 하나

    session.expire_all()
    new_text = session.scalars(select(OutreachMessage).where(OutreachMessage.contact_id == kim.id)).one()
    assert again["redirected"] is True and twice["redirected"] is True
    assert (new_text.body, new_text.reply_to_id, new_text.origin) == (asked.body, text_row.id, "agent")
    assert (new_text.status, new_text.send_mode) == ("accepted", "delegated")
    assert [(d.channel, d.row_id) for d in fake_channel.delivered] == [("sms", new_text.id)]
    assert count(session, OutreachCall, OutreachCall.contact_id == kim.id) == 1


async def test_redirect_needs_exactly_one_match(session, fake_channel):
    w = world(session)
    connect(session)
    who(session, w.rebar_a, "김철근", "01000000122")
    who(session, w.rebar_a, "김철수", "01000000123")
    box, row = outbound(session, w.park)

    two = await box.call("find_contact", {"query": "김철", "redirect": True})
    none = await box.call("find_contact", {"query": "없는사람", "redirect": True})
    me = await box.call("find_contact", {"query": "박현장", "redirect": True})  # 지금 통화하는 그 사람
    plain = await box.call("find_contact", {"query": "김철근"})  # redirect 를 말하지 않음

    assert len(two["items"]) == 2 and len(me["items"]) == 1 and len(plain["items"]) == 1
    assert [r["redirected"] for r in (two, none, me, plain)] == [False] * 4
    assert count(session, OutreachCall, OutreachCall.id != row.id) == 0


async def test_redirect_never_carries_a_request_of_another_site(session, fake_channel):
    """가람 현장에서 보낸 요청에 온 답인데 상대가 나래 현장 일이라고 함 → 가람 현장의 요청 글을 나래 현장 사람에게 넘기지 않는다."""
    w = world(session)
    connect(session, agent_sms="delegate")
    park_b = who(session, w.rebar_b, "박현장", PHONE)
    asked = message(session, w.park, status="accepted", sent_at=WORK - timedelta(hours=1), body=f"{MARK_A} 철근 반입 되나요")
    box, row = inbound(session, "sms", PHONE, reply_to_id=asked.id)

    r = await box.call("find_contact", {"query": "최철근", "site": SITE_B, "redirect": True})

    assert [item["name"] for item in r["items"]] == ["최철근"] and r["redirected"] is False
    assert box.scope.schedule_ids == (w.b,) and park_b.id in box.scope.contact_ids
    assert count(session, OutreachMessage, OutreachMessage.direction == "out", OutreachMessage.id != asked.id) == 0
    assert fake_channel.delivered == [] and row.id


async def test_redirect_without_anything_to_carry_makes_nothing(session, fake_channel):
    """물려줄 목적(통화)·원래 요청 글(문자)이 없으면 후속을 만들지 않는다 — 빈 통화·빈 문자가 나가지 않게."""
    w = world(session)
    connect(session, agent_sms="delegate", agent_call="delegate")
    who(session, w.rebar_a, "김철근", "01000000122")
    call_box, _ = inbound(session, "call", PHONE)
    text_box, _ = inbound(session, "sms", PHONE)

    assert (await call_box.call("find_contact", {"query": "김철근", "redirect": True}))["redirected"] is False
    assert (await text_box.call("find_contact", {"query": "김철근", "redirect": True}))["redirected"] is False
    assert count(session, OutreachCall, OutreachCall.direction == "out") == 0
    assert count(session, OutreachMessage, OutreachMessage.direction == "out") == 0
    assert fake_channel.delivered == []
