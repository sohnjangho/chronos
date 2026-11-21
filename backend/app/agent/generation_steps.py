"""생성 루프의 LLM 쪽: 답 모양(JSON 스키마, strict), 지시문, 보낼 글, 부르기.

LLM 은 구조(WBS)와 액티비티(기간·선후 관계)만 낸다. 날짜는 코드가 계산한다.
스키마는 strict 모드 규칙을 따른다: 객체마다 모든 속성이 required, additionalProperties false.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.domains.loader import DomainPack, levels, levels_prompt
from app.harness.conditions import Condition
from app.llm.client import LlmClient, LlmReply

PROMPTS = Path(__file__).parent / "prompts"
DATE_RULE = "날짜는 계산하지 않는다 — 기간(근무일)과 선후 관계만 낸다"
HARD_TIMEOUT_S = 240  # WBS·초안·고침(긴 JSON 답)
_NONE = "(없음)"


def strict_object(props: dict) -> dict:
    """strict 모드 객체: 모든 속성이 required, 모르는 칸 금지."""
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_STR = {"type": "string"}
_WBS_LIST = {
    "type": "array",
    "items": strict_object({"code": _STR, "name": _STR, "parent": {"type": ["string", "null"]}}),
}
_PREDECESSOR = strict_object(
    {"pred": _STR, "type": {"type": "string", "enum": ["FS", "SS", "FF", "SF"]}, "lag": {"type": "integer"}}
)
_RESOURCE = strict_object({"id": _STR, "name": _STR, "unit": _STR, "capacity": {"type": "integer"}})
_ACTIVITIES = {
    "type": "array",
    "items": strict_object(
        {
            "id": _STR,
            "name": _STR,
            "kind": {"type": "string", "enum": ["task", "start_ms", "finish_ms"]},
            "wbs": _STR,
            "od": {"type": "integer"},
            "tags": {"type": "array", "items": _STR},
            "resources": {"type": "array", "items": _STR},
            "predecessors": {"type": "array", "items": _PREDECESSOR},
        }
    ),
}
WBS_SCHEMA = strict_object({"wbs": _WBS_LIST})
SCHEDULE_SCHEMA = strict_object({"resources": {"type": "array", "items": _RESOURCE}, "activities": _ACTIVITIES})
# 고침: WBS 를 바꿀 때만 새 WBS 전체, 아니면 null
REPAIR_SCHEMA = strict_object(
    {
        "wbs": {"anyOf": [_WBS_LIST, {"type": "null"}]},
        "resources": {"type": "array", "items": _RESOURCE},
        "activities": _ACTIVITIES,
    }
)


def system_prompt(name: str, pack: DomainPack) -> str:
    """prompts/<name>.md 에 정밀도 정의({{levels}})와 분야 지식({{domain}})을 넣은 지시문."""
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    return text.replace("{{levels}}", levels_prompt()).replace("{{domain}}", pack.prompt())


def level_line(level: str) -> str:
    d = levels()[level]
    depth = "~".join(str(n) for n in sorted(set(d.wbs_depth)))
    count = "~".join(str(n) for n in d.activity_count) + "개" if d.activity_count else "고른 구간만"
    return (
        f"정밀도: {d.id} {d.name} — WBS 깊이 {depth}, 액티비티 {count}, 기간 단위 {d.time_unit}, "
        f"자원 {d.resources}, 꼭 있어야 하는 것: {d.must_contain}"
    )


def _items(rows: Sequence[dict]) -> list[str]:
    return [f"- {r['label']}: {r['value']} ({r['source']})" for r in rows] or [_NONE]


def condition_line(c: Condition) -> str:
    if not c.checkable:
        return f"- {c.text} [{c.id} · 자동 점검 안 됨]"
    params = ", ".join(f"{k}={v}" for k, v in c.params.items())
    return f"- {c.text} [{c.id} · {c.kind} {params}]"


@dataclass(frozen=True)
class Brief:
    """LLM 에 주는 일감. conditions 는 입력 조건(분야 규칙은 지시문에 있다)."""

    level: str
    request: str
    facts: list[dict]
    assumptions: list[dict]
    conditions: list[Condition]
    tags: list[str]  # 액티비티에 달 수 있는 꼬리표

    def text(self) -> str:
        lines = [level_line(self.level), f"요청: {self.request}", "알고 있는 것:", *_items(self.facts)]
        lines += ["가정한 것:", *_items(self.assumptions), "지킬 조건:"]
        lines += [condition_line(c) for c in self.conditions] or [_NONE]
        lines.append("쓸 수 있는 꼬리표(tags): " + (", ".join(self.tags) or _NONE))
        return "\n".join(lines)


def compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _messages(system: str, user: str) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def wbs_messages(pack: DomainPack, brief: Brief, problem: str) -> list[dict]:
    user = brief.text()
    if problem:
        user += f"\n앞 답의 문제: {problem}\n다시 WBS 전체를 내라."
    return _messages(system_prompt("wbs", pack), user)


def schedule_messages(pack: DomainPack, brief: Brief, wbs: list[dict]) -> list[dict]:
    user = f"{brief.text()}\nWBS: {compact(wbs)}"
    return _messages(system_prompt("schedule", pack), user)


def repair_messages(
    pack: DomainPack,
    brief: Brief,
    wbs: list[dict],
    draft: list[dict] | None,
    feedback: str,
    resources: list[dict] | None = None,
) -> list[dict]:
    """draft 가 None 이면(앞 답을 읽지 못함) 처음부터 전체 초안을 내게 한다."""
    if draft is None:
        current = "(읽은 초안 없음 — 전체 초안을 처음부터 낸다)"
    elif resources:
        current = compact({"resources": resources, "activities": draft})
    else:
        current = compact({"activities": draft})
    user = f"{brief.text()}\nWBS: {compact(wbs)}\n지금 초안: {current}\n고칠 것:\n{feedback}"
    return _messages(system_prompt("repair", pack), user)


async def ask(
    llm: LlmClient, messages: list[dict], schema: dict, chat_session_id: int | None
) -> LlmReply:
    """hard 쓰임새로 한 번 부른다. 실패(LlmNotReady·LlmFailed)는 그대로 올라간다."""
    return await llm.chat(
        "hard",
        messages,
        json_schema=schema,
        timeout_s=HARD_TIMEOUT_S,
        chat_session_id=chat_session_id,
        max_tokens=32000,
    )
