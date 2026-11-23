"""음성 고르기(Task 87): 직접 지정이 먼저, 아니면 연락처 성별의 칸(언어별 칸이 있으면 그것이 먼저), 없으면 None.
음성 목록은 가상 값이다(실제 목록은 Task 99)."""

import itertools
from types import SimpleNamespace

import pytest

from app.outreach.voice import voices
from app.outreach.voice.session import VoiceInfo
from app.store.tables_outreach import VoiceSettings

# 가상 음성 목록 — 실제 제공사 음성 이름이 아니다
CATALOGUE = (
    VoiceInfo("sim-f1", "가상 여성 1", "female"),
    VoiceInfo("sim-m1", "가상 남성 1", "male"),
    VoiceInfo("sim-n1", "가상 중성 1", "unknown"),
    VoiceInfo("sim-f2", "가상 여성 2", "female"),
    VoiceInfo("sim-m2", "가상 남성 2", "male"),
)


def _settings(**fields) -> SimpleNamespace:
    base = {"voice_male_contact": None, "voice_female_contact": None, "voice_unknown": None,
            "voices_by_language_json": {}}
    return SimpleNamespace(**(base | fields))


# PM 이 설정에서 골라 둔 꼴: 남성 연락처에게는 여성 음성, 여성 연락처에게는 남성 음성, 모르면 중성
FULL = _settings(
    voice_male_contact="sim-f1", voice_female_contact="sim-m1", voice_unknown="sim-n1",
    voices_by_language_json={"en": {"voice_male_contact": "sim-f2", "voice_female_contact": "sim-m2",
                                    "voice_unknown": "sim-n1"},
                             "vi": {"voice_male_contact": "sim-f2"}},
)


def test_pick_manual_wins():
    assert voices.pick("male", "manual", "sim-m2", "ko", FULL) == "sim-m2"
    assert voices.pick("female", "manual", "sim-m2", "en", FULL) == "sim-m2"
    assert voices.pick("unknown", "manual", "sim-m2", "ko", None) == "sim-m2"  # 설정이 없어도 직접 지정은 쓴다


def test_pick_by_contact_gender():
    assert voices.pick("male", "auto", None, "ko", FULL) == "sim-f1"
    assert voices.pick("female", "auto", None, "ko", FULL) == "sim-m1"
    assert voices.pick("unknown", "auto", None, "ko", FULL) == "sim-n1"


def test_pick_language_override():
    assert voices.pick("male", "auto", None, "en", FULL) == "sim-f2"
    assert voices.pick("female", "auto", None, "en", FULL) == "sim-m2"
    # 그 언어에 그 칸이 비어 있으면 기본 칸
    assert voices.pick("male", "auto", None, "vi", FULL) == "sim-f2"
    assert voices.pick("female", "auto", None, "vi", FULL) == "sim-m1"
    assert voices.pick("unknown", "auto", None, "vi", FULL) == "sim-n1"
    # 언어별 칸이 없는 언어는 기본 칸
    assert voices.pick("male", "auto", None, "zh", FULL) == "sim-f1"


def test_pick_none_when_unset():
    for gender in ("male", "female", "unknown"):
        assert voices.pick(gender, "auto", None, "ko", _settings()) is None
        assert voices.pick(gender, "auto", None, "ko", None) is None
    # 다른 성별의 칸만 채워져 있으면 그것을 빌려 쓰지 않는다
    only_male = _settings(voice_male_contact="sim-f1")
    assert voices.pick("female", "auto", None, "ko", only_male) is None
    assert voices.pick("unknown", "auto", None, "ko", only_male) is None


GENDERS = ("male", "female", "unknown")
MODES = ("auto", "manual")
VOICE_IDS = (None, "sim-m2")
LANGUAGE_CASES = ("ko", "en", "vi", "zh")


def _expected(gender: str, mode: str, voice_id: str | None, language: str) -> str | None:
    """구현과 따로 적은 표(FULL 설정 기준)."""
    if mode == "manual" and voice_id:
        return voice_id
    default = {"male": "sim-f1", "female": "sim-m1", "unknown": "sim-n1"}
    by_language = {"en": {"male": "sim-f2", "female": "sim-m2", "unknown": "sim-n1"}, "vi": {"male": "sim-f2"}}
    return by_language.get(language, {}).get(gender) or default[gender]


@pytest.mark.parametrize("gender,mode,voice_id,language", list(itertools.product(GENDERS, MODES, VOICE_IDS, LANGUAGE_CASES)))
def test_pick_over_every_gender_mode_and_language(gender, mode, voice_id, language):
    want = _expected(gender, mode, voice_id, language)
    assert voices.pick(gender, mode, voice_id, language, FULL) == want
    choice = voices.choose(gender, mode, voice_id, language, FULL)
    assert choice.voice_id == want
    if mode == "manual" and voice_id:
        assert (choice.source, choice.slot) == ("manual", None)
    else:
        assert choice.slot == voices.SLOTS[gender]
        assert choice.source == ("language" if language in ("en", "vi") and not (language == "vi" and gender != "male")
                                 else "default")


@pytest.mark.parametrize("gender", GENDERS)
def test_auto_mode_follows_the_pm_rule_of_the_opposite_gender(gender):
    """PM 규칙: 자동이면 상대와 반대 성별의 음성. 칸에 무엇을 넣을지는 PM 이 고르고, 목록에서 어울리는 것을 앞에 세운다."""
    assert voices.OPPOSITE == {"male": "female", "female": "male", "unknown": None}
    suited = voices.suited(CATALOGUE, gender)
    assert sorted(v.id for v in suited) == sorted(v.id for v in CATALOGUE)  # 빼지는 않는다(PM 이 고른다)
    wanted = voices.OPPOSITE[gender]
    if wanted is None:
        assert suited == list(CATALOGUE)
    else:
        head = [v for v in suited if v.gender == wanted]
        assert suited[: len(head)] == head and len(head) == 2
        assert [v.id for v in head] == [v.id for v in CATALOGUE if v.gender == wanted]  # 목록의 차례는 그대로
        assert suited[len(head)].gender == "unknown" and suited[-1].gender == gender  # 같은 성별은 맨 뒤
    # 그 목록의 첫 음성을 칸에 넣어 두면 걸 때 그 음성이 나온다
    settings = _settings(**{voices.SLOTS[gender]: suited[0].id})
    assert voices.pick(gender, "auto", None, "ko", settings) == suited[0].id


def test_slots_are_the_three_settings_columns():
    assert voices.SLOTS == {"male": "voice_male_contact", "female": "voice_female_contact",
                            "unknown": "voice_unknown"}
    assert all(hasattr(VoiceSettings, column) for column in voices.SLOTS.values())


@pytest.mark.parametrize("gender", [None, "", "other", "MALE ", 3])
def test_unrecognised_gender_uses_the_unknown_slot(gender):
    assert voices.pick(gender, "auto", None, "ko", FULL) == "sim-n1"
    assert voices.choose(gender, "auto", None, "ko", FULL).slot == "voice_unknown"


@pytest.mark.parametrize("mode,voice_id", [("manual", None), ("manual", ""), ("manual", "   "), ("auto", "sim-m2"),
                                           (None, "sim-m2"), ("MANUAL", "sim-m2"), ("", "sim-m2")])
def test_manual_needs_both_the_mode_and_an_id(mode, voice_id):
    """직접 지정인데 음성이 비었거나, 자동인데 예전에 고른 음성이 남아 있으면 자동으로 고른다."""
    assert voices.pick("male", mode, voice_id, "ko", FULL) == "sim-f1"
    assert voices.choose("male", mode, voice_id, "ko", FULL).source == "default"


def test_manual_id_is_trimmed():
    assert voices.pick("male", "manual", "  sim-m2 ", "ko", FULL) == "sim-m2"


@pytest.mark.parametrize("by_language", [None, [], "en", 3, {"en": None}, {"en": "sim-f2"}, {"en": ["sim-f2"]},
                                         {"en": {"voice_male_contact": None}}, {"en": {"voice_male_contact": ""}},
                                         {"en": {"voice_male_contact": 7}}, {"en": {"voice_male_contact": "  "}},
                                         {"en": {"male": "sim-f2"}}, {"EN": {"voice_male_contact": "sim-f2"}}])
def test_broken_language_table_falls_back_to_the_default_slot(by_language):
    """저장된 언어별 칸이 틀린 꼴이어도 통화를 막지 않는다 — 기본 칸으로."""
    settings = _settings(voice_male_contact="sim-f1", voices_by_language_json=by_language)
    assert voices.pick("male", "auto", None, "en", settings) == "sim-f1"
    assert voices.choose("male", "auto", None, "en", settings).source == "default"


@pytest.mark.parametrize("slot_value", ["", "   ", 5, None])
def test_blank_slot_is_unset(slot_value):
    settings = _settings(voice_male_contact=slot_value)
    assert voices.pick("male", "auto", None, "ko", settings) is None
    choice = voices.choose("male", "auto", None, "ko", settings)
    assert (choice.voice_id, choice.source, choice.slot) == (None, "none", "voice_male_contact")


@pytest.mark.parametrize("language", ["en", " en ", "EN", "En"])
def test_language_code_is_matched_without_case_or_spaces(language):
    assert voices.pick("male", "auto", None, language, FULL) == "sim-f2"


def test_works_with_the_stored_settings_row():
    """저장소의 VoiceSettings 줄을 그대로 받는다(아직 저장하지 않아 기본값이 채워지지 않은 줄도)."""
    fresh = VoiceSettings(connection_id=1)
    assert voices.pick("male", "auto", None, "ko", fresh) is None
    row = VoiceSettings(connection_id=1, voice_male_contact="sim-f1", voice_female_contact="sim-m1",
                        voice_unknown="sim-n1", voices_by_language_json={"en": {"voice_unknown": "sim-n1"}})
    assert voices.pick("male", "auto", None, "ko", row) == "sim-f1"
    assert voices.pick("unknown", "auto", None, "en", row) == "sim-n1"
    assert voices.choose("unknown", "auto", None, "en", row).source == "language"


def test_pick_never_changes_the_settings():
    by_language = {"en": {"voice_male_contact": "sim-f2"}}
    settings = _settings(voice_male_contact="sim-f1", voices_by_language_json=by_language)
    voices.pick("male", "auto", None, "en", settings)
    assert settings.voices_by_language_json == {"en": {"voice_male_contact": "sim-f2"}}
    assert by_language == {"en": {"voice_male_contact": "sim-f2"}}
