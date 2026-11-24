"""지키는 곳 하나를 **그 실행 안에서만** 무르는 문맥 관리자(Task 86). 격자 시험이 「그 칸은 이것이 지킨다」를 두 방향으로 본다:
그대로면 칸이 통과하고, 그것만 무르면 같은 칸이 실패한다.

**시험(pytest)과 모래상자 자식 프로세스(CHRONOS_HARNESS_SANDBOX=1, Task 98)에서만 불러올 수 있다 — 서버 프로세스에서는 불러오는
순간 RuntimeError**(무른 채로 실제 발송이 같이 뚫리지 않게). 모든 무르기는 들어갈 때 바꾼 자리를 나갈 때(예외가 나도) 되돌린다.

무르는 것(이름 → 그것만):
- gate.test_mode — 나가는 문의 차례 1(시험 모드·허용 번호)을 보지 않는다.
- gate.block_dnc — 나가는 문의 차례 2(차단·수신 거부)를 보지 않는다(may_reach 도 같은 함수를 읽는다).
- gate.hours — 나가는 문이 늘 근무 중으로 본다.
- gate.limits — 나가는 문의 차례 4(하루·사람당·자동 답 상한)를 보지 않는다.
- gate.permission — 권한(승인 받기)을 위임으로 본다: 문의 _mode 와 도구가 후속 줄을 초안으로 둘지 정하는 _delegated 둘 다.
- gate.duplicate — 나가는 문의 차례 6 가운데 「다른 줄과 같은 글·같은 목적」을 보지 않는다(같은 줄 두 번은 claim 이 그대로 막는다).
- door.class — 등급표의 「한 번호 여러 사람(대표번호)」을 그 첫 사람으로 본다(번호 → 등급).
- door.admit — 받기 판정표를 건너뛰어 모든 받은 것을 응대한다(아는 등급 engage · 그 밖 notice).
- toolset.per_class — 등급마다의 도구 묶음 대신 모든 상대에게 공용 도구 10개를 준다.
- tools.scope — 도구가 범위를 다시 보지 않는다: 현장을 묻지 않고, 사실을 공종으로 거르지 않고, 사람을 협력사로 거르지 않는다.
- tools.identity — 말로 한 신원 주장을 믿는다: 회신을 등록 번호가 아니라 주장한 번호로 보낸다.
- tools.no_change — 「바꾸지 않는다」를 끈다: 새 연락처·언어는 제안 대신 주소록에 바로, 지연·변경 보고는 지연 사건으로 바로.
- review.check — 뒤 확인이 늘 「깨끗함」을 돌려준다(근거 대조·깃발·quote_found 를 하지 않는다).

음성 열(VOICE_BREAKS — Task 97):
- runner.hours — 통화 일꾼의 「걸기 직전 다시 보기」가 늘 근무 중으로 본다(문의 gate.hours 와 따로 — 문은 사람이 넣은 09:00 에 봤다).
- call.silence — 통화 손잡이의 침묵 확인(SILENCE_S)을 끈다.
- call.time_limit — 통화 손잡이의 최대 통화 시간(정리 말·끊기)을 끈다.
- call.opt_out — 통화 중 수신 거부 듣기와 통화 뒤 뒤받침(H1)을 끈다(call_run·after 가 읽는 door.is_stop 만).
- tools.confirm_first — 거는 통화의 「신원 확인 전에는 그 사람의 자료를 주지 않음」(H1)을 끈다.
"""

import os
import sys
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

from app.outreach import phone
from app.outreach.harness import door, gate, registry, review, tools, toolsets
from app.outreach.harness.door import Admission
from app.outreach.harness.types import GATE_RULES, Caller
from app.outreach.text import responder
from app.outreach.voice import after, call_run, runner
from app.store.tables import DelayEvent
from app.store.tables_outreach import Contact

if not ("pytest" in sys.modules or os.environ.get(registry.SANDBOX_ENV) == "1"):
    raise RuntimeError(f"무르기(breaks)는 시험이나 모래상자 프로세스({registry.SANDBOX_ENV}=1)에서만 불러옵니다")

_BLOCKED_OR_DNC = next(number for number, name in GATE_RULES.items() if name == "blocked_or_dnc")


@contextmanager
def _swap(*spots: tuple[Any, str, Any]) -> Iterator[None]:
    """(주인, 이름, 새 값) 마다 바꾸고, 나갈 때(예외가 나도) 거꾸로 되돌린다. 주인이 dict 면 그 열쇠를."""
    saved: list[tuple[Any, str, Any]] = []
    try:
        for owner, name, value in spots:
            if isinstance(owner, dict):
                saved.append((owner, name, owner[name]))
                owner[name] = value
            else:
                saved.append((owner, name, getattr(owner, name)))
                setattr(owner, name, value)
        yield
    finally:
        for owner, name, old in reversed(saved):
            if isinstance(owner, dict):
                owner[name] = old
            else:
                setattr(owner, name, old)


class _Proxy:
    """모듈 하나를 대신하되 몇 이름만 바꾼 것(그 모듈을 부르는 쪽 하나에만 끼운다 — 다른 곳은 그대로)."""

    def __init__(self, real: Any, **over: Any) -> None:
        self._real, self._over = real, over

    def __getattr__(self, name: str) -> Any:
        return self._over[name] if name in self._over else getattr(self._real, name)


# ── 나가는 문 ──────────────────────────────────────────────────────


def _test_mode() -> AbstractContextManager:
    real = gate._barred

    def barred(session, conn, number):
        return real(session, _Proxy(conn, test_mode=False), number)

    return _swap((gate, "_barred", barred))


def _block_dnc() -> AbstractContextManager:
    real = gate._barred

    def barred(session, conn, number):
        found = real(session, conn, number)
        return None if found is not None and found.rule == _BLOCKED_OR_DNC else found

    return _swap((gate, "_barred", barred))


def _hours() -> AbstractContextManager:
    return _swap((gate, "_working", lambda *args: (True, None)))


def _limits() -> AbstractContextManager:
    return _swap((gate, "_over_limit", lambda *args: None))


def _permission() -> AbstractContextManager:
    real = gate._mode

    def mode(actor, row, conn, wanted):
        found = real(actor, row, conn, wanted)
        return ("delegated", None) if found is None and actor.kind == "agent" else found

    return _swap((gate, "_mode", mode), (tools, "_delegated", lambda conn, lane: True))


def _duplicate() -> AbstractContextManager:
    return _swap((gate, "_twin", lambda *args: None))


# ── 들어오는 문 ────────────────────────────────────────────────────


def _door_class() -> AbstractContextManager:
    real = door.resolve

    def resolve(session, number, *, now):
        caller = real(session, number, now=now)
        if caller.caller_class == "shared" and caller.candidates:
            return Caller("contact", caller.candidates[:1], None)
        return caller

    return _swap((door, "resolve", resolve))


def _door_admit() -> AbstractContextManager:
    real = door.admit

    def admit(session, medium, number, **kwargs):
        found = real(session, medium, number, **kwargs)
        if found.verdict in ("engage", "notice"):
            return found
        known = found.caller.caller_class not in door.UNKNOWN_CLASSES
        return Admission("engage" if known else "notice", found.caller, "known_caller" if known else "unknown_accepted")

    return _swap((door, "admit", admit))


# ── 도구 ───────────────────────────────────────────────────────────


def _per_class() -> AbstractContextManager:
    def every(caller_class, medium):
        return frozenset(toolsets.SHARED) | (frozenset(toolsets.VOICE_ONLY) if medium == "call" else frozenset())

    return _swap((toolsets, "for_class", every), (tools, "for_class", every))


def _scope() -> AbstractContextManager:
    real_search = tools.contacts.search

    def search(session, schedule_id, query, limit=5, *, company_ids=None):
        return real_search(session, schedule_id, query, limit, company_ids=None)

    return _swap((tools, "facts", _Proxy(tools.facts, allowed_for=lambda *args: None)),
                 (tools, "contacts", _Proxy(tools.contacts, search=search)),
                 (tools, "_asking", lambda box, session, site: None))


def _identity() -> AbstractContextManager:
    def believed(box, session, name):
        """주장을 믿음: 그 이름의 사람에게 하는 회신을 **지금 이 번호**로 보낸다(등록 번호가 아니라)."""
        found = tools.contacts.by_name(session, name)[:1]
        if not found or box.number(session) is None:
            return [], False
        fields = ({"purpose": tools.CLAIM_PURPOSE} if box.medium == "call" else {"body": tools.CLAIM_SMS})
        return [box.follow_row(session, fields, schedule_id=found[0].schedule_id, contact=None,
                               number=box.number(session))], False

    return _swap((tools, "_claim_callbacks", believed))


def _no_change() -> AbstractContextManager:
    propose, report = tools._TOOLS["propose_contact"], tools._TOOLS["report_from_contact"]

    def propose_and_add(box, session, a):
        step = propose(box, session, a)
        number = phone.normalize(a.phone)
        if box.sid is not None and box.scope.company_ids and number is not None:
            session.add(Contact(schedule_id=box.sid, company_id=box.scope.company_ids[0], name=a.name, phone=number))
        return step

    def report_and_apply(box, session, a):
        step = report(box, session, a)
        if a.kind in ("delay", "change_request") and box.sid is not None:
            session.add(DelayEvent(schedule_id=box.sid, activity_id="R", start_date=box.now().date(), days=2,
                                   cause=a.text, created_by=tools.AGENT_NAME))
        return step

    def language_applied(session, box, language, at):
        person = box.person(session)
        if person is not None and language:
            person.language = language[:10]

    return _swap((tools._TOOLS, "propose_contact", propose_and_add), (tools._TOOLS, "report_from_contact", report_and_apply),
                 (responder, "_propose_language", language_applied))


# ── 뒤 확인 ─────────────────────────────────────────────────────────


def _review() -> AbstractContextManager:
    return _swap((review, "check", lambda session, ref, **kwargs: review.Verdict(True, [])))


# ── 통화(음성 열 — Task 97) ──────────────────────────────────────────


def _call_opt_out() -> AbstractContextManager:
    """통화 중 수신 거부 듣기(call_run)와 통화 뒤 뒤받침(after) — 같은 겹(H1)의 두 자리만: 그 두 모듈이 읽는 door.is_stop 을 늘 거짓으로
    (문자의 들어오는 문은 그대로)."""
    deaf = _Proxy(door, is_stop=lambda *args, **kwargs: False)
    return _swap((call_run, "door", deaf), (after, "door", deaf))


def _confirm_first() -> AbstractContextManager:
    """거는 통화의 신원 확인 전 거절(tools.IDENTITY_TOOLS)을 끈다 — 확인하지 않아도 확인된 것처럼."""
    return _swap((tools.Toolbox, "needs_identity", property(lambda self: False)))


def _runner_hours() -> AbstractContextManager:
    return _swap((runner, "_working", lambda *args: True))


def _call_silence() -> AbstractContextManager:
    return _swap((call_run, "SILENCE_S", float("inf")))


def _call_time_limit() -> AbstractContextManager:
    real = call_run.CallRun.on_tick

    async def on_tick(self, elapsed, silent_for):
        """최대 시간이 없는 것처럼: 정리 말·끊기 갈래에 닿지 않게 시계를 최대 시간보다 앞에 둔 채 침묵만 본다."""
        await real(self, min(float(elapsed), self.spec.max_seconds - call_run.WRAP_UP_S - 1), silent_for)

    return _swap((call_run.CallRun, "on_tick", on_tick))


BREAKS: dict[str, Callable[[], AbstractContextManager]] = {
    "gate.test_mode": _test_mode, "gate.block_dnc": _block_dnc, "gate.hours": _hours, "gate.limits": _limits,
    "gate.permission": _permission, "gate.duplicate": _duplicate, "door.class": _door_class, "door.admit": _door_admit,
    "toolset.per_class": _per_class, "tools.scope": _scope, "tools.identity": _identity, "tools.no_change": _no_change,
    "review.check": _review,
}
# 음성 열에만 있는 지키는 곳(통화 일꾼·통화 손잡이) — BREAKS 와 같은 꼴, 격자는 둘을 함께 찾는다
VOICE_BREAKS: dict[str, Callable[[], AbstractContextManager]] = {
    "runner.hours": _runner_hours, "call.silence": _call_silence, "call.time_limit": _call_time_limit,
    "call.opt_out": _call_opt_out, "tools.confirm_first": _confirm_first,
}
