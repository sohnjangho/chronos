"""글 구동기(Task 86): 상황 대본 하나를 문자 길 그대로 돌린다 — 판정·도구·뒤 확인·문을 새로 만들지 않고 부르기만 한다.

한 칸(run):
1. 임시 DB(temp_database — db._engine 을 그 실행 동안만 바꾼다) 에 가상 주소록·알림 연결(Setup.limits 를 limits_json 에)을 깐다.
   일꾼·응대 줄·번호별 차례의 메모리 상태도 그 실행 동안만 새것으로.
2. 통로는 FakeChannel(registry.pinned — 시험·모래상자 프로세스에서만 열린다), 받은 문자는 대본의 가짜 제공사(_Inbox —
   provider.client_for 를 그 실행 동안만), 글 세션은 Them 마다 SimulatedText(text_session.pinned).
3. sms_reply 열이면 먼저 우리 메시지 한 건을 사람이 보낸다(gate.dispatch — 통로는 가짜).
4. 걸음: Them → (앞 응대를 마치고) 받은 문자로 넣고 일꾼 한 바퀴(worker.tick — 저장·받기 판정·수신 거부) · Model/ModelSays →
   그 Them 의 대본 · Wait → 시각을 옮기고 일꾼 한 바퀴 · Permit → (앞 응대를 마치고) 권한을 바꿈. 응대(inbox.drain →
   responder.handle)는 다음 Them·Permit 앞과 끝에서 그때의 시각으로 — 그래서 Them 과 ModelSays 사이의 Wait 는 「늦게 답하기」다.
5. Setup.probes(사람이 보내 봄)를 문에 넣고, Check 를 World 로 본다.

번호는 이 모듈만 안다(NUMBERS — 모두 가상). 결과(CellResult)에는 번호가 없다: 사건 detail 은 저장할 때 이미 가려진다.
시험(pytest)이나 CHRONOS_HARNESS_SANDBOX=1 프로세스에서만 돌고, 연락 일꾼 고리가 도는 프로세스(서버)에서는 돌지 않는다.
"""

import logging
import os
import sys
import tempfile
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import db
from app.core.model import Activity, CalendarSpec, Relation, Schedule, WbsNode
from app.outreach import hours, provider, worker
from app.outreach.harness import events, gate, registry
from app.outreach.harness.types import Actor, Delivered, Outcome, Ref
from app.outreach.provider import Delivery, Inbound, Received
from app.outreach.scenarios.situations import (
    TEXT_COLUMNS,
    Column,
    Model,
    ModelSays,
    Permit,
    Situation,
    Them,
    Wait,
    World,
    snapshot,
)
from app.outreach.text import inbox, responder
from app.outreach.text import session as text_session
from app.outreach.text.simulated import Reply, SimulatedText, Tool
from app.store import outreach
from app.store.schedules import create_schedule
from app.store.tables import Base, User
from app.store.tables_outreach import (
    BlockedNumber,
    Contact,
    ContactCompany,
    ContactReport,
    KakaoTemplate,
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
)
from app.store.timeutil import as_utc

logger = logging.getLogger(__name__)

KST = hours.KST
WORK = datetime(2026, 11, 27, 10, 0, tzinfo=KST)  # 금요일 10시 — 근무 중
OFF = datetime(2026, 11, 27, 19, 0, tzinfo=KST)  # 금요일 19시 — 근무 밖
REQUEST_AT_HOUR = 9  # 우리 요청을 보낸 때(그날 09:00)
GAP_S = 60  # Them 사이의 시간(일꾼이 받은 문자를 읽는 간격보다 넉넉히)
MAX_PROVIDER_READS = 200  # 가짜 제공사가 받는 읽기 수(넘으면 고리가 도는 것)
OUR_NUMBER = "07000000000"
NUMBERS = {  # 이름표 → 가상 번호(SENTINEL 010-0000-0199 가 박현장)
    "park": "01000000199", "kim": "01000000133", "kim_mep": "01000000134", "lee": "01000000188", "choi": "01000000177",
    "multi": "01000000111", "shared": "01000000122", "stranger": "01000000155", "blocked": "01000000166",
    "internal": "01000000100", "new": "01000000144", "withheld": "",
}
PEER_CONTACT = {"park": "park", "multi": "multi_a", "shared": "rep_park"}  # Setup.peer → 우리 요청을 받은 연락처
REQUEST_BODY = "토요일 철근 배근 인원 6명 가능하신가요?"
CALL_PURPOSE = "토요일 철근 배근 인원 확인"
ADMIN = "김공정"


@dataclass
class CellResult:
    passed: bool
    checks: list[dict]  # [{text, ok, error, guarded}] — error 는 검사가 터졌을 때 예외 종류(아니면 None), guarded 는 그 칸의
    #                     지키는 곳을 무르면 거짓이 되어야 하는 기대인가
    events: list[dict]  # [{ref, rule, verdict, detail}] — 모든 줄의 하네스 사건(번호 없음)
    sessions: tuple[str, ...] = ()  # 쓴 글 세션의 종류
    channel: str = ""  # 쓴 통로의 종류
    note: str | None = None  # 격자에 보일 말(설계와 다름 · 공통 겹만 — Situation.notes)


# ── 가짜 ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FakeLane:
    """FakeChannel 의 한 이름(Channel 꼴)."""

    name: str
    fake: "FakeChannel"

    async def deliver(self, row_id: int) -> Delivered:
        return self.fake.take(self.name, row_id)


class FakeChannel:
    """통로 가짜(앱 쪽 — 모래상자 자식 프로세스도 쓴다). 받은 (통로 이름, 줄 id) 를 쌓고, results 를 차례로 돌려준다(비면 sent)."""

    def __init__(self) -> None:
        self.delivered: list[tuple[str, int]] = []
        self.results: deque[Delivered] = deque()

    def lane(self, name: str) -> FakeLane:
        return FakeLane(name, self)

    def take(self, name: str, row_id: int) -> Delivered:
        self.delivered.append((name, row_id))
        if self.results:
            return self.results.popleft()
        return Delivered("sent", provider_id=f"scn-{len(self.delivered)}")


def _status(spec: str) -> Delivery:
    """Setup.status_results 한 칸 → 제공사의 상태 조회 결과(fell_back 은 알림톡이 실패해 문자로 대신 나감)."""
    if spec == "delivered":
        return Delivery("delivered")
    kind, _, code = spec.partition(":")
    if kind in ("failed", "fell_back") and code:
        return Delivery("failed", fail_code=code, fell_back=kind == "fell_back")
    raise ValueError("상태 결과는 delivered · failed:<code> · fell_back:<code> 입니다")


def _result(spec: str) -> Delivered:
    if spec == "sent":
        return Delivered("sent", provider_id="scn-scripted")
    if spec == "unsure":
        return Delivered("unsure")
    if spec.startswith("failed:"):
        return Delivered("failed", fail_code=spec.removeprefix("failed:"))
    raise ValueError("통로 결과는 sent · unsure · failed:<code> 입니다")


class WatchedText(SimulatedText):
    """대본 글 세션 + 모델이 답을 마치는 순간(Reply 를 돌려주기 바로 전)에 열린 보고(contact_reports open)의 종류를 적는다 —
    「세션이 끝나기 전에 보고가 있다」를 같은 시각이 아니라 차례로 보려고."""

    def __init__(self, script: list) -> None:
        super().__init__(script)
        self.open_reports_at_reply: list[list[str]] = []

    async def respond(self, instructions, tools, history, on_tool):
        reply = await super().respond(instructions, tools, history, on_tool)
        with Session(db._engine) as session:
            kinds = session.scalars(select(ContactReport.kind).where(ContactReport.status == "open").order_by(ContactReport.id))
            self.open_reports_at_reply.append(list(kinds))
        return reply


class _Inbox:
    """가짜 제공사: 대본이 넣은 받은 문자를 한 번씩 준다. 상태 조회는 「접수」. 보내기는 하지 않는다(통로가 가짜)."""

    def __init__(self) -> None:
        self.waiting: list[Inbound] = []
        self.at = WORK
        self.reads = 0
        self.statuses: deque[Delivery] = deque()  # Setup.status_results — 비면 「접수」

    async def received(self, since: datetime | None) -> Received:
        self.reads += 1
        if self.reads > MAX_PROVIDER_READS:
            raise RuntimeError("가짜 제공사가 상한보다 많이 읽혔습니다")
        items, self.waiting = self.waiting, []
        return Received(items=items, fetched_at=as_utc(self.at))

    async def message_status(self, provider_id: str) -> Delivery:
        return self.statuses.popleft() if self.statuses else Delivery("accepted")

    async def send_message(self, request: object) -> object:
        raise RuntimeError("대본 구동기는 제공사로 보내지 않습니다(통로는 가짜)")


# ── 실행 울타리 ─────────────────────────────────────────────────────


def allowed() -> bool:
    """시험(pytest)이나 모래상자 프로세스(CHRONOS_HARNESS_SANDBOX=1)인가 — 서버는 이 변수를 두지 않는다."""
    return "pytest" in sys.modules or os.environ.get(registry.SANDBOX_ENV) == "1"


def _refuse_outside() -> None:
    if not allowed():
        raise RuntimeError(f"상황 대본은 시험이나 모래상자 프로세스({registry.SANDBOX_ENV}=1)에서만 돌립니다")
    if worker.status()["running"]:
        raise RuntimeError("연락 일꾼이 도는 프로세스에서는 상황 대본을 돌리지 않습니다")


@contextmanager
def temp_database(folder: Path | None = None) -> Iterator[Callable[[], Session]]:
    """그 실행 동안만 하네스가 쓰는 DB(db._engine)를 임시 파일 DB 로 바꾼다. 세션을 만드는 함수를 준다. 끝나면 되돌리고 지운다."""
    _refuse_outside()
    with tempfile.TemporaryDirectory(prefix="chronos-scn-", dir=folder) as where:
        engine = create_engine(f"sqlite:///{Path(where) / 'scenario.db'}", hide_parameters=True)
        Base.metadata.create_all(engine)
        before = db._engine
        db._engine = engine
        try:
            yield lambda: Session(engine)
        finally:
            db._engine = before
            engine.dispose()


@contextmanager
def _fresh_state() -> Iterator[None]:
    """일꾼·응대 줄·번호별 차례의 메모리 상태를 그 실행 동안만 새것으로."""
    saved = (worker._state, inbox._pending, inbox._task, responder._turns)
    worker._state, inbox._pending, inbox._task, responder._turns = worker._State(), deque(), None, {}
    try:
        yield
    finally:
        worker._state, inbox._pending, inbox._task, responder._turns = saved


@contextmanager
def _provider(fake: _Inbox) -> Iterator[None]:
    real = provider.client_for
    provider.client_for = lambda row: fake
    try:
        yield
    finally:
        provider.client_for = real


# ── 가상 세계 ───────────────────────────────────────────────────────


def _project(session: Session, name: str, start: date, other: str) -> int:
    """일정 하나: R 「철근 배근」(3일, WBS 골조) → E 「마감 작업」(4일, WBS <other>) → Z 「준공」(마일스톤)."""
    schedule = Schedule(
        start=start, calendar=CalendarSpec(days_per_week=5),
        wbs=(WbsNode("1", "골조", None), WbsNode("2", other, None)),
        activities=(Activity("R", "철근 배근", "task", "1", 3), Activity("E", "마감 작업", "task", "2", 4),
                    Activity("Z", "준공", "finish_ms", "1", 0)),
        relations=(Relation("R", "E"), Relation("E", "Z")), resources=(),
    )
    return create_schedule(session, name=name, domain="construction", level="L3", schedule=schedule, conditions=[],
                           by_kind="agent", by_name="에이전트", note="처음 만듦")


def _seed(session: Session) -> tuple[dict[str, int], dict[str, int], int]:
    """두 현장·네 협력사·사람들. (연락처 이름표 → id, 현장 → 일정 id, 관리자 id)."""
    a = _project(session, "가람 현장", date(2027, 3, 1), "설비")
    b = _project(session, "나래 현장", date(2028, 5, 1), "전기")
    firms = {}
    for key, sid, name, trade in (("rebar_a", a, "가람철근", "철근"), ("mep_a", a, "가람설비", "설비"),
                                  ("rebar_b", b, "나래철근", "철근"), ("elec_b", b, "나래전기", "전기")):
        firms[key] = ContactCompany(schedule_id=sid, name=name, trade=trade)
        session.add(firms[key])
    session.flush()
    people = {}
    for key, firm, name, role, number in (
            ("park", "rebar_a", "박현장", "철근 반장", "park"), ("kim", "rebar_a", "김민수", "철근 기사", "kim"),
            ("kim_mep", "mep_a", "김민수", "설비 기사", "kim_mep"), ("lee", "mep_a", "이설비", "설비 소장", "lee"),
            ("choi", "rebar_b", "최철근", "철근 반장", "choi"), ("multi_a", "rebar_a", "최다현", "철근 기사", "multi"),
            ("multi_b", "rebar_b", "최다현", "철근 기사", "multi"), ("rep_park", "rebar_a", "박대표", "대표", "shared"),
            ("rep_kim", "rebar_a", "김대표", "총무", "shared")):
        company = firms[firm]
        people[key] = Contact(schedule_id=company.schedule_id, company_id=company.id, name=name, role_title=role,
                              phone=NUMBERS[number])
        session.add(people[key])
    admin = User(login_id="scn-admin", name=ADMIN, role="admin", password_hash="x")
    session.add_all([admin, User(login_id="scn-internal", name="이내부", role="user", phone=NUMBERS["internal"],
                                 password_hash="x")])
    session.flush()
    return {key: row.id for key, row in people.items()}, {"a": a, "b": b}, admin.id


def _connection(session: Session, situation: Situation) -> NotifyConnection:
    setup = situation.setup
    row = NotifyConnection(name="대본 연결", base_url="https://kat.invalid", secret_ciphertext="x", secret_last4="0000",
                           account_id="scn", sender_number=OUR_NUMBER, is_default=True, status="ok", test_mode=False,
                           inbound_mode=setup.inbound, agent_sms=setup.permission, limits_json=dict(setup.limits))
    session.add(row)
    session.flush()
    return row


# ── 한 칸 ──────────────────────────────────────────────────────────


@dataclass
class _Run:
    situation: Situation
    column: Column
    factory: Callable[[], Session]
    fake: FakeChannel = field(default_factory=FakeChannel)
    inbox: _Inbox = field(default_factory=_Inbox)
    clock: datetime = WORK
    sims: list[WatchedText] = field(default_factory=list)
    pending: list | None = None
    sent_count: int = 0
    people: dict[str, int] = field(default_factory=dict)
    schedules: dict[str, int] = field(default_factory=dict)
    admin_id: int = 0
    request_id: int | None = None
    probes: dict[str, Outcome] = field(default_factory=dict)
    baseline: dict[str, int] = field(default_factory=dict)

    def actor(self) -> Actor:
        return Actor("user", self.admin_id, ADMIN, "admin")

    async def prepare(self) -> None:
        setup = self.situation.setup
        self.clock = WORK if setup.start == "work" else OFF
        asked_at = self.clock.replace(hour=REQUEST_AT_HOUR, minute=0)
        with self.factory() as session:
            self.people, self.schedules, self.admin_id = _seed(session)
            conn = _connection(session, self.situation)
            for key in setup.dnc:
                outreach.mark_do_not_contact(session, NUMBERS[key], reason="대본")
            for key in setup.blocked:
                session.add(BlockedNumber(number=NUMBERS[key], reason="대본", created_by="대본"))
            target = self.people[PEER_CONTACT[setup.peer]]
            person = session.get(Contact, target)
            if setup.request_call:
                session.add(OutreachCall(schedule_id=person.schedule_id, contact_id=target, direction="out", origin="user",
                                         origin_name=ADMIN, purpose=CALL_PURPOSE, status="completed", claimed_at=asked_at,
                                         started_at=asked_at, created_at=asked_at))
            if self.column == "sms_reply":
                request = OutreachMessage(schedule_id=person.schedule_id, contact_id=target, direction="out",
                                          channel=setup.request_channel, origin="user", origin_name=ADMIN, body=REQUEST_BODY,
                                          status="draft", created_at=asked_at)
                if setup.kakao_template:
                    template = KakaoTemplate(connection_id=conn.id, channel="scn", provider_template_id="scn-request",
                                             use="request", body=REQUEST_BODY, status="approved")
                    session.add(template)
                    session.flush()
                    request.template_id = template.id
                session.add(request)
                session.flush()
                self.request_id = request.id
            session.commit()
        if self.request_id is not None:
            sent = await gate.dispatch("message", self.request_id, self.actor(), now=asked_at)
            if sent.code != "accepted":
                raise RuntimeError(f"대본 준비: 우리 요청이 나가지 않았습니다({sent.code})")
        with self.factory() as session:
            conn = outreach.connection(session)
            conn.test_mode = setup.test_mode
            self.baseline = snapshot(session)
            session.commit()
        self.fake.delivered.clear()
        self.fake.results.extend(_result(spec) for spec in setup.channel_results)
        self.inbox.statuses.extend(_status(spec) for spec in setup.status_results)

    async def tick(self) -> dict:
        self.inbox.at = self.clock
        done = await worker.tick(now=self.clock)
        if done["skipped"] is not None or done["error"] is not None:
            raise RuntimeError(f"대본: 일꾼 바퀴가 돌지 않았습니다({done['skipped'] or done['error']})")
        return done

    async def flush(self) -> None:
        """앞 Them 의 응대를 지금 시각으로 돌린다(그 Them 의 대본을 끼우고)."""
        if self.pending is None:
            return
        sim = WatchedText(self.pending)
        self.sims.append(sim)
        self.pending = None
        with text_session.pinned(sim):
            await inbox.drain(now=self.clock)

    async def arrive(self, turn: Them) -> None:
        await self.flush()
        if self.sent_count:
            self.clock += timedelta(seconds=GAP_S)
        self.sent_count += 1
        number = NUMBERS[self.situation.setup.peer if turn.sender == "peer" else turn.sender]
        self.inbox.waiting.append(Inbound(provider_id=f"SCN{self.sent_count:04d}", from_number=number, body=turn.text,
                                          at=as_utc(self.clock - timedelta(seconds=30)), has_media=turn.media,
                                          to_number=OUR_NUMBER))
        done = await self.tick()
        if done["inbound"] != 1:
            raise RuntimeError("대본: 받은 문자가 저장되지 않았습니다")
        self.pending = []

    async def permit(self, turn: Permit) -> None:
        await self.flush()
        with self.factory() as session:
            outreach.connection(session).agent_sms = turn.mode
            session.commit()

    async def play(self) -> None:
        for turn in self.situation.turns:
            if isinstance(turn, Them):
                await self.arrive(turn)
            elif isinstance(turn, Model | ModelSays):
                if self.pending is None:
                    raise ValueError("모델 걸음은 Them 뒤에만 옵니다")
                self.pending.append(Tool(turn.tool, dict(turn.args)) if isinstance(turn, Model)
                                    else Reply(turn.text, turn.text_ko, turn.language))
            elif isinstance(turn, Wait):
                self.clock += timedelta(seconds=turn.seconds)
                await self.tick()
            elif isinstance(turn, Permit):
                await self.permit(turn)
            else:
                raise TypeError("대본 걸음은 Them · Model · ModelSays · Wait · Permit 입니다")
        await self.flush()

    async def probe(self) -> None:
        """사람이 보내 봄: 대본 뒤 그 연락처에게 문자 한 건·전화 한 통을 문에 넣는다."""
        for name in self.situation.setup.probes:
            kind, key = name.split(":")
            with self.factory() as session:
                person = session.get(Contact, self.people[key])
                if kind == "sms":
                    row = OutreachMessage(schedule_id=person.schedule_id, contact_id=person.id, direction="out",
                                          channel="sms", origin="user", origin_name=ADMIN, body="확인용 문자입니다",
                                          status="draft", created_at=self.clock)
                else:
                    row = OutreachCall(schedule_id=person.schedule_id, contact_id=person.id, direction="out", origin="user",
                                       origin_name=ADMIN, purpose="확인용 전화", status="draft", created_at=self.clock)
                session.add(row)
                session.commit()
                row_id = row.id
            self.probes[name] = await gate.dispatch("message" if kind == "sms" else "call", row_id, self.actor(),
                                                    now=self.clock)

    def judge(self) -> CellResult:
        with self.factory() as session:
            world = World(session=session, column=self.column, people=self.people, schedules=self.schedules,
                          numbers=NUMBERS, request_id=self.request_id, request_body=REQUEST_BODY, call_purpose=CALL_PURPOSE,
                          sims=self.sims, delivered=[row_id for _, row_id in self.fake.delivered], probes=self.probes,
                          baseline=self.baseline, start=WORK if self.situation.setup.start == "work" else OFF)
            checks = []
            for check in self.situation.expect:
                if check.columns is not None and self.column not in check.columns:
                    continue
                error = None
                try:
                    ok = check.fn(world) is True
                except Exception as exc:  # noqa: BLE001 — 기대가 터지면 그 기대는 거짓(까닭은 종류만)
                    ok, error = False, type(exc).__name__
                checks.append({"text": check.text, "ok": ok, "error": error, "guarded": check.breaks_in(self.column)})
            trail = _events(session)
        return CellResult(bool(checks) and all(c["ok"] for c in checks), checks, trail,
                          tuple(SimulatedText.__name__ for sim in self.sims if sim.seen_instructions), type(self.fake).__name__,
                          self.situation.notes.get(self.column))


def _events(session: Session) -> list[dict]:
    out = []
    for model, kind in ((OutreachMessage, "message"), (OutreachCall, "call")):
        for row_id in session.scalars(select(model.id).order_by(model.id)):
            for event in events.of(session, Ref(kind, row_id)):
                out.append({"ref": f"{kind}:{row_id}", "rule": event["rule"], "verdict": event["verdict"],
                            "detail": event["detail"]})
    return out


async def run(situation: Situation, column: Column, session_factory: Callable[[], Session]) -> CellResult:
    """대본 하나를 그 글 열로 돌린다. session_factory 는 하네스와 같은 DB(temp_database 가 준 것)의 세션을 만든다."""
    _refuse_outside()
    if column not in TEXT_COLUMNS:
        raise ValueError("글 구동기는 sms_in · sms_reply 열만 돌립니다(음성 열은 Task 97)")
    if situation.marks[column] == "none":
        raise ValueError("그 상황은 이 열에 없습니다")
    work = _Run(situation, column, session_factory)
    with ExitStack() as stack:
        stack.enter_context(_fresh_state())
        stack.enter_context(registry.pinned({name: work.fake.lane(name) for name in registry.CHANNEL_NAMES}))
        stack.enter_context(_provider(work.inbox))
        await work.prepare()
        await work.play()
        await work.probe()
        return work.judge()
