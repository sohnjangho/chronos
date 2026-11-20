"""작업 공간 설정(settings 표: key → value). 지금은 승인 수준(approval_mode) 하나다."""

from sqlalchemy.orm import Session

from app.store.tables import Setting

APPROVAL_MODE = "approval_mode"
DEFAULT_APPROVAL_MODE = "important"  # all | important | auto (app.agent.approval.Mode)


def approval_mode(session: Session) -> str:
    """지금 승인 수준. 정한 적이 없으면 important."""
    row = session.get(Setting, APPROVAL_MODE)
    return row.value if row is not None else DEFAULT_APPROVAL_MODE


def set_approval_mode(session: Session, mode: str) -> None:
    """승인 수준을 바꾸고 commit 한다. 값 확인은 부르는 쪽(API 의 요청 모델)이 한다."""
    row = session.get(Setting, APPROVAL_MODE)
    if row is None:
        session.add(Setting(key=APPROVAL_MODE, value=mode))
    else:
        row.value = mode
    session.commit()
