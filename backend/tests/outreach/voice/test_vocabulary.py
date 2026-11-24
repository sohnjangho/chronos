"""통화 받아쓰기 낱말(11-24): 구글 Live 세션의 `input_audio_transcription.custom_vocabulary` 에 그 통화의 현장 이름·작업 이름과
건설 낱말을 넣어 받아쓰기가 「가람 물류센터」「타설」을 바르게 적게 한다. 받아쓰기 언어(language_codes)는 그대로다.

- 낱말은 site_name.vocabulary 가 짓는다: 부를 이름·다듬은 이름 → 건설 낱말 → 작업 이름(겹침 없이·빈칸 맞춤·40자까지·번호처럼
  보이는 것은 뺌·모두 100개까지). 거는 통화와 현장이 정해진 받는 통화는 그 현장, 현장을 모르는 받는 통화는 모든 프로젝트의 이름만.
- CallSpec.vocabulary 로 어댑터까지 간다. 시험은 지은 설정만 본다 — 망·실제 SDK 세션은 없다(가짜 SDK). 이름·번호는 가상이다.
"""

from datetime import UTC, datetime

import pytest

from app.outreach import site_name
from app.outreach.harness import door
from app.outreach.voice import inbound, numbers
from app.security import crypto
from app.store.tables import ProjectProfile, ScheduleRecord
from app.store.tables_outreach import VoiceSettings
from tests import schedules
from tests.outreach.harness.test_gate import PHONE, connect, person
from tests.outreach.voice.test_backend_for import FakeSdk, World, kat, place
from tests.outreach.voice.test_runner import AGENT_NUMBER, plain_call, queued
from tests.outreach.voice.test_runner import place as place_call
from tests.outreach.voice.test_simulated import _spec
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY, SENTINEL_PHONE

pytestmark = pytest.mark.usefixtures("time_guard")


def _named(session, sid: int, name: str, spoken: str = "") -> None:
    session.get(ScheduleRecord, sid).name = name
    if spoken:
        session.add(ProjectProfile(schedule_id=sid, spoken_name=spoken))
    session.commit()


# ── 설정 꼴 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(("language", "words", "sent"), [
    ("ko", ("가람 물류센터", "타설"), {"language_codes": ["ko-KR"], "custom_vocabulary": ["가람 물류센터", "타설"]}),
    ("ko", (), {"language_codes": ["ko-KR"]}),  # 낱말이 없으면 전과 같다
    ("vi", ("가람",), {"custom_vocabulary": ["가람"]}),  # 표에 없는 언어는 자동 감지 + 낱말
])
def test_transcription_config_carries_the_vocabulary(language, words, sent):
    assert numbers.google_transcription(language, words) == sent


async def test_the_vocabulary_reaches_the_gemini_session():
    sdk = FakeSdk(world := World())
    await place(kat(world, sdk), _spec(vocabulary=("가람 물류센터", "타설")))
    _, kw = sdk.sessions[-1]
    assert kw["input_audio_transcription"] == {"language_codes": ["ko-KR"], "custom_vocabulary": ["가람 물류센터", "타설"]}


def test_a_call_spec_drops_vocabulary_words_that_look_like_numbers_instead_of_failing_the_call():
    """낱말이 통화를 막지 않는다: 번호처럼 보이는 낱말(그 통화의 번호를 띄어 쓴 것 포함)은 빼고 통화는 만든다."""
    spaced = " ".join(SENTINEL_DIGITS[i:i + 4] for i in range(0, len(SENTINEL_DIGITS), 4))
    spec = _spec(vocabulary=("가람", f"문의 {SENTINEL_PHONE}", spaced, "1588-0000", "타설"))
    assert spec.vocabulary == ("가람", "타설")


# ── 낱말 짓기 ─────────────────────────────────────────────────────────


def test_vocabulary_is_site_names_then_construction_words_then_activities(session, sid):
    _named(session, sid, "가람 물류센터 신축 2026-11-23", spoken="가람 물류센터")

    words = site_name.vocabulary(session, [sid])

    # 건설 낱말이 먼저(100 개 상한에 잘리지 않게), 그다음 현장 이름, 그다음 작업 이름
    assert words[:len(site_name.CONSTRUCTION_WORDS)] == site_name.CONSTRUCTION_WORDS
    assert words[len(site_name.CONSTRUCTION_WORDS):][:2] == ("가람 물류센터", "가람 물류센터 신축")
    assert {"타설", "양생", "준공", "협력사", "소장님", "현장"} <= set(words)
    assert {"작업 A", "작업 B"} <= set(words)
    assert len(words) == len(set(words)) and "가람 물류센터 신축 2026-11-23" not in words


def test_vocabulary_is_bounded_and_has_no_numbers(session, monkeypatch):
    sid = schedules.store(session, schedules.sample())
    long = "가" * 41
    names = {f"A{i}": f"작업 이름 {i}" for i in range(300)} | {"X": long, "Y": f"연락 {SENTINEL_PHONE}", "Z": "  작업 이름 1  "}
    monkeypatch.setattr(site_name.facts, "names", lambda _session, _sid: names)

    words = site_name.vocabulary(session, [sid])

    assert len(words) == site_name.MAX_VOCABULARY and set(site_name.CONSTRUCTION_WORDS) <= set(words)
    assert all(len(word) <= site_name.MAX_PHRASE for word in words) and long not in words
    assert not any(SENTINEL_PHONE in word or "[번호]" in word for word in words)
    assert words.count("작업 이름 1") == 1


def test_without_activities_only_project_names_and_construction_words(session, sid):
    other = schedules.store(session, schedules.sample())
    _named(session, sid, "가람 물류센터", spoken="가람")
    _named(session, other, "나래 아파트 (v2)")

    words = site_name.vocabulary(session, [sid, other], activities=False)

    assert {"가람", "가람 물류센터", "나래 아파트", "타설"} <= set(words) and "작업 A" not in words
    assert "나래 아파트 (v2)" not in words  # 전체 이름(날짜·판 표시가 섞인 것)은 싣지 않는다


# ── 통화에 붙는 낱말 ───────────────────────────────────────────────────


@pytest.fixture
def voice_world(session, sid):
    conn = connect(session, inbound_mode="all")
    session.add(VoiceSettings(connection_id=conn.id, provider="google", secret_ciphertext=crypto.encrypt(SENTINEL_KEY),
                              secret_last4="9999", model="sim-model", agent_number=AGENT_NUMBER, voices_by_language_json={},
                              status="ok"))
    session.commit()
    return conn


async def test_an_outbound_call_gets_its_site_and_activity_words(session, sid, voice_world):
    _named(session, sid, "가람 물류센터 신축 2026-11-23", spoken="가람 물류센터")
    row = queued(session, person(session, sid))

    spec = (await place_call(row, plain_call())).calls[0].spec

    assert spec.vocabulary == site_name.vocabulary(session, [sid])
    assert "가람 물류센터" in spec.vocabulary and "작업 A" in spec.vocabulary


def test_an_inbound_call_from_a_known_site_gets_that_site(session, sid, voice_world):
    _named(session, sid, "가람 물류센터 신축", spoken="가람 물류센터")
    person(session, sid)
    session.commit()

    spec, _ = inbound._spec(session, door.resolve(session, PHONE, now=datetime.now(UTC)))

    assert spec.vocabulary == site_name.vocabulary(session, [sid])


def test_an_inbound_call_without_a_site_gets_every_project_name_only(session, sid, voice_world):
    other = schedules.store(session, schedules.sample())
    _named(session, sid, "가람 물류센터 신축", spoken="가람 물류센터")
    _named(session, other, "나래 아파트")

    spec, _ = inbound._spec(session, door.resolve(session, "01000000155", now=datetime.now(UTC)))

    assert spec.vocabulary == site_name.vocabulary(session, [sid, other], activities=False)
    assert "나래 아파트" in spec.vocabulary and "작업 A" not in spec.vocabulary


def test_a_vocabulary_error_falls_back_to_construction_words(session, sid, monkeypatch):
    def broken(*_args):
        raise RuntimeError("일정을 읽지 못함")

    monkeypatch.setattr(site_name.facts, "names", broken)
    assert site_name.vocabulary(session, [sid]) == site_name.CONSTRUCTION_WORDS


async def test_a_broken_vocabulary_never_stops_the_call(session, sid, voice_world, monkeypatch):
    monkeypatch.setattr(site_name.facts, "names", lambda *_: (_ for _ in ()).throw(RuntimeError("x")))
    row = queued(session, person(session, sid))

    spec = (await place_call(row, plain_call())).calls[0].spec

    assert spec.vocabulary == site_name.CONSTRUCTION_WORDS


def test_diagnosis_vocabulary_is_construction_words_and_the_first_project_names(session, sid):
    other = schedules.store(session, schedules.sample())
    _named(session, sid, "가람 물류센터 신축 2026-11-23", spoken="가람 물류센터")
    _named(session, other, "나래 아파트")

    words = site_name.diagnosis_vocabulary(session)

    assert words == site_name.vocabulary(session, [sid], activities=False)
    assert "가람 물류센터" in words and "나래 아파트" not in words and "작업 A" not in words
    assert site_name.diagnosis_vocabulary(session) == words  # 매번 같다


def test_diagnosis_vocabulary_without_projects_is_construction_words(session):
    assert site_name.diagnosis_vocabulary(session) == site_name.CONSTRUCTION_WORDS
