"""Task 99 고침 1 — 통화 API 의 voice_id 도 음성 꼴만 받는다(422, 보낸 값은 되풀이하지 않음)."""

import pytest

from tests.programs.test_outreach_calls_api import _call, _person, _url, at_work, conn  # noqa: F401 — fixture

BAD = ["010-0000-0000", "01000000000", "목소리", "Kore voice", "-Kore"]


@pytest.mark.parametrize("voice_id", BAD)
def test_draft_voice_id_is_shape_checked(client, user, session, sid, voice_id):
    pid = _person(session, sid)
    created = client.post(_url(sid, ""), json={"contact_id": pid, "purpose": "타설 확인", "voice_id": voice_id},
                          headers=user)
    draft = _call(session, sid, pid)
    patched = client.patch(_url(sid, f"/{draft.id}"), json={"voice_id": voice_id}, headers=user)
    for r in (created, patched):
        assert r.status_code == 422 and r.json()["code"] == "invalid_request"
        assert voice_id not in r.text


def test_a_well_formed_voice_id_is_still_accepted(client, user, session, sid):
    pid = _person(session, sid)
    draft = _call(session, sid, pid)
    r = client.patch(_url(sid, f"/{draft.id}"), json={"voice_id": "ko-KR.Wavenet:A_1"}, headers=user)
    assert r.status_code == 200 and r.json()["voice_id"] == "ko-KR.Wavenet:A_1"
