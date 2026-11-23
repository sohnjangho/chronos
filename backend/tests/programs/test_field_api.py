"""현장 허브 API(/api/schedules/{id}/field...): 체크인 반영·사진 판독."""

import json

import httpx
import pytest
from sqlalchemy import func, select

from app.llm.client import LlmClient
from app.programs.progress import field
from app.store.tables import Approval, DelayEvent, FieldItem, LlmCall, User
from tests.llm_doubles import FakeLiner, add_connection, chat_body

PHOTO = "data:image/png;base64,iVBORw0KGgo="


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
