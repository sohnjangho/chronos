"""화면에서 받은 조건 변경을 저장된 조건 목록(dict)에 넣는다. 저장은 하지 않는다.

겹마다 바꿀 수 있는 것:
- 기본 규칙(base): 못 바꿈(422).
- 분야 규칙(domain): 켜고 끄기만, 관리자만(일반 사용자는 403). params 는 못 바꿈(422).
- 내 규칙(mine): 값·켜짐은 못 바꿈(422). 내 규칙 목록의 [이 일정에 넣기]로 더할 수는 있다(source 「내 규칙」이고
  저장된 내 규칙의 조건 id 일 때만, Task 35).
- 입력 조건(input): params(지금 params 에 덮어 합침, 형식 검사)·켜짐을 바꾸고, 더하고, 뺀다.
바뀌지 않은 저장 조건 dict 는 받은 그대로 둔다(읽지 못한 dict 도 제자리에 남는다).
값을 바꾸면 조건 글을 새 값으로 다시 만든다(words.condition_text). 값만 바꾸면 켜짐·진 표시는 그대로다
(뒤 겹 조건에 진 조건은 계속 지고, 켜고 끄기를 눌러야 사용자가 정한 켜짐이 된다).
"""

from collections.abc import Sequence

from sqlalchemy.orm import object_session

from app.core.model import Resource
from app.errors import ApiError
from app.harness.conditions import (
    BASE_IDS,
    Condition,
    ConditionFormatError,
    read_conditions,
    validate_params,
)
from app.programs.conditions.schemas import AddChange, Change, EditChange
from app.programs.conditions.words import condition_text
from app.store import my_rules
from app.store.tables import User

MY_RULE_SOURCE = "내 규칙"  # 내 규칙 목록에서 일정에 넣는 조건의 출처


def _invalid(message: str) -> ApiError:
    return ApiError(422, "invalid_change", message)


def _find(entries: list[object], cid: str) -> tuple[int, Condition]:
    """cid 인 마지막 읽을 수 있는 조건의 자리와 조건. 없으면 422."""
    for n in range(len(entries) - 1, -1, -1):
        d = entries[n]
        if isinstance(d, dict) and d.get("id") == cid:
            try:
                return n, Condition.from_dict(d)
            except ConditionFormatError:
                break
    raise _invalid(f"없는 조건입니다: {cid}")


def _edited(c: Condition, change: EditChange, user: User, resources: Sequence[Resource]) -> Condition:
    if c.layer == "mine":
        raise _invalid(f"내 규칙은 이 화면에서 바꿀 수 없습니다: {c.id}")
    if c.layer == "domain":
        if change.params is not None:
            raise _invalid(f"분야 규칙은 켜고 끄기만 할 수 있습니다: {c.id}")
        if user.role != "admin":
            raise ApiError(403, "admin_only", "분야 규칙은 관리자만 켜고 끌 수 있습니다.")
    params = c.params if change.params is None else {**c.params, **change.params}
    if (problem := validate_params(c.kind, params)) is not None:
        raise _invalid(f"{c.id}: {problem}")
    if change.enabled is None:  # 값만 바꿈: 켜짐·진 표시는 그대로(조립이 다시 매긴다)
        enabled, winner = c.enabled, c.overridden_by
    else:  # 사용자가 정한 켜짐
        enabled, winner = change.enabled, None
    text = c.text if params == c.params else (condition_text(c.kind, params, resources) or c.text)
    return Condition(c.id, c.layer, c.kind, params, text, c.source, enabled, winner)


def _added(entries: list[object], change: AddChange, user: User) -> dict:
    try:
        c = Condition.from_dict(change.add)
    except ConditionFormatError as e:
        raise _invalid(f"{e.condition_id}: {e.message}") from None
    if not (c.layer == "input" or (c.layer == "mine" and c.source == MY_RULE_SOURCE)):
        raise _invalid(f"입력 조건만 더할 수 있습니다: {c.id}")
    session = object_session(user)  # 요청의 세션(사용자를 읽은 세션)
    if c.layer == "mine" and (session is None or not my_rules.has_condition(session, c.id)):
        raise _invalid(f"저장된 내 규칙이 아닙니다: {c.id}")
    if c.id in BASE_IDS or any(isinstance(d, dict) and d.get("id") == c.id for d in entries):
        raise _invalid(f"같은 id 의 조건이 이미 있습니다: {c.id}")
    return c.to_dict()


def _removed(entries: list[object], cid: str) -> list[object]:
    _, c = _find(entries, cid)
    if c.layer != "input":
        raise _invalid(f"입력 조건만 뺄 수 있습니다: {cid}")
    return [d for d in entries if not (isinstance(d, dict) and d.get("id") == cid)]


def apply_changes(
    stored: Sequence[object], changes: Sequence[Change], user: User, resources: Sequence[Resource]
) -> list[dict]:
    """차례대로 넣은 새 조건 목록. 할 수 없는 변경이면 ApiError(422 invalid_change, 403 admin_only).

    resources 는 일정의 자원(자원 조건의 글을 다시 만들 때 이름·단위를 쓴다).
    """
    entries = list(stored)
    for change in changes:
        if isinstance(change, AddChange):
            entries.append(_added(entries, change, user))
            continue
        cid = change.id if isinstance(change, EditChange) else change.remove
        if cid in BASE_IDS:
            raise _invalid("기본 규칙은 바꿀 수 없습니다.")
        if isinstance(change, EditChange):
            n, c = _find(entries, cid)
            entries[n] = _edited(c, change, user, resources).to_dict()
        else:
            entries = _removed(entries, cid)
    return entries


def input_only(stored: Sequence[object], changes: Sequence[Change]) -> tuple[list[Change], bool]:
    """(입력 조건에 대한 변경만, 그 밖의 겹(분야 규칙) 변경이 있었는가). apply_changes 로 확인한 변경을 받는다."""
    layers = {c.id: c.layer for c in read_conditions(stored)[0]}
    kept: list[Change] = []
    for change in changes:
        if isinstance(change, AddChange):
            layers[str(change.add.get("id"))] = "input"  # 같은 목록에서 더한 조건을 뒤에서 바꿀 수 있다
        if not isinstance(change, EditChange) or layers.get(change.id) == "input":
            kept.append(change)
    return kept, len(kept) < len(changes)
