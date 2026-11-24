"""개발 콘솔 ④(Task 111): 카카오톡 — 시스템 진단의 notify.kakao · 사용량의 알림톡 건수와 문자로 대신 나간 수. 읽기만 한다.

콘솔은 제공사를 부르지 않는다(저장된 채널·문안 상태만). 번호·키·발신 키는 어떤 응답에도 없다. 가상 데이터만 쓴다.
"""

from datetime import UTC, datetime

from app.outreach import provider
from app.outreach.harness import events
from app.outreach.harness.types import Ref
from app.security.crypto import encrypt
from app.store.tables_outreach import KakaoTemplate, NotifyConnection, OutreachMessage
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY, SENTINEL_PHONE, _leaks

NOW = datetime.now(UTC)
SYNCED = datetime(2026, 11, 24, 5, 6, 7, tzinfo=UTC)


def _connection(session, **fields) -> NotifyConnection:
    values = {"name": "기본 연결", "base_url": "https://kat.invalid", "secret_ciphertext": encrypt(SENTINEL_KEY),
              "secret_last4": "9999", "account_id": "ACCT-0000", "sender_number": SENTINEL_DIGITS, "is_default": True,
              "status": "ok", "checked_at": NOW, **fields}
    row = NotifyConnection(**values)
    session.add(row)
    session.commit()
    return row


def _template(session, conn_id: int, n: int, status: str, **fields) -> None:
    session.add(KakaoTemplate(connection_id=conn_id, channel="ch-1", provider_template_id=f"tpl-{n}", status=status,
                              body=f"가상 문안 {n}", synced_at=SYNCED, **fields))


def _walk(value) -> list[str]:
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (str(k), *_walk(v))]
    if isinstance(value, list):
        return [s for v in value for s in _walk(v)]
    return [str(value)]


def _health(client, admin) -> dict:
    r = client.get("/api/devconsole/health", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()["notify"]


def test_kakao_health_from_stored_state_without_provider_call(client, admin, session, monkeypatch):
    async def refuse(*_a, **_k):
        raise AssertionError("콘솔이 제공사를 불렀습니다")

    monkeypatch.setattr(provider.KatClient, "kakao_channels", refuse)
    monkeypatch.setattr(provider.KatClient, "kakao_templates", refuse)
    conn = _connection(session, kakao_channels_json=[
        {"id": "ch-0", "name": "끊긴 채널", "status": "disconnected"},
        {"id": "ch-1", "name": f"한빛 현장 {SENTINEL_PHONE}", "status": "connected"}])
    for n, status in enumerate(["approved", "approved", "reviewing", "rejected", "dormant", "dormant", "dormant"]):
        _template(session, conn.id, n, status)
    session.commit()

    kakao = _health(client, admin)["kakao"]
    assert kakao["channel"].startswith("한빛 현장")
    assert kakao["templates"] == {"approved": 2, "reviewing": 1, "rejected": 1, "dormant": 3}
    assert datetime.fromisoformat(kakao["synced_at"]) == SYNCED
    assert kakao["ready"] is False and isinstance(kakao["available"], bool)
    text = "\n".join(_walk(kakao))
    assert not _leaks(text, (SENTINEL_KEY,)), _leaks(text, (SENTINEL_KEY,))
    assert SENTINEL_PHONE not in text and SENTINEL_DIGITS not in text and "ACCT-0000" not in text


def test_no_channel_state(client, admin, session):
    _connection(session)
    kakao = _health(client, admin)["kakao"]
    assert kakao["channel"] is None
    assert kakao["templates"] == {"approved": 0, "reviewing": 0, "rejected": 0, "dormant": 0}
    assert kakao["synced_at"] is None and kakao["ready"] is False


def _message(session, **fields) -> OutreachMessage:
    values = {"direction": "out", "channel": "sms", "origin": "user", "origin_name": "김하늘", "body": "가상 본문",
              "status": "accepted", "claimed_at": NOW, "created_at": NOW, **fields}
    row = OutreachMessage(**values)
    session.add(row)
    session.commit()
    return row


def test_usage_counts_kakao_and_sms_instead(client, admin, session):
    _message(session, channel="kakao", status="accepted")  # 알림톡으로 나간 것
    first = _message(session, channel="kakao", fallback_sms=True)
    second = _message(session, channel="kakao", fallback_sms=True)
    for row in (first, second):
        events.record(session, Ref("message", row.id), "kakao_not_ready", "noted", "문자로 보냅니다")
    third = _message(session, channel="kakao", fallback_sms=True)  # 사건 없이 대신 나간 줄(사건 수는 따로 센다)
    _message(session, channel="sms")
    _message(session, channel="kakao", fallback_sms=True, status="draft", claimed_at=None)  # 차지 안 함 — 세지 않음
    session.commit()
    assert third.id

    out = client.get("/api/devconsole/usage?days=7", headers=admin).json()["outreach"]
    assert out["kakao"] == 1
    assert out["fallback_sms"] == 3
    assert out["kakao_not_ready"] == 2
    assert out["sms"] == 4  # 문자 하나 + 문자로 대신 나간 셋
