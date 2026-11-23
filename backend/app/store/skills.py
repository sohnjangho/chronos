"""워크플로우 → 스킬 저장 및 매칭(베테랑 노하우 재실행).

- 맞추기: 스킬 이름이 요청에 들어 있으면 3점, 찾는 말 하나에 1점. MIN_SCORE 점 이상인 것 가운데 가장 높은 것.
  흔한 말(COMMON_WORDS 로 시작하는 말)과 숫자로 시작하는 말(3일·16주)은 점수에 넣지 않는다 — 관계없는 요청에 붙지 않게.
- 붙은 스킬의 도구 순서는 참고만 한다. 기록·저장·제출 도구는 사용자가 이번에 요청했을 때만 부른다(skill_prompt_block).
- 저장할 때 단계를 정리한다: 질문지·창 열기(SKIPPED_TOOLS)는 빼고, 연달아 같은 도구는 한 번으로.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.store.tables import SkillRow, WorkflowRun, WorkflowStep

MIN_SCORE = 3
# 거의 모든 요청에 나오는 말(이 말로 시작하는 낱말: 영향을·지연됐어·늦어졌어·계산해서 …)
COMMON_WORDS = ("영향", "지연", "일정", "계산", "알려", "때문", "늦어", "확인", "분석", "정리", "보여", "해줘")
SKIPPED_TOOLS = frozenset({"ask.questionnaire", "ui.open_window"})  # 스킬 단계로 저장하지 않는 도구


def _counts(word: str) -> bool:
    """찾는 말로 점수에 드는가: 두 글자 이상, 숫자로 시작하지 않고 흔한 말로 시작하지 않는다."""
    return len(word) >= 2 and not word[0].isdigit() and not word.startswith(COMMON_WORDS)


def _default_triggers(name: str, request: str) -> list[str]:
    words = [w.strip(".,!?\"'()[]") for w in f"{name} {request}".split()]
    out: list[str] = []
    for w in words:
        if _counts(w) and w not in out:
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
    kept = _kept_steps(steps)
    if not kept:
        raise ApiError(422, "empty_workflow", "도구 단계가 없는 실행은 스킬로 저장할 수 없습니다.")
    cleaned_triggers = [t.strip() for t in (triggers or []) if t.strip()]
    if not cleaned_triggers:
        cleaned_triggers = _default_triggers(name, run.request)
    row = SkillRow(
        name=name.strip()[:80],
        description=(description.strip() or run.title)[:240],
        triggers_json=cleaned_triggers,
        steps_json=kept,
        source_run_id=run.id,
        created_by=user_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _kept_steps(steps: list[WorkflowStep]) -> list[dict]:
    """질문지·창 열기를 빼고, 연달아 같은 도구는 첫 번째 것 하나로."""
    out: list[dict] = []
    for s in steps:
        if s.tool in SKIPPED_TOOLS or (out and out[-1]["tool"] == s.tool):
            continue
        out.append({"tool": s.tool, "why": s.why})
    return out


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
            if _counts(k) and k in q:
                score += 1
        if score >= MIN_SCORE and (best is None or score > best[0]):
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
        "- 요청이 같은 일일 때만 참고한다. 이 스킬 순서 때문에 기록 도구를 부르지는 않는다 — 부를지는 지시문과 이번 요청으로 정한다.",
        "- 참고할 도구 순서(상황에 맞게 인자를 채운다):",
    ]
    for i, step in enumerate(skill.steps_json or [], 1):
        why = f" — {step['why']}" if step.get("why") else ""
        lines.append(f"  {i}. `{step['tool']}`{why}")
    return "\n".join(lines)
