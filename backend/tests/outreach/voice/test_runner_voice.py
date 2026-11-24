"""Task 99 고침 1 — 통화 줄에 저장된 음성(`OutreachCall.voice_id`)의 꼴이 틀리면 SDK 기본으로 떨어지지 않고 연락처·설정의 음성으로
간다(`voices.pick`). 가상 연락처·가상 키, 실제 SDK 없음(SimulatedVoice)."""

import pytest

from app.security import crypto
from app.store.tables_outreach import VoiceSettings
from tests.outreach.harness.test_gate import connect, person
from tests.outreach.voice.test_runner import AGENT_NUMBER, place, plain_call, queued
from tests.outreach_doubles import SENTINEL_KEY

pytestmark = pytest.mark.usefixtures("time_guard")


@pytest.fixture
def world(session, sid):
    """test_runner 의 world 와 같은 꼴: 기본 알림 연결 + 음성 설정 + 연락처 한 사람(모두 가상)."""
    conn = connect(session)
    session.add(VoiceSettings(connection_id=conn.id, provider="google", secret_ciphertext=crypto.encrypt(SENTINEL_KEY),
                              secret_last4="9999", model="sim-model", agent_number=AGENT_NUMBER, voices_by_language_json={},
                              status="ok"))
    who = person(session, sid)
    session.commit()
    return type("World", (), {"conn": conn, "who": who, "sid": sid})


def _settings(session, world, **slots) -> None:
    row = session.get(VoiceSettings, world.conn.id)
    for name, value in slots.items():
        setattr(row, name, value)
    session.commit()


@pytest.mark.parametrize("stored", ["010-0000-0000", "목소리", "Kore voice", "-x"])
async def test_a_stored_call_voice_of_the_wrong_shape_falls_through_to_the_contact_and_settings(session, world, stored):
    _settings(session, world, voice_unknown="Puck")
    row = queued(session, world.who, voice_id=stored)
    sim = await place(row, plain_call())
    assert sim.calls[0].spec.voice_id == "Puck"


async def test_a_well_formed_stored_call_voice_still_wins(session, world):
    _settings(session, world, voice_unknown="Puck")
    row = queued(session, world.who, voice_id="Leda")
    sim = await place(row, plain_call())
    assert sim.calls[0].spec.voice_id == "Leda"
