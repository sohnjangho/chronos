"""대화 에이전트가 지금 무엇을 할 수 있나(계획 4 Task 80): 채널마다 권한(승인 받기·위임)과 시험 모드.

기본 알림 연결(store.outreach.connection) 한 줄만 읽는다 — 네트워크도 다른 표도 보지 않는다(쿼리 하나).
번호·키·Account ID 는 읽지도 내보내지도 않는다. 권한 값은 approve | delegate 이고, 그 밖의 값은 approve 로 읽는다
(모르는 값을 위임으로 보지 않게). 연결이 없으면 GET /api/notify/status 와 같은 기본값(모두 승인 받기, 시험 모드 켜짐).
보내기 판정은 여기서 하지 않는다 — 나가는 문(harness.gate)이 보낼 때마다 처음부터 다시 본다.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.store import outreach
from app.store.tables import User
from app.store.tables_outreach import NotifyConnection
from app.tools import registry

Permission = Literal["approve", "delegate"]
_WORDS = {"approve": "승인 받기", "delegate": "위임"}
_CONTACT_TOOLS = ("contacts.", "notify.")  # 연락처를 쓰는 대화 도구 이름의 앞
SEND_MESSAGE, PLACE_CALL = "notify.send_message", "notify.place_call"  # 위임일 때만 보이는 보내기 도구(Task 81)


@dataclass(frozen=True)
class AgentPolicy:
    ready: bool  # 기본 연결이 있고 연결 상태가 ok
    test_mode: bool  # 켜져 있으면 허용 번호에만 실제로 나간다
    sms: Permission
    kakao: Permission
    call: Permission


def _permission(value: object) -> Permission:
    return "delegate" if value == "delegate" else "approve"


def for_agent(session: Session) -> AgentPolicy:
    """기본 연결의 권한·시험 모드. 연결이 없으면 준비 안 됨·시험 모드·모두 승인 받기."""
    return _of(outreach.connection(session))


def _of(conn: NotifyConnection | None) -> AgentPolicy:
    if conn is None:
        return AgentPolicy(ready=False, test_mode=True, sms="approve", kakao="approve", call="approve")
    return AgentPolicy(ready=conn.status == "ok", test_mode=bool(conn.test_mode), sms=_permission(conn.agent_sms),
                       kakao=_permission(conn.agent_kakao), call=_permission(conn.agent_call))


def hidden_tools(session: Session, user: User | None) -> frozenset[str]:
    """이번 턴에 모델에게 보이지 않을 도구 이름. 현장 관리자이거나 기본 연결이 없으면 contacts.*·notify.* 전부. 아니면 위임이
    아닌 쪽의 보내기 도구 — 문자·카카오톡이 둘 다 승인 받기면 notify.send_message, 전화가 승인 받기면 notify.place_call(모르는
    값은 승인 받기). 첫 겹일 뿐이다: 그래도 불리면 나가는 문이 권한 차례에서 막는다. 쿼리는 기본 연결 하나(현장 관리자는 0)."""
    conn = None if user is not None and user.role == "field" else outreach.connection(session)
    if conn is None:
        return frozenset(s.name for s in registry.list_tools(enabled_only=False) if s.name.startswith(_CONTACT_TOOLS))
    p = _of(conn)
    return frozenset(name for name, shown in ((SEND_MESSAGE, "delegate" in (p.sms, p.kakao)),
                                              (PLACE_CALL, p.call == "delegate")) if not shown)


def line(session: Session) -> str | None:
    """맥락 한 줄: 「- 알림: 문자 승인 받기 · 카카오톡 승인 받기 · 전화 위임 · 시험 모드 켜짐」. 연결이 없으면 None.
    연결 상태가 ok 가 아니면 끝에 「· 연결 확인 전」."""
    conn = outreach.connection(session)
    if conn is None:
        return None
    p = _of(conn)
    parts = [f"문자 {_WORDS[p.sms]}", f"카카오톡 {_WORDS[p.kakao]}", f"전화 {_WORDS[p.call]}",
             "시험 모드 켜짐" if p.test_mode else "시험 모드 꺼짐"]
    if not p.ready:
        parts.append("연결 확인 전")
    return "- 알림: " + " · ".join(parts)
