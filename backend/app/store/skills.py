"""워크플로우 → 스킬 저장 및 매칭(베테랑 노하우 재실행)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.store.tables import SkillRow, WorkflowRun, WorkflowStep


def _default_triggers(name: str, request: str) -> list[str]:
    words = [w.strip(".,!?\"'()[]") for w in f"{name} {request}".split()]
    out: list[str] = []
    for w in words:
        if len(w) >= 2 and w not in out:
            out.append(w)
        if len(out) >= 6:
            break
    return out


def create_from_run(
    session: Session,
    *,
    run_id: int,
    user_id: int,
    name: str,
    description: str = "",
    triggers: list[str] | None = None,
) -> SkillRow:
    run = session.get(WorkflowRun, run_id)
    if run is None:
        raise ApiError(404, "not_found", "워크플로우 실행을 찾을 수 없습니다.")
    steps = list(
        session.scalars(select(WorkflowStep).where(WorkflowStep.run_id == run_id).order_by(WorkflowStep.n))
    )
    if not steps:
        raise ApiError(422, "empty_workflow", "도구 단계가 없는 실행은 스킬로 저장할 수 없습니다.")
    cleaned_triggers = [t.strip() for t in (triggers or []) if t.strip()]
    if not cleaned_triggers:
        cleaned_triggers = _default_triggers(name, run.request)
    row = SkillRow(
        name=name.strip()[:80],
        description=(description.strip() or run.title)[:240],
        triggers_json=cleaned_triggers,
        steps_json=[{"tool": s.tool, "why": s.why} for s in steps],
        source_run_id=run.id,
        created_by=user_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_skills(session: Session) -> list[SkillRow]:
    return list(session.scalars(select(SkillRow).order_by(SkillRow.use_count.desc(), SkillRow.id.desc())))


def delete_skill(session: Session, skill_id: int) -> None:
    row = session.get(SkillRow, skill_id)
    if row is None:
        raise ApiError(404, "not_found", "스킬을 찾을 수 없습니다.")
    session.delete(row)
    session.commit()


def match_skill(session: Session, text: str) -> SkillRow | None:
    """사용자 요청과 트리거 키워드(또는 스킬 이름)가 가장 잘 맞는 스킬 하나를 고른다."""
    q = (text or "").strip().lower()
    if len(q) < 2:
        return None
    best: tuple[int, SkillRow] | None = None
    for skill in list_skills(session):
        score = 0
        if skill.name.lower() in q:
            score += 3
        for kw in skill.triggers_json or []:
            k = str(kw).strip().lower()
            if len(k) >= 2 and k in q:
                score += 1
        if score >= 2 and (best is None or score > best[0]):
            best = (score, skill)
    return best[1] if best else None


def record_use(session: Session, skill_id: int) -> None:
    row = session.get(SkillRow, skill_id)
    if row is not None:
        row.use_count += 1


def skill_prompt_block(skill: SkillRow) -> str:
    """매칭된 스킬의 검증된 도구 순서를 시스템 지시문 끝에 붙인다."""
    lines = [
        f"## 매칭된 스킬: {skill.name}",
        f"- 설명: {skill.description}",
        "- 아래 검증된 도구 순서를 우선 따라 실행한다(상황에 맞게 인자를 채운다):",
    ]
    for i, step in enumerate(skill.steps_json or [], 1):
        why = f" — {step['why']}" if step.get("why") else ""
        lines.append(f"  {i}. `{step['tool']}`{why}")
    return "\n".join(lines)
