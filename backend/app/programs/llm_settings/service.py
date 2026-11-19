"""LLM 연결 저장·연결 시험과 쓰임새별 모델 배정.

평문 키는 요청을 처리하는 동안에만 쓰고, 저장은 암호문으로만 한다. 기록(log)은 남기지 않는다.
"""

from datetime import UTC, datetime

import httpx
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.llm import connections
from app.llm.connections import DEFAULT_BASE_URLS, ProbeResult, secret_is_sendable
from app.programs.llm_settings.schemas import (
    AssignmentOut,
    AssignmentsIn,
    ConnectionCreate,
    ConnectionTestIn,
    ConnectionUpdate,
    StatusOut,
)
from app.security.crypto import SecretUnreadable, decrypt, encrypt
from app.store.tables import LlmAssignment, LlmConnection

# 키가 이보다 짧으면 끝 4자리도 보여주지 않는다(거의 전부가 드러나므로).
MIN_SECRET_CHARS_FOR_LAST4 = 8

_DEFAULT_PORTS = {"http": 80, "https": 443}

# 쓰임새별 기본 배정: (모델, 라우팅 전략). 기본 연결을 가리킨다.
DEFAULT_ASSIGNMENTS: dict[str, tuple[str, str | None]] = {
    "light": ("liner-claude-router", "cost"),
    "normal": ("liner-claude-router", "balanced"),
    "hard": ("liner-claude-router", "quality"),
    "longdoc": ("liner-mark", None),
}


def _resolve_base_url(provider: str, base_url: str | None) -> str:
    if base_url:
        return base_url
    default = DEFAULT_BASE_URLS.get(provider)
    if default is None:
        raise ApiError(422, "base_url_required", "연결 주소를 넣어 주세요.")
    return default


def _last4(secret: str) -> str:
    return secret[-4:] if len(secret) >= MIN_SECRET_CHARS_FOR_LAST4 else ""


def _origin(url: str) -> tuple[str, str, int]:
    """(scheme, host, 실제 포트). 기본 포트는 채워서 비교한다."""
    parsed = httpx.URL(url)
    return parsed.scheme, parsed.host.lower(), parsed.port or _DEFAULT_PORTS[parsed.scheme]


def _secret_value(secret: SecretStr) -> str:
    """앞뒤 공백을 떼고, 머리글에 실을 수 없는 키면 422 invalid_secret(키는 응답에 담지 않음)."""
    value = secret.get_secret_value().strip()
    if not secret_is_sendable(value):
        raise ApiError(
            422,
            "invalid_secret",
            "API 키에 쓸 수 없는 문자가 있습니다. 공백이나 줄바꿈이 섞이지 않았는지 확인해 주세요.",
        )
    return value


def _get(session: Session, conn_id: int) -> LlmConnection:
    conn = session.get(LlmConnection, conn_id)
    if conn is None:
        raise ApiError(404, "connection_not_found", "연결을 찾을 수 없습니다.")
    return conn


def _default(session: Session) -> LlmConnection | None:
    return session.scalar(select(LlmConnection).where(LlmConnection.is_default))


def _stored_secret(conn: LlmConnection) -> str:
    try:
        return decrypt(conn.secret_ciphertext)
    except SecretUnreadable:
        raise ApiError(
            409, "secret_unreadable", "저장된 키를 읽을 수 없습니다. 키를 다시 넣어 주세요."
        ) from None


def _record(conn: LlmConnection, result: ProbeResult) -> None:
    """시험 결과를 연결에 적는다. 모델 목록은 성공했을 때만 바꾼다."""
    conn.status = "ok" if result.ok else "failed"
    conn.latency_ms = result.latency_ms
    conn.checked_at = datetime.now(UTC)
    if result.ok:
        conn.models_json = result.models
        conn.model_count = len(result.models)


def _make_default(session: Session, conn: LlmConnection) -> None:
    for other in session.scalars(select(LlmConnection).where(LlmConnection.is_default)):
        other.is_default = False
    conn.is_default = True


def list_connections(session: Session) -> list[LlmConnection]:
    return list(session.scalars(select(LlmConnection).order_by(LlmConnection.id)))


def test_connection(data: ConnectionTestIn) -> ProbeResult:
    base_url = _resolve_base_url(data.provider, data.base_url)
    return connections.probe(base_url, _secret_value(data.secret))


def create_connection(
    session: Session, data: ConnectionCreate
) -> tuple[LlmConnection, ProbeResult]:
    """연결을 시험하고 저장한다. 시험이 실패해도 status='failed' 로 저장한다."""
    base_url = _resolve_base_url(data.provider, data.base_url)
    secret = _secret_value(data.secret)
    result = connections.probe(base_url, secret)
    conn = LlmConnection(
        name=data.name,
        provider=data.provider,
        base_url=base_url,
        secret_ciphertext=encrypt(secret),
        secret_last4=_last4(secret),
        is_default=_default(session) is None,
    )
    _record(conn, result)
    session.add(conn)
    session.commit()
    return conn, result


def update_connection(
    session: Session, conn_id: int, data: ConnectionUpdate
) -> tuple[LlmConnection, ProbeResult | None]:
    """고친다. 주소나 키가 바뀌면 다시 시험한다(그때만 결과가 있다)."""
    conn = _get(session, conn_id)
    new_secret = _secret_value(data.secret) if data.secret is not None else None
    url_changed = data.base_url is not None and data.base_url != conn.base_url
    if url_changed and new_secret is None and _origin(data.base_url) != _origin(conn.base_url):
        raise ApiError(
            422, "secret_required", "주소의 호스트가 바뀌면 API 키를 다시 넣어 주세요."
        )
    result = None
    if url_changed or new_secret is not None:
        secret = new_secret if new_secret is not None else _stored_secret(conn)
        if new_secret is not None:
            conn.secret_ciphertext = encrypt(secret)
            conn.secret_last4 = _last4(secret)
        if data.base_url is not None:
            conn.base_url = data.base_url
        result = connections.probe(conn.base_url, secret)
        _record(conn, result)
    if data.name is not None:
        conn.name = data.name
    if data.is_default:
        _make_default(session, conn)
    session.commit()
    return conn, result


def retest_connection(session: Session, conn_id: int) -> ProbeResult:
    conn = _get(session, conn_id)
    result = connections.probe(conn.base_url, _stored_secret(conn))
    _record(conn, result)
    session.commit()
    return result


def delete_connection(session: Session, conn_id: int) -> None:
    """지운다. 기본 연결이었으면 남은 것 중 가장 오래된 것이 기본이 된다.

    이 연결을 가리키던 배정은 지워서 기본 배정으로 돌아가게 한다.
    """
    conn = _get(session, conn_id)
    was_default = conn.is_default
    session.execute(delete(LlmAssignment).where(LlmAssignment.connection_id == conn.id))
    session.delete(conn)
    session.flush()
    if was_default:
        oldest = session.scalars(select(LlmConnection).order_by(LlmConnection.id)).first()
        if oldest is not None:
            oldest.is_default = True
    session.commit()


def connection_models(session: Session, conn_id: int) -> list[str]:
    return list(_get(session, conn_id).models_json)


def get_assignments(session: Session) -> list[AssignmentOut]:
    """네 쓰임새 모두. 저장 안 된 쓰임새는 기본 연결을 가리키는 기본값으로 채운다."""
    stored = {a.purpose: a for a in session.scalars(select(LlmAssignment))}
    default = _default(session)
    items = []
    for purpose, (model, strategy) in DEFAULT_ASSIGNMENTS.items():
        found = stored.get(purpose)
        if found is not None:
            items.append(
                AssignmentOut(
                    purpose=purpose,
                    connection_id=found.connection_id,
                    model=found.model,
                    routing_strategy=found.routing_strategy,
                )
            )
        else:
            items.append(
                AssignmentOut(
                    purpose=purpose,
                    connection_id=default.id if default else None,
                    model=model,
                    routing_strategy=strategy,
                )
            )
    return items


def put_assignments(session: Session, data: AssignmentsIn) -> None:
    ids = {item.connection_id for item in data.items}
    known = set(session.scalars(select(LlmConnection.id).where(LlmConnection.id.in_(ids))))
    missing = sorted(ids - known)
    if missing:
        raise ApiError(
            422, "invalid_request", "없는 연결을 골랐습니다.", {"connection_ids": missing}
        )
    for item in data.items:
        session.merge(LlmAssignment(**item.model_dump()))
    session.commit()


def status(session: Session) -> StatusOut:
    default = _default(session)
    return StatusOut(
        ready=default is not None and default.status == "ok",
        default_connection=default.name if default else None,
    )
