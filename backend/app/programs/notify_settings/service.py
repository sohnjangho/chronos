"""알림 연결 저장·연결 테스트·상한·상태(계획 4 Task 70). 계약: .superpowers/sdd/2026-11-23-chronos-plan-4-contacts/task-70-contract.md.

- 평문 키는 요청을 처리하는 동안에만 쓰고 저장은 암호문으로만 한다. 기록(log)은 남기지 않는다.
  Account ID 는 식별자라 글로 저장한다(코디네이터 판정 — 출력에서는 가리고 로그 거르개에 올린다).
- 키·Account ID 를 풀어 쓰기 전에 `provider.register_secrets`. 바꾸거나 지울 때, 그리고 저장하지 않은 연결 테스트 뒤에는
  **저장된 연결이 쓰지 않는 값만** `redact.drop_secrets`.
- 제공사는 `provider.client_for(row)` 로만 부른다(모듈 속성 — 시험이 바꿔 끼운다). 연결 테스트 전체에 상한 CHECK_CEILING_S.
- 제공사를 부르는 길(async)은 DB 일을 스레드에서 한다(`*_sync` 함수 — 이벤트 루프를 막지 않게). 부르기 전에 트랜잭션을
  끝내고, 부른 뒤 줄을 다시 읽어 쓴다.
- 번호는 `phone.normalize` 꼴로 저장하고 가린 꼴로만 내보낸다. 오류에 보낸 값을 싣지 않는다.
- 상한 검사는 `store.outreach.validate_limits` 하나로만, 저장은 쓰기 트랜잭션 하나(BEGIN IMMEDIATE)로 한다.
"""

import asyncio
import dataclasses
import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from pydantic import SecretStr
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

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
    ConnectionSaved,
    ConnectionTestIn,
    ConnectionUpdate,
    ErrorOut,
    LimitsOut,
    ProbeOut,
    SenderOut,
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
MAX_CHARS = {"name": 100, "account_id": 100, "kakao_channel": 100, "base_url": 500, "allow_numbers_version": 100,
             "allow_numbers_add": 40, "handoff_number": 40, "number": 40, "reason": 200}  # 목록 칸은 항목마다
MAX_ITEMS = 50  # 목록 칸의 개수
OVERSEAS = "나라 밖 IP 에서는 보낼 수 없습니다. 이 서버가 나가는 IP 가 한국 밖으로 보입니다."
TIMEOUT = "제공사 응답이 시간 안에 오지 않았습니다."
UNKNOWN = "제공사 응답을 읽지 못했습니다."


@dataclass(frozen=True)
class Probe:
    """연결 테스트 결과. senders 는 정리한 번호(저장용) — 내보낼 때 가린다."""

    ok: bool
    latency_ms: int | None
    senders: list[str]
    error: ErrorOut | None


@dataclass(frozen=True)
class _Creds:
    """연결 테스트에 쓸 값(평문은 이 요청 동안만)."""

    base_url: str
    account_id: str
    key: str


# ── 입력 ──────────────────────────────────────────────────────────


def check_lengths(values: dict) -> None:
    """글 길이·목록 개수(계약 V5): 넘으면 422 too_long {field, max}. 값은 싣지 않는다."""
    for field, value in values.items():
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        limit = MAX_CHARS.get(field)
        if isinstance(value, list):
            if len(value) > MAX_ITEMS:
                raise ApiError(422, "too_long", f"{MAX_ITEMS}개까지 넣을 수 있습니다.", {"field": field, "max": MAX_ITEMS})
            if limit is not None and any(isinstance(v, str) and len(v) > limit for v in value):
                raise ApiError(422, "too_long", f"{limit}자까지 넣을 수 있습니다.", {"field": field, "max": limit})
        elif isinstance(value, str) and limit is not None and len(value) > limit:
            raise ApiError(422, "too_long", f"{limit}자까지 넣을 수 있습니다.", {"field": field, "max": limit})


def _check_name(name: str | None) -> None:
    if name is not None and not name.strip():
        raise ApiError(422, "required", "이름을 넣어 주세요.", {"field": "name"})


def _usable(value: str) -> bool:
    """진단·제공사 호출이 받는 꼴(ASCII·찍을 수 있는 글자·8자 이상)에 빈칸도 없음."""
    return diagnostics.MIN_SECRET <= len(value) <= MAX_SECRET_CHARS and value.isascii() and value.isprintable() \
        and " " not in value


def secret_value(secret: SecretStr) -> str:
    value = secret.get_secret_value().strip()
    if not _usable(value):
        raise ApiError(422, "invalid_secret", "API 키는 8자 이상이고 공백·줄바꿈 같은 글자가 없어야 합니다.")
    return value


def account_value(raw: SecretStr) -> str:
    value = raw.get_secret_value().strip()
    if not _usable(value):
        raise ApiError(422, "invalid_account_id", "Account ID 는 8자 이상이고 공백·줄바꿈 같은 글자가 없어야 합니다.")
    return value


def base_url_value(raw: str | None) -> str:
    value = (raw or "").strip() or diagnostics.DEFAULT_BASE_URL
    problem = diagnostics.base_url_problem(value)
    if problem:
        raise ApiError(422, "bad_base_url", problem)
    return value.rstrip("/")


def _new_creds(data: ConnectionTestIn) -> _Creds:
    check_lengths({"base_url": data.base_url, "account_id": data.account_id})
    return _Creds(base_url=base_url_value(data.base_url), account_id=account_value(data.account_id),
                  key=secret_value(data.secret))


def _bad_number(field: str, index: int | None = None) -> ApiError:
    detail = {"field": field} if index is None else {"field": field, "index": index}
    return ApiError(422, "invalid_number", "번호 형식이 올바르지 않거나 쓸 수 없는 번호입니다.", detail)


def _bad_index(field: str) -> ApiError:
    return ApiError(422, "invalid_index", "목록에 없는 순번입니다.", {"field": field})


def get(session: Session, conn_id: int, *, fresh: bool = False) -> NotifyConnection:
    conn = session.get(NotifyConnection, conn_id, populate_existing=fresh)
    if conn is None:
        raise ApiError(404, "connection_not_found", "알림 연결을 찾을 수 없습니다.")
    return conn


def begin_write(session: Session) -> None:
    """지금 트랜잭션을 끝내고 쓰기 트랜잭션(BEGIN IMMEDIATE)을 연다 — 읽고-합치고-쓰기를 한 덩어리로."""
    session.rollback()
    session.execute(text("BEGIN IMMEDIATE"))


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


def drop_unused(session: Session, values: list[str | None]) -> None:
    """키·Account ID 를 로그 거르개에서 뺀다 — 저장된 연결 가운데 같은 값을 쓰는 것이 없을 때만."""
    old = [v for v in values if v]
    if not old:
        return
    in_use: set[str] = set()
    for row in session.scalars(select(NotifyConnection)):
        in_use.update(v for v in (row.account_id, _key_or_none(row)) if v)
    session.rollback()
    redact.drop_secrets(*[v for v in old if v not in in_use])


# ── 연결 테스트 ─────────────────────────────────────────────────────


def _draft(creds: _Creds) -> NotifyConnection:
    """제공사 클라이언트를 만들 값만 담은 줄(세션에 넣지 않는다) — 부르는 동안 DB 줄을 붙들지 않게."""
    return NotifyConnection(base_url=creds.base_url, account_id=creds.account_id,
                            secret_ciphertext=crypto.encrypt(creds.key))


async def _probe(creds: _Creds) -> Probe:
    """`provider.check()` 한 번. 실패는 모두 Probe(ok=False) — 글에 키·Account ID·번호 없음."""
    provider.register_secrets(creds.key, creds.account_id)
    try:
        async with asyncio.timeout(CHECK_CEILING_S):
            check = await provider.client_for(_draft(creds)).check()
    except ProviderFailed as exc:
        message = OVERSEAS if exc.code == "overseas_ip" else redact.scrub(exc.message, [creds.key, creds.account_id])
        return Probe(False, None, [], ErrorOut(code=exc.code, message=message))
    except TimeoutError:
        return Probe(False, None, [], ErrorOut(code="timeout", message=TIMEOUT))
    except Exception:  # noqa: BLE001 — 어떤 실패든 「읽지 못함」으로(예외 글에 무엇이 섞였는지 모른다)
        return Probe(False, None, [], ErrorOut(code="unknown", message=UNKNOWN))
    return Probe(True, check.latency_ms, list(check.senders), None)


def _senders_out(numbers: list[str]) -> list[SenderOut]:
    return [SenderOut(index=i, number_masked=phone.mask(n), kind=phone.kind(n) or "", label=f"발신번호 {i + 1}")
            for i, n in enumerate(numbers)]


def probe_out(result: Probe) -> ProbeOut:
    return ProbeOut(ok=result.ok, latency_ms=result.latency_ms, senders=_senders_out(result.senders),
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


async def test_new(session: Session, data: ConnectionTestIn) -> ProbeOut:
    """저장하지 않는 연결 테스트. 끝나면 이 시험에만 쓴 키·Account ID 를 로그 거르개에서 뺀다."""
    creds = _new_creds(data)
    try:
        return probe_out(await _probe(creds))
    finally:
        await run_in_threadpool(drop_unused, session, [creds.key, creds.account_id])


def _insert_sync(session: Session, name: str, creds: _Creds, result: Probe) -> ConnectionSaved:
    conn = NotifyConnection(
        name=name.strip(), base_url=creds.base_url, secret_ciphertext=crypto.encrypt(creds.key),
        secret_last4=creds.key[-4:], account_id=creds.account_id, senders_json=[], kakao_channels_json=[],
        allow_numbers_json=[], test_mode=True, agent_sms="approve", agent_kakao="approve", agent_call="approve",
        inbound_mode="off", is_default=outreach.connection(session) is None,
    )
    _record(conn, result)
    session.add(conn)
    session.commit()
    return saved(session, conn, result)


async def create(session: Session, data: ConnectionCreate) -> ConnectionSaved:
    """연결 테스트를 한 번 하고 저장한다(실패해도 status 'failed' 로 저장). 기본값은 안전한 쪽."""
    check_lengths({"name": data.name})
    _check_name(data.name)
    creds = _new_creds(data)
    result = await _probe(creds)
    return await run_in_threadpool(_insert_sync, session, data.name, creds, result)


def _stored_creds_sync(session: Session, conn_id: int) -> _Creds:
    conn = get(session, conn_id)
    creds = _Creds(base_url=conn.base_url, account_id=conn.account_id, key=stored_key(conn))
    session.rollback()  # 트랜잭션을 끝내고 부른다
    return creds


def _retest_finish_sync(session: Session, conn_id: int, result: Probe) -> None:
    _record(get(session, conn_id, fresh=True), result)
    session.commit()


async def retest(session: Session, conn_id: int) -> ProbeOut:
    creds = await run_in_threadpool(_stored_creds_sync, session, conn_id)
    result = await _probe(creds)
    await run_in_threadpool(_retest_finish_sync, session, conn_id, result)
    return probe_out(result)


# ── 고치기 ──────────────────────────────────────────────────────────


def allow_version(conn: NotifyConnection) -> str:
    """허용 번호 목록의 판 — 지울 때·시험 문자를 보낼 때 「본 목록 그대로인가」를 본다. 번호로 되돌릴 수 없다(HMAC)."""
    body = f"allow:{conn.id}:" + json.dumps(list(conn.allow_numbers_json or []))
    return hmac.new(Settings().secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()[:24]


def check_allow_version(conn: NotifyConnection, version: str | None, missing: str) -> None:
    if version is None:
        raise ApiError(422, "allow_version_required", missing)
    # 판은 ASCII 글이다. 다른 글자(한글·이모지·짝 없는 서로게이트)가 섞인 값은 견주지 않고 낡은 판으로 다룬다 —
    # hmac.compare_digest 는 ASCII 가 아닌 str 에 TypeError 를 낸다. ASCII 끼리는 그대로 일정한 시간에 견준다.
    if not (version.isascii() and hmac.compare_digest(version, allow_version(conn))):
        raise ApiError(409, "allow_list_changed", "허용 번호 목록이 그사이 바뀌었습니다. 새로 불러온 뒤 다시 해 주세요.")


def _allow_list(conn: NotifyConnection, data: ConnectionUpdate) -> list[str] | None:
    if data.allow_numbers_remove is None and data.allow_numbers_add is None:
        return None
    current = list(conn.allow_numbers_json or [])
    if data.allow_numbers_remove:
        check_allow_version(conn, data.allow_numbers_version,
                            "허용 번호를 지우려면 목록 판(allow_numbers_version)을 함께 보내 주세요.")
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
    for field in ("test_mode", "agent_sms", "agent_call", "agent_kakao", "inbound_mode"):
        if getattr(data, field) is not None:
            changes[field] = getattr(data, field)
    if data.name is not None:
        changes["name"] = data.name.strip()
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


def _plan_update_sync(session: Session, conn_id: int, data: ConnectionUpdate) -> tuple[_Creds | None, list]:
    """입력을 모두 검사한다(아무것도 쓰지 않음). 주소·키·Account ID 가 바뀌면 (새 연결 값, 옛 비밀)."""
    conn = get(session, conn_id)
    check_lengths({f: getattr(data, f) for f in (*MAX_CHARS, "allow_numbers_remove") if f in ConnectionUpdate.model_fields})
    _check_name(data.name)
    _refuse_kakao(data)
    new_key = secret_value(data.secret) if data.secret is not None else None
    if data.base_url is not None and new_key is None:
        raise ApiError(422, "secret_required", "주소를 바꾸면 API 키를 다시 넣어 주세요.")
    base = base_url_value(data.base_url) if data.base_url is not None else conn.base_url
    account = account_value(data.account_id) if data.account_id is not None else conn.account_id
    _changes(conn, data)
    creds = None
    if new_key is not None or account != conn.account_id:
        creds = _Creds(base_url=base, account_id=account, key=new_key if new_key is not None else stored_key(conn))
    old = [_key_or_none(conn), conn.account_id]
    session.rollback()  # 트랜잭션을 끝내고 부른다
    return creds, old


def _finish_update_sync(session: Session, conn_id: int, data: ConnectionUpdate, creds: _Creds | None,
                        result: Probe | None, old: list) -> ConnectionSaved:
    conn = get(session, conn_id, fresh=True)  # 부르는 사이 다른 요청이 고친 칸을 덮지 않게 다시 읽는다
    if creds is not None and result is not None:
        conn.secret_ciphertext, conn.secret_last4 = crypto.encrypt(creds.key), creds.key[-4:]
        conn.base_url, conn.account_id = creds.base_url, creds.account_id
        _record(conn, result)
    for field, value in _changes(conn, data).items():  # 다시 읽은 줄에 맞춰 다시 검사·적용
        setattr(conn, field, value)
    if data.is_default:
        _make_default(session, conn)
    session.commit()
    out = saved(session, conn, result)
    if creds is not None:
        drop_unused(session, old)
    return out


async def update(session: Session, conn_id: int, data: ConnectionUpdate) -> ConnectionSaved:
    """보낸 칸만 고친다. 주소·키·Account ID 가 바뀌면 연결 테스트를 한 번 다시 한다(그때만 결과가 있다)."""
    creds, old = await run_in_threadpool(_plan_update_sync, session, conn_id, data)
    result = await _probe(creds) if creds is not None else None
    return await run_in_threadpool(_finish_update_sync, session, conn_id, data, creds, result, old)


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
    drop_unused(session, old)


def _has_history(session: Session) -> bool:
    return any(session.scalar(select(model.id).limit(1)) is not None for model in (OutreachMessage, OutreachCall))


# ── 보이기 ──────────────────────────────────────────────────────────


def used_today(session: Session) -> UsedToday:
    today = outreach_usage.summary(session, days=1)
    return UsedToday(sms=today.sms, call=today.calls_placed)


def _masked(number: str | None) -> str | None:
    return phone.mask(number) if number else None


def check_summary(conn: NotifyConnection, used: UsedToday | None) -> str:
    """연결 테스트 결과 한 줄 — 저장된 확인 결과(status·발신번호 목록)와 우리 DB 의 오늘 사용량만으로 만든다.
    제공사에 묻지 않는다. 이번 달 수는 제공사 조회 길이 문서로 확인되지 않아 싣지 않는다(어림하지 않는다)."""
    if conn.status == "failed":
        return "연결 테스트 실패 — 키·Account ID 를 확인하지 못했습니다"
    if conn.status != "ok":
        return "아직 연결 테스트를 하지 않았습니다"
    senders = list(conn.senders_json or [])
    if not senders:
        sender = "승인된 발신번호 없음"
    elif conn.sender_number in senders:
        sender = "발신번호 승인됨"
    else:
        sender = "발신번호 고르지 않음"
    parts = ["키·Account ID 확인됨", sender]
    if used is not None:
        parts.append(f"오늘 문자 {used.sms}건 · 통화 {used.call}통")
    return " · ".join(parts)


def out(conn: NotifyConnection, used: UsedToday | None) -> ConnectionOut:
    """used 는 기본 연결의 오늘 사용량(기본 연결이 아니면 무시하고 null)."""
    senders = list(conn.senders_json or [])
    allow = list(conn.allow_numbers_json or [])
    test_index = 0 if allow and phone.can_sms(allow[0]) and conn.sender_number else None
    account = conn.account_id or ""
    return ConnectionOut(
        id=conn.id, name=conn.name, provider=conn.provider, base_url=conn.base_url, secret_last4=conn.secret_last4,
        account_id_masked="…" + (account[-4:] if len(account) >= diagnostics.MIN_SECRET else ""),
        sender_number_masked=_masked(conn.sender_number),
        sender_index=senders.index(conn.sender_number) if conn.sender_number in senders else None,
        senders=_senders_out(senders), kakao_channel=conn.kakao_channel, test_mode=conn.test_mode,
        allow_numbers=[AllowNumberOut(index=i, number_masked=phone.mask(n), kind=phone.kind(n) or "",
                                      can_test_sms=phone.can_sms(n)) for i, n in enumerate(allow)],
        allow_numbers_version=allow_version(conn), test_sms_index=test_index,
        limits=asdict(outreach.limits(conn)), agent_sms=conn.agent_sms, agent_kakao=conn.agent_kakao,
        agent_call=conn.agent_call, inbound_mode=conn.inbound_mode,
        handoff_number_masked=_masked(conn.handoff_number), is_default=conn.is_default, status=conn.status,
        checked_at=conn.checked_at, latency_ms=conn.latency_ms, used_today=used if conn.is_default else None,
        check_summary=check_summary(conn, used if conn.is_default else None),
    )


def saved(session: Session, conn: NotifyConnection, result: Probe | None) -> ConnectionSaved:
    shown = out(conn, used_today(session) if conn.is_default else None)
    error = result.error if result is not None and not result.ok else None
    return ConnectionSaved(**shown.model_dump(), error=error)


def list_out(session: Session) -> list[ConnectionOut]:
    rows = list(session.scalars(select(NotifyConnection).order_by(NotifyConnection.id)))
    used = used_today(session) if any(r.is_default for r in rows) else None
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
    """바꿀 칸만 받는다. 검사는 validate_limits 하나로(저장된 값 + 보낸 값), 읽기부터 쓰기까지 쓰기 트랜잭션 하나.
    모르는 칸은 이름을 싣지 않고 개수만 알린다."""
    begin_write(session)
    try:
        conn = get(session, conn_id, fresh=True)
    except ApiError:
        session.rollback()
        raise
    merged = {**(conn.limits_json if isinstance(conn.limits_json, dict) else {}), **values}
    errors = outreach.validate_limits(merged)
    if errors:
        session.rollback()
        known = {f.name for f in dataclasses.fields(outreach.Limits)}
        detail: dict = {k: v for k, v in errors.items() if k in known}
        unknown = sum(1 for k in errors if k not in known)
        if unknown:
            detail["unknown_fields"] = unknown
        raise ApiError(422, "invalid_limits", "한도 값이 올바르지 않습니다.", detail)
    conn.limits_json = merged
    session.commit()
    return limits_out(conn)


def reset_limits(session: Session, conn_id: int) -> LimitsOut:
    conn = get(session, conn_id)
    conn.limits_json = None
    session.commit()
    return limits_out(conn)
