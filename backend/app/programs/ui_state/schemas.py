"""화면 상태의 모양(frontend/src/os/layoutMemory.ts 와 같게). 프로그램 id 는 ui.open_window 의 목록, 숫자·글은 길이를 묶고
글은 탭 이름 꼴(영문 소문자·붙임표)만 — 자유 글·번호는 들어갈 칸이 없다."""

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.tools.ui.open_window import Program

Mode = Literal["desktop", "tablet", "phone", "appearance"]

_NUM = re.compile(r"[1-9]\d{0,6}")  # 일정·연락처·대화·실행 id(7자리까지 — 가장 짧은 전화번호 8자리보다 짧다)
_NAME = re.compile(r"[a-z][a-z-]{0,30}")  # 탭·구역·보기 이름
_NUM_KEYS = {"id", "contact", "session", "run"}
ParamKey = Literal["id", "contact", "session", "run", "tab", "view", "section"]


def _check_params(params: dict[str, str]) -> dict[str, str]:
    for key, value in params.items():
        pattern = _NUM if key in _NUM_KEYS else _NAME
        if not pattern.fullmatch(value):
            raise ValueError(f"{key} 값의 꼴이 맞지 않습니다.")
    return params


Params = Annotated[dict[ParamKey, str], Field(max_length=7), AfterValidator(_check_params)]
_STRICT = ConfigDict(extra="forbid", strict=True)
Coord = Annotated[int, Field(ge=-20000, le=20000)]
Size = Annotated[int, Field(ge=0, le=20000)]


class DesktopWin(BaseModel):
    model_config = _STRICT

    program: Program
    x: Coord
    y: Coord
    w: Size
    h: Size
    min: bool
    max: bool
    params: Params | None = None


class DesktopState(BaseModel):
    model_config = _STRICT

    v: Literal[1]
    wins: Annotated[list[DesktopWin], Field(max_length=40)]
    deactivated: bool


class TabletState(BaseModel):
    model_config = _STRICT

    v: Literal[1]
    active: Program | Literal["field"]
    params: Params | None = None


class PhoneState(BaseModel):
    model_config = _STRICT

    v: Literal[1]
    tab: Literal["chat", "schedule", "approvals", "contacts", "more"]
    sub: Literal["schedule-table", "gantt", "progress", "delays", "field"]
    more: Program | None = None
    params: Params | None = None


class AppearanceState(BaseModel):
    """바탕화면 배경(frontend/src/os/wallpapers.ts 의 WALLPAPER_IDS·FITS 와 같게). 기기 형태와 상관없이 하나."""

    model_config = _STRICT

    v: Literal[1]
    wallpaper: Literal[
        "default", "prism-schedule", "orbits", "contours", "drafting-grid", "sculpt-mono", "chronos-sky",
        "minimal-warm", "minimal-cool", "photo",
    ]
    fit: Literal["fill", "fit", "stretch", "tile", "center"]


MODELS: dict[str, type[BaseModel]] = {
    "desktop": DesktopState,
    "tablet": TabletState,
    "phone": PhoneState,
    "appearance": AppearanceState,
}
