"""info.list — 관리자가 연결해 둔 정보 API(공공데이터) 목록. 에이전트가 설명을 읽고 고른 뒤, 고른 연결의 쓰는 법을 하나씩 본다.

- 에이전트가 쓸 수 있는 연결만: preset kma(→ info.weather)·generic(→ info.call) 이고 저장된 키를 읽을 수 있는 것.
- 입력 없이 부르면 연결마다 {id, name, kind, description(120자까지), status, usage_chars} 이고 usage 는 null. 연결이 많아
  BUDGET(도구 결과 4,000자 한도 안)을 넘으면 앞의 들어가는 만큼만 주고 more(못 보인 수)와 hint 를 단다.
  connection_id 를 주면 그 연결 하나와 usage — usage 는 JSON 글로 옮긴 길이로 BUDGET 안까지(넘으면 끝을 줄인다).
- 키·끝 4자리·암호문·주소는 내보내지 않는다. 내보내는 글(이름·설명·쓰는 법)은 그 연결의 키로 한 번 더 지운다(scrub).
  kma 줄은 kind "kma" 와 info__weather 를 쓰라는 usage.
"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.info.generic import fit_json, scrub
from app.security.crypto import SecretUnreadable, decrypt
from app.store.tables import InfoConnection
from app.tools.context import ToolContext, ToolError
from app.tools.registry import tool

KMA_DESCRIPTION = "기상청 날씨 — 지난 해들의 그 달 통계(ASOS 일자료)와 오늘부터 3일 예보(단기예보)."
KMA_USAGE = "기상청 전용 연결입니다. info__call 로 부르지 말고 info__weather 로 보세요."
NOT_FOUND = "없는 정보 API 연결입니다: {id} — info__list 를 입력 없이 불러 연결 id 를 확인하세요."
BUDGET = 3600  # 결과를 JSON 글로 옮긴 길이 한도(도구 결과 4,000자 안, 여유 있게)
DESCRIPTION_IN_LIST = 120
MORE_HINT = ("연결이 많아 {more}개는 보이지 않습니다. 보이지 않는 연결은 마지막으로 보인 id 보다 큰 id 이고 "
             "connection_id 로 하나씩 볼 수 있습니다.")
USAGE_HINT = " …(쓰는 법이 길어 뒤를 줄였습니다)"


class ListIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: int | None = Field(default=None, description="주면 그 연결 하나와 쓰는 법(usage) 전체. 없으면 목록")


class ConnectionOut(BaseModel):
    id: int
    name: str
    kind: Literal["kma", "generic"]
    description: str
    status: str  # 'ok' | 'failed' | 'unknown' — 마지막 연결 시험 결과
    usage_chars: int  # 쓰는 법 글자 수
    usage: str | None = None  # connection_id 를 줄 때만


class ListOut(BaseModel):
    connections: list[ConnectionOut]
    more: int = 0  # BUDGET 에 들지 않아 보이지 않은 연결 수
    hint: str | None = None


def _key(row: InfoConnection) -> str | None:
    try:
        return decrypt(row.secret_ciphertext)
    except SecretUnreadable:
        return None


def _length(out: BaseModel) -> int:
    return len(json.dumps(out.model_dump(mode="json"), ensure_ascii=False))


def _short(text: str) -> str:
    return text if len(text) <= DESCRIPTION_IN_LIST else text[: DESCRIPTION_IN_LIST - 1] + "…"


def _out(row: InfoConnection, key: str, *, with_usage: bool) -> ConnectionOut:
    kma = row.preset == "kma"
    description = scrub((row.description or KMA_DESCRIPTION) if kma else row.description, key, key_name=row.key_name)
    usage = scrub(KMA_USAGE if kma else row.usage, key, key_name=row.key_name)
    out = ConnectionOut(id=row.id, name=scrub(row.name, key), kind="kma" if kma else "generic",
                        description=description if with_usage else _short(description), status=row.status,
                        usage_chars=len(usage))
    if with_usage:  # 쓰는 법 자리("usage": null 의 null)만큼 남은 예산 안에서
        out.usage = fit_json(usage, BUDGET - _length(ListOut(connections=[out])) + 4, USAGE_HINT)[0]
    return out


def _within_budget(found: list[ConnectionOut]) -> ListOut:
    """앞에서부터 BUDGET 에 드는 만큼. 다 들지 않으면 more·hint."""
    whole = ListOut(connections=found)
    if _length(whole) <= BUDGET:
        return whole
    for n in range(len(found) - 1, -1, -1):
        more = len(found) - n
        part = ListOut(connections=found[:n], more=more, hint=MORE_HINT.format(more=more))
        if _length(part) <= BUDGET:
            return part
    return part


@tool(
    "info.list",
    "관리자가 연결해 둔 정보 API(공공데이터) 목록을 본다: 연결마다 id·name·kind(kma = 기상청 전용, generic = 범용)·"
    "description(무엇을 주는지)·status(마지막 연결 시험)·usage_chars. 바깥 공공데이터(공휴일·특보·대기오염·입찰공고 등)가 "
    "필요하면 먼저 입력 없이 부르고, 맞는 generic 연결을 골라 connection_id 를 주어 다시 부르면 usage(쓰는 법: 경로·필수 "
    "파라미터·예시)가 온다. 그대로 info__call 을 짠다. 키는 보이지 않는다.",
)
def info_list(args: ListIn, ctx: ToolContext) -> ListOut:
    query = select(InfoConnection).where(InfoConnection.preset.in_(("kma", "generic"))).order_by(InfoConnection.id)
    if args.connection_id is not None:
        query = query.where(InfoConnection.id == args.connection_id)
    with ctx.session.no_autoflush:
        rows = ctx.session.scalars(query).all()
    found = [_out(r, key, with_usage=args.connection_id is not None) for r in rows if (key := _key(r)) is not None]
    if args.connection_id is not None and not found:
        raise ToolError(NOT_FOUND.format(id=args.connection_id))
    return _within_budget(found)
