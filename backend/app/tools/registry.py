"""도구 등록부. 에이전트는 도구를 여기로만 부른다.

도구 모듈은 `@tool("이름", "설명")` 으로 import 될 때 등록된다. 함수 서명은
`(args: 입력모델, ctx: ToolContext) -> 출력모델` 이고 sync·async 둘 다 된다.
입력 모델은 모르는 칸을 거절해야 한다(`ConfigDict(extra="forbid")`). 잘못 쓴 칸 이름이
조용히 버려져 기본값으로 도는 일을 막는다.
이름은 `영역.동작` 꼴(소문자·숫자·밑줄, 점으로 나눔). LLM 에는 점을 __ 로 바꿔 보낸다.
"""

import importlib
import inspect
import logging
import pkgutil
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from pydantic import BaseModel, ValidationError

import app.tools
from app.llm.names import from_llm_name, to_llm_name
from app.tools.context import ToolContext, ToolError

__all__ = [
    "ToolResult",
    "ToolSpec",
    "as_llm_tools",
    "call",
    "from_llm_name",
    "list_tools",
    "load_all",
    "set_enabled",
    "to_llm_name",
    "tool",
    "unregister",
]

logger = logging.getLogger(__name__)

_NAME = re.compile(r"[a-z][a-z0-9]*(_[a-z0-9]+)*(\.[a-z][a-z0-9]*(_[a-z0-9]+)*)*")
_MAX_INPUT_ERRORS = 3
_NOT_AN_OBJECT = "입력 형식 오류: 인자가 JSON 객체가 아닙니다."


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    program: str | None  # 이 도구가 속한 프로그램(없으면 None)
    mutates: bool  # 자료를 바꾸는 도구인가
    enabled: bool = True


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: dict | None
    error: str | None
    ms: int


_specs: dict[str, ToolSpec] = {}
_functions: dict[str, Callable] = {}


def _models(fn: Callable) -> tuple[type[BaseModel], type[BaseModel]]:
    """함수 서명에서 (입력 모델, 출력 모델)을 읽는다."""
    signature = inspect.signature(fn, eval_str=True)
    params = list(signature.parameters.values())
    input_model = params[0].annotation if params else None
    output_model = signature.return_annotation
    for model in (input_model, output_model):
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            raise TypeError(
                f"도구 함수 {fn.__name__} 의 첫 인자와 반환값은 pydantic 모델이어야 합니다."
            )
    if input_model.model_config.get("extra") != "forbid":
        raise TypeError(
            f"도구 함수 {fn.__name__} 의 입력 모델 {input_model.__name__} 은 모르는 칸을 거절해야 "
            '합니다: model_config = ConfigDict(extra="forbid")'
        )
    return input_model, output_model


def tool(
    name: str, description: str, *, program: str | None = None, mutates: bool = False
) -> Callable[[Callable], Callable]:
    """도구를 등록하는 데코레이터. 같은 이름이 있거나 이름 꼴이 틀리면 ValueError.

    입력·출력이 pydantic 모델이 아니거나 입력 모델이 extra="forbid" 가 아니면 TypeError.
    """

    def decorator(fn: Callable) -> Callable:
        if _NAME.fullmatch(name) is None:
            raise ValueError(f"도구 이름이 올바르지 않습니다: {name!r}")
        if name in _specs:
            raise ValueError(f"같은 이름의 도구가 이미 있습니다: {name}")
        input_model, output_model = _models(fn)
        _specs[name] = ToolSpec(name, description, input_model, output_model, program, mutates)
        _functions[name] = fn
        return fn

    return decorator


def unregister(name: str) -> None:
    """등록을 지운다(시험에서 잠깐 등록한 도구를 치울 때)."""
    del _specs[name]
    del _functions[name]


def load_all() -> None:
    """app/tools/*/ 아래 도구 모듈을 모두 import 해 등록시킨다. 여러 번 불러도 된다."""
    for package in pkgutil.iter_modules(app.tools.__path__, "app.tools."):
        if not package.ispkg:
            continue
        found = importlib.import_module(package.name)
        for module in pkgutil.iter_modules(found.__path__, f"{package.name}."):
            importlib.import_module(module.name)


def list_tools(*, enabled_only: bool = True) -> list[ToolSpec]:
    """등록된 도구(이름 순). enabled_only=False 면 꺼진 것도."""
    return [s for _, s in sorted(_specs.items()) if s.enabled or not enabled_only]


def set_enabled(name: str, enabled: bool) -> None:
    """도구를 켜고 끈다(메모리에만). 없는 도구면 KeyError."""
    _specs[name] = replace(_specs[name], enabled=enabled)


def as_llm_tools() -> list[dict]:
    """켜진 도구를 OpenAI tools 형식으로. 이름은 LLM 쪽 이름(schedule__read)."""
    return [
        {
            "type": "function",
            "function": {
                "name": to_llm_name(spec.name),
                "description": spec.description,
                "parameters": spec.input_model.model_json_schema(),
            },
        }
        for spec in list_tools()
    ]


def _input_reason(error: ValidationError) -> str:
    """어느 칸이 왜 틀렸는지 짧게. 받은 값은 넣지 않는다."""
    parts = []
    for item in error.errors(include_input=False, include_url=False)[:_MAX_INPUT_ERRORS]:
        where = ".".join(str(p) for p in item["loc"]) or "입력"
        parts.append(f"{where}: {item['msg']}")
    return "; ".join(parts)


async def _run(
    spec: ToolSpec, arguments: dict | None, ctx: ToolContext
) -> tuple[dict | None, str | None]:
    """(출력, 오류 글). 둘 중 하나만 있다."""
    if not isinstance(arguments, dict):  # 모델이 준 인자가 JSON 객체가 아니었다(None)
        return None, _NOT_AN_OBJECT
    try:
        args = spec.input_model.model_validate(arguments)
    except ValidationError as e:
        return None, f"입력 형식 오류: {_input_reason(e)}"
    try:
        result = _functions[spec.name](args, ctx)
        if inspect.isawaitable(result):
            result = await result
        return spec.output_model.model_validate(result).model_dump(mode="json"), None
    except ToolError as e:
        return None, e.message
    except Exception as e:  # 도구 안의 어떤 오류도 에이전트를 멈추지 않게 결과로 바꾼다
        logger.exception("도구 실행 중 오류: %s", spec.name)
        return None, f"도구 실행 중 오류: {type(e).__name__}"


async def call(name: str, arguments: dict | None, ctx: ToolContext) -> ToolResult:
    """도구를 부른다. 어떤 실패도 예외 대신 ToolResult(ok=False, error=…) 로 돌려준다.

    arguments 가 dict 가 아니면(LlmClient 의 ToolCall.arguments 가 None 인 경우 등)
    실행하지 않고 "입력 형식 오류: 인자가 JSON 객체가 아닙니다." 를 돌려준다.
    """
    start = time.perf_counter()
    spec = _specs.get(name)
    if spec is None:
        output, error = None, f"없는 도구입니다: {name}"
    elif not spec.enabled:
        output, error = None, f"꺼져 있는 도구입니다: {name}"
    else:
        output, error = await _run(spec, arguments, ctx)
    ms = int((time.perf_counter() - start) * 1000)
    return ToolResult(ok=error is None, output=output, error=error, ms=ms)
