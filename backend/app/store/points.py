"""버전별 관리 포인트(management_points): (일정, 버전) 한 줄에 그 버전의 포인트 목록(core.points.Point)을 JSON 으로.

계산·차이는 app.points.service 가 한다. 표는 app.db 가 import 해서 create_all 전에 Base 에 올린다.
"""

from datetime import UTC, date, datetime

from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.points import Point
from app.store.tables import Base
from app.store.tables_outreach import UtcDateTime


class ManagementPoints(Base):
    __tablename__ = "management_points"

    schedule_id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    points_json: Mapped[list[dict]] = mapped_column(JSON)
    computed_at: Mapped[datetime] = mapped_column(UtcDateTime)


def _to_json(p: Point) -> dict:
    return {"activity_id": p.activity_id, "name": p.name, "critical": p.critical, "tf": p.tf,
            "es": p.es.isoformat(), "ef": p.ef.isoformat()}


def _from_json(d: dict) -> Point:
    return Point(d["activity_id"], d["name"], d["critical"], d["tf"], date.fromisoformat(d["es"]),
                 date.fromisoformat(d["ef"]))


def get(session: Session, schedule_id: int, version: int) -> tuple[Point, ...] | None:
    """저장한 적이 없으면 None."""
    row = session.get(ManagementPoints, (schedule_id, version))
    return None if row is None else tuple(_from_json(d) for d in row.points_json)


def put(session: Session, schedule_id: int, version: int, points: tuple[Point, ...]) -> None:
    """덮어쓴다. flush·commit 은 부른 쪽."""
    data, now = [_to_json(p) for p in points], datetime.now(UTC)
    row = session.get(ManagementPoints, (schedule_id, version))
    if row is None:
        session.add(ManagementPoints(schedule_id=schedule_id, version=version, points_json=data, computed_at=now))
    else:
        row.points_json, row.computed_at = data, now
