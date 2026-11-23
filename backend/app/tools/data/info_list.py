"""info.list — 관리자가 연결해 둔 정보 API(공공데이터) 목록. 에이전트가 설명을 읽고 고른다.

- 에이전트가 쓸 수 있는 연결만: preset kma(→ info.weather)·generic(→ info.call) 이고 저장된 키를 읽을 수 있는 것.
- 키·끝 4자리·암호문·주소는 내보내지 않는다. kma 줄은 kind "kma" 와 info__weather 를 쓰라는 usage.
"""

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select

from app.security.crypto import SecretUnreadable, decrypt
from app.store.tables import InfoConnection
from app.tools.context import NoArgs, ToolContext
from app.tools.registry import tool

KMA_DESCRIPTION = "기상청 날씨 — 지난 해들의 그 달 통계(ASOS 일자료)와 오늘부터 3일 예보(단기예보)."
KMA_USAGE = "기상청 전용 연결입니다. info__call 로 부르지 말고 info__weather 로 보세요."


class ConnectionOut(BaseModel):
    id: int
    name: str
    kind: Literal["kma", "generic"]
    description: str
    usage: str
    status: str  # 'ok' | 'failed' | 'unknown' — 마지막 연결 시험 결과


class ListOut(BaseModel):
    connections: list[ConnectionOut]


def _readable(row: InfoConnection) -> bool:
    try:
        decrypt(row.secret_ciphertext)
    except SecretUnreadable:
        return False
    return True


def _out(row: InfoConnection) -> ConnectionOut:
    if row.preset == "kma":
        return ConnectionOut(id=row.id, name=row.name, kind="kma", description=row.description or KMA_DESCRIPTION,
                             usage=KMA_USAGE, status=row.status)
    return ConnectionOut(id=row.id, name=row.name, kind="generic", description=row.description, usage=row.usage,
                         status=row.status)


@tool(
    "info.list",
    "관리자가 연결해 둔 정보 API(공공데이터) 목록을 본다: 연결마다 id·name·kind(kma = 기상청 전용, generic = 범용)·"
    "description(무엇을 주는지)·usage(쓰는 법: 경로·필수 파라미터·예시)·status(마지막 연결 시험). 바깥 공공데이터"
    "(공휴일·특보·대기오염·입찰공고 등)가 필요하면 먼저 부르고, 맞는 generic 연결을 info__call 로 부른다. 키는 보이지 않는다.",
)
def info_list(args: NoArgs, ctx: ToolContext) -> ListOut:
    with ctx.session.no_autoflush:
        rows = ctx.session.scalars(select(InfoConnection).where(InfoConnection.preset.in_(("kma", "generic")))
                                   .order_by(InfoConnection.id)).all()
    return ListOut(connections=[_out(r) for r in rows if _readable(r)])
