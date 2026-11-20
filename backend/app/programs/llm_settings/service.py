"""LLM 연결 저장·연결 시험과 쓰임새별 모델 배정.

평문 키는 요청을 처리하는 동안에만 쓰고, 저장은 암호문으로만 한다. 기록(log)은 남기지 않는다.
"""

import logging
from dataclasses import asdict
from datetime import UTC, datetime

import httpx
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.files import jobs
from app.llm import assignments, connections
from app.llm.connections import (
    DEFAULT_BASE_URLS,
    ModelInfo,
    ProbeResult,
    normalize_models,
    secret_is_sendable,
)
from app.programs.llm_settings.schemas import (
    AssignmentOut,
    AssignmentsIn,
    ConnectionCreate,
    ConnectionModels,
    ConnectionTestIn,
    ConnectionUpdate,
    ModelsFor,
    ReindexOut,
    StatusOut,
)
from app.security.crypto import SecretUnreadable, decrypt, encrypt
from app.store.tables import LlmAssignment, LlmConnection

logger = logging.getLogger(__name__)
NO_REINDEX_MESSAGE = "다시 넣기를 시작할 수 없어 임베딩 모델을 바꾸지 않았습니다."

# 키가 이보다 짧으면 끝 4자리도 보여주지 않는다(거의 전부가 드러나므로).
MIN_SECRET_CHARS_FOR_LAST4 = 8

_DEFAULT_PORTS = {"http": 80, "https": 443}


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
            422, "secret_required", "다른 서버 주소로 바꾸면 API 키를 다시 넣어 주세요."
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


def connection_models(session: Session, conn_id: int) -> list[ModelInfo]:
    return normalize_models(_get(session, conn_id).models_json)


def chat_model_count(conn: LlmConnection) -> int | None:
    """대화용 모델 수. 시험에 성공한 적이 없으면(model_count 없음) None."""
    if conn.model_count is None:
        return None
    return sum(1 for model in normalize_models(conn.models_json) if model["chat"])


def _fits(model: ModelInfo, purpose: ModelsFor) -> bool:
    if purpose == "embedding":
        return bool(model.get("embedding"))
    return model["chat"]  # 그림 입력 여부는 /models 가 알려 주지 않아 대화용 목록 그대로


def models_for(session: Session, purpose: ModelsFor) -> list[ConnectionModels]:
    """연결마다 저장된 모델 목록을 쓰임새로 거른다(연결 차례)."""
    return [
        ConnectionModels(connection_id=conn.id, name=conn.name, is_default=conn.is_default,
                         models=[m for m in normalize_models(conn.models_json) if _fits(m, purpose)])
        for conn in list_connections(session)
    ]


def get_assignments(session: Session) -> list[AssignmentOut]:
    """여섯 쓰임새 모두. 저장 안 된 쓰임새는 기본 연결을 가리키는 기본값으로 채운다."""
    return [AssignmentOut(**asdict(item)) for item in assignments.resolve_all(session)]


def _check_embedding(session: Session, connection_id: int, model: str) -> None:
    conn = session.get(LlmConnection, connection_id)
    if not any(m["id"] == model and _fits(m, "embedding") for m in normalize_models(conn.models_json)):
        raise ApiError(422, "invalid_request", "임베딩을 지원하지 않는 모델입니다.", {"model": model})


def _start_reindex(model: str) -> ReindexOut:
    """Task 48 의 다시 넣기를 시작한다(reindex_jobs 줄을 바로 만들고 {job_id, total} 을 돌려준다).

    함수가 없거나 실패하면 503 — 부른 쪽은 배정을 저장하지 않는다(벡터와 배정이 어긋나지 않게).
    """
    enqueue = getattr(jobs, "enqueue_reindex", None)
    if enqueue is None:
        raise ApiError(503, "reindex_unavailable", NO_REINDEX_MESSAGE)
    try:
        return ReindexOut(**enqueue(model))
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 배정을 바꾸지 않고 알린다(종류만 남김)
        logger.warning("다시 넣기 시작 실패: %s", type(exc).__name__)
        raise ApiError(503, "reindex_unavailable", NO_REINDEX_MESSAGE) from None


def put_assignments(session: Session, data: AssignmentsIn) -> ReindexOut | None:
    """저장한다. 임베딩 모델이 바뀌면 저장 전에 다시 넣기를 먼저 시작하고, 못 하면 아무것도 저장하지 않는다."""
    ids = {item.connection_id for item in data.items}
    known = set(session.scalars(select(LlmConnection.id).where(LlmConnection.id.in_(ids))))
    missing = sorted(ids - known)
    if missing:
        raise ApiError(
            422, "invalid_request", "없는 연결을 골랐습니다.", {"connection_ids": missing}
        )
    embedding = [item for item in data.items if item.purpose == "embedding"]
    for item in embedding:
        _check_embedding(session, item.connection_id, item.model)
    reindex = None
    if embedding and embedding[-1].model != assignments.resolve(session, "embedding").model:  # 뒤의 줄이 저장된다
        reindex = _start_reindex(embedding[-1].model)
    for item in data.items:
        session.merge(LlmAssignment(**item.model_dump()))
    session.commit()
    return reindex


def status(session: Session) -> StatusOut:
    default = _default(session)
    return StatusOut(
        ready=default is not None and default.status == "ok",
        default_connection=default.name if default else None,
    )
