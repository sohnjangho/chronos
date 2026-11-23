"""정보 API 연결 저장·연결 시험·빠른 채움 목록. 평문 키는 요청을 처리하는 동안에만 쓰고 암호문으로만 저장한다.

기상청(kma) 연결 시험은 서비스마다 한 번씩 부른다: 단기예보(서울 격자 60·127) 1번, ASOS 일자료(서울 108, 사흘 전 하루) 1번.
범용(generic) 연결은 주소·설명이 꼭 있고, 주소는 저장할 때 내부망 꼴을 거절한다(부를 때 app.info.generic 이 다시 본다).
범용 연결 시험은 test_path 를 한 번 부른다(HTTP 상태·걸린 시간·응답 앞 300자, 키 지움).
"""

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.info import generic, kma, templates
from app.info.generic import GenericConn, GenericFailed
from app.info.kma import KmaConn, KmaFailed
from app.llm.connections import secret_is_sendable
from app.programs.info_settings.schemas import (
    InfoConnectionCreate,
    InfoConnectionUpdate,
    InfoTestOut,
    ServiceCheckOut,
    ServiceErrorOut,
    TemplateOut,
)
from app.security.crypto import SecretUnreadable, decrypt, encrypt
from app.store.tables import InfoConnection

DEFAULT_BASE_URLS = {"kma": kma.DEFAULT_BASE_URL}
MIN_SECRET_CHARS_FOR_LAST4 = 8
TEST_STN, TEST_NX, TEST_NY = "108", 60, 127
TEST_DAYS_AGO = 3  # ASOS 일자료는 다음 날 들어온다 — 넉넉히 사흘 전 하루
# 요약 줄에 쓰는 짧은 말
SHORT = {"not_registered": "등록 안 됨", "key_expired": "키 기한 지남", "ip_not_allowed": "IP 미등록",
         "rate_limited": "호출 한도 초과", "bad_key": "키 오류", "timeout": "응답 늦음"}


def _secret_value(secret: SecretStr) -> str:
    value = secret.get_secret_value().strip()
    if not secret_is_sendable(value):
        raise ApiError(422, "invalid_secret",
                       "서비스키에 쓸 수 없는 문자가 있습니다. 공백이나 줄바꿈이 섞이지 않았는지 확인해 주세요.")
    return value


def _last4(secret: str) -> str:
    return secret[-4:] if len(secret) >= MIN_SECRET_CHARS_FOR_LAST4 else ""


def _get(session: Session, conn_id: int) -> InfoConnection:
    conn = session.get(InfoConnection, conn_id)
    if conn is None:
        raise ApiError(404, "connection_not_found", "연결을 찾을 수 없습니다.")
    return conn


def _set_secret(conn: InfoConnection, secret: str) -> None:
    conn.secret_ciphertext, conn.secret_last4 = encrypt(secret), _last4(secret)
    _untested(conn)


def _untested(conn: InfoConnection) -> None:
    conn.status, conn.checked_at = "unknown", None


def _check_generic(base_url: str | None, description: str, test_path: str, key_name: str) -> None:
    """범용 연결의 저장 검사: 주소(내부망 꼴 거절)·설명이 꼭 있고, 시험 경로는 부를 때와 같은 경로 검사."""
    if not base_url:
        raise ApiError(422, "base_url_required", "범용 연결에는 주소가 필요합니다.")
    if (problem := generic.base_url_problem(base_url)) is not None:
        raise ApiError(422, "base_url_not_allowed", problem)
    if not description.strip():
        raise ApiError(422, "description_required", "범용 연결에는 설명이 필요합니다(에이전트가 읽고 고릅니다).")
    if test_path and (problem := generic.request_problem(test_path, {}, key_name)) is not None:
        raise ApiError(422, "invalid_test_path", f"시험 경로: {problem}")


def list_connections(session: Session) -> list[InfoConnection]:
    return list(session.scalars(select(InfoConnection).order_by(InfoConnection.id)))


def create_connection(session: Session, data: InfoConnectionCreate) -> InfoConnection:
    """저장만 한다(status unknown). 시험은 /test 로 따로."""
    if data.preset == "generic":
        _check_generic(data.base_url, data.description, data.test_path, data.key_name)
    conn = InfoConnection(name=data.name, preset=data.preset, base_url=data.base_url or DEFAULT_BASE_URLS[data.preset],
                          description=data.description, usage=data.usage, key_in=data.key_in, key_name=data.key_name,
                          test_path=data.test_path)
    _set_secret(conn, _secret_value(data.secret))
    session.add(conn)
    session.commit()
    return conn


def update_connection(session: Session, conn_id: int, data: InfoConnectionUpdate) -> InfoConnection:
    """고친다. 키·주소·키 넣는 곳·키 이름이 바뀌면 status 를 unknown 으로 되돌린다. 다른 주소로 바꿀 때는 키도 다시 받는다."""
    conn = _get(session, conn_id)
    new_secret = _secret_value(data.secret) if data.secret is not None else None
    if data.base_url is not None and data.base_url != conn.base_url and new_secret is None:
        raise ApiError(422, "secret_required", "다른 주소로 바꾸면 서비스키를 다시 넣어 주세요.")
    fields = data.model_dump(exclude_unset=True, exclude={"name", "secret"})
    fields = {k: v for k, v in fields.items() if v is not None}
    if conn.preset == "generic":
        merged = {c: fields.get(c, getattr(conn, c)) for c in ("base_url", "description", "test_path", "key_name")}
        _check_generic(**merged)
    if any(fields.get(c, getattr(conn, c)) != getattr(conn, c) for c in ("base_url", "key_in", "key_name")):
        _untested(conn)
    for column, value in fields.items():
        setattr(conn, column, value)
    if new_secret is not None:
        _set_secret(conn, new_secret)
    if data.name is not None:
        conn.name = data.name
    session.commit()
    return conn


def delete_connection(session: Session, conn_id: int) -> None:
    session.delete(_get(session, conn_id))
    session.commit()


async def _check(service: str, label: str, call: Callable[[], Awaitable[object]]) -> ServiceCheckOut:
    start = time.perf_counter()
    error = None
    try:
        await call()
    except KmaFailed as e:
        error = ServiceErrorOut(code=e.code, message=e.message)
    return ServiceCheckOut(service=service, label=label, ok=error is None,
                           latency_ms=int((time.perf_counter() - start) * 1000), error=error)


def _summary(checks: list[ServiceCheckOut]) -> str:
    return " · ".join(f"{c.label} {'OK' if c.ok else SHORT.get(c.error.code, '실패')}" for c in checks)


def _key(conn: InfoConnection) -> str:
    try:
        return decrypt(conn.secret_ciphertext)
    except SecretUnreadable:
        raise ApiError(409, "secret_unreadable", "저장된 서비스키를 읽을 수 없습니다. 키를 다시 넣어 주세요.") from None


async def _test_kma(conn: InfoConnection) -> InfoTestOut:
    target = KmaConn(conn.base_url, _key(conn))
    day = datetime.now(kma.KST).date() - timedelta(days=TEST_DAYS_AGO)
    checks = [
        await _check("short_forecast", "단기예보", lambda: kma.short_forecast(target, TEST_NX, TEST_NY)),
        await _check("asos", "ASOS 일자료", lambda: kma.asos_daily(target, TEST_STN, day, day)),
    ]
    return InfoTestOut(ok=all(c.ok for c in checks), summary=_summary(checks), services=checks)


async def _test_generic(conn: InfoConnection) -> InfoTestOut:
    """test_path 를 한 번 부른다. ok = 2xx 이고 공공데이터포털 오류 봉투가 아님."""
    if not conn.test_path:
        raise ApiError(422, "test_path_required", "시험 경로를 넣어 주세요.")
    target = GenericConn(conn.name, conn.base_url, _key(conn), conn.key_in, conn.key_name)
    start = time.perf_counter()
    error, status, sample = None, None, None
    try:
        got = await generic.fetch(target, conn.test_path, {})
        status, sample = got.http_status, got.text[:generic.SAMPLE_LIMIT]
    except GenericFailed as e:
        error, status, sample = ServiceErrorOut(code=e.code, message=e.message), e.http_status, e.sample
    check = ServiceCheckOut(service="generic", label=conn.name, ok=error is None,
                            latency_ms=int((time.perf_counter() - start) * 1000), error=error)
    return InfoTestOut(ok=check.ok, summary=_summary([check]), services=[check], http_status=status, sample=sample)


async def test_connection(session: Session, conn_id: int) -> InfoTestOut:
    """연결 시험. 부르는 동안 쓰기를 쥐지 않는다(결과는 끝난 뒤에 저장)."""
    conn = _get(session, conn_id)
    result = await (_test_generic(conn) if conn.preset == "generic" else _test_kma(conn))
    conn.status, conn.checked_at = ("ok" if result.ok else "failed"), datetime.now(UTC)
    session.commit()
    return result


def list_templates() -> list[TemplateOut]:
    """빠른 채움 목록. 파일이 틀리면 ValueError 로 크게 실패한다(app.info.templates)."""
    return [TemplateOut(**t.model_dump()) for t in templates.load_templates()]
