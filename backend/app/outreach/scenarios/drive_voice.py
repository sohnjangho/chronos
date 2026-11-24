"""음성 구동기(Task 97): 상황 대본 하나를 **같은 대본 그대로** 통화 길로 돌린다 — 판정·도구·뒤 확인·문·일꾼을 새로 만들지 않고
부르기만 한다. 대본을 매체마다 고쳐 쓰지 않는다(상황마다 가르는 곳도 없다 — 이 파일에 상황 번호가 없다).

대본 → 가짜 통화(SimulatedVoice) 걸음:
- Them → 상대 말 `Say("peer", 글)` · Model → `Tool(이름, 인자)` · ModelSays → 모델 말 `Say("agent", 글)` · Wait → `Silence(초)`
  (통화 밖이면 시계만 민다) · 통화의 끝은 상대가 끊음(`Hangup("peer")`).
- 통화 한 통은 **같은 번호의 이어진 말**이다: 다른 이름표(sender)의 Them 은 그 번호에서 걸려 온 새 통화, Permit(권한 바꿈 — 사람이
  설정에서 한다)은 지금 통화를 마치고 다음 통화부터 듣는다. 통화 사이는 GAP_S 초.
- call_out: 상대(Setup.peer)와의 첫 통화는 사람이 거는 통화 — 그날 09:00 에 사람이 문에 넣고(`gate.dispatch("call")` — 통로는
  가짜라 줄에 들어갈 뿐) 대본의 시각에 `runner.run_one`(걸기 직전 다시 보기 · 하네스 도구 · 통화 뒤 일 `after.finish`). 그 뒤의 통화
  (다른 번호, Permit 뒤의 상대)는 걸려 온 통화다 — 우리가 같은 목적으로 두 번 걸지 않는다(문이 같은 목적을 막는다).
- call_in: 통화마다 `Ring(번호)` → `inbound.on_incoming`(받기 전 판정) → 통화 → 통화 뒤 일(`after.finish`, 뒤에서 — 끝을 기다린다).
- Setup.channel_results 는 음성 열에서 **통화마다의 결과**로 쓴다(통화 차례): sent → 받음(대본대로), failed:no_answer → 받지 않음,
  failed:busy → 통화 중, failed:<그 밖> → 걸지 못함(그 코드), unsure → 통화 백엔드 고장(결과 모름). 다 쓰면 받음.
- Setup.permission 은 그 매체의 에이전트 권한(전화·문자 둘 다 — 통화의 후속은 통화·문자 줄), test_mode 는 우리 통화를 문에 넣은
  **뒤** 켠다(글 구동기와 같다 — 걸기 직전 다시 보기가 막는다).

모델은 없다: 통화 속 모델은 대본(SimulatedVoice), 통화 뒤 요약은 정해 둔 답을 주는 가짜(`_Summary` — after.client_for 를 그 실행
동안만). 통로는 FakeChannel. 결과(CellResult)에 번호가 없다. 시험(pytest)이나 CHRONOS_HARNESS_SANDBOX=1 프로세스에서만 돌고, 연락 일꾼
고리가 도는 프로세스(서버)에서는 돌지 않는다. 기다림은 모두 끝이 있다(통화 뒤 일 SETTLE_ROUNDS × SETTLE_WAIT_S).
"""

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.client import LlmReply, Usage
from app.outreach.harness import gate, registry
from app.outreach.harness.types import Actor, Outcome
from app.outreach.scenarios.drive_text import (
    ADMIN,
    CALL_PURPOSE,
    GAP_S,
    NUMBERS,
    OFF,
    OUR_NUMBER,
    PEER_CONTACT,
    REQUEST_AT_HOUR,
    REQUEST_BODY,
    WORK,
    CellResult,
    FakeChannel,
    _connection,
    _events,
    _fresh_state,
    _refuse_outside,
    _seed,
)
from app.outreach.scenarios.situations import (
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
from app.outreach.voice import after, inbound, runner
from app.outreach.voice import session as voice_session
from app.outreach.voice.simulated import (
    Busy,
    Crash,
    Failed,
    Hangup,
    NoAnswer,
    Ring,
    Say,
    Silence,
    SimulatedVoice,
    Tool,
)
from app.store import outreach
from app.store.tables_outreach import (
    BlockedNumber,
    Contact,
    OutreachCall,
    OutreachMessage,
)

VOICE_COLUMNS: tuple[Column, ...] = ("call_out", "call_in")
STEP_S = 2  # 통화 속 말 사이(초) — 침묵 확인(call_run.SILENCE_S)보다 짧게
SETTLE_ROUNDS, SETTLE_WAIT_S = 20, 5.0  # 받는 통화의 뒤 일(통화 끝·뒤 확인·요약·회신 문자)을 기다리는 끝
SUMMARY = {"summary_ko": "대본 통화를 요약했습니다.", "result": "대본 결과"}  # 가짜 요약 모델의 답
QUESTIONS = ["토요일 인원"]  # 우리 통화의 물어볼 것


class _Summary:
    """통화 뒤 요약 모델의 가짜(LlmClient 꼴의 chat 하나) — 늘 SUMMARY 를 돌려준다. 망·모델을 부르지 않는다."""

    def __init__(self) -> None:
        self.asked = 0

    async def chat(self, *args, **kwargs) -> LlmReply:
        self.asked += 1
        return LlmReply(json.dumps(SUMMARY, ensure_ascii=False), [], "scn-summary", Usage(0, 0, None), parsed=dict(SUMMARY))


@dataclass
class Heard:
    """Them 하나에 대한 응대 — 글 구동기의 세션과 같은 꼴(World.results·opened·instructions·tools_seen 이 읽는다). 그 Them 이 든
    통화가 받혀(시작돼) 모델이 지시문·도구를 받았으면 seen_* 가 차고, 그 Them 뒤의 도구 결과가 tool_results 에 든다."""

    call: int  # 이 Them 이 든 통화의 차례(Leg)
    tool_results: list[dict] = field(default_factory=list)
    seen_instructions: list[str] = field(default_factory=list)
    seen_tools: list[tuple[str, ...]] = field(default_factory=list)
    open_reports_at_reply: list = field(default_factory=list)  # 글 길에만 있다(차례로 보는 보고) — 음성은 빈 채


@dataclass
class _Leg:
    """통화 한 통: 같은 번호의 이어진 대본 걸음."""

    sender: str  # 번호 이름표
    outbound: bool  # 사람이 거는 통화(call_out 의 상대)
    steps: list = field(default_factory=list)
    tools_of: list[int] = field(default_factory=list)  # Tool 걸음마다 그 Them 의 차례
    hears: list[int] = field(default_factory=list)  # 이 통화에 든 Them 의 차례
    clock: float = 0.0
    missed: object | None = None  # 받지 않은 통화의 걸음(Setup.channel_results) — None 이면 받는다
    sim: SimulatedVoice | None = None
    row_id: int | None = None  # 통화 줄(거는 통화는 만든 줄, 받는 통화는 그 벨의 줄)

    def script(self, at: datetime) -> list:
        """이 통화의 가짜 대본 — 받는 통화는 그 시각의 벨로 시작한다."""
        talk = [self.missed] if self.missed is not None else [*self.steps, Hangup("peer")]
        return talk if self.outbound else [Ring(NUMBERS[self.sender] or None, at=at), *talk]


def _outcome(spec: str) -> object | None:
    """Setup.channel_results 한 칸 → 받지 않은 통화의 걸음(받으면 None)."""
    if spec == "sent":
        return None
    if spec == "unsure":
        return Crash()
    code = spec.removeprefix("failed:")
    if code == "no_answer":
        return NoAnswer()
    if code == "busy":
        return Busy()
    return Failed(code)


@dataclass
class _Run:
    situation: Situation
    column: Column
    factory: Callable[[], Session]
    fake: FakeChannel = field(default_factory=FakeChannel)
    summary: _Summary = field(default_factory=_Summary)
    clock: datetime = WORK
    legs: list[_Leg] = field(default_factory=list)
    heard: list[Heard] = field(default_factory=list)
    people: dict[str, int] = field(default_factory=dict)
    schedules: dict[str, int] = field(default_factory=dict)
    admin_id: int = 0
    asked_at: datetime = WORK
    probes: dict[str, Outcome] = field(default_factory=dict)
    baseline: dict[str, int] = field(default_factory=dict)

    def actor(self) -> Actor:
        return Actor("user", self.admin_id, ADMIN, "admin")

    def number(self, key: str) -> str:
        return NUMBERS[self.situation.setup.peer if key == "peer" else key]

    # ── 대본 → 통화들 ──────────────────────────────────────────────
    def split(self) -> None:
        """대본을 통화들로 나눈다(모듈 머리 글의 규칙 — 상황을 보지 않는다)."""
        setup, current = self.situation.setup, None
        for turn in self.situation.turns:
            if isinstance(turn, Them):
                sender = setup.peer if turn.sender == "peer" else turn.sender
                if current is None or current.sender != sender:
                    ours = self.column == "call_out" and sender == setup.peer and not any(leg.outbound for leg in self.legs)
                    current = _Leg(sender, ours)
                    self.legs.append(current)
                current.clock += STEP_S
                current.steps.append(Say("peer", turn.text, t=current.clock))
                current.hears.append(len(self.heard))
                self.heard.append(Heard(len(self.legs) - 1))
            elif isinstance(turn, Model):
                if current is None:
                    raise ValueError("모델 걸음은 Them 뒤에만 옵니다")
                current.steps.append(Tool(turn.tool, dict(turn.args)))
                current.tools_of.append(len(self.heard) - 1)
            elif isinstance(turn, ModelSays):
                if current is None:
                    raise ValueError("모델 걸음은 Them 뒤에만 옵니다")
                current.clock += STEP_S
                current.steps.append(Say("agent", turn.text, t=current.clock))
            elif isinstance(turn, Wait):
                if current is not None:
                    current.steps.append(Silence(turn.seconds))
                    current.clock += turn.seconds
            elif isinstance(turn, Permit):
                self.legs.append(_Leg("", False, [turn]))  # 통화가 아니라 사이에 끼는 권한 바꿈
                current = None
            else:
                raise TypeError("대본 걸음은 Them · Model · ModelSays · Wait · Permit 입니다")
        results = list(self.situation.setup.channel_results)
        for leg in self.legs:
            if leg.sender != "" and results:
                leg.missed = _outcome(results.pop(0))

    # ── 준비 ──────────────────────────────────────────────────────
    async def prepare(self) -> None:
        setup = self.situation.setup
        self.clock = WORK if setup.start == "work" else OFF
        self.asked_at = self.clock.replace(hour=REQUEST_AT_HOUR, minute=0)
        with self.factory() as session:
            self.people, self.schedules, self.admin_id = _seed(session)
            conn = _connection(session, self.situation)
            conn.agent_call = setup.permission
            for key in setup.dnc:
                outreach.mark_do_not_contact(session, NUMBERS[key], reason="대본")
            for key in setup.blocked:
                session.add(BlockedNumber(number=NUMBERS[key], reason="대본", created_by="대본"))
            person = session.get(Contact, self.people[PEER_CONTACT[setup.peer]])
            if setup.request_call:
                session.add(OutreachCall(schedule_id=person.schedule_id, contact_id=person.id, direction="out", origin="user",
                                         origin_name=ADMIN, purpose=CALL_PURPOSE, status="completed",
                                         claimed_at=self.asked_at, started_at=self.asked_at, created_at=self.asked_at))
            for leg in self.legs:
                if leg.outbound:
                    row = OutreachCall(schedule_id=person.schedule_id, contact_id=person.id, direction="out", origin="user",
                                       origin_name=ADMIN, purpose=CALL_PURPOSE, questions_json=list(QUESTIONS),
                                       status="draft", created_at=self.asked_at)
                    session.add(row)
                    session.flush()
                    leg.row_id = row.id
            session.commit()
        for leg in self.legs:
            if leg.row_id is not None:
                sent = await gate.dispatch("call", leg.row_id, self.actor(), now=self.asked_at)
                if sent.code != "queued":
                    raise RuntimeError(f"대본 준비: 우리 통화가 줄에 들어가지 않았습니다({sent.code})")
        with self.factory() as session:
            outreach.connection(session).test_mode = setup.test_mode
            self.baseline = snapshot(session)
            session.commit()
        self.fake.delivered.clear()

    # ── 돌리기 ────────────────────────────────────────────────────
    async def play(self) -> None:
        for index, leg in enumerate(self.legs):
            if leg.sender == "":
                await self.permit(leg.steps[0])
                continue
            if index and self.legs[index - 1].sender != "":
                self.clock += timedelta(seconds=GAP_S)
            leg.sim = SimulatedVoice(leg.script(self.clock))
            with voice_session.pinned(leg.sim):
                if leg.outbound:
                    await runner.run_one(leg.row_id, now=self.clock)
                else:
                    await leg.sim.listen(OUR_NUMBER, inbound.on_incoming)
                    await _settle()
            self.hear(leg)
            if leg.sim.calls:
                self.clock += timedelta(seconds=leg.sim.calls[0].seconds)

    def hear(self, leg: _Leg) -> None:
        record = leg.sim.calls[0] if leg.sim.calls else None
        if record is None or record.failed is not None:  # 받지 않았다(거절·받지 않음) — 모델이 아무것도 받지 않았다
            return
        for them in leg.hears:
            self.heard[them].seen_instructions.append(record.spec.instructions)
            self.heard[them].seen_tools.append(tuple(tool.name for tool in record.spec.tools))
        for them, result in zip(leg.tools_of, record.tool_results, strict=False):
            self.heard[them].tool_results.append(result.result)

    async def permit(self, turn: Permit) -> None:
        with self.factory() as session:
            conn = outreach.connection(session)
            conn.agent_call = conn.agent_sms = turn.mode
            session.commit()

    async def probe(self) -> None:
        """사람이 보내 봄(글 구동기와 같다): 대본 뒤 그 연락처에게 문자 한 건·전화 한 통을 문에 넣는다."""
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
                          numbers=NUMBERS, request_id=None, request_body=REQUEST_BODY, call_purpose=CALL_PURPOSE,
                          sims=self.heard, delivered=[row for lane, row in self.fake.delivered if lane != "call"],
                          probes=self.probes, baseline=self.baseline,
                          start=WORK if self.situation.setup.start == "work" else OFF,
                          calls=[leg.row_id for leg in self.legs if leg.sender != ""],
                          heard_in=[self.legs[h.call].row_id for h in self.heard],
                          voices=[leg.sim for leg in self.legs if leg.sim is not None])
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
        used = tuple(SimulatedVoice.__name__ for leg in self.legs if leg.sim is not None and leg.sim.calls)
        return CellResult(bool(checks) and all(c["ok"] for c in checks), checks, trail, used, type(self.fake).__name__,
                          self.situation.notes.get(self.column))


async def _settle() -> None:
    """받는 통화의 뒤에서 도는 일(통화 끝 기다림 · 통화 뒤 일 · 회신 문자)을 끝이 있게 기다린다."""
    for _ in range(SETTLE_ROUNDS):
        pending = [task for task in inbound._state.follows if not task.done()]
        if not pending:
            return
        await asyncio.wait(pending, timeout=SETTLE_WAIT_S)
    raise RuntimeError("대본: 받는 통화의 뒤 일이 끝나지 않았습니다")


@contextmanager
def _fresh_voice(summary: _Summary) -> Iterator[None]:
    """통화 일꾼·받는 쪽의 메모리 상태와 요약 모델을 그 실행 동안만 새것·가짜로."""
    saved = (runner._state, inbound._state, after.client_for)
    runner._state, inbound._state, after.client_for = runner._State(), inbound._State(), lambda session: summary
    try:
        yield
    finally:
        runner._state, inbound._state, after.client_for = saved


def _inbound_rows(session: Session) -> list[int]:
    return list(session.scalars(select(OutreachCall.id).where(OutreachCall.direction == "in").order_by(OutreachCall.id)))


async def run(situation: Situation, column: Column, session_factory: Callable[[], Session]) -> CellResult:
    """대본 하나를 그 음성 열로 돌린다. session_factory 는 하네스와 같은 DB(temp_database 가 준 것)의 세션을 만든다."""
    _refuse_outside()
    if column not in VOICE_COLUMNS:
        raise ValueError("음성 구동기는 call_out · call_in 열만 돌립니다")
    if situation.marks[column] == "none":
        raise ValueError("그 상황은 이 열에 없습니다")
    work = _Run(situation, column, session_factory)
    work.split()
    with ExitStack() as stack:
        stack.enter_context(_fresh_state())
        stack.enter_context(_fresh_voice(work.summary))
        stack.enter_context(registry.pinned({name: work.fake.lane(name) for name in registry.CHANNEL_NAMES}))
        await work.prepare()
        await work.play()
        await work.probe()
        _assign_rings(work)
        return work.judge()


def _assign_rings(work: _Run) -> None:
    """받는 통화(벨)의 줄 id 를 차례대로 그 통화에 붙인다 — 벨마다 한 줄이 생긴다(받든 안 받든)."""
    with work.factory() as session:
        rows = iter(_inbound_rows(session))
    for leg in work.legs:
        if leg.sender != "" and not leg.outbound:
            leg.row_id = next(rows, None)
