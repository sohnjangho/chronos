"""연락 하네스의 낱말(Task 64 — 여기서만 정의한다). 나가는 문·들어오는 문·도구 묶음·사건 기록·통로·글과 음성 세션이
모두 이것을 쓰고, 서로를 import 하지 않아도 같은 말을 한다. 표준 라이브러리만 쓴다(DB·제공사·LLM 없음).

- 전화번호는 어느 낱말에도 칸이 없다 — 번호는 줄(연락처·peer_number)에만 있고 코드가 붙인다.
- 값은 만들 때 검사한다(이름표 밖의 등급·코드·종류, 정수가 아닌 id 는 ValueError). 오류 글에 받은 값을 싣지 않는다.
- 상수는 모두 읽기 전용(MappingProxyType·frozenset·tuple). 글자를 직접 쓰지 말고 이 상수를 쓴다. 새 이름이 필요하면 여기에
  한 줄 더한다(소문자·밑줄만 — 번호나 모델 글이 이름에 들어갈 수 없게).

사건 이름(events.record 의 rule)과 한 번에 남기는 수:
- **보내기·걸기 한 번(gate.dispatch)**: 문의 판정 사건은 **꼭 하나** — 걸리면 걸린 차례의 GATE_RULES 이름(판정 blocked),
  지나가면 `channel_choice`(판정 allowed, detail 은 고른 통로 CHANNELS 하나). 그 판정을 설명하는 GATE_NOTES(판정 noted)는
  판정 사건 앞에 몇 개든 둘 수 있다. 통로를 부른 결과는 **따로** `delivery` 한 줄(판정은 DELIVERY_VERDICT: sent→allowed,
  failed→blocked, unsure→noted, detail 은 까닭 글).
- **도구 한 번(Toolbox.call)**: 사건 **꼭 하나** — 허용되면 `tool:<이름>`(allowed, detail 은 인자), 거절되면 TOOL_REFUSALS 의
  그 까닭 이름(blocked, detail 은 events.tool_detail(이름, …) 꼴 `tool=<이름> …`). 둘 다 남기지 않는다.
- FIXED_DETAILS 의 이름은 detail 이 정해 둔 코드 하나여야 한다(그 밖의 이름은 자유 글 — 저장할 때 비밀·번호를 지운다).
- 「판정 사건 꼭 하나」는 **dispatch 한 번마다**다(줄마다가 아니다): 예약됐다가 나중에 다시 dispatch 된 줄은 시도마다 판정
  사건이 하나씩, 시도한 차례대로 쌓인다.
- 도구가 **돌았지만** 바람을 이루지 못한 것(다시 연락할 근무시간을 찾지 못함, 제안한 연락처의 번호가 틀림 …)은 거절이 아니다 —
  `tool:<이름>` allowed 에 그 결과를 detail 로. TOOL_REFUSALS 는 하네스가 도구를 **돌리지 않은** 호출만.
- 통화 중 전환·회신을 나가는 문이 막으면 사건이 **두 가지** 남는다: 문의 판정(막은 차례 이름, 예 `test_mode` blocked)과 도구
  호출(`tool:handoff_to_human` allowed, 결과는 detail).
- 빈 범위(일정 0개)는 「아무것도 보이지 않음」이지 「거르지 않음」이 아니다 — 끝이 none 인 등급만 만들 수 있다.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal, Protocol, get_args

Medium = Literal["sms", "call"]  # 하네스가 보는 매체(카카오톡은 보내기만 하는 통로라 매체가 아니다)
ChannelName = Literal["sms", "kakao", "call"]
CHANNELS: tuple[str, ...] = get_args(ChannelName)  # 통로 이름(registry 가 받는 이름)
CallerClass = Literal[
    "internal", "contact", "contact_multi", "shared", "do_not_contact", "unknown", "withheld", "blocked", "outside_test",
    "outbound",  # 우리가 먼저 건 통화의 상대
]
FactLevel = Literal["none", "trade", "all"]  # 일정 사실을 어디까지: 없음 · 그 협력사·공종 · 전부(좁은 것부터)
# 등급마다 줄 수 있는 사실 수준의 끝(Scope 가 이보다 넓으면 ValueError — 만드는 쪽의 실수가 열린 쪽으로 가지 않게).
GRANT_CEILING: Mapping[str, str] = MappingProxyType({
    "internal": "all",
    "contact": "trade", "contact_multi": "trade", "shared": "trade", "outbound": "trade",
    "do_not_contact": "none", "unknown": "none", "withheld": "none", "blocked": "none", "outside_test": "none",
})
PERSONAL_CLASSES: frozenset[str] = frozenset({"contact", "contact_multi", "outbound"})  # 「본인에게 온 요청」을 말해도 되는 등급
ONE_PERSON_CLASSES: frozenset[str] = frozenset({"contact", "contact_multi", "outbound"})  # 일정마다 짝이 꼭 하나(둘이면 shared)
OutcomeCode = Literal[  # 이름표의 판정 코드
    "accepted", "queued", "scheduled", "blocked_test", "blocked_hours", "blocked_number", "do_not_contact", "limit_daily",
    "limit_person", "needs_approval", "duplicate", "held_for_review", "not_ready", "not_sendable",
    "unsure",  # 이름표 밖(제공사 리뷰 11-23): 보내기 요청은 나갔는데 결과를 모름 — 「보냈는지 확인 필요」, 줄은 unconfirmed
    "failed",  # 이름표 밖(Task 65): 문은 지나갔는데 통로가 보내지 못함(가지 않았음이 확실) — 줄은 failed, rule 은 None
]
DeliveryState = Literal["sent", "failed", "unsure"]
EventVerdict = Literal["blocked", "allowed", "noted"]
SHARED_TOOLS = ("find_contact", "propose_contact", "schedule_fact", "my_requests", "record_answer", "take_message",
                "report_from_contact", "schedule_callback", "mark_do_not_contact", "handoff_to_human")  # 음성·글 공통
VOICE_ONLY_TOOLS = ("end_call", "confirm_person")  # 통화에만(전환은 handoff_to_human 안에서)

# ── 사건 이름 ───────────────────────────────────────────────────────
# 나가는 문의 차례(Outcome.rule)와 그 판정 사건 이름. 1~6 은 설계 규칙 1 의 차례, 7 은 채널 고르기.
# 0 precheck = 앞 확인: 기본 연결이 있고 상태 ok · 줄과 연락처가 같은 일정 · 번호 있음·잘못된 번호 아님 · 그 번호로 그
# 통로를 쓸 수 있음(연락처 깃발과 phone.can_sms/can_call) · 현장 관리자가 아님 · 줄이 보낼 수 있는 상태(draft·scheduled·
# 통화의 blocked_hours)임.
GATE_RULES: Mapping[int, str] = MappingProxyType({
    0: "precheck", 1: "test_mode", 2: "blocked_or_dnc", 3: "working_hours", 4: "limits", 5: "permission", 6: "duplicate",
    7: "channel_choice",
})
GATE_NOTES: frozenset[str] = frozenset({
    "reply_within_grace",  # 답 유예 안이라 근무시간을 건너뜀(65)
    "kakao_not_ready",  # 카카오톡 통로·문안이 준비되지 않아 문자로(65)
})
DELIVERY_VERDICT: Mapping[str, str] = MappingProxyType({"sent": "allowed", "failed": "blocked", "unsure": "noted"})
DELIVERY_UPDATES: frozenset[str] = frozenset({"delivered", "failed", "gave_up"})  # delivery_update 의 detail(71)
ADMIT_REASONS: frozenset[str] = frozenset({  # admission 의 detail — 들어오는 문의 차례 표(66)
    "inbound_off",  # 1 받는 범위가 「받지 않음」
    "outside_test", "blocked_number",  # 2 시험 모드인데 허용 번호가 아님 · 차단 번호
    "burst_limit", "auto_reply_limit",  # 3 잦은 전화 · 그 번호로 나간 자동 답이 상한에 닿음
    "stop_word",  # 4 문자: 수신 거부 말
    "machine_text", "media_attached",  # 5 문자: 기계가 보낸 문자 · 사진이 붙음
    "do_not_contact",  # 6 수신 거부 연락처
    "unknown_not_accepted", "unknown_accepted",  # 7 모르는 번호·번호 숨김 — 모드가 all 이 아님 / all
    "line_busy",  # 8 전화: 동시 통화 한도
    "known_caller",  # 9 내부·연락처 등급
})
CALL_RESULTS: frozenset[str] = frozenset({"no_answer", "busy", "failed", "backend_error"})  # call_result 의 detail(88·95)
TOOL_REFUSALS: frozenset[str] = frozenset({
    "tool:unknown",  # 묶음 어디에도 없는 이름(모델이 지어냄)
    "tool_not_allowed",  # 아는 도구지만 이 등급·매체의 묶음에 없음
    "tool_bad_args",  # 인자가 틀림(extra="forbid" 포함)
    "scope_denied",  # 범위 밖 사실·사람을 물음
})
REVIEW_FLAGS: frozenset[str] = frozenset({  # 뒤 확인의 깃발(68)
    "unsupported_date",  # 도구 결과에 없는 날짜를 말함
    "unsupported_answer",  # 답의 근거 말(quote)이 상대 말에 없음
    "out_of_scope_said",  # 범위 밖 작업 이름을 말함
    "money_said",  # 금액·계약을 말함
    "disclosed_to_unknown",  # 모르는 사람에게 일정 이름을 말함
})
EVENT_RULES: frozenset[str] = GATE_NOTES | REVIEW_FLAGS | (TOOL_REFUSALS - {"tool:unknown"}) | frozenset({
    "delivery",  # 통로를 부른 결과(65) — 판정은 DELIVERY_VERDICT
    "delivery_update",  # 뒤에 상태를 물어 바뀜: 도착·실패·기다리다 그만(71) — detail 은 DELIVERY_UPDATES
    "no_answer_retry",  # 받지 않은 통화를 위임으로 한 번 더 예약(65)
    "admission",  # 들어온 전화·문자의 받기 판정(66 — 84·95 가 남김) — detail 은 ADMIT_REASONS
    "site_pinned",  # 여러 현장에 걸친 상대의 현장을 굳힘(67) — detail 은 현장 이름
    "reply_failed",  # 들어온 문자의 답을 만들지 못함(84)
    "held_for_review",  # 뒤 확인에 걸려 답을 보내지 않고 초안에 둠(84)
    "recheck_before_dial",  # 걸기 직전 다시 본 문(88)
    "silence", "time_limit",  # 통화 중 침묵 확인 · 최대 시간(88)
    "call_result",  # 대화 없이 끝난 통화: 받지 않음·통화 중·실패·백엔드 오류(88·95) — detail 은 CALL_RESULTS
    "hangup_by_person",  # 사람이 화면에서 통화를 끊음(88)
    "server_restart",  # 서버가 다시 떠서 닫은 줄(71·88)
})
FIXED_DETAILS: Mapping[str, frozenset[str]] = MappingProxyType({
    "channel_choice": frozenset(CHANNELS), "admission": ADMIT_REASONS, "call_result": CALL_RESULTS,
    "delivery_update": DELIVERY_UPDATES,
})

# 사건 이름마다 보여 줄 묶음 하나(개발 콘솔이 묶음을 지어내지 않게). 한글 이름표는 콘솔의 몫이다.
EVENT_GROUP_KEYS = ("gate_decision", "gate_note", "admission", "tool", "post_check", "channel_result", "call", "text_reply",
                    "recovery")


def _grouped(*groups: tuple[str, Iterable[str]]) -> Mapping[str, str]:
    out: dict[str, str] = {}
    for group, names in groups:
        for name in names:
            if name in out:
                raise ValueError(f"사건 이름이 두 묶음에 있습니다: {name}")
            out[name] = group
    return MappingProxyType(out)


EVENT_GROUPS: Mapping[str, str] = _grouped(
    ("gate_decision", GATE_RULES.values()),  # 나가는 문의 판정
    ("gate_note", GATE_NOTES),  # 판정을 설명하는 메모
    ("admission", {"admission"}),  # 들어오는 문의 받기 판정
    ("tool", {f"tool:{name}" for name in SHARED_TOOLS + VOICE_ONLY_TOOLS} | TOOL_REFUSALS | {"site_pinned"}),
    ("post_check", REVIEW_FLAGS | {"held_for_review"}),  # 뒤 확인과 그 결과
    ("channel_result", {"delivery", "delivery_update"}),  # 통로 결과·뒤에 바뀐 상태
    ("call", {"recheck_before_dial", "silence", "time_limit", "call_result", "hangup_by_person", "no_answer_retry"}),
    ("text_reply", {"reply_failed"}),  # 들어온 문자의 답 만들기
    ("recovery", {"server_restart"}),  # 서버가 다시 떠서 닫은 줄
)


class NotReady(Exception):
    """쓸 것이 아직 없다(등록되지 않은 통로 등). 아무것도 보내지 않았다. 판정 코드 not_ready 에 맞는다."""


def _check(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _ints(values: Iterable[object], what: str) -> tuple[int, ...]:
    out = tuple(values)
    _check(all(type(v) is int for v in out), f"{what} 는 정수 id 만 받습니다")
    return out  # type: ignore[return-value]


def _unique(values: Iterable[int]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class Actor:
    """보내기·걸기를 부른 쪽. system 은 일꾼(예약된 줄을 보낼 때)."""

    kind: Literal["user", "agent", "system"]
    user_id: int | None
    name: str
    role: str | None


@dataclass(frozen=True)
class Outcome:
    """문의 판정. code 는 이름표의 판정 코드, message 는 한국어, rule 은 걸린 차례(GATE_RULES 의 열쇠, 지나갔으면 None)."""

    code: OutcomeCode
    message: str
    rule: int | None = None
    scheduled_at: datetime | None = None

    def __post_init__(self) -> None:
        _check(self.code in get_args(OutcomeCode), "Outcome.code 는 이름표의 판정 코드만 받습니다")
        _check(self.rule is None or self.rule in GATE_RULES, "Outcome.rule 은 GATE_RULES 의 차례만 받습니다")


@dataclass(frozen=True)
class Candidate:
    """번호로 찾은 연락처 하나와 그 짝(일정·협력사). 공종은 협력사 줄에서 코드가 읽는다(여기 두 번 적지 않는다)."""

    schedule_id: int
    contact_id: int
    company_id: int

    def __post_init__(self) -> None:
        _ints((self.schedule_id, self.contact_id, self.company_id), "Candidate")


def _candidates(values: Iterable[object]) -> tuple[Candidate, ...]:
    out = tuple(values)
    _check(all(isinstance(c, Candidate) for c in out), "candidates 는 Candidate 만 받습니다")
    return out  # type: ignore[return-value]


@dataclass(frozen=True)
class Caller:
    """번호로 코드가 정한 상대. 등급은 말·글로 한 주장으로 바뀌지 않는다."""

    caller_class: CallerClass
    candidates: tuple[Candidate, ...]
    user_id: int | None  # internal 일 때 그 계정

    def __post_init__(self) -> None:
        _check(self.caller_class in get_args(CallerClass), "Caller.caller_class 가 등급표에 없습니다")
        object.__setattr__(self, "candidates", _candidates(self.candidates))
        _check(self.user_id is None or type(self.user_id) is int, "Caller.user_id 는 정수 id 나 None 입니다")


@dataclass(frozen=True)
class Scope:
    """그 상대에게 도구가 보일 수 있는 범위. 도구는 불릴 때마다 이것만 보고, 모델이 준 인자로 넓히지 않는다.
    만드는 쪽이 실수해도 열린 쪽으로 가지 않게 닫혀 있다(fail closed):

    schedule_ids — 볼 수 있는 일정(internal 은 그 계정이 볼 수 있는 일정 전부). internal 밖의 등급은 짝의 일정과 **같아야**
      한다(짝 없는 일정이 끼면 ValueError — 굳혔을 때 협력사 없는 사실 범위가 되지 않게). 같은 일정을 두 번 둘 수 없다.
    candidates — 일정마다 그 상대의 짝(일정·연락처·협력사). 연락처·협력사 범위는 이 짝에서만 나온다(contact_ids·company_ids).
      internal 은 짝이 없다.
    grant_personal · grant_facts — 현장이 하나로 정해졌을 때 줄 것(「본인에게 온 요청」·사실 수준). 등급의 끝
      (PERSONAL_CLASSES·GRANT_CEILING)보다 넓으면 ValueError — dataclasses.replace 로 넓혀도 같다. 한 일정에서 짝들이
      두 협력사 이상에 걸치면(대표번호를 두 협력사 사람이 씀) 끝은 none 이고 company_ids 는 비어 있다.
    ONE_PERSON_CLASSES 는 일정마다 짝이 꼭 하나다(같은 일정에 둘이면 shared). 일정이 0개인 범위는 끝이 none 인 등급만.
    site_required — 인자가 아니라 **계산**한다: 일정이 둘 이상이면 참. 그동안 facts 는 "none", personal 은 False 이고,
      pinned(일정) 이 한 현장으로 좁혀야 열린다.
    """

    caller_class: CallerClass
    schedule_ids: tuple[int, ...]
    candidates: tuple[Candidate, ...]
    grant_personal: bool
    grant_facts: FactLevel

    def __post_init__(self) -> None:
        cls = self.caller_class
        _check(cls in get_args(CallerClass), "Scope.caller_class 가 등급표에 없습니다")
        _check(self.grant_facts in get_args(FactLevel), "Scope.grant_facts 는 none·trade·all 가운데 하나입니다")
        _check(type(self.grant_personal) is bool, "Scope.grant_personal 은 bool 만 받습니다")
        schedule_ids = _ints(self.schedule_ids, "Scope.schedule_ids")
        candidates = _candidates(self.candidates)
        _check(len(set(schedule_ids)) == len(schedule_ids), "Scope.schedule_ids 에 같은 일정이 두 번 있습니다")
        if cls == "internal":
            _check(not candidates, "internal 범위에는 연락처 짝이 없습니다")
        else:
            _check(set(schedule_ids) == {c.schedule_id for c in candidates}, "Scope 의 일정이 짝의 일정과 다릅니다")
        per_schedule: dict[int, list[Candidate]] = {}
        for pair in candidates:
            per_schedule.setdefault(pair.schedule_id, []).append(pair)
        if cls in ONE_PERSON_CLASSES:
            _check(all(len(pairs) == 1 for pairs in per_schedule.values()), "한 사람 등급은 일정마다 짝이 하나입니다")
        _check(bool(schedule_ids) or GRANT_CEILING[cls] == "none", "빈 범위는 아무것도 보이지 않는 등급만 만들 수 있습니다")
        mixed = any(len({pair.company_id for pair in pairs}) > 1 for pairs in per_schedule.values())
        ceiling = "none" if mixed else GRANT_CEILING[cls]
        order = get_args(FactLevel)
        _check(order.index(self.grant_facts) <= order.index(ceiling), "그 등급에 줄 수 없는 사실 수준입니다")
        _check(not self.grant_personal or cls in PERSONAL_CLASSES, "그 등급에는 본인 요청을 말할 수 없습니다")
        object.__setattr__(self, "schedule_ids", schedule_ids)
        object.__setattr__(self, "candidates", candidates)

    @property
    def site_required(self) -> bool:
        """현장을 아직 고르지 않았는가(일정이 둘 이상)."""
        return len(self.schedule_ids) > 1

    @property
    def facts(self) -> FactLevel:
        """지금 말할 수 있는 사실 수준 — 현장을 고르기 전에는 늘 "none"."""
        return "none" if self.site_required else self.grant_facts

    @property
    def personal(self) -> bool:
        """지금 「본인에게 온 요청」을 말해도 되는가 — 현장을 고르기 전에는 늘 False(두 프로젝트가 섞이지 않게)."""
        return False if self.site_required else self.grant_personal

    @property
    def contact_ids(self) -> tuple[int, ...]:
        return _unique(c.contact_id for c in self.candidates)

    @property
    def company_ids(self) -> tuple[int, ...]:
        """짝의 협력사들 — 한 일정에서 두 협력사 이상에 걸치면(공유 번호) 비어 있다."""
        per_schedule: dict[int, set[int]] = {}
        for pair in self.candidates:
            per_schedule.setdefault(pair.schedule_id, set()).add(pair.company_id)
        if any(len(companies) > 1 for companies in per_schedule.values()):
            return ()
        return _unique(c.company_id for c in self.candidates)

    def pinned(self, schedule_id: int) -> "Scope":
        """그 현장 하나로 좁힌 범위(그 일정의 짝만). 이 범위의 일정이 아니면 ValueError — 고른 뒤에 넓히지 못한다."""
        _check(type(schedule_id) is int and schedule_id in self.schedule_ids, "그 현장은 이 범위의 후보가 아닙니다")
        pairs = tuple(c for c in self.candidates if c.schedule_id == schedule_id)
        return Scope(self.caller_class, (schedule_id,), pairs, self.grant_personal, self.grant_facts)


@dataclass(frozen=True)
class Ref:
    """사건·답·보고가 붙는 줄(outreach_messages 또는 outreach_calls 의 id)."""

    kind: Literal["message", "call"]
    row_id: int

    def __post_init__(self) -> None:
        _check(self.kind in ("message", "call"), "Ref.kind 는 message·call 가운데 하나입니다")
        _ints((self.row_id,), "Ref.row_id")


@dataclass(frozen=True)
class Delivered:
    """통로가 돌려준 결과 — 셋 가운데 하나. fail_text 는 한국어이고 번호·키가 없다.

    sent — 제공사가 받았다(provider_id). failed — 가지 않았음이 확실하다(고쳐서 다시 보내도 된다).
    unsure — 보내기 요청은 나갔는데 결과를 모른다(시간 초과·5xx·409, 제공사의 maybe_sent). 실패로 적으면 다시 보내져 글이
    두 번 가므로 「보냈는지 확인 필요」(Outcome "unsure", 줄 unconfirmed)로 두고 사람이 정한다.
    """

    state: DeliveryState
    provider_id: str | None = None
    fail_code: str | None = None
    fail_text: str | None = None

    def __post_init__(self) -> None:
        _check(self.state in get_args(DeliveryState), "Delivered.state 는 sent·failed·unsure 가운데 하나입니다")

    @property
    def ok(self) -> bool:
        """보냈음이 확실한가(sent). failed·unsure 는 거짓 — 둘은 state 로 가른다."""
        return self.state == "sent"


def _frozen(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _frozen(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_frozen(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True)
class ToolDef:
    """도구 하나의 정의. 음성 세션과 글 세션이 같은 객체를 받으므로 parameters 는 읽기 전용이다(만들 때 깊이 복사해 얼림 —
    dict 는 MappingProxyType, 목록은 tuple). 세션·SDK 에 넘길 JSON Schema 는 json_schema() 가 새 dict 로 준다."""

    name: str
    description: str
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _frozen(self.parameters))

    def json_schema(self) -> dict[str, Any]:
        return _plain(self.parameters)


class Channel(Protocol):
    """통로: 문자·카카오톡·통화가 하나씩 구현하고 registry 에 스스로 등록한다. 판정은 하지 않는다(문이 이미 했다).
    deliver 를 부르는 곳은 나가는 문 하나뿐이다."""

    name: str

    async def deliver(self, row_id: int) -> Delivered: ...
