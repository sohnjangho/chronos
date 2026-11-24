"""들어오는 문(Task 66): 걸려 온 전화·들어온 문자의 **번호만** 보고 코드가 정한다 — 누구인가(resolve: 발신자 등급),
무엇을 볼 수 있는가(scope_of·outbound_scope: 범위), 받을 것인가(admit: 받기 판정표). 전화든 문자든 같은 등급표·같은 차례다.

- 등급을 올릴 길은 번호뿐이다. 말·글로 한 신원 주장, 모델이 준 값은 어느 함수의 인자에도 자리가 없다. 번호 기준 신원의
  한계도 그대로다: 발신 번호를 속인 전화는 그 번호의 등급을 얻고, 내부 등급은 계정에 적힌 번호(가입할 때 본인이 적고
  관리자가 계정을 승인한 것)를 믿는다.
- 수신 거부 말·기계 문자는 코드만 판정한다(모델에게 묻지 않는다). 문턱 숫자는 판정할 때마다 store.outreach.limits 에서 읽는다.
- 번호·본문은 돌려주는 값(Caller·Scope·Admission)에 없고, 이 모듈은 로그·사건을 남기지 않는다 — `admission` 사건은 판정을
  받은 쪽(들어온 문자 응대·받는 통화)이 Admission.reason(ADMIT_REASONS 의 코드)으로 남긴다. 등급은 Caller.caller_class 에서
  읽는다(Scope.caller_class 가 아니다 — 닫힌 빈 범위는 등급 칸이 unknown 일 수 있다).
- 줄에 적는 번호는 stored_peer_number 하나: 국내 번호는 phone.normalize 꼴, 나라 밖 번호는 `+숫자`(국내 꼴과 겹치지 않는다),
  번호가 없으면 None. phone.NO_NUMBER(번호 없는 모든 상대가 같이 쓰는 값)는 번호가 아니다 — 차단·되풀이 셈에 쓰지 않는다.
- 수신 거부(받는 사람이 연락하지 말라고 함 — store.outreach.is_do_not_contact 만 판정)와 관리자 차단(blocked_numbers)은 다른
  것이다: 수신 거부 번호는 걸어 와 메모를 남길 수 있고(보이는 연락처일 때), 차단 번호는 받지 않는다.
- 되풀이 상한은 **들어온 것**과 **만든 것**을 센다(나간 것이 아니다): 그 번호에서 들어온 줄, 그 번호 앞으로 만든 자동 답·
  고정 안내 줄(초안이든 나갔든). 나가는 쪽의 상한(차지한 것)은 나가는 문이 따로 본다.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal, get_args

from sqlalchemy import ColumnElement, and_, func, or_, select
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
    OutreachMessage,
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
MAX_LIVE_CALLS = 1  # 동시 통화 한도(한 번에 한 통) — 이 숫자는 여기 한 곳에만 둔다(통화 일꾼이 들여와 쓴다)
INTERNAL_ROLES = ("admin", "user")  # 로그인 계정 가운데 내부 등급인 역할(현장 관리자 field 는 아니다)
KNOWN_CLASSES = frozenset({"internal", "contact", "contact_multi", "shared"})  # 받기 판정표 10: 내부·연락처 등급
UNKNOWN_CLASSES = frozenset({"unknown", "withheld"})  # 받기 판정표 9
NOT_TAKEN = ("rejected", "missed")  # 받는 통화 줄의 상태 가운데 응대하지 않은 것
AUTO_KINDS = ("auto_reply", "notice")  # 자동 답·고정 안내(메시지 종류)
# 수신 거부 말(빈칸·문장 부호·대소문자를 빼고 견준다): STOP_WHOLE 은 글 전체가 그 말일 때만, STOP_WORD 는 글 전체이거나
# 뒤에 공손한 맺음말(STOP_ENDINGS)만 붙었을 때만. 「수신거부 아닙니다」「그만 철수합니다」는 수신 거부가 아니다.
STOP_WHOLE = ("그만", "stop")
STOP_WORD = "수신거부"
STOP_ENDINGS = ("", "요", "입니다", "합니다", "해요", "할게", "할게요", "할께요", "하겠습니다", "해주세요", "해줘", "해주십시오",
                "처리해주세요", "부탁합니다", "부탁드립니다", "부탁드려요", "부탁드릴게요", "부탁해요", "바랍니다", "원합니다", "원해요", "신청",
                "신청합니다")
# 「전화·연락·문자 (하지|주지) 마세요 / 마십시오 / 마요 / 말아 주세요」가 **문장 전체**일 때(글자만 남겨 fullmatch). 앞에는
# STOP_LEADS 만 올 수 있다 — 남(「소장님한테」「현장에」)이나 때(「지금은」)가 붙으면 아니다. 「마시고」처럼 끝이 아닌 꼴도 아니다.
STOP_ACKS = ("네", "예", "아", "응", "넵")  # 「수신거부」 앞에 올 수 있는 대답 말 하나(「네, 수신거부요」)
STOP_LEADS = ("앞으로", "다시는", "이제", "더는", "더이상", "저한테", "제게", "이번호로")
STOP_PHRASE = re.compile(rf"(?:{'|'.join(STOP_LEADS)})*(전화|연락|문자)(하지|주지)?(마세요|마십시오|마요|말아주세요)")
# 글 어디에든 때를 말하면(「연락 주지 마세요. 지금 운전 중이라」) STOP_PHRASE 는 잠깐의 부탁이다 — 코드는 표시하지 않는다(모델의
# 도구·다시 연락은 그대로). 「수신거부」 말은 이것과 상관없다(뚜렷한 말).
STOP_TIME_WORDS = ("지금", "오늘", "당분간", "이따", "잠깐", "잠시", "아직", "내일", "모레", "나중", "이번주", "주말", "오전", "오후",
                   "한동안", "요즘", "금방")
_SENTENCE = re.compile(r"([^.?!\n]*)([.?!\n]|$)")  # 문장 하나와 그 끝 부호(. ? ! 줄 바꿈 · 끝)
# 기계가 보낸 글의 표지(빈칸을 빼고 견준다) — 주소록에 없는 번호의 글에만 쓴다(연락처의 글은 _CODE_ONLY 와 맨 앞 AD_MARK 만)
MACHINE_MARKS = ("인증번호", "인증코드", "verificationcode", "(광고)", "[web발신]", "[국제발신]", "무료수신거부")
AD_MARK = "(광고)"
# 등급마다 주는 것(본인에게 온 요청, 사실 수준). 등급의 끝(types.GRANT_CEILING)은 Scope 가 한 번 더 막는다.
_GRANTS: dict[str, tuple[bool, FactLevel]] = {
    "contact": (True, "trade"), "contact_multi": (True, "trade"), "shared": (False, "trade"),
    "do_not_contact": (False, "none"),
}
# 관리자 등급(11-24): 연락처 줄의 access_level 이 manager 면 사실 수준이 all(그 프로젝트의 모든 협력사·공종 일정)이 되는 등급.
# 공유 번호(shared — 한 번호를 여러 사람이 씀)는 넓히지 않는다. 본인 요청은 _GRANTS 그대로.
MANAGER_LEVEL = "manager"
_MANAGER_WIDENS = frozenset({"contact", "contact_multi"})
_FOREIGN = re.compile(r"\+[0-9]{7,15}")
_FOREIGN_INPUT = re.compile(r"\+[0-9\s\-.()]+")
_NOT_DIGIT = re.compile(r"[^0-9]")
_SPACE = re.compile(r"\s+")
_RELAY_PREFIX = re.compile(r"^(\[(web|국제)발신\]\s*)+")  # 통신사가 붙이는 머리 — 떼고 본다(그것만으로 기계 글이 아니다)
# 인증번호와 4~8자리 숫자뿐인 글(글자·숫자만 남긴 꼴로 견준다): 「인증번호 [0000] 를 입력해 주세요」「OTP 0000」
_CODE_ONLY = re.compile(r"(본인확인|your)?(인증번호|인증코드|verificationcode|otp)(는|은|is)?[0-9]{4,8}"
                        r"(입니다|를?입력(해주세요|하세요|해주십시오))?")
_OTP = re.compile(r"\botp\b")
_URL_ONLY = re.compile(r"((https?://|www\.)\S+\s*)+")  # 주소뿐인 글


@dataclass(frozen=True)
class Admission:
    """받기 판정 하나. reason 은 ADMIT_REASONS 의 코드(사건 `admission` 의 detail 로 그대로 쓴다). 번호·본문은 없다.
    confirm 은 verdict 가 stop 일 때만 뜻이 있다: 수신 거부 확인 문자를 보낼 것인가 — 주소록(보이는 연락처)·내부 계정의
    번호면 참, 주소록에 없는 번호면 거짓(번호는 표시하되 모르는 사람에게 문자를 보내지 않는다). stop 이 아니면 늘 거짓."""

    verdict: AdmitVerdict
    caller: Caller
    reason: str
    confirm: bool = False

    def __post_init__(self) -> None:
        if self.verdict not in ADMIT_VERDICTS:
            raise ValueError("Admission.verdict 는 받기 판정 낱말만 받습니다")
        if not isinstance(self.caller, Caller):
            raise TypeError("Admission.caller 는 Caller 만 받습니다")
        if self.reason not in ADMIT_REASONS:
            raise ValueError("Admission.reason 은 ADMIT_REASONS 의 코드만 받습니다")
        if type(self.confirm) is not bool or (self.confirm and self.verdict != "stop"):
            raise ValueError("Admission.confirm 은 수신 거부 말(stop)에만 참일 수 있습니다")


def stored_peer_number(number: str | None) -> str | None:
    """받는 통화·들어온 문자 줄의 peer_number 칸에 적을 값. **이것은 전화번호 그대로다 — 로그·사건·오류 글·화면에 쓰지
    않는다. 보여 주거나 기록할 것에는 phone.peer_key(이 값) 를 쓴다.**

    국내 번호(phone.normalize 가 받는 모든 꼴 — `+82 10-…` 포함)는 phone.normalize 꼴(숫자만), 나라 밖 번호(`+` 로 시작하고
    숫자 7~15자리, `+82`·`+0` 이 아닌 것)는 `+숫자`, 번호가 없거나 번호로 볼 수 없으면(None·빈 글·phone.NO_NUMBER·글자·
    `+82` 인데 국내 번호가 아닌 것) None — 그때는 칸을 비운다. 되풀이 셈이 이 값으로 줄을 찾으므로 줄은 꼭 이 꼴로 적는다."""
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


def _visible_pair(session: Session, person: Contact) -> Candidate | None:
    """그 사람의 짝. 숨긴 사람·「잘못된 번호」로 표시된 사람·협력사가 없거나 숨긴 사람은 None."""
    if person.hidden or person.phone_invalid:
        return None
    try:
        company = contacts.get_company(session, person.schedule_id, person.company_id)
    except contacts.NotFound:
        return None
    return None if company.hidden else Candidate(person.schedule_id, person.id, company.id)


def _people(session: Session, key: str) -> tuple[Candidate, ...]:
    """그 번호로 주소록에서 보이는 사람들의 짝. 숨긴 사람·숨긴 협력사의 사람·「잘못된 번호」로 표시된 사람은 뺀다."""
    pairs = (_visible_pair(session, person) for person in contacts.by_number(session, key))
    return tuple(pair for pair in pairs if pair is not None)


def _still_there(session: Session, pairs: tuple[Candidate, ...]) -> tuple[Candidate, ...]:
    """짝마다 지금도 그대로인가: 그 일정의 연락처가 있고, 보이고, 그 협력사 사람이다. 아닌 짝은 버린다."""
    kept = []
    for pair in pairs:
        try:
            person = contacts.get_contact(session, pair.schedule_id, pair.contact_id)
        except contacts.NotFound:
            continue
        if _visible_pair(session, person) == pair:
            kept.append(pair)
    return tuple(kept)


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
    key = stored_peer_number(number)
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
    **admit·resolve 가 돌려준 Caller 만 넘긴다 — 저장해 둔 칸으로 Caller 를 다시 만들어 넘기지 않는다.** 그래도 받은 것을
    그대로 믿지 않고 다시 본다: 내부는 계정을, 연락처 등급은 짝마다 그 일정의 연락처·협력사가 지금도 있고 보이는지.

    internal → 그 계정이 볼 수 있는 일정, 사실 all · contact·contact_multi → 그 짝, 사실 trade(짝의 연락처가 모두 관리자
    등급이면 all — 그래도 그 짝의 프로젝트뿐, 여러 프로젝트면 현장을 고른 뒤에만), 본인 요청 · shared → 그 짝,
    사실 trade(한 일정에서 두 협력사에 걸치면 none), 본인 요청 없음 · do_not_contact → 그 짝, 아무것도 없음 ·
    unknown·withheld·blocked·outside_test → 빈 범위. outbound 는 outbound_scope 로만 만든다(ValueError).
    볼 것이 하나도 남지 않으면(일정이 없는 내부·지금 내부 계정이 아님·짝이 모두 사라졌거나 숨겨짐) 닫힌 빈 범위 — 타입이
    그 등급의 빈 범위를 받지 않아 **Scope 안의 등급만** unknown 이다. 누구인지는 Caller.caller_class 가 말한다.
    """
    cls = caller.caller_class
    closed = Scope("unknown", (), (), False, "none")
    if cls == "outbound":
        raise ValueError("우리가 건 통화의 범위는 outbound_scope 로 만듭니다")
    if cls == "internal":
        seen = _internal_schedules(session, caller.user_id)
        return Scope(cls, seen, (), False, "all") if seen else closed
    if cls not in _GRANTS:
        return Scope(cls, (), (), False, "none")
    personal, facts = _GRANTS[cls]
    pairs = _still_there(session, caller.candidates)
    if not pairs and facts != "none":
        return closed
    if _mixed(pairs):
        facts = "none"
    elif cls in _MANAGER_WIDENS and _all_managers(session, pairs):
        facts = "all"
    return Scope(cls, tuple(dict.fromkeys(pair.schedule_id for pair in pairs)), pairs, personal, facts)


def _all_managers(session: Session, pairs: tuple[Candidate, ...]) -> bool:
    """짝의 연락처가 **모두** 관리자 등급인가. Scope 는 일정마다 다른 수준을 담지 못하므로(pinned 가 수준을 그대로 물려준다),
    같은 번호가 어느 프로젝트에서는 관리자이고 다른 곳에서는 아니면 좁은 쪽(trade)이다."""
    return bool(pairs) and all(
        getattr(session.get(Contact, pair.contact_id), "access_level", None) == MANAGER_LEVEL for pair in pairs)


def outbound_scope(session: Session, schedule_id: int, contact_id: int) -> Scope:
    """우리가 먼저 건 통화의 상대: 그 일정 하나에 굳은 범위, 본인 요청. 사실은 trade(자기 협력사·공종의 작업과 마일스톤만),
    그 연락처가 관리자 등급(access_level manager)이면 all(그 프로젝트의 모든 협력사 일정 — 다른 프로젝트는 아니다).
    연락처나 그 협력사가 그 일정 것이 아니면 NotFound."""
    person = contacts.get_contact(session, schedule_id, contact_id)
    company = contacts.get_company(session, schedule_id, person.company_id)
    facts: FactLevel = "all" if person.access_level == MANAGER_LEVEL else "trade"
    return Scope("outbound", (schedule_id,), (Candidate(schedule_id, person.id, company.id),), True, facts)


# ── 받기 판정 ───────────────────────────────────────────────────────


def _whose(model: type[OutreachMessage] | type[OutreachCall], key: str | None) -> ColumnElement[bool]:
    """그 번호와 주고받은 줄: 번호 칸이 그 번호이거나 연락처(어느 일정이든)의 번호가 그 번호. 번호가 없으면 번호 없는 상대의
    한 묶음 — 등급이 withheld 로 적힌 줄, 또는 번호도 연락처도 없는 줄."""
    if key is None:
        return or_(model.caller_class == "withheld", and_(model.peer_number.is_(None), model.contact_id.is_(None)))
    return or_(model.peer_number == key, model.contact_id.in_(select(Contact.id).where(Contact.phone == key)))


def _count(session: Session, model: type[OutreachMessage] | type[OutreachCall], *where: ColumnElement[bool],
           exclude: int | None = None) -> int:
    stmt = select(func.count(model.id)).where(*where)
    if exclude is not None:
        stmt = stmt.where(model.id != exclude)
    return session.scalar(stmt) or 0


def _received(session: Session, model: type[OutreachMessage] | type[OutreachCall], key: str | None, since: datetime,
              exclude: int | None) -> int:
    """그 번호에서 since 뒤에 들어온 줄 수(받았든 거절했든, 응대했든 기록만 했든). 이번 줄(exclude)은 세지 않는다."""
    return _count(session, model, model.direction == "in", model.created_at >= since, _whose(model, key), exclude=exclude)


def _replies_made(session: Session, key: str | None, since: datetime, kinds: tuple[str, ...] = AUTO_KINDS) -> int:
    """그 번호 앞으로 since 뒤에 **만든** 자동 답·고정 안내 줄 수 — 초안이든 나갔든(차지했는지는 보지 않는다)."""
    if key is None:
        return 0
    return _count(session, OutreachMessage, OutreachMessage.direction == "out", OutreachMessage.kind.in_(kinds),
                  OutreachMessage.created_at >= since, _whose(OutreachMessage, key))


def _notices_made(session: Session, since: datetime) -> int:
    """모든 번호 앞으로 since 뒤에 만든 고정 안내 줄 수(고정 안내는 모르는 번호에게만 만든다)."""
    return _count(session, OutreachMessage, OutreachMessage.direction == "out", OutreachMessage.kind == "notice",
                  OutreachMessage.created_at >= since)


def _unknown_calls_taken(session: Session, since: datetime, exclude: int | None) -> int:
    """모르는 번호·번호 숨김 등급의 받는 통화 가운데 since 뒤에 응대한 줄 수(거절·받지 못한 줄은 빼고, 모든 번호를 합쳐)."""
    return _count(session, OutreachCall, OutreachCall.direction == "in", OutreachCall.created_at >= since,
                  OutreachCall.caller_class.in_(sorted(UNKNOWN_CLASSES)), OutreachCall.status.not_in(NOT_TAKEN),
                  exclude=exclude)


def _flat(body: str | None) -> str:
    """견줄 글: 전각·대소문자를 맞추고 이어진 공백을 한 칸으로."""
    if not isinstance(body, str):
        return ""
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", body).casefold()).strip()


def _letters(text: str) -> str:
    """글자·숫자만(빈칸·문장 부호·보이지 않는 글자를 뺀다)."""
    return "".join(ch for ch in text if ch.isalnum())


def is_stop(text: str | None, *, single_words: bool = True) -> bool:
    """수신 거부 말인가 — 들어오는 문자(admit)와 통화 중 상대 말(voice.call_run·after)이 같이 쓰는 규칙 하나. 통신사 머리를 떼고
    **문장마다**(. ? ! 줄 바꿈으로 나눔) 글자만 남겨 본다: (대답 말 STOP_ACKS 하나를 뗀 뒤) STOP_WORD 로 시작하고 나머지가 STOP_ENDINGS 이거나, 문장 전체가
    STOP_PHRASE 이고 글 어디에도 때 말(STOP_TIME_WORDS)이 없으면 수신 거부. 「?」로 끝난 문장은 물음이라 아니다(「수신거부요?」). single_words 면 글 **전체**가 STOP_WHOLE 낱말(「그만」
    「stop」)일 때도 — 통화는 single_words=False(말에서는 「그만」이 너무 자주 나온다)."""
    if not isinstance(text, str):
        return False
    norm = _RELAY_PREFIX.sub("", unicodedata.normalize("NFKC", text).casefold().strip())
    if single_words and _letters(norm) in STOP_WHOLE:
        return True
    timed = any(word in _letters(norm) for word in STOP_TIME_WORDS)
    for sentence, end in _SENTENCE.findall(norm):
        core = _letters(sentence)
        if end == "?" or not core:
            continue
        word = next((core[len(ack):] for ack in STOP_ACKS if core.startswith(ack + STOP_WORD)), core)
        if word.startswith(STOP_WORD) and word[len(STOP_WORD):] in STOP_ENDINGS:
            return True
        if not timed and STOP_PHRASE.fullmatch(core):
            return True
    return False


def _is_machine(flat: str, plain: str, in_book: bool) -> bool:
    """기계가 보낸 글인가. 누가 보냈든: 맨 앞의 (광고) 표지, 인증번호와 4~8자리 숫자뿐인 글. 주소록에 없는 번호의 글은
    더 넓게: 기계 글의 표지가 어디든 있음(통신사 머리 포함), OTP, 주소뿐인 글."""
    if plain.replace(" ", "").startswith(AD_MARK) or _CODE_ONLY.fullmatch(_letters(plain)) is not None:
        return True
    if in_book:
        return False
    squeezed = flat.replace(" ", "")
    return (any(mark in squeezed for mark in MACHINE_MARKS) or _OTP.search(flat) is not None
            or _URL_ONLY.fullmatch(plain) is not None)


def _admit_call(session: Session, key: str | None, caller: Caller, mode: str, limits: outreach.Limits, at: datetime,
                live_calls: int, exclude: int | None) -> tuple[AdmitVerdict, str]:
    cls = caller.caller_class
    since = at - timedelta(minutes=limits.inbound_burst_minutes)
    if _received(session, OutreachCall, key, since, exclude) >= limits.inbound_burst_count:
        return "reject", "burst_limit"  # 4 잦은 전화
    if cls == "do_not_contact" and caller.candidates:
        reason = "do_not_contact"  # 8 보이는 연락처의 수신 거부 번호: 받되 메모만(도구는 등급이 정한다)
    elif cls in KNOWN_CLASSES:
        reason = "known_caller"  # 10
    elif cls in UNKNOWN_CLASSES or cls == "do_not_contact":  # 9 (주소록에 보이지 않는 수신 거부 번호도 이 길)
        if mode != "all":
            return "reject", "unknown_not_accepted"
        if _unknown_calls_taken(session, at - timedelta(hours=1), exclude) >= limits.unknown_calls_hourly:
            return "reject", "burst_limit"  # 모르는 번호 전화 전체의 한 시간 상한
        reason = "unknown_accepted"
    else:
        return "reject", "unknown_not_accepted"  # 등급표 밖의 등급 — 받지 않는다
    if live_calls >= MAX_LIVE_CALLS:
        return "missed", "line_busy"  # 받을 통화였는데 받을 수 없음
    return "engage", reason


def _admit_sms(session: Session, key: str | None, caller: Caller, mode: str, limits: outreach.Limits, at: datetime,
               flat: str, plain: str, in_book: bool, has_media: bool, exclude: int | None) -> tuple[AdmitVerdict, str]:
    cls = caller.caller_class
    since = at - timedelta(minutes=limits.inbound_burst_minutes)
    if _received(session, OutreachMessage, key, since, exclude) >= limits.inbound_burst_count:
        return "record", "burst_limit"  # 4 잦은 문자
    day_start = datetime.combine(at.astimezone(outreach.KST).date(), time(), tzinfo=outreach.KST)  # 「오늘」은 서울 날짜
    if (_replies_made(session, key, at - timedelta(hours=1)) >= limits.auto_reply_hourly
            or _replies_made(session, key, day_start) >= limits.auto_reply_daily):
        return "record", "auto_reply_limit"  # 5 그 번호 앞으로 만든 자동 답이 상한에 닿음
    if _is_machine(flat, plain, in_book) or not (phone.can_sms(key) or in_book):
        return "record", "machine_text"  # 6
    if has_media:
        return "record", "media_attached"  # 7
    if cls == "do_not_contact":
        return "record", "do_not_contact"  # 8 (주소록에 없어도 — 수신 거부 번호에는 안내도 보내지 않는다)
    if cls in KNOWN_CLASSES:
        return "engage", "known_caller"  # 10
    if cls in UNKNOWN_CLASSES and mode == "all":  # 9
        if (_replies_made(session, key, day_start, ("notice",)) >= limits.unknown_notice_daily
                or _notices_made(session, day_start) >= limits.unknown_notice_total_daily):
            return "record", "auto_reply_limit"  # 고정 안내는 그 번호 하루 상한·모르는 번호 전체 하루 상한까지
        return "notice", "unknown_accepted"
    return "record", "unknown_not_accepted"  # 9 (등급표 밖의 등급도 여기)


def admit(session: Session, medium: Medium, number: str | None, *, now: datetime, body: str | None = None,
          has_media: bool = False, live_calls: int = 0, exclude_message_id: int | None = None,
          exclude_call_id: int | None = None) -> Admission:
    """들어온 전화·문자 하나의 받기 판정(위가 이긴다 — 전화 / 문자):

    1 등급 outside_test·blocked → reject / record · 2 문자: 수신 거부 말(표시할 국내 번호가 있을 때) → stop — 받지 않음·
    되풀이 상한보다 먼저 듣는다. 주소록에 없는 번호면 Admission.confirm 이 거짓(확인 문자를 보내지 않는다) · 3 받는 범위가
    「받지 않음」(모르는 값도) → reject / record · 4 잦은 연락: 그 번호에서 **들어온** 통화 줄 / 문자 줄이
    inbound_burst_minutes 분에 inbound_burst_count 개 이상 → reject / record · 5 문자: 그 번호 앞으로 **만든** 자동 답·고정
    안내(초안도)가 auto_reply_hourly·auto_reply_daily 에 닿음 → record · 6 문자: 기계 문자(기계 글, 또는 휴대전화가 아니고
    주소록에도 없는 번호) → record · 7 문자: 사진 → record · 8 do_not_contact → 보이는 연락처일 때 engage(메모만) / record
    · 9 unknown·withheld(전화는 보이는 연락처가 없는 do_not_contact 도) → 받는 범위가 「모두」일 때만 engage(모르는 번호
    전화 전체가 지난 한 시간 unknown_calls_hourly 통에 닿으면 reject) / notice(그 번호 하루 unknown_notice_daily 번·모르는
    번호 전체 하루 unknown_notice_total_daily 번까지, 닿으면 record), 아니면 reject / record · 전화: 받을 통화인데
    live_calls 가 동시 통화 한도 이상 → missed · 10 내부·연락처 등급 → engage.

    문턱은 부를 때마다 store.outreach.limits 에서 읽는다. body 는 2·6 의 글 판정에만 쓴다(등급에는 쓰지 않는다). 시간대
    없는 now 는 UTC 로 본다. **이번 전화·문자의 줄을 먼저 쓰고 부르는 쪽은 그 줄의 id 를 exclude_call_id /
    exclude_message_id 로 넘긴다** — 넘기지 않으면 이번 줄까지 세어 한 번 일찍 닫힌다.
    """
    if medium not in get_args(Medium):
        raise ValueError("medium 은 sms·call 가운데 하나입니다")
    at = as_utc(now)
    caller = resolve(session, number, now=now)
    cls = caller.caller_class
    closed: AdmitVerdict = "reject" if medium == "call" else "record"  # 받지 않을 때: 전화는 거절, 문자는 기록만
    if cls in ("outside_test", "blocked"):
        return Admission(closed, caller, "outside_test" if cls == "outside_test" else "blocked_number")
    key = stored_peer_number(number)
    in_book = bool(caller.candidates) or cls == "internal"
    flat = _flat(body) if medium == "sms" else ""
    plain = _RELAY_PREFIX.sub("", flat)
    if medium == "sms" and is_stop(body) and phone.normalize(key) is not None:
        return Admission("stop", caller, "stop_word", confirm=in_book)
    conn = outreach.connection(session)
    mode = conn.inbound_mode if conn is not None else "off"
    if mode not in ("known", "all"):
        return Admission(closed, caller, "inbound_off")
    limits = outreach.limits(conn)
    if medium == "call":
        verdict, reason = _admit_call(session, key, caller, mode, limits, at, live_calls, exclude_call_id)
    else:
        verdict, reason = _admit_sms(session, key, caller, mode, limits, at, flat, plain, in_book, has_media,
                                     exclude_message_id)
    return Admission(verdict, caller, reason)
