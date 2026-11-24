"""사진 사람 판독(PM 11-24): AI 가 못 읽은 사진은 「사람 판독 대기」가 되고, 관리자(설정으로 사용자까지)가 진도·근거를 넣으면
현장 보고와 같은 길(승인함)로 간다. 현장 관리자는 사람 판독·다시 찍기 요청을 못 하고, 올린 사람은 상태를 본다."""

import json
from datetime import date

import pytest
from sqlalchemy import select

from app.agent import context
from app.llm.client import LlmClient
from app.programs.progress import field
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.settings import set_approval_mode
from app.store.tables import Approval, FieldItem, User
from tests.helpers import auth
from tests.llm_doubles import FakeLiner, add_connection, chat_body

PHOTO = "data:image/png;base64,iVBORw0KGgo="
DARK = {"readable": False, "unreadable_reason": "사진이 어두워 작업 상태가 보이지 않습니다.", "progress": None,
        "reason": "야간이라 보가 매달린 것만 보인다.", "risks": []}


@pytest.fixture(autouse=True)
def today_in_the_project(monkeypatch):
    monkeypatch.setattr(context, "today", lambda: date(2027, 3, 3))


@pytest.fixture
def liner(session, monkeypatch) -> FakeLiner:
    add_connection(session)
    fake = FakeLiner()
    monkeypatch.setattr(field, "client_for", lambda s: LlmClient(s, transport=fake.transport))
    return fake


def _headers(session, role: str, name: str) -> dict[str, str]:
    row = User(login_id=f"{role}-{name}", name=name, role=role, password_hash=hash_password("x-pass-123"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


@pytest.fixture
def fieldman(session) -> dict[str, str]:
    return _headers(session, "field", "박현장")


def _item(r, item_id: int) -> dict:
    return next(i for i in r.json()["items"] if i["id"] == item_id)


def _upload_dark(client, who, sid, liner, answer=None) -> dict:
    liner.push(chat_body(json.dumps(answer or DARK, ensure_ascii=False)))
    r = client.post(f"/api/schedules/{sid}/field/photos",
                    json={"activity_id": "A", "photo_name": "night.jpg", "photo_data_url": PHOTO}, headers=who)
    assert r.status_code == 200, r.json()
    return next(i for i in r.json()["items"] if i["kind"] == "photo")


def test_a_photo_the_ai_cannot_read_waits_for_a_human_with_no_number(client, admin, session, sid, liner, fieldman):
    item = _upload_dark(client, fieldman, sid, liner)

    assert (item["status"], item["response_choice"], item["reported_progress"]) == ("human_wait", "unread", None)
    assert item["payload_json"]["ai_progress"] is None
    assert item["payload_json"]["uploaded_by"]["name"] == "박현장"
    r = client.get(f"/api/schedules/{sid}/field", headers=admin)
    assert r.json()["summary"]["photo_human_wait"] == 1
    session.expire_all()
    assert session.get(FieldItem, item["id"]).reported_progress is None


def test_a_failed_call_is_not_put_in_the_human_queue(client, admin, sid, liner):
    """호출 실패·사진 없음은 다시 올리면 되는 것 — 대기에 넣지 않는다(지금처럼 판독하지 않음)."""
    liner.push(chat_body("not json"))
    r = client.post(f"/api/schedules/{sid}/field/photos",
                    json={"activity_id": "A", "photo_name": "x.jpg", "photo_data_url": PHOTO}, headers=admin)
    item = next(i for i in r.json()["items"] if i["kind"] == "photo")
    assert (item["status"], item["response_choice"]) == ("responded", "unread")
    assert r.json()["summary"]["photo_human_wait"] == 0


def test_a_human_reading_goes_to_the_approvals_inbox_and_the_admin_may_approve_it(client, admin, session, sid, liner, fieldman):
    """사람이 넣은 값은 현장 보고와 같은 길(승인함 change 건, 사유 human_read)로 가고, 자동 승인 수준이어도 기다린다.
    넣은 관리자가 스스로 승인할 수 있다(PM 11-24 ②). 기록에는 사람 판독한 이름과 승인한 이름이 따로 남는다."""
    set_approval_mode(session, "auto")
    item = _upload_dark(client, fieldman, sid, liner)
    version = client.get(f"/api/schedules/{sid}", headers=admin).json()["version"]

    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/human-read",
                    json={"progress": 35, "reason": "보 인양 장면뿐 — 반입 대장 대조로 35%"}, headers=admin)

    assert r.status_code == 200, r.json()
    done = _item(r, item["id"])
    assert (done["status"], done["response_choice"], done["reported_progress"]) == ("applied", "human", 35)
    assert done["payload_json"]["ai_progress"] is None  # AI 숫자와 사람 숫자를 섞지 않는다
    assert done["payload_json"]["human_read"]["by"] and done["payload_json"]["human_read"]["progress"] == 35
    session.expire_all()
    row = session.get(Approval, done["approval_id"])
    assert (row.kind, row.status) == ("change", "pending")
    assert "human_read" in row.reasons_json
    assert row.title.endswith("(35%)")
    reader = done["payload_json"]["human_read"]["by"]
    assert any(n.startswith(f"사람 판독 · {reader}") for n in row.summary_json["notes"])
    assert client.get(f"/api/schedules/{sid}", headers=admin).json()["version"] == version  # 기다린다

    r = client.post(f"/api/approvals/{row.id}/decide", json={"decision": "approve"}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    session.expire_all()
    assert session.get(Approval, row.id).decided_by == reader
    assert client.get(f"/api/schedules/{sid}", headers=admin).json()["version"] == version + 1


@pytest.mark.parametrize("action", ["human-read", "retake"])
def test_field_managers_cannot_human_read_or_ask_for_a_retake(client, sid, liner, fieldman, action):
    item = _upload_dark(client, fieldman, sid, liner)
    body = {"progress": 50, "reason": "괜찮아 보임"} if action == "human-read" else {"reason": "다시"}

    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/{action}", json=body, headers=fieldman)

    assert r.status_code == 403 and r.json()["code"] == "human_read_forbidden"


def test_field_managers_cannot_fill_a_waiting_photo_by_the_respond_route(client, sid, liner, fieldman):
    item = _upload_dark(client, fieldman, sid, liner)
    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/respond",
                    json={"response_choice": "verified", "reported_progress": 80}, headers=fieldman)
    assert r.status_code == 422 and r.json()["code"] == "photo_human_read"


def test_users_can_human_read_only_when_the_setting_widens_it(client, admin, session, sid, liner, fieldman):
    who = _headers(session, "user", "김공정")
    item = _upload_dark(client, fieldman, sid, liner)
    url = f"/api/schedules/{sid}/field/{item['id']}/human-read"
    body = {"progress": 30, "reason": "사진 밖 구간은 반입 대장으로"}

    assert client.get("/api/settings/human-read", headers=who).json() == {"role": "admin"}
    assert client.get(f"/api/schedules/{sid}/field", headers=who).json()["can_human_read"] is False
    assert client.post(url, json=body, headers=who).status_code == 403
    assert client.put("/api/settings/human-read", json={"role": "user"}, headers=who).status_code == 403  # 관리자만 바꾼다

    assert client.put("/api/settings/human-read", json={"role": "user"}, headers=admin).json() == {"role": "user"}
    assert client.get(f"/api/schedules/{sid}/field", headers=who).json()["can_human_read"] is True
    assert client.get(f"/api/schedules/{sid}/field", headers=fieldman).json()["can_human_read"] is False
    r = client.post(url, json=body, headers=who)
    assert r.status_code == 200 and _item(r, item["id"])["payload_json"]["human_read"]["by"] == "김공정"


def test_a_retake_request_is_recorded_and_the_uploader_sees_it(client, admin, session, sid, liner, fieldman):
    item = _upload_dark(client, fieldman, sid, liner)

    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/retake",
                    json={"reason": "보가 걸린 자리와 설치된 보가 함께 보이게 낮에 다시 찍어 주세요"}, headers=admin)

    assert r.status_code == 200, r.json()
    asked = _item(r, item["id"])
    assert asked["status"] == "retake" and asked["reported_progress"] is None
    assert asked["payload_json"]["retake"]["reason"].startswith("보가 걸린 자리")
    seen = _item(client.get(f"/api/schedules/{sid}/field", headers=fieldman), item["id"])
    assert seen["status"] == "retake" and seen["payload_json"]["retake"]["by"]
    summary = client.get(f"/api/schedules/{sid}/field", headers=admin).json()["summary"]
    assert (summary["photo_human_wait"], summary["photo_retake"]) == (0, 1)

    # 같은 작업 사진을 다시 올리면 요청 줄은 닫히고 새 줄을 가리킨다
    liner.push(chat_body(json.dumps({"readable": True, "unreadable_reason": "", "progress": 40, "reason": "보 두 개가 섰다.",
                                     "risks": []}, ensure_ascii=False)))
    r = client.post(f"/api/schedules/{sid}/field/photos",
                    json={"activity_id": "A", "photo_name": "day.jpg", "photo_data_url": PHOTO}, headers=fieldman)
    new = next(i for i in r.json()["items"] if i["kind"] == "photo")
    old = _item(r, item["id"])
    assert old["status"] == "retaken" and old["payload_json"]["retake"]["replaced_by"] == new["id"]
    assert r.json()["summary"]["photo_retake"] == 0


def test_only_a_waiting_photo_can_be_human_read(client, admin, session, sid, liner):
    liner.push(chat_body(json.dumps({"readable": True, "unreadable_reason": "", "progress": 40, "reason": "보 두 개가 섰다.",
                                     "risks": []}, ensure_ascii=False)))
    r = client.post(f"/api/schedules/{sid}/field/photos",
                    json={"activity_id": "A", "photo_name": "day.jpg", "photo_data_url": PHOTO}, headers=admin)
    item = next(i for i in r.json()["items"] if i["kind"] == "photo")
    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/human-read", json={"progress": 90, "reason": "x"}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "not_waiting"


@pytest.mark.parametrize("progress", [-1, 101, None])
def test_human_progress_must_be_a_number_from_0_to_100(client, admin, sid, liner, fieldman, progress):
    item = _upload_dark(client, fieldman, sid, liner)
    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/human-read",
                    json={"progress": progress, "reason": "근거"}, headers=admin)
    assert r.status_code == 422
    assert client.get(f"/api/schedules/{sid}/field", headers=admin).json()["summary"]["photo_human_wait"] == 1


def test_attention_counts_waiting_photos_for_those_who_can_human_read(client, admin, session, sid, liner, fieldman):
    _upload_dark(client, fieldman, sid, liner)

    mine = next(i for i in client.get("/api/attention", headers=admin).json()["items"] if i["id"] == sid)
    theirs = next(i for i in client.get("/api/attention", headers=fieldman).json()["items"] if i["id"] == sid)

    assert (mine["human_read_wait"], theirs["human_read_wait"]) == (1, 0)
    assert session.scalars(select(FieldItem).where(FieldItem.status == "human_wait")).first() is not None
