"""도구 등록부: 등록·목록·LLM 형식·부르기."""

import logging
import re

import pytest
from pydantic import BaseModel, ConfigDict, create_model

from app.tools import registry
from app.tools.context import ToolContext, ToolError
from app.tools.registry import (
    ToolResult,
    as_llm_tools,
    call,
    from_llm_name,
    list_tools,
    set_enabled,
    to_llm_name,
    tool,
)
from tests.tool_doubles import Empty, SpyIn, SpyOut, registered

# ── 작업 지시서의 시험 ──────────────────────────────────────────────


async def test_bad_args_are_rejected_before_running(ctx, spy_tool):
    r = await call("spy", {"n": "not-int"}, ctx); assert r.ok is False and "입력 형식" in r.error and spy_tool.calls == 0
async def test_unknown_tool(ctx): assert (await call("nope", {}, ctx)).ok is False
async def test_tool_exception_is_contained(ctx, boom_tool): assert (await call("boom", {}, ctx)).ok is False
def test_as_llm_tools_shape(): assert all(t["type"] == "function" and "parameters" in t["function"] for t in as_llm_tools())


# ── 덧붙인 시험 ─────────────────────────────────────────────────────

FIRST_TOOLS = {"schedule.read", "calc.cpm", "ui.open_window"}


def test_load_all_finds_the_first_three_tools():
    registry.load_all()
    registry.load_all()  # 두 번 불러도 같은 이름 오류가 나지 않는다
    assert FIRST_TOOLS <= {t.name for t in list_tools()}


def test_spec_is_built_from_the_function(spy_tool):
    spec = next(t for t in list_tools() if t.name == "spy")
    assert (spec.description, spec.input_model, spec.output_model) == ("시험용 도구", SpyIn, SpyOut)
    assert (spec.program, spec.mutates, spec.enabled) == (None, False, True)


def test_program_and_mutates_are_kept():
    def run(args: Empty, ctx: ToolContext) -> Empty:
        return Empty()

    with registered("temp.write", run, program="schedule", mutates=True):
        spec = next(t for t in list_tools() if t.name == "temp.write")
        assert (spec.program, spec.mutates) == ("schedule", True)
    assert "temp.write" not in {t.name for t in list_tools(enabled_only=False)}


def test_duplicate_name_raises(spy_tool):
    def run(args: Empty, ctx: ToolContext) -> Empty:
        return Empty()

    with pytest.raises(ValueError, match="spy"):
        tool("spy", "또 등록")(run)


@pytest.mark.parametrize("name", ["a__b", "A.b", "a b", "", ".a", "a.", "a-b"])
def test_bad_tool_name_raises(name):
    def run(args: Empty, ctx: ToolContext) -> Empty:
        return Empty()

    with pytest.raises(ValueError):
        tool(name, "이름이 틀림")(run)
    assert name not in {t.name for t in list_tools(enabled_only=False)}


@pytest.mark.parametrize("extra", [None, "ignore", "allow"])
def test_input_model_must_forbid_unknown_fields(extra):
    config = ConfigDict(extra=extra) if extra else ConfigDict()
    loose = create_model("Loose", __config__=config, n=(int, 0))

    def run(args: loose, ctx: ToolContext) -> SpyOut:
        return SpyOut(n=args.n)

    with pytest.raises(TypeError, match="extra"):
        tool("temp.loose", "모르는 칸을 받음")(run)
    assert "temp.loose" not in {t.name for t in list_tools(enabled_only=False)}


def test_function_without_models_raises():
    def run(args: dict, ctx: ToolContext) -> dict:
        return {}

    with pytest.raises(TypeError):
        tool("temp.untyped", "모델 없음")(run)


def test_as_llm_tools_entries(spy_tool):
    entries = {t["function"]["name"]: t for t in as_llm_tools()}
    assert {"schedule__read", "calc__cpm", "ui__open_window", "spy"} <= set(entries)
    assert all(re.fullmatch(r"[a-zA-Z0-9_-]+", name) for name in entries)
    spy = entries["spy"]["function"]
    assert spy["description"] == "시험용 도구" and spy["parameters"] == SpyIn.model_json_schema()
    window = entries["ui__open_window"]["function"]["parameters"]
    assert window["required"] == ["program"] and set(window["properties"]) == {"program", "params"}


def test_name_mapping_both_ways():
    for t in list_tools():
        assert from_llm_name(to_llm_name(t.name)) == t.name
    assert to_llm_name("schedule.read") == "schedule__read"
    assert from_llm_name("ui__open_window") == "ui.open_window"


async def test_disabled_tool_is_not_listed_or_run(ctx, spy_tool):
    set_enabled("spy", False)
    assert "spy" not in {t.name for t in list_tools()}
    assert "spy" in {t.name for t in list_tools(enabled_only=False)}
    assert "spy" not in {t["function"]["name"] for t in as_llm_tools()}
    r = await call("spy", {"n": 1}, ctx)
    assert (r.ok, r.error, r.output) == (False, "꺼져 있는 도구입니다: spy", None) and spy_tool.calls == 0
    set_enabled("spy", True)
    assert (await call("spy", {"n": 1}, ctx)).ok is True


def test_set_enabled_unknown_tool_raises():
    with pytest.raises(KeyError):
        set_enabled("nope", False)


async def test_unknown_tool_message(ctx):
    r = await call("nope", {}, ctx)
    assert r == ToolResult(ok=False, output=None, error="없는 도구입니다: nope", ms=r.ms)


async def test_bad_args_message_is_short_and_has_no_input_value(ctx, spy_tool):
    r = await call("spy", {"n": "not-int-SECRET"}, ctx)
    assert r.error.startswith("입력 형식 오류: n: ") and "SECRET" not in r.error and r.output is None
    assert (await call("spy", {}, ctx)).error.startswith("입력 형식 오류: n: ")


async def test_sync_tool_runs_and_output_is_a_dict(ctx, spy_tool):
    r = await call("spy", {"n": 4}, ctx)
    assert (r.ok, r.output, r.error) == (True, {"n": 4}, None) and spy_tool.calls == 1
    assert isinstance(r.ms, int) and r.ms >= 0


async def test_async_tool_is_awaited(ctx):
    async def run(args: SpyIn, ctx: ToolContext) -> SpyOut:
        return SpyOut(n=args.n * 2)

    with registered("temp.double", run):
        assert (await call("temp.double", {"n": 4}, ctx)).output == {"n": 8}


async def test_tool_may_return_a_dict_that_fits_the_output_model(ctx):
    def run(args: SpyIn, ctx: ToolContext) -> SpyOut:
        return {"n": args.n}

    with registered("temp.dict", run):
        assert (await call("temp.dict", {"n": 4}, ctx)).output == {"n": 4}


async def test_exception_message_is_hidden_but_logged(ctx, boom_tool, caplog):
    caplog.set_level(logging.ERROR)
    r = await call("boom", {}, ctx)
    assert (r.ok, r.output, r.error) == (False, None, "도구 실행 중 오류: RuntimeError")
    assert "Traceback" in caplog.text and "boom" in caplog.text


async def test_wrong_output_is_contained(ctx):
    def run(args: Empty, ctx: ToolContext) -> SpyOut:
        return {"n": "x"}

    with registered("temp.badout", run):
        r = await call("temp.badout", {}, ctx)
    assert r.ok is False and r.error == "도구 실행 중 오류: ValidationError"


async def test_tool_error_message_is_passed_through(ctx):
    class Out(BaseModel):
        ok: bool

    async def run(args: Empty, ctx: ToolContext) -> Out:
        raise ToolError("그 창은 열 수 없습니다.")

    with registered("temp.refuse", run):
        r = await call("temp.refuse", {}, ctx)
    assert (r.ok, r.output, r.error) == (False, None, "그 창은 열 수 없습니다.")


class OptionalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int = 1


@pytest.mark.parametrize("arguments", [None, [1], "{}"], ids=["none", "list", "string"])
async def test_arguments_that_are_not_an_object_are_rejected_before_running(ctx, arguments):
    ran = []

    def run(args: OptionalIn, ctx: ToolContext) -> SpyOut:  # 칸이 모두 선택이라 {} 면 돈다
        ran.append(args)
        return SpyOut(n=args.n)

    with registered("temp.optional", run):
        r = await call("temp.optional", arguments, ctx)
    assert (r.ok, r.output, r.error) == (False, None, "입력 형식 오류: 인자가 JSON 객체가 아닙니다.")
    assert ran == []
