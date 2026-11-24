"""Task 99 고침 1 — 음성 진단 P9 가 설정한 음성 이름을 전화 없이 확인한다(실시간 세션을 그 음성으로 열고 닫는다), 시험 전화는
「성별 모름」 칸의 음성으로 걸고, OpenAI 의 오류 줄(세션 설정 거절)은 통화 실패로 본다. Task 60 의 대본 가짜 SDK·대본 시계를 쓰고,
실제 SDK 는 불러오지 않는다. 결과에는 음성 이름이 실리지 않고 칸 이름표만 실린다."""

from functools import partial

import pytest

from app.notify import diagnostics_voice as dv
from app.notify import voice_names
from app.notify.diagnostics_voice import VoiceDiag
from tests.notify.test_diagnostics_voice import (
    ACCOUNT,
    GOOD_CALL,
    GOOGLE_KEY,
    SDK_LOG,
    FakeAgent,
    FakeSdk,
    World,
    dump,
    run,
)
from tests.outreach_doubles import SENTINEL_PHONE


@pytest.fixture
def world() -> World:
    return World()


MALE, FEMALE, UNKNOWN = "남성 연락처에게 걸 때", "여성 연락처에게 걸 때", "성별 모름"
OPENAI_ERROR = "OpenAI error: {'type': 'invalid_request_error', 'message': \"Invalid value: '%s'.\"}"


class Refused(Exception):
    status_code = 403


class LiveClosed(Exception):
    """Gemini Live 가 setup 을 거절하고 닫은 흉내(웹소켓 1007) — 글에 계정이 들어도 결과로 가지 않는다."""


class LoggingAgent(FakeAgent):
    async def step(self, call, kind, *args):
        if kind == "openai_error":
            SDK_LOG.error(OPENAI_ERROR, "x")
            return None
        return await super().step(call, kind, *args)


class VoiceSdk(FakeSdk):
    """세션에 prewarm·stop 이 있는 가짜(실제 GeminiRealtime·OpenAIRealtime 의 이름). bad = 공급자가 받지 않는 음성."""

    def __init__(self, clock: World, *, bad=(), slow=(), refused=False, **kw) -> None:
        super().__init__(clock, **kw)
        self.checks: list[tuple[str, str, bool]] = []
        self.stops = 0
        sdk = self

        class _Session:
            kind = ""

            def setup(self, voice, greeting, kw) -> None:
                self.voice, self.greeting = voice, greeting
                sdk.sessions.append((self.kind, {"voice": voice, "greeting": greeting, **kw}))

            async def prewarm(self) -> None:
                sdk.checks.append((self.kind, self.voice, self.greeting))
                if self.voice in slow:
                    await World.hang()
                if refused:
                    raise Refused("403")
                if self.voice in bad and self.kind == "GeminiRealtime":
                    raise LiveClosed(f"1007 invalid voice {self.voice} for {ACCOUNT}")
                if self.voice in bad:  # OpenAI 는 session.update 를 거절해도 오류 사건(줄 하나)만 — 조금 뒤에 온다
                    sdk.world.at(sdk.world.ms + 500, partial(_log, self.voice))

            async def stop(self) -> None:
                sdk.stops += 1

        class GeminiRealtime(_Session):
            kind = "GeminiRealtime"

            def __init__(self, *, api_key=None, system_prompt="", model="fake-live", voice="Kore", language="ko",
                         greeting=True, api_version=None) -> None:
                self.setup(voice, greeting, {"api_key": api_key, "model": model, "api_version": api_version,
                                             "system_prompt": system_prompt, "language": language})

        class OpenAIRealtime(_Session):
            kind = "OpenAIRealtime"

            def __init__(self, *, api_key=None, system_prompt="", model="fake-rt", voice="marin", language="ko",
                         greeting=True) -> None:
                self.setup(voice, greeting, {"api_key": api_key, "model": model, "system_prompt": system_prompt,
                                             "language": language})

        self.GeminiRealtime, self.OpenAIRealtime = GeminiRealtime, OpenAIRealtime

    def ClawOpsAgent(self, **kw):
        agent = LoggingAgent(self, **kw)
        self.agents.append(agent)
        return agent


async def _log(voice: str) -> None:
    SDK_LOG.error(OPENAI_ERROR, voice)


def diag(*voices: tuple[str, str], provider="google", call_voice=None) -> VoiceDiag:
    return VoiceDiag(provider=provider, key=GOOGLE_KEY, model="gpt-rt" if provider == "openai" else None,
                     voices=tuple(voices), call_voice=call_voice)


async def test_configured_voices_are_opened_and_closed_without_any_call(world):
    sdk = VoiceSdk(world)
    out = await run(world, sdk, voice=diag((MALE, "Aoede"), (FEMALE, "Charon"), (f"영어 · {UNKNOWN}", "Aoede")))
    assert out["P9"].ok and out["P9"].code == "ok" and out["P9"].data == {"checked": 2}
    assert "전화는 걸지 않았습니다" in out["P9"].detail
    assert sdk.checks == [("GeminiRealtime", "Aoede", False), ("GeminiRealtime", "Charon", False)]  # 같은 이름은 한 번
    assert sdk.stops == 2 and sdk.dialed == [] and out["P5"].ok and out["P11"].ok
    assert "Aoede" not in dump(out) and "Charon" not in dump(out)


@pytest.mark.parametrize("provider", ["google", "openai"])
async def test_a_voice_the_provider_refuses_fails_p9_by_slot_label(world, provider):
    sdk = VoiceSdk(world, bad={"Aoedee"})
    out = await run(world, sdk, voice=diag((MALE, "Aoedee"), (FEMALE, "Charon"), (f"영어 · {UNKNOWN}", "Aoedee"),
                                           provider=provider))
    p9 = out["P9"]
    assert (p9.ok, p9.skipped, p9.code) == (False, False, "voice_rejected")
    assert voice_names.REJECTED in p9.detail and MALE in p9.detail and f"영어 · {UNKNOWN}" in p9.detail
    assert FEMALE not in p9.detail and p9.data == {"checked": 2, "rejected": 1}
    assert "Aoedee" not in dump(out) and ACCOUNT not in dump(out)
    assert sdk.stops == 2 and sdk.dialed == []


async def test_a_voice_check_that_never_answers_is_bounded_and_unconfirmed(world):
    sdk = VoiceSdk(world, slow={"Aoede"})
    out = await run(world, sdk, voice=diag((MALE, "Aoede"), (FEMALE, "Charon")))
    assert out["P9"].code == "voice_unconfirmed" and not out["P9"].ok and MALE in out["P9"].detail
    assert sdk.stops == 2 and world.ms < (voice_names.VOICE_OPEN_S + voice_names.VOICE_STOP_S + 5) * 1000 * 2


async def test_a_refused_key_is_not_blamed_on_the_voice(world):
    out = await run(world, VoiceSdk(world, refused=True), voice=diag((MALE, "Aoede")))
    assert out["P9"].code == "model_connect_failed" and voice_names.REJECTED not in out["P9"].detail


async def test_at_most_eight_voices_are_checked(world):
    sdk = VoiceSdk(world)
    many = tuple((f"{UNKNOWN} {i}", f"Voice{i}") for i in range(11))
    out = await run(world, sdk, voice=diag(*many))
    assert len(sdk.checks) == voice_names.MAX_VOICES and out["P9"].ok
    assert any("앞의 8개만" in note for note in out["P9"].notes)


async def test_no_configured_voice_keeps_the_old_line(world):
    sdk = VoiceSdk(world)
    out = await run(world, sdk)
    assert out["P9"].skipped and out["P9"].code == "not_supported" and sdk.checks == []


@pytest.mark.parametrize(("call_voice", "expected"), [("Puck", "Puck"), (None, "Kore")])
async def test_the_test_call_uses_the_unknown_gender_voice(world, call_voice, expected):
    sdk = VoiceSdk(world)
    out = await run(world, sdk, voice=diag(call_voice=call_voice), steps=(6, 7, 8), call_to=SENTINEL_PHONE)
    assert out["P6"].ok
    assert {kw["voice"] for _, kw in sdk.sessions} == {expected}


async def test_an_openai_error_before_the_agent_speaks_fails_the_test_call(world):
    script = ((1000, "call_start"), (1200, "openai_error"), *GOOD_CALL[1:])
    sdk = VoiceSdk(world, calls=[script])
    out = await run(world, sdk, voice=diag(provider="openai"), steps=(6, 7, 8), call_to=SENTINEL_PHONE)
    assert out["P6"].code == "model_rejected" and not out["P6"].ok
    assert out["P7"].code == out["P8"].code == "skipped_no_model"


async def test_an_openai_error_after_the_agent_spoke_does_not_fail_the_call(world):
    script = (*GOOD_CALL[:2], (1500, "openai_error"), *GOOD_CALL[2:])
    out = await run(world, VoiceSdk(world, calls=[script]), voice=diag(provider="openai"), steps=(6, 7, 8),
                    call_to=SENTINEL_PHONE)
    assert out["P6"].ok and out["P8"].ok


def test_voice_names_are_not_in_repr():
    assert "Aoede" not in repr(diag((MALE, "Aoede"), call_voice="Aoede"))


def test_the_settings_budget_covers_the_voice_checks():
    assert voice_names.BUDGET_S >= voice_names.MAX_VOICES * (voice_names.VOICE_OPEN_S + voice_names.VOICE_SETTLE_S
                                                               + voice_names.VOICE_STOP_S)
    assert dv.LABELS["P9"]  # 줄 이름은 그대로(화면이 쓴다)
