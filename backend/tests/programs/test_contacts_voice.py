"""Task 99 고침 1 — 사람의 음성 「직접 지정」 id 가 전화번호처럼 보이면 받지 않는다(422 invalid_voice, 값은 되풀이하지 않음)."""

import pytest

from tests.programs.test_contacts_api import _company, _person, _url

PHONE_LIKE = ("invalid_voice", "음성 id 가 전화번호처럼 보입니다. 공급자의 음성 이름을 넣어 주세요.")


@pytest.mark.parametrize("voice_id", ["01000000000", "010-0000-0000", "07000000100"])
def test_a_phone_looking_voice_id_is_refused(client, user, sid, voice_id):
    company = _company(client, user, sid)
    pid = _person(client, user, sid, company, voice_mode="manual", voice_id="Puck")["id"]
    created = client.post(_url(sid, "/people"), json={"name": "음성", "company_id": company, "voice_mode": "manual",
                                                      "voice_id": voice_id}, headers=user)
    patched = client.patch(_url(sid, f"/people/{pid}"), json={"voice_id": voice_id}, headers=user)
    for r in (created, patched):
        assert (r.status_code, r.json()["code"], r.json()["message"]) == (422, *PHONE_LIKE)
        assert voice_id not in r.text
