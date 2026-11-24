"""내 사진 배경(사람마다 한 장) — 바이트·형식·가로세로만 둔다(파일 이름·경로·EXIF 따로 두지 않는다).

새로 올리면 덮어쓴다. FK 는 두지 않는다(ui_states 와 같이): 계정보다 오래된 줄은 내보내지 않아, 지운 계정의 id 를
새 계정이 다시 받아도 앞 사람 사진이 보이지 않는다. app.db 가 import 해서 create_all 이 표를 만든다.
"""

from datetime import UTC, datetime

from sqlalchemy import LargeBinary, String
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.store.tables import Base, User
from app.store.timeutil import as_utc


class UserWallpaper(Base):
    __tablename__ = "user_wallpapers"

    user_id: Mapped[int] = mapped_column(primary_key=True)
    mime: Mapped[str] = mapped_column(String(16))  # image/jpeg | image/png | image/webp
    width: Mapped[int]
    height: Mapped[int]
    data: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


def get(session: Session, user: User) -> UserWallpaper | None:
    row = session.get(UserWallpaper, user.id)
    if row is None or as_utc(row.updated_at) < as_utc(user.created_at):
        return None
    return row


def put(session: Session, user: User, mime: str, width: int, height: int, data: bytes) -> str:
    """덮어쓴다(한 문장 upsert). 서버 시각 updated_at 을 돌려준다."""
    now = datetime.now(UTC)
    stmt = sqlite_insert(UserWallpaper).values(
        user_id=user.id, mime=mime, width=width, height=height, data=data, updated_at=now
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[UserWallpaper.user_id],
        set_={"mime": mime, "width": width, "height": height, "data": data, "updated_at": now},
    )
    session.execute(stmt)
    session.commit()
    return as_utc(now).isoformat()


def delete(session: Session, user: User) -> None:
    row = session.get(UserWallpaper, user.id)
    if row is not None:
        session.delete(row)
        session.commit()
