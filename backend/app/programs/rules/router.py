from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.programs.rules import service
from app.programs.rules.schemas import DeletedOut, EnabledIn, RuleOut
from app.security.deps import current_user
from app.store.tables import User

# 내 규칙: 로그인한 누구나 본다. 켜고 끄기·지우기는 만든 사람이나 관리자. 만들기는 rules.propose → 승인함.
router = APIRouter(prefix="/api/rules", tags=["rules"], dependencies=[Depends(current_user)])

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


@router.get("")
def list_rules(session: SessionDep, domain: str | None = None, schedule_id: int | None = None) -> list[RuleOut]:
    return service.list_rules(session, domain, schedule_id)


@router.patch("/{rule_id}")
def set_enabled(rule_id: int, body: EnabledIn, session: SessionDep, user: UserDep) -> RuleOut:
    return service.set_enabled(session, rule_id, body, user)


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, session: SessionDep, user: UserDep) -> DeletedOut:
    return service.delete(session, rule_id, user)
