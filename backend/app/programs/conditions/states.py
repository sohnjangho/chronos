"""조립한 조건 목록과 점검 보고서 → 겹별 조건 줄과 상태(화면 그대로).

상태: 꺼짐(off: 사용자가 껐거나 뒤 겹 조건에 짐) → 위반(violated) → 통과(passed) → 자동 점검 안 됨(uncheckable).
점검하지 않은 조건(말로 된 조건, 일정이 깨져 건너뛴 조건)은 통과로 세지 않는다.
"""

from app.core.model import Schedule
from app.harness.checks import CheckReport
from app.harness.conditions import Condition, duplicated_later
from app.store.tables import User

UNCHECKED_MESSAGE = "생성할 때 지침으로만 씁니다."
SKIPPED_MESSAGE = "일정을 계산할 수 없어 점검하지 못했습니다."


def _editable(c: Condition, user: User) -> bool | str:
    if c.layer == "input":
        return True
    if c.layer == "domain" and user.role == "admin":
        return "toggle"
    return False


def _used_by(c: Condition, schedule: Schedule) -> list[str] | None:
    """조건이 걸리는 액티비티 id(일정 차례). 자원·꼬리표·마일스톤 조건만, 나머지는 None."""
    p = c.params
    if c.kind == "resource_cap":
        return [a.id for a in schedule.activities if p.get("resource_id") in a.resources]
    tag = p.get("tag") if c.kind == "blocked_period" else p.get("after_tag") if c.kind == "min_gap" else None
    if tag is not None:
        return [a.id for a in schedule.activities if tag in a.tags]
    if c.kind == "milestone_by":
        return [a.id for a in schedule.activities if a.id == p.get("activity_id")]
    return None


def _state(c: Condition, report: CheckReport, texts: dict[str, str]) -> tuple[str, str | None]:
    if not c.enabled:
        if c.overridden_by is None:
            return "off", None
        return "off", f"뒤 겹의 조건을 따릅니다: {texts.get(c.overridden_by) or c.overridden_by}"
    violation = next((v for v in report.violations if v.condition_id == c.id), None)
    if violation is not None:
        return "violated", violation.message
    if c.id in report.passed:
        notice = next((v for v in report.notices if v.condition_id == c.id), None)
        return "passed", notice.message if notice else None
    return "uncheckable", SKIPPED_MESSAGE if c.id in report.skipped else UNCHECKED_MESSAGE


def layers(schedule: Schedule, assembled: list[Condition], report: CheckReport, user: User) -> dict:
    """{base, domain, mine, input: [조건 줄]}. 같은 id 가 뒤에 다시 있는 앞 조건은 빼고(invalid 로 간다)."""
    texts = {c.id: c.text for c in assembled}
    out: dict[str, list[dict]] = {"base": [], "domain": [], "mine": [], "input": []}
    for c, later in zip(assembled, duplicated_later(assembled), strict=True):
        if later:
            continue
        state, message = _state(c, report, texts)
        out[c.layer].append({
            "id": c.id, "layer": c.layer, "kind": c.kind, "params": c.params, "text": c.text, "source": c.source,
            "enabled": c.enabled, "editable": _editable(c, user), "state": state, "message": message,
            "overridden_by": c.overridden_by, "used_by": _used_by(c, schedule),
        })
    return out


def summary(report: CheckReport) -> dict:
    return {
        "passed": len(report.passed),
        "violated": len(report.violations),
        "uncheckable": len(report.uncheckable) + len(report.skipped),
    }
