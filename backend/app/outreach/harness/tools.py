"""도구 묶음(Task 67): 음성 에이전트와 글 에이전트가 연락 상대와 이야기할 때 받는 도구 — 한 벌을 둘이 같이 쓴다.
어느 도구를 받는지는 등급이 정하고(toolsets.for_class), 도구는 **불릴 때마다** 범위(Scope)를 다시 본다.

- 일정·연락처·협력사는 Scope 에서만 온다. 인자에는 id 칸이 없고(toolsets.ARGS, extra="forbid"), 현장은 이름으로만 받아 그
  상대의 후보(scope.schedule_ids) 안에서 코드가 맞춘다 — 맞으면 scope.pinned 로 굳히고 `site_pinned` 를 남긴다. 굳기 전에는
  사실도 본인 요청도 사람 찾기도 가지 않는다. 호출마다 범위의 짝이 지금도 있고 보이는지 다시 본다(사라지면 범위가 닫힌다).
- **한 현장으로 정해진 통화**에서 상대가 **다른 실제 현장**(저장된 다른 일정의 이름 — 빈칸·「현장」 꼬리를 떼고 서로 들어 있음)을
  대면 그 현장 것을 조용히 주지 않는다: 고정 안내 OTHER_SITE 「이 통화는 <그 현장> 현장 건입니다」 하나만 주고 scope_denied 하나.
  그 밖의 말(「우리 현장」「B동」「3층」「가람 아파트」)은 이 현장 일로 답한다. 보고(report_from_contact)는 버리지 않고 일정 없는
  보고로 남긴다. 문자는 그대로다(H1 — 통화만).
- **우리가 건 통화**(outbound·call)는 confirm_person(is_person=True) 이 그 통화에 적히기 전에는 그 사람의 요청·일정을 주는 도구
  (IDENTITY_TOOLS: my_requests · schedule_fact)가 CONFIRM_FIRST 로 거절한다(scope_denied). 아니라고 하면(is_person=False) 다시
  닫힌다. 받는 통화는 문이 번호로 상대를 정했으므로 그대로다(H1).
- 빈 범위는 「줄 없음」이다: 일정·협력사가 비면 저장소를 읽기 전에 빈 결과·거절을 돌려준다. 저장소의 「조건 없음」(None)은
  범위가 정말 그 현장 전부일 때만(사실 수준 all — 내부 등급) 넘긴다. 그 밖의 모든 등급은 — **우리가 건 통화의 상대도** —
  사람 찾기가 자기 협력사(scope.company_ids) 안이다. 「담당은 그 사람」으로 줄을 만드는 대상은 그 상대의 찾기 결과 안의 사람뿐
  (규칙 하나 — 내부는 그 현장 전체, 나머지는 자기 협력사).
- 등급은 상대에서 읽는다(box.caller_class — Caller.caller_class). Scope 안의 등급 칸은 읽지 않는다. 상자에 넣는 도구(names)는
  그 등급·매체의 묶음(toolsets.for_class) 안이어야 한다 — 세션이 묶음을 잘못 넘겨도 모르는 번호에게 일정 도구가 가지 않는다.
- 전화번호는 인자(새 연락처 제안의 번호 하나)로만 들어오고 결과·사건·오류 어디에도 나가지 않는다. 번호는 줄에서 코드가 읽고,
  모델이 준 자유 글은 저장·사건 전에 redact.hide_phones 를 거친다.
- 말·글로 한 신원 주장은 등급을 올리지 않는다: take_message 가 그 이름의 **등록된 번호로 가는** 회신을 만들 뿐이고, 답하는
  글은 그 이름이 주소록에 있든 없든 같다.
- 아무것도 바꾸지 않는다: 보고·요청·제안·답을 적어 사람이 확인하게 한다. 일정·승인·지연·주소록은 그대로다(예외 하나 — 우리가
  건 통화에서 「잘못된 번호」면 그 연락처의 phone_invalid). 수신 거부는 번호 기준 저장소 함수로만 남긴다.
- **한 번 불릴 때 도구 사건은 꼭 하나**: 돌았으면 `tool:<이름>` allowed(detail 은 가린 인자 → 결과 한마디 — 돌았지만 못 해 준
  것도 여기), 돌리지 않았으면 TOOL_REFUSALS 의 까닭 하나(blocked). 현장을 굳힌 호출에는 그 앞에 `site_pinned`(noted)가 하나 더
  있다. 전환을 나가는 문이 막으면 문의 판정(막은 차례 이름, blocked)을 이 줄에 따로 남기고, 위임으로 내보낸 후속 줄은 문이
  그 줄에 자기 판정을 남긴다. 남긴 뒤 곧바로 commit 하고, 문·통화 손잡이는 commit 한 뒤에 부른다(DB 를 쥐고 부르지 않는다).
- 한 대화가 만들 수 있는 줄에는 상한이 있다(아래 MAX_* 한 묶음): 신원 주장 회신 줄, 보고·메모, 긴급 알림(따로), 제안, 답.
  한 대화는 통화면 그 한 통, 문자면 **같은 번호에서 지난 24시간에 들어온 글들**(답만은 그 글 한 줄). **저장된 줄을 세므로**
  다음 차례에 상자를 새로 만들어도 이어서 센다. 넘으면 답은 평소와 같고 줄은 만들지 않으며 사건 detail 에 「상한」을 적는다.
- call 밖으로 예외가 나가지 않는다(취소만 지나간다): 붙을 줄이 지워졌거나(일정 지우기), DB 가 바쁘거나, 후속·도구가 무엇으로
  터져도 로그에는 예외의 종류만 남기고 모델에게는 정해 둔 한 줄({"error": ERR_BUSY})만 준다.
- 후속(회신·다시 연락·담당자에게)은 같은 매체의 새 줄이다: 권한이 「승인 받기」면 초안, 「위임」이면 gate.dispatch(때를 정한
  것은 예약 — 일꾼이 때가 되면 문에 넣는다). 줄의 글은 아래 고정 문장이거나 물려받은 목적·원래 요청 글이다.
"""

import asyncio
import logging
import unicodedata
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, get_args

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import db
from app.outreach import hours, phone, redact, site_name
from app.outreach.harness import events, facts, gate
from app.outreach.harness.review import REVIEW_KIND
from app.outreach.harness.toolsets import ALL, ARGS, for_class, tool_defs
from app.outreach.harness.types import (
    GATE_RULES,
    Actor,
    CallerClass,
    Medium,
    Ref,
    Scope,
)
from app.store import contacts, outreach
from app.store.tables import ScheduleRecord
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    ContactProposal,
    ContactReport,
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
)
from app.store.timeutil import as_utc

__all__ = ["AGENT", "AGENT_NAME", "Toolbox", "tool_defs"]

logger = logging.getLogger(__name__)

AGENT_NAME = "AI 비서"
AGENT = Actor("agent", None, AGENT_NAME, "user")  # 하네스가 만든 후속 줄을 문에 넣는 쪽(위임일 때만 지나간다)
REFUSED_FACT = "말씀드릴 수 없는 내용입니다"
REFUSED_PERSONAL = "개인에게 온 요청은 이 번호로 말씀드릴 수 없습니다"
ASK_SITE = "어느 현장 일인지 여쭤보세요"
OTHER_SITE = "이 통화는 {site} 현장 건입니다"  # 한 현장 통화에서 다른 현장을 물음(다른 자료는 주지 않는다)
CONFIRM_FIRST = "먼저 통화하시는 분이 맞는지 확인해 주세요"  # 우리가 건 통화에서 신원 확인 전
IDENTITY_TOOLS = frozenset({"my_requests", "schedule_fact"})  # 우리가 건 통화에서 confirm_person 뒤에만 도는 도구
SITE_TAIL = "현장"
SAY_REGISTERED = "등록된 번호로 다시 연락드리겠습니다"
SAY_MESSAGE = "담당자가 확인 후 연락드리겠습니다"
SAY_REPORTED = "담당자가 확인하도록 전달했습니다"
SAY_HANDOFF = "담당자가 다시 연락드리겠습니다"
NO_CALLBACK_TIME = "다시 연락드릴 시간을 정하지 못했습니다"
ERR_TOOL = "쓸 수 없는 도구입니다"
ERR_ARGS = "입력이 맞지 않습니다"
ERR_BUSY = "지금은 처리하지 못했습니다. 잠시 뒤 다시 해 주세요"
GATE_BLOCKED = "문이 막음"
# 후속 줄에 코드가 넣는 글(모델이 쓴 글은 넣지 않는다)
CLAIM_PURPOSE = "본인이라고 밝힌 분이 다른 번호로 연락해 와서, 등록된 번호로 본인이 연락한 것이 맞는지 확인"
CLAIM_SMS = ("ChronOS AI 비서입니다. 본인이라고 밝힌 분의 연락을 받아 등록된 번호로 확인드립니다. "
             "연락하신 적이 없으면 이 문자는 무시하셔도 됩니다.")
CALLBACK_PURPOSE = "상대가 정한 때에 다시 연락"
CALLBACK_SMS = "ChronOS AI 비서입니다. 말씀하신 때에 다시 연락드립니다."
VOICEMAIL_SMS = "안녕하세요, {site} 일정 담당 ChronOS AI 비서입니다. 전화를 드렸으나 연결되지 않아 문자 남깁니다. 다시 연락드리겠습니다."
HANDOFF_TEXT = {"asked_for_person": "사람 담당자를 찾음", "out_of_scope": "답할 수 없는 것을 물음",
                "schedule_change": "일정 변경을 요구함", "emergency": "긴급하다고 알림", "other": "담당자 확인 요청"}
HANDOFF_KIND = {"emergency": "emergency", "schedule_change": "change_request"}  # 그 밖은 message
TRANSFER_CLASSES = frozenset({"internal", "contact", "contact_multi", "shared", "outbound"})  # 내부·연락처 쪽
FIND_LIMIT, CLAIM_MATCHES = 5, 3
# 한 대화가 만들 수 있는 줄 수의 상한. 저장된 줄을 센다(상자를 새로 만들어도 이어진다). 한 대화는 통화면 그 한 통,
# 문자면 같은 번호(peer_number)에서 TEXT_WINDOW 안에 들어온 글들 — 답(MAX_ANSWERS)만은 그 글 한 줄.
MAX_CLAIM_ROWS = 3  # 신원 주장으로 등록된 번호에 가는 회신 줄 — 이름마다가 아니라 모두 합쳐
MAX_REPORTS = 5  # 보고·메모(contact_reports, 긴급 알림 밖)
MAX_EMERGENCY_REPORTS = 2  # 긴급 알림(contact_reports kind emergency) — 보통 보고 다섯이 긴급을 막지 못하게 따로
MAX_PROPOSALS = 5  # 새 연락처·언어 제안(contact_proposals)
MAX_ANSWERS = 20  # 답(answers_json): 그 줄에 질문이 있으면 질문 수까지, 없으면 이 값
TEXT_WINDOW = timedelta(hours=24)  # 문자 대화로 묶는 동안
OVER = "상한"  # 상한에 닿아 줄을 만들지 않았을 때 사건 detail 에 적는 말
CLAIM_KEY = "claim:"  # 신원 주장 회신 통화의 purpose_key 머리(뒤에 그 연락처 id)
REQUEST_DAYS, REQUEST_LIMIT, REQUEST_TEXT = 7, 5, 200
CLAIM_QUIET = timedelta(hours=24)  # 같은 사람 앞으로 신원 주장 회신을 다시 만들지 않는 동안
SHOWN_ARGS = 200  # 사건 detail 에 싣는 인자 글자 수
HIDDEN_ARGS = frozenset({"phone"})  # 값을 사건에 아예 싣지 않는 인자
_CLOSED = Scope("unknown", (), (), False, "none")
_OPEN_MESSAGE = ("draft", "scheduled", "sending")
_OPEN_CALL = ("draft", "scheduled", "blocked_hours", *outreach.LIVE_CALL)
_SENT_MESSAGE, _PLACED_CALL = ("accepted", "delivered"), ("completed", "no_answer", "busy")
_BAD_HOURS = (KeyError, TypeError, ValueError, AttributeError)  # 저장된 근무시간이 틀린 꼴(NoWorkingTime 은 ValueError)


@dataclass
class _Step:
    """도구가 한 일. note 는 사건 detail 의 결과 한마디, denied 면 범위 밖(scope_denied). follow 는 commit 한 뒤에 할 일
    (문·통화 손잡이 — 돌려준 글을 note 에 덧붙이고 사건은 그 뒤에 남긴다)."""

    result: dict[str, Any]
    note: str = ""
    denied: bool = False
    follow: Callable[[], Awaitable[str]] | None = None


@dataclass(frozen=True)
class _Made:
    """만든 후속 줄 하나. send_now 면 위임이라 commit 뒤에 문에 넣는다."""

    kind: str
    row_id: int
    send_now: bool
    delegated: bool


def _hide(text: str | None) -> str:
    return redact.hide_phones(text or "")


def _flat(text: str) -> str:
    return "".join(unicodedata.normalize("NFC", text).casefold().split())


def _match_site(site: str, sites: dict[int, tuple[str, ...]]) -> int | None:
    """상대가 말한 현장 이름에 맞는 후보 하나: 이름(부를 이름·다듬은 이름·전체 이름 가운데 하나)이 꼭 같은 후보가 하나거나,
    그 말이 이름에 든 후보가 하나일 때만(「가람」 → 「가람 현장」). 여러 현장 이름이 섞인 말·어느 후보에도 없는 말은 맞추지
    않는다 — 다시 묻는다."""
    want = _flat(site)
    if len(want) < 2:
        return None
    flat = {sid: [_flat(name) for name in names] for sid, names in sites.items()}
    for hits in ([sid for sid, names in flat.items() if want in names],
                 [sid for sid, names in flat.items() if any(want in name for name in names)]):
        if len(hits) == 1:
            return hits[0]
    return None


def _site_core(name: str) -> str:
    """현장 이름의 견줄 꼴: NFC·빈칸·대소문자를 맞추고 끝의 「현장」「공사」를 뗀다(그것뿐이면 빈 글). 프로젝트 관리의 같은 이름
    검사와 한 기준(site_name.key)."""
    return site_name.key(name)


def _score(said: str, names: Iterable[str]) -> tuple[int, int]:
    """한 현장이 그 말에 얼마나 구체적으로 걸리나: (길이, 온전함). 말 속에 든 가장 긴 이름 꼴의 길이(온전함 1), 아니면 말이 이름
    꼴 안에 들 때 말의 길이(온전함 0) 가운데 큰 것. 같은 길이면 이름이 통째로 든 쪽이 이긴다. 두 글자 밑의 꼴은 보지 않는다."""
    best = (0, 0)
    for core in (_site_core(name) for name in names):
        if len(core) < 2:
            continue
        if core in said:
            best = max(best, (len(core), 1))
        elif said in core:
            best = max(best, (len(said), 0))
    return best


def _which_site(said: str, here: Iterable[str], others: Iterable[Iterable[str]]) -> str:
    """상대가 말한 현장이 어느 쪽인가 — 「가장 구체적인 이름이 이긴다」(고침 1). 현장마다 이름 꼴(부를 이름·다듬은 이름·전체 이름 —
    site_name.names)로 _score 를 매겨 가장 높은 현장: 이 현장이면 "here", 다른 실제 현장이면 "other", 이 현장과 다른 현장이 같으면
    "tie"(다시 묻는다). 아무 이름에도 걸리지 않으면(「우리 현장」「B동」「3층」) 이 현장."""
    want = _site_core(said)
    mine = _score(want, here)
    best = max((_score(want, names) for names in others), default=(0, 0))
    if best > mine:
        return "other"
    return "tie" if best == mine and mine > (0, 0) else "here"


def _labels(sites: dict[int, tuple[str, ...]]) -> list[str]:
    """현장 고르기 물음에 싣는 이름: 부를 이름, 겹치면(빈칸·대소문자 무시) 그 현장들은 다듬은 이름, 그래도 겹치면 전체 이름."""
    shown = {sid: names[0] for sid, names in sites.items()}
    for fallback in (lambda names: site_name.clean(names[-1]), lambda names: names[-1]):
        seen = Counter(_flat(name) for name in shown.values())
        clashing = [sid for sid, name in shown.items() if seen[_flat(name)] > 1]
        if not clashing:
            break
        for sid in clashing:
            shown[sid] = fallback(sites[sid])
    return [_hide(name) for name in shown.values()]


def _site_label(name: str) -> str:
    """고정 안내에 넣을 현장 이름(끝의 「현장」을 떼어 「… 현장 건」이 겹치지 않게)."""
    text = " ".join(_hide(name).split())
    return text[:-len(SITE_TAIL)].rstrip() if text.endswith(SITE_TAIL) and len(text) > len(SITE_TAIL) else text


def _shown(parsed: BaseModel) -> str:
    """사건에 남길 인자: 준 것만, 번호 칸은 값 없이, 글은 번호를 가려 SHOWN_ARGS 자까지."""
    given = parsed.model_dump(exclude_defaults=True)
    text = "; ".join(f"{key}={redact.PHONE_MASK if key in HIDDEN_ARGS else value}" for key, value in given.items())
    return redact.hide_phones(text)[:SHOWN_ARGS]


def _alive(session: Session, pair) -> bool:
    """그 짝이 지금도 그대로인가: 그 일정의 보이는 연락처이고 그 (보이는) 협력사 사람이다."""
    person = session.get(Contact, pair.contact_id)
    if person is None or person.hidden or (person.schedule_id, person.company_id) != (pair.schedule_id, pair.company_id):
        return False
    company = session.get(ContactCompany, pair.company_id)
    return company is not None and not company.hidden and company.schedule_id == pair.schedule_id


def _live(session: Session, scope: Scope, caller_class: str) -> Scope:
    """지금도 남아 있는 것만 담은 범위(좁아지기만 한다). 볼 것이 하나도 없으면 닫힌 빈 범위. 등급은 상대의 것(caller_class)."""
    if caller_class == "internal":
        kept = tuple(sid for sid in scope.schedule_ids if session.get(ScheduleRecord, sid) is not None)
        if kept == scope.schedule_ids:
            return scope
        return Scope(caller_class, kept, (), False, "all") if kept else _CLOSED
    pairs = tuple(pair for pair in scope.candidates if _alive(session, pair))
    if pairs == scope.candidates:
        return scope
    if not pairs:
        return _CLOSED
    return Scope(caller_class, tuple(dict.fromkeys(pair.schedule_id for pair in pairs)), pairs,
                 scope.grant_personal, scope.grant_facts, scope.manager)


def _delegated(conn: NotifyConnection | None, lane: str) -> bool:
    return conn is not None and getattr(conn, f"agent_{lane}") == "delegate"


def _barred_rule(conn: NotifyConnection, number: str) -> str:
    """gate.may_reach 가 거짓일 때 어느 차례가 막았는가(문과 같은 차례: 시험 모드 → 차단·수신 거부). 판정은 문이 한다 —
    이것은 문이 돌려주지 않는 차례 이름을 사건에 적으려고 다시 읽을 뿐이다."""
    listed = conn.allow_numbers_json if isinstance(conn.allow_numbers_json, list) else ()
    allowed = {phone.normalize(item) for item in listed if isinstance(item, str)}
    return GATE_RULES[1] if conn.test_mode and number not in allowed else GATE_RULES[2]


class Toolbox:
    """한 통화·한 문자 응대의 도구 상자. scope 는 들어오는 문이 번호로 정한 범위(door.scope_of·outbound_scope),
    caller_class 는 **Caller.caller_class**(우리가 건 통화는 "outbound") — Scope 안의 등급은 닫힌 빈 범위에서 unknown 일 수
    있어 따로 받는다. names 는 그 세션에 준 도구 — toolsets.for_class(caller_class, medium) 이거나 그 안의 것(밖의 도구가 있으면
    ValueError). ref 는 사건·답·보고가 붙는 줄.

    call(name, args) 가 도구를 돌려 모델에게 줄 dict 를 준다(JSON 으로 바뀐다, 번호 없음). 묶음 밖·틀린 인자는 {"error": …}.
    results 는 돌려준 결과들(부른 차례 — 뒤 확인이 읽는다), scope 는 지금의 범위(현장을 굳혔으면 굳은 것).
    """

    def __init__(self, scope: Scope, medium: Medium, ref: Ref, *, names: Iterable[str], caller_class: CallerClass,
                 clock: Callable[[], datetime] | None = None) -> None:
        if not isinstance(scope, Scope) or not isinstance(ref, Ref):
            raise TypeError("Toolbox 는 Scope 와 Ref 를 받습니다")
        if medium not in get_args(Medium) or ref.kind != ("call" if medium == "call" else "message"):
            raise ValueError("매체는 sms·call 이고, 통화는 통화 줄에 문자는 메시지 줄에 붙습니다")
        if caller_class not in get_args(CallerClass):
            raise ValueError("등급표에 없는 등급입니다")
        if caller_class != scope.caller_class and scope != _CLOSED:
            raise ValueError("등급이 범위와 다릅니다 — 닫힌 빈 범위만 다른 등급에 붙습니다")
        self.names = frozenset(names)
        if not self.names <= for_class(caller_class, medium):
            raise ValueError("그 등급·매체의 도구 묶음(toolsets.for_class) 밖의 도구입니다")
        self.scope, self.medium, self.ref, self.caller_class = scope, medium, ref, caller_class
        self.results: list[dict[str, Any]] = []
        self.confirmed = False  # 이 통화에서 confirm_person(is_person=True) 이 적혔다(마지막 확인이 이긴다)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._control: Any = None
        self._lock = asyncio.Lock()

    def set_control(self, control: Any) -> None:
        """통화가 시작되면 그 손잡이(voice.session.CallControl) — 전환·끊기에 쓴다."""
        if self.medium != "call":
            raise ValueError("통화 손잡이는 통화에만 있습니다")
        self._control = control

    def now(self) -> datetime:
        return as_utc(self._clock())

    @property
    def needs_identity(self) -> bool:
        """우리가 건 통화인데 받은 사람이 그 사람인지 아직 확인되지 않았다."""
        return self.medium == "call" and self.caller_class == "outbound" and not self.confirmed

    @property
    def sid(self) -> int | None:
        """범위가 한 현장으로 정해졌으면 그 일정."""
        return self.scope.schedule_ids[0] if len(self.scope.schedule_ids) == 1 else None

    async def call(self, name: str, args: dict) -> dict[str, Any]:
        async with self._lock:  # 한 줄의 도구는 차례대로(범위 굳히기·줄 쓰기가 섞이지 않게)
            try:
                result = await self._call(name, args)
            except Exception as exc:  # noqa: BLE001 — DB 가 바쁨·줄이 지워짐·사건 칸이 깨짐·후속이나 도구가 터짐: 무엇이든 통화·응대를
                # 끊지 않고 모델에게 정해 둔 한 줄만 준다. 예외 글(줄 id·SQL·번호가 있을 수 있다)은 결과에도 로그에도 남기지 않는다.
                # 취소(CancelledError)는 Exception 이 아니라 그대로 지나간다.
                logger.warning("도구가 일을 마치지 못했습니다: %s", type(exc).__name__)
                result = {"error": ERR_BUSY}
        self.results.append(result)
        return result

    async def _call(self, name: str, args: dict) -> dict[str, Any]:
        if not isinstance(name, str) or name not in ALL:
            return await self._refuse("tool:unknown", "", {"error": ERR_TOOL})  # 모델이 준 이름은 적지 않는다
        if name not in self.names:
            return await self._refuse("tool_not_allowed", name, {"error": ERR_TOOL})
        try:
            parsed = ARGS[name].model_validate(args)
        except ValidationError as exc:  # 받은 값도, 모델이 지어낸 칸 이름도 싣지 않는다 — 우리 칸 이름만
            known = ARGS[name].model_fields
            fields = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"] and error["loc"][0] in known})
            return await self._refuse("tool_bad_args", name, {"error": ERR_ARGS, "fields": fields}, " ".join(fields))
        step = await asyncio.to_thread(self._work, name, parsed)
        if step.follow is not None:
            try:
                after = await step.follow()
            except BaseException:  # 후속이 취소되거나 터져도 한 일(이미 commit)의 사건은 남긴다 — 짧은 쓰기라 그 자리에서
                step.note = f"{step.note} · 후속을 마치지 못함"
                try:
                    self._write(lambda session: self._record(session, name, parsed, step))
                except Exception as exc:  # noqa: BLE001 — 사건을 못 적어도 원래의 취소·예외를 가리지 않는다
                    logger.info("도구 사건을 적지 못했습니다: %s", type(exc).__name__)
                raise
            step.note = " · ".join(part for part in (step.note, after) if part)
            await asyncio.to_thread(self._write, lambda session: self._record(session, name, parsed, step))
        return step.result

    async def _refuse(self, rule: str, name: str, result: dict[str, Any], note: str = "") -> dict[str, Any]:
        detail = events.tool_detail(name, note)
        await asyncio.to_thread(self._write, lambda session: events.record(session, self.ref, rule, "blocked", detail,
                                                                          now=self.now()))
        return result

    def _write(self, work: Callable[[Session], Any]) -> None:
        with Session(db._engine) as session:
            work(session)
            session.commit()

    def _work(self, name: str, parsed: BaseModel) -> _Step:
        """도구 하나를 짧은 세션 하나에서 돌리고 commit 한다(스레드에서 돈다). 실패하면 범위를 되돌린다."""
        before = self.scope, self.confirmed
        try:
            with Session(db._engine) as session:
                self.row(session)  # 붙을 줄이 지워졌으면(일정 지우기) 아무것도 만들지 않고 NotFound — call 이 한 줄로 답한다
                self.scope = _live(session, self.scope, self.caller_class)
                if name in IDENTITY_TOOLS and self.needs_identity:  # 우리가 건 통화: 신원 확인 전 — 범위 밖과 같은 거절 사건
                    step = _Step({"refused": CONFIRM_FIRST}, denied=True)
                else:
                    step = _TOOLS[name](self, session, parsed)
                if step.follow is None:
                    self._record(session, name, parsed, step)
                session.commit()
                return step
        except BaseException:
            self.scope, self.confirmed = before
            raise

    def _record(self, session: Session, name: str, parsed: BaseModel, step: _Step) -> None:
        shown = _shown(parsed)
        if step.denied:
            events.record(session, self.ref, "scope_denied", "blocked", events.tool_detail(name, shown), now=self.now())
        else:
            events.record(session, self.ref, events.tool_rule(name), "allowed", f"{shown} → {step.note}".strip(),
                          now=self.now())

    # ── 도구가 같이 쓰는 것 ──────────────────────────────────────────

    def row(self, session: Session) -> OutreachMessage | OutreachCall:
        found = session.get(OutreachCall if self.ref.kind == "call" else OutreachMessage, self.ref.row_id)
        if found is None:
            raise outreach.NotFound(self.ref.row_id)
        return found

    def link(self) -> dict[str, int]:
        """보고·제안 줄이 이 줄을 가리키는 칸."""
        return {"call_id" if self.ref.kind == "call" else "message_id": self.ref.row_id}

    def person(self, session: Session) -> Contact | None:
        """범위가 한 현장의 한 사람으로 정해졌으면 그 연락처."""
        ids = self.scope.contact_ids
        return session.get(Contact, ids[0]) if self.sid is not None and len(ids) == 1 else None

    def number(self, session: Session) -> str | None:
        """이 상대의 번호 — 줄에서 코드가 읽는다(한 사람으로 정해졌으면 그 연락처의 번호, 아니면 줄에 적힌 번호)."""
        person = self.person(session)
        return phone.normalize(person.phone if person is not None else self.row(session).peer_number)

    def pin(self, session: Session, site: str) -> dict[str, Any] | None:
        """현장이 하나로 정해져 있으면 None — 통화에서 다른 현장 이름을 댔으면 고정 안내 {refused: OTHER_SITE}. 아니면 site 를 후보
        안에서 맞춰 굳히거나(None), 물을 것 {ask, sites} 를 준다."""
        scope = self.scope
        if not scope.site_required:
            here = site_name.names(session, self.sid) if self.medium == "call" else ()
            if here and scope.facts != "none" and len(_site_core(site)) >= 2:
                ids = session.scalars(select(ScheduleRecord.id).where(ScheduleRecord.id != self.sid)).all()
                which = _which_site(site, here, [site_name.names(session, sid) for sid in ids])
                if which == "other":
                    return {"refused": OTHER_SITE.format(site=_site_label(here[0]))}  # here[0] = 부를 이름
                if which == "tie":  # 이 현장과 다른 현장을 같은 만큼 말함 — 이 현장 이름만 싣고 다시 묻는다
                    return {"ask": ASK_SITE, "sites": [_hide(here[0])]}
            return None
        # 후보마다 (부를 이름, 다듬은 이름, 전체 이름) — 맞추기는 모두와, 묻거나 적을 때는 부를 이름
        sites = {sid: names for sid in scope.schedule_ids if (names := site_name.names(session, sid))}
        chosen = _match_site(site, sites)
        if chosen is None:
            return {"ask": ASK_SITE, "sites": _labels(sites)}
        self.scope = scope.pinned(chosen)
        row, person = self.row(session), self.person(session)
        if person is not None:  # 그 줄도 그 현장의 그 사람 대화로
            row.schedule_id, row.contact_id = chosen, person.id
        elif row.contact_id is None:
            row.schedule_id = chosen
        events.record(session, self.ref, "site_pinned", "noted", _hide(sites[chosen][0]), now=self.now())
        return None

    def conversation(self, session: Session) -> Any:
        """상한을 세는 대화의 줄 id 들: 통화는 이 통화 한 줄, 문자는 이 글과 같은 번호에서 TEXT_WINDOW 안에 들어온 글들
        (들어온 문자 한 건이 한 줄이라 — 번호가 적히지 않은 줄이면 이 글 하나)."""
        if self.ref.kind == "call" or (key := self.row(session).peer_number) is None:
            return [self.ref.row_id]
        return select(OutreachMessage.id).where(or_(
            OutreachMessage.id == self.ref.row_id,
            (OutreachMessage.peer_number == key) & (OutreachMessage.direction == "in")
            & (OutreachMessage.created_at >= self.now() - TEXT_WINDOW)))

    def room(self, session: Session, model: type[ContactReport] | type[ContactProposal], cap: int, *where: Any) -> bool:
        """이 대화에 딸린 그 표의 줄(where 로 더 좁힘)이 상한보다 적은가 — 저장된 줄을 센다."""
        back = model.call_id if self.ref.kind == "call" else model.message_id
        counted = select(func.count(model.id)).where(back.in_(self.conversation(session)), *where)
        return (session.scalar(counted) or 0) < cap

    def report(self, session: Session, kind: str, text: str, quote: str = "", *, unscheduled: bool = False) -> str:
        """보고 한 줄(한 대화에 MAX_REPORTS 줄까지 — 뒤 확인 줄은 세지 않음, 긴급 알림은 따로 MAX_EMERGENCY_REPORTS 줄까지). 돌려주는 것은 사건에
        적을 한마디. unscheduled 면 일정 없는 보고(다른 현장의 일)."""
        urgent = kind == "emergency"
        if not self.room(session, ContactReport, MAX_EMERGENCY_REPORTS if urgent else MAX_REPORTS,
                         (ContactReport.kind == "emergency") if urgent else ContactReport.kind.not_in(("emergency", REVIEW_KIND))):
            return f"보고는 {OVER}이라 남기지 않음"
        person = self.person(session)
        outreach.add_report(session, schedule_id=None if unscheduled else self.sid, medium=self.medium, contact_id=person.id if person else None,
                            kind=kind, text=_hide(text), quote=_hide(quote), status="open", created_at=self.now(),
                            **self.link())
        return "보고 남김"

    def follow_row(self, session: Session, fields: dict[str, Any], *, schedule_id: int | None, contact: Contact | None,
                   number: str | None = None, at: datetime | None = None, lane: str | None = None) -> _Made:
        """후속 줄 하나(같은 매체 — lane 을 주면 그 통로). 「승인 받기」면 초안, 「위임」이면 때가 있는 것은 예약,
        없는 것은 commit 뒤에 문에 넣는다. 받는 쪽은 연락처(번호는 문이 읽는다)이거나, 연락처가 없으면 줄에 적힌 번호."""
        lane = lane or self.medium
        delegated = _delegated(outreach.connection(session), lane)
        base = {"schedule_id": schedule_id, "contact_id": contact.id if contact else None,
                "peer_number": None if contact else number, "direction": "out", "origin": "agent",
                "origin_name": AGENT_NAME, "created_at": self.now(), "scheduled_at": at,
                "status": "scheduled" if at and delegated else "draft",
                "send_mode": "delegated" if at and delegated else None}
        if lane == "call":
            made = OutreachCall(**base, **{"language": contact.language if contact else "ko", **fields},
                                prev_call_id=self.ref.row_id if self.ref.kind == "call" else None)
        else:
            back = {"reply_to_id": self.ref.row_id} if self.ref.kind == "message" else {"call_id": self.ref.row_id}
            made = OutreachMessage(**base, **fields, **back, channel="sms")
        session.add(made)
        session.flush()
        return _Made("call" if lane == "call" else "message", made.id, delegated and at is None, delegated)

    def dispatching(self, made: list[_Made]) -> Callable[[], Awaitable[str]] | None:
        """위임이라 지금 내보낼 후속 줄을 문에 넣는 일(없으면 None). 문이 막으면 문이 그 줄에 자기 판정을 남긴다."""
        due = [one for one in made if one.send_now]
        if not due:
            return None

        async def follow() -> str:
            notes = []
            for one in due:
                outcome = await gate.dispatch(one.kind, one.row_id, AGENT, now=self.now())
                blocked = outcome.rule is not None
                notes.append(f"{GATE_BLOCKED}({GATE_RULES[outcome.rule]})" if blocked else f"문을 지남({outcome.code})")
            return ", ".join(notes)

        return follow


# ── 도구 ─────────────────────────────────────────────────────────────


def _asking(box: Toolbox, session: Session, site: str) -> _Step | None:
    ask = box.pin(session, site)
    if ask is None:
        return None
    return _Step(ask, denied=True) if "refused" in ask else _Step(ask, "현장을 물음")  # 다른 현장(통화) — 거절 사건 하나


def _carried(box: Toolbox, session: Session) -> dict[str, Any] | None:
    """후속 줄이 물려받을 것: 통화면 이 통화의 목적·질문, 문자면 이 문자가 답한 우리 요청 글. 없으면 None."""
    row = box.row(session)
    if box.ref.kind == "call":
        if not row.purpose.strip():
            return None
        names = ("purpose", "questions_json", "avoid_json", "purpose_key", "activity_id", "field_item_id", "chat_session_id")
        return {name: getattr(row, name) for name in names}
    asked = session.get(OutreachMessage, row.reply_to_id) if row.reply_to_id is not None else None
    if asked is None or asked.direction != "out" or asked.schedule_id != box.sid or not asked.body.strip():
        return None
    return {"body": asked.body, "activity_id": asked.activity_id, "field_item_id": asked.field_item_id,
            "chat_session_id": asked.chat_session_id}


def _find_contact(box: Toolbox, session: Session, a) -> _Step:
    """사람 찾기. 우리가 건 통화에서 신원 확인 전에는 목록을 주지 않는다 — 「담당은 그 사람」 후속 줄은 그대로 만든다(H1)."""
    step = _finding(box, session, a)
    if box.needs_identity and "items" in step.result:
        step.result = {"redirected": step.result["redirected"]}
        step.note += " · 신원 확인 전이라 목록은 주지 않음"
    return step


def _finding(box: Toolbox, session: Session, a) -> _Step:
    nobody = _Step({"items": [], "redirected": False}, "0명")
    if not box.scope.schedule_ids:
        return nobody
    if (ask := _asking(box, session, a.site)) is not None:
        return ask
    scope, sid = box.scope, box.sid
    # 그 현장 주소록 전체는 내부뿐 — 관리자 등급 연락처(일정 사실만 all)와 우리가 건 통화의 상대도 자기 협력사 안에서만 찾는다
    whole = scope.caller_class == "internal" and scope.facts == "all"
    if scope.facts == "none" or (not whole and not scope.company_ids):
        return nobody
    found = contacts.search(session, sid, a.query, FIND_LIMIT, company_ids=None if whole else list(scope.company_ids))
    firms = {person.company_id: contacts.get_company(session, sid, person.company_id).name for person in found}
    items = [{"contact_id": person.id, "name": _hide(person.name), "role_title": _hide(person.role_title),
              "company": _hide(firms[person.company_id])} for person in found]
    step = _Step({"items": items, "redirected": False}, f"{len(items)}명")
    if a.redirect and len(found) == 1:
        _redirect(box, session, found[0], step)
    return step


def _redirect(box: Toolbox, session: Session, target: Contact, step: _Step) -> None:
    """상대가 「담당은 그 사람」이라고 알려 줌 → 그 사람에게 같은 매체의 후속 줄. target 은 상대 자신의 범위로 돈 찾기의 결과
    하나뿐이다(찾기가 돌려줄 수 있는 사람에게만 — 등급마다 따로 가르지 않는다). 물려줄 것이 있을 때, 한 번만."""
    me, fields = box.person(session), _carried(box, session)
    if fields is None or (me is not None and me.id == target.id):
        step.note += " · 후속 없음"
        return
    model, back = (OutreachCall, OutreachCall.prev_call_id) if box.ref.kind == "call" else (OutreachMessage,
                                                                                         OutreachMessage.reply_to_id)
    again = session.scalar(select(model.id).where(back == box.ref.row_id, model.contact_id == target.id).limit(1))
    step.result["redirected"] = True
    if again is not None:
        step.note += " · 후속은 이미 있음"
        return
    made = box.follow_row(session, fields, schedule_id=box.sid, contact=target)  # 통화의 언어는 그 사람의 언어
    step.note += " · 후속 줄"
    step.follow = box.dispatching([made])


def _propose_contact(box: Toolbox, session: Session, a) -> _Step:
    number = phone.normalize(a.phone)
    if number is None or not phone.storable(number):
        return _Step({"saved": False, "note": "번호를 다시 확인해 주세요"}, "번호가 맞지 않아 저장하지 않음")
    saved = {"saved": True, "note": "담당자가 확인한 뒤 주소록에 넣습니다"}
    if not box.room(session, ContactProposal, MAX_PROPOSALS):
        return _Step(saved, f"제안은 {OVER}이라 남기지 않음")
    session.add(ContactProposal(schedule_id=box.sid, kind="new", name=_hide(a.name), role_title=_hide(a.role_title),
                                phone=number, created_at=box.now(), **box.link()))
    return _Step(saved, "제안 남김")


def _schedule_fact(box: Toolbox, session: Session, a) -> _Step:
    refused = _Step({"refused": REFUSED_FACT}, denied=True)  # 범위 밖이든 없는 작업이든 같은 글·같은 사건
    if not box.scope.schedule_ids:
        return refused
    if (ask := _asking(box, session, a.site)) is not None:
        return ask
    scope = box.scope
    if scope.facts == "none":
        return refused
    allowed = None if scope.facts == "all" else facts.allowed_for(session, box.sid, scope.company_ids, scope.contact_ids)
    found = facts.find(session, box.sid, a.activity, allowed=allowed)
    if not found:
        return refused
    items = [{"id": fact.id, "name": _hide(fact.name), "start": fact.start.isoformat(), "finish": fact.finish.isoformat(),
              "status": fact.status} for fact in found]
    return _Step({"items": items}, f"{len(items)}건")


def _my_requests(box: Toolbox, session: Session, a) -> _Step:
    refused = _Step({"refused": REFUSED_PERSONAL}, denied=True)
    if not box.scope.schedule_ids:
        return refused
    if (ask := _asking(box, session, a.site)) is not None:
        return ask
    person, sid = box.person(session), box.sid
    if not box.scope.personal or person is None:
        return refused
    since = box.now() - timedelta(days=REQUEST_DAYS)
    found = []  # (때, 채널, 글, 작업 id)
    for sent in outreach.thread(session, sid, person.id):
        when = as_utc(sent.sent_at or sent.created_at)
        if sent.direction == "out" and sent.kind == "normal" and sent.status in _SENT_MESSAGE and when >= since:
            found.append((when, sent.channel, sent.body, sent.activity_id))
    placed = select(OutreachCall).where(OutreachCall.schedule_id == sid, OutreachCall.contact_id == person.id,
                                        OutreachCall.direction == "out", OutreachCall.status.in_(_PLACED_CALL))
    for made in session.scalars(placed):
        when = as_utc(made.started_at or made.claimed_at or made.created_at)
        if when >= since:
            found.append((when, "call", made.purpose, made.activity_id))
    recent = sorted(found, key=lambda item: item[0], reverse=True)[:REQUEST_LIMIT]
    names = facts.names(session, sid) if any(item[3] for item in recent) else {}
    items = []
    for when, channel, text, activity_id in recent:
        day = when.astimezone(hours.KST)
        items.append({"channel": channel, "date": f"{day.month}월 {day.day}일", "text": _hide(text)[:REQUEST_TEXT],
                      "activity": _hide(names[activity_id]) if activity_id in names else None})
    return _Step({"items": items}, f"{len(items)}건")


def _record_answer(box: Toolbox, session: Session, a) -> _Step:
    row = box.row(session)
    written = list(row.answers_json or [])
    if len(written) >= (len(getattr(row, "questions_json", None) or ()) or MAX_ANSWERS):  # 질문 수까지, 질문이 없으면 MAX_ANSWERS
        return _Step({"ok": True}, f"답은 {OVER}이라 적지 않음")
    answer = {"question": _hide(a.question), "answer": _hide(a.answer), "quote": _hide(a.quote), "quote_found": False}
    row.answers_json = [*written, answer]  # quote_found 는 뒤 확인이 받아쓰기·받은 글과 견줘 정한다
    return _Step({"ok": True}, "답을 적음")


def _reached_already(session: Session, person: Contact, since: datetime) -> bool:
    """그 사람 앞으로 에이전트가 만든 줄이 아직 열려 있거나, 신원 주장 회신을 since 뒤에 이미 만들었는가."""
    texts = select(OutreachMessage.id).where(
        OutreachMessage.contact_id == person.id, OutreachMessage.direction == "out",
        or_(OutreachMessage.status.in_(_OPEN_MESSAGE) & (OutreachMessage.origin == "agent"),
            (OutreachMessage.body == CLAIM_SMS) & (OutreachMessage.created_at >= since)))
    calls = select(OutreachCall.id).where(
        OutreachCall.contact_id == person.id, OutreachCall.direction == "out",
        or_(OutreachCall.status.in_(_OPEN_CALL) & (OutreachCall.origin == "agent"),
            (OutreachCall.purpose_key == f"{CLAIM_KEY}{person.id}") & (OutreachCall.created_at >= since)))
    return session.scalar(texts.limit(1)) is not None or session.scalar(calls.limit(1)) is not None


def _claim_rows(box: Toolbox, session: Session) -> int:
    """이 대화(통화는 이 통화, 문자는 같은 번호의 24시간)에서 이미 만든 신원 주장 회신 줄 수 — 저장된 줄을 센다."""
    if box.ref.kind == "call":
        made = select(func.count(OutreachCall.id)).where(OutreachCall.prev_call_id == box.ref.row_id,
                                                         OutreachCall.purpose_key.startswith(CLAIM_KEY, autoescape=True))
    else:
        made = select(func.count(OutreachMessage.id)).where(OutreachMessage.reply_to_id.in_(box.conversation(session)),
                                                            OutreachMessage.origin == "agent", OutreachMessage.body == CLAIM_SMS)
    return session.scalar(made) or 0


def _claim_callbacks(box: Toolbox, session: Session, name: str) -> tuple[list[_Made], bool]:
    """신원 규칙: 그 이름의 사람(셋까지)마다 **등록된 번호로 가는** 같은 매체의 회신 줄. 닿을 수 없는 사람(번호 없음·잘못된
    번호·그 매체를 받지 않음·수신 거부), 지금 이 번호의 그 사람, 회신이 이미 있는 사람은 건너뛴다. 한 대화에 MAX_CLAIM_ROWS 줄
    까지(이름을 바꿔 대도 모두 합쳐) — (만든 줄, 상한 때문에 만들지 않은 것이 있는가)."""
    made: list[_Made] = []
    left = MAX_CLAIM_ROWS - _claim_rows(box, session)
    for person in contacts.by_name(session, name)[:CLAIM_MATCHES]:
        number = phone.normalize(person.phone)
        able = (phone.can_call(number) and person.can_call) if box.medium == "call" else (phone.can_sms(number) and person.can_sms)
        if (number is None or person.phone_invalid or not able or person.id in box.scope.contact_ids
                or outreach.is_do_not_contact(session, number) or _reached_already(session, person, box.now() - CLAIM_QUIET)):
            continue
        if len(made) >= left:
            return made, True
        fields = ({"purpose": CLAIM_PURPOSE, "purpose_key": f"{CLAIM_KEY}{person.id}"} if box.medium == "call"
                  else {"body": CLAIM_SMS})
        made.append(box.follow_row(session, fields, schedule_id=person.schedule_id, contact=person))
    return made, False


def _take_message(box: Toolbox, session: Session, a) -> _Step:
    kept = box.report(session, "message", a.text)
    if not a.claimed_name:
        return _Step({"say": SAY_MESSAGE}, kept)
    made, capped = _claim_callbacks(box, session, a.claimed_name)  # 찾았든 못 찾았든·상한에 닿았든 답하는 글은 같다
    note = f"{kept} · 등록된 번호로 회신 {len(made)}건{f'({OVER})' if capped else ''}"
    return _Step({"say": SAY_REGISTERED}, note, follow=box.dispatching(made))


def _report_from_contact(box: Toolbox, session: Session, a) -> _Step:
    ask = box.pin(session, a.site)  # 현장을 말했으면 굳힌다 — 못 맞춰도 보고는 남긴다(일정 없는 보고)
    if ask is not None and "refused" in ask:  # 한 현장 통화에서 다른 실제 현장의 일 — 이 현장에 붙이지 않고 일정 없는 보고로
        return _Step(ask, f"다른 현장 · {box.report(session, a.kind, a.text, a.quote, unscheduled=True)}")
    if ask is not None and not box.scope.site_required:  # 이 현장과 다른 현장을 함께 말함 — 어느 현장인지 몰라 일정 없는 보고로
        return _Step(ask, f"현장을 물음 · {box.report(session, a.kind, a.text, a.quote, unscheduled=True)}")
    return _Step({"say": SAY_REPORTED}, box.report(session, a.kind, a.text, a.quote))


def _schedule_callback(box: Toolbox, session: Session, a) -> _Step:
    """다시 연락할 때: 코드가 서울 날짜로 세고 그 사람(없으면 프로젝트)의 근무시간 안으로 옮긴다."""
    person, number, now = box.person(session), box.number(session), box.now().astimezone(hours.KST)
    wanted = datetime.combine(now.date() + timedelta(days=a.day_offset), time(a.hour, a.minute), tzinfo=hours.KST)
    try:
        at = hours.clamp(person.hours_json if person else None, contacts.calendar_of(session, box.sid), max(wanted, now))
    except _BAD_HOURS:
        at = None
    if at is None or number is None:
        return _Step({"refused": NO_CALLBACK_TIME}, "다시 연락할 때를 정하지 못함")
    model, back = (OutreachCall, OutreachCall.prev_call_id) if box.ref.kind == "call" else (OutreachMessage,
                                                                                         OutreachMessage.reply_to_id)
    earlier = session.scalar(select(model).where(back == box.ref.row_id, model.origin == "agent", model.direction == "out",
                                                 model.status.in_(("draft", "scheduled")), model.scheduled_at.is_not(None)))
    if earlier is not None:  # 때를 다시 말함 — 같은 줄을 고친다
        earlier.scheduled_at, delegated = at, earlier.status == "scheduled"
    else:
        fields = _carried(box, session) or ({"purpose": CALLBACK_PURPOSE} if box.ref.kind == "call" else {"body": CALLBACK_SMS})
        delegated = box.follow_row(session, fields, schedule_id=box.sid, contact=person, number=number, at=at).delegated
    when = f"{at.month}월 {at.day}일 {at:%H:%M}"
    return _Step({"when": when, "needs_approval": not delegated}, f"{when} {'예약' if delegated else '초안'}")


def _mark_do_not_contact(box: Toolbox, session: Session, a) -> _Step:
    number = box.number(session)
    if number is None:
        return _Step({"ok": False}, "표시할 번호가 없음")
    outreach.mark_do_not_contact(session, number, reason=_hide(a.reason)[:200])  # 번호 기준 — 연락처 줄은 고치지 않는다
    return _Step({"ok": True}, "수신 거부로 표시")


def _project_hours(session: Session, schedule_id: int | None, now: datetime) -> bool:
    try:
        return hours.is_working(None, contacts.calendar_of(session, schedule_id), now)
    except _BAD_HOURS:
        return False


def _handoff_to_human(box: Toolbox, session: Session, a) -> _Step:
    kept = box.report(session, HANDOFF_KIND.get(a.reason, "message"), a.note or HANDOFF_TEXT[a.reason])
    result = {"transferred": False, "say": SAY_HANDOFF}
    conn, control = outreach.connection(session), box._control
    number = phone.normalize(conn.handoff_number) if conn is not None else None
    if a.reason != "asked_for_person":
        why = ""
    elif box.medium != "call" or control is None:
        why = "통화 손잡이가 없어 넘기지 않음"
    elif box.caller_class not in TRANSFER_CLASSES:
        why = "넘기지 않는 상대"
    elif number is None:
        why = "넘길 번호가 없음"
    elif not _project_hours(session, box.sid, box.now()):
        why = "근무시간 밖"
    elif not gate.may_reach(session, number):  # 문이 막음 — 문의 판정을 이 줄에 따로 남긴다
        events.record(session, box.ref, _barred_rule(conn, number), "blocked", "넘길 번호에 연락할 수 없습니다", now=box.now())
        why = GATE_BLOCKED
    else:
        async def follow() -> str:
            try:
                result["transferred"] = bool(await control.transfer(number))
            except Exception as exc:  # noqa: BLE001 — 손잡이가 무엇으로 실패하든 통화는 잇는다. 예외 글에는 번호가 있을 수 있다
                logger.warning("전환이 예외로 끝났습니다: %s", type(exc).__name__)
            return "전환 시작" if result["transferred"] else "전환하지 못함"

        return _Step(result, kept, follow=follow)
    return _Step(result, " · ".join(part for part in (kept, why) if part))


def _end_call(box: Toolbox, session: Session, a) -> _Step:
    person, notes, made = box.person(session), [a.reason], []
    ours = person is not None and box.caller_class == "outbound"  # 우리가 건 통화에서만 주소록·문자 초안을 건드린다
    if ours and a.reason == "wrong_number":
        person.phone_invalid = True
        notes.append("잘못된 번호로 표시")
    if ours and a.reason == "voicemail" and person.can_sms and phone.can_sms(person.phone):  # 남기지 않고 끊고 문자 초안
        body = VOICEMAIL_SMS.format(site=_hide(site_name.spoken(session, box.sid)))  # 부를 이름(없으면 날짜를 뗀 이름)
        made.append(box.follow_row(session, {"body": body}, schedule_id=box.sid, contact=person, lane="sms"))
        notes.append("문자 초안")
    if a.language and person is not None and a.language.split("-")[0] != person.language.split("-")[0].lower():
        if box.room(session, ContactProposal, MAX_PROPOSALS):
            session.add(ContactProposal(schedule_id=box.sid, kind="language", contact_id=person.id, language=a.language[:10],
                                        created_at=box.now(), **box.link()))
            notes.append("언어 제안")
        else:
            notes.append(f"언어 제안은 {OVER}이라 남기지 않음")
    control, send = box._control, box.dispatching(made)

    async def follow() -> str:
        sent = await send() if send is not None else ""
        if control is not None:
            try:
                await control.hangup()
            except Exception as exc:  # noqa: BLE001 — 끊기가 실패해도 도구는 답한다(통화 일꾼이 끝을 본다)
                logger.warning("끊기가 예외로 끝났습니다: %s", type(exc).__name__)
        return sent

    return _Step({"ok": True}, " · ".join(notes), follow=follow)


def _confirm_person(box: Toolbox, session: Session, a) -> _Step:
    box.confirmed = a.is_person  # 사건과 같은 commit 에서만 남는다(_work 가 실패하면 되돌린다)
    return _Step({"ok": True}, "맞음" if a.is_person else "아님")


_TOOLS: dict[str, Callable[[Toolbox, Session, Any], _Step]] = {
    "find_contact": _find_contact, "propose_contact": _propose_contact, "schedule_fact": _schedule_fact,
    "my_requests": _my_requests, "record_answer": _record_answer, "take_message": _take_message,
    "report_from_contact": _report_from_contact, "schedule_callback": _schedule_callback,
    "mark_do_not_contact": _mark_do_not_contact, "handoff_to_human": _handoff_to_human, "end_call": _end_call,
    "confirm_person": _confirm_person,
}
