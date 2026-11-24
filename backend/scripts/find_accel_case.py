"""당김 효과 장면 찾기: 「5층 사무동 신축」 버전 2(기본) 또는 3 에서 골조(WBS 2.x) 작업의 기간을 n(1..5)일 줄여 준공이
얼마나 당겨지는지 본다.

임시 DB 에만 씨앗을 만든다. 규칙은 core/shorten.py 와 같다(실적 있는 것 제외, od 최소 1, apply_moves → level(shift=True)).
--delay ID:일수 = 먼저 그 지연을 넣은 일정에서 잰다(delay.insert_delay). --combo ID=od,ID=od = 여러 작업을 한꺼번에 줄인 줄 하나를
더한다. --shorten n = 그 일정의 만회안(core.shorten, 목표 n 근무일)도 보인다.
실행: cd backend && PYTHONPATH=. uv run python scripts/find_accel_case.py [--version 3] [--delay A1402:3] [--combo A1250=1,A1252=2]
"""

import argparse
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.calendar import WorkCalendar
from app.core.cpm import compute
from app.core.delay import DelayEvent, insert_delay
from app.core.resources import level
from app.core.shorten import Move, apply_moves, shorten
from app.harness.assemble import prepare_stored
from app.seed.office import office_building
from app.store.schedules import load
from app.store.tables import Base

EXTERIOR = ("커튼월", "외장", "창호", "외벽")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, choices=(2, 3), default=2)
    parser.add_argument("--delay", help="ID:일수")
    parser.add_argument("--combo", help="ID=od,ID=od")
    parser.add_argument("--shorten", type=int)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_engine(f"sqlite:///{Path(tmp) / 'demo.db'}")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            sid = office_building(session, v3=args.version == 3)
            session.commit()
            schedule, conditions, n = load(session, sid, args.version)
        engine.dispose()
    ready = prepare_stored(schedule, conditions)
    cal = WorkCalendar(ready.calendar)
    base = level(ready, compute(ready), shift=True)
    if args.delay:
        aid, days = args.delay.split(":")
        ready, _ = insert_delay(ready, DelayEvent("E1", aid, base.dates[aid][0], int(days)))
        before = base.finish
        base = level(ready, compute(ready), shift=True)
        print(f"버전 {n}, 준공 {before} → 지연 {aid} +{days}일 넣은 뒤 준공 {base.finish}")
    else:
        print(f"버전 {n}, 준공 {base.finish}")
    names = {a.id: a.name for a in ready.activities}
    print("id | name | od | n | finish_gain | 이어지는 크리티컬(위상 순, 만진 작업 제외) | 외장 계열")

    def row(label: str, moves: list[Move]) -> None:
        moved = apply_moves(ready, moves)
        lv = level(moved, compute(moved), shift=True)
        gain = cal.workdays_between(lv.finish, base.finish)
        touched = {m.activity_ids[0] for m in moves}
        chain = [names[i] for i in lv.cpm.critical_path if i not in touched]
        ext = "Y" if any(any(w in c for w in EXTERIOR) for c in chain) else "-"
        print(f"{label} | {gain} | {' > '.join(chain)} | {ext}")

    for a in ready.activities:
        if a.kind != "task" or not a.wbs.startswith("2.") or a.actual_start or a.actual_finish:
            continue
        for k in range(1, 6):
            if a.od - k < 1:
                break
            row(f"{a.id} | {a.name} | {a.od} | {k}", [Move(f"cmp:{a.id}", "compress", (a.id,), "", od=a.od - k)])
    if args.combo:
        ods = {a.id: a.od for a in ready.activities}
        pairs = [(i, int(od)) for i, od in (p.split("=") for p in args.combo.split(","))]
        row(f"{'+'.join(i for i, _ in pairs)} | {'+'.join(names[i] for i, _ in pairs)} | "
            f"{'+'.join(str(ods[i]) for i, _ in pairs)} | {sum(ods[i] - od for i, od in pairs)}",
            [Move(f"cmp:{i}", "compress", (i,), "", od=od) for i, od in pairs])
    if args.shorten:
        result = shorten(ready, target=args.shorten)
        print(f"만회안(목표 {args.shorten}일, 기준 준공 {result.base_finish}):")
        for p in result.packages:
            print(f"  {p.key} {p.name} | 준공 {p.finish} | 이득 {p.gain} | " + " · ".join(m.text for m in p.moves))


if __name__ == "__main__":
    main()
