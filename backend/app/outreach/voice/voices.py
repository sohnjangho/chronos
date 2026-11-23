"""음성 고르기(Task 87). 직접 지정이 먼저, 아니면 연락처 성별의 칸 — 그 언어의 칸이 있으면 그것, 없으면 기본 칸, 없으면 None.

- 칸(SLOTS)은 voice_settings 의 세 열이다: 남성 연락처 → voice_male_contact, 여성 연락처 → voice_female_contact,
  모름(그 밖의 값 모두) → voice_unknown. 다른 성별의 칸을 빌려 쓰지 않는다.
- voices_by_language_json 은 {언어: {칸: 음성 id}}. 꼴이 틀리거나 그 칸이 비었으면 기본 칸으로(통화를 막지 않는다).
- 직접 지정은 방식이 "manual" 이고 음성 id 가 있을 때만. 자동인데 예전에 고른 id 가 남아 있으면 쓰지 않는다.
- PM 규칙: 자동이면 상대와 반대 성별의 음성(OPPOSITE). 칸에 무엇을 넣을지는 PM 이 설정에서 고르고, suited 가 음성 목록에서
  어울리는 것을 앞에 세워 준다(빼지는 않는다). settings 는 읽기만 한다(없으면 None).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.outreach.voice.session import VoiceInfo

SLOTS = {"male": "voice_male_contact", "female": "voice_female_contact", "unknown": "voice_unknown"}
OPPOSITE = {"male": "female", "female": "male", "unknown": None}


@dataclass(frozen=True)
class Choice:
    """고른 음성과 그 까닭. source: manual(직접 지정) · language(그 언어의 칸) · default(기본 칸) · none(고르지 못함)."""

    voice_id: str | None
    source: Literal["manual", "language", "default", "none"]
    slot: str | None  # 본 칸(직접 지정이면 None)


def _id(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def choose(contact_gender: object, contact_voice_mode: object, contact_voice_id: object, language: object,
           settings: object) -> Choice:
    """고른 음성과 어디서 왔는지(설정 화면·기록이 까닭을 보여 줄 때 쓴다)."""
    manual = _id(contact_voice_id)
    if contact_voice_mode == "manual" and manual:
        return Choice(manual, "manual", None)
    slot = SLOTS[contact_gender if isinstance(contact_gender, str) and contact_gender in SLOTS else "unknown"]
    by_language = getattr(settings, "voices_by_language_json", None)
    code = language.strip().lower() if isinstance(language, str) else ""
    for_language = by_language.get(code) if isinstance(by_language, dict) else None
    found = _id(for_language.get(slot)) if isinstance(for_language, dict) else None
    if found:
        return Choice(found, "language", slot)
    found = _id(getattr(settings, slot, None))
    return Choice(found, "default" if found else "none", slot)


def pick(contact_gender: object, contact_voice_mode: object, contact_voice_id: object, language: object,
         settings: object) -> str | None:
    """그 연락처에게 걸 때 쓸 음성 id(없으면 None — 백엔드의 기본 음성)."""
    return choose(contact_gender, contact_voice_mode, contact_voice_id, language, settings).voice_id


def suited(catalogue: Sequence[VoiceInfo], contact_gender: object) -> list[VoiceInfo]:
    """음성 목록을 그 성별의 연락처에게 어울리는 차례로: 반대 성별 → 성별 모름 → 같은 성별(각 안에서는 목록의 차례 그대로)."""
    wanted = OPPOSITE.get(contact_gender) if isinstance(contact_gender, str) else None
    if wanted is None:
        return list(catalogue)
    rank = {wanted: 0, "unknown": 1}
    return sorted(catalogue, key=lambda voice: rank.get(voice.gender, 2))
