"""통로 등록부(Task 64): 등록·찾기·고정(pinned), 시험 가짜가 진짜 통로보다 앞에 섬, 진짜 통로에 닿는 시험은 실패함,
하네스가 통로·제공사·음성·글·모델을 import 하지 않음."""

import ast
import importlib
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.outreach.harness import registry
from app.outreach.harness.types import Delivered, NotReady
from tests.harness_doubles import Delivery, RealChannelGuard, faked_channels

BACKEND = Path(__file__).resolve().parents[3]
HARNESS = BACKEND / "app" / "outreach" / "harness"
PACKAGE = "app.outreach.harness"
# 하네스는 코드만 — 통로·제공사·음성·글 세션(계획)과 HTTP·모델 SDK·음성 SDK(제공사·모델 호출 없음)를 import 하지 않는다.
# 음성 SDK 의 import 이름은 clawops(배포 이름 koreaaitel — 둘 다 막는다).
FORBIDDEN = ("app.outreach.channels", "app.outreach.provider", "app.outreach.voice", "app.outreach.text", "app.llm",
             "httpx", "openai", "google.genai", "anthropic", "koreaaitel", "clawops")
DYNAMIC = "<동적 import>"


def _imports(source: str, module: str) -> set[str]:
    """그 모듈이 import 하는 이름 전부(상대 import 는 풀고, `from a import b` 는 a 와 a.b 둘 다,
    importlib.import_module("x")·__import__("x") 도). 글자 그대로가 아닌 동적 import 는 DYNAMIC."""
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
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called in ("import_module", "__import__"):
                arg = node.args[0] if node.args else None
                literal = isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                names.add(arg.value if literal else DYNAMIC)
    return names


def _forbidden(names: set[str]) -> set[str]:
    bad = {name for name in names for f in FORBIDDEN if name == f or name.startswith(f + ".")}
    return bad | (names & {DYNAMIC})


def test_harness_package_imports_no_channel_or_provider():
    files = sorted(HARNESS.rglob("*.py"))
    assert {"__init__.py", "types.py", "events.py", "registry.py"} <= {f.name for f in files}
    for path in files:
        parts = path.relative_to(HARNESS).with_suffix("").parts
        module = ".".join((PACKAGE, *parts))  # __init__ 은 'pkg.__init__' — 상대 import 의 바탕이 그 꾸러미가 된다
        assert not _forbidden(_imports(path.read_text(encoding="utf-8"), module)), path.name

    planted = textwrap.dedent("""
        from app.outreach import provider
        from ..channels import sms
        from ..text.session import x
        import httpx, openai
        from google import genai
        import anthropic.types
        import importlib
        importlib.import_module("app.outreach.voice.kat_sdk")
        __import__("koreaaitel")
        import clawops
        from clawops.agent import ClawOpsAgent
        from importlib import import_module
        import_module(name)
    """)
    assert _forbidden(_imports(planted, f"{PACKAGE}.gate")) == {
        "app.outreach.provider", "app.outreach.channels", "app.outreach.channels.sms", "app.outreach.text.session",
        "app.outreach.text.session.x", "httpx", "openai", "google.genai", "anthropic.types",
        "app.outreach.voice.kat_sdk", "koreaaitel", "clawops", "clawops.agent", "clawops.agent.ClawOpsAgent", DYNAMIC,
    }  # 훑는 함수가 이런 꼴을 놓치지 않는다


@pytest.mark.parametrize("source", [
    "import clawops",  # 음성 SDK 의 실제 import 이름(배포 이름은 koreaaitel)
    "from clawops.agent import ClawOpsAgent",
    "import koreaaitel",
    "from google import genai",
    "import google.genai as genai",
    "from google.genai import types",
])
def test_model_and_voice_sdk_imports_are_forbidden_in_harness(source):
    assert _forbidden(_imports(source, f"{PACKAGE}.door")), source


def test_importing_every_harness_module_loads_no_channel_provider_or_model():
    """간접 import 까지: 새 프로세스에서 하네스 모듈을 모두(하위 폴더 포함) 불러온 뒤 sys.modules 를 본다.
    (httpx 는 redact → app.info.generic 이 불러오므로 여기서는 보지 않는다 — 직접 import 는 위 시험이 막는다.)"""
    code = textwrap.dedent("""
        import importlib, pkgutil, sys
        import app.outreach.harness as harness
        for info in pkgutil.walk_packages(harness.__path__, harness.__name__ + "."):
            importlib.import_module(info.name)
        bad = ("app.outreach.channels", "app.outreach.provider", "app.outreach.voice", "app.outreach.text", "app.llm",
               "openai", "google.genai", "anthropic", "koreaaitel", "clawops")
        loaded = sorted(n for n in sys.modules if any(n == b or n.startswith(b + ".") for b in bad))
        print("LOADED", loaded)
        print("COUNT", len([n for n in sys.modules if n.startswith("app.outreach.harness.")]))
    """)
    done = subprocess.run([sys.executable, "-c", code], check=False, cwd=BACKEND, capture_output=True, text=True, timeout=120,
                          env=os.environ.copy())
    assert done.returncode == 0, done.stderr[-2000:]
    lines = dict(line.split(" ", 1) for line in done.stdout.splitlines())
    assert lines["LOADED"] == "[]"
    assert int(lines["COUNT"]) >= 3  # types·events·registry 를 실제로 불러왔다


def test_unregistered_channel_is_not_ready(monkeypatch):
    monkeypatch.setattr(registry, "_CHANNELS", {})
    for name in ("sms", "kakao", "call"):
        with pytest.raises(NotReady):
            registry.channel(name)
    assert registry.registered() == []


class _Lane:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[int] = []

    async def deliver(self, row_id: int) -> Delivered:
        self.calls.append(row_id)
        return Delivered("sent", provider_id=f"p-{row_id}")


@pytest.mark.real_channel("sms")
async def test_registered_channel_is_found_by_name(monkeypatch):
    monkeypatch.setattr(registry, "_CHANNELS", {})
    sms = _Lane("sms")
    registry.register_channel("sms", sms)
    assert registry.channel("sms") is sms
    assert (await registry.channel("sms").deliver(7)).provider_id == "p-7"
    assert registry.registered() == ["sms"]
    with pytest.raises(NotReady):
        registry.channel("kakao")  # 등록한 이름만


def test_register_refuses_a_second_channel_under_the_same_name(monkeypatch):
    monkeypatch.setattr(registry, "_CHANNELS", {})
    first, second = _Lane("sms"), _Lane("sms")
    registry.register_channel("sms", first)
    registry.register_channel("sms", first)  # 같은 객체는 다시 불러도 된다(모듈 import 가 두 번 돌아도)
    with pytest.raises(ValueError):
        registry.register_channel("sms", second)
    assert registry.registered() == ["sms"] and registry._CHANNELS["sms"] is first
    registry.register_channel("sms", second, replace=True)
    assert registry._CHANNELS["sms"] is second


def test_register_checks_the_name(monkeypatch):
    monkeypatch.setattr(registry, "_CHANNELS", {})
    with pytest.raises(ValueError):
        registry.register_channel("sms", _Lane("call"))  # 이름과 통로의 name 이 다름
    with pytest.raises(ValueError):
        registry.register_channel("fax", _Lane("fax"))  # 이름표의 통로(sms·kakao·call)가 아님
    assert registry.registered() == []


@pytest.mark.real_channel("sms")
async def test_fake_stays_in_front_when_a_real_channel_registers_mid_test(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "_CHANNELS", {})
    name = "late_sms_channel_t64"
    (tmp_path / f"{name}.py").write_text(textwrap.dedent("""
        from app.outreach.harness import registry
        from app.outreach.harness.types import Delivered

        class RealSms:
            name = "sms"

            def __init__(self):
                self.calls = []

            async def deliver(self, row_id):
                self.calls.append(row_id)
                return Delivered("sent")

        CHANNEL = RealSms()
        registry.register_channel("sms", CHANNEL)
    """), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, name, raising=False)
    with faked_channels() as fake:
        module = importlib.import_module(name)  # 진짜 통로가 시험 가운데 처음 import 돼 스스로 등록한다
        await registry.channel("sms").deliver(1)
        assert fake.delivered == [Delivery("sms", 1)] and module.CHANNEL.calls == []
    assert registry.channel("sms") is module.CHANNEL  # 가짜를 걷어 낸 뒤에도 진짜 등록은 남는다
    assert registry.registered() == ["sms"]


def test_faked_channels_checks_at_the_end_that_the_fake_still_answers():
    stray = _Lane("sms")
    with pytest.raises(AssertionError, match="sms"), faked_channels():
        registry._PINNED.append({"sms": stray})  # 누가 가짜 위에 다른 것을 끼우고 걷지 않음
    registry._PINNED.remove({"sms": stray})
    assert all(layer != {"sms": stray} for layer in registry._PINNED)


async def test_test_that_reaches_a_real_channel_fails_loudly(monkeypatch, no_real_channels):
    monkeypatch.setattr(registry, "_CHANNELS", {})
    real = _Lane("sms")
    registry.register_channel("sms", real)
    with pytest.raises(pytest.fail.Exception, match="real_channel"):
        try:
            await registry.channel("sms").deliver(3)
        except Exception:  # noqa: BLE001 — 문이 통로 예외를 잡아도 새어 나가는지 본다
            pytest.fail("가드가 Exception 으로 잡혔습니다")
    assert real.calls == []
    assert len(no_real_channels.violations) == 1
    no_real_channels.violations.clear()  # 이 시험이 일부러 낸 위반 — 걷지 않으면 끝에서 실패한다
    with pytest.raises(NotReady):
        registry.channel("kakao")  # 가드는 등록되지 않은 통로를 있는 것처럼 만들지 않는다


def test_registered_lists_what_channel_can_find(monkeypatch):
    monkeypatch.setattr(registry, "_CHANNELS", {})
    assert registry.registered() == []
    with faked_channels():
        assert registry.registered() == ["call", "kakao", "sms"]  # 덮은 층의 이름도 찾을 수 있다
    assert registry.registered() == []


async def test_fake_channel_stands_in_for_all_three_channels(fake_channel):
    for row_id, name in enumerate(("sms", "kakao", "call"), start=1):
        assert (await registry.channel(name).deliver(row_id)).ok
    assert fake_channel.delivered == [Delivery("sms", 1), Delivery("kakao", 2), Delivery("call", 3)]


async def test_fake_channel_can_fail_and_run_code_inside_deliver(fake_channel):
    seen = []
    fake_channel.result = Delivered("failed", fail_code="bad_sender", fail_text="발신번호가 등록돼 있지 않습니다")
    fake_channel.during = seen.append
    got = await registry.channel("sms").deliver(5)
    assert not got.ok and got.fail_code == "bad_sender"
    assert seen == [5] and fake_channel.delivered == [Delivery("sms", 5)]
    fake_channel.result = RuntimeError("연결 끊김")
    with pytest.raises(RuntimeError):
        await registry.channel("call").deliver(6)
    assert fake_channel.delivered[-1] == Delivery("call", 6)


async def test_fake_channel_can_return_unsure(fake_channel):
    fake_channel.result = Delivered("unsure", fail_code="timeout", fail_text="결과를 알 수 없습니다")
    got = await registry.channel("sms").deliver(8)
    assert got.state == "unsure" and not got.ok
    assert fake_channel.delivered == [Delivery("sms", 8)]
    fake_channel.result = None
    assert (await registry.channel("sms").deliver(9)).state == "sent"  # 기본은 보냄


# ── 가짜 통로는 시험(또는 밝힌 모래상자 프로세스)에서만 ─────────────────


def _pin_in_fresh_process(extra_env: dict[str, str]) -> str:
    code = textwrap.dedent("""
        import sys
        from app.outreach.harness import registry
        assert "pytest" not in sys.modules
        try:
            with registry.pinned({}):
                pass
        except RuntimeError as exc:
            print("REFUSED", exc)
        else:
            print("ALLOWED")
    """)
    env = {k: v for k, v in os.environ.items() if k != registry.SANDBOX_ENV} | extra_env
    done = subprocess.run([sys.executable, "-c", code], check=False, cwd=BACKEND, capture_output=True, text=True,
                          timeout=120, env=env)
    assert done.returncode == 0, done.stderr[-2000:]
    return done.stdout.strip()


def test_pinning_is_refused_outside_tests_and_sandbox():
    assert _pin_in_fresh_process({}).startswith("REFUSED")  # 서버 프로세스: 진짜 예약 문자가 가짜로 가면 안 된다
    assert _pin_in_fresh_process({registry.SANDBOX_ENV: "0"}).startswith("REFUSED")
    assert _pin_in_fresh_process({registry.SANDBOX_ENV: "1"}) == "ALLOWED"  # 격자 칸을 돌리는 자식 프로세스


REGISTRY = "app.outreach.harness.registry"
_BANNED = ("pinned", "faked_channels")


def _from_base(node: ast.ImportFrom, module: str) -> str:
    """`from … import` 의 바탕 모듈(상대 import 는 module 의 꾸러미에서 푼다)."""
    if not node.level:
        return node.module or ""
    package = module.split(".")[:-1]
    base = package[: len(package) - node.level + 1]
    return ".".join([*base, node.module] if node.module else base)


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = _dotted(node.value)
        return f"{inner}.{node.attr}" if inner else None
    return None


def _pins(source: str, module: str) -> list[str]:
    """registry 모듈의 pinned·faked_channels 에 닿는 자리 전부(부르든 꺼내 두든). registry 의 별칭(절대·상대 import,
    꾸러미 별칭 + .registry)을 따라가고, getattr(별칭, "pinned") 와 import 해 온 이름도 잡는다. Scope.pinned 는 아니다."""
    tree = ast.parse(source)
    aliases, imported, found = {REGISTRY}, set(), []

    def bind(local: str, full: str) -> None:
        if full == REGISTRY:
            aliases.add(local)
        elif REGISTRY.startswith(full + "."):
            aliases.add(local + REGISTRY[len(full):])

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bind(alias.asname, alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _from_base(node, module)
            for alias in node.names:
                bind(alias.asname or alias.name, f"{base}.{alias.name}")
                if alias.name == "faked_channels" or (base == REGISTRY and alias.name == "pinned"):
                    found.append(f"import {alias.name}")
                    imported.add(alias.asname or alias.name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _BANNED:
            owner = _dotted(node.value)
            if node.attr == "faked_channels" or owner in aliases:
                found.append(f"{owner}.{node.attr}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
            owner, name = (_dotted(node.args[0]), node.args[1]) if len(node.args) >= 2 else (None, None)
            if isinstance(name, ast.Constant) and name.value in _BANNED and \
                    (name.value == "faked_channels" or owner in aliases):
                found.append(f"getattr({owner}, {name.value!r})")
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in imported:
            found.append(node.id)
    return found


CAUGHT_FORMS = {
    "alias": "from app.outreach.harness import registry as reg\nreg.pinned({})\n",
    "module_alias": "import app.outreach.harness.registry as r2\nwith r2.pinned({}):\n    pass\n",
    "relative_name": "from .registry import pinned\nwith pinned({}):\n    pass\n",
    "relative_module": "from . import registry\nregistry.pinned({})\n",
    "renamed_name": "from app.outreach.harness.registry import pinned as keep\nwith keep({}):\n    pass\n",
    "getattr": "from app.outreach.harness import registry\nopen_ = getattr(registry, 'pinned')\n",
    "kept_not_called": "from app.outreach.harness import registry\np = registry.pinned\n",
    "full_path": "import app.outreach.harness.registry\napp.outreach.harness.registry.pinned({})\n",
    "package_alias": "import app.outreach.harness as h\nh.registry.pinned({})\n",
    "faked_import": "from tests.harness_doubles import faked_channels\n",
    "faked_attr": "import tests.harness_doubles as d\nd.faked_channels()\n",
    "faked_getattr": "import tests.harness_doubles as d\ngetattr(d, 'faked_channels')\n",
}
NOT_CAUGHT = (
    "scope.pinned(3)\np = scope.pinned\ngetattr(scope, 'pinned')\n"
    "from app.outreach.harness import types\ntypes.Scope.pinned\n"
)


def test_pin_scanner_catches_every_form(tmp_path):
    for form, source in CAUGHT_FORMS.items():
        planted = tmp_path / f"planted_{form}.py"  # 임시 모듈에 심고 그 파일을 훑는다
        planted.write_text(source, encoding="utf-8")
        assert _pins(planted.read_text(encoding="utf-8"), "app.outreach.harness.planted"), form
    clean = tmp_path / "planted_scope.py"
    clean.write_text(NOT_CAUGHT, encoding="utf-8")
    assert _pins(clean.read_text(encoding="utf-8"), "app.outreach.harness.planted") == []  # Scope.pinned 은 범위 메서드


def test_no_app_module_pins_channels():
    assert registry.SANDBOX_MODULES == frozenset({"app.outreach.scenarios.drive_text", "app.outreach.scenarios.drive_voice",
                                                  "app.outreach.scenarios.prove"})  # 모래상자 실행 모듈(Task 86·97 구동기 · 98 자식)
    app_dir = BACKEND / "app"
    offenders = {}
    for path in sorted(app_dir.rglob("*.py")):
        module = ".".join(path.relative_to(BACKEND).with_suffix("").parts)
        if module in registry.SANDBOX_MODULES or path == HARNESS / "registry.py":
            continue
        hits = _pins(path.read_text(encoding="utf-8"), module)
        if hits:
            offenders[module] = hits
    assert offenders == {}


def test_session_floor_sits_under_every_test(no_real_channels):
    floor = registry._PINNED[0]
    assert isinstance(floor, RealChannelGuard) and floor is not no_real_channels
    assert no_real_channels in registry._PINNED[1:]


# ── 가드: 시험 밖 호출·표지 쓰는 법 (새 pytest 프로세스에서 확인) ──────────


def _run_pytest(tmp_path: Path, source: str) -> tuple[dict[str, str], str]:
    test_file = tmp_path / "test_guard_t64.py"
    test_file.write_text(textwrap.dedent(source), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(BACKEND)}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "-p", "tests.harness_doubles",
         "-c", str(BACKEND / "pyproject.toml"), "--rootdir", str(tmp_path), str(test_file)],
        check=False, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=180,
    )
    outcomes = {}
    for line in done.stdout.splitlines():
        for word in ("PASSED", "FAILED", "ERROR"):
            if line.startswith(word + " ") and "::" in line:
                name = line.split("::", 1)[1].split(" ")[0]
                outcomes[name] = outcomes.get(name, word) if word == "PASSED" else word
    return outcomes, done.stdout + done.stderr


REAL_SMS = """
    import asyncio, threading, time
    import pytest
    from app.outreach.harness import registry
    from app.outreach.harness.types import Delivered

    CALLS = []

    class Real:
        name = "sms"

        async def deliver(self, row_id):
            CALLS.append(row_id)
            return Delivered("sent")

    registry.register_channel("sms", Real())
"""


def test_marker_frees_only_named_channels_and_only_on_the_test_itself(tmp_path):
    outcomes, output = _run_pytest(tmp_path, REAL_SMS + """
    @pytest.mark.real_channel("sms")
    def test_named_channel_is_free():
        asyncio.run(registry.channel("sms").deliver(1))
        assert CALLS == [1]

    @pytest.mark.real_channel("call")
    def test_other_name_does_not_free_sms():
        asyncio.run(registry.channel("sms").deliver(2))

    @pytest.mark.real_channel
    def test_marker_without_names_is_refused():
        pass

    @pytest.mark.real_channel("fax")
    def test_marker_with_unknown_name_is_refused():
        pass

    class TestInClass:
        pytestmark = pytest.mark.real_channel("sms")

        def test_class_mark_does_not_free(self):
            asyncio.run(registry.channel("sms").deliver(3))
    """)
    assert outcomes["test_named_channel_is_free"] == "PASSED", output[-3000:]
    assert outcomes["test_other_name_does_not_free_sms"] == "FAILED"
    assert outcomes["test_marker_without_names_is_refused"] in ("FAILED", "ERROR")
    assert outcomes["test_marker_with_unknown_name_is_refused"] in ("FAILED", "ERROR")
    assert outcomes["TestInClass::test_class_mark_does_not_free"] == "FAILED"
    assert "시험 함수에 직접" in output and "통로 이름" in output


def test_module_mark_does_not_switch_the_guard_off(tmp_path):
    outcomes, output = _run_pytest(tmp_path, REAL_SMS + """
    pytestmark = pytest.mark.real_channel("sms")

    def test_any_test_in_module_reaches_real():
        asyncio.run(registry.channel("sms").deliver(99))
    """)
    assert outcomes["test_any_test_in_module_reaches_real"] == "FAILED", output[-3000:]
    assert "시험 함수에 직접" in output


def test_real_call_after_a_test_ends_is_reported_at_session_end(tmp_path):
    _outcomes, output = _run_pytest(tmp_path, REAL_SMS + """
    @pytest.fixture(scope="module")
    def slow_end():
        yield
        time.sleep(1.0)  # 시험이 끝난 뒤(모듈 고정물 정리) — 시험마다의 가드는 이미 걷혔다

    def test_leaves_a_thread(slow_end):
        def later():
            time.sleep(0.3)
            try:
                asyncio.run(registry.channel("sms").deliver(7))
            except BaseException:
                pass

        threading.Thread(target=later, daemon=True).start()
    """)
    assert "1 passed, 1 error" in output, output[-3000:]  # 시험 몸통은 통과, 세션 끝 정리에서 실패로 드러난다
    assert "시험 밖" in output and "「sms」" in output
