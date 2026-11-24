"""상황 S-01…S-24 — 한 번만 쓴다(Task 86). 매체를 모르는 꼴이라 음성 가짜(Task 97)는 Them 을 상대 말로, 글 가짜(drive_text)는 받은
문자로 옮긴다. 기대(Check)는 **코드가 한 일**을 본다 — 말솜씨가 아니라 줄·사건·도구 결과. 사건 이름은 harness.types 의 낱말만
(rule() 이 그 밖의 이름을 불러올 때 거절한다). 채널에 따라 다른 기대만 Check.columns 로 나눈다.

Situation.guards — 그 칸을 지키는 곳(breaks.BREAKS 의 열쇠): 그것을 무르면 그 칸이 실패한다(grid 시험이 두 방향을 다 본다).
Setup.limits — 그 대본이 쓰는 상한을 **모두** 적는다(알림 연결의 limits_json 에 그대로 들어간다 — 기본값에 기대지 않는다).
번호·이름은 모두 가상이다(번호는 drive_text 만 안다 — Check 는 World.number(이름표)로 읽는다).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.outreach import hours
from app.outreach.harness import events, facts, gate, rules_text, tools, toolsets
from app.outreach.harness.types import GATE_RULES, REVIEW_FLAGS, Outcome, Ref
from app.outreach.text import instructions, responder
from app.outreach.voice import call_run
from app.store import outreach
from app.store.tables import Approval, DelayEvent, ScheduleVersion
from app.store.tables_outreach import (
    Contact,
    ContactProposal,
    ContactReport,
    OutreachCall,
    OutreachMessage,
)
from app.store.timeutil import as_utc

Column = Literal["call_out", "call_in", "sms_in", "sms_reply"]
COLUMNS: tuple[Column, ...] = ("call_out", "call_in", "sms_in", "sms_reply")
TEXT_COLUMNS: tuple[Column, ...] = ("sms_in", "sms_reply")
Mark = str  # "run" | "none" | 특별 표시 글(「막음」·「받지 않음」·「기록만」·「예약」·「30분 규칙」·「받는 범위 설정대로」·「후속 행동에」)
USED_RULES: set[str] = set()


def rule(name: str) -> str:
    """기대에 쓰는 사건 이름 — harness.types 의 낱말(events.KNOWN_RULES)이 아니면 ValueError."""
    if name not in events.KNOWN_RULES:
        raise ValueError(f"사건 낱말에 없는 이름입니다: {name}")
    USED_RULES.add(name)
    return name


# ── 대본의 걸음(매체를 모르는 꼴) ────────────────────────────────────


@dataclass(frozen=True)
class Them:
    """상대가 보낸 것(문자 한 건 · 통화의 말 한 마디). sender 는 drive_text 의 번호 이름표("peer" = Setup.peer)."""

    text: str
    sender: str = "peer"
    media: bool = False


@dataclass(frozen=True)
class Model:
    """모델의 도구 호출 — 바로 앞 Them 에 대한 응대 안에서."""

    tool: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ModelSays:
    """모델의 답(그 응대가 끝난다)."""

    text: str
    text_ko: str | None = None
    language: str = "ko"


@dataclass(frozen=True)
class Wait:
    """시간이 흐름(초) — 그동안 일꾼이 한 바퀴 돈다. 앞 Them 의 응대는 Wait 뒤의 시각에 돈다(늦게 답하기)."""

    seconds: int


@dataclass(frozen=True)
class Permit:
    """그 매체의 에이전트 권한을 바꾼다(approve | delegate) — 같은 대본 안에서 「승인 받기 → 위임」을 보려고(S-23)."""

    mode: Literal["approve", "delegate"]


Turn = Them | Model | ModelSays | Wait | Permit


@dataclass(frozen=True)
class Setup:
    """대본의 바탕. limits 는 Limits 의 칸 전부(BASE_LIMITS 에서 고침). permission 은 그 매체의 에이전트 권한.
    start — work(금 10:00) | off(금 19:00). peer — 기본 상대(park · multi · shared). 우리 요청(sms_reply 열)은 그 상대에게,
    request_channel 로(kakao 면 문이 문자로 대신 보냄). test_mode 는 우리 요청을 보낸 **뒤** 켠다.
    dnc·blocked — 처음부터 수신 거부·차단인 번호 이름표. request_call — 앞서 건 통화(완료) 한 통. channel_results — 준비 뒤
    통로가 차례로 줄 결과("sent" · "unsure" · "failed:<fail_code>"). probes — 대본 뒤 사람이 보내 보는 것("sms:<이름표>" ·
    "call:<이름표>")."""

    limits: Mapping[str, int]
    permission: Literal["approve", "delegate"] = "approve"
    start: Literal["work", "off"] = "work"
    peer: str = "park"
    request_channel: Literal["sms", "kakao"] = "sms"
    request_call: bool = False
    test_mode: bool = False
    inbound: Literal["off", "known", "all"] = "all"
    dnc: tuple[str, ...] = ()
    blocked: tuple[str, ...] = ()
    channel_results: tuple[str, ...] = ()
    probes: tuple[str, ...] = ()
    kakao_template: bool = False  # 이 연결에 승인된 카카오톡 문안이 있다 — 우리 요청(kakao)이 카카오톡 통로(가짜)로 나간다
    status_results: tuple[str, ...] = ()  # 일꾼의 상태 조회가 차례로 받을 결과: delivered · failed:<code> · fell_back:<code>


@dataclass(frozen=True)
class Check:
    """기대 하나. guarded — 그 칸의 지키는 곳(Situation.guards)을 무르면 **이 기대가** 거짓이 된다(무르기 시험은 거짓이 되는 기대의
    집합이 guarded 인 기대의 집합과 꼭 같은지 본다 — 「무언가 깨짐」이 아니라 「이것이 깨짐」)."""

    text: str
    fn: Callable[["World"], bool]
    columns: frozenset[Column] | None = None
    guarded: bool | frozenset[Column] = False  # 참이면 모든 열, 열 집합이면 그 열에서만

    def breaks_in(self, column: Column) -> bool:
        return self.guarded is True or (isinstance(self.guarded, frozenset) and column in self.guarded)


@dataclass(frozen=True)
class Situation:
    id: str
    title: str
    marks: Mapping[Column, Mark]
    setup: Setup
    turns: tuple[Turn, ...]
    expect: tuple[Check, ...]
    refs: tuple[str, ...]
    guards: Mapping[Column, str]
    notes: Mapping[Column, str] = field(default_factory=dict)  # 격자에 보일 말(설계와 다름 · 공통 겹만)


# ── Check 가 보는 세계 ───────────────────────────────────────────────


def snapshot(session: Session) -> dict[str, int]:
    """바뀌면 안 되는 것의 수: 일정 버전 · 승인 · 지연 사건 · 주소록."""
    return {name: session.scalar(select(func.count()).select_from(model)) or 0
            for name, model in (("versions", ScheduleVersion), ("approvals", Approval), ("delays", DelayEvent),
                                ("contacts", Contact))}


@dataclass
class World:
    """한 칸을 돌린 뒤: 임시 DB 세션과 가짜들이 남긴 것. sims 는 Them 마다 하나(응대가 열리지 않았으면 쓰이지 않은 대본)."""

    session: Session
    column: Column
    people: Mapping[str, int]
    schedules: Mapping[str, int]
    numbers: Mapping[str, str]
    request_id: int | None
    request_body: str
    call_purpose: str
    sims: list
    delivered: list[int]
    probes: dict[str, Outcome]
    baseline: dict[str, int]
    start: datetime
    calls: list[int | None] = field(default_factory=list)  # 음성: 통화마다(대본 차례) 그 줄 id — 받지 않은 벨도 줄이 있다
    heard_in: list[int | None] = field(default_factory=list)  # 음성: Them 마다 그것이 든 통화의 줄 id
    voices: list = field(default_factory=list)  # 음성: 통화마다 가짜 통화(SimulatedVoice — said·calls)

    def call(self, index: int) -> OutreachCall:
        """음성: Them(index)이 든 통화의 줄."""
        return self.session.get(OutreachCall, self.heard_in[index])

    def leg(self, index: int) -> OutreachCall:
        """음성: 대본 차례로 index 번째 통화의 줄."""
        return self.session.get(OutreachCall, self.calls[index])

    def code_said(self, index: int) -> list[str]:
        """음성: index 번째 통화에서 코드가 시킨 말(침묵 확인·정리 말·첫마디 다시)."""
        return list(self.voices[index].said)

    def calls_to(self, person: str) -> list[OutreachCall]:
        """그 연락처에게 에이전트가 만든 나가는 통화(후속 줄)."""
        rows = select(OutreachCall).where(OutreachCall.direction == "out", OutreachCall.origin == "agent",
                                          OutreachCall.contact_id == self.people[person]).order_by(OutreachCall.id)
        return list(self.session.scalars(rows))

    def inbound(self) -> list[OutreachMessage]:
        rows = select(OutreachMessage).where(OutreachMessage.direction == "in").order_by(OutreachMessage.id)
        return list(self.session.scalars(rows))

    def replies(self) -> list[OutreachMessage]:
        """응대가 만든 답 줄(자동 답·고정 안내), 만든 차례."""
        rows = select(OutreachMessage).where(OutreachMessage.direction == "out", OutreachMessage.origin == "agent",
                                             OutreachMessage.kind.in_(responder.AUTO_KINDS)).order_by(OutreachMessage.id)
        return list(self.session.scalars(rows))

    def to(self, person: str) -> list[OutreachMessage]:
        """그 연락처에게 에이전트가 만든 나가는 메시지(답 밖의 후속 줄)."""
        rows = select(OutreachMessage).where(OutreachMessage.direction == "out", OutreachMessage.origin == "agent",
                                             OutreachMessage.contact_id == self.people[person],
                                             OutreachMessage.kind == "normal").order_by(OutreachMessage.id)
        return list(self.session.scalars(rows))

    def out(self, **equal) -> list[OutreachMessage]:
        rows = select(OutreachMessage).where(OutreachMessage.direction == "out",
                                             *[getattr(OutreachMessage, k) == v for k, v in equal.items()])
        return list(self.session.scalars(rows.order_by(OutreachMessage.id)))

    def log(self, row: OutreachMessage | OutreachCall) -> list[tuple[str, str, str]]:
        kind = "call" if isinstance(row, OutreachCall) else "message"
        return [(e["rule"], e["verdict"], e["detail"]) for e in events.of(self.session, Ref(kind, row.id))]

    def rules(self, row: OutreachMessage | OutreachCall) -> list[str]:
        return [name for name, _, _ in self.log(row)]

    def admission(self, row: OutreachMessage) -> tuple[str, str] | None:
        found = [(verdict, detail) for name, verdict, detail in self.log(row) if name == rule("admission")]
        return found[0] if len(found) == 1 else None

    def every_rule(self) -> list[str]:
        return [name for row in self.inbound() for name in self.rules(row)]

    def results(self, index: int) -> list[dict]:
        return list(self.sims[index].tool_results)

    def opened(self, index: int) -> bool:
        return bool(self.sims[index].seen_instructions)

    def instructions(self, index: int) -> str:
        return self.sims[index].seen_instructions[0]

    def tools_seen(self, index: int) -> tuple[str, ...]:
        return self.sims[index].seen_tools[0]

    def reports(self, kind: str) -> list[ContactReport]:
        rows = select(ContactReport).where(ContactReport.kind == kind).order_by(ContactReport.id)
        return list(self.session.scalars(rows))

    def proposals(self, kind: str) -> list[ContactProposal]:
        rows = select(ContactProposal).where(ContactProposal.kind == kind).order_by(ContactProposal.id)
        return list(self.session.scalars(rows))

    def unchanged(self, *names: str) -> bool:
        now = snapshot(self.session)
        return all(now[name] == self.baseline[name] for name in names)

    def sent(self, row: OutreachMessage) -> int:
        """통로가 그 줄을 받은 번 수(준비 뒤)."""
        return self.delivered.count(row.id)

    def number(self, key: str) -> str:
        return self.numbers[key]

    def person(self, key: str) -> Contact:
        return self.session.get(Contact, self.people[key])

    def fact(self, site: str, activity: str) -> facts.Fact:
        """그 현장 일정을 코드가 계산한 작업 하나(화면과 같은 계산)."""
        return facts.find(self.session, self.schedules[site], activity, allowed=None)[0]

    def probe(self, name: str) -> tuple[str, str | None]:
        outcome = self.probes[name]
        return outcome.code, GATE_RULES.get(outcome.rule) if outcome.rule is not None else None


# ── 상한(모든 칸을 적는다) ────────────────────────────────────────────

BASE_LIMITS: Mapping[str, int] = {
    "daily_sms_total": 50, "daily_calls_total": 10, "per_contact_sms_daily": 5, "per_contact_calls_daily": 2,
    "max_call_seconds": 300, "max_call_seconds_unknown": 120, "auto_reply_hourly": 5, "auto_reply_daily": 20,
    "inbound_burst_count": 5, "inbound_burst_minutes": 10, "reply_grace_minutes": 30, "unknown_notice_daily": 1,
    "unknown_calls_hourly": 6, "unknown_notice_total_daily": 10,
}


def limits(**over: int) -> dict[str, int]:
    return {**BASE_LIMITS, **over}


def TEXT_GUARD(name: str) -> dict[Column, str]:
    """두 글 열이 같은 지키는 곳."""
    return {"sms_in": name, "sms_reply": name}


def marks(call_out: Mark, call_in: Mark, sms_in: Mark, sms_reply: Mark) -> dict[Column, Mark]:
    return {"call_out": call_out, "call_in": call_in, "sms_in": sms_in, "sms_reply": sms_reply}


COMMON_ONLY: dict[Column, str] = {
    column: "공통 겹만 — 이 상황을 지키는 보고·지시문 줄을 끄는 무르기가 없어 답의 권한(gate.permission)으로 본다"
    for column in ("sms_in", "sms_reply")}
RUN4 = marks("run", "run", "run", "run")
IN_ONLY = marks("none", "run", "run", "none")
ONLY_REPLY = frozenset({"sms_reply"})
ONLY_IN = frozenset({"sms_in"})
TEXT: frozenset[Column] = frozenset(TEXT_COLUMNS)
VOICE: frozenset[Column] = frozenset({"call_out", "call_in"})
ONLY_OUT = frozenset({"call_out"})
ONLY_CALL_IN = frozenset({"call_in"})
DIVERGED_DNC = ("하네스가 갈라짐: 통화에는 수신 거부 말을 코드가 듣는 길이 없다 — 문자는 들어오는 문이 「수신거부」를 보고 표시하지만, "
                "통화는 모델이 mark_do_not_contact 를 불러야만 표시된다(같은 대본으로는 통과하지 않음)")
DIVERGED_LANGUAGE = ("하네스가 갈라짐: 통화의 언어 제안은 모델이 end_call(language) 를 부를 때만 생긴다 — 문자는 답의 언어로 코드가 "
                     "제안한다(같은 대본으로는 통과하지 않음)")
DIVERGED_REPEAT = ("하네스가 갈라짐: 대본의 되풀이는 한 번호의 이어진 말이라 통화 한 통이 된다 — 「전화 여러 번」은 통화를 여러 번 "
                   "걸어야 해 같은 대본으로는 통과하지 않음")
VOICE_COMMON_ONLY = ("공통 겹만 — 통화의 말은 실시간이라 권한·뒤 확인 전에 나가고, 이 상황을 지키는 보고·지시문 줄을 끄는 무르기가 "
                     "없다(지키는 곳 없음)")


def GUARDS(text: str | None, voice: str | None, **only: str) -> dict[Column, str]:
    """네 열의 지키는 곳 — text 는 두 글 열, voice 는 두 음성 열(None 이면 그 열에 무를 곳이 없음), only 는 열 하나씩."""
    found: dict[Column, str] = {}
    for columns, name in ((TEXT_COLUMNS, text), (("call_out", "call_in"), voice)):
        if name is not None:
            found.update(dict.fromkeys(columns, name))
    return {**found, **only}


def G(text: str, fn: Callable[["World"], bool], columns: frozenset[Column] | None = None,
      guarded: bool | frozenset[Column] = True) -> Check:
    """지키는 곳을 무르면 거짓이 되어야 하는 기대(Check(guarded=…))."""
    return Check(text, fn, columns, guarded)


# ── 기대 도우미 ────────────────────────────────────────────────────


def _draft_only(w: World, row: OutreachMessage) -> bool:
    """승인 받기: 초안(판정 permission blocked), 통로 0."""
    return (row.status == "draft" and row.send_mode is None and w.sent(row) == 0
            and (rule("permission"), "blocked") in [(n, v) for n, v, _ in w.log(row)])


def _all_drafts(w: World) -> bool:
    found = w.replies()
    return bool(found) and all(_draft_only(w, row) for row in found)


def _held(w: World, row: OutreachMessage, flag: str) -> bool:
    """뒤 확인에 걸려 보내지 않음(확인 뒤 보내기) — 깃발은 받은 줄에."""
    asked = w.session.get(OutreachMessage, row.reply_to_id)
    return (row.status == "draft" and row.fail_reason == responder.HELD_REASON and w.sent(row) == 0
            and rule(flag) in w.rules(asked) and w.rules(row) == [rule("held_for_review")])


def _went_out(w: World, row: OutreachMessage) -> bool:
    return row.status == "accepted" and row.send_mode == "delegated" and w.sent(row) == 1


def _five_fields(result: dict) -> bool:
    items = result.get("items") or []
    return bool(items) and all(set(item) == {"id", "name", "start", "finish", "status"} for item in items)


def _no_number(w: World, value: object, key: str) -> bool:
    digits = "".join(ch for ch in repr(value) if ch.isdigit())
    return w.number(key) not in digits and w.number(key)[1:] not in digits


def _kst(w: World, *, day: int, hour: int) -> datetime:
    return w.start.astimezone(hours.KST).replace(day=day, hour=hour, minute=0, second=0, microsecond=0)


def _same(at: datetime | None, want: datetime) -> bool:
    return at is not None and as_utc(at) == as_utc(want)


def _fell_back(w: World) -> bool:
    """우리 요청(카카오톡)이 문자로 대신 나감."""
    asked = w.session.get(OutreachMessage, w.request_id)
    return ((asked.channel, asked.fallback_sms, asked.status) == ("sms", True, "accepted")
            and rule("kakao_not_ready") in w.rules(asked))


def _answered(w: World, index: int = 0) -> bool:
    """음성: Them(index)이 든 통화가 받혀 끝났다(completed) — 받은 통화마다 뒤 확인·요약이 돌았다."""
    row = w.call(index)
    return row.status == "completed" and bool(row.summary_ko)


def _review_held(w: World, index: int, flag: str) -> bool:
    """음성: 그 통화의 뒤 확인이 깃발을 세우고 사람이 볼 확인 보고(review) 한 줄을 남겼다."""
    row = w.call(index)
    return rule(flag) in w.rules(row) and [r.call_id for r in w.reports("review")].count(row.id) == 1


def _claim_calls(w: World) -> list[OutreachCall]:
    """신원 주장 회신 통화(등록 번호로 거는 확인 통화) 줄."""
    rows = select(OutreachCall).where(OutreachCall.purpose == tools.CLAIM_PURPOSE).order_by(OutreachCall.id)
    return list(w.session.scalars(rows))


def _no_flags(w: World, index: int) -> bool:
    """음성: 그 통화의 뒤 확인이 깃발을 세우지 않았다."""
    return not set(w.rules(w.call(index))) & REVIEW_FLAGS and not [r for r in w.reports("review") if r.call_id == w.call(index).id]


REQUEST_ITEM = Check("my_requests 가 그 요청을 돌려준다",
                     lambda w: any(item["text"] == (w.request_body if w.column == "sms_reply" else w.call_purpose)
                                   for item in w.results(0)[0]["items"]))

# ── 상황 ─────────────────────────────────────────────────────────────

SITUATIONS: list[Situation] = [
    Situation(
        "S-01", "담당자가 아님 · 담당자가 주소록에 있음", RUN4, Setup(limits()),
        (Them("저는 담당이 아닙니다. 김민수 기사님이 담당이세요"), Model("find_contact", {"query": "김민수", "redirect": True}),
         ModelSays("알겠습니다. 김민수 기사님께 연락드리겠습니다")),
        (G("find_contact 는 상대 자신의 협력사에서 그 사람 한 명만 돌려준다",
               lambda w: [i["contact_id"] for i in w.results(0)[0]["items"]] == [w.people["kim"]]),
         G("그 사람에게 같은 매체(문자)의 새 줄 하나 — 우리 요청 글을 물려받고, 승인 받기라 초안·통로 0",
               lambda w: len(w.to("kim")) == 1 and w.to("kim")[0].body == w.request_body
               and w.to("kim")[0].channel == "sms" and w.to("kim")[0].status == "draft" and w.sent(w.to("kim")[0]) == 0,
               ONLY_REPLY),
         Check("물려줄 우리 요청이 없으면 새 줄을 만들지 않는다(Task 67 — 물려줄 것이 있을 때만)",
               lambda w: w.to("kim") == [] and w.calls_to("kim") == [], ONLY_IN | ONLY_CALL_IN),
         G("통화: 그 사람에게 새 통화 한 줄 — 우리 통화의 목적을 물려받고, 승인 받기라 초안",
               lambda w: [(c.purpose, c.status, c.prev_call_id) for c in w.calls_to("kim")]
               == [(w.call_purpose, "draft", w.call(0).id)] and w.to("kim") == [], ONLY_OUT)),
        ("V-01",), GUARDS("tools.scope", "tools.scope"),
        {"sms_in": "설계와 다름: 물려줄 요청 없음 — 먼저 온 문자에는 넘길 우리 요청이 없어 새 줄을 만들지 않는다(Task 67)",
         "call_in": "설계와 다름: 물려줄 요청 없음 — 걸려 온 통화에는 넘길 우리 목적이 없어 새 줄을 만들지 않는다(Task 67)"}),
    Situation(
        "S-02", "담당자가 아님 · 주소록에 없음 → 연락처 받아 제안", RUN4, Setup(limits()),
        (Them("저는 담당이 아니에요. 담당은 정우성 소장님이고 번호는 010-0000-0144 입니다"),
         Model("propose_contact", {"name": "정우성", "role_title": "소장", "phone": "010-0000-0144"}),
         ModelSays("감사합니다. 담당자가 확인한 뒤 연락드리겠습니다")),
        (Check("새 연락처는 제안 한 줄(pending)로만 남는다",
               lambda w: [(p.status, p.phone) for p in w.proposals("new")] == [("pending", w.number("new"))]),
         G("주소록은 그대로다", lambda w: w.unchanged("contacts")),
         Check("도구 결과·사건에 번호가 없다",
               lambda w: _no_number(w, w.results(0), "new") and _no_number(w, w.log(w.inbound()[0]), "new"), TEXT),
         Check("통화: 도구 결과·통화 사건·받아쓰기에 번호가 없다",
               lambda w: _no_number(w, w.results(0), "new") and _no_number(w, w.log(w.call(0)), "new")
               and _no_number(w, w.call(0).transcript_json, "new"), VOICE)),
        ("V-02",), GUARDS("tools.no_change", "tools.no_change")),
    Situation(
        "S-03", "지금 어렵다 · 나중에 → 다시 연락할 때 정함", RUN4, Setup(limits()),
        (Them("지금 현장이라 바쁩니다. 월요일 아침 일찍 다시 연락 주세요"),
         Model("schedule_callback", {"day_offset": 3, "hour": 6, "minute": 0}),
         ModelSays("네, 말씀하신 때에 다시 연락드리겠습니다")),
        (G("다시 연락할 때는 코드가 근무시간 안으로 정한다(월 06:00 → 월 08:00)",
               lambda w: w.results(0)[0] == {"when": "11월 30일 08:00", "needs_approval": True}
               and len(w.to("park")) == 1 and _same(w.to("park")[0].scheduled_at, _kst(w, day=30, hour=8)), TEXT),
         G("승인 받기라 초안이고 통로는 부르지 않는다",
               lambda w: [(r.status, r.send_mode, w.sent(r)) for r in w.to("park")] == [("draft", None, 0)], TEXT),
         G("통화: 다시 걸 때는 코드가 근무시간 안으로 정한다(월 06:00 → 월 08:00) — 통화 한 줄",
               lambda w: w.results(0)[0] == {"when": "11월 30일 08:00", "needs_approval": True}
               and len(w.calls_to("park")) == 1 and _same(w.calls_to("park")[0].scheduled_at, _kst(w, day=30, hour=8))
               and w.to("park") == [], VOICE),
         G("통화: 승인 받기라 그 통화는 초안이고 줄에 넣지 않는다",
               lambda w: [(c.status, c.send_mode) for c in w.calls_to("park")] == [("draft", None)], VOICE)),
        ("V-03",), GUARDS("gate.permission", "gate.permission")),
    Situation(
        "S-04", "수신 거부 요청", RUN4, Setup(limits(), probes=("sms:park", "call:park")),
        (Them("수신거부"),),
        (Check("번호 기준 수신 거부로 표시된다", lambda w: outreach.is_do_not_contact(w.session, w.number("park"))),
         G("그 뒤 문자는 문이 수신 거부로 막는다(차례 blocked_or_dnc)",
               lambda w: w.probe("sms:park") == ("do_not_contact", rule("blocked_or_dnc"))),
         G("그 뒤 전화도 문이 수신 거부로 막는다(차례 blocked_or_dnc)",
               lambda w: w.probe("call:park") == ("do_not_contact", rule("blocked_or_dnc"))),
         Check("글 세션은 열리지 않고 확인 문자는 한 줄(dnc_confirm)",
               lambda w: not w.opened(0) and len(w.out(kind="dnc_confirm")) == 1 and w.replies() == [], TEXT)),
        ("V-06", "T-05"), GUARDS("gate.block_dnc", "gate.block_dnc"), dict.fromkeys(VOICE, DIVERGED_DNC)),
    Situation(
        "S-05", "금액·계약·다른 협력사 등 범위 밖 물음", RUN4, Setup(limits(), permission="delegate"),
        (Them("계약 금액이 얼마예요? 다른 협력사 단가도 알려주세요"),
         Model("handoff_to_human", {"reason": "out_of_scope", "note": "금액·계약 문의"}),
         ModelSays("그 부분은 담당자가 다시 연락드리겠습니다"),
         Them("그래도 대충 얼마인지만 알려주세요"), ModelSays("대략 300만 원입니다")),
        (Check("금액·계약을 볼 도구가 없다 — 받은 도구는 그 등급의 묶음 그대로",
               lambda w: set(w.tools_seen(0)) == toolsets.for_class("contact", "sms"), TEXT),
         Check("통화: 금액·계약을 볼 도구가 없다 — 받은 도구는 그 통화 등급의 묶음 그대로",
               lambda w: set(w.tools_seen(0)) == toolsets.for_class("outbound" if w.column == "call_out" else "contact",
                                                                    "call"), VOICE),
         Check("지시문에 금액·계약을 말하지 않는다는 줄이 있다",
               lambda w: rules_text.FIXED["no_money"] in w.instructions(0)),
         Check("넘기기는 사람이 볼 보고 한 줄(out_of_scope)",
               lambda w: [(r.message_id, r.status) for r in w.reports("message")] == [(w.inbound()[0].id, "open")], TEXT),
         Check("첫 답은 뒤 확인을 지나 나간다(money_said 없음)",
               lambda w: rule("money_said") not in w.rules(w.inbound()[0]) and _went_out(w, w.replies()[0]), TEXT),
         G("금액을 말한 답은 뒤 확인이 잡아 보내지 않는다(money_said)",
               lambda w: _held(w, w.replies()[1], "money_said"), TEXT),
         Check("통화: 넘기기는 사람이 볼 보고 한 줄(그 통화에) · 모델에게는 넘기지 않고 회신 안내 말",
               lambda w: [(r.call_id, r.status) for r in w.reports("message")] == [(w.call(0).id, "open")]
               and w.results(0) == [{"transferred": False, "say": tools.SAY_HANDOFF}], VOICE),
         G("통화: 금액을 말한 통화는 뒤 확인이 잡는다(money_said) — 사람이 볼 확인 보고 한 줄",
               lambda w: _answered(w) and _review_held(w, 0, "money_said"), VOICE)),
        ("V-07", "R-07"), GUARDS("review.check", "review.check")),
    Situation(
        "S-06", "일정 사실 물음(허용 범위)", RUN4, Setup(limits(), permission="delegate"),
        (Them("철근 배근 언제 시작해요?"), Model("schedule_fact", {"activity": "철근 배근"}),
         ModelSays("철근 배근은 2027-03-01 시작입니다"),
         Them("끝나는 날은요?"), ModelSays("3월 9일에 끝납니다"),
         Them("혹시 철근 배근 언제 시작해요?"), Model("schedule_fact", {"activity": "철근 배근"}),
         ModelSays("네, 철근 배근은 2027-03-01 시작입니다"),
         Them("가람 현장 철근 배근 일정 알려주세요", sender="internal"),
         Model("schedule_fact", {"activity": "철근 배근", "site": "가람"}),
         ModelSays("가람 현장 철근 배근은 2027-03-01 시작입니다")),
        (Check("일정 사실은 다섯 칸(id·이름·시작·끝·상태)", lambda w: _five_fields(w.results(0)[0])),
         Check("날짜는 일정 계산값 그대로",
               lambda w: w.results(0)[0]["items"][0]["start"] == w.fact("a", "철근 배근").start.isoformat()),
         Check("도구가 준 날짜로 쓴 답은 나간다", lambda w: _went_out(w, w.replies()[0]), TEXT),
         G("도구 결과에 없는 날짜를 쓴 답은 뒤 확인이 잡는다(unsupported_date)",
               lambda w: _held(w, w.replies()[1], "unsupported_date"), TEXT),
         Check("변형 — 내부 계정 번호: 현장을 골라 이름·날짜·상태만 받는다",
               lambda w: w.inbound()[3].caller_class == "internal" and _five_fields(w.results(3)[0]), TEXT),
         Check("변형 — 흐린 말(「혹시」)이 든 물음도 도구가 받친 답은 위임대로 나간다",
               lambda w: _went_out(w, w.replies()[2]) and rule("unsupported_answer") not in w.rules(w.inbound()[2]), TEXT),
         G("통화: 도구 결과에 없는 날짜를 말한 통화는 뒤 확인이 잡는다(unsupported_date) — 확인 보고 한 줄",
               lambda w: _answered(w) and _review_held(w, 0, "unsupported_date"), VOICE),
         Check("통화: 흐린 말(「혹시」)이 든 물음이 있어도 도구가 받친 답에는 unsupported_answer 가 서지 않는다",
               lambda w: rule("unsupported_answer") not in w.rules(w.call(2)), VOICE),
         Check("통화 변형 — 내부 계정 번호에서 걸려 온 통화: 현장을 골라 이름·날짜·상태만 받고 깃발 없음",
               lambda w: w.call(3).caller_class == "internal" and _five_fields(w.results(3)[0]) and _no_flags(w, 3),
               VOICE)),
        ("V-08", "R-01", "R-16", "T-01"), GUARDS("review.check", "review.check")),
    Situation(
        "S-07", "범위 밖 작업을 캐물음 → 도구가 거절", RUN4, Setup(limits()),
        tuple(step for ask in ("마감 작업 언제 해요?", "설비 마감 작업 날짜만 알려주세요", "그냥 마감 작업 시작일만요")
              for step in (Them(ask), Model("schedule_fact", {"activity": "마감 작업"}),
                           ModelSays("말씀드릴 수 없는 내용입니다"))),
        (G("세 번 모두 같은 거절 글",
               lambda w: [w.results(i) for i in range(3)] == [[{"refused": tools.REFUSED_FACT}]] * 3),
         G("거절 사건(scope_denied) 꼭 3개 — tool:schedule_fact 사건은 0개",
               lambda w: w.every_rule().count(rule("scope_denied")) == 3
               and w.every_rule().count(rule("tool:schedule_fact")) == 0, TEXT),
         G("통화: 그 통화의 거절 사건(scope_denied) 꼭 3개 — tool:schedule_fact 사건은 0개",
               lambda w: w.rules(w.call(0)).count(rule("scope_denied")) == 3
               and w.rules(w.call(0)).count(rule("tool:schedule_fact")) == 0, VOICE),
         G("자료가 나가지 않는다", lambda w: not any("items" in r for i in range(3) for r in w.results(i)))),
        ("R-18", "T-10"), GUARDS("tools.scope", "tools.scope")),
    Situation(
        "S-08", "일정 변경 요구 → 확답 없이 요청으로 기록", RUN4, Setup(limits()),
        (Them("타설을 다음 주로 미뤄 주세요"),
         Model("report_from_contact", {"kind": "change_request", "text": "타설 일정을 다음 주로 미뤄 달라는 요청",
                                       "quote": "타설을 다음 주로 미뤄 주세요"}),
         ModelSays("요청을 담당자에게 전달했습니다")),
        (G("일정 버전·승인 건·지연 사건이 그대로다", lambda w: w.unchanged("versions", "approvals", "delays")),
         Check("변경 요구는 보고(change_request, open) 한 줄 — 근거 말이 상대 글에 있다",
               lambda w: [(r.status, r.quote_found) for r in w.reports("change_request")] == [("open", True)])),
        ("V-09", "R-04"), GUARDS("tools.no_change", "tools.no_change")),
    Situation(
        "S-09", "지연·문제 보고 → 보고로 기록", RUN4, Setup(limits()),
        (Them("비 때문에 자재 반입이 이틀 늦어집니다"),
         Model("report_from_contact", {"kind": "delay", "text": "자재 반입 지연", "quote": "자재 반입이 이틀 늦어집니다"}),
         ModelSays("담당자가 확인하도록 전달했습니다")),
        (Check("보고(delay, open) 한 줄 — 근거 말이 상대 글에 있다",
               lambda w: [(r.status, r.quote_found) for r in w.reports("delay")] == [("open", True)]),
         G("지연 사건은 생기지 않는다", lambda w: w.unchanged("delays", "versions"))),
        ("R-03", "T-03"), GUARDS("tools.no_change", "tools.no_change")),
    Situation(
        "S-10", "사람 담당자를 찾음", RUN4, Setup(limits()),
        (Them("사람 담당자랑 직접 얘기하고 싶어요"), Model("handoff_to_human", {"reason": "asked_for_person"}),
         ModelSays("담당자가 다시 연락드리겠습니다")),
        (Check("문자에는 전환이 없다 — 「담당자가 다시 연락드리겠습니다」",
               lambda w: w.results(0) == [{"transferred": False, "say": tools.SAY_HANDOFF}]),
         Check("사람이 볼 보고 한 줄",
               lambda w: [r.text for r in w.reports("message")] == [tools.HANDOFF_TEXT["asked_for_person"]]),
         G("답은 권한대로 — 승인 받기라 초안·통로 0", _all_drafts, TEXT),
         Check("통화: 넘길 사람 번호가 없으면 넘기지 않고(전환 0) 회신을 약속한다 — 통화는 이어져 상대가 끊는다",
               lambda w: w.voices[0].transfers == [] and _answered(w)
               and (rule("tool:handoff_to_human"), "allowed") in [(n, v) for n, v, _ in w.log(w.call(0))], VOICE)),
        ("V-10", "R-05"), GUARDS("gate.permission", None), COMMON_ONLY | dict.fromkeys(VOICE, VOICE_COMMON_ONLY)),
    Situation(
        "S-11", "안전사고·긴급", RUN4, Setup(limits()),
        (Them("현장에서 사람이 다쳤어요! 빨리 와 주세요"),
         Model("handoff_to_human", {"reason": "emergency", "note": "현장 부상자 발생"}), ModelSays("담당자에게 바로 알렸습니다")),
        (Check("긴급 보고(emergency, open)가 그 문자에 붙어, 모델이 답을 마치기 전에 이미 있다(알림 길이 읽는 줄)",
               lambda w: [(r.status, r.message_id) for r in w.reports("emergency")] == [("open", w.inbound()[0].id)]
               and w.sims[0].open_reports_at_reply == [["emergency"]] and w.replies()[0].reply_to_id == w.inbound()[0].id,
               TEXT),
         G("답은 권한대로 — 승인 받기라 초안·통로 0", _all_drafts, TEXT),
         Check("통화: 긴급 보고(emergency, open)가 그 통화에 붙어 통화가 끝나기 전에 이미 있다(알림 길이 읽는 줄)",
               lambda w: [(r.status, r.call_id) for r in w.reports("emergency")] == [("open", w.call(0).id)]
               and as_utc(w.reports("emergency")[0].created_at) < as_utc(w.call(0).ended_at), VOICE)),
        ("V-13", "R-09"), GUARDS("gate.permission", None), COMMON_ONLY | dict.fromkeys(VOICE, VOICE_COMMON_ONLY)),
    Situation(
        "S-12", "「AI 인가요?」", RUN4, Setup(limits()),
        (Them("AI 인가요?"), ModelSays("네, 저는 ChronOS AI 비서입니다"),
         Them("그럼 철근 배근 시작일 알려주세요"), Model("schedule_fact", {"activity": "철근 배근"}),
         ModelSays("철근 배근은 2027-03-01 시작입니다")),
        (Check("지시문에 「사실대로 답한다」 줄이 있다", lambda w: rules_text.FIXED["ai"] in w.instructions(0)),
         Check("세션은 계속 — 다음 문자에도 답한다",
               lambda w: [r.reply_to_id for r in w.replies()] == [row.id for row in w.inbound()], TEXT),
         G("답은 권한대로 — 승인 받기라 초안·통로 0", _all_drafts, TEXT),
         Check("통화: AI 라고 답한 뒤에도 통화는 이어진다 — 같은 통화에서 다음 물음에 도구로 답하고, 끝은 상대가 끊음",
               lambda w: w.heard_in[0] == w.heard_in[1] and _five_fields(w.results(1)[0])
               and w.voices[0].ended == [("peer", w.call(0).duration_s)], VOICE)),
        ("V-16",), GUARDS("gate.permission", None), COMMON_ONLY | dict.fromkeys(VOICE, VOICE_COMMON_ONLY)),
    Situation(
        "S-13", "다른 언어", RUN4, Setup(limits()),
        (Them("Ngày mai có làm việc không?"),
         ModelSays("Vâng, chúng tôi sẽ báo lại.", text_ko="네, 다시 알려 드리겠습니다.", language="vi")),
        (G("언어는 제안 한 줄(language, pending)로만",
               lambda w: [(p.contact_id, p.language, p.status) for p in w.proposals("language")]
               == [(w.people["park"], "vi", "pending")]),
         G("연락처 언어는 그대로", lambda w: w.person("park").language == "ko"),
         Check("문자 답에 한국어 뜻(body_ko)이 있다",
               lambda w: w.replies()[0].body_ko == "네, 다시 알려 드리겠습니다.", TEXT)),
        ("V-17", "T-09"), GUARDS("tools.no_change", "tools.no_change"), dict.fromkeys(VOICE, DIVERGED_LANGUAGE)),
    Situation(
        "S-14", "우리가 보낸 요청에 대한 답 → 그 요청에 이어 붙임", marks("none", "run", "run", "run"),
        Setup(limits(), request_call=True),
        (Them("네 토요일 6명 가능합니다"), Model("my_requests", {}),
         Model("record_answer", {"question": "토요일 인원", "answer": "6명 가능", "quote": "토요일 6명 가능합니다"}),
         ModelSays("감사합니다. 담당자에게 전하겠습니다")),
        (Check("받은 줄이 우리 요청에 이어진다(reply_to_id)",
               lambda w: w.inbound()[0].reply_to_id == w.request_id, ONLY_REPLY),
         Check("우리 요청이 통화였으면 이을 문자가 없다(reply_to_id 없음) — 요청은 my_requests 로 찾는다",
               lambda w: w.inbound()[0].reply_to_id is None, ONLY_IN),
         REQUEST_ITEM,
         G("답이 근거 말과 함께 적힌다(quote_found)",
               lambda w: [(a["answer"], a["quote_found"]) for a in w.inbound()[0].answers_json] == [("6명 가능", True)],
               TEXT),
         G("통화: 답이 근거 말과 함께 그 통화에 적힌다(quote_found — 통화 뒤 확인이 받아쓰기의 상대 말에서 찾음)",
               lambda w: [(a["answer"], a.get("quote_found")) for a in w.call(0).answers_json] == [("6명 가능", True)],
               VOICE)),
        ("R-11", "T-04"), GUARDS("review.check", "review.check")),
    Situation(
        "S-15", "모르는 번호", IN_ONLY, Setup(limits(unknown_notice_daily=1), permission="delegate"),
        (Them("현장 일정 좀 알려주세요", sender="stranger"), Model("schedule_fact", {"activity": "철근 배근"}),
         ModelSays("철근 배근은 2027-03-01 시작입니다"),
         Them("답 좀 주세요", sender="stranger"), ModelSays("철근 배근은 2027-03-01 입니다"),
         Them("일정 알려주세요", sender="withheld"), Model("schedule_fact", {"activity": "철근 배근"}),
         ModelSays("철근 배근은 2027-03-01 입니다")),
        (G("모르는 번호에게는 일정 도구가 없다",
               lambda w: "schedule_fact" not in w.tools_seen(0) and w.results(0) == [{"error": tools.ERR_TOOL}]),
         Check("통화: 모르는 번호는 받는 범위 「모두」라 받되 짧은 최대 시간(max_call_seconds_unknown)",
               lambda w: w.call(0).caller_class == "unknown" and (rule("admission"), "allowed", "unknown_accepted")
               in w.log(w.call(0)) and w.voices[0].calls[0].spec.max_seconds == BASE_LIMITS["max_call_seconds_unknown"],
               VOICE),
         G("통화 변형 — 번호 표시 제한 전화도 모르는 번호의 묶음: 일정 도구 없음",
               lambda w: w.call(2).caller_class == "withheld" and "schedule_fact" not in w.tools_seen(2)
               and w.results(2) == [{"error": tools.ERR_TOOL}], VOICE),
         Check("통화: 모르는 상대에게 일정을 말한 통화는 뒤 확인이 잡는다(disclosed_to_unknown)",
               lambda w: _review_held(w, 0, "disclosed_to_unknown"), VOICE),
         Check("답은 고정 안내 한 번 — 둘째 문자는 기록만(auto_reply_limit)",
               lambda w: [(r.kind, r.body, r.status) for r in w.replies() if r.peer_number == w.number("stranger")]
               == [("notice", responder.NOTICE_TEXT, "accepted")]
               and w.admission(w.inbound()[1]) == ("blocked", "auto_reply_limit") and not w.opened(1), TEXT),
         Check("변형 — 번호 표시 제한 문자는 기록만: 받지 않음 판정·세션·일정 도구·답 없음",
               lambda w: w.inbound()[2].caller_class == "withheld"
               and (w.admission(w.inbound()[2]) or ("", ""))[0] == "blocked" and not w.opened(2)
               and [r for r in w.replies() if r.reply_to_id == w.inbound()[2].id] == [], TEXT)),
        ("R-02", "R-12", "T-02"), {"sms_in": "toolset.per_class", "call_in": "toolset.per_class"}),
    Situation(
        "S-16", "모르는 번호의 신원 주장 → 등록 번호로 회신", IN_ONLY, Setup(limits()),
        (Them("박현장입니다. 폰을 바꿨어요. 내일 일정 알려주세요", sender="stranger"),
         Model("take_message", {"text": "일정 문의", "claimed_name": "박현장"}),
         ModelSays("박현장 반장님, 내일 일정은 철근 배근입니다")),
        (Check("등급은 그대로 모르는 번호", lambda w: w.inbound()[0].caller_class == "unknown", TEXT),
         G("회신은 그 사람의 등록 번호로 가는 초안 한 줄(승인 받기)",
               lambda w: [(m.contact_id, m.peer_number, m.status, w.sent(m)) for m in w.out(body=tools.CLAIM_SMS)]
               == [(w.people["park"], None, "draft", 0)], TEXT),
         Check("답 글은 고정 안내", lambda w: [(r.kind, r.body) for r in w.replies()]
               == [("notice", responder.NOTICE_TEXT)], TEXT),
         Check("통화: 등급은 그대로 모르는 번호 · 모델은 도구가 정한 말(등록 번호로 회신)",
               lambda w: w.call(0).caller_class == "unknown" and w.results(0) == [{"say": tools.SAY_REGISTERED}], VOICE),
         G("통화: 회신은 그 사람의 등록 번호로 거는 통화 초안 한 줄(승인 받기 — 번호는 줄에 없음)",
               lambda w: [(c.contact_id, c.peer_number, c.status) for c in _claim_calls(w)]
               == [(w.people["park"], None, "draft")], VOICE)),
        ("R-13", "T-06"), {"sms_in": "tools.identity", "call_in": "tools.identity"}),
    Situation(
        "S-17", "여러 프로젝트에 걸친 사람 → 현장을 먼저 정함", RUN4, Setup(limits(), peer="multi"),
        (Them("철근 배근 언제예요?", sender="multi"), Model("schedule_fact", {"activity": "철근 배근"}),
         Model("schedule_fact", {"activity": "철근 배근", "site": "나래"}),
         ModelSays("나래 현장 철근 배근은 2028-05-01 시작입니다")),
        (G("처음에는 현장을 묻는다 — 후보 현장 이름만",
               lambda w: w.results(0)[0] == {"ask": tools.ASK_SITE, "sites": ["가람 현장", "나래 현장"]},
               TEXT | ONLY_CALL_IN),
         G("고른 뒤에는 그 현장 것만",
               lambda w: [i["start"] for i in w.results(0)[1]["items"]] == [w.fact("b", "철근 배근").start.isoformat()],
               TEXT | ONLY_CALL_IN),
         G("현장을 굳힌 사건(site_pinned)과 그 현장의 그 사람 대화로",
               lambda w: rule("site_pinned") in w.rules(w.inbound()[0])
               and w.inbound()[0].schedule_id == w.schedules["b"] and w.inbound()[0].contact_id == w.people["multi_b"],
               TEXT),
         G("답은 뒤 확인을 지난다", lambda w: w.replies()[0].fail_reason != responder.HELD_REASON, TEXT),
         G("통화: 현장을 굳힌 사건(site_pinned)과 그 현장의 그 사람 통화로 · 뒤 확인 깃발 없음",
               lambda w: rule("site_pinned") in w.rules(w.call(0)) and w.call(0).schedule_id == w.schedules["b"]
               and w.call(0).contact_id == w.people["multi_b"] and _no_flags(w, 0), ONLY_CALL_IN),
         Check("우리가 건 통화: 현장은 그 통화의 현장(가람)으로 이미 정해져 묻지 않는다 — 다른 현장 이름을 대도 그 현장 것만",
               lambda w: [i["start"] for r in w.results(0) for i in r["items"]] == [w.fact("a", "철근 배근").start.isoformat()] * 2,
               ONLY_OUT),
         G("우리가 건 통화: 그 현장에 없는 날짜(다른 현장 것)를 말하면 뒤 확인이 잡는다(unsupported_date)",
               lambda w: _review_held(w, 0, "unsupported_date"), ONLY_OUT)),
        ("R-06",), GUARDS("tools.scope", None, call_in="tools.scope", call_out="review.check"),
        {"call_out": "설계와 다름: 우리가 건 통화는 현장이 통화에 정해져 있어 「현장을 먼저 정함」이 없다 — 그 현장 범위로만 답한다"}),
    Situation(
        "S-18", "같은 번호 여러 사람(대표번호)", RUN4, Setup(limits(), peer="shared"),
        (Them("저희 회사 앞으로 온 요청 있어요? 철근 배근은 언제 시작해요?", sender="shared"), Model("my_requests", {}),
         Model("schedule_fact", {"activity": "철근 배근"}),
         ModelSays("철근 배근은 2027-03-01 시작입니다. 개인에게 온 요청은 이 번호로 말씀드릴 수 없습니다")),
        (G("대표번호는 개인에게 온 요청을 받지 못한다",
               lambda w: w.inbound()[0].caller_class == "shared" and w.results(0)[0] == {"refused": tools.REFUSED_PERSONAL},
               TEXT),
         G("통화: 대표번호에서 걸려 온 통화는 개인에게 온 요청을 받지 못한다",
               lambda w: w.call(0).caller_class == "shared" and w.results(0)[0] == {"refused": tools.REFUSED_PERSONAL},
               ONLY_CALL_IN),
         Check("우리가 건 대표번호 통화: 우리가 고른 그 사람의 범위(outbound) — 그 사람 앞 요청만 돌려준다(이 대본엔 0건)",
               lambda w: w.call(0).contact_id == w.people["rep_park"] and w.results(0)[0] == {"items": []}, ONLY_OUT),
         Check("협력사 범위의 작업은 답한다",
               lambda w: [i["start"] for i in w.results(0)[1]["items"]] == [w.fact("a", "철근 배근").start.isoformat()])),
        ("R-17",), GUARDS("door.class", None, call_in="door.class"),
        {"call_out": "설계와 다름: 우리가 건 대표번호 통화는 대표번호 등급(shared)이 아니라 고른 그 사람(outbound)의 범위다 — 받은 "
                     "사람이 그 사람인지는 confirm_person(모델)에 기댄다. 지키는 곳(무르기) 없음"}),
    Situation(
        "S-19", "수신 거부·차단 번호에서 들어옴", IN_ONLY,
        Setup(limits(), permission="delegate", dnc=("lee",), blocked=("blocked",), probes=("sms:lee",)),
        (Them("내일 작업 있나요?", sender="lee"), ModelSays("네 있습니다"),
         Them("일정 알려주세요", sender="blocked"), ModelSays("네")),
        (G("수신 거부 번호의 문자는 기록만 — 세션도 답도 없다",
               lambda w: w.admission(w.inbound()[0]) == ("blocked", "do_not_contact") and not w.opened(0), TEXT),
         G("차단 번호는 받지 않고 기록만",
               lambda w: w.admission(w.inbound()[1]) == ("blocked", "blocked_number") and not w.opened(1), TEXT),
         G("답 줄이 없다", lambda w: w.replies() == [], TEXT),
         Check("우리 쪽 보내기는 여전히 막힌다",
               lambda w: w.probe("sms:lee") == ("do_not_contact", rule("blocked_or_dnc"))),
         Check("통화: 수신 거부 번호의 전화는 받되 메모만 — 도구는 그 등급의 묶음(메모·끊기)뿐",
               lambda w: w.call(0).caller_class == "do_not_contact"
               and (rule("admission"), "allowed", "do_not_contact") in w.log(w.call(0))
               and set(w.tools_seen(0)) == toolsets.for_class("do_not_contact", "call"), VOICE),
         G("통화: 차단 번호의 전화는 받지 않고 거절(blocked_number) — 모델에게 간 것이 없다",
               lambda w: w.call(1).status == "rejected" and (rule("admission"), "blocked", "blocked_number")
               in w.log(w.call(1)) and not w.opened(1), VOICE)),
        ("R-14",), {"sms_in": "door.admit", "call_in": "door.admit"}),
    Situation(
        "S-20", "짧은 시간에 되풀이(문자 폭주)", marks("none", "run", "run", "run"),
        Setup(limits(inbound_burst_count=3, inbound_burst_minutes=5, auto_reply_hourly=2)),
        tuple(step for n in range(1, 6) for step in (Them(f"확인 부탁드립니다 {n}번"), ModelSays(f"네 확인했습니다 {n}"))),
        (G("자동 답은 대본이 정한 상한(한 시간 2)까지만 만든다", lambda w: len(w.replies()) == 2, TEXT),
         G("글 세션은 두 번만 열린다", lambda w: [w.opened(i) for i in range(5)] == [True, True, False, False, False], TEXT),
         G("그 뒤의 문자는 기록만 — 셋째는 자동 답 상한, 넷째부터는 폭주 문턱(5분에 3)",
               lambda w: [w.admission(row) for row in w.inbound()[2:]]
               == [("blocked", "auto_reply_limit"), ("blocked", "burst_limit"), ("blocked", "burst_limit")], TEXT),
         G("통화: 같은 번호가 짧은 시간에 거듭 걸면 문턱(5분에 3) 뒤부터 받지 않는다(burst_limit)",
               lambda w: [w.leg(i).status for i in range(len(w.calls))] == ["completed"] * 3 + ["rejected"] * 2, VOICE)),
        ("R-15", "T-08"), {**TEXT_GUARD("door.admit"), "call_in": "door.admit"}, {"call_in": DIVERGED_REPEAT}),
    Situation(
        "S-21", "근무시간 밖", marks("막음", "받는 범위 설정대로", "30분 규칙", "예약"),
        Setup(limits(reply_grace_minutes=30), permission="delegate", start="off"),
        (Them("오늘 작업 끝났습니다"), Wait(600), ModelSays("네 확인했습니다. 수고하셨습니다"),
         Them("자재는 몇 시에 오나요?"), Wait(2400), ModelSays("담당자가 확인 후 알려드리겠습니다")),
        (G("상대가 먼저 보낸 대화: 30분 안의 답은 근무 밖이어도 나간다(reply_within_grace)",
               lambda w: _went_out(w, w.replies()[0]) and rule("reply_within_grace") in w.rules(w.replies()[0]), ONLY_IN),
         G("우리 요청에 온 답: 30분 안이어도 유예 없이 다음 근무 시작(월 08:00)으로 예약",
               lambda w: (w.replies()[0].status, w.replies()[0].send_mode, w.sent(w.replies()[0]))
               == ("scheduled", "delegated", 0) and _same(w.replies()[0].scheduled_at, _kst(w, day=30, hour=8))
               and rule("reply_within_grace") not in w.rules(w.replies()[0]), ONLY_REPLY),
         G("30분을 넘긴 답은 다음 근무 시작(월 08:00)으로 예약",
               lambda w: (w.replies()[1].status, w.replies()[1].send_mode, w.sent(w.replies()[1]))
               == ("scheduled", "delegated", 0) and _same(w.replies()[1].scheduled_at, _kst(w, day=30, hour=8)), TEXT),
         G("우리가 걸 통화: 걸기 직전에 보니 근무시간 밖 — blocked_hours, 걸지 않음(모델에게 간 것 없음)",
               lambda w: w.call(0).status == "blocked_hours" and (rule("recheck_before_dial"), "blocked", "working_hours")
               in w.log(w.call(0)) and w.voices[0].dialed == [] and not w.opened(0), ONLY_OUT),
         Check("걸려 온 통화: 근무 밖에도 받는 범위(「모두」)대로 받는다",
               lambda w: (rule("admission"), "allowed", "known_caller") in w.log(w.call(0)) and w.opened(0), ONLY_CALL_IN),
         G("걸려 온 통화: 늦게 답하는 침묵이 이어지면 두 번 확인한 뒤 끊는다(silence)",
               lambda w: w.code_said(0) == [call_run.HELLO, call_run.HELLO, call_run.GIVE_UP]
               and [d for n, _, d in w.log(w.call(0)) if n == rule("silence")] == ["침묵 확인 1", "침묵 확인 2", "침묵으로 끊음"]
               and w.voices[0].ended[0][0] == "agent", ONLY_CALL_IN)),
        ("V-11",), GUARDS("gate.hours", None, call_out="runner.hours", call_in="call.silence"),
        {"call_in": "침묵 확인 말(「여보세요, 들리시나요?」)은 가짜 통화에서만 들린다 — SDK 에 「이 말을 하라」가 없어 실제로는 끊기만 돈다(Task 113)"}),
    Situation(
        "S-22", "시험 모드에서 허용 안 된 번호", marks("막음", "받지 않음", "기록만", "막음"),
        Setup(limits(), test_mode=True, probes=("sms:park",)),
        (Them("일정 알려주세요"), ModelSays("네")),
        (G("시험 모드 밖 번호의 문자는 기록만(outside_test) — 세션도 답도 없다",
               lambda w: w.admission(w.inbound()[0]) == ("blocked", "outside_test") and not w.opened(0)
               and w.replies() == [], TEXT, guarded=ONLY_IN),
         G("우리 쪽 보내기는 blocked_test — 통로 0번",
               lambda w: w.probe("sms:park") == ("blocked_test", rule("test_mode")) and w.delivered == [], ONLY_REPLY),
         G("우리가 걸 통화: 걸기 직전에 보니 시험 모드 밖 번호 — blocked_test, 걸지 않음",
               lambda w: w.call(0).status == "blocked_test" and (rule("recheck_before_dial"), "blocked", "test_mode")
               in w.log(w.call(0)) and w.voices[0].dialed == [], ONLY_OUT),
         G("걸려 온 통화: 시험 모드 밖 번호의 전화는 받지 않는다(outside_test) — 모델에게 간 것이 없다",
               lambda w: w.call(0).status == "rejected" and (rule("admission"), "blocked", "outside_test")
               in w.log(w.call(0)) and not w.opened(0), ONLY_CALL_IN)),
        ("V-12", "R-08"), {"sms_in": "door.admit", "sms_reply": "gate.test_mode", "call_out": "gate.test_mode",
                           "call_in": "door.admit"}),
    Situation(
        "S-23", "권한: 승인 받기 / 위임", marks("run", "후속 행동에", "run", "run"), Setup(limits()),
        (Them("내일 작업 시간 확인 부탁드립니다"), ModelSays("네 확인했습니다. 담당자가 연락드리겠습니다"),
         Permit("delegate"), Them("감사합니다. 기다리겠습니다"), ModelSays("네 알겠습니다")),
        (G("승인 받기: 답은 초안만 — 통로 0", lambda w: _draft_only(w, w.replies()[0]), TEXT),
         Check("위임: 나가고 [에이전트 발신 · 위임](send_mode delegated)", lambda w: _went_out(w, w.replies()[1]), TEXT),
         Check("통화: 통화 속 말은 권한과 상관없이 실시간으로 나간다 — 문을 지나는 답 줄이 없고, 권한을 바꾼 뒤의 말은 다음 통화",
               lambda w: w.replies() == [] and w.out() == [] and w.heard_in[0] != w.heard_in[1]
               and all(w.leg(i).status == "completed" for i in range(len(w.calls))), VOICE)),
        ("T-11",), GUARDS("gate.permission", None),
        dict.fromkeys(VOICE, "공통 겹만 — 통화의 권한은 후속 행동(후속 통화·문자 줄)에만 걸리는데 이 대본에는 후속 행동이 없다(지키는 곳 없음)")),
    Situation(
        "S-24", "받지 않음·실패(통화) / 실패·대신 보냄(메시지)", marks("run", "none", "none", "run"),
        Setup(limits(daily_sms_total=50, per_contact_sms_daily=5), permission="delegate", request_channel="kakao",
              channel_results=("failed:network", "unsure")),
        (Them("네 확인했어요. 몇 시까지 가면 되나요?"), ModelSays("담당자가 확인 후 알려드리겠습니다"),
         Them("답 기다릴게요"), ModelSays("곧 알려드리겠습니다"),
         Them("아직인가요?"), ModelSays("곧 알려드리겠습니다"), Wait(600)),
        (Check("카카오톡이 준비되지 않아 문자로 대신 보냄(fallback_sms)",
               _fell_back, TEXT),
         Check("실패한 답은 failed 와 까닭 문장",
               lambda w: (w.replies()[0].status, w.replies()[0].fail_reason) == ("failed", gate.FAIL_TEXT["network"]), TEXT),
         Check("결과를 모르는 답은 unconfirmed — 다시 보내지 않는다",
               lambda w: w.replies()[1].status == "unconfirmed" and w.sent(w.replies()[1]) == 1, TEXT),
         G("같은 답을 또 쓰면 문이 막는다(duplicate) — 통로는 그 글을 한 번만 받았다",
               lambda w: w.replies()[2].status == "draft" and rule("duplicate") in w.rules(w.replies()[2])
               and sum(w.sent(r) for r in w.replies() if r.body == "곧 알려드리겠습니다") == 1, TEXT),
         Check("우리가 건 통화: 걸지 못함(통로 결과 failed:network) — failed 와 까닭 문장 · call_result failed",
               lambda w: (w.call(0).status, w.call(0).fail_reason) == ("failed", call_run.FAILED_TEXT["failed"])
               and (rule("call_result"), "noted", "failed") in w.log(w.call(0)), ONLY_OUT),
         Check("우리가 건 통화: 받지 않은 통화에서 모델은 아무것도 받지 않았고, 분명한 실패라 다시 걸 줄도 없다(다시 걸기는 받지 않음만)",
               lambda w: not w.opened(0) and w.calls_to("park") == [] and w.voices[0].calls[0].failed == ("failed", "network"),
               ONLY_OUT)),
        (), {"sms_reply": "gate.duplicate"},
        {"call_out": "공통 겹만 — 걸지 못한 통화를 닫는 것은 통화 손잡이의 구조(받지 않음 외에는 다시 걸지 않음)이고 끌 무르기가 없다"}),
]

assert len({s.id for s in SITUATIONS}) == len(SITUATIONS)
TEXT_RULE_LINE = instructions.TEXT_RULES[0]  # 「두 문장까지」 — CHANNEL_ONLY 의 길이 경우가 읽는다
