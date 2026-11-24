"""당김 효과 장면 찾기: 「5층 사무동 신축」 버전 2 에서 골조(WBS 2.x) 작업의 기간을 n(1..5)일 줄여 준공이 얼마나 당겨지는지 본다.

임시 DB 에만 씨앗을 만든다. 규칙은 core/shorten.py 와 같다(실적 있는 것 제외, od 최소 1, apply_moves → level(shift=True)).
실행: cd backend && PYTHONPATH=. uv run python scripts/find_accel_case.py
"""

import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.calendar import WorkCalendar
from app.core.cpm import compute
from app.core.resources import level
from app.core.shorten import Move, apply_moves
from app.harness.assemble import prepare_stored
from app.seed.office import office_building
from app.store.schedules import load
from app.store.tables import Base

EXTERIOR = ("커튼월", "외장", "창호", "외벽")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_engine(f"sqlite:///{Path(tmp) / 'demo.db'}")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            sid = office_building(session)
            session.commit()
            schedule, conditions, n = load(session, sid, 2)
        engine.dispose()
    ready = prepare_stored(schedule, conditions)
    cal = WorkCalendar(ready.calendar)
    base = level(ready, compute(ready), shift=True)
    names = {a.id: a.name for a in ready.activities}
    print(f"버전 {n}, 준공 {base.finish}")
    print("id | name | od | n | finish_gain | 이어지는 크리티컬(위상 순, 만진 작업 제외) | 외장 계열")
    for a in ready.activities:
        if a.kind != "task" or not a.wbs.startswith("2.") or a.actual_start or a.actual_finish:
            continue
        for k in range(1, 6):
            if a.od - k < 1:
                break
            moved = apply_moves(ready, [Move(f"cmp:{a.id}", "compress", (a.id,), "", od=a.od - k)])
            lv = level(moved, compute(moved), shift=True)
            gain = cal.workdays_between(lv.finish, base.finish)
            chain = [names[i] for i in lv.cpm.critical_path if i != a.id]
            ext = "Y" if any(any(w in c for w in EXTERIOR) for c in chain) else "-"
            print(f"{a.id} | {a.name} | {a.od} | {k} | {gain} | {' > '.join(chain)} | {ext}")


if __name__ == "__main__":
    main()
