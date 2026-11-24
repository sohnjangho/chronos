"""계획 4 표(Task 61 만 정의한다): 주소록·연락 기록·알림 연결. FK 는 두지 않는다. Base 는 tables.py 것.

app.db 가 import 해서 create_all 전에 Base 에 올린다. 이 표들은 계획 4 전 DB 에는 없어서 create_all 이 만들고,
나중에 더하는 칸은 store.upgrade 가 기존 DB 에 더한다(NULL 가능이거나 글·숫자·참거짓 기본값이 있는 칸만).
id 를 FK 없이 다른 곳에 적는 표(협력사·연락처·메시지·통화·알림 연결·알림톡 문안)는 sqlite_autoincrement — 지운 뒤에도 같은
id 를 다시 쓰지 않는다(SQLite 는 가장 큰 id 를 지우면 그 id 를 다시 준다). 이미 만들어진 표에는 ALTER 로 더할 수 없다.
시각 칸은 모두 UtcDateTime: 시간대가 붙은 값(예: KST)은 같은 순간의 UTC 로 바꿔 저장한다. 읽으면 다른 표와 같이
시간대 없는 UTC 값이다(내보낼 때 app.store.timeutil.as_utc 로 UTC 를 붙인다).

일정(schedule_id)은 프로젝트다. 주소록에 없는 번호와 주고받은 줄은 schedule_id·contact_id 가 비고 peer_number 에 번호.
전화번호(phone·peer_number·number·…_number)는 app.outreach.phone.normalize 한 꼴(숫자만, 예 01000000199).
키는 암호문(secret_ciphertext)과 끝 4자리만 둔다. 시각은 UTC(SQLite 는 시간대 없이 저장한다).
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Dialect, Index, String, Text, TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column

from app.store.tables import Base
from app.store.timeutil import as_utc


class UtcDateTime(TypeDecorator):
    """시각 칸. 넣을 때 시간대가 있으면 UTC 로 바꾸고, 없으면 UTC 로 본다 — 어느 시간대로 넣어도 같은 순간이 같은 값.
    읽으면 시간대 없는 UTC(SQLite 규칙, 다른 표와 같음)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else as_utc(value).replace(tzinfo=None)


# id 를 FK 없이 다른 곳에 적는 표: 지운 뒤에도 같은 id 를 다시 쓰지 않는다(SQLite AUTOINCREMENT)
_NO_ID_REUSE = {"sqlite_autoincrement": True}


def _now() -> datetime:
    return datetime.now(UTC)


def new_person_key() -> str:
    """같은 사람의 연락처 줄(프로젝트마다 하나)을 잇는 열쇠 — 새 줄마다 새 값(11-24)."""
    return uuid4().hex


class ContactCompany(Base):
    """협력사 하나(일정마다 따로)."""

    __tablename__ = "contact_companies"
    __table_args__ = _NO_ID_REUSE

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(100))
    trade: Mapped[str] = mapped_column(String(100), default="")  # 공종
    note: Mapped[str] = mapped_column(Text, default="")
    hidden: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class Contact(Base):
    """연락처 한 사람(일정마다 따로). hours_json = {"days": [0..6](월=0), "start": "HH:MM", "end": "HH:MM"},
    None 이면 프로젝트 달력의 기본 근무시간. voice_mode 'auto' 는 성별로 음성을 고른다(voice_id 는 'manual' 일 때)."""

    __tablename__ = "contacts"
    __table_args__ = _NO_ID_REUSE

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(index=True)
    company_id: Mapped[int]
    name: Mapped[str] = mapped_column(String(100))
    role_title: Mapped[str] = mapped_column(String(100), default="")  # 담당
    phone: Mapped[str | None] = mapped_column(String(20), default=None, index=True)
    can_sms: Mapped[bool] = mapped_column(default=True)
    can_kakao: Mapped[bool] = mapped_column(default=True)
    can_call: Mapped[bool] = mapped_column(default=True)
    hours_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    gender: Mapped[str] = mapped_column(String(10), default="unknown")  # male | female | unknown
    language: Mapped[str] = mapped_column(String(10), default="ko")
    voice_mode: Mapped[str] = mapped_column(String(10), default="auto")  # auto | manual
    voice_id: Mapped[str | None] = mapped_column(String(100), default=None)
    do_not_contact: Mapped[bool] = mapped_column(default=False)  # 수신 거부
    dnc_reason: Mapped[str | None] = mapped_column(String(200), default=None)
    phone_invalid: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    hidden: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, onupdate=_now)
    # 관리자 등급(11-24): trade = 자기 협력사·공종의 일정만, manager = 등록된 프로젝트의 모든 협력사 일정(관리자만 바꾼다 —
    # contact_access_changes 에 기록). 기존 DB 에는 store.upgrade 가 DEFAULT 'trade' 로 더한다.
    access_level: Mapped[str] = mapped_column(String(10), default="trade")
    # 같은 사람의 줄(프로젝트마다 하나)을 잇는 열쇠(11-24). 새 줄은 새 값, 기존 DB 의 옛 줄은 NULL(혼자인 사람).
    # 이름·번호·성별·언어·음성·채널·수신 거부·등급은 같은 열쇠의 줄에 함께 저장된다(programs.contacts.links).
    person_key: Mapped[str | None] = mapped_column(String(32), default=new_person_key)


class ContactAccessChange(Base):
    """관리자 등급을 정하거나 바꾼 기록 한 줄(11-24 — 감사: 누가 언제 어느 일정·연락처의 등급을 무엇에서 무엇으로).
    before 는 새 줄이면 NULL. 번호는 두지 않는다. 일정을 지워도 남는다."""

    __tablename__ = "contact_access_changes"
    __table_args__ = _NO_ID_REUSE

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(index=True)
    contact_id: Mapped[int]
    user_id: Mapped[int]
    login_id: Mapped[str | None] = mapped_column(String(50), default=None)
    before: Mapped[str | None] = mapped_column(String(10), default=None)
    after: Mapped[str] = mapped_column(String(10))
    at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class ContactProposal(Base):
    """통화·문자에서 받은 새 연락처(kind 'new') 또는 언어 바꿈(kind 'language') 제안. 사람이 승인해야 주소록에 든다.
    status: pending | accepted | rejected. 받은 번호는 이 줄의 phone 에만 둔다."""

    __tablename__ = "contact_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int | None] = mapped_column(default=None, index=True)
    call_id: Mapped[int | None] = mapped_column(default=None)
    message_id: Mapped[int | None] = mapped_column(default=None)
    kind: Mapped[str] = mapped_column(String(10))
    contact_id: Mapped[int | None] = mapped_column(default=None)
    name: Mapped[str] = mapped_column(String(100), default="")
    role_title: Mapped[str] = mapped_column(String(100), default="")
    company_name: Mapped[str] = mapped_column(String(100), default="")
    phone: Mapped[str | None] = mapped_column(String(20), default=None)
    language: Mapped[str | None] = mapped_column(String(10), default=None)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(100), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class OutreachMessage(Base):
    """문자·카카오톡 한 건(보낸 것·받은 것). 상태·종류·시작한 쪽 값은 계획 4 이름표.

    idempotency_key 는 메시지마다 고유(주지 않으면 새로 만든다). answers_json·harness_json 은 줄 목록
    (harness_json 한 줄 = 하네스 사건 {rule, verdict, detail, evidence, at}). provider_cost 는 제공사가 알려 준 값만.
    """

    __tablename__ = "outreach_messages"
    __table_args__ = _NO_ID_REUSE

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int | None] = mapped_column(default=None, index=True)
    contact_id: Mapped[int | None] = mapped_column(default=None, index=True)
    peer_number: Mapped[str | None] = mapped_column(String(20), default=None, index=True)
    caller_class: Mapped[str | None] = mapped_column(String(20), default=None)
    direction: Mapped[str] = mapped_column(String(5))  # out | in
    channel: Mapped[str] = mapped_column(String(10))  # sms | kakao
    kind: Mapped[str] = mapped_column(String(20), default="normal")  # normal | auto_reply | notice | dnc_confirm
    body: Mapped[str] = mapped_column(Text, default="")
    body_ko: Mapped[str | None] = mapped_column(Text, default=None)
    has_media: Mapped[bool] = mapped_column(default=False)
    template_id: Mapped[int | None] = mapped_column(default=None)
    template_vars_json: Mapped[dict] = mapped_column(JSON, default=dict)
    origin: Mapped[str] = mapped_column(String(10))  # user | agent | peer
    origin_name: Mapped[str] = mapped_column(String(100), default="")
    send_mode: Mapped[str | None] = mapped_column(String(10), default=None)  # manual | approved | delegated
    approved_by: Mapped[str | None] = mapped_column(String(100), default=None)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    fail_reason: Mapped[str | None] = mapped_column(String(200), default=None)
    fallback_sms: Mapped[bool] = mapped_column(default=False)
    length_kind: Mapped[str | None] = mapped_column(String(10), default=None)  # sms | long
    provider_cost: Mapped[float | None] = mapped_column(default=None)
    provider_message_id: Mapped[str | None] = mapped_column(String(100), default=None, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: uuid4().hex)
    reply_to_id: Mapped[int | None] = mapped_column(default=None)
    answers_json: Mapped[list] = mapped_column(JSON, default=list)
    harness_json: Mapped[list] = mapped_column(JSON, default=list)
    activity_id: Mapped[str | None] = mapped_column(String(50), default=None)
    field_item_id: Mapped[int | None] = mapped_column(default=None)
    approval_id: Mapped[int | None] = mapped_column(default=None)
    chat_session_id: Mapped[int | None] = mapped_column(default=None)
    call_id: Mapped[int | None] = mapped_column(default=None)
    batch_id: Mapped[int | None] = mapped_column(default=None, index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    claimed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)  # 나가려고 차지한 때(store.outreach.claim)
    sent_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    delivered_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    read_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    last_checked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    checks: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class OutreachCall(Base):
    """통화 한 통(거는 것·받는 것). transcript_json 한 줄 {role: agent|peer, text, t}(번호는 가려 저장),
    answers_json 한 줄 {question, answer, quote, quote_found}. purpose_key 는 같은 목적의 통화를 묶는 손잡이."""

    __tablename__ = "outreach_calls"
    __table_args__ = _NO_ID_REUSE

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int | None] = mapped_column(default=None, index=True)
    contact_id: Mapped[int | None] = mapped_column(default=None, index=True)
    peer_number: Mapped[str | None] = mapped_column(String(20), default=None, index=True)
    caller_class: Mapped[str | None] = mapped_column(String(20), default=None)
    direction: Mapped[str] = mapped_column(String(5), default="out")  # out | in
    purpose: Mapped[str] = mapped_column(Text, default="")
    questions_json: Mapped[list] = mapped_column(JSON, default=list)
    avoid_json: Mapped[list] = mapped_column(JSON, default=list)
    language: Mapped[str] = mapped_column(String(10), default="ko")
    voice_id: Mapped[str | None] = mapped_column(String(100), default=None)
    origin: Mapped[str] = mapped_column(String(10))  # user | agent | peer
    origin_name: Mapped[str] = mapped_column(String(100), default="")
    send_mode: Mapped[str | None] = mapped_column(String(10), default=None)
    approved_by: Mapped[str | None] = mapped_column(String(100), default=None)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    fail_reason: Mapped[str | None] = mapped_column(String(200), default=None)
    duration_s: Mapped[int | None] = mapped_column(default=None)
    transcript_json: Mapped[list] = mapped_column(JSON, default=list)
    summary_ko: Mapped[str] = mapped_column(Text, default="")
    answers_json: Mapped[list] = mapped_column(JSON, default=list)
    result_proposed: Mapped[str] = mapped_column(Text, default="")
    result_confirmed: Mapped[str | None] = mapped_column(Text, default=None)
    confirmed_by: Mapped[str | None] = mapped_column(String(100), default=None)
    harness_json: Mapped[list] = mapped_column(JSON, default=list)
    prev_call_id: Mapped[int | None] = mapped_column(default=None)
    retry_of: Mapped[int | None] = mapped_column(default=None)
    auto_retry_used: Mapped[bool] = mapped_column(default=False)
    purpose_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    provider_call_id: Mapped[str | None] = mapped_column(String(100), default=None)
    provider_cost: Mapped[float | None] = mapped_column(default=None)
    recording_path: Mapped[str | None] = mapped_column(String(500), default=None)
    activity_id: Mapped[str | None] = mapped_column(String(50), default=None)
    field_item_id: Mapped[int | None] = mapped_column(default=None)
    approval_id: Mapped[int | None] = mapped_column(default=None)
    chat_session_id: Mapped[int | None] = mapped_column(default=None)
    scheduled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    claimed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)  # 줄에 넣은 때(store.outreach.claim)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class ContactReport(Base):
    """「전화로 받은 보고」·「문자로 받은 보고」·메모·긴급 알림 한 줄. medium: sms | call.
    kind: delay | problem | change_request | message | emergency | review | other. status: open | reviewed."""

    __tablename__ = "contact_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int | None] = mapped_column(default=None, index=True)
    medium: Mapped[str] = mapped_column(String(10))
    call_id: Mapped[int | None] = mapped_column(default=None)
    message_id: Mapped[int | None] = mapped_column(default=None)
    contact_id: Mapped[int | None] = mapped_column(default=None)
    kind: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text, default="")
    quote: Mapped[str] = mapped_column(Text, default="")
    quote_found: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(10), default="open")
    reviewed_by: Mapped[str | None] = mapped_column(String(100), default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class BlockedNumber(Base):
    """관리자가 차단한 번호 하나(모든 일정). 걸려 오는 전화·문자를 받지 않고 거절한다. 수신 거부와는 다르다."""

    __tablename__ = "blocked_numbers"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class DoNotContactNumber(Base):
    """수신 거부한 번호 하나(PM 11-23: 수신 거부는 번호 기준 전체 — 일정을 지워도 남는다). 받는 사람이 연락하지 말라고 한 것이라
    우리가 보내거나 걸지 않을 뿐, 그 번호가 걸어 오거나 보내 오면 메모는 남길 수 있다(차단 blocked_numbers 와 다름).
    판단은 store.outreach.is_do_not_contact 로만 한다(연락처 줄의 do_not_contact 표시와 함께 본다)."""

    __tablename__ = "do_not_contact_numbers"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class ContactReveal(Base):
    """전체 번호를 본 기록 한 줄(Task 72 — 감사: 누가 언제 어느 일정·연락처의 번호를 봤나). 번호는 어떤 꼴로도(가린 꼴도)
    두지 않는다. 일정을 지워도 남는다(purge_schedule 이 지우지 않음). 번호 보기 상한(사용자마다 10분에 30번)도 이 표로 센다
    — store.contact_reveals.record_reveal·count_reveals. login_id 는 그때의 로그인 id: 사용자를 지우면 users 의 id 가 다시
    쓰일 수 있어 user_id 만으로는 누군지 남지 않는다(이 칸 전에 남은 줄은 비어 있다)."""

    __tablename__ = "contact_reveals"
    __table_args__ = (Index("ix_contact_reveals_user_at", "user_id", "at"), _NO_ID_REUSE)

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(index=True)
    contact_id: Mapped[int]
    user_id: Mapped[int]
    login_id: Mapped[str | None] = mapped_column(String(50), default=None)
    at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class OutreachUsage(Base):
    """연락 기능의 모델·음성 사용 한 번(개발 콘솔 사용량이 읽는다). cost 는 알려 준 값만(계산해 넣지 않는다).
    kind: text_reply | draft | summary | translation | voice_model | transcription | voice_sample. ref_kind: message | call."""

    __tablename__ = "outreach_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, index=True)
    kind: Mapped[str] = mapped_column(String(20))
    ref_kind: Mapped[str | None] = mapped_column(String(10), default=None)
    ref_id: Mapped[int | None] = mapped_column(default=None)
    model: Mapped[str | None] = mapped_column(String(200), default=None)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    seconds: Mapped[int | None] = mapped_column(default=None)
    cost: Mapped[float | None] = mapped_column(default=None)


class NotifyConnection(Base):
    """알림 연결(한국AI통신). 키는 암호문과 끝 4자리만. 권한(agent_*): approve | delegate. inbound_mode: off | known | all.

    한도(하루·사람당·통화 길이·자동 답·되풀이 …)는 limits_json 에 바꾼 값만 두고 store.outreach.limits 로만 읽는다
    (PM 11-23: 설정·개발 콘솔에서 바꾼다). None 이면 모두 기본값.
    """

    __tablename__ = "notify_connections"
    __table_args__ = _NO_ID_REUSE

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(30), default="koreaaitel")
    base_url: Mapped[str] = mapped_column(String(500))
    secret_ciphertext: Mapped[str] = mapped_column(Text)
    secret_last4: Mapped[str] = mapped_column(String(4))
    account_id: Mapped[str] = mapped_column(String(100))
    sender_number: Mapped[str | None] = mapped_column(String(20), default=None)
    senders_json: Mapped[list] = mapped_column(JSON, default=list)
    kakao_channels_json: Mapped[list] = mapped_column(JSON, default=list)
    kakao_channel: Mapped[str | None] = mapped_column(String(100), default=None)
    test_mode: Mapped[bool] = mapped_column(default=True)
    allow_numbers_json: Mapped[list] = mapped_column(JSON, default=list)
    limits_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    agent_sms: Mapped[str] = mapped_column(String(10), default="approve")
    agent_kakao: Mapped[str] = mapped_column(String(10), default="approve")
    agent_call: Mapped[str] = mapped_column(String(10), default="approve")
    inbound_mode: Mapped[str] = mapped_column(String(10), default="off")
    handoff_number: Mapped[str | None] = mapped_column(String(20), default=None)
    is_default: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(10), default="unknown")  # ok | failed | unknown
    checked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    latency_ms: Mapped[int | None] = mapped_column(default=None)
    reply_cursor: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)  # 들어온 문자를 여기 뒤 것만 묻는다
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    # 마지막 연결 진단 {ran_at, steps: [DiagnosticStep 을 dict 로], real: bool}(Task 112, NULL 이면 아직 안 돌림).
    # 가린 글만 — masked text only, no key, no number(걸음의 detail·notes 는 진단 함수의 scrub 을 거친 것).
    last_diagnosis_json: Mapped[dict | None] = mapped_column(
        JSON, default=None, comment="masked text only, no key, no number"
    )


class KakaoTemplate(Base):
    """알림톡 문안 하나(제공사에서 맞춰 옴). status: approved | reviewing | rejected | dormant."""

    __tablename__ = "kakao_templates"
    __table_args__ = _NO_ID_REUSE

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(index=True)
    channel: Mapped[str] = mapped_column(String(100))
    provider_template_id: Mapped[str] = mapped_column(String(100))
    use: Mapped[str | None] = mapped_column(String(50), default=None)
    body: Mapped[str] = mapped_column(Text, default="")
    variables_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(10))
    reply_line: Mapped[bool] = mapped_column(default=False)
    fallback_body: Mapped[str | None] = mapped_column(Text, default=None)
    synced_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class VoiceSettings(Base):
    """알림 연결에 딸린 음성 설정. provider: google | openai | dashboard. 키는 암호문과 끝 4자리만.
    voice_male_contact = 남성 연락처에게 걸 때 쓰는 음성. 최대 통화 시간은 여기 두지 않고 알림 연결의 한도(limits)."""

    __tablename__ = "voice_settings"

    connection_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    provider: Mapped[str] = mapped_column(String(10), default="google")
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, default=None)
    secret_last4: Mapped[str] = mapped_column(String(4), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    voice_male_contact: Mapped[str | None] = mapped_column(String(100), default=None)
    voice_female_contact: Mapped[str | None] = mapped_column(String(100), default=None)
    voice_unknown: Mapped[str | None] = mapped_column(String(100), default=None)
    voices_by_language_json: Mapped[dict] = mapped_column(JSON, default=dict)
    dashboard_agent_id: Mapped[str | None] = mapped_column(String(100), default=None)
    # AI 전화 번호 — 플랫폼에서 받은, 음성 에이전트에 묶는 번호(문자 발신번호와 다를 수 있다). 정리한 숫자 꼴(Task 90).
    agent_number: Mapped[str | None] = mapped_column(String(20), default=None)
    status: Mapped[str] = mapped_column(String(10), default="unknown")
    checked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    # 마지막 음성 진단 {ran_at, steps: [DiagnosticStep 을 dict 로], real: bool}(Task 112, NULL 이면 아직 안 돌림).
    # 가린 글만 — masked text only, no key, no number(걸음의 detail·notes 는 진단 함수의 scrub 을 거친 것).
    last_diagnosis_json: Mapped[dict | None] = mapped_column(
        JSON, default=None, comment="masked text only, no key, no number"
    )
