"""Task 99 — 고른 음성이 실제 통화의 세션에 쓰인다. `voices.pick` 이 고른 `CallSpec.voice_id` 를 어댑터가 실시간 세션의
`voice=` 로 넘기고, 없으면 넘기지 않아 SDK 기본(구글 Kore · OpenAI marin)이 남는다. 꼴이 틀린 글(번호처럼 보이는 것·빈칸·한글)은
SDK 로 가지 않는다. 가짜 SDK 와 대본 시계는 Task 113 의 시험(test_backend_for)의 것을 그대로 쓴다 — 실제 SDK 는 불러오지 않는다.
"""

from types import SimpleNamespace

import pytest

from app.outreach.voice import voices
from tests.outreach.voice.test_backend_for import FakeSdk, World, kat, place, voice
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
