"""알림 연결 저장·연결 테스트·상한·상태(계획 4 Task 70). 계약: .superpowers/sdd/2026-11-23-chronos-plan-4-contacts/task-70-contract.md.

- 평문 키는 요청을 처리하는 동안에만 쓰고 저장은 암호문으로만 한다. 기록(log)은 남기지 않는다.
- 키·Account ID 를 풀어 쓰기 전에 `provider.register_secrets`. 바꾸거나 지울 때 옛 값은 **다른 연결이 쓰지 않을 때만**
  `redact.drop_secrets`.
- 제공사는 `provider.client_for(row)` 로만 부른다(모듈 속성 — 시험이 바꿔 끼운다). 부르기 전에 commit 해 트랜잭션을 쥐지 않고,
  부른 뒤 줄을 다시 읽어 쓴다. 연결 테스트 전체에 상한 CHECK_CEILING_S.
- 번호는 `phone.normalize` 꼴로 저장하고 가린 꼴로만 내보낸다. 오류에 보낸 값을 싣지 않는다.
- 상한 검사는 `store.outreach.validate_limits` 하나로만 한다.
"""

import asyncio
import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import ApiError
from app.notify import diagnostics
from app.outreach import phone, provider, redact
from app.outreach.provider import ProviderFailed
from app.programs.notify_settings.schemas import (
    AgentOut,
    AllowNumberOut,
    ConnectionCreate,
    ConnectionOut,
    ConnectionTestIn,
    ConnectionUpdate,
    ErrorOut,
    LimitsOut,
    ProbeOut,
    StatusOut,
    UsedToday,
)
from app.security import crypto
from app.store import outreach, outreach_usage
from app.store.tables_outreach import (
    KakaoTemplate,
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
    VoiceSettings,
)

CHECK_CEILING_S = 30.0  # 연결 테스트 한 번의 전체 시간(제공사 호출 자체의 15초 제한 위에 한 번 더)
MAX_SECRET_CHARS = 500
OVERSEAS = "나라 밖 IP 에서는 보낼 수 없습니다. 이 서버가 나가는 IP 가 한국 밖으로 보입니다."
TIMEOUT = "제공사 응답이 시간 안에 오지 않았습니다."
UNKNOWN = "제공사 응답을 읽지 못했습니다."
NO_USE = UsedToday(sms=0, call=0)


@dataclass(frozen=True)
class Probe:
    """연결 테스트 결과. senders 는 정리한 번호(저장용) — 내보낼 때 가린다."""

    ok: bool
    latency_ms: int | None
    senders: list[str]
    error: ErrorOut | None


# ── 입력 ──────────────────────────────────────────────────────────


def _usable(value: str) -> bool:
    """진단·제공사 호출이 받는 꼴(ASCII·찍을 수 있는 글자·8자 이상)에 빈칸도 없음."""
    return diagnostics.MIN_SECRET <= len(value) <= MAX_SECRET_CHARS and value.isascii() and value.isprintable() \
        and " " not in value


def secret_value(secret: SecretStr) -> str:
    value = secret.get_secret_value().strip()
    if not _usable(value):
        raise ApiError(422, "invalid_secret", "API 키는 8자 이상이고 공백·줄바꿈 같은 글자가 없어야 합니다.")
    return value


def account_value(raw: str) -> str:
    value = raw.strip()
    if not _usable(value):
        raise ApiError(422, "invalid_account_id", "Account ID 는 8자 이상이고 공백·줄바꿈 같은 글자가 없어야 합니다.")
    return value


def base_url_value(raw: str | None) -> str:
    value = (raw or "").strip() or diagnostics.DEFAULT_BASE_URL
    problem = diagnostics.base_url_problem(value)
    if problem:
        raise ApiError(422, "bad_base_url", problem)
    return value.rstrip("/")


def _bad_number(field: str, index: int | None = None) -> ApiError:
    detail = {"field": field} if index is None else {"field": field, "index": index}
    return ApiError(422, "invalid_number", "번호 형식이 올바르지 않거나 쓸 수 없는 번호입니다.", detail)


def _bad_index(field: str) -> ApiError:
    return ApiError(422, "invalid_index", "목록에 없는 순번입니다.", {"field": field})


def get(session: Session, conn_id: int) -> NotifyConnection:
    conn = session.get(NotifyConnection, conn_id)
    if conn is None:
        raise ApiError(404, "connection_not_found", "알림 연결을 찾을 수 없습니다.")
    return conn


def stored_key(conn: NotifyConnection) -> str:
    try:
        return crypto.decrypt(conn.secret_ciphertext)
    except crypto.SecretUnreadable:
        raise ApiError(409, "secret_unreadable", "저장된 키를 읽을 수 없습니다. 키를 다시 넣어 주세요.") from None


def _key_or_none(conn: NotifyConnection) -> str | None:
    try:
        return crypto.decrypt(conn.secret_ciphertext)
    except crypto.SecretUnreadable:
        return None


def _drop_unused(session: Session, values: list[str | None]) -> None:
    """옛 키·Account ID 를 로그 거르개에서 뺀다 — 남은 연결 가운데 같은 값을 쓰는 것이 없을 때만."""
    old = [v for v in values if v]
    if not old:
        return
    in_use: set[str] = set()
    for row in session.scalars(select(NotifyConnection)):
        in_use.update(v for v in (row.account_id, _key_or_none(row)) if v)
    redact.drop_secrets(*[v for v in old if v not in in_use])


# ── 연결 테스트 ─────────────────────────────────────────────────────


def _draft(base_url: str, account_id: str, key: str) -> NotifyConnection:
    """제공사 클라이언트를 만들 값만 담은 줄(세션에 넣지 않는다) — 부르는 동안 DB 줄을 붙들지 않게."""
    return NotifyConnection(base_url=base_url, account_id=account_id, secret_ciphertext=crypto.encrypt(key))


async def _probe(row: NotifyConnection, secrets: list[str]) -> Probe:
    """`provider.check()` 한 번. 실패는 모두 Probe(ok=False) — 글에 키·Account ID·번호 없음."""
    try:
        async with asyncio.timeout(CHECK_CEILING_S):
            check = await provider.client_for(row).check()
    except ProviderFailed as exc:
        message = OVERSEAS if exc.code == "overseas_ip" else redact.scrub(exc.message, secrets)
        return Probe(False, None, [], ErrorOut(code=exc.code, message=message))
    except TimeoutError:
        return Probe(False, None, [], ErrorOut(code="timeout", message=TIMEOUT))
    except Exception:  # noqa: BLE001 — 어떤 실패든 「읽지 못함」으로(예외 글에 무엇이 섞였는지 모른다)
        return Probe(False, None, [], ErrorOut(code="unknown", message=UNKNOWN))
    return Probe(True, check.latency_ms, list(check.senders), None)


def probe_out(result: Probe) -> ProbeOut:
    return ProbeOut(ok=result.ok, latency_ms=result.latency_ms, senders=[phone.mask(s) for s in result.senders],
                    error=result.error)


def _record(conn: NotifyConnection, result: Probe) -> None:
    """시험 결과를 줄에 적는다. 발신번호 목록은 성공했을 때만 바꾸고, 고른 번호가 사라졌으면 남은 첫 번호로."""
    conn.status = "ok" if result.ok else "failed"
    conn.checked_at = datetime.now(UTC)
    conn.latency_ms = result.latency_ms
    if result.ok:
        conn.senders_json = list(result.senders)
        if conn.sender_number not in result.senders:
            conn.sender_number = result.senders[0] if result.senders else None


async def test_new(data: ConnectionTestIn) -> Probe:
    key, account, base = secret_value(data.secret), account_value(data.account_id), base_url_value(data.base_url)
    provider.register_secrets(key, account)
    return await _probe(_draft(base, account, key), [key, account])


async def create(session: Session, data: ConnectionCreate) -> tuple[NotifyConnection, Probe]:
    """연결 테스트를 한 번 하고 저장한다(실패해도 status 'failed' 로 저장). 기본값은 안전한 쪽."""
    key, account, base = secret_value(data.secret), account_value(data.account_id), base_url_value(data.base_url)
    provider.register_secrets(key, account)
    session.commit()  # 트랜잭션을 놓고 부른다
    result = await _probe(_draft(base, account, key), [key, account])
    conn = NotifyConnection(
        name=data.name, base_url=base, secret_ciphertext=crypto.encrypt(key), secret_last4=key[-4:],
        account_id=account, senders_json=[], kakao_channels_json=[], allow_numbers_json=[], test_mode=True,
        agent_sms="approve", agent_kakao="approve", agent_call="approve", inbound_mode="off",
        is_default=outreach.connection(session) is None,
    )
    _record(conn, result)
    session.add(conn)
    session.commit()
    return conn, result


async def retest(session: Session, conn_id: int) -> Probe:
    conn = get(session, conn_id)
    key, account, base = stored_key(conn), conn.account_id, conn.base_url
    provider.register_secrets(key, account)
    session.commit()
    result = await _probe(_draft(base, account, key), [key, account])
    _record(get(session, conn_id), result)
    session.commit()
    return result


# ── 고치기 ──────────────────────────────────────────────────────────


def allow_version(conn: NotifyConnection) -> str:
    """허용 번호 목록의 판 — 지울 때 「본 목록 그대로인가」를 본다. 번호로 되돌릴 수 없다(secret_key HMAC)."""
    text = f"allow:{conn.id}:" + json.dumps(list(conn.allow_numbers_json or []))
    return hmac.new(Settings().secret_key.encode(), text.encode(), hashlib.sha256).hexdigest()[:24]


def _allow_list(conn: NotifyConnection, data: ConnectionUpdate) -> list[str] | None:
    if data.allow_numbers_remove is None and data.allow_numbers_add is None:
        return None
    current = list(conn.allow_numbers_json or [])
    if data.allow_numbers_remove:
        if data.allow_numbers_version is None:
            raise ApiError(422, "allow_version_required",
                           "허용 번호를 지우려면 목록 판(allow_numbers_version)을 함께 보내 주세요.")
        if not hmac.compare_digest(data.allow_numbers_version, allow_version(conn)):
            raise ApiError(409, "allow_list_changed", "허용 번호 목록이 그사이 바뀌었습니다. 새로 불러온 뒤 다시 지워 주세요.")
        if any(not 0 <= i < len(current) for i in data.allow_numbers_remove):
            raise _bad_index("allow_numbers_remove")
        drop = set(data.allow_numbers_remove)
        current = [n for i, n in enumerate(current) if i not in drop]
    for i, raw in enumerate(data.allow_numbers_add or []):
        number = phone.normalize(raw)
        if number is None or not phone.can_call(number):
            raise _bad_number("allow_numbers_add", i)
        if number not in current:
            current.append(number)
    return current


def _changes(conn: NotifyConnection, data: ConnectionUpdate) -> dict:
    """고칠 칸 {칸: 값}. 틀린 입력은 여기서 ApiError(아무것도 바꾸기 전)."""
    sent = data.model_fields_set
    changes: dict = {}
    for field in ("name", "test_mode", "agent_sms", "agent_call", "agent_kakao", "inbound_mode"):
        if getattr(data, field) is not None:
            changes[field] = getattr(data, field)
    if "kakao_channel" in sent:
        changes["kakao_channel"] = None  # 글은 _refuse_kakao 가 이미 막았다
    if data.sender_index is not None:
        senders = list(conn.senders_json or [])
        if not 0 <= data.sender_index < len(senders):
            raise _bad_index("sender_index")
        changes["sender_number"] = senders[data.sender_index]
    if "handoff_number" in sent:
        raw = (data.handoff_number or "").strip()
        number = phone.normalize(raw) if raw else None
        if raw and (number is None or not phone.can_call(number)):
            raise _bad_number("handoff_number")
        changes["handoff_number"] = number
    allow = _allow_list(conn, data)
    if allow is not None:
        changes["allow_numbers_json"] = allow
    return changes


def _refuse_kakao(data: ConnectionUpdate) -> None:
    if data.agent_kakao == "delegate" or data.kakao_channel is not None:
        raise ApiError(422, "kakao_not_ready", "카카오톡(알림톡)은 아직 쓸 수 없습니다.")


def _make_default(session: Session, conn: NotifyConnection) -> None:
    for other in session.scalars(select(NotifyConnection).where(NotifyConnection.is_default)):
        other.is_default = False
    conn.is_default = True


async def update(session: Session, conn_id: int, data: ConnectionUpdate) -> tuple[NotifyConnection, Probe | None]:
    """보낸 칸만 고친다. 주소·키·Account ID 가 바뀌면 연결 테스트를 한 번 다시 한다(그때만 결과가 있다)."""
    conn = get(session, conn_id)
    _refuse_kakao(data)
    new_key = secret_value(data.secret) if data.secret is not None else None
    if data.base_url is not None and new_key is None:
        raise ApiError(422, "secret_required", "주소를 바꾸면 API 키를 다시 넣어 주세요.")
    base = base_url_value(data.base_url) if data.base_url is not None else conn.base_url
    account = account_value(data.account_id) if data.account_id is not None else conn.account_id
    _changes(conn, data)  # 부르기 전에 입력을 모두 검사한다
    result = None
    old = [_key_or_none(conn), conn.account_id]
    if new_key is not None or account != conn.account_id:
        key = new_key if new_key is not None else stored_key(conn)
        provider.register_secrets(key, account)
        session.commit()  # 트랜잭션을 놓고 부른다
        result = await _probe(_draft(base, account, key), [key, account])
        conn = get(session, conn_id)  # 부르는 사이 다른 요청이 고친 칸을 덮지 않게 다시 읽는다
        conn.secret_ciphertext, conn.secret_last4 = crypto.encrypt(key), key[-4:]
        conn.base_url, conn.account_id = base, account
        _record(conn, result)
    for field, value in _changes(conn, data).items():  # 다시 읽은 줄에 맞춰 다시 검사·적용
        setattr(conn, field, value)
    if data.is_default:
        _make_default(session, conn)
    session.commit()
    if result is not None:
        _drop_unused(session, old)
    return conn, result


def delete_connection(session: Session, conn_id: int) -> None:
    """지운다. 기본(또는 하나뿐인) 연결은 연락 기록이 있으면 409 — 기록 줄에 연결 id 가 없고 기본 연결로 나가므로.
    딸린 카카오 문안·음성 설정도 지우고, 기본이었으면 가장 오래된 남은 연결이 기본이 된다."""
    conn = get(session, conn_id)
    others = list(session.scalars(select(NotifyConnection).where(NotifyConnection.id != conn_id)
                                  .order_by(NotifyConnection.id)))
    if (conn.is_default or not others) and _has_history(session):
        raise ApiError(409, "has_history", "연락 기록이 있어 지울 수 없습니다")
    old = [_key_or_none(conn), conn.account_id]
    was_default = conn.is_default
    session.execute(delete(KakaoTemplate).where(KakaoTemplate.connection_id == conn_id))
    session.execute(delete(VoiceSettings).where(VoiceSettings.connection_id == conn_id))
    session.delete(conn)
    session.flush()
    if was_default and others and not any(o.is_default for o in others):
        others[0].is_default = True
    session.commit()
    _drop_unused(session, old)


def _has_history(session: Session) -> bool:
    return any(session.scalar(select(model.id).limit(1)) is not None for model in (OutreachMessage, OutreachCall))


# ── 보이기 ──────────────────────────────────────────────────────────


def used_today(session: Session) -> UsedToday:
    today = outreach_usage.summary(session, days=1)
    return UsedToday(sms=today.sms, call=today.calls_placed)


def _masked(number: str | None) -> str | None:
    return phone.mask(number) if number else None


def out(conn: NotifyConnection, used: UsedToday) -> ConnectionOut:
    senders = list(conn.senders_json or [])
    allow = list(conn.allow_numbers_json or [])
    test_index = 0 if allow and phone.can_sms(allow[0]) and conn.sender_number else None
    account = conn.account_id or ""
    return ConnectionOut(
        id=conn.id, name=conn.name, provider=conn.provider, base_url=conn.base_url, secret_last4=conn.secret_last4,
        account_id_masked="…" + (account[-4:] if len(account) >= diagnostics.MIN_SECRET else ""),
        sender_number_masked=_masked(conn.sender_number),
        sender_index=senders.index(conn.sender_number) if conn.sender_number in senders else None,
        senders=[phone.mask(s) for s in senders], kakao_channel=conn.kakao_channel, test_mode=conn.test_mode,
        allow_numbers=[AllowNumberOut(index=i, number_masked=phone.mask(n), kind=phone.kind(n) or "",
                                      can_test_sms=phone.can_sms(n)) for i, n in enumerate(allow)],
        allow_numbers_version=allow_version(conn), test_sms_index=test_index,
        limits=asdict(outreach.limits(conn)), agent_sms=conn.agent_sms, agent_kakao=conn.agent_kakao,
        agent_call=conn.agent_call, inbound_mode=conn.inbound_mode,
        handoff_number_masked=_masked(conn.handoff_number), is_default=conn.is_default, status=conn.status,
        checked_at=conn.checked_at, latency_ms=conn.latency_ms, used_today=used if conn.is_default else NO_USE,
    )


def list_out(session: Session) -> list[ConnectionOut]:
    rows = list(session.scalars(select(NotifyConnection).order_by(NotifyConnection.id)))
    used = used_today(session) if any(r.is_default for r in rows) else NO_USE
    return [out(r, used) for r in rows]


def status(session: Session) -> StatusOut:
    conn = outreach.connection(session)
    if conn is None:
        return StatusOut(ready=False, test_mode=True, allow_count=0,
                         agent=AgentOut(sms="approve", kakao="approve", call="approve"), inbound_mode="off",
                         kakao_ready=False)
    return StatusOut(ready=conn.status == "ok", test_mode=conn.test_mode,
                     allow_count=len(conn.allow_numbers_json or []),
                     agent=AgentOut(sms=conn.agent_sms, kakao=conn.agent_kakao, call=conn.agent_call),
                     inbound_mode=conn.inbound_mode, kakao_ready=False)


# ── 상한 ────────────────────────────────────────────────────────────


def limits_out(conn: NotifyConnection) -> LimitsOut:
    return LimitsOut(values=asdict(outreach.limits(conn)), defaults=asdict(outreach.limits(None)),
                     ranges={k: list(v) for k, v in outreach.LIMIT_RANGES.items()})  # 화면에 알려 줄 뿐(검사 아님)


def put_limits(session: Session, conn_id: int, values: dict) -> LimitsOut:
    """바꿀 칸만 받는다. 검사는 validate_limits 하나로(저장된 값 + 보낸 값). 새 dict 로 저장한다."""
    conn = get(session, conn_id)
    merged = {**(conn.limits_json if isinstance(conn.limits_json, dict) else {}), **values}
    errors = outreach.validate_limits(merged)
    if errors:
        raise ApiError(422, "invalid_limits", "한도 값이 올바르지 않습니다.",
                       {redact.hide_phones(k): v for k, v in errors.items()})
    conn.limits_json = merged
    session.commit()
    return limits_out(conn)


def reset_limits(session: Session, conn_id: int) -> LimitsOut:
    conn = get(session, conn_id)
    conn.limits_json = None
    session.commit()
    return limits_out(conn)
