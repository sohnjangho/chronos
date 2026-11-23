"""현장 허브 API(/api/schedules/{id}/field...): 체크인 반영·사진 판독."""

import json
from dataclasses import replace
from datetime import date

import httpx
import pytest
from sqlalchemy import func, select

from app.agent import context
from app.llm.client import LlmClient
from app.programs.progress import field
from app.store.tables import Approval, DelayEvent, FieldItem, LlmCall, User
from tests import schedules
from tests.llm_doubles import FakeLiner, add_connection, chat_body

PHOTO = "data:image/png;base64,iVBORw0KGgo="


@pytest.fixture(autouse=True)
def today_in_the_project(monkeypatch):
    """현장 회신의 「오늘」(Data Date 가 없을 때)을 착공(2027-03-01) 뒤로 — 실적은 착공일 앞일 수 없다(재확인 2).
    실제 오늘을 쓰는 시험은 스스로 바꿔 끼운다."""
    monkeypatch.setattr(context, "today", lambda: date(2027, 3, 3))


@pytest.fixture
def liner(session, monkeypatch) -> FakeLiner:
    """사진 판독이 부르는 그림 읽기 모델 자리에 대본 LLM 을 끼운다(네트워크 없음)."""
    add_connection(session)
    fake = FakeLiner()
    monkeypatch.setattr(field, "client_for", lambda s: LlmClient(s, transport=fake.transport))
    return fake


def _upload(client, admin, sid, **body) -> httpx.Response:
    return client.post(
        f"/api/schedules/{sid}/field/photos",
        json={"activity_id": "A", "photo_name": "rebar.jpg", "note": "1층 철근 배근 1차 완료, 거푸집 조립 중", **body},
        headers=admin,
    )


def _newest_photo(r) -> dict:
    return next(i for i in r.json()["items"] if i["kind"] == "photo")


def _count(session, table) -> int:
    session.expire_all()
    return session.scalar(select(func.count()).select_from(table))


def _pending_checkin(client, admin, sid, aid="B") -> dict:
    r = client.post(f"/api/schedules/{sid}/field/checkins/dispatch", json={"activity_ids": [aid]}, headers=admin)
    assert r.status_code == 200, r.json()
    return next(i for i in r.json()["items"] if i["kind"] == "checkin" and i["activity_id"] == aid and i["status"] == "pending")


def test_delayed_checkin_raises_only_its_approval_and_no_delay_event(client, admin, session, sid):
    """F2: 「지연 우려」 회신을 반영해도 지연 사건을 따로 만들지 않는다(승인 건 1개만)."""
    item = _pending_checkin(client, admin, sid)
    r = client.post(
        f"/api/schedules/{sid}/field/{item['id']}/respond",
        json={"response_choice": "delayed", "reported_progress": 30, "reported_rd": 6, "response_note": "자재 반입 지연"},
        headers=admin,
    )
    assert r.status_code == 200, r.json()
    approvals_before = _count(session, Approval)

    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/apply", headers=admin)

    assert r.status_code == 200, r.json()
    assert _count(session, DelayEvent) == 0
    assert _count(session, Approval) == approvals_before + 1
    applied = next(i for i in r.json()["items"] if i["id"] == item["id"])
    assert applied["status"] == "applied" and applied["approval_id"] is not None


def test_photo_is_read_by_the_vision_model_once(client, admin, session, sid, liner):
    """F1: 사진이 있으면 그림 읽기(vision) 모델을 한 번 불러 그 답의 진도·까닭을 카드에 넣고 llm_calls 에 남긴다."""
    liner.push(chat_body(json.dumps({"progress": 40, "reason": "철근 배근은 끝났고 거푸집은 절반쯤 섰다.", "risks": []})))

    r = _upload(client, admin, sid, photo_data_url=PHOTO)

    assert r.status_code == 200, r.json()
    assert len(liner.bodies) == 1
    user_parts = liner.last_body["messages"][-1]["content"]
    assert {"type": "image_url", "image_url": {"url": PHOTO}} in user_parts
    assert "1층 철근 배근 1차 완료" in json.dumps(user_parts, ensure_ascii=False)
    item = _newest_photo(r)
    assert item["reported_progress"] == 40
    assert item["payload_json"]["ai_progress"] == 40
    assert item["payload_json"]["ai_reason"] == "철근 배근은 끝났고 거푸집은 절반쯤 섰다."
    assert "confidence" not in item["payload_json"]
    session.expire_all()
    assert [c.purpose for c in session.scalars(select(LlmCall))] == ["vision"]


def test_photo_without_picture_is_not_read_and_cannot_be_applied(client, admin, session, sid, liner):
    """F1: 사진이 없으면(샘플 단추) 부르지 않고 진도 값을 만들지 않는다. 상신은 422."""
    r = _upload(client, admin, sid)

    assert r.status_code == 200, r.json()
    assert liner.bodies == []
    item = _newest_photo(r)
    assert item["reported_progress"] is None
    assert item["payload_json"]["ai_progress"] is None
    assert "사진" in item["payload_json"]["unread_reason"]
    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/apply", headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "photo_unread"
    assert _count(session, Approval) == 0


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(500, json={"error": "boom"}), chat_body(json.dumps({"progress": 140, "reason": "?", "risks": []}))],
    ids=["call-failed", "out-of-range"],
)
def test_failed_vision_call_leaves_the_photo_unread_with_its_reason(client, admin, session, sid, liner, answer):
    """F1: 호출이 실패하거나 답을 쓸 수 없으면 판독하지 않음 + 까닭. 지어낸 숫자는 없다."""
    liner.push(answer)

    r = _upload(client, admin, sid, photo_data_url=PHOTO)

    assert r.status_code == 200, r.json()
    item = _newest_photo(r)
    assert item["reported_progress"] is None and item["payload_json"]["ai_progress"] is None
    assert item["payload_json"]["unread_reason"]
    assert item["payload_json"]["photo_data_url"] == PHOTO
    assert client.post(f"/api/schedules/{sid}/field/{item['id']}/apply", headers=admin).status_code == 422


def test_a_phone_photo_shrunk_to_1280px_fits_the_upload_limit(client, admin, sid, liner):
    """리뷰 I-2: 브라우저가 긴 변 1280px·JPEG 0.7 로 줄인 휴대폰 사진(base64 ~1MB)이 422 없이 판독까지 간다.
    한도는 그림 읽기 한도(agent.image_turn.IMAGE_MAX_BYTES, 5MiB) 안이다."""
    from app.agent.image_turn import IMAGE_MAX_BYTES

    liner.push(chat_body(json.dumps({"progress": 40, "reason": "철근 배근은 끝났다.", "risks": []})))
    big = "data:image/jpeg;base64," + "A" * 1_000_000
    r = _upload(client, admin, sid, photo_data_url=big)
    assert r.status_code == 200, r.json()
    assert _newest_photo(r)["reported_progress"] == 40
    assert field.PHOTO_DATA_URL_MAX < IMAGE_MAX_BYTES
    too_big = _upload(client, admin, sid, photo_data_url="data:image/jpeg;base64," + "A" * field.PHOTO_DATA_URL_MAX)
    assert too_big.status_code == 422


def test_seeded_example_photo_has_no_made_up_reading(client, admin, sid):
    """F1: 처음 채우는 예시 사진 항목도 판독하지 않음이다(지어낸 진도·신뢰도 없음)."""
    r = client.get(f"/api/schedules/{sid}/field", headers=admin)

    item = _newest_photo(r)
    assert item["reported_progress"] is None and item["payload_json"]["ai_progress"] is None
    assert item["payload_json"]["unread_reason"] and "confidence" not in item["payload_json"]


def test_approval_requester_is_the_signed_in_person(client, admin, session, sid):
    """F7: 현장 반영 승인 건의 요청자는 로그인한 사람 이름 하나다(가상 공종 담당자 이름과 섞지 않는다)."""
    item = _pending_checkin(client, admin, sid)
    client.post(
        f"/api/schedules/{sid}/field/{item['id']}/respond",
        json={"response_choice": "on_track", "reported_progress": 50, "response_note": ""},
        headers=admin,
    )
    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/apply", headers=admin)

    approval_id = next(i for i in r.json()["items"] if i["id"] == item["id"])["approval_id"]
    session.expire_all()
    me = session.scalars(select(User).where(User.login_id == "admin")).one()
    assert session.get(Approval, approval_id).requested_by == me.name


REAL_TODAY = date(2026, 11, 23)  # 실제 오늘 — Data Date(2027-03-04)와 멀다
DATA_DATE = date(2027, 3, 4)


@pytest.fixture
def dated_sid(session, monkeypatch) -> int:
    """Data Date 가 실제 오늘과 먼 일정: A(3일) → B(2일), 착공 2027-03-01, Data Date 2027-03-04(A·B 둘 다 아직 시작 전)."""
    monkeypatch.setattr(context, "today", lambda: REAL_TODAY)
    return schedules.store(session, replace(schedules.sample(), data_date=DATA_DATE))


def _checkin_approval(client, admin, session, sid, aid: str, progress: int) -> Approval:
    item = _pending_checkin(client, admin, sid, aid)
    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/respond",
                    json={"response_choice": "on_track", "reported_progress": progress, "reported_rd": 1,
                          "response_note": ""}, headers=admin)
    assert r.status_code == 200, r.json()
    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/apply", headers=admin)
    assert r.status_code == 200, r.json()
    approval_id = next(i for i in r.json()["items"] if i["id"] == item["id"])["approval_id"]
    session.expire_all()
    return session.get(Approval, approval_id)


def _snapshot(row: Approval, aid: str) -> dict:
    return next(a for a in row.snapshot_json["activities"] if a["id"] == aid)


def test_checkin_start_is_the_data_date_not_the_real_today(client, admin, session, dated_sid):
    """#18(재확인): 현장 회신으로 넣는 실제 시작은 일정의 Data Date 다(실제 오늘 아님). 선행이 막지 않으면 알릴 것도 없다."""
    row = _checkin_approval(client, admin, session, dated_sid, "A", 30)
    a = _snapshot(row, "A")
    assert a["actual_start"] == DATA_DATE.isoformat() and a["actual_finish"] is None
    assert row.snapshot_json["data_date"] == DATA_DATE.isoformat()
    assert not row.summary_json.get("notes")
    done = _checkin_approval(client, admin, session, dated_sid, "B", 100)
    assert (_snapshot(done, "B")["actual_start"], _snapshot(done, "B")["actual_finish"]) == (DATA_DATE.isoformat(),) * 2


def test_checkin_start_earlier_than_the_predecessors_allow_is_shown_in_the_summary(client, admin, session, dated_sid):
    """#18(재확인): B 의 선행 A 가 아직이라 계산상 가장 이른 시작은 Data Date 뒤다. 실제 시작을 Data Date 로 넣되 그 사실을
    승인 요약(summary.notes)에 남긴다 — Data Date 보다 늦게는 넣지 않는다."""
    row = _checkin_approval(client, admin, session, dated_sid, "B", 30)
    assert _snapshot(row, "B")["actual_start"] == DATA_DATE.isoformat()
    notes = row.summary_json["notes"]
    assert len(notes) == 1 and "B" in notes[0] and "2027-03-04" in notes[0] and "2027-03-09" in notes[0]
    assert "선행" in notes[0]


def test_a_data_date_on_a_day_off_is_named_as_the_reason_not_a_predecessor(client, admin, session, monkeypatch):
    """리뷰: Data Date 가 쉬는 날(토요일)이라 가장 이른 시작이 뒤로 밀린 것뿐이면 그렇게 적는다(선행·제약 탓으로 적지 않는다).
    선행 탓이면 예전 글 그대로."""
    monkeypatch.setattr(context, "today", lambda: REAL_TODAY)
    saturday = date(2027, 3, 6)
    sid = schedules.store(session, replace(schedules.sample(), data_date=saturday))
    a = _checkin_approval(client, admin, session, sid, "A", 30)
    assert _snapshot(a, "A")["actual_start"] == "2027-03-06"
    assert a.summary_json["notes"] == [
        "A 작업 A: 실제 시작을 Data Date 2027-03-06로 넣었습니다 — 그날은 달력상 쉬는 날이라 계산상 가장 이른 시작은 2027-03-08입니다."]
    b = _checkin_approval(client, admin, session, sid, "B", 30)
    (note,) = b.summary_json["notes"]
    assert "선행 작업" in note and "쉬는 날" not in note


LEGACY = "판독하지 않음 — 이전 방식으로 만든 항목입니다. 사진을 다시 올려 주세요"


def _legacy_photo(session, sid) -> int:
    """F1 이전에 만든 사진 항목: 판독 까닭(ai_reason)도 못 읽은 까닭(unread_reason)도 없고 숫자는 지어낸 것."""
    row = FieldItem(schedule_id=sid, kind="photo", activity_id="A", activity_name="작업 A", trade="골조팀", status="responded",
                    title="[AI 사진 판독] A 작업 A", prompt_text="", response_choice="verified", reported_progress=62,
                    reported_rd=3, response_note="거푸집 조립 단계", payload_json={"photo_name": "old.jpg", "ai_progress": 62,
                                                                               "ai_stage": "거푸집 조립 단계"})
    session.add(row)
    session.commit()
    return row.id


def test_an_old_made_up_photo_reading_is_shown_as_unread_without_changing_the_row(client, admin, session, sid):
    """리뷰 I-3: 예전 방식의 사진 항목은 판독하지 않음으로 보이고(숫자 없음) 상신할 수 없다. 저장된 줄은 그대로."""
    client.get(f"/api/schedules/{sid}/field", headers=admin)  # 예시 항목을 먼저 채운다
    item_id = _legacy_photo(session, sid)
    r = client.get(f"/api/schedules/{sid}/field", headers=admin)
    item = next(i for i in r.json()["items"] if i["id"] == item_id)
    assert (item["response_choice"], item["reported_progress"]) == ("unread", None)
    assert item["payload_json"]["ai_progress"] is None
    assert "판독하지 않음 — " + item["payload_json"]["unread_reason"] == LEGACY
    r = client.post(f"/api/schedules/{sid}/field/{item_id}/apply", headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "photo_unread"
    session.expire_all()
    row = session.get(FieldItem, item_id)
    assert (row.response_choice, row.reported_progress, row.payload_json["ai_progress"]) == ("verified", 62, 62)
    assert "unread_reason" not in row.payload_json


# ── 재확인 #14: 예전 방식(판독 없이 지어낸 숫자)의 사진 항목에서 나온 승인 건은 반영할 수 없다 ──────────────
OLD_READING = "이전 방식으로 만든 판독이라 반영할 수 없습니다 — 사진을 다시 올려 주세요"


def _photo_approval(client, admin, session, sid, payload: dict) -> tuple[int, int]:
    """사진 항목 하나와 그 항목이 낸 승인 대기 건(예전 상신을 흉내 낸다: 체크인으로 승인 건을 만들고 사진 항목에 단다)."""
    approval_id = _checkin_approval(client, admin, session, sid, "B", 50).id
    row = FieldItem(schedule_id=sid, kind="photo", activity_id="B", activity_name="작업 B", trade="골조팀", status="applied",
                    title="[AI 사진 판독] B 작업 B", prompt_text="", response_choice="verified", reported_progress=95,
                    reported_rd=1, response_note="", payload_json=payload, approval_id=approval_id)
    session.add(row)
    session.commit()
    return approval_id, row.id


def test_an_approval_from_an_old_photo_reading_cannot_be_applied(client, admin, session, sid):
    approval_id, item_id = _photo_approval(client, admin, session, sid, {"photo_name": "old.jpg", "ai_progress": 95})
    version = client.get(f"/api/schedules/{sid}", headers=admin).json()["version"]

    detail = client.get(f"/api/approvals/{approval_id}", headers=admin).json()
    assert detail["blocked"] == OLD_READING
    r = client.post(f"/api/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=admin)
    assert r.status_code == 422 and (r.json()["code"], r.json()["message"]) == ("photo_unread", OLD_READING)
    assert client.get(f"/api/approvals/{approval_id}", headers=admin).json()["status"] == "pending"
    assert client.get(f"/api/schedules/{sid}", headers=admin).json()["version"] == version  # 95% 가 들어가지 않았다

    r = client.post(f"/api/approvals/{approval_id}/decide", json={"decision": "reject"}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "rejected"  # 거부는 그대로 된다
    session.expire_all()
    row = session.get(FieldItem, item_id)
    assert (row.reported_progress, row.payload_json) == (95, {"photo_name": "old.jpg", "ai_progress": 95})  # 저장된 줄 그대로


def test_an_unread_photo_answered_by_hand_is_not_an_old_reading_and_can_be_decided(client, admin, session, sid):
    """리뷰: 새 방식이 읽지 못한 사진(unread_reason 있음)에 사람이 손으로 진도를 넣은 건은 예전 지어낸 판독이 아니다 —
    현장 허브와 승인함이 같은 기준(field.legacy_photo)으로 본다."""
    payload = {"photo_name": "dark.jpg", "ai_progress": None, "unread_reason": "모델 답을 읽지 못해 판독하지 않았습니다."}
    approval_id, item_id = _photo_approval(client, admin, session, sid, payload)
    session.expire_all()
    assert field.legacy_photo(session.get(FieldItem, item_id)) is False
    assert client.get(f"/api/approvals/{approval_id}", headers=admin).json()["blocked"] is None
    r = client.post(f"/api/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "approved"


def test_an_approval_from_a_real_photo_reading_is_applied_as_before(client, admin, session, sid):
    payload = {"photo_name": "new.jpg", "ai_progress": 50, "ai_reason": "철근 배근이 절반쯤 끝났다.", "ai_risks": []}
    approval_id, _ = _photo_approval(client, admin, session, sid, payload)
    assert client.get(f"/api/approvals/{approval_id}", headers=admin).json()["blocked"] is None
    r = client.post(f"/api/approvals/{approval_id}/decide", json={"decision": "approve"}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "approved"


# ── 리뷰: 현장 관리자가 올린 것은 승인 수준과 상관없이 늘 승인을 기다린다(자동 승인이어도 일정이 바뀌지 않음) ──────
FIELD_WAITS = "현장 관리자가 올린 건이라 승인 수준과 상관없이 승인을 기다립니다 — 승인되기 전에는 일정이 바뀌지 않습니다."


def _headers(session, role: str) -> dict[str, str]:
    from app.security.passwords import hash_password
    from app.security.tokens import issue_token
    from tests.helpers import auth

    row = User(login_id=f"{role}-auto", name="박현장" if role == "field" else "김공정", role=role,
               password_hash=hash_password("x-pass-123"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


@pytest.mark.parametrize(("role", "applied"), [("field", False), ("user", True), ("admin", True)])
def test_field_reports_by_the_field_role_wait_for_approval_even_at_the_auto_level(client, admin, session, sid, role, applied):
    from app.store.settings import set_approval_mode

    set_approval_mode(session, "auto")
    who = admin if role == "admin" else _headers(session, role)
    before = client.get(f"/api/schedules/{sid}", headers=admin).json()["version"]

    row = _checkin_approval(client, who, session, sid, "B", 50)

    after = client.get(f"/api/schedules/{sid}", headers=admin).json()["version"]
    if applied:
        assert (row.status, after) == ("auto", before + 1)  # 사용자·관리자는 예전처럼 바로 반영
        assert "field_report" not in row.reasons_json
    else:
        assert (row.status, after) == ("pending", before)
        # 재확인 2: 기다리는 까닭은 승인 사유 「현장 보고」(목록 꼬리표·승인이 필요한 이유) — 알릴 것에 따로 적지 않는다
        assert row.reasons_json[-1] == "field_report"
        assert FIELD_WAITS not in (row.summary_json.get("notes") or [])


def test_a_photo_reading_applied_by_the_field_role_also_waits(client, admin, session, sid):
    from app.store.settings import set_approval_mode

    set_approval_mode(session, "auto")
    field_user = _headers(session, "field")
    client.get(f"/api/schedules/{sid}/field", headers=field_user)
    item = FieldItem(schedule_id=sid, kind="photo", activity_id="A", activity_name="작업 A", trade="골조팀", status="responded",
                     title="[AI 사진 판독] A 작업 A", prompt_text="", response_choice="verified", reported_progress=40,
                     reported_rd=2, response_note="", payload_json={"ai_progress": 40, "ai_reason": "절반쯤 섰다."})
    session.add(item)
    session.commit()
    r = client.post(f"/api/schedules/{sid}/field/{item.id}/apply", headers=field_user)
    assert r.status_code == 200, r.json()
    approval_id = next(i for i in r.json()["items"] if i["id"] == item.id)["approval_id"]
    session.expire_all()
    assert session.get(Approval, approval_id).status == "pending"
    assert client.get(f"/api/schedules/{sid}", headers=admin).json()["version"] == 1


# ── 재확인 2: 실적 날짜는 Data Date 뒤일 수 없고 실제 시작은 착공일 앞일 수 없다(승인 결정·현장 반영 모두) ──────
ACTUALS = "실제 날짜가 Data Date({})와 맞지 않아 반영할 수 없습니다 — 현장에서 다시 올려 주세요. ({})"


def test_an_approval_with_an_actual_start_before_the_project_start_cannot_be_applied(client, admin, session, dated_sid):
    """#18 처럼 실제 오늘(2026-11-23)이 실제 시작으로 들어간 승인 건(예전에 만든 줄을 흉내 냄)은 결정할 때 막는다 — 상세 blocked,
    승인 422 같은 글, 거부는 된다. 저장된 줄은 바꾸지 않는다."""
    row = _checkin_approval(client, admin, session, dated_sid, "A", 30)
    snap = {**row.snapshot_json, "activities": [
        {**a, "actual_start": "2026-11-23"} if a["id"] == "A" else a for a in row.snapshot_json["activities"]]}
    row.snapshot_json = snap
    session.commit()
    text = ACTUALS.format("2027-03-04", "A 실제 시작 2026-11-23 — 착공일 2027-03-01 앞")
    assert client.get(f"/api/approvals/{row.id}", headers=admin).json()["blocked"] == text
    r = client.post(f"/api/approvals/{row.id}/decide", json={"decision": "approve"}, headers=admin)
    assert r.status_code == 422 and (r.json()["code"], r.json()["message"]) == ("actual_dates", text)
    assert client.get(f"/api/schedules/{dated_sid}", headers=admin).json()["version"] == 1
    assert client.post(f"/api/approvals/{row.id}/decide", json={"decision": "reject"}, headers=admin).status_code == 200


def test_an_approval_with_an_actual_finish_after_the_data_date_cannot_be_applied(client, admin, session, dated_sid):
    row = _checkin_approval(client, admin, session, dated_sid, "A", 30)
    row.snapshot_json = {**row.snapshot_json, "activities": [
        {**a, "actual_finish": "2027-03-10"} if a["id"] == "A" else a for a in row.snapshot_json["activities"]]}
    session.commit()
    blocked = client.get(f"/api/approvals/{row.id}", headers=admin).json()["blocked"]
    assert blocked == ACTUALS.format("2027-03-04", "A 실제 종료 2027-03-10 — Data Date 뒤")


def test_a_field_report_that_would_start_before_the_project_start_is_refused(client, admin, session, monkeypatch):
    """Data Date 가 없는 일정이면 현장 회신의 「오늘」은 실제 오늘 — 착공일(2027-03-01)보다 앞이면 반영(상신)하지 않는다."""
    monkeypatch.setattr(context, "today", lambda: REAL_TODAY)
    sid = schedules.store(session, schedules.sample())
    item = _pending_checkin(client, admin, sid, "A")
    client.post(f"/api/schedules/{sid}/field/{item['id']}/respond",
                json={"response_choice": "on_track", "reported_progress": 30, "response_note": ""}, headers=admin)
    before = _count(session, Approval)
    r = client.post(f"/api/schedules/{sid}/field/{item['id']}/apply", headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "actual_dates"
    assert r.json()["message"] == ACTUALS.format("2026-11-23", "A 실제 시작 2026-11-23 — 착공일 2027-03-01 앞")
    assert _count(session, Approval) == before


# ── 재확인 2: 체크인 일괄 발송은 이미 회신을 기다리거나 승인함에서 기다리는 작업에는 또 보내지 않는다 ──────────
def test_bulk_check_in_skips_work_that_already_waits_and_says_so(client, admin, session, sid):
    first = client.post(f"/api/schedules/{sid}/field/checkins/dispatch", json={"activity_ids": ["A"]}, headers=admin)
    assert first.status_code == 200 and first.json()["notice"] is None  # A: 회신 대기 카드 하나
    b = next(i for i in first.json()["items"] if i["activity_id"] == "B" and i["status"] == "pending")  # 예시 카드
    client.post(f"/api/schedules/{sid}/field/{b['id']}/respond",
                json={"response_choice": "on_track", "reported_progress": 50, "response_note": ""}, headers=admin)
    client.post(f"/api/schedules/{sid}/field/{b['id']}/apply", headers=admin)  # B: 승인함에서 기다림
    before = _count(session, FieldItem)

    again = client.post(f"/api/schedules/{sid}/field/checkins/dispatch", json={"activity_ids": ["A", "B"]}, headers=admin)

    assert again.status_code == 200 and _count(session, FieldItem) == before  # A(회신 대기)·B(승인 대기) 둘 다 건너뜀
    assert again.json()["notice"] == (
        "체크인 0건을 보냈습니다. 2건은 건너뛰었습니다 — 회신을 기다리는 체크인이나 승인함에서 기다리는 보고가 "
        "이미 있습니다(A, B).")


def test_an_old_field_approval_without_reasons_reads_as_field_report(client, admin, session, sid):
    """재확인 3(#21): 사유를 저장하기 전에 만든 현장 관리자 건(reasons_json 비어 있음)은 읽을 때 「현장 보고」 사유로 보인다.
    저장된 줄은 그대로다."""
    field_user = _headers(session, "field")
    row = _checkin_approval(client, field_user, session, sid, "B", 50)
    row.reasons_json = []  # 예전 줄을 흉내 냄
    session.commit()
    assert client.get(f"/api/approvals/{row.id}", headers=admin).json()["reasons"] == ["field_report"]
    listed = client.get("/api/approvals?status=pending", headers=admin).json()["items"]
    assert next(i for i in listed if i["id"] == row.id)["reasons"] == ["field_report"]
    session.expire_all()
    assert session.get(Approval, row.id).reasons_json == []
