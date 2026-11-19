"""core 시험이 같이 쓰는 일정 만들기 도우미."""

from datetime import date

from app.core.model import Activity, CalendarSpec, Relation, Resource, Schedule, WbsNode

CAL5 = CalendarSpec(days_per_week=5)


def act(i, od, **k):
    return Activity(id=i, name=i, kind="task", wbs="1", od=od, **k)


def sched(acts, rels, cal=CAL5, start=date(2027, 3, 1)):
    return Schedule(
        start=start,
        calendar=cal,
        wbs=(WbsNode("1", "w", None),),
        activities=tuple(acts),
        relations=tuple(rels),
    )


def big_schedule(chains=4, per_chain=50):
    """정해진 큰 일정: WBS 사슬 4개 × 50개, 사슬 사이 연결, 자원 3개(용량 1~2)."""
    res = (
        Resource("crane", "타워크레인", "대", 1),
        Resource("pump", "펌프카", "대", 2),
        Resource("hoist", "호이스트", "대", 1),
    )
    acts, rels = [], []
    for c in range(chains):
        for k in range(per_chain):
            n = c * per_chain + k
            use = tuple(r.id for j, r in enumerate(res) if (n + j) % 3 == 0 or n % 7 == j)
            acts.append(
                Activity(id=f"W{c}-{k:02d}", name=f"W{c}-{k:02d}", kind="task", wbs=str(c + 1),
                         od=1 + n % 5, resources=use)
            )
            if k:
                rels.append(Relation(f"W{c}-{k - 1:02d}", f"W{c}-{k:02d}", ("FS", "SS")[n % 4 == 0], n % 3))
            if c and k % 5 == 0 and k:  # 앞 사슬의 조금 앞 작업에 걸린다
                rels.append(Relation(f"W{c - 1}-{k - 2:02d}", f"W{c}-{k:02d}", "FS", 0))
    return Schedule(
        start=date(2027, 3, 1),
        calendar=CAL5,
        wbs=tuple(WbsNode(str(c + 1), f"w{c + 1}", None) for c in range(chains)),
        activities=tuple(acts),
        relations=tuple(rels),
        resources=res,
    )
