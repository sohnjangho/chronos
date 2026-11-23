"""계획 4 표(Task 61 만 정의한다): 주소록·연락 기록·알림 연결. FK 는 두지 않는다. Base 는 tables.py 것.

app.db 가 import 해서 create_all 전에 Base 에 올린다. 이 표들은 계획 4 전 DB 에는 없어서 create_all 이 만들고,
나중에 더하는 칸은 store.upgrade 가 기존 DB 에 더한다(NULL 가능이거나 글·숫자·참거짓 기본값이 있는 칸만).

일정(schedule_id)은 프로젝트다. 주소록에 없는 번호와 주고받은 줄은 schedule_id·contact_id 가 비고 peer_number 에 번호.
전화번호(phone·peer_number·number·…_number)는 app.outreach.phone.normalize 한 꼴(숫자만, 예 01000000199).
키는 암호문(secret_ciphertext)과 끝 4자리만 둔다. 시각은 UTC(SQLite 는 시간대 없이 저장한다).
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.store.tables import Base


def _now() -> datetime:
    return datetime.now(UTC)


class ContactCompany(Base):
    """협력사 하나(일정마다 따로)."""

    __tablename__ = "contact_companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(100))
    trade: Mapped[str] = mapped_column(String(100), default="")  # 공종
    note: Mapped[str] = mapped_column(Text, default="")
    hidden: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Contact(Base):
    """연락처 한 사람(일정마다 따로). hours_json = {"days": [0..6](월=0), "start": "HH:MM", "end": "HH:MM"},
    None 이면 프로젝트 달력의 기본 근무시간. voice_mode 'auto' 는 성별로 음성을 고른다(voice_id 는 'manual' 일 때)."""

    __tablename__ = "contacts"

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
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


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
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class OutreachMessage(Base):
    """문자·카카오톡 한 건(보낸 것·받은 것). 상태·종류·시작한 쪽 값은 계획 4 이름표.

    idempotency_key 는 메시지마다 고유(주지 않으면 새로 만든다). answers_json·harness_json 은 줄 목록
    (harness_json 한 줄 = 하네스 사건 {rule, verdict, detail, evidence, at}). provider_cost 는 제공사가 알려 준 값만.
    """

    __tablename__ = "outreach_messages"

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
    scheduled_at: Mapped[datetime | None] = mapped_column(default=None)
    sent_at: Mapped[datetime | None] = mapped_column(default=None)
    delivered_at: Mapped[datetime | None] = mapped_column(default=None)
    read_at: Mapped[datetime | None] = mapped_column(default=None)
    last_checked_at: Mapped[datetime | None] = mapped_column(default=None)
    checks: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class OutreachCall(Base):
    """통화 한 통(거는 것·받는 것). transcript_json 한 줄 {role: agent|peer, text, t}(번호는 가려 저장),
    answers_json 한 줄 {question, answer, quote, quote_found}. purpose_key 는 같은 목적의 통화를 묶는 손잡이."""

    __tablename__ = "outreach_calls"

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
    scheduled_at: Mapped[datetime | None] = mapped_column(default=None)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)


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
    reviewed_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class BlockedNumber(Base):
    """차단한 번호 하나(모든 일정)."""

    __tablename__ = "blocked_numbers"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=_now)


class OutreachUsage(Base):
    """연락 기능의 모델·음성 사용 한 번(개발 콘솔 사용량이 읽는다). cost 는 알려 준 값만(계산해 넣지 않는다).
    kind: text_reply | draft | summary | translation | voice_model | transcription | voice_sample. ref_kind: message | call."""

    __tablename__ = "outreach_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(default=_now, index=True)
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
    checked_at: Mapped[datetime | None] = mapped_column(default=None)
    latency_ms: Mapped[int | None] = mapped_column(default=None)
    reply_cursor: Mapped[datetime | None] = mapped_column(default=None)  # 들어온 문자를 여기 뒤 것만 묻는다
    created_at: Mapped[datetime] = mapped_column(default=_now)


class KakaoTemplate(Base):
    """알림톡 문안 하나(제공사에서 맞춰 옴). status: approved | reviewing | rejected | dormant."""

    __tablename__ = "kakao_templates"

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
    synced_at: Mapped[datetime] = mapped_column(default=_now)


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
    status: Mapped[str] = mapped_column(String(10), default="unknown")
    checked_at: Mapped[datetime | None] = mapped_column(default=None)
