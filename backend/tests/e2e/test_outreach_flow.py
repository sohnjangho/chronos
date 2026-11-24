"""서버 끝에서 끝까지 — 계획 4(연락처 · 문자 · AI 전화). 가짜 제공사(fake_provider · KatMock) · SimulatedVoice · SimulatedText ·
ScriptedLlm 뿐이다 — 실제 제공사·SDK·LLM·망이 없다. 시각은 정해 둔 금요일 10시(근무 중)이고, 일꾼·통화 일꾼은 한 바퀴씩 직접 돌린다.

알림 연결 추가 → [연결 진단](가짜 — OK/FAIL 줄) → 주소록에 CSV 로 3명 → 허용 번호가 아닌 사람에게 문자 → 「시험 모드로 보내지 않음」
→ 허용 번호 사람에게 체크인 문자 → 도착 → 답 문자가 그 요청에 이어 대화에 → (받는 범위 켬) 자동 답 초안 → [보내기]
→ 대화 「박현장 팀장에게 철근 반입 시간 물어봐 줘」 → 초안 카드 → [보내기] → 에이전트 발신 · 김공정 승인 → 전화 초안 → 걸기
→ (가짜) 통화 → 받아쓰기·요약·근거 → [결과 확정] → 위임으로 바꾼 뒤 에이전트가 직접 → 에이전트 발신 · 위임 → 받는 통화(가짜 Ring)
→ 상대 발신 · 확인할 보고 1 → 모르는 번호의 문자 → 「모르는 번호」 묶음·고정 안내 → 다른 프로젝트로 바꾸면 주소록이 비어 있음
→ 개발 콘솔: 격자 전부 돌리기 · 연락 추적(발신·권한·등급·문 판정) · 진단·사용량 · 응답 전체에 전체 번호·키 없음
→ 끝에 DB(trace_events · chat_messages · llm_calls · 하네스 사건)와 로그에 SENTINEL_PHONE · SENTINEL_KEY 가 없는지 훑는다.

번호·이름·회사는 모두 가상이다.
"""

import asyncio
import json
import logging
import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, text

from app.agent import loop
from app.info.generic import key_survives
from app.llm.client import LlmClient
from app.notify import diagnostics
from app.outreach import worker
from app.outreach.channels import sms as _sms_channel  # noqa: F401 — 진짜 문자 통로를 등록(서버에서는 일꾼이 불러온다)
from app.outreach.channels import voice as _voice_channel  # noqa: F401 — 진짜 통화 통로(줄에 넣기만)
from app.outreach.provider import Delivery, Inbound
from app.outreach.text import inbox
from app.outreach.text import session as text_session
from app.outreach.text.simulated import Reply, SimulatedText
from app.outreach.voice import after, inbound, kat_listen, runner
from app.outreach.voice import session as voice_session
from app.outreach.voice.simulated import Hangup, Ring, Say, SimulatedVoice, Tool
from app.programs.contacts import service as contacts_service
from app.programs.outreach import calls_service, inbox_service, service
from app.security import crypto
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store import outreach_usage
from app.store.tables import User
from app.store.tables_outreach import OutreachCall, OutreachMessage, VoiceSettings
from app.tools.notify import list_contacts, send_message
from tests import schedules
from tests.helpers import auth
from tests.llm_doubles import add_connection
from tests.loop_doubles import ScriptedLlm, calls, reply
from tests.outreach_doubles import (
    SENTINEL_DIGITS,
    SENTINEL_KEY,
    SENTINEL_PHONE,
    assert_clean,
)
from tests.provider_doubles import KAT_ACCOUNT, KAT_SENDER, KatMock, time_limit

WORK = datetime(2026, 11, 27, 1, 0, tzinfo=UTC)  # 한국 시각 2026-11-27(금) 10:00 — 근무 중
NOTIFY = "/api/notify/connections"
STRANGER = "010-0000-0188"  # 주소록에 없는 가상 번호
CSV = ("협력사,이름,담당,전화번호,공종\n"
       f"가람철근,박현장,철근 팀장,{SENTINEL_PHONE},철근\n"
       "가람철근,이반장,철근 반장,010-0000-0198,철근\n"
       "한빛전기,최전기,전기 과장,010-0000-0197,전기\n")
FULL_NUMBERS = [re.sub(r"\D", "", n) for n in (SENTINEL_PHONE, "010-0000-0198", "010-0000-0197", STRANGER)]
AGENT_NUMBER = "07000000100"  # 가상 AI 전화 번호
UI = {"program": "contacts"}


def ok(r, status: int = 200):
    assert r.status_code == status, r.text
    return r.json() if r.content else None


def leaks(blob: str) -> list[str]:
    """글 하나에 전체 번호(어느 꼴이든 — 숫자만 남겨 본다)나 키가 남았는가."""
    digits = re.sub(r"\D", "", blob)
    found = [n for n in FULL_NUMBERS if n in digits or n[1:] in digits]
    return found + (["SENTINEL_KEY"] if key_survives(blob, SENTINEL_KEY) else [])


class Clock:
    """모든 「지금」을 한 시계로 — 걸음마다 몇 분씩 앞으로 간다(근무시간 안에서)."""

    def __init__(self, monkeypatch) -> None:
        self.at = WORK
        for module in (service, calls_service, inbox_service, contacts_service, send_message, list_contacts, worker,
                       runner, after, inbound):
            monkeypatch.setattr(module, "_now", lambda: self.at)
        real_window = outreach_usage._window  # 사용량의 「오늘」도 이 시계로(시험 날짜가 실제 오늘과 다르다)
        monkeypatch.setattr(outreach_usage, "_window", lambda days, now: real_window(days, now or self.at))

    def tick(self, minutes: int = 2) -> datetime:
        self.at += timedelta(minutes=minutes)
        return self.at


class Console:
    """개발 콘솔 GET/POST — 응답 글을 모두 모아 두었다가 끝에 번호·키를 훑는다."""

    def __init__(self, client, headers) -> None:
        self.client, self.headers, self.texts = client, headers, []

    def __call__(self, method: str, path: str):
        r = getattr(self.client, method)(f"/api/devconsole{path}", headers=self.headers)
        self.texts.append(r.text)
        return ok(r)


@pytest.fixture
def kim(session) -> dict[str, str]:
    """일반 사용자 김공정 — 화면에서 [보내기]를 누르는 사람."""
    row = User(login_id="kim", name="김공정", role="user", password_hash=hash_password("kim-pass"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


@pytest.fixture
def kat(monkeypatch) -> KatMock:
    """연결 진단의 걸음은 진짜 코드 + 가짜 서버(전송 층). 제공사 연결 확인(만들기)은 fake_provider."""
    mock = KatMock()
    real_make = diagnostics.make_client
    monkeypatch.setattr(diagnostics, "make_client", lambda *, transport=None: real_make(transport=transport or mock))
    monkeypatch.setattr(diagnostics, "POLL_GAP_S", 0)
    return mock


@pytest.fixture
def liner(session, monkeypatch) -> ScriptedLlm:
    """대화 루프와 통화 요약이 같은 대본 가짜 Liner 를 쓴다."""
    add_connection(session)
    llm = ScriptedLlm()
    monkeypatch.setattr(loop, "default_llm", lambda s: LlmClient(s, transport=llm.transport))
    monkeypatch.setattr(after, "client_for", lambda s: LlmClient(s, transport=llm.transport))
    return llm


@pytest.fixture(autouse=True)
def fresh_voice_state(monkeypatch):
    """받는 통화의 메모리 상태 · SDK 어댑터의 번호별 에이전트는 시험마다 새것."""
    monkeypatch.setattr(inbound, "_state", inbound._State())
    monkeypatch.setattr(kat_listen, "AGENTS", {})


def _events(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        if block.startswith(":"):
            continue
        event, data = block.split("\n")
        out.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def _say(client, headers, chat_id: int, said: str, sid: int) -> list[tuple[str, dict]]:
    r = client.post(f"/api/chat/sessions/{chat_id}/messages", headers=headers,
                    json={"text": said, "ui": {**UI, "schedule_id": sid}})
    assert r.status_code == 200, r.text
    events = _events(r.text)
    assert events[-1][0] == "done" and not [e for e in events if e[0] == "error"], events
    return events


def _card(events, kind: str) -> dict:
    return next(d for name, d in events if name == "card" and d.get("kind") == kind)


def _inbound(pid: str, sender: str, body: str, at: datetime) -> Inbound:
    return Inbound(provider_id=pid, from_number=re.sub(r"\D", "", sender), body=body, at=at, has_media=False,
                   to_number=KAT_SENDER)


async def _ring(session, sim: SimulatedVoice) -> None:
    """가짜 음성으로 벨을 울리고, 통화 뒤 일(뒤 확인·요약)이 끝날 때까지 기다린다.

    통화 뒤 일은 `inbound._behind` 가 띄우는 따로 도는 작업이다 — listen 이 돌아온 순간에 아직 없을 수 있어(뜨기 전이면 기다릴
    것이 없다고 보고 일찍 나간다), 결과(받은 통화 줄의 요약)가 DB 에 보일 때까지 뒤 작업을 기다리며 짧게 다시 본다(최대 10초)."""
    with voice_session.pinned(sim):
        async with asyncio.timeout(10):
            await sim.listen(AGENT_NUMBER, inbound.on_incoming)
            while True:
                pending = [task for task in inbound._state.follows if not task.done()]
                if pending:
                    await asyncio.wait(pending, timeout=5)
                    continue
                session.expire_all()
                latest = session.scalars(select(OutreachCall).where(OutreachCall.direction == "in")
                                         .order_by(OutreachCall.id.desc())).first()
                if latest is not None and latest.summary_ko:
                    return
                await asyncio.sleep(0.05)


def _sweep_db(session) -> dict[str, list[str]]:
    """DB 를 훑는다: 실행 추적·대화 저장·LLM 호출·하네스 사건(메시지·통화의 harness_json)·받아쓰기·보고·사용량에 전체 번호·키가
    없는지, 그리고 **어느 표에도** 키가 평문으로 없는지(키는 암호문으로만 저장)."""
    found: dict[str, list[str]] = {}
    scoped = {"trace_events": "*", "chat_messages": "*", "llm_calls": "*", "contact_reports": "*", "outreach_usage": "*",
              "outreach_messages": "harness_json, body, fail_reason", "outreach_calls": "harness_json, transcript_json, answers_json, summary_ko"}
    for table, columns in scoped.items():
        for row in session.execute(text(f"SELECT {columns} FROM {table}")):
            if hit := leaks(json.dumps([str(v) for v in row], ensure_ascii=False)):
                found.setdefault(table, []).extend(hit)
    tables = [r[0] for r in session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))]
    for table in tables:
        for row in session.execute(text(f'SELECT * FROM "{table}"')):
            if key_survives(json.dumps([str(v) for v in row], ensure_ascii=False), SENTINEL_KEY):
                found.setdefault(table, []).append("SENTINEL_KEY")
    return found


@pytest.mark.real_channel("sms", "call")
async def test_contacts_outreach_flow(client, session, admin, kim, fake_provider, kat, liner, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    clock = Clock(monkeypatch)
    sid = schedules.store(session, schedules.sample())
    other_sid = schedules.store(session, schedules.sample())
    url = f"/api/schedules/{sid}"
    with time_limit(300):
        # ── 1. 알림 연결 추가 → 연결 진단(가짜 — OK/FAIL 줄) ─────────────────
        conn = ok(client.post(NOTIFY, json={"name": "한국AI통신", "secret": SENTINEL_KEY, "account_id": KAT_ACCOUNT},
                              headers=admin), 201)
        assert (conn["test_mode"], conn["inbound_mode"], conn["agent_sms"], conn["agent_call"]) == (
            True, "off", "approve", "approve")  # 처음은 안전한 쪽: 시험 모드 · 받지 않음 · 승인 받기
        assert conn["secret_last4"] == "9999" and SENTINEL_KEY not in json.dumps(conn)
        cid = conn["id"]
        conn = ok(client.patch(f"{NOTIFY}/{cid}", json={"allow_numbers_add": [SENTINEL_PHONE]}, headers=admin))
        diag = ok(client.post(f"{NOTIFY}/{cid}/diagnose", headers=admin, json={
            "steps": ["P1", "P2", "P3", "P4"], "send": True, "allow_numbers_version": conn["allow_numbers_version"]}))
        assert [(s["id"], s["ok"], s["code"]) for s in diag["steps"]] == [
            ("P1", True, "ok"), ("P2", True, "ok"), ("P3", False, "still_queued"), ("P4", True, "ok")]
        assert diag["sent_real"] is True  # 명시한 시험 문자 하나 — 첫 허용 번호로만
        assert [json.loads(r.content)["To"] for r in kat.requests if r.method == "POST"] == [SENTINEL_DIGITS]
        kat.override = lambda r: (httpx.Response(500, json={"error": "가짜 고장", "code": "server"})
                                  if r.method == "GET" and r.url.path.endswith("/messages") else None)
        diag = ok(client.post(f"{NOTIFY}/{cid}/diagnose", json={"steps": ["P4"]}, headers=admin))
        assert [(s["id"], s["ok"], s["skipped"], s["code"]) for s in diag["steps"]][-1] == ("P4", False, False, "server")
        assert leaks(json.dumps(diag, ensure_ascii=False)) == []

        # ── 2. 주소록에 CSV 로 3명 ───────────────────────────────────
        upload = {"file": ("people.csv", CSV.encode(), "text/csv")}
        preview = ok(client.post(f"{url}/contacts/import?dry_run=1", files=upload, headers=kim))
        assert preview["summary"]["new"] == 3 and leaks(json.dumps(preview)) == []
        assert ok(client.post(f"{url}/contacts/import?dry_run=0", files=upload, headers=kim))["summary"]["new"] == 3
        book = ok(client.get(f"{url}/contacts", headers=kim))
        people = {p["name"]: p["id"] for c in book["companies"] for p in c["people"]}
        assert set(people) == {"박현장", "이반장", "최전기"} and leaks(json.dumps(book)) == []

        # ── 3. 허용 번호가 아닌 사람에게 문자 → 「시험 모드로 보내지 않음」 ──────
        out = ok(client.post(f"{url}/outreach/messages", headers=kim, json={
            "contact_id": people["이반장"], "channel": "sms", "body": "내일 철근 반입 가능하신가요?", "send": True}))
        assert out["outcome"] == {"code": "blocked_test", "message": "시험 모드라 허용한 번호에만 연락합니다",
                                  "scheduled_at": None}
        blocked_id = out["message"]["id"]
        assert fake_provider.sent == []

        # ── 4. 허용 번호 사람에게 체크인 문자 → 도착 → 답 문자가 그 요청에 이어 대화에 ──
        clock.tick()
        out = ok(client.post(f"{url}/outreach/messages", headers=kim, json={
            "contact_id": people["박현장"], "channel": "sms", "body": "내일 오전 철근 반입 예정대로인가요?", "send": True}))
        assert out["outcome"]["code"] == "accepted" and out["message"]["send_mode"] == "manual"
        checkin = out["message"]["id"]
        assert len(fake_provider.sent) == 1  # 진짜 문자 통로 → 가짜 제공사
        for provider_id in fake_provider._ids.values():
            fake_provider.statuses[provider_id] = Delivery(state="delivered")
        await worker.tick(now=clock.tick())
        fake_provider.inbox.append(_inbound("MGIN0001", SENTINEL_PHONE, "네 예정대로 9시에 들어갑니다", clock.tick()))
        await worker.tick(now=clock.tick())
        thread = ok(client.get(f"{url}/outreach/threads/{people['박현장']}", headers=kim))
        lines = {m["id"]: m for m in thread["messages"]}
        assert lines[checkin]["status"] == "delivered" and lines[checkin]["delivered_at"]
        (answer,) = [m for m in thread["messages"] if m["direction"] == "in"]
        assert (answer["reply_to_id"], answer["origin"]) == (checkin, "peer")
        assert answer["events"] == [{"rule": "admission", "verdict": "blocked", "detail": "inbound_off"}]  # 받지 않음 — 기록만

        # ── 5. (받는 범위 켬) 자동 답 초안이 점선 말풍선으로 → [보내기] ──────────
        ok(client.patch(f"{NOTIFY}/{cid}", json={"inbound_mode": "known"}, headers=admin))
        with text_session.pinned(SimulatedText([Reply("네, 9시 반입으로 알겠습니다. 감사합니다.")])):
            fake_provider.inbox.append(_inbound("MGIN0002", SENTINEL_PHONE, "하차 장소는 어디로 하면 될까요?", clock.tick()))
            await worker.tick(now=clock.tick())
            assert await inbox.drain(now=clock.tick()) == 1
        thread = ok(client.get(f"{url}/outreach/threads/{people['박현장']}", headers=kim))
        question, draft = thread["messages"][-2:]
        assert (draft["kind"], draft["origin"], draft["status"], draft["reply_to_id"]) == (
            "auto_reply", "agent", "draft", question["id"])  # 화면은 kind auto_reply·draft 를 점선 말풍선으로 그린다
        assert draft["fail_reason"] == "사람의 승인이 필요합니다"
        sent = ok(client.post(f"{url}/outreach/messages/{draft['id']}/send", headers=kim))
        assert sent["outcome"]["code"] == "accepted"
        assert (sent["message"]["origin"], sent["message"]["approved_by"]) == ("agent", "김공정")

        # ── 6. 대화 「박현장 팀장에게 철근 반입 시간 물어봐 줘」 → 초안 카드 → [보내기] ──
        chat_id = ok(client.post("/api/chat/sessions", json={}, headers=kim))["id"]
        liner.push(calls("contacts.list", {"query": "박현장"}),
                   calls("notify.draft_message", {"contact_id": people["박현장"], "channel": "sms",
                                                  "body": "박현장 팀장님, 내일 철근 반입 시간 알려 주실 수 있을까요?"},
                         call_id="call_2"),
                   reply("박현장 팀장에게 보낼 문자 초안을 만들었습니다. [보내기]를 눌러 주세요."))
        card = _card(_say(client, kim, chat_id, "박현장 팀장에게 철근 반입 시간 물어봐 줘", sid), "outreach_draft")
        assert card["needs_approval"] is True and card["contact"]["name"] == "박현장" and "phone" not in json.dumps(card)
        clock.tick()
        sent = ok(client.post(f"{url}/outreach/messages/{card['message_id']}/send", headers=kim))
        line = sent["message"]
        assert sent["outcome"]["code"] == "accepted"
        assert (line["origin"], line["send_mode"], line["approved_by"]) == ("agent", "approved", "김공정")  # [에이전트 발신] · 김공정 승인
        assert line["chat"]["id"] == chat_id

        # ── 7. 전화 초안 → 걸기 → (가짜) 통화 → 받아쓰기·요약·근거 → [결과 확정] ──────
        session.add(VoiceSettings(connection_id=cid, provider="google", secret_ciphertext=crypto.encrypt(SENTINEL_KEY),
                                  secret_last4="9999", model="sim-model", agent_number=AGENT_NUMBER,
                                  voices_by_language_json={}, status="ok"))
        session.commit()
        call = ok(client.post(f"{url}/outreach/calls", headers=kim, json={
            "contact_id": people["박현장"], "purpose": "내일 철근 반입 시간 확인", "questions": ["내일 철근 반입 시각"],
            "avoid": ["계약·금액"]}))
        assert call["status"] == "draft"
        placed = ok(client.post(f"{url}/outreach/calls/{call['id']}/place", headers=kim))  # 걸기 창의 [전화 걸기]
        assert placed["outcome"]["code"] == "queued" and placed["call"]["send_mode"] == "manual"
        liner.push(reply(json.dumps({"summary_ko": "박현장 팀장이 내일 오전 9시에 철근이 들어온다고 답했습니다.",
                                     "result": "내일 09:00 반입"}, ensure_ascii=False)))
        talk = SimulatedVoice([Say("peer", "네 박현장입니다", t=1), Tool("confirm_person", {"is_person": True}),
                               Say("peer", "철근은 내일 오전 9시에 들어옵니다", t=3),
                               Tool("record_answer", {"question": "내일 철근 반입 시각", "answer": "오전 9시",
                                                      "quote": "철근은 내일 오전 9시에 들어옵니다"}),
                               Say("agent", "네 오전 9시로 전하겠습니다", t=5), Hangup("peer")])
        with voice_session.pinned(talk):
            assert await runner.run_one(call["id"], now=clock.tick()) == "completed"
        one = ok(client.get(f"{url}/outreach/calls/{call['id']}", headers=kim))
        opening = one["transcript"][0]
        assert opening["role"] == "agent" and "AI" in opening["text"] and "기록됩니다" in opening["text"]
        assert one["summary_ko"].startswith("박현장 팀장이") and one["result_proposed"] == "내일 09:00 반입"
        assert one["answers"] == [{"question": "내일 철근 반입 시각", "answer": "오전 9시",
                                   "quote": "철근은 내일 오전 9시에 들어옵니다", "quote_found": True}]  # 근거
        done = ok(client.post(f"{url}/outreach/calls/{call['id']}/confirm", json={"result": "내일 09:00 반입 확정"},
                              headers=kim))
        assert (done["result_confirmed"], done["confirmed_by"]) == ("내일 09:00 반입 확정", "김공정")

        # ── 8. 위임으로 바꾼 뒤 에이전트가 직접 → [에이전트 발신 · 위임] ──────────
        ok(client.patch(f"{NOTIFY}/{cid}", json={"agent_sms": "delegate", "agent_call": "delegate"}, headers=admin))
        next_id = session.scalar(select(func.max(OutreachMessage.id))) + 1  # 이 턴의 초안 id(sqlite_autoincrement)
        liner.push(calls("notify.draft_message", {"contact_id": people["박현장"], "channel": "sms",
                                                  "body": "내일 하차는 2번 게이트로 부탁드립니다."}),
                   calls("notify.send_message", {"message_id": next_id}, call_id="call_2"),
                   reply("박현장 팀장에게 하차 위치를 보냈습니다."))
        clock.tick()
        events = _say(client, kim, chat_id, "박현장 팀장에게 하차는 2번 게이트라고 보내 줘", sid)
        assert _card(events, "outreach_draft")["needs_approval"] is False
        assert _card(events, "outreach_sent")["outcome"] == "accepted"
        last = ok(client.get(f"{url}/outreach/threads/{people['박현장']}", headers=kim))["messages"][-1]
        assert (last["id"], last["origin"], last["send_mode"], last["approved_by"]) == (next_id, "agent", "delegated", None)

        # ── 9. 받는 통화(가짜 Ring) → [상대 발신] · 「확인할 보고 1」 ──────────────
        liner.push(reply(json.dumps({"summary_ko": "박현장 팀장이 철근 반입이 내일 오후 2시로 늦어진다고 알렸습니다.",
                                     "result": "철근 반입 지연 보고"}, ensure_ascii=False)))
        await _ring(session, SimulatedVoice([Ring(SENTINEL_DIGITS, clock.tick()),
                                    Say("peer", "철근 반입이 내일 오후 2시로 늦어집니다", t=2),
                                    Tool("report_from_contact", {"kind": "delay", "text": "철근 반입 내일 오후 2시로 지연",
                                                                 "quote": "철근 반입이 내일 오후 2시로 늦어집니다"}),
                                    Say("agent", "네 담당자에게 전하겠습니다", t=4), Hangup("peer")]))
        incoming = ok(client.get(f"{url}/outreach/calls?contact_id={people['박현장']}", headers=kim))[0]
        assert (incoming["direction"], incoming["origin"], incoming["caller_class"], incoming["status"]) == (
            "in", "peer", "contact", "completed")
        assert incoming["summary_ko"].startswith("박현장 팀장이")
        (report,) = ok(client.get(f"{url}/outreach/reports", headers=kim))
        assert (report["kind"], report["status"], report["quote_found"], report["call_id"]) == (
            "delay", "open", True, incoming["id"])
        assert ok(client.get(f"{url}/contacts", headers=kim))["reports_open"] == 1  # 「확인할 보고 1」

        # ── 10. 모르는 번호의 문자 → 「모르는 번호」 묶음 · 고정 안내 ───────────────
        # 고정 안내는 받는 범위 「모두」일 때만 나간다. 시험 모드라 그 가상 번호도 허용 번호에 넣는다.
        version = ok(client.get(NOTIFY, headers=admin))[0]["allow_numbers_version"]
        ok(client.patch(f"{NOTIFY}/{cid}", headers=admin, json={
            "inbound_mode": "all", "allow_numbers_add": [STRANGER], "allow_numbers_version": version}))
        fake_provider.inbox.append(_inbound("MGIN0003", STRANGER, "거기 현장 사무실 맞나요?", clock.tick()))
        with text_session.pinned(SimulatedText([Reply("문의 감사합니다. 일정은 내일 오전부터입니다.")])):
            await worker.tick(now=clock.tick())
            assert await inbox.drain(now=clock.tick()) == 1
        for other in (sid, other_sid):  # 어느 프로젝트 화면에서나 같은 묶음(프로젝트에 묶지 않음)
            (group,) = ok(client.get(f"/api/outreach/unknown?schedule_id={other}", headers=kim))
            assert (group["number_masked"], group["known"], group["messages"]) == ("010-****-0188", False, 2)
        lines = ok(client.get(f"/api/outreach/unknown/{group['peer_key']}", headers=kim))["lines"]
        assert [(x["direction"], x["message_kind"]) for x in lines] == [("in", "normal"), ("out", "notice")]
        assert lines[1]["text"] == "담당자가 확인 후 연락드리겠습니다."  # 모델 글이 아니라 고정 안내(일정 내용 없음)

        # ── 11. 다른 프로젝트로 바꾸면 주소록이 비어 있음 ─────────────────────
        assert ok(client.get(f"/api/schedules/{other_sid}/contacts", headers=kim)) == {
            "companies": [], "proposals_pending": 0, "reports_open": 0}

        # ── 12. 개발 콘솔 ─────────────────────────────────────────────
        console = Console(client, admin)
        grid = console("get", "/catalog")["outreach_grid"]
        assert grid["error"] is None and grid["connection_id"] == cid
        results: dict[str, tuple[bool, str | None]] = {}
        cells = [(f"{row['id']}@{col}", cell) for row in grid["rows"] for col, cell in row["cells"].items()]
        for rule, cell in [*cells, *[(case["id"], case) for case in grid["channel_only"]]]:
            if cell["runnable"]:  # [전부 돌리기]와 같다 — 한 칸씩 차례로, 칸마다 모래상자 자식 프로세스
                results[rule] = (console("post", f"/harness/{rule}/test")["passed"], cell["note_kind"])
        failed = {rule for rule, (passed, _) in results.items() if not passed}
        diverged = {rule for rule, (_, kind) in results.items() if kind == "diverged"}
        # 실패는 정확히 「하네스 갈라짐」 표시 세 칸뿐(S-13 언어 제안 · S-20 되풀이 통화) — 나머지 93칸은 통과
        assert failed == diverged == {"S-13@call_out", "S-13@call_in", "S-20@call_in"}, (failed, diverged)
        assert (len(results), len(results) - len(failed)) == (96, 93)

        listing = console("get", "/outreach")["items"]
        rows = {(item["kind"], item["id"]): item for item in listing}
        assert (rows[("message", blocked_id)]["status"], rows[("message", card["message_id"])]["send_mode"]) == (
            "blocked_test", "approved")
        assert rows[("message", next_id)]["send_mode"] == "delegated"
        assert (rows[("call", incoming["id"])]["direction"], rows[("call", incoming["id"])]["caller_class"]) == ("in", "contact")
        assert rows[("message", lines[0]["id"])]["caller_class"] == "unknown"
        gate_seen = {}
        for kind, row_id in (("message", blocked_id), ("message", card["message_id"]), ("message", next_id),
                             ("call", call["id"]), ("call", incoming["id"])):
            detail = console("get", f"/outreach/{kind}/{row_id}")
            gate_seen[(kind, row_id)] = [(t["harness"]["rule"], t["harness"]["verdict"]) for t in detail["timeline"]]
            assert detail["head"]["number_masked"].startswith("010-****-")
        assert gate_seen[("message", blocked_id)] == [("test_mode", "blocked")]
        assert ("channel_choice", "allowed") in gate_seen[("message", card["message_id"])]
        assert gate_seen[("call", call["id"])][:3] == [("channel_choice", "allowed"), ("delivery", "allowed"),
                                                      ("recheck_before_dial", "allowed")]
        assert gate_seen[("call", incoming["id"])][0] == ("admission", "allowed")
        assert console("get", f"/outreach/message/{card['message_id']}")["head"]["approved_by"] == "김공정"

        health = console("get", "/health")["notify"]
        assert health["connected"] and health["test_mode"] and health["inbound_mode"] == "all"
        assert [s["outcome"] for s in health["last_diagnosis"]["steps"]][-1] == "failed"  # 진단 칸이 채워짐
        assert health["voice"]["provider"] == "google"
        usage = console("get", "/usage")["outreach"]
        # 문자 5 = 체크인 · 자동 답(사람이 보내면 kind normal) · 대화 초안 · 위임 · 고정 안내(자동 답 칸에 드는 것은 이것 하나)
        assert (usage["sms"], usage["auto_replies"]) == (5, 1)
        assert (usage["calls"]["calls_placed"], usage["calls"]["calls_answered"]) == (1, 1)
        assert {m["kind"]: m["count"] for m in usage["calls"]["models"]}["summary"] == 2
        assert [leak for blob in console.texts for leak in leaks(blob)] == []  # 콘솔 응답 전체에 전체 번호·키 없음

    # ── 끝: DB 와 로그를 한 번 더 훑는다 ─────────────────────────────
    session.expire_all()
    assert _sweep_db(session) == {}
    assert_clean(caplog, KAT_ACCOUNT)  # Account ID 도 로그에 없다
