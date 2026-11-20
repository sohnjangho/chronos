"""조건 변경을 사람이 읽는 한국어로: 승인 건 제목·요청 글, 에이전트에게 보낼 요청 글.

조건 변화 줄은 승인 판단(app.agent.approval.assess)이 만든 summary["conditions_changed"]
([{id, name, before, after}], 켜진 조건 기준)를 그대로 읽는다. 날짜·위반은 코드가 계산한 값이다.
"""

from datetime import date

from app.harness.checks import Violation

TITLE_LIMIT = 100  # approvals.title, chat_sessions.title 칸 길이
REQUEST_LIMIT = 200  # approvals.request (store.approvals.REQUEST_LIMIT 와 같다)
SHOWN_VIOLATIONS = 5


def change_line(row: dict, with_id: bool = False) -> str:
    """'타워크레인: 1대 → 2대' · '준공 기한: 적용 안 함' · '35일 이하: 새로 적용'."""
    name = row["name"] or row["id"]
    label = f"{name}({row['id']})" if with_id else name
    before, after = row["before"], row["after"]
    if before is not None and after is not None:
        return f"{label}: {before} → {after}"
    if after is None:
        return f"{label}: 적용 안 함" + ("" if before in (None, name) else f" (전: {before})")
    return f"{label}: 새로 적용" + ("" if after == name else f" ({after})")


def approval_title(rows: list[dict]) -> str:
    head = change_line(rows[0]) if rows else "조건 켜고 끄기"
    more = f" 외 {len(rows) - 1}건" if len(rows) > 1 else ""
    return f"조건 바꾸기 — {head}{more}"[:TITLE_LIMIT]


def approval_request(rows: list[dict]) -> str:
    lines = "; ".join(change_line(r) for r in rows) or "조건 켜고 끄기"
    return f"조건·규칙 화면에서 확정: {lines}"[:REQUEST_LIMIT]


def chat_title(schedule_name: str) -> str:
    return f"조건 맞추기 — {schedule_name}"[:TITLE_LIMIT]


def _violation_lines(violations: list[Violation]) -> list[str]:
    lines = [f"- {v.message}" for v in violations[:SHOWN_VIOLATIONS]]
    if len(violations) > SHOWN_VIOLATIONS:
        lines.append(f"- 그 밖에 {len(violations) - SHOWN_VIOLATIONS}건")
    return lines


def agent_request(schedule_name: str, rows: list[dict], finish: tuple[date, date], violations: list[Violation]) -> str:
    """에이전트에게 보낼 요청(대화 입력창에 미리 넣는다). finish = (지금 준공, 바꾼 뒤 준공)."""
    before, after = finish
    if not rows:
        lines = [f"'{schedule_name}' 일정을 지금 조건에 맞게 고쳐 주세요.",
                 f"지금 준공 {after.isoformat()}, 위반 {len(violations)}건입니다."]
    else:
        moved = f"{before.isoformat()} → {after.isoformat()}" if before != after else f"{after.isoformat()}(그대로)"
        lines = [f"'{schedule_name}' 일정의 조건을 아래처럼 바꾸려고 합니다. 이 조건에 맞게 일정을 고쳐 주세요.",
                 *(f"- {change_line(r, with_id=True)}" for r in rows),
                 f"바꾼 조건으로 계산하면 준공 {moved}, 위반 {len(violations)}건입니다."]
    return "\n".join([*lines, *_violation_lines(violations)])
