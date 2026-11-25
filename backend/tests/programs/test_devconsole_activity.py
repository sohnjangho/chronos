"""접속 기록: 미들웨어가 기능 사용을 적고, 개발 콘솔이 계정별로 대화·프로젝트·기능을 보여 준다."""

from sqlalchemy import select

from app.store import activity, chats
from app.store.activity import ActivityLog, feature_name
from app.store.tables import ScheduleRecord, User


def _features(session, login_id="admin"):
    session.expire_all()
    uid = session.scalar(select(User.id).where(User.login_id == login_id))
    return [r.feature for r in session.scalars(select(ActivityLog).where(ActivityLog.user_id == uid)
                                               .order_by(ActivityLog.id))]


def test_login_success_and_failure_are_recorded(client, session):
    assert client.post("/api/auth/login", json={"login_id": "admin", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"login_id": "nobody", "password": "x"}).status_code == 401
    assert client.post("/api/auth/login", json={"login_id": "admin", "password": "test-pass"}).status_code == 200
    assert _features(session) == ["로그인 실패", "로그인"]
    unknown = session.scalars(select(ActivityLog).where(ActivityLog.user_id.is_(None))).all()
    assert [r.note for r in unknown] == ["nobody"]


def test_requests_are_recorded_with_schedule_and_repeats_skipped(client, session, admin, sid):
    client.get(f"/api/schedules/{sid}", headers=admin)
    client.get(f"/api/schedules/{sid}", headers=admin)  # 1분 안 같은 GET → 한 줄
    client.post("/api/me/presence", json={"kind": "desktop"}, headers=admin)  # 접속 신호는 빼기
    client.get("/api/devconsole/turns", headers=admin)  # 개발 콘솔 읽기는 빼기
    client.post("/api/chat/sessions", json={}, headers=admin)
    assert _features(session) == ["일정 보기", "새 대화"]
    row = session.scalars(select(ActivityLog).order_by(ActivityLog.id)).first()
    assert row.schedule_id == sid and row.route == "/api/schedules/{schedule_id}" and row.status == 200


def test_no_token_no_record(client, session):
    client.get("/api/schedules")
    session.expire_all()
    assert session.scalars(select(ActivityLog)).all() == []


def test_record_failure_never_breaks_the_request(client, admin, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db gone")
    monkeypatch.setattr(activity, "record", boom)
    assert client.get("/api/schedules", headers=admin).status_code == 200


def test_feature_names():
    assert feature_name("POST", "/api/chat/sessions/{chat_id}/messages") == "에이전트 질문"
    assert feature_name("POST", "/api/schedules/{schedule_id}/delays/analyze") == "지연 분석"
    assert feature_name("GET", "/api/schedules/{schedule_id}/delays") == "지연 분석 보기"
    assert feature_name("GET", "/api/zzz") == "/api/zzz"


def test_account_view_shows_chats_by_session_projects_and_features(client, session, admin, user):
    me = session.scalar(select(User).where(User.login_id == "user1"))
    chat = chats.create_chat(session, user_id=me.id)
    q = chats.add_message(session, chat.id, "user", {"text": "일정 지연 분석해줘"})
    chats.add_message(session, chat.id, "assistant", {"text": "", "tool_calls": [{"id": "1", "name": "x", "arguments": "{}"}]})
    chats.add_message(session, chat.id, "tool", {"tool_call_id": "1", "content": "ok"})
    chats.add_message(session, chat.id, "assistant", {"text": "크리티컬 경로가 3일 늦습니다."})
    session.add(ScheduleRecord(name="심사 프로젝트", domain="rnd", level="L3", created_by=me.name))
    session.commit()
    client.get("/api/chat/sessions", headers=user)

    assert client.get("/api/devconsole/activity/accounts", headers=user).status_code == 403
    accounts = client.get("/api/devconsole/activity/accounts", headers=admin).json()
    row = next(a for a in accounts["accounts"] if a["login_id"] == "user1")
    assert row["chats"] == 1 and row["features"] == 1

    body = client.get(f"/api/devconsole/activity/accounts/{me.id}", headers=admin).json()
    assert [(m["role"], m["text"]) for m in body["chats"][0]["messages"]] == [
        ("user", "일정 지연 분석해줘"), ("assistant", "크리티컬 경로가 3일 늦습니다.")]
    assert body["chats"][0]["messages"][0]["turn_id"] == q.id
    assert [p["name"] for p in body["projects"]] == ["심사 프로젝트"]
    assert body["features"][0]["feature"] == "대화 보기"
    assert body["summary"] == [{"feature": "대화 보기", "count": 1}]
    assert client.get("/api/devconsole/activity/accounts/9999", headers=admin).status_code == 404
