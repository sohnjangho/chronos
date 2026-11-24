"""시연 짝 찾기: 씨앗 「5층 사무동 신축」 버전 2(실적 포함, 기본) 또는 3(6월 말 실적·조달 줄)에서 끝나지 않은 task 마다
같은 3일 지연을 넣어 본다.

임시 폴더의 임시 DB 에만 씨앗을 만든다(실제 data/ 를 건드리지 않는다). 설정 기본값(k, w)은 store.settings 와 같다.
실행: cd backend && PYTHONPATH=. uv run python scripts/find_demo_pair.py [k w] [--version 3]
"""

import argparse
import re
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.cpm import compute
from app.core.delay import DelayEvent, analyze, insert_delay
from app.core.points import compute_points, diff_points
from app.core.resources import level as level_schedule
from app.harness.assemble import prepare_stored
from app.seed.office import office_building
from app.store.schedules import load
from app.store.settings import _POINTS_INT_BOUNDS
from app.store.tables import Base

DAYS = 3
OUTDOOR = re.compile(r"타설|골조|외벽|방수|토공|터파기|흙막이|잔토|외장|패널|지붕|옥탑|조경|부대 토목|철근|거푸집|기초")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("k", nargs="?", type=int, default=_POINTS_INT_BOUNDS["tf_days"][3])  # 기본은 설정 기본값
    parser.add_argument("w", nargs="?", type=int, default=_POINTS_INT_BOUNDS["window_weeks"][3])
    parser.add_argument("--version", type=int, choices=(2, 3), default=2)
    args = parser.parse_args()
    k, w = args.k, args.w
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_engine(f"sqlite:///{Path(tmp) / 'demo.db'}")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            sid = office_building(session, v3=args.version == 3)
            session.commit()
            schedule, conditions, n = load(session, sid, args.version)
        engine.dispose()
    ready = prepare_stored(schedule, conditions)
    lv = level_schedule(ready, compute(ready), shift=True)
    before = compute_points(ready, lv.cpm, tf_days=k, window_weeks=w)
    print(f"일정 「{schedule.name if hasattr(schedule, 'name') else '5층 사무동 신축'}」 버전 {n}, 지연 {DAYS}일, k={k} w={w}, 기존 포인트 {len(before)}개")
    print(f"Data Date {ready.data_date}, 준공 {lv.finish}, 포인트(id 이름 tf 크리티컬): "
          + "; ".join(f"{p.activity_id} {p.name} {p.tf} {'C' if p.critical else '-'}" for p in before))
    print("id | name | wbs | outdoor | tf | es | finish_delta | critical_added | added(id:tf) | removed | tightened")
    for a in ready.activities:
        if a.kind != "task" or a.actual_finish is not None:
            continue
        row = lv.cpm.rows[a.id]
        ev = DelayEvent("E1", a.id, lv.dates[a.id][0], DAYS)
        impact = analyze(ready, [ev]).impacts[0]
        changed, _ = insert_delay(ready, ev)
        cl = level_schedule(changed, compute(changed), shift=True)
        diff = diff_points(before, compute_points(changed, cl.cpm, tf_days=k, window_weeks=w))
        out = "Y" if OUTDOOR.search(a.name) else "-"
        print(
            f"{a.id} | {a.name} | {a.wbs} | {out} | {row.tf} | {row.es} | {impact.finish_delta} | "
            f"{','.join(impact.critical_added) or '-'} | {','.join(f'{p.activity_id}:{p.tf}' for p in diff.added) or '-'} | "
            f"{','.join(diff.removed) or '-'} | {','.join(f'{i}:{x}->{y}' for i, x, y in diff.tightened) or '-'}"
        )


if __name__ == "__main__":
    main()
