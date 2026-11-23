"""files.set_axes — 자료함 파일의 5축 분류(종류·공종·현장·시기·출처)를 사용자 요청대로 고친다(A6-2).

화면의 PATCH /api/files/{id}/axes 와 같은 서비스(programs.files.service.patch_axes)·같은 권한(로그인한 누구나)이다.
보낸 축만 바꾸고 빈 목록이면 그 축을 비운다. 없는 파일·지운 파일·값 한도(100자·한 축 10개)는 서비스의 한국어 글이
ToolError 가 된다. 사람이 고친 축은 뒤 분류 단계가 덮지 않는다(app.files.classify).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.errors import ApiError
from app.programs.files import service
from app.tools.context import ToolContext, ToolError
from app.tools.registry import tool

LOGIN_NEEDED = "로그인한 사람만 파일 분류를 고칠 수 있습니다."

Axis = Literal["종류", "공종", "현장", "시기", "출처"]


class SetAxesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: int = Field(description="파일 id(「이 대화에 붙인 파일」의 #id, files__search 결과의 file_id)")
    axes: dict[Axis, list[str]] = Field(min_length=1,
                                        description="{축: [값]} — 보낸 축만 바뀐다. 빈 목록이면 그 축을 비운다")


class SetAxesOut(BaseModel):
    file_id: int
    name: str
    axes: dict[str, list[str]]  # 고친 뒤 이 파일의 모든 축


@tool(
    "files.set_axes",
    "자료함 파일의 5축 분류(종류·공종·현장·시기·출처)를 설정하거나 수정한다. 지정한 축만 바뀌고, 빈 목록이면 그 축을 "
    "비운다. 한 축에 값 10개·값 100자까지. 지운 파일은 고칠 수 없다.",
    mutates=True,
)
def set_file_axes(args: SetAxesIn, ctx: ToolContext) -> SetAxesOut:
    if ctx.user is None:
        raise ToolError(LOGIN_NEEDED)
    try:
        out = service.patch_axes(ctx.session, args.file_id, dict(args.axes))
    except ApiError as e:
        raise ToolError(e.message) from None
    return SetAxesOut(file_id=out.file_id, name=out.name, axes=out.axes)
