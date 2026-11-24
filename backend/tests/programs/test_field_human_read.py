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
    assert r.status_code == 422 and r.json()["code"] == "photo_respond"


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


# ── 리뷰 11-24: 우회·확인만 하는 사람 판독·반려·경쟁·표식 ─────────────────────────────────────────────────────

def _failed_call_photo(client, who, sid, liner) -> dict:
    liner.push(chat_body("not json"))
    r = client.post(f"/api/schedules/{sid}/field/photos",
                    json={"activity_id": "A", "photo_name": "x.jpg", "photo_data_url": PHOTO}, headers=who)
    return next(i for i in r.json()["items"] if i["kind"] == "photo")


def _retaken_photo(client, admin, who, sid, liner) -> dict:
    item = _upload_dark(client, who, sid, liner)
    client.post(f"/api/schedules/{sid}/field/{item['id']}/retake", json={"reason": "다시"}, headers=admin)
    _upload_dark(client, who, sid, liner)  # 새 사진도 못 읽음 → 옛 줄은 retaken
    return item


@pytest.mark.parametrize("who", ["field", "admin"])
@pytest.mark.parametrize("path", ["retaken", "failed-call"])
def test_photo_rows_never_take_a_hand_answer_and_cannot_be_applied_unread(client, admin, session, sid, liner, fieldman,
                                                                           who, path):
    """리뷰 1(Critical): respond 로 사진 줄에 진도를 넣고 apply 하는 우회를 막는다 — 사진 줄은 respond 를 받지 않고,
    apply 는 AI 판독(verified·risk)이나 사람 판독(human)만 올린다."""
    headers = fieldman if who == "field" else admin
    item = _retaken_photo(client, admin, headers, sid, liner) if path == "retaken" else _failed_call_photo(client, headers, sid, liner)
    before = session.scalars(select(Approval.id)).all()

    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/respond",
                    json={"response_choice": "verified", "reported_progress": 80}, headers=headers)
    assert r.status_code == 422 and r.json()["code"] == "photo_respond"
    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/apply", headers=headers)
    assert r.status_code == 422 and r.json()["code"] == "photo_unread"
    session.expire_all()
    assert session.scalars(select(Approval.id)).all() == before


def test_apply_refuses_a_photo_row_whose_answer_is_not_a_reading(client, admin, session, sid):
    row = FieldItem(schedule_id=sid, kind="photo", activity_id="A", activity_name="작업 A", trade="골조팀", status="responded",
                    title="[AI 사진 판독] A 작업 A", prompt_text="", response_choice="on_track", reported_progress=80, reported_rd=2,
                    response_note="", payload_json={"ai_progress": None, "unread_reason": "모델 답을 읽지 못해 판독하지 않았습니다."})
    session.add(row)
    session.commit()
    r = client.post(f"/api/schedules/{sid}/field/{row.id}/apply", headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "photo_unread"


@pytest.fixture
def at_forty(session) -> int:
    """작업 A 가 이미 40%·잔여 3일로 기록된 일정(사람 판독 값이 지금 기록과 같게)."""
    from dataclasses import replace

    from tests import schedules

    s = schedules.sample()
    acts = tuple(replace(a, progress=0.4, actual_start=date(2027, 3, 1), rd=3) if a.id == "A" else a for a in s.activities)
    return schedules.store(session, replace(s, data_date=date(2027, 3, 3), activities=acts))


def test_a_human_reading_equal_to_the_record_is_recorded_without_a_rule_or_approval(client, admin, session, liner, fieldman,
                                                                                    at_forty):
    """리뷰 2: 사람 값이 지금 기록과 같으면 일정이 바뀌지 않는다 — 내 규칙 승인 건(현장 증빙 확인)을 만들지 않고,
    사진 줄에 확인한 사람 판독(no_change)으로 바로 남긴다."""
    from app.store.tables import MyRule

    item = _upload_dark(client, fieldman, at_forty, liner)
    r = client.post(f"/api/schedules/{at_forty}/field/{item['id']}/human-read",
                    json={"progress": 40, "reason": "그대로"}, headers=admin)

    assert r.status_code == 200, r.json()
    done = _item(r, item["id"])
    assert (done["status"], done["response_choice"], done["reported_progress"], done["approval_id"]) == ("applied", "human", 40, None)
    assert done["payload_json"]["human_read"]["no_change"] is True
    session.expire_all()
    assert session.scalars(select(Approval)).all() == []
    assert session.scalars(select(MyRule)).all() == []
    again = client.post(f"/api/schedules/{at_forty}/field/{item['id']}/apply", headers=admin)
    assert again.status_code == 200 and _item(again, item["id"])["approval_id"] is None  # 다시 눌러도 승인 건이 생기지 않는다


@pytest.mark.parametrize("outcome", ["rejected", "conflict"])
def test_a_rejected_or_conflicted_human_reading_goes_back_to_the_queue_with_its_history(client, admin, session, sid, liner,
                                                                                        fieldman, outcome):
    """리뷰 3: 승인함에서 거부되거나 충돌하면 사진 줄은 다시 사람 판독 대기 — 숫자·승인 건을 떼고, 거부된 시도는 이력에 남긴다."""
    item = _upload_dark(client, fieldman, sid, liner)
    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/human-read", json={"progress": 40, "reason": "x"}, headers=admin)
    aid = _item(r, item["id"])["approval_id"]
    if outcome == "rejected":
        assert client.post(f"/api/approvals/{aid}/decide", json={"decision": "reject"}, headers=admin).status_code == 200
    else:
        client.patch(f"/api/schedules/{sid}/activities/B", json={"od": 9, "base_version": 1}, headers=admin)
        assert client.post(f"/api/approvals/{aid}/decide", json={"decision": "approve"}, headers=admin).status_code == 409

    r = client.get(f"/api/schedules/{sid}/field", headers=fieldman)
    back = _item(r, item["id"])
    assert (back["status"], back["response_choice"], back["reported_progress"], back["approval_id"]) == ("human_wait", "unread", None, None)
    assert "human_read" not in back["payload_json"]
    history = back["payload_json"]["human_history"]
    assert [(h["outcome"], h["progress"], h["approval_id"]) for h in history] == [(outcome, 40, aid)]
    assert r.json()["summary"]["photo_human_wait"] == 1
    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/human-read", json={"progress": 30, "reason": "y"}, headers=admin)
    assert r.status_code == 200 and _item(r, item["id"])["approval_id"] not in (None, aid)


@pytest.mark.parametrize("action", ["human-read", "retake"])
def test_a_stale_waiting_check_cannot_claim_a_photo_twice(client, admin, session, sid, liner, fieldman, action):
    """리뷰 4: 상태 확인과 쓰기 사이에 다른 요청이 먼저 처리하면(같은 줄을 낡게 읽은 세션) 조건부 UPDATE 가 막는다 —
    승인 건이 둘 생기지 않는다."""
    from sqlalchemy.orm import Session

    from app.programs.progress.router import _for  # noqa: F401 - 같은 앱 세션 모양
    from app.store.tables import User as UserRow

    item = _upload_dark(client, fieldman, sid, liner)
    stale = Session(bind=session.get_bind())
    stale_row = stale.get(FieldItem, item["id"])
    assert stale_row.status == "human_wait"  # 낡게 읽어 둔다
    assert client.post(f"/api/schedules/{sid}/field/{item['id']}/human-read",
                       json={"progress": 40, "reason": "먼저"}, headers=admin).status_code == 200

    me = stale.scalars(select(UserRow).where(UserRow.role == "admin")).first()
    with pytest.raises(Exception) as caught:
        if action == "human-read":
            field.human_read(stale, sid, item["id"], field.HumanReadIn(progress=41, reason="나중"), me)
        else:
            field.retake(stale, sid, item["id"], field.RetakeIn(reason="나중"), me)
    assert getattr(caught.value, "code", None) == "not_waiting"
    stale.close()
    session.expire_all()
    assert len(session.scalars(select(Approval)).all()) == 1


def test_new_readings_carry_the_vision_schema_marker(client, admin, sid, liner):
    """리뷰 5: 새 판독에는 vision_v 2 표식을 남긴다(예전 0% 줄과 가를 수 있게). 예전 줄은 바꾸지 않는다."""
    item = _upload_dark(client, admin, sid, liner)
    assert item["payload_json"]["vision_v"] == 2


def test_an_answer_without_readable_is_a_bad_answer(client, admin, sid, liner):
    """리뷰 6: readable 은 기본값 없이 꼭 있어야 한다 — 없으면 모델 답을 읽지 못한 것(대기에 넣지 않고 숫자도 없음)."""
    item = _upload_dark(client, admin, sid, liner, answer={"progress": 40, "reason": "보 두 개가 섰다.", "risks": []})
    assert (item["status"], item["response_choice"], item["reported_progress"]) == ("responded", "unread", None)
    assert item["payload_json"]["unread_reason"] == field.BAD_ANSWER


def test_asking_for_a_retake_again_keeps_the_earlier_requests(client, admin, sid, liner, fieldman):
    item = _upload_dark(client, fieldman, sid, liner)
    url = f"/api/schedules/{sid}/field/{item['id']}/retake"
    client.post(url, json={"reason": "첫 요청"}, headers=admin)
    r = client.post(url, json={"reason": "둘째 요청"}, headers=admin)
    asked = _item(r, item["id"])["payload_json"]
    assert [x["reason"] for x in asked["retakes"]] == ["첫 요청", "둘째 요청"]
    assert asked["retake"]["reason"] == "둘째 요청"  # 화면은 마지막 요청을 본다


def test_unreadable_photos_are_not_counted_as_evidence(client, admin, sid, liner, fieldman):
    """리뷰 6: 「증빙 n건」에 AI 가 못 읽은 사진(대기·요청·다시 올림)을 세지 않는다 — 대기는 따로 센다."""
    _upload_dark(client, fieldman, sid, liner)
    liner.push(chat_body(json.dumps({"readable": True, "unreadable_reason": "", "progress": 40, "reason": "보 두 개가 섰다.",
                                     "risks": []}, ensure_ascii=False)))
    r = client.post(f"/api/schedules/{sid}/field/photos",
                    json={"activity_id": "B", "photo_name": "day.jpg", "photo_data_url": PHOTO}, headers=fieldman)
    s = r.json()["summary"]
    photos = [i for i in r.json()["items"] if i["kind"] == "photo"]
    assert (s["photo_total"], s["photo_human_wait"]) == (len(photos) - 1, 1)


async def test_the_field_tool_hides_phone_numbers_in_free_text(client, admin, session, sid, liner, fieldman):
    """리뷰 6: 에이전트 도구 field.list 는 새로 생긴 자유 글(사람 판독 근거·다시 찍기 까닭·올린 사람 이름)과 회신 메모의 번호를 가린다."""
    from app.store.tables import User as UserRow
    from app.tools.context import ToolContext
    from app.tools.registry import call

    phone = "010-1234-5678"
    item = _upload_dark(client, fieldman, sid, liner)
    client.post(f"/api/schedules/{sid}/field/{item['id']}/retake", json={"reason": f"{phone} 로 전화 주세요"}, headers=admin)
    session.expire_all()
    row = session.get(FieldItem, item["id"])
    row.payload_json = {**row.payload_json, "uploaded_by": {"id": 9, "name": f"박현장 {phone}"},
                        "human_read": {"by": "관리자", "progress": 30, "reason": f"{phone} 확인"}}
    row.response_note = f"메모 {phone}"
    session.commit()
    me = session.scalars(select(UserRow).where(UserRow.role == "admin")).first()
    out = await call("field.list", {"schedule_id": sid, "kind": "photo"}, ToolContext(session=session, user=me, schedule_id=sid,
                                                                                    emit=lambda e: None))
    assert out.ok, out.error
    assert "1234" not in json.dumps(out.output, ensure_ascii=False)
