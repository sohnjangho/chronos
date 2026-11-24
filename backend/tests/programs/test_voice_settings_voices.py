"""Task 99 고침 1 — 음성 진단(연결)이 설정한 음성(세 칸 + 언어별)을 칸 이름표와 함께 진단 모듈에 넘기고, 시험 전화는 「성별 모름」
칸의 음성으로 건다. 공급자가 받지 않은 음성(P9 voice_rejected)은 「AI 전화」 상태를 실패로 만든다. 진단 모듈은 대역(Spy)."""

import pytest

from app.notify import diagnostics_voice as dv
from app.notify import voice_names
from app.programs.notify_settings import voice
from tests.programs.test_voice_settings_api import (  # noqa: F401 — no_google 은 autouse fixture(구글을 부르지 않게)
    BASE,
    Spy,
    diag,
    no_google,
    put,
    ready,
    row,
)

MALE, UNKNOWN = "남성 연락처에게 걸 때", "성별 모름"


@pytest.fixture
def spy(monkeypatch) -> Spy:
    found = Spy()
    monkeypatch.setattr(dv, "run_voice_checks", found)
    return found


def test_diagnosis_gets_the_configured_voices_by_slot_label_and_the_call_voice(client, admin, fake_provider, spy):
    cid = ready(client, admin)["id"]
    r = put(client, admin, cid, voice_male_contact="Aoede", voice_unknown="Puck",
            voices_by_language={"en": {"voice_male_contact": "Leda"}, "zh-cn": {"voice_unknown": "Aoede"}})
    assert r.status_code == 200, r.text
    assert diag(client, admin, cid, {}).status_code == 200
    seen = spy.calls[0]["voice"]
    assert seen.voices == ((MALE, "Aoede"), (UNKNOWN, "Puck"), (f"영어 · {MALE}", "Leda"), (f"zh-cn · {UNKNOWN}", "Aoede"))
    assert seen.call_voice == "Puck"


def test_without_voices_the_diagnosis_gets_none_and_the_sdk_default(client, admin, fake_provider, spy):
    conn = ready(client, admin)
    assert diag(client, admin, conn["id"], {}).status_code == 200
    assert spy.calls[0]["voice"].voices == () and spy.calls[0]["voice"].call_voice is None


def test_a_rejected_voice_makes_the_status_failed(client, admin, fake_provider, monkeypatch):
    detail = f"{voice_names.REJECTED}: {MALE}."
    monkeypatch.setattr(dv, "run_voice_checks", Spy({9: row(9, "voice_rejected", detail)}))
    cid = ready(client, admin)["id"]
    assert put(client, admin, cid, voice_male_contact="Aoedee").status_code == 200
    body = diag(client, admin, cid, {}).json()
    p9 = next(s for s in body["steps"] if s["id"] == "P9")
    assert p9["code"] == "voice_rejected" and p9["detail"] == detail
    assert client.get(f"{BASE}/{cid}/voice", headers=admin).json()["status"] == "failed"


def test_the_connection_budget_covers_the_voice_checks():
    assert voice._ceiling((5, 9, 11), 90) - voice._ceiling((5, 11), 90) >= voice_names.BUDGET_S
