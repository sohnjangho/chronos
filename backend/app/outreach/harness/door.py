"""들어오는 문(Task 66): 걸려 온 전화·들어온 문자의 **번호만** 보고 코드가 정한다 — 누구인가(resolve: 발신자 등급),
무엇을 볼 수 있는가(scope_of·outbound_scope: 범위), 받을 것인가(admit: 받기 판정표). 전화든 문자든 같은 등급표·같은 차례다.

- 등급을 올릴 길은 번호뿐이다. 말·글로 한 신원 주장, 모델이 준 값은 어느 함수의 인자에도 자리가 없다.
- 수신 거부 말·기계 문자는 코드만 판정한다(모델에게 묻지 않는다). 문턱 숫자는 판정할 때마다 store.outreach.limits 에서 읽는다.
- 번호·본문은 돌려주는 값(Caller·Scope·Admission)에 없고, 이 모듈은 로그·사건을 남기지 않는다 — `admission` 사건은 판정을
  받은 쪽(들어온 문자 응대·받는 통화)이 Admission.reason(ADMIT_REASONS 의 코드)으로 남긴다.
- 번호의 열쇠는 number_key 하나: 국내 번호는 phone.normalize 꼴, 나라 밖 번호는 `+숫자`(국내 열쇠와 겹치지 않는다), 번호가
  없으면 None. phone.NO_NUMBER(번호 없는 모든 상대가 같이 쓰는 값)는 열쇠가 아니다 — 차단·되풀이 셈에 쓰지 않는다.
- 수신 거부(받는 사람이 연락하지 말라고 함 — store.outreach.is_do_not_contact 만 판정)와 관리자 차단(blocked_numbers)은 다른
  것이다: 수신 거부 번호는 걸어 와 메모를 남길 수 있고, 차단 번호는 받지 않는다.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal, get_args

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.outreach import phone
from app.outreach.harness.types import (
    ADMIT_REASONS,
    Caller,
    Candidate,
    FactLevel,
    Medium,
    Scope,
)
from app.store import contacts, outreach, schedules
from app.store.tables import User
from app.store.tables_outreach import (
    BlockedNumber,
    Contact,
    NotifyConnection,
    OutreachCall,
)
from app.store.timeutil import as_utc

AdmitVerdict = Literal[
    "engage",  # 에이전트가 응대
    "notice",  # 문자: 일정 내용 없이 고정 안내만(모르는 번호)
    "record",  # 문자: 기록만
    "reject",  # 통화: 받지 않고 거절
    "missed",  # 통화: 받을 수 없음(부재중)
    "stop",  # 문자: 수신 거부 말
]
ADMIT_VERDICTS: tuple[str, ...] = get_args(AdmitVerdict)
MAX_LIVE_CALLS = 1  # 동시 통화 한도(한 번에 한 통) — 통화 일꾼의 한도와 같은 값이어야 한다
INTERNAL_ROLES = ("admin", "user")  # 로그인 계정 가운데 내부 등급인 역할(현장 관리자 field 는 아니다)
KNOWN_CLASSES = frozenset({"internal", "contact", "contact_multi", "shared"})  # 받기 판정표 9: 내부·연락처 등급
UNKNOWN_CLASSES = frozenset({"unknown", "withheld"})  # 받기 판정표 7
STOP_WORDS = ("수신거부", "수신 거부", "그만", "stop")  # 글 전체가 이 말이거나 이 말로 시작(뒤는 빈칸·문장 부호)
MACHINE_MARKS = ("인증번호", "(광고)", "[web발신]", "무료수신거부")  # 기계가 보낸 글의 표지(빈칸을 빼고 견준다)
# 등급마다 주는 것(본인에게 온 요청, 사실 수준). 등급의 끝(types.GRANT_CEILING)은 Scope 가 한 번 더 막는다.
_GRANTS: dict[str, tuple[bool, FactLevel]] = {
    "contact": (True, "trade"), "contact_multi": (True, "trade"), "shared": (False, "trade"),
    "do_not_contact": (False, "none"),
}
_FOREIGN = re.compile(r"\+[0-9]{7,15}")
_FOREIGN_INPUT = re.compile(r"\+[0-9\s\-.()]+")
_NOT_DIGIT = re.compile(r"[^0-9]")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Admission:
    """받기 판정 하나. reason 은 ADMIT_REASONS 의 코드(사건 `admission` 의 detail 로 그대로 쓴다). 번호·본문은 없다."""

    verdict: AdmitVerdict
    caller: Caller
    reason: str

    def __post_init__(self) -> None:
        if self.verdict not in ADMIT_VERDICTS:
            raise ValueError("Admission.verdict 는 받기 판정 낱말만 받습니다")
        if not isinstance(self.caller, Caller):
            raise TypeError("Admission.caller 는 Caller 만 받습니다")
        if self.reason not in ADMIT_REASONS:
            raise ValueError("Admission.reason 은 ADMIT_REASONS 의 코드만 받습니다")


def number_key(number: str | None) -> str | None:
    """그 번호의 열쇠: 국내 번호는 phone.normalize 꼴(숫자만), 나라 밖 번호(+82 가 아닌 +)는 `+숫자`, 번호가 없거나 번호로
    볼 수 없으면(None·빈 글·phone.NO_NUMBER·글자) None. 받는 통화·들어온 문자 줄의 peer_number 에는 이 값을 둔다(None 이면
    비운다) — 되풀이 셈이 이 열쇠로 줄을 찾는다."""
    if not isinstance(number, str):
        return None
    local = phone.normalize(number)
    if local is not None:
        return local
    text = number.strip()
    foreign = "+" + _NOT_DIGIT.sub("", text)
    if _FOREIGN_INPUT.fullmatch(text) and _FOREIGN.fullmatch(foreign) and not foreign.startswith(("+82", "+0")):
        return foreign
    return None


# ── 등급 ────────────────────────────────────────────────────────────


def _allowed(conn: NotifyConnection) -> set[str]:
    """시험 모드의 허용 번호(정리한 꼴). 목록이 아니거나 번호가 아닌 것은 버린다."""
    listed = conn.allow_numbers_json if isinstance(conn.allow_numbers_json, list) else []
    return {key for item in listed if isinstance(item, str) and (key := phone.normalize(item)) is not None}


def _is_blocked(session: Session, key: str) -> bool:
    return session.scalar(select(BlockedNumber.id).where(BlockedNumber.number == key).limit(1)) is not None


def _people(session: Session, key: str) -> tuple[Candidate, ...]:
    """그 번호로 주소록에서 보이는 사람들의 짝. 숨긴 사람·숨긴 협력사의 사람·「잘못된 번호」로 표시된 사람은 뺀다."""
    pairs = []
    for person in contacts.by_number(session, key):
        if person.hidden or person.phone_invalid:
            continue
        try:
            company = contacts.get_company(session, person.schedule_id, person.company_id)
        except contacts.NotFound:
            continue
        if not company.hidden:
            pairs.append(Candidate(person.schedule_id, person.id, company.id))
    return tuple(pairs)


def _internal_user(session: Session, key: str) -> int | None:
    """그 번호가 등록된 로그인 계정(관리자·사용자, 쓸 수 있는 계정만). 계정의 번호는 정리해서 견준다."""
    rows = session.execute(
        select(User.id, User.phone)
        .where(User.role.in_(INTERNAL_ROLES), User.status == "active", User.phone.is_not(None))
        .order_by(User.id)
    )
    return next((user_id for user_id, raw in rows if phone.normalize(raw) == key), None)


def resolve(session: Session, number: str | None, *, now: datetime) -> Caller:
    """번호로 발신자 등급을 정한다(위가 이긴다). 번호 밖의 것은 보지 않는다 — now 도 등급을 바꾸지 않는다.

    ① 시험 모드(알림 연결이 없어도)이고 허용 번호가 아님 → outside_test ② 관리자 차단 → blocked ③ 번호 없음 → withheld
    ④ store.outreach.is_do_not_contact → do_not_contact ⑤ 로그인 계정(관리자·사용자)의 번호 → internal
    ⑥ 보이는 연락처가 한 일정 안에 둘 이상 → shared ⑦ 여러 일정 → contact_multi ⑧ 한 곳 → contact ⑨ 없음 → unknown.
    """
    key = number_key(number)
    conn = outreach.connection(session)
    if (conn is None or conn.test_mode) and (conn is None or key is None or key not in _allowed(conn)):
        return Caller("outside_test", (), None)
    if key is not None and _is_blocked(session, key):
        return Caller("blocked", (), None)
    if key is None:
        return Caller("withheld", (), None)
    people = _people(session, key)
    if outreach.is_do_not_contact(session, key):
        return Caller("do_not_contact", people, None)
    user_id = _internal_user(session, key)
    if user_id is not None:
        return Caller("internal", (), user_id)
    per_schedule: dict[int, int] = {}
    for pair in people:
        per_schedule[pair.schedule_id] = per_schedule.get(pair.schedule_id, 0) + 1
    if any(count > 1 for count in per_schedule.values()):
        return Caller("shared", people, None)
    if len(per_schedule) > 1:
        return Caller("contact_multi", people, None)
    return Caller("contact" if people else "unknown", people, None)


# ── 범위 ────────────────────────────────────────────────────────────


def _internal_schedules(session: Session, user_id: int | None) -> tuple[int, ...]:
    """그 계정이 볼 수 있는 일정(관리자·사용자는 모든 일정). 지금 내부 계정이 아니면 없다."""
    user = session.get(User, user_id) if user_id is not None else None
    if user is None or user.role not in INTERNAL_ROLES or user.status != "active":
        return ()
    return tuple(record.id for record in schedules.list_records(session))


def _mixed(pairs: tuple[Candidate, ...]) -> bool:
    """어느 일정에서든 짝이 두 협력사 이상에 걸치는가."""
    seen: dict[int, int] = {}
    return any(seen.setdefault(pair.schedule_id, pair.company_id) != pair.company_id for pair in pairs)


def scope_of(session: Session, caller: Caller) -> Scope:
    """그 상대의 범위(닫힌 채로 — 일정이 둘 이상이면 Scope.pinned 로 한 현장에 굳히기 전에는 아무것도 열리지 않는다).

    internal → 그 계정이 볼 수 있는 일정, 사실 all. 볼 일정이 없으면(일정이 하나도 없거나 지금 내부 계정이 아니면) 닫힌
    빈 범위 — 타입이 빈 internal 범위를 받지 않아 **Scope 안의 등급만** unknown 이다. 누구인지는 Caller 가 말한다:
    Caller.caller_class 는 internal 그대로이고, 사건·화면·개발 콘솔은 Scope 가 아니라 Caller 의 등급을 쓴다.
    · contact·contact_multi → 그 짝, 사실 trade, 본인 요청 · shared → 그 짝,
    사실 trade(한 일정에서 두 협력사에 걸치면 none), 본인 요청 없음 · do_not_contact → 그 짝, 아무것도 없음 ·
    unknown·withheld·blocked·outside_test → 빈 범위. outbound 는 outbound_scope 로만 만든다(ValueError).
    """
    cls = caller.caller_class
    if cls == "outbound":
        raise ValueError("우리가 건 통화의 범위는 outbound_scope 로 만듭니다")
    if cls == "internal":
        seen = _internal_schedules(session, caller.user_id)
        if seen:
            return Scope(cls, seen, (), False, "all")
        return Scope("unknown", (), (), False, "none")  # 볼 일정이 없는 내부: 닫힌 빈 범위(등급은 Caller 가 internal 로 말한다)
    if cls not in _GRANTS:
        return Scope(cls, (), (), False, "none")
    personal, facts = _GRANTS[cls]
    pairs = caller.candidates
    if _mixed(pairs):
        facts = "none"
    return Scope(cls, tuple(dict.fromkeys(pair.schedule_id for pair in pairs)), pairs, personal, facts)


def outbound_scope(session: Session, schedule_id: int, contact_id: int) -> Scope:
    """우리가 먼저 건 통화의 상대: 그 일정 하나에 굳은 범위, 사실은 trade(자기 협력사·공종의 작업과 마일스톤만 — all 이
    아니다), 본인 요청. 연락처나 그 협력사가 그 일정 것이 아니면 NotFound."""
    person = contacts.get_contact(session, schedule_id, contact_id)
    company = contacts.get_company(session, schedule_id, person.company_id)
    return Scope("outbound", (schedule_id,), (Candidate(schedule_id, person.id, company.id),), True, "trade")


# ── 받기 판정 ───────────────────────────────────────────────────────


def _inbound_calls(session: Session, key: str | None, since: datetime) -> int:
    """그 번호의 받는 통화 줄 수(since 뒤, 받았든 거절했든). 번호 없는 전화는 한 묶음으로 센다."""
    if key is None:
        whose = or_(OutreachCall.caller_class == "withheld",
                    and_(OutreachCall.peer_number.is_(None), OutreachCall.contact_id.is_(None)))
    else:
        whose = or_(OutreachCall.peer_number == key,
                    OutreachCall.contact_id.in_(select(Contact.id).where(Contact.phone == key)))
    stmt = select(func.count(OutreachCall.id)).where(
        OutreachCall.direction == "in", OutreachCall.created_at >= since, whose)
    return session.scalar(stmt) or 0


def _auto_reply_counts(session: Session, key: str | None, now: datetime) -> tuple[int, int, int]:
    """그 번호로 나간 자동 답 수: (지난 한 시간, 오늘, 오늘의 고정 안내). 「오늘」은 서울 날짜."""
    day_start = datetime.combine(now.astimezone(outreach.KST).date(), time(), tzinfo=outreach.KST)
    hour_ago = now - timedelta(hours=1)
    rows = outreach.auto_replies(session, key or "", min(day_start, hour_ago))
    sent = [(as_utc(row.claimed_at), row.kind) for row in rows]
    return (sum(at >= hour_ago for at, _ in sent), sum(at >= day_start for at, _ in sent),
            sum(at >= day_start and kind == "notice" for at, kind in sent))


def _flat(body: str | None) -> str:
    """견줄 글: 전각·대소문자를 맞추고 이어진 공백을 한 칸으로."""
    if not isinstance(body, str):
        return ""
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", body).casefold()).strip()


def _is_stop(text: str) -> bool:
    """글 전체가 수신 거부 말이거나 그 말로 시작한다(바로 뒤가 글자·숫자면 다른 낱말 — 「그만큼」은 아니다)."""
    for word in STOP_WORDS:
        if text.startswith(word):
            rest = text[len(word):]
            if not rest or not rest[0].isalnum():
                return True
    return False


def _is_machine(text: str) -> bool:
    squeezed = text.replace(" ", "")
    return any(mark in squeezed for mark in MACHINE_MARKS)


def _admit_call(session: Session, key: str | None, cls: str, mode: str, limits: outreach.Limits, now: datetime,
                live_calls: int) -> tuple[AdmitVerdict, str]:
    since = now - timedelta(minutes=limits.inbound_burst_minutes)
    if _inbound_calls(session, key, since) >= limits.inbound_burst_count:
        return "reject", "burst_limit"  # 3 잦은 전화
    if cls == "do_not_contact":
        reason = "do_not_contact"  # 6 받되 메모만(도구는 등급이 정한다)
    elif cls in KNOWN_CLASSES:
        reason = "known_caller"  # 9
    elif cls in UNKNOWN_CLASSES and mode == "all":
        reason = "unknown_accepted"  # 7
    else:
        return "reject", "unknown_not_accepted"  # 7 (등급표 밖의 등급도 여기 — 받지 않는다)
    if live_calls >= MAX_LIVE_CALLS:
        return "missed", "line_busy"  # 8 받을 통화였는데 받을 수 없음
    return "engage", reason


def _admit_sms(session: Session, key: str | None, caller: Caller, mode: str, limits: outreach.Limits, now: datetime,
               body: str | None, has_media: bool) -> tuple[AdmitVerdict, str]:
    cls = caller.caller_class
    hourly, daily, notices = _auto_reply_counts(session, key, now)
    if hourly >= limits.auto_reply_hourly or daily >= limits.auto_reply_daily:
        return "record", "auto_reply_limit"  # 3 문자 폭주
    text = _flat(body)
    if _is_stop(text) and phone.normalize(key) is not None:
        return "stop", "stop_word"  # 4 (표시할 국내 번호가 있을 때만)
    in_book = bool(caller.candidates) or cls == "internal"
    if _is_machine(text) or not (phone.can_sms(key) or in_book):
        return "record", "machine_text"  # 5
    if has_media:
        return "record", "media_attached"  # 5
    if cls == "do_not_contact":
        return "record", "do_not_contact"  # 6
    if cls in KNOWN_CLASSES:
        return "engage", "known_caller"  # 9
    if cls in UNKNOWN_CLASSES and mode == "all":
        if notices >= limits.unknown_notice_daily:
            return "record", "auto_reply_limit"  # 고정 안내는 하루 상한까지
        return "notice", "unknown_accepted"  # 7
    return "record", "unknown_not_accepted"  # 7 (등급표 밖의 등급도 여기)


def admit(session: Session, medium: Medium, number: str | None, *, now: datetime, body: str | None = None,
          has_media: bool = False, live_calls: int = 0) -> Admission:
    """들어온 전화·문자 하나의 받기 판정(위가 이긴다 — 전화 / 문자):

    1 받는 범위가 「받지 않음」(연결이 없거나 모르는 값도) → reject / record · 2 등급 outside_test·blocked → reject / record
    · 3 되풀이: 그 번호의 받는 통화 줄이 inbound_burst_minutes 분에 inbound_burst_count 개 이상 → reject / 그 번호로 나간
    자동 답이 auto_reply_hourly·auto_reply_daily 에 닿음 → record · 4 문자: 수신 거부 말 → stop · 5 문자: 기계 문자(기계
    글의 표지, 또는 휴대전화가 아니고 주소록에도 없는 번호) · 사진 → record · 6 do_not_contact → engage(메모만) / record
    · 7 unknown·withheld → 받는 범위가 「모두」일 때만 engage / notice(하루 unknown_notice_daily 번까지), 아니면 reject /
    record · 8 전화: 받을 통화인데 live_calls 가 동시 통화 한도 이상 → missed · 9 내부·연락처 등급 → engage.
    문턱은 부를 때마다 store.outreach.limits 에서 읽는다. body 는 4·5 의 글 판정에만 쓴다(등급에는 쓰지 않는다).
    """
    if medium not in get_args(Medium):
        raise ValueError("medium 은 sms·call 가운데 하나입니다")
    caller = resolve(session, number, now=now)
    cls = caller.caller_class
    closed: AdmitVerdict = "reject" if medium == "call" else "record"  # 받지 않을 때: 전화는 거절, 문자는 기록만
    conn = outreach.connection(session)
    mode = conn.inbound_mode if conn is not None else "off"
    if mode not in ("known", "all"):
        return Admission(closed, caller, "inbound_off")
    if cls in ("outside_test", "blocked"):
        return Admission(closed, caller, "outside_test" if cls == "outside_test" else "blocked_number")
    key, limits, at = number_key(number), outreach.limits(conn), as_utc(now)
    if medium == "call":
        verdict, reason = _admit_call(session, key, cls, mode, limits, at, live_calls)
    else:
        verdict, reason = _admit_sms(session, key, caller, mode, limits, at, body, has_media)
    return Admission(verdict, caller, reason)
