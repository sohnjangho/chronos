"""문자 통로(Task 71) — 얇다: 줄을 읽어 제공사에 한 번 보내고 결과 셋(sent·failed·unsure) 가운데 하나를 돌려준다.

제공사는 가짜(fake_provider·KatMock)이고 번호·키는 가상이다. 도우미는 나가는 문 시험의 것을 같이 쓴다.
"""

import ast
import asyncio
import importlib
import logging
import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
import pytest

from app import db
from app.outreach import channels, provider
from app.outreach.channels import sms
from app.outreach.harness import gate, registry
from app.outreach.harness.types import Delivered
from app.outreach.provider import (
    Accepted,
    KatClient,
    ProviderConn,
    ProviderFailed,
)
from app.store import outreach
from app.store.tables_outreach import BlockedNumber
from tests.harness_doubles import faked_channels
from tests.outreach.harness.test_gate import (
    BODY,
    PHONE,
    USER,
    WORK,
    connect,
    db_path,
    message,
    person,
    reread,
    send,
    trail,
)
from tests.outreach_doubles import SENTINEL_KEY, SENTINEL_PHONE, assert_clean
from tests.provider_doubles import KAT_ACCOUNT, KAT_BASE, KatMock

pytestmark = pytest.mark.usefixtures("time_guard")

OUR = "07000000000"  # connect() 의 발신번호


class Scripted:
    """send_message 한 번에 정해 둔 것을 돌려주거나 던지는 가짜 제공사(보낸 요청은 requests 에)."""

    def __init__(self, result) -> None:
        self.result, self.requests = result, []

    async def send_message(self, req):
        self.requests.append(req)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def leaving(session, sid, **over):
    """문이 차지한 뒤의 줄(sending) 하나와 그 연락처."""
    who = person(session, sid)
    row = message(session, who, status="sending", claimed_at=WORK, **over)
    session.commit()
    return row, who


def ready(session, sid, **over):
    """기본 알림 연결(시험 모드 끔)과, 문이 차지한 뒤의 줄 하나·그 연락처."""
    connect(session)
    return leaving(session, sid, **over)


def scripted(monkeypatch, result) -> Scripted:
    client = Scripted(result)
    monkeypatch.setattr(provider, "client_for", lambda row: client)
    return client


# ── 등록 ──────────────────────────────────────────────────────────────


@pytest.mark.real_channel("sms")
def test_sms_channel_registers_once_and_not_under_a_fake():
    first = sms.CHANNEL
    assert first.name == "sms" and registry.channel("sms") is first and "sms" in registry.registered()

    importlib.reload(sms)  # 다시 불러와도 같은 객체 하나 — 겹쳐 등록하지 않는다(다른 객체면 register_channel 이 ValueError)
    importlib.reload(channels)
    assert sms.CHANNEL is first and registry.channel("sms") is first

    with faked_channels():
        importlib.reload(sms)  # 가짜가 덮인 동안 불려도 가짜가 앞에 선다
        assert registry.channel("sms") is not first
    assert registry.channel("sms") is first


def test_channels_package_registers_sms_on_import():
    assert channels.sms is sms and registry._CHANNELS["sms"] is sms.CHANNEL


# ── 결과 셋 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(("failure", "expected"), [
    (ProviderFailed("server", "오류", 503, maybe_sent=True), ("unsure", None)),
    (ProviderFailed("timeout", "시간 초과", None, maybe_sent=True), ("unsure", None)),  # 읽는 중 시간 초과
    (ProviderFailed("unknown", "읽지 못함", 201, maybe_sent=True), ("unsure", None)),
    (ProviderFailed("bad_request", "거절", 400), ("failed", "bad_request")),
    (ProviderFailed("bad_sender", "발신번호", 400), ("failed", "bad_sender")),
    (ProviderFailed("rate_limited", "잦음", 429, retry_after_s=30), ("failed", "rate_limited")),
    (ProviderFailed("timeout", "연결 시간 초과", None), ("failed", "network")),  # 한 바이트도 나가지 않았다
])
async def test_maybe_sent_failure_becomes_unsure_not_failed(session, sid, monkeypatch, failure, expected):
    row, _ = ready(session, sid)
    client = scripted(monkeypatch, failure)

    got = await sms.SmsChannel().deliver(row.id)

    assert (got.state, got.fail_code) == expected and got.provider_id is None
    assert got.fail_text is None  # 제공사의 글은 통로 밖으로 나가지 않는다
    assert len(client.requests) == 1  # 통로는 스스로 다시 보내지 않는다


@pytest.mark.parametrize(("status", "expected"), [
    (500, ("unsure", None)), (502, ("unsure", None)), (409, ("unsure", None)), (301, ("unsure", None)),
    (400, ("failed", "bad_request")), (401, ("failed", "bad_key")), (403, ("failed", "bad_account")),
    (422, ("failed", "bad_request")), (429, ("failed", "rate_limited")),
])
async def test_http_answers_map_to_the_three_outcomes(session, sid, monkeypatch, status, expected):
    """실제 클라이언트를 가짜 서버에 붙여: 5xx·409·3xx 는 「모름」, 409 밖의 4xx 는 「실패」."""
    row, _ = ready(session, sid)
    server = KatMock(override=lambda request: httpx.Response(status, json={"error": "가짜", "code": "x"}))
    client = KatClient(ProviderConn(KAT_BASE, KAT_ACCOUNT, SENTINEL_KEY), transport=server)
    monkeypatch.setattr(provider, "client_for", lambda conn: client)

    got = await sms.SmsChannel().deliver(row.id)

    assert (got.state, got.fail_code) == expected and len(server.requests) == 1


async def test_accepted_send_is_sent_with_the_provider_id(session, sid, fake_provider):
    row, who = ready(session, sid)

    got = await sms.SmsChannel().deliver(row.id)

    assert got == Delivered("sent", provider_id="FAKE0001")
    [req] = fake_provider.sent
    assert (req.channel, req.to, req.sender, req.body) == ("sms", who.phone, OUR, BODY)
    assert req.idempotency_key == row.idempotency_key


async def test_same_row_always_uses_the_same_key(session, sid, fake_provider):
    """중복 방지 키는 줄마다 하나 — 같은 줄을 다시 넣어도 같은 키라 제공사가 한 번만 보낸다."""
    row, _ = ready(session, sid)
    channel = sms.SmsChannel()

    first, second = await channel.deliver(row.id), await channel.deliver(row.id)

    assert first == second == Delivered("sent", provider_id="FAKE0001")
    assert len(fake_provider.sent) == 1 and fake_provider.log == ["send_message", "send_message"]


async def test_cancelled_send_is_not_swallowed(session, sid, monkeypatch):
    row, _ = ready(session, sid)
    scripted(monkeypatch, asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):  # 문이 받아 「보냈는지 확인 필요」로 적는다
        await sms.SmsChannel().deliver(row.id)


async def test_unexpected_error_while_sending_is_unsure_and_leaves_nothing_in_the_log(session, sid, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    row, _ = ready(session, sid)
    scripted(monkeypatch, RuntimeError(f"boom {SENTINEL_PHONE} {SENTINEL_KEY} {BODY}"))

    got = await sms.SmsChannel().deliver(row.id)

    assert got == Delivered("unsure")
    assert_clean(caplog, BODY)
    assert "RuntimeError" in caplog.text


async def test_provider_text_and_values_never_leave_the_channel(session, sid, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    row, _ = ready(session, sid)
    scripted(monkeypatch, ProviderFailed("bad_request", f"거절 {SENTINEL_PHONE} {SENTINEL_KEY}", 400))

    got = await sms.SmsChannel().deliver(row.id)

    assert got == Delivered("failed", fail_code="bad_request")
    assert SENTINEL_KEY not in repr(got) and PHONE not in repr(got)
    assert_clean(caplog, BODY)


# ── 보내기 바로 전에 다시 본다 ────────────────────────────────────────


@pytest.mark.parametrize("change", ["test_mode", "allow_list", "blocked", "dnc", "no_connection"])
async def test_sms_channel_rechecks_the_number_just_before_sending(session, sid, fake_provider, change):
    """줄이 기다리는 사이 시험 모드·허용 번호·차단·수신 거부가 바뀌었으면 보내지 않는다(문과 같은 gate.may_reach)."""
    conn = connect(session, test_mode=change == "allow_list", allow_numbers_json=[SENTINEL_PHONE])
    row, _ = leaving(session, sid)
    assert gate.may_reach(session, PHONE)
    if change == "test_mode":
        conn.test_mode, conn.allow_numbers_json = True, []
    elif change == "allow_list":
        conn.allow_numbers_json = ["010-0000-0188"]
    elif change == "blocked":
        session.add(BlockedNumber(number=PHONE, reason="요청", created_by="관리자"))
    elif change == "dnc":
        outreach.mark_do_not_contact(session, PHONE, reason="문자로 수신 거부")
    else:
        session.delete(conn)
    session.commit()

    got = await sms.SmsChannel().deliver(row.id)

    assert got == Delivered("failed", fail_code=sms.NOT_REACHABLE)
    assert fake_provider.sent == [] and fake_provider.log == []


@pytest.mark.parametrize(("case", "goes"), [
    ("confirm", True), ("other_kind", False), ("other_text", False), ("test_mode", False), ("blocked", False),
    ("not_refused", True),
])
async def test_dnc_confirmation_passes_the_recheck_only_against_the_refusal_itself(session, sid, fake_provider, case, goes):
    """수신 거부 확인 문자는 문이 한 번 지나보낸 것 — 통로는 수신 거부만으로는 막지 않는다. 시험 모드·차단은 그대로 막고,
    확인 문자가 아닌 글(종류가 다르거나 정해 둔 글이 아님)은 수신 거부 번호에 가지 않는다."""
    conn = connect(session)
    who = person(session, sid)
    over = {"kind": "dnc_confirm", "body": f" {gate.DNC_CONFIRM_TEXT}\n", "origin": "agent"}
    if case == "other_kind":
        over["kind"] = "normal"
    elif case == "other_text":
        over["body"] = "수신 거부로 처리했습니다. 그런데 내일 타설 가능하신가요"
    row = message(session, who, status="sending", **over)
    if case != "not_refused":
        outreach.mark_do_not_contact(session, PHONE, reason="문자로 수신 거부")
    if case == "test_mode":
        conn.test_mode = True
    elif case == "blocked":
        session.add(BlockedNumber(number=PHONE, reason="요청", created_by="관리자"))
    session.commit()

    got = await sms.SmsChannel().deliver(row.id)

    if goes:
        assert got.ok and [req.to for req in fake_provider.sent] == [PHONE]
    else:
        assert got == Delivered("failed", fail_code=sms.NOT_REACHABLE) and fake_provider.log == []


async def test_number_is_read_by_the_gates_rule(session, sid, fake_provider):
    """연락처가 있으면 연락처의 지금 번호, 없으면 peer_number."""
    connect(session)
    who = person(session, sid)
    to_contact = message(session, who, status="sending", peer_number="01000000177")
    to_number = message(session, peer_number="01000000188", status="sending", body="안내드립니다")
    who.phone = "01000000166"  # 예약 뒤에 번호가 바뀜
    session.commit()

    channel = sms.SmsChannel()
    assert (await channel.deliver(to_contact.id)).ok and (await channel.deliver(to_number.id)).ok

    assert [req.to for req in fake_provider.sent] == ["01000000166", "01000000188"]


async def test_row_whose_contact_is_gone_does_not_fall_back_to_its_peer_number(session, sid, fake_provider):
    """연락처 줄이 가리키는 연락처가 사라졌으면 줄에 남은 peer_number 로 보내지 않는다(문의 「이 일정의 연락처가 아닙니다」와 같은 쪽)."""
    connect(session)
    who = person(session, sid)
    row = message(session, who, status="sending", peer_number=PHONE)
    session.delete(who)
    session.commit()

    got = await sms.SmsChannel().deliver(row.id)

    assert got == Delivered("failed", fail_code=sms.NOT_REACHABLE) and fake_provider.log == []


@pytest.mark.parametrize("stored", ["010-0000-0199", None, "번호 아님"])
async def test_number_not_in_stored_form_is_not_sent(session, sid, fake_provider, stored):
    connect(session)
    who = person(session, sid, stored)
    row = message(session, who, status="sending")
    session.commit()

    got = await sms.SmsChannel().deliver(row.id)

    assert got == Delivered("failed", fail_code=sms.NOT_REACHABLE) and fake_provider.log == []


@pytest.mark.parametrize("over", [
    {"status": "draft"}, {"status": "scheduled"}, {"status": "accepted"}, {"status": "unconfirmed"},
    {"direction": "in", "status": "received"}, {"direction": "in"}, {"channel": "kakao"}, {"body": "   "},
])
async def test_channel_refuses_rows_the_gate_did_not_claim(session, sid, fake_provider, over):
    """통로는 판정하지 않지만, 문이 차지한 줄(나가는 sms · sending)만 보낸다 — 문 밖에서 불려도 초안이 나가지 않는다."""
    connect(session)
    who = person(session, sid)
    row = message(session, who, **{"status": "sending", **over})
    session.commit()

    got = await sms.SmsChannel().deliver(row.id)

    assert got == Delivered("failed", fail_code=sms.NOT_SENDABLE) and fake_provider.log == []


async def test_missing_row_is_failed(session, fake_provider):
    connect(session)
    session.commit()
    assert await sms.SmsChannel().deliver(987654) == Delivered("failed", fail_code=sms.NOT_SENDABLE)


async def test_no_sender_number_fails_before_sending(session, sid, fake_provider):
    connect(session, sender_number=None)
    row, _ = leaving(session, sid)

    assert await sms.SmsChannel().deliver(row.id) == Delivered("failed", fail_code="bad_sender")
    assert fake_provider.log == []


async def test_unreadable_key_fails_before_sending(session, sid):
    """저장된 키를 풀 수 없으면(가짜를 끼우지 않은 실제 client_for) 요청 없이 실패 — 실제 전송에 닿지 않는다."""
    connect(session)  # secret_ciphertext 가 암호문이 아니다
    row, _ = leaving(session, sid)

    assert await sms.SmsChannel().deliver(row.id) == Delivered("failed", fail_code="bad_key")


async def test_database_trouble_before_sending_is_a_clean_failure(session, sid, fake_provider, monkeypatch, caplog):
    """줄을 읽지 못하면 보내지 않는다 — 가지 않았음이 확실하므로 「모름」이 아니라 실패."""
    connect(session)
    row, _ = leaving(session, sid)
    monkeypatch.setattr(db, "_engine", None)

    got = await sms.SmsChannel().deliver(row.id)

    assert got == Delivered("failed", fail_code=sms.LOCAL_ERROR) and fake_provider.log == []
    assert_clean(caplog)


# ── 글 길이 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(("body", "kind"), [
    ("가" * 45, "sms"), ("가" * 46, "long"), ("a" * 90, "sms"), ("a" * 91, "long"), ("가" * 44 + "ab", "sms"),
    ("가" * 44 + "abc", "long"),
])
async def test_length_kind_is_recorded(session, sid, fake_provider, body, kind):
    """한글 2·영문 1 로 90바이트까지 sms, 넘으면 long. 요금 칸은 비워 둔다(제공사가 메시지마다 주지 않는다)."""
    connect(session)
    row, _ = leaving(session, sid, body=body)

    assert sms.length_kind(body) == kind
    assert (await sms.SmsChannel().deliver(row.id)).ok

    row = reread(session, row)
    assert row.length_kind == kind and row.provider_cost is None


# ── 제공사를 부르는 동안 DB 를 쥐지 않는다 ────────────────────────────


async def test_channel_holds_no_database_lock_while_the_provider_is_called(session, sid, monkeypatch):
    connect(session)
    row, _ = leaving(session, sid)
    wrote = []

    class Probing(Scripted):
        async def send_message(self, req):
            with closing(sqlite3.connect(db_path(), timeout=0.1)) as other:  # 쓰기 잠금이 잡혀 있으면 여기서 실패한다
                other.execute("BEGIN IMMEDIATE")
                other.execute("COMMIT")
            wrote.append(True)
            return await super().send_message(req)

    client = Probing(Accepted(provider_id="FAKE0009"))
    monkeypatch.setattr(provider, "client_for", lambda conn: client)

    assert await sms.SmsChannel().deliver(row.id) == Delivered("sent", provider_id="FAKE0009") and wrote == [True]


# ── 문을 거쳐서 ───────────────────────────────────────────────────────


@pytest.mark.real_channel("sms")
async def test_gate_sends_through_the_real_channel(session, sid, fake_provider):
    connect(session)
    who = person(session, sid)
    row = message(session, who)
    session.commit()

    out = await send(row, USER, WORK)

    row = reread(session, row)
    assert out.code == "accepted" and (row.status, row.provider_message_id, row.length_kind) == ("accepted", "FAKE0001", "sms")
    assert trail(session, row) == [("channel_choice", "allowed"), ("delivery", "allowed")]
    assert len(fake_provider.sent) == 1


@pytest.mark.real_channel("sms")
async def test_unsure_send_through_the_gate_is_unconfirmed_and_failed_send_is_failed(session, sid, fake_provider):
    connect(session)
    who = person(session, sid)
    lost, refused = message(session, who, body="첫 글"), message(session, who, body="둘째 글")
    session.commit()

    fake_provider.fail = ProviderFailed("server", "오류", 502, maybe_sent=True)
    assert (await send(lost, USER, WORK)).code == "unsure"
    fake_provider.fail = ProviderFailed("bad_sender", "발신번호", 400)
    out = await send(refused, USER, WORK)

    assert reread(session, lost).status == "unconfirmed"
    assert (out.code, out.message) == ("failed", gate.FAIL_TEXT["bad_sender"]) and reread(session, refused).status == "failed"


# ── 구조 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["channels/sms.py", "worker.py"])
def test_client_for_is_called_as_a_module_attribute(name):
    """`provider.client_for(…)` 로만 부른다 — 이름을 먼저 들여오면 시험의 가짜(fake_provider)가 듣지 않는다."""
    path = Path(sms.__file__).parents[1] / name
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                and node.module == "app.outreach.provider" for alias in node.names}
    assert "client_for" not in imported
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "client_for"]
    assert calls and all(isinstance(call.func.value, ast.Name) and call.func.value.id == "provider" for call in calls)
