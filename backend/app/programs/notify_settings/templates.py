"""카카오톡 채널·문안 상태 API(계획 4 Task 101) — 읽기만. 보내기·문안 등록·카카오톡 켜기는 없다([PM 11-23]).

- `POST /api/notify/connections/{id}/kakao/sync`(관리자): 제공사에서 채널·문안 목록을 읽어 `kakao_channels_json`·`kakao_templates`
  를 맞춘다(app.outreach.kakao — 상한·지우기·dormant). 목록 읽는 길이 확인되지 않았으면(`provider.KAKAO_LISTING_CONFIRMED`
  거짓, 또는 클라이언트가 `not_confirmed`) 제공사를 부르지 않고 501 `kakao_listing_unconfirmed`. 같은 연결의 진단이 돌고 있으면
  409 `diagnosis_running`(진단 길과 같은 표시 `diagnose._RUNNING`). 읽는 동안 DB 트랜잭션을 쥐지 않고(부르기 전에 끝내고,
  읽은 뒤 쓰기 트랜잭션 하나로 다시 읽어 쓴다), 전체에 `SYNC_CEILING_S`. 실패하면 아무것도 쓰지 않는다(502 `kakao_sync_failed`).
- `GET …/kakao`(관리자): 맞춰 둔 것. `PATCH …/kakao/templates/{tid}`(관리자): `use`·`fallback_body` 만 — 다른 연결의 문안은
  없는 것과 같은 404. 글 검사는 문자 본문과 같은 규칙(NFC, 줄 바꿈·탭 밖의 제어·글 방향·폭 없는 글자는 422, 1,000자).
- `GET /api/notify/templates`(관리자·사용자, 현장 관리자 빼고): 입력창에 필요한 것만 — 기본 연결의 쓰는 곳이 이어진 문안과
  「잠김 + 까닭」. 채널·제공사 문안 id·계정 자료는 싣지 않는다.
- 오류 글에 보낸 값을 싣지 않는다. 응답의 번호는 가린 꼴(끝 4자리)뿐이고 키·Account ID 는 없다.
"""

import asyncio
import unicodedata
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.errors import ApiError
from app.outreach import kakao, provider, redact
from app.outreach.provider import ProviderFailed
from app.programs.notify_settings import diagnose, service
from app.programs.notify_settings.schemas import UtcDatetime
from app.security.deps import require_admin, require_contacts
from app.store import outreach
from app.store.tables import User
from app.store.tables_outreach import KakaoTemplate, NotifyConnection
from app.store.timeutil import as_utc

router = APIRouter(prefix="/api/notify", tags=["notify"])
SessionDep = Annotated[Session, Depends(get_session)]
AdminOnly = Depends(require_admin)

SYNC_CEILING_S = 60.0  # 맞추기 한 번의 전체 시간(요청마다의 15초 제한 위에 한 번 더)
SHOWN_MAX = 500  # 한 연결에서 보이는 문안 줄 수(dormant 는 뒤로)
USE_MAX = 50  # kakao_templates.use 칸 길이
RUNNING = "이 연결의 진단이 이미 돌고 있습니다. 끝난 뒤 다시 해 주세요."
TEMPLATE_NOT_FOUND = "알림톡 문안을 찾을 수 없습니다."
BAD_TEXT = "보이지 않는 제어 글자나 글 방향을 바꾸는 글자를 쓸 수 없습니다."
# 주소록 메모·문자 본문과 같은 막는 글자: 글 방향 바꾸기·표시, 줄·문단 구분, 폭 없는 빈칸, 제어 글자(줄 바꿈·탭 빼고)
_HIDDEN = (frozenset(range(0x202A, 0x202F)) | frozenset(range(0x2066, 0x206A))
           | {0x200E, 0x200F, 0x061C, 0x2028, 0x2029, 0x200B})


class ChannelOut(BaseModel):
    id: str
    name: str
    status: str


class TemplateOut(BaseModel):
    id: int
    channel: str
    provider_template_id: str
    use: str | None
    body: str  # 번호는 끝 4자리만 남긴 가린 꼴
    variables: list[str]
    status: str  # approved | reviewing | rejected | dormant
    reply_line: bool  # 지금 발신번호로 다시 본 값
    usable: bool
    fallback_body: str | None


class KakaoOut(BaseModel):
    available: bool  # 목록 읽는 길이 확인됐는가
    reason: str | None  # available 이 거짓인 까닭
    channels: list[ChannelOut]
    templates: list[TemplateOut]
    synced_at: UtcDatetime | None  # 문안 줄의 마지막 맞춘 시각(줄이 없으면 null)
    ready: bool  # kakao.ready — 지금은 늘 거짓


class SyncOut(KakaoOut):
    truncated: bool  # 상한 뒤에 읽지 않은 것이 있을 수 있음 — 그래서 dormant 로 바꾼 것이 없음


class TemplatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use: StrictStr | None = None
    fallback_body: StrictStr | None = None


class ComposerTemplate(BaseModel):
    id: int
    use: str
    body: str
    variables: list[str]
    fallback_body: str | None
    status: str
    usable: bool


class ComposerOut(BaseModel):
    ready: bool
    reason: str | None  # ready 가 거짓인 까닭(입력창의 잠긴 카카오톡 옆에)
    templates: list[ComposerTemplate]


# ── 보이기 ──────────────────────────────────────────────────────────


def _template_out(row: KakaoTemplate, sender: str | None) -> TemplateOut:
    return TemplateOut(id=row.id, channel=row.channel, provider_template_id=row.provider_template_id, use=row.use,
                       body=row.body, variables=list(row.variables_json or []), status=row.status,
                       reply_line=kakao.has_reply_line(row.body, sender), usable=kakao.usable(row),
                       fallback_body=row.fallback_body)


def _channels(stored: object) -> list[ChannelOut]:
    out = []
    for item in stored if isinstance(stored, list) else []:
        try:
            out.append(ChannelOut.model_validate(item))
        except ValidationError:
            continue
    return out


def _view(session: Session, conn: NotifyConnection) -> KakaoOut:
    rows = list(session.scalars(select(KakaoTemplate).where(KakaoTemplate.connection_id == conn.id)
                                .order_by(KakaoTemplate.status == "dormant", KakaoTemplate.id).limit(SHOWN_MAX)))
    available = provider.KAKAO_LISTING_CONFIRMED
    return KakaoOut(available=available, reason=None if available else provider.KAKAO_NOT_CONFIRMED,
                    channels=_channels(conn.kakao_channels_json),
                    templates=[_template_out(row, conn.sender_number) for row in rows],
                    synced_at=max((as_utc(row.synced_at) for row in rows), default=None), ready=kakao.ready(session))


def view(session: Session, conn_id: int) -> KakaoOut:
    return _view(session, service.get(session, conn_id))


def composer(session: Session) -> ComposerOut:
    conn = outreach.connection(session)
    rows = [] if conn is None else session.scalars(
        select(KakaoTemplate).where(KakaoTemplate.connection_id == conn.id, KakaoTemplate.status != "dormant",
                                    KakaoTemplate.use.is_not(None)).order_by(KakaoTemplate.id).limit(SHOWN_MAX))
    ready = kakao.ready(session)
    return ComposerOut(ready=ready, reason=None if ready else kakao.NOT_READY, templates=[
        ComposerTemplate(id=row.id, use=row.use, body=row.body, variables=list(row.variables_json or []),
                         fallback_body=row.fallback_body, status=row.status, usable=kakao.usable(row))
        for row in rows])


# ── 맞추기 ──────────────────────────────────────────────────────────


def _unconfirmed() -> ApiError:
    return ApiError(501, "kakao_listing_unconfirmed", provider.KAKAO_NOT_CONFIRMED)


def _failed(reason: str, message: str) -> ApiError:
    return ApiError(502, "kakao_sync_failed", message, {"reason": reason})


def _prepare_sync(session: Session, conn_id: int) -> tuple[NotifyConnection, list[str]]:
    """제공사 클라이언트를 만들 값만 담은 줄(세션 밖)과 지울 비밀. 트랜잭션을 끝내고 돌려준다."""
    conn = service.get(session, conn_id)
    key = service.stored_key(conn)
    draft = NotifyConnection(base_url=conn.base_url, account_id=conn.account_id,
                             secret_ciphertext=conn.secret_ciphertext)
    session.rollback()
    return draft, [key, draft.account_id]


def _save_sync(session: Session, conn_id: int, listing: kakao.Listing) -> SyncOut:
    service.begin_write(session)
    try:
        conn = service.get(session, conn_id, fresh=True)
    except ApiError:
        session.rollback()
        raise
    kakao.save(session, conn, listing, datetime.now(UTC))
    session.commit()
    return SyncOut(**_view(session, conn).model_dump(), truncated=listing.truncated)


async def sync(session: Session, conn_id: int) -> SyncOut:
    draft, secrets = await run_in_threadpool(_prepare_sync, session, conn_id)
    if conn_id in diagnose._RUNNING:
        raise ApiError(409, "diagnosis_running", RUNNING)
    if not provider.KAKAO_LISTING_CONFIRMED:
        raise _unconfirmed()
    provider.register_secrets(*secrets)
    try:
        async with asyncio.timeout(SYNC_CEILING_S):
            listing = await kakao.read_listing(provider.client_for(draft))
    except ProviderFailed as exc:
        if exc.code == "not_confirmed":
            raise _unconfirmed() from None
        raise _failed(exc.code, redact.scrub(exc.message, secrets)) from None
    except TimeoutError:
        raise _failed("timeout", service.TIMEOUT) from None
    return await run_in_threadpool(_save_sync, session, conn_id, kakao.clean(listing, secrets))


# ── 고치기 ──────────────────────────────────────────────────────────


def _checked_text(raw: str | None, field: str, limit: int, *, lines: bool) -> str | None:
    text = unicodedata.normalize("NFC", raw or "").strip()
    if any(ord(c) in _HIDDEN or (unicodedata.category(c) == "Cc" and (not lines or c not in "\n\t")) for c in text):
        raise ApiError(422, "invalid_text", BAD_TEXT, {"field": field})
    if len(text) > limit:
        raise ApiError(422, "too_long", f"{limit}자까지 넣을 수 있습니다.", {"field": field, "max": limit})
    return text or None


def patch(session: Session, conn_id: int, tid: int, data: TemplatePatch) -> TemplateOut:
    values = {}
    if "use" in data.model_fields_set:
        values["use"] = _checked_text(data.use, "use", USE_MAX, lines=False)
    if "fallback_body" in data.model_fields_set:
        values["fallback_body"] = _checked_text(data.fallback_body, "fallback_body", kakao.BODY_MAX, lines=True)
    conn = service.get(session, conn_id)
    row = session.get(KakaoTemplate, tid)
    if row is None or row.connection_id != conn.id:
        raise ApiError(404, "template_not_found", TEMPLATE_NOT_FOUND)
    for name, value in values.items():
        setattr(row, name, value)
    session.commit()
    return _template_out(row, conn.sender_number)


# ── 길 ─────────────────────────────────────────────────────────────


@router.post("/connections/{conn_id}/kakao/sync", dependencies=[AdminOnly])
async def sync_kakao(conn_id: int, session: SessionDep) -> SyncOut:
    return await sync(session, conn_id)


@router.get("/connections/{conn_id}/kakao", dependencies=[AdminOnly])
def get_kakao(conn_id: int, session: SessionDep) -> KakaoOut:
    return view(session, conn_id)


@router.patch("/connections/{conn_id}/kakao/templates/{tid}", dependencies=[AdminOnly])
def patch_template(conn_id: int, tid: int, body: TemplatePatch, session: SessionDep) -> TemplateOut:
    return patch(session, conn_id, tid, body)


@router.get("/templates")
def list_templates(session: SessionDep, _user: Annotated[User, Depends(require_contacts)]) -> ComposerOut:
    return composer(session)
