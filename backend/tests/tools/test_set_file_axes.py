"""도구 files.set_axes(A6-2): 자료함 파일의 5축 분류를 사용자 요청대로 고친다.

HTTP PATCH /api/files/{id}/axes 와 같은 서비스(programs.files.service.patch_axes)·같은 권한(로그인한 누구나).
파일·사람·현장은 모두 가상이다(5층 사무동 신축 · A현장).
"""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select

from app.security.passwords import hash_password
from app.store import files
from app.store.tables import AxisValue, FileAxis, FileRow, User
from app.tools.registry import call, list_tools


def put(session, name: str = "동절기_콘크리트_시방서.pdf", **fields) -> int:
    admin = session.scalars(select(User).where(User.login_id == "admin")).one()
    row = FileRow(sha256=hashlib.sha256(name.encode()).hexdigest(), name=name, ext="pdf", kind="pdf", size=10,
                  status="classified", uploaded_by=admin.id, **fields)
    session.add(row)
    session.commit()
    return row.id


def test_set_axes_is_registered_as_a_mutating_tool():
    spec = {t.name: t for t in list_tools()}["files.set_axes"]
    assert spec.mutates and spec.description


async def test_sets_only_the_given_axes(session, ctx):
    fid = put(session)
    session.add(FileAxis(file_id=fid, axis="현장", value="A현장"))
    session.commit()
    r = await call("files.set_axes", {"file_id": fid, "axes": {"종류": ["시방서"], "공종": [" 골조 ", "골조", "콘크리트"]}},
                   ctx)
    assert r.ok, r.error
    assert r.output == {"file_id": fid, "name": "동절기_콘크리트_시방서.pdf",
                        "axes": {"공종": ["골조", "콘크리트"], "종류": ["시방서"], "현장": ["A현장"]}}
    assert files.axes_of(session, fid) == r.output["axes"]  # 보낸 축만 바뀌고 「현장」은 그대로
    assert session.get(AxisValue, ("종류", "시방서")).is_new is False  # 사람이 고른 값(HTTP 와 같다)


async def test_an_empty_list_clears_that_axis(session, ctx):
    fid = put(session)
    session.add(FileAxis(file_id=fid, axis="출처", value="협력사"))
    session.commit()
    r = await call("files.set_axes", {"file_id": fid, "axes": {"출처": []}}, ctx)
    assert r.ok, r.error
    assert r.output["axes"] == {} and files.axes_of(session, fid) == {}


async def test_any_signed_in_user_may_set_axes_like_the_http_patch(session, ctx):
    user = User(login_id="field1", name="현장 사용자", role="user", password_hash=hash_password("user-pass"))
    session.add(user)
    session.commit()
    fid = put(session)
    r = await call("files.set_axes", {"file_id": fid, "axes": {"시기": ["2026-11"]}}, replace(ctx, user=user))
    assert r.ok, r.error
    assert r.output["axes"] == {"시기": ["2026-11"]}


async def test_without_a_signed_in_user_nothing_changes(session, ctx):
    fid = put(session)
    r = await call("files.set_axes", {"file_id": fid, "axes": {"종류": ["시방서"]}}, replace(ctx, user=None))
    assert not r.ok and r.error == "로그인한 사람만 파일 분류를 고칠 수 있습니다."
    assert files.axes_of(session, fid) == {}


async def test_unknown_and_deleted_files_are_refused_in_korean(session, ctx):
    gone = put(session, "지운_시방서.pdf", deleted_at=datetime.now(UTC))
    missing = await call("files.set_axes", {"file_id": 999, "axes": {"종류": ["시방서"]}}, ctx)
    deleted = await call("files.set_axes", {"file_id": gone, "axes": {"종류": ["시방서"]}}, ctx)
    assert (missing.ok, missing.error) == (False, "파일을 찾을 수 없습니다.")
    assert (deleted.ok, deleted.error) == (False, "지워진 파일입니다")
    assert session.scalars(select(FileAxis)).all() == []


async def test_unknown_axis_or_no_axis_is_an_input_error(session, ctx):
    fid = put(session)
    unknown = await call("files.set_axes", {"file_id": fid, "axes": {"층": ["5층"]}}, ctx)
    empty = await call("files.set_axes", {"file_id": fid, "axes": {}}, ctx)
    assert not unknown.ok and unknown.error.startswith("입력 형식 오류: axes.층")
    assert not empty.ok and empty.error.startswith("입력 형식 오류: axes")


async def test_value_limits_come_back_as_korean_errors(session, ctx):
    fid = put(session)
    long = await call("files.set_axes", {"file_id": fid, "axes": {"종류": ["가" * 101]}}, ctx)
    many = await call("files.set_axes", {"file_id": fid, "axes": {"공종": [f"공종{i}" for i in range(11)]}}, ctx)
    assert (long.ok, long.error) == (False, "값은 100자까지 쓸 수 있습니다.")
    assert (many.ok, many.error) == (False, "한 축에 값은 10개까지 넣을 수 있습니다.")
    assert files.axes_of(session, fid) == {}
