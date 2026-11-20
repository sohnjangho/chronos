"""씨앗 일정 줄 모양과 액티비티 만들기(일정 모듈들이 같이 쓴다)."""

from app.core.model import Activity, Relation

BY = "시연 자료"

# (id, 이름, WBS, 기간(근무일), 선행 [(id, 관계, lag)], 꼬리표). 선행 글 "A1010" 은 FS lag 0.
Row = tuple[str, str, str, int, tuple, tuple[str, ...]]


def activity(row: Row, uses_of: dict[str, tuple[str, ...]]) -> tuple[Activity, list[Relation]]:
    """줄 하나 → 액티비티와 선행 관계. 기간 0 이면 마일스톤(선행이 없으면 시작, 있으면 종료).
    자원은 꼬리표마다 uses_of 의 자원(겹치면 한 번)."""
    aid, name, wbs, od, preds, tags = row
    kind = "task" if od else ("start_ms" if not preds else "finish_ms")
    uses = dict.fromkeys(r for t in tags for r in uses_of.get(t, ()))
    rels = [Relation(p, aid) if isinstance(p, str) else Relation(p[0], aid, p[1], p[2]) for p in preds]
    return Activity(aid, name, kind, wbs, od, resources=tuple(uses), tags=tags), rels
