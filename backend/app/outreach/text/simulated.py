"""대본대로 도는 글 세션(Task 84) — 실제 모델·네트워크가 없다. 들어온 문자 응대의 시험(84·86)과 개발 콘솔이 같이 쓴다 — 그래서
app 코드에 둔다. 끼우는 곳은 session.pinned 하나(시험·모래상자 프로세스에서만 열린다).

대본은 걸음의 목록이다: `Tool(name, args)`(모델의 도구 호출 — on_tool 로 부른다) · `Reply(text, text_ko=None, language="ko")`(답 —
respond 한 번이 끝난다). respond 를 부를 때마다 대본의 다음 걸음부터 Reply 까지 돈다(한 대본에 여러 문자의 응대를 이어 적는다).
Reply 앞에서 대본이 끝나면 TextFailed("script_end").

남기는 것: tool_results(on_tool 이 준 결과 — 부른 차례) · seen_instructions(받은 지시문) · seen_history(받은 대화 기록) ·
seen_tools(받은 도구 이름 — 받은 차례 그대로). 대본은 만들 때 검사하고(틀리면 ValueError — 몇 번째 걸음인지만) 깊이 복사해 둔다.
대본 길이는 MAX_STEPS 까지라 respond 한 번의 고리도 그 수로 끝난다.
"""

import copy
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.outreach.harness.types import ToolDef
from app.outreach.text.session import TextFailed, TextReply, TextUsage

MAX_STEPS = 500  # 대본 하나의 걸음 수


@dataclass(frozen=True)
class Tool:
    name: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Reply:
    text: str
    text_ko: str | None = None
    language: str = "ko"


Step = Tool | Reply


def _check(ok: bool, message: str) -> None:
    """대본 검사 — 틀리면 ValueError(몇 번째 걸음인지만, 받은 값은 싣지 않는다)."""
    if not ok:
        raise ValueError(message)


class SimulatedText:
    def __init__(self, script: list[Step], *, usage: TextUsage | None = None) -> None:
        steps = list(script)
        _check(len(steps) <= MAX_STEPS, f"대본은 {MAX_STEPS} 걸음까지입니다")
        for index, step in enumerate(steps, start=1):
            _check(isinstance(step, Tool | Reply), f"{index}번째 걸음: Tool 이나 Reply 가 아닙니다")
            if isinstance(step, Tool):
                _check(isinstance(step.name, str) and bool(step.name) and isinstance(step.args, dict),
                       f"{index}번째 걸음: Tool 은 이름(글)과 인자(dict)를 받습니다")
            else:
                _check(isinstance(step.text, str) and isinstance(step.language, str),
                       f"{index}번째 걸음: Reply 는 글과 언어 코드를 받습니다")
        self._script = copy.deepcopy(steps)
        self._next = 0
        self._usage = usage
        self.tool_results: list[dict] = []
        self.seen_instructions: list[str] = []
        self.seen_history: list[list[dict]] = []
        self.seen_tools: list[tuple[str, ...]] = []

    async def respond(self, instructions: str, tools: tuple[ToolDef, ...], history: list[dict],
                      on_tool: Callable[[str, dict], Awaitable[dict]]) -> TextReply:
        self.seen_instructions.append(instructions)
        self.seen_history.append(copy.deepcopy(history))
        self.seen_tools.append(tuple(tool.name for tool in tools))
        while self._next < len(self._script):
            step = self._script[self._next]
            self._next += 1
            if isinstance(step, Reply):
                return TextReply(step.text, step.text_ko, step.language, self._usage)
            self.tool_results.append(await on_tool(step.name, copy.deepcopy(step.args)))
        raise TextFailed("script_end", self._usage)
