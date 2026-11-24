"""Task 99 — 고른 음성이 실제 통화의 세션에 쓰인다. `voices.pick` 이 고른 `CallSpec.voice_id` 를 어댑터가 실시간 세션의
`voice=` 로 넘기고, 없으면 넘기지 않아 SDK 기본(구글 Kore · OpenAI marin)이 남는다. 꼴이 틀린 글(번호처럼 보이는 것·빈칸·한글)은
SDK 로 가지 않는다. 가짜 SDK 와 대본 시계는 Task 113 의 시험(test_backend_for)의 것을 그대로 쓴다 — 실제 SDK 는 불러오지 않는다.
"""

from types import SimpleNamespace

import pytest

from app.outreach.voice import voices
from app.outreach.voice.session import END_LOST, END_PEER
from tests.outreach.voice.test_backend_for import (
    SAID,
    SDK_LOG,
    FakeAgent,
    FakeSdk,
    World,
    kat,
    place,
    voice,
)
from tests.outreach.voice.test_simulated import _spec

pytestmark = pytest.mark.usefixtures("time_guard")


@pytest.fixture
def world() -> World:
    return World()


async def _session_kwargs(world: World, spec, v=None) -> tuple[str, dict]:
    sdk = FakeSdk(world)
    await place(kat(world, sdk, v=v), spec)
    return sdk.sessions[-1]


async def test_the_chosen_voice_reaches_the_gemini_session(world):
    kind, kw = await _session_kwargs(world, _spec(voice_id="Puck"))
    assert kind == "GeminiRealtime" and kw["voice"] == "Puck"


async def test_the_chosen_voice_reaches_the_openai_session(world):
    kind, kw = await _session_kwargs(world, _spec(voice_id="cedar"), voice(provider="openai", model="gpt-realtime-test"))
    assert kind == "OpenAIRealtime" and kw["voice"] == "cedar"


@pytest.mark.parametrize(("provider", "model", "default"), [("google", "", "Kore"), ("openai", "gpt-realtime-test", "marin")])
async def test_no_voice_leaves_the_sdk_default(world, provider, model, default):
    _, kw = await _session_kwargs(world, _spec(voice_id=None), voice(provider=provider, model=model))
    assert kw["voice"] == default  # 넘기지 않았다 — 가짜의 기본값은 실제 SDK 의 기본값과 같다


@pytest.mark.parametrize("bad", ["010-0000-0000", "01000000000", "목소리", "Kore voice", "a" * 101, "-Kore", "Kore\n"])
async def test_a_voice_id_of_the_wrong_shape_never_reaches_the_sdk(world, bad):
    _, kw = await _session_kwargs(world, _spec(voice_id=bad))
    assert kw["voice"] == "Kore"


async def test_voices_pick_feeds_the_session(world):
    """설정의 칸(PM 규칙: 상대와 반대 성별) → pick → CallSpec.voice_id → 세션의 voice."""
    settings = SimpleNamespace(voice_male_contact="Aoede", voice_female_contact="Charon", voice_unknown=None,
                               voices_by_language_json={"en": {"voice_male_contact": "Leda"}})
    for gender, language, expected in (("male", "ko", "Aoede"), ("female", "ko", "Charon"), ("male", "en", "Leda")):
        chosen = voices.pick(gender, "auto", None, language, settings)
        _, kw = await _session_kwargs(World(), _spec(voice_id=chosen, language=language))
        assert kw["voice"] == expected
    manual = voices.pick("male", "manual", "Fenrir", "ko", settings)  # 연락처의 직접 지정이 먼저
    _, kw = await _session_kwargs(world, _spec(voice_id=manual))
    assert kw["voice"] == "Fenrir"


# ── 받아쓰기 언어(ASR 보고서 11-24): 구글 SDK 의 language= 는 원격 측정 값뿐이라 받아쓰기 언어를 따로 준다 ─────────


@pytest.mark.parametrize(("language", "sent"), [("ko", {"language_codes": ["ko-KR"]}),
                                                ("en", {"language_codes": ["en-US"]}),
                                                ("vi", {})])  # 표에 없는 언어는 SDK 기본(자동 감지) 그대로
async def test_the_call_language_reaches_the_gemini_transcription(world, language, sent):
    kind, kw = await _session_kwargs(world, _spec(language=language))
    assert kind == "GeminiRealtime" and kw["language"] == language
    assert kw["input_audio_transcription"] == sent


@pytest.mark.parametrize("language", ["ko", "en"])
async def test_openai_transcription_language_rides_on_language(world, language):
    """OpenAI 는 SDK 가 language= 를 받아쓰기(gpt-4o-transcribe) 언어로 이미 쓴다 — 구글 칸은 넘기지 않는다."""
    kind, kw = await _session_kwargs(world, _spec(language=language), voice(provider="openai", model="gpt-realtime-test"))
    assert kind == "OpenAIRealtime" and kw["language"] == language and "input_audio_transcription" not in kw


# ── 고침 1: 꼴 검사는 voices.well_formed 하나 · OpenAI 오류 줄은 세션 실패 ─────────────────────────────


@pytest.mark.parametrize(("value", "ok"), [("Puck", True), ("ko-KR.Wavenet:A_1", True), ("cedar", True), ("v-1", True),
                                           ("010-0000-0000", False), ("01000000000", False), ("목소리", False),
                                           ("Kore voice", False), ("-Kore", False), ("a" * 101, False), ("", False),
                                           (None, False), (7, False)])
def test_well_formed_is_the_one_shape_check(value, ok):
    assert voices.well_formed(value) is ok


OPENAI_ERROR = "OpenAI error: {'type': 'invalid_request_error', 'message': \"Invalid value: 'Puckk'. Supported values are…\"}"


class LoggingAgent(FakeAgent):
    """실제 OpenAIRealtime 처럼 세션 오류를 `clawops.agent` 로거의 ERROR 줄로만 알린다(사건은 오지 않는다)."""

    async def step(self, call, kind, *args):
        if kind == "openai_error" and not call.over:
            SDK_LOG.error(OPENAI_ERROR)
            return None
        return await super().step(call, kind, *args)


class LoggingSdk(FakeSdk):
    def ClawOpsAgent(self, **kw):  # 실제 SDK 의 이름
        agent = LoggingAgent(self, **kw)
        self.agents.append(agent)
        return agent


async def test_an_openai_error_before_the_opening_ends_the_call_as_lost(world, caplog):
    """세션 설정(session.update)이 거절되면 OpenAI 는 오류 사건만 보내고 SDK 는 줄 하나만 남긴다 — 지시문·첫마디·소리 꼴이 빠진
    세션이 그대로 돌지 않게, 첫 발화 전의 그 줄은 세션 실패(END_LOST)다."""
    sdk = LoggingSdk(world, ((1000, "call_start"), (1200, "openai_error"), (1300, "transcript", "assistant", "Hello"),
                             (9000, "call_end")))
    rec = await place(kat(world, sdk, v=voice(provider="openai", model="gpt-realtime-test")), _spec(voice_id="Puckk"))
    assert rec.log[-1][:2] == ("end", END_LOST) and world.ms < 9000
    assert "Puckk" not in str(rec.log)


async def test_an_openai_error_after_the_opening_does_not_cut_a_good_call(world):
    """첫 발화가 나간 뒤의 오류(예: 끝난 응답을 취소)는 통화를 끊지 않는다 — 사람과 하던 통화를 오류 줄 하나로 끊지 않게."""
    sdk = LoggingSdk(world, ((1000, "call_start"), (1300, "transcript", "assistant", SAID), (2000, "openai_error"),
                             (3000, "call_end")))
    rec = await place(kat(world, sdk, v=voice(provider="openai", model="gpt-realtime-test")))
    assert rec.log[-1][:2] == ("end", END_PEER)
