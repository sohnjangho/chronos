"""도구 시험용 도우미: 시험 안에서만 쓰는 도구를 잠깐 등록한다."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from pydantic import BaseModel, ConfigDict

from app.tools import registry


class SpyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int


class SpyOut(BaseModel):
    n: int


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


@contextmanager
def registered(
    name: str,
    fn: Callable,
    *,
    description: str = "시험용 도구",
    program: str | None = None,
    mutates: bool = False,
) -> Iterator[Callable]:
    """with registered("spy", fn): ... — 블록을 나가면 등록부에서 지운다."""
    registry.tool(name, description, program=program, mutates=mutates)(fn)
    try:
        yield fn
    finally:
        registry.unregister(name)
