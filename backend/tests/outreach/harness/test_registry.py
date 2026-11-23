"""하네스 바탕(Task 64): 하네스 낱말의 꼴, 통로 등록부, 하네스가 통로·제공사·음성·글·LLM 을 import 하지 않음, 통로 가짜."""

import ast
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import get_args

import pytest

from app.outreach.harness import registry
from app.outreach.harness.types import (
    Actor,
    Caller,
    CallerClass,
    Candidate,
    Delivered,
    Medium,
    NotReady,
    Outcome,
    Ref,
    Scope,
    ToolDef,
)
from tests.harness_doubles import Delivery

HARNESS = Path(__file__).resolve().parents[3] / "app" / "outreach" / "harness"
PACKAGE = "app.outreach.harness"
# 하네스는 코드만 — 통로·제공사·음성·글 세션(계획)과 HTTP·LLM(제공사·모델 호출 없음)을 import 하지 않는다.
FORBIDDEN = ("app.outreach.channels", "app.outreach.provider", "app.outreach.voice", "app.outreach.text", "httpx", "app.llm")


def _imports(source: str, module: str) -> set[str]:
    """그 모듈이 import 하는 이름 전부(상대 import 는 풀고, `from a import b` 는 a 와 a.b 둘 다)."""
    names: set[str] = set()
    package = module.rsplit(".", 1)[0]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1])
                base = f"{base}.{node.module}" if node.module else base
            else:
                base = node.module or ""
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def _forbidden(names: set[str]) -> set[str]:
    return {name for name in names for bad in FORBIDDEN if name == bad or name.startswith(bad + ".")}


def test_harness_package_imports_no_channel_or_provider():
    files = sorted(HARNESS.glob("*.py"))
    assert {"__init__.py", "types.py", "events.py", "registry.py"} <= {f.name for f in files}
    for path in files:
        module = f"{PACKAGE}.{path.stem}" if path.stem != "__init__" else f"{PACKAGE}.__init__"
        assert not _forbidden(_imports(path.read_text(encoding="utf-8"), module)), path.name

    planted = "from app.outreach import provider\nfrom ..channels import sms\nfrom ..text.session import x\nimport httpx\n"
    assert _forbidden(_imports(planted, f"{PACKAGE}.gate")) == {
        "app.outreach.provider", "app.outreach.channels", "app.outreach.channels.sms", "app.outreach.text.session",
        "app.outreach.text.session.x", "httpx",
    }  # 훑는 함수가 이런 꼴을 놓치지 않는다


def test_words_have_the_plan_shapes():
    assert get_args(Medium) == ("sms", "call")
    assert get_args(CallerClass) == (
        "internal", "contact", "contact_multi", "shared", "do_not_contact", "unknown", "withheld", "blocked",
        "outside_test", "outbound",
    )
    shapes = {
        Actor: ["kind", "user_id", "name", "role"],
        Outcome: ["code", "message", "rule", "scheduled_at"],
        Candidate: ["schedule_id", "contact_id", "company_id"],
        Caller: ["caller_class", "candidates", "user_id"],
        Scope: ["caller_class", "schedule_ids", "contact_ids", "company_ids", "personal", "facts"],
        Ref: ["kind", "row_id"],
        Delivered: ["ok", "provider_id", "fail_code", "fail_text"],
        ToolDef: ["name", "description", "parameters"],
    }
    for cls, names in shapes.items():
        assert [f.name for f in fields(cls)] == names, cls.__name__
    assert Outcome("accepted", "보냈습니다") == Outcome("accepted", "보냈습니다", None, None)
    assert Delivered(ok=True) == Delivered(True, None, None, None)
    scope = Scope("contact", (1,), (2,), (3,), True, "trade")
    with pytest.raises(FrozenInstanceError):
        scope.facts = "all"  # 범위는 만든 뒤 바꿀 수 없다


def test_unregistered_channel_is_not_ready(monkeypatch):
    monkeypatch.setattr(registry, "_CHANNELS", {})
    for name in ("sms", "kakao", "call"):
        with pytest.raises(NotReady):
            registry.channel(name)


class _Lane:
    def __init__(self, name: str) -> None:
        self.name = name

    async def deliver(self, row_id: int) -> Delivered:
        return Delivered(ok=True, provider_id=f"p-{row_id}")


async def test_registered_channel_is_found_by_name(monkeypatch):
    monkeypatch.setattr(registry, "_CHANNELS", {})
    sms = _Lane("sms")
    registry.register_channel("sms", sms)
    assert registry.channel("sms") is sms
    assert (await registry.channel("sms").deliver(7)).provider_id == "p-7"
    with pytest.raises(NotReady):
        registry.channel("kakao")  # 등록한 이름만


async def test_fake_channel_stands_in_for_all_three_channels(fake_channel):
    for row_id, name in enumerate(("sms", "kakao", "call"), start=1):
        assert (await registry.channel(name).deliver(row_id)).ok
    assert fake_channel.delivered == [Delivery("sms", 1), Delivery("kakao", 2), Delivery("call", 3)]


async def test_fake_channel_can_fail_and_run_code_inside_deliver(fake_channel):
    seen = []
    fake_channel.result = Delivered(ok=False, fail_code="bad_sender", fail_text="발신번호가 등록돼 있지 않습니다")
    fake_channel.during = seen.append
    got = await registry.channel("sms").deliver(5)
    assert not got.ok and got.fail_code == "bad_sender"
    assert seen == [5] and fake_channel.delivered == [Delivery("sms", 5)]
    fake_channel.result = RuntimeError("연결 끊김")
    with pytest.raises(RuntimeError):
        await registry.channel("call").deliver(6)
    assert fake_channel.delivered[-1] == Delivery("call", 6)
