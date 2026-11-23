"""통화 API(계획 4 Task 91): 한 사람과의 통화 읽기 · 초안 쓰기 · 걸기(나가는 문) · 예약 · 취소 · 끊기 · 다시 걸기 · 결과 확정 · 녹음.

걸기는 모두 나가는 문(gate.dispatch("call", …))을 지난다 — 이 API 는 통로를 부르지 않는다. 판정은 막힌 것도 200 이고 코드·글은
문이 준 그대로. 격리: 다른 일정의 줄·연락처는 없는 것과 같은 404 이고 그때 문·일꾼을 부르지 않는다. 번호·키는 응답·오류
어디에도 없다(받아쓰기·답·사건·보고는 hide_phones). 끊기는 통화 일꾼(Task 88 runner)을 가짜로 끼워 본다.
"""

import asyncio
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.outreach import hours
from app.outreach.harness import events, gate
from app.outreach.harness.types import Actor, Delivered, Ref
from app.programs.outreach import calls_service
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.tables import User
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    ContactReport,
    NotifyConnection,
    OutreachCall,
)
from tests import schedules
from tests.helpers import auth
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY, SENTINEL_PHONE

KST = hours.KST
WORK = datetime(2026, 11, 27, 10, 0, tzinfo=KST)  # 금요일 10시 — 근무 중
OFF = datetime(2026, 11, 27, 19, 0, tzinfo=KST)  # 금요일 19시 — 근무 밖
MONDAY = datetime(2026, 11, 30, 8, 0, tzinfo=KST)  # 그 뒤 첫 근무 시작
PURPOSE = "내일 3층 타설 인원 확인"
QUESTIONS = ["내일 몇 명 오시나요?", "장비는 언제 들어오나요?"]
USER_NAME = "일반 사용자"  # conftest 의 user1
FIELD_NO = ("field_no_contacts", "현장 관리자는 연락처를 열 수 없습니다.")
PERSON_404 = ("not_found", "연락처를 찾을 수 없습니다.")
CALL_404 = ("not_found", "통화를 찾을 수 없습니다.")
NOT_DRAFT = ("not_draft", "초안만 고치거나 지울 수 있습니다.")
CALL_KEYS = {"id", "direction", "caller_class", "contact", "origin", "origin_name", "send_mode", "approved_by", "status",
             "fail_reason", "purpose", "questions", "avoid", "language", "voice_id", "duration_s", "summary_ko",
             "result_proposed", "result_confirmed", "confirmed_by", "answers", "events", "has_recording", "prev_call_id",
             "activity", "scheduled_at", "started_at", "ended_at", "created_at"}
DETAIL_KEYS = CALL_KEYS | {"transcript", "reports"}


@pytest.fixture(autouse=True)
def at_work(monkeypatch):
    monkeypatch.setattr(calls_service, "_now", lambda: WORK)


@pytest.fixture
def field_user(session) -> dict[str, str]:
    row = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


@pytest.fixture
def sid2(session) -> int:
    return schedules.store(session, schedules.sample())


@pytest.fixture
def conn(session) -> NotifyConnection:
    """기본 알림 연결: 상태 ok, 시험 모드 끔, 모두 「승인 받기」."""
    row = NotifyConnection(name="시험 연결", base_url="https://kat.invalid", secret_ciphertext="x", secret_last4="9999",
                           account_id="acct-test", sender_number="07000000000", is_default=True, status="ok",
                           test_mode=False)
    session.add(row)
    session.commit()
    return row


class FakeRunner:
    """통화 일꾼(Task 88 runner) 자리: hangup(call_id) -> bool 만. 부른 id 를 쌓는다."""

    def __init__(self, answer: bool = True) -> None:
        self.answer = answer
        self.hung: list[int] = []

    def hangup(self, call_id: int) -> bool:
        self.hung.append(call_id)
        return self.answer


@pytest.fixture
def runner(monkeypatch) -> FakeRunner:
    fake = FakeRunner()
    monkeypatch.setattr(calls_service, "_runner", lambda: fake)
    return fake


@pytest.fixture
def no_gate(monkeypatch) -> list:
    """문을 부르면 기록만 하고 실패시킨다 — 「문을 부르지 않았음」을 볼 때."""
    called: list = []

    async def refuse(*args, **kwargs):
        called.append(args)
        raise AssertionError("문을 부르면 안 됩니다")

    monkeypatch.setattr(gate, "dispatch", refuse)
    return called


def _person(session, sid: int, phone: str | None = SENTINEL_DIGITS, **over) -> int:
    company = ContactCompany(schedule_id=sid, name="가람철근", trade="철근")
    session.add(company)
    session.flush()
    who = Contact(**{"schedule_id": sid, "company_id": company.id, "name": "김공정", "role_title": "공무",
                     "phone": phone, **over})
    session.add(who)
    session.commit()
    return who.id


def _call(session, sid: int, contact_id: int | None, **over) -> OutreachCall:
    values = {"schedule_id": sid, "contact_id": contact_id, "direction": "out", "origin": "user",
              "origin_name": USER_NAME, "purpose": PURPOSE, "questions_json": list(QUESTIONS), **over}
    row = OutreachCall(**values)
    session.add(row)
    session.commit()
    return row


def _url(sid: int, rest: str = "") -> str:
    return f"/api/schedules/{sid}/outreach/calls{rest}"


def _create(client, headers, sid, contact_id, **kw):
    return client.post(_url(sid), json={"contact_id": contact_id, "purpose": PURPOSE, "questions": QUESTIONS,
                                        "avoid": [], **kw}, headers=headers)


def _reread(session, row_id: int) -> OutreachCall:
    session.expire_all()
    return session.get(OutreachCall, row_id)


def _count(session) -> int:
    session.expire_all()
    return session.scalar(select(func.count()).select_from(OutreachCall))


def _recording(sid: int, call_id: int, data: bytes = b"RIFF-fake-wav") -> str:
    folder = Settings().data_dir / "recordings" / str(sid)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{call_id}.wav"
    path.write_bytes(data)
    return str(path)


def _no_secret(*texts: str) -> None:
    for text in texts:
        digits = "".join(ch for ch in text if ch.isdigit())
        assert SENTINEL_DIGITS not in digits and SENTINEL_DIGITS[1:] not in digits, text
        assert SENTINEL_KEY not in text and "acct-test" not in text, text


# ── 앱에 올라가 있다 ──────────────────────────────────────────────────────


def test_call_routes_are_mounted_in_the_real_app(client, user, session, sid):
    """새 파일의 라우터는 프로그램의 router.py 가 import 해야 앱에 붙는다(Task 90) — 길이 404 가 아니다."""
    paths = set(client.app.openapi()["paths"])
    assert {"/api/schedules/{schedule_id}/outreach/calls", "/api/schedules/{schedule_id}/outreach/calls/{call_id}",
            "/api/schedules/{schedule_id}/outreach/calls/{call_id}/place",
            "/api/schedules/{schedule_id}/outreach/calls/{call_id}/recording"} <= paths

    r = client.get(_url(sid), headers=user)

    assert (r.status_code, r.json()) == (200, [])
    missing = client.get(_url(sid, "/12345"), headers=user)  # 앱의 뜻 없는 404 「찾을 수 없습니다.」가 아니라 이 API 의 404
    assert (missing.status_code, (missing.json()["code"], missing.json()["message"])) == (404, CALL_404)


# ── 걸기는 문을 지난다 ────────────────────────────────────────────────────


def test_place_goes_through_gate(client, user, session, sid, conn, fake_channel, monkeypatch):
    """근무 밖에 걸면 문이 blocked_hours 와 다음 근무 시작(제안)을 준다 — 통로는 부르지 않는다. 근무 안에 걸면 줄에 들어간다."""
    pid = _person(session, sid)
    draft = _create(client, user, sid, pid).json()
    monkeypatch.setattr(calls_service, "_now", lambda: OFF)

    r = client.post(_url(sid, f"/{draft['id']}/place"), headers=user)

    assert r.status_code == 200, r.json()
    outcome = r.json()["outcome"]
    assert (outcome["code"], outcome["message"]) == ("blocked_hours", "근무시간 밖입니다")
    assert datetime.fromisoformat(outcome["scheduled_at"]) == MONDAY
    call = r.json()["call"]
    assert set(call) == CALL_KEYS
    assert (call["status"], call["scheduled_at"]) == ("blocked_hours", None)
    assert [(e["rule"], e["verdict"]) for e in call["events"]] == [("working_hours", "blocked")]
    assert fake_channel.delivered == []

    monkeypatch.setattr(calls_service, "_now", lambda: WORK)
    r = client.post(_url(sid, f"/{draft['id']}/place"), headers=user)

    assert r.status_code == 200, r.json()
    assert r.json()["outcome"]["code"] == "queued"
    call = r.json()["call"]
    assert (call["status"], call["send_mode"], call["approved_by"]) == ("queued", "manual", None)
    assert [e["rule"] for e in call["events"]] == ["working_hours", "channel_choice", "delivery"]
    assert [(d.channel, d.row_id) for d in fake_channel.delivered] == [("call", draft["id"])]


def test_place_passes_the_actor_from_the_session_only(client, user, session, sid, conn, monkeypatch):
    pid = _person(session, sid)
    draft = _create(client, user, sid, pid).json()
    seen = []

    async def spy(kind, row_id, actor, *, now=None):
        seen.append((kind, row_id, actor, now))
        return gate.Outcome("not_ready", "준비 안 됨", 0)

    monkeypatch.setattr(gate, "dispatch", spy)

    r = client.post(_url(sid, f"/{draft['id']}/place"), headers=user)

    assert r.status_code == 200
    kind, row_id, actor, now = seen[0]
    assert (kind, row_id, actor.kind, actor.name, actor.role, now) == ("call", draft["id"], "user", USER_NAME, "user", WORK)


def test_agent_draft_placed_by_a_person_is_recorded_as_approved_by_that_person(client, user, session, sid, conn,
                                                                             fake_channel):
    pid = _person(session, sid)
    row = _call(session, sid, pid, origin="agent", origin_name="에이전트")

    r = client.post(_url(sid, f"/{row.id}/place"), headers=user)

    call = r.json()["call"]
    assert (call["status"], call["origin"], call["origin_name"]) == ("queued", "agent", "에이전트")
    assert (call["send_mode"], call["approved_by"]) == ("approved", USER_NAME)


def test_patch_is_not_an_approval(client, user, session, sid):
    pid = _person(session, sid)
    row = _call(session, sid, pid, origin="agent", origin_name="에이전트")

    r = client.patch(_url(sid, f"/{row.id}"), json={"purpose": "모레 타설 인원 확인"}, headers=user)

    assert r.status_code == 200, r.json()
    assert (r.json()["purpose"], r.json()["origin"], r.json()["approved_by"], r.json()["send_mode"]) == (
        "모레 타설 인원 확인", "agent", None, None)


def test_place_results_stay_three_and_unsure_is_not_an_error(client, user, session, sid, conn, fake_channel):
    pid = _person(session, sid)
    fake_channel.result = Delivered("unsure")
    first = _create(client, user, sid, pid).json()

    r = client.post(_url(sid, f"/{first['id']}/place"), headers=user)

    assert r.status_code == 200
    assert (r.json()["outcome"]["code"], r.json()["outcome"]["message"]) == ("unsure", gate.UNSURE)
    assert r.json()["call"]["status"] == "failed"

    fake_channel.result = Delivered("failed", fail_code="network")
    other = _create(client, user, sid, pid, purpose="다른 목적").json()
    gate_closed = client.post(_url(sid, f"/{other['id']}/place"), headers=user)  # 120초 안 — 문이 막는다
    assert (gate_closed.status_code, gate_closed.json()["outcome"]["code"]) == (200, "duplicate")


def test_clear_failure_shows_the_gate_sentence(client, user, session, sid, conn, fake_channel):
    pid = _person(session, sid)
    fake_channel.result = Delivered("failed", fail_code="network", fail_text=f"secret {SENTINEL_KEY} {SENTINEL_PHONE}")
    draft = _create(client, user, sid, pid).json()

    r = client.post(_url(sid, f"/{draft['id']}/place"), headers=user)

    assert r.status_code == 200
    assert (r.json()["outcome"]["code"], r.json()["call"]["fail_reason"]) == ("failed", gate.FAIL_TEXT["network"])
    _no_secret(r.text)


def test_busy_duplicate_is_passed_through_as_try_again_not_already_called(client, user, session, sid, conn,
                                                                         fake_channel):
    pid = _person(session, sid)
    row = _call(session, sid, pid, status="dialing")

    r = client.post(_url(sid, f"/{row.id}/place"), headers=user)

    assert r.status_code == 200
    assert r.json()["outcome"] == {"code": "duplicate", "message": gate.BUSY, "scheduled_at": None}
    assert "잠시 뒤 다시 해 보세요" in r.json()["outcome"]["message"]
    assert "이미 걸었" not in r.text
    assert fake_channel.delivered == []


@pytest.mark.parametrize("status", ["no_answer", "busy", "failed"])
def test_ended_call_cannot_be_placed_again(client, user, session, sid, conn, no_gate, status):
    """다시 걸기는 새 줄[리뷰 판정 14] — 끝난 줄은 409 not_sendable, 문을 부르지 않는다."""
    pid = _person(session, sid)
    row = _call(session, sid, pid, status=status)

    r = client.post(_url(sid, f"/{row.id}/place"), headers=user)

    assert (r.status_code, r.json()["code"]) == (409, "not_sendable")
    assert "[다시 걸기]" in r.json()["message"]
    assert no_gate == [] and _reread(session, row.id).status == status


@pytest.mark.parametrize("status", ["completed", "blocked_test"])
def test_other_finished_calls_are_not_sendable(client, user, session, sid, conn, no_gate, status):
    pid = _person(session, sid)
    row = _call(session, sid, pid, status=status)

    r = client.post(_url(sid, f"/{row.id}/place"), headers=user)

    assert (r.status_code, r.json()) == (409, {"code": "not_sendable", "message": "이미 처리된 통화입니다.",
                                               "detail": None})
    assert no_gate == []


def test_inbound_call_cannot_be_placed(client, user, session, sid, no_gate):
    pid = _person(session, sid)
    row = _call(session, sid, pid, direction="in", origin="peer", status="completed")

    r = client.post(_url(sid, f"/{row.id}/place"), headers=user)

    assert (r.status_code, r.json()["code"]) == (409, "not_sendable")
    assert no_gate == []


# ── 예약 · 취소 ──────────────────────────────────────────────────────────


def test_schedule_outside_hours_is_422(client, user, session, sid):
    pid = _person(session, sid)
    row = _call(session, sid, pid)

    r = client.post(_url(sid, f"/{row.id}/schedule"), json={"at": OFF.isoformat()}, headers=user)

    assert (r.status_code, r.json()["code"], r.json()["message"]) == (422, "outside_hours",
                                                                      "근무시간 안의 시각을 골라 주세요")
    row = _reread(session, row.id)
    assert (row.status, row.scheduled_at, row.send_mode) == ("draft", None, None)


def test_schedule_follows_the_persons_own_hours(client, user, session, sid):
    pid = _person(session, sid, hours_json={"days": [0, 1, 2, 3, 4], "start": "13:00", "end": "17:00"})
    row = _call(session, sid, pid)
    morning = MONDAY + timedelta(hours=2)  # 월 10시 — 기본 근무시간 안이지만 이 사람은 13시부터

    r = client.post(_url(sid, f"/{row.id}/schedule"), json={"at": morning.isoformat()}, headers=user)

    assert (r.status_code, r.json()["code"]) == (422, "outside_hours")


def test_schedule_in_the_past_is_422(client, user, session, sid):
    pid = _person(session, sid)
    row = _call(session, sid, pid)

    r = client.post(_url(sid, f"/{row.id}/schedule"), json={"at": (WORK - timedelta(hours=1)).isoformat()},
                    headers=user)

    assert (r.status_code, r.json()["code"]) == (422, "past_time")


def test_schedule_without_a_time_zone_is_422(client, user, session, sid):
    pid = _person(session, sid)
    row = _call(session, sid, pid)

    r = client.post(_url(sid, f"/{row.id}/schedule"), json={"at": "2026-11-30T10:00:00"}, headers=user)

    assert r.status_code == 422


def test_schedule_and_cancel(client, user, session, sid, conn, fake_channel, no_gate):
    """예약은 문(gate.schedule)을 지나 사람의 결정을 적는다 — 에이전트 초안은 approved + 누른 사람. 취소는 초안으로, 모두 비운다."""
    pid = _person(session, sid)
    row = _call(session, sid, pid, origin="agent", origin_name="에이전트", status="blocked_hours",
                fail_reason="근무시간 밖입니다")
    at = MONDAY + timedelta(hours=2)

    r = client.post(_url(sid, f"/{row.id}/schedule"), json={"at": at.isoformat()}, headers=user)

    assert r.status_code == 200, r.json()
    call = r.json()
    assert (call["status"], datetime.fromisoformat(call["scheduled_at"])) == ("scheduled", at)
    assert (call["send_mode"], call["approved_by"], call["fail_reason"]) == ("approved", USER_NAME, None)
    assert [(e["rule"], e["verdict"]) for e in call["events"]] == [("working_hours", "noted")]

    r = client.post(_url(sid, f"/{row.id}/cancel"), headers=user)

    assert r.status_code == 200, r.json()
    assert (r.json()["status"], r.json()["scheduled_at"], r.json()["send_mode"], r.json()["approved_by"]) == (
        "draft", None, None, None)
    row = _reread(session, row.id)
    assert (row.status, row.scheduled_at, row.send_mode, row.approved_by) == ("draft", None, None, None)
    assert no_gate == []

    again = client.post(_url(sid, f"/{row.id}/cancel"), headers=user)
    assert (again.status_code, again.json()["code"], again.json()["message"]) == (409, "not_scheduled",
                                                                                  "예약된 통화가 아닙니다.")


def test_schedule_leaves_no_earlier_approval_on_the_row(client, user, session, sid, conn, fake_channel):
    """사람의 초안을 다른 시각으로 다시 예약하면 manual — 앞서 적힌 승인한 사람이 남지 않는다."""
    pid = _person(session, sid)
    row = _call(session, sid, pid, status="scheduled", scheduled_at=MONDAY + timedelta(hours=1), send_mode="approved",
                approved_by="누군가")

    r = client.post(_url(sid, f"/{row.id}/schedule"), json={"at": (MONDAY + timedelta(hours=3)).isoformat()},
                    headers=user)

    assert r.status_code == 200, r.json()
    assert (r.json()["send_mode"], r.json()["approved_by"]) == ("manual", None)
    row = _reread(session, row.id)
    assert (row.status, row.send_mode, row.approved_by) == ("scheduled", "manual", None)


@pytest.mark.parametrize("origin", ["user", "agent"])
def test_a_persons_schedule_is_placed_when_it_is_due(client, user, session, sid, conn, fake_channel, origin):
    """끝에서 끝: 사람이 예약 → 때가 되면 일꾼(system)이 문에 넣고 → 줄에 들어간다(초안으로 돌아가지 않는다)."""
    pid = _person(session, sid)
    row = _call(session, sid, pid, origin=origin, origin_name=USER_NAME if origin == "user" else "에이전트")
    at = MONDAY + timedelta(hours=2)
    assert client.post(_url(sid, f"/{row.id}/schedule"), json={"at": at.isoformat()}, headers=user).status_code == 200

    outcome = asyncio.run(gate.dispatch("call", row.id, Actor("system", None, "통화 일꾼", None), now=at))

    assert outcome.code == "queued", outcome
    row = _reread(session, row.id)
    assert (row.status, row.send_mode, row.approved_by) == (
        ("queued", "manual", None) if origin == "user" else ("queued", "approved", USER_NAME))
    assert [(d.channel, d.row_id) for d in fake_channel.delivered] == [("call", row.id)]


def test_schedule_of_a_call_that_could_never_go_out_is_409_with_the_gates_message(client, user, session, sid, conn,
                                                                                     fake_channel):
    """예약도 문의 앞 확인을 지난다 — 시험 모드에 허용 번호가 아니면 「예약됨」이 아니라 409, 줄은 초안 그대로."""
    conn.test_mode = True
    session.commit()
    pid = _person(session, sid)
    row = _call(session, sid, pid)

    r = client.post(_url(sid, f"/{row.id}/schedule"), json={"at": (MONDAY + timedelta(hours=1)).isoformat()},
                    headers=user)

    assert (r.status_code, r.json()["code"], r.json()["message"]) == (409, "not_schedulable",
                                                                      "시험 모드라 허용한 번호에만 연락합니다")
    row = _reread(session, row.id)
    assert (row.status, row.scheduled_at, row.send_mode) == ("draft", None, None)
    assert fake_channel.delivered == []


def test_schedule_the_gate_refuses_is_409_with_its_message(client, user, session, sid, monkeypatch):
    pid = _person(session, sid)
    row = _call(session, sid, pid)
    monkeypatch.setattr(gate, "schedule", lambda *a, **k: gate.Outcome("duplicate", gate.BUSY, 6))

    r = client.post(_url(sid, f"/{row.id}/schedule"), json={"at": (MONDAY + timedelta(hours=1)).isoformat()},
                    headers=user)

    assert (r.status_code, r.json()["code"], r.json()["message"]) == (409, "not_schedulable", gate.BUSY)


def test_schedule_passes_the_session_user_to_the_gate(client, user, session, sid, monkeypatch):
    pid = _person(session, sid)
    row = _call(session, sid, pid)
    at = MONDAY + timedelta(hours=1)
    seen = []

    def spy(kind, row_id, actor, when, *, now=None):
        seen.append((kind, row_id, actor.kind, actor.name, actor.role, when, now))
        return gate.Outcome("scheduled", "예약했습니다", 3, when)

    monkeypatch.setattr(gate, "schedule", spy)

    client.post(_url(sid, f"/{row.id}/schedule"), json={"at": at.isoformat()}, headers=user)

    assert seen == [("call", row.id, "user", USER_NAME, "user", at, WORK)]


@pytest.mark.parametrize("status", ["queued", "dialing", "completed", "no_answer"])
def test_only_drafts_and_held_calls_can_be_scheduled(client, user, session, sid, status):
    pid = _person(session, sid)
    row = _call(session, sid, pid, status=status)

    r = client.post(_url(sid, f"/{row.id}/schedule"), json={"at": (MONDAY + timedelta(hours=1)).isoformat()},
                    headers=user)

    assert (r.status_code, r.json()["code"]) == (409, "not_schedulable")
    assert _reread(session, row.id).status == status


# ── 끊기 ─────────────────────────────────────────────────────────────────


def test_hangup_live_call(client, user, session, sid, runner):
    pid = _person(session, sid)
    live = _call(session, sid, pid, status="in_call")
    done = _call(session, sid, pid, status="completed")

    r = client.post(_url(sid, f"/{live.id}/hangup"), headers=user)

    assert r.status_code == 200, r.json()
    assert r.json()["id"] == live.id and set(r.json()) == CALL_KEYS
    assert runner.hung == [live.id]

    r = client.post(_url(sid, f"/{done.id}/hangup"), headers=user)

    assert (r.status_code, r.json()["code"], r.json()["message"]) == (409, "not_live", "진행 중인 통화가 아닙니다.")
    assert runner.hung == [live.id]


def test_hangup_the_runner_does_not_hold_is_409(client, user, session, sid, runner):
    runner.answer = False
    pid = _person(session, sid)
    live = _call(session, sid, pid, status="dialing")

    r = client.post(_url(sid, f"/{live.id}/hangup"), headers=user)

    assert (r.status_code, r.json()["code"]) == (409, "not_live")
    assert runner.hung == [live.id]


# ── 다시 걸기 ────────────────────────────────────────────────────────────


def test_redial_makes_new_draft_not_a_call(client, user, session, sid, conn, no_gate, runner):
    pid = _person(session, sid)
    old = _call(session, sid, pid, status="no_answer", avoid_json=["단가"], language="en", voice_id="v-1",
                purpose_key="k1", activity_id="A", send_mode="approved", approved_by="누군가", origin="agent",
                origin_name="에이전트", summary_ko="받지 않음", fail_reason="받지 않음")
    before = _count(session)

    r = client.post(_url(sid, f"/{old.id}/redial"), headers=user)

    assert r.status_code == 200, r.json()
    new = r.json()
    assert new["id"] != old.id and _count(session) == before + 1
    assert (new["status"], new["origin"], new["origin_name"], new["send_mode"], new["approved_by"]) == (
        "draft", "user", USER_NAME, None, None)
    assert (new["purpose"], new["questions"], new["avoid"], new["language"], new["voice_id"]) == (
        PURPOSE, QUESTIONS, ["단가"], "en", "v-1")
    assert (new["activity"], new["summary_ko"], new["fail_reason"]) == ({"id": "A", "name": "작업 A"}, "", None)
    row = _reread(session, new["id"])
    assert (row.retry_of, row.contact_id, row.purpose_key, row.direction) == (old.id, pid, "k1", "out")
    assert _reread(session, old.id).status == "no_answer"
    assert no_gate == [] and runner.hung == []


@pytest.mark.parametrize("status", ["draft", "scheduled", "queued", "in_call", "completed"])
def test_redial_only_after_no_answer_busy_or_failure(client, user, session, sid, status):
    pid = _person(session, sid)
    old = _call(session, sid, pid, status=status)
    before = _count(session)

    r = client.post(_url(sid, f"/{old.id}/redial"), headers=user)

    assert (r.status_code, r.json()["code"]) == (409, "not_redialable")
    assert _count(session) == before


# ── 결과 확정 ────────────────────────────────────────────────────────────


def test_confirm_records_who(client, user, admin, session, sid):
    pid = _person(session, sid)
    row = _call(session, sid, pid, status="completed", result_proposed="내일 6명 투입")

    r = client.post(_url(sid, f"/{row.id}/confirm"), json={"result": "내일 6명 투입 확정"}, headers=user)

    assert r.status_code == 200, r.json()
    assert (r.json()["result_confirmed"], r.json()["confirmed_by"], r.json()["result_proposed"]) == (
        "내일 6명 투입 확정", USER_NAME, "내일 6명 투입")

    r = client.post(_url(sid, f"/{row.id}/confirm"), json={"result": "내일 5명", "confirmed_by": "남의 이름"},
                    headers=admin)
    assert r.status_code == 422  # 확정한 사람은 요청이 아니라 로그인한 사람

    r = client.post(_url(sid, f"/{row.id}/confirm"), json={"result": "내일 5명"}, headers=admin)
    row = _reread(session, row.id)
    assert (row.result_confirmed, row.confirmed_by) == ("내일 5명", "관리자")


@pytest.mark.parametrize("status", ["draft", "in_call", "no_answer"])
def test_confirm_needs_a_completed_call(client, user, session, sid, status):
    pid = _person(session, sid)
    row = _call(session, sid, pid, status=status)

    r = client.post(_url(sid, f"/{row.id}/confirm"), json={"result": "확정"}, headers=user)

    assert (r.status_code, r.json()["code"]) == (409, "not_completed")
    assert _reread(session, row.id).result_confirmed is None


def test_confirm_rejects_hidden_characters(client, user, session, sid):
    pid = _person(session, sid)
    row = _call(session, sid, pid, status="completed")

    r = client.post(_url(sid, f"/{row.id}/confirm"), json={"result": "확정\u202e"}, headers=user)

    assert (r.status_code, r.json()["code"]) == (422, "invalid_text")


# ── 녹음 ─────────────────────────────────────────────────────────────────


def test_recording_needs_role_and_project(client, user, field_user, session, sid, sid2):
    pid = _person(session, sid)
    row = _call(session, sid, pid, status="completed")
    row.recording_path = _recording(sid, row.id, b"RIFF-call-audio")
    session.commit()
    url = _url(sid, f"/{row.id}/recording")

    assert client.get(url).status_code == 401
    r = client.get(url, headers=field_user)
    assert (r.status_code, (r.json()["code"], r.json()["message"])) == (403, FIELD_NO)
    other = client.get(_url(sid2, f"/{row.id}/recording"), headers=user)
    assert (other.status_code, (other.json()["code"], other.json()["message"])) == (404, CALL_404)

    r = client.get(url, headers=user)

    assert r.status_code == 200
    assert r.content == b"RIFF-call-audio"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-type"] == "audio/wav"
    assert f"call-{row.id}.wav" in r.headers["content-disposition"]
    _no_secret(*(f"{k}: {v}" for k, v in r.headers.items()))


def test_no_recording_is_the_same_404_as_not_found(client, user, session, sid):
    pid = _person(session, sid)
    none = _call(session, sid, pid, status="completed")
    gone = _call(session, sid, pid, status="completed",
                 recording_path=str(Settings().data_dir / "recordings" / str(sid) / "missing.wav"))

    for row in (none, gone):
        r = client.get(_url(sid, f"/{row.id}/recording"), headers=user)
        assert (r.status_code, (r.json()["code"], r.json()["message"])) == (404, CALL_404)
    assert client.get(_url(sid, f"/{none.id}"), headers=user).json()["has_recording"] is False


def test_recording_outside_its_schedule_folder_is_not_served(client, user, session, sid, sid2, tmp_path):
    pid = _person(session, sid)
    other_project = _recording(sid2, 999, b"other")
    outside = tmp_path / "secret.wav"
    outside.write_bytes(b"secret")
    for path in (other_project, str(outside), str(Settings().data_dir / "recordings" / str(sid) / ".." / str(sid2)
                                                  / "999.wav")):
        row = _call(session, sid, pid, status="completed", recording_path=path)

        r = client.get(_url(sid, f"/{row.id}/recording"), headers=user)

        assert (r.status_code, r.json()["code"]) == (404, "not_found")
        assert client.get(_url(sid, f"/{row.id}"), headers=user).json()["has_recording"] is False


# ── 읽기 ─────────────────────────────────────────────────────────────────


def test_list_and_detail_shapes_hide_numbers_everywhere(client, user, session, sid, conn):
    pid = _person(session, sid)
    other = _person(session, sid, phone="01000000200", name="이다른")
    row = _call(session, sid, pid, status="completed", duration_s=95, summary_ko=f"{SENTINEL_PHONE} 로 회신 요청",
                result_proposed=f"내일 6명 · {SENTINEL_PHONE}", caller_class="outbound", activity_id="A",
                transcript_json=[{"role": "agent", "text": "안녕하세요", "t": 0.5},
                                 {"role": "peer", "text": f"제 번호는 {SENTINEL_PHONE} 입니다", "t": 3.0}],
                answers_json=[{"question": QUESTIONS[0], "answer": f"6명, 연락은 {SENTINEL_PHONE}",
                               "quote": f"{SENTINEL_PHONE} 로", "quote_found": True}])
    events.record(session, Ref("call", row.id), "hangup_by_person", "noted", f"끊음 {SENTINEL_PHONE}")
    session.commit()
    session.add(ContactReport(schedule_id=sid, medium="call", call_id=row.id, contact_id=pid, kind="delay",
                              text=f"하루 늦음 {SENTINEL_PHONE}", quote=f"늦어요 {SENTINEL_PHONE}", quote_found=True))
    session.add(ContactReport(schedule_id=sid, medium="sms", message_id=1, contact_id=pid, kind="other", text="문자"))
    session.commit()
    _call(session, sid, other)

    listed = client.get(_url(sid), params={"contact_id": pid}, headers=user)

    assert listed.status_code == 200, listed.json()
    assert [c["id"] for c in listed.json()] == [row.id]
    item = listed.json()[0]
    assert set(item) == CALL_KEYS
    assert item["contact"] == {"id": pid, "name": "김공정", "role_title": "공무", "company": "가람철근"}
    assert (item["caller_class"], item["duration_s"], item["questions"], item["activity"]) == (
        "outbound", 95, QUESTIONS, {"id": "A", "name": "작업 A"})
    assert item["answers"] == [{"question": QUESTIONS[0], "answer": "6명, 연락은 [번호]", "quote": "[번호] 로",
                                "quote_found": True}]
    assert set(item["events"][0]) == {"rule", "verdict", "detail", "at"}
    assert len(client.get(_url(sid), headers=user).json()) == 2

    detail = client.get(_url(sid, f"/{row.id}"), headers=user)

    assert detail.status_code == 200, detail.json()
    body = detail.json()
    assert set(body) == DETAIL_KEYS
    assert body["transcript"] == [{"role": "agent", "text": "안녕하세요", "t": 0.5},
                                  {"role": "peer", "text": "제 번호는 [번호] 입니다", "t": 3.0}]
    assert [(r["kind"], r["text"], r["quote"]) for r in body["reports"]] == [("delay", "하루 늦음 [번호]", "늦어요 [번호]")]
    assert body["summary_ko"] == "[번호] 로 회신 요청"
    for response in (listed, detail):
        _no_secret(response.text)


def test_list_of_a_person_of_another_project_is_404(client, user, session, sid, sid2):
    pid2 = _person(session, sid2)

    r = client.get(_url(sid), params={"contact_id": pid2}, headers=user)

    assert (r.status_code, (r.json()["code"], r.json()["message"])) == (404, PERSON_404)


def test_list_is_newest_first(client, user, session, sid):
    pid = _person(session, sid)
    ids = [_call(session, sid, pid).id for _ in range(3)]

    r = client.get(_url(sid), params={"contact_id": pid}, headers=user)

    assert [c["id"] for c in r.json()] == ids[::-1]


def test_field_manager_is_403_and_anonymous_401(client, field_user, session, sid):
    assert client.get(_url(sid)).status_code == 401
    r = client.get(_url(sid), headers=field_user)
    assert (r.status_code, (r.json()["code"], r.json()["message"])) == (403, FIELD_NO)


# ── 격리 ─────────────────────────────────────────────────────────────────


def test_calls_of_other_project_are_404(client, user, session, sid, sid2, conn, fake_channel, no_gate, runner):
    pid = _person(session, sid)
    row = _call(session, sid, pid, status="draft")
    live = _call(session, sid, pid, status="in_call")
    done = _call(session, sid, pid, status="completed", recording_path=_recording(sid, 1))
    ended = _call(session, sid, pid, status="no_answer")
    before = _count(session)
    at = {"at": (MONDAY + timedelta(hours=1)).isoformat()}

    attempts = [
        client.get(_url(sid2, f"/{row.id}"), headers=user),
        client.patch(_url(sid2, f"/{row.id}"), json={"purpose": "바꿈"}, headers=user),
        client.delete(_url(sid2, f"/{row.id}"), headers=user),
        client.post(_url(sid2, f"/{row.id}/place"), headers=user),
        client.post(_url(sid2, f"/{row.id}/schedule"), json=at, headers=user),
        client.post(_url(sid2, f"/{row.id}/cancel"), headers=user),
        client.post(_url(sid2, f"/{live.id}/hangup"), headers=user),
        client.post(_url(sid2, f"/{ended.id}/redial"), headers=user),
        client.post(_url(sid2, f"/{done.id}/confirm"), json={"result": "확정"}, headers=user),
        client.get(_url(sid2, f"/{done.id}/recording"), headers=user),
        client.post(_url(sid, "/999999/place"), headers=user),
    ]

    for r in attempts:
        assert (r.status_code, (r.json()["code"], r.json()["message"])) == (404, CALL_404), r.request.url
    assert no_gate == [] and runner.hung == [] and fake_channel.delivered == []
    assert _count(session) == before
    assert (_reread(session, row.id).purpose, _reread(session, done.id).result_confirmed) == (PURPOSE, None)


def test_create_for_a_person_of_another_project_is_404_and_makes_nothing(client, user, session, sid, sid2):
    pid2 = _person(session, sid2)

    r = _create(client, user, sid, pid2)

    assert (r.status_code, (r.json()["code"], r.json()["message"])) == (404, PERSON_404)
    assert _count(session) == 0


# ── 초안 ─────────────────────────────────────────────────────────────────


def test_create_draft_shape(client, user, session, sid, no_gate):
    pid = _person(session, sid, language="vi")

    r = _create(client, user, sid, pid, avoid=["단가"], activity_id="A")

    assert r.status_code == 200, r.json()
    call = r.json()
    assert set(call) == CALL_KEYS
    assert (call["status"], call["direction"], call["origin"], call["origin_name"]) == ("draft", "out", "user", USER_NAME)
    assert (call["purpose"], call["questions"], call["avoid"], call["language"], call["voice_id"]) == (
        PURPOSE, QUESTIONS, ["단가"], "vi", None)
    assert (call["events"], call["answers"], call["has_recording"], call["result_confirmed"]) == ([], [], False, None)
    assert no_gate == []
    row = _reread(session, call["id"])
    assert row.purpose_key and row.schedule_id == sid and row.contact_id == pid


def test_same_purpose_gets_the_same_purpose_key(client, user, session, sid):
    """같은 목적의 두 초안은 같은 손잡이 — 문이 「같은 목적의 전화」를 막는다[리뷰 판정 8]."""
    pid = _person(session, sid)
    a = _create(client, user, sid, pid).json()["id"]
    b = _create(client, user, sid, pid, purpose=f"  {PURPOSE} ").json()["id"]
    c = _create(client, user, sid, pid, purpose="다른 목적").json()["id"]

    keys = [_reread(session, i).purpose_key for i in (a, b, c)]

    assert keys[0] == keys[1] != keys[2]


def test_second_call_with_the_same_purpose_is_stopped_by_the_gate(client, user, session, sid, conn, fake_channel):
    pid = _person(session, sid)
    first = _create(client, user, sid, pid).json()["id"]
    second = _create(client, user, sid, pid).json()["id"]
    client.post(_url(sid, f"/{first}/place"), headers=user)
    session.execute(OutreachCall.__table__.update().where(OutreachCall.id == first).values(status="completed"))
    session.commit()

    r = client.post(_url(sid, f"/{second}/place"), headers=user)

    assert (r.json()["outcome"]["code"], r.json()["call"]["status"]) == ("duplicate", "draft")
    assert len(fake_channel.delivered) == 1


@pytest.mark.parametrize("body", [
    {"purpose": ""},
    {"purpose": "x" * 501},
    {"questions": ["q"] * 11},
    {"questions": [""]},
    {"language": "jp"},
    {"status": "queued"},
    {"origin": "agent"},
    {"contact_id": "1"},
])
def test_bad_draft_input_is_422(client, user, session, sid, body):
    pid = _person(session, sid)

    r = client.post(_url(sid), json={"contact_id": pid, "purpose": PURPOSE, "questions": [], "avoid": [], **body},
                    headers=user)

    assert r.status_code == 422
    assert _count(session) == 0


@pytest.mark.parametrize("field", ["purpose", "questions", "avoid"])
def test_hidden_characters_in_draft_text_are_422(client, user, session, sid, field):
    pid = _person(session, sid)
    value = "확인\u202e" if field == "purpose" else ["확인\u2066"]

    r = _create(client, user, sid, pid, **{field: value})

    assert (r.status_code, r.json()["code"], r.json()["detail"]) == (422, "invalid_text", {"field": field})
    assert _count(session) == 0


def test_unknown_activity_is_404(client, user, session, sid):
    pid = _person(session, sid)

    r = _create(client, user, sid, pid, activity_id="없는작업")

    assert (r.status_code, r.json()["message"]) == (404, "작업을 찾을 수 없습니다.")


def test_patch_and_delete_drafts_only(client, user, session, sid):
    pid = _person(session, sid)
    draft = _call(session, sid, pid, purpose_key="old", activity_id="A")
    queued = _call(session, sid, pid, status="queued")

    r = client.patch(_url(sid, f"/{draft.id}"), json={"questions": ["새 질문"], "activity_id": None,
                                                     "voice_id": "v-2"}, headers=user)

    assert r.status_code == 200, r.json()
    assert (r.json()["questions"], r.json()["activity"], r.json()["voice_id"], r.json()["purpose"]) == (
        ["새 질문"], None, "v-2", PURPOSE)
    assert _reread(session, draft.id).purpose_key == "old"  # 목적을 바꾸지 않았으면 손잡이도 그대로

    r = client.patch(_url(sid, f"/{draft.id}"), json={"purpose": "다른 목적"}, headers=user)
    assert _reread(session, draft.id).purpose_key not in ("old", "")

    for r in (client.patch(_url(sid, f"/{queued.id}"), json={"purpose": "바꿈"}, headers=user),
              client.delete(_url(sid, f"/{queued.id}"), headers=user)):
        assert (r.status_code, (r.json()["code"], r.json()["message"])) == (409, NOT_DRAFT)
    assert _reread(session, queued.id).purpose == PURPOSE

    assert client.patch(_url(sid, f"/{draft.id}"), json={"purpose": None}, headers=user).status_code == 422
    assert client.patch(_url(sid, f"/{draft.id}"), json={"status": "queued"}, headers=user).status_code == 422

    r = client.delete(_url(sid, f"/{draft.id}"), headers=user)
    assert r.status_code == 204
    assert _reread(session, draft.id) is None


def test_errors_carry_no_number_or_key(client, user, session, sid, conn, fake_channel):
    pid = _person(session, sid)
    bad = client.post(_url(sid), json={"contact_id": pid, "purpose": SENTINEL_PHONE * 40, "questions": [],
                                       "avoid": [SENTINEL_KEY * 20]}, headers=user)
    assert bad.status_code == 422
    _no_secret(json.dumps(bad.json(), ensure_ascii=False))


# ── 사람이 쓴 글의 번호(Task 92 고침 1) ────────────────────────────────────────
# 화면이 가리개를 따로 갖지 않게: 쓰기는 번호가 든 글을 422 has_phone 로 막고, 읽기는 사람이 쓴 글도 hide_phones 를 거친다.
PHONE_FORMS = [SENTINEL_PHONE, "+82 10-0000-0199", "(010)0000-0199", "０１０-００００-０１９９", "010 0000 0199", "01000000199"]


@pytest.mark.parametrize("form", PHONE_FORMS)
@pytest.mark.parametrize("field", ["purpose", "questions", "avoid"])
def test_a_draft_with_a_phone_number_is_refused(client, user, session, sid, form, field):
    pid = _person(session, sid)
    before = _count(session)
    text = f"{form} 로 다시 연락"
    body = {"purpose": text} if field == "purpose" else {field: [text]}

    made = _create(client, user, sid, pid, **body)
    draft = _call(session, sid, pid)
    patched = client.patch(_url(sid, f"/{draft.id}"), json=body, headers=user)

    for r in (made, patched):
        assert (r.status_code, r.json()["code"], r.json()["detail"]) == (422, "has_phone", {"field": field}), r.json()
        assert r.json()["message"] == "전화번호는 넣을 수 없습니다 — 연락처에서 고릅니다"
        _no_secret(json.dumps(r.json(), ensure_ascii=False))
    assert _count(session) == before + 1  # 만들기는 줄을 남기지 않았다(고치기용 초안 하나뿐)
    assert (_reread(session, draft.id).purpose, _reread(session, draft.id).questions_json) == (PURPOSE, QUESTIONS)


@pytest.mark.parametrize("form", PHONE_FORMS)
def test_a_confirmed_result_with_a_phone_number_is_refused(client, user, session, sid, form):
    pid = _person(session, sid)
    row = _call(session, sid, pid, status="completed")

    r = client.post(_url(sid, f"/{row.id}/confirm"), json={"result": f"회신은 {form}"}, headers=user)

    assert (r.status_code, r.json()["code"], r.json()["detail"]) == (422, "has_phone", {"field": "result"})
    assert _reread(session, row.id).result_confirmed is None


def test_dates_times_and_counts_are_not_phone_numbers(client, user, session, sid):
    pid = _person(session, sid)
    r = _create(client, user, sid, pid, purpose="A1210 11/30 08:00 6명 확인", questions=["2026-11-24 반입분 120톤?"])
    assert r.status_code == 200, r.json()
    assert (r.json()["purpose"], r.json()["questions"]) == ("A1210 11/30 08:00 6명 확인", ["2026-11-24 반입분 120톤?"])


def test_stored_text_written_by_people_is_masked_in_every_answer(client, user, session, sid):
    """고침 전에 저장된 줄(또는 에이전트 도구가 쓴 초안)에 번호가 있어도 응답에는 가린 꼴만."""
    pid = _person(session, sid)
    row = _call(session, sid, pid, status="completed", purpose=f"{SENTINEL_PHONE} 로 확인",
                questions_json=["+82 10-0000-0199 는 누구?"], avoid_json=["０１０-００００-０１９９"],
                result_proposed=f"회신 {SENTINEL_PHONE}", result_confirmed="확정 (010)0000-0199")

    for r in (client.get(_url(sid), params={"contact_id": pid}, headers=user), client.get(_url(sid, f"/{row.id}"), headers=user)):
        assert r.status_code == 200
        text = json.dumps(r.json(), ensure_ascii=False)
        _no_secret(text)
        assert "０１０" not in text
    got = client.get(_url(sid, f"/{row.id}"), headers=user).json()
    assert (got["purpose"], got["questions"], got["avoid"], got["result_proposed"], got["result_confirmed"]) == (
        "[번호] 로 확인", ["[번호] 는 누구?"], ["[번호]"], "회신 [번호]", "확정 [번호]")


# ── 후속: 번호가 남은 옛 줄은 걸기·예약 전에 고치게 ─────────────────────────────
@pytest.mark.parametrize("field", ["purpose", "questions_json", "avoid_json"])
@pytest.mark.parametrize("verb", ["place", "schedule"])
def test_an_old_row_with_a_number_must_be_edited_before_it_is_placed_or_scheduled(client, user, session, sid, no_gate, field,
                                                                                    verb):
    """사람은 가린 글([번호])을 승인하는데 음성 에이전트는 진짜 번호를 받는 일이 없게 — 걸기·예약 모두 422 has_phone, 문을 부르지 않음."""
    pid = _person(session, sid)
    stored = f"{SENTINEL_PHONE} 로 확인"
    row = _call(session, sid, pid, **{field: stored if field == "purpose" else [stored]})
    body = {"at": "2099-01-05T10:00:00+09:00"} if verb == "schedule" else None

    r = client.post(_url(sid, f"/{row.id}/{verb}"), json=body, headers=user)

    assert (r.status_code, r.json()["code"], r.json()["message"]) == (422, "has_phone", "전화번호는 넣을 수 없습니다 — 연락처에서 고릅니다")
    field_name = field.removesuffix("_json")
    assert r.json()["detail"] == {"field": field_name}
    _no_secret(json.dumps(r.json(), ensure_ascii=False))
    assert no_gate == [] and _reread(session, row.id).status == "draft"
